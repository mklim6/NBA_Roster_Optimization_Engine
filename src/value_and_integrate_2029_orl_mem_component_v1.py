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
    "future-pick-2029-orl-mem-protected-swap-fallback-component-v1-2026-08-04"
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

V23_INPUT_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v23_mil_nyk_det_chi_enriched.parquet"
)

V23_INPUT_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v23_mil_nyk_det_chi_provisional.csv"
)

DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2029_orl_mem_group_claims_v1.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_candidate_rights_v1.csv"
)

EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_event_summary_v1.parquet"
)

EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2029_orl_mem_event_summary_v1.csv"
)

V24_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v24_orl_mem_enriched.parquet"
)

V24_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v24_orl_mem_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_team_adjustments_v1.csv"
)

V24_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v24_orl_mem_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_source_reconciliation_v1.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_component_reconciliation_v1.csv"
)

EXHAUSTIVE_SLOT_PROOF_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_exhaustive_slot_proof_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_component_metadata_v1.json"
)


SOURCE_ASSETS = {
    "2029_R1_MEM": (2029, 1, "MEM"),
    "2029_R1_ORL": (2029, 1, "ORL"),
    "2029_R2_ORL": (2029, 2, "ORL"),
}

CANDIDATE_TEAMS = {
    "MEM",
    "ORL",
}

TARGET_GROUP_ID = "OBL_5bbf674a68e1"

REQUIRED_SOURCE_CLAIMS = {
    "2029_R1_MEM_C1",
    "2029_R1_ORL_C1",
    "2029_R2_ORL_C1",
}

EXPECTED_DIAGNOSTIC_CLAIMS = {
    "2029_R1_ORL_C1",
}

EXPECTED_EXISTING_BASELINE_ASSETS = {
    "2029_R1_MEM",
    "2029_R2_ORL",
}

PROTECTED_MAX_SLOT = 2

BRANCH_PROTECTED_FALLBACK = (
    "ORL_PICK_1_2_PROTECTED_SECOND_TO_MEM"
)

BRANCH_SWAP_EXERCISED = (
    "ORL_PICK_3_30_SWAP_EXERCISED"
)

BRANCH_SWAP_NOT_EXERCISED = (
    "ORL_PICK_3_30_SWAP_NOT_EXERCISED"
)

EXPECTED_TEXT_FRAGMENTS = [
    (
        "Memphis has the right to swap its 2029 1st round pick "
        "for Orlando's 2029 1st round pick"
    ),
    "protected for selections 1-2",
    (
        "if this pick falls within its protected range and is therefore "
        "not conveyable"
    ),
    "Orlando will instead convey its 2029 2nd round pick to Memphis",
]

UNRELATED_MEM_SECOND_CLAIM_ID = "2029_R2_MEM_C1"
EXPECTED_UNRELATED_MEM_SECOND_BENEFICIARY = "BKN"


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

    try:
        if pd.isna(
            value
        ):
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


def normalized_text(
    value: Any,
) -> str:
    text = clean_text(
        value
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
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

    return (
        number
        if np.isfinite(
            number
        )
        else 0.0
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
        return (
            None
            if np.isnan(
                value
            )
            else float(
                value
            )
        )

    if isinstance(
        value,
        float,
    ):
        return (
            None
            if math.isnan(
                value
            )
            else value
        )

    try:
        if pd.isna(
            value
        ):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

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
        ].astype(
            int
        )

        missing = sorted(
            {
                team
                for _, _, team in SOURCE_ASSETS.values()
            }
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

        for row in curve.itertuples(
            index=False
        ):
            self.value[
                int(
                    row.overall_pick
                )
            ] = float(
                row.historical_pick_value_score
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
]:
    required_paths = [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        V23_INPUT_VALUATIONS_PATH,
        V23_INPUT_TEAM_SUMMARY_PATH,
        DIAGNOSTIC_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required V24 component input was not found:\n"
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
            V23_INPUT_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V23_INPUT_TEAM_SUMMARY_PATH
        )
    )

    diagnostic = normalize_columns(
        pd.read_csv(
            DIAGNOSTIC_PATH
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
        "V23 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_mil_nyk_det_chi_component_provisional"
            ),
        ],
        "V23 provisional team summary",
    )

    require_columns(
        diagnostic,
        [
            "claim_id",
            "asset_key",
        ],
        "ORL-MEM diagnostic",
    )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        diagnostic,
    )


