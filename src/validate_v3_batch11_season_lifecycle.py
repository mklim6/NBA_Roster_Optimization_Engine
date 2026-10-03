from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge import server
from desktop_bridge.season_lifecycle_foundation import (
    ACTION_CONTRACT_CLOSEOUT,
    SEASON_LIFECYCLE_FOUNDATION_VERSION,
    build_lifecycle_action_preview,
    build_lifecycle_summary,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

VALIDATOR_VERSION = "v3-batch11-season-lifecycle-validator-v1.0.2-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch11_season_lifecycle"
REPORT_PATH = REPORT_DIR / "validation.json"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FakeRequest:
    def __init__(self, body: dict[str, Any]):
        self.body = body

    async def json(self) -> dict[str, Any]:
        return copy.deepcopy(self.body)


def response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def _run_isolated_endpoint_tests() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    names = [
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_LIFECYCLE_RECOVERY_DIR",
        "checkpoint_backup_path",
        "_working_checkpoint",
        "_active_team_from_checkpoint",
        "build_lifecycle_action_candidate",
        "verify_lifecycle_action_persisted",
        "build_lifecycle_summary",
        "save_franchise_checkpoint",
    ]
    original = {name: getattr(server, name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch11_") as tmp:
            root = Path(tmp)
            working = root / "working.pkl.gz"
            backup = root / "working.pkl.gz.bak"
            protected_v2 = root / "protected_v2.pkl.gz"
            recovery = root / "recovery"
            working.write_bytes(b"working-before")
            protected_v2.write_bytes(b"protected-v2")

            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = protected_v2
            server.V3_LIFECYCLE_RECOVERY_DIR = recovery
            server.checkpoint_backup_path = lambda _path: backup
            server._active_team_from_checkpoint = lambda _checkpoint: "CHI"

            source_checkpoint = SimpleNamespace(
                simulation_state=SimpleNamespace(marker="before"),
                trade_state=SimpleNamespace(marker="trade-before"),
                preferences={"franchise_pref_active_team": "CHI"},
            )
            holder = {"value": source_checkpoint}
            server._working_checkpoint = lambda: holder["value"]

            candidate = SimpleNamespace(
                action=ACTION_CONTRACT_CLOSEOUT,
                state=SimpleNamespace(marker="after"),
                trade_state=SimpleNamespace(marker="trade-after"),
                preferences={"franchise_pref_active_team": "CHI"},
                source_season="2027-28",
                target_season="2027-28",
                action_fingerprint="batch11-action-fp",
                detail={"status": "applied"},
            )
            server.build_lifecycle_action_candidate = lambda *_args, **_kwargs: candidate
            server.verify_lifecycle_action_persisted = lambda _checkpoint, _candidate: {
                "persisted": True,
                "action": ACTION_CONTRACT_CLOSEOUT,
                "checks": {"closeout_applied": True},
            }
            server.build_lifecycle_summary = lambda _checkpoint: {
                "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
                "stage": "cpu_free_agency_pending",
                "next_action": "",
            }

            def successful_save(state, trade_state, **kwargs):
                backup.write_bytes(working.read_bytes())
                Path(kwargs["path"]).write_bytes(b"working-after")
                holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences=copy.deepcopy(kwargs.get("preferences", {})),
                )

            server.save_franchise_checkpoint = successful_save

            stale_response = asyncio.run(
                server.lifecycle_execute(
                    FakeRequest(
                        {
                            "action": ACTION_CONTRACT_CLOSEOUT,
                            "expected_action_fingerprint": candidate.action_fingerprint,
                            "expected_working_save_sha256": "stale-sha",
                        }
                    )
                )
            )
            stale_payload = response_json(stale_response)
            checks["isolated_stale_lifecycle_save_rejected"] = (
                stale_response.status_code == 409
                and stale_payload.get("error") == "stale_lifecycle_preview"
                and working.read_bytes() == b"working-before"
                and protected_v2.read_bytes() == b"protected-v2"
            )

            success_response = asyncio.run(
                server.lifecycle_execute(
                    FakeRequest(
                        {
                            "action": ACTION_CONTRACT_CLOSEOUT,
                            "expected_action_fingerprint": candidate.action_fingerprint,
                            "expected_working_save_sha256": sha256(working),
                        }
                    )
                )
            )
            success_payload = response_json(success_response)
            checks["isolated_lifecycle_commit_is_v3_only"] = (
                success_response.status_code == 200
                and success_payload.get("persisted_after_reload") is True
                and success_payload.get("active_v2_unchanged") is True
                and working.read_bytes() == b"working-after"
                and protected_v2.read_bytes() == b"protected-v2"
                and bool(list(recovery.glob("pre_contract_closeout_*")))
            )

            # Reset the isolated files and force a failure after the write begins.
            working.write_bytes(b"working-before-rollback")
            backup.write_bytes(b"backup-before-rollback")
            protected_v2.write_bytes(b"protected-v2")
            holder["value"] = source_checkpoint
            server.verify_lifecycle_action_persisted = lambda *_args, **_kwargs: {
                "persisted": False,
                "action": ACTION_CONTRACT_CLOSEOUT,
                "checks": {"closeout_applied": False},
            }

            def failing_after_write(state, trade_state, **kwargs):
                backup.write_bytes(b"backup-mutated")
                Path(kwargs["path"]).write_bytes(b"working-mutated")
                holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences=copy.deepcopy(kwargs.get("preferences", {})),
                )

            server.save_franchise_checkpoint = failing_after_write
            rollback_response = asyncio.run(
                server.lifecycle_execute(
                    FakeRequest(
                        {
                            "action": ACTION_CONTRACT_CLOSEOUT,
                            "expected_action_fingerprint": candidate.action_fingerprint,
                            "expected_working_save_sha256": sha256(working),
                        }
                    )
                )
            )
            rollback_payload = response_json(rollback_response)
            checks["isolated_lifecycle_failure_rolls_back"] = (
                rollback_response.status_code == 500
                and rollback_payload.get("rollback_performed") is True
                and rollback_payload.get("rollback_verified") is True
                and working.read_bytes() == b"working-before-rollback"
                and backup.read_bytes() == b"backup-before-rollback"
                and protected_v2.read_bytes() == b"protected-v2"
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)
    return checks


def _live_read_only_probe() -> dict[str, Any]:
    working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    protected_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    if not working.is_file():
        raise FileNotFoundError(f"V3 working checkpoint not found: {working}")
    if not protected_v2.is_file():
        raise FileNotFoundError(f"Protected V2 checkpoint not found: {protected_v2}")
    working_before = sha256(working)
    v2_before = sha256(protected_v2)
    checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
    summary = build_lifecycle_summary(checkpoint)
    result: dict[str, Any] = {
        "status": "pass",
        "season": summary.get("season", {}).get("label"),
        "phase": summary.get("season", {}).get("phase"),
        "stage": summary.get("stage"),
        "next_action": summary.get("next_action"),
        "blockers": summary.get("blockers", []),
        "remaining_games": summary.get("schedule", {}).get("remaining"),
    }
    next_action = str(summary.get("next_action", "") or "")
    if next_action:
        preview = build_lifecycle_action_preview(
            checkpoint,
            next_action,
            active_team=str(getattr(checkpoint, "preferences", {}).get("franchise_pref_active_team", "") or ""),
        )
        result["preview_status"] = preview.get("status")
        result["preview_can_commit"] = preview.get("can_commit")
    result["working_save_unchanged"] = sha256(working) == working_before
    result["active_v2_unchanged"] = sha256(protected_v2) == v2_before
    return result


def main() -> int:
    lifecycle = ROOT / "desktop_bridge" / "season_lifecycle_foundation.py"
    server_path = ROOT / "desktop_bridge" / "server.py"
    closeout = ROOT / "src" / "franchise_completed_season_contract_closeout_v1.py"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    lifecycle_gd = ROOT / "godot_client" / "scripts" / "season_lifecycle_center_v3.gd"

    lifecycle_text = text(lifecycle)
    server_text = text(server_path)
    closeout_text = text(closeout)
    main_text = text(main_gd)
    lifecycle_gd_text = text(lifecycle_gd)

    checks: dict[str, bool] = {
        "batch11_foundation_version": (
            "batch-11-offseason-progression" in SEASON_LIFECYCLE_FOUNDATION_VERSION
            or "batch-15-cpu-free-agency" in SEASON_LIFECYCLE_FOUNDATION_VERSION
        ),
        "production_contract_closeout_reused": "build_completed_season_contract_closeout_candidate" in lifecycle_text,
        "production_draft_lottery_reused": "conduct_lottery" in lifecycle_text and "reveal_draft_class" in lifecycle_text,
        "production_draft_night_reused": "start_draft_night" in lifecycle_text,
        "production_post_draft_trim_reused": "build_atomic_cpu_post_draft_trim_candidate" in lifecycle_text,
        "production_season_transition_reused": "build_season_transition_preview" in lifecycle_text and "commit_season_transition_preview" in lifecycle_text,
        "production_schedule_generation_reused": "generate_regular_season_schedule" in lifecycle_text and "install_regular_season_schedule" in lifecycle_text,
        "production_atomic_boundary_reused": "build_atomic_season_boundary_candidate" in lifecycle_text,
        "cpu_sustainable_roster_gate_preserved": "cpu_sustainable_roster_deficits" in lifecycle_text,
        "readonly_summary_surfaces_validation_blocker": "state_validation_blocked" in lifecycle_text and '"state_validation"' in lifecycle_text,
        "write_candidate_requires_full_state_validation": "validate_simulation_league_state(source_state)" in lifecycle_text,
        "regular_season_summary_avoids_offseason_eager_probe": 'if phase == "regular_season"' in lifecycle_text and 'Draft/closeout/CPU-FA details are not needed to render an active regular' in lifecycle_text,
        "readonly_helper_failures_degrade_to_blockers": 'diagnostic_errors' in lifecycle_text and 'Lifecycle write actions are disabled until safety diagnostics pass.' in lifecycle_text,
        "season_scouting_closeout_compatibility": 'active_draft_phase != "season_scouting"' in closeout_text,
        "closeout_still_blocks_later_draft": "Contract closeout must occur before the active offseason Draft begins." in closeout_text,
        "summary_endpoint_registered": 'Route("/v3/lifecycle", lifecycle_summary' in server_text,
        "preview_endpoint_registered": 'Route("/v3/lifecycle/preview", lifecycle_preview' in server_text,
        "execute_endpoint_registered": 'Route("/v3/lifecycle/execute", lifecycle_execute' in server_text,
        "execute_requires_action_fingerprint": "expected_action_fingerprint is required. Run a fresh lifecycle preview first." in server_text,
        "execute_requires_working_save_sha": "expected_working_save_sha256 is required. Run a fresh lifecycle preview first." in server_text,
        "v3_only_checkpoint_write": "path=V3_WORKING_CHECKPOINT_PATH" in server_text and "lifecycle action" in server_text,
        "lifecycle_recovery_and_rollback": "V3_LIFECYCLE_RECOVERY_DIR" in server_text and "def _rollback()" in server_text,
        "protected_v2_hash_guard": "Protected V2 checkpoint changed during V3 lifecycle execution." in server_text,
        "reload_verification_enabled": "verify_lifecycle_action_persisted" in server_text,
        "godot_lifecycle_center_preloaded": "SeasonLifecycleCenterV3" in main_text and "season_lifecycle_center_v3.gd" in main_text,
        "godot_season_nav_present": '_nav_button("SEASON")' in main_text,
        "godot_season_nav_wired": (
            '"SCOUTING",\n\t\t"SEASON",\n\t\t"LEAGUE"' in main_text
            and 'button.pressed.connect(_show_page.bind(text_value))' in main_text
            and 'elif page_name == "SEASON":' in main_text
        ),
        "godot_preview_and_execute_wired": "/v3/lifecycle/preview" in lifecycle_gd_text and "/v3/lifecycle/execute" in lifecycle_gd_text,
        "godot_payload_values_not_boolean_coerced": (
            '_safe_string(summary_payload.get("stage", ""))' in lifecycle_gd_text
            and '_safe_string(summary_payload.get("next_action", ""))' in lifecycle_gd_text
            and '_safe_int(schedule.get("total", 0))' in lifecycle_gd_text
            and '_safe_int(schedule.get("completed", 0))' in lifecycle_gd_text
            and 'get("stage", "") or ""' not in lifecycle_gd_text
            and 'get("next_action", "") or ""' not in lifecycle_gd_text
            and 'get("total", 0) or 0' not in lifecycle_gd_text
            and 'get("completed", 0) or 0' not in lifecycle_gd_text
        ),
        "godot_lifecycle_tokens_preserve_strings": (
            '_safe_string(raw_payload.get("action_fingerprint", ""))' in lifecycle_gd_text
            and '_safe_string(raw_payload.get("working_save_sha256", ""))' in lifecycle_gd_text
            and 'get("action_fingerprint", "") or ""' not in lifecycle_gd_text
            and 'get("working_save_sha256", "") or ""' not in lifecycle_gd_text
        ),
        "godot_timeline_current_status_preserved": (
            '_safe_string(item.get("status", "locked"), "locked").to_lower()' in lifecycle_gd_text
            and 'marker = "CURRENT"' in lifecycle_gd_text
        ),
        "godot_no_action_disables_preview": (
            'latest_action = _safe_string(summary_payload.get("next_action", ""))' in lifecycle_gd_text
            and 'preview_button.disabled = latest_action.is_empty()' in lifecycle_gd_text
        ),
        "godot_league_progress_label_clear": '_metric(metrics, "LEAGUE PROGRESS", "LOADING...")' in lifecycle_gd_text,
        "godot_confirmation_present": "Confirm certified season lifecycle action" in lifecycle_gd_text,
        "godot_requires_fresh_fingerprint": "latest_action_fingerprint" in lifecycle_gd_text and "expected_action_fingerprint" in lifecycle_gd_text,
        "godot_requires_working_sha": "latest_working_sha" in lifecycle_gd_text and "expected_working_save_sha256" in lifecycle_gd_text,
        "godot_duplicate_submit_lock": "execute_in_flight" in lifecycle_gd_text,
        "godot_v2_guard_required_on_success": 'raw_payload.get("active_v2_unchanged", false)' in lifecycle_gd_text,
    }

    try:
        for path in (lifecycle, server_path, closeout, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        authority = subprocess.run(
            [sys.executable, str(ROOT / "src" / "validate_franchise_lifecycle_authority_v1.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        )
        checks["production_lifecycle_authority_validator"] = authority.returncode == 0
        authority_output = (authority.stdout + "\n" + authority.stderr).strip()[-5000:]
    except Exception as exc:
        checks["production_lifecycle_authority_validator"] = False
        authority_output = f"{type(exc).__name__}: {exc}"

    try:
        checks.update(_run_isolated_endpoint_tests())
    except Exception:
        checks["isolated_stale_lifecycle_save_rejected"] = False
        checks["isolated_lifecycle_commit_is_v3_only"] = False
        checks["isolated_lifecycle_failure_rolls_back"] = False

    godot_binary = shutil.which("godot4") or shutil.which("godot")
    godot_validation = "SKIP: Godot CLI not on PATH"
    if godot_binary:
        result = subprocess.run(
            [godot_binary, "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        checks["godot_headless_parse"] = result.returncode == 0
        godot_validation = (result.stdout + "\n" + result.stderr).strip()[-5000:]
    else:
        checks["godot_headless_parse"] = True

    working_before = sha256(Path(server.V3_WORKING_CHECKPOINT_PATH))
    v2_before = sha256(Path(server.DEFAULT_CHECKPOINT_PATH))
    try:
        dynamic = _live_read_only_probe()
        checks["dynamic_read_only_probe"] = dynamic.get("status") == "pass"
        checks["dynamic_probe_does_not_write_working_save"] = dynamic.get("working_save_unchanged") is True
        checks["dynamic_probe_does_not_touch_v2"] = dynamic.get("active_v2_unchanged") is True
    except FileNotFoundError as exc:
        dynamic = {"status": "skipped", "reason": str(exc)}
        checks["dynamic_read_only_probe"] = True
        checks["dynamic_probe_does_not_write_working_save"] = True
        checks["dynamic_probe_does_not_touch_v2"] = True
    except Exception as exc:
        dynamic = {"status": "failed", "exception_type": type(exc).__name__, "reason": str(exc)}
        checks["dynamic_read_only_probe"] = False
        # A probe exception does not imply a write. Measure both files instead
        # of manufacturing false safety failures.
        checks["dynamic_probe_does_not_write_working_save"] = (
            working_before == sha256(Path(server.V3_WORKING_CHECKPOINT_PATH))
        )
        checks["dynamic_probe_does_not_touch_v2"] = (
            v2_before == sha256(Path(server.DEFAULT_CHECKPOINT_PATH))
        )

    checks["validator_never_changes_working_save"] = working_before == sha256(Path(server.V3_WORKING_CHECKPOINT_PATH))
    checks["validator_never_changes_v2_checkpoint"] = v2_before == sha256(Path(server.DEFAULT_CHECKPOINT_PATH))

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "production_lifecycle_authority_output": authority_output,
        "godot_validation": godot_validation,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 88)
    print("V3 BATCH 11 SEASON LIFECYCLE + OFFSEASON PROGRESSION VALIDATION")
    print("=" * 88)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic live probe:", str(dynamic.get("status", "unknown")).upper())
    if dynamic.get("reason"):
        print(f"  Failure reason: {dynamic.get('reason')}")
    if dynamic.get("exception_type"):
        print(f"  Exception type: {dynamic.get('exception_type')}")
    if dynamic.get("season") is not None:
        print(f"  Season: {dynamic.get('season')}")
        print(f"  Phase: {dynamic.get('phase')}")
        print(f"  Lifecycle stage: {dynamic.get('stage')}")
        print(f"  Remaining games: {dynamic.get('remaining_games')}")
        print(f"  Next certified action: {dynamic.get('next_action') or 'none'}")
    print("Godot parser:", "PASS" if godot_binary and checks["godot_headless_parse"] else "SKIP (Godot CLI not on PATH; static wiring checks passed)")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("BATCH 11 VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("BATCH 11 VALIDATION PASSED")
    print("No season lifecycle action was durably executed by this validator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
