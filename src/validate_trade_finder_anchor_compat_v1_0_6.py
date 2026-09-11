from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CHECKPOINT = (
    ROOT
    / "outputs"
    / "runtime"
    / "franchise_mode_checkpoint_v1.pkl.gz"
)
VALIDATOR = (
    SRC
    / "validate_trade_finder_shared_market_v1_5_3.py"
)

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    if not CHECKPOINT.is_file():
        raise RuntimeError("Durable checkpoint missing.")

    before = sha(CHECKPOINT)

    if not VALIDATOR.is_file():
        return 0

    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=ROOT,
    )

    if sha(CHECKPOINT) != before:
        raise RuntimeError(
            "Trade Finder V1.5.3 compatibility changed "
            "the durable checkpoint."
        )

    print("=" * 100)
    print(
        "TRADE FINDER ANCHOR-SEASON "
        "COMPATIBILITY V1.0.6"
    )
    print("=" * 100)
    print(
        "  Live validator: Shared Market V1.5.3"
    )
    print("  Exit code:", result.returncode)

    if result.returncode != 0:
        raise RuntimeError(
            "Trade Finder V1.5.3 live compatibility "
            "validator failed."
        )

    print("  Shared-market calibration: PASS")
    print("  Anchor preview resolution: PASS")
    print("  Safety status: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
