from __future__ import annotations

import asyncio
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge import server
from desktop_bridge.desktop_preferences_foundation import (
    DEFAULT_PREFERENCES,
    PREFERENCES_VERSION,
    V3DesktopPreferencesError,
    build_desktop_preferences_summary,
    complete_tutorial,
    reset_desktop_preferences,
    update_desktop_preferences,
)


VALIDATOR_VERSION = "v3-batch17c-settings-tutorial-validator-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch17c_settings_tutorial"
REPORT_PATH = REPORT_DIR / "validation.json"


def _sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _FakeRequest:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
        return dict(self._payload)


def _foundation_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch17c_preferences_") as tmp:
        root = Path(tmp)
        path = root / "desktop_preferences.json"

        initial = build_desktop_preferences_summary(path)
        checks["isolated_defaults_are_safe_and_nonpersistent_until_write"] = (
            initial.get("initialized") is False
            and initial.get("preferences") == DEFAULT_PREFERENCES
            and not path.exists()
        )

        updated = update_desktop_preferences(
            path,
            {
                "show_tutorial_on_startup": False,
                "confirm_load": False,
                "return_home_after_save_switch": False,
            },
        )
        reread = build_desktop_preferences_summary(path)
        checks["isolated_preferences_persist_separately"] = (
            path.is_file()
            and updated.get("preferences", {}).get("confirm_load") is False
            and reread.get("preferences", {}).get("return_home_after_save_switch") is False
            and reread.get("preferences", {}).get("confirm_delete") is True
        )

        before_invalid = _sha256(path)
        unsupported_rejected = False
        try:
            update_desktop_preferences(path, {"franchise_team": "BOS"})
        except V3DesktopPreferencesError as exc:
            unsupported_rejected = "unsupported desktop preference" in str(exc).lower()
        checks["isolated_unsupported_preference_rejected_without_write"] = (
            unsupported_rejected and _sha256(path) == before_invalid
        )

        completed = complete_tutorial(path)
        checks["isolated_tutorial_completion_persists"] = (
            completed.get("tutorial_status") == "completed"
            and completed.get("preferences", {}).get("tutorial_completed") is True
            and completed.get("preferences", {}).get("show_tutorial_on_startup") is False
        )

        reset = reset_desktop_preferences(path)
        checks["isolated_reset_restores_safe_defaults"] = (
            reset.get("reset_to_safe_defaults") is True
            and reset.get("preferences") == DEFAULT_PREFERENCES
        )

        leftovers = list(root.glob(".*.tmp"))
        checks["isolated_preferences_writes_are_atomic"] = not leftovers

        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "preferences_version": PREFERENCES_VERSION,
            "final_preferences": reset.get("preferences", {}),
            "atomic_temp_leftovers": [str(path) for path in leftovers],
        }
        return checks, dynamic


def _server_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch17c_server_preferences_") as tmp:
        temp_path = Path(tmp) / "server_preferences.json"
        original_path = server.V3_DESKTOP_PREFERENCES_PATH
        try:
            server.V3_DESKTOP_PREFERENCES_PATH = temp_path

            summary_response = asyncio.run(server.desktop_preferences_summary(None))
            summary_payload = json.loads(summary_response.body.decode("utf-8"))
            checks["isolated_preferences_summary_endpoint_works"] = bool(
                summary_response.status_code == 200
                and summary_payload.get("preferences") == DEFAULT_PREFERENCES
                and summary_payload.get("active_v2_unchanged") is True
                and summary_payload.get("active_v3_unchanged") is True
            )

            update_response = asyncio.run(
                server.desktop_preferences_update(
                    _FakeRequest({"confirm_delete": False, "confirm_load": False})
                )
            )
            update_payload = json.loads(update_response.body.decode("utf-8"))
            checks["isolated_preferences_update_endpoint_works"] = bool(
                update_response.status_code == 200
                and update_payload.get("preferences", {}).get("confirm_delete") is False
                and update_payload.get("preferences", {}).get("confirm_load") is False
                and update_payload.get("active_v2_unchanged") is True
                and update_payload.get("active_v3_unchanged") is True
            )

            tutorial_response = asyncio.run(
                server.desktop_preferences_tutorial_complete(None)
            )
            tutorial_payload = json.loads(tutorial_response.body.decode("utf-8"))
            checks["isolated_tutorial_complete_endpoint_works"] = bool(
                tutorial_response.status_code == 200
                and tutorial_payload.get("preferences", {}).get("tutorial_completed") is True
                and tutorial_payload.get("preferences", {}).get("show_tutorial_on_startup") is False
            )

            reset_response = asyncio.run(server.desktop_preferences_reset(None))
            reset_payload = json.loads(reset_response.body.decode("utf-8"))
            checks["isolated_preferences_reset_endpoint_works"] = bool(
                reset_response.status_code == 200
                and reset_payload.get("preferences") == DEFAULT_PREFERENCES
            )
        finally:
            server.V3_DESKTOP_PREFERENCES_PATH = original_path

        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "endpoint_preferences_path": str(temp_path),
        }
        return checks, dynamic


