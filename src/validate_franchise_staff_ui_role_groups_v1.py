from __future__ import annotations

from pathlib import Path
import ast
import json

VALIDATOR_VERSION = "franchise-staff-ui-role-groups-v1-validator-2026-09-16"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "src" / "franchise_staff_ui_v1.py"
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    compile_ok = False
    if text:
        try:
            ast.parse(text, filename=str(target))
            compile_ok = True
        except SyntaxError:
            compile_ok = False

    checks = {
        "staff_ui_exists": target.is_file(),
        "staff_ui_compiles": compile_ok,
        "v1_3_role_group_version_present": "franchise-staff-ui-v1.3-role-groups-2026-09-16" in text,
        "coaching_group_present": '"🏀 Coaching"' in text,
        "development_health_group_present": '"🩺 Development & Health"' in text,
        "scouting_group_present": '"🔎 Scouting"' in text,
        "role_masks_present": all(marker in text for marker in (
            "development_health_mask", "scouting_mask", "coaching_mask"
        )),
        "role_specific_columns_present": all(marker in text for marker in (
            "coaching_columns", "development_columns", "scouting_columns"
        )),
        "uncertainty_caption_present": "Expected error ±" in text,
        "lower_error_explanation_present": "Lower ± values mean tighter expected scouting uncertainty." in text,
        "old_metric_delta_removed": 'f"±{scouting_error_band(state, team):.1f} expected band"' not in text,
        "scout_hiring_preserved": "hire_lead_scout(state, team, selected_id)" in text,
        "track_record_preserved": "scouting_track_record_rows(state, team)" in text,
        "organization_impact_preserved": "### Organization impact" in text,
        "league_staff_comparison_preserved": "League staff comparison" in text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {"validator": VALIDATOR_VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        print("FRANCHISE STAFF UI ROLE GROUPS V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE STAFF UI ROLE GROUPS V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
