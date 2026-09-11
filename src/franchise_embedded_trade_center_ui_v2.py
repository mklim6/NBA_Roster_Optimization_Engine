from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from freeform_trade_machine_engine_v3 import normalize_team
from franchise_embedded_trade_center_v2 import (
    EMBEDDED_TRADE_CENTER_VERSION,
    build_franchise_trade_preview,
    preview_to_dict,
)
from franchise_live_asset_ledger_v1 import (
    FranchiseAssetLedger,
    team_draft_rows,
    team_player_rows,
)
from franchise_trade_transaction_v1 import (
    FranchiseTradeTransactionError,
    commit_live_franchise_trade,
    pending_rfa_offer_sheet_trade_capacity_report,
)


EMBEDDED_TRADE_CENTER_UI_VERSION = (
    "franchise-embedded-trade-center-ui-v2-live-transaction-v1.0.1-2026-08-12"
)
SESSION_PREVIEW_KEY = "franchise_embedded_trade_center_v2_preview"


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


def _player_label(row: dict[str, Any]) -> str:
    source = "Generated" if row.get("generated_player") else "Baseline"
    return (
        f"{row.get('player_name', row.get('player_id'))} · "
        f"{row.get('position', 'UNK')} · {float(row.get('overall') or 0):.1f} OVR · "
        f"{_money(row.get('salary'))} · {source}"
    )


def _pick_label(row: dict[str, Any]) -> str:
    return (
        f"{row.get('draft_year')} R{row.get('round')} · "
        f"{row.get('display_name', row.get('asset_id'))} · "
        f"{row.get('tradability_status')}"
    )


def _checks_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for check in payload.get("checks", []):
        rows.append(
            {
                "Status": str(check.get("status", "")).replace("_", " ").title(),
                "Code": check.get("code", ""),
                "Team": check.get("team", ""),
                "Asset": check.get("asset_id", ""),
                "Detail": check.get("message", ""),
            }
        )
    return pd.DataFrame(rows)


def _render_side_metrics(label: str, side: dict[str, Any]) -> None:
    st.markdown(f"#### {label} · {side.get('team', '')}")
    cols = st.columns(5)
    cols[0].metric("Outgoing", _money(side.get("outgoing_salary")))
    cols[1].metric("Incoming", _money(side.get("incoming_salary")))
    cols[2].metric(
        "Roster",
        f"{side.get('roster_players_before', 0)} → {side.get('roster_players_after', 0)}",
    )
    cols[3].metric("Generated Out", side.get("generated_player_count", 0))
    cols[4].metric(
        "Engine-Covered",
        f"{side.get('engine_covered_player_count', 0)}/{len(side.get('player_ids', []))}",
    )


