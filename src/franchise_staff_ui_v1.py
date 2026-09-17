from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import streamlit as st

from franchise_staff_system_v1 import (
    STAFF_SYSTEM_VERSION,
    ensure_franchise_staff_state,
    hire_lead_scout,
    lead_scout_member,
    league_staff_summary,
    scout_market_candidates,
    scouting_error_band,
    scouting_error_band_for_rating,
    scouting_track_record_rows,
    staff_rows,
    team_staff_effects,
)

STAFF_UI_VERSION = "franchise-staff-ui-v1.3-role-groups-2026-09-16"


def _pct_delta(multiplier: float) -> str:
    return f"{(float(multiplier) - 1.0) * 100:+.1f}%"


def _dev_label(value: float) -> str:
    return f"{float(value):+.3f} rating pts/skill"


def _scout_grade(value: float) -> str:
    value = float(value)
    if value >= 90:
        return "Elite"
    if value >= 82:
        return "Excellent"
    if value >= 74:
        return "Strong"
    if value >= 66:
        return "Average"
    if value >= 58:
        return "Below average"
    return "Weak"


def _candidate_rows(candidates):
    rows = []
    for scout in candidates:
        rows.append({
            "Candidate": scout.name,
            "OVR": scout.overall_rating,
            "Current": scout.scouting_current_rating,
            "Current ±": scouting_error_band_for_rating(scout.scouting_current_rating),
            "Potential": scout.scouting_potential_rating,
            "Potential ±": scouting_error_band_for_rating(scout.scouting_potential_rating),
            "Adaptability": scout.adaptability_rating,
            "Contract Yrs": scout.contract_years_remaining,
            "Salary ($M)": scout.annual_salary_millions,
            "Specialties": ", ".join(scout.traits),
        })
    return rows


