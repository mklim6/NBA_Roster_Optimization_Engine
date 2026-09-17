from __future__ import annotations

import html
import math
import re
from typing import Any, Callable, Iterable


FRANCHISE_VISUAL_OVERHAUL_V3_VERSION = "franchise-visual-overhaul-v3.0-current-aware-2026-09-11"

TEAM_IDS = {
    "ATL": 1610612737, "BOS": 1610612738, "CLE": 1610612739, "NOP": 1610612740,
    "CHI": 1610612741, "DAL": 1610612742, "DEN": 1610612743, "GSW": 1610612744,
    "HOU": 1610612745, "LAC": 1610612746, "LAL": 1610612747, "MIA": 1610612748,
    "MIL": 1610612749, "MIN": 1610612750, "BKN": 1610612751, "NYK": 1610612752,
    "ORL": 1610612753, "IND": 1610612754, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "OKC": 1610612760,
    "TOR": 1610612761, "UTA": 1610612762, "MEM": 1610612763, "WAS": 1610612764,
    "DET": 1610612765, "CHA": 1610612766,
}

HOME_FEATURE_TEAMS = ("CHI", "LAL", "BOS", "NYK", "GSW", "OKC")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _logo(team: str) -> str:
    team_id = TEAM_IDS.get(_text(team).upper())
    if not team_id:
        return ""
    return f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"


def _safe_img(url: str, alt: str, cls: str) -> str:
    if not _text(url):
        return f'<div class="{cls} fallback">🏀</div>'
    return (
        f'<img class="{cls}" src="{html.escape(url, quote=True)}" '
        f'alt="{html.escape(alt, quote=True)}">'
    )


