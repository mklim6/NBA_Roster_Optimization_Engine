from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "src" / "run_franchise_protected_multi_season_soak_v1.py"
VERSION = "franchise-protected-multi-season-soak-validator-v1.1-2026-09-10"


def main() -> int:
    text = RUNNER.read_text(encoding="utf-8") if RUNNER.exists() else ""
    compile_ok = False
    try:
        ast.parse(text)
        py_compile.compile(str(RUNNER), doraise=True)
        compile_ok = True
    except Exception:
        pass

    checks = {
        "runner_exists": RUNNER.is_file(),
        "runner_compiles": compile_ok,
        "default_soak_is_eight_seasons": "DEFAULT_SEASONS = 8" in text,
        "soak_is_capped_at_ten_seasons": "MAX_SEASONS = 10" in text,
        "runner_reuses_tested_checkpoint_isolation": "_isolated_checkpoint_contract" in text,
        "runner_hashes_active_checkpoint_family": "_checkpoint_family_hashes" in text,
        "runner_requires_sep7_release_freeze": "_validate_release_freeze" in text,
        "runner_launches_frozen_live_start": "commit_live_franchise_start" in text,
        "runner_initializes_staff_once": "ensure_franchise_staff_state" in text,
        "runner_opens_initial_regular_season": "commit_opening_regular_season_live" in text,
        "runner_sims_full_regular_season_each_cycle": "SimulationScope.REMAINDER" in text,
        "runner_sims_postseason_to_champion_each_cycle": "PostseasonSimulationScope.TO_CHAMPION" in text,
        "runner_commits_contract_closeout_each_cycle": "commit_completed_season_contract_closeout_durably" in text,
        "runner_executes_cpu_free_agency_each_cycle": "execute_cpu_free_agency_round_durably" in text,
        "runner_requires_roster_floor": "cpu_free_agency_reaches_roster_floor" in text,
        "runner_executes_complete_draft_each_cycle": "simulate_rest_of_draft" in text,
        "runner_tracks_clippers_forfeiture_draft_sizes": "EXPECTED_FORFEIT_DRAFT_SIZES" in text and "2029: 59" in text and "2033: 59" in text,
        "runner_commits_post_draft_trim_each_cycle": "commit_atomic_cpu_post_draft_trim_live" in text,
        "runner_generates_next_1230_game_schedule": "generate_regular_season_schedule" in text and "install_regular_season_schedule" in text,
        "runner_uses_live_career_lifecycle_adapter": (
            "from career_lifecycle_transition_adapter_v1 import" in text
            and "career_lifecycle_adapter_active" in text
            and "retirement_population_matches_preview" in text
        ),
        "runner_commits_atomic_boundary_each_cycle": "commit_atomic_season_boundary_live" in text,
        "runner_validates_trade_and_simulation_state": "validate_simulation_league_state" in text and "validate_state" in text,
        "runner_requires_generated_player_trade_registry_coverage": (
            "boundary_trade_registry_covers_non_synthetic_players" in text
            and "_trade_registry_covers_non_synthetic_players(" in text
        ),
        "runner_checks_staff_signature_each_boundary": "staff_signature_stable" in text,
        "runner_checks_completed_games_reset": "new_season_has_zero_completed_games" in text,
        "runner_checks_standings_reset": "new_season_standings_reset" in text,
        "runner_saves_boundary_snapshots": 'season_snapshot = run_root / "cp"' in text,
        "runner_writes_partial_progress_report": "_write_partial(report)" in text,
        "runner_handles_keyboard_interrupt": "except KeyboardInterrupt" in text,
        "runner_restores_clean_frozen_fixture": "clean_frozen_live_start_restores_exactly" in text,
        "runner_requires_active_save_unchanged": "active_checkpoint_family_unchanged" in text,
        "runner_prints_stage_progress": "Progress is printed at every major lifecycle stage." in text,
        "runner_uses_short_windows_safe_run_root": 'RUNS = ROOT / "outputs" / "_soak"' in text and 'run_root = RUNS / f"r{_stamp()}"' in text,
        "runner_uses_short_per_season_recovery_paths": all(token in text for token in ['season_dir / "c"', 'season_dir / f"f{round_index}"', 'season_dir / "t"', 'season_dir / "b"']),
        "runner_captures_exception_traceback": 'report["details"]["exception_traceback"] = traceback.format_exc()' in text,
    }
    failed = [k for k,v in checks.items() if not v]
    report = {"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    print()
    if failed:
        print("FRANCHISE PROTECTED MULTI-SEASON SOAK HARNESS V1 FAILED")
        return 1
    print("FRANCHISE PROTECTED MULTI-SEASON SOAK HARNESS V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
