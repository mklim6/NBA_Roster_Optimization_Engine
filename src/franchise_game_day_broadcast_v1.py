from __future__ import annotations

import html
import re
from typing import Any, Callable


# Keep the V1 public API/version string for backward-compatible validators and
# call sites while the presentation itself advances to Broadcast Center V2.
FRANCHISE_GAME_DAY_BROADCAST_VERSION = "franchise-game-day-broadcast-v1.0-2026-09-11"
FRANCHISE_GAME_DAY_BROADCAST_CENTER_VERSION = "franchise-game-day-broadcast-center-v2.0-2026-09-11"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).lower()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _headshot_url(player_id: str, fallback: str) -> str:
    resolved = _text(player_id)
    if re.fullmatch(r"\d+", resolved):
        return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{resolved}.png"
    return fallback


def _standing(state: Any, team: str) -> Any:
    return (getattr(state, "standings", {}) or {}).get(team)


def _team_record(state: Any, team: str) -> dict[str, Any]:
    row = _standing(state, team)
    games = int(getattr(row, "games_played", 0) or 0)
    wins = int(getattr(row, "wins", 0) or 0)
    losses = int(getattr(row, "losses", 0) or 0)
    points_for = int(getattr(row, "points_for", 0) or 0)
    points_against = int(getattr(row, "points_against", 0) or 0)
    streak_type = _text(getattr(row, "streak_type", "")).upper()
    streak_length = int(getattr(row, "streak_length", 0) or 0)
    streak = f"{streak_type}{streak_length}" if streak_type in {"W", "L"} and streak_length else "—"
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "ppg": points_for / games if games else 0.0,
        "opp_ppg": points_against / games if games else 0.0,
        "margin": (points_for - points_against) / games if games else 0.0,
        "streak": streak,
    }


def _team_game_rows(state: Any, team: str) -> list[tuple[int, bool]]:
    schedule = getattr(state, "schedule", {}) or {}
    rows: list[tuple[int, bool]] = []
    for game_id, game in (getattr(state, "completed_games", {}) or {}).items():
        home = _text(getattr(game, "home_team", "")).upper()
        away = _text(getattr(game, "away_team", "")).upper()
        if team not in {home, away}:
            continue
        home_score = int(getattr(game, "home_score", 0) or 0)
        away_score = int(getattr(game, "away_score", 0) or 0)
        won = (home == team and home_score > away_score) or (away == team and away_score > home_score)
        scheduled = schedule.get(game_id)
        rows.append((int(getattr(scheduled, "day_index", len(rows)) or 0), won))
    rows.sort(key=lambda item: item[0])
    return rows


def _form_html(state: Any, team: str) -> str:
    recent = _team_game_rows(state, team)[-5:]
    if not recent:
        return '<span class="fgb-form empty">FIRST GAME</span>'
    return "".join(
        f'<span class="fgb-form {"win" if won else "loss"}">{"W" if won else "L"}</span>'
        for _, won in recent
    )


def _team_profile(state: Any, team: str) -> dict[str, Any]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    rotation = getattr(team_state, "rotation", None)
    starters = tuple(getattr(rotation, "starter_ids", ()) or ())
    rotation_ids = tuple(getattr(rotation, "rotation_player_ids", ()) or ())
    if not starters:
        starters = rotation_ids[:5]
    players = getattr(state, "players", {}) or {}
    eligible = [players[player_id] for player_id in rotation_ids if player_id in players]
    best_eight = sorted(
        (_number(getattr(player, "overall_rating", 0)) for player in eligible),
        reverse=True,
    )[:8]
    injuries = getattr(state, "injuries", {}) or {}
    unavailable = sum(
        1
        for player_id in rotation_ids
        if _enum(getattr(injuries.get(player_id), "status", "healthy")) in {"out", "doubtful"}
    )
    limited = sum(
        1
        for player_id in rotation_ids
        if _enum(getattr(injuries.get(player_id), "status", "healthy")) in {"questionable", "day_to_day"}
    )
    return {
        "starters": starters[:5],
        "rotation_ids": rotation_ids,
        "power": sum(best_eight) / len(best_eight) if best_eight else 0.0,
        "unavailable": unavailable,
        "limited": limited,
    }


def _player_season_line(state: Any, player_id: str) -> dict[str, float]:
    totals = (getattr(state, "player_season_totals", {}) or {}).get(player_id)
    games = int(getattr(totals, "games_played", 0) or 0)
    return {
        "games": games,
        "ppg": _number(getattr(totals, "points", 0)) / games if games else 0.0,
        "rpg": _number(getattr(totals, "rebounds", 0)) / games if games else 0.0,
        "apg": _number(getattr(totals, "assists", 0)) / games if games else 0.0,
    }


