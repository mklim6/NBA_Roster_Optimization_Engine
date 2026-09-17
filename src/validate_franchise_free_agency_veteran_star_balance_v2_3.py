from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys
import types

def _install_stubs():
    # Market module has only stdlib imports in the current implementation, but
    # keep this helper for clean-room forward compatibility.
    return None

def _load(path: Path, name: str):
    _install_stubs()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def _player(age: float, overall: float, availability_rating: float):
    return SimpleNamespace(
        player_id=f"P-{age}-{overall}-{availability_rating}",
        age=age,
        overall_rating=overall,
        potential_rating=overall,
        availability_rating=availability_rating,
    )

def main() -> int:
    project = Path.cwd()
    market_path = project / "src" / "franchise_free_agency_market_value_v2.py"
    audit_path = project / "src" / "audit_franchise_free_agency_market_value_v2.py"

    checks = {
        "market_exists": market_path.exists(),
        "audit_exists": audit_path.exists(),
    }
    market_text = market_path.read_text(encoding="utf-8") if market_path.exists() else ""
    audit_text = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""

    try:
        ast.parse(market_text)
        checks["market_compiles"] = True
    except Exception:
        checks["market_compiles"] = False
    try:
        ast.parse(audit_text)
        checks["audit_compiles"] = True
    except Exception:
        checks["audit_compiles"] = False

    checks["version_is_v2_3"] = "v2.3-veteran-star-balance-2026-09-12" in market_text
    checks["age_curve_preserved"] = all(
        marker in market_text
        for marker in (
            "elif age <= 35:",
            "base = 0.920",
            "elif age <= 36:",
            "base = 0.880",
            "elif age <= 38:",
            "base = 0.800",
        )
    )
    checks["history_factor_is_severity_based"] = 'tier = "history"\n            factor = 0.70' in market_text
    checks["moderate_factor_is_severity_based"] = 'tier = "moderate"\n            factor = 0.62' in market_text
    checks["severe_factor_is_severity_based"] = 'tier = "severe"\n            factor = 0.54' in market_text
    checks["v2_2_age_indexed_medical_table_removed"] = "35: 0.52" not in market_text and "36: 0.44" not in market_text
    checks["combined_factor_is_audited"] = "combined_age_medical_factor" in audit_text
    checks["v2_3_audit_filename"] = "market_value_calibration_v2_3_audit.csv" in audit_text
    checks["legal_salary_clipping_preserved"] = (
        "final = max(final, minimum)" in market_text
        and "final = min(final, maximum)" in market_text
    )
    checks["young_high_risk_curve_preserved"] = (
        'tier = "younger_high_risk"' in market_text
        and "factor = 0.94" in market_text
    )

    # Architecture-level combined discounts.
    age35_history = 0.920 * 0.70
    age36_severe = 0.880 * 0.54
    age38_history = 0.800 * 0.70
    checks["age35_history_still_heavily_discounted"] = 0.62 <= age35_history <= 0.66
    checks["age36_severe_still_heavily_discounted"] = 0.46 <= age36_severe <= 0.49
    checks["age38_history_not_double_counted"] = 0.54 <= age38_history <= 0.58

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FREE AGENCY VETERAN STAR BALANCE V2.3 VALIDATOR FAILED")
        return 1

    print("FRANCHISE FREE AGENCY VETERAN STAR BALANCE V2.3 VALIDATOR PASSED")
    print(f"Age-35 history combined factor: x{age35_history:.3f}")
    print(f"Age-36 severe combined factor: x{age36_severe:.3f}")
    print(f"Age-38 history combined factor: x{age38_history:.3f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
