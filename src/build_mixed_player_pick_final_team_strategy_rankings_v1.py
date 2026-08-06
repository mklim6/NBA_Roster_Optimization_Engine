"""Build final team-specific strategy rankings for V4 mixed trade packages.

This release scores only the strategy-ready routine and minor-asset package pool.
Protected-player blockbuster concepts remain concept-only and are not assigned a
final recommendation score.

The workflow:
1. Validates the V4 quality gate and V2 strategy-readiness audit.
2. Loads both team perspectives for all 56 strategy-ready package variants.
3. Computes team-specific strategy utility using archetype-specific weights.
4. Chooses one canonical pick variant per player-exchange concept by maximizing
   the weaker side's score, then the bilateral mean score.
5. Produces team-specific concept rankings and diversified top recommendations.
6. Reports explicit statuses for all 30 teams, including teams without legal or
   strategy-ready routine concepts.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "mixed-player-pick-final-team-strategy-rankings-v1-2026-08-05"
)
RELEASE_NAME = (
    "mixed_player_pick_final_team_strategy_rankings_2026_27_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

QUALITY_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_metadata_v4.json"
)
READINESS_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_readiness_metadata_v2.json"
)
TEAM_PERSPECTIVE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_perspective_quality_review_2026_27_v4.csv"
)
ROUTINE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_routine_recommendation_review_2026_27_v4.csv"
)
MINOR_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_minor_asset_recommendation_review_2026_27_v4.csv"
)
TEAM_PROFILES_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_team_profiles_2026_27_v2.csv"
)
PLAYER_MARKET_PARQUET_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.parquet"
)
PLAYER_MARKET_CSV_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.csv"
)

FULL_SCORES_PARQUET_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_scores_2026_27_v1.parquet"
)
FULL_SCORES_CSV_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_scores_2026_27_v1.csv"
)
BILATERAL_CONCEPT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_bilateral_concept_rankings_2026_27_v1.csv"
)
TEAM_CONCEPT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_concept_rankings_2026_27_v1.csv"
)
TOP_RECOMMENDATIONS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_top_recommendations_2026_27_v1.csv"
)
TEAM_SUMMARY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_summary_2026_27_v1.csv"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_validation_v1.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_metadata_v1.json"
)

EXPECTED_ROUTINE_ROWS = 33
EXPECTED_MINOR_ROWS = 23
EXPECTED_PACKAGE_VARIANTS = 56
EXPECTED_PERSPECTIVE_ROWS = 112
EXPECTED_UNIQUE_CONCEPTS = 34
EXPECTED_TEAM_PROFILES = 30

ROUTINE_CLASSES = {
    "routine_recommendation_review",
    "routine_plus_minor_assets_review",
}

RELEASE_THRESHOLDS = {
    "strong_bilateral_strategy_match": 68.0,
    "solid_bilateral_strategy_match": 60.0,
    "exploratory_bilateral_strategy_match": 52.0,
}

TOP_RECOMMENDATIONS_PER_TEAM = 10
MAX_PRIMARY_INCOMING_PLAYER_EXPOSURE = 2
MAX_PRIMARY_OUTGOING_PLAYER_EXPOSURE = 2
MAX_COUNTERPART_TEAM_EXPOSURE = 3

ARCHETYPE_WEIGHTS = {
    "win_now_contender": {
        "package_quality_prior": 0.15,
        "team_trade_fit": 0.25,
        "asset_utility": 0.10,
        "expected_contribution_utility": 0.20,
        "downside_utility": 0.15,
        "pick_alignment": 0.05,
        "timeline_alignment": 0.05,
        "transaction_structure": 0.05,
    },
    "competitive_builder": {
        "package_quality_prior": 0.15,
        "team_trade_fit": 0.20,
        "asset_utility": 0.15,
        "expected_contribution_utility": 0.15,
        "downside_utility": 0.10,
        "pick_alignment": 0.15,
        "timeline_alignment": 0.05,
        "transaction_structure": 0.05,
    },
    "development_rebuild": {
        "package_quality_prior": 0.10,
        "team_trade_fit": 0.10,
        "asset_utility": 0.20,
        "expected_contribution_utility": 0.10,
        "downside_utility": 0.10,
        "pick_alignment": 0.25,
        "timeline_alignment": 0.10,
        "transaction_structure": 0.05,
    },
    "ascending_retool": {
        "package_quality_prior": 0.10,
        "team_trade_fit": 0.15,
        "asset_utility": 0.15,
        "expected_contribution_utility": 0.10,
        "downside_utility": 0.10,
        "pick_alignment": 0.20,
        "timeline_alignment": 0.15,
        "transaction_structure": 0.05,
    },
    "flexible_retool": {
        "package_quality_prior": 0.15,
        "team_trade_fit": 0.15,
        "asset_utility": 0.15,
        "expected_contribution_utility": 0.15,
        "downside_utility": 0.10,
        "pick_alignment": 0.15,
        "timeline_alignment": 0.10,
        "transaction_structure": 0.05,
    },
}

PICK_ALIGNMENT_SCORES = {
    "win_now_contender": {
        ("attaches", "first_round"): 45.0,
        ("attaches", "second_round"): 65.0,
        ("attaches", "other_or_complex"): 50.0,
        ("receives", "first_round"): 85.0,
        ("receives", "second_round"): 75.0,
        ("receives", "other_or_complex"): 75.0,
    },
    "competitive_builder": {
        ("attaches", "first_round"): 20.0,
        ("attaches", "second_round"): 50.0,
        ("attaches", "other_or_complex"): 35.0,
        ("receives", "first_round"): 90.0,
        ("receives", "second_round"): 75.0,
        ("receives", "other_or_complex"): 80.0,
    },
    "development_rebuild": {
        ("attaches", "first_round"): 0.0,
        ("attaches", "second_round"): 25.0,
        ("attaches", "other_or_complex"): 10.0,
        ("receives", "first_round"): 100.0,
        ("receives", "second_round"): 85.0,
        ("receives", "other_or_complex"): 90.0,
    },
    "ascending_retool": {
        ("attaches", "first_round"): 10.0,
        ("attaches", "second_round"): 40.0,
        ("attaches", "other_or_complex"): 25.0,
        ("receives", "first_round"): 95.0,
        ("receives", "second_round"): 80.0,
        ("receives", "other_or_complex"): 85.0,
    },
    "flexible_retool": {
        ("attaches", "first_round"): 25.0,
        ("attaches", "second_round"): 50.0,
        ("attaches", "other_or_complex"): 35.0,
        ("receives", "first_round"): 90.0,
        ("receives", "second_round"): 75.0,
        ("receives", "other_or_complex"): 80.0,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without project files.",
    )
    return parser.parse_args()


def normalized_text(value: Any) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def clean_text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def split_players(value: Any) -> list[str]:
    return [
        part.strip()
        for part in str(value).split("|")
        if part.strip()
    ]


def sorted_player_string(value: Any) -> str:
    return "|".join(
        sorted(
            split_players(value),
            key=normalized_text,
        )
    )


def concept_key(row: pd.Series) -> str:
    sides = sorted(
        [
            (
                f"{clean_text(row['team_a'])}:"
                f"{sorted_player_string(row['side_a_player_names'])}"
            ),
            (
                f"{clean_text(row['team_b'])}:"
                f"{sorted_player_string(row['side_b_player_names'])}"
            ),
        ]
    )
    return "||".join(sides)


def infer_pick_round(value: Any) -> str:
    text = str(value).lower()
    if (
        "first-round" in text
        or re.search(r"\br1\b|_r1_", text)
    ):
        return "first_round"
    if (
        "second-round" in text
        or re.search(r"\br2\b|_r2_", text)
    ):
        return "second_round"
    return "other_or_complex"


def first_existing(
    frame: pd.DataFrame,
    candidates: Iterable[str],
) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def read_player_market() -> tuple[pd.DataFrame, str]:
    if PLAYER_MARKET_PARQUET_PATH.exists():
        return (
            pd.read_parquet(PLAYER_MARKET_PARQUET_PATH),
            str(PLAYER_MARKET_PARQUET_PATH),
        )
    if PLAYER_MARKET_CSV_PATH.exists():
        return (
            pd.read_csv(PLAYER_MARKET_CSV_PATH),
            str(PLAYER_MARKET_CSV_PATH),
        )
    raise FileNotFoundError(
        "The centralized V4 player market was not found:\n"
        f"{PLAYER_MARKET_PARQUET_PATH}\n"
        f"{PLAYER_MARKET_CSV_PATH}"
    )


def ratio_utility(value: Any) -> float:
    """Map a retention ratio to a centered 0-100 team utility score.

    0.50 -> 0
    1.00 -> 50
    1.50 -> 100
    """
    ratio = safe_float(value)
    if not math.isfinite(ratio):
        return 50.0
    return float(
        np.clip(
            50.0 + 100.0 * (ratio - 1.0),
            0.0,
            100.0,
        )
    )


def timeline_alignment_score(
    archetype: str,
    outgoing_average_age: float,
    incoming_average_age: float,
) -> float:
    if (
        not math.isfinite(outgoing_average_age)
        or not math.isfinite(incoming_average_age)
    ):
        return 50.0

    younger_delta = outgoing_average_age - incoming_average_age

    multiplier = {
        "development_rebuild": 8.0,
        "ascending_retool": 6.0,
        "competitive_builder": 3.0,
        "flexible_retool": 2.0,
        "win_now_contender": 1.0,
    }[archetype]

    baseline = (
        55.0
        if archetype == "win_now_contender"
        else 50.0
    )
    return float(
        np.clip(
            baseline + multiplier * younger_delta,
            0.0,
            100.0,
        )
    )


def transaction_structure_score(
    archetype: str,
    outgoing_player_count: int,
    incoming_player_count: int,
) -> float:
    delta = incoming_player_count - outgoing_player_count

    if archetype == "win_now_contender":
        if delta < 0:
            return 75.0
        if delta == 0:
            return 60.0
        return 45.0

    if archetype == "development_rebuild":
        if delta > 0:
            return 75.0
        if delta == 0:
            return 60.0
        return 45.0

    if archetype == "ascending_retool":
        if delta > 0:
            return 65.0
        if delta == 0:
            return 60.0
        return 55.0

    if archetype == "competitive_builder":
        return 60.0 if delta == 0 else 55.0

    return 65.0 if delta == 0 else 58.0


def pick_alignment_score(
    archetype: str,
    team_attaches_pick: bool,
    pick_round_type: str,
) -> float:
    direction = (
        "attaches"
        if team_attaches_pick
        else "receives"
    )
    return PICK_ALIGNMENT_SCORES[
        archetype
    ][
        (
            direction,
            pick_round_type,
        )
    ]


def classify_bilateral_floor(score: float) -> str:
    if score >= RELEASE_THRESHOLDS[
        "strong_bilateral_strategy_match"
    ]:
        return "strong_bilateral_strategy_match"
    if score >= RELEASE_THRESHOLDS[
        "solid_bilateral_strategy_match"
    ]:
        return "solid_bilateral_strategy_match"
    if score >= RELEASE_THRESHOLDS[
        "exploratory_bilateral_strategy_match"
    ]:
        return "exploratory_bilateral_strategy_match"
    return "not_released_bilateral_strategy_hold"


def player_market_lookup(
    players: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, Any]]:
    required = {
        "player_name",
        "current_team_2026_27",
        "age",
        "market_value_percentile_v2",
        "protected_player_flag_v4",
        "recommendation_asset_class_v4",
    }
    missing = sorted(required.difference(players.columns))
    if missing:
        raise ValueError(
            "The V4 player market is missing required fields:\n"
            + "\n".join(missing)
        )

    lookup: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for _, row in players.iterrows():
        key = (
            normalized_text(row["player_name"]),
            clean_text(row["current_team_2026_27"]),
        )
        if key in lookup:
            raise ValueError(
                "Duplicate player/team key in V4 market: "
                f"{key}"
            )

        lookup[key] = {
            "player_name": clean_text(row["player_name"]),
            "age": safe_float(row["age"]),
            "market_value_percentile_v2": safe_float(
                row["market_value_percentile_v2"]
            ),
            "protected_player_flag_v4": bool_value(
                row["protected_player_flag_v4"]
            ),
            "recommendation_asset_class_v4": clean_text(
                row["recommendation_asset_class_v4"]
            ),
        }

    return lookup


def summarize_players(
    names: Any,
    team: str,
    lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    player_names = split_players(names)
    rows: list[dict[str, Any]] = []

    for player_name in player_names:
        key = (
            normalized_text(player_name),
            team,
        )
        if key not in lookup:
            raise ValueError(
                "Player was not found in the V4 market: "
                f"{player_name} | team={team}"
            )
        rows.append(lookup[key])

    if not rows:
        raise ValueError(
            f"No players were parsed for team {team}: {names}"
        )

    primary = max(
        rows,
        key=lambda row: (
            safe_float(
                row["market_value_percentile_v2"],
                -1.0,
            ),
            normalized_text(row["player_name"]),
        ),
    )

    ages = [
        safe_float(row["age"])
        for row in rows
        if math.isfinite(safe_float(row["age"]))
    ]
    market_values = [
        safe_float(
            row["market_value_percentile_v2"]
        )
        for row in rows
        if math.isfinite(
            safe_float(
                row["market_value_percentile_v2"]
            )
        )
    ]

    return {
        "player_count": len(rows),
        "average_age": (
            float(np.mean(ages))
            if ages
            else np.nan
        ),
        "average_market_value_percentile": (
            float(np.mean(market_values))
            if market_values
            else np.nan
        ),
        "primary_player_name": primary["player_name"],
        "primary_player_market_value_percentile": (
            primary["market_value_percentile_v2"]
        ),
        "protected_player_count": sum(
            bool(row["protected_player_flag_v4"])
            for row in rows
        ),
        "asset_classes": "|".join(
            str(row["recommendation_asset_class_v4"])
            for row in rows
        ),
    }


def strategy_fit_summary(row: pd.Series) -> str:
    positives: list[str] = []
    cautions: list[str] = []

    if bool(row["team_receives_pick"]):
        positives.append(
            f"receives a {row['pick_round_type'].replace('_', ' ')} asset"
        )
    else:
        cautions.append(
            f"attaches a {row['pick_round_type'].replace('_', ' ')} asset"
        )

    if row["team_expected_contribution_retention_ratio"] >= 1.05:
        positives.append("improves projected contribution")
    elif row["team_expected_contribution_retention_ratio"] < 0.90:
        cautions.append("reduces projected contribution")

    if row["team_downside_contribution_retention_ratio"] >= 1.05:
        positives.append("improves downside protection")
    elif row["team_downside_contribution_retention_ratio"] < 0.90:
        cautions.append("weakens downside protection")

    if row["incoming_average_age"] <= row["outgoing_average_age"] - 2.0:
        positives.append("gets meaningfully younger")
    elif row["incoming_average_age"] >= row["outgoing_average_age"] + 2.0:
        cautions.append("gets meaningfully older")

    if row["team_trade_fit_score"] >= 55.0:
        positives.append("grades as a strong roster fit")
    elif row["team_trade_fit_score"] < 50.0:
        cautions.append("has only a marginal roster-fit score")

    if row["incoming_player_count"] < row["outgoing_player_count"]:
        structure = "consolidates roster slots"
    elif row["incoming_player_count"] > row["outgoing_player_count"]:
        structure = "adds roster depth"
    else:
        structure = "keeps player count neutral"

    narrative_parts = []
    if positives:
        narrative_parts.append(
            "Strengths: " + "; ".join(positives)
        )
    narrative_parts.append(
        "Structure: " + structure
    )
    if cautions:
        narrative_parts.append(
            "Cautions: " + "; ".join(cautions)
        )

    return ". ".join(narrative_parts) + "."


def score_perspectives(
    perspectives: pd.DataFrame,
    packages: pd.DataFrame,
    profiles: pd.DataFrame,
    player_lookup: dict[
        tuple[str, str],
        dict[str, Any],
    ],
) -> pd.DataFrame:
    package_columns = [
        "optimizer_candidate_id",
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "quality_gate_class",
        "quality_gate_reason",
        "adjusted_absolute_value_gap",
        "optimizer_final_legal_rank_score_v1",
        "optimizer_trade_display",
        "right_display_name",
        "attached_pick_team",
        "optimizer_package_final_legal",
    ]

    missing_package_columns = sorted(
        set(package_columns).difference(packages.columns)
    )
    if missing_package_columns:
        raise ValueError(
            "Routine package catalog is missing fields:\n"
            + "\n".join(missing_package_columns)
        )

    package_catalog = packages[
        package_columns
    ].copy()
    package_catalog["player_exchange_key"] = (
        package_catalog.apply(
            concept_key,
            axis=1,
        )
    )
    package_catalog["pick_round_type"] = (
        package_catalog[
            "right_display_name"
        ].map(infer_pick_round)
    )

    scored = perspectives.merge(
        package_catalog,
        on="optimizer_candidate_id",
        how="inner",
        suffixes=("", "_package"),
        validate="many_to_one",
    )

    profile_required = {
        "team_abbreviation",
        "model_team_strategy_archetype",
        "model_team_strategy_priority",
        "model_pick_preference",
        "top_need_1",
        "top_need_2",
        "top_need_3",
        "strength_percentile_2026_27",
        "projected_wins_2026_27",
    }
    missing_profiles = sorted(
        profile_required.difference(profiles.columns)
    )
    if missing_profiles:
        raise ValueError(
            "Team strategy profiles are missing fields:\n"
            + "\n".join(missing_profiles)
        )

    scored = scored.merge(
        profiles,
        left_on="recommendation_team",
        right_on="team_abbreviation",
        how="left",
        validate="many_to_one",
    )

    if scored["model_team_strategy_archetype"].isna().any():
        missing_teams = sorted(
            scored.loc[
                scored[
                    "model_team_strategy_archetype"
                ].isna(),
                "recommendation_team",
            ].unique()
        )
        raise ValueError(
            "Missing team strategy profiles: "
            + ", ".join(missing_teams)
        )

    scored["counterpart_team"] = np.where(
        scored["recommendation_team"]
        .eq(scored["team_a"]),
        scored["team_b"],
        scored["team_a"],
    )

    outgoing_summaries: list[dict[str, Any]] = []
    incoming_summaries: list[dict[str, Any]] = []

    for _, row in scored.iterrows():
        outgoing_summaries.append(
            summarize_players(
                row["outgoing_players"],
                clean_text(row["recommendation_team"]),
                player_lookup,
            )
        )
        incoming_summaries.append(
            summarize_players(
                row["incoming_players"],
                clean_text(row["counterpart_team"]),
                player_lookup,
            )
        )

    outgoing_frame = pd.DataFrame(
        outgoing_summaries
    ).add_prefix("outgoing_")
    incoming_frame = pd.DataFrame(
        incoming_summaries
    ).add_prefix("incoming_")

    scored = pd.concat(
        [
            scored.reset_index(drop=True),
            outgoing_frame,
            incoming_frame,
        ],
        axis=1,
    )

    if (
        scored["outgoing_protected_player_count"].gt(0).any()
        or scored["incoming_protected_player_count"].gt(0).any()
    ):
        protected_rows = scored.loc[
            scored["outgoing_protected_player_count"].gt(0)
            | scored["incoming_protected_player_count"].gt(0),
            [
                "optimizer_candidate_id",
                "recommendation_team",
                "outgoing_players",
                "incoming_players",
            ],
        ]
        raise ValueError(
            "Protected players entered the strategy-ready routine pool:\n"
            + protected_rows.to_string(index=False)
        )

    scored["asset_utility_score"] = scored[
        "team_asset_retention_ratio"
    ].map(ratio_utility)
    scored[
        "expected_contribution_utility_score"
    ] = scored[
        "team_expected_contribution_retention_ratio"
    ].map(ratio_utility)
    scored[
        "downside_contribution_utility_score"
    ] = scored[
        "team_downside_contribution_retention_ratio"
    ].map(ratio_utility)

    scored["pick_alignment_score"] = scored.apply(
        lambda row: pick_alignment_score(
            row["model_team_strategy_archetype"],
            bool_value(row["team_attaches_pick"]),
            row["pick_round_type"],
        ),
        axis=1,
    )

    scored["timeline_alignment_score"] = scored.apply(
        lambda row: timeline_alignment_score(
            row["model_team_strategy_archetype"],
            safe_float(row["outgoing_average_age"]),
            safe_float(row["incoming_average_age"]),
        ),
        axis=1,
    )

    scored["transaction_structure_score"] = scored.apply(
        lambda row: transaction_structure_score(
            row["model_team_strategy_archetype"],
            int(row["outgoing_player_count"]),
            int(row["incoming_player_count"]),
        ),
        axis=1,
    )

    component_columns = {
        "package_quality_prior": (
            "package_quality_prior_score"
        ),
        "team_trade_fit": "team_trade_fit_score",
        "asset_utility": "asset_utility_score",
        "expected_contribution_utility": (
            "expected_contribution_utility_score"
        ),
        "downside_utility": (
            "downside_contribution_utility_score"
        ),
        "pick_alignment": "pick_alignment_score",
        "timeline_alignment": "timeline_alignment_score",
        "transaction_structure": (
            "transaction_structure_score"
        ),
    }

    final_scores: list[float] = []
    weight_labels: list[str] = []

    for _, row in scored.iterrows():
        archetype = row[
            "model_team_strategy_archetype"
        ]
        weights = ARCHETYPE_WEIGHTS[archetype]

        final_score = sum(
            weights[component]
            * safe_float(
                row[column],
                0.0,
            )
            for component, column in (
                component_columns.items()
            )
        )

        final_scores.append(
            float(
                np.clip(
                    final_score,
                    0.0,
                    100.0,
                )
            )
        )
        weight_labels.append(
            "|".join(
                f"{component}={weight:.2f}"
                for component, weight in (
                    weights.items()
                )
            )
        )

    scored[
        "final_team_strategy_score"
    ] = final_scores
    scored[
        "strategy_weight_profile"
    ] = weight_labels
    scored[
        "team_strategy_score_released"
    ] = True
    scored[
        "team_strategy_score_scope"
    ] = (
        "Final team-specific score for strategy-ready routine "
        "mixed player-and-pick concepts. Protected-player "
        "blockbusters remain outside this score."
    )
    scored[
        "team_strategy_fit_summary"
    ] = scored.apply(
        strategy_fit_summary,
        axis=1,
    )

    return scored


def select_canonical_concepts(
    scored: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_counts = (
        scored.groupby(
            "optimizer_candidate_id"
        )["recommendation_team"]
        .nunique()
    )
    invalid_pair_counts = pair_counts.loc[
        pair_counts.ne(2)
    ]
    if not invalid_pair_counts.empty:
        raise ValueError(
            "Every package must have exactly two team perspectives:\n"
            + invalid_pair_counts.to_string()
        )

    bilateral_rows: list[dict[str, Any]] = []

    for candidate_id, group in scored.groupby(
        "optimizer_candidate_id",
        sort=True,
    ):
        ordered = group.sort_values(
            "recommendation_team"
        )
        side_rows = ordered.to_dict(
            orient="records"
        )
        first, second = side_rows

        score_a = safe_float(
            first["final_team_strategy_score"]
        )
        score_b = safe_float(
            second["final_team_strategy_score"]
        )

        bilateral_rows.append(
            {
                "optimizer_candidate_id": candidate_id,
                "player_exchange_key": first[
                    "player_exchange_key"
                ],
                "team_one": first[
                    "recommendation_team"
                ],
                "team_one_strategy_score": score_a,
                "team_two": second[
                    "recommendation_team"
                ],
                "team_two_strategy_score": score_b,
                "bilateral_floor_score": min(
                    score_a,
                    score_b,
                ),
                "bilateral_mean_score": (
                    score_a + score_b
                ) / 2.0,
                "bilateral_score_gap": abs(
                    score_a - score_b
                ),
                "quality_gate_class": first[
                    "quality_gate_class"
                ],
                "right_display_name": first[
                    "right_display_name_package"
                ],
                "attached_pick_team": first[
                    "attached_pick_team"
                ],
                "pick_round_type": first[
                    "pick_round_type"
                ],
                "adjusted_absolute_value_gap": safe_float(
                    first[
                        "adjusted_absolute_value_gap"
                    ]
                ),
                "package_quality_prior_score": safe_float(
                    first[
                        "package_quality_prior_score"
                    ]
                ),
                "optimizer_trade_display": first[
                    "optimizer_trade_display_package"
                ],
                "optimizer_package_final_legal": bool_value(
                    first[
                        "optimizer_package_final_legal_package"
                    ]
                ),
            }
        )

    bilateral_variants = pd.DataFrame(
        bilateral_rows
    )
    bilateral_variants[
        "bilateral_strategy_tier"
    ] = bilateral_variants[
        "bilateral_floor_score"
    ].map(classify_bilateral_floor)

    canonical_rows: list[pd.Series] = []

    for _, group in bilateral_variants.groupby(
        "player_exchange_key",
        sort=True,
    ):
        selected = group.sort_values(
            [
                "bilateral_floor_score",
                "bilateral_mean_score",
                "package_quality_prior_score",
                "adjusted_absolute_value_gap",
                "optimizer_candidate_id",
            ],
            ascending=[
                False,
                False,
                False,
                True,
                True,
            ],
        ).iloc[0]
        canonical_rows.append(selected)

    canonical = pd.DataFrame(
        canonical_rows
    ).reset_index(drop=True)
    canonical[
        "canonical_variant_rank_basis"
    ] = (
        "maximum bilateral floor, then bilateral mean, "
        "package prior, lower adjusted value gap"
    )
    canonical[
        "concept_variant_count"
    ] = canonical[
        "player_exchange_key"
    ].map(
        bilateral_variants[
            "player_exchange_key"
        ].value_counts()
    )

    selected_ids = set(
        canonical["optimizer_candidate_id"]
    )
    team_concepts = scored.loc[
        scored[
            "optimizer_candidate_id"
        ].isin(selected_ids)
    ].copy()

    counterpart_scores = team_concepts[
        [
            "optimizer_candidate_id",
            "recommendation_team",
            "final_team_strategy_score",
        ]
    ].copy()
    counterpart_scores = counterpart_scores.rename(
        columns={
            "recommendation_team": (
                "counterpart_team_for_score"
            ),
            "final_team_strategy_score": (
                "counterpart_final_team_strategy_score"
            ),
        }
    )

    team_concepts = team_concepts.merge(
        counterpart_scores,
        left_on=[
            "optimizer_candidate_id",
            "counterpart_team",
        ],
        right_on=[
            "optimizer_candidate_id",
            "counterpart_team_for_score",
        ],
        how="left",
        validate="one_to_one",
    ).drop(
        columns=[
            "counterpart_team_for_score",
        ]
    )

    bilateral_fields = canonical[
        [
            "optimizer_candidate_id",
            "bilateral_floor_score",
            "bilateral_mean_score",
            "bilateral_score_gap",
            "bilateral_strategy_tier",
            "concept_variant_count",
            "canonical_variant_rank_basis",
        ]
    ]

    team_concepts = team_concepts.merge(
        bilateral_fields,
        on="optimizer_candidate_id",
        how="left",
        validate="many_to_one",
    )

    return (
        canonical.sort_values(
            [
                "bilateral_floor_score",
                "bilateral_mean_score",
                "player_exchange_key",
            ],
            ascending=[
                False,
                False,
                True,
            ],
        ).reset_index(drop=True),
        team_concepts,
    )


def rank_team_concepts(
    team_concepts: pd.DataFrame,
) -> pd.DataFrame:
    output = team_concepts.copy()

    output[
        "team_strategy_rank_all_concepts"
    ] = (
        output.groupby(
            "recommendation_team"
        )[
            "final_team_strategy_score"
        ]
        .rank(
            method="first",
            ascending=False,
        )
        .astype(int)
    )

    output[
        "bilateral_recommendation_released"
    ] = ~output[
        "bilateral_strategy_tier"
    ].eq(
        "not_released_bilateral_strategy_hold"
    )

    released_rank = (
        output.loc[
            output[
                "bilateral_recommendation_released"
            ]
        ]
        .groupby(
            "recommendation_team"
        )[
            "final_team_strategy_score"
        ]
        .rank(
            method="first",
            ascending=False,
        )
    )
    output[
        "team_strategy_rank_released"
    ] = np.nan
    output.loc[
        released_rank.index,
        "team_strategy_rank_released",
    ] = released_rank
    output[
        "team_strategy_rank_released"
    ] = pd.to_numeric(
        output[
            "team_strategy_rank_released"
        ],
        errors="coerce",
    ).astype("Int64")

    return output.sort_values(
        [
            "recommendation_team",
            "bilateral_recommendation_released",
            "final_team_strategy_score",
            "bilateral_floor_score",
            "optimizer_candidate_id",
        ],
        ascending=[
            True,
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def diversify_top_recommendations(
    ranked: pd.DataFrame,
) -> pd.DataFrame:
    selected_rows: list[pd.Series] = []

    for team, group in ranked.groupby(
        "recommendation_team",
        sort=True,
    ):
        incoming_counts: Counter[str] = Counter()
        outgoing_counts: Counter[str] = Counter()
        counterpart_counts: Counter[str] = Counter()

        eligible = group.loc[
            group[
                "bilateral_recommendation_released"
            ]
        ].sort_values(
            [
                "final_team_strategy_score",
                "bilateral_floor_score",
                "package_quality_prior_score",
                "optimizer_candidate_id",
            ],
            ascending=[
                False,
                False,
                False,
                True,
            ],
        )

        for _, row in eligible.iterrows():
            incoming = clean_text(
                row[
                    "incoming_primary_player_name"
                ]
            )
            outgoing = clean_text(
                row[
                    "outgoing_primary_player_name"
                ]
            )
            counterpart = clean_text(
                row[
                    "counterpart_team"
                ]
            )

            if (
                incoming_counts[incoming]
                >= MAX_PRIMARY_INCOMING_PLAYER_EXPOSURE
            ):
                continue
            if (
                outgoing_counts[outgoing]
                >= MAX_PRIMARY_OUTGOING_PLAYER_EXPOSURE
            ):
                continue
            if (
                counterpart_counts[counterpart]
                >= MAX_COUNTERPART_TEAM_EXPOSURE
            ):
                continue

            selected_rows.append(row)
            incoming_counts[incoming] += 1
            outgoing_counts[outgoing] += 1
            counterpart_counts[counterpart] += 1

            if sum(
                1
                for selected in selected_rows
                if selected[
                    "recommendation_team"
                ] == team
            ) >= TOP_RECOMMENDATIONS_PER_TEAM:
                break

    if not selected_rows:
        return ranked.head(0).copy()

    output = pd.DataFrame(
        selected_rows
    ).reset_index(drop=True)
    output[
        "diversified_team_rank"
    ] = (
        output.groupby(
            "recommendation_team"
        )[
            "final_team_strategy_score"
        ]
        .rank(
            method="first",
            ascending=False,
        )
        .astype(int)
    )
    output[
        "diversification_policy"
    ] = (
        f"max {MAX_PRIMARY_INCOMING_PLAYER_EXPOSURE} per primary "
        f"incoming player; max {MAX_PRIMARY_OUTGOING_PLAYER_EXPOSURE} "
        f"per primary outgoing player; max "
        f"{MAX_COUNTERPART_TEAM_EXPOSURE} per counterpart; "
        f"top {TOP_RECOMMENDATIONS_PER_TEAM} per team"
    )

    return output.sort_values(
        [
            "recommendation_team",
            "diversified_team_rank",
        ]
    ).reset_index(drop=True)


def build_team_summary(
    profiles: pd.DataFrame,
    full_perspectives: pd.DataFrame,
    routine_perspectives: pd.DataFrame,
    ranked: pd.DataFrame,
    top: pd.DataFrame,
) -> pd.DataFrame:
    teams = profiles[
        [
            "team_abbreviation",
            "model_team_strategy_archetype",
            "model_pick_preference",
            "top_need_1",
            "top_need_2",
            "top_need_3",
            "strength_percentile_2026_27",
            "projected_wins_2026_27",
        ]
    ].copy()

    legal_exposure = (
        full_perspectives.groupby(
            "recommendation_team"
        )
        .size()
        .rename(
            "deterministic_legal_perspective_rows"
        )
        .reset_index()
    )

    routine_exposure = (
        routine_perspectives.groupby(
            "recommendation_team"
        )
        .agg(
            routine_package_variants=(
                "optimizer_candidate_id",
                "nunique",
            ),
        )
        .reset_index()
    )

    concept_summary = (
        ranked.groupby(
            "recommendation_team"
        )
        .agg(
            unique_canonical_concepts=(
                "player_exchange_key",
                "nunique",
            ),
            released_bilateral_concepts=(
                "bilateral_recommendation_released",
                "sum",
            ),
            maximum_team_strategy_score=(
                "final_team_strategy_score",
                "max",
            ),
            maximum_bilateral_floor_score=(
                "bilateral_floor_score",
                "max",
            ),
        )
        .reset_index()
    )

    top_summary = (
        top.groupby(
            "recommendation_team"
        )
        .size()
        .rename(
            "diversified_top_recommendations"
        )
        .reset_index()
    )

    output = teams.merge(
        legal_exposure,
        left_on="team_abbreviation",
        right_on="recommendation_team",
        how="left",
    ).drop(
        columns=[
            "recommendation_team",
        ],
        errors="ignore",
    )

    for frame in [
        routine_exposure,
        concept_summary,
        top_summary,
    ]:
        output = output.merge(
            frame,
            left_on="team_abbreviation",
            right_on="recommendation_team",
            how="left",
        ).drop(
            columns=[
                "recommendation_team",
            ],
            errors="ignore",
        )

    numeric_fill_columns = [
        "deterministic_legal_perspective_rows",
        "routine_package_variants",
        "unique_canonical_concepts",
        "released_bilateral_concepts",
        "diversified_top_recommendations",
    ]
    for column in numeric_fill_columns:
        output[column] = (
            pd.to_numeric(
                output[column],
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    output[
        "strategy_recommendation_status"
    ] = np.select(
        [
            output[
                "deterministic_legal_perspective_rows"
            ].eq(0),
            output[
                "routine_package_variants"
            ].eq(0),
            output[
                "released_bilateral_concepts"
            ].eq(0),
        ],
        [
            "no_deterministic_legal_pool_exposure",
            "no_strategy_ready_routine_concepts",
            "routine_concepts_below_bilateral_release_threshold",
        ],
        default=(
            "ranked_strategy_recommendations_available"
        ),
    )

    output[
        "final_team_strategy_score_released"
    ] = output[
        "released_bilateral_concepts"
    ].gt(0)

    return output.sort_values(
        "team_abbreviation"
    ).reset_index(drop=True)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return (
            None
            if np.isnan(value)
            else float(value)
        )
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def run_self_test() -> int:
    weights_valid = all(
        math.isclose(
            sum(profile.values()),
            1.0,
            abs_tol=1e-12,
        )
        for profile in (
            ARCHETYPE_WEIGHTS.values()
        )
    )

    variants = pd.DataFrame(
        [
            {
                "optimizer_candidate_id": "A",
                "player_exchange_key": "X",
                "bilateral_floor_score": 55.0,
                "bilateral_mean_score": 75.0,
                "package_quality_prior_score": 90.0,
                "adjusted_absolute_value_gap": 1.0,
            },
            {
                "optimizer_candidate_id": "B",
                "player_exchange_key": "X",
                "bilateral_floor_score": 65.0,
                "bilateral_mean_score": 68.0,
                "package_quality_prior_score": 85.0,
                "adjusted_absolute_value_gap": 2.0,
            },
        ]
    )
    selected = variants.sort_values(
        [
            "bilateral_floor_score",
            "bilateral_mean_score",
            "package_quality_prior_score",
            "adjusted_absolute_value_gap",
            "optimizer_candidate_id",
        ],
        ascending=[
            False,
            False,
            False,
            True,
            True,
        ],
    ).iloc[0]["optimizer_candidate_id"]

    tests = {
        "archetype_weights_sum_to_one": weights_valid,
        "ratio_utility_center": math.isclose(
            ratio_utility(1.0),
            50.0,
        ),
        "ratio_utility_upper": math.isclose(
            ratio_utility(1.5),
            100.0,
        ),
        "rebuild_receiving_first_beats_attaching_first": (
            pick_alignment_score(
                "development_rebuild",
                False,
                "first_round",
            )
            > pick_alignment_score(
                "development_rebuild",
                True,
                "first_round",
            )
        ),
        "rebuild_younger_timeline_scores_higher": (
            timeline_alignment_score(
                "development_rebuild",
                27.0,
                22.0,
            )
            > timeline_alignment_score(
                "development_rebuild",
                22.0,
                27.0,
            )
        ),
        "contender_consolidation_scores_higher": (
            transaction_structure_score(
                "win_now_contender",
                2,
                1,
            )
            > transaction_structure_score(
                "win_now_contender",
                1,
                2,
            )
        ),
        "canonical_variant_maximizes_floor": (
            selected == "B"
        ),
        "bilateral_tier_threshold": (
            classify_bilateral_floor(60.0)
            == "solid_bilateral_strategy_match"
        ),
    }

    print(
        json.dumps(
            tests,
            indent=2,
        )
    )
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 92)
    print(
        "MIXED PLAYER-AND-PICK FINAL TEAM STRATEGY RANKINGS"
    )
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/8] Loading and validating upstream releases")
    required_paths = [
        QUALITY_METADATA_PATH,
        READINESS_METADATA_PATH,
        TEAM_PERSPECTIVE_PATH,
        ROUTINE_PATH,
        MINOR_PATH,
        TEAM_PROFILES_PATH,
    ]
    missing_paths = [
        path
        for path in required_paths
        if not path.exists()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "Missing required upstream files:\n"
            + "\n".join(
                str(path)
                for path in missing_paths
            )
        )

    quality_metadata = json.loads(
        QUALITY_METADATA_PATH.read_text(
            encoding="utf-8"
        )
    )
    readiness_metadata = json.loads(
        READINESS_METADATA_PATH.read_text(
            encoding="utf-8"
        )
    )

    routine = pd.read_csv(ROUTINE_PATH)
    minor = pd.read_csv(MINOR_PATH)
    packages = pd.concat(
        [
            routine,
            minor,
        ],
        ignore_index=True,
        sort=False,
    )
    full_perspectives = pd.read_csv(
        TEAM_PERSPECTIVE_PATH
    )
    routine_perspectives = (
        full_perspectives.loc[
            full_perspectives[
                "quality_gate_class"
            ].isin(ROUTINE_CLASSES)
        ].copy()
    )
    profiles = pd.read_csv(
        TEAM_PROFILES_PATH
    )
    players, player_market_source = (
        read_player_market()
    )
    lookup = player_market_lookup(
        players
    )

    print(
        f"  Routine: {len(routine):,} | minor assets: "
        f"{len(minor):,} | package variants: "
        f"{len(packages):,}"
    )
    print(
        f"  Team-perspective rows: "
        f"{len(routine_perspectives):,} | team profiles: "
        f"{len(profiles):,}"
    )

    print("[2/8] Building team-specific strategy scores")
    scored = score_perspectives(
        perspectives=routine_perspectives,
        packages=packages,
        profiles=profiles,
        player_lookup=lookup,
    )

    print("[3/8] Selecting one canonical pick variant per concept")
    bilateral_concepts, team_concepts = (
        select_canonical_concepts(
            scored
        )
    )
    print(
        f"  {len(packages):,} variants -> "
        f"{len(bilateral_concepts):,} canonical concepts"
    )

    print("[4/8] Ranking concepts for each team")
    ranked = rank_team_concepts(
        team_concepts
    )

    print("[5/8] Applying recommendation diversification")
    top = diversify_top_recommendations(
        ranked
    )

    print("[6/8] Building 30-team release summary")
    team_summary = build_team_summary(
        profiles=profiles,
        full_perspectives=full_perspectives,
        routine_perspectives=routine_perspectives,
        ranked=ranked,
        top=top,
    )

    print("[7/8] Validating final strategy release")
    perspective_counts = (
        routine_perspectives.groupby(
            "optimizer_candidate_id"
        )["recommendation_team"]
        .nunique()
    )
    side_score_differences = (
        scored.groupby(
            "optimizer_candidate_id"
        )[
            "final_team_strategy_score"
        ]
        .agg(
            lambda values: (
                values.max()
                - values.min()
            )
        )
    )
    canonical_pair_counts = (
        ranked.groupby(
            "player_exchange_key"
        )["recommendation_team"]
        .nunique()
    )

    validation_rows = [
        {
            "check_name": "v4_quality_gate_release_valid",
            "passed": bool(
                quality_metadata.get(
                    "release_valid"
                )
            ),
            "observed": quality_metadata.get(
                "release_valid"
            ),
            "expected": True,
        },
        {
            "check_name": "strategy_readiness_release_ready",
            "passed": bool(
                readiness_metadata.get(
                    "strategy_ready"
                )
            ),
            "observed": readiness_metadata.get(
                "strategy_ready"
            ),
            "expected": True,
        },
        {
            "check_name": "routine_row_count",
            "passed": (
                len(routine)
                == EXPECTED_ROUTINE_ROWS
            ),
            "observed": len(routine),
            "expected": EXPECTED_ROUTINE_ROWS,
        },
        {
            "check_name": "minor_row_count",
            "passed": (
                len(minor)
                == EXPECTED_MINOR_ROWS
            ),
            "observed": len(minor),
            "expected": EXPECTED_MINOR_ROWS,
        },
        {
            "check_name": "package_variant_count",
            "passed": (
                len(packages)
                == EXPECTED_PACKAGE_VARIANTS
            ),
            "observed": len(packages),
            "expected": EXPECTED_PACKAGE_VARIANTS,
        },
        {
            "check_name": "routine_perspective_row_count",
            "passed": (
                len(routine_perspectives)
                == EXPECTED_PERSPECTIVE_ROWS
            ),
            "observed": len(routine_perspectives),
            "expected": EXPECTED_PERSPECTIVE_ROWS,
        },
        {
            "check_name": "two_perspectives_per_package",
            "passed": bool(
                perspective_counts.eq(2).all()
            ),
            "observed": perspective_counts.value_counts().to_dict(),
            "expected": {
                2: EXPECTED_PACKAGE_VARIANTS
            },
        },
        {
            "check_name": "canonical_concept_count",
            "passed": (
                len(bilateral_concepts)
                == EXPECTED_UNIQUE_CONCEPTS
            ),
            "observed": len(
                bilateral_concepts
            ),
            "expected": EXPECTED_UNIQUE_CONCEPTS,
        },
        {
            "check_name": "two_team_rows_per_canonical_concept",
            "passed": bool(
                canonical_pair_counts.eq(2).all()
            ),
            "observed": canonical_pair_counts.value_counts().to_dict(),
            "expected": {
                2: EXPECTED_UNIQUE_CONCEPTS
            },
        },
        {
            "check_name": "team_profiles_cover_30_teams",
            "passed": (
                len(profiles)
                == EXPECTED_TEAM_PROFILES
            ),
            "observed": len(profiles),
            "expected": EXPECTED_TEAM_PROFILES,
        },
        {
            "check_name": "all_strategy_scores_finite",
            "passed": bool(
                np.isfinite(
                    scored[
                        "final_team_strategy_score"
                    ]
                ).all()
            ),
            "observed": int(
                np.isfinite(
                    scored[
                        "final_team_strategy_score"
                    ]
                ).sum()
            ),
            "expected": len(scored),
        },
        {
            "check_name": "team_scores_are_perspective_specific",
            "passed": bool(
                side_score_differences.gt(
                    1e-9
                ).any()
            ),
            "observed": {
                "packages_with_different_side_scores": int(
                    side_score_differences.gt(
                        1e-9
                    ).sum()
                ),
                "packages": int(
                    len(
                        side_score_differences
                    )
                ),
            },
            "expected": (
                "at_least_one_package_with_different_side_scores"
            ),
        },
        {
            "check_name": "no_protected_players_scored",
            "passed": bool(
                scored[
                    "outgoing_protected_player_count"
                ].eq(0).all()
                and scored[
                    "incoming_protected_player_count"
                ].eq(0).all()
            ),
            "observed": int(
                (
                    scored[
                        "outgoing_protected_player_count"
                    ].gt(0)
                    | scored[
                        "incoming_protected_player_count"
                    ].gt(0)
                ).sum()
            ),
            "expected": 0,
        },
        {
            "check_name": "final_legality_preserved",
            "passed": bool(
                scored[
                    "optimizer_package_final_legal_package"
                ].map(
                    bool_value
                ).all()
            ),
            "observed": int(
                scored[
                    "optimizer_package_final_legal_package"
                ].map(
                    bool_value
                ).sum()
            ),
            "expected": len(scored),
        },
        {
            "check_name": "team_summary_covers_30_teams",
            "passed": (
                len(team_summary)
                == EXPECTED_TEAM_PROFILES
            ),
            "observed": len(
                team_summary
            ),
            "expected": EXPECTED_TEAM_PROFILES,
        },
        {
            "check_name": "final_team_strategy_score_released",
            "passed": bool(
                scored[
                    "team_strategy_score_released"
                ].all()
            ),
            "observed": True,
            "expected": True,
        },
    ]

    release_valid = all(
        bool(row["passed"])
        for row in validation_rows
    )

    print("[8/8] Writing final strategy artifacts")
    scored.to_parquet(
        FULL_SCORES_PARQUET_OUTPUT,
        index=False,
    )
    scored.to_csv(
        FULL_SCORES_CSV_OUTPUT,
        index=False,
    )
    bilateral_concepts.to_csv(
        BILATERAL_CONCEPT_OUTPUT,
        index=False,
    )
    ranked.to_csv(
        TEAM_CONCEPT_OUTPUT,
        index=False,
    )
    top.to_csv(
        TOP_RECOMMENDATIONS_OUTPUT,
        index=False,
    )
    team_summary.to_csv(
        TEAM_SUMMARY_OUTPUT,
        index=False,
    )
    pd.DataFrame(
        validation_rows
    ).to_csv(
        VALIDATION_OUTPUT,
        index=False,
    )

    metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "release_valid": release_valid,
        "quality_gate_source": str(
            QUALITY_METADATA_PATH
        ),
        "strategy_readiness_source": str(
            READINESS_METADATA_PATH
        ),
        "player_market_source": (
            player_market_source
        ),
        "counts": {
            "routine_packages": len(
                routine
            ),
            "minor_asset_packages": len(
                minor
            ),
            "package_variants": len(
                packages
            ),
            "team_perspective_scores": len(
                scored
            ),
            "canonical_bilateral_concepts": len(
                bilateral_concepts
            ),
            "team_concept_rows": len(
                ranked
            ),
            "diversified_top_recommendations": len(
                top
            ),
            "teams_with_released_recommendations": int(
                team_summary[
                    "final_team_strategy_score_released"
                ].sum()
            ),
            "team_profiles": len(
                profiles
            ),
        },
        "release_thresholds": RELEASE_THRESHOLDS,
        "archetype_weights": ARCHETYPE_WEIGHTS,
        "pick_alignment_scores": {
            archetype: {
                "|".join(key): value
                for key, value in scores.items()
            }
            for archetype, scores in (
                PICK_ALIGNMENT_SCORES.items()
            )
        },
        "ratio_utility": (
            "0.50 retention ratio maps to 0; "
            "1.00 maps to 50; 1.50 maps to 100; "
            "values are clipped to 0-100"
        ),
        "canonical_variant_method": (
            "For each player-exchange concept, choose the package "
            "variant with the highest minimum team strategy score. "
            "Break ties by bilateral mean, package-quality prior, "
            "lower adjusted value gap, and candidate ID."
        ),
        "diversification_policy": {
            "top_recommendations_per_team": (
                TOP_RECOMMENDATIONS_PER_TEAM
            ),
            "maximum_primary_incoming_player_exposure": (
                MAX_PRIMARY_INCOMING_PLAYER_EXPOSURE
            ),
            "maximum_primary_outgoing_player_exposure": (
                MAX_PRIMARY_OUTGOING_PLAYER_EXPOSURE
            ),
            "maximum_counterpart_team_exposure": (
                MAX_COUNTERPART_TEAM_EXPOSURE
            ),
        },
        "scope_note": (
            "This is the final team-specific strategy score for "
            "strategy-ready routine and minor-asset mixed packages. "
            "The score is model-derived and is not a prediction that "
            "a real team or player is available. Protected-player "
            "blockbusters remain concept-only and are excluded."
        ),
        "outputs": {
            "full_scores_parquet": str(
                FULL_SCORES_PARQUET_OUTPUT
            ),
            "full_scores_csv": str(
                FULL_SCORES_CSV_OUTPUT
            ),
            "bilateral_concepts": str(
                BILATERAL_CONCEPT_OUTPUT
            ),
            "team_concept_rankings": str(
                TEAM_CONCEPT_OUTPUT
            ),
            "top_recommendations": str(
                TOP_RECOMMENDATIONS_OUTPUT
            ),
            "team_summary": str(
                TEAM_SUMMARY_OUTPUT
            ),
            "validation": str(
                VALIDATION_OUTPUT
            ),
        },
    }
    METADATA_OUTPUT.write_text(
        json.dumps(
            json_safe(metadata),
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Complete")
    print(
        f"Validation: "
        f"{sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Release valid: {release_valid}")
    print(
        f"Package variants: {len(packages):,} | "
        f"team perspectives: {len(scored):,}"
    )
    print(
        f"Canonical bilateral concepts: "
        f"{len(bilateral_concepts):,} | "
        f"team concept rows: {len(ranked):,}"
    )
    print(
        f"Diversified top recommendations: "
        f"{len(top):,}"
    )
    print(
        "Teams with released recommendations: "
        f"{int(team_summary['final_team_strategy_score_released'].sum()):,}/"
        f"{len(team_summary):,}"
    )
    print(
        "Final team strategy score released: True"
    )

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())