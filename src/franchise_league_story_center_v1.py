from __future__ import annotations

import html
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import streamlit as st


FRANCHISE_LEAGUE_STORY_CENTER_VERSION = (
    "franchise-league-story-center-v1.2-2026-09-11"
)


@dataclass(frozen=True)
class LeagueStoryV1:
    story_id: str
    category: str
    kicker: str
    headline: str
    detail: str
    priority: float
    day_index: int = -1
    team: str = ""
    opponent: str = ""
    player_id: str = ""
    game_id: str = ""
    statline: str = ""
    metrics: tuple[tuple[str, str], ...] = ()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _enum_text(value: Any) -> str:
    return _clean(getattr(value, "value", value)).lower()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _esc(value: Any) -> str:
    return html.escape(_clean(value), quote=True)


def _obj_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _player_name(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id))
    return _clean(getattr(player, "player_name", "")) or str(player_id)


def _player_team(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id))
    return _team(getattr(player, "team_abbreviation", ""))


def _game_day(state: Any, game_id: str) -> int:
    game = (getattr(state, "schedule", {}) or {}).get(str(game_id))
    return _int(getattr(game, "day_index", -1), -1)


def _completed_games(state: Any) -> list[tuple[int, str, Any]]:
    rows: list[tuple[int, str, Any]] = []
    for game_id, game in (getattr(state, "completed_games", {}) or {}).items():
        rows.append((_game_day(state, str(game_id)), str(game_id), game))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def _record(standing: Any) -> str:
    return f"{_int(getattr(standing, 'wins', 0))}-{_int(getattr(standing, 'losses', 0))}"


def _win_pct(standing: Any) -> float:
    wins = _int(getattr(standing, "wins", 0))
    losses = _int(getattr(standing, "losses", 0))
    games = wins + losses
    return wins / games if games else 0.0


def _point_diff(standing: Any) -> float:
    games = max(1, _int(getattr(standing, "games_played", 0)))
    return (
        _num(getattr(standing, "points_for", 0))
        - _num(getattr(standing, "points_against", 0))
    ) / games


def _standing_games(standing: Any) -> int:
    games = _int(getattr(standing, "games_played", 0))
    if games > 0:
        return games
    return _int(getattr(standing, "wins", 0)) + _int(getattr(standing, "losses", 0))


def _team_rates(standing: Any) -> tuple[float, float]:
    games = max(1, _standing_games(standing))
    return (
        _num(getattr(standing, "points_for", 0)) / games,
        _num(getattr(standing, "points_against", 0)) / games,
    )


def _conference_name(state: Any, team: str) -> str:
    team_obj = (getattr(state, "teams", {}) or {}).get(_team(team))
    raw = _clean(getattr(team_obj, "conference", ""))
    lowered = raw.lower()
    if lowered.startswith("e"):
        return "East"
    if lowered.startswith("w"):
        return "West"
    return raw


def _ordered_standings(state: Any) -> list[Any]:
    rows = list((getattr(state, "standings", {}) or {}).values())
    return sorted(
        rows,
        key=lambda row: (
            -_win_pct(row),
            -_point_diff(row),
            -_num(getattr(row, "points_for", 0)),
            _team(getattr(row, "team_abbreviation", "")),
        ),
    )


def _league_rank(state: Any, team: str) -> int:
    team = _team(team)
    for index, row in enumerate(_ordered_standings(state), start=1):
        if _team(getattr(row, "team_abbreviation", "")) == team:
            return index
    return 0


def _conference_rank(state: Any, team: str) -> int:
    team = _team(team)
    conference = _conference_name(state, team).lower()
    rows = [
        row
        for row in _ordered_standings(state)
        if _conference_name(
            state,
            _team(getattr(row, "team_abbreviation", "")),
        ).lower()
        == conference
    ]
    for index, row in enumerate(rows, start=1):
        if _team(getattr(row, "team_abbreviation", "")) == team:
            return index
    return 0


def _pct(made: Any, attempted: Any) -> float:
    attempts = _num(attempted, 0.0)
    if attempts <= 0:
        return 0.0
    return 100.0 * _num(made, 0.0) / attempts


def _true_shooting(points: Any, fga: Any, fta: Any) -> float:
    denominator = 2.0 * (_num(fga, 0.0) + 0.44 * _num(fta, 0.0))
    if denominator <= 0:
        return 0.0
    return 100.0 * _num(points, 0.0) / denominator


