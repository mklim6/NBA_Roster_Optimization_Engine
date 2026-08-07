from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DATA = ROOT / "app_data"
OUTPUTS = ROOT / "outputs"
DEFAULT_SCENARIO_DIR = APP_DATA / "league_scenarios"
SELF_TEST_REPORT = (
    OUTPUTS / "league_scenario_store_v1_self_test.json"
)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    VALIDATION_REVISION,
    RuntimeData,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from mutable_league_state_v1 import (  # noqa: E402
    STATE_VERSION,
    LeagueState,
    StateMutationError,
    StateSnapshot,
    TeamFinancialState,
    TransactionRecord,
    apply_passed_trade,
    create_league_state,
    find_pass_player_trade,
    reset_league_state,
    undo_last_trade,
    validate_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    StateRuntimeAdapterError,
    build_state_runtime,
)


SCENARIO_SCHEMA_VERSION = (
    "league-scenario-store-v1-2026-08-07"
)
CHECKSUM_ALGORITHM = "sha256"
MAX_SCENARIO_BYTES = 25 * 1024 * 1024
MAX_NAME_LENGTH = 80
MAX_NOTES_LENGTH = 4000


class ScenarioStoreError(RuntimeError):
    """Base exception for persistent scenario operations."""


class ScenarioExistsError(ScenarioStoreError):
    """Raised when a scenario would overwrite an existing file."""


class ScenarioIntegrityError(ScenarioStoreError):
    """Raised when a scenario checksum does not match."""


class ScenarioCompatibilityError(ScenarioStoreError):
    """Raised when a scenario cannot be used by this release."""


class ScenarioValidationError(ScenarioStoreError):
    """Raised when a decoded league state is internally invalid."""


@dataclass(frozen=True)
class ScenarioSummary:
    name: str
    slug: str
    path: str
    saved_at_utc: str
    state_revision: int
    transaction_count: int
    player_count: int
    draft_right_count: int
    notes: str
    valid: bool
    error: str = ""


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def utc_now_text() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_scenario_name(name: Any) -> str:
    text = clean_text(name)

    if not text:
        raise ScenarioValidationError(
            "A scenario name is required."
        )

    if len(text) > MAX_NAME_LENGTH:
        raise ScenarioValidationError(
            f"Scenario names cannot exceed "
            f"{MAX_NAME_LENGTH} characters."
        )

    if any(ord(character) < 32 for character in text):
        raise ScenarioValidationError(
            "Scenario names cannot contain control characters."
        )

    return text


def validate_notes(notes: Any) -> str:
    text = clean_text(notes)

    if len(text) > MAX_NOTES_LENGTH:
        raise ScenarioValidationError(
            f"Scenario notes cannot exceed "
            f"{MAX_NOTES_LENGTH} characters."
        )

    return text


def scenario_slug(name: Any) -> str:
    text = validate_scenario_name(name)
    normalized = unicodedata.normalize(
        "NFKD",
        text,
    )
    ascii_text = normalized.encode(
        "ascii",
        "ignore",
    ).decode("ascii")
    slug = re.sub(
        r"[^A-Za-z0-9]+",
        "-",
        ascii_text,
    ).strip("-").lower()

    if not slug:
        slug = "scenario"

    return slug[:80]


