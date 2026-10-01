from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = SRC / "franchise_cpu_post_draft_roster_trim_live_v1.py"
CHECKPOINT = SRC / "simulation_franchise_checkpoint_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_PATCHED_SHA256 = "0b3f4852bade2e7d66778c0bb0b972bfc9a45d2d24c7c7dcbc061b63bfa96aa2"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha256(ACTIVE) if ACTIVE.is_file() else ""

    source = TARGET.read_text(encoding="utf-8")
    checkpoint_source = CHECKPOINT.read_text(encoding="utf-8")
    ast.parse(source, filename=str(TARGET))

    commit_section = source.split("def commit_atomic_cpu_post_draft_trim_live(", 1)[1]

    checks = {
        "exact_patched_trim_source": sha256(TARGET) == EXPECTED_PATCHED_SHA256,
        "copy_payload_false_preserved": "copy_payload=False" in commit_section,
        "existing_checkpoint_reused": "_existing_checkpoint=checkpoint" in commit_section,
        "source_sha_reused": "_expected_existing_sha256=source_hash" in commit_section,
        "verified_checkpoint_returned": "_return_verified=True" in commit_section,
        "redundant_post_save_reload_removed": (
            "reloaded = cp.load_franchise_checkpoint(path=path, allow_backup=False)"
            not in commit_section.split("except Exception as exc:", 1)[0]
        ),
        "target_boundary_fingerprint_still_checked": (
            "observed_target = durable.checkpoint_boundary_fingerprint(reloaded)"
            in commit_section
        ),
        "rollback_semantic_verification_preserved": (
            "durable.checkpoint_boundary_fingerprint(restored) != source_fingerprint"
            in commit_section
        ),
        "rollback_byte_verification_preserved": "_sha256(path) != source_hash" in commit_section,
        "writer_supports_return_verified": "_return_verified: bool = False" in checkpoint_source,
        "writer_supports_existing_checkpoint": "_existing_checkpoint:" in checkpoint_source,
        "writer_supports_expected_sha": "_expected_existing_sha256: str = \"\"" in checkpoint_source,
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 POST-DRAFT TRIM CHECKPOINT REUSE V1 VALIDATION")
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
