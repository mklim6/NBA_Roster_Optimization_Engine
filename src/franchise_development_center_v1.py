from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

import importlib

import player_development_engine_v1 as _development_engine

# Streamlit can retain a pre-upgrade module object across page navigation.
# Reload the exact project source before building any offseason preview.
_development_engine = importlib.reload(_development_engine)
DevelopmentConfig = _development_engine.DevelopmentConfig
DEVELOPMENT_ENGINE_VERSION = _development_engine.ENGINE_VERSION
next_season_label = _development_engine.next_season_label
project_player_development = _development_engine.project_player_development
from franchise_generated_player_portraits_v1 import player_image_url
from simulation_season_transition_v1 import (
    player_development_profile,
    resolve_performance_signals,
)


DEVELOPMENT_CENTER_VERSION = (
    "franchise-development-center-v2.0-presentation-2026-09-12"
)
EXPECTED_DEVELOPMENT_ENGINE_VERSION = "player-development-engine-v2.0-2026-08-11"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _projection_map(projection: Any) -> dict[str, Any]:
    """Return projection fields without requiring a particular dataclass schema."""
    try:
        raw = vars(projection)
    except (TypeError, AttributeError):
        raw = {}
    return dict(raw) if isinstance(raw, dict) else {}


def _projection_number(
    projection_data: dict[str, Any],
    name: str,
    default: float = 0.0,
) -> float:
    return _number(projection_data.get(name, default), default)


def _primary_position(value: Any) -> str:
    text = str(value or "UNK").strip().upper()
    return text.split("/", 1)[0] or "UNK"


def _display_change(value: float) -> str:
    return f"{value:+.1f}"


def _development_label(delta: float) -> str:
    if delta >= 7.0:
        return "🚀 Massive Breakout"
    if delta >= 4.0:
        return "🚀 Major Growth"
    if delta >= 2.0:
        return "↑ Strong Growth"
    if delta >= 0.75:
        return "↑ Improved"
    if delta > -0.75:
        return "→ Stable"
    if delta > -2.5:
        return "↓ Decline"
    if delta > -5.0:
        return "↓ Major Decline"
    return "⬇ Steep Decline"


def _exposure_label(score: float, mpg: float) -> str:
    if mpg >= 28.0 and score >= 0.80:
        return "Excellent"
    if mpg >= 22.0 and score >= 0.60:
        return "Strong"
    if mpg >= 15.0 and score >= 0.40:
        return "Meaningful"
    if mpg >= 8.0:
        return "Limited"
    return "Minimal"


def _projected_opportunity_priority(
    player: Any,
    projected_overall: float,
    years_of_service: int | None = None,
) -> float:
    age = _number(getattr(player, "age", 99.0), 99.0)
    if age > 24.0:
        return projected_overall

    potential = _number(
        getattr(player, "potential_rating", projected_overall),
        projected_overall,
    )
    gap = max(0.0, potential - projected_overall)
    years = years_of_service
    if years is None:
        years = getattr(player, "years_of_service", None)
    if years is None:
        years = len(
            getattr(player, "development_history", [])
            or []
        )
    try:
        years = int(years)
    except (TypeError, ValueError):
        years = 99

    if years > 3:
        return projected_overall

    if age <= 21:
        age_bonus = 0.80
    elif age <= 23:
        age_bonus = 0.45
    else:
        age_bonus = 0.20

    gap_bonus = min(3.10, 0.22 * gap)

    try:
        pick = int(getattr(player, "draft_pick", 999))
    except (TypeError, ValueError):
        pick = 999

    if pick <= 5:
        draft_bonus = 1.00
    elif pick <= 14:
        draft_bonus = 0.75
    elif pick <= 30:
        draft_bonus = 0.40
    else:
        draft_bonus = 0.0

    decay = {
        0: 1.00,
        1: 1.00,
        2: 0.70,
        3: 0.35,
    }.get(years, 0.0)

    return (
        projected_overall
        + age_bonus
        + gap_bonus
        + draft_bonus * decay
    )


SKILL_LABELS_V2 = {
    "scoring_rating": "Scoring",
    "shooting_rating": "Shooting",
    "playmaking_rating": "Playmaking",
    "rebounding_rating": "Rebounding",
    "defense_rating": "Defense",
    "efficiency_rating": "Efficiency",
    "availability_rating": "Availability",
}


