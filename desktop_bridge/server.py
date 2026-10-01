from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


SERVICE_NAME = "nba-franchise-v3-bridge"
API_VERSION = "0.3.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

# V2 checkpoints were serialized with top-level src module names.
# Keep src directly importable so cloudpickle can resolve them.
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _obj_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _find_number(
    value: Any,
    candidate_keys: tuple[str, ...],
    depth: int = 0,
) -> float | None:
    if depth > 4:
        return None

    data = _obj_dict(value)
    if not data:
        return None

    normalized = {str(k).lower(): v for k, v in data.items()}

    for key in candidate_keys:
        if key.lower() in normalized:
            result = _number(normalized[key.lower()])
            if result is not None:
                return result

    for child in data.values():
        if isinstance(child, dict) or hasattr(child, "__dict__"):
            result = _find_number(child, candidate_keys, depth + 1)
            if result is not None:
                return result

    return None


def _chemistry_score(morale_snapshot: Any, team_abbreviation: str) -> float | None:
    morale = _obj_dict(morale_snapshot)
    teams = _obj_dict(morale.get("teams", {}))
    team_state = teams.get(team_abbreviation)

    if team_state is None:
        return None

    direct = _find_number(
        team_state,
        (
            "chemistry_score",
            "team_chemistry",
            "chemistry_rating",
            "chemistry",
        ),
    )

    if direct is not None:
        if 0.0 <= direct <= 1.0:
            direct *= 100.0
        return direct

    data = _obj_dict(team_state)

    for key, value in data.items():
        if "chemistry" not in str(key).lower():
            continue

        numeric = _number(value)
        if numeric is not None:
            if 0.0 <= numeric <= 1.0:
                numeric *= 100.0
            return numeric

        nested = _find_number(
            value,
            ("score", "value", "rating", "chemistry_score"),
        )
        if nested is not None:
            if 0.0 <= nested <= 1.0:
                nested *= 100.0
            return nested

    return None


def _chemistry_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "Elite"
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Stable"
    if score >= 50:
        return "Fragile"
    return "Low"


def _team_cap_space(financial_snapshot: Any, team_abbreviation: str) -> float | None:
    financial = _obj_dict(financial_snapshot)
    team_financials = _obj_dict(financial.get("team_financials", {}))
    team_state = team_financials.get(team_abbreviation)

    if team_state is None:
        return None

    direct = _find_number(
        team_state,
        (
            "cap_space",
            "salary_cap_space",
            "available_cap_space",
            "cap_room",
            "room_under_cap",
        ),
    )

    if direct is not None:
        return direct

    salary_cap = _find_number(
        team_state,
        (
            "salary_cap",
            "salary_cap_amount",
            "cap_limit",
        ),
    )

    payroll = _find_number(
        team_state,
        (
            "team_salary",
            "total_salary",
            "payroll",
            "active_salary",
            "salary_total",
        ),
    )

    if salary_cap is not None and payroll is not None:
        return salary_cap - payroll

    return None


def _money_display(value: float | None) -> str | None:
    if value is None:
        return None

    sign = "-" if value < 0 else ""
    amount = abs(value)

    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.1f}M"

    if amount >= 1_000:
        return f"{sign}${amount / 1_000:.0f}K"

    return f"{sign}${amount:,.0f}"



def _safe_float(value: Any, default: float = 0.0) -> float:
    number = _number(value)
    return float(number) if number is not None else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _contract_payload(player: Any) -> dict[str, Any]:
    contract = getattr(player, "contract", None)
    salary = _number(getattr(contract, "salary", None))
    years_remaining = _safe_int(getattr(contract, "years_remaining", 0))
    option_type = str(getattr(contract, "option_type", "") or "")
    guaranteed = getattr(contract, "guaranteed", None)
    status = str(getattr(contract, "status", "") or "")

    return {
        "status": status,
        "salary": salary,
        "salary_display": _money_display(salary),
        "years_remaining": years_remaining,
        "option_type": option_type,
        "guaranteed": guaranteed,
    }


