from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-linked-rollover-value-v1-v3-bank-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

READY_ROLLOVERS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_rollover_valuation_ready_2027_2029_v3.csv"
)

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

VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v3_floor_corrected.parquet"
)

TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_2027_2029_v3_floor_corrected.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

ROLLOVER_VALUES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_linked_rollover_values_2027_2029_v1_v3_bank.parquet"
)

ROLLOVER_VALUES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_linked_rollover_values_2027_2029_v1_v3_bank.csv"
)

ENRICHED_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v4_rollover_enriched.parquet"
)

ENRICHED_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v4_rollover_enriched.csv"
)

FALLBACK_OVERLAP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_rollover_fallback_asset_overlap_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_rollover_team_adjustment_candidates_v1.csv"
)

PROVISIONAL_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v4_rollover_adjusted_provisional.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_linked_rollover_validation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_linked_rollover_value_metadata_v1.json"
)


REQUIRED_READY_COLUMNS = [
    "obligation_group_id",
    "claim_id",
    "asset_key",
    "current_originating_team",
    "current_beneficiary_team",
    "current_draft_year",
    "current_round_number",
    "current_protection_type",
    "current_protection_start_pick",
    "current_protection_end_pick",
    "fallback_originating_team",
    "fallback_draft_year",
    "fallback_round_number",
    "fallback_beneficiary_team",
    "fallback_protection_type",
    "fallback_protection_start_pick",
    "fallback_protection_end_pick",
    "strict_automatic_valuation_ready",
]

REQUIRED_CURVE_COLUMNS = [
    "overall_pick",
    "historical_pick_value_score",
    "historical_pick_value_rating_60_99",
    "rotation_probability_calibrated",
    "starter_probability_calibrated",
    "star_proxy_probability_calibrated",
    "year4_active_probability_calibrated",
]

KEY_COLUMNS = [
    "draft_year",
    "round_number",
    "originating_team",
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


def numeric_series(
    frame: pd.DataFrame,
    column: str,
) -> pd.Series:
    return pd.to_numeric(
        frame[
            column
        ],
        errors="coerce",
    ).astype(
        float
    )


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


def boolean_series(
    frame: pd.DataFrame,
    column: str,
) -> pd.Series:
    values = frame[
        column
    ]

    if pd.api.types.is_bool_dtype(
        values
    ):
        return values.fillna(
            False
        ).astype(
            bool
        )

    return (
        values.fillna(
            False
        )
        .astype(
            str
        )
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "y",
            }
        )
    )


def safe_conditional_mean(
    values: np.ndarray,
    condition: np.ndarray,
) -> float:
    if not np.any(
        condition
    ):
        return np.nan

    return float(
        np.mean(
            values[
                condition
            ]
        )
    )


def protection_mask(
    slots: np.ndarray,
    protection_type: str,
    start_pick: float,
    end_pick: float,
) -> np.ndarray:
    protection_type = str(
        protection_type
    ).strip().lower()

    if protection_type in {
        "",
        "none",
        "none_detected",
        "unprotected",
        "not_applicable",
    }:
        return np.zeros(
            len(
                slots
            ),
            dtype=bool,
        )

    if protection_type == "lottery":
        return slots <= 16

    if protection_type == "top_n":
        if not np.isfinite(
            end_pick
        ):
            raise ValueError(
                "Top-N protection is missing its ending pick."
            )

        return slots <= int(
            round(
                end_pick
            )
        )

    if protection_type in {
        "protected_range",
        "single_pick",
    }:
        if (
            not np.isfinite(
                start_pick
            )
            or not np.isfinite(
                end_pick
            )
        ):
            raise ValueError(
                "Protected-range clause is missing a boundary."
            )

        lower = int(
            round(
                min(
                    start_pick,
                    end_pick,
                )
            )
        )

        upper = int(
            round(
                max(
                    start_pick,
                    end_pick,
                )
            )
        )

        return (
            (
                slots
                >= lower
            )
            & (
                slots
                <= upper
            )
        )

    raise ValueError(
        "Unsupported protection type: "
        f"{protection_type}"
    )


