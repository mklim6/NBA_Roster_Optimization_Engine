from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import copy
import hashlib
import sys

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


SERVICE_NAME = "nba-franchise-v3-bridge"
API_VERSION = "0.9.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
V3_WORKING_CHECKPOINT_PATH = (
    REPO_ROOT
    / "outputs"
    / "runtime"
    / "v3_godot_working_checkpoint.pkl.gz"
)

# V2 checkpoints were serialized with top-level src module names.
# Keep src directly importable so cloudpickle can resolve them.
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)
from franchise_command_center_v1 import (
    apply_rotation_plan,
    coaching_alerts_for_game,
    rotation_plan_from_rows,
)
from franchise_game_day_league_calendar_sync_v1 import (
    catch_up_cpu_schedule_v1,
    league_calendar_sync_status_v1,
)
from regular_season_simulation_controller_v1 import (
    regular_season_state_fingerprint,
)
from simulation_league_state_v1 import (
    GameStatus,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (
    simulate_scheduled_game,
)
from desktop_bridge.transaction_foundation import (
    build_free_agency_preview_payload,
    build_trade_preview_payload,
    build_transaction_foundation_payload,
)



def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _active_team_from_checkpoint(checkpoint: Any) -> str:
    return str(
        checkpoint.preferences.get("franchise_pref_active_team", "")
        or ""
    ).strip().upper()


def _working_checkpoint() -> Any | None:
    return load_franchise_checkpoint(
        path=V3_WORKING_CHECKPOINT_PATH,
        allow_backup=False,
    )


def _rotation_plan_payload(plan: Any) -> dict[str, Any]:
    return {
        "team": plan.team,
        "starter_ids": list(plan.starter_ids),
        "rotation_player_ids": list(plan.rotation_player_ids),
        "minutes_targets": dict(plan.minutes_targets),
        "total_minutes": float(plan.total_minutes),
    }


def _rotation_rows_from_request(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Request body must contain a 'rows' array.")

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Every rotation row must be a JSON object.")

        normalized.append(
            {
                "player_id": str(row.get("player_id", "") or "").strip(),
                "starter": bool(row.get("starter", False)),
                "in_rotation": bool(row.get("in_rotation", False)),
                "minutes": float(row.get("minutes", 0.0) or 0.0),
            }
        )

    return normalized


def _next_controlled_scheduled_game(state: Any, team: str) -> Any | None:
    resolved_team = str(team or "").strip().upper()
    candidates = [
        game
        for game in state.schedule.values()
        if (
            getattr(game, "status", None) == GameStatus.SCHEDULED
            and resolved_team
            in {
                str(getattr(game, "home_team", "")).upper(),
                str(getattr(game, "away_team", "")).upper(),
            }
        )
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda game: (
            int(getattr(game, "day_index", 0)),
            str(getattr(game, "game_id", "")),
        ),
    )


def _standing_payload(state: Any, team: str) -> dict[str, Any]:
    standing = state.standings.get(team)
    if standing is None:
        return {}
    games = int(standing.games_played)
    return {
        "games_played": games,
        "wins": int(standing.wins),
        "losses": int(standing.losses),
        "display": f"{standing.wins}-{standing.losses}",
        "points_for": int(standing.points_for),
        "points_against": int(standing.points_against),
        "win_pct": (
            round(float(standing.wins) / games, 4)
            if games
            else 0.0
        ),
    }


def _game_day_player_line(state: Any, line: Any) -> dict[str, Any]:
    player = state.players.get(line.player_id)
    return {
        "player_id": str(line.player_id),
        "name": str(getattr(player, "player_name", line.player_id)),
        "team": str(line.team_abbreviation),
        "starter": bool(line.started),
        "minutes": round(float(line.minutes), 1),
        "points": int(line.points),
        "rebounds": int(line.rebounds),
        "assists": int(line.assists),
        "steals": int(line.steals),
        "blocks": int(line.blocks),
        "turnovers": int(line.turnovers),
        "field_goals_made": int(getattr(line, "field_goals_made", 0)),
        "field_goals_attempted": int(
            getattr(line, "field_goals_attempted", 0)
        ),
        "three_pointers_made": int(
            getattr(line, "three_pointers_made", 0)
        ),
        "three_pointers_attempted": int(
            getattr(line, "three_pointers_attempted", 0)
        ),
    }


def _completed_game_payload(state: Any, completed: Any) -> dict[str, Any]:
    player_lines = [
        _game_day_player_line(state, line)
        for line in completed.player_box_scores
    ]
    top_performers = sorted(
        player_lines,
        key=lambda row: (
            -row["points"],
            -row["assists"],
            -row["rebounds"],
            row["name"],
        ),
    )[:6]

    scheduled = state.schedule.get(str(completed.game_id))
    day_index = (
        int(getattr(scheduled, "day_index", state.current_day_index))
        if scheduled is not None
        else int(state.current_day_index)
    )

    return {
        "game_id": str(completed.game_id),
        "day_index": day_index,
        "home_team": str(completed.home_team),
        "away_team": str(completed.away_team),
        "home_team_name": TEAM_NAMES.get(
            str(completed.home_team),
            str(completed.home_team),
        ),
        "away_team_name": TEAM_NAMES.get(
            str(completed.away_team),
            str(completed.away_team),
        ),
        "home_score": int(completed.home_score),
        "away_score": int(completed.away_score),
        "overtime_periods": int(
            getattr(completed, "overtime_periods", 0) or 0
        ),
        "top_performers": top_performers,
        "player_box_scores": player_lines,
    }


def _latest_completed_game_for_team(state: Any, active_team: str) -> Any | None:
    candidates: list[tuple[int, str, Any]] = []

    for completed in state.completed_games.values():
        home_team = str(getattr(completed, "home_team", ""))
        away_team = str(getattr(completed, "away_team", ""))
        if active_team not in (home_team, away_team):
            continue

        scheduled = state.schedule.get(str(completed.game_id))
        day_index = int(
            getattr(scheduled, "day_index", state.current_day_index)
            if scheduled is not None
            else state.current_day_index
        )
        candidates.append((day_index, str(completed.game_id), completed))

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return candidates[0][2]


def _game_day_payload(state: Any, active_team: str) -> dict[str, Any]:
    last_completed = _latest_completed_game_for_team(state, active_team)
    last_game = (
        _completed_game_payload(state, last_completed)
        if last_completed is not None
        else None
    )

    game = _next_controlled_scheduled_game(state, active_team)
    sync = league_calendar_sync_status_v1(
        state,
        controlled_teams=(active_team,),
    )

    if game is None:
        return {
            "api_version": API_VERSION,
            "source": "v3_working_checkpoint",
            "working_save_only": True,
            "active_v2_read_only": True,
            "team": active_team,
            "team_name": TEAM_NAMES.get(active_team, active_team),
            "season": str(state.settings.season_label),
            "phase": _enum_value(state.phase),
            "day_index": int(state.current_day_index),
            "record": _standing_payload(state, active_team),
            "last_game": last_game,
            "next_game": None,
            "league_sync": sync,
        }

    is_home = str(game.home_team) == active_team
    opponent = (
        str(game.away_team)
        if is_home
        else str(game.home_team)
    )

    alerts = [
        {
            "severity": str(alert.severity),
            "category": str(alert.category),
            "title": str(alert.title),
            "detail": str(alert.detail),
            "player_ids": list(alert.player_ids),
        }
        for alert in coaching_alerts_for_game(
            state,
            game,
            active_team,
        )
    ]

    team_state = state.teams[active_team]
    rotation = team_state.rotation
    unavailable = []

    for player_id in team_state.roster_player_ids:
        injury = state.injuries.get(player_id)
        status = _enum_value(getattr(injury, "status", "")).lower()
        if status in ("", "healthy"):
            continue
        player = state.players.get(player_id)
        unavailable.append(
            {
                "player_id": str(player_id),
                "name": str(
                    getattr(player, "player_name", player_id)
                ),
                "status": status,
                "injury_type": str(
                    getattr(injury, "injury_type", "") or ""
                ),
                "games_remaining": int(
                    getattr(injury, "games_remaining", 0) or 0
                ),
            }
        )

    return {
        "api_version": API_VERSION,
        "source": "v3_working_checkpoint",
        "working_save_only": True,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": TEAM_NAMES.get(active_team, active_team),
        "season": str(state.settings.season_label),
        "phase": _enum_value(state.phase),
        "day_index": int(state.current_day_index),
        "record": _standing_payload(state, active_team),
        "opponent_record": _standing_payload(state, opponent),
        "last_game": last_game,
        "next_game": {
            "game_id": str(game.game_id),
            "day_index": int(game.day_index),
            "home_team": str(game.home_team),
            "away_team": str(game.away_team),
            "is_home": is_home,
            "opponent": opponent,
            "opponent_name": TEAM_NAMES.get(opponent, opponent),
            "matchup": (
                f"{active_team} vs {opponent}"
                if is_home
                else f"{active_team} at {opponent}"
            ),
        },
        "rotation": {
            "starter_ids": list(rotation.starter_ids),
            "rotation_player_ids": list(rotation.rotation_player_ids),
            "minutes_targets": dict(rotation.minutes_targets),
            "total_minutes": round(
                sum(rotation.minutes_targets.values()),
                1,
            ),
        },
        "unavailable_players": unavailable,
        "coaching_alerts": alerts,
        "league_sync": sync,
    }

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


def _roster_payload(
    state: Any,
    team_abbreviation: str,
    *,
    source: str = "active_v2_franchise_checkpoint",
    editable: bool = False,
) -> dict[str, Any]:
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
        "read_only": not editable,
        "editable": editable,
        "active_v2_read_only": True,
        "source": source,
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
        "rotation_rules": {
            "required_starters": 5,
            "minimum_game_players": _safe_int(
                getattr(state.settings, "minimum_game_players", 8),
                8,
            ),
            "maximum_rotation_players": 15,
            "required_total_minutes": 240.0,
            "maximum_player_minutes": 48.0,
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


def _ranked_standings_payload(
    state: Any,
    conference: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    teams = [
        abbreviation
        for abbreviation, team_state in state.teams.items()
        if str(getattr(team_state, "conference", "")) == conference
    ]

    def sort_key(abbreviation: str) -> tuple[float, int, int]:
        standing = state.standings.get(abbreviation)
        if standing is None:
            return (0.0, 0, 0)
        games = max(int(standing.games_played), 1)
        return (
            float(standing.wins) / games,
            int(standing.wins),
            int(standing.points_for) - int(standing.points_against),
        )

    ordered = sorted(teams, key=sort_key, reverse=True)
    rows: list[dict[str, Any]] = []

    for rank, abbreviation in enumerate(ordered[:limit], start=1):
        standing = state.standings.get(abbreviation)
        if standing is None:
            continue
        rows.append(
            {
                "rank": rank,
                "team": abbreviation,
                "name": TEAM_NAMES.get(abbreviation, abbreviation),
                "record": f"{standing.wins}-{standing.losses}",
                "wins": int(standing.wins),
                "losses": int(standing.losses),
                "point_diff": int(standing.points_for)
                - int(standing.points_against),
                "streak": (
                    f"{standing.streak_type}{standing.streak_length}"
                    if standing.streak_type
                    else ""
                ),
            }
        )
    return rows


def _league_leaders_payload(
    state: Any,
    *,
    limit: int = 3,
    minimum_games: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []

    for player_id, totals in state.player_season_totals.items():
        games = int(getattr(totals, "games_played", 0) or 0)
        if games < minimum_games:
            continue

        player = state.players.get(player_id)
        if player is None:
            continue

        rows.append(
            {
                "player_id": str(player_id),
                "name": str(getattr(player, "player_name", player_id)),
                "team": str(getattr(player, "team_abbreviation", "")),
                "games": games,
                "ppg": _per_game(getattr(totals, "points", 0), games),
                "rpg": _per_game(getattr(totals, "rebounds", 0), games),
                "apg": _per_game(getattr(totals, "assists", 0), games),
            }
        )

    def top(metric: str) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                -float(row.get(metric, 0.0)),
                str(row.get("name", "")),
            ),
        )[:limit]

    return {
        "scoring": top("ppg"),
        "rebounds": top("rpg"),
        "assists": top("apg"),
    }


def _recent_results_payload(
    state: Any,
    limit: int = 4,
) -> list[dict[str, Any]]:
    rows: list[tuple[int, str, Any]] = []

    for game_id, completed in state.completed_games.items():
        scheduled = state.schedule.get(str(game_id))
        day_index = int(
            getattr(scheduled, "day_index", state.current_day_index)
            if scheduled is not None
            else state.current_day_index
        )
        rows.append((day_index, str(game_id), completed))

    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)

    results: list[dict[str, Any]] = []
    for day_index, game_id, completed in rows[:limit]:
        results.append(
            {
                "game_id": game_id,
                "day_index": day_index,
                "away_team": str(completed.away_team),
                "away_score": int(completed.away_score),
                "home_team": str(completed.home_team),
                "home_score": int(completed.home_score),
                "display": (
                    f"{completed.away_team} {completed.away_score}  "
                    f"{completed.home_team} {completed.home_score}"
                ),
            }
        )
    return results


def _draft_collection_counts(state: Any) -> dict[str, int]:
    draft = _obj_dict(getattr(state, "franchise_draft_state_v1", {}))
    if not draft:
        return {}

    counts: dict[str, int] = {}
    candidate_keys = (
        "prospects",
        "draft_class",
        "board",
        "scouting_board",
        "reports",
        "scouting_reports",
        "scouts",
        "staff",
    )

    for key in candidate_keys:
        value = draft.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            counts[key] = len(value)

    return counts


def _front_office_payload(state: Any, active_team: str) -> dict[str, Any]:
    roster = _roster_payload(
        state,
        active_team,
        source="v3_working_checkpoint",
        editable=True,
    )
    players = list(roster.get("players", []))

    injured = [
        {
            "name": row.get("name"),
            "status": row.get("health", {}).get("display"),
            "games_remaining": row.get("health", {}).get("games_remaining", 0),
        }
        for row in players
        if row.get("health", {}).get("status")
        not in ("", "healthy", "unknown")
    ]

    morale_watch = [
        {
            "name": row.get("name"),
            "status": row.get("morale", {}).get("status"),
            "role": row.get("role"),
        }
        for row in players
        if str(row.get("morale", {}).get("status", ""))
        in ("Uneasy", "Frustrated", "Angry", "Demanding Trade")
    ][:5]

    team_state = state.teams.get(active_team)
    rotation = getattr(team_state, "rotation", None) if team_state else None
    rotation_ids = list(getattr(rotation, "rotation_player_ids", ())) if rotation else []
    starter_ids = list(getattr(rotation, "starter_ids", ())) if rotation else []
    minute_targets = dict(getattr(rotation, "minutes_targets", {})) if rotation else {}

    rank, conference = _conference_rank(state, active_team)
    standing = state.standings.get(active_team)

    return {
        "team": roster.get("team", {}),
        "chemistry": roster.get("chemistry", {}),
        "financial": roster.get("financial", {}),
        "injured_players": injured,
        "morale_watch": morale_watch,
        "rotation": {
            "starters": len(starter_ids),
            "rotation_players": len(rotation_ids),
            "total_minutes": round(sum(float(v) for v in minute_targets.values()), 1),
        },
        "competitive": {
            "record": (
                f"{standing.wins}-{standing.losses}"
                if standing is not None
                else ""
            ),
            "conference_rank": rank,
            "conference": conference,
        },
    }


def _franchise_intelligence_payload(
    state: Any,
    active_team: str,
) -> dict[str, Any]:
    draft = _draft_summary(state)
    return {
        "api_version": API_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": TEAM_NAMES.get(active_team, active_team),
        "season": {
            "label": str(state.settings.season_label),
            "phase": _enum_value(state.phase),
            "day_index": int(state.current_day_index),
        },
        "league": {
            "east": _ranked_standings_payload(state, "East", 5),
            "west": _ranked_standings_payload(state, "West", 5),
            "leaders": _league_leaders_payload(state),
            "recent_results": _recent_results_payload(state),
        },
        "scouting": {
            "draft": draft,
            "collection_counts": _draft_collection_counts(state),
        },
        "front_office": _front_office_payload(state, active_team),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def _primary_position(position: Any) -> str:
    raw = str(position or "").upper().strip()
    if not raw:
        return "UNK"
    return raw.split("/")[0].strip() or "UNK"


def _market_player_payload(player: Any) -> dict[str, Any]:
    contract = getattr(player, "contract", None)
    salary = _number(getattr(contract, "salary", None))
    overall = _number(getattr(player, "overall_rating", None))
    potential = _number(getattr(player, "potential_rating", None))
    future = _number(getattr(player, "future_outlook_rating", None))
    age = _number(getattr(player, "age", None))

    return {
        "player_id": str(getattr(player, "player_id", "")),
        "name": str(
            getattr(
                player,
                "player_name",
                getattr(player, "player_id", "Unknown"),
            )
        ),
        "position": str(getattr(player, "position", "") or ""),
        "primary_position": _primary_position(
            getattr(player, "position", "")
        ),
        "age": round(age, 1) if age is not None else None,
        "overall": round(overall, 1) if overall is not None else None,
        "potential": (
            round(potential, 1) if potential is not None else None
        ),
        "future_outlook": (
            round(future, 1) if future is not None else None
        ),
        "contract_status": str(
            getattr(contract, "status", "") or ""
        ),
        "salary": salary,
        "salary_display": _money_display(salary),
        "years_remaining": _safe_int(
            getattr(contract, "years_remaining", 0)
        ),
    }


def _free_agent_market_payload(
    state: Any,
    limit: int = 12,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for player_id in state.free_agent_player_ids:
        player = state.players.get(player_id)
        if player is None:
            continue

        row = _market_player_payload(player)
        rows.append(row)

        position = str(row.get("primary_position", "UNK"))
        counts[position] = counts.get(position, 0) + 1

    rows.sort(
        key=lambda row: (
            -float(row.get("overall") or 0.0),
            float(row.get("age") or 99.0),
            str(row.get("name", "")),
        )
    )

    return {
        "total_available": len(rows),
        "position_counts": counts,
        "top_available": rows[:limit],
    }


def _roster_depth_payload(
    state: Any,
    active_team: str,
) -> dict[str, Any]:
    team = state.teams.get(active_team)
    if team is None:
        return {}

    counts: dict[str, int] = {
        "PG": 0,
        "SG": 0,
        "SF": 0,
        "PF": 0,
        "C": 0,
        "OTHER": 0,
    }

    for player_id in team.roster_player_ids:
        player = state.players.get(player_id)
        if player is None:
            continue

        position = _primary_position(
            getattr(player, "position", "")
        )
        if position in counts:
            counts[position] += 1
        else:
            counts["OTHER"] += 1

    core = ["PG", "SG", "SF", "PF", "C"]
    thinnest = sorted(
        core,
        key=lambda pos: (counts[pos], pos),
    )

    return {
        "position_counts": counts,
        "thinnest_positions": thinnest[:2],
        "roster_size": len(team.roster_player_ids),
    }


def _trade_asset_payload(
    state: Any,
    active_team: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    roster = _roster_payload(
        state,
        active_team,
        source="v3_working_checkpoint",
        editable=True,
    )

    assets: list[dict[str, Any]] = []
    for row in roster.get("players", []):
        contract = row.get("contract", {})
        stats = row.get("season_stats", {})

        assets.append(
            {
                "player_id": str(row.get("player_id", "")),
                "name": str(row.get("name", "")),
                "position": str(row.get("position", "")),
                "age": row.get("age"),
                "overall": row.get("overall"),
                "potential": row.get("potential"),
                "future_outlook": row.get("future_outlook"),
                "role": str(row.get("role", "")),
                "salary_display": contract.get(
                    "salary_display"
                ),
                "years_remaining": contract.get(
                    "years_remaining"
                ),
                "ppg": stats.get("ppg", 0.0),
            }
        )

    assets.sort(
        key=lambda row: (
            -float(row.get("future_outlook") or 0.0),
            -float(row.get("overall") or 0.0),
            float(row.get("age") or 99.0),
        )
    )
    return assets[:limit]


def _market_intelligence_payload(
    state: Any,
    active_team: str,
) -> dict[str, Any]:
    roster_financial = _roster_financial_summary(
        state,
        active_team,
    )

    return {
        "api_version": API_VERSION,
        "source": "v3_working_checkpoint",
        "read_only": True,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": TEAM_NAMES.get(active_team, active_team),
        "season": {
            "label": str(state.settings.season_label),
            "phase": _enum_value(state.phase),
            "day_index": int(state.current_day_index),
        },
        "free_agency": _free_agent_market_payload(state),
        "roster_depth": _roster_depth_payload(
            state,
            active_team,
        ),
        "trade": {
            "assets": _trade_asset_payload(
                state,
                active_team,
            ),
            "financial": roster_financial,
            "draft": _draft_summary(state),
            "incoming_offer_queue_exposed": False,
            "write_actions_enabled": False,
        },
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


async def transaction_foundation(request: Request) -> JSONResponse:
    working_before = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
    v2_path = Path(DEFAULT_CHECKPOINT_PATH)
    v2_before = _file_sha256(v2_path)
    try:
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse({"error": "v3_working_save_not_initialized", "read_only": True, "active_v2_read_only": True}, status_code=409)
        active_team = _active_team_from_checkpoint(checkpoint)
        if not active_team:
            return JSONResponse({"error": "active_franchise_not_found", "read_only": True, "active_v2_read_only": True}, status_code=404)

        include_trade_finder = str(request.query_params.get("trade_finder", "1")).strip().lower() not in {"0", "false", "no"}
        payload = build_transaction_foundation_payload(checkpoint, active_team, include_trade_finder=include_trade_finder)
        working_after = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
        v2_after = _file_sha256(v2_path)
        working_unchanged = bool(working_before is not None and working_before == working_after)
        v2_unchanged = bool(v2_before is not None and v2_before == v2_after)
        payload.update({
            "api_version": API_VERSION,
            "working_save_sha256": working_after,
            "working_save_unchanged": working_unchanged,
            "active_v2_sha256": v2_after,
            "active_v2_unchanged": v2_unchanged,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })
        if not working_unchanged or not v2_unchanged:
            return JSONResponse({"error": "read_only_transaction_foundation_changed_checkpoint", **payload}, status_code=500)
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse({
            "error": "transaction_foundation_failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
            "read_only": True,
            "active_v2_read_only": True,
            "working_save_unchanged": working_before == _file_sha256(V3_WORKING_CHECKPOINT_PATH),
            "active_v2_unchanged": v2_before == _file_sha256(v2_path),
        }, status_code=500)


async def trade_preview(request: Request) -> JSONResponse:
    working_before = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
    v2_path = Path(DEFAULT_CHECKPOINT_PATH)
    v2_before = _file_sha256(v2_path)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Trade preview request body must be a JSON object.")
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse({"error": "v3_working_save_not_initialized"}, status_code=409)
        active_team = _active_team_from_checkpoint(checkpoint)
        payload = build_trade_preview_payload(checkpoint, active_team, body)
        working_after = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
        v2_after = _file_sha256(v2_path)
        payload.update({
            "api_version": API_VERSION,
            "working_save_unchanged": working_before is not None and working_before == working_after,
            "active_v2_unchanged": v2_before is not None and v2_before == v2_after,
            "working_save_write_performed": False,
        })
        if not payload["working_save_unchanged"] or not payload["active_v2_unchanged"]:
            return JSONResponse({"error": "trade_preview_changed_checkpoint", **payload}, status_code=500)
        return JSONResponse(payload)
    except ValueError as exc:
        return JSONResponse({
            "error": "invalid_trade_preview_request",
            "detail": str(exc),
            "working_save_unchanged": working_before == _file_sha256(V3_WORKING_CHECKPOINT_PATH),
            "active_v2_unchanged": v2_before == _file_sha256(v2_path),
        }, status_code=400)
    except Exception as exc:
        return JSONResponse({
            "error": "trade_preview_failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
            "working_save_unchanged": working_before == _file_sha256(V3_WORKING_CHECKPOINT_PATH),
            "active_v2_unchanged": v2_before == _file_sha256(v2_path),
        }, status_code=500)


async def free_agency_preview(request: Request) -> JSONResponse:
    working_before = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
    v2_path = Path(DEFAULT_CHECKPOINT_PATH)
    v2_before = _file_sha256(v2_path)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Free-agency preview request body must be a JSON object.")
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse({"error": "v3_working_save_not_initialized"}, status_code=409)
        active_team = _active_team_from_checkpoint(checkpoint)
        payload = build_free_agency_preview_payload(checkpoint, active_team, body)
        working_after = _file_sha256(V3_WORKING_CHECKPOINT_PATH)
        v2_after = _file_sha256(v2_path)
        payload.update({
            "api_version": API_VERSION,
            "working_save_unchanged": working_before is not None and working_before == working_after,
            "active_v2_unchanged": v2_before is not None and v2_before == v2_after,
            "working_save_write_performed": False,
        })
        if not payload["working_save_unchanged"] or not payload["active_v2_unchanged"]:
            return JSONResponse({"error": "free_agency_preview_changed_checkpoint", **payload}, status_code=500)
        return JSONResponse(payload)
    except ValueError as exc:
        return JSONResponse({
            "error": "invalid_free_agency_preview_request",
            "detail": str(exc),
            "working_save_unchanged": working_before == _file_sha256(V3_WORKING_CHECKPOINT_PATH),
            "active_v2_unchanged": v2_before == _file_sha256(v2_path),
        }, status_code=400)
    except Exception as exc:
        return JSONResponse({
            "error": "free_agency_preview_failed",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
            "working_save_unchanged": working_before == _file_sha256(V3_WORKING_CHECKPOINT_PATH),
            "active_v2_unchanged": v2_before == _file_sha256(v2_path),
        }, status_code=500)


async def market_intelligence(_: Request) -> JSONResponse:
    try:
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)
        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        return JSONResponse(
            _market_intelligence_payload(
                state,
                active_team,
            )
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": "market_intelligence_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "read_only": True,
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def franchise_intelligence(_: Request) -> JSONResponse:
    try:
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)
        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        return JSONResponse(
            _franchise_intelligence_payload(state, active_team)
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": "franchise_intelligence_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "read_only": True,
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": API_VERSION,
            "phase": "V3 desktop development",
            "read_only": True,
            "active_v2_read_only": True,
            "v3_working_save_writable": True,
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
            "save_access": "active_v2_read_only__v3_working_save_writable",
            "working_save_path": str(V3_WORKING_CHECKPOINT_PATH),
            "api_version": API_VERSION,
        }
    )


async def franchise_summary(_: Request) -> JSONResponse:
    # V3 Home follows the isolated working checkpoint. Protected V2 remains
    # a read-only fallback only before V3 working-save initialization.
    try:
        checkpoint = _working_checkpoint()
        source = "v3_working_checkpoint"

        if checkpoint is None:
            checkpoint = load_franchise_checkpoint()
            source = "active_v2_franchise_checkpoint"

        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "franchise_checkpoint_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)

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
            "source": source,
            "active_v2_read_only": True,
            "v3_working_save_writable": True,
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
    # Prefer the isolated V3 working save. Fall back to protected V2 only
    # before a working save has been initialized.
    try:
        checkpoint = _working_checkpoint()
        source = "v3_working_checkpoint"
        editable = True

        if checkpoint is None:
            checkpoint = load_franchise_checkpoint()
            source = "active_v2_franchise_checkpoint"
            editable = False

        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "franchise_checkpoint_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)

        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        payload = _roster_payload(
            state,
            active_team,
            source=source,
            editable=editable,
        )

        if not payload:
            return JSONResponse(
                {
                    "error": "active_team_roster_not_found",
                    "team": active_team,
                    "active_v2_read_only": True,
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
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def working_save_status(_: Request) -> JSONResponse:
    try:
        active_v2 = load_franchise_checkpoint()
        if active_v2 is None:
            return JSONResponse(
                {
                    "error": "active_v2_checkpoint_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        working = _working_checkpoint()
        active_team = _active_team_from_checkpoint(active_v2)

        payload: dict[str, Any] = {
            "api_version": API_VERSION,
            "active_v2_read_only": True,
            "active_v2_path": str(DEFAULT_CHECKPOINT_PATH),
            "active_v2_sha256": _file_sha256(DEFAULT_CHECKPOINT_PATH),
            "working_save_path": str(V3_WORKING_CHECKPOINT_PATH),
            "working_save_exists": working is not None,
            "active_team": active_team,
        }

        if working is not None:
            state = working.simulation_state
            working_team = _active_team_from_checkpoint(working)
            team_state = state.teams.get(working_team)
            payload["working_save"] = {
                "team": working_team,
                "season": str(state.settings.season_label),
                "phase": _enum_value(state.phase),
                "day_index": int(state.current_day_index),
                "sha256": _file_sha256(V3_WORKING_CHECKPOINT_PATH),
                "reason": str(working.reason),
                "rotation": (
                    {
                        "starter_ids": list(team_state.rotation.starter_ids),
                        "rotation_player_ids": list(
                            team_state.rotation.rotation_player_ids
                        ),
                        "minutes_targets": dict(
                            team_state.rotation.minutes_targets
                        ),
                        "total_minutes": round(
                            sum(team_state.rotation.minutes_targets.values()),
                            1,
                        ),
                    }
                    if team_state is not None
                    else None
                ),
            }

        return JSONResponse(payload)

    except Exception as exc:
        return JSONResponse(
            {
                "error": "working_save_status_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def reset_working_save(_: Request) -> JSONResponse:
    try:
        active_v2_sha_before = _file_sha256(DEFAULT_CHECKPOINT_PATH)
        active = load_franchise_checkpoint()

        if active is None:
            return JSONResponse(
                {
                    "error": "active_v2_checkpoint_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        V3_WORKING_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)

        save_franchise_checkpoint(
            active.simulation_state,
            active.trade_state,
            preferences=active.preferences,
            reason="V3 working save initialized from active V2 checkpoint",
            path=V3_WORKING_CHECKPOINT_PATH,
            copy_payload=False,
            force_replace=True,
        )

        verified = _working_checkpoint()
        if verified is None:
            raise RuntimeError("V3 working checkpoint could not be reloaded.")

        active_v2_sha_after = _file_sha256(DEFAULT_CHECKPOINT_PATH)

        if active_v2_sha_before != active_v2_sha_after:
            raise RuntimeError(
                "Active V2 checkpoint changed during V3 working-save reset."
            )

        state = verified.simulation_state
        active_team = _active_team_from_checkpoint(verified)

        return JSONResponse(
            {
                "status": "ok",
                "api_version": API_VERSION,
                "active_v2_read_only": True,
                "active_v2_unchanged": True,
                "active_v2_sha256": active_v2_sha_after,
                "working_save_path": str(V3_WORKING_CHECKPOINT_PATH),
                "working_save_sha256": _file_sha256(
                    V3_WORKING_CHECKPOINT_PATH
                ),
                "team": active_team,
                "season": str(state.settings.season_label),
                "phase": _enum_value(state.phase),
                "day_index": int(state.current_day_index),
            }
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": "working_save_reset_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def rotation_preview(request: Request) -> JSONResponse:
    try:
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "hint": "POST /v3/working-save/reset first.",
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)
        payload = await request.json()
        rows = _rotation_rows_from_request(payload)

        plan = rotation_plan_from_rows(
            state,
            active_team,
            rows,
        )

        return JSONResponse(
            {
                "status": "valid",
                "api_version": API_VERSION,
                "write_performed": False,
                "working_save_only": True,
                "active_v2_read_only": True,
                "plan": _rotation_plan_payload(plan),
            }
        )

    except Exception as exc:
        return JSONResponse(
            {
                "status": "invalid",
                "error": "rotation_preview_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "write_performed": False,
                "working_save_only": True,
                "active_v2_read_only": True,
            },
            status_code=400,
        )


async def rotation_apply(request: Request) -> JSONResponse:
    try:
        active_v2_sha_before = _file_sha256(DEFAULT_CHECKPOINT_PATH)

        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "hint": "POST /v3/working-save/reset first.",
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)
        payload = await request.json()
        rows = _rotation_rows_from_request(payload)

        plan = rotation_plan_from_rows(
            state,
            active_team,
            rows,
        )
        updated_state = apply_rotation_plan(
            state,
            plan,
        )

        save_franchise_checkpoint(
            updated_state,
            checkpoint.trade_state,
            preferences=checkpoint.preferences,
            reason="V3 Godot rotation update",
            path=V3_WORKING_CHECKPOINT_PATH,
            copy_payload=False,
            force_replace=True,
        )

        verified = _working_checkpoint()
        if verified is None:
            raise RuntimeError("Saved V3 working checkpoint could not be reloaded.")

        verified_team = verified.simulation_state.teams[active_team]
        verified_rotation = verified_team.rotation

        persisted = (
            tuple(verified_rotation.starter_ids) == tuple(plan.starter_ids)
            and tuple(verified_rotation.rotation_player_ids)
            == tuple(plan.rotation_player_ids)
            and {
                str(player_id): round(float(minutes), 1)
                for player_id, minutes in verified_rotation.minutes_targets.items()
            }
            == {
                str(player_id): round(float(minutes), 1)
                for player_id, minutes in plan.minutes_targets.items()
            }
        )

        if not persisted:
            raise RuntimeError(
                "V3 rotation write did not persist exactly after reload."
            )

        active_v2_sha_after = _file_sha256(DEFAULT_CHECKPOINT_PATH)
        active_v2_unchanged = active_v2_sha_before == active_v2_sha_after

        if not active_v2_unchanged:
            raise RuntimeError(
                "Active V2 checkpoint changed during isolated V3 rotation write."
            )

        return JSONResponse(
            {
                "status": "applied",
                "api_version": API_VERSION,
                "working_save_only": True,
                "active_v2_read_only": True,
                "active_v2_unchanged": True,
                "persisted_after_reload": True,
                "active_v2_sha256": active_v2_sha_after,
                "working_save_sha256": _file_sha256(
                    V3_WORKING_CHECKPOINT_PATH
                ),
                "plan": _rotation_plan_payload(plan),
            }
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": "rotation_apply_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "working_save_only": True,
                "active_v2_read_only": True,
            },
            status_code=400,
        )


async def game_day_summary(_: Request) -> JSONResponse:
    try:
        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "hint": "POST /v3/working-save/reset first.",
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)

        if not active_team:
            return JSONResponse(
                {
                    "error": "active_franchise_not_found",
                    "active_v2_read_only": True,
                },
                status_code=404,
            )

        return JSONResponse(_game_day_payload(state, active_team))

    except Exception as exc:
        return JSONResponse(
            {
                "error": "game_day_summary_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "working_save_only": True,
                "active_v2_read_only": True,
            },
            status_code=500,
        )


async def game_day_simulate(_: Request) -> JSONResponse:
    # Exact next controlled regular-season game only. Operates exclusively
    # on the isolated V3 working checkpoint.
    try:
        active_v2_sha_before = _file_sha256(DEFAULT_CHECKPOINT_PATH)

        checkpoint = _working_checkpoint()
        if checkpoint is None:
            return JSONResponse(
                {
                    "error": "v3_working_save_not_initialized",
                    "hint": "POST /v3/working-save/reset first.",
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        state = checkpoint.simulation_state
        active_team = _active_team_from_checkpoint(checkpoint)

        if _enum_value(state.phase).lower() != "regular_season":
            return JSONResponse(
                {
                    "error": "game_day_not_regular_season",
                    "phase": _enum_value(state.phase),
                    "working_save_only": True,
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        game = _next_controlled_scheduled_game(state, active_team)
        if game is None:
            return JSONResponse(
                {
                    "error": "no_controlled_game_scheduled",
                    "working_save_only": True,
                    "active_v2_read_only": True,
                },
                status_code=409,
            )

        game_id = str(game.game_id)
        before_record = _standing_payload(state, active_team)
        source_fingerprint = regular_season_state_fingerprint(state)

        # Mirrors V2 Franchise Mode commit_game_transactionally:
        # deepcopy, exact single-game simulator, committed result, deferred
        # global validation, then one authoritative validation.
        updated = copy.deepcopy(state)
        simulate_scheduled_game(
            updated,
            game_id,
            seed=None,
            commit=True,
            sit_player_ids=(),
            _defer_global_state_validation=True,
        )
        validate_simulation_league_state(updated)

        if regular_season_state_fingerprint(state) != source_fingerprint:
            raise RuntimeError(
                "Controlled-game simulation mutated the source working state."
            )

        completed = updated.completed_games.get(game_id)
        if completed is None:
            raise RuntimeError(
                "Controlled game was not committed after simulation."
            )

        # Reuse the existing V2 league-calendar catch-up so all CPU games
        # before the following CHI decision are synchronized.
        updated, sync_report = catch_up_cpu_schedule_v1(
            updated,
            controlled_teams=(active_team,),
            private_transactional_state=True,
        )
        validate_simulation_league_state(updated)

        after_record = _standing_payload(updated, active_team)
        if (
            int(after_record.get("games_played", 0))
            != int(before_record.get("games_played", 0)) + 1
        ):
            raise RuntimeError(
                "Controlled team's games played did not advance by exactly one."
            )

        save_franchise_checkpoint(
            updated,
            checkpoint.trade_state,
            preferences=checkpoint.preferences,
            reason=f"V3 Godot Game Day commit {game_id}",
            path=V3_WORKING_CHECKPOINT_PATH,
            copy_payload=False,
            force_replace=True,
        )

        verified = _working_checkpoint()
        if verified is None:
            raise RuntimeError(
                "Saved V3 Game Day checkpoint could not be reloaded."
            )

        verified_state = verified.simulation_state
        verified_completed = verified_state.completed_games.get(game_id)
        if verified_completed is None:
            raise RuntimeError(
                "Game Day result did not persist after checkpoint reload."
            )

        verified_record = _standing_payload(
            verified_state,
            active_team,
        )
        if verified_record != after_record:
            raise RuntimeError(
                "Team record changed across Game Day save/reload verification."
            )

        if (
            int(verified_completed.home_score) != int(completed.home_score)
            or int(verified_completed.away_score) != int(completed.away_score)
        ):
            raise RuntimeError(
                "Game score changed across Game Day save/reload verification."
            )

        active_v2_sha_after = _file_sha256(DEFAULT_CHECKPOINT_PATH)
        if active_v2_sha_before != active_v2_sha_after:
            raise RuntimeError(
                "Protected V2 checkpoint changed during V3 Game Day simulation."
            )

        result_payload = _completed_game_payload(
            verified_state,
            verified_completed,
        )
        active_score = (
            int(verified_completed.home_score)
            if str(verified_completed.home_team) == active_team
            else int(verified_completed.away_score)
        )
        opponent_score = (
            int(verified_completed.away_score)
            if str(verified_completed.home_team) == active_team
            else int(verified_completed.home_score)
        )

        return JSONResponse(
            {
                "status": "applied",
                "api_version": API_VERSION,
                "working_save_only": True,
                "active_v2_read_only": True,
                "active_v2_unchanged": True,
                "persisted_after_reload": True,
                "game_id": game_id,
                "result": "W" if active_score > opponent_score else "L",
                "before_record": before_record,
                "after_record": verified_record,
                "game": result_payload,
                "cpu_games_synchronized": int(
                    sync_report.get("games_simulated", 0)
                ),
                "league_sync": sync_report,
                "next_game": _game_day_payload(
                    verified_state,
                    active_team,
                ).get("next_game"),
                "active_v2_sha256": active_v2_sha_after,
                "working_save_sha256": _file_sha256(
                    V3_WORKING_CHECKPOINT_PATH
                ),
            }
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": "game_day_simulation_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "working_save_only": True,
                "active_v2_read_only": True,
            },
            status_code=400,
        )

async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=404)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v3/meta", project_meta, methods=["GET"]),
    Route("/v3/franchise-summary", franchise_summary, methods=["GET"]),
    Route("/v3/franchise-intelligence", franchise_intelligence, methods=["GET"]),
    Route("/v3/market-intelligence", market_intelligence, methods=["GET"]),
    Route("/v3/transaction-foundation", transaction_foundation, methods=["GET"]),
    Route("/v3/trade/preview", trade_preview, methods=["POST"]),
    Route("/v3/free-agency/preview", free_agency_preview, methods=["POST"]),
    Route("/v3/roster", roster_summary, methods=["GET"]),
    Route("/v3/working-save/status", working_save_status, methods=["GET"]),
    Route("/v3/working-save/reset", reset_working_save, methods=["POST"]),
    Route("/v3/rotation/preview", rotation_preview, methods=["POST"]),
    Route("/v3/rotation/apply", rotation_apply, methods=["POST"]),
    Route("/v3/game-day", game_day_summary, methods=["GET"]),
    Route("/v3/game-day/simulate", game_day_simulate, methods=["POST"]),
]


app = Starlette(
    debug=False,
    routes=routes,
    exception_handlers={404: not_found},
)
