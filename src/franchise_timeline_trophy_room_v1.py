from __future__ import annotations

import html
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Iterable, Mapping

import streamlit as st


FRANCHISE_TIMELINE_TROPHY_ROOM_VERSION = "franchise-timeline-trophy-room-v1.0-2026-09-11"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum(value: Any) -> str:
    return _text(getattr(value, "value", value)).lower()


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _rows(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in list(value or ()):
        if isinstance(row, Mapping):
            output.append(dict(row))
        elif is_dataclass(row):
            output.append(asdict(row))
        elif hasattr(row, "__dict__"):
            output.append(dict(vars(row)))
    return output


def _season_rank(label: str) -> int:
    text = _text(label)
    for token in text.replace("–", "-").replace("/", "-").split("-"):
        token = token.strip()
        if token.isdigit() and len(token) == 4:
            return int(token)
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else 0


def _player_name(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(_text(player_id))
    if player is not None:
        value = _text(getattr(player, "player_name", ""))
        if value:
            return value
    for row in reversed(_rows(getattr(state, "retirement_history", ()) or ())):
        if _text(row.get("player_id")) == _text(player_id):
            value = _text(row.get("player_name"))
            if value:
                return value
    return _text(player_id) or "Unknown player"


def _team_record_from_standing(standing: Any) -> tuple[int, int]:
    if standing is None:
        return 0, 0
    return (
        max(0, _integer(getattr(standing, "wins", 0))),
        max(0, _integer(getattr(standing, "losses", 0))),
    )


def _archive_finish(archive: Any, team: str) -> tuple[str, str]:
    resolved = _text(team).upper()
    champion = _text(_field(archive, "champion", "")).upper()
    runner_up = _text(_field(archive, "runner_up", "")).upper()
    conference_champions = _field(archive, "conference_champions", {}) or {}
    if champion == resolved:
        return "NBA CHAMPION", "champion"
    if runner_up == resolved:
        return "NBA Finals", "finals"
    if resolved and resolved in {_text(v).upper() for v in getattr(conference_champions, "values", lambda: [])()}:
        return "Conference Champion", "conference"
    postseason = _field(archive, "postseason_state", None)
    if postseason is not None:
        # Do not invent a round result. Only claim a playoff appearance if the
        # archived postseason state itself visibly contains the team.
        raw = repr(postseason)
        if resolved and resolved in raw:
            return "Playoff appearance", "playoffs"
    return "Season complete", "season"


def _season_summaries(state: Any, team: str) -> list[dict[str, Any]]:
    resolved = _text(team).upper()
    rows: list[dict[str, Any]] = []
    for index, archive in enumerate(list(getattr(state, "season_history", ()) or ())):
        standings = _field(archive, "standings", {}) or {}
        wins, losses = _team_record_from_standing(standings.get(resolved))
        finish, tier = _archive_finish(archive, resolved)
        rows.append(
            {
                "season": _text(_field(archive, "season_label", "")) or f"Season {index + 1}",
                "wins": wins,
                "losses": losses,
                "finish": finish,
                "tier": tier,
                "champion": _text(_field(archive, "champion", "")).upper(),
                "runner_up": _text(_field(archive, "runner_up", "")).upper(),
                "archived": True,
                "index": index,
            }
        )
    current_standing = (getattr(state, "standings", {}) or {}).get(resolved)
    wins, losses = _team_record_from_standing(current_standing)
    current_label = _text(getattr(getattr(state, "settings", None), "season_label", "")) or "Current Season"
    rows.append(
        {
            "season": current_label,
            "wins": wins,
            "losses": losses,
            "finish": "In progress",
            "tier": "current",
            "champion": "",
            "runner_up": "",
            "archived": False,
            "index": len(rows),
        }
    )
    return rows


def _team_games(state: Any, team: str) -> list[dict[str, Any]]:
    resolved = _text(team).upper()
    output: list[dict[str, Any]] = []
    archives = list(getattr(state, "season_history", ()) or ())
    containers: list[tuple[str, Any, Mapping[str, Any], Mapping[str, Any]]] = []
    for archive in archives:
        containers.append(
            (
                _text(_field(archive, "season_label", "")),
                archive,
                _field(archive, "schedule", {}) or {},
                _field(archive, "completed_games", {}) or {},
            )
        )
    containers.append(
        (
            _text(getattr(getattr(state, "settings", None), "season_label", "")),
            state,
            getattr(state, "schedule", {}) or {},
            getattr(state, "completed_games", {}) or {},
        )
    )
    for season_index, (season, _, schedule, completed) in enumerate(containers):
        for fallback_index, (game_id, game) in enumerate(completed.items()):
            home = _text(_field(game, "home_team", "")).upper()
            away = _text(_field(game, "away_team", "")).upper()
            if resolved not in {home, away}:
                continue
            home_score = _integer(_field(game, "home_score", 0))
            away_score = _integer(_field(game, "away_score", 0))
            team_score = home_score if home == resolved else away_score
            opponent_score = away_score if home == resolved else home_score
            scheduled = schedule.get(game_id)
            day = _integer(_field(scheduled, "day_index", fallback_index), fallback_index)
            output.append(
                {
                    "season": season,
                    "season_index": season_index,
                    "day": day,
                    "game_id": _text(game_id),
                    "game": game,
                    "team_score": team_score,
                    "opponent_score": opponent_score,
                    "margin": team_score - opponent_score,
                    "win": team_score > opponent_score,
                    "opponent": away if home == resolved else home,
                }
            )
    output.sort(key=lambda row: (row["season_index"], row["day"], row["game_id"]))
    return output


def _longest_win_streak(games: list[dict[str, Any]]) -> tuple[int, str]:
    best = 0
    best_season = "—"
    current = 0
    current_season = ""
    for row in games:
        if row["season"] != current_season:
            current_season = row["season"]
            current = 0
        if row["win"]:
            current += 1
            if current > best:
                best = current
                best_season = row["season"] or "—"
        else:
            current = 0
    return best, best_season


def _player_totals_for_team(state: Any, team: str) -> list[dict[str, Any]]:
    resolved = _text(team).upper()
    totals: dict[str, dict[str, Any]] = {}
    containers = [
        *list(getattr(state, "season_history", ()) or ()),
        state,
    ]
    for container in containers:
        for game in (_field(container, "completed_games", {}) or {}).values():
            for box in tuple(_field(game, "player_box_scores", ()) or ()):
                if _text(_field(box, "team_abbreviation", "")).upper() != resolved:
                    continue
                player_id = _text(_field(box, "player_id", ""))
                if not player_id:
                    continue
                row = totals.setdefault(
                    player_id,
                    {"player_id": player_id, "games": 0, "points": 0, "rebounds": 0, "assists": 0},
                )
                row["games"] += 1
                row["points"] += _integer(_field(box, "points", 0))
                row["rebounds"] += _integer(_field(box, "rebounds", 0))
                row["assists"] += _integer(_field(box, "assists", 0))
    result = []
    for row in totals.values():
        row = dict(row)
        row["player_name"] = _player_name(state, row["player_id"])
        result.append(row)
    result.sort(key=lambda row: (row["points"], row["assists"], row["rebounds"]), reverse=True)
    return result


def _fmt_money(value: Any) -> str:
    amount = _number(value, 0.0)
    if amount <= 0:
        return ""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _event(
    *,
    season: str,
    category: str,
    title: str,
    detail: str,
    day: int = 0,
    icon: str = "•",
    importance: int = 1,
    order: int = 0,
) -> dict[str, Any]:
    return {
        "season": _text(season) or "Franchise history",
        "category": category,
        "title": _text(title),
        "detail": _text(detail),
        "day": max(0, _integer(day)),
        "icon": icon,
        "importance": importance,
        "order": order,
    }


def _timeline_events(state: Any, trade_state: Any, team: str, team_name: Callable[[str], str]) -> list[dict[str, Any]]:
    resolved = _text(team).upper()
    events: list[dict[str, Any]] = []
    season_rows = _season_summaries(state, resolved)
    for row in season_rows:
        if not row["archived"]:
            continue
        record = f"{row['wins']}-{row['losses']}"
        events.append(
            _event(
                season=row["season"],
                category="Season",
                title=row["finish"],
                detail=f"{team_name(resolved)} finished {record}.",
                day=999,
                icon="🏆" if row["tier"] == "champion" else "🏀",
                importance=5 if row["tier"] == "champion" else (4 if row["tier"] in {"finals", "conference"} else 2),
                order=10_000 + row["index"],
            )
        )

    draft_history = list(getattr(state, "franchise_draft_history_v1", ()) or ())
    for history_index, draft in enumerate(draft_history):
        season = _text(_field(draft, "target_season", "")) or _text(_field(draft, "source_season", ""))
        year = _integer(_field(draft, "draft_year", 0))
        for pick in list(_field(draft, "draft_order", ()) or ()):
            if _text(_field(pick, "owner_team", "")).upper() != resolved:
                continue
            player_name = _text(_field(pick, "player_name", ""))
            if not player_name:
                continue
            overall_pick = _integer(_field(pick, "overall_pick", 0))
            position = _text(_field(pick, "position", ""))
            school = _text(_field(pick, "school", ""))
            extras = " · ".join(v for v in (position, school) if v)
            detail = f"No. {overall_pick} overall" if overall_pick else "Draft selection"
            if extras:
                detail += f" · {extras}"
            events.append(
                _event(
                    season=season or (str(year) if year else "Draft"),
                    category="Draft",
                    title=f"Drafted {player_name}",
                    detail=detail,
                    day=990,
                    icon="🎓",
                    importance=3 if overall_pick and overall_pick <= 14 else 2,
                    order=20_000 + history_index * 100 + overall_pick,
                )
            )

    trade_history = list(getattr(state, "franchise_transaction_history_v1", ()) or ())
    if not trade_history and trade_state is not None:
        trade_history = list(getattr(trade_state, "transaction_history", ()) or ())
    for idx, row in enumerate(trade_history):
        team_a = _text(_field(row, "team_a", "")).upper()
        team_b = _text(_field(row, "team_b", "")).upper()
        if resolved not in {team_a, team_b}:
            continue
        other = team_b if team_a == resolved else team_a
        sent_ids = list(_field(row, "side_a_player_ids" if team_a == resolved else "side_b_player_ids", ()) or ())
        received_ids = list(_field(row, "side_b_player_ids" if team_a == resolved else "side_a_player_ids", ()) or ())
        sent_picks = list(_field(row, "side_a_pick_asset_ids" if team_a == resolved else "side_b_pick_asset_ids", ()) or ())
        received_picks = list(_field(row, "side_b_pick_asset_ids" if team_a == resolved else "side_a_pick_asset_ids", ()) or ())
        pieces: list[str] = []
        if received_ids:
            names = ", ".join(_player_name(state, pid) for pid in received_ids[:3])
            pieces.append(f"Acquired {names}")
        if received_picks:
            pieces.append(f"acquired {len(received_picks)} pick{'s' if len(received_picks) != 1 else ''}")
        if sent_ids:
            names = ", ".join(_player_name(state, pid) for pid in sent_ids[:3])
            pieces.append(f"sent {names}")
        if sent_picks:
            pieces.append(f"sent {len(sent_picks)} pick{'s' if len(sent_picks) != 1 else ''}")
        detail = " · ".join(pieces) or "Franchise trade completed"
        events.append(
            _event(
                season=_text(_field(row, "season_label", "")) or _text(getattr(getattr(state, "settings", None), "season_label", "")),
                category="Trade",
                title=f"Trade with {team_name(other) if other else 'another team'}",
                detail=detail,
                day=_integer(_field(row, "day_index", 0)),
                icon="🔁",
                importance=3,
                order=30_000 + idx,
            )
        )

    current_season = _text(getattr(getattr(state, "settings", None), "season_label", ""))
    for idx, row in enumerate(_rows(getattr(state, "free_agency_transaction_history", ()) or ())):
        row_team = _text(row.get("team_abbreviation", row.get("team", ""))).upper()
        if row_team != resolved:
            continue
        player_name = _text(row.get("player_name")) or _player_name(state, _text(row.get("player_id")))
        years = _integer(row.get("years", 0))
        salary = _fmt_money(row.get("annual_salary", 0))
        pieces = [x for x in ((f"{years} year{'s' if years != 1 else ''}" if years else ""), salary) if x]
        events.append(
            _event(
                season=_text(row.get("season_label")) or current_season,
                category="Signing",
                title=f"Signed {player_name}",
                detail=" · ".join(pieces) or "Free-agent signing",
                day=_integer(row.get("day_index", 0)),
                icon="✍️",
                importance=2,
                order=40_000 + idx,
            )
        )

    for idx, row in enumerate(_rows(getattr(state, "retirement_history", ()) or ())):
        row_team = _text(row.get("team", row.get("team_abbreviation", ""))).upper()
        if row_team and row_team != resolved:
            continue
        player_id = _text(row.get("player_id"))
        player_name = _text(row.get("player_name")) or _player_name(state, player_id)
        if not player_name:
            continue
        events.append(
            _event(
                season=_text(row.get("source_season", row.get("season", current_season))),
                category="Retirement",
                title=f"{player_name} retired",
                detail=_text(row.get("decision_reason")) or "Career completed",
                day=998,
                icon="👋",
                importance=2,
                order=50_000 + idx,
            )
        )

    # Awards are included only when a durable award-history layer exists.
    for attr in ("franchise_award_history", "award_history", "awards_history"):
        for idx, row in enumerate(_rows(getattr(state, attr, ()) or ())):
            row_team = _text(row.get("team", row.get("team_abbreviation", ""))).upper()
            if row_team and row_team != resolved:
                continue
            award = _text(row.get("award", row.get("award_name", row.get("name", ""))))
            winner = _text(row.get("player_name", row.get("winner", "")))
            if not award:
                continue
            title = f"{winner} won {award}" if winner else award
            events.append(
                _event(
                    season=_text(row.get("season", row.get("season_label", current_season))),
                    category="Award",
                    title=title,
                    detail=_text(row.get("detail", row.get("description", "League award"))),
                    day=995,
                    icon="🏅",
                    importance=3,
                    order=60_000 + idx,
                )
            )

    events.sort(
        key=lambda row: (
            _season_rank(row["season"]),
            row["day"],
            row["order"],
        ),
        reverse=True,
    )
    return events


def build_franchise_legacy_snapshot_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
) -> dict[str, Any]:
    team = _text(active_team).upper()
    seasons = _season_summaries(state, team)
    archived = [row for row in seasons if row["archived"]]
    championships = [row for row in archived if row["tier"] == "champion"]
    finals = [row for row in archived if row["tier"] in {"champion", "finals"}]
    games = _team_games(state, team)
    streak, streak_season = _longest_win_streak(games)
    best_season = max(archived, key=lambda row: (row["wins"], -row["losses"]), default=None)
    biggest_win = max(games, key=lambda row: row["margin"], default=None)
    highest_score = max(games, key=lambda row: row["team_score"], default=None)
    player_totals = _player_totals_for_team(state, team)
    timeline = _timeline_events(state, trade_state, team, team_name_resolver)
    current = seasons[-1]
    return {
        "team": team,
        "team_name": team_name_resolver(team),
        "season_count": len(archived),
        "championship_count": len(championships),
        "finals_count": len(finals),
        "championship_seasons": [row["season"] for row in championships],
        "seasons": seasons,
        "current": current,
        "best_season": best_season,
        "games": games,
        "total_wins": sum(int(row["win"]) for row in games),
        "total_losses": sum(int(not row["win"]) for row in games),
        "longest_streak": streak,
        "longest_streak_season": streak_season,
        "biggest_win": biggest_win,
        "highest_score": highest_score,
        "player_totals": player_totals,
        "timeline": timeline,
        "version": FRANCHISE_TIMELINE_TROPHY_ROOM_VERSION,
    }


def inject_franchise_legacy_visuals_v1(*, primary: str, secondary: str) -> None:
    p = html.escape(_text(primary) or "#CE1141")
    s = html.escape(_text(secondary) or "#0B0D12")
    st.markdown(
        f"""
<style>
.fm-legacy-hero{{position:relative;overflow:hidden;border:1px solid rgba(255,255,255,.10);border-radius:24px;padding:28px 30px;margin:2px 0 18px;background:radial-gradient(circle at 90% 10%,{p}44,transparent 34%),linear-gradient(135deg,#11151d 0%,#090b10 62%,{s}66 100%);box-shadow:0 22px 60px rgba(0,0,0,.28)}}
.fm-legacy-kicker{{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:rgba(255,255,255,.62);font-weight:800}}
.fm-legacy-title{{font-size:34px;line-height:1.05;font-weight:900;color:white;margin-top:6px}}
.fm-legacy-copy{{max-width:720px;color:rgba(255,255,255,.72);font-size:14px;margin-top:8px}}
.fm-trophy-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0 22px}}
.fm-trophy-card{{border:1px solid rgba(255,255,255,.09);border-radius:18px;padding:18px;background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.02));min-height:118px}}
.fm-trophy-icon{{font-size:25px;margin-bottom:10px}} .fm-trophy-value{{font-size:27px;color:#fff;font-weight:900}} .fm-trophy-label{{font-size:11px;color:rgba(255,255,255,.56);text-transform:uppercase;letter-spacing:.11em;font-weight:800}}
.fm-banner-wrap{{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 20px}} .fm-banner{{min-width:130px;text-align:center;padding:13px 16px;border-radius:8px 8px 18px 18px;background:linear-gradient(180deg,{p},#191b22);border:1px solid rgba(255,255,255,.18);color:white;box-shadow:0 10px 30px rgba(0,0,0,.24)}} .fm-banner-year{{font-weight:900;font-size:18px}} .fm-banner-copy{{font-size:9px;letter-spacing:.14em;text-transform:uppercase;opacity:.82}}
.fm-season-strip{{display:flex;gap:10px;overflow-x:auto;padding:4px 2px 12px;scrollbar-width:thin}} .fm-season-card{{min-width:180px;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:15px;background:#11141b}} .fm-season-card.champion{{border-color:{p};box-shadow:inset 0 0 0 1px {p}55}} .fm-season-card.current{{background:linear-gradient(145deg,{p}33,#11141b 70%)}} .fm-season-year{{font-size:12px;font-weight:900;color:white}} .fm-season-record{{font-size:25px;font-weight:900;color:white;margin:5px 0}} .fm-season-finish{{font-size:11px;color:rgba(255,255,255,.58)}}
.fm-timeline{{position:relative;margin:4px 0 12px;padding-left:24px}} .fm-timeline:before{{content:'';position:absolute;left:8px;top:8px;bottom:8px;width:2px;background:linear-gradient({p},rgba(255,255,255,.08))}} .fm-event{{position:relative;margin:0 0 12px;border:1px solid rgba(255,255,255,.08);background:#10131a;border-radius:16px;padding:14px 16px}} .fm-event:before{{content:'';position:absolute;left:-21px;top:20px;width:10px;height:10px;border-radius:50%;background:{p};box-shadow:0 0 0 4px #0b0d12}} .fm-event-meta{{font-size:10px;text-transform:uppercase;letter-spacing:.11em;color:rgba(255,255,255,.47);font-weight:800}} .fm-event-title{{font-size:15px;color:white;font-weight:850;margin-top:3px}} .fm-event-detail{{font-size:12px;color:rgba(255,255,255,.62);margin-top:3px}}
.fm-record-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0 20px}} .fm-record-card{{border:1px solid rgba(255,255,255,.08);border-radius:16px;background:#10131a;padding:15px}} .fm-record-value{{font-size:22px;font-weight:900;color:white}} .fm-record-label{{font-size:10px;color:rgba(255,255,255,.48);letter-spacing:.1em;text-transform:uppercase;font-weight:800}} .fm-record-sub{{font-size:11px;color:rgba(255,255,255,.58);margin-top:5px}}
.fm-legend-row{{display:grid;grid-template-columns:42px 1fr auto;gap:12px;align-items:center;border-bottom:1px solid rgba(255,255,255,.07);padding:11px 2px}} .fm-legend-rank{{height:34px;width:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:{p}33;color:#fff;font-weight:900}} .fm-legend-name{{font-weight:850;color:white}} .fm-legend-copy{{font-size:11px;color:rgba(255,255,255,.52)}} .fm-legend-points{{font-size:17px;color:white;font-weight:900;text-align:right}}
.fm-legacy-preview{{border:1px solid rgba(255,255,255,.08);border-radius:18px;padding:16px 18px;background:linear-gradient(110deg,{p}22,#10131a 55%);margin:14px 0}} .fm-legacy-preview strong{{color:white}} .fm-legacy-preview span{{color:rgba(255,255,255,.62)}}
@media(max-width:900px){{.fm-trophy-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.fm-record-grid{{grid-template-columns:1fr}}.fm-legacy-title{{font-size:28px}}}}
</style>
""",
        unsafe_allow_html=True,
    )


def _record_card(label: str, value: str, sub: str) -> str:
    return (
        '<div class="fm-record-card">'
        f'<div class="fm-record-label">{html.escape(label)}</div>'
        f'<div class="fm-record-value">{html.escape(value)}</div>'
        f'<div class="fm-record-sub">{html.escape(sub)}</div>'
        '</div>'
    )


def render_franchise_legacy_preview_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    set_section: Callable[[str], Any],
) -> None:
    payload = build_franchise_legacy_snapshot_v1(
        state=state,
        trade_state=trade_state,
        active_team=active_team,
        team_name_resolver=team_name_resolver,
    )
    latest = payload["timeline"][0] if payload["timeline"] else None
    latest_copy = (
        f"Latest milestone: {latest['title']} · {latest['season']}"
        if latest
        else "Your timeline will grow as games, drafts, trades and seasons are completed."
    )
    left, right = st.columns([4.8, 1.2])
    with left:
        st.markdown(
            '<div class="fm-legacy-preview">'
            f'<strong>🏆 Franchise Legacy</strong><br><span>{payload["championship_count"]} titles · {payload["season_count"]} archived seasons · {html.escape(latest_copy)}</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.write("")
        if st.button("Open Legacy", key="franchise_open_legacy_v1", width="stretch"):
            set_section("Franchise Legacy")
            st.rerun()


def render_franchise_timeline_trophy_room_v1(
    *,
    state: Any,
    trade_state: Any,
    active_team: str,
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str] | None = None,
) -> None:
    payload = build_franchise_legacy_snapshot_v1(
        state=state,
        trade_state=trade_state,
        active_team=active_team,
        team_name_resolver=team_name_resolver,
    )
    team_name = payload["team_name"]
    current = payload["current"]
    logo = team_logo_resolver(active_team) if team_logo_resolver is not None else ""
    logo_html = (
        f'<img src="{html.escape(logo)}" style="position:absolute;right:28px;top:16px;width:112px;height:112px;object-fit:contain;opacity:.90">'
        if logo
        else ""
    )
    st.markdown(
        '<div class="fm-legacy-hero">'
        f'{logo_html}<div class="fm-legacy-kicker">Franchise Timeline · Trophy Room</div>'
        f'<div class="fm-legacy-title">{html.escape(team_name)} Legacy</div>'
        f'<div class="fm-legacy-copy">Every banner, season, major transaction and franchise record below is derived from this save. Nothing is invented for presentation.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    best = payload["best_season"]
    best_value = f"{best['wins']}-{best['losses']}" if best else "—"
    best_label = best["season"] if best else "No archived season yet"
    trophy_cards = [
        ("🏆", str(payload["championship_count"]), "Championships"),
        ("🏀", str(payload["finals_count"]), "Finals Appearances"),
        ("📚", str(payload["season_count"]), "Archived Seasons"),
        ("⭐", best_value, f"Best Record · {best_label}"),
    ]
    st.markdown(
        '<div class="fm-trophy-grid">'
        + "".join(
            '<div class="fm-trophy-card">'
            f'<div class="fm-trophy-icon">{icon}</div><div class="fm-trophy-value">{html.escape(value)}</div><div class="fm-trophy-label">{html.escape(label)}</div>'
            '</div>'
            for icon, value, label in trophy_cards
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["🏆 Trophy Room", "🕰️ Franchise Timeline", "📖 Records & Icons"])

    with tabs[0]:
        st.markdown("### Championship Banners")
        if payload["championship_seasons"]:
            banners = "".join(
                '<div class="fm-banner"><div class="fm-banner-copy">NBA Champions</div>'
                f'<div class="fm-banner-year">{html.escape(season)}</div><div class="fm-banner-copy">{html.escape(payload["team"])}</div></div>'
                for season in payload["championship_seasons"]
            )
            st.markdown(f'<div class="fm-banner-wrap">{banners}</div>', unsafe_allow_html=True)
        else:
            st.info("No championship banner has been earned in this save yet. The first title will appear here automatically.")

        st.markdown("### Season-by-Season Wall")
        cards = []
        for row in payload["seasons"]:
            cls = "champion" if row["tier"] == "champion" else ("current" if row["tier"] == "current" else "")
            cards.append(
                f'<div class="fm-season-card {cls}"><div class="fm-season-year">{html.escape(row["season"])}</div>'
                f'<div class="fm-season-record">{row["wins"]}-{row["losses"]}</div>'
                f'<div class="fm-season-finish">{html.escape(row["finish"])}</div></div>'
            )
        st.markdown(f'<div class="fm-season-strip">{"".join(cards)}</div>', unsafe_allow_html=True)

        if current["tier"] == "current":
            st.caption(f"Current season: {current['season']} · {current['wins']}-{current['losses']}. This card updates as you simulate games.")

    with tabs[1]:
        categories = ["All", "Season", "Draft", "Trade", "Signing", "Award", "Retirement"]
        chosen = st.segmented_control(
            "Timeline filter",
            options=categories,
            default="All",
            key="franchise_legacy_timeline_filter_v1",
            label_visibility="collapsed",
        )
        chosen = chosen or "All"
        events = [row for row in payload["timeline"] if chosen == "All" or row["category"] == chosen]
        if not events:
            st.info("No matching franchise events have been recorded yet. This timeline fills itself from durable save history as the franchise progresses.")
        else:
            event_html = []
            for row in events[:80]:
                day = f" · Day {row['day']}" if row["day"] and row["day"] < 900 else ""
                event_html.append(
                    '<div class="fm-event">'
                    f'<div class="fm-event-meta">{html.escape(row["season"])}{day} · {html.escape(row["category"])}</div>'
                    f'<div class="fm-event-title">{row["icon"]} {html.escape(row["title"])}</div>'
                    f'<div class="fm-event-detail">{html.escape(row["detail"])}</div>'
                    '</div>'
                )
            st.markdown(f'<div class="fm-timeline">{"".join(event_html)}</div>', unsafe_allow_html=True)

    with tabs[2]:
        games = payload["games"]
        biggest = payload["biggest_win"]
        high = payload["highest_score"]
        streak = payload["longest_streak"]
        record_cards = [
            _record_card(
                "All-Time Sim Record",
                f"{payload['total_wins']}-{payload['total_losses']}",
                f"{len(games)} completed franchise games across the stored save",
            ),
            _record_card(
                "Largest Victory",
                (f"+{biggest['margin']}" if biggest is not None else "—"),
                (f"{biggest['season']} vs {team_name_resolver(biggest['opponent'])} · {biggest['team_score']}-{biggest['opponent_score']}" if biggest is not None else "No completed games yet"),
            ),
            _record_card(
                "Longest Win Streak",
                (f"{streak} games" if streak else "—"),
                (payload["longest_streak_season"] if streak else "No winning streak recorded yet"),
            ),
            _record_card(
                "Highest Team Score",
                (str(high["team_score"]) if high is not None else "—"),
                (f"{high['season']} vs {team_name_resolver(high['opponent'])}" if high is not None else "No completed games yet"),
            ),
            _record_card(
                "Best Archived Season",
                (f"{best['wins']}-{best['losses']}" if best else "—"),
                (best["season"] if best else "Complete a season to establish this record"),
            ),
            _record_card(
                "Current Season",
                f"{current['wins']}-{current['losses']}",
                current["season"],
            ),
        ]
        st.markdown(f'<div class="fm-record-grid">{"".join(record_cards)}</div>', unsafe_allow_html=True)

        st.markdown("### Franchise Icons")
        leaders = payload["player_totals"][:8]
        if not leaders:
            st.info("Franchise player leaders appear after completed games are stored in the save.")
        else:
            leader_html = []
            for rank, row in enumerate(leaders, start=1):
                leader_html.append(
                    '<div class="fm-legend-row">'
                    f'<div class="fm-legend-rank">{rank}</div>'
                    f'<div><div class="fm-legend-name">{html.escape(row["player_name"])}</div><div class="fm-legend-copy">{row["games"]} GP · {row["rebounds"]:,} REB · {row["assists"]:,} AST</div></div>'
                    f'<div><div class="fm-legend-points">{row["points"]:,}</div><div class="fm-legend-copy">PTS</div></div>'
                    '</div>'
                )
            st.markdown("".join(leader_html), unsafe_allow_html=True)
        st.caption("Franchise Icons are calculated only from stored box scores for this team, including archived seasons and the current season.")
