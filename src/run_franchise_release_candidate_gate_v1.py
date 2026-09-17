from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "outputs" / "franchise_release_candidate_gate_v1.json"
VERSION = "franchise-release-candidate-gate-v1.2-2026-09-16"


@dataclass(frozen=True)
class StageResult:
    name: str
    command: list[str]
    returncode: int
    passed: bool
    stdout_tail: list[str]
    stderr_tail: list[str]
    duration_seconds: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_family_hashes(primary: Path) -> dict[str, str]:
    if not primary.parent.exists():
        return {}
    prefix = primary.name.split(".pkl", 1)[0]
    return {
        candidate.name: digest
        for candidate in sorted(primary.parent.iterdir(), key=lambda p: p.name)
        if candidate.is_file()
        and candidate.name.startswith(prefix)
        and (digest := _sha256(candidate)) is not None
    }


def _tail(text: str, *, lines: int = 35) -> list[str]:
    values = str(text or "").splitlines()
    return values[-lines:]


def _run_stage(name: str, command: Iterable[str]) -> StageResult:
    args = [str(value) for value in command]
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (
        os.pathsep + current_pythonpath if current_pythonpath else ""
    )
    started = time.perf_counter()
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
    )
    elapsed = round(time.perf_counter() - started, 3)
    result = StageResult(
        name=name,
        command=args,
        returncode=int(completed.returncode),
        passed=completed.returncode == 0,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
        duration_seconds=elapsed,
    )
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {name} ({elapsed:.3f}s)")
    if not result.passed:
        for line in result.stderr_tail[-12:]:
            print(f"  stderr: {line}")
        for line in result.stdout_tail[-12:]:
            print(f"  stdout: {line}")
    return result


