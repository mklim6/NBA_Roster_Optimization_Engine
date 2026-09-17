from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
REPORT = ROOT / "outputs" / "franchise_scout_management_tutorial_v1_validation.json"
VERSION = "franchise-scout-management-tutorial-validator-v1.0-2026-09-16"


def compiles(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def main() -> int:
    staff = SRC / "franchise_staff_system_v1.py"
    ui = SRC / "franchise_staff_ui_v1.py"
    onboarding = SRC / "franchise_onboarding_progression_v1.py"
    scouting = SRC / "franchise_scouting_discovery_v1.py"
    draft = SRC / "franchise_draft_engine_v1.py"
    validator = Path(__file__)
    regression = SRC / "run_franchise_scout_management_tutorial_v1_regression.py"
    paths = [staff, ui, onboarding, scouting, draft, PAGE, validator, regression]
    texts = {path: path.read_text(encoding="utf-8") if path.exists() else "" for path in paths}

    checks: dict[str, bool] = {
        "all_files_exist": all(path.exists() for path in paths),
        "all_files_compile": all(path.exists() and compiles(path) for path in paths),
        "staff_system_v12": "franchise-staff-system-v1.2-scout-market-2026-09-16" in texts[staff],
        "staff_history_state": "scouting_history" in texts[staff],
        "market_generator": "def scout_market_candidates" in texts[staff],
        "hire_engine": "def hire_lead_scout" in texts[staff],
        "accuracy_archive": "def archive_completed_scouting_accuracy" in texts[staff],
        "no_active_truth_ui": "hidden_overall" not in texts[ui] and "hidden_potential" not in texts[ui],
        "staff_ui_market": "Scout hiring market" in texts[ui] and "Hire {selected.name}" in texts[ui],
        "staff_ui_track_record": "Scouting track record" in texts[ui],
        "staff_ui_commit_callback": "commit_state=commit_state" not in texts[ui] or "checkpoint_reason=\"franchise-lead-scout-hire-v1\"" in texts[ui],
        "page_passes_commit": "commit_state=set_franchise_state," in texts[PAGE],
        "tutorial_has_scouting_lesson": "Start scouting immediately" in texts[onboarding],
        "tutorial_can_open_draft": "Open Draft scouting now" in texts[onboarding] and 'set_section("Draft Room")' in texts[onboarding],
        "tutorial_is_five_steps": "{step + 1} of 5" in texts[onboarding],
        "draft_archives_accuracy": "archive_completed_scouting_accuracy" in texts[draft],
        "scouting_names_lead_scout": "Lead scout:" in texts[scouting] and "Manage or replace the scout" in texts[scouting],
        "season_long_scouting_preserved": "FRANCHISE_SEASON_LONG_SCOUTING_V1_2" in texts[draft],
    }
    failed = [name for name, passed in checks.items() if not passed]
    report: dict[str, Any] = {"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report)
    if failed:
        print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