def _development_tone(delta: float) -> str:
    if delta >= 2.0:
        return "riser"
    if delta <= -2.0:
        return "decliner"
    return "steady"


def _safe_player_image(
    player: Any,
    *,
    team: str,
) -> str:
    try:
        return player_image_url(
            getattr(player, "player_id", ""),
            team=team,
            player_name=str(
                getattr(player, "player_name", "")
                or getattr(player, "display_name", "")
                or ""
            ),
            generated=bool(
                getattr(player, "synthetic", False)
                or getattr(player, "generated_prospect", False)
            ),
        )
    except Exception:
        return ""


def _detail_component_story(detail: dict[str, Any]) -> tuple[str, ...]:
    rows: list[str] = []
    age = _number(detail.get("age_curve_component"), 0.0)
    growth = _number(detail.get("potential_growth_component"), 0.0)
    opportunity = _number(detail.get("opportunity_component"), 0.0)
    performance = _number(detail.get("performance_component"), 0.0)
    breakout = _number(detail.get("breakout_component"), 0.0)

    if abs(growth) >= 0.10:
        rows.append(
            "Potential runway is pushing the projection upward."
            if growth > 0
            else "The remaining development runway is limited."
        )
    if abs(opportunity) >= 0.10:
        rows.append(
            "Meaningful NBA reps are helping development."
            if opportunity > 0
            else "Limited opportunity is suppressing development."
        )
    if abs(performance) >= 0.10:
        rows.append(
            "Recent performance supports the projection."
            if performance > 0
            else "Recent performance is dragging on the projection."
        )
    if abs(age) >= 0.10:
        rows.append(
            "The age curve is still favorable."
            if age > 0
            else "The age curve is creating natural regression pressure."
        )
    if abs(breakout) >= 0.50:
        rows.append(
            "A breakout development roll is amplifying the result."
            if breakout > 0
            else "A stall/regression roll is amplifying the decline."
        )
    return tuple(rows[:4])


