from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "trade-realism-protected-player-gate-v3-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PLAYER_MARKET_V2_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_trade_market_value_layer_2026_27_v2.parquet"
)

PAIR_SCORES_V2_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "one_for_one_trade_realism_scores_2026_27_v2.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

PLAYER_MARKET_V3_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)

PLAYER_MARKET_V3_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v3.csv"
)

PAIR_SCORES_V3_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_scores_2026_27_v3.parquet"
)

ORDINARY_RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_recommendations_2026_27_v3.csv"
)

PREMIUM_COMPARISONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_premium_player_value_comparisons_2026_27_v3.csv"
)

FILTERED_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_filtered_audit_2026_27_v3.csv"
)

TEAM_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_realistic_trade_targets_2026_27_v3.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "trade_realism_protected_player_metadata_2026_27_v3.json"
)


CALIBER_WEIGHTS = {
    "expected_contribution_percentile": 0.40,
    "roster_value_percentile": 0.25,
    "downside_contribution_percentile": 0.15,
    "skill_breadth_score": 0.10,
    "survival_percentile": 0.10,
}

V3_PAIR_SCORE_WEIGHTS = {
    "v2_realism_score": 0.50,
    "minimum_team_fit_score": 0.25,
    "market_value_parity": 0.15,
    "age_parity": 0.10,
}

PROTECTED_CLASSES = {
    "franchise_caliber",
    "star_caliber",
    "premium_young_asset",
}

