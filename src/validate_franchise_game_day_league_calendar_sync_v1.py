from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
HELPER = ROOT / "src" / "franchise_game_day_league_calendar_sync_v1.py"
SIMULATOR = ROOT / "src" / "single_game_simulator_v1.py"
STATE = ROOT / "src" / "simulation_league_state_v1.py"
CONTROLLER = ROOT / "src" / "regular_season_simulation_controller_v1.py"


def _function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == name
        ),
        None,
    )
    if node is None:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def main() -> int:
    checks: dict[str, bool] = {}
    for path in (PAGE, HELPER, SIMULATOR, STATE, CONTROLLER):
        checks[f"{path.name}_exists"] = path.exists()
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                checks[f"{path.name}_compiles"] = True
            except Exception:
                checks[f"{path.name}_compiles"] = False

    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    helper_text = HELPER.read_text(encoding="utf-8") if HELPER.exists() else ""
    simulator_text = SIMULATOR.read_text(encoding="utf-8") if SIMULATOR.exists() else ""
    state_text = STATE.read_text(encoding="utf-8") if STATE.exists() else ""
    controller_text = CONTROLLER.read_text(encoding="utf-8") if CONTROLLER.exists() else ""

    catchup_fn = _function_source(helper_text, "catch_up_cpu_schedule_v1")
    sim_fn = _function_source(simulator_text, "simulate_scheduled_game")
    record_fn = _function_source(state_text, "record_completed_game")
    commit_plan_fn = _function_source(
        controller_text,
        "commit_regular_season_simulation_plan",
    )
    commit_fn = _function_source(page_text, "commit_game_transactionally")

    sim_start = page_text.find("if simulate_commit_clicked:")
    sim_end = page_text.find('if active_section == "League Stories":', sim_start)
    sim = page_text[sim_start:sim_end] if sim_start >= 0 and sim_end > sim_start else ""

    commit_pos = sim.find("commit_game_transactionally(")
    catchup_pos = sim.find("_league_sync_report_v1 = catch_up_cpu_schedule_v1(", commit_pos)
    autonomous_pos = sim.find("run_cpu_autonomous_trade_market_v1(", catchup_pos)
    incoming_pos = sim.find("run_cpu_incoming_trade_offer_tick_v1(", autonomous_pos)
    state_pos = sim.find("set_franchise_state(", incoming_pos)

    checks.update({
        "manual_commit_runs_catchup": catchup_pos >= 0,
        "catchup_precedes_markets_and_state_commit": (
            catchup_pos >= 0
            and autonomous_pos > catchup_pos
            and incoming_pos > autonomous_pos
            and state_pos > incoming_pos
        ),
        "game_day_uses_private_transactional_fast_path": (
            "private_transactional_state=True" in sim
        ),
        "batched_checkpoint_reason_present": (
            "franchise-postgame-batched-v6-0-1" in sim
        ),
        "performance_version_present": (
            "franchise-game-day-league-calendar-sync-v1-perf-v7-2026-09-17"
            in helper_text
        ),
        "default_catchup_still_deepcopies_for_source_safety": (
            "else copy.deepcopy(state)" in catchup_fn
        ),
        "private_catchup_reuses_existing_working_state": (
            "if private_transactional_state" in catchup_fn
        ),
        "catchup_is_direct_chronological_cpu_batch": (
            "_cpu_games_to_catch_up(" in catchup_fn
            and "simulate_game(" in catchup_fn
            and "advance_franchise_scope(" not in catchup_fn
        ),
        "catchup_defers_per_game_global_validation": (
            "_defer_global_state_validation=True" in catchup_fn
        ),
        "catchup_validates_once_after_batch": (
            "state_validator(working)" in catchup_fn
        ),
        "simulator_reuses_regulation_plan_when_no_ot": (
            "if overtime_periods:" in sim_fn
            and "home_plan = home_regulation_plan" in sim_fn
            and "away_plan = away_regulation_plan" in sim_fn
        ),
        "simulator_marks_completed_game_already_validated": (
            "_completed_game_already_validated=True" in sim_fn
        ),
        "record_completed_game_supports_deferred_validation": (
            "_defer_global_state_validation" in record_fn
            and "if not _defer_global_state_validation:" in record_fn
        ),
        "controller_batch_defers_validation_per_game": (
            "_defer_global_state_validation=True" in commit_plan_fn
        ),
        "controller_still_validates_batch_at_end": (
            "validate_simulation_league_state(" in commit_plan_fn
        ),
        "user_game_commit_defers_inner_global_validation": (
            "_defer_global_state_validation=True" in commit_fn
            and "validate_simulation_league_state(" in commit_fn
        ),
        "postgame_timing_is_recorded": (
            "franchise_last_game_day_performance_v7" in sim
        ),
    })

    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit(1)
    print("FRANCHISE GAME-DAY LEAGUE CALENDAR SYNC V1 / PERFORMANCE V7 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
