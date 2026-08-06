from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-cle-min-uta-2027-three-way-pool-integration-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SIMULATION_BANK_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_draft_pick_simulation_bank_2027_2029_v3_floor_corrected.npz"
)

PICK_CURVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.parquet"
)

PICK_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_originating_team_pick_values_2027_2029_v3_floor_corrected.parquet"
)

CLAIMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_obligation_claims_2027_2029_v3_floor_corrected.parquet"
)

V8_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v8_denver_joint_enriched.parquet"
)

V8_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v8_denver_joint_provisional.csv"
)

GROUP_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_cle_min_2027_group_claims_v1.csv"
)

GROUP_METADATA_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_cle_min_2027_group_diagnostic_metadata_v1.json"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_cle_min_uta_2027_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_cle_min_uta_2027_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_cle_min_uta_2027_candidate_rights_v1.csv"
)

V9_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v9_cle_min_uta_pool_enriched.parquet"
)

V9_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v9_cle_min_uta_pool_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_team_adjustments_v1.csv"
)

V9_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v9_cle_min_uta_pool_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_source_reconciliation_v1.csv"
)

POOL_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_pool_reconciliation_v1.csv"
)

SELECTION_BREAKDOWN_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_selection_breakdown_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_uta_2027_pool_metadata_v1.json"
)


OBLIGATION_GROUP_ID = "OBL_a1a4abc01bb0"

DRAFT_YEAR = 2027
ROUND_NUMBER = 1

SOURCE_ASSETS = {
    "2027_R1_CLE": (
        2027,
        1,
        "CLE",
    ),
    "2027_R1_MIN": (
        2027,
        1,
        "MIN",
    ),
    "2027_R1_UTA": (
        2027,
        1,
        "UTA",
    ),
}

SOURCE_TEAMS = [
    "CLE",
    "MIN",
    "UTA",
]

CANDIDATE_TEAMS = [
    "MEM",
    "UTA",
    "PHX",
]

GROUP_CLAIM_IDS = {
    "2027_R1_CLE_C1",
    "2027_R1_MIN_C1",
}

EXPECTED_SOURCE_TEXT_FRAGMENTS = [
    "Memphis will receive the most favorable",
    "Utah's 2027 1st round pick barred from selections 1 through 5",
    "Cleveland's 2027 1st round pick",
    "Minnesota's 2027 1st round pick",
    "Utah will receive the second most favorable",
    "Phoenix will receive the least favorable",
]


def normalize_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    output.columns = [
        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        for column in output.columns
    ]

    return output


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
            + "\n".join(
                missing
            )
        )


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(
        value,
        float,
    ) and np.isnan(
        value
    ):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(
            value
        ),
    ).strip()


def numeric_value(
    value: Any,
) -> float:
    return float(
        pd.to_numeric(
            pd.Series(
                [
                    value
                ]
            ),
            errors="coerce",
        ).iloc[
            0
        ]
    )


def finite_or_zero(
    value: Any,
) -> float:
    number = numeric_value(
        value
    )

    if np.isfinite(
        number
    ):
        return number

    return 0.0


def json_safe(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): json_safe(
                item
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            json_safe(
                item
            )
            for item in value
        ]

    if isinstance(
        value,
        np.integer,
    ):
        return int(
            value
        )

    if isinstance(
        value,
        np.floating,
    ):
        if np.isnan(
            value
        ):
            return None

        return float(
            value
        )

    if isinstance(
        value,
        float,
    ):
        if math.isnan(
            value
        ):
            return None

        return value

    if pd.isna(
        value
    ):
        return None

    return value