def _featured_player(state: Any, team: str) -> dict[str, Any] | None:
    players = getattr(state, "players", {}) or {}
    profile = _team_profile(state, team)
    candidates = [players[player_id] for player_id in profile["starters"] if player_id in players]
    if not candidates:
        candidates = [players[player_id] for player_id in profile["rotation_ids"] if player_id in players]
    if not candidates:
        return None
    player = max(
        candidates,
        key=lambda row: (
            _number(getattr(row, "overall_rating", 0)),
            _number(getattr(row, "potential_rating", 0)),
            _text(getattr(row, "player_name", "")),
        ),
    )
    player_id = _text(getattr(player, "player_id", ""))
    if not player_id:
        for key, value in players.items():
            if value is player:
                player_id = _text(key)
                break
    return {
        "player_id": player_id,
        "name": _text(getattr(player, "player_name", player_id)) or "Featured player",
        "position": _text(getattr(player, "position", "")) or "—",
        "overall": int(round(_number(getattr(player, "overall_rating", 0)))),
        "season": _player_season_line(state, player_id),
    }


def _starter_strip(state: Any, team: str, logo_url: str) -> str:
    players = getattr(state, "players", {}) or {}
    profile = _team_profile(state, team)
    cards: list[str] = []
    for player_id in profile["starters"]:
        player = players.get(player_id)
        if player is None:
            continue
        name = _text(getattr(player, "player_name", player_id))
        last_name = name.split()[-1] if name else "Starter"
        season = _player_season_line(state, player_id)
        stat = f"{season['ppg']:.1f} PPG" if season["games"] else "Season debut"
        cards.append(
            '<div class="fgb-player">'
            f'<img src="{html.escape(_headshot_url(player_id, logo_url), quote=True)}" alt="{html.escape(name, quote=True)}">'
            f'<div class="fgb-player-name">{html.escape(last_name)}</div>'
            f'<div class="fgb-player-meta">{html.escape(_text(getattr(player, "position", "")) or "—")} · {int(round(_number(getattr(player, "overall_rating", 0))))} OVR</div>'
            f'<div class="fgb-player-stat">{html.escape(stat)}</div>'
            "</div>"
        )
    while len(cards) < 5:
        cards.append('<div class="fgb-player empty"><div class="fgb-player-placeholder">?</div><div class="fgb-player-name">TBD</div><div class="fgb-player-meta">Rotation</div><div class="fgb-player-stat">—</div></div>')
    return "".join(cards)


def _keys_to_game(state: Any, away: str, home: str) -> list[tuple[str, str]]:
    away_profile = _team_profile(state, away)
    home_profile = _team_profile(state, home)
    away_record = _team_record(state, away)
    home_record = _team_record(state, home)
    talent_gap = away_profile["power"] - home_profile["power"]
    if abs(talent_gap) < 1.25:
        talent_copy = "The rotation talent is nearly even. Execution and availability should decide the edge."
    else:
        favored = away if talent_gap > 0 else home
        talent_copy = f"{favored} carry the stronger eight-man rating profile into the matchup."
    total_flags = away_profile["unavailable"] + home_profile["unavailable"]
    limited_flags = away_profile["limited"] + home_profile["limited"]
    if total_flags:
        health_copy = f"{total_flags} projected rotation player(s) are doubtful or out; depth will matter."
    elif limited_flags:
        health_copy = f"{limited_flags} projected rotation player(s) have a limited availability flag."
    else:
        health_copy = "Both projected rotations enter without an unavailable-player flag."
    margin_gap = away_record["margin"] - home_record["margin"]
    if not away_record["games"] and not home_record["games"]:
        rhythm_copy = "Opening night starts a clean slate. The first five-game trend begins here."
    elif abs(margin_gap) < 1.0:
        rhythm_copy = "Season scoring margins are nearly level; late-game possessions could carry extra weight."
    else:
        sharper = away if margin_gap > 0 else home
        rhythm_copy = f"{sharper} own the stronger season scoring margin entering tip-off."
    return [("Talent edge", talent_copy), ("Availability", health_copy), ("Current rhythm", rhythm_copy)]


def _matchup_profile(state: Any, away: str, home: str) -> tuple[float, str]:
    away_profile = _team_profile(state, away)
    home_profile = _team_profile(state, home)
    away_record = _team_record(state, away)
    home_record = _team_record(state, home)
    talent = (away_profile["power"] - home_profile["power"]) * 2.4
    margin = (away_record["margin"] - home_record["margin"]) * 1.6
    availability = (
        (home_profile["unavailable"] - away_profile["unavailable"]) * 4.0
        + (home_profile["limited"] - away_profile["limited"]) * 1.6
    )
    away_share = _clamp(50.0 + talent + margin + availability, 22.0, 78.0)
    if abs(away_share - 50.0) <= 4.0:
        label = "Even matchup profile"
    else:
        label = f"Profile edge: {away if away_share > 50.0 else home}"
    return away_share, label


