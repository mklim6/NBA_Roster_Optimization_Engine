from __future__ import annotations

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
from simulation_season_transition_v1 import (
    player_development_profile,
    resolve_performance_signals,
)


DEVELOPMENT_CENTER_VERSION = (
    "franchise-development-center-v1.0.2-2026-08-11"
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

    for player_id in team_state.roster_player_ids:
        player = state.players[player_id]
        current_overall = float(player.overall_rating)
        incoming_rookie = bool(
            getattr(player, "generated_prospect", False)
            and getattr(player, "synthetic", False)
        )

        if incoming_rookie:
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
        "engine_versions": engine_versions,
        "runtime_fresh": bool(
            not engine_versions
            or engine_versions == [EXPECTED_DEVELOPMENT_ENGINE_VERSION]
        ),
    }


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

    st.markdown("---")
    st.markdown("## Offseason Team Development")
    st.caption(
        f"{preview['source_season']} → {preview['target_season']} · "
        "Deterministic preview. Reloading the page does not reroll player development."
    )

    if not preview.get("runtime_fresh", True):
        st.warning(
            "The page detected an older development-engine object still cached "
            "inside the running Streamlit process. The preview is using safe "
            "fallback fields. Restart Streamlit before committing the next-season "
            "transition so Player Development V2 is guaranteed to be active."
        )

    rows = preview["rows"]
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
    riser = max(
        existing,
        key=lambda row: float(row["Δ OVR"]),
        default=None,
    )
    faller = min(
        existing,
        key=lambda row: float(row["Δ OVR"]),
        default=None,
    )
    avg_change = (
        sum(float(row["Δ OVR"]) for row in existing)
        / len(existing)
        if existing
        else 0.0
    )
    promotions = sum(
        row["Projected Role"]
        in {
            "New Starter Candidate",
            "Rotation Promotion",
        }
        for row in rows
    )

    metrics = st.columns(4)
    metrics[0].metric(
        "Biggest Riser",
        riser["Player"] if riser else "—",
        (
            _display_change(float(riser["Δ OVR"]))
            if riser
            else None
        ),
    )
    metrics[1].metric(
        "Biggest Decline",
        faller["Player"] if faller else "—",
        (
            _display_change(float(faller["Δ OVR"]))
            if faller
            else None
        ),
    )
    metrics[2].metric(
        "Average OVR Change",
        _display_change(avg_change),
    )
    metrics[3].metric(
        "Role Promotions",
        promotions,
    )

    frame = pd.DataFrame(rows)
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        height=min(720, 52 + 35 * len(frame)),
        column_config={
            "Old OVR": st.column_config.NumberColumn(
                "Old OVR",
                format="%.1f",
            ),
            "New OVR": st.column_config.NumberColumn(
                "New OVR",
                format="%.1f",
            ),
            "Δ OVR": st.column_config.NumberColumn(
                "Δ OVR",
                format="%+.1f",
            ),
            "POT": st.column_config.NumberColumn(
                "POT",
                format="%.1f",
            ),
            "Last MPG": st.column_config.NumberColumn(
                "Last MPG",
                format="%.1f",
            ),
        },
    )

    st.markdown("### Rotation & Roster Impact")
    if preview["advice"]:
        for item in preview["advice"]:
            st.info(item)
    else:
        st.caption(
            "No major rotation changes are flagged. Review the table before committing the next season."
        )

    st.caption(
        "After opening the next season, use Roster to apply your final starters, "
        "rotation order, and 240-minute plan. Young players gain more development "
        "benefit when they receive meaningful NBA reps during their first three seasons."
    )
