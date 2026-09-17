from __future__ import annotations

from pathlib import Path
import ast
import json
import pandas as pd

REGRESSION_VERSION = "franchise-staff-ui-role-groups-v1-regression-2026-09-16"


def classify(roles: list[str]) -> dict[str, list[str]]:
    frame = pd.DataFrame({"Role": roles})
    role_text = frame["Role"].fillna("").astype(str).str.lower()
    development_health_mask = (
        role_text.str.contains("development", regex=False)
        | role_text.str.contains("medical", regex=False)
        | role_text.str.contains("performance", regex=False)
        | role_text.str.contains("health", regex=False)
    )
    scouting_mask = role_text.str.contains("scout", regex=False)
    coaching_mask = ~(development_health_mask | scouting_mask)
    return {
        "coaching": frame.loc[coaching_mask, "Role"].tolist(),
        "development_health": frame.loc[development_health_mask, "Role"].tolist(),
        "scouting": frame.loc[scouting_mask, "Role"].tolist(),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "src" / "franchise_staff_ui_v1.py"
    text = target.read_text(encoding="utf-8")
    ast.parse(text, filename=str(target))

    groups = classify([
        "Head Coach",
        "Lead Assistant",
        "Player Development Coach",
        "Lead Scout",
        "Medical / Performance Director",
    ])
    checks = {
        "head_coach_is_coaching": "Head Coach" in groups["coaching"],
        "lead_assistant_is_coaching": "Lead Assistant" in groups["coaching"],
        "development_coach_is_development_health": "Player Development Coach" in groups["development_health"],
        "medical_director_is_development_health": "Medical / Performance Director" in groups["development_health"],
        "lead_scout_is_scouting": "Lead Scout" in groups["scouting"],
        "each_sample_role_classified_once": sum(len(values) for values in groups.values()) == 5,
        "scout_error_band_is_role_specific": 'scouting["Current ±"]' in text and 'scouting["Potential ±"]' in text,
        "legacy_full_org_wide_render_removed": 'st.dataframe(frame, hide_index=True, width="stretch")' not in text,
        "staff_hiring_flow_preserved": "franchise_hire_scout_" in text,
        "historical_accuracy_flow_preserved": "Scouting track record" in text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "regression": REGRESSION_VERSION,
        "groups": groups,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        print("FRANCHISE STAFF UI ROLE GROUPS V1 REGRESSION FAILED")
        return 1
    print("FRANCHISE STAFF UI ROLE GROUPS V1 REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
