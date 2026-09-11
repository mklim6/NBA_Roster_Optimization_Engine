from __future__ import annotations

import json
import py_compile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RUNNER = SRC / "run_franchise_protected_lifecycle_boundary_regression_v1.py"
OUTPUT = ROOT / "outputs" / "franchise_protected_lifecycle_boundary_regression_v1_validator.json"
VERSION = "franchise-protected-lifecycle-boundary-regression-validator-v1.2-2026-09-10"


def main() -> int:
    text = RUNNER.read_text(encoding="utf-8") if RUNNER.is_file() else ""
    checks = {
        "runner_exists": RUNNER.is_file(),
        "runner_compiles": True,
        "step2a_isolation_harness_available": (SRC / "run_franchise_protected_launch_smoke_v1.py").is_file(),
        "step2b_transaction_harness_available": (SRC / "run_franchise_protected_transaction_regression_v1.py").is_file(),
        "sep7_freeze_manifest_available": (ROOT / "app_data" / "nba_sep7_release_freeze_v1.json").is_file(),
        "runner_reuses_tested_isolated_checkpoint_context": "_isolated_checkpoint_contract" in text,
        "runner_hashes_active_checkpoint_family": "_checkpoint_family_hashes" in text,
        "runner_requires_release_freeze": "_validate_release_freeze" in text,
        "runner_launches_frozen_live_start": "commit_live_franchise_start" in text,
        "runner_mirrors_ui_staff_initialization": "ensure_franchise_staff_state(live_cp.simulation_state)" in text,
        "runner_persists_staff_before_season": "staff_initialization_survives_reload" in text,
        "runner_requires_exact_staff_signature_at_boundary": "final_staff_signature == staff_source_signature" in text,
        "runner_opens_regular_season_durably": "commit_opening_regular_season_live" in text,
        "runner_simulates_regular_season_remainder": "SimulationScope.REMAINDER" in text,
        "runner_requires_all_1230_games": "regular_season_simulated_all_1230_games" in text,
        "runner_reloads_completed_regular_season": "regular_season_complete_survives_reload" in text,
        "runner_initializes_postseason": "initialize_postseason" in text,
        "runner_reloads_postseason_initialization": "postseason_initialization_survives_reload" in text,
        "runner_sims_to_champion": "PostseasonSimulationScope.TO_CHAMPION" in text,
        "runner_reloads_completed_postseason": "completed_postseason_survives_reload" in text,
        "runner_commits_completed_season_closeout": "commit_completed_season_contract_closeout_durably" in text,
        "runner_executes_canonical_cpu_free_agency_stage": "execute_cpu_free_agency_round_durably" in text,
        "runner_bounds_cpu_free_agency_rounds": "for round_index in range(1, 7)" in text,
        "runner_requires_cpu_roster_floor_before_draft": "cpu_free_agency_reaches_game_roster_floor_before_draft" in text,
        "runner_runs_complete_draft": "simulate_rest_of_draft" in text,
        "runner_reloads_completed_draft": "draft_complete_survives_reload" in text,
        "runner_runs_certified_post_draft_trim": "commit_atomic_cpu_post_draft_trim_live" in text,
        "runner_builds_next_season_transition": "commit_season_transition_preview" in text,
        "runner_uses_live_career_lifecycle_adapter": (
            "from career_lifecycle_transition_adapter_v1 import" in text
            and "career_lifecycle_adapter_active" in text
            and "retirement_population_matches_preview" in text
        ),
        "runner_activates_drafted_rookies": "activate_drafted_rookies_after_transition" in text,
        "runner_generates_next_1230_game_schedule": "generate_regular_season_schedule" in text and "next_season_candidate_has_1230_games" in text,
        "runner_commits_atomic_season_boundary": "commit_atomic_season_boundary_live" in text,
        "runner_reloads_next_season": "next_season_atomic_commit_survives_reload" in text,
        "runner_checks_completed_season_archive": "completed_season_archived" in text,
        "runner_performs_second_target_roundtrip": "next_season_second_roundtrip_exact" in text,
        "runner_restores_clean_live_fixture": "clean_frozen_live_start_restores_exactly" in text,
        "runner_requires_active_checkpoint_unchanged": "active_checkpoint_family_unchanged" in text,
        "runner_preserves_failure_artifacts": "isolated_artifacts_preserved" in text,
    }
    if RUNNER.is_file():
        try:
            py_compile.compile(str(RUNNER), doraise=True)
        except Exception:
            checks["runner_compiles"] = False
    else:
        checks["runner_compiles"] = False

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE PROTECTED LIFECYCLE BOUNDARY REGRESSION HARNESS V1 FAILED")
        return 1
    print("FRANCHISE PROTECTED LIFECYCLE BOUNDARY REGRESSION HARNESS V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
