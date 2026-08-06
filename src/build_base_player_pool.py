from pathlib import Path

import duckdb
import pandas as pd


SOURCE_DATABASE = Path(
    r"C:\Users\klima\Python Projects\Projects"
    r"\NBA_Front_Office_Decision_Center"
    r"\database\nba_front_office.duckdb"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "processed"


def main() -> None:
    """Build an optimizer-ready player pool from the latest NBA season."""

    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "The source NBA database could not be found at:\n"
            f"{SOURCE_DATABASE}"
        )

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(
        database=str(SOURCE_DATABASE),
        read_only=True,
    )

    try:
        latest_season = connection.execute(
            """
            SELECT season
            FROM dim_season
            ORDER BY season DESC
            LIMIT 1
            """
        ).fetchone()[0]

        player_pool = connection.execute(
            """
            SELECT
                season,
                player_id,
                player_name,
                team_id,
                team_abbreviation,
                age,

                COALESCE(base_team_count, 1) AS teams_played_for,
                base_gp AS games_played,
                base_min AS total_minutes,

                ROUND(base_min / NULLIF(base_gp, 0), 3)
                    AS minutes_per_game,

                ROUND(base_pts / NULLIF(base_gp, 0), 3)
                    AS points_per_game,

                ROUND(base_ast / NULLIF(base_gp, 0), 3)
                    AS assists_per_game,

                ROUND(base_reb / NULLIF(base_gp, 0), 3)
                    AS rebounds_per_game,

                ROUND(base_oreb / NULLIF(base_gp, 0), 3)
                    AS offensive_rebounds_per_game,

                ROUND(base_dreb / NULLIF(base_gp, 0), 3)
                    AS defensive_rebounds_per_game,

                ROUND(base_stl / NULLIF(base_gp, 0), 3)
                    AS steals_per_game,

                ROUND(base_blk / NULLIF(base_gp, 0), 3)
                    AS blocks_per_game,

                ROUND(base_tov / NULLIF(base_gp, 0), 3)
                    AS turnovers_per_game,

                ROUND(base_fg3m / NULLIF(base_gp, 0), 3)
                    AS threes_made_per_game,

                ROUND(base_fg3a / NULLIF(base_gp, 0), 3)
                    AS threes_attempted_per_game,

                base_fg_pct AS field_goal_percentage,
                base_fg3_pct AS three_point_percentage,
                base_ft_pct AS free_throw_percentage,

                advanced_off_rating AS offensive_rating,
                advanced_def_rating AS defensive_rating,
                advanced_net_rating AS net_rating,

                advanced_ast_pct AS assist_percentage,
                advanced_ast_to AS assist_to_turnover_ratio,
                advanced_oreb_pct AS offensive_rebound_percentage,
                advanced_dreb_pct AS defensive_rebound_percentage,
                advanced_reb_pct AS total_rebound_percentage,
                advanced_tm_tov_pct AS turnover_percentage,
                advanced_efg_pct AS effective_field_goal_percentage,
                advanced_ts_pct AS true_shooting_percentage,
                advanced_usg_pct AS usage_percentage,
                advanced_pace AS pace,
                advanced_pie AS player_impact_estimate,
                advanced_poss AS possessions,

                ROUND(
                    LEAST(base_gp / 82.0, 1.0),
                    4
                ) AS availability_rate,

                CASE
                    WHEN COALESCE(base_team_count, 1) > 1
                    THEN TRUE
                    ELSE FALSE
                END AS changed_teams,

                CASE
                    WHEN base_gp < 10
                      OR base_min / NULLIF(base_gp, 0) < 8
                    THEN TRUE
                    ELSE FALSE
                END AS small_sample_flag

            FROM fact_player_season

            WHERE season = ?
              AND has_base_stats = TRUE
              AND has_advanced_stats = TRUE

            ORDER BY
                minutes_per_game DESC,
                player_name
            """,
            [latest_season],
        ).fetchdf()

    finally:
        connection.close()

    if player_pool.empty:
        raise ValueError("The player pool query returned no players.")

    if player_pool["player_id"].duplicated().any():
        duplicate_players = player_pool.loc[
            player_pool["player_id"].duplicated(keep=False),
            ["player_id", "player_name"],
        ]

        raise ValueError(
            "Duplicate player IDs were found:\n"
            f"{duplicate_players.to_string(index=False)}"
        )

    required_columns = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "games_played",
        "minutes_per_game",
    ]

    null_counts = player_pool[required_columns].isna().sum()

    if null_counts.any():
        raise ValueError(
            "Required player-pool fields contain missing values:\n"
            f"{null_counts[null_counts > 0]}"
        )

    season_slug = latest_season.replace("-", "_")

    parquet_path = (
        OUTPUT_DIRECTORY /
        f"base_player_pool_{season_slug}.parquet"
    )

    csv_path = (
        OUTPUT_DIRECTORY /
        f"base_player_pool_{season_slug}.csv"
    )

    player_pool.to_parquet(parquet_path, index=False)
    player_pool.to_csv(csv_path, index=False)

    print("BASE PLAYER POOL CREATED")
    print(f"Season: {latest_season}")
    print(f"Players: {len(player_pool):,}")
    print(f"Teams: {player_pool['team_abbreviation'].nunique()}")
    print(
        "Multi-team players: "
        f"{int(player_pool['changed_teams'].sum()):,}"
    )
    print(
        "Small-sample players: "
        f"{int(player_pool['small_sample_flag'].sum()):,}"
    )
    print()

    print("SAVED FILES")
    print(parquet_path)
    print(csv_path)
    print()

    print("TOP 15 PLAYERS BY MINUTES PER GAME")
    print(
        player_pool[
            [
                "player_name",
                "team_abbreviation",
                "games_played",
                "minutes_per_game",
                "points_per_game",
                "assists_per_game",
                "rebounds_per_game",
                "true_shooting_percentage",
                "net_rating",
                "player_impact_estimate",
            ]
        ]
        .head(15)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
