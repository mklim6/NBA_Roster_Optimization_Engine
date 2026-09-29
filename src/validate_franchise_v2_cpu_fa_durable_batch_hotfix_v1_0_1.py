from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = SRC / "franchise_free_agency_cpu_execution_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED_SHA256 = "679dd6cbc91f8ae9bbbdb6d97de715b00d00d879bef020a0bbf6c5843a34657e"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha256(ACTIVE) if ACTIVE.is_file() else ""
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source, filename=str(TARGET))

    checks = {
        "exact_hotfix_source": sha256(TARGET) == EXPECTED_SHA256,
        "hotfix_version": "franchise-free-agency-durable-batch-v1.0.1-2026-09-28" in source,
        "batch_size_5_preserved": "CPU_FREE_AGENCY_DURABLE_BATCH_SIZE = 5" in source,
        "explicit_initial_load_path": "load_franchise_checkpoint(path=checkpoint_path)" in source,
        "explicit_batch_save_path": "path=checkpoint_path," in source,
        "preflush_hash_assertion": "observed_hash_before_flush = _sha256(checkpoint_path)" in source,
        "explicit_recovery_load_path": "load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)" in source,
        "explicit_final_semantic_reload": "semantic = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)" in source,
        "stale_sha_guard_preserved": "_expected_existing_sha256=durable_hash" in source,
        "deferred_internal_commit_preserved": "_defer_durable_write=True" in source,
        "public_single_signing_path_preserved": "if _defer_durable_write:" in source and "else:" in source,
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 CPU FA DURABLE BATCH HOTFIX V1.0.1 STATIC VALIDATION")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
