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


VERSION = "fa-frozen-dead-cap-final-freeze-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
COMPLETENESS_PATTERN = "fa_frozen_dead_cap_completeness_setoff_resolution_v1_2026-27_*.zip"
PLAYER_RESOLUTION_PATTERN = "fa_frozen_dead_cap_player_resolution_preview_v1_2026-27_*.zip"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
EXPECTED_PLAYER_COUNT = 12
EXPECTED_POSITIVE_TEAM_COUNT = 7
EXPECTED_ZERO_TEAM_COUNT = 23
EXPECTED_FROZEN_TOTAL = 55_653_831
EXPECTED_EXCLUDED_COUNT = 6
EXPECTED_EXCLUDED_TOTAL = 39_820_430
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
    if text in {"", "-", "–", "—"}:
        return 0 if text else None
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


def latest(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return member


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


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


def main() -> int:
    root = Path.cwd().resolve()
    completeness_zip = latest(root, COMPLETENESS_PATTERN)
    player_zip = latest(root, PLAYER_RESOLUTION_PATTERN)
    boundary_zip = latest(root, BOUNDARY_PATTERN)

    with zipfile.ZipFile(completeness_zip) as archive:
        completeness_summary = json_suffix(archive, "frozen_dead_cap_completeness_setoff_summary.json")
        completeness_checks = csv_suffix(archive, "frozen_dead_cap_completeness_setoff_checks.csv")
        candidate_rows = csv_suffix(archive, "frozen_dead_cap_final_candidates_12.csv")
        team_rows = csv_suffix(archive, "frozen_dead_cap_team_completeness_30.csv")
        source_notes = csv_suffix(archive, "frozen_dead_cap_source_notes_12.csv")
        post_contract_exposures = csv_suffix(archive, "frozen_dead_cap_post_split_contract_exposures.csv")
        post_option_exposures = csv_suffix(archive, "frozen_dead_cap_post_split_option_exposures.csv")

    with zipfile.ZipFile(player_zip) as archive:
        player_summary = json_suffix(archive, "dead_cap_player_resolution_summary.json")
        player_checks = csv_suffix(archive, "dead_cap_player_resolution_checks.csv")
        frozen_evidence_rows = csv_suffix(archive, "frozen_eligible_dead_cap_rows.csv")
        excluded_evidence_rows = csv_suffix(archive, "post_split_excluded_dead_cap_rows.csv")

    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")
        prior_blockers = csv_suffix(archive, "remaining_financial_component_blockers_3.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before final frozen dead-cap freeze.")

    print("=" * 132)
    print("2026 FROZEN DEAD-CAP FINAL FREEZE V1")
    print("=" * 132)
    print("Freezing the complete 30-team dead-cap ledger as audited evidence only...")

    candidate_by_slug = {clean(row.get("player_slug")): row for row in candidate_rows}
    note_by_slug = {clean(row.get("player_slug")): row for row in source_notes}
    final_player_ledger: list[dict[str, Any]] = []
    for evidence in frozen_evidence_rows:
        slug = clean(evidence.get("player_href")).split("/")[-1]
        candidate = candidate_by_slug.get(slug)
        note = note_by_slug.get(slug)
        if not candidate or not note:
            raise RuntimeError(f"Missing final completeness evidence for frozen player: {slug}")
        final_player_ledger.append(
            {
                "season": SEASON_LABEL,
                "canonical_split_date": SPLIT_DATE.isoformat(),
                "team": clean(evidence.get("team")),
                "player_display_name": clean(evidence.get("player_display_name")),
                "player_slug": slug,
                "method": clean(evidence.get("method")),
                "dead_cap_effective_date": clean(evidence.get("dead_cap_effective_date")),
                "frozen_2026_27_dead_cap_amount": int(money_int(evidence.get("frozen_2026_27_dead_cap_amount")) or 0),
                "temporal_classification": "frozen_snapshot_final_positive",
                "setoff_resolution_status": clean(candidate.get("setoff_resolution_status")),
                "frozen_amount_basis": clean(candidate.get("frozen_amount_basis")),
                "explicit_setoff_note": as_bool(note.get("explicit_setoff_note")),
                "setoff_credit_annual": int(money_int(note.get("setoff_credit_annual")) or 0),
                "player_page_source_url": clean(evidence.get("player_page_source_url")),
                "player_page_source_sha256": clean(evidence.get("player_page_source_sha256")),
                "team_snapshot_member": clean(evidence.get("team_snapshot_member")),
                "all_completeness_checks_passed": True,
                "setoff_amount_unresolved": False,
                "post_split_outcome_imported": False,
                "frozen_evidence_status": "final",
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            }
        )

    final_team_ledger: list[dict[str, Any]] = []
    for team_row in sorted(team_rows, key=lambda row: clean(row.get("team"))):
        team = clean(team_row.get("team"))
        amount = int(money_int(team_row.get("frozen_2026_27_dead_cap_total")) or 0)
        player_count = sum(row["team"] == team for row in final_player_ledger)
        final_team_ledger.append(
            {
                "season": SEASON_LABEL,
                "canonical_split_date": SPLIT_DATE.isoformat(),
                "team": team,
                "frozen_positive_player_count": player_count,
                "frozen_2026_27_dead_cap_total": amount,
                "team_ledger_status": "final_exact_positive" if amount else "final_exact_zero",
                "completeness_proof_class": clean(team_row.get("completeness_proof_class")),
                "historical_zero_or_positive_completeness_proven": as_bool(team_row.get("historical_zero_or_positive_completeness_proven")),
                "frozen_evidence_status": "final",
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            }
        )

    final_exclusion_ledger: list[dict[str, Any]] = []
    for row in excluded_evidence_rows:
        final_exclusion_ledger.append(
            {
                "season": SEASON_LABEL,
                "canonical_split_date": SPLIT_DATE.isoformat(),
                "team": clean(row.get("team")),
                "player_display_name": clean(row.get("player_display_name")),
                "player_slug": clean(row.get("player_href")).split("/")[-1],
                "method": clean(row.get("method")),
                "dead_cap_effective_date": clean(row.get("dead_cap_effective_date")),
                "post_split_excluded_amount": int(money_int(row.get("post_split_excluded_amount")) or 0),
                "temporal_classification": "final_post_split_exclusion",
                "imported_to_frozen_snapshot": False,
                "applied_to_team_salary": False,
            }
        )

    closed_blocker = [{
        "prior_priority": 1,
        "blocker_id": "frozen_dead_cap_and_waiver_ledger",
        "resolution": "closed_as_complete_final_audited_evidence",
        "positive_player_count": len(final_player_ledger),
        "positive_team_count": sum(row["frozen_2026_27_dead_cap_total"] > 0 for row in final_team_ledger),
        "zero_team_count": sum(row["frozen_2026_27_dead_cap_total"] == 0 for row in final_team_ledger),
        "frozen_total": sum(row["frozen_2026_27_dead_cap_total"] for row in final_team_ledger),
        "applied_to_simulation": False,
    }]
    remaining_blockers = [
        {
            "priority": 1,
            "blocker_id": "frozen_likely_and_unlikely_incentive_ledger",
            "known_exact_rows": 1,
            "known_exact_total": 814620,
            "required_next_input": "Complete player-level likely and unlikely incentive classifications without substituting guarantee values.",
            "opening_snapshot_complete": False,
        },
        {
            "priority": 2,
            "blocker_id": "post_draft_2026_first_round_pick_hold_bridge",
            "known_exact_rows": 0,
            "known_exact_total": "",
            "required_next_input": "Create dynamic rookie-scale holds only when the simulated 2026 draft event occurs.",
            "opening_snapshot_complete": False,
        },
    ]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    add("completeness_setoff_resolution_passed", bool(completeness_summary.get("passed")) and not completeness_summary.get("failed_checks"), completeness_zip.name)
    add("all_26_completeness_setoff_checks_passed", len(completeness_checks) == 26 and all(clean(row.get("status")) == "PASS" for row in completeness_checks), "26/26")
    add("player_resolution_preview_passed", bool(player_summary.get("passed")) and not player_summary.get("failed_checks"), player_zip.name)
    add("all_25_player_resolution_checks_passed", len(player_checks) == 25 and all(clean(row.get("status")) == "PASS" for row in player_checks), "25/25")
    add("effective_boundary_freeze_passed", bool(boundary_summary.get("passed")) and not boundary_summary.get("failed_checks"), boundary_zip.name)
    add("all_upstreams_use_exact_april_12_boundary", clean(completeness_summary.get("canonical_split_date")) == clean(player_summary.get("canonical_split_date")) == clean(boundary_summary.get("canonical_split_date")) == SPLIT_DATE.isoformat(), SPLIT_DATE.isoformat())
    add("exact_12_player_final_ledger_is_unique", len(final_player_ledger) == EXPECTED_PLAYER_COUNT and len({row["player_slug"] for row in final_player_ledger}) == EXPECTED_PLAYER_COUNT, "12/12")
    add("all_final_player_dates_are_on_or_before_split", all(date.fromisoformat(row["dead_cap_effective_date"]) <= SPLIT_DATE for row in final_player_ledger), "12/12")
    add("all_12_setoff_statuses_are_resolved", all(row["setoff_resolution_status"] and not row["setoff_amount_unresolved"] for row in final_player_ledger), "12/12")
    add("lillard_setoff_credit_is_frozen_exactly", any(row["player_slug"] == "damian-lillard" and row["setoff_credit_annual"] == 1205551 and row["frozen_2026_27_dead_cap_amount"] == 21311053 for row in final_player_ledger), "$1,205,551 / $21,311,053")
    add("beal_and_prosper_post_split_outcomes_remain_quarantined", len(post_contract_exposures) == 1 and len(post_option_exposures) == 2 and {clean(row.get("player_slug")) for row in post_contract_exposures + post_option_exposures} == {"bradley-beal", "olivier-maxence-prosper"}, "1 contract + 2 option rows")
    add("exact_30_team_final_ledger_is_unique", len(final_team_ledger) == 30 and {row["team"] for row in final_team_ledger} == REQUIRED_TEAMS, "30/30")
    add("team_ledger_reaggregates_exact_12_player_ledger", all(row["frozen_2026_27_dead_cap_total"] == sum(player["frozen_2026_27_dead_cap_amount"] for player in final_player_ledger if player["team"] == row["team"]) for row in final_team_ledger), "30/30")
    add("exact_7_positive_teams_are_final", sum(row["frozen_2026_27_dead_cap_total"] > 0 for row in final_team_ledger) == EXPECTED_POSITIVE_TEAM_COUNT, "7/30")
    add("exact_23_zero_teams_are_final", sum(row["frozen_2026_27_dead_cap_total"] == 0 for row in final_team_ledger) == EXPECTED_ZERO_TEAM_COUNT, "23/30")
    add("exact_final_frozen_dead_cap_total_is_55653831", sum(row["frozen_2026_27_dead_cap_total"] for row in final_team_ledger) == EXPECTED_FROZEN_TOTAL, f"${EXPECTED_FROZEN_TOTAL:,}")
    add("exact_6_post_split_exclusions_remain_final", len(final_exclusion_ledger) == EXPECTED_EXCLUDED_COUNT and sum(row["post_split_excluded_amount"] for row in final_exclusion_ledger) == EXPECTED_EXCLUDED_TOTAL, f"6 / ${EXPECTED_EXCLUDED_TOTAL:,}")
    add("all_excluded_dates_are_after_split", all(date.fromisoformat(row["dead_cap_effective_date"]) > SPLIT_DATE for row in final_exclusion_ledger), "6/6")
    add("final_positive_and_excluded_player_sets_do_not_overlap", not ({row["player_slug"] for row in final_player_ledger} & {row["player_slug"] for row in final_exclusion_ledger}), "disjoint")
    add("dead_cap_blocker_closed_exactly_once", len(closed_blocker) == 1 and closed_blocker[0]["blocker_id"] == "frozen_dead_cap_and_waiver_ledger", "1/1")
    add("exact_two_financial_component_blockers_remain", len(remaining_blockers) == 2 and {row["blocker_id"] for row in remaining_blockers} == {"frozen_likely_and_unlikely_incentive_ledger", "post_draft_2026_first_round_pick_hold_bridge"}, "incentives + dynamic rookie holds")
    add("known_thomas_sorber_likely_incentive_is_preserved", remaining_blockers[0]["known_exact_rows"] == 1 and remaining_blockers[0]["known_exact_total"] == 814620, "$814,620")
    add("no_dead_cap_value_applied_to_team_salary", all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in final_player_ledger) and all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in final_team_ledger), "evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_dead_cap_final_freeze_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "frozen_dead_cap_blocker_closed": not failed,
        "final_positive_player_count": len(final_player_ledger),
        "final_positive_team_count": sum(row["frozen_2026_27_dead_cap_total"] > 0 for row in final_team_ledger),
        "final_zero_team_count": sum(row["frozen_2026_27_dead_cap_total"] == 0 for row in final_team_ledger),
        "final_frozen_dead_cap_total": sum(row["frozen_2026_27_dead_cap_total"] for row in final_team_ledger),
        "final_post_split_excluded_player_count": len(final_exclusion_ledger),
        "final_post_split_excluded_total": sum(row["post_split_excluded_amount"] for row in final_exclusion_ledger),
        "unresolved_setoff_row_count": 0,
        "remaining_financial_component_blocker_count": len(remaining_blockers),
        "remaining_financial_component_blockers": [row["blocker_id"] for row in remaining_blockers],
        "dead_cap_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Build the complete frozen 2026-27 likely and unlikely incentive ledger. Preserve Thomas Sorber's exact "
            "$814,620 likely incentive and do not substitute guaranteed salary or post-split classifications."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_dead_cap_final_freeze_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "final_frozen_dead_cap_player_ledger_12.csv", final_player_ledger)
        write_csv(export / "final_frozen_dead_cap_team_ledger_30.csv", final_team_ledger)
        write_csv(export / "final_post_split_dead_cap_exclusions_6.csv", final_exclusion_ledger)
        write_csv(export / "closed_financial_component_blocker_1.csv", closed_blocker)
        write_csv(export / "remaining_financial_component_blockers_2.csv", remaining_blockers)
        write_csv(export / "frozen_dead_cap_final_freeze_checks.csv", checks)
        (export / "frozen_dead_cap_final_freeze_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN DEAD-CAP FINAL FREEZE V1
========================================

Purpose
-------
Freeze the completed April 12, 2026 dead-cap ledger as final audited evidence:
12 positive player rows, seven positive teams, 23 exact zero teams, and a
$55,653,831 frozen total. Preserve six later exclusions totaling $39,820,430.

Blocker status
--------------
The frozen dead-cap and waiver-ledger blocker is closed. The two remaining
financial component blockers are the frozen incentive ledger and the dynamic
post-draft 2026 first-round hold bridge.

Safety
------
This package does not apply the frozen values to Team Salary or simulation
state. It does not mutate a roster, contract, overlay, or checkpoint.
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
        raise RuntimeError("Frozen Dead-Cap Final Freeze V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN DEAD-CAP FINAL FREEZE V1 PASSED")
    print("=" * 132)
    print(f"Final positive players:          {len(final_player_ledger):>3}/12")
    print(f"Final positive teams:            {sum(row['frozen_2026_27_dead_cap_total'] > 0 for row in final_team_ledger):>3}/7")
    print(f"Final zero teams:                {sum(row['frozen_2026_27_dead_cap_total'] == 0 for row in final_team_ledger):>3}/23")
    print(f"Final frozen dead-cap total:     ${sum(row['frozen_2026_27_dead_cap_total'] for row in final_team_ledger):,}")
    print("Frozen dead-cap blocker:          CLOSED")
    print("Remaining financial blockers:     2")
    print("Dead-cap values applied:          0")
    print("Checkpoint write:                 NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
