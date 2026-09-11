from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DEFAULT_OUTPUT_ROOT = (
    OUTPUTS / "batch_simulation_audits"
)
CHECKPOINT_PATH = (
    OUTPUTS
    / "runtime"
    / "franchise_mode_checkpoint_v1.pkl.gz"
)

BATCH_AUDIT_VERSION = (
    "franchise-batch-simulation-audit-v2.1-calibration-grade-2026-08-13"
)
BATCH_SCHEMA_VERSION = (
    "franchise-batch-simulation-schema-v2.1-2026-08-13"
)


BENCHMARK_SEASON = "2025-26"
BENCHMARK_SOURCE = (
    "Basketball-Reference NBA League Averages, completed 2025-26 season"
)
BENCHMARK_SOURCE_URL = (
    "https://www.basketball-reference.com/leagues/NBA_stats_per_game.html"
)

# Tolerances are diagnostic calibration bands, not claims that one simulated
# season must exactly equal one historical NBA season.
REGULAR_BENCHMARKS = {
    "reg_pts_per_team_game": {
        "label": "PTS / team game",
        "benchmark": 115.6,
        "tolerance": 1.5,
        "weight": 1.25,
        "category": "scoring",
    },
    "reg_fga_per_team_game": {
        "label": "FGA / team game",
        "benchmark": 89.1,
        "tolerance": 1.5,
        "weight": 1.0,
        "category": "shot_volume",
    },
    "reg_fg_pct": {
        "label": "FG%",
        "benchmark": 47.1,
        "tolerance": 0.7,
        "weight": 1.5,
        "category": "shooting_efficiency",
    },
    "reg_3pa_per_team_game": {
        "label": "3PA / team game",
        "benchmark": 37.0,
        "tolerance": 1.5,
        "weight": 1.0,
        "category": "shot_volume",
    },
    "reg_3p_pct": {
        "label": "3P%",
        "benchmark": 36.0,
        "tolerance": 0.7,
        "weight": 1.25,
        "category": "shooting_efficiency",
    },
    "reg_fta_per_team_game": {
        "label": "FTA / team game",
        "benchmark": 23.5,
        "tolerance": 1.5,
        "weight": 1.25,
        "category": "shot_volume",
    },
    "reg_ft_pct": {
        "label": "FT%",
        "benchmark": 78.3,
        "tolerance": 0.9,
        "weight": 1.0,
        "category": "shooting_efficiency",
    },
    "reg_reb_per_team_game": {
        "label": "REB / team game",
        "benchmark": 43.8,
        "tolerance": 1.5,
        "weight": 0.75,
        "category": "secondary_box_score",
    },
    "reg_ast_per_team_game": {
        "label": "AST / team game",
        "benchmark": 26.7,
        "tolerance": 1.3,
        "weight": 0.9,
        "category": "secondary_box_score",
    },
    "reg_stl_per_team_game": {
        "label": "STL / team game",
        "benchmark": 8.4,
        "tolerance": 0.7,
        "weight": 0.8,
        "category": "secondary_box_score",
    },
    "reg_blk_per_team_game": {
        "label": "BLK / team game",
        "benchmark": 4.8,
        "tolerance": 0.7,
        "weight": 0.6,
        "category": "secondary_box_score",
    },
    "reg_tov_per_team_game": {
        "label": "TOV / team game",
        "benchmark": 14.5,
        "tolerance": 0.9,
        "weight": 0.8,
        "category": "secondary_box_score",
    },
    "reg_pf_per_team_game": {
        "label": "PF / team game",
        "benchmark": 19.9,
        "tolerance": 1.2,
        "weight": 0.6,
        "category": "secondary_box_score",
    },
    "reg_efg_pct": {
        "label": "eFG%",
        "benchmark": 54.6,
        "tolerance": 0.8,
        "weight": 1.5,
        "category": "shooting_efficiency",
    },
    "reg_ts_pct": {
        "label": "TS%",
        "benchmark": 58.1,
        "tolerance": 0.8,
        "weight": 1.5,
        "category": "shooting_efficiency",
    },
}

PLAYOFF_BENCHMARKS = {
    "playoff_pts_per_team_game": {
        "label": "Playoff PTS / team game",
        "benchmark": 107.9,
        "tolerance": 2.5,
        "weight": 1.25,
        "category": "playoff_scoring",
    },
    "playoff_fga_per_team_game": {
        "label": "Playoff FGA / team game",
        "benchmark": 85.1,
        "tolerance": 2.5,
        "weight": 1.0,
        "category": "playoff_shot_volume",
    },
    "playoff_fg_pct": {
        "label": "Playoff FG%",
        "benchmark": 45.2,
        "tolerance": 1.0,
        "weight": 1.4,
        "category": "playoff_efficiency",
    },
    "playoff_3pa_per_team_game": {
        "label": "Playoff 3PA / team game",
        "benchmark": 34.4,
        "tolerance": 2.0,
        "weight": 1.0,
        "category": "playoff_shot_volume",
    },
    "playoff_3p_pct": {
        "label": "Playoff 3P%",
        "benchmark": 34.8,
        "tolerance": 1.0,
        "weight": 1.2,
        "category": "playoff_efficiency",
    },
    "playoff_fta_per_team_game": {
        "label": "Playoff FTA / team game",
        "benchmark": 24.8,
        "tolerance": 2.0,
        "weight": 1.0,
        "category": "playoff_shot_volume",
    },
    "playoff_ft_pct": {
        "label": "Playoff FT%",
        "benchmark": 76.8,
        "tolerance": 1.2,
        "weight": 0.9,
        "category": "playoff_efficiency",
    },
    "playoff_reb_per_team_game": {
        "label": "Playoff REB / team game",
        "benchmark": 42.5,
        "tolerance": 2.0,
        "weight": 0.7,
        "category": "playoff_secondary",
    },
    "playoff_ast_per_team_game": {
        "label": "Playoff AST / team game",
        "benchmark": 23.3,
        "tolerance": 1.8,
        "weight": 0.8,
        "category": "playoff_secondary",
    },
    "playoff_stl_per_team_game": {
        "label": "Playoff STL / team game",
        "benchmark": 8.0,
        "tolerance": 0.9,
        "weight": 0.7,
        "category": "playoff_secondary",
    },
    "playoff_blk_per_team_game": {
        "label": "Playoff BLK / team game",
        "benchmark": 5.1,
        "tolerance": 0.9,
        "weight": 0.6,
        "category": "playoff_secondary",
    },
    "playoff_tov_per_team_game": {
        "label": "Playoff TOV / team game",
        "benchmark": 14.4,
        "tolerance": 1.2,
        "weight": 0.7,
        "category": "playoff_secondary",
    },
    "playoff_pf_per_team_game": {
        "label": "Playoff PF / team game",
        "benchmark": 22.0,
        "tolerance": 1.5,
        "weight": 0.6,
        "category": "playoff_secondary",
    },
    "playoff_efg_pct": {
        "label": "Playoff eFG%",
        "benchmark": 52.2,
        "tolerance": 1.0,
        "weight": 1.4,
        "category": "playoff_efficiency",
    },
    "playoff_ts_pct": {
        "label": "Playoff TS%",
        "benchmark": 56.2,
        "tolerance": 1.0,
        "weight": 1.4,
        "category": "playoff_efficiency",
    },
}

CALIBRATION_AREA_BY_METRIC = {
    "reg_fga_per_team_game": "shot-volume / scoring decomposition",
    "reg_fg_pct": "two-point and three-point miss-rate calibration",
    "reg_3pa_per_team_game": "three-point shot-share calibration",
    "reg_3p_pct": "three-point make/miss calibration",
    "reg_fta_per_team_game": "free-throw scoring allocation",
    "reg_ft_pct": "free-throw miss-rate calibration",
    "reg_reb_per_team_game": "team rebound total generation",
    "reg_ast_per_team_game": "team assist expectation",
    "reg_stl_per_team_game": "team steal expectation",
    "reg_blk_per_team_game": "team block expectation",
    "reg_tov_per_team_game": "team turnover expectation",
    "reg_pf_per_team_game": "team foul expectation",
    "reg_efg_pct": "shot efficiency mix",
    "reg_ts_pct": "overall scoring efficiency mix",
    "playoff_pts_per_team_game": "postseason scoring environment",
    "playoff_fga_per_team_game": "postseason shot volume",
    "playoff_fg_pct": "postseason field-goal efficiency",
    "playoff_3pa_per_team_game": "postseason three-point volume",
    "playoff_3p_pct": "postseason three-point efficiency",
    "playoff_fta_per_team_game": "postseason foul / free-throw volume",
    "playoff_ft_pct": "postseason free-throw efficiency",
    "playoff_reb_per_team_game": "postseason rebound environment",
    "playoff_ast_per_team_game": "postseason assist environment",
    "playoff_stl_per_team_game": "postseason steal environment",
    "playoff_blk_per_team_game": "postseason block environment",
    "playoff_tov_per_team_game": "postseason turnover environment",
    "playoff_pf_per_team_game": "postseason foul environment",
    "playoff_efg_pct": "postseason shot efficiency mix",
    "playoff_ts_pct": "postseason overall efficiency mix",
}