def _semantic_fingerprint(state: Any, trade_state: Any) -> str:
    """Stable-enough state fingerprint for isolated rollback verification.

    This intentionally ignores checkpoint timestamps and serializer details. It covers
    franchise identity, player placement/contracts, rosters, schedule/completed-game
    keys, transaction count, and current draft-right ownership.
    """

    players: dict[str, dict[str, Any]] = {}
    for player_id, player in sorted(getattr(state, "players", {}).items()):
        contract = getattr(player, "contract", None)
        players[str(player_id)] = {
            "team": str(getattr(player, "team_abbreviation", "") or ""),
            "status": str(getattr(player, "roster_status", "") or ""),
            "overall": getattr(player, "overall_rating", None),
            "two_way": bool(getattr(player, "two_way", False)),
            "salary": getattr(contract, "salary", None),
            "years_remaining": getattr(contract, "years_remaining", None),
            "option_type": str(getattr(contract, "option_type", "") or ""),
        }

    teams = {
        str(team): list(getattr(team_state, "roster_player_ids", ()))
        for team, team_state in sorted(getattr(state, "teams", {}).items())
    }
    schedule = sorted(str(key) for key in getattr(state, "schedule", {}))
    completed = sorted(str(key) for key in getattr(state, "completed_games", {}))
    payload = {
        "season": str(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": str(getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", ""))),
        "players": players,
        "teams": teams,
        "free_agents": sorted(str(value) for value in getattr(state, "free_agent_player_ids", ())),
        "schedule": schedule,
        "completed": completed,
        "transaction_count": len(getattr(trade_state, "transaction_history", ()) or ()),
        "pick_team_by_id": {
            str(key): str(value or "")
            for key, value in sorted(getattr(trade_state, "pick_team_by_id", {}).items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _run_isolated_live_start_transaction_test() -> dict[str, Any]:
    """Exercise commit + forced rollback entirely against a temporary checkpoint tree."""

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_live_start_v1 as live_api
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_full_reset_v1 import build_starting_franchise

    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_backup = Path(checkpoint_api.DEFAULT_BACKUP_PATH).resolve()
    active_before = _checkpoint_family_hashes(active_primary)

    original_default_primary = checkpoint_api.DEFAULT_CHECKPOINT_PATH
    original_default_backup = checkpoint_api.DEFAULT_BACKUP_PATH
    original_builder = live_api.build_live_starting_franchise

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {
        "active_checkpoint_path": str(active_primary),
        "active_checkpoint_family_before": active_before,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="franchise_rc_gate_",
            dir=str(OUTPUT.parent),
        ) as temp_dir:
            temp_root = Path(temp_dir)
            temp_primary = (
                temp_root
                / "outputs"
                / "runtime"
                / "franchise_mode_checkpoint_v1.pkl.gz"
            )
            temp_backup = temp_primary.with_name(temp_primary.name + ".backup")
            temp_primary.parent.mkdir(parents=True, exist_ok=True)

            # Both constants must move together: checkpoint_backup_path() treats the
            # default primary specially and otherwise could point at the real backup.
            checkpoint_api.DEFAULT_CHECKPOINT_PATH = temp_primary
            checkpoint_api.DEFAULT_BACKUP_PATH = temp_backup

            runtime = load_runtime_data()
            source = build_starting_franchise(runtime)
            source_fingerprint = _semantic_fingerprint(
                source.simulation_state,
                source.trade_state,
            )

            result = live_api.commit_live_franchise_start(
                runtime,
                source.simulation_state,
                source.trade_state,
                preferences={"release_candidate_gate": True},
            )
            committed = checkpoint_api.load_franchise_checkpoint(
                path=temp_primary,
                allow_backup=False,
            )
            checks["isolated_commit_returned"] = committed is not None
            if committed is None:
                raise RuntimeError("Isolated live-start commit could not be reloaded.")

            committed_fingerprint = live_api.live_start_fingerprint(
                committed.simulation_state,
                committed.trade_state,
            )
            checks["isolated_commit_fingerprint_matches"] = (
                committed_fingerprint == result.fingerprint
            )
            checks["isolated_commit_installed_expected_universe"] = (
                getattr(
                    committed.simulation_state,
                    "franchise_start_universe_v1",
                    {},
                ).get("universe_id")
                == live_api.LIVE_START_UNIVERSE_ID
            )
            recovery_dir = Path(result.backup_directory)
            checks["isolated_commit_created_recovery_manifest"] = (
                recovery_dir.is_dir()
                and (recovery_dir / "live_start_manifest.json").is_file()
                and (recovery_dir / "checkpoint").is_dir()
            )

            # Avoid same-second recovery-directory collisions because the live-start
            # transaction intentionally uses a second-resolution timestamp.
            time.sleep(1.05)

            def _intentional_failure(*_args: Any, **_kwargs: Any) -> Any:
                raise RuntimeError("intentional-release-candidate-rollback-test")

            live_api.build_live_starting_franchise = _intentional_failure
            rollback_error = ""
            try:
                live_api.commit_live_franchise_start(
                    runtime,
                    source.simulation_state,
                    source.trade_state,
                    preferences={"release_candidate_gate": True},
                )
            except live_api.FranchiseLiveStartError as exc:
                rollback_error = str(exc)
            finally:
                live_api.build_live_starting_franchise = original_builder

            checks["forced_failure_was_observed"] = bool(rollback_error)
            checks["forced_failure_reports_automatic_restore"] = (
                "restored automatically" in rollback_error.lower()
            )
            restored = checkpoint_api.load_franchise_checkpoint(
                path=temp_primary,
                allow_backup=False,
            )
            checks["rollback_checkpoint_reloaded"] = restored is not None
            restored_fingerprint = (
                _semantic_fingerprint(restored.simulation_state, restored.trade_state)
                if restored is not None
                else ""
            )
            checks["rollback_restored_source_semantics"] = (
                restored_fingerprint == source_fingerprint
            )

            details.update(
                {
                    "temporary_checkpoint": str(temp_primary),
                    "commit_result": asdict(result),
                    "committed_live_fingerprint": committed_fingerprint,
                    "source_semantic_fingerprint": source_fingerprint,
                    "restored_semantic_fingerprint": restored_fingerprint,
                    "forced_rollback_error": rollback_error,
                }
            )
    finally:
        live_api.build_live_starting_franchise = original_builder
        checkpoint_api.DEFAULT_CHECKPOINT_PATH = original_default_primary
        checkpoint_api.DEFAULT_BACKUP_PATH = original_default_backup

    # The entire transactional test ran on the temporary path. Verify that the active
    # checkpoint family is byte-for-byte unchanged anyway.
    active_after = _checkpoint_family_hashes(active_primary)
    details["active_checkpoint_family_after"] = active_after
    details["active_backup_path"] = str(active_backup)
    checks["active_checkpoint_family_unchanged"] = active_before == active_after

    failed = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the final non-destructive Franchise Mode release-candidate gate. "
            "The active franchise checkpoint is hashed before/after; live-start commit "
            "and rollback are exercised only against a temporary checkpoint tree."
        )
    )
    parser.add_argument(
        "--skip-full",
        action="store_true",
        help="Skip the expensive unified --full validation stage.",
    )
    parser.add_argument(
        "--skip-quick",
        action="store_true",
        help="Skip the unified --quick validation stage.",
    )
    parser.add_argument(
        "--skip-isolated-transaction",
        action="store_true",
        help="Skip the temporary live-start commit/forced-rollback transaction test.",
    )
    args = parser.parse_args()

    print("FRANCHISE RELEASE CANDIDATE GATE V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print()

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_api

        active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    except Exception:
        active_primary = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

    active_before = _checkpoint_family_hashes(active_primary)
    stages: list[StageResult] = []

    if not args.skip_quick:
        stages.append(
            _run_stage(
                "unified_quick_validation",
                [sys.executable, str(SRC / "run_project_validation.py"), "--quick"],
            )
        )

    if not args.skip_full:
        stages.append(
            _run_stage(
                "unified_full_validation",
                [sys.executable, str(SRC / "run_project_validation.py"), "--full"],
            )
        )

    dedicated = [
        ("release_worktree_audit", "audit_franchise_release_worktree_v1.py"),
        ("live_cutoff_evidence_audit", "audit_franchise_live_cutoff_v1.py"),
        ("current_reference_validation", "validate_nba_current_reference_v2.py"),
        ("sep7_release_data_freeze", "validate_franchise_sep7_release_data_freeze_v1.py"),
        ("live_start_validation", "validate_franchise_live_start_v1.py"),
        ("staff_foundation_validation", "validate_franchise_staff_foundation_v1.py"),
        (
            "free_agency_subfive_rotation_repair",
            "validate_franchise_free_agency_subfive_rotation_repair_v1.py",
        ),
        (
            "deep_season_free_agency_performance_v2",
            "validate_franchise_deep_season_free_agency_performance_hotfix_v2.py",
        ),
        ("draft_forfeiture_validation", "validate_franchise_draft_forfeitures_v1.py"),
        ("live_asset_ledger_validation", "validate_franchise_live_asset_ledger_v1.py"),
        ("morale_v3_0_2_validation", "validate_franchise_morale_v3_0_2_dnp_ui_hotfix.py"),
        ("morale_v3_0_2_regression", "run_franchise_morale_v3_0_2_dnp_ui_hotfix_regression.py"),
        ("cpu_morale_v4_validation", "validate_franchise_cpu_morale_reactions_v4.py"),
        ("cpu_morale_v4_regression", "run_franchise_cpu_morale_reactions_v4_regression.py"),
        ("morale_trade_market_v5a_validation", "validate_franchise_morale_trade_market_bridge_v5a.py"),
        ("morale_trade_market_v5a_regression", "run_franchise_morale_trade_market_bridge_v5a_regression.py"),
        ("morale_trade_finder_v5b_validation", "validate_franchise_morale_trade_finder_bridge_v5b.py"),
        ("morale_trade_finder_v5b_regression", "run_franchise_morale_trade_finder_bridge_v5b_regression.py"),
        ("cpu_autonomous_trade_v6a_validation", "validate_franchise_cpu_autonomous_trade_market_v6a.py"),
        ("cpu_autonomous_trade_v6a_regression", "run_franchise_cpu_autonomous_trade_market_v6a_regression.py"),
        ("cpu_incoming_offers_v6b_validation", "validate_franchise_cpu_incoming_trade_offers_v6b.py"),
        ("cpu_incoming_offers_v6b_regression", "run_franchise_cpu_incoming_trade_offers_v6b_regression.py"),
        ("game_day_calendar_sync_validation", "validate_franchise_game_day_league_calendar_sync_v1.py"),
        ("game_day_calendar_sync_regression", "run_franchise_game_day_league_calendar_sync_v1_regression.py"),
        ("postgame_hotfix_v6_0_1_validation", "validate_franchise_postgame_performance_offer_hotfix_v6_0_1.py"),
        ("postgame_hotfix_v6_0_1_regression", "run_franchise_postgame_performance_offer_hotfix_v6_0_1_regression.py"),
    ]
    for name, filename in dedicated:
        stages.append(_run_stage(name, [sys.executable, str(SRC / filename)]))

    transaction_result: dict[str, Any]
    if args.skip_isolated_transaction:
        transaction_result = {
            "passed": True,
            "skipped": True,
            "checks": {},
            "failed_checks": [],
        }
    else:
        print("[....] isolated_live_start_commit_and_rollback")
        started = time.perf_counter()
        try:
            transaction_result = _run_isolated_live_start_transaction_test()
        except Exception as exc:
            transaction_result = {
                "passed": False,
                "checks": {},
                "failed_checks": ["isolated_transaction_raised"],
                "error": f"{type(exc).__name__}: {exc}",
            }
        elapsed = round(time.perf_counter() - started, 3)
        transaction_result["duration_seconds"] = elapsed
        print(
            f"[{'PASS' if transaction_result.get('passed') else 'FAIL'}] "
            f"isolated_live_start_commit_and_rollback ({elapsed:.3f}s)"
        )

    active_after = _checkpoint_family_hashes(active_primary)
    active_checkpoint_unchanged = active_before == active_after

    failed_stages = [stage.name for stage in stages if not stage.passed]
    if not transaction_result.get("passed", False):
        failed_stages.append("isolated_live_start_commit_and_rollback")
    if not active_checkpoint_unchanged:
        failed_stages.append("active_checkpoint_family_unchanged")

    report = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "project_root": str(ROOT),
        "passed": not failed_stages,
        "failed_stages": failed_stages,
        "active_checkpoint": {
            "path": str(active_primary),
            "family_before": active_before,
            "family_after": active_after,
            "unchanged": active_checkpoint_unchanged,
        },
        "stages": [asdict(stage) for stage in stages],
        "isolated_live_start_transaction": transaction_result,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Report: {OUTPUT}")
    if report["passed"]:
        print("FRANCHISE RELEASE CANDIDATE GATE V1 PASSED")
        return 0

    print("FRANCHISE RELEASE CANDIDATE GATE V1 FAILED")
    for stage in failed_stages:
        print(f"  - {stage}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
