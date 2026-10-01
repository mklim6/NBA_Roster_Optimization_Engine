from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from franchise_coaching_matchup_tactics_v1 import (
    apply_matchup_tactical_counters_v1,
    coach_tendency_profile_v1,
    opponent_threat_profile_v1,
)
from franchise_coaching_role_rotation_v1 import (
    workload_redistribution_report_v1,
)
from single_game_simulator_v1 import (
    GameSimulationConfig,
    build_team_game_plan,
)


COACHING_GAME_DAY_UI_VERSION = (
    "franchise-coaching-game-day-ui-v1-2026-09-30"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def render_game_day_coaching_plan_v1(
    *,
    state: Any,
    game: Any,
    active_team: str,
    sit_player_ids: Iterable[str],
) -> None:
    active = _clean(active_team).upper()
    home = _clean(getattr(game, "home_team", "")).upper()
    away = _clean(getattr(game, "away_team", "")).upper()
    if active not in {home, away}:
        return

    config = GameSimulationConfig()
    sit_ids = tuple(dict.fromkeys(str(value) for value in sit_player_ids))

    try:
        home_plan = build_team_game_plan(
            state,
            home,
            sit_player_ids=set(sit_ids),
            overtime_periods=0,
            config=config,
        )
        away_plan = build_team_game_plan(
            state,
            away,
            sit_player_ids=set(sit_ids),
            overtime_periods=0,
            config=config,
        )
        adjusted_home, adjusted_away, report = apply_matchup_tactical_counters_v1(
            state,
            home_plan,
            away_plan,
            offense_rating_weight=config.offense_rating_weight,
            opponent_rating_weight=config.opponent_rating_weight,
        )
    except Exception as exc:
        st.caption(f"Coaching plan unavailable: {exc}")
        return

    if active == home:
        active_plan = home_plan
        active_adjusted = adjusted_home
        opponent_plan = away_plan
        decision = report.home_defense
        opponent_team = away
    else:
        active_plan = away_plan
        active_adjusted = adjusted_away
        opponent_plan = home_plan
        decision = report.away_defense
        opponent_team = home

    tendency = coach_tendency_profile_v1(state, active)
    threat = opponent_threat_profile_v1(state, opponent_plan)
    workload = workload_redistribution_report_v1(
        state,
        active,
        rotation_ids=tuple(getattr(active_plan, "player_ids", ()) or ()),
        starter_ids=tuple(getattr(active_plan, "starter_ids", ()) or ()),
    )

    with st.expander(
        "Coaching plan",
        expanded=bool(
            decision.scheme != "balanced"
            or workload.missing_starter_ids
            or sit_ids
        ),
    ):
        st.caption(
            "Pregame coaching intelligence only. This explains the lineup, "
            "workload, and matchup plan without previewing a game result."
        )

        cols = st.columns(4)
        cols[0].metric("Head coach", tendency.head_coach_name)
        cols[1].metric("Defensive counter", decision.scheme_label)
        cols[2].metric(
            "Primary threat",
            threat.primary_threat_player_name or opponent_team,
        )
        cols[3].metric(
            "Modeled effect",
            f"-{decision.suppression_points:.2f} pts",
        )

        head_traits = ", ".join(tendency.head_traits) or "Neutral"
        assistant_traits = ", ".join(tendency.assistant_traits) or "Neutral"
        st.caption(
            f"Simulated staff traits · Head coach: {head_traits} · "
            f"Assistant: {assistant_traits}"
        )
        st.caption(
            "These tendencies are simulation-generated franchise attributes tied "
            "to the current staff identity. They are not a claim that the real "
            "coach uses this exact scheme."
        )

        st.markdown("**Opponent threat profile**")
        threat_cols = st.columns(5)
        threat_cols[0].metric("Creation", f"{threat.creation:.0f}")
        threat_cols[1].metric("Spacing", f"{threat.spacing:.0f}")
        threat_cols[2].metric("Rim pressure", f"{threat.rim_pressure:.0f}")
        threat_cols[3].metric("Size / glass", f"{threat.glass_size:.0f}")
        threat_cols[4].metric("Interior hub", f"{threat.interior_hub:.0f}")

        st.info(decision.explanation)

        if workload.missing_starter_ids:
            st.markdown("**Availability adjustment**")
            st.warning(workload.summary)
            rows = [
                {
                    "Player": player_name,
                    "Minute weight": f"{multiplier:.3f}x",
                }
                for player_name, multiplier in workload.minute_multipliers[:5]
            ]
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")

        with st.expander("Why this staff may prefer this plan"):
            for note in tendency.style_notes:
                st.markdown(f"- {note}")
            positive = [
                (scheme, bias)
                for scheme, bias in tendency.scheme_biases
                if bias > 0.004
            ]
            if positive:
                st.caption(
                    "Largest simulated tactical preferences: "
                    + ", ".join(
                        f"{scheme.replace('_', ' ')} {bias:+.03f}"
                        for scheme, bias in positive[:3]
                    )
                )

        internal_offset = (
            float(getattr(active_adjusted, "weighted_team_rating", 0.0))
            - float(getattr(active_plan, "weighted_team_rating", 0.0))
        )
        st.caption(
            f"Internal bounded matchup offset: {internal_offset:+.3f} rating points. "
            "No player rating is permanently changed."
        )


__all__ = [
    "COACHING_GAME_DAY_UI_VERSION",
    "render_game_day_coaching_plan_v1",
]