def scenario_path_for_name(
    name: Any,
    directory: Path = DEFAULT_SCENARIO_DIR,
) -> Path:
    root = Path(directory).resolve()
    slug = scenario_slug(name)
    candidate = (root / f"{slug}.json").resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ScenarioValidationError(
            "The scenario path escaped the scenario directory."
        ) from exc

    return candidate


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def payload_checksum(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()


def signed_document(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **payload,
        "integrity": {
            "algorithm": CHECKSUM_ALGORITHM,
            "payload_sha256": payload_checksum(payload),
        },
    }


def verify_document_integrity(
    document: dict[str, Any],
) -> dict[str, Any]:
    integrity = document.get("integrity")

    if not isinstance(integrity, dict):
        raise ScenarioIntegrityError(
            "The scenario does not contain an integrity record."
        )

    algorithm = clean_text(
        integrity.get("algorithm")
    ).lower()
    expected = clean_text(
        integrity.get("payload_sha256")
    ).lower()

    if algorithm != CHECKSUM_ALGORITHM:
        raise ScenarioIntegrityError(
            f"Unsupported integrity algorithm: "
            f"{algorithm or '<missing>'}."
        )

    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ScenarioIntegrityError(
            "The scenario checksum is malformed."
        )

    payload = {
        key: value
        for key, value in document.items()
        if key != "integrity"
    }
    observed = payload_checksum(payload)

    if not hmac.compare_digest(expected, observed):
        raise ScenarioIntegrityError(
            "The scenario checksum does not match its contents."
        )

    return payload


def financial_to_payload(
    value: TeamFinancialState,
) -> dict[str, Any]:
    return asdict(value)


def financial_from_payload(
    value: Any,
) -> TeamFinancialState:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            "A team financial record is not an object."
        )

    required = {
        "team_abbreviation",
        "team_salary",
        "apron_salary",
        "standard_contract_count",
        "two_way_contract_count",
        "hard_cap_active",
        "hard_cap_level",
    }
    missing = required.difference(value)

    if missing:
        raise ScenarioValidationError(
            "A team financial record is missing: "
            + ", ".join(sorted(missing))
        )

    return TeamFinancialState(
        team_abbreviation=normalize_team(
            value["team_abbreviation"]
        ),
        team_salary=(
            None
            if value["team_salary"] is None
            else float(value["team_salary"])
        ),
        apron_salary=(
            None
            if value["apron_salary"] is None
            else float(value["apron_salary"])
        ),
        standard_contract_count=(
            None
            if value["standard_contract_count"] is None
            else int(value["standard_contract_count"])
        ),
        two_way_contract_count=(
            None
            if value["two_way_contract_count"] is None
            else int(value["two_way_contract_count"])
        ),
        hard_cap_active=(
            None
            if value["hard_cap_active"] is None
            else bool(value["hard_cap_active"])
        ),
        hard_cap_level=(
            clean_text(value["hard_cap_level"]).lower()
            or "none"
        ),
    )


def financial_map_to_payload(
    values: dict[str, TeamFinancialState],
) -> dict[str, dict[str, Any]]:
    return {
        team: financial_to_payload(value)
        for team, value in sorted(values.items())
    }


def financial_map_from_payload(
    value: Any,
) -> dict[str, TeamFinancialState]:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            "Team financials are not an object."
        )

    result: dict[str, TeamFinancialState] = {}

    for raw_team, raw_financial in value.items():
        team = normalize_team(raw_team)
        financial = financial_from_payload(
            raw_financial
        )

        if financial.team_abbreviation != team:
            raise ScenarioValidationError(
                f"Team financial key {team} does not match "
                f"record {financial.team_abbreviation}."
            )

        if team in result:
            raise ScenarioValidationError(
                f"Duplicate team financial record: {team}."
            )

        result[team] = financial

    return result


def snapshot_to_payload(
    snapshot: StateSnapshot,
) -> dict[str, Any]:
    return {
        "player_team_by_id": dict(
            sorted(snapshot.player_team_by_id.items())
        ),
        "pick_team_by_id": dict(
            sorted(snapshot.pick_team_by_id.items())
        ),
        "team_financials": financial_map_to_payload(
            snapshot.team_financials
        ),
        "acquired_player_ids": sorted(
            snapshot.acquired_player_ids
        ),
    }


def normalized_string_map(
    value: Any,
    *,
    key_kind: str,
    owner_kind: str,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            f"{key_kind} ownership is not an object."
        )

    result: dict[str, str] = {}

    for raw_key, raw_owner in value.items():
        key = (
            normalize_player_id(raw_key)
            if key_kind == "player"
            else clean_text(raw_key)
        )
        owner = normalize_team(raw_owner)

        if not key:
            raise ScenarioValidationError(
                f"A {key_kind} ownership key is blank."
            )

        if key in result:
            raise ScenarioValidationError(
                f"Duplicate {key_kind} ownership key: {key}."
            )

        if owner_kind == "required" and not owner:
            raise ScenarioValidationError(
                f"{key_kind.title()} {key} has no owner."
            )

        result[key] = owner

    return result


