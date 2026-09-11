from __future__ import annotations

from typing import Any

import streamlit as st

from franchise_live_start_v1 import (
    LIVE_START_CONFIRMATION_PHRASE,
    build_live_starting_franchise,
    commit_live_franchise_start,
)


LIVE_START_UI_VERSION = "franchise-live-start-ui-v1.4-2026-09-09"

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


def _preview_summary(build: Any) -> dict[str, Any]:
    roster_sizes = {
        team: len(team_state.roster_player_ids)
        for team, team_state in build.simulation_state.teams.items()
    }
    profile_scope = getattr(
        build.simulation_state, "franchise_live_profile_scope_v1", {}
    ) or {}
    return {
        "version": build.version,
        "cutoff_date": build.cutoff_date,
        "reference_players": build.reference_players_applied,
        "materialized_players": build.materialized_players,
        "total_players": len(build.simulation_state.players),
        "rostered_players": build.rostered_players,
        "free_agents": build.free_agents,
        "two_way_players": build.two_way_players,
        "exhibit_10_players": build.exhibit_10_players,
        "unresolved_contracts": build.unresolved_current_contract_amounts,
        "sourced_overalls": int(
            profile_scope.get("externally_sourced_overall_count", 0) or 0
        ),
        "empirical_overalls": int(
            profile_scope.get("empirically_calibrated_overall_count", 0) or 0
        ),
        "source_informed_overalls": int(
            profile_scope.get("source_informed_overall_count", 0) or 0
        ),
        "modeled_overalls": int(
            profile_scope.get("fully_modeled_overall_count", 0) or 0
        ),
        "sourced_stat_profiles": int(
            profile_scope.get("detailed_statistical_profiles_sourced", 0) or 0
        ),
        "remaining_stat_profiles": int(
            profile_scope.get("detailed_statistical_profiles_remaining", 0) or 0
        ),
        "sourced_shooting_profiles": int(
            profile_scope.get("shooting_efficiency_profiles_sourced", 0) or 0
        ),
        "remaining_shooting_profiles": int(
            profile_scope.get("shooting_efficiency_profiles_remaining", 0) or 0
        ),
        "sourced_skill_profiles": int(
            profile_scope.get("broader_skill_ratings_source_informed", 0) or 0
        ),
        "calibrated_potential_profiles": int(
            profile_scope.get(
                "potential_profiles_age_and_production_calibrated", 0
            )
            or 0
        ),
        "draft_overrides": build.draft_asset_overrides,
        "international_rights": build.international_draft_rights,
        "schedule_games": build.schedule_games,
        "minimum_roster": min(roster_sizes.values()),
        "maximum_roster": max(roster_sizes.values()),
        "fingerprint": build.fingerprint,
    }


