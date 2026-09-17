from __future__ import annotations

import html
from typing import Any, Callable


# Preserve the V1 marker for backward validator compatibility.
FRANCHISE_GAME_FLOW_V1_VERSION = "franchise-game-flow-v1.0-2026-09-11"
FRANCHISE_GAME_FLOW_V2_VERSION = "franchise-game-flow-v2.0-season-sync-2026-09-11"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).lower()


def _featured_player(state: Any, team: str) -> dict[str, Any] | None:
    team = _text(team).upper()
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    if team_state is None:
        return None
    rotation = getattr(team_state, "rotation", None)
    ids = tuple(getattr(rotation, "starter_ids", ()) or ())
    if not ids:
        ids = tuple(getattr(rotation, "rotation_player_ids", ()) or ())[:5]
    players = getattr(state, "players", {}) or {}
    candidates = [(player_id, players[player_id]) for player_id in ids if player_id in players]
    if not candidates:
        ids = tuple(getattr(team_state, "roster_player_ids", ()) or ())
        candidates = [(player_id, players[player_id]) for player_id in ids if player_id in players]
    if not candidates:
        return None
    player_id, player = max(
        candidates,
        key=lambda item: (
            _number(getattr(item[1], "overall_rating", 0)),
            _number(getattr(item[1], "potential_rating", 0)),
            _text(getattr(item[1], "player_name", item[0])),
        ),
    )
    totals = (getattr(state, "player_season_totals", {}) or {}).get(player_id)
    games = int(getattr(totals, "games_played", 0) or 0)
    points = _number(getattr(totals, "points", 0))
    assists = _number(getattr(totals, "assists", 0))
    rebounds = _number(getattr(totals, "rebounds", 0))
    return {
        "player_id": _text(player_id),
        "name": _text(getattr(player, "player_name", player_id)) or "Featured player",
        "position": _text(getattr(player, "position", "")) or "—",
        "overall": int(round(_number(getattr(player, "overall_rating", 0)))),
        "games": games,
        "ppg": points / games if games else 0.0,
        "apg": assists / games if games else 0.0,
        "rpg": rebounds / games if games else 0.0,
    }


def _player_focus_html(
    *,
    state: Any,
    team: str,
    opponent: str,
    headshot_resolver: Callable[..., str],
) -> str:
    cards: list[str] = []
    for code, side in ((team, "YOUR STAR"), (opponent, "OPPONENT FOCUS")):
        row = _featured_player(state, code)
        if row is None:
            continue
        image = _text(headshot_resolver(row["player_id"], code, row["name"]))
        stat = (
            f"{row['ppg']:.1f} PPG · {row['apg']:.1f} APG"
            if row["games"]
            else "Season debut"
        )
        cards.append(
            '<div class="fgf-focus-player">'
            f'<img src="{html.escape(image, quote=True)}" alt="{html.escape(row["name"], quote=True)}">'
            '<div class="fgf-focus-copy">'
            f'<div class="fgf-focus-tag">{html.escape(side)}</div>'
            f'<div class="fgf-focus-name">{html.escape(row["name"])}</div>'
            f'<div class="fgf-focus-meta">{html.escape(row["position"])} · {row["overall"]} OVR</div>'
            f'<div class="fgf-focus-stat">{html.escape(stat)}</div>'
            '</div></div>'
        )
    if not cards:
        return '<div class="fgf-focus-empty">Key-player matchup will appear once rotations are available.</div>'
    return "".join(cards)


def _earliest_scheduled_day(state: Any) -> int | None:
    days = [
        int(getattr(game, "day_index", 0) or 0)
        for game in (getattr(state, "schedule", {}) or {}).values()
        if _enum(getattr(game, "status", "")) == "scheduled"
    ]
    return min(days) if days else None


