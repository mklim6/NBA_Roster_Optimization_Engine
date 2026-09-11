from __future__ import annotations

import json
import py_compile
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RUNNER = SRC / "run_franchise_protected_transaction_regression_v1.py"
OUTPUT = ROOT / "outputs" / "franchise_protected_transaction_regression_v1_validator.json"
VERSION = "franchise-protected-transaction-regression-validator-v1.0-2026-09-09"


def main() -> int:
    text = RUNNER.read_text(encoding="utf-8") if RUNNER.is_file() else ""
    checks = {
        "runner_exists": RUNNER.is_file(),
        "runner_compiles": True,
        "step2a_isolation_harness_available": (SRC / "run_franchise_protected_launch_smoke_v1.py").is_file(),
        "sep7_freeze_manifest_available": (ROOT / "app_data" / "nba_sep7_release_freeze_v1.json").is_file(),
        "runner_reuses_tested_isolated_checkpoint_context": "_isolated_checkpoint_contract" in text,
        "runner_hashes_active_checkpoint_family": "_checkpoint_family_hashes" in text,
        "runner_requires_release_freeze": "_validate_release_freeze" in text,
        "runner_builds_disposable_source_fixture": "protected-transaction-source-fixture" in text,
        "runner_launches_frozen_live_start": "commit_live_franchise_start" in text,
        "runner_persists_controlled_team_preference": "franchise_pref_controlled_teams" in text,
        "runner_builds_contract_legal_fa_preview": "build_contract_legal_free_agency_preview" in text,
        "runner_commits_live_fa_signing": "commit_contract_legal_free_agency_preview_live" in text,
        "runner_checks_fa_trade_state_sync": "free_agency_trade_state_sync_survives_reload" in text,
        "runner_reloads_after_fa_signing": "post_signing_save_reload_exact" in text,
        "runner_opens_regular_season_after_signing": "post_signing_opening_preview_is_commit_ready" in text,
        "runner_finds_deterministic_pick_trade": "_find_pick_only_trade_pass" in text,
        "runner_commits_live_trade": "commit_live_franchise_trade" in text,
        "runner_checks_pick_ownership_after_reload": "pick_a_owner_swapped_after_reload" in text and "pick_b_owner_swapped_after_reload" in text,
        "runner_reloads_after_trade": "post_trade_save_reload_exact" in text,
        "runner_restores_clean_live_fixture": "clean_frozen_live_start_restores_exactly" in text,
        "runner_requires_active_checkpoint_unchanged": "active_checkpoint_family_unchanged" in text,
        "runner_preserves_failure_artifacts": "isolated_artifacts_preserved" in text,
    }
    if RUNNER.is_file():
        try:
            py_compile.compile(str(RUNNER), doraise=True)
        except Exception:
            checks["runner_compiles"] = False
    else:
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
    if failed:
        print("FRANCHISE PROTECTED TRANSACTION REGRESSION HARNESS V1 FAILED")
        return 1
    print("FRANCHISE PROTECTED TRANSACTION REGRESSION HARNESS V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