def build_team_development_preview_v1(
    state: Any,
    team: str,
) -> dict[str, Any]:
    resolved_team = str(team or "").strip().upper()
    if resolved_team not in state.teams:
        raise ValueError(
            f"Unknown team for development preview: {resolved_team}"
        )

    source_season = str(state.settings.season_label)
    target_season = next_season_label(source_season)
    signals = resolve_performance_signals(
        state,
        None,
    )
    config = DevelopmentConfig(
        random_seed=state.settings.random_seed,
    )

    team_state = state.teams[resolved_team]
    previous_rotation = set(
        team_state.rotation.rotation_player_ids
    )
    previous_starters = set(
        team_state.rotation.starter_ids
    )

    rows: list[dict[str, Any]] = []
    projection_by_id: dict[str, Any] = {}
    detail_by_player: dict[str, dict[str, Any]] = {}

    for player_id in team_state.roster_player_ids:
        player = state.players[player_id]
        current_overall = float(player.overall_rating)
        incoming_rookie = bool(
            getattr(player, "generated_prospect", False)
            and getattr(player, "synthetic", False)
        )

        if incoming_rookie:
            detail_by_player[str(player.player_name)] = {
                "player_id": player_id,
                "image_url": _safe_player_image(
                    player,
                    team=resolved_team,
                ),
                "skill_deltas": {},
                "projected_skill_ratings": dict(
                    getattr(player, "skill_ratings", {}) or {}
                ),
                "age_curve_component": 0.0,
                "potential_growth_component": 0.0,
                "opportunity_component": 0.0,
                "performance_component": 0.0,
                "breakout_component": 0.0,
                "career_stage": "incoming rookie",
                "development_direction": "Incoming Rookie",
            }
            rows.append(
                {
                    "player_id": player_id,
                    "Player": player.player_name,
                    "Age": _number(player.age, 20.0),
                    "Pos": player.position,
                    "Old OVR": round(current_overall, 1),
                    "New OVR": round(current_overall, 1),
                    "Δ OVR": 0.0,
                    "POT": round(
                        _number(
                            player.potential_rating,
                            current_overall,
                        ),
                        1,
                    ),
                    "Last GP": 0,
                    "Last MPG": 0.0,
                    "Exposure": "Incoming rookie",
                    "Development": "Drafted this offseason",
                    "Projected Role": "Incoming Rookie",
                    "Minutes Guidance": (
                        "Set rookie role after the new season opens"
                    ),
                    "Drivers": (
                        "New draft pick. Rookie development begins "
                        "after his first NBA season."
                    ),
                    "_projected_score": current_overall,
                    "_previous_rotation": False,
                    "_previous_starter": False,
                }
            )
            continue

        if getattr(player, "synthetic", False):
            continue

        profile = player_development_profile(
            state,
            player_id,
        )
        projection = project_player_development(
            profile,
            source_season=source_season,
            target_season=target_season,
            performance_signal=float(
                signals.get(player_id, 0.0)
            ),
            config=config,
        )
        projection_by_id[player_id] = projection
        projection_data = _projection_map(projection)

        # The durable profile is the source of truth for prior-season workload.
        # Do not read GP/MPG from PlayerDevelopmentProjection at all.
        projection_games = int(_number(profile.get("games_played", 0), 0.0))
        projection_mpg = _number(profile.get("minutes_per_game", 0.0), 0.0)
        projection_years = int(_number(
            profile.get(
                "years_of_service",
                getattr(player, "years_of_service", 99),
            ),
            99.0,
        ))
        gp_exposure = min(1.0, max(0.0, projection_games / 65.0))
        mpg_exposure = min(1.0, max(0.0, projection_mpg / 28.0))
        profile_exposure_score = gp_exposure * mpg_exposure
        projection_opportunity_score = _projection_number(
            projection_data, "opportunity_score", profile_exposure_score
        )
        projection_opportunity_component = _projection_number(
            projection_data, "opportunity_component", 0.0
        )
        projection_pedigree_component = _projection_number(
            projection_data, "draft_pedigree_component", 0.0
        )
        projection_breakout_component = _projection_number(
            projection_data, "breakout_component", 0.0
        )
        projection_source_age = _projection_number(
            projection_data,
            "source_age",
            _number(getattr(player, "age", 0.0), 0.0),
        )
        projection_current_overall = _projection_number(
            projection_data, "current_overall_rating", current_overall
        )
        projection_new_overall = _projection_number(
            projection_data, "projected_overall_rating", current_overall
        )
        projection_overall_delta = _projection_number(
            projection_data,
            "overall_delta",
            projection_new_overall - projection_current_overall,
        )
        projection_performance_component = _projection_number(
            projection_data, "performance_component", 0.0
        )

        potential = float(
            player.potential_rating
            if player.potential_rating is not None
            else current_overall
        )
        gap = max(
            0.0,
            potential
            - projection_new_overall,
        )

        drivers = [
            f"Age {projection_source_age:.0f}",
            (
                f"{projection_games} GP / "
                f"{projection_mpg:.1f} MPG"
            ),
        ]
        if gap >= 4.0:
            drivers.append(
                f"{gap:.1f} POT runway"
            )
        if abs(projection_performance_component) >= 0.10:
            drivers.append(
                "strong performance signal"
                if projection_performance_component > 0
                else "negative performance signal"
            )
        if projection_opportunity_component >= 0.50:
            drivers.append("meaningful development reps")
        if projection_pedigree_component >= 0.30:
            drivers.append("early-career draft pedigree")
        if projection_breakout_component >= 0.75:
            drivers.append("breakout development roll")
        elif projection_breakout_component <= -0.75:
            drivers.append("stall / regression roll")
        if projection_source_age >= 33:
            drivers.append("veteran aging curve")

        detail_by_player[str(player.player_name)] = {
            "player_id": player_id,
            "image_url": _safe_player_image(
                player,
                team=resolved_team,
            ),
            "skill_deltas": dict(
                projection_data.get("skill_deltas", {}) or {}
            ),
            "projected_skill_ratings": dict(
                projection_data.get("projected_skill_ratings", {}) or {}
            ),
            "age_curve_component": _projection_number(
                projection_data,
                "age_curve_component",
                0.0,
            ),
            "potential_growth_component": _projection_number(
                projection_data,
                "potential_growth_component",
                0.0,
            ),
            "opportunity_component": projection_opportunity_component,
            "performance_component": projection_performance_component,
            "breakout_component": projection_breakout_component,
            "career_stage": str(
                projection_data.get("career_stage", "") or ""
            ),
            "development_direction": str(
                projection_data.get("development_direction", "") or ""
            ),
        }

        rows.append(
            {
                "player_id": player_id,
                "Player": player.player_name,
                "Age": round(projection_source_age, 1),
                "Pos": player.position,
                "Old OVR": round(
                    projection_current_overall,
                    1,
                ),
                "New OVR": round(
                    projection_new_overall,
                    1,
                ),
                "Δ OVR": round(
                    projection_overall_delta,
                    1,
                ),
                "POT": round(potential, 1),
                "Last GP": projection_games,
                "Last MPG": round(
                    projection_mpg,
                    1,
                ),
                "Exposure": _exposure_label(
                    projection_opportunity_score,
                    projection_mpg,
                ),
                "Development": _development_label(
                    projection_overall_delta
                ),
                "Projected Role": "",
                "Minutes Guidance": "",
                "Drivers": " · ".join(drivers),
                "_projected_score": (
                    _projected_opportunity_priority(
                        player,
                        projection_new_overall,
                        projection_years,
                    )
                ),
                "_previous_rotation": (
                    player_id in previous_rotation
                ),
                "_previous_starter": (
                    player_id in previous_starters
                ),
            }
        )

    if not rows:
        return {
            "version": DEVELOPMENT_CENTER_VERSION,
            "source_season": source_season,
            "target_season": target_season,
            "team": resolved_team,
            "rows": [],
            "advice": [],
            "detail_by_player": {},
        }

    eligible_rows = [
        row
        for row in rows
        if row["Projected Role"] != "Incoming Rookie"
    ]
    projected_starters = {
        row["player_id"]
        for row in sorted(
            eligible_rows,
            key=lambda item: (
                -float(item["New OVR"]),
                str(item["Player"]),
            ),
        )[:5]
    }

    rotation_size = min(
        int(state.settings.rotation_size),
        len(eligible_rows),
    )
    protected_count = min(
        rotation_size,
        max(5, rotation_size - 3),
    )
    ovr_order = sorted(
        eligible_rows,
        key=lambda item: (
            -float(item["New OVR"]),
            str(item["Player"]),
        ),
    )
    protected = ovr_order[:protected_count]
    protected_ids = {
        row["player_id"]
        for row in protected
    }
    remaining = [
        row
        for row in eligible_rows
        if row["player_id"] not in protected_ids
    ]
    remaining.sort(
        key=lambda item: (
            -float(item["_projected_score"]),
            -float(item["New OVR"]),
            str(item["Player"]),
        )
    )
    projected_rotation = protected + remaining[
        : max(
            0,
            rotation_size - len(protected),
        )
    ]
    projected_rotation_ids = {
        row["player_id"]
        for row in projected_rotation
    }

    for row in rows:
        player_id = row["player_id"]
        if row["Projected Role"] == "Incoming Rookie":
            continue

        if player_id in projected_starters:
            row["Projected Role"] = (
                "Starter"
                if row["_previous_starter"]
                else "New Starter Candidate"
            )
        elif player_id in projected_rotation_ids:
            row["Projected Role"] = (
                "Rotation"
                if row["_previous_rotation"]
                else "Rotation Promotion"
            )
        else:
            row["Projected Role"] = "Outside Rotation"

        age = float(row["Age"])
        potential_gap = (
            float(row["POT"])
            - float(row["New OVR"])
        )
        previous_mpg = float(row["Last MPG"])
        delta = float(row["Δ OVR"])

        if player_id in projected_starters:
            if age <= 24 and previous_mpg < 28.0:
                row["Minutes Guidance"] = (
                    "Consider 28-34 MPG"
                )
            else:
                row["Minutes Guidance"] = (
                    "Starter-level minutes"
                )
        elif (
            age <= 23
            and potential_gap >= 6.0
            and previous_mpg < 22.0
        ):
            row["Minutes Guidance"] = (
                "Development priority: target 18-26 MPG"
            )
        elif (
            player_id in projected_rotation_ids
            and not row["_previous_rotation"]
        ):
            row["Minutes Guidance"] = (
                "New rotation opportunity: 14-22 MPG"
            )
        elif age >= 33 and delta <= -2.0:
            row["Minutes Guidance"] = (
                "Reassess / reduce veteran minutes"
            )
        elif player_id in projected_rotation_ids:
            row["Minutes Guidance"] = (
                "Maintain rotation role"
            )
        else:
            row["Minutes Guidance"] = (
                "Depth role unless roster changes"
            )

    advice: list[str] = []
    projected_existing = [
        row
        for row in rows
        if row["Projected Role"] != "Incoming Rookie"
    ]
    if projected_existing:
        biggest_riser = max(
            projected_existing,
            key=lambda row: float(row["Δ OVR"]),
        )
        if float(biggest_riser["Δ OVR"]) >= 2.0:
            advice.append(
                f"{biggest_riser['Player']} is your biggest riser "
                f"({_display_change(float(biggest_riser['Δ OVR']))} OVR). "
                "Reevaluate his role before opening night."
            )

        biggest_faller = min(
            projected_existing,
            key=lambda row: float(row["Δ OVR"]),
        )
        if float(biggest_faller["Δ OVR"]) <= -2.0:
            advice.append(
                f"{biggest_faller['Player']} projects to decline "
                f"{_display_change(float(biggest_faller['Δ OVR']))} OVR. "
                "That may create a new rotation or roster need."
            )

    promotions = [
        row
        for row in rows
        if row["Projected Role"]
        in {
            "New Starter Candidate",
            "Rotation Promotion",
        }
    ]
    for row in promotions[:3]:
        advice.append(
            f"{row['Player']} projects as a "
            f"{row['Projected Role'].lower()} at "
            f"{row['New OVR']:.1f} OVR. "
            f"{row['Minutes Guidance']}."
        )

    position_best: dict[str, float] = {}
    for row in rows:
        pos = _primary_position(row["Pos"])
        position_best[pos] = max(
            position_best.get(pos, 0.0),
            float(row["New OVR"]),
        )
    for pos, rating in sorted(
        position_best.items(),
        key=lambda item: item[1],
    ):
        if pos != "UNK" and rating < 77.0:
            advice.append(
                f"{pos} is a projected roster weakness. "
                f"Best current option is only {rating:.1f} OVR."
            )

    visible_rows = []
    for row in rows:
        visible_rows.append(
            {
                key: value
                for key, value in row.items()
                if not key.startswith("_")
                and key != "player_id"
            }
        )

    visible_rows.sort(
        key=lambda row: (
            -float(row["New OVR"]),
            str(row["Player"]),
        )
    )

    engine_versions = sorted({
        str(_projection_map(item).get("engine_version", "unknown") or "unknown")
        for item in projection_by_id.values()
    })

    return {
        "version": DEVELOPMENT_CENTER_VERSION,
        "source_season": source_season,
        "target_season": target_season,
        "team": resolved_team,
        "rows": visible_rows,
        "advice": advice[:6],
        "detail_by_player": detail_by_player,
        "engine_versions": engine_versions,
        "runtime_fresh": bool(
            not engine_versions
            or engine_versions == [EXPECTED_DEVELOPMENT_ENGINE_VERSION]
        ),
    }


