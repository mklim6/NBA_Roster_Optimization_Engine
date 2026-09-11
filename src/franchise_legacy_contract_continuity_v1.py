from __future__ import annotations

import csv
import hashlib
import html
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

LEGACY_CONTRACT_CONTINUITY_VERSION = (
    "franchise-legacy-contract-continuity-v1-2026-08-18"
)
ANCHOR_SEASON = "2026-27"
ANCHOR_LINEAGE = "anchor_2026_27_listed_contract_schedule"
FRANCHISE_TRANSACTION_LINEAGE = "franchise_transaction_contract"
CONTINUITY_ATTR = "franchise_legacy_contract_continuity_v1"
LINEAGE_ATTR = "franchise_contract_lineage_v1"
SCHEDULE_ATTR = "franchise_contract_salary_schedule_v1"
SOURCE_ATTR = "franchise_contract_schedule_source_v1"
MATCH_ATTR = "franchise_contract_schedule_match_v1"
ANCHOR_GUARANTEE_ATTR = "franchise_contract_anchor_guaranteed_remaining_v1"
CURRENT_SEASON_ATTR = "franchise_contract_schedule_current_season_v1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_CONTRACT_CANDIDATES = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "contracts"
    / "basketball_reference_player_contracts_2026_27_v2_clean.csv",
    PROJECT_ROOT
    / "data"
    / "raw"
    / "contracts"
    / "basketball_reference_player_contracts_2026_27.csv",
)
SEASON_COLUMNS = (
    ("2026-27", "salary_2026_27"),
    ("2027-28", "salary_2027_28"),
    ("2028-29", "salary_2028_29"),
    ("2029-30", "salary_2029_30"),
    ("2030-31", "salary_2030_31"),
    ("2031-32", "salary_2031_32"),
)
TEAM_ALIASES = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
}
NAME_ALIASES = {
    "aj green": "a j green",
    "aj johnson": "a j johnson",
    "aj lawson": "a j lawson",
    "cj mccollum": "c j mccollum",
    "dj carton": "d j carton",
    "gg jackson": "g g jackson",
    "gg jackson ii": "g g jackson",
    "kj martin": "k j martin",
    "pj tucker": "p j tucker",
    "pj washington": "p j washington",
    "rj barrett": "r j barrett",
    "ronald holland": "ron holland",
    "ron holland": "ron holland",
    "tj mcconnell": "t j mcconnell",
    # Basketball-Reference's frozen table carries a Cyrillic-looking character
    # in this name. Keep the alias explicit and source-specific.
    "egor demin": "egor d min",
}
MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "Å",
    "Ä",
    "Ð",
    "Ñ",
    "â",
    "ð",
    "�",
    "¼",
    "½",
)


class LegacyContractContinuityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyContractContinuityResult:
    version: str
    season_label: str
    source_path: str
    source_sha256: str
    seeded_player_ids: tuple[str, ...]
    aligned_player_ids: tuple[str, ...]
    authoritative_existing_player_ids: tuple[str, ...]
    normalized_rostered_contract_status_player_ids: tuple[str, ...]
    unresolved_player_ids: tuple[str, ...]
    unresolved_reasons: tuple[tuple[str, str], ...]

    @property
    def seeded_count(self) -> int:
        return len(self.seeded_player_ids)

    @property
    def aligned_count(self) -> int:
        return len(self.aligned_player_ids)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved_player_ids)


@dataclass(frozen=True)
class LegacyContractRolloverResult:
    version: str
    target_season: str
    rolled_player_ids: tuple[str, ...]
    skipped_non_anchor_player_ids: tuple[str, ...]

    @property
    def rolled_count(self) -> int:
        return len(self.rolled_player_ids)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    raw = _clean(value).upper()
    return TEAM_ALIASES.get(raw, raw)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _repair_mojibake(value: Any) -> str:
    current = html.unescape(_clean(value))
    for _ in range(2):
        candidates = [current]
        for encoding in ("latin-1", "cp1252"):
            try:
                candidates.append(current.encode(encoding).decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass

        def score(candidate: str) -> tuple[int, int, int]:
            return (
                sum(candidate.count(marker) for marker in MOJIBAKE_MARKERS),
                candidate.count("�"),
                abs(len(candidate) - len(current)),
            )

        current = min(candidates, key=score)
    return unicodedata.normalize("NFC", current)


def _normalize_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _repair_mojibake(value))
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = normalized.lower().replace("’", "'").replace("`", "'")
    normalized = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return NAME_ALIASES.get(normalized, normalized)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path() -> Path:
    for path in RAW_CONTRACT_CANDIDATES:
        if path.is_file():
            return path
    raise LegacyContractContinuityError(
        "Frozen 2026-27 raw contract schedule is unavailable. Checked: "
        + ", ".join(str(path) for path in RAW_CONTRACT_CANDIDATES)
    )


