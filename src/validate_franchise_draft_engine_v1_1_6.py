from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"


def main() -> int:
    text = PAGE.read_text(
        encoding="utf-8"
    )
    tree = ast.parse(text)

    transition_source = ""
    for node in tree.body:
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "advance_to_next_season_with_schedule"
        ):
            transition_source = (
                ast.get_source_segment(
                    text,
                    node,
                )
                or ""
            )
            break

    checks = {
        "v116_status_helper_present": (
            "def _draft_transition_status_v1_1_6("
            in text
        ),
        "v116_gate_present": (
            "def _draft_completion_gate_v1_1_6("
            in text
        ),
        "source_season_mode": (
            '"normal_transition"'
            in text
        ),
        "target_season_mode": (
            '"target_already_transitioned"'
            in text
        ),
        "label_drift_recovery_mode": (
            '"repair_season_label_then_transition"'
            in text
        ),
        "no_double_advance_recovery": (
            "recovered_existing_target=True"
            in transition_source
        ),
        "rookie_activation_retained": (
            "activate_drafted_rookies_after_transition"
            in transition_source
        ),
        "schedule_install_is_idempotent": (
            "if not transitioned.schedule:"
            in transition_source
        ),
        "old_v114_gate_removed": (
            "_draft_completion_gate_v1_1_4("
            not in text
        ),
        "sanction_aware_pick_requirement_retained": (
            "expected_draft_pick_count("
            in text
            and "if total_picks != expected_picks:"
            in text
        ),
        "all_selected_requirement_retained": (
            "if completed_picks != total_picks:"
            in text
        ),
    }

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]

    print("DRAFT V1.1.6 CHECKS")
    for name, passed in checks.items():
        print(
            f"  {name}: "
            + (
                "PASS"
                if passed
                else "FAIL"
            )
        )

    if failed:
        raise AssertionError(
            "Draft V1.1.6 validation failed: "
            + ", ".join(failed)
        )

    print()
    print(
        "FRANCHISE DRAFT ENGINE V1.1.6 "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
