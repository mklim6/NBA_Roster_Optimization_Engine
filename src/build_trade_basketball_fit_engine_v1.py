from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "trade-basketball-fit-v1-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRADE_POOL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "trade_eligible_player_pool_2026_27.parquet"
)

PASSING_SALARY_PRECHECKS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "one_for_one_trade_salary_prechecks_passing_2026_27.parquet"
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

ENRICHED_TRADE_POOL_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "trade_fit_player_pool_2026_27.parquet"
)

ENRICHED_TRADE_POOL_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "trade_fit_player_pool_2026_27.csv"
)

TEAM_NEEDS_PATH = (
    PROCESSED_DIRECTORY
    / "team_roster_needs_2026_27.csv"
)

ALL_FIT_SCORES_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_fit_scores_2026_27.parquet"
)

RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_recommendations_2026_27.csv"
)

TEAM_TARGETS_PATH = (
    OUTPUT_DIRECTORY
    / "team_specific_trade_targets_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "trade_fit_scoring_metadata_2026_27.json"
)


SKILL_COLUMNS = [
    "scoring_score",
    "shooting_score",
    "playmaking_score",
    "rebounding_score",
    "defense_score",
]

SKILL_LABELS = {
    "scoring_score": "Scoring",
    "shooting_score": "Shooting",
    "playmaking_score": "Playmaking",
    "rebounding_score": "Rebounding",
    "defense_score": "Defense",
}

SKILL_PERCENTILE_COLUMNS = {
    column: column.replace(
        "_score",
        "_percentile",
    )
    for column in SKILL_COLUMNS
}

PLAYER_REQUIRED_COLUMNS = [
    "player_id",
    "player_name",
    "current_team_2026_27",
    "trade_salary_2026_27",
    "projected_expected_contribution",
    "projected_survival_probability",
    "projected_active_downside_contribution_80",
    "projected_active_upside_contribution_80",
    "survival_weighted_active_downside_score",
    "optimizer_projection_eligible",
]

PRECHECK_REQUIRED_COLUMNS = [
    "pair_id",
    "team_a",
    "team_b",
    "player_a_id",
    "player_a_name",
    "player_b_id",
    "player_b_name",
    "both_teams_salary_precheck_pass",
    "both_main_pool_eligible",
    "salary_similarity_score",
    "projection_similarity_score",
    "screening_similarity_score",
]

FIT_COMPONENT_WEIGHTS = {
    "fit_delta_percentile": 0.30,
    "expected_delta_percentile": 0.25,
    "downside_delta_percentile": 0.15,
    "contract_value_delta_percentile": 0.10,
    "future_salary_relief_percentile": 0.10,
    "survival_delta_percentile": 0.05,
    "incoming_need_fit_percentile": 0.05,
}

