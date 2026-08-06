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
    "future-pick-utah-2028-second-pool-mia-component-v1-2026-08-04"
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

BRANCH_LEDGER_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_conditional_branch_ledger_2027_2029_v1.parquet"
)

V5_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v5_conditional_split_enriched.parquet"
)

V5_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v5_conditional_split_provisional.csv"
)

CHAIN_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_detroit_utah_2028_mia_second_chain_claims_v1.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

POOL_VALUES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_second_favorability_pool_values_v1.parquet"
)

POOL_VALUES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_second_favorability_pool_values_v1.csv"
)

MIA_COMPONENT_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_mia_2028_second_conditional_pool_resolution_v1.parquet"
)

MIA_COMPONENT_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_mia_2028_second_conditional_pool_resolution_v1.csv"
)

V6_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v6_utah_pool_enriched.parquet"
)

V6_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v6_utah_pool_enriched.csv"
)

POOL_SELECTION_BREAKDOWN_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_second_pool_selection_breakdown_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_mia_2028_second_detroit_utah_team_adjustments_v1.csv"
)

V6_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v6_utah_pool_component_provisional.csv"
)

RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_mia_2028_second_pool_reconciliation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_second_pool_metadata_v1.json"
)


DALLAS_ROLLOVER_CLAIM_ID = "2027_R1_DAL_C1"
MIA_FALLBACK_CLAIM_ID = "2028_R2_MIA_C1"
UTAH_POOL_CLAIM_ID = "2028_R2_DET_C2"

TARGET_BRANCH_ID = (
    "2028_R2_MIA_TO_DET_UTA_CHAIN_IF_DAL_2027_R1_CONVEYS"
)

DRAFT_YEAR = 2028
ROUND_NUMBER = 2

TIME_DISCOUNT_REFERENCE_ASSET = (
    2028,
    2,
    "MIA",
)

POOL_TEAMS = [
    "DET",
    "CHA",
    "LAC",
    "MIA",
    "NYK",
]

EXPECTED_POOL_TEXT_FRAGMENTS = [
    "Utah will receive the least / less favorable",
    "Detroit's 2028 2nd round pick protected for selections 56-60",
    "Charlotte's 2028 2nd round pick and the L.A. Clippers' 2028 2nd round pick",
    "Miami's 2028 2nd round pick",
    "New York's 2028 2nd",
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

        self.draft_years = [
            int(
                value
            )
            for value in self.archive[
                "draft_years"
            ].tolist()
        ]

        self.simulation_ids = self.archive[
            "simulation_ids"
        ].astype(
            int
        )

        self.team_to_index = {
            team: index
            for index, team in enumerate(
                self.teams
            )
        }

        missing_teams = [
            team
            for team in [
                "DAL",
                *POOL_TEAMS,
            ]
            if team not in self.team_to_index
        ]

        if missing_teams:
            raise ValueError(
                "Simulation bank is missing teams:\n"
                + "\n".join(
                    missing_teams
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
                "Simulation array was not found: "
                f"{key}"
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

        size = maximum_pick + 1

        self.value = np.full(
            size,
            np.nan,
            dtype=float,
        )

        self.rating = np.full(
            size,
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
                "Historical value lookup does not cover all picks."
            )

        if np.isnan(
            self.rating[
                1:
            ]
        ).any():
            raise ValueError(
                "Historical rating lookup does not cover all picks."
            )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        BRANCH_LEDGER_PATH,
        V5_VALUATIONS_PATH,
        V5_TEAM_SUMMARY_PATH,
        CHAIN_CLAIMS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required Utah-pool input was not found:\n"
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

    branches = normalize_columns(
        pd.read_parquet(
            BRANCH_LEDGER_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            V5_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V5_TEAM_SUMMARY_PATH
        )
    )

    chain_claims = normalize_columns(
        pd.read_csv(
            CHAIN_CLAIMS_PATH
        )
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
        ],
        "V3 originating-team pick values",
    )

    require_columns(
        branches,
        [
            "conditional_branch_id",
            "fallback_asset_key",
            "branch_probability",
            "branch_expected_value_score",
            "branch_allocation_status",
        ],
        "Conditional branch ledger",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
        ],
        "V5 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_conditional_split_provisional"
            ),
            (
                "leaguewide_unallocated_conditional_chain_"
                "value_score"
            ),
        ],
        "V5 provisional team summary",
    )

    require_columns(
        chain_claims,
        [
            "claim_id",
            "asset_key",
            "transaction_text",
            "full_obligation_text",
        ],
        "Detroit-Utah chain claims",
    )

    return (
        curve,
        pick_values,
        branches,
        valuations,
        team_summary,
        chain_claims,
    )


