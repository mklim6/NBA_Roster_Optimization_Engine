from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
V6A = SRC / "franchise_cpu_autonomous_trade_market_v1.py"
V6B = SRC / "franchise_cpu_incoming_trade_offers_v1.py"


def _function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    node = next((item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name), None)
    if node is None:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def main() -> int:
    checks = {}
    for path in (PAGE, V6A, V6B):
        checks[f"{path.name}_exists"] = path.exists()
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                checks[f"{path.name}_compiles"] = True
            except Exception:
                checks[f"{path.name}_compiles"] = False

    page = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    a = V6A.read_text(encoding="utf-8") if V6A.exists() else ""
    b = V6B.read_text(encoding="utf-8") if V6B.exists() else ""
    a_run = _function_source(a, "run_cpu_autonomous_trade_market_v1")
    b_run = _function_source(b, "run_cpu_incoming_trade_offer_tick_v1")
    sim_start = page.find("if simulate_commit_clicked:")
    sim_end = page.find("current_preview_request =", sim_start)
    sim = page[sim_start:sim_end]

    checks.update({
        "page_hotfix_marker": "FRANCHISE_POSTGAME_PERFORMANCE_HOTFIX_V6_0_1" in page,
        "v6a_perf_marker": "franchise-cpu-autonomous-trade-market-v6a-perf-v6-0-1-2026-09-17" in a,
        "v6b_perf_marker": "franchise-cpu-incoming-trade-offers-v6b-perf-v6-0-1-2026-09-17" in b,
        "v6a_deepcopy_after_cooldown": a_run.find("copy.deepcopy(state)") > a_run.find("day - last_tick < TICK_COOLDOWN_DAYS"),
        "v6b_deepcopy_after_scan_guard": b_run.find("copy.deepcopy(state)") > b_run.find("day - last_scan_day < OFFER_SCAN_INTERVAL_DAYS"),
        "v6b_two_day_retry": "OFFER_SCAN_INTERVAL_DAYS = 2" in b,
        "v6b_two_team_scan": "MAX_CPU_TEAMS_SCANNED = 2" in b,
        "incoming_status_renderer": "render_cpu_incoming_trade_offer_market_status_v1(" in page,
        "one_postgame_checkpoint": sim.count("set_franchise_state(") == 1,
        "batched_checkpoint_reason": "franchise-postgame-batched-v6-0-1" in sim,
        "league_sync_preserved": "catch_up_cpu_schedule_v1(" in sim,
        "v6a_preserved": "run_cpu_autonomous_trade_market_v1(" in sim,
        "v6b_preserved": "run_cpu_incoming_trade_offer_tick_v1(" in sim,
    })
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit(1)
    print("FRANCHISE POSTGAME PERFORMANCE / OFFER HOTFIX V6.0.1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