from simulation_franchise_checkpoint_v1 import (
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import (
    GameStatus,
    LeaguePhase,
    validate_simulation_league_state,
)
from regular_season_simulation_controller_v1 import (
    CONTROLLER_VERSION as REGULAR_SEASON_CONTROLLER_VERSION,
    SimulationScope,
    regular_season_state_fingerprint,
    simulate_regular_season_scope,
)
from simulation_postseason_v1 import (
    POSTSEASON_VERSION,
    PostseasonSimulationScope,
    PostseasonStage,
    advance_postseason,
    completed_postseason_games,
    get_postseason_state,
    initialize_postseason,
)
from franchise_command_center_v1 import (
    FranchiseSimulationPolicy,
)
from franchise_audit_export_v1 import (
    AUDIT_EXPORT_VERSION,
    AUDIT_SCHEMA_VERSION,
    _medical_profile_rows,
    _postseason_rows,
    _regular_player_stat_rows,
    _regular_team_stat_rows,
    _standings_export_rows,
)


@dataclass(frozen=True)
class BatchSimulationAuditResult:
    version: str
    schema_version: str
    batch_id: str
    runs: int
    seed_base: int
    season_label: str
    output_directory: str
    zip_path: str
    zip_sha256: str
    checkpoint_sha256: str
    source_state_fingerprint: str
    elapsed_seconds: float
    unique_champions: int
    realism_warning_count: int
    files: tuple[str, ...]


def _sha(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        try:
            return str(value.value)
        except Exception:
            pass
    return str(value).strip()


def _finite(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _mean(values: Iterable[float]) -> float:
    data = [
        float(value)
        for value in values
        if math.isfinite(float(value))
    ]
    return (
        statistics.fmean(data)
        if data
        else 0.0
    )


def _stdev(values: Iterable[float]) -> float:
    data = [
        float(value)
        for value in values
        if math.isfinite(float(value))
    ]
    return (
        statistics.stdev(data)
        if len(data) >= 2
        else 0.0
    )


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return (
            round(value, 6)
            if math.isfinite(value)
            else ""
        )
    if hasattr(value, "value"):
        return _csv_value(value.value)
    if isinstance(value, dict):
        return json.dumps(
            value,
            sort_keys=True,
            default=str,
        )
    if isinstance(
        value,
        (list, tuple, set),
    ):
        return json.dumps(
            list(value),
            default=str,
        )
    return str(value)


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    preferred: tuple[str, ...] = (),
) -> int:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    fields = list(preferred)
    seen = set(fields)
    for row in rows:
        for key in row:
            key = str(key)
            if key not in seen:
                fields.append(key)
                seen.add(key)

    if not fields:
        fields = ["empty"]

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _csv_value(
                        row.get(key, "")
                    )
                    for key in fields
                }
            )
    return len(rows)


def _aggregate_shooting(
    state: Any,
) -> dict[str, float]:
    totals = list(
        (
            getattr(
                state,
                "player_season_totals",
                {},
            )
            or {}
        ).values()
    )
    fgm = sum(
        int(
            getattr(
                row,
                "field_goals_made",
                0,
            )
            or 0
        )
        for row in totals
    )
    fga = sum(
        int(
            getattr(
                row,
                "field_goals_attempted",
                0,
            )
            or 0
        )
        for row in totals
    )
    tpm = sum(
        int(
            getattr(
                row,
                "three_pointers_made",
                0,
            )
            or 0
        )
        for row in totals
    )
    tpa = sum(
        int(
            getattr(
                row,
                "three_pointers_attempted",
                0,
            )
            or 0
        )
        for row in totals
    )
    ftm = sum(
        int(
            getattr(
                row,
                "free_throws_made",
                0,
            )
            or 0
        )
        for row in totals
    )
    fta = sum(
        int(
            getattr(
                row,
                "free_throws_attempted",
                0,
            )
            or 0
        )
        for row in totals
    )
    points = sum(
        int(
            getattr(
                row,
                "points",
                0,
            )
            or 0
        )
        for row in totals
    )
    ts_denom = 2.0 * (
        fga + 0.44 * fta
    )

    def pct(
        made: int,
        attempts: int,
    ) -> float:
        return (
            100.0 * made / attempts
            if attempts
            else 0.0
        )

    return {
        "fg_pct": pct(fgm, fga),
        "three_pct": pct(tpm, tpa),
        "ft_pct": pct(ftm, fta),
        "efg_pct": (
            100.0
            * (fgm + 0.5 * tpm)
            / fga
            if fga
            else 0.0
        ),
        "ts_pct": (
            100.0
            * points
            / ts_denom
            if ts_denom
            else 0.0
        ),
    }



def _box_rate_metrics_from_totals(
    totals: dict[str, float],
    *,
    team_games: int,
    prefix: str,
) -> dict[str, float]:
    divisor = float(team_games) if team_games else 1.0
    points = totals["points"]
    fgm = totals["field_goals_made"]
    fga = totals["field_goals_attempted"]
    tpm = totals["three_pointers_made"]
    tpa = totals["three_pointers_attempted"]
    ftm = totals["free_throws_made"]
    fta = totals["free_throws_attempted"]
    ts_denom = 2.0 * (fga + 0.44 * fta)

    def pct(made: float, attempts: float) -> float:
        return 100.0 * made / attempts if attempts else 0.0

    return {
        f"{prefix}_pts_per_team_game": points / divisor,
        f"{prefix}_fgm_per_team_game": fgm / divisor,
        f"{prefix}_fga_per_team_game": fga / divisor,
        f"{prefix}_fg_pct": pct(fgm, fga),
        f"{prefix}_3pm_per_team_game": tpm / divisor,
        f"{prefix}_3pa_per_team_game": tpa / divisor,
        f"{prefix}_3p_pct": pct(tpm, tpa),
        f"{prefix}_ftm_per_team_game": ftm / divisor,
        f"{prefix}_fta_per_team_game": fta / divisor,
        f"{prefix}_ft_pct": pct(ftm, fta),
        f"{prefix}_reb_per_team_game": totals["rebounds"] / divisor,
        f"{prefix}_ast_per_team_game": totals["assists"] / divisor,
        f"{prefix}_stl_per_team_game": totals["steals"] / divisor,
        f"{prefix}_blk_per_team_game": totals["blocks"] / divisor,
        f"{prefix}_tov_per_team_game": totals["turnovers"] / divisor,
        f"{prefix}_pf_per_team_game": totals["fouls"] / divisor,
        f"{prefix}_efg_pct": (
            100.0 * (fgm + 0.5 * tpm) / fga
            if fga else 0.0
        ),
        f"{prefix}_ts_pct": (
            100.0 * points / ts_denom
            if ts_denom else 0.0
        ),
        f"{prefix}_three_attempt_rate": (
            tpa / fga if fga else 0.0
        ),
        f"{prefix}_free_throw_rate": (
            fta / fga if fga else 0.0
        ),
        f"{prefix}_assist_per_fgm": (
            totals["assists"] / fgm
            if fgm else 0.0
        ),
    }