def inject_franchise_visual_overhaul_v3(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_VISUAL_OVERHAUL_V3 */
:root {{
  --fx3-primary:{primary};
  --fx3-secondary:{secondary};
  --fx3-ink:#f8fbff;
  --fx3-muted:#90a0b7;
  --fx3-panel:rgba(10,16,27,.86);
  --fx3-border:rgba(255,255,255,.085);
}}
.stApp {{
  background:
    radial-gradient(circle at 87% 5%, color-mix(in srgb, var(--fx3-primary) 18%, transparent), transparent 25rem),
    radial-gradient(circle at 18% 80%, color-mix(in srgb, var(--fx3-secondary) 8%, transparent), transparent 33rem),
    linear-gradient(180deg,#050912 0%,#080d16 52%,#050911 100%) !important;
}}
.stApp::before {{
  content:"";
  position:fixed;
  inset:0;
  z-index:0;
  opacity:.075;
  pointer-events:none;
  background-image:
    linear-gradient(rgba(255,255,255,.08) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.08) 1px,transparent 1px);
  background-size:58px 58px;
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.65),transparent 78%);
}}
.main .block-container {{ position:relative; z-index:1; max-width:1420px; }}
[data-testid="stSidebar"] {{
  background:
    radial-gradient(circle at 55% 9%, color-mix(in srgb,var(--fx3-primary) 20%,transparent), transparent 16rem),
    linear-gradient(180deg,#0a101b,#070c14 64%,#080c14) !important;
}}
[data-testid="stSidebar"]::after {{
  content:"";
  position:absolute;
  top:0;right:0;bottom:0;width:1px;
  background:linear-gradient(transparent,color-mix(in srgb,var(--fx3-primary) 45%,transparent),transparent);
}}
.fxv2-team-hero {{
  border-radius:30px !important;
  border:1px solid color-mix(in srgb,var(--team-primary) 42%,rgba(255,255,255,.1)) !important;
  box-shadow:0 30px 78px rgba(0,0,0,.38),0 0 70px color-mix(in srgb,var(--team-primary) 12%,transparent) !important;
  min-height:330px !important;
  background:
    radial-gradient(circle at 88% 32%, color-mix(in srgb,var(--team-primary) 30%,transparent), transparent 34%),
    radial-gradient(circle at 5% 92%, color-mix(in srgb,var(--team-secondary) 12%,transparent), transparent 26%),
    linear-gradient(128deg,#090e18 5%,#101827 58%,#080d16) !important;
}}
.fxv2-team-hero::after {{
  content:"";
  position:absolute;inset:auto 0 0;height:5px;
  background:linear-gradient(90deg,var(--team-primary),var(--team-secondary),transparent 88%);
}}
.fxv2-logo {{ filter:drop-shadow(0 16px 28px rgba(0,0,0,.42)) !important; }}
.fxv2-team-name {{ text-shadow:0 5px 26px rgba(0,0,0,.38); }}
.fxv2-hero-player img {{ filter:drop-shadow(0 24px 30px rgba(0,0,0,.45)); }}
.fm2-hud,.fm2-masthead,.fm2-wizard,.frx-brief,.frx-goal,.frx-cabinet,.frx-stories {{
  backdrop-filter:blur(14px);
}}
.fm2-hud {{
  border-color:color-mix(in srgb,var(--fx3-primary) 28%,rgba(255,255,255,.09)) !important;
  box-shadow:0 18px 46px rgba(0,0,0,.20) !important;
}}
.fm2-track-fill {{
  box-shadow:0 0 22px color-mix(in srgb,var(--fx3-primary) 42%,transparent);
}}
.fm2-masthead {{
  border-radius:22px !important;
  box-shadow:0 18px 44px rgba(0,0,0,.18),0 0 34px color-mix(in srgb,var(--route-color) 8%,transparent) !important;
}}
.frx-brief {{
  border-radius:22px !important;
  border-color:color-mix(in srgb,var(--fx3-primary) 23%,rgba(255,255,255,.08)) !important;
  background:
    radial-gradient(circle at 92% 20%,color-mix(in srgb,var(--fx3-primary) 18%,transparent),transparent 34%),
    linear-gradient(135deg,rgba(12,19,31,.96),rgba(8,13,22,.92)) !important;
}}
.frx-goal {{
  transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease;
}}
.frx-goal:hover {{
  transform:translateY(-3px);
  border-color:color-mix(in srgb,var(--fx3-primary) 35%,rgba(255,255,255,.1)) !important;
  box-shadow:0 15px 35px rgba(0,0,0,.22);
}}
[data-testid="stMetric"] {{
  border-radius:17px !important;
  border:1px solid rgba(255,255,255,.075) !important;
  background:linear-gradient(145deg,rgba(16,24,38,.92),rgba(9,14,24,.92)) !important;
  box-shadow:0 12px 28px rgba(0,0,0,.15);
}}
[data-testid="stDataFrame"] {{
  border-radius:18px !important;
  overflow:hidden;
  border:1px solid rgba(255,255,255,.075) !important;
  box-shadow:0 14px 34px rgba(0,0,0,.14);
}}
div[data-baseweb="tab-list"] {{
  background:rgba(7,12,20,.72);
  border:1px solid rgba(255,255,255,.07);
  border-radius:14px;
  padding:4px;
}}
button[data-baseweb="tab"] {{
  border-radius:10px !important;
  font-weight:800 !important;
}}
.fx3-live-strip {{
  position:relative;overflow:hidden;
  display:flex;align-items:center;gap:14px;
  margin:.65rem 0 1rem;padding:9px 12px;
  border:1px solid rgba(255,255,255,.075);border-radius:13px;
  background:rgba(5,10,18,.82);box-shadow:0 12px 30px rgba(0,0,0,.18);
  color:#9fb0c5;font-size:.62rem;font-weight:820;letter-spacing:.02em;
}}
.fx3-live-strip::before {{ content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--fx3-primary); }}
.fx3-live-dot {{ width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 13px #22c55e;flex:0 0 auto; }}
.fx3-live-label {{ color:#eaf2ff;font-weight:950;letter-spacing:.12em;font-size:.54rem; }}
.fx3-live-item strong {{ color:#f8fbff; }}
.fx3-showcase {{
  display:grid;grid-template-columns:1.13fr .92fr .95fr;gap:12px;margin:.55rem 0 1.15rem;
}}
.fx3-card {{
  position:relative;overflow:hidden;min-height:220px;padding:18px;
  border:1px solid var(--fx3-border);border-radius:22px;
  background:linear-gradient(145deg,rgba(14,22,35,.96),rgba(7,12,21,.95));
  box-shadow:0 18px 44px rgba(0,0,0,.22);
}}
.fx3-card::after {{ content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--fx3-accent,var(--fx3-primary)),transparent 78%); }}
.fx3-card:hover {{ border-color:color-mix(in srgb,var(--fx3-accent,var(--fx3-primary)) 40%,rgba(255,255,255,.1)); }}
.fx3-overline {{ color:#7f91a9;font-size:.52rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase; }}
.fx3-card-title {{ margin:.28rem 0 .15rem;color:#fff;font-size:1.02rem;font-weight:950;letter-spacing:-.025em; }}
.fx3-card-copy {{ color:#91a2b8;font-size:.66rem;line-height:1.45; }}
.fx3-match {{ display:grid;grid-template-columns:1fr 58px 1fr;align-items:center;gap:8px;margin-top:15px; }}
.fx3-club {{ text-align:center; }}
.fx3-club img {{ width:78px;height:78px;object-fit:contain;filter:drop-shadow(0 12px 18px rgba(0,0,0,.4)); }}
.fx3-club-name {{ margin-top:6px;color:#fff;font-size:.67rem;font-weight:900; }}
.fx3-club-record {{ color:#8395ab;font-size:.56rem;font-weight:800; }}
.fx3-versus {{ text-align:center;color:#6e8097;font-size:.52rem;font-weight:950;letter-spacing:.16em; }}
.fx3-date {{ margin-top:3px;color:#dbeafe;font-size:.58rem;font-weight:850;letter-spacing:0; }}
.fx3-star-wrap {{ display:flex;align-items:flex-end;justify-content:space-between;min-height:164px;gap:8px; }}
.fx3-star-copy {{ position:relative;z-index:2;max-width:58%;padding-bottom:4px; }}
.fx3-star-name {{ margin:.4rem 0 .25rem;color:#fff;font-size:1.35rem;font-weight:950;line-height:1.03;letter-spacing:-.045em; }}
.fx3-star-meta {{ color:#a9bad0;font-size:.65rem;font-weight:760; }}
.fx3-star-img {{ position:absolute;right:-4px;bottom:0;width:154px;height:178px;object-fit:contain;object-position:bottom center;filter:drop-shadow(0 18px 24px rgba(0,0,0,.44)); }}
.fx3-star-watermark {{ position:absolute;right:8px;top:10px;width:84px;height:84px;object-fit:contain;opacity:.09;filter:grayscale(1); }}
.fx3-pulse-ring {{
  width:118px;height:118px;border-radius:50%;display:grid;place-items:center;margin:13px auto 8px;
  background:conic-gradient(var(--fx3-accent,var(--fx3-primary)) calc(var(--progress) * 1%),rgba(255,255,255,.07) 0);
  box-shadow:0 0 30px color-mix(in srgb,var(--fx3-accent,var(--fx3-primary)) 12%,transparent);
}}
.fx3-pulse-ring::before {{ content:"";width:88px;height:88px;border-radius:50%;background:#0b111c;border:1px solid rgba(255,255,255,.07); }}
.fx3-pulse-inner {{ position:absolute;text-align:center; }}
.fx3-pulse-value {{ color:#fff;font-size:1.22rem;font-weight:950; }}
.fx3-pulse-label {{ color:#788ba3;font-size:.48rem;font-weight:900;letter-spacing:.1em;text-transform:uppercase; }}
.fx3-pulse-grid {{ display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px; }}
.fx3-mini {{ padding:8px;border-radius:10px;background:rgba(255,255,255,.028);border:1px solid rgba(255,255,255,.055);text-align:center; }}
.fx3-mini span {{ display:block;color:#6f829a;font-size:.46rem;font-weight:900;letter-spacing:.09em;text-transform:uppercase; }}
.fx3-mini strong {{ display:block;margin-top:2px;color:#f8fbff;font-size:.69rem;font-weight:950; }}
.fx3-action-row {{ display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:.15rem 0 1.2rem; }}
.fx3-action-card {{ padding:10px 12px;border:1px solid rgba(255,255,255,.065);border-radius:12px;background:rgba(255,255,255,.025); }}
.fx3-action-card b {{ display:block;color:#fff;font-size:.61rem; }}
.fx3-action-card span {{ display:block;color:#75879f;font-size:.52rem;margin-top:2px; }}
@media(max-width:1100px) {{ .fx3-showcase{{grid-template-columns:1fr 1fr}} .fx3-showcase>.fx3-card:last-child{{grid-column:1/-1}} }}
@media(max-width:720px) {{ .fx3-showcase,.fx3-action-row{{grid-template-columns:1fr}} .fx3-showcase>.fx3-card:last-child{{grid-column:auto}} .fx3-live-strip{{flex-wrap:wrap}} }}
@media(prefers-reduced-motion:reduce) {{ .frx-goal{{transition:none}} }}
</style>
""",
        unsafe_allow_html=True,
    )


def _featured_player(featured_rows: Iterable[dict[str, Any]], active_team: str, headshot_resolver: Callable[[str, str], str]) -> dict[str, str]:
    rows = list(featured_rows or [])
    if not rows:
        return {
            "name": "Franchise core",
            "meta": "Build your identity",
            "image": _logo(active_team),
        }
    row = rows[0]
    player_id = _text(row.get("player_id"))
    name = _text(row.get("player")) or "Franchise core"
    ovr = _number(row.get("overall"))
    detail = f"{ovr:.0f} OVR"
    minutes = _number(row.get("minutes"))
    if minutes > 0:
        detail += f" · {minutes:.0f} MIN"
    return {
        "name": name,
        "meta": detail,
        "image": _text(headshot_resolver(player_id, active_team)) or _logo(active_team),
    }


def render_franchise_showcase_v3(
    *,
    state: Any,
    snapshot: Any,
    active_team: str,
    featured_rows: Iterable[dict[str, Any]],
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    player_headshot_resolver: Callable[[str, str], str],
    blocking_count: int,
    set_section: Callable[[str], None],
) -> None:
    import streamlit as st

    # The first-time wizard owns the screen until the user dismisses it.
    if st.session_state.get("franchise_tutorial_open_v1", True):
        return

    team = _text(active_team).upper()
    next_opponent = _text(getattr(snapshot, "next_opponent", "")).upper()
    season_label = _text(getattr(getattr(state, "settings", None), "season_label", ""))
    raw_phase = _text(getattr(getattr(state, "phase", None), "value", getattr(state, "phase", "")))
    phase = raw_phase.replace("_", " ").title()
    opening_setup = (
        raw_phase.lower() == "offseason"
        and int(getattr(state, "transition_count", 0) or 0) == 0
        and not list(getattr(state, "season_history", ()) or ())
        and not dict(getattr(state, "completed_games", {}) or {})
    )
    star = _featured_player(featured_rows, team, player_headshot_resolver)

    recent_form = _text(getattr(snapshot, "recent_form", "")) or "No games"
    streak = _text(getattr(snapshot, "streak", "")) or "—"
    progress = max(0.0, min(100.0, _number(getattr(snapshot, "season_completion_percentage", 0))))
    league_rank = int(_number(getattr(snapshot, "league_rank", 0)))
    conf_rank = int(_number(getattr(snapshot, "conference_rank", 0)))
    alerts = len(tuple(getattr(snapshot, "alerts", ()) or ()))
    wins = int(_number(getattr(snapshot, "wins", 0)))
    losses = int(_number(getattr(snapshot, "losses", 0)))

    if next_opponent:
        opponent_name = team_name_resolver(next_opponent)
        opponent_logo = team_logo_resolver(next_opponent)
        opponent_record = f"{int(_number(getattr(snapshot, 'opponent_wins', 0)))}-{int(_number(getattr(snapshot, 'opponent_losses', 0)))}"
        game_date = _text(getattr(snapshot, "next_game_date", "")) or "Upcoming"
        location = _text(getattr(snapshot, "next_location", "")) or "NEXT"
        matchup_html = f"""
        <div class="fx3-overline">{("Opening-week preview" if opening_setup else "Next matchup · " + html.escape(location))}</div>
        <div class="fx3-card-title">{html.escape(game_date)}</div>
        <div class="fx3-match">
          <div class="fx3-club">{_safe_img(team_logo_resolver(team), team_name_resolver(team), "fx3-club-logo")}<div class="fx3-club-name">{html.escape(team)}</div><div class="fx3-club-record">{wins}-{losses}</div></div>
          <div class="fx3-versus">VS<div class="fx3-date">{html.escape(_text(getattr(snapshot,'next_location','')))}</div></div>
          <div class="fx3-club">{_safe_img(opponent_logo, opponent_name, "fx3-club-logo")}<div class="fx3-club-name">{html.escape(next_opponent)}</div><div class="fx3-club-record">{opponent_record}</div></div>
        </div>
        """
    else:
        matchup_html = f"""
        <div class="fx3-overline">Season calendar</div>
        <div class="fx3-card-title">{html.escape(phase or "Offseason")}</div>
        <div class="fx3-card-copy">No regular-season matchup is queued. Use the highlighted progression action to move the franchise toward its next competitive date.</div>
        <div style="margin-top:22px;text-align:center">{_safe_img(team_logo_resolver(team), team_name_resolver(team), "fx3-club-logo")}</div>
        """

    inbox_copy = "CLEAR" if blocking_count == 0 else f"{blocking_count} WAITING"
    strip_items = [
        ("SEASON", season_label or "Current"),
        ("PHASE", phase or "Active"),
        ("FORM", recent_form),
        ("INBOX", inbox_copy),
    ]
    strip_html = "".join(
        f'<span class="fx3-live-item">{html.escape(label)} <strong>{html.escape(value)}</strong></span>'
        for label, value in strip_items
    )
    st.markdown(
        f'<div class="fx3-live-strip"><span class="fx3-live-dot"></span><span class="fx3-live-label">FRANCHISE LIVE</span>{strip_html}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="fx3-showcase">
  <div class="fx3-card" style="--fx3-accent:var(--fx3-primary)">{matchup_html}</div>
  <div class="fx3-card" style="--fx3-accent:var(--fx3-secondary)">
    <img class="fx3-star-watermark" src="{html.escape(team_logo_resolver(team), quote=True)}" alt="">
    <div class="fx3-overline">Franchise face</div>
    <div class="fx3-star-wrap">
      <div class="fx3-star-copy">
        <div class="fx3-card-copy">Featured from your current rotation</div>
        <div class="fx3-star-name">{html.escape(star['name'])}</div>
        <div class="fx3-star-meta">{html.escape(star['meta'])}</div>
      </div>
      <img class="fx3-star-img" src="{html.escape(star['image'], quote=True)}" alt="{html.escape(star['name'], quote=True)}">
    </div>
  </div>
  <div class="fx3-card" style="--fx3-accent:var(--fx3-primary)">
    <div class="fx3-overline">Season pulse</div>
    <div class="fx3-card-title">{wins}-{losses} · {html.escape(streak)}</div>
    <div class="fx3-pulse-ring" style="--progress:{progress:.1f}"><div class="fx3-pulse-inner"><div class="fx3-pulse-value">{progress:.0f}%</div><div class="fx3-pulse-label">season</div></div></div>
    <div class="fx3-pulse-grid">
      <div class="fx3-mini"><span>NBA rank</span><strong>#{league_rank if league_rank else '—'}</strong></div>
      <div class="fx3-mini"><span>Conf rank</span><strong>#{conf_rank if conf_rank else '—'}</strong></div>
      <div class="fx3-mini"><span>Game alerts</span><strong>{alerts}</strong></div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    if opening_setup:
        first_card = '<div class="fx3-action-card"><b>🏁 Opening Night</b><span>Start the regular season below to unlock Game Day.</span></div>'
    else:
        first_card = '<div class="fx3-action-card"><b>🏀 Game Day</b><span>Prepare, play or simulate the next matchup.</span></div>'
    st.markdown(
        '<div class="fx3-action-row">'
        + first_card
        + '<div class="fx3-action-card"><b>👥 Roster</b><span>Rotation, minutes and player availability.</span></div>'
        + '<div class="fx3-action-card"><b>🔄 Transactions</b><span>Improve the roster without leaving Franchise Mode.</span></div>'
        + '<div class="fx3-action-card"><b>📊 League pulse</b><span>Standings, stats and the wider NBA story.</span></div>'
        + '</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    if opening_setup:
        cols[0].button(
            "Game Day unlocks after season start",
            width="stretch",
            disabled=True,
            key="fx3_route::opening_setup_locked",
        )
    elif cols[0].button("Open Game Day", width="stretch", key="fx3_route::Game Day"):
        set_section("Game Day")
        st.rerun()

    for col, (label, section) in zip(
        cols[1:],
        (
            ("Manage Roster", "Team Management"),
            ("Open Transactions", "Trade Center"),
            ("View League", "Stats & Standings"),
        ),
    ):
        if col.button(label, width="stretch", key=f"fx3_route::{section}"):
            set_section(section)
            st.rerun()


def inject_home_visual_overhaul_v3() -> None:
    import streamlit as st
    st.markdown(
        """
<style>
/* FRANCHISE_HOME_VISUAL_OVERHAUL_V3 */
.hero-shell,.metric-grid,.product-grid{display:none!important}
.fx3-home-hero{position:relative;overflow:hidden;margin:.3rem 0 1.05rem;padding:34px 34px 28px;border:1px solid rgba(255,255,255,.11);border-radius:28px;background:radial-gradient(circle at 82% 24%,rgba(37,99,235,.32),transparent 31%),radial-gradient(circle at 68% 98%,rgba(206,17,65,.18),transparent 28%),linear-gradient(135deg,#0b1322,#0c1e39 58%,#0a101b);box-shadow:0 28px 72px rgba(0,0,0,.33)}
.fx3-home-hero:after{content:"";position:absolute;inset:auto 0 0;height:4px;background:linear-gradient(90deg,#2563eb,#ef4444,#f59e0b,#22c55e)}
.fx3-home-kicker{display:inline-flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid rgba(96,165,250,.2);border-radius:999px;background:rgba(37,99,235,.12);color:#bfdbfe;font-size:.57rem;font-weight:950;letter-spacing:.12em;text-transform:uppercase}
.fx3-home-title{margin:.85rem 0 .6rem;max-width:850px;color:#fff;font-size:clamp(2.4rem,5vw,5rem);line-height:.93;font-weight:1000;letter-spacing:-.065em}
.fx3-home-title span{background:linear-gradient(90deg,#fff,#bfdbfe 52%,#fdba74);-webkit-background-clip:text;background-clip:text;color:transparent}
.fx3-home-copy{max-width:760px;color:#a9bad0;font-size:.95rem;line-height:1.65}
.fx3-home-logos{position:absolute;right:24px;top:26px;width:330px;height:245px}
.fx3-home-logo{position:absolute;width:92px;height:92px;object-fit:contain;filter:drop-shadow(0 17px 24px rgba(0,0,0,.45));opacity:.92}
.fx3-home-logo:nth-child(1){right:118px;top:0;width:116px;height:116px}
.fx3-home-logo:nth-child(2){right:0;top:56px}.fx3-home-logo:nth-child(3){right:220px;top:62px}.fx3-home-logo:nth-child(4){right:48px;top:146px}.fx3-home-logo:nth-child(5){right:174px;top:151px}.fx3-home-logo:nth-child(6){right:278px;top:150px;width:72px;height:72px}
.fx3-home-proof{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:24px;max-width:820px}
.fx3-home-proof div{padding:10px 11px;border:1px solid rgba(255,255,255,.075);border-radius:12px;background:rgba(255,255,255,.035)}
.fx3-home-proof b{display:block;color:#fff;font-size:.72rem}.fx3-home-proof span{display:block;margin-top:2px;color:#7f91a9;font-size:.51rem;line-height:1.35}
.fx3-home-tools{display:grid;grid-template-columns:1.7fr 1fr 1fr;gap:9px;margin:1rem 0 1.2rem}
.fx3-home-tool{padding:15px;border:1px solid rgba(255,255,255,.07);border-radius:15px;background:linear-gradient(145deg,rgba(15,23,38,.88),rgba(8,13,22,.9))}
.fx3-home-tool.primary{border-color:rgba(59,130,246,.27);background:radial-gradient(circle at 95% 0%,rgba(37,99,235,.16),transparent 40%),linear-gradient(145deg,rgba(15,23,38,.94),rgba(8,13,22,.94))}
.fx3-home-tool b{display:block;color:#fff;font-size:.77rem}.fx3-home-tool span{display:block;margin-top:3px;color:#8192a8;font-size:.57rem;line-height:1.42}
@media(max-width:1050px){.fx3-home-logos{opacity:.25}.fx3-home-title,.fx3-home-copy{position:relative;z-index:2}.fx3-home-proof{position:relative;z-index:2}.fx3-home-tools{grid-template-columns:1fr}}
@media(max-width:700px){.fx3-home-hero{padding:24px 20px}.fx3-home-logos{display:none}.fx3-home-proof{grid-template-columns:repeat(2,1fr)}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_home_flagship_v3() -> None:
    import streamlit as st

    logos = "".join(
        f'<img class="fx3-home-logo" src="{html.escape(_logo(team), quote=True)}" alt="{team}">'
        for team in HOME_FEATURE_TEAMS
    )
    st.markdown(
        f"""
<div class="fx3-home-hero">
  <div class="fx3-home-kicker">🏆 Persistent NBA management universe</div>
  <div class="fx3-home-title"><span>Build the franchise.<br>Own every season.</span></div>
  <div class="fx3-home-copy">A deep NBA franchise simulator built around persistent saves, real roster management, CBA-aware transactions, Game Day, staff, health, free agency, the draft, development, playoffs and multi-season league history.</div>
  <div class="fx3-home-proof">
    <div><b>30 NBA teams</b><span>One connected league universe</span></div>
    <div><b>1,230-game seasons</b><span>Full regular-season lifecycle</span></div>
    <div><b>Persistent progression</b><span>Draft, development and history</span></div>
    <div><b>CBA-aware front office</b><span>Trades, rights and free agency</span></div>
  </div>
  <div class="fx3-home-logos">{logos}</div>
</div>
<div class="fx3-home-tools">
  <div class="fx3-home-tool primary"><b>🏆 Franchise Mode is the main experience</b><span>Start here. Every major system feeds the same durable franchise universe.</span></div>
  <div class="fx3-home-tool"><b>🧪 Analysis sandboxes</b><span>Trade Lab, Player Ratings and the standalone Game Simulator remain useful specialist tools.</span></div>
  <div class="fx3-home-tool"><b>💾 Built to come back to</b><span>Autosave, progression guidance, league stories and multi-season history keep your franchise moving.</span></div>
</div>
""",
        unsafe_allow_html=True,
    )
