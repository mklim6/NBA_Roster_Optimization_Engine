from __future__ import annotations

import json
import math
import statistics
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

from regular_season_simulation_controller_v1 import (
    SimulationScope,
    build_installed_state,
    simulate_regular_season_scope,
)
from simulation_league_alignment_v1 import apply_nba_team_alignment
from simulation_league_state_v1 import validate_simulation_league_state
from simulation_player_stat_fingerprints_v3 import (
    EMPIRICAL_SOURCE,
    FINGERPRINT_VERSION,
    build_player_stat_fingerprint,
    empirical_player_prior,
    load_empirical_player_priors,
)
from single_game_simulator_v1 import PLAYER_STAT_FINGERPRINT_VERSION

VALIDATOR_VERSION = "player-statistical-fingerprint-validator-v3-2026-08-10"
EXPECTED_VERSION = "player-statistical-fingerprint-v3-empirical-2026-08-10"
REPORT_PATH = OUTPUTS / "player_statistical_fingerprint_validation_v3.json"


def pct(made: float, attempted: float) -> float:
    return made / attempted if attempted > 0 else 0.0


def per36(value: float, minutes: float) -> float:
    return value * 36.0 / minutes if minutes > 0 else 0.0


def correlation(xs: Iterable[float], ys: Iterable[float]) -> float:
    x, y = list(xs), list(ys)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    mx, my = statistics.fmean(x), statistics.fmean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return numerator / (dx * dy) if dx > 0 and dy > 0 else 0.0


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return ordered[lo]
    w = index - lo
    return ordered[lo] * (1.0 - w) + ordered[hi] * w


def find_player_id(state: Any, *names: str) -> str | None:
    wanted = set(names)
    return next(
        (player_id for player_id, player in state.players.items() if player.player_name in wanted),
        None,
    )


