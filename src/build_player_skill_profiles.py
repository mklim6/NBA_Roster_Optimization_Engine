from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

MIN_GAMES_FOR_MAIN_POOL = 10
MIN_MINUTES_PER_GAME_FOR_MAIN_POOL = 8.0

COUNTING_STAT_PRIOR_MINUTES = 500.0
RATE_STAT_PRIOR_POSSESSIONS = 1_000.0
RATING_PRIOR_POSSESSIONS = 1_500.0
THREE_POINT_PRIOR_ATTEMPTS = 100.0


def find_latest_player_pool() -> Path:
    """Find the most recently created base player-pool file."""

    candidates = list(
        PROCESSED_DIRECTORY.glob(
            "base_player_pool_*.parquet"
        )
    )

    if not candidates:
        raise FileNotFoundError(
            "No base player-pool Parquet file was found in:\n"
            f"{PROCESSED_DIRECTORY}"
        )

    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def weighted_league_mean(
    values: pd.Series,
    weights: pd.Series,
) -> float:
    """Calculate a weighted league average."""

    clean_values = pd.to_numeric(
        values,
        errors="coerce",
    )

    clean_weights = (
        pd.to_numeric(
            weights,
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0)
    )

    valid = (
        clean_values.notna()
        & clean_weights.notna()
        & (clean_weights > 0)
    )

    if valid.any():
        return float(
            np.average(
                clean_values.loc[valid],
                weights=clean_weights.loc[valid],
            )
        )

    fallback = clean_values.mean()

    if pd.isna(fallback):
        raise ValueError(
            "A league average could not be calculated."
        )

    return float(fallback)


def shrink_to_league_average(
    values: pd.Series,
    sample_size: pd.Series,
    prior_size: float,
) -> pd.Series:
    """
    Shrink unstable statistics toward the league average.

    Large-sample players retain more of their observed value.
    Small-sample players receive more influence from the prior.
    """

    clean_values = pd.to_numeric(
        values,
        errors="coerce",
    )

    clean_sample = (
        pd.to_numeric(
            sample_size,
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0)
    )

    league_average = weighted_league_mean(
        clean_values,
        clean_sample,
    )

    clean_values = clean_values.fillna(
        league_average
    )

    return (
        clean_values * clean_sample
        + league_average * prior_size
    ) / (clean_sample + prior_size)


def percentile_score(
    values: pd.Series,
    higher_is_better: bool = True,
) -> pd.Series:
    """Convert a metric into a 0-to-100 league percentile."""

    clean_values = (
        pd.to_numeric(
            values,
            errors="coerce",
        )
        .replace(
            [np.inf, -np.inf],
            np.nan,
        )
    )

    median_value = clean_values.median()

    if pd.isna(median_value):
        median_value = 0.0

    clean_values = clean_values.fillna(
        median_value
    )

    percentiles = (
        clean_values.rank(
            method="average",
            pct=True,
        )
        * 100.0
    )

    if not higher_is_better:
        percentiles = 100.0 - percentiles

    return percentiles.clip(
        lower=0.0,
        upper=100.0,
    )


def add_per_36_stat(
    frame: pd.DataFrame,
    source_column: str,
    output_column: str,
) -> None:
    """Convert a per-game statistic to a per-36 rate."""

    minutes = pd.to_numeric(
        frame["minutes_per_game"],
        errors="coerce",
    )

    source = pd.to_numeric(
        frame[source_column],
        errors="coerce",
    )

    frame[output_column] = np.where(
        minutes > 0,
        source * 36.0 / minutes,
        np.nan,
    )


