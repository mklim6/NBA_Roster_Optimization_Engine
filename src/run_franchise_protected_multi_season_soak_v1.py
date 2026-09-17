from __future__ import annotations

import argparse
import copy
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
OUTPUT = ROOT / "outputs" / "franchise_protected_multi_season_soak_v1.json"
RUNS = ROOT / "outputs" / "_soak"
VERSION = "franchise-protected-multi-season-soak-v1.2-staff-invariant-2026-09-17"
DEFAULT_SEASONS = 8
MAX_SEASONS = 10
EXPECTED_FORFEIT_DRAFT_SIZES = {
    2029: 59,
    2030: 59,
    2031: 59,
    2032: 59,
    2033: 59,
}

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _durability_fingerprint,
    _isolated_checkpoint_contract,
    _save_and_assert_roundtrip,
    _validate_release_freeze,
)
from run_franchise_protected_lifecycle_boundary_regression_v1 import (
    _checkpoint_or_raise,
    _jsonable,
    _phase,
    _postseason_stage,
    _staff_signature,
)


def _staff_personnel_signature(state: Any) -> str:
    """Hash only persistent staff personnel, excluding season metadata/history.

    The staff container intentionally advances ``season_label`` and
    ``scouting_history`` over a multi-season franchise. Those fields must not
    invalidate the persistence invariant. In this headless soak no staff
    transaction is performed, so the 30 teams' actual staff payload should
    remain byte-for-byte stable.
    """
    import hashlib

    staff = getattr(state, "franchise_staff_state_v1", None)
    if staff is None:
        return ""
    teams = getattr(staff, "teams", {}) or {}
    encoded = json.dumps(
        _jsonable(teams),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProtectedMultiSeasonSoakError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_partial(report: dict[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _progress(season_index: int, seasons: int, season_label: str, stage: str) -> None:
    print(f"[{season_index}/{seasons}] {season_label} · {stage}", flush=True)


def _population_metrics(state: Any) -> dict[str, Any]:
    teams = getattr(state, "teams", {}) or {}
    players = getattr(state, "players", {}) or {}
    free_agents = list(
        getattr(
            state,
            "free_agent_player_ids",
            getattr(state, "free_agent_ids", []),
        )
        or []
    )
    roster_counts = {
        str(team): len(getattr(team_state, "roster_player_ids", []) or [])
        for team, team_state in teams.items()
    }
    rostered_ids = {
        str(pid)
        for team_state in teams.values()
        for pid in (getattr(team_state, "roster_player_ids", []) or [])
    }
    return {
        "teams": len(teams),
        "players": len(players),
        "rostered": len(rostered_ids),
        "free_agents": len(free_agents),
        "minimum_roster": min(roster_counts.values()) if roster_counts else 0,
        "maximum_roster": max(roster_counts.values()) if roster_counts else 0,
        "roster_counts": dict(sorted(roster_counts.items())),
    }


def _trade_registry_covers_non_synthetic_players(state: Any, trade_state: Any) -> bool:
    ownership = getattr(trade_state, "player_team_by_id", {}) or {}
    expected = {
        str(player_id).strip()
        for player_id, player in (getattr(state, "players", {}) or {}).items()
        if str(player_id).strip() and not bool(getattr(player, "synthetic", False))
    }
    return expected.issubset(set(ownership))


def _validate_boundary_state(
    state: Any,
    *,
    target_season: str,
    staff_personnel_signature: str,
    staff_version: str,
) -> dict[str, bool]:
    from regular_season_schedule_v1 import LEAGUE_GAME_COUNT
    from simulation_league_state_v1 import validate_simulation_league_state
    from franchise_staff_system_v1 import ensure_franchise_staff_state

    validate_simulation_league_state(state)
    pop = _population_metrics(state)
    # Mirror the real UI/runtime behavior at a new season boundary. This may
    # legitimately advance staff.season_label and append scouting history.
    staff = ensure_franchise_staff_state(state)
    standings = getattr(state, "standings", {}) or {}
    history = getattr(staff, "scouting_history", None)
    return {
        "target_season_active": str(getattr(getattr(state, "settings", None), "season_label", "")) == target_season,
        "regular_season_phase": _phase(state) == "regular_season",
        "schedule_is_1230": len(getattr(state, "schedule", []) or []) == LEAGUE_GAME_COUNT,
        "new_season_has_zero_completed_games": len(getattr(state, "completed_games", []) or []) == 0,
        "new_season_standings_reset": sum(int(getattr(s, "games_played", 0) or 0) for s in standings.values()) == 0,
        "all_30_teams_present": pop["teams"] == 30,
        "all_teams_game_ready": pop["minimum_roster"] >= int(getattr(getattr(state, "settings", None), "minimum_game_players", 8) or 8),
        "staff_30_teams_and_version": bool(
            staff is not None
            and len(getattr(staff, "teams", {}) or {}) == 30
            and str(getattr(staff, "version", "") or "") == staff_version
        ),
        "staff_season_label_current": str(getattr(staff, "season_label", "") or "") == target_season,
        "staff_personnel_signature_stable": _staff_personnel_signature(state) == staff_personnel_signature,
        "staff_scouting_history_well_formed": isinstance(history, list),
    }


def run_soak(*, seasons: int = DEFAULT_SEASONS, keep_artifacts: bool = False) -> dict[str, Any]:
    if seasons < 1 or seasons > MAX_SEASONS:
        raise ProtectedMultiSeasonSoakError(f"--seasons must be between 1 and {MAX_SEASONS}.")

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_live_start_v1 as live_api
    import franchise_opening_regular_season_transition_v1 as opening_api
    import franchise_completed_season_contract_closeout_v1 as closeout_api
    import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
    import franchise_draft_engine_v1 as draft_api
    import franchise_cpu_post_draft_roster_trim_live_v1 as trim_api
    import franchise_season_boundary_durable_transition_v1 as boundary_api
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_full_reset_v1 import build_starting_franchise
    from mutable_league_state_v1 import validate_state
    from regular_season_simulation_controller_v1 import SimulationScope, simulate_regular_season_scope
    from simulation_postseason_v1 import FranchiseSimulationPolicy, PostseasonSimulationScope, advance_postseason, initialize_postseason
    from career_lifecycle_transition_adapter_v1 import (
        build_season_transition_preview,
        commit_season_transition_preview,
    )
    from regular_season_schedule_v1 import LEAGUE_GAME_COUNT, generate_regular_season_schedule, install_regular_season_schedule
    from simulation_league_state_v1 import validate_simulation_league_state
    from franchise_offseason_market_season_v1 import completed_season_closeout_applied
    from franchise_staff_system_v1 import STAFF_SYSTEM_VERSION, ensure_franchise_staff_state

    freeze = _validate_release_freeze()
    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = _checkpoint_family_hashes(active_primary)
    run_root = RUNS / f"r{_stamp()}"
    temp_primary = run_root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    run_root.mkdir(parents=True, exist_ok=False)

    checks: dict[str, bool] = {}
    season_reports: list[dict[str, Any]] = []
    failure = ""
    interrupted = False
    report: dict[str, Any] = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "requested_seasons": seasons,
        "completed_seasons": 0,
        "passed": False,
        "checks": checks,
        "failed_checks": [],
        "error": "",
        "interrupted": False,
        "season_reports": season_reports,
        "details": {
            "active_checkpoint_path": str(active_primary),
            "active_checkpoint_family_before": active_before,
            "isolated_run_root": str(run_root),
            "isolated_checkpoint": str(temp_primary),
            "release_freeze": freeze,
        },
    }

    try:
        with _isolated_checkpoint_contract(temp_primary):
            runtime = load_runtime_data()
            source = build_starting_franchise(runtime)
            validate_simulation_league_state(source.simulation_state)
            validate_state(source.trade_state, runtime)
            preferences = {
                "protected_multi_season_soak_v1": True,
                "release_id": "live_2026_09_07_release_candidate_v1",
                "franchise_pref_controlled_teams": [],
            }
            checkpoint_api.save_franchise_checkpoint(
                source.simulation_state,
                source.trade_state,
                preferences=preferences,
                reason="protected-multi-season-soak-source",
                path=temp_primary,
                copy_payload=True,
                force_replace=True,
            )
            checks["isolated_source_checkpoint_created"] = temp_primary.is_file()

            live_api.commit_live_franchise_start(runtime, source.simulation_state, source.trade_state, preferences=preferences)
            live_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, "Frozen live start")
            checks["frozen_live_start_reloaded"] = _phase(live_cp.simulation_state) == "offseason"
            pristine_live_fp = _durability_fingerprint(live_cp.simulation_state, live_cp.trade_state)

            staff = ensure_franchise_staff_state(live_cp.simulation_state)
            staff_signature = _staff_signature(live_cp.simulation_state)
            staff_personnel_signature = _staff_personnel_signature(live_cp.simulation_state)
            checks["staff_initialized_once"] = bool(
                staff
                and len(getattr(staff, "teams", {}) or {}) == 30
                and staff_signature
                and staff_personnel_signature
            )
            live_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                live_cp.simulation_state,
                live_cp.trade_state,
                preferences=live_cp.preferences,
                reason="protected-multi-season-soak-staff-init",
            )
            checks["staff_initialization_survives_reload"] = expected == observed and _staff_signature(live_cp.simulation_state) == staff_signature

            clean_live_fp = _durability_fingerprint(live_cp.simulation_state, live_cp.trade_state)
            clean_live_copy = run_root / "live.pkl.gz"
            shutil.copy2(temp_primary, clean_live_copy)
            report["details"]["pristine_frozen_fingerprint"] = pristine_live_fp
            report["details"]["gameplay_fixture_fingerprint"] = clean_live_fp
            report["details"]["staff_signature_initial_full"] = staff_signature
            report["details"]["staff_personnel_signature"] = staff_personnel_signature

            opening_preview = opening_api.preview_opening_regular_season(live_cp.simulation_state, live_cp.trade_state)
            if not opening_preview.can_commit:
                raise ProtectedMultiSeasonSoakError("Frozen live start cannot open regular season: " + ", ".join(opening_preview.blockers))
            opening_api.commit_opening_regular_season_live(
                confirmation_token=opening_preview.confirmation_token,
                expected_fingerprint=opening_preview.source_fingerprint,
                recovery_directory=run_root / "o",
            )
            current_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, "Opening regular season")
            validate_simulation_league_state(current_cp.simulation_state)
            validate_state(current_cp.trade_state, runtime)
            checks["opening_regular_season_ready"] = (
                _phase(current_cp.simulation_state) == "regular_season"
                and len(current_cp.simulation_state.schedule) == LEAGUE_GAME_COUNT
            )

            for season_index in range(1, seasons + 1):
                source_season = str(current_cp.simulation_state.settings.season_label)
                season_dir = run_root / f"s{season_index:02d}_{source_season.replace('-', '')}"
                season_dir.mkdir(parents=True, exist_ok=True)
                srep: dict[str, Any] = {
                    "season_index": season_index,
                    "source_season": source_season,
                    "started_at_utc": _utc_now(),
                    "checks": {},
                    "durations_seconds": {},
                    "population_start": _population_metrics(current_cp.simulation_state),
                }
                season_reports.append(srep)
                _write_partial(report)

                _progress(season_index, seasons, source_season, "simulate 1,230-game regular season")
                t0 = time.perf_counter()
                completed_state, season_result = simulate_regular_season_scope(current_cp.simulation_state, scope=SimulationScope.REMAINDER)
                validate_simulation_league_state(completed_state)
                srep["durations_seconds"]["regular_season"] = round(time.perf_counter() - t0, 3)
                srep["checks"]["regular_season_complete"] = bool(
                    len(completed_state.completed_games) == LEAGUE_GAME_COUNT
                    and season_result.regular_season_complete
                    and int(season_result.remaining_games_after) == 0
                )
                season_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api, temp_primary, completed_state, current_cp.trade_state,
                    preferences=current_cp.preferences,
                    reason=f"protected-multi-season-{source_season}-regular-season-complete",
                )
                srep["checks"]["regular_season_roundtrip_exact"] = expected == observed
                srep["checks"]["standings_2460_team_games"] = sum(
                    int(getattr(s, "games_played", 0) or 0) for s in season_cp.simulation_state.standings.values()
                ) == 2460

                _progress(season_index, seasons, source_season, "postseason to champion")
                t0 = time.perf_counter()
                postseason_source = copy.deepcopy(season_cp.simulation_state)
                initialize_postseason(postseason_source)
                ps_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api, temp_primary, postseason_source, season_cp.trade_state,
                    preferences=season_cp.preferences,
                    reason=f"protected-multi-season-{source_season}-postseason-init",
                )
                srep["checks"]["postseason_initialization_roundtrip_exact"] = expected == observed
                champion_state, postseason_result = advance_postseason(
                    ps_cp.simulation_state,
                    scope=PostseasonSimulationScope.TO_CHAMPION,
                    controlled_teams=(),
                    policy=FranchiseSimulationPolicy.FREE_SIMULATION,
                    max_games=140,
                )
                champion = str(getattr(getattr(champion_state, "postseason_state", None), "champion", "") or "").strip()
                validate_simulation_league_state(champion_state)
                srep["checks"]["postseason_complete_with_champion"] = bool(
                    _postseason_stage(champion_state) == "complete"
                    and _phase(champion_state) == "offseason"
                    and champion
                    and str(postseason_result.champion or "").strip() == champion
                )
                champion_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api, temp_primary, champion_state, ps_cp.trade_state,
                    preferences=ps_cp.preferences,
                    reason=f"protected-multi-season-{source_season}-postseason-complete",
                )
                srep["checks"]["champion_roundtrip_exact"] = expected == observed
                srep["champion"] = champion
                srep["postseason_games"] = int(postseason_result.games_simulated)
                srep["durations_seconds"]["postseason"] = round(time.perf_counter() - t0, 3)

                _progress(season_index, seasons, source_season, "contract closeout + CPU Free Agency")
                t0 = time.perf_counter()
                closeout_result = closeout_api.commit_completed_season_contract_closeout_durably(
                    champion_cp.simulation_state,
                    champion_cp.trade_state,
                    preferences=champion_cp.preferences,
                    checkpoint_path=temp_primary,
                    recovery_directory=season_dir / "c",
                )
                closed = _checkpoint_or_raise(checkpoint_api, temp_primary, f"{source_season} closeout")
                validate_simulation_league_state(closed.simulation_state)
                validate_state(closed.trade_state, runtime)
                srep["checks"]["completed_season_closeout_applied"] = completed_season_closeout_applied(closed.simulation_state, source_season)
                srep["closeout_trade_revision_after"] = int(getattr(closeout_result, "trade_revision_after", 0) or 0)

                cpu_fa_signings = 0
                cpu_fa_rounds = 0
                for round_index in range(1, 7):
                    fa_source = _checkpoint_or_raise(checkpoint_api, temp_primary, f"{source_season} CPU FA round {round_index}")
                    roster_counts = [len(team_state.roster_player_ids) for team_state in fa_source.simulation_state.teams.values()]
                    minimum_required = int(getattr(fa_source.simulation_state.settings, "minimum_game_players", 8) or 8)
                    if roster_counts and min(roster_counts) >= minimum_required:
                        break
                    rr = cpu_fa_api.execute_cpu_free_agency_round_durably(
                        max_signings=15,
                        max_targets_per_team=8,
                        recovery_directory=season_dir / f"f{round_index}",
                    )
                    cpu_fa_rounds += 1
                    cpu_fa_signings += int(rr.committed_signing_count)
                    if int(rr.committed_signing_count) <= 0:
                        break
                fa_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, f"{source_season} CPU FA complete")
                validate_simulation_league_state(fa_cp.simulation_state)
                validate_state(fa_cp.trade_state, runtime)
                fa_pop = _population_metrics(fa_cp.simulation_state)
                minimum_required = int(getattr(fa_cp.simulation_state.settings, "minimum_game_players", 8) or 8)
                srep["checks"]["cpu_free_agency_reaches_roster_floor"] = fa_pop["minimum_roster"] >= minimum_required
                if not srep["checks"]["cpu_free_agency_reaches_roster_floor"]:
                    underfilled = {k:v for k,v in fa_pop["roster_counts"].items() if v < minimum_required}
                    raise ProtectedMultiSeasonSoakError(f"{source_season} CPU Free Agency exhausted below roster floor: {underfilled}")
                srep["cpu_free_agency"] = {
                    "rounds": cpu_fa_rounds,
                    "signings": cpu_fa_signings,
                    "minimum_roster_after": fa_pop["minimum_roster"],
                }
                srep["durations_seconds"]["closeout_and_free_agency"] = round(time.perf_counter() - t0, 3)

                _progress(season_index, seasons, source_season, "Draft + post-Draft trim")
                t0 = time.perf_counter()
                draft_api.initialize_draft_state(fa_cp.simulation_state, runtime, controlled_teams=(), class_strength=5)
                draft_api.conduct_lottery(fa_cp.simulation_state, runtime)
                draft_api.reveal_draft_class(fa_cp.simulation_state)
                draft_api.start_draft_night(fa_cp.simulation_state)
                drafted_count = draft_api.simulate_rest_of_draft(fa_cp.simulation_state, integrate=True)
                current_draft = draft_api.draft_state(fa_cp.simulation_state)
                if current_draft is None:
                    raise ProtectedMultiSeasonSoakError(f"{source_season} draft state disappeared.")
                order_count = len(current_draft.get("draft_order", []))
                draft_year = int(current_draft.get("draft_year", 0) or 0)
                srep["checks"]["draft_complete"] = bool(
                    draft_api.draft_is_complete(fa_cp.simulation_state)
                    and int(current_draft.get("current_pick_index", 0) or 0) == order_count
                    and drafted_count == order_count
                )
                expected_draft_size = EXPECTED_FORFEIT_DRAFT_SIZES.get(draft_year, 60)
                srep["checks"]["draft_size_matches_clippers_forfeiture_schedule"] = order_count == expected_draft_size
                srep["draft"] = {
                    "draft_year": draft_year,
                    "picks": order_count,
                    "expected_picks": expected_draft_size,
                    "prospects": len(current_draft.get("prospects", []) or []),
                }
                draft_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api, temp_primary, fa_cp.simulation_state, fa_cp.trade_state,
                    preferences=fa_cp.preferences,
                    reason=f"protected-multi-season-{source_season}-draft-complete",
                )
                srep["checks"]["draft_roundtrip_exact"] = expected == observed and draft_api.draft_is_complete(draft_cp.simulation_state)

                trim_source_fp = boundary_api.checkpoint_boundary_fingerprint(draft_cp)
                trim_result = trim_api.commit_atomic_cpu_post_draft_trim_live(
                    expected_source_fingerprint=trim_source_fp,
                    confirmation=trim_api.confirmation_token(draft_cp.simulation_state),
                    checkpoint_path=temp_primary,
                    recovery_directory=season_dir / "t",
                )
                trimmed = _checkpoint_or_raise(checkpoint_api, temp_primary, f"{source_season} post-Draft trim")
                validate_simulation_league_state(trimmed.simulation_state)
                validate_state(trimmed.trade_state, runtime)
                srep["checks"]["post_draft_trim_committed_or_unneeded"] = str(trim_result.status) in {"committed", "no_trim_required"}
                srep["durations_seconds"]["draft_and_trim"] = round(time.perf_counter() - t0, 3)

                _progress(season_index, seasons, source_season, "atomic boundary to next season")
                t0 = time.perf_counter()
                boundary_source_fp = boundary_api.checkpoint_boundary_fingerprint(trimmed)
                transition_preview = build_season_transition_preview(trimmed.simulation_state)
                transitioned, transition_result = commit_season_transition_preview(trimmed.simulation_state, transition_preview)
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
                    "adapter_version": lifecycle.get("adapter_version"),
                    "engine_version": lifecycle.get("career_lifecycle_version"),
                    "players_before": retirement_plan.get("players_before"),
                    "retirements": retirement_plan.get("retirement_count"),
                    "rostered_retirements": retirement_plan.get("rostered_retirements"),
                    "free_agent_retirements": retirement_plan.get("free_agent_retirements"),
                    "players_after_transition": lifecycle.get("players_after_transition"),
                }
                target_season = str(transition_preview["target_season"])
                rookies_activated = draft_api.activate_drafted_rookies_after_transition(transitioned, target_season)
                generated_schedule = generate_regular_season_schedule(transitioned, seed=transitioned.settings.random_seed)
                install_regular_season_schedule(transitioned, generated_schedule)
                validate_simulation_league_state(transitioned)
                boundary_api.commit_atomic_season_boundary_live(
                    transitioned,
                    expected_source_fingerprint=boundary_source_fp,
                    expected_target_season=target_season,
                    confirmation=boundary_api.confirmation_token(source_season, target_season),
                    checkpoint_path=temp_primary,
                    recovery_directory=season_dir / "b",
                )
                next_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, f"{target_season} boundary")
                validate_simulation_league_state(next_cp.simulation_state)
                validate_state(next_cp.trade_state, runtime)
                srep["checks"]["boundary_trade_registry_covers_non_synthetic_players"] = (
                    _trade_registry_covers_non_synthetic_players(
                        next_cp.simulation_state,
                        next_cp.trade_state,
                    )
                )
                boundary_checks = _validate_boundary_state(
                    next_cp.simulation_state,
                    target_season=target_season,
                    staff_personnel_signature=staff_personnel_signature,
                    staff_version=STAFF_SYSTEM_VERSION,
                )
                srep["checks"].update({f"boundary_{k}": v for k,v in boundary_checks.items()})
                boundary_staff = getattr(next_cp.simulation_state, "franchise_staff_state_v1", None)
                boundary_history = getattr(boundary_staff, "scouting_history", None)
                srep["staff"] = {
                    "version": str(getattr(boundary_staff, "version", "") or ""),
                    "season_label": str(getattr(boundary_staff, "season_label", "") or ""),
                    "personnel_signature": _staff_personnel_signature(next_cp.simulation_state),
                    "scouting_history_count": len(boundary_history) if isinstance(boundary_history, list) else -1,
                }
                srep["checks"]["completed_season_archived"] = any(
                    str(getattr(item, "season_label", "") or "") == source_season
                    for item in (getattr(next_cp.simulation_state, "season_history", []) or [])
                )
                srep["checks"]["drafted_rookies_activated"] = int(rookies_activated) > 0
                second_cp, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api, temp_primary, next_cp.simulation_state, next_cp.trade_state,
                    preferences=next_cp.preferences,
                    reason=f"protected-multi-season-{target_season}-second-roundtrip",
                )
                srep["checks"]["next_season_second_roundtrip_exact"] = expected == observed
                srep["target_season"] = target_season
                srep["rookies_activated"] = int(rookies_activated)
                srep["season_history_count"] = len(getattr(second_cp.simulation_state, "season_history", []) or [])
                srep["population_end"] = _population_metrics(second_cp.simulation_state)
                srep["durations_seconds"]["season_boundary"] = round(time.perf_counter() - t0, 3)
                srep["completed_at_utc"] = _utc_now()
                srep["passed"] = all(srep["checks"].values())

                if not srep["passed"]:
                    bad = [k for k,v in srep["checks"].items() if not v]
                    raise ProtectedMultiSeasonSoakError(f"{source_season} season checks failed: {bad}")

                season_snapshot = run_root / "cp" / f"{target_season.replace('-', '')}.pkl.gz"
                season_snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_primary, season_snapshot)
                srep["checkpoint_snapshot"] = str(season_snapshot)
                report["completed_seasons"] = season_index
                current_cp = second_cp
                _write_partial(report)
                _progress(season_index, seasons, source_season, f"PASS → {target_season}")

            checks["all_requested_seasons_completed"] = report["completed_seasons"] == seasons
            checks["all_season_reports_passed"] = len(season_reports) == seasons and all(bool(x.get("passed")) for x in season_reports)
            checks["staff_personnel_survived_all_seasons"] = (
                _staff_personnel_signature(current_cp.simulation_state) == staff_personnel_signature
            )
            checks["season_history_count_matches_soak_depth"] = len(getattr(current_cp.simulation_state, "season_history", []) or []) >= seasons

            if seasons >= 7:
                actual_forfeit_drafts = {
                    int(s["draft"]["draft_year"]): int(s["draft"]["picks"])
                    for s in season_reports
                    if int(s.get("draft", {}).get("draft_year", 0) or 0) in EXPECTED_FORFEIT_DRAFT_SIZES
                }
                checks["all_2029_2033_forfeiture_drafts_observed_as_59_picks"] = actual_forfeit_drafts == EXPECTED_FORFEIT_DRAFT_SIZES
                report["details"]["forfeiture_drafts_observed"] = actual_forfeit_drafts

            shutil.copy2(clean_live_copy, temp_primary)
            restored = _checkpoint_or_raise(checkpoint_api, temp_primary, "Frozen live-start restore")
            restored_fp = _durability_fingerprint(restored.simulation_state, restored.trade_state)
            checks["clean_frozen_live_start_restores_exactly"] = restored_fp == clean_live_fp
            checks["restored_fixture_returns_to_2026_27_offseason"] = (
                str(restored.simulation_state.settings.season_label) == "2026-27" and _phase(restored.simulation_state) == "offseason"
            )

    except KeyboardInterrupt:
        interrupted = True
        failure = "KeyboardInterrupt: soak interrupted by user"
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        report["details"]["exception_traceback"] = traceback.format_exc()
    finally:
        active_after = _checkpoint_family_hashes(active_primary)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        report["details"]["active_checkpoint_family_after"] = active_after

    failed = [name for name, passed in checks.items() if not passed]
    for srep in season_reports:
        for name, passed in (srep.get("checks") or {}).items():
            if not passed:
                failed.append(f"season_{srep.get('season_index')}_{srep.get('source_season')}::{name}")
    if failure and not interrupted:
        failed.append("protected_multi_season_soak_raised")

    report["generated_at_utc"] = _utc_now()
    report["interrupted"] = interrupted
    report["error"] = failure
    report["failed_checks"] = failed
    report["passed"] = not failed and not interrupted and report["completed_seasons"] == seasons

    if report["passed"] and not keep_artifacts:
        shutil.rmtree(run_root, ignore_errors=True)
        report["details"]["isolated_artifacts_removed_after_pass"] = True
    else:
        report["details"]["isolated_artifacts_preserved"] = str(run_root)
    _write_partial(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated multi-season franchise lifecycle soak without touching the active save.")
    parser.add_argument("--seasons", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    print("FRANCHISE PROTECTED MULTI-SEASON SOAK V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Active franchise mutation: FORBIDDEN")
    print(f"Requested complete seasons: {args.seasons}")
    print("Progress is printed at every major lifecycle stage.")
    print()
    started = time.perf_counter()
    report = run_soak(seasons=args.seasons, keep_artifacts=args.keep_artifacts)
    elapsed = round(time.perf_counter() - started, 3)
    report["duration_seconds"] = elapsed
    _write_partial(report)

    print()
    print("SOAK SUMMARY")
    for s in report["season_reports"]:
        print(
            f"  Season {s.get('season_index')}: {s.get('source_season')} -> {s.get('target_season', '?')} · "
            f"champion={s.get('champion', '?')} · draft={s.get('draft', {}).get('picks', '?')} picks · "
            f"{'PASS' if s.get('passed') else 'FAIL'}"
        )
    print(f"Completed seasons: {report['completed_seasons']}/{report['requested_seasons']}")
    print(f"Report: {OUTPUT}")
    print(f"Elapsed: {elapsed:.3f}s")
    if report["passed"]:
        print("FRANCHISE PROTECTED MULTI-SEASON SOAK V1 PASSED")
        return 0
    if report.get("interrupted"):
        print("FRANCHISE PROTECTED MULTI-SEASON SOAK V1 INTERRUPTED")
        print("Isolated artifacts and partial report were preserved. Active franchise safety was still verified.")
        return 130
    print("FRANCHISE PROTECTED MULTI-SEASON SOAK V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report["failed_checks"]:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