def _salary_schedule(row: dict[str, str]) -> dict[str, float]:
    schedule: dict[str, float] = {}
    seen_gap = False
    for season, column in SEASON_COLUMNS:
        value = _finite(row.get(column))
        if value is None or value <= 0.0:
            seen_gap = True
            continue
        if seen_gap:
            raise LegacyContractContinuityError(
                f"Non-contiguous listed salary schedule for {row.get('contract_player_name')!r}."
            )
        schedule[season] = float(value)
    return schedule


@lru_cache(maxsize=1)
def _contract_index() -> tuple[
    Path,
    str,
    dict[tuple[str, str], tuple[dict[str, Any], ...]],
    dict[str, tuple[dict[str, Any], ...]],
]:
    path = _source_path()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    by_name_team: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        name = _normalize_name(raw.get("contract_player_name"))
        team = _team(raw.get("contract_team_2026_27") or raw.get("contract_team_bref"))
        if not name:
            continue
        row = dict(raw)
        row["_normalized_name"] = name
        row["_normalized_team"] = team
        row["_salary_schedule"] = _salary_schedule(row)
        by_name_team.setdefault((name, team), []).append(row)
        by_name.setdefault(name, []).append(row)

    return (
        path,
        _sha256(path),
        {key: tuple(value) for key, value in by_name_team.items()},
        {key: tuple(value) for key, value in by_name.items()},
    )


def _row_for_player(player: Any, team_code: str) -> tuple[dict[str, Any] | None, str]:
    _, _, by_name_team, by_name = _contract_index()
    name = _normalize_name(getattr(player, "player_name", ""))
    team = _team(team_code)
    exact = by_name_team.get((name, team), ())
    if len(exact) == 1:
        return dict(exact[0]), "normalized_name_and_team"
    same_name = by_name.get(name, ())
    if len(same_name) == 1:
        return dict(same_name[0]), "unique_normalized_name"
    if not same_name:
        return None, "no_frozen_contract_schedule"
    return None, "ambiguous_frozen_contract_schedule"


def _schedule_from_contract(contract: Any) -> dict[str, float]:
    raw = getattr(contract, SCHEDULE_ATTR, None)
    if isinstance(raw, dict):
        out: dict[str, float] = {}
        for season, value in raw.items():
            amount = _finite(value)
            if _clean(season) and amount is not None and amount > 0.0:
                out[_clean(season)] = float(amount)
        return out
    if isinstance(raw, (list, tuple)):
        out = {}
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            amount = _finite(item[1])
            if _clean(item[0]) and amount is not None and amount > 0.0:
                out[_clean(item[0])] = float(amount)
        return out
    return {}


def _remaining_years(schedule: dict[str, float], season_label: str) -> int | None:
    seasons = [season for season, _ in SEASON_COLUMNS]
    if season_label not in seasons:
        return None
    start = seasons.index(season_label)
    remaining = 0
    for season in seasons[start:]:
        if schedule.get(season, 0.0) <= 0.0:
            break
        remaining += 1
    return remaining or None


def _is_generated(player: Any) -> bool:
    if bool(getattr(player, "synthetic", False)):
        return True
    if bool(getattr(player, "generated_prospect", False)):
        return True
    if _clean(getattr(player, "draft_class_id", "")).upper().startswith("DRAFT-"):
        return True
    source = _clean(getattr(player, "rating_source", "")).lower()
    return "generated-draft" in source or "generated rookie" in source


def _contract_status(contract: Any) -> str:
    return _clean(getattr(contract, "status", "")).lower().replace("-", "_")


def _attach_anchor_metadata(
    contract: Any,
    *,
    schedule: dict[str, float],
    source_path: Path,
    match_method: str,
    guaranteed_remaining: float | None,
    season_label: str,
) -> None:
    setattr(contract, LINEAGE_ATTR, ANCHOR_LINEAGE)
    setattr(contract, SCHEDULE_ATTR, dict(schedule))
    setattr(contract, SOURCE_ATTR, str(source_path.relative_to(PROJECT_ROOT)))
    setattr(contract, MATCH_ATTR, match_method)
    setattr(contract, ANCHOR_GUARANTEE_ATTR, guaranteed_remaining)
    setattr(contract, CURRENT_SEASON_ATTR, season_label)


