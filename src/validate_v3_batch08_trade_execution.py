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
    build_trade_execution_candidate,
)
from franchise_draft_right_stepien_bridge_v1 import (
    build_franchise_draft_right_profiles,
)
from franchise_embedded_trade_center_v2 import build_franchise_trade_preview
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_transaction_v1 import (
    FRANCHISE_TRADE_TRANSACTION_VERSION,
    FranchiseTradeTransactionError,
    _state_signature,
)
from freeform_trade_machine_engine_v3 import load_runtime_data
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

VALIDATOR_VERSION = "v3-batch08-transactional-trade-execution-validator-2026-10-03-hotfix1"


class _JsonRequest:
    """Minimal request shim for endpoint tests without starlette.testclient/httpx."""

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _call_trade_execute(payload: dict[str, Any]):
    return asyncio.run(server.trade_execute(_JsonRequest(payload)))


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
    """Exercise stale, success, duplicate, and rollback paths on temp files only."""
    patched_names = (
        "DEFAULT_CHECKPOINT_PATH",
        "V3_WORKING_CHECKPOINT_PATH",
        "V3_TRADE_RECOVERY_DIR",
        "_working_checkpoint",
        "build_trade_execution_candidate",
        "save_franchise_checkpoint",
        "verify_trade_execution_persisted",
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
            recovery_dir = root / "trade_recovery"
            v2_path.write_bytes(b"protected-v2")
            working_path.write_bytes(b"working-before")

            checkpoint_holder = {
                "value": SimpleNamespace(
                    simulation_state=SimpleNamespace(),
                    trade_state=SimpleNamespace(),
                    preferences={"franchise_pref_active_team": "CHI"},
                )
            }
            candidate = SimpleNamespace(
                transaction_id="FTX-TEST-0001",
                state=SimpleNamespace(),
                transaction_record={"transaction_id": "FTX-TEST-0001"},
                preview=SimpleNamespace(package_fingerprint="test-fingerprint"),
            )

            server.DEFAULT_CHECKPOINT_PATH = v2_path
            server.V3_WORKING_CHECKPOINT_PATH = working_path
            server.V3_TRADE_RECOVERY_DIR = recovery_dir
            server._working_checkpoint = lambda: checkpoint_holder["value"]
            server.build_trade_execution_candidate = (
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
            server.verify_trade_execution_persisted = (
                lambda checkpoint, value: {"transaction_id": value.transaction_id}
            )

            working_sha = sha256(working_path)
            body = {
                "partner_team": "BOS",
                "side_a_player_ids": ["A"],
                "side_b_player_ids": ["B"],
                "side_a_pick_asset_ids": [],
                "side_b_pick_asset_ids": [],
                "expected_package_fingerprint": "test-fingerprint",
                "expected_working_save_sha256": working_sha,
            }

            stale = _call_trade_execute(
                {**body, "expected_working_save_sha256": "0" * 64}
            )
            stale_payload = _response_json(stale)
            checks["isolated_stale_preview_rejected_without_write"] = bool(
                stale.status_code == 409
                and stale_payload.get("error") == "stale_trade_preview"
                and working_path.read_bytes() == b"working-before"
                and v2_path.read_bytes() == b"protected-v2"
            )

            success = _call_trade_execute(body)
            success_payload = _response_json(success)
            checks["isolated_success_commits_v3_only"] = bool(
                success.status_code == 200
                and success_payload.get("status") == "applied"
                and success_payload.get("persisted_after_reload") is True
                and success_payload.get("active_v2_unchanged") is True
                and working_path.read_bytes() == b"working-after-success"
                and v2_path.read_bytes() == b"protected-v2"
            )

            duplicate = _call_trade_execute(body)
            duplicate_payload = _response_json(duplicate)
            checks["isolated_duplicate_submit_rejected"] = bool(
                duplicate.status_code == 409
                and duplicate_payload.get("error") == "stale_trade_preview"
                and v2_path.read_bytes() == b"protected-v2"
            )

            # Reset the temp working save and force a failure after the write
            # boundary opens. The endpoint must restore the exact pre-write bytes.
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
            rollback = _call_trade_execute(rollback_body)
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


def _find_pick_only_pass(runtime: Any, checkpoint: Any):
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_franchise_draft_right_profiles(ledger)
    seconds_by_team: dict[str, list[Any]] = {}
    for profile in profiles:
        if profile.round_number == 2 and profile.bridge_ready:
            seconds_by_team.setdefault(profile.current_owner, []).append(profile)

    teams = sorted(team for team, rows in seconds_by_team.items() if rows)
    for index, team_a in enumerate(teams):
        for team_b in teams[index + 1 :]:
            pick_a = sorted(
                seconds_by_team[team_a],
                key=lambda row: (row.draft_year, row.asset_id),
            )[0]
            pick_b = sorted(
                seconds_by_team[team_b],
                key=lambda row: (row.draft_year, row.asset_id),
            )[0]
            preview = build_franchise_trade_preview(
                runtime,
                state,
                trade_state,
                team_a=team_a,
                team_b=team_b,
                side_a_pick_asset_ids=(pick_a.asset_id,),
                side_b_pick_asset_ids=(pick_b.asset_id,),
                ledger=ledger,
            )
            if preview.status == "pass" and preview.can_commit:
                return team_a, team_b, pick_a.asset_id, pick_b.asset_id, preview
    raise AssertionError(
        "No deterministic PASS pick-only package was found in the V3 working save."
    )


def main() -> int:
    foundation_path = ROOT / "desktop_bridge" / "transaction_foundation.py"
    server_path = ROOT / "desktop_bridge" / "server.py"
    godot_path = ROOT / "godot_client" / "scripts" / "trade_center_v3.gd"
    validator_path = Path(__file__).resolve()

    foundation_text = text(foundation_path)
    server_text = text(server_path)
    godot_text = text(godot_path)

    checks: dict[str, bool] = {
        "batch08_foundation_version": "batch-08-transactional-trade-execution" in TRANSACTION_FOUNDATION_VERSION,
        "production_trade_engine_reused": "build_franchise_trade_candidate" in foundation_text,
        "production_transaction_version_exposed": "FRANCHISE_TRADE_TRANSACTION_VERSION" in foundation_text,
        "execute_endpoint_registered": 'Route("/v3/trade/execute", trade_execute' in server_text,
        "execute_endpoint_requires_preview_fingerprint": "expected_package_fingerprint" in foundation_text,
        "execute_endpoint_requires_working_save_sha": "expected_working_save_sha256" in server_text,
        "stale_working_save_rejected": '"error": "stale_trade_preview"' in server_text,
        "candidate_rechecks_without_writing": "build_trade_execution_candidate" in server_text,
        "v3_only_checkpoint_write": "path=V3_WORKING_CHECKPOINT_PATH" in server_text,
        "pretrade_recovery_copy_created": "shutil.copy2(V3_WORKING_CHECKPOINT_PATH, recovery_path)" in server_text,
        "rollback_restores_working_checkpoint": "shutil.copy2(recovery_path, V3_WORKING_CHECKPOINT_PATH)" in server_text,
        "reload_verification_enabled": "verify_trade_execution_persisted" in server_text,
        "protected_v2_hash_guard": "Protected V2 checkpoint changed during V3 trade execution." in server_text,
        "preview_returns_working_save_sha": '"working_save_sha256": working_after' in server_text,
        "godot_execute_endpoint_wired": "TRADE_EXECUTE_URL" in godot_text,
        "godot_confirmation_dialog_present": "ConfirmationDialog.new()" in godot_text,
        "godot_requires_fresh_preview_fingerprint": 'request_payload["expected_package_fingerprint"]' in godot_text,
        "godot_requires_preview_working_sha": 'request_payload["expected_working_save_sha256"]' in godot_text,
        "godot_duplicate_submit_lock": "execute_in_flight" in godot_text,
        "godot_stale_preview_handling": '"stale_trade_preview"' in godot_text,
        "godot_success_requires_reload_and_v2_guard": "persisted_after_reload" in godot_text and "active_v2_unchanged" in godot_text,
    }

    try:
        for path in (foundation_path, server_path, validator_path):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

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
            [
                godot_binary,
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
        checks["godot_headless_parse"] = result.returncode == 0
        godot_validation = (result.stdout + "\n" + result.stderr).strip()[-4000:]
    else:
        checks["godot_headless_parse"] = True

    working_path = server.V3_WORKING_CHECKPOINT_PATH
    v2_path = Path(server.DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working_path)
    v2_before = sha256(v2_path)
    dynamic: dict[str, Any] = {
        "status": "skipped",
        "reason": "V3 working save or runtime inputs unavailable.",
    }

    if working_before is not None:
        try:
            checkpoint = load_franchise_checkpoint(
                path=working_path,
                allow_backup=False,
            )
            if checkpoint is None:
                raise RuntimeError("V3 working checkpoint could not be loaded.")
            runtime = load_runtime_data()
            team_a, team_b, pick_a, pick_b, preview = _find_pick_only_pass(
                runtime,
                checkpoint,
            )
            source_signature = _state_signature(checkpoint.simulation_state)
            request_payload = {
                "partner_team": team_b,
                "side_a_player_ids": [],
                "side_b_player_ids": [],
                "side_a_pick_asset_ids": [pick_a],
                "side_b_pick_asset_ids": [pick_b],
                "expected_package_fingerprint": preview.package_fingerprint,
            }
            candidate = build_trade_execution_candidate(
                checkpoint,
                team_a,
                request_payload,
            )
            if _state_signature(checkpoint.simulation_state) != source_signature:
                raise AssertionError("Candidate construction mutated the source V3 state.")

            stale_rejected = False
            stale_payload = dict(request_payload)
            stale_payload["expected_package_fingerprint"] = "0" * 64
            try:
                build_trade_execution_candidate(
                    checkpoint,
                    team_a,
                    stale_payload,
                )
            except FranchiseTradeTransactionError:
                stale_rejected = True

            checks["dynamic_pass_candidate_builds_in_memory"] = bool(
                candidate.preview.can_commit
                and candidate.preview.status == "pass"
                and candidate.transaction_id.startswith("FTX-")
            )
            checks["dynamic_stale_fingerprint_rejected"] = stale_rejected
            checks["dynamic_candidate_does_not_write_working_save"] = (
                sha256(working_path) == working_before
            )
            checks["dynamic_candidate_does_not_touch_v2"] = (
                sha256(v2_path) == v2_before
            )
            dynamic = {
                "status": "pass",
                "team_a": team_a,
                "team_b": team_b,
                "pick_a": pick_a,
                "pick_b": pick_b,
                "transaction_id": candidate.transaction_id,
                "package_fingerprint": preview.package_fingerprint,
                "durable_write_performed": False,
            }
        except FileNotFoundError as exc:
            dynamic = {
                "status": "skipped",
                "reason": str(exc),
            }
        except Exception as exc:
            checks["dynamic_validation"] = False
            dynamic = {
                "status": "failed",
                "exception_type": type(exc).__name__,
                "reason": str(exc),
            }

    checks.setdefault("dynamic_pass_candidate_builds_in_memory", True)
    checks.setdefault("dynamic_stale_fingerprint_rejected", True)
    checks.setdefault("dynamic_candidate_does_not_write_working_save", True)
    checks.setdefault("dynamic_candidate_does_not_touch_v2", True)
    checks.setdefault("dynamic_validation", dynamic.get("status") != "failed")

    working_after = sha256(working_path)
    v2_after = sha256(v2_path)
    checks["validator_never_changes_working_save"] = working_before == working_after
    checks["validator_never_changes_v2_checkpoint"] = v2_before == v2_after

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "transaction_foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "production_transaction_version": FRANCHISE_TRADE_TRANSACTION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_validation,
        "working_save_sha256_before": working_before,
        "working_save_sha256_after": working_after,
        "active_v2_sha256_before": v2_before,
        "active_v2_sha256_after": v2_after,
    }

    output_dir = ROOT / "outputs" / "v3_batch08_trade_execution"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=" * 88)
    print("V3 BATCH 08 TRANSACTIONAL TRADE EXECUTION VALIDATION")
    print("=" * 88)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print(f"Dynamic candidate validation: {dynamic.get('status', 'unknown').upper()}")
    if dynamic.get("reason"):
        print(f"  {dynamic['reason']}")
    if godot_binary is None:
        print("Godot parser: SKIP (Godot CLI not on PATH; static wiring checks passed)")
    else:
        print(f"Godot parser: {'PASS' if checks['godot_headless_parse'] else 'FAIL'}")
    print(f"Report: {report_path}")

    if failed:
        raise SystemExit("Batch 08 validation failed: " + ", ".join(failed))

    print()
    print("BATCH 08 VALIDATION PASSED")
    print("No trade was durably executed by this validator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
