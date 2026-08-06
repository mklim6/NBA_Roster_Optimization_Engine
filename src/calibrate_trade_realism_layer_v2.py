from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "trade-realism-calibration-v2-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PLAYER_MARKET_V1_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_trade_market_value_layer_2026_27.parquet"
)

REALISM_SCORES_V1_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "one_for_one_trade_realism_scores_2026_27.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

PLAYER_MARKET_V2_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v2.parquet"
)

PLAYER_MARKET_V2_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v2.csv"
)

REALISM_SCORES_V2_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_scores_2026_27_v2.parquet"
)

ORDINARY_RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_recommendations_2026_27_v2.csv"
)

STAR_COMPARISONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_star_swap_value_comparisons_2026_27_v2.csv"
)

FILTERED_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_filtered_audit_2026_27_v2.csv"
)

TEAM_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_realistic_trade_targets_2026_27_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "trade_realism_calibration_metadata_2026_27_v2.json"
)


SKILL_PERCENTILE_COLUMNS = [
    "scoring_percentile",
    "shooting_percentile",
    "playmaking_percentile",
    "rebounding_percentile",
    "defense_percentile",
]

QUALITY_WEIGHTS = {
    "expected_contribution_percentile": 0.35,
    "downside_contribution_percentile": 0.20,
    "roster_value_percentile": 0.20,
    "survival_percentile": 0.10,
    "skill_breadth_score": 0.10,
    "skill_peak_score": 0.05,
}

MARKET_VALUE_WEIGHTS_V2 = {
    "player_quality_score": 0.75,
    "age_market_score": 0.10,
    "contract_control_score": 0.10,
    "contract_value_percentile": 0.05,
}

SURPLUS_VALUE_WEIGHTS = {
    "contract_value_percentile": 0.50,
    "age_market_score": 0.25,
    "contract_control_score": 0.25,
}

PAIR_SCORE_WEIGHTS_V2 = {
    "mutual_trade_score": 0.45,
    "market_value_parity_score_v2": 0.25,
    "quality_parity_score": 0.15,
    "age_parity_score_v2": 0.08,
    "contract_control_parity_score_v2": 0.07,
}

ASSET_TIER_ORDER_V2 = {
    "franchise_cornerstone": 5,
    "core_star": 4,
    "high_end_starter": 3,
    "starter_rotation": 2,
    "rotation_depth": 1,
    "development_depth": 0,
}

MAJOR_ASSET_TIERS = {
    "franchise_cornerstone",
    "core_star",
}


def require_columns(
    frame: pd.DataFrame,
    columns: list[str],
    frame_name: str,
) -> None:
    missing = [
        column
        for column in columns
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            f"{frame_name} is missing required columns:\n"
            + "\n".join(missing)
        )


def player_key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0"):
        numeric_part = text[:-2]

        if numeric_part.isdigit():
            return numeric_part

    return text


