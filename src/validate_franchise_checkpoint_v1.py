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

CHECKPOINT_PATH = (
    SRC
    / "simulation_franchise_checkpoint_v1.py"
)
POSTSEASON_PATH = (
    SRC
    / "simulation_postseason_v1.py"
)
FRANCHISE_PAGE = (
    PAGES
    / "5_Franchise_Mode.py"
)
REPORT_PATH = (
    OUTPUTS
    / "franchise_checkpoint_validation_v1.json"
)

VALIDATOR_VERSION = (
    "franchise-checkpoint-validator-v1.2.3-2026-08-09"
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
    paths = {
        "checkpoint_module": CHECKPOINT_PATH,
        "postseason_backend": POSTSEASON_PATH,
        "franchise_page": FRANCHISE_PAGE,
    }
    checks: dict[str, bool] = {
        f"{name}_exists": path.exists()
        for name, path
        in paths.items()
    }
    details: dict[str, Any] = {}

    texts = {
        name: (
            path.read_text(
                encoding="utf-8"
            )
            if path.exists()
            else ""
        )
        for name, path
        in paths.items()
    }
    checkpoint_text = texts[
        "checkpoint_module"
    ]
    backend_text = texts[
        "postseason_backend"
    ]
    page_text = texts[
        "franchise_page"
    ]
    normalized_page_text = " ".join(
        page_text.split()
    )

    checkpoint_markers = {
        "atomic_temporary_write": (
            "tempfile.mkstemp("
        ),
        "atomic_replace": (
            "os.replace("
        ),
        "fast_gzip": (
            "compresslevel=1"
        ),
        "integrity_digest": (
            "hashlib.sha256("
        ),
        "primary_save": (
            "def save_franchise_checkpoint("
        ),
        "primary_load": (
            "def load_franchise_checkpoint("
        ),
        "backup_recovery": (
            "allow_backup"
        ),
        "clear_action": (
            "def clear_franchise_checkpoint("
        ),
        "self_test": (
            "def run_self_test("
        ),
        "implementation_version": (
            "CHECKPOINT_IMPLEMENTATION_VERSION"
        ),
        "stale_class_rebinding": (
            "def rebind_runtime_graph("
        ),
        "string_enum_rebinding": (
            "String-backed enums must be rebound"
        ),
        "windows_io_retries": (
            "IO_RETRY_DELAYS"
        ),
        "write_verification": (
            "verify-written-revision"
        ),
        "detailed_error_stage": (
            "self.stage = str(stage)"
        ),
        "cloudpickle_payload": (
            "cloudpickle.dumps("
        ),
        "legacy_pickle_compatibility": (
            "Backward compatibility with every checkpoint"
        ),
        "structural_payload_normalization": (
            "def checkpoint_from_payload("
        ),
        "stale_tab_regression_guard": (
            "A stale tab"
        ),
        "progress_comparison": (
            "def checkpoint_progress_key("
        ),
    }
    missing_checkpoint = [
        name
        for name, marker
        in checkpoint_markers.items()
        if marker not in checkpoint_text
    ]
    checks[
        "checkpoint_contract_is_complete"
    ] = not missing_checkpoint
    details[
        "missing_checkpoint_markers"
    ] = missing_checkpoint

    backend_markers = {
        "progress_callback": (
            "progress_callback:"
        ),
        "bounded_advance": (
            "max_games: int = 140"
        ),
        "limit_result": (
            "stopped_at_game_limit"
        ),
        "stall_detection": (
            "The postseason bracket stalled"
        ),
        "one_game_progress_guard": (
            "Postseason advancement did not "
        ),
        "callback_after_commit": (
            "progress_callback("
        ),
    }
    missing_backend = [
        name
        for name, marker
        in backend_markers.items()
        if marker not in backend_text
    ]
    checks[
        "postseason_advance_is_bounded_and_checkpointable"
    ] = not missing_backend
    details[
        "missing_backend_markers"
    ] = missing_backend

    page_markers = {
        "checkpoint_import_reload_bridge": (
            "import simulation_franchise_checkpoint_v1 as _franchise_checkpoint"
        ),
        "checkpoint_import_reload_call": (
            "importlib.reload("
        ),
        "restore_function": (
            "def restore_franchise_checkpoint("
        ),
        "restore_before_trade_state": (
            "checkpoint_restored ="
        ),
        "live_session_migration": (
            "live-session-checkpoint-migration"
        ),
        "state_commit_default_reason": (
            'checkpoint_reason: str = "franchise-state-commit"'
        ),
        "state_commit_forwards_reason": (
            "reason=checkpoint_reason"
        ),
        "fresh_state_saves": (
            'reason="fresh-franchise-state"'
        ),
        "progress_wrapper": (
            "def advance_postseason_with_progress("
        ),
        "progress_status": (
            "with st.status("
        ),
        "round_boundary_checkpoint": (
            "postseason-round-boundary-"
        ),
        "bounded_next_game": (
            ".NEXT_CONTROLLED_GAME: 12"
        ),
        "bounded_stage": (
            ".CURRENT_STAGE: 20"
        ),
        "final_checkpoint": (
            'reason="postseason-advance-complete"'
        ),
        "restore_notice": (
            "Restored the durable Franchise Mode"
        ),
        "checkpoint_timestamp": (
            "Autosave checkpoint ·"
        ),
        "footer_provenance": (
            "CHECKPOINT_VERSION"
        ),
        "implementation_provenance": (
            "CHECKPOINT_IMPLEMENTATION_VERSION"
        ),
        "automatic_write_retry": (
            "automatic-checkpoint-write-recovery"
        ),
        "writer_upgrade_live_state_recovery": (
            "checkpoint-writer-upgrade-recovery"
        ),
        "manual_write_retry": (
            "Retry durable checkpoint now"
        ),
        "checkpoint_error_details": (
            "Checkpoint error details"
        ),
        "save_helper_returns_success": (
            ") -> bool:"
        ),
    }
    missing_page = [
        name
        for name, marker
        in page_markers.items()
        if marker not in page_text
    ]
    checks[
        "franchise_page_uses_durable_checkpoint_flow"
    ] = not missing_page
    details[
        "missing_page_markers"
    ] = missing_page

    for name, path in paths.items():
        compiled, error = (
            compile_path(path)
            if path.exists()
            else (
                False,
                f"{path} is missing",
            )
        )
        checks[
            f"{name}_compiles"
        ] = compiled
        details[
            f"{name}_compile_error"
        ] = error

    checks[
        "checkpoint_restore_does_not_override_live_session"
    ] = (
        '"franchise_simulation_league_state" in st.session_state'
        in normalized_page_text
        and "# FRANCHISE_SIMULATION_SESSION_ISOLATION_V1"
        in page_text
    )
    checks[
        "checkpoint_restores_trade_and_simulation_state"
    ] = (
        'st.session_state[ "franchise_simulation_league_state" ] = simulation_state'
        in normalized_page_text
        and 'st.session_state[ "franchise_trade_league_state" ] = trade_state'
        in normalized_page_text
    )
    checks[
        "long_postseason_calls_use_progress_wrapper"
    ] = (
        page_text.count(
            "advance_postseason_with_progress("
        )
        >= 4
        and page_text.count(
            "advance_postseason("
        )
        == 1
    )
    checks[
        "state_version_remains_backward_compatible"
    ] = (
        '"simulation-postseason-v1-2026-08-08"'
        in backend_text
    )
    checks[
        "checkpoint_state_contract_remains_backward_compatible"
    ] = (
        '"simulation-franchise-checkpoint-v1-2026-08-08"'
        in checkpoint_text
    )
    checks[
        "checkpoint_self_test_covers_hot_reload_failure"
    ] = (
        "stale_hot_reload_class_is_rebound"
        in checkpoint_text
        and "create_stale_reload_fixture("
        in checkpoint_text
    )
    checks[
        "checkpoint_self_test_blocks_stale_tab_regression"
    ] = (
        "stale_tab_cannot_overwrite_advanced_state"
        in checkpoint_text
        and "regression_loaded.reason"
        in checkpoint_text
    )
    checks[
        "page_can_retry_live_state_without_reset"
    ] = (
        "save_current_franchise_checkpoint("
        in page_text
        and 'copy_payload=False'
        in page_text
        and "st.rerun()"
        in page_text
    )

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
            "Franchise checkpoint validation failed: "
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
        "\nFRANCHISE CHECKPOINT "
        "VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
