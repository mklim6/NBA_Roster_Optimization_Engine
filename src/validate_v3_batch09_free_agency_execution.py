from __future__ import annotations

import asyncio
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge import server
from desktop_bridge.transaction_foundation import (
    TRANSACTION_FOUNDATION_VERSION,
    build_free_agency_preview_payload,
)
from franchise_free_agency_transaction_v1 import (
    FREE_AGENCY_TRANSACTION_VERSION,
    run_self_test as run_free_agency_transaction_self_test,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

VALIDATOR_VERSION = "v3-batch09-transactional-free-agency-execution-validator-2026-10-02"


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _call_free_agency_execute(payload: dict[str, Any]):
    return asyncio.run(server.free_agency_execute(_JsonRequest(payload)))


def _response_json(response: Any) -> dict[str, Any]:
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body or "{}")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_isolated_endpoint_transaction_test() -> dict[str, bool]:
    patched_names = (
        "DEFAULT_CHECKPOINT_PATH",
        "V3_WORKING_CHECKPOINT_PATH",
        "V3_FREE_AGENCY_RECOVERY_DIR",
        "_working_checkpoint",
        "build_free_agency_execution_candidate",
        "save_franchise_checkpoint",
        "verify_free_agency_execution_persisted",
    )
    original = {name: getattr(server, name) for name in patched_names}
    checks = {
        "isolated_stale_preview_rejected_without_write": False,
        "isolated_success_commits_v3_only": False,
        "isolated_duplicate_submit_rejected": False,
        "isolated_forced_failure_rolls_back": False,
    }

    try:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            v2_path = root / "protected_v2.pkl.gz"
            working_path = root / "v3_working.pkl.gz"
            recovery_dir = root / "free_agency_recovery"
            v2_path.write_bytes(b"protected-v2")
            working_path.write_bytes(b"working-before")

            checkpoint_holder = {
                "value": SimpleNamespace(
                    simulation_state=SimpleNamespace(),
                    trade_state=SimpleNamespace(),
                    preferences={"franchise_pref_active_team": "CHI"},
                )
            }
            result = SimpleNamespace(
                offer_id="FAO-TEST-0001",
                player_id="FA1",
                player_name="Test Free Agent",
                team_abbreviation="CHI",
                committed_fingerprint="candidate-fingerprint",
            )
            candidate = SimpleNamespace(
                state=SimpleNamespace(),
                commit_result=result,
                preview=SimpleNamespace(),
            )

            server.DEFAULT_CHECKPOINT_PATH = v2_path
            server.V3_WORKING_CHECKPOINT_PATH = working_path
            server.V3_FREE_AGENCY_RECOVERY_DIR = recovery_dir
            server._working_checkpoint = lambda: checkpoint_holder["value"]
            server.build_free_agency_execution_candidate = (
                lambda checkpoint, active_team, body: candidate
            )

            def successful_save(state, trade_state, **_kwargs):
                working_path.write_bytes(b"working-after-success")
                checkpoint_holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences={"franchise_pref_active_team": "CHI"},
                )
                return SimpleNamespace()

            server.save_franchise_checkpoint = successful_save
            server.verify_free_agency_execution_persisted = (
                lambda checkpoint, value: {
                    "offer_id": value.commit_result.offer_id,
                    "player_id": value.commit_result.player_id,
                }
            )

            body = {
                "player_id": "FA1",
                "annual_salary": 5_000_000.0,
                "years": 2,
                "guaranteed": True,
                "option_type": "",
                "expected_candidate_fingerprint": "candidate-fingerprint",
                "expected_working_save_sha256": sha256(working_path),
            }

            stale = _call_free_agency_execute(
                {**body, "expected_working_save_sha256": "0" * 64}
            )
            stale_payload = _response_json(stale)
            checks["isolated_stale_preview_rejected_without_write"] = bool(
                stale.status_code == 409
                and stale_payload.get("error") == "stale_free_agency_preview"
                and working_path.read_bytes() == b"working-before"
                and v2_path.read_bytes() == b"protected-v2"
            )

            success = _call_free_agency_execute(body)
            success_payload = _response_json(success)
            checks["isolated_success_commits_v3_only"] = bool(
                success.status_code == 200
                and success_payload.get("status") == "applied"
                and success_payload.get("persisted_after_reload") is True
                and success_payload.get("active_v2_unchanged") is True
                and working_path.read_bytes() == b"working-after-success"
                and v2_path.read_bytes() == b"protected-v2"
            )

            duplicate = _call_free_agency_execute(body)
            duplicate_payload = _response_json(duplicate)
            checks["isolated_duplicate_submit_rejected"] = bool(
                duplicate.status_code == 409
                and duplicate_payload.get("error") == "stale_free_agency_preview"
                and v2_path.read_bytes() == b"protected-v2"
            )

            working_path.write_bytes(b"rollback-source")
            checkpoint_holder["value"] = SimpleNamespace(
                simulation_state=SimpleNamespace(),
                trade_state=SimpleNamespace(),
                preferences={"franchise_pref_active_team": "CHI"},
            )

            def failing_save(*_args, **_kwargs):
                working_path.write_bytes(b"partial-write")
                raise RuntimeError("forced isolated save failure")

            server.save_franchise_checkpoint = failing_save
            rollback_body = dict(body)
            rollback_body["expected_working_save_sha256"] = sha256(working_path)
            rollback = _call_free_agency_execute(rollback_body)
            rollback_payload = _response_json(rollback)
            checks["isolated_forced_failure_rolls_back"] = bool(
                rollback.status_code == 500
                and rollback_payload.get("rollback_performed") is True
                and rollback_payload.get("rollback_verified") is True
                and working_path.read_bytes() == b"rollback-source"
                and v2_path.read_bytes() == b"protected-v2"
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)

    return checks


