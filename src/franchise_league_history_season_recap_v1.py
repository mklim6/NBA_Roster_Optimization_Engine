from __future__ import annotations

import html
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Mapping

import streamlit as st

from franchise_generated_player_portraits_v1 import player_image_url
from franchise_player_stats_v1 import regular_season_player_rows
from franchise_timeline_trophy_room_v1 import build_franchise_legacy_snapshot_v1
from simulation_career_awards_v2 import (
    AWARD_META,
    PLAYOFF_AWARD_META,
    build_playoff_honors_v2,
    build_regular_awards_v2,
)
from simulation_postseason_v1 import PostseasonStage, get_postseason_state


LEAGUE_HISTORY_SEASON_RECAP_VERSION = (
    "franchise-league-history-season-recap-v1.2-inaugural-rookie-truth-2026-09-16"
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).strip().lower()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _standing_record(standing: Any) -> tuple[int, int, float]:
    if standing is None:
        return 0, 0, 0.0
    wins = max(0, _integer(_field(standing, "wins", 0)))
    losses = max(0, _integer(_field(standing, "losses", 0)))
    differential = (
        _number(_field(standing, "points_for", 0.0))
        - _number(_field(standing, "points_against", 0.0))
    )
    return wins, losses, differential


def _league_rank(state: Any, team: str) -> int:
    resolved = _text(team).upper()
    standings = getattr(state, "standings", {}) or {}
    ordered = sorted(
        standings.values(),
        key=lambda row: (
            -_integer(_field(row, "wins", 0)),
            -(
                _number(_field(row, "points_for", 0.0))
                - _number(_field(row, "points_against", 0.0))
            ),
            -_number(_field(row, "points_for", 0.0)),
            _text(_field(row, "team_abbreviation", "")),
        ),
    )
    for rank, row in enumerate(ordered, start=1):
        if _text(_field(row, "team_abbreviation", "")).upper() == resolved:
            return rank
    return 0



def _season_start_from_label(season_label: str) -> int:
    text = _text(season_label)
    if not text:
        return 0
    head = text.split("-", 1)[0].strip()
    return _integer(head, 0)


def _player_season_rows(
    *,
    state: Any,
    team: str = "",
    minimum_games: int = 1,
) -> list[dict[str, Any]]:
    resolved_team = _text(team).upper()
    output: list[dict[str, Any]] = []
    for player_id, totals in (getattr(state, "player_season_totals", {}) or {}).items():
        games = max(0, _integer(_field(totals, "games_played", 0)))
        if games < minimum_games:
            continue
        player = (getattr(state, "players", {}) or {}).get(player_id)
        if player is None:
            continue

        team_abbr = _text(getattr(player, "team_abbreviation", "")).upper()
        if resolved_team and team_abbr != resolved_team:
            continue

        points = _integer(_field(totals, "points", 0))
        rebounds = _integer(_field(totals, "rebounds", 0))
        assists = _integer(_field(totals, "assists", 0))
        steals = _integer(_field(totals, "steals", 0))
        blocks = _integer(_field(totals, "blocks", 0))
        minutes = _number(_field(totals, "minutes", 0.0))
        output.append(
            {
                "player_id": str(player_id),
                "Player": _text(getattr(player, "player_name", "")) or str(player_id),
                "Team": team_abbr,
                "Pos": _text(getattr(player, "position", "")),
                "GP": games,
                "MIN": round(minutes / max(1, games), 1),
                "PTS": round(points / max(1, games), 1),
                "REB": round(rebounds / max(1, games), 1),
                "AST": round(assists / max(1, games), 1),
                "STL": round(steals / max(1, games), 1),
                "BLK": round(blocks / max(1, games), 1),
                "image_url": player_image_url(
                    player_id,
                    team=team_abbr,
                    player_name=_text(getattr(player, "player_name", "")),
                ),
            }
        )
    output.sort(
        key=lambda row: (
            -_number(row.get("PTS")),
            -_number(row.get("AST")),
            -_number(row.get("REB")),
            row.get("Player", ""),
        )
    )
    return output