CLASS_ORDER = {
    "franchise_caliber": 6,
    "star_caliber": 5,
    "premium_young_asset": 4,
    "high_end_starter": 3,
    "starter_rotation": 2,
    "rotation_depth": 1,
    "development_depth": 0,
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


def parity_score(
    first: float,
    second: float,
    scale: float,
) -> float:
    return float(
        np.clip(
            100.0
            - abs(first - second) * scale,
            0.0,
            100.0,
        )
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PLAYER_MARKET_V2_PATH,
        PAIR_SCORES_V2_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    players = pd.read_parquet(
        PLAYER_MARKET_V2_PATH
    )

    pairs = pd.read_parquet(
        PAIR_SCORES_V2_PATH
    )

    require_columns(
        players,
        [
            "player_id",
            "player_name",
            "age",
            "player_quality_score",
            "market_value_percentile_v2",
            "expected_contribution_percentile",
            "downside_contribution_percentile",
            "roster_value_percentile",
            "skill_breadth_score",
            "survival_percentile",
        ],
        "Player market layer V2",
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
            "recommendation_eligible",
            "realism_adjusted_trade_score_v2",
            "minimum_team_trade_fit_score",
            "market_value_parity_score_v2",
            "age_parity_score_v2",
            "market_value_gap_v2",
            "team_a_expected_retention_ratio",
            "team_b_expected_retention_ratio",
            "team_a_downside_retention_ratio",
            "team_b_downside_retention_ratio",
        ],
        "Pair scores V2",
    )

    return (
        players.copy(),
        pairs.copy(),
    )


def classify_recommendation_asset(
    row: pd.Series,
) -> str:
    caliber = float(
        row[
            "on_court_caliber_score"
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

    age = float(
        row["age"]
    ) if pd.notna(
        row["age"]
    ) else np.nan

    if (
        caliber >= 92.0
        and expected >= 85.0
        and roster >= 85.0
    ):
        return "franchise_caliber"

    if (
        caliber >= 86.0
        and expected >= 76.0
        and roster >= 78.0
    ):
        return "star_caliber"

    if (
        np.isfinite(age)
        and age <= 24.0
        and market >= 92.0
        and quality >= 82.0
    ):
        return "premium_young_asset"

    if (
        caliber >= 72.0
        and expected >= 60.0
    ):
        return "high_end_starter"

    if (
        caliber >= 58.0
        and expected >= 45.0
    ):
        return "starter_rotation"

    if caliber >= 40.0:
        return "rotation_depth"

    return "development_depth"


def build_player_market_v3(
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = players.copy()

    for column in CALIBER_WEIGHTS:
        output[column] = numeric_series(
            output,
            column,
            fill_value=50.0,
        ).clip(
            lower=0.0,
            upper=100.0,
        )

    output[
        "on_court_caliber_score"
    ] = 0.0

    for component, weight in (
        CALIBER_WEIGHTS.items()
    ):
        output[
            "on_court_caliber_score"
        ] += (
            weight
            * output[
                component
            ]
        )

    output[
        "recommendation_asset_class_v3"
    ] = output.apply(
        classify_recommendation_asset,
        axis=1,
    )

    output[
        "recommendation_asset_class_order_v3"
    ] = output[
        "recommendation_asset_class_v3"
    ].map(
        CLASS_ORDER
    ).astype(int)

    output[
        "protected_player_flag_v3"
    ] = output[
        "recommendation_asset_class_v3"
    ].isin(
        PROTECTED_CLASSES
    )

    output[
        "protected_player_reason_v3"
    ] = np.select(
        [
            output[
                "recommendation_asset_class_v3"
            ].eq(
                "franchise_caliber"
            ),
            output[
                "recommendation_asset_class_v3"
            ].eq(
                "star_caliber"
            ),
            output[
                "recommendation_asset_class_v3"
            ].eq(
                "premium_young_asset"
            ),
        ],
        [
            "elite_on_court_caliber",
            "high_on_court_caliber",
            "young_premium_market_asset",
        ],
        default="not_protected",
    )

    output[
        "protected_player_scope_note"
    ] = (
        "Protected status removes premium players from ordinary "
        "one-for-one recommendations. It is model-derived and "
        "does not mean the player is officially unavailable."
    )

    return output.sort_values(
        [
            "protected_player_flag_v3",
            "on_court_caliber_score",
            "market_value_percentile_v2",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)


def build_lookup(
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


def add_player_fields(
    row: dict[str, Any],
    side: str,
    player: dict[str, Any],
) -> None:
    prefix = f"player_{side}_"

    for field in [
        "age",
        "on_court_caliber_score",
        "recommendation_asset_class_v3",
        "recommendation_asset_class_order_v3",
        "protected_player_flag_v3",
        "protected_player_reason_v3",
        "market_value_percentile_v2",
        "player_quality_score",
        "playstyle_archetype",
    ]:
        row[
            f"{prefix}{field}"
        ] = player.get(
            field,
            pd.NA,
        )


def build_pair_scores_v3(
    pairs: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    lookup = build_lookup(
        players
    )

    rows: list[
        dict[str, Any]
    ] = []

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

        protected_a = bool(
            player_a[
                "protected_player_flag_v3"
            ]
        )

        protected_b = bool(
            player_b[
                "protected_player_flag_v3"
            ]
        )

        either_protected = bool(
            protected_a
            or protected_b
        )

        both_protected = bool(
            protected_a
            and protected_b
        )

        class_order_a = int(
            player_a[
                "recommendation_asset_class_order_v3"
            ]
        )

        class_order_b = int(
            player_b[
                "recommendation_asset_class_order_v3"
            ]
        )

        class_gap = abs(
            class_order_a
            - class_order_b
        )

        caliber_gap = abs(
            float(
                player_a[
                    "on_court_caliber_score"
                ]
            )
            - float(
                player_b[
                    "on_court_caliber_score"
                ]
            )
        )

        market_gap = float(
            pair[
                "market_value_gap_v2"
            ]
        )

        minimum_fit = float(
            pair[
                "minimum_team_trade_fit_score"
            ]
        )

        v2_score = float(
            pair[
                "realism_adjusted_trade_score_v2"
            ]
        )

        market_parity = float(
            pair[
                "market_value_parity_score_v2"
            ]
        )

        age_parity = float(
            pair[
                "age_parity_score_v2"
            ]
        )

        v3_score = (
            V3_PAIR_SCORE_WEIGHTS[
                "v2_realism_score"
            ]
            * v2_score
            + V3_PAIR_SCORE_WEIGHTS[
                "minimum_team_fit_score"
            ]
            * minimum_fit
            + V3_PAIR_SCORE_WEIGHTS[
                "market_value_parity"
            ]
            * market_parity
            + V3_PAIR_SCORE_WEIGHTS[
                "age_parity"
            ]
            * age_parity
        )

        expected_retention_pass = bool(
            float(
                pair[
                    "team_a_expected_retention_ratio"
                ]
            )
            >= 0.88
            and float(
                pair[
                    "team_b_expected_retention_ratio"
                ]
            )
            >= 0.88
        )

        downside_retention_pass = bool(
            float(
                pair[
                    "team_a_downside_retention_ratio"
                ]
            )
            >= 0.72
            and float(
                pair[
                    "team_b_downside_retention_ratio"
                ]
            )
            >= 0.72
        )

        ordinary_eligible = bool(
            pair[
                "recommendation_eligible"
            ]
            and not either_protected
            and v3_score >= 68.0
            and minimum_fit >= 52.0
            and market_gap <= 8.0
            and class_gap <= 1
            and caliber_gap <= 12.0
            and expected_retention_pass
            and downside_retention_pass
        )

        premium_comparison_eligible = bool(
            pair[
                "recommendation_eligible"
            ]
            and both_protected
            and v3_score >= 68.0
            and minimum_fit >= 50.0
            and market_gap <= 6.0
            and class_gap <= 1
            and caliber_gap <= 10.0
            and expected_retention_pass
            and downside_retention_pass
        )

        if ordinary_eligible:
            if (
                v3_score >= 76.0
                and minimum_fit >= 58.0
            ):
                review_tier = (
                    "strong_ordinary_review_v3"
                )
            elif v3_score >= 72.0:
                review_tier = (
                    "detailed_ordinary_review_v3"
                )
            else:
                review_tier = (
                    "exploratory_ordinary_review_v3"
                )
        elif premium_comparison_eligible:
            review_tier = (
                "premium_player_value_comparison_only"
            )
        else:
            review_tier = (
                "filtered_from_v3_review"
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

        if either_protected and not (
            premium_comparison_eligible
        ):
            filter_reasons.append(
                "protected_player_removed_from_ordinary_pool"
            )

        if v3_score < 68.0:
            filter_reasons.append(
                "v3_score_below_68"
            )

        if minimum_fit < 52.0:
            filter_reasons.append(
                "minimum_team_fit_below_52"
            )

        if market_gap > 8.0:
            filter_reasons.append(
                "market_value_gap_above_8"
            )

        if class_gap > 1:
            filter_reasons.append(
                "recommendation_asset_class_gap_above_one"
            )

        if caliber_gap > 12.0:
            filter_reasons.append(
                "on_court_caliber_gap_above_12"
            )

        if not expected_retention_pass:
            filter_reasons.append(
                "expected_retention_below_88_percent"
            )

        if not downside_retention_pass:
            filter_reasons.append(
                "downside_retention_below_72_percent"
            )

        row[
            "either_protected_player_flag_v3"
        ] = either_protected

        row[
            "both_protected_players_flag_v3"
        ] = both_protected

        row[
            "recommendation_asset_class_gap_v3"
        ] = class_gap

        row[
            "on_court_caliber_gap_v3"
        ] = caliber_gap

        row[
            "expected_retention_88_pass_v3"
        ] = expected_retention_pass

        row[
            "downside_retention_72_pass_v3"
        ] = downside_retention_pass

        row[
            "realism_adjusted_trade_score_v3"
        ] = v3_score

        row[
            "ordinary_trade_review_eligible_v3"
        ] = ordinary_eligible

        row[
            "premium_player_value_comparison_eligible_v3"
        ] = premium_comparison_eligible

        row[
            "v3_review_tier"
        ] = review_tier

        row[
            "v3_filter_reasons"
        ] = (
            " | ".join(
                filter_reasons
            )
        )

        row[
            "v3_scope_note"
        ] = (
            "Ordinary recommendations exclude every protected "
            "player. Premium-player matches are value comparisons "
            "only and are not presented as likely trades."
        )

        rows.append(row)

    if missing_ids:
        raise ValueError(
            "Pair rows referenced missing player IDs:\n"
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
                "ordinary_trade_review_eligible_v3",
                "premium_player_value_comparison_eligible_v3",
                "realism_adjusted_trade_score_v3",
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
                    "outgoing_asset_class_v3": (
                        pair[
                            (
                                f"player_{side}_"
                                "recommendation_asset_class_v3"
                            )
                        ]
                    ),
                    "incoming_asset_class_v3": (
                        pair[
                            (
                                f"player_{other_side}_"
                                "recommendation_asset_class_v3"
                            )
                        ]
                    ),
                    "realism_adjusted_trade_score_v3": (
                        pair[
                            "realism_adjusted_trade_score_v3"
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
            "realism_adjusted_trade_score_v3"
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
    print("TRADE REALISM PROTECTED-PLAYER GATE V3")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    players_v2, pairs_v2 = (
        load_inputs()
    )

    players_v3 = (
        build_player_market_v3(
            players_v2
        )
    )

    pairs_v3 = (
        build_pair_scores_v3(
            pairs=pairs_v2,
            players=players_v3,
        )
    )

    ordinary = (
        pairs_v3.loc[
            pairs_v3[
                "ordinary_trade_review_eligible_v3"
            ]
        ]
        .copy()
        .sort_values(
            "realism_adjusted_trade_score_v3",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    premium = (
        pairs_v3.loc[
            pairs_v3[
                "premium_player_value_comparison_eligible_v3"
            ]
        ]
        .copy()
        .sort_values(
            "realism_adjusted_trade_score_v3",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    filtered = (
        pairs_v3.loc[
            pairs_v3[
                "recommendation_eligible"
            ].fillna(False)
            & ~pairs_v3[
                "ordinary_trade_review_eligible_v3"
            ].fillna(False)
            & ~pairs_v3[
                "premium_player_value_comparison_eligible_v3"
            ].fillna(False)
        ]
        .copy()
        .sort_values(
            "mutual_trade_score",
            ascending=False,
        )
        .reset_index(drop=True)
    )

    team_targets = build_team_targets(
        ordinary
    )

    players_v3.to_parquet(
        PLAYER_MARKET_V3_PARQUET_PATH,
        index=False,
    )

    players_v3.to_csv(
        PLAYER_MARKET_V3_CSV_PATH,
        index=False,
    )

    pairs_v3.to_parquet(
        PAIR_SCORES_V3_PARQUET_PATH,
        index=False,
    )

    ordinary_columns = [
        "pair_id",
        "v3_review_tier",
        "realism_adjusted_trade_score_v3",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "market_value_gap_v2",
        "on_court_caliber_gap_v3",
        "team_a",
        "player_a_name",
        "player_a_age",
        "player_a_recommendation_asset_class_v3",
        "player_a_on_court_caliber_score",
        "team_a_trade_fit_score",
        "team_a_critical_need",
        "team_a_expected_delta",
        "team_a_downside_delta",
        "team_b",
        "player_b_name",
        "player_b_age",
        "player_b_recommendation_asset_class_v3",
        "player_b_on_court_caliber_score",
        "team_b_trade_fit_score",
        "team_b_critical_need",
        "team_b_expected_delta",
        "team_b_downside_delta",
        "v3_scope_note",
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

    premium_columns = [
        "pair_id",
        "realism_adjusted_trade_score_v3",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "market_value_gap_v2",
        "on_court_caliber_gap_v3",
        "team_a",
        "player_a_name",
        "player_a_age",
        "player_a_recommendation_asset_class_v3",
        "player_a_on_court_caliber_score",
        "team_b",
        "player_b_name",
        "player_b_age",
        "player_b_recommendation_asset_class_v3",
        "player_b_on_court_caliber_score",
        "v3_scope_note",
    ]

    premium[
        [
            column
            for column
            in premium_columns
            if column
            in premium.columns
        ]
    ].to_csv(
        PREMIUM_COMPARISONS_PATH,
        index=False,
    )

    filtered_columns = [
        "pair_id",
        "mutual_trade_score",
        "realism_adjusted_trade_score_v3",
        "team_a",
        "player_a_name",
        "player_a_recommendation_asset_class_v3",
        "team_b",
        "player_b_name",
        "player_b_recommendation_asset_class_v3",
        "market_value_gap_v2",
        "on_court_caliber_gap_v3",
        "v3_filter_reasons",
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

    class_counts = (
        players_v3[
            "recommendation_asset_class_v3"
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
            players_v3
        ),
        "protected_players": int(
            players_v3[
                "protected_player_flag_v3"
            ].sum()
        ),
        "asset_class_counts_v3": (
            class_counts
        ),
        "original_recommendation_eligible_pairs": int(
            pairs_v3[
                "recommendation_eligible"
            ].fillna(False).sum()
        ),
        "ordinary_trade_review_pairs_v3": len(
            ordinary
        ),
        "premium_player_value_comparisons_v3": len(
            premium
        ),
        "original_eligible_pairs_filtered_v3": len(
            filtered
        ),
        "caliber_weights": (
            CALIBER_WEIGHTS
        ),
        "v3_pair_score_weights": (
            V3_PAIR_SCORE_WEIGHTS
        ),
        "ordinary_filters": {
            "protected_players_excluded": True,
            "minimum_v3_score": 68.0,
            "minimum_team_fit": 52.0,
            "maximum_market_value_gap": 8.0,
            "maximum_asset_class_gap": 1,
            "maximum_on_court_caliber_gap": 12.0,
            "minimum_expected_retention": 0.88,
            "minimum_downside_retention": 0.72,
        },
        "premium_comparison_filters": {
            "both_players_protected": True,
            "classification": (
                "value comparison only"
            ),
            "minimum_v3_score": 68.0,
            "minimum_team_fit": 50.0,
            "maximum_market_value_gap": 6.0,
            "maximum_asset_class_gap": 1,
            "maximum_on_court_caliber_gap": 10.0,
            "minimum_expected_retention": 0.88,
            "minimum_downside_retention": 0.72,
        },
        "limitations": [
            (
                "Protected status is derived from the project "
                "model and is not an official availability label."
            ),
            (
                "Premium comparisons are not trade likelihood "
                "predictions."
            ),
            (
                "Draft assets, team direction, positions, and "
                "individual restrictions remain absent."
            ),
            (
                "Salary legality remains a proxy precheck."
            ),
        ],
        "output_files": {
            "player_market_v3": str(
                PLAYER_MARKET_V3_PARQUET_PATH
            ),
            "pair_scores_v3": str(
                PAIR_SCORES_V3_PARQUET_PATH
            ),
            "ordinary_recommendations_v3": str(
                ORDINARY_RECOMMENDATIONS_PATH
            ),
            "premium_comparisons_v3": str(
                PREMIUM_COMPARISONS_PATH
            ),
            "filtered_audit_v3": str(
                FILTERED_AUDIT_PATH
            ),
            "team_targets_v3": str(
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
        f"{len(players_v3):,}"
    )
    print(
        "Protected players: "
        f"{metadata['protected_players']:,}"
    )
    print(
        "Original recommendation-eligible pairs: "
        f"{metadata['original_recommendation_eligible_pairs']:,}"
    )
    print(
        "Ordinary one-for-one review pairs V3: "
        f"{len(ordinary):,}"
    )
    print(
        "Premium-player value comparisons V3: "
        f"{len(premium):,}"
    )
    print(
        "Original eligible pairs filtered V3: "
        f"{len(filtered):,}"
    )
    print()

    print("V3 RECOMMENDATION-ASSET CLASS COUNTS")
    print(
        players_v3[
            "recommendation_asset_class_v3"
        ]
        .value_counts()
        .to_string()
    )
    print()

    print("PROTECTED PLAYERS")
    protected_display = (
        players_v3.loc[
            players_v3[
                "protected_player_flag_v3"
            ],
            [
                "player_name",
                "current_team_2026_27",
                "age",
                "on_court_caliber_score",
                "market_value_percentile_v2",
                "recommendation_asset_class_v3",
                "protected_player_reason_v3",
            ],
        ]
        .sort_values(
            "on_court_caliber_score",
            ascending=False,
        )
        .copy()
    )

    for column in [
        "age",
        "on_court_caliber_score",
        "market_value_percentile_v2",
    ]:
        protected_display[column] = (
            pd.to_numeric(
                protected_display[column],
                errors="coerce",
            )
            .round(2)
        )

    print(
        protected_display.to_string(
            index=False,
        )
    )
    print()

    print("TOP 30 ORDINARY ONE-FOR-ONE REVIEWS V3")
    if ordinary.empty:
        print(
            "No ordinary trades passed every V3 rule."
        )
    else:
        display_columns = [
            "v3_review_tier",
            "realism_adjusted_trade_score_v3",
            "team_a",
            "player_a_name",
            "player_a_recommendation_asset_class_v3",
            "team_b",
            "player_b_name",
            "player_b_recommendation_asset_class_v3",
            "market_value_gap_v2",
            "on_court_caliber_gap_v3",
            "minimum_team_trade_fit_score",
        ]

        display = ordinary.head(
            30
        )[
            display_columns
        ].copy()

        for column in [
            "realism_adjusted_trade_score_v3",
            "market_value_gap_v2",
            "on_court_caliber_gap_v3",
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
    print("TOP 20 PREMIUM-PLAYER VALUE COMPARISONS V3")
    if premium.empty:
        print(
            "No protected-player pairs passed the separate "
            "comparison rules."
        )
    else:
        display_columns = [
            "realism_adjusted_trade_score_v3",
            "team_a",
            "player_a_name",
            "player_a_recommendation_asset_class_v3",
            "team_b",
            "player_b_name",
            "player_b_recommendation_asset_class_v3",
            "market_value_gap_v2",
            "on_court_caliber_gap_v3",
            "minimum_team_trade_fit_score",
        ]

        display = premium.head(
            20
        )[
            display_columns
        ].copy()

        for column in [
            "realism_adjusted_trade_score_v3",
            "market_value_gap_v2",
            "on_court_caliber_gap_v3",
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
        PLAYER_MARKET_V3_PARQUET_PATH
    )
    print(
        PLAYER_MARKET_V3_CSV_PATH
    )
    print(
        PAIR_SCORES_V3_PARQUET_PATH
    )
    print(
        ORDINARY_RECOMMENDATIONS_PATH
    )
    print(
        PREMIUM_COMPARISONS_PATH
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