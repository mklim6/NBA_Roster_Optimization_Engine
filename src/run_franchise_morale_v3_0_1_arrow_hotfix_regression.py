from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "franchise_roster_rotation_headquarters_v1.py"


def _num(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def main() -> int:
    recent_values = [
        _num(None, float("nan")),
        _num(18.0, float("nan")),
        _num(24.5, float("nan")),
        _num(None, float("nan")),
    ]
    frame = pd.DataFrame({"Recent MIN": recent_values})
    arrow_checked = False
    arrow_ok = True
    arrow_error = ""
    try:
        import pyarrow as pa
        pa.Table.from_pandas(frame, preserve_index=False)
        arrow_checked = True
    except ImportError:
        arrow_checked = False
    except Exception as exc:
        arrow_checked = True
        arrow_ok = False
        arrow_error = f"{type(exc).__name__}: {exc}"

    text = TARGET.read_text(encoding="utf-8")
    checks = {
        "recent_min_dtype_is_numeric": pd.api.types.is_float_dtype(frame["Recent MIN"].dtype),
        "missing_recent_min_is_nan": math.isnan(float(frame.loc[0, "Recent MIN"])),
        "numeric_recent_min_preserved": float(frame.loc[2, "Recent MIN"]) == 24.5,
        "source_uses_same_numeric_expression": '"Recent MIN": _num(row.get("recent_minutes"), float("nan"))' in text,
        "pyarrow_serialization_passes_when_available": arrow_ok,
    }
    failed = [name for name, value in checks.items() if not value]
    report = {
        "checks": checks,
        "pyarrow_checked": arrow_checked,
        "pyarrow_error": arrow_error,
        "dtype": str(frame["Recent MIN"].dtype),
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise RuntimeError("FRANCHISE MORALE V3.0.1 ARROW HOTFIX REGRESSION FAILED")
    print("FRANCHISE MORALE V3.0.1 ARROW HOTFIX REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
