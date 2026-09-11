from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    tree = ast.parse(text)

    transition_source = ""
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "advance_to_next_season_with_schedule"
        ):
            transition_source = (
                ast.get_source_segment(text, node) or ""
            )
            break

    checks = {
        "durable_gate_present": (
            "def _draft_completion_gate_v1_1_4("
            in text
        ),
        "transition_uses_durable_gate": (
            "_draft_completion_gate_v1_1_4(state)"
            in transition_source
        ),
        "transition_old_guard_removed": (
            "draft_is_complete(state)"
            not in transition_source
        ),
        "ui_uses_durable_gate": (
            "_draft_gate_ready_v1_1_5"
            in text
        ),
        "all_stale_guards_removed": (
            "if not draft_is_complete(state):"
            not in text
        ),
        "sanction_aware_pick_gate_retained": (
            "expected_draft_pick_count("
            in text
            and "if total_picks != expected_picks:"
            in text
        ),
        "all_picks_gate_retained": (
            "if completed_picks != total_picks:"
            in text
        ),
        "diagnostic_retained": (
            "Draft-state diagnostic:"
            in text
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    print("DRAFT V1.1.5 CHECKS")
    for name, passed in checks.items():
        print(
            f"  {name}: "
            + ("PASS" if passed else "FAIL")
        )

    if failed:
        raise AssertionError(
            "Draft V1.1.5 validation failed: "
            + ", ".join(failed)
        )

    print()
    print(
        "FRANCHISE DRAFT ENGINE V1.1.5 "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
