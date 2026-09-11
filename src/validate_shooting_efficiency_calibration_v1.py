from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from single_game_simulator_v1 import (  # noqa: E402
    SHOOTING_CALIBRATION_VERSION,
    scoring_components,
)

VALIDATOR_VERSION = (
    "shooting-efficiency-calibration-validator-v1-2026-08-10"
)
EXPECTED_CALIBRATION_VERSION = (
    "shooting-efficiency-calibration-v1-2026-08-10"
)
REPORT_PATH = (
    OUTPUTS / "shooting_efficiency_calibration_validation_v1.json"
)


def pct(made: int, attempted: int) -> float:
    if attempted <= 0:
        return 0.0
    return made / attempted


def run_validation(seed: int = 20260810) -> dict:
    rng = random.Random(seed)
    positions = (
        "PG/SG",
        "SG/SF",
        "SF/PF",
        "PF/C",
        "C",
    )
    ratings = (68.0, 74.0, 80.0, 86.0, 92.0, 96.0)

    aggregate = {
        "fgm": 0,
        "fga": 0,
        "3pm": 0,
        "3pa": 0,
        "ftm": 0,
        "fta": 0,
    }
    buckets: list[dict] = []

    for position in positions:
        for rating in ratings:
            bucket = {
                "fgm": 0,
                "fga": 0,
                "3pm": 0,
                "3pa": 0,
                "ftm": 0,
                "fta": 0,
            }
            for _ in range(1200):
                expected_points = 20.0 + (rating - 80.0) * 0.4
                points = max(
                    0,
                    int(round(rng.gauss(expected_points, 5.0))),
                )
                (
                    fgm,
                    fga,
                    three_made,
                    three_attempted,
                    ftm,
                    fta,
                ) = scoring_components(
                    rng,
                    points=points,
                    position=position,
                    overall_rating=rating,
                )
                values = {
                    "fgm": fgm,
                    "fga": fga,
                    "3pm": three_made,
                    "3pa": three_attempted,
                    "ftm": ftm,
                    "fta": fta,
                }
                for key, value in values.items():
                    bucket[key] += value
                    aggregate[key] += value

            buckets.append(
                {
                    "position": position,
                    "rating": rating,
                    "FG%": round(100.0 * pct(bucket["fgm"], bucket["fga"]), 1),
                    "3P%": round(100.0 * pct(bucket["3pm"], bucket["3pa"]), 1),
                    "FT%": round(100.0 * pct(bucket["ftm"], bucket["fta"]), 1),
                }
            )

    aggregate_fg = 100.0 * pct(aggregate["fgm"], aggregate["fga"])
    aggregate_three = 100.0 * pct(aggregate["3pm"], aggregate["3pa"])
    aggregate_ft = 100.0 * pct(aggregate["ftm"], aggregate["fta"])

    guards = [row for row in buckets if row["position"] == "PG/SG"]
    centers = [row for row in buckets if row["position"] == "C"]

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "shooting-efficiency-calibration-validator-v1-2026-08-10"
        ),
        "calibration_version_is_current": (
            SHOOTING_CALIBRATION_VERSION
            == EXPECTED_CALIBRATION_VERSION
        ),
        "aggregate_fg_percentage_is_plausible": 45.0 <= aggregate_fg <= 53.0,
        "aggregate_three_percentage_is_plausible": 33.0 <= aggregate_three <= 41.0,
        "aggregate_free_throw_percentage_is_plausible": 74.0 <= aggregate_ft <= 84.0,
        "no_representative_bucket_has_55_percent_three_point_rate": all(
            row["3P%"] < 46.0 for row in buckets
        ),
        "no_representative_bucket_has_65_percent_field_goal_rate": all(
            row["FG%"] < 62.0 for row in buckets
        ),
        "higher_rated_guards_are_more_efficient": guards[-1]["FG%"] > guards[0]["FG%"],
        "higher_rated_centers_are_more_efficient": centers[-1]["FG%"] > centers[0]["FG%"],
        "made_attempt_relationships_are_valid": (
            aggregate["fgm"] <= aggregate["fga"]
            and aggregate["3pm"] <= aggregate["3pa"]
            and aggregate["ftm"] <= aggregate["fta"]
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "calibration_version": SHOOTING_CALIBRATION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "aggregate_FG%": round(aggregate_fg, 1),
            "aggregate_3P%": round(aggregate_three, 1),
            "aggregate_FT%": round(aggregate_ft, 1),
            "representative_buckets": buckets,
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Shooting efficiency calibration failed: "
            + ", ".join(failed)
        )
    print("\nSHOOTING EFFICIENCY CALIBRATION V1 VALIDATION PASSED")
    return report


def main() -> int:
    run_validation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
