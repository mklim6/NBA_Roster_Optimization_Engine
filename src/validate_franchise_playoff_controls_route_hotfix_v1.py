from __future__ import annotations

from pathlib import Path
import ast
import importlib.util
import sys

def main() -> int:
    project = Path.cwd()
    target = project / "src" / "franchise_onboarding_progression_v1.py"
    page = project / "pages" / "5_Franchise_Mode.py"

    checks = {}
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    checks["onboarding_source_exists"] = target.exists()
    checks["playoff_button_targets_game_day"] = (
        '"Game Day", "Open playoff controls"' in text
    )
    checks["old_dead_route_removed"] = (
        '"Command Center", "Open playoff controls"' not in text
    )

    try:
        ast.parse(text)
        checks["onboarding_python_compiles"] = True
    except Exception:
        checks["onboarding_python_compiles"] = False

    page_text = page.read_text(encoding="utf-8") if page.exists() else ""
    checks["game_day_routes_completed_regular_season_to_postseason"] = (
        'if active_section == "Game Day"' in page_text
        and "render_postseason_game_day(" in page_text
        and "regular_season_is_complete(" in page_text
    )

    # Pure function fixture: confirm postseason next action now resolves to Game Day.
    try:
        spec = importlib.util.spec_from_file_location(
            "_playoff_route_fixture",
            target,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        result = module._next_action(
            phase_name="regular_season",
            has_history=False,
            regular_season_complete=True,
            postseason_complete=False,
            draft_complete=False,
            blocking_count=0,
            next_game_id=None,
        )
        checks["postseason_fixture_target_is_game_day"] = (
            isinstance(result, tuple)
            and len(result) >= 4
            and result[2] == "Game Day"
            and result[3] == "Open playoff controls"
        )
    except Exception:
        checks["postseason_fixture_target_is_game_day"] = False

    failed = [name for name, ok in checks.items() if not ok]
    result = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(result)
    if failed:
        print("FRANCHISE PLAYOFF CONTROLS ROUTE HOTFIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE PLAYOFF CONTROLS ROUTE HOTFIX V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
