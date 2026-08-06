"""Build fan-friendly player profiles for the mixed trade Streamlit app.

The output contains familiar 2025-26 NBA statistics, league percentiles used
for visual comparison bars, and presentation-only 60.0-99.9 player ratings.

Inputs:
    app_data/mixed_trade_visual_assets_2026_27_v1.json
    data/processed/current_player_projection_board_2025_26_to_2026_27.parquet
        or CSV fallback

Outputs:
    app_data/mixed_trade_player_profiles_2026_27_v1.json
    outputs/mixed_trade_player_profiles_validation_v1.csv
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "mixed-trade-player-profiles-v1-2026-08-06"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

VISUAL_ASSETS_PATH = (
    APP_DATA_DIRECTORY
    / "mixed_trade_visual_assets_2026_27_v1.json"
)
PROJECTION_BOARD_CANDIDATES = [
    DATA_DIRECTORY
    / "current_player_projection_board_2025_26_to_2026_27.parquet",
    DATA_DIRECTORY
    / "current_player_projection_board_2025_26_to_2026_27.csv",
]
OUTPUT_PATH = (
    APP_DATA_DIRECTORY
    / "mixed_trade_player_profiles_2026_27_v1.json"
)
VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_trade_player_profiles_validation_v1.csv"
)

COMPARISON_MINIMUM_GAMES = 10
COMPARISON_MINIMUM_MPG = 8.0

REQUIRED_COLUMNS = {
    "player_id",
    "player_name",
    "games_played",
    "minutes_per_game",
    "points_per_game",
    "assists_per_game",
    "rebounds_per_game",
    "base_fg_pct",
    "base_fg3_pct",
    "advanced_ts_pct",
    "availability_rate",
    "roster_value_percentile",
    "scoring_score",
    "shooting_score",
    "playmaking_score",
    "rebounding_score",
    "defense_score",
}

OPTIONAL_COLUMNS = {
    "age",
    "advanced_usg_pct",
    "advanced_pie",
    "advanced_net_rating",
    "primary_skill",
    "secondary_skill",
    "value_tier",
    "confidence_tier",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without project files.",
    )
    return parser.parse_args()


def clean_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def percent_display(value: Any) -> float | None:
    number = safe_float(value)
    if not math.isfinite(number):
        return None
    if abs(number) <= 1.5:
        number *= 100.0
    return round(number, 1)


def one_decimal(value: Any) -> float | None:
    number = safe_float(value)
    return None if not math.isfinite(number) else round(number, 1)


def percentile_to_rating(percentile: Any) -> float | None:
    """Map a 0-100 percentile to the presentation-only 60.0-99.9 scale."""
    number = safe_float(percentile)
    if not math.isfinite(number):
        return None
    number = float(np.clip(number, 0.0, 100.0))
    return round(60.0 + 39.9 * number / 100.0, 1)


def percentile_series(
    population: pd.Series,
    target: pd.Series,
) -> pd.Series:
    """Return percentile positions for target values against population."""
    population_numeric = pd.to_numeric(
        population,
        errors="coerce",
    ).dropna()

    if population_numeric.empty:
        return pd.Series(np.nan, index=target.index)

    sorted_values = np.sort(
        population_numeric.to_numpy(dtype=float)
    )

    target_numeric = pd.to_numeric(target, errors="coerce")
    values = []
    for value in target_numeric:
        if not math.isfinite(safe_float(value)):
            values.append(np.nan)
            continue

        right_position = np.searchsorted(
            sorted_values,
            float(value),
            side="right",
        )
        values.append(
            100.0 * right_position / len(sorted_values)
        )

    return pd.Series(values, index=target.index, dtype=float)


def locate_projection_board() -> Path:
    for path in PROJECTION_BOARD_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Projection board not found:\n"
        + "\n".join(str(path) for path in PROJECTION_BOARD_CANDIDATES)
    )


def read_projection_board(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def build_profiles(
    visual_assets: dict[str, Any],
    board: pd.DataFrame,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    missing = sorted(REQUIRED_COLUMNS.difference(board.columns))
    if missing:
        raise ValueError(
            "Projection board is missing required columns:\n"
            + "\n".join(missing)
        )

    working = board.copy()
    working["normalized_player_id"] = working[
        "player_id"
    ].map(clean_player_id)

    population = working.loc[
        pd.to_numeric(
            working["games_played"],
            errors="coerce",
        ).ge(COMPARISON_MINIMUM_GAMES)
        & pd.to_numeric(
            working["minutes_per_game"],
            errors="coerce",
        ).ge(COMPARISON_MINIMUM_MPG)
    ].copy()

    metric_columns = {
        "points_per_game": "points_per_game_percentile",
        "rebounds_per_game": "rebounds_per_game_percentile",
        "assists_per_game": "assists_per_game_percentile",
        "advanced_ts_pct": "true_shooting_percentile",
        "base_fg3_pct": "three_point_percentile",
        "minutes_per_game": "minutes_per_game_percentile",
        "games_played": "games_played_percentile",
        "scoring_score": "scoring_percentile",
        "shooting_score": "shooting_percentile",
        "playmaking_score": "playmaking_percentile",
        "rebounding_score": "rebounding_percentile",
        "defense_score": "defense_percentile",
    }

    for source_column, percentile_column in metric_columns.items():
        working[percentile_column] = percentile_series(
            population[source_column],
            working[source_column],
        )

    by_id = {
        row["normalized_player_id"]: row
        for row in working.to_dict(orient="records")
        if row["normalized_player_id"]
    }

    profiles: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    for key, asset in visual_assets.get("players", {}).items():
        player_id = clean_player_id(asset.get("player_id"))
        row = by_id.get(player_id)

        if row is None:
            unresolved.append(
                {
                    "player_key": key,
                    "player_id": player_id,
                    "player_name": asset.get("player_name", ""),
                    "team_abbreviation": asset.get(
                        "team_abbreviation",
                        "",
                    ),
                }
            )
            continue

        overall_rating = percentile_to_rating(
            row["roster_value_percentile"]
        )

        profile = {
            "player_id": player_id,
            "player_name": str(row["player_name"]).strip(),
            "team_abbreviation": str(
                asset.get("team_abbreviation", "")
            ).strip(),
            "statistics_season": "2025-26",
            "comparison_population_note": (
                "Bar length is the league percentile among players "
                f"with at least {COMPARISON_MINIMUM_GAMES} games and "
                f"{COMPARISON_MINIMUM_MPG:.0f} minutes per game."
            ),
            "age": one_decimal(row.get("age")),
            "games_played": int(
                round(safe_float(row["games_played"], 0.0))
            ),
            "minutes_per_game": one_decimal(
                row["minutes_per_game"]
            ),
            "points_per_game": one_decimal(
                row["points_per_game"]
            ),
            "rebounds_per_game": one_decimal(
                row["rebounds_per_game"]
            ),
            "assists_per_game": one_decimal(
                row["assists_per_game"]
            ),
            "field_goal_pct": percent_display(
                row["base_fg_pct"]
            ),
            "three_point_pct": percent_display(
                row["base_fg3_pct"]
            ),
            "true_shooting_pct": percent_display(
                row["advanced_ts_pct"]
            ),
            "usage_pct": percent_display(
                row.get("advanced_usg_pct")
            ),
            "pie": one_decimal(row.get("advanced_pie")),
            "net_rating": one_decimal(
                row.get("advanced_net_rating")
            ),
            "availability_pct": percent_display(
                row["availability_rate"]
            ),
            "points_per_game_percentile": one_decimal(
                row["points_per_game_percentile"]
            ),
            "rebounds_per_game_percentile": one_decimal(
                row["rebounds_per_game_percentile"]
            ),
            "assists_per_game_percentile": one_decimal(
                row["assists_per_game_percentile"]
            ),
            "true_shooting_percentile": one_decimal(
                row["true_shooting_percentile"]
            ),
            "three_point_percentile": one_decimal(
                row["three_point_percentile"]
            ),
            "minutes_per_game_percentile": one_decimal(
                row["minutes_per_game_percentile"]
            ),
            "games_played_percentile": one_decimal(
                row["games_played_percentile"]
            ),
            "overall_rating": overall_rating,
            "scoring_rating": percentile_to_rating(
                row["scoring_percentile"]
            ),
            "shooting_rating": percentile_to_rating(
                row["shooting_percentile"]
            ),
            "playmaking_rating": percentile_to_rating(
                row["playmaking_percentile"]
            ),
            "rebounding_rating": percentile_to_rating(
                row["rebounding_percentile"]
            ),
            "defense_rating": percentile_to_rating(
                row["defense_percentile"]
            ),
            "primary_skill": str(
                row.get("primary_skill", "")
            ).strip(),
            "secondary_skill": str(
                row.get("secondary_skill", "")
            ).strip(),
            "value_tier": str(
                row.get("value_tier", "")
            ).strip(),
            "confidence_tier": str(
                row.get("confidence_tier", "")
            ).strip(),
            "rating_scope_note": (
                "The 60.0-99.9 ratings are presentation-only transforms "
                "of league-relative model percentiles. Internal optimization "
                "continues to use the original precise values."
            ),
        }

        profiles[key] = profile

    return profiles, unresolved


def run_self_test() -> int:
    population = pd.Series([1.0, 2.0, 3.0, 4.0])
    target = pd.Series([1.0, 2.0, 4.0])
    percentile_result = percentile_series(
        population,
        target,
    ).round(1).tolist()

    tests = {
        "player_id_cleaning": clean_player_id(1630180.0) == "1630180",
        "decimal_percentage_conversion": percent_display(0.583) == 58.3,
        "whole_percentage_preserved": percent_display(58.3) == 58.3,
        "rating_floor": percentile_to_rating(0.0) == 60.0,
        "rating_ceiling": percentile_to_rating(100.0) == 99.9,
        "rating_midpoint": percentile_to_rating(50.0) == 80.0,
        "percentile_ordering": percentile_result == [25.0, 50.0, 100.0],
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    if not VISUAL_ASSETS_PATH.exists():
        raise FileNotFoundError(
            f"Visual assets not found: {VISUAL_ASSETS_PATH}"
        )

    visual_assets = json.loads(
        VISUAL_ASSETS_PATH.read_text(encoding="utf-8")
    )
    projection_path = locate_projection_board()
    board = read_projection_board(projection_path)

    profiles, unresolved = build_profiles(
        visual_assets,
        board,
    )

    payload = {
        "release_name": "mixed_trade_player_profiles_2026_27_v1",
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "statistics_season": "2025-26",
        "projection_board_source": str(projection_path),
        "comparison_population": {
            "minimum_games": COMPARISON_MINIMUM_GAMES,
            "minimum_minutes_per_game": COMPARISON_MINIMUM_MPG,
        },
        "counts": {
            "visual_asset_players": len(
                visual_assets.get("players", {})
            ),
            "resolved_players": len(profiles),
            "unresolved_players": len(unresolved),
        },
        "players": profiles,
        "unresolved_players": unresolved,
    }

    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    validation_rows = [
        {
            "check_name": "visual_asset_players_exist",
            "passed": len(
                visual_assets.get("players", {})
            ) > 0,
            "observed": len(
                visual_assets.get("players", {})
            ),
            "expected": ">0",
        },
        {
            "check_name": "all_visual_asset_players_resolved",
            "passed": len(unresolved) == 0,
            "observed": len(unresolved),
            "expected": 0,
        },
        {
            "check_name": "all_profiles_have_familiar_stats",
            "passed": all(
                profile.get("points_per_game") is not None
                and profile.get("rebounds_per_game") is not None
                and profile.get("assists_per_game") is not None
                and profile.get("true_shooting_pct") is not None
                for profile in profiles.values()
            ),
            "observed": sum(
                profile.get("points_per_game") is not None
                and profile.get("rebounds_per_game") is not None
                and profile.get("assists_per_game") is not None
                and profile.get("true_shooting_pct") is not None
                for profile in profiles.values()
            ),
            "expected": len(profiles),
        },
        {
            "check_name": "all_profiles_have_overall_rating",
            "passed": all(
                profile.get("overall_rating") is not None
                for profile in profiles.values()
            ),
            "observed": sum(
                profile.get("overall_rating") is not None
                for profile in profiles.values()
            ),
            "expected": len(profiles),
        },
        {
            "check_name": "all_display_ratings_within_scale",
            "passed": all(
                60.0 <= float(profile["overall_rating"]) <= 99.9
                for profile in profiles.values()
            ),
            "observed": {
                "minimum": min(
                    (
                        profile["overall_rating"]
                        for profile in profiles.values()
                    ),
                    default=None,
                ),
                "maximum": max(
                    (
                        profile["overall_rating"]
                        for profile in profiles.values()
                    ),
                    default=None,
                ),
            },
            "expected": "60.0-99.9",
        },
    ]

    release_valid = all(
        bool(row["passed"]) for row in validation_rows
    )
    pd.DataFrame(validation_rows).to_csv(
        VALIDATION_PATH,
        index=False,
    )

    print("=" * 84)
    print("MIXED TRADE PLAYER COMPARISON PROFILES")
    print("=" * 84)
    print(f"Projection source: {projection_path}")
    print(
        f"Players resolved: {len(profiles)}/"
        f"{len(visual_assets.get('players', {}))}"
    )
    if unresolved:
        print("Unresolved players:")
        for player in unresolved:
            print(
                f"  {player['player_name']} | "
                f"{player['team_abbreviation']} | "
                f"{player['player_id']}"
            )
    print(
        f"Validation: "
        f"{sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Release valid: {release_valid}")
    print(f"Saved: {OUTPUT_PATH}")

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())