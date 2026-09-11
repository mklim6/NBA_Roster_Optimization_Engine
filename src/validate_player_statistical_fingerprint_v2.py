from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    build_installed_state,
    simulate_regular_season_scope,
)
from simulation_league_alignment_v1 import (  # noqa: E402
    apply_nba_team_alignment,
)
from simulation_league_state_v1 import (  # noqa: E402
    validate_simulation_league_state,
)
from simulation_player_stat_fingerprints_v2 import (  # noqa: E402
    FINGERPRINT_VERSION,
    build_player_stat_fingerprint,
)
from single_game_simulator_v1 import (  # noqa: E402
    PLAYER_STAT_FINGERPRINT_VERSION,
)

VALIDATOR_VERSION = "player-statistical-fingerprint-validator-v2.2-2026-09-09"
EXPECTED_FINGERPRINT_VERSION = "player-statistical-fingerprint-v2.1-2026-09-09"
EXPECTED_RUNTIME_VERSION = "player-statistical-fingerprint-v3-empirical-2026-08-10"
REPORT_PATH = OUTPUTS / "player_statistical_fingerprint_validation_v2.json"


def pct(made: float, attempted: float) -> float:
    return made / attempted if attempted > 0 else 0.0


def per36(value: float, minutes: float) -> float:
    return value * 36.0 / minutes if minutes > 0 else 0.0


def correlation(xs: Iterable[float], ys: Iterable[float]) -> float:
    x = list(xs)
    y = list(ys)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    denom_x = math.sqrt(sum((a - mean_x) ** 2 for a in x))
    denom_y = math.sqrt(sum((b - mean_y) ** 2 for b in y))
    if denom_x <= 0 or denom_y <= 0:
        return 0.0
    return numerator / (denom_x * denom_y)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def player_row(state: Any, player_id: str) -> dict[str, Any] | None:
    totals = state.player_season_totals.get(player_id)
    player = state.players.get(player_id)
    if totals is None or player is None:
        return None
    if totals.games_played < 58 or totals.minutes < 1200.0:
        return None

    fp = build_player_stat_fingerprint(player)
    actual = {
        "3PA36": per36(totals.three_pointers_attempted, totals.minutes),
        "FTA36": per36(totals.free_throws_attempted, totals.minutes),
        "REB36": per36(totals.rebounds, totals.minutes),
        "AST36": per36(totals.assists, totals.minutes),
        "STL36": per36(totals.steals, totals.minutes),
        "BLK36": per36(totals.blocks, totals.minutes),
        "TO36": per36(totals.turnovers, totals.minutes),
        "PF36": per36(totals.fouls, totals.minutes),
        "3P%": pct(totals.three_pointers_made, totals.three_pointers_attempted),
        "FT%": pct(totals.free_throws_made, totals.free_throws_attempted),
        "FG%": pct(totals.field_goals_made, totals.field_goals_attempted),
    }
    expected = {
        "3PA36": fp.three_attempts_per_36,
        "FTA36": fp.free_throw_attempts_per_36,
        "REB36": fp.rebounds_per_36,
        "AST36": fp.assists_per_36,
        "STL36": fp.steals_per_36,
        "BLK36": fp.blocks_per_36,
        "TO36": fp.turnovers_per_36,
        "PF36": fp.fouls_per_36,
        "3P%": fp.three_point_percentage,
        "FT%": fp.free_throw_percentage,
    }
    return {
        "player_id": player_id,
        "player": player.player_name,
        "team": player.team_abbreviation,
        "position": player.position,
        "games": totals.games_played,
        "minutes": round(totals.minutes / totals.games_played, 2),
        "points": round(totals.points / totals.games_played, 2),
        "actual": actual,
        "expected": expected,
        "three_attempts": totals.three_pointers_attempted,
        "free_throw_attempts": totals.free_throws_attempted,
    }


