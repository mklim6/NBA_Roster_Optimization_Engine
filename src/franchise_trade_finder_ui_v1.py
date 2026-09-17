from __future__ import annotations

from html import escape
from typing import Any
import csv
import io

import streamlit as st

from freeform_trade_machine_engine_v3 import normalize_team
from franchise_live_asset_ledger_v1 import FranchiseAssetLedger
from franchise_ui_branding_v1 import rgba, team_colors, team_logo_url, team_name
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    GOAL_BIGGEST_NEED,
    GOAL_FUTURE_UPSIDE,
    GOAL_WIN_NOW,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    FranchiseTradeFinderAIError,
    FranchiseTradeFinderProposal,
    FranchiseTradeFinderResult,
    generate_trade_finder_proposals,
)

TRADE_FINDER_UI_VERSION = "franchise-trade-finder-ui-v1.5.3-anchor-preview-resolution-2026-08-13"
SESSION_RESULT_KEY = "franchise_trade_finder_ai_v1_result"
SESSION_PREVIEW_KEY = "franchise_embedded_trade_center_v2_preview"
LEDGER_VIEW_KEY = "franchise_live_asset_ledger_view_v1"

_GOAL_LABELS = {
    "Best available": GOAL_BEST_AVAILABLE,
    "Fill biggest need": GOAL_BIGGEST_NEED,
    "Win now": GOAL_WIN_NOW,
    "Future upside": GOAL_FUTURE_UPSIDE,
}


