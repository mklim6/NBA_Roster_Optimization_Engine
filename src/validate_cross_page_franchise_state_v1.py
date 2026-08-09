from __future__ import annotations

import argparse
import json
import py_compile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

FRANCHISE_PAGE = (
    PAGES / "5_Franchise_Mode.py"
)
SIMULATOR_PAGE = (
    PAGES / "4_Game_Simulator.py"
)
HELPER_PATH = (
    SRC / "simulation_cross_page_state_v1.py"
)
REPORT_PATH = (
    OUTPUTS
    / "cross_page_franchise_state_validation_v1.json"
)

VALIDATOR_VERSION = (
    "cross-page-franchise-state-validator-v1.1-2026-08-08"
)


def compile_path(
    path: Path,
) -> tuple[bool, str]:
    try:
        py_compile.compile(
            str(path),
            doraise=True,
        )
    except py_compile.PyCompileError as exc:
        return False, str(exc)

    return True, ""


def run_validation() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    paths = (
        FRANCHISE_PAGE,
        SIMULATOR_PAGE,
        HELPER_PATH,
    )
    checks["required_cross_page_files_exist"] = (
        all(path.exists() for path in paths)
    )

    franchise_text = (
        FRANCHISE_PAGE.read_text(
            encoding="utf-8"
        )
        if FRANCHISE_PAGE.exists()
        else ""
    )
    simulator_text = (
        SIMULATOR_PAGE.read_text(
            encoding="utf-8"
        )
        if SIMULATOR_PAGE.exists()
        else ""
    )
    helper_text = (
        HELPER_PATH.read_text(
            encoding="utf-8"
        )
        if HELPER_PATH.exists()
        else ""
    )

    checks[
        "object_identity_guard_removed_from_franchise"
    ] = (
        "id(trade_state)"
        not in franchise_text
        and (
            "game_simulator_source_trade_object_id"
            not in franchise_text
        )
    )
    checks[
        "object_identity_guard_removed_from_simulator"
    ] = (
        "id(trade_state)"
        not in simulator_text
        and (
            "game_simulator_source_trade_object_id"
            not in simulator_text
        )
    )
    checks[
        "both_pages_use_stable_source_matching"
    ] = (
        "simulation_matches_trade_state("
        in franchise_text
        and "simulation_matches_trade_state("
        in simulator_text
    )
    checks[
        "both_pages_use_structural_simulation_state_contract"
    ] = (
        "simulation_state_is_compatible("
        in franchise_text
        and "simulation_state_is_compatible("
        in simulator_text
        and "isinstance(\n            state,\n            SimulationLeagueState"
        not in franchise_text
    )
    checks[
        "trade_revision_change_preserves_franchise_state"
    ] = (
        "statistics, injuries, and history remain intact."
        in franchise_text
        and (
            "return state, False"
            in franchise_text
        )
    )
    checks[
        "trade_revision_change_preserves_simulator_state"
    ] = (
        "were preserved rather than reset."
        in simulator_text
        and (
            "return state, rebuilt"
            in simulator_text
        )
    )
    checks[
        "franchise_simulation_blocks_unsynced_trade_revision"
    ] = (
        "trade_sync_required"
        in franchise_text
        and (
            "or trade_sync_required"
            in franchise_text
        )
    )
    checks[
        "franchise_exposes_transactional_trade_sync"
    ] = (
        "Apply trade to active season"
        in franchise_text
        and "synchronize_simulation_with_trade_state("
        in franchise_text
        and "preserving "
        in franchise_text
    )
    checks[
        "simulator_blocks_unsynced_trade_revision"
    ] = (
        "trade_sync_required"
        in simulator_text
        and "st.stop()" in simulator_text
    )

    persistent_markers = (
        "franchise_pref_controlled_teams",
        "franchise_pref_active_team",
        "franchise_pref_simulation_policy",
        "franchise_pref_calendar_month",
        "franchise_pref_draft_class_strength",
    )
    missing_preferences = [
        marker
        for marker in persistent_markers
        if marker not in franchise_text
    ]
    checks[
        "franchise_preferences_use_shadow_keys"
    ] = not missing_preferences
    details[
        "missing_preference_markers"
    ] = missing_preferences

    checks[
        "simulator_shares_franchise_preferences"
    ] = all(
        marker in simulator_text
        for marker in (
            "franchise_pref_controlled_teams",
            "franchise_pref_active_team",
            "franchise_pref_calendar_month",
        )
    )
    checks[
        "widget_callbacks_persist_shadow_values"
    ] = (
        "persist_franchise_widget"
        in franchise_text
        and "persist_simulator_widget"
        in simulator_text
        and "persist_widget_value("
        in helper_text
    )
    checks[
        "helper_explicitly_handles_streamlit_widget_cleanup"
    ] = (
        "Streamlit removes a widget key"
        in helper_text
        and "initialize_persistent_widget("
        in helper_text
    )
    checks[
        "helper_uses_revision_not_object_identity"
    ] = (
        "source_league_state_revision"
        in helper_text
        and "source_transaction_count"
        in helper_text
        and "id(" not in helper_text
    )

    compile_results = {
        str(path): compile_path(path)
        for path in paths
        if path.exists()
    }
    checks["all_cross_page_files_compile"] = (
        len(compile_results)
        == len(paths)
        and all(
            passed
            for passed, _
            in compile_results.values()
        )
    )
    details["compile_results"] = {
        path: {
            "passed": passed,
            "error": error,
        }
        for path, (
            passed,
            error,
        ) in compile_results.items()
    }

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": details,
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Cross-page franchise-state "
            "validation failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    report = run_validation()
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nCROSS-PAGE FRANCHISE STATE "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