def asset_key(
    draft_year: int,
    round_number: int,
    originating_team: str,
) -> str:
    return (
        f"{int(draft_year)}_"
        f"R{int(round_number)}_"
        f"{str(originating_team).strip()}"
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
                "The floor-corrected simulation bank was not found:\n"
                f"{path}"
            )

        self.archive = np.load(
            path,
            allow_pickle=False,
        )

        required_keys = {
            "team_abbreviations",
            "draft_years",
            "simulation_ids",
        }

        missing = (
            required_keys
            - set(
                self.archive.files
            )
        )

        if missing:
            raise ValueError(
                "The simulation bank is missing required arrays:\n"
                + "\n".join(
                    sorted(
                        missing
                    )
                )
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

        self.simulations = len(
            self.simulation_ids
        )

    def slots(
        self,
        draft_year: int,
        round_number: int,
        team: str,
    ) -> np.ndarray:
        draft_year = int(
            draft_year
        )

        round_number = int(
            round_number
        )

        team = str(
            team
        ).strip()

        if team not in self.team_to_index:
            raise KeyError(
                "Team was not found in the simulation bank: "
                f"{team}"
            )

        if draft_year not in self.draft_years:
            raise KeyError(
                "Draft year was not found in the simulation bank: "
                f"{draft_year}"
            )

        if round_number not in {
            1,
            2,
        }:
            raise ValueError(
                "Round number must be 1 or 2."
            )

        prefix = (
            "first_round"
            if round_number == 1
            else "second_round"
        )

        key = (
            f"{prefix}_{draft_year}"
        )

        if key not in self.archive.files:
            raise KeyError(
                "Simulation array was not found: "
                f"{key}"
            )

        values = self.archive[
            key
        ][
            :,
            self.team_to_index[
                team
            ],
        ].astype(
            int
        )

        if len(
            values
        ) != self.simulations:
            raise ValueError(
                "Simulation array length does not match simulation IDs."
            )

        return values

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

        size = (
            maximum_pick
            + 1
        )

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

        self.rotation = np.full(
            size,
            np.nan,
            dtype=float,
        )

        self.starter = np.full(
            size,
            np.nan,
            dtype=float,
        )

        self.star = np.full(
            size,
            np.nan,
            dtype=float,
        )

        self.year4 = np.full(
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

            self.rotation[
                pick
            ] = float(
                row.rotation_probability_calibrated
            )

            self.starter[
                pick
            ] = float(
                row.starter_probability_calibrated
            )

            self.star[
                pick
            ] = float(
                row.star_proxy_probability_calibrated
            )

            self.year4[
                pick
            ] = float(
                row.year4_active_probability_calibrated
            )

        for name, values in [
            (
                "value",
                self.value,
            ),
            (
                "rating",
                self.rating,
            ),
            (
                "rotation",
                self.rotation,
            ),
            (
                "starter",
                self.starter,
            ),
            (
                "star",
                self.star,
            ),
            (
                "year4",
                self.year4,
            ),
        ]:
            if np.isnan(
                values[
                    1:
                ]
            ).any():
                raise ValueError(
                    "Pick-value lookup is incomplete for field: "
                    f"{name}"
                )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        READY_ROLLOVERS_PATH,
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        VALUATIONS_PATH,
        TEAM_SUMMARY_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "A required linked-rollover input was not found:\n"
                f"{path}"
            )

    ready = normalize_columns(
        pd.read_csv(
            READY_ROLLOVERS_PATH
        )
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
            VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            TEAM_SUMMARY_PATH
        )
    )

    require_columns(
        ready,
        REQUIRED_READY_COLUMNS,
        "Strict rollover candidates",
    )

    require_columns(
        curve,
        REQUIRED_CURVE_COLUMNS,
        "Historical pick-value curve",
    )

    require_columns(
        pick_values,
        [
            *KEY_COLUMNS,
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
            "candidate_beneficiary_team",
            "expected_transferred_value_score",
            "expected_total_candidate_asset_value_score",
        ],
        "V3 claim valuations",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            "candidate_total_pick_asset_value_score",
        ],
        "V3 candidate team summary",
    )

    ready[
        "strict_automatic_valuation_ready"
    ] = boolean_series(
        ready,
        "strict_automatic_valuation_ready",
    )

    ready = ready.loc[
        ready[
            "strict_automatic_valuation_ready"
        ]
    ].copy()

    if ready.empty:
        raise ValueError(
            "No strict rollover candidates are ready for valuation."
        )

    if ready[
        "claim_id"
    ].duplicated().any():
        raise ValueError(
            "Strict rollover candidate claim IDs are not unique."
        )

    curve[
        "overall_pick"
    ] = numeric_series(
        curve,
        "overall_pick",
    ).round().astype(
        int
    )

    for frame in [
        pick_values,
        claims,
    ]:
        frame[
            "draft_year"
        ] = numeric_series(
            frame,
            "draft_year",
        ).round().astype(
            int
        )

        frame[
            "round_number"
        ] = numeric_series(
            frame,
            "round_number",
        ).round().astype(
            int
        )

        frame[
            "originating_team"
        ] = (
            frame[
                "originating_team"
            ]
            .astype(
                str
            )
            .str.strip()
        )

    return (
        ready,
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
    )


