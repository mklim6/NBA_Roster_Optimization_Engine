from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _isolated_checkpoint_contract,
)

PROBE_VERSION = "franchise-deep-season-free-agency-performance-probe-v2-2026-09-11"
EXPECTED_INITIAL_PLAYERS = 850
EXPECTED_INITIAL_FREE_AGENTS = 533
EXPECTED_INITIAL_LAC_ROSTER = 3
EXPECTED_INITIAL_HISTORY = 557
EXPECTED_SIGNINGS = (
    ("Cameron Williams", "LAC", 12_700_000.00, 1),
    ("Kai Green", "POR", 9_100_000.00, 1),
    ("Luka Walker", "LAC", 22_200_000.00, 1),
    ("Emil Wright", "LAC", 33_250_000.00, 1),
    ("Amari Parker", "LAC", 2_513_124.56, 1),
    ("Isaiah Ellis", "LAC", 2_513_124.56, 1),
)
TARGET_SECONDS = 120.0
HARD_CEILING_SECONDS = 180.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in value.__dict__.items()}
    return value


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "deep_season_fa_performance_checkpoint.pkl.gz"
    if not fixture.exists():
        raise FileNotFoundError(
            "Place deep_season_fa_performance_checkpoint.pkl.gz in the project root before running this probe."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_free_agency_cpu_execution_v1 as cpu_api
    from simulation_league_state_v1 import validate_simulation_league_state
    from mutable_league_state_v1 import validate_state
    from freeform_trade_machine_engine_v3 import load_runtime_data

    active_before = _checkpoint_family_hashes(checkpoint_api.DEFAULT_CHECKPOINT_PATH)
    fixture_hash_before = _sha256(fixture)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_root = root / "outputs" / "_fa_perf_v2" / f"r{stamp}"
    probe_checkpoint = run_root / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    probe_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture, probe_checkpoint)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {
        "fixture": str(fixture),
        "fixture_sha256": fixture_hash_before,
        "isolated_checkpoint": str(probe_checkpoint),
        "target_seconds": TARGET_SECONDS,
        "hard_ceiling_seconds": HARD_CEILING_SECONDS,
    }

    try:
        with _isolated_checkpoint_contract(probe_checkpoint):
            source = checkpoint_api.load_franchise_checkpoint()
            if source is None:
                raise RuntimeError("Deep-season fixture could not be loaded.")
            state = source.simulation_state
            runtime = load_runtime_data()
            validate_simulation_league_state(state)
            validate_state(source.trade_state, runtime)

            initial_counts = {team: len(team_state.roster_player_ids) for team, team_state in state.teams.items()}
            initial_history = len(getattr(state, "free_agency_transaction_history", []) or [])
            checks.update({
                "fixture_has_expected_player_count": len(state.players) == EXPECTED_INITIAL_PLAYERS,
                "fixture_has_expected_free_agent_count": len(state.free_agent_player_ids) == EXPECTED_INITIAL_FREE_AGENTS,
                "fixture_has_expected_lac_roster": initial_counts.get("LAC") == EXPECTED_INITIAL_LAC_ROSTER,
                "fixture_has_expected_history_depth": initial_history == EXPECTED_INITIAL_HISTORY,
            })

            started = time.perf_counter()
            result = cpu_api.execute_cpu_free_agency_round_durably(
                max_signings=15,
                max_targets_per_team=8,
                recovery_directory=run_root / "recovery",
            )
            round_seconds = time.perf_counter() - started

            reload_started = time.perf_counter()
            after = checkpoint_api.load_franchise_checkpoint()
            immediate_reload_seconds = time.perf_counter() - reload_started
            if after is None:
                raise RuntimeError("Isolated checkpoint disappeared after the performance round.")
            validate_simulation_league_state(after.simulation_state)
            validate_state(after.trade_state, runtime)

            counts = {team: len(team_state.roster_player_ids) for team, team_state in after.simulation_state.teams.items()}
            observed_signings = tuple(
                (
                    row.player_name,
                    row.team_abbreviation,
                    round(float(row.annual_salary), 2),
                    int(row.years),
                )
                for row in result.signings
            )
            expected_signings = tuple(
                (name, team, round(float(salary), 2), years)
                for name, team, salary, years in EXPECTED_SIGNINGS
            )
            checks.update({
                "round_completed": result.status == "completed",
                "round_stops_at_roster_floor": result.stop_reason == "all_cpu_teams_meet_roster_floor",
                "round_commits_six_signings": result.committed_signing_count == 6,
                "signing_sequence_matches_preserved_deep_state": observed_signings == expected_signings,
                "lac_reaches_game_ready_floor": counts.get("LAC") == 8,
                "league_minimum_roster_is_game_ready": min(counts.values()) >= int(after.simulation_state.settings.minimum_game_players),
                "free_agent_pool_decrements_by_six": len(after.simulation_state.free_agent_player_ids) == EXPECTED_INITIAL_FREE_AGENTS - 6,
                "history_advances_by_six": len(getattr(after.simulation_state, "free_agency_transaction_history", []) or []) == EXPECTED_INITIAL_HISTORY + 6,
                "round_under_hard_performance_ceiling": round_seconds <= HARD_CEILING_SECONDS,
            })
            details.update({
                "round_seconds": round(round_seconds, 3),
                "immediate_reload_seconds": round(immediate_reload_seconds, 3),
                "performance_target_met": round_seconds <= TARGET_SECONDS,
                "status": result.status,
                "stop_reason": result.stop_reason,
                "signings": [
                    {
                        "player": row.player_name,
                        "team": row.team_abbreviation,
                        "annual_salary": row.annual_salary,
                        "years": row.years,
                    }
                    for row in result.signings
                ],
                "minimum_roster_after": min(counts.values()),
                "lac_roster_after": counts.get("LAC"),
                "free_agents_after": len(after.simulation_state.free_agent_player_ids),
                "history_after": len(getattr(after.simulation_state, "free_agency_transaction_history", []) or []),
            })
    finally:
        checks["fixture_unchanged"] = fixture.exists() and _sha256(fixture) == fixture_hash_before
        active_after = _checkpoint_family_hashes(checkpoint_api.DEFAULT_CHECKPOINT_PATH)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        details["active_checkpoint_family_before"] = active_before
        details["active_checkpoint_family_after"] = active_after

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": PROBE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failed_checks": failed,
        "details": details,
        "passed": not failed,
    }
    report_path = root / "outputs" / "franchise_deep_season_free_agency_performance_probe_v2.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("FRANCHISE DEEP-SEASON FREE AGENCY PERFORMANCE PROBE V2")
    print(f"Round: {details.get('round_seconds', '?')}s")
    print(f"Immediate reload: {details.get('immediate_reload_seconds', '?')}s")
    print(f"Signings: {len(details.get('signings', []))}")
    print(f"LAC roster after: {details.get('lac_roster_after', '?')}")
    print(f"Active franchise mutation: {'FORBIDDEN / UNCHANGED' if checks.get('active_checkpoint_family_unchanged') else 'FAILED'}")
    print(f"Report: {report_path}")
    if failed:
        print("FAILED CHECKS:", ", ".join(failed))
        print("FRANCHISE DEEP-SEASON FREE AGENCY PERFORMANCE PROBE V2 FAILED")
        return 1
    print("FRANCHISE DEEP-SEASON FREE AGENCY PERFORMANCE PROBE V2 PASSED")
    if not details.get("performance_target_met"):
        print(f"NOTE: correctness passed, but runtime exceeded the {TARGET_SECONDS:.0f}s target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
