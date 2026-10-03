from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from career_lifecycle_transition_adapter_v1 import (
    build_season_transition_preview,
    commit_season_transition_preview,
)
from franchise_completed_season_contract_closeout_v1 import (
    COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
    build_completed_season_contract_closeout_candidate,
)
from franchise_cpu_post_draft_roster_trim_live_v1 import (
    LIVE_TRIM_VERSION,
    build_atomic_cpu_post_draft_trim_candidate,
)
from franchise_draft_engine_v1 import (
    DRAFT_ENGINE_VERSION,
    activate_drafted_rookies_after_transition,
    conduct_lottery,
    draft_is_complete,
    draft_state,
    initialize_draft_state,
    reveal_draft_class,
    start_draft_night,
)
from franchise_free_agency_cpu_execution_v1 import (
    CPU_FREE_AGENCY_EXECUTION_VERSION,
    CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET,
    build_cpu_free_agency_round_candidate,
    cpu_sustainable_roster_deficits,
)
from franchise_offseason_market_season_v1 import completed_season_closeout_applied
from franchise_season_boundary_durable_transition_v1 import (
    SEASON_BOUNDARY_DURABLE_TRANSITION_VERSION,
    build_atomic_season_boundary_candidate,
    checkpoint_boundary_fingerprint,
)
from freeform_trade_machine_engine_v3 import load_runtime_data
from regular_season_schedule_v1 import (
    LEAGUE_GAME_COUNT,
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
from simulation_league_state_v1 import validate_simulation_league_state
from simulation_postseason_v1 import (
    POSTSEASON_VERSION,
    PostseasonSimulationScope,
    advance_postseason,
    get_postseason_state,
    initialize_postseason,
    postseason_seed_rows,
    postseason_series_rows,
)


SEASON_LIFECYCLE_FOUNDATION_VERSION = (
    "v3-season-lifecycle-foundation-batch-15-cpu-free-agency-plus-15-1-postseason-continuity-v15.1.0-2026-10-03"
)

ACTION_POSTSEASON_INITIALIZE = "postseason_initialize"
ACTION_POSTSEASON_SIMULATE = "postseason_simulate"
ACTION_CONTRACT_CLOSEOUT = "contract_closeout"
ACTION_CPU_FREE_AGENCY = "cpu_free_agency"
ACTION_DRAFT_LOTTERY = "draft_lottery"
ACTION_DRAFT_NIGHT = "draft_night"
ACTION_NEXT_SEASON = "next_season"
SUPPORTED_ACTIONS = (
    ACTION_POSTSEASON_INITIALIZE,
    ACTION_POSTSEASON_SIMULATE,
    ACTION_CONTRACT_CLOSEOUT,
    ACTION_CPU_FREE_AGENCY,
    ACTION_DRAFT_LOTTERY,
    ACTION_DRAFT_NIGHT,
    ACTION_NEXT_SEASON,
)


@dataclass(frozen=True)
class V3LifecycleActionCandidate:
    action: str
    state: Any
    trade_state: Any
    preferences: dict[str, Any]
    source_fingerprint: str
    action_fingerprint: str
    source_season: str
    target_season: str
    detail: dict[str, Any]


class V3SeasonLifecycleError(RuntimeError):
    pass


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _postseason_stage(state: Any) -> str:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return ""
    raw = getattr(postseason, "stage", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _postseason_champion(state: Any) -> str:
    postseason = getattr(state, "postseason_state", None)
    return _clean(getattr(postseason, "champion", "")) if postseason is not None else ""


def _postseason_summary_payload(state: Any) -> dict[str, Any]:
    postseason = get_postseason_state(state, required=False)
    if postseason is None:
        return {
            "initialized": False,
            "stage": "",
            "champion": "",
            "runner_up": "",
            "completed_games": 0,
            "conference_champions": {},
            "east_seeds": [],
            "west_seeds": [],
            "series": [],
        }
    return {
        "initialized": True,
        "stage": _postseason_stage(state),
        "champion": _clean(getattr(postseason, "champion", "")),
        "runner_up": _clean(getattr(postseason, "runner_up", "")),
        "completed_games": len(getattr(postseason, "completed_games", {}) or {}),
        "conference_champions": _json_safe(
            getattr(postseason, "conference_champions", {}) or {}
        ),
        "east_seeds": _json_safe(postseason_seed_rows(state, "East")[:10]),
        "west_seeds": _json_safe(postseason_seed_rows(state, "West")[:10]),
        "series": _json_safe(postseason_series_rows(state)),
    }


def _draft_payload(state: Any) -> dict[str, Any]:
    current = draft_state(state)
    if not isinstance(current, dict):
        return {
            "initialized": False,
            "phase": "",
            "draft_year": None,
            "current_pick_index": 0,
            "pick_count": 0,
            "lottery_count": 0,
            "complete": False,
        }
    order = list(current.get("draft_order", []) or [])
    return {
        "initialized": True,
        "phase": _clean(current.get("phase")).lower(),
        "draft_year": current.get("draft_year"),
        "current_pick_index": int(current.get("current_pick_index", 0) or 0),
        "pick_count": len(order),
        "lottery_count": len(current.get("lottery_order", []) or []),
        "complete": bool(draft_is_complete(state)),
    }


def _schedule_payload(state: Any) -> dict[str, int]:
    schedule = dict(getattr(state, "schedule", {}) or {})
    completed = 0
    scheduled = 0
    for game in schedule.values():
        raw = getattr(game, "status", "")
        status = _clean(getattr(raw, "value", raw)).lower()
        if status == "completed":
            completed += 1
        elif status == "scheduled":
            scheduled += 1
    return {
        "total": len(schedule),
        "completed": completed,
        "scheduled": scheduled,
        "remaining": max(0, len(schedule) - completed),
    }


def _controlled_teams(checkpoint: Any) -> tuple[str, ...]:
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    found = {
        _clean(value).upper()
        for value in preferences.get("franchise_pref_controlled_teams", ()) or ()
        if _clean(value)
    }
    active = _clean(preferences.get("franchise_pref_active_team", "")).upper()
    if active:
        found.add(active)
    return tuple(sorted(found))


def _cpu_deficits(checkpoint: Any) -> tuple[tuple[Any, ...], ...]:
    state = checkpoint.simulation_state
    try:
        rows = cpu_sustainable_roster_deficits(state, _controlled_teams(checkpoint))
    except Exception:
        return ()
    return tuple(tuple(row) for row in rows)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _checkpoint_like(source: Any, state: Any, trade_state: Any) -> Any:
    return SimpleNamespace(
        simulation_state=state,
        trade_state=trade_state,
        preferences=copy.deepcopy(dict(getattr(source, "preferences", {}) or {})),
    )


def _source_fingerprint(checkpoint: Any) -> str:
    return checkpoint_boundary_fingerprint(checkpoint)


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _closeout_applied(state: Any) -> bool:
    season = _season(state)
    return bool(season and completed_season_closeout_applied(state, season))


def _next_action(checkpoint: Any) -> tuple[str, str, tuple[str, ...]]:
    state = checkpoint.simulation_state
    phase = _phase(state)
    schedule = _schedule_payload(state)

    # Keep ordinary in-season status independent of offseason-only helpers.
    # A regular-season checkpoint should never need Draft, closeout, or CPU-FA
    # machinery simply to render the read-only Season Lifecycle Center.
    if phase == "regular_season":
        if schedule["remaining"] > 0:
            return (
                "",
                "regular_season_in_progress",
                (f"{schedule['remaining']} regular-season games remain.",),
            )
        if not _postseason_stage(state):
            return (ACTION_POSTSEASON_INITIALIZE, "postseason_setup_ready", ())

    postseason_stage = _postseason_stage(state)
    if postseason_stage and postseason_stage != "complete":
        return (ACTION_POSTSEASON_SIMULATE, "postseason_in_progress", ())

    champion = _postseason_champion(state)
    if phase == "offseason" and postseason_stage == "complete" and champion:
        closeout = _closeout_applied(state)
        if not closeout:
            return (ACTION_CONTRACT_CLOSEOUT, "contract_closeout_pending", ())

        cpu_deficits = _cpu_deficits(checkpoint)
        if cpu_deficits:
            total = sum(int(row[2]) for row in cpu_deficits if len(row) >= 3)
            return (
                ACTION_CPU_FREE_AGENCY,
                "cpu_free_agency_pending",
                (
                    f"CPU roster construction is incomplete: {len(cpu_deficits)} team(s), {total} roster spot(s) below the sustainable target of {CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET}.",
                ),
            )

        draft = _draft_payload(state)
        draft_phase = draft["phase"]
        if draft_phase in {"season_scouting", "lottery_ready", "lottery_complete"}:
            return (ACTION_DRAFT_LOTTERY, "draft_lottery_ready", ())
        if draft_phase == "scouting":
            return (ACTION_DRAFT_NIGHT, "draft_night_ready", ())
        if draft_phase == "draft_in_progress":
            return (
                "",
                "draft_in_progress",
                ("Complete Draft Night through the Scouting & Draft Center.",),
            )
        if draft["complete"]:
            return (ACTION_NEXT_SEASON, "next_season_ready", ())
        if not draft["initialized"]:
            return (ACTION_DRAFT_LOTTERY, "draft_lottery_ready", ())

    return (
        "",
        "lifecycle_waiting",
        ("No certified automatic lifecycle action is available from the current state.",),
    )


def build_lifecycle_summary(checkpoint: Any) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None or trade_state is None:
        raise V3SeasonLifecycleError("V3 lifecycle summary requires simulation and trade state.")

    # This surface is intentionally diagnostic/read-only. Any helper that is
    # not required to load the checkpoint is allowed to degrade to a blocker
    # instead of crashing the whole Season page. Durable lifecycle candidates
    # remain strict and validate the complete league state before mutation.
    diagnostic_errors: list[str] = []

    state_validation_error = ""
    try:
        validate_simulation_league_state(state)
    except Exception as exc:
        state_validation_error = f"{type(exc).__name__}: {exc}"
        diagnostic_errors.append(state_validation_error)

    try:
        action, stage, blockers = _next_action(checkpoint)
    except Exception as exc:
        lifecycle_error = f"{type(exc).__name__}: {exc}"
        diagnostic_errors.append(lifecycle_error)
        action = ""
        stage = "state_validation_blocked"
        blockers = (
            "Current franchise state could not complete the read-only lifecycle status probe. " + lifecycle_error,
        )

    source_fingerprint = ""
    fingerprint_error = ""
    try:
        source_fingerprint = _source_fingerprint(checkpoint)
    except Exception as exc:
        fingerprint_error = f"{type(exc).__name__}: {exc}"
        diagnostic_errors.append(fingerprint_error)

    try:
        schedule = _schedule_payload(state)
    except Exception as exc:
        schedule_error = f"{type(exc).__name__}: {exc}"
        diagnostic_errors.append(schedule_error)
        schedule = {"total": 0, "completed": 0, "scheduled": 0, "remaining": 0}

    phase = _phase(state)

    # Draft/closeout/CPU-FA details are not needed to render an active regular
    # season. Avoid forcing those offseason-only systems to deserialize just to
    # show status. Outside the regular season, read them defensively.
    draft = {
        "initialized": False,
        "phase": "",
        "draft_year": None,
        "current_pick_index": 0,
        "pick_count": 0,
        "lottery_count": 0,
        "complete": False,
    }
    closeout_applied = False
    deficits: tuple[tuple[Any, ...], ...] = ()

    if phase != "regular_season":
        try:
            draft = _draft_payload(state)
        except Exception as exc:
            diagnostic_errors.append(f"{type(exc).__name__}: {exc}")
        try:
            closeout_applied = _closeout_applied(state)
        except Exception as exc:
            diagnostic_errors.append(f"{type(exc).__name__}: {exc}")
        deficits = _cpu_deficits(checkpoint)

    if diagnostic_errors:
        action = ""
        if stage not in {"regular_season_in_progress", "postseason_pending", "postseason_in_progress"}:
            stage = "state_validation_blocked"
        diagnostic_blocker = (
            "Lifecycle write actions are disabled until safety diagnostics pass. "
            + " | ".join(dict.fromkeys(diagnostic_errors))
        )
        blockers = tuple(blockers) + (diagnostic_blocker,)

    postseason_stage = _postseason_stage(state)
    timeline = [
        {
            "key": "regular_season",
            "label": "REGULAR SEASON",
            "status": "complete" if schedule["total"] and schedule["remaining"] == 0 else ("current" if phase == "regular_season" else "complete"),
        },
        {
            "key": "postseason",
            "label": "POSTSEASON",
            "status": (
                "complete"
                if postseason_stage == "complete"
                else (
                    "current"
                    if stage in {"postseason_setup_ready", "postseason_in_progress"}
                    else "locked"
                )
            ),
        },
        {
            "key": "closeout",
            "label": "CONTRACT CLOSEOUT",
            "status": "complete" if closeout_applied else ("current" if stage == "contract_closeout_pending" else "locked"),
        },
        {
            "key": "cpu_free_agency",
            "label": "CPU FREE AGENCY",
            "status": "complete" if closeout_applied and not deficits else ("current" if stage == "cpu_free_agency_pending" else "locked"),
        },
        {
            "key": "draft_lottery",
            "label": "DRAFT LOTTERY",
            "status": "complete" if draft["phase"] in {"scouting", "draft_in_progress", "draft_complete"} else ("current" if stage == "draft_lottery_ready" else "locked"),
        },
        {
            "key": "draft_night",
            "label": "DRAFT NIGHT",
            "status": "complete" if draft["complete"] else ("current" if stage in {"draft_night_ready", "draft_in_progress"} else "locked"),
        },
        {
            "key": "next_season",
            "label": "NEXT SEASON",
            "status": "current" if stage == "next_season_ready" else "locked",
        },
    ]

    return {
        "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "read_only": True,
        "active_v2_read_only": True,
        "working_save_write_performed": False,
        "source_fingerprint": source_fingerprint,
        "state_validation": {
            "valid": not bool(state_validation_error),
            "error": state_validation_error,
        },
        "fingerprint_validation": {
            "valid": not bool(fingerprint_error),
            "error": fingerprint_error,
        },
        "diagnostic_errors": list(dict.fromkeys(diagnostic_errors)),
        "season": {
            "label": _season(state),
            "phase": phase,
            "day_index": int(getattr(state, "current_day_index", 0) or 0),
        },
        "schedule": schedule,
        "postseason": _postseason_summary_payload(state),
        "closeout": {
            "applied": closeout_applied,
            "version": COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
        },
        "cpu_free_agency": {
            "version": CPU_FREE_AGENCY_EXECUTION_VERSION,
            "sustainable_target": CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET,
            "deficit_team_count": len(deficits),
            "total_deficit": sum(int(row[2]) for row in deficits if len(row) >= 3),
            "deficits": _json_safe(deficits),
        },
        "draft": draft,
        "stage": stage,
        "next_action": action,
        "next_action_label": {
            ACTION_POSTSEASON_INITIALIZE: "CREATE PLAYOFF BRACKET",
            ACTION_POSTSEASON_SIMULATE: "SIMULATE POSTSEASON",
            ACTION_CONTRACT_CLOSEOUT: "CLOSE OUT CONTRACTS",
            ACTION_CPU_FREE_AGENCY: "RUN CPU FREE AGENCY",
            ACTION_DRAFT_LOTTERY: "RUN DRAFT LOTTERY",
            ACTION_DRAFT_NIGHT: "OPEN DRAFT NIGHT",
            ACTION_NEXT_SEASON: "OPEN NEXT SEASON",
        }.get(action, "NO ACTION AVAILABLE"),
        "blockers": list(dict.fromkeys(blockers)),
        "timeline": timeline,
        "engine_versions": {
            "postseason": POSTSEASON_VERSION,
            "draft": DRAFT_ENGINE_VERSION,
            "post_draft_trim": LIVE_TRIM_VERSION,
            "season_boundary": SEASON_BOUNDARY_DURABLE_TRANSITION_VERSION,
            "closeout": COMPLETED_SEASON_CONTRACT_CLOSEOUT_VERSION,
            "cpu_free_agency": CPU_FREE_AGENCY_EXECUTION_VERSION,
        },
    }


def _require_action_available(checkpoint: Any, action: str) -> None:
    action = _clean(action).lower()
    if action not in SUPPORTED_ACTIONS:
        raise V3SeasonLifecycleError(f"Unsupported lifecycle action: {action or '<blank>'}.")
    expected, stage, blockers = _next_action(checkpoint)
    if expected != action:
        detail = "; ".join(blockers) if blockers else f"Current lifecycle stage is {stage}."
        raise V3SeasonLifecycleError(
            f"Lifecycle action '{action}' is not legal now. {detail}"
        )


def _candidate_fingerprint(
    checkpoint: Any,
    action: str,
    detail: Mapping[str, Any],
) -> str:
    return _fingerprint(
        {
            "version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
            "source_fingerprint": _source_fingerprint(checkpoint),
            "action": action,
            "season": _season(checkpoint.simulation_state),
            "detail": detail,
        }
    )


def build_lifecycle_action_candidate(
    checkpoint: Any,
    action: str,
    *,
    active_team: str = "",
    source_checkpoint_path: str | Path | None = None,
    source_checkpoint_sha256: str = "",
) -> V3LifecycleActionCandidate:
    action = _clean(action).lower()
    source_state = checkpoint.simulation_state

    # Write-side safety remains strict. Read-only summaries may surface an
    # invalid state, but no certified lifecycle mutation can be built from one.
    validate_simulation_league_state(source_state)
    _require_action_available(checkpoint, action)

    source_trade = checkpoint.trade_state
    preferences = copy.deepcopy(dict(getattr(checkpoint, "preferences", {}) or {}))
    source_season = _season(source_state)
    source_fp = _source_fingerprint(checkpoint)

    if action == ACTION_POSTSEASON_INITIALIZE:
        state = copy.deepcopy(source_state)
        trade_state = copy.deepcopy(source_trade)
        postseason = initialize_postseason(state)
        detail = {
            "status": "bracket_ready",
            "stage": _postseason_stage(state),
            "play_in_enabled": bool(getattr(state.settings, "play_in_enabled", False)),
            "east_seeds": _json_safe(postseason_seed_rows(state, "East")[:10]),
            "west_seeds": _json_safe(postseason_seed_rows(state, "West")[:10]),
            "scheduled_opening_games": len(
                [
                    game
                    for game in (getattr(postseason, "games", {}) or {}).values()
                    if _clean(getattr(getattr(game, "status", ""), "value", getattr(game, "status", ""))).lower()
                    == "scheduled"
                ]
            ),
        }
        target_season = source_season

    elif action == ACTION_POSTSEASON_SIMULATE:
        deterministic_seed = (
            int(getattr(getattr(source_state, "settings", None), "random_seed", 0) or 0)
            + int(getattr(source_state, "current_day_index", 0) or 0)
            + 15100
        )
        state, result = advance_postseason(
            source_state,
            scope=PostseasonSimulationScope.TO_CHAMPION,
            controlled_teams=(),
            policy="free_simulation",
            seed=deterministic_seed,
            max_games=140,
        )
        trade_state = copy.deepcopy(source_trade)
        postseason = get_postseason_state(state)
        if result.stopped_at_game_limit or _postseason_stage(state) != "complete":
            raise V3SeasonLifecycleError(
                "Postseason simulation did not reach a champion within the certified game limit."
            )
        if not _clean(getattr(postseason, "champion", "")):
            raise V3SeasonLifecycleError("Postseason simulation completed without a champion.")
        detail = {
            "status": "champion_crowned",
            "games_simulated": int(result.games_simulated),
            "stage_before": _clean(getattr(result.stage_before, "value", result.stage_before)),
            "stage_after": _clean(getattr(result.stage_after, "value", result.stage_after)),
            "champion": _clean(postseason.champion),
            "runner_up": _clean(postseason.runner_up),
            "conference_champions": _json_safe(postseason.conference_champions),
            "completed_postseason_games": len(postseason.completed_games),
            "simulation_seed": deterministic_seed,
        }
        target_season = source_season

    elif action == ACTION_CONTRACT_CLOSEOUT:
        result = build_completed_season_contract_closeout_candidate(source_state, source_trade)
        state = result.simulation_state
        trade_state = result.trade_state
        detail = {
            "status": result.status,
            "target_market_season": result.target_market_season,
            "contracts_decremented": result.contracts_decremented,
            "contracts_expired": result.contracts_expired,
            "trade_owners_released": result.trade_owners_released,
            "minimum_roster_after_closeout": result.minimum_roster_after_closeout,
            "draft_scouting_preserved": (
                _draft_payload(source_state)["phase"] == "season_scouting"
                and _draft_payload(state)["phase"] == "season_scouting"
            ),
        }
        target_season = source_season

    elif action == ACTION_CPU_FREE_AGENCY:
        if source_checkpoint_path is None or not _clean(source_checkpoint_sha256):
            raise V3SeasonLifecycleError(
                "CPU Free Agency requires the V3 working-save path and a fresh SHA-256 token."
            )
        deficits_before = _cpu_deficits(checkpoint)
        result, candidate_checkpoint = build_cpu_free_agency_round_candidate(
            checkpoint,
            source_checkpoint_path=source_checkpoint_path,
            source_checkpoint_sha256=source_checkpoint_sha256,
            max_signings=15,
            max_targets_per_team=8,
        )
        state = candidate_checkpoint.simulation_state
        trade_state = candidate_checkpoint.trade_state
        candidate_like = _checkpoint_like(checkpoint, state, trade_state)
        deficits_after = _cpu_deficits(candidate_like)
        if result.committed_signing_count < 1 and deficits_after:
            raise V3SeasonLifecycleError(
                "CPU Free Agency found no legal, player-accepted path for the remaining roster deficits: "
                + result.stop_reason
            )
        signings = [
            {
                "transaction_id": row.transaction_id,
                "player_id": row.player_id,
                "player_name": row.player_name,
                "team_abbreviation": row.team_abbreviation,
                "annual_salary": row.annual_salary,
                "years": row.years,
            }
            for row in result.signings
        ]
        detail = {
            "status": result.status,
            "committed_signing_count": result.committed_signing_count,
            "requested_max_signings": result.requested_max_signings,
            "stop_reason": result.stop_reason,
            "deficits_before": _json_safe(deficits_before),
            "deficits_after": _json_safe(deficits_after),
            "deficit_team_count_before": len(deficits_before),
            "deficit_team_count_after": len(deficits_after),
            "total_deficit_before": sum(int(row[2]) for row in deficits_before),
            "total_deficit_after": sum(int(row[2]) for row in deficits_after),
            "sustainable_target": CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET,
            "round_complete": not bool(deficits_after),
            "signings": signings,
        }
        target_season = source_season

    elif action == ACTION_DRAFT_LOTTERY:
        state = copy.deepcopy(source_state)
        trade_state = copy.deepcopy(source_trade)
        runtime = load_runtime_data()
        controlled = _controlled_teams(checkpoint)
        if active_team:
            controlled = tuple(sorted(set(controlled) | {_clean(active_team).upper()}))
        initialize_draft_state(state, runtime, controlled_teams=controlled, class_strength=5)
        conduct_lottery(state, runtime)
        reveal_draft_class(state)
        current = draft_state(state) or {}
        detail = {
            "draft_year": current.get("draft_year"),
            "phase": current.get("phase"),
            "lottery_order": copy.deepcopy(current.get("lottery_order", []) or []),
            "draft_pick_count": len(current.get("draft_order", []) or []),
            "prospect_count": len(current.get("prospects", []) or []),
        }
        target_season = source_season

    elif action == ACTION_DRAFT_NIGHT:
        state = copy.deepcopy(source_state)
        trade_state = copy.deepcopy(source_trade)
        start_draft_night(state, now_ts=time.time())
        current = draft_state(state) or {}
        detail = {
            "draft_year": current.get("draft_year"),
            "phase": current.get("phase"),
            "current_pick_index": int(current.get("current_pick_index", 0) or 0),
            "draft_pick_count": len(current.get("draft_order", []) or []),
        }
        target_season = source_season

    elif action == ACTION_NEXT_SEASON:
        trim = build_atomic_cpu_post_draft_trim_candidate(checkpoint)
        if trim.status == "blocked":
            raise V3SeasonLifecycleError(
                "Post-Draft roster preparation is blocked: " + "; ".join(trim.blockers)
            )
        if trim.simulation_state is None or trim.trade_state is None:
            raise V3SeasonLifecycleError("Post-Draft roster preparation returned no candidate state.")

        trimmed_checkpoint = _checkpoint_like(checkpoint, trim.simulation_state, trim.trade_state)
        transition_preview = build_season_transition_preview(trim.simulation_state)
        transitioned, transition_result = commit_season_transition_preview(
            trim.simulation_state,
            transition_preview,
        )
        target_season = _clean(transition_preview.get("target_season", ""))
        if not target_season:
            raise V3SeasonLifecycleError("Season transition preview did not expose a target season.")

        rookies_activated = activate_drafted_rookies_after_transition(transitioned, target_season)
        schedule = generate_regular_season_schedule(
            transitioned,
            seed=transitioned.settings.random_seed,
        )
        install_regular_season_schedule(transitioned, schedule)
        validate_simulation_league_state(transitioned)

        state, trade_state, reconciliation, target_fp = build_atomic_season_boundary_candidate(
            trimmed_checkpoint,
            transitioned,
            expected_target_season=target_season,
        )
        validate_simulation_league_state(state)
        detail = {
            "trim_status": trim.status,
            "cpu_players_released": len(trim.released_player_ids),
            "trimmed_teams": dict(trim.team_release_counts),
            "target_season": target_season,
            "rookies_activated": int(rookies_activated),
            "schedule_count": len(getattr(state, "schedule", {}) or {}),
            "transition": _json_safe(transition_result),
            "trade_revision_before": int(reconciliation.source_revision),
            "trade_revision_after": int(reconciliation.target_revision),
            "boundary_target_fingerprint": target_fp,
        }

    else:  # pragma: no cover
        raise V3SeasonLifecycleError(f"Unsupported lifecycle action: {action}.")

    validate_simulation_league_state(state)
    action_fp = _candidate_fingerprint(checkpoint, action, detail)
    return V3LifecycleActionCandidate(
        action=action,
        state=state,
        trade_state=trade_state,
        preferences=preferences,
        source_fingerprint=source_fp,
        action_fingerprint=action_fp,
        source_season=source_season,
        target_season=target_season,
        detail=_json_safe(detail),
    )


def build_lifecycle_action_preview(
    checkpoint: Any,
    action: str,
    *,
    active_team: str = "",
    source_checkpoint_path: str | Path | None = None,
    source_checkpoint_sha256: str = "",
) -> dict[str, Any]:
    source_fp = _source_fingerprint(checkpoint)
    try:
        candidate = build_lifecycle_action_candidate(
            checkpoint,
            action,
            active_team=active_team,
            source_checkpoint_path=source_checkpoint_path,
            source_checkpoint_sha256=source_checkpoint_sha256,
        )
    except Exception as exc:
        return {
            "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
            "status": "blocked",
            "can_commit": False,
            "action": _clean(action).lower(),
            "source_fingerprint": source_fp,
            "action_fingerprint": "",
            "detail": {},
            "blockers": [str(exc)],
            "read_only": True,
            "working_save_write_performed": False,
            "active_v2_read_only": True,
        }

    return {
        "foundation_version": SEASON_LIFECYCLE_FOUNDATION_VERSION,
        "status": "pass",
        "can_commit": True,
        "action": candidate.action,
        "source_fingerprint": candidate.source_fingerprint,
        "action_fingerprint": candidate.action_fingerprint,
        "source_season": candidate.source_season,
        "target_season": candidate.target_season,
        "detail": candidate.detail,
        "blockers": [],
        "read_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
    }


def verify_lifecycle_action_persisted(
    checkpoint: Any,
    candidate: V3LifecycleActionCandidate,
) -> dict[str, Any]:
    state = checkpoint.simulation_state
    action = candidate.action
    ok = False
    checks: dict[str, bool] = {}

    if action == ACTION_POSTSEASON_INITIALIZE:
        postseason = get_postseason_state(state, required=False)
        expected_east = candidate.detail.get("east_seeds", [])
        expected_west = candidate.detail.get("west_seeds", [])
        checks = {
            "postseason_initialized": postseason is not None,
            "postseason_stage_matches_candidate": _postseason_stage(state)
            == _clean(candidate.detail.get("stage")).lower(),
            "east_seed_order_persisted": (
                _json_safe(postseason_seed_rows(state, "East")[:10]) == expected_east
                if postseason is not None
                else False
            ),
            "west_seed_order_persisted": (
                _json_safe(postseason_seed_rows(state, "West")[:10]) == expected_west
                if postseason is not None
                else False
            ),
            "regular_season_phase_closed": _phase(state) in {"play_in", "playoffs"},
        }
        ok = all(checks.values())

    elif action == ACTION_POSTSEASON_SIMULATE:
        postseason = get_postseason_state(state, required=False)
        checks = {
            "postseason_complete": _postseason_stage(state) == "complete",
            "offseason_phase_active": _phase(state) == "offseason",
            "champion_persisted": bool(
                postseason is not None
                and _clean(getattr(postseason, "champion", ""))
                == _clean(candidate.detail.get("champion"))
            ),
            "runner_up_persisted": bool(
                postseason is not None
                and _clean(getattr(postseason, "runner_up", ""))
                == _clean(candidate.detail.get("runner_up"))
            ),
            "postseason_game_count_persisted": bool(
                postseason is not None
                and len(getattr(postseason, "completed_games", {}) or {})
                == int(candidate.detail.get("completed_postseason_games", -1) or -1)
            ),
        }
        ok = all(checks.values())

    elif action == ACTION_CONTRACT_CLOSEOUT:
        checks["closeout_applied"] = completed_season_closeout_applied(
            state,
            candidate.source_season,
        )
        source_draft_phase = str(candidate.detail.get("draft_scouting_preserved", False)).lower() == "true"
        if source_draft_phase:
            checks["season_scouting_preserved"] = _draft_payload(state)["phase"] == "season_scouting"
        ok = all(checks.values())

    elif action == ACTION_DRAFT_LOTTERY:
        current = draft_state(state) or {}
        checks = {
            "draft_phase_is_scouting": _clean(current.get("phase")).lower() == "scouting",
            "lottery_order_present": bool(current.get("lottery_order")),
            "draft_order_present": bool(current.get("draft_order")),
            "prospects_present": bool(current.get("prospects")),
        }
        ok = all(checks.values())

    elif action == ACTION_CPU_FREE_AGENCY:
        expected_deficits = candidate.detail.get("deficits_after", [])
        observed_deficits = _json_safe(_cpu_deficits(checkpoint))
        expected_transactions = {
            _clean(row.get("transaction_id"))
            for row in candidate.detail.get("signings", [])
            if isinstance(row, Mapping) and _clean(row.get("transaction_id"))
        }
        observed_transactions = {
            _clean(row.get("transaction_id"))
            for row in getattr(state, "free_agency_transaction_history", ()) or ()
            if isinstance(row, Mapping) and _clean(row.get("transaction_id"))
        }
        checks = {
            "cpu_roster_deficits_match_candidate": observed_deficits == expected_deficits,
            "cpu_signing_transactions_persisted": expected_transactions.issubset(observed_transactions),
            "cpu_signing_count_matches": len(expected_transactions)
            == int(candidate.detail.get("committed_signing_count", 0) or 0),
        }
        ok = all(checks.values())

    elif action == ACTION_DRAFT_NIGHT:
        current = draft_state(state) or {}
        checks = {
            "draft_in_progress": _clean(current.get("phase")).lower() == "draft_in_progress",
            "draft_order_present": bool(current.get("draft_order")),
        }
        ok = all(checks.values())

    elif action == ACTION_NEXT_SEASON:
        checks = {
            "target_season_loaded": _season(state) == candidate.target_season,
            "regular_season_active": _phase(state) == "regular_season",
            "schedule_has_1230_games": len(getattr(state, "schedule", {}) or {}) == LEAGUE_GAME_COUNT,
            "source_season_archived": any(
                _clean(getattr(item, "season_label", "")) == candidate.source_season
                for item in getattr(state, "season_history", ()) or ()
            ),
        }
        ok = all(checks.values())

    return {
        "persisted": bool(ok),
        "action": action,
        "checks": checks,
        "season": _season(state),
        "phase": _phase(state),
    }