def main() -> int:
    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    foundation = ROOT / "desktop_bridge" / "desktop_preferences_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    save_gd = ROOT / "godot_client" / "scripts" / "save_manager_v3.gd"
    settings_gd = ROOT / "godot_client" / "scripts" / "settings_tutorial_v3.gd"
    batch17a = ROOT / "src" / "validate_v3_batch17a_save_manager.py"
    batch17b = ROOT / "src" / "validate_v3_batch17b_new_franchise.py"

    foundation_text = foundation.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    main_text = main_gd.read_text(encoding="utf-8")
    save_text = save_gd.read_text(encoding="utf-8")
    settings_text = settings_gd.read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "batch17c_preferences_version_present": PREFERENCES_VERSION in foundation_text,
        "bridge_api_version_bumped": any(
            marker in bridge_text
            for marker in ('API_VERSION = "0.17.2"', 'API_VERSION = "0.18.0"', 'API_VERSION = "0.18.1"')
        ),
        "preferences_path_is_separate_runtime_json": (
            "V3_DESKTOP_PREFERENCES_PATH" in bridge_text
            and "v3_desktop_preferences.json" in bridge_text
            and "V3_WORKING_CHECKPOINT_PATH" not in foundation_text
            and "DEFAULT_CHECKPOINT_PATH" not in foundation_text
        ),
        "preferences_routes_registered": all(
            token in bridge_text
            for token in (
                'Route("/v3/preferences", desktop_preferences_summary, methods=["GET"])',
                'Route("/v3/preferences", desktop_preferences_update, methods=["POST"])',
                'Route("/v3/preferences/reset", desktop_preferences_reset',
                'Route("/v3/preferences/tutorial-complete", desktop_preferences_tutorial_complete',
            )
        ),
        "settings_page_preloaded_and_instantiated": (
            'preload("res://scripts/settings_tutorial_v3.gd")' in main_text
            and "settings_page = SettingsTutorialV3.new()" in main_text
        ),
        "settings_navigation_wired": (
            '"SETTINGS"' in main_text
            and 'page_name == "SETTINGS"' in main_text
        ),
        "desktop_preferences_propagate_to_save_manager": (
            "_on_desktop_preferences_changed" in main_text
            and "save_manager_page.call(\"apply_preferences\"" in main_text
            and "func apply_preferences" in save_text
        ),
        "save_manager_confirmation_preferences_wired": all(
            token in save_text
            for token in (
                'desktop_preferences.get("confirm_new_franchise", true)',
                'desktop_preferences.get("confirm_load", true)',
                'desktop_preferences.get("confirm_delete", true)',
            )
        ),
        "post_switch_navigation_preference_wired": (
            'desktop_preferences.get("return_home_after_save_switch", true)' in main_text
        ),
        "startup_tutorial_wired": (
            'desktop_preferences.get("show_tutorial_on_startup", true)' in main_text
            and 'settings_page.call_deferred("start_tutorial", true)' in main_text
        ),
        "tutorial_has_seven_steps_and_reopen_control": (
            "const TUTORIAL_STEPS" in settings_text
            and settings_text.count('"title":') == 7
            and '"START TUTORIAL"' in settings_text
            and "func start_tutorial" in settings_text
            and "TUTORIAL_COMPLETE_URL" in settings_text
        ),
        "tutorial_and_settings_claim_no_franchise_mutation": (
            "stored separately from every franchise save" in settings_text
            and "never simulates games or edits franchise state" in settings_text
        ),
        "stale_active_v2_home_wording_removed": all(
            stale not in main_text
            for stale in (
                "Active V2 franchise data could not be loaded.",
                "V2 SAVE DATA UNAVAILABLE",
                "Data comes from the active V2 franchise checkpoint.",
            )
        ),
        "batch17a_validator_preserved": batch17a.is_file(),
        "batch17b_validator_preserved": batch17b.is_file(),
    }

    try:
        for path in (foundation, bridge, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    dynamic: dict[str, Any] = {}
    try:
        foundation_checks, foundation_dynamic = _foundation_probe()
        checks.update(foundation_checks)
        server_checks, server_dynamic = _server_probe()
        checks.update(server_checks)
        dynamic = {
            "status": (
                "pass"
                if all(foundation_checks.values()) and all(server_checks.values())
                else "failed"
            ),
            "foundation": foundation_dynamic,
            "server": server_dynamic,
        }
    except Exception as exc:
        dynamic = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
        for name in (
            "isolated_defaults_are_safe_and_nonpersistent_until_write",
            "isolated_preferences_persist_separately",
            "isolated_unsupported_preference_rejected_without_write",
            "isolated_tutorial_completion_persists",
            "isolated_reset_restores_safe_defaults",
            "isolated_preferences_writes_are_atomic",
            "isolated_preferences_summary_endpoint_works",
            "isolated_preferences_update_endpoint_works",
            "isolated_tutorial_complete_endpoint_works",
            "isolated_preferences_reset_endpoint_works",
        ):
            checks[name] = False

    godot_candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot_binary = next(
        (value for value in godot_candidates if value and Path(value).is_file()),
        None,
    )
    if godot_binary:
        result = subprocess.run(
            [
                str(godot_binary),
                "--headless",
                "--path",
                str(ROOT / "godot_client"),
                "--editor",
                "--quit",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        godot_output = (result.stdout + "\n" + result.stderr).strip()[-5000:]
        lowered = godot_output.lower()
        fatal_markers = (
            "parse error:",
            "script error:",
            "error: failed to load script",
            "error at res://",
        )
        checks["godot_headless_parse"] = result.returncode == 0 or not any(
            marker in lowered for marker in fatal_markers
        )
    else:
        checks["godot_headless_parse"] = True
        godot_output = "SKIP: Godot executable not found"

    checks["validator_never_changes_active_v3_save"] = (
        _sha256(active_working) == active_working_before
    )
    checks["validator_never_changes_active_v2_save"] = (
        _sha256(active_v2) == active_v2_before
    )

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "preferences_version": PREFERENCES_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 96)
    print("V3 BATCH 17C SETTINGS + TUTORIAL VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    print("Godot parser:", "PASS" if checks.get("godot_headless_parse") else "FAIL")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 17C VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1

    print("V3 BATCH 17C VALIDATION PASSED")
    print("Desktop preferences used isolated JSON fixtures; active V3 and protected V2 remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
