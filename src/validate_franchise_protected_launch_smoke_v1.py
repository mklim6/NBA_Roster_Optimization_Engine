from __future__ import annotations

import ast
import json
import py_compile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "src" / "run_franchise_protected_launch_smoke_v1.py"
OUTPUT = ROOT / "outputs" / "franchise_protected_launch_smoke_v1_validator.json"
VERSION = "franchise-protected-launch-smoke-validator-v1.0-2026-09-09"


def main() -> int:
    source = RUNNER.read_text(encoding="utf-8") if RUNNER.is_file() else ""
    tree = ast.parse(source) if source else None
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    } if tree is not None else set()

    checks = {
        "runner_exists": RUNNER.is_file(),
        "runner_compiles": False,
        "runner_has_isolated_checkpoint_context": "_isolated_checkpoint_contract" in function_names,
        "runner_hashes_active_checkpoint_family": "_checkpoint_family_hashes(active_primary)" in source,
        "runner_requires_sep7_freeze": "nba_sep7_release_freeze_v1.json" in source,
        "runner_verifies_all_frozen_hashes": "all_frozen_hashes_match" in source,
        "runner_never_clears_active_checkpoint": "clear_franchise_checkpoint(" not in source,
        "runner_redirects_bound_checkpoint_defaults": "__kwdefaults__" in source,
        "runner_builds_isolated_source_fixture": "protected-launch-source-fixture" in source,
        "runner_commits_live_start": "commit_live_franchise_start(" in source,
        "runner_verifies_frozen_live_fingerprint": "frozen_live_start_fingerprint_matches" in source,
        "runner_opens_regular_season": "commit_opening_regular_season_live(" in source,
        "runner_previews_games_before_commit": "commit=False" in source and "commit=True" in source,
        "runner_reloads_after_game_saves": "protected-smoke-after-game-" in source,
        "runner_checks_standings_after_reload": "standings_reconcile_after_games" in source,
        "runner_restores_prelaunch_source": "_restore_checkpoint_family" in source,
        "runner_requires_active_family_unchanged": "active_checkpoint_family_unchanged" in source,
        "runner_preserves_failure_artifacts": "isolated_artifacts_preserved" in source,
    }
    try:
        py_compile.compile(str(RUNNER), doraise=True)
        checks["runner_compiles"] = True
    except Exception:
        checks["runner_compiles"] = False

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print()
    if report["passed"]:
        print("FRANCHISE PROTECTED LAUNCH SMOKE HARNESS V1 PASSED")
        return 0
    print("FRANCHISE PROTECTED LAUNCH SMOKE HARNESS V1 FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
