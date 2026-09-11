from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
ENGINE = SRC / "franchise_draft_engine_v1.py"

sys.path.insert(
    0,
    str(SRC),
)


def function_source(
    text: str,
    name: str,
) -> str:
    tree = ast.parse(text)
    matches = [
        node
        for node in tree.body
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == name
        )
    ]

    if len(matches) != 1:
        raise AssertionError(
            f"Expected one {name}, found {len(matches)}."
        )

    return (
        ast.get_source_segment(
            text,
            matches[0],
        )
        or ""
    )


def main() -> int:
    page_text = PAGE.read_text(
        encoding="utf-8"
    )
    engine_text = ENGINE.read_text(
        encoding="utf-8"
    )

    importlib.invalidate_caches()
    sys.modules.pop(
        "franchise_draft_engine_v1",
        None,
    )

    engine = importlib.import_module(
        "franchise_draft_engine_v1"
    )

    stale_draft = {
        "draft_year": 2029,
        "source_season": "2028-29",
        "target_season": "2029-30",
        "phase": "draft_complete",
    }

    consumed_state = SimpleNamespace(
        settings=SimpleNamespace(
            season_label="2029-30",
        ),
        season_history=[
            SimpleNamespace(
                season_label="2028-29",
            )
        ],
        franchise_draft_state_v1=stale_draft,
    )

    partial_recovery_state = SimpleNamespace(
        settings=SimpleNamespace(
            season_label="2029-30",
        ),
        season_history=[],
        franchise_draft_state_v1=stale_draft,
    )

    active_2030 = {
        "draft_year": 2030,
        "source_season": "2029-30",
        "target_season": "2030-31",
        "phase": "lottery_ready",
    }
    active_state = SimpleNamespace(
        settings=SimpleNamespace(
            season_label="2029-30",
        ),
        season_history=[
            SimpleNamespace(
                season_label="2028-29",
            )
        ],
        franchise_draft_state_v1=active_2030,
    )

    transition_source = function_source(
        page_text,
        "advance_to_next_season_with_schedule",
    )

    checks = {
        "engine_lifecycle_version": (
            getattr(
                engine,
                "DRAFT_LIFECYCLE_VERSION",
                "",
            )
            == (
                "franchise-draft-lifecycle-"
                "v1.1.8-2026-08-10"
            )
        ),
        "consumed_2029_draft_is_not_active_in_2029_30": (
            engine.draft_state(
                consumed_state
            )
            is None
        ),
        "consumed_2029_draft_is_not_current_year_complete": (
            not engine.draft_is_complete(
                consumed_state
            )
        ),
        "partial_transition_recovery_is_not_hidden": (
            engine.draft_state(
                partial_recovery_state
            )
            is stale_draft
        ),
        "new_2030_draft_remains_active": (
            engine.draft_state(
                active_state
            )
            is active_2030
        ),
        "required_draft_year_advances_to_2030": (
            engine.draft_year_for_state(
                consumed_state
            )
            == 2030
        ),
        "new_draft_overwrite_preserves_history": (
            "_raw_existing_draft_v1_1_8"
            in engine_text
            and "_archive_completed_draft("
            in engine_text
        ),
        "postseason_ui_uses_current_year_draft_gate": (
            "if not draft_is_complete(state):"
            in page_text
        ),
        "v116_rollover_recovery_retained": (
            "_draft_transition_status_v1_1_6"
            in transition_source
            and "target_already_transitioned"
            in transition_source
            and "repair_season_label_then_transition"
            in transition_source
        ),
        "v116_no_double_advance_retained": (
            "recovered_existing_target=True"
            in transition_source
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    print("DRAFT V1.1.8 CHECKS")

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
            "Draft V1.1.8 validation failed: "
            + ", ".join(failed)
        )

    print()
    print(
        "FRANCHISE DRAFT V1.1.8 "
        "VALIDATION PASSED"
    )

    # Optional read-only inspection of the user's durable checkpoint.
    try:
        from simulation_franchise_checkpoint_v1 import (
            load_franchise_checkpoint,
        )

        checkpoint = (
            load_franchise_checkpoint()
        )
    except Exception as exc:
        print()
        print(
            "Checkpoint inspection skipped:",
            exc,
        )
        return 0

    if checkpoint is None:
        print()
        print(
            "Checkpoint inspection: "
            "no durable checkpoint loaded."
        )
        return 0

    state = checkpoint.simulation_state
    raw = getattr(
        state,
        "franchise_draft_state_v1",
        None,
    )
    raw_year = (
        raw.get(
            "draft_year",
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    active = engine.draft_state(
        state
    )

    print()
    print("CURRENT CHECKPOINT INTERPRETATION")
    print("---------------------------------")
    print(
        "Live season:",
        state.settings.season_label,
    )
    print(
        "Required Draft year:",
        engine.draft_year_for_state(
            state
        ),
    )
    print(
        "Raw stored Draft year:",
        raw_year,
    )
    print(
        "Active Draft year:",
        (
            active.get(
                "draft_year",
                None,
            )
            if isinstance(
                active,
                dict,
            )
            else None
        ),
    )
    print(
        "Next Draft action:",
        (
            "ENTER NEW DRAFT LOTTERY"
            if active is None
            else (
                "CONTINUE ACTIVE DRAFT"
            )
        ),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
