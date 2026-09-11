from __future__ import annotations

import copy
import csv
import dataclasses
import hashlib
import io
import json
import math
import pickle
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-offseason-roster-capacity-semantics-audit-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
CBA_OFFSEASON_ROSTER_MAX = 21

PENDING_PREFIX = "pending_"
UNDER_CONTRACT_PREFIX = "under_contract_"


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def team(value: Any) -> str:
    return clean(value).upper()


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        data = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def replace_attr(obj: Any, **changes: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.replace(obj, **changes)
    cloned = copy.deepcopy(obj)
    for key, value in changes.items():
        setattr(cloned, key, value)
    return cloned


def set_player_roster_status(player: Any, status: str) -> Any:
    if not hasattr(player, "roster_status"):
        return player
    return replace_attr(player, roster_status=status)


def set_team_roster(team_state: Any, roster_ids: tuple[str, ...]) -> Any:
    if not hasattr(team_state, "roster_player_ids"):
        raise RuntimeError("Team state lacks roster_player_ids.")
    return replace_attr(team_state, roster_player_ids=tuple(roster_ids))


def update_state(
    state: Any,
    *,
    players: Mapping[str, Any],
    teams: Mapping[str, Any],
    free_agents: tuple[str, ...],
) -> Any:
    return replace_attr(
        state,
        players=players,
        teams=teams,
        free_agent_player_ids=free_agents,
    )


def active_roster_status(state: Any) -> str:
    players = getattr(state, "players", {}) or {}
    counter = Counter()
    for team_state in (getattr(state, "teams", {}) or {}).values():
        for player_id in (getattr(team_state, "roster_player_ids", ()) or ()):
            player = players.get(pid(player_id))
            if player is None:
                continue
            status = clean(getattr(player, "roster_status", ""))
            if status:
                counter[status] += 1
    return counter.most_common(1)[0][0] if counter else "active_roster"


def safe_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return clean(value)
    if isinstance(value, (tuple, list, set, frozenset)):
        return "|".join(clean(x) for x in list(value)[:30])
    if isinstance(value, Mapping):
        return json.dumps(
            {clean(k): clean(v) for k, v in list(value.items())[:30]},
            sort_keys=True,
        )
    return clean(repr(value))


def object_attrs(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    try:
        attrs = dict(vars(obj))
    except Exception:
        attrs = {}
    return attrs


def contract_signature(contract: Any) -> dict[str, Any]:
    attrs = object_attrs(contract)
    lowered = {
        clean(key).lower(): value
        for key, value in attrs.items()
    }

    string_blob = " ".join(
        f"{key}={safe_value(value)}"
        for key, value in lowered.items()
    ).lower()

    two_way = "two-way" in string_blob or "two_way" in string_blob
    if not two_way:
        for key in (
            "contract_type",
            "type",
            "kind",
            "roster_type",
            "deal_type",
        ):
            value = lowered.get(key)
            if value is not None and "two" in clean(value).lower():
                two_way = True

    salary_fields = {}
    for key, value in lowered.items():
        if any(token in key for token in ("salary", "amount", "cap_hit", "guarante")):
            salary_fields[key] = safe_value(value)

    season_fields = {}
    for key, value in lowered.items():
        if any(token in key for token in ("season", "year", "start", "end", "expiry", "expiration")):
            season_fields[key] = safe_value(value)

    return {
        "contract_present": contract is not None,
        "contract_class": (
            f"{type(contract).__module__}.{type(contract).__name__}"
            if contract is not None else ""
        ),
        "contract_two_way_detected": two_way,
        "contract_attr_count": len(attrs),
        "contract_attrs_json": json.dumps(
            {clean(k): safe_value(v) for k, v in attrs.items()},
            sort_keys=True,
        ),
        "contract_salary_fields_json": json.dumps(salary_fields, sort_keys=True),
        "contract_season_fields_json": json.dumps(season_fields, sort_keys=True),
    }


def player_name(player: Any, fallback: str) -> str:
    for attr in (
        "player_name",
        "display_name",
        "name",
        "full_name",
    ):
        value = clean(getattr(player, attr, ""))
        if value:
            return value
    return fallback


def build_clone(
    state: Any,
    *,
    market_ids: set[str],
    attached_rows: list[dict[str, str]],
) -> Any:
    cloned = copy.deepcopy(state)
    players = dict(getattr(cloned, "players", {}) or {})
    teams = dict(getattr(cloned, "teams", {}) or {})
    live_fa = tuple(
        pid(x)
        for x in (getattr(cloned, "free_agent_player_ids", ()) or ())
    )
    roster_status = active_roster_status(cloned)

    ordered_market = [x for x in live_fa if x in market_ids]
    seen = set(ordered_market)
    ordered_market.extend(sorted(market_ids - seen))

    for row in attached_rows:
        player_id = pid(row.get("player_id"))
        team_code = team(row.get("prior_team"))
        if player_id not in players or team_code not in teams:
            raise RuntimeError(
                f"Cannot reconstruct attached player {player_id} -> {team_code}"
            )
        roster = [
            pid(x)
            for x in (getattr(teams[team_code], "roster_player_ids", ()) or ())
        ]
        if player_id not in set(roster):
            roster.append(player_id)
        teams[team_code] = set_team_roster(
            teams[team_code],
            tuple(roster),
        )
        players[player_id] = set_player_roster_status(
            players[player_id],
            roster_status,
        )

    return update_state(
        cloned,
        players=players,
        teams=teams,
        free_agents=tuple(ordered_market),
    )


def engine_roster_limit_hits(root: Path) -> list[dict[str, Any]]:
    src = root / "src"
    rows = []
    if not src.exists():
        return rows

    patterns = (
        re.compile(r"roster_player_ids"),
        re.compile(r"\b18\b"),
        re.compile(r"\b21\b"),
        re.compile(r"roster.{0,40}(?:limit|max|capacity)", re.I),
        re.compile(r"(?:limit|max|capacity).{0,40}roster", re.I),
    )

    for path in src.glob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="cp1252", errors="ignore")
        except Exception:
            continue

        lines = text.splitlines()
        for index, line in enumerate(lines, start=1):
            if "roster" not in line.lower() and "18" not in line and "21" not in line:
                continue
            if not any(pattern.search(line) for pattern in patterns):
                continue
            rows.append({
                "source_path": str(path.resolve()),
                "source_sha256": sha256_file(path),
                "line_number": index,
                "line_text": line.strip()[:1200],
            })

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()

    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    corrected_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )
    dryrun_zip = find_latest(
        root,
        "fa_offseason_contract_state_reconciliation_dry_run_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )
        lifecycle_rows = read_csv_member(
            archive,
            "contract_option_lifecycle_all.csv",
        )

    with zipfile.ZipFile(corrected_zip) as archive:
        corrected_summary = read_json_member(
            archive,
            "corrected_rfa_qo_summary.json",
        )
        market_rows = read_csv_member(
            archive,
            "corrected_rfa_qo_universe_all.csv",
        )

    with zipfile.ZipFile(dryrun_zip) as archive:
        dryrun_summary = read_json_member(
            archive,
            "contract_state_reconciliation_summary.json",
        )
        delta_rows = read_csv_member(
            archive,
            "team_roster_count_deltas.csv",
        )

    market_ids = {pid(row.get("player_id")) for row in market_rows}
    attached_rows = [
        row for row in lifecycle_rows
        if (
            clean(row.get("contract_lifecycle_state")).startswith(PENDING_PREFIX)
            or clean(row.get("contract_lifecycle_state")).startswith(UNDER_CONTRACT_PREFIX)
        )
    ]
    attached_by_id = {
        pid(row.get("player_id")): row
        for row in attached_rows
    }

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_hash = sha256_file(checkpoint_path)
        checkpoint = checkpoint_module.load_franchise_checkpoint()
    except Exception as exc:
        raise RuntimeError("Could not load canonical franchise checkpoint.") from exc

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Checkpoint changed unexpectedly after failed apply.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    live_state = checkpoint.simulation_state
    live_digest_before = object_digest(live_state)

    clone = build_clone(
        live_state,
        market_ids=market_ids,
        attached_rows=attached_rows,
    )
    clone_players = getattr(clone, "players", {}) or {}
    clone_teams = getattr(clone, "teams", {}) or {}

    live_teams = getattr(live_state, "teams", {}) or {}
    live_players = getattr(live_state, "players", {}) or {}

    print("=" * 126, flush=True)
    print("2026 OFFSEASON ROSTER CAPACITY SEMANTICS AUDIT V1", flush=True)
    print("=" * 126, flush=True)
    print(f"Checkpoint: {checkpoint_hash}", flush=True)
    print(f"CBA offseason aggregate roster maximum: {CBA_OFFSEASON_ROSTER_MAX}", flush=True)
    print("READ-ONLY. No roster, contract, free-agent, or checkpoint mutation.", flush=True)
    print("", flush=True)

    team_rows = []
    player_rows = []

    for team_code in sorted(clone_teams):
        live_roster = tuple(
            pid(x)
            for x in (getattr(live_teams[team_code], "roster_player_ids", ()) or ())
        )
        clone_roster = tuple(
            pid(x)
            for x in (getattr(clone_teams[team_code], "roster_player_ids", ()) or ())
        )

        countable_contracts = 0
        contractless = 0
        two_way_detected = 0
        standard_or_other_contract = 0

        for player_id in clone_roster:
            player = clone_players.get(player_id)
            signature = contract_signature(
                getattr(player, "contract", None) if player is not None else None
            )
            if signature["contract_present"]:
                countable_contracts += 1
                if signature["contract_two_way_detected"]:
                    two_way_detected += 1
                else:
                    standard_or_other_contract += 1
            else:
                contractless += 1

            lifecycle = attached_by_id.get(player_id, {})
            player_rows.append({
                "team_abbreviation": team_code,
                "player_id": player_id,
                "player_name": player_name(player, player_id),
                "was_on_live_roster": player_id in set(live_roster),
                "restored_by_reconciliation": player_id in attached_by_id and player_id not in set(live_roster),
                "lifecycle_state": clean(lifecycle.get("contract_lifecycle_state")),
                "lifecycle_contract_type": clean(lifecycle.get("active_contract_type_at_split")),
                "lifecycle_2026_27_base_salary": clean(lifecycle.get("season_2026_27_base_salary")),
                "lifecycle_2026_27_guaranteed": clean(lifecycle.get("season_2026_27_guaranteed")),
                "roster_status": clean(getattr(player, "roster_status", "")) if player is not None else "",
                **signature,
            })

        team_rows.append({
            "team_abbreviation": team_code,
            "raw_roster_count_live": len(live_roster),
            "raw_roster_count_projected": len(clone_roster),
            "raw_delta": len(clone_roster) - len(live_roster),
            "players_with_contract_object_projected": countable_contracts,
            "players_without_contract_object_projected": contractless,
            "two_way_contracts_detected_projected": two_way_detected,
            "standard_or_other_contracts_projected": standard_or_other_contract,
            "raw_exceeds_18": len(clone_roster) > 18,
            "raw_exceeds_cba_offseason_21": len(clone_roster) > CBA_OFFSEASON_ROSTER_MAX,
            "contract_object_count_exceeds_cba_21": countable_contracts > CBA_OFFSEASON_ROSTER_MAX,
        })

    mem_rows = [
        row for row in player_rows
        if row["team_abbreviation"] == "MEM"
    ]

    engine_hits = engine_roster_limit_hits(root)

    live_digest_after = object_digest(live_state)
    checkpoint_after = sha256_file(checkpoint_path)

    checks = []

    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("Running strict audit checks...", flush=True)
    check(
        "upstream_lifecycle_passed",
        bool(lifecycle_summary.get("passed")),
        "Lifecycle source passed.",
    )
    check(
        "upstream_corrected_market_passed",
        bool(corrected_summary.get("passed")),
        "Corrected market source passed.",
    )
    check(
        "upstream_reconciliation_dry_run_passed",
        bool(dryrun_summary.get("passed")),
        "Reconciliation clone source passed.",
    )
    check(
        "canonical_checkpoint_is_still_preapply_revision",
        checkpoint_hash == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash,
    )
    check(
        "memphis_projected_raw_roster_is_22",
        next(
            (row["raw_roster_count_projected"] for row in team_rows if row["team_abbreviation"] == "MEM"),
            None,
        ) == 22,
        "Expected to reproduce the failed apply boundary exactly.",
    )
    check(
        "memphis_has_exactly_three_restored_rows",
        sum(row["restored_by_reconciliation"] for row in mem_rows) == 3,
        "Jahmai Mashack, Javon Small, Taj Gibson are the three MEM restorations.",
    )
    check(
        "no_mutation_to_live_state",
        live_digest_before == live_digest_after,
        live_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash == checkpoint_after,
        checkpoint_after,
    )

    cba_semantics_ready = all(
        (
            row["raw_roster_count_projected"] <= CBA_OFFSEASON_ROSTER_MAX
            or row["players_with_contract_object_projected"] <= CBA_OFFSEASON_ROSTER_MAX
        )
        for row in team_rows
    )
    check(
        "raw_or_contract_semantics_fit_cba_21",
        cba_semantics_ready,
        (
            "PASS means every raw >21 roster has at least one roster entry "
            "without a ContractState, suggesting raw roster_player_ids is broader "
            "than the CBA Active/Inactive/Two-Way aggregate. FAIL means a genuine "
            "contract-bearing >21 conflict remains."
        ),
        severity="diagnostic",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Offseason Roster Capacity Semantics Audit V1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_offseason_roster_capacity_semantics_audit_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    raw_over_18 = [row for row in team_rows if row["raw_exceeds_18"]]
    raw_over_21 = [row for row in team_rows if row["raw_exceeds_cba_offseason_21"]]
    contract_over_21 = [row for row in team_rows if row["contract_object_count_exceeds_cba_21"]]

    with tempfile.TemporaryDirectory(prefix="fa_roster_semantics_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "team_roster_capacity_summary.csv", team_rows)
        write_csv(export / "projected_roster_player_semantics.csv", player_rows)
        write_csv(export / "memphis_22_player_detail.csv", mem_rows)
        write_csv(export / "engine_roster_limit_source_hits.csv", engine_hits)
        write_csv(export / "roster_capacity_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "cba_offseason_roster_max": CBA_OFFSEASON_ROSTER_MAX,
            "checkpoint_sha256": checkpoint_hash,
            "teams_raw_over_18": [row["team_abbreviation"] for row in raw_over_18],
            "teams_raw_over_21": [row["team_abbreviation"] for row in raw_over_21],
            "teams_contract_object_count_over_21": [
                row["team_abbreviation"] for row in contract_over_21
            ],
            "memphis_raw_live_count": next(
                row["raw_roster_count_live"]
                for row in team_rows
                if row["team_abbreviation"] == "MEM"
            ),
            "memphis_raw_projected_count": next(
                row["raw_roster_count_projected"]
                for row in team_rows
                if row["team_abbreviation"] == "MEM"
            ),
            "memphis_projected_contract_object_count": next(
                row["players_with_contract_object_projected"]
                for row in team_rows
                if row["team_abbreviation"] == "MEM"
            ),
            "memphis_projected_contractless_count": next(
                row["players_without_contract_object_projected"]
                for row in team_rows
                if row["team_abbreviation"] == "MEM"
            ),
            "memphis_projected_two_way_count_detected": next(
                row["two_way_contracts_detected_projected"]
                for row in team_rows
                if row["team_abbreviation"] == "MEM"
            ),
            "engine_roster_limit_source_hit_count": len(engine_hits),
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed_strict_checks": True,
            "diagnostic_cba_semantics_ready": cba_semantics_ready,
            "next_slice_if_diagnostic_passes": (
                "Patch reconciliation apply to validate the CBA-countable "
                "Active/Inactive/Two-Way aggregate rather than raw roster_player_ids."
            ),
            "next_slice_if_diagnostic_fails": (
                "Resolve the genuine Memphis >21 contract-bearing conflict "
                "before durable reconciliation. Do not auto-waive a player."
            ),
        }

        (export / "roster_capacity_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """2026 OFFSEASON ROSTER CAPACITY SEMANTICS AUDIT V1
==================================================

Why this exists
---------------
The guarded reconciliation apply failed before any durable write because it
used a raw `len(roster_player_ids) <= 18` invariant.

That invariant is not correct for an offseason state.

The 2023 NBA CBA Article XXIX, Section 2(d) provides that outside the regular-
season/postseason period a team may have no more than 21 players in aggregate
on its Active, Inactive, and Two-Way Lists.

The reconciliation clone projects Memphis from 19 raw roster_player_ids to 22.
Therefore simply changing 18 -> 21 is also insufficient.

This audit determines whether:
A) raw roster_player_ids contains at least one non-contract organizational /
   draft-rights / other non-counting entry, so the CBA-countable roster remains
   <=21, or
B) all 22 are contract-bearing, which would require resolving a genuine CBA
   roster-capacity conflict before any durable reconciliation.

No player is waived.
No contract is changed.
No free-agent membership is changed.
No checkpoint is written.
"""

        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    print("", flush=True)
    print("=" * 126, flush=True)
    print("2026 OFFSEASON ROSTER CAPACITY SEMANTICS AUDIT V1 PASSED", flush=True)
    print("=" * 126, flush=True)

    for row in raw_over_18:
        print(
            f"{row['team_abbreviation']}: raw={row['raw_roster_count_projected']} | "
            f"contract_objects={row['players_with_contract_object_projected']} | "
            f"contractless={row['players_without_contract_object_projected']} | "
            f"two_way_detected={row['two_way_contracts_detected_projected']}",
            flush=True,
        )

    print(
        "Teams raw >21: "
        + (", ".join(row["team_abbreviation"] for row in raw_over_21) or "NONE"),
        flush=True,
    )
    print(
        "Teams with >21 ContractState-bearing roster entries: "
        + (", ".join(row["team_abbreviation"] for row in contract_over_21) or "NONE"),
        flush=True,
    )
    print(
        "CBA roster semantics diagnostic: "
        + ("PASS" if cba_semantics_ready else "FAIL"),
        flush=True,
    )
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
