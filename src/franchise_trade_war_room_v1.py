from __future__ import annotations

from html import escape
from typing import Any, Callable

import pandas as pd
import streamlit as st

from freeform_trade_machine_engine_v3 import normalize_team
from franchise_command_center_v1 import team_needs_rows
from franchise_embedded_trade_center_v2 import (
    build_franchise_trade_preview,
    preview_to_dict,
)
from franchise_live_asset_ledger_ui_v1 import render_live_asset_ledger
from franchise_live_asset_ledger_v1 import (
    build_live_asset_ledger,
    team_draft_rows,
    team_player_rows,
)
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    build_team_trade_ai_profiles,
    pick_value_for_team,
    player_value_for_team,
)
from franchise_trade_transaction_v1 import (
    FranchiseTradeTransactionError,
    commit_live_franchise_trade,
    pending_rfa_offer_sheet_trade_capacity_report,
)
from franchise_ui_branding_v1 import rgba, team_colors, team_logo_url, team_name


TRADE_WAR_ROOM_VERSION = "franchise-trade-war-room-v1.0-2026-09-12"
PREVIEW_KEY = "franchise_embedded_trade_center_v2_preview"
WORKSPACE_KEY = "franchise_trade_war_room_workspace_v1"


def _money(value: Any) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        return "—"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _status_text(value: Any) -> str:
    return str(value or "not_run").replace("_", " ").title()


def _position_family(position: str) -> str:
    primary = str(position or "").split("/", 1)[0].strip().upper()
    if primary in {"PG", "SG"}:
        return "Guard"
    if primary in {"SF", "PF"}:
        return "Wing/Forward"
    if primary == "C":
        return "Center"
    return "Other"


def _needs(state: Any, team: str) -> dict[str, float]:
    return {
        str(row.get("Position Group", "")): float(row.get("Need Score", 0.0) or 0.0)
        for row in team_needs_rows(state, team)
    }


def _fit_signal(state: Any, receiving_team: str, incoming_rows: list[dict[str, Any]]) -> tuple[str, str]:
    if not incoming_rows:
        return "Waiting", "No incoming players selected"
    needs = _needs(state, receiving_team)
    ranked = sorted(
        ((family, score) for family, score in needs.items() if family != "Other"),
        key=lambda item: (-item[1], item[0]),
    )
    biggest = ranked[0][0] if ranked else ""
    second = ranked[1][0] if len(ranked) > 1 else ""
    families = [_position_family(str(row.get("position", ""))) for row in incoming_rows]
    if biggest and biggest in families:
        return "Strong fit", f"Adds directly to {biggest.lower()} need"
    if second and second in families:
        return "Useful fit", f"Adds to secondary {second.lower()} need"
    return "Depth fit", "Incoming players do not target the biggest current need"


def _player_label(row: dict[str, Any]) -> str:
    return (
        f"{row.get('player_name', row.get('player_id'))} · "
        f"{row.get('position', 'UNK')} · {float(row.get('overall') or 0):.0f} OVR · "
        f"{_money(row.get('salary'))}"
    )


def _pick_label(row: dict[str, Any]) -> str:
    return (
        f"{row.get('draft_year')} R{row.get('round')} · "
        f"{row.get('display_name', row.get('asset_id'))} · "
        f"{str(row.get('tradability_status') or '').replace('_', ' ').title()}"
    )


def _safe_headshot(
    resolver: Callable[..., str] | None,
    player_id: str,
    team: str,
    player_name: str,
) -> str:
    if resolver is None:
        return ""
    try:
        return str(resolver(player_id, team, player_name) or "")
    except TypeError:
        try:
            return str(resolver(player_id, team) or "")
        except Exception:
            return ""
    except Exception:
        return ""


