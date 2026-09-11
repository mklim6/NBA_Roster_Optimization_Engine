from __future__ import annotations

from typing import Any


FRANCHISE_PLAYER_STATS_VERSION = (
    "franchise-player-stats-v1-2026-08-10"
)


def _percentage(made: int, attempted: int) -> float:
    if attempted <= 0:
        return 0.0
    return round(100.0 * made / attempted, 1)


def _effective_field_goal_percentage(
    field_goals_made: int,
    three_pointers_made: int,
    field_goals_attempted: int,
) -> float:
    if field_goals_attempted <= 0:
        return 0.0
    return round(
        100.0
        * (
            field_goals_made
            + 0.5 * three_pointers_made
        )
        / field_goals_attempted,
        1,
    )


def _true_shooting_percentage(
    points: int,
    field_goals_attempted: int,
    free_throws_attempted: int,
) -> float:
    denominator = 2.0 * (
        field_goals_attempted
        + 0.44 * free_throws_attempted
    )
    if denominator <= 0.0:
        return 0.0
    return round(100.0 * points / denominator, 1)


def regular_season_player_rows(
    state: Any,
    *,
    minimum_games: int = 1,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return NBA-style regular-season player leader rows.

    Counting and shooting-volume fields are per-game averages.
    Shooting percentages are calculated from season totals so they are
    weighted correctly instead of averaging game-level percentages.
    """
    rows: list[dict[str, Any]] = []

    for player_id, totals in state.player_season_totals.items():
        games = int(totals.games_played)
        if games < int(minimum_games):
            continue

        player = state.players.get(player_id)
        if player is None:
            continue

        field_goals_made = int(totals.field_goals_made)
        field_goals_attempted = int(totals.field_goals_attempted)
        three_pointers_made = int(totals.three_pointers_made)
        three_pointers_attempted = int(totals.three_pointers_attempted)
        free_throws_made = int(totals.free_throws_made)
        free_throws_attempted = int(totals.free_throws_attempted)

        rows.append(
            {
                "Player": player.player_name,
                "Team": player.team_abbreviation,
                "Pos": player.position,
                "GP": games,
                "GS": int(totals.games_started),
                "MIN": round(float(totals.minutes) / games, 1),
                "PTS": round(float(totals.points) / games, 1),
                "REB": round(float(totals.rebounds) / games, 1),
                "AST": round(float(totals.assists) / games, 1),
                "STL": round(float(totals.steals) / games, 1),
                "BLK": round(float(totals.blocks) / games, 1),
                "TO": round(float(totals.turnovers) / games, 1),
                "PF": round(float(totals.fouls) / games, 1),
                "FGM": round(field_goals_made / games, 1),
                "FGA": round(field_goals_attempted / games, 1),
                "FG%": _percentage(
                    field_goals_made,
                    field_goals_attempted,
                ),
                "3PM": round(three_pointers_made / games, 1),
                "3PA": round(three_pointers_attempted / games, 1),
                "3P%": _percentage(
                    three_pointers_made,
                    three_pointers_attempted,
                ),
                "FTM": round(free_throws_made / games, 1),
                "FTA": round(free_throws_attempted / games, 1),
                "FT%": _percentage(
                    free_throws_made,
                    free_throws_attempted,
                ),
                "eFG%": _effective_field_goal_percentage(
                    field_goals_made,
                    three_pointers_made,
                    field_goals_attempted,
                ),
                "TS%": _true_shooting_percentage(
                    int(totals.points),
                    field_goals_attempted,
                    free_throws_attempted,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row["PTS"]),
            -float(row["AST"]),
            str(row["Player"]),
        )
    )
    return rows[: int(limit)]
