from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = SRC / "franchise_cpu_autonomous_trade_market_v1.py"
V5B = SRC / "franchise_morale_trade_finder_terms_v1.py"
TRANSACTION = SRC / "franchise_trade_transaction_v1.py"


def _function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ),
        None,
    )
    if node is None:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def main() -> int:
    checks: dict[str, bool] = {}

    for path in (PAGE, MODULE, V5B, TRANSACTION):
        checks[f"{path.name}_exists"] = path.exists()
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                checks[f"{path.name}_compiles"] = True
            except Exception:
                checks[f"{path.name}_compiles"] = False

    page = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    module = MODULE.read_text(encoding="utf-8") if MODULE.exists() else ""
    v5b = V5B.read_text(encoding="utf-8") if V5B.exists() else ""
    runner = _function_source(module, "run_cpu_autonomous_trade_market_v1")

    sim_start = page.find("if simulate_commit_clicked:")
    sim_end = page.find("current_preview_request =", sim_start)
    sim = page[sim_start:sim_end] if sim_start >= 0 and sim_end > sim_start else ""
    league_sync_pos = sim.find("catch_up_cpu_schedule_v1(")
    auto_pos = sim.find("run_cpu_autonomous_trade_market_v1(")
    incoming_pos = sim.find("run_cpu_incoming_trade_offer_tick_v1(")
    final_save_pos = sim.find("set_franchise_state(", incoming_pos)
    next_game_pos = sim.find("next_games = upcoming_controlled_games(")

    checks.update(
        {
            "v5b_dependency_is_current": (
                "franchise-morale-trade-finder-terms-v5b-2026-09-16"
                in v5b
            ),
            "module_imported_in_page": (
                "from franchise_cpu_autonomous_trade_market_v1 import"
                in page
            ),
            "autonomous_tick_runs_after_league_sync": (
                league_sync_pos >= 0
                and auto_pos > league_sync_pos
            ),
            "autonomous_tick_precedes_incoming_offer_and_final_save": (
                auto_pos >= 0
                and incoming_pos > auto_pos
                and final_save_pos > incoming_pos
            ),
            "final_save_precedes_next_controlled_game_selection": (
                final_save_pos >= 0
                and next_game_pos > final_save_pos
            ),
            "league_hub_audit_present": (
                "render_cpu_autonomous_trade_market_v1("
                in page
            ),
            "controlled_teams_are_excluded": (
                "buyer in controlled"
                in runner
                and "seller in controlled"
                in runner
            ),
            "regular_season_guard_present": (
                '_phase(state) != "regular_season"'
                in runner
            ),
            "trade_window_guards_present": (
                "MIN_MEDIAN_GAMES"
                in runner
                and "TRADE_DEADLINE_MEDIAN_GAMES"
                in runner
            ),
            "seven_day_cooldown_present": (
                "TICK_COOLDOWN_DAYS"
                in runner
            ),
            "one_trade_return_after_commit": (
                "return CPUAutonomousTradeTickResult("
                in runner
                and "committed=True"
                in runner
            ),
            "uses_trade_finder": (
                "proposal_generator("
                in runner
            ),
            "uses_live_transaction_commit": (
                "trade_committer("
                in runner
            ),
            "grievance_resolution_present": (
                "_resolve_traded_player_grievance("
                in runner
            ),
            "no_force_trade_or_legality_bypass": (
                "build_franchise_trade_candidate"
                not in runner
                and "evaluate_trade("
                not in runner
            ),
            "transaction_engine_still_contains_rollback": (
                "automatic durable-checkpoint rollback"
                in (
                    TRANSACTION.read_text(encoding="utf-8")
                    if TRANSACTION.exists()
                    else ""
                )
            ),
        }
    )

    failed = [
        name for name, passed in checks.items() if not passed
    ]

    print(
        json.dumps(
            {
                "checks": checks,
                "failed_checks": failed,
                "passed": not failed,
            },
            indent=2,
        )
    )

    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE CPU AUTONOMOUS TRADE MARKET "
        "V6A VALIDATOR PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