def _selected_player_cards_html(
    rows_by_id: dict[str, dict[str, Any]],
    selected_ids: list[str],
    receiving_profile: Any,
    *,
    player_headshot_resolver: Callable[..., str] | None,
    team: str,
) -> str:
    if not selected_ids:
        return '<div class="twr-empty">No players in package</div>'
    cards: list[str] = []
    for player_id in selected_ids:
        row = rows_by_id.get(player_id, {})
        name = str(row.get("player_name") or player_id)
        image = _safe_headshot(player_headshot_resolver, player_id, team, name)
        image_html = (
            f'<img src="{escape(image)}" alt="{escape(name)}">'
            if image
            else '<div class="twr-player-placeholder">NBA</div>'
        )
        ai_value = player_value_for_team(row, receiving_profile, goal=GOAL_BEST_AVAILABLE)
        years = int(row.get("years_remaining") or 0)
        years_text = f"{years}Y" if years > 0 else "TERM N/A"
        cards.append(
            '<div class="twr-player-card">'
            f'<div class="twr-player-photo">{image_html}</div>'
            '<div class="twr-player-main">'
            f'<div class="twr-player-name">{escape(name)}</div>'
            f'<div class="twr-player-meta">{escape(str(row.get("position") or "UNK"))} · '
            f'{float(row.get("overall") or 0):.0f} OVR · POT {float(row.get("potential") or 0):.0f}</div>'
            f'<div class="twr-player-contract">{escape(_money(row.get("salary")))} · {escape(years_text)}</div>'
            '</div>'
            f'<div class="twr-value-badge"><span>AI VALUE</span><b>{ai_value:.1f}</b></div>'
            '</div>'
        )
    return "".join(cards)


def _selected_pick_cards_html(
    picks_by_id: dict[str, dict[str, Any]],
    selected_ids: list[str],
    ledger: Any,
    receiving_profile: Any,
) -> str:
    if not selected_ids:
        return '<div class="twr-empty twr-empty-small">No draft assets in package</div>'
    cards: list[str] = []
    for asset_id in selected_ids:
        row = picks_by_id.get(asset_id, {})
        value = pick_value_for_team(row, ledger, receiving_profile)
        label = str(row.get("display_name") or asset_id)
        status = str(row.get("tradability_status") or "").replace("_", " ").title()
        cards.append(
            '<div class="twr-pick-card">'
            '<div>'
            f'<div class="twr-pick-year">{int(row.get("draft_year") or 0)} · R{int(row.get("round") or 0)}</div>'
            f'<div class="twr-pick-name">{escape(label)}</div>'
            f'<div class="twr-pick-status">{escape(status or "Status n/a")}</div>'
            '</div>'
            f'<div class="twr-pick-value">{value:.1f}</div>'
            '</div>'
        )
    return "".join(cards)


def _timeline_html(rows: list[dict[str, Any]], selected: set[str]) -> str:
    if not rows:
        return '<div class="twr-empty twr-empty-small">No draft assets in horizon</div>'
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row.get("draft_year") or 0), []).append(row)
    years: list[str] = []
    for year in sorted(grouped):
        assets = []
        for row in sorted(grouped[year], key=lambda x: (int(x.get("round") or 9), str(x.get("asset_id") or ""))):
            asset_id = str(row.get("asset_id") or "")
            selected_class = " selected" if asset_id in selected else ""
            ready = bool(row.get("engine_ready"))
            ready_class = " ready" if ready else " review"
            assets.append(
                f'<span class="twr-round{selected_class}{ready_class}">R{int(row.get("round") or 0)}</span>'
            )
        years.append(
            '<div class="twr-year">'
            f'<div class="twr-year-label">{year}</div>'
            f'<div class="twr-year-assets">{"".join(assets)}</div>'
            '</div>'
        )
    return '<div class="twr-timeline">' + "".join(years) + "</div>"


def _bundle_value(
    *,
    player_ids: list[str],
    pick_ids: list[str],
    player_map: dict[str, dict[str, Any]],
    pick_map: dict[str, dict[str, Any]],
    ledger: Any,
    profile: Any,
) -> float:
    # Mirrors Trade Finder V2's diminishing-package philosophy while relying
    # only on the public player/pick value functions.
    values: list[float] = []
    for player_id in player_ids:
        row = player_map.get(player_id)
        if row is not None:
            values.append(player_value_for_team(row, profile, goal=GOAL_BEST_AVAILABLE))
    for asset_id in pick_ids:
        row = pick_map.get(asset_id)
        if row is not None:
            values.append(pick_value_for_team(row, ledger, profile))
    values.sort(reverse=True)
    total = 0.0
    for index, value in enumerate(values):
        if index == 0:
            weight = 1.0
        elif index == 1:
            weight = 0.78 if value >= 75 else 0.65 if value >= 35 else 0.55
        elif index == 2:
            weight = 0.58 if value >= 75 else 0.46 if value >= 35 else 0.36
        elif index == 3:
            weight = 0.42 if value >= 75 else 0.32 if value >= 35 else 0.25
        else:
            weight = 0.18
        total += value * weight
    return round(total, 2)