class SimulationBank:
    def __init__(
        self,
        path: Path,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(
                "Simulation bank was not found:\n"
                f"{path}"
            )

        self.archive = np.load(
            path,
            allow_pickle=False,
        )

        self.teams = [
            str(
                value
            )
            for value in self.archive[
                "team_abbreviations"
            ].tolist()
        ]

        self.team_to_index = {
            team: index
            for index, team in enumerate(
                self.teams
            )
        }

        self.simulation_ids = self.archive[
            "simulation_ids"
        ].astype(
            int
        )

        missing = sorted(
            set(
                SOURCE_TEAMS
            )
            - set(
                self.teams
            )
        )

        if missing:
            raise ValueError(
                "Simulation bank is missing required teams:\n"
                + "\n".join(
                    missing
                )
            )

    def slots(
        self,
        draft_year: int,
        round_number: int,
        team: str,
    ) -> np.ndarray:
        prefix = (
            "first_round"
            if int(
                round_number
            )
            == 1
            else "second_round"
        )

        key = (
            f"{prefix}_{int(draft_year)}"
        )

        if key not in self.archive.files:
            raise KeyError(
                f"Simulation array was not found: {key}"
            )

        return self.archive[
            key
        ][
            :,
            self.team_to_index[
                str(
                    team
                )
            ],
        ].astype(
            int
        )

    def close(
        self,
    ) -> None:
        self.archive.close()


class SlotValueLookup:
    def __init__(
        self,
        curve: pd.DataFrame,
    ) -> None:
        maximum_pick = int(
            curve[
                "overall_pick"
            ].max()
        )

        self.value = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        self.rating = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        for row in curve.itertuples(
            index=False
        ):
            pick = int(
                row.overall_pick
            )

            self.value[
                pick
            ] = float(
                row.historical_pick_value_score
            )

            self.rating[
                pick
            ] = float(
                row.historical_pick_value_rating_60_99
            )

        if np.isnan(
            self.value[
                1:
            ]
        ).any():
            raise ValueError(
                "Historical pick-value lookup is incomplete."
            )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        V8_VALUATIONS_PATH,
        V8_TEAM_SUMMARY_PATH,
        GROUP_CLAIMS_PATH,
        GROUP_METADATA_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required CLE-MIN-UTA pool input was not found:\n"
                f"{path}"
            )

    curve = normalize_columns(
        pd.read_parquet(
            PICK_CURVE_PATH
        )
    )

    pick_values = normalize_columns(
        pd.read_parquet(
            PICK_VALUES_PATH
        )
    )

    claims = normalize_columns(
        pd.read_parquet(
            CLAIMS_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            V8_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V8_TEAM_SUMMARY_PATH
        )
    )

    group_claims = normalize_columns(
        pd.read_csv(
            GROUP_CLAIMS_PATH
        )
    )

    with GROUP_METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        group_metadata = json.load(
            file
        )

    require_columns(
        curve,
        [
            "overall_pick",
            "historical_pick_value_score",
            "historical_pick_value_rating_60_99",
        ],
        "Historical pick-value curve",
    )

    require_columns(
        pick_values,
        [
            "draft_year",
            "round_number",
            "originating_team",
            "time_discount_factor",
            "time_discounted_pick_value_score",
        ],
        "V3 originating-team pick values",
    )

    require_columns(
        claims,
        [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "claim_type",
            "resolution_status",
        ],
        "V3 obligation claims",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
        ],
        "V8 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_denver_joint_integration_provisional"
            ),
        ],
        "V8 provisional team summary",
    )

    require_columns(
        group_claims,
        [
            "claim_id",
            "asset_key",
            "full_obligation_text",
            "joint_value_ready",
        ],
        "CLE-MIN group diagnostic claims",
    )

    if clean_text(
        group_metadata.get(
            "target_group_id",
            "",
        )
    ) != OBLIGATION_GROUP_ID:
        raise ValueError(
            "Group metadata does not describe the configured obligation."
        )

    if not bool(
        group_metadata.get(
            "joint_value_ready",
            False,
        )
    ):
        raise RuntimeError(
            "The group diagnostic did not mark joint valuation as ready."
        )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        group_claims,
    )


def validate_source_text(
    group_claims: pd.DataFrame,
) -> str:
    claim_ids = set(
        group_claims[
            "claim_id"
        ].astype(
            str
        )
    )

    if claim_ids != GROUP_CLAIM_IDS:
        raise ValueError(
            "Group diagnostic claim IDs changed. Expected:\n"
            + "\n".join(
                sorted(
                    GROUP_CLAIM_IDS
                )
            )
        )

    texts = sorted(
        {
            clean_text(
                value
            )
            for value in group_claims[
                "full_obligation_text"
            ]
            if clean_text(
                value
            )
        },
        key=len,
        reverse=True,
    )

    if not texts:
        raise ValueError(
            "No canonical obligation text was available."
        )

    canonical_text = texts[
        0
    ]

    missing = [
        fragment
        for fragment in EXPECTED_SOURCE_TEXT_FRAGMENTS
        if fragment.lower()
        not in canonical_text.lower()
    ]

    if missing:
        raise ValueError(
            "Canonical obligation text is missing expected clauses:\n"
            + "\n".join(
                missing
            )
        )

    return canonical_text