def _regular_box_rate_metrics(
    state: Any,
) -> dict[str, float]:
    keys = (
        "points",
        "field_goals_made",
        "field_goals_attempted",
        "three_pointers_made",
        "three_pointers_attempted",
        "free_throws_made",
        "free_throws_attempted",
        "rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "fouls",
    )
    totals = {key: 0.0 for key in keys}
    for row in (
        getattr(
            state,
            "player_season_totals",
            {},
        )
        or {}
    ).values():
        for key in keys:
            totals[key] += _finite(
                getattr(row, key, 0)
            )

    regular_games = len(
        getattr(
            state,
            "completed_games",
            {},
        )
        or {}
    )
    return {
        "regular_games": regular_games,
        **_box_rate_metrics_from_totals(
            totals,
            team_games=2 * regular_games,
            prefix="reg",
        ),
    }


def _completed_playoff_pairs(
    state: Any,
) -> list[tuple[Any, Any]]:
    postseason = get_postseason_state(
        state,
        required=True,
    )
    pairs: list[tuple[Any, Any]] = []

    for item in completed_postseason_games(
        state
    ):
        if (
            isinstance(item, tuple)
            and len(item) >= 2
        ):
            game, completed = item[0], item[1]
        else:
            completed = item
            game_id = _clean(
                getattr(
                    completed,
                    "game_id",
                    "",
                )
            )
            game = postseason.games.get(
                game_id
            )

        round_label = _clean(
            getattr(
                game,
                "round_label",
                "",
            )
        ).lower()

        # Basketball-Reference playoff league averages exclude the Play-In.
        if "play-in" in round_label:
            continue

        if completed is not None:
            pairs.append(
                (game, completed)
            )

    return pairs


def _playoff_box_rate_metrics(
    state: Any,
) -> dict[str, float]:
    keys = (
        "points",
        "field_goals_made",
        "field_goals_attempted",
        "three_pointers_made",
        "three_pointers_attempted",
        "free_throws_made",
        "free_throws_attempted",
        "rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "fouls",
    )
    totals = {key: 0.0 for key in keys}
    pairs = _completed_playoff_pairs(
        state
    )

    for _, completed in pairs:
        for line in (
            getattr(
                completed,
                "player_box_scores",
                (),
            )
            or ()
        ):
            for key in keys:
                totals[key] += _finite(
                    getattr(line, key, 0)
                )

    return {
        "playoff_games_excluding_play_in": len(
            pairs
        ),
        **_box_rate_metrics_from_totals(
            totals,
            team_games=2 * len(pairs),
            prefix="playoff",
        ),
    }


def _playoff_player_detail_rows(
    state: Any,
    run: int,
    seed: int,
) -> list[dict[str, Any]]:
    aggregates: dict[
        str,
        dict[str, Any],
    ] = {}

    counting_fields = (
        "minutes",
        "points",
        "rebounds",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "fouls",
        "field_goals_made",
        "field_goals_attempted",
        "three_pointers_made",
        "three_pointers_attempted",
        "free_throws_made",
        "free_throws_attempted",
    )

    for _, completed in _completed_playoff_pairs(
        state
    ):
        for line in (
            getattr(
                completed,
                "player_box_scores",
                (),
            )
            or ()
        ):
            player_id = _clean(
                getattr(
                    line,
                    "player_id",
                    "",
                )
            )
            if not player_id:
                continue

            player = (
                getattr(
                    state,
                    "players",
                    {},
                )
                or {}
            ).get(player_id)

            row = aggregates.setdefault(
                player_id,
                {
                    "run": run,
                    "seed": seed,
                    "player_id": player_id,
                    "player_name": _clean(
                        getattr(
                            player,
                            "player_name",
                            player_id,
                        )
                    ),
                    "team": _clean(
                        getattr(
                            line,
                            "team_abbreviation",
                            getattr(
                                player,
                                "team_abbreviation",
                                "",
                            ),
                        )
                    ),
                    "position": _clean(
                        getattr(
                            player,
                            "position",
                            "",
                        )
                    ),
                    "games_played": 0,
                    "games_started": 0,
                    **{
                        field: 0.0
                        for field
                        in counting_fields
                    },
                },
            )

            row["games_played"] += 1
            if bool(
                getattr(
                    line,
                    "started",
                    getattr(
                        line,
                        "is_starter",
                        False,
                    ),
                )
            ):
                row["games_started"] += 1

            for field in counting_fields:
                row[field] += _finite(
                    getattr(line, field, 0)
                )

    output = []
    for row in aggregates.values():
        gp = max(
            1,
            int(row["games_played"]),
        )
        fgm = row["field_goals_made"]
        fga = row["field_goals_attempted"]
        tpm = row["three_pointers_made"]
        tpa = row["three_pointers_attempted"]
        ftm = row["free_throws_made"]
        fta = row["free_throws_attempted"]
        points = row["points"]
        ts_denom = 2.0 * (
            fga + 0.44 * fta
        )

        row.update(
            {
                "minutes_per_game": (
                    row["minutes"] / gp
                ),
                "points_per_game": (
                    points / gp
                ),
                "rebounds_per_game": (
                    row["rebounds"] / gp
                ),
                "assists_per_game": (
                    row["assists"] / gp
                ),
                "steals_per_game": (
                    row["steals"] / gp
                ),
                "blocks_per_game": (
                    row["blocks"] / gp
                ),
                "turnovers_per_game": (
                    row["turnovers"] / gp
                ),
                "fouls_per_game": (
                    row["fouls"] / gp
                ),
                "fg_pct": (
                    100.0 * fgm / fga
                    if fga else 0.0
                ),
                "three_pct": (
                    100.0 * tpm / tpa
                    if tpa else 0.0
                ),
                "ft_pct": (
                    100.0 * ftm / fta
                    if fta else 0.0
                ),
                "effective_fg_pct": (
                    100.0
                    * (fgm + 0.5 * tpm)
                    / fga
                    if fga else 0.0
                ),
                "true_shooting_pct": (
                    100.0
                    * points
                    / ts_denom
                    if ts_denom
                    else 0.0
                ),
            }
        )
        output.append(row)

    output.sort(
        key=lambda row: (
            -_finite(
                row.get(
                    "points_per_game"
                )
            ),
            row.get(
                "player_name",
                "",
            ),
        )
    )
    return output


def _benchmark_reference_rows() -> list[dict[str, Any]]:
    rows = []
    for scope, specs in (
        ("regular_season", REGULAR_BENCHMARKS),
        ("playoffs", PLAYOFF_BENCHMARKS),
    ):
        for metric, spec in specs.items():
            rows.append(
                {
                    "benchmark_season": BENCHMARK_SEASON,
                    "scope": scope,
                    "metric": metric,
                    "label": spec["label"],
                    "benchmark": spec["benchmark"],
                    "tolerance": spec["tolerance"],
                    "weight": spec["weight"],
                    "category": spec["category"],
                    "source": BENCHMARK_SOURCE,
                    "source_url": BENCHMARK_SOURCE_URL,
                }
            )
    return rows


def _status_for_normalized_error(
    normalized_error: float,
) -> str:
    if normalized_error <= 1.0:
        return "IN_RANGE"
    if normalized_error <= 2.0:
        return "WATCH"
    return "PRIORITY"


