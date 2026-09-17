from __future__ import annotations

import html


FRANCHISE_ONBOARDING_PROGRESSION_VERSION = "franchise-onboarding-progression-v2.0-2026-09-11"

SECTION_ICONS = {
    "Command Center": "🎛️", "Inbox & League Health": "🚨", "Calendar": "📅",
    "Team Management": "👥", "Staff": "🧠", "Free Agency": "✍️",
    "Game Day": "🏀", "Stats & Standings": "📊", "Trade Center": "🔄",
    "Draft Room": "🎓", "League & Offseason": "🏆",
}

SECTION_EXPERIENCE = {
    "Command Center": ("time", "Advances time when you simulate", ("Next action", "Quick sim")),
    "Inbox & League Health": ("confirm", "Safe until you confirm", ("Decisions", "League health")),
    "Calendar": ("safe", "Safe to explore", ("Schedule", "Results")),
    "Team Management": ("confirm", "Changes lineup when saved", ("Rotation", "Roster")),
    "Staff": ("confirm", "Changes staff when confirmed", ("Coaches", "Front office")),
    "Free Agency": ("confirm", "Changes roster when signed", ("Market", "Offers")),
    "Game Day": ("time", "Advances time when committed", ("Matchup", "Game plan")),
    "Stats & Standings": ("safe", "Safe to explore", ("Standings", "Leaders")),
    "Trade Center": ("confirm", "Changes roster when committed", ("Trade finder", "Offers")),
    "Draft Room": ("confirm", "Changes roster when pick is made", ("Big board", "Draft")),
    "League & Offseason": ("time", "Advances season when confirmed", ("Lifecycle", "History")),
}


