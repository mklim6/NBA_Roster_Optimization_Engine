from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
while str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

from franchise_offseason_market_season_v1 import (
    resolve_offseason_market_season,
    modeled_future_market_enabled,
)
from franchise_completed_season_contract_closeout_v1 import (
    completed_season_contract_closeout_required,
    commit_completed_season_contract_closeout_durably,
)
from franchise_free_agency_transaction_v1 import FreeAgencyOffer
from franchise_free_agency_transaction_v1_1 import team_guaranteed_payroll
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    resolve_free_agency_financial_environment,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    build_contract_legal_free_agency_preview,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    FREE_AGENCY_LIVE_UI_VERSION,
    FreeAgencyLiveSigningError,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    FREE_AGENCY_PLAYER_DECISION_UI_VERSION,
    evaluate_free_agent_offer_decision,
)
from franchise_resigning_negotiation_suite_v1 import (
    FRANCHISE_RESIGNING_NEGOTIATION_SUITE_VERSION,
    render_resigning_watchlist_v1,
    render_negotiation_room_intro_v1,
    render_player_reaction_v1,
)
from franchise_free_agency_visual_dashboard_v1 import (
    render_free_agency_visual_dashboard_v1,
)
from franchise_free_agency_shared_market_v1 import (
    FREE_AGENCY_SHARED_MARKET_UI_VERSION,
    FREE_AGENCY_SHARED_MARKET_VERSION,
    FreeAgencySharedMarketError,
    build_user_cpu_shared_market,
    commit_user_shared_market_winner_live,
    shared_market_matches_state_and_preview,
)
from franchise_free_agency_negotiation_rounds_v1 import (
    FREE_AGENCY_NEGOTIATION_ROUNDS_UI_VERSION,
    FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
    FreeAgencyNegotiationRoundsError,
    build_free_agency_negotiation_round,
    commit_negotiated_user_winner_live,
    negotiation_round_matches_state_and_preview,
)
from franchise_free_agency_interest_meter_v1 import (
    FREE_AGENCY_INTEREST_METER_UI_VERSION,
    FREE_AGENCY_INTEREST_METER_VERSION,
    build_player_interest_rows,
    interest_meter_value,
)
from franchise_free_agency_persistent_calendar_v1 import (
    FREE_AGENCY_PERSISTENT_CALENDAR_UI_VERSION,
    FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
    FreeAgencyPersistentCalendarError,
    advance_free_agency_day_durably,
    build_persistent_negotiation_result,
    commit_persistent_user_winner_live,
    free_agency_calendar_snapshot,
    initialize_free_agency_calendar_durably,
    persist_user_negotiation_durably,
    persistent_market_for_player_team,
)
from franchise_free_agency_rfa_offer_sheet_v1 import (
    DECISION_DECLINE,
    DECISION_MATCH,
    RFAOfferSheetError,
    build_external_offer_sheet_preview,
    commit_external_offer_sheet_live,
    pending_offer_sheet_for_player,
    pending_offer_sheets,
    resolve_offer_sheet_live,
)
from franchise_free_agency_rfa_offer_sheet_cpu_v1 import (
    advance_free_agency_day_with_rfa_offer_sheets_durably,
)
# Compatibility marker for superseded Player Decisions V1 validator:
# evaluate_free_agent_offer_decision · commit_player_accepted_free_agency_preview_live(
# Live Signing V1 compatibility marker: commit_contract_legal_free_agency_preview_live
from franchise_free_agency_ui_v1 import (
    FREE_AGENCY_UI_EXECUTION_BOUNDARY,
    FREE_AGENCY_UI_VERSION,
    active_controlled_team,
    controlled_teams_from_checkpoint,
    free_agent_rows,
    free_agency_history_rows,
    isolated_offseason_preview_state,
    offer_signature,
    preview_matches_signature,
)
from franchise_free_agency_prior_salary_v1 import (
    apply_prior_salary_to_free_agent_rows,
)
from franchise_free_agency_rfa_qo_lifecycle_v1 import (
    ACTION_ISSUE_QO,
    ACTION_RENOUNCE_RIGHTS,
    ACTION_WITHDRAW_QO,
    RFAQOLifecycleError,
    commit_controlled_rfa_action_live,
    preview_controlled_rfa_action,
    rfa_market_metadata,
)
from franchise_free_agency_non_rfa_rights_lifecycle_v1 import (
    NonRFARightsLifecycleError,
    commit_controlled_non_rfa_renouncement_live,
    preview_controlled_non_rfa_renouncement,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_league_state_v1 import validate_simulation_league_state


FREE_AGENCY_WORKSPACE_VERSION = "franchise-free-agency-workspace-v1.3-visual-command-desk-2026-09-12"

def render_free_agency_workspace(
    *,
    checkpoint_override=None,
    active_team_override: str | None = None,
    controlled_teams_override=None,
    embedded: bool = False,
) -> None:
    if embedded:
        st.markdown("## Free Agency")
        st.caption(
            "Live Franchise Mode offseason workspace. Offers, negotiations, rights, qualifying offers, "
            "calendar advancement, and finalized signings operate on the durable franchise state."
        )
    else:
        st.markdown("# Free Agency")
        st.caption(
            "This is the same live Free Agency workspace used inside Franchise Mode. "
            "Franchise Mode is the primary game shell."
        )

    checkpoint = checkpoint_override
    if checkpoint is None:
        try:
            checkpoint = load_franchise_checkpoint()
        except Exception as exc:
            st.error(f"The durable Franchise Mode checkpoint could not be loaded: {exc}")
            st.stop()

    if checkpoint is None:
        st.warning("Create or restore a Franchise Mode checkpoint before using Free Agency.")
        st.stop()

    state = checkpoint.simulation_state
    try:
        validate_simulation_league_state(state)
    except Exception as exc:
        st.error(f"The durable franchise state is not valid: {exc}")
        st.stop()

    if completed_season_contract_closeout_required(state):
        # Standalone Free Agency can be opened without first revisiting Franchise
        # Mode. Enforce the same durable closeout gate here.
        if checkpoint_override is not None:
            st.error(
                "The embedded Franchise checkpoint requires completed-season closeout. "
                "Return to Franchise Mode once so the durable boundary can commit."
            )
            st.stop()
        try:
            commit_completed_season_contract_closeout_durably(
                state,
                checkpoint.trade_state,
                preferences=dict(getattr(checkpoint, "preferences", {}) or {}),
            )
            checkpoint = load_franchise_checkpoint()
            if checkpoint is None:
                raise RuntimeError("Closeout checkpoint could not be reloaded.")
            state = checkpoint.simulation_state
        except Exception as exc:
            st.error(f"Completed-season contract closeout failed safely: {exc}")
            st.stop()

    season = resolve_offseason_market_season(state)
    phase_obj = getattr(state, "phase", "")
    phase = str(getattr(phase_obj, "value", phase_obj)).strip().lower()
    controlled_teams = (
        list(controlled_teams_override)
        if controlled_teams_override is not None
        else controlled_teams_from_checkpoint(checkpoint, state)
    )
    active_team = (
        str(active_team_override).strip().upper()
        if active_team_override
        else active_controlled_team(checkpoint, controlled_teams)
    )
    if controlled_teams and active_team not in controlled_teams:
        active_team = controlled_teams[0]
    rows = free_agent_rows(state)
    # FRANCHISE_FLAGSHIP_OFFSEASON_EXPERIENCE_V1
    # Attach canonical rights/QO context to every market row.
    def _fa_flagship_dict_rows(value):
        output = []
        for item in list(value or ()):
            if isinstance(item, dict):
                output.append(item)
            elif hasattr(item, "__dict__"):
                output.append(vars(item))
        return output

    _fa_rfa_rights = _fa_flagship_dict_rows(
        getattr(state, "offseason_rfa_rights_qo_decisions_v1", ())
    )
    _fa_non_rfa_rights = _fa_flagship_dict_rows(
        getattr(state, "offseason_non_rfa_rights_decisions_v1", ())
    )
    _fa_market_amounts = _fa_flagship_dict_rows(
        getattr(state, "offseason_free_agent_amount_candidates_v1", ())
    )
    _fa_rights_by_id = {
        str(item.get("player_id") or "").strip(): item
        for item in (_fa_rfa_rights + _fa_non_rfa_rights)
    }
    _fa_market_by_id = {
        str(item.get("player_id") or "").strip(): item
        for item in _fa_market_amounts
    }
    for _fa_row in rows:
        _fa_pid = str(_fa_row.get("player_id") or "").strip()
        _fa_rights = _fa_rights_by_id.get(_fa_pid, {})
        _fa_market = _fa_market_by_id.get(_fa_pid, {})
        _fa_row["rights_classification"] = str(
            _fa_rights.get("rights_classification") or "not_applicable"
        ).strip()
        _fa_row["rights_decision"] = str(
            _fa_rights.get("rights_decision") or "not_applicable"
        ).strip()
        _fa_row["qo_decision"] = str(
            _fa_rights.get("qo_decision") or "not_applicable"
        ).strip()
        _fa_row["qo_amount"] = _fa_rights.get("qo_amount_2026_27")
        _fa_row["rights_charge"] = _fa_rights.get(
            "effective_charge_2026_27"
        )
        if _fa_row.get("last_salary") in (None, ""):
            for _fa_salary_key in (
                "prior_salary_2025_26",
                "prior_salary",
                "regular_salary_2025_26",
                "salary_2025_26",
            ):
                _fa_salary_value = _fa_market.get(_fa_salary_key)
                if isinstance(_fa_salary_value, (int, float)):
                    _fa_row["last_salary"] = float(_fa_salary_value)
                    break

    rows = apply_prior_salary_to_free_agent_rows(rows, state)

    # FRANCHISE_RFA_QO_WORKSPACE_INTEGRATION_V1
    # The verified 64-player RFA/QO board belongs only to the anchor 2026-27
    # market. A modeled future market must not reuse stale rights/QO rows.
    _fa_live_rfa_by_id = rfa_market_metadata(state)
    _fa_future_market_without_anchor_rfa = bool(
        modeled_future_market_enabled(state)
        and not _fa_live_rfa_by_id
    )
    if _fa_future_market_without_anchor_rfa:
        st.info(
            "Modeled future offseason market: the historical 2026-27 RFA/QO "
            "decision overlay is not carried forward. Free-agent offers, CPU "
            "competition, salary legality, negotiations, calendar advancement, "
            "and signings remain active."
        )
    for _fa_row in rows:
        _fa_pid = str(_fa_row.get("player_id") or "").strip()
        _fa_rfa_live = _fa_live_rfa_by_id.get(_fa_pid)
        _fa_row["restricted_free_agent"] = bool(_fa_rfa_live)
        if _fa_rfa_live:
            _fa_row["prior_team"] = _fa_rfa_live["prior_team"]
            _fa_row["rights_classification"] = _fa_rfa_live["rights_classification"]
            _fa_row["rights_decision"] = _fa_rfa_live["rights_decision"]
            _fa_row["qo_decision"] = _fa_rfa_live["qo_decision"]
            _fa_row["qo_amount"] = _fa_rfa_live["qo_amount_2026_27"]
            _fa_row["rights_charge"] = _fa_rfa_live["effective_charge_2026_27"]
            _fa_row["free_agent_amount"] = _fa_rfa_live["free_agent_amount_2026_27"]
        else:
            _fa_market_live = _fa_market_by_id.get(_fa_pid, {})
            if not modeled_future_market_enabled(state):
                _fa_row["prior_team"] = str(
                    _fa_market_live.get("prior_team") or ""
                ).strip().upper()
                _fa_row["free_agent_amount"] = _fa_market_live.get(
                    "free_agent_amount_2026_27"
                )
            else:
                # Do not reuse stale 2026-27 rights/market evidence in a modeled
                # future market. The negotiation suite may still show recent-team
                # presentation context from saved games, but never treats that as
                # rights or cap authority.
                _fa_row["prior_team"] = ""
                _fa_row["free_agent_amount"] = None

    environment = resolve_free_agency_financial_environment(state)
    calendar_snapshot = free_agency_calendar_snapshot(state)
    try:
        dashboard_payroll, _dashboard_payroll_detail = team_guaranteed_payroll(
            state,
            active_team,
        )
    except Exception:
        dashboard_payroll = None
    render_free_agency_visual_dashboard_v1(
        state=state,
        rows=rows,
        active_team=active_team,
        season=season or "Unknown",
        phase=phase or "offseason",
        payroll=dashboard_payroll,
        salary_cap=environment.salary_cap,
        calendar_day=(
            calendar_snapshot.offseason_day
            if calendar_snapshot.initialized
            else None
        ),
        active_negotiations=calendar_snapshot.active_market_count,
        financial_source=(
            "Canonical 2026-27"
            if environment.exact_anchor_season
            else "Modeled future market"
        ),
    )

    live_notice = st.session_state.pop("fa_live_signing_notice", None)
    if live_notice:
        st.success(live_notice)

    rfa_qo_notice = st.session_state.pop("fa_rfa_qo_notice", None)
    if rfa_qo_notice:
        st.success(rfa_qo_notice)

    non_rfa_rights_notice = st.session_state.pop("fa_non_rfa_rights_notice", None)
    if non_rfa_rights_notice:
        st.success(non_rfa_rights_notice)

    rfa_offer_sheet_notice = st.session_state.pop("fa_rfa_offer_sheet_notice", None)
    if rfa_offer_sheet_notice:
        st.success(rfa_offer_sheet_notice)

    calendar_notice = st.session_state.pop("fa_calendar_notice", None)
    if calendar_notice:
        st.success(calendar_notice)

    st.markdown("### Offseason free-agency calendar")
    cal1, cal2, cal3, cal4 = st.columns(4)
    cal1.metric("FA day", str(calendar_snapshot.offseason_day) if calendar_snapshot.initialized else "Not started")
    cal2.metric("Active negotiations", calendar_snapshot.active_market_count)
    cal3.metric("Archived markets", calendar_snapshot.archived_market_count)
    cal4.metric("Calendar revision", calendar_snapshot.revision)

    # FRANCHISE_RFA_OFFER_SHEET_WORKSPACE_CALENDAR_INTEGRATION_V1
    _pending_rfa_sheets = pending_offer_sheets(state)
    if _pending_rfa_sheets:
        st.markdown("### Restricted free-agent offer sheets")
        st.caption(
            "A pending offer sheet keeps the player in restricted free agency until "
            "the original team matches, declines, or its two-day response window expires."
        )
        for _sheet in _pending_rfa_sheets:
            _sheet_id = str(_sheet.get("offer_sheet_id") or "")
            _sheet_player = str(_sheet.get("player_name") or _sheet.get("player_id") or "RFA")
            _sheet_prior = str(_sheet.get("prior_team") or "").strip().upper()
            _sheet_offering = str(_sheet.get("offering_team") or "").strip().upper()
            _sheet_salary = float(_sheet.get("annual_salary") or 0.0)
            _sheet_years = int(_sheet.get("years") or 0)
            _sheet_deadline = int(_sheet.get("match_deadline_day") or 0)
            _sheet_current_day = int(calendar_snapshot.offseason_day) if calendar_snapshot.initialized else 0
            _sheet_days_left = _sheet_deadline - _sheet_current_day
            _sheet_expired = calendar_snapshot.initialized and _sheet_current_day > _sheet_deadline

            with st.container(border=True):
                st.markdown(
                    f"**{_sheet_player}** · ${_sheet_salary:,.0f} × {_sheet_years} years"
                )
                _os1, _os2, _os3, _os4 = st.columns(4)
                _os1.metric("Offering team", _sheet_offering)
                _os2.metric("Original team", _sheet_prior)
                _os3.metric("Response deadline", f"FA Day {_sheet_deadline}")
                _os4.metric(
                    "Window",
                    "Expired" if _sheet_expired else f"{max(_sheet_days_left, 0)} day(s) left",
                )

                if _sheet_prior in set(controlled_teams):
                    if _sheet_expired:
                        st.warning(
                            "Your right-of-first-refusal window has expired. "
                            "The sheet can only be finalized as declined."
                        )
                        if st.button(
                            "Finalize expired sheet · decline",
                            type="primary",
                            width="stretch",
                            key=f"fa_rfa_offer_sheet_expired_user_{_sheet_id}",
                        ):
                            try:
                                with st.spinner(
                                    "Finalizing expired RFA offer sheet and verifying durable state..."
                                ):
                                    _resolution = resolve_offer_sheet_live(
                                        offer_sheet_id=_sheet_id,
                                        decision=DECISION_DECLINE,
                                        authority="user",
                                    )
                                    _refreshed = load_franchise_checkpoint()
                                    if _refreshed is None:
                                        raise RFAOfferSheetError(
                                            "The expired sheet resolved, but the checkpoint could not be reloaded."
                                        )
                                    st.session_state["franchise_simulation_league_state"] = _refreshed.simulation_state
                                    st.session_state["franchise_trade_league_state"] = _refreshed.trade_state
                                    st.session_state["fa_rfa_offer_sheet_notice"] = (
                                        f"{_resolution.offer_sheet_id}: {_resolution.player_name} · "
                                        f"original team declined · {_resolution.destination_team} receives the player."
                                    )
                            except Exception as _offer_sheet_exc:
                                st.error(
                                    "The expired RFA offer sheet was not finalized. "
                                    f"Detail: {_offer_sheet_exc}"
                                )
                            else:
                                st.rerun()
                    else:
                        st.info(
                            "Your team owns the right of first refusal. Match uses the "
                            "exact principal terms of the signed offer sheet."
                        )
                        _match_col, _decline_col = st.columns(2)
                        if _match_col.button(
                            "Match offer sheet",
                            type="primary",
                            width="stretch",
                            key=f"fa_rfa_offer_sheet_match_{_sheet_id}",
                        ):
                            try:
                                with st.spinner(
                                    "Matching RFA offer sheet and verifying contract/ownership..."
                                ):
                                    _resolution = resolve_offer_sheet_live(
                                        offer_sheet_id=_sheet_id,
                                        decision=DECISION_MATCH,
                                        authority="user",
                                    )
                                    _refreshed = load_franchise_checkpoint()
                                    if _refreshed is None:
                                        raise RFAOfferSheetError(
                                            "The match saved, but the checkpoint could not be reloaded."
                                        )
                                    st.session_state["franchise_simulation_league_state"] = _refreshed.simulation_state
                                    st.session_state["franchise_trade_league_state"] = _refreshed.trade_state
                                    st.session_state["fa_rfa_offer_sheet_notice"] = (
                                        f"{_resolution.offer_sheet_id}: matched {_resolution.player_name} "
                                        f"at ${_resolution.annual_salary:,.0f} × {_resolution.years} years."
                                    )
                            except Exception as _offer_sheet_exc:
                                st.error(
                                    "The RFA offer sheet was not matched. "
                                    f"Detail: {_offer_sheet_exc}"
                                )
                            else:
                                st.rerun()

                        if _decline_col.button(
                            "Decline offer sheet",
                            width="stretch",
                            key=f"fa_rfa_offer_sheet_decline_{_sheet_id}",
                        ):
                            try:
                                with st.spinner(
                                    "Declining RFA offer sheet and verifying final destination..."
                                ):
                                    _resolution = resolve_offer_sheet_live(
                                        offer_sheet_id=_sheet_id,
                                        decision=DECISION_DECLINE,
                                        authority="user",
                                    )
                                    _refreshed = load_franchise_checkpoint()
                                    if _refreshed is None:
                                        raise RFAOfferSheetError(
                                            "The decline saved, but the checkpoint could not be reloaded."
                                        )
                                    st.session_state["franchise_simulation_league_state"] = _refreshed.simulation_state
                                    st.session_state["franchise_trade_league_state"] = _refreshed.trade_state
                                    st.session_state["fa_rfa_offer_sheet_notice"] = (
                                        f"{_resolution.offer_sheet_id}: declined {_resolution.player_name}; "
                                        f"{_resolution.destination_team} receives the player."
                                    )
                            except Exception as _offer_sheet_exc:
                                st.error(
                                    "The RFA offer sheet was not declined. "
                                    f"Detail: {_offer_sheet_exc}"
                                )
                            else:
                                st.rerun()
                elif _sheet_offering in set(controlled_teams):
                    if _sheet_expired:
                        st.success(
                            "The CPU original team did not match within the response window. "
                            "The sheet can now finalize to your team."
                        )
                        if st.button(
                            "Finalize expired CPU response · player joins your team",
                            type="primary",
                            width="stretch",
                            key=f"fa_rfa_offer_sheet_expired_cpu_{_sheet_id}",
                        ):
                            try:
                                with st.spinner(
                                    "Finalizing expired CPU RFA response and verifying durable state..."
                                ):
                                    _resolution = resolve_offer_sheet_live(
                                        offer_sheet_id=_sheet_id,
                                        decision=DECISION_DECLINE,
                                        authority="cpu",
                                    )
                                    _refreshed = load_franchise_checkpoint()
                                    if _refreshed is None:
                                        raise RFAOfferSheetError(
                                            "The expired CPU response resolved, but the checkpoint could not be reloaded."
                                        )
                                    st.session_state["franchise_simulation_league_state"] = _refreshed.simulation_state
                                    st.session_state["franchise_trade_league_state"] = _refreshed.trade_state
                                    st.session_state["fa_rfa_offer_sheet_notice"] = (
                                        f"{_resolution.offer_sheet_id}: {_resolution.player_name} joins "
                                        f"{_resolution.destination_team} after the original team's response window expired."
                                    )
                            except Exception as _offer_sheet_exc:
                                st.error(
                                    "The expired CPU response was not finalized. "
                                    f"Detail: {_offer_sheet_exc}"
                                )
                            else:
                                st.rerun()
                    else:
                        st.info(
                            f"Awaiting {_sheet_prior}'s CPU right-of-first-refusal response. "
                            "The player has not changed teams and the sheet remains pending."
                        )
                else:
                    st.caption(
                        "This offer sheet does not involve the currently controlled team."
                    )

    if phase != "offseason":
        st.info(
            "The persistent free-agency calendar is locked until the durable franchise reaches the actual offseason. "
            "Hypothetical offer/negotiation previews remain read-only and are never written to the checkpoint."
        )
    elif not calendar_snapshot.initialized:
        if st.button("Start free agency calendar", type="primary", key="fa_calendar_start"):
            try:
                write = initialize_free_agency_calendar_durably()
                refreshed = load_franchise_checkpoint()
                if refreshed is None:
                    raise FreeAgencyPersistentCalendarError("The calendar saved, but the checkpoint could not be reloaded.")
                st.session_state["franchise_simulation_league_state"] = refreshed.simulation_state
                st.session_state["franchise_trade_league_state"] = refreshed.trade_state
                st.session_state["fa_calendar_notice"] = (
                    f"Free agency calendar started at Day {write.offseason_day}. Durable calendar revision {write.revision}."
                )
            except Exception as exc:
                st.error(f"The free-agency calendar was not started. Detail: {exc}")
            else:
                st.rerun()
    else:
        advance_col, calendar_help_col = st.columns([1.0, 2.0])
        with advance_col:
            advance_day = st.button(
                "Advance free agency day",
                type="primary",
                width="stretch",
                key="fa_calendar_advance_day",
                help="Advances every active persisted negotiation at most one round, then saves and reload-verifies the checkpoint.",
            )
        with calendar_help_col:
            # FRANCHISE_RFA_OFFER_SHEET_CPU_DEADLINE_AUTOMATION_V1
            st.caption(
                "Advancing a day still does not silently sign an ordinary Free Agency negotiation winner. "
                "It also advances RFA response windows: CPU original teams may match through the existing "
                "front-office/offer model, and an expired unmatched sheet finalizes as a decline."
            )
        if advance_day:
            try:
                with st.spinner("Advancing the durable free-agency calendar and verifying checkpoint persistence..."):
                    advance_result = advance_free_agency_day_with_rfa_offer_sheets_durably()
                    if advance_result.offer_sheets_resolved:
                        st.session_state["fa_rfa_offer_sheet_notice"] = advance_result.resolution_notice
                    refreshed = load_franchise_checkpoint()
                    if refreshed is None:
                        raise FreeAgencyPersistentCalendarError("The day advanced, but the checkpoint could not be reloaded.")
                    st.session_state["franchise_simulation_league_state"] = refreshed.simulation_state
                    st.session_state["franchise_trade_league_state"] = refreshed.trade_state
                    st.session_state.pop("fa_ui_preview", None)
                    st.session_state.pop("fa_ui_preview_signature", None)
                    st.session_state.pop("fa_negotiation_round", None)
                    st.session_state["fa_calendar_notice"] = (
                        f"Advanced to Free Agency Day {advance_result.current_day}: "
                        f"{advance_result.markets_advanced} market(s) advanced, "
                        f"{advance_result.markets_ready_user} user-ready, "
                        f"{advance_result.markets_ready_cpu} CPU-ready, "
                        f"{advance_result.markets_closed} closed."
                    )
            except Exception as exc:
                st.error(f"The free-agency day was not advanced. Detail: {exc}")
            else:
                st.rerun()

    if calendar_snapshot.active_markets:
        with st.expander("Active persistent negotiations", expanded=True):
            active_rows = [
                {
                    "Player": row.player_name,
                    "Team": row.user_team_abbreviation,
                    "Salary": row.annual_salary,
                    "Years": row.years,
                    "Round": f"{row.current_round}/{row.max_rounds}",
                    "Player response": row.player_response.replace("_", " ").title(),
                    "Market leader": row.winner_team_abbreviation or "None",
                    "CPU bids": row.active_cpu_offer_count,
                    "Last updated day": row.last_updated_day,
                }
                for row in calendar_snapshot.active_markets
            ]
            st.dataframe(
                pd.DataFrame(active_rows),
                width="stretch",
                hide_index=True,
                column_config={"Salary": st.column_config.NumberColumn(format="$%,.0f")},
            )

    if not controlled_teams:
        st.warning(
            "The durable checkpoint does not identify a user-controlled team. "
            "Offer previews remain visible, but no team is granted implicit control. "
            "Open Franchise Mode and save your controlled-team preference first."
        )

    # FRANCHISE_RESIGNING_NEGOTIATION_SUITE_V1
    render_resigning_watchlist_v1(
        state,
        rows,
        active_team=active_team,
    )

    market_section = st.container()
    offer_section = st.container()

    with market_section:
        st.markdown("### Available players")
        _fa_retained_count = sum(
            1
            for _row in (_fa_rfa_rights + _fa_non_rfa_rights)
            if float(_row.get("effective_charge_2026_27") or 0.0) > 0.0
        )
        _fa_qo_count = sum(
            1
            for _row in _fa_rfa_rights
            if str(_row.get("qo_decision") or "").strip() == "issue_qo"
        )
        st.caption(
            f"Canonical offseason market · {len(rows)} available players · "
            f"{_fa_retained_count} retained rights holds · "
            f"{_fa_qo_count} active qualifying offers"
        )
        search = st.text_input("Search free agents", placeholder="Name or position", key="fa_ui_search")
        position_values = sorted({str(row["position"]) for row in rows if row["position"]})
        position_filter = st.multiselect("Position", position_values, key="fa_ui_positions")

        filtered = rows
        if search.strip():
            needle = search.strip().casefold()
            filtered = [
                row for row in filtered
                if needle in row["player_name"].casefold()
                or needle in row["position"].casefold()
            ]
        if position_filter:
            selected_positions = set(position_filter)
            filtered = [row for row in filtered if row["position"] in selected_positions]

        table = pd.DataFrame(filtered)
        if table.empty:
            st.info("No free agents match the current filters.")
        else:
            display = table[[
                "player_name",
                "position",
                "age",
                "overall",
                "potential",
                "restricted_free_agent",
                "rights_classification",
                "rights_decision",
                "qo_decision",
                "qo_amount",
                "rights_charge",
                "last_salary",
            ]].rename(columns={
                "player_name": "Player",
                "position": "Pos",
                "age": "Age",
                "overall": "OVR",
                "potential": "Potential",
                "restricted_free_agent": "RFA",
                "rights_classification": "Rights",
                "rights_decision": "Rights status",
                "qo_decision": "QO status",
                "qo_amount": "QO amount",
                "rights_charge": "Rights/QO charge",
                "last_salary": "Prior salary",
            })
            display["RFA"] = display["RFA"].map({True: "Yes", False: ""})
            for _column in ("Rights", "Rights status", "QO status"):
                display[_column] = (
                    display[_column]
                    .fillna("")
                    .astype(str)
                    .str.replace("_", " ", regex=False)
                    .str.title()
                )
            st.dataframe(
                display,
                width="stretch",
                hide_index=True,
                column_config={
                    "Age": st.column_config.NumberColumn(format="%.1f"),
                    "OVR": st.column_config.NumberColumn(format="%.1f"),
                    "Potential": st.column_config.NumberColumn(format="%.1f"),
                    "QO amount": st.column_config.NumberColumn(format="$%,.0f"),
                    "Rights/QO charge": st.column_config.NumberColumn(format="$%,.0f"),
                    "Prior salary": st.column_config.NumberColumn(format="$%,.0f"),
                },
            )

    # FRANCHISE_OFFER_BUILDER_LAYOUT_POLISH_V1
    st.markdown("---")

    with offer_section:
        st.markdown("### Offer builder")
        st.caption("Full-width negotiation workspace for easier building, previewing and reviewing player reactions.")
        if not rows:
            st.info("No free agents are available in the durable franchise state.")
            st.stop()

        player_options = {f'{row["player_name"]} · {row["position"]} · OVR {row["overall"]:.1f}' if row["overall"] is not None else f'{row["player_name"]} · {row["position"]}': row for row in rows}
        player_label = st.selectbox("Player", list(player_options), key="fa_ui_player")
        selected_player = player_options[player_label]

        if controlled_teams:
            default_team_index = controlled_teams.index(active_team) if active_team in controlled_teams else 0
            team = st.selectbox("Signing team", controlled_teams, index=default_team_index, key="fa_ui_team")
        else:
            team = ""
            st.selectbox("Signing team", ["No controlled team available"], disabled=True, key="fa_ui_team_disabled")

        persistent_record = (
            persistent_market_for_player_team(state, selected_player["player_id"], team)
            if team and phase == "offseason"
            else None
        )

        _selected_pid = str(selected_player["player_id"]).strip()
        _selected_rfa = _fa_live_rfa_by_id.get(_selected_pid)
        _selected_is_rfa = _selected_rfa is not None
        _selected_rfa_prior_team = (
            str(_selected_rfa["prior_team"]).strip().upper()
            if _selected_rfa
            else ""
        )
        rfa_direct_signing_allowed = (
            not _selected_is_rfa
            or team == _selected_rfa_prior_team
        )

        _rsn_context = render_negotiation_room_intro_v1(
            state,
            selected_player,
            signing_team=team,
            persistent_record=persistent_record,
        )

        if _selected_is_rfa:
            st.markdown("#### Restricted free agency")
            _r1, _r2, _r3 = st.columns(3)
            _r1.metric("Prior team", _selected_rfa_prior_team)
            _r2.metric(
                "QO",
                (
                    f"${float(_selected_rfa['qo_amount_2026_27']):,.0f}"
                    if isinstance(_selected_rfa.get("qo_amount_2026_27"), (int, float))
                    else "Not applicable"
                ),
            )
            _r3.metric(
                "Current rights/QO charge",
                f"${float(_selected_rfa['effective_charge_2026_27']):,.0f}",
            )
            st.caption(
                "Rights: "
                f"{str(_selected_rfa['rights_classification']).replace('_', ' ').title()} · "
                f"{str(_selected_rfa['rights_decision']).replace('_', ' ').title()} · "
                f"QO: {str(_selected_rfa['qo_decision']).replace('_', ' ').title()}"
            )

            if _selected_rfa_prior_team in set(controlled_teams):
                _rights = str(_selected_rfa["rights_decision"])
                _qo = str(_selected_rfa["qo_decision"])

                if persistent_record is not None:
                    st.info(
                        "This player already has a persisted negotiation. A rights/QO "
                        "decision changes the durable financial state, so the negotiation "
                        "must rebuild from the new fingerprint afterward."
                    )

                _action_specs = []
                if _rights == "retain_rights" and _qo == "issue_qo":
                    _action_specs.append(
                        (
                            ACTION_WITHDRAW_QO,
                            "Confirm and withdraw qualifying offer",
                            "Withdraw the QO while retaining the player's rights.",
                        )
                    )
                elif _rights == "retain_rights" and _qo == "do_not_issue_qo":
                    _action_specs.append(
                        (
                            ACTION_ISSUE_QO,
                            "Confirm and issue qualifying offer",
                            "Issue the verified QO while retaining the player's rights.",
                        )
                    )

                if _rights == "retain_rights":
                    _action_specs.append(
                        (
                            ACTION_RENOUNCE_RIGHTS,
                            "Confirm and renounce rights",
                            "Irreversible: removes the retained rights/QO charge and makes the QO inapplicable.",
                        )
                    )
                else:
                    st.warning(
                        "Rights have been renounced. This decision is irreversible "
                        "in the current offseason lifecycle."
                    )

                for _action, _label, _help in _action_specs:
                    try:
                        _action_preview = preview_controlled_rfa_action(
                            checkpoint,
                            player_id=_selected_pid,
                            action=_action,
                        )
                    except RFAQOLifecycleError as _rfa_preview_exc:
                        st.caption(f"{_label}: unavailable · {_rfa_preview_exc}")
                        continue

                    _delta = float(_action_preview.charge_delta)
                    _delta_text = (
                        f"+${abs(_delta):,.0f}"
                        if _delta > 0
                        else (
                            f"-${abs(_delta):,.0f}"
                            if _delta < 0
                            else "$0"
                        )
                    )
                    if st.button(
                        f"{_label} · team salary {_delta_text}",
                        width="stretch",
                        key=f"fa_rfa_qo_action_{_selected_pid}_{_action}",
                        help=(
                            f"{_help} This is the final decision. Clicking commits "
                            "immediately, reload-verifies the checkpoint, and restores "
                            "the exact pre-decision primary and backup files on failure."
                        ),
                    ):
                        try:
                            with st.spinner(
                                "Committing RFA/QO decision and verifying durable checkpoint..."
                            ):
                                _result = commit_controlled_rfa_action_live(
                                    player_id=_selected_pid,
                                    action=_action,
                                    confirmation_token=_action_preview.confirmation_token,
                                )
                                _refreshed = load_franchise_checkpoint()
                                if _refreshed is None:
                                    raise RFAQOLifecycleError(
                                        "The RFA/QO decision saved, but the checkpoint "
                                        "could not be reloaded into the UI."
                                    )
                                st.session_state["franchise_simulation_league_state"] = (
                                    _refreshed.simulation_state
                                )
                                st.session_state["franchise_trade_league_state"] = (
                                    _refreshed.trade_state
                                )
                                for _key in (
                                    "fa_ui_preview",
                                    "fa_ui_preview_signature",
                                    "fa_ui_preview_hypothetical",
                                    "fa_player_decision",
                                    "fa_shared_market",
                                    "fa_negotiation_round",
                                ):
                                    st.session_state.pop(_key, None)
                                st.session_state["fa_rfa_qo_notice"] = (
                                    f"{_result.transaction_id}: "
                                    f"{_result.player_name} · "
                                    f"{_result.action.replace('_', ' ')} · "
                                    f"team salary delta ${_result.charge_delta:,.0f}."
                                )
                                st.session_state["franchise_notice"] = (
                                    st.session_state["fa_rfa_qo_notice"]
                                )
                        except Exception as _rfa_commit_exc:
                            st.error(
                                "The RFA/QO decision was not committed. "
                                f"Detail: {_rfa_commit_exc}"
                            )
                        else:
                            st.rerun()

            if not rfa_direct_signing_allowed:
                st.warning(
                    "This player is an RFA whose prior team is "
                    f"{_selected_rfa_prior_team}. A contract from {team or 'this team'} "
                    "must use the offer-sheet / right-of-first-refusal lifecycle. "
                    "Build the terms below, then use the dedicated offer-sheet action."
                )

        # FRANCHISE_NON_RFA_RIGHTS_WORKSPACE_INTEGRATION_V1
        _selected_non_rfa = next(
            (
                _row
                for _row in _fa_non_rfa_rights
                if str(_row.get("player_id") or "").strip() == _selected_pid
            ),
            None,
        )
        if _selected_non_rfa is not None:
            _non_rfa_prior_team = str(
                _selected_non_rfa.get("prior_team") or ""
            ).strip().upper()
            _non_rfa_rights = str(
                _selected_non_rfa.get("rights_classification") or "not_applicable"
            ).strip()
            _non_rfa_decision = str(
                _selected_non_rfa.get("rights_decision") or "not_applicable"
            ).strip()
            _non_rfa_charge = float(
                _selected_non_rfa.get("effective_charge_2026_27") or 0.0
            )

            if _non_rfa_decision in {
                "retain_rights_by_default",
                "retain_rights",
                "renounce_rights",
            }:
                st.markdown("#### Non-restricted free-agent rights")
                _nr1, _nr2, _nr3 = st.columns(3)
                _nr1.metric(
                    "Prior team",
                    _non_rfa_prior_team or "Unknown",
                )
                _nr2.metric(
                    "Rights",
                    _non_rfa_rights.replace("_", " ").title(),
                )
                _nr3.metric(
                    "Current rights charge",
                    f"${_non_rfa_charge:,.0f}",
                )
                st.caption(
                    "Rights status: "
                    f"{_non_rfa_decision.replace('_', ' ').title()}"
                )

                if _non_rfa_decision == "renounce_rights":
                    st.warning(
                        "These non-RFA rights have been renounced. This decision is "
                        "irreversible in the current offseason lifecycle."
                    )
                elif _non_rfa_prior_team in set(controlled_teams):
                    if persistent_record is not None:
                        st.info(
                            "This player already has a persisted negotiation. Renouncing "
                            "rights changes the durable financial state, so the negotiation "
                            "must rebuild from the new fingerprint afterward."
                        )

                    try:
                        _non_rfa_preview = preview_controlled_non_rfa_renouncement(
                            checkpoint,
                            player_id=_selected_pid,
                        )
                    except NonRFARightsLifecycleError as _non_rfa_preview_exc:
                        st.caption(
                            "Confirm and renounce non-RFA rights: unavailable · "
                            f"{_non_rfa_preview_exc}"
                        )
                    else:
                        if st.button(
                            "Confirm and renounce non-RFA rights · "
                            f"team salary -${_non_rfa_preview.current_charge:,.0f}",
                            width="stretch",
                            key=f"fa_non_rfa_rights_renounce_{_selected_pid}",
                            help=(
                                "Irreversible for the current offseason. This is the final "
                                "decision: clicking commits immediately, releases the exact "
                                "verified rights charge, reload-verifies the durable checkpoint, "
                                "and restores the exact pre-decision primary and backup files "
                                "on failure."
                            ),
                        ):
                            try:
                                with st.spinner(
                                    "Renouncing non-RFA rights and verifying durable checkpoint..."
                                ):
                                    _non_rfa_result = (
                                        commit_controlled_non_rfa_renouncement_live(
                                            _non_rfa_preview,
                                            confirmation_token=(
                                                _non_rfa_preview.confirmation_token
                                            ),
                                        )
                                    )
                                    _refreshed = load_franchise_checkpoint()
                                    if _refreshed is None:
                                        raise NonRFARightsLifecycleError(
                                            "The non-RFA rights decision saved, but the "
                                            "checkpoint could not be reloaded into the UI."
                                        )
                                    st.session_state[
                                        "franchise_simulation_league_state"
                                    ] = _refreshed.simulation_state
                                    st.session_state[
                                        "franchise_trade_league_state"
                                    ] = _refreshed.trade_state
                                    for _key in (
                                        "fa_ui_preview",
                                        "fa_ui_preview_signature",
                                        "fa_ui_preview_hypothetical",
                                        "fa_player_decision",
                                        "fa_shared_market",
                                        "fa_negotiation_round",
                                        "fa_rfa_offer_sheet_preview",
                                    ):
                                        st.session_state.pop(_key, None)

                                    st.session_state["fa_non_rfa_rights_notice"] = (
                                        f"{_non_rfa_result.transaction_id}: "
                                        f"renounced {_non_rfa_result.player_name}'s "
                                        f"non-RFA rights · team salary "
                                        f"-${_non_rfa_result.released_charge:,.0f}."
                                    )
                                    st.session_state["franchise_notice"] = (
                                        st.session_state[
                                            "fa_non_rfa_rights_notice"
                                        ]
                                    )
                            except Exception as _non_rfa_commit_exc:
                                st.error(
                                    "The non-RFA rights decision was not committed. "
                                    f"Detail: {_non_rfa_commit_exc}"
                                )
                            else:
                                st.rerun()

        # A negotiation-room quick action stages a revised salary and forces
        # the normal preview / legality / negotiation flow to rebuild.
        _rsn_pending_salary = st.session_state.pop(
            "fa_resign_suite_pending_salary",
            None,
        )
        if _rsn_pending_salary is not None:
            st.session_state["fa_ui_salary"] = float(_rsn_pending_salary)

        prior_salary = selected_player.get("last_salary")
        if persistent_record is not None:
            suggested = float(persistent_record.annual_salary)
        else:
            suggested = float(prior_salary) if isinstance(prior_salary, (int, float)) and prior_salary and prior_salary > 0 else 2_500_000.0
        annual_salary = st.number_input(
            "Annual salary",
            min_value=1.0,
            max_value=100_000_000.0,
            value=float(min(max(suggested, 1.0), 100_000_000.0)),
            step=250_000.0,
            format="%.0f",
            key="fa_ui_salary",
            help="V1.3 evaluates the 2026-27 standard-contract salary floor/ceiling conservatively. A live signing is enabled only for an actual offseason PASS preview.",
        )
        years_default = int(persistent_record.years) if persistent_record is not None else 1
        years = st.slider("Years", 1, 5, years_default, key="fa_ui_years")
        guarantee_default = bool(persistent_record.guaranteed) if persistent_record is not None else True
        guaranteed = st.checkbox("Guaranteed contract", value=guarantee_default, key="fa_ui_guaranteed")
        option_values = ["None", "Team option", "Player option"]
        persisted_option_label = {"team_option": "Team option", "player_option": "Player option"}.get(
            persistent_record.option_type if persistent_record is not None else "", "None"
        )
        option_label = st.selectbox(
            "Option", option_values, index=option_values.index(persisted_option_label), key="fa_ui_option"
        )
        option_type = {"None": "", "Team option": "team_option", "Player option": "player_option"}[option_label]

        preview_state = state
        hypothetical_offseason = False
        if phase != "offseason":
            hypothetical_offseason = st.checkbox(
                "Evaluate as a hypothetical offseason offer",
                value=True,
                help="Uses an isolated deepcopy with only the phase changed to offseason. It never writes the checkpoint.",
                key="fa_ui_hypothetical_offseason",
            )
            if hypothetical_offseason:
                preview_state = isolated_offseason_preview_state(state)

        if team:
            try:
                payroll, payroll_detail = team_guaranteed_payroll(preview_state, team)
            except Exception as exc:
                payroll, payroll_detail = None, {"error": str(exc)}
            cap = environment.salary_cap
            p1, p2 = st.columns(2)
            p1.metric("Guaranteed payroll", f"${payroll:,.0f}" if payroll is not None else "Unknown")
            p2.metric("Salary cap", f"${cap:,.0f}" if cap is not None else "Manual review")

        offer = FreeAgencyOffer(
            player_id=selected_player["player_id"],
            team_abbreviation=team,
            annual_salary=float(annual_salary),
            years=int(years),
            guaranteed=bool(guaranteed),
            option_type=option_type,
        )
        signature = offer_signature(
            offer.player_id,
            offer.team_abbreviation,
            offer.annual_salary,
            offer.years,
            offer.guaranteed,
            offer.option_type,
        )

        _external_rfa_offer_sheet = bool(
            _selected_is_rfa
            and not rfa_direct_signing_allowed
            and team
        )
        _pending_selected_sheet = (
            pending_offer_sheet_for_player(state, _selected_pid)
            if _selected_is_rfa
            else None
        )

        if _external_rfa_offer_sheet:
            st.markdown("#### External RFA offer sheet")
            if _pending_selected_sheet is not None:
                st.info(
                    f"This player already has pending offer sheet "
                    f"{_pending_selected_sheet.get('offer_sheet_id')}. Resolve it before creating another."
                )
            elif phase != "offseason":
                st.info(
                    "Offer sheets can be created only in the actual durable offseason."
                )
            elif not calendar_snapshot.initialized:
                st.info(
                    "Start the Free Agency calendar before creating an offer sheet so the "
                    "two-day right-of-first-refusal deadline can be recorded."
                )
            elif int(years) < 2:
                st.warning(
                    "An external restricted-free-agent offer sheet requires at least two seasons."
                )
            else:
                _offer_sheet_preview_clicked = st.button(
                    "Preview RFA offer sheet",
                    type="primary",
                    width="stretch",
                    key="fa_rfa_offer_sheet_preview_button",
                    help=(
                        "Checks the external contract, cap legality, active QO/retained rights, "
                        "and player acceptance before any durable offer sheet is created."
                    ),
                )
                if _offer_sheet_preview_clicked:
                    try:
                        _offer_sheet_preview = build_external_offer_sheet_preview(
                            checkpoint,
                            offer,
                        )
                        st.session_state["fa_rfa_offer_sheet_preview"] = _offer_sheet_preview
                    except Exception as _offer_sheet_exc:
                        st.session_state.pop("fa_rfa_offer_sheet_preview", None)
                        st.error(
                            "The RFA offer sheet is not ready. "
                            f"Detail: {_offer_sheet_exc}"
                        )

                _stored_offer_sheet_preview = st.session_state.get(
                    "fa_rfa_offer_sheet_preview"
                )
                _stored_offer_sheet_current = bool(
                    _stored_offer_sheet_preview is not None
                    and str(_stored_offer_sheet_preview.player_id) == str(offer.player_id)
                    and str(_stored_offer_sheet_preview.offering_team) == str(offer.team_abbreviation)
                    and abs(float(_stored_offer_sheet_preview.annual_salary) - float(offer.annual_salary)) < 0.01
                    and int(_stored_offer_sheet_preview.years) == int(offer.years)
                    and bool(_stored_offer_sheet_preview.guaranteed) == bool(offer.guaranteed)
                    and str(_stored_offer_sheet_preview.option_type or "") == str(offer.option_type or "")
                )
                if _stored_offer_sheet_current:
                    _os_preview = _stored_offer_sheet_preview
                    st.success(
                        f"Player accepted the sheet in negotiation round {_os_preview.accepted_round}. "
                        f"If submitted now, {_os_preview.prior_team} has through FA Day "
                        f"{_os_preview.match_deadline_day} to match."
                    )
                    _osp1, _osp2, _osp3 = st.columns(3)
                    _osp1.metric("Offer", f"${_os_preview.annual_salary:,.0f}")
                    _osp2.metric("Years", _os_preview.years)
                    _osp3.metric("Original team", _os_preview.prior_team)

                    if st.button(
                        "Confirm and submit RFA offer sheet",
                        type="primary",
                        width="stretch",
                        key="fa_rfa_offer_sheet_commit_button",
                        help=(
                            "This is the final offer-sheet submission. It creates the durable "
                            "two-day response window but does not transfer the player yet."
                        ),
                    ):
                        try:
                            with st.spinner(
                                "Submitting RFA offer sheet and reload-verifying the pending match window..."
                            ):
                                _created = commit_external_offer_sheet_live(
                                    _os_preview,
                                    confirmation_token=_os_preview.confirmation_token,
                                )
                                _refreshed = load_franchise_checkpoint()
                                if _refreshed is None:
                                    raise RFAOfferSheetError(
                                        "The offer sheet saved, but the checkpoint could not be reloaded into the UI."
                                    )
                                st.session_state["franchise_simulation_league_state"] = _refreshed.simulation_state
                                st.session_state["franchise_trade_league_state"] = _refreshed.trade_state
                                st.session_state.pop("fa_rfa_offer_sheet_preview", None)
                                st.session_state.pop("fa_ui_preview", None)
                                st.session_state.pop("fa_ui_preview_signature", None)
                                st.session_state["fa_rfa_offer_sheet_notice"] = (
                                    f"{_created.offer_sheet_id}: {_created.player_name} signed an offer sheet "
                                    f"with {_created.offering_team} for ${_created.annual_salary:,.0f} × "
                                    f"{_created.years} years. {_created.prior_team} has through FA Day "
                                    f"{_created.match_deadline_day} to match."
                                )
                        except Exception as _offer_sheet_exc:
                            st.error(
                                "The RFA offer sheet was not submitted. "
                                f"Detail: {_offer_sheet_exc}"
                            )
                        else:
                            st.rerun()
                else:
                    st.session_state.pop("fa_rfa_offer_sheet_preview", None)

        preview_clicked = st.button(
            "Preview offer",
            type="primary",
            width="stretch",
            disabled=(
                not bool(team)
                or not rfa_direct_signing_allowed
            ),
            key="fa_ui_preview_button",
            help=(
                None
                if rfa_direct_signing_allowed
                else "Use Preview RFA offer sheet above for an external restricted free agent."
            ),
        )
        if preview_clicked:
            st.session_state["fa_ui_preview"] = build_contract_legal_free_agency_preview(preview_state, offer)
            st.session_state["fa_ui_preview_signature"] = signature
            st.session_state["fa_ui_preview_hypothetical"] = hypothetical_offseason
            st.session_state.pop("fa_player_decision", None)
            st.session_state.pop("fa_shared_market", None)
            st.session_state.pop("fa_negotiation_round", None)

        preview = st.session_state.get("fa_ui_preview")
        if preview is not None:
            if not preview_matches_signature(preview, signature):
                st.info("Offer inputs changed. Preview again before relying on the result.")
            else:
                status = str(getattr(preview, "status", "")).lower()
                if status == "pass":
                    st.success("Backend preview: PASS")
                elif status == "manual_review":
                    st.warning("Backend preview: MANUAL REVIEW")
                else:
                    st.error("Backend preview: BLOCKED")
                st.write(getattr(preview, "message", ""))
                # V1.2 marker retained for prior validator compatibility: build_live_financial_free_agency_preview
                gate = getattr(preview, "financial_gate", None)
                if gate is not None:
                    st.caption(f"Financial/CBA: {str(getattr(gate, 'status', '')).upper()} · {getattr(gate, 'reason', '')}")
                    payload = dict(getattr(gate, "payload", {}) or {})
                    if payload:
                        contract_legality = payload.get("contract_salary_legality")
                        if isinstance(contract_legality, dict):
                            st.markdown("#### Contract salary legality")
                            c1, c2 = st.columns(2)
                            minimum = contract_legality.get("minimum_salary_floor")
                            maximum = contract_legality.get("maximum_initial_salary")
                            c1.metric("Minimum salary floor", f"${float(minimum):,.0f}" if minimum is not None else "Manual review")
                            c2.metric("Auto-releasable maximum", f"${float(maximum):,.0f}" if maximum is not None else "Manual review")
                            service = contract_legality.get("years_of_service")
                            service_text = str(service) if service is not None else "Unknown (conservative window)"
                            st.caption(
                                f"Years of service: {service_text} · "
                                f"Term status: {contract_legality.get('term_status', '')} · "
                                f"Source: {contract_legality.get('service_source', '')}"
                            )
                        with st.expander("Financial details"):
                            st.json(payload)
                checks = dict(getattr(preview, "checks", {}) or {})
                if checks:
                    checks_df = pd.DataFrame([
                        {"Check": name.replace("_", " ").title(), "Result": "PASS" if passed else "FAIL"}
                        for name, passed in checks.items()
                    ])
                    with st.expander("Structural checks", expanded=status != "pass"):
                        st.dataframe(checks_df, width="stretch", hide_index=True)

        preview_is_hypothetical = bool(
            st.session_state.get("fa_ui_preview_hypothetical", False)
        )
        preview_signature_matches = (
            preview is not None
            and preview_matches_signature(preview, signature)
        )
        backend_offer_passes = (
            preview_signature_matches
            and str(getattr(preview, "status", "")).lower() == "pass"
            and bool(getattr(preview, "can_commit", False))
            and bool(team)
        )

        st.markdown("#### Player decision + negotiation market")
        decision_state = preview_state
        actual_offseason = phase == "offseason"

        negotiation = None
        negotiation_is_current = False
        persistent_negotiation = False
        negotiation_preview = preview
        selected_market_record = (
            persistent_market_for_player_team(state, selected_player["player_id"], team)
            if team and actual_offseason
            else None
        )

        if actual_offseason:
            if selected_market_record is not None:
                try:
                    negotiation = build_persistent_negotiation_result(
                        state,
                        selected_market_record,
                        controlled_teams=controlled_teams,
                    )
                    negotiation_is_current = (
                        negotiation.negotiation_fingerprint
                        == selected_market_record.negotiation_fingerprint
                    )
                    persistent_negotiation = negotiation_is_current
                    persisted_offer = FreeAgencyOffer(
                        player_id=selected_market_record.player_id,
                        team_abbreviation=selected_market_record.user_team_abbreviation,
                        annual_salary=selected_market_record.annual_salary,
                        years=selected_market_record.years,
                        guaranteed=selected_market_record.guaranteed,
                        option_type=selected_market_record.option_type,
                    )
                    negotiation_preview = build_contract_legal_free_agency_preview(
                        state,
                        persisted_offer,
                    )
                except Exception as exc:
                    st.warning(
                        "A persisted negotiation exists for this player, but it no longer rebuilds exactly from the durable state. "
                        f"Open the current legal offer again to replace it. Detail: {exc}"
                    )

            current_offer_matches_persisted = (
                selected_market_record is not None
                and abs(float(selected_market_record.annual_salary) - float(annual_salary)) < 0.01
                and int(selected_market_record.years) == int(years)
                and bool(selected_market_record.guaranteed) == bool(guaranteed)
                and str(selected_market_record.option_type or "") == str(option_type or "")
            )
            open_label = (
                "Open negotiation round 1"
                if selected_market_record is None
                else "Replace persistent negotiation with current offer"
            )
            if selected_market_record is not None and current_offer_matches_persisted:
                open_label = "Rebuild persistent negotiation from current offer"
            open_negotiation = st.button(
                open_label,
                width="stretch",
                key="fa_negotiation_open",
                disabled=not backend_offer_passes,
                help=(
                    "Persists this legal offer into the durable checkpoint. Multiple players can have active negotiations at the same time. "
                    "Replacing an offer archives the prior version and restarts this player at negotiation round 1."
                ),
            )
            if open_negotiation:
                try:
                    with st.spinner("Persisting negotiation round 1 and verifying checkpoint reload..."):
                        write, record = persist_user_negotiation_durably(preview)
                        refreshed = load_franchise_checkpoint()
                        if refreshed is None:
                            raise FreeAgencyPersistentCalendarError(
                                "The negotiation saved, but the checkpoint could not be reloaded."
                            )
                        st.session_state["franchise_simulation_league_state"] = refreshed.simulation_state
                        st.session_state["franchise_trade_league_state"] = refreshed.trade_state
                        st.session_state["fa_calendar_notice"] = (
                            f"Persisted {selected_player['player_name']} negotiation on Free Agency Day {write.offseason_day} "
                            f"as {record.market_id}."
                        )
                except Exception as exc:
                    st.error(f"The persistent negotiation was not saved. Detail: {exc}")
                else:
                    st.rerun()

            if selected_market_record is None:
                if backend_offer_passes:
                    st.info(
                        "This legal offer is not yet part of the durable market. Open negotiation round 1 to persist it."
                    )
            else:
                st.caption(
                    f"Persistent market {selected_market_record.market_id} · created Day {selected_market_record.created_day} · "
                    f"last updated Day {selected_market_record.last_updated_day}."
                )
                st.caption(
                    "Advance this negotiation through the **Advance free agency day** control above. "
                    "One day advances every active persisted market at most one round."
                )
                # Locked V1 compatibility marker: Advance market one round
        else:
            open_negotiation = st.button(
                "Open negotiation round 1",
                width="stretch",
                key="fa_negotiation_open",
                disabled=not backend_offer_passes,
                help="Hypothetical regular-season preview only. This session result is never persisted.",
            )
            if open_negotiation:
                try:
                    st.session_state["fa_negotiation_round"] = build_free_agency_negotiation_round(
                        decision_state,
                        preview,
                        controlled_teams=controlled_teams,
                        round_number=1,
                    )
                except Exception as exc:
                    st.session_state.pop("fa_negotiation_round", None)
                    st.error(f"The hypothetical negotiation could not be opened. Detail: {exc}")

            negotiation = st.session_state.get("fa_negotiation_round")
            negotiation_is_current = (
                backend_offer_passes
                and negotiation is not None
                and negotiation_round_matches_state_and_preview(
                    decision_state,
                    preview,
                    negotiation,
                    controlled_teams=controlled_teams,
                )
            )
            if negotiation_is_current:
                advance_round = st.button(
                    "Advance market one round",
                    width="stretch",
                    key="fa_negotiation_advance",
                    disabled=negotiation.round_number >= MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
                )
                if advance_round:
                    try:
                        st.session_state["fa_negotiation_round"] = build_free_agency_negotiation_round(
                            decision_state,
                            preview,
                            controlled_teams=controlled_teams,
                            round_number=negotiation.round_number + 1,
                        )
                    except Exception as exc:
                        st.error(f"The next hypothetical negotiation round could not be built. Detail: {exc}")
                    else:
                        st.rerun()

        decision = (
            negotiation.user_decision
            if negotiation_is_current and negotiation is not None
            else None
        )
        if (
            decision is None
            and backend_offer_passes
            and preview is not None
            and preview_signature_matches
        ):
            try:
                decision = evaluate_free_agent_offer_decision(
                    decision_state,
                    preview,
                )
            except Exception:
                decision = None
        decision_is_current = decision is not None and (
            negotiation_is_current or backend_offer_passes
        )

        # FRANCHISE_RESIGNING_NEGOTIATION_SUITE_V1
        render_player_reaction_v1(
            decision_state,
            selected_player,
            signing_team=team,
            decision=decision,
            negotiation=negotiation if negotiation_is_current else None,
            annual_salary=float(annual_salary),
            years=int(years),
        )

        if negotiation is None or not negotiation_is_current:
            if actual_offseason and selected_market_record is not None:
                st.warning("The persisted negotiation is stale and cannot be relied on until it is replaced/rebuilt.")
            elif not actual_offseason and backend_offer_passes:
                st.info("Open negotiation round 1 for the current hypothetical legal offer.")
        else:
            market = negotiation.market
            response = negotiation.player_response
            if response == "ready_to_sign":
                if negotiation.user_is_winner:
                    st.success(f"Player response: READY TO SIGN · {negotiation.user_team_abbreviation} leads the accepted market.")
                else:
                    st.warning(f"Player response: READY TO SIGN · {market.winner_team_abbreviation} leads the accepted market.")
            elif response == "hold":
                st.info("Player response: HOLD · at least one offer is acceptable, but the player is keeping the market open.")
            elif response == "counter_market":
                st.warning("Player response: COUNTER MARKET · no team has cleared the acceptance threshold yet.")
            elif response == "exploring_market":
                st.info("Player response: EXPLORING MARKET · no acceptable offer yet, so the player remains available.")
            else:
                st.warning("Player response: NO ACCEPTABLE OFFER in the final decision window.")

            st.caption(negotiation.player_response_reason)
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("Negotiation round", f"{negotiation.round_number}/{negotiation.max_rounds}")
            n2.metric("CPU bids active", len(negotiation.cpu_offers))
            n3.metric("Market winner", market.winner_team_abbreviation or "None")
            n4.metric("Winning margin", f"{market.winning_margin:.1f}" if market.winning_margin is not None else "—")

            st.markdown("#### Player interest by team")
            st.caption(
                "Interest is the locked Player Decisions V1 utility score on a 0–100 scale, not a signing probability. "
                "The acceptance line is this player's deterministic threshold for the current season/profile."
            )
            try:
                interest_rows = build_player_interest_rows(decision_state, negotiation)
            except Exception as exc:
                interest_rows = ()
                st.warning(f"Player interest meters could not be rebuilt from the current offer set. Detail: {exc}")

            if interest_rows:
                top_interest_rows = interest_rows[: min(6, len(interest_rows))]
                for start in range(0, len(top_interest_rows), 3):
                    meter_columns = st.columns(min(3, len(top_interest_rows) - start))
                    for column, row in zip(meter_columns, top_interest_rows[start:start + 3]):
                        with column:
                            source_label = "Your offer" if row.is_user_offer else "CPU offer"
                            st.markdown(f"**#{row.rank} {row.team_abbreviation} · {row.interest_band} interest**")
                            st.progress(
                                interest_meter_value(row.interest_score),
                                text=f"Interest {row.interest_score:.1f}/100",
                            )
                            gap_label = (
                                f"+{row.gap_to_acceptance:.1f} above"
                                if row.gap_to_acceptance >= 0
                                else f"{abs(row.gap_to_acceptance):.1f} below"
                            )
                            st.caption(
                                f"{source_label} · ${row.annual_salary:,.0f} × {row.years}y · "
                                f"Acceptance line {row.acceptance_threshold:.1f} · {gap_label} · "
                                f"{row.player_decision_status.upper()}"
                            )

                interest_table_rows = [
                    {
                        "Rank": row.rank,
                        "Team": row.team_abbreviation,
                        "Source": "Your offer" if row.is_user_offer else "CPU offer",
                        "Interest": row.interest_score,
                        "Interest level": row.interest_band,
                        "Acceptance line": row.acceptance_threshold,
                        "Gap to yes": row.gap_to_acceptance,
                        "Decision": row.player_decision_status.upper(),
                        "Annual salary": row.annual_salary,
                        "Years": row.years,
                    }
                    for row in interest_rows
                ]
                st.dataframe(
                    pd.DataFrame(interest_table_rows),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Interest": st.column_config.ProgressColumn(
                            "Interest",
                            help="Deterministic player utility, not signing probability.",
                            format="%.1f",
                            min_value=0.0,
                            max_value=100.0,
                        ),
                        "Acceptance line": st.column_config.NumberColumn(format="%.1f"),
                        "Gap to yes": st.column_config.NumberColumn(format="%+.1f"),
                        "Annual salary": st.column_config.NumberColumn(format="$%,.0f"),
                    },
                )

                with st.expander("Why the player likes each team", expanded=False):
                    component_rows = [
                        {
                            "Team": row.team_abbreviation,
                            "Money": row.salary_score,
                            "Role": row.role_score,
                            "Winning": row.winning_score,
                            "Security": row.security_score,
                            "Career fit": row.career_fit_score,
                            "Overall interest": row.interest_score,
                        }
                        for row in interest_rows
                    ]
                    st.dataframe(
                        pd.DataFrame(component_rows),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Money": st.column_config.NumberColumn(format="%.1f"),
                            "Role": st.column_config.NumberColumn(format="%.1f"),
                            "Winning": st.column_config.NumberColumn(format="%.1f"),
                            "Security": st.column_config.NumberColumn(format="%.1f"),
                            "Career fit": st.column_config.NumberColumn(format="%.1f"),
                            "Overall interest": st.column_config.NumberColumn(format="%.1f"),
                        },
                    )

            market_rows = [
                {
                    "Rank": evaluation.rank,
                    "Team": evaluation.team_abbreviation,
                    "Source": "Your offer" if evaluation.team_abbreviation == negotiation.user_team_abbreviation else "CPU bid",
                    "Annual salary": evaluation.annual_salary,
                    "Years": evaluation.years,
                    "Utility": evaluation.utility_score,
                    "Decision": evaluation.player_decision_status.upper(),
                }
                for evaluation in market.evaluations
            ]
            st.dataframe(
                pd.DataFrame(market_rows),
                width="stretch",
                hide_index=True,
                column_config={
                    "Annual salary": st.column_config.NumberColumn(format="$%,.0f"),
                    "Utility": st.column_config.NumberColumn(format="%.1f"),
                },
            )

            if negotiation.cpu_offers:
                with st.expander("CPU negotiation actions", expanded=True):
                    cpu_rows = [
                        {
                            "Team": row.team_abbreviation,
                            "Action": row.action.upper(),
                            "Prior salary": row.prior_salary,
                            "Current salary": row.annual_salary,
                            "Years": row.years,
                            "Direction": row.team_direction,
                            "Target fit": row.target_fit_score,
                            "Reason": row.action_reason,
                        }
                        for row in negotiation.cpu_offers
                    ]
                    st.dataframe(
                        pd.DataFrame(cpu_rows),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Prior salary": st.column_config.NumberColumn(format="$%,.0f"),
                            "Current salary": st.column_config.NumberColumn(format="$%,.0f"),
                            "Target fit": st.column_config.NumberColumn(format="%.1f"),
                        },
                    )

            if negotiation.history:
                with st.expander("Negotiation round history", expanded=False):
                    history_rows = [
                        {
                            "Round": row.round_number,
                            "Window": row.round_label,
                            "Player response": row.player_response.replace("_", " ").title(),
                            "Winner": row.winner_team_abbreviation or "None",
                            "Margin": row.winning_margin,
                            "Active CPU bids": row.active_cpu_offer_count,
                            "CPU increases": row.increased_cpu_offer_count,
                            "CPU withdrawals": row.withdrawn_cpu_offer_count,
                        }
                        for row in negotiation.history
                    ]
                    st.dataframe(pd.DataFrame(history_rows), width="stretch", hide_index=True)

            if decision.counter_salary is not None:
                st.metric("Player counter to your current offer", f"${decision.counter_salary:,.0f} / year")
                st.caption(
                    "To answer the counter, change the contract above, preview it, and replace this persistent negotiation with the new legal offer."
                )

            with st.expander("Player preference profile"):
                profile = decision.preference_profile
                st.caption(
                    f"{profile.archetype} · patience {profile.market_patience:.3f} · deterministic player/season negotiation profile"
                )
                pref_df = pd.DataFrame([
                    {"Preference": "Money", "Weight": profile.money_weight * 100.0},
                    {"Preference": "Role opportunity", "Weight": profile.role_weight * 100.0},
                    {"Preference": "Winning", "Weight": profile.winning_weight * 100.0},
                    {"Preference": "Contract security", "Weight": profile.security_weight * 100.0},
                    {"Preference": "Career/timeline fit", "Weight": profile.career_fit_weight * 100.0},
                ])
                st.dataframe(
                    pref_df,
                    width="stretch",
                    hide_index=True,
                    column_config={"Weight": st.column_config.NumberColumn(format="%.1f%%")},
                )

        actual_offseason = phase == "offseason"
        player_accepted = (
            decision_is_current
            and str(getattr(decision, "status", "")).lower() == "accept"
        )
        user_market_winner = (
            negotiation_is_current
            and bool(getattr(negotiation, "user_is_winner", False))
        )
        player_ready_to_sign = (
            negotiation_is_current
            and bool(getattr(negotiation, "ready_to_sign", False))
        )
        live_preview_passes = (
            negotiation_is_current
            and player_accepted
            and user_market_winner
            and player_ready_to_sign
            and not preview_is_hypothetical
            and actual_offseason
            and negotiation.user_team_abbreviation in controlled_teams
            and persistent_negotiation
            and rfa_direct_signing_allowed
        )
        # Locked V1 validator compatibility: backend_offer_passes and player_ready_to_sign

        if actual_offseason and persistent_negotiation:
            preview_is_hypothetical = False

        st.markdown("#### Durable signing")
        if preview_is_hypothetical:
            st.info(
                "This is a hypothetical offseason negotiation. It can never be committed. "
                "Advance the durable franchise to the offseason and preview the offer again."
            )
        elif not actual_offseason:
            st.info("Live signing is locked until the durable franchise is actually in the offseason.")
        elif not persistent_negotiation:
            st.info("Persist the current player negotiation into the offseason calendar before a live signing can be confirmed.")
        elif not negotiation_is_current:
            st.info("The persistent negotiation must rebuild exactly from the durable state before signing.")
        elif not player_accepted:
            st.warning("The player has not individually accepted your offer.")
        elif not user_market_winner:
            st.warning(
                "Another team currently leads the negotiation market. Your signing cannot be committed."
            )
        elif not player_ready_to_sign:
            st.info(
                "Your team currently leads, but the player is HOLDING the market open. Advance the negotiation before signing."
            )
        else:
            st.success(
                "All backend gates PASS, your team wins the current market, and the player is READY TO SIGN. "
                "The confirmation button below is the final basketball decision and commits immediately."
            )

        confirmation_player = negotiation.player_name if negotiation_is_current and negotiation is not None else selected_player["player_name"]
        confirmation_team = negotiation.user_team_abbreviation if negotiation_is_current and negotiation is not None else team
        confirmation_salary = (
            selected_market_record.annual_salary
            if selected_market_record is not None and persistent_negotiation
            else float(annual_salary)
        )
        confirmation_years = (
            selected_market_record.years
            if selected_market_record is not None and persistent_negotiation
            else int(years)
        )
        confirmation_text = (
            f"I confirm this signing: {confirmation_player} to {confirmation_team} "
            f"for ${float(confirmation_salary):,.0f} per year for {int(confirmation_years)} year(s)."
        )
        st.caption(
            "Final decision: clicking the button below immediately commits the "
            "signing to the durable franchise, reload-verifies the saved state, "
            "and automatically restores the pre-signing checkpoint if verification fails."
        )
        sign_clicked = st.button(
            (
                f"Confirm and sign {confirmation_player} → {confirmation_team} · "
                f"${float(confirmation_salary):,.0f}/yr × {int(confirmation_years)}"
            ),
            type="primary",
            width="stretch",
            key="fa_live_sign_button",
            disabled=not live_preview_passes,
            help=confirmation_text,
        )
        if sign_clicked:
            try:
                with st.spinner("Committing negotiated FATX transaction and verifying durable checkpoint..."):
                    if selected_market_record is None:
                        raise FreeAgencyPersistentCalendarError(
                            "No persistent market record is available for this signing."
                        )
                    negotiated_signing = commit_persistent_user_winner_live(
                        selected_market_record.market_id,
                        hypothetical=preview_is_hypothetical,
                    )
                    # Locked Negotiation V1 compatibility marker: commit_negotiated_user_winner_live(
                    result = negotiated_signing.live_signing_result
                    refreshed = load_franchise_checkpoint()
                    if refreshed is None:
                        raise FreeAgencyLiveSigningError(
                            "The signing saved, but the checkpoint could not be reloaded into the UI."
                        )
                    st.session_state["franchise_simulation_league_state"] = refreshed.simulation_state
                    st.session_state["franchise_trade_league_state"] = refreshed.trade_state
                    st.session_state.pop("fa_ui_preview", None)
                    st.session_state.pop("fa_ui_preview_signature", None)
                    st.session_state.pop("fa_ui_preview_hypothetical", None)
                    st.session_state.pop("fa_player_decision", None)
                    st.session_state.pop("fa_shared_market", None)
                    st.session_state.pop("fa_negotiation_round", None)
                    st.session_state["fa_live_signing_notice"] = (
                        f"{result.transaction_id}: signed {result.player_name} to {result.team_abbreviation} "
                        f"for ${result.annual_salary:,.0f} per year over {result.years} year(s)."
                    )
                    st.session_state["franchise_notice"] = st.session_state["fa_live_signing_notice"]
            except Exception as exc:
                st.error(f"The signing was not committed. Detail: {exc}")
            else:
                st.rerun()

        # Compatibility markers retained for locked predecessor validators:
        # build_user_cpu_shared_market · Submit offer to player + CPU market · CPU competing-offer details
        # user_market_winner and user_market_winner · commit_user_shared_market_winner_live(
        # Legacy decision labels: == "accept" · == "counter" · == "decline"

    st.divider()
    st.markdown("### Free-agency transaction history")
    history = free_agency_history_rows(state)
    if history:
        history_df = pd.DataFrame(history).rename(columns={
            "transaction_id": "Transaction",
            "player": "Player",
            "team": "Team",
            "annual_salary": "Annual salary",
            "years": "Years",
            "route": "Route",
            "financial_status": "Financial status",
        })
        st.dataframe(
            history_df,
            width="stretch",
            hide_index=True,
            column_config={"Annual salary": st.column_config.NumberColumn(format="$%,.0f")},
        )
    else:
        st.caption("No durable free-agency transactions have been recorded yet.")

    st.caption(
        f"{FREE_AGENCY_INTEREST_METER_UI_VERSION} · {FREE_AGENCY_INTEREST_METER_VERSION} · "
        f"{FREE_AGENCY_PERSISTENT_CALENDAR_UI_VERSION} · {FREE_AGENCY_PERSISTENT_CALENDAR_VERSION} · "
        f"{FREE_AGENCY_NEGOTIATION_ROUNDS_UI_VERSION} · {FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION} · "
        f"{FREE_AGENCY_SHARED_MARKET_UI_VERSION} · {FREE_AGENCY_SHARED_MARKET_VERSION} · "
        f"{FREE_AGENCY_PLAYER_DECISION_UI_VERSION} · {FREE_AGENCY_PLAYER_DECISION_VERSION} · "
        f"{FREE_AGENCY_LIVE_UI_VERSION} · {FREE_AGENCY_LIVE_SIGNING_VERSION} · "
        f"{FREE_AGENCY_UI_VERSION} · {FREE_AGENCY_FINANCIAL_BRIDGE_VERSION} · "
        f"{FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION}"
    )

    # Compatibility marker: minimum/maximum salary legality