def render_live_franchise_start(runtime: Any, state: Any, trade_state: Any) -> None:
    completion_notice = st.session_state.pop(
        "franchise_live_start_completed_notice_v1", None
    )
    if completion_notice:
        st.success(completion_notice)

    st.divider()
    st.markdown("## Live September 7, 2026 Start")
    st.caption(
        "Build a current-day 2026-27 franchise universe while preserving this save. "
        "Nothing changes until the confirmed launch button is used; launch first creates "
        "a timestamped recovery copy of the active checkpoint."
    )

    active_universe = getattr(state, "franchise_start_universe_v1", {}) or {}
    if active_universe.get("universe_id") == "live-2026-09-07":
        st.success("This save is already using the Live September 7, 2026 universe.")
        return

    preview_key = "franchise_live_start_preview_v1"
    if st.button(
        "Build live-start preview",
        key="franchise_live_start_build_preview_v1",
    ):
        try:
            with st.spinner("Building and validating the live universe in memory..."):
                st.session_state[preview_key] = _preview_summary(
                    build_live_starting_franchise(runtime)
                )
        except Exception as exc:
            st.session_state.pop(preview_key, None)
            st.error(f"The live-start preview failed validation: {exc}")

    preview = st.session_state.get(preview_key)
    if not preview:
        st.info(
            "Preview is read-only. It validates every roster, the Trade Machine state, "
            "the schedule, and the new draft-right ownership before launch is enabled."
        )
        return

    metrics = st.columns(6)
    metrics[0].metric("Reference Moves", preview["reference_players"])
    metrics[1].metric("Players Added", preview["materialized_players"])
    metrics[2].metric("Total Players", preview["total_players"])
    metrics[3].metric("Rostered", preview["rostered_players"])
    metrics[4].metric("Free Agents", preview["free_agents"])
    metrics[5].metric("Schedule", f'{preview["schedule_games"]:,}')

    status_metrics = st.columns(6)
    status_metrics[0].metric("Two-Way", preview["two_way_players"])
    status_metrics[1].metric("Exhibit 10", preview["exhibit_10_players"])
    status_metrics[2].metric("Draft Changes", preview["draft_overrides"])
    status_metrics[3].metric("Intl. Rights", preview["international_rights"])
    status_metrics[4].metric("Smallest Roster", preview["minimum_roster"])
    status_metrics[5].metric("Largest Roster", preview["maximum_roster"])

    st.success(
        "Preview passed: all 30 teams have 8-21 players, the full 1,230-game schedule "
        "is retained, and the universe is ready at the opening of the 2026-27 season."
    )
    if preview["unresolved_contracts"]:
        contract_note = (
            f'- Leaves {preview["unresolved_contracts"]} newly reported contract amounts '
            "flagged for later confirmation instead of inventing salary figures."
        )
    else:
        contract_note = (
            "- Resolves all eight previously unknown standard-contract amounts, with base "
            "salary, cap charge, guaranteed money, and option years stored separately."
        )

    with st.expander("What this live start includes", expanded=False):
        st.markdown(
            "- Applies the 49-player September 7 transaction/reference overlay.\n"
            "- Adds 19 real players that were absent from the original runtime. "
            f'{preview["sourced_overalls"]} use released current external overall-rating '
            f'anchors; the other {preview["empirical_overalls"]} had no released roster '
            "rating and use clearly labeled, source-informed lower-roster proxies. "
            f'{preview["modeled_overalls"]} overalls remain without evidence calibration. '
            f'All {preview["sourced_stat_profiles"]} production baselines now retain '
            "source evidence and use conservative competition/sample adjustment; "
            f'all {preview["sourced_shooting_profiles"]} shooting-efficiency profiles '
            "are also source-informed and sample-adjusted. "
            f'All {preview["sourced_skill_profiles"]} broader skill profiles are now '
            "differentiated from those inputs, and all "
            f'{preview["calibrated_potential_profiles"]} potential/outlook profiles use '
            "the deterministic age-and-production calibration.\n"
            "- Applies three post-August 4 draft-capital changes and the Ismael Kamagate "
            "international draft-rights transfer.\n"
            "- Preserves the Clippers' five forfeited first-round picks.\n"
            + contract_note
        )
        st.caption(
            f'Deterministic preview fingerprint: {preview["fingerprint"][:16]}… · '
            f'UI: {LIVE_START_UI_VERSION}'
        )

    acknowledge = st.checkbox(
        "I understand this will replace the active save after creating a recovery backup.",
        key="franchise_live_start_ack_v1",
    )
    confirmation = st.text_input(
        f"Type {LIVE_START_CONFIRMATION_PHRASE} to confirm",
        key="franchise_live_start_phrase_v1",
        placeholder=LIVE_START_CONFIRMATION_PHRASE,
    )
    enabled = bool(
        acknowledge and confirmation.strip() == LIVE_START_CONFIRMATION_PHRASE
    )

    if st.button(
        "Launch Live September 7 Franchise",
        type="primary",
        disabled=not enabled,
        key="franchise_live_start_commit_v1",
    ):
        try:
            with st.status(
                "Backing up the current franchise and installing the live universe...",
                expanded=True,
            ):
                result = commit_live_franchise_start(
                    runtime,
                    state,
                    trade_state,
                    preferences=_preferences(),
                )
        except Exception as exc:
            st.error(f"Live start was blocked or rolled back. Detail: {exc}")
        else:
            backup = result.backup_directory
            _clear_franchise_session_for_restore()
            st.session_state["franchise_live_start_completed_notice_v1"] = (
                "Live September 7, 2026 franchise created. "
                f"Recovery backup: {backup}"
            )
            st.rerun()