def _league_snapshot_metrics_v1(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
) -> list[tuple[str, str, str]]:
    standings = [row for row in _ordered_standings(state) if _standing_games(row) > 0]
    metrics: list[tuple[str, str, str]] = []
    if standings:
        best = standings[0]
        best_team = _team(getattr(best, "team_abbreviation", ""))
        metrics.append((
            "Best record",
            f"{best_team} {_record(best)}",
            f"{_point_diff(best):+.1f} diff · #{_league_rank(state, best_team)} NBA",
        ))

        offense = max(standings, key=lambda row: _team_rates(row)[0])
        offense_team = _team(getattr(offense, "team_abbreviation", ""))
        offense_ppg, _ = _team_rates(offense)
        metrics.append((
            "Top offense",
            f"{offense_ppg:.1f} PPG",
            team_name_resolver(offense_team),
        ))

        defense = min(standings, key=lambda row: _team_rates(row)[1])
        defense_team = _team(getattr(defense, "team_abbreviation", ""))
        _, defense_ppg = _team_rates(defense)
        metrics.append((
            "Top defense",
            f"{defense_ppg:.1f} OPP",
            team_name_resolver(defense_team),
        ))

        win_streaks = [
            row
            for row in standings
            if _clean(getattr(row, "streak_type", "")).upper().startswith("W")
            and _int(getattr(row, "streak_length", 0)) > 0
        ]
        if win_streaks:
            hottest = max(win_streaks, key=lambda row: _int(getattr(row, "streak_length", 0)))
            hot_team = _team(getattr(hottest, "team_abbreviation", ""))
            hot_len = _int(getattr(hottest, "streak_length", 0))
            conf = _conference_name(state, hot_team)
            conf_rank = _conference_rank(state, hot_team)
            rank_text = f"#{conf_rank} {conf}" if conf_rank and conf else _record(hottest)
            metrics.append((
                "Hot streak",
                f"{hot_team} W{hot_len}",
                f"{_record(hottest)} · {rank_text}",
            ))

    max_games = max((_standing_games(row) for row in standings), default=0)
    min_games = max(1, math.ceil(max_games * 0.5))
    scoring_candidates: list[tuple[float, str, int]] = []
    for pid, totals in (getattr(state, "player_season_totals", {}) or {}).items():
        games = _int(getattr(totals, "games_played", 0))
        if games < min_games:
            continue
        ppg = _num(getattr(totals, "points", 0)) / max(1, games)
        scoring_candidates.append((ppg, str(pid), games))
    if scoring_candidates:
        ppg, pid, games = max(scoring_candidates, key=lambda row: row[0])
        team = _player_team(state, pid)
        metrics.insert(min(1, len(metrics)), (
            "Scoring leader",
            f"{ppg:.1f} PPG",
            f"{_player_name(state, pid)} · {team} · {games} GP",
        ))

    return metrics[:5]


def _select_preview_stories_v1(
    stories: Iterable[LeagueStoryV1],
    *,
    limit: int = 3,
) -> list[LeagueStoryV1]:
    values = list(stories)
    if not values or limit <= 0:
        return []
    selected: list[LeagueStoryV1] = [values[0]]
    used_categories = {values[0].category}
    for story in values[1:]:
        if len(selected) >= limit:
            break
        if story.category in used_categories:
            continue
        selected.append(story)
        used_categories.add(story.category)
    if len(selected) < limit:
        selected_ids = {story.story_id for story in selected}
        for story in values:
            if len(selected) >= limit:
                break
            if story.story_id in selected_ids:
                continue
            selected.append(story)
            selected_ids.add(story.story_id)
    return selected


def _story(
    story_id: str,
    category: str,
    kicker: str,
    headline: str,
    detail: str,
    priority: float,
    **kwargs: Any,
) -> LeagueStoryV1:
    return LeagueStoryV1(
        story_id=story_id,
        category=category,
        kicker=kicker,
        headline=headline,
        detail=detail,
        priority=float(priority),
        **kwargs,
    )


def _result_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    stories: list[LeagueStoryV1] = []
    recent = _completed_games(state)[-18:]
    for day_index, game_id, game in reversed(recent):
        home = _team(getattr(game, "home_team", ""))
        away = _team(getattr(game, "away_team", ""))
        home_score = _int(getattr(game, "home_score", 0))
        away_score = _int(getattr(game, "away_score", 0))
        if home_score == away_score or not home or not away:
            continue
        winner = home if home_score > away_score else away
        loser = away if winner == home else home
        winner_score = max(home_score, away_score)
        loser_score = min(home_score, away_score)
        margin = winner_score - loser_score
        overtime = _int(getattr(game, "overtime_periods", 0))
        if overtime:
            kicker = "OVERTIME FINAL"
            priority = 77 + min(overtime, 3) * 2
        elif margin >= 20:
            kicker = "STATEMENT WIN"
            priority = 72 + min(margin, 30) / 5
        else:
            kicker = "RECENT FINAL"
            priority = 56 + min(margin, 15) / 5
        if active_team and winner == active_team:
            priority += 4
        headline = (
            f"{team_name_resolver(winner)} beats "
            f"{team_name_resolver(loser)}, {winner_score}-{loser_score}"
        )
        detail_bits = [f"Margin {margin}", f"Combined {winner_score + loser_score} points"]
        if overtime:
            detail_bits.append(f"{overtime} OT" if overtime > 1 else "Overtime")
        result_metrics = [
            ("FINAL", f"{winner_score}-{loser_score}"),
            ("MARGIN", f"+{margin}"),
            ("TOTAL", str(winner_score + loser_score)),
        ]
        if overtime:
            result_metrics.append(("OT", str(overtime)))
        stories.append(
            _story(
                f"result:{game_id}",
                "Games",
                kicker,
                headline,
                " · ".join(detail_bits),
                priority,
                day_index=day_index,
                team=winner,
                opponent=loser,
                game_id=game_id,
                metrics=tuple(result_metrics),
            )
        )
    return stories


