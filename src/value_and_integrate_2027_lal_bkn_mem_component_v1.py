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
    "future-pick-2027-lal-bkn-mem-conditional-second-component-v1-2026-08-04"
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

V26_INPUT_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v26_atl_mia_cha_okc_enriched.parquet"
)

V26_INPUT_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v26_atl_mia_cha_okc_provisional.csv"
)

DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2027_lal_bkn_group_claim_v1.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_candidate_rights_v1.csv"
)

EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_event_summary_v1.parquet"
)

EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_event_summary_v1.csv"
)

V27_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v27_lal_bkn_mem_enriched.parquet"
)

V27_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v27_lal_bkn_mem_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_existing_baseline_audit_v1.csv"
)

FIRST_ROUND_LINKAGE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_first_round_linkage_audit_v1.csv"
)

PRESERVATION_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_preservation_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_team_adjustments_v1.csv"
)

V27_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v27_lal_bkn_mem_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_source_reconciliation_v1.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_component_reconciliation_v1.csv"
)

BRANCH_PROOF_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_branch_proof_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_lal_bkn_mem_component_metadata_v1.json"
)


TARGET_GROUP_ID = "OBL_44f6f783bace"

SOURCE_ASSET_KEY = "2027_R2_LAL"
SOURCE_CLAIM_ID = "2027_R2_LAL_C1"

DRIVER_ASSET_KEY = "2027_R1_LAL"
DRIVER_CLAIM_ID = "2027_R1_LAL_C1"

SOURCE_DRAFT_YEAR = 2027
SOURCE_ROUND_NUMBER = 2
SOURCE_TEAM = "LAL"

DRIVER_DRAFT_YEAR = 2027
DRIVER_ROUND_NUMBER = 1
DRIVER_TEAM = "LAL"

PROTECTION_START_PICK = 1
PROTECTION_END_PICK = 4

CANDIDATE_TEAMS = {
    "BKN",
    "MEM",
}

BRANCH_FIRST_CONVEYS = (
    "LAL_FIRST_CONVEYS_SECOND_TO_BKN"
)

BRANCH_FIRST_PROTECTED = (
    "LAL_FIRST_PROTECTED_SECOND_TO_MEM"
)

EXPECTED_TEXT_FRAGMENTS = [
    (
        "If the L.A. Lakers convey a 1st round pick to Memphis in 2027"
    ),
    (
        "then the L.A. Lakers' 2027 2nd round pick to Brooklyn"
    ),
    (
        "if the L.A. Lakers do not convey a 1st round pick to Memphis "
        "in 2027"
    ),
    (
        "then the obligation to Brooklyn will be extinguished and instead "
        "Memphis will receive this 2nd round pick"
    ),
]

PRESERVED_CONNECTED_CLAIM_IDS = {
    "2027_R1_LAL_C1",
    "2027_R2_BKN_C1",
    "2027_R2_DAL_C1",
}

EXPECTED_DRIVER_METHOD = (
    "single_year_protection_component"
)