def render_embedded_trade_center_v2(
    runtime: Any,
    state: Any,
    trade_state: Any,
    ledger: FranchiseAssetLedger,
    active_team: str,
) -> None:
    # FRANCHISE_EMBEDDED_TRADE_CENTER_V2_PREVIEW
    active = normalize_team(active_team)
    teams = sorted(normalize_team(team) for team in getattr(state, "teams", {}) if normalize_team(team))
    opponents = [team for team in teams if team != active]

    st.markdown("### Embedded Franchise Trade Center V2")
    st.caption(
        "Build a two-team package directly from the live franchise universe. V2 Preview "
        "verifies live ownership, future-season player-contract eligibility, modeled trade "
        "salaries, Draft Capital mapping, and canonical Trade Machine coverage. Deterministic "
        "PASS packages can now be committed transactionally with durable-checkpoint rollback."
    )

    if not opponents:
        st.error("No second live franchise team is available for a two-team package.")
        return

    opponent = st.selectbox(
        "Trade partner",
        options=opponents,
        key=f"franchise_trade_center_v2_partner_{active}",
    )

    side_a_players = [
        row for row in team_player_rows(ledger, active)
        if row.get("roster_status") == "rostered"
    ]
    side_b_players = [
        row for row in team_player_rows(ledger, opponent)
        if row.get("roster_status") == "rostered"
    ]
    side_a_by_id = {row["player_id"]: row for row in side_a_players}
    side_b_by_id = {row["player_id"]: row for row in side_b_players}

    side_a_picks = team_draft_rows(ledger, active)
    side_b_picks = team_draft_rows(ledger, opponent)
    side_a_pick_by_id = {row["asset_id"]: row for row in side_a_picks}
    side_b_pick_by_id = {row["asset_id"]: row for row in side_b_picks}

    a_col, b_col = st.columns(2)
    with a_col:
        st.markdown(f"#### {active} sends")
        selected_a_players = st.multiselect(
            "Players",
            options=list(side_a_by_id),
            format_func=lambda player_id: _player_label(side_a_by_id[player_id]),
            key=f"franchise_trade_center_v2_side_a_players_{active}_{opponent}",
        )
        selected_a_picks = st.multiselect(
            "Draft assets",
            options=list(side_a_pick_by_id),
            format_func=lambda asset_id: _pick_label(side_a_pick_by_id[asset_id]),
            key=f"franchise_trade_center_v2_side_a_picks_{active}_{opponent}",
        )
        manual_count = sum(not bool(row.get("engine_ready")) for row in side_a_picks)
        st.caption(
            f"{manual_count} {active} draft-capital row(s) currently require bridge/manual review. "
            "They may be selected for diagnosis, but cannot produce a deterministic release."
        )

    with b_col:
        st.markdown(f"#### {opponent} sends")
        selected_b_players = st.multiselect(
            "Players",
            options=list(side_b_by_id),
            format_func=lambda player_id: _player_label(side_b_by_id[player_id]),
            key=f"franchise_trade_center_v2_side_b_players_{active}_{opponent}",
        )
        selected_b_picks = st.multiselect(
            "Draft assets",
            options=list(side_b_pick_by_id),
            format_func=lambda asset_id: _pick_label(side_b_pick_by_id[asset_id]),
            key=f"franchise_trade_center_v2_side_b_picks_{active}_{opponent}",
        )
        manual_count = sum(not bool(row.get("engine_ready")) for row in side_b_picks)
        st.caption(
            f"{manual_count} {opponent} draft-capital row(s) currently require bridge/manual review."
        )

    action_cols = st.columns([1.3, 1, 4])
    evaluate_clicked = action_cols[0].button(
        "Evaluate live package",
        type="primary",
        width="stretch",
        key=f"franchise_trade_center_v2_evaluate_{active}_{opponent}",
    )
    clear_clicked = action_cols[1].button(
        "Clear preview",
        width="stretch",
        key=f"franchise_trade_center_v2_clear_{active}_{opponent}",
    )
    action_cols[2].caption(
        "The package must be re-evaluated against the current live state before commit. Financial, "
        "player-contract, and draft-right / Stepien bridges must all return PASS. Manual-review or "
        "blocked packages can never be forced through Franchise Mode."
    )

    if clear_clicked:
        st.session_state.pop(SESSION_PREVIEW_KEY, None)

    if evaluate_clicked:
        preview = build_franchise_trade_preview(
            runtime,
            state,
            trade_state,
            team_a=active,
            team_b=opponent,
            side_a_player_ids=tuple(selected_a_players),
            side_b_player_ids=tuple(selected_b_players),
            side_a_pick_asset_ids=tuple(selected_a_picks),
            side_b_pick_asset_ids=tuple(selected_b_picks),
            ledger=ledger,
        )
        st.session_state[SESSION_PREVIEW_KEY] = preview_to_dict(preview)

    payload = st.session_state.get(SESSION_PREVIEW_KEY)
    if not isinstance(payload, dict):
        st.info("Select assets on both sides and evaluate the package. Nothing is mutated during preview.")
        return

    # Hide a stale preview if the active team changed.
    if payload.get("side_a", {}).get("team") != active:
        st.session_state.pop(SESSION_PREVIEW_KEY, None)
        st.info("The previous package preview belonged to a different active team and was cleared.")
        return

    status = str(payload.get("status", "manual_review"))
    if status == "pass":
        st.success("Live franchise legality preview: PASS. This package is eligible for the transactional commit gate.")
    elif status == "blocked":
        st.error("Package preview: BLOCKED. Review the failed checks below.")
    else:
        st.warning(
            "Package preview: MANUAL REVIEW. Live ownership/salary data is available, "
            "but at least one financial, player-contract, draft-right, or final franchise legality gate is unresolved."
        )

    summary = st.columns(7)
    summary[0].metric("Season", payload.get("season_label", ""))
    summary[1].metric("Status", status.replace("_", " ").title())
    summary[2].metric(
        "Financial Bridge",
        str(payload.get("financial_bridge_status", "not_run")).replace("_", " ").title(),
    )
    summary[3].metric(
        "Player Contract",
        str(payload.get("player_contract_bridge_status", "not_run")).replace("_", " ").title(),
    )
    summary[4].metric(
        "Draft Rights",
        str(payload.get("draft_right_bridge_status", "not_run")).replace("_", " ").title(),
    )
    summary[5].metric(
        "Canonical Engine",
        "Ran" if payload.get("canonical_engine_invoked") else "Not Released",
    )
    summary[6].metric(
        "Commit",
        "Eligible" if bool(payload.get("can_commit")) else "Disabled",
    )

    _render_side_metrics("Side A", payload.get("side_a", {}))
    _render_side_metrics("Side B", payload.get("side_b", {}))

    st.markdown("#### Legality and bridge checks")
    frame = _checks_frame(payload)
    if not frame.empty:
        st.dataframe(frame, hide_index=True, width="stretch")

    current_matches_preview = bool(
        tuple(selected_a_players) == tuple(payload.get("side_a", {}).get("player_ids", []))
        and tuple(selected_b_players) == tuple(payload.get("side_b", {}).get("player_ids", []))
        and tuple(selected_a_picks) == tuple(payload.get("side_a", {}).get("pick_asset_ids", []))
        and tuple(selected_b_picks) == tuple(payload.get("side_b", {}).get("pick_asset_ids", []))
        and payload.get("side_b", {}).get("team") == opponent
    )

    # RFA_OFFER_SHEET_TRADE_CAP_PROTECTION_V1
    offer_sheet_capacity = pending_rfa_offer_sheet_trade_capacity_report(
        state,
        team_a=active,
        team_b=opponent,
        side_a_player_ids=tuple(selected_a_players),
        side_b_player_ids=tuple(selected_b_players),
    )
    offer_sheet_capacity_blocked = bool(offer_sheet_capacity.get("blocked"))
    if offer_sheet_capacity_blocked:
        for capacity_row in offer_sheet_capacity.get("teams", []):
            if capacity_row.get("blocked"):
                st.warning(
                    "Pending RFA offer-sheet protection: "
                    + str(capacity_row.get("reason") or "")
                    + " Resolve the offer sheet or build a salary-neutral/decreasing package."
                )

    if bool(payload.get("can_commit")):
        st.markdown("#### Commit live franchise trade")
        if not current_matches_preview:
            st.warning(
                "The selected assets changed after this preview. Re-evaluate the package before committing."
            )
        fingerprint = str(payload.get("package_fingerprint", ""))
        confirm_key = (
            f"franchise_trade_commit_confirm_{fingerprint[:16]}"
        )
        confirmed = st.checkbox(
            "I understand this will change the live franchise and write a new durable checkpoint.",
            value=False,
            key=confirm_key,
            disabled=not (
                current_matches_preview
                and not offer_sheet_capacity_blocked
            ),
        )
        if st.button(
            "Commit live franchise trade",
            type="primary",
            width="stretch",
            disabled=not (
                current_matches_preview
                and confirmed
                and not offer_sheet_capacity_blocked
            ),
            key=f"franchise_trade_commit_button_{fingerprint[:16]}",
        ):
            try:
                result = commit_live_franchise_trade(
                    runtime,
                    state,
                    trade_state,
                    team_a=active,
                    team_b=opponent,
                    side_a_player_ids=tuple(selected_a_players),
                    side_b_player_ids=tuple(selected_b_players),
                    side_a_pick_asset_ids=tuple(selected_a_picks),
                    side_b_pick_asset_ids=tuple(selected_b_picks),
                    expected_fingerprint=fingerprint,
                )
            except FranchiseTradeTransactionError as exc:
                st.error(str(exc))
                st.caption(
                    "The commit engine automatically reconciles same-lineage checkpoint "
                    "revision drift. This message now appears only for a true conflict or "
                    "a package that stopped being a deterministic PASS."
                )
            else:
                st.session_state["game_simulator_league_state"] = result.committed_state
                st.session_state["franchise_live_asset_ledger_view_v1"] = "Trade Builder"
                st.session_state.pop(SESSION_PREVIEW_KEY, None)
                st.session_state["franchise_notice"] = (
                    f"Committed {result.transaction_id}. A pre-trade recovery checkpoint was saved at "
                    f"{result.recovery_checkpoint_path}."
                )
                st.rerun()
    elif status == "pass":
        st.warning(
            "The package passed displayed checks but is not commit-eligible. Re-evaluate after reviewing the bridge statuses."
        )

    with st.expander("Future-season financial bridge", expanded=False):
        if payload.get("financial_bridge_payload"):
            st.json(payload["financial_bridge_payload"], expanded=False)
        else:
            st.caption(
                "The financial bridge did not run because the package failed an earlier structural or ownership check."
            )

    with st.expander("Player contract eligibility bridge", expanded=False):
        if payload.get("player_contract_bridge_payload"):
            st.json(payload["player_contract_bridge_payload"], expanded=False)
        else:
            st.caption(
                "The player-contract bridge did not run because the package failed an earlier structural or ownership check."
            )

    with st.expander("Draft Right / Stepien bridge", expanded=False):
        if payload.get("draft_right_bridge_payload"):
            st.json(payload["draft_right_bridge_payload"], expanded=False)
        else:
            st.caption(
                "The draft-right bridge did not run because the package failed an earlier structural or ownership check."
            )

    with st.expander("Canonical engine payload", expanded=False):
        if payload.get("canonical_engine_payload"):
            st.json(payload["canonical_engine_payload"], expanded=False)
        else:
            st.caption(
                "No canonical engine payload was released for this package. The check table "
                "shows why the live package remains outside the verified engine scope."
            )

    st.caption(
        f"Trade Center: {EMBEDDED_TRADE_CENTER_VERSION} · UI: {EMBEDDED_TRADE_CENTER_UI_VERSION} · "
        f"Fingerprint: {str(payload.get('package_fingerprint', ''))[:16]}"
    )
