from __future__ import annotations

import html
import io
import math
import time
import zipfile
from typing import Any, Callable, Iterable

import pandas as pd
import streamlit as st

from franchise_development_center_v1 import render_team_development_center_v1
from franchise_scouting_discovery_v1 import (
    render_scouting_discovery_v1,
    scouting_board_rows_v1,
)

from franchise_command_center_v1 import team_logo_url, team_name
from franchise_draft_engine_v1 import (
    AI_PICK_CLOCK_SECONDS,
    DRAFT_ENGINE_VERSION,
    big_board_rows,
    catch_up_expired_ai_picks,
    clock_remaining,
    conduct_lottery,
    current_pick,
    draft_board_rows,
    draft_is_complete,
    draft_state,
    initialize_draft_state,
    initialize_regular_season_scouting_state,
    promote_regular_season_scouting_to_lottery,
    is_user_pick,
    lottery_rows,
    make_selection,
    pause_draft,
    recommended_prospects,
    remaining_user_picks,
    future_user_picks,
    team_depth_chart_rows,
    top_team_needs,
    resume_draft,
    reveal_draft_class,
    simulate_next_pick,
    simulate_rest_of_draft,
    simulate_to_next_round,
    simulate_to_next_user_pick,
    start_draft_night,
)

DRAFT_UI_VERSION = (
    "franchise-draft-ui-v1.1-2026-08-11+pick-forfeitures-v1-2026-09-07"
)


def escaped(value: Any) -> str:
    return html.escape(str(value or ""))


def inject_draft_styles() -> None:
    st.markdown(
        """
<style>
.draft-stage {
  border:1px solid rgba(255,255,255,.12); border-radius:28px; overflow:hidden;
  background:radial-gradient(circle at 78% 20%,rgba(245,179,1,.16),transparent 30%),linear-gradient(135deg,#0a1222,#070b13 70%);
  padding:22px; margin:14px 0 18px; position:relative;
}
.draft-kicker { color:#f9d66d; font-size:.68rem; font-weight:950; letter-spacing:.18em; text-transform:uppercase; }
.draft-title { color:#fff; font-size:2rem; font-weight:1000; letter-spacing:-.035em; margin-top:4px; }
.draft-copy { color:#aeb9c8; max-width:900px; font-size:.85rem; line-height:1.55; margin-top:7px; }
.draft-lottery-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:14px 0; }
.draft-lottery-card { border:1px solid rgba(255,255,255,.1); border-radius:17px; padding:12px; background:rgba(18,24,36,.82); min-height:112px; }
.draft-lottery-card img { width:42px; height:42px; object-fit:contain; float:right; }
.draft-lottery-slot { color:#f9d66d; font-size:.62rem; font-weight:900; letter-spacing:.1em; }
.draft-lottery-team { color:#fff; font-weight:900; margin-top:5px; }
.draft-lottery-meta { color:#8fa0b5; font-size:.68rem; margin-top:4px; }
.draft-clock-shell { border:1px solid rgba(255,255,255,.12); border-radius:28px; padding:24px; background:linear-gradient(120deg,rgba(16,24,42,.96),rgba(8,12,20,.96)); margin:12px 0; text-align:center; }
.draft-clock-kicker { color:#ff6b75; font-size:.72rem; font-weight:950; letter-spacing:.2em; }
.draft-clock-team { color:#fff; font-size:2.15rem; font-weight:1000; letter-spacing:-.04em; margin-top:4px; }
.draft-clock-pick { color:#aeb9c8; font-size:.82rem; margin-top:4px; }
.draft-clock-time { color:#fff; font-size:4.6rem; font-weight:1000; letter-spacing:-.06em; line-height:1; margin:18px 0 8px; font-variant-numeric:tabular-nums; }
.draft-clock-paused { color:#f9d66d; font-size:1.25rem; font-weight:950; margin:18px 0 8px; }
.draft-prospect-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:12px 0; }
.draft-prospect-card { border:1px solid rgba(255,255,255,.1); border-radius:18px; padding:13px; background:linear-gradient(145deg,rgba(24,31,46,.92),rgba(10,15,25,.92)); }
.draft-prospect-rank { color:#f9d66d; font-size:.62rem; font-weight:950; letter-spacing:.12em; }
.draft-prospect-name { color:#fff; font-size:.93rem; font-weight:950; margin-top:4px; }
.draft-prospect-meta { color:#9badc1; font-size:.68rem; margin-top:3px; }
.draft-grade-row { display:flex; flex-wrap:wrap; gap:5px; margin-top:9px; }
.draft-grade { border:1px solid rgba(255,255,255,.11); border-radius:999px; padding:4px 7px; color:#dce6f2; font-size:.6rem; background:rgba(255,255,255,.04); }
.draft-ticker { display:flex; gap:8px; overflow-x:auto; padding:8px 0 12px; scrollbar-width:thin; }
.draft-ticker-item { flex:0 0 180px; border:1px solid rgba(255,255,255,.09); border-radius:13px; padding:9px; background:rgba(14,19,28,.88); }
.draft-ticker-pick { color:#718096; font-size:.6rem; font-weight:900; }
.draft-ticker-player { color:#fff; font-size:.72rem; font-weight:850; margin-top:3px; }
.draft-ticker-team { color:#9badc1; font-size:.61rem; margin-top:2px; }
.draft-current { border-color:rgba(249,214,109,.55); background:rgba(82,62,13,.24); }
@media (max-width:1050px) { .draft-lottery-grid,.draft-prospect-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
        """,
        unsafe_allow_html=True,
    )