def _benchmark_rows(
    summaries: list[dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    *,
    scope: str,
) -> list[dict[str, Any]]:
    rows = []
    for metric, spec in specs.items():
        values = [
            _finite(
                summary.get(metric)
            )
            for summary in summaries
        ]
        simulated_mean = _mean(values)
        benchmark = float(
            spec["benchmark"]
        )
        tolerance = float(
            spec["tolerance"]
        )
        delta = (
            simulated_mean - benchmark
        )
        normalized = (
            abs(delta) / tolerance
            if tolerance
            else 0.0
        )
        rows.append(
            {
                "scope": scope,
                "metric": metric,
                "label": spec["label"],
                "category": spec["category"],
                "simulated_mean": simulated_mean,
                "simulated_stdev": _stdev(values),
                "benchmark": benchmark,
                "delta": delta,
                "absolute_delta": abs(delta),
                "percent_delta": (
                    100.0 * delta / benchmark
                    if benchmark
                    else 0.0
                ),
                "tolerance": tolerance,
                "normalized_error": normalized,
                "weight": spec["weight"],
                "weighted_error": (
                    normalized
                    * float(spec["weight"])
                ),
                "direction": (
                    "HIGH"
                    if delta > 0
                    else "LOW"
                    if delta < 0
                    else "EVEN"
                ),
                "status": (
                    _status_for_normalized_error(
                        normalized
                    )
                ),
                "calibration_area": (
                    CALIBRATION_AREA_BY_METRIC.get(
                        metric,
                        "",
                    )
                ),
                "benchmark_season": BENCHMARK_SEASON,
                "source": BENCHMARK_SOURCE,
            }
        )

    rows.sort(
        key=lambda row: (
            -row["weighted_error"],
            row["metric"],
        )
    )
    return rows


def _run_benchmark_delta_rows(
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for summary in summaries:
        for scope, specs in (
            ("regular_season", REGULAR_BENCHMARKS),
            ("playoffs", PLAYOFF_BENCHMARKS),
        ):
            for metric, spec in specs.items():
                value = _finite(
                    summary.get(metric)
                )
                benchmark = float(
                    spec["benchmark"]
                )
                tolerance = float(
                    spec["tolerance"]
                )
                delta = value - benchmark
                normalized = (
                    abs(delta) / tolerance
                    if tolerance
                    else 0.0
                )
                output.append(
                    {
                        "run": summary["run"],
                        "seed": summary["seed"],
                        "scope": scope,
                        "metric": metric,
                        "label": spec["label"],
                        "value": value,
                        "benchmark": benchmark,
                        "delta": delta,
                        "tolerance": tolerance,
                        "normalized_error": normalized,
                        "status": (
                            _status_for_normalized_error(
                                normalized
                            )
                        ),
                    }
                )
    return output


def _calibration_priority_rows(
    regular_rows: list[dict[str, Any]],
    playoff_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in (
            *regular_rows,
            *playoff_rows,
        )
        if row["status"] != "IN_RANGE"
    ]
    rows.sort(
        key=lambda row: (
            0
            if row["status"] == "PRIORITY"
            else 1,
            -row["weighted_error"],
            row["metric"],
        )
    )
    for index, row in enumerate(
        rows,
        start=1,
    ):
        row["priority_rank"] = index
    return rows


def _medical_summary_row(
    state: Any,
    run: int,
    seed: int,
) -> dict[str, Any]:
    profiles = list(
        (
            getattr(
                state,
                "injury_fatigue_profiles",
                {},
            )
            or {}
        ).values()
    )
    games_missed = [
        max(
            0.0,
            _finite(
                getattr(
                    profile,
                    "season_games_missed",
                    getattr(
                        profile,
                        "games_missed",
                        0,
                    ),
                )
            ),
        )
        for profile in profiles
    ]
    injury_events = [
        max(
            0.0,
            _finite(
                getattr(
                    profile,
                    "injuries_suffered",
                    0,
                )
            ),
        )
        for profile in profiles
    ]
    fatigue = sorted(
        _finite(
            getattr(
                profile,
                "fatigue",
                0,
            )
        )
        for profile in profiles
    )
    p90_index = (
        max(
            0,
            math.ceil(
                0.90 * len(fatigue)
            )
            - 1,
        )
        if fatigue
        else 0
    )

    return {
        "run": run,
        "seed": seed,
        "profile_count": len(profiles),
        "season_games_missed_total": sum(
            games_missed
        ),
        "players_with_games_missed": sum(
            value > 0
            for value in games_missed
        ),
        "max_player_games_missed": max(
            games_missed,
            default=0.0,
        ),
        "injury_events_total": sum(
            injury_events
        ),
        "players_injured": sum(
            value > 0
            for value in injury_events
        ),
        "players_with_multiple_injuries": sum(
            value >= 2
            for value in injury_events
        ),
        "average_fatigue": _mean(
            fatigue
        ),
        "p90_fatigue": (
            fatigue[p90_index]
            if fatigue
            else 0.0
        ),
    }


def _player_distribution_row(
    regular_player_rows: list[dict[str, Any]],
    run: int,
    seed: int,
) -> dict[str, Any]:
    qualified = sorted(
        (
            _finite(
                row.get(
                    "points_per_game"
                )
            )
            for row in regular_player_rows
            if _finite(
                row.get(
                    "games_played"
                )
            )
            >= 41
        )
    )

    def percentile(
        data: list[float],
        p: float,
    ) -> float:
        if not data:
            return 0.0
        index = max(
            0,
            min(
                len(data) - 1,
                math.ceil(
                    p * len(data)
                )
                - 1,
            ),
        )
        return data[index]

    return {
        "run": run,
        "seed": seed,
        "qualified_players": len(
            qualified
        ),
        "ppg_p50": percentile(
            qualified,
            0.50,
        ),
        "ppg_p90": percentile(
            qualified,
            0.90,
        ),
        "ppg_p95": percentile(
            qualified,
            0.95,
        ),
        "ppg_p99": percentile(
            qualified,
            0.99,
        ),
        "ppg_max": max(
            qualified,
            default=0.0,
        ),
        "players_20_plus_ppg": sum(
            value >= 20.0
            for value in qualified
        ),
        "players_25_plus_ppg": sum(
            value >= 25.0
            for value in qualified
        ),
        "players_30_plus_ppg": sum(
            value >= 30.0
            for value in qualified
        ),
    }



def _game_metrics(
    state: Any,
) -> dict[str, float]:
    games = list(
        (
            getattr(
                state,
                "completed_games",
                {},
            )
            or {}
        ).values()
    )
    if not games:
        return {
            "regular_games": 0,
            "avg_game_total": 0.0,
            "avg_margin": 0.0,
            "home_win_pct": 0.0,
            "overtime_rate": 0.0,
        }

    totals = [
        int(game.home_score)
        + int(game.away_score)
        for game in games
    ]
    margins = [
        abs(
            int(game.home_score)
            - int(game.away_score)
        )
        for game in games
    ]
    home_wins = sum(
        int(game.home_score)
        > int(game.away_score)
        for game in games
    )
    overtime = sum(
        int(
            getattr(
                game,
                "overtime_periods",
                0,
            )
            or 0
        )
        > 0
        for game in games
    )
    return {
        "regular_games": len(games),
        "avg_game_total": _mean(totals),
        "avg_margin": _mean(margins),
        "home_win_pct": (
            home_wins / len(games)
        ),
        "overtime_rate": (
            overtime / len(games)
        ),
    }


def _injury_metrics(
    state: Any,
) -> dict[str, float]:
    injuries = (
        getattr(
            state,
            "injuries",
            {},
        )
        or {}
    )
    profiles = (
        getattr(
            state,
            "injury_fatigue_profiles",
            {},
        )
        or {}
    )

    nonhealthy = 0
    out = 0
    for injury in injuries.values():
        status = _clean(
            getattr(
                injury,
                "status",
                "",
            )
        ).lower()
        if status and status != "healthy":
            nonhealthy += 1
        if status == "out":
            out += 1

    games_missed = [
        max(
            0.0,
            _finite(
                getattr(
                    profile,
                    "season_games_missed",
                    getattr(
                        profile,
                        "games_missed",
                        0,
                    ),
                )
            ),
        )
        for profile in profiles.values()
    ]
    injury_events = [
        max(
            0.0,
            _finite(
                getattr(
                    profile,
                    "injuries_suffered",
                    0,
                )
            ),
        )
        for profile in profiles.values()
    ]
    fatigue = [
        _finite(
            getattr(
                profile,
                "fatigue",
                0,
            )
        )
        for profile in profiles.values()
    ]

    return {
        "end_nonhealthy_players": nonhealthy,
        "end_out_players": out,
        "medical_games_missed_total": sum(
            games_missed
        ),
        "medical_injury_events_total": sum(
            injury_events
        ),
        "medical_players_injured": sum(
            value > 0
            for value in injury_events
        ),
        "medical_players_multiple_injuries": sum(
            value >= 2
            for value in injury_events
        ),
        "medical_max_player_games_missed": max(
            games_missed,
            default=0.0,
        ),
        "medical_recurrence_total": sum(
            max(
                0.0,
                _finite(
                    getattr(
                        profile,
                        "recurrence_count",
                        0,
                    )
                ),
            )
            for profile in profiles.values()
        ),
        "medical_setback_total": sum(
            max(
                0.0,
                _finite(
                    getattr(
                        profile,
                        "setback_count",
                        0,
                    )
                ),
            )
            for profile in profiles.values()
        ),
        "end_average_fatigue": _mean(
            fatigue
        ),
    }


def _qualified_player_extremes(
    player_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    qualified = [
        row
        for row in player_rows
        if int(
            _finite(
                row.get("games_played"),
                0,
            )
        )
        >= 41
    ]
    shooters = [
        row
        for row in qualified
        if _finite(
            row.get(
                "three_pointers_attempted"
            ),
            0,
        )
        >= 100
    ]
    fg_qualified = [
        row
        for row in qualified
        if _finite(
            row.get(
                "field_goals_attempted"
            ),
            0,
        )
        >= 300
    ]

    top_ppg = max(
        qualified,
        key=lambda row: _finite(
            row.get("points_per_game")
        ),
        default={},
    )
    top_three = max(
        shooters,
        key=lambda row: _finite(
            row.get("three_pct")
        ),
        default={},
    )
    top_fg = max(
        fg_qualified,
        key=lambda row: _finite(
            row.get("fg_pct")
        ),
        default={},
    )
    return {
        "qualified_player_count": len(
            qualified
        ),
        "top_ppg_player": top_ppg.get(
            "player_name",
            "",
        ),
        "top_ppg": _finite(
            top_ppg.get("points_per_game")
        ),
        "top_3p_player": top_three.get(
            "player_name",
            "",
        ),
        "top_qualified_3p_pct": _finite(
            top_three.get("three_pct")
        ),
        "top_fg_player": top_fg.get(
            "player_name",
            "",
        ),
        "top_qualified_fg_pct": _finite(
            top_fg.get("fg_pct")
        ),
    }


def _run_realism_flags(
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    specs = (
        (
            "max_team_wins",
            summary["max_team_wins"],
            42.0,
            76.0,
            "Best regular-season record",
        ),
        (
            "min_team_wins",
            summary["min_team_wins"],
            4.0,
            42.0,
            "Worst regular-season record",
        ),
        (
            "top_qualified_ppg",
            summary["top_ppg"],
            22.0,
            42.0,
            "Qualified scoring leader",
        ),
        (
            "postseason_games_total",
            summary["postseason_games"],
            66.0,
            111.0,
            "Play-In + playoffs game count",
        ),
        (
            "playoff_games_excluding_play_in",
            summary[
                "playoff_games_excluding_play_in"
            ],
            60.0,
            105.0,
            "Best-of-seven playoff game count",
        ),
    )

    rows = []
    for (
        metric,
        value,
        lower,
        upper,
        description,
    ) in specs:
        passed = (
            lower
            <= float(value)
            <= upper
        )
        rows.append(
            {
                "scope": "structural",
                "run": summary["run"],
                "seed": summary["seed"],
                "metric": metric,
                "description": description,
                "value": value,
                "lower_bound": lower,
                "upper_bound": upper,
                "status": (
                    "PASS"
                    if passed
                    else "REVIEW"
                ),
            }
        )
    return rows


def _team_rows_for_run(
    state: Any,
    run: int,
    seed: int,
    playoff_rows: list[dict[str, Any]],
    champion: str,
    runner_up: str,
) -> list[dict[str, Any]]:
    playoff_map = {
        _clean(
            row.get(
                "Team",
                row.get("team", ""),
            )
        ).upper(): row
        for row in playoff_rows
    }

    rows = []
    for standing in _standings_export_rows(
        state
    ):
        team = _clean(
            standing.get("team")
        ).upper()
        playoff = playoff_map.get(
            team,
            {},
        )
        row = {
            "run": run,
            "seed": seed,
            **standing,
            "made_postseason": bool(
                playoff
            ),
            "postseason_games": _finite(
                playoff.get(
                    "GP",
                    playoff.get(
                        "games_played",
                        0,
                    ),
                )
            ),
            "furthest_round": _clean(
                playoff.get(
                    "Furthest Round",
                    playoff.get(
                        "furthest_round",
                        "",
                    ),
                )
            ),
            "champion": (
                team == champion
            ),
            "runner_up": (
                team == runner_up
            ),
        }
        rows.append(row)
    return rows


def _player_rows_for_run(
    state: Any,
    run: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows = []
    for row in _regular_player_stat_rows(
        state
    ):
        if int(
            _finite(
                row.get("games_played"),
                0,
            )
        ) <= 0:
            continue
        rows.append(
            {
                "run": run,
                "seed": seed,
                **row,
            }
        )
    return rows


def _playoff_player_rows_for_run(
    state: Any,
    run: int,
    seed: int,
) -> list[dict[str, Any]]:
    return _playoff_player_detail_rows(
        state,
        run,
        seed,
    )


def _medical_rows_for_run(
    state: Any,
    run: int,
    seed: int,
) -> list[dict[str, Any]]:
    return [
        {
            "run": run,
            "seed": seed,
            **row,
        }
        for row in _medical_profile_rows(
            state
        )
    ]


def _aggregate_team_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)
    for row in rows:
        grouped[
            _clean(row.get("team")).upper()
        ].append(row)

    result = []
    for team, group in sorted(
        grouped.items()
    ):
        wins = [
            _finite(row.get("wins"))
            for row in group
        ]
        ppg = [
            _finite(
                row.get(
                    "points_for_per_game"
                )
            )
            for row in group
        ]
        result.append(
            {
                "team": team,
                "runs": len(group),
                "average_wins": _mean(
                    wins
                ),
                "win_stdev": _stdev(
                    wins
                ),
                "minimum_wins": min(
                    wins,
                    default=0,
                ),
                "maximum_wins": max(
                    wins,
                    default=0,
                ),
                "average_ppg": _mean(
                    ppg
                ),
                "postseason_appearances": sum(
                    bool(
                        row.get(
                            "made_postseason"
                        )
                    )
                    for row in group
                ),
                "finals_appearances": sum(
                    bool(
                        row.get(
                            "champion"
                        )
                        or row.get(
                            "runner_up"
                        )
                    )
                    for row in group
                ),
                "titles": sum(
                    bool(
                        row.get(
                            "champion"
                        )
                    )
                    for row in group
                ),
            }
        )
    return result


def _aggregate_player_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)
    for row in rows:
        player_id = _clean(
            row.get("player_id")
        )
        if player_id:
            grouped[player_id].append(
                row
            )

    result = []
    for player_id, group in grouped.items():
        result.append(
            {
                "player_id": player_id,
                "player_name": _clean(
                    group[0].get(
                        "player_name"
                    )
                ),
                "team": _clean(
                    group[0].get(
                        "team"
                    )
                ),
                "position": _clean(
                    group[0].get(
                        "position"
                    )
                ),
                "runs_played": len(group),
                "average_gp": _mean(
                    _finite(
                        row.get(
                            "games_played"
                        )
                    )
                    for row in group
                ),
                "average_ppg": _mean(
                    _finite(
                        row.get(
                            "points_per_game"
                        )
                    )
                    for row in group
                ),
                "ppg_stdev": _stdev(
                    _finite(
                        row.get(
                            "points_per_game"
                        )
                    )
                    for row in group
                ),
                "maximum_ppg": max(
                    (
                        _finite(
                            row.get(
                                "points_per_game"
                            )
                        )
                        for row in group
                    ),
                    default=0.0,
                ),
                "average_rpg": _mean(
                    _finite(
                        row.get(
                            "rebounds_per_game"
                        )
                    )
                    for row in group
                ),
                "average_apg": _mean(
                    _finite(
                        row.get(
                            "assists_per_game"
                        )
                    )
                    for row in group
                ),
                "average_fg_pct": _mean(
                    _finite(
                        row.get(
                            "fg_pct"
                        )
                    )
                    for row in group
                    if _finite(
                        row.get(
                            "field_goals_attempted"
                        )
                    )
                    > 0
                ),
                "average_3p_pct": _mean(
                    _finite(
                        row.get(
                            "three_pct"
                        )
                    )
                    for row in group
                    if _finite(
                        row.get(
                            "three_pointers_attempted"
                        )
                    )
                    > 0
                ),
                "average_ft_pct": _mean(
                    _finite(
                        row.get(
                            "ft_pct"
                        )
                    )
                    for row in group
                    if _finite(
                        row.get(
                            "free_throws_attempted"
                        )
                    )
                    > 0
                ),
                "average_ts_pct": _mean(
                    _finite(
                        row.get(
                            "true_shooting_pct"
                        )
                    )
                    for row in group
                    if _finite(
                        row.get(
                            "field_goals_attempted"
                        )
                    )
                    > 0
                ),
            }
        )

    result.sort(
        key=lambda row: (
            -row["average_ppg"],
            row["player_name"],
        )
    )
    return result


def _champion_summary(
    summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    count = Counter(
        _clean(row.get("champion"))
        for row in summaries
        if _clean(row.get("champion"))
    )
    total = len(summaries)
    return [
        {
            "team": team,
            "titles": titles,
            "title_share": (
                titles / total
                if total
                else 0.0
            ),
        }
        for team, titles in sorted(
            count.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    ]


def _cross_run_flags(
    summaries: list[dict[str, Any]],
    team_aggregate: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    runs = len(summaries)
    champions = Counter(
        _clean(row.get("champion"))
        for row in summaries
        if _clean(row.get("champion"))
    )
    unique = len(champions)
    largest_share = (
        max(champions.values())
        / runs
        if champions and runs
        else 0.0
    )

    rows = [
        {
            "scope": "cross_run",
            "metric": "unique_champions",
            "value": unique,
            "status": (
                "PASS"
                if (
                    runs < 5
                    or unique >= 3
                )
                else "REVIEW"
            ),
            "detail": (
                "With 5+ runs, three or more "
                "different champions is a useful "
                "first diversity check."
            ),
        },
        {
            "scope": "cross_run",
            "metric": "largest_title_share",
            "value": largest_share,
            "status": (
                "PASS"
                if (
                    runs < 5
                    or largest_share <= 0.60
                )
                else "REVIEW"
            ),
            "detail": (
                "A single team winning more than "
                "60% of a 5+ run batch deserves "
                "power-balance review."
            ),
        },
    ]

    for row in team_aggregate:
        avg_wins = _finite(
            row.get("average_wins")
        )
        if avg_wins > 65.0:
            rows.append(
                {
                    "scope": "team",
                    "metric": (
                        "systematic_overpower"
                    ),
                    "team": row["team"],
                    "value": avg_wins,
                    "status": "REVIEW",
                    "detail": (
                        "Average wins above 65 "
                        "across the batch."
                    ),
                }
            )
        if avg_wins < 15.0:
            rows.append(
                {
                    "scope": "team",
                    "metric": (
                        "systematic_underpower"
                    ),
                    "team": row["team"],
                    "value": avg_wins,
                    "status": "REVIEW",
                    "detail": (
                        "Average wins below 15 "
                        "across the batch."
                    ),
                }
            )
    return rows


def _prepare_source_state() -> tuple[
    Any,
    str,
    str,
]:
    if not CHECKPOINT_PATH.is_file():
        raise RuntimeError(
            "Durable franchise checkpoint is missing."
        )
    checkpoint_sha = _sha(
        CHECKPOINT_PATH
    )
    checkpoint = (
        load_franchise_checkpoint()
    )
    if checkpoint is None:
        raise RuntimeError(
            "Durable franchise checkpoint "
            "could not be loaded."
        )

    source = checkpoint.simulation_state
    validate_simulation_league_state(
        source
    )
    season = _clean(
        source.settings.season_label
    )
    completed = len(
        getattr(
            source,
            "completed_games",
            {},
        )
        or {}
    )
    scheduled = len(
        getattr(
            source,
            "schedule",
            {},
        )
        or {}
    )
    if completed:
        raise RuntimeError(
            "Batch Simulation Audit V2 requires "
            "a clean season-start checkpoint with "
            "zero completed regular-season games. "
            f"Found {completed}."
        )
    if scheduled != 1230:
        raise RuntimeError(
            "Batch Simulation Audit V2 expects "
            "the installed 1,230-game schedule. "
            f"Found {scheduled}."
        )
    if source.phase not in {
        LeaguePhase.PRESEASON,
        LeaguePhase.REGULAR_SEASON,
    }:
        raise RuntimeError(
            "Batch Simulation Audit V2 requires "
            "a preseason or regular-season start. "
            f"Found {source.phase!r}."
        )

    return (
        source,
        checkpoint_sha,
        regular_season_state_fingerprint(
            source
        ),
    )


def run_batch_simulation_audit(
    *,
    runs: int = 10,
    seed_base: int = 2026081300,
    output_root: Path | None = None,
    write_zip: bool = True,
    quiet: bool = False,
) -> BatchSimulationAuditResult:
    if runs < 1:
        raise ValueError(
            "runs must be at least 1."
        )
    if runs > 100:
        raise ValueError(
            "V2 intentionally caps one batch "
            "at 100 seasons."
        )

    start = time.perf_counter()
    source, checkpoint_sha, source_fp = (
        _prepare_source_state()
    )
    source_copy_fp = (
        regular_season_state_fingerprint(
            source
        )
    )
    season_label = _clean(
        source.settings.season_label
    )

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    batch_id = (
        f"batch_{season_label}_"
        f"{runs}runs_{stamp}"
    )
    root = (
        Path(output_root)
        if output_root is not None
        else DEFAULT_OUTPUT_ROOT
    )
    batch_dir = root / batch_id
    batch_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    run_summaries: list[
        dict[str, Any]
    ] = []
    team_rows: list[
        dict[str, Any]
    ] = []
    player_rows: list[
        dict[str, Any]
    ] = []
    playoff_player_rows: list[
        dict[str, Any]
    ] = []
    medical_rows: list[
        dict[str, Any]
    ] = []
    medical_summary_rows: list[
        dict[str, Any]
    ] = []
    player_distribution_rows: list[
        dict[str, Any]
    ] = []
    realism_flags: list[
        dict[str, Any]
    ] = []

    for run_index in range(1, runs + 1):
        seed = int(seed_base) + run_index - 1
        run_start = time.perf_counter()

        trial = copy.deepcopy(source)
        trial.settings = replace(
            trial.settings,
            random_seed=seed,
        )
        validate_simulation_league_state(
            trial
        )

        regular_start = time.perf_counter()
        trial, regular_result = (
            simulate_regular_season_scope(
                trial,
                scope=(
                    SimulationScope.REMAINDER
                ),
            )
        )
        regular_seconds = (
            time.perf_counter()
            - regular_start
        )

        if not (
            regular_result.regular_season_complete
        ):
            raise RuntimeError(
                f"Run {run_index} did not "
                "complete the regular season."
            )

        initialize_postseason(
            trial
        )
        postseason_start = (
            time.perf_counter()
        )
        trial, postseason_result = (
            advance_postseason(
                trial,
                scope=(
                    PostseasonSimulationScope
                    .TO_CHAMPION
                ),
                controlled_teams=(),
                policy=(
                    FranchiseSimulationPolicy
                    .FREE_SIMULATION
                ),
                max_games=140,
            )
        )
        postseason_seconds = (
            time.perf_counter()
            - postseason_start
        )

        validate_simulation_league_state(
            trial
        )
        postseason_state = (
            get_postseason_state(
                trial,
                required=True,
            )
        )
        if (
            postseason_state.stage
            != PostseasonStage.COMPLETE
        ):
            raise RuntimeError(
                f"Run {run_index} postseason "
                "did not reach COMPLETE."
            )

        champion = _clean(
            postseason_state.champion
        ).upper()
        runner_up = _clean(
            postseason_state.runner_up
        ).upper()

        standing_rows = (
            _standings_export_rows(
                trial
            )
        )
        regular_player_rows = (
            _regular_player_stat_rows(
                trial
            )
        )
        (
            _display_playoff_player_rows,
            current_playoff_team_rows,
        ) = _postseason_rows(
            trial
        )
        current_playoff_player_rows = (
            _playoff_player_detail_rows(
                trial,
                run_index,
                seed,
            )
        )
        regular_box = (
            _regular_box_rate_metrics(
                trial
            )
        )
        playoff_box = (
            _playoff_box_rate_metrics(
                trial
            )
        )

        standings_by_team = {
            _clean(
                row.get("team")
            ).upper(): row
            for row in standing_rows
        }
        wins = [
            _finite(row.get("wins"))
            for row in standing_rows
        ]
        team_ppg = [
            _finite(
                row.get(
                    "points_for_per_game"
                )
            )
            for row in standing_rows
        ]
        shooting = _aggregate_shooting(
            trial
        )
        games = _game_metrics(
            trial
        )
        injuries = _injury_metrics(
            trial
        )
        extremes = (
            _qualified_player_extremes(
                regular_player_rows
            )
        )
        postseason_games = len(
            getattr(
                postseason_state,
                "completed_games",
                {},
            )
            or {}
        )

        summary = {
            "run": run_index,
            "seed": seed,
            "season_label": season_label,
            "champion": champion,
            "runner_up": runner_up,
            "champion_regular_wins": (
                standings_by_team.get(
                    champion,
                    {},
                ).get("wins", 0)
            ),
            "runner_up_regular_wins": (
                standings_by_team.get(
                    runner_up,
                    {},
                ).get("wins", 0)
            ),
            "max_team_wins": max(
                wins,
                default=0,
            ),
            "min_team_wins": min(
                wins,
                default=0,
            ),
            "team_win_stdev": _stdev(
                wins
            ),
            "league_team_ppg": _mean(
                team_ppg
            ),
            "aggregate_fg_pct": (
                shooting["fg_pct"]
            ),
            "aggregate_3p_pct": (
                shooting["three_pct"]
            ),
            "aggregate_ft_pct": (
                shooting["ft_pct"]
            ),
            "aggregate_efg_pct": (
                shooting["efg_pct"]
            ),
            "aggregate_ts_pct": (
                shooting["ts_pct"]
            ),
            **regular_box,
            **playoff_box,
            **games,
            "postseason_games": (
                postseason_games
            ),
            **injuries,
            **extremes,
            "regular_season_seconds": (
                regular_seconds
            ),
            "postseason_seconds": (
                postseason_seconds
            ),
            "total_run_seconds": (
                time.perf_counter()
                - run_start
            ),
        }

        run_summaries.append(summary)
        realism_flags.extend(
            _run_realism_flags(summary)
        )
        team_rows.extend(
            _team_rows_for_run(
                trial,
                run_index,
                seed,
                current_playoff_team_rows,
                champion,
                runner_up,
            )
        )
        player_rows.extend(
            _player_rows_for_run(
                trial,
                run_index,
                seed,
            )
        )
        playoff_player_rows.extend(
            current_playoff_player_rows
        )
        medical_summary_rows.append(
            _medical_summary_row(
                trial,
                run_index,
                seed,
            )
        )
        player_distribution_rows.append(
            _player_distribution_row(
                regular_player_rows,
                run_index,
                seed,
            )
        )
        medical_rows.extend(
            _medical_rows_for_run(
                trial,
                run_index,
                seed,
            )
        )

        if not quiet:
            print(
                f"[{run_index:>3}/{runs}] "
                f"seed={seed} "
                f"champion={champion} "
                f"{summary['max_team_wins']:.0f}-"
                f"{summary['min_team_wins']:.0f} "
                f"PPG={summary['reg_pts_per_team_game']:.2f} "
                f"FG={summary['reg_fg_pct']:.2f}% "
                f"3P={summary['reg_3p_pct']:.2f}% "
                f"FT={summary['reg_ft_pct']:.2f}% "
                f"FTA={summary['reg_fta_per_team_game']:.1f} "
                f"{summary['total_run_seconds']:.2f}s",
                flush=True,
            )

        # Prove each trial was isolated from the source object.
        if (
            regular_season_state_fingerprint(
                source
            )
            != source_copy_fp
        ):
            raise RuntimeError(
                "A batch trial mutated the "
                "source franchise state in memory."
            )

    team_aggregate = (
        _aggregate_team_rows(team_rows)
    )
    player_aggregate = (
        _aggregate_player_rows(
            player_rows
        )
    )
    champion_rows = (
        _champion_summary(
            run_summaries
        )
    )
    regular_benchmark_rows = (
        _benchmark_rows(
            run_summaries,
            REGULAR_BENCHMARKS,
            scope="regular_season",
        )
    )
    playoff_benchmark_rows = (
        _benchmark_rows(
            run_summaries,
            PLAYOFF_BENCHMARKS,
            scope="playoffs",
        )
    )
    run_benchmark_delta_rows = (
        _run_benchmark_delta_rows(
            run_summaries
        )
    )
    calibration_priority_rows = (
        _calibration_priority_rows(
            regular_benchmark_rows,
            playoff_benchmark_rows,
        )
    )
    cross_run_flags = _cross_run_flags(
        run_summaries,
        team_aggregate,
    )

    all_flag_rows = [
        *realism_flags,
        *cross_run_flags,
    ]
    warning_count = (
        sum(
            _clean(
                row.get("status")
            ).upper()
            == "REVIEW"
            for row in all_flag_rows
        )
        + len(
            calibration_priority_rows
        )
    )

    manifest_rows = [
        {
            "key": "batch_audit_version",
            "value": BATCH_AUDIT_VERSION,
        },
        {
            "key": "batch_schema_version",
            "value": BATCH_SCHEMA_VERSION,
        },
        {
            "key": "audit_export_version",
            "value": AUDIT_EXPORT_VERSION,
        },
        {
            "key": "audit_schema_version",
            "value": AUDIT_SCHEMA_VERSION,
        },
        {
            "key": "regular_season_controller_version",
            "value": (
                REGULAR_SEASON_CONTROLLER_VERSION
            ),
        },
        {
            "key": "postseason_version",
            "value": POSTSEASON_VERSION,
        },
        {
            "key": "batch_id",
            "value": batch_id,
        },
        {
            "key": "season_label",
            "value": season_label,
        },
        {
            "key": "runs",
            "value": runs,
        },
        {
            "key": "seed_base",
            "value": seed_base,
        },
        {
            "key": "checkpoint_sha256",
            "value": checkpoint_sha,
        },
        {
            "key": "source_state_fingerprint",
            "value": source_fp,
        },
        {
            "key": "unique_champions",
            "value": len(
                {
                    row["champion"]
                    for row in run_summaries
                }
            ),
        },
        {
            "key": "realism_warning_count",
            "value": warning_count,
        },
        {
            "key": "benchmark_season",
            "value": BENCHMARK_SEASON,
        },
        {
            "key": "benchmark_source",
            "value": BENCHMARK_SOURCE,
        },
        {
            "key": "benchmark_source_url",
            "value": BENCHMARK_SOURCE_URL,
        },
        {
            "key": "calibration_priority_count",
            "value": len(
                calibration_priority_rows
            ),
        },
    ]

    file_specs = {
        "batch_manifest.csv": (
            manifest_rows,
            ("key", "value"),
        ),
        "batch_run_summary.csv": (
            run_summaries,
            (
                "run",
                "seed",
                "champion",
                "runner_up",
                "champion_regular_wins",
                "max_team_wins",
                "min_team_wins",
                "league_team_ppg",
                "aggregate_fg_pct",
                "aggregate_3p_pct",
                "aggregate_ft_pct",
                "aggregate_ts_pct",
                "reg_fga_per_team_game",
                "reg_3pa_per_team_game",
                "reg_fta_per_team_game",
                "reg_reb_per_team_game",
                "reg_ast_per_team_game",
                "reg_stl_per_team_game",
                "reg_blk_per_team_game",
                "reg_tov_per_team_game",
                "reg_pf_per_team_game",
                "playoff_games_excluding_play_in",
                "playoff_pts_per_team_game",
                "playoff_fga_per_team_game",
                "playoff_fg_pct",
                "playoff_3pa_per_team_game",
                "playoff_3p_pct",
                "playoff_fta_per_team_game",
                "playoff_ft_pct",
                "playoff_efg_pct",
                "playoff_ts_pct",
                "avg_game_total",
                "avg_margin",
                "home_win_pct",
                "overtime_rate",
                "postseason_games",
                "top_ppg_player",
                "top_ppg",
                "top_3p_player",
                "top_qualified_3p_pct",
                "medical_games_missed_total",
                "end_nonhealthy_players",
                "end_average_fatigue",
                "regular_season_seconds",
                "postseason_seconds",
                "total_run_seconds",
            ),
        ),
        "batch_team_seasons.csv": (
            team_rows,
            (
                "run",
                "seed",
                "team",
                "conference",
                "games_played",
                "wins",
                "losses",
                "win_pct",
                "points_for_per_game",
                "points_against_per_game",
                "point_diff",
                "made_postseason",
                "furthest_round",
                "champion",
                "runner_up",
            ),
        ),
        "batch_team_aggregate.csv": (
            team_aggregate,
            (
                "team",
                "runs",
                "average_wins",
                "win_stdev",
                "minimum_wins",
                "maximum_wins",
                "average_ppg",
                "postseason_appearances",
                "finals_appearances",
                "titles",
            ),
        ),
        "batch_player_seasons.csv": (
            player_rows,
            (
                "run",
                "seed",
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
        ),
        "batch_player_aggregate.csv": (
            player_aggregate,
            (
                "player_id",
                "player_name",
                "team",
                "position",
                "runs_played",
                "average_gp",
                "average_ppg",
                "ppg_stdev",
                "maximum_ppg",
                "average_rpg",
                "average_apg",
                "average_fg_pct",
                "average_3p_pct",
                "average_ft_pct",
                "average_ts_pct",
            ),
        ),
        "batch_playoff_player_seasons.csv": (
            playoff_player_rows,
            (
                "run",
                "seed",
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
                "field_goals_made",
                "field_goals_attempted",
                "fg_pct",
                "three_pointers_made",
                "three_pointers_attempted",
                "three_pct",
                "free_throws_made",
                "free_throws_attempted",
                "ft_pct",
                "effective_fg_pct",
                "true_shooting_pct",
            ),
        ),
        "batch_medical_end_state.csv": (
            medical_rows,
            (
                "run",
                "seed",
                "player_id",
                "player_name",
                "team",
                "position",
                "availability_status",
                "injury_type",
                "injury_games_remaining",
                "fatigue",
                "medical_profile_present",
            ),
        ),
        "batch_medical_summary.csv": (
            medical_summary_rows,
            (
                "run",
                "seed",
                "profile_count",
                "season_games_missed_total",
                "players_with_games_missed",
                "max_player_games_missed",
                "injury_events_total",
                "players_injured",
                "players_with_multiple_injuries",
                "average_fatigue",
                "p90_fatigue",
            ),
        ),
        "batch_player_distribution_summary.csv": (
            player_distribution_rows,
            (
                "run",
                "seed",
                "qualified_players",
                "ppg_p50",
                "ppg_p90",
                "ppg_p95",
                "ppg_p99",
                "ppg_max",
                "players_20_plus_ppg",
                "players_25_plus_ppg",
                "players_30_plus_ppg",
            ),
        ),
        "batch_benchmark_reference.csv": (
            _benchmark_reference_rows(),
            (
                "benchmark_season",
                "scope",
                "metric",
                "label",
                "benchmark",
                "tolerance",
                "weight",
                "category",
                "source",
                "source_url",
            ),
        ),
        "batch_regular_season_benchmark.csv": (
            regular_benchmark_rows,
            (
                "scope",
                "metric",
                "label",
                "category",
                "simulated_mean",
                "simulated_stdev",
                "benchmark",
                "delta",
                "absolute_delta",
                "percent_delta",
                "tolerance",
                "normalized_error",
                "weight",
                "weighted_error",
                "direction",
                "status",
                "calibration_area",
            ),
        ),
        "batch_playoff_benchmark.csv": (
            playoff_benchmark_rows,
            (
                "scope",
                "metric",
                "label",
                "category",
                "simulated_mean",
                "simulated_stdev",
                "benchmark",
                "delta",
                "absolute_delta",
                "percent_delta",
                "tolerance",
                "normalized_error",
                "weight",
                "weighted_error",
                "direction",
                "status",
                "calibration_area",
            ),
        ),
        "batch_run_benchmark_deltas.csv": (
            run_benchmark_delta_rows,
            (
                "run",
                "seed",
                "scope",
                "metric",
                "label",
                "value",
                "benchmark",
                "delta",
                "tolerance",
                "normalized_error",
                "status",
            ),
        ),
        "batch_calibration_priorities.csv": (
            calibration_priority_rows,
            (
                "priority_rank",
                "scope",
                "metric",
                "label",
                "category",
                "simulated_mean",
                "benchmark",
                "delta",
                "tolerance",
                "normalized_error",
                "weighted_error",
                "direction",
                "status",
                "calibration_area",
            ),
        ),
        "batch_champions.csv": (
            champion_rows,
            (
                "team",
                "titles",
                "title_share",
            ),
        ),
        "batch_realism_flags.csv": (
            all_flag_rows,
            (
                "scope",
                "run",
                "seed",
                "team",
                "metric",
                "description",
                "value",
                "lower_bound",
                "upper_bound",
                "status",
                "detail",
            ),
        ),
    }

    row_counts = {}
    for filename, (
        rows,
        preferred,
    ) in file_specs.items():
        row_counts[filename] = (
            _write_csv(
                batch_dir / filename,
                rows,
                preferred,
            )
        )

    inventory_rows = []
    for path in sorted(
        batch_dir.glob("*.csv")
    ):
        inventory_rows.append(
            {
                "file": path.name,
                "rows": (
                    row_counts.get(
                        path.name,
                        "",
                    )
                ),
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            }
        )
    _write_csv(
        batch_dir
        / "batch_file_inventory.csv",
        inventory_rows,
        (
            "file",
            "rows",
            "sha256",
            "bytes",
        ),
    )

    elapsed = (
        time.perf_counter() - start
    )
    summary_json = {
        "version": BATCH_AUDIT_VERSION,
        "schema_version": (
            BATCH_SCHEMA_VERSION
        ),
        "batch_id": batch_id,
        "season_label": season_label,
        "runs": runs,
        "seed_base": seed_base,
        "checkpoint_sha256": (
            checkpoint_sha
        ),
        "source_state_fingerprint": (
            source_fp
        ),
        "elapsed_seconds": elapsed,
        "unique_champions": len(
            {
                row["champion"]
                for row in run_summaries
            }
        ),
        "realism_warning_count": (
            warning_count
        ),
        "calibration_priority_count": len(
            calibration_priority_rows
        ),
        "top_calibration_priorities": (
            calibration_priority_rows[:10]
        ),
        "benchmark_season": BENCHMARK_SEASON,
        "benchmark_source": BENCHMARK_SOURCE,
        "champions": champion_rows,
        "row_counts": row_counts,
    }
    (
        batch_dir
        / "batch_summary.json"
    ).write_text(
        json.dumps(
            summary_json,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    zip_path = (
        root / f"{batch_id}.zip"
    )
    if write_zip:
        with zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(
                batch_dir.rglob("*")
            ):
                if path.is_file():
                    archive.write(
                        path,
                        path.relative_to(
                            batch_dir.parent
                        ),
                    )
        zip_sha = _sha(zip_path)
    else:
        zip_path = Path("")
        zip_sha = ""

    # Final live-state protections.
    if _sha(CHECKPOINT_PATH) != checkpoint_sha:
        raise RuntimeError(
            "Durable checkpoint changed during "
            "read-only batch simulation audit."
        )
    if (
        regular_season_state_fingerprint(
            source
        )
        != source_fp
    ):
        raise RuntimeError(
            "Source checkpoint state changed "
            "during batch simulation audit."
        )

    return BatchSimulationAuditResult(
        version=BATCH_AUDIT_VERSION,
        schema_version=(
            BATCH_SCHEMA_VERSION
        ),
        batch_id=batch_id,
        runs=runs,
        seed_base=seed_base,
        season_label=season_label,
        output_directory=str(
            batch_dir.relative_to(ROOT)
            if batch_dir.is_relative_to(ROOT)
            else batch_dir
        ),
        zip_path=str(
            zip_path.relative_to(ROOT)
            if write_zip
            and zip_path.is_relative_to(ROOT)
            else zip_path
        ),
        zip_sha256=zip_sha,
        checkpoint_sha256=(
            checkpoint_sha
        ),
        source_state_fingerprint=(
            source_fp
        ),
        elapsed_seconds=elapsed,
        unique_champions=len(
            {
                row["champion"]
                for row in run_summaries
            }
        ),
        realism_warning_count=(
            warning_count
        ),
        files=tuple(
            sorted(
                path.name
                for path in batch_dir.iterdir()
                if path.is_file()
            )
        ),
    )
