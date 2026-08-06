from __future__ import annotations

import itertools
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-2027-mil-nop-atl-protected-component-v1-2026-08-04"
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

V17_INPUT_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v17_bkn_dal_enriched.parquet"
)

V17_INPUT_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v17_bkn_dal_provisional.csv"
)

GROUP_DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2027_mil_nop_atl_group_claims_v1.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_candidate_rights_v1.csv"
)

EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_event_summary_v1.parquet"
)

EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_mil_nop_atl_event_summary_v1.csv"
)

V18_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v18_mil_nop_atl_enriched.parquet"
)

V18_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v18_mil_nop_atl_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_team_adjustments_v1.csv"
)

V18_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v18_mil_nop_atl_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_source_reconciliation_v1.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_component_reconciliation_v1.csv"
)

EXHAUSTIVE_PROOF_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_exhaustive_slot_proof_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_mil_nop_atl_component_metadata_v1.json"
)

SOURCE_ASSETS = {
    "2027_R1_NOP": (2027, 1, "NOP"),
    "2027_R1_MIL": (2027, 1, "MIL"),
}

CANDIDATE_TEAMS = {
    "NOP",
    "ATL",
}

TARGET_GROUP_ID = "OBL_eed06f74d793"

REQUIRED_GROUP_CLAIMS = {
    "2027_R1_MIL_C1",
}

EXPECTED_TEXT_FRAGMENTS = [
    (
        "New Orleans will receive the more favorable of its "
        "2027 1st round pick and Milwaukee's 2027 1st round pick"
    ),
    (
        "Atlanta will receive the less favorable of the two "
        "protected for selections 1-4"
    ),
    (
        "if this pick falls within its protected range and is "
        "therefore not conveyable"
    ),
    "New Orleans' obligation to Atlanta will be extinguished",
    "New Orleans will instead receive both picks",
]

PROTECTED_MAX_SLOT = 4

EXPECTED_BASELINE_ASSETS = {
    "2027_R1_NOP",
}

FORBIDDEN_SOURCE_ASSETS = {
    "2027_R1_ATL",
    "2027_R1_OKC",
    "2027_R1_DEN",
    "2027_R1_TOR",
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
            + "\n".join(missing)
        )


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and np.isnan(value):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def numeric_value(
    value: Any,
) -> float:
    return float(
        pd.to_numeric(
            pd.Series([value]),
            errors="coerce",
        ).iloc[0]
    )


def finite_or_zero(
    value: Any,
) -> float:
    number = numeric_value(value)
    return number if np.isfinite(number) else 0.0


def json_safe(
    value: Any,
) -> Any:
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

    if pd.isna(value):
        return None

    return value


class SimulationBank:
    def __init__(
        self,
        path: Path,
    ) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"Simulation bank was not found:\n{path}"
            )

        self.archive = np.load(
            path,
            allow_pickle=False,
        )

        self.teams = [
            str(value)
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
        ].astype(int)

        missing = sorted(
            {
                team
                for _, _, team in SOURCE_ASSETS.values()
            }
            - set(self.teams)
        )

        if missing:
            raise ValueError(
                "Simulation bank is missing required teams:\n"
                + "\n".join(missing)
            )

    def slots(
        self,
        draft_year: int,
        round_number: int,
        team: str,
    ) -> np.ndarray:
        prefix = (
            "first_round"
            if int(round_number) == 1
            else "second_round"
        )

        key = f"{prefix}_{int(draft_year)}"

        if key not in self.archive.files:
            raise KeyError(
                f"Simulation array was not found: {key}"
            )

        return self.archive[key][
            :,
            self.team_to_index[str(team)],
        ].astype(int)

    def close(self) -> None:
        self.archive.close()


class SlotValueLookup:
    def __init__(
        self,
        curve: pd.DataFrame,
    ) -> None:
        maximum_pick = int(
            curve["overall_pick"].max()
        )

        self.value = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        for row in curve.itertuples(
            index=False
        ):
            self.value[
                int(row.overall_pick)
            ] = float(
                row.historical_pick_value_score
            )

        if np.isnan(
            self.value[1:]
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
]:
    for path in [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        V17_INPUT_VALUATIONS_PATH,
        V17_INPUT_TEAM_SUMMARY_PATH,
        GROUP_DIAGNOSTIC_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required protected component input was not found:\n"
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
            V17_INPUT_VALUATIONS_PATH
        )
    )
    team_summary = normalize_columns(
        pd.read_csv(
            V17_INPUT_TEAM_SUMMARY_PATH
        )
    )
    group_diagnostic = normalize_columns(
        pd.read_csv(
            GROUP_DIAGNOSTIC_PATH
        )
    )

    require_columns(
        curve,
        [
            "overall_pick",
            "historical_pick_value_score",
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
        "V3 originating-team values",
    )
    require_columns(
        claims,
        [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "full_obligation_text",
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
        "V17 valuation layer",
    )
    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_bkn_dal_component_provisional"
            ),
        ],
        "V17 provisional team summary",
    )
    require_columns(
        group_diagnostic,
        [
            "claim_id",
            "asset_key",
        ],
        "MIL-NOP-ATL diagnostic",
    )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        group_diagnostic,
    )


