from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DATA = ROOT / "app_data"
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from simulation_roster_validator_v1 import (  # noqa: E402
    POSITION_DATA_PATH,
    load_position_records,
)


SCRIPT_VERSION = "simulation-player-stat-profile-builder-v1.1-2026-08-08"
SOURCE_PATH = PROCESSED / "player_skill_profiles_2025_26.parquet"
POSITION_PATH = POSITION_DATA_PATH
OUTPUT_PATH = APP_DATA / "simulation_player_stat_profiles_2026_27_v1.json"
REPORT_PATH = OUTPUTS / "simulation_player_stat_profile_build_v1.json"


CORE_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "player_id": (
        "player_id",
        "person_id",
        "nba_player_id",
    ),
    "player_name": (
        "player_name",
        "player_display_name",
        "display_name",
        "name",
    ),
    "games_played": (
        "games_played",
        "gp",
        "games",
    ),
    "minutes_per_game": (
        "minutes_per_game",
        "mpg",
        "min",
        "minutes",
    ),
    "points_per_game": (
        "points_per_game",
        "pts_per_game",
        "points_pg",
        "ppg",
        "pts",
        "points",
    ),
    "rebounds_per_game": (
        "rebounds_per_game",
        "reb_per_game",
        "rebounds_pg",
        "rpg",
        "reb",
        "rebounds",
    ),
    "assists_per_game": (
        "assists_per_game",
        "ast_per_game",
        "assists_pg",
        "apg",
        "ast",
        "assists",
    ),
    "steals_per_game": (
        "steals_per_game",
        "stl_per_game",
        "steals_pg",
        "stl_pg",
        "spg",
        "stl",
        "steals",
    ),
    "blocks_per_game": (
        "blocks_per_game",
        "blk_per_game",
        "blocks_pg",
        "blk_pg",
        "bpg",
        "blk",
        "blocks",
    ),
    "turnovers_per_game": (
        "turnovers_per_game",
        "tov_per_game",
        "turnovers_pg",
        "tov_pg",
        "topg",
        "tov",
        "turnovers",
    ),
    "fouls_per_game": (
        "fouls_per_game",
        "pf_per_game",
        "personal_fouls_per_game",
        "fouls_pg",
        "pf_pg",
        "pfpg",
        "pf",
        "personal_fouls",
    ),
    "field_goals_attempted_per_game": (
        "field_goals_attempted_per_game",
        "field_goal_attempts_per_game",
        "fg_attempts_per_game",
        "fga_per_game",
        "fga_pg",
        "fga",
    ),
    "three_pointers_attempted_per_game": (
        "three_pointers_attempted_per_game",
        "three_point_attempts_per_game",
        "three_point_attempts_pg",
        "fg3a_per_game",
        "fg3a_pg",
        "three_pa",
        "3pa",
        "fg3a",
    ),
    "free_throws_attempted_per_game": (
        "free_throws_attempted_per_game",
        "free_throw_attempts_per_game",
        "fta_per_game",
        "fta_pg",
        "fta",
    ),
    "field_goal_pct": (
        "field_goal_pct",
        "fg_pct",
        "fg_percentage",
    ),
    "three_point_pct": (
        "three_point_pct",
        "fg3_pct",
        "three_pt_pct",
        "3p_pct",
    ),
    "free_throw_pct": (
        "free_throw_pct",
        "ft_pct",
        "free_throw_percentage",
    ),
    "true_shooting_pct": (
        "true_shooting_pct",
        "ts_pct",
        "true_shooting",
    ),
    "usage_pct": (
        "usage_pct",
        "usg_pct",
        "usage_rate",
        "usg",
    ),
    "age": (
        "age",
        "player_age",
    ),
}


