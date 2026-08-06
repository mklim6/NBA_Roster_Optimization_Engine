from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "mixed-player-pick-optimizer-v2-merge-safe-2026-08-04"
)

RELEASE_NAME = (
    "mixed_player_pick_optimizer_2026_27_v2"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

PLAYER_VALUE_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)

ONE_FOR_ONE_RUNTIME_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_trade_realism_scores_2026_27_v3.parquet"
)

TWO_FOR_ONE_RUNTIME_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_trade_realism_scores_2026_27_v2.parquet"
)

PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

TEAM_SALARY_PROFILE_PATH = (
    PROCESSED_DIRECTORY
    / "team_trade_salary_profiles_2026_27.csv"
)

CANONICAL_CONTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_v3.csv"
)

CANONICAL_CONTRACT_READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_readiness_v3.csv"
)

UNIFIED_ASSET_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "optimizer_unified_asset_inventory_2026_27_v2.parquet"
)

ONE_FOR_ONE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_mixed_player_pick_candidates_2026_27_v2.parquet"
)

TWO_FOR_ONE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_mixed_player_pick_candidates_2026_27_v2.parquet"
)

TOP_TEAM_RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_recommendations_2026_27_v2.csv"
)

BRANCH_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_optimizer_branch_summary_2026_27_v2.csv"
)

TEAM_PICK_POOL_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_pick_pool_summary_2026_27_v2.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_optimizer_validation_2026_27_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_optimizer_metadata_2026_27_v2.json"
)


EXPECTED_PLAYER_ROWS = 395
EXPECTED_ONE_FOR_ONE_ROWS = 17147
EXPECTED_TWO_FOR_ONE_ROWS = 100033
EXPECTED_PICK_ROWS = 174
EXPECTED_STANDALONE_PICK_ROWS = 172
EXPECTED_TEAM_ROWS = 30

MAX_PICK_OPTIONS_PER_BASE_PACKAGE = 3
TOP_RECOMMENDATIONS_PER_TEAM = 50

VALUE_TOLERANCE = 1e-9

ONE_FOR_ONE_REQUIRED_COLUMNS = [
    "pair_id",
    "team_a",
    "team_b",
    "player_a_id",
    "player_b_id",
    "both_teams_salary_precheck_pass",
]

TWO_FOR_ONE_REQUIRED_COLUMNS = [
    "team_sending_one",
    "team_sending_two",
    "one_side_player_id",
    "two_side_player_1_id",
    "two_side_player_2_id",
    "both_teams_salary_precheck_pass",
]

PICK_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "candidate_right_value_score",
    "standalone_trade_asset_flag",
    "tradability_status",
    "right_structure",
    "right_display_name",
    "expected_pick_count",
]

PLAYER_REQUIRED_COLUMNS = [
    "player_id",
    "player_name",
    "current_team_2026_27",
    "surplus_value_score",
    "trade_salary_2026_27",
]


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def json_safe(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
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

    if isinstance(value, float):
        return (
            None
            if math.isnan(value)
            else value
        )

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


def require_file(
    path: Path,
    label: str,
) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required {label} was not found:\n{path}"
        )


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


def parse_bool_series(
    series: pd.Series,
) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    return (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "passed",
            }
        )
    )


def normalize_id_series(
    series: pd.Series,
) -> pd.Series:
    output = (
        series
        .fillna("")
        .astype(str)
        .str.strip()
    )

    output = output.str.replace(
        r"\.0$",
        "",
        regex=True,
    )

    return output


def stable_id(
    *parts: Any,
    prefix: str,
) -> str:
    payload = "|".join(
        clean_text(part)
        for part in parts
    )

    digest = hashlib.sha1(
        payload.encode("utf-8")
    ).hexdigest()[:20]

    return f"{prefix}_{digest}"


def first_existing_column(
    frame: pd.DataFrame,
    candidates: list[str],
) -> str:
    for column in candidates:
        if column in frame.columns:
            return column

    return ""


def select_numeric_signal(
    frame: pd.DataFrame,
    preferred: list[str],
    required_terms: list[str],
    excluded_terms: list[str],
) -> str:
    preferred_column = first_existing_column(
        frame,
        preferred,
    )

    if preferred_column:
        return preferred_column

    candidates = []

    for column in frame.columns:
        normalized = column.lower()

        if not all(
            term in normalized
            for term in required_terms
        ):
            continue

        if any(
            term in normalized
            for term in excluded_terms
        ):
            continue

        numeric = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

        non_null = int(
            numeric.notna().sum()
        )

        if non_null <= 0:
            continue

        candidates.append(
            (
                non_null,
                column,
            )
        )

    if not candidates:
        return ""

    return sorted(
        candidates,
        key=lambda item: (
            -item[0],
            item[1],
        ),
    )[0][1]


def percentile_score(
    series: pd.Series,
) -> pd.Series:
    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    if numeric.notna().sum() == 0:
        return pd.Series(
            np.full(
                len(series),
                50.0,
            ),
            index=series.index,
            dtype=float,
        )

    return (
        numeric.rank(
            method="average",
            pct=True,
        )
        .fillna(0.5)
        .mul(100.0)
    )


def load_inputs() -> dict[str, pd.DataFrame]:
    required_files = [
        (
            PLAYER_VALUE_PATH,
            "player-value layer",
        ),
        (
            ONE_FOR_ONE_RUNTIME_PATH,
            "one-for-one runtime",
        ),
        (
            TWO_FOR_ONE_RUNTIME_PATH,
            "two-for-one runtime",
        ),
        (
            PICK_INVENTORY_PATH,
            "future-pick inventory",
        ),
        (
            TEAM_SALARY_PROFILE_PATH,
            "team salary profiles",
        ),
        (
            CANONICAL_CONTRACT_PATH,
            "canonical runtime contract",
        ),
        (
            CANONICAL_CONTRACT_READINESS_PATH,
            "canonical contract readiness",
        ),
    ]

    for path, label in required_files:
        require_file(
            path,
            label,
        )

    player_values = pd.read_parquet(
        PLAYER_VALUE_PATH
    )

    one_for_one = pd.read_parquet(
        ONE_FOR_ONE_RUNTIME_PATH
    )

    two_for_one = pd.read_parquet(
        TWO_FOR_ONE_RUNTIME_PATH
    )

    picks = pd.read_parquet(
        PICK_INVENTORY_PATH
    )

    team_salary_profiles = pd.read_csv(
        TEAM_SALARY_PROFILE_PATH
    )

    contract = pd.read_csv(
        CANONICAL_CONTRACT_PATH
    )

    contract_readiness = pd.read_csv(
        CANONICAL_CONTRACT_READINESS_PATH
    )

    require_columns(
        player_values,
        PLAYER_REQUIRED_COLUMNS,
        "Player-value layer",
    )

    require_columns(
        one_for_one,
        ONE_FOR_ONE_REQUIRED_COLUMNS,
        "One-for-one runtime",
    )

    require_columns(
        two_for_one,
        TWO_FOR_ONE_REQUIRED_COLUMNS,
        "Two-for-one runtime",
    )

    require_columns(
        picks,
        PICK_REQUIRED_COLUMNS,
        "Future-pick inventory",
    )

    if not parse_bool_series(
        contract_readiness[
            "passed"
        ]
    ).all():
        raise RuntimeError(
            "Canonical runtime contract readiness does not pass "
            "every check."
        )

    return {
        "player_values": player_values,
        "one_for_one": one_for_one,
        "two_for_one": two_for_one,
        "picks": picks,
        "team_salary_profiles": team_salary_profiles,
        "contract": contract,
        "contract_readiness": contract_readiness,
    }


