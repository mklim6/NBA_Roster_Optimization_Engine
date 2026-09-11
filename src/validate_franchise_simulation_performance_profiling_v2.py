from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path

VERSION = "franchise-simulation-performance-profiling-validator-v2-2026-08-13"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GAME = SRC / "single_game_simulator_v1.py"
FINGERPRINT = SRC / "simulation_player_stat_fingerprints_v3.py"
PROFILER = SRC / "profile_franchise_simulation_performance_v2.py"
BATCH = SRC / "run_franchise_batch_simulation_audit_v2.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
CHECKPOINT_MODULE = SRC / "simulation_franchise_checkpoint_v1.py"


def main() -> int:
    checks: dict[str, bool] = {}
    checks["validator_version_is_current"] = VERSION.endswith("2026-08-13")
    checks["profiler_installed"] = PROFILER.is_file()
    checks["batch_audit_exists"] = BATCH.is_file()
    checks["checkpoint_exists"] = CHECKPOINT.is_file()
    checks["checkpoint_module_exists"] = CHECKPOINT_MODULE.is_file()
    checks["fingerprint_v3_exists"] = FINGERPRINT.is_file()

    try:
        sys.path.insert(0, str(SRC))
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        loaded = load_franchise_checkpoint()
        checks["zero_argument_checkpoint_loader_returns_state"] = bool(
            loaded is not None and getattr(loaded, "simulation_state", None) is not None
        )
    except Exception:
        checks["zero_argument_checkpoint_loader_returns_state"] = False

    game_text = GAME.read_text(encoding="utf-8") if GAME.is_file() else ""
    fp_text = FINGERPRINT.read_text(encoding="utf-8") if FINGERPRINT.is_file() else ""
    checks["performance_v2_is_live"] = (
        '_FRANCHISE_SIMULATION_PERFORMANCE_OPTIMIZATION_V2 = True' in game_text
        and 'FRANCHISE_SIMULATION_PERFORMANCE_VERSION_V2 = "franchise-simulation-performance-optimization-v2-2026-08-13"' in game_text
    )
    checks["shooting_identity_v1_0_3_is_live"] = '_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3 = True' in game_text
    checks["fingerprint_runtime_cache_v1_is_live"] = (
        '_PLAYER_FINGERPRINT_RUNTIME_CACHE_V1 = True' in fp_text
        and 'PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION = "player-fingerprint-runtime-cache-v1-2026-08-13"' in fp_text
    )
    try:
        py_compile.compile(str(PROFILER), doraise=True)
        checks["profiler_compiles"] = True
    except Exception:
        checks["profiler_compiles"] = False

    failed = [k for k, v in checks.items() if not v]
    print(json.dumps({"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit("Franchise simulation performance profiling V2 validator failed: " + ", ".join(failed))
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V2 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