def validate_diagnostic(
    diagnostic: pd.DataFrame,
) -> None:
    claim_ids = set(
        diagnostic[
            "claim_id"
        ].astype(
            str
        )
    )

    asset_keys = set(
        diagnostic[
            "asset_key"
        ].astype(
            str
        )
    )

    if claim_ids != EXPECTED_DIAGNOSTIC_CLAIMS:
        raise ValueError(
            "The ORL-MEM diagnostic claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    EXPECTED_DIAGNOSTIC_CLAIMS
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
        "2029_R1_ORL",
    }:
        raise ValueError(
            "The ORL-MEM diagnostic target asset changed."
        )


def validate_controlling_text(
    claims: pd.DataFrame,
) -> str:
    match = claims.loc[
        claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            "2029_R1_ORL_C1"
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected exactly one Orlando 2029 first-round claim."
        )

    text = clean_text(
        match.iloc[
            0
        ][
            "full_obligation_text"
        ]
    )

    normalized = normalized_text(
        text
    )

    missing = [
        fragment
        for fragment in EXPECTED_TEXT_FRAGMENTS
        if normalized_text(
            fragment
        )
        not in normalized
    ]

    if missing:
        raise ValueError(
            "The Orlando-Memphis controlling text changed. "
            "Missing fragments:\n"
            + "\n".join(
                missing
            )
        )

    return text


