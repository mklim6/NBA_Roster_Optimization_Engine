from __future__ import annotations

import html
from typing import Any, Callable
from urllib.parse import quote


FRANCHISE_GAME_NAVIGATION_V1_VERSION = "franchise-game-navigation-v2-native-2026-09-11"
FRANCHISE_GAME_QUERY_KEY = "fgame"
FRANCHISE_GAME_ARCHIVE_SESSION_KEY = "franchise_game_archive_id"


def _text(value: Any) -> str:
    return str(value or "").strip()


def game_href(game_id: str) -> str:
    # Kept only for backward compatibility with any stale bookmarks. New UI controls
    # route through Streamlit session state and do not use browser navigation.
    return f"?{FRANCHISE_GAME_QUERY_KEY}={quote(_text(game_id), safe='')}"


def requested_game_id_v1() -> str:
    import streamlit as st

    value = st.query_params.get(FRANCHISE_GAME_QUERY_KEY, "")
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else ""
    return _text(value)


def clear_requested_game_id_v1() -> None:
    import streamlit as st

    try:
        if FRANCHISE_GAME_QUERY_KEY in st.query_params:
            del st.query_params[FRANCHISE_GAME_QUERY_KEY]
    except Exception:
        pass


def _game_status(game: Any) -> str:
    return _text(getattr(getattr(game, "status", None), "value", getattr(game, "status", ""))).lower()


def _route_game_native_v2(*, state: Any, team: str, game_id: str) -> None:
    """Route a schedule click entirely inside Streamlit state.

    This deliberately avoids HTML href/query-parameter navigation, which can open a
    separate browser tab or lose the current Streamlit session.
    """
    import streamlit as st

    game_id = _text(game_id)
    team = _text(team).upper()
    game = (getattr(state, "schedule", {}) or {}).get(game_id)
    if game is None:
        st.warning("That game is no longer present in the active franchise schedule.")
        return

    participants = {
        _text(getattr(game, "home_team", "")).upper(),
        _text(getattr(game, "away_team", "")).upper(),
    }
    if team and team not in participants:
        st.warning("That game does not belong to the active franchise team.")
        return

    if _game_status(game) == "completed" and game_id in (getattr(state, "completed_games", {}) or {}):
        st.session_state[FRANCHISE_GAME_ARCHIVE_SESSION_KEY] = game_id
        st.session_state["franchise_last_committed_game_id"] = game_id
    else:
        st.session_state.pop(FRANCHISE_GAME_ARCHIVE_SESSION_KEY, None)
        st.session_state["franchise_selected_game_id"] = game_id
        st.session_state.pop("franchise_game_preview", None)
        st.session_state.pop("franchise_game_preview_request", None)

    # The section radio already exists by the time a schedule control is clicked.
    # Use the page's pending-section handoff rather than mutating the widget key.
    st.session_state["franchise_pending_section"] = "Game Day"
    st.rerun()


