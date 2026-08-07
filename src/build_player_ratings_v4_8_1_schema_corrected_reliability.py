"""
Build a V4.8.1 schema-corrected reliability-weighted NBA player OVR preview.

Purpose
-------
V4.7 fixed the league-wide rating scale, but a universal 75% model / 25% 2K
blend preserved several implausible player-hierarchy errors. V4.8.1 keeps the
statistical model as the primary source while allowing a stronger external
benchmark correction only where the model is less reliable or the disagreement
is extreme.

Core design
-----------
1. Always start from the original pre-V4.6 V4.5.1 statistical payload.
2. Preserve the original model OVR percentile signal.
3. Map that model signal onto the realistic current-2K league distribution.
4. Assign a player-specific external-benchmark weight from fields that are
   actually present in the V4.5.1 payload:
   - current_core_rating_v44;
   - history_quality_score_v43 and recent-three history percentile;
   - evidence_weight, availability_rating, minutes, and career experience;
   - young/high-confidence players: usually 10-25% external;
   - normal established players: usually 20-30% external;
   - established stars: usually 45-50% external;
   - extreme disagreements: up to 60% external;
   - fringe/free-agent extreme outliers: up to 55% external.
5. Never copy a 2K rank.
6. Recompute all league/team ranks from the final blended OVR.
7. Preserve every underlying statistic and component rating.
8. Preserve POT unless it must be raised solely to maintain POT >= OVR.

The live alias is never modified.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "player-rating-v4-8-1-schema-corrected-reliability-v1-2026-08-07"
)
RELEASE_NAME = (
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_preview"
)

RATING_MINIMUM = 67.0
RATING_MAXIMUM = 98.5
MAX_EXTERNAL_WEIGHT = 0.60

DEFAULT_SOURCE = Path(
    "backups/player_ratings_2026_27_v2_before_v4_6_2k_recalibration.json"
)
DEFAULT_AUDIT = Path(
    "outputs/player_ratings_vs_current_2k_audit_v1.csv"
)
DEFAULT_CANDIDATE = Path(
    "app_data/"
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_preview.json"
)
DEFAULT_PLAYER_AUDIT = Path(
    "outputs/"
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_audit.csv"
)
DEFAULT_SUMMARY = Path(
    "outputs/"
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_summary.json"
)
DEFAULT_VALIDATION = Path(
    "outputs/"
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_validation.csv"
)
DEFAULT_BENCHMARKS = Path(
    "outputs/"
    "player_ratings_2026_27_v4_8_1_schema_corrected_reliability_benchmarks.csv"
)

BENCHMARK_NAMES = {
    "Nikola Jokić",
    "Shai Gilgeous-Alexander",
    "Luka Dončić",
    "Victor Wembanyama",
    "Kevin Durant",
    "Cade Cunningham",
    "Jaylen Brown",
    "Donovan Mitchell",
    "Jamal Murray",
    "Alperen Sengun",
    "Alperen Şengün",
    "Scottie Barnes",
    "Giannis Antetokounmpo",
    "Stephen Curry",
    "Jayson Tatum",
    "Anthony Davis",
    "Trae Young",
    "Ja Morant",
    "Kon Knueppel",
    "Payton Pritchard",
    "Nikola Vučević",
    "Kel'el Ware",
    "Kel’el Ware",
    "Moussa Diabaté",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--audit-csv", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--candidate-json", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument(
        "--player-audit-csv",
        type=Path,
        default=DEFAULT_PLAYER_AUDIT,
    )
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--validation-csv",
        type=Path,
        default=DEFAULT_VALIDATION,
    )
    parser.add_argument(
        "--benchmarks-csv",
        type=Path,
        default=DEFAULT_BENCHMARKS,
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return Path.cwd()


def resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return " ".join(str(value).strip().split())


def normalize_player_id(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        number = float(text)
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
    except (TypeError, ValueError):
        pass
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def quality_tier_label(overall: Any) -> str:
    rating = safe_float(overall)
    if not math.isfinite(rating):
        return "Unrated"
    if rating >= 97.0:
        return "MVP-level superstar"
    if rating >= 94.0:
        return "Franchise superstar"
    if rating >= 91.0:
        return "All-NBA caliber"
    if rating >= 88.0:
        return "All-Star caliber"
    if rating >= 85.0:
        return "High-end starter"
    if rating >= 82.0:
        return "Quality starter"
    if rating >= 79.0:
        return "Solid starter"
    if rating >= 76.0:
        return "Rotation player"
    if rating >= 73.0:
        return "Bench contributor"
    if rating >= 70.0:
        return "Developmental depth"
    return "Fringe/development"


def overall_grade(value: Any) -> str:
    rating = safe_float(value, RATING_MINIMUM)
    thresholds = [
        (97.0, "A+"),
        (94.0, "A"),
        (91.0, "A-"),
        (88.0, "B+"),
        (85.0, "B"),
        (82.0, "B-"),
        (79.0, "C+"),
        (76.0, "C"),
        (73.0, "C-"),
        (70.0, "D+"),
        (67.0, "D"),
    ]
    return next(
        (grade for threshold, grade in thresholds if rating >= threshold),
        "D-",
    )


def load_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Original statistical payload not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    players = payload.get("players_by_id")

    if not isinstance(players, dict):
        raise ValueError("Statistical payload is missing players_by_id.")
    if len(players) != 582:
        raise ValueError(f"Expected 582 players, found {len(players)}.")

    release_name = clean_text(payload.get("release_name"))
    if "v4_5_1" not in release_name:
        raise ValueError(
            "V4.8 must start from the original V4.5.1 statistical release. "
            f"Observed release: {release_name!r}"
        )

    return payload


def payload_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for payload_key, value in payload["players_by_id"].items():
        if not isinstance(value, dict):
            raise ValueError(f"Invalid player payload: {payload_key}")

        player_id = normalize_player_id(value.get("player_id", payload_key))
        player_name = clean_text(value.get("player_name"))
        overall = safe_float(value.get("overall_rating"))
        potential = safe_float(value.get("potential_rating"))
        future = safe_float(value.get("future_outlook_rating"))

        if not player_id or not player_name:
            raise ValueError(f"Missing player identity: {payload_key}")
        if not math.isfinite(overall):
            raise ValueError(f"Missing OVR for {player_name}")
        if not math.isfinite(potential):
            raise ValueError(f"Missing POT for {player_name}")
        if not math.isfinite(future):
            raise ValueError(f"Missing FUT for {player_name}")

        current_core = safe_float(
            value.get("current_core_rating_v44"),
            np.nan,
        )
        history_quality = safe_float(
            value.get("history_quality_score_v43"),
            np.nan,
        )
        evidence = safe_float(
            value.get("evidence_weight"),
            np.nan,
        )

        if not math.isfinite(current_core):
            raise ValueError(
                f"Missing current_core_rating_v44 for {player_name}"
            )
        if not math.isfinite(history_quality):
            raise ValueError(
                f"Missing history_quality_score_v43 for {player_name}"
            )
        if not math.isfinite(evidence):
            raise ValueError(
                f"Missing evidence_weight for {player_name}"
            )

        rows.append(
            {
                "payload_key": str(payload_key),
                "player_id": player_id,
                "player_name": player_name,
                "team_abbreviation": clean_text(
                    value.get(
                        "team_abbreviation",
                        value.get(
                            "current_team_2026_27",
                            value.get("display_team_abbreviation", ""),
                        ),
                    )
                ).upper(),
                "old_overall": overall,
                "old_potential": potential,
                "old_future": future,
                "old_role_label": clean_text(value.get("role_label")),
                "old_league_rank": safe_float(
                    value.get("league_overall_rank")
                ),
                "old_trade_value": safe_float(
                    value.get("trade_value_rating"),
                    0.0,
                ),
                "age": safe_float(value.get("age"), 27.0),
                "career_seasons": safe_float(
                    value.get("career_seasons"),
                    1.0,
                ),
                "evidence_weight": evidence,
                "current_core_rating_v44": current_core,
                "history_quality_score_v43": history_quality,
                "history_recent3_value_percentile": safe_float(
                    value.get("history_recent3_value_percentile"),
                    history_quality,
                ),
                "minutes_per_game": safe_float(
                    value.get("minutes_per_game"),
                    0.0,
                ),
                "availability_rating": safe_float(
                    value.get("availability_rating"),
                    50.0,
                ),
                "career_minutes": safe_float(
                    value.get("career_minutes"),
                    0.0,
                ),
            }
        )

    frame = pd.DataFrame(rows)

    if len(frame) != 582:
        raise ValueError(f"Expected 582 payload rows, found {len(frame)}.")
    if frame["player_id"].duplicated().any():
        raise ValueError("Statistical payload contains duplicate player IDs.")

    return frame

def load_audit(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Current 2K audit not found: {path}")

    frame = pd.read_csv(path, low_memory=False)
    required = {
        "player_id",
        "source_overall",
        "match_method",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "Current 2K audit is missing required columns: "
            + ", ".join(missing)
        )

    frame = frame.copy()
    frame["player_id"] = frame["player_id"].map(normalize_player_id)
    frame["source_overall"] = pd.to_numeric(
        frame["source_overall"],
        errors="coerce",
    )
    frame = frame.loc[frame["player_id"].ne("")].copy()

    if frame["player_id"].duplicated().any():
        duplicates = sorted(
            frame.loc[
                frame["player_id"].duplicated(False),
                "player_id",
            ].unique()
        )
        raise ValueError(
            "Current 2K audit has duplicate player IDs: "
            + ", ".join(duplicates[:20])
        )

    return frame.reset_index(drop=True)


def empirical_percentiles(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any():
        raise ValueError("Model OVR input contains missing values.")
    return numeric.rank(method="average", pct=True, ascending=True)


def quantile_map(
    percentiles: pd.Series,
    target_values: pd.Series,
) -> np.ndarray:
    target = (
        pd.to_numeric(target_values, errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
    )
    if len(target) < 100:
        raise ValueError(
            f"At least 100 current 2K ratings are required; found {len(target)}."
        )

    target = np.sort(target)
    probabilities = np.clip(
        percentiles.to_numpy(dtype=float),
        0.0,
        1.0,
    )

    try:
        mapped = np.quantile(target, probabilities, method="linear")
    except TypeError:
        mapped = np.quantile(
            target,
            probabilities,
            interpolation="linear",
        )

    return np.asarray(mapped, dtype=float)


def external_weight_and_reason(row: pd.Series) -> tuple[float, str]:
    if not bool(row.get("matched_to_current_2k", False)):
        return 0.0, "unmatched_100_percent_model"

    seasons = safe_float(row.get("career_seasons"), 1.0)
    evidence = safe_float(row.get("evidence_weight"), 0.65)
    source = safe_float(row.get("source_overall"), np.nan)
    mapped = safe_float(
        row.get("distribution_mapped_model_overall"),
        np.nan,
    )
    team = clean_text(row.get("team_abbreviation"))
    core = safe_float(row.get("current_core_rating_v44"), 50.0)
    history = safe_float(
        row.get("history_quality_score_v43"),
        50.0,
    )
    recent_history = safe_float(
        row.get("history_recent3_value_percentile"),
        history,
    )
    availability = safe_float(
        row.get("availability_rating"),
        50.0,
    )
    minutes = safe_float(row.get("minutes_per_game"), 0.0)

    disagreement = abs(mapped - source)
    model_above = mapped - source
    core_history_gap = abs(core - history)
    reasons: list[str] = []

    if seasons <= 2.0:
        weight = 0.15
        reasons.append("young_player")
    elif seasons <= 4.0:
        weight = 0.20
        reasons.append("early_career")
    else:
        weight = 0.30
        reasons.append("established_player")

    # Young players remain model-first, but large disagreements receive more
    # benchmark influence than they did in V4.8.
    if seasons <= 2.0:
        if disagreement >= 6.0:
            weight = max(weight, 0.35)
            reasons.append("young_extreme_disagreement")
        elif disagreement >= 4.0:
            weight = max(weight, 0.25)
            reasons.append("young_large_disagreement")
    elif seasons <= 4.0:
        if disagreement >= 6.0:
            weight = max(weight, 0.45)
            reasons.append("early_career_extreme_disagreement")
        elif disagreement >= 4.0:
            weight = max(weight, 0.35)
            reasons.append("early_career_large_disagreement")

    if (
        seasons <= 2.0
        and evidence >= 0.85
        and disagreement <= 3.0
    ):
        weight = min(weight, 0.10)
        reasons.append("young_high_confidence_model")

    if seasons >= 5.0 and source >= 90.0:
        weight = max(weight, 0.45)
        reasons.append("established_2k_90_plus")

    if seasons >= 5.0 and source >= 94.0:
        weight = max(weight, 0.50)
        reasons.append("established_2k_94_plus")

    if seasons >= 5.0 and disagreement >= 4.0:
        weight = max(weight, 0.45)
        reasons.append("established_large_disagreement")

    if seasons >= 5.0 and disagreement >= 6.0:
        weight = max(weight, 0.60)
        reasons.append("established_extreme_disagreement")

    # Low-confidence statistical profiles receive a modest extra correction.
    low_reliability_signals = 0
    if evidence < 0.85:
        low_reliability_signals += 1
        reasons.append("lower_evidence")
    if history < 75.0 or recent_history < 75.0:
        low_reliability_signals += 1
        reasons.append("lower_history_support")
    if availability < 75.0:
        low_reliability_signals += 1
        reasons.append("lower_availability")
    if minutes < 24.0:
        low_reliability_signals += 1
        reasons.append("lower_minutes")

    if disagreement >= 3.0 and low_reliability_signals >= 2:
        weight = min(MAX_EXTERNAL_WEIGHT, weight + 0.05)
        reasons.append("multi_signal_reliability_adjustment")

    if (
        not team
        and source <= 72.0
        and model_above >= 4.0
    ):
        weight = max(weight, 0.55)
        reasons.append("fringe_free_agent_outlier")

    # This replaces the unavailable V4.8 impact/role fields with fields that
    # are actually present for all 582 players.
    strong_model_support = (
        evidence >= 0.93
        and core >= 85.0
        and history >= 82.0
        and recent_history >= 82.0
        and availability >= 75.0
        and minutes >= 24.0
        and core_history_gap <= 10.0
        and disagreement <= 3.0
    )
    if strong_model_support:
        weight = max(0.10, weight - 0.05)
        reasons.append("strong_observed_model_support")

    very_strong_model_support = (
        evidence >= 0.97
        and core >= 90.0
        and history >= 90.0
        and recent_history >= 90.0
        and availability >= 80.0
        and minutes >= 28.0
        and core_history_gap <= 7.0
        and disagreement <= 2.0
    )
    if very_strong_model_support:
        weight = max(0.10, weight - 0.05)
        reasons.append("very_strong_observed_model_support")

    weight = float(np.clip(weight, 0.0, MAX_EXTERNAL_WEIGHT))
    return round(weight, 2), "|".join(reasons)

def calibrate(
    active: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    output = active.copy()

    target_distribution = audit.loc[
        audit["source_overall"].notna(),
        "source_overall",
    ]

    output["model_percentile"] = empirical_percentiles(
        output["old_overall"]
    )
    output["distribution_mapped_model_overall"] = quantile_map(
        output["model_percentile"],
        target_distribution,
    )

    merge_columns = [
        column
        for column in (
            "player_id",
            "source_player_name",
            "source_team",
            "source_overall",
            "source_position",
            "source_archetype",
            "match_method",
            "match_score",
            "source_player_url",
        )
        if column in audit.columns
    ]

    output = output.merge(
        audit[merge_columns],
        on="player_id",
        how="left",
        validate="one_to_one",
    )

    output["matched_to_current_2k"] = output["source_overall"].notna()
    output["preblend_difference_from_current_2k"] = (
        output["distribution_mapped_model_overall"]
        - output["source_overall"]
    ).round(3)
    output["preblend_absolute_difference"] = (
        output["preblend_difference_from_current_2k"].abs()
    )

    weight_results = output.apply(
        external_weight_and_reason,
        axis=1,
        result_type="expand",
    )
    weight_results.columns = [
        "external_benchmark_weight",
        "reliability_weight_reason",
    ]
    output = pd.concat([output, weight_results], axis=1)

    output["statistical_model_weight"] = (
        1.0 - output["external_benchmark_weight"]
    ).round(2)

    mapped = pd.to_numeric(
        output["distribution_mapped_model_overall"],
        errors="coerce",
    )
    source = pd.to_numeric(
        output["source_overall"],
        errors="coerce",
    )
    external_weight = output["external_benchmark_weight"].astype(float)
    model_weight = output["statistical_model_weight"].astype(float)

    blended = mapped * model_weight + source * external_weight
    candidate = mapped.where(
        ~output["matched_to_current_2k"],
        blended,
    )

    output["new_overall"] = (
        candidate
        .clip(RATING_MINIMUM, RATING_MAXIMUM)
        .round(1)
    )
    output["overall_change"] = (
        output["new_overall"] - output["old_overall"]
    ).round(1)
    output["difference_from_current_2k"] = (
        output["new_overall"] - source
    ).round(1)
    output["absolute_difference_from_current_2k"] = (
        output["difference_from_current_2k"].abs()
    )

    output["new_potential"] = np.maximum(
        output["old_potential"],
        output["new_overall"],
    ).round(1)
    output["potential_change"] = (
        output["new_potential"] - output["old_potential"]
    ).round(1)

    output["new_role_label"] = output["new_overall"].map(
        quality_tier_label
    )
    output["role_label_changed"] = (
        output["new_role_label"] != output["old_role_label"]
    )

    output = output.sort_values(
        ["new_overall", "old_trade_value", "player_name"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    output["new_league_rank"] = np.arange(1, len(output) + 1)
    output["new_team_rank"] = (
        output.groupby("team_abbreviation", dropna=False).cumcount() + 1
    )

    return output


def apply_candidate(
    payload: dict[str, Any],
    calibrated: pd.DataFrame,
) -> dict[str, Any]:
    candidate = copy.deepcopy(payload)
    by_id = calibrated.set_index("player_id").to_dict(orient="index")

    for payload_key, player in candidate["players_by_id"].items():
        player_id = normalize_player_id(
            player.get("player_id", payload_key)
        )
        if player_id not in by_id:
            raise KeyError(f"Missing calibrated player: {player_id}")

        row = by_id[player_id]

        player["overall_rating_before_v4_8_1_calibration"] = round(
            float(row["old_overall"]),
            1,
        )
        player["overall_rating"] = round(
            float(row["new_overall"]),
            1,
        )
        player["league_overall_rank"] = int(
            row["new_league_rank"]
        )
        player["team_overall_rank"] = int(
            row["new_team_rank"]
        )
        player["overall_grade"] = overall_grade(
            row["new_overall"]
        )

        player["role_label_before_v4_8_1_calibration"] = clean_text(
            row["old_role_label"]
        )
        player["role_label"] = clean_text(
            row["new_role_label"]
        )
        player["role_label_method"] = (
            "v4_8_1_schema_corrected_reliability_band"
        )

        if float(row["new_potential"]) > float(row["old_potential"]):
            player["potential_rating_before_v4_8_1_floor"] = round(
                float(row["old_potential"]),
                1,
            )
            player["potential_rating"] = round(
                float(row["new_potential"]),
                1,
            )

        player["distribution_mapped_statistical_overall"] = round(
            float(row["distribution_mapped_model_overall"]),
            1,
        )
        player["current_2k_benchmark_matched"] = bool(
            row["matched_to_current_2k"]
        )
        player["current_2k_overall"] = (
            round(float(row["source_overall"]), 1)
            if pd.notna(row.get("source_overall"))
            else None
        )
        player["current_2k_match_method"] = clean_text(
            row.get("match_method")
        )
        player["current_2k_match_score"] = (
            round(float(row["match_score"]), 2)
            if pd.notna(row.get("match_score"))
            else None
        )
        player["overall_statistical_model_weight"] = round(
            float(row["statistical_model_weight"]),
            2,
        )
        player["overall_external_benchmark_weight"] = round(
            float(row["external_benchmark_weight"]),
            2,
        )
        player["overall_reliability_weight_reason"] = clean_text(
            row["reliability_weight_reason"]
        )
        player["overall_calibration_method"] = (
            "v4_8_1_schema_corrected_reliability"
            if row["matched_to_current_2k"]
            else "100_percent_distribution_mapped_model"
        )

    candidate["release_name"] = RELEASE_NAME
    candidate["script_version"] = SCRIPT_VERSION

    candidate["rating_scale"] = {
        **dict(candidate.get("rating_scale", {})),
        "overall_minimum": round(
            float(calibrated["new_overall"].min()),
            1,
        ),
        "overall_maximum": round(
            float(calibrated["new_overall"].max()),
            1,
        ),
        "potential_maximum": round(
            float(calibrated["new_potential"].max()),
            1,
        ),
        "decimals": 1,
        "overall_calibration": (
            "schema_corrected_reliability_current_2k_v4_8_1"
        ),
    }

    methodology = dict(candidate.get("methodology", {}))
    methodology["v4_8_1_schema_corrected_reliability"] = {
        "distribution_calibration": (
            "Original model OVR percentile is mapped onto the current-2K "
            "distribution to correct only the league-wide scale."
        ),
        "player_specific_blend": (
            "External benchmark weight varies from 0% to 60% based on career "
            "experience, evidence strength, current core, history quality, "
            "availability, minutes, roster status, benchmark tier, and "
            "disagreement magnitude."
        ),
        "default_weights": {
            "young_player_external": 0.15,
            "early_career_external": 0.20,
            "established_player_external": 0.30,
            "established_90_plus_external_minimum": 0.45,
            "established_94_plus_external_minimum": 0.50,
            "established_extreme_disagreement_external": 0.60,
            "fringe_free_agent_outlier_external": 0.55,
        },
        "rank_policy": "No 2K rank is copied.",
        "hard_distance_cap_to_2k": None,
        "schema_correction": (
            "Uses current_core_rating_v44, history_quality_score_v43, "
            "history_recent3_value_percentile, evidence_weight, "
            "availability_rating, minutes_per_game, and career_minutes. "
            "Unavailable impact/role fields are not fabricated."
        ),
        "maximum_external_weight": MAX_EXTERNAL_WEIGHT,
        "preview_only": True,
    }
    candidate["methodology"] = methodology

    candidate["v4_8_1_calibration"] = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "preview_only": True,
        "live_alias_modified": False,
        "source_release": clean_text(payload.get("release_name")),
        "matched_players": int(
            calibrated["matched_to_current_2k"].sum()
        ),
        "unmatched_players": int(
            (~calibrated["matched_to_current_2k"]).sum()
        ),
        "mean_statistical_model_weight_matched": round(
            float(
                calibrated.loc[
                    calibrated["matched_to_current_2k"],
                    "statistical_model_weight",
                ].mean()
            ),
            4,
        ),
        "median_statistical_model_weight_matched": round(
            float(
                calibrated.loc[
                    calibrated["matched_to_current_2k"],
                    "statistical_model_weight",
                ].median()
            ),
            4,
        ),
    }

    return candidate


def distribution(
    frame: pd.DataFrame,
    column: str,
) -> dict[str, Any]:
    values = pd.to_numeric(frame[column], errors="coerce")
    return {
        "count": int(values.notna().sum()),
        "minimum": round(float(values.min()), 3),
        "p10": round(float(values.quantile(0.10)), 3),
        "p25": round(float(values.quantile(0.25)), 3),
        "median": round(float(values.median()), 3),
        "mean": round(float(values.mean()), 3),
        "p75": round(float(values.quantile(0.75)), 3),
        "p90": round(float(values.quantile(0.90)), 3),
        "p95": round(float(values.quantile(0.95)), 3),
        "maximum": round(float(values.max()), 3),
        "count_90_plus": int(values.ge(90).sum()),
        "count_85_plus": int(values.ge(85).sum()),
        "count_80_plus": int(values.ge(80).sum()),
    }


def player_value(
    calibrated: pd.DataFrame,
    name: str,
    column: str,
) -> float:
    normalized = calibrated["player_name"].str.replace(
        "’",
        "'",
        regex=False,
    )
    target = name.replace("’", "'")
    matched = calibrated.loc[normalized.eq(target)]

    if matched.empty:
        return float("nan")

    return safe_float(matched.iloc[0][column])


def validation_rows(
    active: pd.DataFrame,
    audit: pd.DataFrame,
    calibrated: pd.DataFrame,
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    players = candidate.get("players_by_id", {})
    new_values = pd.to_numeric(
        calibrated["new_overall"],
        errors="coerce",
    )
    potential = pd.to_numeric(
        calibrated["new_potential"],
        errors="coerce",
    )
    matched = calibrated["matched_to_current_2k"]

    matched_frame = calibrated.loc[matched].copy()
    expected_matched = int(audit["source_overall"].notna().sum())

    formula_value = (
        matched_frame["distribution_mapped_model_overall"]
        * matched_frame["statistical_model_weight"]
        + matched_frame["source_overall"]
        * matched_frame["external_benchmark_weight"]
    ).round(1)
    formula_error = (
        matched_frame["new_overall"] - formula_value
    ).abs()

    old_new_spearman = calibrated[
        ["old_overall", "new_overall"]
    ].corr(method="spearman").iloc[0, 1]

    pre_extreme_established = int(
        (
            matched_frame["career_seasons"].ge(5)
            & matched_frame["preblend_absolute_difference"].ge(6)
        ).sum()
    )
    post_extreme_established = int(
        (
            matched_frame["career_seasons"].ge(5)
            & matched_frame[
                "absolute_difference_from_current_2k"
            ].ge(6)
        ).sum()
    )

    expected_labels = calibrated["new_overall"].map(
        quality_tier_label
    )

    reliability_fields = [
        "current_core_rating_v44",
        "history_quality_score_v43",
        "evidence_weight",
        "availability_rating",
        "minutes_per_game",
    ]
    reliability_missing = {
        field: int(
            pd.to_numeric(
                calibrated[field],
                errors="coerce",
            ).isna().sum()
        )
        for field in reliability_fields
    }

    benchmark_checks = {
        "giannis_minimum": (
            player_value(
                calibrated,
                "Giannis Antetokounmpo",
                "new_overall",
            )
            >= 92.5
        ),
        "curry_minimum": (
            player_value(
                calibrated,
                "Stephen Curry",
                "new_overall",
            )
            >= 90.5
        ),
        "tatum_minimum": (
            player_value(
                calibrated,
                "Jayson Tatum",
                "new_overall",
            )
            >= 89.5
        ),
        "trae_minimum": (
            player_value(
                calibrated,
                "Trae Young",
                "new_overall",
            )
            >= 84.5
        ),
        "jamal_maximum": (
            player_value(
                calibrated,
                "Jamal Murray",
                "new_overall",
            )
            <= 92.5
        ),
        "pritchard_maximum": (
            player_value(
                calibrated,
                "Payton Pritchard",
                "new_overall",
            )
            <= 85.0
        ),
        "vucevic_maximum": (
            player_value(
                calibrated,
                "Nikola Vučević",
                "new_overall",
            )
            <= 82.5
        ),
        "amen_maximum": (
            player_value(
                calibrated,
                "Amen Thompson",
                "new_overall",
            )
            <= 90.5
        ),
        "podziemski_maximum": (
            player_value(
                calibrated,
                "Brandin Podziemski",
                "new_overall",
            )
            <= 84.5
        ),
        "jaquez_maximum": (
            player_value(
                calibrated,
                "Jaime Jaquez Jr.",
                "new_overall",
            )
            <= 83.5
        ),
    }

    checks = [
        (
            "player_count_preserved",
            len(active) == len(calibrated) == len(players) == 582,
            {
                "active": len(active),
                "calibrated": len(calibrated),
                "payload": len(players),
            },
            582,
        ),
        (
            "player_ids_preserved",
            set(active["player_id"]) == set(calibrated["player_id"]),
            int(calibrated["player_id"].nunique()),
            582,
        ),
        (
            "ratings_complete",
            not new_values.isna().any(),
            int(new_values.notna().sum()),
            582,
        ),
        (
            "ratings_within_bounds",
            bool(
                new_values.ge(RATING_MINIMUM).all()
                and new_values.le(RATING_MAXIMUM).all()
            ),
            {
                "minimum": float(new_values.min()),
                "maximum": float(new_values.max()),
            },
            f"{RATING_MINIMUM}-{RATING_MAXIMUM}",
        ),
        (
            "one_decimal_ratings",
            bool(np.allclose(new_values, new_values.round(1))),
            True,
            True,
        ),
        (
            "potential_not_below_overall",
            bool((potential + 1e-9 >= new_values).all()),
            int((potential + 1e-9 < new_values).sum()),
            0,
        ),
        (
            "matched_count_consistent_with_audit",
            int(matched.sum()) == expected_matched,
            int(matched.sum()),
            expected_matched,
        ),
        (
            "real_reliability_fields_complete",
            all(value == 0 for value in reliability_missing.values()),
            reliability_missing,
            "all zero",
        ),
        (
            "unavailable_impact_role_fields_not_used",
            (
                "current_impact_rank_pct" not in calibrated.columns
                and "role_burden_rank_pct" not in calibrated.columns
            ),
            {
                "current_impact_rank_pct_present": (
                    "current_impact_rank_pct" in calibrated.columns
                ),
                "role_burden_rank_pct_present": (
                    "role_burden_rank_pct" in calibrated.columns
                ),
            },
            "both false",
        ),
        (
            "reliability_weighted_formula_exact",
            bool(formula_error.le(1e-9).all()),
            float(formula_error.max()),
            0.0,
        ),
        (
            "external_weights_within_bounds",
            bool(
                calibrated["external_benchmark_weight"].between(
                    0.0,
                    MAX_EXTERNAL_WEIGHT,
                ).all()
            ),
            {
                "minimum": float(
                    calibrated["external_benchmark_weight"].min()
                ),
                "maximum": float(
                    calibrated["external_benchmark_weight"].max()
                ),
            },
            f"0.0-{MAX_EXTERNAL_WEIGHT}",
        ),
        (
            "matched_mean_model_weight_is_majority",
            float(
                matched_frame["statistical_model_weight"].mean()
            )
            >= 0.60,
            round(
                float(
                    matched_frame["statistical_model_weight"].mean()
                ),
                4,
            ),
            ">= 0.60",
        ),
        (
            "matched_median_model_weight_is_majority",
            float(
                matched_frame["statistical_model_weight"].median()
            )
            >= 0.65,
            round(
                float(
                    matched_frame["statistical_model_weight"].median()
                ),
                4,
            ),
            ">= 0.65",
        ),
        (
            "model_rank_signal_preserved",
            float(old_new_spearman) >= 0.94,
            round(float(old_new_spearman), 4),
            ">= 0.94 Spearman",
        ),
        (
            "not_a_direct_2k_copy",
            float(
                matched_frame[
                    "absolute_difference_from_current_2k"
                ].mean()
            )
            >= 0.75,
            round(
                float(
                    matched_frame[
                        "absolute_difference_from_current_2k"
                    ].mean()
                ),
                3,
            ),
            "mean absolute difference from 2K >= 0.75",
        ),
        (
            "established_extreme_disagreements_reduced",
            post_extreme_established < pre_extreme_established,
            {
                "before": pre_extreme_established,
                "after": post_extreme_established,
            },
            "after < before",
        ),
        (
            "median_realistic",
            75.0 <= float(new_values.median()) <= 78.0,
            float(new_values.median()),
            "75.0-78.0",
        ),
        (
            "ninety_plus_realistic",
            15 <= int(new_values.ge(90).sum()) <= 30,
            int(new_values.ge(90).sum()),
            "15-30",
        ),
        (
            "eighty_five_plus_realistic",
            50 <= int(new_values.ge(85).sum()) <= 90,
            int(new_values.ge(85).sum()),
            "50-90",
        ),
        (
            "eighty_plus_realistic",
            140 <= int(new_values.ge(80).sum()) <= 215,
            int(new_values.ge(80).sum()),
            "140-215",
        ),
        (
            "role_labels_match_new_ovr_bands",
            bool(calibrated["new_role_label"].eq(expected_labels).all()),
            int(
                (~calibrated["new_role_label"].eq(expected_labels)).sum()
            ),
            0,
        ),
        (
            "benchmark_sanity_checks",
            all(benchmark_checks.values()),
            benchmark_checks,
            "all true",
        ),
        (
            "preview_only",
            bool(
                candidate.get("v4_8_1_calibration", {}).get(
                    "preview_only"
                )
            ),
            candidate.get("v4_8_1_calibration", {}).get(
                "preview_only"
            ),
            True,
        ),
    ]

    return [
        {
            "check_name": name,
            "passed": bool(passed),
            "observed": json.dumps(observed, ensure_ascii=False)
            if isinstance(observed, (dict, list))
            else observed,
            "expected": expected,
        }
        for name, passed, observed, expected in checks
    ]


def benchmark_rows(calibrated: pd.DataFrame) -> pd.DataFrame:
    targets = {
        name.replace("’", "'")
        for name in BENCHMARK_NAMES
    }
    mask = (
        calibrated["player_name"]
        .str.replace("’", "'", regex=False)
        .isin(targets)
    )

    columns = [
        "player_id",
        "player_name",
        "team_abbreviation",
        "age",
        "career_seasons",
        "evidence_weight",
        "current_core_rating_v44",
        "history_quality_score_v43",
        "history_recent3_value_percentile",
        "availability_rating",
        "minutes_per_game",
        "old_league_rank",
        "old_overall",
        "source_overall",
        "distribution_mapped_model_overall",
        "preblend_difference_from_current_2k",
        "statistical_model_weight",
        "external_benchmark_weight",
        "reliability_weight_reason",
        "new_league_rank",
        "new_overall",
        "overall_change",
        "difference_from_current_2k",
        "old_role_label",
        "new_role_label",
        "old_potential",
        "new_potential",
        "old_future",
    ]

    return calibrated.loc[mask, columns].sort_values(
        "new_league_rank"
    )


def run_self_test() -> int:
    sample_base = {
        "matched_to_current_2k": True,
        "evidence_weight": 0.88,
        "current_core_rating_v44": 86.0,
        "history_quality_score_v43": 84.0,
        "history_recent3_value_percentile": 84.0,
        "availability_rating": 82.0,
        "minutes_per_game": 30.0,
        "team_abbreviation": "DEN",
    }

    young = pd.Series(
        {
            **sample_base,
            "career_seasons": 1.0,
            "source_overall": 82.0,
            "distribution_mapped_model_overall": 84.0,
        }
    )
    early_large = pd.Series(
        {
            **sample_base,
            "career_seasons": 3.0,
            "source_overall": 81.0,
            "distribution_mapped_model_overall": 86.0,
        }
    )
    established = pd.Series(
        {
            **sample_base,
            "career_seasons": 8.0,
            "source_overall": 88.0,
            "distribution_mapped_model_overall": 90.0,
        }
    )
    established_extreme = pd.Series(
        {
            **sample_base,
            "career_seasons": 8.0,
            "source_overall": 89.0,
            "distribution_mapped_model_overall": 95.0,
        }
    )
    fringe = pd.Series(
        {
            **sample_base,
            "career_seasons": 2.0,
            "source_overall": 67.0,
            "distribution_mapped_model_overall": 79.0,
            "team_abbreviation": "",
        }
    )
    strong_support = pd.Series(
        {
            **sample_base,
            "career_seasons": 8.0,
            "evidence_weight": 0.98,
            "current_core_rating_v44": 92.0,
            "history_quality_score_v43": 92.0,
            "history_recent3_value_percentile": 93.0,
            "availability_rating": 88.0,
            "minutes_per_game": 34.0,
            "source_overall": 89.0,
            "distribution_mapped_model_overall": 90.0,
        }
    )

    tests = {
        "young_high_confidence_weight_10_percent": math.isclose(
            external_weight_and_reason(young)[0],
            0.10,
        ),
        "early_large_disagreement_weight_35_percent": math.isclose(
            external_weight_and_reason(early_large)[0],
            0.35,
        ),
        "established_weight_30_percent": math.isclose(
            external_weight_and_reason(established)[0],
            0.30,
        ),
        "extreme_established_weight_60_percent": math.isclose(
            external_weight_and_reason(established_extreme)[0],
            0.60,
        ),
        "fringe_outlier_weight_55_percent": math.isclose(
            external_weight_and_reason(fringe)[0],
            0.55,
        ),
        "strong_support_reduces_weight": math.isclose(
            external_weight_and_reason(strong_support)[0],
            0.20,
        ),
        "98_is_mvp": quality_tier_label(98.0)
        == "MVP-level superstar",
        "90_is_all_star": quality_tier_label(90.0)
        == "All-Star caliber",
        "80_is_solid_starter": quality_tier_label(80.0)
        == "Solid starter",
    }

    print(
        json.dumps(
            {
                "script": SCRIPT_VERSION,
                "checks": tests,
            },
            indent=2,
        )
    )

    if not all(tests.values()):
        raise AssertionError("One or more self-tests failed.")

    return 0

def main() -> int:
    args = parse_args()

    if args.self_test:
        return run_self_test()

    root = project_root()
    source_path = resolve(root, args.source_json)
    audit_path = resolve(root, args.audit_csv)
    candidate_path = resolve(root, args.candidate_json)
    player_audit_path = resolve(root, args.player_audit_csv)
    summary_path = resolve(root, args.summary_json)
    validation_path = resolve(root, args.validation_csv)
    benchmarks_path = resolve(root, args.benchmarks_csv)

    for path in (
        candidate_path,
        player_audit_path,
        summary_path,
        validation_path,
        benchmarks_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("V4.8.1 SCHEMA-CORRECTED RELIABILITY-WEIGHTED RATINGS PREVIEW")
    print("=" * 100)
    print("Original statistical payload:", source_path)
    print("Current 2K audit:", audit_path)

    payload = load_payload(source_path)
    active = payload_frame(payload)
    audit = load_audit(audit_path)
    calibrated = calibrate(active, audit)
    candidate = apply_candidate(payload, calibrated)
    validations = pd.DataFrame(
        validation_rows(
            active,
            audit,
            calibrated,
            candidate,
        )
    )
    benchmarks = benchmark_rows(calibrated)

    old_distribution = distribution(calibrated, "old_overall")
    new_distribution = distribution(calibrated, "new_overall")
    source_distribution = distribution(
        calibrated.loc[
            calibrated["matched_to_current_2k"]
        ],
        "source_overall",
    )

    matched = calibrated.loc[
        calibrated["matched_to_current_2k"]
    ]
    old_new_spearman = calibrated[
        ["old_overall", "new_overall"]
    ].corr(method="spearman").iloc[0, 1]

    weight_distribution = (
        matched["external_benchmark_weight"]
        .value_counts()
        .sort_index()
        .to_dict()
    )

    summary = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "preview_only": True,
        "live_alias_modified": False,
        "source_release": clean_text(payload.get("release_name")),
        "counts": {
            "players": int(len(calibrated)),
            "matched_to_current_2k": int(
                calibrated["matched_to_current_2k"].sum()
            ),
            "unmatched_to_current_2k": int(
                (~calibrated["matched_to_current_2k"]).sum()
            ),
            "role_labels_changed": int(
                calibrated["role_label_changed"].sum()
            ),
            "potential_rows_raised_only_to_ovr_floor": int(
                calibrated["potential_change"].gt(0).sum()
            ),
        },
        "model_originality": {
            "old_model_to_new_ovr_spearman": round(
                float(old_new_spearman),
                4,
            ),
            "mean_statistical_model_weight_matched": round(
                float(matched["statistical_model_weight"].mean()),
                4,
            ),
            "median_statistical_model_weight_matched": round(
                float(matched["statistical_model_weight"].median()),
                4,
            ),
            "mean_absolute_difference_from_current_2k": round(
                float(
                    matched[
                        "absolute_difference_from_current_2k"
                    ].mean()
                ),
                4,
            ),
            "ranking_source": (
                "Recomputed from reliability-weighted OVR; no 2K rank copied."
            ),
        },
        "external_weight_distribution": {
            str(key): int(value)
            for key, value in weight_distribution.items()
        },
        "old_distribution": old_distribution,
        "new_distribution": new_distribution,
        "matched_current_2k_distribution": source_distribution,
        "validation": {
            "passed": bool(validations["passed"].all()),
            "checks_passed": int(validations["passed"].sum()),
            "checks_total": int(len(validations)),
        },
        "outputs": {
            "candidate_json": str(candidate_path),
            "player_audit_csv": str(player_audit_path),
            "summary_json": str(summary_path),
            "validation_csv": str(validation_path),
            "benchmarks_csv": str(benchmarks_path),
        },
    }

    candidate_path.write_text(
        json.dumps(
            candidate,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    calibrated.to_csv(player_audit_path, index=False)
    validations.to_csv(validation_path, index=False)
    benchmarks.to_csv(benchmarks_path, index=False)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("\nOLD DISTRIBUTION")
    print(json.dumps(old_distribution, indent=2))

    print("\nNEW RELIABILITY-WEIGHTED DISTRIBUTION")
    print(json.dumps(new_distribution, indent=2))

    print("\nMATCHED CURRENT 2K DISTRIBUTION")
    print(json.dumps(source_distribution, indent=2))

    print("\nMODEL ORIGINALITY")
    print(
        json.dumps(
            summary["model_originality"],
            indent=2,
        )
    )

    print("\nEXTERNAL WEIGHT DISTRIBUTION")
    print(json.dumps(summary["external_weight_distribution"], indent=2))

    print("\nBENCHMARK PLAYERS")
    print(benchmarks.to_string(index=False))

    print("\nTOP 30")
    print(
        calibrated[
            [
                "new_league_rank",
                "player_name",
                "team_abbreviation",
                "new_overall",
                "new_role_label",
                "current_core_rating_v44",
                "history_quality_score_v43",
                "evidence_weight",
                "statistical_model_weight",
                "external_benchmark_weight",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )

    print("\nVALIDATION")
    print(validations.to_string(index=False))

    print("\nOutputs:")
    for path in (
        candidate_path,
        player_audit_path,
        summary_path,
        validation_path,
        benchmarks_path,
    ):
        print(" ", path)

    print("\nLive alias was not modified.")

    if not validations["passed"].all():
        raise AssertionError(
            "V4.8.1 schema-corrected reliability preview failed one or more validations."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())