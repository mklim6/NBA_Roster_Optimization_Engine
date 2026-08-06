from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-pick-conditional-swap-value-v1-fixed-schema-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLAIMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_obligation_claims_2027_2029_v2.parquet"
)

SIMULATION_BANK_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_draft_pick_simulation_bank_2027_2029_v2.npz"
)

PICK_CURVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

ALL_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v1.parquet"
)

ALL_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v1.csv"
)

PROTECTION_VALUATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_protection_value_components_2027_2029_v1.csv"
)

SWAP_VALUATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_simple_swap_option_values_2027_2029_v1.csv"
)

DIRECT_ASSET_VALUES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_direct_asset_values_2027_2029_v1.csv"
)

UNRESOLVED_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_unresolved_complex_claims_2027_2029_v1.csv"
)

TEAM_CANDIDATE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_2027_2029_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_conditional_swap_value_metadata_v1.json"
)


REQUIRED_CLAIM_COLUMNS = [
    "claim_id",
    "asset_key",
    "draft_year",
    "round_number",
    "originating_team",
    "destination_team_sequence",
    "destination_team_count",
    "claim_type",
    "resolution_status",
    "resolved_owner_candidate",
    "swap_flag",
    "favorability_pool_flag",
    "conditional_language_flag",
    "protection_flag",
    "protection_type",
    "protection_start_pick",
    "protection_end_pick",
    "rollover_or_fallback_language_flag",
    "multiple_claim_rows_flag",
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
    "expected_overall_pick",
    "time_discount_factor",
    "time_discounted_pick_value_score",
    "expected_pick_value_rating_60_99",
]

REQUIRED_PICK_CURVE_COLUMNS = [
    "overall_pick",
    "historical_pick_value_score",
    "historical_pick_value_rating_60_99",
    "rotation_probability_calibrated",
    "starter_probability_calibrated",
    "star_proxy_probability_calibrated",
    "year4_active_probability_calibrated",
]

DIRECT_RESOLUTION_STATUSES = {
    "resolved_own",
    "resolved_outright_candidate",
}

SIMPLE_PROTECTION_TYPES = {
    "top_n",
    "protected_range",
    "single_pick",
    "lottery",
}

SWAP_PHRASE_PATTERNS = [
    re.compile(
        r"\bright\s+to\s+swap\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\boption\s+to\s+swap\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmay\s+swap\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bswap\s+rights?\b",
        re.IGNORECASE,
    ),
]