def numeric_series(
    frame: pd.DataFrame,
    column: str,
    fill_value: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(
        frame[column],
        errors="coerce",
    )

    if fill_value is not None:
        values = values.fillna(
            fill_value
        )

    return values.astype(float)


def percentile_rank(
    values: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(
        values,
        errors="coerce",
    )

    if numeric.notna().sum() == 0:
        return pd.Series(
            50.0,
            index=values.index,
        )

    filled = numeric.fillna(
        numeric.median()
    )

    return (
        filled.rank(
            method="average",
            pct=True,
        )
        * 100.0
    )


def age_market_score(age: float) -> float:
    if not np.isfinite(age):
        return 50.0

    return float(
        np.clip(
            105.0
            - 4.0
            * max(
                0.0,
                age - 19.0,
            ),
            10.0,
            100.0,
        )
    )


def contract_control_score(
    years_remaining: float,
) -> float:
    if not np.isfinite(
        years_remaining
    ):
        return 40.0

    return float(
        np.clip(
            20.0
            + 20.0
            * years_remaining,
            20.0,
            100.0,
        )
    )


def classify_asset_tier_v2(
    row: pd.Series,
) -> str:
    market = float(
        row[
            "market_value_percentile_v2"
        ]
    )

    quality = float(
        row[
            "player_quality_score"
        ]
    )

    expected = float(
        row[
            "expected_contribution_percentile"
        ]
    )

    roster = float(
        row[
            "roster_value_percentile"
        ]
    )

    if (
        market >= 96.0
        and quality >= 88.0
        and expected >= 85.0
        and roster >= 85.0
    ):
        return "franchise_cornerstone"

    if (
        market >= 88.0
        and quality >= 80.0
        and expected >= 75.0
    ):
        return "core_star"

    if (
        market >= 72.0
        and quality >= 67.0
    ):
        return "high_end_starter"

    if (
        market >= 50.0
        and quality >= 50.0
    ):
        return "starter_rotation"

    if market >= 25.0:
        return "rotation_depth"

    return "development_depth"


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PLAYER_MARKET_V1_PATH,
        REALISM_SCORES_V1_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    players = pd.read_parquet(
        PLAYER_MARKET_V1_PATH
    )

    pairs = pd.read_parquet(
        REALISM_SCORES_V1_PATH
    )

    require_columns(
        players,
        [
            "player_id",
            "player_name",
            "projected_expected_contribution",
            "projected_survival_probability",
            "survival_weighted_active_downside_score",
            "roster_value_percentile",
            "contract_value_percentile",
            *SKILL_PERCENTILE_COLUMNS,
        ],
        "Player market layer v1",
    )

    require_columns(
        pairs,
        [
            "pair_id",
            "player_a_id",
            "player_b_id",
            "player_a_name",
            "player_b_name",
            "team_a",
            "team_b",
            "mutual_trade_score",
            "minimum_team_trade_fit_score",
            "recommendation_eligible",
            "team_a_expected_retention_ratio",
            "team_b_expected_retention_ratio",
            "team_a_downside_retention_ratio",
            "team_b_downside_retention_ratio",
        ],
        "Trade realism scores v1",
    )

    return (
        players.copy(),
        pairs.copy(),
    )


def build_player_market_v2(
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = players.copy()

    output[
        "expected_contribution_percentile"
    ] = percentile_rank(
        output[
            "projected_expected_contribution"
        ]
    )

    output[
        "downside_contribution_percentile"
    ] = percentile_rank(
        output[
            "survival_weighted_active_downside_score"
        ]
    )

    output[
        "survival_percentile"
    ] = percentile_rank(
        output[
            "projected_survival_probability"
        ]
    )

    for column in [
        "roster_value_percentile",
        "contract_value_percentile",
        *SKILL_PERCENTILE_COLUMNS,
    ]:
        output[column] = numeric_series(
            output,
            column,
            fill_value=50.0,
        ).clip(
            lower=0.0,
            upper=100.0,
        )

    skill_matrix = output[
        SKILL_PERCENTILE_COLUMNS
    ].to_numpy(dtype=float)

    sorted_skills = np.sort(
        skill_matrix,
        axis=1,
    )

    output[
        "skill_peak_score"
    ] = sorted_skills[
        :,
        -1,
    ]

    output[
        "skill_breadth_score"
    ] = sorted_skills[
        :,
        -3:,
    ].mean(
        axis=1
    )

    if "age" in output.columns:
        ages = numeric_series(
            output,
            "age",
        )
    else:
        ages = pd.Series(
            np.nan,
            index=output.index,
        )

    output["age"] = ages

    output[
        "age_market_score"
    ] = output[
        "age"
    ].map(
        age_market_score
    )

    years_column = (
        "contract_years_remaining_including_2026_27"
    )

    if years_column in output.columns:
        years = numeric_series(
            output,
            years_column,
        )
    else:
        years = pd.Series(
            np.nan,
            index=output.index,
        )

    output[
        years_column
    ] = years

    output[
        "contract_control_score"
    ] = output[
        years_column
    ].map(
        contract_control_score
    )

    output[
        "player_quality_score"
    ] = 0.0

    for component, weight in (
        QUALITY_WEIGHTS.items()
    ):
        output[
            "player_quality_score"
        ] += (
            weight
            * numeric_series(
                output,
                component,
                fill_value=50.0,
            )
        )

    output[
        "surplus_value_score"
    ] = 0.0

    for component, weight in (
        SURPLUS_VALUE_WEIGHTS.items()
    ):
        output[
            "surplus_value_score"
        ] += (
            weight
            * numeric_series(
                output,
                component,
                fill_value=50.0,
            )
        )

    output[
        "market_value_score_v2"
    ] = 0.0

    for component, weight in (
        MARKET_VALUE_WEIGHTS_V2.items()
    ):
        output[
            "market_value_score_v2"
        ] += (
            weight
            * numeric_series(
                output,
                component,
                fill_value=50.0,
            )
        )

    output[
        "market_value_percentile_v2"
    ] = percentile_rank(
        output[
            "market_value_score_v2"
        ]
    )

    output[
        "asset_tier_v2"
    ] = output.apply(
        classify_asset_tier_v2,
        axis=1,
    )

    output[
        "asset_tier_order_v2"
    ] = output[
        "asset_tier_v2"
    ].map(
        ASSET_TIER_ORDER_V2
    ).astype(int)

    output[
        "major_asset_flag"
    ] = output[
        "asset_tier_v2"
    ].isin(
        MAJOR_ASSET_TIERS
    )

    output[
        "elite_surplus_contract_flag"
    ] = (
        output[
            "surplus_value_score"
        ].ge(85.0)
        & output[
            "asset_tier_v2"
        ].isin(
            {
                "high_end_starter",
                "starter_rotation",
                "rotation_depth",
            }
        )
    )

    output[
        "market_value_calibration_note"
    ] = (
        "V2 gives 75% of market value to player quality. "
        "Age, contract control, and contract value affect "
        "market value but cannot independently create a "
        "franchise-cornerstone label."
    )

    return output.sort_values(
        "market_value_percentile_v2",
        ascending=False,
    ).reset_index(drop=True)


def build_player_lookup(
    players: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    return {
        player_key(
            row[
                "player_id"
            ]
        ): row
        for row in players.to_dict(
            orient="records"
        )
    }


def parity_score(
    first: float,
    second: float,
    scale: float,
) -> float:
    return float(
        np.clip(
            100.0
            - abs(
                first
                - second
            )
            * scale,
            0.0,
            100.0,
        )
    )


def tier_distance(
    first_tier: str,
    second_tier: str,
) -> int:
    return abs(
        ASSET_TIER_ORDER_V2[
            first_tier
        ]
        - ASSET_TIER_ORDER_V2[
            second_tier
        ]
    )


def tier_parity_score(
    distance: int,
) -> float:
    score_map = {
        0: 100.0,
        1: 75.0,
        2: 40.0,
        3: 15.0,
        4: 3.0,
        5: 0.0,
    }

    return score_map.get(
        distance,
        0.0,
    )


def add_player_fields(
    row: dict[str, Any],
    side: str,
    player: dict[str, Any],
) -> None:
    prefix = f"player_{side}_"

    fields = [
        "age",
        "player_quality_score",
        "surplus_value_score",
        "market_value_score_v2",
        "market_value_percentile_v2",
        "asset_tier_v2",
        "asset_tier_order_v2",
        "major_asset_flag",
        "elite_surplus_contract_flag",
        "contract_control_score",
        "contract_value_percentile",
        "expected_contribution_percentile",
        "downside_contribution_percentile",
        "roster_value_percentile",
        "playstyle_archetype",
    ]

    for field in fields:
        row[
            f"{prefix}{field}"
        ] = player.get(
            field,
            pd.NA,
        )


def build_pair_calibration(
    pairs: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    lookup = build_player_lookup(
        players
    )

    rows: list[dict[str, Any]] = []

    missing_ids: set[str] = set()

    for pair in pairs.to_dict(
        orient="records"
    ):
        player_a_id = player_key(
            pair[
                "player_a_id"
            ]
        )

        player_b_id = player_key(
            pair[
                "player_b_id"
            ]
        )

        player_a = lookup.get(
            player_a_id
        )

        player_b = lookup.get(
            player_b_id
        )

        if player_a is None:
            missing_ids.add(
                player_a_id
            )
            continue

        if player_b is None:
            missing_ids.add(
                player_b_id
            )
            continue

        row = dict(pair)

        add_player_fields(
            row=row,
            side="a",
            player=player_a,
        )

        add_player_fields(
            row=row,
            side="b",
            player=player_b,
        )

        market_a = float(
            player_a[
                "market_value_percentile_v2"
            ]
        )

        market_b = float(
            player_b[
                "market_value_percentile_v2"
            ]
        )

        quality_a = float(
            player_a[
                "player_quality_score"
            ]
        )

        quality_b = float(
            player_b[
                "player_quality_score"
            ]
        )

        control_a = float(
            player_a[
                "contract_control_score"
            ]
        )

        control_b = float(
            player_b[
                "contract_control_score"
            ]
        )

        age_a = float(
            player_a.get(
                "age",
                np.nan,
            )
        )

        age_b = float(
            player_b.get(
                "age",
                np.nan,
            )
        )

        market_gap = abs(
            market_a
            - market_b
        )

        quality_gap = abs(
            quality_a
            - quality_b
        )

        age_gap = (
            abs(
                age_a
                - age_b
            )
            if (
                np.isfinite(age_a)
                and np.isfinite(age_b)
            )
            else 0.0
        )

        market_parity = parity_score(
            market_a,
            market_b,
            scale=4.0,
        )

        quality_parity = parity_score(
            quality_a,
            quality_b,
            scale=3.0,
        )

        age_parity = (
            parity_score(
                age_a,
                age_b,
                scale=8.0,
            )
            if (
                np.isfinite(age_a)
                and np.isfinite(age_b)
            )
            else 65.0
        )

        control_parity = parity_score(
            control_a,
            control_b,
            scale=1.0,
        )

        tier_gap = tier_distance(
            player_a[
                "asset_tier_v2"
            ],
            player_b[
                "asset_tier_v2"
            ],
        )

        tier_parity = (
            tier_parity_score(
                tier_gap
            )
        )

        mutual_score = float(
            pair[
                "mutual_trade_score"
            ]
        )

        adjusted_score = (
            PAIR_SCORE_WEIGHTS_V2[
                "mutual_trade_score"
            ]
            * mutual_score
            + PAIR_SCORE_WEIGHTS_V2[
                "market_value_parity_score_v2"
            ]
            * market_parity
            + PAIR_SCORE_WEIGHTS_V2[
                "quality_parity_score"
            ]
            * quality_parity
            + PAIR_SCORE_WEIGHTS_V2[
                "age_parity_score_v2"
            ]
            * age_parity
            + PAIR_SCORE_WEIGHTS_V2[
                "contract_control_parity_score_v2"
            ]
            * control_parity
        )

        major_a = bool(
            player_a[
                "major_asset_flag"
            ]
        )

        major_b = bool(
            player_b[
                "major_asset_flag"
            ]
        )

        either_major = bool(
            major_a
            or major_b
        )

        both_major = bool(
            major_a
            and major_b
        )

        expected_retention_pass = bool(
            float(
                pair[
                    "team_a_expected_retention_ratio"
                ]
            )
            >= 0.85
            and float(
                pair[
                    "team_b_expected_retention_ratio"
                ]
            )
            >= 0.85
        )

        downside_retention_pass = bool(
            float(
                pair[
                    "team_a_downside_retention_ratio"
                ]
            )
            >= 0.70
            and float(
                pair[
                    "team_b_downside_retention_ratio"
                ]
            )
            >= 0.70
        )

        standard_tier_pass = bool(
            tier_gap <= 1
        )

        standard_value_pass = bool(
            market_gap <= 10.0
        )

        star_value_pass = bool(
            market_gap <= 6.0
            and tier_gap == 0
        )

        young_asset_mismatch = bool(
            (
                np.isfinite(age_a)
                and np.isfinite(age_b)
                and age_a <= 25.0
                and age_b >= 31.0
                and market_a
                >= market_b - 2.0
            )
            or (
                np.isfinite(age_a)
                and np.isfinite(age_b)
                and age_b <= 25.0
                and age_a >= 31.0
                and market_b
                >= market_a - 2.0
            )
        )

        ordinary_candidate = bool(
            pair[
                "recommendation_eligible"
            ]
            and not either_major
            and adjusted_score >= 65.0
            and float(
                pair[
                    "minimum_team_trade_fit_score"
                ]
            )
            >= 50.0
            and expected_retention_pass
            and downside_retention_pass
            and standard_tier_pass
            and standard_value_pass
            and not young_asset_mismatch
        )

        star_comparison_candidate = bool(
            pair[
                "recommendation_eligible"
            ]
            and both_major
            and adjusted_score >= 68.0
            and float(
                pair[
                    "minimum_team_trade_fit_score"
                ]
            )
            >= 50.0
            and expected_retention_pass
            and downside_retention_pass
            and star_value_pass
            and not young_asset_mismatch
        )

        if ordinary_candidate:
            if (
                adjusted_score >= 75.0
                and float(
                    pair[
                        "minimum_team_trade_fit_score"
                    ]
                )
                >= 58.0
            ):
                review_tier = (
                    "strong_ordinary_trade_review"
                )
            elif adjusted_score >= 69.0:
                review_tier = (
                    "detailed_ordinary_trade_review"
                )
            else:
                review_tier = (
                    "exploratory_ordinary_trade_review"
                )
        elif star_comparison_candidate:
            review_tier = (
                "star_swap_value_comparison_only"
            )
        else:
            review_tier = (
                "filtered_from_v2_review"
            )

        filter_reasons = []

        if not bool(
            pair[
                "recommendation_eligible"
            ]
        ):
            filter_reasons.append(
                "failed_original_fit_eligibility"
            )

        if adjusted_score < 65.0:
            filter_reasons.append(
                "v2_adjusted_score_below_65"
            )

        if float(
            pair[
                "minimum_team_trade_fit_score"
            ]
        ) < 50.0:
            filter_reasons.append(
                "minimum_team_fit_below_50"
            )

        if not expected_retention_pass:
            filter_reasons.append(
                "expected_retention_below_85_percent"
            )

        if not downside_retention_pass:
            filter_reasons.append(
                "downside_retention_below_70_percent"
            )

        if market_gap > 10.0:
            filter_reasons.append(
                "v2_market_value_gap_above_10"
            )

        if tier_gap > 1:
            filter_reasons.append(
                "asset_tier_gap_above_one"
            )

        if young_asset_mismatch:
            filter_reasons.append(
                "young_asset_for_older_asset_mismatch"
            )

        if either_major and not star_comparison_candidate:
            filter_reasons.append(
                "major_asset_removed_from_ordinary_recommendations"
            )

        row[
            "market_value_gap_v2"
        ] = market_gap

        row[
            "player_quality_gap"
        ] = quality_gap

        row[
            "asset_tier_gap_v2"
        ] = tier_gap

        row[
            "market_value_parity_score_v2"
        ] = market_parity

        row[
            "quality_parity_score"
        ] = quality_parity

        row[
            "age_parity_score_v2"
        ] = age_parity

        row[
            "contract_control_parity_score_v2"
        ] = control_parity

        row[
            "asset_tier_parity_score_v2"
        ] = tier_parity

        row[
            "realism_adjusted_trade_score_v2"
        ] = adjusted_score

        row[
            "either_major_asset_flag"
        ] = either_major

        row[
            "both_major_assets_flag"
        ] = both_major

        row[
            "young_asset_mismatch_flag_v2"
        ] = young_asset_mismatch

        row[
            "expected_retention_85_pass"
        ] = expected_retention_pass

        row[
            "downside_retention_70_pass"
        ] = downside_retention_pass

        row[
            "ordinary_trade_review_eligible"
        ] = ordinary_candidate

        row[
            "star_swap_value_comparison_eligible"
        ] = star_comparison_candidate

        row[
            "v2_review_tier"
        ] = review_tier

        row[
            "v2_filter_reasons"
        ] = (
            " | ".join(
                filter_reasons
            )
        )

        row[
            "v2_scope_note"
        ] = (
            "Ordinary recommendations exclude franchise and "
            "core-star assets. Comparable star swaps are stored "
            "separately as value comparisons, not trade predictions."
        )

        rows.append(row)

    if missing_ids:
        raise ValueError(
            "Pair rows referenced player IDs missing from "
            "the calibrated market layer:\n"
            + "\n".join(
                sorted(
                    missing_ids
                )
            )
        )

    return (
        pd.DataFrame(
            rows
        )
        .sort_values(
            [
                "ordinary_trade_review_eligible",
                "star_swap_value_comparison_eligible",
                "realism_adjusted_trade_score_v2",
            ],
            ascending=[
                False,
                False,
                False,
            ],
        )
        .reset_index(drop=True)
    )


def build_team_targets(
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for pair in recommendations.to_dict(
        orient="records"
    ):
        for side, other_side in [
            ("a", "b"),
            ("b", "a"),
        ]:
            rows.append(
                {
                    "team_abbreviation": (
                        pair[
                            f"team_{side}"
                        ]
                    ),
                    "trade_partner": (
                        pair[
                            f"team_{other_side}"
                        ]
                    ),
                    "outgoing_player": (
                        pair[
                            f"player_{side}_name"
                        ]
                    ),
                    "incoming_player": (
                        pair[
                            f"player_{other_side}_name"
                        ]
                    ),
                    "outgoing_asset_tier_v2": (
                        pair[
                            (
                                f"player_{side}_"
                                "asset_tier_v2"
                            )
                        ]
                    ),
                    "incoming_asset_tier_v2": (
                        pair[
                            (
                                f"player_{other_side}_"
                                "asset_tier_v2"
                            )
                        ]
                    ),
                    "outgoing_archetype": (
                        pair.get(
                            (
                                f"player_{side}_"
                                "playstyle_archetype"
                            ),
                            pd.NA,
                        )
                    ),
                    "incoming_archetype": (
                        pair.get(
                            (
                                f"player_{other_side}_"
                                "playstyle_archetype"
                            ),
                            pd.NA,
                        )
                    ),
                    "realism_adjusted_trade_score_v2": (
                        pair[
                            "realism_adjusted_trade_score_v2"
                        ]
                    ),
                    "team_trade_fit_score": (
                        pair[
                            (
                                f"team_{side}_"
                                "trade_fit_score"
                            )
                        ]
                    ),
                    "market_value_gap_v2": (
                        pair[
                            "market_value_gap_v2"
                        ]
                    ),
                    "critical_team_need": (
                        pair[
                            (
                                f"team_{side}_"
                                "critical_need"
                            )
                        ]
                    ),
                    "expected_contribution_delta": (
                        pair[
                            (
                                f"team_{side}_"
                                "expected_delta"
                            )
                        ]
                    ),
                    "downside_contribution_delta": (
                        pair[
                            (
                                f"team_{side}_"
                                "downside_delta"
                            )
                        ]
                    ),
                    "v2_review_tier": (
                        pair[
                            "v2_review_tier"
                        ]
                    ),
                    "pair_id": (
                        pair[
                            "pair_id"
                        ]
                    ),
                }
            )

    targets = pd.DataFrame(
        rows
    )

    if targets.empty:
        return targets

    targets[
        "team_target_rank"
    ] = (
        targets.groupby(
            "team_abbreviation"
        )[
            "realism_adjusted_trade_score_v2"
        ]
        .rank(
            method="first",
            ascending=False,
        )
        .astype(int)
    )

    return targets.sort_values(
        [
            "team_abbreviation",
            "team_target_rank",
        ]
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
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, float):
        if math.isnan(value):
            return None
        return value

    if pd.isna(value):
        return None

    return value


def format_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    return f"${float(value):,.0f}"


def main() -> None:
    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("TRADE REALISM CALIBRATION V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    players_v1, pairs_v1 = (
        load_inputs()
    )

    players_v2 = (
        build_player_market_v2(
            players_v1
        )
    )

    pairs_v2 = (
        build_pair_calibration(
            pairs=pairs_v1,
            players=players_v2,
        )
    )

    ordinary = (
        pairs_v2.loc[
            pairs_v2[
                "ordinary_trade_review_eligible"
            ]
        ]
        .copy()
        .sort_values(
            [
                "realism_adjusted_trade_score_v2",
                "minimum_team_trade_fit_score",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(drop=True)
    )

    stars = (
        pairs_v2.loc[
            pairs_v2[
                "star_swap_value_comparison_eligible"
            ]
        ]
        .copy()
        .sort_values(
            "realism_adjusted_trade_score_v2",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    filtered = (
        pairs_v2.loc[
            pairs_v2[
                "recommendation_eligible"
            ].fillna(False)
            & ~pairs_v2[
                "ordinary_trade_review_eligible"
            ].fillna(False)
            & ~pairs_v2[
                "star_swap_value_comparison_eligible"
            ].fillna(False)
        ]
        .copy()
        .sort_values(
            "mutual_trade_score",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    team_targets = (
        build_team_targets(
            ordinary
        )
    )

    players_v2.to_parquet(
        PLAYER_MARKET_V2_PARQUET_PATH,
        index=False,
    )

    players_v2.to_csv(
        PLAYER_MARKET_V2_CSV_PATH,
        index=False,
    )

    pairs_v2.to_parquet(
        REALISM_SCORES_V2_PARQUET_PATH,
        index=False,
    )

    ordinary_columns = [
        "pair_id",
        "v2_review_tier",
        "realism_adjusted_trade_score_v2",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "market_value_gap_v2",
        "player_quality_gap",
        "asset_tier_gap_v2",
        "team_a",
        "player_a_name",
        "player_a_salary",
        "player_a_age",
        "player_a_asset_tier_v2",
        "player_a_market_value_percentile_v2",
        "player_a_playstyle_archetype",
        "team_a_trade_fit_score",
        "team_a_critical_need",
        "team_a_expected_delta",
        "team_a_downside_delta",
        "team_a_selected_salary_method",
        "team_b",
        "player_b_name",
        "player_b_salary",
        "player_b_age",
        "player_b_asset_tier_v2",
        "player_b_market_value_percentile_v2",
        "player_b_playstyle_archetype",
        "team_b_trade_fit_score",
        "team_b_critical_need",
        "team_b_expected_delta",
        "team_b_downside_delta",
        "team_b_selected_salary_method",
        "v2_scope_note",
    ]

    ordinary[
        [
            column
            for column
            in ordinary_columns
            if column
            in ordinary.columns
        ]
    ].to_csv(
        ORDINARY_RECOMMENDATIONS_PATH,
        index=False,
    )

    star_columns = [
        "pair_id",
        "realism_adjusted_trade_score_v2",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "market_value_gap_v2",
        "team_a",
        "player_a_name",
        "player_a_age",
        "player_a_asset_tier_v2",
        "player_a_market_value_percentile_v2",
        "team_b",
        "player_b_name",
        "player_b_age",
        "player_b_asset_tier_v2",
        "player_b_market_value_percentile_v2",
        "v2_scope_note",
    ]

    stars[
        [
            column
            for column
            in star_columns
            if column
            in stars.columns
        ]
    ].to_csv(
        STAR_COMPARISONS_PATH,
        index=False,
    )

    filtered_columns = [
        "pair_id",
        "mutual_trade_score",
        "realism_adjusted_trade_score_v2",
        "team_a",
        "player_a_name",
        "player_a_asset_tier_v2",
        "team_b",
        "player_b_name",
        "player_b_asset_tier_v2",
        "market_value_gap_v2",
        "asset_tier_gap_v2",
        "v2_filter_reasons",
    ]

    filtered[
        [
            column
            for column
            in filtered_columns
            if column
            in filtered.columns
        ]
    ].to_csv(
        FILTERED_AUDIT_PATH,
        index=False,
    )

    team_targets.to_csv(
        TEAM_TARGETS_PATH,
        index=False,
    )

    tier_counts = (
        players_v2[
            "asset_tier_v2"
        ]
        .value_counts()
        .to_dict()
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "player_rows": len(
            players_v2
        ),
        "asset_tier_counts_v2": (
            tier_counts
        ),
        "all_pair_rows": len(
            pairs_v2
        ),
        "original_recommendation_eligible_pairs": int(
            pairs_v2[
                "recommendation_eligible"
            ].fillna(False).sum()
        ),
        "ordinary_trade_review_pairs": len(
            ordinary
        ),
        "star_swap_value_comparison_pairs": len(
            stars
        ),
        "original_eligible_pairs_filtered": len(
            filtered
        ),
        "strong_ordinary_trade_reviews": int(
            ordinary[
                "v2_review_tier"
            ].eq(
                "strong_ordinary_trade_review"
            ).sum()
        ),
        "detailed_ordinary_trade_reviews": int(
            ordinary[
                "v2_review_tier"
            ].eq(
                "detailed_ordinary_trade_review"
            ).sum()
        ),
        "exploratory_ordinary_trade_reviews": int(
            ordinary[
                "v2_review_tier"
            ].eq(
                "exploratory_ordinary_trade_review"
            ).sum()
        ),
        "quality_weights": (
            QUALITY_WEIGHTS
        ),
        "market_value_weights_v2": (
            MARKET_VALUE_WEIGHTS_V2
        ),
        "surplus_value_weights": (
            SURPLUS_VALUE_WEIGHTS
        ),
        "pair_score_weights_v2": (
            PAIR_SCORE_WEIGHTS_V2
        ),
        "ordinary_trade_filters": {
            "major_assets_excluded": True,
            "minimum_adjusted_score": 65.0,
            "minimum_team_fit_score": 50.0,
            "maximum_market_value_gap": 10.0,
            "maximum_asset_tier_gap": 1,
            "minimum_expected_retention": 0.85,
            "minimum_downside_retention": 0.70,
        },
        "star_comparison_filters": {
            "both_players_major_assets": True,
            "same_asset_tier": True,
            "maximum_market_value_gap": 6.0,
            "minimum_adjusted_score": 68.0,
            "minimum_team_fit_score": 50.0,
            "minimum_expected_retention": 0.85,
            "minimum_downside_retention": 0.70,
            "classification": (
                "value comparison only, not recommendation"
            ),
        },
        "limitations": [
            (
                "Asset tiers remain model-derived labels, not "
                "league or front-office consensus."
            ),
            (
                "Star comparisons indicate comparable modeled "
                "value and fit, not actual trade likelihood."
            ),
            (
                "Draft assets, team direction, player requests, "
                "and individual restrictions remain absent."
            ),
            (
                "Official salary legality remains unverified."
            ),
        ],
        "output_files": {
            "player_market_v2": str(
                PLAYER_MARKET_V2_PARQUET_PATH
            ),
            "all_pair_scores_v2": str(
                REALISM_SCORES_V2_PARQUET_PATH
            ),
            "ordinary_recommendations": str(
                ORDINARY_RECOMMENDATIONS_PATH
            ),
            "star_value_comparisons": str(
                STAR_COMPARISONS_PATH
            ),
            "filtered_audit": str(
                FILTERED_AUDIT_PATH
            ),
            "team_targets": str(
                TEAM_TARGETS_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print(
        f"Player rows: "
        f"{len(players_v2):,}"
    )
    print(
        "Original recommendation-eligible pairs: "
        f"{metadata['original_recommendation_eligible_pairs']:,}"
    )
    print(
        "Ordinary one-for-one review pairs: "
        f"{len(ordinary):,}"
    )
    print(
        "Star-swap value comparisons: "
        f"{len(stars):,}"
    )
    print(
        "Original eligible pairs filtered out: "
        f"{len(filtered):,}"
    )
    print()

    print("V2 ASSET-TIER COUNTS")
    print(
        players_v2[
            "asset_tier_v2"
        ]
        .value_counts()
        .to_string()
    )
    print()

    print("TOP 25 V2 PLAYER MARKET VALUES")
    player_display_columns = [
        "player_name",
        "current_team_2026_27",
        "age",
        "trade_salary_2026_27",
        "player_quality_score",
        "surplus_value_score",
        "market_value_percentile_v2",
        "asset_tier_v2",
        "playstyle_archetype",
    ]

    player_display = (
        players_v2.head(
            25
        )[
            player_display_columns
        ]
        .copy()
    )

    player_display[
        "trade_salary_2026_27"
    ] = player_display[
        "trade_salary_2026_27"
    ].map(
        format_money
    )

    for column in [
        "age",
        "player_quality_score",
        "surplus_value_score",
        "market_value_percentile_v2",
    ]:
        player_display[column] = (
            pd.to_numeric(
                player_display[column],
                errors="coerce",
            )
            .round(2)
        )

    print(
        player_display.to_string(
            index=False,
        )
    )
    print()

    print("TOP 30 ORDINARY ONE-FOR-ONE TRADE REVIEWS")
    if ordinary.empty:
        print(
            "No ordinary trades passed every V2 realism rule."
        )
    else:
        display_columns = [
            "v2_review_tier",
            "realism_adjusted_trade_score_v2",
            "team_a",
            "player_a_name",
            "player_a_asset_tier_v2",
            "team_b",
            "player_b_name",
            "player_b_asset_tier_v2",
            "market_value_gap_v2",
            "minimum_team_trade_fit_score",
        ]

        display = ordinary.head(
            30
        )[
            display_columns
        ].copy()

        for column in [
            "realism_adjusted_trade_score_v2",
            "market_value_gap_v2",
            "minimum_team_trade_fit_score",
        ]:
            display[column] = (
                pd.to_numeric(
                    display[column],
                    errors="coerce",
                )
                .round(3)
            )

        print(
            display.to_string(
                index=False,
            )
        )

    print()
    print("TOP 20 STAR-SWAP VALUE COMPARISONS")
    if stars.empty:
        print(
            "No major-asset pairs passed the separate "
            "value-comparison rules."
        )
    else:
        display_columns = [
            "realism_adjusted_trade_score_v2",
            "team_a",
            "player_a_name",
            "player_a_asset_tier_v2",
            "team_b",
            "player_b_name",
            "player_b_asset_tier_v2",
            "market_value_gap_v2",
            "minimum_team_trade_fit_score",
        ]

        display = stars.head(
            20
        )[
            display_columns
        ].copy()

        for column in [
            "realism_adjusted_trade_score_v2",
            "market_value_gap_v2",
            "minimum_team_trade_fit_score",
        ]:
            display[column] = (
                pd.to_numeric(
                    display[column],
                    errors="coerce",
                )
                .round(3)
            )

        print(
            display.to_string(
                index=False,
            )
        )

    print()
    print("SAVED FILES")
    print(
        PLAYER_MARKET_V2_PARQUET_PATH
    )
    print(
        PLAYER_MARKET_V2_CSV_PATH
    )
    print(
        REALISM_SCORES_V2_PARQUET_PATH
    )
    print(
        ORDINARY_RECOMMENDATIONS_PATH
    )
    print(
        STAR_COMPARISONS_PATH
    )
    print(
        FILTERED_AUDIT_PATH
    )
    print(
        TEAM_TARGETS_PATH
    )
    print(METADATA_PATH)


if __name__ == "__main__":
    main()