def _roster_financial_summary(state: Any, team_abbreviation: str) -> dict[str, Any]:
    financial = _obj_dict(
        getattr(state, "franchise_active_financial_snapshot_v1", {})
    )
    thresholds = _obj_dict(financial.get("thresholds", {}))

    salary_cap = _number(thresholds.get("salary_cap"))
    minimum_team_salary = _number(thresholds.get("minimum_team_salary"))
    tax_level = _number(thresholds.get("tax_level"))
    first_apron = _number(thresholds.get("first_apron"))
    second_apron = _number(thresholds.get("second_apron"))

    team_state = state.teams.get(team_abbreviation)
    roster_ids = list(getattr(team_state, "roster_player_ids", ())) if team_state else []

    payroll = 0.0
    salary_rows = 0
    missing_salary_rows = 0

    for player_id in roster_ids:
        player = state.players.get(player_id)
        if player is None:
            missing_salary_rows += 1
            continue

        salary = _number(getattr(getattr(player, "contract", None), "salary", None))
        if salary is None:
            missing_salary_rows += 1
            continue

        payroll += salary
        salary_rows += 1

    cap_room = salary_cap - payroll if salary_cap is not None else None
    tax_room = tax_level - payroll if tax_level is not None else None
    first_apron_room = first_apron - payroll if first_apron is not None else None
    second_apron_room = second_apron - payroll if second_apron is not None else None

    return {
        "payroll": round(payroll, 2),
        "payroll_display": _money_display(payroll),
        "salary_cap": salary_cap,
        "salary_cap_display": _money_display(salary_cap),
        "cap_space": cap_room,
        "cap_space_display": _money_display(cap_room),
        "cap_room_estimate": cap_room,
        "cap_room_estimate_display": _money_display(cap_room),
        "minimum_team_salary": minimum_team_salary,
        "tax_level": tax_level,
        "tax_level_display": _money_display(tax_level),
        "tax_room": tax_room,
        "tax_room_display": _money_display(tax_room),
        "first_apron": first_apron,
        "first_apron_display": _money_display(first_apron),
        "first_apron_room": first_apron_room,
        "first_apron_room_display": _money_display(first_apron_room),
        "second_apron": second_apron,
        "second_apron_display": _money_display(second_apron),
        "second_apron_room": second_apron_room,
        "second_apron_room_display": _money_display(second_apron_room),
        "salary_rows": salary_rows,
        "missing_salary_rows": missing_salary_rows,
        "basis": "active_roster_contracts_only",
        "is_estimate": True,
    }


def _per_game(total: Any, games_played: int) -> float:
    if games_played <= 0:
        return 0.0
    return round(_safe_float(total) / games_played, 1)


def _percentage(made: Any, attempted: Any) -> float | None:
    attempts = _safe_float(attempted)
    if attempts <= 0:
        return None
    return round(100.0 * _safe_float(made) / attempts, 1)


def _season_stats_payload(totals: Any) -> dict[str, Any]:
    if totals is None:
        return {
            "games_played": 0,
            "games_started": 0,
            "mpg": 0.0,
            "ppg": 0.0,
            "rpg": 0.0,
            "apg": 0.0,
            "spg": 0.0,
            "bpg": 0.0,
            "fg_pct": None,
            "three_pct": None,
            "ft_pct": None,
        }

    games = _safe_int(getattr(totals, "games_played", 0))

    return {
        "games_played": games,
        "games_started": _safe_int(getattr(totals, "games_started", 0)),
        "mpg": _per_game(getattr(totals, "minutes", 0.0), games),
        "ppg": _per_game(getattr(totals, "points", 0), games),
        "rpg": _per_game(getattr(totals, "rebounds", 0), games),
        "apg": _per_game(getattr(totals, "assists", 0), games),
        "spg": _per_game(getattr(totals, "steals", 0), games),
        "bpg": _per_game(getattr(totals, "blocks", 0), games),
        "fg_pct": _percentage(
            getattr(totals, "field_goals_made", 0),
            getattr(totals, "field_goals_attempted", 0),
        ),
        "three_pct": _percentage(
            getattr(totals, "three_pointers_made", 0),
            getattr(totals, "three_pointers_attempted", 0),
        ),
        "ft_pct": _percentage(
            getattr(totals, "free_throws_made", 0),
            getattr(totals, "free_throws_attempted", 0),
        ),
    }


