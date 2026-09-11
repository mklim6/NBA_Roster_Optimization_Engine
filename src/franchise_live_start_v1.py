from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from freeform_trade_machine_engine_v3 import RuntimeData, normalize_player_id, normalize_team
from franchise_full_reset_v1 import build_starting_franchise
from mutable_league_state_v1 import capture_snapshot, validate_state
from nba_current_reference_overlay_v1 import (
    DEFAULT_MANIFEST_PATH,
    load_current_reference_overlay,
)
import simulation_franchise_checkpoint_v1 as checkpoint_api
from simulation_league_state_v1 import (
    BASELINE_PER_36_FIELDS,
    ContractState,
    InjuryState,
    LeaguePhase,
    PlayerSeasonTotals,
    player_state_from_simulation_player,
    validate_simulation_league_state,
)
from simulation_roster_validator_v1 import SimulationPlayer
from simulation_player_stat_fingerprints_v2 import (
    RATE_LIMITS,
    position_fallback,
    position_tokens,
)
from simulation_injury_fatigue_v1 import ensure_injury_fatigue_state
from simulation_season_transition_v1 import refresh_team_rotations


LIVE_START_VERSION = "franchise-live-start-v1.4-2026-09-09"
LIVE_RATING_PROFILE_TRANSLATION_VERSION = (
    "live-supplemental-rating-profile-translation-v1-2026-09-09"
)
LIVE_SKILL_PROFILE_TRANSLATION_VERSION = (
    "live-supplemental-skill-profile-translation-v1-2026-09-09"
)
LIVE_STAT_PROFILE_TRANSLATION_VERSION = (
    "live-supplemental-stat-profile-translation-v1-2026-09-09"
)
LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION = (
    "live-supplemental-shooting-profile-translation-v1-2026-09-09"
)
LIVE_START_UNIVERSE_ID = "live-2026-09-07"
LIVE_START_CUTOFF_DATE = "2026-09-07"
LIVE_START_CONFIRMATION_PHRASE = "START LIVE SEP 7"
LIVE_START_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "app_data"
    / "nba_live_franchise_start_2026_09_07.json"
)
LIVE_START_OVERLAY_FILENAME = "nba_current_reference_overlay_2026_09_07.json"
LIVE_REFERENCE_PLAYER_COUNT = 49
LIVE_REFERENCE_MATERIALIZED_PLAYER_COUNT = 19
LIVE_CONDITIONAL_SECOND_RIGHT_ID = "FPR_AFD12DB20C9F72A2"
PRESERVED_DIRECT_LAC_SECOND_RIGHT_ID = "FPR_FBB8EED06724F4B1"


class FranchiseLiveStartError(RuntimeError):
    """Raised when the derived live franchise universe cannot be built safely."""


@dataclass(frozen=True)
class LiveStartingFranchiseBuild:
    version: str
    universe_id: str
    cutoff_date: str
    simulation_state: Any
    trade_state: Any
    reference_players_applied: int
    materialized_players: int
    rostered_players: int
    free_agents: int
    two_way_players: int
    exhibit_10_players: int
    unresolved_current_contract_amounts: int
    draft_asset_overrides: int
    international_draft_rights: int
    schedule_games: int
    fingerprint: str


@dataclass(frozen=True)
class LiveFranchiseCommitResult:
    version: str
    universe_id: str
    cutoff_date: str
    backup_directory: str
    source_season: str
    target_season: str
    target_players: int
    target_rostered_players: int
    target_schedule_games: int
    fingerprint: str
    saved_at_utc: str
    checkpoint_reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_live_start_config() -> dict[str, Any]:
    if not LIVE_START_CONFIG_PATH.is_file():
        raise FranchiseLiveStartError(
            f"Live-start configuration is missing: {LIVE_START_CONFIG_PATH}"
        )
    try:
        payload = json.loads(LIVE_START_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FranchiseLiveStartError("Live-start configuration is unreadable.") from exc
    if not isinstance(payload, dict):
        raise FranchiseLiveStartError("Live-start configuration root must be an object.")
    if payload.get("cutoff_date") != LIVE_START_CUTOFF_DATE:
        raise FranchiseLiveStartError("Live-start cutoff date does not match the code contract.")
    if payload.get("source_overlay") != LIVE_START_OVERLAY_FILENAME:
        raise FranchiseLiveStartError("Live-start configuration points to the wrong overlay.")

    profiles = payload.get("missing_player_profiles")
    if not isinstance(profiles, list):
        raise FranchiseLiveStartError("Live-start configuration is missing player profiles.")
    profile_ids = [_clean(row.get("player_id")) for row in profiles if isinstance(row, dict)]
    if (
        len(profiles) != LIVE_REFERENCE_MATERIALIZED_PLAYER_COUNT
        or len(profile_ids) != len(set(profile_ids))
        or not all(profile_ids)
    ):
        raise FranchiseLiveStartError("Live-start supplemental player profiles are incomplete or duplicated.")

    try:
        manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FranchiseLiveStartError("Current-reference manifest is unavailable.") from exc
    if (
        manifest.get("active_overlay") != LIVE_START_OVERLAY_FILENAME
        or manifest.get("active_cutoff_date") != LIVE_START_CUTOFF_DATE
    ):
        raise FranchiseLiveStartError(
            "The active current-reference manifest is not the September 7 source."
        )
    overlay_path = DEFAULT_MANIFEST_PATH.parent / LIVE_START_OVERLAY_FILENAME
    if manifest.get("active_overlay_sha256") != _sha256(overlay_path):
        raise FranchiseLiveStartError("The live-start overlay hash does not match its manifest.")
    return payload


def _profile_map(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in config.get("missing_player_profiles", [])
        if isinstance(row, Mapping) and normalize_player_id(row.get("player_id"))
    }


def _stat_profile_map(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("statistical_profile_overrides", {})
    if not isinstance(raw, Mapping):
        raise FranchiseLiveStartError(
            "statistical_profile_overrides must be an object."
        )
    profiles = {
        normalize_player_id(player_id): dict(row)
        for player_id, row in raw.items()
        if normalize_player_id(player_id) and isinstance(row, Mapping)
    }
    for player_id, row in profiles.items():
        source_level = _clean(row.get("source_level")).lower()
        observed = row.get("observed_per_36")
        if source_level not in {"nba", "gleague", "ncaa", "international"}:
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has an invalid source level."
            )
        if not isinstance(observed, Mapping) or set(observed) != set(
            BASELINE_PER_36_FIELDS
        ):
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has incomplete per-36 evidence."
            )
        try:
            values = [float(observed[field]) for field in BASELINE_PER_36_FIELDS]
        except (TypeError, ValueError) as exc:
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has non-numeric evidence."
            ) from exc
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has invalid per-36 evidence."
            )
        if int(row.get("games_played", 0) or 0) <= 0 or not _clean(
            row.get("source_url")
        ):
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} is missing sample/source metadata."
            )
        shooting = row.get("observed_shooting")
        if not isinstance(shooting, Mapping) or set(shooting) != {
            "field_goal_percentage",
            "three_point_percentage",
            "free_throw_percentage",
            "field_goal_attempts",
            "three_point_attempts",
            "free_throw_attempts",
        }:
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has incomplete shooting evidence."
            )
        try:
            percentages = [
                float(shooting[field])
                for field in (
                    "field_goal_percentage",
                    "three_point_percentage",
                    "free_throw_percentage",
                )
            ]
            attempts = [
                float(shooting[field])
                for field in (
                    "field_goal_attempts",
                    "three_point_attempts",
                    "free_throw_attempts",
                )
            ]
        except (TypeError, ValueError) as exc:
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has non-numeric shooting evidence."
            ) from exc
        if (
            not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in percentages)
            or not all(math.isfinite(value) and value >= 0.0 for value in attempts)
            or attempts[1] > attempts[0]
        ):
            raise FranchiseLiveStartError(
                f"Supplemental stat profile {player_id} has invalid shooting evidence."
            )
    return profiles


