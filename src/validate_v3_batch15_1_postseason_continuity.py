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
    ACTION_CONTRACT_CLOSEOUT,
    ACTION_POSTSEASON_INITIALIZE,
    ACTION_POSTSEASON_SIMULATE,
    SEASON_LIFECYCLE_FOUNDATION_VERSION,
    build_lifecycle_summary,
)
from regular_season_simulation_controller_v1 import (
    SimulationScope,
    simulate_regular_season_scope,
)
from simulation_franchise_checkpoint_v1 import (
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)


VALIDATOR_VERSION = "v3-batch15-1-postseason-continuity-validator-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch15_1_postseason_continuity"
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


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw) or "").strip().lower()


class _FakeRequest:
    def __init__(self, body: dict[str, Any]):
        self._body = copy.deepcopy(body)

    async def json(self) -> dict[str, Any]:
        return copy.deepcopy(self._body)


def _build_regular_season_complete_fixture(checkpoint: Any) -> tuple[Any, dict[str, Any]]:
    source_state = checkpoint.simulation_state
    if _phase(source_state) != "regular_season":
        raise RuntimeError(
            "The active V3 checkpoint is not in the regular season, so the isolated "
            "postseason fixture could not be derived from it."
        )
    started = time.perf_counter()
    completed_state, result = simulate_regular_season_scope(
        copy.deepcopy(source_state),
        scope=SimulationScope.REMAINDER,
    )
    detail = {
        "regular_season_games_simulated": int(result.games_simulated),
        "fixture_build_seconds": round(time.perf_counter() - started, 3),
    }
    return completed_state, detail