def inject_franchise_game_navigation_visuals_v1() -> None:
    import streamlit as st

    st.markdown(
        """
<style>
/* FRANCHISE_GAME_NAVIGATION_V2_NATIVE */
.fgn-native-card{min-height:128px;padding:10px 8px 9px;border:1px solid rgba(148,163,184,.18);border-radius:14px;background:linear-gradient(180deg,rgba(15,23,42,.72),rgba(8,15,27,.82));text-align:center;margin-bottom:6px}
.fgn-native-card.selected,.fgn-native-card.next{border-color:rgba(244,63,94,.70);box-shadow:0 0 0 1px rgba(244,63,94,.13),0 12px 26px rgba(0,0,0,.18)}
.fgn-native-card.completed{border-color:rgba(148,163,184,.24)}
.fgn-native-date{font-size:.52rem;font-weight:900;letter-spacing:.04em;color:#cbd5e1;margin-bottom:5px}.fgn-native-card img{width:48px;height:48px;object-fit:contain;display:block;margin:0 auto 5px}.fgn-native-opp{font-size:.66rem;font-weight:900;color:#eef4fb}.fgn-native-result{font-size:.50rem;font-weight:850;color:#8fa3ba;margin-top:3px}.fgn-native-card.next .fgn-native-result{color:#7dd3fc}.fgn-native-card.completed .fgn-native-result{color:#cbd5e1}
.fgn-weekday{text-align:center;color:#7f91a7;font-size:.54rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin:4px 0 7px}.fgn-day-shell{min-height:108px;padding:8px;border:1px solid rgba(148,163,184,.14);border-radius:12px;background:rgba(15,23,42,.40);margin-bottom:4px}.fgn-day-shell.outside{opacity:.32}.fgn-day-date{font-size:.55rem;font-weight:900;color:#cbd5e1;margin-bottom:6px}.fgn-day-rest{font-size:.48rem;color:#64748b;font-weight:800;padding-top:20px;text-align:center}.fgn-day-match{font-size:.58rem;color:#e5edf7;font-weight:900;text-align:center}.fgn-day-result{font-size:.48rem;color:#8fa3ba;font-weight:800;text-align:center;margin-top:3px}.fgn-day-shell img{width:34px;height:34px;object-fit:contain;display:block;margin:0 auto 4px}
/* Keep the larger Game Day presentation from Navigation V1. */
.fgb-scoreboard{min-height:228px!important;padding:34px 30px 28px!important;grid-template-columns:minmax(220px,1fr) minmax(225px,.68fr) minmax(220px,1fr)!important}
.fgb-team{gap:20px!important}.fgb-team img{width:132px!important;height:132px!important}.fgb-team-name{font-size:1.28rem!important}.fgb-record{font-size:.80rem!important}.fgb-date{font-size:1.04rem!important}.fgb-season{font-size:.64rem!important}.fgb-control{font-size:.55rem!important;padding:5px 9px!important}
.fgb-ticker{padding:10px 14px!important;font-size:.56rem!important}.fgb-title{font-size:1.08rem!important}.fgb-note{font-size:.58rem!important}
.fgb-lineup{padding:15px!important;border-radius:18px!important}.fgb-lineup-head{font-size:.69rem!important;margin-bottom:10px!important}.fgb-lineup-head img{width:29px!important;height:29px!important}.fgb-player-row{gap:7px!important}.fgb-player{padding:7px 5px 8px!important;border-radius:11px!important}.fgb-player img,.fgb-player-placeholder{height:86px!important}.fgb-player-name{font-size:.61rem!important}.fgb-player-meta{font-size:.50rem!important}.fgb-player-stat{font-size:.48rem!important;margin-top:3px!important}
.fgb-spotlight{grid-template-columns:126px 1fr!important;min-height:150px!important;padding:10px 17px 10px 9px!important}.fgb-spotlight-img{width:122px!important;height:138px!important}.fgb-spotlight-name{font-size:.95rem!important}.fgb-spotlight-meta{font-size:.58rem!important}.fgb-spotlight-line{font-size:.62rem!important}
.fgb-tape-card{min-height:66px!important;padding:14px!important}.fgb-tape-side{font-size:.82rem!important}.fgb-tape-label{font-size:.51rem!important}.fgb-key{min-height:108px!important;padding:15px!important}.fgb-key-title{font-size:.73rem!important}.fgb-key-copy{font-size:.60rem!important}
@media(max-width:1100px){.fgb-scoreboard{grid-template-columns:1fr 170px 1fr!important;padding:24px 18px!important}.fgb-team img{width:98px!important;height:98px!important}.fgb-player img,.fgb-player-placeholder{height:72px!important}}
@media(max-width:700px){.fgb-scoreboard{min-height:auto!important;grid-template-columns:1fr 82px 1fr!important;padding:16px 9px!important}.fgb-team img{width:62px!important;height:62px!important}.fgb-team-name{font-size:.72rem!important}.fgb-lineups{grid-template-columns:1fr!important}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_interactive_schedule_ribbon_v1(
    *,
    state: Any,
    team: str,
    team_logo_resolver: Callable[[str], str],
    selected_game_id: str | None = None,
    title: str = "Season rail",
) -> None:
    import streamlit as st
    from franchise_calendar_v1 import team_game_card, team_schedule_games

    team = _text(team).upper()
    if not team or not getattr(state, "schedule", None):
        return
    games = list(team_schedule_games(state, team))
    if not games:
        return

    selected_game_id = _text(selected_game_id)
    anchor = None
    if selected_game_id:
        for idx, game in enumerate(games):
            if _text(getattr(game, "game_id", "")) == selected_game_id:
                anchor = idx
                break
    if anchor is None:
        for idx, game in enumerate(games):
            if _game_status(game) == "scheduled":
                anchor = idx
                break
    if anchor is None:
        anchor = max(0, len(games) - 1)

    start = max(0, min(anchor - 2, len(games) - 7))
    window = games[start:start + 7]
    completed_count = sum(1 for game in games if _game_status(game) == "completed")

    next_scheduled_id = ""
    for candidate in games:
        if _game_status(candidate) == "scheduled" and int(getattr(candidate, "day_index", 0) or 0) >= int(getattr(state, "current_day_index", 0) or 0):
            next_scheduled_id = _text(getattr(candidate, "game_id", ""))
            break

    head_left, head_right = st.columns([4, 1])
    with head_left:
        st.markdown(f"**{title}**")
    with head_right:
        st.caption(f"{completed_count} of {len(games)} games complete")

    cols = st.columns(len(window), gap="small")
    for idx, (col, game) in enumerate(zip(cols, window)):
        game_id = _text(getattr(game, "game_id", ""))
        card = team_game_card(state, team, game)
        is_selected = game_id == selected_game_id
        is_next = bool(next_scheduled_id and game_id == next_scheduled_id)
        classes = ["fgn-native-card"]
        if card.status == "completed":
            classes.append("completed")
        if is_next:
            classes.append("next")
        if is_selected:
            classes.append("selected")
        location = "VS" if card.location == "HOME" else "AT"
        if card.status == "completed":
            result_copy = f"{card.result} {card.team_score}-{card.opponent_score}"
            action_copy = "View box score"
        elif is_next:
            result_copy = "NEXT GAME"
            action_copy = "Open Game Day"
        elif is_selected:
            result_copy = "SELECTED"
            action_copy = "Open Game Day"
        else:
            result_copy = "UPCOMING"
            action_copy = "View matchup"
        logo = _text(team_logo_resolver(card.opponent))
        with col:
            st.markdown(
                f'<div class="{" ".join(classes)}">'
                f'<div class="fgn-native-date">{html.escape(card.calendar_date.strftime("%b %d"))}</div>'
                f'<img src="{html.escape(logo, quote=True)}" alt="{html.escape(card.opponent)}">'
                f'<div class="fgn-native-opp">{location} {html.escape(card.opponent)}</div>'
                f'<div class="fgn-native-result">{html.escape(result_copy)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                action_copy,
                key=f"fgn_native_rail_{game_id}_{start}_{idx}",
                width="stretch",
            ):
                _route_game_native_v2(state=state, team=team, game_id=game_id)


def render_clickable_month_calendar_v2(*, month_calendar: Any, state: Any, team: str) -> None:
    """Render a month calendar with native Streamlit game controls."""
    import streamlit as st
    from franchise_command_center_v1 import team_logo_url

    labels = list(month_calendar.weekday_labels)
    label_cols = st.columns(7, gap="small")
    for col, label in zip(label_cols, labels):
        with col:
            st.markdown(f'<div class="fgn-weekday">{html.escape(str(label))}</div>', unsafe_allow_html=True)

    for week_index, week in enumerate(month_calendar.weeks):
        cols = st.columns(7, gap="small")
        for day_index, (col, cell) in enumerate(zip(cols, week)):
            with col:
                if not cell.in_month:
                    st.markdown(
                        f'<div class="fgn-day-shell outside"><div class="fgn-day-date">{cell.calendar_date.day}</div></div>',
                        unsafe_allow_html=True,
                    )
                    continue
                if cell.game is None:
                    current = " current" if cell.is_current_day else ""
                    st.markdown(
                        f'<div class="fgn-day-shell{current}"><div class="fgn-day-date">{cell.calendar_date.day}</div><div class="fgn-day-rest">REST</div></div>',
                        unsafe_allow_html=True,
                    )
                    continue

                game = cell.game
                game_id = _text(getattr(game, "game_id", ""))
                logo = team_logo_url(game.opponent)
                location = "VS" if game.location == "HOME" else "AT"
                if game.result:
                    result = f"{game.result} {game.team_score}-{game.opponent_score}"
                    action = "Box score"
                else:
                    result = "UPCOMING"
                    action = "Game Day"
                st.markdown(
                    '<div class="fgn-day-shell">'
                    f'<div class="fgn-day-date">{cell.calendar_date.day}</div>'
                    f'<img src="{html.escape(str(logo), quote=True)}" alt="{html.escape(str(game.opponent))}">'
                    f'<div class="fgn-day-match">{location} {html.escape(str(game.opponent))}</div>'
                    f'<div class="fgn-day-result">{html.escape(result)}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                if st.button(
                    action,
                    key=f"fgn_native_month_{game_id}_{week_index}_{day_index}",
                    width="stretch",
                ):
                    _route_game_native_v2(state=state, team=team, game_id=game_id)

    st.caption("Click Box score for a completed game or Game Day for an upcoming matchup. Navigation stays inside the current Franchise session.")


def calendar_with_clickable_games_html_v1(month_calendar: Any) -> str:
    """Legacy passive HTML renderer retained for compatibility.

    New code should use render_clickable_month_calendar_v2 so navigation remains in
    the active Streamlit session.
    """
    def esc(value: Any) -> str:
        return html.escape(str(value))

    from franchise_command_center_v1 import team_logo_url
    weekdays = "".join(f'<div class="fm-weekday">{esc(label)}</div>' for label in month_calendar.weekday_labels)
    cells: list[str] = []
    for week in month_calendar.weeks:
        for cell in week:
            classes = ["fm-day"]
            if not cell.in_month:
                classes.append("outside")
            if cell.is_current_day:
                classes.append("current")
            if cell.is_past_day:
                classes.append("past")
            body = '<div class="fm-rest">REST</div>'
            if not cell.in_month:
                body = '<div class="fm-rest">OUTSIDE</div>'
            elif cell.game is not None:
                game = cell.game
                classes.append("home" if game.location == "HOME" else "away")
                logo = team_logo_url(game.opponent)
                location = "VS" if game.location == "HOME" else "AT"
                outcome = (
                    f'<div class="fm-result">{esc(game.result)} {game.team_score}-{game.opponent_score}</div>'
                    if game.result else '<div class="fm-upcoming">UPCOMING</div>'
                )
                body = '<div class="fm-game">' f'<img class="fm-game-logo" src="{esc(logo)}" alt="{esc(game.opponent)} logo">' f'<div class="fm-matchup">{location} {esc(game.opponent)}</div>' f'{outcome}</div>'
            cells.append(f'<div class="{" ".join(classes)}"><div class="fm-date">{cell.calendar_date.day}</div>{body}</div>')
    return '<div class="fm-calendar">' f'{weekdays}{"".join(cells)}' '</div>'