def _spotlight_html(state: Any, team: str, logo_url: str, primary: str) -> str:
    featured = _featured_player(state, team)
    if featured is None:
        return (
            f'<div class="fgb-spotlight" style="--spot:{html.escape(primary)}">'
            f'<img class="fgb-spotlight-img logo" src="{html.escape(logo_url, quote=True)}" alt="">'
            '<div><div class="fgb-spotlight-kicker">PLAYER SPOTLIGHT</div>'
            '<div class="fgb-spotlight-name">Rotation TBD</div>'
            '<div class="fgb-spotlight-meta">No projected starter available</div></div></div>'
        )
    season = featured["season"]
    if season["games"]:
        line = f"{season['ppg']:.1f} PPG · {season['rpg']:.1f} RPG · {season['apg']:.1f} APG"
    else:
        line = "Season debut · opening-night baseline"
    return (
        f'<div class="fgb-spotlight" style="--spot:{html.escape(primary)}">'
        f'<img class="fgb-spotlight-img" src="{html.escape(_headshot_url(featured["player_id"], logo_url), quote=True)}" alt="{html.escape(featured["name"], quote=True)}">'
        '<div><div class="fgb-spotlight-kicker">PLAYER SPOTLIGHT</div>'
        f'<div class="fgb-spotlight-name">{html.escape(featured["name"])}</div>'
        f'<div class="fgb-spotlight-meta">{html.escape(featured["position"])} · {featured["overall"]} OVR</div>'
        f'<div class="fgb-spotlight-line">{html.escape(line)}</div></div></div>'
    )


def _team_box_totals(completed: Any, team: str) -> dict[str, float]:
    totals = {
        "fgm": 0.0,
        "fga": 0.0,
        "tpm": 0.0,
        "tpa": 0.0,
        "ftm": 0.0,
        "fta": 0.0,
        "reb": 0.0,
        "ast": 0.0,
        "tov": 0.0,
        "stl": 0.0,
        "blk": 0.0,
    }
    for line in tuple(getattr(completed, "player_box_scores", ()) or ()):
        if _text(getattr(line, "team_abbreviation", "")).upper() != team:
            continue
        totals["fgm"] += _number(getattr(line, "field_goals_made", 0))
        totals["fga"] += _number(getattr(line, "field_goals_attempted", 0))
        totals["tpm"] += _number(getattr(line, "three_pointers_made", 0))
        totals["tpa"] += _number(getattr(line, "three_pointers_attempted", 0))
        totals["ftm"] += _number(getattr(line, "free_throws_made", 0))
        totals["fta"] += _number(getattr(line, "free_throws_attempted", 0))
        totals["reb"] += _number(getattr(line, "rebounds", 0))
        totals["ast"] += _number(getattr(line, "assists", 0))
        totals["tov"] += _number(getattr(line, "turnovers", 0))
        totals["stl"] += _number(getattr(line, "steals", 0))
        totals["blk"] += _number(getattr(line, "blocks", 0))
    return totals


def _pct(made: float, attempted: float) -> float:
    return 100.0 * made / attempted if attempted else 0.0


def _broadcast_headline(completed: Any, team_name_resolver: Callable[[str], str]) -> tuple[str, str]:
    away = _text(getattr(completed, "away_team", "")).upper()
    home = _text(getattr(completed, "home_team", "")).upper()
    away_score = int(getattr(completed, "away_score", 0) or 0)
    home_score = int(getattr(completed, "home_score", 0) or 0)
    overtime = int(getattr(completed, "overtime_periods", 0) or 0)
    winner = away if away_score > home_score else home
    loser = home if winner == away else away
    margin = abs(away_score - home_score)
    winner_name = team_name_resolver(winner)
    loser_name = team_name_resolver(loser)
    if overtime:
        headline = f"{winner_name} outlast {loser_name} in overtime"
    elif margin <= 3:
        headline = f"{winner_name} survive {loser_name} in a one-possession finish"
    elif margin <= 8:
        headline = f"{winner_name} edge {loser_name}"
    elif margin <= 15:
        headline = f"{winner_name} pull away from {loser_name}"
    else:
        headline = f"{winner_name} dominate {loser_name}"
    deck = f"Final: {away} {away_score}, {home} {home_score}. The result is now part of the permanent franchise season."
    return headline, deck


def _next_game_for_team(state: Any, team: str, completed_game_id: str) -> Any | None:
    schedule = getattr(state, "schedule", {}) or {}
    completed_ids = set((getattr(state, "completed_games", {}) or {}).keys())
    current = schedule.get(completed_game_id)
    current_day = int(getattr(current, "day_index", -1) or -1)
    candidates = []
    for game_id, game in schedule.items():
        if game_id in completed_ids:
            continue
        home = _text(getattr(game, "home_team", "")).upper()
        away = _text(getattr(game, "away_team", "")).upper()
        if team not in {home, away}:
            continue
        day = int(getattr(game, "day_index", 10**9) or 10**9)
        if day <= current_day:
            continue
        candidates.append((day, _text(game_id), game))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2] if candidates else None