def validate_group_diagnostic(
    group_diagnostic: pd.DataFrame,
) -> None:
    claim_ids = set(
        group_diagnostic[
            "claim_id"
        ].astype(str)
    )

    asset_keys = set(
        group_diagnostic[
            "asset_key"
        ].astype(str)
    )

    if claim_ids != REQUIRED_GROUP_CLAIMS:
        raise ValueError(
            "The diagnostic claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    REQUIRED_GROUP_CLAIMS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    claim_ids
                )
            )
        )

    if asset_keys != {
        "2027_R1_MIL",
    }:
        raise ValueError(
            "The diagnostic unresolved source set changed."
        )


def validate_claim_text(
    claims: pd.DataFrame,
) -> str:
    match = claims.loc[
        claims[
            "claim_id"
        ]
        .astype(str)
        .eq(
            "2027_R1_MIL_C1"
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected exactly one controlling Milwaukee claim."
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
        for fragment in EXPECTED_TEXT_FRAGMENTS
        if fragment.lower() not in text.lower()
    ]

    if missing:
        raise ValueError(
            "Controlling claim text is missing expected clauses:\n"
            + "\n".join(
                missing
            )
        )

    return text


def validate_source_claim_coverage(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    if set(
        SOURCE_ASSETS
    ) & FORBIDDEN_SOURCE_ASSETS:
        raise ValueError(
            "A connected-text-only asset was incorrectly included "
            "in the physical source set."
        )

    source_claims = claims.loc[
        claims[
            "asset_key"
        ]
        .astype(str)
        .isin(
            SOURCE_ASSETS.keys()
        )
    ].copy()

    found_assets = set(
        source_claims[
            "asset_key"
        ].astype(str)
    )

    missing_assets = sorted(
        set(
            SOURCE_ASSETS
        )
        - found_assets
    )

    if missing_assets:
        raise ValueError(
            "The claim layer is missing physical source assets:\n"
            + "\n".join(
                missing_assets
            )
        )

    return source_claims


def build_value_lookups(
    pick_values: pd.DataFrame,
) -> tuple[
    dict[str, float],
    dict[str, float],
]:
    discounts: dict[
        str,
        float,
    ] = {}

    unconditional_values: dict[
        str,
        float,
    ] = {}

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
            ]
            .astype(str)
            .eq(
                team
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                f"Expected one pick-value row for {asset_key}; "
                f"found {len(match)}."
            )

        discounts[
            asset_key
        ] = numeric_value(
            match.iloc[
                0
            ][
                "time_discount_factor"
            ]
        )

        unconditional_values[
            asset_key
        ] = numeric_value(
            match.iloc[
                0
            ][
                "time_discounted_pick_value_score"
            ]
        )

    if len(
        {
            round(
                value,
                12,
            )
            for value in discounts.values()
        }
    ) != 1:
        raise ValueError(
            "The two 2027 first-round assets do not share "
            "one time-discount factor."
        )

    return (
        discounts,
        unconditional_values,
    )


def allocate_component(
    rank: dict[str, int],
) -> tuple[
    dict[str, list[str]],
    str,
]:
    ordered = sorted(
        SOURCE_ASSETS,
        key=lambda asset_key: (
            rank[
                asset_key
            ],
            asset_key,
        ),
    )

    better_asset = ordered[
        0
    ]

    worse_asset = ordered[
        1
    ]

    protection_hits = bool(
        rank[
            worse_asset
        ]
        <= PROTECTED_MAX_SLOT
    )

    if protection_hits:
        return (
            {
                "NOP": [
                    better_asset,
                    worse_asset,
                ],
                "ATL": [],
            },
            "LESS_FAVORABLE_PICK_1_4_NOT_CONVEYABLE",
        )

    return (
        {
            "NOP": [
                better_asset,
            ],
            "ATL": [
                worse_asset,
            ],
        },
        "LESS_FAVORABLE_PICK_5_30_CONVEYED",
    )


def prove_allocation_closure() -> pd.DataFrame:
    rows = []

    for nop_slot in range(
        1,
        31,
    ):
        for mil_slot in range(
            1,
            31,
        ):
            if nop_slot == mil_slot:
                continue

            rank = {
                "2027_R1_NOP": nop_slot,
                "2027_R1_MIL": mil_slot,
            }

            (
                allocation,
                protection_branch,
            ) = allocate_component(
                rank
            )

            assigned = (
                allocation[
                    "NOP"
                ]
                + allocation[
                    "ATL"
                ]
            )

            protected = bool(
                protection_branch
                == "LESS_FAVORABLE_PICK_1_4_NOT_CONVEYABLE"
            )

            expected_nop_count = (
                2
                if protected
                else 1
            )

            expected_atl_count = (
                0
                if protected
                else 1
            )

            closure_passed = bool(
                set(
                    assigned
                )
                == set(
                    SOURCE_ASSETS
                )
                and len(
                    assigned
                )
                == len(
                    set(
                        assigned
                    )
                )
                and len(
                    allocation[
                        "NOP"
                    ]
                )
                == expected_nop_count
                and len(
                    allocation[
                        "ATL"
                    ]
                )
                == expected_atl_count
            )

            ordered = sorted(
                SOURCE_ASSETS,
                key=lambda asset_key: (
                    rank[
                        asset_key
                    ],
                    asset_key,
                ),
            )

            rows.append(
                {
                    "nop_slot": nop_slot,
                    "mil_slot": mil_slot,
                    "better_source_asset": ordered[
                        0
                    ],
                    "worse_source_asset": ordered[
                        1
                    ],
                    "worse_pick_slot": int(
                        rank[
                            ordered[
                                1
                            ]
                        ]
                    ),
                    "protection_branch": protection_branch,
                    "new_orleans_pick_count": int(
                        len(
                            allocation[
                                "NOP"
                            ]
                        )
                    ),
                    "atlanta_pick_count": int(
                        len(
                            allocation[
                                "ATL"
                            ]
                        )
                    ),
                    "all_two_sources_assigned_once": closure_passed,
                }
            )

    proof = pd.DataFrame(
        rows
    )

    if len(
        proof
    ) != 870:
        raise RuntimeError(
            "Exhaustive proof did not evaluate all 870 distinct "
            "two-team first-round slot assignments."
        )

    if not proof[
        "all_two_sources_assigned_once"
    ].all():
        raise RuntimeError(
            "The protected allocation failed at least one slot assignment."
        )

    protected_count = int(
        proof[
            "protection_branch"
        ]
        .eq(
            "LESS_FAVORABLE_PICK_1_4_NOT_CONVEYABLE"
        )
        .sum()
    )

    if protected_count != 12:
        raise RuntimeError(
            "The exhaustive proof did not find the expected 12 "
            "ordered assignments where both picks are selections 1-4."
        )

    return proof


def evaluate_component(
    bank: SimulationBank,
    lookup: SlotValueLookup,
    discounts: dict[str, float],
) -> tuple[
    pd.DataFrame,
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
            "Protected two-pick simulation arrays do not align."
        )

    discounted_values = {
        asset_key: (
            lookup.value[
                asset_slots
            ]
            * discounts[
                asset_key
            ]
        )
        for asset_key, asset_slots in slots.items()
    }

    owner_arrays = {
        asset_key: np.full(
            simulation_count,
            "",
            dtype="U3",
        )
        for asset_key in SOURCE_ASSETS
    }

    branch_array = np.full(
        simulation_count,
        "",
        dtype="U48",
    )

    allocation_event_rows: list[
        dict[str, Any]
    ] = []

    for simulation_index in range(
        simulation_count
    ):
        rank = {
            asset_key: int(
                slots[
                    asset_key
                ][
                    simulation_index
                ]
            )
            for asset_key in SOURCE_ASSETS
        }

        (
            allocation,
            protection_branch,
        ) = allocate_component(
            rank
        )

        branch_array[
            simulation_index
        ] = protection_branch

        assigned = (
            allocation[
                "NOP"
            ]
            + allocation[
                "ATL"
            ]
        )

        if (
            set(
                assigned
            )
            != set(
                SOURCE_ASSETS
            )
            or len(
                assigned
            )
            != len(
                set(
                    assigned
                )
            )
        ):
            raise RuntimeError(
                "A simulation did not assign both physical picks "
                "exactly once."
            )

        for candidate_team in CANDIDATE_TEAMS:
            for asset_key in allocation[
                candidate_team
            ]:
                owner_arrays[
                    asset_key
                ][
                    simulation_index
                ] = candidate_team

        ordered = sorted(
            SOURCE_ASSETS,
            key=lambda asset_key: (
                rank[
                    asset_key
                ],
                asset_key,
            ),
        )

        rank_labels = {
            ordered[
                0
            ]: "more_favorable",
            ordered[
                1
            ]: "less_favorable",
        }

        for candidate_team, assets in allocation.items():
            for asset_key in assets:
                allocation_event_rows.append(
                    {
                        "simulation_id": int(
                            bank.simulation_ids[
                                simulation_index
                            ]
                        ),
                        "event_type": "candidate_receipt",
                        "event_outcome": protection_branch,
                        "candidate_team": candidate_team,
                        "source_asset_key": asset_key,
                        "allocation_rank": rank_labels[
                            asset_key
                        ],
                        "overall_pick": int(
                            slots[
                                asset_key
                            ][
                                simulation_index
                            ]
                        ),
                    }
                )

    for asset_key, owner_array in owner_arrays.items():
        if np.any(
            owner_array
            == ""
        ):
            raise RuntimeError(
                f"{asset_key} has at least one missing owner."
            )

    allocation_rows: list[
        dict[str, Any]
    ] = []

    reconciliation_rows: list[
        dict[str, Any]
    ] = []

    for asset_key, owner_array in owner_arrays.items():
        allocated_value_sum = 0.0

        for candidate_team in sorted(
            set(
                owner_array.tolist()
            )
        ):
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

            allocated_value_sum += expected_value

            allocation_rows.append(
                {
                    "source_asset_key": asset_key,
                    "source_team": SOURCE_ASSETS[
                        asset_key
                    ][
                        2
                    ],
                    "candidate_team": candidate_team,
                    "allocation_probability": float(
                        np.mean(
                            condition
                        )
                    ),
                    "expected_allocated_value_score": expected_value,
                    "expected_pick_when_allocated": float(
                        np.mean(
                            slots[
                                asset_key
                            ][
                                condition
                            ]
                        )
                    ),
                    "simulation_count": simulation_count,
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
                "source_asset_key": asset_key,
                "unconditional_asset_value_score": unconditional_value,
                "allocated_value_sum": allocated_value_sum,
                "allocation_value_difference": (
                    allocated_value_sum
                    - unconditional_value
                ),
                "allocation_probability_sum": float(
                    sum(
                        np.mean(
                            owner_array
                            == team
                        )
                        for team in set(
                            owner_array.tolist()
                        )
                    )
                ),
                "allocation_reconciliation_passed": bool(
                    abs(
                        allocated_value_sum
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
            expected_pick_count=(
                "allocation_probability",
                "sum",
            ),
            source_asset_count=(
                "source_asset_key",
                "nunique",
            ),
        )
    )

    source_lists = (
        source_allocations.groupby(
            "candidate_team"
        )[
            "source_asset_key"
        ]
        .apply(
            lambda series: "|".join(
                sorted(
                    set(
                        series
                    )
                )
            )
        )
        .rename(
            "source_assets"
        )
        .reset_index()
    )

    candidate_rights = candidate_rights.merge(
        source_lists,
        how="left",
        on="candidate_team",
        validate="one_to_one",
    )

    raw_allocation_events = pd.DataFrame(
        allocation_event_rows
    )

    receipt_summary = (
        raw_allocation_events.groupby(
            [
                "event_type",
                "event_outcome",
                "candidate_team",
                "source_asset_key",
                "allocation_rank",
            ],
            as_index=False,
        )
        .agg(
            event_count=(
                "simulation_id",
                "count",
            ),
            expected_pick_when_received=(
                "overall_pick",
                "mean",
            ),
        )
    )

    receipt_summary[
        "event_probability"
    ] = (
        receipt_summary[
            "event_count"
        ]
        / simulation_count
    )

    receipt_summary[
        "expected_nop_pick_when_event_occurs"
    ] = np.nan

    receipt_summary[
        "expected_mil_pick_when_event_occurs"
    ] = np.nan

    branch_rows = []

    for protection_branch in sorted(
        set(
            branch_array.tolist()
        )
    ):
        condition = (
            branch_array
            == protection_branch
        )

        branch_rows.append(
            {
                "event_type": "protection_branch",
                "event_outcome": protection_branch,
                "candidate_team": "",
                "source_asset_key": "",
                "allocation_rank": "",
                "event_count": int(
                    condition.sum()
                ),
                "event_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_pick_when_received": np.nan,
                "expected_nop_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2027_R1_NOP"
                        ][
                            condition
                        ]
                    )
                ),
                "expected_mil_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2027_R1_MIL"
                        ][
                            condition
                        ]
                    )
                ),
            }
        )

    event_summary = pd.concat(
        [
            pd.DataFrame(
                branch_rows
            ),
            receipt_summary,
        ],
        ignore_index=True,
        sort=False,
    )

    expected_pick_counts = (
        candidate_rights.set_index(
            "candidate_team"
        )[
            "expected_pick_count"
        ]
        .to_dict()
    )

    protection_probability = float(
        np.mean(
            branch_array
            == "LESS_FAVORABLE_PICK_1_4_NOT_CONVEYABLE"
        )
    )

    expected_nop_pick_count = (
        1.0
        + protection_probability
    )

    expected_atl_pick_count = (
        1.0
        - protection_probability
    )

    component_reconciliation = pd.DataFrame(
        [
            {
                "joint_simulation_count": simulation_count,
                "source_asset_count": len(
                    SOURCE_ASSETS
                ),
                "candidate_team_count": int(
                    candidate_rights[
                        "candidate_team"
                    ].nunique()
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
                "total_candidate_pick_count": float(
                    candidate_rights[
                        "expected_pick_count"
                    ].sum()
                ),
                "protection_hit_probability": protection_probability,
                "new_orleans_expected_pick_count": float(
                    expected_pick_counts.get(
                        "NOP",
                        np.nan,
                    )
                ),
                "atlanta_expected_pick_count": float(
                    expected_pick_counts.get(
                        "ATL",
                        np.nan,
                    )
                ),
                "value_difference": float(
                    candidate_rights[
                        "expected_candidate_right_value_score"
                    ].sum()
                    - source_allocations[
                        "expected_allocated_value_score"
                    ].sum()
                ),
                "component_reconciliation_passed": bool(
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
                            "expected_pick_count"
                        ].sum()
                        - 2.0
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get(
                            "NOP",
                            np.nan,
                        )
                        - expected_nop_pick_count
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get(
                            "ATL",
                            np.nan,
                        )
                        - expected_atl_pick_count
                    )
                    <= 1e-10
                ),
            }
        ]
    )

    return (
        source_allocations,
        source_reconciliation,
        candidate_rights,
        event_summary,
        component_reconciliation,
    )


