from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_generated_player_portraits_v1 as portraits


def main() -> int:
    stock_dir = ROOT / "assets" / "generated_player_stock_portraits"
    manifest = stock_dir / "manifest.csv"

    rows = []
    if manifest.exists():
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    valid_rows = [
        row for row in rows
        if (stock_dir / str(row.get("file", ""))).is_file()
    ]
    hashes = [
        hashlib.sha256(
            (stock_dir / str(row["file"])).read_bytes()
        ).hexdigest()
        for row in valid_rows
    ]

    portraits._stock_rows.cache_clear()
    portraits._file_data_url.cache_clear()

    n = min(30, len(valid_rows))
    draft_ids = [f"DRAFT-2027-{i:03d}" for i in range(1, n + 1)]
    assigned = [
        (portraits.stock_portrait_metadata(pid) or {}).get("file", "")
        for pid in draft_ids
    ]

    checks = {
        "manifest_exists": manifest.exists(),
        "at_least_20_pexels_portraits": len(valid_rows) >= 20,
        "all_active_rows_are_pexels": bool(valid_rows) and all(
            str(row.get("provider", "")) == "Pexels" for row in valid_rows
        ),
        "all_rows_declared_non_ai": bool(valid_rows) and all(
            str(row.get("ai_generated", "")).upper() == "NO" for row in valid_rows
        ),
        "no_exact_duplicate_image_bytes": len(hashes) == len(set(hashes)),
        "goofy_mix_present": sum(
            str(row.get("style_bucket", "")) == "goofy" for row in valid_rows
        ) >= 8,
        "portrait_module_is_pexels_v3": (
            "franchise-pexels-goofy-player-portraits-v3-2026-09-12"
            in portraits.GENERATED_PORTRAIT_VERSION
        ),
        "stock_bank_detected": portraits.stock_portrait_available(),
        "sequential_draft_ids_are_unique_until_bank_exhaustion": (
            len(assigned) == len(set(assigned))
        ),
        "same_player_is_stable": (
            portraits.stock_portrait_metadata("DRAFT-2027-007")
            == portraits.stock_portrait_metadata("DRAFT-2027-007")
        ),
        "generated_player_returns_local_image": portraits.generated_player_portrait_url(
            "DRAFT-2027-007",
            team="CHI",
            player_name="Test Prospect",
        ).startswith("data:image/"),
    }

    failed = [name for name, ok in checks.items() if not ok]
    print({
        "checks": checks,
        "portrait_count": len(valid_rows),
        "goofy_count": sum(
            str(row.get("style_bucket", "")) == "goofy" for row in valid_rows
        ),
        "failed_checks": failed,
        "passed": not failed,
    })

    if failed:
        print("FRANCHISE PEXELS GOOFY PORTRAIT BANK V1 VALIDATOR FAILED")
        return 1

    print("FRANCHISE PEXELS GOOFY PORTRAIT BANK V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
