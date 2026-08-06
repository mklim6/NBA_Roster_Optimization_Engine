from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "multi-player-trade-fit-v1-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PASSING_PRECHECKS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "two_for_one_trade_salary_prechecks_passing_2026_27.parquet"
)

PACKAGE_PLAYER_POOL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "multi_player_trade_package_pool_2026_27.parquet"
)

TEAM_NEEDS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "team_roster_needs_2026_27.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

ALL_FIT_SCORES_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_fit_scores_2026_27.parquet"
)

RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_recommendations_2026_27.csv"
)

TEAM_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_multi_player_trade_targets_2026_27.csv"
)

FILTERED_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_fit_filtered_audit_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_fit_metadata_2026_27.json"
)


SKILLS = [
    "scoring",
    "shooting",
    "playmaking",
    "rebounding",
    "defense",
]

PLAYER_REQUIRED_COLUMNS = [
    "player_id",
    "player_name",
    "projected_expected_contribution",
    "survival_weighted_active_downside_score",
    "projected_survival_probability",
    "market_value_percentile_v2",
    "on_court_caliber_score",
    *[
        f"{skill}_percentile"
        for skill in SKILLS
    ],
]

PRECHECK_REQUIRED_COLUMNS = [
    "package_trade_id",
    "team_sending_two",
    "team_sending_one",
    "two_side_player_1_id",
    "two_side_player_2_id",
    "one_side_player_id",
    "two_side_total_salary",
    "one_side_player_salary",
    "two_side_expected_contribution",
    "one_side_expected_contribution",
    "two_side_downside_contribution",
    "one_side_downside_contribution",
    "two_side_market_value_units",
    "one_side_market_value_units",
    "two_side_future_salary_commitment",
    "one_side_future_salary_commitment",
    "salary_similarity_score",
    "expected_contribution_similarity_score",
    "downside_similarity_score",
    "market_value_similarity_score",
    "package_screening_score",
    "both_teams_salary_precheck_pass",
]

COMPONENT_WEIGHTS = {
    "fit_delta_percentile": 0.30,
    "expected_delta_percentile": 0.25,
    "downside_delta_percentile": 0.15,
    "market_value_delta_percentile": 0.15,
    "future_salary_relief_percentile": 0.05,
    "structure_delta_percentile": 0.05,
    "survival_delta_percentile": 0.05,
}

