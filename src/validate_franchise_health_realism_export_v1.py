from __future__ import annotations

import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"

from franchise_health_realism_export_v1 import rows_to_csv_bytes

VERSION = "franchise-health-realism-export-validator-v1-2026-08-10"


def main() -> int:
    sample = [
        {"player": "Sample", "GP": 70, "injury_events": 2},
        {"player": "Other", "GP": 82, "injury_events": 0},
    ]
    csv_payload = rows_to_csv_bytes(sample).decode("utf-8-sig")
    page_text = PAGE.read_text(encoding="utf-8")
    compile_results = {}
    for path in [SRC / "franchise_health_realism_export_v1.py", PAGE]:
        try:
            py_compile.compile(str(path), doraise=True)
            compile_results[str(path.relative_to(ROOT))] = ""
        except Exception as exc:
            compile_results[str(path.relative_to(ROOT))] = str(exc)

    checks = {
        "validator_version_is_current": VERSION.endswith("2026-08-10"),
        "csv_has_header_and_rows": (
            "player,GP,injury_events" in csv_payload
            and "Sample,70,2" in csv_payload
        ),
        "page_imports_health_realism_export": (
            "franchise_health_realism_export_v1" in page_text
        ),
        "page_has_availability_download": (
            "Download availability & injury realism CSV" in page_text
        ),
        "page_has_event_history_download": (
            "Download injury event history CSV" in page_text
        ),
        "page_explains_reference_games": (
            "reference-team game count" in page_text
        ),
        "modified_files_compile": not any(compile_results.values()),
    }
    result = {
        "script": VERSION,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "compile_results": compile_results,
        "passed": all(checks.values()),
    }
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise AssertionError(
            "Franchise Health Realism Export validation failed: "
            + ", ".join(result["failed_checks"])
        )
    print("\nFRANCHISE HEALTH REALISM EXPORT V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
