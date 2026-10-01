from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = SRC / "franchise_staff_system_v1.py"
DRAFT = SRC / "franchise_draft_engine_v1.py"
SCOUT = SRC / "franchise_scouting_discovery_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_STAFF_SHA256 = "c76edaf317cc3371868e9fdc833b57c3b917da7aefbd88f4ae8f42847fd554ab"
EXPECTED_DRAFT_SHA256 = "cb3e8db42511fbff17b73fe6fa034bad71085ad1f740917a22e44e870d7724e6"
EXPECTED_SCOUT_SHA256 = "c2ca334f97e90eaad216be52d2e14066f25b5428891b38599f325ac4882d5a1e"


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
        "exact_patched_staff_source": sha256(TARGET) == EXPECTED_STAFF_SHA256,
        "current_draft_source_unchanged": sha256(DRAFT) == EXPECTED_DRAFT_SHA256,
        "current_scouting_source_unchanged": sha256(SCOUT) == EXPECTED_SCOUT_SHA256,
        "bounded_cache": "@lru_cache(maxsize=4)" in source,
        "path_in_cache_key": "path_text: str" in source,
        "version_in_cache_key": "reference_version: str" in source,
        "mtime_in_cache_key": "mtime_ns: int" in source,
        "size_in_cache_key": "file_size: int" in source,
        "file_stat_before_cache": "_REAL_STAFF_REFERENCE_PATH.stat()" in source,
        "version_validation_preserved": "!= reference_version" in source,
        "teams_dict_validation_preserved": "return teams if isinstance(teams, dict) else {}" in source,
        "missing_file_fallback_preserved": "except (OSError, json.JSONDecodeError):" in source,
        "real_head_coach_overlay_unchanged": "_apply_real_head_coach_identity" in source,
        "staff_effect_math_unchanged": "def team_staff_effects(" in source,
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 STAFF REFERENCE CACHE V1 STATIC VALIDATION")
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
