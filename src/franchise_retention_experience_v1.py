from __future__ import annotations

import html
import re
from typing import Any, Callable


FRANCHISE_RETENTION_EXPERIENCE_VERSION = "franchise-retention-experience-v1.1.1-quest-lifecycle-hotfix-2026-09-16"

GM_PATHS = ("Balanced", "Builder", "Win Now", "Deal Maker")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).lower()


def _dict_or_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _headshot_url(player_id: str, fallback: str) -> str:
    resolved = _text(player_id)
    if re.fullmatch(r"\d+", resolved):
        return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{resolved}.png"
    return fallback


def _team_transaction_counts(state: Any, trade_state: Any, team: str) -> tuple[int, int]:
    resolved = _text(team).upper()
    trade_history = list(getattr(state, "franchise_transaction_history_v1", []) or [])
    if not trade_history:
        trade_history = list(getattr(trade_state, "transaction_history", []) or [])
    trades = sum(
        1
        for item in trade_history
        if resolved in {
            _text(_dict_or_attr(item, "team_a", "")).upper(),
            _text(_dict_or_attr(item, "team_b", "")).upper(),
            _text(_dict_or_attr(item, "team_abbreviation", "")).upper(),
        }
    )
    signings = sum(
        1
        for item in list(getattr(state, "free_agency_transaction_history", []) or [])
        if _text(_dict_or_attr(item, "team_abbreviation", _dict_or_attr(item, "team", ""))).upper()
        == resolved
    )
    return trades, signings


def _team_game_rows(state: Any, team: str) -> list[tuple[int, Any]]:
    resolved = _text(team).upper()
    schedule = getattr(state, "schedule", {}) or {}
    rows: list[tuple[int, Any]] = []
    for game_id, game in (getattr(state, "completed_games", {}) or {}).items():
        home = _text(getattr(game, "home_team", "")).upper()
        away = _text(getattr(game, "away_team", "")).upper()
        if resolved not in {home, away}:
            continue
        scheduled = schedule.get(game_id)
        day_index = int(getattr(scheduled, "day_index", len(rows)) or 0)
        rows.append((day_index, game))
    rows.sort(key=lambda item: item[0])
    return rows


def _recent_form(state: Any, team: str) -> tuple[int, int, float, str]:
    resolved = _text(team).upper()
    recent = _team_game_rows(state, resolved)[-5:]
    wins = 0
    margin = 0
    latest = "No completed games yet"
    for _, game in recent:
        home = _text(getattr(game, "home_team", "")).upper()
        home_score = int(getattr(game, "home_score", 0) or 0)
        away_score = int(getattr(game, "away_score", 0) or 0)
        team_score = home_score if home == resolved else away_score
        opponent_score = away_score if home == resolved else home_score
        wins += int(team_score > opponent_score)
        margin += team_score - opponent_score
    if recent:
        game = recent[-1][1]
        home = _text(getattr(game, "home_team", "")).upper()
        away = _text(getattr(game, "away_team", "")).upper()
        home_score = int(getattr(game, "home_score", 0) or 0)
        away_score = int(getattr(game, "away_score", 0) or 0)
        opponent = away if home == resolved else home
        team_score = home_score if home == resolved else away_score
        opponent_score = away_score if home == resolved else home_score
        latest = f"{'W' if team_score > opponent_score else 'L'} {team_score}-{opponent_score} vs {opponent}"
    return wins, len(recent) - wins, margin / len(recent) if recent else 0.0, latest


def _roster_profile(state: Any, team: str) -> dict[str, Any]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    roster = tuple(getattr(team_state, "roster_player_ids", ()) or ())
    rotation = getattr(team_state, "rotation", None)
    rotation_ids = tuple(getattr(rotation, "rotation_player_ids", ()) or ())
    minutes = getattr(rotation, "minutes_targets", {}) or {}
    rotation_ready = bool(rotation_ids) and sum(_safe_number(value) for value in minutes.values()) >= 230
    players = getattr(state, "players", {}) or {}
    young_core = sum(
        1
        for player_id in roster
        if 0 < _safe_number(getattr(players.get(player_id), "age", 0)) <= 24
    )
    unavailable_statuses = {"out", "doubtful"}
    unavailable = 0
    for player_id in roster:
        injury = (getattr(state, "injuries", {}) or {}).get(player_id)
        if _enum(getattr(injury, "status", "healthy")) in unavailable_statuses:
            unavailable += 1
    return {
        "roster": roster,
        "roster_count": len(roster),
        "rotation_count": len(rotation_ids),
        "rotation_ready": rotation_ready,
        "young_core": young_core,
        "unavailable": unavailable,
    }