def discount_factor_for_asset(
    pick_values: pd.DataFrame,
    draft_year: int,
    round_number: int,
    team: str,
) -> float:
    match = pick_values.loc[
        pick_values[
            "draft_year"
        ].eq(
            int(
                draft_year
            )
        )
        & pick_values[
            "round_number"
        ].eq(
            int(
                round_number
            )
        )
        & pick_values[
            "originating_team"
        ].eq(
            str(
                team
            ).strip()
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected one V3 pick-value row for asset: "
            f"{draft_year} R{round_number} {team}; "
            f"found {len(match)}"
        )

    return float(
        match.iloc[
            0
        ][
            "time_discount_factor"
        ]
    )


def locate_fallback_claims(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
    fallback_asset_key: str,
) -> pd.DataFrame:
    matching_claims = claims.loc[
        claims[
            "asset_key"
        ].astype(
            str
        ).eq(
            fallback_asset_key
        )
    ].copy()

    if matching_claims.empty:
        return matching_claims

    valuation_columns = [
        "claim_id",
        "valuation_method",
        "valuation_status",
        "candidate_beneficiary_team",
        "expected_transferred_value_score",
        "expected_total_candidate_asset_value_score",
    ]

    return matching_claims.merge(
        valuations[
            valuation_columns
        ],
        how="left",
        on="claim_id",
        validate="one_to_one",
    )


def determine_overlap_status(
    fallback_claims: pd.DataFrame,
    rollover_claim_id: str,
    fallback_unconditional_value: float,
    rollover_beneficiary: str,
) -> dict[str, Any]:
    if fallback_claims.empty:
        return {
            "fallback_claim_rows_found": 0,
            "fallback_direct_claim_rows_found": 0,
            "fallback_existing_candidate_owner": "",
            "fallback_existing_direct_value_score": (
                np.nan
            ),
            "fallback_direct_value_difference_from_bank": (
                np.nan
            ),
            "fallback_overlap_status": (
                "no_existing_fallback_claim_found"
            ),
            "team_adjustment_auto_ready": (
                True
            ),
            "team_adjustment_note": (
                "No separately valued fallback claim was found. "
                "The conditional fallback component can be added to "
                "the rollover beneficiary without subtracting a "
                "previously counted direct claim."
            ),
        }

    other_claims = fallback_claims.loc[
        ~fallback_claims[
            "claim_id"
        ].astype(
            str
        ).eq(
            str(
                rollover_claim_id
            )
        )
    ].copy()

    direct = other_claims.loc[
        other_claims[
            "valuation_status"
        ].astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ].copy()

    if len(
        direct
    ) == 1:
        direct_row = direct.iloc[
            0
        ]

        owner = str(
            direct_row[
                "candidate_beneficiary_team"
            ]
        ).strip()

        direct_value = numeric_value(
            direct_row[
                "expected_total_candidate_asset_value_score"
            ]
        )

        difference = (
            direct_value
            - fallback_unconditional_value
        )

        value_match = (
            np.isfinite(
                difference
            )
            and abs(
                difference
            )
            <= 0.05
        )

        if not owner:
            status = (
                "one_direct_claim_missing_candidate_owner"
            )

            auto_ready = False
        elif not value_match:
            status = (
                "one_direct_claim_value_does_not_match_bank"
            )

            auto_ready = False
        elif owner == rollover_beneficiary:
            status = (
                "fallback_already_counted_to_rollover_beneficiary"
            )

            auto_ready = True
        else:
            status = (
                "fallback_counted_to_other_candidate_owner"
            )

            auto_ready = True

        return {
            "fallback_claim_rows_found": len(
                other_claims
            ),
            "fallback_direct_claim_rows_found": 1,
            "fallback_existing_candidate_owner": (
                owner
            ),
            "fallback_existing_direct_value_score": (
                direct_value
            ),
            "fallback_direct_value_difference_from_bank": (
                difference
            ),
            "fallback_overlap_status": (
                status
            ),
            "team_adjustment_auto_ready": (
                auto_ready
            ),
            "team_adjustment_note": (
                "A single separately valued direct fallback claim "
                "was found. Conditional rollover integration must "
                "reallocate the triggered fallback value from its "
                "existing candidate owner to the rollover beneficiary."
                if owner
                != rollover_beneficiary
                else
                "The fallback asset is already counted to the rollover "
                "beneficiary. Replace its unconditional direct value "
                "with its conditional retained value rather than "
                "adding the fallback component again."
            ),
        }

    if len(
        direct
    ) == 0:
        return {
            "fallback_claim_rows_found": len(
                other_claims
            ),
            "fallback_direct_claim_rows_found": 0,
            "fallback_existing_candidate_owner": "",
            "fallback_existing_direct_value_score": (
                np.nan
            ),
            "fallback_direct_value_difference_from_bank": (
                np.nan
            ),
            "fallback_overlap_status": (
                "fallback_claims_found_but_none_directly_valued"
            ),
            "team_adjustment_auto_ready": (
                False
            ),
            "team_adjustment_note": (
                "Fallback claim rows exist but none is a single direct "
                "candidate. Keep team aggregation on hold."
            ),
        }

    return {
        "fallback_claim_rows_found": len(
            other_claims
        ),
        "fallback_direct_claim_rows_found": len(
            direct
        ),
        "fallback_existing_candidate_owner": "",
        "fallback_existing_direct_value_score": (
            np.nan
        ),
        "fallback_direct_value_difference_from_bank": (
            np.nan
        ),
        "fallback_overlap_status": (
            "multiple_direct_fallback_claims_found"
        ),
        "team_adjustment_auto_ready": (
            False
        ),
        "team_adjustment_note": (
            "Multiple direct claims were found for the fallback asset. "
            "Team aggregation requires manual ownership resolution."
        ),
    }


def value_rollover(
    row: pd.Series,
    bank: SimulationBank,
    lookup: SlotValueLookup,
    pick_values: pd.DataFrame,
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> tuple[
    dict[str, Any],
    pd.DataFrame,
]:
    current_year = int(
        row[
            "current_draft_year"
        ]
    )

    current_round = int(
        row[
            "current_round_number"
        ]
    )

    current_origin = str(
        row[
            "current_originating_team"
        ]
    ).strip()

    current_beneficiary = str(
        row[
            "current_beneficiary_team"
        ]
    ).strip()

    fallback_year = int(
        row[
            "fallback_draft_year"
        ]
    )

    fallback_round = int(
        row[
            "fallback_round_number"
        ]
    )

    fallback_origin = str(
        row[
            "fallback_originating_team"
        ]
    ).strip()

    fallback_beneficiary = str(
        row[
            "fallback_beneficiary_team"
        ]
    ).strip()

    if (
        current_beneficiary
        != fallback_beneficiary
    ):
        raise ValueError(
            "Current and fallback beneficiaries differ for claim: "
            f"{row['claim_id']}"
        )

    current_slots = bank.slots(
        draft_year=current_year,
        round_number=current_round,
        team=current_origin,
    )

    fallback_slots = bank.slots(
        draft_year=fallback_year,
        round_number=fallback_round,
        team=fallback_origin,
    )

    current_protected = protection_mask(
        slots=current_slots,
        protection_type=(
            row[
                "current_protection_type"
            ]
        ),
        start_pick=numeric_value(
            row[
                "current_protection_start_pick"
            ]
        ),
        end_pick=numeric_value(
            row[
                "current_protection_end_pick"
            ]
        ),
    )

    current_conveyed = (
        ~current_protected
    )

    fallback_protected = protection_mask(
        slots=fallback_slots,
        protection_type=(
            row[
                "fallback_protection_type"
            ]
        ),
        start_pick=numeric_value(
            row[
                "fallback_protection_start_pick"
            ]
        ),
        end_pick=numeric_value(
            row[
                "fallback_protection_end_pick"
            ]
        ),
    )

    fallback_conveyed = (
        ~fallback_protected
    )

    fallback_triggered_and_conveyed = (
        current_protected
        & fallback_conveyed
    )

    no_asset_delivered = (
        current_protected
        & fallback_protected
    )

    current_discount = discount_factor_for_asset(
        pick_values=pick_values,
        draft_year=current_year,
        round_number=current_round,
        team=current_origin,
    )

    fallback_discount = discount_factor_for_asset(
        pick_values=pick_values,
        draft_year=fallback_year,
        round_number=fallback_round,
        team=fallback_origin,
    )

    current_raw_values = lookup.value[
        current_slots
    ]

    fallback_raw_values = lookup.value[
        fallback_slots
    ]

    current_discounted_values = (
        current_raw_values
        * current_discount
    )

    fallback_discounted_values = (
        fallback_raw_values
        * fallback_discount
    )

    current_component = np.where(
        current_conveyed,
        current_discounted_values,
        0.0,
    )

    fallback_component = np.where(
        fallback_triggered_and_conveyed,
        fallback_discounted_values,
        0.0,
    )

    beneficiary_total = (
        current_component
        + fallback_component
    )

    current_retained_component = np.where(
        current_protected,
        current_discounted_values,
        0.0,
    )

    fallback_retained_by_existing_holder = np.where(
        fallback_triggered_and_conveyed,
        0.0,
        fallback_discounted_values,
    )

    delivered_rating = np.where(
        current_conveyed,
        lookup.rating[
            current_slots
        ],
        np.where(
            fallback_triggered_and_conveyed,
            lookup.rating[
                fallback_slots
            ],
            np.nan,
        ),
    )

    delivered_rotation = np.where(
        current_conveyed,
        lookup.rotation[
            current_slots
        ],
        np.where(
            fallback_triggered_and_conveyed,
            lookup.rotation[
                fallback_slots
            ],
            np.nan,
        ),
    )

    delivered_starter = np.where(
        current_conveyed,
        lookup.starter[
            current_slots
        ],
        np.where(
            fallback_triggered_and_conveyed,
            lookup.starter[
                fallback_slots
            ],
            np.nan,
        ),
    )

    delivered_star = np.where(
        current_conveyed,
        lookup.star[
            current_slots
        ],
        np.where(
            fallback_triggered_and_conveyed,
            lookup.star[
                fallback_slots
            ],
            np.nan,
        ),
    )

    delivered_year4 = np.where(
        current_conveyed,
        lookup.year4[
            current_slots
        ],
        np.where(
            fallback_triggered_and_conveyed,
            lookup.year4[
                fallback_slots
            ],
            np.nan,
        ),
    )

    fallback_asset_key = asset_key(
        draft_year=fallback_year,
        round_number=fallback_round,
        originating_team=fallback_origin,
    )

    fallback_claims = locate_fallback_claims(
        claims=claims,
        valuations=valuations,
        fallback_asset_key=fallback_asset_key,
    )

    fallback_unconditional_value = float(
        np.mean(
            fallback_discounted_values
        )
    )

    overlap = determine_overlap_status(
        fallback_claims=fallback_claims,
        rollover_claim_id=str(
            row[
                "claim_id"
            ]
        ),
        fallback_unconditional_value=(
            fallback_unconditional_value
        ),
        rollover_beneficiary=current_beneficiary,
    )

    existing_current = valuations.loc[
        valuations[
            "claim_id"
        ].astype(
            str
        ).eq(
            str(
                row[
                    "claim_id"
                ]
            )
        )
    ]

    if len(
        existing_current
    ) != 1:
        raise ValueError(
            "Expected one existing valuation row for rollover claim: "
            f"{row['claim_id']}"
        )

    existing_current_row = existing_current.iloc[
        0
    ]

    existing_current_component = numeric_value(
        existing_current_row[
            "expected_transferred_value_score"
        ]
    )

    recomputed_current_component = float(
        np.mean(
            current_component
        )
    )

    current_component_difference = (
        recomputed_current_component
        - existing_current_component
    )

    if (
        not np.isfinite(
            current_component_difference
        )
        or abs(
            current_component_difference
        )
        > 0.05
    ):
        raise ValueError(
            "Recomputed current protection value does not match the "
            "V3 valuation layer for claim "
            f"{row['claim_id']}. Difference: "
            f"{current_component_difference:.6f}"
        )

    output = {
        "obligation_group_id": (
            row[
                "obligation_group_id"
            ]
        ),
        "claim_id": (
            row[
                "claim_id"
            ]
        ),
        "current_asset_key": (
            row[
                "asset_key"
            ]
        ),
        "candidate_beneficiary_team": (
            current_beneficiary
        ),
        "current_originating_team": (
            current_origin
        ),
        "current_draft_year": (
            current_year
        ),
        "current_round_number": (
            current_round
        ),
        "current_protection_type": (
            row[
                "current_protection_type"
            ]
        ),
        "current_protection_start_pick": numeric_value(
            row[
                "current_protection_start_pick"
            ]
        ),
        "current_protection_end_pick": numeric_value(
            row[
                "current_protection_end_pick"
            ]
        ),
        "fallback_asset_key": (
            fallback_asset_key
        ),
        "fallback_originating_team": (
            fallback_origin
        ),
        "fallback_draft_year": (
            fallback_year
        ),
        "fallback_round_number": (
            fallback_round
        ),
        "fallback_protection_type": (
            row[
                "fallback_protection_type"
            ]
        ),
        "current_conveyance_probability": float(
            np.mean(
                current_conveyed
            )
        ),
        "current_protection_probability": float(
            np.mean(
                current_protected
            )
        ),
        "fallback_transfer_probability": float(
            np.mean(
                fallback_triggered_and_conveyed
            )
        ),
        "fallback_conveyance_probability_given_trigger": (
            safe_conditional_mean(
                fallback_conveyed.astype(
                    float
                ),
                current_protected,
            )
        ),
        "probability_any_asset_delivered": float(
            np.mean(
                current_conveyed
                | fallback_triggered_and_conveyed
            )
        ),
        "probability_no_asset_delivered": float(
            np.mean(
                no_asset_delivered
            )
        ),
        "expected_current_pick_when_conveyed": (
            safe_conditional_mean(
                current_slots.astype(
                    float
                ),
                current_conveyed,
            )
        ),
        "expected_fallback_pick_when_transferred": (
            safe_conditional_mean(
                fallback_slots.astype(
                    float
                ),
                fallback_triggered_and_conveyed,
            )
        ),
        "current_time_discount_factor": (
            current_discount
        ),
        "fallback_time_discount_factor": (
            fallback_discount
        ),
        "expected_current_transfer_value_score": (
            recomputed_current_component
        ),
        "expected_fallback_transfer_value_score": float(
            np.mean(
                fallback_component
            )
        ),
        "expected_total_rollover_obligation_value_score": float(
            np.mean(
                beneficiary_total
            )
        ),
        "expected_current_pick_retained_value_score": float(
            np.mean(
                current_retained_component
            )
        ),
        "fallback_unconditional_asset_value_score": (
            fallback_unconditional_value
        ),
        "expected_fallback_value_retained_by_existing_holder": float(
            np.mean(
                fallback_retained_by_existing_holder
            )
        ),
        "expected_delivered_pick_rating_60_99": float(
            np.nanmean(
                delivered_rating
            )
        ),
        "expected_delivered_rotation_probability": float(
            np.nanmean(
                delivered_rotation
            )
        ),
        "expected_delivered_starter_probability": float(
            np.nanmean(
                delivered_starter
            )
        ),
        "expected_delivered_star_proxy_probability": float(
            np.nanmean(
                delivered_star
            )
        ),
        "expected_delivered_year4_active_probability": float(
            np.nanmean(
                delivered_year4
            )
        ),
        "existing_current_component_value_score": (
            existing_current_component
        ),
        "current_component_recomputation_difference": (
            current_component_difference
        ),
        "incremental_fallback_value_above_existing_claim_layer": float(
            np.mean(
                fallback_component
            )
        ),
        **overlap,
        "joint_simulation_count": (
            bank.simulations
        ),
        "valuation_method": (
            "joint_linked_rollover_obligation"
        ),
        "valuation_status": (
            "valued_joint_rollover_candidate"
        ),
        "team_aggregation_hold_flag": (
            not bool(
                overlap[
                    "team_adjustment_auto_ready"
                ]
            )
        ),
        "valuation_scope_note": (
            "Current and fallback pick outcomes are valued on aligned "
            "simulation rows. The beneficiary receives the current pick "
            "when it conveys and the fallback asset only when the current "
            "pick is protected. Team aggregation also audits whether the "
            "fallback asset is already counted elsewhere."
        ),
    }

    return (
        output,
        fallback_claims,
    )


def build_team_adjustments(
    rollover_values: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for row in rollover_values.itertuples(
        index=False
    ):
        fallback_component = float(
            row.expected_fallback_transfer_value_score
        )

        beneficiary = str(
            row.candidate_beneficiary_team
        ).strip()

        existing_owner = str(
            row.fallback_existing_candidate_owner
        ).strip()

        status = str(
            row.fallback_overlap_status
        )

        auto_ready = bool(
            row.team_adjustment_auto_ready
        )

        if not auto_ready:
            rows.append(
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "team": "",
                    "rollover_adjustment_value_score": (
                        np.nan
                    ),
                    "adjustment_type": (
                        "manual_integration_hold"
                    ),
                    "automatic_adjustment_ready": (
                        False
                    ),
                    "fallback_overlap_status": (
                        status
                    ),
                }
            )

            continue

        if status == (
            "no_existing_fallback_claim_found"
        ):
            rows.append(
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "team": (
                        beneficiary
                    ),
                    "rollover_adjustment_value_score": (
                        fallback_component
                    ),
                    "adjustment_type": (
                        "add_unrepresented_conditional_fallback"
                    ),
                    "automatic_adjustment_ready": (
                        True
                    ),
                    "fallback_overlap_status": (
                        status
                    ),
                }
            )

            continue

        fallback_unconditional = float(
            row.fallback_unconditional_asset_value_score
        )

        fallback_retained = float(
            row.expected_fallback_value_retained_by_existing_holder
        )

        if existing_owner == beneficiary:
            rows.append(
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "team": (
                        beneficiary
                    ),
                    "rollover_adjustment_value_score": (
                        fallback_retained
                        - fallback_unconditional
                    ),
                    "adjustment_type": (
                        "replace_unconditional_fallback_with_conditional_retention"
                    ),
                    "automatic_adjustment_ready": (
                        True
                    ),
                    "fallback_overlap_status": (
                        status
                    ),
                }
            )

            continue

        rows.extend(
            [
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "team": (
                        beneficiary
                    ),
                    "rollover_adjustment_value_score": (
                        fallback_component
                    ),
                    "adjustment_type": (
                        "add_conditional_fallback_to_beneficiary"
                    ),
                    "automatic_adjustment_ready": (
                        True
                    ),
                    "fallback_overlap_status": (
                        status
                    ),
                },
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "team": (
                        existing_owner
                    ),
                    "rollover_adjustment_value_score": (
                        -fallback_component
                    ),
                    "adjustment_type": (
                        "remove_conditional_fallback_from_existing_owner"
                    ),
                    "automatic_adjustment_ready": (
                        True
                    ),
                    "fallback_overlap_status": (
                        status
                    ),
                },
            ]
        )

    return pd.DataFrame(
        rows
    )


