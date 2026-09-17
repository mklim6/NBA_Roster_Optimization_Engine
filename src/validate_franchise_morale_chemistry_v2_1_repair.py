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
    roster_version = re.search(
        r"franchise-roster-rotation-headquarters-v1\.(\d+)", roster_text
    )
    checks = {
        "required_files_exist": MORALE.is_file() and ROSTER.is_file(),
        "modules_compile": compiles(MORALE) and compiles(ROSTER),
        "morale_version_supports_v1_2_contract": (
            morale_version is not None and int(morale_version.group(1)) >= 2
        ),
        "roster_version_supports_v1_3_contract": (
            roster_version is not None and int(roster_version.group(1)) >= 3
        ),
        "legacy_state_attr_preserved": 'MORALE_STATE_ATTR = "franchise_morale_chemistry_v1"' in morale_text,
        "individual_game_adjustment_present": "def _game_personal_adjustment" in morale_text and "personal_game_adjustment" in morale_text,
        "rotation_emphasis_persists": 'payload.setdefault("rotation_emphasis", {})' in morale_text and "set_rotation_emphasis_v1(updated, resolved, philosophy)" in roster_text,
        "auto_role_uses_derived_minutes": 'elif role_choice == "Auto":' in roster_text and 'default_minutes = current_expectation["minutes"]' in roster_text,
        "short_metric_labels_present": 'metric("Role fit"' in roster_text and 'metric("Trade asks"' in roster_text,
        "reason_cards_replace_wide_table": "morale-reason-grid" in roster_text and 'Reason 1' not in roster_text,
        "recent_minutes_empty_state_clean": (
            'else "—"' in roster_text
            or '_num(row.get("recent_minutes"), float("nan"))' in roster_text
        ),
        "role_promises_preserved": 'payload.setdefault("role_promises", {})' in morale_text,
        "trade_request_guardrails_preserved": "low_morale_games >= 4" in morale_text and "high_risk_games >= 3" in morale_text,
        "role_conversation_preserved": 'with st.expander("Player role conversation"' in roster_text,
        "full_morale_board_preserved": 'Full morale & role-satisfaction board' in roster_text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit("FRANCHISE MORALE / CHEMISTRY V2.1 REPAIR VALIDATOR FAILED")
    print("FRANCHISE MORALE / CHEMISTRY V2.1 REPAIR VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