def _featured_player(state: Any, team: str, logo_url: str) -> dict[str, Any]:
    profile = _roster_profile(state, team)
    players = getattr(state, "players", {}) or {}
    totals = getattr(state, "player_season_totals", {}) or {}
    candidates: list[tuple[float, float, str, Any]] = []
    for player_id in profile["roster"]:
        player = players.get(player_id)
        if player is None:
            continue
        total = totals.get(player_id)
        games = int(getattr(total, "games_played", 0) or 0)
        ppg = _safe_number(getattr(total, "points", 0)) / games if games else 0.0
        overall = _safe_number(getattr(player, "overall_rating", 0))
        candidates.append((ppg if games else overall, overall, player_id, player))
    if not candidates:
        return {"name": "Your franchise", "detail": "Build a new team identity", "image": logo_url}
    _, overall, player_id, player = max(candidates)
    total = totals.get(player_id)
    games = int(getattr(total, "games_played", 0) or 0)
    detail = (
        f"{_safe_number(getattr(total, 'points', 0)) / games:.1f} PPG · {games} GP"
        if games
        else f"{overall:.0f} OVR · {_text(getattr(player, 'position', '')) or 'Core player'}"
    )
    return {
        "name": _text(getattr(player, "player_name", player_id)),
        "detail": detail,
        "image": _headshot_url(player_id, logo_url),
    }


def _championship_count(state: Any, team: str) -> int:
    resolved = _text(team).upper()
    return sum(
        1
        for archive in list(getattr(state, "season_history", []) or [])
        if _text(_dict_or_attr(archive, "champion", "")).upper() == resolved
    )


def _objective(title: str, detail: str, current: int, target: int, reward: str) -> dict[str, Any]:
    safe_target = max(1, int(target))
    safe_current = max(0, int(current))
    return {
        "title": title,
        "detail": detail,
        "current": safe_current,
        "target": safe_target,
        "progress": min(1.0, safe_current / safe_target),
        "complete": safe_current >= safe_target,
        "reward": reward,
    }


