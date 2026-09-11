from __future__ import annotations

import importlib.util
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "src" / "audit_player_development_churn_v1.py"


def load():
    spec = importlib.util.spec_from_file_location(
        "_development_churn_audit_v1_validator",
        AUDIT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load development churn audit module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Totals:
    def __init__(
        self,
        gp=70,
        gs=60,
        minutes=2100,
        points=1400,
        rebounds=420,
        assists=350,
        steals=70,
        blocks=35,
        turnovers=140,
        fouls=140,
        fgm=500,
        fga=1050,
        tpm=140,
        tpa=380,
        ftm=260,
        fta=310,
    ):
        self.games_played = gp
        self.games_started = gs
        self.minutes = minutes
        self.points = points
        self.rebounds = rebounds
        self.assists = assists
        self.steals = steals
        self.blocks = blocks
        self.turnovers = turnovers
        self.fouls = fouls
        self.field_goals_made = fgm
        self.field_goals_attempted = fga
        self.three_pointers_made = tpm
        self.three_pointers_attempted = tpa
        self.free_throws_made = ftm
        self.free_throws_attempted = fta


def main() -> int:
    audit = load()

    prior = audit.rate_row(
        Totals(
            gp=68,
            minutes=1836,
            points=1142,
            rebounds=333,
            assists=258,
            fgm=410,
            fga=900,
            tpm=110,
            tpa=310,
            ftm=212,
            fta=250,
        )
    )
    current = audit.rate_row(
        Totals(
            gp=74,
            minutes=2516,
            points=1813,
            rebounds=459,
            assists=451,
            fgm=640,
            fga=1300,
            tpm=185,
            tpa=490,
            ftm=348,
            fta=395,
        )
    )

    row = {
        "prior_gp": prior["gp"],
        "prior_mpg": prior["mpg"],
        "current_gp": current["gp"],
        "current_mpg": current["mpg"],
        "current_ppg": current["ppg"],
        "ppg_delta": current["ppg"] - prior["ppg"],
        "apg_delta": current["apg"] - prior["apg"],
        "rpg_delta": current["rpg"] - prior["rpg"],
        "mpg_delta": current["mpg"] - prior["mpg"],
        "production36_delta": (
            current["production36"] - prior["production36"]
        ),
        "ts_delta": current["ts_pct"] - prior["ts_pct"],
    }
    row["impact_gain"] = (
        row["ppg_delta"]
        + 0.85 * row["rpg_delta"]
        + 1.10 * row["apg_delta"]
        + 0.15 * row["mpg_delta"]
        + 0.08 * row["ts_delta"]
    )

    checks = {
        "audit_version_is_current": (
            audit.AUDIT_VERSION
            == "player-development-league-churn-audit-v1-2026-08-11"
        ),
        "season_parser_works": (
            audit.season_start_year("2030-31") == 2030
        ),
        "age_buckets_work": (
            audit.age_bucket(21) == "19-21"
            and audit.age_bucket(24) == "22-24"
            and audit.age_bucket(27) == "25-27"
            and audit.age_bucket(30) == "28-30"
            and audit.age_bucket(33) == "31-33"
            and audit.age_bucket(34) == "34+"
        ),
        "rate_math_is_finite": all(
            math.isfinite(value)
            for value in prior.values()
        ),
        "real_breakout_is_detected": audit.material_breakout(row),
        "rating_bands_work": (
            audit.classify_rating_delta(5.2) == "+5_or_more"
            and audit.classify_rating_delta(3.2) == "+3_to_4.99"
            and audit.classify_rating_delta(1.2) == "+1_to_2.99"
            and audit.classify_rating_delta(0.2) == "roughly_stable"
            and audit.classify_rating_delta(-1.5) == "-1_to_-2.99"
            and audit.classify_rating_delta(-3.2) == "-3_to_-4.99"
            and audit.classify_rating_delta(-5.2) == "-5_or_worse"
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    print("PLAYER DEVELOPMENT CHURN AUDIT V1 CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    if failed:
        raise AssertionError(
            "Development churn audit validation failed: "
            + ", ".join(failed)
        )

    print()
    print("PLAYER DEVELOPMENT CHURN AUDIT V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