MUTUAL_SCORE_WEIGHTS = {
    "minimum_team_score": 0.50,
    "average_team_score": 0.25,
    "salary_similarity": 0.10,
    "package_screening": 0.10,
    "market_value_similarity": 0.05,
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


def safe_ratio(
    numerator: pd.Series,
    denominator: pd.Series,
) -> pd.Series:
    numerator_values = pd.to_numeric(
        numerator,
        errors="coerce",
    ).fillna(0.0)

    denominator_values = pd.to_numeric(
        denominator,
        errors="coerce",
    ).fillna(0.0)

    result = np.where(
        denominator_values > 0.0,
        numerator_values
        / denominator_values,
        np.where(
            numerator_values >= 0.0,
            1.0,
            0.0,
        ),
    )

    return pd.Series(
        np.clip(
            result,
            0.0,
            2.5,
        ),
        index=numerator.index,
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PASSING_PRECHECKS_PATH,
        PACKAGE_PLAYER_POOL_PATH,
        TEAM_NEEDS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    prechecks = pd.read_parquet(
        PASSING_PRECHECKS_PATH
    )

    players = pd.read_parquet(
        PACKAGE_PLAYER_POOL_PATH
    )

    team_needs = pd.read_csv(
        TEAM_NEEDS_PATH
    )

    require_columns(
        prechecks,
        PRECHECK_REQUIRED_COLUMNS,
        "Passing package prechecks",
    )

    require_columns(
        players,
        PLAYER_REQUIRED_COLUMNS,
        "Package player pool",
    )

    require_columns(
        team_needs,
        [
            "team_abbreviation",
            *[
                f"{skill}_need_score"
                for skill in SKILLS
            ],
        ],
        "Team roster needs",
    )

    return (
        prechecks.copy(),
        players.copy(),
        team_needs.copy(),
    )


def prepare_player_lookup(
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
        duplicates = (
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
            "Package player pool contains duplicate IDs:\n"
            + "\n".join(
                duplicates
            )
        )

    numeric_columns = [
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
        "projected_survival_probability",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "future_salary_commitment_2027_28_plus",
        *[
            f"{skill}_percentile"
            for skill in SKILLS
        ],
    ]

    for column in numeric_columns:
        if column in output.columns:
            output[column] = numeric_series(
                output,
                column,
                fill_value=0.0,
            )

    output[
        "role_weight"
    ] = (
        np.sqrt(
            output[
                "projected_expected_contribution"
            ].clip(
                lower=0.0
            )
            + 10.0
        )
        * (
            0.50
            + 0.50
            * output[
                "projected_survival_probability"
            ].clip(
                lower=0.0,
                upper=1.0,
            )
        )
    )

    return output


def prepare_team_needs(
    team_needs: pd.DataFrame,
) -> pd.DataFrame:
    output = team_needs.copy()

    need_score_columns = [
        f"{skill}_need_score"
        for skill in SKILLS
    ]

    for column in need_score_columns:
        output[column] = numeric_series(
            output,
            column,
            fill_value=50.0,
        ).clip(
            lower=0.0,
            upper=100.0,
        )

    existing_weight_columns = [
        f"{skill}_need_weight"
        for skill in SKILLS
    ]

    if all(
        column in output.columns
        for column in existing_weight_columns
    ):
        weights = output[
            existing_weight_columns
        ].apply(
            pd.to_numeric,
            errors="coerce",
        ).fillna(0.0)
    else:
        weights = (
            output[
                need_score_columns
            ]
            + 15.0
        )

    weight_sums = weights.sum(
        axis=1
    ).replace(
        0.0,
        np.nan,
    )

    normalized = (
        weights.div(
            weight_sums,
            axis=0,
        )
        .fillna(
            1.0 / len(SKILLS)
        )
    )

    for index, skill in enumerate(
        SKILLS
    ):
        output[
            f"{skill}_need_weight_model"
        ] = normalized.iloc[
            :,
            index,
        ]

    return output


def merge_player(
    frame: pd.DataFrame,
    players: pd.DataFrame,
    id_column: str,
    prefix: str,
) -> pd.DataFrame:
    player_columns = [
        "player_merge_key",
        "player_name",
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
        "projected_survival_probability",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "role_weight",
        "future_salary_commitment_2027_28_plus",
        *[
            f"{skill}_percentile"
            for skill in SKILLS
        ],
    ]

    player_columns = [
        column
        for column in player_columns
        if column in players.columns
    ]

    renamed = {
        column: f"{prefix}{column}"
        for column in player_columns
        if column != "player_merge_key"
    }

    lookup = (
        players[
            player_columns
        ]
        .rename(
            columns=renamed
        )
    )

    output = frame.copy()

    output[
        f"{prefix}player_merge_key"
    ] = output[
        id_column
    ].map(
        player_key
    )

    output = output.merge(
        lookup,
        how="left",
        left_on=(
            f"{prefix}player_merge_key"
        ),
        right_on="player_merge_key",
        validate="many_to_one",
    )

    output = output.drop(
        columns=[
            "player_merge_key"
        ]
    )

    return output


def merge_team_need(
    frame: pd.DataFrame,
    team_needs: pd.DataFrame,
    team_column: str,
    prefix: str,
) -> pd.DataFrame:
    need_columns = [
        "team_abbreviation",
        *[
            f"{skill}_need_weight_model"
            for skill in SKILLS
        ],
        *[
            f"top_need_{rank}"
            for rank in range(
                1,
                4,
            )
            if f"top_need_{rank}"
            in team_needs.columns
        ],
    ]

    renamed = {
        column: f"{prefix}{column}"
        for column in need_columns
        if column != "team_abbreviation"
    }

    lookup = team_needs[
        need_columns
    ].rename(
        columns=renamed
    )

    output = frame.merge(
        lookup,
        how="left",
        left_on=team_column,
        right_on="team_abbreviation",
        validate="many_to_one",
    )

    output = output.drop(
        columns=[
            "team_abbreviation"
        ]
    )

    return output


def player_need_fit(
    frame: pd.DataFrame,
    player_prefix: str,
    need_prefix: str,
) -> pd.Series:
    result = pd.Series(
        0.0,
        index=frame.index,
    )

    for skill in SKILLS:
        skill_column = (
            f"{player_prefix}"
            f"{skill}_percentile"
        )

        weight_column = (
            f"{need_prefix}"
            f"{skill}_need_weight_model"
        )

        result += (
            numeric_series(
                frame,
                skill_column,
                fill_value=50.0,
            )
            * numeric_series(
                frame,
                weight_column,
                fill_value=(
                    1.0
                    / len(SKILLS)
                ),
            )
        )

    return result


def enrich_prechecks(
    prechecks: pd.DataFrame,
    players: pd.DataFrame,
    team_needs: pd.DataFrame,
) -> pd.DataFrame:
    output = prechecks.copy()

    output = merge_player(
        output,
        players,
        "two_side_player_1_id",
        "p1_",
    )

    output = merge_player(
        output,
        players,
        "two_side_player_2_id",
        "p2_",
    )

    output = merge_player(
        output,
        players,
        "one_side_player_id",
        "s_",
    )

    output = merge_team_need(
        output,
        team_needs,
        "team_sending_two",
        "two_team_",
    )

    output = merge_team_need(
        output,
        team_needs,
        "team_sending_one",
        "one_team_",
    )

    required_merged_columns = [
        "p1_player_name",
        "p2_player_name",
        "s_player_name",
    ]

    missing_rows = output[
        required_merged_columns
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
            "Some package players did not merge into the "
            "player context table:\n"
            + sample.to_string(
                index=False
            )
        )

    return output


def add_raw_side_metrics(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    p1_fit_two = player_need_fit(
        output,
        "p1_",
        "two_team_",
    )

    p2_fit_two = player_need_fit(
        output,
        "p2_",
        "two_team_",
    )

    single_fit_two = player_need_fit(
        output,
        "s_",
        "two_team_",
    )

    p1_fit_one = player_need_fit(
        output,
        "p1_",
        "one_team_",
    )

    p2_fit_one = player_need_fit(
        output,
        "p2_",
        "one_team_",
    )

    single_fit_one = player_need_fit(
        output,
        "s_",
        "one_team_",
    )

    p1_weight = numeric_series(
        output,
        "p1_role_weight",
        fill_value=1.0,
    )

    p2_weight = numeric_series(
        output,
        "p2_role_weight",
        fill_value=1.0,
    )

    single_weight = numeric_series(
        output,
        "s_role_weight",
        fill_value=1.0,
    )

    package_fit_capital_two = (
        p1_fit_two
        * p1_weight
        + p2_fit_two
        * p2_weight
    )

    single_fit_capital_two = (
        single_fit_two
        * single_weight
    )

    package_fit_capital_one = (
        p1_fit_one
        * p1_weight
        + p2_fit_one
        * p2_weight
    )

    single_fit_capital_one = (
        single_fit_one
        * single_weight
    )

    output[
        "team_two_fit_delta"
    ] = (
        single_fit_capital_two
        - package_fit_capital_two
    )

    output[
        "team_one_fit_delta"
    ] = (
        package_fit_capital_one
        - single_fit_capital_one
    )

    two_expected = numeric_series(
        output,
        "two_side_expected_contribution",
        fill_value=0.0,
    )

    one_expected = numeric_series(
        output,
        "one_side_expected_contribution",
        fill_value=0.0,
    )

    two_downside = numeric_series(
        output,
        "two_side_downside_contribution",
        fill_value=0.0,
    )

    one_downside = numeric_series(
        output,
        "one_side_downside_contribution",
        fill_value=0.0,
    )

    two_market = numeric_series(
        output,
        "two_side_market_value_units",
        fill_value=0.0,
    )

    one_market = numeric_series(
        output,
        "one_side_market_value_units",
        fill_value=0.0,
    )

    two_future = numeric_series(
        output,
        "two_side_future_salary_commitment",
        fill_value=0.0,
    )

    one_future = numeric_series(
        output,
        "one_side_future_salary_commitment",
        fill_value=0.0,
    )

    p1_survival = numeric_series(
        output,
        "p1_projected_survival_probability",
        fill_value=0.0,
    )

    p2_survival = numeric_series(
        output,
        "p2_projected_survival_probability",
        fill_value=0.0,
    )

    single_survival = numeric_series(
        output,
        "s_projected_survival_probability",
        fill_value=0.0,
    )

    package_weight_sum = (
        p1_weight
        + p2_weight
    ).replace(
        0.0,
        np.nan,
    )

    package_survival = (
        (
            p1_survival
            * p1_weight
            + p2_survival
            * p2_weight
        )
        / package_weight_sum
    ).fillna(0.0)

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

    package_best_caliber = np.maximum(
        p1_caliber,
        p2_caliber,
    )

    package_second_caliber = np.minimum(
        p1_caliber,
        p2_caliber,
    )

    output[
        "team_two_expected_delta"
    ] = (
        one_expected
        - two_expected
    )

    output[
        "team_one_expected_delta"
    ] = (
        two_expected
        - one_expected
    )

    output[
        "team_two_downside_delta"
    ] = (
        one_downside
        - two_downside
    )

    output[
        "team_one_downside_delta"
    ] = (
        two_downside
        - one_downside
    )

    output[
        "team_two_market_value_delta"
    ] = (
        one_market
        - two_market
    )

    output[
        "team_one_market_value_delta"
    ] = (
        two_market
        - one_market
    )

    output[
        "team_two_future_salary_relief"
    ] = (
        two_future
        - one_future
    )

    output[
        "team_one_future_salary_relief"
    ] = (
        one_future
        - two_future
    )

    output[
        "team_two_survival_delta"
    ] = (
        single_survival
        - package_survival
    )

    output[
        "team_one_survival_delta"
    ] = (
        package_survival
        - single_survival
    )

    # The team sending two receives a consolidation and roster-flexibility
    # benefit when the incoming player is better than either outgoing player.
    output[
        "team_two_structure_delta"
    ] = (
        single_caliber
        - package_best_caliber
        + 4.0
    )

    # The team receiving two gets a depth benefit only when the second
    # incoming player is substantial enough to justify the extra roster slot.
    output[
        "team_one_structure_delta"
    ] = (
        package_second_caliber
        - 0.35
        * single_caliber
        - 5.0
    )

    output[
        "team_two_expected_retention_ratio"
    ] = safe_ratio(
        one_expected,
        two_expected,
    )

    output[
        "team_one_expected_retention_ratio"
    ] = safe_ratio(
        two_expected,
        one_expected,
    )

    output[
        "team_two_downside_retention_ratio"
    ] = safe_ratio(
        one_downside,
        two_downside,
    )

    output[
        "team_one_downside_retention_ratio"
    ] = safe_ratio(
        two_downside,
        one_downside,
    )

    output[
        "team_two_market_value_retention_ratio"
    ] = safe_ratio(
        one_market,
        two_market,
    )

    output[
        "team_one_market_value_retention_ratio"
    ] = safe_ratio(
        two_market,
        one_market,
    )

    output[
        "team_one_extra_roster_slot_required"
    ] = True

    output[
        "team_two_roster_slot_created"
    ] = True

    return output


def build_long_side_table(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    side_frames = []

    for side, team_column in [
        (
            "two",
            "team_sending_two",
        ),
        (
            "one",
            "team_sending_one",
        ),
    ]:
        side_frame = pd.DataFrame(
            {
                "package_trade_id": (
                    frame[
                        "package_trade_id"
                    ]
                ),
                "side": side,
                "team_abbreviation": (
                    frame[
                        team_column
                    ]
                ),
                "fit_delta": (
                    frame[
                        f"team_{side}_fit_delta"
                    ]
                ),
                "expected_delta": (
                    frame[
                        f"team_{side}_expected_delta"
                    ]
                ),
                "downside_delta": (
                    frame[
                        f"team_{side}_downside_delta"
                    ]
                ),
                "market_value_delta": (
                    frame[
                        (
                            f"team_{side}_"
                            "market_value_delta"
                        )
                    ]
                ),
                "future_salary_relief": (
                    frame[
                        (
                            f"team_{side}_"
                            "future_salary_relief"
                        )
                    ]
                ),
                "structure_delta": (
                    frame[
                        (
                            f"team_{side}_"
                            "structure_delta"
                        )
                    ]
                ),
                "survival_delta": (
                    frame[
                        (
                            f"team_{side}_"
                            "survival_delta"
                        )
                    ]
                ),
                "expected_retention_ratio": (
                    frame[
                        (
                            f"team_{side}_"
                            "expected_retention_ratio"
                        )
                    ]
                ),
                "downside_retention_ratio": (
                    frame[
                        (
                            f"team_{side}_"
                            "downside_retention_ratio"
                        )
                    ]
                ),
                "market_value_retention_ratio": (
                    frame[
                        (
                            f"team_{side}_"
                            "market_value_retention_ratio"
                        )
                    ]
                ),
            }
        )

        side_frames.append(
            side_frame
        )

    return pd.concat(
        side_frames,
        ignore_index=True,
    )


def score_sides(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    long = build_long_side_table(
        frame
    )

    raw_components = [
        "fit_delta",
        "expected_delta",
        "downside_delta",
        "market_value_delta",
        "future_salary_relief",
        "structure_delta",
        "survival_delta",
    ]

    for component in raw_components:
        long[
            f"{component}_percentile"
        ] = percentile_rank(
            long[
                component
            ]
        )

    long[
        "team_package_score_before_penalty"
    ] = 0.0

    for component, weight in (
        COMPONENT_WEIGHTS.items()
    ):
        long[
            "team_package_score_before_penalty"
        ] += (
            weight
            * long[
                component
            ]
        )

    expected_penalty = (
        np.maximum(
            0.0,
            0.82
            - long[
                "expected_retention_ratio"
            ],
        )
        * 100.0
    )

    downside_penalty = (
        np.maximum(
            0.0,
            0.65
            - long[
                "downside_retention_ratio"
            ],
        )
        * 65.0
    )

    market_penalty = (
        np.maximum(
            0.0,
            0.80
            - long[
                "market_value_retention_ratio"
            ],
        )
        * 80.0
    )

    roster_slot_penalty = np.where(
        long["side"].eq(
            "one"
        ),
        3.0,
        0.0,
    )

    long[
        "team_package_penalty"
    ] = (
        expected_penalty
        + downside_penalty
        + market_penalty
        + roster_slot_penalty
    )

    long[
        "team_package_fit_score"
    ] = np.clip(
        long[
            "team_package_score_before_penalty"
        ]
        - long[
            "team_package_penalty"
        ],
        0.0,
        100.0,
    )

    return long


def merge_side_scores(
    frame: pd.DataFrame,
    long: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    columns_to_merge = [
        "package_trade_id",
        "team_package_score_before_penalty",
        "team_package_penalty",
        "team_package_fit_score",
        "fit_delta_percentile",
        "expected_delta_percentile",
        "downside_delta_percentile",
        "market_value_delta_percentile",
        "future_salary_relief_percentile",
        "structure_delta_percentile",
        "survival_delta_percentile",
    ]

    for side in [
        "two",
        "one",
    ]:
        subset = long.loc[
            long[
                "side"
            ].eq(side),
            columns_to_merge,
        ].copy()

        subset = subset.rename(
            columns={
                column: (
                    f"team_{side}_{column}"
                )
                for column
                in columns_to_merge
                if column
                != "package_trade_id"
            }
        )

        output = output.merge(
            subset,
            how="left",
            on="package_trade_id",
            validate="one_to_one",
        )

    return output


def add_mutual_scores(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    minimum_team_score = np.minimum(
        output[
            "team_two_team_package_fit_score"
        ],
        output[
            "team_one_team_package_fit_score"
        ],
    )

    average_team_score = (
        output[
            "team_two_team_package_fit_score"
        ]
        + output[
            "team_one_team_package_fit_score"
        ]
    ) / 2.0

    output[
        "minimum_team_package_fit_score"
    ] = minimum_team_score

    output[
        "average_team_package_fit_score"
    ] = average_team_score

    output[
        "mutual_package_trade_score"
    ] = (
        MUTUAL_SCORE_WEIGHTS[
            "minimum_team_score"
        ]
        * minimum_team_score
        + MUTUAL_SCORE_WEIGHTS[
            "average_team_score"
        ]
        * average_team_score
        + MUTUAL_SCORE_WEIGHTS[
            "salary_similarity"
        ]
        * numeric_series(
            output,
            "salary_similarity_score",
            fill_value=0.0,
        )
        * 100.0
        + MUTUAL_SCORE_WEIGHTS[
            "package_screening"
        ]
        * numeric_series(
            output,
            "package_screening_score",
            fill_value=0.0,
        )
        * 100.0
        + MUTUAL_SCORE_WEIGHTS[
            "market_value_similarity"
        ]
        * numeric_series(
            output,
            "market_value_similarity_score",
            fill_value=0.0,
        )
        * 100.0
    )

    output[
        "both_expected_retention_pass"
    ] = (
        output[
            "team_two_expected_retention_ratio"
        ].ge(0.82)
        & output[
            "team_one_expected_retention_ratio"
        ].ge(0.82)
    )

    output[
        "both_downside_retention_pass"
    ] = (
        output[
            "team_two_downside_retention_ratio"
        ].ge(0.65)
        & output[
            "team_one_downside_retention_ratio"
        ].ge(0.65)
    )

    output[
        "both_market_value_retention_pass"
    ] = (
        output[
            "team_two_market_value_retention_ratio"
        ].ge(0.80)
        & output[
            "team_one_market_value_retention_ratio"
        ].ge(0.80)
    )

    output[
        "package_fit_review_eligible"
    ] = (
        output[
            "both_teams_salary_precheck_pass"
        ].fillna(False)
        & output[
            "minimum_team_package_fit_score"
        ].ge(50.0)
        & output[
            "mutual_package_trade_score"
        ].ge(58.0)
        & output[
            "package_screening_score"
        ].ge(0.55)
        & output[
            "both_expected_retention_pass"
        ]
        & output[
            "both_downside_retention_pass"
        ]
        & output[
            "both_market_value_retention_pass"
        ]
    )

    output[
        "package_review_tier"
    ] = np.select(
        [
            (
                output[
                    "package_fit_review_eligible"
                ]
                & output[
                    "minimum_team_package_fit_score"
                ].ge(60.0)
                & output[
                    "mutual_package_trade_score"
                ].ge(70.0)
            ),
            (
                output[
                    "package_fit_review_eligible"
                ]
                & output[
                    "minimum_team_package_fit_score"
                ].ge(55.0)
                & output[
                    "mutual_package_trade_score"
                ].ge(64.0)
            ),
            output[
                "package_fit_review_eligible"
            ],
        ],
        [
            "strong_package_review",
            "detailed_package_review",
            "exploratory_package_review",
        ],
        default="salary_match_only",
    )

    filter_reasons = []

    for row in output.itertuples(
        index=False
    ):
        reasons = []

        if not bool(
            row.both_expected_retention_pass
        ):
            reasons.append(
                "expected_retention_failed"
            )

        if not bool(
            row.both_downside_retention_pass
        ):
            reasons.append(
                "downside_retention_failed"
            )

        if not bool(
            row.both_market_value_retention_pass
        ):
            reasons.append(
                "market_value_retention_failed"
            )

        if (
            row.minimum_team_package_fit_score
            < 50.0
        ):
            reasons.append(
                "minimum_team_fit_below_50"
            )

        if (
            row.mutual_package_trade_score
            < 58.0
        ):
            reasons.append(
                "mutual_score_below_58"
            )

        if row.package_screening_score < 0.55:
            reasons.append(
                "package_screening_below_0_55"
            )

        filter_reasons.append(
            " | ".join(
                reasons
            )
        )

    output[
        "package_fit_filter_reasons"
    ] = filter_reasons

    output[
        "package_fit_scope_note"
    ] = (
        "Exploratory two-for-one basketball-fit score. "
        "Official roster-slot availability, positions, draft "
        "assets, individual restrictions, and final NBA approval "
        "remain unverified."
    )

    return output.sort_values(
        [
            "package_fit_review_eligible",
            "mutual_package_trade_score",
            "minimum_team_package_fit_score",
        ],
        ascending=[
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
                "package_review_tier": (
                    package[
                        "package_review_tier"
                    ]
                ),
                "expected_contribution_delta": (
                    package[
                        "team_two_expected_delta"
                    ]
                ),
                "downside_contribution_delta": (
                    package[
                        "team_two_downside_delta"
                    ]
                ),
                "market_value_delta": (
                    package[
                        "team_two_market_value_delta"
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
                "package_review_tier": (
                    package[
                        "package_review_tier"
                    ]
                ),
                "expected_contribution_delta": (
                    package[
                        "team_one_expected_delta"
                    ]
                ),
                "downside_contribution_delta": (
                    package[
                        "team_one_downside_delta"
                    ]
                ),
                "market_value_delta": (
                    package[
                        "team_one_market_value_delta"
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
    print("TWO-FOR-ONE TRADE BASKETBALL-FIT ENGINE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        prechecks,
        players,
        team_needs,
    ) = load_inputs()

    players = prepare_player_lookup(
        players
    )

    team_needs = prepare_team_needs(
        team_needs
    )

    print(
        "Salary-compatible packages loaded: "
        f"{len(prechecks):,}"
    )
    print(
        f"Package players: "
        f"{len(players):,}"
    )
    print(
        f"Teams with needs profiles: "
        f"{len(team_needs):,}"
    )
    print()
    print(
        "Merging player context and scoring both "
        "sides of every package..."
    )

    enriched = enrich_prechecks(
        prechecks=prechecks,
        players=players,
        team_needs=team_needs,
    )

    enriched = add_raw_side_metrics(
        enriched
    )

    long_scores = score_sides(
        enriched
    )

    scored = merge_side_scores(
        enriched,
        long_scores,
    )

    scored = add_mutual_scores(
        scored
    )

    recommendations = scored.loc[
        scored[
            "package_fit_review_eligible"
        ]
    ].copy()

    filtered = scored.loc[
        ~scored[
            "package_fit_review_eligible"
        ]
    ].copy()

    team_targets = build_team_targets(
        recommendations
    )

    scored.to_parquet(
        ALL_FIT_SCORES_PATH,
        index=False,
    )

    recommendation_columns = [
        "package_trade_id",
        "package_review_tier",
        "mutual_package_trade_score",
        "minimum_team_package_fit_score",
        "average_team_package_fit_score",
        "team_sending_two",
        "two_side_player_1_name",
        "two_side_player_2_name",
        "two_side_total_salary",
        "team_two_team_package_fit_score",
        "team_two_expected_delta",
        "team_two_downside_delta",
        "team_two_market_value_delta",
        "team_two_expected_retention_ratio",
        "team_two_downside_retention_ratio",
        "team_two_market_value_retention_ratio",
        "team_sending_two_selected_salary_method",
        "team_sending_one",
        "one_side_player_name",
        "one_side_player_salary",
        "team_one_team_package_fit_score",
        "team_one_expected_delta",
        "team_one_downside_delta",
        "team_one_market_value_delta",
        "team_one_expected_retention_ratio",
        "team_one_downside_retention_ratio",
        "team_one_market_value_retention_ratio",
        "team_sending_one_selected_salary_method",
        "salary_similarity_score",
        "market_value_similarity_score",
        "package_screening_score",
        "package_fit_scope_note",
    ]

    recommendations[
        [
            column
            for column
            in recommendation_columns
            if column
            in recommendations.columns
        ]
    ].head(
        10_000
    ).to_csv(
        RECOMMENDATIONS_PATH,
        index=False,
    )

    filtered_columns = [
        "package_trade_id",
        "team_sending_two",
        "two_side_player_1_name",
        "two_side_player_2_name",
        "team_sending_one",
        "one_side_player_name",
        "mutual_package_trade_score",
        "minimum_team_package_fit_score",
        "package_screening_score",
        "package_fit_filter_reasons",
    ]

    filtered[
        [
            column
            for column
            in filtered_columns
            if column
            in filtered.columns
        ]
    ].head(
        25_000
    ).to_csv(
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
        "salary_compatible_packages_loaded": len(
            prechecks
        ),
        "packages_scored": len(
            scored
        ),
        "recommendation_eligible_packages": len(
            recommendations
        ),
        "strong_package_reviews": int(
            recommendations[
                "package_review_tier"
            ].eq(
                "strong_package_review"
            ).sum()
        ),
        "detailed_package_reviews": int(
            recommendations[
                "package_review_tier"
            ].eq(
                "detailed_package_review"
            ).sum()
        ),
        "exploratory_package_reviews": int(
            recommendations[
                "package_review_tier"
            ].eq(
                "exploratory_package_review"
            ).sum()
        ),
        "component_weights": (
            COMPONENT_WEIGHTS
        ),
        "mutual_score_weights": (
            MUTUAL_SCORE_WEIGHTS
        ),
        "eligibility_rules": {
            "minimum_team_package_fit_score": 50.0,
            "minimum_mutual_package_trade_score": 58.0,
            "minimum_package_screening_score": 0.55,
            "minimum_expected_retention_ratio": 0.82,
            "minimum_downside_retention_ratio": 0.65,
            "minimum_market_value_retention_ratio": 0.80,
        },
        "limitations": [
            (
                "This is an exploratory package-fit model, "
                "not a front-office acceptance probability."
            ),
            (
                "Official roster-slot availability is not verified."
            ),
            (
                "Positions and lineup interaction effects are not "
                "yet included."
            ),
            (
                "Draft assets, team direction, individual contract "
                "restrictions, and final NBA approval are absent."
            ),
            (
                "Team salary legality remains based on proxy inputs."
            ),
        ],
        "output_files": {
            "all_fit_scores": str(
                ALL_FIT_SCORES_PATH
            ),
            "recommendations": str(
                RECOMMENDATIONS_PATH
            ),
            "team_targets": str(
                TEAM_TARGETS_PATH
            ),
            "filtered_audit": str(
                FILTERED_AUDIT_PATH
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

    print()
    print("=" * 80)
    print("TWO-FOR-ONE BASKETBALL-FIT SCORES CREATED")
    print("=" * 80)
    print(
        "Salary-compatible packages scored: "
        f"{len(scored):,}"
    )
    print(
        "Recommendation-eligible packages: "
        f"{len(recommendations):,}"
    )
    print(
        "Strong package reviews: "
        f"{metadata['strong_package_reviews']:,}"
    )
    print(
        "Detailed package reviews: "
        f"{metadata['detailed_package_reviews']:,}"
    )
    print(
        "Exploratory package reviews: "
        f"{metadata['exploratory_package_reviews']:,}"
    )
    print()

    print("TOP 30 MULTI-PLAYER PACKAGE REVIEWS")
    if recommendations.empty:
        print(
            "No packages passed every conservative fit rule."
        )
    else:
        display_columns = [
            "package_review_tier",
            "mutual_package_trade_score",
            "team_sending_two",
            "two_side_player_1_name",
            "two_side_player_2_name",
            "two_side_total_salary",
            "team_two_team_package_fit_score",
            "team_sending_one",
            "one_side_player_name",
            "one_side_player_salary",
            "team_one_team_package_fit_score",
            "minimum_team_package_fit_score",
        ]

        display = recommendations.head(
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
            "team_two_team_package_fit_score",
            "team_one_team_package_fit_score",
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
    print(ALL_FIT_SCORES_PATH)
    print(RECOMMENDATIONS_PATH)
    print(TEAM_TARGETS_PATH)
    print(FILTERED_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()