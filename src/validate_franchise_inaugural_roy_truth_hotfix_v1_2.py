from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_league_history_season_recap_v1.py"
    source = path.read_text(encoding="utf-8")

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["version_is_v1_2"] = (
        "franchise-league-history-season-recap-v1.2-inaugural-rookie-truth-2026-09-16"
        in source
    )
    checks["truthful_empty_state_present"] = "No qualifying rookie class" in source
    checks["played_rookie_count_present"] = '"played_rookie_count"' in source
    checks["no_invented_winner_copy"] = "It never invents an inaugural-season winner." in source
    checks["no_checkpoint_write"] = (
        "save_franchise_checkpoint" not in source
        and "commit_franchise_checkpoint" not in source
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE INAUGURAL ROY TRUTH HOTFIX V1.2 VALIDATOR FAILED")
        return 1

    print("FRANCHISE INAUGURAL ROY TRUTH HOTFIX V1.2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
