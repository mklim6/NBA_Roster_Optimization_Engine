from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MORALE = SRC / "franchise_morale_chemistry_v1.py"
HQ = SRC / "franchise_roster_rotation_headquarters_v1.py"


def main() -> int:
    morale_text = MORALE.read_text(encoding="utf-8")
    hq_text = HQ.read_text(encoding="utf-8")
    ast.parse(morale_text)
    ast.parse(hq_text)
    checks = {
        "morale_module_compiles": True,
        "hq_module_compiles": True,
        "v1_3_version_present": "franchise-morale-chemistry-v1.3-2026-09-16" in morale_text,
        "promise_review_present": "_evaluate_role_promise_after_game" in morale_text and "review_after_games" in morale_text,
        "broken_promise_memory_present": "broken_promise_games" in morale_text,
        "offseason_grievance_present": "offseason_grievance_games" in morale_text,
        "player_meetings_present": "def hold_player_meeting_v1" in morale_text,
        "meeting_cooldown_present": "meeting_cooldown_games" in morale_text,
        "trade_response_present": "def set_player_trade_response_v1" in morale_text,
        "trade_block_ui_present": "Player meeting & front-office response" in hq_text,
        "promise_deadline_ui_present": "Review promise after games" in hq_text,
        "no_rating_mutation": ".overall_rating =" not in morale_text and ".potential_rating =" not in morale_text,
        "no_forced_trade_engine_call": "commit_trade" not in morale_text and "execute_trade" not in morale_text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit("FRANCHISE MORALE FRONT-OFFICE CONSEQUENCES V3 VALIDATOR FAILED")
    print("FRANCHISE MORALE FRONT-OFFICE CONSEQUENCES V3 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
