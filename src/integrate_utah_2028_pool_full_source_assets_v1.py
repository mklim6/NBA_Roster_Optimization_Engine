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
    "future-pick-utah-2028-pool-full-source-integration-v1-2026-08-04"
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

V6_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v6_utah_pool_enriched.parquet"
)

V6_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v6_utah_pool_component_provisional.csv"
)

POOL_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_utah_2028_second_favorability_pool_values_v1.parquet"
)

POOL_SELECTION_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_utah_2028_second_pool_selection_breakdown_v1.csv"
)

MIA_RESOLUTION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_mia_2028_second_conditional_pool_resolution_v1.parquet"
)

SOURCE_CLAIMS_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_utah_2028_pool_source_claims_v1.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATION_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_pool_source_asset_allocations_v1.parquet"
)

SOURCE_ALLOCATION_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_pool_source_asset_allocations_v1.csv"
)

RIGHTS_LEDGER_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_pool_candidate_rights_ledger_v1.parquet"
)

RIGHTS_LEDGER_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_utah_2028_pool_candidate_rights_ledger_v1.csv"
)

V7_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v7_utah_pool_fully_integrated.parquet"
)

V7_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v7_utah_pool_fully_integrated.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_full_team_adjustments_v1.csv"
)

V7_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v7_utah_pool_fully_integrated_provisional.csv"
)

ASSET_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_source_asset_reconciliation_v1.csv"
)

POOL_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_full_reconciliation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_full_integration_metadata_v1.json"
)


DRAFT_YEAR = 2028
ROUND_NUMBER = 2

POOL_CLAIM_ID = "2028_R2_DET_C2"

SOURCE_CLAIM_IDS = {
    "DET_PHI": "2028_R2_DET_C1",
    "DET_POOL": "2028_R2_DET_C2",
    "CHA": "2028_R2_CHA_C1",
    "LAC": "2028_R2_LAC_C1",
    "MIA": "2028_R2_MIA_C1",
    "NYK": "2028_R2_NYK_C1",
}

SOURCE_ASSET_KEYS = {
    "DET": "2028_R2_DET",
    "CHA": "2028_R2_CHA",
    "LAC": "2028_R2_LAC",
    "MIA": "2028_R2_MIA",
    "NYK": "2028_R2_NYK",
}

AFFECTED_TEAMS = [
    "CHA",
    "DET",
    "PHI",
    "UTA",
]

EXPECTED_TEXT = {
    "DET_PHI": [
        "Detroit's 2028 2nd round pick to Philadelphia",
        "protected for selections 31-55",
    ],
    "DET_POOL": [
        "Utah will receive the least / less favorable",
        "Detroit's 2028 2nd round pick protected for selections 56-60",
    ],
    "LAC": [
        "Charlotte will receive the more favorable",
        "Detroit will receive the less favorable",
    ],
    "NYK": [
        "New York's 2028 2nd round pick to Detroit",
        "Detroit may convey this pick to Utah",
    ],
}


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

        required_teams = [
            "DAL",
            *SOURCE_ASSET_KEYS.keys(),
        ]

        missing = [
            team
            for team in required_teams
            if team not in self.team_to_index
        ]

        if missing:
            raise ValueError(
                "Simulation bank is missing teams:\n"
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
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        V6_VALUATIONS_PATH,
        V6_TEAM_SUMMARY_PATH,
        POOL_VALUES_PATH,
        POOL_SELECTION_PATH,
        MIA_RESOLUTION_PATH,
        SOURCE_CLAIMS_AUDIT_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required full-pool integration input was not found:\n"
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

    valuations = normalize_columns(
        pd.read_parquet(
            V6_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V6_TEAM_SUMMARY_PATH
        )
    )

    pool_values = normalize_columns(
        pd.read_parquet(
            POOL_VALUES_PATH
        )
    )

    pool_selection = normalize_columns(
        pd.read_csv(
            POOL_SELECTION_PATH
        )
    )

    mia_resolution = normalize_columns(
        pd.read_parquet(
            MIA_RESOLUTION_PATH
        )
    )

    source_claims = normalize_columns(
        pd.read_csv(
            SOURCE_CLAIMS_AUDIT_PATH
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
            "time_discounted_pick_value_score",
        ],
        "V3 originating-team pick values",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "expected_total_candidate_asset_value_score",
        ],
        "V6 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_utah_pool_component_provisional"
            ),
            (
                "leaguewide_unallocated_conditional_chain_value_score_"
                "after_mia_pool_resolution"
            ),
        ],
        "V6 provisional team summary",
    )

    require_columns(
        pool_values,
        [
            "pool_claim_id",
            "expected_utah_pool_pick",
            "expected_utah_pool_value_score",
        ],
        "Utah pool values",
    )

    require_columns(
        pool_selection,
        [
            "selected_source_team",
            "selection_probability",
            "expected_pool_value_component_score",
        ],
        "Utah pool selection breakdown",
    )

    require_columns(
        mia_resolution,
        [
            "candidate_team",
            "branch_probability",
            "branch_expected_value_score",
        ],
        "Miami branch resolution",
    )

    require_columns(
        source_claims,
        [
            "claim_id",
            "asset_key",
            "transaction_text",
            "full_obligation_text",
        ],
        "Utah-pool source claims",
    )

    return (
        curve,
        pick_values,
        valuations,
        team_summary,
        pool_values,
        pool_selection,
        mia_resolution,
        source_claims,
    )