def _player_game_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    stories: list[LeagueStoryV1] = []
    seen_players: set[str] = set()
    for day_index, game_id, game in reversed(_completed_games(state)[-12:]):
        rows = list(getattr(game, "player_box_scores", ()) or ())
        rows.sort(
            key=lambda row: (
                _num(getattr(row, "points", 0))
                + 0.7 * _num(getattr(row, "rebounds", 0))
                + 0.9 * _num(getattr(row, "assists", 0))
                + 1.2 * _num(getattr(row, "steals", 0))
                + 1.2 * _num(getattr(row, "blocks", 0))
            ),
            reverse=True,
        )
        for row in rows[:4]:
            pid = _clean(getattr(row, "player_id", ""))
            if not pid or pid in seen_players:
                continue
            pts = _int(getattr(row, "points", 0))
            reb = _int(getattr(row, "rebounds", 0))
            ast = _int(getattr(row, "assists", 0))
            stl = _int(getattr(row, "steals", 0))
            blk = _int(getattr(row, "blocks", 0))
            team = _team(getattr(row, "team_abbreviation", "")) or _player_team(state, pid)
            home_team = _team(getattr(game, "home_team", ""))
            away_team = _team(getattr(game, "away_team", ""))
            if team and team == home_team:
                opponent = away_team
                opponent_prefix = "vs"
            elif team and team == away_team:
                opponent = home_team
                opponent_prefix = "at"
            else:
                opponent = ""
                opponent_prefix = "vs"
            opponent_context = (
                f"{opponent_prefix} {team_name_resolver(opponent)}"
                if opponent
                else ""
            )
            triple_double = sum(v >= 10 for v in (pts, reb, ast, stl, blk)) >= 3
            qualifying = triple_double or pts >= 25 or reb >= 16 or ast >= 13
            if not qualifying:
                continue
            name = _player_name(state, pid)
            fgm = _int(getattr(row, "field_goals_made", 0))
            fga = _int(getattr(row, "field_goals_attempted", 0))
            tpm = _int(getattr(row, "three_pointers_made", 0))
            tpa = _int(getattr(row, "three_pointers_attempted", 0))
            ftm = _int(getattr(row, "free_throws_made", 0))
            fta = _int(getattr(row, "free_throws_attempted", 0))
            ts_pct = _true_shooting(pts, fga, fta)
            if triple_double:
                kicker = "TRIPLE-DOUBLE"
                headline = f"{name} fills the box score for {team_name_resolver(team)}"
                priority = 84
            elif pts >= 40:
                kicker = "SCORING EXPLOSION"
                headline = f"{name} erupts for {pts} points"
                priority = 86 + min(pts - 40, 10) / 2
            elif pts >= 30:
                kicker = "PLAYER SPOTLIGHT"
                headline = f"{name} drops {pts} for {team_name_resolver(team)}"
                priority = 78 + min(pts - 30, 10) / 2
            elif ast >= 13:
                kicker = "PLAYMAKING MASTERCLASS"
                headline = f"{name} hands out {ast} assists"
                priority = 75
            else:
                kicker = "INTERIOR FORCE"
                headline = f"{name} controls the glass with {reb} rebounds"
                priority = 73
            if team == active_team:
                priority += 4
            detail_bits = []
            if opponent_context:
                detail_bits.append(opponent_context)
            detail_bits.extend([f"{pts} PTS", f"{reb} REB", f"{ast} AST"])
            if fga > 0:
                detail_bits.append(f"{fgm}/{fga} FG ({_pct(fgm, fga):.0f}%)")
            if tpa > 0:
                detail_bits.append(f"{tpm}/{tpa} 3PT")
            if fta > 0:
                detail_bits.append(f"{ftm}/{fta} FT")
            if ts_pct > 0:
                detail_bits.append(f"{ts_pct:.1f} TS%")
            statline = " · ".join(detail_bits)
            stories.append(
                _story(
                    f"player-game:{game_id}:{pid}",
                    "Players",
                    kicker,
                    headline,
                    statline,
                    priority,
                    day_index=day_index,
                    team=team,
                    opponent=opponent,
                    player_id=pid,
                    game_id=game_id,
                    statline=statline,
                    metrics=(
                        ("PTS", str(pts)),
                        ("REB", str(reb)),
                        ("AST", str(ast)),
                        ("TS%", f"{ts_pct:.1f}" if ts_pct > 0 else "—"),
                    ),
                )
            )
            seen_players.add(pid)
            break
    return stories


def _season_leader_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    standings = list((getattr(state, "standings", {}) or {}).values())
    max_games = max((_int(getattr(row, "games_played", 0)) for row in standings), default=0)
    min_games = max(1, math.ceil(max_games * 0.5))
    candidates: list[dict[str, Any]] = []
    for pid, totals in (getattr(state, "player_season_totals", {}) or {}).items():
        games = _int(getattr(totals, "games_played", 0))
        if games < min_games:
            continue
        candidates.append(
            {
                "pid": str(pid),
                "games": games,
                "ppg": _num(getattr(totals, "points", 0)) / games,
                "rpg": _num(getattr(totals, "rebounds", 0)) / games,
                "apg": _num(getattr(totals, "assists", 0)) / games,
                "fg_pct": _pct(
                    getattr(totals, "field_goals_made", 0),
                    getattr(totals, "field_goals_attempted", 0),
                ),
            }
        )
    if not candidates:
        return []
    specs = (
        ("ppg", "SCORING RACE", "sets the scoring pace", "PPG"),
        ("rpg", "GLASS LEADER", "leads the league on the glass", "RPG"),
        ("apg", "ASSIST LEADER", "paces the league in playmaking", "APG"),
    )
    stories: list[LeagueStoryV1] = []
    for key, kicker, phrase, suffix in specs:
        leader = max(candidates, key=lambda row: row[key])
        pid = leader["pid"]
        team = _player_team(state, pid)
        value = float(leader[key])
        priority = 66 + (3 if team == active_team else 0)
        detail = (
            f"{team_name_resolver(team)} · {leader['games']} GP · "
            f"{leader['ppg']:.1f} PPG · {leader['rpg']:.1f} RPG · {leader['apg']:.1f} APG"
        )
        if leader.get("fg_pct", 0.0) > 0:
            detail += f" · {leader['fg_pct']:.1f} FG%"
        stories.append(
            _story(
                f"season-leader:{key}:{pid}",
                "Players",
                kicker,
                f"{_player_name(state, pid)} {phrase} at {value:.1f} {suffix}",
                detail,
                priority,
                team=team,
                player_id=pid,
                statline=f"{value:.1f} {suffix}",
                metrics=(
                    ("PPG", f"{leader['ppg']:.1f}"),
                    ("RPG", f"{leader['rpg']:.1f}"),
                    ("APG", f"{leader['apg']:.1f}"),
                    ("GP", str(leader["games"])),
                ),
            )
        )
    return stories