def _inject_development_center_styles_v2() -> None:
    st.markdown(
        '''
<style>
.dev2-shell{
  margin:1.1rem 0 1.6rem;
  border:1px solid rgba(255,65,115,.34);
  border-radius:25px;
  overflow:hidden;
  background:
    radial-gradient(circle at 100% 0%,rgba(180,25,75,.22),transparent 38%),
    linear-gradient(145deg,#07111d 0%,#0b101a 65%,#120a13 100%);
}
.dev2-hero{padding:26px 28px 22px}
.dev2-kicker{
  color:#7dd3fc;font-size:.68rem;font-weight:950;letter-spacing:.15em;
  text-transform:uppercase
}
.dev2-title{
  margin:.42rem 0 .4rem;color:#fff;font-size:2rem;font-weight:950;line-height:1.05
}
.dev2-copy{max-width:900px;color:#9badc2;font-size:.84rem;line-height:1.55}
.dev2-summary{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;
  padding:0 28px 24px
}
.dev2-metric{
  background:#09131f;border:1px solid rgba(255,255,255,.075);
  border-radius:16px;padding:14px 15px
}
.dev2-metric small{
  display:block;color:#74879e;font-size:.50rem;font-weight:950;
  letter-spacing:.12em;text-transform:uppercase
}
.dev2-metric strong{display:block;margin-top:6px;color:#fff;font-size:1.02rem}
.dev2-metric span{display:block;margin-top:4px;color:#90a2b8;font-size:.61rem}
.dev2-spotlights{
  display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px;margin:12px 0
}
.dev2-card{
  display:grid;grid-template-columns:112px 1fr;min-height:160px;
  overflow:hidden;border:1px solid rgba(255,255,255,.08);
  border-radius:18px;background:#09121d
}
.dev2-card.riser{border-color:rgba(52,211,153,.30)}
.dev2-card.decliner{border-color:rgba(251,113,133,.34)}
.dev2-card.steady{border-color:rgba(125,211,252,.23)}
.dev2-photo{
  width:112px;height:100%;min-height:160px;object-fit:cover;background:#111827
}
.dev2-card-body{padding:14px}
.dev2-card-tag{
  font-size:.49rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase;
  color:#7dd3fc
}
.dev2-card.riser .dev2-card-tag{color:#6ee7b7}
.dev2-card.decliner .dev2-card-tag{color:#fda4af}
.dev2-card-name{margin-top:5px;color:#fff;font-size:.94rem;font-weight:950}
.dev2-card-meta{margin-top:4px;color:#8295aa;font-size:.59rem}
.dev2-ovr{margin-top:11px;color:#f8fafc;font-size:.75rem;font-weight:850}
.dev2-delta{font-size:1.05rem;font-weight:950;margin-left:7px}
.dev2-delta.pos{color:#6ee7b7}.dev2-delta.neg{color:#fb7185}.dev2-delta.flat{color:#93c5fd}
.dev2-role{margin-top:8px;color:#aebdcd;font-size:.60rem;line-height:1.45}
.dev2-detail{
  margin:12px 0;padding:17px 18px;border:1px solid rgba(255,255,255,.08);
  border-radius:18px;background:#08111c
}
.dev2-detail-grid{display:grid;grid-template-columns:160px 1fr;gap:18px;align-items:start}
.dev2-detail-photo{width:160px;height:190px;object-fit:cover;border-radius:15px;background:#111827}
.dev2-detail-name{color:#fff;font-size:1.22rem;font-weight:950}
.dev2-detail-meta{margin-top:4px;color:#8497ad;font-size:.68rem}
.dev2-story{margin-top:8px;padding:8px 10px;border-radius:11px;background:#0c1724;color:#aebdcd;font-size:.63rem}
.dev2-skill-grid{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:12px
}
.dev2-skill{padding:9px 10px;border-radius:11px;background:#0c1724;border:1px solid rgba(255,255,255,.055)}
.dev2-skill small{display:block;color:#71859b;font-size:.46rem;font-weight:900;text-transform:uppercase}
.dev2-skill strong{display:block;margin-top:4px;color:#fff;font-size:.76rem}
.dev2-skill .pos{color:#6ee7b7}.dev2-skill .neg{color:#fb7185}.dev2-skill .flat{color:#93c5fd}
@media(max-width:1000px){
  .dev2-spotlights{grid-template-columns:1fr}
  .dev2-summary{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:650px){
  .dev2-hero{padding:21px}.dev2-summary{padding:0 21px 21px}
  .dev2-title{font-size:1.55rem}
  .dev2-summary{grid-template-columns:1fr 1fr}
  .dev2-card{grid-template-columns:92px 1fr}.dev2-photo{width:92px}
  .dev2-detail-grid{grid-template-columns:1fr}
  .dev2-detail-photo{width:100%;height:240px}
  .dev2-skill-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
</style>
        ''',
        unsafe_allow_html=True,
    )