def build_provisional_team_summary(
    team_summary: pd.DataFrame,
    adjustments: pd.DataFrame,
) -> pd.DataFrame:
    output = team_summary.copy()

    adjustment_totals = (
        adjustments.loc[
            adjustments[
                "automatic_adjustment_ready"
            ].fillna(
                False
            )
            & adjustments[
                "team"
            ].astype(
                str
            ).ne(
                ""
            )
        ]
        .groupby(
            "team",
            as_index=False,
        )
        .agg(
            linked_rollover_adjustment_value_score=(
                "rollover_adjustment_value_score",
                "sum",
            ),
            linked_rollover_adjustment_rows=(
                "claim_id",
                "nunique",
            ),
        )
        .rename(
            columns={
                "team": (
                    "candidate_beneficiary_team"
                )
            }
        )
    )

    output = output.merge(
        adjustment_totals,
        how="outer",
        on="candidate_beneficiary_team",
        validate="one_to_one",
    )

    numeric_defaults = {
        "candidate_total_pick_asset_value_score": 0.0,
        "linked_rollover_adjustment_value_score": 0.0,
        "linked_rollover_adjustment_rows": 0,
    }

    for column, default in numeric_defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

        output[
            column
        ] = pd.to_numeric(
            output[
                column
            ],
            errors="coerce",
        ).fillna(
            default
        )

    output[
        "candidate_total_pick_asset_value_score_before_rollovers"
    ] = output[
        "candidate_total_pick_asset_value_score"
    ]

    output[
        "candidate_total_pick_asset_value_score_after_rollovers_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_rollovers"
        ]
        + output[
            "linked_rollover_adjustment_value_score"
        ]
    )

    output[
        "rollover_team_summary_status"
    ] = (
        "provisional_candidate_allocation"
    )

    output[
        "rollover_team_summary_scope_note"
    ] = (
        "Applies only rollover adjustments whose fallback overlap "
        "audit found zero or one compatible direct claim. Complex "
        "pools, chains, Denver's multi-year obligation, and unresolved "
        "ownership remain excluded."
    )

    return output.sort_values(
        "candidate_total_pick_asset_value_score_after_rollovers_provisional",
        ascending=False,
    ).reset_index(
        drop=True
    )


