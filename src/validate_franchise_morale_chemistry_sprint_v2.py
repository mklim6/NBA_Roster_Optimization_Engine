from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MORALE = ROOT / "src" / "franchise_morale_chemistry_v1.py"
ROSTER = ROOT / "src" / "franchise_roster_rotation_headquarters_v1.py"


def compiles(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def main() -> int:
    morale_text = MORALE.read_text(encoding="utf-8")
    roster_text = ROSTER.read_text(encoding="utf-8")
    morale_version = re.search(
        r"franchise-morale-chemistry-v1\.(\d+)", morale_text
    )
    checks = {
        "required_files_exist": MORALE.is_file() and ROSTER.is_file(),
        "modules_compile": compiles(MORALE) and compiles(ROSTER),
        "morale_version_supports_v1_1_contract": (
            morale_version is not None and int(morale_version.group(1)) >= 1
        ),
        "legacy_state_attr_preserved": 'MORALE_STATE_ATTR = "franchise_morale_chemistry_v1"' in morale_text,
        "role_promises_persist": 'payload.setdefault("role_promises", {})' in morale_text,
        "recent_game_usage_tracked": '"recent_games"' in morale_text and "MAX_RECENT_GAMES" in morale_text,
        "trade_requests_require_sustained_pressure": "low_morale_games >= 4" in morale_text and "high_risk_games >= 3" in morale_text,
        "trade_request_recovery_exists": 'return "Withdrawn request", False' in morale_text,
        "role_conversation_ui_present": 'with st.expander("Player role conversation"' in roster_text,
        "full_roster_morale_still_present": 'Full morale & role-satisfaction board' in roster_text,
        "morale_reason_explanation_present": 'Why morale is moving' in roster_text,
        "chemistry_pulse_present": 'pulse[0].metric("Chemistry"' in roster_text,
        "trade_status_visible": '"Trade status"' in roster_text,
        "checkpoint_commit_used_for_role_change": 'checkpoint_reason="roster-hq-role-expectation-v1"' in roster_text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit("FRANCHISE MORALE / CHEMISTRY SPRINT V2 VALIDATOR FAILED")
    print("FRANCHISE MORALE / CHEMISTRY SPRINT V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
