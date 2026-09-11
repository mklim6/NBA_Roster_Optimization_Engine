from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-team-salary-snapshot-boundary-reconciliation-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
HOTFIX_PATTERN = "fa_salaryswish_team_component_semantic_hotfix_v1_0_1_2026-27_*.zip"
POSTURE_PATTERN = "fa_team_base_salary_and_rights_posture_preview_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
REQUIRED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}
EXPECTED_LIVE_DRIFT_TEAMS = {
    "BOS", "CHA", "CHI", "CLE", "DET", "HOU", "LAC", "MIL", "NOP", "PHX",
    "SAC", "SAS", "TOR", "UTA",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def as_int(value: Any, *, label: str) -> int:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        raise RuntimeError(f"Missing integer value for {label}.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise RuntimeError(f"Invalid integer value for {label}: {value!r}") from exc
    if number != number.to_integral_value():
        raise RuntimeError(f"Non-integral value for {label}: {value!r}")
    return int(number)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def latest(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def unique_team_map(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        team = clean(row.get("team"))
        if not team:
            raise RuntimeError(f"Blank team in {label}.")
        if team in result:
            raise RuntimeError(f"Duplicate {team} row in {label}.")
        result[team] = row
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def find_check_detail(rows: list[dict[str, str]], check_id: str) -> str:
    row = next((item for item in rows if clean(item.get("check_id")) == check_id), {})
    if clean(row.get("status")) != "PASS":
        return ""
    return clean(row.get("detail"))


def main() -> int:
    root = Path.cwd().resolve()
    hotfix_zip = latest(root, HOTFIX_PATTERN)
    posture_zip = latest(root, POSTURE_PATTERN)

    with zipfile.ZipFile(hotfix_zip) as archive:
        hotfix_summary = json_suffix(archive, "semantic_hotfix_summary.json")
        hotfix_checks = csv_suffix(archive, "semantic_hotfix_checks.csv")
        live_rows = csv_suffix(archive, "reconciled_team_component_evidence_30.csv")
        live_drift_rows = csv_suffix(archive, "live_source_vs_legacy_checkpoint_drift_30.csv")
        formula_exception_rows = csv_suffix(archive, "source_formula_semantic_exceptions_5.csv")
        dead_cap_rows = csv_suffix(archive, "dead_cap_team_evidence_30.csv")
        incentive_rows = csv_suffix(archive, "team_incentive_evidence_30.csv")
        rookie_rows = csv_suffix(archive, "unsigned_first_round_hold_evidence_30.csv")

    with zipfile.ZipFile(posture_zip) as archive:
        posture_summary = json_suffix(archive, "team_base_salary_and_rights_posture_summary.json")
        posture_checks = csv_suffix(archive, "team_base_salary_and_rights_posture_checks.csv")
        posture_rows = csv_suffix(archive, "team_rights_posture_wide_30.csv")
        scenario_rows = csv_suffix(archive, "team_rights_posture_scenarios_120.csv")
        active_rows = csv_suffix(archive, "active_listed_salary_evidence_361.csv")
        standard_rows = csv_suffix(archive, "standard_contract_salary_base_331.csv")
        two_way_rows = csv_suffix(archive, "two_way_salary_excluded_30.csv")

    live_by_team = unique_team_map(live_rows, "live component evidence")
    posture_by_team = unique_team_map(posture_rows, "frozen team posture")
    drift_by_team = unique_team_map(live_drift_rows, "live/checkpoint drift evidence")
    dead_by_team = unique_team_map(dead_cap_rows, "live dead-cap evidence")
    incentive_by_team = unique_team_map(incentive_rows, "live incentive evidence")
    rookie_by_team = unique_team_map(rookie_rows, "live unsigned rookie-hold evidence")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before snapshot-boundary reconciliation.")

    reconciliation_rows: list[dict[str, Any]] = []
    for team in sorted(REQUIRED_TEAMS):
        live = live_by_team[team]
        frozen = posture_by_team[team]
        drift = drift_by_team[team]

        frozen_standard_count = as_int(frozen.get("standard_contract_count"), label=f"{team} frozen standard count")
        frozen_two_way_count = as_int(frozen.get("two_way_contract_count_excluded"), label=f"{team} frozen two-way count")
        frozen_attached_count = frozen_standard_count + frozen_two_way_count
        live_roster_size = as_int(live.get("current_roster_size"), label=f"{team} live roster size")
        frozen_base = as_int(frozen.get("standard_contract_base_salary_subtotal"), label=f"{team} frozen base salary")
        live_roster_cap = as_int(live.get("roster_cap_hit"), label=f"{team} live roster cap hit")
        live_holds = as_int(live.get("holds"), label=f"{team} live holds")
        frozen_model_holds = as_int(frozen.get("model_scenario_hold_total"), label=f"{team} frozen model holds")
        frozen_all_holds = as_int(frozen.get("all_preserved_hold_total_no_qo"), label=f"{team} frozen all-preserved holds")
        live_team_salary = as_int(live.get("team_salary"), label=f"{team} live Team Salary")
        checkpoint_team_salary = as_int(drift.get("legacy_checkpoint_team_salary"), label=f"{team} checkpoint Team Salary")
        team_salary_delta = live_team_salary - checkpoint_team_salary
        aggregate_matches = team_salary_delta == 0
        population_delta = live_roster_size - frozen_attached_count
        base_delta = live_roster_cap - frozen_base
        model_hold_delta = live_holds - frozen_model_holds
        all_hold_delta = live_holds - frozen_all_holds
        component_composition_matches = (
            population_delta == 0
            and base_delta == 0
            and model_hold_delta == 0
            and all_hold_delta == 0
        )
        direct_merge_safe = aggregate_matches and component_composition_matches
        boundary_classification = (
            "aggregate_total_match_but_component_composition_drift"
            if aggregate_matches
            else "aggregate_total_and_component_composition_drift"
        )
        reconciliation_rows.append(
            {
                "team": team,
                "frozen_standard_contract_count": frozen_standard_count,
                "frozen_two_way_contract_count": frozen_two_way_count,
                "frozen_attached_player_count": frozen_attached_count,
                "live_source_current_roster_size": live_roster_size,
                "live_minus_frozen_attached_player_count": population_delta,
                "frozen_standard_contract_base_salary_subtotal": frozen_base,
                "live_source_roster_cap_hit": live_roster_cap,
                "live_roster_cap_hit_minus_frozen_base_salary": base_delta,
                "frozen_model_scenario_hold_total": frozen_model_holds,
                "frozen_all_preserved_hold_total_no_qo": frozen_all_holds,
                "live_source_holds": live_holds,
                "live_holds_minus_frozen_model_holds": model_hold_delta,
                "live_holds_minus_frozen_all_preserved_holds": all_hold_delta,
                "legacy_checkpoint_team_salary": checkpoint_team_salary,
                "live_source_team_salary": live_team_salary,
                "live_minus_legacy_checkpoint_team_salary": team_salary_delta,
                "aggregate_team_salary_exact_match": aggregate_matches,
                "component_composition_exact_match": component_composition_matches,
                "boundary_classification": boundary_classification,
                "live_component_direct_merge_safe": direct_merge_safe,
                "canonical_snapshot_branch": "frozen_pre_offseason_split",
                "recommended_action": "reconstruct_frozen_snapshot_components_do_not_import_live_values",
                "live_source_url": clean(live.get("source_url")),
                "live_source_fetched_at_utc": clean(live.get("fetched_at_utc")),
                "live_source_sha256": clean(live.get("source_sha256")),
                "external_evidence_applied": False,
                "state_mutation_applied": False,
            }
        )

    aggregate_match_rows = [row for row in reconciliation_rows if row["aggregate_team_salary_exact_match"]]
    aggregate_drift_rows = [row for row in reconciliation_rows if not row["aggregate_team_salary_exact_match"]]
    direct_merge_safe_rows = [row for row in reconciliation_rows if row["live_component_direct_merge_safe"]]
    live_drift_teams = {row["team"] for row in aggregate_drift_rows}

    known_frozen_incentive_rows = [
        row for row in standard_rows
        if clean(row.get("known_likely_incentive_2026_27")) or clean(row.get("known_cap_hit_2026_27"))
    ]
    live_rookie_hold_total = sum(
        as_int(row.get("unsigned_first_round_hold_amount_2026_27"), label=f"{team} live rookie hold")
        for team, row in rookie_by_team.items()
    )
    missing_component_queue: list[dict[str, Any]] = [
        {
            "priority": 1,
            "blocker_id": "canonical_frozen_snapshot_effective_timestamp",
            "scope": "global",
            "current_evidence": "Frozen 361-player/331-standard roster split is internally audited; live pages were fetched later from a different roster population.",
            "required_resolution": "Freeze one canonical pre-offseason effective timestamp and require every historical component source to be valid at that instant.",
            "why_live_source_cannot_close_it": "Fetch time proves when the page was captured, not when each roster component became effective.",
            "direct_application_allowed": False,
        },
        {
            "priority": 2,
            "blocker_id": "frozen_dead_cap_and_waiver_ledger",
            "scope": "30 teams",
            "current_evidence": f"Live 30-team dead-cap registry totals ${int(hotfix_summary.get('dead_cap_total', 0)):,}; population is post-split.",
            "required_resolution": "Reconstruct player-level dead money and waiver/stretch charges as of the canonical frozen split.",
            "why_live_source_cannot_close_it": "Dead-cap entries can change after waivers, stretches, trades, and signings.",
            "direct_application_allowed": False,
        },
        {
            "priority": 3,
            "blocker_id": "frozen_likely_and_unlikely_incentive_ledger",
            "scope": "30 teams / player-level",
            "current_evidence": f"Live likely incentives total ${int(hotfix_summary.get('likely_incentive_total', 0)):,}; live unlikely incentives total ${int(hotfix_summary.get('unlikely_incentive_total', 0)):,}; frozen player evidence has {len(known_frozen_incentive_rows)} explicit cap-hit/incentive rows.",
            "required_resolution": "Resolve frozen-split player incentive classifications and team totals without treating guaranteed salary as Cap Hit.",
            "why_live_source_cannot_close_it": "Incentive classification and roster membership are snapshot-sensitive.",
            "direct_application_allowed": False,
        },
        {
            "priority": 4,
            "blocker_id": "frozen_unsigned_2026_first_round_pick_hold_status",
            "scope": "NYK candidate / league-wide zero proof",
            "current_evidence": f"Live source reports one unsigned first-round hold totaling ${live_rookie_hold_total:,}; frozen posture contains no draft-pick-hold component.",
            "required_resolution": "Prove whether the NYK $2,926,800 hold existed at the frozen split and prove zero/nonzero status for the other 29 teams.",
            "why_live_source_cannot_close_it": "Signing timing can create or remove an unsigned rookie hold after the frozen split.",
            "direct_application_allowed": False,
        },
    ]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 TEAM SALARY SNAPSHOT BOUNDARY RECONCILIATION PREVIEW V1")
    print("=" * 132)
    print("Reconciling live external components against the frozen pre-offseason roster split...")

    hotfix_checkpoint = find_check_detail(hotfix_checks, "checkpoint_file_unchanged")
    posture_checkpoint = find_check_detail(posture_checks, "checkpoint_file_unchanged")
    add("salaryswish_semantic_hotfix_passed", bool(hotfix_summary.get("passed")) and not hotfix_summary.get("failed_checks"), hotfix_zip.name)
    add("frozen_team_posture_preview_passed", bool(posture_summary.get("passed")) and not posture_summary.get("failed_checks"), posture_zip.name)
    add("both_upstreams_reference_canonical_checkpoint", hotfix_checkpoint == posture_checkpoint == EXPECTED_CHECKPOINT_SHA256, EXPECTED_CHECKPOINT_SHA256)
    add("exact_30_unique_teams_joined_across_all_registries", set(live_by_team) == set(posture_by_team) == set(drift_by_team) == set(dead_by_team) == set(incentive_by_team) == set(rookie_by_team) == REQUIRED_TEAMS, "30/30")
    add("frozen_population_is_exactly_361_players", len(active_rows) == 361 and len(standard_rows) == 331 and len(two_way_rows) == 30, f"active={len(active_rows)}, standard={len(standard_rows)}, two_way={len(two_way_rows)}")
    add("frozen_team_posture_has_exactly_120_scenario_rows", len(scenario_rows) == 120, f"rows={len(scenario_rows)}")
    add("hotfix_retains_exactly_five_formula_exception_rows", len(formula_exception_rows) == 5, f"rows={len(formula_exception_rows)}")
    add("all_30_live_roster_populations_differ_from_frozen_attached_population", all(row["live_minus_frozen_attached_player_count"] != 0 for row in reconciliation_rows), "30/30")
    add("all_30_live_roster_cap_totals_differ_from_frozen_standard_base", all(row["live_roster_cap_hit_minus_frozen_base_salary"] != 0 for row in reconciliation_rows), "30/30")
    add("aggregate_team_salary_split_is_exactly_16_match_14_drift", len(aggregate_match_rows) == 16 and len(aggregate_drift_rows) == 14, f"match={len(aggregate_match_rows)}, drift={len(aggregate_drift_rows)}")
    add("exact_14_drift_team_set_preserved", live_drift_teams == EXPECTED_LIVE_DRIFT_TEAMS, json.dumps(sorted(live_drift_teams)))
    add("all_16_aggregate_matches_still_have_component_composition_drift", all(not row["component_composition_exact_match"] for row in aggregate_match_rows), "16/16")
    add("zero_teams_are_safe_for_direct_live_component_merge", len(direct_merge_safe_rows) == 0, f"safe={len(direct_merge_safe_rows)}")
    add("canonical_branch_is_frozen_pre_offseason_reconstruction", all(row["canonical_snapshot_branch"] == "frozen_pre_offseason_split" for row in reconciliation_rows), "30/30")
    add("exact_four_frozen_snapshot_blockers_queued", len(missing_component_queue) == 4 and [row["priority"] for row in missing_component_queue] == [1, 2, 3, 4], "4/4")
    add("live_nyk_unsigned_first_round_hold_is_quarantined", live_rookie_hold_total == 2926800, f"live_total={live_rookie_hold_total}")
    add("all_live_source_provenance_retained", all(row["live_source_url"] and row["live_source_fetched_at_utc"] and row["live_source_sha256"] for row in reconciliation_rows), "30/30")
    add("no_external_component_applied_to_team_salary", all(not row["external_evidence_applied"] and not row["state_mutation_applied"] for row in reconciliation_rows), "Evidence only.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_team_salary_snapshot_boundary_reconciliation_preview_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "source_salaryswish_semantic_hotfix_audit": hotfix_zip.name,
        "source_frozen_team_posture_audit": posture_zip.name,
        "team_count": len(reconciliation_rows),
        "frozen_attached_player_count": len(active_rows),
        "frozen_standard_contract_count": len(standard_rows),
        "frozen_two_way_contract_count": len(two_way_rows),
        "aggregate_team_salary_match_count": len(aggregate_match_rows),
        "aggregate_team_salary_drift_count": len(aggregate_drift_rows),
        "aggregate_match_but_component_drift_count": sum(row["boundary_classification"] == "aggregate_total_match_but_component_composition_drift" for row in reconciliation_rows),
        "aggregate_and_component_drift_count": sum(row["boundary_classification"] == "aggregate_total_and_component_composition_drift" for row in reconciliation_rows),
        "direct_live_component_merge_safe_team_count": len(direct_merge_safe_rows),
        "frozen_snapshot_blocker_count": len(missing_component_queue),
        "canonical_snapshot_branch": "frozen_pre_offseason_split",
        "live_evidence_status": "quarantined_as_post_split_context_only",
        "official_team_salary_complete": False,
        "external_evidence_applied": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Freeze the canonical pre-offseason effective timestamp, then reconstruct the frozen dead-cap/waiver ledger, "
            "player-level incentive ledger, and unsigned 2026 first-round pick-hold status. Do not import live team values."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_snapshot_boundary_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "snapshot_boundary_team_reconciliation_30.csv", reconciliation_rows)
        write_csv(export / "aggregate_match_component_drift_16.csv", aggregate_match_rows)
        write_csv(export / "aggregate_and_component_drift_14.csv", aggregate_drift_rows)
        write_csv(export / "direct_live_component_merge_safe_0.csv", direct_merge_safe_rows)
        write_csv(export / "frozen_snapshot_missing_component_queue_4.csv", missing_component_queue)
        write_csv(export / "snapshot_boundary_checks.csv", checks)
        (export / "snapshot_boundary_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 TEAM SALARY SNAPSHOT BOUNDARY RECONCILIATION PREVIEW V1
================================================================

Purpose
-------
Protect the frozen pre-offseason 361-player salary split from a later live
SalarySwish roster snapshot. The live source is valuable external evidence,
but all 30 teams have a different roster population and roster-cap component
than the frozen model. Sixteen Team Salary totals happen to match the legacy
checkpoint, but their component composition still differs. Fourteen teams
also have an aggregate Team Salary drift.

Decision
--------
Zero teams are eligible for a direct live-component merge. The canonical
branch remains the frozen pre-offseason split. The next work is a historical,
source-aligned reconstruction of its effective timestamp, dead-cap/waiver
ledger, incentive ledger, and unsigned first-round pick-hold status.

Safety
------
No salary, cap hold, rights decision, renouncement, roster, simulation,
overlay, or checkpoint mutation occurs. Official Team Salary remains blocked.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Team Salary Snapshot Boundary Reconciliation Preview V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 TEAM SALARY SNAPSHOT BOUNDARY RECONCILIATION PREVIEW V1 PASSED")
    print("=" * 132)
    print("Teams reconciled:                         30/30")
    print("Aggregate Team Salary matches:            16/30")
    print("Aggregate Team Salary drift:              14/30")
    print("Aggregate matches with component drift:   16/16")
    print("Direct live-component merges allowed:      0/30")
    print("Frozen snapshot blockers queued:            4")
    print("Official Team Salary complete:             NO")
    print("Checkpoint write:               NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