def validate_source_claim_coverage(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    source_claims = claims.loc[
        claims[
            "asset_key"
        ]
        .astype(
            str
        )
        .isin(
            SOURCE_ASSETS
        )
    ].copy()

    found_assets = set(
        source_claims[
            "asset_key"
        ].astype(
            str
        )
    )

    if found_assets != set(
        SOURCE_ASSETS
    ):
        raise ValueError(
            "The physical source asset set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    SOURCE_ASSETS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_assets
                )
            )
        )

    found_claims = set(
        source_claims[
            "claim_id"
        ].astype(
            str
        )
    )

    if found_claims != REQUIRED_SOURCE_CLAIMS:
        raise ValueError(
            "The physical source claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    REQUIRED_SOURCE_CLAIMS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_claims
                )
            )
        )

    asset_counts = (
        source_claims.groupby(
            "asset_key"
        )[
            "claim_id"
        ]
        .nunique()
    )

    if not asset_counts.eq(
        1
    ).all():
        raise ValueError(
            "Each physical source must have exactly one claim row:\n"
            + asset_counts.to_string()
        )

    return source_claims.sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def validate_unrelated_memphis_second(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    row = valuations.loc[
        valuations[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            UNRELATED_MEM_SECOND_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one unrelated Memphis 2029 second claim."
        )

    if clean_text(
        row.iloc[
            0
        ].get(
            "valuation_method",
            "",
        )
    ) != "direct_asset_value":
        raise ValueError(
            "Memphis's 2029 second no longer has its expected direct "
            "valuation."
        )

    if clean_text(
        row.iloc[
            0
        ].get(
            "valuation_status",
            "",
        )
    ) != "valued_direct_candidate":
        raise ValueError(
            "Memphis's 2029 second no longer has valued direct status."
        )

    if clean_text(
        row.iloc[
            0
        ].get(
            "candidate_beneficiary_team",
            "",
        )
    ) != EXPECTED_UNRELATED_MEM_SECOND_BENEFICIARY:
        raise ValueError(
            "Memphis's 2029 second is no longer assigned to Brooklyn."
        )

    return row.reset_index(
        drop=True
    )


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
            .astype(
                str
            )
            .eq(
                team
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                f"Expected one V3 pick-value row for {asset_key}; "
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

    return (
        discounts,
        unconditional_values,
    )


def allocate_component(
    mem_first_slot: int,
    orl_first_slot: int,
) -> tuple[
    dict[str, list[str]],
    str,
]:
    if int(
        orl_first_slot
    ) <= PROTECTED_MAX_SLOT:
        return (
            {
                "MEM": [
                    "2029_R1_MEM",
                    "2029_R2_ORL",
                ],
                "ORL": [
                    "2029_R1_ORL",
                ],
            },
            BRANCH_PROTECTED_FALLBACK,
        )

    if int(
        orl_first_slot
    ) < int(
        mem_first_slot
    ):
        return (
            {
                "MEM": [
                    "2029_R1_ORL",
                ],
                "ORL": [
                    "2029_R1_MEM",
                    "2029_R2_ORL",
                ],
            },
            BRANCH_SWAP_EXERCISED,
        )

    return (
        {
            "MEM": [
                "2029_R1_MEM",
            ],
            "ORL": [
                "2029_R1_ORL",
                "2029_R2_ORL",
            ],
        },
        BRANCH_SWAP_NOT_EXERCISED,
    )


def prove_allocation_closure() -> pd.DataFrame:
    rows = []

    for mem_slot in range(
        1,
        31,
    ):
        for orl_slot in range(
            1,
            31,
        ):
            if mem_slot == orl_slot:
                continue

            (
                allocation,
                branch,
            ) = allocate_component(
                mem_first_slot=mem_slot,
                orl_first_slot=orl_slot,
            )

            assigned = (
                allocation[
                    "MEM"
                ]
                + allocation[
                    "ORL"
                ]
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
                        "MEM"
                    ]
                )
                + len(
                    allocation[
                        "ORL"
                    ]
                )
                == 3
            )

            protected_logic_passed = bool(
                (
                    branch
                    == BRANCH_PROTECTED_FALLBACK
                )
                == (
                    orl_slot
                    <= PROTECTED_MAX_SLOT
                )
            )

            exercise_logic_passed = bool(
                (
                    branch
                    == BRANCH_SWAP_EXERCISED
                )
                == (
                    orl_slot
                    > PROTECTED_MAX_SLOT
                    and orl_slot
                    < mem_slot
                )
            )

            if branch == BRANCH_PROTECTED_FALLBACK:
                ownership_logic_passed = bool(
                    allocation[
                        "MEM"
                    ]
                    == [
                        "2029_R1_MEM",
                        "2029_R2_ORL",
                    ]
                    and allocation[
                        "ORL"
                    ]
                    == [
                        "2029_R1_ORL",
                    ]
                )
            elif branch == BRANCH_SWAP_EXERCISED:
                ownership_logic_passed = bool(
                    allocation[
                        "MEM"
                    ]
                    == [
                        "2029_R1_ORL",
                    ]
                    and allocation[
                        "ORL"
                    ]
                    == [
                        "2029_R1_MEM",
                        "2029_R2_ORL",
                    ]
                )
            else:
                ownership_logic_passed = bool(
                    allocation[
                        "MEM"
                    ]
                    == [
                        "2029_R1_MEM",
                    ]
                    and allocation[
                        "ORL"
                    ]
                    == [
                        "2029_R1_ORL",
                        "2029_R2_ORL",
                    ]
                )

            rows.append(
                {
                    "mem_first_slot": mem_slot,
                    "orl_first_slot": orl_slot,
                    "branch": branch,
                    "memphis_receives": "|".join(
                        allocation[
                            "MEM"
                        ]
                    ),
                    "orlando_receives": "|".join(
                        allocation[
                            "ORL"
                        ]
                    ),
                    "memphis_pick_count": len(
                        allocation[
                            "MEM"
                        ]
                    ),
                    "orlando_pick_count": len(
                        allocation[
                            "ORL"
                        ]
                    ),
                    "all_three_sources_assigned_once": closure_passed,
                    "protection_logic_passed": protected_logic_passed,
                    "exercise_logic_passed": exercise_logic_passed,
                    "ownership_logic_passed": ownership_logic_passed,
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
            "Memphis-Orlando first-round slot assignments."
        )

    required_checks = [
        "all_three_sources_assigned_once",
        "protection_logic_passed",
        "exercise_logic_passed",
        "ownership_logic_passed",
    ]

    if not proof[
        required_checks
    ].all().all():
        raise RuntimeError(
            "The protected swap-fallback component failed an exhaustive "
            "proof check."
        )

    branch_counts = (
        proof[
            "branch"
        ]
        .value_counts()
        .to_dict()
    )

    expected_counts = {
        BRANCH_PROTECTED_FALLBACK: 58,
        BRANCH_SWAP_EXERCISED: 378,
        BRANCH_SWAP_NOT_EXERCISED: 434,
    }

    if branch_counts != expected_counts:
        raise RuntimeError(
            "Exhaustive branch counts changed.\nExpected:\n"
            + json.dumps(
                expected_counts,
                indent=2,
                sort_keys=True,
            )
            + "\nFound:\n"
            + json.dumps(
                branch_counts,
                indent=2,
                sort_keys=True,
            )
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
            "ORL-MEM simulation arrays do not align."
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

    event_rows: list[
        dict[str, Any]
    ] = []

    for simulation_index in range(
        simulation_count
    ):
        mem_slot = int(
            slots[
                "2029_R1_MEM"
            ][
                simulation_index
            ]
        )

        orl_slot = int(
            slots[
                "2029_R1_ORL"
            ][
                simulation_index
            ]
        )

        (
            allocation,
            branch,
        ) = allocate_component(
            mem_first_slot=mem_slot,
            orl_first_slot=orl_slot,
        )

        branch_array[
            simulation_index
        ] = branch

        assigned = (
            allocation[
                "MEM"
            ]
            + allocation[
                "ORL"
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
                "A simulation did not assign all three physical sources "
                "exactly once."
            )

        for candidate_team in sorted(
            CANDIDATE_TEAMS
        ):
            for asset_key in allocation[
                candidate_team
            ]:
                owner_arrays[
                    asset_key
                ][
                    simulation_index
                ] = candidate_team

                if branch == BRANCH_PROTECTED_FALLBACK:
                    if asset_key == "2029_R2_ORL":
                        role = "protected_fallback_second"
                    else:
                        role = "retained_own"
                elif branch == BRANCH_SWAP_EXERCISED:
                    if candidate_team == "MEM":
                        role = "swap_incoming"
                    elif asset_key == "2029_R1_MEM":
                        role = "swap_outgoing_received"
                    else:
                        role = "retained_own"
                else:
                    role = "retained_own"

                event_rows.append(
                    {
                        "simulation_id": int(
                            bank.simulation_ids[
                                simulation_index
                            ]
                        ),
                        "event_type": "candidate_receipt",
                        "event_outcome": branch,
                        "candidate_team": candidate_team,
                        "source_asset_key": asset_key,
                        "allocation_role": role,
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
            CANDIDATE_TEAMS
        ):
            condition = (
                owner_array
                == candidate_team
            )

            probability = float(
                np.mean(
                    condition
                )
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

            expected_pick = (
                float(
                    np.mean(
                        slots[
                            asset_key
                        ][
                            condition
                        ]
                    )
                )
                if condition.any()
                else np.nan
            )

            allocation_rows.append(
                {
                    "source_asset_key": asset_key,
                    "source_team": SOURCE_ASSETS[
                        asset_key
                    ][
                        2
                    ],
                    "candidate_team": candidate_team,
                    "allocation_probability": probability,
                    "expected_allocated_value_score": expected_value,
                    "expected_pick_when_allocated": expected_pick,
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
                        for team in CANDIDATE_TEAMS
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

    raw_events = pd.DataFrame(
        event_rows
    )

    event_summary = (
        raw_events.groupby(
            [
                "event_type",
                "event_outcome",
                "candidate_team",
                "source_asset_key",
                "allocation_role",
            ],
            as_index=False,
        )
        .agg(
            event_count=(
                "simulation_id",
                "size",
            ),
            expected_pick_when_received=(
                "overall_pick",
                "mean",
            ),
        )
    )

    event_summary[
        "event_probability"
    ] = (
        event_summary[
            "event_count"
        ]
        / simulation_count
    )

    branch_rows = []

    for branch in [
        BRANCH_PROTECTED_FALLBACK,
        BRANCH_SWAP_EXERCISED,
        BRANCH_SWAP_NOT_EXERCISED,
    ]:
        condition = (
            branch_array
            == branch
        )

        branch_rows.append(
            {
                "event_type": "branch",
                "event_outcome": branch,
                "candidate_team": "",
                "source_asset_key": "",
                "allocation_role": "",
                "event_count": int(
                    condition.sum()
                ),
                "expected_pick_when_received": np.nan,
                "event_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_mem_first_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2029_R1_MEM"
                        ][
                            condition
                        ]
                    )
                ),
                "expected_orl_first_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2029_R1_ORL"
                        ][
                            condition
                        ]
                    )
                ),
                "expected_orl_second_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2029_R2_ORL"
                        ][
                            condition
                        ]
                    )
                ),
            }
        )

    event_summary[
        "expected_mem_first_pick_when_event_occurs"
    ] = np.nan

    event_summary[
        "expected_orl_first_pick_when_event_occurs"
    ] = np.nan

    event_summary[
        "expected_orl_second_pick_when_event_occurs"
    ] = np.nan

    event_summary = pd.concat(
        [
            pd.DataFrame(
                branch_rows
            ),
            event_summary,
        ],
        ignore_index=True,
        sort=False,
    )

    event_summary = event_summary.sort_values(
        [
            "event_type",
            "event_outcome",
            "candidate_team",
            "source_asset_key",
        ]
    ).reset_index(
        drop=True
    )

    expected_pick_counts = (
        candidate_rights.set_index(
            "candidate_team"
        )[
            "expected_pick_count"
        ]
        .to_dict()
    )

    protected_probability = float(
        np.mean(
            branch_array
            == BRANCH_PROTECTED_FALLBACK
        )
    )

    swap_exercise_probability = float(
        np.mean(
            branch_array
            == BRANCH_SWAP_EXERCISED
        )
    )

    swap_not_exercised_probability = float(
        np.mean(
            branch_array
            == BRANCH_SWAP_NOT_EXERCISED
        )
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
                "total_source_asset_value_score": total_source_value,
                "total_candidate_right_value_score": total_candidate_value,
                "total_candidate_pick_count": float(
                    candidate_rights[
                        "expected_pick_count"
                    ].sum()
                ),
                "memphis_expected_pick_count": float(
                    expected_pick_counts.get(
                        "MEM",
                        np.nan,
                    )
                ),
                "orlando_expected_pick_count": float(
                    expected_pick_counts.get(
                        "ORL",
                        np.nan,
                    )
                ),
                "protected_fallback_probability": protected_probability,
                "swap_exercise_probability": swap_exercise_probability,
                "swap_not_exercised_probability": (
                    swap_not_exercised_probability
                ),
                "value_difference": (
                    total_candidate_value
                    - total_source_value
                ),
                "component_reconciliation_passed": bool(
                    abs(
                        total_candidate_value
                        - total_source_value
                    )
                    <= 1e-8
                    and abs(
                        candidate_rights[
                            "expected_pick_count"
                        ].sum()
                        - 3.0
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get(
                            "MEM",
                            np.nan,
                        )
                        - (
                            1.0
                            + protected_probability
                        )
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get(
                            "ORL",
                            np.nan,
                        )
                        - (
                            2.0
                            - protected_probability
                        )
                    )
                    <= 1e-10
                    and abs(
                        protected_probability
                        + swap_exercise_probability
                        + swap_not_exercised_probability
                        - 1.0
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
        .astype(
            str
        )
        .str.startswith(
            "valued_"
        )
    )

    allowed_direct = (
        audit[
            "valuation_method"
        ]
        .fillna("")
        .astype(
            str
        )
        .eq(
            "direct_asset_value"
        )
        | audit[
            "valuation_status"
        ]
        .fillna("")
        .astype(
            str
        )
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
            "A source is already represented by a non-direct component:\n"
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

    contribution_rows: list[
        dict[str, Any]
    ] = []

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

            if value > 0.0:
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
                    "claim_id": row.claim_id,
                    "asset_key": row.asset_key,
                    "team": team,
                    "current_baseline_value_score": value,
                    "baseline_component_type": "direct_asset",
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

    found_assets = set(
        contributions[
            "asset_key"
        ].astype(
            str
        )
    )

    if found_assets != EXPECTED_EXISTING_BASELINE_ASSETS:
        raise RuntimeError(
            "The existing baseline asset set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    EXPECTED_EXISTING_BASELINE_ASSETS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_assets
                )
            )
        )

    team_by_asset = (
        contributions.set_index(
            "asset_key"
        )[
            "team"
        ]
        .to_dict()
    )

    if team_by_asset != {
        "2029_R1_MEM": "MEM",
        "2029_R2_ORL": "ORL",
    }:
        raise RuntimeError(
            "The existing direct baselines are assigned to unexpected "
            "teams:\n"
            + contributions.to_string(
                index=False
            )
        )

    return (
        audit,
        contributions,
    )


def validate_existing_baselines(
    baseline_contributions: pd.DataFrame,
    unconditional_values: dict[str, float],
) -> None:
    for asset_key in sorted(
        EXPECTED_EXISTING_BASELINE_ASSETS
    ):
        actual = float(
            baseline_contributions.loc[
                baseline_contributions[
                    "asset_key"
                ]
                .astype(
                    str
                )
                .eq(
                    asset_key
                ),
                "current_baseline_value_score",
            ].sum()
        )

        expected = float(
            unconditional_values[
                asset_key
            ]
        )

        if abs(
            actual
            - expected
        ) > 1e-8:
            raise RuntimeError(
                f"The existing baseline for {asset_key} does not match "
                "its V3 unconditional value."
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
    )

    rows = []

    for team in sorted(
        CANDIDATE_TEAMS
    ):
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
                "orl_mem_component_right_value_score": new_value,
                "existing_counted_baseline_value_score": baseline,
                "net_team_adjustment_value_score": (
                    new_value
                    - baseline
                ),
                "adjustment_scope": (
                    "replace_memphis_first_and_orlando_second_baselines_"
                    "with_joint_protected_swap_fallback_rights"
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
        "after_mil_nyk_det_chi_component_provisional"
    )

    before_column = (
        "candidate_total_pick_asset_value_score_"
        "before_orl_mem_component"
    )

    adjustment_column = (
        "orl_mem_component_adjustment_value_score"
    )

    after_column = (
        "candidate_total_pick_asset_value_score_"
        "after_orl_mem_component_provisional"
    )

    output[
        before_column
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
        adjustment_column
    ] = (
        output[
            "candidate_beneficiary_team"
        ]
        .astype(
            str
        )
        .map(
            adjustment_lookup
        )
        .fillna(
            0.0
        )
    )

    output[
        after_column
    ] = (
        output[
            before_column
        ]
        + output[
            adjustment_column
        ]
    )

    output[
        "orl_mem_component_status"
    ] = (
        "fully_integrated_protected_swap_with_second_round_fallback"
    )

    output[
        "orl_mem_component_scope_note"
    ] = (
        "Memphis may swap its 2029 first for Orlando's 2029 first "
        "when Orlando's pick is outside the protected 1-2 range and "
        "is more favorable. If Orlando's first lands 1-2, Orlando "
        "retains it and conveys its 2029 second to Memphis instead."
    )

    return output.sort_values(
        after_column,
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
        "orl_mem_component_modeled_flag": False,
        "orl_mem_component_primary_claim_flag": False,
        "orl_mem_source_asset_value_score": np.nan,
        "orl_mem_candidate_allocations_json": "",
    }

    for column, default in defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    for asset_key, claim_group in source_claims.groupby(
        "asset_key",
        sort=True,
    ):
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
                ): {
                    "expected_value_score": float(
                        row.expected_allocated_value_score
                    ),
                    "allocation_probability": float(
                        row.allocation_probability
                    ),
                }
                for row in source_rows.itertuples(
                    index=False
                )
            },
            sort_keys=True,
        )

        primary_claim_id = str(
            claim_group.sort_values(
                "claim_id"
            ).iloc[
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
                .astype(
                    str
                )
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
                "joint_2029_orl_mem_protected_swap_fallback_source_allocation"
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
                "orl_mem_component_modeled_flag",
            ] = True

            output.loc[
                mask,
                "orl_mem_component_primary_claim_flag",
            ] = primary_flag

            output.loc[
                mask,
                "orl_mem_source_asset_value_score",
            ] = (
                source_value
                if primary_flag
                else np.nan
            )

            output.loc[
                mask,
                "orl_mem_candidate_allocations_json",
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
                    "joint 2029 Orlando-Memphis protected first-round "
                    "swap with Orlando second-round fallback. Candidate "
                    "rights are stored separately to prevent duplicate "
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

    print(
        "=" * 80
    )
    print(
        "2029 ORL-MEM PROTECTED SWAP WITH SECOND-ROUND FALLBACK"
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
        diagnostic,
    ) = load_inputs()

    validate_diagnostic(
        diagnostic
    )

    controlling_text = validate_controlling_text(
        claims
    )

    source_claims = validate_source_claim_coverage(
        claims
    )

    unrelated_mem_second_before = validate_unrelated_memphis_second(
        valuations
    )

    exhaustive_slot_proof = prove_allocation_closure()

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
            "At least one physical source failed reconciliation."
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
            "The Orlando-Memphis component failed reconciliation."
        )

    for asset_key, expected_value in unconditional_values.items():
        actual_value = float(
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
            actual_value
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

    validate_existing_baselines(
        baseline_contributions=baseline_contributions,
        unconditional_values=unconditional_values,
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

    unrelated_mem_second_after = validate_unrelated_memphis_second(
        enriched_valuations
    )

    comparison_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "expected_total_candidate_asset_value_score",
        ]
        if column in unrelated_mem_second_before.columns
        and column in unrelated_mem_second_after.columns
    ]

    if not unrelated_mem_second_before[
        comparison_columns
    ].equals(
        unrelated_mem_second_after[
            comparison_columns
        ]
    ):
        raise RuntimeError(
            "The unrelated Memphis 2029 second-to-Brooklyn claim changed "
            "during V24 integration."
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

    expected_unresolved_value = float(
        unconditional_values[
            "2029_R1_ORL"
        ]
    )

    expected_baseline = float(
        unconditional_values[
            "2029_R1_MEM"
        ]
        + unconditional_values[
            "2029_R2_ORL"
        ]
    )

    if abs(
        total_source_value
        - total_candidate_value
    ) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal physical source value."
        )

    if abs(
        total_baseline
        - expected_baseline
    ) > 1e-8:
        raise RuntimeError(
            "The component did not remove exactly the Memphis first and "
            "Orlando second direct baselines."
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
            "existing baselines."
        )

    if abs(
        total_adjustment
        - expected_unresolved_value
    ) > 1e-8:
        raise RuntimeError(
            "The net adjustment does not equal the previously unresolved "
            "Orlando 2029 first-round value."
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
        V24_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V24_VALUATIONS_CSV_PATH,
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
        V24_TEAM_SUMMARY_PATH,
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

    exhaustive_slot_proof.to_csv(
        EXHAUSTIVE_SLOT_PROOF_PATH,
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
        "exhaustive_slot_assignments_proved": len(
            exhaustive_slot_proof
        ),
        "all_slot_assignments_allocate_sources_once": bool(
            exhaustive_slot_proof[
                "all_three_sources_assigned_once"
            ].all()
        ),
        "total_source_asset_value_score": total_source_value,
        "total_candidate_right_value_score": total_candidate_value,
        "existing_counted_baseline_value_score": total_baseline,
        "expected_unresolved_orlando_first_value_score": (
            expected_unresolved_value
        ),
        "net_team_adjustment_value_score": total_adjustment,
        "protected_fallback_probability": float(
            component[
                "protected_fallback_probability"
            ]
        ),
        "swap_exercise_probability": float(
            component[
                "swap_exercise_probability"
            ]
        ),
        "swap_not_exercised_probability": float(
            component[
                "swap_not_exercised_probability"
            ]
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
        "unrelated_memphis_second_preserved": True,
        "controlling_claim_text": controlling_text,
        "source_assets": sorted(
            SOURCE_ASSETS
        ),
        "allocation_policy": [
            (
                "If Orlando's 2029 first lands 1-2, Orlando retains its "
                "first, Memphis retains its first, and Orlando's 2029 "
                "second is conveyed to Memphis."
            ),
            (
                "If Orlando's first lands 3-30 and is more favorable than "
                "Memphis's first, Memphis receives Orlando's first and "
                "Orlando receives Memphis's first."
            ),
            (
                "If Orlando's first lands 3-30 and is not more favorable, "
                "both teams retain their own firsts."
            ),
            (
                "Orlando retains its 2029 second in every non-protected "
                "branch."
            ),
            (
                "Memphis's first and Orlando's second direct baselines are "
                "removed and replaced by conditional source allocations."
            ),
            (
                "Memphis's separate 2029 second to Brooklyn is preserved."
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
            "v24_valuation_layer": str(
                V24_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v24_team_summary": str(
                V24_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
            "exhaustive_slot_proof": str(
                EXHAUSTIVE_SLOT_PROOF_PATH
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

    print(
        "=" * 80
    )
    print(
        "PROTECTED SWAP-FALLBACK COMPONENT FULLY INTEGRATED"
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
        "Exhaustive distinct first-round slot assignments proved: "
        f"{len(exhaustive_slot_proof):,}"
    )
    print(
        "Every slot assignment allocates all sources once: "
        f"{bool(exhaustive_slot_proof['all_three_sources_assigned_once'].all())}"
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
        "Existing MEM-first plus ORL-second baselines removed: "
        f"{total_baseline:.4f}"
    )
    print(
        "Expected unresolved Orlando-first value: "
        f"{expected_unresolved_value:.4f}"
    )
    print(
        "Net team-value adjustment: "
        f"{total_adjustment:.4f}"
    )
    print(
        "Protected 1-2 fallback probability: "
        f"{float(component['protected_fallback_probability']) * 100.0:.2f}%"
    )
    print(
        "Swap exercise probability: "
        f"{float(component['swap_exercise_probability']) * 100.0:.2f}%"
    )
    print(
        "Swap not exercised probability: "
        f"{float(component['swap_not_exercised_probability']) * 100.0:.2f}%"
    )
    print(
        "Unrelated Memphis second to Brooklyn preserved: True"
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
        "orl_mem_component_right_value_score",
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
        "BRANCH EVENT SUMMARY"
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
        "expected_mem_first_pick_when_event_occurs",
        "expected_orl_first_pick_when_event_occurs",
        "expected_orl_second_pick_when_event_occurs",
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
        "EXHAUSTIVE SLOT-ASSIGNMENT PROOF"
    )

    proof_summary = (
        exhaustive_slot_proof.groupby(
            "branch",
            as_index=False,
        )
        .agg(
            valid_distinct_slot_assignments=(
                "mem_first_slot",
                "count",
            ),
            all_sources_assigned_once=(
                "all_three_sources_assigned_once",
                "all",
            ),
            protection_logic_passed=(
                "protection_logic_passed",
                "all",
            ),
            exercise_logic_passed=(
                "exercise_logic_passed",
                "all",
            ),
            ownership_logic_passed=(
                "ownership_logic_passed",
                "all",
            ),
        )
    )

    print(
        proof_summary.to_string(
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
        V24_VALUATIONS_PARQUET_PATH,
        V24_VALUATIONS_CSV_PATH,
        BASELINE_AUDIT_PATH,
        TEAM_ADJUSTMENTS_PATH,
        V24_TEAM_SUMMARY_PATH,
        SOURCE_RECONCILIATION_PATH,
        COMPONENT_RECONCILIATION_PATH,
        EXHAUSTIVE_SLOT_PROOF_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()
