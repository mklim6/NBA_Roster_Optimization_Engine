from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "multi-player-trade-salary-precheck-v1-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PLAYER_MARKET_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)

TEAM_SALARY_PROFILES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "team_trade_salary_profiles_2026_27.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

PACKAGE_PLAYER_POOL_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "multi_player_trade_package_pool_2026_27.parquet"
)

PACKAGE_PLAYER_POOL_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "multi_player_trade_package_pool_2026_27.csv"
)

TEAM_DOUBLE_PACKAGES_PATH = (
    PROCESSED_DIRECTORY
    / "team_two_player_trade_packages_2026_27.parquet"
)

ALL_PRECHECKS_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_salary_prechecks_2026_27.parquet"
)

PASSING_PRECHECKS_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_salary_prechecks_passing_2026_27.parquet"
)

TOP_PASSING_CSV_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_salary_prechecks_top_25000_2026_27.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_salary_precheck_team_summary_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_salary_precheck_metadata_2026_27.json"
)


SALARY_CAP_2026_27 = 164_961_000.0
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
    "projected_expected_contribution",
    "survival_weighted_active_downside_score",
    "projected_survival_probability",
    "market_value_percentile_v2",
    "on_court_caliber_score",
    "recommendation_asset_class_v3",
    "protected_player_flag_v3",
]