def snapshot_from_payload(
    value: Any,
) -> StateSnapshot:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            "A state snapshot is not an object."
        )

    required = {
        "player_team_by_id",
        "pick_team_by_id",
        "team_financials",
        "acquired_player_ids",
    }
    missing = required.difference(value)

    if missing:
        raise ScenarioValidationError(
            "A state snapshot is missing: "
            + ", ".join(sorted(missing))
        )

    acquired = value["acquired_player_ids"]
    if not isinstance(acquired, list):
        raise ScenarioValidationError(
            "A snapshot acquired-player list is invalid."
        )

    return StateSnapshot(
        player_team_by_id=normalized_string_map(
            value["player_team_by_id"],
            key_kind="player",
            owner_kind="optional",
        ),
        pick_team_by_id=normalized_string_map(
            value["pick_team_by_id"],
            key_kind="draft right",
            owner_kind="required",
        ),
        team_financials=financial_map_from_payload(
            value["team_financials"]
        ),
        acquired_player_ids={
            normalize_player_id(player_id)
            for player_id in acquired
            if normalize_player_id(player_id)
        },
    )


def transaction_to_payload(
    record: TransactionRecord,
) -> dict[str, Any]:
    return {
        "transaction_id": record.transaction_id,
        "state_revision": record.state_revision,
        "trade_date": record.trade_date,
        "team_a": record.team_a,
        "team_b": record.team_b,
        "team_a_player_ids": list(
            record.team_a_player_ids
        ),
        "team_b_player_ids": list(
            record.team_b_player_ids
        ),
        "team_a_pick_right_ids": list(
            record.team_a_pick_right_ids
        ),
        "team_b_pick_right_ids": list(
            record.team_b_pick_right_ids
        ),
        "team_a_before": financial_to_payload(
            record.team_a_before
        ),
        "team_a_after": financial_to_payload(
            record.team_a_after
        ),
        "team_b_before": financial_to_payload(
            record.team_b_before
        ),
        "team_b_after": financial_to_payload(
            record.team_b_after
        ),
        "evaluation_status": record.evaluation_status,
    }


def normalized_id_tuple(
    value: Any,
    *,
    player: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ScenarioValidationError(
            "A transaction asset list is invalid."
        )

    normalized = tuple(
        (
            normalize_player_id(item)
            if player
            else clean_text(item)
        )
        for item in value
    )

    if any(not item for item in normalized):
        raise ScenarioValidationError(
            "A transaction contains a blank asset ID."
        )

    if len(normalized) != len(set(normalized)):
        raise ScenarioValidationError(
            "A transaction contains a duplicate asset ID."
        )

    return normalized


def transaction_from_payload(
    value: Any,
) -> TransactionRecord:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            "A transaction record is not an object."
        )

    required = {
        "transaction_id",
        "state_revision",
        "trade_date",
        "team_a",
        "team_b",
        "team_a_player_ids",
        "team_b_player_ids",
        "team_a_pick_right_ids",
        "team_b_pick_right_ids",
        "team_a_before",
        "team_a_after",
        "team_b_before",
        "team_b_after",
        "evaluation_status",
    }
    missing = required.difference(value)

    if missing:
        raise ScenarioValidationError(
            "A transaction record is missing: "
            + ", ".join(sorted(missing))
        )

    return TransactionRecord(
        transaction_id=clean_text(
            value["transaction_id"]
        ),
        state_revision=int(value["state_revision"]),
        trade_date=clean_text(value["trade_date"]),
        team_a=normalize_team(value["team_a"]),
        team_b=normalize_team(value["team_b"]),
        team_a_player_ids=normalized_id_tuple(
            value["team_a_player_ids"],
            player=True,
        ),
        team_b_player_ids=normalized_id_tuple(
            value["team_b_player_ids"],
            player=True,
        ),
        team_a_pick_right_ids=normalized_id_tuple(
            value["team_a_pick_right_ids"],
            player=False,
        ),
        team_b_pick_right_ids=normalized_id_tuple(
            value["team_b_pick_right_ids"],
            player=False,
        ),
        team_a_before=financial_from_payload(
            value["team_a_before"]
        ),
        team_a_after=financial_from_payload(
            value["team_a_after"]
        ),
        team_b_before=financial_from_payload(
            value["team_b_before"]
        ),
        team_b_after=financial_from_payload(
            value["team_b_after"]
        ),
        evaluation_status=clean_text(
            value["evaluation_status"]
        ).lower(),
    )