def assign_skill_labels(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Identify each player's two strongest skill groups."""

    skill_columns = {
        "scoring_score": "Scoring",
        "playmaking_score": "Playmaking",
        "shooting_score": "Shooting",
        "rebounding_score": "Rebounding",
        "defense_score": "Defense",
    }

    skill_frame = frame[
        list(skill_columns)
    ].rename(
        columns=skill_columns
    )

    ordered_skills = np.argsort(
        -skill_frame.to_numpy(),
        axis=1,
    )

    skill_names = np.array(
        skill_frame.columns
    )

    frame["primary_skill"] = skill_names[
        ordered_skills[:, 0]
    ]

    frame["secondary_skill"] = skill_names[
        ordered_skills[:, 1]
    ]

    return frame


def assign_value_tier(
    percentile: float,
) -> str:
    """Translate a value percentile into a player tier."""

    if percentile >= 95:
        return "Elite cornerstone"

    if percentile >= 80:
        return "High-impact starter"

    if percentile >= 60:
        return "Starter"

    if percentile >= 35:
        return "Rotation player"

    return "Depth / development"


def assign_confidence_tier(
    total_minutes: float,
) -> str:
    """Describe the amount of evidence behind a profile."""

    if total_minutes >= 2_000:
        return "High"

    if total_minutes >= 1_000:
        return "Medium"

    if total_minutes >= 300:
        return "Limited"

    return "Very limited"


def main() -> None:
    """Create reliability-adjusted player skill profiles."""

    source_path = find_latest_player_pool()

    player_pool = pd.read_parquet(
        source_path
    )

    required_columns = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "games_played",
        "total_minutes",
        "minutes_per_game",
        "points_per_game",
        "assists_per_game",
        "rebounds_per_game",
        "offensive_rebounds_per_game",
        "defensive_rebounds_per_game",
        "steals_per_game",
        "blocks_per_game",
        "turnovers_per_game",
        "threes_made_per_game",
        "threes_attempted_per_game",
        "three_point_percentage",
        "offensive_rating",
        "defensive_rating",
        "net_rating",
        "assist_percentage",
        "assist_to_turnover_ratio",
        "offensive_rebound_percentage",
        "defensive_rebound_percentage",
        "total_rebound_percentage",
        "turnover_percentage",
        "effective_field_goal_percentage",
        "true_shooting_percentage",
        "usage_percentage",
        "player_impact_estimate",
        "possessions",
        "availability_rate",
        "small_sample_flag",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in player_pool.columns
    ]

    if missing_columns:
        raise ValueError(
            "The player pool is missing columns:\n"
            + "\n".join(missing_columns)
        )

    player_pool = player_pool.copy()

    numeric_columns = [
        column
        for column in required_columns
        if column not in {
            "player_id",
            "player_name",
            "team_abbreviation",
            "small_sample_flag",
        }
    ]

    for column in numeric_columns:
        player_pool[column] = pd.to_numeric(
            player_pool[column],
            errors="coerce",
        )

    per_36_mapping = {
        "points_per_game": "points_per_36",
        "assists_per_game": "assists_per_36",
        "rebounds_per_game": "rebounds_per_36",
        "offensive_rebounds_per_game":
            "offensive_rebounds_per_36",
        "defensive_rebounds_per_game":
            "defensive_rebounds_per_36",
        "steals_per_game": "steals_per_36",
        "blocks_per_game": "blocks_per_36",
        "turnovers_per_game": "turnovers_per_36",
        "threes_made_per_game":
            "threes_made_per_36",
        "threes_attempted_per_game":
            "threes_attempted_per_36",
    }

    for source_column, output_column in (
        per_36_mapping.items()
    ):
        add_per_36_stat(
            player_pool,
            source_column,
            output_column,
        )

    player_pool["total_three_point_attempts"] = (
        player_pool["threes_attempted_per_game"]
        * player_pool["games_played"]
    )

    minute_sample = (
        player_pool["total_minutes"]
        .fillna(0.0)
        .clip(lower=0.0)
    )

    possession_sample = (
        player_pool["possessions"]
        .fillna(0.0)
        .clip(lower=0.0)
    )

    counting_metrics = [
        "points_per_36",
        "assists_per_36",
        "rebounds_per_36",
        "offensive_rebounds_per_36",
        "defensive_rebounds_per_36",
        "steals_per_36",
        "blocks_per_36",
        "turnovers_per_36",
        "threes_made_per_36",
        "threes_attempted_per_36",
    ]

    for metric in counting_metrics:
        player_pool[f"adjusted_{metric}"] = (
            shrink_to_league_average(
                player_pool[metric],
                minute_sample,
                COUNTING_STAT_PRIOR_MINUTES,
            )
        )

    possession_rate_metrics = [
        "assist_percentage",
        "assist_to_turnover_ratio",
        "offensive_rebound_percentage",
        "defensive_rebound_percentage",
        "total_rebound_percentage",
        "turnover_percentage",
        "effective_field_goal_percentage",
        "true_shooting_percentage",
        "usage_percentage",
        "player_impact_estimate",
    ]

    for metric in possession_rate_metrics:
        player_pool[f"adjusted_{metric}"] = (
            shrink_to_league_average(
                player_pool[metric],
                possession_sample,
                RATE_STAT_PRIOR_POSSESSIONS,
            )
        )

    rating_metrics = [
        "offensive_rating",
        "defensive_rating",
        "net_rating",
    ]

    for metric in rating_metrics:
        player_pool[f"adjusted_{metric}"] = (
            shrink_to_league_average(
                player_pool[metric],
                possession_sample,
                RATING_PRIOR_POSSESSIONS,
            )
        )

    player_pool[
        "adjusted_three_point_percentage"
    ] = shrink_to_league_average(
        player_pool["three_point_percentage"],
        player_pool[
            "total_three_point_attempts"
        ],
        THREE_POINT_PRIOR_ATTEMPTS,
    )

    score_inputs = {
        "points_score": (
            "adjusted_points_per_36",
            True,
        ),
        "assists_score": (
            "adjusted_assists_per_36",
            True,
        ),
        "rebounds_score": (
            "adjusted_rebounds_per_36",
            True,
        ),
        "steals_score": (
            "adjusted_steals_per_36",
            True,
        ),
        "blocks_score": (
            "adjusted_blocks_per_36",
            True,
        ),
        "three_point_accuracy_score": (
            "adjusted_three_point_percentage",
            True,
        ),
        "three_point_volume_score": (
            "adjusted_threes_attempted_per_36",
            True,
        ),
        "assist_percentage_score": (
            "adjusted_assist_percentage",
            True,
        ),
        "assist_to_turnover_score": (
            "adjusted_assist_to_turnover_ratio",
            True,
        ),
        "turnover_percentage_score": (
            "adjusted_turnover_percentage",
            False,
        ),
        "offensive_rebound_percentage_score": (
            "adjusted_offensive_rebound_percentage",
            True,
        ),
        "defensive_rebound_percentage_score": (
            "adjusted_defensive_rebound_percentage",
            True,
        ),
        "total_rebound_percentage_score": (
            "adjusted_total_rebound_percentage",
            True,
        ),
        "effective_field_goal_score": (
            "adjusted_effective_field_goal_percentage",
            True,
        ),
        "true_shooting_score": (
            "adjusted_true_shooting_percentage",
            True,
        ),
        "usage_score": (
            "adjusted_usage_percentage",
            True,
        ),
        "offensive_rating_score": (
            "adjusted_offensive_rating",
            True,
        ),
        "defensive_rating_score": (
            "adjusted_defensive_rating",
            False,
        ),
        "net_rating_score": (
            "adjusted_net_rating",
            True,
        ),
        "impact_estimate_score": (
            "adjusted_player_impact_estimate",
            True,
        ),
        "minutes_score": (
            "minutes_per_game",
            True,
        ),
        "availability_score": (
            "availability_rate",
            True,
        ),
    }

    for output_column, (
        metric,
        higher_is_better,
    ) in score_inputs.items():
        player_pool[output_column] = (
            percentile_score(
                player_pool[metric],
                higher_is_better=higher_is_better,
            )
        )

    player_pool["scoring_score"] = (
        0.45 * player_pool["points_score"]
        + 0.25
        * player_pool["true_shooting_score"]
        + 0.15 * player_pool["usage_score"]
        + 0.15
        * player_pool[
            "effective_field_goal_score"
        ]
    )

    player_pool["playmaking_score"] = (
        0.40 * player_pool["assists_score"]
        + 0.25
        * player_pool[
            "assist_percentage_score"
        ]
        + 0.20
        * player_pool[
            "assist_to_turnover_score"
        ]
        + 0.15
        * player_pool[
            "turnover_percentage_score"
        ]
    )

    player_pool["shooting_score"] = (
        0.35
        * player_pool[
            "three_point_accuracy_score"
        ]
        + 0.25
        * player_pool[
            "three_point_volume_score"
        ]
        + 0.20
        * player_pool[
            "effective_field_goal_score"
        ]
        + 0.20
        * player_pool["true_shooting_score"]
    )

    player_pool["rebounding_score"] = (
        0.50 * player_pool["rebounds_score"]
        + 0.20
        * player_pool[
            "total_rebound_percentage_score"
        ]
        + 0.15
        * player_pool[
            "offensive_rebound_percentage_score"
        ]
        + 0.15
        * player_pool[
            "defensive_rebound_percentage_score"
        ]
    )

    player_pool["defense_score"] = (
        0.35
        * player_pool["defensive_rating_score"]
        + 0.20 * player_pool["steals_score"]
        + 0.20 * player_pool["blocks_score"]
        + 0.15
        * player_pool[
            "defensive_rebound_percentage_score"
        ]
        + 0.10
        * player_pool["net_rating_score"]
    )

    player_pool["workload_score"] = (
        0.65 * player_pool["minutes_score"]
        + 0.35
        * player_pool["availability_score"]
    )

    player_pool["impact_score"] = (
        0.35
        * player_pool["impact_estimate_score"]
        + 0.25
        * player_pool["net_rating_score"]
        + 0.15
        * player_pool[
            "offensive_rating_score"
        ]
        + 0.15
        * player_pool["workload_score"]
        + 0.10
        * player_pool["availability_score"]
    )

    player_pool["raw_overall_score"] = (
        0.20 * player_pool["scoring_score"]
        + 0.15
        * player_pool["playmaking_score"]
        + 0.15
        * player_pool["shooting_score"]
        + 0.10
        * player_pool["rebounding_score"]
        + 0.15
        * player_pool["defense_score"]
        + 0.25
        * player_pool["impact_score"]
    )

    player_pool["reliability_weight"] = (
        1.0
        - np.exp(
            -player_pool[
                "total_minutes"
            ].fillna(0.0)
            / 750.0
        )
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    player_pool[
        "reliability_adjusted_score"
    ] = (
        50.0
        + (
            player_pool["raw_overall_score"]
            - 50.0
        )
        * player_pool["reliability_weight"]
    )

    player_pool["roster_value_score"] = (
        player_pool[
            "reliability_adjusted_score"
        ]
        + 0.10
        * (
            player_pool["availability_score"]
            - 50.0
        )
    ).clip(
        lower=0.0,
        upper=100.0,
    )

    player_pool[
        "roster_value_percentile"
    ] = percentile_score(
        player_pool["roster_value_score"],
        higher_is_better=True,
    )

    player_pool["main_pool_eligible"] = (
        (
            player_pool["games_played"]
            >= MIN_GAMES_FOR_MAIN_POOL
        )
        & (
            player_pool["minutes_per_game"]
            >= MIN_MINUTES_PER_GAME_FOR_MAIN_POOL
        )
    )

    player_pool["confidence_tier"] = (
        player_pool["total_minutes"]
        .fillna(0.0)
        .apply(assign_confidence_tier)
    )

    player_pool["value_tier"] = (
        player_pool["roster_value_percentile"]
        .apply(assign_value_tier)
    )

    player_pool = assign_skill_labels(
        player_pool
    )

    score_columns = [
        "roster_value_score",
        "roster_value_percentile",
        "raw_overall_score",
        "reliability_adjusted_score",
        "reliability_weight",
        "scoring_score",
        "playmaking_score",
        "shooting_score",
        "rebounding_score",
        "defense_score",
        "impact_score",
        "workload_score",
    ]

    player_pool[score_columns] = (
        player_pool[score_columns].round(3)
    )

    season_slug = str(
        player_pool["season"].iloc[0]
    ).replace(
        "-",
        "_",
    )

    parquet_path = (
        PROCESSED_DIRECTORY
        / f"player_skill_profiles_{season_slug}.parquet"
    )

    csv_path = (
        PROCESSED_DIRECTORY
        / f"player_skill_profiles_{season_slug}.csv"
    )

    player_pool.to_parquet(
        parquet_path,
        index=False,
    )

    player_pool.to_csv(
        csv_path,
        index=False,
    )

    eligible_pool = (
        player_pool.loc[
            player_pool["main_pool_eligible"]
        ]
        .sort_values(
            "roster_value_score",
            ascending=False,
        )
    )

    print("PLAYER SKILL PROFILES CREATED")
    print(f"Source: {source_path}")
    print(f"Players: {len(player_pool):,}")

    print(
        "Main optimizer pool: "
        f"{int(player_pool['main_pool_eligible'].sum()):,}"
    )

    print(
        "Limited-sample players: "
        f"{int(player_pool['small_sample_flag'].sum()):,}"
    )

    print()
    print("SAVED FILES")
    print(parquet_path)
    print(csv_path)
    print()

    print(
        "TOP 20 MAIN-POOL PLAYERS "
        "BY ROSTER VALUE"
    )

    display_columns = [
        "player_name",
        "team_abbreviation",
        "games_played",
        "minutes_per_game",
        "roster_value_score",
        "roster_value_percentile",
        "value_tier",
        "confidence_tier",
        "primary_skill",
        "secondary_skill",
    ]

    print(
        eligible_pool[display_columns]
        .head(20)
        .to_string(index=False)
    )

    example = player_pool.loc[
        player_pool["player_name"]
        == "Toby Okani",
        [
            "player_name",
            "games_played",
            "total_minutes",
            "raw_overall_score",
            "reliability_weight",
            "reliability_adjusted_score",
            "roster_value_score",
            "confidence_tier",
            "main_pool_eligible",
        ],
    ]

    if not example.empty:
        print()
        print(
            "SMALL-SAMPLE RELIABILITY EXAMPLE"
        )
        print(
            example.to_string(index=False)
        )


if __name__ == "__main__":
    main()