def _value_signal(delta: float) -> tuple[str, str]:
    if delta >= 8.0:
        return "Favorable", "good"
    if delta >= 1.5:
        return "Positive", "good"
    if delta > -1.5:
        return "Balanced", "neutral"
    if delta > -8.0:
        return "Costly", "warn"
    return "Heavy cost", "bad"


def _inject_styles(primary: str, secondary: str) -> None:
    st.markdown(
        f"""
        <style>
        .twr-hero{{border:1px solid {rgba(primary,.42)};border-radius:26px;padding:20px 24px;background:radial-gradient(circle at 12% 0%,{rgba(primary,.30)},transparent 34%),radial-gradient(circle at 90% 100%,{rgba(secondary,.20)},transparent 38%),linear-gradient(135deg,#0b111c,#090c13 60%,#0c1019);box-shadow:0 20px 60px rgba(0,0,0,.28);margin:4px 0 14px;}}
        .twr-kicker{{font-size:.69rem;letter-spacing:.18em;font-weight:950;color:#7dd3fc;}}
        .twr-title{{font-size:2.15rem;line-height:1.04;font-weight:950;color:#fff;margin-top:5px;}}
        .twr-sub{{color:#94a3b8;font-size:.88rem;margin-top:7px;}}
        .twr-versus{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:18px;margin-top:18px;}}
        .twr-team{{display:flex;align-items:center;gap:12px;min-width:0;}}
        .twr-team.right{{justify-content:flex-end;text-align:right;}}
        .twr-team img{{width:64px;height:64px;object-fit:contain;}}
        .twr-team-name{{font-size:1.28rem;font-weight:950;color:#fff;}}
        .twr-team-meta{{font-size:.73rem;color:#94a3b8;margin-top:3px;text-transform:uppercase;letter-spacing:.06em;}}
        .twr-vs{{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.04);color:#94a3b8;font-weight:950;}}
        .twr-panel{{border:1px solid rgba(255,255,255,.09);border-radius:20px;background:linear-gradient(145deg,rgba(15,23,42,.92),rgba(5,9,15,.95));padding:14px;margin-top:8px;}}
        .twr-panel-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;}}
        .twr-panel-title{{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;font-weight:950;color:#cbd5e1;}}
        .twr-fit{{font-size:.67rem;font-weight:900;border-radius:999px;padding:5px 8px;border:1px solid rgba(125,211,252,.25);color:#7dd3fc;background:rgba(14,165,233,.08);}}
        .twr-player-card{{display:grid;grid-template-columns:54px 1fr auto;align-items:center;gap:10px;border-radius:14px;padding:9px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);margin:7px 0;}}
        .twr-player-photo{{width:54px;height:54px;border-radius:13px;overflow:hidden;background:rgba(255,255,255,.05);display:flex;align-items:flex-end;justify-content:center;}}
        .twr-player-photo img{{width:100%;height:100%;object-fit:contain;object-position:center bottom;}}
        .twr-player-placeholder{{font-size:.65rem;font-weight:950;color:#64748b;margin:auto;}}
        .twr-player-name{{font-size:.92rem;font-weight:900;color:#f8fafc;}}
        .twr-player-meta{{font-size:.66rem;color:#93c5fd;margin-top:2px;}}
        .twr-player-contract{{font-size:.62rem;color:#94a3b8;margin-top:2px;}}
        .twr-value-badge{{min-width:54px;border-radius:11px;padding:6px 7px;text-align:center;background:{rgba(primary,.10)};border:1px solid {rgba(primary,.28)};}}
        .twr-value-badge span{{display:block;font-size:.48rem;letter-spacing:.08em;color:#94a3b8;font-weight:900;}}
        .twr-value-badge b{{font-size:.84rem;color:#fff;}}
        .twr-pick-card{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 10px;border-radius:12px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);margin:6px 0;}}
        .twr-pick-year{{font-size:.6rem;color:#7dd3fc;font-weight:900;letter-spacing:.07em;}}
        .twr-pick-name{{font-size:.75rem;font-weight:850;color:#f8fafc;margin-top:2px;}}
        .twr-pick-status{{font-size:.58rem;color:#94a3b8;margin-top:2px;}}
        .twr-pick-value{{width:42px;height:32px;border-radius:9px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.05);font-size:.72rem;font-weight:950;color:#fff;}}
        .twr-empty{{padding:14px;border-radius:12px;border:1px dashed rgba(255,255,255,.10);color:#64748b;font-size:.72rem;text-align:center;}}
        .twr-empty-small{{padding:9px;}}
        .twr-timeline{{display:grid;grid-template-columns:repeat(auto-fit,minmax(74px,1fr));gap:7px;}}
        .twr-year{{border-radius:12px;padding:8px;background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);}}
        .twr-year-label{{font-size:.65rem;color:#94a3b8;font-weight:900;margin-bottom:5px;}}
        .twr-year-assets{{display:flex;gap:4px;flex-wrap:wrap;}}
        .twr-round{{font-size:.6rem;font-weight:950;border-radius:7px;padding:4px 6px;background:rgba(255,255,255,.05);color:#cbd5e1;border:1px solid rgba(255,255,255,.08);}}
        .twr-round.ready{{border-color:rgba(34,197,94,.22);}}
        .twr-round.review{{border-color:rgba(245,158,11,.22);}}
        .twr-round.selected{{background:{rgba(primary,.20)};border-color:{rgba(primary,.62)};color:#fff;box-shadow:0 0 18px {rgba(primary,.10)};}}
        .twr-salary-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:9px;}}
        .twr-salary{{padding:11px;border-radius:14px;background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);}}
        .twr-salary-label{{font-size:.6rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.09em;font-weight:900;}}
        .twr-salary-value{{font-size:1.02rem;color:#fff;font-weight:950;margin-top:2px;}}
        .twr-salary-note{{font-size:.61rem;color:#64748b;margin-top:2px;}}
        .twr-signal-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
        .twr-signal{{padding:12px;border-radius:15px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);}}
        .twr-signal.good{{border-color:rgba(34,197,94,.28);}}
        .twr-signal.warn{{border-color:rgba(245,158,11,.30);}}
        .twr-signal.bad{{border-color:rgba(239,68,68,.28);}}
        .twr-signal-title{{font-size:.63rem;text-transform:uppercase;letter-spacing:.09em;color:#94a3b8;font-weight:900;}}
        .twr-signal-main{{font-size:1.12rem;font-weight:950;color:#fff;margin-top:3px;}}
        .twr-signal-detail{{font-size:.65rem;color:#94a3b8;margin-top:2px;}}
        .twr-gates{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:10px 0;}}
        .twr-gate{{padding:9px;border-radius:12px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.025);}}
        .twr-gate span{{display:block;font-size:.54rem;color:#64748b;text-transform:uppercase;letter-spacing:.07em;font-weight:900;}}
        .twr-gate b{{display:block;font-size:.72rem;color:#f8fafc;margin-top:2px;}}
        @media(max-width:900px){{.twr-versus{{grid-template-columns:1fr;}}.twr-team.right{{justify-content:flex-start;text-align:left;}}.twr-vs{{display:none;}}.twr-signal-grid,.twr-salary-grid{{grid-template-columns:1fr;}}.twr-gates{{grid-template-columns:repeat(2,1fr);}}}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header(active: str, partner: str, profiles: dict[str, Any]) -> None:
    active_profile = profiles[active]
    partner_profile = profiles[partner]
    st.markdown(
        '<div class="twr-hero">'
        '<div class="twr-kicker">FRANCHISE TRANSACTION COMMAND</div>'
        '<div class="twr-title">NBA Trade War Room</div>'
        '<div class="twr-sub">Build the package visually, compare AI team value and roster fit, inspect draft capital, then send the exact assets through the existing salary, contract, Stepien and full-legality gates.</div>'
        '<div class="twr-versus">'
        '<div class="twr-team">'
        f'<img src="{escape(team_logo_url(active))}" alt="{escape(team_name(active))}">'
        '<div>'
        f'<div class="twr-team-name">{escape(team_name(active))}</div>'
        f'<div class="twr-team-meta">{escape(active_profile.timeline)} · need: {escape(active_profile.biggest_need)}</div>'
        '</div></div>'
        '<div class="twr-vs">↔</div>'
        '<div class="twr-team right"><div>'
        f'<div class="twr-team-name">{escape(team_name(partner))}</div>'
        f'<div class="twr-team-meta">{escape(partner_profile.timeline)} · need: {escape(partner_profile.biggest_need)}</div>'
        '</div>'
        f'<img src="{escape(team_logo_url(partner))}" alt="{escape(team_name(partner))}">'
        '</div></div></div>',
        unsafe_allow_html=True,
    )


def _checks_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for check in payload.get("checks", []) or []:
        rows.append(
            {
                "Status": _status_text(check.get("status")),
                "Code": check.get("code", ""),
                "Team": check.get("team", ""),
                "Asset": check.get("asset_id", ""),
                "Detail": check.get("message", ""),
            }
        )
    return pd.DataFrame(rows)


def render_franchise_trade_war_room_v1(
    runtime: Any,
    state: Any,
    trade_state: Any,
    active_team: str,
    *,
    player_headshot_resolver: Callable[..., str] | None = None,
) -> None:
    active = normalize_team(active_team)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_team_trade_ai_profiles(state, ledger)
    primary, secondary = team_colors(active)
    _inject_styles(primary, secondary)

    choices = ("War Room", "Asset Ledger & Finder")
    pending_workspace = st.session_state.pop("_franchise_trade_war_room_pending_workspace_v1", None)
    if pending_workspace in choices:
        st.session_state[WORKSPACE_KEY] = pending_workspace
    if st.session_state.get(WORKSPACE_KEY) not in choices:
        st.session_state[WORKSPACE_KEY] = "War Room"
    if hasattr(st, "segmented_control"):
        workspace = st.segmented_control(
            "Trade workspace",
            choices,
            key=WORKSPACE_KEY,
            label_visibility="collapsed",
            width="content",
        )
    else:
        workspace = st.radio(
            "Trade workspace",
            choices,
            key=WORKSPACE_KEY,
            horizontal=True,
            label_visibility="collapsed",
        )

    if workspace == "Asset Ledger & Finder":
        render_live_asset_ledger(runtime, state, trade_state, active)
        return

    teams = sorted(team for team in profiles if team != active)
    if not teams:
        st.error("No trade partner is available in the live league state.")
        return
    partner_key = f"franchise_trade_center_v2_partner_{active}"
    current_partner = normalize_team(st.session_state.get(partner_key, ""))
    if current_partner not in teams:
        st.session_state[partner_key] = teams[0]
    partner = st.selectbox(
        "Trade partner",
        teams,
        key=partner_key,
        format_func=team_name,
    )
    partner = normalize_team(partner)
    _render_header(active, partner, profiles)

    active_players = [row for row in team_player_rows(ledger, active) if row.get("roster_status") == "rostered"]
    partner_players = [row for row in team_player_rows(ledger, partner) if row.get("roster_status") == "rostered"]
    active_player_map = {str(row["player_id"]): row for row in active_players}
    partner_player_map = {str(row["player_id"]): row for row in partner_players}
    active_picks = team_draft_rows(ledger, active)
    partner_picks = team_draft_rows(ledger, partner)
    active_pick_map = {str(row["asset_id"]): row for row in active_picks}
    partner_pick_map = {str(row["asset_id"]): row for row in partner_picks}

    a_player_key = f"franchise_trade_center_v2_side_a_players_{active}_{partner}"
    b_player_key = f"franchise_trade_center_v2_side_b_players_{active}_{partner}"
    a_pick_key = f"franchise_trade_center_v2_side_a_picks_{active}_{partner}"
    b_pick_key = f"franchise_trade_center_v2_side_b_picks_{active}_{partner}"

    selection_keys = (a_player_key, b_player_key, a_pick_key, b_pick_key)
    if st.session_state.pop("_franchise_trade_war_room_pending_clear_v1", False):
        for key in selection_keys:
            st.session_state[key] = []
        st.session_state.pop(PREVIEW_KEY, None)
    for key in selection_keys:
        if not isinstance(st.session_state.get(key), list):
            st.session_state[key] = []

    a_col, b_col = st.columns(2, gap="large")
    with a_col:
        st.markdown(f"### {team_name(active)} sends")
        selected_a_players = st.multiselect(
            "Players",
            options=list(active_player_map),
            format_func=lambda pid: _player_label(active_player_map[pid]),
            key=a_player_key,
        )
        selected_a_picks = st.multiselect(
            "Draft assets",
            options=list(active_pick_map),
            format_func=lambda aid: _pick_label(active_pick_map[aid]),
            key=a_pick_key,
        )
    with b_col:
        st.markdown(f"### {team_name(partner)} sends")
        selected_b_players = st.multiselect(
            "Players",
            options=list(partner_player_map),
            format_func=lambda pid: _player_label(partner_player_map[pid]),
            key=b_player_key,
        )
        selected_b_picks = st.multiselect(
            "Draft assets",
            options=list(partner_pick_map),
            format_func=lambda aid: _pick_label(partner_pick_map[aid]),
            key=b_pick_key,
        )

    active_fit, active_fit_detail = _fit_signal(
        state,
        active,
        [partner_player_map[pid] for pid in selected_b_players if pid in partner_player_map],
    )
    partner_fit, partner_fit_detail = _fit_signal(
        state,
        partner,
        [active_player_map[pid] for pid in selected_a_players if pid in active_player_map],
    )

    boards = st.columns(2, gap="large")
    with boards[0]:
        st.markdown(
            '<div class="twr-panel"><div class="twr-panel-head">'
            f'<div class="twr-panel-title">Outgoing package · {escape(active)}</div>'
            f'<div class="twr-fit">Partner fit: {escape(partner_fit)}</div></div>'
            + _selected_player_cards_html(
                active_player_map,
                list(selected_a_players),
                profiles[partner],
                player_headshot_resolver=player_headshot_resolver,
                team=active,
            )
            + _selected_pick_cards_html(active_pick_map, list(selected_a_picks), ledger, profiles[partner])
            + '</div>',
            unsafe_allow_html=True,
        )
        st.caption(partner_fit_detail)
    with boards[1]:
        st.markdown(
            '<div class="twr-panel"><div class="twr-panel-head">'
            f'<div class="twr-panel-title">Incoming package · {escape(partner)}</div>'
            f'<div class="twr-fit">Your fit: {escape(active_fit)}</div></div>'
            + _selected_player_cards_html(
                partner_player_map,
                list(selected_b_players),
                profiles[active],
                player_headshot_resolver=player_headshot_resolver,
                team=partner,
            )
            + _selected_pick_cards_html(partner_pick_map, list(selected_b_picks), ledger, profiles[active])
            + '</div>',
            unsafe_allow_html=True,
        )
        st.caption(active_fit_detail)

    all_player_map = {**active_player_map, **partner_player_map}
    all_pick_map = {**active_pick_map, **partner_pick_map}
    active_sent_value = _bundle_value(
        player_ids=list(selected_a_players),
        pick_ids=list(selected_a_picks),
        player_map=all_player_map,
        pick_map=all_pick_map,
        ledger=ledger,
        profile=profiles[active],
    )
    active_received_value = _bundle_value(
        player_ids=list(selected_b_players),
        pick_ids=list(selected_b_picks),
        player_map=all_player_map,
        pick_map=all_pick_map,
        ledger=ledger,
        profile=profiles[active],
    )
    partner_sent_value = _bundle_value(
        player_ids=list(selected_b_players),
        pick_ids=list(selected_b_picks),
        player_map=all_player_map,
        pick_map=all_pick_map,
        ledger=ledger,
        profile=profiles[partner],
    )
    partner_received_value = _bundle_value(
        player_ids=list(selected_a_players),
        pick_ids=list(selected_a_picks),
        player_map=all_player_map,
        pick_map=all_pick_map,
        ledger=ledger,
        profile=profiles[partner],
    )
    active_delta = round(active_received_value - active_sent_value, 1)
    partner_delta = round(partner_received_value - partner_sent_value, 1)
    active_signal, active_class = _value_signal(active_delta)
    partner_signal, partner_class = _value_signal(partner_delta)

    st.markdown("### War Room readout")
    st.markdown(
        '<div class="twr-signal-grid">'
        f'<div class="twr-signal {active_class}"><div class="twr-signal-title">{escape(team_name(active))} AI value signal</div>'
        f'<div class="twr-signal-main">{escape(active_signal)} · {active_delta:+.1f}</div>'
        f'<div class="twr-signal-detail">Receives {active_received_value:.1f} · Sends {active_sent_value:.1f} · {escape(active_fit)}</div></div>'
        f'<div class="twr-signal {partner_class}"><div class="twr-signal-title">{escape(team_name(partner))} AI value signal</div>'
        f'<div class="twr-signal-main">{escape(partner_signal)} · {partner_delta:+.1f}</div>'
        f'<div class="twr-signal-detail">Receives {partner_received_value:.1f} · Sends {partner_sent_value:.1f} · {escape(partner_fit)}</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "AI value signal uses the same player/pick value concepts as Trade Finder and applies diminishing value to multi-asset bundles. "
        "It is a front-office comparison signal, not a CPU acceptance decision and not a CBA legality result."
    )

    listed_a_salary = sum(float(active_player_map[pid].get("salary") or 0.0) for pid in selected_a_players if pid in active_player_map)
    listed_b_salary = sum(float(partner_player_map[pid].get("salary") or 0.0) for pid in selected_b_players if pid in partner_player_map)
    payload = st.session_state.get(PREVIEW_KEY)
    current_matches_preview = bool(
        isinstance(payload, dict)
        and tuple(selected_a_players) == tuple(payload.get("side_a", {}).get("player_ids", []))
        and tuple(selected_b_players) == tuple(payload.get("side_b", {}).get("player_ids", []))
        and tuple(selected_a_picks) == tuple(payload.get("side_a", {}).get("pick_asset_ids", []))
        and tuple(selected_b_picks) == tuple(payload.get("side_b", {}).get("pick_asset_ids", []))
        and payload.get("side_b", {}).get("team") == partner
        and payload.get("side_a", {}).get("team") == active
    )
    financial_status = (
        _status_text(payload.get("financial_bridge_status"))
        if current_matches_preview
        else "Evaluate Package"
    )
    st.markdown(
        '<div class="twr-salary-grid">'
        '<div class="twr-salary">'
        f'<div class="twr-salary-label">{escape(active)} listed salary sent</div>'
        f'<div class="twr-salary-value">{escape(_money(listed_a_salary))}</div>'
        f'<div class="twr-salary-note">Incoming listed salary: {escape(_money(listed_b_salary))}</div></div>'
        '<div class="twr-salary">'
        f'<div class="twr-salary-label">Financial bridge</div>'
        f'<div class="twr-salary-value">{escape(financial_status)}</div>'
        '<div class="twr-salary-note">Exact trade-salary / apron rules are authoritative only after evaluation.</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Draft-pick timeline")
    pick_cols = st.columns(2, gap="large")
    with pick_cols[0]:
        st.caption(f"{team_name(active)} draft capital · selected picks glow")
        st.markdown(_timeline_html(active_picks, set(selected_a_picks)), unsafe_allow_html=True)
    with pick_cols[1]:
        st.caption(f"{team_name(partner)} draft capital · selected picks glow")
        st.markdown(_timeline_html(partner_picks, set(selected_b_picks)), unsafe_allow_html=True)

    action_cols = st.columns([1.3, 1, 1.15, 3.5])
    evaluate = action_cols[0].button(
        "Evaluate package",
        type="primary",
        width="stretch",
        key=f"twr_evaluate_{active}_{partner}",
    )
    clear = action_cols[1].button(
        "Clear package",
        width="stretch",
        key=f"twr_clear_{active}_{partner}",
    )
    if action_cols[2].button(
        "Open Trade Finder",
        width="stretch",
        key=f"twr_finder_{active}_{partner}",
    ):
        st.session_state["_franchise_trade_war_room_pending_workspace_v1"] = "Asset Ledger & Finder"
        st.session_state["franchise_live_asset_ledger_view_v1"] = "Trade Finder"
        st.rerun()
    action_cols[3].caption(
        "Evaluation is read-only. A live transaction remains impossible until every required bridge returns a deterministic PASS and you explicitly confirm commit."
    )

    if clear:
        st.session_state["_franchise_trade_war_room_pending_clear_v1"] = True
        st.rerun()

    if evaluate:
        preview = build_franchise_trade_preview(
            runtime,
            state,
            trade_state,
            team_a=active,
            team_b=partner,
            side_a_player_ids=tuple(selected_a_players),
            side_b_player_ids=tuple(selected_b_players),
            side_a_pick_asset_ids=tuple(selected_a_picks),
            side_b_pick_asset_ids=tuple(selected_b_picks),
            ledger=ledger,
        )
        st.session_state[PREVIEW_KEY] = preview_to_dict(preview)
        payload = st.session_state.get(PREVIEW_KEY)
        current_matches_preview = True

    if not isinstance(payload, dict) or not current_matches_preview:
        st.info("Package board is ready. Evaluate it to run the financial, contract, draft-right, Stepien and final legality gates.")
        return

    status = str(payload.get("status") or "manual_review")
    if status == "pass":
        st.success("War Room legality result: PASS. The package reached the live transaction commit gate.")
    elif status == "blocked":
        st.error("War Room legality result: BLOCKED. One or more authoritative checks failed.")
    else:
        st.warning("War Room legality result: MANUAL REVIEW. At least one authoritative bridge is unresolved.")

    st.markdown(
        '<div class="twr-gates">'
        f'<div class="twr-gate"><span>Overall</span><b>{escape(_status_text(status))}</b></div>'
        f'<div class="twr-gate"><span>Financial</span><b>{escape(_status_text(payload.get("financial_bridge_status")))}</b></div>'
        f'<div class="twr-gate"><span>Contracts</span><b>{escape(_status_text(payload.get("player_contract_bridge_status")))}</b></div>'
        f'<div class="twr-gate"><span>Draft rights</span><b>{escape(_status_text(payload.get("draft_right_bridge_status")))}</b></div>'
        f'<div class="twr-gate"><span>Commit</span><b>{"Eligible" if payload.get("can_commit") else "Disabled"}</b></div>'
        '</div>',
        unsafe_allow_html=True,
    )

    checks = _checks_frame(payload)
    failed = checks[checks["Status"].str.lower() != "pass"] if not checks.empty else checks
    with st.expander(
        f"Legality audit · {len(failed)} non-pass check(s)",
        expanded=bool(status != "pass"),
    ):
        if checks.empty:
            st.caption("No individual check rows were returned.")
        else:
            st.dataframe(checks, hide_index=True, width="stretch")

    offer_sheet_capacity = pending_rfa_offer_sheet_trade_capacity_report(
        state,
        team_a=active,
        team_b=partner,
        side_a_player_ids=tuple(selected_a_players),
        side_b_player_ids=tuple(selected_b_players),
    )
    offer_sheet_blocked = bool(offer_sheet_capacity.get("blocked"))
    if offer_sheet_blocked:
        st.warning("Pending RFA offer-sheet trade-capacity protection blocks this transaction until the conflict is resolved.")

    if bool(payload.get("can_commit")):
        fingerprint = str(payload.get("package_fingerprint") or "")
        st.markdown("### Transaction desk")
        confirmed = st.checkbox(
            "I understand this changes the live franchise and writes a new durable checkpoint.",
            key=f"twr_confirm_{fingerprint[:18]}",
            disabled=offer_sheet_blocked,
        )
        if st.button(
            "Approve & commit live trade",
            type="primary",
            width="stretch",
            key=f"twr_commit_{fingerprint[:18]}",
            disabled=not confirmed or offer_sheet_blocked,
        ):
            try:
                result = commit_live_franchise_trade(
                    runtime,
                    state,
                    trade_state,
                    team_a=active,
                    team_b=partner,
                    side_a_player_ids=tuple(selected_a_players),
                    side_b_player_ids=tuple(selected_b_players),
                    side_a_pick_asset_ids=tuple(selected_a_picks),
                    side_b_pick_asset_ids=tuple(selected_b_picks),
                    expected_fingerprint=fingerprint,
                )
            except FranchiseTradeTransactionError as exc:
                st.error(str(exc))
            else:
                st.session_state["franchise_simulation_league_state"] = result.committed_state
                st.session_state.pop(PREVIEW_KEY, None)
                st.session_state["franchise_notice"] = (
                    f"Committed {result.transaction_id}. Pre-trade recovery checkpoint: "
                    f"{result.recovery_checkpoint_path}"
                )
                st.rerun()


__all__ = [
    "TRADE_WAR_ROOM_VERSION",
    "render_franchise_trade_war_room_v1",
]