def _leader_for(rows: list[dict[str, Any]], stat: str) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            _number(row.get(stat)),
            _number(row.get("GP")),
            row.get("Player", ""),
        ),
        default=None,
    )


def _season_specific_roy_winner(
    *,
    state: Any,
    season_label: str,
) -> dict[str, Any] | None:
    season_start = _season_start_from_label(season_label)
    standings = getattr(state, "standings", {}) or {}
    players = getattr(state, "players", {}) or {}
    totals_map = getattr(state, "player_season_totals", {}) or {}

    candidates: list[dict[str, Any]] = []
    for player_id, totals in totals_map.items():
        games = max(0, _integer(_field(totals, "games_played", 0)))
        if games <= 0:
            continue
        player = players.get(player_id)
        if player is None:
            continue

        rookie_season = _text(getattr(player, "rookie_season", ""))
        rookie_start = _integer(getattr(player, "rookie_season_start", 0))
        draft_year = _integer(getattr(player, "draft_year", 0))
        years_of_service = _integer(getattr(player, "years_of_service", 99))
        rookie_like = (
            (rookie_season and rookie_season == season_label)
            or (rookie_start and rookie_start == season_start)
            or (draft_year and draft_year == season_start and years_of_service <= 1)
        )
        if not rookie_like:
            continue

        team_abbr = _text(getattr(player, "team_abbreviation", "")).upper()
        wins = _integer(_field(standings.get(team_abbr), "wins", 0))
        points = _integer(_field(totals, "points", 0))
        rebounds = _integer(_field(totals, "rebounds", 0))
        assists = _integer(_field(totals, "assists", 0))
        steals = _integer(_field(totals, "steals", 0))
        blocks = _integer(_field(totals, "blocks", 0))

        ppg = round(points / max(1, games), 1)
        rpg = round(rebounds / max(1, games), 1)
        apg = round(assists / max(1, games), 1)
        spg = round(steals / max(1, games), 1)
        bpg = round(blocks / max(1, games), 1)
        score = (
            ppg * 1.55
            + apg * 1.10
            + rpg * 0.95
            + spg * 1.75
            + bpg * 1.55
            + wins * 0.08
        )
        candidates.append(
            {
                "subject_name": _text(getattr(player, "player_name", "")),
                "subject_team": team_abbr,
                "player_id": str(player_id),
                "image_url": player_image_url(
                    player_id,
                    team=team_abbr,
                    player_name=_text(getattr(player, "player_name", "")),
                ),
                "detail": f"{ppg:.1f} PPG · {rpg:.1f} REB · {apg:.1f} AST · {games} GP",
                "_score": score,
            }
        )

    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (-_number(row.get("_score")), row.get("subject_name", ""))
    )
    winner = dict(candidates[0])
    winner["detail"] = winner.get("detail", "") + " · season-specific rookie fallback"
    return winner


def _safe_regular_awards(state: Any) -> dict[str, Any]:
    try:
        payload = build_regular_awards_v2(state)
    except Exception:
        return {"ready": False, "awards": {}}
    return payload if isinstance(payload, dict) else {"ready": False, "awards": {}}


def _safe_playoff_honors(state: Any) -> dict[str, Any]:
    try:
        payload = build_playoff_honors_v2(state)
    except Exception:
        return {"ready": False}
    return payload if isinstance(payload, dict) else {"ready": False}