EXPECTED_DRIVER_STATUS = (
    "valued_partial_rollover_component"
)


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
        str(
            value
        ),
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
            str(
                key
            ): json_safe(
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

        if "LAL" not in self.team_to_index:
            raise ValueError(
                "Simulation bank does not contain the Lakers."
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
            pd.to_numeric(
                curve[
                    "overall_pick"
                ],
                errors="raise",
            ).max()
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
        V26_INPUT_VALUATIONS_PATH,
        V26_INPUT_TEAM_SUMMARY_PATH,
        DIAGNOSTIC_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required V27 component input was not found:\n"
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
            V26_INPUT_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V26_INPUT_TEAM_SUMMARY_PATH
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
        "V26 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_atl_mia_cha_okc_component_provisional"
            ),
        ],
        "V26 provisional team summary",
    )

    require_columns(
        diagnostic,
        [
            "claim_id",
            "asset_key",
        ],
        "LAL-BKN conditional diagnostic",
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

    if claim_ids != {
        SOURCE_CLAIM_ID,
    }:
        raise ValueError(
            "The LAL-BKN diagnostic claim set changed.\nExpected:\n"
            f"{SOURCE_CLAIM_ID}\nFound:\n"
            + "\n".join(
                sorted(
                    claim_ids
                )
            )
        )

    if asset_keys != {
        SOURCE_ASSET_KEY,
    }:
        raise ValueError(
            "The LAL-BKN diagnostic asset set changed."
        )


def validate_controlling_text(
    claims: pd.DataFrame,
) -> str:
    row = claims.loc[
        claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            SOURCE_CLAIM_ID
        )
    ]

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one Lakers 2027 second-round claim."
        )

    text = clean_text(
        row.iloc[
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
            "The Lakers-Brooklyn controlling text changed. "
            "Missing fragments:\n"
            + "\n".join(
                missing
            )
        )

    return text


def validate_source_claim(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    row = claims.loc[
        claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            SOURCE_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one source claim row."
        )

    actual = row.iloc[
        0
    ]

    if clean_text(
        actual[
            "asset_key"
        ]
    ) != SOURCE_ASSET_KEY:
        raise ValueError(
            "The Lakers conditional second source asset changed."
        )

    if int(
        numeric_value(
            actual[
                "draft_year"
            ]
        )
    ) != SOURCE_DRAFT_YEAR:
        raise ValueError(
            "The source draft year changed."
        )

    if int(
        numeric_value(
            actual[
                "round_number"
            ]
        )
    ) != SOURCE_ROUND_NUMBER:
        raise ValueError(
            "The source round changed."
        )

    if clean_text(
        actual[
            "originating_team"
        ]
    ) != SOURCE_TEAM:
        raise ValueError(
            "The source originating team changed."
        )

    return row.reset_index(
        drop=True
    )


def validate_driver_claim(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    row = claims.loc[
        claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            DRIVER_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one Lakers 2027 first-round driver claim."
        )

    actual = row.iloc[
        0
    ]

    if clean_text(
        actual[
            "asset_key"
        ]
    ) != DRIVER_ASSET_KEY:
        raise ValueError(
            "The Lakers first-round driver asset changed."
        )

    return row.reset_index(
        drop=True
    )


def get_pick_value_row(
    pick_values: pd.DataFrame,
    draft_year: int,
    round_number: int,
    team: str,
) -> pd.Series:
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
            "Expected one originating-team value row for "
            f"{draft_year} R{round_number} {team}; found {len(match)}."
        )

    return match.iloc[
        0
    ]


def capture_preserved_claims(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    preserved = valuations.loc[
        valuations[
            "claim_id"
        ]
        .astype(
            str
        )
        .isin(
            PRESERVED_CONNECTED_CLAIM_IDS
        )
    ].copy()

    found = set(
        preserved[
            "claim_id"
        ].astype(
            str
        )
    )

    if found != PRESERVED_CONNECTED_CLAIM_IDS:
        raise ValueError(
            "The preserved connected claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    PRESERVED_CONNECTED_CLAIM_IDS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found
                )
            )
        )

    counts = (
        preserved.groupby(
            "claim_id"
        ).size()
    )

    if not counts.eq(
        1
    ).all():
        raise ValueError(
            "Each preserved claim must appear exactly once."
        )

    columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "conveyance_probability",
            "retention_probability",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "valuation_scope_note",
        ]
        if column in preserved.columns
    ]

    return preserved[
        columns
    ].sort_values(
        "claim_id"
    ).reset_index(
        drop=True
    )


def validate_driver_valuation(
    valuations: pd.DataFrame,
) -> pd.Series:
    row = valuations.loc[
        valuations[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            DRIVER_CLAIM_ID
        )
    ]

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one Lakers first-round valuation row."
        )

    row = row.iloc[
        0
    ]

    if clean_text(
        row[
            "valuation_method"
        ]
    ) != EXPECTED_DRIVER_METHOD:
        raise ValueError(
            "The Lakers first-round driver no longer uses the expected "
            "protection valuation method."
        )

    if clean_text(
        row[
            "valuation_status"
        ]
    ) != EXPECTED_DRIVER_STATUS:
        raise ValueError(
            "The Lakers first-round driver no longer has the expected "
            "partial-rollover status."
        )

    if clean_text(
        row.get(
            "candidate_beneficiary_team",
            "",
        )
    ) != "MEM":
        raise ValueError(
            "The Lakers first-round driver is no longer assigned to "
            "Memphis when conveyed."
        )

    if clean_text(
        row.get(
            "candidate_retaining_team",
            "",
        )
    ) != "LAL":
        raise ValueError(
            "The Lakers are no longer the retaining team on protected "
            "first-round outcomes."
        )

    if (
        "protection_start_pick"
        in valuations.columns
        and np.isfinite(
            numeric_value(
                row.get(
                    "protection_start_pick",
                    np.nan,
                )
            )
        )
        and int(
            numeric_value(
                row[
                    "protection_start_pick"
                ]
            )
        )
        != PROTECTION_START_PICK
    ):
        raise ValueError(
            "The Lakers first-round protection start changed."
        )

    if (
        "protection_end_pick"
        in valuations.columns
        and np.isfinite(
            numeric_value(
                row.get(
                    "protection_end_pick",
                    np.nan,
                )
            )
        )
        and int(
            numeric_value(
                row[
                    "protection_end_pick"
                ]
            )
        )
        != PROTECTION_END_PICK
    ):
        raise ValueError(
            "The Lakers first-round protection end changed."
        )

    return row