def build_enriched_valuations(
    valuations: pd.DataFrame,
    rollover_values: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    added_defaults = {
        "linked_rollover_value_modeled_flag": (
            False
        ),
        "linked_rollover_group_id": "",
        "linked_rollover_fallback_asset_key": "",
        "expected_fallback_transfer_value_score": (
            0.0
        ),
        "expected_total_rollover_obligation_value_score": (
            np.nan
        ),
        "rollover_team_aggregation_hold_flag": (
            False
        ),
        "rollover_fallback_overlap_status": "",
    }

    for column, default in added_defaults.items():
        if column not in output.columns:
            output[
                column
            ] = default

    rollover_lookup = (
        rollover_values.set_index(
            "claim_id"
        )
    )

    for claim_id, row in rollover_lookup.iterrows():
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
                "Expected one valuation row while enriching claim: "
                f"{claim_id}"
            )

        output.loc[
            mask,
            "valuation_method",
        ] = (
            "joint_linked_rollover_obligation"
        )

        output.loc[
            mask,
            "valuation_status",
        ] = (
            "valued_joint_rollover_candidate"
        )

        output.loc[
            mask,
            "expected_transferred_value_score",
        ] = float(
            row[
                "expected_total_rollover_obligation_value_score"
            ]
        )

        output.loc[
            mask,
            "expected_total_candidate_asset_value_score",
        ] = float(
            row[
                "expected_total_rollover_obligation_value_score"
            ]
        )

        output.loc[
            mask,
            "linked_rollover_value_modeled_flag",
        ] = True

        output.loc[
            mask,
            "linked_rollover_group_id",
        ] = str(
            row[
                "obligation_group_id"
            ]
        )

        output.loc[
            mask,
            "linked_rollover_fallback_asset_key",
        ] = str(
            row[
                "fallback_asset_key"
            ]
        )

        output.loc[
            mask,
            "expected_fallback_transfer_value_score",
        ] = float(
            row[
                "expected_fallback_transfer_value_score"
            ]
        )

        output.loc[
            mask,
            "expected_total_rollover_obligation_value_score",
        ] = float(
            row[
                "expected_total_rollover_obligation_value_score"
            ]
        )

        output.loc[
            mask,
            "rollover_team_aggregation_hold_flag",
        ] = bool(
            row[
                "team_aggregation_hold_flag"
            ]
        )

        output.loc[
            mask,
            "rollover_fallback_overlap_status",
        ] = str(
            row[
                "fallback_overlap_status"
            ]
        )

        if (
            "rollover_value_not_modeled_flag"
            in output.columns
        ):
            output.loc[
                mask,
                "rollover_value_not_modeled_flag",
            ] = False

        if (
            "valuation_scope_note"
            in output.columns
        ):
            output.loc[
                mask,
                "valuation_scope_note",
            ] = str(
                row[
                    "valuation_scope_note"
                ]
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
    print("FUTURE NBA LINKED ROLLOVER VALUE LAYER")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        ready,
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
    ) = load_inputs()

    bank = SimulationBank(
        SIMULATION_BANK_PATH
    )

    lookup = SlotValueLookup(
        curve
    )

    rollover_rows = []

    overlap_frames = []

    try:
        for _, row in ready.iterrows():
            (
                valued,
                fallback_claims,
            ) = value_rollover(
                row=row,
                bank=bank,
                lookup=lookup,
                pick_values=pick_values,
                claims=claims,
                valuations=valuations,
            )

            rollover_rows.append(
                valued
            )

            if fallback_claims.empty:
                overlap_frames.append(
                    pd.DataFrame(
                        [
                            {
                                "obligation_group_id": (
                                    row[
                                        "obligation_group_id"
                                    ]
                                ),
                                "rollover_claim_id": (
                                    row[
                                        "claim_id"
                                    ]
                                ),
                                "fallback_asset_key": asset_key(
                                    draft_year=int(
                                        row[
                                            "fallback_draft_year"
                                        ]
                                    ),
                                    round_number=int(
                                        row[
                                            "fallback_round_number"
                                        ]
                                    ),
                                    originating_team=(
                                        row[
                                            "fallback_originating_team"
                                        ]
                                    ),
                                ),
                                "fallback_claim_id": "",
                                "fallback_claim_found": False,
                            }
                        ]
                    )
                )
            else:
                frame = fallback_claims.copy()

                frame.insert(
                    0,
                    "obligation_group_id",
                    row[
                        "obligation_group_id"
                    ],
                )

                frame.insert(
                    1,
                    "rollover_claim_id",
                    row[
                        "claim_id"
                    ],
                )

                frame.insert(
                    2,
                    "fallback_asset_key_audited",
                    asset_key(
                        draft_year=int(
                            row[
                                "fallback_draft_year"
                            ]
                        ),
                        round_number=int(
                            row[
                                "fallback_round_number"
                            ]
                        ),
                        originating_team=(
                            row[
                                "fallback_originating_team"
                            ]
                        ),
                    ),
                )

                frame[
                    "fallback_claim_found"
                ] = True

                overlap_frames.append(
                    frame
                )
    finally:
        bank.close()

    rollover_values = pd.DataFrame(
        rollover_rows
    ).sort_values(
        [
            "candidate_beneficiary_team",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )

    overlap_audit = pd.concat(
        overlap_frames,
        ignore_index=True,
        sort=False,
    )

    team_adjustments = build_team_adjustments(
        rollover_values
    )

    provisional_team_summary = (
        build_provisional_team_summary(
            team_summary=team_summary,
            adjustments=team_adjustments,
        )
    )

    enriched_valuations = (
        build_enriched_valuations(
            valuations=valuations,
            rollover_values=rollover_values,
        )
    )

    validation = rollover_values[
        [
            "claim_id",
            "current_component_recomputation_difference",
            "probability_any_asset_delivered",
            "probability_no_asset_delivered",
            "team_adjustment_auto_ready",
            "team_aggregation_hold_flag",
        ]
    ].copy()

    validation[
        "current_component_matches_v3_layer"
    ] = (
        validation[
            "current_component_recomputation_difference"
        ].abs()
        <= 0.05
    )

    validation[
        "delivery_probabilities_sum_to_one"
    ] = (
        (
            validation[
                "probability_any_asset_delivered"
            ]
            + validation[
                "probability_no_asset_delivered"
            ]
        )
        .sub(
            1.0
        )
        .abs()
        <= 1e-12
    )

    validation[
        "validation_passed"
    ] = (
        validation[
            "current_component_matches_v3_layer"
        ]
        & validation[
            "delivery_probabilities_sum_to_one"
        ]
    )

    if not validation[
        "validation_passed"
    ].all():
        raise RuntimeError(
            "At least one linked-rollover validation check failed."
        )

    rollover_values.to_parquet(
        ROLLOVER_VALUES_PARQUET_PATH,
        index=False,
    )

    rollover_values.to_csv(
        ROLLOVER_VALUES_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        ENRICHED_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        ENRICHED_VALUATIONS_CSV_PATH,
        index=False,
    )

    overlap_audit.to_csv(
        FALLBACK_OVERLAP_AUDIT_PATH,
        index=False,
    )

    team_adjustments.to_csv(
        TEAM_ADJUSTMENTS_PATH,
        index=False,
    )

    provisional_team_summary.to_csv(
        PROVISIONAL_TEAM_SUMMARY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "strict_rollover_candidates_loaded": len(
            ready
        ),
        "linked_rollovers_valued": len(
            rollover_values
        ),
        "joint_simulations_per_obligation": int(
            rollover_values[
                "joint_simulation_count"
            ].iloc[
                0
            ]
        ),
        "total_incremental_fallback_value": float(
            rollover_values[
                "expected_fallback_transfer_value_score"
            ].sum()
        ),
        "all_validation_checks_passed": bool(
            validation[
                "validation_passed"
            ].all()
        ),
        "team_adjustments_auto_ready_count": int(
            rollover_values[
                "team_adjustment_auto_ready"
            ].sum()
        ),
        "team_aggregation_hold_count": int(
            rollover_values[
                "team_aggregation_hold_flag"
            ].sum()
        ),
        "valuation_method": (
            "Aligned simulation rows preserve the modeled correlation "
            "between the current pick and its fallback asset. The "
            "beneficiary receives exactly one scenario-dependent asset."
        ),
        "double_count_policy": [
            (
                "Every fallback asset is searched in the V3 claims and "
                "valuation layer."
            ),
            (
                "A separately counted direct fallback claim is not "
                "ignored. The triggered value is reallocated from its "
                "existing candidate owner to the rollover beneficiary."
            ),
            (
                "Multiple or inconsistent fallback claims place team "
                "aggregation on hold even though the obligation value "
                "itself remains available."
            ),
        ],
        "scope_limitations": [
            (
                "The Denver protection ladder and onward-conveyance "
                "chain remain excluded."
            ),
            (
                "Favorability pools, complex swap chains, and other "
                "manual dependency groups remain unresolved."
            ),
            (
                "The provisional team summary is not a final ownership-"
                "certified asset inventory."
            ),
        ],
        "output_files": {
            "rollover_values": str(
                ROLLOVER_VALUES_PARQUET_PATH
            ),
            "enriched_claim_values": str(
                ENRICHED_VALUATIONS_PARQUET_PATH
            ),
            "fallback_overlap_audit": str(
                FALLBACK_OVERLAP_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "provisional_team_summary": str(
                PROVISIONAL_TEAM_SUMMARY_PATH
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
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print("=" * 80)
    print("LINKED ROLLOVER VALUES CREATED")
    print("=" * 80)
    print(
        f"Strict rollover candidates loaded: "
        f"{len(ready):,}"
    )
    print(
        f"Linked rollovers valued: "
        f"{len(rollover_values):,}"
    )
    print(
        "Joint simulations per obligation: "
        f"{int(rollover_values['joint_simulation_count'].iloc[0]):,}"
    )
    print(
        "Team adjustments automatically ready: "
        f"{int(rollover_values['team_adjustment_auto_ready'].sum()):,}"
    )
    print(
        "Team aggregation holds: "
        f"{int(rollover_values['team_aggregation_hold_flag'].sum()):,}"
    )
    print(
        "All validation checks passed: "
        f"{bool(validation['validation_passed'].all())}"
    )
    print()

    print("ROLLOVER VALUE SUMMARY")
    display_columns = [
        "claim_id",
        "candidate_beneficiary_team",
        "current_asset_key",
        "current_conveyance_probability",
        "fallback_asset_key",
        "fallback_transfer_probability",
        "expected_current_transfer_value_score",
        "expected_fallback_transfer_value_score",
        "expected_total_rollover_obligation_value_score",
        "fallback_overlap_status",
        "fallback_existing_candidate_owner",
        "team_adjustment_auto_ready",
    ]

    display = rollover_values[
        display_columns
    ].copy()

    probability_columns = [
        "current_conveyance_probability",
        "fallback_transfer_probability",
    ]

    for column in probability_columns:
        display[
            column
        ] = (
            pd.to_numeric(
                display[
                    column
                ],
                errors="coerce",
            )
            * 100.0
        ).round(
            2
        )

    value_columns = [
        "expected_current_transfer_value_score",
        "expected_fallback_transfer_value_score",
        "expected_total_rollover_obligation_value_score",
    ]

    for column in value_columns:
        display[
            column
        ] = pd.to_numeric(
            display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("TEAM ADJUSTMENT CANDIDATES")
    adjustment_display = team_adjustments.copy()

    if not adjustment_display.empty:
        adjustment_display[
            "rollover_adjustment_value_score"
        ] = pd.to_numeric(
            adjustment_display[
                "rollover_adjustment_value_score"
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
    else:
        print(
            "No team adjustments were created."
        )

    print()
    print("SAVED FILES")
    print(ROLLOVER_VALUES_PARQUET_PATH)
    print(ROLLOVER_VALUES_CSV_PATH)
    print(ENRICHED_VALUATIONS_PARQUET_PATH)
    print(ENRICHED_VALUATIONS_CSV_PATH)
    print(FALLBACK_OVERLAP_AUDIT_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(PROVISIONAL_TEAM_SUMMARY_PATH)
    print(VALIDATION_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()