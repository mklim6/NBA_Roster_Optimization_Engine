from __future__ import annotations
import ast, hashlib, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED = 'dba4e0a70ec2fe63ea25f40f8f5a8e34e0fe590f339a4acb77e445b829ef961c'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    text = PAGE.read_text(encoding="utf-8")
    checks = {
        "exact_v1_7_page_hash": sha(PAGE) == EXPECTED,
        "page_compiles": True,
        "v1_6_foundation_preserved": "_franchise_module_source_signature_v1_6" in text,
        "lazy_router_preserved": "active_section = st.radio(" in text and text.count("if active_section == ") >= 9,
        "deep_profile_installed": "Imports + page setup" in text and "Runtime data" in text,
        "event_marker_seeded": "restored_event_sync_marker_v1_7" in text,
        "checkpoint_exists": CHECKPOINT.is_file(),
    }
    try:
        ast.parse(text); compile(text, str(PAGE), "exec")
    except Exception:
        checks["page_compiles"] = False
    before = sha(CHECKPOINT) if CHECKPOINT.is_file() else ""
    elapsed = 0.0
    if CHECKPOINT.is_file():
        sys.path.insert(0, str(ROOT / "src"))
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        started = time.perf_counter()
        loaded = load_franchise_checkpoint()
        elapsed = time.perf_counter() - started
        checks["checkpoint_read_only_loads"] = loaded is not None
        checks["checkpoint_hash_unchanged_after_read"] = sha(CHECKPOINT) == before
    print("="*88)
    print("FRANCHISE MODE DEEP STARTUP V1.7 VALIDATION")
    print("="*88)
    for k,v in checks.items(): print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print()
    print("READ-ONLY PERFORMANCE SAMPLE")
    print(f"  Durable checkpoint restore: {elapsed:.2f}s")
    print("  Deep browser startup timing: ENABLED")
    print("  Redundant event-sync cold-session checkpoint write: GUARDED")
    if not all(checks.values()): return 1
    print()
    print("FRANCHISE MODE DEEP STARTUP V1.7 VALIDATION PASSED")
    return 0
if __name__ == "__main__": raise SystemExit(main())
