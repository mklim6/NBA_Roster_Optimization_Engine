from __future__ import annotations

import html
from typing import Any, Callable


FRANCHISE_VISUAL_OVERHAUL_V4_VERSION = "franchise-visual-overhaul-v4.0-gameflow-2026-09-11"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inject_franchise_visual_overhaul_v4(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_VISUAL_OVERHAUL_V4 */
:root {{
  --fx4-primary:{primary};
  --fx4-secondary:{secondary};
}}

/* Keep long franchise names clear of the player-art stage. */
.fxv2-hero-copy {{
  width:53% !important;
}}
.fxv2-team-name {{
  max-width:520px;
  font-size:clamp(2.1rem,3.25vw,3.85rem) !important;
  line-height:.94 !important;
  text-wrap:balance;
}}
.fxv2-player-stage {{
  width:47% !important;
}}
.fxv2-hero-player {{
  width:268px !important;
  height:334px !important;
}}
.fxv2-hero-player-1 {{ right:132px !important; }}
.fxv2-hero-player-2 {{ right:-12px !important; transform:scale(.86) !important; }}
.fxv2-hero-player-3 {{ right:252px !important; transform:scale(.72) !important; opacity:.76 !important; }}

/* Command Center metrics are custom so text never truncates into ellipses. */
.fx4-metrics {{
  display:grid;
  grid-template-columns:repeat(6,minmax(0,1fr));
  gap:10px;
  margin:.35rem 0 1rem;
}}
.fx4-metric {{
  min-width:0;
  min-height:112px;
  padding:15px 16px 14px;
  border:1px solid rgba(255,255,255,.08);
  border-top:2px solid color-mix(in srgb,var(--fx4-primary) 72%,transparent);
  border-radius:18px;
  background:
    radial-gradient(circle at 98% 0%,color-mix(in srgb,var(--fx4-primary) 10%,transparent),transparent 44%),
    linear-gradient(145deg,rgba(16,24,38,.94),rgba(8,13,22,.94));
  box-shadow:0 13px 30px rgba(0,0,0,.16);
}}
.fx4-metric-label {{
  color:#edf4ff;
  font-size:.67rem;
  font-weight:820;
  line-height:1.2;
}}
.fx4-metric-value {{
  margin-top:12px;
  color:#fff;
  font-size:1.62rem;
  font-weight:1000;
  line-height:1.02;
  letter-spacing:-.045em;
  white-space:normal;
  overflow:visible;
  text-overflow:clip;
  word-break:normal;
}}
.fx4-metric-value.compact {{
  font-size:1.22rem;
  line-height:1.08;
  letter-spacing:-.03em;
}}
.fx4-metric-sub {{
  margin-top:6px;
  color:#72849b;
  font-size:.49rem;
  font-weight:850;
  letter-spacing:.08em;
  text-transform:uppercase;
}}

/* NBA-2K-style season rail shown in the Command Center and Game Day. */
.fx4-rail-shell {{
  margin:.55rem 0 1.05rem;
  padding:13px 13px 12px;
  border:1px solid rgba(255,255,255,.075);
  border-radius:20px;
  background:
    radial-gradient(circle at 92% 8%,color-mix(in srgb,var(--fx4-primary) 13%,transparent),transparent 32%),
    linear-gradient(145deg,rgba(10,17,29,.95),rgba(6,11,19,.96));
  box-shadow:0 16px 40px rgba(0,0,0,.19);
}}
.fx4-rail-head {{
  display:flex;
  justify-content:space-between;
  align-items:end;
  gap:10px;
  padding:0 3px 10px;
}}
.fx4-rail-kicker {{
  color:#7dd3fc;
  font-size:.52rem;
  font-weight:1000;
  letter-spacing:.15em;
  text-transform:uppercase;
}}
.fx4-rail-title {{
  margin-top:2px;
  color:#fff;
  font-size:.82rem;
  font-weight:950;
}}
.fx4-rail-count {{
  color:#8294aa;
  font-size:.54rem;
  font-weight:850;
  white-space:nowrap;
}}
.fx4-rail {{
  display:grid;
  grid-template-columns:repeat(7,minmax(112px,1fr));
  gap:8px;
  overflow-x:auto;
  scrollbar-width:thin;
  padding-bottom:2px;
}}
.fx4-game {{
  position:relative;
  min-width:112px;
  min-height:122px;
  padding:10px 9px 9px;
  border:1px solid rgba(255,255,255,.075);
  border-radius:14px;
  background:rgba(255,255,255,.025);
  text-align:center;
}}
.fx4-game.completed {{ opacity:.76; }}
.fx4-game.win {{ border-color:rgba(34,197,94,.28); }}
.fx4-game.loss {{ border-color:rgba(239,68,68,.25); }}
.fx4-game.next {{
  border-color:color-mix(in srgb,var(--fx4-primary) 70%,#fff 8%);
  background:
    radial-gradient(circle at 50% 0%,color-mix(in srgb,var(--fx4-primary) 22%,transparent),transparent 50%),
    rgba(255,255,255,.035);
  box-shadow:0 0 0 1px color-mix(in srgb,var(--fx4-primary) 18%,transparent),0 10px 28px color-mix(in srgb,var(--fx4-primary) 12%,transparent);
}}
.fx4-game.selected::after {{
  content:"SELECTED";
  position:absolute;
  right:7px;
  top:6px;
  color:#fff;
  font-size:.39rem;
  font-weight:1000;
  letter-spacing:.09em;
}}
.fx4-game-date {{
  color:#dce8f8;
  font-size:.53rem;
  font-weight:900;
  letter-spacing:.035em;
}}
.fx4-game img {{
  width:46px;
  height:46px;
  object-fit:contain;
  margin:7px auto 4px;
  filter:drop-shadow(0 7px 10px rgba(0,0,0,.35));
}}
.fx4-game-opponent {{
  color:#fff;
  font-size:.64rem;
  font-weight:950;
  line-height:1.05;
}}
.fx4-game-result {{
  margin-top:5px;
  color:#83a0bf;
  font-size:.48rem;
  font-weight:900;
  letter-spacing:.075em;
  text-transform:uppercase;
}}
.fx4-game.win .fx4-game-result {{ color:#86efac; }}
.fx4-game.loss .fx4-game-result {{ color:#fca5a5; }}
.fx4-game.next .fx4-game-result {{ color:#7dd3fc; }}

/* Slightly tighter dense metric values globally, preserving large numeric impact. */
[data-testid="stMetricValue"] {{
  line-height:1.02 !important;
}}

@media(max-width:1180px) {{
  .fx4-metrics {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
  .fxv2-hero-player-3 {{ display:none !important; }}
  .fxv2-team-name {{ max-width:440px; }}
}}
@media(max-width:760px) {{
  .fx4-metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .fx4-rail {{ grid-template-columns:repeat(7,118px); }}
  .fxv2-team-name {{ font-size:2.15rem !important; max-width:none; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_command_center_metrics_v4(snapshot: Any) -> None:
    import streamlit as st

    recent_form = _text(getattr(snapshot, "recent_form", "")) or "No games yet"
    metrics = (
        ("Record", f"{int(_number(getattr(snapshot, 'wins', 0)))}-{int(_number(getattr(snapshot, 'losses', 0)))}", "Season record", False),
        ("Conference", f"#{int(_number(getattr(snapshot, 'conference_rank', 0)))}" if _number(getattr(snapshot, "conference_rank", 0)) else "—", "Conference rank", False),
        ("League", f"#{int(_number(getattr(snapshot, 'league_rank', 0)))}" if _number(getattr(snapshot, "league_rank", 0)) else "—", "NBA rank", False),
        ("Point diff", f"{int(_number(getattr(snapshot, 'point_differential', 0))):+d}", "Net points", False),
        ("Recent form", recent_form, "Last five games", len(recent_form) > 7),
        ("Season", f"{_number(getattr(snapshot, 'season_completion_percentage', 0)):.1f}%", "Schedule complete", False),
    )
    cards = []
    for label, value, sub, compact in metrics:
        value_cls = "fx4-metric-value compact" if compact else "fx4-metric-value"
        cards.append(
            '<div class="fx4-metric">'
            f'<div class="fx4-metric-label">{html.escape(label)}</div>'
            f'<div class="{value_cls}">{html.escape(value)}</div>'
            f'<div class="fx4-metric-sub">{html.escape(sub)}</div>'
            '</div>'
        )
    st.markdown('<div class="fx4-metrics">' + ''.join(cards) + '</div>', unsafe_allow_html=True)


def render_schedule_ribbon_v4(
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
            if _text(getattr(getattr(game, "status", None), "value", getattr(game, "status", ""))).lower() == "scheduled":
                anchor = idx
                break
    if anchor is None:
        anchor = max(0, len(games) - 1)

    start = max(0, min(anchor - 2, len(games) - 7))
    window = games[start:start + 7]
    completed_count = sum(
        1
        for game in games
        if _text(getattr(getattr(game, "status", None), "value", getattr(game, "status", ""))).lower() == "completed"
    )

    next_scheduled_id = ""
    for candidate in games:
        if (
            _text(getattr(getattr(candidate, "status", None), "value", getattr(candidate, "status", ""))).lower() == "scheduled"
            and int(getattr(candidate, "day_index", 0) or 0) >= int(getattr(state, "current_day_index", 0) or 0)
        ):
            next_scheduled_id = _text(getattr(candidate, "game_id", ""))
            break

    cells: list[str] = []
    for game in window:
        game_id = _text(getattr(game, "game_id", ""))
        card = team_game_card(state, team, game)
        is_selected = game_id == selected_game_id
        is_next = bool(next_scheduled_id and game_id == next_scheduled_id)
        classes = ["fx4-game"]
        if card.status == "completed":
            classes.append("completed")
            if card.result == "W":
                classes.append("win")
            elif card.result == "L":
                classes.append("loss")
        if is_next:
            classes.append("next")
        if is_selected:
            classes.append("selected")
            if "next" not in classes:
                classes.append("next")

        location = "VS" if card.location == "HOME" else "AT"
        if card.status == "completed":
            result_copy = f"{card.result} {card.team_score}-{card.opponent_score}"
        elif is_selected:
            result_copy = "Selected game"
        elif is_next:
            result_copy = "Next game"
        else:
            result_copy = "Upcoming"

        logo = _text(team_logo_resolver(card.opponent))
        cells.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="fx4-game-date">{html.escape(card.calendar_date.strftime("%b %d"))}</div>'
            f'<img src="{html.escape(logo, quote=True)}" alt="{html.escape(card.opponent)}">'
            f'<div class="fx4-game-opponent">{location} {html.escape(card.opponent)}</div>'
            f'<div class="fx4-game-result">{html.escape(result_copy)}</div>'
            '</div>'
        )

    st.markdown(
        '<div class="fx4-rail-shell">'
        '<div class="fx4-rail-head">'
        f'<div><div class="fx4-rail-kicker">FRANCHISE CALENDAR</div><div class="fx4-rail-title">{html.escape(title)}</div></div>'
        f'<div class="fx4-rail-count">{completed_count} of {len(games)} games complete</div>'
        '</div>'
        '<div class="fx4-rail">' + ''.join(cells) + '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