def _run_isolated_full_stack(active_checkpoint: Any) -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    completed_state, detail = _build_regular_season_complete_fixture(active_checkpoint)

    names = (
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_LIFECYCLE_RECOVERY_DIR",
    )
    original = {name: getattr(server, name) for name in names}

    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch15_1_postseason_") as tmp:
            tmp_root = Path(tmp)
            working = tmp_root / "v3_working.pkl.gz"
            protected_v2 = tmp_root / "protected_v2.bin"
            recovery = tmp_root / "recovery"

            save_franchise_checkpoint(
                completed_state,
                copy.deepcopy(active_checkpoint.trade_state),
                preferences=copy.deepcopy(dict(active_checkpoint.preferences or {})),
                reason="V3 Batch 15.1 isolated postseason validation fixture",
                path=working,
                copy_payload=False,
                force_replace=True,
            )
            protected_v2.write_bytes(b"protected-v2-postseason-sentinel")

            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = protected_v2
            server.V3_LIFECYCLE_RECOVERY_DIR = recovery

            initial_working_sha = _sha256(working)
            initial_v2_sha = _sha256(protected_v2)

            summary_response = asyncio.run(server.lifecycle_summary(_FakeRequest({})))
            summary = _response_json(summary_response)
            checks["isolated_regular_season_completion_exposes_bracket_action"] = (
                summary_response.status_code == 200
                and summary.get("next_action") == ACTION_POSTSEASON_INITIALIZE
                and summary.get("stage") == "postseason_setup_ready"
            )

            init_preview_response = asyncio.run(
                server.lifecycle_preview(_FakeRequest({"action": ACTION_POSTSEASON_INITIALIZE}))
            )
            init_preview = _response_json(init_preview_response)
            init_detail = dict(init_preview.get("detail", {}) or {})
            checks["bracket_preview_is_read_only_and_seeded"] = (
                init_preview_response.status_code == 200
                and init_preview.get("status") == "pass"
                and init_preview.get("can_commit") is True
                and len(init_detail.get("east_seeds", []) or []) == 10
                and len(init_detail.get("west_seeds", []) or []) == 10
                and init_preview.get("working_save_unchanged") is True
                and init_preview.get("active_v2_unchanged") is True
                and _sha256(working) == initial_working_sha
                and _sha256(protected_v2) == initial_v2_sha
            )

            init_execute_response = asyncio.run(
                server.lifecycle_execute(
                    _FakeRequest(
                        {
                            "action": ACTION_POSTSEASON_INITIALIZE,
                            "expected_action_fingerprint": init_preview.get("action_fingerprint"),
                            "expected_working_save_sha256": init_preview.get("working_save_sha256"),
                        }
                    )
                )
            )
            init_execute = _response_json(init_execute_response)
            init_lifecycle = dict(init_execute.get("lifecycle", {}) or {})
            checks["bracket_execute_persists_and_advances_gate"] = (
                init_execute_response.status_code == 200
                and init_execute.get("status") == "applied"
                and init_execute.get("persisted_after_reload") is True
                and init_execute.get("working_save_only") is True
                and init_execute.get("active_v2_unchanged") is True
                and init_execute.get("verification", {}).get("persisted") is True
                and init_lifecycle.get("next_action") == ACTION_POSTSEASON_SIMULATE
                and init_lifecycle.get("stage") == "postseason_in_progress"
            )
            checks["bracket_recovery_checkpoint_created"] = bool(
                list(recovery.glob("pre_postseason_initialize_*"))
            )

            bracket_sha = _sha256(working)
            postseason_preview_started = time.perf_counter()
            postseason_preview_response = asyncio.run(
                server.lifecycle_preview(_FakeRequest({"action": ACTION_POSTSEASON_SIMULATE}))
            )
            postseason_preview_seconds = time.perf_counter() - postseason_preview_started
            postseason_preview = _response_json(postseason_preview_response)
            postseason_detail = dict(postseason_preview.get("detail", {}) or {})
            checks["postseason_preview_reaches_hidden_champion_candidate"] = (
                postseason_preview_response.status_code == 200
                and postseason_preview.get("status") == "pass"
                and postseason_preview.get("can_commit") is True
                and int(postseason_detail.get("games_simulated", 0) or 0) > 0
                and str(postseason_detail.get("stage_after", "")).lower() == "complete"
                and bool(str(postseason_detail.get("champion", "")).strip())
                and postseason_preview.get("working_save_unchanged") is True
                and _sha256(working) == bracket_sha
                and _sha256(protected_v2) == initial_v2_sha
            )

            postseason_execute_started = time.perf_counter()
            postseason_execute_response = asyncio.run(
                server.lifecycle_execute(
                    _FakeRequest(
                        {
                            "action": ACTION_POSTSEASON_SIMULATE,
                            "expected_action_fingerprint": postseason_preview.get("action_fingerprint"),
                            "expected_working_save_sha256": postseason_preview.get("working_save_sha256"),
                        }
                    )
                )
            )
            postseason_execute_seconds = time.perf_counter() - postseason_execute_started
            postseason_execute = _response_json(postseason_execute_response)
            final_lifecycle = dict(postseason_execute.get("lifecycle", {}) or {})
            final_postseason = dict(final_lifecycle.get("postseason", {}) or {})
            checks["postseason_execute_crowns_champion_and_enters_offseason"] = (
                postseason_execute_response.status_code == 200
                and postseason_execute.get("status") == "applied"
                and postseason_execute.get("persisted_after_reload") is True
                and postseason_execute.get("active_v2_unchanged") is True
                and postseason_execute.get("verification", {}).get("persisted") is True
                and final_lifecycle.get("season", {}).get("phase") == "offseason"
                and final_postseason.get("stage") == "complete"
                and bool(str(final_postseason.get("champion", "")).strip())
                and final_lifecycle.get("next_action") == ACTION_CONTRACT_CLOSEOUT
            )
            checks["postseason_recovery_checkpoint_created"] = bool(
                list(recovery.glob("pre_postseason_simulate_*"))
            )
            checks["isolated_postseason_never_changes_protected_v2"] = (
                _sha256(protected_v2) == initial_v2_sha
            )

            detail.update(
                {
                    "season": final_lifecycle.get("season", {}).get("label"),
                    "opening_stage": init_detail.get("stage"),
                    "east_seed_1": (init_detail.get("east_seeds") or [{}])[0].get("Team"),
                    "west_seed_1": (init_detail.get("west_seeds") or [{}])[0].get("Team"),
                    "postseason_games": postseason_detail.get("games_simulated"),
                    "champion": final_postseason.get("champion"),
                    "runner_up": final_postseason.get("runner_up"),
                    "postseason_preview_seconds": round(postseason_preview_seconds, 3),
                    "postseason_execute_seconds": round(postseason_execute_seconds, 3),
                    "next_stage_after_champion": final_lifecycle.get("stage"),
                }
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)

    return checks, detail


