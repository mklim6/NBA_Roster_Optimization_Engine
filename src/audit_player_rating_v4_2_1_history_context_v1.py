"""Audit V4.2.1 player ratings against sustained multi-season NBA evidence.

This is a diagnostic script. It does not alter or promote any rating release.

It builds a season-level historical value score from the project's unified
2014-15 through 2025-26 player-season dataset, then compares V4.2.1 OVR against:

- weighted recent-three-season value
- best recent season
- number of recent elite seasons
- number of recent star-caliber seasons
- history depth and minutes

Season value uses the same broad evidence families already used elsewhere in
the project:
    role/minutes availability: 45%
    Player Impact Estimate:   30%
    net rating:                10%
    availability:              15%

Outputs
-------
outputs/player_rating_v4_2_1_history_context_audit_v1.csv
outputs/player_rating_v4_2_1_history_context_validation_v1.csv
outputs/player_rating_v4_2_1_history_context_methodology_v1.json
"""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "player-rating-v4-2-1-history-audit-v1-2026-08-06"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

RATING_CANDIDATES = [
    DATA_DIRECTORY / "player_rating_release_2026_27_v4_2_1.parquet",
    DATA_DIRECTORY / "player_rating_release_2026_27_v4_2_1.csv",
]
HISTORY_CANDIDATES = [
    DATA_DIRECTORY / "unified_player_seasons_2014_15_2025_26.parquet",
    DATA_DIRECTORY / "unified_player_seasons_2014_15_2025_26.csv",
]

AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_2_1_history_context_audit_v1.csv"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_2_1_history_context_validation_v1.csv"
)
METHODOLOGY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "player_rating_v4_2_1_history_context_methodology_v1.json"
)

SEASON_VALUE_WEIGHTS = {
    "history_role_percentile": 0.45,
    "history_pie_percentile": 0.30,
    "history_net_percentile": 0.10,
    "history_availability_percentile": 0.15,
}

RECENT_SEASON_WEIGHTS = {
    0: 0.50,
    1: 0.30,
    2: 0.20,
}

FOCUS_PLAYERS = [
    "Nikola Jokić",
    "Luka Dončić",
    "Shai Gilgeous-Alexander",
    "Giannis Antetokounmpo",
    "Victor Wembanyama",
    "Jalen Johnson",
    "Cade Cunningham",
    "Kevin Durant",
    "Kawhi Leonard",
    "Donovan Mitchell",
    "Jamal Murray",
    "Alperen Sengun",
    "Karl-Anthony Towns",
    "Scottie Barnes",
    "Tyrese Maxey",
    "LeBron James",
    "Jaylen Brown",
    "Anthony Edwards",
    "Evan Mobley",
    "Kon Knueppel",
    "Moussa Diabaté",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without loading project data.",
    )
    return parser.parse_args()


def locate(candidates: list[Path], label: str) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"{label} not found:\n"
        + "\n".join(str(path) for path in candidates)
    )


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    raise ValueError(f"Unsupported file type: {path}")


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    return " ".join(text.casefold().replace(".", "").split())


def numeric(
    frame: pd.DataFrame,
    column: str,
    default: float = np.nan,
) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def percentile_within_group(
    frame: pd.DataFrame,
    value_column: str,
    group_column: str = "season_start",
) -> pd.Series:
    values = numeric(frame, value_column)
    return (
        values.groupby(frame[group_column])
        .rank(method="average", pct=True)
        .mul(100.0)
        .fillna(50.0)
        .clip(0.0, 100.0)
    )


def winsorize_within_group(
    frame: pd.DataFrame,
    value_column: str,
    group_column: str = "season_start",
    lower: float = 0.05,
    upper: float = 0.95,
) -> pd.Series:
    values = numeric(frame, value_column)

    def clip_group(series: pd.Series) -> pd.Series:
        valid = series.dropna()
        if valid.empty:
            return series
        low = valid.quantile(lower)
        high = valid.quantile(upper)
        return series.clip(low, high)

    return values.groupby(
        frame[group_column],
        group_keys=False,
    ).apply(clip_group)


