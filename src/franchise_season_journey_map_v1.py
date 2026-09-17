from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import streamlit as st


FRANCHISE_SEASON_JOURNEY_MAP_VERSION = "franchise-season-journey-map-v1.0-2026-09-11"


@dataclass(frozen=True)
class JourneyMilestoneV1:
    key: str
    label: str
    eyebrow: str
    detail: str
    status: str
    icon: str


@dataclass(frozen=True)
class SeasonJourneyModelV1:
    season_label: str
    current_key: str
    current_label: str
    current_detail: str
    next_event_label: str
    next_event_detail: str
    progress_pct: float
    milestones: tuple[JourneyMilestoneV1, ...]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value) or "").strip()


def _status(value: Any) -> str:
    return _text(value).lower().replace(" ", "_")


def _team_games(state: Any, active_team: str) -> list[Any]:
    team = _text(active_team).upper()
    games = []
    for game in (getattr(state, "schedule", {}) or {}).values():
        home = _text(getattr(game, "home_team", "")).upper()
        away = _text(getattr(game, "away_team", "")).upper()
        if team and team in {home, away}:
            games.append(game)
    return sorted(
        games,
        key=lambda game: (
            int(getattr(game, "day_index", 0) or 0),
            _text(getattr(game, "game_id", "")),
        ),
    )


def _is_completed_game(state: Any, game: Any) -> bool:
    game_id = _text(getattr(game, "game_id", ""))
    if game_id and game_id in (getattr(state, "completed_games", {}) or {}):
        return True
    return _status(getattr(game, "status", "")) == "completed"