def validate_pool_source_text(
    chain_claims: pd.DataFrame,
) -> str:
    match = chain_claims.loc[
        chain_claims[
            "claim_id"
        ].astype(
            str
        ).eq(
            UTAH_POOL_CLAIM_ID
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected exactly one Utah pool claim row. "
            f"Found {len(match)}."
        )

    row = match.iloc[
        0
    ]

    text = clean_text(
        row[
            "full_obligation_text"
        ]
    )

    missing_fragments = [
        fragment
        for fragment in EXPECTED_POOL_TEXT_FRAGMENTS
        if fragment.lower()
        not in text.lower()
    ]

    if missing_fragments:
        raise ValueError(
            "Utah pool source text did not contain expected clauses:\n"
            + "\n".join(
                missing_fragments
            )
        )

    return text


def select_unresolved_mia_branch(
    branches: pd.DataFrame,
) -> pd.Series:
    match = branches.loc[
        branches[
            "conditional_branch_id"
        ].astype(
            str
        ).eq(
            TARGET_BRANCH_ID
        )
        & branches[
            "branch_allocation_status"
        ].astype(
            str
        ).eq(
            "unresolved_downstream_conveyance_chain"
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected one unresolved Miami-to-Detroit/Utah branch. "
            f"Found {len(match)}."
        )

    return match.iloc[
        0
    ]


def time_discount_factor(
    pick_values: pd.DataFrame,
) -> float:
    draft_year, round_number, team = (
        TIME_DISCOUNT_REFERENCE_ASSET
    )

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
            "Could not locate one 2028 Miami second-round "
            "time-discount row."
        )

    return numeric_value(
        match.iloc[
            0
        ][
            "time_discount_factor"
        ]
    )


def evaluate_pool(
    bank: SimulationBank,
    lookup: SlotValueLookup,
    discount: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dal_2027_first = bank.slots(
        draft_year=2027,
        round_number=1,
        team="DAL",
    )

    det = bank.slots(
        draft_year=2028,
        round_number=2,
        team="DET",
    )

    cha = bank.slots(
        draft_year=2028,
        round_number=2,
        team="CHA",
    )

    lac = bank.slots(
        draft_year=2028,
        round_number=2,
        team="LAC",
    )

    mia = bank.slots(
        draft_year=2028,
        round_number=2,
        team="MIA",
    )

    nyk = bank.slots(
        draft_year=2028,
        round_number=2,
        team="NYK",
    )

    simulations = len(
        dal_2027_first
    )

    if any(
        len(
            array
        )
        != simulations
        for array in [
            det,
            cha,
            lac,
            mia,
            nyk,
        ]
    ):
        raise ValueError(
            "Simulation arrays do not share the same row count."
        )

    dal_conveys = (
        dal_2027_first
        > 2
    )

    det_available = ~(
        (
            det
            >= 56
        )
        & (
            det
            <= 60
        )
    )

    cha_lac_source_is_cha = (
        cha
        > lac
    )

    cha_lac_source_is_lac = (
        lac
        > cha
    )

    if np.any(
        cha
        == lac
    ):
        raise RuntimeError(
            "Charlotte and Clippers second-round slots tied in a "
            "simulation, which should be impossible."
        )

    cha_lac_worse = np.maximum(
        cha,
        lac,
    )

    unavailable = -1

    candidate_slots = np.column_stack(
        [
            np.where(
                det_available,
                det,
                unavailable,
            ),
            np.where(
                cha_lac_source_is_cha,
                cha_lac_worse,
                unavailable,
            ),
            np.where(
                cha_lac_source_is_lac,
                cha_lac_worse,
                unavailable,
            ),
            np.where(
                dal_conveys,
                mia,
                unavailable,
            ),
            nyk,
        ]
    )

    source_labels = np.array(
        [
            "DET",
            "CHA",
            "LAC",
            "MIA",
            "NYK",
        ],
        dtype="U3",
    )

    selected_indices = np.argmax(
        candidate_slots,
        axis=1,
    )

    selected_sources = source_labels[
        selected_indices
    ]

    selected_slots = candidate_slots[
        np.arange(
            simulations
        ),
        selected_indices,
    ]

    if np.any(
        selected_slots
        < 31
    ):
        raise RuntimeError(
            "At least one Utah pool scenario had no available pick."
        )

    selected_values = (
        lookup.value[
            selected_slots
        ]
        * discount
    )

    selected_ratings = lookup.rating[
        selected_slots
    ]

    mia_discounted_values = (
        lookup.value[
            mia
        ]
        * discount
    )

    mia_to_charlotte = (
        ~dal_conveys
    )

    mia_selected_by_utah = (
        dal_conveys
        & (
            selected_sources
            == "MIA"
        )
    )

    mia_retained_by_detroit = (
        dal_conveys
        & ~mia_selected_by_utah
    )

    branch_partition_count = (
        mia_to_charlotte.astype(
            int
        )
        + mia_selected_by_utah.astype(
            int
        )
        + mia_retained_by_detroit.astype(
            int
        )
    )

    if not np.all(
        branch_partition_count
        == 1
    ):
        raise RuntimeError(
            "Miami second-round ownership branches did not partition "
            "the simulation rows exactly once."
        )

    mia_rows = [
        {
            "fallback_asset_key": (
                "2028_R2_MIA"
            ),
            "resolved_branch": (
                "Charlotte"
            ),
            "candidate_team": (
                "CHA"
            ),
            "branch_trigger": (
                "Dallas 2027 first is protected at selections 1-2"
            ),
            "branch_probability": float(
                np.mean(
                    mia_to_charlotte
                )
            ),
            "branch_expected_value_score": float(
                np.mean(
                    np.where(
                        mia_to_charlotte,
                        mia_discounted_values,
                        0.0,
                    )
                )
            ),
            "branch_expected_pick_when_received": float(
                np.mean(
                    mia[
                        mia_to_charlotte
                    ]
                )
            ),
            "branch_allocation_status": (
                "resolved_candidate_allocation"
            ),
        },
        {
            "fallback_asset_key": (
                "2028_R2_MIA"
            ),
            "resolved_branch": (
                "Utah"
            ),
            "candidate_team": (
                "UTA"
            ),
            "branch_trigger": (
                "Dallas 2027 first conveys and Miami's 2028 second "
                "is the least favorable available Utah-pool option"
            ),
            "branch_probability": float(
                np.mean(
                    mia_selected_by_utah
                )
            ),
            "branch_expected_value_score": float(
                np.mean(
                    np.where(
                        mia_selected_by_utah,
                        mia_discounted_values,
                        0.0,
                    )
                )
            ),
            "branch_expected_pick_when_received": (
                float(
                    np.mean(
                        mia[
                            mia_selected_by_utah
                        ]
                    )
                )
                if np.any(
                    mia_selected_by_utah
                )
                else np.nan
            ),
            "branch_allocation_status": (
                "resolved_candidate_allocation"
            ),
        },
        {
            "fallback_asset_key": (
                "2028_R2_MIA"
            ),
            "resolved_branch": (
                "Detroit"
            ),
            "candidate_team": (
                "DET"
            ),
            "branch_trigger": (
                "Dallas 2027 first conveys and another available "
                "second-round pick is less favorable for Utah"
            ),
            "branch_probability": float(
                np.mean(
                    mia_retained_by_detroit
                )
            ),
            "branch_expected_value_score": float(
                np.mean(
                    np.where(
                        mia_retained_by_detroit,
                        mia_discounted_values,
                        0.0,
                    )
                )
            ),
            "branch_expected_pick_when_received": (
                float(
                    np.mean(
                        mia[
                            mia_retained_by_detroit
                        ]
                    )
                )
                if np.any(
                    mia_retained_by_detroit
                )
                else np.nan
            ),
            "branch_allocation_status": (
                "resolved_candidate_allocation"
            ),
        },
    ]

    mia_resolution = pd.DataFrame(
        mia_rows
    )

    selection_rows = []

    for source in source_labels:
        selected = (
            selected_sources
            == source
        )

        selection_rows.append(
            {
                "selected_source_team": (
                    str(
                        source
                    )
                ),
                "selection_probability": float(
                    np.mean(
                        selected
                    )
                ),
                "expected_selected_pick_when_source_wins": (
                    float(
                        np.mean(
                            selected_slots[
                                selected
                            ]
                        )
                    )
                    if np.any(
                        selected
                    )
                    else np.nan
                ),
                "expected_pool_value_component_score": float(
                    np.mean(
                        np.where(
                            selected,
                            selected_values,
                            0.0,
                        )
                    )
                ),
            }
        )

    selection_breakdown = pd.DataFrame(
        selection_rows
    )

    pool_summary = pd.DataFrame(
        [
            {
                "pool_claim_id": (
                    UTAH_POOL_CLAIM_ID
                ),
                "candidate_beneficiary_team": (
                    "UTA"
                ),
                "draft_year": (
                    DRAFT_YEAR
                ),
                "round_number": (
                    ROUND_NUMBER
                ),
                "joint_simulation_count": (
                    simulations
                ),
                "pool_selection_rule": (
                    "Select the highest overall pick number, representing "
                    "the least favorable available second-round pick."
                ),
                "detroit_pick_protection_rule": (
                    "Detroit 2028 second is unavailable at picks 56-60."
                ),
                "charlotte_clippers_composite_rule": (
                    "Use the less favorable, higher-numbered pick of "
                    "Charlotte and the Clippers."
                ),
                "miami_availability_rule": (
                    "Miami 2028 second is available only if Dallas's "
                    "2027 first conveys to Charlotte."
                ),
                "dallas_2027_first_conveyance_probability": float(
                    np.mean(
                        dal_conveys
                    )
                ),
                "detroit_pick_availability_probability": float(
                    np.mean(
                        det_available
                    )
                ),
                "expected_utah_pool_pick": float(
                    np.mean(
                        selected_slots
                    )
                ),
                "expected_utah_pool_value_score": float(
                    np.mean(
                        selected_values
                    )
                ),
                "expected_utah_pool_pick_rating_60_99": float(
                    np.mean(
                        selected_ratings
                    )
                ),
                "selection_probability_sum": float(
                    selection_breakdown[
                        "selection_probability"
                    ].sum()
                ),
                "selection_value_component_sum": float(
                    selection_breakdown[
                        "expected_pool_value_component_score"
                    ].sum()
                ),
            }
        ]
    )

    return (
        pool_summary,
        selection_breakdown,
        mia_resolution,
    )


def validate_mia_reconciliation(
    mia_resolution: pd.DataFrame,
    unresolved_branch: pd.Series,
) -> pd.DataFrame:
    probability_sum = float(
        mia_resolution[
            "branch_probability"
        ].sum()
    )

    value_sum = float(
        mia_resolution[
            "branch_expected_value_score"
        ].sum()
    )

    old_unresolved_probability = numeric_value(
        unresolved_branch[
            "branch_probability"
        ]
    )

    old_unresolved_value = numeric_value(
        unresolved_branch[
            "branch_expected_value_score"
        ]
    )

    new_det_uta_probability = float(
        mia_resolution.loc[
            mia_resolution[
                "candidate_team"
            ].isin(
                [
                    "DET",
                    "UTA",
                ]
            ),
            "branch_probability",
        ].sum()
    )

    new_det_uta_value = float(
        mia_resolution.loc[
            mia_resolution[
                "candidate_team"
            ].isin(
                [
                    "DET",
                    "UTA",
                ]
            ),
            "branch_expected_value_score",
        ].sum()
    )

    charlotte_row = mia_resolution.loc[
        mia_resolution[
            "candidate_team"
        ].eq(
            "CHA"
        )
    ]

    if len(
        charlotte_row
    ) != 1:
        raise ValueError(
            "Expected one Charlotte branch in the Miami resolution."
        )

    unconditional_value = value_sum

    return pd.DataFrame(
        [
            {
                "fallback_asset_key": (
                    "2028_R2_MIA"
                ),
                "branch_probability_sum": (
                    probability_sum
                ),
                "branch_value_sum": (
                    value_sum
                ),
                "old_unresolved_detroit_utah_probability": (
                    old_unresolved_probability
                ),
                "new_detroit_plus_utah_probability": (
                    new_det_uta_probability
                ),
                "detroit_utah_probability_difference": (
                    new_det_uta_probability
                    - old_unresolved_probability
                ),
                "old_unresolved_detroit_utah_value_score": (
                    old_unresolved_value
                ),
                "new_detroit_plus_utah_value_score": (
                    new_det_uta_value
                ),
                "detroit_utah_value_difference": (
                    new_det_uta_value
                    - old_unresolved_value
                ),
                "unconditional_asset_value_score": (
                    unconditional_value
                ),
                "probability_reconciliation_passed": (
                    abs(
                        probability_sum
                        - 1.0
                    )
                    <= 1e-12
                ),
                "detroit_utah_probability_reconciliation_passed": (
                    abs(
                        new_det_uta_probability
                        - old_unresolved_probability
                    )
                    <= 1e-12
                ),
                "detroit_utah_value_reconciliation_passed": (
                    abs(
                        new_det_uta_value
                        - old_unresolved_value
                    )
                    <= 1e-8
                ),
            }
        ]
    )


def update_team_summary(
    team_summary: pd.DataFrame,
    mia_resolution: pd.DataFrame,
    unresolved_branch_value: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    output = team_summary.copy()

    base_total_column = (
        "candidate_total_pick_asset_value_score_"
        "after_conditional_split_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_utah_pool_component"
    ] = pd.to_numeric(
        output[
            base_total_column
        ],
        errors="coerce",
    )

    output[
        "mia_2028_second_utah_pool_component_adjustment_value_score"
    ] = 0.0

    adjustment_rows = []

    for team in [
        "DET",
        "UTA",
    ]:
        branch = mia_resolution.loc[
            mia_resolution[
                "candidate_team"
            ].eq(
                team
            )
        ]

        if len(
            branch
        ) != 1:
            raise ValueError(
                f"Expected one resolved Miami branch for {team}."
            )

        value = float(
            branch.iloc[
                0
            ][
                "branch_expected_value_score"
            ]
        )

        mask = output[
            "candidate_beneficiary_team"
        ].astype(
            str
        ).eq(
            team
        )

        if int(
            mask.sum()
        ) != 1:
            raise ValueError(
                f"Expected exactly one {team} row in the team summary."
            )

        output.loc[
            mask,
            "mia_2028_second_utah_pool_component_adjustment_value_score",
        ] = value

        adjustment_rows.append(
            {
                "team": (
                    team
                ),
                "fallback_asset_key": (
                    "2028_R2_MIA"
                ),
                "adjustment_value_score": (
                    value
                ),
                "adjustment_type": (
                    "add_utah_selected_mia_component"
                    if team
                    == "UTA"
                    else "add_detroit_retained_mia_component"
                ),
                "source_pool_claim_id": (
                    UTAH_POOL_CLAIM_ID
                ),
                "source_fallback_claim_id": (
                    MIA_FALLBACK_CLAIM_ID
                ),
            }
        )

    output[
        "candidate_total_pick_asset_value_score_after_utah_pool_component_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_utah_pool_component"
        ]
        + output[
            "mia_2028_second_utah_pool_component_adjustment_value_score"
        ]
    )

    previous_unallocated = pd.to_numeric(
        output[
            "leaguewide_unallocated_conditional_chain_value_score"
        ],
        errors="coerce",
    )

    output[
        "leaguewide_unallocated_conditional_chain_value_score_after_mia_pool_resolution"
    ] = (
        previous_unallocated
        - unresolved_branch_value
    )

    if (
        output[
            "leaguewide_unallocated_conditional_chain_value_score_"
            "after_mia_pool_resolution"
        ]
        .abs()
        .max()
        > 1e-8
    ):
        raise RuntimeError(
            "The Miami branch did not clear the previously unallocated "
            "conditional-chain value."
        )

    output[
        "utah_pool_component_team_summary_status"
    ] = (
        "mia_component_fully_allocated_pool_total_not_yet_integrated"
    )

    output[
        "utah_pool_component_scope_note"
    ] = (
        "Miami's 2028 second-round value is fully allocated among "
        "Charlotte, Detroit, and Utah. The full Utah favorability-pool "
        "value is calculated separately but is not added wholesale to "
        "team totals because its other source picks require overlap "
        "reallocation."
    )

    output = output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_utah_pool_component_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )

    return (
        output,
        pd.DataFrame(
            adjustment_rows
        ),
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    pool_summary: pd.DataFrame,
    mia_resolution: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    added_defaults = {
        "favorability_pool_value_modeled_flag": False,
        "expected_favorability_pool_value_score": np.nan,
        "expected_favorability_pool_pick": np.nan,
        "favorability_pool_team_integration_hold_flag": False,
        "mia_conditional_asset_fully_allocated_flag": False,
        "mia_branch_value_to_charlotte_score": 0.0,
        "mia_branch_value_to_detroit_score": 0.0,
        "mia_branch_value_to_utah_score": 0.0,
    }

    for column, default in added_defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    pool_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        UTAH_POOL_CLAIM_ID
    )

    if int(
        pool_mask.sum()
    ) != 1:
        raise ValueError(
            "Expected exactly one Utah pool valuation row."
        )

    pool = pool_summary.iloc[
        0
    ]

    output.loc[
        pool_mask,
        "valuation_method",
    ] = (
        "joint_multi_pick_favorability_pool"
    )

    output.loc[
        pool_mask,
        "valuation_status",
    ] = (
        "valued_pool_total_team_integration_hold"
    )

    output.loc[
        pool_mask,
        "candidate_beneficiary_team",
    ] = (
        "UTA"
    )

    output.loc[
        pool_mask,
        "favorability_pool_value_modeled_flag",
    ] = True

    output.loc[
        pool_mask,
        "expected_favorability_pool_value_score",
    ] = float(
        pool[
            "expected_utah_pool_value_score"
        ]
    )

    output.loc[
        pool_mask,
        "expected_favorability_pool_pick",
    ] = float(
        pool[
            "expected_utah_pool_pick"
        ]
    )

    output.loc[
        pool_mask,
        "favorability_pool_team_integration_hold_flag",
    ] = True

    if (
        "expected_total_candidate_asset_value_score"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "expected_total_candidate_asset_value_score",
        ] = np.nan

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "automatic_exclusion_reason",
        ] = (
            "pool_total_valued_source_asset_overlap_reallocation_pending"
        )

    if (
        "valuation_scope_note"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "valuation_scope_note",
        ] = (
            "The Utah pool is valued scenario by scenario. Its full "
            "value is held outside candidate team totals until selected "
            "portions of Detroit, Charlotte, Clippers, and New York "
            "source assets are reallocated without double-counting."
        )

    mia_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        MIA_FALLBACK_CLAIM_ID
    )

    if int(
        mia_mask.sum()
    ) != 1:
        raise ValueError(
            "Expected exactly one Miami fallback valuation row."
        )

    branch_values = (
        mia_resolution.set_index(
            "candidate_team"
        )[
            "branch_expected_value_score"
        ].to_dict()
    )

    output.loc[
        mia_mask,
        "valuation_method",
    ] = (
        "joint_conditional_split_with_favorability_pool"
    )

    output.loc[
        mia_mask,
        "valuation_status",
    ] = (
        "valued_conditional_split_fully_allocated"
    )

    output.loc[
        mia_mask,
        "mia_conditional_asset_fully_allocated_flag",
    ] = True

    output.loc[
        mia_mask,
        "mia_branch_value_to_charlotte_score",
    ] = float(
        branch_values[
            "CHA"
        ]
    )

    output.loc[
        mia_mask,
        "mia_branch_value_to_detroit_score",
    ] = float(
        branch_values[
            "DET"
        ]
    )

    output.loc[
        mia_mask,
        "mia_branch_value_to_utah_score",
    ] = float(
        branch_values[
            "UTA"
        ]
    )

    if (
        "conditional_split_unresolved_branch_value_score"
        in output.columns
    ):
        output.loc[
            mia_mask,
            "conditional_split_unresolved_branch_value_score",
        ] = 0.0

    if (
        "conditional_split_allocation_status"
        in output.columns
    ):
        output.loc[
            mia_mask,
            "conditional_split_allocation_status",
        ] = (
            "charlotte_detroit_utah_branches_fully_allocated"
        )

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            mia_mask,
            "automatic_exclusion_reason",
        ] = ""

    if (
        "valuation_scope_note"
        in output.columns
    ):
        output.loc[
            mia_mask,
            "valuation_scope_note",
        ] = (
            "Miami's 2028 second is fully partitioned among Charlotte, "
            "Detroit, and Utah using the Dallas conveyance condition and "
            "Utah favorability-pool selection rule."
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
    print("UTAH 2028 SECOND-ROUND FAVORABILITY POOL")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        curve,
        pick_values,
        branches,
        valuations,
        team_summary,
        chain_claims,
    ) = load_inputs()

    pool_source_text = validate_pool_source_text(
        chain_claims
    )

    unresolved_branch = select_unresolved_mia_branch(
        branches
    )

    discount = time_discount_factor(
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
            pool_summary,
            selection_breakdown,
            mia_resolution,
        ) = evaluate_pool(
            bank=bank,
            lookup=lookup,
            discount=discount,
        )
    finally:
        bank.close()

    reconciliation = validate_mia_reconciliation(
        mia_resolution=mia_resolution,
        unresolved_branch=unresolved_branch,
    )

    if not bool(
        reconciliation[
            [
                "probability_reconciliation_passed",
                "detroit_utah_probability_reconciliation_passed",
                "detroit_utah_value_reconciliation_passed",
            ]
        ].all(
            axis=None
        )
    ):
        raise RuntimeError(
            "Miami second-round pool reconciliation failed."
        )

    unresolved_value = numeric_value(
        unresolved_branch[
            "branch_expected_value_score"
        ]
    )

    (
        updated_team_summary,
        team_adjustments,
    ) = update_team_summary(
        team_summary=team_summary,
        mia_resolution=mia_resolution,
        unresolved_branch_value=unresolved_value,
    )

    enriched_valuations = enrich_valuations(
        valuations=valuations,
        pool_summary=pool_summary,
        mia_resolution=mia_resolution,
    )

    pool_summary[
        "source_claim_text"
    ] = pool_source_text

    pool_summary.to_parquet(
        POOL_VALUES_PARQUET_PATH,
        index=False,
    )

    pool_summary.to_csv(
        POOL_VALUES_CSV_PATH,
        index=False,
    )

    mia_resolution.to_parquet(
        MIA_COMPONENT_PARQUET_PATH,
        index=False,
    )

    mia_resolution.to_csv(
        MIA_COMPONENT_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        V6_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V6_VALUATIONS_CSV_PATH,
        index=False,
    )

    selection_breakdown.to_csv(
        POOL_SELECTION_BREAKDOWN_PATH,
        index=False,
    )

    team_adjustments.to_csv(
        TEAM_ADJUSTMENTS_PATH,
        index=False,
    )

    updated_team_summary.to_csv(
        V6_TEAM_SUMMARY_PATH,
        index=False,
    )

    reconciliation.to_csv(
        RECONCILIATION_PATH,
        index=False,
    )

    pool = pool_summary.iloc[
        0
    ]

    mia_values = (
        mia_resolution.set_index(
            "candidate_team"
        )[
            "branch_expected_value_score"
        ].to_dict()
    )

    mia_probabilities = (
        mia_resolution.set_index(
            "candidate_team"
        )[
            "branch_probability"
        ].to_dict()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "joint_simulations": int(
            pool[
                "joint_simulation_count"
            ]
        ),
        "utah_pool_expected_pick": float(
            pool[
                "expected_utah_pool_pick"
            ]
        ),
        "utah_pool_expected_value_score": float(
            pool[
                "expected_utah_pool_value_score"
            ]
        ),
        "miami_asset_branch_probabilities": (
            mia_probabilities
        ),
        "miami_asset_branch_values": (
            mia_values
        ),
        "miami_asset_fully_allocated": True,
        "team_summary_adjustments": (
            team_adjustments.to_dict(
                orient="records"
            )
        ),
        "all_reconciliation_checks_passed": True,
        "interpretation_policy": [
            (
                "For second-round picks, the least favorable pick is "
                "the highest overall pick number."
            ),
            (
                "Detroit's pick is excluded when it lands 56-60 because "
                "those selections are protected."
            ),
            (
                "The Charlotte-Clippers component contributes the higher "
                "of their two pick numbers."
            ),
            (
                "Miami is available only when Dallas's 2027 first conveys."
            ),
            (
                "New York is treated as an always-available pool option."
            ),
        ],
        "team_integration_policy": [
            (
                "Miami's selected share is added to Utah."
            ),
            (
                "Miami's non-selected Detroit-side share is added to Detroit."
            ),
            (
                "The full Utah pool value is not added wholesale because "
                "the other selected-source components require offsetting "
                "reallocations from their existing owners."
            ),
        ],
        "output_files": {
            "pool_values": str(
                POOL_VALUES_PARQUET_PATH
            ),
            "selection_breakdown": str(
                POOL_SELECTION_BREAKDOWN_PATH
            ),
            "miami_component_resolution": str(
                MIA_COMPONENT_PARQUET_PATH
            ),
            "v6_valuation_layer": str(
                V6_VALUATIONS_PARQUET_PATH
            ),
            "v6_team_summary": str(
                V6_TEAM_SUMMARY_PATH
            ),
            "reconciliation": str(
                RECONCILIATION_PATH
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
    print("UTAH POOL AND MIAMI COMPONENT VALUED")
    print("=" * 80)
    print(
        "Joint simulations: "
        f"{int(pool['joint_simulation_count']):,}"
    )
    print(
        "Expected Utah pool pick: "
        f"{float(pool['expected_utah_pool_pick']):.4f}"
    )
    print(
        "Expected Utah pool value score: "
        f"{float(pool['expected_utah_pool_value_score']):.4f}"
    )
    print(
        "Miami second fully allocated: True"
    )
    print(
        "All reconciliation checks passed: True"
    )
    print()

    print("UTAH POOL SELECTION BREAKDOWN")
    display_selection = (
        selection_breakdown.copy()
    )

    display_selection[
        "selection_probability"
    ] = (
        display_selection[
            "selection_probability"
        ]
        * 100.0
    ).round(
        2
    )

    for column in [
        "expected_selected_pick_when_source_wins",
        "expected_pool_value_component_score",
    ]:
        display_selection[
            column
        ] = pd.to_numeric(
            display_selection[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        display_selection.to_string(
            index=False
        )
    )
    print()

    print("MIAMI 2028 SECOND-ROUND BRANCHES")
    display_mia = (
        mia_resolution.copy()
    )

    display_mia[
        "branch_probability"
    ] = (
        display_mia[
            "branch_probability"
        ]
        * 100.0
    ).round(
        2
    )

    for column in [
        "branch_expected_value_score",
        "branch_expected_pick_when_received",
    ]:
        display_mia[
            column
        ] = pd.to_numeric(
            display_mia[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        display_mia[
            [
                "candidate_team",
                "branch_probability",
                "branch_expected_value_score",
                "branch_expected_pick_when_received",
                "branch_trigger",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("TEAM ADJUSTMENTS")
    adjustment_display = (
        team_adjustments.copy()
    )

    adjustment_display[
        "adjustment_value_score"
    ] = pd.to_numeric(
        adjustment_display[
            "adjustment_value_score"
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

    print("SAVED FILES")
    print(POOL_VALUES_PARQUET_PATH)
    print(POOL_VALUES_CSV_PATH)
    print(MIA_COMPONENT_PARQUET_PATH)
    print(MIA_COMPONENT_CSV_PATH)
    print(V6_VALUATIONS_PARQUET_PATH)
    print(V6_VALUATIONS_CSV_PATH)
    print(POOL_SELECTION_BREAKDOWN_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V6_TEAM_SUMMARY_PATH)
    print(RECONCILIATION_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()