def weighted_sum(
    frame: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("Weights must sum to 1.0.")

    output = pd.Series(0.0, index=frame.index, dtype=float)
    for column, weight in weights.items():
        if column not in frame.columns:
            raise ValueError(f"Missing weighted column: {column}")
        output += (
            numeric(frame, column, 50.0)
            .fillna(50.0)
            .clip(0.0, 100.0)
            * weight
        )
    return output


def build_season_history_scores(
    history: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "player_id",
        "player_name",
        "season",
        "season_start",
        "games_played",
        "total_minutes",
        "minutes_per_game",
        "availability_rate",
        "advanced_pie",
        "advanced_net_rating",
    }
    missing = sorted(required.difference(history.columns))
    if missing:
        raise ValueError(
            "Unified history is missing required columns:\n"
            + "\n".join(missing)
        )

    output = history.copy()
    output["player_id"] = output["player_id"].map(
        normalize_player_id
    )
    output["season_start"] = pd.to_numeric(
        output["season_start"],
        errors="raise",
    ).astype(int)

    duplicate_mask = output.duplicated(
        subset=["player_id", "season_start"],
        keep=False,
    )
    if duplicate_mask.any():
        duplicates = output.loc[
            duplicate_mask,
            ["player_id", "player_name", "season"],
        ]
        raise ValueError(
            "Duplicate player-seasons found:\n"
            + duplicates.head(25).to_string(index=False)
        )

    role_source = (
        "minutes_availability_value"
        if "minutes_availability_value" in output.columns
        else "total_minutes"
    )

    output["history_role_percentile"] = percentile_within_group(
        output,
        role_source,
    )
    output["history_pie_percentile"] = percentile_within_group(
        output,
        "advanced_pie",
    )

    output["_net_rating_winsorized"] = winsorize_within_group(
        output,
        "advanced_net_rating",
    )
    output["history_net_percentile"] = (
        output["_net_rating_winsorized"]
        .groupby(output["season_start"])
        .rank(method="average", pct=True)
        .mul(100.0)
        .fillna(50.0)
        .clip(0.0, 100.0)
    )
    output["history_availability_percentile"] = (
        percentile_within_group(
            output,
            "availability_rate",
        )
    )

    output["historical_season_value_score"] = weighted_sum(
        output,
        SEASON_VALUE_WEIGHTS,
    )
    output["historical_season_value_percentile"] = (
        output["historical_season_value_score"]
        .groupby(output["season_start"])
        .rank(method="average", pct=True)
        .mul(100.0)
        .fillna(50.0)
        .clip(0.0, 100.0)
    )

    return output


def summarize_recent_history(
    season_scores: pd.DataFrame,
    current_player_ids: set[str],
) -> pd.DataFrame:
    relevant = season_scores.loc[
        season_scores["player_id"].isin(current_player_ids)
    ].copy()

    relevant = relevant.sort_values(
        ["player_id", "season_start"],
        ascending=[True, False],
    )
    relevant["recent_season_index"] = relevant.groupby(
        "player_id"
    ).cumcount()
    recent = relevant.loc[
        relevant["recent_season_index"].le(2)
    ].copy()
    recent["recent_weight"] = recent[
        "recent_season_index"
    ].map(RECENT_SEASON_WEIGHTS)

    recent["weighted_value_piece"] = (
        recent["historical_season_value_percentile"]
        * recent["recent_weight"]
    )
    recent["weighted_pie_piece"] = (
        recent["history_pie_percentile"]
        * recent["recent_weight"]
    )
    recent["weighted_role_piece"] = (
        recent["history_role_percentile"]
        * recent["recent_weight"]
    )

    grouped_rows: list[dict[str, Any]] = []
    for player_id, group in recent.groupby(
        "player_id",
        sort=False,
    ):
        weight_total = float(group["recent_weight"].sum())
        if weight_total <= 0:
            continue

        value_percentiles = group[
            "historical_season_value_percentile"
        ]
        grouped_rows.append(
            {
                "player_id": player_id,
                "history_recent_seasons": int(len(group)),
                "history_recent_weight_total": weight_total,
                "history_recent3_value_percentile": float(
                    group["weighted_value_piece"].sum()
                    / weight_total
                ),
                "history_recent3_pie_percentile": float(
                    group["weighted_pie_piece"].sum()
                    / weight_total
                ),
                "history_recent3_role_percentile": float(
                    group["weighted_role_piece"].sum()
                    / weight_total
                ),
                "history_best_recent_value_percentile": float(
                    value_percentiles.max()
                ),
                "history_worst_recent_value_percentile": float(
                    value_percentiles.min()
                ),
                "history_recent_elite_seasons": int(
                    value_percentiles.ge(90.0).sum()
                ),
                "history_recent_star_seasons": int(
                    value_percentiles.ge(80.0).sum()
                ),
                "history_recent_quality_seasons": int(
                    value_percentiles.ge(70.0).sum()
                ),
                "history_recent_total_minutes": float(
                    numeric(group, "total_minutes", 0.0)
                    .fillna(0.0)
                    .sum()
                ),
                "history_latest_season": str(
                    group.iloc[0]["season"]
                ),
                "history_latest_value_percentile": float(
                    group.iloc[0][
                        "historical_season_value_percentile"
                    ]
                ),
            }
        )

    return pd.DataFrame(grouped_rows)


def build_audit(
    ratings: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    ratings = ratings.copy()
    ratings["player_id"] = ratings["player_id"].map(
        normalize_player_id
    )

    current_ids = set(ratings["player_id"])
    season_scores = build_season_history_scores(history)
    recent_summary = summarize_recent_history(
        season_scores,
        current_ids,
    )

    audit = ratings.merge(
        recent_summary,
        how="left",
        on="player_id",
        validate="one_to_one",
    )

    audit["history_recent3_value_percentile"] = numeric(
        audit,
        "history_recent3_value_percentile",
        50.0,
    ).fillna(50.0)
    audit["history_recent3_league_rank"] = (
        audit["history_recent3_value_percentile"]
        .rank(method="min", ascending=False)
        .astype(int)
    )

    audit["history_vs_current_rank_difference"] = (
        numeric(audit, "league_overall_rank")
        - numeric(audit, "history_recent3_league_rank")
    )
    audit["history_vs_current_percentile_gap"] = (
        audit["history_recent3_value_percentile"]
        - numeric(audit, "overall_league_percentile_v4", 50.0)
    )

    audit["history_context_flag"] = np.select(
        [
            (
                audit["history_recent3_value_percentile"].ge(90.0)
                & numeric(audit, "league_overall_rank").gt(20)
            ),
            (
                audit["history_recent3_value_percentile"].lt(80.0)
                & numeric(audit, "league_overall_rank").le(15)
            ),
            (
                numeric(audit, "career_seasons", 1.0).le(1.0)
                & numeric(audit, "overall_rating").ge(87.0)
            ),
        ],
        [
            "Sustained history suggests underrating",
            "Current rating may exceed sustained history",
            "High current rating with one season",
        ],
        default="No major history mismatch",
    )

    selected_columns = [
        "league_overall_rank",
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "career_seasons",
        "career_games",
        "career_minutes",
        "evidence_weight",
        "demonstrated_rating_v4",
        "projection_based_rating_v4",
        "tier_eligibility_cap_v4",
        "tier_gate_reasons_v4",
        "history_recent_seasons",
        "history_recent3_value_percentile",
        "history_recent3_league_rank",
        "history_recent3_pie_percentile",
        "history_recent3_role_percentile",
        "history_best_recent_value_percentile",
        "history_worst_recent_value_percentile",
        "history_recent_elite_seasons",
        "history_recent_star_seasons",
        "history_recent_quality_seasons",
        "history_recent_total_minutes",
        "history_latest_season",
        "history_latest_value_percentile",
        "history_vs_current_rank_difference",
        "history_vs_current_percentile_gap",
        "history_context_flag",
        "archetype",
    ]
    return audit[
        [column for column in selected_columns if column in audit.columns]
    ].sort_values("league_overall_rank").reset_index(drop=True)


def validation_rows(
    ratings: pd.DataFrame,
    audit: pd.DataFrame,
) -> list[dict[str, Any]]:
    coverage = float(
        audit["history_recent_seasons"].notna().mean()
    )
    return [
        {
            "check_name": "rating_rows_preserved",
            "passed": len(audit) == len(ratings) == 582,
            "observed": len(audit),
            "expected": 582,
        },
        {
            "check_name": "player_ids_unique",
            "passed": audit["player_id"].is_unique,
            "observed": int(audit["player_id"].nunique()),
            "expected": len(audit),
        },
        {
            "check_name": "history_coverage_at_least_95_percent",
            "passed": coverage >= 0.95,
            "observed": round(coverage, 4),
            "expected": ">=0.95",
        },
        {
            "check_name": "history_rank_complete",
            "passed": (
                audit["history_recent3_league_rank"]
                .between(1, len(audit))
                .all()
            ),
            "observed": {
                "minimum": int(
                    audit["history_recent3_league_rank"].min()
                ),
                "maximum": int(
                    audit["history_recent3_league_rank"].max()
                ),
            },
            "expected": f"1-{len(audit)}",
        },
        {
            "check_name": "recent_history_percentile_in_range",
            "passed": (
                audit["history_recent3_value_percentile"]
                .between(0.0, 100.0)
                .all()
            ),
            "observed": {
                "minimum": round(
                    float(
                        audit[
                            "history_recent3_value_percentile"
                        ].min()
                    ),
                    3,
                ),
                "maximum": round(
                    float(
                        audit[
                            "history_recent3_value_percentile"
                        ].max()
                    ),
                    3,
                ),
            },
            "expected": "0-100",
        },
    ]


def display_focus_players(audit: pd.DataFrame) -> pd.DataFrame:
    normalized_focus = {
        normalize_name(name)
        for name in FOCUS_PLAYERS
    }
    focus = audit.loc[
        audit["player_name"].map(normalize_name).isin(
            normalized_focus
        )
    ].copy()
    return focus[
        [
            "league_overall_rank",
            "player_name",
            "team_abbreviation",
            "overall_rating",
            "potential_rating",
            "career_seasons",
            "history_recent3_value_percentile",
            "history_recent3_league_rank",
            "history_recent_elite_seasons",
            "history_recent_star_seasons",
            "history_latest_value_percentile",
            "history_context_flag",
        ]
    ].sort_values("league_overall_rank")


def run_self_test() -> int:
    sample = pd.DataFrame(
        {
            "season_start": [2024, 2024, 2025, 2025],
            "value": [10.0, 20.0, 30.0, 10.0],
        }
    )
    percentiles = percentile_within_group(
        sample,
        "value",
    ).tolist()

    weighted_sample = pd.DataFrame(
        {
            "a": [100.0, 0.0],
            "b": [0.0, 100.0],
        }
    )
    weights = {"a": 0.5, "b": 0.5}

    tests = {
        "season_value_weights_sum_to_one": math.isclose(
            sum(SEASON_VALUE_WEIGHTS.values()),
            1.0,
        ),
        "recent_weights_sum_to_one": math.isclose(
            sum(RECENT_SEASON_WEIGHTS.values()),
            1.0,
        ),
        "within_season_percentiles": (
            [round(value, 1) for value in percentiles]
            == [50.0, 100.0, 100.0, 50.0]
        ),
        "weighted_sum": (
            weighted_sum(weighted_sample, weights).tolist()
            == [50.0, 50.0]
        ),
        "accent_normalization": (
            normalize_name("Nikola Jokić")
            == normalize_name("Nikola Jokic")
        ),
        "player_id_normalization": (
            normalize_player_id(1630162.0) == "1630162"
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    rating_path = locate(
        RATING_CANDIDATES,
        "V4.2.1 candidate rating release",
    )
    history_path = locate(
        HISTORY_CANDIDATES,
        "Unified player-season history",
    )

    print("=" * 92)
    print("PLAYER RATING V4.2.1 MULTI-SEASON HISTORY AUDIT")
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/5] Loading rating candidate and unified history")
    ratings = read_frame(rating_path)
    history = read_frame(history_path)
    print(
        f"  Ratings: {len(ratings):,} x {len(ratings.columns):,}"
    )
    print(
        f"  History: {len(history):,} x {len(history.columns):,}"
    )

    print("[2/5] Building season-relative historical value scores")
    print("[3/5] Summarizing weighted recent-three-season evidence")
    audit = build_audit(ratings, history)

    print("[4/5] Validating history coverage and joins")
    validations = pd.DataFrame(
        validation_rows(ratings, audit)
    )
    valid = bool(validations["passed"].all())

    print("[5/5] Writing audit outputs")
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    audit.to_csv(AUDIT_OUTPUT, index=False)
    validations.to_csv(VALIDATION_OUTPUT, index=False)

    methodology = {
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "rating_source": str(rating_path),
        "history_source": str(history_path),
        "season_value_weights": SEASON_VALUE_WEIGHTS,
        "recent_season_weights": RECENT_SEASON_WEIGHTS,
        "notes": [
            (
                "This audit does not alter or promote player ratings."
            ),
            (
                "Historical value is calculated relative to each season, "
                "which avoids comparing raw league environments directly."
            ),
            (
                "Net rating is winsorized within season before ranking to "
                "reduce extreme small-sample effects."
            ),
        ],
        "validation_passed": int(
            validations["passed"].sum()
        ),
        "validation_total": len(validations),
        "audit_output": str(AUDIT_OUTPUT),
    }
    METHODOLOGY_OUTPUT.write_text(
        json.dumps(methodology, indent=2),
        encoding="utf-8",
    )

    print("Complete")
    print(
        f"Validation: {int(validations['passed'].sum())}/"
        f"{len(validations)}"
    )
    print(f"Audit valid: {valid}")
    print(
        "History coverage: "
        f"{audit['history_recent_seasons'].notna().mean():.1%}"
    )

    print()
    print("FOCUS PLAYER HISTORY CONTEXT")
    print(
        display_focus_players(audit).to_string(index=False)
    )

    print()
    print("TOP 30 BY RECENT THREE-SEASON HISTORY")
    print(
        audit.sort_values(
            [
                "history_recent3_value_percentile",
                "history_best_recent_value_percentile",
            ],
            ascending=[False, False],
        )[
            [
                "history_recent3_league_rank",
                "player_name",
                "team_abbreviation",
                "league_overall_rank",
                "overall_rating",
                "history_recent3_value_percentile",
                "history_recent_elite_seasons",
                "history_recent_star_seasons",
                "history_latest_value_percentile",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )

    print()
    print("LARGEST POSSIBLE CURRENT OVERRATINGS VS HISTORY")
    print(
        audit.sort_values(
            "history_vs_current_rank_difference",
            ascending=True,
        )[
            [
                "league_overall_rank",
                "player_name",
                "overall_rating",
                "history_recent3_league_rank",
                "history_recent3_value_percentile",
                "career_seasons",
                "history_context_flag",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    print()
    print("LARGEST POSSIBLE CURRENT UNDERRATINGS VS HISTORY")
    print(
        audit.sort_values(
            "history_vs_current_rank_difference",
            ascending=False,
        )[
            [
                "league_overall_rank",
                "player_name",
                "overall_rating",
                "history_recent3_league_rank",
                "history_recent3_value_percentile",
                "career_seasons",
                "history_context_flag",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    if not valid:
        print()
        print("FAILED VALIDATION CHECKS")
        print(
            validations.loc[
                ~validations["passed"]
            ].to_string(index=False)
        )

    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())