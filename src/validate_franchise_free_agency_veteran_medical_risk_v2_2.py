from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import ast, importlib.util, sys


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _player(age, ovr=95.0, availability=85.0):
    return SimpleNamespace(
        player_id=f"P-{age}-{availability}",
        age=float(age),
        overall_rating=float(ovr),
        potential_rating=float(ovr),
        skill_ratings={"availability_rating": float(availability)},
    )


def main() -> int:
    project = Path.cwd()
    path = project / "src" / "franchise_free_agency_market_value_v2.py"
    audit = project / "src" / "audit_franchise_free_agency_market_value_v2.py"
    checks = {"market_exists": path.exists(), "audit_exists": audit.exists()}
    try:
        ast.parse(path.read_text(encoding="utf-8")); checks["market_compiles"] = True
    except Exception: checks["market_compiles"] = False
    try:
        ast.parse(audit.read_text(encoding="utf-8")); checks["audit_compiles"] = True
    except Exception: checks["audit_compiles"] = False

    mod = _load(path, "_fa_v22_fixture")
    checks["version_is_v2_2_or_later"] = any(
        marker in mod.FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION
        for marker in (
            "v2.2-veteran-medical-risk",
            "v2.3-veteran-star-balance",
        )
    )

    # Patch health/multi-season helpers to isolate the age+profile-history curve.
    mod._health_profile = lambda state, pid: None
    mod._season_availability_samples = lambda state, pid, limit=4: []

    p35 = _player(35, availability=85.5)
    m35 = mod.medical_risk_adjustment_v2_1(SimpleNamespace(), p35)
    checks["age35_profile_history_is_meaningful_history"] = m35["tier"] in {"history","moderate","severe"}
    # V2.3 intentionally removed age-indexed medical double counting. Age is
    # still discounted by the separate age curve, while a history-tier medical
    # profile retains a material severity-based multiplier of at most 0.70.
    checks["age35_history_factor_remains_material"] = float(m35["factor"]) <= 0.70

    p38 = _player(38, availability=79.6)
    m38 = mod.medical_risk_adjustment_v2_1(SimpleNamespace(), p38)
    checks["age38_history_plus_age_remains_strong"] = (
        float(m38["factor"]) * float(mod.age_risk_factor_v2(p38)) <= 0.56 + 1e-9
    )

    p32 = _player(32, availability=70.0)
    m32 = mod.medical_risk_adjustment_v2_1(SimpleNamespace(), p32)
    checks["under34_not_given_veteran_cliff"] = float(m32["factor"]) >= 0.94

    text = path.read_text(encoding="utf-8")
    checks["legal_clipping_preserved"] = "maximum_legal_salary" in text and "minimum_salary_floor" in text
    checks["ovr_curve_preserved"] = "_BASE_ANCHORS" in text and "base_rating_reference_v1" in text

    failed = [k for k,v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FREE AGENCY VETERAN MEDICAL RISK V2.2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE FREE AGENCY VETERAN MEDICAL RISK V2.2 VALIDATOR PASSED")
    print(f"Age-35 history fixture medical factor: x{m35['factor']:.2f}")
    print(f"Age-38 history fixture medical factor: x{m38['factor']:.2f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