def state_to_payload(
    state: LeagueState,
) -> dict[str, Any]:
    if state.initial_snapshot is None:
        raise ScenarioValidationError(
            "League state does not contain an initial snapshot."
        )

    return {
        "state_version": state.state_version,
        "engine_validation_revision": (
            state.engine_validation_revision
        ),
        "state_revision": state.state_revision,
        "player_team_by_id": dict(
            sorted(state.player_team_by_id.items())
        ),
        "pick_team_by_id": dict(
            sorted(state.pick_team_by_id.items())
        ),
        "team_financials": financial_map_to_payload(
            state.team_financials
        ),
        "acquired_player_ids": sorted(
            state.acquired_player_ids
        ),
        "transaction_history": [
            transaction_to_payload(record)
            for record in state.transaction_history
        ],
        "undo_stack": [
            snapshot_to_payload(snapshot)
            for snapshot in state.undo_stack
        ],
        "initial_snapshot": snapshot_to_payload(
            state.initial_snapshot
        ),
    }


def state_from_payload(
    value: Any,
) -> LeagueState:
    if not isinstance(value, dict):
        raise ScenarioValidationError(
            "The stored league state is not an object."
        )

    required = {
        "state_version",
        "engine_validation_revision",
        "state_revision",
        "player_team_by_id",
        "pick_team_by_id",
        "team_financials",
        "acquired_player_ids",
        "transaction_history",
        "undo_stack",
        "initial_snapshot",
    }
    missing = required.difference(value)

    if missing:
        raise ScenarioValidationError(
            "The stored league state is missing: "
            + ", ".join(sorted(missing))
        )

    history = value["transaction_history"]
    undo_stack = value["undo_stack"]
    acquired = value["acquired_player_ids"]

    if not isinstance(history, list):
        raise ScenarioValidationError(
            "Transaction history is not a list."
        )

    if not isinstance(undo_stack, list):
        raise ScenarioValidationError(
            "The undo stack is not a list."
        )

    if not isinstance(acquired, list):
        raise ScenarioValidationError(
            "The acquired-player collection is not a list."
        )

    return LeagueState(
        state_version=clean_text(
            value["state_version"]
        ),
        engine_validation_revision=clean_text(
            value["engine_validation_revision"]
        ),
        state_revision=int(
            value["state_revision"]
        ),
        player_team_by_id=normalized_string_map(
            value["player_team_by_id"],
            key_kind="player",
            owner_kind="optional",
        ),
        pick_team_by_id=normalized_string_map(
            value["pick_team_by_id"],
            key_kind="draft right",
            owner_kind="required",
        ),
        team_financials=financial_map_from_payload(
            value["team_financials"]
        ),
        acquired_player_ids={
            normalize_player_id(player_id)
            for player_id in acquired
            if normalize_player_id(player_id)
        },
        transaction_history=[
            transaction_from_payload(record)
            for record in history
        ],
        undo_stack=[
            snapshot_from_payload(snapshot)
            for snapshot in undo_stack
        ],
        initial_snapshot=snapshot_from_payload(
            value["initial_snapshot"]
        ),
    )