def _goal_set(
    *,
    phase: str,
    history_count: int,
    games: int,
    wins: int,
    moves: int,
    profile: dict[str, Any],
    path: str,
) -> list[dict[str, Any]]:
    phase = _text(phase).strip().lower()
    games = max(0, int(games))
    wins = max(0, int(wins))
    moves = max(0, int(moves))
    history_count = max(0, int(history_count))
    roster_count = max(0, int(profile.get("roster_count", 0) or 0))
    rotation_ready = bool(profile.get("rotation_ready", False))

    # The first-ever opening setup is the only offseason state where
    # "Open the season" is correct. Once games have actually been played,
    # an offseason belongs to the completed campaign and should guide the
    # user toward the NEXT roster rather than pretending opening night has
    # never happened.
    first_opening_setup = (
        phase == "offseason"
        and history_count == 0
        and games == 0
    )
    completed_regular_season = games >= 82

    if first_opening_setup:
        phase_goal = _objective(
            "Open the season",
            "Launch the certified regular-season schedule when your roster is ready.",
            0,
            1,
            "Tip-Off badge",
        )
        support_goal = _objective(
            "Set the opening rotation",
            "Save a legal rotation before opening night.",
            int(rotation_ready),
            1,
            "Prepared badge",
        )
    elif phase in {"regular_season", "preseason"}:
        if games < 10:
            phase_goal = _objective(
                "Build early rhythm",
                "Complete ten games with your current core.",
                games,
                10,
                "Rhythm badge",
            )
        else:
            phase_goal = _objective(
                "Finish the regular season",
                "Play through the full 82-game regular-season schedule.",
                games,
                82,
                "82-Game Road badge",
            )
        support_goal = _objective(
            "Earn five wins",
            "Turn individual results into visible momentum.",
            wins,
            5,
            "Winning Culture badge",
        )
    elif phase in {"play_in", "playoffs", "postseason"}:
        phase_goal = _objective(
            "Survive the postseason",
            "Keep advancing until the championship is decided.",
            0,
            1,
            "Playoff Run badge",
        )
        support_goal = _objective(
            "Bank a winning foundation",
            "Carry at least five regular-season wins into the postseason.",
            wins,
            5,
            "Winning Culture badge",
        )
    elif phase == "offseason" and (completed_regular_season or history_count > 0):
        phase_goal = _objective(
            "Build the next roster",
            "Reach a legal opening-night roster size for the next campaign.",
            min(roster_count, 14),
            14,
            "Roster Architect badge",
        )
        support_goal = _objective(
            "Set the next rotation",
            "Save a legal rotation for the roster you are building.",
            int(rotation_ready),
            1,
            "Prepared badge",
        )
    else:
        phase_goal = _objective(
            "Advance the franchise lifecycle",
            "Complete the current franchise phase and clear the next progression gate.",
            0,
            1,
            "Front Office badge",
        )
        support_goal = _objective(
            "Keep the rotation ready",
            "Maintain a legal saved rotation.",
            int(rotation_ready),
            1,
            "Prepared badge",
        )

    goals = [
        phase_goal,
        support_goal,
        _objective(
            "Shape the roster",
            "Complete a trade or free-agent signing.",
            moves,
            1,
            "Deal Maker badge",
        ),
    ]

    if path == "Builder":
        goals.append(
            _objective(
                "Build a young core",
                "Roster at least three players age 24 or younger.",
                profile["young_core"],
                3,
                "Youth Movement badge",
            )
        )
    elif path == "Win Now":
        if phase == "offseason" and (completed_regular_season or history_count > 0):
            goals.append(
                _objective(
                    "Prepare a winning rotation",
                    "Enter the next season with a legal rotation already saved.",
                    int(rotation_ready),
                    1,
                    "Contender badge",
                )
            )
        else:
            goals.append(
                _objective(
                    "Chase double-digit wins",
                    "Reach ten victories this season.",
                    wins,
                    10,
                    "Contender badge",
                )
            )
    elif path == "Deal Maker":
        goals.append(
            _objective(
                "Own the transaction wire",
                "Complete three franchise roster moves.",
                moves,
                3,
                "Market Master badge",
            )
        )
    else:
        if phase == "offseason" and (completed_regular_season or history_count > 0):
            goals.append(
                _objective(
                    "Balance the roster",
                    "Carry at least fourteen players into the next opening-night build.",
                    min(roster_count, 14),
                    14,
                    "Foundation badge",
                )
            )
        else:
            goals.append(
                _objective(
                    "Establish the franchise",
                    "Complete twenty team games.",
                    games,
                    20,
                    "Foundation badge",
                )
            )
    return goals


def _goal_card_html_v1(
    *,
    index: int,
    goal: dict[str, Any],
    is_current: bool,
) -> str:
    classes = "complete" if bool(goal.get("complete")) else ""
    if is_current:
        classes = (classes + " current").strip()

    current_badge = (
        '<div class="frx-goal-current">Next objective</div>'
        if is_current
        else ""
    )
    title = html.escape(_text(goal.get("title")))
    detail = html.escape(_text(goal.get("detail")))
    reward = html.escape(_text(goal.get("reward")))
    progress = max(0.0, min(1.0, float(goal.get("progress", 0.0) or 0.0)))
    current = max(0, int(goal.get("current", 0) or 0))
    target = max(1, int(goal.get("target", 1) or 1))
    state = "Complete" if bool(goal.get("complete")) else "Active"

    # Keep each card on ONE physical line. Streamlit's Markdown parser can
    # interpret four-space-indented HTML continuation lines as code blocks,
    # which was the source of the raw <div class=...> text seen in V1.1.
    return (
        f'<div class="frx-goal {classes}">'
        f'<div class="frx-goal-status"><span class="frx-goal-num">QUEST {index:02d}</span>'
        f'<span class="frx-goal-state">{state}</span></div>'
        f'{current_badge}'
        f'<div class="frx-goal-title">{title}</div>'
        f'<div class="frx-goal-copy">{detail}</div>'
        f'<div class="frx-bar"><span style="width:{progress * 100:.0f}%"></span></div>'
        f'<div class="frx-goal-foot"><span><strong>{min(current, target)}/{target}</strong></span>'
        f'<span>{progress * 100:.0f}%</span></div>'
        f'<div class="frx-goal-reward"><strong>REWARD</strong> · {reward}</div>'
        f'</div>'
    )


def _milestones(*, rotation_ready: bool, games: int, wins: int, moves: int, seasons: int, championships: int) -> list[tuple[str, str, bool]]:
    return [
        ("🧠", "Prepared", rotation_ready),
        ("🏀", "Tip-Off", games >= 1),
        ("🔥", "First Win", wins >= 1),
        ("🤝", "Deal Maker", moves >= 1),
        ("📚", "Seasoned", seasons >= 1),
        ("🏆", "Champion", championships >= 1),
    ]