def _roster_player_payload(
    state: Any,
    team_state: Any,
    player_id: str,
    roster_index: int,
) -> dict[str, Any] | None:
    player = state.players.get(player_id)
    if player is None:
        return None

    starter_ids = list(getattr(team_state.rotation, "starter_ids", ()))
    rotation_ids = list(getattr(team_state.rotation, "rotation_player_ids", ()))
    minutes_targets = _obj_dict(getattr(team_state.rotation, "minutes_targets", {}))
    active_ids = set(getattr(team_state, "active_player_ids", ()))
    inactive_ids = set(getattr(team_state, "inactive_player_ids", ()))

    morale_snapshot = _obj_dict(
        getattr(state, "franchise_morale_chemistry_v1", {})
    )
    morale_players = _obj_dict(morale_snapshot.get("players", {}))
    morale = _obj_dict(morale_players.get(player_id, {}))

    injury = _obj_dict(getattr(state, "injuries", {}).get(player_id))
    health = _obj_dict(
        getattr(state, "injury_fatigue_profiles", {}).get(player_id)
    )
    totals = getattr(state, "player_season_totals", {}).get(player_id)

    is_starter = player_id in starter_ids
    in_rotation = player_id in rotation_ids
    is_active = player_id in active_ids
    is_inactive = player_id in inactive_ids

    rotation_order = None
    if player_id in rotation_ids:
        rotation_order = rotation_ids.index(player_id) + 1

    automatic_role = morale.get("automatic_role")
    expected_role = morale.get("expected_role")

    if automatic_role:
        role = str(automatic_role)
    elif expected_role:
        role = str(expected_role)
    elif is_starter:
        role = "Starter"
    elif in_rotation:
        role = "Rotation"
    else:
        role = "Reserve"

    injury_status = _enum_value(injury.get("status", "unknown")).lower()
    injury_type = str(injury.get("injury_type", "") or "")
    games_remaining = _safe_int(injury.get("games_remaining", 0))

    if injury_status == "healthy":
        health_display = "Healthy"
    elif injury_type:
        health_display = injury_type.title()
        if games_remaining > 0:
            health_display += f" ({games_remaining}g)"
    else:
        health_display = injury_status.replace("_", " ").title()

    age = _number(getattr(player, "age", None))
    overall = _number(getattr(player, "overall_rating", None))
    potential = _number(getattr(player, "potential_rating", None))
    future_outlook = _number(getattr(player, "future_outlook_rating", None))

    skill_ratings = dict(_obj_dict(getattr(player, "skill_ratings", {})))

    return {
        "player_id": str(player_id),
        "name": str(getattr(player, "player_name", player_id)),
        "position": str(getattr(player, "position", "")),
        "age": round(age, 1) if age is not None else None,
        "overall": round(overall, 1) if overall is not None else None,
        "potential": round(potential, 1) if potential is not None else None,
        "future_outlook": round(future_outlook, 1) if future_outlook is not None else None,
        "development_direction": str(
            getattr(player, "development_direction", "") or ""
        ),
        "generated_prospect": bool(
            getattr(player, "generated_prospect", False)
        ),
        "two_way": bool(getattr(player, "two_way", False)),
        "roster_index": roster_index,
        "is_starter": is_starter,
        "in_rotation": in_rotation,
        "is_active": is_active,
        "is_inactive": is_inactive,
        "rotation_order": rotation_order,
        "target_minutes": _safe_float(minutes_targets.get(player_id, 0.0)),
        "role": role,
        "contract": _contract_payload(player),
        "morale": {
            "score": _number(morale.get("score")),
            "status": str(morale.get("status", "") or ""),
            "role_satisfaction": _number(morale.get("role_satisfaction")),
            "expected_role": str(expected_role or ""),
            "actual_minutes": _number(morale.get("actual_minutes")),
            "recent_minutes": _number(morale.get("recent_minutes")),
            "trade_request_risk": _number(morale.get("trade_request_risk")),
            "trade_request_status": str(
                morale.get("trade_request_status", "") or ""
            ),
            "reasons": list(morale.get("reasons", []) or []),
        },
        "health": {
            "status": injury_status,
            "display": health_display,
            "injury_type": injury_type,
            "games_remaining": games_remaining,
            "notes": str(injury.get("notes", "") or ""),
            "fatigue": _number(health.get("fatigue")),
            "durability": _number(health.get("durability")),
            "expected_return_day": _safe_int(
                health.get("expected_return_day", 0)
            ),
            "season_games_missed": _safe_int(
                health.get("season_games_missed", 0)
            ),
            "injuries_suffered": _safe_int(
                health.get("injuries_suffered", 0)
            ),
            "risk_tier": str(health.get("last_risk_tier", "") or ""),
            "risk_explanation": str(
                health.get("last_risk_explanation", "") or ""
            ),
        },
        "season_stats": _season_stats_payload(totals),
        "skills": skill_ratings,
    }