def prepare_player_lookup(
    player_values: pd.DataFrame,
) -> pd.DataFrame:
    output = player_values[
        PLAYER_REQUIRED_COLUMNS
    ].copy()

    output[
        "player_id_key"
    ] = normalize_id_series(
        output[
            "player_id"
        ]
    )

    output[
        "current_team_2026_27"
    ] = (
        output[
            "current_team_2026_27"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "surplus_value_score"
    ] = pd.to_numeric(
        output[
            "surplus_value_score"
        ],
        errors="coerce",
    )

    output[
        "trade_salary_2026_27"
    ] = pd.to_numeric(
        output[
            "trade_salary_2026_27"
        ],
        errors="coerce",
    ).fillna(0.0)

    if output[
        "player_id_key"
    ].eq("").any():
        raise RuntimeError(
            "The player-value layer contains an empty player ID."
        )

    if output[
        "player_id_key"
    ].duplicated().any():
        duplicates = output.loc[
            output[
                "player_id_key"
            ].duplicated(
                keep=False
            )
        ]

        raise RuntimeError(
            "The player-value layer contains duplicate player IDs:\n"
            + duplicates.head(20).to_string(
                index=False
            )
        )

    if output[
        "surplus_value_score"
    ].isna().any():
        raise RuntimeError(
            "The player-value layer contains a missing surplus-value "
            "score."
        )

    return output


def prepare_pick_pool(
    picks: pd.DataFrame,
) -> pd.DataFrame:
    output = picks.copy()

    output[
        "candidate_team"
    ] = (
        output[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "candidate_right_value_score"
    ] = pd.to_numeric(
        output[
            "candidate_right_value_score"
        ],
        errors="coerce",
    )

    output[
        "expected_pick_count"
    ] = pd.to_numeric(
        output[
            "expected_pick_count"
        ],
        errors="coerce",
    )

    output[
        "standalone_trade_asset_flag"
    ] = parse_bool_series(
        output[
            "standalone_trade_asset_flag"
        ]
    )

    output = output.loc[
        output[
            "standalone_trade_asset_flag"
        ]
    ].copy()

    if output[
        "candidate_right_value_score"
    ].isna().any():
        raise RuntimeError(
            "The standalone pick pool contains a missing value score."
        )

    if output[
        "future_pick_right_id"
    ].duplicated().any():
        raise RuntimeError(
            "The standalone pick pool contains duplicate right IDs."
        )

    output = output.sort_values(
        [
            "candidate_team",
            "candidate_right_value_score",
            "future_pick_right_id",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    return output


def build_unified_asset_inventory(
    player_lookup: pd.DataFrame,
    pick_pool: pd.DataFrame,
) -> pd.DataFrame:
    players = pd.DataFrame(
        {
            "asset_id": (
                "PLAYER_"
                + player_lookup[
                    "player_id_key"
                ]
            ),
            "asset_type": "player",
            "asset_team": (
                player_lookup[
                    "current_team_2026_27"
                ]
            ),
            "asset_display_name": (
                player_lookup[
                    "player_name"
                ]
                .fillna("")
                .astype(str)
            ),
            "asset_value_score": (
                player_lookup[
                    "surplus_value_score"
                ]
            ),
            "asset_trade_salary": (
                player_lookup[
                    "trade_salary_2026_27"
                ]
            ),
            "standalone_trade_asset_flag": True,
            "trade_date_legality_verified": False,
            "tradability_status": (
                "requires_player_trade_date_restriction_validation"
            ),
            "source_asset_id": (
                player_lookup[
                    "player_id_key"
                ]
            ),
            "right_structure": "",
            "expected_pick_count": 0.0,
            "source_dataset": (
                PLAYER_VALUE_PATH.name
            ),
        }
    )

    picks = pd.DataFrame(
        {
            "asset_id": (
                pick_pool[
                    "future_pick_right_id"
                ]
            ),
            "asset_type": "future_pick_right",
            "asset_team": (
                pick_pool[
                    "candidate_team"
                ]
            ),
            "asset_display_name": (
                pick_pool[
                    "right_display_name"
                ]
                .fillna("")
                .astype(str)
            ),
            "asset_value_score": (
                pick_pool[
                    "candidate_right_value_score"
                ]
            ),
            "asset_trade_salary": 0.0,
            "standalone_trade_asset_flag": (
                pick_pool[
                    "standalone_trade_asset_flag"
                ]
            ),
            "trade_date_legality_verified": False,
            "tradability_status": (
                pick_pool[
                    "tradability_status"
                ]
                .fillna("")
                .astype(str)
            ),
            "source_asset_id": (
                pick_pool[
                    "future_pick_right_id"
                ]
            ),
            "right_structure": (
                pick_pool[
                    "right_structure"
                ]
                .fillna("")
                .astype(str)
            ),
            "expected_pick_count": (
                pick_pool[
                    "expected_pick_count"
                ]
            ),
            "source_dataset": (
                PICK_INVENTORY_PATH.name
            ),
        }
    )

    output = pd.concat(
        [
            players,
            picks,
        ],
        ignore_index=True,
        sort=False,
    )

    output[
        "optimizer_release"
    ] = RELEASE_NAME

    output[
        "optimizer_release_version"
    ] = SCRIPT_VERSION

    return output.sort_values(
        [
            "asset_team",
            "asset_type",
            "asset_value_score",
            "asset_id",
        ],
        ascending=[
            True,
            True,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def add_player_value(
    frame: pd.DataFrame,
    *,
    player_lookup: pd.DataFrame,
    player_id_column: str,
    output_prefix: str,
) -> pd.DataFrame:
    """Attach canonical player values without Pandas merge suffix collisions."""

    key_column = f"{output_prefix}_player_id_key"

    canonical_columns = {
        "player_name": (
            f"{output_prefix}_player_name_lookup"
        ),
        "current_team_2026_27": (
            f"{output_prefix}_current_team_lookup"
        ),
        "surplus_value_score": (
            f"{output_prefix}_surplus_value_score"
        ),
        "trade_salary_2026_27": (
            f"{output_prefix}_trade_salary_lookup"
        ),
    }

    lookup = player_lookup[
        [
            "player_id_key",
            *canonical_columns.keys(),
        ]
    ].rename(
        columns={
            "player_id_key": key_column,
            **canonical_columns,
        }
    )

    output = frame.copy()

    output[
        key_column
    ] = normalize_id_series(
        output[
            player_id_column
        ]
    )

    collision_renames = {}

    for canonical_column in canonical_columns.values():
        if canonical_column not in output.columns:
            continue

        preserved_column = (
            f"{canonical_column}_runtime_existing"
        )

        suffix_number = 2

        while (
            preserved_column in output.columns
            or preserved_column in collision_renames.values()
        ):
            preserved_column = (
                f"{canonical_column}_runtime_existing_"
                f"{suffix_number}"
            )

            suffix_number += 1

        collision_renames[
            canonical_column
        ] = preserved_column

    if collision_renames:
        output = output.rename(
            columns=collision_renames
        )

    merged = output.merge(
        lookup,
        how="left",
        on=key_column,
        validate="many_to_one",
        suffixes=(
            "",
            "_unexpected_lookup_collision",
        ),
    )

    unexpected_columns = [
        column
        for column in merged.columns
        if column.endswith(
            "_unexpected_lookup_collision"
        )
    ]

    if unexpected_columns:
        raise RuntimeError(
            "Unexpected canonical player-value merge collisions "
            f"for {output_prefix}:\n"
            + "\n".join(
                unexpected_columns
            )
        )

    required_merged_columns = [
        key_column,
        *canonical_columns.values(),
    ]

    missing_columns = [
        column
        for column in required_merged_columns
        if column not in merged.columns
    ]

    if missing_columns:
        raise RuntimeError(
            "Canonical player-value merge did not produce the "
            f"required {output_prefix} columns:\n"
            + "\n".join(
                missing_columns
            )
        )

    return merged


def prepare_one_for_one_base(
    frame: pd.DataFrame,
    player_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    output = frame.copy()

    output = add_player_value(
        output,
        player_lookup=player_lookup,
        player_id_column="player_a_id",
        output_prefix="player_a",
    )

    output = add_player_value(
        output,
        player_lookup=player_lookup,
        player_id_column="player_b_id",
        output_prefix="player_b",
    )

    output[
        "team_a"
    ] = (
        output[
            "team_a"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "team_b"
    ] = (
        output[
            "team_b"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    salary_pass_column = (
        "both_teams_salary_precheck_pass"
    )

    legality_column = first_existing_column(
        output,
        [
            "final_trade_legality_verified",
        ],
    )

    fit_column = select_numeric_signal(
        output,
        preferred=[
            "minimum_team_trade_fit_score",
            "average_team_trade_fit_score",
        ],
        required_terms=[
            "fit",
            "score",
        ],
        excluded_terms=[
            "before",
            "percentile",
            "delta",
        ],
    )

    realism_column = select_numeric_signal(
        output,
        preferred=[
            "realism_adjusted_trade_score_v3",
            "realism_adjusted_trade_score_v2",
            "realism_adjusted_trade_score",
        ],
        required_terms=[
            "realism",
            "score",
        ],
        excluded_terms=[
            "filter",
            "reason",
            "tier",
            "scope",
        ],
    )

    output[
        "base_salary_precheck_passed"
    ] = parse_bool_series(
        output[
            salary_pass_column
        ]
    )

    output[
        "base_final_trade_legality_verified"
    ] = (
        parse_bool_series(
            output[
                legality_column
            ]
        )
        if legality_column
        else False
    )

    output[
        "base_fit_signal"
    ] = (
        pd.to_numeric(
            output[
                fit_column
            ],
            errors="coerce",
        )
        if fit_column
        else np.nan
    )

    output[
        "base_realism_signal"
    ] = (
        pd.to_numeric(
            output[
                realism_column
            ],
            errors="coerce",
        )
        if realism_column
        else np.nan
    )

    output[
        "side_a_player_value_score"
    ] = output[
        "player_a_surplus_value_score"
    ]

    output[
        "side_b_player_value_score"
    ] = output[
        "player_b_surplus_value_score"
    ]

    output[
        "base_package_id"
    ] = (
        output[
            "pair_id"
        ]
        .fillna("")
        .astype(str)
    )

    return (
        output,
        {
            "salary_pass_column": salary_pass_column,
            "legality_column": legality_column,
            "fit_column": fit_column,
            "realism_column": realism_column,
        },
    )


def prepare_two_for_one_base(
    frame: pd.DataFrame,
    player_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    output = frame.copy()

    output = add_player_value(
        output,
        player_lookup=player_lookup,
        player_id_column="one_side_player_id",
        output_prefix="one_side",
    )

    output = add_player_value(
        output,
        player_lookup=player_lookup,
        player_id_column="two_side_player_1_id",
        output_prefix="two_side_player_1",
    )

    output = add_player_value(
        output,
        player_lookup=player_lookup,
        player_id_column="two_side_player_2_id",
        output_prefix="two_side_player_2",
    )

    output[
        "team_sending_one"
    ] = (
        output[
            "team_sending_one"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "team_sending_two"
    ] = (
        output[
            "team_sending_two"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    salary_pass_column = (
        "both_teams_salary_precheck_pass"
    )

    legality_column = first_existing_column(
        output,
        [
            "final_trade_legality_verified",
        ],
    )

    fit_column = select_numeric_signal(
        output,
        preferred=[
            "minimum_team_package_fit_score",
            "average_team_package_fit_score",
        ],
        required_terms=[
            "fit",
            "score",
        ],
        excluded_terms=[
            "before",
            "percentile",
            "delta",
            "penalty",
        ],
    )

    realism_column = select_numeric_signal(
        output,
        preferred=[
            "realism_adjusted_package_score_v2",
            "realism_adjusted_trade_score_v2",
            "package_realism_score_v2",
            "realism_score_v2",
        ],
        required_terms=[
            "realism",
            "score",
        ],
        excluded_terms=[
            "filter",
            "reason",
            "tier",
            "scope",
        ],
    )

    market_similarity_column = first_existing_column(
        output,
        [
            "market_value_similarity_score",
        ],
    )

    output[
        "base_salary_precheck_passed"
    ] = parse_bool_series(
        output[
            salary_pass_column
        ]
    )

    output[
        "base_final_trade_legality_verified"
    ] = (
        parse_bool_series(
            output[
                legality_column
            ]
        )
        if legality_column
        else False
    )

    output[
        "base_fit_signal"
    ] = (
        pd.to_numeric(
            output[
                fit_column
            ],
            errors="coerce",
        )
        if fit_column
        else np.nan
    )

    if realism_column:
        output[
            "base_realism_signal"
        ] = pd.to_numeric(
            output[
                realism_column
            ],
            errors="coerce",
        )

        realism_signal_source = (
            realism_column
        )
    elif market_similarity_column:
        output[
            "base_realism_signal"
        ] = pd.to_numeric(
            output[
                market_similarity_column
            ],
            errors="coerce",
        )

        realism_signal_source = (
            f"proxy:{market_similarity_column}"
        )
    else:
        output[
            "base_realism_signal"
        ] = np.nan

        realism_signal_source = (
            "unavailable"
        )

    output[
        "side_one_player_value_score"
    ] = output[
        "one_side_surplus_value_score"
    ]

    output[
        "side_two_player_value_score"
    ] = (
        output[
            "two_side_player_1_surplus_value_score"
        ]
        + output[
            "two_side_player_2_surplus_value_score"
        ]
    )

    output[
        "base_package_id"
    ] = [
        stable_id(
            row.team_sending_one,
            row.team_sending_two,
            row.one_side_player_id_key,
            row.two_side_player_1_player_id_key,
            row.two_side_player_2_player_id_key,
            prefix="TWO_FOR_ONE",
        )
        for row in output.itertuples(
            index=False
        )
    ]

    return (
        output,
        {
            "salary_pass_column": salary_pass_column,
            "legality_column": legality_column,
            "fit_column": fit_column,
            "realism_column": realism_signal_source,
            "market_similarity_column": (
                market_similarity_column
            ),
        },
    )


def calculate_balance_fields(
    frame: pd.DataFrame,
    *,
    side_a_value_column: str,
    side_b_value_column: str,
    side_a_pick_value_column: str,
    side_b_pick_value_column: str,
) -> pd.DataFrame:
    output = frame.copy()

    output[
        "side_a_total_asset_value_score"
    ] = (
        pd.to_numeric(
            output[
                side_a_value_column
            ],
            errors="coerce",
        )
        + pd.to_numeric(
            output[
                side_a_pick_value_column
            ],
            errors="coerce",
        ).fillna(0.0)
    )

    output[
        "side_b_total_asset_value_score"
    ] = (
        pd.to_numeric(
            output[
                side_b_value_column
            ],
            errors="coerce",
        )
        + pd.to_numeric(
            output[
                side_b_pick_value_column
            ],
            errors="coerce",
        ).fillna(0.0)
    )

    output[
        "base_absolute_value_gap"
    ] = (
        pd.to_numeric(
            output[
                side_a_value_column
            ],
            errors="coerce",
        )
        - pd.to_numeric(
            output[
                side_b_value_column
            ],
            errors="coerce",
        )
    ).abs()

    output[
        "adjusted_absolute_value_gap"
    ] = (
        output[
            "side_a_total_asset_value_score"
        ]
        - output[
            "side_b_total_asset_value_score"
        ]
    ).abs()

    output[
        "value_gap_improvement_score"
    ] = (
        output[
            "base_absolute_value_gap"
        ]
        - output[
            "adjusted_absolute_value_gap"
        ]
    )

    denominator = pd.concat(
        [
            output[
                "side_a_total_asset_value_score"
            ].abs(),
            output[
                "side_b_total_asset_value_score"
            ].abs(),
            pd.Series(
                np.ones(
                    len(output)
                ),
                index=output.index,
            ),
        ],
        axis=1,
    ).max(
        axis=1
    )

    output[
        "relative_value_gap"
    ] = (
        output[
            "adjusted_absolute_value_gap"
        ]
        / denominator
    )

    output[
        "optimizer_value_balance_score"
    ] = (
        100.0
        * (
            1.0
            - output[
                "relative_value_gap"
            ].clip(
                lower=0.0,
                upper=1.0,
            )
        )
    )

    return output


def add_optimizer_score(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    output[
        "fit_signal_percentile"
    ] = percentile_score(
        output[
            "base_fit_signal"
        ]
    )

    output[
        "realism_signal_percentile"
    ] = percentile_score(
        output[
            "base_realism_signal"
        ]
    )

    output[
        "heuristic_optimizer_score_v1"
    ] = (
        0.30
        * output[
            "optimizer_value_balance_score"
        ]
        + 0.25
        * output[
            "fit_signal_percentile"
        ]
        + 0.45
        * output[
            "realism_signal_percentile"
        ]
    )

    output[
        "heuristic_optimizer_score_scope_note"
    ] = (
        "Heuristic rank only: 45% existing realism signal "
        "+ 25% existing fit signal + 30% combined asset-value "
        "balance. Not a causal or acceptance-probability model."
    )

    return output


def slim_one_for_one(
    base: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "base_package_id",
        "pair_id",
        "team_a",
        "team_b",
        "player_a_id_key",
        "player_b_id_key",
        "player_a_player_name_lookup",
        "player_b_player_name_lookup",
        "player_a_trade_salary_lookup",
        "player_b_trade_salary_lookup",
        "side_a_player_value_score",
        "side_b_player_value_score",
        "base_salary_precheck_passed",
        "base_final_trade_legality_verified",
        "base_fit_signal",
        "base_realism_signal",
    ]

    return base[
        columns
    ].copy()


def slim_two_for_one(
    base: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "base_package_id",
        "team_sending_one",
        "team_sending_two",
        "one_side_player_id_key",
        "two_side_player_1_player_id_key",
        "two_side_player_2_player_id_key",
        "one_side_player_name_lookup",
        "two_side_player_1_player_name_lookup",
        "two_side_player_2_player_name_lookup",
        "one_side_trade_salary_lookup",
        "two_side_player_1_trade_salary_lookup",
        "two_side_player_2_trade_salary_lookup",
        "side_one_player_value_score",
        "side_two_player_value_score",
        "base_salary_precheck_passed",
        "base_final_trade_legality_verified",
        "base_fit_signal",
        "base_realism_signal",
    ]

    return base[
        columns
    ].copy()


def attach_single_pick_options(
    *,
    base: pd.DataFrame,
    pick_pool: pd.DataFrame,
    branch: str,
    side_a_team_column: str,
    side_b_team_column: str,
    side_a_value_column: str,
    side_b_value_column: str,
) -> pd.DataFrame:
    eligible = base.loc[
        base[
            "base_salary_precheck_passed"
        ]
    ].copy()

    eligible[
        "underpaying_side"
    ] = np.where(
        pd.to_numeric(
            eligible[
                side_a_value_column
            ],
            errors="coerce",
        )
        <= pd.to_numeric(
            eligible[
                side_b_value_column
            ],
            errors="coerce",
        ),
        "A",
        "B",
    )

    eligible[
        "underpaying_team"
    ] = np.where(
        eligible[
            "underpaying_side"
        ].eq("A"),
        eligible[
            side_a_team_column
        ],
        eligible[
            side_b_team_column
        ],
    )

    pick_columns = [
        "future_pick_right_id",
        "candidate_team",
        "right_display_name",
        "right_structure",
        "candidate_right_value_score",
        "expected_pick_count",
        "tradability_status",
        "source_assets",
        "draft_year_min",
        "draft_year_max",
        "round_numbers",
        "originating_teams",
    ]

    available_pick_columns = [
        column
        for column in pick_columns
        if column in pick_pool.columns
    ]

    expanded = eligible.merge(
        pick_pool[
            available_pick_columns
        ],
        how="inner",
        left_on="underpaying_team",
        right_on="candidate_team",
        validate="many_to_many",
    )

    expanded[
        "side_a_attached_pick_value_score"
    ] = np.where(
        expanded[
            "underpaying_side"
        ].eq("A"),
        expanded[
            "candidate_right_value_score"
        ],
        0.0,
    )

    expanded[
        "side_b_attached_pick_value_score"
    ] = np.where(
        expanded[
            "underpaying_side"
        ].eq("B"),
        expanded[
            "candidate_right_value_score"
        ],
        0.0,
    )

    expanded = calculate_balance_fields(
        expanded,
        side_a_value_column=side_a_value_column,
        side_b_value_column=side_b_value_column,
        side_a_pick_value_column=(
            "side_a_attached_pick_value_score"
        ),
        side_b_pick_value_column=(
            "side_b_attached_pick_value_score"
        ),
    )

    expanded = expanded.loc[
        expanded[
            "value_gap_improvement_score"
        ]
        > VALUE_TOLERANCE
    ].copy()

    expanded = expanded.sort_values(
        [
            "base_package_id",
            "adjusted_absolute_value_gap",
            "candidate_right_value_score",
            "future_pick_right_id",
        ],
        ascending=[
            True,
            True,
            True,
            True,
        ],
    )

    expanded[
        "pick_option_rank_within_base_package"
    ] = (
        expanded.groupby(
            "base_package_id"
        ).cumcount()
        + 1
    )

    expanded = expanded.loc[
        expanded[
            "pick_option_rank_within_base_package"
        ]
        <= MAX_PICK_OPTIONS_PER_BASE_PACKAGE
    ].copy()

    expanded[
        "optimizer_candidate_id"
    ] = [
        stable_id(
            branch,
            row.base_package_id,
            row.future_pick_right_id,
            prefix="MIXED",
        )
        for row in expanded.itertuples(
            index=False
        )
    ]

    expanded[
        "optimizer_branch"
    ] = branch

    expanded[
        "candidate_variant_type"
    ] = (
        "single_pick_attached_to_underpaying_side"
    )

    expanded[
        "attached_pick_side"
    ] = expanded[
        "underpaying_side"
    ]

    expanded[
        "attached_pick_team"
    ] = expanded[
        "underpaying_team"
    ]

    expanded[
        "attached_pick_right_id"
    ] = expanded[
        "future_pick_right_id"
    ]

    expanded[
        "attached_pick_value_score"
    ] = expanded[
        "candidate_right_value_score"
    ]

    expanded[
        "attached_pick_trade_salary"
    ] = 0.0

    expanded[
        "pick_trade_date_legality_verified"
    ] = False

    expanded[
        "optimizer_package_legality_status"
    ] = (
        "requires_trade_date_pick_ownership_stepien_frozen_"
        "and_encumbrance_validation"
    )

    expanded[
        "optimizer_package_final_legal"
    ] = False

    expanded[
        "salary_validation_scope_note"
    ] = (
        "Existing player salary precheck preserved. Future-pick "
        "right contributes zero trade salary."
    )

    expanded = add_optimizer_score(
        expanded
    )

    return expanded.reset_index(
        drop=True
    )


def build_one_for_one_candidates(
    base: pd.DataFrame,
    pick_pool: pd.DataFrame,
) -> pd.DataFrame:
    output = attach_single_pick_options(
        base=slim_one_for_one(base),
        pick_pool=pick_pool,
        branch="one_for_one",
        side_a_team_column="team_a",
        side_b_team_column="team_b",
        side_a_value_column=(
            "side_a_player_value_score"
        ),
        side_b_value_column=(
            "side_b_player_value_score"
        ),
    )

    output[
        "side_a_player_ids"
    ] = output[
        "player_a_id_key"
    ]

    output[
        "side_b_player_ids"
    ] = output[
        "player_b_id_key"
    ]

    output[
        "side_a_player_names"
    ] = output[
        "player_a_player_name_lookup"
    ]

    output[
        "side_b_player_names"
    ] = output[
        "player_b_player_name_lookup"
    ]

    output[
        "side_a_player_trade_salary"
    ] = output[
        "player_a_trade_salary_lookup"
    ]

    output[
        "side_b_player_trade_salary"
    ] = output[
        "player_b_trade_salary_lookup"
    ]

    return output


def build_two_for_one_candidates(
    base: pd.DataFrame,
    pick_pool: pd.DataFrame,
) -> pd.DataFrame:
    output = attach_single_pick_options(
        base=slim_two_for_one(base),
        pick_pool=pick_pool,
        branch="two_for_one",
        side_a_team_column="team_sending_one",
        side_b_team_column="team_sending_two",
        side_a_value_column=(
            "side_one_player_value_score"
        ),
        side_b_value_column=(
            "side_two_player_value_score"
        ),
    )

    output[
        "side_a_player_ids"
    ] = output[
        "one_side_player_id_key"
    ]

    output[
        "side_b_player_ids"
    ] = (
        output[
            "two_side_player_1_player_id_key"
        ]
        + "|"
        + output[
            "two_side_player_2_player_id_key"
        ]
    )

    output[
        "side_a_player_names"
    ] = output[
        "one_side_player_name_lookup"
    ]

    output[
        "side_b_player_names"
    ] = (
        output[
            "two_side_player_1_player_name_lookup"
        ]
        + "|"
        + output[
            "two_side_player_2_player_name_lookup"
        ]
    )

    output[
        "side_a_player_trade_salary"
    ] = output[
        "one_side_trade_salary_lookup"
    ]

    output[
        "side_b_player_trade_salary"
    ] = (
        output[
            "two_side_player_1_trade_salary_lookup"
        ]
        + output[
            "two_side_player_2_trade_salary_lookup"
        ]
    )

    output[
        "team_a"
    ] = output[
        "team_sending_one"
    ]

    output[
        "team_b"
    ] = output[
        "team_sending_two"
    ]

    return output


def select_output_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "optimizer_candidate_id",
        "optimizer_branch",
        "base_package_id",
        "candidate_variant_type",
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "side_a_player_names",
        "side_b_player_names",
        "side_a_player_trade_salary",
        "side_b_player_trade_salary",
        "side_a_player_value_score",
        "side_b_player_value_score",
        "attached_pick_side",
        "attached_pick_team",
        "attached_pick_right_id",
        "right_display_name",
        "right_structure",
        "source_assets",
        "draft_year_min",
        "draft_year_max",
        "round_numbers",
        "originating_teams",
        "expected_pick_count",
        "attached_pick_value_score",
        "attached_pick_trade_salary",
        "base_absolute_value_gap",
        "adjusted_absolute_value_gap",
        "value_gap_improvement_score",
        "relative_value_gap",
        "optimizer_value_balance_score",
        "base_fit_signal",
        "fit_signal_percentile",
        "base_realism_signal",
        "realism_signal_percentile",
        "heuristic_optimizer_score_v1",
        "base_salary_precheck_passed",
        "base_final_trade_legality_verified",
        "pick_trade_date_legality_verified",
        "optimizer_package_final_legal",
        "optimizer_package_legality_status",
        "tradability_status",
        "salary_validation_scope_note",
        "heuristic_optimizer_score_scope_note",
        "pick_option_rank_within_base_package",
    ]

    available = [
        column
        for column in columns
        if column in frame.columns
    ]

    output = frame[
        available
    ].copy()

    output[
        "optimizer_release"
    ] = RELEASE_NAME

    output[
        "optimizer_release_version"
    ] = SCRIPT_VERSION

    return output


def build_team_recommendations(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
) -> pd.DataFrame:
    combined = pd.concat(
        [
            one_for_one,
            two_for_one,
        ],
        ignore_index=True,
        sort=False,
    )

    rows = []

    for side, team_column in [
        (
            "A",
            "team_a",
        ),
        (
            "B",
            "team_b",
        ),
    ]:
        side_rows = combined.copy()

        side_rows[
            "recommendation_team"
        ] = side_rows[
            team_column
        ]

        side_rows[
            "recommendation_team_attaches_pick"
        ] = side_rows[
            "attached_pick_side"
        ].eq(side)

        rows.append(
            side_rows
        )

    recommendations = pd.concat(
        rows,
        ignore_index=True,
        sort=False,
    )

    recommendations = recommendations.sort_values(
        [
            "recommendation_team",
            "heuristic_optimizer_score_v1",
            "value_gap_improvement_score",
            "adjusted_absolute_value_gap",
            "optimizer_candidate_id",
        ],
        ascending=[
            True,
            False,
            False,
            True,
            True,
        ],
    )

    recommendations[
        "recommendation_rank_for_team"
    ] = (
        recommendations.groupby(
            "recommendation_team"
        ).cumcount()
        + 1
    )

    recommendations = recommendations.loc[
        recommendations[
            "recommendation_rank_for_team"
        ]
        <= TOP_RECOMMENDATIONS_PER_TEAM
    ].copy()

    output_columns = [
        "recommendation_team",
        "recommendation_rank_for_team",
        "optimizer_candidate_id",
        "optimizer_branch",
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "attached_pick_team",
        "right_display_name",
        "attached_pick_value_score",
        "value_gap_improvement_score",
        "optimizer_value_balance_score",
        "base_fit_signal",
        "base_realism_signal",
        "heuristic_optimizer_score_v1",
        "recommendation_team_attaches_pick",
        "optimizer_package_legality_status",
        "optimizer_package_final_legal",
    ]

    return recommendations[
        output_columns
    ].reset_index(
        drop=True
    )


def build_branch_summary(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for branch, frame in [
        (
            "one_for_one",
            one_for_one,
        ),
        (
            "two_for_one",
            two_for_one,
        ),
    ]:
        rows.append(
            {
                "optimizer_branch": branch,
                "candidate_rows": int(
                    len(frame)
                ),
                "base_packages_with_pick_options": int(
                    frame[
                        "base_package_id"
                    ].nunique()
                ),
                "teams_represented": int(
                    len(
                        set(
                            frame[
                                "team_a"
                            ]
                        )
                        | set(
                            frame[
                                "team_b"
                            ]
                        )
                    )
                ),
                "unique_attached_pick_rights": int(
                    frame[
                        "attached_pick_right_id"
                    ].nunique()
                ),
                "average_pick_value_score": float(
                    frame[
                        "attached_pick_value_score"
                    ].mean()
                )
                if len(frame)
                else np.nan,
                "average_value_gap_improvement": float(
                    frame[
                        "value_gap_improvement_score"
                    ].mean()
                )
                if len(frame)
                else np.nan,
                "average_value_balance_score": float(
                    frame[
                        "optimizer_value_balance_score"
                    ].mean()
                )
                if len(frame)
                else np.nan,
                "average_heuristic_optimizer_score": float(
                    frame[
                        "heuristic_optimizer_score_v1"
                    ].mean()
                )
                if len(frame)
                else np.nan,
                "final_legal_rows": int(
                    frame[
                        "optimizer_package_final_legal"
                    ].sum()
                ),
                "trade_date_pick_validation_required_rows": int(
                    frame[
                        "optimizer_package_legality_status"
                    ]
                    .eq(
                        "requires_trade_date_pick_ownership_stepien_"
                        "frozen_and_encumbrance_validation"
                    )
                    .sum()
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_team_pick_pool_summary(
    pick_pool: pd.DataFrame,
) -> pd.DataFrame:
    return (
        pick_pool.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            standalone_pick_right_rows=(
                "future_pick_right_id",
                "size",
            ),
            total_pick_value_score=(
                "candidate_right_value_score",
                "sum",
            ),
            average_pick_value_score=(
                "candidate_right_value_score",
                "mean",
            ),
            maximum_pick_value_score=(
                "candidate_right_value_score",
                "max",
            ),
            total_expected_pick_count=(
                "expected_pick_count",
                "sum",
            ),
        )
        .sort_values(
            [
                "total_pick_value_score",
                "candidate_team",
            ],
            ascending=[
                False,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )


def build_validation(
    *,
    inputs: dict[str, pd.DataFrame],
    player_lookup: pd.DataFrame,
    pick_pool: pd.DataFrame,
    unified_assets: pd.DataFrame,
    one_base: pd.DataFrame,
    two_base: pd.DataFrame,
    one_candidates: pd.DataFrame,
    two_candidates: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    combined = pd.concat(
        [
            one_candidates,
            two_candidates,
        ],
        ignore_index=True,
        sort=False,
    )

    one_missing_values = int(
        one_base[
            [
                "player_a_surplus_value_score",
                "player_b_surplus_value_score",
            ]
        ].isna().any(axis=1).sum()
    )

    two_missing_values = int(
        two_base[
            [
                "one_side_surplus_value_score",
                "two_side_player_1_surplus_value_score",
                "two_side_player_2_surplus_value_score",
            ]
        ].isna().any(axis=1).sum()
    )

    duplicate_candidate_ids = int(
        combined[
            "optimizer_candidate_id"
        ].duplicated().sum()
    )

    accounting_only_pick_rows_used = int(
        combined[
            "attached_pick_right_id"
        ].isin(
            inputs[
                "picks"
            ].loc[
                ~parse_bool_series(
                    inputs[
                        "picks"
                    ][
                        "standalone_trade_asset_flag"
                    ]
                ),
                "future_pick_right_id",
            ]
        ).sum()
    )

    pick_team_mismatches = int(
        combined[
            "attached_pick_team"
        ]
        .ne(
            combined[
                "underpaying_team"
            ]
        )
        .sum()
    )

    non_improving_rows = int(
        (
            combined[
                "value_gap_improvement_score"
            ]
            <= VALUE_TOLERANCE
        ).sum()
    )

    nonzero_pick_salary_rows = int(
        (
            combined[
                "attached_pick_trade_salary"
            ].abs()
            > VALUE_TOLERANCE
        ).sum()
    )

    final_legal_pick_rows = int(
        combined[
            "optimizer_package_final_legal"
        ].sum()
    )

    checks = [
        {
            "check_name": "player_value_row_count",
            "observed_value": len(
                inputs[
                    "player_values"
                ]
            ),
            "expected_value": EXPECTED_PLAYER_ROWS,
            "passed": len(
                inputs[
                    "player_values"
                ]
            )
            == EXPECTED_PLAYER_ROWS,
        },
        {
            "check_name": "one_for_one_runtime_row_count",
            "observed_value": len(
                inputs[
                    "one_for_one"
                ]
            ),
            "expected_value": EXPECTED_ONE_FOR_ONE_ROWS,
            "passed": len(
                inputs[
                    "one_for_one"
                ]
            )
            == EXPECTED_ONE_FOR_ONE_ROWS,
        },
        {
            "check_name": "two_for_one_runtime_row_count",
            "observed_value": len(
                inputs[
                    "two_for_one"
                ]
            ),
            "expected_value": EXPECTED_TWO_FOR_ONE_ROWS,
            "passed": len(
                inputs[
                    "two_for_one"
                ]
            )
            == EXPECTED_TWO_FOR_ONE_ROWS,
        },
        {
            "check_name": "future_pick_inventory_row_count",
            "observed_value": len(
                inputs[
                    "picks"
                ]
            ),
            "expected_value": EXPECTED_PICK_ROWS,
            "passed": len(
                inputs[
                    "picks"
                ]
            )
            == EXPECTED_PICK_ROWS,
        },
        {
            "check_name": "standalone_pick_pool_row_count",
            "observed_value": len(
                pick_pool
            ),
            "expected_value": EXPECTED_STANDALONE_PICK_ROWS,
            "passed": len(
                pick_pool
            )
            == EXPECTED_STANDALONE_PICK_ROWS,
        },
        {
            "check_name": "team_salary_profile_row_count",
            "observed_value": len(
                inputs[
                    "team_salary_profiles"
                ]
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": len(
                inputs[
                    "team_salary_profiles"
                ]
            )
            == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "unique_player_value_lookup",
            "observed_value": int(
                player_lookup[
                    "player_id_key"
                ].nunique()
            ),
            "expected_value": EXPECTED_PLAYER_ROWS,
            "passed": (
                player_lookup[
                    "player_id_key"
                ].nunique()
                == EXPECTED_PLAYER_ROWS
            ),
        },
        {
            "check_name": "unified_asset_inventory_rows",
            "observed_value": len(
                unified_assets
            ),
            "expected_value": (
                EXPECTED_PLAYER_ROWS
                + EXPECTED_STANDALONE_PICK_ROWS
            ),
            "passed": len(
                unified_assets
            )
            == (
                EXPECTED_PLAYER_ROWS
                + EXPECTED_STANDALONE_PICK_ROWS
            ),
        },
        {
            "check_name": "one_for_one_missing_player_values",
            "observed_value": one_missing_values,
            "expected_value": 0,
            "passed": one_missing_values
            == 0,
        },
        {
            "check_name": "two_for_one_missing_player_values",
            "observed_value": two_missing_values,
            "expected_value": 0,
            "passed": two_missing_values
            == 0,
        },
        {
            "check_name": "one_for_one_pick_candidates_created",
            "observed_value": len(
                one_candidates
            ),
            "expected_value": ">0",
            "passed": len(
                one_candidates
            )
            > 0,
        },
        {
            "check_name": "two_for_one_pick_candidates_created",
            "observed_value": len(
                two_candidates
            ),
            "expected_value": ">0",
            "passed": len(
                two_candidates
            )
            > 0,
        },
        {
            "check_name": "unique_optimizer_candidate_ids",
            "observed_value": duplicate_candidate_ids,
            "expected_value": 0,
            "passed": duplicate_candidate_ids
            == 0,
        },
        {
            "check_name": "accounting_only_pick_rows_excluded",
            "observed_value": accounting_only_pick_rows_used,
            "expected_value": 0,
            "passed": accounting_only_pick_rows_used
            == 0,
        },
        {
            "check_name": "attached_pick_team_matches_underpaying_team",
            "observed_value": pick_team_mismatches,
            "expected_value": 0,
            "passed": pick_team_mismatches
            == 0,
        },
        {
            "check_name": "all_pick_options_improve_value_gap",
            "observed_value": non_improving_rows,
            "expected_value": 0,
            "passed": non_improving_rows
            == 0,
        },
        {
            "check_name": "future_picks_contribute_zero_salary",
            "observed_value": nonzero_pick_salary_rows,
            "expected_value": 0,
            "passed": nonzero_pick_salary_rows
            == 0,
        },
        {
            "check_name": "pick_packages_not_marked_final_legal",
            "observed_value": final_legal_pick_rows,
            "expected_value": 0,
            "passed": final_legal_pick_rows
            == 0,
        },
        {
            "check_name": "team_recommendations_created",
            "observed_value": len(
                recommendations
            ),
            "expected_value": ">0",
            "passed": len(
                recommendations
            )
            > 0,
        },
        {
            "check_name": "all_teams_have_recommendations",
            "observed_value": int(
                recommendations[
                    "recommendation_team"
                ].nunique()
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": (
                recommendations[
                    "recommendation_team"
                ].nunique()
                == EXPECTED_TEAM_ROWS
            ),
        },
    ]

    return pd.DataFrame(
        checks
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK OPTIMIZER")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/9] Loading validated runtime artifacts")
    inputs = load_inputs()

    print("[2/9] Preparing player and pick asset inventories")
    player_lookup = prepare_player_lookup(
        inputs[
            "player_values"
        ]
    )

    pick_pool = prepare_pick_pool(
        inputs[
            "picks"
        ]
    )

    unified_assets = build_unified_asset_inventory(
        player_lookup,
        pick_pool,
    )

    print("[3/9] Joining player values to one-for-one runtime")
    (
        one_base,
        one_signal_columns,
    ) = prepare_one_for_one_base(
        inputs[
            "one_for_one"
        ],
        player_lookup,
    )

    print("[4/9] Joining player values to two-for-one runtime")
    (
        two_base,
        two_signal_columns,
    ) = prepare_two_for_one_base(
        inputs[
            "two_for_one"
        ],
        player_lookup,
    )

    print("[5/9] Generating one-for-one single-pick options")
    one_candidates = build_one_for_one_candidates(
        one_base,
        pick_pool,
    )

    one_candidates = select_output_columns(
        one_candidates
    )

    print("[6/9] Generating two-for-one single-pick options")
    two_candidates = build_two_for_one_candidates(
        two_base,
        pick_pool,
    )

    two_candidates = select_output_columns(
        two_candidates
    )

    print("[7/9] Ranking team recommendations")
    recommendations = build_team_recommendations(
        one_candidates,
        two_candidates,
    )

    branch_summary = build_branch_summary(
        one_candidates,
        two_candidates,
    )

    team_pick_summary = build_team_pick_pool_summary(
        pick_pool
    )

    print("[8/9] Validating optimizer outputs")
    validation = build_validation(
        inputs=inputs,
        player_lookup=player_lookup,
        pick_pool=pick_pool,
        unified_assets=unified_assets,
        one_base=one_base,
        two_base=two_base,
        one_candidates=one_candidates,
        two_candidates=two_candidates,
        recommendations=recommendations,
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    unified_assets.to_parquet(
        UNIFIED_ASSET_INVENTORY_PATH,
        index=False,
    )

    one_candidates.to_parquet(
        ONE_FOR_ONE_CANDIDATES_PATH,
        index=False,
    )

    two_candidates.to_parquet(
        TWO_FOR_ONE_CANDIDATES_PATH,
        index=False,
    )

    recommendations.to_csv(
        TOP_TEAM_RECOMMENDATIONS_PATH,
        index=False,
    )

    branch_summary.to_csv(
        BRANCH_SUMMARY_PATH,
        index=False,
    )

    team_pick_summary.to_csv(
        TEAM_PICK_POOL_SUMMARY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "scope": (
            "Single standalone future-pick right attached to the "
            "underpaying side of an existing salary-approved player "
            "package."
        ),
        "player_asset_rows": int(
            len(player_lookup)
        ),
        "standalone_pick_asset_rows": int(
            len(pick_pool)
        ),
        "unified_asset_rows": int(
            len(unified_assets)
        ),
        "one_for_one_base_rows": int(
            len(one_base)
        ),
        "one_for_one_candidate_rows": int(
            len(one_candidates)
        ),
        "two_for_one_base_rows": int(
            len(two_base)
        ),
        "two_for_one_candidate_rows": int(
            len(two_candidates)
        ),
        "team_recommendation_rows": int(
            len(recommendations)
        ),
        "teams_with_recommendations": int(
            recommendations[
                "recommendation_team"
            ].nunique()
        ),
        "max_pick_options_per_base_package": (
            MAX_PICK_OPTIONS_PER_BASE_PACKAGE
        ),
        "top_recommendations_per_team": (
            TOP_RECOMMENDATIONS_PER_TEAM
        ),
        "one_for_one_signal_columns": (
            one_signal_columns
        ),
        "two_for_one_signal_columns": (
            two_signal_columns
        ),
        "validation_checks": int(
            len(validation)
        ),
        "validation_checks_passed": int(
            validation[
                "passed"
            ].sum()
        ),
        "optimizer_release_valid": bool(
            failed.empty
        ),
        "legal_scope_note": (
            "No pick-attached package is marked finally legal. "
            "Trade-date ownership, Stepien, frozen-pick, protection, "
            "encumbrance, and other CBA checks remain required."
        ),
        "output_files": {
            "unified_asset_inventory": str(
                UNIFIED_ASSET_INVENTORY_PATH
            ),
            "one_for_one_candidates": str(
                ONE_FOR_ONE_CANDIDATES_PATH
            ),
            "two_for_one_candidates": str(
                TWO_FOR_ONE_CANDIDATES_PATH
            ),
            "team_recommendations": str(
                TOP_TEAM_RECOMMENDATIONS_PATH
            ),
            "branch_summary": str(
                BRANCH_SUMMARY_PATH
            ),
            "team_pick_pool_summary": str(
                TEAM_PICK_POOL_SUMMARY_PATH
            ),
            "validation": str(
                VALIDATION_PATH
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

    print("[9/9] Optimizer outputs saved")
    print()

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK OPTIMIZER CREATED")
    print("=" * 80)
    print(
        "Unified asset rows: "
        f"{len(unified_assets):,}"
    )
    print(
        "One-for-one pick candidates: "
        f"{len(one_candidates):,}"
    )
    print(
        "Two-for-one pick candidates: "
        f"{len(two_candidates):,}"
    )
    print(
        "Team recommendation rows: "
        f"{len(recommendations):,}"
    )
    print(
        "Teams with recommendations: "
        f"{recommendations['recommendation_team'].nunique():,}"
        f"/{EXPECTED_TEAM_ROWS}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Optimizer release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("SIGNAL COLUMNS")
    print(
        "One-for-one fit: "
        f"{one_signal_columns['fit_column']}"
    )
    print(
        "One-for-one realism: "
        f"{one_signal_columns['realism_column']}"
    )
    print(
        "Two-for-one fit: "
        f"{two_signal_columns['fit_column']}"
    )
    print(
        "Two-for-one realism: "
        f"{two_signal_columns['realism_column']}"
    )
    print()

    print("BRANCH SUMMARY")
    display_summary = branch_summary.copy()

    for column in [
        "average_pick_value_score",
        "average_value_gap_improvement",
        "average_value_balance_score",
        "average_heuristic_optimizer_score",
    ]:
        display_summary[
            column
        ] = pd.to_numeric(
            display_summary[
                column
            ],
            errors="coerce",
        ).round(6)

    print(
        display_summary.to_string(
            index=False
        )
    )
    print()

    print("VALIDATION")
    print(
        validation.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")

    for path in [
        UNIFIED_ASSET_INVENTORY_PATH,
        ONE_FOR_ONE_CANDIDATES_PATH,
        TWO_FOR_ONE_CANDIDATES_PATH,
        TOP_TEAM_RECOMMENDATIONS_PATH,
        BRANCH_SUMMARY_PATH,
        TEAM_PICK_POOL_SUMMARY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        raise RuntimeError(
            "Mixed player-and-pick optimizer failed validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()