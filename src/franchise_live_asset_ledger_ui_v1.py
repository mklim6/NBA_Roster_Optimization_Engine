from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from franchise_embedded_trade_center_ui_v2 import render_embedded_trade_center_v2
from franchise_trade_finder_ui_v1 import render_trade_finder_v1
from franchise_player_search_ui_v1 import render_player_search_v1
from franchise_ui_branding_v1 import rgba, team_colors, team_logo_url, team_name
from franchise_live_asset_ledger_v1 import (
    ASSET_LEDGER_VERSION,
    build_live_asset_ledger,
    team_draft_rows,
    team_forfeited_draft_rows,
    team_player_rows,
)


ASSET_LEDGER_UI_VERSION = (
    "franchise-live-asset-ledger-ui-v1.5-arena-shell-2026-08-12+"
    "pick-forfeitures-v1-2026-09-07+international-rights-v1-2026-09-08"
)


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"${number / 1_000:.0f}K"
    return f"${number:,.0f}"


def _player_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    display = []
    for row in rows:
        display.append(
            {
                "Player": row["player_name"],
                "Pos": row["position"],
                "Age": row["age"],
                "OVR": row["overall"],
                "POT": row["potential"],
                "Future": row["future_outlook"],
                "Role": row["role"],
                "Availability": str(row["availability"]).replace("_", " ").title(),
                "Career": str(row["career_status"]).replace("_", " ").title(),
                "Development": row["development_direction"],
                "Salary": _money(row["salary"]),
                "Yrs": row["years_remaining"],
                "Source": "Generated" if row["generated_player"] else "Baseline",
                "Asset Score": row["asset_score"],
                "Player ID": row["player_id"],
            }
        )
    return pd.DataFrame(display)


def _draft_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    display = []
    for row in rows:
        display.append(
            {
                "Year": row["draft_year"],
                "Rd": row["round"],
                "Origin": row["origin_team"],
                "Asset": row["display_name"],
                "Protection": row["protection"] or "—",
                "Swap": row["swap_status"] or "—",
                "Encumbrance": row["encumbrance"] or "—",
                "Tradability": row["tradability_status"],
                "Engine Ready": "Yes" if row["engine_ready"] else "No",
                "Evidence": row["evidence_source"],
                "Asset ID": row["asset_id"],
            }
        )
    return pd.DataFrame(display)


def _forfeiture_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Year": row["draft_year"],
                "Rd": row["round"],
                "Origin": row["origin_team"],
                "Forfeited Source": row["forfeited_source_asset_id"],
                "Reason": row["forfeiture_reason"],
                "Announced": row["forfeiture_announced_date"],
            }
            for row in rows
        ]
    )


