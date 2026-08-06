from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "trade-salary-precheck-v1-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FINANCIAL_LAYER_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_financial_layer_2026_27_v2.parquet"
)

TEAM_FINANCIAL_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "player_financial_layer_team_summary_2026_27_v2.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

TRADE_POOL_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "trade_eligible_player_pool_2026_27.parquet"
)

TRADE_POOL_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "trade_eligible_player_pool_2026_27.csv"
)

TEAM_PROFILES_PATH = (
    PROCESSED_DIRECTORY
    / "team_trade_salary_profiles_2026_27.csv"
)

ALL_PRECHECKS_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_salary_prechecks_2026_27.parquet"
)

PASSING_PRECHECKS_PARQUET_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_salary_prechecks_passing_2026_27.parquet"
)

PASSING_PRECHECKS_CSV_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_salary_prechecks_passing_2026_27.csv"
)

TEAM_METHOD_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "trade_salary_precheck_team_method_summary_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "trade_salary_precheck_metadata_2026_27.json"
)


SALARY_CAP_2026_27 = 164_961_000.0
LUXURY_TAX_2026_27 = 200_428_000.0
FIRST_APRON_2026_27 = 209_015_000.0
SECOND_APRON_2026_27 = 221_686_000.0

SALARY_CAP_2023_24 = 136_021_000.0

BASE_TPE_ALLOWANCE = 250_000.0

EXPANDED_TPE_SCALED_ADDEND_2026_27 = (
    7_500_000.0
    * SALARY_CAP_2026_27
    / SALARY_CAP_2023_24
)

PLAYER_REQUIRED_COLUMNS = [
    "player_id",
    "player_name",
    "current_team_2026_27",
    "trade_salary_2026_27",
    "under_contract_2026_27",
    "main_pool_eligible",
    "projected_expected_contribution",
    "projected_survival_probability",
    "projected_active_downside_contribution_80",
    "projected_active_upside_contribution_80",
    "survival_weighted_active_downside_score",
]

