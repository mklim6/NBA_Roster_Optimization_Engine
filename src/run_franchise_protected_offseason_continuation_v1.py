from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "outputs" / "franchise_protected_offseason_continuation_v1.json"
RUNS = ROOT / "outputs" / "_soak_resume"
VERSION = "franchise-protected-offseason-continuation-v1.2-staff-invariant-2026-09-17"
MAX_CONTINUED_SEASONS = 6

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _isolated_checkpoint_contract,
    _save_and_assert_roundtrip,
    _validate_release_freeze,
)
from run_franchise_protected_lifecycle_boundary_regression_v1 import (
    _checkpoint_or_raise,
    _phase,
    _postseason_stage,
    _staff_signature,
)
from run_franchise_protected_multi_season_soak_v1 import (
    EXPECTED_FORFEIT_DRAFT_SIZES,
    _population_metrics,
    _staff_personnel_signature,
    _trade_registry_covers_non_synthetic_players,
    _validate_boundary_state,
)


class ProtectedOffseasonContinuationError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(report: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _progress(index: int, count: int, season: str, stage: str) -> None:
    # Keep protected soak output portable to the default Windows cp1252
    # console. Reporting must never turn a completed lifecycle into a failure.
    print(f"[{index}/{count}] {season} - {stage}", flush=True)


def run_continuation(
    source_checkpoint: str | Path,
    *,
    seasons: int,
    keep_artifacts: bool = False,
) -> dict[str, Any]:
    if seasons < 1 or seasons > MAX_CONTINUED_SEASONS:
        raise ProtectedOffseasonContinuationError(
            f"--seasons must be between 1 and {MAX_CONTINUED_SEASONS}."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_completed_season_contract_closeout_v1 as closeout_api
    import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
    import franchise_draft_engine_v1 as draft_api
    import franchise_cpu_post_draft_roster_trim_live_v1 as trim_api
    import franchise_season_boundary_durable_transition_v1 as boundary_api
    from career_lifecycle_transition_adapter_v1 import (
        build_season_transition_preview,
        commit_season_transition_preview,
    )
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_market_season_v1 import completed_season_closeout_applied
    from franchise_staff_system_v1 import STAFF_SYSTEM_VERSION
    from mutable_league_state_v1 import validate_state
    from regular_season_schedule_v1 import (
        LEAGUE_GAME_COUNT,
        generate_regular_season_schedule,
        install_regular_season_schedule,
    )
    from regular_season_simulation_controller_v1 import (
        SimulationScope,
        simulate_regular_season_scope,
    )
    from simulation_league_state_v1 import validate_simulation_league_state
    from simulation_postseason_v1 import (
        FranchiseSimulationPolicy,
        PostseasonSimulationScope,
        advance_postseason,
        initialize_postseason,
    )
    from simulation_season_boundary_trade_reconciliation_v1 import (
        reconcile_trade_state_after_season_boundary,
    )

    source_path = Path(source_checkpoint).resolve()
    if not source_path.is_file():
        raise ProtectedOffseasonContinuationError(
            f"Source checkpoint does not exist: {source_path}"
        )

    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    if source_path == active_primary:
        raise ProtectedOffseasonContinuationError(
            "Continuation source must not be the active Streamlit checkpoint."
        )

    freeze = _validate_release_freeze()
    active_before = _checkpoint_family_hashes(active_primary)
    source_hash_before = _sha256(source_path)
    run_root = RUNS / f"r{_stamp()}"
    temp_primary = run_root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    temp_primary.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, temp_primary)

    checks: dict[str, bool] = {}
    season_reports: list[dict[str, Any]] = []
    failure = ""
    interrupted = False
    report: dict[str, Any] = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "requested_continued_seasons": seasons,
        "completed_continued_seasons": 0,
        "passed": False,
        "checks": checks,
        "failed_checks": [],
        "error": "",
        "interrupted": False,
        "season_reports": season_reports,
        "details": {
            "source_checkpoint": str(source_path),
            "source_checkpoint_hash_before": source_hash_before,
            "active_checkpoint_path": str(active_primary),
            "active_checkpoint_family_before": active_before,
            "isolated_run_root": str(run_root),
            "isolated_checkpoint": str(temp_primary),
            "release_freeze": freeze,
        },
    }
    _write(report)

    try:
        with _isolated_checkpoint_contract(temp_primary):
            runtime = load_runtime_data()
            current_cp = _checkpoint_or_raise(
                checkpoint_api, temp_primary, "Continuation source"
            )
            validate_simulation_league_state(current_cp.simulation_state)
            validate_state(current_cp.trade_state, runtime)
            source_state = current_cp.simulation_state
            source_season = str(source_state.settings.season_label)
            source_is_completed_offseason = bool(
                _phase(source_state) == "offseason"
                and _postseason_stage(source_state) == "complete"
                and completed_season_closeout_applied(source_state, source_season)
            )
            source_is_open_regular_season = bool(
                _phase(source_state) == "regular_season"
                and len(getattr(source_state, "schedule", []) or []) == LEAGUE_GAME_COUNT
            )
            checks["source_is_supported_lifecycle_stage"] = bool(
                source_is_completed_offseason or source_is_open_regular_season
            )
            if not checks["source_is_supported_lifecycle_stage"]:
                raise ProtectedOffseasonContinuationError(
                    "Continuation requires either an open regular season or a "
                    "completed-postseason offseason checkpoint whose contract "
                    "closeout is already applied."
                )

            staff_signature = _staff_signature(source_state)
            staff_personnel_signature = _staff_personnel_signature(source_state)
            checks["source_staff_signature_present"] = bool(
                staff_signature and staff_personnel_signature
            )
            history_count_before = len(getattr(source_state, "season_history", []) or [])
            report["details"]["source_season"] = source_season
            report["details"]["source_season_history_count"] = history_count_before

            # Migrate older multi-season checkpoints that predate generated-player
            # TradeState registration. This mutates only the isolated copy.
            reconciled_state, reconciled_trade, registry = (
                reconcile_trade_state_after_season_boundary(
                    current_cp.simulation_state,
                    current_cp.trade_state,
                )
            )
            checkpoint_api.save_franchise_checkpoint(
                reconciled_state,
                reconciled_trade,
                preferences=current_cp.preferences,
                reason="protected-offseason-continuation-generated-player-registry-catchup",
                path=temp_primary,
                copy_payload=True,
                force_replace=True,
            )
            current_cp = _checkpoint_or_raise(
                checkpoint_api, temp_primary, "Generated-player registry catch-up"
            )
            checks["registry_covers_non_synthetic_players"] = (
                _trade_registry_covers_non_synthetic_players(
                    current_cp.simulation_state,
                    current_cp.trade_state,
                )
            )
            report["details"]["registry_catchup_count"] = len(
                registry.registered_player_ids
            )
            _write(report)

            for continued_index in range(1, seasons + 1):
                source_season = str(current_cp.simulation_state.settings.season_label)
                season_dir = run_root / f"s{continued_index:02d}_{source_season.replace('-', '')}"
                season_dir.mkdir(parents=True, exist_ok=True)
                srep: dict[str, Any] = {
                    "continued_index": continued_index,
                    "source_season": source_season,
                    "started_at_utc": _utc_now(),
                    "checks": {},
                    "durations_seconds": {},
                    "population_start": _population_metrics(current_cp.simulation_state),
                }
                season_reports.append(srep)
                _write(report)

                if _phase(current_cp.simulation_state) == "regular_season":
                    _progress(continued_index, seasons, source_season, "simulate 1,230-game regular season")
                    t0 = time.perf_counter()
                    completed_state, season_result = simulate_regular_season_scope(
                        current_cp.simulation_state,
                        scope=SimulationScope.REMAINDER,
                    )
                    validate_simulation_league_state(completed_state)
                    srep["durations_seconds"]["regular_season"] = round(time.perf_counter() - t0, 3)
                    srep["checks"]["regular_season_complete"] = bool(
                        len(completed_state.completed_games) == LEAGUE_GAME_COUNT
                        and season_result.regular_season_complete
                        and int(season_result.remaining_games_after) == 0
                    )
                    season_cp, expected, observed = _save_and_assert_roundtrip(
                        checkpoint_api,
                        temp_primary,
                        completed_state,
                        current_cp.trade_state,
                        preferences=current_cp.preferences,
                        reason=f"protected-continuation-{source_season}-regular-season-complete",
                    )
                    srep["checks"]["regular_season_roundtrip_exact"] = expected == observed

                    _progress(continued_index, seasons, source_season, "postseason to champion")
                    t0 = time.perf_counter()
                    postseason_source = copy.deepcopy(season_cp.simulation_state)
                    initialize_postseason(postseason_source)
                    ps_cp, expected, observed = _save_and_assert_roundtrip(
                        checkpoint_api,
                        temp_primary,
                        postseason_source,
                        season_cp.trade_state,
                        preferences=season_cp.preferences,
                        reason=f"protected-continuation-{source_season}-postseason-init",
                    )
                    srep["checks"]["postseason_initialization_roundtrip_exact"] = expected == observed
                    champion_state, postseason_result = advance_postseason(
                        ps_cp.simulation_state,
                        scope=PostseasonSimulationScope.TO_CHAMPION,
                        controlled_teams=(),
                        policy=FranchiseSimulationPolicy.FREE_SIMULATION,
                        max_games=140,
                    )
                    champion = str(
                        getattr(getattr(champion_state, "postseason_state", None), "champion", "") or ""
                    ).strip()
                    validate_simulation_league_state(champion_state)
                    srep["checks"]["postseason_complete_with_champion"] = bool(
                        _postseason_stage(champion_state) == "complete"
                        and _phase(champion_state) == "offseason"
                        and champion
                        and str(postseason_result.champion or "").strip() == champion
                    )
                    champion_cp, expected, observed = _save_and_assert_roundtrip(
                        checkpoint_api,
                        temp_primary,
                        champion_state,
                        ps_cp.trade_state,
                        preferences=ps_cp.preferences,
                        reason=f"protected-continuation-{source_season}-postseason-complete",
                    )
                    srep["checks"]["champion_roundtrip_exact"] = expected == observed
                    srep["champion"] = champion
                    srep["durations_seconds"]["postseason"] = round(time.perf_counter() - t0, 3)

                    closeout_result = closeout_api.commit_completed_season_contract_closeout_durably(
                        champion_cp.simulation_state,
                        champion_cp.trade_state,
                        preferences=champion_cp.preferences,
                        checkpoint_path=temp_primary,
                        recovery_directory=season_dir / "c",
                    )
                    current_cp = _checkpoint_or_raise(
                        checkpoint_api, temp_primary, f"{source_season} closeout"
                    )
                    srep["closeout_trade_revision_after"] = int(
                        getattr(closeout_result, "trade_revision_after", 0) or 0
                    )
                else:
                    srep["checks"]["resumed_completed_regular_season"] = len(
                        getattr(current_cp.simulation_state, "completed_games", []) or []
                    ) == LEAGUE_GAME_COUNT
                    srep["checks"]["resumed_completed_postseason"] = (
                        _postseason_stage(current_cp.simulation_state) == "complete"
                    )
                    srep["checks"]["resumed_completed_closeout"] = (
                        completed_season_closeout_applied(
                            current_cp.simulation_state,
                            source_season,
                        )
                    )
                    srep["champion"] = str(
                        getattr(
                            getattr(current_cp.simulation_state, "postseason_state", None),
                            "champion",
                            "",
                        )
                        or ""
                    ).strip()

                _progress(continued_index, seasons, source_season, "CPU Free Agency")
                t0 = time.perf_counter()
                cpu_fa_signings = 0
                cpu_fa_rounds = 0
                for round_index in range(1, 7):
                    fa_source = _checkpoint_or_raise(
                        checkpoint_api,
                        temp_primary,
                        f"{source_season} CPU FA round {round_index}",
                    )
                    roster_counts = [
                        len(team.roster_player_ids)
                        for team in fa_source.simulation_state.teams.values()
                    ]
                    minimum_required = int(
                        getattr(fa_source.simulation_state.settings, "minimum_game_players", 8) or 8
                    )
                    if roster_counts and min(roster_counts) >= minimum_required:
                        break
                    result = cpu_fa_api.execute_cpu_free_agency_round_durably(
                        max_signings=15,
                        max_targets_per_team=8,
                        recovery_directory=season_dir / f"f{round_index}",
                    )
                    cpu_fa_rounds += 1
                    cpu_fa_signings += int(result.committed_signing_count)
                    if int(result.committed_signing_count) <= 0:
                        break

                fa_cp = _checkpoint_or_raise(
                    checkpoint_api, temp_primary, f"{source_season} CPU FA complete"
                )
                validate_simulation_league_state(fa_cp.simulation_state)
                validate_state(fa_cp.trade_state, runtime)
                fa_pop = _population_metrics(fa_cp.simulation_state)
                minimum_required = int(
                    getattr(fa_cp.simulation_state.settings, "minimum_game_players", 8) or 8
                )
                srep["checks"]["cpu_free_agency_reaches_roster_floor"] = (
                    fa_pop["minimum_roster"] >= minimum_required
                )
                if not srep["checks"]["cpu_free_agency_reaches_roster_floor"]:
                    underfilled = {
                        team: count
                        for team, count in fa_pop["roster_counts"].items()
                        if count < minimum_required
                    }
                    raise ProtectedOffseasonContinuationError(
                        f"{source_season} CPU Free Agency exhausted below roster floor: {underfilled}"
                    )
                srep["cpu_free_agency"] = {
                    "rounds": cpu_fa_rounds,
                    "new_signings_after_resume": cpu_fa_signings,
                    "minimum_roster_after": fa_pop["minimum_roster"],
                }
                srep["durations_seconds"]["free_agency"] = round(time.perf_counter() - t0, 3)

                _progress(continued_index, seasons, source_season, "Draft + post-Draft trim")
                t0 = time.perf_counter()
                draft_api.initialize_draft_state(
                    fa_cp.simulation_state,
                    runtime,
                    controlled_teams=(),
                    class_strength=5,
                )
                draft_api.conduct_lottery(fa_cp.simulation_state, runtime)
                draft_api.reveal_draft_class(fa_cp.simulation_state)
                draft_api.start_draft_night(fa_cp.simulation_state)
                drafted_count = draft_api.simulate_rest_of_draft(
                    fa_cp.simulation_state,
                    integrate=True,
                )
                draft = draft_api.draft_state(fa_cp.simulation_state)
                if draft is None:
                    raise ProtectedOffseasonContinuationError(
                        f"{source_season} draft state disappeared."
                    )
                order_count = len(draft.get("draft_order", []) or [])
                draft_year = int(draft.get("draft_year", 0) or 0)
                expected_draft_size = EXPECTED_FORFEIT_DRAFT_SIZES.get(draft_year, 60)
                srep["checks"]["draft_complete"] = bool(
                    draft_api.draft_is_complete(fa_cp.simulation_state)
                    and int(draft.get("current_pick_index", 0) or 0) == order_count
                    and drafted_count == order_count
                )
                srep["checks"]["draft_size_matches_clippers_forfeiture_schedule"] = (
                    order_count == expected_draft_size
                )
                srep["draft"] = {
                    "draft_year": draft_year,
                    "picks": order_count,
                    "expected_picks": expected_draft_size,
                }
                draft_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api,
                    temp_primary,
                    fa_cp.simulation_state,
                    fa_cp.trade_state,
                    preferences=fa_cp.preferences,
                    reason=f"protected-continuation-{source_season}-draft-complete",
                )
                srep["checks"]["draft_roundtrip_exact"] = expected == observed
                trim_source_fp = boundary_api.checkpoint_boundary_fingerprint(draft_cp)
                trim_result = trim_api.commit_atomic_cpu_post_draft_trim_live(
                    expected_source_fingerprint=trim_source_fp,
                    confirmation=trim_api.confirmation_token(draft_cp.simulation_state),
                    checkpoint_path=temp_primary,
                    recovery_directory=season_dir / "t",
                )
                trimmed = _checkpoint_or_raise(
                    checkpoint_api, temp_primary, f"{source_season} post-Draft trim"
                )
                validate_simulation_league_state(trimmed.simulation_state)
                validate_state(trimmed.trade_state, runtime)
                srep["checks"]["post_draft_trim_committed_or_unneeded"] = (
                    str(trim_result.status) in {"committed", "no_trim_required"}
                )
                srep["durations_seconds"]["draft_and_trim"] = round(time.perf_counter() - t0, 3)

                _progress(continued_index, seasons, source_season, "atomic boundary to next season")
                t0 = time.perf_counter()
                boundary_source_fp = boundary_api.checkpoint_boundary_fingerprint(trimmed)
                transition_preview = build_season_transition_preview(trimmed.simulation_state)
                transitioned, _ = commit_season_transition_preview(
                    trimmed.simulation_state,
                    transition_preview,
                )
                lifecycle = dict(transition_preview.get("career_lifecycle", {}) or {})
                retirement_plan = dict(lifecycle.get("retirement_plan", {}) or {})
                srep["checks"]["career_lifecycle_adapter_active"] = bool(
                    lifecycle.get("adapter_version")
                    and lifecycle.get("career_lifecycle_version")
                    and not retirement_plan.get("skipped_because_no_completed_season", True)
                )
                srep["checks"]["retirement_population_matches_preview"] = (
                    len(transitioned.players)
                    == int(lifecycle.get("players_after_transition", -1))
                )
                srep["career_lifecycle"] = {
                    "retirements": retirement_plan.get("retirement_count"),
                    "rostered_retirements": retirement_plan.get("rostered_retirements"),
                    "free_agent_retirements": retirement_plan.get("free_agent_retirements"),
                    "players_after_transition": lifecycle.get("players_after_transition"),
                }
                target_season = str(transition_preview["target_season"])
                rookies_activated = draft_api.activate_drafted_rookies_after_transition(
                    transitioned,
                    target_season,
                )
                schedule = generate_regular_season_schedule(
                    transitioned,
                    seed=transitioned.settings.random_seed,
                )
                install_regular_season_schedule(transitioned, schedule)
                validate_simulation_league_state(transitioned)
                boundary_api.commit_atomic_season_boundary_live(
                    transitioned,
                    expected_source_fingerprint=boundary_source_fp,
                    expected_target_season=target_season,
                    confirmation=boundary_api.confirmation_token(source_season, target_season),
                    checkpoint_path=temp_primary,
                    recovery_directory=season_dir / "b",
                )
                next_cp = _checkpoint_or_raise(
                    checkpoint_api, temp_primary, f"{target_season} boundary"
                )
                validate_simulation_league_state(next_cp.simulation_state)
                validate_state(next_cp.trade_state, runtime)
                srep["checks"]["boundary_trade_registry_covers_non_synthetic_players"] = (
                    _trade_registry_covers_non_synthetic_players(
                        next_cp.simulation_state,
                        next_cp.trade_state,
                    )
                )
                srep["checks"].update(
                    {
                        f"boundary_{key}": value
                        for key, value in _validate_boundary_state(
                            next_cp.simulation_state,
                            target_season=target_season,
                            staff_personnel_signature=staff_personnel_signature,
                            staff_version=STAFF_SYSTEM_VERSION,
                        ).items()
                    }
                )
                second_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api,
                    temp_primary,
                    next_cp.simulation_state,
                    next_cp.trade_state,
                    preferences=next_cp.preferences,
                    reason=f"protected-continuation-{target_season}-second-roundtrip",
                )
                srep["checks"]["next_season_second_roundtrip_exact"] = expected == observed
                srep["checks"]["drafted_rookies_activated"] = int(rookies_activated) > 0
                srep["target_season"] = target_season
                srep["rookies_activated"] = int(rookies_activated)
                srep["population_end"] = _population_metrics(second_cp.simulation_state)
                srep["season_history_count"] = len(
                    getattr(second_cp.simulation_state, "season_history", []) or []
                )
                srep["durations_seconds"]["season_boundary"] = round(time.perf_counter() - t0, 3)
                srep["completed_at_utc"] = _utc_now()
                srep["passed"] = all(srep["checks"].values())
                if not srep["passed"]:
                    bad = [name for name, passed in srep["checks"].items() if not passed]
                    raise ProtectedOffseasonContinuationError(
                        f"{source_season} continuation checks failed: {bad}"
                    )

                snapshot = run_root / "cp" / f"{target_season.replace('-', '')}.pkl.gz"
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_primary, snapshot)
                srep["checkpoint_snapshot"] = str(snapshot)
                report["completed_continued_seasons"] = continued_index
                current_cp = second_cp
                _write(report)
                _progress(
                    continued_index,
                    seasons,
                    source_season,
                    f"PASS -> {target_season}",
                )

            checks["all_requested_continued_seasons_completed"] = (
                report["completed_continued_seasons"] == seasons
            )
            checks["all_continued_season_reports_passed"] = bool(
                len(season_reports) == seasons
                and all(bool(item.get("passed")) for item in season_reports)
            )
            checks["staff_personnel_signature_survived"] = (
                _staff_personnel_signature(current_cp.simulation_state)
                == staff_personnel_signature
            )
            checks["season_history_advanced_by_continuation_depth"] = (
                len(getattr(current_cp.simulation_state, "season_history", []) or [])
                == history_count_before + seasons
            )
    except KeyboardInterrupt:
        interrupted = True
        failure = "KeyboardInterrupt: continuation interrupted by user"
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        report["details"]["exception_traceback"] = traceback.format_exc()
    finally:
        checks["source_checkpoint_unchanged"] = (
            source_path.is_file() and _sha256(source_path) == source_hash_before
        )
        active_after = _checkpoint_family_hashes(active_primary)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        report["details"]["source_checkpoint_hash_after"] = (
            _sha256(source_path) if source_path.is_file() else ""
        )
        report["details"]["active_checkpoint_family_after"] = active_after

    failed = [name for name, passed in checks.items() if not passed]
    for srep in season_reports:
        for name, passed in (srep.get("checks") or {}).items():
            if not passed:
                failed.append(
                    f"continued_{srep.get('continued_index')}_{srep.get('source_season')}::{name}"
                )
    if failure and not interrupted:
        failed.append("protected_offseason_continuation_raised")

    report["generated_at_utc"] = _utc_now()
    report["interrupted"] = interrupted
    report["error"] = failure
    report["failed_checks"] = failed
    report["passed"] = bool(
        not failed
        and not interrupted
        and report["completed_continued_seasons"] == seasons
    )
    if report["passed"] and not keep_artifacts:
        shutil.rmtree(run_root, ignore_errors=True)
        report["details"]["isolated_artifacts_removed_after_pass"] = True
    else:
        report["details"]["isolated_artifacts_preserved"] = str(run_root)
    _write(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Continue a protected soak from a preserved completed-postseason "
            "offseason checkpoint without touching the active save."
        )
    )
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--seasons", type=int, default=1)
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    print("FRANCHISE PROTECTED OFFSEASON CONTINUATION V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Active franchise mutation: FORBIDDEN")
    print(f"Requested continued seasons: {args.seasons}")
    print()
    started = time.perf_counter()
    report = run_continuation(
        args.source_checkpoint,
        seasons=args.seasons,
        keep_artifacts=args.keep_artifacts,
    )
    elapsed = round(time.perf_counter() - started, 3)
    report["duration_seconds"] = elapsed
    _write(report)

    print()
    print("CONTINUATION SUMMARY")
    for item in report["season_reports"]:
        print(
            f"  {item.get('source_season')} -> {item.get('target_season', '?')} - "
            f"champion={item.get('champion', '?')} - "
            f"draft={item.get('draft', {}).get('picks', '?')} picks - "
            f"{'PASS' if item.get('passed') else 'FAIL'}"
        )
    print(
        "Completed continued seasons: "
        f"{report['completed_continued_seasons']}/{report['requested_continued_seasons']}"
    )
    print(f"Report: {OUTPUT}")
    print(f"Elapsed: {elapsed:.3f}s")
    if report["passed"]:
        print("FRANCHISE PROTECTED OFFSEASON CONTINUATION V1 PASSED")
        return 0
    print("FRANCHISE PROTECTED OFFSEASON CONTINUATION V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report.get("failed_checks", []):
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