def normalize_column(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(
        character
        for character in text
        if character.isalnum()
    )


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    return " ".join(text.lower().split())


def player_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def finite_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def first_nonempty(
    values: Iterable[Any],
    default: Any = "",
) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        if str(value).strip():
            return value
    return default


def resolve_column(
    columns: Iterable[str],
    candidates: Iterable[str],
    *,
    required: bool = False,
) -> str | None:
    columns = list(columns)
    normalized = {
        normalize_column(column): column
        for column in columns
    }

    for candidate in candidates:
        match = normalized.get(
            normalize_column(candidate)
        )
        if match is not None:
            return match

    if required:
        raise KeyError(
            "Could not resolve any of these columns: "
            + ", ".join(candidates)
        )
    return None


def load_positions() -> dict[str, str]:
    """Load positions through the canonical roster-validator parser.

    The position payload uses a top-level ``players_by_id`` mapping.
    Reusing the already validated loader prevents this builder from
    maintaining a second, incompatible JSON parser.
    """
    if not POSITION_PATH.exists():
        raise FileNotFoundError(
            f"Position layer not found: {POSITION_PATH}"
        )

    load_position_records.cache_clear()
    records = load_position_records()
    positions = {
        player_key(player_id): str(
            record.get("position") or ""
        ).strip().upper()
        for player_id, record in records.items()
        if str(
            record.get("position") or ""
        ).strip()
    }

    if not positions:
        raise ValueError(
            "The canonical position loader returned no "
            "usable player records."
        )

    unresolved = [
        player_id
        for player_id, position in positions.items()
        if position == "UNK"
    ]
    if unresolved:
        raise ValueError(
            "The canonical position layer still contains "
            f"{len(unresolved)} UNK record(s)."
        )

    return positions


def source_value(
    row: dict[str, Any] | None,
    column_map: dict[str, str | None],
    field: str,
) -> float | None:
    column = column_map.get(field)
    if row is None or column is None:
        return None
    return finite_float(row.get(column))


def runtime_value(
    record: dict[str, Any],
    *keys: str,
) -> float | None:
    for key in keys:
        value = finite_float(record.get(key))
        if value is not None:
            return value
    return None


def observed_or_runtime(
    row: dict[str, Any] | None,
    column_map: dict[str, str | None],
    field: str,
    runtime_record: dict[str, Any],
    runtime_keys: tuple[str, ...],
    default: float = 0.0,
) -> tuple[float, str]:
    observed = source_value(
        row,
        column_map,
        field,
    )
    if observed is not None:
        return observed, "player_skill_profiles_2025_26"

    fallback = runtime_value(
        runtime_record,
        *runtime_keys,
    )
    if fallback is not None:
        return fallback, "runtime_ratings_fallback"

    return default, "position_baseline_fallback"


def per_36(
    per_game: float,
    minutes_per_game: float,
) -> float:
    if minutes_per_game <= 0:
        return 0.0
    return 36.0 * per_game / minutes_per_game


def weighted_average(
    values: list[tuple[float, float]],
) -> float:
    denominator = sum(
        max(weight, 0.0)
        for _, weight in values
    )
    if denominator <= 0:
        return 0.0
    return sum(
        value * max(weight, 0.0)
        for value, weight in values
    ) / denominator


def profile_reliability(
    games_played: float,
    minutes_per_game: float,
    evidence_weight: float,
) -> float:
    games_component = clamp(
        games_played / 65.0,
        0.0,
        1.0,
    )
    minutes_component = clamp(
        minutes_per_game / 30.0,
        0.0,
        1.0,
    )
    evidence_component = clamp(
        evidence_weight,
        0.0,
        1.0,
    )
    return round(
        0.50 * games_component
        + 0.25 * minutes_component
        + 0.25 * evidence_component,
        4,
    )


def shrink_factor(
    raw_factor: float,
    reliability: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    shrunk = 1.0 + reliability * (
        raw_factor - 1.0
    )
    return round(
        clamp(shrunk, minimum, maximum),
        4,
    )


def build_profiles() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(
            f"Player skill source not found: {SOURCE_PATH}"
        )

    source = pd.read_parquet(SOURCE_PATH)
    if source.empty:
        raise ValueError(
            "Player skill source is empty."
        )

    column_map = {
        field: resolve_column(
            source.columns,
            candidates,
            required=field in {
                "player_id",
                "player_name",
            },
        )
        for field, candidates
        in CORE_COLUMN_CANDIDATES.items()
    }

    id_column = column_map["player_id"]
    assert id_column is not None
    source = source.copy()
    source["_simulation_player_id"] = (
        source[id_column].map(player_key)
    )
    source = source.loc[
        source["_simulation_player_id"].ne("")
    ].drop_duplicates(
        subset=["_simulation_player_id"],
        keep="first",
    )
    source_by_id = {
        record["_simulation_player_id"]: record
        for record in source.to_dict(orient="records")
    }

    runtime = load_runtime_data()
    positions = load_positions()
    profiles: dict[str, dict[str, Any]] = {}
    field_source_counts: dict[
        str,
        dict[str, int],
    ] = defaultdict(lambda: defaultdict(int))

    for player_id, runtime_record in (
        runtime.ratings_by_id.items()
    ):
        player_id = player_key(player_id)
        source_row = source_by_id.get(player_id)

        player_name = str(
            first_nonempty(
                (
                    runtime_record.get("player_name"),
                    runtime_record.get(
                        "player_display_name"
                    ),
                    source_row.get(
                        column_map["player_name"]
                    )
                    if source_row is not None
                    and column_map["player_name"]
                    else None,
                ),
                default=player_id,
            )
        ).strip()

        numeric_fields: dict[
            str,
            tuple[float, str],
        ] = {
            "games_played": observed_or_runtime(
                source_row,
                column_map,
                "games_played",
                runtime_record,
                ("games_played",),
            ),
            "minutes_per_game": observed_or_runtime(
                source_row,
                column_map,
                "minutes_per_game",
                runtime_record,
                ("minutes_per_game",),
            ),
            "points_per_game": observed_or_runtime(
                source_row,
                column_map,
                "points_per_game",
                runtime_record,
                ("points_per_game",),
            ),
            "rebounds_per_game": observed_or_runtime(
                source_row,
                column_map,
                "rebounds_per_game",
                runtime_record,
                ("rebounds_per_game",),
            ),
            "assists_per_game": observed_or_runtime(
                source_row,
                column_map,
                "assists_per_game",
                runtime_record,
                ("assists_per_game",),
            ),
            "steals_per_game": observed_or_runtime(
                source_row,
                column_map,
                "steals_per_game",
                runtime_record,
                ("steals_per_game",),
            ),
            "blocks_per_game": observed_or_runtime(
                source_row,
                column_map,
                "blocks_per_game",
                runtime_record,
                ("blocks_per_game",),
            ),
            "turnovers_per_game": observed_or_runtime(
                source_row,
                column_map,
                "turnovers_per_game",
                runtime_record,
                ("turnovers_per_game",),
            ),
            "fouls_per_game": observed_or_runtime(
                source_row,
                column_map,
                "fouls_per_game",
                runtime_record,
                ("fouls_per_game",),
            ),
            "field_goals_attempted_per_game": (
                observed_or_runtime(
                    source_row,
                    column_map,
                    "field_goals_attempted_per_game",
                    runtime_record,
                    (
                        "field_goals_attempted_per_game",
                    ),
                )
            ),
            "three_pointers_attempted_per_game": (
                observed_or_runtime(
                    source_row,
                    column_map,
                    "three_pointers_attempted_per_game",
                    runtime_record,
                    (
                        "three_pointers_attempted_per_game",
                    ),
                )
            ),
            "free_throws_attempted_per_game": (
                observed_or_runtime(
                    source_row,
                    column_map,
                    "free_throws_attempted_per_game",
                    runtime_record,
                    (
                        "free_throws_attempted_per_game",
                    ),
                )
            ),
            "field_goal_pct": observed_or_runtime(
                source_row,
                column_map,
                "field_goal_pct",
                runtime_record,
                ("field_goal_pct",),
            ),
            "three_point_pct": observed_or_runtime(
                source_row,
                column_map,
                "three_point_pct",
                runtime_record,
                ("three_point_pct",),
            ),
            "free_throw_pct": observed_or_runtime(
                source_row,
                column_map,
                "free_throw_pct",
                runtime_record,
                ("free_throw_pct",),
            ),
            "true_shooting_pct": observed_or_runtime(
                source_row,
                column_map,
                "true_shooting_pct",
                runtime_record,
                ("true_shooting_pct",),
            ),
            "usage_pct": observed_or_runtime(
                source_row,
                column_map,
                "usage_pct",
                runtime_record,
                ("usage_pct",),
            ),
            "age": observed_or_runtime(
                source_row,
                column_map,
                "age",
                runtime_record,
                ("age",),
            ),
        }

        values = {
            field: float(value)
            for field, (value, _)
            in numeric_fields.items()
        }
        sources = {
            field: source_name
            for field, (_, source_name)
            in numeric_fields.items()
        }
        for field, source_name in sources.items():
            field_source_counts[field][source_name] += 1

        games_played = values["games_played"]
        minutes_per_game = values["minutes_per_game"]
        evidence_weight = (
            runtime_value(
                runtime_record,
                "evidence_weight",
            )
            or 0.5
        )
        reliability = profile_reliability(
            games_played,
            minutes_per_game,
            evidence_weight,
        )

        profile = {
            "player_id": player_id,
            "player_name": player_name,
            "position": positions.get(
                player_id,
                "UNK",
            ),
            "source_season": "2025-26",
            "profile_version": SCRIPT_VERSION,
            "age_2026_27": values["age"],
            "games_played": games_played,
            "minutes_per_game": minutes_per_game,
            "points_per_game": values[
                "points_per_game"
            ],
            "rebounds_per_game": values[
                "rebounds_per_game"
            ],
            "assists_per_game": values[
                "assists_per_game"
            ],
            "steals_per_game": values[
                "steals_per_game"
            ],
            "blocks_per_game": values[
                "blocks_per_game"
            ],
            "turnovers_per_game": values[
                "turnovers_per_game"
            ],
            "fouls_per_game": values[
                "fouls_per_game"
            ],
            "field_goals_attempted_per_game": values[
                "field_goals_attempted_per_game"
            ],
            "three_pointers_attempted_per_game": values[
                "three_pointers_attempted_per_game"
            ],
            "free_throws_attempted_per_game": values[
                "free_throws_attempted_per_game"
            ],
            "field_goal_pct": values[
                "field_goal_pct"
            ],
            "three_point_pct": values[
                "three_point_pct"
            ],
            "free_throw_pct": values[
                "free_throw_pct"
            ],
            "true_shooting_pct": values[
                "true_shooting_pct"
            ],
            "usage_pct": values["usage_pct"],
            "points_per_36": round(
                per_36(
                    values["points_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "rebounds_per_36": round(
                per_36(
                    values["rebounds_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "assists_per_36": round(
                per_36(
                    values["assists_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "steals_per_36": round(
                per_36(
                    values["steals_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "blocks_per_36": round(
                per_36(
                    values["blocks_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "turnovers_per_36": round(
                per_36(
                    values["turnovers_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "fouls_per_36": round(
                per_36(
                    values["fouls_per_game"],
                    minutes_per_game,
                ),
                4,
            ),
            "three_attempts_per_36": round(
                per_36(
                    values[
                        "three_pointers_attempted_per_game"
                    ],
                    minutes_per_game,
                ),
                4,
            ),
            "free_throw_attempts_per_36": round(
                per_36(
                    values[
                        "free_throws_attempted_per_game"
                    ],
                    minutes_per_game,
                ),
                4,
            ),
            "overall_rating": (
                runtime_value(
                    runtime_record,
                    "overall_rating",
                )
                or 67.0
            ),
            "scoring_rating": (
                runtime_value(
                    runtime_record,
                    "scoring_rating",
                )
                or 67.0
            ),
            "shooting_rating": (
                runtime_value(
                    runtime_record,
                    "shooting_rating",
                )
                or 67.0
            ),
            "playmaking_rating": (
                runtime_value(
                    runtime_record,
                    "playmaking_rating",
                )
                or 67.0
            ),
            "rebounding_rating": (
                runtime_value(
                    runtime_record,
                    "rebounding_rating",
                )
                or 67.0
            ),
            "defense_rating": (
                runtime_value(
                    runtime_record,
                    "defense_rating",
                )
                or 67.0
            ),
            "efficiency_rating": (
                runtime_value(
                    runtime_record,
                    "efficiency_rating",
                )
                or 67.0
            ),
            "availability_rating": (
                runtime_value(
                    runtime_record,
                    "availability_rating",
                )
                or 67.0
            ),
            "potential_rating": (
                runtime_value(
                    runtime_record,
                    "potential_rating",
                )
                or runtime_value(
                    runtime_record,
                    "overall_rating",
                )
                or 67.0
            ),
            "future_outlook_rating": (
                runtime_value(
                    runtime_record,
                    "future_outlook_rating",
                )
                or runtime_value(
                    runtime_record,
                    "overall_rating",
                )
                or 67.0
            ),
            "career_seasons": (
                runtime_value(
                    runtime_record,
                    "career_seasons",
                )
                or 0.0
            ),
            "career_games": (
                runtime_value(
                    runtime_record,
                    "career_games",
                )
                or 0.0
            ),
            "career_minutes": (
                runtime_value(
                    runtime_record,
                    "career_minutes",
                )
                or 0.0
            ),
            "future_peak_season": (
                runtime_value(
                    runtime_record,
                    "future_peak_season",
                )
                or 0.0
            ),
            "development_direction": str(
                runtime_record.get(
                    "development_direction",
                    "",
                )
            ).strip(),
            "archetype": str(
                runtime_record.get(
                    "archetype",
                    "",
                )
            ).strip(),
            "primary_skill": str(
                runtime_record.get(
                    "primary_skill",
                    "",
                )
            ).strip(),
            "secondary_skill": str(
                runtime_record.get(
                    "secondary_skill",
                    "",
                )
            ).strip(),
            "evidence_weight": evidence_weight,
            "profile_reliability": reliability,
            "field_sources": sources,
        }
        profiles[player_id] = profile

    baseline_stats = (
        "points_per_36",
        "rebounds_per_36",
        "assists_per_36",
        "steals_per_36",
        "blocks_per_36",
        "turnovers_per_36",
        "fouls_per_36",
        "three_attempts_per_36",
        "free_throw_attempts_per_36",
    )
    baselines: dict[
        str,
        dict[str, float],
    ] = defaultdict(dict)

    positions_present = sorted(
        {
            profile["position"]
            for profile in profiles.values()
        }
    )
    for position in positions_present:
        position_profiles = [
            profile
            for profile in profiles.values()
            if profile["position"] == position
            and profile["minutes_per_game"] > 0
        ]
        for stat in baseline_stats:
            values = [
                (
                    float(profile[stat]),
                    float(profile["games_played"])
                    * float(profile["minutes_per_game"]),
                )
                for profile in position_profiles
                if float(profile[stat]) > 0
            ]
            baselines[position][stat] = round(
                weighted_average(values),
                4,
            )

    factor_ranges = {
        "points_per_36": (0.45, 1.85),
        "rebounds_per_36": (0.35, 2.60),
        "assists_per_36": (0.30, 3.50),
        "steals_per_36": (0.35, 2.40),
        "blocks_per_36": (0.20, 4.50),
        "turnovers_per_36": (0.45, 2.20),
        "fouls_per_36": (0.55, 1.80),
        "three_attempts_per_36": (0.15, 3.50),
        "free_throw_attempts_per_36": (
            0.25,
            2.80,
        ),
    }

    for profile in profiles.values():
        position = profile["position"]
        profile["stat_factors"] = {}

        for stat, (
            minimum,
            maximum,
        ) in factor_ranges.items():
            baseline = baselines.get(
                position,
                {},
            ).get(stat, 0.0)
            observed = float(profile[stat])
            raw_factor = (
                observed / baseline
                if baseline > 0 and observed >= 0
                else 1.0
            )
            profile["stat_factors"][
                stat.replace("_per_36", "")
            ] = shrink_factor(
                raw_factor,
                float(
                    profile["profile_reliability"]
                ),
                minimum=minimum,
                maximum=maximum,
            )

    name_index = {
        normalize_name(profile["player_name"]): profile
        for profile in profiles.values()
    }

    def sample(name: str) -> dict[str, Any] | None:
        return name_index.get(normalize_name(name))

    jokic = sample("Nikola Jokic")
    curry = sample("Stephen Curry")
    wemby = sample("Victor Wembanyama")
    trae = sample("Trae Young")
    duren = sample("Jalen Duren")

    checks = {
        "source_has_582_rows": len(source) == 582,
        "runtime_has_582_players": (
            len(runtime.ratings_by_id) == 582
        ),
        "all_runtime_players_profiled": (
            len(profiles) == len(runtime.ratings_by_id)
        ),
        "position_layer_has_582_records": (
            len(positions) == 582
        ),
        "all_profiles_have_positions": all(
            profile["position"] != "UNK"
            for profile in profiles.values()
        ),
        "profile_ids_match_position_ids": (
            set(profiles) == set(positions)
        ),
        "all_profiles_have_core_ratings": all(
            profile["overall_rating"] > 0
            and profile["scoring_rating"] > 0
            and profile["playmaking_rating"] > 0
            and profile["rebounding_rating"] > 0
            for profile in profiles.values()
        ),
        "jokic_profile_found": jokic is not None,
        "jokic_elite_passing_and_rebounding": bool(
            jokic
            and jokic["assists_per_game"] >= 7.0
            and jokic["rebounds_per_game"] >= 9.0
            and jokic["playmaking_rating"] >= 90.0
            and jokic["rebounding_rating"] >= 90.0
        ),
        "jokic_center_assist_factor_is_exceptional": bool(
            jokic
            and jokic["stat_factors"]["assists"] >= 1.75
        ),
        "curry_elite_shooting_profile": bool(
            curry
            and curry["shooting_rating"] >= 90.0
            and curry["three_point_pct"] >= 0.35
        ),
        "wembanyama_elite_defense_profile": bool(
            wemby
            and wemby["defense_rating"] >= 95.0
            and (
                wemby["blocks_per_game"] >= 2.0
                or wemby["stat_factors"]["blocks"] >= 1.40
            )
        ),
        "trae_elite_assist_profile": bool(
            trae
            and trae["assists_per_game"] >= 7.0
            and trae["stat_factors"]["assists"] >= 1.30
        ),
        "duren_strong_rebound_profile": bool(
            duren
            and duren["rebounds_per_game"] >= 9.0
            and duren["rebounding_rating"] >= 90.0
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    metadata = {
        "script": SCRIPT_VERSION,
        "source_path": str(
            SOURCE_PATH.relative_to(ROOT)
        ),
        "position_path": str(
            POSITION_PATH.relative_to(ROOT)
        ),
        "output_path": str(
            OUTPUT_PATH.relative_to(ROOT)
        ),
        "source_rows": len(source),
        "runtime_players": len(
            runtime.ratings_by_id
        ),
        "profiles_built": len(profiles),
        "resolved_columns": column_map,
        "field_source_counts": {
            field: dict(counts)
            for field, counts
            in field_source_counts.items()
        },
        "position_baselines": dict(baselines),
        "checks": checks,
        "failed_checks": failed,
        "sample_profiles": {
            name: profile
            for name, profile in {
                "Nikola Jokic": jokic,
                "Stephen Curry": curry,
                "Victor Wembanyama": wemby,
                "Trae Young": trae,
                "Jalen Duren": duren,
            }.items()
            if profile is not None
        },
        "passed": not failed,
    }

    return profiles, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    profiles, report = build_profiles()

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "version": SCRIPT_VERSION,
                "source_season": "2025-26",
                "players": profiles,
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    print("=" * 88)
    print("SIMULATION PLAYER STAT PROFILE BUILD")
    print("=" * 88)
    print(f"Source rows:       {report['source_rows']}")
    print(f"Runtime players:   {report['runtime_players']}")
    print(f"Profiles built:    {report['profiles_built']}")
    print("\nRESOLVED COLUMNS")
    for field, column in (
        report["resolved_columns"].items()
    ):
        print(
            f"{field:40s} -> "
            f"{column or '(runtime fallback)'}"
        )

    print("\nCHECKS")
    for name, passed in report["checks"].items():
        print(
            f"{'PASS' if passed else 'FAIL':4s}  "
            f"{name}"
        )

    print("\nSAMPLE PROFILE SIGNALS")
    for name, profile in (
        report["sample_profiles"].items()
    ):
        print(
            f"{name:22s} | "
            f"POS={profile['position']:5s} | "
            f"PPG={profile['points_per_game']:.2f} | "
            f"RPG={profile['rebounds_per_game']:.2f} | "
            f"APG={profile['assists_per_game']:.2f} | "
            f"AST factor="
            f"{profile['stat_factors']['assists']:.2f} | "
            f"REB factor="
            f"{profile['stat_factors']['rebounds']:.2f} | "
            f"BLK factor="
            f"{profile['stat_factors']['blocks']:.2f}"
        )

    print(f"\nProfile layer: {OUTPUT_PATH}")
    print(f"Build report:  {REPORT_PATH}")

    if not report["passed"]:
        print(
            "\nSIMULATION PLAYER STAT PROFILE BUILD FAILED"
        )
        return 1

    print(
        "\nSIMULATION PLAYER STAT PROFILE BUILD PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())