from __future__ import annotations

import html
import time
from typing import Any, Callable, Iterable

import pandas as pd
import streamlit as st

from franchise_command_center_v1 import team_logo_url, team_name
from franchise_draft_engine_v1 import (
    AI_PICK_CLOCK_SECONDS,
    available_prospects,
    catch_up_expired_ai_picks,
    clock_remaining,
    current_pick,
    draft_board_rows,
    draft_state,
    future_user_picks,
    is_user_pick,
    make_selection,
    pause_draft,
    recommended_prospects,
    remaining_user_picks,
    resume_draft,
    simulate_next_pick,
    simulate_rest_of_draft,
    simulate_to_next_round,
    simulate_to_next_user_pick,
    top_team_needs,
)
from franchise_draft_ui_v1 import render_draft_room_v1 as _legacy_render_draft_room_v1
from franchise_generated_player_portraits_v1 import player_image_url

DRAFT_NIGHT_EXPERIENCE_VERSION = "franchise-draft-night-experience-v1.0-2026-09-12"


def _e(value: Any) -> str:
    return html.escape(str(value or ""))


def _commit(commit_state: Callable[..., None], state: Any, reason: str) -> None:
    commit_state(state, checkpoint_reason=reason)


def inject_draft_night_experience_styles_v1() -> None:
    st.markdown(
        """
<style>
.dnx-stage{border:1px solid rgba(255,255,255,.11);border-radius:28px;background:radial-gradient(circle at 78% 4%,rgba(245,179,1,.18),transparent 26%),radial-gradient(circle at 10% 90%,rgba(206,17,65,.14),transparent 30%),linear-gradient(135deg,#0a111e,#070b12 72%);padding:22px 24px;margin:12px 0 16px;overflow:hidden}
.dnx-kicker{font-size:.64rem;letter-spacing:.18em;font-weight:950;color:#f7d66b;text-transform:uppercase}.dnx-title{font-size:2rem;letter-spacing:-.04em;font-weight:1000;color:#fff;margin-top:3px}.dnx-copy{color:#9eadbf;font-size:.82rem;line-height:1.5;margin-top:6px;max-width:1050px}
.dnx-clock{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;border:1px solid rgba(255,255,255,.1);border-radius:24px;background:linear-gradient(120deg,rgba(14,21,34,.98),rgba(13,12,21,.96));padding:20px;margin:10px 0 14px}.dnx-clock-left{display:flex;align-items:center;gap:18px}.dnx-clock-logo{width:86px;height:86px;object-fit:contain}.dnx-clock-kicker{font-size:.64rem;letter-spacing:.17em;font-weight:950;color:#ff6678}.dnx-clock-team{font-size:1.75rem;font-weight:1000;color:#fff;letter-spacing:-.035em}.dnx-clock-meta{font-size:.72rem;color:#9aaabd;margin-top:4px}.dnx-clock-right{text-align:right;display:flex;flex-direction:column;justify-content:center}.dnx-clock-time{font-size:3.8rem;line-height:.95;font-variant-numeric:tabular-nums;font-weight:1000;color:#fff;letter-spacing:-.06em}.dnx-clock-label{font-size:.62rem;color:#8494a8;text-transform:uppercase;letter-spacing:.16em;font-weight:900;margin-top:5px}.dnx-user-clock{font-size:1.28rem;font-weight:950;color:#f7d66b}.dnx-paused{font-size:1.45rem;font-weight:950;color:#f7d66b}
.dnx-ticker{display:flex;gap:8px;overflow-x:auto;padding:4px 0 11px;scrollbar-width:thin}.dnx-tick{flex:0 0 172px;border:1px solid rgba(255,255,255,.09);border-radius:14px;padding:9px 10px;background:rgba(11,17,27,.9);min-height:78px}.dnx-tick.current{border-color:rgba(247,214,107,.55);background:rgba(86,66,15,.23)}.dnx-tick.done{background:rgba(18,31,27,.75)}.dnx-tick-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.dnx-tick-pick{font-size:.57rem;font-weight:950;letter-spacing:.12em;color:#78879a}.dnx-tick-logo{width:24px;height:24px;object-fit:contain}.dnx-tick-main{font-size:.72rem;color:#fff;font-weight:900;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dnx-tick-sub{font-size:.6rem;color:#91a0b3;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dnx-announce{display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center;border:1px solid rgba(247,214,107,.24);border-radius:20px;background:linear-gradient(100deg,rgba(89,66,12,.18),rgba(14,20,30,.92));padding:14px 16px;margin:8px 0 14px}.dnx-announce-logo{width:54px;height:54px;object-fit:contain}.dnx-announce-kicker{font-size:.6rem;letter-spacing:.16em;color:#f7d66b;font-weight:950}.dnx-announce-title{font-size:1rem;color:#fff;font-weight:950;margin-top:3px}.dnx-announce-copy{font-size:.67rem;color:#99a9bc;margin-top:3px}.dnx-grade{border:1px solid rgba(255,255,255,.12);border-radius:15px;padding:8px 12px;text-align:center;min-width:88px}.dnx-grade-letter{font-size:1.3rem;font-weight:1000;color:#fff}.dnx-grade-label{font-size:.55rem;color:#8ea0b4;letter-spacing:.08em;text-transform:uppercase}
.dnx-section-title{font-size:1rem;font-weight:950;color:#fff;margin:16px 0 7px}.dnx-section-copy{font-size:.7rem;color:#8fa0b4;margin-top:-3px;margin-bottom:8px}.dnx-prospects{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:8px 0 12px}.dnx-prospect{border:1px solid rgba(255,255,255,.09);border-radius:18px;overflow:hidden;background:linear-gradient(160deg,rgba(28,35,50,.94),rgba(9,14,23,.96));min-width:0}.dnx-prospect-img{height:152px;width:100%;object-fit:cover;object-position:center 18%;background:#111827}.dnx-prospect-body{padding:11px}.dnx-rank{font-size:.58rem;color:#f7d66b;font-weight:950;letter-spacing:.12em}.dnx-name{font-size:.87rem;color:#fff;font-weight:950;line-height:1.15;margin-top:4px}.dnx-meta{font-size:.61rem;color:#95a6b9;margin-top:4px}.dnx-badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:8px}.dnx-badge{font-size:.54rem;font-weight:850;color:#dce6f2;border:1px solid rgba(255,255,255,.1);border-radius:999px;padding:3px 6px;background:rgba(255,255,255,.035)}.dnx-fit{font-size:.58rem;color:#8ed9bd;margin-top:7px;line-height:1.3}
.dnx-needs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.dnx-need{border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:9px 10px;background:rgba(12,18,28,.82)}.dnx-need-pos{font-size:.58rem;color:#8090a4;font-weight:900;letter-spacing:.12em}.dnx-need-priority{font-size:.85rem;color:#fff;font-weight:950;margin-top:2px}.dnx-need-score{font-size:.6rem;color:#9aabbc;margin-top:2px}
.dnx-capital{display:flex;gap:7px;overflow-x:auto;padding-bottom:3px}.dnx-pick-chip{flex:0 0 auto;border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:7px 9px;background:rgba(11,17,26,.86);font-size:.62rem;color:#cbd7e4}.dnx-pick-chip strong{color:#fff}.dnx-empty{border:1px dashed rgba(255,255,255,.1);border-radius:16px;padding:15px;color:#8292a5;font-size:.72rem}
@media(max-width:1200px){.dnx-prospects{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:850px){.dnx-clock{grid-template-columns:1fr}.dnx-clock-right{text-align:left}.dnx-prospects{grid-template-columns:repeat(2,minmax(0,1fr))}.dnx-needs{grid-template-columns:1fr}.dnx-announce{grid-template-columns:auto 1fr}.dnx-grade{display:none}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _board_value_reaction(pick: dict[str, Any], prospect: dict[str, Any]) -> tuple[str, str]:
    slot = int(pick.get("overall_pick", 0) or 0)
    rank = int(prospect.get("big_board_rank", slot) or slot)
    delta = slot - rank
    if delta >= 8:
        return "A+", "Major value"
    if delta >= 4:
        return "A", "Strong value"
    if delta >= 1:
        return "A-", "Good value"
    if delta >= -2:
        return "B+", "On board"
    if delta >= -6:
        return "B", "Mild reach"
    return "C+", "Aggressive reach"


def _last_pick(current: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    index = int(current.get("current_pick_index", 0) or 0)
    if index <= 0:
        return None, None
    order = current.get("draft_order", [])
    if index - 1 >= len(order):
        return None, None
    pick = order[index - 1]
    prospect_id = str(pick.get("prospect_id", "") or "")
    prospect = next((p for p in current.get("prospects", []) if str(p.get("prospect_id", "")) == prospect_id), None)
    return pick, prospect


def _announcement_html(current: dict[str, Any]) -> str:
    pick, prospect = _last_pick(current)
    if not pick or not prospect:
        return ""
    team = str(pick.get("owner_team", "") or "")
    grade, label = _board_value_reaction(pick, prospect)
    return (
        '<div class="dnx-announce">'
        f'<img class="dnx-announce-logo" src="{_e(team_logo_url(team))}">'
        '<div>'
        '<div class="dnx-announce-kicker">THE PICK IS IN</div>'
        f'<div class="dnx-announce-title">With pick #{int(pick.get("overall_pick", 0) or 0)}, {_e(team_name(team))} selects {_e(prospect.get("player_name"))}</div>'
        f'<div class="dnx-announce-copy">{_e(prospect.get("position"))} · {_e(prospect.get("school"))} · Big board #{int(prospect.get("big_board_rank", 0) or 0)} · Scouted OVR {float(prospect.get("scouted_overall", 0) or 0):.0f} · POT {float(prospect.get("scouted_potential", 0) or 0):.0f}</div>'
        '</div>'
        f'<div class="dnx-grade"><div class="dnx-grade-letter">{grade}</div><div class="dnx-grade-label">{_e(label)}</div></div>'
        '</div>'
    )


def _ticker_html(current: dict[str, Any]) -> str:
    order = current.get("draft_order", [])
    index = int(current.get("current_pick_index", 0) or 0)
    start = max(0, index - 4)
    end = min(len(order), index + 7)
    cards: list[str] = []
    controlled = {str(t).upper() for t in current.get("controlled_teams", [])}
    for idx in range(start, end):
        pick = order[idx]
        team = str(pick.get("owner_team", "") or "")
        classes = ["dnx-tick"]
        if idx < index:
            classes.append("done")
        if idx == index:
            classes.append("current")
        if idx < index and pick.get("player_name"):
            main = _e(pick.get("player_name"))
            sub = f'{_e(team_name(team))} · {_e(pick.get("position"))}'
        elif idx == index:
            main = _e(team_name(team))
            sub = "ON THE CLOCK" if team.upper() not in controlled else "YOUR PICK"
        else:
            main = _e(team_name(team))
            sub = "YOUR PICK" if team.upper() in controlled else "UPCOMING"
        cards.append(
            f'<div class="{" ".join(classes)}">'
            '<div class="dnx-tick-top">'
            f'<div class="dnx-tick-pick">PICK #{int(pick.get("overall_pick", idx + 1) or idx + 1)}</div>'
            f'<img class="dnx-tick-logo" src="{_e(team_logo_url(team))}">'
            '</div>'
            f'<div class="dnx-tick-main">{main}</div><div class="dnx-tick-sub">{sub}</div>'
            '</div>'
        )
    return '<div class="dnx-ticker">' + ''.join(cards) + '</div>'


def _prospect_card_html(row: dict[str, Any], *, team: str = "", show_fit: bool = False) -> str:
    image = player_image_url(row.get("prospect_id"), team=team, player_name=str(row.get("player_name", "") or ""), generated=True)
    badges = [
        f'OVR ~{float(row.get("scouted_overall", 0) or 0):.0f}',
        f'POT ~{float(row.get("scouted_potential", 0) or 0):.0f}',
        f'CONF {float(row.get("scouting_confidence", 0) or 0):.0f}%',
        f'STAR {float(row.get("star_probability", 0) or 0):.0f}%',
        f'BUST {float(row.get("bust_probability", 0) or 0):.0f}%',
    ]
    if show_fit and "team_need_score" in row:
        badges.append(f'NEED {float(row.get("team_need_score", 0) or 0):.0f}')
    badge_html = ''.join(f'<span class="dnx-badge">{_e(b)}</span>' for b in badges)
    fit = f'<div class="dnx-fit">{_e(row.get("fit_reason", ""))}</div>' if show_fit and row.get("fit_reason") else ''
    return (
        '<div class="dnx-prospect">'
        f'<img class="dnx-prospect-img" src="{_e(image)}">'
        '<div class="dnx-prospect-body">'
        f'<div class="dnx-rank">BIG BOARD #{int(row.get("big_board_rank", 0) or 0)}</div>'
        f'<div class="dnx-name">{_e(row.get("player_name"))}</div>'
        f'<div class="dnx-meta">{_e(row.get("position"))} · {_e(row.get("school"))} · Age {row.get("age", "—")}</div>'
        f'<div class="dnx-meta">{_e(row.get("archetype"))} · {_e(row.get("projected_range"))}</div>'
        f'<div class="dnx-badges">{badge_html}</div>{fit}'
        '</div></div>'
    )


def _prospect_grid(rows: list[dict[str, Any]], *, team: str = "", show_fit: bool = False, limit: int = 5) -> None:
    chosen = list(rows)[:limit]
    if not chosen:
        st.markdown('<div class="dnx-empty">No prospects remain available.</div>', unsafe_allow_html=True)
        return
    st.markdown('<div class="dnx-prospects">' + ''.join(_prospect_card_html(row, team=team, show_fit=show_fit) for row in chosen) + '</div>', unsafe_allow_html=True)


def _needs_html(state: Any, team: str) -> str:
    rows = top_team_needs(state, team, limit=3)
    cards = []
    for row in rows:
        cards.append(
            '<div class="dnx-need">'
            f'<div class="dnx-need-pos">{_e(row.get("Position"))} NEED</div>'
            f'<div class="dnx-need-priority">{_e(row.get("Priority"))}</div>'
            f'<div class="dnx-need-score">Need score {float(row.get("Need Score", 0) or 0):.0f}/100 · Starter: {_e(row.get("Starter"))}</div>'
            '</div>'
        )
    return '<div class="dnx-needs">' + ''.join(cards) + '</div>'


def _capital_html(state: Any) -> str:
    picks = remaining_user_picks(state)
    if not picks:
        return '<div class="dnx-empty">No user-controlled picks remain in this draft.</div>'
    chips = []
    for pick in picks[:12]:
        chips.append('<div class="dnx-pick-chip">' f'<strong>#{int(pick.get("overall_pick", 0) or 0)}</strong> · R{int(pick.get("round", 0) or 0)} · {_e(team_name(pick.get("owner_team", "")))}' '</div>')
    return '<div class="dnx-capital">' + ''.join(chips) + '</div>'


def _clock_markup(state: Any, now_ts: float) -> str:
    current = draft_state(state) or {}
    pick = current_pick(current)
    if pick is None:
        return ""
    team = str(pick.get("owner_team", "") or "")
    if is_user_pick(current, pick):
        time_html = '<div class="dnx-user-clock">YOUR FRONT OFFICE</div><div class="dnx-clock-label">Clock paused for your decision</div>'
        kicker = "YOUR PICK"
    elif current.get("paused"):
        remaining = clock_remaining(current, now_ts=now_ts) or AI_PICK_CLOCK_SECONDS
        time_html = f'<div class="dnx-paused">PAUSED · {remaining // 60}:{remaining % 60:02d}</div><div class="dnx-clock-label">Draft clock stopped</div>'
        kicker = "DRAFT PAUSED"
    else:
        remaining = clock_remaining(current, now_ts=now_ts) or 0
        time_html = f'<div class="dnx-clock-time">{remaining // 60}:{remaining % 60:02d}</div><div class="dnx-clock-label">Remaining on pick clock</div>'
        kicker = "ON THE CLOCK"
    return (
        '<div class="dnx-clock"><div class="dnx-clock-left">'
        f'<img class="dnx-clock-logo" src="{_e(team_logo_url(team))}"><div>'
        f'<div class="dnx-clock-kicker">{_e(kicker)}</div><div class="dnx-clock-team">{_e(team_name(team))}</div>'
        f'<div class="dnx-clock-meta">ROUND {int(pick.get("round", 0) or 0)} · PICK #{int(pick.get("overall_pick", 0) or 0)} · ORIGIN {_e(pick.get("origin_team"))}</div>'
        f'</div></div><div class="dnx-clock-right">{time_html}</div></div>'
    )


def _live_clock_body(state: Any, commit_state: Callable[..., None]) -> None:
    current = draft_state(state)
    if not current or current.get("phase") != "draft_in_progress":
        return
    now = time.time()
    caught = catch_up_expired_ai_picks(state, now_ts=now, integrate=True)
    if caught:
        _commit(commit_state, state, "draft-night-auto-pick")
        st.rerun()
    st.markdown(_clock_markup(state, now), unsafe_allow_html=True)


if hasattr(st, "fragment"):
    _clock_fragment = st.fragment(run_every="1s")(_live_clock_body)
else:
    _clock_fragment = _live_clock_body


def _render_live_draft(state: Any, *, controlled_teams: Iterable[str], active_team: str, commit_state: Callable[..., None]) -> None:
    current = draft_state(state)
    if current is None:
        return
    current["controlled_teams"] = sorted({str(team).upper() for team in controlled_teams})
    st.markdown(
        '<div class="dnx-stage"><div class="dnx-kicker">NBA DRAFT NIGHT</div>'
        f'<div class="dnx-title">{int(current.get("draft_year", 0) or 0)} NBA Draft</div>'
        '<div class="dnx-copy">Live pick ticker, scouting-only prospect cards, team needs, user draft capital and the same two-minute AI clock backed by the existing Franchise Draft engine.</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_ticker_html(current), unsafe_allow_html=True)
    announcement = _announcement_html(current)
    if announcement:
        st.markdown(announcement, unsafe_allow_html=True)
    _clock_fragment(state, commit_state)
    current = draft_state(state)
    pick = current_pick(current) if current else None
    if current is None or pick is None:
        st.rerun()
        return

    user_left = remaining_user_picks(state)
    later_user_picks = future_user_picks(state, include_current=False)
    controls = st.columns(5)
    if current.get("paused") and not is_user_pick(current, pick):
        if controls[0].button("Resume Draft", width="stretch", key="dnx_resume_v1"):
            resume_draft(state, now_ts=time.time()); _commit(commit_state, state, "draft-night-resume"); st.rerun()
    elif not is_user_pick(current, pick):
        if controls[0].button("Pause Draft", width="stretch", key="dnx_pause_v1"):
            pause_draft(state, now_ts=time.time()); _commit(commit_state, state, "draft-night-pause"); st.rerun()
    else:
        controls[0].button("Your Pick", disabled=True, width="stretch", key="dnx_user_clock_v1")
    if controls[1].button("Sim Next Pick", width="stretch", key="dnx_sim_next_v1"):
        simulate_next_pick(state, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-sim-next"); st.rerun()
    if later_user_picks:
        if controls[2].button("Sim to My Pick", width="stretch", key="dnx_sim_user_v1"):
            if is_user_pick(current, pick): simulate_next_pick(state, now_ts=time.time(), integrate=True)
            simulate_to_next_user_pick(state, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-sim-user"); st.rerun()
    else:
        controls[2].button("No Later User Pick", disabled=True, width="stretch", key="dnx_no_user_v1")
    if controls[3].button("Sim Next Round", width="stretch", key="dnx_sim_round_v1"):
        simulate_to_next_round(state, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-sim-round"); st.rerun()
    if controls[4].button("Sim Rest", width="stretch", key="dnx_sim_rest_v1"):
        if user_left: st.session_state["dnx_confirm_sim_rest_v1"] = True
        else:
            simulate_rest_of_draft(state, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-sim-rest"); st.rerun()

    if st.session_state.get("dnx_confirm_sim_rest_v1"):
        st.warning(f"You still control {len(user_left)} remaining pick(s). Simulating the rest lets front-office AI make those selections.")
        a, b = st.columns(2)
        if a.button("Confirm Sim Rest", type="primary", width="stretch", key="dnx_confirm_yes_v1"):
            st.session_state.pop("dnx_confirm_sim_rest_v1", None); simulate_rest_of_draft(state, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-sim-rest-confirmed"); st.rerun()
        if b.button("Cancel", width="stretch", key="dnx_confirm_no_v1"):
            st.session_state.pop("dnx_confirm_sim_rest_v1", None); st.rerun()

    st.markdown('<div class="dnx-section-title">Your draft capital</div>', unsafe_allow_html=True)
    st.markdown(_capital_html(state), unsafe_allow_html=True)
    st.markdown('<div class="dnx-section-title">Best available</div><div class="dnx-section-copy">Scouted estimates only. Hidden ratings remain hidden.</div>', unsafe_allow_html=True)
    best = sorted(available_prospects(current), key=lambda row: int(row.get("big_board_rank", 9999) or 9999))
    _prospect_grid(best, team=str(pick.get("owner_team", "") or ""), limit=5)

    if is_user_pick(current, pick):
        team = str(pick.get("owner_team", "") or "")
        st.markdown('<div class="dnx-section-title">Your front office is on the clock</div><div class="dnx-section-copy">Recommendations blend the live depth chart with best-player-available value.</div>', unsafe_allow_html=True)
        st.markdown(_needs_html(state, team), unsafe_allow_html=True)
        st.markdown('<div class="dnx-section-title">Recommended board</div>', unsafe_allow_html=True)
        recs = recommended_prospects(state, team, limit=8)
        _prospect_grid(recs, team=team, show_fit=True, limit=5)
        options = {str(row.get("prospect_id")): row for row in available_prospects(current)}
        selected = st.selectbox("Select prospect", options=list(options), format_func=lambda pid: f"#{options[pid].get('big_board_rank')} · {options[pid].get('player_name')} · {options[pid].get('position')} · {options[pid].get('school')}", key="dnx_user_prospect_v1")
        selected_row = options[selected]
        pick_no = int(pick.get("overall_pick", 0) or 0); board_rank = int(selected_row.get("big_board_rank", pick_no) or pick_no); delta = pick_no - board_rank
        if delta >= 4: st.success(f"Board value: {selected_row.get('player_name')} is ranked #{board_rank}, {delta} slot(s) ahead of pick #{pick_no}.")
        elif delta <= -5: st.warning(f"Board value: {selected_row.get('player_name')} is ranked #{board_rank}, {-delta} slot(s) behind pick #{pick_no}. This would be a reach relative to your current board.")
        else: st.info(f"Board value: {selected_row.get('player_name')} is ranked #{board_rank}, close to pick #{pick_no}.")
        if st.button("Announce Selection", type="primary", width="stretch", key="dnx_select_v1"):
            make_selection(state, selected, selected_by_user=True, now_ts=time.time(), integrate=True); _commit(commit_state, state, "draft-night-user-selection"); st.rerun()

    with st.expander("Full live draft board", expanded=False):
        st.dataframe(pd.DataFrame(draft_board_rows(state)), hide_index=True, width="stretch", height=620)


def render_draft_room_v1(state: Any, runtime: Any, *, controlled_teams: Iterable[str], active_team: str, default_class_strength: int, commit_state: Callable[..., None], set_section: Callable[[str], None] | None = None) -> None:
    inject_draft_night_experience_styles_v1()
    current = draft_state(state)
    if current is not None and current.get("phase") == "draft_in_progress":
        _render_live_draft(state, controlled_teams=controlled_teams, active_team=active_team, commit_state=commit_state)
        return
    _legacy_render_draft_room_v1(state, runtime, controlled_teams=controlled_teams, active_team=active_team, default_class_strength=default_class_strength, commit_state=commit_state, set_section=set_section)