MUTUAL_SCORE_WEIGHTS = {
    "minimum_team_score": 0.50,
    "average_team_score": 0.25,
    "salary_similarity": 0.10,
    "projection_similarity": 0.10,
    "downside_similarity": 0.05,
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


def bounded_ratio(
    numerator: float,
    denominator: float,
) -> float:
    if not np.isfinite(numerator):
        return 0.0

    if not np.isfinite(denominator):
        return 0.0

    if denominator <= 0:
        return 1.0 if numerator >= 0 else 0.0

    return float(
        np.clip(
            numerator / denominator,
            0.0,
            2.0,
        )
    )


def safe_similarity(
    first: float,
    second: float,
) -> float:
    denominator = max(
        abs(first),
        abs(second),
        1.0,
    )

    return float(
        np.clip(
            1.0
            - abs(first - second)
            / denominator,
            0.0,
            1.0,
        )
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        TRADE_POOL_PATH,
        PASSING_SALARY_PRECHECKS_PATH,
        SKILL_PROFILES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    trade_pool = pd.read_parquet(
        TRADE_POOL_PATH
    )

    prechecks = pd.read_parquet(
        PASSING_SALARY_PRECHECKS_PATH
    )

    skills = pd.read_parquet(
        SKILL_PROFILES_PATH
    )

    require_columns(
        trade_pool,
        PLAYER_REQUIRED_COLUMNS,
        "Trade pool",
    )

    require_columns(
        prechecks,
        PRECHECK_REQUIRED_COLUMNS,
        "Passing salary prechecks",
    )

    require_columns(
        skills,
        [
            "player_id",
            "player_name",
            *SKILL_COLUMNS,
        ],
        "Player skill profiles",
    )

    return (
        trade_pool.copy(),
        prechecks.copy(),
        skills.copy(),
    )


def enrich_trade_pool(
    trade_pool: pd.DataFrame,
    skills: pd.DataFrame,
) -> pd.DataFrame:
    trade_pool = trade_pool.copy()
    skills = skills.copy()

    trade_pool[
        "player_merge_key"
    ] = trade_pool[
        "player_id"
    ].map(
        player_key
    )

    skills[
        "player_merge_key"
    ] = skills[
        "player_id"
    ].map(
        player_key
    )

    if skills[
        "player_merge_key"
    ].duplicated().any():
        duplicate_names = (
            skills.loc[
                skills[
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
            "Skill profiles contain duplicate player IDs:\n"
            + "\n".join(
                duplicate_names
            )
        )

    profile_columns = [
        "player_merge_key",
        *SKILL_COLUMNS,
    ]

    for optional_column in [
        "roster_value_score",
        "roster_value_percentile",
        "raw_overall_score",
        "reliability_weight",
        "reliability_adjusted_score",
        "primary_skill",
        "secondary_skill",
        "confidence_tier",
        "value_tier",
    ]:
        if (
            optional_column
            in skills.columns
        ):
            profile_columns.append(
                optional_column
            )

    overlapping_columns = [
        column
        for column in profile_columns
        if (
            column
            in trade_pool.columns
            and column
            != "player_merge_key"
        )
    ]

    if overlapping_columns:
        trade_pool = (
            trade_pool.drop(
                columns=overlapping_columns
            )
        )

    enriched = trade_pool.merge(
        skills[
            profile_columns
        ],
        how="left",
        on="player_merge_key",
        validate="one_to_one",
    )

    missing_skill_rows = enriched[
        SKILL_COLUMNS
    ].isna().all(axis=1)

    if missing_skill_rows.any():
        missing_names = (
            enriched.loc[
                missing_skill_rows,
                "player_name",
            ]
            .astype(str)
            .tolist()
        )

        raise ValueError(
            "Trade-pool players are missing all skill scores:\n"
            + "\n".join(
                missing_names
            )
        )

    for column in SKILL_COLUMNS:
        values = numeric_series(
            enriched,
            column,
        )

        median_value = float(
            values.median()
        )

        enriched[column] = (
            values.fillna(
                median_value
            )
        )

        percentile_column = (
            SKILL_PERCENTILE_COLUMNS[
                column
            ]
        )

        enriched[
            percentile_column
        ] = (
            enriched[column]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

    expected = numeric_series(
        enriched,
        "projected_expected_contribution",
        fill_value=0.0,
    ).clip(
        lower=0.0,
    )

    survival = numeric_series(
        enriched,
        "projected_survival_probability",
        fill_value=0.0,
    ).clip(
        lower=0.0,
        upper=1.0,
    )

    # This weight gives larger projected rotation pieces more influence
    # without allowing one star to completely define the team profile.
    enriched[
        "team_profile_weight"
    ] = (
        np.sqrt(
            expected + 10.0
        )
        * (
            0.50
            + 0.50
            * survival
        )
    )

    enriched[
        "player_profile_complete_flag"
    ] = (
        enriched[
            list(
                SKILL_PERCENTILE_COLUMNS.values()
            )
        ]
        .notna()
        .all(axis=1)
    )

    return enriched.sort_values(
        [
            "current_team_2026_27",
            "projected_expected_contribution",
        ],
        ascending=[
            True,
            False,
        ],
    ).reset_index(drop=True)


def roster_supply_vector(
    roster: pd.DataFrame,
) -> dict[str, float]:
    if roster.empty:
        return {
            column: 0.0
            for column
            in SKILL_PERCENTILE_COLUMNS.values()
        }

    weights = numeric_series(
        roster,
        "team_profile_weight",
        fill_value=0.0,
    ).clip(
        lower=0.001,
    ).to_numpy(dtype=float)

    supply: dict[str, float] = {}

    for raw_column, percentile_column in (
        SKILL_PERCENTILE_COLUMNS.items()
    ):
        values = numeric_series(
            roster,
            percentile_column,
            fill_value=50.0,
        ).to_numpy(dtype=float)

        weighted_average = float(
            np.average(
                values,
                weights=weights,
            )
        )

        top_count = min(
            3,
            len(values),
        )

        top_values = np.sort(
            values
        )[-top_count:]

        top_average = float(
            np.mean(
                top_values
            )
        )

        depth_count = int(
            (values >= 70.0).sum()
        )

        depth_score = float(
            min(
                100.0,
                depth_count
                / 3.0
                * 100.0,
            )
        )

        composite_supply = (
            0.65
            * weighted_average
            + 0.25
            * top_average
            + 0.10
            * depth_score
        )

        supply[
            percentile_column
        ] = float(
            composite_supply
        )

    return supply


def build_team_needs(
    enriched_pool: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    dict[str, pd.DataFrame],
]:
    rosters = {
        team: group.copy()
        for (
            team,
            group,
        ) in enriched_pool.groupby(
            "current_team_2026_27",
            sort=True,
        )
    }

    rows: list[dict[str, Any]] = []

    for team, roster in rosters.items():
        supply = roster_supply_vector(
            roster
        )

        row: dict[str, Any] = {
            "team_abbreviation": team,
            "trade_pool_players": len(
                roster
            ),
            "main_projection_pool_players": int(
                roster[
                    "optimizer_projection_eligible"
                ]
                .fillna(False)
                .astype(bool)
                .sum()
            ),
            "team_expected_contribution": float(
                numeric_series(
                    roster,
                    "projected_expected_contribution",
                    fill_value=0.0,
                ).sum()
            ),
        }

        for percentile_column, value in (
            supply.items()
        ):
            skill_name = (
                percentile_column.replace(
                    "_percentile",
                    "",
                )
            )

            row[
                f"{skill_name}_team_supply"
            ] = value

        rows.append(row)

    needs = pd.DataFrame(
        rows
    )

    for raw_column, percentile_column in (
        SKILL_PERCENTILE_COLUMNS.items()
    ):
        skill_name = (
            percentile_column.replace(
                "_percentile",
                "",
            )
        )

        supply_column = (
            f"{skill_name}_team_supply"
        )

        need_column = (
            f"{skill_name}_need_score"
        )

        needs[
            need_column
        ] = (
            100.0
            - (
                needs[
                    supply_column
                ]
                .rank(
                    method="average",
                    pct=True,
                )
                * 100.0
            )
        )

    need_score_columns = [
        (
            percentile_column.replace(
                "_percentile",
                ""
            )
            + "_need_score"
        )
        for percentile_column
        in SKILL_PERCENTILE_COLUMNS.values()
    ]

    need_values = needs[
        need_score_columns
    ].to_numpy(dtype=float)

    # Every category keeps a small floor so that teams still receive
    # credit for adding a strong skill even when it is not their top need.
    need_weights = (
        need_values + 15.0
    )

    need_weights = (
        need_weights
        / need_weights.sum(
            axis=1,
            keepdims=True,
        )
    )

    for index, need_column in enumerate(
        need_score_columns
    ):
        skill_name = (
            need_column.replace(
                "_need_score",
                "",
            )
        )

        needs[
            f"{skill_name}_need_weight"
        ] = need_weights[
            :,
            index,
        ]

    top_need_labels: list[list[str]] = []

    for _, row in needs.iterrows():
        ordered = sorted(
            [
                (
                    float(
                        row[
                            (
                                percentile_column.replace(
                                    "_percentile",
                                    ""
                                )
                                + "_need_score"
                            )
                        ]
                    ),
                    SKILL_LABELS[
                        raw_column
                    ],
                )
                for (
                    raw_column,
                    percentile_column,
                ) in (
                    SKILL_PERCENTILE_COLUMNS.items()
                )
            ],
            reverse=True,
        )

        top_need_labels.append(
            [
                label
                for _, label
                in ordered
            ]
        )

    for rank in range(3):
        needs[
            f"top_need_{rank + 1}"
        ] = [
            labels[rank]
            for labels
            in top_need_labels
        ]

    return (
        needs.sort_values(
            "team_abbreviation"
        ).reset_index(drop=True),
        rosters,
    )


def build_player_lookup(
    enriched_pool: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    return {
        player_key(
            row[
                "player_id"
            ]
        ): row
        for row in enriched_pool.to_dict(
            orient="records"
        )
    }


def build_team_need_lookup(
    team_needs: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    return (
        team_needs.set_index(
            "team_abbreviation"
        )
        .to_dict(
            orient="index"
        )
    )


def skill_percentile_vector(
    player: dict[str, Any],
) -> np.ndarray:
    return np.array(
        [
            float(
                player[
                    percentile_column
                ]
            )
            for percentile_column
            in (
                SKILL_PERCENTILE_COLUMNS.values()
            )
        ],
        dtype=float,
    )


def team_need_weight_vector(
    team_need: dict[str, Any],
) -> np.ndarray:
    values = []

    for percentile_column in (
        SKILL_PERCENTILE_COLUMNS.values()
    ):
        skill_name = (
            percentile_column.replace(
                "_percentile",
                "",
            )
        )

        values.append(
            float(
                team_need[
                    f"{skill_name}_need_weight"
                ]
            )
        )

    weights = np.array(
        values,
        dtype=float,
    )

    total = float(
        weights.sum()
    )

    if total <= 0:
        return np.full(
            len(weights),
            1.0 / len(weights),
        )

    return weights / total


def roster_after_trade(
    roster: pd.DataFrame,
    outgoing_player_id: str,
    incoming_player: dict[str, Any],
) -> pd.DataFrame:
    remaining = roster.loc[
        roster[
            "player_id"
        ].map(
            player_key
        )
        .ne(
            outgoing_player_id
        )
    ].copy()

    incoming_frame = pd.DataFrame(
        [
            {
                column: incoming_player.get(
                    column,
                    pd.NA,
                )
                for column
                in roster.columns
            }
        ]
    )

    return pd.concat(
        [
            remaining,
            incoming_frame,
        ],
        ignore_index=True,
    )


def score_team_side_raw(
    team: str,
    outgoing_player: dict[str, Any],
    incoming_player: dict[str, Any],
    roster: pd.DataFrame,
    team_need: dict[str, Any],
) -> dict[str, Any]:
    pre_supply = roster_supply_vector(
        roster
    )

    post_roster = roster_after_trade(
        roster=roster,
        outgoing_player_id=player_key(
            outgoing_player[
                "player_id"
            ]
        ),
        incoming_player=incoming_player,
    )

    post_supply = roster_supply_vector(
        post_roster
    )

    need_weights = (
        team_need_weight_vector(
            team_need
        )
    )

    pre_vector = np.array(
        [
            pre_supply[
                percentile_column
            ]
            for percentile_column
            in (
                SKILL_PERCENTILE_COLUMNS.values()
            )
        ],
        dtype=float,
    )

    post_vector = np.array(
        [
            post_supply[
                percentile_column
            ]
            for percentile_column
            in (
                SKILL_PERCENTILE_COLUMNS.values()
            )
        ],
        dtype=float,
    )

    incoming_vector = (
        skill_percentile_vector(
            incoming_player
        )
    )

    outgoing_vector = (
        skill_percentile_vector(
            outgoing_player
        )
    )

    skill_delta_vector = (
        post_vector
        - pre_vector
    )

    fit_delta = float(
        np.dot(
            need_weights,
            skill_delta_vector,
        )
    )

    incoming_need_fit = float(
        np.dot(
            need_weights,
            incoming_vector,
        )
    )

    outgoing_need_fit = float(
        np.dot(
            need_weights,
            outgoing_vector,
        )
    )

    critical_need_index = int(
        np.argmax(
            need_weights
        )
    )

    raw_skill_columns = list(
        SKILL_COLUMNS
    )

    critical_need_column = (
        raw_skill_columns[
            critical_need_index
        ]
    )

    critical_need_label = (
        SKILL_LABELS[
            critical_need_column
        ]
    )

    expected_out = float(
        outgoing_player[
            "projected_expected_contribution"
        ]
    )

    expected_in = float(
        incoming_player[
            "projected_expected_contribution"
        ]
    )

    downside_out = float(
        outgoing_player[
            "survival_weighted_active_downside_score"
        ]
    )

    downside_in = float(
        incoming_player[
            "survival_weighted_active_downside_score"
        ]
    )

    survival_out = float(
        outgoing_player[
            "projected_survival_probability"
        ]
    )

    survival_in = float(
        incoming_player[
            "projected_survival_probability"
        ]
    )

    contract_value_out = float(
        outgoing_player.get(
            "projected_contract_value_score",
            0.0,
        )
        if pd.notna(
            outgoing_player.get(
                "projected_contract_value_score",
                np.nan,
            )
        )
        else 0.0
    )

    contract_value_in = float(
        incoming_player.get(
            "projected_contract_value_score",
            0.0,
        )
        if pd.notna(
            incoming_player.get(
                "projected_contract_value_score",
                np.nan,
            )
        )
        else 0.0
    )

    future_out = float(
        outgoing_player.get(
            "future_salary_commitment_2027_28_plus",
            0.0,
        )
        if pd.notna(
            outgoing_player.get(
                "future_salary_commitment_2027_28_plus",
                np.nan,
            )
        )
        else 0.0
    )

    future_in = float(
        incoming_player.get(
            "future_salary_commitment_2027_28_plus",
            0.0,
        )
        if pd.notna(
            incoming_player.get(
                "future_salary_commitment_2027_28_plus",
                np.nan,
            )
        )
        else 0.0
    )

    expected_delta = (
        expected_in - expected_out
    )

    downside_delta = (
        downside_in - downside_out
    )

    survival_delta = (
        survival_in - survival_out
    )

    contract_value_delta = (
        contract_value_in
        - contract_value_out
    )

    future_salary_relief = (
        future_out - future_in
    )

    expected_retention = (
        bounded_ratio(
            expected_in,
            expected_out,
        )
    )

    downside_retention = (
        bounded_ratio(
            downside_in,
            downside_out,
        )
    )

    skill_delta_by_label = {
        SKILL_LABELS[
            raw_column
        ]: float(
            skill_delta_vector[
                index
            ]
        )
        for index, raw_column
        in enumerate(
            SKILL_COLUMNS
        )
    }

    strongest_gain = max(
        skill_delta_by_label.items(),
        key=lambda item: item[1],
    )

    largest_loss = min(
        skill_delta_by_label.items(),
        key=lambda item: item[1],
    )

    result: dict[str, Any] = {
        "team": team,
        "fit_delta": fit_delta,
        "incoming_need_fit": (
            incoming_need_fit
        ),
        "outgoing_need_fit": (
            outgoing_need_fit
        ),
        "need_fit_change": (
            incoming_need_fit
            - outgoing_need_fit
        ),
        "critical_need": (
            critical_need_label
        ),
        "critical_need_supply_delta": (
            float(
                skill_delta_vector[
                    critical_need_index
                ]
            )
        ),
        "strongest_skill_gain": (
            strongest_gain[0]
        ),
        "strongest_skill_gain_value": (
            strongest_gain[1]
        ),
        "largest_skill_loss": (
            largest_loss[0]
        ),
        "largest_skill_loss_value": (
            largest_loss[1]
        ),
        "expected_delta": (
            expected_delta
        ),
        "downside_delta": (
            downside_delta
        ),
        "survival_delta": (
            survival_delta
        ),
        "contract_value_delta": (
            contract_value_delta
        ),
        "future_salary_relief": (
            future_salary_relief
        ),
        "expected_retention_ratio": (
            expected_retention
        ),
        "downside_retention_ratio": (
            downside_retention
        ),
    }

    for raw_column, percentile_column in (
        SKILL_PERCENTILE_COLUMNS.items()
    ):
        skill_name = (
            percentile_column.replace(
                "_percentile",
                "",
            )
        )

        result[
            f"{skill_name}_supply_before"
        ] = pre_supply[
            percentile_column
        ]

        result[
            f"{skill_name}_supply_after"
        ] = post_supply[
            percentile_column
        ]

        result[
            f"{skill_name}_supply_delta"
        ] = (
            post_supply[
                percentile_column
            ]
            - pre_supply[
                percentile_column
            ]
        )

    return result


def prefix_dictionary(
    values: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    return {
        f"{prefix}{key}": value
        for key, value
        in values.items()
    }


def build_raw_trade_scores(
    prechecks: pd.DataFrame,
    enriched_pool: pd.DataFrame,
    team_needs: pd.DataFrame,
    rosters: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    player_lookup = (
        build_player_lookup(
            enriched_pool
        )
    )

    team_need_lookup = (
        build_team_need_lookup(
            team_needs
        )
    )

    rows: list[dict[str, Any]] = []

    missing_player_keys: set[str] = set()

    for pair in prechecks.to_dict(
        orient="records"
    ):
        player_a_key = player_key(
            pair[
                "player_a_id"
            ]
        )

        player_b_key = player_key(
            pair[
                "player_b_id"
            ]
        )

        player_a = player_lookup.get(
            player_a_key
        )

        player_b = player_lookup.get(
            player_b_key
        )

        if player_a is None:
            missing_player_keys.add(
                player_a_key
            )
            continue

        if player_b is None:
            missing_player_keys.add(
                player_b_key
            )
            continue

        team_a = str(
            pair["team_a"]
        )

        team_b = str(
            pair["team_b"]
        )

        side_a = score_team_side_raw(
            team=team_a,
            outgoing_player=player_a,
            incoming_player=player_b,
            roster=rosters[team_a],
            team_need=(
                team_need_lookup[
                    team_a
                ]
            ),
        )

        side_b = score_team_side_raw(
            team=team_b,
            outgoing_player=player_b,
            incoming_player=player_a,
            roster=rosters[team_b],
            team_need=(
                team_need_lookup[
                    team_b
                ]
            ),
        )

        row = dict(pair)

        row.update(
            prefix_dictionary(
                side_a,
                "team_a_",
            )
        )

        row.update(
            prefix_dictionary(
                side_b,
                "team_b_",
            )
        )

        row[
            "downside_similarity_score"
        ] = safe_similarity(
            float(
                player_a[
                    "survival_weighted_active_downside_score"
                ]
            ),
            float(
                player_b[
                    "survival_weighted_active_downside_score"
                ]
            ),
        )

        rows.append(row)

    if missing_player_keys:
        raise ValueError(
            "Passing prechecks reference missing trade-pool "
            "player IDs:\n"
            + "\n".join(
                sorted(
                    missing_player_keys
                )
            )
        )

    return pd.DataFrame(
        rows
    )


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


def add_team_scores(
    raw_scores: pd.DataFrame,
) -> pd.DataFrame:
    scores = raw_scores.copy()

    long_rows: list[pd.DataFrame] = []

    for side in [
        "a",
        "b",
    ]:
        side_frame = pd.DataFrame(
            {
                "pair_index": (
                    scores.index
                ),
                "side": side,
                "fit_delta": (
                    scores[
                        f"team_{side}_fit_delta"
                    ]
                ),
                "expected_delta": (
                    scores[
                        f"team_{side}_expected_delta"
                    ]
                ),
                "downside_delta": (
                    scores[
                        f"team_{side}_downside_delta"
                    ]
                ),
                "contract_value_delta": (
                    scores[
                        (
                            f"team_{side}_"
                            "contract_value_delta"
                        )
                    ]
                ),
                "future_salary_relief": (
                    scores[
                        (
                            f"team_{side}_"
                            "future_salary_relief"
                        )
                    ]
                ),
                "survival_delta": (
                    scores[
                        f"team_{side}_survival_delta"
                    ]
                ),
                "incoming_need_fit": (
                    scores[
                        (
                            f"team_{side}_"
                            "incoming_need_fit"
                        )
                    ]
                ),
            }
        )

        long_rows.append(
            side_frame
        )

    long = pd.concat(
        long_rows,
        ignore_index=True,
    )

    component_columns = [
        "fit_delta",
        "expected_delta",
        "downside_delta",
        "contract_value_delta",
        "future_salary_relief",
        "survival_delta",
        "incoming_need_fit",
    ]

    for column in component_columns:
        long[
            f"{column}_percentile"
        ] = percentile_rank(
            long[column]
        )

    long[
        "team_fit_score_before_penalty"
    ] = 0.0

    for percentile_column, weight in (
        FIT_COMPONENT_WEIGHTS.items()
    ):
        long[
            "team_fit_score_before_penalty"
        ] += (
            weight
            * long[
                percentile_column
            ]
        )

    score_lookup = {
        (
            int(row["pair_index"]),
            str(row["side"]),
        ): row
        for row in long.to_dict(
            orient="records"
        )
    }

    for side in [
        "a",
        "b",
    ]:
        before_penalty = []
        final_score = []
        penalty_values = []

        for index, row in scores.iterrows():
            component_row = score_lookup[
                (
                    int(index),
                    side,
                )
            ]

            base_score = float(
                component_row[
                    "team_fit_score_before_penalty"
                ]
            )

            expected_retention = float(
                row[
                    (
                        f"team_{side}_"
                        "expected_retention_ratio"
                    )
                ]
            )

            downside_retention = float(
                row[
                    (
                        f"team_{side}_"
                        "downside_retention_ratio"
                    )
                ]
            )

            expected_penalty = max(
                0.0,
                0.80
                - expected_retention,
            ) * 80.0

            downside_penalty = max(
                0.0,
                0.70
                - downside_retention,
            ) * 45.0

            penalty = (
                expected_penalty
                + downside_penalty
            )

            before_penalty.append(
                base_score
            )

            penalty_values.append(
                penalty
            )

            final_score.append(
                float(
                    np.clip(
                        base_score
                        - penalty,
                        0.0,
                        100.0,
                    )
                )
            )

            for component_column in (
                FIT_COMPONENT_WEIGHTS
            ):
                scores.loc[
                    index,
                    (
                        f"team_{side}_"
                        f"{component_column}"
                    ),
                ] = component_row[
                    component_column
                ]

        scores[
            (
                f"team_{side}_"
                "fit_score_before_penalty"
            )
        ] = before_penalty

        scores[
            f"team_{side}_value_loss_penalty"
        ] = penalty_values

        scores[
            f"team_{side}_trade_fit_score"
        ] = final_score

    minimum_score = np.minimum(
        scores[
            "team_a_trade_fit_score"
        ],
        scores[
            "team_b_trade_fit_score"
        ],
    )

    average_score = (
        scores[
            "team_a_trade_fit_score"
        ]
        + scores[
            "team_b_trade_fit_score"
        ]
    ) / 2.0

    scores[
        "minimum_team_trade_fit_score"
    ] = minimum_score

    scores[
        "average_team_trade_fit_score"
    ] = average_score

    scores[
        "mutual_trade_score"
    ] = (
        MUTUAL_SCORE_WEIGHTS[
            "minimum_team_score"
        ]
        * minimum_score
        + MUTUAL_SCORE_WEIGHTS[
            "average_team_score"
        ]
        * average_score
        + MUTUAL_SCORE_WEIGHTS[
            "salary_similarity"
        ]
        * (
            scores[
                "salary_similarity_score"
            ]
            * 100.0
        )
        + MUTUAL_SCORE_WEIGHTS[
            "projection_similarity"
        ]
        * (
            scores[
                "projection_similarity_score"
            ]
            * 100.0
        )
        + MUTUAL_SCORE_WEIGHTS[
            "downside_similarity"
        ]
        * (
            scores[
                "downside_similarity_score"
            ]
            * 100.0
        )
    )

    scores[
        "both_teams_expected_retention_75_plus"
    ] = (
        scores[
            "team_a_expected_retention_ratio"
        ].ge(0.75)
        & scores[
            "team_b_expected_retention_ratio"
        ].ge(0.75)
    )

    scores[
        "both_teams_downside_retention_60_plus"
    ] = (
        scores[
            "team_a_downside_retention_ratio"
        ].ge(0.60)
        & scores[
            "team_b_downside_retention_ratio"
        ].ge(0.60)
    )

    scores[
        "recommendation_eligible"
    ] = (
        scores[
            "both_teams_salary_precheck_pass"
        ].fillna(False)
        & scores[
            "both_main_pool_eligible"
        ].fillna(False)
        & scores[
            "minimum_team_trade_fit_score"
        ].ge(45.0)
        & scores[
            "mutual_trade_score"
        ].ge(55.0)
        & scores[
            "both_teams_expected_retention_75_plus"
        ]
        & scores[
            "both_teams_downside_retention_60_plus"
        ]
    )

    scores[
        "recommendation_tier"
    ] = np.select(
        [
            (
                scores[
                    "recommendation_eligible"
                ]
                & scores[
                    "minimum_team_trade_fit_score"
                ].ge(60.0)
                & scores[
                    "mutual_trade_score"
                ].ge(68.0)
            ),
            (
                scores[
                    "recommendation_eligible"
                ]
                & scores[
                    "minimum_team_trade_fit_score"
                ].ge(52.0)
                & scores[
                    "mutual_trade_score"
                ].ge(60.0)
            ),
            scores[
                "recommendation_eligible"
            ],
        ],
        [
            "strong_two_team_fit",
            "worth_detailed_review",
            "exploratory_fit",
        ],
        default="salary_match_only",
    )

    scores[
        "recommendation_scope_note"
    ] = (
        "Exploratory one-for-one basketball-fit score. "
        "It does not include draft assets, positions, official "
        "trade approval, individual restrictions, or team intent."
    )

    return scores.sort_values(
        [
            "recommendation_eligible",
            "mutual_trade_score",
            "minimum_team_trade_fit_score",
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

    eligible = recommendations.loc[
        recommendations[
            "recommendation_eligible"
        ]
    ].copy()

    for pair in eligible.to_dict(
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
                    "trade_partner": (
                        pair[
                            f"team_{other_side}"
                        ]
                    ),
                    "outgoing_salary": (
                        pair[
                            f"player_{side}_salary"
                        ]
                    ),
                    "incoming_salary": (
                        pair[
                            f"player_{other_side}_salary"
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
                    "mutual_trade_score": (
                        pair[
                            "mutual_trade_score"
                        ]
                    ),
                    "recommendation_tier": (
                        pair[
                            "recommendation_tier"
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
                    "critical_need_supply_delta": (
                        pair[
                            (
                                f"team_{side}_"
                                "critical_need_supply_delta"
                            )
                        ]
                    ),
                    "strongest_skill_gain": (
                        pair[
                            (
                                f"team_{side}_"
                                "strongest_skill_gain"
                            )
                        ]
                    ),
                    "strongest_skill_gain_value": (
                        pair[
                            (
                                f"team_{side}_"
                                "strongest_skill_gain_value"
                            )
                        ]
                    ),
                    "largest_skill_loss": (
                        pair[
                            (
                                f"team_{side}_"
                                "largest_skill_loss"
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
                    "contract_value_delta": (
                        pair[
                            (
                                f"team_{side}_"
                                "contract_value_delta"
                            )
                        ]
                    ),
                    "future_salary_relief": (
                        pair[
                            (
                                f"team_{side}_"
                                "future_salary_relief"
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

    if not rows:
        return pd.DataFrame()

    targets = pd.DataFrame(
        rows
    )

    targets[
        "team_target_rank"
    ] = (
        targets.groupby(
            "team_abbreviation"
        )[
            "team_trade_fit_score"
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
    print("ONE-FOR-ONE TRADE BASKETBALL-FIT ENGINE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        trade_pool,
        prechecks,
        skills,
    ) = load_inputs()

    enriched_pool = enrich_trade_pool(
        trade_pool=trade_pool,
        skills=skills,
    )

    (
        team_needs,
        rosters,
    ) = build_team_needs(
        enriched_pool
    )

    print(
        f"Trade-pool players: "
        f"{len(enriched_pool):,}"
    )
    print(
        f"Passing salary pairs: "
        f"{len(prechecks):,}"
    )
    print(
        f"Teams profiled: "
        f"{len(team_needs):,}"
    )
    print(
        "Skill dimensions: "
        + ", ".join(
            SKILL_LABELS.values()
        )
    )
    print()
    print(
        "Scoring basketball fit for both teams "
        "in every passing one-for-one pair..."
    )

    raw_scores = build_raw_trade_scores(
        prechecks=prechecks,
        enriched_pool=enriched_pool,
        team_needs=team_needs,
        rosters=rosters,
    )

    scored = add_team_scores(
        raw_scores
    )

    recommendations = scored.loc[
        scored[
            "recommendation_eligible"
        ]
    ].copy()

    team_targets = build_team_targets(
        recommendations
    )

    enriched_pool.to_parquet(
        ENRICHED_TRADE_POOL_PARQUET_PATH,
        index=False,
    )

    enriched_pool.to_csv(
        ENRICHED_TRADE_POOL_CSV_PATH,
        index=False,
    )

    team_needs.to_csv(
        TEAM_NEEDS_PATH,
        index=False,
    )

    scored.to_parquet(
        ALL_FIT_SCORES_PARQUET_PATH,
        index=False,
    )

    recommendation_columns = [
        "pair_id",
        "recommendation_tier",
        "mutual_trade_score",
        "minimum_team_trade_fit_score",
        "average_team_trade_fit_score",
        "team_a",
        "player_a_name",
        "player_a_salary",
        "team_a_trade_fit_score",
        "team_a_critical_need",
        "team_a_critical_need_supply_delta",
        "team_a_strongest_skill_gain",
        "team_a_strongest_skill_gain_value",
        "team_a_expected_delta",
        "team_a_downside_delta",
        "team_a_contract_value_delta",
        "team_a_future_salary_relief",
        "team_a_selected_salary_method",
        "team_b",
        "player_b_name",
        "player_b_salary",
        "team_b_trade_fit_score",
        "team_b_critical_need",
        "team_b_critical_need_supply_delta",
        "team_b_strongest_skill_gain",
        "team_b_strongest_skill_gain_value",
        "team_b_expected_delta",
        "team_b_downside_delta",
        "team_b_contract_value_delta",
        "team_b_future_salary_relief",
        "team_b_selected_salary_method",
        "salary_similarity_score",
        "projection_similarity_score",
        "downside_similarity_score",
        "recommendation_scope_note",
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
        RECOMMENDATIONS_PATH,
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
        "trade_pool_players": len(
            enriched_pool
        ),
        "teams_profiled": len(
            team_needs
        ),
        "passing_salary_pairs_scored": len(
            scored
        ),
        "recommendation_eligible_pairs": len(
            recommendations
        ),
        "strong_two_team_fit_pairs": int(
            recommendations[
                "recommendation_tier"
            ].eq(
                "strong_two_team_fit"
            ).sum()
        ),
        "worth_detailed_review_pairs": int(
            recommendations[
                "recommendation_tier"
            ].eq(
                "worth_detailed_review"
            ).sum()
        ),
        "exploratory_fit_pairs": int(
            recommendations[
                "recommendation_tier"
            ].eq(
                "exploratory_fit"
            ).sum()
        ),
        "skill_columns": (
            SKILL_COLUMNS
        ),
        "skill_labels": (
            SKILL_LABELS
        ),
        "fit_component_weights": (
            FIT_COMPONENT_WEIGHTS
        ),
        "mutual_score_weights": (
            MUTUAL_SCORE_WEIGHTS
        ),
        "eligibility_rules": {
            "salary_precheck": True,
            "both_main_projection_pool": True,
            "minimum_team_fit_score": 45.0,
            "minimum_mutual_trade_score": 55.0,
            "minimum_expected_retention_ratio": 0.75,
            "minimum_downside_retention_ratio": 0.60,
        },
        "methodology": [
            (
                "Player skill scores are converted to "
                "trade-pool percentiles."
            ),
            (
                "Team skill supply combines weighted roster "
                "average, top-three skill quality, and depth."
            ),
            (
                "Team needs are the inverse league ranking "
                "of each team's skill supply."
            ),
            (
                "Each trade is simulated by removing the "
                "outgoing player and adding the incoming player."
            ),
            (
                "Team fit scores combine skill improvement, "
                "expected contribution, downside contribution, "
                "contract value, future salary relief, survival, "
                "and incoming need fit."
            ),
            (
                "Large expected or downside value losses receive "
                "an explicit penalty."
            ),
        ],
        "limitations": [
            (
                "This is an exploratory ranking, not a model "
                "of front-office acceptance probability."
            ),
            (
                "Positions and lineup-level interaction effects "
                "are not included in v1."
            ),
            (
                "Draft picks, exceptions, roster slots, and "
                "multi-player packages are not included."
            ),
            (
                "Salary checks remain proxy prechecks rather "
                "than final NBA legality determinations."
            ),
            (
                "No-trade clauses, consent rights, and signing "
                "or acquisition timing restrictions remain "
                "unverified."
            ),
        ],
        "output_files": {
            "enriched_trade_pool": str(
                ENRICHED_TRADE_POOL_PARQUET_PATH
            ),
            "team_needs": str(
                TEAM_NEEDS_PATH
            ),
            "all_fit_scores": str(
                ALL_FIT_SCORES_PARQUET_PATH
            ),
            "recommendations": str(
                RECOMMENDATIONS_PATH
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

    print()
    print("=" * 80)
    print("TRADE BASKETBALL-FIT SCORES CREATED")
    print("=" * 80)
    print(
        "Salary-compatible pairs scored: "
        f"{len(scored):,}"
    )
    print(
        "Recommendation-eligible pairs: "
        f"{len(recommendations):,}"
    )
    print(
        "Strong two-team fits: "
        f"{metadata['strong_two_team_fit_pairs']:,}"
    )
    print(
        "Worth detailed review: "
        f"{metadata['worth_detailed_review_pairs']:,}"
    )
    print(
        "Exploratory fits: "
        f"{metadata['exploratory_fit_pairs']:,}"
    )
    print()

    print("TEAM NEEDS")
    need_display = team_needs[
        [
            "team_abbreviation",
            "trade_pool_players",
            "top_need_1",
            "top_need_2",
            "top_need_3",
        ]
    ].copy()

    print(
        need_display.to_string(
            index=False,
        )
    )
    print()

    print("TOP 30 MUTUALLY PLAUSIBLE ONE-FOR-ONE TRADES")
    top = recommendations.head(
        30
    ).copy()

    display_columns = [
        "recommendation_tier",
        "mutual_trade_score",
        "team_a",
        "player_a_name",
        "player_a_salary",
        "team_a_trade_fit_score",
        "team_a_critical_need",
        "team_a_expected_delta",
        "team_b",
        "player_b_name",
        "player_b_salary",
        "team_b_trade_fit_score",
        "team_b_critical_need",
        "team_b_expected_delta",
    ]

    if top.empty:
        print(
            "No pairs met every conservative recommendation rule."
        )
    else:
        display = top[
            display_columns
        ].copy()

        for column in [
            "player_a_salary",
            "player_b_salary",
        ]:
            display[column] = (
                display[column]
                .map(
                    format_money
                )
            )

        numeric_display_columns = [
            "mutual_trade_score",
            "team_a_trade_fit_score",
            "team_a_expected_delta",
            "team_b_trade_fit_score",
            "team_b_expected_delta",
        ]

        for column in numeric_display_columns:
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
        ENRICHED_TRADE_POOL_PARQUET_PATH
    )
    print(
        ENRICHED_TRADE_POOL_CSV_PATH
    )
    print(TEAM_NEEDS_PATH)
    print(ALL_FIT_SCORES_PARQUET_PATH)
    print(RECOMMENDATIONS_PATH)
    print(TEAM_TARGETS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()