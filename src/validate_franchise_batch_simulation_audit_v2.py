from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_batch_simulation_audit_v2 import (
    BATCH_AUDIT_VERSION,
    BATCH_SCHEMA_VERSION,
    CHECKPOINT_PATH,
    run_batch_simulation_audit,
)
from franchise_audit_export_v1 import (
    AUDIT_EXPORT_VERSION,
    AUDIT_SCHEMA_VERSION,
)
from regular_season_simulation_controller_v1 import (
    CONTROLLER_VERSION,
)
from simulation_postseason_v1 import (
    POSTSEASON_VERSION,
)

VALIDATOR_VERSION = (
    "franchise-batch-simulation-audit-validator-v2.1-2026-08-13"
)


def sha(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        return list(
            csv.DictReader(handle)
        )


def main() -> int:
    print("=" * 108)
    print(
        "FRANCHISE BATCH SIMULATION AUDIT V2.1 CALIBRATION-GRADE VALIDATION"
    )
    print("=" * 108)

    checkpoint_before = sha(
        CHECKPOINT_PATH
    )
    tmp = Path(
        tempfile.mkdtemp(
            prefix=(
                "franchise_batch_sim_v2_"
            )
        )
    )

    try:
        result = (
            run_batch_simulation_audit(
                runs=2,
                seed_base=2026081390,
                output_root=tmp,
                write_zip=True,
                quiet=False,
            )
        )
        batch_dir = Path(
            result.output_directory
        )
        # The result uses an absolute path for temp output.
        if not batch_dir.is_absolute():
            batch_dir = ROOT / batch_dir

        summary = read_csv(
            batch_dir
            / "batch_run_summary.csv"
        )
        teams = read_csv(
            batch_dir
            / "batch_team_seasons.csv"
        )
        team_agg = read_csv(
            batch_dir
            / "batch_team_aggregate.csv"
        )
        players = read_csv(
            batch_dir
            / "batch_player_seasons.csv"
        )
        player_agg = read_csv(
            batch_dir
            / "batch_player_aggregate.csv"
        )
        playoffs = read_csv(
            batch_dir
            / "batch_playoff_player_seasons.csv"
        )
        flags = read_csv(
            batch_dir
            / "batch_realism_flags.csv"
        )
        medical = read_csv(
            batch_dir
            / "batch_medical_summary.csv"
        )
        regular_benchmark = read_csv(
            batch_dir
            / "batch_regular_season_benchmark.csv"
        )
        playoff_benchmark = read_csv(
            batch_dir
            / "batch_playoff_benchmark.csv"
        )
        priorities = read_csv(
            batch_dir
            / "batch_calibration_priorities.csv"
        )

        checks = {
            "validator_version_is_current": (
                VALIDATOR_VERSION
                == "franchise-batch-simulation-audit-validator-v2.1-2026-08-13"
            ),
            "batch_version_is_current": (
                BATCH_AUDIT_VERSION
                == "franchise-batch-simulation-audit-v2.1-calibration-grade-2026-08-13"
            ),
            "batch_schema_is_current": (
                BATCH_SCHEMA_VERSION
                == "franchise-batch-simulation-schema-v2.1-2026-08-13"
            ),
            "audit_v1_1_dependency_is_live": (
                AUDIT_EXPORT_VERSION
                == "franchise-audit-export-v1.1-2026-08-13"
                and AUDIT_SCHEMA_VERSION
                == "franchise-audit-schema-v1.1-2026-08-13"
            ),
            "regular_season_controller_is_expected": (
                CONTROLLER_VERSION
                == "regular-season-simulation-controller-v1-2026-08-08"
            ),
            "postseason_engine_is_present": bool(
                POSTSEASON_VERSION
            ),
            "two_independent_runs_complete": (
                len(summary) == 2
            ),
            "run_seeds_are_distinct": (
                len(
                    {
                        row["seed"]
                        for row in summary
                    }
                )
                == 2
            ),
            "each_run_has_1230_regular_games": all(
                int(
                    float(
                        row["regular_games"]
                    )
                )
                == 1230
                for row in summary
            ),
            "each_run_crowns_champion": all(
                row["champion"].strip()
                for row in summary
            ),
            "each_run_has_plausible_postseason_game_count": all(
                60
                <= int(
                    float(
                        row[
                            "postseason_games"
                        ]
                    )
                )
                <= 115
                for row in summary
            ),
            "team_seasons_are_30_per_run": (
                len(teams) == 60
            ),
            "team_aggregate_has_all_30_teams": (
                len(team_agg) == 30
            ),
            "player_season_rows_are_populated": (
                len(players) > 500
            ),
            "player_aggregate_is_populated": (
                len(player_agg) > 250
            ),
            "playoff_player_rows_are_populated": (
                len(playoffs) > 100
            ),
            "playoff_rows_have_raw_shooting_totals": (
                bool(playoffs)
                and all(
                    key in playoffs[0]
                    for key in (
                        "field_goals_made",
                        "field_goals_attempted",
                        "three_pointers_made",
                        "three_pointers_attempted",
                        "free_throws_made",
                        "free_throws_attempted",
                        "effective_fg_pct",
                        "true_shooting_pct",
                    )
                )
                and any(
                    float(
                        row.get(
                            "field_goals_attempted",
                            0,
                        )
                        or 0
                    )
                    > 0
                    for row in playoffs
                )
            ),
            "medical_summary_uses_season_games_missed": (
                len(medical) == 2
                and all(
                    float(
                        row[
                            "season_games_missed_total"
                        ]
                    )
                    > 0
                    for row in medical
                )
                and all(
                    float(
                        row[
                            "injury_events_total"
                        ]
                    )
                    > 0
                    for row in medical
                )
            ),
            "regular_benchmark_table_is_complete": (
                len(regular_benchmark) == 15
            ),
            "playoff_benchmark_table_is_complete": (
                len(playoff_benchmark) == 15
            ),
            "benchmark_rows_have_normalized_error": (
                all(
                    row.get(
                        "normalized_error",
                        "",
                    )
                    != ""
                    for row in (
                        regular_benchmark
                        + playoff_benchmark
                    )
                )
            ),
            "calibration_priority_table_exists": (
                priorities is not None
            ),
            "realism_flag_table_is_populated": (
                len(flags) >= 10
            ),
            "batch_zip_exists": (
                Path(result.zip_path).is_file()
                if Path(
                    result.zip_path
                ).is_absolute()
                else (
                    ROOT
                    / result.zip_path
                ).is_file()
            ),
            "checkpoint_hash_still_unchanged": (
                sha(CHECKPOINT_PATH)
                == checkpoint_before
                == result.checkpoint_sha256
            ),
        }

        failed = [
            name
            for name, passed
            in checks.items()
            if not passed
        ]

        for name, passed in checks.items():
            print(
                f"  {name}: "
                f"{'PASS' if passed else 'FAIL'}"
            )

        print()
        print("TWO-RUN SAMPLE")
        for row in summary:
            print(
                "  "
                f"run={row['run']} "
                f"seed={row['seed']} "
                f"champion={row['champion']} "
                f"max/min wins="
                f"{float(row['max_team_wins']):.0f}/"
                f"{float(row['min_team_wins']):.0f} "
                f"PPG="
                f"{float(row['league_team_ppg']):.2f} "
                f"FG="
                f"{float(row['aggregate_fg_pct']):.2f}% "
                f"3P="
                f"{float(row['aggregate_3p_pct']):.2f}% "
                f"FT="
                f"{float(row['aggregate_ft_pct']):.2f}% "
                f"FTA="
                f"{float(row['reg_fta_per_team_game']):.1f} "
                f"PO eFG="
                f"{float(row['playoff_efg_pct']):.2f}%"
            )

        print()
        print("MEDICAL V2 SAMPLE")
        for row in medical:
            print(
                "  "
                f"run={row['run']} "
                f"games_missed="
                f"{float(row['season_games_missed_total']):.0f} "
                f"injury_events="
                f"{float(row['injury_events_total']):.0f}"
            )

        print()
        print("TOP CALIBRATION ITEMS")
        for row in priorities[:8]:
            print(
                "  "
                f"{row['label']}: "
                f"sim={float(row['simulated_mean']):.3f} "
                f"NBA={float(row['benchmark']):.3f} "
                f"delta={float(row['delta']):+.3f} "
                f"{row['status']}"
            )

        if failed:
            raise AssertionError(
                "Batch Simulation Audit V2 "
                "validation failed: "
                + ", ".join(failed)
            )

        print()
        print(
            "FRANCHISE BATCH SIMULATION AUDIT V2.1 CALIBRATION-GRADE VALIDATION PASSED"
        )
        print(
            "READ-ONLY VALIDATION: two full regular seasons and "
            "postseasons were simulated only on deep-copied state. "
            "The durable checkpoint was not modified."
        )
        return 0
    finally:
        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
