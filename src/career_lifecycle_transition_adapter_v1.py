from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import simulation_season_transition_controller_v1 as _base
from franchise_career_lifecycle_v1 import (
    CAREER_LIFECYCLE_VERSION,
    apply_retirement_plan,
    build_retirement_plan,
    initialize_career_intents_for_season,
    lifecycle_source_payload,
)
from simulation_league_state_v1 import LeaguePhase, validate_simulation_league_state


CONTROLLER_VERSION = "career-lifecycle-transition-adapter-v1.0.1-2026-08-11"
BASE_CONTROLLER_VERSION = _base.CONTROLLER_VERSION
SimulationSeasonTransitionControllerError = _base.SimulationSeasonTransitionControllerError
incomplete_scheduled_game_ids = _base.incomplete_scheduled_game_ids


def _base_preview_payload(preview: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "controller_version": preview["controller_version"],
        "source_fingerprint": preview["source_fingerprint"],
        "source_season": preview["source_season"],
        "target_season": preview["target_season"],
        "result": copy.deepcopy(preview["result"]),
    }


def lifecycle_source_fingerprint(state: Any) -> str:
    payload = {
        "base_transition_fingerprint": _base.transition_source_fingerprint(state),
        "career_lifecycle": lifecycle_source_payload(state),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_DEFERRED_VALIDATION_V2
def _validate_post_retirement_transition_state_v2(state: Any) -> None:
    """Validate every invariant except the temporary preseason roster floor.

    Retirement is applied inside the career adapter before drafted-rookie
    activation and before the season-boundary CPU roster repair. At this exact
    intermediate point a valid team may temporarily fall below the regular-
    season floor. Re-use the established OFFSEASON validation semantics for
    this intermediate copy, then restore its true PRESEASON phase.
    """
    original_phase = getattr(state, "phase", None)
    try:
        state.phase = LeaguePhase.OFFSEASON
        validate_simulation_league_state(state)
    finally:
        state.phase = original_phase


def _lifecycle_preview_for_state(state: Any, base_preview: Mapping[str, Any]) -> dict[str, Any]:
    plan = build_retirement_plan(
        state,
        target_season=str(base_preview["target_season"]),
    )
    trial_state, _ = _base.commit_season_transition_preview(
        state,
        _base_preview_payload(base_preview),
    )
    apply_retirement_plan(trial_state, plan)
    target_intents = initialize_career_intents_for_season(trial_state)
    _validate_post_retirement_transition_state_v2(trial_state)
    return {
        "adapter_version": CONTROLLER_VERSION,
        "career_lifecycle_version": CAREER_LIFECYCLE_VERSION,
        "source_fingerprint": lifecycle_source_fingerprint(state),
        "retirement_plan": plan.payload(),
        "target_season_intents": target_intents,
        "players_after_transition": len(getattr(trial_state, "players", {})),
    }


def build_season_transition_preview(
    state: Any,
    *,
    performance_signals: Mapping[str, float] | None = None,
    development_config: Any = None,
) -> dict[str, Any]:
    source_fingerprint = lifecycle_source_fingerprint(state)
    base_preview = _base.build_season_transition_preview(
        state,
        performance_signals=performance_signals,
        development_config=development_config,
    )
    lifecycle = _lifecycle_preview_for_state(state, base_preview)
    if lifecycle_source_fingerprint(state) != source_fingerprint:
        raise SimulationSeasonTransitionControllerError(
            "Building the career-lifecycle preview unexpectedly mutated the live franchise state."
        )
    preview = copy.deepcopy(base_preview)
    preview["career_lifecycle"] = lifecycle
    return preview


def preview_matches_state(state: Any, preview: Any) -> bool:
    if not isinstance(preview, Mapping):
        return False
    lifecycle = preview.get("career_lifecycle")
    if not isinstance(lifecycle, Mapping):
        return False
    try:
        base_preview = _base_preview_payload(preview)
    except (KeyError, TypeError):
        return False
    return bool(
        _base.preview_matches_state(state, base_preview)
        and lifecycle.get("adapter_version") == CONTROLLER_VERSION
        and lifecycle.get("career_lifecycle_version") == CAREER_LIFECYCLE_VERSION
        and lifecycle.get("source_fingerprint") == lifecycle_source_fingerprint(state)
    )


def commit_season_transition_preview(
    state: Any,
    preview: Any,
    *,
    performance_signals: Mapping[str, float] | None = None,
    development_config: Any = None,
) -> tuple[Any, Any]:
    if not preview_matches_state(state, preview):
        raise SimulationSeasonTransitionControllerError(
            "The live franchise or career-lifecycle inputs changed after this preview. Build a new preview before advancing."
        )

    expected_lifecycle = copy.deepcopy(preview["career_lifecycle"])
    plan = build_retirement_plan(
        state,
        target_season=str(preview["target_season"]),
    )
    if plan.payload() != expected_lifecycle.get("retirement_plan"):
        raise SimulationSeasonTransitionControllerError(
            "Retirement decisions changed after the preview. Build a new preview before advancing."
        )

    transitioned_state, result = _base.commit_season_transition_preview(
        state,
        _base_preview_payload(preview),
        performance_signals=performance_signals,
        development_config=development_config,
    )
    apply_retirement_plan(transitioned_state, plan)
    target_intents = initialize_career_intents_for_season(transitioned_state)
    _validate_post_retirement_transition_state_v2(transitioned_state)

    if target_intents != expected_lifecycle.get("target_season_intents"):
        raise SimulationSeasonTransitionControllerError(
            "The committed career-intent state did not match the previewed deterministic result."
        )
    if len(getattr(transitioned_state, "players", {})) != int(
        expected_lifecycle.get("players_after_transition", -1)
    ):
        raise SimulationSeasonTransitionControllerError(
            "The committed league population did not match the preview."
        )
    return transitioned_state, result