def _stat_profile_weight(source_level: str, games_played: int) -> float:
    sample = min(1.0, max(0.0, float(games_played)) / 30.0)
    if source_level == "nba":
        return min(0.95, 0.80 + 0.15 * sample)
    if source_level == "ncaa":
        return min(0.50, 0.25 + 0.25 * sample)
    if source_level == "international":
        return min(0.48, 0.22 + 0.26 * sample)
    return min(0.42, 0.16 + 0.26 * sample)


def _stat_profile_reliability(source_level: str, games_played: int) -> float:
    sample = min(1.0, max(0.0, float(games_played)) / 30.0)
    if source_level == "nba":
        return 0.80
    if source_level == "ncaa":
        return min(0.55, 0.35 + 0.20 * sample)
    if source_level == "international":
        return min(0.48, 0.30 + 0.18 * sample)
    return min(0.42, 0.18 + 0.22 * sample)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _round_half(value: float) -> float:
    return round(float(value) * 2.0) / 2.0


def _rating_score_components(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, float]:
    """Translate retained production into auditable lower-roster rating signals."""
    position = _clean(profile.get("position")) or "SF"
    observed = evidence["observed_per_36"]
    components = {
        "scoring": _clamp(
            (float(observed["points_per_36"]) - 14.0) * 0.12,
            -1.50,
            2.00,
        ),
        "rebounding": _clamp(
            (
                float(observed["rebounds_per_36"])
                - position_fallback(position, "rebounds_per_36")
            )
            * 0.17,
            -1.25,
            1.25,
        ),
        "playmaking": _clamp(
            (
                float(observed["assists_per_36"])
                - position_fallback(position, "assists_per_36")
            )
            * 0.30,
            -1.25,
            1.25,
        ),
        "defense": _clamp(
            (
                float(observed["steals_per_36"])
                + float(observed["blocks_per_36"])
                - position_fallback(position, "steals_per_36")
                - position_fallback(position, "blocks_per_36")
            )
            * 0.65,
            -1.50,
            1.75,
        ),
        "ball_security": _clamp(
            (
                position_fallback(position, "turnovers_per_36")
                - float(observed["turnovers_per_36"])
            )
            * 0.25,
            -0.75,
            0.75,
        ),
    }
    return {key: round(value, 4) for key, value in components.items()}


def _potential_age_uplift(age: float) -> float:
    if age <= 21.0:
        return 5.0
    if age <= 22.0:
        return 4.5
    if age <= 23.0:
        return 3.5
    if age <= 24.0:
        return 2.5
    if age <= 25.0:
        return 1.5
    if age <= 26.0:
        return 1.0
    if age <= 27.0:
        return 0.5
    if age <= 28.0:
        return 0.25
    return 0.0