def _award_winner(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    candidates = (payload.get("awards", {}) or {}).get(key, []) if isinstance(payload, dict) else []
    if not candidates:
        return None
    winner = candidates[0]
    return dict(winner) if isinstance(winner, Mapping) else None


def _honor_winner(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    winner = payload.get(key) if isinstance(payload, dict) else None
    return dict(winner) if isinstance(winner, Mapping) else None


def _award_card(
    *,
    title: str,
    short: str,
    icon: str,
    winner: dict[str, Any] | None,
    empty_name: str = "Not available",
    empty_detail: str = "No eligible winner is available from the current save state.",
) -> str:
    if winner is None:
        name, team, detail, image = empty_name, "", empty_detail, ""
    else:
        name = _text(winner.get("subject_name", winner.get("player_name", ""))) or "Not available"
        team = _text(winner.get("subject_team", winner.get("team", "")))
        detail = _text(winner.get("detail", ""))
        image = _text(winner.get("image_url", ""))
    image_html = (
        f'<img class="flh-award-img" src="{html.escape(image)}" alt="">'
        if image else f'<div class="flh-award-fallback">{html.escape(icon)}</div>'
    )
    return (
        '<div class="flh-award-card">'
        f'<div class="flh-award-chip">{html.escape(icon)} {html.escape(short)}</div>'
        f'<div class="flh-award-row">{image_html}<div>'
        f'<div class="flh-award-name">{html.escape(name)}</div>'
        f'<div class="flh-award-team">{html.escape(team)}</div></div></div>'
        f'<div class="flh-award-title">{html.escape(title)}</div>'
        f'<div class="flh-award-detail">{html.escape(detail)}</div>'
        '</div>'
    )


def _current_draft_rows(state: Any, team: str) -> list[dict[str, Any]]:
    resolved = _text(team).upper()
    output: list[dict[str, Any]] = []
    for draft_index, draft in enumerate(list(getattr(state, "franchise_draft_history_v1", ()) or ())):
        season = _text(_field(draft, "target_season", "")) or _text(_field(draft, "source_season", ""))
        year = _integer(_field(draft, "draft_year", 0))
        for pick in list(_field(draft, "draft_order", ()) or ()):
            if _text(_field(pick, "owner_team", "")).upper() != resolved:
                continue
            player = _text(_field(pick, "player_name", ""))
            if not player:
                continue
            output.append({
                "season": season or (str(year) if year else "Draft"),
                "pick": _integer(_field(pick, "overall_pick", 0)),
                "player": player,
                "position": _text(_field(pick, "position", "")),
                "school": _text(_field(pick, "school", "")),
                "draft_index": draft_index,
            })
    output.sort(key=lambda row: (-row["draft_index"], row["pick"] if row["pick"] else 999, row["player"]))
    return output


def _transaction_events(legacy_payload: dict[str, Any], *, current_season: str) -> list[dict[str, Any]]:
    events = [row for row in list(legacy_payload.get("timeline", []) or []) if row.get("category") in {"Trade", "Signing"}]
    current = [row for row in events if _text(row.get("season")) == _text(current_season)]
    return (current or events)[:6]


def _championship_rows(*, state: Any, current_season: str, playoff_honors: dict[str, Any], team_name_resolver: Callable[[str], str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for archive in list(getattr(state, "season_history", ()) or ()):
        rows.append({
            "season": _text(_field(archive, "season_label", "")),
            "champion": _text(_field(archive, "champion", "")).upper(),
            "runner_up": _text(_field(archive, "runner_up", "")).upper(),
            "current": False,
        })
    live_champion = _text(playoff_honors.get("champion", "")).upper()
    live_runner = _text(playoff_honors.get("runner_up", "")).upper()
    if live_champion and not any(_text(row["season"]) == _text(current_season) for row in rows):
        rows.append({"season": current_season, "champion": live_champion, "runner_up": live_runner, "current": True})
    rows.sort(key=lambda row: row["season"], reverse=True)
    for row in rows:
        row["champion_name"] = team_name_resolver(row["champion"]) if row["champion"] else "Not recorded"
        row["runner_up_name"] = team_name_resolver(row["runner_up"]) if row["runner_up"] else "Not recorded"
    return rows


def build_league_history_season_recap_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
) -> dict[str, Any]:
    team = _text(active_team).upper()
    season = _text(
        getattr(getattr(state, "settings", None), "season_label", "")
    ) or "Current Season"
    phase = _enum(getattr(state, "phase", ""))

    standing = (getattr(state, "standings", {}) or {}).get(team)
    wins, losses, diff = _standing_record(standing)
    rank = _league_rank(state, team)
    games = wins + losses

    regular_awards = _safe_regular_awards(state)
    playoff_honors = _safe_playoff_honors(state)
    postseason = get_postseason_state(state, required=False)
    postseason_stage = (
        _enum(getattr(postseason, "stage", ""))
        if postseason is not None else ""
    )

    champion = _text(playoff_honors.get("champion", "")).upper()
    runner_up = _text(playoff_honors.get("runner_up", "")).upper()
    completed_season = (
        games >= 82
        or postseason_stage == _enum(PostseasonStage.COMPLETE)
        or bool(champion)
    )

    league_rows = _player_season_rows(state=state, minimum_games=1)
    team_rows = _player_season_rows(state=state, team=team, minimum_games=1)

    legacy = build_franchise_legacy_snapshot_v1(
        state=state,
        trade_state=trade_state,
        active_team=team,
        team_name_resolver=team_name_resolver,
    )
    draft_rows = _current_draft_rows(state, team)
    transactions = _transaction_events(
        legacy,
        current_season=season,
    )
    championships = _championship_rows(
        state=state,
        current_season=season,
        playoff_honors=playoff_honors,
        team_name_resolver=team_name_resolver,
    )

    roy_display = _award_winner(regular_awards, "roy")
    if roy_display is None:
        roy_display = _season_specific_roy_winner(
            state=state,
            season_label=season,
        )

    played_rookie_count = 0
    for row in league_rows:
        player = (getattr(state, "players", {}) or {}).get(row.get("player_id"))
        if player is None:
            continue
        if (
            _text(getattr(player, "rookie_season", "")) == season
            and _integer(row.get("GP", 0)) > 0
        ):
            played_rookie_count += 1

    return {
        "version": LEAGUE_HISTORY_SEASON_RECAP_VERSION,
        "team": team,
        "team_name": team_name_resolver(team),
        "season": season,
        "phase": phase,
        "games": games,
        "wins": wins,
        "losses": losses,
        "point_diff": round(diff, 1),
        "league_rank": rank,
        "completed_season": completed_season,
        "champion": champion,
        "runner_up": runner_up,
        "champion_name": (
            team_name_resolver(champion) if champion else ""
        ),
        "runner_up_name": (
            team_name_resolver(runner_up) if runner_up else ""
        ),
        "regular_awards": regular_awards,
        "playoff_honors": playoff_honors,
        "roy_winner": roy_display,
        "played_rookie_count": played_rookie_count,
        "league_scoring_leader": _leader_for(league_rows, "PTS"),
        "league_rebounding_leader": _leader_for(league_rows, "REB"),
        "league_assist_leader": _leader_for(league_rows, "AST"),
        "team_scoring_leader": _leader_for(team_rows, "PTS"),
        "team_rebounding_leader": _leader_for(team_rows, "REB"),
        "team_assist_leader": _leader_for(team_rows, "AST"),
        "draft_rows": draft_rows,
        "transactions": transactions,
        "championship_rows": championships,
        "legacy": legacy,
    }

def inject_league_history_season_recap_visuals_v1(
    *,
    primary: str,
    secondary: str,
) -> None:
    p = html.escape(_text(primary) or "#CE1141")
    s = html.escape(_text(secondary) or "#0B0D12")
    st.markdown(
        f"""
<style>
.flh-hero{{position:relative;overflow:hidden;padding:24px 25px;margin:2px 0 14px;border:1px solid rgba(255,255,255,.09);border-radius:22px;background:radial-gradient(circle at 92% 0%,{p}38,transparent 35%),linear-gradient(140deg,#08121e,#0b0f17 68%,{s}66)}}
.flh-kicker{{color:#7dd3fc;font-size:.62rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}}
.flh-title{{margin-top:5px;color:#fff;font-size:1.85rem;line-height:1.05;font-weight:950}}
.flh-copy{{max-width:850px;margin-top:7px;color:#91a4b9;font-size:.73rem;line-height:1.5}}
.flh-metrics{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:10px 0 14px}}
.flh-metric{{padding:13px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:#09131f}}
.flh-metric small{{display:block;color:#71849a;font-size:.48rem;font-weight:950;letter-spacing:.11em;text-transform:uppercase}}
.flh-metric strong{{display:block;margin-top:4px;color:#fff;font-size:1rem}}
.flh-metric span{{display:block;margin-top:3px;color:#8194aa;font-size:.54rem}}
.flh-champ{{display:grid;grid-template-columns:1fr 50px 1fr;gap:11px;align-items:center;padding:15px;border-radius:16px;background:linear-gradient(120deg,#0a1420,#0b111a);border:1px solid rgba(255,255,255,.075);margin:8px 0 13px}}
.flh-team{{display:flex;gap:10px;align-items:center}} .flh-team.right{{justify-content:flex-end;text-align:right}}
.flh-logo{{width:54px;height:54px;object-fit:contain}} .flh-team small{{display:block;color:#71849a;font-size:.48rem;font-weight:950;letter-spacing:.1em;text-transform:uppercase}}
.flh-team strong{{display:block;margin-top:3px;color:#fff;font-size:.9rem}} .flh-vs{{text-align:center;color:#516175;font-size:.58rem;font-weight:950}}
.flh-award-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:10px 0 14px}}
.flh-award-card{{min-height:145px;padding:12px;border:1px solid rgba(255,255,255,.07);border-radius:14px;background:#09131f}}
.flh-award-chip{{color:#7dd3fc;font-size:.48rem;font-weight:950;letter-spacing:.09em;text-transform:uppercase}}
.flh-award-row{{display:grid;grid-template-columns:48px 1fr;gap:8px;align-items:center;margin-top:8px}}
.flh-award-img,.flh-award-fallback{{width:48px;height:48px;border-radius:10px;object-fit:cover;background:#101b29;display:flex;align-items:center;justify-content:center;font-size:1.2rem}}
.flh-award-name{{color:#fff;font-size:.72rem;font-weight:950}} .flh-award-team{{color:#8194a8;font-size:.51rem}}
.flh-award-title{{margin-top:7px;color:#a9b9ca;font-size:.54rem;font-weight:850}} .flh-award-detail{{margin-top:3px;color:#708297;font-size:.49rem;line-height:1.35}}
.flh-leader-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:9px 0}}
.flh-leader{{padding:12px;border-radius:13px;border:1px solid rgba(255,255,255,.07);background:#09131f}}
.flh-leader-row{{display:grid;grid-template-columns:54px 1fr;gap:10px;align-items:center}}
.flh-leader-img,.flh-leader-fallback{{width:54px;height:54px;border-radius:12px;object-fit:cover;background:#101b29;display:flex;align-items:center;justify-content:center;font-size:1.2rem}}
.flh-leader small{{display:block;color:#71849a;font-size:.48rem;font-weight:950;text-transform:uppercase;letter-spacing:.1em}}
.flh-leader strong{{display:block;margin-top:3px;color:#fff;font-size:.76rem}}
.flh-leader em{{display:block;margin-top:2px;color:#8296ac;font-style:normal;font-size:.52rem}}
.flh-leader span{{display:block;margin-top:4px;color:#7dd3fc;font-size:.62rem;font-weight:900}}
.flh-history-row{{display:grid;grid-template-columns:90px 1fr 28px 1fr;gap:10px;align-items:center;padding:10px 4px;border-bottom:1px solid rgba(255,255,255,.06)}}
.flh-season{{color:#7dd3fc;font-size:.62rem;font-weight:950}} .flh-history-team{{display:flex;align-items:center;gap:7px;color:#eef6ff;font-size:.63rem;font-weight:850}} .flh-history-logo{{width:30px;height:30px;object-fit:contain}} .flh-arrow{{color:#53657a;text-align:center}}
.flh-list-card{{padding:12px 13px;border:1px solid rgba(255,255,255,.07);border-radius:13px;background:#09131f;margin-top:7px}} .flh-list-card small{{color:#7dd3fc;font-size:.48rem;font-weight:950;text-transform:uppercase;letter-spacing:.1em}} .flh-list-card strong{{display:block;margin-top:3px;color:#fff;font-size:.7rem}} .flh-list-card span{{display:block;margin-top:3px;color:#8193a7;font-size:.54rem;line-height:1.4}}
@media(max-width:1050px){{.flh-metrics{{grid-template-columns:repeat(3,minmax(0,1fr))}}.flh-award-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:650px){{.flh-metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.flh-award-grid,.flh-leader-grid{{grid-template-columns:1fr}}.flh-champ{{grid-template-columns:1fr}}.flh-vs{{display:none}}.flh-team.right{{justify-content:flex-start;text-align:left}}.flh-history-row{{grid-template-columns:72px 1fr}}.flh-arrow,.flh-history-row>div:nth-child(4){{display:none}}}}
</style>
""",
        unsafe_allow_html=True,
    )

def _leader_card(label: str, row: dict[str, Any] | None, stat: str) -> str:
    if not row:
        return (
            '<div class="flh-leader">'
            '<div class="flh-leader-row">'
            f'<div class="flh-leader-fallback">{html.escape(label[:1])}</div>'
            f'<div><small>{html.escape(label)}</small><strong>Not available</strong><em>—</em><span>—</span></div>'
            '</div></div>'
        )
    image = _text(row.get("image_url", ""))
    image_html = (
        f'<img class="flh-leader-img" src="{html.escape(image)}" alt="">'
        if image else
        f'<div class="flh-leader-fallback">{html.escape(_text(row.get("Pos"))[:1] or "P")}</div>'
    )
    subline = " · ".join(
        part for part in (
            _text(row.get("Team")),
            _text(row.get("Pos")),
            f'{_integer(row.get("GP", 0))} GP' if _integer(row.get("GP", 0)) else "",
        ) if part
    )
    return (
        '<div class="flh-leader">'
        '<div class="flh-leader-row">'
        f'{image_html}<div>'
        f'<small>{html.escape(label)}</small>'
        f'<strong>{html.escape(_text(row.get("Player")))}</strong>'
        f'<em>{html.escape(subline)}</em>'
        f'<span>{html.escape(str(row.get(stat, "—")))} {html.escape(stat)}</span>'
        '</div></div></div>'
    )

def render_league_history_season_recap_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    primary: str,
    secondary: str,
) -> None:
    payload = build_league_history_season_recap_v1(
        state=state,
        trade_state=trade_state,
        active_team=active_team,
        team_name_resolver=team_name_resolver,
    )
    inject_league_history_season_recap_visuals_v1(
        primary=primary,
        secondary=secondary,
    )

    completion_copy = (
        "Completed season recap"
        if payload["completed_season"]
        else "Live season snapshot"
    )
    st.markdown(
        (
            '<div class="flh-hero">'
            f'<div class="flh-kicker">LEAGUE ARCHIVE · {html.escape(completion_copy)}</div>'
            f'<div class="flh-title">{html.escape(payload["season"])} Season Recap</div>'
            '<div class="flh-copy">A league-wide archive built from the durable franchise universe: '
            'standings, postseason results, award models, draft history and transactions. '
            'The current completed season appears here immediately even before it is rolled into the next season archive.</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )

    champion_copy = payload["champion_name"] or "Not decided"
    metrics = [
        ("Your record", f'{payload["wins"]}-{payload["losses"]}', payload["team_name"]),
        ("League rank", f'#{payload["league_rank"]}' if payload["league_rank"] else "—", "Regular season"),
        ("Point diff", f'{payload["point_diff"]:+.0f}', "Net points"),
        ("Champion", champion_copy, payload["season"]),
        ("Archive", str(len(payload["championship_rows"])), "Championship seasons"),
    ]
    st.markdown(
        '<div class="flh-metrics">'
        + "".join(
            '<div class="flh-metric">'
            f'<small>{html.escape(label)}</small><strong>{html.escape(value)}</strong><span>{html.escape(sub)}</span>'
            '</div>'
            for label, value, sub in metrics
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(
        [
            "🏆 Season Recap",
            "📚 League History",
            "🏅 Awards & Honors",
            "🧾 Draft & Moves",
        ]
    )

    with tabs[0]:
        if payload["champion"]:
            champion_logo = team_logo_resolver(payload["champion"])
            runner_logo = team_logo_resolver(payload["runner_up"])
            st.markdown(
                (
                    '<div class="flh-champ">'
                    '<div class="flh-team">'
                    f'<img class="flh-logo" src="{html.escape(champion_logo)}" alt="">'
                    f'<div><small>NBA CHAMPION</small><strong>{html.escape(payload["champion_name"])}</strong></div></div>'
                    '<div class="flh-vs">DEFEATED</div>'
                    '<div class="flh-team right">'
                    f'<div><small>NBA FINALS</small><strong>{html.escape(payload["runner_up_name"] or "Runner-Up")}</strong></div>'
                    f'<img class="flh-logo" src="{html.escape(runner_logo)}" alt=""></div>'
                    '</div>'
                ),
                unsafe_allow_html=True,
            )
        else:
            st.info("The NBA champion will appear here as soon as the postseason is complete.")

        regular = payload["regular_awards"]
        award_cards = []
        for key in ("mvp", "dpoy"):
            meta = AWARD_META[key]
            award_cards.append(
                _award_card(
                    title=meta["label"],
                    short=meta["short"],
                    icon=meta["icon"],
                    winner=_award_winner(regular, key),
                )
            )
        award_cards.append(
            _award_card(
                title=AWARD_META["roy"]["label"],
                short=AWARD_META["roy"]["short"],
                icon=AWARD_META["roy"]["icon"],
                winner=payload.get("roy_winner"),
                empty_name="No qualifying rookie class",
                empty_detail=(
                    f'{payload.get("played_rookie_count", 0)} rookies logged a regular-season game '
                    f'in {payload["season"]}. No Rookie of the Year was awarded in this opening universe.'
                ),
            )
        )
        finals_meta = PLAYOFF_AWARD_META["finals_mvp"]
        award_cards.append(
            _award_card(
                title=finals_meta["label"],
                short=finals_meta["short"],
                icon=finals_meta["icon"],
                winner=_honor_winner(payload["playoff_honors"], "finals_mvp"),
            )
        )
        st.markdown(
            '<div class="flh-award-grid">' + "".join(award_cards) + '</div>',
            unsafe_allow_html=True,
        )

        st.markdown("#### League leaders")
        st.markdown(
            '<div class="flh-leader-grid">'
            + _leader_card("Scoring", payload["league_scoring_leader"], "PTS")
            + _leader_card("Rebounding", payload["league_rebounding_leader"], "REB")
            + _leader_card("Assists", payload["league_assist_leader"], "AST")
            + '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"#### {payload['team_name']} leaders")
        st.markdown(
            '<div class="flh-leader-grid">'
            + _leader_card("Scoring", payload["team_scoring_leader"], "PTS")
            + _leader_card("Rebounding", payload["team_rebounding_leader"], "REB")
            + _leader_card("Assists", payload["team_assist_leader"], "AST")
            + '</div>',
            unsafe_allow_html=True,
        )

    with tabs[1]:
        if not payload["championship_rows"]:
            st.info(
                "No championship history has been recorded yet. "
                "Completed seasons will build this league archive automatically."
            )
        else:
            history_html = []
            for row in payload["championship_rows"]:
                champion_logo = team_logo_resolver(row["champion"])
                runner_logo = team_logo_resolver(row["runner_up"])
                history_html.append(
                    '<div class="flh-history-row">'
                    f'<div class="flh-season">{html.escape(row["season"])}</div>'
                    '<div class="flh-history-team">'
                    f'<img class="flh-history-logo" src="{html.escape(champion_logo)}" alt="">'
                    f'{html.escape(row["champion_name"])}</div>'
                    '<div class="flh-arrow">→</div>'
                    '<div class="flh-history-team">'
                    f'<img class="flh-history-logo" src="{html.escape(runner_logo)}" alt="">'
                    f'{html.escape(row["runner_up_name"])}</div>'
                    '</div>'
                )
            st.markdown(
                '<div>' + "".join(history_html) + '</div>',
                unsafe_allow_html=True,
            )

        st.caption(
            "Champion/runner-up history is sourced only from the live completed postseason "
            "or durable SeasonArchive records. No historical result is fabricated."
        )

    with tabs[2]:
        regular = payload["regular_awards"]
        cards = []
        for key in ("mvp", "dpoy"):
            meta = AWARD_META[key]
            cards.append(
                _award_card(
                    title=meta["label"],
                    short=meta["short"],
                    icon=meta["icon"],
                    winner=_award_winner(regular, key),
                )
            )
        cards.append(
            _award_card(
                title=AWARD_META["roy"]["label"],
                short=AWARD_META["roy"]["short"],
                icon=AWARD_META["roy"]["icon"],
                winner=payload.get("roy_winner"),
                empty_name="No qualifying rookie class",
                empty_detail=(
                    f'{payload.get("played_rookie_count", 0)} rookies logged a regular-season game '
                    f'in {payload["season"]}. No Rookie of the Year was awarded in this opening universe.'
                ),
            )
        )
        for key in ("smoy", "mip", "clutch", "coach", "executive"):
            meta = AWARD_META[key]
            cards.append(
                _award_card(
                    title=meta["label"],
                    short=meta["short"],
                    icon=meta["icon"],
                    winner=_award_winner(regular, key),
                )
            )
        st.markdown(
            '<div class="flh-award-grid">' + "".join(cards) + '</div>',
            unsafe_allow_html=True,
        )

        playoff = payload["playoff_honors"]
        playoff_cards = []
        for key in ("east_cf_mvp", "west_cf_mvp", "finals_mvp"):
            meta = PLAYOFF_AWARD_META[key]
            playoff_cards.append(
                _award_card(
                    title=meta["label"],
                    short=meta["short"],
                    icon=meta["icon"],
                    winner=_honor_winner(playoff, key),
                )
            )
        st.markdown("#### Postseason honors")
        st.markdown(
            '<div class="flh-award-grid">' + "".join(playoff_cards) + '</div>',
            unsafe_allow_html=True,
        )

        st.caption(
            "These current-season awards use the existing certified awards engine. "
            "Legacy names Rookie of the Year only when at least one correctly tagged rookie "
            "actually logged regular-season games. It never invents an inaugural-season winner."
        )

    with tabs[3]:
        left, right = st.columns(2)
        with left:
            st.markdown("#### Your recent draft selections")
            if payload["draft_rows"]:
                for row in payload["draft_rows"][:8]:
                    pick = f"No. {row['pick']}" if row["pick"] else "Draft pick"
                    extra = " · ".join(
                        part for part in (
                            row["position"],
                            row["school"],
                        ) if part
                    )
                    detail = pick + (f" · {extra}" if extra else "")
                    st.markdown(
                        (
                            '<div class="flh-list-card">'
                            f'<small>{html.escape(row["season"])}</small>'
                            f'<strong>{html.escape(row["player"])}</strong>'
                            f'<span>{html.escape(detail)}</span>'
                            '</div>'
                        ),
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No durable draft selections have been recorded for this franchise yet.")

        with right:
            st.markdown("#### Recent roster moves")
            if payload["transactions"]:
                for row in payload["transactions"]:
                    st.markdown(
                        (
                            '<div class="flh-list-card">'
                            f'<small>{html.escape(_text(row.get("category")))}</small>'
                            f'<strong>{html.escape(_text(row.get("title")))}</strong>'
                            f'<span>{html.escape(_text(row.get("detail")))}</span>'
                            '</div>'
                        ),
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No saved trades or free-agent signings are available for this franchise yet.")

    st.caption(
        "The existing Franchise Timeline, Trophy Room and franchise record book continue below. "
        "This recap adds league-wide context without replacing those durable legacy surfaces."
    )