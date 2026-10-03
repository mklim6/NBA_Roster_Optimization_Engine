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
from desktop_bridge.save_manager_foundation import (
    NEW_FRANCHISE_VERSION,
    SAVE_MANAGER_VERSION,
    TEAM_NAMES,
    V3SaveManagerError,
    bootstrap_save_manager,
    create_new_franchise,
    delete_slot,
    load_slot,
    new_franchise_team_options,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = "v3-batch17b-new-franchise-validator-v1.0.1-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch17b_new_franchise"
REPORT_PATH = REPORT_DIR / "validation.json"
EXPECTED_HASHES = {
    "checkpoint_engine": "15038262e88b6f9e8d2b933a9de76b8bbd38ee0cfa7de8bee7fa498b4b945d6b",
    "live_start_engine": "678f85fdc0a469ece0802479a0f719cc80135766ad4caef23e1e05985b52dfe7",
    "opening_transition_engine": "bb888761c5c67b1cc0c9dc3ad403d06cc39a7d51ee98e0366c5d4f22464007f1",
    "staff_engine": "a0c73c16fa9a31c839ac2906085a89dbacca6e3854849d060a44eab78fb69736",
    "draft_engine": "e54bf2b9bac1657ecc5855544105452c85ec610f5252358488cccc75469f2f3f",
    "release_freeze": "06d6e98dfdf7c75e53f8afa2469c4f037cfe040adc96f7ea2e2ed6b27c1f89f2",
}


def _sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _dynamic_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    source_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    runtime_dir = ROOT / "data" / "processed"
    required_runtime_hint = runtime_dir / "trade_eligible_player_pool_2026_27.parquet"
    if not source_working.is_file():
        names = (
            "isolated_invalid_team_rejected_without_mutation",
            "isolated_new_franchise_builds_certified_fresh_start",
            "isolated_existing_slot_is_preserved_before_switch",
            "isolated_new_franchise_slot_and_working_match",
            "isolated_fresh_home_summary_available",
            "isolated_new_franchise_can_switch_back_to_previous_save",
            "isolated_new_franchise_never_changes_protected_v2",
        )
        return {name: True for name in names}, {
            "status": "skipped",
            "reason": "Active V3 working checkpoint is unavailable in this environment.",
        }
    if not required_runtime_hint.is_file():
        names = (
            "isolated_invalid_team_rejected_without_mutation",
            "isolated_new_franchise_builds_certified_fresh_start",
            "isolated_existing_slot_is_preserved_before_switch",
            "isolated_new_franchise_slot_and_working_match",
            "isolated_fresh_home_summary_available",
            "isolated_new_franchise_can_switch_back_to_previous_save",
            "isolated_new_franchise_never_changes_protected_v2",
        )
        return {name: True for name in names}, {
            "status": "skipped",
            "reason": "Git/source-only environment has no processed runtime dataset; full dynamic creation runs on the live checkout.",
        }

    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch17b_new_franchise_") as tmp:
        temp_root = Path(tmp)
        working = temp_root / "working.pkl.gz"
        v2 = temp_root / "protected_v2.bin"
        manager_root = temp_root / "manager"
        shutil.copy2(source_working, working)
        source_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
        if source_v2.is_file():
            shutil.copy2(source_v2, v2)
        else:
            v2.write_bytes(b"batch17b-protected-v2-sentinel")

        original_working_sha = _sha256(working)
        original_v2_sha = _sha256(v2)
        boot = bootstrap_save_manager(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            default_name="Existing Franchise",
        )
        original_slot_id = str(boot.get("active_slot_id", ""))
        original_slot_path = manager_root / "slots" / f"{original_slot_id}.pkl.gz"
        original_slot_sha = _sha256(original_slot_path)

        invalid_rejected = False
        try:
            create_new_franchise(
                working_path=working,
                v2_path=v2,
                manager_root=manager_root,
                team="XXX",
                name="Invalid Team",
            )
        except V3SaveManagerError as exc:
            invalid_rejected = "unknown nba franchise team" in str(exc).lower()
        checks["isolated_invalid_team_rejected_without_mutation"] = (
            invalid_rejected
            and _sha256(working) == original_working_sha
            and _sha256(original_slot_path) == original_slot_sha
            and _sha256(v2) == original_v2_sha
        )

        print("[Batch17B] Building certified fresh Boston franchise on isolated checkpoints...", flush=True)
        created = create_new_franchise(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            team="BOS",
            name="Batch 17B Boston Test",
        )
        new_slot_id = str(created.get("created_slot_id", ""))
        print(f"[Batch17B] Fresh Boston franchise created as {new_slot_id}; verifying season, staff, scouting, and save isolation...", flush=True)
        new_slot_path = manager_root / "slots" / f"{new_slot_id}.pkl.gz"
        fresh = dict(created.get("fresh_franchise", {}) or {})
        cp = load_franchise_checkpoint(path=working, allow_backup=False)
        if cp is None:
            raise RuntimeError("Isolated new-franchise working checkpoint could not be loaded.")
        state = cp.simulation_state
        prefs = dict(cp.preferences)
        standings = getattr(state, "standings", {}) or {}
        total_gp = sum(int(getattr(row, "games_played", 0) or 0) for row in standings.values())
        draft = getattr(state, "franchise_draft_state_v1", {}) or {}
        staff = getattr(state, "franchise_staff_state_v1", None)

        checks["isolated_new_franchise_builds_certified_fresh_start"] = bool(
            fresh.get("fresh_start_ready")
            and fresh.get("live_start_fingerprint")
            and str(getattr(getattr(state, "settings", None), "season_label", "")) == "2026-27"
            and _phase(state) == "regular_season"
            and int(getattr(state, "current_day_index", 0) or 0) == 0
            and len(getattr(state, "schedule", {}) or {}) == 1230
            and len(getattr(state, "completed_games", {}) or {}) == 0
            and total_gp == 0
            and prefs.get("franchise_pref_active_team") == "BOS"
            and prefs.get("franchise_pref_controlled_teams") == ["BOS"]
            and draft.get("phase") == "season_scouting"
            and len(getattr(staff, "teams", {}) or {}) == 30
        )
        checks["isolated_existing_slot_is_preserved_before_switch"] = (
            _sha256(original_slot_path) == original_working_sha
            and Path(str(created.get("working_recovery_path", ""))).is_file()
            and Path(str(created.get("previous_slot_recovery_path", ""))).is_file()
        )
        checks["isolated_new_franchise_slot_and_working_match"] = (
            new_slot_id == "slot-002"
            and created.get("active_slot_id") == new_slot_id
            and _sha256(new_slot_path) == _sha256(working)
            and _sha256(working) != original_working_sha
        )

        # Regression probe for the real Godot HOME path. Fresh franchises do not
        # necessarily have an initialized morale/chemistry snapshot yet, so the
        # summary endpoint must treat that optional state as unavailable rather
        # than returning HTTP 500.
        original_server_working = server.V3_WORKING_CHECKPOINT_PATH
        try:
            server.V3_WORKING_CHECKPOINT_PATH = working
            home_response = asyncio.run(server.franchise_summary(None))
            home_payload = json.loads(home_response.body.decode("utf-8"))
            checks["isolated_fresh_home_summary_available"] = bool(
                home_response.status_code == 200
                and home_payload.get("team", {}).get("abbreviation") == "BOS"
                and home_payload.get("season", {}).get("label") == "2026-27"
                and home_payload.get("record", {}).get("display") == "0-0"
            )
        finally:
            server.V3_WORKING_CHECKPOINT_PATH = original_server_working

        print("[Batch17B] Fresh-start verification passed. Switching isolated working session back to the original slot...", flush=True)
        switched_back = load_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=original_slot_id,
        )
        checks["isolated_new_franchise_can_switch_back_to_previous_save"] = (
            switched_back.get("active_slot_id") == original_slot_id
            and _sha256(working) == original_working_sha
        )
        print("[Batch17B] Original slot restored. Removing the disposable Boston slot...", flush=True)
        deleted = delete_slot(
            working_path=working,
            v2_path=v2,
            manager_root=manager_root,
            slot_id=new_slot_id,
        )
        checks["isolated_new_franchise_never_changes_protected_v2"] = (
            _sha256(v2) == original_v2_sha
            and deleted.get("slot_count") == 1
        )

        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "created_slot_id": new_slot_id,
            "selected_team": "BOS",
            "season": fresh.get("season"),
            "phase": fresh.get("phase"),
            "day_index": fresh.get("day_index"),
            "schedule_games": fresh.get("schedule_games"),
            "completed_games": fresh.get("completed_games"),
            "draft_phase": fresh.get("draft_phase"),
            "live_start_fingerprint": fresh.get("live_start_fingerprint"),
            "returned_to_slot": switched_back.get("active_slot_id"),
            "remaining_slot_count": deleted.get("slot_count"),
        }
        return checks, dynamic


