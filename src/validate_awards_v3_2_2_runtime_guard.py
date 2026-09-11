from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
AWARDS = ROOT / "src" / "simulation_career_awards_v2.py"

EXPECTED = "simulation-career-awards-v3.2-2026-08-11"

page_text = PAGE.read_text(encoding="utf-8")
awards_text = AWARDS.read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location(
    "_awards_v322_runtime_guard_validator",
    AWARDS,
)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load Awards module from exact src path.")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

checks = {
    "src_backend_is_v32": (
        getattr(module, "CAREER_AWARDS_VERSION", "") == EXPECTED
    ),
    "page_guard_expects_v32": (
        EXPECTED in page_text
    ),
    "stale_v31_guard_removed": (
        "simulation-career-awards-v3.1-2026-08-11" not in page_text
    ),
    "exact_src_runtime_wiring_retained": (
        "_awards_v3_runtime_path" in page_text
        and "_awards_v3_runtime_spec" in page_text
        and "_awards_v3_runtime" in page_text
    ),
}

failed = [
    name
    for name, passed in checks.items()
    if not passed
]

print("AWARDS V3.2.2 RUNTIME GUARD CHECKS")
for name, passed in checks.items():
    print(f"  {name}: {'PASS' if passed else 'FAIL'}")

print()
print("Loaded Awards version:", getattr(module, "CAREER_AWARDS_VERSION", "unknown"))
print("Loaded Awards path:", Path(module.__file__).resolve())

if failed:
    raise AssertionError(
        "Awards V3.2.2 runtime guard validation failed: "
        + ", ".join(failed)
    )

print()
print("AWARDS V3.2.2 RUNTIME GUARD VALIDATION PASSED")
