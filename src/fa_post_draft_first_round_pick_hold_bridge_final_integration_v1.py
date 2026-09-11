from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-post-draft-first-round-pick-hold-bridge-final-integration-v1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
PREVIEW_PATTERN = "fa_post_draft_first_round_pick_hold_bridge_preview_v1_2026-27_*.zip"
FINAL_INCENTIVE_PATTERN = "fa_frozen_incentive_final_freeze_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
DRAFT_MARKER = "FA_POST_DRAFT_PICK_HOLD_BRIDGE_V1: draft-event hook"
FINANCIAL_MARKER = "FA_POST_DRAFT_PICK_HOLD_BRIDGE_V1: financial-snapshot hook"
SYNTHETIC_PLAYER_ID = "FA-BRIDGE-2026-R1-P30"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


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


def find_passed(root: Path, pattern: str, summary_suffix: str) -> Path:
    valid: list[Path] = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields or [])
    if not fieldnames:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def team_rows(snapshot: Any) -> dict[str, Any]:
    return {clean(row.team).upper(): row for row in snapshot.team_financials}


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    preview_zip = find_passed(root, PREVIEW_PATTERN, "post_draft_pick_hold_bridge_preview_summary.json")
    final_zip = find_passed(root, FINAL_INCENTIVE_PATTERN, "frozen_incentive_final_freeze_summary.json")
    with zipfile.ZipFile(preview_zip) as archive:
        preview_summary = json_suffix(archive, "post_draft_pick_hold_bridge_preview_summary.json")
        preview_checks = csv_suffix(archive, "post_draft_pick_hold_bridge_preview_checks.csv")
        scale_rows = csv_suffix(archive, "official_2026_27_rookie_scale_pick_hold_schedule_30.csv")
    with zipfile.ZipFile(final_zip) as archive:
        final_summary = json_suffix(archive, "frozen_incentive_final_freeze_summary.json")
        final_checks = csv_suffix(archive, "frozen_incentive_final_freeze_checks.csv")

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_financial_cba_bridge_v1 import build_franchise_financial_snapshot
    from franchise_post_draft_first_round_pick_hold_bridge_v1 import (
        STATE_LEDGER_ATTR,
        active_post_draft_first_round_pick_hold_rows,
        active_team_pick_hold_totals,
        sync_post_draft_first_round_pick_hold_ledger,
    )
    from simulation_league_state_v1 import ContractState

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    source_state = checkpoint.simulation_state
    simulation_digest_before = object_digest(source_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before final dynamic bridge integration validation.")

    print("=" * 132)
    print("2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE FINAL INTEGRATION V1")
    print("=" * 132)
    print("Validating the armed draft-event and Team Salary hooks on clone-only states...")

    runtime = load_runtime_data()
    state_before_snapshot = object_digest(source_state)
    baseline_snapshot = build_franchise_financial_snapshot(runtime, source_state)
    baseline_by_team = team_rows(baseline_snapshot)
    state_after_snapshot = object_digest(source_state)
    opening_active = active_post_draft_first_round_pick_hold_rows(source_state)

    clone = copy.deepcopy(source_state)
    teams = sorted(clean(team).upper() for team in clone.teams)
    drafting_team, assigned_team = teams[0], teams[1]
    team_state = clone.teams[drafting_team]
    template_id = next(iter(team_state.roster_player_ids))
    template = copy.deepcopy(clone.players[template_id])
    template.player_id = SYNTHETIC_PLAYER_ID
    template.player_name = "Synthetic 2026 Pick 30 Bridge Validation"
    template.team_abbreviation = drafting_team
    template.two_way = False
    template.synthetic = True
    template.roster_status = "inactive_roster"
    template.contract = ContractState(
        status="rookie_scale_pending",
        salary=None,
        years_remaining=4,
        option_type="rookie_scale",
        guaranteed=True,
    )
    setattr(template, "draft_year", 2026)
    setattr(template, "draft_round", 1)
    setattr(template, "draft_pick", 30)
    setattr(template, "draft_round_pick", 30)
    setattr(template, "drafted_by", drafting_team)
    setattr(template, "generated_prospect", True)
    setattr(template, "draft_class_id", "DRAFT-2026")
    clone.players[SYNTHETIC_PLAYER_ID] = template
    team_state.roster_player_ids = tuple(list(team_state.roster_player_ids) + [SYNTHETIC_PLAYER_ID])

    current = {
        "draft_year": 2026,
        "source_season": "2025-26",
        "target_season": SEASON_LABEL,
        "draft_order": [{
            "overall_pick": 30,
            "round": 1,
            "round_pick": 30,
            "origin_team": drafting_team,
            "owner_team": drafting_team,
            "prospect_id": SYNTHETIC_PLAYER_ID,
            "player_name": template.player_name,
        }],
    }
    first_sync = sync_post_draft_first_round_pick_hold_ledger(clone, current)
    second_sync = sync_post_draft_first_round_pick_hold_ledger(clone, current)
    active_unsigned = active_post_draft_first_round_pick_hold_rows(clone)
    unsigned_snapshot = build_franchise_financial_snapshot(runtime, clone)
    unsigned_by_team = team_rows(unsigned_snapshot)
    unsigned_delta = round(
        unsigned_by_team[drafting_team].modeled_team_salary
        - baseline_by_team[drafting_team].modeled_team_salary,
        2,
    )

    assigned_clone = copy.deepcopy(clone)
    sync_post_draft_first_round_pick_hold_ledger(
        assigned_clone,
        current,
        rights_holder_by_player_id={SYNTHETIC_PLAYER_ID: assigned_team},
    )
    assigned_snapshot = build_franchise_financial_snapshot(runtime, assigned_clone)
    assigned_by_team = team_rows(assigned_snapshot)
    assigned_origin_delta = round(
        assigned_by_team[drafting_team].modeled_team_salary
        - baseline_by_team[drafting_team].modeled_team_salary,
        2,
    )
    assigned_holder_delta = round(
        assigned_by_team[assigned_team].modeled_team_salary
        - baseline_by_team[assigned_team].modeled_team_salary,
        2,
    )

    signed_clone = copy.deepcopy(clone)
    signed_clone.players[SYNTHETIC_PLAYER_ID].contract.status = "under_contract"
    signed_clone.players[SYNTHETIC_PLAYER_ID].contract.salary = 2_439_000
    active_signed = active_post_draft_first_round_pick_hold_rows(signed_clone)
    signed_snapshot = build_franchise_financial_snapshot(runtime, signed_clone)
    signed_by_team = team_rows(signed_snapshot)
    signed_delta = round(
        signed_by_team[drafting_team].modeled_team_salary
        - baseline_by_team[drafting_team].modeled_team_salary,
        2,
    )

    draft_source = (src / "franchise_draft_engine_v1.py").read_text(encoding="utf-8")
    financial_source = (src / "franchise_financial_cba_bridge_v1.py").read_text(encoding="utf-8")
    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating final integration invariants...")
    add("preview_passed_and_ready_for_final_integration", preview_summary.get("passed") is True and preview_summary.get("preview_ready_for_final_integration") is True and all(clean(row.get("status")) == "PASS" for row in preview_checks), preview_zip.name)
    add("final_incentive_freeze_still_has_exactly_one_bridge_blocker", final_summary.get("passed") is True and int(final_summary.get("remaining_financial_component_blocker_count", -1)) == 1 and all(clean(row.get("status")) == "PASS" for row in final_checks), final_zip.name)
    add("rookie_scale_schedule_remains_exactly_30_unique", len(scale_rows) == 30 and {int(row["overall_pick"]) for row in scale_rows} == set(range(1, 31)), "30/30")
    add("draft_event_hook_is_installed_exactly_once", draft_source.count(DRAFT_MARKER) == 1 and "sync_post_draft_first_round_pick_hold_ledger" in draft_source, "1/1")
    add("financial_snapshot_hook_is_installed_exactly_once", financial_source.count(FINANCIAL_MARKER) == 1 and "active_post_draft_first_round_pick_hold_rows" in financial_source, "1/1")
    add("opening_snapshot_has_zero_dynamic_pick_holds", not opening_active and not hasattr(source_state, STATE_LEDGER_ATTR), "0 at 2026-04-12")
    add("financial_snapshot_read_is_state_immutable", state_before_snapshot == state_after_snapshot, state_after_snapshot)
    add("canonical_financial_snapshot_has_exactly_30_teams", len(baseline_by_team) == 30, "30/30")
    add("draft_selection_creates_exactly_one_pick_30_hold", len(first_sync) == len(active_unsigned) == 1 and int(active_unsigned[0]["rookie_scale_cap_hold_amount"]) == 2_926_800, "$2,926,800")
    add("draft_selection_sync_is_idempotent", first_sync == second_sync and len(getattr(clone, STATE_LEDGER_ATTR)) == 1, "1 stable row")
    add("pending_rookie_proxy_is_not_double_counted", unsigned_delta == 2_926_800, f"delta=${unsigned_delta:,.0f}")
    add("pending_rookie_is_not_counted_as_standard_contract", unsigned_by_team[drafting_team].standard_contract_count == baseline_by_team[drafting_team].standard_contract_count, "count unchanged")
    add("hold_is_visible_in_salary_source_summary", unsigned_by_team[drafting_team].salary_source_summary.get("post_draft_first_round_pick_hold_bridge_v1") == 1, "1 bridged hold")
    add("rights_assignment_moves_hold_off_origin_team", assigned_origin_delta == 0, f"origin delta=${assigned_origin_delta:,.0f}")
    add("rights_assignment_moves_hold_to_current_holder", assigned_holder_delta == 2_926_800 and active_team_pick_hold_totals(assigned_clone) == {assigned_team: 2_926_800}, f"{assigned_team} delta=${assigned_holder_delta:,.0f}")
    add("signed_contract_removes_dynamic_hold", not active_signed, "0 active holds")
    add("signed_contract_salary_replaces_hold_once", signed_delta == 2_439_000, f"delta=${signed_delta:,.0f}")
    add("bridge_validation_used_clone_only_state", not hasattr(source_state, STATE_LEDGER_ATTR) and SYNTHETIC_PLAYER_ID not in source_state.players, "canonical state untouched")

    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_after = object_digest(checkpoint_after.simulation_state)
    add("loaded_simulation_state_unchanged", simulation_digest_before == simulation_digest_after == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    scenario_rows = [
        {"scenario": "opening_snapshot", "hold_count": len(opening_active), "team_salary_delta": 0, "result": "PASS" if not opening_active else "FAIL"},
        {"scenario": "post_draft_pick_30_unsigned", "hold_count": len(active_unsigned), "team_salary_delta": unsigned_delta, "result": "PASS" if unsigned_delta == 2_926_800 else "FAIL"},
        {"scenario": "post_draft_rights_assigned", "hold_count": len(active_post_draft_first_round_pick_hold_rows(assigned_clone)), "team_salary_delta": assigned_holder_delta, "result": "PASS" if assigned_origin_delta == 0 and assigned_holder_delta == 2_926_800 else "FAIL"},
        {"scenario": "rookie_contract_signed", "hold_count": len(active_signed), "team_salary_delta": signed_delta, "result": "PASS" if not active_signed and signed_delta == 2_439_000 else "FAIL"},
    ]
    closed_blocker = [{
        "prior_priority": 1,
        "blocker_id": "post_draft_2026_first_round_pick_hold_bridge",
        "resolution": "closed_by_event_driven_120_percent_rookie_scale_hold_bridge",
        "opening_snapshot_hold_count": 0,
        "draft_event_hook_installed": True,
        "financial_snapshot_hook_installed": True,
        "signing_status_removes_hold": True,
        "rights_assignment_moves_hold": True,
        "applied_to_opening_snapshot": False,
    }]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_post_draft_first_round_pick_hold_bridge_final_integration_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output_zip = audit_dir / f"{name}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "passed": not failed,
        "failed_checks": failed,
        "bridge_code_integrated": not failed,
        "opening_snapshot_hold_count": len(opening_active),
        "draft_event_apply_enabled": not failed,
        "rights_assignment_transition_enabled": not failed,
        "signing_status_removal_enabled": not failed,
        "pick_30_hold_validation_amount": 2_926_800,
        "remaining_financial_component_blocker_count": 0 if not failed else 1,
        "remaining_financial_component_blockers": [] if not failed else ["post_draft_2026_first_round_pick_hold_bridge"],
        "financial_component_registry_complete": not failed,
        "canonical_team_salary_mutation_performed": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "next_slice": "Financial evidence and dynamic component blockers are closed. Proceed to the next project section without backfilling the April 12 opening snapshot.",
    }
    readme = f"""2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE FINAL INTEGRATION V1

Result
------
Audit passed: {not failed}
Draft-event hook installed: {draft_source.count(DRAFT_MARKER) == 1}
Financial-snapshot hook installed: {financial_source.count(FINANCIAL_MARKER) == 1}
Opening snapshot holds: {len(opening_active)}
Remaining financial component blockers: {0 if not failed else 1}

Behavior
--------
- A simulated 2026 first-round selection creates its exact 120% rookie-scale hold.
- The pending-player proxy is excluded, preventing double counting.
- The hold follows assignment of draft rights.
- A signed rookie contract replaces the hold with contract salary exactly once.
- The April 12 opening snapshot remains at zero post-draft holds.

Safety
------
The installer patches future event behavior, but validation is clone-only. It did
not mutate the current Team Salary, roster, simulation state, or checkpoint.
"""

    with tempfile.TemporaryDirectory(prefix="fa_post_draft_bridge_final_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "closed_financial_component_blocker_1.csv", closed_blocker)
        write_csv(folder / "remaining_financial_component_blockers_0.csv", [], ["priority", "blocker_id", "required_next_input"])
        write_csv(folder / "final_bridge_clone_validation_scenarios_4.csv", scenario_rows)
        write_csv(folder / "final_bridge_integration_checks.csv", checks)
        (folder / "final_bridge_integration_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE FINAL INTEGRATION V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print(f"Opening snapshot holds:          {len(opening_active)}")
    print(f"Post-draft pick 30 hold:         ${unsigned_delta:,.0f}")
    print(f"Signed replacement salary:       ${signed_delta:,.0f}")
    print(f"Remaining financial blockers:    {0 if not failed else 1}")
    print("Canonical state mutation:        NOT PERFORMED")
    print("Checkpoint write:                NOT PERFORMED")
    print(f"Audit ZIP: {output_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