def _commit(commit_state: Callable[..., None], state: Any, reason: str) -> None:
    commit_state(state, checkpoint_reason=reason)


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


def _download_csv(label: str, rows: list[dict[str, Any]], filename: str, *, key: str) -> None:
    st.download_button(label, data=_csv_bytes(rows), file_name=filename, mime="text/csv", width="stretch", key=key)


def _draft_export_bundle(state: Any) -> bytes:
    current = draft_state(state) or {}
    year = int(current.get("draft_year", 0) or 0)
    files = {
        f"draft_lottery_{year}.csv": lottery_rows(state),
        f"draft_order_results_{year}.csv": draft_board_rows(state),
        f"draft_class_scouting_{year}.csv": big_board_rows(state),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, rows in files.items():
            archive.writestr(filename, _csv_bytes(rows))
    return buffer.getvalue()


def _export_bar(state: Any, *, stage_key: str) -> None:
    current = draft_state(state)
    if current is None:
        return
    year = int(current.get("draft_year", 0) or 0)
    columns = st.columns(4)
    with columns[0]:
        _download_csv("Download lottery CSV", lottery_rows(state), f"draft_lottery_{year}.csv", key=f"draft_export_lottery_{stage_key}")
    with columns[1]:
        _download_csv("Download draft order CSV", draft_board_rows(state), f"draft_order_results_{year}.csv", key=f"draft_export_order_{stage_key}")
    with columns[2]:
        _download_csv("Download scouting CSV", big_board_rows(state), f"draft_class_scouting_{year}.csv", key=f"draft_export_class_{stage_key}")
    with columns[3]:
        st.download_button("Download all draft CSVs", data=_draft_export_bundle(state), file_name=f"draft_audit_bundle_{year}.zip", mime="application/zip", width="stretch", key=f"draft_export_bundle_{stage_key}")


def _render_team_needs(state: Any, team: str) -> None:
    needs = top_team_needs(state, team, limit=3)
    depth = team_depth_chart_rows(state, team)
    st.markdown("### Roster needs before you pick")
    st.caption("Recommendations blend best-player-available value with the live franchise depth chart.")
    need_cols = st.columns(3)
    for column, row in zip(need_cols, needs):
        with column:
            st.metric(f"{row['Position']} need", row["Priority"], f"Need score {row['Need Score']:.0f}/100")
            st.caption(f"Starter: {row['Starter']} · Backup: {row['Backup']} · Depth: {row['Depth']}")
    with st.expander("Full position depth chart", expanded=False):
        st.dataframe(pd.DataFrame(depth), hide_index=True, width="stretch")


def _stage_header(title: str, detail: str, kicker: str = "NBA OFFSEASON") -> None:
    st.markdown(
        (
            '<div class="draft-stage">'
            f'<div class="draft-kicker">{escaped(kicker)}</div>'
            f'<div class="draft-title">{escaped(title)}</div>'
            f'<div class="draft-copy">{escaped(detail)}</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def _lottery_result_html(state: Any) -> str:
    current = draft_state(state)
    cards = []
    for item in current.get("lottery_order", [])[:16]:
        team = item["team"]
        cards.append(
            '<div class="draft-lottery-card">'
            f'<img src="{escaped(team_logo_url(team))}">'
            f'<div class="draft-lottery-slot">PICK #{int(item["slot"])}</div>'
            f'<div class="draft-lottery-team">{escaped(team_name(team))}</div>'
            f'<div class="draft-lottery-meta">{int(item["balls"])} lottery ball(s) · {int(item["wins"])}-{int(item["losses"])}</div>'
            '</div>'
        )
    return '<div class="draft-lottery-grid">' + ''.join(cards) + '</div>'


def _prospect_cards(rows: list[dict[str, Any]]) -> None:
    cards = []
    for row in rows[:8]:
        cards.append(
            '<div class="draft-prospect-card">'
            f'<div class="draft-prospect-rank">BIG BOARD #{int(row["big_board_rank"])}</div>'
            f'<div class="draft-prospect-name">{escaped(row["player_name"])}</div>'
            f'<div class="draft-prospect-meta">{escaped(row["position"])} · {escaped(row["school"])} · Age {row["age"]}</div>'
            f'<div class="draft-prospect-meta">{escaped(row["archetype"])} · {escaped(row["projected_range"])}</div>'
            '<div class="draft-grade-row">'
            f'<span class="draft-grade">OVR ~ {float(row["scouted_overall"]):.0f}</span>'
            f'<span class="draft-grade">POT ~ {float(row["scouted_potential"]):.0f}</span>'
            f'<span class="draft-grade">CONF {float(row["scouting_confidence"]):.0f}%</span>'
            f'<span class="draft-grade">STAR {float(row["star_probability"]):.0f}%</span>'
            + (f'<span class="draft-grade">FIT {float(row["team_fit_score"]):.0f}</span>' if "team_fit_score" in row else "")
            + '</div>'
            + (f'<div class="draft-prospect-meta">{escaped(row.get("fit_reason", ""))}</div>' if row.get("fit_reason") else "")
            + '</div>'
        )
    st.markdown('<div class="draft-prospect-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)


def _ticker(state: Any) -> None:
    current = draft_state(state)
    index = int(current.get("current_pick_index", 0))
    start = max(0, index - 5)
    end = min(len(current.get("draft_order", [])), index + 4)
    items = []
    for pick in current.get("draft_order", [])[start:end]:
        css = " draft-current" if int(pick["overall_pick"]) == index + 1 else ""
        player = pick.get("player_name") or "ON THE CLOCK"
        items.append(
            f'<div class="draft-ticker-item{css}">'
            f'<div class="draft-ticker-pick">#{int(pick["overall_pick"])} · {escaped(pick["owner_team"])}</div>'
            f'<div class="draft-ticker-player">{escaped(player)}</div>'
            f'<div class="draft-ticker-team">{escaped(team_name(pick["owner_team"]))}</div>'
            '</div>'
        )
    st.markdown('<div class="draft-ticker">' + ''.join(items) + '</div>', unsafe_allow_html=True)


def _clock_markup(state: Any, now_ts: float) -> str:
    current = draft_state(state)
    pick = current_pick(current)
    if pick is None:
        return ""
    user_pick = is_user_pick(current, pick)
    if user_pick:
        clock_html = '<div class="draft-clock-paused">CLOCK PAUSED FOR USER DECISION</div>'
        kicker = "YOUR PICK"
    elif current.get("paused"):
        remaining = clock_remaining(current, now_ts=now_ts) or AI_PICK_CLOCK_SECONDS
        clock_html = f'<div class="draft-clock-paused">PAUSED · {remaining // 60}:{remaining % 60:02d}</div>'
        kicker = "DRAFT PAUSED"
    else:
        remaining = clock_remaining(current, now_ts=now_ts) or 0
        clock_html = f'<div class="draft-clock-time">{remaining // 60}:{remaining % 60:02d}</div>'
        kicker = "ON THE CLOCK"
    return (
        '<div class="draft-clock-shell">'
        f'<div class="draft-clock-kicker">{escaped(kicker)}</div>'
        f'<div class="draft-clock-team">{escaped(team_name(pick["owner_team"]))}</div>'
        f'<div class="draft-clock-pick">ROUND {int(pick["round"])} · PICK {int(pick["overall_pick"])} · ORIGIN {escaped(pick["origin_team"])}</div>'
        f'{clock_html}'
        '</div>'
    )


def _live_clock_body(state: Any, commit_state: Callable[..., None]) -> None:
    current = draft_state(state)
    if not current or current.get("phase") != "draft_in_progress":
        return
    now = time.time()
    caught = catch_up_expired_ai_picks(state, now_ts=now, integrate=True)
    if caught:
        _commit(commit_state, state, "draft-clock-auto-pick")
        st.rerun()
    st.markdown(_clock_markup(state, now), unsafe_allow_html=True)


if hasattr(st, "fragment"):
    _clock_fragment = st.fragment(run_every="1s")(_live_clock_body)
else:
    _clock_fragment = _live_clock_body


def render_draft_room_v1(
    state: Any,
    runtime: Any,
    *,
    controlled_teams: Iterable[str],
    active_team: str,
    default_class_strength: int,
    commit_state: Callable[..., None],
    set_section: Callable[[str], None] | None = None,
) -> None:
    inject_draft_styles()

    # FRANCHISE_SEASON_LONG_SCOUTING_UI_V1_2
    postseason_complete = bool(
        getattr(state, "postseason_state", None)
        and str(
            getattr(
                state.postseason_state.stage,
                "value",
                state.postseason_state.stage,
            )
        ).lower()
        == "complete"
    )
    current = draft_state(state)

    if not postseason_complete:
        has_prior_season = bool(getattr(state, "season_history", None))
        if current is None and has_prior_season:
            current = initialize_regular_season_scouting_state(
                state,
                controlled_teams=controlled_teams,
                class_strength=default_class_strength,
            )
            _commit(commit_state, state, "draft-season-long-scouting-initialize-v1-2")

        if current is not None and current.get("phase") == "season_scouting":
            _stage_header(
                f"{current['draft_year']} Draft Class",
                "Scout the next class all season. Reports, confidence and focus assignments persist through the postseason, lottery and Draft Night. The lottery order remains unresolved until the season is complete.",
                kicker="SEASON-LONG SCOUTING",
            )
            render_scouting_discovery_v1(
                state=state,
                team=active_team,
                commit_state=commit_state,
            )
            st.info(
                "The Draft Lottery will unlock after the NBA Finals. Your current scouting work will carry forward unchanged."
            )
            return

        _stage_header(
            "Draft Room",
            "The next draft class becomes available after your first completed franchise season. Lottery and Draft Night remain postseason events.",
        )
        return

    if current is not None and current.get("phase") == "season_scouting":
        _stage_header(
            f"{current['draft_year']} Draft Class",
            "Season-long scouting is complete and preserved. Enter the Draft Lottery when you are ready; prospect reports and confidence will not reset.",
            kicker="SCOUTING COMPLETE · LOTTERY READY",
        )
        render_scouting_discovery_v1(
            state=state,
            team=active_team,
            commit_state=commit_state,
        )
        if st.button(
            "Enter NBA Draft Lottery",
            type="primary",
            width="stretch",
            key="draft_promote_season_scouting_v1_2",
        ):
            promote_regular_season_scouting_to_lottery(
                state,
                controlled_teams=controlled_teams,
            )
            _commit(commit_state, state, "draft-season-scouting-to-lottery-v1-2")
            st.rerun()
        return

    if current is None:
        _stage_header(
            f"{state.settings.season_label} season complete",
            "Your next required offseason event is the NBA Draft Lottery. The current franchise uses the NBA's 3-2-1 lottery structure for the 2027-2029 drafts.",
            kicker="NEXT CHAPTER",
        )
        strength = st.slider(
            "Generated draft-class strength",
            min_value=1,
            max_value=10,
            value=max(1, min(10, int(default_class_strength))),
            help="Controls the generated class's top-end talent, depth, sleepers and bust risk.",
            key="draft_room_class_strength_v1",
        )
        if st.button("Enter NBA Draft Lottery", type="primary", width="stretch", key="draft_initialize_v1"):
            initialize_draft_state(
                state,
                runtime,
                controlled_teams=controlled_teams,
                class_strength=strength,
            )
            _commit(commit_state, state, "draft-initialize")
            st.rerun()
        return

    current["controlled_teams"] = sorted({str(team).upper() for team in controlled_teams})
    phase = current.get("phase")

    if phase == "lottery_ready":
        _stage_header(
            f"{current['draft_year']} NBA Draft Lottery",
            "Sixteen teams enter the 3-2-1 lottery. Teams outside the Play-In receive three balls except the three worst records, which are draft-relegated to two. Play-In seeds 9-10 receive two balls, while the losers of the 7-v-8 games receive one.",
            kicker="DRAFT LOTTERY",
        )
        st.dataframe(pd.DataFrame(lottery_rows(state)), hide_index=True, width="stretch")
        _export_bar(state, stage_key="lottery_ready")
        if st.button("Reveal Lottery Order", type="primary", width="stretch", key="draft_run_lottery_v1"):
            conduct_lottery(state, runtime)
            _commit(commit_state, state, "draft-lottery-complete")
            st.rerun()
        return

    if phase == "lottery_complete":
        _stage_header(
            f"{current['draft_year']} Lottery Results",
            "The first 16 origin-team slots are locked. Direct traded-pick ownership from the canonical pick-right inventory is applied when deterministic; complex swaps and protections are flagged conservatively for later resolution.",
            kicker="LOTTERY RESULTS",
        )
        st.markdown(_lottery_result_html(state), unsafe_allow_html=True)
        with st.expander(
            f"Full {len(current.get('draft_order', []))}-pick order and ownership audit"
        ):
            st.dataframe(pd.DataFrame(draft_board_rows(state)), hide_index=True, width="stretch")
        _export_bar(state, stage_key="lottery_complete")
        _class_button_label_v1_2 = (
            "Continue to Draft Board"
            if current.get("prospects")
            else "Reveal Draft Class"
        )
        if st.button(_class_button_label_v1_2, type="primary", width="stretch", key="draft_reveal_class_v1"):
            reveal_draft_class(state)
            _commit(commit_state, state, "draft-class-reveal")
            st.rerun()
        return

    if phase == "scouting":
        # FRANCHISE_SCOUTING_DISCOVERY_UI_V1
        _stage_header(
            f"{current['draft_year']} Draft Class",
            "Build team-specific confidence through scouting assignments. Staff quality controls uncertainty, and CPU front offices now draft from imperfect team-specific evaluations rather than exact hidden ratings.",
            kicker="SCOUTING & PROSPECT DISCOVERY",
        )
        render_scouting_discovery_v1(
            state=state,
            team=active_team,
            commit_state=commit_state,
        )
        _export_bar(state, stage_key="scouting")
        if st.button("Start Draft Night", type="primary", width="stretch", key="draft_start_night_v1"):
            start_draft_night(state, now_ts=time.time())
            _commit(commit_state, state, "draft-night-start")
            st.rerun()
        return

    if phase == "draft_in_progress":
        _stage_header(
            f"{current['draft_year']} NBA Draft",
            "AI-controlled picks use a two-minute Franchise Mode clock. Pause at any time, or jump to the next pick, your next pick, the next round, or the end of the draft. User picks pause automatically.",
            kicker="DRAFT NIGHT",
        )
        _ticker(state)
        _clock_fragment(state, commit_state)
        current = draft_state(state)
        pick = current_pick(current)
        if pick is None:
            st.rerun()
            return

        user_left = remaining_user_picks(state)
        later_user_picks = future_user_picks(state, include_current=False)
        controls = st.columns(5)
        if current.get("paused") and not is_user_pick(current, pick):
            if controls[0].button("Resume Draft", width="stretch", key="draft_resume_v1"):
                resume_draft(state, now_ts=time.time())
                _commit(commit_state, state, "draft-resume")
                st.rerun()
        elif not is_user_pick(current, pick):
            if controls[0].button("Pause Draft", width="stretch", key="draft_pause_v1"):
                pause_draft(state, now_ts=time.time())
                _commit(commit_state, state, "draft-pause")
                st.rerun()
        else:
            controls[0].button("User Clock Paused", disabled=True, width="stretch", key="draft_user_paused_v1")

        if controls[1].button("Sim to Next Pick", width="stretch", key="draft_sim_next_v1"):
            simulate_next_pick(state, now_ts=time.time(), integrate=True)
            _commit(commit_state, state, "draft-sim-to-next-pick")
            st.rerun()

        if later_user_picks:
            if controls[2].button("Sim to My Next Pick", width="stretch", key="draft_sim_user_v1"):
                if is_user_pick(current, pick):
                    simulate_next_pick(state, now_ts=time.time(), integrate=True)
                simulate_to_next_user_pick(state, now_ts=time.time(), integrate=True)
                _commit(commit_state, state, "draft-sim-to-user-pick")
                st.rerun()
        else:
            controls[2].empty()

        if controls[3].button("Sim to Next Round", width="stretch", key="draft_sim_round_v1"):
            simulate_to_next_round(state, now_ts=time.time(), integrate=True)
            _commit(commit_state, state, "draft-sim-next-round")
            st.rerun()

        if controls[4].button("Sim Rest of Draft", width="stretch", key="draft_sim_rest_v1"):
            if user_left:
                st.session_state["draft_confirm_sim_rest_v1"] = True
            else:
                simulate_rest_of_draft(state, now_ts=time.time(), integrate=True)
                _commit(commit_state, state, "draft-sim-rest")
                st.rerun()

        if st.session_state.get("draft_confirm_sim_rest_v1"):
            st.warning(
                f"You still control {len(user_left)} remaining pick(s). Simulating the rest will let your front-office AI make those selections."
            )
            confirm_cols = st.columns(2)
            if confirm_cols[0].button("Confirm Sim Rest", type="primary", width="stretch", key="draft_confirm_rest_yes_v1"):
                st.session_state.pop("draft_confirm_sim_rest_v1", None)
                simulate_rest_of_draft(state, now_ts=time.time(), integrate=True)
                _commit(commit_state, state, "draft-sim-rest-user-confirmed")
                st.rerun()
            if confirm_cols[1].button("Cancel", width="stretch", key="draft_confirm_rest_no_v1"):
                st.session_state.pop("draft_confirm_sim_rest_v1", None)
                st.rerun()

        if is_user_pick(current, pick):
            st.markdown("### Your front office is on the clock")
            _render_team_needs(state, pick["owner_team"])
            st.markdown("### Recommended prospects")
            recs = recommended_prospects(state, pick["owner_team"], limit=8)
            _prospect_cards(recs)
            option_map = {row["prospect_id"]: row for row in available_prospects_for_ui(current)}
            selected = st.selectbox(
                "Select prospect",
                options=list(option_map),
                format_func=lambda prospect_id: (
                    f"#{option_map[prospect_id]['big_board_rank']} · "
                    f"{option_map[prospect_id]['player_name']} · "
                    f"{option_map[prospect_id]['position']} · "
                    f"{option_map[prospect_id]['school']}"
                ),
                key="draft_user_prospect_v1",
            )
            decision_cols = st.columns([2, 1, 1])
            if decision_cols[0].button("Draft Player", type="primary", width="stretch", key="draft_user_select_v1"):
                make_selection(state, selected, selected_by_user=True, now_ts=time.time(), integrate=True)
                _commit(commit_state, state, "draft-user-selection")
                st.rerun()
            decision_cols[1].button("Shop Pick · next slice", disabled=True, width="stretch", key="draft_shop_pick_placeholder")
            decision_cols[2].button("View Offers · next slice", disabled=True, width="stretch", key="draft_view_offers_placeholder")

        with st.expander("Live Draft Board", expanded=False):
            st.dataframe(pd.DataFrame(draft_board_rows(state)), hide_index=True, width="stretch", height=620)
        _export_bar(state, stage_key="draft_live")
        return

    if phase == "draft_complete":
        _stage_header(
            f"{current['draft_year']} NBA Draft Complete",
            f"All {len(current.get('draft_order', []))} selections are finalized and checkpointed. Drafted rookies are attached to their teams and will activate as true rookies when the next season opens.",
            kicker="DRAFT COMPLETE",
        )
        st.success("Draft complete. The next-season transition is now unlocked.")
        st.dataframe(pd.DataFrame(draft_board_rows(state)), hide_index=True, width="stretch", height=700)
        unresolved = sum(
            pick.get("owner_resolution") == "complex_right_requires_slot_resolution"
            for pick in current.get("draft_order", [])
        )
        if unresolved:
            st.warning(
                f"{unresolved} physical pick(s) involved complex swap/protection structures and currently retain the origin team as a conservative ownership fallback. Draft Pick Rights Resolution V2 will resolve those branches before pick-trading is enabled."
            )
        _export_bar(state, stage_key="draft_complete")
        # OFFSEASON TEAM DEVELOPMENT CENTER V1
        # DYNAMIC DEVELOPMENT CENTER RELOAD V2.1
        import importlib as _development_center_importlib
        import franchise_development_center_v1 as _development_center_module
        _development_center_module = _development_center_importlib.reload(
            _development_center_module
        )
        _development_center_module.render_team_development_center_v1(
            state,
            active_team,
        )
        st.markdown("### Continue your franchise")
        st.caption(
            "The Draft is complete. The next season must open through the "
            "Franchise Season Boundary so the certified post-Draft CPU trim, "
            "TradeState reconciliation, financial-rights rollover, and atomic "
            "checkpoint commit all run through one authority."
        )
        if set_section is not None:
            if st.button(
                "Return to Season Boundary",
                type="primary",
                width="stretch",
                key="draft_complete_return_to_season_boundary_v1",
            ):
                set_section("League & Offseason")
                st.session_state["franchise_notice"] = (
                    "Draft complete. Open the next season from the certified "
                    "Season Boundary control."
                )
                st.rerun()
        else:
            st.info(
                "Return to Franchise Home and use the certified Season Boundary "
                "control to open the next season."
            )
        return


def available_prospects_for_ui(current: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in current.get("prospects", []) if not row.get("drafted")]
