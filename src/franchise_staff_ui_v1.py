from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import streamlit as st

from franchise_staff_system_v1 import (
    STAFF_SYSTEM_VERSION,
    ensure_franchise_staff_state,
    league_staff_summary,
    scouting_error_band,
    staff_rows,
    team_staff_effects,
)

STAFF_UI_VERSION = "franchise-staff-ui-v1.0-2026-09-09"


def _pct_delta(multiplier: float) -> str:
    return f"{(float(multiplier) - 1.0) * 100:+.1f}%"


def _dev_label(value: float) -> str:
    return f"{float(value):+.3f} rating pts/skill"


def render_franchise_staff_center_v1(
    state: Any,
    *,
    active_team: str,
    controlled_teams: Iterable[str] = (),
) -> None:
    ensure_franchise_staff_state(state)
    team = str(active_team or "").strip().upper()
    controlled = {str(value).strip().upper() for value in controlled_teams}
    effects = team_staff_effects(state, team)

    st.markdown("## Staff & Organization")
    st.caption(
        "Persistent coaching, development, scouting, and medical staff now live inside the franchise save. "
        "Development and medical quality already affect the simulation. Scouting ratings are the authority "
        "for the upcoming uncertainty-based scouting system."
    )

    metrics = st.columns(6)
    metrics[0].metric("Staff quality", f"{effects.overall_quality:.1f}")
    metrics[1].metric("Development", _dev_label(effects.development_modifier))
    metrics[2].metric("Injury risk", _pct_delta(effects.injury_risk_multiplier))
    metrics[3].metric("Recovery", _pct_delta(effects.recovery_multiplier))
    metrics[4].metric("Scout current", f"{effects.scouting_current_accuracy:.1f}")
    metrics[5].metric("Scout potential", f"{effects.scouting_potential_accuracy:.1f}")

    if team in controlled:
        st.info(
            "This is your controlled organization. Staff hiring, firing, extensions, interviews, and a staff market "
            "are intentionally reserved for Staff Market V2 so this first release can establish stable persistent effects."
        )

    rows = staff_rows(state, team)
    frame = pd.DataFrame(rows).rename(columns={
        "role": "Role",
        "name": "Name",
        "age": "Age",
        "experience": "Experience",
        "contract_years": "Contract Yrs",
        "salary_m": "Salary ($M)",
        "overall": "OVR",
        "offense": "Offense",
        "defense": "Defense",
        "rotations": "Rotations",
        "development": "Development",
        "scout_current": "Scout Current",
        "scout_potential": "Scout Potential",
        "medical_prevention": "Prevention",
        "medical_recovery": "Recovery",
        "communication": "Communication",
        "adaptability": "Adaptability",
        "traits": "Traits",
    })
    st.dataframe(frame, hide_index=True, width="stretch")

    st.markdown("### Organization impact")
    impact = st.columns(3)
    with impact[0]:
        st.markdown("**Coaching**")
        st.write(f"Offense index: **{effects.offense_index:.1f}**")
        st.write(f"Defense index: **{effects.defense_index:.1f}**")
        st.write(f"Rotation management: **{effects.rotation_management:.1f}**")
    with impact[1]:
        st.markdown("**Development & health**")
        st.write(f"Development modifier: **{effects.development_modifier:+.3f}**")
        st.write(f"Injury-risk multiplier: **{effects.injury_risk_multiplier:.3f}x**")
        st.write(f"Recovery multiplier: **{effects.recovery_multiplier:.3f}x**")
    with impact[2]:
        st.markdown("**Scouting readiness**")
        st.write(f"Current-skill error band: **±{scouting_error_band(state, team):.1f}**")
        st.write(f"Potential error band: **±{scouting_error_band(state, team, potential=True):.1f}**")
        st.caption("These uncertainty bands become active when Scouting V1 is installed.")

    with st.expander("League staff comparison", expanded=False):
        league = pd.DataFrame(league_staff_summary(state)).rename(columns={
            "team": "Team",
            "overall_quality": "Staff OVR",
            "development_modifier": "Dev Modifier",
            "injury_risk_multiplier": "Injury Risk",
            "recovery_multiplier": "Recovery",
            "scouting_current_accuracy": "Scout Current",
            "scouting_potential_accuracy": "Scout Potential",
            "rotation_management": "Rotations",
            "offense_index": "Offense",
            "defense_index": "Defense",
        })
        st.dataframe(league.sort_values("Staff OVR", ascending=False), hide_index=True, width="stretch")

    st.caption(f"{STAFF_SYSTEM_VERSION} · {STAFF_UI_VERSION}")
