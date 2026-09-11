from __future__ import annotations

import csv
import hashlib
import inspect
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
from single_game_simulator_v1 import (
    ENGINE_VERSION,
    REALISM_CALIBRATION_VERSION,
    POSTSEASON_REALISM_CALIBRATION_VERSION,
    GameSimulationConfig,
    postseason_game_config,
    resolve_game_environment_config,
    scoring_components,
)
from franchise_batch_simulation_audit_v2 import run_batch_simulation_audit

VALIDATOR_VERSION = "game-season-realism-calibration-validator-v1.0.9-2026-08-13"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def numeric(row: dict[str, str], key: str) -> float:
    return float(row.get(key, 0) or 0)


def lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric"]: row for row in rows}


def fake_state(phase: str):
    return type(
        "_PhaseState",
        (),
        {"phase": type("_Phase", (), {"value": phase})()},
    )()


def main() -> int:
    checkpoint = Path(DEFAULT_CHECKPOINT_PATH)
    checkpoint_before = sha(checkpoint)
    tmp = Path(tempfile.mkdtemp(prefix="realism_calibration_v109_"))

    try:
        result = run_batch_simulation_audit(
            runs=2,
            seed_base=2026081390,
            output_root=tmp,
            write_zip=True,
            quiet=False,
        )
        batch_dir = Path(result.output_directory)
        if not batch_dir.is_absolute():
            batch_dir = ROOT / batch_dir

        run_rows = read_csv(batch_dir / "batch_run_summary.csv")
        regular = lookup(read_csv(batch_dir / "batch_regular_season_benchmark.csv"))
        playoffs = lookup(read_csv(batch_dir / "batch_playoff_benchmark.csv"))
        medical = read_csv(batch_dir / "batch_medical_summary.csv")

        def m(table, metric):
            return numeric(table[metric], "simulated_mean")

        reg_ppg = m(regular, "reg_pts_per_team_game")
        reg_fg = m(regular, "reg_fg_pct")
        reg_3p = m(regular, "reg_3p_pct")
        reg_efg = m(regular, "reg_efg_pct")
        reg_ts = m(regular, "reg_ts_pct")
        reg_ft = m(regular, "reg_ft_pct")
        reg_fga = m(regular, "reg_fga_per_team_game")
        reg_3pa = m(regular, "reg_3pa_per_team_game")
        reg_fta = m(regular, "reg_fta_per_team_game")
        reg_ast = m(regular, "reg_ast_per_team_game")
        reg_stl = m(regular, "reg_stl_per_team_game")
        reg_tov = m(regular, "reg_tov_per_team_game")

        po_ppg = m(playoffs, "playoff_pts_per_team_game")
        po_fga = m(playoffs, "playoff_fga_per_team_game")
        po_3pa = m(playoffs, "playoff_3pa_per_team_game")
        po_fta = m(playoffs, "playoff_fta_per_team_game")
        po_fg = m(playoffs, "playoff_fg_pct")
        po_3p = m(playoffs, "playoff_3p_pct")
        po_ft = m(playoffs, "playoff_ft_pct")
        po_efg = m(playoffs, "playoff_efg_pct")
        po_ts = m(playoffs, "playoff_ts_pct")
        po_ast = m(playoffs, "playoff_ast_per_team_game")
        po_stl = m(playoffs, "playoff_stl_per_team_game")
        po_blk = m(playoffs, "playoff_blk_per_team_game")
        po_tov = m(playoffs, "playoff_tov_per_team_game")
        po_pf = m(playoffs, "playoff_pf_per_team_game")

        weighted_error = sum(
            numeric(row, "weighted_error")
            for row in list(regular.values()) + list(playoffs.values())
        )
        max_ppg = max(numeric(row, "top_ppg") for row in run_rows)
        scoring_signature = inspect.signature(scoring_components)

        checks = {
            "validator_version_is_current": VALIDATOR_VERSION == "game-season-realism-calibration-validator-v1.0.9-2026-08-13",
            "engine_api_version_is_preserved": ENGINE_VERSION == "single-game-simulator-v1.6-2026-08-08",
            "regular_calibration_version_is_live": REALISM_CALIBRATION_VERSION == "game-season-realism-calibration-v1-2026-08-13",
            "postseason_calibration_version_is_live": POSTSEASON_REALISM_CALIBRATION_VERSION == "postseason-realism-environment-v1-2026-08-13",
            "scoring_wrapper_accepts_live_profile_kwargs": any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in scoring_signature.parameters.values()
            ),
            "postseason_has_distinct_scoring_environment": 102.0 <= float(postseason_game_config().base_points_per_team) <= 105.0,
            "phase_router_selects_playoff_config": float(resolve_game_environment_config(fake_state("playoffs"), None).base_points_per_team) == float(postseason_game_config().base_points_per_team),
            "phase_router_selects_play_in_config": float(resolve_game_environment_config(fake_state("play_in"), None).base_points_per_team) == float(postseason_game_config().base_points_per_team),
            "phase_router_preserves_regular_default": float(resolve_game_environment_config(fake_state("regular_season"), None).base_points_per_team) == float(GameSimulationConfig().base_points_per_team),
            "explicit_config_still_takes_precedence": float(resolve_game_environment_config(fake_state("playoffs"), GameSimulationConfig(base_points_per_team=111.25)).base_points_per_team) == 111.25,
            "regular_attempt_tuning_is_live": abs(float(GameSimulationConfig().three_attempt_multiplier) - 0.904) < 1e-12 and abs(float(GameSimulationConfig().free_throw_attempt_multiplier) - 0.843) < 1e-12,
            "postseason_fta_tuning_is_live": abs(float(postseason_game_config().free_throw_attempt_multiplier) - 0.862) < 1e-12,
            "two_full_seasons_complete": len(run_rows) == 2 and all(int(float(row["regular_games"])) == 1230 for row in run_rows),
            "regular_team_scoring_is_preserved": 113.5 <= reg_ppg <= 117.5,
            "regular_fg_efficiency_improves": 46.3 <= reg_fg <= 48.2,
            "regular_three_pct_remains_plausible": 34.8 <= reg_3p <= 37.2,
            "regular_efg_is_calibrated": 53.5 <= reg_efg <= 56.0,
            "regular_ts_is_calibrated": 57.1 <= reg_ts <= 59.4,
            "regular_ft_pct_is_repaired": 77.0 <= reg_ft <= 80.5,
            "regular_fga_remains_plausible": 87.0 <= reg_fga <= 91.5,
            "regular_three_volume_remains_plausible": 34.5 <= reg_3pa <= 39.0,
            "regular_fta_is_reduced": 21.5 <= reg_fta <= 25.5,
            "regular_assists_are_reduced": 25.0 <= reg_ast <= 28.0,
            "regular_steals_are_increased": 7.6 <= reg_stl <= 9.3,
            "regular_turnovers_are_increased": 13.5 <= reg_tov <= 15.8,
            "postseason_scoring_environment_is_distinct": 104.0 <= po_ppg <= 112.0,
            "postseason_fga_is_reduced": 82.0 <= po_fga <= 88.8,
            "postseason_three_volume_is_reduced": 31.5 <= po_3pa <= 37.0,
            "postseason_fta_is_reduced": 21.5 <= po_fta <= 27.0,
            "postseason_fg_pct_is_plausible": 43.5 <= po_fg <= 48.0,
            "postseason_three_pct_is_plausible": 32.0 <= po_3p <= 37.5,
            "postseason_ft_pct_is_plausible": 74.0 <= po_ft <= 81.0,
            "postseason_efg_is_calibrated": 50.0 <= po_efg <= 54.8,
            "postseason_ts_is_calibrated": 54.0 <= po_ts <= 59.0,
            "postseason_assists_are_reduced": 21.0 <= po_ast <= 25.8,
            "postseason_steals_are_plausible": 7.0 <= po_stl <= 9.3,
            "postseason_blocks_are_plausible": 4.2 <= po_blk <= 6.2,
            "postseason_turnovers_are_plausible": 13.0 <= po_tov <= 15.9,
            "postseason_fouls_are_increased": 20.0 <= po_pf <= 24.2,
            "star_scoring_remains_realistic": 24.0 <= max_ppg <= 36.0,
            "medical_v2_still_runs_during_batch": len(medical) == 2 and all(numeric(row, "injury_events_total") > 0 for row in medical),
            "combined_benchmark_error_improves_materially": weighted_error < 30.0,
            "checkpoint_hash_still_unchanged": sha(checkpoint) == checkpoint_before == result.checkpoint_sha256,
        }

        print("=" * 112)
        print("GAME / SEASON REALISM CALIBRATION V1.0.9 VALIDATION")
        print("=" * 112)
        for name, passed in checks.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")

        print()
        print("REGULAR-SEASON TWO-RUN MEANS")
        print(f"  PTS {reg_ppg:.3f} | FGA {reg_fga:.3f} | 3PA {reg_3pa:.3f} | FTA {reg_fta:.3f}")
        print(f"  FG {reg_fg:.3f}% | 3P {reg_3p:.3f}% | FT {reg_ft:.3f}% | eFG {reg_efg:.3f}% | TS {reg_ts:.3f}%")
        print(f"  AST {reg_ast:.3f} | STL {reg_stl:.3f} | TOV {reg_tov:.3f}")

        print()
        print("POSTSEASON TWO-RUN MEANS")
        print(f"  PTS {po_ppg:.3f} | FGA {po_fga:.3f} | 3PA {po_3pa:.3f} | FTA {po_fta:.3f}")
        print(f"  FG {po_fg:.3f}% | 3P {po_3p:.3f}% | FT {po_ft:.3f}% | eFG {po_efg:.3f}% | TS {po_ts:.3f}%")
        print(f"  AST {po_ast:.3f} | STL {po_stl:.3f} | BLK {po_blk:.3f} | TOV {po_tov:.3f} | PF {po_pf:.3f}")
        print()
        print("Combined weighted benchmark error:", f"{weighted_error:.3f}", "(V2.1 10-run baseline: 37.137)")

        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise AssertionError("Realism calibration V1.0.9 failed: " + ", ".join(failed))

        print()
        print("GAME / SEASON REALISM CALIBRATION V1.0.9 VALIDATION PASSED")
        print("READ-ONLY CALIBRATION TEST: both seasons ran on deep copies; the durable franchise checkpoint was not modified.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