def prepare_legacy_contracts_for_closeout(
    state: Any,
    *,
    season_label: str | None = None,
) -> LegacyContractContinuityResult:
    season = _clean(
        season_label
        or getattr(getattr(state, "settings", None), "season_label", "")
    )
    if not season:
        raise LegacyContractContinuityError("Simulation season label is unavailable.")

    path, source_hash, _, _ = _contract_index()
    seeded: list[str] = []
    aligned: list[str] = []
    authoritative_existing: list[str] = []
    normalized_rostered_contract_status: list[str] = []
    unresolved: list[str] = []
    unresolved_reasons: list[tuple[str, str]] = []

    teams = getattr(state, "teams", {}) or {}
    players = getattr(state, "players", {}) or {}
    for raw_team, team_state in sorted(teams.items(), key=lambda item: str(item[0])):
        team = _team(raw_team)
        for raw_player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
            player_id = _clean(raw_player_id)
            player = players.get(player_id)
            if player is None or _is_generated(player):
                continue
            contract = getattr(player, "contract", None)
            if contract is None:
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, "rostered_player_has_no_contract_state"))
                continue

            contract_status = _contract_status(contract)
            if contract_status not in {"under_contract", "free_agent_pool", "free_agent"}:
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, f"rostered_contract_status_unhandled:{contract_status or 'blank'}"))
                continue

            lineage = _clean(getattr(contract, LINEAGE_ATTR, ""))
            if lineage == FRANCHISE_TRANSACTION_LINEAGE:
                authoritative_existing.append(player_id)
                continue

            schedule = _schedule_from_contract(contract)
            if lineage == ANCHOR_LINEAGE and schedule:
                expected_salary = schedule.get(season)
                expected_years = _remaining_years(schedule, season)
                current_years = _int_or_none(getattr(contract, "years_remaining", None))
                current_salary = _finite(getattr(contract, "salary", None))
                if expected_salary is None or expected_years is None:
                    raise LegacyContractContinuityError(
                        f"Anchor contract {player_id} has no listed salary for live season {season}."
                    )
                if current_years != expected_years:
                    raise LegacyContractContinuityError(
                        f"Anchor contract year drift for {player_id}: expected {expected_years}, got {current_years}."
                    )
                if current_salary is None or not math.isclose(
                    current_salary,
                    expected_salary,
                    rel_tol=0.0,
                    abs_tol=0.01,
                ):
                    raise LegacyContractContinuityError(
                        f"Anchor contract salary drift for {player_id}: expected {expected_salary}, got {current_salary}."
                    )
                setattr(contract, CURRENT_SEASON_ATTR, season)
                aligned.append(player_id)
                continue

            current_years = _int_or_none(getattr(contract, "years_remaining", None))
            if current_years is not None:
                if contract_status != "under_contract":
                    unresolved.append(player_id)
                    unresolved_reasons.append((player_id, f"rostered_contract_status_conflicts_with_explicit_years:{contract_status}"))
                else:
                    authoritative_existing.append(player_id)
                continue

            # Only the frozen anchor season may recover a previously omitted
            # legacy duration. Future unknown contracts may represent a later
            # transaction and remain unresolved rather than being backfilled.
            if season != ANCHOR_SEASON:
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, "future_unknown_contract_not_backfilled_from_anchor"))
                continue

            row, match_method = _row_for_player(player, team)
            if row is None:
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, match_method))
                continue

            schedule = dict(row.get("_salary_schedule", {}) or {})
            expected_salary = schedule.get(ANCHOR_SEASON)
            expected_years = _remaining_years(schedule, ANCHOR_SEASON)
            if expected_salary is None or expected_years is None:
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, "frozen_schedule_has_no_anchor_salary"))
                continue

            current_salary = _finite(getattr(contract, "salary", None))
            if current_salary is not None and not math.isclose(
                current_salary,
                expected_salary,
                rel_tol=0.0,
                abs_tol=0.01,
            ):
                unresolved.append(player_id)
                unresolved_reasons.append((player_id, "current_salary_conflicts_with_frozen_schedule"))
                continue

            if contract_status != "under_contract":
                # Roster membership plus an exact frozen 2026-27 contract row is
                # sufficient to repair a stale free-agent contract status. No
                # such repair is attempted without source-backed salary terms.
                contract.status = "under_contract"
                normalized_rostered_contract_status.append(player_id)
            contract.salary = float(expected_salary)
            contract.years_remaining = int(expected_years)
            guaranteed_remaining = _finite(row.get("guaranteed_remaining"))
            _attach_anchor_metadata(
                contract,
                schedule=schedule,
                source_path=path,
                match_method=match_method,
                guaranteed_remaining=guaranteed_remaining,
                season_label=ANCHOR_SEASON,
            )
            seeded.append(player_id)

    setattr(
        state,
        CONTINUITY_ATTR,
        {
            "version": LEGACY_CONTRACT_CONTINUITY_VERSION,
            "season_label": season,
            "source": str(path.relative_to(PROJECT_ROOT)),
            "source_sha256": source_hash,
            "seeded_player_ids": tuple(sorted(seeded)),
            "aligned_player_ids": tuple(sorted(aligned)),
            "authoritative_existing_player_ids": tuple(sorted(authoritative_existing)),
            "normalized_rostered_contract_status_player_ids": tuple(sorted(normalized_rostered_contract_status)),
            "unresolved_player_ids": tuple(sorted(unresolved)),
            "unresolved_reasons": tuple(sorted(unresolved_reasons)),
        },
    )
    return LegacyContractContinuityResult(
        version=LEGACY_CONTRACT_CONTINUITY_VERSION,
        season_label=season,
        source_path=str(path),
        source_sha256=source_hash,
        seeded_player_ids=tuple(sorted(seeded)),
        aligned_player_ids=tuple(sorted(aligned)),
        authoritative_existing_player_ids=tuple(sorted(authoritative_existing)),
        normalized_rostered_contract_status_player_ids=tuple(sorted(normalized_rostered_contract_status)),
        unresolved_player_ids=tuple(sorted(unresolved)),
        unresolved_reasons=tuple(sorted(unresolved_reasons)),
    )


