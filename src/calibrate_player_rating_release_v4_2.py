"""Build a more conservative and interpretable V4 player-rating release.

V4 addresses three presentation issues found during visual review:
1. Current OVR was too generous outside the very top of the league.
2. Potential was treated as a future rank instead of a career ceiling.
3. Free agents lost their most recent team branding in the app.

The script preserves all underlying model values and league ordering. It only
changes display ratings and app-facing affiliation fields.

Install as:
    src/calibrate_player_rating_release_v4.py

Run:
    python src/calibrate_player_rating_release_v4.py --self-test
    python src/calibrate_player_rating_release_v4.py
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

SCRIPT_VERSION = "player-rating-calibration-v4-2-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v4"

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
APP_DATA = ROOT / "app_data"

INPUT_CANDIDATES = [
    DATA / "player_rating_release_2026_27_v3.parquet",
    DATA / "player_rating_release_2026_27_v3.csv",
]
PROJECTION_CANDIDATES = [
    DATA / "current_player_projection_board_2025_26_to_2026_27.parquet",
    DATA / "current_player_projection_board_2025_26_to_2026_27.csv",
]
INPUT_METHODOLOGY_CANDIDATES = [
    OUTPUTS / "player_rating_methodology_v3.json",
    OUTPUTS / "player_rating_methodology_v2.json",
]

OUTPUT_PARQUET = DATA / "player_rating_release_2026_27_v4.parquet"
OUTPUT_CSV = OUTPUT_PARQUET.with_suffix(".csv")
OUTPUT_JSON = APP_DATA / "player_ratings_2026_27_v4.json"
OUTPUT_VALIDATION = OUTPUTS / "player_rating_calibration_validation_v4.csv"
OUTPUT_DISTRIBUTION = OUTPUTS / "player_rating_distribution_summary_v4.csv"
OUTPUT_COMPARISON = OUTPUTS / "player_rating_calibration_comparison_v4.csv"
OUTPUT_TEAM_AUDIT = OUTPUTS / "player_rating_affiliation_audit_v4.csv"
OUTPUT_BENCHMARKS = OUTPUTS / "player_rating_benchmark_examples_v4.csv"
OUTPUT_METHODOLOGY = OUTPUTS / "player_rating_methodology_v4.json"

# Current OVR is intentionally conservative. A top-13-percent player maps to
# roughly 83 rather than 88. The very top remains separated.
CURRENT_PERCENTILE_ANCHORS = np.array([
    0, 5, 10, 20, 30, 40, 50, 60, 70, 80,
    85, 88, 90, 92, 95, 97, 98, 99, 99.5, 100,
], dtype=float)
CURRENT_RATING_ANCHORS = np.array([
    60.0, 61.0, 62.5, 65.0, 67.5, 70.0, 73.0, 76.0, 78.5, 81.0,
    82.5, 83.5, 84.5, 86.0, 89.0, 92.0, 94.0, 96.0, 97.2, 98.2,
], dtype=float)

# Potential uses a different curve because it represents ceiling, not current
# ability. High-end prospects can reach 98-99, while ordinary young rotation
# players land in the mid/high 80s.
POTENTIAL_PERCENTILE_ANCHORS = np.array([
    0, 10, 20, 30, 40, 50, 60, 70, 80, 85,
    88, 90, 92, 95, 97, 98, 99, 99.5, 100,
], dtype=float)
POTENTIAL_RATING_ANCHORS = np.array([
    60.0, 64.0, 67.0, 70.0, 73.0, 76.0, 79.0, 82.0, 85.0, 87.0,
    88.0, 89.0, 90.0, 92.0, 94.0, 96.0, 98.0, 98.6, 99.0,
], dtype=float)

# Contract and trade value are relative asset measures, not player ability.
# Keep their V3 presentation values unchanged.
CURRENT_RATING_FIELDS = {
    "overall_rating": "overall_calibration_percentile",
    "scoring_rating": "scoring_calibration_percentile",
    "shooting_rating": "shooting_calibration_percentile",
    "playmaking_rating": "playmaking_calibration_percentile",
    "rebounding_rating": "rebounding_calibration_percentile",
    "defense_rating": "defense_calibration_percentile",
    "efficiency_rating": "efficiency_calibration_percentile",
    "availability_rating": "availability_calibration_percentile",
    "future_outlook_rating": "potential_calibration_percentile",
}

GRADE_THRESHOLDS = [
    (97.0, "A+"), (94.0, "A"), (90.0, "A-"), (86.0, "B+"),
    (82.0, "B"), (78.0, "B-"), (74.0, "C+"), (70.0, "C"),
    (67.0, "C-"), (64.0, "D+"), (61.0, "D"), (60.0, "D-"),
]
ROLE_THRESHOLDS = [
    (97.0, "MVP-level superstar"),
    (94.0, "Franchise superstar"),
    (90.0, "All-Star caliber"),
    (86.0, "High-end starter"),
    (82.0, "Quality starter"),
    (78.0, "Rotation player"),
    (74.0, "Bench contributor"),
    (70.0, "Depth player"),
    (60.0, "Developmental player"),
]

FREE_AGENT_CODES = {"", "FA", "FREE AGENT", "NONE", "NAN"}

APP_COLUMNS = [
    "player_id", "player_name", "team_abbreviation",
    "display_team_abbreviation", "display_team_name", "roster_status",
    "age", "league_overall_rank", "team_overall_rank", "overall_rating",
    "overall_grade", "role_label", "archetype", "primary_skill",
    "secondary_skill", "primary_strength", "secondary_strength", "strengths",
    "concerns", "rating_confidence", "development_direction",
    "development_arrow", "future_peak_season", "games_played",
    "minutes_per_game", "points_per_game", "rebounds_per_game",
    "assists_per_game", "field_goal_pct", "three_point_pct",
    "true_shooting_pct", "usage_pct", "scoring_rating", "scoring_grade",
    "shooting_rating", "shooting_grade", "playmaking_rating",
    "playmaking_grade", "rebounding_rating", "rebounding_grade",
    "defense_rating", "defense_grade", "efficiency_rating",
    "efficiency_grade", "availability_rating", "availability_grade",
    "potential_rating", "potential_grade", "future_outlook_rating",
    "future_outlook_grade", "contract_value_rating", "contract_value_grade",
    "contract_value_source", "trade_value_rating", "trade_value_grade",
    "trade_value_source", "market_asset_class", "protected_player_flag",
    "salary_2026_27", "future_salary_commitment", "rating_scope_note",
    "potential_scope_note", "future_outlook_scope_note",
    "affiliation_scope_note", "finishing_scope_note",
]

TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_team(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().upper()


def locate(candidates: list[Path], label: str) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        f"{label} was not found:\n" + "\n".join(str(path) for path in candidates)
    )


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def current_rating(percentile: Any) -> float:
    value = float(np.clip(safe_float(percentile, 50.0), 0.0, 100.0))
    return round(float(np.interp(
        value, CURRENT_PERCENTILE_ANCHORS, CURRENT_RATING_ANCHORS
    )), 1)


def potential_base_rating(percentile: Any) -> float:
    value = float(np.clip(safe_float(percentile, 50.0), 0.0, 100.0))
    return round(float(np.interp(
        value, POTENTIAL_PERCENTILE_ANCHORS, POTENTIAL_RATING_ANCHORS
    )), 1)


def potential_gap_cap(overall: float) -> float:
    if overall >= 95.0:
        return 2.0
    if overall >= 90.0:
        return 5.0
    if overall >= 85.0:
        return 7.0
    if overall >= 80.0:
        return 8.0
    return 9.0


def career_potential(
    overall: Any,
    potential_percentile: Any,
    age: Any,
    overall_percentile: Any,
) -> float:
    """Estimate a career ceiling without equating prospect rank with perfection.

    A player receives the generational tier only when he is already an elite
    current player and also has top-end future evidence. A younger prospect
    with elite future evidence but less current dominance is capped in the
    franchise-superstar tier instead.
    """
    current = safe_float(overall, 60.0)
    pct = safe_float(potential_percentile, 50.0)
    player_age = safe_float(age, 27.0)
    overall_pct = safe_float(overall_percentile, 50.0)

    base = potential_base_rating(pct)

    # Established veterans normally have little remaining future ceiling.
    if player_age >= 29.0:
        base = min(base, current + 0.5)

    generational_profile = (
        player_age <= 23.0
        and current >= 95.0
        and overall_pct >= 99.0
        and pct >= 98.5
    )

    elite_prospect_profile = (
        player_age <= 24.0
        and pct >= 98.5
        and not generational_profile
    )

    if generational_profile:
        # This tier is intentionally rare. It represents a plausible
        # all-time-great ceiling rather than a perfect current player.
        # The ordinary improvement-gap cap does not apply because the player
        # has already supplied elite current evidence.
        result = max(current, 99.5)
        return round(float(min(result, 99.5)), 1)

    if elite_prospect_profile:
        # Exceptional prospects who have not yet demonstrated generational
        # current dominance remain in the franchise-superstar ceiling tier.
        # Their future evidence can support 97.0, but not the 99+ tier.
        result = max(current, min(base, 97.0))
        return round(float(result), 1)

    cap = current + potential_gap_cap(current)
    result = max(
        current,
        min(base, cap, 99.0),
    )
    return round(float(result), 1)


def grade(value: Any) -> str:
    rating = safe_float(value, 60.0)
    return next(
        (label for threshold, label in GRADE_THRESHOLDS if rating >= threshold),
        "D-",
    )


def role(value: Any) -> str:
    rating = safe_float(value, 60.0)
    return next(
        (label for threshold, label in ROLE_THRESHOLDS if rating >= threshold),
        "Developmental player",
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
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


def projection_affiliations(projection: pd.DataFrame) -> pd.DataFrame:
    if "player_id" not in projection.columns:
        raise ValueError("Projection board is missing player_id.")

    team_column = next(
        (
            column for column in [
                "team_abbreviation", "current_team_2026_27", "recent_team", "team"
            ] if column in projection.columns
        ),
        None,
    )
    if team_column is None:
        raise ValueError("Projection board has no usable team affiliation column.")

    age_column = next(
        (
            column for column in ["age", "age_2026_27", "projection_age"]
            if column in projection.columns
        ),
        None,
    )
    output = pd.DataFrame({
        "_player_key": projection["player_id"].map(normalize_player_id),
        "projection_team_abbreviation": projection[team_column].map(normalize_team),
        "projection_age": (
            pd.to_numeric(projection[age_column], errors="coerce")
            if age_column is not None
            else np.nan
        ),
    })
    output = output.loc[output["_player_key"].ne("")].copy()
    output = output.drop_duplicates("_player_key", keep="first")
    return output


def add_affiliation_fields(
    ratings: pd.DataFrame,
    projection: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output = ratings.copy()
    output["_player_key"] = output["player_id"].map(normalize_player_id)
    output["team_abbreviation"] = output["team_abbreviation"].map(normalize_team)

    affiliations = projection_affiliations(projection)
    output = output.merge(
        affiliations,
        on="_player_key",
        how="left",
        validate="one_to_one",
    )

    is_free_agent = output["team_abbreviation"].isin(FREE_AGENT_CODES)
    projection_team_valid = (
        output["projection_team_abbreviation"].notna()
        & ~output["projection_team_abbreviation"].isin(FREE_AGENT_CODES)
    )

    output["age"] = pd.to_numeric(output["age"], errors="coerce")
    output["age"] = output["age"].fillna(output["projection_age"])

    output["roster_status"] = np.where(
        is_free_agent,
        "Free agent",
        "Under contract",
    )
    output["display_team_abbreviation"] = output["team_abbreviation"]
    output.loc[
        is_free_agent & projection_team_valid,
        "display_team_abbreviation",
    ] = output.loc[
        is_free_agent & projection_team_valid,
        "projection_team_abbreviation",
    ]
    output["display_team_name"] = output["display_team_abbreviation"].map(
        TEAM_NAMES
    ).fillna(output["display_team_abbreviation"])
    output["affiliation_scope_note"] = np.where(
        is_free_agent & projection_team_valid,
        "Free agent; logo and team branding use the most recent modeled team affiliation.",
        "Team branding uses the current modeled team affiliation.",
    )

    audit = output.loc[
        is_free_agent,
        [
            "player_id", "player_name", "team_abbreviation",
            "projection_team_abbreviation", "display_team_abbreviation",
            "roster_status", "affiliation_scope_note",
        ],
    ].copy()

    return output, audit


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
            "calibration": "conservative_current_ovr_and_separate_ceiling_v4",
        },
        "player_count": len(records),
        "methodology": methodology,
        "players_by_id": players_by_id,
        "player_ids_by_team": by_team,
    }


def distribution(frame: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "overall_rating", "potential_rating", "future_outlook_rating",
        "scoring_rating", "shooting_rating", "playmaking_rating",
        "rebounding_rating", "defense_rating", "efficiency_rating",
        "availability_rating", "contract_value_rating", "trade_value_rating",
    ]
    rows = []
    for field in fields:
        values = pd.to_numeric(frame[field], errors="coerce")
        rows.append({
            "rating": field,
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


def benchmark_examples(frame: pd.DataFrame) -> pd.DataFrame:
    names = ["Moussa Diabaté", "Victor Wembanyama", "Kon Knueppel", "Jalen Duren", "Nikola Jokić"]
    columns = [
        "player_id", "player_name", "team_abbreviation",
        "display_team_abbreviation", "roster_status", "age",
        "league_overall_rank", "overall_rating", "potential_rating",
        "future_outlook_rating", "role_label",
    ]
    return frame.loc[frame["player_name"].isin(names), columns].sort_values(
        "league_overall_rank"
    )


def validation(v3: pd.DataFrame, v4: pd.DataFrame) -> pd.DataFrame:
    def check(name: str, passed: bool, observed: Any, expected: Any) -> dict[str, Any]:
        return {
            "check_name": name,
            "passed": bool(passed),
            "observed": observed,
            "expected": expected,
        }

    rating_fields = [
        "overall_rating", "potential_rating", "future_outlook_rating",
        "scoring_rating", "shooting_rating", "playmaking_rating",
        "rebounding_rating", "defense_rating", "efficiency_rating",
        "availability_rating", "contract_value_rating", "trade_value_rating",
    ]
    matrix = v4[rating_fields].apply(pd.to_numeric, errors="coerce")
    v3_order = v3.sort_values("league_overall_rank")["player_id"].astype(str).tolist()
    v4_order = v4.sort_values("league_overall_rank")["player_id"].astype(str).tolist()

    benchmarks = benchmark_examples(v4).set_index("player_name")

    def benchmark_value(name: str, field: str, default: float = np.nan) -> float:
        if name not in benchmarks.index:
            return default
        return safe_float(benchmarks.loc[name, field], default)

    duren_display_team = (
        str(benchmarks.loc["Jalen Duren", "display_team_abbreviation"])
        if "Jalen Duren" in benchmarks.index
        else ""
    )
    duren_status = (
        str(benchmarks.loc["Jalen Duren", "roster_status"])
        if "Jalen Duren" in benchmarks.index
        else ""
    )

    checks = [
        check("player_count_preserved", len(v3) == len(v4) == 582, len(v4), 582),
        check(
            "player_ids_preserved",
            set(v3["player_id"].astype(str)) == set(v4["player_id"].astype(str)),
            int(v4["player_id"].nunique()),
            int(v3["player_id"].nunique()),
        ),
        check("overall_rank_order_preserved", v3_order == v4_order, True, True),
        check("ratings_complete", not matrix.isna().any().any(), int(matrix.notna().sum().sum()), int(matrix.size)),
        check(
            "ratings_within_scale",
            (matrix.ge(60.0) & matrix.le(99.5)).all().all(),
            {"minimum": float(matrix.min().min()), "maximum": float(matrix.max().max())},
            "60.0-99.5",
        ),
        check(
            "ratings_use_one_decimal",
            all(np.allclose(matrix[field].to_numpy(), matrix[field].round(1).to_numpy()) for field in rating_fields),
            True,
            True,
        ),
        check(
            "league_leader_near_98",
            97.8 <= float(v4.iloc[0]["overall_rating"]) <= 98.3,
            float(v4.iloc[0]["overall_rating"]),
            "97.8-98.3",
        ),
        check(
            "overall_median_is_conservative",
            72.0 <= float(v4["overall_rating"].median()) <= 75.0,
            round(float(v4["overall_rating"].median()), 3),
            "72.0-75.0",
        ),
        check(
            "all_star_population_selective",
            10 <= int(v4["overall_rating"].ge(90.0).sum()) <= 30,
            int(v4["overall_rating"].ge(90.0).sum()),
            "10-30",
        ),
        check(
            "potential_never_below_overall",
            int((v4["potential_rating"] < v4["overall_rating"]).sum()) == 0,
            int((v4["potential_rating"] < v4["overall_rating"]).sum()),
            0,
        ),
        check(
            "diabate_current_low_80s",
            81.0 <= benchmark_value("Moussa Diabaté", "overall_rating") <= 84.9,
            benchmark_value("Moussa Diabaté", "overall_rating"),
            "81.0-84.9",
        ),
        check(
            "diabate_potential_high_80s",
            86.0 <= benchmark_value("Moussa Diabaté", "potential_rating") <= 89.9,
            benchmark_value("Moussa Diabaté", "potential_rating"),
            "86.0-89.9",
        ),
        check(
            "wembanyama_generational_potential",
            99.4 <= benchmark_value(
                "Victor Wembanyama",
                "potential_rating",
            ) <= 99.5,
            benchmark_value(
                "Victor Wembanyama",
                "potential_rating",
            ),
            "99.4-99.5",
        ),
        check(
            "kon_franchise_superstar_potential",
            96.5 <= benchmark_value(
                "Kon Knueppel",
                "potential_rating",
            ) <= 97.1,
            benchmark_value(
                "Kon Knueppel",
                "potential_rating",
            ),
            "96.5-97.1",
        ),
        check(
            "wembanyama_potential_above_kon",
            benchmark_value(
                "Victor Wembanyama",
                "potential_rating",
            )
            > benchmark_value(
                "Kon Knueppel",
                "potential_rating",
            ),
            {
                "wembanyama": benchmark_value(
                    "Victor Wembanyama",
                    "potential_rating",
                ),
                "kon_knueppel": benchmark_value(
                    "Kon Knueppel",
                    "potential_rating",
                ),
            },
            "Wembanyama > Kon Knueppel",
        ),
        check(
            "duren_uses_detroit_branding",
            duren_display_team == "DET",
            duren_display_team,
            "DET",
        ),
        check(
            "duren_still_marked_free_agent",
            duren_status == "Free agent",
            duren_status,
            "Free agent",
        ),
        check(
            "finishing_remains_unreleased",
            not v4["finishing_rating_released"].any(),
            bool(v4["finishing_rating_released"].any()),
            False,
        ),
    ]
    return pd.DataFrame(checks)


def run_self_test() -> int:
    tests = {
        "current_anchors_match": len(CURRENT_PERCENTILE_ANCHORS) == len(CURRENT_RATING_ANCHORS),
        "potential_anchors_match": len(POTENTIAL_PERCENTILE_ANCHORS) == len(POTENTIAL_RATING_ANCHORS),
        "current_anchors_monotonic": bool(np.all(np.diff(CURRENT_RATING_ANCHORS) > 0)),
        "potential_anchors_monotonic": bool(np.all(np.diff(POTENTIAL_RATING_ANCHORS) > 0)),
        "current_ceiling_is_98_2": current_rating(100.0) == 98.2,
        "top_13_percent_maps_low_80s": 82.0 <= current_rating(87.0) <= 84.0,
        "median_maps_73": current_rating(50.0) == 73.0,
        "potential_top_is_99": potential_base_rating(100.0) == 99.0,
        "potential_floor": career_potential(88.0, 70.0, 24.0, 85.0) >= 88.0,
        "generational_young_ceiling_is_99_5": (
            career_potential(
                97.0,
                99.5,
                22.0,
                99.5,
            )
            == 99.5
        ),
        "elite_prospect_without_current_dominance_caps_at_97": (
            career_potential(
                88.0,
                100.0,
                20.0,
                90.0,
            )
            == 97.0
        ),
        "veteran_potential_near_current": career_potential(96.0, 99.0, 31.0, 99.0) <= 96.5,
        "free_agent_normalization": normalize_team("FA") in FREE_AGENT_CODES,
    }
    serializable = {key: bool(value) for key, value in tests.items()}
    print(json.dumps(serializable, indent=2))
    return 0 if all(serializable.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    input_path = locate(INPUT_CANDIDATES, "V3 rating release")
    projection_path = locate(PROJECTION_CANDIDATES, "Projection board")
    methodology_path = locate(INPUT_METHODOLOGY_CANDIDATES, "Prior methodology")

    print("=" * 88)
    print("PLAYER RATING CALIBRATION V4")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}\n")

    print("[1/7] Loading V3 ratings and affiliation source")
    v3 = read_frame(input_path)
    projection = read_frame(projection_path)
    prior_methodology = json.loads(methodology_path.read_text(encoding="utf-8"))
    print(f"  Ratings: {len(v3):,} players")
    print(f"  Projection board: {len(projection):,} rows")

    missing = sorted(
        set(CURRENT_RATING_FIELDS.values())
        .union({"overall_calibration_percentile", "potential_calibration_percentile"})
        .difference(v3.columns)
    )
    if missing:
        raise ValueError(
            "V3 release is missing required percentile fields:\n" + "\n".join(missing)
        )

    print("[2/7] Recalibrating current basketball ratings")
    v4 = v3.copy()
    comparison = pd.DataFrame({
        "player_id": v3["player_id"].astype(str),
        "player_name": v3["player_name"],
        "team_abbreviation": v3["team_abbreviation"],
        "league_overall_rank": v3["league_overall_rank"],
    })

    for rating_field, percentile_field in CURRENT_RATING_FIELDS.items():
        comparison[f"{rating_field}_v3"] = v3[rating_field]
        v4[rating_field] = v4[percentile_field].map(current_rating)
        comparison[f"{rating_field}_v4"] = v4[rating_field]
        comparison[f"{rating_field}_change"] = (
            v4[rating_field] - v3[rating_field]
        ).round(1)

    print("[3/7] Building career-ceiling potential")
    v4["potential_rating"] = [
        career_potential(overall, potential_pct, age, overall_pct)
        for overall, potential_pct, age, overall_pct in zip(
            v4["overall_rating"],
            v4["potential_calibration_percentile"],
            v4["age"],
            v4["overall_calibration_percentile"],
        )
    ]

    # Preserve relative asset-value ratings from V3.
    v4["contract_value_rating"] = v3["contract_value_rating"]
    v4["trade_value_rating"] = v3["trade_value_rating"]

    for field in [
        "overall_rating", "scoring_rating", "shooting_rating",
        "playmaking_rating", "rebounding_rating", "defense_rating",
        "efficiency_rating", "availability_rating", "potential_rating",
        "future_outlook_rating", "contract_value_rating", "trade_value_rating",
    ]:
        v4[field.replace("_rating", "_grade")] = v4[field].map(grade)
    v4["role_label"] = v4["overall_rating"].map(role)

    v4["rating_scope_note"] = (
        "Current basketball ratings use a conservative 60.0-98.2 display scale. "
        "Underlying projections, percentiles, optimizer inputs, legality results, "
        "and simulation values remain unchanged."
    )
    v4["potential_scope_note"] = (
        "Potential is a career-ceiling estimate built from future model standing, "
        "age, current caliber, and explicit gap limits. It is never below OVR."
    )
    v4["future_outlook_scope_note"] = (
        "Future Outlook is the model's projected future standing and is separate "
        "from career-ceiling potential."
    )

    print("[4/7] Restoring free-agent team branding")
    v4, affiliation_audit = add_affiliation_fields(v4, projection)
    v4 = v4.sort_values("league_overall_rank").reset_index(drop=True)

    print("[5/7] Building diagnostics")
    distributions = distribution(v4)
    benchmarks = benchmark_examples(v4)

    print("[6/7] Validating V4 release")
    validations = validation(v3, v4)
    release_valid = bool(validations["passed"].all())

    methodology = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "source_release": prior_methodology.get("release_name", "player_ratings_2026_27_v3"),
        "current_ovr_definition": (
            "Current on-court ability mapped conservatively from the approved "
            "league ordering. Top-13-percent players land around 83 rather than 88."
        ),
        "potential_definition": (
            "Career ceiling based on future percentile, age, current OVR, current "
            "league percentile, explicit improvement gaps, and distinct "
            "generational versus franchise-superstar prospect tiers."
        ),
        "future_outlook_definition": (
            "Projected future standing. It may differ from career ceiling."
        ),
        "affiliation_definition": (
            "Free agents remain labeled FA. Team logo and color use the most recent "
            "projection-board affiliation when available."
        ),
        "current_percentile_anchors": CURRENT_PERCENTILE_ANCHORS.tolist(),
        "current_rating_anchors": CURRENT_RATING_ANCHORS.tolist(),
        "potential_percentile_anchors": POTENTIAL_PERCENTILE_ANCHORS.tolist(),
        "potential_rating_anchors": POTENTIAL_RATING_ANCHORS.tolist(),
        "validation_passed": int(validations["passed"].sum()),
        "validation_total": len(validations),
    }

    print("[7/7] Writing V4 artifacts")
    DATA.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)

    v4.to_parquet(OUTPUT_PARQUET, index=False)
    v4.to_csv(OUTPUT_CSV, index=False)
    validations.to_csv(OUTPUT_VALIDATION, index=False)
    distributions.to_csv(OUTPUT_DISTRIBUTION, index=False)
    comparison.to_csv(OUTPUT_COMPARISON, index=False)
    affiliation_audit.to_csv(OUTPUT_TEAM_AUDIT, index=False)
    benchmarks.to_csv(OUTPUT_BENCHMARKS, index=False)
    OUTPUT_METHODOLOGY.write_text(
        json.dumps(json_safe(methodology), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    OUTPUT_JSON.write_text(
        json.dumps(json_safe(build_app_json(v4, methodology)), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Complete")
    print(f"Validation: {int(validations['passed'].sum())}/{len(validations)}")
    print(f"Release valid: {release_valid}")
    print(f"Players rated: {len(v4):,}")
    print(
        f"Overall range: {v4['overall_rating'].min():.1f}-"
        f"{v4['overall_rating'].max():.1f}"
    )
    print(
        f"Overall distribution: median {v4['overall_rating'].median():.1f} | "
        f"std {v4['overall_rating'].std():.1f}"
    )
    print(
        f"Elite counts: 93+ {v4['overall_rating'].ge(93).sum()} | "
        f"90+ {v4['overall_rating'].ge(90).sum()} | "
        f"86+ {v4['overall_rating'].ge(86).sum()}"
    )
    print(
        f"Potential floor violations: "
        f"{int((v4['potential_rating'] < v4['overall_rating']).sum())}"
    )
    print("\nBENCHMARK EXAMPLES")
    print(benchmarks.to_string(index=False))

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())