def _spotlight_card_html(
    row: dict[str, Any],
    detail: dict[str, Any],
    *,
    tag: str,
) -> str:
    delta = float(row["Δ OVR"])
    tone = _development_tone(delta)
    delta_class = "pos" if delta > 0.05 else ("neg" if delta < -0.05 else "flat")
    image_url = html.escape(str(detail.get("image_url", "") or ""))
    image_html = (
        f'<img class="dev2-photo" src="{image_url}" alt="">'
        if image_url
        else '<div class="dev2-photo"></div>'
    )
    return (
        f'<div class="dev2-card {tone}">'
        f'{image_html}'
        '<div class="dev2-card-body">'
        f'<div class="dev2-card-tag">{html.escape(tag)}</div>'
        f'<div class="dev2-card-name">{html.escape(str(row["Player"]))}</div>'
        f'<div class="dev2-card-meta">{html.escape(str(row["Pos"]))} · Age {float(row["Age"]):.0f} · {html.escape(str(row["Development"]))}</div>'
        f'<div class="dev2-ovr">{float(row["Old OVR"]):.1f} OVR → {float(row["New OVR"]):.1f}'
        f'<span class="dev2-delta {delta_class}">{delta:+.1f}</span></div>'
        f'<div class="dev2-role">{html.escape(str(row["Projected Role"]))} · {html.escape(str(row["Minutes Guidance"]))}</div>'
        '</div></div>'
    )