def inject_franchise_game_flow_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_GAME_FLOW_V2 */
:root {{--fgf-primary:{primary};--fgf-secondary:{secondary};}}
.fgf-shell{{margin:.35rem 0 1.05rem;border:1px solid color-mix(in srgb,var(--fgf-primary) 26%,rgba(255,255,255,.08));border-radius:24px;overflow:hidden;background:radial-gradient(circle at 87% 8%,color-mix(in srgb,var(--fgf-primary) 18%,transparent),transparent 34%),linear-gradient(145deg,rgba(11,18,30,.985),rgba(6,10,18,.99));box-shadow:0 22px 60px rgba(0,0,0,.24)}}
.fgf-top{{display:grid;grid-template-columns:minmax(0,1.12fr) minmax(330px,.88fr);min-height:232px}}
.fgf-matchup{{position:relative;padding:24px 28px 20px;border-right:1px solid rgba(255,255,255,.07)}}
.fgf-kicker,.fgf-side-label,.fgf-focus-tag{{color:#7dd3fc;font-size:.49rem;font-weight:1000;letter-spacing:.14em;text-transform:uppercase}}
.fgf-date{{margin-top:5px;color:#8193ab;font-size:.61rem;font-weight:800}}
.fgf-teams{{display:flex;align-items:center;gap:15px;margin-top:18px}}
.fgf-team{{display:flex;align-items:center;gap:11px;min-width:0}}
.fgf-team img{{width:68px;height:68px;object-fit:contain;filter:drop-shadow(0 12px 18px rgba(0,0,0,.34))}}
.fgf-team-copy{{min-width:0}}.fgf-abbr{{color:#fff;font-size:1.5rem;font-weight:1000;line-height:1;letter-spacing:-.04em}}
.fgf-name{{margin-top:4px;color:#8394aa;font-size:.55rem;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:175px}}
.fgf-vs{{color:#516179;font-size:.62rem;font-weight:1000;letter-spacing:.09em;text-transform:uppercase}}
.fgf-detail-row{{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}}.fgf-chip{{border:1px solid rgba(255,255,255,.075);border-radius:999px;padding:6px 9px;color:#a9b8ca;background:rgba(255,255,255,.025);font-size:.49rem;font-weight:900;letter-spacing:.035em}}
.fgf-focus{{padding:22px 22px 18px;display:flex;flex-direction:column;justify-content:center}}
.fgf-focus-title{{margin-top:6px;color:#fff;font-size:.95rem;font-weight:1000}}
.fgf-focus-player{{display:grid;grid-template-columns:64px 1fr;gap:11px;align-items:center;margin-top:10px;padding:8px 10px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:rgba(255,255,255,.025)}}
.fgf-focus-player img{{width:62px;height:68px;object-fit:cover;object-position:top;border-radius:11px;background:rgba(255,255,255,.04)}}
.fgf-focus-name{{margin-top:2px;color:#fff;font-size:.67rem;font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fgf-focus-meta{{margin-top:2px;color:#8496ac;font-size:.48rem;font-weight:820}}.fgf-focus-stat{{margin-top:3px;color:#c7d5e5;font-size:.49rem;font-weight:900}}
.fgf-focus-empty{{margin-top:12px;color:#788ba3;font-size:.55rem;line-height:1.45}}
.fgf-footer{{display:grid;grid-template-columns:minmax(0,1fr) minmax(250px,.55fr);gap:12px;padding:13px 20px 16px;border-top:1px solid rgba(255,255,255,.065);background:rgba(2,7,13,.36)}}
.fgf-progress-meta{{display:flex;justify-content:space-between;color:#8294aa;font-size:.47rem;font-weight:900;margin-bottom:7px}}.fgf-track{{height:7px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.075)}}.fgf-fill{{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--fgf-primary),color-mix(in srgb,var(--fgf-secondary) 78%,#fff 12%));box-shadow:0 0 16px color-mix(in srgb,var(--fgf-primary) 40%,transparent)}}
.fgf-policy{{color:#8294aa;font-size:.49rem;line-height:1.45;font-weight:800}}.fgf-policy strong{{display:block;color:#dce7f4;font-size:.55rem;margin-bottom:2px}}
.fgf-status{{margin-top:8px;border-radius:12px;border:1px solid rgba(34,197,94,.18);background:rgba(34,197,94,.055);padding:9px 10px;color:#a7f3d0;font-size:.5rem;line-height:1.4;font-weight:820}}.fgf-status.blocked{{border-color:rgba(245,158,11,.32);background:rgba(245,158,11,.08);color:#fde68a}}
.fgf-actions-label{{margin:.15rem 0 -.05rem;color:#7f91a8;font-size:.50rem;font-weight:950;letter-spacing:.13em;text-transform:uppercase}}
div[data-testid="stHorizontalBlock"]:has(button[kind="primary"]) button{{min-height:42px}}
@media(max-width:980px){{.fgf-top{{grid-template-columns:1fr}}.fgf-matchup{{border-right:0;border-bottom:1px solid rgba(255,255,255,.07)}}.fgf-footer{{grid-template-columns:1fr}}}}
@media(max-width:680px){{.fgf-matchup,.fgf-focus{{padding:18px}}.fgf-team img{{width:52px;height:52px}}.fgf-abbr{{font-size:1.2rem}}.fgf-name{{max-width:110px}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_franchise_game_flow_v1(
    *,
    state: Any,
    snapshot: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    player_headshot_resolver: Callable[..., str],
    policy_label: str,
    blocking_count: int,
    trade_sync_required: bool,
    full_schedule_active: bool,
) -> str | None:
    """Render the in-season control console and return a requested action."""
    import streamlit as st

    team = _text(active_team).upper()
    opponent = _text(getattr(snapshot, "next_opponent", "")).upper()
    next_game_id = _text(getattr(snapshot, "next_game_id", ""))
    next_date = _text(getattr(snapshot, "next_game_date", "")) or "Schedule pending"
    location = _text(getattr(snapshot, "next_location", "")).upper()
    pct = max(0.0, min(100.0, _number(getattr(snapshot, "season_completion_percentage", 0.0))))
    wins = int(_number(getattr(snapshot, "wins", 0)))
    losses = int(_number(getattr(snapshot, "losses", 0)))
    opp_wins = int(_number(getattr(snapshot, "opponent_wins", 0)))
    opp_losses = int(_number(getattr(snapshot, "opponent_losses", 0)))
    rest_days = getattr(snapshot, "rest_days", None)
    back_to_back = bool(getattr(snapshot, "back_to_back", False))

    if opponent:
        team_logo = _text(team_logo_resolver(team))
        opp_logo = _text(team_logo_resolver(opponent))
        team_name = _text(team_name_resolver(team)) or team
        opp_name = _text(team_name_resolver(opponent)) or opponent
        if location == "HOME":
            left_abbr, left_name, left_logo = opponent, opp_name, opp_logo
            right_abbr, right_name, right_logo = team, team_name, team_logo
        else:
            left_abbr, left_name, left_logo = team, team_name, team_logo
            right_abbr, right_name, right_logo = opponent, opp_name, opp_logo
        rest_copy = "Back-to-back" if back_to_back else (
            f"{int(rest_days)} day rest" if rest_days is not None else "Rest TBD"
        )
        chips = (
            f'<span class="fgf-chip">{html.escape(team)} {wins}-{losses}</span>'
            f'<span class="fgf-chip">{html.escape(opponent)} {opp_wins}-{opp_losses}</span>'
            f'<span class="fgf-chip">{html.escape(rest_copy)}</span>'
        )
        matchup_html = (
            '<div class="fgf-kicker">NEXT FRANCHISE EVENT</div>'
            f'<div class="fgf-date">{html.escape(next_date)}</div>'
            '<div class="fgf-teams">'
            '<div class="fgf-team">'
            f'<img src="{html.escape(left_logo, quote=True)}" alt="{html.escape(left_abbr)}">'
            '<div class="fgf-team-copy">'
            f'<div class="fgf-abbr">{html.escape(left_abbr)}</div><div class="fgf-name">{html.escape(left_name)}</div>'
            '</div></div><div class="fgf-vs">AT</div><div class="fgf-team">'
            f'<img src="{html.escape(right_logo, quote=True)}" alt="{html.escape(right_abbr)}">'
            '<div class="fgf-team-copy">'
            f'<div class="fgf-abbr">{html.escape(right_abbr)}</div><div class="fgf-name">{html.escape(right_name)}</div>'
            '</div></div></div>'
            f'<div class="fgf-detail-row">{chips}</div>'
        )
        focus_html = _player_focus_html(
            state=state,
            team=team,
            opponent=opponent,
            headshot_resolver=player_headshot_resolver,
        )
    else:
        matchup_html = (
            '<div class="fgf-kicker">SEASON CONTROL</div><div class="fgf-date">No controlled-team matchup is queued.</div>'
            '<div style="margin-top:22px;color:#fff;font-size:1.35rem;font-weight:1000;">Open the calendar to plan your next move.</div>'
        )
        focus_html = '<div class="fgf-focus-empty">Matchup focus will appear when the next controlled game is known.</div>'

    blocked = int(blocking_count or 0) > 0
    status_class = "fgf-status blocked" if blocked else "fgf-status"
    if blocked:
        status_copy = f"{blocking_count} decision(s) are blocking simulation. Resolve them before advancing the league."
    elif trade_sync_required:
        status_copy = "Trade state synchronization is required before league advancement."
    elif full_schedule_active:
        status_copy = "Season clock is live. Game Day and simulation controls are synced to the next unplayed league date."
    else:
        status_copy = "The regular-season schedule is not active yet."

    st.markdown(
        '<div class="fgf-shell"><div class="fgf-top">'
        f'<div class="fgf-matchup">{matchup_html}</div>'
        '<div class="fgf-focus"><div class="fgf-focus-tag">MATCHUP FOCUS</div><div class="fgf-focus-title">Players to watch</div>'
        f'{focus_html}</div></div>'
        '<div class="fgf-footer"><div>'
        '<div class="fgf-progress-meta"><span>SEASON PROGRESS</span>'
        f'<span>{pct:.1f}%</span></div><div class="fgf-track"><div class="fgf-fill" style="width:{pct:.1f}%"></div></div>'
        f'<div class="{status_class}">{html.escape(status_copy)}</div>'
        '</div><div class="fgf-policy"><strong>Simulation policy</strong>'
        f'{html.escape(policy_label)}<br>Simulation pauses whenever your current policy requires your attention.</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fgf-actions-label">FRANCHISE CONTROLS</div>', unsafe_allow_html=True)
    disabled_advance = not full_schedule_active or trade_sync_required or blocked

    earliest_day = _earliest_scheduled_day(state)
    next_game_day = getattr(snapshot, "next_game_day", None)
    controlled_game_is_next_event = bool(
        next_game_id
        and earliest_day is not None
        and next_game_day is not None
        and int(next_game_day) == int(earliest_day)
    )

    if blocked:
        columns = st.columns([1.55, 1, 1, 1, 1])
        if columns[0].button(
            f"Resolve {blocking_count} decision{'s' if blocking_count != 1 else ''}",
            type="primary", width="stretch", key="franchise_flow_resolve_decisions_v1",
        ):
            return "inbox"
    else:
        columns = st.columns([1.55, 1, 1, 1, 1])
        if columns[0].button(
            "Open Game Day" if next_game_id else "Open schedule",
            type="primary", width="stretch",
            disabled=(not bool(next_game_id) and not full_schedule_active),
            key="franchise_flow_open_next_v1",
        ):
            return "open_game" if next_game_id else "schedule"

    if columns[1].button(
        "Game pending" if controlled_game_is_next_event else "Sim next date",
        width="stretch",
        disabled=(disabled_advance or controlled_game_is_next_event),
        key="franchise_flow_next_day_v1",
    ):
        return "next_day"
    if columns[2].button(
        "Sim 7 days", width="stretch",
        disabled=(disabled_advance or controlled_game_is_next_event),
        key="franchise_flow_next_week_v1",
    ):
        return "next_week"
    if columns[3].button(
        "Sim season", width="stretch",
        disabled=(disabled_advance or controlled_game_is_next_event),
        key="franchise_flow_remainder_v1",
    ):
        return "remainder"
    if columns[4].button("Full schedule", width="stretch", key="franchise_flow_schedule_v1"):
        return "schedule"

    if controlled_game_is_next_event and not blocked:
        st.caption(
            "Your controlled-team game is the next league event, so calendar simulation is paused by design. "
            "Open Game Day to prepare it. After the matchup is resolved, the sim controls advance normally."
        )
    return None