def validate_source_text(
    source_claims: pd.DataFrame,
) -> None:
    for key, fragments in EXPECTED_TEXT.items():
        claim_id = SOURCE_CLAIM_IDS[
            key
        ]

        match = source_claims.loc[
            source_claims[
                "claim_id"
            ].astype(
                str
            ).eq(
                claim_id
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                f"Expected one source-text row for {claim_id}; "
                f"found {len(match)}."
            )

        text = clean_text(
            match.iloc[
                0
            ][
                "full_obligation_text"
            ]
        )

        missing = [
            fragment
            for fragment in fragments
            if fragment.lower()
            not in text.lower()
        ]

        if missing:
            raise ValueError(
                f"Source text for {claim_id} is missing expected clauses:\n"
                + "\n".join(
                    missing
                )
            )


def discount_factor(
    pick_values: pd.DataFrame,
) -> float:
    match = pick_values.loc[
        pd.to_numeric(
            pick_values[
                "draft_year"
            ],
            errors="coerce",
        ).eq(
            DRAFT_YEAR
        )
        & pd.to_numeric(
            pick_values[
                "round_number"
            ],
            errors="coerce",
        ).eq(
            ROUND_NUMBER
        )
    ]

    factors = pd.to_numeric(
        match[
            "time_discount_factor"
        ],
        errors="coerce",
    ).dropna().unique()

    if len(
        factors
    ) != 1:
        raise ValueError(
            "Expected one common 2028 second-round discount factor."
        )

    return float(
        factors[
            0
        ]
    )


def unconditional_asset_value_lookup(
    pick_values: pd.DataFrame,
) -> dict[str, float]:
    rows = pick_values.loc[
        pd.to_numeric(
            pick_values[
                "draft_year"
            ],
            errors="coerce",
        ).eq(
            DRAFT_YEAR
        )
        & pd.to_numeric(
            pick_values[
                "round_number"
            ],
            errors="coerce",
        ).eq(
            ROUND_NUMBER
        )
        & pick_values[
            "originating_team"
        ].astype(
            str
        ).isin(
            SOURCE_ASSET_KEYS.keys()
        )
    ]

    output = {
        str(
            row.originating_team
        ): float(
            row.time_discounted_pick_value_score
        )
        for row in rows.itertuples(
            index=False
        )
    }

    missing = (
        set(
            SOURCE_ASSET_KEYS.keys()
        )
        - set(
            output
        )
    )

    if missing:
        raise ValueError(
            "Missing unconditional source-asset values:\n"
            + "\n".join(
                sorted(
                    missing
                )
            )
        )

    return output


def evaluate_full_allocations(
    bank: SimulationBank,
    lookup: SlotValueLookup,
    discount: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dal_first = bank.slots(
        draft_year=2027,
        round_number=1,
        team="DAL",
    )

    slots = {
        team: bank.slots(
            draft_year=DRAFT_YEAR,
            round_number=ROUND_NUMBER,
            team=team,
        )
        for team in SOURCE_ASSET_KEYS
    }

    simulation_count = len(
        dal_first
    )

    if any(
        len(
            values
        )
        != simulation_count
        for values in slots.values()
    ):
        raise ValueError(
            "Source-asset simulation arrays do not align."
        )

    dal_conveys = (
        dal_first
        > 2
    )

    det_available_to_pool = (
        slots[
            "DET"
        ]
        <= 55
    )

    det_to_phi = (
        slots[
            "DET"
        ]
        >= 56
    )

    cha_more_favorable = (
        slots[
            "CHA"
        ]
        < slots[
            "LAC"
        ]
    )

    lac_more_favorable = (
        slots[
            "LAC"
        ]
        < slots[
            "CHA"
        ]
    )

    if np.any(
        slots[
            "CHA"
        ]
        == slots[
            "LAC"
        ]
    ):
        raise RuntimeError(
            "Charlotte and Clippers second-round slots tied."
        )

    composite_slots = np.maximum(
        slots[
            "CHA"
        ],
        slots[
            "LAC"
        ],
    )

    composite_source = np.where(
        slots[
            "CHA"
        ]
        > slots[
            "LAC"
        ],
        "CHA",
        "LAC",
    )

    unavailable = -1

    candidate_slots = np.column_stack(
        [
            np.where(
                det_available_to_pool,
                slots[
                    "DET"
                ],
                unavailable,
            ),
            np.where(
                composite_source
                == "CHA",
                composite_slots,
                unavailable,
            ),
            np.where(
                composite_source
                == "LAC",
                composite_slots,
                unavailable,
            ),
            np.where(
                dal_conveys,
                slots[
                    "MIA"
                ],
                unavailable,
            ),
            slots[
                "NYK"
            ],
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
            simulation_count
        ),
        selected_indices,
    ]

    if np.any(
        selected_slots
        < 31
    ):
        raise RuntimeError(
            "A Utah-pool simulation had no available source pick."
        )

    asset_values = {
        team: (
            lookup.value[
                team_slots
            ]
            * discount
        )
        for team, team_slots in slots.items()
    }

    allocations: dict[
        str,
        dict[
            str,
            np.ndarray,
        ],
    ] = {
        team: {}
        for team in SOURCE_ASSET_KEYS
    }

    allocations[
        "DET"
    ][
        "PHI"
    ] = det_to_phi

    allocations[
        "DET"
    ][
        "UTA"
    ] = (
        det_available_to_pool
        & (
            selected_sources
            == "DET"
        )
    )

    allocations[
        "DET"
    ][
        "DET"
    ] = (
        det_available_to_pool
        & (
            selected_sources
            != "DET"
        )
    )

    allocations[
        "CHA"
    ][
        "CHA"
    ] = cha_more_favorable

    allocations[
        "CHA"
    ][
        "UTA"
    ] = (
        ~cha_more_favorable
        & (
            selected_sources
            == "CHA"
        )
    )

    allocations[
        "CHA"
    ][
        "DET"
    ] = (
        ~cha_more_favorable
        & (
            selected_sources
            != "CHA"
        )
    )

    allocations[
        "LAC"
    ][
        "CHA"
    ] = lac_more_favorable

    allocations[
        "LAC"
    ][
        "UTA"
    ] = (
        ~lac_more_favorable
        & (
            selected_sources
            == "LAC"
        )
    )

    allocations[
        "LAC"
    ][
        "DET"
    ] = (
        ~lac_more_favorable
        & (
            selected_sources
            != "LAC"
        )
    )

    allocations[
        "MIA"
    ][
        "CHA"
    ] = (
        ~dal_conveys
    )

    allocations[
        "MIA"
    ][
        "UTA"
    ] = (
        dal_conveys
        & (
            selected_sources
            == "MIA"
        )
    )

    allocations[
        "MIA"
    ][
        "DET"
    ] = (
        dal_conveys
        & (
            selected_sources
            != "MIA"
        )
    )

    allocations[
        "NYK"
    ][
        "UTA"
    ] = (
        selected_sources
        == "NYK"
    )

    allocations[
        "NYK"
    ][
        "DET"
    ] = (
        selected_sources
        != "NYK"
    )

    allocation_rows = []

    reconciliation_rows = []

    for source_team, team_allocations in allocations.items():
        partition_count = np.zeros(
            simulation_count,
            dtype=int,
        )

        for condition in team_allocations.values():
            partition_count += condition.astype(
                int
            )

        if not np.all(
            partition_count
            == 1
        ):
            raise RuntimeError(
                f"Allocations for {source_team} did not partition "
                "every simulation exactly once."
            )

        source_value_sum = 0.0

        for candidate_team, condition in team_allocations.items():
            component_values = np.where(
                condition,
                asset_values[
                    source_team
                ],
                0.0,
            )

            expected_value = float(
                np.mean(
                    component_values
                )
            )

            source_value_sum += expected_value

            allocation_rows.append(
                {
                    "source_asset_key": (
                        SOURCE_ASSET_KEYS[
                            source_team
                        ]
                    ),
                    "source_team": (
                        source_team
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
                                    source_team
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
                asset_values[
                    source_team
                ]
            )
        )

        reconciliation_rows.append(
            {
                "source_asset_key": (
                    SOURCE_ASSET_KEYS[
                        source_team
                    ]
                ),
                "source_team": (
                    source_team
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
                            condition
                        )
                        for condition
                        in team_allocations.values()
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

    asset_reconciliation = pd.DataFrame(
        reconciliation_rows
    )

    selected_values = (
        lookup.value[
            selected_slots
        ]
        * discount
    )

    rights_rows = []

    for candidate_team in AFFECTED_TEAMS:
        candidate_allocations = (
            source_allocations.loc[
                source_allocations[
                    "candidate_team"
                ].eq(
                    candidate_team
                )
            ]
        )

        rights_rows.append(
            {
                "candidate_team": (
                    candidate_team
                ),
                "right_type": (
                    {
                        "CHA": (
                            "more_favorable_cha_lac_plus_conditional_mia"
                        ),
                        "DET": (
                            "unselected_pool_source_retention"
                        ),
                        "PHI": (
                            "detroit_second_late-pick_protected_transfer"
                        ),
                        "UTA": (
                            "least_favorable_available_pool_selection"
                        ),
                    }[
                        candidate_team
                    ]
                ),
                "expected_candidate_right_value_score": float(
                    candidate_allocations[
                        "expected_allocated_value_score"
                    ].sum()
                ),
                "source_asset_count": int(
                    candidate_allocations[
                        "source_asset_key"
                    ].nunique()
                ),
                "source_assets": "|".join(
                    sorted(
                        candidate_allocations[
                            "source_asset_key"
                        ].unique()
                    )
                ),
            }
        )

    rights_ledger = pd.DataFrame(
        rights_rows
    )

    pool_reconciliation = pd.DataFrame(
        [
            {
                "expected_pool_pick": float(
                    np.mean(
                        selected_slots
                    )
                ),
                "expected_pool_value_score": float(
                    np.mean(
                        selected_values
                    )
                ),
                "utah_allocated_value_from_source_ledger": float(
                    source_allocations.loc[
                        source_allocations[
                            "candidate_team"
                        ].eq(
                            "UTA"
                        ),
                        "expected_allocated_value_score",
                    ].sum()
                ),
                "pool_value_difference": float(
                    source_allocations.loc[
                        source_allocations[
                            "candidate_team"
                        ].eq(
                            "UTA"
                        ),
                        "expected_allocated_value_score",
                    ].sum()
                    - np.mean(
                        selected_values
                    )
                ),
                "pool_value_reconciliation_passed": (
                    abs(
                        source_allocations.loc[
                            source_allocations[
                                "candidate_team"
                            ].eq(
                                "UTA"
                            ),
                            "expected_allocated_value_score",
                        ].sum()
                        - np.mean(
                            selected_values
                        )
                    )
                    <= 1e-8
                ),
            }
        ]
    )

    return (
        source_allocations,
        asset_reconciliation,
        rights_ledger,
        pool_reconciliation,
    )


def validate_against_prior_outputs(
    source_allocations: pd.DataFrame,
    pool_reconciliation: pd.DataFrame,
    pool_values: pd.DataFrame,
    pool_selection: pd.DataFrame,
    mia_resolution: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    prior_pool = pool_values.iloc[
        0
    ]

    rows.append(
        {
            "validation_check": (
                "expected_pool_value_matches_prior"
            ),
            "current_value": numeric_value(
                pool_reconciliation.iloc[
                    0
                ][
                    "expected_pool_value_score"
                ]
            ),
            "prior_value": numeric_value(
                prior_pool[
                    "expected_utah_pool_value_score"
                ]
            ),
            "difference": (
                numeric_value(
                    pool_reconciliation.iloc[
                        0
                    ][
                        "expected_pool_value_score"
                    ]
                )
                - numeric_value(
                    prior_pool[
                        "expected_utah_pool_value_score"
                    ]
                )
            ),
        }
    )

    for source_team in SOURCE_ASSET_KEYS:
        current = float(
            source_allocations.loc[
                (
                    source_allocations[
                        "source_team"
                    ].eq(
                        source_team
                    )
                )
                & (
                    source_allocations[
                        "candidate_team"
                    ].eq(
                        "UTA"
                    )
                ),
                "expected_allocated_value_score",
            ].sum()
        )

        prior_match = pool_selection.loc[
            pool_selection[
                "selected_source_team"
            ].astype(
                str
            ).eq(
                source_team
            )
        ]

        if len(
            prior_match
        ) != 1:
            raise ValueError(
                f"Missing prior pool-selection row for {source_team}."
            )

        prior = numeric_value(
            prior_match.iloc[
                0
            ][
                "expected_pool_value_component_score"
            ]
        )

        rows.append(
            {
                "validation_check": (
                    f"{source_team}_utah_component_matches_prior"
                ),
                "current_value": (
                    current
                ),
                "prior_value": (
                    prior
                ),
                "difference": (
                    current
                    - prior
                ),
            }
        )

    for candidate_team in [
        "CHA",
        "DET",
        "UTA",
    ]:
        current = float(
            source_allocations.loc[
                (
                    source_allocations[
                        "source_team"
                    ].eq(
                        "MIA"
                    )
                )
                & (
                    source_allocations[
                        "candidate_team"
                    ].eq(
                        candidate_team
                    )
                ),
                "expected_allocated_value_score",
            ].sum()
        )

        prior_match = mia_resolution.loc[
            mia_resolution[
                "candidate_team"
            ].astype(
                str
            ).eq(
                candidate_team
            )
        ]

        if len(
            prior_match
        ) != 1:
            raise ValueError(
                f"Missing prior Miami branch row for {candidate_team}."
            )

        prior = numeric_value(
            prior_match.iloc[
                0
            ][
                "branch_expected_value_score"
            ]
        )

        rows.append(
            {
                "validation_check": (
                    f"MIA_{candidate_team}_branch_matches_prior"
                ),
                "current_value": (
                    current
                ),
                "prior_value": (
                    prior
                ),
                "difference": (
                    current
                    - prior
                ),
            }
        )

    validation = pd.DataFrame(
        rows
    )

    validation[
        "validation_passed"
    ] = (
        validation[
            "difference"
        ].abs()
        <= 1e-8
    )

    if not validation[
        "validation_passed"
    ].all():
        raise RuntimeError(
            "At least one comparison with prior Utah-pool outputs failed."
        )

    return validation


def current_cha_direct_value(
    valuations: pd.DataFrame,
) -> float:
    match = valuations.loc[
        valuations[
            "claim_id"
        ].astype(
            str
        ).eq(
            SOURCE_CLAIM_IDS[
                "CHA"
            ]
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected one Charlotte 2028 second valuation row."
        )

    row = match.iloc[
        0
    ]

    if clean_text(
        row[
            "valuation_status"
        ]
    ) != "valued_direct_candidate":
        raise RuntimeError(
            "Charlotte's 2028 second is no longer a direct candidate. "
            "The integration script would need a new overlap baseline."
        )

    return numeric_value(
        row[
            "expected_total_candidate_asset_value_score"
        ]
    )


def build_team_adjustments(
    source_allocations: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    cha_old = current_cha_direct_value(
        valuations
    )

    rights = (
        source_allocations.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            full_integrated_right_value_score=(
                "expected_allocated_value_score",
                "sum",
            )
        )
    )

    current_baseline_components = {
        "CHA": (
            cha_old
            + float(
                source_allocations.loc[
                    (
                        source_allocations[
                            "source_team"
                        ].eq(
                            "MIA"
                        )
                    )
                    & (
                        source_allocations[
                            "candidate_team"
                        ].eq(
                            "CHA"
                        )
                    ),
                    "expected_allocated_value_score",
                ].sum()
            )
        ),
        "DET": float(
            source_allocations.loc[
                (
                    source_allocations[
                        "source_team"
                    ].eq(
                        "MIA"
                    )
                )
                & (
                    source_allocations[
                        "candidate_team"
                    ].eq(
                        "DET"
                    )
                ),
                "expected_allocated_value_score",
            ].sum()
        ),
        "UTA": float(
            source_allocations.loc[
                (
                    source_allocations[
                        "source_team"
                    ].eq(
                        "MIA"
                    )
                )
                & (
                    source_allocations[
                        "candidate_team"
                    ].eq(
                        "UTA"
                    )
                ),
                "expected_allocated_value_score",
            ].sum()
        ),
        "PHI": 0.0,
    }

    rows = []

    for team in AFFECTED_TEAMS:
        match = rights.loc[
            rights[
                "candidate_team"
            ].eq(
                team
            )
        ]

        full_value = (
            float(
                match.iloc[
                    0
                ][
                    "full_integrated_right_value_score"
                ]
            )
            if len(
                match
            )
            == 1
            else 0.0
        )

        baseline = current_baseline_components[
            team
        ]

        rows.append(
            {
                "team": (
                    team
                ),
                "full_integrated_right_value_score": (
                    full_value
                ),
                "already_counted_baseline_value_score": (
                    baseline
                ),
                "net_team_adjustment_value_score": (
                    full_value
                    - baseline
                ),
                "adjustment_scope": (
                    "replace_existing_partial_utah_pool_source_accounting"
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
        "after_utah_pool_component_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_full_utah_pool_integration"
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
        "full_utah_pool_source_adjustment_value_score"
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
        "candidate_total_pick_asset_value_score_after_full_utah_pool_integration_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_full_utah_pool_integration"
        ]
        + output[
            "full_utah_pool_source_adjustment_value_score"
        ]
    )

    output[
        "leaguewide_unallocated_conditional_chain_value_score_after_full_utah_pool_integration"
    ] = 0.0

    output[
        "full_utah_pool_integration_status"
    ] = (
        "all_five_source_assets_allocated_without_double_count"
    )

    output[
        "full_utah_pool_integration_scope_note"
    ] = (
        "Detroit, Charlotte, Clippers, Miami, and New York 2028 "
        "second-round source assets are partitioned among Charlotte, "
        "Detroit, Philadelphia, and Utah on aligned simulation rows. "
        "Previously counted Charlotte and Miami components are replaced "
        "rather than added again."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_full_utah_pool_integration_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    source_allocations: pd.DataFrame,
    rights_ledger: pd.DataFrame,
    pool_reconciliation: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    added_defaults = {
        "full_source_allocation_modeled_flag": False,
        "full_source_asset_unconditional_value_score": np.nan,
        "full_source_candidate_allocations_json": "",
        "full_utah_pool_integrated_flag": False,
        "full_utah_pool_right_value_score": np.nan,
    }

    for column, default in added_defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    for source_team, asset_key in SOURCE_ASSET_KEYS.items():
        source_rows = source_allocations.loc[
            source_allocations[
                "source_team"
            ].eq(
                source_team
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

        unconditional_value = float(
            source_rows[
                "expected_allocated_value_score"
            ].sum()
        )

        claim_ids = []

        if source_team == "DET":
            claim_ids = [
                SOURCE_CLAIM_IDS[
                    "DET_PHI"
                ],
                SOURCE_CLAIM_IDS[
                    "DET_POOL"
                ],
            ]
        else:
            claim_ids = [
                SOURCE_CLAIM_IDS[
                    source_team
                ]
            ]

        mask = output[
            "claim_id"
        ].astype(
            str
        ).isin(
            claim_ids
        )

        if int(
            mask.sum()
        ) != len(
            claim_ids
        ):
            raise ValueError(
                f"Missing valuation claims while enriching {source_team}."
            )

        output.loc[
            mask,
            "full_source_allocation_modeled_flag",
        ] = True

        output.loc[
            mask,
            "full_source_asset_unconditional_value_score",
        ] = unconditional_value

        output.loc[
            mask,
            "full_source_candidate_allocations_json",
        ] = allocation_json

    # The Charlotte claim represents only the Charlotte-Clippers
    # composite. Miami's conditional Charlotte branch remains attached
    # to the Dallas rollover obligation and must not be copied into this
    # claim-level candidate value.
    cha_composite_right = float(
        source_allocations.loc[
            source_allocations[
                "source_team"
            ].isin(
                [
                    "CHA",
                    "LAC",
                ]
            )
            & source_allocations[
                "candidate_team"
            ].eq(
                "CHA"
            ),
            "expected_allocated_value_score",
        ].sum()
    )

    cha_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        SOURCE_CLAIM_IDS[
            "CHA"
        ]
    )

    output.loc[
        cha_mask,
        "valuation_method",
    ] = (
        "joint_multi_asset_candidate_right"
    )

    output.loc[
        cha_mask,
        "valuation_status",
    ] = (
        "valued_composite_candidate_right"
    )

    output.loc[
        cha_mask,
        "candidate_beneficiary_team",
    ] = (
        "CHA"
    )

    output.loc[
        cha_mask,
        "expected_total_candidate_asset_value_score",
    ] = cha_composite_right

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            cha_mask,
            "automatic_exclusion_reason",
        ] = ""

    phi_component = float(
        source_allocations.loc[
            (
                source_allocations[
                    "source_team"
                ].eq(
                    "DET"
                )
            )
            & (
                source_allocations[
                    "candidate_team"
                ].eq(
                    "PHI"
                )
            ),
            "expected_allocated_value_score",
        ].sum()
    )

    phi_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        SOURCE_CLAIM_IDS[
            "DET_PHI"
        ]
    )

    output.loc[
        phi_mask,
        "valuation_method",
    ] = (
        "joint_conditional_source_allocation"
    )

    output.loc[
        phi_mask,
        "valuation_status",
    ] = (
        "valued_protected_transfer_candidate"
    )

    output.loc[
        phi_mask,
        "candidate_beneficiary_team",
    ] = (
        "PHI"
    )

    output.loc[
        phi_mask,
        "expected_total_candidate_asset_value_score",
    ] = phi_component

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            phi_mask,
            "automatic_exclusion_reason",
        ] = ""

    pool_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        POOL_CLAIM_ID
    )

    pool_value = numeric_value(
        pool_reconciliation.iloc[
            0
        ][
            "expected_pool_value_score"
        ]
    )

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
        "valued_pool_total_fully_integrated"
    )

    output.loc[
        pool_mask,
        "candidate_beneficiary_team",
    ] = (
        "UTA"
    )

    output.loc[
        pool_mask,
        "full_utah_pool_integrated_flag",
    ] = True

    output.loc[
        pool_mask,
        "full_utah_pool_right_value_score",
    ] = pool_value

    if (
        "favorability_pool_team_integration_hold_flag"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "favorability_pool_team_integration_hold_flag",
        ] = False

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "automatic_exclusion_reason",
        ] = ""

    if (
        "valuation_scope_note"
        in output.columns
    ):
        output.loc[
            pool_mask,
            "valuation_scope_note",
        ] = (
            "The Utah least-favorable 2028 second-round pool is fully "
            "valued and integrated through a source-allocation ledger "
            "that removes prior Charlotte and Miami overlap."
        )

    structural_claim_ids = [
        SOURCE_CLAIM_IDS[
            "LAC"
        ],
        SOURCE_CLAIM_IDS[
            "MIA"
        ],
        SOURCE_CLAIM_IDS[
            "NYK"
        ],
    ]

    structural_mask = output[
        "claim_id"
    ].astype(
        str
    ).isin(
        structural_claim_ids
    )

    output.loc[
        structural_mask,
        "valuation_method",
    ] = (
        "joint_source_asset_allocation"
    )

    output.loc[
        structural_mask,
        "valuation_status",
    ] = (
        "valued_source_asset_fully_allocated"
    )

    output.loc[
        structural_mask,
        "expected_total_candidate_asset_value_score",
    ] = np.nan

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            structural_mask,
            "automatic_exclusion_reason",
        ] = ""

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
    print("UTAH 2028 POOL FULL SOURCE-ASSET INTEGRATION")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        curve,
        pick_values,
        valuations,
        team_summary,
        pool_values,
        pool_selection,
        mia_resolution,
        source_claims,
    ) = load_inputs()

    validate_source_text(
        source_claims
    )

    discount = discount_factor(
        pick_values
    )

    unconditional_lookup = (
        unconditional_asset_value_lookup(
            pick_values
        )
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
            asset_reconciliation,
            rights_ledger,
            pool_reconciliation,
        ) = evaluate_full_allocations(
            bank=bank,
            lookup=lookup,
            discount=discount,
        )
    finally:
        bank.close()

    if not asset_reconciliation[
        "allocation_reconciliation_passed"
    ].all():
        raise RuntimeError(
            "At least one source asset failed allocation reconciliation."
        )

    prior_validation = validate_against_prior_outputs(
        source_allocations=source_allocations,
        pool_reconciliation=pool_reconciliation,
        pool_values=pool_values,
        pool_selection=pool_selection,
        mia_resolution=mia_resolution,
    )

    for source_team, expected_value in unconditional_lookup.items():
        actual = float(
            source_allocations.loc[
                source_allocations[
                    "source_team"
                ].eq(
                    source_team
                ),
                "expected_allocated_value_score",
            ].sum()
        )

        if abs(
            actual
            - expected_value
        ) > 1e-8:
            raise RuntimeError(
                f"Allocated {source_team} value does not match the "
                "V3 unconditional source-asset value."
            )

    adjustments = build_team_adjustments(
        source_allocations=source_allocations,
        valuations=valuations,
    )

    updated_team_summary = update_team_summary(
        team_summary=team_summary,
        adjustments=adjustments,
    )

    enriched_valuations = enrich_valuations(
        valuations=valuations,
        source_allocations=source_allocations,
        rights_ledger=rights_ledger,
        pool_reconciliation=pool_reconciliation,
    )

    source_allocations.to_parquet(
        SOURCE_ALLOCATION_PARQUET_PATH,
        index=False,
    )

    source_allocations.to_csv(
        SOURCE_ALLOCATION_CSV_PATH,
        index=False,
    )

    rights_ledger.to_parquet(
        RIGHTS_LEDGER_PARQUET_PATH,
        index=False,
    )

    rights_ledger.to_csv(
        RIGHTS_LEDGER_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        V7_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V7_VALUATIONS_CSV_PATH,
        index=False,
    )

    adjustments.to_csv(
        TEAM_ADJUSTMENTS_PATH,
        index=False,
    )

    updated_team_summary.to_csv(
        V7_TEAM_SUMMARY_PATH,
        index=False,
    )

    asset_reconciliation.to_csv(
        ASSET_RECONCILIATION_PATH,
        index=False,
    )

    full_reconciliation = pd.concat(
        [
            pool_reconciliation.assign(
                reconciliation_type=(
                    "pool_total"
                )
            ),
            prior_validation.assign(
                reconciliation_type=(
                    "prior_output_comparison"
                )
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    full_reconciliation.to_csv(
        POOL_RECONCILIATION_PATH,
        index=False,
    )

    total_source_value = float(
        source_allocations[
            "expected_allocated_value_score"
        ].sum()
    )

    total_right_value = float(
        rights_ledger[
            "expected_candidate_right_value_score"
        ].sum()
    )

    total_adjustment = float(
        adjustments[
            "net_team_adjustment_value_score"
        ].sum()
    )

    cha_old_direct = current_cha_direct_value(
        valuations
    )

    mia_already_counted = float(
        source_allocations.loc[
            source_allocations[
                "source_team"
            ].eq(
                "MIA"
            ),
            "expected_allocated_value_score",
        ].sum()
    )

    expected_increment = (
        unconditional_lookup[
            "DET"
        ]
        + unconditional_lookup[
            "LAC"
        ]
        + unconditional_lookup[
            "NYK"
        ]
    )

    if abs(
        total_adjustment
        - expected_increment
    ) > 1e-8:
        raise RuntimeError(
            "Net team adjustments did not equal the previously "
            "uncounted DET, LAC, and NYK source-asset values."
        )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_assets_integrated": len(
            SOURCE_ASSET_KEYS
        ),
        "source_allocation_rows": len(
            source_allocations
        ),
        "candidate_rights_created": len(
            rights_ledger
        ),
        "total_source_asset_value_score": (
            total_source_value
        ),
        "total_candidate_right_value_score": (
            total_right_value
        ),
        "total_net_team_adjustment_score": (
            total_adjustment
        ),
        "expected_newly_counted_source_value_score": (
            expected_increment
        ),
        "previously_counted_charlotte_direct_value_score": (
            cha_old_direct
        ),
        "previously_counted_miami_asset_value_score": (
            mia_already_counted
        ),
        "expected_utah_pool_value_score": numeric_value(
            pool_reconciliation.iloc[
                0
            ][
                "expected_pool_value_score"
            ]
        ),
        "all_asset_reconciliations_passed": bool(
            asset_reconciliation[
                "allocation_reconciliation_passed"
            ].all()
        ),
        "all_prior_output_comparisons_passed": bool(
            prior_validation[
                "validation_passed"
            ].all()
        ),
        "accounting_policy": [
            (
                "Each of the five source picks is assigned to exactly one "
                "candidate team in every simulation."
            ),
            (
                "Charlotte's previously counted standalone 2028 second "
                "is removed and replaced with its true composite rights."
            ),
            (
                "Miami's already integrated Charlotte, Detroit, and Utah "
                "branches are preserved rather than added again."
            ),
            (
                "Detroit, Clippers, and New York source values were not "
                "previously counted and therefore enter team totals now."
            ),
            (
                "Utah's pool value equals the sum of source allocations "
                "selected by Utah."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATION_PARQUET_PATH
            ),
            "candidate_rights_ledger": str(
                RIGHTS_LEDGER_PARQUET_PATH
            ),
            "v7_valuation_layer": str(
                V7_VALUATIONS_PARQUET_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v7_team_summary": str(
                V7_TEAM_SUMMARY_PATH
            ),
            "asset_reconciliation": str(
                ASSET_RECONCILIATION_PATH
            ),
            "full_reconciliation": str(
                POOL_RECONCILIATION_PATH
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
    print("UTAH POOL FULLY INTEGRATED")
    print("=" * 80)
    print(
        f"Source assets integrated: "
        f"{len(SOURCE_ASSET_KEYS):,}"
    )
    print(
        f"Source allocation rows: "
        f"{len(source_allocations):,}"
    )
    print(
        f"Candidate rights created: "
        f"{len(rights_ledger):,}"
    )
    print(
        "Expected Utah pool value: "
        f"{numeric_value(pool_reconciliation.iloc[0]['expected_pool_value_score']):.4f}"
    )
    print(
        "Total source-asset value: "
        f"{total_source_value:.4f}"
    )
    print(
        "Total candidate-right value: "
        f"{total_right_value:.4f}"
    )
    print(
        "Net newly counted team value: "
        f"{total_adjustment:.4f}"
    )
    print(
        "All asset reconciliations passed: "
        f"{bool(asset_reconciliation['allocation_reconciliation_passed'].all())}"
    )
    print(
        "All prior-output comparisons passed: "
        f"{bool(prior_validation['validation_passed'].all())}"
    )
    print()

    print("CANDIDATE RIGHTS LEDGER")
    rights_display = (
        rights_ledger.copy()
    )

    rights_display[
        "expected_candidate_right_value_score"
    ] = pd.to_numeric(
        rights_display[
            "expected_candidate_right_value_score"
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
    adjustment_display = (
        adjustments.copy()
    )

    for column in [
        "full_integrated_right_value_score",
        "already_counted_baseline_value_score",
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

    print("SOURCE-ASSET RECONCILIATION")
    reconciliation_display = (
        asset_reconciliation.copy()
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
    print(SOURCE_ALLOCATION_PARQUET_PATH)
    print(SOURCE_ALLOCATION_CSV_PATH)
    print(RIGHTS_LEDGER_PARQUET_PATH)
    print(RIGHTS_LEDGER_CSV_PATH)
    print(V7_VALUATIONS_PARQUET_PATH)
    print(V7_VALUATIONS_CSV_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V7_TEAM_SUMMARY_PATH)
    print(ASSET_RECONCILIATION_PATH)
    print(POOL_RECONCILIATION_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()