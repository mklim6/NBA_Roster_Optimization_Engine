from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "franchise_roster_rotation_headquarters_v1.py"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    ast.parse(text, filename=str(TARGET))
    checks = {
        "roster_hq_compiles": True,
        "v3_consequences_preserved": "franchise-roster-rotation-headquarters-v1.4-consequences-2026-09-16" in text,
        "recent_min_uses_numeric_helper": '"Recent MIN": _num(row.get("recent_minutes"), float("nan"))' in text,
        "recent_min_string_float_mix_removed": 'else "—"' not in "\n".join(
            line for line in text.splitlines() if "Recent MIN" in line
        ),
        "player_meeting_ui_preserved": "Player meeting & front-office response" in text,
        "role_conversation_preserved": "Player role conversation" in text,
        "full_morale_board_preserved": "Full morale & role-satisfaction board" in text,
    }
    failed = [name for name, value in checks.items() if not value]
    report = {"checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(report, indent=2))
    if failed:
        raise RuntimeError("FRANCHISE MORALE V3.0.1 ARROW HOTFIX VALIDATOR FAILED")
    print("FRANCHISE MORALE V3.0.1 ARROW HOTFIX VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
