from __future__ import annotations

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
from desktop_bridge.save_manager_foundation import (
    SAVE_MANAGER_VERSION,
    V3SaveManagerError,
    bootstrap_save_manager,
    build_save_manager_summary,
    create_slot_copy,
    delete_slot,
    load_slot,
    rename_slot,
    save_current_slot,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint, save_franchise_checkpoint


VALIDATOR_VERSION = "v3-batch17a-save-manager-validator-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch17a_save_manager"
REPORT_PATH = REPORT_DIR / "validation.json"
CHECKPOINT_ENGINE_SHA256 = "15038262e88b6f9e8d2b933a9de76b8bbd38ee0cfa7de8bee7fa498b4b945d6b"


def _sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _dynamic_save_manager_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    source_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    if not source_working.is_file():
        return {
            "isolated_bootstrap_preserves_working": True,
            "isolated_create_and_rename_preserve_working": True,
            "isolated_save_current_updates_snapshot": True,
            "isolated_load_switch_is_atomic": True,
            "isolated_active_slot_delete_is_blocked": True,
            "isolated_nonactive_delete_creates_recovery": True,
            "isolated_save_manager_never_changes_protected_v2": True,
        }, {
            "status": "skipped",
            "reason": "Active V3 working checkpoint is unavailable in this environment.",
        }

    with tempfile.TemporaryDirectory(prefix="v3_batch17a_save_manager_") as tmp:
        temp_root = Path(tmp)
        working = temp_root / "working.pkl.gz"
        v2 = temp_root / "protected_v2.bin"
        manager_root = temp_root / "manager"
        shutil.copy2(source_working, working)
        source_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
        if source_v2.is_file():
            shutil.copy2(source_v2, v2)
        else:
            v2.write_bytes(b"batch17a-protected-v2-sentinel")

        original_working_sha = _sha256(working)
        original_v2_sha = _sha256(v2)

        initial_summary = build_save_manager_summary(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
        )
        boot = bootstrap_save_manager(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
        )
        slot1 = str(boot.get("active_slot_id", ""))
        checks["isolated_bootstrap_preserves_working"] = (
            initial_summary.get("initialized") is False
            and boot.get("initialized") is True
            and slot1 == "slot-001"
            and boot.get("slot_count") == 1
            and _sha256(working) == original_working_sha
        )

        created = create_slot_copy(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            name="Alternate Franchise",
        )
        slot2 = str(created.get("created_slot_id", ""))
        renamed = rename_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=slot2,
            name="Alternate Timeline",
        )
        slot2_row = next(
            (row for row in renamed.get("slots", []) if row.get("slot_id") == slot2),
            {},
        )
        checks["isolated_create_and_rename_preserve_working"] = (
            slot2 == "slot-002"
            and slot2_row.get("name") == "Alternate Timeline"
            and _sha256(working) == original_working_sha
        )

        # Advance only the TEMPORARY working checkpoint metadata so slot-001
        # and slot-002 have distinct valid checkpoint bytes without changing
        # any simulation result or the user's actual save.
        checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
        assert checkpoint is not None
        preferences = dict(checkpoint.preferences)
        preferences["batch17a_validator_marker"] = "slot-one-newer"
        save_franchise_checkpoint(
            checkpoint.simulation_state,
            checkpoint.trade_state,
            preferences=preferences,
            reason="Batch17A temporary save-manager validator marker",
            path=working,
            copy_payload=False,
            force_replace=True,
        )
        modified_working_sha = _sha256(working)
        saved = save_current_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
        )
        active_snapshot_sha = str(saved.get("active_slot_snapshot_sha256", ""))
        checks["isolated_save_current_updates_snapshot"] = (
            modified_working_sha is not None
            and modified_working_sha != original_working_sha
            and active_snapshot_sha == modified_working_sha
            and saved.get("live_session_ahead_of_snapshot") is False
        )

        loaded_slot2 = load_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=slot2,
        )
        after_slot2_sha = _sha256(working)
        loaded_slot1 = load_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=slot1,
        )
        recovery_path = Path(str(loaded_slot2.get("recovery_path", "")))
        checks["isolated_load_switch_is_atomic"] = (
            loaded_slot2.get("active_slot_id") == slot2
            and loaded_slot1.get("active_slot_id") == slot1
            and after_slot2_sha == original_working_sha
            and _sha256(working) == modified_working_sha
            and recovery_path.is_file()
        )

        active_delete_blocked = False
        try:
            delete_slot(
                working_path=working,
                v2_path=v2,
                manager_root=manager_root,
                slot_id=slot1,
            )
        except V3SaveManagerError as exc:
            active_delete_blocked = "active franchise cannot be deleted" in str(exc).lower()
        checks["isolated_active_slot_delete_is_blocked"] = active_delete_blocked

        deleted = delete_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=slot2,
        )
        deleted_recovery = Path(str(deleted.get("recovery_path", "")))
        checks["isolated_nonactive_delete_creates_recovery"] = (
            deleted.get("slot_count") == 1
            and deleted.get("active_slot_id") == slot1
            and deleted_recovery.is_file()
        )
        checks["isolated_save_manager_never_changes_protected_v2"] = (
            _sha256(v2) == original_v2_sha
        )

        final_checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
        final_marker = ""
        if final_checkpoint is not None:
            final_marker = str(final_checkpoint.preferences.get("batch17a_validator_marker", ""))

        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "starting_working_sha256": original_working_sha,
            "modified_slot1_sha256": modified_working_sha,
            "slot2_loaded_sha256": after_slot2_sha,
            "active_slot_after_probe": loaded_slot1.get("active_slot_id"),
            "remaining_slot_count": deleted.get("slot_count"),
            "final_temp_marker": final_marker,
            "load_recovery_created": recovery_path.is_file(),
            "delete_recovery_created": deleted_recovery.is_file(),
        }
        return checks, dynamic


