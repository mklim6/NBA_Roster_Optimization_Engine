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
API_VERSION = "0.2.0"

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

        cap_space = _team_cap_space(
            state.franchise_active_financial_snapshot_v1,
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

            "financial": {
                "cap_space": cap_space,
                "cap_space_display": _money_display(cap_space),
            },

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


async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v3/meta", project_meta, methods=["GET"]),
    Route("/v3/franchise-summary", franchise_summary, methods=["GET"]),
]


app = Starlette(
    debug=False,
    routes=routes,
    exception_handlers={404: not_found},
)
