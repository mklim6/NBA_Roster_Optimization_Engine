from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")

    checks = {
        "durable_gate_present": "def _draft_completion_gate_v1_1_4(" in text,
        "direct_draft_state_read": '"franchise_draft_state_v1"' in text,
        "phase_complete_required": 'phase != "draft_complete"' in text,
        "sanction_aware_pick_reconciliation": (
            "expected_draft_pick_count(" in text
            and "if total_picks != expected_picks:" in text
        ),
        "all_picks_selected": "if completed_picks != total_picks:" in text,
        "source_season_guard": "source_season != current_season" in text,
        "diagnostic_error": "Draft-state diagnostic:" in text,
        "old_bound_guard_removed": "if not draft_is_complete(state):" not in text,
    }

    failed = [name for name, passed in checks.items() if not passed]

    print("DRAFT V1.1.4 CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: " + ("PASS" if passed else "FAIL"))

    if failed:
        raise AssertionError(
            "Draft V1.1.4 validation failed: " + ", ".join(failed)
        )

    print()
    print("FRANCHISE DRAFT ENGINE V1.1.4 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
