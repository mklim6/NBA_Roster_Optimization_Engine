from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import streamlit as st


UI_VERSION = "franchise-career-lifecycle-ui-v1-2026-08-11"


def _pct(value: Any) -> str:
    try:
        return f"{100.0 * float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def render_career_lifecycle_season_open(state: Any) -> None:
    season = str(getattr(getattr(state, "settings", None), "season_label", ""))
    intents = getattr(state, "career_intent_by_player_id", {}) or {}
    records = [
        record
        for record in intents.values()
        if isinstance(record, Mapping) and str(record.get("season", "")) == season
    ]
    farewells = [record for record in records if record.get("status") == "farewell_season"]
    considering = [record for record in records if record.get("status") == "considering_retirement"]
    if not farewells and not considering:
        return

    with st.expander("Career Watch", expanded=bool(farewells)):
        if farewells:
            st.markdown(f"**Farewell Tour · {season}**")
            st.caption(
                "These players announced before the season that this will be their final NBA year. "
                "A later contract offer will not reverse an announced farewell season."
            )
            table = pd.DataFrame(
                [
                    {
                        "Player": row.get("player_name", ""),
                        "Team": row.get("team", ""),
                        "Age": row.get("age", ""),
                        "OVR": row.get("overall", ""),
                        "Retirement Risk": _pct(row.get("retirement_risk", 0.0)),
                    }
                    for row in farewells
                ]
            )
            st.dataframe(table, hide_index=True, width="stretch")
        if considering:
            st.caption(
                f"{len(considering)} veteran(s) are currently in the considering-retirement state. "
                "The future re-signing system can lower their retirement probability with a strong return offer."
            )


def render_career_lifecycle_preview(preview: Any) -> None:
    if not isinstance(preview, Mapping):
        return
    lifecycle = preview.get("career_lifecycle")
    if not isinstance(lifecycle, Mapping):
        return
    retirement = lifecycle.get("retirement_plan", {})
    target = lifecycle.get("target_season_intents", {})
    if not isinstance(retirement, Mapping) or not isinstance(target, Mapping):
        return

    st.markdown("### Career Lifecycle")
    metrics = st.columns(6)
    metrics[0].metric("Retirements", int(retirement.get("retirement_count", 0) or 0))
    metrics[1].metric("Rostered", int(retirement.get("rostered_retirements", 0) or 0))
    metrics[2].metric("Free Agents", int(retirement.get("free_agent_retirements", 0) or 0))
    metrics[3].metric("Offers Saved", int(retirement.get("offer_saved_returns", 0) or 0))
    metrics[4].metric("Next-Year Farewells", int(target.get("farewell_seasons", 0) or 0))
    metrics[5].metric("Players After", int(lifecycle.get("players_after_transition", 0) or 0))

    retirees = retirement.get("retirements", []) or []
    saved = retirement.get("offer_saved_return_records", []) or []
    announcements = target.get("farewell_announcements", []) or []
    tabs = st.tabs(["Projected Retirements", "Return Offers", "Next Season Farewells"])

    with tabs[0]:
        if retirees:
            rows = []
            for row in retirees:
                rows.append(
                    {
                        "Player": row.get("player_name", ""),
                        "Team": row.get("team", ""),
                        "Age": row.get("age", ""),
                        "OVR": row.get("overall", ""),
                        "Career State": row.get("status_before", "active"),
                        "Base": _pct(row.get("base_retirement_probability", 0.0)),
                        "Offer Adj.": f"{100.0 * float(row.get('return_offer_modifier', 0.0)):+.1f} pts",
                        "Final": _pct(row.get("final_retirement_probability", 0.0)),
                        "Reason": row.get("decision_reason", ""),
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.caption("No retirements are projected in this transition.")

    with tabs[1]:
        if saved:
            st.success(
                f"{len(saved)} player(s) would have retired under the baseline roll but are projected to return because of a re-signing offer."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Player": row.get("player_name", ""),
                            "Team": row.get("team", ""),
                            "Base": _pct(row.get("base_retirement_probability", 0.0)),
                            "Offer Adjustment": f"{100.0 * float(row.get('return_offer_modifier', 0.0)):+.1f} pts",
                            "Final": _pct(row.get("final_retirement_probability", 0.0)),
                        }
                        for row in saved
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption(
                "No return offer currently changes a retirement outcome. This tab becomes interactive when the contract/re-signing system writes return offers into the lifecycle engine."
            )

    with tabs[2]:
        if announcements:
            st.info(
                f"{len(announcements)} player(s) are projected to announce a farewell season when {target.get('season', '')} opens."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Player": row.get("player_name", ""),
                            "Team": row.get("team", ""),
                            "Age": row.get("age", ""),
                            "OVR": row.get("overall", ""),
                            "Retirement Risk": _pct(row.get("retirement_risk", 0.0)),
                        }
                        for row in announcements
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No farewell-season announcements are projected for the new season.")