def _milestone_display_rows(
    *,
    rotation_ready: bool,
    games: int,
    wins: int,
    moves: int,
    seasons: int,
    championships: int,
) -> list[dict[str, Any]]:
    return [
        {"icon": "🧠", "name": "Prepared", "unlocked": bool(rotation_ready),
         "requirement": "Save a legal opening rotation."},
        {"icon": "🏀", "name": "Tip-Off", "unlocked": games >= 1,
         "requirement": "Complete your first franchise game."},
        {"icon": "🔥", "name": "First Win", "unlocked": wins >= 1,
         "requirement": "Earn your first franchise victory."},
        {"icon": "🤝", "name": "Deal Maker", "unlocked": moves >= 1,
         "requirement": "Complete a trade or free-agent signing."},
        {"icon": "📚", "name": "Seasoned", "unlocked": seasons >= 1,
         "requirement": "Complete one full franchise season."},
        {"icon": "🏆", "name": "Champion", "unlocked": championships >= 1,
         "requirement": "Win an NBA championship."},
    ]


def _league_story(state: Any, team_name: Callable[[str], str]) -> tuple[str, str]:
    standings = list((getattr(state, "standings", {}) or {}).values())
    played = [row for row in standings if int(getattr(row, "games_played", 0) or 0) > 0]
    if not played:
        return "The league is level", "All 30 teams are still waiting to establish the first standings order."
    leader = max(
        played,
        key=lambda row: (
            int(getattr(row, "wins", 0) or 0) / max(1, int(getattr(row, "games_played", 0) or 0)),
            int(getattr(row, "wins", 0) or 0),
        ),
    )
    abbr = _text(getattr(leader, "team_abbreviation", ""))
    return "League pace setter", f"{team_name(abbr)} lead the early race at {int(getattr(leader, 'wins', 0) or 0)}-{int(getattr(leader, 'losses', 0) or 0)}."