def _draft_phase(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return _text(payload.get("phase", "")).lower()


def _postseason_stage(postseason_state: Any) -> str:
    if postseason_state is None:
        return ""
    return _status(getattr(postseason_state, "stage", ""))


def _postseason_is_complete(postseason_state: Any) -> bool:
    return _postseason_stage(postseason_state) == "complete"


def _postseason_started(postseason_state: Any) -> bool:
    return _postseason_stage(postseason_state) not in {"", "not_started"}


def _date_text(date_resolver: Callable[[int], Any] | None, day_index: int) -> str:
    if date_resolver is None:
        return f"Day {day_index}"
    try:
        value = date_resolver(day_index)
    except Exception:
        return f"Day {day_index}"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%b %d, %Y")
        except Exception:
            pass
    return _text(value) or f"Day {day_index}"


def _conference_label(postseason_state: Any) -> str:
    stage = _postseason_stage(postseason_state)
    labels = {
        "play_in_opening": "Play-In Tournament",
        "play_in_final": "Play-In Tournament",
        "first_round": "First Round",
        "conference_semifinals": "Conference Semifinals",
        "conference_finals": "Conference Finals",
        "nba_finals": "NBA Finals",
        "complete": "Postseason Complete",
    }
    return labels.get(stage, stage.replace("_", " ").title() if stage else "Postseason")


def build_season_journey_model_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    date_resolver: Callable[[int], Any] | None = None,
) -> SeasonJourneyModelV1:
    """Build a read-only lifecycle model from the durable franchise state."""
    season_label = _text(getattr(getattr(state, "settings", None), "season_label", "")) or "Current season"
    phase = _status(getattr(state, "phase", ""))
    history = list(getattr(state, "season_history", ()) or ())
    team_games = _team_games(state, active_team)
    completed = [game for game in team_games if _is_completed_game(state, game)]
    scheduled = [game for game in team_games if not _is_completed_game(state, game)]
    game_total = len(team_games) or 82
    completed_count = len(completed)
    progress_pct = max(0.0, min(100.0, (completed_count / max(1, game_total)) * 100.0))
    regular_complete = bool(team_games) and completed_count >= len(team_games)

    next_game = scheduled[0] if scheduled else None
    next_game_detail = ""
    if next_game is not None:
        home = _text(getattr(next_game, "home_team", "")).upper()
        away = _text(getattr(next_game, "away_team", "")).upper()
        team = _text(active_team).upper()
        opponent = away if home == team else home
        opponent_name = team_name_resolver(opponent) if team_name_resolver else opponent
        venue = "vs" if home == team else "at"
        next_game_detail = (
            f"{venue} {opponent_name} · "
            f"{_date_text(date_resolver, int(getattr(next_game, 'day_index', 0) or 0))}"
        )

    postseason_complete = _postseason_is_complete(postseason_state)
    postseason_started = _postseason_started(postseason_state)
    dphase = _draft_phase(draft_state_payload)
    opening_offseason = (
        phase == "offseason"
        and not history
        and completed_count == 0
        and not dphase
        and not postseason_started
    )

    # The active franchise lifecycle is cyclic. Draft and postseason state take
    # priority over the broad LeaguePhase enum because those durable sub-states
    # carry the more specific progression truth.
    if dphase == "draft_in_progress":
        current_key = "draft"
    elif dphase in {"lottery_complete", "scouting"}:
        current_key = "scouting"
    elif dphase == "lottery_ready":
        current_key = "lottery"
    elif dphase == "draft_complete":
        current_key = "offseason"
    elif postseason_complete:
        current_key = "lottery"
    elif postseason_started or regular_complete:
        current_key = "playoffs"
    elif opening_offseason:
        current_key = "offseason"
    elif completed_count == 0:
        current_key = "opening"
    else:
        current_key = "regular"

    labels = {
        "opening": "Opening Night",
        "regular": "Regular Season",
        "playoffs": "Playoffs",
        "lottery": "Draft Lottery",
        "scouting": "Scouting",
        "draft": "Draft Night",
        "offseason": "Offseason Build",
    }
    order = tuple(labels)
    current_index = order.index(current_key)

    # For a normal season, milestones before the active point are complete.
    # Opening-offseason is the one wraparound state: it precedes Opening Night,
    # so no competitive-season milestone is falsely marked complete.
    def milestone_status(key: str) -> str:
        if opening_offseason and current_key == "offseason":
            return "current" if key == "offseason" else "upcoming"
        idx = order.index(key)
        if idx < current_index:
            return "complete"
        if idx == current_index:
            return "current"
        return "upcoming"

    regular_detail = f"{completed_count}/{game_total} team games complete · {progress_pct:.1f}%"
    if next_game_detail:
        regular_detail += f" · Next {next_game_detail}"

    playoff_detail = "Postseason bracket not started"
    if postseason_started:
        playoff_detail = _conference_label(postseason_state)
        completed_post = len(getattr(postseason_state, "completed_games", {}) or {})
        playoff_detail += f" · {completed_post} postseason games complete"
    elif regular_complete:
        playoff_detail = "Regular season complete · postseason is the next competitive gate"

    lottery_detail = "Unlocks after the postseason"
    if postseason_complete and not dphase:
        lottery_detail = "Championship complete · enter the NBA Draft Lottery"
    elif dphase:
        year = int((draft_state_payload or {}).get("draft_year", 0) or 0)
        suffix = f" · {year} class" if year else ""
        if dphase == "lottery_ready":
            lottery_detail = "Lottery is ready to run" + suffix
        elif dphase in {"lottery_complete", "scouting", "draft_in_progress", "draft_complete"}:
            lottery_detail = "Lottery complete" + suffix

    scouting_detail = "Reveal and scout the generated class after the lottery"
    if dphase in {"scouting", "draft_in_progress", "draft_complete"}:
        prospects = len(list((draft_state_payload or {}).get("prospects", []) or []))
        scouting_detail = f"Draft class revealed · {prospects} prospects on the board"

    draft_detail = "Two-round Draft Night follows scouting"
    if dphase == "draft_in_progress":
        order_rows = list((draft_state_payload or {}).get("draft_order", []) or [])
        pick_index = int((draft_state_payload or {}).get("current_pick_index", 0) or 0)
        draft_detail = f"Pick {min(pick_index + 1, max(1, len(order_rows)))}/{max(1, len(order_rows))} is on the clock"
    elif dphase == "draft_complete":
        draft_detail = "All 60 selections are complete"

    fa_payload = getattr(state, "free_agency_market_calendar_v1", None)
    offseason_day = 0
    active_markets = 0
    if isinstance(fa_payload, Mapping):
        offseason_day = int(fa_payload.get("offseason_day", 0) or 0)
        markets = fa_payload.get("active_markets", {}) or {}
        active_markets = len(markets) if isinstance(markets, Mapping) else 0
    offseason_detail = "Roster building, trades, rights and free agency lead into the next season"
    if phase == "offseason":
        parts = [f"Offseason day {offseason_day}" if offseason_day else "Offseason workspace active"]
        if active_markets:
            parts.append(f"{active_markets} live free-agent market{'s' if active_markets != 1 else ''}")
        if dphase == "draft_complete":
            parts.append("Draft complete · next-season transition unlocked")
        elif opening_offseason:
            parts.append("Opening-season setup")
        offseason_detail = " · ".join(parts)

    detail_by_key = {
        "opening": (
            "Season launch and first scheduled game"
            if completed_count == 0
            else f"Opening chapter complete · {completed_count} team game{'s' if completed_count != 1 else ''} logged"
        ),
        "regular": regular_detail,
        "playoffs": playoff_detail,
        "lottery": lottery_detail,
        "scouting": scouting_detail,
        "draft": draft_detail,
        "offseason": offseason_detail,
    }
    eyebrow_by_key = {
        "opening": "01 · TIP-OFF",
        "regular": "02 · 82-GAME ROAD",
        "playoffs": "03 · CHAMPIONSHIP RUN",
        "lottery": "04 · DRAFT ORDER",
        "scouting": "05 · FRONT OFFICE",
        "draft": "06 · DRAFT STAGE",
        "offseason": "07 · ROSTER BUILD",
    }
    icon_by_key = {
        "opening": "🏀",
        "regular": "📅",
        "playoffs": "🏆",
        "lottery": "🎱",
        "scouting": "🔎",
        "draft": "🎙️",
        "offseason": "🧩",
    }
    milestones = tuple(
        JourneyMilestoneV1(
            key=key,
            label=labels[key],
            eyebrow=eyebrow_by_key[key],
            detail=detail_by_key[key],
            status=milestone_status(key),
            icon=icon_by_key[key],
        )
        for key in order
    )

    current_detail = detail_by_key[current_key]
    next_key = order[(current_index + 1) % len(order)]
    next_event_label = labels[next_key]
    next_event_detail = detail_by_key[next_key]
    if current_key == "regular" and next_game_detail:
        next_event_label = "Next Game"
        next_event_detail = next_game_detail
    elif current_key == "playoffs" and postseason_started and not postseason_complete:
        next_event_label = _conference_label(postseason_state)
        next_event_detail = "Advance the postseason from League Hub or Game Day"
    elif current_key == "draft" and dphase == "draft_in_progress":
        next_event_label = "Next Draft Pick"
        next_event_detail = draft_detail
    elif current_key == "offseason" and opening_offseason:
        next_event_label = "Opening Night"
        next_event_detail = "Finalize the opening offseason and activate the regular-season clock"

    return SeasonJourneyModelV1(
        season_label=season_label,
        current_key=current_key,
        current_label=labels[current_key],
        current_detail=current_detail,
        next_event_label=next_event_label,
        next_event_detail=next_event_detail,
        progress_pct=progress_pct,
        milestones=milestones,
    )


