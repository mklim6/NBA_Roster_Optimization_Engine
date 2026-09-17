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
TRADE_WAR_ROOM_PATH = (
    SRC / "franchise_trade_war_room_v1.py"
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
        TRADE_WAR_ROOM_PATH,
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
    trade_war_room_text = (
        TRADE_WAR_ROOM_PATH.read_text(encoding="utf-8")
        if TRADE_WAR_ROOM_PATH.exists()
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
        "pages_follow_declared_state_authority"
    ] = (
        "FRANCHISE_TRADE_AUTHORITY_V1"
        in franchise_text
        and "Standalone sandbox: this Game Simulator uses its own independent"
        in simulator_text
        and "source_league_state_revision"
        in simulator_text
    )
    checks[
        "both_pages_validate_simulation_state_contract"
    ] = (
        "simulation_state_is_compatible("
        in franchise_text
        and "state.state_version"
        in simulator_text
        and "SIMULATION_STATE_VERSION"
        in simulator_text
    )
    checks[
        "franchise_checkpoint_state_is_preserved_on_rerun"
    ] = (
        "checkpoint-owned"
        in franchise_text
        and "return state, False"
        in franchise_text
    )
    checks[
        "standalone_simulator_preserves_state_when_revision_changes"
    ] = (
        "were preserved rather than reset."
        in simulator_text
        and "return state, False"
        in simulator_text
    )
    checks[
        "franchise_ignores_standalone_trade_revision"
    ] = (
        "No cross-page roster sync is"
        in franchise_text
        and 'trade_sync_required = False'
        in franchise_text
    )
    checks[
        "franchise_uses_transactional_live_trade_center"
    ] = (
        "render_franchise_trade_war_room_v1("
        in franchise_text
        and "render_live_asset_ledger("
        in trade_war_room_text
        and "Build and commit live franchise trades"
        in franchise_text
        and "FRANCHISE_TRADE_AUTHORITY_V1"
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