def validate_history(
    state: LeagueState,
) -> dict[str, bool]:
    valid_transaction_ids = all(
        record.transaction_id
        == f"TXN-{index:04d}"
        for index, record in enumerate(
            state.transaction_history,
            start=1,
        )
    )
    valid_statuses = all(
        record.evaluation_status == "pass"
        for record in state.transaction_history
    )
    different_teams = all(
        record.team_a
        and record.team_b
        and record.team_a != record.team_b
        for record in state.transaction_history
    )
    financial_teams_match = all(
        record.team_a_before.team_abbreviation
        == record.team_a
        and record.team_a_after.team_abbreviation
        == record.team_a
        and record.team_b_before.team_abbreviation
        == record.team_b
        and record.team_b_after.team_abbreviation
        == record.team_b
        for record in state.transaction_history
    )
    revisions_increase = all(
        current.state_revision
        > previous.state_revision
        for previous, current in zip(
            state.transaction_history,
            state.transaction_history[1:],
        )
    )

    checks = {
        "transaction_ids_are_sequential": (
            valid_transaction_ids
        ),
        "all_transactions_are_passed": valid_statuses,
        "transaction_teams_are_distinct": different_teams,
        "transaction_financial_teams_match": (
            financial_teams_match
        ),
        "transaction_revisions_increase": (
            revisions_increase
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise ScenarioValidationError(
            "Stored transaction history is invalid: "
            + ", ".join(failed)
        )

    return checks


def validate_loaded_state(
    state: LeagueState,
    runtime: RuntimeData,
) -> dict[str, bool]:
    if state.state_version != STATE_VERSION:
        raise ScenarioCompatibilityError(
            f"Scenario state version {state.state_version!r} "
            f"does not match {STATE_VERSION!r}."
        )

    if (
        state.engine_validation_revision
        != VALIDATION_REVISION
    ):
        raise ScenarioCompatibilityError(
            "Scenario engine revision "
            f"{state.engine_validation_revision!r} does not "
            f"match {VALIDATION_REVISION!r}."
        )

    history_checks = validate_history(state)

    try:
        state_checks = validate_state(
            state,
            runtime,
        )
        build_state_runtime(
            runtime,
            state,
        )
    except (
        StateMutationError,
        StateRuntimeAdapterError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise ScenarioValidationError(
            f"The stored league state is invalid: {exc}"
        ) from exc

    return {
        **{
            f"state_{name}": passed
            for name, passed in state_checks.items()
        },
        **{
            f"history_{name}": passed
            for name, passed in history_checks.items()
        },
        "runtime_rebuild_passed": True,
    }


def build_scenario_payload(
    *,
    state: LeagueState,
    runtime: RuntimeData,
    name: Any,
    notes: Any = "",
    saved_at_utc: str | None = None,
) -> dict[str, Any]:
    validated_name = validate_scenario_name(name)
    validated_notes = validate_notes(notes)
    validate_loaded_state(state, runtime)

    return {
        "scenario_schema_version": (
            SCENARIO_SCHEMA_VERSION
        ),
        "name": validated_name,
        "slug": scenario_slug(validated_name),
        "notes": validated_notes,
        "saved_at_utc": (
            saved_at_utc or utc_now_text()
        ),
        "state_summary": {
            "state_revision": state.state_revision,
            "transaction_count": len(
                state.transaction_history
            ),
            "player_count": len(
                state.player_team_by_id
            ),
            "draft_right_count": len(
                state.pick_team_by_id
            ),
            "team_count": len(
                state.team_financials
            ),
        },
        "league_state": state_to_payload(state),
    }


def atomic_write_document(
    path: Path,
    document: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.tmp"
    )
    data = json.dumps(
        document,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"

    try:
        with temporary.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_scenario(
    state: LeagueState,
    runtime: RuntimeData,
    name: Any,
    *,
    notes: Any = "",
    directory: Path = DEFAULT_SCENARIO_DIR,
    overwrite: bool = False,
) -> ScenarioSummary:
    payload = build_scenario_payload(
        state=state,
        runtime=runtime,
        name=name,
        notes=notes,
    )
    path = scenario_path_for_name(
        payload["name"],
        directory,
    )

    if path.exists() and not overwrite:
        raise ScenarioExistsError(
            f"Scenario {payload['name']!r} already exists."
        )

    atomic_write_document(
        path,
        signed_document(payload),
    )

    loaded_state, summary = load_scenario_file(
        path,
        runtime,
    )
    if (
        len(loaded_state.transaction_history)
        != len(state.transaction_history)
    ):
        raise ScenarioValidationError(
            "Saved transaction count did not round-trip."
        )

    return summary


def read_json_document(
    path: Path,
) -> dict[str, Any]:
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(
            f"Scenario file does not exist: {resolved}"
        )

    size = resolved.stat().st_size
    if size > MAX_SCENARIO_BYTES:
        raise ScenarioValidationError(
            f"Scenario file exceeds "
            f"{MAX_SCENARIO_BYTES} bytes."
        )

    try:
        document = json.loads(
            resolved.read_text(encoding="utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ScenarioValidationError(
            f"Scenario file is not valid UTF-8 JSON: {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise ScenarioValidationError(
            "Scenario document is not an object."
        )

    return document


def summary_from_payload(
    payload: dict[str, Any],
    path: Path,
    *,
    valid: bool,
    error: str = "",
) -> ScenarioSummary:
    state_summary = payload.get(
        "state_summary",
        {},
    )
    if not isinstance(state_summary, dict):
        state_summary = {}

    return ScenarioSummary(
        name=clean_text(payload.get("name")),
        slug=clean_text(payload.get("slug")),
        path=str(path.resolve()),
        saved_at_utc=clean_text(
            payload.get("saved_at_utc")
        ),
        state_revision=int(
            state_summary.get("state_revision", 0)
            or 0
        ),
        transaction_count=int(
            state_summary.get(
                "transaction_count",
                0,
            )
            or 0
        ),
        player_count=int(
            state_summary.get("player_count", 0)
            or 0
        ),
        draft_right_count=int(
            state_summary.get(
                "draft_right_count",
                0,
            )
            or 0
        ),
        notes=clean_text(payload.get("notes")),
        valid=valid,
        error=clean_text(error),
    )


def validate_payload_metadata(
    payload: dict[str, Any],
) -> None:
    schema = clean_text(
        payload.get("scenario_schema_version")
    )
    if schema != SCENARIO_SCHEMA_VERSION:
        raise ScenarioCompatibilityError(
            f"Scenario schema {schema!r} does not match "
            f"{SCENARIO_SCHEMA_VERSION!r}."
        )

    name = validate_scenario_name(
        payload.get("name")
    )
    expected_slug = scenario_slug(name)
    observed_slug = clean_text(
        payload.get("slug")
    )

    if observed_slug != expected_slug:
        raise ScenarioValidationError(
            f"Scenario slug {observed_slug!r} does not "
            f"match {expected_slug!r}."
        )

    validate_notes(payload.get("notes", ""))

    if not clean_text(payload.get("saved_at_utc")):
        raise ScenarioValidationError(
            "Scenario saved timestamp is missing."
        )

    if "league_state" not in payload:
        raise ScenarioValidationError(
            "Scenario league state is missing."
        )


def load_scenario_file(
    path: Path,
    runtime: RuntimeData,
) -> tuple[LeagueState, ScenarioSummary]:
    resolved = Path(path).resolve()
    document = read_json_document(resolved)
    payload = verify_document_integrity(document)
    validate_payload_metadata(payload)

    state = state_from_payload(
        payload["league_state"]
    )
    validate_loaded_state(
        state,
        runtime,
    )

    summary = summary_from_payload(
        payload,
        resolved,
        valid=True,
    )
    actual = {
        "state_revision": state.state_revision,
        "transaction_count": len(
            state.transaction_history
        ),
        "player_count": len(
            state.player_team_by_id
        ),
        "draft_right_count": len(
            state.pick_team_by_id
        ),
        "team_count": len(
            state.team_financials
        ),
    }
    stored = payload.get("state_summary")

    if stored != actual:
        raise ScenarioValidationError(
            "Scenario summary does not match the stored state."
        )

    return state, summary


def load_scenario(
    name: Any,
    runtime: RuntimeData,
    *,
    directory: Path = DEFAULT_SCENARIO_DIR,
) -> tuple[LeagueState, ScenarioSummary]:
    return load_scenario_file(
        scenario_path_for_name(name, directory),
        runtime,
    )


def list_scenarios(
    runtime: RuntimeData,
    *,
    directory: Path = DEFAULT_SCENARIO_DIR,
) -> list[ScenarioSummary]:
    root = Path(directory).resolve()
    if not root.exists():
        return []

    summaries: list[ScenarioSummary] = []

    for path in sorted(
        root.glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        try:
            _, summary = load_scenario_file(
                path,
                runtime,
            )
        except Exception as exc:
            payload: dict[str, Any] = {}

            try:
                document = read_json_document(path)
                payload = {
                    key: value
                    for key, value in document.items()
                    if key != "integrity"
                }
            except Exception:
                pass

            summary = summary_from_payload(
                payload,
                path,
                valid=False,
                error=str(exc),
            )

        summaries.append(summary)

    return summaries


def import_scenario_file(
    source_path: Path,
    runtime: RuntimeData,
    *,
    name: Any | None = None,
    notes: Any | None = None,
    directory: Path = DEFAULT_SCENARIO_DIR,
    overwrite: bool = False,
) -> ScenarioSummary:
    state, source_summary = load_scenario_file(
        source_path,
        runtime,
    )

    target_name = (
        validate_scenario_name(name)
        if name is not None
        else source_summary.name
    )
    target_notes = (
        validate_notes(notes)
        if notes is not None
        else source_summary.notes
    )

    return save_scenario(
        state,
        runtime,
        target_name,
        notes=target_notes,
        directory=directory,
        overwrite=overwrite,
    )


def delete_scenario(
    name: Any,
    *,
    directory: Path = DEFAULT_SCENARIO_DIR,
) -> Path:
    path = scenario_path_for_name(name, directory)

    if not path.exists():
        raise FileNotFoundError(
            f"Scenario does not exist: {path}"
        )

    path.unlink()
    return path


def operational_signature(
    state: LeagueState,
) -> dict[str, Any]:
    return {
        "state_version": state.state_version,
        "engine_validation_revision": (
            state.engine_validation_revision
        ),
        "state_revision": state.state_revision,
        "player_team_by_id": tuple(
            sorted(state.player_team_by_id.items())
        ),
        "pick_team_by_id": tuple(
            sorted(state.pick_team_by_id.items())
        ),
        "team_financials": tuple(
            (
                team,
                tuple(
                    sorted(asdict(value).items())
                ),
            )
            for team, value in sorted(
                state.team_financials.items()
            )
        ),
        "acquired_player_ids": tuple(
            sorted(state.acquired_player_ids)
        ),
        "transaction_history": tuple(
            json.dumps(
                transaction_to_payload(record),
                sort_keys=True,
            )
            for record in state.transaction_history
        ),
        "undo_stack": tuple(
            json.dumps(
                snapshot_to_payload(snapshot),
                sort_keys=True,
            )
            for snapshot in state.undo_stack
        ),
        "initial_snapshot": json.dumps(
            snapshot_to_payload(
                state.initial_snapshot
            )
            if state.initial_snapshot is not None
            else None,
            sort_keys=True,
        ),
    }


def write_tampered_document(
    source: Path,
    target: Path,
    mutate: Any,
    *,
    resign: bool,
) -> None:
    document = read_json_document(source)
    payload = {
        key: copy.deepcopy(value)
        for key, value in document.items()
        if key != "integrity"
    }
    mutate(payload)
    output = (
        signed_document(payload)
        if resign
        else {
            **payload,
            "integrity": document["integrity"],
        }
    )
    atomic_write_document(target, output)


def run_self_test() -> dict[str, Any]:
    runtime = load_runtime_data()
    state = create_league_state(runtime)
    request, result = find_pass_player_trade(runtime)
    apply_passed_trade(
        state,
        runtime,
        request,
        result,
    )
    source_signature = operational_signature(state)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    OUTPUTS.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="scenario_store_v1_",
        dir=OUTPUTS,
    ) as temporary:
        root = Path(temporary)
        primary_name = "BKN-MIL Test Universe"
        summary = save_scenario(
            state,
            runtime,
            primary_name,
            notes="Self-test transaction universe.",
            directory=root,
        )
        primary_path = Path(summary.path)

        checks["scenario_file_created"] = (
            primary_path.exists()
        )
        checks["scenario_name_slugged"] = (
            primary_path.name
            == "bkn-mil-test-universe.json"
        )
        checks["scenario_summary_valid"] = (
            summary.valid
            and summary.transaction_count == 1
        )

        loaded, loaded_summary = load_scenario(
            primary_name,
            runtime,
            directory=root,
        )
        checks["state_round_trip_exact"] = (
            operational_signature(loaded)
            == source_signature
        )
        checks["loaded_summary_valid"] = (
            loaded_summary.valid
        )
        checks["runtime_rebuild_after_load"] = bool(
            build_state_runtime(
                runtime,
                loaded,
            )
        )

        removed = undo_last_trade(
            loaded,
            runtime,
        )
        checks["loaded_undo_stack_operates"] = (
            removed.transaction_id == "TXN-0001"
            and not loaded.transaction_history
            and not loaded.undo_stack
        )

        loaded_again, _ = load_scenario(
            primary_name,
            runtime,
            directory=root,
        )
        reset_league_state(
            loaded_again,
            runtime,
        )
        checks["loaded_reset_operates"] = (
            not loaded_again.transaction_history
            and not loaded_again.undo_stack
            and all(
                validate_state(
                    loaded_again,
                    runtime,
                ).values()
            )
        )

        overwrite_blocked = False
        try:
            save_scenario(
                state,
                runtime,
                primary_name,
                directory=root,
            )
        except ScenarioExistsError:
            overwrite_blocked = True
        checks["overwrite_blocked_by_default"] = (
            overwrite_blocked
        )

        replaced = save_scenario(
            state,
            runtime,
            primary_name,
            notes="Updated self-test notes.",
            directory=root,
            overwrite=True,
        )
        checks["explicit_overwrite_succeeds"] = (
            replaced.notes
            == "Updated self-test notes."
        )

        listed = list_scenarios(
            runtime,
            directory=root,
        )
        checks["scenario_listing_succeeds"] = (
            len(listed) == 1
            and listed[0].valid
        )

        checksum_path = (
            root / "tampered-checksum.json"
        )

        def mutate_checksum(
            payload: dict[str, Any],
        ) -> None:
            ownership = payload[
                "league_state"
            ]["player_team_by_id"]
            player_id = next(iter(ownership))
            ownership[player_id] = "XXX"

        write_tampered_document(
            primary_path,
            checksum_path,
            mutate_checksum,
            resign=False,
        )
        checksum_blocked = False
        try:
            load_scenario_file(
                checksum_path,
                runtime,
            )
        except ScenarioIntegrityError:
            checksum_blocked = True
        checks["checksum_tampering_blocked"] = (
            checksum_blocked
        )

        invalid_state_path = (
            root / "tampered-resigned.json"
        )
        write_tampered_document(
            primary_path,
            invalid_state_path,
            mutate_checksum,
            resign=True,
        )
        invalid_state_blocked = False
        try:
            load_scenario_file(
                invalid_state_path,
                runtime,
            )
        except ScenarioValidationError:
            invalid_state_blocked = True
        checks["resigned_invalid_state_blocked"] = (
            invalid_state_blocked
        )

        schema_path = (
            root / "incompatible-schema.json"
        )

        def mutate_schema(
            payload: dict[str, Any],
        ) -> None:
            payload["scenario_schema_version"] = (
                "unsupported-scenario-schema"
            )

        write_tampered_document(
            primary_path,
            schema_path,
            mutate_schema,
            resign=True,
        )
        schema_blocked = False
        try:
            load_scenario_file(
                schema_path,
                runtime,
            )
        except ScenarioCompatibilityError:
            schema_blocked = True
        checks["schema_mismatch_blocked"] = (
            schema_blocked
        )

        import_root = root / "imports"
        imported = import_scenario_file(
            primary_path,
            runtime,
            name="Imported Universe",
            directory=import_root,
        )
        imported_state, _ = load_scenario(
            "Imported Universe",
            runtime,
            directory=import_root,
        )
        checks["scenario_import_round_trip"] = (
            imported.valid
            and operational_signature(
                imported_state
            )
            == source_signature
        )

        deleted_path = delete_scenario(
            "Imported Universe",
            directory=import_root,
        )
        checks["scenario_delete_succeeds"] = (
            not deleted_path.exists()
        )

        temporary_files = [
            path.name
            for path in root.rglob("*.tmp")
        ]
        checks["no_atomic_temp_files_remain"] = (
            not temporary_files
        )

        details = {
            "saved_path": str(primary_path),
            "transaction_count": len(
                state.transaction_history
            ),
            "state_revision": state.state_revision,
            "listed_scenarios": [
                asdict(item)
                for item in listed
            ],
            "temporary_files": temporary_files,
        }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": SCENARIO_SCHEMA_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": details,
        "passed": not failed,
    }

    SELF_TEST_REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "League scenario store V1 self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--list",
        action="store_true",
    )
    args = parser.parse_args()

    runtime = load_runtime_data()

    if args.self_test:
        report = run_self_test()
        print(json.dumps(report, indent=2))
        print(
            "\nLEAGUE SCENARIO STORE V1 SELF-TEST PASSED"
        )
        return 0

    if args.list:
        print(
            json.dumps(
                [
                    asdict(summary)
                    for summary in list_scenarios(
                        runtime
                    )
                ],
                indent=2,
            )
        )
        return 0

    state = create_league_state(runtime)
    print(
        json.dumps(
            {
                "script": SCENARIO_SCHEMA_VERSION,
                "scenario_directory": str(
                    DEFAULT_SCENARIO_DIR
                ),
                "state_revision": state.state_revision,
                "transactions": len(
                    state.transaction_history
                ),
                "status": "initialized",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())