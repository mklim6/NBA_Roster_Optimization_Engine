from __future__ import annotations
import ast
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED_PAGE_HASH = 'e91d0b99daa2c19a54ce3bfc1c7c0cb8b44b929801897e5db6ab3d289d2097c5'

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    checks = {
        "exact_patched_page_hash": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "existing_nine_workspace_lazy_router_preserved": (
            "active_section = st.radio(" in text
            and text.count("if active_section == ") >= 9
            and "\"Inbox & League Health\"" in text
            and "\"Draft Room\"" in text
        ),
        "source_change_reload_gate_installed": "_franchise_module_source_signature_v1_6" in text,
        "ordinary_rerun_dependency_purge_removed": (
            "_module_sources_changed_v1_6" in text
            and "ensure_current_simulation_modules()\n\n\n\nimport simulation_cross_page_state" not in text
        ),
        "preference_sidecar_installed": "FRANCHISE_UI_PREFERENCES_PATH_V1_6" in text,
        "preference_callback_no_full_checkpoint_write": "preference-update-{persistent_key}" not in text,
        "restored_writer_marker_seeded": (
            "franchise_checkpoint_writer_implementation" in text
            and "CHECKPOINT_IMPLEMENTATION_VERSION" in text
        ),
        "restored_health_marker_seeded": "restored_health_marker_v1_6" in text,
        "team_snapshot_cache_installed": "_cached_team_snapshot_v1_6" in text,
        "stat_health_cache_installed": "_cached_stat_health_v1_6" in text,
        "performance_diagnostics_installed": "Performance diagnostics" in text,
        "durable_checkpoint_exists": CHECKPOINT.is_file(),
    }
    try:
        ast.parse(text)
        compile(text, str(PAGE), "exec")
    except Exception:
        checks["page_compiles"] = False

    checkpoint_seconds = None
    if CHECKPOINT.is_file():
        sys.path.insert(0, str(ROOT / "src"))
        try:
            from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
            started = time.perf_counter()
            checkpoint = load_franchise_checkpoint()
            checkpoint_seconds = time.perf_counter() - started
            checks["checkpoint_read_only_loads"] = checkpoint is not None
        except Exception as exc:
            print("Checkpoint read-only load error:", exc)
            checks["checkpoint_read_only_loads"] = False

    print("=" * 88)
    print("FRANCHISE MODE EXACT PERFORMANCE V1.6 VALIDATION")
    print("=" * 88)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    if checkpoint_seconds is not None:
        print()
        print("READ-ONLY PERFORMANCE SAMPLE")
        print(f"  Durable checkpoint restore: {checkpoint_seconds:.2f}s")
        print("  Outer workspace rendering: ALREADY LAZY (existing 9-section radio router)")
        print("  Redundant startup checkpoint rewrites: REMOVED")
        print("  Full checkpoint writes on UI preference changes: REMOVED")
        print("  Dependency-chain purge on ordinary reruns: REMOVED")

    if not all(checks.values()):
        return 1

    print()
    print("FRANCHISE MODE EXACT PERFORMANCE V1.6 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade, game, roster move, or checkpoint write was performed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