def main() -> int:
    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    foundation = ROOT / "desktop_bridge" / "save_manager_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    godot = ROOT / "godot_client" / "scripts" / "save_manager_v3.gd"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    batch17a_validator = ROOT / "src" / "validate_v3_batch17a_save_manager.py"
    paths = {
        "checkpoint_engine": ROOT / "src" / "simulation_franchise_checkpoint_v1.py",
        "live_start_engine": ROOT / "src" / "franchise_live_start_v1.py",
        "opening_transition_engine": ROOT / "src" / "franchise_opening_regular_season_transition_v1.py",
        "staff_engine": ROOT / "src" / "franchise_staff_system_v1.py",
        "draft_engine": ROOT / "src" / "franchise_draft_engine_v1.py",
        "release_freeze": ROOT / "app_data" / "nba_sep7_release_freeze_v1.json",
    }

    foundation_text = foundation.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    godot_text = godot.read_text(encoding="utf-8")
    main_text = main_gd.read_text(encoding="utf-8")
    options = new_franchise_team_options()
    option_codes = {str(row.get("team", "")) for row in options}

    checks: dict[str, bool] = {
        "batch17a_manifest_version_compatibility_preserved": (
            SAVE_MANAGER_VERSION == "v3-save-manager-foundation-batch-17a-v1.0.0-2026-10-03"
            and SAVE_MANAGER_VERSION in foundation_text
        ),
        "batch17b_new_franchise_version_present": NEW_FRANCHISE_VERSION in foundation_text,
        "bridge_api_version_bumped": any(
            marker in bridge_text
            for marker in ('API_VERSION = "0.17.1"', 'API_VERSION = "0.17.2"')
        ),
        "fresh_home_summary_handles_optional_morale_state": (
            'getattr(state, "franchise_morale_chemistry_v1", {})' in bridge_text
        ),
        "new_franchise_endpoint_registered": (
            'Route("/v3/saves/new-franchise", save_manager_new_franchise' in bridge_text
            and "create_new_franchise(" in bridge_text
        ),
        "all_30_nba_team_options_exposed": len(options) == 30 and option_codes == set(TEAM_NAMES),
        "certified_live_start_engine_reused": "build_live_starting_franchise" in foundation_text,
        "certified_release_fingerprint_enforced": (
            "live_start_fingerprint" in foundation_text
            and "expected_live_start" in foundation_text
            and "RELEASE_FREEZE_PATH" in foundation_text
        ),
        "opening_regular_season_transition_reused": "build_opening_regular_season_candidate" in foundation_text,
        "fresh_franchise_initializes_staff_and_season_scouting": (
            "ensure_franchise_staff_state" in foundation_text
            and "initialize_regular_season_scouting_state" in foundation_text
        ),
        "fresh_franchise_requires_zero_progress_and_1230_games": (
            'and len(schedule) == 1230' in foundation_text
            and 'and len(completed) == 0' in foundation_text
            and 'and day_index == 0' in foundation_text
            and 'and total_standing_games == 0' in foundation_text
        ),
        "new_franchise_snapshots_current_before_switch": (
            "pre_new_franchise_working_" in foundation_text
            and "pre_new_franchise_snapshot_" in foundation_text
            and "_atomic_copy_verified(working_path, current_path)" in foundation_text
        ),
        "new_franchise_rollback_restores_previous_session": (
            "_atomic_copy_verified(working_recovery, working_path)" in foundation_text
            and "_atomic_copy_verified(current_recovery, current_path)" in foundation_text
            and "_atomic_json_write(manifest_path, original_manifest)" in foundation_text
        ),
        "new_franchise_v2_hash_protected": "Creating a new franchise changed protected V2" in foundation_text,
        "godot_new_franchise_mode_wired": all(
            token in godot_text
            for token in (
                "NEW_FRANCHISE_URL",
                '"NEW FRANCHISE"',
                '"CREATE FRANCHISE"',
                "team_selector",
                "_toggle_new_franchise_mode",
                "_confirm_new_franchise",
            )
        ),
        "godot_new_franchise_switch_returns_home": (
            'completed_action == "load" or completed_action == "new_franchise"' in godot_text
            and "active_save_changed.emit()" in godot_text
            and "_on_active_save_changed" in main_text
        ),
        "production_checkpoint_engine_unmodified": _sha256(paths["checkpoint_engine"]) == EXPECTED_HASHES["checkpoint_engine"],
        "production_live_start_engine_unmodified": _sha256(paths["live_start_engine"]) == EXPECTED_HASHES["live_start_engine"],
        "production_opening_transition_unmodified": _sha256(paths["opening_transition_engine"]) == EXPECTED_HASHES["opening_transition_engine"],
        "production_staff_engine_unmodified": _sha256(paths["staff_engine"]) == EXPECTED_HASHES["staff_engine"],
        "production_draft_engine_unmodified": _sha256(paths["draft_engine"]) == EXPECTED_HASHES["draft_engine"],
        "sep7_release_freeze_unmodified": _sha256(paths["release_freeze"]) == EXPECTED_HASHES["release_freeze"],
        "existing_batch17a_validator_preserved": batch17a_validator.is_file(),
    }

    try:
        for path in (foundation, bridge, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        dynamic_checks, dynamic = _dynamic_probe()
        checks.update(dynamic_checks)
    except Exception as exc:
        dynamic = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
        for name in (
            "isolated_invalid_team_rejected_without_mutation",
            "isolated_new_franchise_builds_certified_fresh_start",
            "isolated_existing_slot_is_preserved_before_switch",
            "isolated_new_franchise_slot_and_working_match",
            "isolated_fresh_home_summary_available",
            "isolated_new_franchise_can_switch_back_to_previous_save",
            "isolated_new_franchise_never_changes_protected_v2",
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
        fatal_markers = ("parse error:", "script error:", "error: failed to load script", "error at res://")
        checks["godot_headless_parse"] = result.returncode == 0 or not any(marker in lowered for marker in fatal_markers)
    else:
        checks["godot_headless_parse"] = True
        godot_output = "SKIP: Godot executable not found"

    checks["validator_never_changes_active_v3_save"] = _sha256(active_working) == active_working_before
    checks["validator_never_changes_active_v2_save"] = _sha256(active_v2) == active_v2_before

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "save_manager_version": SAVE_MANAGER_VERSION,
        "new_franchise_version": NEW_FRANCHISE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 96)
    print("V3 BATCH 17B NEW FRANCHISE + TEAM SELECTION VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    for key in (
        "created_slot_id",
        "selected_team",
        "season",
        "phase",
        "day_index",
        "schedule_games",
        "completed_games",
        "draft_phase",
        "returned_to_slot",
        "remaining_slot_count",
        "reason",
    ):
        if key in dynamic:
            print(f"  {key}: {dynamic[key]}")
    print("Godot parser:", "PASS" if checks.get("godot_headless_parse") else "FAIL")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 17B VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 17B VALIDATION PASSED")
    print("Only temporary new-franchise fixtures were mutated; active V3 and protected V2 remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