def _roster_payload(state: Any, team_abbreviation: str) -> dict[str, Any]:
    team_state = state.teams.get(team_abbreviation)
    if team_state is None:
        return {}

    roster_ids = list(getattr(team_state, "roster_player_ids", ()))
    starter_ids = list(getattr(team_state.rotation, "starter_ids", ()))
    rotation_ids = list(getattr(team_state.rotation, "rotation_player_ids", ()))

    rows = []
    for index, player_id in enumerate(roster_ids):
        row = _roster_player_payload(
            state,
            team_state,
            str(player_id),
            index,
        )
        if row is not None:
            rows.append(row)

    starter_rank = {player_id: index for index, player_id in enumerate(starter_ids)}
    rotation_rank = {player_id: index for index, player_id in enumerate(rotation_ids)}

    def sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        player_id = row["player_id"]
        if player_id in starter_rank:
            return (0, starter_rank[player_id], row["roster_index"])
        if player_id in rotation_rank:
            return (1, rotation_rank[player_id], row["roster_index"])
        return (2, row["roster_index"], row["roster_index"])

    rows.sort(key=sort_key)

    morale_snapshot = _obj_dict(
        getattr(state, "franchise_morale_chemistry_v1", {})
    )
    morale_teams = _obj_dict(morale_snapshot.get("teams", {}))
    team_morale = _obj_dict(morale_teams.get(team_abbreviation, {}))

    injured_count = sum(
        1
        for row in rows
        if row.get("health", {}).get("status") not in ("", "healthy", "unknown")
    )

    return {
        "read_only": True,
        "source": "active_v2_franchise_checkpoint",
        "api_version": API_VERSION,
        "team": {
            "abbreviation": team_abbreviation,
            "name": TEAM_NAMES.get(team_abbreviation, team_abbreviation),
            "roster_size": len(roster_ids),
            "active_players": len(getattr(team_state, "active_player_ids", ())),
            "inactive_players": len(getattr(team_state, "inactive_player_ids", ())),
            "starters": len(starter_ids),
            "rotation_players": len(rotation_ids),
            "injured_players": injured_count,
        },
        "season": {
            "label": state.settings.season_label,
            "phase": _enum_value(state.phase),
            "day_index": int(state.current_day_index),
        },
        "financial": _roster_financial_summary(state, team_abbreviation),
        "chemistry": {
            "score": _number(team_morale.get("chemistry")),
            "morale_average": _number(team_morale.get("morale_average")),
            "role_alignment": _number(team_morale.get("role_alignment")),
            "happy_players": _safe_int(team_morale.get("happy_players", 0)),
            "frustrated_players": _safe_int(
                team_morale.get("frustrated_players", 0)
            ),
            "trade_pressure_players": _safe_int(
                team_morale.get("trade_pressure_players", 0)
            ),
        },
        "players": rows,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _conference_rank(state: Any, active_team: str) -> tuple[int | None, str | None]:
    teams = state.teams
    standings = state.standings

    active_team_state = teams.get(active_team)
    if active_team_state is None:
        return None, None

    conference = active_team_state.conference

    conference_teams = [
        abbreviation
        for abbreviation, team_state in teams.items()
        if team_state.conference == conference
    ]

    def ranking_key(abbreviation: str) -> tuple[float, int, int]:
        standing = standings.get(abbreviation)
        if standing is None:
            return (0.0, 0, 0)

        games = max(int(standing.games_played), 1)
        win_pct = float(standing.wins) / games
        point_diff = int(standing.points_for) - int(standing.points_against)

        return (win_pct, int(standing.wins), point_diff)

    ordered = sorted(
        conference_teams,
        key=ranking_key,
        reverse=True,
    )

    try:
        rank = ordered.index(active_team) + 1
    except ValueError:
        return None, conference

    return rank, conference


def _next_game(state: Any, active_team: str) -> dict[str, Any] | None:
    candidates = []

    for game in state.schedule.values():
        if game.home_team != active_team and game.away_team != active_team:
            continue

        status = _enum_value(game.status).lower()

        if status == "completed":
            continue

        if int(game.day_index) < int(state.current_day_index):
            continue

        candidates.append(game)

    if not candidates:
        return None

    game = min(
        candidates,
        key=lambda item: (int(item.day_index), str(item.game_id)),
    )

    is_home = game.home_team == active_team
    opponent = game.away_team if is_home else game.home_team
    days_away = max(int(game.day_index) - int(state.current_day_index), 0)

    return {
        "game_id": game.game_id,
        "day_index": int(game.day_index),
        "days_away": days_away,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "is_home": is_home,
        "opponent": opponent,
        "opponent_name": TEAM_NAMES.get(opponent, opponent),
        "status": _enum_value(game.status),
        "matchup": (
            f"{TEAM_NAMES.get(active_team, active_team)} vs "
            f"{TEAM_NAMES.get(opponent, opponent)}"
            if is_home
            else
            f"{TEAM_NAMES.get(active_team, active_team)} at "
            f"{TEAM_NAMES.get(opponent, opponent)}"
        ),
    }


def _draft_summary(state: Any) -> dict[str, Any] | None:
    draft = _obj_dict(getattr(state, "franchise_draft_state_v1", {}))

    if not draft:
        return None

    return {
        "draft_year": draft.get("draft_year"),
        "target_season": draft.get("target_season"),
        "phase": draft.get("phase"),
        "current_pick_index": draft.get("current_pick_index"),
    }


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": API_VERSION,
            "phase": "V3 desktop development",
            "read_only": True,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


async def project_meta(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "project": "NBA Franchise Simulator",
            "release_line": "V3 desktop development",
            "backend": "Python",
            "client": "Godot",
            "simulation_source": "validated V2 engine",
            "save_access": "read_only",
            "api_version": API_VERSION,
        }
    )