def _standings_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    standings_map = getattr(state, "standings", {}) or {}
    standings = list(standings_map.values())
    if not standings:
        return []
    stories: list[LeagueStoryV1] = []
    ordered = sorted(
        standings,
        key=lambda row: (
            -_win_pct(row),
            -_point_diff(row),
            _team(getattr(row, "team_abbreviation", "")),
        ),
    )
    leader = ordered[0]
    leader_team = _team(getattr(leader, "team_abbreviation", ""))
    if _int(getattr(leader, "games_played", 0)) > 0:
        leader_ppg, leader_opp = _team_rates(leader)
        leader_conf = _conference_name(state, leader_team)
        leader_conf_rank = _conference_rank(state, leader_team)
        stories.append(
            _story(
                f"league-leader:{leader_team}",
                "Standings",
                "LEAGUE LEADER",
                f"{team_name_resolver(leader_team)} owns the NBA's best record at {_record(leader)}",
                f"{leader_ppg:.1f} PPG · {leader_opp:.1f} allowed · {_point_diff(leader):+.1f} differential",
                69 + (3 if leader_team == active_team else 0),
                team=leader_team,
                metrics=(
                    ("RECORD", _record(leader)),
                    ("WIN%", f"{_win_pct(leader) * 100:.0f}%"),
                    ("DIFF", f"{_point_diff(leader):+.1f}"),
                    ("CONF", f"#{leader_conf_rank} {leader_conf}" if leader_conf_rank else "—"),
                ),
            )
        )
    for conference in ("East", "West"):
        conference_rows = [
            row
            for row in standings
            if _clean(getattr((getattr(state, "teams", {}) or {}).get(_team(getattr(row, "team_abbreviation", ""))), "conference", "")).lower().startswith(conference.lower()[0])
        ]
        if len(conference_rows) < 2:
            continue
        conference_rows.sort(key=lambda row: (-_win_pct(row), -_point_diff(row)))
        first, second = conference_rows[:2]
        first_team = _team(getattr(first, "team_abbreviation", ""))
        second_team = _team(getattr(second, "team_abbreviation", ""))
        if _int(getattr(first, "games_played", 0)) <= 0:
            continue
        gap = (
            (_int(getattr(first, "wins", 0)) - _int(getattr(first, "losses", 0)))
            - (_int(getattr(second, "wins", 0)) - _int(getattr(second, "losses", 0)))
        ) / 2
        detail = (
            f"{team_name_resolver(second_team)} is {abs(gap):.1f} game"
            f"{'s' if abs(gap) != 1 else ''} back at {_record(second)}"
        )
        stories.append(
            _story(
                f"conference-race:{conference}:{first_team}:{second_team}",
                "Standings",
                f"{conference.upper()} RACE",
                f"{team_name_resolver(first_team)} leads the {conference} at {_record(first)}",
                detail,
                63 + (2 if active_team in {first_team, second_team} else 0),
                team=first_team,
                opponent=second_team,
                metrics=(
                    ("LEADER", _record(first)),
                    ("2ND", _record(second)),
                    ("GAP", f"{abs(gap):.1f} GB"),
                    ("DIFF", f"{_point_diff(first):+.1f}"),
                ),
            )
        )
    for row in ordered:
        length = _int(getattr(row, "streak_length", 0))
        if length < 2:
            continue
        streak_type = _clean(getattr(row, "streak_type", "")).upper()
        team = _team(getattr(row, "team_abbreviation", ""))
        if streak_type.startswith("W"):
            headline = f"{team_name_resolver(team)} has won {length} straight"
            kicker = "WINNING STREAK"
            priority = 73 + min(length, 8)
        elif streak_type.startswith("L"):
            headline = f"{team_name_resolver(team)} has dropped {length} in a row"
            kicker = "ROUGH PATCH"
            priority = 57 + min(length, 8)
        else:
            continue
        team_ppg, team_opp = _team_rates(row)
        conf = _conference_name(state, team)
        conf_rank = _conference_rank(state, team)
        stories.append(
            _story(
                f"streak:{team}:{streak_type}:{length}",
                "Standings",
                kicker,
                headline,
                f"{_record(row)} · {team_ppg:.1f} PPG · {team_opp:.1f} allowed · {_point_diff(row):+.1f} differential",
                priority + (3 if team == active_team else 0),
                team=team,
                metrics=(
                    ("STREAK", f"{streak_type[:1]}{length}"),
                    ("RECORD", _record(row)),
                    ("DIFF", f"{_point_diff(row):+.1f}"),
                    ("CONF", f"#{conf_rank} {conf}" if conf_rank and conf else "—"),
                ),
            )
        )
    return stories


def _injury_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    stories: list[LeagueStoryV1] = []
    for pid, injury in (getattr(state, "injuries", {}) or {}).items():
        status = _enum_text(getattr(injury, "status", ""))
        games = _int(getattr(injury, "games_remaining", 0))
        if status in {"", "healthy", "available"} and games <= 0:
            continue
        team = _player_team(state, str(pid))
        name = _player_name(state, str(pid))
        injury_type = _clean(getattr(injury, "injury_type", "")) or "medical issue"
        if games > 0:
            headline = f"{name} sidelined for roughly {games} game{'s' if games != 1 else ''}"
            detail = f"{team_name_resolver(team)} · {injury_type} · status {status.replace('_', ' ').title() or 'Unavailable'}"
        else:
            headline = f"{name} listed {status.replace('_', ' ').title()}"
            detail = f"{team_name_resolver(team)} · {injury_type}"
        priority = 75 if status in {"out", "doubtful"} or games >= 3 else 61
        if team == active_team:
            priority += 5
        stories.append(
            _story(
                f"injury:{pid}:{status}:{games}",
                "Health",
                "INJURY REPORT",
                headline,
                detail,
                priority,
                team=team,
                player_id=str(pid),
                metrics=(
                    ("STATUS", status.replace("_", " ").upper() or "OUT"),
                    ("GAMES", str(games) if games > 0 else "—"),
                ),
            )
        )
    return stories