def inject_franchise_season_journey_visuals_v1(*, primary: str = "#CE1141", secondary: str = "#0b1020") -> None:
    primary = html.escape(primary or "#CE1141")
    secondary = html.escape(secondary or "#0b1020")
    st.markdown(
        f"""
<style>
.fm-journey-shell {{
  --fj-primary:{primary}; --fj-secondary:{secondary};
  border:1px solid color-mix(in srgb, var(--fj-primary) 48%, #2a3341);
  border-radius:24px; padding:22px 22px 18px; margin:12px 0 22px;
  background:
    radial-gradient(circle at 88% 0%, color-mix(in srgb, var(--fj-primary) 22%, transparent), transparent 34%),
    linear-gradient(135deg,#07101d 0%,#0a0f18 60%,#17101a 100%);
  overflow:hidden;
}}
.fm-journey-top {{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:16px;}}
.fm-journey-kicker {{font-size:11px;font-weight:900;letter-spacing:.18em;color:#7dd3fc;text-transform:uppercase;}}
.fm-journey-title {{font-size:25px;font-weight:900;line-height:1.05;color:#f8fafc;margin-top:4px;}}
.fm-journey-copy {{color:#94a3b8;font-size:13px;margin-top:5px;max-width:760px;}}
.fm-journey-current {{text-align:right;min-width:210px;}}
.fm-journey-current b {{display:block;color:#fff;font-size:17px;}}
.fm-journey-current span {{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.12em;}}
.fm-journey-track {{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;position:relative;}}
.fm-journey-node {{position:relative;min-height:114px;border-radius:16px;padding:13px 12px;border:1px solid #263142;background:#0a1019;}}
.fm-journey-node.complete {{background:linear-gradient(180deg,rgba(22,163,74,.13),#0a1019);border-color:rgba(74,222,128,.32);}}
.fm-journey-node.current {{background:linear-gradient(180deg,color-mix(in srgb,var(--fj-primary) 24%,#10121a),#0a1019);border-color:var(--fj-primary);box-shadow:0 0 28px color-mix(in srgb,var(--fj-primary) 22%,transparent);}}
.fm-journey-node.upcoming {{opacity:.72;}}
.fm-journey-icon {{font-size:18px;margin-bottom:8px;}}
.fm-journey-status {{font-size:9px;letter-spacing:.14em;font-weight:900;text-transform:uppercase;color:#64748b;}}
.fm-journey-node.complete .fm-journey-status {{color:#4ade80;}}
.fm-journey-node.current .fm-journey-status {{color:#fda4af;}}
.fm-journey-label {{font-size:13px;color:#f8fafc;font-weight:850;margin-top:5px;line-height:1.15;}}
.fm-journey-detail {{font-size:10px;color:#7f8da2;margin-top:6px;line-height:1.35;}}
.fm-journey-footer {{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;}}
.fm-journey-callout {{border:1px solid #263142;border-radius:14px;background:#080e16;padding:12px 14px;}}
.fm-journey-callout small {{display:block;color:#64748b;font-size:9px;letter-spacing:.14em;font-weight:900;text-transform:uppercase;margin-bottom:3px;}}
.fm-journey-callout b {{display:block;color:#f8fafc;font-size:13px;}}
.fm-journey-callout span {{display:block;color:#94a3b8;font-size:11px;margin-top:3px;}}
.fm-journey-progress {{height:6px;background:#171e29;border-radius:999px;overflow:hidden;margin-top:12px;}}
.fm-journey-progress > span {{display:block;height:100%;background:linear-gradient(90deg,var(--fj-primary),#fb7185);border-radius:999px;}}
.fm-journey-compact {{padding:16px 17px 14px;margin-top:10px;}}
.fm-journey-compact .fm-journey-top {{margin-bottom:11px;align-items:center;}}
.fm-journey-compact .fm-journey-title {{font-size:18px;}}
.fm-journey-compact .fm-journey-copy {{display:none;}}
.fm-journey-compact .fm-journey-track {{gap:6px;}}
.fm-journey-compact .fm-journey-node {{min-height:72px;padding:9px 9px;}}
.fm-journey-compact .fm-journey-icon {{font-size:14px;margin-bottom:4px;}}
.fm-journey-compact .fm-journey-label {{font-size:10px;}}
.fm-journey-compact .fm-journey-detail {{display:none;}}
.fm-journey-compact .fm-journey-status {{font-size:8px;}}
.fm-journey-compact .fm-journey-footer {{display:none;}}
@media (max-width:1100px) {{.fm-journey-track{{grid-template-columns:repeat(4,minmax(0,1fr));}}}}
@media (max-width:760px) {{.fm-journey-track{{grid-template-columns:repeat(2,minmax(0,1fr));}} .fm-journey-top{{align-items:flex-start;flex-direction:column;}} .fm-journey-current{{text-align:left;}} .fm-journey-footer{{grid-template-columns:1fr;}}}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _journey_html(model: SeasonJourneyModelV1, *, compact: bool) -> str:
    nodes = []
    for milestone in model.milestones:
        status_label = {"complete": "Complete", "current": "Now", "upcoming": "Upcoming"}.get(milestone.status, milestone.status)
        nodes.append(
            f'<div class="fm-journey-node {html.escape(milestone.status)}">'
            f'<div class="fm-journey-icon">{html.escape(milestone.icon)}</div>'
            f'<div class="fm-journey-status">{html.escape(status_label)} · {html.escape(milestone.eyebrow)}</div>'
            f'<div class="fm-journey-label">{html.escape(milestone.label)}</div>'
            f'<div class="fm-journey-detail">{html.escape(milestone.detail)}</div>'
            '</div>'
        )
    compact_class = " fm-journey-compact" if compact else ""
    footer = (
        '' if compact else
        '<div class="fm-journey-footer">'
        '<div class="fm-journey-callout"><small>Current chapter</small>'
        f'<b>{html.escape(model.current_label)}</b><span>{html.escape(model.current_detail)}</span></div>'
        '<div class="fm-journey-callout"><small>Next checkpoint</small>'
        f'<b>{html.escape(model.next_event_label)}</b><span>{html.escape(model.next_event_detail)}</span></div>'
        '</div>'
        f'<div class="fm-journey-progress"><span style="width:{model.progress_pct:.2f}%"></span></div>'
    )
    return (
        f'<div class="fm-journey-shell{compact_class}">'
        '<div class="fm-journey-top"><div>'
        '<div class="fm-journey-kicker">Franchise season journey</div>'
        f'<div class="fm-journey-title">{html.escape(model.season_label)} Road Map</div>'
        '<div class="fm-journey-copy">One living path from Opening Night through the postseason, lottery, scouting, Draft Night and the offseason roster build.</div>'
        '</div><div class="fm-journey-current"><span>Current chapter</span>'
        f'<b>{html.escape(model.current_label)}</b></div></div>'
        f'<div class="fm-journey-track">{"".join(nodes)}</div>'
        f'{footer}</div>'
    )


def render_franchise_season_journey_preview_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    date_resolver: Callable[[int], Any] | None = None,
    set_section: Callable[[str], None] | None = None,
) -> None:
    model = build_season_journey_model_v1(
        state=state,
        active_team=active_team,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
        team_name_resolver=team_name_resolver,
        date_resolver=date_resolver,
    )
    st.markdown(_journey_html(model, compact=True), unsafe_allow_html=True)
    if set_section is not None:
        if st.button("Open full season journey", width="stretch", key="franchise_open_full_season_journey_v1"):
            set_section("League & Offseason")
            st.rerun()


def render_franchise_season_journey_map_v1(
    *,
    state: Any,
    active_team: str,
    postseason_state: Any = None,
    draft_state_payload: Mapping[str, Any] | None = None,
    team_name_resolver: Callable[[str], str] | None = None,
    date_resolver: Callable[[int], Any] | None = None,
    set_section: Callable[[str], None] | None = None,
) -> None:
    model = build_season_journey_model_v1(
        state=state,
        active_team=active_team,
        postseason_state=postseason_state,
        draft_state_payload=draft_state_payload,
        team_name_resolver=team_name_resolver,
        date_resolver=date_resolver,
    )
    st.markdown(_journey_html(model, compact=False), unsafe_allow_html=True)
    if set_section is None:
        return
    action_section = {
        "opening": "Command Center",
        "regular": "Calendar",
        "playoffs": "League & Offseason",
        "lottery": "Draft Room",
        "scouting": "Draft Room",
        "draft": "Draft Room",
        "offseason": "Free Agency",
    }.get(model.current_key, "Command Center")
    cols = st.columns([1.4, 3.6])
    with cols[0]:
        if st.button(
            f"Open {model.current_label}",
            type="primary",
            width="stretch",
            key="franchise_season_journey_primary_action_v1",
        ):
            set_section(action_section)
            st.rerun()
    with cols[1]:
        st.caption(
            "This map is read-only. Every completed/current/upcoming state is derived from the durable season, postseason and Draft lifecycle already stored in this franchise save."
        )
