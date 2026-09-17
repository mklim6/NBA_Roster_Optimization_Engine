from __future__ import annotations

import hashlib
import json
import py_compile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"

PAGE = PAGES / "5_Franchise_Mode.py"
MODULE = SRC / "franchise_game_flow_v1.py"
V4_MODULE = SRC / "franchise_visual_overhaul_v4.py"
REPORT = OUTPUTS / "franchise_game_flow_v1_validation.json"

VALIDATOR_VERSION = "franchise-game-flow-v1-validator-2026-09-11"
EXPECTED_V4_SHA256 = "ae9e5b5ce3f7b0355c7766c812a67a84ab607be868ee5692b4c1af15d9c07546"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _compile(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError:
        return False
    return True


def run_validation() -> dict[str, Any]:
    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    module_text = MODULE.read_text(encoding="utf-8") if MODULE.exists() else ""

    checks = {
        "page_exists": PAGE.exists(),
        "module_exists": MODULE.exists(),
        "page_compiles": PAGE.exists() and _compile(PAGE),
        "module_compiles": MODULE.exists() and _compile(MODULE),
        "v4_visual_module_unchanged": V4_MODULE.exists() and _sha256(V4_MODULE) == EXPECTED_V4_SHA256,
        "game_flow_version_current": "franchise-game-flow-v1.0-2026-09-11" in module_text,
        "game_flow_imported": (
            "from franchise_game_flow_v1 import" in page_text
            or "from franchise_game_flow_runtime_bridge_v1 import" in page_text
        ),
        "game_flow_visuals_injected": "inject_franchise_game_flow_visuals_v1(" in page_text,
        "game_flow_panel_rendered": "render_franchise_game_flow_v1(" in page_text,
        "next_game_navigation_preserved": 'set_franchise_section("Game Day")' in page_text,
        "full_schedule_navigation_present": 'set_franchise_section("Calendar")' in page_text,
        "blocking_decision_navigation_present": 'set_franchise_section("Inbox & League Health")' in page_text,
        "quick_day_maps_to_existing_scope": '"next_day": SimulationScope.NEXT_DAY' in page_text,
        "quick_week_maps_to_existing_scope": '"next_week": SimulationScope.NEXT_WEEK' in page_text,
        "quick_remainder_maps_to_existing_scope": '"remainder": SimulationScope.REMAINDER' in page_text,
        "advance_still_uses_existing_engine": "advance_franchise_scope(" in page_text,
        "legacy_next_day_control_preserved": '"Next day"' in page_text,
        "legacy_next_week_control_preserved": '"Next week"' in page_text,
        "legacy_season_control_preserved": 'key="franchise_season_end"' in page_text,
        "legacy_controls_collapsed": 'with st.expander("Advanced simulation controls", expanded=False):' in page_text,
        "retention_system_preserved": "render_franchise_retention_hub_v1(" in page_text,
        "game_day_broadcast_preserved": "render_game_day_broadcast_v1(" in page_text,
        "v4_schedule_rail_preserved": "render_schedule_ribbon_v4(" in page_text,
        "active_save_mutation_not_added": "replace_active" not in module_text and "save_checkpoint" not in module_text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "version": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    result = run_validation()
    print(json.dumps(result, indent=2))
    print()
    if result["passed"]:
        print("FRANCHISE GAME FLOW V1 VALIDATOR PASSED")
        return 0
    print("FRANCHISE GAME FLOW V1 VALIDATOR FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
