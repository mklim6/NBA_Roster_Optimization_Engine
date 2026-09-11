from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from freeform_trade_machine_engine_v3 import (
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from franchise_asset_market_value_v1 import (
    ASSET_MARKET_CONTEXT_VERSION,
    ASSET_MARKET_MODEL_VERSION,
    build_league_asset_market_contexts,
)
from franchise_cpu_front_office_v1 import (
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    build_league_front_office_plan,
    front_office_state_fingerprint,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

try:
    from simulation_postseason_v1 import (
        postseason_player_rows,
        postseason_team_rows,
    )
except Exception:
    postseason_player_rows = None
    postseason_team_rows = None

AUDIT_EXPORT_VERSION = "franchise-audit-export-v1.1-2026-08-13"
AUDIT_SCHEMA_VERSION = "franchise-audit-schema-v1.1-2026-08-13"

DEFAULT_OUTPUT_DIR = (
    Path("outputs")
    / "audit_exports"
)

REQUIRED_EXPORT_FILES = (
    "audit_manifest.csv",
    "audit_file_inventory.csv",
    "team_state.csv",
    "team_rosters.csv",
    "league_player_pool.csv",
    "active_rosters.csv",
    "free_agent_pool.csv",
    "player_market_context.csv",
    "player_health.csv",
    "injury_records.csv",
    "player_contracts.csv",
    "standings.csv",
    "regular_season_player_stats.csv",
    "regular_season_team_stats.csv",
    "playoff_player_stats.csv",
    "playoff_team_stats.csv",
    "season_history.csv",
    "cpu_front_office_team_plans.csv",
    "cpu_front_office_player_decisions.csv",
    "cpu_trade_package_intents.csv",
    "draft_rights.csv",
    "transactions.csv",
    "trade_finder_search_summary.csv",
    "trade_finder_package_audit.csv",
    "trade_finder_actionable_offers.csv",
)


@dataclass(frozen=True)
class FranchiseAuditExportResult:
    version: str
    schema_version: str
    export_id: str
    season_label: str
    checkpoint_sha256: str
    state_fingerprint: str
    active_trade_finder_team: str
    include_trade_finder: bool
    zip_path: str
    zip_sha256: str
    file_count: int
    row_counts: dict[str, int]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {
            key: _jsonable(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _jsonable(item)
            for item in value
        ]
    if hasattr(value, "value") and isinstance(
        getattr(value, "value", None),
        (str, int, float, bool),
    ):
        return _jsonable(value.value)
    return str(value)


def _csv_cell(value: Any) -> Any:
    normalized = _jsonable(value)
    if normalized is None:
        return ""
    if isinstance(normalized, (dict, list)):
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return normalized


def _object_to_row(
    value: Any,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        source = dict(value)
    elif is_dataclass(value):
        source = asdict(value)
    else:
        try:
            source = vars(value)
        except TypeError:
            return {"value": _csv_cell(value)}

    output: dict[str, Any] = {}
    for key, item in source.items():
        key = str(key)
        if not include_private and key.startswith("_"):
            continue
        if callable(item):
            continue
        output[key] = _csv_cell(item)
    return output


def _write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    preferred_columns: Iterable[str] = (),
) -> int:
    materialized = [
        {
            str(key): _csv_cell(value)
            for key, value in dict(row).items()
        }
        for row in rows
    ]

    columns: list[str] = []
    seen: set[str] = set()

    for column in preferred_columns:
        name = str(column)
        if name not in seen:
            seen.add(name)
            columns.append(name)

    for row in materialized:
        for column in row:
            if column not in seen:
                seen.add(column)
                columns.append(column)

    if not columns:
        columns = ["status"]

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in materialized:
            writer.writerow(row)

    return len(materialized)


def _controlled_teams(
    preferences: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    preferences = dict(preferences or {})
    raw = preferences.get(
        "franchise_pref_controlled_teams",
        (),
    )
    if isinstance(raw, str):
        raw = (raw,)
    try:
        values = tuple(raw)
    except TypeError:
        values = ()
    return tuple(
        team
        for team in (
            normalize_team(value)
            for value in values
        )
        if team
    )


def _active_trade_team(
    state: Any,
    controlled: tuple[str, ...],
    requested: str = "",
) -> str:
    teams = {
        normalize_team(team)
        for team in getattr(
            state,
            "teams",
            {},
        )
    }
    requested = normalize_team(requested)
    if requested and requested in teams:
        return requested
    for team in controlled:
        if team in teams:
            return team
    if "PHI" in teams:
        return "PHI"
    return sorted(teams)[0] if teams else ""


def _team_player_map(state: Any) -> dict[str, str]:
    output: dict[str, str] = {}
    for team, team_state in getattr(
        state,
        "teams",
        {},
    ).items():
        normalized_team = normalize_team(team)
        for raw_id in tuple(
            getattr(
                team_state,
                "roster_player_ids",
                (),
            )
            or ()
        ):
            player_id = normalize_player_id(raw_id)
            if player_id:
                output[player_id] = normalized_team
    return output


def _player_name(player: Any, player_id: str) -> str:
    return _clean(
        getattr(player, "player_name", "")
        or getattr(player, "name", "")
        or player_id
    )


def _player_health_rows(
    state: Any,
    team_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    players = getattr(
        state,
        "players",
        {},
    ) or {}

    for raw_id, player in players.items():
        player_id = normalize_player_id(
            getattr(
                player,
                "player_id",
                raw_id,
            )
        )
        if not player_id:
            continue

        row = {
            "player_id": player_id,
            "team": team_map.get(
                player_id,
                "",
            ),
            "player_name": _player_name(
                player,
                player_id,
            ),
            "age": getattr(
                player,
                "age",
                "",
            ),
            "overall": getattr(
                player,
                "overall_rating",
                getattr(
                    player,
                    "overall",
                    "",
                ),
            ),
            "availability": getattr(
                player,
                "availability",
                getattr(
                    player,
                    "availability_status",
                    "",
                ),
            ),
            "injury_status": getattr(
                player,
                "injury_status",
                getattr(
                    player,
                    "medical_status",
                    "",
                ),
            ),
            "health_status": getattr(
                player,
                "health_status",
                "",
            ),
            "injury_games_remaining": getattr(
                player,
                "injury_games_remaining",
                getattr(
                    player,
                    "games_remaining_injury",
                    "",
                ),
            ),
            "fatigue": getattr(
                player,
                "fatigue",
                getattr(
                    player,
                    "fatigue_level",
                    "",
                ),
            ),
            "stamina": getattr(
                player,
                "stamina",
                getattr(
                    player,
                    "stamina_rating",
                    "",
                ),
            ),
            "durability": getattr(
                player,
                "durability",
                getattr(
                    player,
                    "durability_rating",
                    "",
                ),
            ),
            "career_status": getattr(
                player,
                "career_status",
                "",
            ),
            "retirement_status": getattr(
                player,
                "retirement_status",
                "",
            ),
        }

        # Preserve primitive health-like fields that future Medical versions add.
        try:
            raw_attrs = vars(player)
        except TypeError:
            raw_attrs = {}

        for key, value in raw_attrs.items():
            lower = str(key).lower()
            if not any(
                token in lower
                for token in (
                    "injur",
                    "health",
                    "medical",
                    "fatigue",
                    "stamina",
                    "durab",
                    "avail",
                    "recover",
                )
            ):
                continue
            if key in row:
                continue
            if isinstance(
                value,
                (
                    str,
                    int,
                    float,
                    bool,
                    type(None),
                ),
            ):
                row[str(key)] = value

        rows.append(row)

    return rows


def _player_contract_rows(
    state: Any,
    team_map: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    players = getattr(
        state,
        "players",
        {},
    ) or {}

    for raw_id, player in players.items():
        player_id = normalize_player_id(
            getattr(
                player,
                "player_id",
                raw_id,
            )
        )
        if not player_id:
            continue

        contract = getattr(
            player,
            "contract",
            None,
        )
        row = {
            "player_id": player_id,
            "team": team_map.get(
                player_id,
                "",
            ),
            "player_name": _player_name(
                player,
                player_id,
            ),
            "age": getattr(
                player,
                "age",
                "",
            ),
        }

        if contract is not None:
            contract_row = _object_to_row(
                contract
            )
            for key, value in contract_row.items():
                row[f"contract_{key}"] = value

        # Stable convenience aliases.
        row["salary"] = getattr(
            contract,
            "salary",
            "",
        ) if contract is not None else ""
        row["years_remaining"] = getattr(
            contract,
            "years_remaining",
            "",
        ) if contract is not None else ""
        row["contract_status"] = getattr(
            contract,
            "status",
            "",
        ) if contract is not None else ""

        rows.append(row)

    return rows


def _team_state_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team, team_state in sorted(
        getattr(
            state,
            "teams",
            {},
        ).items()
    ):
        row = {
            "team": normalize_team(team),
            "roster_count": len(
                tuple(
                    getattr(
                        team_state,
                        "roster_player_ids",
                        (),
                    )
                    or ()
                )
            ),
            "roster_player_ids": tuple(
                getattr(
                    team_state,
                    "roster_player_ids",
                    (),
                )
                or ()
            ),
        }

        try:
            attrs = vars(team_state)
        except TypeError:
            attrs = {}

        for key, value in attrs.items():
            if key == "roster_player_ids":
                continue
            if isinstance(
                value,
                (
                    str,
                    int,
                    float,
                    bool,
                    type(None),
                ),
            ):
                row[str(key)] = value

        rows.append(row)
    return rows



def _all_player_pool_rows(
    state: Any,
    ledger: Any,
) -> list[dict[str, Any]]:
    ledger_by_id = {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in getattr(ledger, "player_rows", ()) or ()
        if normalize_player_id(row.get("player_id"))
    }
    free_agent_ids = {
        normalize_player_id(player_id)
        for player_id in (
            getattr(
                state,
                "free_agent_player_ids",
                (),
            )
            or ()
        )
        if normalize_player_id(player_id)
    }

    rows: list[dict[str, Any]] = []
    for player_id, player in sorted(
        getattr(state, "players", {}).items()
    ):
        normalized = normalize_player_id(player_id)
        ledger_row = ledger_by_id.get(normalized, {})
        row = dict(ledger_row)
        row.update(
            {
                "player_id": normalized,
                "player_name": _clean(
                    getattr(player, "player_name", "")
                ),
                "team": _clean(
                    getattr(
                        player,
                        "team_abbreviation",
                        "",
                    )
                ),
                "roster_status": _clean(
                    getattr(
                        player,
                        "roster_status",
                        "",
                    )
                ),
                "position": _clean(
                    getattr(player, "position", "")
                ),
                "overall": getattr(
                    player,
                    "overall_rating",
                    "",
                ),
                "synthetic": bool(
                    getattr(player, "synthetic", False)
                ),
                "two_way": bool(
                    getattr(player, "two_way", False)
                ),
                "is_free_agent": (
                    normalized in free_agent_ids
                ),
            }
        )
        rows.append(row)
    return rows


def _active_roster_rows(
    state: Any,
    player_pool_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roster_ids = {
        normalize_player_id(player_id)
        for team_state in getattr(
            state,
            "teams",
            {},
        ).values()
        for player_id in (
            getattr(
                team_state,
                "roster_player_ids",
                (),
            )
            or ()
        )
        if normalize_player_id(player_id)
    }
    return [
        dict(row)
        for row in player_pool_rows
        if normalize_player_id(
            row.get("player_id")
        )
        in roster_ids
    ]


def _free_agent_rows(
    state: Any,
    player_pool_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    free_agent_ids = {
        normalize_player_id(player_id)
        for player_id in (
            getattr(
                state,
                "free_agent_player_ids",
                (),
            )
            or ()
        )
        if normalize_player_id(player_id)
    }
    return [
        dict(row)
        for row in player_pool_rows
        if normalize_player_id(
            row.get("player_id")
        )
        in free_agent_ids
    ]


def _injury_record_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows = []
    for player_id, player in sorted(
        getattr(state, "players", {}).items()
    ):
        normalized = normalize_player_id(player_id)
        injury = (
            getattr(state, "injuries", {}) or {}
        ).get(normalized)
        row = {
            "player_id": normalized,
            "player_name": _clean(
                getattr(player, "player_name", "")
            ),
            "team": _clean(
                getattr(
                    player,
                    "team_abbreviation",
                    "",
                )
            ),
            "position": _clean(
                getattr(player, "position", "")
            ),
            "status": _clean(
                getattr(
                    getattr(injury, "status", ""),
                    "value",
                    getattr(injury, "status", ""),
                )
            ),
            "injury_type": _clean(
                getattr(injury, "injury_type", "")
            ),
            "games_remaining": getattr(
                injury,
                "games_remaining",
                "",
            ),
            "performance_multiplier": getattr(
                injury,
                "performance_multiplier",
                "",
            ),
            "aggravation_risk": getattr(
                injury,
                "aggravation_risk",
                "",
            ),
            "notes": _clean(
                getattr(injury, "notes", "")
            ),
        }
        if injury is not None:
            for key, value in _object_to_row(
                injury
            ).items():
                row.setdefault(
                    f"injury_{key}",
                    value,
                )
        rows.append(row)
    return rows


def _medical_profile_rows(
    state: Any,
) -> list[dict[str, Any]]:
    profiles = (
        getattr(
            state,
            "injury_fatigue_profiles",
            {},
        )
        or {}
    )
    injuries = (
        getattr(
            state,
            "injuries",
            {},
        )
        or {}
    )

    rows = []
    for player_id, player in sorted(
        getattr(state, "players", {}).items()
    ):
        normalized = normalize_player_id(player_id)
        profile = profiles.get(normalized)
        injury = injuries.get(normalized)

        row = {
            "player_id": normalized,
            "player_name": _clean(
                getattr(player, "player_name", "")
            ),
            "team": _clean(
                getattr(
                    player,
                    "team_abbreviation",
                    "",
                )
            ),
            "position": _clean(
                getattr(player, "position", "")
            ),
            "roster_status": _clean(
                getattr(
                    player,
                    "roster_status",
                    "",
                )
            ),
            "availability_status": _clean(
                getattr(
                    getattr(injury, "status", ""),
                    "value",
                    getattr(injury, "status", ""),
                )
            ),
            "injury_type": _clean(
                getattr(injury, "injury_type", "")
            ),
            "injury_games_remaining": getattr(
                injury,
                "games_remaining",
                "",
            ),
        }

        if profile is not None:
            for key, value in _object_to_row(
                profile,
                include_private=False,
            ).items():
                # Avoid overwriting stable identity columns.
                output_key = (
                    key
                    if key not in row
                    else f"medical_{key}"
                )
                row[output_key] = value

        # Stable convenience aliases for audit/statistical work.
        row["fatigue"] = getattr(
            profile,
            "fatigue",
            "",
        ) if profile is not None else ""
        row["medical_profile_present"] = (
            profile is not None
        )

        rows.append(row)
    return rows


def _exact_contract_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows = []
    for player_id, player in sorted(
        getattr(state, "players", {}).items()
    ):
        normalized = normalize_player_id(player_id)
        contract = getattr(
            player,
            "contract",
            None,
        )
        row = {
            "player_id": normalized,
            "team": _clean(
                getattr(
                    player,
                    "team_abbreviation",
                    "",
                )
            ),
            "player_name": _clean(
                getattr(player, "player_name", "")
            ),
            "roster_status": _clean(
                getattr(
                    player,
                    "roster_status",
                    "",
                )
            ),
            "status": _clean(
                getattr(contract, "status", "")
            ),
            "salary": getattr(
                contract,
                "salary",
                "",
            ),
            "years_remaining": getattr(
                contract,
                "years_remaining",
                "",
            ),
            "option_type": _clean(
                getattr(
                    contract,
                    "option_type",
                    "",
                )
            ),
            "guaranteed": getattr(
                contract,
                "guaranteed",
                "",
            ),
            "contract_source": (
                "simulation_contract_state"
            ),
        }
        if contract is not None:
            for key, value in _object_to_row(
                contract
            ).items():
                row.setdefault(key, value)
        rows.append(row)
    return rows


def _standings_export_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows = []
    for team, standing in sorted(
        getattr(state, "standings", {}).items()
    ):
        games = int(
            getattr(
                standing,
                "games_played",
                0,
            )
            or 0
        )
        wins = int(
            getattr(standing, "wins", 0)
            or 0
        )
        losses = int(
            getattr(standing, "losses", 0)
            or 0
        )
        points_for = int(
            getattr(
                standing,
                "points_for",
                0,
            )
            or 0
        )
        points_against = int(
            getattr(
                standing,
                "points_against",
                0,
            )
            or 0
        )
        team_state = (
            getattr(state, "teams", {})
            or {}
        ).get(team)
        rows.append(
            {
                "team": normalize_team(team),
                "conference": _clean(
                    getattr(
                        team_state,
                        "conference",
                        "",
                    )
                ),
                "division": _clean(
                    getattr(
                        team_state,
                        "division",
                        "",
                    )
                ),
                "games_played": games,
                "wins": wins,
                "losses": losses,
                "win_pct": (
                    round(wins / games, 4)
                    if games
                    else 0.0
                ),
                "home_wins": getattr(
                    standing,
                    "home_wins",
                    0,
                ),
                "home_losses": getattr(
                    standing,
                    "home_losses",
                    0,
                ),
                "away_wins": getattr(
                    standing,
                    "away_wins",
                    0,
                ),
                "away_losses": getattr(
                    standing,
                    "away_losses",
                    0,
                ),
                "points_for": points_for,
                "points_against": points_against,
                "point_diff": (
                    points_for
                    - points_against
                ),
                "points_for_per_game": (
                    round(
                        points_for / games,
                        3,
                    )
                    if games
                    else 0.0
                ),
                "points_against_per_game": (
                    round(
                        points_against / games,
                        3,
                    )
                    if games
                    else 0.0
                ),
                "streak_type": _clean(
                    getattr(
                        standing,
                        "streak_type",
                        "",
                    )
                ),
                "streak_length": getattr(
                    standing,
                    "streak_length",
                    0,
                ),
            }
        )
    return rows


def _pct(
    made: float,
    attempted: float,
) -> float:
    return (
        round(
            100.0 * made / attempted,
            3,
        )
        if attempted
        else 0.0
    )


def _regular_player_stat_rows(
    state: Any,
) -> list[dict[str, Any]]:
    totals_map = (
        getattr(
            state,
            "player_season_totals",
            {},
        )
        or {}
    )

    rows = []
    for player_id, player in sorted(
        getattr(state, "players", {}).items()
    ):
        normalized = normalize_player_id(player_id)
        totals = totals_map.get(normalized)
        games = int(
            getattr(
                totals,
                "games_played",
                0,
            )
            or 0
        )
        minutes = float(
            getattr(totals, "minutes", 0.0)
            or 0.0
        )
        points = int(
            getattr(totals, "points", 0)
            or 0
        )
        fgm = int(
            getattr(
                totals,
                "field_goals_made",
                0,
            )
            or 0
        )
        fga = int(
            getattr(
                totals,
                "field_goals_attempted",
                0,
            )
            or 0
        )
        tpm = int(
            getattr(
                totals,
                "three_pointers_made",
                0,
            )
            or 0
        )
        tpa = int(
            getattr(
                totals,
                "three_pointers_attempted",
                0,
            )
            or 0
        )
        ftm = int(
            getattr(
                totals,
                "free_throws_made",
                0,
            )
            or 0
        )
        fta = int(
            getattr(
                totals,
                "free_throws_attempted",
                0,
            )
            or 0
        )
        possessions_denom = (
            2.0
            * (
                fga
                + 0.44 * fta
            )
        )

        per_game = lambda value: (
            round(
                float(value) / games,
                3,
            )
            if games
            else 0.0
        )

        rows.append(
            {
                "player_id": normalized,
                "player_name": _clean(
                    getattr(
                        player,
                        "player_name",
                        "",
                    )
                ),
                "team": _clean(
                    getattr(
                        player,
                        "team_abbreviation",
                        "",
                    )
                ),
                "position": _clean(
                    getattr(
                        player,
                        "position",
                        "",
                    )
                ),
                "roster_status": _clean(
                    getattr(
                        player,
                        "roster_status",
                        "",
                    )
                ),
                "games_played": games,
                "games_started": int(
                    getattr(
                        totals,
                        "games_started",
                        0,
                    )
                    or 0
                ),
                "minutes": round(
                    minutes,
                    3,
                ),
                "minutes_per_game": per_game(
                    minutes
                ),
                "points": points,
                "points_per_game": per_game(
                    points
                ),
                "rebounds": int(
                    getattr(
                        totals,
                        "rebounds",
                        0,
                    )
                    or 0
                ),
                "rebounds_per_game": per_game(
                    getattr(
                        totals,
                        "rebounds",
                        0,
                    )
                ),
                "assists": int(
                    getattr(
                        totals,
                        "assists",
                        0,
                    )
                    or 0
                ),
                "assists_per_game": per_game(
                    getattr(
                        totals,
                        "assists",
                        0,
                    )
                ),
                "steals": int(
                    getattr(
                        totals,
                        "steals",
                        0,
                    )
                    or 0
                ),
                "steals_per_game": per_game(
                    getattr(
                        totals,
                        "steals",
                        0,
                    )
                ),
                "blocks": int(
                    getattr(
                        totals,
                        "blocks",
                        0,
                    )
                    or 0
                ),
                "blocks_per_game": per_game(
                    getattr(
                        totals,
                        "blocks",
                        0,
                    )
                ),
                "turnovers": int(
                    getattr(
                        totals,
                        "turnovers",
                        0,
                    )
                    or 0
                ),
                "turnovers_per_game": per_game(
                    getattr(
                        totals,
                        "turnovers",
                        0,
                    )
                ),
                "fouls": int(
                    getattr(
                        totals,
                        "fouls",
                        0,
                    )
                    or 0
                ),
                "fouls_per_game": per_game(
                    getattr(
                        totals,
                        "fouls",
                        0,
                    )
                ),
                "field_goals_made": fgm,
                "field_goals_attempted": fga,
                "fg_pct": _pct(fgm, fga),
                "three_pointers_made": tpm,
                "three_pointers_attempted": tpa,
                "three_pct": _pct(tpm, tpa),
                "free_throws_made": ftm,
                "free_throws_attempted": fta,
                "ft_pct": _pct(ftm, fta),
                "effective_fg_pct": (
                    round(
                        100.0
                        * (
                            fgm
                            + 0.5 * tpm
                        )
                        / fga,
                        3,
                    )
                    if fga
                    else 0.0
                ),
                "true_shooting_pct": (
                    round(
                        100.0
                        * points
                        / possessions_denom,
                        3,
                    )
                    if possessions_denom
                    else 0.0
                ),
            }
        )
    return rows


def _regular_team_stat_rows(
    state: Any,
) -> list[dict[str, Any]]:
    # Standing-derived team metrics are the current canonical regular-season
    # team totals. This avoids re-aggregating 1,230 completed game objects.
    return _standings_export_rows(state)


def _postseason_rows(
    state: Any,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    if (
        postseason_player_rows is None
        or postseason_team_rows is None
    ):
        return [], []

    # Public postseason helpers may normalize/migrate postseason state. Run
    # them against a deepcopy so an audit export remains strictly read-only.
    cloned = copy.deepcopy(state)
    try:
        player_rows = list(
            postseason_player_rows(
                cloned
            )
            or []
        )
        team_rows = list(
            postseason_team_rows(
                cloned
            )
            or []
        )
    except Exception:
        return [], []

    return (
        [
            dict(row)
            for row in player_rows
        ],
        [
            dict(row)
            for row in team_rows
        ],
    )


def _season_history_rows(
    state: Any,
) -> list[dict[str, Any]]:
    rows = []
    history = (
        getattr(
            state,
            "season_history",
            (),
        )
        or ()
    )
    for index, archive in enumerate(
        history,
        start=1,
    ):
        postseason = getattr(
            archive,
            "postseason_state",
            None,
        )
        rows.append(
            {
                "archive_index": index,
                "season_label": _clean(
                    getattr(
                        archive,
                        "season_label",
                        "",
                    )
                ),
                "champion": _clean(
                    getattr(
                        archive,
                        "champion",
                        "",
                    )
                    or getattr(
                        postseason,
                        "champion",
                        "",
                    )
                ),
                "runner_up": _clean(
                    getattr(
                        archive,
                        "runner_up",
                        "",
                    )
                    or getattr(
                        postseason,
                        "runner_up",
                        "",
                    )
                ),
                "conference_champions": getattr(
                    archive,
                    "conference_champions",
                    {},
                ),
                "regular_games_completed": len(
                    getattr(
                        archive,
                        "completed_games",
                        {},
                    )
                    or {}
                ),
                "postseason_games_completed": int(
                    getattr(
                        archive,
                        "postseason_games_completed",
                        0,
                    )
                    or len(
                        getattr(
                            postseason,
                            "completed_games",
                            {},
                        )
                        or {}
                    )
                ),
                "transition_engine_version": _clean(
                    getattr(
                        archive,
                        "transition_engine_version",
                        "",
                    )
                ),
                "development_summary": getattr(
                    archive,
                    "development_summary",
                    {},
                ),
            }
        )
    return rows



def _transaction_rows(
    state: Any,
) -> list[dict[str, Any]]:
    raw = getattr(
        state,
        "franchise_transaction_history_v1",
        (),
    ) or ()
    rows = []
    for index, transaction in enumerate(
        raw,
        start=1,
    ):
        row = _object_to_row(
            transaction
        )
        row.setdefault(
            "transaction_index",
            index,
        )
        rows.append(row)
    return rows


def _front_office_rows(
    league_plan: Any,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    teams: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []
    intents: list[dict[str, Any]] = []

    for team, plan in sorted(
        league_plan.teams.items()
    ):
        team_row = {
            "team": team,
            "cpu_managed": plan.cpu_managed,
            "timeline": plan.timeline,
            "timeline_label": plan.timeline_label,
            "league_rank": plan.league_rank,
            "league_percentile": plan.league_percentile,
            "competitive_score": plan.competitive_score,
            "win_pct": plan.win_pct,
            "strength_score": plan.strength_score,
            "average_age": plan.average_age,
            "top_five_overall": plan.top_five_overall,
            "top_three_overall": plan.top_three_overall,
            "rotation_quality": plan.rotation_quality,
            "young_core_score": plan.young_core_score,
            "roster_count": plan.roster_count,
            "known_payroll": plan.known_payroll,
            "salary_coverage": plan.salary_coverage,
            "financial_posture": plan.financial_posture,
            "biggest_need": plan.biggest_need,
            "secondary_need": plan.secondary_need,
            "surplus_family": plan.surplus_family,
            "primary_upgrade_need": plan.primary_upgrade_need,
            "secondary_upgrade_need": plan.secondary_upgrade_need,
            "depth_surplus_family": plan.depth_surplus_family,
            "roster_balance_score": plan.roster_balance_score,
            "draft_posture": plan.draft_posture,
            "trade_goal": plan.trade_goal,
            "draft_first_budget": plan.draft_first_budget,
            "draft_second_budget": plan.draft_second_budget,
            "allow_pick_swap": plan.allow_pick_swap,
            "desired_return_profile": plan.desired_return_profile,
            "trade_intent_count": len(
                plan.trade_package_intents
            ),
            "direction_rationale": plan.direction_rationale,
            "objectives": plan.objectives,
            "need_scores": plan.need_scores,
            "surplus_scores": plan.surplus_scores,
            "position_profiles": plan.position_profiles,
        }
        teams.append(team_row)

        for decision in plan.player_decisions:
            row = {
                "team": team,
                **asdict(decision),
            }
            players.append(row)

        for intent in plan.trade_package_intents:
            row = {
                "team": team,
                **asdict(intent),
            }
            intents.append(row)

    return teams, players, intents


def _market_context_rows(
    state: Any,
    league_plan: Any,
) -> list[dict[str, Any]]:
    contexts = build_league_asset_market_contexts(
        state,
        team_timelines={
            team: plan.timeline
            for team, plan in league_plan.teams.items()
        },
    )
    return [
        asdict(context)
        for _, context in sorted(
            contexts.items()
        )
    ]


def _proposal_rows(
    result: Any,
) -> list[dict[str, Any]]:
    rows = []
    for proposal in result.proposals:
        data = asdict(proposal)
        preview = data.pop(
            "preview_payload",
            {},
        ) or {}
        data["preview_status"] = (
            preview.get("status", "")
            if isinstance(preview, Mapping)
            else ""
        )
        data["preview_can_commit"] = (
            preview.get(
                "can_commit",
                False,
            )
            if isinstance(preview, Mapping)
            else False
        )
        data[
            "preview_anchor_financial_resolution_applied"
        ] = (
            preview.get(
                "anchor_financial_resolution_applied",
                False,
            )
            if isinstance(preview, Mapping)
            else False
        )
        rows.append(data)
    return rows


def _trade_finder_summary_row(
    result: Any,
) -> dict[str, Any]:
    return {
        "version": result.version,
        "value_model_version": result.value_model_version,
        "season_label": result.season_label,
        "franchise_trade_revision": result.franchise_trade_revision,
        "active_team": result.active_team,
        "goal": result.goal,
        "partner_filter": result.partner_filter,
        "teams_scanned": result.teams_scanned,
        "targets_identified": result.targets_identified,
        "candidate_packages_generated": result.candidate_packages_generated,
        "value_screen_passes": result.value_screen_passes,
        "financial_prechecks": result.financial_prechecks,
        "financial_precheck_passes": result.financial_precheck_passes,
        "packages_evaluated": result.packages_evaluated,
        "legal_packages": result.legal_packages,
        "cpu_accepts_found": result.cpu_accepts_found,
        "cpu_counters_found": result.cpu_counters_found,
        "proposal_count": len(
            result.proposals
        ),
        "search_elapsed_seconds": result.search_elapsed_seconds,
        "partner_funnel": result.partner_funnel,
        "rejection_counts": result.rejection_counts,
        "rejection_examples": result.rejection_examples,
    }


def build_franchise_audit_export(
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    checkpoint_path: Path | str = DEFAULT_CHECKPOINT_PATH,
    include_trade_finder: bool = True,
    active_trade_finder_team: str = "",
    trade_finder_max_partners: int = 10,
    trade_finder_max_targets_per_partner: int = 4,
    trade_finder_max_package_evaluations: int = 12,
    trade_finder_max_financial_prechecks: int = 320,
) -> FranchiseAuditExportResult:
    checkpoint_path = Path(
        checkpoint_path
    )
    output_dir = Path(
        output_dir
    )
    if not checkpoint_path.is_file():
        raise RuntimeError(
            "Durable Franchise Mode checkpoint is missing: "
            f"{checkpoint_path}"
        )

    default_checkpoint_path = Path(
        DEFAULT_CHECKPOINT_PATH
    )

    # The durable checkpoint module's public loader is intentionally
    # zero-argument and owns its canonical path internally. V1 accidentally
    # passed checkpoint_path positionally even though static compilation could
    # not detect that API mismatch.
    #
    # Keep the argument for future schema compatibility, but fail clearly if a
    # caller tries to point V1.0.1 at a different checkpoint than the loader
    # owns.
    try:
        requested_resolved = checkpoint_path.resolve()
        default_resolved = default_checkpoint_path.resolve()
    except Exception:
        requested_resolved = checkpoint_path
        default_resolved = default_checkpoint_path

    if requested_resolved != default_resolved:
        raise RuntimeError(
            "Audit Export V1.0.1 supports only the canonical durable "
            "Franchise Mode checkpoint path used by "
            "load_franchise_checkpoint()."
        )

    checkpoint_sha_before = _sha256(
        checkpoint_path
    )
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError(
            "Durable Franchise Mode checkpoint could not be loaded."
        )

    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    preferences = (
        checkpoint.preferences
        if isinstance(
            checkpoint.preferences,
            Mapping,
        )
        else {}
    )

    before_fingerprint = (
        front_office_state_fingerprint(
            state
        )
    )

    season_label = _clean(
        getattr(
            getattr(
                state,
                "settings",
                None,
            ),
            "season_label",
            "",
        )
    ) or "unknown-season"

    controlled = _controlled_teams(
        preferences
    )
    active_team = _active_trade_team(
        state,
        controlled,
        active_trade_finder_team,
    )

    export_timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    safe_season = (
        season_label
        .replace("/", "-")
        .replace(" ", "_")
    )
    export_id = (
        f"franchise_audit_{safe_season}_{export_timestamp}"
    )

    ledger = build_live_asset_ledger(
        runtime,
        state,
        trade_state,
    )
    league_plan = build_league_front_office_plan(
        state,
        controlled_teams=controlled,
    )

    team_map = _team_player_map(
        state
    )

    team_plan_rows, decision_rows, intent_rows = (
        _front_office_rows(
            league_plan
        )
    )

    datasets: dict[
        str,
        tuple[
            list[dict[str, Any]],
            tuple[str, ...],
        ],
    ] = {}

    datasets["team_state.csv"] = (
        _team_state_rows(state),
        (
            "team",
            "roster_count",
            "roster_player_ids",
        ),
    )

    player_pool_rows = _all_player_pool_rows(
        state,
        ledger,
    )
    active_roster_rows = _active_roster_rows(
        state,
        player_pool_rows,
    )
    free_agent_rows = _free_agent_rows(
        state,
        player_pool_rows,
    )

    # V1.1 corrects the old "team_rosters" ambiguity. It is now a true
    # roster-only export. league_player_pool contains every player.
    datasets["team_rosters.csv"] = (
        active_roster_rows,
        (
            "team",
            "player_id",
            "player_name",
            "position",
            "roster_status",
            "overall",
            "is_free_agent",
        ),
    )
    datasets["active_rosters.csv"] = (
        active_roster_rows,
        (
            "team",
            "player_id",
            "player_name",
            "position",
            "roster_status",
            "overall",
            "is_free_agent",
        ),
    )
    datasets["league_player_pool.csv"] = (
        player_pool_rows,
        (
            "team",
            "player_id",
            "player_name",
            "position",
            "roster_status",
            "overall",
            "is_free_agent",
        ),
    )
    datasets["free_agent_pool.csv"] = (
        free_agent_rows,
        (
            "player_id",
            "player_name",
            "position",
            "roster_status",
            "overall",
            "is_free_agent",
        ),
    )

    datasets["player_market_context.csv"] = (
        _market_context_rows(
            state,
            league_plan,
        ),
        (
            "player_id",
            "player_name",
            "team",
            "age",
            "overall",
            "potential",
            "asset_tier",
            "market_score",
            "organizational_score",
            "trade_value_score",
            "market_percentile",
        ),
    )

    datasets["player_health.csv"] = (
        _medical_profile_rows(
            state,
        ),
        (
            "player_id",
            "team",
            "player_name",
            "position",
            "roster_status",
            "availability_status",
            "injury_type",
            "injury_games_remaining",
            "fatigue",
            "medical_profile_present",
        ),
    )

    datasets["injury_records.csv"] = (
        _injury_record_rows(
            state,
        ),
        (
            "player_id",
            "team",
            "player_name",
            "position",
            "status",
            "injury_type",
            "games_remaining",
            "performance_multiplier",
            "aggravation_risk",
            "notes",
        ),
    )

    datasets["player_contracts.csv"] = (
        _exact_contract_rows(
            state,
        ),
        (
            "player_id",
            "team",
            "player_name",
            "roster_status",
            "status",
            "salary",
            "years_remaining",
            "option_type",
            "guaranteed",
            "contract_source",
        ),
    )

    datasets["standings.csv"] = (
        _standings_export_rows(
            state,
        ),
        (
            "team",
            "conference",
            "division",
            "games_played",
            "wins",
            "losses",
            "win_pct",
            "points_for",
            "points_against",
            "point_diff",
            "streak_type",
            "streak_length",
        ),
    )

    datasets[
        "regular_season_player_stats.csv"
    ] = (
        _regular_player_stat_rows(
            state,
        ),
        (
            "player_id",
            "player_name",
            "team",
            "position",
            "games_played",
            "games_started",
            "minutes_per_game",
            "points_per_game",
            "rebounds_per_game",
            "assists_per_game",
            "steals_per_game",
            "blocks_per_game",
            "turnovers_per_game",
            "fouls_per_game",
            "fg_pct",
            "three_pct",
            "ft_pct",
            "effective_fg_pct",
            "true_shooting_pct",
        ),
    )

    datasets[
        "regular_season_team_stats.csv"
    ] = (
        _regular_team_stat_rows(
            state,
        ),
        (
            "team",
            "conference",
            "games_played",
            "wins",
            "losses",
            "win_pct",
            "points_for_per_game",
            "points_against_per_game",
            "point_diff",
        ),
    )

    (
        playoff_player_rows,
        playoff_team_rows,
    ) = _postseason_rows(
        state,
    )
    datasets["playoff_player_stats.csv"] = (
        playoff_player_rows,
        (
            "Player",
            "Team",
            "Pos",
            "GP",
            "GS",
            "MIN",
            "PTS",
            "REB",
            "AST",
            "STL",
            "BLK",
            "TO",
            "PF",
            "FGM",
            "FGA",
            "FG%",
            "3PM",
            "3PA",
            "3P%",
            "FTM",
            "FTA",
            "FT%",
            "eFG%",
            "TS%",
        ),
    )
    datasets["playoff_team_stats.csv"] = (
        playoff_team_rows,
        (
            "Team",
            "Conf",
            "GP",
            "W",
            "L",
            "Win%",
            "PF",
            "PA",
            "Diff",
            "Furthest Round",
        ),
    )

    datasets["season_history.csv"] = (
        _season_history_rows(
            state,
        ),
        (
            "archive_index",
            "season_label",
            "champion",
            "runner_up",
            "regular_games_completed",
            "postseason_games_completed",
            "conference_champions",
            "transition_engine_version",
            "development_summary",
        ),
    )

    datasets[
        "cpu_front_office_team_plans.csv"
    ] = (
        team_plan_rows,
        (
            "team",
            "cpu_managed",
            "timeline",
            "timeline_label",
            "league_rank",
            "competitive_score",
            "win_pct",
            "average_age",
            "top_five_overall",
            "primary_upgrade_need",
            "depth_surplus_family",
            "financial_posture",
            "trade_goal",
        ),
    )

    datasets[
        "cpu_front_office_player_decisions.csv"
    ] = (
        decision_rows,
        (
            "team",
            "player_id",
            "player_name",
            "position",
            "age",
            "overall",
            "potential",
            "asset_tier",
            "asset_policy",
            "market_stance",
            "contract_plan",
            "decision_priority",
            "market_value_score",
            "trade_value_score",
            "minimum_return_label",
        ),
    )

    datasets[
        "cpu_trade_package_intents.csv"
    ] = (
        intent_rows,
        (
            "team",
            "intent_id",
            "intent_type",
            "priority",
            "outgoing_player_names",
            "outgoing_peak_asset_tier",
            "target_family",
            "return_profile",
            "required_first_equivalent_return",
            "requires_blue_chip_return",
            "minimum_return_label",
            "execution_ready",
        ),
    )

    datasets["draft_rights.csv"] = (
        [
            dict(row)
            for row in ledger.draft_rows
        ],
        (
            "asset_id",
            "current_owner_team",
            "draft_year",
            "round_number",
            "origin_team",
            "display_name",
            "bridge_ready",
            "engine_ready",
        ),
    )

    datasets["transactions.csv"] = (
        _transaction_rows(
            state
        ),
        (
            "transaction_index",
            "transaction_id",
            "timestamp",
            "team_a",
            "team_b",
        ),
    )

    trade_finder_result = None
    if (
        include_trade_finder
        and active_team
    ):
        trade_finder_result = (
            generate_trade_finder_proposals(
                runtime,
                state,
                trade_state,
                active_team=active_team,
                goal=GOAL_BEST_AVAILABLE,
                include_picks=True,
                max_results=8,
                max_partners=trade_finder_max_partners,
                max_targets_per_partner=(
                    trade_finder_max_targets_per_partner
                ),
                max_package_evaluations=(
                    trade_finder_max_package_evaluations
                ),
                max_financial_prechecks=(
                    trade_finder_max_financial_prechecks
                ),
                ledger=ledger,
            )
        )

    if trade_finder_result is None:
        datasets[
            "trade_finder_search_summary.csv"
        ] = (
            [],
            (
                "version",
                "value_model_version",
                "season_label",
                "active_team",
                "proposal_count",
            ),
        )
        datasets[
            "trade_finder_package_audit.csv"
        ] = (
            [],
            (
                "audit_id",
                "route_stage",
                "partner_team",
                "target_player_name",
                "user_value_delta",
                "cpu_value_delta",
            ),
        )
        datasets[
            "trade_finder_actionable_offers.csv"
        ] = (
            [],
            (
                "proposal_id",
                "active_team",
                "partner_team",
                "response_label",
                "target_player_name",
                "user_value_delta",
                "cpu_value_delta",
                "preview_status",
                "preview_can_commit",
            ),
        )
    else:
        datasets[
            "trade_finder_search_summary.csv"
        ] = (
            [
                _trade_finder_summary_row(
                    trade_finder_result
                )
            ],
            (
                "version",
                "value_model_version",
                "season_label",
                "active_team",
                "teams_scanned",
                "candidate_packages_generated",
                "financial_prechecks",
                "packages_evaluated",
                "legal_packages",
                "proposal_count",
                "search_elapsed_seconds",
            ),
        )
        datasets[
            "trade_finder_package_audit.csv"
        ] = (
            [
                dict(row)
                for row in trade_finder_result.package_audit_rows
            ],
            (
                "audit_id",
                "trade_finder_version",
                "value_model_version",
                "route_stage",
                "partner_team",
                "target_player_name",
                "target_shared_asset_tier",
                "target_shared_trade_value",
                "user_value_delta",
                "cpu_value_delta",
                "cpu_accept_floor",
                "financial_status",
                "canonical_precheck_status",
                "anchor_financial_resolution_applied",
                "full_legality_status",
                "can_commit",
            ),
        )
        datasets[
            "trade_finder_actionable_offers.csv"
        ] = (
            _proposal_rows(
                trade_finder_result
            ),
            (
                "proposal_id",
                "active_team",
                "partner_team",
                "cpu_response",
                "response_label",
                "deal_type",
                "target_player_id",
                "target_player_name",
                "user_value_delta",
                "cpu_value_delta",
                "fit_score",
                "ranking_score",
                "preview_status",
                "preview_can_commit",
                "preview_anchor_financial_resolution_applied",
            ),
        )

    after_fingerprint = (
        front_office_state_fingerprint(
            state
        )
    )
    if (
        before_fingerprint
        != after_fingerprint
    ):
        raise RuntimeError(
            "Audit export unexpectedly mutated the live franchise state."
        )

    if _sha256(checkpoint_path) != checkpoint_sha_before:
        raise RuntimeError(
            "Audit export changed the durable franchise checkpoint."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_root = Path(
        tempfile.mkdtemp(
            prefix="franchise_audit_"
        )
    )
    try:
        bundle_dir = (
            temp_root
            / export_id
        )
        bundle_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        row_counts: dict[str, int] = {}
        file_inventory: list[dict[str, Any]] = []

        for filename, (
            rows,
            preferred,
        ) in datasets.items():
            path = bundle_dir / filename
            row_count = _write_csv(
                path,
                rows,
                preferred_columns=preferred,
            )
            row_counts[filename] = row_count
            file_inventory.append(
                {
                    "filename": filename,
                    "row_count": row_count,
                    "sha256": _sha256(
                        path
                    ),
                }
            )

        manifest_rows = [
            {
                "category": "export",
                "key": "audit_export_version",
                "value": AUDIT_EXPORT_VERSION,
            },
            {
                "category": "export",
                "key": "audit_schema_version",
                "value": AUDIT_SCHEMA_VERSION,
            },
            {
                "category": "export",
                "key": "export_id",
                "value": export_id,
            },
            {
                "category": "export",
                "key": "created_utc",
                "value": export_timestamp,
            },
            {
                "category": "state",
                "key": "season_label",
                "value": season_label,
            },
            {
                "category": "state",
                "key": "franchise_trade_revision",
                "value": int(
                    getattr(
                        state,
                        "franchise_trade_revision_v1",
                        0,
                    )
                    or 0
                ),
            },
            {
                "category": "state",
                "key": "checkpoint_sha256",
                "value": checkpoint_sha_before,
            },
            {
                "category": "state",
                "key": "state_fingerprint",
                "value": before_fingerprint,
            },
            {
                "category": "state",
                "key": "controlled_teams",
                "value": controlled,
            },
            {
                "category": "trade_finder",
                "key": "included",
                "value": include_trade_finder,
            },
            {
                "category": "trade_finder",
                "key": "active_team",
                "value": active_team,
            },
            {
                "category": "models",
                "key": "cpu_front_office_version",
                "value": CPU_FRONT_OFFICE_VERSION,
            },
            {
                "category": "models",
                "key": "cpu_front_office_model_version",
                "value": CPU_FRONT_OFFICE_MODEL_VERSION,
            },
            {
                "category": "models",
                "key": "asset_market_context_version",
                "value": ASSET_MARKET_CONTEXT_VERSION,
            },
            {
                "category": "models",
                "key": "asset_market_model_version",
                "value": ASSET_MARKET_MODEL_VERSION,
            },
            {
                "category": "models",
                "key": "trade_finder_version",
                "value": TRADE_FINDER_AI_VERSION,
            },
            {
                "category": "models",
                "key": "trade_finder_value_model_version",
                "value": TRADE_FINDER_VALUE_MODEL_VERSION,
            },
        ]

        for filename, count in sorted(
            row_counts.items()
        ):
            manifest_rows.append(
                {
                    "category": "row_count",
                    "key": filename,
                    "value": count,
                }
            )

        manifest_path = (
            bundle_dir
            / "audit_manifest.csv"
        )
        manifest_count = _write_csv(
            manifest_path,
            manifest_rows,
            preferred_columns=(
                "category",
                "key",
                "value",
            ),
        )
        row_counts[
            "audit_manifest.csv"
        ] = manifest_count
        file_inventory.append(
            {
                "filename": "audit_manifest.csv",
                "row_count": manifest_count,
                "sha256": _sha256(
                    manifest_path
                ),
            }
        )

        inventory_path = (
            bundle_dir
            / "audit_file_inventory.csv"
        )
        inventory_count = _write_csv(
            inventory_path,
            file_inventory,
            preferred_columns=(
                "filename",
                "row_count",
                "sha256",
            ),
        )
        row_counts[
            "audit_file_inventory.csv"
        ] = inventory_count

        readme = (
            bundle_dir
            / "README.txt"
        )
        readme.write_text(
            (
                "FRANCHISE AUDIT EXPORT V1\n\n"
                f"Export ID: {export_id}\n"
                f"Season: {season_label}\n"
                f"Checkpoint SHA256: {checkpoint_sha_before}\n"
                f"State fingerprint: {before_fingerprint}\n"
                f"Trade Finder included: {include_trade_finder}\n"
                f"Trade Finder active team: {active_team}\n\n"
                "This bundle is a read-only snapshot. It does not mutate "
                "the live franchise checkpoint.\n\n"
                "V1.1 separates active rosters from the free-agent pool, "
                "exports the real Medical V2 profile layer, exact simulation "
                "contract state, standings, regular-season player/team stats, "
                "playoff player/team stats when available, season history, "
                "CPU Front Office intelligence, draft rights, transactions, "
                "and the bounded Trade Finder audit.\n"
            ),
            encoding="utf-8",
        )

        zip_path = (
            output_dir
            / f"{export_id}.zip"
        )
        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(
                bundle_dir.rglob("*")
            ):
                if not path.is_file():
                    continue
                archive.write(
                    path,
                    path.relative_to(
                        temp_root
                    ),
                )

        zip_sha = _sha256(
            zip_path
        )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )

    return FranchiseAuditExportResult(
        version=AUDIT_EXPORT_VERSION,
        schema_version=AUDIT_SCHEMA_VERSION,
        export_id=export_id,
        season_label=season_label,
        checkpoint_sha256=checkpoint_sha_before,
        state_fingerprint=before_fingerprint,
        active_trade_finder_team=active_team,
        include_trade_finder=include_trade_finder,
        zip_path=str(zip_path),
        zip_sha256=zip_sha,
        file_count=(
            len(row_counts)
            + 1
        ),
        row_counts=dict(
            row_counts
        ),
    )