def build_discount_lookup(
    pick_values: pd.DataFrame,
) -> dict[str, float]:
    output = {}

    for asset_key, (
        draft_year,
        round_number,
        team,
    ) in SOURCE_ASSETS.items():
        match = pick_values.loc[
            pd.to_numeric(
                pick_values[
                    "draft_year"
                ],
                errors="coerce",
            ).eq(
                draft_year
            )
            & pd.to_numeric(
                pick_values[
                    "round_number"
                ],
                errors="coerce",
            ).eq(
                round_number
            )
            & pick_values[
                "originating_team"
            ].astype(
                str
            ).eq(
                team
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                "Expected one originating-team value row for "
                f"{asset_key}; found {len(match)}."
            )

        output[
            asset_key
        ] = numeric_value(
            match.iloc[
                0
            ][
                "time_discount_factor"
            ]
        )

    unique_discounts = {
        round(
            value,
            12,
        )
        for value in output.values()
    }

    if len(
        unique_discounts
    ) != 1:
        raise ValueError(
            "The three 2027 first-round assets do not share one "
            "time-discount factor."
        )

    return output


def unconditional_value_lookup(
    pick_values: pd.DataFrame,
) -> dict[str, float]:
    output = {}

    for asset_key, (
        draft_year,
        round_number,
        team,
    ) in SOURCE_ASSETS.items():
        match = pick_values.loc[
            pd.to_numeric(
                pick_values[
                    "draft_year"
                ],
                errors="coerce",
            ).eq(
                draft_year
            )
            & pd.to_numeric(
                pick_values[
                    "round_number"
                ],
                errors="coerce",
            ).eq(
                round_number
            )
            & pick_values[
                "originating_team"
            ].astype(
                str
            ).eq(
                team
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                f"Missing unconditional value for {asset_key}."
            )

        output[
            asset_key
        ] = numeric_value(
            match.iloc[
                0
            ][
                "time_discounted_pick_value_score"
            ]
        )

    return output


def evaluate_pool(
    bank: SimulationBank,
    lookup: SlotValueLookup,
    discounts: dict[str, float],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    slots = {
        asset_key: bank.slots(
            draft_year=draft_year,
            round_number=round_number,
            team=team,
        )
        for asset_key, (
            draft_year,
            round_number,
            team,
        ) in SOURCE_ASSETS.items()
    }

    simulation_count = len(
        bank.simulation_ids
    )

    if any(
        len(
            values
        )
        != simulation_count
        for values in slots.values()
    ):
        raise ValueError(
            "Pool simulation arrays do not align."
        )

    uta_top_five = (
        slots[
            "2027_R1_UTA"
        ]
        <= 5
    )

    uta_top_five_violations = int(
        uta_top_five.sum()
    )

    if uta_top_five_violations != 0:
        raise RuntimeError(
            "The V3 simulation bank contains Utah 2027 top-five "
            "outcomes even though the obligation source states that "
            "Utah's pick is barred from selections 1-5. "
            f"Violations: {uta_top_five_violations:,}"
        )

    asset_keys = np.array(
        list(
            SOURCE_ASSETS.keys()
        ),
        dtype="U11",
    )

    slot_matrix = np.column_stack(
        [
            slots[
                asset_key
            ]
            for asset_key in asset_keys
        ]
    )

    ordered_indices = np.argsort(
        slot_matrix,
        axis=1,
    )

    most_favorable_source = asset_keys[
        ordered_indices[
            :,
            0
        ]
    ]

    second_favorable_source = asset_keys[
        ordered_indices[
            :,
            1
        ]
    ]

    least_favorable_source = asset_keys[
        ordered_indices[
            :,
            2
        ]
    ]

    owner_by_rank = {
        "MEM": (
            most_favorable_source
        ),
        "UTA": (
            second_favorable_source
        ),
        "PHX": (
            least_favorable_source
        ),
    }

    owners = {
        asset_key: np.full(
            simulation_count,
            "",
            dtype="U3",
        )
        for asset_key in SOURCE_ASSETS
    }

    for candidate_team, selected_sources in owner_by_rank.items():
        for asset_key in SOURCE_ASSETS:
            owners[
                asset_key
            ][
                selected_sources
                == asset_key
            ] = candidate_team

    discounted_values = {
        asset_key: (
            lookup.value[
                slots[
                    asset_key
                ]
            ]
            * discounts[
                asset_key
            ]
        )
        for asset_key in SOURCE_ASSETS
    }

    allocation_rows = []

    reconciliation_rows = []

    for asset_key, owner_array in owners.items():
        if np.any(
            owner_array
            == ""
        ):
            raise RuntimeError(
                f"At least one {asset_key} simulation lacks an owner."
            )

        source_value_sum = 0.0

        for candidate_team in CANDIDATE_TEAMS:
            condition = (
                owner_array
                == candidate_team
            )

            expected_value = float(
                np.mean(
                    np.where(
                        condition,
                        discounted_values[
                            asset_key
                        ],
                        0.0,
                    )
                )
            )

            source_value_sum += expected_value

            allocation_rows.append(
                {
                    "obligation_group_id": (
                        OBLIGATION_GROUP_ID
                    ),
                    "source_asset_key": (
                        asset_key
                    ),
                    "source_team": (
                        SOURCE_ASSETS[
                            asset_key
                        ][
                            2
                        ]
                    ),
                    "candidate_team": (
                        candidate_team
                    ),
                    "allocation_probability": float(
                        np.mean(
                            condition
                        )
                    ),
                    "expected_allocated_value_score": (
                        expected_value
                    ),
                    "expected_pick_when_allocated": (
                        float(
                            np.mean(
                                slots[
                                    asset_key
                                ][
                                    condition
                                ]
                            )
                        )
                        if np.any(
                            condition
                        )
                        else np.nan
                    ),
                    "simulation_count": (
                        simulation_count
                    ),
                }
            )

        unconditional_value = float(
            np.mean(
                discounted_values[
                    asset_key
                ]
            )
        )

        reconciliation_rows.append(
            {
                "source_asset_key": (
                    asset_key
                ),
                "unconditional_asset_value_score": (
                    unconditional_value
                ),
                "allocated_value_sum": (
                    source_value_sum
                ),
                "allocation_value_difference": (
                    source_value_sum
                    - unconditional_value
                ),
                "allocation_probability_sum": float(
                    sum(
                        np.mean(
                            owner_array
                            == candidate_team
                        )
                        for candidate_team in CANDIDATE_TEAMS
                    )
                ),
                "allocation_reconciliation_passed": (
                    abs(
                        source_value_sum
                        - unconditional_value
                    )
                    <= 1e-8
                ),
            }
        )

    source_allocations = pd.DataFrame(
        allocation_rows
    )

    source_reconciliation = pd.DataFrame(
        reconciliation_rows
    )

    candidate_rights = (
        source_allocations.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            expected_candidate_right_value_score=(
                "expected_allocated_value_score",
                "sum",
            ),
            expected_source_pick_count=(
                "allocation_probability",
                "sum",
            ),
            source_asset_count=(
                "source_asset_key",
                "nunique",
            ),
        )
    )

    candidate_rights[
        "right_description"
    ] = candidate_rights[
        "candidate_team"
    ].map(
        {
            "MEM": (
                "most favorable of UTA, CLE, and MIN 2027 firsts"
            ),
            "UTA": (
                "second-most favorable of UTA, CLE, and MIN 2027 firsts"
            ),
            "PHX": (
                "least favorable of UTA, CLE, and MIN 2027 firsts"
            ),
        }
    )

    rank_sources = {
        "MEM": (
            most_favorable_source
        ),
        "UTA": (
            second_favorable_source
        ),
        "PHX": (
            least_favorable_source
        ),
    }

    selection_rows = []

    for candidate_team, selected_sources in rank_sources.items():
        for asset_key in SOURCE_ASSETS:
            condition = (
                selected_sources
                == asset_key
            )

            selection_rows.append(
                {
                    "candidate_team": (
                        candidate_team
                    ),
                    "rank_right": (
                        {
                            "MEM": (
                                "most_favorable"
                            ),
                            "UTA": (
                                "second_most_favorable"
                            ),
                            "PHX": (
                                "least_favorable"
                            ),
                        }[
                            candidate_team
                        ]
                    ),
                    "selected_source_asset_key": (
                        asset_key
                    ),
                    "selection_probability": float(
                        np.mean(
                            condition
                        )
                    ),
                    "expected_pick_when_selected": (
                        float(
                            np.mean(
                                slots[
                                    asset_key
                                ][
                                    condition
                                ]
                            )
                        )
                        if np.any(
                            condition
                        )
                        else np.nan
                    ),
                    "expected_value_component_score": float(
                        np.mean(
                            np.where(
                                condition,
                                discounted_values[
                                    asset_key
                                ],
                                0.0,
                            )
                        )
                    ),
                }
            )

    selection_breakdown = pd.DataFrame(
        selection_rows
    )

    pool_reconciliation = pd.DataFrame(
        [
            {
                "obligation_group_id": (
                    OBLIGATION_GROUP_ID
                ),
                "joint_simulation_count": (
                    simulation_count
                ),
                "utah_top_five_violation_count": (
                    uta_top_five_violations
                ),
                "total_source_asset_value_score": float(
                    source_allocations[
                        "expected_allocated_value_score"
                    ].sum()
                ),
                "total_candidate_right_value_score": float(
                    candidate_rights[
                        "expected_candidate_right_value_score"
                    ].sum()
                ),
                "candidate_pick_count_sum": float(
                    candidate_rights[
                        "expected_source_pick_count"
                    ].sum()
                ),
                "value_difference": float(
                    candidate_rights[
                        "expected_candidate_right_value_score"
                    ].sum()
                    - source_allocations[
                        "expected_allocated_value_score"
                    ].sum()
                ),
                "pool_reconciliation_passed": bool(
                    abs(
                        candidate_rights[
                            "expected_candidate_right_value_score"
                        ].sum()
                        - source_allocations[
                            "expected_allocated_value_score"
                        ].sum()
                    )
                    <= 1e-8
                    and abs(
                        candidate_rights[
                            "expected_source_pick_count"
                        ].sum()
                        - 3.0
                    )
                    <= 1e-12
                    and uta_top_five_violations
                    == 0
                ),
            }
        ]
    )

    return (
        source_allocations,
        source_reconciliation,
        candidate_rights,
        selection_breakdown,
        pool_reconciliation,
    )


def build_baseline_audit(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    affected_claims = claims.loc[
        claims[
            "asset_key"
        ].astype(
            str
        ).isin(
            SOURCE_ASSETS.keys()
        )
    ].copy()

    valuation_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
        ]
        if column in valuations.columns
    ]

    audit = affected_claims.merge(
        valuations[
            valuation_columns
        ].drop_duplicates(
            subset=[
                "claim_id"
            ]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    unexpected_valued = audit.loc[
        audit[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).str.startswith(
            "valued_"
        )
        & ~audit[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    if not unexpected_valued.empty:
        raise RuntimeError(
            "An affected source asset is already represented by a "
            "non-direct valued claim. Review this overlap before "
            "integration:\n"
            + unexpected_valued[
                [
                    "claim_id",
                    "asset_key",
                    "valuation_method",
                    "valuation_status",
                ]
            ].to_string(
                index=False
            )
        )

    contribution_rows = []

    direct_rows = audit.loc[
        audit[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    for row in direct_rows.itertuples(
        index=False
    ):
        team = clean_text(
            getattr(
                row,
                "candidate_beneficiary_team",
                "",
            )
        )

        value = finite_or_zero(
            getattr(
                row,
                "expected_total_candidate_asset_value_score",
                np.nan,
            )
        )

        if team and value:
            contribution_rows.append(
                {
                    "claim_id": (
                        row.claim_id
                    ),
                    "asset_key": (
                        row.asset_key
                    ),
                    "team": (
                        team
                    ),
                    "current_baseline_value_score": (
                        value
                    ),
                    "baseline_component_type": (
                        "direct_asset"
                    ),
                }
            )

    contributions = pd.DataFrame(
        contribution_rows,
        columns=[
            "claim_id",
            "asset_key",
            "team",
            "current_baseline_value_score",
            "baseline_component_type",
        ],
    )

    return (
        audit,
        contributions,
    )


def build_team_adjustments(
    candidate_rights: pd.DataFrame,
    baseline_contributions: pd.DataFrame,
) -> pd.DataFrame:
    new_values = (
        candidate_rights.set_index(
            "candidate_team"
        )[
            "expected_candidate_right_value_score"
        ].to_dict()
    )

    baseline_values = (
        baseline_contributions.groupby(
            "team"
        )[
            "current_baseline_value_score"
        ].sum().to_dict()
        if not baseline_contributions.empty
        else {}
    )

    teams = sorted(
        set(
            CANDIDATE_TEAMS
        )
        | set(
            baseline_values
        )
    )

    rows = []

    for team in teams:
        new_value = float(
            new_values.get(
                team,
                0.0,
            )
        )

        baseline = float(
            baseline_values.get(
                team,
                0.0,
            )
        )

        rows.append(
            {
                "team": (
                    team
                ),
                "cle_min_uta_pool_right_value_score": (
                    new_value
                ),
                "existing_counted_baseline_value_score": (
                    baseline
                ),
                "net_team_adjustment_value_score": (
                    new_value
                    - baseline
                ),
                "adjustment_scope": (
                    "replace_existing_source_asset_accounting_with_joint_pool_right"
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def update_team_summary(
    team_summary: pd.DataFrame,
    adjustments: pd.DataFrame,
) -> pd.DataFrame:
    output = team_summary.copy()

    base_column = (
        "candidate_total_pick_asset_value_score_"
        "after_denver_joint_integration_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_cle_min_uta_pool"
    ] = pd.to_numeric(
        output[
            base_column
        ],
        errors="coerce",
    )

    adjustment_lookup = (
        adjustments.set_index(
            "team"
        )[
            "net_team_adjustment_value_score"
        ].to_dict()
    )

    output[
        "cle_min_uta_2027_pool_adjustment_value_score"
    ] = (
        output[
            "candidate_beneficiary_team"
        ].astype(
            str
        ).map(
            adjustment_lookup
        ).fillna(
            0.0
        )
    )

    output[
        "candidate_total_pick_asset_value_score_after_cle_min_uta_pool_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_cle_min_uta_pool"
        ]
        + output[
            "cle_min_uta_2027_pool_adjustment_value_score"
        ]
    )

    output[
        "cle_min_uta_2027_pool_status"
    ] = (
        "fully_allocated_three_pick_favorability_pool"
    )

    output[
        "cle_min_uta_2027_pool_scope_note"
    ] = (
        "Utah, Cleveland, and Minnesota's 2027 first-round picks are "
        "ranked on aligned simulation rows. Memphis receives the most "
        "favorable, Utah the second-most favorable, and Phoenix the least "
        "favorable pick. Utah's previous standalone source value is "
        "replaced rather than counted twice."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_cle_min_uta_pool_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    added_defaults = {
        "cle_min_uta_pool_modeled_flag": False,
        "cle_min_uta_pool_group_id": "",
        "cle_min_uta_source_asset_value_score": np.nan,
        "cle_min_uta_candidate_allocations_json": "",
    }

    for column, default in added_defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    affected_claims = claims.loc[
        claims[
            "asset_key"
        ].astype(
            str
        ).isin(
            SOURCE_ASSETS.keys()
        )
    ][
        [
            "claim_id",
            "asset_key",
        ]
    ].copy()

    claim_to_asset = (
        affected_claims.set_index(
            "claim_id"
        )[
            "asset_key"
        ].to_dict()
    )

    for claim_id, asset_key in claim_to_asset.items():
        mask = output[
            "claim_id"
        ].astype(
            str
        ).eq(
            str(
                claim_id
            )
        )

        if int(
            mask.sum()
        ) != 1:
            raise ValueError(
                f"Expected one valuation row for {claim_id}."
            )

        source_rows = source_allocations.loc[
            source_allocations[
                "source_asset_key"
            ].eq(
                asset_key
            )
        ]

        allocation_json = json.dumps(
            {
                str(
                    row.candidate_team
                ): float(
                    row.expected_allocated_value_score
                )
                for row in source_rows.itertuples(
                    index=False
                )
            },
            sort_keys=True,
        )

        source_value = float(
            source_rows[
                "expected_allocated_value_score"
            ].sum()
        )

        output.loc[
            mask,
            "valuation_method",
        ] = (
            "joint_three_pick_favorability_pool_source_allocation"
        )

        output.loc[
            mask,
            "valuation_status",
        ] = (
            "valued_source_asset_fully_allocated"
        )

        output.loc[
            mask,
            "candidate_beneficiary_team",
        ] = ""

        output.loc[
            mask,
            "cle_min_uta_pool_modeled_flag",
        ] = True

        output.loc[
            mask,
            "cle_min_uta_pool_group_id",
        ] = (
            OBLIGATION_GROUP_ID
        )

        output.loc[
            mask,
            "cle_min_uta_source_asset_value_score",
        ] = source_value

        output.loc[
            mask,
            "cle_min_uta_candidate_allocations_json",
        ] = allocation_json

        if (
            "expected_total_candidate_asset_value_score"
            in output.columns
        ):
            output.loc[
                mask,
                "expected_total_candidate_asset_value_score",
            ] = np.nan

        if (
            "automatic_exclusion_reason"
            in output.columns
        ):
            output.loc[
                mask,
                "automatic_exclusion_reason",
            ] = ""

        if (
            "valuation_scope_note"
            in output.columns
        ):
            output.loc[
                mask,
                "valuation_scope_note",
            ] = (
                "This physical pick is fully allocated through the "
                "CLE-MIN-UTA 2027 three-way favorability pool. Candidate "
                "rights are stored in the separate rights ledger, and the "
                "generic claim candidate total is blank to avoid duplicate "
                "aggregation."
            )

    return output


def main() -> None:
    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("CLE-MIN-UTA 2027 THREE-WAY FAVORABILITY POOL")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        group_claims,
    ) = load_inputs()

    canonical_text = validate_source_text(
        group_claims
    )

    discounts = build_discount_lookup(
        pick_values
    )

    unconditional_values = unconditional_value_lookup(
        pick_values
    )

    bank = SimulationBank(
        SIMULATION_BANK_PATH
    )

    lookup = SlotValueLookup(
        curve
    )

    try:
        (
            source_allocations,
            source_reconciliation,
            candidate_rights,
            selection_breakdown,
            pool_reconciliation,
        ) = evaluate_pool(
            bank=bank,
            lookup=lookup,
            discounts=discounts,
        )
    finally:
        bank.close()

    if not source_reconciliation[
        "allocation_reconciliation_passed"
    ].all():
        raise RuntimeError(
            "At least one source asset failed allocation reconciliation."
        )

    if not bool(
        pool_reconciliation.iloc[
            0
        ][
            "pool_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "Three-way pool reconciliation failed."
        )

    for asset_key, expected_value in unconditional_values.items():
        actual = float(
            source_allocations.loc[
                source_allocations[
                    "source_asset_key"
                ].eq(
                    asset_key
                ),
                "expected_allocated_value_score",
            ].sum()
        )

        if abs(
            actual
            - expected_value
        ) > 1e-8:
            raise RuntimeError(
                f"Allocated value for {asset_key} does not match the "
                "V3 originating-team value."
            )

    (
        baseline_audit,
        baseline_contributions,
    ) = build_baseline_audit(
        claims=claims,
        valuations=valuations,
    )

    adjustments = build_team_adjustments(
        candidate_rights=candidate_rights,
        baseline_contributions=baseline_contributions,
    )

    updated_team_summary = update_team_summary(
        team_summary=team_summary,
        adjustments=adjustments,
    )

    enriched_valuations = enrich_valuations(
        valuations=valuations,
        claims=claims,
        source_allocations=source_allocations,
    )

    total_source_value = float(
        source_allocations[
            "expected_allocated_value_score"
        ].sum()
    )

    total_candidate_value = float(
        candidate_rights[
            "expected_candidate_right_value_score"
        ].sum()
    )

    total_baseline = float(
        baseline_contributions[
            "current_baseline_value_score"
        ].sum()
    ) if not baseline_contributions.empty else 0.0

    total_adjustment = float(
        adjustments[
            "net_team_adjustment_value_score"
        ].sum()
    )

    if abs(
        total_source_value
        - total_candidate_value
    ) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal total source value."
        )

    if abs(
        total_adjustment
        - (
            total_source_value
            - total_baseline
        )
    ) > 1e-8:
        raise RuntimeError(
            "Team adjustments do not reconcile to source value minus "
            "the existing counted baseline."
        )

    source_allocations.to_parquet(
        SOURCE_ALLOCATIONS_PARQUET_PATH,
        index=False,
    )

    source_allocations.to_csv(
        SOURCE_ALLOCATIONS_CSV_PATH,
        index=False,
    )

    candidate_rights.to_parquet(
        CANDIDATE_RIGHTS_PARQUET_PATH,
        index=False,
    )

    candidate_rights.to_csv(
        CANDIDATE_RIGHTS_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        V9_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V9_VALUATIONS_CSV_PATH,
        index=False,
    )

    baseline_audit.to_csv(
        BASELINE_AUDIT_PATH,
        index=False,
    )

    adjustments.to_csv(
        TEAM_ADJUSTMENTS_PATH,
        index=False,
    )

    updated_team_summary.to_csv(
        V9_TEAM_SUMMARY_PATH,
        index=False,
    )

    source_reconciliation.to_csv(
        SOURCE_RECONCILIATION_PATH,
        index=False,
    )

    pool_reconciliation.to_csv(
        POOL_RECONCILIATION_PATH,
        index=False,
    )

    selection_breakdown.to_csv(
        SELECTION_BREAKDOWN_PATH,
        index=False,
    )

    pool = pool_reconciliation.iloc[
        0
    ]

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "obligation_group_id": (
            OBLIGATION_GROUP_ID
        ),
        "joint_simulations": int(
            pool[
                "joint_simulation_count"
            ]
        ),
        "utah_top_five_violation_count": int(
            pool[
                "utah_top_five_violation_count"
            ]
        ),
        "source_assets_integrated": len(
            SOURCE_ASSETS
        ),
        "source_allocation_rows": len(
            source_allocations
        ),
        "candidate_rights_created": len(
            candidate_rights
        ),
        "total_source_asset_value_score": (
            total_source_value
        ),
        "total_candidate_right_value_score": (
            total_candidate_value
        ),
        "existing_counted_baseline_value_score": (
            total_baseline
        ),
        "net_team_adjustment_value_score": (
            total_adjustment
        ),
        "all_source_reconciliations_passed": bool(
            source_reconciliation[
                "allocation_reconciliation_passed"
            ].all()
        ),
        "pool_reconciliation_passed": bool(
            pool[
                "pool_reconciliation_passed"
            ]
        ),
        "canonical_source_text": (
            canonical_text
        ),
        "interpretation_policy": [
            (
                "Lower overall pick number is treated as more favorable."
            ),
            (
                "Memphis receives the lowest-numbered of the three picks."
            ),
            (
                "Utah receives the median-numbered pick."
            ),
            (
                "Phoenix receives the highest-numbered pick."
            ),
            (
                "The simulation bank must contain zero Utah 2027 "
                "top-five selections before the pool is valued."
            ),
            (
                "Utah's existing standalone source value is removed and "
                "replaced by the joint second-most-favorable right."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATIONS_PARQUET_PATH
            ),
            "candidate_rights": str(
                CANDIDATE_RIGHTS_PARQUET_PATH
            ),
            "v9_valuation_layer": str(
                V9_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v9_team_summary": str(
                V9_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "pool_reconciliation": str(
                POOL_RECONCILIATION_PATH
            ),
            "selection_breakdown": str(
                SELECTION_BREAKDOWN_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print("=" * 80)
    print("CLE-MIN-UTA POOL FULLY INTEGRATED")
    print("=" * 80)
    print(
        f"Joint simulations: "
        f"{int(pool['joint_simulation_count']):,}"
    )
    print(
        "Utah 2027 top-five simulation violations: "
        f"{int(pool['utah_top_five_violation_count']):,}"
    )
    print(
        f"Source assets integrated: "
        f"{len(SOURCE_ASSETS):,}"
    )
    print(
        f"Source allocation rows: "
        f"{len(source_allocations):,}"
    )
    print(
        f"Candidate rights created: "
        f"{len(candidate_rights):,}"
    )
    print(
        "Total source-asset value: "
        f"{total_source_value:.4f}"
    )
    print(
        "Total candidate-right value: "
        f"{total_candidate_value:.4f}"
    )
    print(
        "Existing counted baseline removed: "
        f"{total_baseline:.4f}"
    )
    print(
        "Net team-value adjustment: "
        f"{total_adjustment:.4f}"
    )
    print(
        "All source reconciliations passed: "
        f"{bool(source_reconciliation['allocation_reconciliation_passed'].all())}"
    )
    print(
        "Pool reconciliation passed: "
        f"{bool(pool['pool_reconciliation_passed'])}"
    )
    print()

    print("CANDIDATE RIGHTS")
    rights_display = candidate_rights.copy()

    for column in [
        "expected_candidate_right_value_score",
        "expected_source_pick_count",
    ]:
        rights_display[
            column
        ] = pd.to_numeric(
            rights_display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        rights_display.to_string(
            index=False
        )
    )
    print()

    print("TEAM ADJUSTMENTS")
    adjustment_display = adjustments.copy()

    for column in [
        "cle_min_uta_pool_right_value_score",
        "existing_counted_baseline_value_score",
        "net_team_adjustment_value_score",
    ]:
        adjustment_display[
            column
        ] = pd.to_numeric(
            adjustment_display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        adjustment_display.to_string(
            index=False
        )
    )
    print()

    print("SELECTION BREAKDOWN")
    selection_display = selection_breakdown.copy()

    selection_display[
        "selection_probability"
    ] = (
        pd.to_numeric(
            selection_display[
                "selection_probability"
            ],
            errors="coerce",
        )
        * 100.0
    ).round(
        2
    )

    for column in [
        "expected_pick_when_selected",
        "expected_value_component_score",
    ]:
        selection_display[
            column
        ] = pd.to_numeric(
            selection_display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        selection_display.to_string(
            index=False
        )
    )
    print()

    print("SOURCE-ASSET RECONCILIATION")
    reconciliation_display = (
        source_reconciliation.copy()
    )

    for column in [
        "unconditional_asset_value_score",
        "allocated_value_sum",
        "allocation_value_difference",
        "allocation_probability_sum",
    ]:
        reconciliation_display[
            column
        ] = pd.to_numeric(
            reconciliation_display[
                column
            ],
            errors="coerce",
        ).round(
            8
        )

    print(
        reconciliation_display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(SOURCE_ALLOCATIONS_PARQUET_PATH)
    print(SOURCE_ALLOCATIONS_CSV_PATH)
    print(CANDIDATE_RIGHTS_PARQUET_PATH)
    print(CANDIDATE_RIGHTS_CSV_PATH)
    print(V9_VALUATIONS_PARQUET_PATH)
    print(V9_VALUATIONS_CSV_PATH)
    print(BASELINE_AUDIT_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V9_TEAM_SUMMARY_PATH)
    print(SOURCE_RECONCILIATION_PATH)
    print(POOL_RECONCILIATION_PATH)
    print(SELECTION_BREAKDOWN_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()