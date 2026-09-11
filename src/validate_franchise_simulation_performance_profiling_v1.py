from __future__ import annotations
import json
import py_compile
import sys
from pathlib import Path

VERSION = "franchise-simulation-performance-profiling-validator-v1.0.1-2026-08-13"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GAME = SRC / "single_game_simulator_v1.py"
PROFILER = SRC / "profile_franchise_simulation_performance_v1.py"
BATCH = SRC / "run_franchise_batch_simulation_audit_v2.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
CHECKPOINT_MODULE = SRC / "simulation_franchise_checkpoint_v1.py"


def main() -> int:
    checks = {}
    checks["validator_version_is_current"] = VERSION.endswith("2026-08-13")
    checks["profiler_installed"] = PROFILER.is_file()
    checks["batch_audit_exists"] = BATCH.is_file()
    checks["checkpoint_exists"] = CHECKPOINT.is_file()
    checks["checkpoint_module_exists"] = CHECKPOINT_MODULE.is_file()
    try:
        sys.path.insert(0, str(SRC))
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        loaded = load_franchise_checkpoint()
        checks["zero_argument_checkpoint_loader_returns_state"] = bool(loaded is not None and getattr(loaded, "simulation_state", None) is not None)
    except Exception:
        checks["zero_argument_checkpoint_loader_returns_state"] = False
    text = GAME.read_text(encoding="utf-8") if GAME.is_file() else ""
    checks["performance_v1_is_live"] = '_SHOOTING_IDENTITY_PERFORMANCE_OPTIMIZATION_V1 = True' in text
    checks["player_identity_v1_0_3_is_live"] = '_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3 = True' in text
    try:
        py_compile.compile(str(PROFILER), doraise=True)
        checks["profiler_compiles"] = True
    except Exception:
        checks["profiler_compiles"] = False
    failed = [k for k, v in checks.items() if not v]
    print(json.dumps({"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        raise SystemExit("Franchise simulation performance profiling validator failed: " + ", ".join(failed))
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V1.0.1 VALIDATION PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
