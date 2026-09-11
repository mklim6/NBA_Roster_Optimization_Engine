from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "franchise_release_worktree_audit_v1.json"
VERSION = "franchise-release-worktree-audit-v1.0-2026-09-11"

SOURCE_ROOTS = ("src/", "pages/", "app_data/", "docs/", "data/reference/")
DISPOSABLE_PREFIXES = (
    "outputs/",
    "backups/",
    ".",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors="replace",
    )


def _status_rows() -> list[dict[str, str]]:
    completed = _git("status", "--porcelain=v1", "--untracked-files=all")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git status failed")
    rows: list[dict[str, str]] = []
    for raw in completed.stdout.splitlines():
        if len(raw) < 4:
            continue
        status = raw[:2]
        path = raw[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append({"status": status, "path": path.replace("\\", "/")})
    return rows


def _tracked_files() -> set[str]:
    completed = _git("ls-files")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git ls-files failed")
    return {line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()}


def _category(path: str, status: str, tracked: set[str]) -> str:
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    if any(normalized.startswith(prefix) for prefix in SOURCE_ROOTS) or normalized in {
        "Home.py", "README.md", "requirements.txt", "environment.yml", "pyproject.toml", ".gitignore"
    }:
        return "production_source_change"
    if lower.endswith((".zip", ".7z", ".tar", ".gz")) and not normalized.startswith("app_data/"):
        return "generated_archive_or_fixture"
    if normalized.startswith(("outputs/", "backups/")):
        return "generated_runtime_artifact"
    first = normalized.split("/", 1)[0]
    if first.startswith(".") and first not in {".gitignore", ".github"}:
        return "generated_stage_directory"
    if first.startswith("franchise_") and status == "??":
        return "installer_or_patch_artifact"
    if first.startswith("_snapshot") or "snapshot" in lower:
        return "snapshot_artifact"
    return "manual_review"


def main() -> int:
    tracked = _tracked_files()
    rows = _status_rows()
    for row in rows:
        row["category"] = _category(row["path"], row["status"], tracked)
        row["tracked"] = row["path"] in tracked

    tracked_src = {p for p in tracked if p.startswith("src/") and p.endswith(".py")}
    actual_src = {
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (ROOT / "src").glob("*.py")
    }
    untracked_src = sorted(actual_src - tracked_src)

    by_category: dict[str, list[str]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row["path"])

    report = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "branch": (_git("branch", "--show-current").stdout.strip()),
        "status_entry_count": len(rows),
        "tracked_src_python_count": len(tracked_src),
        "actual_src_python_count": len(actual_src),
        "untracked_src_python_count": len(untracked_src),
        "untracked_src_python": untracked_src,
        "categories": {key: sorted(value) for key, value in sorted(by_category.items())},
        "rows": rows,
        "release_blockers": {
            "untracked_production_src_present": bool(untracked_src),
            "production_source_changes_present": bool(by_category.get("production_source_change")),
        },
        "safe_cleanup_note": (
            "This audit is read-only. Do not delete production_source_change entries. "
            "Generated-stage/archive categories are cleanup candidates only after manual review."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("FRANCHISE RELEASE WORKTREE AUDIT V1")
    print(f"Branch: {report['branch'] or '(detached/unknown)'}")
    print(f"Status entries: {len(rows)}")
    print(f"Tracked src Python: {len(tracked_src)} / {len(actual_src)}")
    print(f"Untracked src Python: {len(untracked_src)}")
    for category, values in sorted(by_category.items()):
        print(f"  {category}: {len(values)}")
    print(f"Report: {OUTPUT}")
    if untracked_src:
        print("RELEASE WORKTREE AUDIT: REVIEW REQUIRED")
        print("Untracked production Python files must be classified/tracked before release packaging.")
        return 2
    print("RELEASE WORKTREE AUDIT: NO UNTRACKED SRC BLOCKER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