def run_validation(seed: int = 20260810) -> dict[str, Any]:
    priors = load_empirical_player_priors()
    state = build_installed_state(seed=seed)
    state.settings = replace(state.settings, injuries_enabled=False)
    apply_nba_team_alignment(state)

    curry_id = find_player_id(state, "Stephen Curry")
    giannis_id = find_player_id(state, "Giannis Antetokounmpo")
    jokic_id = find_player_id(state, "Nikola Jokić", "Nikola Jokic")
    luka_id = find_player_id(state, "Luka Dončić", "Luka Doncic")
    sga_id = find_player_id(state, "Shai Gilgeous-Alexander")

    pre_examples = {}
    for label, player_id in {
        "Curry": curry_id,
        "Giannis": giannis_id,
        "Jokic": jokic_id,
        "Luka": luka_id,
        "SGA": sga_id,
    }.items():
        if player_id:
            prior = empirical_player_prior(player_id)
            fp = build_player_stat_fingerprint(state.players[player_id])
            pre_examples[label] = {
                "player_id": player_id,
                "empirical_seasons": list(prior.seasons) if prior else [],
                "empirical_3PA36": round(prior.three_attempts_per_36, 2) if prior else None,
                "fingerprint_3PA36": round(fp.three_attempts_per_36, 2),
                "empirical_FTA36": round(prior.free_throw_attempts_per_36, 2) if prior else None,
                "fingerprint_FTA36": round(fp.free_throw_attempts_per_36, 2),
                "fingerprint_3P%": round(100.0 * fp.three_point_percentage, 1),
                "fingerprint_2P%": round(100.0 * fp.two_point_percentage, 1),
                "fingerprint_FT%": round(100.0 * fp.free_throw_percentage, 1),
                "fingerprint_AST36": round(fp.assists_per_36, 2),
                "fingerprint_PF36": round(fp.fouls_per_36, 2),
            }

    state, simulation = simulate_regular_season_scope(
        state,
        scope=SimulationScope.REMAINDER,
    )
    validate_simulation_league_state(state)

    rows = []
    for player_id, player in state.players.items():
        totals = state.player_season_totals[player_id]
        if totals.games_played < 58 or totals.minutes < 1200.0:
            continue
        fp = build_player_stat_fingerprint(player)
        rows.append({
            "player_id": player_id,
            "player": player.player_name,
            "expected_3PA36": fp.three_attempts_per_36,
            "actual_3PA36": per36(totals.three_pointers_attempted, totals.minutes),
            "expected_FTA36": fp.free_throw_attempts_per_36,
            "actual_FTA36": per36(totals.free_throws_attempted, totals.minutes),
            "expected_AST36": fp.assists_per_36,
            "actual_AST36": per36(totals.assists, totals.minutes),
            "expected_PF36": fp.fouls_per_36,
            "actual_PF36": per36(totals.fouls, totals.minutes),
            "expected_3P": fp.three_point_percentage,
            "actual_3P": pct(totals.three_pointers_made, totals.three_pointers_attempted),
            "expected_FT": fp.free_throw_percentage,
            "actual_FT": pct(totals.free_throws_made, totals.free_throws_attempted),
            "three_attempts": totals.three_pointers_attempted,
            "ft_attempts": totals.free_throws_attempted,
            "GP": totals.games_played,
            "PPG": totals.points / totals.games_played if totals.games_played else 0.0,
        })

    aggregate_fgm = sum(t.field_goals_made for t in state.player_season_totals.values())
    aggregate_fga = sum(t.field_goals_attempted for t in state.player_season_totals.values())
    aggregate_3pm = sum(t.three_pointers_made for t in state.player_season_totals.values())
    aggregate_3pa = sum(t.three_pointers_attempted for t in state.player_season_totals.values())
    aggregate_ftm = sum(t.free_throws_made for t in state.player_season_totals.values())
    aggregate_fta = sum(t.free_throws_attempted for t in state.player_season_totals.values())

    corr_3pa = correlation(
        [row["expected_3PA36"] for row in rows],
        [row["actual_3PA36"] for row in rows],
    )
    corr_fta = correlation(
        [row["expected_FTA36"] for row in rows],
        [row["actual_FTA36"] for row in rows],
    )
    corr_ast = correlation(
        [row["expected_AST36"] for row in rows],
        [row["actual_AST36"] for row in rows],
    )
    corr_pf = correlation(
        [row["expected_PF36"] for row in rows],
        [row["actual_PF36"] for row in rows],
    )
    three_accuracy_rows = [row for row in rows if row["three_attempts"] >= 100]
    ft_accuracy_rows = [row for row in rows if row["ft_attempts"] >= 100]
    corr_3p = correlation(
        [row["expected_3P"] for row in three_accuracy_rows],
        [row["actual_3P"] for row in three_accuracy_rows],
    )
    corr_ft = correlation(
        [row["expected_FT"] for row in ft_accuracy_rows],
        [row["actual_FT"] for row in ft_accuracy_rows],
    )

    curry_fp = pre_examples.get("Curry", {})
    giannis_fp = pre_examples.get("Giannis", {})
    jokic_fp = pre_examples.get("Jokic", {})

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-10"),
        "fingerprint_v3_is_active": (
            FINGERPRINT_VERSION == EXPECTED_VERSION
            and PLAYER_STAT_FINGERPRINT_VERSION == EXPECTED_VERSION
        ),
        "empirical_source_exists": EMPIRICAL_SOURCE.exists(),
        "empirical_prior_pool_is_large": len(priors) >= 350,
        "full_season_simulates_1230_games": int(getattr(simulation, "games_simulated", 0)) == 1230,
        "qualified_pool_is_large": len(rows) >= 250,
        "curry_has_high_volume_empirical_three_prior": curry_fp.get("fingerprint_3PA36", 0.0) >= 8.5,
        "giannis_has_low_volume_empirical_three_prior": giannis_fp.get("fingerprint_3PA36", 99.0) <= 4.0,
        "curry_giannis_three_volume_identity_is_separated": (
            curry_fp.get("fingerprint_3PA36", 0.0) - giannis_fp.get("fingerprint_3PA36", 0.0) >= 4.5
        ),
        "jokic_playmaking_identity_is_elite": jokic_fp.get("fingerprint_AST36", 0.0) >= 7.5,
        "three_volume_tracks_fingerprint": corr_3pa >= 0.76,
        "free_throw_volume_tracks_fingerprint": corr_fta >= 0.62,
        "assist_volume_tracks_fingerprint": corr_ast >= 0.68,
        "foul_volume_tracks_fingerprint": corr_pf >= 0.45,
        "three_accuracy_tracks_fingerprint": corr_3p >= 0.35,
        "free_throw_accuracy_tracks_fingerprint": corr_ft >= 0.35,
        "three_volume_has_real_identity_spread": (
            quantile([row["actual_3PA36"] for row in rows], 0.90)
            - quantile([row["actual_3PA36"] for row in rows], 0.10)
            >= 4.5
        ),
        "aggregate_fg_is_plausible": 0.44 <= pct(aggregate_fgm, aggregate_fga) <= 0.54,
        "aggregate_three_is_plausible": 0.32 <= pct(aggregate_3pm, aggregate_3pa) <= 0.41,
        "aggregate_ft_is_plausible": 0.70 <= pct(aggregate_ftm, aggregate_fta) <= 0.85,
    }
    failed = [name for name, passed in checks.items() if not passed]

    post_examples = []
    example_ids = {value for value in [curry_id, giannis_id, jokic_id, luka_id, sga_id] if value}
    for row in rows:
        if row["player_id"] in example_ids:
            post_examples.append({
                "player": row["player"],
                "GP": row["GP"],
                "PPG": round(row["PPG"], 2),
                "3PA36_prior": round(row["expected_3PA36"], 2),
                "3PA36_actual": round(row["actual_3PA36"], 2),
                "FTA36_prior": round(row["expected_FTA36"], 2),
                "FTA36_actual": round(row["actual_FTA36"], 2),
                "AST36_prior": round(row["expected_AST36"], 2),
                "AST36_actual": round(row["actual_AST36"], 2),
                "PF36_prior": round(row["expected_PF36"], 2),
                "PF36_actual": round(row["actual_PF36"], 2),
                "3P%": round(100.0 * row["actual_3P"], 1),
                "FT%": round(100.0 * row["actual_FT"], 1),
            })

    report = {
        "script": VALIDATOR_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "empirical_source": str(EMPIRICAL_SOURCE),
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "empirical_player_priors": len(priors),
            "games_simulated": int(getattr(simulation, "games_simulated", 0)),
            "qualified_players": len(rows),
            "correlations": {
                "3PA36": round(corr_3pa, 3),
                "FTA36": round(corr_fta, 3),
                "AST36": round(corr_ast, 3),
                "PF36": round(corr_pf, 3),
                "3P%": round(corr_3p, 3),
                "FT%": round(corr_ft, 3),
            },
            "aggregate_FG%": round(100.0 * pct(aggregate_fgm, aggregate_fga), 1),
            "aggregate_3P%": round(100.0 * pct(aggregate_3pm, aggregate_3pa), 1),
            "aggregate_FT%": round(100.0 * pct(aggregate_ftm, aggregate_fta), 1),
            "preseason_identity_examples": pre_examples,
            "simulated_identity_examples": post_examples,
        },
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Player Statistical Fingerprint V3 validation failed: "
            + ", ".join(failed)
        )
    print("\nPLAYER STATISTICAL FINGERPRINT V3 VALIDATION PASSED")
    return report


if __name__ == "__main__":
    run_validation()
