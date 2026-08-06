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
    "future-pick-2027-sas-sac-okc-cha-linked-component-v1-2026-08-04"
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

V20_INPUT_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v20_lal_was_orl_enriched.parquet"
)

V20_INPUT_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v20_lal_was_orl_provisional.csv"
)

LINKED_DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2027_sas_sac_okc_cha_linked_claims_v1.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_candidate_rights_v1.csv"
)

EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_event_summary_v1.parquet"
)

EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_event_summary_v1.csv"
)

V21_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v21_sas_sac_okc_cha_enriched.parquet"
)

V21_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v21_sas_sac_okc_cha_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_team_adjustments_v1.csv"
)

V21_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v21_sas_sac_okc_cha_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_source_reconciliation_v1.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_component_reconciliation_v1.csv"
)

BRANCH_SLOT_PROOF_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_branch_slot_proof_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_component_metadata_v1.json"
)


SOURCE_ASSETS = {
    "2027_R1_SAS": (2027, 1, "SAS"),
    "2027_R2_SAC": (2027, 2, "SAC"),
    "2027_R2_CHA": (2027, 2, "CHA"),
}

CANDIDATE_TEAMS = {
    "SAC",
    "OKC",
}

REQUIRED_LINKED_DIAGNOSTIC_CLAIMS = {
    "2027_R1_SAS_C1",
    "2027_R2_CHA_C1",
}

REQUIRED_SOURCE_CLAIMS = {
    "2027_R1_SAS_C1",
    "2027_R2_SAC_C1",
    "2027_R2_CHA_C1",
}

EXPECTED_EXISTING_BASELINE_ASSETS = {
    "2027_R2_SAC",
}

SAS_PROTECTED_MAX_SLOT = 16

BRANCH_SAS_1_16 = (
    "SAS_PICK_1_16_FIRST_TO_SAC_SECONDS_TO_OKC"
)

BRANCH_SAS_17_30 = (
    "SAS_PICK_17_30_FIRST_TO_OKC_SECONDS_TO_SAC"
)

EXPECTED_SAS_TEXT_FRAGMENTS = [
    (
        "San Antonio's 2027 1st round pick to Sacramento "
        "protected for selections 17-30"
    ),
    "to Oklahoma City protected for selections 1-16",
    "if this pick falls within its protected range of 1-16",
    (
        "Sacramento will instead convey its 2027 2nd round pick "
        "and Charlotte's 2027 2nd round pick to Oklahoma City"
    ),
    (
        "San Antonio's obligation to Oklahoma City and Sacramento "
        "will thereafter be extinguished"
    ),
]

EXPECTED_CHA_TEXT_FRAGMENTS = [
    "Charlotte's 2027 2nd round pick to Sacramento",
    "Sacramento may convey this pick to Oklahoma City",
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
        V20_INPUT_VALUATIONS_PATH,
        V20_INPUT_TEAM_SUMMARY_PATH,
        LINKED_DIAGNOSTIC_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required V21 linked-component input was not found:\n"
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
            V20_INPUT_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V20_INPUT_TEAM_SUMMARY_PATH
        )
    )

    linked_diagnostic = normalize_columns(
        pd.read_csv(
            LINKED_DIAGNOSTIC_PATH
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
        "V20 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_lal_was_orl_component_provisional"
            ),
        ],
        "V20 provisional team summary",
    )

    require_columns(
        linked_diagnostic,
        [
            "claim_id",
            "asset_key",
        ],
        "SAS-SAC-OKC-CHA linked diagnostic",
    )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        linked_diagnostic,
    )


def validate_linked_diagnostic(
    linked_diagnostic: pd.DataFrame,
) -> None:
    claim_ids = set(
        linked_diagnostic[
            "claim_id"
        ].astype(
            str
        )
    )

    asset_keys = set(
        linked_diagnostic[
            "asset_key"
        ].astype(
            str
        )
    )

    if claim_ids != REQUIRED_LINKED_DIAGNOSTIC_CLAIMS:
        raise ValueError(
            "The linked diagnostic claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    REQUIRED_LINKED_DIAGNOSTIC_CLAIMS
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
        "2027_R1_SAS",
        "2027_R2_CHA",
    }:
        raise ValueError(
            "The linked diagnostic source set changed."
        )