def inject_franchise_retention_visuals_v1(*, primary: str, secondary: str) -> None:
    import streamlit as st

    st.markdown(
        f"""
<style>
/* FRANCHISE_RETENTION_EXPERIENCE_V1 */
.frx-shell{{--frx-primary:{primary};--frx-secondary:{secondary};position:relative;margin:1.05rem 0 1.2rem}}
.frx-brief{{position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(230px,.55fr);gap:12px;padding:20px;border:1px solid color-mix(in srgb,var(--frx-primary) 38%,rgba(255,255,255,.1));border-radius:21px;background:radial-gradient(circle at 85% 5%,color-mix(in srgb,var(--frx-secondary) 25%,transparent),transparent 38%),linear-gradient(130deg,color-mix(in srgb,var(--frx-primary) 15%,#09101a),rgba(7,12,20,.97));box-shadow:0 22px 54px rgba(0,0,0,.2)}}
.frx-brief:after{{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,#22d3ee,var(--frx-primary),var(--frx-secondary),transparent 82%)}}
.frx-brief-main,.frx-star{{position:relative;z-index:1}}.frx-overline{{color:#7dd3fc;font-size:.62rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}}
.frx-brief h2{{margin:.28rem 0 .45rem!important;font-size:1.42rem!important;color:#fff!important}}.frx-brief-copy{{max-width:760px;color:#a7b5c8;font-size:.79rem;line-height:1.5}}
.frx-brief-meta{{display:flex;gap:7px;flex-wrap:wrap;margin-top:14px}}.frx-meta{{padding:7px 9px;border-radius:9px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025);color:#cfdaea;font-size:.63rem;font-weight:800}}.frx-meta strong{{color:#fff}}
.frx-star{{display:flex;align-items:center;gap:10px;padding:11px;border:1px solid rgba(255,255,255,.09);border-radius:15px;background:rgba(255,255,255,.035)}}.frx-star img{{width:76px;height:76px;object-fit:cover;object-position:top;border-radius:12px;background:rgba(255,255,255,.04)}}.frx-star-name{{font-size:.8rem;font-weight:950;color:#fff}}.frx-star-detail{{margin-top:3px;color:#91a1b5;font-size:.63rem}}
.frx-section-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:18px 2px 10px}}.frx-section-title{{font-size:.82rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#eef6ff}}.frx-section-copy{{color:#7f90a6;font-size:.66rem}}
.frx-goals{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.frx-goal{{position:relative;overflow:hidden;min-height:154px;padding:13px;border:1px solid rgba(255,255,255,.075);border-radius:15px;background:linear-gradient(145deg,rgba(255,255,255,.038),rgba(255,255,255,.015))}}.frx-goal.complete{{border-color:rgba(52,211,153,.23);background:linear-gradient(145deg,rgba(52,211,153,.075),rgba(255,255,255,.012))}}
.frx-goal-status{{display:flex;align-items:center;justify-content:space-between;gap:6px}}.frx-goal-num{{color:#7dd3fc;font-size:.58rem;font-weight:950;letter-spacing:.09em}}.frx-goal-state{{padding:3px 5px;border-radius:999px;background:rgba(245,158,11,.1);color:#fde68a;font-size:.49rem;font-weight:900;text-transform:uppercase}}.frx-goal.complete .frx-goal-state{{background:rgba(52,211,153,.12);color:#86efac}}
.frx-goal-title{{margin:.55rem 0 .28rem;color:#fff;font-size:.79rem;font-weight:950}}.frx-goal-copy{{min-height:38px;color:#899aaf;font-size:.63rem;line-height:1.4}}.frx-bar{{height:5px;margin:10px 0 7px;border-radius:999px;background:rgba(255,255,255,.065);overflow:hidden}}.frx-bar span{{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#22d3ee,var(--frx-primary),var(--frx-secondary))}}.frx-goal-foot{{display:flex;justify-content:space-between;gap:8px;color:#718096;font-size:.54rem}}.frx-goal-foot strong{{color:#dbeafe}}
.frx-path-note{{margin:.55rem 0 .8rem;padding:9px 11px;border-left:3px solid var(--frx-primary);border-radius:0 10px 10px 0;background:color-mix(in srgb,var(--frx-primary) 8%,transparent);color:#9eafc2;font-size:.67rem}}
.st-key-franchise_gm_path_choice_v1 [role="radiogroup"]{{gap:.4rem!important;flex-wrap:wrap!important}}.st-key-franchise_gm_path_choice_v1 label{{padding:.45rem .75rem!important;border:1px solid rgba(255,255,255,.08)!important;border-radius:999px!important;background:rgba(255,255,255,.025)!important}}.st-key-franchise_gm_path_choice_v1 label:has(input:checked){{border-color:color-mix(in srgb,var(--frx-primary) 52%,white 10%)!important;background:color-mix(in srgb,var(--frx-primary) 22%,#101722)!important;box-shadow:0 8px 22px color-mix(in srgb,var(--frx-primary) 14%,transparent)}}
.frx-bottom{{display:grid;grid-template-columns:1.05fr 1.35fr;gap:10px;margin-top:9px}}.frx-cabinet,.frx-stories{{padding:14px;border:1px solid rgba(255,255,255,.075);border-radius:16px;background:rgba(255,255,255,.018)}}
.frx-badges{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}}.frx-badge{{padding:10px 6px;text-align:center;border:1px solid rgba(255,255,255,.06);border-radius:11px;background:rgba(255,255,255,.02);filter:grayscale(1);opacity:.38}}.frx-badge.on{{filter:none;opacity:1;border-color:color-mix(in srgb,var(--frx-primary) 30%,rgba(255,255,255,.1));background:color-mix(in srgb,var(--frx-primary) 8%,rgba(255,255,255,.02))}}.frx-badge-icon{{font-size:1.12rem}}.frx-badge-name{{margin-top:4px;color:#dbeafe;font-size:.54rem;font-weight:850}}
.frx-story-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}}.frx-story{{padding:11px;border:1px solid rgba(255,255,255,.065);border-radius:11px;background:rgba(255,255,255,.02)}}.frx-story-icon{{font-size:.95rem}}.frx-story-title{{margin:.35rem 0 .22rem;color:#fff;font-size:.68rem;font-weight:900}}.frx-story-copy{{color:#8293a8;font-size:.58rem;line-height:1.4}}
.frx-quest-summary{{display:grid;grid-template-columns:auto minmax(180px,1fr) auto;gap:12px;align-items:center;margin:10px 0;padding:12px 14px;border:1px solid rgba(255,255,255,.075);border-radius:14px;background:linear-gradient(110deg,color-mix(in srgb,var(--frx-primary) 9%,#09131f),#09131f)}}
.frx-quest-summary strong{{color:#fff;font-size:.92rem}}.frx-quest-summary small{{display:block;color:#708399;font-size:.51rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}}
.frx-quest-overall{{height:7px;border-radius:999px;background:rgba(255,255,255,.07);overflow:hidden}}.frx-quest-overall span{{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#22d3ee,var(--frx-primary),#34d399)}}
.frx-quest-next{{text-align:right;color:#91a4ba;font-size:.58rem}}.frx-quest-next b{{display:block;color:#f8fafc;font-size:.68rem}}
.frx-goal.current{{border-color:color-mix(in srgb,var(--frx-primary) 50%,rgba(255,255,255,.1));box-shadow:0 0 0 1px color-mix(in srgb,var(--frx-primary) 18%,transparent),0 12px 30px rgba(0,0,0,.16)}}
.frx-goal-current{{display:inline-flex;margin-top:8px;padding:3px 6px;border-radius:999px;background:color-mix(in srgb,var(--frx-primary) 15%,transparent);color:#bfdbfe;font-size:.48rem;font-weight:950;letter-spacing:.08em;text-transform:uppercase}}
.frx-goal-reward{{margin-top:6px;color:#a9bad0;font-size:.55rem}}.frx-goal-reward strong{{color:#f8fafc}}
.frx-milestone-summary{{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:9px;padding:9px 10px;border-radius:10px;background:#09141f;border:1px solid rgba(255,255,255,.06)}}
.frx-milestone-summary small{{color:#70849b;font-size:.49rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}.frx-milestone-summary strong{{display:block;margin-top:2px;color:#fff;font-size:.67rem}}
.frx-badges{{grid-template-columns:repeat(2,1fr)!important}}
.frx-badge{{padding:10px!important;text-align:left!important;display:grid;grid-template-columns:32px 1fr;gap:8px;align-items:center}}
.frx-badge-icon{{font-size:1.2rem!important;text-align:center}}.frx-badge-name{{text-align:left!important;font-size:.64rem!important;font-weight:950!important}}
.frx-badge-requirement{{margin-top:2px;color:#75879c;font-size:.51rem;line-height:1.35}}
.frx-badge-state{{margin-top:4px;color:#64748b;font-size:.46rem;font-weight:950;letter-spacing:.08em;text-transform:uppercase}}.frx-badge.on .frx-badge-state{{color:#6ee7b7}}
@media(max-width:1050px){{.frx-brief{{grid-template-columns:1fr}}.frx-goals{{grid-template-columns:repeat(2,1fr)}}.frx-bottom{{grid-template-columns:1fr}}}}
@media(max-width:650px){{.frx-brief{{padding:15px}}.frx-goals{{grid-template-columns:1fr}}.frx-story-grid{{grid-template-columns:1fr}}.frx-star img{{width:64px;height:64px}}}}
@media(prefers-reduced-motion:reduce){{.frx-bar span{{transition:none!important}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_franchise_retention_hub_v1(
    *,
    state: Any,
    trade_state: Any,
    snapshot: Any,
    active_team: str,
    checkpoint_saved_at: str | None,
    set_section,
    team_name_resolver: Callable[[str], str] | None = None,
    persist_gm_path: Callable[[], None] | None = None,
) -> None:
    import streamlit as st

    if st.session_state.get("franchise_tutorial_open_v1", True):
        return

    resolve_name = team_name_resolver or (lambda team: team)
    team = _text(active_team).upper()
    display_team = _text(getattr(snapshot, "team_name", "")) or resolve_name(team)
    logo_url = _text(getattr(snapshot, "logo_url", ""))
    phase = _enum(getattr(state, "phase", ""))
    season = _text(getattr(getattr(state, "settings", None), "season_label", ""))
    wins = int(getattr(snapshot, "wins", 0) or 0)
    losses = int(getattr(snapshot, "losses", 0) or 0)
    games = wins + losses
    seasons = len(list(getattr(state, "season_history", []) or []))
    if phase == "offseason" and games >= 82:
        seasons = max(seasons, 1)
    championships = _championship_count(state, team)
    trades, signings = _team_transaction_counts(state, trade_state, team)
    moves = trades + signings
    profile = _roster_profile(state, team)
    recent_wins, recent_losses, recent_margin, latest_result = _recent_form(state, team)
    star = _featured_player(state, team, logo_url)

    if phase == "offseason" and seasons == 0 and games == 0:
        headline = f"The {season} launchpad is ready."
        briefing = "Your roster, staff, transaction tools, free-agent market, and draft room are connected. Choose a challenge path, then open the season when the franchise feels like yours."
    elif phase == "offseason":
        headline = f"A new version of {display_team} is taking shape."
        briefing = "Review the season you just completed, attack the market, and leave the offseason with a clear identity for opening night."
    elif games == 0:
        headline = "Opening night is waiting."
        briefing = "Your first result will begin the story. Review the matchup or trust your rotation and let the season start moving."
    elif wins >= losses:
        headline = f"{display_team} are building momentum."
        briefing = f"The club is {wins}-{losses}, with a {recent_wins}-{recent_losses} mark over its latest five-game window. Decide whether to stay patient or turn momentum into a bigger move."
    else:
        headline = "The next decision can change the tone."
        briefing = f"The club is {wins}-{losses}. Use the latest results, player form, and roster tools to decide whether the answer is tactical or transactional."

    saved_copy = _text(checkpoint_saved_at).replace("T", " ")[:16] if checkpoint_saved_at else "Autosave active"
    st.markdown(
        f'''<div class="frx-shell"><div class="frx-brief"><div class="frx-brief-main">
        <div class="frx-overline">Welcome back, GM · Front office briefing</div><h2>{html.escape(headline)}</h2><div class="frx-brief-copy">{html.escape(briefing)}</div>
        <div class="frx-brief-meta"><span class="frx-meta">RECORD <strong>{wins}-{losses}</strong></span><span class="frx-meta">ROSTER <strong>{profile['roster_count']}</strong></span><span class="frx-meta">MOVES <strong>{moves}</strong></span><span class="frx-meta">SAVED <strong>{html.escape(saved_copy)}</strong></span></div></div>
        <div class="frx-star"><img src="{html.escape(star['image'], quote=True)}" alt="{html.escape(star['name'], quote=True)}"><div><div class="frx-overline">Franchise face</div><div class="frx-star-name">{html.escape(star['name'])}</div><div class="frx-star-detail">{html.escape(star['detail'])}</div></div></div></div></div>''',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="frx-section-head"><div><div class="frx-section-title">Choose your GM challenge path</div><div class="frx-section-copy">This changes your featured objective—not simulation results.</div></div></div>', unsafe_allow_html=True)
    persistent_path_key = "franchise_gm_path_v1"
    widget_path_key = "franchise_gm_path_choice_v1"
    saved_path = _text(st.session_state.get(persistent_path_key, "Balanced"))
    if saved_path not in GM_PATHS:
        saved_path = "Balanced"
    st.session_state[persistent_path_key] = saved_path
    st.session_state.setdefault(widget_path_key, saved_path)

    def _remember_gm_path() -> None:
        selected = _text(st.session_state.get(widget_path_key, "Balanced"))
        st.session_state[persistent_path_key] = selected if selected in GM_PATHS else "Balanced"
        if persist_gm_path is not None:
            persist_gm_path()

    st.radio(
        "GM challenge path",
        GM_PATHS,
        horizontal=True,
        label_visibility="collapsed",
        key=widget_path_key,
        on_change=_remember_gm_path,
    )
    path = _text(st.session_state.get(persistent_path_key, "Balanced"))
    path_copy = {
        "Builder": "Prioritize youth, development, and the long view.",
        "Win Now": "Turn the current roster into wins as quickly as possible.",
        "Deal Maker": "Create your identity through trades and free agency.",
        "Balanced": "Build results, continuity, and flexibility together.",
    }.get(path, "Build results, continuity, and flexibility together.")
    st.markdown(f'<div class="frx-path-note"><strong>{html.escape(path)} path:</strong> {html.escape(path_copy)}</div>', unsafe_allow_html=True)

    goals = _goal_set(
        phase=phase,
        history_count=seasons,
        games=games,
        wins=wins,
        moves=moves,
        profile=profile,
        path=path,
    )
    complete_goals = sum(int(goal["complete"]) for goal in goals)
    quest_pct = complete_goals / max(1, len(goals))
    next_goal_index = next(
        (index for index, goal in enumerate(goals) if not goal["complete"]),
        None,
    )
    next_goal = goals[next_goal_index] if next_goal_index is not None else None

    goal_html_parts: list[str] = []
    for index, goal in enumerate(goals, 1):
        goal_html_parts.append(
            _goal_card_html_v1(
                index=index,
                goal=goal,
                is_current=(next_goal_index == (index - 1)),
            )
        )
    goal_html = "".join(goal_html_parts)
    next_goal_title = (
        html.escape(next_goal["title"])
        if next_goal is not None
        else "All season quests complete"
    )

    st.markdown(
        (
            f'<div class="frx-section-head"><div>'
            f'<div class="frx-section-title">Season quests</div>'
            f'<div class="frx-section-copy">Context-aware front-office objectives for the current franchise phase. Progress is derived automatically from the save and never changes simulation outcomes.</div>'
            f'</div></div>'
            f'<div class="frx-quest-summary">'
            f'<div><small>Quest progress</small><strong>{complete_goals}/{len(goals)} COMPLETE</strong></div>'
            f'<div class="frx-quest-overall"><span style="width:{quest_pct * 100:.0f}%"></span></div>'
            f'<div class="frx-quest-next"><small>Up next</small><b>{next_goal_title}</b></div>'
            f'</div>'
            f'<div class="frx-goals">{goal_html}</div>'
        ),
        unsafe_allow_html=True,
    )


    milestones = _milestones(
        rotation_ready=profile["rotation_ready"],
        games=games,
        wins=wins,
        moves=moves,
        seasons=seasons,
        championships=championships,
    )
    milestone_rows = _milestone_display_rows(
        rotation_ready=profile["rotation_ready"],
        games=games,
        wins=wins,
        moves=moves,
        seasons=seasons,
        championships=championships,
    )
    unlocked_count = sum(int(item["unlocked"]) for item in milestone_rows)
    next_milestone = next(
        (item for item in milestone_rows if not item["unlocked"]),
        None,
    )
    next_milestone_name = (
        next_milestone["name"]
        if next_milestone is not None
        else "Cabinet complete"
    )
    badge_html = "".join(
        (
            f'<div class="frx-badge {"on" if item["unlocked"] else ""}">'
            f'<div class="frx-badge-icon">{item["icon"] if item["unlocked"] else "🔒"}</div>'
            f'<div><div class="frx-badge-name">{html.escape(item["name"])}</div>'
            f'<div class="frx-badge-requirement">{html.escape(item["requirement"])}</div>'
            f'<div class="frx-badge-state">{"Unlocked" if item["unlocked"] else "Locked"}</div>'
            f'</div></div>'
        )
        for item in milestone_rows
    )

    league_title, league_copy = _league_story(state, resolve_name)
    health_copy = (
        "The active rotation is fully available."
        if profile["unavailable"] == 0
        else f"{profile['unavailable']} rotation or roster player(s) are currently unavailable."
    )
    recent_copy = latest_result if games else "Opening night will create the first result in your franchise timeline."
    stories = [
        ("🏀", "Latest result", recent_copy),
        ("🌎", league_title, league_copy),
        ("🩺", "Availability watch", health_copy),
    ]
    story_html = "".join(
        f'<div class="frx-story"><div class="frx-story-icon">{icon}</div><div class="frx-story-title">{html.escape(title)}</div><div class="frx-story-copy">{html.escape(copy)}</div></div>'
        for icon, title, copy in stories
    )
    st.markdown(
        f"""<div class="frx-bottom">
        <div class="frx-cabinet">
          <div class="frx-section-title">Milestone cabinet · {unlocked_count}/{len(milestone_rows)} unlocked</div>
          <div class="frx-section-copy">Permanent accomplishments that stay tied to your franchise career.</div>
          <div class="frx-milestone-summary">
            <div><small>Next milestone</small><strong>{html.escape(next_milestone_name)}</strong></div>
            <div><small>Career bonus</small><strong>+30 XP per milestone</strong></div>
          </div>
          <div class="frx-badges">{badge_html}</div>
        </div>
        <div class="frx-stories">
          <div class="frx-section-title">Around your universe</div>
          <div class="frx-section-copy">A live story feed built from results, standings, and health.</div>
          <div class="frx-story-grid">{story_html}</div>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    target = {"Builder": "Team Management", "Win Now": "Game Day", "Deal Maker": "Trade Center"}.get(path, "Stats & Standings")
    label = {"Builder": "Open Team Management", "Win Now": "Prepare Game Day", "Deal Maker": "Open Trade Center"}.get(path, "Review the league")
    action_cols = st.columns([1.15, 3.0])
    if action_cols[0].button(label, type="primary", width="stretch", key="franchise_gm_path_action_v1"):
        set_section(target)
        st.rerun()
    action_cols[1].caption(f"Current five-game window: {recent_wins}-{recent_losses} · average margin {recent_margin:+.1f}. Milestones and quests never alter simulation outcomes.")