def inject_franchise_onboarding_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_ONBOARDING_PROGRESSION_V2 */
.fm2-hud,.fm2-wizard,.fm2-masthead{{--team-primary:{primary};--team-secondary:{secondary};position:relative;overflow:hidden}}
.fm2-hud::before,.fm2-wizard::before,.fm2-masthead::before{{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 92% 0%,color-mix(in srgb,var(--team-primary) 22%,transparent),transparent 34%)}}
.fm2-eyebrow{{font-size:.63rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase;color:#7dd3fc}}
.fm2-kicker-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.fm2-live-dot{{width:7px;height:7px;border-radius:50%;background:#34d399;box-shadow:0 0 0 4px rgba(52,211,153,.11),0 0 18px rgba(52,211,153,.45)}}

/* Persistent season control HUD */
.fm2-hud{{margin:.15rem 0 1rem;padding:17px 18px 15px;border:1px solid color-mix(in srgb,var(--team-primary) 34%,rgba(255,255,255,.11));border-radius:20px;background:linear-gradient(135deg,color-mix(in srgb,var(--team-primary) 12%,#0a1019),rgba(8,13,22,.96) 58%,color-mix(in srgb,var(--team-secondary) 10%,#080d16));box-shadow:0 20px 50px rgba(0,0,0,.20)}}
.fm2-hud-head{{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:14px}}
.fm2-hud-team{{display:flex;align-items:center;gap:12px;min-width:0}}
.fm2-hud-logo{{width:46px;height:46px;object-fit:contain;padding:4px;border-radius:13px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.10);filter:drop-shadow(0 10px 13px rgba(0,0,0,.26))}}
.fm2-hud-title{{color:#fff;font-size:1rem;font-weight:950;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fm2-hud-sub{{color:#8fa0b5;font-size:.69rem;margin-top:2px}}
.fm2-hud-stats{{display:flex;align-items:center;justify-content:flex-end;gap:7px;flex-wrap:wrap}}
.fm2-hud-stat{{padding:7px 9px;border:1px solid rgba(255,255,255,.08);border-radius:10px;background:rgba(255,255,255,.03);color:#dbe7f5;font-size:.65rem;font-weight:850}}
.fm2-hud-stat strong{{color:#fff;margin-left:4px}}
.fm2-track-wrap{{position:relative;z-index:1;padding:7px 4px 2px}}
.fm2-track{{position:absolute;left:8.3%;right:8.3%;top:22px;height:3px;border-radius:999px;background:rgba(255,255,255,.075);overflow:hidden}}
.fm2-track-fill{{height:100%;border-radius:inherit;background:linear-gradient(90deg,#22d3ee,var(--team-primary),var(--team-secondary),#f59e0b);box-shadow:0 0 18px color-mix(in srgb,var(--team-primary) 45%,transparent);transition:width .45s ease}}
.fm2-nodes{{display:grid;grid-template-columns:repeat(6,1fr);position:relative}}
.fm2-node{{display:flex;flex-direction:column;align-items:center;gap:6px;color:#64748b;font-size:.62rem;font-weight:850;text-align:center}}
.fm2-node-dot{{display:grid;place-items:center;width:31px;height:31px;border-radius:50%;border:1px solid rgba(255,255,255,.09);background:#0c131f;color:#718096;font-size:.72rem;box-shadow:0 0 0 5px rgba(8,13,22,.86)}}
.fm2-node.done{{color:#9ce8ba}}.fm2-node.done .fm2-node-dot{{color:#07140d;background:#34d399;border-color:#6ee7b7}}
.fm2-node.current{{color:#fff}}.fm2-node.current .fm2-node-dot{{color:#fff;background:linear-gradient(135deg,var(--team-primary),var(--team-secondary));border-color:rgba(255,255,255,.42);box-shadow:0 0 0 5px rgba(8,13,22,.88),0 0 24px color-mix(in srgb,var(--team-primary) 55%,transparent);transform:scale(1.08)}}
.fm2-you-are-here{{display:inline-block;margin-top:3px;padding:2px 5px;border-radius:5px;background:rgba(125,211,252,.11);color:#bae6fd;font-size:.48rem;letter-spacing:.08em;text-transform:uppercase}}
.fm2-action-grid{{position:relative;z-index:1;display:grid;grid-template-columns:minmax(0,1.55fr) minmax(280px,.85fr);gap:10px;margin-top:15px}}
.fm2-next{{padding:14px 15px;border-radius:14px;border:1px solid color-mix(in srgb,var(--team-primary) 28%,rgba(255,255,255,.08));background:linear-gradient(115deg,color-mix(in srgb,var(--team-primary) 12%,rgba(255,255,255,.025)),rgba(255,255,255,.018))}}
.fm2-next-title{{font-size:1rem;font-weight:950;color:#fff;margin:.18rem 0 .2rem}}.fm2-next-copy{{color:#9eacc0;font-size:.75rem;line-height:1.43}}
.fm2-signals{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}}
.fm2-signal{{padding:9px;border-radius:11px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.023)}}
.fm2-signal-icon{{font-size:.85rem}}.fm2-signal-label{{color:#718096;font-size:.52rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-top:4px}}.fm2-signal-value{{color:#edf5ff;font-size:.65rem;font-weight:850;margin-top:2px;line-height:1.25}}

/* Section identity and action-risk indicator */
.fm2-masthead{{margin:.35rem 0 1rem;padding:16px 18px;border:1px solid color-mix(in srgb,var(--route-color) 36%,rgba(255,255,255,.10));border-radius:18px;background:linear-gradient(125deg,color-mix(in srgb,var(--route-color) 15%,#0a1019),rgba(9,14,23,.95));box-shadow:0 16px 38px rgba(0,0,0,.14)}}
.fm2-masthead::after{{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--route-color),transparent 76%)}}
.fm2-watermark{{position:absolute;right:18px;top:50%;width:84px;height:84px;object-fit:contain;transform:translateY(-50%);opacity:.11;filter:grayscale(.2)}}
.fm2-masthead-row{{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:18px;padding-right:76px}}
.fm2-masthead-main{{display:flex;align-items:center;gap:13px;min-width:0}}
.fm2-masthead-icon{{display:grid;place-items:center;flex:0 0 auto;width:48px;height:48px;border-radius:14px;background:color-mix(in srgb,var(--route-color) 22%,rgba(255,255,255,.035));border:1px solid color-mix(in srgb,var(--route-color) 45%,rgba(255,255,255,.12));font-size:1.35rem;box-shadow:0 10px 28px color-mix(in srgb,var(--route-color) 14%,transparent)}}
.fm2-masthead-title{{color:#fff;font-size:1.13rem;font-weight:950;letter-spacing:-.025em;margin:.1rem 0 .14rem}}.fm2-masthead-copy{{color:#9eacc0;font-size:.78rem;line-height:1.43;max-width:920px}}
.fm2-route-tools{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end}}
.fm2-impact,.fm2-chip{{white-space:nowrap;border-radius:999px;font-size:.56rem;font-weight:900;letter-spacing:.055em;text-transform:uppercase}}
.fm2-impact{{padding:6px 8px;border:1px solid}}
.fm2-impact.safe{{color:#86efac;border-color:rgba(34,197,94,.28);background:rgba(34,197,94,.08)}}
.fm2-impact.confirm{{color:#fde68a;border-color:rgba(245,158,11,.3);background:rgba(245,158,11,.08)}}
.fm2-impact.time{{color:#fda4af;border-color:rgba(244,63,94,.3);background:rgba(244,63,94,.08)}}
.fm2-chip{{padding:5px 7px;color:#aab8ca;border:1px solid rgba(255,255,255,.075);background:rgba(255,255,255,.025)}}

/* Progressive Rookie GM walkthrough */
.fm2-wizard{{margin:.45rem 0 1.1rem;padding:22px;border:1px solid rgba(125,211,252,.19);border-radius:22px;background:radial-gradient(circle at 10% 110%,rgba(168,85,247,.15),transparent 34%),linear-gradient(145deg,rgba(13,23,40,.98),rgba(8,13,22,.97));box-shadow:0 25px 60px rgba(0,0,0,.22)}}
.fm2-wizard-head{{position:relative;z-index:1;display:flex;align-items:flex-start;justify-content:space-between;gap:18px}}
.fm2-wizard-brand{{display:flex;align-items:center;gap:13px}}
.fm2-wizard-logo{{width:55px;height:55px;object-fit:contain;padding:5px;border-radius:16px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);filter:drop-shadow(0 12px 18px rgba(0,0,0,.28))}}
.fm2-wizard h2{{font-size:1.38rem!important;line-height:1.12;margin:.22rem 0 .35rem!important;color:#fff!important}}.fm2-wizard p{{max-width:780px;color:#a8b5c7;font-size:.82rem;line-height:1.5}}
.fm2-wizard-count{{flex:0 0 auto;padding:7px 9px;border-radius:999px;background:rgba(125,211,252,.08);border:1px solid rgba(125,211,252,.17);color:#bae6fd;font-size:.58rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}
.fm2-wizard-progress{{position:relative;z-index:1;display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:16px 0 18px}}.fm2-wizard-progress span{{height:4px;border-radius:999px;background:rgba(255,255,255,.075)}}.fm2-wizard-progress span.on{{background:linear-gradient(90deg,#22d3ee,var(--team-primary));box-shadow:0 0 12px color-mix(in srgb,var(--team-primary) 42%,transparent)}}
.fm2-feature{{position:relative;z-index:1;padding:16px;border:1px solid rgba(255,255,255,.075);border-radius:16px;background:rgba(255,255,255,.024)}}
.fm2-feature-title{{color:#fff;font-size:1.02rem;font-weight:950;margin:.22rem 0 .32rem}}.fm2-feature-copy{{color:#9faec1;font-size:.77rem;line-height:1.48}}
.fm2-loop,.fm2-safety,.fm2-discovery{{position:relative;z-index:1;display:grid;gap:8px;margin-top:12px}}
.fm2-loop{{grid-template-columns:repeat(4,1fr)}}.fm2-safety{{grid-template-columns:repeat(3,1fr)}}.fm2-discovery{{grid-template-columns:repeat(2,1fr)}}
.fm2-mini{{padding:13px;border:1px solid rgba(255,255,255,.075);border-radius:14px;background:rgba(255,255,255,.025);min-height:98px}}
.fm2-mini-icon{{font-size:1.2rem}}.fm2-mini-name{{color:#fff;font-size:.76rem;font-weight:900;margin:.35rem 0 .22rem}}.fm2-mini-copy{{color:#91a1b5;font-size:.66rem;line-height:1.42}}
.fm2-mini.safe{{border-color:rgba(34,197,94,.18);background:rgba(34,197,94,.045)}}.fm2-mini.confirm{{border-color:rgba(245,158,11,.18);background:rgba(245,158,11,.045)}}.fm2-mini.time{{border-color:rgba(244,63,94,.18);background:rgba(244,63,94,.045)}}
.fm2-tip{{position:relative;z-index:1;margin-top:12px;padding:10px 12px;border-left:3px solid #22d3ee;border-radius:0 10px 10px 0;background:rgba(34,211,238,.055);color:#b5c5d8;font-size:.71rem;line-height:1.4}}

@media(max-width:1050px){{.fm2-action-grid{{grid-template-columns:1fr}}.fm2-masthead-row{{align-items:flex-start;flex-direction:column}}.fm2-route-tools{{justify-content:flex-start}}.fm2-loop{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:760px){{.fm2-hud,.fm2-wizard{{padding:15px}}.fm2-hud-head,.fm2-wizard-head{{align-items:flex-start;flex-direction:column}}.fm2-hud-stats{{justify-content:flex-start}}.fm2-node{{font-size:.52rem}}.fm2-node-dot{{width:26px;height:26px}}.fm2-track{{top:19px}}.fm2-signals{{grid-template-columns:repeat(3,1fr)}}.fm2-safety,.fm2-discovery{{grid-template-columns:1fr}}.fm2-masthead-row{{padding-right:0}}.fm2-watermark{{display:none}}}}
@media(prefers-reduced-motion:reduce){{.fm2-track-fill,.fm2-node-dot{{transition:none!important}}.fm2-live-dot{{box-shadow:none}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def _nav_button(label: str, section: str, set_section, *, key: str, primary: bool = False) -> None:
    import streamlit as st
    if st.button(label, type=("primary" if primary else "secondary"), width="stretch", key=key):
        set_section(section)
        st.rerun()


def _logo_html(team_logo_url: str, *, class_name: str) -> str:
    if not team_logo_url:
        return ""
    return f'<img class="{class_name}" src="{html.escape(team_logo_url, quote=True)}" alt="Team logo">'


def render_help_sidebar_v1(*, set_section) -> bool:
    import streamlit as st
    st.session_state.setdefault("franchise_guidance_mode_v1", True)
    with st.sidebar:
        st.markdown('<div class="fpnav-divider"></div><div class="fpnav-section">Guidance</div>', unsafe_allow_html=True)
        guidance = st.toggle("Show progression guide", key="franchise_guidance_mode_v1")
        if st.button("❓ How to play / replay tour", width="stretch", key="franchise_replay_tutorial_v1"):
            st.session_state["franchise_tutorial_open_v1"] = True
            st.session_state["franchise_tutorial_step_v2"] = 0
            set_section("Command Center")
            st.rerun()
    return bool(guidance)


def render_section_masthead_v1(*, section: str, guide_tuple, team_logo_url: str = "") -> None:
    import streamlit as st
    title, detail, color = guide_tuple
    icon = SECTION_ICONS.get(section, "🏀")
    impact_class, impact_label, chips = SECTION_EXPERIENCE.get(section, ("safe", "Safe to explore", ("Overview", "Tools")))
    chip_html = "".join(f'<span class="fm2-chip">{html.escape(chip)}</span>' for chip in chips)
    st.markdown(
        f'''<div class="fm2-masthead" style="--route-color:{html.escape(color, quote=True)}">
        {_logo_html(team_logo_url, class_name="fm2-watermark")}
        <div class="fm2-masthead-row"><div class="fm2-masthead-main"><div class="fm2-masthead-icon">{icon}</div><div>
        <div class="fm2-eyebrow">{html.escape(section)}</div><div class="fm2-masthead-title">{html.escape(title)}</div><div class="fm2-masthead-copy">{html.escape(detail)}</div>
        </div></div><div class="fm2-route-tools"><span class="fm2-impact {impact_class}">{html.escape(impact_label)}</span>{chip_html}</div></div></div>''',
        unsafe_allow_html=True,
    )


def _journey_index(*, phase_name: str, has_history: bool, regular_season_complete: bool, postseason_complete: bool, draft_complete: bool) -> int:
    if phase_name == "offseason" and not has_history and not regular_season_complete and not postseason_complete:
        return 0
    if phase_name != "offseason" and not regular_season_complete:
        return 1
    if regular_season_complete and not postseason_complete and phase_name != "offseason":
        return 2
    if phase_name == "offseason" and not draft_complete:
        return 3
    if phase_name == "offseason" and draft_complete:
        return 5
    return 1


def _next_action(*, phase_name: str, has_history: bool, regular_season_complete: bool, postseason_complete: bool, draft_complete: bool, blocking_count: int, next_game_id: str | None):
    if blocking_count:
        return "Resolve your decision inbox", f"{blocking_count} unresolved decision(s) are pausing league advancement.", "Inbox & League Health", "Open decision inbox"
    if phase_name == "offseason" and not has_history and not regular_season_complete and not postseason_complete:
        return "Open your first regular season", "Your league is ready. Review your roster if you want, then use the certified season-opening control.", "League & Offseason", "Go to season opener"
    if not regular_season_complete:
        return "Prepare your next game" if next_game_id else "Advance the calendar", "Take hands-on control in Game Day, or simulate from the Command Center when you are ready.", "Game Day" if next_game_id else "Command Center", "Open Game Day" if next_game_id else "Open Command Center"
    if not postseason_complete:
        return "Continue the postseason", "Your regular season is complete. Follow the playoff controls until a champion is crowned.", "Game Day", "Open playoff controls"
    if phase_name == "offseason" and not draft_complete:
        return "Build the next version of your team", "Work Free Agency and trades, then complete the Draft. The next season stays locked until you are ready.", "Free Agency", "Open Free Agency"
    return "Open the next season", "The Draft is complete. Archive the year and build the next 1,230-game league schedule.", "League & Offseason", "Open next-season controls"


def render_franchise_progress_coach_v1(
    *, phase_name: str, has_history: bool, regular_season_complete: bool,
    postseason_complete: bool, draft_complete: bool, blocking_count: int,
    next_game_id: str | None, set_section, guidance: bool, season_label: str = "",
    active_team: str = "", team_name: str = "", team_logo_url: str = "",
    completed_games: int = 0, scheduled_games: int = 0,
) -> None:
    import streamlit as st
    if not guidance:
        return
    steps = [("Setup", "01"), ("Regular season", "02"), ("Playoffs", "03"), ("Offseason", "04"), ("Draft", "05"), ("Next season", "06")]
    idx = _journey_index(phase_name=phase_name, has_history=has_history, regular_season_complete=regular_season_complete, postseason_complete=postseason_complete, draft_complete=draft_complete)
    league_progress = max(0.0, min(1.0, completed_games / max(1, scheduled_games)))
    fill = idx / (len(steps) - 1)
    if idx == 1 and not regular_season_complete:
        fill += league_progress / (len(steps) - 1)
    fill = min(1.0, fill)
    nodes = "".join(
        f'''<div class="fm2-node {'done' if i < idx else 'current' if i == idx else ''}"><div class="fm2-node-dot">{'✓' if i < idx else num}</div><div>{html.escape(name)}</div>{'<span class="fm2-you-are-here">You are here</span>' if i == idx else ''}</div>'''
        for i, (name, num) in enumerate(steps)
    )
    title, copy, target, button = _next_action(phase_name=phase_name, has_history=has_history, regular_season_complete=regular_season_complete, postseason_complete=postseason_complete, draft_complete=draft_complete, blocking_count=blocking_count, next_game_id=next_game_id)
    games_value = f"{completed_games:,} / {scheduled_games:,}" if scheduled_games else "Offseason"
    inbox_value = f"{blocking_count} waiting" if blocking_count else "Clear"
    if blocking_count:
        next_value = "Decision inbox"
    elif phase_name == "offseason" and not has_history and not regular_season_complete and not postseason_complete:
        next_value = "Season opener"
    elif not regular_season_complete:
        next_value = "Game Day" if next_game_id else "Command Center"
    elif not postseason_complete:
        next_value = "Playoffs"
    elif phase_name == "offseason" and not draft_complete:
        next_value = "Free Agency"
    else:
        next_value = "Next season"
    display_team = team_name or active_team or "Your franchise"
    display_season = season_label or "Current season"
    st.markdown(
        f'''<div class="fm2-hud"><div class="fm2-hud-head"><div class="fm2-hud-team">{_logo_html(team_logo_url, class_name="fm2-hud-logo")}<div>
        <div class="fm2-kicker-row"><span class="fm2-live-dot"></span><span class="fm2-eyebrow">Season control</span></div><div class="fm2-hud-title">{html.escape(display_team)} · {html.escape(display_season)}</div><div class="fm2-hud-sub">One clear route from opening night to the next season.</div></div></div>
        <div class="fm2-hud-stats"><span class="fm2-hud-stat">LEAGUE GAMES <strong>{html.escape(games_value)}</strong></span><span class="fm2-hud-stat">INBOX <strong>{html.escape(inbox_value)}</strong></span></div></div>
        <div class="fm2-track-wrap"><div class="fm2-track"><div class="fm2-track-fill" style="width:{fill * 100:.1f}%"></div></div><div class="fm2-nodes">{nodes}</div></div>
        <div class="fm2-action-grid"><div class="fm2-next"><div class="fm2-eyebrow">Recommended next action</div><div class="fm2-next-title">{html.escape(title)}</div><div class="fm2-next-copy">{html.escape(copy)}</div></div>
        <div class="fm2-signals"><div class="fm2-signal"><div class="fm2-signal-icon">📥</div><div class="fm2-signal-label">Decisions</div><div class="fm2-signal-value">{html.escape(inbox_value)}</div></div><div class="fm2-signal"><div class="fm2-signal-icon">🏀</div><div class="fm2-signal-label">Progress</div><div class="fm2-signal-value">{html.escape(games_value)}</div></div><div class="fm2-signal"><div class="fm2-signal-icon">➡️</div><div class="fm2-signal-label">Up next</div><div class="fm2-signal-value">{html.escape(next_value)}</div></div></div></div></div>''',
        unsafe_allow_html=True,
    )
    cols = st.columns([1.15, 1.0, 2.4])
    with cols[0]:
        _nav_button(button, target, set_section, key=f"franchise_next_action_v2::{target}", primary=True)
    with cols[1]:
        _nav_button("Manage roster", "Team Management", set_section, key="franchise_quick_roster_v2")
    cols[2].caption("Nothing advances time until you explicitly simulate, commit a franchise game, advance the offseason calendar, or open the next season.")


def _tutorial_slide(step: int, *, active_team: str, team_name: str) -> tuple[str, str, str]:
    display_team = html.escape(team_name or active_team)
    if step == 0:
        return "Welcome to your front office", f"Take control of {display_team} without learning every screen today.", '''<div class="fm2-feature"><div class="fm2-eyebrow">Your only job right now</div><div class="fm2-feature-title">Follow the highlighted next action.</div><div class="fm2-feature-copy">The Season Control panel always shows where the league is, what is blocking progress, and the safest button to press next. Explore at your own pace—the simulator will warn you before league time moves.</div></div><div class="fm2-tip">💡 You can replay this tour at any time from <strong>Guidance → How to play</strong> in the sidebar.</div>'''
    if step == 1:
        return "The franchise loop", "Four beats are enough to understand an entire season.", '''<div class="fm2-loop"><div class="fm2-mini"><div class="fm2-mini-icon">👥</div><div class="fm2-mini-name">1 · Build</div><div class="fm2-mini-copy">Set a rotation, evaluate the roster, and decide your team identity.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🏀</div><div class="fm2-mini-name">2 · Play</div><div class="fm2-mini-copy">Control key games or simulate days, weeks, and longer stretches.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🔄</div><div class="fm2-mini-name">3 · Improve</div><div class="fm2-mini-copy">Use trades, staff, health, and performance data to adjust.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🏆</div><div class="fm2-mini-name">4 · Reload</div><div class="fm2-mini-copy">Navigate playoffs, free agency, the draft, and a new season.</div></div></div><div class="fm2-tip">The glowing node in Season Control is your current stage. Completed stages turn green.</div>'''
    if step == 2:
        return "Know what every click can do", "A simple traffic-light system keeps experimentation safe.", '''<div class="fm2-safety"><div class="fm2-mini safe"><div class="fm2-mini-icon">🟢</div><div class="fm2-mini-name">Safe to explore</div><div class="fm2-mini-copy">Viewing rosters, stats, standings, schedules, health, and scouting never advances time.</div></div><div class="fm2-mini confirm"><div class="fm2-mini-icon">🟡</div><div class="fm2-mini-name">Changes your team</div><div class="fm2-mini-copy">Rotations, trades, signings, staff moves, and draft picks only apply when confirmed.</div></div><div class="fm2-mini time"><div class="fm2-mini-icon">🔴</div><div class="fm2-mini-name">Advances the universe</div><div class="fm2-mini-copy">Simulation, committed games, offseason advancement, and season transitions move league time.</div></div></div><div class="fm2-tip">Every section header repeats the relevant risk label, so you never have to memorize this.</div>'''
    if step == 3:
        return "Start scouting immediately", "Your next Draft class is already waiting for your front office.", '''<div class="fm2-discovery"><div class="fm2-mini"><div class="fm2-mini-icon">🔎</div><div class="fm2-mini-name">Build your board</div><div class="fm2-mini-copy">Open Draft during the regular season to see the next class, assign priority prospects, and advance scouting weeks.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🎯</div><div class="fm2-mini-name">Manage uncertainty</div><div class="fm2-mini-copy">Scouted OVR and POT are estimates. Confidence improves with attention, but hidden ratings never become perfectly known.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🧑‍💼</div><div class="fm2-mini-name">Your scout matters</div><div class="fm2-mini-copy">The Staff tab shows your lead scout, expected error bands, specialties, contract, hiring market, and historical accuracy.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">📈</div><div class="fm2-mini-name">Learn from results</div><div class="fm2-mini-copy">After each Draft, scouting reports are graded so you can see OVR/POT error and decide whether your scout deserves another year.</div></div></div><div class="fm2-tip">Scouting is safe to do immediately. Advancing a scouting week improves information but does not simulate NBA games.</div>'''
    return "Choose how you want to begin", "There is no wrong first move—and you can leave every default in place.", '''<div class="fm2-discovery"><div class="fm2-mini"><div class="fm2-mini-icon">👥</div><div class="fm2-mini-name">Set the rotation</div><div class="fm2-mini-copy">Choose starters, minutes, and player availability in Team Management.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🔄</div><div class="fm2-mini-name">Explore a trade</div><div class="fm2-mini-copy">Search realistic offers and inspect the impact before committing anything.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🏀</div><div class="fm2-mini-name">Prepare Game Day</div><div class="fm2-mini-copy">See the matchup, choose a strategy, and play when the schedule is active.</div></div><div class="fm2-mini"><div class="fm2-mini-icon">🎛️</div><div class="fm2-mini-name">Trust the defaults</div><div class="fm2-mini-copy">Go straight to the recommended action and let the front office evolve naturally.</div></div></div><div class="fm2-tip">Your save is automatic. Come back later and the Command Center will orient you again.</div>'''


def render_first_time_tutorial_v1(*, active_team: str, set_section, team_name: str = "", team_logo_url: str = "", persist_preferences=None) -> None:
    # TUTORIAL_PREFERENCE_CALLBACK_COMPAT_V1_0_1
    # The current Franchise page supplies this UI-only callback.
    # V1.0.1 accepts it without making tutorial rendering depend on persistence.
    import streamlit as st
    st.session_state.setdefault("franchise_tutorial_open_v1", True)
    st.session_state.setdefault("franchise_tutorial_step_v2", 0)
    if not st.session_state.get("franchise_tutorial_open_v1", True):
        return
    step = max(0, min(4, int(st.session_state.get("franchise_tutorial_step_v2", 0))))
    title, subtitle, body = _tutorial_slide(step, active_team=active_team, team_name=team_name)
    progress = "".join(f'<span class="{"on" if i <= step else ""}"></span>' for i in range(5))
    st.markdown(
        f'''<div class="fm2-wizard"><div class="fm2-wizard-head"><div class="fm2-wizard-brand">{_logo_html(team_logo_url, class_name="fm2-wizard-logo")}<div><div class="fm2-eyebrow">Rookie GM walkthrough</div><h2>{html.escape(title)}</h2><p>{subtitle}</p></div></div><div class="fm2-wizard-count">{step + 1} of 5</div></div><div class="fm2-wizard-progress">{progress}</div>{body}</div>''',
        unsafe_allow_html=True,
    )
    if step < 4:
        back_col, next_col, skip_col = st.columns([0.8, 1.15, 2.0])
        if back_col.button("← Back", width="stretch", disabled=step == 0, key=f"franchise_tutorial_back_v2_{step}"):
            st.session_state["franchise_tutorial_step_v2"] = step - 1
            st.rerun()
        if next_col.button("Next lesson →", width="stretch", type="primary", key=f"franchise_tutorial_next_v2_{step}"):
            st.session_state["franchise_tutorial_step_v2"] = step + 1
            st.rerun()
        if step == 3:
            if skip_col.button("Open Draft scouting now", width="stretch", key="franchise_tutorial_open_scouting_v1"):
                st.session_state["franchise_tutorial_open_v1"] = False
                set_section("Draft Room")
                st.rerun()
        elif skip_col.button("Skip — I’ll explore on my own", width="stretch", key=f"franchise_tutorial_skip_v2_{step}"):
            st.session_state["franchise_tutorial_open_v1"] = False
            st.rerun()
        return
    start, scout_col, roster, trade, game = st.columns([1.25, 1.0, 1.0, 1.0, 1.0])
    if start.button("Start managing", type="primary", width="stretch", key="franchise_tutorial_finish_v2"):
        st.session_state["franchise_tutorial_open_v1"] = False
        st.rerun()
    if scout_col.button("Start scouting", width="stretch", key="franchise_tutorial_scout_v1"):
        st.session_state["franchise_tutorial_open_v1"] = False
        set_section("Draft Room")
        st.rerun()
    if roster.button("Set rotation", width="stretch", key="franchise_tutorial_roster_v2"):
        st.session_state["franchise_tutorial_open_v1"] = False
        set_section("Team Management")
        st.rerun()
    if trade.button("Explore trades", width="stretch", key="franchise_tutorial_trade_v2"):
        st.session_state["franchise_tutorial_open_v1"] = False
        set_section("Trade Center")
        st.rerun()
    if game.button("Open Game Day", width="stretch", key="franchise_tutorial_game_v2"):
        st.session_state["franchise_tutorial_open_v1"] = False
        set_section("Game Day")
        st.rerun()


# Backward-compatible alias for early V1 callers.
render_progress_coach_v1 = render_franchise_progress_coach_v1