def run_validation(seed: int = 20260810) -> dict[str, Any]:
    state = build_installed_state(seed=seed)
    state.settings = replace(state.settings, injuries_enabled=False)
    apply_nba_team_alignment(state)
    state, simulation = simulate_regular_season_scope(
        state,
        scope=SimulationScope.REMAINDER,
    )
    validate_simulation_league_state(state)

    rows = [
        row
        for player_id in state.players
        if (row := player_row(state, player_id)) is not None
    ]

    def corr(field: str) -> float:
        return correlation(
            [row["expected"][field] for row in rows],
            [row["actual"][field] for row in rows],
        )

    three_accuracy_rows = [row for row in rows if row["three_attempts"] >= 100]
    ft_accuracy_rows = [row for row in rows if row["free_throw_attempts"] >= 100]

    three_accuracy_corr = correlation(
        [row["expected"]["3P%"] for row in three_accuracy_rows],
        [row["actual"]["3P%"] for row in three_accuracy_rows],
    )
    ft_accuracy_corr = correlation(
        [row["expected"]["FT%"] for row in ft_accuracy_rows],
        [row["actual"]["FT%"] for row in ft_accuracy_rows],
    )

    three_percentages = [row["actual"]["3P%"] for row in three_accuracy_rows]
    ft_percentages = [row["actual"]["FT%"] for row in ft_accuracy_rows]
    three_volumes = [row["actual"]["3PA36"] for row in rows]
    ft_volumes = [row["actual"]["FTA36"] for row in rows]

    aggregate = {
        "fgm": sum(t.field_goals_made for t in state.player_season_totals.values()),
        "fga": sum(t.field_goals_attempted for t in state.player_season_totals.values()),
        "3pm": sum(t.three_pointers_made for t in state.player_season_totals.values()),
        "3pa": sum(t.three_pointers_attempted for t in state.player_season_totals.values()),
        "ftm": sum(t.free_throws_made for t in state.player_season_totals.values()),
        "fta": sum(t.free_throws_attempted for t in state.player_season_totals.values()),
    }
    aggregate_fg = pct(aggregate["fgm"], aggregate["fga"])
    aggregate_three = pct(aggregate["3pm"], aggregate["3pa"])
    aggregate_ft = pct(aggregate["ftm"], aggregate["fta"])

    correlations = {
        "three_attempt_volume": corr("3PA36"),
        "free_throw_volume": corr("FTA36"),
        "rebounds": corr("REB36"),
        "assists": corr("AST36"),
        "steals": corr("STL36"),
        "blocks": corr("BLK36"),
        "turnovers": corr("TO36"),
        "fouls": corr("PF36"),
        "three_point_accuracy": three_accuracy_corr,
        "free_throw_accuracy": ft_accuracy_corr,
    }

    names = (
        "Stephen Curry",
        "Nikola Jokić",
        "Nikola Jokic",
        "Luka Dončić",
        "Luka Doncic",
        "Shai Gilgeous-Alexander",
        "Giannis Antetokounmpo",
        "Kawhi Leonard",
    )
    examples: list[dict[str, Any]] = []
    used: set[str] = set()
    for name in names:
        for row in rows:
            if row["player"] == name and row["player_id"] not in used:
                used.add(row["player_id"])
                examples.append(
                    {
                        "player": row["player"],
                        "team": row["team"],
                        "GP": row["games"],
                        "MPG": row["minutes"],
                        "PPG": row["points"],
                        "3PA36_actual": round(row["actual"]["3PA36"], 2),
                        "3PA36_prior": round(row["expected"]["3PA36"], 2),
                        "FTA36_actual": round(row["actual"]["FTA36"], 2),
                        "FTA36_prior": round(row["expected"]["FTA36"], 2),
                        "REB36_actual": round(row["actual"]["REB36"], 2),
                        "AST36_actual": round(row["actual"]["AST36"], 2),
                        "PF36_actual": round(row["actual"]["PF36"], 2),
                        "3P%": round(100.0 * row["actual"]["3P%"], 1),
                        "3P_target": round(100.0 * row["expected"]["3P%"], 1),
                        "FT%": round(100.0 * row["actual"]["FT%"], 1),
                        "FT_target": round(100.0 * row["expected"]["FT%"], 1),
                    }
                )

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION == "player-statistical-fingerprint-validator-v2.2-2026-09-09"
        ),
        "v2_compatibility_layer_and_v3_runtime_are_expected": (
            FINGERPRINT_VERSION == EXPECTED_FINGERPRINT_VERSION
            and PLAYER_STAT_FINGERPRINT_VERSION == EXPECTED_RUNTIME_VERSION
        ),
        "full_season_simulates_1230_games": (
            int(getattr(simulation, "games_simulated", 0)) == 1230
        ),
        "qualified_pool_is_large": len(rows) >= 250,
        "legacy_three_attempt_prior_retains_signal": correlations["three_attempt_volume"] >= 0.45,
        "free_throw_volume_tracks_player_prior": correlations["free_throw_volume"] >= 0.62,
        "rebounding_tracks_player_prior": correlations["rebounds"] >= 0.62,
        "assists_track_player_prior": correlations["assists"] >= 0.62,
        "fouls_track_player_prior": correlations["fouls"] >= 0.42,
        "three_accuracy_tracks_shooting_skill": three_accuracy_corr >= 0.30,
        "free_throw_accuracy_tracks_shooting_skill": ft_accuracy_corr >= 0.30,
        "three_point_distribution_is_not_compressed": (
            len(three_percentages) >= 80
            and statistics.pstdev(three_percentages) >= 0.018
        ),
        "free_throw_distribution_is_not_compressed": (
            len(ft_percentages) >= 80
            and statistics.pstdev(ft_percentages) >= 0.025
        ),
        "three_point_volume_has_real_role_spread": (
            quantile(three_volumes, 0.90) - quantile(three_volumes, 0.10) >= 3.2
        ),
        "free_throw_volume_has_real_role_spread": (
            quantile(ft_volumes, 0.90) - quantile(ft_volumes, 0.10) >= 2.0
        ),
        "aggregate_fg_percentage_is_plausible": 0.44 <= aggregate_fg <= 0.54,
        "aggregate_three_percentage_is_plausible": 0.32 <= aggregate_three <= 0.41,
        "aggregate_free_throw_percentage_is_plausible": 0.70 <= aggregate_ft <= 0.85,
    }
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "script": VALIDATOR_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "games_simulated": int(getattr(simulation, "games_simulated", 0)),
            "qualified_players": len(rows),
            "correlations": {key: round(value, 3) for key, value in correlations.items()},
            "aggregate_FG%": round(100.0 * aggregate_fg, 1),
            "aggregate_3P%": round(100.0 * aggregate_three, 1),
            "aggregate_FT%": round(100.0 * aggregate_ft, 1),
            "3P%_standard_deviation": round(100.0 * statistics.pstdev(three_percentages), 2) if three_percentages else 0.0,
            "FT%_standard_deviation": round(100.0 * statistics.pstdev(ft_percentages), 2) if ft_percentages else 0.0,
            "3PA36_p10": round(quantile(three_volumes, 0.10), 2),
            "3PA36_p90": round(quantile(three_volumes, 0.90), 2),
            "FTA36_p10": round(quantile(ft_volumes, 0.10), 2),
            "FTA36_p90": round(quantile(ft_volumes, 0.90), 2),
            "player_examples": examples,
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Player Statistical Fingerprint V2 validation failed: "
            + ", ".join(failed)
        )
    print("\nPLAYER STATISTICAL FINGERPRINT V2 VALIDATION PASSED")
    return report


def main() -> int:
    run_validation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
