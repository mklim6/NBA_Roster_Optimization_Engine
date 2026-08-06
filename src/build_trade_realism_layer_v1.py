from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "trade-realism-layer-v1-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FIT_SCORES_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "one_for_one_trade_fit_scores_2026_27.parquet"
)

TRADE_POOL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "trade_fit_player_pool_2026_27.parquet"
)

PROJECTION_BOARD_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "current_player_projection_board_2025_26_to_2026_27.parquet"
)

SKILL_PROFILES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_skill_profiles_2025_26.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

PLAYER_MARKET_LAYER_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27.parquet"
)

PLAYER_MARKET_LAYER_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27.csv"
)

ALL_REALISM_SCORES_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_scores_2026_27.parquet"
)

REALISTIC_RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_recommendations_2026_27.csv"
)

FILTERED_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_filtered_audit_2026_27.csv"
)

TEAM_REALISTIC_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_realistic_trade_targets_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "trade_realism_layer_metadata_2026_27.json"
)


SKILL_PERCENTILE_COLUMNS = [
    "scoring_percentile",
    "shooting_percentile",
    "playmaking_percentile",
    "rebounding_percentile",
    "defense_percentile",
]

MARKET_VALUE_WEIGHTS = {
    "expected_contribution_percentile": 0.35,
    "downside_contribution_percentile": 0.20,
    "roster_value_percentile": 0.20,
    "contract_value_percentile": 0.10,
    "age_market_score": 0.10,
    "contract_control_score": 0.05,
}

REALISM_SCORE_WEIGHTS = {
    "mutual_trade_score": 0.55,
    "asset_parity_score": 0.25,
    "age_parity_score": 0.08,
    "contract_control_parity_score": 0.07,
    "asset_tier_parity_score": 0.05,
}