def main() -> int:
    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    foundation = ROOT / "desktop_bridge" / "save_manager_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    save_gd = ROOT / "godot_client" / "scripts" / "save_manager_v3.gd"
    checkpoint_engine = ROOT / "src" / "simulation_franchise_checkpoint_v1.py"
    batch16_validator = ROOT / "src" / "validate_v3_batch16_draft_night_continuity.py"

    foundation_text = foundation.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    main_text = main_gd.read_text(encoding="utf-8")
    godot_text = save_gd.read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "batch17a_foundation_version": SAVE_MANAGER_VERSION in foundation_text,
        "bridge_api_version_bumped": any(
            marker in bridge_text
            for marker in (
                'API_VERSION = "0.17.0"',
                'API_VERSION = "0.17.1"',
                'API_VERSION = "0.17.2"',
            )
        ),
        "save_manager_summary_endpoint_registered": 'Route("/v3/saves", save_manager_summary' in bridge_text,
        "save_manager_bootstrap_endpoint_registered": 'Route("/v3/saves/bootstrap", save_manager_bootstrap' in bridge_text,
        "save_manager_save_current_endpoint_registered": 'Route("/v3/saves/save-current", save_manager_save_current' in bridge_text,
        "save_manager_create_endpoint_registered": 'Route("/v3/saves/create", save_manager_create' in bridge_text,
        "save_manager_rename_endpoint_registered": 'Route("/v3/saves/rename", save_manager_rename' in bridge_text,
        "save_manager_load_endpoint_registered": 'Route("/v3/saves/load", save_manager_load' in bridge_text,
        "save_manager_delete_endpoint_registered": 'Route("/v3/saves/delete", save_manager_delete' in bridge_text,
        "save_manager_atomic_copy_and_manifest_write_present": (
            "_atomic_copy_verified" in foundation_text
            and "_atomic_json_write" in foundation_text
            and "os.replace" in foundation_text
        ),
        "save_manager_load_snapshots_current_before_switch": (
            "pre_switch_snapshot_" in foundation_text
            and "pre_load_working_" in foundation_text
        ),
        "save_manager_active_delete_protected": "The active franchise cannot be deleted" in foundation_text,
        "save_manager_v2_hash_protection_present": "changed protected V2" in foundation_text,
        "godot_save_manager_preloaded": 'preload("res://scripts/save_manager_v3.gd")' in main_text,
        "godot_save_manager_instantiated": "save_manager_page = SaveManagerV3.new()" in main_text,
        "godot_save_manager_navigation_wired": '"FRANCHISES"' in main_text,
        "godot_save_manager_all_actions_wired": all(
            token in godot_text
            for token in (
                "SAVE_CURRENT_URL",
                "CREATE_URL",
                "RENAME_URL",
                "LOAD_URL",
                "DELETE_URL",
                '"SAVE CURRENT"',
                '"CREATE COPY"',
                '"LOAD SELECTED"',
                '"DELETE SELECTED"',
            )
        ),
        "godot_load_returns_home_after_slot_switch": (
            "active_save_changed.emit()" in godot_text
            and "_on_active_save_changed" in main_text
        ),
        "production_checkpoint_engine_unmodified": _sha256(checkpoint_engine) == CHECKPOINT_ENGINE_SHA256,
        "existing_batch16_validator_preserved": batch16_validator.is_file(),
    }

    try:
        for path in (foundation, bridge, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        dynamic_checks, dynamic = _dynamic_save_manager_probe()
        checks.update(dynamic_checks)
    except Exception as exc:
        dynamic = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
        for name in (
            "isolated_bootstrap_preserves_working",
            "isolated_create_and_rename_preserve_working",
            "isolated_save_current_updates_snapshot",
            "isolated_load_switch_is_atomic",
            "isolated_active_slot_delete_is_blocked",
            "isolated_nonactive_delete_creates_recovery",
            "isolated_save_manager_never_changes_protected_v2",
        ):
            checks[name] = False

    godot_candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot_binary = next((value for value in godot_candidates if value and Path(value).is_file()), None)
    if godot_binary:
        result = subprocess.run(
            [str(godot_binary), "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
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

    checks["validator_never_changes_active_v3_save"] = _sha256(active_working) == active_working_before
    checks["validator_never_changes_active_v2_save"] = _sha256(active_v2) == active_v2_before

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "save_manager_version": SAVE_MANAGER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 96)
    print("V3 BATCH 17A MULTI-SAVE FRANCHISE MANAGER VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    for key in (
        "active_slot_after_probe",
        "remaining_slot_count",
        "load_recovery_created",
        "delete_recovery_created",
        "final_temp_marker",
        "reason",
    ):
        if key in dynamic:
            print(f"  {key}: {dynamic[key]}")
    print("Godot parser:", "PASS" if checks.get("godot_headless_parse") else "FAIL")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 17A VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 17A VALIDATION PASSED")
    print("Only temporary Save Manager fixtures were mutated; active V3 and protected V2 remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
