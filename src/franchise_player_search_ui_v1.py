from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from franchise_ui_branding_v1 import rgba, team_colors, team_logo_url, team_name

from franchise_live_asset_ledger_v1 import FranchiseAssetLedger
from franchise_player_search_v1 import (
    PLAYER_SEARCH_VERSION,
    build_player_search_profile,
    search_players,
)


PLAYER_SEARCH_UI_VERSION = "franchise-player-search-ui-v1.1-arena-profile-2026-08-12"


def _money(value: Any) -> str:
    try:
        if value is None:
            return "—"
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"${number / 1_000:.0f}K"
    return f"${number:,.0f}"


def render_player_search_v1(
    state: Any,
    ledger: FranchiseAssetLedger,
) -> None:
    st.markdown("### Player Search · Where Are They Now?")
    st.caption(
        "Search every player in the live franchise universe. Current location comes "
        "from the exact live roster/free-agent state. Older team history is reconstructed "
        "from archived game appearances, while Franchise Mode trades are shown from the "
        "exact transaction log."
    )

    query = st.text_input(
        "Search player",
        placeholder="Try: Luka, Wembanyama, Cameron Gibson...",
        key="franchise_player_search_v1_query",
    )
    matches = search_players(ledger, query, limit=40)

    if not query.strip():
        st.info("Type part of a player's first or last name to search the franchise universe.")
        return
    if not matches:
        st.warning("No live-franchise player matched that search.")
        return

    choices = {match.player_id: match for match in matches}
    selected_id = st.selectbox(
        "Matches",
        options=list(choices),
        format_func=lambda pid: (
            f"{choices[pid].player_name} · "
            f"{choices[pid].current_team or 'FA'} · "
            f"{choices[pid].position} · "
            f"OVR {choices[pid].overall:.1f}"
        ),
        key="franchise_player_search_v1_selected",
    )
    profile = build_player_search_profile(state, ledger, selected_id)

    current_team = profile.current_team or ""
    primary, secondary = team_colors(current_team)
    logo = team_logo_url(current_team) if current_team else "https://cdn.nba.com/logos/leagues/logo-nba.svg"
    location = team_name(current_team) if current_team else profile.current_location_label
    st.markdown(
        f"""<div style="display:flex;align-items:center;gap:16px;padding:17px 20px;border-radius:20px;border:1px solid {rgba(primary,.35)};background:linear-gradient(120deg,{rgba(primary,.30)},rgba(12,17,27,.96),{rgba(secondary,.14)});margin:8px 0 14px"><img src="{logo}" style="width:68px;height:68px;object-fit:contain"><div><div style="font-size:.7rem;letter-spacing:.13em;color:#94a3b8;font-weight:900">WHERE ARE THEY NOW?</div><div style="font-size:1.75rem;color:white;font-weight:950">{profile.player_name}</div><div style="color:#cbd5e1">{location} · {profile.position} · OVR {profile.overall:.1f}</div></div></div>""",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Player ID {profile.player_id} · "
        f"{'Generated / Drafted' if profile.generated_player else 'Baseline player'}"
    )

    cards = st.columns(6)
    cards[0].metric("Current", profile.current_location_label)
    cards[1].metric("Pos", profile.position)
    cards[2].metric("Age", "—" if profile.age is None else f"{profile.age:.1f}")
    cards[3].metric("OVR", f"{profile.overall:.1f}")
    cards[4].metric("POT", f"{profile.potential:.1f}")
    cards[5].metric("Salary", _money(profile.salary))

    detail_cols = st.columns(3)
    with detail_cols[0]:
        st.markdown("#### Current status")
        st.write(
            {
                "Roster": profile.roster_status.replace("_", " ").title(),
                "Career": profile.career_status.replace("_", " ").title(),
                "Availability": profile.availability.replace("_", " ").title(),
                "Contract": profile.contract_status.replace("_", " ").title() or "—",
                "Years remaining": profile.years_remaining,
            }
        )
    with detail_cols[1]:
        st.markdown("#### Current season")
        st.write(
            {
                "GP": profile.current_games_played,
                "PTS": profile.current_points_per_game,
                "REB": profile.current_rebounds_per_game,
                "AST": profile.current_assists_per_game,
                "Future outlook": round(profile.future_outlook, 1),
            }
        )
    with detail_cols[2]:
        st.markdown("#### Draft origin")
        if profile.draft_year or profile.draft_class_id:
            st.write(
                {
                    "Draft year": profile.draft_year,
                    "Draft team": profile.draft_team or "—",
                    "Round": profile.draft_round,
                    "Pick": profile.draft_pick,
                    "Class": profile.draft_class_id or "—",
                }
            )
        else:
            st.caption("No franchise draft metadata is stored for this player.")

    st.markdown("#### Where they've been")
    if profile.season_locations:
        history_frame = pd.DataFrame(
            [
                {
                    "Season": item.season_label,
                    "Team": item.team,
                    "Games observed": item.games_observed,
                    "Evidence": item.evidence,
                }
                for item in profile.season_locations
            ]
        )
        st.dataframe(history_frame, hide_index=True, width="stretch")
        st.caption(
            "Archived seasons do not store full roster snapshots. Historical teams are "
            "therefore inferred from the player's actual archived box-score appearances."
        )
    else:
        st.info("No archived team appearances are available for this player yet.")

    st.markdown("#### Franchise transaction history")
    if profile.transactions:
        tx_frame = pd.DataFrame(
            [
                {
                    "Transaction": event.transaction_id,
                    "Season": event.season_label,
                    "Day": event.day_index,
                    "From": event.from_team,
                    "To": event.to_team,
                }
                for event in profile.transactions
            ]
        )
        st.dataframe(tx_frame, hide_index=True, width="stretch")
    else:
        st.caption(
            "No player trade involving this player has been recorded by the live Franchise "
            "Mode transaction system yet."
        )

    if profile.development_history:
        with st.expander("Development history", expanded=False):
            st.dataframe(
                pd.DataFrame(list(profile.development_history)),
                hide_index=True,
                width="stretch",
            )

    st.caption(
        f"Player Search: {PLAYER_SEARCH_VERSION} · UI: {PLAYER_SEARCH_UI_VERSION}"
    )
