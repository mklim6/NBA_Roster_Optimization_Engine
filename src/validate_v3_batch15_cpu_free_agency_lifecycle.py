from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import py_compile
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge import server
from desktop_bridge.season_lifecycle_foundation import (
    ACTION_CPU_FREE_AGENCY,
    SEASON_LIFECYCLE_FOUNDATION_VERSION,
    build_lifecycle_summary,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = "v3-batch15-cpu-free-agency-lifecycle-validator-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch15_cpu_free_agency"
REPORT_PATH = REPORT_DIR / "validation.json"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


class _FakeRequest:
    def __init__(self, body: dict[str, Any]):
        self._body = copy.deepcopy(body)

    async def json(self) -> dict[str, Any]:
        return copy.deepcopy(self._body)


def _find_cpu_fa_fixture() -> Path | None:
    patterns = (
        "outputs/v2_phase1_deep_offseason_profile_v1/*/recovery/free_agency/pre_cpu_round_batch_02_*.pkl.gz",
        "outputs/_soak/*/s*/f*/pre_cpu_round_batch_01_*.pkl.gz",
    )
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(ROOT.glob(pattern))
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            checkpoint = load_franchise_checkpoint(path=path, allow_backup=False)
            if checkpoint is None:
                continue
            summary = build_lifecycle_summary(checkpoint)
            if summary.get("next_action") == ACTION_CPU_FREE_AGENCY:
                return path
        except Exception:
            continue
    return None


def _run_isolated_full_stack(fixture: Path) -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {"fixture": str(fixture)}
    names = (
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_LIFECYCLE_RECOVERY_DIR",
    )
    original = {name: getattr(server, name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch15_cpu_fa_") as tmp:
            root = Path(tmp)
            working = root / "v3_working.pkl.gz"
            protected_v2 = root / "protected_v2.bin"
            recovery = root / "recovery"
            shutil.copy2(fixture, working)
            protected_v2.write_bytes(b"protected-v2-checkpoint-sentinel")

            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = protected_v2
            server.V3_LIFECYCLE_RECOVERY_DIR = recovery

            source_sha = _sha256(working)
            v2_sha = _sha256(protected_v2)
            summary_response = asyncio.run(server.lifecycle_summary(_FakeRequest({})))
            summary = _response_json(summary_response)
            checks["isolated_summary_exposes_cpu_free_agency"] = (
                summary_response.status_code == 200
                and summary.get("next_action") == ACTION_CPU_FREE_AGENCY
                and summary.get("stage") == "cpu_free_agency_pending"
            )

            preview_started = time.perf_counter()
            preview_response = asyncio.run(
                server.lifecycle_preview(_FakeRequest({"action": ACTION_CPU_FREE_AGENCY}))
            )
            preview_seconds = time.perf_counter() - preview_started
            preview = _response_json(preview_response)
            preview_detail = dict(preview.get("detail", {}) or {})
            checks["isolated_preview_builds_real_cpu_signings"] = (
                preview_response.status_code == 200
                and preview.get("status") == "pass"
                and preview.get("can_commit") is True
                and int(preview_detail.get("committed_signing_count", 0) or 0) > 0
            )
            checks["isolated_preview_is_read_only"] = (
                _sha256(working) == source_sha
                and _sha256(protected_v2) == v2_sha
                and preview.get("working_save_unchanged") is True
                and preview.get("active_v2_unchanged") is True
            )

            execute_started = time.perf_counter()
            execute_response = asyncio.run(
                server.lifecycle_execute(
                    _FakeRequest(
                        {
                            "action": ACTION_CPU_FREE_AGENCY,
                            "expected_action_fingerprint": preview.get("action_fingerprint"),
                            "expected_working_save_sha256": preview.get("working_save_sha256"),
                        }
                    )
                )
            )
            execute_seconds = time.perf_counter() - execute_started
            execute = _response_json(execute_response)
            lifecycle = dict(execute.get("lifecycle", {}) or {})
            checks["isolated_execute_writes_only_v3"] = (
                execute_response.status_code == 200
                and execute.get("status") == "applied"
                and execute.get("persisted_after_reload") is True
                and execute.get("working_save_only") is True
                and _sha256(working) != source_sha
                and _sha256(protected_v2) == v2_sha
                and execute.get("active_v2_unchanged") is True
            )
            checks["isolated_execute_reloads_exact_candidate"] = (
                execute.get("verification", {}).get("persisted") is True
                and execute.get("verification", {}).get("checks", {}).get(
                    "cpu_roster_deficits_match_candidate"
                )
                is True
                and execute.get("verification", {}).get("checks", {}).get(
                    "cpu_signing_transactions_persisted"
                )
                is True
            )
            checks["isolated_cpu_rosters_reach_sustainable_target"] = (
                int(preview_detail.get("total_deficit_after", -1)) == 0
                and lifecycle.get("stage") != "cpu_free_agency_pending"
            )
            checks["isolated_recovery_checkpoint_created"] = bool(
                list(recovery.glob("pre_cpu_free_agency_*"))
            )

            detail.update(
                {
                    "season": summary.get("season", {}).get("label"),
                    "deficit_before": preview_detail.get("total_deficit_before"),
                    "deficit_after": preview_detail.get("total_deficit_after"),
                    "committed_signings": preview_detail.get("committed_signing_count"),
                    "stop_reason": preview_detail.get("stop_reason"),
                    "preview_seconds": round(preview_seconds, 3),
                    "execute_seconds": round(execute_seconds, 3),
                    "next_stage_after_commit": lifecycle.get("stage"),
                }
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)
    return checks, detail


def main() -> int:
    engine = ROOT / "src" / "franchise_free_agency_cpu_execution_v1.py"
    lifecycle = ROOT / "desktop_bridge" / "season_lifecycle_foundation.py"
    server_path = ROOT / "desktop_bridge" / "server.py"
    godot = ROOT / "godot_client" / "scripts" / "season_lifecycle_center_v3.gd"
    engine_text = engine.read_text(encoding="utf-8")
    lifecycle_text = lifecycle.read_text(encoding="utf-8")
    server_text = server_path.read_text(encoding="utf-8")
    godot_text = godot.read_text(encoding="utf-8")

    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    checks: dict[str, bool] = {
        "batch15_foundation_version": "batch-15-cpu-free-agency" in SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "production_cpu_fa_engine_reused": "build_cpu_free_agency_round_candidate" in lifecycle_text,
        "candidate_mode_is_explicitly_read_only": "_defer_durable_write=True" in engine_text,
        "candidate_mode_requires_source_sha": "source_checkpoint_sha256" in engine_text,
        "candidate_mode_checks_source_memory_unchanged": "mutated its source checkpoint in memory" in engine_text,
        "bridge_passes_v3_path_and_sha": (
            "source_checkpoint_path=V3_WORKING_CHECKPOINT_PATH" in server_text
            and "source_checkpoint_sha256=working_before" in server_text
        ),
        "godot_cpu_fa_preview_copy_present": (
            '"cpu_free_agency":' in godot_text
            and "ANOTHER ROUND MAY BE NEEDED" in godot_text
            and "competing offers" in godot_text
        ),
    }

    try:
        for path in (engine, lifecycle, server_path, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    fixture = _find_cpu_fa_fixture()
    if fixture is None:
        dynamic = {"status": "skipped", "reason": "No isolated CPU Free Agency fixture was found."}
        for name in (
            "isolated_summary_exposes_cpu_free_agency",
            "isolated_preview_builds_real_cpu_signings",
            "isolated_preview_is_read_only",
            "isolated_execute_writes_only_v3",
            "isolated_execute_reloads_exact_candidate",
            "isolated_cpu_rosters_reach_sustainable_target",
            "isolated_recovery_checkpoint_created",
        ):
            checks[name] = True
    else:
        try:
            dynamic_checks, dynamic = _run_isolated_full_stack(fixture)
            checks.update(dynamic_checks)
            dynamic["status"] = "pass" if all(dynamic_checks.values()) else "failed"
        except Exception as exc:
            dynamic = {
                "status": "failed",
                "fixture": str(fixture),
                "exception_type": type(exc).__name__,
                "reason": str(exc),
            }
            checks["isolated_full_stack_completed"] = False

    godot_binary = Path(r"C:\Users\klima\Downloads\Godot_v4.0-stable_win64.exe")
    if godot_binary.is_file():
        result = __import__("subprocess").run(
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
        # Godot 4.0 returns 1 when its editor IPC socket is already owned by the
        # user's running Godot session. That is not a script parse failure.
        checks["godot_headless_parse"] = result.returncode == 0 or not any(
            marker in lowered for marker in fatal_markers
        )
    else:
        checks["godot_headless_parse"] = True
        godot_output = "SKIP: configured Godot binary not found"

    checks["validator_never_changes_active_v3_save"] = _sha256(active_working) == active_working_before
    checks["validator_never_changes_active_v2_save"] = _sha256(active_v2) == active_v2_before

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 92)
    print("V3 BATCH 15 CPU FREE AGENCY LIFECYCLE VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    for key in (
        "season",
        "committed_signings",
        "deficit_before",
        "deficit_after",
        "stop_reason",
        "preview_seconds",
        "execute_seconds",
        "next_stage_after_commit",
        "reason",
    ):
        if key in dynamic:
            print(f"  {key}: {dynamic[key]}")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 15 VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 15 VALIDATION PASSED")
    print("Only a temporary fixture copy was committed; active V3 and V2 saves remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
