from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-frozen-incentive-final-freeze-v1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
SOURCE_PATTERN = "fa_frozen_incentive_source_acquisition_hotfix_v1_0_3_2026-27_*.zip"
TEMPORAL_PATTERN = "fa_frozen_incentive_temporal_evidence_resolution_preview_v1_2026-27_*.zip"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
DEAD_CAP_PATTERN = "fa_frozen_dead_cap_final_freeze_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
EXPECTED_NUMERIC_COUNT = 320
EXPECTED_NOT_APPLICABLE_COUNT = 11
EXPECTED_POSITIVE_COUNT = 54
EXPECTED_LIKELY_TOTAL = 10_691_125
EXPECTED_UNLIKELY_TOTAL = 42_079_384
EXPECTED_SORBER_LIKELY = 814_620
EXPECTED_TARGET_IDS = {
    "203114", "203468", "204001", "1628380", "1628381", "1629057",
    "1630604", "1631117", "1631127", "1631131", "1631132",
}
REQUIRED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def money_int(value: Any) -> int | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return int(number) if number == number.to_integral_value() else None


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


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one ZIP member ending with {suffix}; found {len(matches)}")
    return matches[0]


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def find_passed(root: Path, pattern: str, summary_suffix: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    valid: list[Path] = []
    for path in candidates:
        try:
            with zipfile.ZipFile(path) as archive:
                summary = json_suffix(archive, summary_suffix)
                if summary.get("passed") is True and not summary.get("failed_checks"):
                    valid.append(path)
        except Exception:
            continue
    if not valid:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(valid, key=lambda path: path.stat().st_mtime)


def main() -> int:
    root = Path.cwd().resolve()
    source_zip = find_passed(
        root, SOURCE_PATTERN,
        "frozen_incentive_source_acquisition_hotfix_v1_0_3_summary.json",
    )
    temporal_zip = find_passed(
        root, TEMPORAL_PATTERN,
        "frozen_incentive_temporal_evidence_resolution_preview_summary.json",
    )
    boundary_zip = find_passed(root, BOUNDARY_PATTERN, "effective_boundary_summary.json")
    dead_cap_zip = find_passed(root, DEAD_CAP_PATTERN, "frozen_dead_cap_final_freeze_summary.json")

    with zipfile.ZipFile(source_zip) as archive:
        source_summary = json_suffix(archive, "frozen_incentive_source_acquisition_hotfix_v1_0_3_summary.json")
        source_checks = csv_suffix(archive, "frozen_incentive_source_acquisition_hotfix_v1_0_3_checks.csv")
        source_rows = csv_suffix(archive, "validated_frozen_incentive_resolution_preview_331.csv")
        source_unresolved = csv_suffix(archive, "validated_unresolved_incentive_targets_11.csv")
        source_team_rows = csv_suffix(archive, "validated_team_incentive_resolution_preview_30.csv")

    with zipfile.ZipFile(temporal_zip) as archive:
        temporal_summary = json_suffix(archive, "frozen_incentive_temporal_evidence_resolution_preview_summary.json")
        temporal_checks = csv_suffix(archive, "frozen_incentive_temporal_evidence_resolution_preview_checks.csv")
        temporal_queue = csv_suffix(archive, "remaining_temporal_evidence_queue_11.csv")
        temporal_combined = csv_suffix(archive, "combined_frozen_incentive_resolution_preview_331.csv")

    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")

    with zipfile.ZipFile(dead_cap_zip) as archive:
        dead_cap_summary = json_suffix(archive, "frozen_dead_cap_final_freeze_summary.json")
        dead_cap_checks = csv_suffix(archive, "frozen_dead_cap_final_freeze_checks.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before final frozen incentive freeze.")

    print("=" * 132)
    print("2026 FROZEN INCENTIVE FINAL FREEZE V1")
    print("=" * 132)
    print("Closing 320 numeric rows plus 11 temporally not-applicable rows as final audited evidence...")

    unresolved_by_id = {clean(row.get("player_id")): row for row in source_unresolved}
    temporal_by_id = {clean(row.get("player_id")): row for row in temporal_queue}
    final_player_ledger: list[dict[str, Any]] = []
    for source in sorted(source_rows, key=lambda row: clean(row.get("player_id"))):
        player_id = clean(source.get("player_id"))
        is_unresolved = clean(source.get("resolution_status")).startswith("unresolved_")
        if not is_unresolved:
            final_player_ledger.append({
                "season": SEASON_LABEL,
                "canonical_split_date": SPLIT_DATE.isoformat(),
                "player_id": player_id,
                "player_name": clean(source.get("player_name")),
                "frozen_team": clean(source.get("frozen_team")),
                "frozen_listed_base_salary": int(money_int(source.get("frozen_listed_base_salary")) or 0),
                "opening_snapshot_incentive_applicability": "applicable_pre_split_2026_27_contract",
                "final_resolution_status": "final_numeric_source_values",
                "resolution_basis": clean(source.get("resolution_status")),
                "signing_team": clean(source.get("signing_team")),
                "signing_date": clean(source.get("signing_date")),
                "cap_hit": int(money_int(source.get("cap_hit")) or 0),
                "base_salary": int(money_int(source.get("base_salary")) or 0),
                "guaranteed": int(money_int(source.get("guaranteed")) or 0),
                "likely_incentive": int(money_int(source.get("likely_incentive")) or 0),
                "unlikely_incentive": int(money_int(source.get("unlikely_incentive")) or 0),
                "source_url": clean(source.get("source_url")),
                "source_sha256": clean(source.get("source_sha256")),
                "snapshot_filename": clean(source.get("snapshot_filename")),
                "numeric_values_frozen": True,
                "applicability_classification_frozen": True,
                "numeric_zero_imputed": False,
                "post_split_outcome_imported": False,
                "frozen_evidence_status": "final",
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            })
            continue

        temporal = temporal_by_id.get(player_id)
        if temporal is None:
            raise RuntimeError(f"Missing temporal closure evidence for player {player_id}.")
        original_status = clean(unresolved_by_id[player_id].get("resolution_status"))
        reason = (
            "no_pre_split_2026_27_contract_post_split_contract_quarantined"
            if original_status == "unresolved_post_split_contract_only"
            else "no_parseable_2026_27_contract_row_at_frozen_boundary"
        )
        final_player_ledger.append({
            "season": SEASON_LABEL,
            "canonical_split_date": SPLIT_DATE.isoformat(),
            "player_id": player_id,
            "player_name": clean(source.get("player_name")),
            "frozen_team": clean(source.get("frozen_team")),
            "frozen_listed_base_salary": int(money_int(source.get("frozen_listed_base_salary")) or 0),
            "opening_snapshot_incentive_applicability": "not_applicable_no_pre_split_2026_27_contract",
            "final_resolution_status": "final_temporal_not_applicable",
            "resolution_basis": reason,
            "signing_team": "",
            "signing_date": "",
            "cap_hit": "",
            "base_salary": "",
            "guaranteed": "",
            "likely_incentive": "",
            "unlikely_incentive": "",
            "source_url": clean(source.get("source_url")),
            "source_sha256": clean(source.get("source_sha256")),
            "snapshot_filename": clean(source.get("snapshot_filename")),
            "numeric_values_frozen": False,
            "applicability_classification_frozen": True,
            "numeric_zero_imputed": False,
            "post_split_outcome_imported": False,
            "frozen_evidence_status": "final",
            "applied_to_team_salary": False,
            "state_mutation_applied": False,
        })

    numeric_rows = [row for row in final_player_ledger if row["numeric_values_frozen"]]
    not_applicable_rows = [row for row in final_player_ledger if not row["numeric_values_frozen"]]
    positive_rows = [row for row in numeric_rows if row["likely_incentive"] > 0 or row["unlikely_incentive"] > 0]

    final_team_ledger: list[dict[str, Any]] = []
    for source_team in sorted(source_team_rows, key=lambda row: clean(row.get("team"))):
        team = clean(source_team.get("team"))
        team_numeric = [row for row in numeric_rows if row["frozen_team"] == team]
        team_na = [row for row in not_applicable_rows if row["frozen_team"] == team]
        final_team_ledger.append({
            "season": SEASON_LABEL,
            "canonical_split_date": SPLIT_DATE.isoformat(),
            "team": team,
            "final_standard_contract_population": len(team_numeric) + len(team_na),
            "numeric_incentive_player_count": len(team_numeric),
            "not_applicable_player_count": len(team_na),
            "positive_incentive_player_count": sum(row["likely_incentive"] > 0 or row["unlikely_incentive"] > 0 for row in team_numeric),
            "frozen_likely_incentive_total": sum(row["likely_incentive"] for row in team_numeric),
            "frozen_unlikely_incentive_total": sum(row["unlikely_incentive"] for row in team_numeric),
            "team_ledger_status": "final_complete_numeric_plus_temporal_na",
            "frozen_evidence_status": "final",
            "applied_to_team_salary": False,
            "state_mutation_applied": False,
        })

    closed_blocker = [{
        "prior_priority": 1,
        "blocker_id": "frozen_likely_and_unlikely_incentive_ledger",
        "resolution": "closed_as_320_numeric_plus_11_temporal_not_applicable",
        "final_player_population": len(final_player_ledger),
        "numeric_player_count": len(numeric_rows),
        "not_applicable_player_count": len(not_applicable_rows),
        "positive_incentive_player_count": len(positive_rows),
        "frozen_likely_total": sum(row["likely_incentive"] for row in numeric_rows),
        "frozen_unlikely_total": sum(row["unlikely_incentive"] for row in numeric_rows),
        "applied_to_simulation": False,
    }]
    remaining_blockers = [{
        "priority": 1,
        "blocker_id": "post_draft_2026_first_round_pick_hold_bridge",
        "temporal_requirement": "create_at_simulated_2026_draft_event_not_opening_snapshot",
        "required_next_input": "Bridge simulated first-round draft results and signing status to dynamic rookie-scale holds.",
        "opening_snapshot_complete": False,
        "applied_to_simulation": False,
    }]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    source_statuses = [clean(row.get("resolution_status")) for row in source_unresolved]
    add("source_acquisition_v1_0_3_passed", source_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in source_checks), source_zip.name)
    add("temporal_repository_preview_passed", temporal_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in temporal_checks), temporal_zip.name)
    add("effective_boundary_freeze_passed", boundary_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in boundary_checks), boundary_zip.name)
    add("dead_cap_final_freeze_passed", dead_cap_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in dead_cap_checks), dead_cap_zip.name)
    add("all_upstreams_use_april_12_boundary", clean(source_summary.get("canonical_split_date")) == clean(temporal_summary.get("canonical_split_date")) == clean(boundary_summary.get("canonical_split_date")) == clean(dead_cap_summary.get("canonical_split_date")) == SPLIT_DATE.isoformat(), SPLIT_DATE.isoformat())
    add("source_registry_is_exactly_331_unique", len(source_rows) == 331 and len({clean(row.get("player_id")) for row in source_rows}) == 331, "331/331")
    add("temporal_combined_registry_is_exactly_331_unique", len(temporal_combined) == 331 and len({clean(row.get("player_id")) for row in temporal_combined}) == 331, "331/331")
    add("exact_11_temporal_target_ids_are_preserved", {clean(row.get("player_id")) for row in source_unresolved} == {clean(row.get("player_id")) for row in temporal_queue} == EXPECTED_TARGET_IDS, "11/11")
    add("temporal_scan_found_zero_eligible_pre_split_candidates", int(temporal_summary.get("eligible_pre_split_candidate_count", -1)) == 0 and int(temporal_summary.get("newly_resolved_target_count", -1)) == 0, "0/11")
    add("quarantine_is_exactly_10_post_split_plus_1_no_row", source_statuses.count("unresolved_post_split_contract_only") == 10 and source_statuses.count("unresolved_no_parseable_2026_27_contract_row") == 1, "10 + 1")
    add("all_11_have_zero_pre_split_contract_rows", all(int(clean(row.get("pre_split_contract_row_count")) or 0) == 0 for row in source_unresolved), "11/11")
    add("final_player_ledger_is_exactly_331_unique", len(final_player_ledger) == 331 and len({row["player_id"] for row in final_player_ledger}) == 331, "331/331")
    add("exact_320_numeric_rows_are_final", len(numeric_rows) == EXPECTED_NUMERIC_COUNT, "320/320")
    add("exact_11_temporal_not_applicable_rows_are_final", len(not_applicable_rows) == EXPECTED_NOT_APPLICABLE_COUNT and {row["player_id"] for row in not_applicable_rows} == EXPECTED_TARGET_IDS, "11/11")
    add("not_applicable_rows_have_no_numeric_values", all(row["likely_incentive"] == row["unlikely_incentive"] == "" and not row["numeric_values_frozen"] for row in not_applicable_rows), "11/11")
    add("no_zero_incentive_was_imputed_for_temporal_na", all(not row["numeric_zero_imputed"] for row in not_applicable_rows), "11/11")
    add("all_numeric_source_dates_are_on_or_before_split", all(clean(row.get("signing_date")) and date.fromisoformat(row["signing_date"]) <= SPLIT_DATE for row in numeric_rows), "320/320")
    add("exact_54_positive_incentive_players_are_final", len(positive_rows) == EXPECTED_POSITIVE_COUNT, "54/54")
    add("final_likely_incentive_total_is_exact", sum(row["likely_incentive"] for row in numeric_rows) == EXPECTED_LIKELY_TOTAL, f"${EXPECTED_LIKELY_TOTAL:,}")
    add("final_unlikely_incentive_total_is_exact", sum(row["unlikely_incentive"] for row in numeric_rows) == EXPECTED_UNLIKELY_TOTAL, f"${EXPECTED_UNLIKELY_TOTAL:,}")
    add("thomas_sorber_likely_incentive_remains_exact", any(row["player_id"] == "1642850" and row["likely_incentive"] == EXPECTED_SORBER_LIKELY for row in numeric_rows), f"${EXPECTED_SORBER_LIKELY:,}")
    add("final_team_ledger_is_exactly_30_unique", len(final_team_ledger) == 30 and {row["team"] for row in final_team_ledger} == REQUIRED_TEAMS, "30/30")
    add("team_ledgers_reaggregate_final_player_ledger", all(row["frozen_likely_incentive_total"] == sum(player["likely_incentive"] for player in numeric_rows if player["frozen_team"] == row["team"]) and row["frozen_unlikely_incentive_total"] == sum(player["unlikely_incentive"] for player in numeric_rows if player["frozen_team"] == row["team"]) for row in final_team_ledger), "30/30")
    add("incentive_blocker_closed_exactly_once", len(closed_blocker) == 1 and closed_blocker[0]["blocker_id"] == "frozen_likely_and_unlikely_incentive_ledger", "1/1")
    add("only_dynamic_rookie_hold_bridge_remains", len(remaining_blockers) == 1 and remaining_blockers[0]["blocker_id"] == "post_draft_2026_first_round_pick_hold_bridge", "1 blocker")
    add("no_incentive_value_applied_to_team_salary", all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in final_player_ledger + final_team_ledger), "evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_incentive_final_freeze_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "frozen_incentive_blocker_closed": not failed,
        "final_player_population": len(final_player_ledger),
        "final_numeric_player_count": len(numeric_rows),
        "final_temporal_not_applicable_count": len(not_applicable_rows),
        "final_positive_incentive_player_count": len(positive_rows),
        "final_frozen_likely_incentive_total": sum(row["likely_incentive"] for row in numeric_rows),
        "final_frozen_unlikely_incentive_total": sum(row["unlikely_incentive"] for row in numeric_rows),
        "numeric_zero_imputed_for_not_applicable_count": 0,
        "remaining_financial_component_blocker_count": len(remaining_blockers),
        "remaining_financial_component_blockers": [row["blocker_id"] for row in remaining_blockers],
        "incentive_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": "Build the post-draft 2026 first-round pick-hold bridge. Do not backfill rookie holds into the April 12 opening snapshot.",
    }

    with tempfile.TemporaryDirectory(prefix="fa_frozen_incentive_final_freeze_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "final_frozen_incentive_player_ledger_331.csv", final_player_ledger)
        write_csv(export / "final_frozen_numeric_incentive_rows_320.csv", numeric_rows)
        write_csv(export / "final_temporal_not_applicable_incentive_rows_11.csv", not_applicable_rows)
        write_csv(export / "final_positive_incentive_rows_54.csv", positive_rows)
        write_csv(export / "final_frozen_incentive_team_ledger_30.csv", final_team_ledger)
        write_csv(export / "closed_financial_component_blocker_1.csv", closed_blocker)
        write_csv(export / "remaining_financial_component_blockers_1.csv", remaining_blockers)
        write_csv(export / "frozen_incentive_final_freeze_checks.csv", checks)
        (export / "frozen_incentive_final_freeze_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN INCENTIVE FINAL FREEZE V1
=========================================

Purpose
-------
Close the April 12, 2026 frozen incentive ledger as final audited evidence.
The final population contains 320 contracts with exact numeric likely and
unlikely incentive values and 11 explicit temporal not-applicable closures.

The 11 closures are not numeric zero assumptions. Ten have only post-split
2026-27 contracts and one has no parseable 2026-27 contract row. Because no
eligible pre-split contract exists, an opening-snapshot incentive amount is
not applicable.

Safety
------
No incentive value is applied to Team Salary or simulation state. No roster,
contract, overlay, or checkpoint is mutated.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.rglob("*")):
                if item.is_file():
                    archive.write(item, arcname=f"{export_id}/{item.relative_to(export)}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Incentive Final Freeze V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN INCENTIVE FINAL FREEZE V1 PASSED")
    print("=" * 132)
    print(f"Final player population:            {len(final_player_ledger):>3}/331")
    print(f"Numeric incentive rows:             {len(numeric_rows):>3}/320")
    print(f"Temporal not-applicable closures:   {len(not_applicable_rows):>3}/11")
    print(f"Positive incentive players:         {len(positive_rows):>3}/54")
    print(f"Final frozen likely incentives:     ${sum(row['likely_incentive'] for row in numeric_rows):,}")
    print(f"Final frozen unlikely incentives:   ${sum(row['unlikely_incentive'] for row in numeric_rows):,}")
    print("Frozen incentive blocker:            CLOSED")
    print("Remaining financial blockers:            1")
    print("Incentive values applied:                 0")
    print("Checkpoint write:                     NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