async def franchise_summary(_: Request) -> JSONResponse:
    """
    Read the active V2 checkpoint and expose a small, read-only summary
    for the V3 Godot desktop client.
    """

    try:
        checkpoint = load_franchise_checkpoint()
        state = checkpoint.simulation_state

        active_team = checkpoint.preferences.get("franchise_pref_active_team")

        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "read_only": True,
                },
                status_code=404,
            )

        team_state = state.teams.get(active_team)
        standing = state.standings.get(active_team)

        if team_state is None or standing is None:
            return JSONResponse(
                {
                    "error": "active_team_state_not_found",
                    "team": active_team,
                    "read_only": True,
                },
                status_code=404,
            )

        rank, conference = _conference_rank(state, active_team)

        chemistry = _chemistry_score(
            state.franchise_morale_chemistry_v1,
            active_team,
        )

        financial_summary = _roster_financial_summary(
            state,
            active_team,
        )

        phase = _enum_value(state.phase)

        payload = {
            "read_only": True,
            "source": "active_v2_franchise_checkpoint",
            "api_version": API_VERSION,

            "team": {
                "abbreviation": active_team,
                "name": TEAM_NAMES.get(active_team, active_team),
                "conference": team_state.conference,
                "division": team_state.division,
                "roster_size": len(team_state.roster_player_ids),
                "active_players": len(team_state.active_player_ids),
                "inactive_players": len(team_state.inactive_player_ids),
            },

            "season": {
                "label": state.settings.season_label,
                "phase": phase,
                "day_index": int(state.current_day_index),
            },

            "record": {
                "games_played": int(standing.games_played),
                "wins": int(standing.wins),
                "losses": int(standing.losses),
                "display": f"{standing.wins}-{standing.losses}",
                "home": f"{standing.home_wins}-{standing.home_losses}",
                "away": f"{standing.away_wins}-{standing.away_losses}",
                "streak_type": standing.streak_type,
                "streak_length": int(standing.streak_length),
                "streak": (
                    f"{standing.streak_type}{standing.streak_length}"
                    if standing.streak_type
                    else None
                ),
                "conference_rank": rank,
                "conference_rank_display": (
                    f"{_ordinal(rank)} in {conference}"
                    if rank is not None and conference
                    else None
                ),
                "points_for": int(standing.points_for),
                "points_against": int(standing.points_against),
            },

            "chemistry": {
                "score": round(chemistry, 1) if chemistry is not None else None,
                "label": _chemistry_label(chemistry),
            },

            "financial": financial_summary,

            "next_game": _next_game(state, active_team),

            # Draft metadata is live now. Exact "next owned pick" inventory
            # will be wired separately rather than guessed from sparse rights.
            "draft": _draft_summary(state),

            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        return JSONResponse(payload)

    except Exception as exc:
        return JSONResponse(
            {
                "error": "franchise_summary_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "read_only": True,
            },
            status_code=500,
        )


async def roster_summary(_: Request) -> JSONResponse:
    # Read-only roster endpoint for the V3 Godot client.
    try:
        checkpoint = load_franchise_checkpoint()
        state = checkpoint.simulation_state
        active_team = checkpoint.preferences.get("franchise_pref_active_team")

        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "read_only": True,
                },
                status_code=404,
            )

        payload = _roster_payload(state, active_team)

        if not payload:
            return JSONResponse(
                {
                    "error": "active_team_roster_not_found",
                    "team": active_team,
                    "read_only": True,
                },
                status_code=404,
            )

        return JSONResponse(payload)

    except Exception as exc:
        return JSONResponse(
            {
                "error": "roster_summary_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "read_only": True,
            },
            status_code=500,
        )


async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v3/meta", project_meta, methods=["GET"]),
    Route("/v3/franchise-summary", franchise_summary, methods=["GET"]),
    Route("/v3/roster", roster_summary, methods=["GET"]),
]


app = Starlette(
    debug=False,
    routes=routes,
    exception_handlers={404: not_found},
)
