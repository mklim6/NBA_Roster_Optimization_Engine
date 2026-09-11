from __future__ import annotations

from typing import Any

import streamlit as st

from franchise_full_reset_v1 import (
    RESET_CONFIRMATION_PHRASE,
    build_full_reset_preview,
    commit_full_franchise_reset,
)


FULL_RESET_UI_VERSION = "franchise-full-reset-ui-v1-2026-08-11"

PREFERENCE_KEYS = (
    "franchise_pref_controlled_teams",
    "franchise_pref_active_team",
    "franchise_pref_simulation_policy",
    "franchise_pref_calendar_month",
    "franchise_pref_draft_class_strength",
)


def _preferences() -> dict[str, Any]:
    return {
        key: st.session_state[key]
        for key in PREFERENCE_KEYS
        if key in st.session_state
    }


def _clear_franchise_session_for_restore() -> None:
    # A rerun will restore the newly written durable checkpoint. Clearing both
    # franchise and simulator state prevents a stale in-memory object from winning.
    prefixes = (
        "franchise_",
        "_franchise_",
        "game_simulator_",
        "_game_simulator_",
        "trade_machine_",
        "_trade_machine_",
    )
    explicit = {
        "game_simulator_league_state",
        "trade_machine_league_state",
    }
    for key in list(st.session_state.keys()):
        if key in explicit or key.startswith(prefixes):
            st.session_state.pop(key, None)


def render_full_franchise_reset(runtime: Any, state: Any, trade_state: Any) -> None:
    completion_notice = st.session_state.pop("franchise_reset_completed_notice_v1", None)
    if completion_notice:
        st.success(completion_notice)

    st.divider()
    st.markdown("## New Franchise / Full League Reset")
    st.caption(
        "Start over from the original 2026-27 league universe. The current franchise is "
        "force-saved and copied to a timestamped recovery folder before anything is replaced."
    )

    source = build_full_reset_preview(state, trade_state)
    metrics = st.columns(6)
    metrics[0].metric("Current Season", source["season"])
    metrics[1].metric("Players", source["players"])
    metrics[2].metric("Archived Seasons", source["archived_seasons"])
    metrics[3].metric("Completed Games", source["completed_games"])
    metrics[4].metric("Retirements Logged", source["retirement_history"])
    metrics[5].metric("Trade Transactions", source["trade_transactions"])

    with st.expander("Reset details and recovery protection", expanded=False):
        st.markdown(
            "This reset creates a completely new live franchise. It removes generated seasons, "
            "completed games, postseason state, generated/drafted players, development history, "
            "retirement history, injuries, awards/history layers, draft history, and Trade Machine "
            "transactions from the **new live save**. The old save remains in the timestamped backup."
        )
        st.markdown(
            "The new league is rebuilt from the base 2026-27 runtime and receives a fresh deterministic "
            "1,230-game starting schedule. Career Lifecycle is initialized for the opening season."
        )

    acknowledge = st.checkbox(
        "I understand this replaces the live franchise after creating a recovery backup.",
        key="franchise_full_reset_ack_v1",
    )
    confirmation = st.text_input(
        f"Type {RESET_CONFIRMATION_PHRASE} to confirm",
        key="franchise_full_reset_phrase_v1",
        placeholder=RESET_CONFIRMATION_PHRASE,
    )
    enabled = bool(acknowledge and confirmation.strip() == RESET_CONFIRMATION_PHRASE)

    if st.button(
        "New Franchise / Reset League",
        type="primary",
        disabled=not enabled,
        key="franchise_full_reset_commit_v1",
    ):
        try:
            with st.status("Backing up the current franchise and rebuilding 2026-27...", expanded=True):
                result = commit_full_franchise_reset(
                    runtime,
                    state,
                    trade_state,
                    preferences=_preferences(),
                )
        except Exception as exc:
            st.error(f"Full franchise reset was blocked or rolled back. Detail: {exc}")
        else:
            backup = result.backup_directory
            _clear_franchise_session_for_restore()
            st.session_state["franchise_reset_completed_notice_v1"] = (
                f"New franchise created in {result.target_season}. Recovery backup: {backup}"
            )
            st.rerun()