def _inject_css(active: str) -> None:
    primary, secondary = team_colors(active)
    st.markdown(
        f"""
        <style>
        .tf-shell {{
          border:1px solid {rgba(primary,.42)};
          border-radius:26px;
          padding:1px;
          margin:4px 0 18px;
          background:linear-gradient(120deg,{rgba(primary,.38)},rgba(10,15,25,.92) 48%,{rgba(secondary,.22)});
          box-shadow:0 24px 70px rgba(0,0,0,.28);
        }}
        .tf-hero {{
          min-height:150px;display:flex;align-items:center;gap:22px;padding:22px 26px;border-radius:25px;
          background:radial-gradient(circle at 88% 8%,{rgba(secondary,.22)},transparent 28%),linear-gradient(118deg,{rgba(primary,.88)},#101827 58%,#090d14);
        }}
        .tf-hero img {{width:92px;height:92px;object-fit:contain;filter:drop-shadow(0 10px 16px rgba(0,0,0,.38));}}
        .tf-kicker {{font-size:.72rem;letter-spacing:.18em;font-weight:900;color:rgba(255,255,255,.72);}}
        .tf-title {{font-size:2.25rem;font-weight:950;line-height:1.02;color:white;margin-top:4px;}}
        .tf-sub {{font-size:.93rem;color:rgba(255,255,255,.78);max-width:800px;margin-top:8px;line-height:1.45;}}
        .tf-badges {{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}}
        .tf-badge {{padding:5px 9px;border-radius:999px;border:1px solid rgba(255,255,255,.16);background:rgba(0,0,0,.23);font-size:.72rem;font-weight:800;color:#fff;}}
        .tf-policy {{padding:10px 13px;border-radius:13px;background:{rgba(primary,.08)};border:1px solid {rgba(primary,.25)};font-size:.78rem;color:#cbd5e1;margin:10px 0 14px;}}
        .tf-funnel {{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:10px 0 14px;}}
        .tf-stage {{padding:12px;border-radius:15px;border:1px solid rgba(255,255,255,.09);background:linear-gradient(145deg,rgba(255,255,255,.055),rgba(255,255,255,.018));min-height:82px;}}
        .tf-stage .n {{font-size:1.55rem;font-weight:950;color:#fff;}}
        .tf-stage .l {{font-size:.68rem;font-weight:800;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;}}
        .tf-stage.hot {{border-color:{rgba(primary,.5)};box-shadow:inset 0 0 0 1px {rgba(primary,.12)};}}
        .tf-deal {{padding:0;border-radius:22px;border:1px solid rgba(255,255,255,.12);overflow:hidden;background:linear-gradient(145deg,rgba(17,24,39,.95),rgba(7,10,16,.95));margin:14px 0 8px;box-shadow:0 15px 40px rgba(0,0,0,.22);}}
        .tf-deal-head {{display:grid;grid-template-columns:1fr auto 1fr auto;align-items:center;gap:14px;padding:14px 18px;background:linear-gradient(100deg,{rgba(primary,.24)},rgba(255,255,255,.025),{rgba(secondary,.14)});}}
        .tf-team {{display:flex;align-items:center;gap:10px;font-weight:900;color:white;}}
        .tf-team.right {{justify-content:flex-end;}}
        .tf-team img {{width:46px;height:46px;object-fit:contain;}}
        .tf-swap {{font-size:1.3rem;color:#94a3b8;}}
        .tf-pill {{padding:7px 10px;border-radius:999px;font-size:.72rem;font-weight:950;letter-spacing:.06em;}}
        .tf-pill.accept {{color:#86efac;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.42);}}
        .tf-pill.counter {{color:#fde68a;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.42);}}
        .tf-pill.reject {{color:#fca5a5;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);}}
        .tf-pill.guard {{color:#bfdbfe;background:rgba(59,130,246,.12);border:1px solid rgba(96,165,250,.42);}}
        .tf-assets {{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:16px 18px;}}
        .tf-asset-side {{padding:14px;border-radius:15px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);}}
        .tf-asset-title {{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;font-weight:900;margin-bottom:8px;}}
        .tf-asset {{padding:8px 0;color:#f8fafc;font-weight:720;border-bottom:1px solid rgba(255,255,255,.045);}}
        .tf-asset:last-child {{border-bottom:0;}}
        .tf-player-name {{font-size:.98rem;font-weight:850;color:#f8fafc;}}
        .tf-player-meta {{margin-top:3px;font-size:.70rem;font-weight:760;color:#93c5fd;letter-spacing:.015em;}}
        .tf-player-contract {{margin-top:2px;font-size:.66rem;color:#94a3b8;}}
        .tf-pick-meta {{font-size:.69rem;color:#cbd5e1;margin-top:2px;}}
        .tf-export-note {{font-size:.76rem;color:#94a3b8;line-height:1.4;}}
        @media(max-width:900px) {{
          .tf-funnel {{grid-template-columns:repeat(3,1fr);}}
          .tf-deal-head {{grid-template-columns:1fr auto 1fr;}}
          .tf-pill {{grid-column:1/-1;width:max-content;}}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _player_row(ledger: FranchiseAssetLedger, player_id: str) -> dict[str, Any]:
    for row in ledger.player_rows:
        if str(row.get("player_id")) == str(player_id):
            return dict(row)
    return {}


def _pick_row(ledger: FranchiseAssetLedger, asset_id: str) -> dict[str, Any]:
    for row in ledger.draft_rows:
        if str(row.get("asset_id")) == str(asset_id):
            return dict(row)
    return {}


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Salary n/a"
    if number <= 0:
        return "Salary n/a"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    return f"${number:,.0f}"


def _age(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "Age —"
    return f"Age {number:.0f}"


def _player_asset_html(ledger: FranchiseAssetLedger, player_id: str) -> str:
    row = _player_row(ledger, player_id)
    name = str(row.get("player_name") or player_id)
    position = str(row.get("position") or "UNK")
    overall = float(row.get("overall") or 0.0)
    potential = float(row.get("potential") or overall)
    years = int(row.get("years_remaining") or 0)
    role = str(row.get("role") or "").replace("_", " ").strip()
    career = str(row.get("career_status") or "").replace("_", " ").strip()
    contract_bits = [_money(row.get("salary"))]
    if years > 0:
        contract_bits.append(f"{years} yr{'s' if years != 1 else ''}")
    if role:
        contract_bits.append(role.title())
    if career and career.lower() not in {"active", "normal"}:
        contract_bits.append(career.title())
    return (
        '<div class="tf-asset">'
        f'<div class="tf-player-name">{escape(name)}</div>'
        f'<div class="tf-player-meta">{escape(position)} · {_age(row.get("age"))} · '
        f'OVR {overall:.1f} · POT {potential:.1f}</div>'
        f'<div class="tf-player-contract">{escape(" · ".join(contract_bits))}</div>'
        '</div>'
    )


def _pick_asset_html(ledger: FranchiseAssetLedger, asset_id: str) -> str:
    row = _pick_row(ledger, asset_id)
    name = str(row.get("display_name") or asset_id)
    status = str(row.get("tradability_status") or "").strip()
    meta = f"{int(row.get('draft_year') or 0)} Round {int(row.get('round') or 0)}"
    if status:
        meta += f" · {status}"
    return (
        '<div class="tf-asset">'
        f'<div class="tf-player-name">{escape(name)}</div>'
        f'<div class="tf-pick-meta">{escape(meta)}</div>'
        '</div>'
    )


def _side_asset_html(
    ledger: FranchiseAssetLedger,
    player_ids: tuple[str, ...],
    pick_ids: tuple[str, ...],
) -> str:
    output = [
        _player_asset_html(ledger, player_id)
        for player_id in player_ids
    ]
    output.extend(
        _pick_asset_html(ledger, asset_id)
        for asset_id in pick_ids
    )
    if not output:
        return '<div class="tf-asset" style="color:#64748b">No assets</div>'
    return "".join(output)


def _audit_csv_bytes(result: FranchiseTradeFinderResult) -> bytes:
    rows = [dict(row) for row in getattr(result, "package_audit_rows", ()) or ()]
    if not rows:
        return b""
    # Stable column order with the package/decision fields first, then the
    # player/pick detail columns in insertion order.
    priority = [
        "audit_id", "season_label", "active_team", "partner_team", "search_goal",
        "deal_type", "route_stage", "final_cpu_response",
        "target_player_id", "target_player_name", "target_position", "target_age",
        "target_overall", "target_potential", "target_salary",
        "target_value_to_active", "target_value_to_partner",
        "active_team_timeline", "partner_team_timeline",
        "active_team_biggest_need", "partner_team_biggest_need",
        "side_a_player_names", "side_b_player_names",
        "side_a_pick_names", "side_b_pick_names",
        "side_a_salary", "side_b_salary",
        "user_value_sent", "user_value_received", "user_value_delta",
        "cpu_value_sent", "cpu_value_received", "cpu_value_delta",
        "cpu_accept_floor_base", "morale_market_floor_adjustment",
        "cpu_accept_floor", "seller_ask_multiplier",
        "morale_market_posture", "morale_trade_risk",
        "morale_trade_request", "morale_market_search_bonus",
        "roster_fit",
        "guaranteed_exploration", "value_screen_pass",
        "financial_status", "financial_reason_codes",
        "full_legality_status", "can_commit", "legality_reason_codes",
        "counter_sweetener",
    ]
    fieldnames: list[str] = []
    for key in priority:
        if any(key in row for row in rows):
            fieldnames.append(key)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")




def _load(proposal: FranchiseTradeFinderProposal) -> None:
    active = normalize_team(proposal.active_team)
    partner = normalize_team(proposal.partner_team)
    st.session_state[f"franchise_trade_center_v2_partner_{active}"] = partner
    st.session_state[f"franchise_trade_center_v2_side_a_players_{active}_{partner}"] = list(proposal.side_a_player_ids)
    st.session_state[f"franchise_trade_center_v2_side_b_players_{active}_{partner}"] = list(proposal.side_b_player_ids)
    st.session_state[f"franchise_trade_center_v2_side_a_picks_{active}_{partner}"] = list(proposal.side_a_pick_asset_ids)
    st.session_state[f"franchise_trade_center_v2_side_b_picks_{active}_{partner}"] = list(proposal.side_b_pick_asset_ids)
    st.session_state[SESSION_PREVIEW_KEY] = dict(proposal.preview_payload)
    st.session_state[LEDGER_VIEW_KEY] = "Trade Builder"


def _asset_html(items: list[str]) -> str:
    if not items:
        return '<div class="tf-asset" style="color:#64748b">No assets</div>'
    return "".join(f'<div class="tf-asset">{escape(item)}</div>' for item in items)


def _render_deal(
    proposal: FranchiseTradeFinderProposal,
    ledger: FranchiseAssetLedger,
    index: int,
    *,
    actionable: bool,
) -> None:
    sent_html = _side_asset_html(
        ledger,
        proposal.side_a_player_ids,
        proposal.side_a_pick_asset_ids,
    )
    received_html = _side_asset_html(
        ledger,
        proposal.side_b_player_ids,
        proposal.side_b_pick_asset_ids,
    )
    pill_class = (
        "accept" if proposal.cpu_response == "accept"
        else "counter" if proposal.cpu_response == "counter"
        else "guard" if proposal.cpu_response == "overpay"
        else "reject"
    )
    st.markdown(
        f"""
        <div class="tf-deal">
          <div class="tf-deal-head">
            <div class="tf-team"><img src="{team_logo_url(proposal.active_team)}"><div>{escape(team_name(proposal.active_team))}<br><span style="font-size:.72rem;color:#94a3b8">{proposal.active_team}</span></div></div>
            <div class="tf-swap">⇄</div>
            <div class="tf-team right"><div style="text-align:right">{escape(team_name(proposal.partner_team))}<br><span style="font-size:.72rem;color:#94a3b8">{proposal.partner_team}</span></div><img src="{team_logo_url(proposal.partner_team)}"></div>
            <div class="tf-pill {pill_class}">{escape(proposal.response_label)}</div>
          </div>
          <div class="tf-assets">
            <div class="tf-asset-side"><div class="tf-asset-title">You send</div>{sent_html}</div>
            <div class="tf-asset-side"><div class="tf-asset-title">You receive</div>{received_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = st.columns(4)
    metrics[0].metric("Your value Δ", f"{proposal.user_value_delta:+.1f}")
    metrics[1].metric("CPU value Δ", f"{proposal.cpu_value_delta:+.1f}")
    metrics[2].metric("Roster fit", f"{proposal.fit_score:.1f}")
    with metrics[3]:
        st.caption("Deal type")
        st.markdown(f"### {escape(proposal.deal_type)}")

    # FRANCHISE_MORALE_TRADE_FINDER_UI_V5B
    morale_terms_v5b = dict(
        proposal.preview_payload.get(
            "morale_trade_finder_terms_v1",
            {},
        )
        or {}
    )
    if morale_terms_v5b.get("material_context"):
        seller_posture = str(
            morale_terms_v5b.get(
                "market_posture",
                "Keep internal",
            )
        )
        seller_risk = float(
            morale_terms_v5b.get(
                "trade_risk",
                0.0,
            )
            or 0.0
        )
        seller_ask = float(
            morale_terms_v5b.get(
                "seller_ask_multiplier",
                1.0,
            )
            or 1.0
        )
        base_floor = float(
            morale_terms_v5b.get(
                "base_accept_floor",
                0.0,
            )
            or 0.0
        )
        adjusted_floor = float(
            morale_terms_v5b.get(
                "adjusted_accept_floor",
                base_floor,
            )
            or base_floor
        )
        st.caption(
            f"Seller posture: {seller_posture} · "
            f"trade risk {seller_risk:.1f}% · "
            f"seller ask {seller_ask:.3f}x · "
            f"CPU accept floor {base_floor:+.1f} → "
            f"{adjusted_floor:+.1f}"
        )

    if proposal.cpu_response == "counter":
        st.warning(f"CPU counter: {proposal.counter_sweetener or 'additional value requested.'}")
    elif proposal.cpu_response == "accept":
        st.success(proposal.rationale)
    else:
        st.info(proposal.rationale)

    with st.expander("Legality & future-economy detail", expanded=False):
        payload = proposal.preview_payload
        st.caption(
            f"Overall {str(payload.get('status', '')).upper()} · "
            f"Financial {str(payload.get('financial_bridge_status', '')).upper()} · "
            f"Contract {str(payload.get('player_contract_bridge_status', '')).upper()} · "
            f"Draft/Stepien {str(payload.get('draft_right_bridge_status', '')).upper()}"
        )
        checks = payload.get("checks", []) or []
        notable = [
            check
            for check in checks
            if "advisory" in str(check.get("code", "")).lower()
            or "uncertainty" in str(check.get("code", "")).lower()
        ]
        if notable:
            st.json(notable, expanded=False)
        else:
            st.caption("No future-economy advisory checks were attached to this package.")

    if actionable:
        label = (
            "Load CPU counter in Trade Builder"
            if proposal.cpu_response == "counter"
            else "Load accepted deal in Trade Builder"
        )
        st.button(
            label,
            key=f"tf13_load_{proposal.proposal_id}_{index}",
            type="primary",
            width="stretch",
            on_click=_load,
            args=(proposal,),
        )


def render_trade_finder_v1(
    runtime: Any,
    state: Any,
    trade_state: Any,
    ledger: FranchiseAssetLedger,
    active_team: str,
) -> None:
    active = normalize_team(active_team)
    teams = sorted(
        normalize_team(team)
        for team in getattr(state, "teams", {})
        if normalize_team(team) and normalize_team(team) != active
    )
    _inject_css(active)
    season = str(getattr(getattr(state, "settings", None), "season_label", ""))

    st.markdown(
        f"""
        <div class="tf-shell"><div class="tf-hero">
          <img src="{team_logo_url(active)}">
          <div>
            <div class="tf-kicker">{escape(team_name(active).upper())} · FRONT OFFICE MARKET</div>
            <div class="tf-title">Trade Command Center</div>
            <div class="tf-sub">Search the full league, build financially plausible player packages, negotiate with CPU front offices, and inspect exactly why every route survives or dies.</div>
            <div class="tf-badges">
              <span class="tf-badge">{escape(season)}</span>
              <span class="tf-badge">SIMULATION-NATIVE FUTURE ECONOMY</span>
              <span class="tf-badge">LIVE CBA GUARDRAILS</span>
              <span class="tf-badge">DURABLE ROLLBACK</span>
            </div>
          </div>
        </div></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="tf-policy"><b>Future Economy V2:</b> Franchise Mode still hard-enforces ownership, roster no-worsening, player eligibility and Stepien. Future salary/apron decisions use the simulated contract universe with explicit uncertainty instead of treating unknown future real-world contracts and incomplete apron charges as exact facts.</div>',
        unsafe_allow_html=True,
    )

    controls = st.columns([1.45, 1.45, .9, .8])
    goal_label = controls[0].selectbox(
        "Search strategy",
        list(_GOAL_LABELS),
        key=f"tf13_goal_{active}",
    )
    partner_label = controls[1].selectbox(
        "Trade partner",
        ["All teams", *teams],
        key=f"tf13_partner_{active}",
    )
    max_results = controls[2].selectbox(
        "Offers",
        [4, 6, 8, 10],
        index=1,
        key=f"tf13_results_{active}",
    )
    include_picks = controls[3].toggle(
        "Use picks",
        value=True,
        key=f"tf13_picks_{active}",
    )

    action = st.columns([1.2, 3.8])
    clicked = action[0].button(
        "Search the market",
        type="primary",
        width="stretch",
        key=f"tf13_find_{active}",
    )
    action[1].caption(
        "All Teams searches up to all 29 partners. CPU approval is separate from legality, so a legal package can still be declined."
    )

    if clicked:
        with st.status("Opening the live trade market...", expanded=False) as status:
            def progress(event: dict[str, Any]) -> None:
                stage = str(event.get("stage", ""))
                partner = str(event.get("partner", ""))
                targets = int(event.get("targets_found", 0) or 0)
                packages = int(event.get("packages_generated", 0) or 0)
                financial_pass = int(event.get("financial_passes", 0) or 0)
                legal_pass = int(event.get("legal_passes", 0) or 0)
                offers = int(event.get("proposals_found", 0) or 0)
                status.update(
                    label=(
                        f"{stage.title()} {partner or 'market'} · {targets} targets · "
                        f"{packages} packages · {financial_pass} financial PASS · "
                        f"{legal_pass} legal PASS · {offers} offers"
                    ),
                    state="running",
                )

            try:
                result = generate_trade_finder_proposals(
                    runtime,
                    state,
                    trade_state,
                    active_team=active,
                    goal=_GOAL_LABELS[goal_label],
                    partner_team="" if partner_label == "All teams" else partner_label,
                    include_picks=bool(include_picks),
                    max_results=int(max_results),
                    max_partners=29,
                    max_targets_per_partner=5,
                    max_package_evaluations=10,
                    max_financial_prechecks=360,
                    progress_callback=progress,
                    ledger=ledger,
                )
            except FranchiseTradeFinderAIError as exc:
                status.update(label="Trade market stopped safely", state="error", expanded=True)
                st.error(str(exc))
            else:
                st.session_state[SESSION_RESULT_KEY] = result
                status.update(
                    label=(
                        f"Market complete in {result.search_elapsed_seconds:.1f}s · "
                        f"{result.legal_packages} legal packages · "
                        f"{len(result.proposals)} actionable offers"
                    ),
                    state="complete",
                )

    result = st.session_state.get(SESSION_RESULT_KEY)
    if (
        not isinstance(result, FranchiseTradeFinderResult)
        or result.active_team != active
        or result.season_label != season
        or result.franchise_trade_revision
        != int(getattr(state, "franchise_trade_revision_v1", 0) or 0)
    ):
        st.info("Choose a strategy and search the market. Results expire automatically after a trade or season change.")
        return

    stages = [
        ("Teams", result.teams_scanned),
        ("Targets", result.targets_identified),
        ("Packages", result.candidate_packages_generated),
        ("Financial PASS", result.financial_precheck_passes),
        ("Legal PASS", result.legal_packages),
        ("CPU offers", len(result.proposals)),
    ]
    funnel_html = "".join(
        f'<div class="tf-stage {"hot" if index in (3,4,5) else ""}"><div class="n">{value:,}</div><div class="l">{escape(label)}</div></div>'
        for index, (label, value) in enumerate(stages)
    )
    st.markdown(
        f'<div style="font-size:1.2rem;font-weight:900;margin-top:8px">Market funnel</div><div class="tf-funnel">{funnel_html}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Search time {result.search_elapsed_seconds:.1f}s · "
        f"{result.packages_evaluated} expensive full legality preview(s) · "
        "cached financial + contract routing used before the final safety gate."
    )

    if result.financial_precheck_passes == 0:
        st.error("Financial routing is still the bottleneck. Open diagnostics below to see the exact remaining blocker codes.")
    elif result.legal_packages == 0:
        st.warning("Financial routes exist, but contract / draft-right / Stepien / structural checks removed them.")
    elif not result.proposals:
        st.info(
            f"{result.legal_packages} legal packages exist, but CPU teams declined them. "
            "Negotiation leads are shown below instead of presenting the market as empty."
        )
    else:
        st.success(
            f"Live market: {result.legal_packages} legal package(s) produced "
            f"{len(result.proposals)} CPU-approved offer(s)."
        )

    audit_bytes = _audit_csv_bytes(result)
    export_cols = st.columns([1.2, 2.8])
    with export_cols[0]:
        st.download_button(
            "Download full package audit CSV",
            data=audit_bytes,
            file_name=(
                f"trade_finder_package_audit_{active}_{season}_"
                f"{result.goal}.csv"
            ),
            mime="text/csv",
            width="stretch",
            disabled=not bool(audit_bytes),
            key=f"tf131_audit_download_{active}_{season}_{result.goal}",
        )
    with export_cols[1]:
        st.markdown(
            f'<div class="tf-export-note">Exports <b>{len(getattr(result, "package_audit_rows", ()) or ()):,}</b> '
            'constructed/routed package rows, including rejected packages, player age/OVR/POT/salary, '
            'individual value-model scores, picks, financial results, legality results and CPU decisions.</div>',
            unsafe_allow_html=True,
        )

    diagnostics = st.columns(2)
    with diagnostics[0]:
        with st.expander("Partner-by-partner market funnel", expanded=False):
            rows = []
            for team, data in result.partner_funnel.items():
                rows.append(
                    {
                        "Partner": team,
                        "Targets": data.get("targets", 0),
                        "Packages": data.get("packages", 0),
                        "Financial PASS": data.get("financial_pass", 0),
                        "Legal PASS": data.get("legal_pass", 0),
                        "CPU offers": data.get("cpu_offers", 0),
                    }
                )
            st.dataframe(rows, hide_index=True, width="stretch")
    with diagnostics[1]:
        with st.expander("Rejection diagnostics", expanded=not bool(result.proposals)):
            rows = [
                {
                    "Stage": key.replace("_", " ").title(),
                    "Count": count,
                    "Example codes": ", ".join(result.rejection_examples.get(key, ())) or "—",
                }
                for key, count in sorted(
                    result.rejection_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ]
            st.dataframe(rows, hide_index=True, width="stretch")

    if result.proposals:
        st.markdown("### CPU-approved market")
        for index, proposal in enumerate(result.proposals, start=1):
            _render_deal(proposal, ledger, index, actionable=True)

    if getattr(result, "near_misses", ()):
        st.markdown("### Negotiation leads")
        st.caption(
            "These packages passed live legality but were not recommended. CPU DECLINES means the "
            "other team wants more. USER VALUE GUARD means the CPU would take the deal, but the "
            "Trade Finder thinks you are overpaying. Neither can be loaded as an approved deal."
        )
        for index, proposal in enumerate(result.near_misses, start=1):
            _render_deal(proposal, ledger, 100 + index, actionable=False)

    if not result.proposals and not getattr(result, "near_misses", ()):
        st.warning(
            "No player-centered route survived this search. The funnel and rejection diagnostics above identify the exact stage to tune next."
        )

    st.caption(
        f"Trade Finder {TRADE_FINDER_AI_VERSION} · Value {TRADE_FINDER_VALUE_MODEL_VERSION} · UI {TRADE_FINDER_UI_VERSION}"
    )