TEAM_REQUIRED_COLUMNS = [
    "team_abbreviation",
    "apron_team_salary_proxy_2026_27",
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


def package_value_units(
    market_value_percentiles: list[float],
) -> float:
    values = np.array(
        market_value_percentiles,
        dtype=float,
    )

    values = np.clip(
        values / 100.0,
        0.0,
        1.0,
    )

    # Convex scaling gives premium individual assets more weight
    # than a simple sum of percentiles.
    return float(
        np.sum(
            np.power(
                values,
                1.35,
            )
            * 100.0
        )
    )


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


def evaluate_salary_precheck(
    team_salary_proxy: float,
    outgoing_salary: float,
    incoming_salary: float,
    outgoing_player_count: int,
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

    aggregated_standard_method_pass = bool(
        outgoing_player_count >= 2
        and incoming_salary
        <= standard_limit + 1e-6
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

    methods: list[str] = []

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

    method_priority = [
        "room_under_cap_plus_250k",
        "standard_tpe",
        "aggregated_standard_tpe",
        "expanded_tpe_first_apron_hard_cap",
    ]

    selected_method = next(
        (
            method
            for method in method_priority
            if method in methods
        ),
        "no_salary_method_passed",
    )

    return {
        "salary_precheck_pass": bool(
            methods
        ),
        "salary_precheck_methods": (
            " | ".join(methods)
        ),
        "selected_salary_method": (
            selected_method
        ),
        "post_trade_salary_proxy": (
            post_trade_salary_proxy
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
        "standard_or_aggregated_limit": (
            standard_limit
        ),
        "expanded_limit_before_hard_cap": (
            expanded_limit
        ),
    }


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PLAYER_MARKET_PATH,
        TEAM_SALARY_PROFILES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    players = pd.read_parquet(
        PLAYER_MARKET_PATH
    )

    teams = pd.read_csv(
        TEAM_SALARY_PROFILES_PATH
    )

    require_columns(
        players,
        PLAYER_REQUIRED_COLUMNS,
        "V3 player market layer",
    )

    require_columns(
        teams,
        TEAM_REQUIRED_COLUMNS,
        "Team salary profiles",
    )

    return (
        players.copy(),
        teams.copy(),
    )


def build_package_player_pool(
    players: pd.DataFrame,
) -> pd.DataFrame:
    salary = numeric_series(
        players,
        "trade_salary_2026_27",
    )

    protected = players[
        "protected_player_flag_v3"
    ].fillna(False).astype(bool)

    valid_team = players[
        "current_team_2026_27"
    ].notna()

    valid_id = players[
        "player_id"
    ].notna()

    if (
        "optimizer_projection_eligible"
        in players.columns
    ):
        optimizer_eligible = players[
            "optimizer_projection_eligible"
        ].fillna(False).astype(bool)
    else:
        optimizer_eligible = pd.Series(
            True,
            index=players.index,
        )

    pool = players.loc[
        ~protected
        & valid_team
        & valid_id
        & salary.gt(0)
        & optimizer_eligible
    ].copy()

    pool[
        "player_id"
    ] = pool[
        "player_id"
    ].map(
        player_key
    )

    if pool[
        "player_id"
    ].duplicated().any():
        duplicate_names = (
            pool.loc[
                pool[
                    "player_id"
                ].duplicated(
                    keep=False
                ),
                "player_name",
            ]
            .astype(str)
            .tolist()
        )

        raise ValueError(
            "Package pool contains duplicate player IDs:\n"
            + "\n".join(
                duplicate_names
            )
        )

    numeric_columns = [
        "trade_salary_2026_27",
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
        "projected_survival_probability",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "future_salary_commitment_2027_28_plus",
        "contract_years_remaining_including_2026_27",
    ]

    for column in numeric_columns:
        if column in pool.columns:
            pool[column] = numeric_series(
                pool,
                column,
                fill_value=0.0,
            )

    pool[
        "multi_player_package_eligible"
    ] = True

    pool[
        "package_pool_scope_note"
    ] = (
        "Non-protected player with matched salary and an "
        "optimizer-eligible projection. Individual contract "
        "restrictions and official NBA trade approval remain "
        "unverified."
    )

    return pool.sort_values(
        [
            "current_team_2026_27",
            "market_value_percentile_v2",
            "projected_expected_contribution",
        ],
        ascending=[
            True,
            False,
            False,
        ],
    ).reset_index(drop=True)


def build_two_player_packages(
    pool: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    package_number = 0

    for team, roster in pool.groupby(
        "current_team_2026_27",
        sort=True,
    ):
        records = roster.to_dict(
            orient="records"
        )

        for first, second in combinations(
            records,
            2,
        ):
            package_number += 1

            salary = (
                float(
                    first[
                        "trade_salary_2026_27"
                    ]
                )
                + float(
                    second[
                        "trade_salary_2026_27"
                    ]
                )
            )

            expected = (
                float(
                    first[
                        "projected_expected_contribution"
                    ]
                )
                + float(
                    second[
                        "projected_expected_contribution"
                    ]
                )
            )

            downside = (
                float(
                    first[
                        "survival_weighted_active_downside_score"
                    ]
                )
                + float(
                    second[
                        "survival_weighted_active_downside_score"
                    ]
                )
            )

            future_salary = (
                float(
                    first.get(
                        "future_salary_commitment_2027_28_plus",
                        0.0,
                    )
                )
                + float(
                    second.get(
                        "future_salary_commitment_2027_28_plus",
                        0.0,
                    )
                )
            )

            value_units = package_value_units(
                [
                    float(
                        first[
                            "market_value_percentile_v2"
                        ]
                    ),
                    float(
                        second[
                            "market_value_percentile_v2"
                        ]
                    ),
                ]
            )

            rows.append(
                {
                    "two_player_package_id": (
                        f"pkg2_{package_number:06d}"
                    ),
                    "team_abbreviation": team,
                    "player_1_id": (
                        first["player_id"]
                    ),
                    "player_1_name": (
                        first["player_name"]
                    ),
                    "player_1_salary": (
                        first[
                            "trade_salary_2026_27"
                        ]
                    ),
                    "player_1_market_value_percentile": (
                        first[
                            "market_value_percentile_v2"
                        ]
                    ),
                    "player_1_asset_class": (
                        first[
                            "recommendation_asset_class_v3"
                        ]
                    ),
                    "player_2_id": (
                        second["player_id"]
                    ),
                    "player_2_name": (
                        second["player_name"]
                    ),
                    "player_2_salary": (
                        second[
                            "trade_salary_2026_27"
                        ]
                    ),
                    "player_2_market_value_percentile": (
                        second[
                            "market_value_percentile_v2"
                        ]
                    ),
                    "player_2_asset_class": (
                        second[
                            "recommendation_asset_class_v3"
                        ]
                    ),
                    "package_salary": salary,
                    "package_expected_contribution": (
                        expected
                    ),
                    "package_downside_contribution": (
                        downside
                    ),
                    "package_future_salary_commitment": (
                        future_salary
                    ),
                    "package_market_value_units": (
                        value_units
                    ),
                    "package_player_count": 2,
                }
            )

    packages = pd.DataFrame(
        rows
    )

    if packages.empty:
        raise ValueError(
            "No two-player team packages were generated."
        )

    return packages.sort_values(
        [
            "team_abbreviation",
            "package_salary",
        ],
        ascending=[
            True,
            False,
        ],
    ).reset_index(drop=True)


def build_single_player_records(
    pool: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for player in pool.to_dict(
        orient="records"
    ):
        rows.append(
            {
                "single_player_id": (
                    player["player_id"]
                ),
                "single_player_name": (
                    player["player_name"]
                ),
                "team_abbreviation": (
                    player[
                        "current_team_2026_27"
                    ]
                ),
                "single_salary": float(
                    player[
                        "trade_salary_2026_27"
                    ]
                ),
                "single_expected_contribution": float(
                    player[
                        "projected_expected_contribution"
                    ]
                ),
                "single_downside_contribution": float(
                    player[
                        "survival_weighted_active_downside_score"
                    ]
                ),
                "single_future_salary_commitment": float(
                    player.get(
                        "future_salary_commitment_2027_28_plus",
                        0.0,
                    )
                ),
                "single_market_value_percentile": float(
                    player[
                        "market_value_percentile_v2"
                    ]
                ),
                "single_market_value_units": (
                    package_value_units(
                        [
                            float(
                                player[
                                    "market_value_percentile_v2"
                                ]
                            )
                        ]
                    )
                ),
                "single_asset_class": (
                    player[
                        "recommendation_asset_class_v3"
                    ]
                ),
            }
        )

    return rows


def build_team_profile_lookup(
    teams: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    teams = teams.copy()

    teams[
        "apron_team_salary_proxy_2026_27"
    ] = numeric_series(
        teams,
        "apron_team_salary_proxy_2026_27",
        fill_value=0.0,
    )

    return (
        teams.set_index(
            "team_abbreviation"
        )
        .to_dict(
            orient="index"
        )
    )


def create_precheck_row(
    package: dict[str, Any],
    single: dict[str, Any],
    team_profile_lookup: dict[str, dict[str, Any]],
    pair_number: int,
) -> dict[str, Any]:
    team_sending_two = str(
        package[
            "team_abbreviation"
        ]
    )

    team_sending_one = str(
        single[
            "team_abbreviation"
        ]
    )

    two_salary = float(
        package[
            "package_salary"
        ]
    )

    one_salary = float(
        single[
            "single_salary"
        ]
    )

    two_team_salary = float(
        team_profile_lookup[
            team_sending_two
        ][
            "apron_team_salary_proxy_2026_27"
        ]
    )

    one_team_salary = float(
        team_profile_lookup[
            team_sending_one
        ][
            "apron_team_salary_proxy_2026_27"
        ]
    )

    two_team_check = (
        evaluate_salary_precheck(
            team_salary_proxy=(
                two_team_salary
            ),
            outgoing_salary=two_salary,
            incoming_salary=one_salary,
            outgoing_player_count=2,
        )
    )

    one_team_check = (
        evaluate_salary_precheck(
            team_salary_proxy=(
                one_team_salary
            ),
            outgoing_salary=one_salary,
            incoming_salary=two_salary,
            outgoing_player_count=1,
        )
    )

    both_pass = bool(
        two_team_check[
            "salary_precheck_pass"
        ]
        and one_team_check[
            "salary_precheck_pass"
        ]
    )

    salary_similarity = (
        safe_similarity(
            two_salary,
            one_salary,
        )
    )

    expected_similarity = (
        safe_similarity(
            float(
                package[
                    "package_expected_contribution"
                ]
            ),
            float(
                single[
                    "single_expected_contribution"
                ]
            ),
        )
    )

    downside_similarity = (
        safe_similarity(
            float(
                package[
                    "package_downside_contribution"
                ]
            ),
            float(
                single[
                    "single_downside_contribution"
                ]
            ),
        )
    )

    market_value_similarity = (
        safe_similarity(
            float(
                package[
                    "package_market_value_units"
                ]
            ),
            float(
                single[
                    "single_market_value_units"
                ]
            ),
        )
    )

    package_screening_score = (
        0.45
        * salary_similarity
        + 0.25
        * expected_similarity
        + 0.15
        * downside_similarity
        + 0.15
        * market_value_similarity
    )

    return {
        "package_trade_id": (
            f"2v1_{pair_number:08d}"
        ),
        "package_type": (
            "two_for_one"
        ),
        "team_sending_two": (
            team_sending_two
        ),
        "team_sending_one": (
            team_sending_one
        ),
        "two_player_package_id": (
            package[
                "two_player_package_id"
            ]
        ),
        "two_side_player_1_id": (
            package[
                "player_1_id"
            ]
        ),
        "two_side_player_1_name": (
            package[
                "player_1_name"
            ]
        ),
        "two_side_player_1_salary": (
            package[
                "player_1_salary"
            ]
        ),
        "two_side_player_1_asset_class": (
            package[
                "player_1_asset_class"
            ]
        ),
        "two_side_player_2_id": (
            package[
                "player_2_id"
            ]
        ),
        "two_side_player_2_name": (
            package[
                "player_2_name"
            ]
        ),
        "two_side_player_2_salary": (
            package[
                "player_2_salary"
            ]
        ),
        "two_side_player_2_asset_class": (
            package[
                "player_2_asset_class"
            ]
        ),
        "two_side_total_salary": (
            two_salary
        ),
        "two_side_expected_contribution": (
            package[
                "package_expected_contribution"
            ]
        ),
        "two_side_downside_contribution": (
            package[
                "package_downside_contribution"
            ]
        ),
        "two_side_market_value_units": (
            package[
                "package_market_value_units"
            ]
        ),
        "two_side_future_salary_commitment": (
            package[
                "package_future_salary_commitment"
            ]
        ),
        "one_side_player_id": (
            single[
                "single_player_id"
            ]
        ),
        "one_side_player_name": (
            single[
                "single_player_name"
            ]
        ),
        "one_side_player_salary": (
            one_salary
        ),
        "one_side_player_asset_class": (
            single[
                "single_asset_class"
            ]
        ),
        "one_side_expected_contribution": (
            single[
                "single_expected_contribution"
            ]
        ),
        "one_side_downside_contribution": (
            single[
                "single_downside_contribution"
            ]
        ),
        "one_side_market_value_units": (
            single[
                "single_market_value_units"
            ]
        ),
        "one_side_future_salary_commitment": (
            single[
                "single_future_salary_commitment"
            ]
        ),
        "team_sending_two_salary_precheck_pass": (
            two_team_check[
                "salary_precheck_pass"
            ]
        ),
        "team_sending_two_selected_salary_method": (
            two_team_check[
                "selected_salary_method"
            ]
        ),
        "team_sending_two_salary_methods": (
            two_team_check[
                "salary_precheck_methods"
            ]
        ),
        "team_sending_two_post_trade_salary_proxy": (
            two_team_check[
                "post_trade_salary_proxy"
            ]
        ),
        "team_sending_one_salary_precheck_pass": (
            one_team_check[
                "salary_precheck_pass"
            ]
        ),
        "team_sending_one_selected_salary_method": (
            one_team_check[
                "selected_salary_method"
            ]
        ),
        "team_sending_one_salary_methods": (
            one_team_check[
                "salary_precheck_methods"
            ]
        ),
        "team_sending_one_post_trade_salary_proxy": (
            one_team_check[
                "post_trade_salary_proxy"
            ]
        ),
        "both_teams_salary_precheck_pass": (
            both_pass
        ),
        "salary_difference_absolute": abs(
            two_salary - one_salary
        ),
        "salary_similarity_score": (
            salary_similarity
        ),
        "expected_contribution_similarity_score": (
            expected_similarity
        ),
        "downside_similarity_score": (
            downside_similarity
        ),
        "market_value_similarity_score": (
            market_value_similarity
        ),
        "package_screening_score": (
            package_screening_score
        ),
        "team_sending_two_roster_count_delta": (
            -1
        ),
        "team_sending_one_roster_count_delta": (
            1
        ),
        "official_roster_slot_availability_verified": (
            False
        ),
        "individual_contract_restrictions_verified": (
            False
        ),
        "final_trade_legality_verified": (
            False
        ),
        "salary_precheck_scope_note": (
            "Preliminary two-for-one salary check using "
            "team salary proxies. Roster slots, individual "
            "restrictions, aggregation timing, and official "
            "NBA approval remain unverified."
        ),
    }


def generate_prechecks(
    packages: pd.DataFrame,
    pool: pd.DataFrame,
    teams: pd.DataFrame,
) -> pd.DataFrame:
    package_lookup = {
        team: group.to_dict(
            orient="records"
        )
        for team, group
        in packages.groupby(
            "team_abbreviation",
            sort=True,
        )
    }

    singles_lookup = {
        team: group
        for team, group
        in pd.DataFrame(
            build_single_player_records(
                pool
            )
        ).groupby(
            "team_abbreviation",
            sort=True,
        )
    }

    team_profile_lookup = (
        build_team_profile_lookup(
            teams
        )
    )

    represented_teams = sorted(
        set(
            package_lookup
        )
        & set(
            singles_lookup
        )
    )

    missing_profiles = sorted(
        set(
            represented_teams
        )
        - set(
            team_profile_lookup
        )
    )

    if missing_profiles:
        raise ValueError(
            "Missing team salary profiles for:\n"
            + "\n".join(
                missing_profiles
            )
        )

    rows: list[dict[str, Any]] = []

    pair_number = 0
    processed_team_pairs = 0

    for team_index, team_a in enumerate(
        represented_teams
    ):
        for team_b in represented_teams[
            team_index + 1:
        ]:
            processed_team_pairs += 1

            team_a_packages = (
                package_lookup[
                    team_a
                ]
            )

            team_b_packages = (
                package_lookup[
                    team_b
                ]
            )

            team_a_singles = (
                singles_lookup[
                    team_a
                ].to_dict(
                    orient="records"
                )
            )

            team_b_singles = (
                singles_lookup[
                    team_b
                ].to_dict(
                    orient="records"
                )
            )

            for package in team_a_packages:
                for single in team_b_singles:
                    pair_number += 1

                    rows.append(
                        create_precheck_row(
                            package=package,
                            single=single,
                            team_profile_lookup=(
                                team_profile_lookup
                            ),
                            pair_number=pair_number,
                        )
                    )

            for package in team_b_packages:
                for single in team_a_singles:
                    pair_number += 1

                    rows.append(
                        create_precheck_row(
                            package=package,
                            single=single,
                            team_profile_lookup=(
                                team_profile_lookup
                            ),
                            pair_number=pair_number,
                        )
                    )

            if (
                processed_team_pairs % 50
                == 0
            ):
                print(
                    "Processed team pairs: "
                    f"{processed_team_pairs:,} / "
                    f"{len(represented_teams) * (len(represented_teams) - 1) // 2:,}"
                )

    if not rows:
        raise ValueError(
            "No two-for-one package combinations "
            "were generated."
        )

    return pd.DataFrame(
        rows
    )


def build_team_summary(
    passing: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for side in [
        "two",
        "one",
    ]:
        team_column = (
            "team_sending_two"
            if side == "two"
            else "team_sending_one"
        )

        method_column = (
            "team_sending_two_selected_salary_method"
            if side == "two"
            else "team_sending_one_selected_salary_method"
        )

        subset = passing[
            [
                team_column,
                method_column,
            ]
        ].copy()

        subset.columns = [
            "team_abbreviation",
            "selected_salary_method",
        ]

        subset[
            "package_side"
        ] = side

        rows.extend(
            subset.to_dict(
                orient="records"
            )
        )

    appearances = pd.DataFrame(
        rows
    )

    if appearances.empty:
        return pd.DataFrame()

    return (
        appearances.groupby(
            [
                "team_abbreviation",
                "package_side",
                "selected_salary_method",
            ],
            as_index=False,
        )
        .size()
        .rename(
            columns={
                "size": (
                    "passing_package_appearances"
                )
            }
        )
        .sort_values(
            [
                "team_abbreviation",
                "package_side",
                "passing_package_appearances",
            ],
            ascending=[
                True,
                True,
                False,
            ],
        )
        .reset_index(drop=True)
    )


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
    print("TWO-FOR-ONE TRADE SALARY PRECHECK ENGINE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    players, teams = load_inputs()

    pool = build_package_player_pool(
        players
    )

    packages = build_two_player_packages(
        pool
    )

    print(
        f"Eligible package players: "
        f"{len(pool):,}"
    )
    print(
        f"Teams represented: "
        f"{pool['current_team_2026_27'].nunique():,}"
    )
    print(
        "Two-player same-team packages: "
        f"{len(packages):,}"
    )
    print()
    print(
        "Generating cross-team two-for-one "
        "salary combinations..."
    )

    prechecks = generate_prechecks(
        packages=packages,
        pool=pool,
        teams=teams,
    )

    passing = prechecks.loc[
        prechecks[
            "both_teams_salary_precheck_pass"
        ]
    ].copy()

    prechecks = prechecks.sort_values(
        [
            "both_teams_salary_precheck_pass",
            "package_screening_score",
            "salary_similarity_score",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    passing = passing.sort_values(
        [
            "package_screening_score",
            "market_value_similarity_score",
            "expected_contribution_similarity_score",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    team_summary = build_team_summary(
        passing
    )

    pool.to_parquet(
        PACKAGE_PLAYER_POOL_PARQUET_PATH,
        index=False,
    )

    pool.to_csv(
        PACKAGE_PLAYER_POOL_CSV_PATH,
        index=False,
    )

    packages.to_parquet(
        TEAM_DOUBLE_PACKAGES_PATH,
        index=False,
    )

    prechecks.to_parquet(
        ALL_PRECHECKS_PATH,
        index=False,
    )

    passing.to_parquet(
        PASSING_PRECHECKS_PATH,
        index=False,
    )

    top_csv = passing.head(
        25_000
    ).copy()

    top_csv.to_csv(
        TOP_PASSING_CSV_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "eligible_package_players": len(
            pool
        ),
        "teams_represented": int(
            pool[
                "current_team_2026_27"
            ].nunique()
        ),
        "same_team_two_player_packages": len(
            packages
        ),
        "cross_team_two_for_one_combinations": len(
            prechecks
        ),
        "salary_precheck_passing_packages": len(
            passing
        ),
        "salary_precheck_pass_rate": float(
            len(passing)
            / len(prechecks)
        ),
        "expanded_tpe_scaled_addend_2026_27": (
            EXPANDED_TPE_SCALED_ADDEND_2026_27
        ),
        "pool_rules": {
            "protected_players_excluded": True,
            "optimizer_projection_required": True,
            "positive_matched_salary_required": True,
        },
        "package_rules": {
            "same_team_two_player_outgoing_package": True,
            "cross_team_single_incoming_player": True,
            "both_team_salary_prechecks_required": True,
            "aggregated_standard_tpe_checked": True,
            "expanded_tpe_checked": True,
            "room_under_cap_checked": True,
        },
        "screening_score_weights": {
            "salary_similarity": 0.45,
            "expected_contribution_similarity": 0.25,
            "downside_similarity": 0.15,
            "market_value_similarity": 0.15,
        },
        "limitations": [
            (
                "This stage tests salary compatibility only. "
                "It does not score basketball fit."
            ),
            (
                "Team salary values remain proxies rather than "
                "official Apron Team Salary."
            ),
            (
                "Roster-slot availability is not verified."
            ),
            (
                "Individual contract restrictions, recent "
                "transaction timing, consent rights, and final "
                "NBA approval are not verified."
            ),
            (
                "Protected players are excluded from this first "
                "ordinary multi-player package universe."
            ),
        ],
        "output_files": {
            "package_player_pool": str(
                PACKAGE_PLAYER_POOL_PARQUET_PATH
            ),
            "two_player_packages": str(
                TEAM_DOUBLE_PACKAGES_PATH
            ),
            "all_prechecks": str(
                ALL_PRECHECKS_PATH
            ),
            "passing_prechecks": str(
                PASSING_PRECHECKS_PATH
            ),
            "top_passing_csv": str(
                TOP_PASSING_CSV_PATH
            ),
            "team_summary": str(
                TEAM_SUMMARY_PATH
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
    print("TWO-FOR-ONE SALARY PRECHECKS CREATED")
    print("=" * 80)
    print(
        "Cross-team package combinations: "
        f"{len(prechecks):,}"
    )
    print(
        "Packages passing both teams' salary precheck: "
        f"{len(passing):,}"
    )
    print(
        "Salary-precheck pass rate: "
        f"{metadata['salary_precheck_pass_rate']:.2%}"
    )
    print()

    print("TOP 30 PASSING PACKAGE SCREENS")
    if passing.empty:
        print(
            "No packages passed both teams' salary precheck."
        )
    else:
        display_columns = [
            "team_sending_two",
            "two_side_player_1_name",
            "two_side_player_2_name",
            "two_side_total_salary",
            "team_sending_one",
            "one_side_player_name",
            "one_side_player_salary",
            "team_sending_two_selected_salary_method",
            "team_sending_one_selected_salary_method",
            "salary_similarity_score",
            "expected_contribution_similarity_score",
            "market_value_similarity_score",
            "package_screening_score",
        ]

        display = passing.head(
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
            "salary_similarity_score",
            "expected_contribution_similarity_score",
            "market_value_similarity_score",
            "package_screening_score",
        ]:
            display[column] = (
                pd.to_numeric(
                    display[column],
                    errors="coerce",
                )
                .round(4)
            )

        print(
            display.to_string(
                index=False,
            )
        )

    print()
    print("SAVED FILES")
    print(
        PACKAGE_PLAYER_POOL_PARQUET_PATH
    )
    print(
        PACKAGE_PLAYER_POOL_CSV_PATH
    )
    print(
        TEAM_DOUBLE_PACKAGES_PATH
    )
    print(ALL_PRECHECKS_PATH)
    print(PASSING_PRECHECKS_PATH)
    print(TOP_PASSING_CSV_PATH)
    print(TEAM_SUMMARY_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()