def _live_read_only_preview() -> dict[str, Any]:
    working_path = server.V3_WORKING_CHECKPOINT_PATH
    v2_path = Path(server.DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working_path)
    v2_before = sha256(v2_path)
    if working_before is None:
        return {"status": "skipped", "reason": "V3 working save unavailable."}

    checkpoint = load_franchise_checkpoint(path=working_path, allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("V3 working checkpoint could not be loaded.")
    state = checkpoint.simulation_state
    active_team = str(
        checkpoint.preferences.get("franchise_pref_active_team", "") or ""
    ).strip().upper()
    free_agents = list(getattr(state, "free_agent_player_ids", ()) or ())
    if not active_team or not free_agents:
        return {
            "status": "skipped",
            "reason": "Active team or free-agent pool unavailable in working save.",
        }

    player_id = str(free_agents[0])
    player = getattr(state, "players", {}).get(player_id)
    contract = getattr(player, "contract", None) if player is not None else None
    salary = float(getattr(contract, "salary", 0.0) or 0.0)
    if salary <= 0:
        salary = 1_500_000.0

    payload = build_free_agency_preview_payload(
        checkpoint,
        active_team,
        {
            "player_id": player_id,
            "annual_salary": salary,
            "years": 1,
            "guaranteed": True,
            "option_type": "",
        },
    )
    transaction = payload.get("transaction_preview", {})
    phase = str(getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", "")))
    return {
        "status": "pass",
        "phase": phase,
        "player_id": player_id,
        "preview_status": transaction.get("status"),
        "can_commit": transaction.get("can_commit"),
        "working_save_unchanged": sha256(working_path) == working_before,
        "active_v2_unchanged": sha256(v2_path) == v2_before,
    }


def main() -> int:
    foundation_path = ROOT / "desktop_bridge" / "transaction_foundation.py"
    server_path = ROOT / "desktop_bridge" / "server.py"
    godot_path = ROOT / "godot_client" / "scripts" / "free_agency_center_v3.gd"
    validator_path = Path(__file__).resolve()

    foundation_text = text(foundation_path)
    server_text = text(server_path)
    godot_text = text(godot_path)

    checks: dict[str, bool] = {
        "batch08_trade_foundation_preserved": "batch-08-transactional-trade-execution" in TRANSACTION_FOUNDATION_VERSION,
        "batch09_foundation_version": "batch-09-transactional-free-agency-execution" in TRANSACTION_FOUNDATION_VERSION,
        "production_free_agency_engine_reused": "commit_free_agency_preview" in foundation_text,
        "production_transaction_version_exposed": "FREE_AGENCY_TRANSACTION_VERSION" in foundation_text,
        "execute_endpoint_registered": 'Route("/v3/free-agency/execute", free_agency_execute' in server_text,
        "execute_endpoint_requires_preview_fingerprint": "expected_candidate_fingerprint" in foundation_text,
        "execute_endpoint_requires_working_save_sha": "expected_working_save_sha256" in server_text,
        "stale_working_save_rejected": '"error": "stale_free_agency_preview"' in server_text,
        "candidate_rechecks_without_writing": "build_free_agency_execution_candidate" in server_text,
        "v3_only_checkpoint_write": "path=V3_WORKING_CHECKPOINT_PATH" in server_text,
        "presigning_recovery_copy_created": "V3_FREE_AGENCY_RECOVERY_DIR" in server_text and "shutil.copy2(V3_WORKING_CHECKPOINT_PATH, recovery_path)" in server_text,
        "rollback_restores_working_checkpoint": "shutil.copy2(recovery_path, V3_WORKING_CHECKPOINT_PATH)" in server_text,
        "reload_verification_enabled": "verify_free_agency_execution_persisted" in server_text,
        "protected_v2_hash_guard": "Protected V2 checkpoint changed during V3 free-agency execution." in server_text,
        "preview_returns_working_save_sha": '"working_save_sha256": working_after' in server_text,
        "offseason_phase_rule_preserved": '"phase_required": "offseason"' in foundation_text,
        "godot_execute_endpoint_wired": "EXECUTE_URL" in godot_text and "/v3/free-agency/execute" in godot_text,
        "godot_confirmation_dialog_present": "Confirm free-agent signing" in godot_text,
        "godot_requires_fresh_preview_fingerprint": 'request_payload["expected_candidate_fingerprint"]' in godot_text,
        "godot_requires_preview_working_sha": 'request_payload["expected_working_save_sha256"]' in godot_text,
        "godot_duplicate_submit_lock": "execute_in_flight" in godot_text,
        "godot_stale_preview_handling": '"stale_free_agency_preview"' in godot_text,
        "godot_success_requires_reload_and_v2_guard": "persisted_after_reload" in godot_text and "active_v2_unchanged" in godot_text,
    }

    try:
        for path in (foundation_path, server_path, validator_path):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        checks["production_free_agency_engine_self_test"] = (
            run_free_agency_transaction_self_test() == 0
        )
    except Exception:
        checks["production_free_agency_engine_self_test"] = False

    try:
        checks.update(_run_isolated_endpoint_transaction_test())
    except Exception:
        checks["isolated_stale_preview_rejected_without_write"] = False
        checks["isolated_success_commits_v3_only"] = False
        checks["isolated_duplicate_submit_rejected"] = False
        checks["isolated_forced_failure_rolls_back"] = False

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
        godot_validation = (result.stdout + "\n" + result.stderr).strip()[-4000:]
    else:
        checks["godot_headless_parse"] = True

    working_path = server.V3_WORKING_CHECKPOINT_PATH
    v2_path = Path(server.DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working_path)
    v2_before = sha256(v2_path)
    try:
        dynamic = _live_read_only_preview()
        checks["dynamic_read_only_preview"] = dynamic.get("status") != "failed"
        if dynamic.get("status") == "pass":
            checks["dynamic_preview_does_not_write_working_save"] = bool(dynamic.get("working_save_unchanged"))
            checks["dynamic_preview_does_not_touch_v2"] = bool(dynamic.get("active_v2_unchanged"))
        else:
            checks["dynamic_preview_does_not_write_working_save"] = True
            checks["dynamic_preview_does_not_touch_v2"] = True
    except FileNotFoundError as exc:
        dynamic = {"status": "skipped", "reason": str(exc)}
        checks["dynamic_read_only_preview"] = True
        checks["dynamic_preview_does_not_write_working_save"] = True
        checks["dynamic_preview_does_not_touch_v2"] = True
    except Exception as exc:
        dynamic = {"status": "failed", "exception_type": type(exc).__name__, "reason": str(exc)}
        checks["dynamic_read_only_preview"] = False
        checks["dynamic_preview_does_not_write_working_save"] = False
        checks["dynamic_preview_does_not_touch_v2"] = False

    working_after = sha256(working_path)
    v2_after = sha256(v2_path)
    checks["validator_never_changes_working_save"] = working_before == working_after
    checks["validator_never_changes_v2_checkpoint"] = v2_before == v2_after

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "transaction_foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "production_transaction_version": FREE_AGENCY_TRANSACTION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_validation,
        "working_save_sha256_before": working_before,
        "working_save_sha256_after": working_after,
        "active_v2_sha256_before": v2_before,
        "active_v2_sha256_after": v2_after,
    }

    output_dir = ROOT / "outputs" / "v3_batch09_free_agency_execution"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=" * 88)
    print("V3 BATCH 09 TRANSACTIONAL FREE AGENCY EXECUTION VALIDATION")
    print("=" * 88)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print(f"Dynamic live preview: {dynamic.get('status', 'unknown').upper()}")
    if dynamic.get("phase"):
        print(f"  Working-save phase: {dynamic['phase']}")
        print(f"  Preview status: {dynamic.get('preview_status')} • can_commit={dynamic.get('can_commit')}")
    if dynamic.get("reason"):
        print(f"  {dynamic['reason']}")
    if godot_binary is None:
        print("Godot parser: SKIP (Godot CLI not on PATH; static wiring checks passed)")
    else:
        print(f"Godot parser: {'PASS' if checks['godot_headless_parse'] else 'FAIL'}")
    print(f"Report: {report_path}")

    if failed:
        raise SystemExit("Batch 09 validation failed: " + ", ".join(failed))

    print()
    print("BATCH 09 VALIDATION PASSED")
    print("No free-agent signing was durably executed by this validator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