def build_baseline_audit(
    source_claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    valuation_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
        ]
        if column in valuations.columns
    ]

    audit = source_claims.merge(
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

    valued_mask = (
        audit[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .str.startswith(
            "valued_"
        )
    )

    allowed_direct = (
        audit[
            "valuation_method"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "direct_asset_value"
        )
        | audit[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "valued_direct_candidate"
        )
    )

    disallowed = audit.loc[
        valued_mask
        & ~allowed_direct
    ]

    if not disallowed.empty:
        raise RuntimeError(
            "A protected-component source asset is already represented by a "
            "non-direct component. Expand the connected component "
            "before integration:\n"
            + disallowed[
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

    for asset_key, group in audit.loc[
        allowed_direct
    ].groupby(
        "asset_key"
    ):
        positive_rows = []

        for row in group.itertuples(
            index=False
        ):
            value = finite_or_zero(
                getattr(
                    row,
                    "expected_total_candidate_asset_value_score",
                    np.nan,
                )
            )

            if value > 0:
                positive_rows.append(
                    (
                        row,
                        value,
                    )
                )

        if len(
            positive_rows
        ) > 1:
            raise RuntimeError(
                "Multiple positive direct baseline rows exist for "
                f"{asset_key}."
            )

        for row, value in positive_rows:
            team = clean_text(
                getattr(
                    row,
                    "candidate_beneficiary_team",
                    "",
                )
            )

            if not team:
                raise RuntimeError(
                    f"Direct baseline row for {asset_key} has no team."
                )

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
        ]
        .to_dict()
    )

    baseline_values = (
        baseline_contributions.groupby(
            "team"
        )[
            "current_baseline_value_score"
        ]
        .sum()
        .to_dict()
        if not baseline_contributions.empty
        else {}
    )

    teams = sorted(
        set(
            new_values
        )
        | set(
            baseline_values
        )
        | CANDIDATE_TEAMS
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
                "team": team,
                "protected_component_right_value_score": new_value,
                "existing_counted_baseline_value_score": baseline,
                "net_team_adjustment_value_score": (
                    new_value
                    - baseline
                ),
                "adjustment_scope": (
                    "replace_existing_nop_baseline_with_joint_"
                    "protected_component_rights"
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
        "after_bkn_dal_component_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_mil_nop_atl_component"
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
        ]
        .to_dict()
    )

    output[
        "mil_nop_atl_component_adjustment_value_score"
    ] = (
        output[
            "candidate_beneficiary_team"
        ]
        .astype(str)
        .map(
            adjustment_lookup
        )
        .fillna(
            0.0
        )
    )

    output[
        "candidate_total_pick_asset_value_score_after_mil_nop_atl_component_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_mil_nop_atl_component"
        ]
        + output[
            "mil_nop_atl_component_adjustment_value_score"
        ]
    )

    output[
        "mil_nop_atl_component_status"
    ] = (
        "fully_integrated_protected_two_first_component"
    )

    output[
        "mil_nop_atl_component_scope_note"
    ] = (
        "New Orleans and Milwaukee's 2027 first-round picks are "
        "modeled jointly. New Orleans receives the more favorable "
        "pick. Atlanta receives the less favorable pick unless it "
        "falls in selections 1-4, in which case Atlanta's right is "
        "extinguished and New Orleans receives both picks."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_mil_nop_atl_component_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    source_claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    defaults = {
        "mil_nop_atl_component_modeled_flag": False,
        "mil_nop_atl_component_primary_claim_flag": False,
        "mil_nop_atl_source_asset_value_score": np.nan,
        "mil_nop_atl_candidate_allocations_json": "",
    }

    for column, default in defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    grouped_claims = (
        source_claims[
            [
                "claim_id",
                "asset_key",
            ]
        ]
        .sort_values(
            [
                "asset_key",
                "claim_id",
            ]
        )
        .groupby(
            "asset_key",
            sort=True,
        )
    )

    for asset_key, claim_group in grouped_claims:
        source_rows = source_allocations.loc[
            source_allocations[
                "source_asset_key"
            ].eq(
                asset_key
            )
        ]

        source_value = float(
            source_rows[
                "expected_allocated_value_score"
            ].sum()
        )

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

        primary_claim_id = str(
            claim_group.iloc[
                0
            ][
                "claim_id"
            ]
        )

        for row in claim_group.itertuples(
            index=False
        ):
            claim_id = str(
                row.claim_id
            )

            mask = (
                output[
                    "claim_id"
                ]
                .astype(str)
                .eq(
                    claim_id
                )
            )

            if int(
                mask.sum()
            ) != 1:
                raise ValueError(
                    f"Expected one valuation row for {claim_id}."
                )

            primary_flag = bool(
                claim_id
                == primary_claim_id
            )

            output.loc[
                mask,
                "valuation_method",
            ] = (
                "joint_2027_mil_nop_atl_source_allocation"
            )

            output.loc[
                mask,
                "valuation_status",
            ] = (
                "valued_source_asset_fully_allocated"
            )

            for team_column in [
                "candidate_beneficiary_team",
                "candidate_retaining_team",
                "candidate_counterparty_team",
            ]:
                if team_column in output.columns:
                    output.loc[
                        mask,
                        team_column,
                    ] = ""

            output.loc[
                mask,
                "mil_nop_atl_component_modeled_flag",
            ] = True

            output.loc[
                mask,
                "mil_nop_atl_component_primary_claim_flag",
            ] = primary_flag

            output.loc[
                mask,
                "mil_nop_atl_source_asset_value_score",
            ] = (
                source_value
                if primary_flag
                else np.nan
            )

            output.loc[
                mask,
                "mil_nop_atl_candidate_allocations_json",
            ] = (
                allocation_json
                if primary_flag
                else ""
            )

            for value_column in [
                "expected_total_candidate_asset_value_score",
                "expected_transferred_value_score",
                "expected_retained_value_score",
                "expected_swap_option_value_score",
            ]:
                if value_column in output.columns:
                    output.loc[
                        mask,
                        value_column,
                    ] = np.nan

            if "automatic_exclusion_reason" in output.columns:
                output.loc[
                    mask,
                    "automatic_exclusion_reason",
                ] = ""

            if "valuation_scope_note" in output.columns:
                output.loc[
                    mask,
                    "valuation_scope_note",
                ] = (
                    "This physical pick is fully allocated through "
                    "the joint 2027 Milwaukee-New Orleans-Atlanta "
                    "protected first-round component. "
                    + (
                        "This primary claim row carries the source "
                        "value and allocation JSON."
                        if primary_flag
                        else
                        "This alias or overlapping claim row carries "
                        "no source value to prevent duplication."
                    )
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

    print(
        "=" * 80
    )
    print(
        "2027 MIL-NOP-ATL PROTECTED TWO-FIRST COMPONENT"
    )
    print(
        "=" * 80
    )
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
        group_diagnostic,
    ) = load_inputs()

    validate_group_diagnostic(
        group_diagnostic
    )

    controlling_text = validate_claim_text(
        claims
    )

    exhaustive_proof = prove_allocation_closure()

    source_claims = validate_source_claim_coverage(
        claims
    )

    (
        discounts,
        unconditional_values,
    ) = build_value_lookups(
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
            event_summary,
            component_reconciliation,
        ) = evaluate_component(
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
            "At least one source asset failed reconciliation."
        )

    component = component_reconciliation.iloc[
        0
    ]

    if not bool(
        component[
            "component_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "Protected two-first component reconciliation failed."
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
                f"Allocated value for {asset_key} does not match "
                "the V3 originating-team value."
            )

    (
        baseline_audit,
        baseline_contributions,
    ) = build_baseline_audit(
        source_claims=source_claims,
        valuations=valuations,
    )

    found_baseline_assets = set(
        baseline_contributions[
            "asset_key"
        ].astype(str)
    )

    if found_baseline_assets != EXPECTED_BASELINE_ASSETS:
        raise RuntimeError(
            "The direct baseline asset set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    EXPECTED_BASELINE_ASSETS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_baseline_assets
                )
            )
        )

    baseline_teams = set(
        baseline_contributions[
            "team"
        ].astype(str)
    )

    if baseline_teams != {
        "NOP",
    }:
        raise RuntimeError(
            "The expected New Orleans direct baseline is assigned "
            "to an unexpected team:\n"
            + baseline_contributions.to_string(
                index=False
            )
        )

    expected_nop_baseline = float(
        unconditional_values[
            "2027_R1_NOP"
        ]
    )

    actual_nop_baseline = float(
        baseline_contributions[
            "current_baseline_value_score"
        ].sum()
    )

    if abs(
        actual_nop_baseline
        - expected_nop_baseline
    ) > 1e-8:
        raise RuntimeError(
            "The existing New Orleans direct baseline does not match "
            "its V3 unconditional source value."
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
        source_claims=source_claims,
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
    )

    total_adjustment = float(
        adjustments[
            "net_team_adjustment_value_score"
        ].sum()
    )

    expected_net_adjustment = float(
        unconditional_values[
            "2027_R1_MIL"
        ]
    )

    if abs(
        total_source_value
        - total_candidate_value
    ) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal source value."
        )

    if abs(
        total_adjustment
        - (
            total_source_value
            - total_baseline
        )
    ) > 1e-8:
        raise RuntimeError(
            "Team adjustments do not reconcile to source value "
            "minus the existing New Orleans baseline."
        )

    if abs(
        total_baseline
        - expected_nop_baseline
    ) > 1e-8:
        raise RuntimeError(
            "The component did not remove exactly the existing "
            "New Orleans first-round baseline."
        )

    if abs(
        total_adjustment
        - expected_net_adjustment
    ) > 1e-8:
        raise RuntimeError(
            "The net team adjustment does not equal the previously "
            "unresolved Milwaukee 2027 first-round value."
        )

    if set(
        SOURCE_ASSETS
    ) & FORBIDDEN_SOURCE_ASSETS:
        raise RuntimeError(
            "An unrelated Atlanta, Oklahoma City, Denver, or Toronto "
            "first-round asset was incorrectly included as a source."
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
    event_summary.to_parquet(
        EVENT_SUMMARY_PARQUET_PATH,
        index=False,
    )
    event_summary.to_csv(
        EVENT_SUMMARY_CSV_PATH,
        index=False,
    )
    enriched_valuations.to_parquet(
        V18_VALUATIONS_PARQUET_PATH,
        index=False,
    )
    enriched_valuations.to_csv(
        V18_VALUATIONS_CSV_PATH,
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
        V18_TEAM_SUMMARY_PATH,
        index=False,
    )
    source_reconciliation.to_csv(
        SOURCE_RECONCILIATION_PATH,
        index=False,
    )
    component_reconciliation.to_csv(
        COMPONENT_RECONCILIATION_PATH,
        index=False,
    )
    exhaustive_proof.to_csv(
        EXHAUSTIVE_PROOF_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_group_id": TARGET_GROUP_ID,
        "source_assets_integrated": len(
            SOURCE_ASSETS
        ),
        "source_claim_rows_enriched": len(
            source_claims
        ),
        "source_allocation_rows": len(
            source_allocations
        ),
        "candidate_rights_created": len(
            candidate_rights
        ),
        "joint_simulations": int(
            component[
                "joint_simulation_count"
            ]
        ),
        "exhaustive_unique_slot_assignments_proved": len(
            exhaustive_proof
        ),
        "all_slot_assignments_allocate_sources_once": bool(
            exhaustive_proof[
                "all_two_sources_assigned_once"
            ].all()
        ),
        "total_source_asset_value_score": total_source_value,
        "total_candidate_right_value_score": total_candidate_value,
        "existing_counted_baseline_value_score": total_baseline,
        "expected_unresolved_milwaukee_value_score": (
            expected_net_adjustment
        ),
        "net_team_adjustment_value_score": total_adjustment,
        "protection_hit_probability": float(
            component[
                "protection_hit_probability"
            ]
        ),
        "atlanta_own_first_excluded_from_sources": bool(
            "2027_R1_ATL"
            not in SOURCE_ASSETS
        ),
        "denver_okc_tor_component_excluded_from_sources": bool(
            not (
                {
                    "2027_R1_DEN",
                    "2027_R1_OKC",
                    "2027_R1_TOR",
                }
                & set(
                    SOURCE_ASSETS
                )
            )
        ),
        "all_source_reconciliations_passed": bool(
            source_reconciliation[
                "allocation_reconciliation_passed"
            ].all()
        ),
        "component_reconciliation_passed": bool(
            component[
                "component_reconciliation_passed"
            ]
        ),
        "source_assets": sorted(
            SOURCE_ASSETS
        ),
        "controlling_claim_text": controlling_text,
        "allocation_policy": [
            (
                "Rank New Orleans and Milwaukee's 2027 first-round "
                "picks from more to less favorable."
            ),
            "New Orleans receives the more favorable pick.",
            (
                "Atlanta receives the less favorable pick when it "
                "falls in selections 5-30."
            ),
            (
                "When the less favorable pick falls in selections "
                "1-4, Atlanta's right is extinguished and New Orleans "
                "receives both picks."
            ),
            (
                "All 870 distinct two-team slot assignments are proven "
                "to allocate each physical source exactly once."
            ),
            (
                "The existing New Orleans direct baseline is removed, "
                "so the net adjustment equals Milwaukee's unresolved "
                "source value."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATIONS_PARQUET_PATH
            ),
            "candidate_rights": str(
                CANDIDATE_RIGHTS_PARQUET_PATH
            ),
            "event_summary": str(
                EVENT_SUMMARY_PARQUET_PATH
            ),
            "v18_valuation_layer": str(
                V18_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v18_team_summary": str(
                V18_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
            "exhaustive_slot_proof": str(
                EXHAUSTIVE_PROOF_PATH
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

    branch_summary = (
        exhaustive_proof.groupby(
            "protection_branch",
            as_index=False,
        )
        .agg(
            valid_unique_slot_assignments=(
                "all_two_sources_assigned_once",
                "size",
            ),
            all_sources_assigned_once=(
                "all_two_sources_assigned_once",
                "all",
            ),
            new_orleans_pick_count=(
                "new_orleans_pick_count",
                "first",
            ),
            atlanta_pick_count=(
                "atlanta_pick_count",
                "first",
            ),
        )
    )

    print(
        "=" * 80
    )
    print(
        "PROTECTED TWO-FIRST COMPONENT FULLY INTEGRATED"
    )
    print(
        "=" * 80
    )
    print(
        "Joint simulations: "
        f"{int(component['joint_simulation_count']):,}"
    )
    print(
        "Source assets integrated: "
        f"{len(SOURCE_ASSETS):,}"
    )
    print(
        "Source claim rows enriched: "
        f"{len(source_claims):,}"
    )
    print(
        "Source allocation rows: "
        f"{len(source_allocations):,}"
    )
    print(
        "Candidate rights created: "
        f"{len(candidate_rights):,}"
    )
    print(
        "Exhaustive unique slot assignments proved: "
        f"{len(exhaustive_proof):,}"
    )
    print(
        "Every slot assignment allocates all sources once: "
        f"{bool(exhaustive_proof['all_two_sources_assigned_once'].all())}"
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
        "Existing New Orleans baseline removed: "
        f"{total_baseline:.4f}"
    )
    print(
        "Expected unresolved Milwaukee value: "
        f"{expected_net_adjustment:.4f}"
    )
    print(
        "Net team-value adjustment: "
        f"{total_adjustment:.4f}"
    )
    print(
        "Protection-hit probability: "
        f"{float(component['protection_hit_probability']) * 100.0:.2f}%"
    )
    print(
        "Atlanta own first excluded from sources: "
        f"{'2027_R1_ATL' not in SOURCE_ASSETS}"
    )
    print(
        "Denver-OKC-Toronto component excluded from sources: "
        f"{not bool({'2027_R1_DEN', '2027_R1_OKC', '2027_R1_TOR'} & set(SOURCE_ASSETS))}"
    )
    print(
        "All source reconciliations passed: "
        f"{bool(source_reconciliation['allocation_reconciliation_passed'].all())}"
    )
    print(
        "Component reconciliation passed: "
        f"{bool(component['component_reconciliation_passed'])}"
    )
    print()

    print(
        "CANDIDATE RIGHTS"
    )

    rights_display = candidate_rights.copy()

    for column in [
        "expected_candidate_right_value_score",
        "expected_pick_count",
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

    print(
        "TEAM ADJUSTMENTS"
    )

    adjustment_display = adjustments.copy()

    for column in [
        "protected_component_right_value_score",
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

    print(
        "SOURCE-ASSET RECONCILIATION"
    )

    reconciliation_display = source_reconciliation.copy()

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

    print(
        "PROTECTION EVENT SUMMARY"
    )

    event_display = event_summary.copy()

    event_display[
        "event_probability"
    ] = (
        pd.to_numeric(
            event_display[
                "event_probability"
            ],
            errors="coerce",
        )
        * 100.0
    ).round(
        2
    )

    for column in [
        "expected_pick_when_received",
        "expected_nop_pick_when_event_occurs",
        "expected_mil_pick_when_event_occurs",
    ]:
        event_display[
            column
        ] = pd.to_numeric(
            event_display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        event_display.to_string(
            index=False
        )
    )
    print()

    print(
        "EXHAUSTIVE BRANCH PROOF"
    )
    print(
        branch_summary.to_string(
            index=False
        )
    )
    print()

    print(
        "SAVED FILES"
    )

    for path in [
        SOURCE_ALLOCATIONS_PARQUET_PATH,
        SOURCE_ALLOCATIONS_CSV_PATH,
        CANDIDATE_RIGHTS_PARQUET_PATH,
        CANDIDATE_RIGHTS_CSV_PATH,
        EVENT_SUMMARY_PARQUET_PATH,
        EVENT_SUMMARY_CSV_PATH,
        V18_VALUATIONS_PARQUET_PATH,
        V18_VALUATIONS_CSV_PATH,
        BASELINE_AUDIT_PATH,
        TEAM_ADJUSTMENTS_PATH,
        V18_TEAM_SUMMARY_PATH,
        SOURCE_RECONCILIATION_PATH,
        COMPONENT_RECONCILIATION_PATH,
        EXHAUSTIVE_PROOF_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()