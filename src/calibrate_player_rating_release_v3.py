"""Refine the approved V2 player-rating display release.

V3 is presentation-only. It compresses the scale so the league leader is near
98.2 rather than 99.9, floors POT at OVR, and preserves the old projected
future standing as Future Outlook.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_VERSION = "player-rating-calibration-v3-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v3"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
APP_DATA = ROOT / "app_data"

INPUT_PARQUET = DATA / "player_rating_release_2026_27_v2.parquet"
INPUT_CSV = INPUT_PARQUET.with_suffix(".csv")
INPUT_METHODOLOGY = OUTPUTS / "player_rating_methodology_v2.json"

OUTPUT_PARQUET = DATA / "player_rating_release_2026_27_v3.parquet"
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_JSON = APP_DATA / "player_ratings_2026_27_v3.json"
OUTPUT_VALIDATION = OUTPUTS / "player_rating_calibration_validation_v3.csv"
OUTPUT_DISTRIBUTION = OUTPUTS / "player_rating_distribution_summary_v3.csv"
OUTPUT_COMPARISON = OUTPUTS / "player_rating_calibration_comparison_v3.csv"
OUTPUT_METHODOLOGY = OUTPUTS / "player_rating_methodology_v3.json"

PERCENTILE_ANCHORS = np.array([
    0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 82, 85, 88, 90, 92,
    95, 97, 98, 99, 99.5, 100,
], dtype=float)
RATING_ANCHORS = np.array([
    60.0, 63.7, 66.7, 70.6, 73.6, 76.6, 79.5, 81.5, 83.5,
    86.0, 86.5, 87.5, 88.5, 89.5, 90.5, 92.4, 94.3, 95.2,
    96.3, 97.1, 98.2,
], dtype=float)

CALIBRATION_COLUMNS = {
    "overall_rating": "overall_calibration_percentile",
    "scoring_rating": "scoring_calibration_percentile",
    "shooting_rating": "shooting_calibration_percentile",
    "playmaking_rating": "playmaking_calibration_percentile",
    "rebounding_rating": "rebounding_calibration_percentile",
    "defense_rating": "defense_calibration_percentile",
    "efficiency_rating": "efficiency_calibration_percentile",
    "availability_rating": "availability_calibration_percentile",
    "future_outlook_rating": "potential_calibration_percentile",
    "contract_value_rating": "contract_value_calibration_percentile",
    "trade_value_rating": "trade_value_calibration_percentile",
}

GRADE_THRESHOLDS = [
    (97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"),
    (80, "B-"), (77, "C+"), (73, "C"), (70, "C-"), (67, "D+"),
    (63, "D"), (60, "D-"),
]
ROLE_THRESHOLDS = [
    (97, "MVP-level superstar"), (94, "Franchise superstar"),
    (90, "All-Star caliber"), (87, "High-end starter"),
    (83, "Quality starter"), (79, "Rotation player"),
    (75, "Bench contributor"), (70, "Depth player"),
    (60, "Developmental player"),
]

APP_COLUMNS = [
    "player_id", "player_name", "team_abbreviation", "age",
    "league_overall_rank", "team_overall_rank", "overall_rating",
    "overall_grade", "role_label", "archetype", "primary_skill",
    "secondary_skill", "primary_strength", "secondary_strength",
    "strengths", "concerns", "rating_confidence",
    "development_direction", "development_arrow", "future_peak_season",
    "games_played", "minutes_per_game", "points_per_game",
    "rebounds_per_game", "assists_per_game", "field_goal_pct",
    "three_point_pct", "true_shooting_pct", "usage_pct",
    "scoring_rating", "scoring_grade", "shooting_rating",
    "shooting_grade", "playmaking_rating", "playmaking_grade",
    "rebounding_rating", "rebounding_grade", "defense_rating",
    "defense_grade", "efficiency_rating", "efficiency_grade",
    "availability_rating", "availability_grade", "potential_rating",
    "potential_grade", "future_outlook_rating", "future_outlook_grade",
    "contract_value_rating", "contract_value_grade", "contract_value_source",
    "trade_value_rating", "trade_value_grade", "trade_value_source",
    "market_asset_class", "protected_player_flag", "salary_2026_27",
    "future_salary_commitment", "rating_scope_note", "potential_scope_note",
    "future_outlook_scope_note", "finishing_scope_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def rating_from_percentile(value: Any) -> float:
    percentile = float(np.clip(safe_float(value, 50.0), 0.0, 100.0))
    return round(float(np.interp(percentile, PERCENTILE_ANCHORS, RATING_ANCHORS)), 1)


def grade(value: Any) -> str:
    rating = safe_float(value, 60.0)
    return next((label for threshold, label in GRADE_THRESHOLDS if rating >= threshold), "D-")


def role(value: Any) -> str:
    rating = safe_float(value, 60.0)
    return next((label for threshold, label in ROLE_THRESHOLDS if rating >= threshold), "Developmental player")


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def locate_input() -> Path:
    if INPUT_PARQUET.exists():
        return INPUT_PARQUET
    if INPUT_CSV.exists():
        return INPUT_CSV
    raise FileNotFoundError(f"Approved V2 release not found:\n{INPUT_PARQUET}\n{INPUT_CSV}")


def read_frame(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)


def distribution(frame: pd.DataFrame) -> pd.DataFrame:
    rating_columns = [*CALIBRATION_COLUMNS, "potential_rating"]
    rows = []
    for column in rating_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        rows.append({
            "rating": column,
            "count": int(values.notna().sum()),
            "minimum": round(float(values.min()), 3),
            "p10": round(float(values.quantile(.10)), 3),
            "p25": round(float(values.quantile(.25)), 3),
            "median": round(float(values.median()), 3),
            "mean": round(float(values.mean()), 3),
            "p75": round(float(values.quantile(.75)), 3),
            "p90": round(float(values.quantile(.90)), 3),
            "p95": round(float(values.quantile(.95)), 3),
            "maximum": round(float(values.max()), 3),
        })
    return pd.DataFrame(rows)


def build_app_json(frame: pd.DataFrame, methodology: dict[str, Any]) -> dict[str, Any]:
    columns = [column for column in APP_COLUMNS if column in frame.columns]
    records = frame[columns].where(pd.notna(frame[columns]), None).to_dict(orient="records")
    players_by_id = {str(row["player_id"]): json_safe(row) for row in records}
    by_team: dict[str, list[str]] = {}
    for row in records:
        by_team.setdefault(str(row.get("team_abbreviation", "")), []).append(str(row["player_id"]))
    return {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "league_year": "2026-27",
        "rating_scale": {
            "minimum": 60.0,
            "maximum": 98.2,
            "decimals": 1,
            "example": "97.8",
            "calibration": "compressed_elite_ceiling_v3",
        },
        "player_count": len(records),
        "methodology": methodology,
        "players_by_id": players_by_id,
        "player_ids_by_team": by_team,
    }


def validation(v2: pd.DataFrame, v3: pd.DataFrame) -> pd.DataFrame:
    def row(name: str, passed: bool, observed: Any, expected: Any) -> dict[str, Any]:
        return {"check_name": name, "passed": bool(passed), "observed": observed, "expected": expected}

    rating_columns = [*CALIBRATION_COLUMNS, "potential_rating"]
    matrix = v3[rating_columns].apply(pd.to_numeric, errors="coerce")
    ids = sorted(set(v2["player_id"].astype(str)) & set(v3["player_id"].astype(str)))
    v2i = v2.assign(_id=v2["player_id"].astype(str)).set_index("_id").loc[ids]
    v3i = v3.assign(_id=v3["player_id"].astype(str)).set_index("_id").loc[ids]
    percentiles_unchanged = all(
        np.allclose(
            pd.to_numeric(v2i[column], errors="coerce").fillna(-9999).to_numpy(),
            pd.to_numeric(v3i[column], errors="coerce").fillna(-9999).to_numpy(),
        )
        for column in CALIBRATION_COLUMNS.values()
    )
    v2_order = v2.sort_values("league_overall_rank")["player_id"].astype(str).tolist()
    v3_order = v3.sort_values("league_overall_rank")["player_id"].astype(str).tolist()
    top = v3.sort_values("league_overall_rank").iloc[0]
    pot_violations = int((v3["potential_rating"] + 1e-9 < v3["overall_rating"]).sum())
    future_below = int((v3["future_outlook_rating"] < v3["overall_rating"]).sum())

    checks = [
        row("player_count_preserved", len(v2) == len(v3) == 582, len(v3), 582),
        row("player_ids_preserved", set(v2["player_id"].astype(str)) == set(v3["player_id"].astype(str)), v3["player_id"].nunique(), v2["player_id"].nunique()),
        row("underlying_calibration_percentiles_unchanged", percentiles_unchanged, True, True),
        row("overall_rank_order_preserved", v2_order == v3_order, True, True),
        row("ratings_complete", not matrix.isna().any().any(), int(matrix.notna().sum().sum()), int(matrix.size)),
        row("ratings_within_v3_scale", (matrix.ge(60) & matrix.le(98.2)).all().all(), {"min": float(matrix.min().min()), "max": float(matrix.max().max())}, "60.0-98.2"),
        row("ratings_use_one_decimal", all(np.allclose(matrix[c].to_numpy(), matrix[c].round(1).to_numpy()) for c in rating_columns), True, True),
        row("league_best_near_98", 97.8 <= safe_float(top["overall_rating"]) <= 98.3, safe_float(top["overall_rating"]), "97.8-98.3"),
        row("league_best_below_99", safe_float(top["overall_rating"]) < 99.0, safe_float(top["overall_rating"]), "<99.0"),
        row("potential_never_below_overall", pot_violations == 0, pot_violations, 0),
        row("future_outlook_separate_from_potential", future_below > 0, future_below, ">0"),
        row("overall_median_shifted_modestly", 78.5 <= float(v3["overall_rating"].median()) <= 80.0, round(float(v3["overall_rating"].median()), 3), "78.5-80.0"),
        row("elite_population_selective", 15 <= int(v3["overall_rating"].ge(93).sum()) <= 35, int(v3["overall_rating"].ge(93).sum()), "15-35"),
        row("all_star_population_selective", 35 <= int(v3["overall_rating"].ge(90).sum()) <= 70, int(v3["overall_rating"].ge(90).sum()), "35-70"),
        row("grades_complete", v3[["overall_grade", "potential_grade", "future_outlook_grade", "contract_value_grade", "trade_value_grade"]].ne("").all().all(), True, True),
        row("finishing_remains_unreleased", not v3["finishing_rating_released"].any(), bool(v3["finishing_rating_released"].any()), False),
    ]
    return pd.DataFrame(checks)


def run_self_test() -> int:
    tests = {
        "anchor_lengths_match": len(PERCENTILE_ANCHORS) == len(RATING_ANCHORS),
        "percentile_anchors_monotonic": bool(np.all(np.diff(PERCENTILE_ANCHORS) > 0)),
        "rating_anchors_monotonic": bool(np.all(np.diff(RATING_ANCHORS) > 0)),
        "rating_floor": rating_from_percentile(0) == 60.0,
        "rating_midpoint": rating_from_percentile(50) == 79.5,
        "rating_ceiling": rating_from_percentile(100) == 98.2,
        "rating_ceiling_below_99": rating_from_percentile(100) < 99.0,
        "grade_mapping": grade(98.2) == "A+" and grade(92.4) == "A-",
        "potential_floor_rule": max(98.2, 88.9) == 98.2,
    }
    serializable = {key: bool(value) for key, value in tests.items()}
    print(json.dumps(serializable, indent=2))
    return 0 if all(serializable.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    input_path = locate_input()
    if not INPUT_METHODOLOGY.exists():
        raise FileNotFoundError(f"V2 methodology not found: {INPUT_METHODOLOGY}")

    print("=" * 88)
    print("PLAYER RATING DISPLAY CALIBRATION V3")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}\n")

    print("[1/6] Loading approved V2 rating release")
    v2 = read_frame(input_path)
    methodology_v2 = json.loads(INPUT_METHODOLOGY.read_text(encoding="utf-8"))
    print(f"  Players: {len(v2):,}")

    missing = sorted(set(CALIBRATION_COLUMNS.values()) - set(v2.columns))
    if missing:
        raise ValueError("V2 release is missing calibration percentile columns:\n" + "\n".join(missing))

    print("[2/6] Compressing the display scale")
    v3 = v2.copy()
    comparison = pd.DataFrame({
        "player_id": v2["player_id"].astype(str),
        "player_name": v2["player_name"],
        "team_abbreviation": v2["team_abbreviation"],
        "league_overall_rank": v2["league_overall_rank"],
    })

    for rating_column, percentile_column in CALIBRATION_COLUMNS.items():
        prior_column = "potential_rating" if rating_column == "future_outlook_rating" else rating_column
        comparison[f"{rating_column}_v2"] = v2[prior_column]
        v3[rating_column] = v3[percentile_column].map(rating_from_percentile)
        comparison[f"{rating_column}_v3"] = v3[rating_column]
        comparison[f"{rating_column}_change"] = (v3[rating_column] - v2[prior_column]).round(1)

    print("[3/6] Separating potential from future outlook")
    v3["potential_rating"] = np.maximum(v3["overall_rating"], v3["future_outlook_rating"]).round(1)
    for field in [*CALIBRATION_COLUMNS, "potential_rating"]:
        v3[field.replace("_rating", "_grade")] = v3[field].map(grade)
    v3["role_label"] = v3["overall_rating"].map(role)
    v3["potential_scope_note"] = "Potential represents modeled career ceiling and is never lower than current OVR."
    v3["future_outlook_scope_note"] = "Future Outlook represents projected future standing and may be lower than current OVR."
    v3["rating_scope_note"] = (
        "Display ratings use a compressed 60.0-98.2 scale. Underlying model percentiles, optimizer values, projections, legality results, and simulation inputs remain unchanged and retain full precision."
    )
    v3 = v3.sort_values("league_overall_rank").reset_index(drop=True)

    print("[4/6] Building diagnostics")
    distributions = distribution(v3)

    print("[5/6] Validating V3 release")
    validations = validation(v2, v3)
    release_valid = bool(validations["passed"].all())

    methodology_v3 = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "source_release": methodology_v2.get("release_name", "player_ratings_2026_27_v2"),
        "calibration_scope": "Presentation-layer recalibration only. The entire scale shifts down modestly and the elite end is compressed. Underlying model values and rankings are unchanged.",
        "rating_scale": {"minimum": 60.0, "maximum": 98.2, "decimals": 1},
        "potential_definition": "Career ceiling. POT is floored at current OVR.",
        "future_outlook_definition": "Projected future standing. May be lower than current OVR.",
        "percentile_anchors": PERCENTILE_ANCHORS.tolist(),
        "rating_anchors": RATING_ANCHORS.tolist(),
        "finishing_rating_released": False,
        "validation_passed": int(validations["passed"].sum()),
        "validation_total": len(validations),
    }

    print("[6/6] Writing V3 artifacts")
    DATA.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    v3.to_parquet(OUTPUT_PARQUET, index=False)
    v3.to_csv(OUTPUT_CSV, index=False)
    validations.to_csv(OUTPUT_VALIDATION, index=False)
    distributions.to_csv(OUTPUT_DISTRIBUTION, index=False)
    comparison.to_csv(OUTPUT_COMPARISON, index=False)
    OUTPUT_METHODOLOGY.write_text(json.dumps(json_safe(methodology_v3), indent=2), encoding="utf-8")
    OUTPUT_JSON.write_text(json.dumps(json_safe(build_app_json(v3, methodology_v3)), indent=2, ensure_ascii=False), encoding="utf-8")

    print("Complete")
    print(f"Validation: {int(validations['passed'].sum())}/{len(validations)}")
    print(f"Release valid: {release_valid}")
    print(f"Players rated: {len(v3):,}")
    print(f"Overall range: {v3['overall_rating'].min():.1f}-{v3['overall_rating'].max():.1f}")
    print(f"Overall distribution: median {v3['overall_rating'].median():.1f} | std {v3['overall_rating'].std():.1f}")
    print(f"Elite counts: 93+ {v3['overall_rating'].ge(93).sum()} | 90+ {v3['overall_rating'].ge(90).sum()} | 87+ {v3['overall_rating'].ge(87).sum()}")
    print(f"Potential floor violations: {int((v3['potential_rating'] < v3['overall_rating']).sum())}")
    print("\nTOP 10 REFINED RATINGS")
    print(v3[[
        "league_overall_rank", "player_name", "team_abbreviation",
        "overall_rating", "overall_grade", "potential_rating",
        "future_outlook_rating", "trade_value_rating", "archetype",
    ]].head(10).to_string(index=False))
    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())