def roll_legacy_contracts_to_target_season(
    state: Any,
    target_season: str,
) -> LegacyContractRolloverResult:
    target = _clean(target_season)
    rolled: list[str] = []
    skipped: list[str] = []
    for player_id, player in sorted(
        (getattr(state, "players", {}) or {}).items(),
        key=lambda item: str(item[0]),
    ):
        contract = getattr(player, "contract", None)
        if contract is None or _contract_status(contract) != "under_contract":
            continue
        if _clean(getattr(contract, LINEAGE_ATTR, "")) != ANCHOR_LINEAGE:
            skipped.append(_clean(player_id))
            continue
        schedule = _schedule_from_contract(contract)
        expected_salary = schedule.get(target)
        expected_years = _remaining_years(schedule, target)
        if expected_salary is None or expected_years is None:
            raise LegacyContractContinuityError(
                f"Anchor contract {_clean(player_id)} remained active without a listed salary for {target}."
            )
        current_years = _int_or_none(getattr(contract, "years_remaining", None))
        if current_years != expected_years:
            raise LegacyContractContinuityError(
                f"Anchor contract {_clean(player_id)} target-year drift: expected {expected_years}, got {current_years}."
            )
        contract.salary = float(expected_salary)
        setattr(contract, CURRENT_SEASON_ATTR, target)
        rolled.append(_clean(player_id))

    return LegacyContractRolloverResult(
        version=LEGACY_CONTRACT_CONTINUITY_VERSION,
        target_season=target,
        rolled_player_ids=tuple(sorted(rolled)),
        skipped_non_anchor_player_ids=tuple(sorted(skipped)),
    )


def mark_contract_as_franchise_transaction(
    contract: Any,
    *,
    season_label: str,
    source: str,
) -> None:
    if contract is None:
        return
    for name in (
        SCHEDULE_ATTR,
        SOURCE_ATTR,
        MATCH_ATTR,
        ANCHOR_GUARANTEE_ATTR,
        CURRENT_SEASON_ATTR,
    ):
        if hasattr(contract, name):
            delattr(contract, name)
    setattr(contract, LINEAGE_ATTR, FRANCHISE_TRANSACTION_LINEAGE)
    setattr(contract, "franchise_contract_transaction_source_v1", _clean(source))
    setattr(contract, "franchise_contract_transaction_season_v1", _clean(season_label))
    setattr(contract, "franchise_contract_continuity_version_v1", LEGACY_CONTRACT_CONTINUITY_VERSION)