def render_team_development_center_v1(
    state: Any,
    team: str,
) -> None:
    try:
        preview = build_team_development_preview_v1(
            state,
            team,
        )
    except Exception as exc:
        st.markdown("---")
        st.markdown("## Offseason Team Development")
        st.warning(
            "The offseason development preview could not be built, but the "
            "rest of Franchise Mode is still available. Do not open the next "
            "season until this preview is healthy."
        )
        st.caption(
            f"Development preview diagnostic: {type(exc).__name__}: {exc}"
        )
        return

    _inject_development_center_styles_v2()

    if not preview.get("runtime_fresh", True):
        st.warning(
            "The page detected an older development-engine object still cached "
            "inside the running Streamlit process. Restart Streamlit before "
            "committing the next-season transition."
        )

    rows = preview["rows"]
    details = preview.get("detail_by_player", {}) or {}
    if not rows:
        st.info(
            "No eligible players are available for an offseason development preview."
        )
        return

    existing = [
        row
        for row in rows
        if row["Development"] != "Drafted this offseason"
    ]
    riser = max(existing, key=lambda row: float(row["Δ OVR"]), default=None)
    faller = min(existing, key=lambda row: float(row["Δ OVR"]), default=None)
    avg_change = (
        sum(float(row["Δ OVR"]) for row in existing) / len(existing)
        if existing else 0.0
    )
    promotions = sum(
        row["Projected Role"] in {"New Starter Candidate", "Rotation Promotion"}
        for row in rows
    )
    meaningful_risers = sum(float(row["Δ OVR"]) >= 1.0 for row in existing)
    meaningful_decliners = sum(float(row["Δ OVR"]) <= -1.0 for row in existing)

    riser_name = html.escape(str(riser["Player"])) if riser else "—"
    riser_delta = f'{float(riser["Δ OVR"]):+.1f} OVR' if riser else "—"
    faller_name = html.escape(str(faller["Player"])) if faller else "—"
    faller_delta = f'{float(faller["Δ OVR"]):+.1f} OVR' if faller else "—"

    st.markdown(
        f'''<div class="dev2-shell">
<div class="dev2-hero">
  <div class="dev2-kicker">{html.escape(preview["team"])} · OFFSEASON DEVELOPMENT REPORT</div>
  <div class="dev2-title">{html.escape(preview["source_season"])} → {html.escape(preview["target_season"])} Player Progression</div>
  <div class="dev2-copy">A deterministic look at how the current roster projects to change when the next season opens. Development, regression, opportunity and role impact are all derived from the existing franchise engine. Reloading this page does not reroll anyone.</div>
</div>
<div class="dev2-summary">
  <div class="dev2-metric"><small>Biggest riser</small><strong>{riser_name}</strong><span>{riser_delta}</span></div>
  <div class="dev2-metric"><small>Biggest decline</small><strong>{faller_name}</strong><span>{faller_delta}</span></div>
  <div class="dev2-metric"><small>Team average</small><strong>{avg_change:+.1f} OVR</strong><span>{meaningful_risers} risers · {meaningful_decliners} decliners</span></div>
  <div class="dev2-metric"><small>Role promotions</small><strong>{promotions}</strong><span>Starter / rotation opportunities</span></div>
</div>
</div>''',
        unsafe_allow_html=True,
    )

    spotlights: list[tuple[str, dict[str, Any]]] = []
    if riser is not None:
        spotlights.append(("BREAKOUT WATCH", riser))
    if faller is not None and (riser is None or faller["Player"] != riser["Player"]):
        spotlights.append(("REGRESSION WATCH", faller))

    promotion_rows = [
        row for row in rows
        if row["Projected Role"] in {"New Starter Candidate", "Rotation Promotion"}
        and all(row["Player"] != x[1]["Player"] for x in spotlights)
    ]
    if promotion_rows:
        spotlights.append(("ROLE CHANGE", promotion_rows[0]))
    else:
        stable = min(rows, key=lambda row: abs(float(row["Δ OVR"])), default=None)
        if stable is not None and all(
            stable["Player"] != x[1]["Player"] for x in spotlights
        ):
            spotlights.append(("STEADY CORE", stable))

    if spotlights:
        cards = "".join(
            _spotlight_card_html(
                row,
                details.get(str(row["Player"]), {}),
                tag=tag,
            )
            for tag, row in spotlights[:3]
        )
        st.markdown(
            f'<div class="dev2-spotlights">{cards}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("### Player Development Detail")
    selected_name = st.selectbox(
        "Choose a player",
        options=[str(row["Player"]) for row in rows],
        key="development_center_v2_player_select",
        label_visibility="collapsed",
    )
    selected_row = next(row for row in rows if str(row["Player"]) == selected_name)
    selected_detail = details.get(selected_name, {}) or {}
    selected_delta = float(selected_row["Δ OVR"])
    selected_delta_class = (
        "pos" if selected_delta > 0.05
        else ("neg" if selected_delta < -0.05 else "flat")
    )
    selected_image = html.escape(str(selected_detail.get("image_url", "") or ""))
    skill_deltas = dict(selected_detail.get("skill_deltas", {}) or {})
    projected_skills = dict(selected_detail.get("projected_skill_ratings", {}) or {})

    stories = _detail_component_story(selected_detail)
    story_html = "".join(
        f'<div class="dev2-story">{html.escape(item)}</div>'
        for item in stories
    ) or '<div class="dev2-story">No major development driver dominates this projection.</div>'

    skill_html_parts: list[str] = []
    for field, label in SKILL_LABELS_V2.items():
        if field not in projected_skills and field not in skill_deltas:
            continue
        delta = _number(skill_deltas.get(field), 0.0)
        value = _number(projected_skills.get(field), 0.0)
        cls = "pos" if delta > 0.05 else ("neg" if delta < -0.05 else "flat")
        skill_html_parts.append(
            '<div class="dev2-skill">'
            f'<small>{html.escape(label)}</small>'
            f'<strong>{value:.1f} <span class="{cls}">{delta:+.1f}</span></strong>'
            '</div>'
        )
    skills_html = "".join(skill_html_parts)

    image_html = (
        f'<img class="dev2-detail-photo" src="{selected_image}" alt="">'
        if selected_image
        else '<div class="dev2-detail-photo"></div>'
    )
    st.markdown(
        f'''<div class="dev2-detail">
<div class="dev2-detail-grid">
  {image_html}
  <div>
    <div class="dev2-detail-name">{html.escape(selected_name)}</div>
    <div class="dev2-detail-meta">{html.escape(str(selected_row["Pos"]))} · Age {float(selected_row["Age"]):.0f} · {html.escape(str(selected_row["Projected Role"]))}</div>
    <div class="dev2-ovr" style="margin-top:12px">{float(selected_row["Old OVR"]):.1f} OVR → {float(selected_row["New OVR"]):.1f}<span class="dev2-delta {selected_delta_class}">{selected_delta:+.1f}</span></div>
    <div class="dev2-role">{html.escape(str(selected_row["Development"]))} · {html.escape(str(selected_row["Exposure"]))} exposure · {html.escape(str(selected_row["Minutes Guidance"]))}</div>
    {story_html}
    <div class="dev2-skill-grid">{skills_html}</div>
  </div>
</div>
</div>''',
        unsafe_allow_html=True,
    )

    st.markdown("### Front Office Development Notes")
    if preview["advice"]:
        note_cols = st.columns(2)
        for index, item in enumerate(preview["advice"]):
            note_cols[index % 2].info(item)
    else:
        st.caption(
            "No major rotation changes are flagged. Review the full roster report before opening the next season."
        )

    with st.expander("Full Development Board", expanded=False):
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            height=min(720, 52 + 35 * len(frame)),
            column_config={
                "Old OVR": st.column_config.NumberColumn("Old OVR", format="%.1f"),
                "New OVR": st.column_config.NumberColumn("New OVR", format="%.1f"),
                "Δ OVR": st.column_config.NumberColumn("Δ OVR", format="%+.1f"),
                "POT": st.column_config.NumberColumn("POT", format="%.1f"),
                "Last MPG": st.column_config.NumberColumn("Last MPG", format="%.1f"),
            },
        )

    st.caption(
        "Preview only. No player ratings are changed on this screen. The certified "
        "season-boundary transition remains the authority that applies development "
        "and opens the next season."
    )