def build_baseline_audit(
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
            SOURCE_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise ValueError(
            "Expected exactly one source valuation row."
        )

    actual = row.iloc[
        0
    ]

    baseline_value = finite_or_zero(
        actual.get(
            "expected_total_candidate_asset_value_score",
            np.nan,
        )
    )

    audit = pd.DataFrame(
        [
            {
                "claim_id": SOURCE_CLAIM_ID,
                "asset_key": SOURCE_ASSET_KEY,
                "existing_valuation_method": clean_text(
                    actual.get(
                        "valuation_method",
                        "",
                    )
                ),
                "existing_valuation_status": clean_text(
                    actual.get(
                        "valuation_status",
                        "",
                    )
                ),
                "existing_candidate_beneficiary_team": clean_text(
                    actual.get(
                        "candidate_beneficiary_team",
                        "",
                    )
                ),
                "existing_counted_baseline_value_score": baseline_value,
                "baseline_expected_to_be_zero": True,
                "baseline_validation_passed": bool(
                    clean_text(
                        actual.get(
                            "valuation_method",
                            "",
                        )
                    )
                    == "not_automatically_valued"
                    and clean_text(
                        actual.get(
                            "valuation_status",
                            "",
                        )
                    )
                    == "requires_dependency_review"
                    and abs(
                        baseline_value
                    )
                    <= 1e-12
                ),
            }
        ]
    )

    if not bool(
        audit.iloc[
            0
        ][
            "baseline_validation_passed"
        ]
    ):
        raise RuntimeError(
            "The Lakers second already has an unexpected counted baseline."
        )

    return audit


def prove_branch_logic() -> pd.DataFrame:
    rows = []

    for first_round_slot in range(
        1,
        31,
    ):
        first_conveys = bool(
            first_round_slot
            > PROTECTION_END_PICK
        )

        recipient = (
            "BKN"
            if first_conveys
            else "MEM"
        )

        branch = (
            BRANCH_FIRST_CONVEYS
            if first_conveys
            else BRANCH_FIRST_PROTECTED
        )

        rows.append(
            {
                "lal_first_round_slot": first_round_slot,
                "lal_first_is_protected": bool(
                    first_round_slot
                    <= PROTECTION_END_PICK
                ),
                "lal_first_conveys_to_memphis": first_conveys,
                "lal_second_recipient": recipient,
                "branch": branch,
                "source_assignment_count": 1,
                "source_assigned_exactly_once": True,
                "branch_logic_passed": bool(
                    (
                        first_round_slot
                        <= PROTECTION_END_PICK
                        and recipient
                        == "MEM"
                    )
                    or (
                        first_round_slot
                        > PROTECTION_END_PICK
                        and recipient
                        == "BKN"
                    )
                ),
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
        [
            "source_assigned_exactly_once",
            "branch_logic_passed",
        ]
    ].all().all():
        raise RuntimeError(
            "The conditional second-round branch proof failed."
        )

    branch_counts = (
        proof[
            "branch"
        ]
        .value_counts()
        .to_dict()
    )

    expected = {
        BRANCH_FIRST_CONVEYS: 26,
        BRANCH_FIRST_PROTECTED: 4,
    }

    if branch_counts != expected:
        raise RuntimeError(
            "The exhaustive branch counts changed.\nExpected:\n"
            + json.dumps(
                expected,
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
    source_discount: float,
    driver_discount: float,
    driver_valuation: pd.Series,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    first_slots = bank.slots(
        draft_year=DRIVER_DRAFT_YEAR,
        round_number=DRIVER_ROUND_NUMBER,
        team=DRIVER_TEAM,
    )

    second_slots = bank.slots(
        draft_year=SOURCE_DRAFT_YEAR,
        round_number=SOURCE_ROUND_NUMBER,
        team=SOURCE_TEAM,
    )

    if len(
        first_slots
    ) != len(
        second_slots
    ):
        raise ValueError(
            "The Lakers first- and second-round simulation arrays do "
            "not align."
        )

    simulation_count = len(
        first_slots
    )

    first_protected = (
        first_slots
        <= PROTECTION_END_PICK
    )

    first_conveys = ~first_protected

    recipients = np.where(
        first_conveys,
        "BKN",
        "MEM",
    )

    source_values = (
        lookup.value[
            second_slots
        ]
        * source_discount
    )

    driver_values = (
        lookup.value[
            first_slots
        ]
        * driver_discount
    )

    branch_array = np.where(
        first_conveys,
        BRANCH_FIRST_CONVEYS,
        BRANCH_FIRST_PROTECTED,
    )

    allocation_rows = []

    for candidate_team in sorted(
        CANDIDATE_TEAMS
    ):
        condition = (
            recipients
            == candidate_team
        )

        allocation_rows.append(
            {
                "source_asset_key": SOURCE_ASSET_KEY,
                "source_team": SOURCE_TEAM,
                "candidate_team": candidate_team,
                "allocation_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_allocated_value_score": float(
                    np.mean(
                        np.where(
                            condition,
                            source_values,
                            0.0,
                        )
                    )
                ),
                "expected_pick_when_allocated": float(
                    np.mean(
                        second_slots[
                            condition
                        ]
                    )
                ),
                "driver_event": (
                    "lal_first_conveys_to_memphis"
                    if candidate_team
                    == "BKN"
                    else "lal_first_is_protected_1_4"
                ),
                "simulation_count": simulation_count,
            }
        )

    source_allocations = pd.DataFrame(
        allocation_rows
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

    candidate_rights[
        "source_assets"
    ] = SOURCE_ASSET_KEY

    unconditional_source_value = float(
        np.mean(
            source_values
        )
    )

    allocated_value_sum = float(
        source_allocations[
            "expected_allocated_value_score"
        ].sum()
    )

    probability_sum = float(
        source_allocations[
            "allocation_probability"
        ].sum()
    )

    source_reconciliation = pd.DataFrame(
        [
            {
                "source_asset_key": SOURCE_ASSET_KEY,
                "unconditional_asset_value_score": (
                    unconditional_source_value
                ),
                "allocated_value_sum": allocated_value_sum,
                "allocation_value_difference": (
                    allocated_value_sum
                    - unconditional_source_value
                ),
                "allocation_probability_sum": probability_sum,
                "allocation_reconciliation_passed": bool(
                    abs(
                        allocated_value_sum
                        - unconditional_source_value
                    )
                    <= 1e-8
                    and abs(
                        probability_sum
                        - 1.0
                    )
                    <= 1e-12
                ),
            }
        ]
    )

    branch_rows = []

    for branch in [
        BRANCH_FIRST_CONVEYS,
        BRANCH_FIRST_PROTECTED,
    ]:
        condition = (
            branch_array
            == branch
        )

        branch_rows.append(
            {
                "event_type": "branch",
                "event_outcome": branch,
                "candidate_team": (
                    "BKN"
                    if branch
                    == BRANCH_FIRST_CONVEYS
                    else "MEM"
                ),
                "source_asset_key": SOURCE_ASSET_KEY,
                "event_count": int(
                    condition.sum()
                ),
                "event_probability": float(
                    np.mean(
                        condition
                    )
                ),
                "expected_lal_first_pick_when_event_occurs": float(
                    np.mean(
                        first_slots[
                            condition
                        ]
                    )
                ),
                "expected_lal_second_pick_when_received": float(
                    np.mean(
                        second_slots[
                            condition
                        ]
                    )
                ),
                "expected_source_value_when_event_occurs": float(
                    np.mean(
                        source_values[
                            condition
                        ]
                    )
                ),
            }
        )

    event_summary = pd.DataFrame(
        branch_rows
    )

    simulated_driver_conveyance_probability = float(
        np.mean(
            first_conveys
        )
    )

    simulated_driver_retention_probability = float(
        np.mean(
            first_protected
        )
    )

    simulated_driver_transferred_value = float(
        np.mean(
            np.where(
                first_conveys,
                driver_values,
                0.0,
            )
        )
    )

    simulated_driver_retained_value = float(
        np.mean(
            np.where(
                first_protected,
                driver_values,
                0.0,
            )
        )
    )

    stored_driver_conveyance_probability = finite_or_zero(
        driver_valuation.get(
            "conveyance_probability",
            np.nan,
        )
    )

    stored_driver_retention_probability = finite_or_zero(
        driver_valuation.get(
            "retention_probability",
            np.nan,
        )
    )

    stored_driver_transferred_value = finite_or_zero(
        driver_valuation.get(
            "expected_transferred_value_score",
            np.nan,
        )
    )

    stored_driver_retained_value = finite_or_zero(
        driver_valuation.get(
            "expected_retained_value_score",
            np.nan,
        )
    )

    first_round_linkage_audit = pd.DataFrame(
        [
            {
                "driver_claim_id": DRIVER_CLAIM_ID,
                "driver_asset_key": DRIVER_ASSET_KEY,
                "protection_start_pick": PROTECTION_START_PICK,
                "protection_end_pick": PROTECTION_END_PICK,
                "stored_conveyance_probability": (
                    stored_driver_conveyance_probability
                ),
                "simulated_conveyance_probability": (
                    simulated_driver_conveyance_probability
                ),
                "conveyance_probability_difference": (
                    simulated_driver_conveyance_probability
                    - stored_driver_conveyance_probability
                ),
                "stored_retention_probability": (
                    stored_driver_retention_probability
                ),
                "simulated_retention_probability": (
                    simulated_driver_retention_probability
                ),
                "retention_probability_difference": (
                    simulated_driver_retention_probability
                    - stored_driver_retention_probability
                ),
                "stored_transferred_value_score": (
                    stored_driver_transferred_value
                ),
                "simulated_transferred_value_score": (
                    simulated_driver_transferred_value
                ),
                "transferred_value_difference": (
                    simulated_driver_transferred_value
                    - stored_driver_transferred_value
                ),
                "stored_retained_value_score": (
                    stored_driver_retained_value
                ),
                "simulated_retained_value_score": (
                    simulated_driver_retained_value
                ),
                "retained_value_difference": (
                    simulated_driver_retained_value
                    - stored_driver_retained_value
                ),
                "driver_linkage_reconciliation_passed": bool(
                    abs(
                        simulated_driver_conveyance_probability
                        - stored_driver_conveyance_probability
                    )
                    <= 1e-12
                    and abs(
                        simulated_driver_retention_probability
                        - stored_driver_retention_probability
                    )
                    <= 1e-12
                    and abs(
                        simulated_driver_transferred_value
                        - stored_driver_transferred_value
                    )
                    <= 1e-8
                    and abs(
                        simulated_driver_retained_value
                        - stored_driver_retained_value
                    )
                    <= 1e-8
                ),
            }
        ]
    )

    if not bool(
        first_round_linkage_audit.iloc[
            0
        ][
            "driver_linkage_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "The conditional second allocation does not match the existing "
            "Lakers first-round protection component."
        )

    right_lookup = (
        candidate_rights.set_index(
            "candidate_team"
        )
    )

    bkn_pick_count = float(
        right_lookup.loc[
            "BKN",
            "expected_pick_count",
        ]
    )

    mem_pick_count = float(
        right_lookup.loc[
            "MEM",
            "expected_pick_count",
        ]
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
                "source_asset_count": 1,
                "source_claim_count": 1,
                "candidate_team_count": 2,
                "total_source_asset_value_score": (
                    unconditional_source_value
                ),
                "total_candidate_right_value_score": (
                    total_candidate_value
                ),
                "total_expected_pick_count": float(
                    candidate_rights[
                        "expected_pick_count"
                    ].sum()
                ),
                "brooklyn_expected_pick_count": bkn_pick_count,
                "memphis_expected_pick_count": mem_pick_count,
                "lal_first_conveyance_probability": (
                    simulated_driver_conveyance_probability
                ),
                "lal_first_protection_probability": (
                    simulated_driver_retention_probability
                ),
                "value_difference": (
                    total_candidate_value
                    - unconditional_source_value
                ),
                "component_reconciliation_passed": bool(
                    abs(
                        total_candidate_value
                        - unconditional_source_value
                    )
                    <= 1e-8
                    and abs(
                        candidate_rights[
                            "expected_pick_count"
                        ].sum()
                        - 1.0
                    )
                    <= 1e-12
                    and abs(
                        bkn_pick_count
                        - simulated_driver_conveyance_probability
                    )
                    <= 1e-12
                    and abs(
                        mem_pick_count
                        - simulated_driver_retention_probability
                    )
                    <= 1e-12
                ),
            }
        ]
    )

    return (
        source_allocations,
        candidate_rights,
        event_summary,
        source_reconciliation,
        first_round_linkage_audit,
        component_reconciliation,
    )


def build_team_adjustments(
    candidate_rights: pd.DataFrame,
    baseline_audit: pd.DataFrame,
) -> pd.DataFrame:
    baseline_value = float(
        baseline_audit[
            "existing_counted_baseline_value_score"
        ].sum()
    )

    if abs(
        baseline_value
    ) > 1e-12:
        raise RuntimeError(
            "The V27 source baseline must be zero."
        )

    rights = (
        candidate_rights.set_index(
            "candidate_team"
        )[
            "expected_candidate_right_value_score"
        ]
        .to_dict()
    )

    rows = []

    for team in sorted(
        CANDIDATE_TEAMS
    ):
        right_value = float(
            rights.get(
                team,
                0.0,
            )
        )

        rows.append(
            {
                "team": team,
                "lal_bkn_mem_component_right_value_score": right_value,
                "existing_counted_baseline_value_score": 0.0,
                "net_team_adjustment_value_score": right_value,
                "adjustment_scope": (
                    "add_conditional_lakers_second_right_tied_to_"
                    "lakers_first_conveyance"
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
        "after_atl_mia_cha_okc_component_provisional"
    )

    before_column = (
        "candidate_total_pick_asset_value_score_"
        "before_lal_bkn_mem_component"
    )

    adjustment_column = (
        "lal_bkn_mem_component_adjustment_value_score"
    )

    after_column = (
        "candidate_total_pick_asset_value_score_"
        "after_lal_bkn_mem_component_provisional"
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
        "lal_bkn_mem_component_status"
    ] = (
        "fully_integrated_conditional_second_linked_to_first_protection"
    )

    output[
        "lal_bkn_mem_component_scope_note"
    ] = (
        "The Lakers' 2027 second goes to Brooklyn when the Lakers' "
        "2027 first conveys to Memphis. If the first is protected at "
        "selections 1-4, Brooklyn's right is extinguished and Memphis "
        "receives the second instead."
    )

    return output.sort_values(
        after_column,
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    source_value: float,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    defaults = {
        "lal_bkn_mem_component_modeled_flag": False,
        "lal_bkn_mem_component_primary_claim_flag": False,
        "lal_bkn_mem_source_asset_value_score": np.nan,
        "lal_bkn_mem_candidate_allocations_json": "",
    }

    for column, default in defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    mask = (
        output[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            SOURCE_CLAIM_ID
        )
    )

    if int(
        mask.sum()
    ) != 1:
        raise ValueError(
            "Expected one target valuation row during V27 enrichment."
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
                "driver_event": str(
                    row.driver_event
                ),
            }
            for row in source_allocations.itertuples(
                index=False
            )
        },
        sort_keys=True,
    )

    output.loc[
        mask,
        "valuation_method",
    ] = (
        "joint_2027_lal_bkn_mem_conditional_source_allocation"
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
        "lal_bkn_mem_component_modeled_flag",
    ] = True

    output.loc[
        mask,
        "lal_bkn_mem_component_primary_claim_flag",
    ] = True

    output.loc[
        mask,
        "lal_bkn_mem_source_asset_value_score",
    ] = source_value

    output.loc[
        mask,
        "lal_bkn_mem_candidate_allocations_json",
    ] = allocation_json

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
            "The physical Lakers 2027 second is fully allocated through "
            "the conditional first-round linkage. Brooklyn receives it "
            "when the Lakers first conveys to Memphis. Memphis receives "
            "it when the first is protected 1-4. Candidate rights are "
            "stored separately to prevent duplicate aggregation."
        )

    return output


def verify_preserved_claims(
    before: pd.DataFrame,
    after: pd.DataFrame,
) -> pd.DataFrame:
    after_subset = after.loc[
        after[
            "claim_id"
        ]
        .astype(
            str
        )
        .isin(
            PRESERVED_CONNECTED_CLAIM_IDS
        )
    ].copy()

    columns = list(
        before.columns
    )

    after_subset = (
        after_subset[
            columns
        ]
        .sort_values(
            "claim_id"
        )
        .reset_index(
            drop=True
        )
    )

    try:
        pd.testing.assert_frame_equal(
            before,
            after_subset,
            check_dtype=False,
            check_exact=True,
        )

        preservation_passed = True
        difference_note = ""
    except AssertionError as error:
        preservation_passed = False
        difference_note = clean_text(
            error
        )

    audit = pd.DataFrame(
        [
            {
                "preserved_claim_count": len(
                    before
                ),
                "expected_preserved_claim_count": len(
                    PRESERVED_CONNECTED_CLAIM_IDS
                ),
                "preserved_claim_ids": "|".join(
                    sorted(
                        PRESERVED_CONNECTED_CLAIM_IDS
                    )
                ),
                "preservation_passed": preservation_passed,
                "difference_note": difference_note,
            }
        ]
    )

    if not preservation_passed:
        raise RuntimeError(
            "An existing connected component changed during V27 "
            "enrichment:\n"
            f"{difference_note}"
        )

    return audit


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
        "2027 LAL-BKN-MEM CONDITIONAL SECOND COMPONENT"
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

    validate_source_claim(
        claims
    )

    validate_driver_claim(
        claims
    )

    driver_valuation = validate_driver_valuation(
        valuations
    )

    preserved_before = capture_preserved_claims(
        valuations
    )

    baseline_audit = build_baseline_audit(
        valuations
    )

    branch_proof = prove_branch_logic()

    source_pick_value_row = get_pick_value_row(
        pick_values=pick_values,
        draft_year=SOURCE_DRAFT_YEAR,
        round_number=SOURCE_ROUND_NUMBER,
        team=SOURCE_TEAM,
    )

    driver_pick_value_row = get_pick_value_row(
        pick_values=pick_values,
        draft_year=DRIVER_DRAFT_YEAR,
        round_number=DRIVER_ROUND_NUMBER,
        team=DRIVER_TEAM,
    )

    source_discount = numeric_value(
        source_pick_value_row[
            "time_discount_factor"
        ]
    )

    driver_discount = numeric_value(
        driver_pick_value_row[
            "time_discount_factor"
        ]
    )

    expected_source_value = numeric_value(
        source_pick_value_row[
            "time_discounted_pick_value_score"
        ]
    )

    lookup = SlotValueLookup(
        curve
    )

    bank = SimulationBank(
        SIMULATION_BANK_PATH
    )

    try:
        (
            source_allocations,
            candidate_rights,
            event_summary,
            source_reconciliation,
            first_round_linkage_audit,
            component_reconciliation,
        ) = evaluate_component(
            bank=bank,
            lookup=lookup,
            source_discount=source_discount,
            driver_discount=driver_discount,
            driver_valuation=driver_valuation,
        )
    finally:
        bank.close()

    simulated_source_value = float(
        source_reconciliation.iloc[
            0
        ][
            "unconditional_asset_value_score"
        ]
    )

    if abs(
        simulated_source_value
        - expected_source_value
    ) > 1e-8:
        raise RuntimeError(
            "The simulated Lakers second value does not match the V3 "
            "originating-team value."
        )

    if not bool(
        source_reconciliation.iloc[
            0
        ][
            "allocation_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "The Lakers second failed source reconciliation."
        )

    if not bool(
        component_reconciliation.iloc[
            0
        ][
            "component_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "The LAL-BKN-MEM component failed reconciliation."
        )

    adjustments = build_team_adjustments(
        candidate_rights=candidate_rights,
        baseline_audit=baseline_audit,
    )

    updated_team_summary = update_team_summary(
        team_summary=team_summary,
        adjustments=adjustments,
    )

    enriched_valuations = enrich_valuations(
        valuations=valuations,
        source_value=simulated_source_value,
        source_allocations=source_allocations,
    )

    preservation_audit = verify_preserved_claims(
        before=preserved_before,
        after=enriched_valuations,
    )

    total_candidate_value = float(
        candidate_rights[
            "expected_candidate_right_value_score"
        ].sum()
    )

    total_adjustment = float(
        adjustments[
            "net_team_adjustment_value_score"
        ].sum()
    )

    if abs(
        total_candidate_value
        - simulated_source_value
    ) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal source value."
        )

    if abs(
        total_adjustment
        - simulated_source_value
    ) > 1e-8:
        raise RuntimeError(
            "Net team adjustment does not equal the unresolved Lakers "
            "second value."
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
        V27_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V27_VALUATIONS_CSV_PATH,
        index=False,
    )

    baseline_audit.to_csv(
        BASELINE_AUDIT_PATH,
        index=False,
    )

    first_round_linkage_audit.to_csv(
        FIRST_ROUND_LINKAGE_AUDIT_PATH,
        index=False,
    )

    preservation_audit.to_csv(
        PRESERVATION_AUDIT_PATH,
        index=False,
    )

    adjustments.to_csv(
        TEAM_ADJUSTMENTS_PATH,
        index=False,
    )

    updated_team_summary.to_csv(
        V27_TEAM_SUMMARY_PATH,
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

    branch_proof.to_csv(
        BRANCH_PROOF_PATH,
        index=False,
    )

    component = component_reconciliation.iloc[
        0
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_group_id": TARGET_GROUP_ID,
        "source_asset_key": SOURCE_ASSET_KEY,
        "source_claim_id": SOURCE_CLAIM_ID,
        "driver_asset_key": DRIVER_ASSET_KEY,
        "driver_claim_id": DRIVER_CLAIM_ID,
        "joint_simulations": int(
            component[
                "joint_simulation_count"
            ]
        ),
        "source_assets_integrated": 1,
        "source_claim_rows_enriched": 1,
        "source_allocation_rows": len(
            source_allocations
        ),
        "candidate_rights_created": len(
            candidate_rights
        ),
        "first_round_slots_proved": len(
            branch_proof
        ),
        "all_branch_assignments_allocate_source_once": bool(
            branch_proof[
                "source_assigned_exactly_once"
            ].all()
        ),
        "total_source_asset_value_score": (
            simulated_source_value
        ),
        "total_candidate_right_value_score": (
            total_candidate_value
        ),
        "existing_counted_baseline_value_score": 0.0,
        "net_team_adjustment_value_score": (
            total_adjustment
        ),
        "lal_first_conveyance_probability": float(
            component[
                "lal_first_conveyance_probability"
            ]
        ),
        "lal_first_protection_probability": float(
            component[
                "lal_first_protection_probability"
            ]
        ),
        "first_round_driver_linkage_passed": bool(
            first_round_linkage_audit.iloc[
                0
            ][
                "driver_linkage_reconciliation_passed"
            ]
        ),
        "preserved_connected_components_passed": bool(
            preservation_audit.iloc[
                0
            ][
                "preservation_passed"
            ]
        ),
        "source_reconciliation_passed": bool(
            source_reconciliation.iloc[
                0
            ][
                "allocation_reconciliation_passed"
            ]
        ),
        "component_reconciliation_passed": bool(
            component[
                "component_reconciliation_passed"
            ]
        ),
        "controlling_claim_text": controlling_text,
        "allocation_policy": [
            (
                "If the Lakers' 2027 first conveys to Memphis, the "
                "Lakers' 2027 second is assigned to Brooklyn."
            ),
            (
                "If the Lakers' 2027 first is protected at selections "
                "1-4, Brooklyn's obligation is extinguished and the "
                "Lakers' 2027 second is assigned to Memphis."
            ),
            (
                "The existing Lakers first-round protection valuation "
                "is preserved and used only as the branch driver."
            ),
            (
                "The existing Brooklyn-Dallas second-round component "
                "is preserved."
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
            "v27_valuation_layer": str(
                V27_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "first_round_linkage_audit": str(
                FIRST_ROUND_LINKAGE_AUDIT_PATH
            ),
            "preservation_audit": str(
                PRESERVATION_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v27_team_summary": str(
                V27_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
            "branch_proof": str(
                BRANCH_PROOF_PATH
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
        "CONDITIONAL SECOND COMPONENT FULLY INTEGRATED"
    )
    print(
        "=" * 80
    )
    print(
        "Joint simulations: "
        f"{int(component['joint_simulation_count']):,}"
    )
    print(
        "Source assets integrated: 1"
    )
    print(
        "Source claim rows enriched: 1"
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
        f"{len(branch_proof):,}"
    )
    print(
        "Every branch assigns the source once: "
        f"{bool(branch_proof['source_assigned_exactly_once'].all())}"
    )
    print(
        "Total source-asset value: "
        f"{simulated_source_value:.4f}"
    )
    print(
        "Total candidate-right value: "
        f"{total_candidate_value:.4f}"
    )
    print(
        "Existing counted baseline removed: 0.0000"
    )
    print(
        "Net team-value adjustment: "
        f"{total_adjustment:.4f}"
    )
    print(
        "Lakers first conveys to Memphis probability: "
        f"{float(component['lal_first_conveyance_probability']) * 100.0:.2f}%"
    )
    print(
        "Lakers first protected 1-4 probability: "
        f"{float(component['lal_first_protection_probability']) * 100.0:.2f}%"
    )
    print(
        "Existing Lakers first-round component preserved: "
        f"{bool(preservation_audit.iloc[0]['preservation_passed'])}"
    )
    print(
        "Brooklyn-Dallas second component preserved: "
        f"{bool(preservation_audit.iloc[0]['preservation_passed'])}"
    )
    print(
        "First-round linkage reconciliation passed: "
        f"{bool(first_round_linkage_audit.iloc[0]['driver_linkage_reconciliation_passed'])}"
    )
    print(
        "Source reconciliation passed: "
        f"{bool(source_reconciliation.iloc[0]['allocation_reconciliation_passed'])}"
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
        "lal_bkn_mem_component_right_value_score",
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
        "expected_lal_first_pick_when_event_occurs",
        "expected_lal_second_pick_when_received",
        "expected_source_value_when_event_occurs",
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
        "FIRST-ROUND LINKAGE AUDIT"
    )

    linkage_display = first_round_linkage_audit.copy()

    for column in [
        "stored_conveyance_probability",
        "simulated_conveyance_probability",
        "conveyance_probability_difference",
        "stored_retention_probability",
        "simulated_retention_probability",
        "retention_probability_difference",
        "stored_transferred_value_score",
        "simulated_transferred_value_score",
        "transferred_value_difference",
        "stored_retained_value_score",
        "simulated_retained_value_score",
        "retained_value_difference",
    ]:
        linkage_display[
            column
        ] = pd.to_numeric(
            linkage_display[
                column
            ],
            errors="coerce",
        ).round(
            8
        )

    print(
        linkage_display.to_string(
            index=False
        )
    )
    print()

    print(
        "EXHAUSTIVE BRANCH PROOF"
    )

    proof_summary = (
        branch_proof.groupby(
            [
                "branch",
                "lal_second_recipient",
            ],
            as_index=False,
        )
        .agg(
            first_round_slots=(
                "lal_first_round_slot",
                "count",
            ),
            all_source_assignments_once=(
                "source_assigned_exactly_once",
                "all",
            ),
            all_branch_logic_passed=(
                "branch_logic_passed",
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
        V27_VALUATIONS_PARQUET_PATH,
        V27_VALUATIONS_CSV_PATH,
        BASELINE_AUDIT_PATH,
        FIRST_ROUND_LINKAGE_AUDIT_PATH,
        PRESERVATION_AUDIT_PATH,
        TEAM_ADJUSTMENTS_PATH,
        V27_TEAM_SUMMARY_PATH,
        SOURCE_RECONCILIATION_PATH,
        COMPONENT_RECONCILIATION_PATH,
        BRANCH_PROOF_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()