def inject_game_day_broadcast_visuals_v1() -> None:
    import streamlit as st

    st.markdown(
        """
<style>
/* FRANCHISE_GAME_DAY_BROADCAST_V1 */
/* FRANCHISE_GAME_DAY_BROADCAST_CENTER_V2 */
.fgb-shell{position:relative;margin:.8rem 0 1.25rem;color:#f8fbff}
.fgb-legacy-matchup{display:none!important}
.fgb-scoreboard{position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(190px,1fr) minmax(205px,.72fr) minmax(190px,1fr);align-items:center;gap:14px;padding:28px 24px 23px;border:1px solid rgba(255,255,255,.13);border-radius:26px;background:radial-gradient(circle at 7% 18%,color-mix(in srgb,var(--fgb-away) 38%,transparent),transparent 36%),radial-gradient(circle at 93% 18%,color-mix(in srgb,var(--fgb-home) 38%,transparent),transparent 36%),linear-gradient(145deg,#050a12 7%,#101827 54%,#050a12);box-shadow:0 26px 70px rgba(0,0,0,.36)}
.fgb-scoreboard:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,color-mix(in srgb,var(--fgb-away) 16%,transparent),transparent 40%,transparent 60%,color-mix(in srgb,var(--fgb-home) 16%,transparent));pointer-events:none}
.fgb-scoreboard:after{content:"";position:absolute;left:0;right:0;bottom:0;height:4px;background:linear-gradient(90deg,var(--fgb-away),#f8fafc 49%,#f8fafc 51%,var(--fgb-home))}
.fgb-team,.fgb-center{position:relative;z-index:1}.fgb-team{display:flex;align-items:center;gap:16px}.fgb-team.home{justify-content:flex-end;text-align:right}.fgb-team img{width:112px;height:112px;object-fit:contain;filter:drop-shadow(0 14px 20px rgba(0,0,0,.4))}.fgb-team-name{font-size:1.1rem;font-weight:950;line-height:1.05}.fgb-record{margin-top:6px;color:#cbd7e7;font-size:.73rem;font-weight:850}.fgb-form-row{display:flex;gap:4px;margin-top:8px}.fgb-team.home .fgb-form-row{justify-content:flex-end}.fgb-form{display:inline-grid;place-items:center;min-width:21px;height:21px;padding:0 5px;border-radius:6px;font-size:.52rem;font-weight:950}.fgb-form.win{color:#9ff8cd;background:rgba(16,185,129,.16);border:1px solid rgba(52,211,153,.2)}.fgb-form.loss{color:#fecaca;background:rgba(239,68,68,.14);border:1px solid rgba(248,113,113,.18)}.fgb-form.empty{color:#9fb0c5;background:rgba(255,255,255,.05)}
.fgb-center{text-align:center}.fgb-live{display:inline-flex;align-items:center;gap:6px;padding:6px 9px;border-radius:999px;background:rgba(239,68,68,.13);border:1px solid rgba(248,113,113,.22);color:#fecaca;font-size:.52rem;font-weight:950;letter-spacing:.12em}.fgb-live i{width:7px;height:7px;border-radius:99px;background:#fb7185;box-shadow:0 0 12px #fb7185}.fgb-date{margin-top:11px;color:#fff;font-size:.9rem;font-weight:900}.fgb-at{margin:.28rem 0;color:#7f90a7;font-size:.58rem;font-weight:900;letter-spacing:.18em}.fgb-season{color:#92a4ba;font-size:.58rem}.fgb-control{display:inline-block;margin-top:9px;padding:4px 8px;border-radius:7px;background:rgba(34,211,238,.09);color:#8be8f5;font-size:.5rem;font-weight:900;text-transform:uppercase;letter-spacing:.06em}
.fgb-ticker{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;margin-top:7px;padding:8px 12px;border:1px solid rgba(255,255,255,.06);border-radius:10px;background:rgba(3,8,14,.78);color:#778ba2;font-size:.5rem;font-weight:850}.fgb-ticker span:nth-child(2){text-align:center}.fgb-ticker span:last-child{text-align:right}.fgb-ticker strong{color:#dce8f5}
.fgb-subhead{display:flex;align-items:end;justify-content:space-between;margin:1.15rem 0 .5rem}.fgb-kicker{color:#7dd3fc;font-size:.5rem;font-weight:950;letter-spacing:.14em;text-transform:uppercase}.fgb-title{margin-top:.18rem;color:#f7faff;font-size:1rem;font-weight:950}.fgb-note{color:#6f8196;font-size:.54rem}.fgb-lineups{display:grid;grid-template-columns:1fr 1fr;gap:10px}.fgb-lineup{padding:12px;border:1px solid rgba(255,255,255,.075);border-radius:15px;background:linear-gradient(145deg,rgba(255,255,255,.025),rgba(255,255,255,.012));box-shadow:inset 0 1px 0 rgba(255,255,255,.025)}.fgb-lineup:first-child{border-top:2px solid color-mix(in srgb,var(--fgb-away) 74%,#fff 8%)}.fgb-lineup:last-child{border-top:2px solid color-mix(in srgb,var(--fgb-home) 74%,#fff 8%)}.fgb-lineup-head{display:flex;align-items:center;gap:7px;margin-bottom:8px;color:#edf5ff;font-size:.62rem;font-weight:950}.fgb-lineup-head img{width:24px;height:24px;object-fit:contain}.fgb-player-row{display:grid;grid-template-columns:repeat(5,1fr);gap:5px}.fgb-player{min-width:0;padding:5px 4px 6px;border-radius:9px;background:rgba(255,255,255,.02);text-align:center}.fgb-player img{width:100%;height:70px;object-fit:cover;object-position:top center;border-radius:7px;background:rgba(255,255,255,.035)}.fgb-player-name{overflow:hidden;margin-top:5px;color:#f7faff;font-size:.55rem;font-weight:900;text-overflow:ellipsis;white-space:nowrap}.fgb-player-meta{margin-top:2px;color:#72849a;font-size:.46rem;white-space:nowrap}.fgb-player-stat{margin-top:2px;color:#9acff8;font-size:.43rem;font-weight:850;white-space:nowrap}.fgb-player-placeholder{display:grid;place-items:center;height:70px;border-radius:7px;background:rgba(255,255,255,.025);color:#63758c;font-size:1.2rem}
.fgb-spotlights{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.fgb-spotlight{position:relative;overflow:hidden;display:grid;grid-template-columns:108px 1fr;align-items:center;min-height:132px;padding:10px 14px 10px 8px;border:1px solid rgba(255,255,255,.08);border-radius:16px;background:radial-gradient(circle at 0 50%,color-mix(in srgb,var(--spot) 22%,transparent),transparent 46%),linear-gradient(145deg,rgba(255,255,255,.025),rgba(255,255,255,.01))}.fgb-spotlight:after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--spot),transparent)}.fgb-spotlight-img{align-self:end;width:104px;height:118px;object-fit:cover;object-position:top center;filter:drop-shadow(0 12px 18px rgba(0,0,0,.35))}.fgb-spotlight-img.logo{object-fit:contain;padding:16px}.fgb-spotlight-kicker{color:#7dd3fc;font-size:.45rem;font-weight:950;letter-spacing:.12em}.fgb-spotlight-name{margin-top:5px;color:#fff;font-size:.84rem;font-weight:950}.fgb-spotlight-meta{margin-top:2px;color:#9badc2;font-size:.53rem;font-weight:800}.fgb-spotlight-line{margin-top:8px;color:#d8e6f5;font-size:.57rem;font-weight:850}
.fgb-edge{margin-top:10px;padding:12px 14px;border:1px solid rgba(255,255,255,.075);border-radius:14px;background:rgba(255,255,255,.015)}.fgb-edge-head{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px}.fgb-edge-label{color:#fff;font-size:.6rem;font-weight:950}.fgb-edge-note{color:#72849a;font-size:.48rem}.fgb-edge-track{height:10px;overflow:hidden;border-radius:999px;background:linear-gradient(90deg,var(--fgb-away) 0 var(--away-share),var(--fgb-home) var(--away-share) 100%);box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}.fgb-edge-foot{display:flex;justify-content:space-between;margin-top:6px;color:#7e90a5;font-size:.46rem;font-weight:900}.fgb-tape{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.fgb-tape-card{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;padding:11px;border:1px solid rgba(255,255,255,.07);border-radius:13px;background:rgba(255,255,255,.018)}.fgb-tape-side{font-size:.74rem;font-weight:950}.fgb-tape-side:last-child{text-align:right}.fgb-tape-label{text-align:center;color:#75879c;font-size:.48rem;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.fgb-keys{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.fgb-key{position:relative;overflow:hidden;min-height:92px;padding:12px;border:1px solid rgba(255,255,255,.07);border-radius:13px;background:linear-gradient(145deg,rgba(255,255,255,.03),rgba(255,255,255,.012))}.fgb-key:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(var(--fgb-away),var(--fgb-home))}.fgb-key-num{color:#7dd3fc;font-size:.49rem;font-weight:950;letter-spacing:.12em}.fgb-key-title{margin:.35rem 0 .24rem;color:#fff;font-size:.67rem;font-weight:900}.fgb-key-copy{color:#8293a8;font-size:.56rem;line-height:1.42}
.fgb-postgame-hero{position:relative;overflow:hidden;padding:22px;border:1px solid rgba(255,255,255,.11);border-radius:24px;background:radial-gradient(circle at 8% 35%,color-mix(in srgb,var(--fgb-away) 25%,transparent),transparent 35%),radial-gradient(circle at 92% 35%,color-mix(in srgb,var(--fgb-home) 25%,transparent),transparent 35%),linear-gradient(145deg,#07101b,#0e1725);box-shadow:0 22px 58px rgba(0,0,0,.3)}.fgb-postgame-kicker{color:#86efac;font-size:.5rem;font-weight:950;letter-spacing:.14em}.fgb-postgame-headline{max-width:900px;margin-top:6px;color:#fff;font-size:1.35rem;font-weight:950;line-height:1.15}.fgb-postgame-deck{margin-top:6px;color:#8fa2b8;font-size:.58rem;line-height:1.45}.fgb-final{position:relative;display:grid;grid-template-columns:1fr minmax(180px,.62fr) 1fr;align-items:center;gap:14px;margin-top:14px;padding:18px 18px 16px;border:1px solid rgba(255,255,255,.08);border-radius:18px;background:rgba(2,8,14,.64)}.fgb-final-team{display:flex;align-items:center;gap:13px}.fgb-final-team.home{justify-content:flex-end;text-align:right}.fgb-final-team img{width:76px;height:76px;object-fit:contain}.fgb-final-name{color:#d9e5f3;font-size:.8rem;font-weight:900}.fgb-final-score{margin-top:3px;color:#fff;font-size:2.45rem;font-weight:950;line-height:1}.fgb-final-center{text-align:center}.fgb-final-label{color:#86efac;font-size:.58rem;font-weight:950;letter-spacing:.15em}.fgb-winner{margin-top:7px;color:#fff;font-size:.84rem;font-weight:950}.fgb-final-detail{margin-top:4px;color:#8293a8;font-size:.56rem}.fgb-leaders{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}.fgb-leader{display:flex;align-items:center;gap:9px;padding:10px;border:1px solid rgba(255,255,255,.07);border-radius:13px;background:rgba(255,255,255,.02)}.fgb-leader img{width:48px;height:48px;object-fit:cover;object-position:top;border-radius:9px;background:rgba(255,255,255,.04)}.fgb-leader-tag{color:#7dd3fc;font-size:.46rem;font-weight:950;letter-spacing:.08em}.fgb-leader-name{color:#fff;font-size:.63rem;font-weight:900}.fgb-leader-line{color:#8495a9;font-size:.5rem}.fgb-poststats{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;margin-top:10px}.fgb-poststat{padding:10px;border:1px solid rgba(255,255,255,.065);border-radius:12px;background:rgba(255,255,255,.018)}.fgb-poststat-label{text-align:center;color:#72849a;font-size:.45rem;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.fgb-poststat-values{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:4px;margin-top:6px;color:#fff;font-size:.66rem;font-weight:950}.fgb-poststat-values span:nth-child(2){color:#52647a;font-size:.42rem}.fgb-poststat-values span:last-child{text-align:right}.fgb-nextup{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;margin-top:10px;padding:12px 14px;border:1px solid rgba(125,211,252,.15);border-radius:14px;background:linear-gradient(90deg,rgba(14,165,233,.07),rgba(255,255,255,.015))}.fgb-nextup img{width:44px;height:44px;object-fit:contain}.fgb-nextup-kicker{color:#7dd3fc;font-size:.45rem;font-weight:950;letter-spacing:.12em}.fgb-nextup-title{margin-top:3px;color:#fff;font-size:.67rem;font-weight:900}.fgb-nextup-meta{margin-top:2px;color:#8495aa;font-size:.5rem}.fgb-nextup-tag{padding:5px 7px;border-radius:8px;background:rgba(125,211,252,.08);color:#9adcf7;font-size:.46rem;font-weight:900}
@media(max-width:900px){.fgb-scoreboard,.fgb-final{grid-template-columns:1fr 130px 1fr;padding:18px 14px}.fgb-team img{width:76px;height:76px}.fgb-lineups,.fgb-spotlights{grid-template-columns:1fr}.fgb-keys,.fgb-tape{grid-template-columns:1fr}.fgb-leaders{grid-template-columns:1fr}.fgb-poststats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.fgb-scoreboard,.fgb-final{grid-template-columns:1fr 76px 1fr;gap:5px;padding:15px 8px}.fgb-team{display:block;text-align:center}.fgb-team.home{display:block;text-align:center}.fgb-team img{width:58px;height:58px}.fgb-team-name{font-size:.7rem}.fgb-record{font-size:.58rem}.fgb-form-row,.fgb-team.home .fgb-form-row{justify-content:center}.fgb-live{font-size:.43rem;padding:4px 5px}.fgb-date{font-size:.62rem}.fgb-season{font-size:.46rem}.fgb-control{font-size:.42rem}.fgb-player-row{gap:3px}.fgb-player{padding:4px 2px}.fgb-player img,.fgb-player-placeholder{height:48px}.fgb-player-name{font-size:.47rem}.fgb-player-meta,.fgb-player-stat{font-size:.39rem}.fgb-spotlight{grid-template-columns:80px 1fr;min-height:102px}.fgb-spotlight-img{width:76px;height:92px}.fgb-final-team{display:block;text-align:center}.fgb-final-team.home{display:block;text-align:center}.fgb-final-team img{width:55px;height:55px}.fgb-final-score{font-size:1.7rem}.fgb-final-name{font-size:.6rem}.fgb-postgame-headline{font-size:1rem}.fgb-poststats{grid-template-columns:1fr}.fgb-nextup{grid-template-columns:auto 1fr}.fgb-nextup-tag{display:none}}
@media(prefers-reduced-motion:reduce){.fgb-live i{box-shadow:none}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_game_day_broadcast_v1(
    *,
    state: Any,
    game: Any,
    active_team: str,
    game_date_label: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
) -> None:
    import streamlit as st

    away = _text(getattr(game, "away_team", "")).upper()
    home = _text(getattr(game, "home_team", "")).upper()
    away_name = team_name_resolver(away)
    home_name = team_name_resolver(home)
    away_logo = team_logo_resolver(away)
    home_logo = team_logo_resolver(home)
    away_primary, _ = team_colors_resolver(away)
    home_primary, _ = team_colors_resolver(home)
    away_record = _team_record(state, away)
    home_record = _team_record(state, home)
    away_profile = _team_profile(state, away)
    home_profile = _team_profile(state, home)
    location = "Road game" if _text(active_team).upper() == away else "Home game"
    phase = _enum(getattr(state, "phase", "regular_season")).replace("_", " ").title()
    away_share, profile_label = _matchup_profile(state, away, home)

    st.markdown(
        f'''<div class="fgb-shell" style="--fgb-away:{html.escape(away_primary)};--fgb-home:{html.escape(home_primary)};--away-share:{away_share:.1f}%">
        <div class="fgb-scoreboard">
          <div class="fgb-team away"><img src="{html.escape(away_logo, quote=True)}" alt="{html.escape(away_name, quote=True)}"><div><div class="fgb-team-name">{html.escape(away_name)}</div><div class="fgb-record">{away_record['record']} · {away_record['streak']} streak</div><div class="fgb-form-row">{_form_html(state, away)}</div></div></div>
          <div class="fgb-center"><div class="fgb-live"><i></i> BROADCAST CENTER</div><div class="fgb-date">{html.escape(game_date_label)}</div><div class="fgb-at">AWAY · AT · HOME</div><div class="fgb-season">{html.escape(phase)}</div><div class="fgb-control">{html.escape(location)} · User controlled</div></div>
          <div class="fgb-team home"><div><div class="fgb-team-name">{html.escape(home_name)}</div><div class="fgb-record">{home_record['record']} · {home_record['streak']} streak</div><div class="fgb-form-row">{_form_html(state, home)}</div></div><img src="{html.escape(home_logo, quote=True)}" alt="{html.escape(home_name, quote=True)}"></div>
        </div>
        <div class="fgb-ticker"><span><strong>{away}</strong> {away_record['ppg']:.1f} PPG</span><span>PROJECTED ROTATION <strong>{away_profile['power']:.1f} – {home_profile['power']:.1f}</strong></span><span><strong>{home}</strong> {home_record['ppg']:.1f} PPG</span></div>
        <div class="fgb-spotlights">{_spotlight_html(state, away, away_logo, away_primary)}{_spotlight_html(state, home, home_logo, home_primary)}</div>
        <div class="fgb-edge"><div class="fgb-edge-head"><div class="fgb-edge-label">{html.escape(profile_label)}</div><div class="fgb-edge-note">Derived from rotation strength, season margin and availability — not a win probability</div></div><div class="fgb-edge-track"></div><div class="fgb-edge-foot"><span>{away} profile</span><span>{home} profile</span></div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fgb-subhead"><div><div class="fgb-kicker">Broadcast desk</div><div class="fgb-title">Projected starting lineups</div></div><div class="fgb-note">Based on the currently saved rotations</div></div>', unsafe_allow_html=True)
    st.markdown(
        f'''<div class="fgb-lineups" style="--fgb-away:{html.escape(away_primary)};--fgb-home:{html.escape(home_primary)}">
        <div class="fgb-lineup"><div class="fgb-lineup-head"><img src="{html.escape(away_logo, quote=True)}" alt="">{html.escape(away_name)}</div><div class="fgb-player-row">{_starter_strip(state, away, away_logo)}</div></div>
        <div class="fgb-lineup"><div class="fgb-lineup-head"><img src="{html.escape(home_logo, quote=True)}" alt="">{html.escape(home_name)}</div><div class="fgb-player-row">{_starter_strip(state, home, home_logo)}</div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="fgb-subhead"><div><div class="fgb-kicker">Matchup intelligence</div><div class="fgb-title">Tale of the tape</div></div><div class="fgb-note">Live season and rotation data</div></div>', unsafe_allow_html=True)
    tape = [
        (f"{away_profile['power']:.1f}", "Top-eight OVR", f"{home_profile['power']:.1f}"),
        (f"{away_record['margin']:+.1f}", "Point margin", f"{home_record['margin']:+.1f}"),
        (str(away_profile["unavailable"]), "Unavailable", str(home_profile["unavailable"])),
    ]
    tape_html = "".join(
        f'<div class="fgb-tape-card"><div class="fgb-tape-side">{html.escape(left)}</div><div class="fgb-tape-label">{html.escape(label)}</div><div class="fgb-tape-side">{html.escape(right)}</div></div>'
        for left, label, right in tape
    )
    keys_html = "".join(
        f'<div class="fgb-key"><div class="fgb-key-num">KEY {index:02d}</div><div class="fgb-key-title">{html.escape(title)}</div><div class="fgb-key-copy">{html.escape(copy)}</div></div>'
        for index, (title, copy) in enumerate(_keys_to_game(state, away, home), 1)
    )
    st.markdown(
        f'<div class="fgb-shell" style="--fgb-away:{html.escape(away_primary)};--fgb-home:{html.escape(home_primary)}"><div class="fgb-tape">{tape_html}</div><div class="fgb-keys">{keys_html}</div></div>',
        unsafe_allow_html=True,
    )


def _leader_rows(state: Any, completed: Any) -> list[dict[str, str]]:
    players = getattr(state, "players", {}) or {}
    rows = []
    for line in tuple(getattr(completed, "player_box_scores", ()) or ()):
        player = players.get(getattr(line, "player_id", ""))
        if player is None:
            continue
        points = int(getattr(line, "points", 0) or 0)
        rebounds = int(getattr(line, "rebounds", 0) or 0)
        assists = int(getattr(line, "assists", 0) or 0)
        score = points + 0.7 * rebounds + 0.8 * assists + _number(getattr(line, "steals", 0)) + _number(getattr(line, "blocks", 0))
        rows.append(
            {
                "score": score,
                "player_id": _text(getattr(line, "player_id", "")),
                "name": _text(getattr(player, "player_name", "")),
                "team": _text(getattr(line, "team_abbreviation", "")),
                "line": f"{points} PTS · {rebounds} REB · {assists} AST",
            }
        )
    return sorted(rows, key=lambda row: (row["score"], row["name"]), reverse=True)[:3]


def render_game_day_final_v1(
    *,
    state: Any,
    completed: Any,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    active_team: str = "",
    game_date_resolver: Callable[[int], str] | None = None,
) -> None:
    import streamlit as st

    away = _text(getattr(completed, "away_team", "")).upper()
    home = _text(getattr(completed, "home_team", "")).upper()
    away_score = int(getattr(completed, "away_score", 0) or 0)
    home_score = int(getattr(completed, "home_score", 0) or 0)
    overtime = int(getattr(completed, "overtime_periods", 0) or 0)
    winner = away if away_score > home_score else home
    away_primary, _ = team_colors_resolver(away)
    home_primary, _ = team_colors_resolver(home)
    leaders = _leader_rows(state, completed)
    headline, deck = _broadcast_headline(completed, team_name_resolver)
    leader_html = "".join(
        f'''<div class="fgb-leader"><img src="{html.escape(_headshot_url(row['player_id'], team_logo_resolver(row['team'])), quote=True)}" alt="{html.escape(row['name'], quote=True)}"><div><div class="fgb-leader-tag">{html.escape('GAME LEADER' if index == 0 else row['team'])}</div><div class="fgb-leader-name">{html.escape(row['name'])}</div><div class="fgb-leader-line">{html.escape(row['line'])}</div></div></div>'''
        for index, row in enumerate(leaders)
    )

    away_totals = _team_box_totals(completed, away)
    home_totals = _team_box_totals(completed, home)
    comparison = [
        (f"{_pct(away_totals['fgm'], away_totals['fga']):.1f}%", "FG%", f"{_pct(home_totals['fgm'], home_totals['fga']):.1f}%"),
        (f"{_pct(away_totals['tpm'], away_totals['tpa']):.1f}%", "3PT%", f"{_pct(home_totals['tpm'], home_totals['tpa']):.1f}%"),
        (str(int(away_totals['reb'])), "REB", str(int(home_totals['reb']))),
        (str(int(away_totals['ast'])), "AST", str(int(home_totals['ast']))),
        (str(int(away_totals['tov'])), "TOV", str(int(home_totals['tov']))),
    ]
    comparison_html = "".join(
        f'<div class="fgb-poststat"><div class="fgb-poststat-label">{html.escape(label)}</div><div class="fgb-poststat-values"><span>{html.escape(left)}</span><span>VS</span><span>{html.escape(right)}</span></div></div>'
        for left, label, right in comparison
    )

    nextup_html = ""
    controlled = _text(active_team).upper()
    if controlled:
        next_game = _next_game_for_team(state, controlled, _text(getattr(completed, "game_id", "")))
        if next_game is not None:
            next_home = _text(getattr(next_game, "home_team", "")).upper()
            next_away = _text(getattr(next_game, "away_team", "")).upper()
            opponent = next_away if next_home == controlled else next_home
            location = "vs" if next_home == controlled else "at"
            day_index = int(getattr(next_game, "day_index", 0) or 0)
            date_label = game_date_resolver(day_index) if game_date_resolver is not None else f"Season day {day_index + 1}"
            nextup_html = (
                '<div class="fgb-nextup">'
                f'<img src="{html.escape(team_logo_resolver(opponent), quote=True)}" alt="">'
                '<div><div class="fgb-nextup-kicker">NEXT UP</div>'
                f'<div class="fgb-nextup-title">{html.escape(team_name_resolver(controlled))} {location} {html.escape(team_name_resolver(opponent))}</div>'
                f'<div class="fgb-nextup-meta">{html.escape(date_label)}</div></div>'
                '<div class="fgb-nextup-tag">NEXT MATCHUP LOADED</div></div>'
            )

    st.markdown(
        f'''<div class="fgb-shell" style="--fgb-away:{html.escape(away_primary)};--fgb-home:{html.escape(home_primary)}"><div class="fgb-postgame-hero">
        <div class="fgb-postgame-kicker">POSTGAME · BROADCAST RECAP</div><div class="fgb-postgame-headline">{html.escape(headline)}</div><div class="fgb-postgame-deck">{html.escape(deck)}</div>
        <div class="fgb-final">
        <div class="fgb-final-team"><img src="{html.escape(team_logo_resolver(away), quote=True)}" alt=""><div><div class="fgb-final-name">{html.escape(team_name_resolver(away))}</div><div class="fgb-final-score">{away_score}</div></div></div>
        <div class="fgb-final-center"><div class="fgb-final-label">FINAL{f' · {overtime} OT' if overtime else ''}</div><div class="fgb-winner">{html.escape(team_name_resolver(winner))} win</div><div class="fgb-final-detail">Season result saved · league state advanced</div></div>
        <div class="fgb-final-team home"><div><div class="fgb-final-name">{html.escape(team_name_resolver(home))}</div><div class="fgb-final-score">{home_score}</div></div><img src="{html.escape(team_logo_resolver(home), quote=True)}" alt=""></div>
        </div><div class="fgb-leaders">{leader_html}</div><div class="fgb-poststats">{comparison_html}</div>{nextup_html}</div></div>''',
        unsafe_allow_html=True,
    )
