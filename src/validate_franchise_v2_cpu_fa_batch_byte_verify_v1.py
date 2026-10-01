from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = SRC / "franchise_free_agency_cpu_execution_v1.py"
CHECKPOINT = SRC / "simulation_franchise_checkpoint_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_SHA256 = "6a9162dc06acf2f512c95ec7161f4cad4b2a7aac2409b5f9b1d38068a8631878"


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

    round_section = source.split("def execute_cpu_free_agency_round_durably(", 1)[1]

    checks = {
        "exact_patched_source": sha256(TARGET) == EXPECTED_SHA256,
        "batch_size_5_preserved": "CPU_FREE_AGENCY_DURABLE_BATCH_SIZE = 5" in source,
        "intermediate_byte_verify_enabled": "_verify_encoded_bytes_only=True" in round_section,
        "writer_sha_sink_used": "_verified_file_sha256_sink=verified_file_sha256_sink" in round_section,
        "writer_sha_reused": "verified_file_sha256_sink[-1]" in round_section,
        "batch_expected_fingerprint_preserved": "expected_sim = free_agency_durable_state_fingerprint(" in round_section,
        "batch_trade_fingerprint_preserved": "expected_trade = trade_state_fingerprint(checkpoint.trade_state)" in round_section,
        "final_semantic_reload_preserved": "semantic = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)" in round_section,
        "final_semantic_sim_check_preserved": "observed_sim = free_agency_durable_state_fingerprint(" in round_section,
        "final_semantic_trade_check_preserved": "observed_trade = trade_state_fingerprint(semantic.trade_state)" in round_section,
        "stale_sha_guard_preserved": "_expected_existing_sha256=durable_hash" in round_section,
        "recovery_copy_preserved": "pre_cpu_round_batch_" in round_section,
        "writer_supports_byte_verify": "_verify_encoded_bytes_only: bool = False" in checkpoint_source,
        "writer_verifies_encoded_hash": "hashlib.sha256(observed_encoded).digest()" in checkpoint_source,
        "writer_can_return_raw_file_sha": "_verified_file_sha256_sink" in checkpoint_source,
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 CPU FA BATCH BYTE VERIFY V1 VALIDATION")
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
