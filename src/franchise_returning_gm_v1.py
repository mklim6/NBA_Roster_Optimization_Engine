from __future__ import annotations

import html
from typing import Any, Callable


RETURNING_GM_VERSION = "franchise-returning-gm-v1.1-progression-clarity-2026-09-16"
RETENTION_SNAPSHOT_KEY = "franchise_retention_snapshot_v1"
SESSION_CHANGES_KEY = "_franchise_returning_gm_changes_v1"
SESSION_INITIALIZED_KEY = "_franchise_returning_gm_initialized_v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).lower()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict_or_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _transaction_count(state: Any, trade_state: Any, team: str) -> int:
    resolved = _text(team).upper()
    history = list(getattr(state, "franchise_transaction_history_v1", []) or [])
    if not history:
        history = list(getattr(trade_state, "transaction_history", []) or [])
    trades = sum(
        1 for item in history
        if resolved in {
            _text(_dict_or_attr(item, "team_a", "")).upper(),
            _text(_dict_or_attr(item, "team_b", "")).upper(),
            _text(_dict_or_attr(item, "team_abbreviation", "")).upper(),
        }
    )
    signings = sum(
        1
        for item in list(getattr(state, "free_agency_transaction_history", []) or [])
        if _text(_dict_or_attr(item, "team_abbreviation", _dict_or_attr(item, "team", ""))).upper() == resolved
    )
    return trades + signings


def _championships(state: Any, team: str) -> int:
    resolved = _text(team).upper()
    return sum(
        1
        for archive in list(getattr(state, "season_history", []) or [])
        if _text(_dict_or_attr(archive, "champion", "")).upper() == resolved
    )


def _roster_profile(state: Any, team: str) -> dict[str, int]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    roster = tuple(getattr(team_state, "roster_player_ids", ()) or ())
    players = getattr(state, "players", {}) or {}
    young = sum(
        1 for pid in roster
        if 0 < _number(getattr(players.get(pid), "age", 0)) <= 24
    )
    return {"roster_count": len(roster), "young_core": young}


def _milestone_names(state: Any, snapshot: Any, team: str, moves: int) -> list[str]:
    wins = int(getattr(snapshot, "wins", 0) or 0)
    losses = int(getattr(snapshot, "losses", 0) or 0)
    games = wins + losses
    seasons = len(list(getattr(state, "season_history", []) or []))
    championships = _championships(state, team)
    names = []
    if games >= 1:
        names.append("Tip-Off")
    if wins >= 1:
        names.append("First Win")
    if moves >= 1:
        names.append("Deal Maker")
    if seasons >= 1:
        names.append("Seasoned")
    if championships >= 1:
        names.append("Champion")
    return names