def render_live_asset_ledger(
    runtime: Any,
    state: Any,
    trade_state: Any,
    active_team: str,
) -> None:
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    players = team_player_rows(ledger, active_team)
    picks = team_draft_rows(ledger, active_team)
    forfeited = team_forfeited_draft_rows(ledger, active_team)

    primary, secondary = team_colors(active_team)
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:18px;padding:18px 22px;border-radius:22px;border:1px solid {rgba(primary,.38)};background:linear-gradient(120deg,{rgba(primary,.35)},rgba(10,15,24,.94) 50%,{rgba(secondary,.18)});margin:4px 0 14px">
        <img src="{team_logo_url(active_team)}" style="width:76px;height:76px;object-fit:contain;filter:drop-shadow(0 8px 14px rgba(0,0,0,.35))">
        <div><div style="font-size:.7rem;letter-spacing:.16em;font-weight:900;color:#94a3b8">LIVE FRANCHISE ASSET ROOM</div><div style="font-size:2rem;font-weight:950;color:#fff">{team_name(active_team)} Front Office</div><div style="color:#cbd5e1;margin-top:4px">Roster, draft capital, trades, market search and player tracking in one persistent workspace.</div></div></div>""",
        unsafe_allow_html=True,
    )

    source_counts = {
        "generated": sum(bool(row["generated_player"]) for row in players),
        "salary": sum(float(row["salary"] or 0.0) for row in players),
        "engine_ready": sum(bool(row["engine_ready"]) for row in picks),
        "manual": sum(bool(row["manual_review_required"]) for row in picks),
    }
    metrics = st.columns(5)
    metrics[0].metric("Live Players", len(players))
    metrics[1].metric("Generated / Drafted", source_counts["generated"])
    metrics[2].metric("Salary Listed", _money(source_counts["salary"]))
    metrics[3].metric("Draft Assets", len(picks))
    metrics[4].metric("Engine-Ready Rights", source_counts["engine_ready"])

    views = (
        "My Assets",
        "Draft Capital",
        "Trade Builder",
        "Trade Finder",
        "Player Search",
    )
    view_key = "franchise_live_asset_ledger_view_v1"
    if st.session_state.get(view_key) not in views:
        st.session_state[view_key] = "My Assets"

    # st.tabs has no persistent key and can visually jump back to the first tab
    # on ordinary Streamlit widget reruns. A keyed segmented control preserves
    # the user's Trade Builder location while selecting players/picks or
    # confirming a transaction.
    if hasattr(st, "segmented_control"):
        selected_view = st.segmented_control(
            "Live asset view",
            views,
            key=view_key,
            label_visibility="collapsed",
            width="content",
        )
    else:
        selected_view = st.radio(
            "Live asset view",
            views,
            key=view_key,
            horizontal=True,
            label_visibility="collapsed",
        )

    if selected_view == "My Assets":
        if players:
            frame = _player_frame(players)
            st.dataframe(
                frame,
                hide_index=True,
                width="stretch",
                column_config={
                    "Age": st.column_config.NumberColumn(format="%.1f"),
                    "OVR": st.column_config.NumberColumn(format="%.1f"),
                    "POT": st.column_config.NumberColumn(format="%.1f"),
                    "Future": st.column_config.NumberColumn(format="%.1f"),
                    "Asset Score": st.column_config.NumberColumn(format="%.1f"),
                },
            )
            st.caption(
                "Franchise Asset Score V1 is a live comparison score using current "
                "OVR, potential, future outlook, and age runway. It is not a CBA rule "
                "or a final trade-value model."
            )
        else:
            st.info("This team currently has no rostered player assets in the live state.")

    elif selected_view == "Draft Capital":
        international_rights = [
            dict(row)
            for row in (
                getattr(state, "franchise_international_draft_rights_v1", {}) or {}
            ).values()
            if str(row.get("current_owner", "")).strip().upper() == active_team
        ]
        firsts = sum(int(row["round"]) == 1 for row in picks)
        seconds = sum(int(row["round"]) == 2 for row in picks)
        verified = sum(row["asset_type"] == "verified_stepien_physical_first" for row in picks)
        capital_metrics = st.columns(5)
        capital_metrics[0].metric("First-Round", firsts)
        capital_metrics[1].metric("Second-Round", seconds)
        capital_metrics[2].metric("Verified Firsts", verified)
        capital_metrics[3].metric("Manual / Bridge", source_counts["manual"])
        capital_metrics[4].metric("Forfeited", len(forfeited))
        if picks:
            st.dataframe(_draft_frame(picks), hide_index=True, width="stretch")
        else:
            st.info("No draft-capital rows are currently assigned to this team.")
        if forfeited:
            st.warning(
                f"{len(forfeited)} first-round pick(s) in this horizon are "
                "forfeited and excluded from trade construction and Draft order."
            )
            st.dataframe(
                _forfeiture_frame(forfeited),
                hide_index=True,
                width="stretch",
            )
        if international_rights:
            st.markdown("### International Draft Rights")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Player": row.get("player_name", "—"),
                            "Previous Owner": row.get("previous_owner", "—"),
                            "Current Owner": row.get("current_owner", "—"),
                            "Effective": row.get("effective_date", "—"),
                            "Evidence": row.get("evidence_source", "—"),
                            "Player ID": row.get("player_id", "—"),
                        }
                        for row in international_rights
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        st.caption(
            f"Rolling horizon: {ledger.next_draft_year}-{ledger.horizon_end_year}. "
            "‘Engine Ready’ means an existing canonical right passed its standalone "
            "right-evidence stage. Package Stepien, frozen-pick, salary, roster, apron, "
            "and full-CBA checks still run when a trade is built."
        )

    elif selected_view == "Trade Builder":
        render_embedded_trade_center_v2(
            runtime,
            state,
            trade_state,
            ledger,
            active_team,
        )

    elif selected_view == "Trade Finder":
        render_trade_finder_v1(
            runtime,
            state,
            trade_state,
            ledger,
            active_team,
        )
    else:
        render_player_search_v1(
            state,
            ledger,
        )

    st.caption(
        f"Asset ledger: {ASSET_LEDGER_VERSION} · UI: {ASSET_LEDGER_UI_VERSION}"
    )
