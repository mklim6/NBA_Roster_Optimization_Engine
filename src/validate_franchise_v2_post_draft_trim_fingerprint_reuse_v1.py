from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
LIVE = SRC / "franchise_cpu_post_draft_roster_trim_live_v1.py"
RELEASE = SRC / "franchise_cpu_post_draft_roster_trim_release_v1.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_LIVE_SHA256 = "0b3f4852bade2e7d66778c0bb0b972bfc9a45d2d24c7c7dcbc061b63bfa96aa2"
EXPECTED_RELEASE_SHA256 = "1caac8cfeac14d42bc25e5f3f9c032e0df48b80f9a287c768a1c13181abb4a49"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha256(ACTIVE) if ACTIVE.is_file() else ""
    live = LIVE.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    ast.parse(live, filename=str(LIVE))
    ast.parse(release, filename=str(RELEASE))

    checks = {
        "exact_live_source": sha256(LIVE) == EXPECTED_LIVE_SHA256,
        "exact_release_source": sha256(RELEASE) == EXPECTED_RELEASE_SHA256,
        "preview_accepts_precomputed_fingerprints": (
            "_precomputed_source_fingerprints: tuple[str, str] | None = None"
            in release.split("def build_cpu_post_draft_release_preview(", 1)[1]
        ),
        "candidate_accepts_precomputed_fingerprints": (
            "_precomputed_source_fingerprints: tuple[str, str] | None = None"
            in release.split("def build_cpu_post_draft_release_candidate(", 1)[1]
        ),
        "candidate_default_recomputes_for_public_callers": (
            "if _precomputed_source_fingerprints is None:" in
            release.split("def build_cpu_post_draft_release_candidate(", 1)[1]
        ),
        "candidate_stale_simulation_check_preserved": (
            "Release preview is stale relative to SimulationState." in release
        ),
        "candidate_stale_trade_check_preserved": (
            "Release preview is stale relative to TradeState." in release
        ),
        "candidate_exact_preview_rebuild_preserved": (
            "Release preview no longer reproduces exactly at candidate-build time."
            in release
        ),
        "atomic_loop_computes_one_pair": (
            "source_release_fingerprints = (" in live
            and "release._simulation_fingerprint(working.simulation_state)" in live
            and "release._trade_fingerprint(working.trade_state)" in live
        ),
        "atomic_preview_reuses_pair": (
            "_precomputed_source_fingerprints=source_release_fingerprints"
            in live
        ),
        "candidate_fingerprints_still_deferred": (
            "_defer_candidate_fingerprints=True" in live
        ),
        "checkpoint_reuse_patch_preserved": (
            "_existing_checkpoint=checkpoint" in live
            and "_expected_existing_sha256=source_hash" in live
            and "_return_verified=True" in live
        ),
    }

    active_after = sha256(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 POST-DRAFT TRIM FINGERPRINT REUSE V1 VALIDATION")
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
