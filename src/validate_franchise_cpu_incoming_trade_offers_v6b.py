from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = SRC / "franchise_cpu_incoming_trade_offers_v1.py"
V6A = SRC / "franchise_cpu_autonomous_trade_market_v1.py"
V5B = SRC / "franchise_morale_trade_finder_terms_v1.py"


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

    for path in (PAGE, MODULE, V6A, V5B):
        checks[f"{path.name}_exists"] = path.exists()
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                checks[f"{path.name}_compiles"] = True
            except Exception:
                checks[f"{path.name}_compiles"] = False

    page = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    module = MODULE.read_text(encoding="utf-8") if MODULE.exists() else ""
    generator = _function_source(
        module,
        "run_cpu_incoming_trade_offer_tick_v1",
    )
    renderer = _function_source(
        module,
        "render_cpu_incoming_trade_offer_actions_v1",
    )

    sim_start = page.find("if simulate_commit_clicked:")
    sim_end = page.find('if active_section == "League Stories":', sim_start)
    sim = page[sim_start:sim_end] if sim_start >= 0 and sim_end > sim_start else ""
    auto_pos = sim.find("run_cpu_autonomous_trade_market_v1(")
    incoming_pos = sim.find("run_cpu_incoming_trade_offer_tick_v1(")
    final_save_pos = sim.find("set_franchise_state(", incoming_pos)
    next_game_pos = sim.find("next_games = upcoming_controlled_games(")

    checks.update(
        {
            "v6a_dependency_current": (
                "franchise-cpu-autonomous-trade-market-v6a-2026-09-17"
                in (
                    V6A.read_text(encoding="utf-8")
                    if V6A.exists()
                    else ""
                )
            ),
            "v5b_dependency_current": (
                "franchise-morale-trade-finder-terms-v5b-2026-09-16"
                in (
                    V5B.read_text(encoding="utf-8")
                    if V5B.exists()
                    else ""
                )
            ),
            "module_imported_in_page": (
                "from franchise_cpu_incoming_trade_offers_v1 import"
                in page
            ),
            "incoming_tick_runs_after_v6a": (
                auto_pos >= 0
                and incoming_pos > auto_pos
            ),
            "incoming_tick_runs_before_next_game_selection": (
                incoming_pos >= 0
                and final_save_pos > incoming_pos
                and next_game_pos > final_save_pos
            ),
            "inbox_special_renderer_present": (
                "render_cpu_incoming_trade_offer_actions_v1("
                in page
            ),
            "generic_actions_skipped_for_cpu_offer": (
                "_cpu_offer_rendered_v6b"
                in page
                and "continue"
                in page[
                    page.find("_cpu_offer_rendered_v6b"):
                    page.find("_cpu_offer_rendered_v6b") + 900
                ]
            ),
            "offer_is_nonblocking": (
                "blocking=False"
                in generator
            ),
            "controlled_teams_are_only_offer_recipients": (
                "for user_team in controlled"
                in generator
            ),
            "cpu_teams_exclude_controlled": (
                "resolved in controlled"
                in module
            ),
            "trade_window_guards_present": (
                "MIN_MEDIAN_GAMES"
                in generator
                and "TRADE_DEADLINE_MEDIAN_GAMES"
                in generator
            ),
            "offer_cooldown_present": (
                "OFFER_COOLDOWN_DAYS"
                in generator
            ),
            "one_pending_offer_guard_present": (
                "active_pending = [" in generator
                and "if active_pending:" in generator
                and 'offer.get("status") == "pending"' in generator
            ),
            "accept_uses_live_transaction_engine": (
                "commit_live_franchise_trade("
                in renderer
            ),
            "reject_does_not_commit_trade": (
                'outcome="rejected"'
                in renderer
            ),
            "counter_loads_trade_center_without_commit": (
                "_load_counter_workspace(offer)"
                in renderer
                and 'set_section_callback("Trade Center")'
                in renderer
            ),
            "exact_fingerprint_required_on_accept": (
                "expected_fingerprint="
                in renderer
            ),
            "offer_expiry_present": (
                "_expire_pending_offers"
                in module
                and 'event["status"] = "expired"'
                in module
            ),
        }
    )

    failed = [
        name
        for name, passed in checks.items()
        if not passed
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
        "FRANCHISE CPU INCOMING TRADE OFFERS "
        "V6B VALIDATOR PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