def _trade_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    history = list(getattr(state, "franchise_transaction_history_v1", ()) or ())
    stories: list[LeagueStoryV1] = []
    for row in reversed(history[-8:]):
        if not isinstance(row, dict):
            continue
        txid = _clean(row.get("transaction_id"))
        a = _team(row.get("team_a"))
        b = _team(row.get("team_b"))
        if not txid or not a or not b:
            continue
        a_players = [_player_name(state, _clean(pid)) for pid in (row.get("side_a_player_ids") or [])]
        b_players = [_player_name(state, _clean(pid)) for pid in (row.get("side_b_player_ids") or [])]
        picks = len(row.get("side_a_pick_asset_ids") or []) + len(row.get("side_b_pick_asset_ids") or [])
        pieces: list[str] = []
        if a_players:
            pieces.append(f"{team_name_resolver(a)} sent {', '.join(a_players[:3])}")
        if b_players:
            pieces.append(f"{team_name_resolver(b)} sent {', '.join(b_players[:3])}")
        if picks:
            pieces.append(f"{picks} draft asset{'s' if picks != 1 else ''} moved")
        stories.append(
            _story(
                f"trade:{txid}",
                "Transactions",
                "TRADE WIRE",
                f"{team_name_resolver(a)} and {team_name_resolver(b)} complete a trade",
                " · ".join(pieces) or "The deal was committed to the franchise transaction ledger.",
                82 + (5 if active_team in {a, b} else 0),
                day_index=_int(row.get("day_index"), -1),
                team=a,
                opponent=b,
                metrics=(
                    ("PLAYERS", str(len(a_players) + len(b_players))),
                    ("PICKS", str(picks)),
                ),
            )
        )
    return stories


def _free_agency_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    history = list(getattr(state, "free_agency_transaction_history", ()) or ())
    stories: list[LeagueStoryV1] = []
    for row in reversed(history[-8:]):
        if not isinstance(row, dict):
            continue
        txid = _clean(row.get("transaction_id"))
        pid = _clean(row.get("player_id"))
        player_name = _clean(row.get("player_name")) or _player_name(state, pid)
        team = _team(row.get("team_abbreviation"))
        if not txid or not team or not player_name:
            continue
        salary = _num(row.get("annual_salary"), 0.0)
        years = _int(row.get("years"), 0)
        if salary >= 1_000_000:
            salary_text = f"${salary / 1_000_000:.1f}M annually"
        elif salary > 0:
            salary_text = f"${salary:,.0f} annually"
        else:
            salary_text = "salary recorded"
        term = f"{years}-year" if years > 0 else "new"
        stories.append(
            _story(
                f"signing:{txid}",
                "Transactions",
                "FREE AGENCY",
                f"{team_name_resolver(team)} signs {player_name}",
                f"{term} contract · {salary_text}",
                79 + (5 if team == active_team else 0),
                team=team,
                player_id=pid,
                metrics=(
                    ("YEARS", str(years) if years > 0 else "—"),
                    ("AAV", salary_text.replace(" annually", "")),
                ),
            )
        )
    return stories


def _postseason_stories(
    state: Any,
    *,
    team_name_resolver: Callable[[str], str],
    active_team: str,
) -> list[LeagueStoryV1]:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return []
    stories: list[LeagueStoryV1] = []
    champion = _team(getattr(postseason, "champion", ""))
    runner_up = _team(getattr(postseason, "runner_up", ""))
    if champion:
        stories.append(
            _story(
                f"champion:{getattr(getattr(state, 'settings', None), 'season_label', '')}:{champion}",
                "Postseason",
                "NBA CHAMPION",
                f"{team_name_resolver(champion)} wins the championship",
                (
                    f"Defeated {team_name_resolver(runner_up)} in the NBA Finals"
                    if runner_up
                    else "The title is now recorded in the durable franchise state."
                ),
                120 + (6 if champion == active_team else 0),
                team=champion,
                opponent=runner_up,
            )
        )
        return stories
    stage = _enum_text(getattr(postseason, "stage", ""))
    conference_champions = dict(getattr(postseason, "conference_champions", {}) or {})
    if conference_champions:
        champs = [team_name_resolver(_team(v)) for v in conference_champions.values() if _team(v)]
        if champs:
            stories.append(
                _story(
                    "postseason:conference-champions",
                    "Postseason",
                    "FINALS SET",
                    " vs. ".join(champs) + " advances to the NBA Finals",
                    "Conference champions are locked in the current postseason state.",
                    105,
                    team=_team(next(iter(conference_champions.values()), "")),
                )
            )
    elif stage and stage not in {"complete", "not_started"}:
        stories.append(
            _story(
                f"postseason-stage:{stage}",
                "Postseason",
                "PLAYOFF PICTURE",
                f"The postseason has reached {stage.replace('_', ' ').title()}",
                f"{len(getattr(postseason, 'completed_games', {}) or {})} postseason games are complete.",
                88,
            )
        )
    return stories