def validate_controlling_text(
    claims: pd.DataFrame,
) -> dict[str, str]:
    output: dict[
        str,
        str,
    ] = {}

    checks = {
        "2027_R1_SAS_C1": (
            EXPECTED_SAS_TEXT_FRAGMENTS
        ),
        "2027_R2_CHA_C1": (
            EXPECTED_CHA_TEXT_FRAGMENTS
        ),
    }

    for claim_id, expected_fragments in checks.items():
        match = claims.loc[
            claims[
                "claim_id"
            ]
            .astype(
                str
            )
            .eq(
                claim_id
            )
        ]

        if len(
            match
        ) != 1:
            raise ValueError(
                f"Expected exactly one controlling claim for {claim_id}; "
                f"found {len(match)}."
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
            for fragment in expected_fragments
            if normalized_text(
                fragment
            )
            not in normalized
        ]

        if missing:
            raise ValueError(
                f"Controlling claim {claim_id} is missing clauses:\n"
                + "\n".join(
                    missing
                )
            )

        output[
            claim_id
        ] = text

    return output


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


def allocate_branch(
    sas_first_slot: int,
) -> tuple[
    dict[str, list[str]],
    str,
]:
    if int(
        sas_first_slot
    ) <= SAS_PROTECTED_MAX_SLOT:
        return (
            {
                "SAC": [
                    "2027_R1_SAS",
                ],
                "OKC": [
                    "2027_R2_SAC",
                    "2027_R2_CHA",
                ],
            },
            BRANCH_SAS_1_16,
        )

    return (
        {
            "SAC": [
                "2027_R2_SAC",
                "2027_R2_CHA",
            ],
            "OKC": [
                "2027_R1_SAS",
            ],
        },
        BRANCH_SAS_17_30,
    )