def _resolved_rating_profile(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve direct 2K anchors or a clearly labeled empirical proxy."""
    source_level = _clean(evidence.get("source_level")).lower()
    games_played = int(evidence.get("games_played", 0) or 0)
    reliability = _stat_profile_reliability(source_level, games_played)
    components = _rating_score_components(profile, evidence)
    raw_score = sum(components.values())
    translation_strength = min(0.78, 0.25 + 0.90 * reliability)
    translated_adjustment = _clamp(raw_score * translation_strength, -2.0, 4.0)
    evidence_status = _clean(profile.get("overall_rating_evidence_status"))
    released_external = evidence_status == "released_external_game_rating"

    if released_external:
        overall = float(profile["overall_rating"])
        resolved_source = _clean(profile.get("rating_source"))
    else:
        lower_roster_anchor = 68.5 if source_level == "international" else 68.0
        overall = _clamp(
            _round_half(lower_roster_anchor + translated_adjustment),
            67.0,
            72.0,
        )
        resolved_source = "live_empirical_rating_translation_v1"

    age = float(profile.get("age", 27.0) or 27.0)
    evidence_upside = _clamp(translated_adjustment * 0.50, -0.5, 1.5)
    potential = _round_half(
        max(overall, overall + _potential_age_uplift(age) + evidence_upside)
    )
    age_decline = _clamp(max(0.0, age - 29.0) * 0.50, 0.0, 3.0)
    future = _round_half(
        max(60.0, overall + 0.65 * (potential - overall) - age_decline)
    )
    return {
        "overall_rating": float(overall),
        "potential_rating": float(potential),
        "future_outlook_rating": float(future),
        "rating_source": resolved_source,
        "released_external_rating": released_external,
        "evidence_status": (
            evidence_status
            if released_external
            else "source_informed_empirical_proxy_no_released_game_rating"
        ),
        "source_level": source_level,
        "source_url": _clean(evidence.get("source_url")),
        "reference_distribution_url": "https://www.2kratings.com/current-teams",
        "reference_released_player_count": 649,
        "reference_lower_roster_anchor": 68.0,
        "component_scores": components,
        "raw_component_score": round(raw_score, 4),
        "translation_strength": round(translation_strength, 4),
        "translated_adjustment": round(translated_adjustment, 4),
    }


def _translated_stat_profile(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[dict[str, float], float, float]:
    source_level = _clean(evidence.get("source_level")).lower()
    games_played = int(evidence.get("games_played", 0) or 0)
    weight = _stat_profile_weight(source_level, games_played)
    reliability = _stat_profile_reliability(source_level, games_played)
    overall = float(profile.get("overall_rating", 70.0))
    position = _clean(profile.get("position")) or "SF"
    observed = evidence.get("observed_per_36", {})
    baseline: dict[str, float] = {}
    for field in BASELINE_PER_36_FIELDS:
        if field == "points_per_36":
            prior = 12.0 + max(0.0, overall - 70.0) * 0.62
            limits = (4.0, 38.0)
        else:
            prior = position_fallback(position, field)
            limits = RATE_LIMITS[field]
        translated = weight * float(observed[field]) + (1.0 - weight) * prior
        baseline[field] = round(max(limits[0], min(limits[1], translated)), 4)
    return baseline, round(weight, 4), round(reliability, 4)


def _shooting_weight(source_level: str, attempts: float, threshold: float) -> float:
    source_weight = {
        "nba": 0.95,
        "gleague": 0.55,
        "ncaa": 0.50,
        "international": 0.55,
    }[source_level]
    sample_weight = attempts / (attempts + threshold) if attempts > 0.0 else 0.0
    return round(source_weight * sample_weight, 4)


def _modeled_shooting_priors(profile: Mapping[str, Any]) -> dict[str, float]:
    overall = float(profile.get("overall_rating", 70.0))
    tokens = set(position_tokens(_clean(profile.get("position")) or "SF"))
    guard_bonus = 0.004 if {"PG", "SG"}.intersection(tokens) else 0.0
    center_three_penalty = -0.006 if "C" in tokens else 0.0
    big_two_bonus = 0.022 if "C" in tokens else 0.012 if "PF" in tokens else 0.0
    center_ft_penalty = -0.018 if "C" in tokens else 0.0
    return {
        "three_point_percentage": max(
            0.255,
            min(
                0.455,
                0.345
                + (overall - 75.0) * 0.00355
                + (overall - 75.0) * 0.00055
                + guard_bonus
                + center_three_penalty,
            ),
        ),
        "two_point_percentage": max(
            0.43,
            min(
                0.70,
                0.515
                + (overall - 75.0) * 0.0033
                + (overall - 75.0) * 0.0012
                + big_two_bonus,
            ),
        ),
        "free_throw_percentage": max(
            0.52,
            min(
                0.95,
                0.755
                + (overall - 75.0) * 0.0062
                + (0.010 if "PG" in tokens else 0.0)
                + center_ft_penalty,
            ),
        ),
    }


def _translated_shooting_profile(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    source_level = _clean(evidence.get("source_level")).lower()
    shooting = evidence["observed_shooting"]
    field_goal_attempts = float(shooting["field_goal_attempts"])
    three_point_attempts = float(shooting["three_point_attempts"])
    two_point_attempts = max(0.0, field_goal_attempts - three_point_attempts)
    field_goals_made = float(shooting["field_goal_percentage"]) * field_goal_attempts
    three_pointers_made = (
        float(shooting["three_point_percentage"]) * three_point_attempts
    )
    observed_two_point_percentage = (
        max(0.0, field_goals_made - three_pointers_made) / two_point_attempts
        if two_point_attempts > 0.0
        else 0.0
    )
    observed = {
        "three_point_percentage": float(shooting["three_point_percentage"]),
        "two_point_percentage": max(0.0, min(1.0, observed_two_point_percentage)),
        "free_throw_percentage": float(shooting["free_throw_percentage"]),
    }
    weights = {
        "three_point_percentage": _shooting_weight(
            source_level, three_point_attempts, 75.0
        ),
        "two_point_percentage": _shooting_weight(
            source_level, two_point_attempts, 100.0
        ),
        "free_throw_percentage": _shooting_weight(
            source_level, float(shooting["free_throw_attempts"]), 50.0
        ),
    }
    priors = _modeled_shooting_priors(profile)
    limits = {
        "three_point_percentage": (0.255, 0.455),
        "two_point_percentage": (0.43, 0.70),
        "free_throw_percentage": (0.52, 0.95),
    }
    translated = {}
    for field, prior in priors.items():
        weight = weights[field]
        value = weight * observed[field] + (1.0 - weight) * prior
        translated[field] = round(max(limits[field][0], min(limits[field][1], value)), 5)
    return translated, weights, {
        **observed,
        "two_point_attempts": round(two_point_attempts, 2),
    }


def _translated_skill_ratings(
    profile: Mapping[str, Any],
    evidence: Mapping[str, Any],
    baseline: Mapping[str, float],
    shooting_targets: Mapping[str, float],
    *,
    overall: float,
) -> dict[str, float]:
    """Build differentiated development skills from the retained evidence."""
    position = _clean(profile.get("position")) or "SF"
    prior_profile = dict(profile)
    prior_profile["overall_rating"] = overall
    shooting_priors = _modeled_shooting_priors(prior_profile)
    scoring_prior = 12.0 + max(0.0, overall - 70.0) * 0.62
    source_level = _clean(evidence.get("source_level")).lower()
    games_played = int(evidence.get("games_played", 0) or 0)
    reliability = _stat_profile_reliability(source_level, games_played)

    adjustments = {
        "scoring_rating": (
            (float(baseline["points_per_36"]) - scoring_prior) * 0.65
            + (
                float(baseline["free_throw_attempts_per_36"])
                - position_fallback(position, "free_throw_attempts_per_36")
            )
            * 0.15
        ),
        "shooting_rating": (
            (
                float(shooting_targets["three_point_percentage"])
                - shooting_priors["three_point_percentage"]
            )
            * 70.0
            + (
                float(shooting_targets["free_throw_percentage"])
                - shooting_priors["free_throw_percentage"]
            )
            * 25.0
            + (
                float(baseline["three_attempts_per_36"])
                - position_fallback(position, "three_attempts_per_36")
            )
            * 0.15
        ),
        "playmaking_rating": (
            (
                float(baseline["assists_per_36"])
                - position_fallback(position, "assists_per_36")
            )
            * 1.20
            + (
                position_fallback(position, "turnovers_per_36")
                - float(baseline["turnovers_per_36"])
            )
            * 0.30
        ),
        "rebounding_rating": (
            float(baseline["rebounds_per_36"])
            - position_fallback(position, "rebounds_per_36")
        ),
        "defense_rating": (
            (
                float(baseline["steals_per_36"])
                - position_fallback(position, "steals_per_36")
            )
            * 1.70
            + (
                float(baseline["blocks_per_36"])
                - position_fallback(position, "blocks_per_36")
            )
            * 1.40
            + (
                position_fallback(position, "fouls_per_36")
                - float(baseline["fouls_per_36"])
            )
            * 0.20
        ),
        "efficiency_rating": (
            (
                float(shooting_targets["two_point_percentage"])
                - shooting_priors["two_point_percentage"]
            )
            * 45.0
            + (
                float(shooting_targets["three_point_percentage"])
                - shooting_priors["three_point_percentage"]
            )
            * 35.0
            + (
                float(shooting_targets["free_throw_percentage"])
                - shooting_priors["free_throw_percentage"]
            )
            * 12.0
            + (
                position_fallback(position, "turnovers_per_36")
                - float(baseline["turnovers_per_36"])
            )
            * 0.30
        ),
        "availability_rating": (
            (reliability - 0.45) * 3.0
            - max(0.0, float(profile.get("age", 27.0) or 27.0) - 31.0) * 0.30
        ),
    }
    return {
        skill: round(_clamp(overall + _clamp(delta, -6.0, 6.0), 55.0, 95.0), 1)
        for skill, delta in adjustments.items()
    }


def _materialize_missing_players(
    runtime: RuntimeData,
    state: Any,
    trade_state: Any,
    overlay: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[str]:
    profiles = _profile_map(config)
    stat_profiles = _stat_profile_map(config)
    missing = sorted(player_id for player_id in overlay if player_id not in state.players)
    if set(missing) != set(profiles):
        absent = sorted(set(missing) - set(profiles))
        stale = sorted(set(profiles) - set(missing))
        raise FranchiseLiveStartError(
            "Supplemental profile coverage does not match the live overlay. "
            f"Missing profiles={absent}; stale profiles={stale}."
        )
    if set(stat_profiles) != set(profiles):
        absent = sorted(set(profiles) - set(stat_profiles))
        stale = sorted(set(stat_profiles) - set(profiles))
        raise FranchiseLiveStartError(
            "Supplemental statistical-profile coverage is incomplete. "
            f"Missing profiles={absent}; stale profiles={stale}."
        )

    for player_id in missing:
        profile = profiles[player_id]
        stat_evidence = stat_profiles[player_id]
        rating_profile = _resolved_rating_profile(profile, stat_evidence)
        resolved_profile = dict(profile)
        resolved_profile.update(
            {
                "overall_rating": rating_profile["overall_rating"],
                "potential_rating": rating_profile["potential_rating"],
                "future_outlook_rating": rating_profile["future_outlook_rating"],
            }
        )
        baseline, translation_weight, stat_reliability = _translated_stat_profile(
            resolved_profile,
            stat_evidence,
        )
        shooting_targets, shooting_weights, observed_shooting = (
            _translated_shooting_profile(resolved_profile, stat_evidence)
        )
        overall = float(rating_profile["overall_rating"])
        skill_ratings = _translated_skill_ratings(
            resolved_profile,
            stat_evidence,
            baseline,
            shooting_targets,
            overall=overall,
        )
        simulation_player = SimulationPlayer(
            player_id=player_id,
            player_name=_clean(profile.get("player_name")) or player_id,
            team_abbreviation="",
            overall_rating=overall,
            position=_clean(profile.get("position")) or "UNK",
            synthetic=False,
            rating_source=_clean(rating_profile.get("rating_source")),
            two_way=False,
        )
        state_profile = {
            "position": profile.get("position"),
            "age_2026_27": profile.get("age"),
            "potential_rating": rating_profile["potential_rating"],
            "future_outlook_rating": rating_profile["future_outlook_rating"],
            "profile_reliability": max(
                float(profile.get("profile_reliability", 0.15)),
                stat_reliability,
            ),
            "development_direction": (
                "External overall; evidence-calibrated skills and outlook"
                if rating_profile["released_external_rating"]
                else "Evidence-calibrated overall, skills and outlook"
            ),
            **skill_ratings,
        }
        state_profile.update(baseline)
        player = player_state_from_simulation_player(
            runtime,
            simulation_player,
            roster_status="free_agent",
            profile=state_profile,
        )
        setattr(player, "years_of_service", int(profile.get("years_of_service", 0) or 0))
        setattr(player, "live_reference_profile_provisional", True)
        setattr(player, "live_reference_profile_source", LIVE_START_CONFIG_PATH.name)
        setattr(
            player,
            "live_reference_overall_sourced",
            bool(rating_profile["released_external_rating"]),
        )
        setattr(
            player,
            "live_reference_overall_evidence_informed",
            True,
        )
        setattr(
            player,
            "live_reference_profile_evidence",
            {
                "translation_version": LIVE_RATING_PROFILE_TRANSLATION_VERSION,
                "rating_source": _clean(rating_profile.get("rating_source")),
                "overall_rating_evidence_status": _clean(
                    rating_profile.get("evidence_status")
                ),
                "overall_rating_source_url": _clean(
                    profile.get("overall_rating_source_url")
                ),
                "production_source_url": _clean(rating_profile.get("source_url")),
                "source_level": _clean(rating_profile.get("source_level")),
                "source_position": _clean(profile.get("source_position")),
                "source_archetype": _clean(profile.get("source_archetype")),
                "released_external_rating": bool(
                    rating_profile.get("released_external_rating")
                ),
                "reference_distribution_url": _clean(
                    rating_profile.get("reference_distribution_url")
                ),
                "reference_released_player_count": int(
                    rating_profile.get("reference_released_player_count", 0) or 0
                ),
                "reference_lower_roster_anchor": float(
                    rating_profile.get("reference_lower_roster_anchor", 0.0) or 0.0
                ),
                "component_scores": copy.deepcopy(
                    rating_profile.get("component_scores", {})
                ),
                "raw_component_score": float(
                    rating_profile.get("raw_component_score", 0.0) or 0.0
                ),
                "translation_strength": float(
                    rating_profile.get("translation_strength", 0.0) or 0.0
                ),
                "translated_adjustment": float(
                    rating_profile.get("translated_adjustment", 0.0) or 0.0
                ),
                "resolved_overall_rating": float(overall),
                "resolved_potential_rating": float(
                    rating_profile["potential_rating"]
                ),
                "resolved_future_outlook_rating": float(
                    rating_profile["future_outlook_rating"]
                ),
            },
        )
        setattr(
            player,
            "live_reference_skill_rating_evidence",
            {
                "translation_version": LIVE_SKILL_PROFILE_TRANSLATION_VERSION,
                "source_level": _clean(stat_evidence.get("source_level")).lower(),
                "source_season": _clean(stat_evidence.get("source_season")),
                "source_url": _clean(stat_evidence.get("source_url")),
                "simulation_skill_ratings": copy.deepcopy(skill_ratings),
            },
        )
        setattr(
            player,
            "live_reference_stat_profile_evidence",
            {
                "translation_version": LIVE_STAT_PROFILE_TRANSLATION_VERSION,
                "source_level": _clean(stat_evidence.get("source_level")).lower(),
                "source_season": _clean(stat_evidence.get("source_season")),
                "games_played": int(stat_evidence.get("games_played", 0) or 0),
                "evidence_method": _clean(stat_evidence.get("evidence_method")),
                "source_url": _clean(stat_evidence.get("source_url")),
                "secondary_source_url": _clean(
                    stat_evidence.get("secondary_source_url")
                ),
                "translation_weight": translation_weight,
                "observed_per_36": {
                    field: float(stat_evidence["observed_per_36"][field])
                    for field in BASELINE_PER_36_FIELDS
                },
                "simulation_baseline_per_36": copy.deepcopy(baseline),
            },
        )
        setattr(
            player,
            "live_reference_shooting_evidence",
            {
                "translation_version": LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION,
                "source_level": _clean(stat_evidence.get("source_level")).lower(),
                "source_season": _clean(stat_evidence.get("source_season")),
                "source_url": _clean(stat_evidence.get("source_url")),
                "attempts": {
                    field: float(stat_evidence["observed_shooting"][field])
                    for field in (
                        "field_goal_attempts",
                        "three_point_attempts",
                        "free_throw_attempts",
                    )
                },
                "observed_percentages": observed_shooting,
                "translation_weights": shooting_weights,
                "simulation_targets": shooting_targets,
                "development_skill_anchor": {
                    field: float(player.skill_ratings[field])
                    for field in (
                        "shooting_rating",
                        "scoring_rating",
                        "efficiency_rating",
                    )
                },
            },
        )
        state.players[player_id] = player
        state.injuries[player_id] = InjuryState(player_id=player_id)
        state.player_season_totals[player_id] = PlayerSeasonTotals(player_id=player_id)
        trade_state.player_team_by_id[player_id] = ""
    sourced_overalls = sum(
        bool(getattr(state.players[player_id], "live_reference_overall_sourced", False))
        for player_id in missing
    )
    evidence_informed_overalls = sum(
        bool(
            getattr(
                state.players[player_id],
                "live_reference_overall_evidence_informed",
                False,
            )
        )
        for player_id in missing
    )
    source_distribution: dict[str, int] = {}
    for player_id in missing:
        level = _clean(stat_profiles[player_id].get("source_level")).lower()
        source_distribution[level] = source_distribution.get(level, 0) + 1
    state.franchise_live_profile_scope_v1 = {
        "materialized_profile_count": len(missing),
        "externally_sourced_overall_count": sourced_overalls,
        "empirically_calibrated_overall_count": (
            evidence_informed_overalls - sourced_overalls
        ),
        "source_informed_overall_count": evidence_informed_overalls,
        "fully_modeled_overall_count": len(missing) - evidence_informed_overalls,
        "rating_profile_translation_version": (
            LIVE_RATING_PROFILE_TRANSLATION_VERSION
        ),
        "detailed_statistical_profiles_sourced": len(stat_profiles),
        "detailed_statistical_profiles_remaining": len(missing) - len(stat_profiles),
        "statistical_profile_source_distribution": source_distribution,
        "statistical_profile_translation_version": (
            LIVE_STAT_PROFILE_TRANSLATION_VERSION
        ),
        "shooting_efficiency_profiles_sourced": len(stat_profiles),
        "shooting_efficiency_profiles_remaining": len(missing) - len(stat_profiles),
        "shooting_profile_translation_version": (
            LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION
        ),
        "broader_skill_ratings_source_informed": len(missing),
        "broader_skill_ratings_still_modeled": 0,
        "skill_profile_translation_version": LIVE_SKILL_PROFILE_TRANSLATION_VERSION,
        "potential_profiles_age_and_production_calibrated": len(missing),
        "potential_profiles_still_modeled": 0,
        "source": LIVE_START_CONFIG_PATH.name,
    }
    return missing


def _contract_terms_map(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("current_contract_overrides", {})
    if not isinstance(raw, Mapping):
        raise FranchiseLiveStartError("current_contract_overrides must be an object.")
    return {
        normalize_player_id(player_id): dict(terms)
        for player_id, terms in raw.items()
        if normalize_player_id(player_id) and isinstance(terms, Mapping)
    }


def _set_live_contract(
    player: Any,
    row: Mapping[str, Any],
    terms: Mapping[str, Any] | None,
    *,
    prior_team: str,
) -> bool:
    status = _clean(row.get("current_reference_status"))
    action = _clean(row.get("contract_reference_action"))
    target_team = normalize_team(row.get("current_reference_team"))
    contract = getattr(player, "contract", None)
    if contract is None:
        contract = ContractState(status="free_agent_pool", salary=None)
        player.contract = contract

    if status == "free_agent":
        player.roster_status = "free_agent"
        player.two_way = False
        contract.status = "free_agent_pool"
        contract.salary = None
        contract.years_remaining = None
        contract.option_type = ""
        contract.guaranteed = None
        setattr(player, "live_contract_cap_hit", 0.0)
        setattr(player, "live_contract_guaranteed_amount", 0.0)
        setattr(player, "live_contract_total_value", None)
        setattr(player, "live_contract_guarantee_status", "not_under_contract")
        setattr(player, "live_contract_signing_method", "")
        setattr(player, "live_contract_salary_schedule", [])
        setattr(player, "live_contract_guarantee_notes", [])
        setattr(player, "live_contract_transaction_source_url", "")
        setattr(player, "live_contract_evidence_status", "waived_or_released")
        return False

    if status == "two_way":
        player.roster_status = "two_way"
        player.two_way = True
        contract.status = "two_way"
        contract.salary = 0.0
        contract.years_remaining = 1
        contract.option_type = ""
        contract.guaranteed = False
        setattr(player, "live_contract_cap_hit", 0.0)
        setattr(player, "live_contract_guaranteed_amount", 0.0)
        setattr(player, "live_contract_total_value", None)
        setattr(player, "live_contract_guarantee_status", "two_way")
        setattr(player, "live_contract_signing_method", "two_way")
        setattr(player, "live_contract_salary_schedule", [])
        setattr(player, "live_contract_guarantee_notes", [])
        setattr(player, "live_contract_transaction_source_url", "")
        setattr(player, "live_contract_evidence_status", "official_two_way_structure")
        return False

    if status == "exhibit_10":
        player.roster_status = "exhibit_10"
        player.two_way = False
        contract.status = "exhibit_10"
        contract.salary = 0.0
        contract.years_remaining = 1
        contract.option_type = "exhibit_10"
        contract.guaranteed = False
        setattr(player, "live_contract_cap_hit", 0.0)
        setattr(player, "live_contract_guaranteed_amount", 0.0)
        setattr(player, "live_contract_total_value", None)
        setattr(player, "live_contract_guarantee_status", "non_guaranteed")
        setattr(player, "live_contract_signing_method", "exhibit_10")
        setattr(player, "live_contract_salary_schedule", [])
        setattr(player, "live_contract_guarantee_notes", [])
        setattr(player, "live_contract_transaction_source_url", "")
        setattr(player, "live_contract_evidence_status", "official_exhibit_10_structure")
        return False

    if status != "under_contract" or not target_team:
        raise FranchiseLiveStartError(
            f"Unsupported live contract status for {player.player_id}: {status!r}."
        )

    player.roster_status = "active_roster"
    player.two_way = False
    contract.status = "under_contract"
    if terms is not None:
        salary = terms.get("salary")
        contract.salary = None if salary is None else float(salary)
        contract.years_remaining = int(terms.get("years_remaining", 1) or 1)
        contract.option_type = _clean(terms.get("option_type"))
        contract.guaranteed = bool(terms.get("guaranteed", True))
        cap_hit = terms.get("cap_hit", salary)
        guaranteed_amount = terms.get("guaranteed_amount")
        total_value = terms.get("total_value")
        setattr(player, "live_contract_cap_hit", None if cap_hit is None else float(cap_hit))
        setattr(
            player,
            "live_contract_guaranteed_amount",
            None if guaranteed_amount is None else float(guaranteed_amount),
        )
        setattr(
            player,
            "live_contract_total_value",
            None if total_value is None else float(total_value),
        )
        setattr(player, "live_contract_guarantee_status", _clean(terms.get("guarantee_status")))
        setattr(player, "live_contract_signing_method", _clean(terms.get("signing_method")))
        setattr(player, "live_contract_salary_schedule", copy.deepcopy(terms.get("salary_schedule", [])))
        setattr(player, "live_contract_guarantee_notes", list(terms.get("guarantee_notes", [])))
        setattr(
            player,
            "live_contract_transaction_source_url",
            _clean(terms.get("transaction_source_url")),
        )
        setattr(
            player,
            "live_contract_evidence_status",
            _clean(terms.get("evidence_status")) or "configured_override",
        )
        setattr(player, "live_contract_source_url", _clean(terms.get("source_url")))
        return salary is None

    preserve_current = action in {"trade", "extension"} or (
        action == "standard_signing"
        and prior_team == target_team
        and getattr(contract, "salary", None) is not None
    )
    if preserve_current:
        if getattr(contract, "years_remaining", None) is None:
            contract.years_remaining = 1
        if getattr(contract, "guaranteed", None) is None:
            contract.guaranteed = True
        salary = getattr(contract, "salary", None)
        setattr(player, "live_contract_cap_hit", salary)
        setattr(
            player,
            "live_contract_guaranteed_amount",
            salary if bool(getattr(contract, "guaranteed", False)) else 0.0,
        )
        setattr(player, "live_contract_total_value", salary)
        setattr(
            player,
            "live_contract_guarantee_status",
            "current_salary_preserved",
        )
        setattr(player, "live_contract_signing_method", "existing_contract")
        setattr(player, "live_contract_salary_schedule", [])
        setattr(player, "live_contract_guarantee_notes", [])
        setattr(player, "live_contract_transaction_source_url", "")
        evidence = (
            "current_salary_preserved_for_trade_or_extension"
            if action in {"trade", "extension"}
            else "existing_same_team_salary_preserved"
        )
        setattr(player, "live_contract_evidence_status", evidence)
        return getattr(contract, "salary", None) is None

    contract.salary = None
    contract.years_remaining = 1
    contract.option_type = ""
    contract.guaranteed = True
    setattr(player, "live_contract_cap_hit", None)
    setattr(player, "live_contract_guaranteed_amount", None)
    setattr(player, "live_contract_total_value", None)
    setattr(player, "live_contract_guarantee_status", "unresolved")
    setattr(player, "live_contract_signing_method", "")
    setattr(player, "live_contract_salary_schedule", [])
    setattr(player, "live_contract_guarantee_notes", [])
    setattr(player, "live_contract_transaction_source_url", "")
    setattr(player, "live_contract_evidence_status", "official_signing_amount_unresolved")
    return True


def _apply_roster_overlay(
    state: Any,
    trade_state: Any,
    overlay: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> int:
    terms_by_id = _contract_terms_map(config)
    prior = {
        player_id: {
            "team": normalize_team(getattr(player, "team_abbreviation", "")),
            "salary": getattr(getattr(player, "contract", None), "salary", None),
            "two_way": bool(getattr(player, "two_way", False)),
        }
        for player_id, player in state.players.items()
    }
    unresolved = 0

    for player_id, row in sorted(overlay.items()):
        if player_id not in state.players:
            raise FranchiseLiveStartError(f"Live overlay player {player_id} was not materialized.")
        player = state.players[player_id]
        prior_team = prior[player_id]["team"]
        target_team = normalize_team(row.get("current_reference_team"))
        player.team_abbreviation = target_team
        unresolved += int(
            _set_live_contract(
                player,
                row,
                terms_by_id.get(player_id),
                prior_team=prior_team,
            )
        )
        setattr(
            player,
            "live_reference_event",
            {
                "cutoff_date": LIVE_START_CUTOFF_DATE,
                "event_date": _clean(row.get("latest_event_date")),
                "event_type": _clean(row.get("latest_event_type")),
                "description": _clean(row.get("latest_description")),
                "source_name": _clean(row.get("source_name")),
                "source_url": _clean(row.get("source_url")),
            },
        )

    for team_code, team_state in state.teams.items():
        roster = sorted(
            (
                player_id
                for player_id, player in state.players.items()
                if normalize_team(getattr(player, "team_abbreviation", "")) == team_code
            ),
            key=lambda player_id: (
                -float(getattr(state.players[player_id], "overall_rating", 0.0) or 0.0),
                _clean(getattr(state.players[player_id], "player_name", "")),
                player_id,
            ),
        )
        team_state.roster_player_ids = tuple(roster)

    state.free_agent_player_ids = tuple(
        sorted(
            player_id
            for player_id, player in state.players.items()
            if not normalize_team(getattr(player, "team_abbreviation", ""))
        )
    )
    trade_state.player_team_by_id = {
        player_id: normalize_team(getattr(player, "team_abbreviation", ""))
        for player_id, player in state.players.items()
    }

    # Preserve the base financial ledger, then shift every known current cap
    # charge touched by the reference overlay. Veteran minimum base salary and
    # team cap charge can differ, so those values remain separate.
    salary_delta = {team: 0.0 for team in trade_state.team_financials}
    for player_id in overlay:
        before = prior[player_id]
        after_player = state.players[player_id]
        after_team = normalize_team(getattr(after_player, "team_abbreviation", ""))
        after_salary = getattr(getattr(after_player, "contract", None), "salary", None)
        after_cap_hit = getattr(after_player, "live_contract_cap_hit", after_salary)
        if before["team"] and not before["two_way"] and before["salary"] is not None:
            salary_delta[before["team"]] -= float(before["salary"])
        if after_team and not bool(getattr(after_player, "two_way", False)) and after_cap_hit is not None:
            salary_delta[after_team] += float(after_cap_hit)

    for team_code, financial in trade_state.team_financials.items():
        team_players = [
            state.players[player_id]
            for player_id in state.teams[team_code].roster_player_ids
        ]
        financial.standard_contract_count = sum(
            not bool(getattr(player, "two_way", False)) for player in team_players
        )
        financial.two_way_contract_count = sum(
            bool(getattr(player, "two_way", False)) for player in team_players
        )
        delta = salary_delta.get(team_code, 0.0)
        if financial.team_salary is not None and math.isfinite(float(financial.team_salary)):
            financial.team_salary = max(0.0, float(financial.team_salary) + delta)
        if financial.apron_salary is not None and math.isfinite(float(financial.apron_salary)):
            financial.apron_salary = max(0.0, float(financial.apron_salary) + delta)

    extensions = config.get("future_extension_references", {})
    if isinstance(extensions, Mapping):
        for player_id, extension in extensions.items():
            normalized = normalize_player_id(player_id)
            if normalized in state.players and isinstance(extension, Mapping):
                setattr(state.players[normalized], "live_future_extension_reference", dict(extension))
    return unresolved


def _apply_draft_assets(state: Any, trade_state: Any, config: Mapping[str, Any]) -> None:
    raw = config.get("draft_asset_overrides", [])
    if not isinstance(raw, list):
        raise FranchiseLiveStartError("draft_asset_overrides must be a list.")
    state_overrides = dict(getattr(state, "franchise_draft_right_ownership_v1", {}) or {})
    audit: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise FranchiseLiveStartError("Draft-asset override rows must be objects.")
        asset_id = _clean(item.get("asset_id"))
        owner = normalize_team(item.get("to_team"))
        ledger_asset_id = _clean(item.get("ledger_asset_id"))
        if not asset_id or not owner:
            raise FranchiseLiveStartError("Draft-asset override is missing an asset or owner.")
        if asset_id in trade_state.pick_team_by_id:
            trade_state.pick_team_by_id[asset_id] = owner
        elif not ledger_asset_id:
            raise FranchiseLiveStartError(
                f"Draft-asset override {asset_id} is absent from the canonical trade inventory."
            )
        if ledger_asset_id:
            state_overrides[ledger_asset_id] = owner
        elif asset_id in trade_state.pick_team_by_id:
            state_overrides[asset_id] = owner
        audit.append(dict(item))
    state.franchise_draft_right_ownership_v1 = state_overrides
    state.franchise_live_draft_asset_audit_v1 = audit

    rights = config.get("international_draft_rights", [])
    if not isinstance(rights, list):
        raise FranchiseLiveStartError("international_draft_rights must be a list.")
    state.franchise_international_draft_rights_v1 = {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in rights
        if isinstance(row, Mapping) and normalize_player_id(row.get("player_id"))
    }


def live_start_fingerprint(state: Any, trade_state: Any) -> str:
    payload = {
        "universe": copy.deepcopy(getattr(state, "franchise_start_universe_v1", {})),
        "phase": _clean(getattr(getattr(state, "phase", None), "value", state.phase)),
        "players": sorted(
            (
                player_id,
                normalize_team(getattr(player, "team_abbreviation", "")),
                _clean(getattr(player, "roster_status", "")),
                bool(getattr(player, "two_way", False)),
                getattr(player, "overall_rating", None),
                getattr(player, "potential_rating", None),
                getattr(player, "future_outlook_rating", None),
                getattr(player, "profile_reliability", None),
                _clean(getattr(player, "rating_source", "")),
                copy.deepcopy(getattr(player, "live_reference_profile_evidence", {})),
                copy.deepcopy(
                    getattr(player, "live_reference_stat_profile_evidence", {})
                ),
                copy.deepcopy(
                    getattr(player, "live_reference_shooting_evidence", {})
                ),
                copy.deepcopy(
                    getattr(player, "live_reference_skill_rating_evidence", {})
                ),
                copy.deepcopy(getattr(player, "skill_ratings", {})),
                copy.deepcopy(getattr(player, "baseline_per_36", {})),
                _clean(getattr(getattr(player, "contract", None), "status", "")),
                getattr(getattr(player, "contract", None), "salary", None),
                getattr(getattr(player, "contract", None), "years_remaining", None),
                _clean(getattr(getattr(player, "contract", None), "option_type", "")),
                getattr(getattr(player, "contract", None), "guaranteed", None),
                getattr(player, "live_contract_cap_hit", None),
                getattr(player, "live_contract_guaranteed_amount", None),
                getattr(player, "live_contract_total_value", None),
                _clean(getattr(player, "live_contract_guarantee_status", "")),
                _clean(getattr(player, "live_contract_signing_method", "")),
                copy.deepcopy(getattr(player, "live_contract_salary_schedule", [])),
            )
            for player_id, player in state.players.items()
        ),
        "rosters": sorted(
            (team, tuple(team_state.roster_player_ids))
            for team, team_state in state.teams.items()
        ),
        "pick_owners": sorted(trade_state.pick_team_by_id.items()),
        "draft_overrides": sorted(
            (str(asset), normalize_team(owner))
            for asset, owner in (
                getattr(state, "franchise_draft_right_ownership_v1", {}) or {}
            ).items()
        ),
        "international_rights": sorted(
            (
                player_id,
                normalize_team(row.get("current_owner")),
            )
            for player_id, row in (
                getattr(state, "franchise_international_draft_rights_v1", {}) or {}
            ).items()
        ),
        "financial_scope": copy.deepcopy(
            getattr(state, "franchise_live_financial_scope_v1", {})
        ),
        "profile_scope": copy.deepcopy(
            getattr(state, "franchise_live_profile_scope_v1", {})
        ),
        "team_financials": sorted(
            (
                team,
                getattr(financial, "team_salary", None),
                getattr(financial, "apron_salary", None),
                getattr(financial, "standard_contract_count", None),
                getattr(financial, "two_way_contract_count", None),
            )
            for team, financial in trade_state.team_financials.items()
        ),
        "schedule": sorted(state.schedule),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_live_starting_franchise(runtime: RuntimeData) -> LiveStartingFranchiseBuild:
    config = load_live_start_config()
    overlay = load_current_reference_overlay()
    if len(overlay) != LIVE_REFERENCE_PLAYER_COUNT:
        raise FranchiseLiveStartError(
            f"Expected {LIVE_REFERENCE_PLAYER_COUNT} current-reference players; found {len(overlay)}."
        )

    base = build_starting_franchise(runtime)
    state = base.simulation_state
    trade_state = base.trade_state
    materialized = _materialize_missing_players(runtime, state, trade_state, overlay, config)
    unresolved = _apply_roster_overlay(state, trade_state, overlay, config)
    _apply_draft_assets(state, trade_state, config)

    state.phase = LeaguePhase.OFFSEASON
    state.franchise_start_universe_v1 = {
        "version": LIVE_START_VERSION,
        "universe_id": LIVE_START_UNIVERSE_ID,
        "label": "Live September 7, 2026",
        "cutoff_date": LIVE_START_CUTOFF_DATE,
        "source_overlay": LIVE_START_OVERLAY_FILENAME,
        "source_overlay_sha256": _sha256(
            DEFAULT_MANIFEST_PATH.parent / LIVE_START_OVERLAY_FILENAME
        ),
        "reference_player_count": len(overlay),
        "materialized_player_count": len(materialized),
        "contract_scope": (
            "Roster/contract status is current through the cutoff. Every standard signing in "
            "the overlay has a sourced current salary and cap charge; guarantees, options, and "
            "multi-year schedules remain separately represented."
        ),
    }
    state.franchise_live_reference_transactions_v1 = [
        dict(row) for _, row in sorted(overlay.items())
    ]
    state.franchise_live_financial_scope_v1 = {
        "known_salary_deltas_applied": True,
        "base_salary_and_cap_hit_separated": True,
        "configured_contract_count": len(_contract_terms_map(config)),
        "detailed_contracts_resolved": sum(
            _clean(terms.get("evidence_status")).startswith("detailed_salary_cap")
            for terms in _contract_terms_map(config).values()
        ),
        "cap_hit_differences": sum(
            terms.get("salary") is not None
            and terms.get("cap_hit") is not None
            and float(terms["salary"]) != float(terms["cap_hit"])
            for terms in _contract_terms_map(config).values()
        ),
        "unresolved_current_contract_amounts": unresolved,
        "source": LIVE_START_CONFIG_PATH.name,
    }
    refresh_team_rotations(state)
    ensure_injury_fatigue_state(state)

    trade_state.initial_snapshot = capture_snapshot(trade_state)
    validate_state(trade_state, runtime)
    validate_simulation_league_state(state)

    if trade_state.pick_team_by_id.get(LIVE_CONDITIONAL_SECOND_RIGHT_ID) != "WAS":
        raise FranchiseLiveStartError("The Clippers-derived 2027 conditional second did not move to WAS.")
    if trade_state.pick_team_by_id.get(PRESERVED_DIRECT_LAC_SECOND_RIGHT_ID) != "UTA":
        raise FranchiseLiveStartError("The separate direct 2027 LAC second was not preserved at UTA.")
    if any(
        len(team.roster_player_ids) < state.settings.minimum_game_players
        or len(team.roster_player_ids) > 21
        for team in state.teams.values()
    ):
        raise FranchiseLiveStartError("The live universe does not satisfy 8-to-21 player roster readiness.")

    fingerprint = live_start_fingerprint(state, trade_state)
    return LiveStartingFranchiseBuild(
        version=LIVE_START_VERSION,
        universe_id=LIVE_START_UNIVERSE_ID,
        cutoff_date=LIVE_START_CUTOFF_DATE,
        simulation_state=state,
        trade_state=trade_state,
        reference_players_applied=len(overlay),
        materialized_players=len(materialized),
        rostered_players=sum(len(team.roster_player_ids) for team in state.teams.values()),
        free_agents=len(state.free_agent_player_ids),
        two_way_players=sum(bool(player.two_way) for player in state.players.values()),
        exhibit_10_players=sum(player.roster_status == "exhibit_10" for player in state.players.values()),
        unresolved_current_contract_amounts=unresolved,
        draft_asset_overrides=len(config.get("draft_asset_overrides", [])),
        international_draft_rights=len(config.get("international_draft_rights", [])),
        schedule_games=len(state.schedule),
        fingerprint=fingerprint,
    )


def _checkpoint_path() -> Path:
    return Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()


def _checkpoint_family(path: Path) -> list[Path]:
    if not path.parent.exists():
        return []
    prefix = path.name.split(".pkl", 1)[0]
    return sorted(
        candidate
        for candidate in path.parent.iterdir()
        if candidate.is_file() and candidate.name.startswith(prefix)
    )


def _snapshot_checkpoint_family(backup_dir: Path, primary: Path) -> list[str]:
    target_dir = backup_dir / "checkpoint"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in _checkpoint_family(primary):
        shutil.copy2(source, target_dir / source.name)
        copied.append(source.name)
    return copied


def _restore_checkpoint_family(backup_dir: Path, primary: Path) -> None:
    source_dir = backup_dir / "checkpoint"
    if not source_dir.exists():
        return
    prefix = primary.name.split(".pkl", 1)[0]
    primary.parent.mkdir(parents=True, exist_ok=True)
    for current in primary.parent.iterdir():
        if current.is_file() and current.name.startswith(prefix):
            current.unlink()
    for source in source_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, primary.parent / source.name)


def commit_live_franchise_start(
    runtime: RuntimeData,
    current_state: Any,
    current_trade_state: Any,
    *,
    preferences: Mapping[str, Any] | None = None,
) -> LiveFranchiseCommitResult:
    """Replace the active franchise with the live branch after a recovery backup."""
    validate_simulation_league_state(current_state)
    validate_state(current_trade_state, runtime)
    primary = _checkpoint_path()
    checkpoint_api.save_franchise_checkpoint(
        current_state,
        current_trade_state,
        preferences=dict(preferences or {}),
        reason="pre-live-franchise-start-v1",
        path=primary,
        copy_payload=True,
    )

    if not primary.is_file():
        raise FranchiseLiveStartError("Could not create the pre-live-start checkpoint.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project_root = primary.parent.parent.parent
    backup_dir = project_root / "backups" / f"live_franchise_start_v1_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    copied = _snapshot_checkpoint_family(backup_dir, primary)
    source_summary = {
        "season": _clean(current_state.settings.season_label),
        "phase": _clean(getattr(current_state.phase, "value", current_state.phase)),
        "players": len(current_state.players),
        "completed_games": len(current_state.completed_games),
        "checkpoint_files": copied,
    }
    (backup_dir / "live_start_manifest.json").write_text(
        json.dumps(
            {
                "version": LIVE_START_VERSION,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": source_summary,
                "target_universe": LIVE_START_UNIVERSE_ID,
                "target_cutoff_date": LIVE_START_CUTOFF_DATE,
                "restore_note": "The checkpoint folder is the active franchise immediately before the live start was installed.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        live = build_live_starting_franchise(runtime)
        saved = checkpoint_api.save_franchise_checkpoint(
            live.simulation_state,
            live.trade_state,
            preferences=dict(preferences or {}),
            reason="new-live-franchise-start-2026-09-07",
            path=primary,
            copy_payload=True,
            force_replace=True,
        )
        reloaded = checkpoint_api.load_franchise_checkpoint(
            path=primary,
            allow_backup=False,
        )
        if reloaded is None:
            raise FranchiseLiveStartError("The live-start checkpoint could not be reloaded.")
        validate_simulation_league_state(reloaded.simulation_state)
        validate_state(reloaded.trade_state, runtime)
        observed = live_start_fingerprint(reloaded.simulation_state, reloaded.trade_state)
        if observed != live.fingerprint:
            raise FranchiseLiveStartError("The reloaded live-start fingerprint changed after save.")
        return LiveFranchiseCommitResult(
            version=LIVE_START_VERSION,
            universe_id=LIVE_START_UNIVERSE_ID,
            cutoff_date=LIVE_START_CUTOFF_DATE,
            backup_directory=str(backup_dir),
            source_season=source_summary["season"],
            target_season=_clean(reloaded.simulation_state.settings.season_label),
            target_players=len(reloaded.simulation_state.players),
            target_rostered_players=sum(
                len(team.roster_player_ids) for team in reloaded.simulation_state.teams.values()
            ),
            target_schedule_games=len(reloaded.simulation_state.schedule),
            fingerprint=observed,
            saved_at_utc=str(saved.saved_at_utc),
            checkpoint_reason=str(saved.reason),
        )
    except Exception as exc:
        try:
            _restore_checkpoint_family(backup_dir, primary)
        except Exception as restore_exc:
            raise FranchiseLiveStartError(
                f"Live start failed ({exc}) and automatic restoration failed ({restore_exc}). "
                f"Manual recovery copy: {backup_dir}"
            ) from exc
        raise FranchiseLiveStartError(
            f"Live start failed and the previous franchise was restored automatically: {exc}"
        ) from exc