def build_league_stories_v1(
    state: Any,
    *,
    active_team: str,
    team_name_resolver: Callable[[str], str],
) -> list[LeagueStoryV1]:
    active_team = _team(active_team)
    stories: list[LeagueStoryV1] = []
    builders = (
        _postseason_stories,
        _trade_stories,
        _free_agency_stories,
        _injury_stories,
        _player_game_stories,
        _standings_stories,
        _season_leader_stories,
        _result_stories,
    )
    for builder in builders:
        stories.extend(
            builder(
                state,
                team_name_resolver=team_name_resolver,
                active_team=active_team,
            )
        )
    unique: dict[str, LeagueStoryV1] = {}
    for story in stories:
        prior = unique.get(story.story_id)
        if prior is None or story.priority > prior.priority:
            unique[story.story_id] = story
    ordered = sorted(
        unique.values(),
        key=lambda row: (row.priority, row.day_index, row.story_id),
        reverse=True,
    )
    if ordered:
        return ordered

    # Empty/preseason fallback that still comes from real schedule state.
    schedule = list((getattr(state, "schedule", {}) or {}).values())
    scheduled = [
        row for row in schedule
        if _enum_text(getattr(row, "status", "")) in {"scheduled", ""}
    ]
    scheduled.sort(key=lambda row: _int(getattr(row, "day_index", 0)))
    if scheduled:
        game = scheduled[0]
        home = _team(getattr(game, "home_team", ""))
        away = _team(getattr(game, "away_team", ""))
        return [
            _story(
                "season-opening:next-game",
                "Games",
                "NEXT ON THE CALENDAR",
                f"{team_name_resolver(away)} visits {team_name_resolver(home)}",
                "The league story feed will expand automatically as games and transactions are completed.",
                40,
                day_index=_int(getattr(game, "day_index", -1), -1),
                team=home,
                opponent=away,
                game_id=_clean(getattr(game, "game_id", "")),
            )
        ]
    return []


def _colors(team: str, resolver: Callable[[str], tuple[str, str]]) -> tuple[str, str]:
    try:
        values = resolver(team) if team else ("#CE1141", "#1f2937")
        if isinstance(values, (tuple, list)) and len(values) >= 2:
            return _clean(values[0]) or "#CE1141", _clean(values[1]) or "#1f2937"
    except Exception:
        pass
    return "#CE1141", "#1f2937"


def _headshot(
    resolver: Callable[..., str],
    *,
    player_id: str,
    player_name: str,
    team: str,
) -> str:
    if not player_id:
        return ""
    try:
        value = _clean(
            resolver(
                player_id,
                team=team,
                player_name=player_name,
            )
        )
        if value:
            return value
    except Exception:
        pass
    attempts = (
        (player_id, team, player_name),
        (player_id, team),
        (player_id,),
    )
    for args in attempts:
        try:
            value = _clean(resolver(*args))
        except Exception:
            continue
        if value:
            return value
    return ""


def _story_image(
    story: LeagueStoryV1,
    *,
    state: Any,
    team_logo_resolver: Callable[[str], str],
    player_headshot_resolver: Callable[..., str],
) -> str:
    if story.player_id:
        player = (getattr(state, "players", {}) or {}).get(story.player_id)
        url = _headshot(
            player_headshot_resolver,
            player_id=story.player_id,
            player_name=_clean(getattr(player, "player_name", "")),
            team=story.team,
        )
        if url:
            return url
    if story.team:
        try:
            return _clean(team_logo_resolver(story.team))
        except Exception:
            return ""
    return ""


def _story_card_html(
    story: LeagueStoryV1,
    *,
    state: Any,
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
    large: bool = False,
) -> str:
    primary, secondary = _colors(story.team, team_colors_resolver)
    image = _story_image(
        story,
        state=state,
        team_logo_resolver=team_logo_resolver,
        player_headshot_resolver=player_headshot_resolver,
    )
    image_html = (
        f'<img class="fm-story-img" src="{_esc(image)}" alt="">'
        if image
        else '<div class="fm-story-img fm-story-img-placeholder">NBA</div>'
    )
    large_class = " fm-story-card-hero" if large else ""
    metric_values = story.metrics[:4] if large else story.metrics[:3]
    metrics_html = ""
    if metric_values:
        metrics_html = '<div class="fm-story-metrics">' + "".join(
            '<div class="fm-story-metric">'
            f'<span>{_esc(label)}</span><strong>{_esc(value)}</strong>'
            '</div>'
            for label, value in metric_values
        ) + '</div>'
    return (
        f'<div class="fm-story-card{large_class}" style="--story-primary:{_esc(primary)};--story-secondary:{_esc(secondary)}">'
        '<div class="fm-story-art">'
        f'{image_html}'
        '</div>'
        '<div class="fm-story-copy">'
        f'<div class="fm-story-kicker">{_esc(story.kicker)} · {_esc(story.category)}</div>'
        f'<div class="fm-story-headline">{_esc(story.headline)}</div>'
        f'<div class="fm-story-detail">{_esc(story.detail)}</div>'
        f'{metrics_html}'
        '</div>'
        '</div>'
    )


def _league_metric_strip_html_v1(
    metrics: Iterable[tuple[str, str, str]],
) -> str:
    cards = []
    for label, value, detail in metrics:
        cards.append(
            '<div class="fm-league-metric">'
            f'<span>{_esc(label)}</span>'
            f'<strong>{_esc(value)}</strong>'
            f'<small>{_esc(detail)}</small>'
            '</div>'
        )
    if not cards:
        return ""
    return '<div class="fm-league-metric-strip">' + "".join(cards) + '</div>'