def prove_branch_slot_closure() -> pd.DataFrame:
    rows = []

    for sas_first_slot in range(
        1,
        31,
    ):
        (
            allocation,
            branch,
        ) = allocate_branch(
            sas_first_slot
        )

        assigned = (
            allocation[
                "SAC"
            ]
            + allocation[
                "OKC"
            ]
        )

        expected_sac_count = (
            1
            if sas_first_slot
            <= SAS_PROTECTED_MAX_SLOT
            else 2
        )

        expected_okc_count = (
            2
            if sas_first_slot
            <= SAS_PROTECTED_MAX_SLOT
            else 1
        )

        passed = bool(
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
                    "SAC"
                ]
            )
            == expected_sac_count
            and len(
                allocation[
                    "OKC"
                ]
            )
            == expected_okc_count
        )

        rows.append(
            {
                "sas_first_slot": sas_first_slot,
                "branch": branch,
                "sacramento_sources": "|".join(
                    allocation[
                        "SAC"
                    ]
                ),
                "oklahoma_city_sources": "|".join(
                    allocation[
                        "OKC"
                    ]
                ),
                "sacramento_pick_count": len(
                    allocation[
                        "SAC"
                    ]
                ),
                "oklahoma_city_pick_count": len(
                    allocation[
                        "OKC"
                    ]
                ),
                "all_three_sources_assigned_once": passed,
            }
        )

    proof = pd.DataFrame(
        rows
    )

    if len(
        proof
    ) != 30:
        raise RuntimeError(
            "Branch proof did not evaluate all 30 first-round slots."
        )

    if not proof[
        "all_three_sources_assigned_once"
    ].all():
        raise RuntimeError(
            "At least one first-round slot failed branch closure."
        )

    branch_counts = (
        proof[
            "branch"
        ]
        .value_counts()
        .to_dict()
    )

    if branch_counts.get(
        BRANCH_SAS_1_16,
        0,
    ) != 16:
        raise RuntimeError(
            "The SAS 1-16 proof branch did not contain 16 slots."
        )

    if branch_counts.get(
        BRANCH_SAS_17_30,
        0,
    ) != 14:
        raise RuntimeError(
            "The SAS 17-30 proof branch did not contain 14 slots."
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
            "Linked-component simulation arrays do not align."
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

    sas_1_16 = (
        slots[
            "2027_R1_SAS"
        ]
        <= SAS_PROTECTED_MAX_SLOT
    )

    branch_array = np.where(
        sas_1_16,
        BRANCH_SAS_1_16,
        BRANCH_SAS_17_30,
    )

    owner_arrays = {
        "2027_R1_SAS": np.where(
            sas_1_16,
            "SAC",
            "OKC",
        ),
        "2027_R2_SAC": np.where(
            sas_1_16,
            "OKC",
            "SAC",
        ),
        "2027_R2_CHA": np.where(
            sas_1_16,
            "OKC",
            "SAC",
        ),
    }

    for asset_key, owner_array in owner_arrays.items():
        if np.any(
            owner_array
            == ""
        ):
            raise RuntimeError(
                f"{asset_key} has at least one missing owner."
            )

        if set(
            owner_array.tolist()
        ) != CANDIDATE_TEAMS:
            raise RuntimeError(
                f"{asset_key} was not allocated across both expected teams."
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

    event_rows: list[
        dict[str, Any]
    ] = []

    for branch in [
        BRANCH_SAS_1_16,
        BRANCH_SAS_17_30,
    ]:
        condition = (
            branch_array
            == branch
        )

        event_rows.append(
            {
                "event_type": "branch",
                "event_outcome": branch,
                "candidate_team": "",
                "source_asset_key": "",
                "allocation_role": "",
                "event_count": int(
                    condition.sum()
                ),
                "event_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_pick_when_received": np.nan,
                "expected_sas_first_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2027_R1_SAS"
                        ][
                            condition
                        ]
                    )
                ),
                "expected_sac_second_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2027_R2_SAC"
                        ][
                            condition
                        ]
                    )
                ),
                "expected_cha_second_pick_when_event_occurs": float(
                    np.mean(
                        slots[
                            "2027_R2_CHA"
                        ][
                            condition
                        ]
                    )
                ),
            }
        )

    role_lookup = {
        (
            BRANCH_SAS_1_16,
            "SAC",
            "2027_R1_SAS",
        ): "first_received",
        (
            BRANCH_SAS_1_16,
            "OKC",
            "2027_R2_SAC",
        ): "fallback_second_received",
        (
            BRANCH_SAS_1_16,
            "OKC",
            "2027_R2_CHA",
        ): "fallback_second_received",
        (
            BRANCH_SAS_17_30,
            "OKC",
            "2027_R1_SAS",
        ): "first_received",
        (
            BRANCH_SAS_17_30,
            "SAC",
            "2027_R2_SAC",
        ): "second_retained",
        (
            BRANCH_SAS_17_30,
            "SAC",
            "2027_R2_CHA",
        ): "second_retained",
    }

    for (
        branch,
        candidate_team,
        asset_key,
    ), allocation_role in role_lookup.items():
        condition = (
            branch_array
            == branch
        )

        event_rows.append(
            {
                "event_type": "candidate_receipt",
                "event_outcome": branch,
                "candidate_team": candidate_team,
                "source_asset_key": asset_key,
                "allocation_role": allocation_role,
                "event_count": int(
                    condition.sum()
                ),
                "event_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_pick_when_received": float(
                    np.mean(
                        slots[
                            asset_key
                        ][
                            condition
                        ]
                    )
                ),
                "expected_sas_first_pick_when_event_occurs": np.nan,
                "expected_sac_second_pick_when_event_occurs": np.nan,
                "expected_cha_second_pick_when_event_occurs": np.nan,
            }
        )

    event_summary = pd.DataFrame(
        event_rows
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
            sas_1_16
        )
    )

    expected_sac_pick_count = (
        2.0
        - protection_probability
    )

    expected_okc_pick_count = (
        1.0
        + protection_probability
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
                "sas_pick_1_16_probability": protection_probability,
                "sas_pick_17_30_probability": (
                    1.0
                    - protection_probability
                ),
                "sacramento_expected_pick_count": float(
                    expected_pick_counts.get(
                        "SAC",
                        np.nan,
                    )
                ),
                "oklahoma_city_expected_pick_count": float(
                    expected_pick_counts.get(
                        "OKC",
                        np.nan,
                    )
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
                            "SAC",
                            np.nan,
                        )
                        - expected_sac_pick_count
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get(
                            "OKC",
                            np.nan,
                        )
                        - expected_okc_pick_count
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
            "A linked-component source is already represented by a "
            "non-direct component:\n"
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

    return (
        audit,
        contributions,
    )


def validate_existing_baseline(
    baseline_contributions: pd.DataFrame,
    unconditional_values: dict[str, float],
) -> None:
    found_assets = set(
        baseline_contributions[
            "asset_key"
        ].astype(
            str
        )
    )

    if found_assets != EXPECTED_EXISTING_BASELINE_ASSETS:
        raise RuntimeError(
            "The existing counted baseline asset set changed.\nExpected:\n"
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

    found_teams = set(
        baseline_contributions[
            "team"
        ].astype(
            str
        )
    )

    if found_teams != {
        "SAC",
    }:
        raise RuntimeError(
            "The Sacramento-second baseline is assigned to an "
            "unexpected team:\n"
            + baseline_contributions.to_string(
                index=False
            )
        )

    expected_value = float(
        unconditional_values[
            "2027_R2_SAC"
        ]
    )

    actual_value = float(
        baseline_contributions[
            "current_baseline_value_score"
        ].sum()
    )

    if abs(
        actual_value
        - expected_value
    ) > 1e-8:
        raise RuntimeError(
            "The existing Sacramento-second baseline does not match "
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
                "sas_sac_okc_cha_component_right_value_score": new_value,
                "existing_counted_baseline_value_score": baseline,
                "net_team_adjustment_value_score": (
                    new_value
                    - baseline
                ),
                "adjustment_scope": (
                    "replace_sacramento_second_baseline_with_joint_"
                    "sas_first_and_two_second_conditional_rights"
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
        "after_lal_was_orl_component_provisional"
    )

    before_column = (
        "candidate_total_pick_asset_value_score_"
        "before_sas_sac_okc_cha_component"
    )

    adjustment_column = (
        "sas_sac_okc_cha_component_adjustment_value_score"
    )

    after_column = (
        "candidate_total_pick_asset_value_score_"
        "after_sas_sac_okc_cha_component_provisional"
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
        "sas_sac_okc_cha_component_status"
    ] = (
        "fully_integrated_three_source_conditional_component"
    )

    output[
        "sas_sac_okc_cha_component_scope_note"
    ] = (
        "San Antonio's 2027 first, Sacramento's 2027 second, and "
        "Charlotte's 2027 second are modeled jointly. If the San "
        "Antonio first lands 1-16, Sacramento receives the first and "
        "Oklahoma City receives both seconds. If it lands 17-30, "
        "Oklahoma City receives the first and Sacramento retains both "
        "seconds."
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
        "sas_sac_okc_cha_component_modeled_flag": False,
        "sas_sac_okc_cha_component_primary_claim_flag": False,
        "sas_sac_okc_cha_source_asset_value_score": np.nan,
        "sas_sac_okc_cha_candidate_allocations_json": "",
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
                "joint_2027_sas_sac_okc_cha_source_allocation"
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
                "sas_sac_okc_cha_component_modeled_flag",
            ] = True

            output.loc[
                mask,
                "sas_sac_okc_cha_component_primary_claim_flag",
            ] = primary_flag

            output.loc[
                mask,
                "sas_sac_okc_cha_source_asset_value_score",
            ] = (
                source_value
                if primary_flag
                else np.nan
            )

            output.loc[
                mask,
                "sas_sac_okc_cha_candidate_allocations_json",
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
                    "joint 2027 San Antonio-Sacramento-Oklahoma City-"
                    "Charlotte conditional component. This claim row "
                    "carries the source value and allocation JSON."
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
        "2027 SAS-SAC-OKC-CHA THREE-SOURCE CONDITIONAL COMPONENT"
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
        linked_diagnostic,
    ) = load_inputs()

    validate_linked_diagnostic(
        linked_diagnostic
    )

    controlling_texts = validate_controlling_text(
        claims
    )

    source_claims = validate_source_claim_coverage(
        claims
    )

    branch_slot_proof = prove_branch_slot_closure()

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
            "The linked three-source component failed reconciliation."
        )

    for (
        asset_key,
        expected_value,
    ) in unconditional_values.items():
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

    validate_existing_baseline(
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
            "2027_R1_SAS"
        ]
        + unconditional_values[
            "2027_R2_CHA"
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
            "Team adjustments do not reconcile to source value minus "
            "the existing Sacramento-second baseline."
        )

    if abs(
        total_baseline
        - unconditional_values[
            "2027_R2_SAC"
        ]
    ) > 1e-8:
        raise RuntimeError(
            "The component did not remove exactly the Sacramento "
            "2027 second-round baseline."
        )

    if abs(
        total_adjustment
        - expected_net_adjustment
    ) > 1e-8:
        raise RuntimeError(
            "The net adjustment does not equal the previously unresolved "
            "San Antonio first plus Charlotte second values."
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
        V21_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V21_VALUATIONS_CSV_PATH,
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
        V21_TEAM_SUMMARY_PATH,
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

    branch_slot_proof.to_csv(
        BRANCH_SLOT_PROOF_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
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
        "first_round_slots_proved": len(
            branch_slot_proof
        ),
        "all_slots_assign_sources_once": bool(
            branch_slot_proof[
                "all_three_sources_assigned_once"
            ].all()
        ),
        "total_source_asset_value_score": total_source_value,
        "total_candidate_right_value_score": total_candidate_value,
        "existing_counted_baseline_value_score": total_baseline,
        "expected_unresolved_sas_and_cha_value_score": (
            expected_net_adjustment
        ),
        "net_team_adjustment_value_score": total_adjustment,
        "sas_pick_1_16_probability": float(
            component[
                "sas_pick_1_16_probability"
            ]
        ),
        "sas_pick_17_30_probability": float(
            component[
                "sas_pick_17_30_probability"
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
        "source_assets": sorted(
            SOURCE_ASSETS
        ),
        "controlling_claim_texts": controlling_texts,
        "allocation_policy": [
            (
                "If San Antonio's 2027 first lands in selections 1-16, "
                "Sacramento receives the first and Oklahoma City receives "
                "Sacramento's and Charlotte's 2027 seconds."
            ),
            (
                "If San Antonio's 2027 first lands in selections 17-30, "
                "Oklahoma City receives the first and Sacramento retains "
                "both seconds."
            ),
            (
                "All three physical sources are assigned exactly once in "
                "every simulation."
            ),
            (
                "The existing Sacramento-second direct baseline is removed "
                "and replaced by its conditional source allocation."
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
            "v21_valuation_layer": str(
                V21_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v21_team_summary": str(
                V21_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
            "branch_slot_proof": str(
                BRANCH_SLOT_PROOF_PATH
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
        "THREE-SOURCE CONDITIONAL COMPONENT FULLY INTEGRATED"
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
        "First-round slots proved: "
        f"{len(branch_slot_proof):,}"
    )
    print(
        "Every slot assigns all sources once: "
        f"{bool(branch_slot_proof['all_three_sources_assigned_once'].all())}"
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
        "Existing Sacramento-second baseline removed: "
        f"{total_baseline:.4f}"
    )
    print(
        "Expected unresolved SAS-first plus CHA-second value: "
        f"{expected_net_adjustment:.4f}"
    )
    print(
        "Net team-value adjustment: "
        f"{total_adjustment:.4f}"
    )
    print(
        "SAS pick 1-16 probability: "
        f"{float(component['sas_pick_1_16_probability']) * 100.0:.2f}%"
    )
    print(
        "SAS pick 17-30 probability: "
        f"{float(component['sas_pick_17_30_probability']) * 100.0:.2f}%"
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
        "sas_sac_okc_cha_component_right_value_score",
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
        "expected_sas_first_pick_when_event_occurs",
        "expected_sac_second_pick_when_event_occurs",
        "expected_cha_second_pick_when_event_occurs",
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
        "EXHAUSTIVE FIRST-ROUND SLOT PROOF"
    )

    proof_summary = (
        branch_slot_proof.groupby(
            "branch",
            as_index=False,
        )
        .agg(
            valid_first_round_slots=(
                "sas_first_slot",
                "count",
            ),
            all_sources_assigned_once=(
                "all_three_sources_assigned_once",
                "all",
            ),
            sacramento_pick_count=(
                "sacramento_pick_count",
                "first",
            ),
            oklahoma_city_pick_count=(
                "oklahoma_city_pick_count",
                "first",
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
        V21_VALUATIONS_PARQUET_PATH,
        V21_VALUATIONS_CSV_PATH,
        BASELINE_AUDIT_PATH,
        TEAM_ADJUSTMENTS_PATH,
        V21_TEAM_SUMMARY_PATH,
        SOURCE_RECONCILIATION_PATH,
        COMPONENT_RECONCILIATION_PATH,
        BRANCH_SLOT_PROOF_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()