def _current_snapshot(state: Any, trade_state: Any, snapshot: Any, team: str) -> dict[str, Any]:
    profile = _roster_profile(state, team)
    wins = int(getattr(snapshot, "wins", 0) or 0)
    losses = int(getattr(snapshot, "losses", 0) or 0)
    moves = _transaction_count(state, trade_state, team)
    return {
        "version": 1,
        "team": _text(team).upper(),
        "season": _text(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": _enum(getattr(state, "phase", "")),
        "wins": wins,
        "losses": losses,
        "games": wins + losses,
        "moves": moves,
        "roster_count": profile["roster_count"],
        "young_core": profile["young_core"],
        "championships": _championships(state, team),
        "milestones": _milestone_names(state, snapshot, team, moves),
    }


def returning_changes(previous: Any, current: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(previous, dict):
        return [{
            "kind": "baseline",
            "title": "Return tracking is active",
            "detail": "This visit establishes the baseline for your next fresh Franchise session.",
        }]
    if _text(previous.get("team")).upper() != _text(current.get("team")).upper():
        return [{
            "kind": "baseline",
            "title": "New team baseline",
            "detail": "Return tracking reset for the currently controlled franchise.",
        }]

    changes: list[dict[str, str]] = []
    if _text(previous.get("season")) != _text(current.get("season")):
        changes.append({
            "kind": "major",
            "title": f"Season advanced to {_text(current.get('season'))}",
            "detail": f"Previous snapshot: {_text(previous.get('season')) or 'unknown season'}.",
        })
    if _text(previous.get("phase")) != _text(current.get("phase")):
        changes.append({
            "kind": "major",
            "title": f"Phase changed to {_text(current.get('phase')).replace('_', ' ').title()}",
            "detail": "The franchise lifecycle moved forward since your last remembered visit.",
        })

    wd = int(current.get("wins", 0)) - int(previous.get("wins", 0))
    ld = int(current.get("losses", 0)) - int(previous.get("losses", 0))
    if wd > 0 or ld > 0:
        changes.append({
            "kind": "result",
            "title": f"{wd}-{ld} since your last visit",
            "detail": f"Current record: {int(current.get('wins', 0))}-{int(current.get('losses', 0))}.",
        })

    md = int(current.get("moves", 0)) - int(previous.get("moves", 0))
    if md > 0:
        changes.append({
            "kind": "move",
            "title": f"{md} new roster move{'s' if md != 1 else ''}",
            "detail": f"Transaction count is now {int(current.get('moves', 0))}.",
        })

    rd = int(current.get("roster_count", 0)) - int(previous.get("roster_count", 0))
    if rd:
        changes.append({
            "kind": "roster",
            "title": f"Roster {'grew' if rd > 0 else 'shrunk'} by {abs(rd)}",
            "detail": f"Current roster size: {int(current.get('roster_count', 0))}.",
        })

    cd = int(current.get("championships", 0)) - int(previous.get("championships", 0))
    if cd > 0:
        changes.append({
            "kind": "major",
            "title": "Championship added to the résumé",
            "detail": f"Franchise titles increased by {cd}.",
        })

    old_badges = set(previous.get("milestones", []) or [])
    new_badges = [x for x in (current.get("milestones", []) or []) if x not in old_badges]
    if new_badges:
        changes.append({
            "kind": "milestone",
            "title": "New milestone unlocked",
            "detail": ", ".join(new_badges[:4]),
        })

    if not changes:
        changes.append({
            "kind": "steady",
            "title": "Your universe is exactly where you left it",
            "detail": "No durable franchise changes were detected since the last local snapshot.",
        })
    return changes[:4]


def gm_career_profile(*, wins: int, games: int, moves: int, seasons: int, championships: int, milestones: int) -> dict[str, Any]:
    xp = wins * 4 + (games // 10) * 6 + moves * 12 + seasons * 90 + championships * 450 + milestones * 30
    levels = (
        (0, "Rookie GM"),
        (90, "Front Office Operator"),
        (220, "Team Builder"),
        (450, "Executive"),
        (800, "Championship Architect"),
        (1300, "Dynasty Builder"),
    )
    index = 0
    for i, (threshold, _name) in enumerate(levels):
        if xp >= threshold:
            index = i
    threshold, label = levels[index]
    if index + 1 < len(levels):
        next_threshold, next_label = levels[index + 1]
        progress = max(0.0, min(1.0, (xp - threshold) / max(1, next_threshold - threshold)))
        next_copy = f"{next_label} at {next_threshold} XP"
    else:
        progress = 1.0
        next_copy = "Max front-office tier"
    xp_sources = {
        "wins": wins * 4,
        "games": (games // 10) * 6,
        "moves": moves * 12,
        "legacy": seasons * 90 + championships * 450 + milestones * 30,
    }
    return {
        "xp": xp,
        "label": label,
        "level": index + 1,
        "progress": progress,
        "next_copy": next_copy,
        "xp_sources": xp_sources,
    }


def franchise_identity(path: str, *, young_core: int, wins: int, losses: int, moves: int) -> tuple[str, str]:
    if path == "Builder":
        return (
            "Development Program" if young_core >= 4 else "Foundation Builder",
            "Youth, reps and long-term roster value define the current front-office identity.",
        )
    if path == "Win Now":
        return (
            "Contender Push" if wins > losses else "Pressure Season",
            "The mandate is to convert current talent into results immediately.",
        )
    if path == "Deal Maker":
        return (
            "Transaction Lab" if moves >= 3 else "Market Hunter",
            "Trades and free agency are the primary tools shaping this roster.",
        )
    return (
        "Balanced Ascender" if young_core >= 3 and wins >= losses else "Balanced Build",
        "Development, winning and flexibility are being managed together.",
    )


def _gm_path_copy_v1(path: str) -> str:
    return {
        "Builder": "Youth, development and long-term roster value.",
        "Win Now": "Immediate wins and maximizing the current roster.",
        "Deal Maker": "Aggressive improvement through trades and free agency.",
        "Balanced": "Results, continuity and flexibility together.",
    }.get(path, "Results, continuity and flexibility together.")


def inject_returning_gm_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st
    st.markdown(
        f"""
<style>
/* FRANCHISE_RETURNING_GM_V1 */
.frg-shell{{--frg-primary:{primary};--frg-secondary:{secondary};display:grid;grid-template-columns:1.18fr .82fr;gap:10px;margin:10px 0 16px}}
.frg-panel{{padding:14px;border:1px solid rgba(255,255,255,.075);border-radius:16px;background:rgba(255,255,255,.018)}}
.frg-title{{color:#eef6ff;font-size:.82rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}
.frg-copy{{margin-top:3px;color:#7f90a6;font-size:.64rem}}
.frg-change-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:10px}}
.frg-change{{padding:10px 11px;border-radius:11px;border:1px solid rgba(255,255,255,.06);background:#0a1420}}
.frg-change.major,.frg-change.milestone{{border-color:color-mix(in srgb,var(--frg-primary) 34%,rgba(255,255,255,.08));background:color-mix(in srgb,var(--frg-primary) 7%,#0a1420)}}
.frg-change b{{display:block;color:#eef6ff;font-size:.66rem}}.frg-change span{{display:block;margin-top:4px;color:#8395aa;font-size:.57rem;line-height:1.42}}
.frg-rank{{margin-top:8px;color:#fff;font-size:1.08rem;font-weight:950}}.frg-xp{{margin-top:3px;color:#89a0b9;font-size:.6rem}}
.frg-bar{{height:6px;margin:9px 0 8px;border-radius:999px;background:rgba(255,255,255,.065);overflow:hidden}}.frg-bar span{{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#22d3ee,var(--frg-primary),var(--frg-secondary))}}
.frg-identity{{margin-top:10px;padding:10px 11px;border-radius:11px;background:#0a1420;border:1px solid rgba(255,255,255,.06)}}
.frg-identity small{{display:block;color:#74879d;font-size:.5rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}}.frg-identity strong{{display:block;margin-top:4px;color:#fff;font-size:.74rem}}.frg-identity span{{display:block;margin-top:4px;color:#8597ab;font-size:.57rem;line-height:1.4}}
.frg-rank-label{{margin-top:8px;color:#6ee7b7;font-size:.5rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}}
.frg-level-row{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}.frg-level{{color:#7dd3fc;font-size:.58rem;font-weight:950;letter-spacing:.08em;text-transform:uppercase}}
.frg-path{{margin-top:9px;padding:10px 11px;border-radius:11px;background:color-mix(in srgb,var(--frg-primary) 7%,#0a1420);border:1px solid color-mix(in srgb,var(--frg-primary) 25%,rgba(255,255,255,.06))}}
.frg-path small{{display:block;color:#7dd3fc;font-size:.48rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}.frg-path strong{{display:block;margin-top:3px;color:#fff;font-size:.73rem}}.frg-path span{{display:block;margin-top:3px;color:#8396aa;font-size:.55rem;line-height:1.35}}
.frg-xp-sources{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;margin-top:9px}}.frg-xp-source{{padding:7px;border-radius:9px;background:#09131f;border:1px solid rgba(255,255,255,.055)}}.frg-xp-source small{{display:block;color:#6f8298;font-size:.43rem;font-weight:950;text-transform:uppercase}}.frg-xp-source b{{display:block;margin-top:2px;color:#dbeafe;font-size:.58rem}}
.frg-rank-note{{margin-top:6px;color:#6f8195;font-size:.5rem}}
@media(max-width:1050px){{.frg-shell{{grid-template-columns:1fr}}}}@media(max-width:650px){{.frg-change-grid{{grid-template-columns:1fr}}.frg-xp-sources{{grid-template-columns:repeat(2,1fr)}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_returning_gm_v1(
    *,
    state: Any,
    trade_state: Any,
    snapshot: Any,
    active_team: str,
    persist_ui_preferences: Callable[[], None] | None = None,
) -> None:
    import streamlit as st

    if st.session_state.get("franchise_tutorial_open_v1", True):
        return

    team = _text(active_team).upper()
    current = _current_snapshot(state, trade_state, snapshot, team)

    if SESSION_INITIALIZED_KEY not in st.session_state:
        previous = st.session_state.get(RETENTION_SNAPSHOT_KEY)
        st.session_state[SESSION_CHANGES_KEY] = returning_changes(previous, current)
        st.session_state[SESSION_INITIALIZED_KEY] = True

    if st.session_state.get(RETENTION_SNAPSHOT_KEY) != current:
        st.session_state[RETENTION_SNAPSHOT_KEY] = current
        if persist_ui_preferences is not None:
            persist_ui_preferences()

    changes = list(st.session_state.get(SESSION_CHANGES_KEY, []) or [])
    path = _text(st.session_state.get("franchise_gm_path_v1", "Balanced")) or "Balanced"
    seasons = len(list(getattr(state, "season_history", []) or []))
    career = gm_career_profile(
        wins=int(current["wins"]),
        games=int(current["games"]),
        moves=int(current["moves"]),
        seasons=seasons,
        championships=int(current["championships"]),
        milestones=len(current["milestones"]),
    )
    identity_name, identity_copy = franchise_identity(
        path,
        young_core=int(current["young_core"]),
        wins=int(current["wins"]),
        losses=int(current["losses"]),
        moves=int(current["moves"]),
    )
    path_copy = _gm_path_copy_v1(path)
    xp_sources = career["xp_sources"]

    change_html = "".join(
        (
            f'<div class="frg-change {html.escape(_text(item.get("kind", "steady")))}">'
            f'<b>{html.escape(_text(item.get("title")))}</b>'
            f'<span>{html.escape(_text(item.get("detail")))}</span></div>'
        )
        for item in changes
    )

    st.markdown(
        f"""<div class="frg-shell"><div class="frg-panel"><div class="frg-title">Since your last visit</div>
        <div class="frg-copy">Compared with the last locally remembered Franchise snapshot.</div>
        <div class="frg-change-grid">{change_html}</div></div>
        <div class="frg-panel">
        <div class="frg-title">Front office progression</div>
        <div class="frg-rank-label">Career rank</div>
        <div class="frg-level-row"><div class="frg-rank">{html.escape(career["label"])}</div><div class="frg-level">Level {career["level"]}</div></div>
        <div class="frg-xp">{career["xp"]} XP · {html.escape(career["next_copy"])}</div>
        <div class="frg-bar"><span style="width:{career["progress"] * 100:.0f}%"></span></div>
        <div class="frg-rank-note">Career rank is independent from your selected GM challenge path.</div>
        <div class="frg-xp-sources">
          <div class="frg-xp-source"><small>Wins</small><b>+{xp_sources["wins"]} XP</b></div>
          <div class="frg-xp-source"><small>Games</small><b>+{xp_sources["games"]} XP</b></div>
          <div class="frg-xp-source"><small>Moves</small><b>+{xp_sources["moves"]} XP</b></div>
          <div class="frg-xp-source"><small>Legacy</small><b>+{xp_sources["legacy"]} XP</b></div>
        </div>
        <div class="frg-path"><small>Selected GM challenge path</small><strong>{html.escape(path)}</strong><span>{html.escape(path_copy)}</span></div>
        <div class="frg-identity"><small>Franchise identity</small><strong>{html.escape(identity_name)}</strong>
        <span>{html.escape(identity_copy)}</span></div></div></div>""",
        unsafe_allow_html=True,
    )