def render_franchise_staff_center_v1(
    state: Any,
    *,
    active_team: str,
    controlled_teams: Iterable[str] = (),
    commit_state: Any = None,
) -> None:
    ensure_franchise_staff_state(state)
    team = str(active_team or "").strip().upper()
    controlled = {str(value).strip().upper() for value in controlled_teams}
    effects = team_staff_effects(state, team)

    st.markdown("## Staff & Organization")
    st.caption(
        "Head coaches are seeded from the real NBA as of Sep. 7, 2026. Supporting staff are "
        "persistent simulator personnel. Staff ratings drive development, health, rotations and "
        "the uncertainty in your Draft scouting reports."
    )

    metrics = st.columns(6)
    metrics[0].metric("Staff quality", f"{effects.overall_quality:.1f}")
    metrics[1].metric("Development", _dev_label(effects.development_modifier))
    metrics[2].metric("Injury risk", _pct_delta(effects.injury_risk_multiplier))
    metrics[3].metric("Recovery", _pct_delta(effects.recovery_multiplier))
    metrics[4].metric("Scout current", f"{effects.scouting_current_accuracy:.1f}")
    metrics[5].metric("Scout potential", f"{effects.scouting_potential_accuracy:.1f}")

    scout = lead_scout_member(state, team, ensure=True)
    st.markdown("### Scouting department")
    if scout is not None:
        top = st.columns([1.3, 1, 1, 1, 1])
        top[0].metric("Lead scout", scout.name)
        top[0].caption(f"{scout.years_experience} years experience")
        top[1].metric("Scout OVR", f"{scout.overall_rating:.1f}")
        top[1].caption(_scout_grade(scout.overall_rating))
        top[2].metric("Current evaluation", f"{scout.scouting_current_rating:.1f}")
        top[2].caption(f"Expected error ±{scouting_error_band(state, team):.1f}")
        top[3].metric("Potential evaluation", f"{scout.scouting_potential_rating:.1f}")
        top[3].caption(f"Expected error ±{scouting_error_band(state, team, potential=True):.1f}")
        top[4].metric("Contract", f"{scout.contract_years_remaining} yr")
        top[4].caption(f"${scout.annual_salary_millions:.2f}M/yr")
        st.caption(
            f"Specialties: {', '.join(scout.traits)}. "
            "Expected error bands describe uncertainty, not a reveal of any prospect's hidden true rating."
        )

    track = scouting_track_record_rows(state, team)
    if track:
        st.markdown("#### Scouting track record")
        frame = pd.DataFrame(track).rename(columns={
            "draft_year": "Draft",
            "lead_scout": "Lead Scout",
            "reports_graded": "Reports",
            "overall_mae": "OVR MAE",
            "potential_mae": "POT MAE",
            "strong_finds": "Strong Finds",
            "major_misses": "Major Misses",
        })
        keep = ["Draft", "Lead Scout", "Reports", "OVR MAE", "POT MAE", "Strong Finds", "Major Misses"]
        st.dataframe(frame[[col for col in keep if col in frame.columns]], hide_index=True, width="stretch")
        st.caption("Historical error is graded only after a Draft is complete, so hidden prospect truth never leaks into an active scouting cycle.")
    else:
        st.info("Scouting accuracy history will appear here after you complete a Draft class. Active-class hidden ratings remain private.")

    if team in controlled:
        st.markdown("#### Scout hiring market")
        st.caption(
            "Replace your lead scout with a persistent candidate. Staff salary is organizational spending and does not count against the NBA player salary cap. "
            "A new scout immediately changes future scouting uncertainty; existing reports are not magically rewritten."
        )
        candidates = scout_market_candidates(state, team)
        candidate_by_id = {row.staff_id: row for row in candidates}
        selected_id = st.selectbox(
            "Interview candidate",
            options=list(candidate_by_id),
            format_func=lambda sid: (
                f"{candidate_by_id[sid].name} · OVR {candidate_by_id[sid].overall_rating:.0f} · "
                f"Current {candidate_by_id[sid].scouting_current_rating:.0f} · Potential {candidate_by_id[sid].scouting_potential_rating:.0f}"
            ),
            key=f"franchise_scout_market_candidate_{team}",
        )
        selected = candidate_by_id[selected_id]
        compare = pd.DataFrame([
            {
                "Option": "Current staff",
                "Name": getattr(scout, "name", "Vacant"),
                "OVR": getattr(scout, "overall_rating", 0.0),
                "Current": getattr(scout, "scouting_current_rating", 0.0),
                "Current ±": scouting_error_band(state, team),
                "Potential": getattr(scout, "scouting_potential_rating", 0.0),
                "Potential ±": scouting_error_band(state, team, potential=True),
                "Salary ($M)": getattr(scout, "annual_salary_millions", 0.0),
                "Contract Yrs": getattr(scout, "contract_years_remaining", 0),
                "Specialties": ", ".join(getattr(scout, "traits", ()) or ()),
            },
            {
                "Option": "Candidate",
                "Name": selected.name,
                "OVR": selected.overall_rating,
                "Current": selected.scouting_current_rating,
                "Current ±": scouting_error_band_for_rating(selected.scouting_current_rating),
                "Potential": selected.scouting_potential_rating,
                "Potential ±": scouting_error_band_for_rating(selected.scouting_potential_rating),
                "Salary ($M)": selected.annual_salary_millions,
                "Contract Yrs": selected.contract_years_remaining,
                "Specialties": ", ".join(selected.traits),
            },
        ])
        st.dataframe(compare, hide_index=True, width="stretch")
        confirm = st.checkbox(
            f"I want to replace {getattr(scout, 'name', 'the current lead scout')} with {selected.name}.",
            key=f"franchise_scout_hire_confirm_{team}_{selected_id}",
        )
        if st.button(
            f"Hire {selected.name}",
            type="primary",
            width="stretch",
            disabled=not confirm,
            key=f"franchise_hire_scout_{team}_{selected_id}",
        ):
            hired = hire_lead_scout(state, team, selected_id)
            if callable(commit_state):
                commit_state(state, checkpoint_reason="franchise-lead-scout-hire-v1")
            st.session_state["franchise_notice"] = (
                f"Hired {hired.name} as {team}'s lead scout. Draft scouting uncertainty now reflects the new staff ratings."
            )
            st.rerun()

        with st.expander("Browse full scout market", expanded=False):
            st.dataframe(pd.DataFrame(_candidate_rows(candidates)), hide_index=True, width="stretch")
    else:
        st.caption("Scout hiring controls are available only for user-controlled teams.")

    st.markdown("### Full organization")
    st.caption(
        "Staff are grouped by responsibility so each view emphasizes the ratings that actually drive that role."
    )
    rows = staff_rows(state, team)
    frame = pd.DataFrame(rows).rename(columns={
        "role": "Role", "name": "Name", "age": "Age", "experience": "Experience",
        "contract_years": "Contract Yrs", "salary_m": "Salary ($M)", "overall": "OVR",
        "offense": "Offense", "defense": "Defense", "rotations": "Rotations",
        "development": "Development", "scout_current": "Scout Current",
        "scout_potential": "Scout Potential", "medical_prevention": "Prevention",
        "medical_recovery": "Recovery", "communication": "Communication",
        "adaptability": "Adaptability", "traits": "Traits", "personnel_basis": "Personnel",
    })

    role_text = frame.get("Role", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
    development_health_mask = (
        role_text.str.contains("development", regex=False)
        | role_text.str.contains("medical", regex=False)
        | role_text.str.contains("performance", regex=False)
        | role_text.str.contains("health", regex=False)
    )
    scouting_mask = role_text.str.contains("scout", regex=False)
    coaching_mask = ~(development_health_mask | scouting_mask)

    coaching_tab, development_tab, scouting_tab = st.tabs([
        "🏀 Coaching",
        "🩺 Development & Health",
        "🔎 Scouting",
    ])

    with coaching_tab:
        coaching = frame.loc[coaching_mask].copy()
        coaching_columns = [
            "Role", "Name", "Age", "Experience", "Contract Yrs", "Salary ($M)",
            "OVR", "Offense", "Defense", "Rotations", "Communication",
            "Adaptability", "Traits",
        ]
        if coaching.empty:
            st.info("No coaching personnel are currently assigned.")
        else:
            st.dataframe(
                coaching[[column for column in coaching_columns if column in coaching.columns]],
                hide_index=True,
                width="stretch",
            )
            st.caption("Coaching ratings shape scheme quality, game management, rotations and player communication.")

    with development_tab:
        development_health = frame.loc[development_health_mask].copy()
        development_columns = [
            "Role", "Name", "Age", "Experience", "Contract Yrs", "Salary ($M)",
            "OVR", "Development", "Prevention", "Recovery", "Communication",
            "Adaptability", "Traits",
        ]
        if development_health.empty:
            st.info("No development or performance personnel are currently assigned.")
        else:
            st.dataframe(
                development_health[[column for column in development_columns if column in development_health.columns]],
                hide_index=True,
                width="stretch",
            )
            st.caption("Development and performance staff influence growth, injury prevention and recovery quality.")

    with scouting_tab:
        scouting = frame.loc[scouting_mask].copy()
        if not scouting.empty:
            scouting["Current ±"] = scouting["Scout Current"].map(
                lambda value: scouting_error_band_for_rating(float(value))
            )
            scouting["Potential ±"] = scouting["Scout Potential"].map(
                lambda value: scouting_error_band_for_rating(float(value))
            )
        scouting_columns = [
            "Role", "Name", "Age", "Experience", "Contract Yrs", "Salary ($M)",
            "OVR", "Scout Current", "Current ±", "Scout Potential", "Potential ±",
            "Communication", "Adaptability", "Traits",
        ]
        if scouting.empty:
            st.info("No scouting personnel are currently assigned.")
        else:
            st.dataframe(
                scouting[[column for column in scouting_columns if column in scouting.columns]],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Lower ± values mean tighter expected scouting uncertainty. Active prospect truth remains hidden."
            )

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
        st.caption("Better scouts narrow uncertainty without ever making an active prospect's hidden rating perfectly known.")

    with st.expander("League staff comparison", expanded=False):
        league = pd.DataFrame(league_staff_summary(state)).rename(columns={
            "team": "Team", "overall_quality": "Staff OVR", "development_modifier": "Dev Modifier",
            "injury_risk_multiplier": "Injury Risk", "recovery_multiplier": "Recovery",
            "scouting_current_accuracy": "Scout Current", "scouting_potential_accuracy": "Scout Potential",
            "rotation_management": "Rotations", "offense_index": "Offense", "defense_index": "Defense",
        })
        st.dataframe(league.sort_values("Staff OVR", ascending=False), hide_index=True, width="stretch")

    st.caption(f"{STAFF_SYSTEM_VERSION} · {STAFF_UI_VERSION}")
