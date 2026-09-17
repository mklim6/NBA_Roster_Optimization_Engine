from __future__ import annotations
import ast
import importlib.util
import sys
from pathlib import Path

def _load(path: Path):
    spec = importlib.util.spec_from_file_location("quest_hotfix_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load retention module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_retention_experience_v1.py"
    source = path.read_text(encoding="utf-8")
    module = _load(path)

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["version_is_hotfix"] = (
        "franchise-retention-experience-v1.1.1-quest-lifecycle-hotfix-2026-09-16"
        in module.FRANCHISE_RETENTION_EXPERIENCE_VERSION
    )
    checks["safe_card_helper_present"] = hasattr(module, "_goal_card_html_v1")
    checks["launchpad_requires_zero_games"] = (
        'phase == "offseason" and seasons == 0 and games == 0' in source
    )
    checks["completed_first_campaign_counts_for_retention"] = (
        'if phase == "offseason" and games >= 82:' in source
    )
    checks["simulation_write_absent"] = (
        "save_franchise_checkpoint" not in source
        and "commit_franchise_checkpoint" not in source
    )

    profile = {
        "roster_count": 11,
        "rotation_ready": True,
        "young_core": 4,
    }
    offseason = module._goal_set(
        phase="offseason",
        history_count=1,
        games=82,
        wins=29,
        moves=0,
        profile=profile,
        path="Balanced",
    )
    checks["completed_season_not_open_season"] = offseason[0]["title"] != "Open the season"
    checks["completed_season_uses_next_roster_goal"] = offseason[0]["title"] == "Build the next roster"
    checks["offseason_roster_progress_is_11_of_14"] = (
        offseason[0]["current"] == 11 and offseason[0]["target"] == 14
    )
    checks["offseason_rotation_goal_present"] = offseason[1]["title"] == "Set the next rotation"

    first_launch = module._goal_set(
        phase="offseason",
        history_count=0,
        games=0,
        wins=0,
        moves=0,
        profile={"roster_count": 15, "rotation_ready": True, "young_core": 2},
        path="Balanced",
    )
    checks["true_first_launch_still_open_season"] = first_launch[0]["title"] == "Open the season"

    sample = module._goal_card_html_v1(
        index=2,
        goal=offseason[1],
        is_current=False,
    )
    checks["card_html_single_line"] = "\\n" not in sample and "\\r" not in sample
    checks["card_html_not_escaped"] = "&lt;div" not in sample
    checks["card_html_balanced_divs"] = sample.count("<div") == sample.count("</div>")
    checks["card_html_has_reward"] = "REWARD" in sample

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE QUEST RENDER + LIFECYCLE HOTFIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE QUEST RENDER + LIFECYCLE HOTFIX V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