TEAM_REQUIRED_COLUMNS = [
    "team_abbreviation",
    "selected_trade_salary_proxy",
    "listed_salary_obligation_proxy",
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


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not FINANCIAL_LAYER_PATH.exists():
        raise FileNotFoundError(
            "The v2 financial layer was not found at:\n"
            f"{FINANCIAL_LAYER_PATH}"
        )

    if not TEAM_FINANCIAL_SUMMARY_PATH.exists():
        raise FileNotFoundError(
            "The v2 team financial summary was not found at:\n"
            f"{TEAM_FINANCIAL_SUMMARY_PATH}"
        )

    financial = pd.read_parquet(
        FINANCIAL_LAYER_PATH
    )

    teams = pd.read_csv(
        TEAM_FINANCIAL_SUMMARY_PATH
    )

    require_columns(
        financial,
        PLAYER_REQUIRED_COLUMNS,
        "Financial layer",
    )

    require_columns(
        teams,
        TEAM_REQUIRED_COLUMNS,
        "Team financial summary",
    )

    return (
        financial.copy(),
        teams.copy(),
    )


def build_trade_pool(
    financial: pd.DataFrame,
) -> pd.DataFrame:
    salary = pd.to_numeric(
        financial[
            "trade_salary_2026_27"
        ],
        errors="coerce",
    )

    under_contract = financial[
        "under_contract_2026_27"
    ].fillna(False).astype(bool)

    valid_team = financial[
        "current_team_2026_27"
    ].notna()

    valid_player_id = financial[
        "player_id"
    ].notna()

    pool = financial.loc[
        under_contract
        & valid_team
        & valid_player_id
        & salary.gt(0)
    ].copy()

    if pool.empty:
        raise ValueError(
            "No trade-eligible player rows were found."
        )

    if pool["player_id"].duplicated().any():
        duplicate_names = (
            pool.loc[
                pool["player_id"].duplicated(
                    keep=False
                ),
                "player_name",
            ]
            .astype(str)
            .tolist()
        )

        raise ValueError(
            "Trade pool contains duplicate player IDs:\n"
            + "\n".join(
                duplicate_names
            )
        )

    numeric_columns = [
        "trade_salary_2026_27",
        "projected_expected_contribution",
        "projected_survival_probability",
        "projected_active_downside_contribution_80",
        "projected_active_upside_contribution_80",
        "survival_weighted_active_downside_score",
        "projected_contract_value_score",
        "downside_contract_value_score",
        "contract_years_remaining_including_2026_27",
        "guaranteed_remaining",
        "future_salary_commitment_2027_28_plus",
    ]

    for column in numeric_columns:
        if column in pool.columns:
            pool[column] = pd.to_numeric(
                pool[column],
                errors="coerce",
            )

    pool[
        "trade_pool_eligible"
    ] = True

    pool[
        "optimizer_projection_eligible"
    ] = pool[
        "main_pool_eligible"
    ].fillna(False).astype(bool)

    pool[
        "salary_data_verified_for_player"
    ] = True

    pool[
        "contract_restrictions_verified"
    ] = False

    pool[
        "no_trade_clause_verified"
    ] = False

    pool[
        "recently_signed_or_acquired_restriction_verified"
    ] = False

    pool[
        "trade_pool_scope_note"
    ] = (
        "Player has a matched 2026-27 contract salary and "
        "a 2025-26-based projection. No-trade clauses, "
        "recently-signed restrictions, consent rights, and "
        "other individual restrictions are not yet verified."
    )

    preferred_columns = [
        "player_id",
        "player_name",
        "current_team_2026_27",
        "performance_team_2025_26",
        "trade_salary_2026_27",
        "salary_2027_28",
        "salary_2028_29",
        "salary_2029_30",
        "salary_2030_31",
        "salary_2031_32",
        "contract_years_remaining_including_2026_27",
        "guaranteed_remaining",
        "future_salary_commitment_2027_28_plus",
        "projected_expected_contribution",
        "projected_survival_probability",
        "projected_active_downside_contribution_80",
        "projected_active_upside_contribution_80",
        "survival_weighted_active_downside_score",
        "projected_contract_value_score",
        "downside_contract_value_score",
        "primary_skill",
        "secondary_skill",
        "main_pool_eligible",
        "optimizer_projection_eligible",
        "contract_match_status",
        "offseason_team_changed_flag",
        "trade_pool_eligible",
        "salary_data_verified_for_player",
        "contract_restrictions_verified",
        "no_trade_clause_verified",
        "recently_signed_or_acquired_restriction_verified",
        "trade_pool_scope_note",
    ]

    pool = pool[
        [
            column
            for column in preferred_columns
            if column in pool.columns
        ]
    ].copy()

    return pool.sort_values(
        [
            "current_team_2026_27",
            "trade_salary_2026_27",
            "player_name",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)


def classify_proxy_salary(
    salary: float,
) -> str:
    if salary > SECOND_APRON_2026_27:
        return "above_second_apron_proxy"

    if salary > FIRST_APRON_2026_27:
        return "between_aprons_proxy"

    if salary > LUXURY_TAX_2026_27:
        return "tax_to_first_apron_proxy"

    if salary > SALARY_CAP_2026_27:
        return "over_cap_below_tax_proxy"

    return "below_cap_proxy"


def build_team_profiles(
    teams: pd.DataFrame,
    trade_pool: pd.DataFrame,
) -> pd.DataFrame:
    teams = teams.copy()

    for column in [
        "selected_trade_salary_proxy",
        "listed_salary_obligation_proxy",
    ]:
        teams[column] = pd.to_numeric(
            teams[column],
            errors="coerce",
        ).fillna(0.0)

    roster_summary = (
        trade_pool.groupby(
            "current_team_2026_27",
            as_index=False,
        )
        .agg(
            trade_pool_players=(
                "player_id",
                "size",
            ),
            trade_pool_salary=(
                "trade_salary_2026_27",
                "sum",
            ),
            main_projection_pool_players=(
                "optimizer_projection_eligible",
                "sum",
            ),
        )
        .rename(
            columns={
                "current_team_2026_27": (
                    "team_abbreviation"
                )
            }
        )
    )

    profiles = teams.merge(
        roster_summary,
        how="left",
        on="team_abbreviation",
        validate="one_to_one",
    )

    for column in [
        "trade_pool_players",
        "trade_pool_salary",
        "main_projection_pool_players",
    ]:
        profiles[column] = pd.to_numeric(
            profiles[column],
            errors="coerce",
        ).fillna(0)

    profiles[
        "apron_team_salary_proxy_2026_27"
    ] = profiles[
        "listed_salary_obligation_proxy"
    ]

    profiles[
        "salary_cap_room_proxy"
    ] = (
        SALARY_CAP_2026_27
        - profiles[
            "apron_team_salary_proxy_2026_27"
        ]
    )

    profiles[
        "distance_to_first_apron_proxy"
    ] = (
        FIRST_APRON_2026_27
        - profiles[
            "apron_team_salary_proxy_2026_27"
        ]
    )

    profiles[
        "distance_to_second_apron_proxy"
    ] = (
        SECOND_APRON_2026_27
        - profiles[
            "apron_team_salary_proxy_2026_27"
        ]
    )

    profiles[
        "salary_proxy_tier"
    ] = profiles[
        "apron_team_salary_proxy_2026_27"
    ].map(
        classify_proxy_salary
    )

    profiles[
        "team_salary_source_quality"
    ] = "proxy_only_not_official_apron_team_salary"

    profiles[
        "official_team_salary_verified"
    ] = False

    profiles[
        "official_apron_status_verified"
    ] = False

    profiles[
        "salary_precheck_scope_note"
    ] = (
        "Uses Basketball-Reference listed salary obligations "
        "as a proxy. Final NBA legality requires official "
        "Team Salary, Apron Team Salary, transaction history, "
        "and individual contract restrictions."
    )

    return profiles.sort_values(
        "team_abbreviation"
    ).reset_index(drop=True)


def expanded_tpe_limit(
    outgoing_salary: float,
    allowance: float,
) -> float:
    doubled_limit = (
        2.0 * outgoing_salary
        + allowance
    )

    addend_limit = (
        outgoing_salary
        + EXPANDED_TPE_SCALED_ADDEND_2026_27
    )

    branch_y = min(
        doubled_limit,
        addend_limit,
    )

    branch_z = (
        1.25 * outgoing_salary
        + allowance
    )

    return max(
        branch_y,
        branch_z,
    )


def evaluate_team_salary_precheck(
    team_salary_proxy: float,
    outgoing_salary: float,
    incoming_salary: float,
    outgoing_player_count: int = 1,
) -> dict[str, Any]:
    post_trade_salary_proxy = (
        team_salary_proxy
        - outgoing_salary
        + incoming_salary
    )

    allowance = (
        0.0
        if post_trade_salary_proxy
        > FIRST_APRON_2026_27
        else BASE_TPE_ALLOWANCE
    )

    room_limit = (
        max(
            0.0,
            SALARY_CAP_2026_27
            - team_salary_proxy
            + outgoing_salary,
        )
        + BASE_TPE_ALLOWANCE
    )

    room_method_pass = bool(
        team_salary_proxy
        < SALARY_CAP_2026_27
        and incoming_salary
        <= room_limit + 1e-6
    )

    standard_limit = (
        outgoing_salary
        + allowance
    )

    standard_method_pass = bool(
        outgoing_player_count == 1
        and incoming_salary
        <= standard_limit + 1e-6
    )

    aggregated_standard_limit = (
        outgoing_salary
        + allowance
    )

    aggregated_standard_method_pass = bool(
        outgoing_player_count >= 2
        and incoming_salary
        <= aggregated_standard_limit + 1e-6
        and post_trade_salary_proxy
        <= SECOND_APRON_2026_27 + 1e-6
    )

    expanded_limit = expanded_tpe_limit(
        outgoing_salary=outgoing_salary,
        allowance=allowance,
    )

    expanded_method_pass = bool(
        incoming_salary
        <= expanded_limit + 1e-6
        and post_trade_salary_proxy
        <= FIRST_APRON_2026_27 + 1e-6
    )

    methods = []

    if room_method_pass:
        methods.append(
            "room_under_cap_plus_250k"
        )

    if standard_method_pass:
        methods.append(
            "standard_tpe"
        )

    if aggregated_standard_method_pass:
        methods.append(
            "aggregated_standard_tpe"
        )

    if expanded_method_pass:
        methods.append(
            "expanded_tpe_first_apron_hard_cap"
        )

    precheck_pass = bool(methods)

    method_priority = [
        "room_under_cap_plus_250k",
        "standard_tpe",
        "expanded_tpe_first_apron_hard_cap",
        "aggregated_standard_tpe",
    ]

    selected_method = next(
        (
            method
            for method in method_priority
            if method in methods
        ),
        "no_salary_method_passed",
    )

    maximum_incoming_by_methods = []

    if team_salary_proxy < SALARY_CAP_2026_27:
        maximum_incoming_by_methods.append(
            (
                "room_under_cap_plus_250k",
                room_limit,
            )
        )

    if outgoing_player_count == 1:
        maximum_incoming_by_methods.append(
            (
                "standard_tpe",
                standard_limit,
            )
        )

    if outgoing_player_count >= 2:
        aggregate_hard_cap_limit = (
            outgoing_salary
            + SECOND_APRON_2026_27
            - team_salary_proxy
        )

        maximum_incoming_by_methods.append(
            (
                "aggregated_standard_tpe",
                max(
                    0.0,
                    min(
                        aggregated_standard_limit,
                        aggregate_hard_cap_limit,
                    ),
                ),
            )
        )

    expanded_hard_cap_limit = (
        outgoing_salary
        + FIRST_APRON_2026_27
        - team_salary_proxy
    )

    maximum_incoming_by_methods.append(
        (
            "expanded_tpe_first_apron_hard_cap",
            max(
                0.0,
                min(
                    expanded_limit,
                    expanded_hard_cap_limit,
                ),
            ),
        )
    )

    max_method_name, max_incoming = max(
        maximum_incoming_by_methods,
        key=lambda item: item[1],
    )

    return {
        "salary_precheck_pass": (
            precheck_pass
        ),
        "salary_precheck_methods": (
            " | ".join(methods)
            if methods
            else ""
        ),
        "selected_salary_method": (
            selected_method
        ),
        "post_trade_salary_proxy": (
            post_trade_salary_proxy
        ),
        "post_trade_salary_proxy_tier": (
            classify_proxy_salary(
                post_trade_salary_proxy
            )
        ),
        "tpe_allowance_used": allowance,
        "room_method_pass": (
            room_method_pass
        ),
        "standard_method_pass": (
            standard_method_pass
        ),
        "aggregated_standard_method_pass": (
            aggregated_standard_method_pass
        ),
        "expanded_method_pass": (
            expanded_method_pass
        ),
        "room_limit": room_limit,
        "standard_limit": standard_limit,
        "aggregated_standard_limit": (
            aggregated_standard_limit
        ),
        "expanded_limit_before_hard_cap": (
            expanded_limit
        ),
        "maximum_incoming_salary_precheck": (
            max_incoming
        ),
        "maximum_incoming_method": (
            max_method_name
        ),
        "salary_precheck_confidence": (
            "proxy_only_requires_official_verification"
        ),
    }


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
        max(
            0.0,
            1.0
            - abs(first - second)
            / denominator,
        )
    )


def optional_value(
    row: pd.Series,
    column: str,
) -> Any:
    if column not in row.index:
        return pd.NA

    return row[column]


def build_pair_row(
    player_a: pd.Series,
    player_b: pd.Series,
    team_profile_lookup: dict[str, dict[str, Any]],
    pair_number: int,
) -> dict[str, Any]:
    team_a = str(
        player_a[
            "current_team_2026_27"
        ]
    )

    team_b = str(
        player_b[
            "current_team_2026_27"
        ]
    )

    salary_a = float(
        player_a[
            "trade_salary_2026_27"
        ]
    )

    salary_b = float(
        player_b[
            "trade_salary_2026_27"
        ]
    )

    expected_a = float(
        player_a[
            "projected_expected_contribution"
        ]
    )

    expected_b = float(
        player_b[
            "projected_expected_contribution"
        ]
    )

    downside_a = float(
        player_a[
            "survival_weighted_active_downside_score"
        ]
    )

    downside_b = float(
        player_b[
            "survival_weighted_active_downside_score"
        ]
    )

    profile_a = team_profile_lookup[
        team_a
    ]

    profile_b = team_profile_lookup[
        team_b
    ]

    check_a = (
        evaluate_team_salary_precheck(
            team_salary_proxy=float(
                profile_a[
                    "apron_team_salary_proxy_2026_27"
                ]
            ),
            outgoing_salary=salary_a,
            incoming_salary=salary_b,
            outgoing_player_count=1,
        )
    )

    check_b = (
        evaluate_team_salary_precheck(
            team_salary_proxy=float(
                profile_b[
                    "apron_team_salary_proxy_2026_27"
                ]
            ),
            outgoing_salary=salary_b,
            incoming_salary=salary_a,
            outgoing_player_count=1,
        )
    )

    both_pass = bool(
        check_a[
            "salary_precheck_pass"
        ]
        and check_b[
            "salary_precheck_pass"
        ]
    )

    salary_similarity = safe_similarity(
        salary_a,
        salary_b,
    )

    projection_similarity = (
        safe_similarity(
            expected_a,
            expected_b,
        )
    )

    downside_similarity = (
        safe_similarity(
            downside_a,
            downside_b,
        )
    )

    screening_similarity_score = (
        0.55 * salary_similarity
        + 0.30 * projection_similarity
        + 0.15 * downside_similarity
    )

    pair_id = (
        f"1v1_{pair_number:07d}_"
        f"{player_a['player_id']}_"
        f"{player_b['player_id']}"
    )

    return {
        "pair_id": pair_id,
        "team_a": team_a,
        "team_b": team_b,
        "player_a_id": (
            player_a["player_id"]
        ),
        "player_a_name": (
            player_a["player_name"]
        ),
        "player_a_salary": salary_a,
        "player_a_expected_contribution": (
            expected_a
        ),
        "player_a_survival_probability": (
            player_a[
                "projected_survival_probability"
            ]
        ),
        "player_a_survival_weighted_downside": (
            downside_a
        ),
        "player_a_primary_skill": (
            optional_value(
                player_a,
                "primary_skill",
            )
        ),
        "player_a_secondary_skill": (
            optional_value(
                player_a,
                "secondary_skill",
            )
        ),
        "player_a_main_pool_eligible": (
            bool(
                player_a[
                    "optimizer_projection_eligible"
                ]
            )
        ),
        "player_b_id": (
            player_b["player_id"]
        ),
        "player_b_name": (
            player_b["player_name"]
        ),
        "player_b_salary": salary_b,
        "player_b_expected_contribution": (
            expected_b
        ),
        "player_b_survival_probability": (
            player_b[
                "projected_survival_probability"
            ]
        ),
        "player_b_survival_weighted_downside": (
            downside_b
        ),
        "player_b_primary_skill": (
            optional_value(
                player_b,
                "primary_skill",
            )
        ),
        "player_b_secondary_skill": (
            optional_value(
                player_b,
                "secondary_skill",
            )
        ),
        "player_b_main_pool_eligible": (
            bool(
                player_b[
                    "optimizer_projection_eligible"
                ]
            )
        ),
        "both_main_pool_eligible": (
            bool(
                player_a[
                    "optimizer_projection_eligible"
                ]
                and player_b[
                    "optimizer_projection_eligible"
                ]
            )
        ),
        "team_a_salary_precheck_pass": (
            check_a[
                "salary_precheck_pass"
            ]
        ),
        "team_a_selected_salary_method": (
            check_a[
                "selected_salary_method"
            ]
        ),
        "team_a_salary_precheck_methods": (
            check_a[
                "salary_precheck_methods"
            ]
        ),
        "team_a_post_trade_salary_proxy": (
            check_a[
                "post_trade_salary_proxy"
            ]
        ),
        "team_a_post_trade_salary_proxy_tier": (
            check_a[
                "post_trade_salary_proxy_tier"
            ]
        ),
        "team_a_maximum_incoming_salary_precheck": (
            check_a[
                "maximum_incoming_salary_precheck"
            ]
        ),
        "team_b_salary_precheck_pass": (
            check_b[
                "salary_precheck_pass"
            ]
        ),
        "team_b_selected_salary_method": (
            check_b[
                "selected_salary_method"
            ]
        ),
        "team_b_salary_precheck_methods": (
            check_b[
                "salary_precheck_methods"
            ]
        ),
        "team_b_post_trade_salary_proxy": (
            check_b[
                "post_trade_salary_proxy"
            ]
        ),
        "team_b_post_trade_salary_proxy_tier": (
            check_b[
                "post_trade_salary_proxy_tier"
            ]
        ),
        "team_b_maximum_incoming_salary_precheck": (
            check_b[
                "maximum_incoming_salary_precheck"
            ]
        ),
        "both_teams_salary_precheck_pass": (
            both_pass
        ),
        "salary_difference_absolute": (
            abs(
                salary_a
                - salary_b
            )
        ),
        "salary_similarity_score": (
            salary_similarity
        ),
        "expected_contribution_difference_absolute": (
            abs(
                expected_a
                - expected_b
            )
        ),
        "projection_similarity_score": (
            projection_similarity
        ),
        "downside_similarity_score": (
            downside_similarity
        ),
        "screening_similarity_score": (
            screening_similarity_score
        ),
        "team_a_expected_contribution_delta": (
            expected_b
            - expected_a
        ),
        "team_b_expected_contribution_delta": (
            expected_a
            - expected_b
        ),
        "salary_precheck_confidence": (
            "proxy_only_requires_official_verification"
        ),
        "individual_contract_restrictions_verified": (
            False
        ),
        "final_trade_legality_verified": (
            False
        ),
    }


def build_one_for_one_prechecks(
    trade_pool: pd.DataFrame,
    team_profiles: pd.DataFrame,
) -> pd.DataFrame:
    team_profile_lookup = (
        team_profiles.set_index(
            "team_abbreviation"
        )
        .to_dict(
            orient="index"
        )
    )

    missing_profile_teams = sorted(
        set(
            trade_pool[
                "current_team_2026_27"
            ]
        )
        - set(
            team_profile_lookup
        )
    )

    if missing_profile_teams:
        raise ValueError(
            "Missing team salary profiles for:\n"
            + "\n".join(
                missing_profile_teams
            )
        )

    records = trade_pool.to_dict(
        orient="records"
    )

    pair_rows: list[dict[str, Any]] = []

    pair_number = 0

    for first, second in combinations(
        records,
        2,
    ):
        if (
            first[
                "current_team_2026_27"
            ]
            == second[
                "current_team_2026_27"
            ]
        ):
            continue

        pair_number += 1

        pair_rows.append(
            build_pair_row(
                player_a=pd.Series(first),
                player_b=pd.Series(second),
                team_profile_lookup=(
                    team_profile_lookup
                ),
                pair_number=pair_number,
            )
        )

    if not pair_rows:
        raise ValueError(
            "No cross-team one-for-one pairings "
            "were generated."
        )

    prechecks = pd.DataFrame(
        pair_rows
    )

    return prechecks.sort_values(
        [
            "both_teams_salary_precheck_pass",
            "both_main_pool_eligible",
            "screening_similarity_score",
            "salary_similarity_score",
        ],
        ascending=[
            False,
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)


def build_team_method_summary(
    passing: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for side in [
        "a",
        "b",
    ]:
        subset = passing[
            [
                f"team_{side}",
                (
                    f"team_{side}_"
                    "selected_salary_method"
                ),
            ]
        ].copy()

        subset.columns = [
            "team_abbreviation",
            "selected_salary_method",
        ]

        rows.extend(
            subset.to_dict(
                orient="records"
            )
        )

    methods = pd.DataFrame(
        rows
    )

    summary = (
        methods.groupby(
            [
                "team_abbreviation",
                "selected_salary_method",
            ],
            as_index=False,
        )
        .size()
        .rename(
            columns={
                "size": (
                    "passing_pair_team_appearances"
                )
            }
        )
    )

    return summary.sort_values(
        [
            "team_abbreviation",
            "passing_pair_team_appearances",
        ],
        ascending=[
            True,
            False,
        ],
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
    print("TRADE SALARY PRECHECK ENGINE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(
        "Important: this is a salary precheck, "
        "not a final NBA legality determination."
    )
    print()

    financial, teams = load_inputs()

    trade_pool = build_trade_pool(
        financial
    )

    team_profiles = build_team_profiles(
        teams=teams,
        trade_pool=trade_pool,
    )

    print(
        f"Trade-pool players: "
        f"{len(trade_pool):,}"
    )
    print(
        "Main projection-pool players in trade pool: "
        f"{trade_pool['optimizer_projection_eligible'].sum():,}"
    )
    print(
        f"Teams represented: "
        f"{trade_pool['current_team_2026_27'].nunique():,}"
    )
    print()
    print(
        "Generating every cross-team one-for-one "
        "salary pairing..."
    )

    prechecks = (
        build_one_for_one_prechecks(
            trade_pool=trade_pool,
            team_profiles=team_profiles,
        )
    )

    passing = prechecks.loc[
        prechecks[
            "both_teams_salary_precheck_pass"
        ]
    ].copy()

    team_method_summary = (
        build_team_method_summary(
            passing
        )
    )

    trade_pool.to_parquet(
        TRADE_POOL_PARQUET_PATH,
        index=False,
    )

    trade_pool.to_csv(
        TRADE_POOL_CSV_PATH,
        index=False,
    )

    team_profiles.to_csv(
        TEAM_PROFILES_PATH,
        index=False,
    )

    prechecks.to_parquet(
        ALL_PRECHECKS_PARQUET_PATH,
        index=False,
    )

    passing.to_parquet(
        PASSING_PRECHECKS_PARQUET_PATH,
        index=False,
    )

    passing.to_csv(
        PASSING_PRECHECKS_CSV_PATH,
        index=False,
    )

    team_method_summary.to_csv(
        TEAM_METHOD_SUMMARY_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "salary_cap_2026_27": (
            SALARY_CAP_2026_27
        ),
        "luxury_tax_2026_27": (
            LUXURY_TAX_2026_27
        ),
        "first_apron_2026_27": (
            FIRST_APRON_2026_27
        ),
        "second_apron_2026_27": (
            SECOND_APRON_2026_27
        ),
        "salary_cap_2023_24": (
            SALARY_CAP_2023_24
        ),
        "expanded_tpe_scaled_addend_2026_27": (
            EXPANDED_TPE_SCALED_ADDEND_2026_27
        ),
        "base_tpe_allowance": (
            BASE_TPE_ALLOWANCE
        ),
        "trade_pool_players": len(
            trade_pool
        ),
        "main_projection_pool_players": int(
            trade_pool[
                "optimizer_projection_eligible"
            ].sum()
        ),
        "teams": int(
            trade_pool[
                "current_team_2026_27"
            ].nunique()
        ),
        "cross_team_one_for_one_pairs": len(
            prechecks
        ),
        "salary_precheck_passing_pairs": len(
            passing
        ),
        "salary_precheck_pass_rate": float(
            len(passing)
            / len(prechecks)
        ),
        "both_main_pool_passing_pairs": int(
            passing[
                "both_main_pool_eligible"
            ].sum()
        ),
        "rules_encoded": {
            "standard_tpe": (
                "one outgoing player; incoming salary no "
                "greater than outgoing salary plus the "
                "applicable allowance"
            ),
            "aggregated_standard_tpe": (
                "two or more outgoing players; incoming "
                "salary no greater than aggregate outgoing "
                "salary plus allowance; post-trade proxy "
                "not above second apron"
            ),
            "expanded_tpe": (
                "CBA formula using 200%, scaled addend, "
                "and 125% branches; post-trade proxy not "
                "above first apron"
            ),
            "room_under_cap": (
                "incoming salary no greater than estimated "
                "cap room after outgoing salary plus $250,000"
            ),
            "allowance_reduction": (
                "$250,000 allowance reduced to zero when "
                "post-trade salary proxy exceeds first apron"
            ),
        },
        "limitations": [
            (
                "Team salary and apron classifications use "
                "a listed-salary-obligation proxy, not "
                "official Apron Team Salary."
            ),
            (
                "Individual no-trade clauses, consent rights, "
                "recently signed/acquired restrictions, "
                "Base Year Compensation, poison-pill rules, "
                "bonuses, non-guaranteed salary adjustments, "
                "and trade timing are not yet verified."
            ),
            (
                "Passing means salary-compatible under at "
                "least one encoded method using proxy inputs. "
                "It does not mean the NBA would approve the trade."
            ),
            (
                "This version generates one-for-one player "
                "pairings only."
            ),
        ],
        "source_references": {
            "cba": (
                "2023 NBA-NBPA Collective Bargaining Agreement, "
                "Article VII Sections 2(e) and 6(j)"
            ),
            "cap_levels": (
                "NBA official 2026-27 salary cap release"
            ),
        },
        "output_files": {
            "trade_pool": str(
                TRADE_POOL_PARQUET_PATH
            ),
            "team_profiles": str(
                TEAM_PROFILES_PATH
            ),
            "all_prechecks": str(
                ALL_PRECHECKS_PARQUET_PATH
            ),
            "passing_prechecks": str(
                PASSING_PRECHECKS_PARQUET_PATH
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
    print("TRADE SALARY PRECHECKS CREATED")
    print("=" * 80)
    print(
        "Cross-team one-for-one pairs: "
        f"{len(prechecks):,}"
    )
    print(
        "Pairs passing both teams' salary precheck: "
        f"{len(passing):,}"
    )
    print(
        "Salary-precheck pass rate: "
        f"{metadata['salary_precheck_pass_rate']:.2%}"
    )
    print(
        "Passing pairs with both players in main "
        "projection pool: "
        f"{metadata['both_main_pool_passing_pairs']:,}"
    )
    print(
        "Expanded TPE scaled addend for 2026-27: "
        f"{format_money(EXPANDED_TPE_SCALED_ADDEND_2026_27)}"
    )
    print()

    print("TOP 30 SCREENING PAIRS")
    display_columns = [
        "team_a",
        "player_a_name",
        "player_a_salary",
        "team_b",
        "player_b_name",
        "player_b_salary",
        "team_a_selected_salary_method",
        "team_b_selected_salary_method",
        "salary_similarity_score",
        "projection_similarity_score",
        "screening_similarity_score",
        "both_main_pool_eligible",
    ]

    display = passing.head(
        30
    )[display_columns].copy()

    for column in [
        "player_a_salary",
        "player_b_salary",
    ]:
        display[column] = (
            display[column]
            .map(format_money)
        )

    for column in [
        "salary_similarity_score",
        "projection_similarity_score",
        "screening_similarity_score",
    ]:
        display[column] = pd.to_numeric(
            display[column],
            errors="coerce",
        ).round(4)

    print(
        display.to_string(
            index=False,
        )
    )

    print()
    print("TEAM SALARY PROXY TIERS")
    team_display = team_profiles[
        [
            "team_abbreviation",
            "trade_pool_players",
            "apron_team_salary_proxy_2026_27",
            "salary_proxy_tier",
            "official_apron_status_verified",
        ]
    ].copy()

    team_display[
        "apron_team_salary_proxy_2026_27"
    ] = team_display[
        "apron_team_salary_proxy_2026_27"
    ].map(
        format_money
    )

    print(
        team_display.to_string(
            index=False,
        )
    )

    print()
    print("SAVED FILES")
    print(TRADE_POOL_PARQUET_PATH)
    print(TRADE_POOL_CSV_PATH)
    print(TEAM_PROFILES_PATH)
    print(ALL_PRECHECKS_PARQUET_PATH)
    print(PASSING_PRECHECKS_PARQUET_PATH)
    print(PASSING_PRECHECKS_CSV_PATH)
    print(TEAM_METHOD_SUMMARY_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()