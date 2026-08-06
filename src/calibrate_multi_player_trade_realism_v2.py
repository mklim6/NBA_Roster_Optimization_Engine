from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "multi-player-trade-realism-v2-fixed-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FIT_SCORES_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "two_for_one_trade_fit_scores_2026_27.parquet"
)

PLAYER_MARKET_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

ALL_REALISM_SCORES_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_realism_scores_2026_27_v2.parquet"
)

ORDINARY_RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_recommendations_2026_27_v2.csv"
)

PREMIUM_COMPARISONS_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_premium_package_value_comparisons_2026_27_v2.csv"
)

FILTERED_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_realism_filtered_audit_2026_27_v2.csv"
)

TEAM_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_multi_player_trade_targets_2026_27_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_realism_metadata_2026_27_v2.json"
)


PROTECTED_CLASSES = {
    "franchise_caliber",
    "star_caliber",
    "premium_young_asset",
}

PLAYER_REQUIRED_COLUMNS = [
    "player_id",
    "player_name",
    "trade_salary_2026_27",
    "projected_expected_contribution",
    "market_value_percentile_v2",
    "on_court_caliber_score",
    "recommendation_asset_class_v3",
    "protected_player_flag_v3",
]

PAIR_REQUIRED_COLUMNS = [
    "package_trade_id",
    "package_fit_review_eligible",
    "package_review_tier",
    "mutual_package_trade_score",
    "minimum_team_package_fit_score",
    "package_screening_score",
    "team_sending_two",
    "team_sending_one",
    "two_side_player_1_id",
    "two_side_player_1_name",
    "two_side_player_2_id",
    "two_side_player_2_name",
    "one_side_player_id",
    "one_side_player_name",
    "two_side_total_salary",
    "one_side_player_salary",
    "team_two_expected_retention_ratio",
    "team_one_expected_retention_ratio",
    "team_two_downside_retention_ratio",
    "team_one_downside_retention_ratio",
    "team_two_market_value_retention_ratio",
    "team_one_market_value_retention_ratio",
    "team_two_team_package_fit_score",
    "team_one_team_package_fit_score",
]


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


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path in [
        FIT_SCORES_PATH,
        PLAYER_MARKET_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    pairs = pd.read_parquet(
        FIT_SCORES_PATH
    )

    players = pd.read_parquet(
        PLAYER_MARKET_PATH
    )

    require_columns(
        pairs,
        PAIR_REQUIRED_COLUMNS,
        "Two-for-one fit scores",
    )

    require_columns(
        players,
        PLAYER_REQUIRED_COLUMNS,
        "Player market layer V3",
    )

    return (
        pairs.copy(),
        players.copy(),
    )


def prepare_players(
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = players.copy()

    output[
        "player_merge_key"
    ] = output[
        "player_id"
    ].map(
        player_key
    )

    if output[
        "player_merge_key"
    ].duplicated().any():
        duplicate_names = (
            output.loc[
                output[
                    "player_merge_key"
                ].duplicated(
                    keep=False
                ),
                "player_name",
            ]
            .astype(str)
            .tolist()
        )

        raise ValueError(
            "Player market layer contains duplicate IDs:\n"
            + "\n".join(
                duplicate_names
            )
        )

    if (
        "expected_contribution_percentile"
        not in output.columns
    ):
        output[
            "expected_contribution_percentile"
        ] = percentile_rank(
            output[
                "projected_expected_contribution"
            ]
        )

    numeric_columns = [
        "trade_salary_2026_27",
        "projected_expected_contribution",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "expected_contribution_percentile",
    ]

    for column in numeric_columns:
        output[column] = numeric_series(
            output,
            column,
            fill_value=0.0,
        )

    class_protected = output[
        "recommendation_asset_class_v3"
    ].isin(
        PROTECTED_CLASSES
    )

    existing_protected = output[
        "protected_player_flag_v3"
    ].fillna(False).astype(bool)

    caliber_protected = output[
        "on_court_caliber_score"
    ].ge(86.0)

    market_protected = output[
        "market_value_percentile_v2"
    ].ge(92.0)

    production_protected = output[
        "expected_contribution_percentile"
    ].ge(90.0)

    high_salary_quality_protected = (
        output[
            "trade_salary_2026_27"
        ].ge(35_000_000.0)
        & output[
            "on_court_caliber_score"
        ].ge(72.0)
    )

    output[
        "package_protected_player_flag_v2"
    ] = (
        existing_protected
        | class_protected
        | caliber_protected
        | market_protected
        | production_protected
        | high_salary_quality_protected
    )

    reasons: list[str] = []

    for index in output.index:
        row_reasons = []

        if existing_protected.loc[index]:
            row_reasons.append(
                "v3_protected"
            )

        if class_protected.loc[index]:
            row_reasons.append(
                "protected_asset_class"
            )

        if caliber_protected.loc[index]:
            row_reasons.append(
                "caliber_86_plus"
            )

        if market_protected.loc[index]:
            row_reasons.append(
                "market_percentile_92_plus"
            )

        if production_protected.loc[index]:
            row_reasons.append(
                "expected_percentile_90_plus"
            )

        if high_salary_quality_protected.loc[index]:
            row_reasons.append(
                "high_salary_quality_player"
            )

        reasons.append(
            " | ".join(
                row_reasons
            )
            if row_reasons
            else "not_protected"
        )

    output[
        "package_protected_player_reasons_v2"
    ] = reasons

    return output


def merge_player_context(
    pairs: pd.DataFrame,
    players: pd.DataFrame,
    id_column: str,
    prefix: str,
) -> pd.DataFrame:
    player_columns = [
        "player_merge_key",
        "player_name",
        "trade_salary_2026_27",
        "projected_expected_contribution",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "expected_contribution_percentile",
        "recommendation_asset_class_v3",
        "package_protected_player_flag_v2",
        "package_protected_player_reasons_v2",
    ]

    renamed_columns = {
        column: f"{prefix}{column}"
        for column in player_columns
        if column != "player_merge_key"
    }

    lookup = players[
        player_columns
    ].rename(
        columns=renamed_columns
    )

    output = pairs.copy()

    # The preceding package-fit stage already stores several p1_, p2_,
    # and s_ context columns. Drop those overlapping copies before this
    # merge so pandas does not create _x and _y suffixed column names.
    overlapping_context_columns = [
        renamed_column
        for renamed_column
        in renamed_columns.values()
        if renamed_column in output.columns
    ]

    if overlapping_context_columns:
        output = output.drop(
            columns=overlapping_context_columns
        )

    left_key = (
        f"{prefix}player_merge_key"
    )

    output[
        left_key
    ] = output[
        id_column
    ].map(
        player_key
    )

    output = output.merge(
        lookup,
        how="left",
        left_on=left_key,
        right_on="player_merge_key",
        validate="many_to_one",
    )

    return output.drop(
        columns=[
            "player_merge_key"
        ]
    )


def enrich_pairs(
    pairs: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = pairs.copy()

    output = merge_player_context(
        output,
        players,
        "two_side_player_1_id",
        "p1_",
    )

    output = merge_player_context(
        output,
        players,
        "two_side_player_2_id",
        "p2_",
    )

    output = merge_player_context(
        output,
        players,
        "one_side_player_id",
        "s_",
    )

    merged_names = [
        "p1_player_name",
        "p2_player_name",
        "s_player_name",
    ]

    missing_rows = output[
        merged_names
    ].isna().any(axis=1)

    if missing_rows.any():
        sample = output.loc[
            missing_rows,
            [
                "package_trade_id",
                "two_side_player_1_id",
                "two_side_player_2_id",
                "one_side_player_id",
            ],
        ].head(20)

        raise ValueError(
            "Some package players did not merge:\n"
            + sample.to_string(
                index=False
            )
        )

    return output


def add_realism_rules(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    p1_protected = output[
        "p1_package_protected_player_flag_v2"
    ].fillna(False).astype(bool)

    p2_protected = output[
        "p2_package_protected_player_flag_v2"
    ].fillna(False).astype(bool)

    single_protected = output[
        "s_package_protected_player_flag_v2"
    ].fillna(False).astype(bool)

    output[
        "two_side_protected_player_count_v2"
    ] = (
        p1_protected.astype(int)
        + p2_protected.astype(int)
    )

    output[
        "one_side_protected_player_count_v2"
    ] = single_protected.astype(int)

    output[
        "any_protected_player_flag_v2"
    ] = (
        p1_protected
        | p2_protected
        | single_protected
    )

    output[
        "protected_player_on_both_sides_v2"
    ] = (
        (
            output[
                "two_side_protected_player_count_v2"
            ]
            >= 1
        )
        & single_protected
    )

    p1_market = numeric_series(
        output,
        "p1_market_value_percentile_v2",
        fill_value=0.0,
    )

    p2_market = numeric_series(
        output,
        "p2_market_value_percentile_v2",
        fill_value=0.0,
    )

    single_market = numeric_series(
        output,
        "s_market_value_percentile_v2",
        fill_value=0.0,
    )

    p1_caliber = numeric_series(
        output,
        "p1_on_court_caliber_score",
        fill_value=0.0,
    )

    p2_caliber = numeric_series(
        output,
        "p2_on_court_caliber_score",
        fill_value=0.0,
    )

    single_caliber = numeric_series(
        output,
        "s_on_court_caliber_score",
        fill_value=0.0,
    )

    output[
        "two_side_best_market_percentile_v2"
    ] = np.maximum(
        p1_market,
        p2_market,
    )

    output[
        "two_side_second_market_percentile_v2"
    ] = np.minimum(
        p1_market,
        p2_market,
    )

    output[
        "two_side_best_caliber_v2"
    ] = np.maximum(
        p1_caliber,
        p2_caliber,
    )

    output[
        "two_side_second_caliber_v2"
    ] = np.minimum(
        p1_caliber,
        p2_caliber,
    )

    output[
        "premium_caliber_gap_v2"
    ] = (
        output[
            "two_side_best_caliber_v2"
        ]
        - single_caliber
    ).abs()

    output[
        "premium_market_gap_v2"
    ] = (
        output[
            "two_side_best_market_percentile_v2"
        ]
        - single_market
    ).abs()

    expected_pass = (
        output[
            "team_two_expected_retention_ratio"
        ].ge(0.85)
        & output[
            "team_one_expected_retention_ratio"
        ].ge(0.85)
    )

    downside_pass = (
        output[
            "team_two_downside_retention_ratio"
        ].ge(0.70)
        & output[
            "team_one_downside_retention_ratio"
        ].ge(0.70)
    )

    market_pass = (
        output[
            "team_two_market_value_retention_ratio"
        ].ge(0.85)
        & output[
            "team_one_market_value_retention_ratio"
        ].ge(0.85)
    )

    output[
        "strict_expected_retention_pass_v2"
    ] = expected_pass

    output[
        "strict_downside_retention_pass_v2"
    ] = downside_pass

    output[
        "strict_market_retention_pass_v2"
    ] = market_pass

    output[
        "ordinary_package_review_eligible_v2"
    ] = (
        output[
            "package_fit_review_eligible"
        ].fillna(False)
        & ~output[
            "any_protected_player_flag_v2"
        ]
        & output[
            "mutual_package_trade_score"
        ].ge(61.0)
        & output[
            "minimum_team_package_fit_score"
        ].ge(52.0)
        & output[
            "package_screening_score"
        ].ge(0.60)
        & expected_pass
        & downside_pass
        & market_pass
        & output[
            "two_side_second_market_percentile_v2"
        ].ge(20.0)
    )

    premium_expected_pass = (
        output[
            "team_two_expected_retention_ratio"
        ].ge(0.90)
        & output[
            "team_one_expected_retention_ratio"
        ].ge(0.90)
    )

    premium_downside_pass = (
        output[
            "team_two_downside_retention_ratio"
        ].ge(0.75)
        & output[
            "team_one_downside_retention_ratio"
        ].ge(0.75)
    )

    premium_market_pass = (
        output[
            "team_two_market_value_retention_ratio"
        ].ge(0.90)
        & output[
            "team_one_market_value_retention_ratio"
        ].ge(0.90)
    )

    output[
        "premium_package_value_comparison_eligible_v2"
    ] = (
        output[
            "package_fit_review_eligible"
        ].fillna(False)
        & output[
            "protected_player_on_both_sides_v2"
        ]
        & output[
            "mutual_package_trade_score"
        ].ge(61.0)
        & output[
            "minimum_team_package_fit_score"
        ].ge(52.0)
        & premium_expected_pass
        & premium_downside_pass
        & premium_market_pass
        & output[
            "premium_caliber_gap_v2"
        ].le(8.0)
        & output[
            "premium_market_gap_v2"
        ].le(8.0)
    )

    output[
        "realism_review_tier_v2"
    ] = np.select(
        [
            (
                output[
                    "ordinary_package_review_eligible_v2"
                ]
                & output[
                    "mutual_package_trade_score"
                ].ge(68.0)
                & output[
                    "minimum_team_package_fit_score"
                ].ge(58.0)
            ),
            (
                output[
                    "ordinary_package_review_eligible_v2"
                ]
                & output[
                    "mutual_package_trade_score"
                ].ge(64.0)
                & output[
                    "minimum_team_package_fit_score"
                ].ge(55.0)
            ),
            output[
                "ordinary_package_review_eligible_v2"
            ],
            output[
                "premium_package_value_comparison_eligible_v2"
            ],
        ],
        [
            "strong_ordinary_package_review",
            "detailed_ordinary_package_review",
            "exploratory_ordinary_package_review",
            "premium_package_value_comparison_only",
        ],
        default="filtered_from_v2_review",
    )

    filter_reasons: list[str] = []

    for row in output.itertuples(
        index=False
    ):
        reasons = []

        if not bool(
            row.package_fit_review_eligible
        ):
            reasons.append(
                "failed_original_package_fit"
            )

        if bool(
            row.any_protected_player_flag_v2
        ) and not bool(
            row.premium_package_value_comparison_eligible_v2
        ):
            reasons.append(
                "protected_player_removed_from_ordinary_pool"
            )

        if (
            row.mutual_package_trade_score
            < 61.0
        ):
            reasons.append(
                "mutual_score_below_61"
            )

        if (
            row.minimum_team_package_fit_score
            < 52.0
        ):
            reasons.append(
                "minimum_team_fit_below_52"
            )

        if row.package_screening_score < 0.60:
            reasons.append(
                "package_screening_below_0_60"
            )

        if not bool(
            row.strict_expected_retention_pass_v2
        ):
            reasons.append(
                "expected_retention_below_85_percent"
            )

        if not bool(
            row.strict_downside_retention_pass_v2
        ):
            reasons.append(
                "downside_retention_below_70_percent"
            )

        if not bool(
            row.strict_market_retention_pass_v2
        ):
            reasons.append(
                "market_retention_below_85_percent"
            )

        if (
            row.two_side_second_market_percentile_v2
            < 20.0
        ):
            reasons.append(
                "second_package_asset_below_20th_percentile"
            )

        filter_reasons.append(
            " | ".join(
                reasons
            )
        )

    output[
        "realism_filter_reasons_v2"
    ] = filter_reasons

    output[
        "realism_scope_note_v2"
    ] = (
        "Ordinary package recommendations exclude every expanded "
        "protected player. Protected-player packages are stored "
        "separately as value comparisons, not trade predictions."
    )

    return output.sort_values(
        [
            "ordinary_package_review_eligible_v2",
            "premium_package_value_comparison_eligible_v2",
            "mutual_package_trade_score",
            "minimum_team_package_fit_score",
        ],
        ascending=[
            False,
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)


def build_team_targets(
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for package in recommendations.to_dict(
        orient="records"
    ):
        rows.append(
            {
                "team_abbreviation": (
                    package[
                        "team_sending_two"
                    ]
                ),
                "trade_partner": (
                    package[
                        "team_sending_one"
                    ]
                ),
                "trade_direction": (
                    "send_two_receive_one"
                ),
                "outgoing_players": (
                    f"{package['two_side_player_1_name']} + "
                    f"{package['two_side_player_2_name']}"
                ),
                "incoming_players": (
                    package[
                        "one_side_player_name"
                    ]
                ),
                "team_package_fit_score": (
                    package[
                        "team_two_team_package_fit_score"
                    ]
                ),
                "mutual_package_trade_score": (
                    package[
                        "mutual_package_trade_score"
                    ]
                ),
                "review_tier": (
                    package[
                        "realism_review_tier_v2"
                    ]
                ),
                "package_trade_id": (
                    package[
                        "package_trade_id"
                    ]
                ),
            }
        )

        rows.append(
            {
                "team_abbreviation": (
                    package[
                        "team_sending_one"
                    ]
                ),
                "trade_partner": (
                    package[
                        "team_sending_two"
                    ]
                ),
                "trade_direction": (
                    "send_one_receive_two"
                ),
                "outgoing_players": (
                    package[
                        "one_side_player_name"
                    ]
                ),
                "incoming_players": (
                    f"{package['two_side_player_1_name']} + "
                    f"{package['two_side_player_2_name']}"
                ),
                "team_package_fit_score": (
                    package[
                        "team_one_team_package_fit_score"
                    ]
                ),
                "mutual_package_trade_score": (
                    package[
                        "mutual_package_trade_score"
                    ]
                ),
                "review_tier": (
                    package[
                        "realism_review_tier_v2"
                    ]
                ),
                "package_trade_id": (
                    package[
                        "package_trade_id"
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
            "team_package_fit_score"
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
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("TWO-FOR-ONE TRADE REALISM CALIBRATION V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    pairs, players = load_inputs()

    players = prepare_players(
        players
    )

    enriched = enrich_pairs(
        pairs=pairs,
        players=players,
    )

    scored = add_realism_rules(
        enriched
    )

    ordinary = scored.loc[
        scored[
            "ordinary_package_review_eligible_v2"
        ]
    ].copy()

    premium = scored.loc[
        scored[
            "premium_package_value_comparison_eligible_v2"
        ]
    ].copy()

    filtered = scored.loc[
        scored[
            "package_fit_review_eligible"
        ].fillna(False)
        & ~scored[
            "ordinary_package_review_eligible_v2"
        ].fillna(False)
        & ~scored[
            "premium_package_value_comparison_eligible_v2"
        ].fillna(False)
    ].copy()

    team_targets = build_team_targets(
        ordinary
    )

    scored.to_parquet(
        ALL_REALISM_SCORES_PATH,
        index=False,
    )

    recommendation_columns = [
        "package_trade_id",
        "realism_review_tier_v2",
        "mutual_package_trade_score",
        "minimum_team_package_fit_score",
        "package_screening_score",
        "team_sending_two",
        "two_side_player_1_name",
        "two_side_player_2_name",
        "two_side_total_salary",
        "team_two_team_package_fit_score",
        "team_sending_one",
        "one_side_player_name",
        "one_side_player_salary",
        "team_one_team_package_fit_score",
        "two_side_second_market_percentile_v2",
        "team_two_expected_retention_ratio",
        "team_one_expected_retention_ratio",
        "team_two_downside_retention_ratio",
        "team_one_downside_retention_ratio",
        "team_two_market_value_retention_ratio",
        "team_one_market_value_retention_ratio",
        "realism_scope_note_v2",
    ]

    ordinary[
        [
            column
            for column in recommendation_columns
            if column in ordinary.columns
        ]
    ].to_csv(
        ORDINARY_RECOMMENDATIONS_PATH,
        index=False,
    )

    premium_columns = [
        "package_trade_id",
        "realism_review_tier_v2",
        "mutual_package_trade_score",
        "minimum_team_package_fit_score",
        "team_sending_two",
        "two_side_player_1_name",
        "two_side_player_2_name",
        "team_sending_one",
        "one_side_player_name",
        "two_side_protected_player_count_v2",
        "one_side_protected_player_count_v2",
        "premium_caliber_gap_v2",
        "premium_market_gap_v2",
        "realism_scope_note_v2",
    ]

    premium[
        [
            column
            for column in premium_columns
            if column in premium.columns
        ]
    ].to_csv(
        PREMIUM_COMPARISONS_PATH,
        index=False,
    )

    filtered_columns = [
        "package_trade_id",
        "mutual_package_trade_score",
        "minimum_team_package_fit_score",
        "team_sending_two",
        "two_side_player_1_name",
        "two_side_player_2_name",
        "team_sending_one",
        "one_side_player_name",
        "any_protected_player_flag_v2",
        "realism_filter_reasons_v2",
    ]

    filtered[
        [
            column
            for column in filtered_columns
            if column in filtered.columns
        ]
    ].to_csv(
        FILTERED_AUDIT_PATH,
        index=False,
    )

    team_targets.to_csv(
        TEAM_TARGETS_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "all_package_rows": len(
            scored
        ),
        "original_fit_eligible_packages": int(
            scored[
                "package_fit_review_eligible"
            ].fillna(False).sum()
        ),
        "ordinary_package_reviews_v2": len(
            ordinary
        ),
        "premium_package_value_comparisons_v2": len(
            premium
        ),
        "original_fit_candidates_filtered_v2": len(
            filtered
        ),
        "expanded_protected_players": int(
            players[
                "package_protected_player_flag_v2"
            ].sum()
        ),
        "ordinary_rules": {
            "protected_players_excluded": True,
            "minimum_mutual_score": 61.0,
            "minimum_team_fit": 52.0,
            "minimum_package_screening": 0.60,
            "minimum_expected_retention": 0.85,
            "minimum_downside_retention": 0.70,
            "minimum_market_retention": 0.85,
            "minimum_second_package_asset_percentile": 20.0,
        },
        "premium_comparison_rules": {
            "protected_player_required_on_both_sides": True,
            "minimum_mutual_score": 61.0,
            "minimum_team_fit": 52.0,
            "minimum_expected_retention": 0.90,
            "minimum_downside_retention": 0.75,
            "minimum_market_retention": 0.90,
            "maximum_best_asset_caliber_gap": 8.0,
            "maximum_best_asset_market_gap": 8.0,
            "classification": (
                "value comparison only, not recommendation"
            ),
        },
        "limitations": [
            (
                "Protected status is model-derived and does not "
                "mean a player is officially unavailable."
            ),
            (
                "Premium packages are value comparisons, not "
                "trade-likelihood predictions."
            ),
            (
                "Draft assets, positions, official roster slots, "
                "team direction, and individual restrictions "
                "remain absent."
            ),
            (
                "Salary legality remains a proxy precheck."
            ),
        ],
        "output_files": {
            "all_realism_scores": str(
                ALL_REALISM_SCORES_PATH
            ),
            "ordinary_recommendations": str(
                ORDINARY_RECOMMENDATIONS_PATH
            ),
            "premium_comparisons": str(
                PREMIUM_COMPARISONS_PATH
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
        "Original fit-eligible packages: "
        f"{metadata['original_fit_eligible_packages']:,}"
    )
    print(
        "Expanded protected players: "
        f"{metadata['expanded_protected_players']:,}"
    )
    print(
        "Ordinary package reviews V2: "
        f"{len(ordinary):,}"
    )
    print(
        "Premium package value comparisons V2: "
        f"{len(premium):,}"
    )
    print(
        "Original fit candidates filtered V2: "
        f"{len(filtered):,}"
    )
    print()

    print("TOP 30 ORDINARY PACKAGE REVIEWS V2")
    if ordinary.empty:
        print(
            "No ordinary packages passed every V2 realism rule."
        )
    else:
        display_columns = [
            "realism_review_tier_v2",
            "mutual_package_trade_score",
            "team_sending_two",
            "two_side_player_1_name",
            "two_side_player_2_name",
            "two_side_total_salary",
            "team_sending_one",
            "one_side_player_name",
            "one_side_player_salary",
            "minimum_team_package_fit_score",
        ]

        display = ordinary.head(
            30
        )[
            display_columns
        ].copy()

        for column in [
            "two_side_total_salary",
            "one_side_player_salary",
        ]:
            display[column] = (
                display[column]
                .map(
                    format_money
                )
            )

        for column in [
            "mutual_package_trade_score",
            "minimum_team_package_fit_score",
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
    print("TOP 20 PREMIUM PACKAGE VALUE COMPARISONS V2")
    if premium.empty:
        print(
            "No protected-player packages passed the separate "
            "comparison rules."
        )
    else:
        display_columns = [
            "mutual_package_trade_score",
            "team_sending_two",
            "two_side_player_1_name",
            "two_side_player_2_name",
            "team_sending_one",
            "one_side_player_name",
            "premium_caliber_gap_v2",
            "premium_market_gap_v2",
            "minimum_team_package_fit_score",
        ]

        display = premium.head(
            20
        )[
            display_columns
        ].copy()

        for column in [
            "mutual_package_trade_score",
            "premium_caliber_gap_v2",
            "premium_market_gap_v2",
            "minimum_team_package_fit_score",
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
    print(ALL_REALISM_SCORES_PATH)
    print(ORDINARY_RECOMMENDATIONS_PATH)
    print(PREMIUM_COMPARISONS_PATH)
    print(FILTERED_AUDIT_PATH)
    print(TEAM_TARGETS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()