from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "outputs" / "franchise_protected_lifecycle_boundary_regression_v1.json"
RUNS = ROOT / "outputs" / "protected_lifecycle_boundary_regression_v1"
VERSION = "franchise-protected-lifecycle-boundary-regression-v1.2-2026-09-10"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _durability_fingerprint,
    _isolated_checkpoint_contract,
    _save_and_assert_roundtrip,
    _validate_release_freeze,
)


class ProtectedLifecycleBoundaryRegressionError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw)).strip().lower()


def _postseason_stage(state: Any) -> str:
    ps = getattr(state, "postseason_state", None)
    raw = getattr(ps, "stage", "") if ps is not None else ""
    return str(getattr(raw, "value", raw)).strip().lower()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _staff_signature(state: Any) -> str:
    staff = getattr(state, "franchise_staff_state_v1", None)
    if staff is None:
        return ""
    encoded = json.dumps(
        _jsonable(staff),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checkpoint_or_raise(checkpoint_api: Any, path: Path, label: str) -> Any:
    cp = checkpoint_api.load_franchise_checkpoint(path=path, allow_backup=False)
    if cp is None:
        raise ProtectedLifecycleBoundaryRegressionError(f"{label} checkpoint did not reload.")
    return cp


def run_regression(*, keep_artifacts: bool = False) -> dict[str, Any]:
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
    from regular_season_simulation_controller_v1 import (
        SimulationScope,
        simulate_regular_season_scope,
    )
    from simulation_postseason_v1 import (
        FranchiseSimulationPolicy,
        PostseasonSimulationScope,
        advance_postseason,
        initialize_postseason,
    )
    from career_lifecycle_transition_adapter_v1 import (
        build_season_transition_preview,
        commit_season_transition_preview,
    )
    from regular_season_schedule_v1 import (
        LEAGUE_GAME_COUNT,
        generate_regular_season_schedule,
        install_regular_season_schedule,
    )
    from simulation_league_state_v1 import validate_simulation_league_state
    from franchise_offseason_market_season_v1 import completed_season_closeout_applied
    from franchise_staff_system_v1 import (
        STAFF_STATE_ATTRIBUTE,
        STAFF_SYSTEM_VERSION,
        ensure_franchise_staff_state,
    )

    freeze = _validate_release_freeze()
    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = _checkpoint_family_hashes(active_primary)

    run_root = RUNS / f"run_{_stamp()}"
    temp_primary = run_root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    run_root.mkdir(parents=True, exist_ok=False)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {
        "version": VERSION,
        "started_at_utc": _utc_now(),
        "active_checkpoint_path": str(active_primary),
        "active_checkpoint_family_before": active_before,
        "isolated_run_root": str(run_root),
        "isolated_checkpoint": str(temp_primary),
        "release_freeze": freeze,
    }
    failure = ""

    try:
        with _isolated_checkpoint_contract(temp_primary):
            runtime = load_runtime_data()
            source = build_starting_franchise(runtime)
            validate_simulation_league_state(source.simulation_state)
            validate_state(source.trade_state, runtime)
            preferences = {
                "protected_lifecycle_boundary_regression_v1": True,
                "release_id": "live_2026_09_07_release_candidate_v1",
                "franchise_pref_controlled_teams": [],
            }
            checkpoint_api.save_franchise_checkpoint(
                source.simulation_state,
                source.trade_state,
                preferences=preferences,
                reason="protected-lifecycle-source-fixture",
                path=temp_primary,
                copy_payload=True,
                force_replace=True,
            )
            checks["isolated_source_checkpoint_created"] = temp_primary.is_file()

            live_result = live_api.commit_live_franchise_start(
                runtime,
                source.simulation_state,
                source.trade_state,
                preferences=preferences,
            )
            live_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, "Frozen live start")
            validate_simulation_league_state(live_cp.simulation_state)
            validate_state(live_cp.trade_state, runtime)
            checks["frozen_live_start_reloaded"] = True
            checks["live_start_is_opening_offseason"] = _phase(live_cp.simulation_state) == "offseason"
            pristine_live_fp = _durability_fingerprint(live_cp.simulation_state, live_cp.trade_state)

            # Mirror the real Franchise Mode page. The UI initializes deterministic
            # staff immediately after loading state and before offseason actions.
            # The headless regression must do the same before asking Staff to
            # survive a full season boundary.
            initialized_staff = ensure_franchise_staff_state(live_cp.simulation_state)
            staff_source_signature = _staff_signature(live_cp.simulation_state)
            checks["staff_initialized_for_gameplay_fixture"] = bool(
                initialized_staff
                and staff_source_signature
                and len(getattr(initialized_staff, "teams", {}) or {}) == 30
                and str(getattr(initialized_staff, "version", "") or "") == STAFF_SYSTEM_VERSION
            )
            live_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                live_cp.simulation_state,
                live_cp.trade_state,
                preferences=live_cp.preferences,
                reason="protected-lifecycle-staff-initialized",
            )
            checks["staff_initialization_survives_reload"] = bool(
                expected == observed
                and getattr(live_cp.simulation_state, STAFF_STATE_ATTRIBUTE, None) is not None
                and _staff_signature(live_cp.simulation_state) == staff_source_signature
            )

            clean_live_fp = _durability_fingerprint(live_cp.simulation_state, live_cp.trade_state)
            clean_live_copy = run_root / "clean_frozen_live_start.pkl.gz"
            shutil.copy2(temp_primary, clean_live_copy)
            details["live_start"] = {
                "result": _jsonable(live_result),
                "pristine_frozen_fingerprint": pristine_live_fp,
                "gameplay_fixture_fingerprint": clean_live_fp,
                "staff_system_version": STAFF_SYSTEM_VERSION,
                "staff_signature": staff_source_signature,
                "staff_team_count": len(getattr(initialized_staff, "teams", {}) or {}),
            }

            opening_preview = opening_api.preview_opening_regular_season(
                live_cp.simulation_state,
                live_cp.trade_state,
            )
            checks["opening_preview_is_commit_ready"] = bool(opening_preview.can_commit)
            if not opening_preview.can_commit:
                raise ProtectedLifecycleBoundaryRegressionError(
                    "Frozen live start cannot open the regular season: " + ", ".join(opening_preview.blockers)
                )
            opening_result = opening_api.commit_opening_regular_season_live(
                confirmation_token=opening_preview.confirmation_token,
                expected_fingerprint=opening_preview.source_fingerprint,
                recovery_directory=run_root / "opening_recovery",
            )
            opened = _checkpoint_or_raise(checkpoint_api, temp_primary, "Opening regular season")
            validate_simulation_league_state(opened.simulation_state)
            checks["opening_regular_season_reloaded"] = _phase(opened.simulation_state) == "regular_season"
            checks["opening_schedule_has_1230_games"] = len(opened.simulation_state.schedule) == LEAGUE_GAME_COUNT
            details["opening_transition"] = _jsonable(opening_result)

            # Complete the entire regular season transactionally, then persist it.
            season_started = time.perf_counter()
            completed_state, season_result = simulate_regular_season_scope(
                opened.simulation_state,
                scope=SimulationScope.REMAINDER,
            )
            validate_simulation_league_state(completed_state)
            checks["regular_season_simulated_all_1230_games"] = (
                len(completed_state.completed_games) == LEAGUE_GAME_COUNT
                and bool(season_result.regular_season_complete)
                and int(season_result.remaining_games_after) == 0
            )
            season_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                completed_state,
                opened.trade_state,
                preferences=opened.preferences,
                reason="protected-lifecycle-regular-season-complete",
            )
            checks["regular_season_complete_survives_reload"] = expected == observed
            checks["standings_total_2460_team_games_after_reload"] = sum(
                int(getattr(s, "games_played", 0) or 0)
                for s in season_cp.simulation_state.standings.values()
            ) == 2460
            details["regular_season"] = {
                "duration_seconds": round(time.perf_counter() - season_started, 3),
                "games_simulated": int(season_result.games_simulated),
                "completed_games": len(season_cp.simulation_state.completed_games),
            }

            # Initialize the postseason and prove the bracket itself is durable.
            postseason_source = copy.deepcopy(season_cp.simulation_state)
            initialized_ps = initialize_postseason(postseason_source)
            checks["postseason_initialized"] = _postseason_stage(postseason_source) in {"play_in_opening", "first_round"}
            postseason_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                postseason_source,
                season_cp.trade_state,
                preferences=season_cp.preferences,
                reason="protected-lifecycle-postseason-initialized",
            )
            checks["postseason_initialization_survives_reload"] = expected == observed

            postseason_started = time.perf_counter()
            champion_state, postseason_result = advance_postseason(
                postseason_cp.simulation_state,
                scope=PostseasonSimulationScope.TO_CHAMPION,
                controlled_teams=(),
                policy=FranchiseSimulationPolicy.FREE_SIMULATION,
                max_games=140,
            )
            validate_simulation_league_state(champion_state)
            champion = str(getattr(getattr(champion_state, "postseason_state", None), "champion", "") or "").strip()
            checks["postseason_reaches_champion"] = (
                _postseason_stage(champion_state) == "complete"
                and _phase(champion_state) == "offseason"
                and bool(champion)
                and str(postseason_result.champion or "").strip() == champion
            )
            champion_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                champion_state,
                postseason_cp.trade_state,
                preferences=postseason_cp.preferences,
                reason="protected-lifecycle-postseason-complete",
            )
            checks["completed_postseason_survives_reload"] = expected == observed
            checks["champion_survives_reload"] = str(
                getattr(getattr(champion_cp.simulation_state, "postseason_state", None), "champion", "") or ""
            ).strip() == champion
            details["postseason"] = {
                "duration_seconds": round(time.perf_counter() - postseason_started, 3),
                "games_simulated": int(postseason_result.games_simulated),
                "champion": champion,
                "stage": _postseason_stage(champion_cp.simulation_state),
            }

            # Apply the authoritative completed-season contract closeout durably.
            source_season = str(champion_cp.simulation_state.settings.season_label)
            closeout_result = closeout_api.commit_completed_season_contract_closeout_durably(
                champion_cp.simulation_state,
                champion_cp.trade_state,
                preferences=champion_cp.preferences,
                checkpoint_path=temp_primary,
                recovery_directory=run_root / "closeout_recovery",
            )
            closed = _checkpoint_or_raise(checkpoint_api, temp_primary, "Completed-season closeout")
            validate_simulation_league_state(closed.simulation_state)
            validate_state(closed.trade_state, runtime)
            checks["completed_season_closeout_survives_reload"] = completed_season_closeout_applied(
                closed.simulation_state,
                source_season,
            )
            checks["closeout_trade_revision_matches_reload"] = int(
                getattr(closed.trade_state, "state_revision", -1) or -1
            ) == int(closeout_result.trade_revision_after)
            details["contract_closeout"] = _jsonable(closeout_result)
            # Avoid embedding deep copied states from the result in the JSON report.
            if isinstance(details["contract_closeout"], dict):
                details["contract_closeout"].pop("simulation_state", None)
                details["contract_closeout"].pop("trade_state", None)

            # Exercise the canonical Free Agency stage before the Draft.  The previous
            # V1.0 harness skipped this stage entirely, which could leave legitimate
            # offseason rosters below the simulator's game-ready floor and create an
            # artificial preseason failure.  All teams are CPU-controlled in this
            # protected fixture, so run bounded durable CPU FA rounds until every team
            # is at the minimum game-player floor or the market has no further action.
            cpu_fa_rounds: list[dict[str, Any]] = []
            cpu_fa_signings = 0
            cpu_fa_started = time.perf_counter()
            for round_index in range(1, 7):
                fa_source = _checkpoint_or_raise(
                    checkpoint_api, temp_primary, f"CPU Free Agency round {round_index} source"
                )
                roster_counts_before = {
                    team: len(team_state.roster_player_ids)
                    for team, team_state in fa_source.simulation_state.teams.items()
                }
                minimum_required = int(
                    getattr(fa_source.simulation_state.settings, "minimum_game_players", 8) or 8
                )
                if roster_counts_before and min(roster_counts_before.values()) >= minimum_required:
                    break

                round_result = cpu_fa_api.execute_cpu_free_agency_round_durably(
                    max_signings=15,
                    max_targets_per_team=8,
                    recovery_directory=run_root / f"cpu_free_agency_round_{round_index}_recovery",
                )
                cpu_fa_rounds.append(_jsonable(round_result))
                cpu_fa_signings += int(round_result.committed_signing_count)
                if int(round_result.committed_signing_count) <= 0:
                    break

            fa_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, "CPU Free Agency stage")
            validate_simulation_league_state(fa_cp.simulation_state)
            validate_state(fa_cp.trade_state, runtime)
            roster_counts_after_fa = {
                team: len(team_state.roster_player_ids)
                for team, team_state in fa_cp.simulation_state.teams.items()
            }
            minimum_required = int(
                getattr(fa_cp.simulation_state.settings, "minimum_game_players", 8) or 8
            )
            minimum_after_fa = min(roster_counts_after_fa.values()) if roster_counts_after_fa else 0
            checks["cpu_free_agency_stage_executed"] = True
            checks["cpu_free_agency_state_survives_reload"] = _phase(fa_cp.simulation_state) == "offseason"
            checks["cpu_free_agency_reaches_game_roster_floor_before_draft"] = (
                minimum_after_fa >= minimum_required
            )
            details["cpu_free_agency"] = {
                "duration_seconds": round(time.perf_counter() - cpu_fa_started, 3),
                "rounds_executed": len(cpu_fa_rounds),
                "committed_signings": cpu_fa_signings,
                "minimum_required": minimum_required,
                "minimum_roster_after": minimum_after_fa,
                "roster_counts_after": dict(sorted(roster_counts_after_fa.items())),
                "round_results": cpu_fa_rounds,
            }
            if minimum_after_fa < minimum_required:
                underfilled = {
                    team: count
                    for team, count in sorted(roster_counts_after_fa.items())
                    if count < minimum_required
                }
                raise ProtectedLifecycleBoundaryRegressionError(
                    "Canonical CPU Free Agency exhausted before every CPU roster reached "
                    f"the game-ready floor of {minimum_required}: {underfilled}"
                )

            # Continue from the exact durable post-Free-Agency state.
            closed = fa_cp

            # Run a complete all-CPU Draft and checkpoint the resulting class.
            draft_api.initialize_draft_state(closed.simulation_state, runtime, controlled_teams=(), class_strength=5)
            draft_api.conduct_lottery(closed.simulation_state, runtime)
            draft_api.reveal_draft_class(closed.simulation_state)
            draft_api.start_draft_night(closed.simulation_state)
            drafted_count = draft_api.simulate_rest_of_draft(closed.simulation_state, integrate=True)
            current_draft = draft_api.draft_state(closed.simulation_state)
            if current_draft is None:
                raise ProtectedLifecycleBoundaryRegressionError("Draft state disappeared before persistence.")
            order_count = len(current_draft.get("draft_order", []))
            checks["full_draft_completes"] = (
                draft_api.draft_is_complete(closed.simulation_state)
                and current_draft.get("phase") == "draft_complete"
                and int(current_draft.get("current_pick_index", 0) or 0) == order_count
                and drafted_count == order_count
            )
            draft_cp, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                closed.simulation_state,
                closed.trade_state,
                preferences=closed.preferences,
                reason="protected-lifecycle-draft-complete",
            )
            checks["draft_complete_survives_reload"] = expected == observed and draft_api.draft_is_complete(draft_cp.simulation_state)
            reloaded_draft = draft_api.draft_state(draft_cp.simulation_state) or {}
            checks["draft_pick_count_survives_reload"] = int(reloaded_draft.get("current_pick_index", 0) or 0) == order_count
            details["draft"] = {
                "draft_year": int(reloaded_draft.get("draft_year", 0) or 0),
                "picks_completed": int(reloaded_draft.get("current_pick_index", 0) or 0),
                "draft_order_count": order_count,
                "prospects": len(reloaded_draft.get("prospects", []) or []),
            }

            # Run the certified post-Draft CPU roster trim on the isolated checkpoint.
            trim_source_fp = boundary_api.checkpoint_boundary_fingerprint(draft_cp)
            trim_result = trim_api.commit_atomic_cpu_post_draft_trim_live(
                expected_source_fingerprint=trim_source_fp,
                confirmation=trim_api.confirmation_token(draft_cp.simulation_state),
                checkpoint_path=temp_primary,
                recovery_directory=run_root / "post_draft_trim_recovery",
            )
            trimmed = _checkpoint_or_raise(checkpoint_api, temp_primary, "Post-Draft CPU trim")
            validate_simulation_league_state(trimmed.simulation_state)
            validate_state(trimmed.trade_state, runtime)
            checks["post_draft_trim_not_blocked"] = str(trim_result.status) in {"committed", "no_trim_required"}
            checks["post_draft_trim_survives_reload"] = draft_api.draft_is_complete(trimmed.simulation_state)
            details["post_draft_trim"] = _jsonable(trim_result)

            # Build the deterministic next-season state, activate drafted rookies,
            # install its 1,230-game schedule, then commit it atomically.
            boundary_source_fp = boundary_api.checkpoint_boundary_fingerprint(trimmed)
            transition_preview = build_season_transition_preview(trimmed.simulation_state)
            transitioned, transition_result = commit_season_transition_preview(
                trimmed.simulation_state,
                transition_preview,
            )
            lifecycle = dict(transition_preview.get("career_lifecycle", {}) or {})
            retirement_plan = dict(lifecycle.get("retirement_plan", {}) or {})
            checks["career_lifecycle_adapter_active"] = bool(
                lifecycle.get("adapter_version")
                and lifecycle.get("career_lifecycle_version")
                and not retirement_plan.get("skipped_because_no_completed_season", True)
            )
            checks["retirement_population_matches_preview"] = (
                len(transitioned.players)
                == int(lifecycle.get("players_after_transition", -1))
            )
            details["career_lifecycle"] = {
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
            generated_schedule = generate_regular_season_schedule(
                transitioned,
                seed=transitioned.settings.random_seed,
            )
            install_regular_season_schedule(transitioned, generated_schedule)
            validate_simulation_league_state(transitioned)
            checks["next_season_candidate_has_1230_games"] = (
                str(transitioned.settings.season_label) == target_season
                and _phase(transitioned) == "regular_season"
                and len(transitioned.schedule) == LEAGUE_GAME_COUNT
            )
            boundary_result = boundary_api.commit_atomic_season_boundary_live(
                transitioned,
                expected_source_fingerprint=boundary_source_fp,
                expected_target_season=target_season,
                confirmation=boundary_api.confirmation_token(source_season, target_season),
                checkpoint_path=temp_primary,
                recovery_directory=run_root / "season_boundary_recovery",
            )
            next_cp = _checkpoint_or_raise(checkpoint_api, temp_primary, "Next-season boundary")
            validate_simulation_league_state(next_cp.simulation_state)
            validate_state(next_cp.trade_state, runtime)
            checks["next_season_atomic_commit_survives_reload"] = (
                str(next_cp.simulation_state.settings.season_label) == target_season
                and _phase(next_cp.simulation_state) == "regular_season"
                and len(next_cp.simulation_state.schedule) == LEAGUE_GAME_COUNT
            )
            checks["completed_season_archived"] = any(
                str(getattr(item, "season_label", "") or "") == source_season
                for item in (getattr(next_cp.simulation_state, "season_history", []) or [])
            )
            checks["drafted_rookies_activated"] = int(rookies_activated) > 0
            final_staff = getattr(next_cp.simulation_state, STAFF_STATE_ATTRIBUTE, None)
            final_staff_signature = _staff_signature(next_cp.simulation_state)
            checks["staff_state_survives_full_boundary"] = bool(
                final_staff is not None
                and len(getattr(final_staff, "teams", {}) or {}) == 30
                and str(getattr(final_staff, "version", "") or "") == STAFF_SYSTEM_VERSION
                and final_staff_signature == staff_source_signature
            )
            details["staff_boundary"] = {
                "system_version": STAFF_SYSTEM_VERSION,
                "source_signature": staff_source_signature,
                "target_signature": final_staff_signature,
                "target_team_count": len(getattr(final_staff, "teams", {}) or {}) if final_staff is not None else 0,
            }
            next_roundtrip, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                next_cp.simulation_state,
                next_cp.trade_state,
                preferences=next_cp.preferences,
                reason="protected-lifecycle-next-season-roundtrip",
            )
            checks["next_season_second_roundtrip_exact"] = expected == observed
            details["season_boundary"] = {
                "transition_result": _jsonable(transition_result),
                "durable_result": _jsonable(boundary_result),
                "source_season": source_season,
                "target_season": target_season,
                "rookies_activated": int(rookies_activated),
                "season_history_count": len(getattr(next_roundtrip.simulation_state, "season_history", []) or []),
            }

            # Exact restore to the frozen live-start semantic fixture.
            shutil.copy2(clean_live_copy, temp_primary)
            restored = _checkpoint_or_raise(checkpoint_api, temp_primary, "Frozen live-start restore")
            restored_fp = _durability_fingerprint(restored.simulation_state, restored.trade_state)
            checks["clean_frozen_live_start_restores_exactly"] = restored_fp == clean_live_fp
            checks["restored_fixture_returns_to_2026_27_offseason"] = (
                str(restored.simulation_state.settings.season_label) == "2026-27"
                and _phase(restored.simulation_state) == "offseason"
            )
            details["restored_fingerprint"] = restored_fp

    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        active_after = _checkpoint_family_hashes(active_primary)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        details["active_checkpoint_family_after"] = active_after

    failed = [name for name, passed in checks.items() if not passed]
    if failure:
        failed.append("protected_lifecycle_boundary_regression_raised")

    report = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "error": failure,
        "details": details,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if report["passed"] and not keep_artifacts:
        shutil.rmtree(run_root, ignore_errors=True)
        report["details"]["isolated_artifacts_removed_after_pass"] = True
    else:
        report["details"]["isolated_artifacts_preserved"] = str(run_root)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen Sep. 7 franchise through a complete isolated regular season, "
            "postseason, completed-season closeout, Draft, certified post-Draft trim, and "
            "atomic next-season opening with checkpoint reloads at every major lifecycle boundary."
        )
    )
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    print("FRANCHISE PROTECTED LIFECYCLE BOUNDARY REGRESSION V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Active franchise mutation: FORBIDDEN")
    print("Scope: full 2026-27 season -> 2027-28 opening")
    print()
    started = time.perf_counter()
    report = run_regression(keep_artifacts=args.keep_artifacts)
    elapsed = round(time.perf_counter() - started, 3)
    report["duration_seconds"] = elapsed
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print()
    print(f"Report: {OUTPUT}")
    print(f"Elapsed: {elapsed:.3f}s")
    if report["passed"]:
        print("FRANCHISE PROTECTED LIFECYCLE BOUNDARY REGRESSION V1 PASSED")
        return 0
    print("FRANCHISE PROTECTED LIFECYCLE BOUNDARY REGRESSION V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report["failed_checks"]:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
