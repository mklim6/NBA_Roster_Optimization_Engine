from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import run_franchise_protected_multi_season_soak_v1 as soak
import run_franchise_protected_launch_smoke_v1 as launch


VERSION = "franchise-v2-protected-multi-season-soak-v1-2026-09-24"
EXPECTED_BRANCH = "feature/franchise-v2"
EXPECTED_V1_BASELINE = "f6e9a49"
EXPECTED_V2_FOUNDATION = "3c9a0dc"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _git_commit_exists(ref: str) -> bool:
    result = _git("cat-file", "-e", f"{ref}^{{commit}}", check=False)
    return result.returncode == 0


def _git_is_ancestor(ancestor: str, descendant: str = "HEAD") -> bool:
    result = _git(
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    return result.returncode == 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _v2_provenance_preflight() -> dict[str, Any]:
    manifest_path = Path(launch.FREEZE_MANIFEST)
    if not manifest_path.is_file():
        raise RuntimeError(
            "V2 provenance preflight cannot find the protected V1 freeze manifest."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    branch = _git("branch", "--show-current").stdout.strip()
    head = _git("rev-parse", "HEAD").stdout.strip()
    v1_commit = _git("rev-parse", "v1.0.0^{commit}").stdout.strip()

    foundation_exists = _git_commit_exists(EXPECTED_V2_FOUNDATION)
    checks = {
        "legacy_freeze_manifest_present": True,
        "legacy_freeze_is_immutable": manifest.get("immutable") is True,
        "legacy_release_id_matches": (
            manifest.get("release_id") == launch.EXPECTED_RELEASE_ID
        ),
        "legacy_cutoff_is_sep7": (
            manifest.get("cutoff_date") == launch.EXPECTED_CUTOFF
        ),
        "v2_branch_selected": branch == EXPECTED_BRANCH,
        "v1_tag_matches_protected_baseline": v1_commit.startswith(
            EXPECTED_V1_BASELINE
        ),
        "head_descends_from_v1_baseline": _git_is_ancestor("v1.0.0", "HEAD"),
        "v2_foundation_commit_exists": foundation_exists,
        "head_descends_from_v2_foundation": (
            _git_is_ancestor(EXPECTED_V2_FOUNDATION, "HEAD")
            if foundation_exists
            else False
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "V2 provenance preflight failed: " + ", ".join(failed)
        )

    frozen_rows: list[dict[str, Any]] = []
    for row in manifest.get("frozen_files", []):
        rel = _clean(row.get("path"))
        expected = _clean(row.get("sha256"))
        path = ROOT / rel
        actual = _sha256(path) if path.is_file() else None
        frozen_rows.append(
            {
                "path": rel,
                "v1_expected_sha256": expected,
                "current_v2_sha256": actual,
                "still_matches_v1": bool(
                    expected and actual and expected == actual
                ),
            }
        )

    changed = [row for row in frozen_rows if not row["still_matches_v1"]]
    return {
        "mode": "v2_provenance_preflight",
        "version": VERSION,
        "checks": checks,
        "branch": branch,
        "head": head,
        "protected_v1_tag_commit": v1_commit,
        "v2_foundation": EXPECTED_V2_FOUNDATION,
        "legacy_frozen_files_changed_in_v2": len(changed),
        "legacy_frozen_changed_paths": [row["path"] for row in changed],
        "note": (
            "V2 is allowed to differ from the immutable V1 frozen source tree. "
            "The protected soak's isolated-checkpoint and active-save-family "
            "safety checks remain unchanged and mandatory."
        ),
        "expected_live_start": dict(
            manifest.get("expected_live_start", {}) or {}
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing protected multi-season soak on the V2 branch "
            "using provenance validation instead of requiring current V2 "
            "source files to equal the immutable V1 freeze hashes."
        )
    )
    parser.add_argument("--seasons", type=int, default=8)
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    if args.seasons < 1 or args.seasons > soak.MAX_SEASONS:
        raise SystemExit(
            f"--seasons must be between 1 and {soak.MAX_SEASONS}."
        )

    print("FRANCHISE V2 PROTECTED MULTI-SEASON SOAK V1")
    print(f"Project root: {ROOT}")
    print("Active franchise mutation: FORBIDDEN")
    print(f"Requested complete seasons: {args.seasons}")
    print("V1 source-hash freeze: replaced by V2 lineage/provenance preflight")
    print("Checkpoint isolation/safety: unchanged")
    print()

    original = soak._validate_release_freeze
    started = time.perf_counter()
    try:
        soak._validate_release_freeze = _v2_provenance_preflight
        report = soak.run_soak(
            seasons=args.seasons,
            keep_artifacts=args.keep_artifacts,
        )
    finally:
        soak._validate_release_freeze = original

    elapsed = round(time.perf_counter() - started, 3)

    print()
    print("V2 SOAK SUMMARY")
    for season in report.get("season_reports", []):
        print(
            f"  Season {season.get('season_index')}: "
            f"{season.get('source_season')} -> "
            f"{season.get('target_season', '?')} · "
            f"champion={season.get('champion', '?')} · "
            f"draft={season.get('draft', {}).get('picks', '?')} picks · "
            f"{'PASS' if season.get('passed') else 'FAIL'}"
        )

    print(
        f"Completed seasons: "
        f"{report.get('completed_seasons', 0)}/"
        f"{report.get('requested_seasons', args.seasons)}"
    )
    print(f"Elapsed: {elapsed:.3f}s")

    details = dict(report.get("details", {}) or {})
    active_unchanged = details.get("active_checkpoint_family_unchanged")
    if active_unchanged is not None:
        print(
            "Active checkpoint family unchanged: "
            + ("YES" if active_unchanged else "NO")
        )

    if report.get("passed"):
        print("FRANCHISE V2 PROTECTED MULTI-SEASON SOAK V1 PASSED")
        return 0

    print("FRANCHISE V2 PROTECTED MULTI-SEASON SOAK V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report.get("failed_checks", []) or []:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
