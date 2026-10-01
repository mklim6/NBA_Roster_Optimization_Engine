from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = SRC / "franchise_draft_engine_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED_SHA256 = "cb3e8db42511fbff17b73fe6fa034bad71085ad1f740917a22e44e870d7724e6"


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
        "exact_patched_source": sha256(TARGET) == EXPECTED_SHA256,
        "cache_version_present": "team-prospect-local-cache-v1-2026-09-29" in source,
        "score_accepts_cache": "_scouting_estimate_cache:" in source,
        "team_prospect_key": "clean_text(prospect.get(\"prospect_id\"))" in source,
        "successful_estimate_cached": "_scouting_estimate_cache[cache_key]" in source,
        "fallback_not_cached": "transient failure is deliberately not cached" in source,
        "team_need_recomputed_before_cache": (
            source.index("need = _team_need_score(state, team, position)")
            < source.index("cache_key = (")
        ),
        "choose_threads_cache": "_scouting_estimate_cache=_scouting_estimate_cache" in source,
        "simulate_rest_local_cache": (
            "def simulate_rest_of_draft" in source
            and "scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] = {}" in source
        ),
        "cache_not_persisted_to_draft_state": "_ai_scouting_estimate_cache" not in source,
        "single_pick_default_unchanged": (
            "def make_ai_selection(" in source
            and "_scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] | None = None" in source
        ),
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 DRAFT SCOUTING ESTIMATE CACHE V1 STATIC VALIDATION")
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