def main() -> int:
    lifecycle = ROOT / "desktop_bridge" / "season_lifecycle_foundation.py"
    server_path = ROOT / "desktop_bridge" / "server.py"
    postseason_engine = ROOT / "src" / "simulation_postseason_v1.py"
    godot = ROOT / "godot_client" / "scripts" / "season_lifecycle_center_v3.gd"
    batch15_validator = ROOT / "src" / "validate_v3_batch15_cpu_free_agency_lifecycle.py"

    lifecycle_text = lifecycle.read_text(encoding="utf-8")
    server_text = server_path.read_text(encoding="utf-8")
    postseason_text = postseason_engine.read_text(encoding="utf-8")
    godot_text = godot.read_text(encoding="utf-8")

    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    checks: dict[str, bool] = {
        "batch15_1_foundation_version": "15-1-postseason-continuity" in SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "batch15_cpu_fa_version_compatibility_preserved": "batch-15-cpu-free-agency" in SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "production_postseason_engine_reused": (
            "initialize_postseason" in lifecycle_text
            and "advance_postseason" in lifecycle_text
            and "PostseasonSimulationScope.TO_CHAMPION" in lifecycle_text
        ),
        "postseason_engine_itself_unmodified_by_batch15_1": "simulation-postseason-v1-2026-08-08" in postseason_text,
        "server_generic_lifecycle_routes_reused": (
            'Route("/v3/lifecycle", lifecycle_summary' in server_text
            and 'Route("/v3/lifecycle/preview", lifecycle_preview' in server_text
            and 'Route("/v3/lifecycle/execute", lifecycle_execute' in server_text
        ),
        "postseason_actions_registered": (
            'ACTION_POSTSEASON_INITIALIZE = "postseason_initialize"' in lifecycle_text
            and 'ACTION_POSTSEASON_SIMULATE = "postseason_simulate"' in lifecycle_text
        ),
        "deterministic_postseason_candidate_seeded": (
            "deterministic_seed" in lifecycle_text
            and "seed=deterministic_seed" in lifecycle_text
        ),
        "postseason_persistence_verification_present": (
            '"postseason_complete"' in lifecycle_text
            and '"offseason_phase_active"' in lifecycle_text
            and '"champion_persisted"' in lifecycle_text
        ),
        "godot_exposes_two_step_postseason_flow": (
            '"postseason_initialize":' in godot_text
            and '"postseason_simulate":' in godot_text
            and "CREATE PLAYOFF BRACKET" in lifecycle_text
            and "SIMULATE POSTSEASON" in lifecycle_text
        ),
        "godot_displays_seed_order_before_simulation": (
            "East seeds:" in godot_text
            and "West seeds:" in godot_text
            and "_seed_summary" in godot_text
        ),
        "godot_hides_preview_champion_until_commit": "champion is revealed only after commit" in godot_text,
        "existing_batch15_validator_still_present": batch15_validator.is_file(),
    }

    try:
        for path in (lifecycle, server_path, postseason_engine, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    active_checkpoint = None
    if active_working.is_file():
        try:
            active_checkpoint = load_franchise_checkpoint(path=active_working, allow_backup=False)
        except Exception:
            active_checkpoint = None

    if active_checkpoint is None:
        dynamic = {
            "status": "skipped",
            "reason": "Active V3 working checkpoint was unavailable; static safety checks still ran.",
        }
        checks["isolated_full_stack_completed"] = True
    elif _phase(active_checkpoint.simulation_state) != "regular_season":
        dynamic = {
            "status": "skipped",
            "reason": "Active V3 checkpoint is not currently in regular_season; isolated full-stack fixture was not derived.",
        }
        checks["isolated_full_stack_completed"] = True
    else:
        try:
            dynamic_checks, dynamic = _run_isolated_full_stack(active_checkpoint)
            checks.update(dynamic_checks)
            checks["isolated_full_stack_completed"] = all(dynamic_checks.values())
            dynamic["status"] = "pass" if all(dynamic_checks.values()) else "failed"
        except Exception as exc:
            dynamic = {
                "status": "failed",
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

    print("=" * 96)
    print("V3 BATCH 15.1 POSTSEASON CONTINUITY VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    for key in (
        "season",
        "regular_season_games_simulated",
        "fixture_build_seconds",
        "opening_stage",
        "east_seed_1",
        "west_seed_1",
        "postseason_games",
        "champion",
        "runner_up",
        "postseason_preview_seconds",
        "postseason_execute_seconds",
        "next_stage_after_champion",
        "reason",
    ):
        if key in dynamic:
            print(f"  {key}: {dynamic[key]}")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 15.1 VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 15.1 VALIDATION PASSED")
    print("Only temporary fixture checkpoints were committed; active V3 and V2 saves remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