ASSET_TIER_ORDER = {
    "franchise_cornerstone": 5,
    "core_star": 4,
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


def player_key(
    value: Any,
) -> str:
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


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        FIT_SCORES_PATH,
        TRADE_POOL_PATH,
        PROJECTION_BOARD_PATH,
        SKILL_PROFILES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    scores = pd.read_parquet(
        FIT_SCORES_PATH
    )

    trade_pool = pd.read_parquet(
        TRADE_POOL_PATH
    )

    projection_board = pd.read_parquet(
        PROJECTION_BOARD_PATH
    )

    skills = pd.read_parquet(
        SKILL_PROFILES_PATH
    )

    require_columns(
        scores,
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
        "Trade fit scores",
    )

    require_columns(
        trade_pool,
        [
            "player_id",
            "player_name",
            "current_team_2026_27",
            "trade_salary_2026_27",
            "projected_expected_contribution",
            "projected_survival_probability",
            "survival_weighted_active_downside_score",
        ],
        "Trade player pool",
    )

    require_columns(
        skills,
        [
            "player_id",
            "player_name",
            "roster_value_percentile",
            "scoring_score",
            "shooting_score",
            "playmaking_score",
            "rebounding_score",
            "defense_score",
        ],
        "Skill profiles",
    )

    return (
        scores.copy(),
        trade_pool.copy(),
        projection_board.copy(),
        skills.copy(),
    )


def merge_player_context(
    trade_pool: pd.DataFrame,
    projection_board: pd.DataFrame,
    skills: pd.DataFrame,
) -> pd.DataFrame:
    pool = trade_pool.copy()
    projection = projection_board.copy()
    profile = skills.copy()

    pool[
        "player_merge_key"
    ] = pool[
        "player_id"
    ].map(
        player_key
    )

    projection[
        "player_merge_key"
    ] = projection[
        "player_id"
    ].map(
        player_key
    )

    profile[
        "player_merge_key"
    ] = profile[
        "player_id"
    ].map(
        player_key
    )

    projection_columns = [
        "player_merge_key",
    ]

    for column in [
        "age",
        "games_played",
        "minutes_per_game",
        "projected_rotation_probability",
        "projection_uncertainty_percentile",
        "projection_board_rank",
    ]:
        if column in projection.columns:
            projection_columns.append(
                column
            )

    profile_columns = [
        "player_merge_key",
        "roster_value_percentile",
        "scoring_score",
        "shooting_score",
        "playmaking_score",
        "rebounding_score",
        "defense_score",
    ]

    for column in [
        "value_tier",
        "confidence_tier",
        "primary_skill",
        "secondary_skill",
    ]:
        if column in profile.columns:
            profile_columns.append(
                column
            )

    drop_columns = [
        column
        for column in (
            projection_columns
            + profile_columns
        )
        if (
            column
            in pool.columns
            and column
            != "player_merge_key"
        )
    ]

    if drop_columns:
        pool = pool.drop(
            columns=sorted(
                set(
                    drop_columns
                )
            )
        )

    context = (
        pool.merge(
            projection[
                projection_columns
            ].drop_duplicates(
                subset=[
                    "player_merge_key"
                ]
            ),
            how="left",
            on="player_merge_key",
            validate="one_to_one",
        )
        .merge(
            profile[
                profile_columns
            ].drop_duplicates(
                subset=[
                    "player_merge_key"
                ]
            ),
            how="left",
            on="player_merge_key",
            validate="one_to_one",
        )
    )

    return context


def add_skill_percentiles(
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = players.copy()

    mapping = {
        "scoring_score": (
            "scoring_percentile"
        ),
        "shooting_score": (
            "shooting_percentile"
        ),
        "playmaking_score": (
            "playmaking_percentile"
        ),
        "rebounding_score": (
            "rebounding_percentile"
        ),
        "defense_score": (
            "defense_percentile"
        ),
    }

    for source, target in mapping.items():
        output[target] = percentile_rank(
            output[source]
        )

    return output


def classify_archetype(
    row: pd.Series,
) -> str:
    scoring = float(
        row[
            "scoring_percentile"
        ]
    )

    shooting = float(
        row[
            "shooting_percentile"
        ]
    )

    playmaking = float(
        row[
            "playmaking_percentile"
        ]
    )

    rebounding = float(
        row[
            "rebounding_percentile"
        ]
    )

    defense = float(
        row[
            "defense_percentile"
        ]
    )

    if (
        playmaking >= 80.0
        and scoring >= 65.0
    ):
        return "lead_creator"

    if (
        rebounding >= 75.0
        and shooting >= 65.0
    ):
        return "stretch_big"

    if (
        defense >= 70.0
        and shooting >= 65.0
    ):
        return "three_and_d"

    if (
        defense >= 70.0
        and rebounding >= 60.0
        and scoring >= 50.0
    ):
        return "two_way_forward"

    if (
        rebounding >= 80.0
        and shooting < 50.0
    ):
        return "interior_big"

    if (
        scoring >= 80.0
        and shooting >= 60.0
    ):
        return "scoring_shooter"

    if (
        playmaking >= 70.0
        and rebounding >= 55.0
    ):
        return "playmaking_forward"

    if defense >= 82.0:
        return "defensive_specialist"

    if shooting >= 82.0:
        return "shooting_specialist"

    if playmaking >= 72.0:
        return "playmaking_connector"

    if rebounding >= 75.0:
        return "rebounding_finisher"

    if scoring >= 75.0:
        return "scoring_specialist"

    return "balanced_rotation"


def age_market_score(
    age: float,
) -> float:
    if not np.isfinite(age):
        return 50.0

    # The score reflects trade-market runway rather than current quality.
    # Current quality is already represented by the projection components.
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


def classify_asset_tier(
    value: float,
) -> str:
    if value >= 93.0:
        return "franchise_cornerstone"

    if value >= 85.0:
        return "core_star"

    if value >= 72.0:
        return "high_end_starter"

    if value >= 52.0:
        return "starter_rotation"

    if value >= 32.0:
        return "rotation_depth"

    return "development_depth"


def build_player_market_layer(
    players: pd.DataFrame,
) -> pd.DataFrame:
    output = add_skill_percentiles(
        players
    )

    output[
        "projected_expected_contribution"
    ] = numeric_series(
        output,
        "projected_expected_contribution",
        fill_value=0.0,
    )

    output[
        "survival_weighted_active_downside_score"
    ] = numeric_series(
        output,
        "survival_weighted_active_downside_score",
        fill_value=0.0,
    )

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

    if (
        "projected_contract_value_score"
        in output.columns
    ):
        output[
            "contract_value_percentile"
        ] = percentile_rank(
            output[
                "projected_contract_value_score"
            ]
        )
    else:
        output[
            "contract_value_percentile"
        ] = 50.0

    if (
        "roster_value_percentile"
        not in output.columns
    ):
        output[
            "roster_value_percentile"
        ] = 50.0

    output[
        "roster_value_percentile"
    ] = numeric_series(
        output,
        "roster_value_percentile",
        fill_value=50.0,
    ).clip(
        lower=0.0,
        upper=100.0,
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
        "market_value_proxy"
    ] = 0.0

    for component, weight in (
        MARKET_VALUE_WEIGHTS.items()
    ):
        output[
            "market_value_proxy"
        ] += (
            weight
            * numeric_series(
                output,
                component,
                fill_value=50.0,
            )
        )

    output[
        "market_value_percentile"
    ] = percentile_rank(
        output[
            "market_value_proxy"
        ]
    )

    output[
        "asset_tier"
    ] = output[
        "market_value_percentile"
    ].map(
        classify_asset_tier
    )

    output[
        "asset_tier_order"
    ] = output[
        "asset_tier"
    ].map(
        ASSET_TIER_ORDER
    ).astype(int)

    output[
        "playstyle_archetype"
    ] = output.apply(
        classify_archetype,
        axis=1,
    )

    output[
        "market_value_scope_note"
    ] = (
        "Relative one-for-one trade-market proxy combining "
        "projected contribution, downside, roster value, "
        "contract value, age runway, and contract control. "
        "It is not a public trade-value ranking."
    )

    return output.sort_values(
        "market_value_percentile",
        ascending=False,
    ).reset_index(drop=True)


def player_lookup(
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


def tier_parity_score(
    first_tier: str,
    second_tier: str,
) -> float:
    first_order = (
        ASSET_TIER_ORDER[
            first_tier
        ]
    )

    second_order = (
        ASSET_TIER_ORDER[
            second_tier
        ]
    )

    distance = abs(
        first_order
        - second_order
    )

    scores = {
        0: 100.0,
        1: 78.0,
        2: 48.0,
        3: 20.0,
        4: 5.0,
        5: 0.0,
    }

    return scores.get(
        distance,
        0.0,
    )


def add_player_to_pair(
    row: dict[str, Any],
    side: str,
    player: dict[str, Any],
) -> None:
    prefix = f"player_{side}_"

    row[
        f"{prefix}age"
    ] = player.get(
        "age",
        np.nan,
    )

    row[
        f"{prefix}market_value_proxy"
    ] = player[
        "market_value_proxy"
    ]

    row[
        f"{prefix}market_value_percentile"
    ] = player[
        "market_value_percentile"
    ]

    row[
        f"{prefix}asset_tier"
    ] = player[
        "asset_tier"
    ]

    row[
        f"{prefix}asset_tier_order"
    ] = player[
        "asset_tier_order"
    ]

    row[
        f"{prefix}playstyle_archetype"
    ] = player[
        "playstyle_archetype"
    ]

    row[
        f"{prefix}contract_control_score"
    ] = player[
        "contract_control_score"
    ]

    row[
        (
            f"{prefix}"
            "contract_years_remaining"
        )
    ] = player.get(
        (
            "contract_years_remaining_"
            "including_2026_27"
        ),
        np.nan,
    )

    row[
        f"{prefix}roster_value_percentile"
    ] = player[
        "roster_value_percentile"
    ]

    row[
        (
            f"{prefix}"
            "expected_contribution_percentile"
        )
    ] = player[
        "expected_contribution_percentile"
    ]

    row[
        (
            f"{prefix}"
            "downside_contribution_percentile"
        )
    ] = player[
        "downside_contribution_percentile"
    ]

    row[
        f"{prefix}age_market_score"
    ] = player[
        "age_market_score"
    ]

    for column in (
        SKILL_PERCENTILE_COLUMNS
    ):
        row[
            f"{prefix}{column}"
        ] = player[column]


def build_realism_scores(
    fit_scores: pd.DataFrame,
    market_players: pd.DataFrame,
) -> pd.DataFrame:
    lookup = player_lookup(
        market_players
    )

    output_rows: list[
        dict[str, Any]
    ] = []

    missing_ids: set[str] = set()

    for pair in fit_scores.to_dict(
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

        add_player_to_pair(
            row=row,
            side="a",
            player=player_a,
        )

        add_player_to_pair(
            row=row,
            side="b",
            player=player_b,
        )

        asset_a = float(
            player_a[
                "market_value_percentile"
            ]
        )

        asset_b = float(
            player_b[
                "market_value_percentile"
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

        asset_gap = abs(
            asset_a
            - asset_b
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

        asset_parity = parity_score(
            asset_a,
            asset_b,
            scale=3.2,
        )

        age_parity = parity_score(
            age_a,
            age_b,
            scale=9.0,
        ) if (
            np.isfinite(age_a)
            and np.isfinite(age_b)
        ) else 65.0

        contract_control_parity = (
            parity_score(
                control_a,
                control_b,
                scale=1.0,
            )
        )

        asset_tier_parity = (
            tier_parity_score(
                player_a[
                    "asset_tier"
                ],
                player_b[
                    "asset_tier"
                ],
            )
        )

        mutual_score = float(
            pair[
                "mutual_trade_score"
            ]
        )

        realism_score = (
            REALISM_SCORE_WEIGHTS[
                "mutual_trade_score"
            ]
            * mutual_score
            + REALISM_SCORE_WEIGHTS[
                "asset_parity_score"
            ]
            * asset_parity
            + REALISM_SCORE_WEIGHTS[
                "age_parity_score"
            ]
            * age_parity
            + REALISM_SCORE_WEIGHTS[
                "contract_control_parity_score"
            ]
            * contract_control_parity
            + REALISM_SCORE_WEIGHTS[
                "asset_tier_parity_score"
            ]
            * asset_tier_parity
        )

        franchise_mismatch = bool(
            (
                player_a[
                    "asset_tier"
                ]
                == "franchise_cornerstone"
                and player_b[
                    "asset_tier"
                ]
                not in {
                    "franchise_cornerstone",
                    "core_star",
                }
            )
            or (
                player_b[
                    "asset_tier"
                ]
                == "franchise_cornerstone"
                and player_a[
                    "asset_tier"
                ]
                not in {
                    "franchise_cornerstone",
                    "core_star",
                }
            )
        )

        young_core_age_mismatch = bool(
            (
                asset_a >= 80.0
                and np.isfinite(
                    age_a
                )
                and age_a <= 25.0
                and np.isfinite(
                    age_b
                )
                and age_b >= 31.0
                and asset_b
                < asset_a + 5.0
            )
            or (
                asset_b >= 80.0
                and np.isfinite(
                    age_b
                )
                and age_b <= 25.0
                and np.isfinite(
                    age_a
                )
                and age_a >= 31.0
                and asset_a
                < asset_b + 5.0
            )
        )

        large_asset_gap = bool(
            asset_gap > 15.0
        )

        contract_control_mismatch = bool(
            contract_control_parity
            < 35.0
            and asset_gap > 7.5
        )

        both_expected_retention_80 = bool(
            float(
                pair[
                    "team_a_expected_retention_ratio"
                ]
            )
            >= 0.80
            and float(
                pair[
                    "team_b_expected_retention_ratio"
                ]
            )
            >= 0.80
        )

        both_downside_retention_65 = bool(
            float(
                pair[
                    "team_a_downside_retention_ratio"
                ]
            )
            >= 0.65
            and float(
                pair[
                    "team_b_downside_retention_ratio"
                ]
            )
            >= 0.65
        )

        realism_eligible = bool(
            pair[
                "recommendation_eligible"
            ]
            and realism_score >= 60.0
            and not franchise_mismatch
            and not young_core_age_mismatch
            and not large_asset_gap
            and not contract_control_mismatch
            and both_expected_retention_80
            and both_downside_retention_65
        )

        if realism_eligible:
            if (
                realism_score >= 72.0
                and float(
                    pair[
                        "minimum_team_trade_fit_score"
                    ]
                )
                >= 56.0
            ):
                realism_tier = (
                    "strong_realistic_review"
                )
            elif realism_score >= 66.0:
                realism_tier = (
                    "detailed_realism_review"
                )
            else:
                realism_tier = (
                    "exploratory_realism_review"
                )
        else:
            realism_tier = (
                "filtered_from_one_for_one_review"
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

        if realism_score < 60.0:
            filter_reasons.append(
                "realism_score_below_60"
            )

        if franchise_mismatch:
            filter_reasons.append(
                "franchise_asset_tier_mismatch"
            )

        if young_core_age_mismatch:
            filter_reasons.append(
                "young_core_age_mismatch"
            )

        if large_asset_gap:
            filter_reasons.append(
                "market_value_gap_above_15"
            )

        if contract_control_mismatch:
            filter_reasons.append(
                "contract_control_and_value_mismatch"
            )

        if not both_expected_retention_80:
            filter_reasons.append(
                "expected_retention_below_80_percent"
            )

        if not both_downside_retention_65:
            filter_reasons.append(
                "downside_retention_below_65_percent"
            )

        row[
            "market_value_gap"
        ] = asset_gap

        row[
            "asset_parity_score"
        ] = asset_parity

        row[
            "age_gap"
        ] = age_gap

        row[
            "age_parity_score"
        ] = age_parity

        row[
            "contract_control_parity_score"
        ] = contract_control_parity

        row[
            "asset_tier_parity_score"
        ] = asset_tier_parity

        row[
            "realism_adjusted_trade_score"
        ] = realism_score

        row[
            "franchise_mismatch_flag"
        ] = franchise_mismatch

        row[
            "young_core_age_mismatch_flag"
        ] = young_core_age_mismatch

        row[
            "large_market_value_gap_flag"
        ] = large_asset_gap

        row[
            "contract_control_mismatch_flag"
        ] = contract_control_mismatch

        row[
            "both_teams_expected_retention_80_plus"
        ] = both_expected_retention_80

        row[
            "both_teams_downside_retention_65_plus"
        ] = both_downside_retention_65

        row[
            "realism_review_eligible"
        ] = realism_eligible

        row[
            "realism_review_tier"
        ] = realism_tier

        row[
            "realism_filter_reasons"
        ] = (
            " | ".join(
                filter_reasons
            )
        )

        row[
            "realism_scope_note"
        ] = (
            "One-for-one market-parity screen. Draft assets, "
            "position labels, team direction, player preferences, "
            "individual restrictions, and front-office intent "
            "are not modeled."
        )

        output_rows.append(
            row
        )

    if missing_ids:
        raise ValueError(
            "Fit-score rows referenced player IDs missing from "
            "the market layer:\n"
            + "\n".join(
                sorted(
                    missing_ids
                )
            )
        )

    return (
        pd.DataFrame(
            output_rows
        )
        .sort_values(
            [
                "realism_review_eligible",
                "realism_adjusted_trade_score",
                "minimum_team_trade_fit_score",
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
    rows: list[
        dict[str, Any]
    ] = []

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
                    "outgoing_asset_tier": (
                        pair[
                            f"player_{side}_asset_tier"
                        ]
                    ),
                    "incoming_asset_tier": (
                        pair[
                            f"player_{other_side}_asset_tier"
                        ]
                    ),
                    "outgoing_archetype": (
                        pair[
                            (
                                f"player_{side}_"
                                "playstyle_archetype"
                            )
                        ]
                    ),
                    "incoming_archetype": (
                        pair[
                            (
                                f"player_{other_side}_"
                                "playstyle_archetype"
                            )
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
                    "realism_adjusted_trade_score": (
                        pair[
                            "realism_adjusted_trade_score"
                        ]
                    ),
                    "realism_review_tier": (
                        pair[
                            "realism_review_tier"
                        ]
                    ),
                    "market_value_gap": (
                        pair[
                            "market_value_gap"
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
                    "salary_method": (
                        pair[
                            (
                                f"team_{side}_"
                                "selected_salary_method"
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
            "realism_adjusted_trade_score"
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


def format_money(
    value: Any,
) -> str:
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
    print("ONE-FOR-ONE TRADE REALISM LAYER")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        fit_scores,
        trade_pool,
        projection_board,
        skills,
    ) = load_inputs()

    player_context = (
        merge_player_context(
            trade_pool=trade_pool,
            projection_board=projection_board,
            skills=skills,
        )
    )

    market_players = (
        build_player_market_layer(
            player_context
        )
    )

    realism_scores = (
        build_realism_scores(
            fit_scores=fit_scores,
            market_players=market_players,
        )
    )

    recommendations = (
        realism_scores.loc[
            realism_scores[
                "realism_review_eligible"
            ]
        ]
        .copy()
        .sort_values(
            [
                "realism_adjusted_trade_score",
                "minimum_team_trade_fit_score",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(drop=True)
    )

    filtered = (
        realism_scores.loc[
            realism_scores[
                "recommendation_eligible"
            ].fillna(False)
            & ~realism_scores[
                "realism_review_eligible"
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
            recommendations
        )
    )

    market_players.to_parquet(
        PLAYER_MARKET_LAYER_PARQUET_PATH,
        index=False,
    )

    market_players.to_csv(
        PLAYER_MARKET_LAYER_CSV_PATH,
        index=False,
    )

    realism_scores.to_parquet(
        ALL_REALISM_SCORES_PARQUET_PATH,
        index=False,
    )

    recommendation_columns = [
        "pair_id",
        "realism_review_tier",
        "realism_adjusted_trade_score",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "market_value_gap",
        "asset_parity_score",
        "age_gap",
        "age_parity_score",
        "contract_control_parity_score",
        "team_a",
        "player_a_name",
        "player_a_salary",
        "player_a_age",
        "player_a_asset_tier",
        "player_a_market_value_percentile",
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
        "player_b_asset_tier",
        "player_b_market_value_percentile",
        "player_b_playstyle_archetype",
        "team_b_trade_fit_score",
        "team_b_critical_need",
        "team_b_expected_delta",
        "team_b_downside_delta",
        "team_b_selected_salary_method",
        "realism_scope_note",
    ]

    recommendations[
        [
            column
            for column
            in recommendation_columns
            if column
            in recommendations.columns
        ]
    ].to_csv(
        REALISTIC_RECOMMENDATIONS_PATH,
        index=False,
    )

    filtered_columns = [
        "pair_id",
        "recommendation_tier",
        "mutual_trade_score",
        "team_a",
        "player_a_name",
        "player_a_asset_tier",
        "player_a_market_value_percentile",
        "team_b",
        "player_b_name",
        "player_b_asset_tier",
        "player_b_market_value_percentile",
        "market_value_gap",
        "realism_adjusted_trade_score",
        "realism_filter_reasons",
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
        TEAM_REALISTIC_TARGETS_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "player_market_layer_rows": len(
            market_players
        ),
        "players_with_age": int(
            market_players[
                "age"
            ].notna().sum()
        ),
        "fit_score_pairs_reviewed": len(
            realism_scores
        ),
        "original_recommendation_eligible_pairs": int(
            realism_scores[
                "recommendation_eligible"
            ]
            .fillna(False)
            .sum()
        ),
        "realism_review_eligible_pairs": len(
            recommendations
        ),
        "strong_realistic_review_pairs": int(
            recommendations[
                "realism_review_tier"
            ].eq(
                "strong_realistic_review"
            ).sum()
        ),
        "detailed_realism_review_pairs": int(
            recommendations[
                "realism_review_tier"
            ].eq(
                "detailed_realism_review"
            ).sum()
        ),
        "exploratory_realism_review_pairs": int(
            recommendations[
                "realism_review_tier"
            ].eq(
                "exploratory_realism_review"
            ).sum()
        ),
        "original_eligible_pairs_filtered_out": len(
            filtered
        ),
        "market_value_weights": (
            MARKET_VALUE_WEIGHTS
        ),
        "realism_score_weights": (
            REALISM_SCORE_WEIGHTS
        ),
        "hard_filters": {
            "minimum_realism_score": 60.0,
            "maximum_market_value_gap": 15.0,
            "minimum_expected_retention": 0.80,
            "minimum_downside_retention": 0.65,
            "franchise_tier_mismatch_blocked": True,
            "young_core_for_older_lesser_asset_blocked": True,
            "large_contract_control_and_value_mismatch_blocked": True,
        },
        "limitations": [
            (
                "Market value is a relative project proxy rather "
                "than observed executive or public consensus value."
            ),
            (
                "Playstyle archetypes are inferred from five "
                "statistical skill dimensions, not official positions."
            ),
            (
                "Draft compensation is absent, so the screen is "
                "intentionally strict for one-for-one asset parity."
            ),
            (
                "Team competitive timelines and player preferences "
                "are not included."
            ),
            (
                "Salary matching remains a preliminary proxy check."
            ),
        ],
        "output_files": {
            "player_market_layer": str(
                PLAYER_MARKET_LAYER_PARQUET_PATH
            ),
            "all_realism_scores": str(
                ALL_REALISM_SCORES_PARQUET_PATH
            ),
            "realistic_recommendations": str(
                REALISTIC_RECOMMENDATIONS_PATH
            ),
            "filtered_audit": str(
                FILTERED_AUDIT_PATH
            ),
            "team_targets": str(
                TEAM_REALISTIC_TARGETS_PATH
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
        f"Player market rows: "
        f"{len(market_players):,}"
    )
    print(
        f"Players with age data: "
        f"{metadata['players_with_age']:,}"
    )
    print(
        "Original recommendation-eligible pairs: "
        f"{metadata['original_recommendation_eligible_pairs']:,}"
    )
    print(
        "Realism-review eligible pairs: "
        f"{metadata['realism_review_eligible_pairs']:,}"
    )
    print(
        "Original eligible pairs filtered out: "
        f"{metadata['original_eligible_pairs_filtered_out']:,}"
    )
    print(
        "Strong realistic reviews: "
        f"{metadata['strong_realistic_review_pairs']:,}"
    )
    print(
        "Detailed realism reviews: "
        f"{metadata['detailed_realism_review_pairs']:,}"
    )
    print(
        "Exploratory realism reviews: "
        f"{metadata['exploratory_realism_review_pairs']:,}"
    )
    print()

    print("TOP 25 PLAYER MARKET-VALUE PROXIES")
    player_display_columns = [
        "player_name",
        "current_team_2026_27",
        "age",
        "trade_salary_2026_27",
        "market_value_percentile",
        "asset_tier",
        "playstyle_archetype",
        "projected_expected_contribution",
        "roster_value_percentile",
    ]

    player_display = (
        market_players.head(
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
        "market_value_percentile",
        "projected_expected_contribution",
        "roster_value_percentile",
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

    print("TOP 30 REALISM-ADJUSTED ONE-FOR-ONE TRADES")
    top = recommendations.head(
        30
    ).copy()

    if top.empty:
        print(
            "No trades passed every strict one-for-one "
            "realism rule."
        )
    else:
        display_columns = [
            "realism_review_tier",
            "realism_adjusted_trade_score",
            "team_a",
            "player_a_name",
            "player_a_age",
            "player_a_asset_tier",
            "team_b",
            "player_b_name",
            "player_b_age",
            "player_b_asset_tier",
            "market_value_gap",
            "minimum_team_trade_fit_score",
        ]

        display = top[
            display_columns
        ].copy()

        for column in [
            "realism_adjusted_trade_score",
            "player_a_age",
            "player_b_age",
            "market_value_gap",
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
    print("TOP ORIGINAL RECOMMENDATIONS FILTERED OUT")
    filtered_display = filtered.head(
        20
    )

    if filtered_display.empty:
        print(
            "No original recommendations were filtered out."
        )
    else:
        display_columns = [
            "mutual_trade_score",
            "team_a",
            "player_a_name",
            "player_a_asset_tier",
            "team_b",
            "player_b_name",
            "player_b_asset_tier",
            "market_value_gap",
            "realism_filter_reasons",
        ]

        print(
            filtered_display[
                display_columns
            ].to_string(
                index=False,
            )
        )

    print()
    print("SAVED FILES")
    print(
        PLAYER_MARKET_LAYER_PARQUET_PATH
    )
    print(
        PLAYER_MARKET_LAYER_CSV_PATH
    )
    print(
        ALL_REALISM_SCORES_PARQUET_PATH
    )
    print(
        REALISTIC_RECOMMENDATIONS_PATH
    )
    print(
        FILTERED_AUDIT_PATH
    )
    print(
        TEAM_REALISTIC_TARGETS_PATH
    )
    print(METADATA_PATH)


if __name__ == "__main__":
    main()