TEAM_CODES = {
    "ATL",
    "BOS",
    "BKN",
    "CHA",
    "CHI",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GSW",
    "HOU",
    "IND",
    "LAC",
    "LAL",
    "MEM",
    "MIA",
    "MIL",
    "MIN",
    "NOP",
    "NYK",
    "OKC",
    "ORL",
    "PHI",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "TOR",
    "UTA",
    "WAS",
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


def numeric_series(
    frame: pd.DataFrame,
    column: str,
    fill_value: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(
        frame[
            column
        ],
        errors="coerce",
    )

    if fill_value is not None:
        values = values.fillna(
            fill_value
        )

    return values.astype(
        float
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
        values.astype(
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


def split_team_sequence(
    value: Any,
) -> list[str]:
    if value is None or pd.isna(
        value
    ):
        return []

    output = []

    for token in re.split(
        r"[|,;/ ]+",
        str(
            value
        ).strip(),
    ):
        team = token.strip().upper()

        if (
            team in TEAM_CODES
            and team not in output
        ):
            output.append(
                team
            )

    return output


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
            for key, item
            in value.items()
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


def load_claims() -> pd.DataFrame:
    if not CLAIMS_PATH.exists():
        raise FileNotFoundError(
            "Future-pick obligation claims were not found:\n"
            f"{CLAIMS_PATH}"
        )

    claims = normalize_columns(
        pd.read_parquet(
            CLAIMS_PATH
        )
    )

    require_columns(
        claims,
        REQUIRED_CLAIM_COLUMNS,
        "Future-pick obligation claims",
    )

    claims[
        "draft_year"
    ] = numeric_series(
        claims,
        "draft_year",
    ).round().astype(
        int
    )

    claims[
        "round_number"
    ] = numeric_series(
        claims,
        "round_number",
    ).round().astype(
        int
    )

    for column in [
        "destination_team_count",
        "protection_start_pick",
        "protection_end_pick",
        "expected_overall_pick",
        "time_discount_factor",
        "time_discounted_pick_value_score",
        "expected_pick_value_rating_60_99",
    ]:
        claims[
            column
        ] = numeric_series(
            claims,
            column,
        )

    for column in [
        "swap_flag",
        "favorability_pool_flag",
        "conditional_language_flag",
        "protection_flag",
        "rollover_or_fallback_language_flag",
        "multiple_claim_rows_flag",
    ]:
        claims[
            column
        ] = boolean_series(
            claims,
            column,
        )

    claims[
        "destination_teams"
    ] = claims[
        "destination_team_sequence"
    ].map(
        split_team_sequence
    )

    claims[
        "full_claim_text"
    ] = (
        claims[
            "pick_heading"
        ].fillna(
            ""
        ).astype(
            str
        )
        + " "
        + claims[
            "transaction_text"
        ].fillna(
            ""
        ).astype(
            str
        )
        + " "
        + claims[
            "full_obligation_text"
        ].fillna(
            ""
        ).astype(
            str
        )
    ).str.replace(
        r"\s+",
        " ",
        regex=True,
    ).str.strip()

    return claims


def load_pick_curve() -> pd.DataFrame:
    if not PICK_CURVE_PATH.exists():
        raise FileNotFoundError(
            "Calibrated pick-value curve was not found:\n"
            f"{PICK_CURVE_PATH}"
        )

    curve = normalize_columns(
        pd.read_parquet(
            PICK_CURVE_PATH
        )
    )

    require_columns(
        curve,
        REQUIRED_PICK_CURVE_COLUMNS,
        "Calibrated pick-value curve",
    )

    curve[
        "overall_pick"
    ] = numeric_series(
        curve,
        "overall_pick",
    ).round().astype(
        int
    )

    duplicate_mask = curve.duplicated(
        subset=[
            "overall_pick"
        ],
        keep=False,
    )

    if duplicate_mask.any():
        raise ValueError(
            "The pick curve contains duplicate overall-pick rows."
        )

    return curve.sort_values(
        "overall_pick"
    ).reset_index(
        drop=True
    )


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
                "Simulation bank is missing arrays:\n"
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

        self.team_to_index = {
            team: index
            for index, team in enumerate(
                self.teams
            )
        }

        self.simulations = len(
            self.archive[
                "simulation_ids"
            ]
        )

        for draft_year in self.draft_years:
            for round_name in [
                "first_round",
                "second_round",
            ]:
                key = (
                    f"{round_name}_{draft_year}"
                )

                if key not in self.archive.files:
                    raise ValueError(
                        "Simulation bank is missing array:\n"
                        f"{key}"
                    )

                matrix = self.archive[
                    key
                ]

                expected_shape = (
                    self.simulations,
                    len(
                        self.teams
                    ),
                )

                if matrix.shape != expected_shape:
                    raise ValueError(
                        f"{key} has shape {matrix.shape}; "
                        f"expected {expected_shape}."
                    )

    def slots(
        self,
        draft_year: int,
        round_number: int,
        team: str,
    ) -> np.ndarray:
        if team not in self.team_to_index:
            raise KeyError(
                f"Team was not found in simulation bank: {team}"
            )

        if draft_year not in self.draft_years:
            raise KeyError(
                "Draft year was not found in simulation bank: "
                f"{draft_year}"
            )

        prefix = (
            "first_round"
            if round_number == 1
            else "second_round"
        )

        key = (
            f"{prefix}_{draft_year}"
        )

        return self.archive[
            key
        ][
            :,
            self.team_to_index[
                team
            ],
        ].astype(
            int
        )


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

        self.rotation = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        self.starter = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        self.star = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        self.year4 = np.full(
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

        if np.isnan(
            self.value[
                1:
            ]
        ).any():
            raise ValueError(
                "The pick-value lookup does not cover every slot."
            )


def protection_mask(
    slots: np.ndarray,
    protection_type: str,
    start_pick: float,
    end_pick: float,
) -> np.ndarray:
    if protection_type == "lottery":
        return slots <= 16

    if protection_type == "top_n":
        if not np.isfinite(
            end_pick
        ):
            raise ValueError(
                "Top-N protection has no ending selection."
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
                "Protected range is missing a boundary."
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
            (slots >= lower)
            & (slots <= upper)
        )

    raise ValueError(
        "Unsupported simple protection type: "
        f"{protection_type}"
    )


def safe_conditional_mean(
    values: np.ndarray,
    mask: np.ndarray,
) -> float:
    if not np.any(
        mask
    ):
        return float(
            "nan"
        )

    return float(
        np.mean(
            values[
                mask
            ]
        )
    )


def base_output_row(
    row: pd.Series,
) -> dict[str, Any]:
    return {
        column: row[
            column
        ]
        for column in row.index
        if column
        not in {
            "destination_teams"
        }
    }


def value_direct_claim(
    row: pd.Series,
) -> dict[str, Any]:
    output = base_output_row(
        row
    )

    owner = str(
        row[
            "resolved_owner_candidate"
        ]
    ).strip()

    output.update(
        {
            "valuation_method": (
                "direct_asset_value"
            ),
            "valuation_status": (
                "valued_direct_candidate"
            ),
            "valuation_confidence_tier": (
                "high_for_structure_candidate"
            ),
            "candidate_beneficiary_team": (
                owner
            ),
            "conveyance_probability": 1.0,
            "retention_probability": 0.0,
            "expected_transferred_value_score": float(
                row[
                    "time_discounted_pick_value_score"
                ]
            ),
            "expected_retained_value_score": 0.0,
            "expected_swap_option_value_score": 0.0,
            "expected_total_candidate_asset_value_score": float(
                row[
                    "time_discounted_pick_value_score"
                ]
            ),
            "valuation_scope_note": (
                "Direct current-owner candidate. Ownership remains "
                "subject to source verification and CBA tradability."
            ),
        }
    )

    return output


def value_simple_protection(
    row: pd.Series,
    bank: SimulationBank,
    lookup: SlotValueLookup,
) -> dict[str, Any]:
    output = base_output_row(
        row
    )

    draft_year = int(
        row[
            "draft_year"
        ]
    )

    round_number = int(
        row[
            "round_number"
        ]
    )

    origin = str(
        row[
            "originating_team"
        ]
    )

    destination_teams = row[
        "destination_teams"
    ]

    destination = (
        destination_teams[
            0
        ]
        if len(
            destination_teams
        )
        == 1
        else ""
    )

    slots = bank.slots(
        draft_year=draft_year,
        round_number=round_number,
        team=origin,
    )

    protected = protection_mask(
        slots=slots,
        protection_type=str(
            row[
                "protection_type"
            ]
        ),
        start_pick=float(
            row[
                "protection_start_pick"
            ]
        ),
        end_pick=float(
            row[
                "protection_end_pick"
            ]
        ),
    )

    conveyed = ~protected

    time_discount = float(
        row[
            "time_discount_factor"
        ]
    )

    raw_values = lookup.value[
        slots
    ]

    discounted_values = (
        raw_values
        * time_discount
    )

    ratings = lookup.rating[
        slots
    ]

    output.update(
        {
            "valuation_method": (
                "single_year_protection_component"
            ),
            "valuation_status": (
                "valued_current_year_component"
                if not bool(
                    row[
                        "rollover_or_fallback_language_flag"
                    ]
                )
                else "valued_partial_rollover_component"
            ),
            "valuation_confidence_tier": (
                "medium_structure_candidate"
            ),
            "candidate_beneficiary_team": (
                destination
            ),
            "candidate_retaining_team": (
                origin
            ),
            "conveyance_probability": float(
                np.mean(
                    conveyed
                )
            ),
            "retention_probability": float(
                np.mean(
                    protected
                )
            ),
            "expected_transferred_value_score": float(
                np.mean(
                    np.where(
                        conveyed,
                        discounted_values,
                        0.0,
                    )
                )
            ),
            "expected_retained_value_score": float(
                np.mean(
                    np.where(
                        protected,
                        discounted_values,
                        0.0,
                    )
                )
            ),
            "expected_swap_option_value_score": 0.0,
            "expected_total_candidate_asset_value_score": float(
                np.mean(
                    discounted_values
                )
            ),
            "expected_conveyed_pick": (
                safe_conditional_mean(
                    slots.astype(
                        float
                    ),
                    conveyed,
                )
            ),
            "expected_protected_pick": (
                safe_conditional_mean(
                    slots.astype(
                        float
                    ),
                    protected,
                )
            ),
            "expected_conveyed_pick_rating": (
                safe_conditional_mean(
                    ratings,
                    conveyed,
                )
            ),
            "expected_protected_pick_rating": (
                safe_conditional_mean(
                    ratings,
                    protected,
                )
            ),
            "conveyed_value_given_conveyance": (
                safe_conditional_mean(
                    discounted_values,
                    conveyed,
                )
            ),
            "retained_value_given_protection": (
                safe_conditional_mean(
                    discounted_values,
                    protected,
                )
            ),
            "rollover_value_not_modeled_flag": bool(
                row[
                    "rollover_or_fallback_language_flag"
                ]
            ),
            "valuation_scope_note": (
                "Current-year protection component only. Any rollover, "
                "conversion, extinguishment, or linked-year value must "
                "be added by the dependency engine."
            ),
        }
    )

    return output


def swap_language_is_explicit(
    text: str,
) -> bool:
    return any(
        pattern.search(
            text
        )
        is not None
        for pattern in SWAP_PHRASE_PATTERNS
    )


def value_simple_swap(
    row: pd.Series,
    bank: SimulationBank,
    lookup: SlotValueLookup,
) -> dict[str, Any]:
    output = base_output_row(
        row
    )

    draft_year = int(
        row[
            "draft_year"
        ]
    )

    round_number = int(
        row[
            "round_number"
        ]
    )

    origin = str(
        row[
            "originating_team"
        ]
    )

    controller = row[
        "destination_teams"
    ][
        0
    ]

    origin_slots = bank.slots(
        draft_year=draft_year,
        round_number=round_number,
        team=origin,
    )

    controller_slots = bank.slots(
        draft_year=draft_year,
        round_number=round_number,
        team=controller,
    )

    origin_values = lookup.value[
        origin_slots
    ]

    controller_values = lookup.value[
        controller_slots
    ]

    time_discount = float(
        row[
            "time_discount_factor"
        ]
    )

    raw_option_gain = np.maximum(
        origin_values
        - controller_values,
        0.0,
    )

    discounted_option_gain = (
        raw_option_gain
        * time_discount
    )

    exercised = (
        origin_values
        > controller_values
    )

    selected_slots = np.where(
        exercised,
        origin_slots,
        controller_slots,
    )

    controller_baseline_discounted = (
        controller_values
        * time_discount
    )

    controller_post_swap_discounted = (
        np.maximum(
            origin_values,
            controller_values,
        )
        * time_discount
    )

    counterparty_post_swap_discounted = (
        np.minimum(
            origin_values,
            controller_values,
        )
        * time_discount
    )

    slot_improvement = np.maximum(
        controller_slots
        - origin_slots,
        0,
    )

    output.update(
        {
            "valuation_method": (
                "simple_two_team_swap_option"
            ),
            "valuation_status": (
                "valued_swap_option_candidate"
            ),
            "valuation_confidence_tier": (
                "medium_structure_candidate"
            ),
            "candidate_beneficiary_team": (
                controller
            ),
            "candidate_counterparty_team": (
                origin
            ),
            "swap_exercise_probability": float(
                np.mean(
                    exercised
                )
            ),
            "expected_swap_option_value_score": float(
                np.mean(
                    discounted_option_gain
                )
            ),
            "expected_transferred_value_score": 0.0,
            "expected_retained_value_score": 0.0,
            "expected_total_candidate_asset_value_score": float(
                np.mean(
                    discounted_option_gain
                )
            ),
            "controller_baseline_own_pick_value_score": float(
                np.mean(
                    controller_baseline_discounted
                )
            ),
            "controller_post_swap_pick_value_score": float(
                np.mean(
                    controller_post_swap_discounted
                )
            ),
            "counterparty_post_swap_pick_value_score": float(
                np.mean(
                    counterparty_post_swap_discounted
                )
            ),
            "expected_selected_pick_after_swap": float(
                np.mean(
                    selected_slots
                )
            ),
            "expected_slot_improvement_unconditional": float(
                np.mean(
                    slot_improvement
                )
            ),
            "expected_slot_improvement_when_exercised": (
                safe_conditional_mean(
                    slot_improvement.astype(
                        float
                    ),
                    exercised,
                )
            ),
            "expected_option_gain_when_exercised": (
                safe_conditional_mean(
                    discounted_option_gain,
                    exercised,
                )
            ),
            "valuation_scope_note": (
                "Candidate value of a simple two-team same-year, "
                "same-round swap option. Ownership, priority among "
                "multiple swap rights, protections, and chaining "
                "must still be verified."
            ),
        }
    )

    return output


def unresolved_claim(
    row: pd.Series,
    reason: str,
) -> dict[str, Any]:
    output = base_output_row(
        row
    )

    output.update(
        {
            "valuation_method": (
                "not_automatically_valued"
            ),
            "valuation_status": (
                "requires_dependency_review"
            ),
            "valuation_confidence_tier": (
                "unresolved"
            ),
            "automatic_exclusion_reason": (
                reason
            ),
            "candidate_beneficiary_team": "",
            "conveyance_probability": np.nan,
            "retention_probability": np.nan,
            "swap_exercise_probability": np.nan,
            "expected_transferred_value_score": np.nan,
            "expected_retained_value_score": np.nan,
            "expected_swap_option_value_score": np.nan,
            "expected_total_candidate_asset_value_score": np.nan,
            "valuation_scope_note": (
                "No automatic value assigned because the claim "
                "requires a linked-obligation or multi-asset parser."
            ),
        }
    )

    return output


def classify_and_value(
    row: pd.Series,
    bank: SimulationBank,
    lookup: SlotValueLookup,
) -> dict[str, Any]:
    if (
        str(
            row[
                "resolution_status"
            ]
        )
        in DIRECT_RESOLUTION_STATUSES
        and not bool(
            row[
                "multiple_claim_rows_flag"
            ]
        )
    ):
        return value_direct_claim(
            row
        )

    simple_protection_ready = (
        bool(
            row[
                "protection_flag"
            ]
        )
        and str(
            row[
                "protection_type"
            ]
        )
        in SIMPLE_PROTECTION_TYPES
        and not bool(
            row[
                "swap_flag"
            ]
        )
        and not bool(
            row[
                "favorability_pool_flag"
            ]
        )
        and len(
            row[
                "destination_teams"
            ]
        )
        == 1
        and not bool(
            row[
                "multiple_claim_rows_flag"
            ]
        )
    )

    if simple_protection_ready:
        try:
            return value_simple_protection(
                row=row,
                bank=bank,
                lookup=lookup,
            )
        except Exception as error:
            return unresolved_claim(
                row,
                (
                    "simple_protection_runtime_error: "
                    f"{type(error).__name__}: {error}"
                ),
            )

    simple_swap_ready = (
        bool(
            row[
                "swap_flag"
            ]
        )
        and not bool(
            row[
                "favorability_pool_flag"
            ]
        )
        and not bool(
            row[
                "protection_flag"
            ]
        )
        and len(
            row[
                "destination_teams"
            ]
        )
        == 1
        and row[
            "destination_teams"
        ][
            0
        ]
        != str(
            row[
                "originating_team"
            ]
        )
        and not bool(
            row[
                "multiple_claim_rows_flag"
            ]
        )
        and swap_language_is_explicit(
            str(
                row[
                    "full_claim_text"
                ]
            )
        )
    )

    if simple_swap_ready:
        try:
            return value_simple_swap(
                row=row,
                bank=bank,
                lookup=lookup,
            )
        except Exception as error:
            return unresolved_claim(
                row,
                (
                    "simple_swap_runtime_error: "
                    f"{type(error).__name__}: {error}"
                ),
            )

    reasons = []

    if bool(
        row[
            "multiple_claim_rows_flag"
        ]
    ):
        reasons.append(
            "multiple_claim_rows"
        )

    if bool(
        row[
            "favorability_pool_flag"
        ]
    ):
        reasons.append(
            "multi_pick_favorability_pool"
        )

    if bool(
        row[
            "swap_flag"
        ]
    ):
        reasons.append(
            "complex_or_unparsed_swap"
        )

    if bool(
        row[
            "protection_flag"
        ]
    ):
        reasons.append(
            "complex_or_unparsed_protection"
        )

    if bool(
        row[
            "rollover_or_fallback_language_flag"
        ]
    ):
        reasons.append(
            "rollover_or_fallback_dependency"
        )

    if len(
        row[
            "destination_teams"
        ]
    ) != 1:
        reasons.append(
            "destination_not_single_team"
        )

    if not reasons:
        reasons.append(
            "unparsed_claim_structure"
        )

    return unresolved_claim(
        row,
        "|".join(
            reasons
        ),
    )


def build_team_candidate_summary(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    valuations = valuations.copy()

    summary_schema_defaults = {
        "candidate_beneficiary_team": "",
        "candidate_retaining_team": "",
        "expected_total_candidate_asset_value_score": np.nan,
        "expected_transferred_value_score": np.nan,
        "expected_retained_value_score": np.nan,
        "expected_swap_option_value_score": np.nan,
    }

    for column, default_value in summary_schema_defaults.items():
        if column not in valuations.columns:
            valuations[column] = default_value

    direct = valuations.loc[
        valuations[
            "valuation_status"
        ].eq(
            "valued_direct_candidate"
        )
        & valuations[
            "candidate_beneficiary_team"
        ].astype(str).ne(
            ""
        )
    ].copy()

    direct_summary = (
        direct.groupby(
            "candidate_beneficiary_team",
            as_index=False,
        )
        .agg(
            direct_asset_claims=(
                "claim_id",
                "nunique",
            ),
            direct_candidate_value_score=(
                "expected_total_candidate_asset_value_score",
                "sum",
            ),
        )
    )

    protections = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "single_year_protection_component"
        )
    ].copy()

    destination_protection = (
        protections.loc[
            protections[
                "candidate_beneficiary_team"
            ].astype(str).ne(
                ""
            )
        ]
        .groupby(
            "candidate_beneficiary_team",
            as_index=False,
        )
        .agg(
            protected_transfer_claims=(
                "claim_id",
                "nunique",
            ),
            expected_protected_transfer_value_score=(
                "expected_transferred_value_score",
                "sum",
            ),
        )
    )

    origin_protection = (
        protections.loc[
            protections[
                "candidate_retaining_team"
            ].astype(str).ne(
                ""
            )
        ]
        .groupby(
            "candidate_retaining_team",
            as_index=False,
        )
        .agg(
            protection_retention_claims=(
                "claim_id",
                "nunique",
            ),
            expected_retained_protection_value_score=(
                "expected_retained_value_score",
                "sum",
            ),
        )
        .rename(
            columns={
                "candidate_retaining_team": (
                    "candidate_beneficiary_team"
                )
            }
        )
    )

    swaps = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "simple_two_team_swap_option"
        )
    ].copy()

    swap_summary = (
        swaps.loc[
            swaps[
                "candidate_beneficiary_team"
            ].astype(str).ne(
                ""
            )
        ]
        .groupby(
            "candidate_beneficiary_team",
            as_index=False,
        )
        .agg(
            simple_swap_option_claims=(
                "claim_id",
                "nunique",
            ),
            expected_swap_option_value_score=(
                "expected_swap_option_value_score",
                "sum",
            ),
        )
    )

    all_teams = pd.DataFrame(
        {
            "candidate_beneficiary_team": sorted(
                TEAM_CODES
            )
        }
    )

    summary = all_teams.copy()

    for frame in [
        direct_summary,
        destination_protection,
        origin_protection,
        swap_summary,
    ]:
        summary = summary.merge(
            frame,
            how="left",
            on="candidate_beneficiary_team",
            validate="one_to_one",
        )

    numeric_columns = [
        column
        for column in summary.columns
        if column
        != "candidate_beneficiary_team"
    ]

    summary[
        numeric_columns
    ] = summary[
        numeric_columns
    ].fillna(
        0.0
    )

    summary[
        "candidate_total_pick_asset_value_score"
    ] = (
        summary[
            "direct_candidate_value_score"
        ]
        + summary[
            "expected_protected_transfer_value_score"
        ]
        + summary[
            "expected_retained_protection_value_score"
        ]
        + summary[
            "expected_swap_option_value_score"
        ]
    )

    summary[
        "summary_scope_note"
    ] = (
        "Candidate values from direct assets, simple current-year "
        "protection components, and simple swap options only. "
        "Unresolved pools, chains, and rollover dependencies are excluded."
    )

    return summary.sort_values(
        "candidate_total_pick_asset_value_score",
        ascending=False,
    ).reset_index(
        drop=True
    )


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
    print("FUTURE NBA PICK PROTECTION AND SWAP VALUE LAYER")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    claims = load_claims()
    curve = load_pick_curve()

    bank = SimulationBank(
        SIMULATION_BANK_PATH
    )

    lookup = SlotValueLookup(
        curve
    )

    valuation_rows = []

    for _, row in claims.iterrows():
        valuation_rows.append(
            classify_and_value(
                row=row,
                bank=bank,
                lookup=lookup,
            )
        )

    valuations = pd.DataFrame(
        valuation_rows
    )

    # Keep a stable output schema even when no claim qualifies for
    # a particular automatic valuation category. Without these
    # defaults, optional columns such as candidate_retaining_team
    # do not exist when the protection subset is empty.
    stable_schema_defaults = {
        "candidate_beneficiary_team": "",
        "candidate_retaining_team": "",
        "candidate_counterparty_team": "",
        "conveyance_probability": np.nan,
        "retention_probability": np.nan,
        "swap_exercise_probability": np.nan,
        "expected_transferred_value_score": np.nan,
        "expected_retained_value_score": np.nan,
        "expected_swap_option_value_score": np.nan,
        "expected_total_candidate_asset_value_score": np.nan,
        "expected_conveyed_pick": np.nan,
        "expected_protected_pick": np.nan,
        "expected_conveyed_pick_rating": np.nan,
        "expected_protected_pick_rating": np.nan,
        "conveyed_value_given_conveyance": np.nan,
        "retained_value_given_protection": np.nan,
        "rollover_value_not_modeled_flag": False,
        "controller_baseline_own_pick_value_score": np.nan,
        "controller_post_swap_pick_value_score": np.nan,
        "counterparty_post_swap_pick_value_score": np.nan,
        "expected_selected_pick_after_swap": np.nan,
        "expected_slot_improvement_unconditional": np.nan,
        "expected_slot_improvement_when_exercised": np.nan,
        "expected_option_gain_when_exercised": np.nan,
        "automatic_exclusion_reason": "",
    }

    for column, default_value in stable_schema_defaults.items():
        if column not in valuations.columns:
            valuations[column] = default_value

    if len(
        valuations
    ) != len(
        claims
    ):
        raise RuntimeError(
            "Valuation row count does not match claim row count."
        )

    if valuations[
        "claim_id"
    ].duplicated().any():
        raise ValueError(
            "Duplicate claim IDs were produced."
        )

    direct = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "direct_asset_value"
        )
    ].copy()

    protections = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "single_year_protection_component"
        )
    ].copy()

    swaps = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "simple_two_team_swap_option"
        )
    ].copy()

    unresolved = valuations.loc[
        valuations[
            "valuation_method"
        ].eq(
            "not_automatically_valued"
        )
    ].copy()

    team_summary = (
        build_team_candidate_summary(
            valuations
        )
    )

    valuations.to_parquet(
        ALL_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    valuations.to_csv(
        ALL_VALUATIONS_CSV_PATH,
        index=False,
    )

    direct.to_csv(
        DIRECT_ASSET_VALUES_PATH,
        index=False,
    )

    protections.to_csv(
        PROTECTION_VALUATIONS_PATH,
        index=False,
    )

    swaps.to_csv(
        SWAP_VALUATIONS_PATH,
        index=False,
    )

    unresolved.to_csv(
        UNRESOLVED_REVIEW_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_CANDIDATE_SUMMARY_PATH,
        index=False,
    )

    method_counts = (
        valuations[
            "valuation_method"
        ]
        .value_counts(
            dropna=False
        )
        .to_dict()
    )

    status_counts = (
        valuations[
            "valuation_status"
        ]
        .value_counts(
            dropna=False
        )
        .to_dict()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "claim_rows_loaded": len(
            claims
        ),
        "simulation_bank_rows": (
            bank.simulations
        ),
        "simulation_bank_teams": len(
            bank.teams
        ),
        "simulation_bank_draft_years": (
            bank.draft_years
        ),
        "direct_asset_claims_valued": len(
            direct
        ),
        "simple_protection_claims_valued": len(
            protections
        ),
        "simple_swap_options_valued": len(
            swaps
        ),
        "unresolved_claims": len(
            unresolved
        ),
        "valuation_method_counts": (
            method_counts
        ),
        "valuation_status_counts": (
            status_counts
        ),
        "protection_method": [
            (
                "The actual simulated slot determines whether the "
                "pick conveys or remains protected."
            ),
            (
                "Expected transfer value equals the mean discounted "
                "slot value in simulations where the pick conveys."
            ),
            (
                "Expected retained value equals the mean discounted "
                "slot value in simulations where protection applies."
            ),
            (
                "Rollover and conversion value is intentionally "
                "excluded until the linked-year dependency engine."
            ),
        ],
        "swap_method": [
            (
                "Only explicit, unprotected, single-destination, "
                "two-team same-year swap candidates are valued."
            ),
            (
                "The option is exercised when the originating pick "
                "has greater modeled slot value than the controller's "
                "own pick."
            ),
            (
                "Swap value is the expected positive value improvement "
                "over the controller's baseline own pick."
            ),
        ],
        "limitations": [
            (
                "All owner and controller assignments remain candidates "
                "until transaction language is verified."
            ),
            (
                "Multi-team favorable pools, chained swap priorities, "
                "overlapping claims, and linked rollover obligations "
                "remain unresolved."
            ),
            (
                "This layer does not determine whether an asset is "
                "currently tradable under the CBA."
            ),
            (
                "Team summaries exclude every unresolved claim and "
                "therefore understate teams with complex draft rights."
            ),
        ],
        "output_files": {
            "all_claim_valuations": str(
                ALL_VALUATIONS_PARQUET_PATH
            ),
            "direct_asset_values": str(
                DIRECT_ASSET_VALUES_PATH
            ),
            "protection_components": str(
                PROTECTION_VALUATIONS_PATH
            ),
            "simple_swap_options": str(
                SWAP_VALUATIONS_PATH
            ),
            "unresolved_review": str(
                UNRESOLVED_REVIEW_PATH
            ),
            "candidate_team_summary": str(
                TEAM_CANDIDATE_SUMMARY_PATH
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
    print("PICK PROTECTION AND SWAP VALUES CREATED")
    print("=" * 80)
    print(
        f"Claim rows loaded: "
        f"{len(claims):,}"
    )
    print(
        f"Direct asset claims valued: "
        f"{len(direct):,}"
    )
    print(
        "Simple protection components valued: "
        f"{len(protections):,}"
    )
    print(
        f"Simple swap options valued: "
        f"{len(swaps):,}"
    )
    print(
        f"Claims still unresolved: "
        f"{len(unresolved):,}"
    )
    print()

    print("VALUATION METHODS")
    method_display = (
        valuations[
            "valuation_method"
        ]
        .value_counts()
        .rename_axis(
            "valuation_method"
        )
        .reset_index(
            name="rows"
        )
    )

    print(
        method_display.to_string(
            index=False
        )
    )
    print()

    print("TOP SIMPLE PROTECTION COMPONENTS")
    if protections.empty:
        print(
            "No simple protection claims met the automatic rules."
        )
    else:
        protection_display = (
            protections.sort_values(
                "expected_transferred_value_score",
                ascending=False,
            )
            .head(
                20
            )[
                [
                    "claim_id",
                    "originating_team",
                    "candidate_beneficiary_team",
                    "draft_year",
                    "round_number",
                    "protection_type",
                    "protection_start_pick",
                    "protection_end_pick",
                    "conveyance_probability",
                    "expected_conveyed_pick",
                    "expected_transferred_value_score",
                    "expected_retained_value_score",
                    "valuation_status",
                ]
            ]
            .copy()
        )

        for column in [
            "conveyance_probability",
        ]:
            protection_display[
                column
            ] = (
                protection_display[
                    column
                ]
                * 100.0
            )

        numeric_columns = [
            column
            for column in protection_display.columns
            if column
            not in {
                "claim_id",
                "originating_team",
                "candidate_beneficiary_team",
                "protection_type",
                "valuation_status",
            }
        ]

        for column in numeric_columns:
            protection_display[
                column
            ] = (
                pd.to_numeric(
                    protection_display[
                        column
                    ],
                    errors="coerce",
                )
                .round(
                    2
                )
            )

        print(
            protection_display.to_string(
                index=False
            )
        )

    print()
    print("TOP SIMPLE SWAP OPTIONS")
    if swaps.empty:
        print(
            "No simple swap claims met the automatic rules."
        )
    else:
        swap_display = (
            swaps.sort_values(
                "expected_swap_option_value_score",
                ascending=False,
            )
            .head(
                20
            )[
                [
                    "claim_id",
                    "candidate_beneficiary_team",
                    "candidate_counterparty_team",
                    "draft_year",
                    "round_number",
                    "swap_exercise_probability",
                    "expected_slot_improvement_unconditional",
                    "expected_slot_improvement_when_exercised",
                    "expected_swap_option_value_score",
                ]
            ]
            .copy()
        )

        swap_display[
            "swap_exercise_probability"
        ] = (
            swap_display[
                "swap_exercise_probability"
            ]
            * 100.0
        )

        for column in swap_display.columns:
            if column not in {
                "claim_id",
                "candidate_beneficiary_team",
                "candidate_counterparty_team",
            }:
                swap_display[
                    column
                ] = (
                    pd.to_numeric(
                        swap_display[
                            column
                        ],
                        errors="coerce",
                    )
                    .round(
                        2
                    )
                )

        print(
            swap_display.to_string(
                index=False
            )
        )

    print()
    print("TOP CANDIDATE TEAM PICK-ASSET VALUES")
    team_display = (
        team_summary.head(
            15
        ).copy()
    )

    for column in team_display.columns:
        if (
            column
            not in {
                "candidate_beneficiary_team",
                "summary_scope_note",
            }
        ):
            team_display[
                column
            ] = (
                pd.to_numeric(
                    team_display[
                        column
                    ],
                    errors="coerce",
                )
                .round(
                    2
                )
            )

    print(
        team_display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(ALL_VALUATIONS_PARQUET_PATH)
    print(ALL_VALUATIONS_CSV_PATH)
    print(DIRECT_ASSET_VALUES_PATH)
    print(PROTECTION_VALUATIONS_PATH)
    print(SWAP_VALUATIONS_PATH)
    print(UNRESOLVED_REVIEW_PATH)
    print(TEAM_CANDIDATE_SUMMARY_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()