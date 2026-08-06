from pathlib import Path

import duckdb


SOURCE_DATABASE = Path(
    r"C:\Users\klima\Python Projects\Projects"
    r"\NBA_Front_Office_Decision_Center"
    r"\database\nba_front_office.duckdb"
)


def main() -> None:
    """Audit the latest-season player pool used by the roster optimizer."""

    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "The source NBA database could not be found at:\n"
            f"{SOURCE_DATABASE}"
        )

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

        print("LATEST SEASON")
        print(latest_season)
        print()

        season_summary = connection.execute(
            """
            SELECT
                COUNT(*) AS player_rows,
                COUNT(DISTINCT player_id) AS unique_players,
                COUNT(DISTINCT team_id) AS unique_teams,
                SUM(
                    CASE
                        WHEN COALESCE(base_team_count, 1) > 1 THEN 1
                        ELSE 0
                    END
                ) AS multi_team_players,
                SUM(
                    CASE
                        WHEN has_base_stats AND has_advanced_stats THEN 1
                        ELSE 0
                    END
                ) AS complete_player_rows
            FROM fact_player_season
            WHERE season = ?
            """,
            [latest_season],
        ).fetchdf()

        print("SEASON SUMMARY")
        print(season_summary.to_string(index=False))
        print()

        team_counts = connection.execute(
            """
            SELECT
                team_abbreviation,
                COUNT(*) AS player_rows,
                SUM(
                    CASE
                        WHEN base_gp >= 5 THEN 1
                        ELSE 0
                    END
                ) AS players_with_5_games,
                ROUND(AVG(age), 2) AS average_age
            FROM fact_player_season
            WHERE season = ?
            GROUP BY team_abbreviation
            ORDER BY player_rows DESC, team_abbreviation
            """,
            [latest_season],
        ).fetchdf()

        print("PLAYER COUNTS BY TEAM")
        print(team_counts.to_string(index=False))
        print()

        multi_team_players = connection.execute(
            """
            SELECT
                player_name,
                team_abbreviation,
                base_team_count,
                base_gp,
                ROUND(base_min / NULLIF(base_gp, 0), 2) AS minutes_per_game,
                ROUND(base_pts / NULLIF(base_gp, 0), 2) AS points_per_game
            FROM fact_player_season
            WHERE season = ?
              AND COALESCE(base_team_count, 1) > 1
            ORDER BY base_team_count DESC, player_name
            """,
            [latest_season],
        ).fetchdf()

        print("MULTI-TEAM PLAYER RECORDS")
        if multi_team_players.empty:
            print("No multi-team player records were found.")
        else:
            print(multi_team_players.to_string(index=False))

    finally:
        connection.close()

    print()
    print("Current player-pool audit completed successfully.")


if __name__ == "__main__":
    main()