def inject_franchise_league_story_visuals_v1(
    *,
    primary: str = "#CE1141",
    secondary: str = "#0B0F17",
) -> None:
    st.markdown(
        f"""
<style>
.fm-story-preview-shell {{
  margin: .72rem 0 .78rem 0;
  padding: .78rem .9rem .72rem .9rem;
  border: 1px solid rgba(255,255,255,.09);
  border-radius: 24px;
  background:
    radial-gradient(circle at 95% 10%, {primary}26, transparent 34%),
    linear-gradient(145deg, rgba(8,13,22,.98), rgba(14,14,22,.98));
  box-shadow: 0 18px 50px rgba(0,0,0,.22);
}}
.fm-story-preview-title {{
  font-size: 1.05rem;
  font-weight: 850;
  color: #f8fafc;
  margin-bottom: .16rem;
}}
.fm-story-preview-sub {{
  color: #8ea0b7;
  font-size: .80rem;
  margin-bottom: .42rem;
}}
.fm-league-metric-strip {{
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  gap:8px;
  margin-top:.62rem;
}}
.fm-league-metric {{
  min-width:0;
  padding:9px 10px 8px;
  border:1px solid rgba(255,255,255,.075);
  border-radius:12px;
  background:rgba(255,255,255,.028);
}}
.fm-league-metric span {{
  display:block; color:#72859e; font-size:.48rem; font-weight:950; letter-spacing:.10em; text-transform:uppercase;
}}
.fm-league-metric strong {{
  display:block; margin-top:3px; color:#f8fbff; font-size:.82rem; font-weight:950; line-height:1.08;
}}
.fm-league-metric small {{
  display:block; margin-top:3px; color:#8799af; font-size:.52rem; line-height:1.25;
}}
.fm-story-card {{
  --story-primary:{primary};
  --story-secondary:{secondary};
  min-height: 164px;
  height: 100%;
  display: grid;
  grid-template-columns: 92px minmax(0,1fr);
  gap: .78rem;
  padding: .82rem;
  border-radius: 19px;
  border: 1px solid color-mix(in srgb, var(--story-primary) 36%, rgba(255,255,255,.10));
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--story-primary) 14%, #090e17), #080d15 72%);
  overflow: hidden;
}}
.fm-story-card-hero {{
  min-height: 260px;
  grid-template-columns: minmax(180px, 31%) minmax(0,1fr);
  align-items: center;
  padding: 1.2rem;
  border-radius: 26px;
}}
.fm-story-art {{
  min-height: 100%;
  border-radius: 15px;
  display:flex;
  align-items:center;
  justify-content:center;
  background: radial-gradient(circle at 50% 25%, color-mix(in srgb, var(--story-primary) 30%, transparent), transparent 65%);
  overflow:hidden;
}}
.fm-story-img {{
  display:block;
  width:100%;
  max-height: 146px;
  object-fit: contain;
  object-position:center bottom;
}}
.fm-story-card-hero .fm-story-img {{ max-height: 230px; }}
.fm-story-img-placeholder {{
  height:100%; min-height:120px; color:#64748b; font-size:.78rem; font-weight:900; letter-spacing:.14em;
}}
.fm-story-copy {{ align-self:center; min-width:0; }}
.fm-story-kicker {{
  color: color-mix(in srgb, var(--story-primary) 70%, #ffffff);
  text-transform: uppercase;
  letter-spacing: .12em;
  font-weight: 900;
  font-size: .61rem;
  margin-bottom: .42rem;
}}
.fm-story-headline {{
  color:#f8fafc;
  font-weight:900;
  font-size:1.02rem;
  line-height:1.14;
  margin-bottom:.42rem;
}}
.fm-story-card-hero .fm-story-headline {{ font-size: clamp(1.45rem, 2.2vw, 2.15rem); }}
.fm-story-detail {{
  color:#9aabc0;
  font-size:.75rem;
  line-height:1.42;
}}
.fm-story-metrics {{
  display:flex; flex-wrap:wrap; gap:5px; margin-top:.62rem;
}}
.fm-story-metric {{
  min-width:56px; padding:5px 7px; border-radius:9px;
  border:1px solid rgba(255,255,255,.075); background:rgba(255,255,255,.03);
}}
.fm-story-metric span {{
  display:block; color:#72849b; font-size:.42rem; font-weight:950; letter-spacing:.08em;
}}
.fm-story-metric strong {{
  display:block; margin-top:1px; color:#f8fbff; font-size:.65rem; font-weight:950;
}}
.fm-story-card-hero .fm-story-detail {{ font-size:.89rem; max-width:780px; }}
.fm-story-card-hero .fm-story-metric {{ min-width:72px; padding:7px 9px; }}
.fm-story-card-hero .fm-story-metric strong {{ font-size:.78rem; }}
.fm-story-section-label {{
  color:#70c8ff; text-transform:uppercase; letter-spacing:.15em; font-size:.65rem; font-weight:900; margin-bottom:.2rem;
}}
.fm-story-center-title {{ color:#f8fafc; font-size:2rem; font-weight:950; margin:0 0 .18rem 0; }}
.fm-story-center-sub {{ color:#91a2b6; margin-bottom:1rem; }}
/* HOME DENSITY V1.1: remove dead space without changing the command-center hierarchy. */
.fxv2-team-hero {{ min-height:300px !important; margin:10px 0 13px !important; }}
.fxv2-hero-copy {{ padding-top:30px !important; padding-bottom:24px !important; }}
.fxv2-logo {{ width:78px !important; height:78px !important; }}
.fxv2-next {{ margin-top:18px !important; }}
.fxv2-hero-desc {{ margin-top:11px !important; line-height:1.45 !important; }}
.fxv2-hero-player {{ height:300px !important; width:245px !important; }}
.fxv2-hero-player-1 {{ right:118px !important; }}
.fxv2-hero-player-2 {{ right:-10px !important; }}
.fxv2-hero-player-3 {{ right:228px !important; }}

@media (max-width: 1100px) {{
  .fm-league-metric-strip {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
}}
@media (max-width: 900px) {{
  .fm-story-card {{ grid-template-columns:72px minmax(0,1fr); min-height:145px; }}
  .fm-story-card-hero {{ grid-template-columns:1fr; }}
  .fm-story-card-hero .fm-story-art {{ max-height:190px; }}
  .fm-league-metric-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .fxv2-team-hero {{ min-height:500px !important; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )


def render_league_story_preview_v1(
    *,
    state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
    set_section: Callable[[str], None],
) -> None:
    stories = build_league_stories_v1(
        state,
        active_team=active_team,
        team_name_resolver=team_name_resolver,
    )
    if not stories:
        return
    pulse_metrics = _league_snapshot_metrics_v1(
        state,
        team_name_resolver=team_name_resolver,
    )
    metric_html = _league_metric_strip_html_v1(pulse_metrics)
    st.markdown(
        '<div class="fm-story-preview-shell">'
        '<div class="fm-story-preview-title">League pulse</div>'
        '<div class="fm-story-preview-sub">Real storylines and live statistical leaders from this franchise save.</div>'
        f'{metric_html}'
        '</div>',
        unsafe_allow_html=True,
    )
    preview_stories = _select_preview_stories_v1(stories, limit=3)
    cols = st.columns(min(3, len(preview_stories)))
    for index, story in enumerate(preview_stories[: len(cols)]):
        with cols[index]:
            st.markdown(
                _story_card_html(
                    story,
                    state=state,
                    team_logo_resolver=team_logo_resolver,
                    team_colors_resolver=team_colors_resolver,
                    player_headshot_resolver=player_headshot_resolver,
                ),
                unsafe_allow_html=True,
            )
    if st.button(
        "Open League Story Center",
        key="franchise_open_league_story_center_v1",
        width="stretch",
    ):
        set_section("League Stories")
        st.rerun()


def _render_story_grid(
    stories: Iterable[LeagueStoryV1],
    *,
    state: Any,
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
) -> None:
    values = list(stories)
    if not values:
        st.info("No saved-state storylines match this category yet.")
        return
    for start in range(0, len(values), 2):
        cols = st.columns(2)
        for offset, story in enumerate(values[start : start + 2]):
            with cols[offset]:
                st.markdown(
                    _story_card_html(
                        story,
                        state=state,
                        team_logo_resolver=team_logo_resolver,
                        team_colors_resolver=team_colors_resolver,
                        player_headshot_resolver=player_headshot_resolver,
                    ),
                    unsafe_allow_html=True,
                )


def render_league_story_center_v1(
    *,
    state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
) -> None:
    stories = build_league_stories_v1(
        state,
        active_team=active_team,
        team_name_resolver=team_name_resolver,
    )
    completed = len(getattr(state, "completed_games", {}) or {})
    current_day = _int(getattr(state, "current_day_index", 0))
    st.markdown('<div class="fm-story-section-label">NBA UNIVERSE</div>', unsafe_allow_html=True)
    st.markdown('<div class="fm-story-center-title">League Story Center</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="fm-story-center-sub">{len(stories)} live storyline{("s" if len(stories) != 1 else "")} · '
        f'{completed} regular-season result{("s" if completed != 1 else "")} saved · Day {current_day}</div>',
        unsafe_allow_html=True,
    )
    if not stories:
        st.info(
            "The story feed will populate automatically after the first saved games, injuries, signings, or trades."
        )
        return

    pulse_metrics = _league_snapshot_metrics_v1(
        state,
        team_name_resolver=team_name_resolver,
    )
    metric_html = _league_metric_strip_html_v1(pulse_metrics)
    if metric_html:
        st.markdown(metric_html, unsafe_allow_html=True)

    st.markdown(
        _story_card_html(
            stories[0],
            state=state,
            team_logo_resolver=team_logo_resolver,
            team_colors_resolver=team_colors_resolver,
            player_headshot_resolver=player_headshot_resolver,
            large=True,
        ),
        unsafe_allow_html=True,
    )

    active_team = _team(active_team)
    active_stories = [
        story
        for story in stories
        if active_team and active_team in {story.team, story.opponent}
    ][:6]
    if active_stories:
        st.markdown("### Your franchise in the news")
        _render_story_grid(
            active_stories,
            state=state,
            team_logo_resolver=team_logo_resolver,
            team_colors_resolver=team_colors_resolver,
            player_headshot_resolver=player_headshot_resolver,
        )

    tabs = st.tabs(
        [
            "Top Stories",
            "Games",
            "Players",
            "Standings",
            "Transactions & Health",
        ]
    )
    category_sets = (
        stories[:12],
        [story for story in stories if story.category in {"Games", "Postseason"}][:12],
        [story for story in stories if story.category == "Players"][:12],
        [story for story in stories if story.category == "Standings"][:12],
        [story for story in stories if story.category in {"Transactions", "Health"}][:12],
    )
    for tab, subset in zip(tabs, category_sets):
        with tab:
            _render_story_grid(
                subset,
                state=state,
                team_logo_resolver=team_logo_resolver,
                team_colors_resolver=team_colors_resolver,
                player_headshot_resolver=player_headshot_resolver,
            )

    with st.expander("Story generation rules", expanded=False):
        st.caption(
            "This center is presentation-only. It derives headlines from saved game results, "
            "player box scores and season totals, standings/streaks, injuries, committed franchise "
            "trades, free-agent signing history, and postseason state. It does not invent rumors, "
            "results, transactions, injuries, morale, or rivalry outcomes."
        )
