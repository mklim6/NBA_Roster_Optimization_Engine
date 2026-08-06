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
    "future-pick-denver-joint-obligation-allocation-v1-2026-08-04"
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

V7_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v7_utah_pool_fully_integrated.parquet"
)

V7_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v7_utah_pool_fully_integrated_provisional.csv"
)

DENVER_CHAIN_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_denver_2027_2029_chain_claims_v1.csv"
)

DENVER_LADDER_STAGES_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_denver_2027_2029_protection_ladder_stages_v1.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_source_asset_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_source_asset_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_candidate_rights_v1.csv"
)

OBLIGATION_EVENTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_obligation_events_v1.parquet"
)

OBLIGATION_EVENTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_denver_joint_obligation_events_v1.csv"
)

V8_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v8_denver_joint_enriched.parquet"
)

V8_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v8_denver_joint_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_joint_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_joint_team_adjustments_v1.csv"
)

V8_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v8_denver_joint_provisional.csv"
)

ASSET_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_joint_source_asset_reconciliation_v1.csv"
)

SWAP_CHAIN_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_swap_chain_audit_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_joint_obligation_metadata_v1.json"
)


SOURCE_ASSETS = {
    "2027_R1_DEN": (
        2027,
        1,
        "DEN",
    ),
    "2027_R1_OKC": (
        2027,
        1,
        "OKC",
    ),
    "2027_R1_LAC": (
        2027,
        1,
        "LAC",
    ),
    "2027_R1_TOR": (
        2027,
        1,
        "TOR",
    ),
    "2028_R1_DEN": (
        2028,
        1,
        "DEN",
    ),
    "2029_R1_DEN": (
        2029,
        1,
        "DEN",
    ),
    "2029_R2_DEN": (
        2029,
        2,
        "DEN",
    ),
}

AFFECTED_TEAMS = [
    "CHA",
    "DEN",
    "LAC",
    "OKC",
    "TOR",
]

PRIMARY_CLAIM_IDS = {
    "FIRST_POTENTIAL": "2027_R1_DEN_C1",
    "SECOND_POTENTIAL": "2029_R1_DEN_C1",
    "DEN_2028_FIRST": "2028_R1_DEN_C1",
    "DEN_2029_SECOND": "2029_R2_DEN_C1",
    "TOR_SWAP_CHAIN": "2027_R1_TOR_C1",
}

EXPECTED_SOURCE_FRAGMENTS = {
    "FIRST_POTENTIAL": [
        "protected for selections 1-5 in 2027",
        "1-5 in 2028",
        "1-5 in 2029",
        "2029 2nd round pick to Oklahoma City",
    ],
    "SECOND_POTENTIAL": [
        "Only if and at least two years after Denver conveys",
        "protected for selections 1-5 in 2029",
        "1-5 in 2030",
    ],
    "DEN_2029_SECOND": [
        "If Denver has conveyed a first potential 1st round pick",
        "2029 2nd round pick to Charlotte",
        "instead Oklahoma City will receive this",
    ],
    "TOR_SWAP_CHAIN": [
        "Oklahoma City has the right to swap",
        "Denver's 2027 1st round pick protected for selections 1-5",
        "L.A. Clippers then have the right to swap",
        "Toronto's 2027 1st round pick",
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

        required_teams = {
            team
            for _, _, team
            in SOURCE_ASSETS.values()
        }

        missing = sorted(
            required_teams
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
    pd.DataFrame,
]:
    for path in [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        V7_VALUATIONS_PATH,
        V7_TEAM_SUMMARY_PATH,
        DENVER_CHAIN_CLAIMS_PATH,
        DENVER_LADDER_STAGES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required Denver-joint input was not found:\n"
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
            V7_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V7_TEAM_SUMMARY_PATH
        )
    )

    chain_claims = normalize_columns(
        pd.read_csv(
            DENVER_CHAIN_CLAIMS_PATH
        )
    )

    ladder_stages = normalize_columns(
        pd.read_csv(
            DENVER_LADDER_STAGES_PATH
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
        claims,
        [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
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
        "V7 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_full_utah_pool_integration_provisional"
            ),
        ],
        "V7 provisional team summary",
    )

    require_columns(
        chain_claims,
        [
            "claim_id",
            "asset_key",
            "transaction_text",
            "full_obligation_text",
        ],
        "Denver chain diagnostic claims",
    )

    require_columns(
        ladder_stages,
        [
            "stage_order",
            "draft_year",
            "round_number",
            "originating_team",
        ],
        "Denver protection ladder",
    )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        chain_claims,
    )


def validate_source_text(
    chain_claims: pd.DataFrame,
) -> None:
    for key, fragments in EXPECTED_SOURCE_FRAGMENTS.items():
        claim_id = PRIMARY_CLAIM_IDS[
            key
        ]

        match = chain_claims.loc[
            chain_claims[
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
                f"Expected one diagnostic claim row for {claim_id}; "
                f"found {len(match)}."
            )

        row = match.iloc[
            0
        ]

        text = clean_text(
            row[
                "full_obligation_text"
            ]
        )

        if not text:
            text = clean_text(
                row[
                    "transaction_text"
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
                "Expected one pick-value row for "
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

    return output


def evaluate_joint_allocations(
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
            "Denver-joint simulation arrays do not align."
        )

    values = {
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

    den_2027_protected = (
        slots[
            "2027_R1_DEN"
        ]
        <= 5
    )

    first_conveys_2027 = (
        ~den_2027_protected
    )

    den_2028_protected = (
        slots[
            "2028_R1_DEN"
        ]
        <= 5
    )

    first_conveys_2028 = (
        den_2027_protected
        & ~den_2028_protected
    )

    den_2029_protected = (
        slots[
            "2029_R1_DEN"
        ]
        <= 5
    )

    first_conveys_2029 = (
        den_2027_protected
        & den_2028_protected
        & ~den_2029_protected
    )

    first_never_conveys = (
        den_2027_protected
        & den_2028_protected
        & den_2029_protected
    )

    first_conveyed_by_2029 = (
        first_conveys_2027
        | first_conveys_2028
        | first_conveys_2029
    )

    second_potential_2029_active = (
        first_conveys_2027
    )

    second_potential_2029_conveys = (
        second_potential_2029_active
        & ~den_2029_protected
    )

    second_potential_rolls_to_2030 = (
        second_potential_2029_active
        & den_2029_protected
    )

    owners = {
        asset_key: np.full(
            simulation_count,
            "",
            dtype="U3",
        )
        for asset_key in SOURCE_ASSETS
    }

    # Denver's 2027 pick is retained when protected. When it conveys,
    # it enters the OKC-LAC-TOR chained swap.
    owners[
        "2027_R1_DEN"
    ][
        den_2027_protected
    ] = "DEN"

    # Resolve the first swap. OKC owns its pick and, when conveyed,
    # Denver's pick. Its right against the Clippers lets OKC preserve
    # the two most favorable available picks, while the Clippers side
    # receives the least favorable of that initial set.
    for simulation_index in range(
        simulation_count
    ):
        initial_sources = [
            "2027_R1_OKC",
            "2027_R1_LAC",
        ]

        if first_conveys_2027[
            simulation_index
        ]:
            initial_sources.append(
                "2027_R1_DEN"
            )

        ordered_sources = sorted(
            initial_sources,
            key=lambda asset_key: (
                int(
                    slots[
                        asset_key
                    ][
                        simulation_index
                    ]
                )
            ),
        )

        if len(
            ordered_sources
        ) == 3:
            okc_sources = ordered_sources[
                :2
            ]

            temporary_lac_source = (
                ordered_sources[
                    2
                ]
            )
        else:
            okc_sources = [
                ordered_sources[
                    0
                ]
            ]

            temporary_lac_source = (
                ordered_sources[
                    1
                ]
            )

        for source_asset in okc_sources:
            owners[
                source_asset
            ][
                simulation_index
            ] = "OKC"

        temporary_lac_slot = int(
            slots[
                temporary_lac_source
            ][
                simulation_index
            ]
        )

        tor_slot = int(
            slots[
                "2027_R1_TOR"
            ][
                simulation_index
            ]
        )

        if temporary_lac_slot < tor_slot:
            owners[
                temporary_lac_source
            ][
                simulation_index
            ] = "LAC"

            owners[
                "2027_R1_TOR"
            ][
                simulation_index
            ] = "TOR"
        else:
            owners[
                temporary_lac_source
            ][
                simulation_index
            ] = "TOR"

            owners[
                "2027_R1_TOR"
            ][
                simulation_index
            ] = "LAC"

    # Denver's 2028 first serves as the second stage only while the
    # first potential obligation remains outstanding.
    owners[
        "2028_R1_DEN"
    ][
        first_conveys_2028
    ] = "OKC"

    owners[
        "2028_R1_DEN"
    ][
        ~first_conveys_2028
    ] = "DEN"

    # Denver's 2029 first is mutually exclusive across two obligations:
    # third stage of the first potential when 2027 and 2028 were protected,
    # or first stage of the second potential when the first conveyed in 2027.
    den_2029_to_okc = (
        first_conveys_2029
        | second_potential_2029_conveys
    )

    owners[
        "2029_R1_DEN"
    ][
        den_2029_to_okc
    ] = "OKC"

    owners[
        "2029_R1_DEN"
    ][
        ~den_2029_to_okc
    ] = "DEN"

    # The 2029 second goes to Charlotte when the first potential first
    # conveyed by 2029. Otherwise it is the terminal fallback to OKC.
    owners[
        "2029_R2_DEN"
    ][
        first_conveyed_by_2029
    ] = "CHA"

    owners[
        "2029_R2_DEN"
    ][
        first_never_conveys
    ] = "OKC"

    for asset_key, owner_array in owners.items():
        if np.any(
            owner_array
            == ""
        ):
            raise RuntimeError(
                "At least one simulation lacks a final owner for "
                f"{asset_key}."
            )

    allocation_rows = []

    reconciliation_rows = []

    for asset_key, owner_array in owners.items():
        source_value_sum = 0.0

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
                        values[
                            asset_key
                        ],
                        0.0,
                    )
                )
            )

            source_value_sum += expected_value

            allocation_rows.append(
                {
                    "source_asset_key": (
                        asset_key
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
                    "expected_pick_when_allocated": float(
                        np.mean(
                            slots[
                                asset_key
                            ][
                                condition
                            ]
                        )
                    ),
                    "simulation_count": (
                        simulation_count
                    ),
                }
            )

        unconditional_value = float(
            np.mean(
                values[
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
                        for candidate_team in set(
                            owner_array.tolist()
                        )
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

    event_rows = [
        {
            "event_name": (
                "first_potential_conveys_2027"
            ),
            "event_probability": float(
                np.mean(
                    first_conveys_2027
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        first_conveys_2027,
                        values[
                            "2027_R1_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "first_potential_conveys_2028"
            ),
            "event_probability": float(
                np.mean(
                    first_conveys_2028
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        first_conveys_2028,
                        values[
                            "2028_R1_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "first_potential_conveys_2029"
            ),
            "event_probability": float(
                np.mean(
                    first_conveys_2029
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        first_conveys_2029,
                        values[
                            "2029_R1_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "first_potential_terminal_2029_second"
            ),
            "event_probability": float(
                np.mean(
                    first_never_conveys
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        first_never_conveys,
                        values[
                            "2029_R2_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "charlotte_receives_2029_denver_second"
            ),
            "event_probability": float(
                np.mean(
                    first_conveyed_by_2029
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        first_conveyed_by_2029,
                        values[
                            "2029_R2_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "second_potential_2029_first_conveys"
            ),
            "event_probability": float(
                np.mean(
                    second_potential_2029_conveys
                )
            ),
            "event_value_score": float(
                np.mean(
                    np.where(
                        second_potential_2029_conveys,
                        values[
                            "2029_R1_DEN"
                        ],
                        0.0,
                    )
                )
            ),
        },
        {
            "event_name": (
                "second_potential_rolls_to_2030"
            ),
            "event_probability": float(
                np.mean(
                    second_potential_rolls_to_2030
                )
            ),
            "event_value_score": np.nan,
        },
    ]

    obligation_events = pd.DataFrame(
        event_rows
    )

    swap_chain_rows = []

    for asset_key in [
        "2027_R1_DEN",
        "2027_R1_OKC",
        "2027_R1_LAC",
        "2027_R1_TOR",
    ]:
        for candidate_team in [
            "DEN",
            "OKC",
            "LAC",
            "TOR",
        ]:
            condition = (
                owners[
                    asset_key
                ]
                == candidate_team
            )

            if not np.any(
                condition
            ):
                continue

            swap_chain_rows.append(
                {
                    "source_asset_key": (
                        asset_key
                    ),
                    "final_candidate_team": (
                        candidate_team
                    ),
                    "allocation_probability": float(
                        np.mean(
                            condition
                        )
                    ),
                    "expected_pick_when_allocated": float(
                        np.mean(
                            slots[
                                asset_key
                            ][
                                condition
                            ]
                        )
                    ),
                    "expected_allocated_value_score": float(
                        np.mean(
                            np.where(
                                condition,
                                values[
                                    asset_key
                                ],
                                0.0,
                            )
                        )
                    ),
                }
            )

    swap_chain_audit = pd.DataFrame(
        swap_chain_rows
    )

    return (
        source_allocations,
        asset_reconciliation,
        candidate_rights,
        obligation_events,
        swap_chain_audit,
    )


def extract_current_baseline(
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
            "expected_total_candidate_asset_value_score",
            "expected_swap_option_value_score",
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

    contribution_rows = []

    for row in audit.itertuples(
        index=False
    ):
        method = clean_text(
            getattr(
                row,
                "valuation_method",
                "",
            )
        )

        status = clean_text(
            getattr(
                row,
                "valuation_status",
                "",
            )
        )

        beneficiary = clean_text(
            getattr(
                row,
                "candidate_beneficiary_team",
                "",
            )
        )

        retaining = clean_text(
            getattr(
                row,
                "candidate_retaining_team",
                "",
            )
        )

        if (
            method
            == "single_year_protection_component"
        ):
            transferred = finite_or_zero(
                getattr(
                    row,
                    "expected_transferred_value_score",
                    np.nan,
                )
            )

            retained = finite_or_zero(
                getattr(
                    row,
                    "expected_retained_value_score",
                    np.nan,
                )
            )

            if beneficiary and transferred:
                contribution_rows.append(
                    {
                        "claim_id": (
                            row.claim_id
                        ),
                        "asset_key": (
                            row.asset_key
                        ),
                        "team": (
                            beneficiary
                        ),
                        "current_baseline_value_score": (
                            transferred
                        ),
                        "baseline_component_type": (
                            "protected_transfer"
                        ),
                    }
                )

            if retaining and retained:
                contribution_rows.append(
                    {
                        "claim_id": (
                            row.claim_id
                        ),
                        "asset_key": (
                            row.asset_key
                        ),
                        "team": (
                            retaining
                        ),
                        "current_baseline_value_score": (
                            retained
                        ),
                        "baseline_component_type": (
                            "protected_retention"
                        ),
                    }
                )

            continue

        if (
            status
            == "valued_direct_candidate"
            or method
            == "direct_asset_value"
        ):
            total_value = finite_or_zero(
                getattr(
                    row,
                    "expected_total_candidate_asset_value_score",
                    np.nan,
                )
            )

            if beneficiary and total_value:
                contribution_rows.append(
                    {
                        "claim_id": (
                            row.claim_id
                        ),
                        "asset_key": (
                            row.asset_key
                        ),
                        "team": (
                            beneficiary
                        ),
                        "current_baseline_value_score": (
                            total_value
                        ),
                        "baseline_component_type": (
                            "direct_asset"
                        ),
                    }
                )

            continue

        option_value = finite_or_zero(
            getattr(
                row,
                "expected_swap_option_value_score",
                np.nan,
            )
        )

        if (
            method
            == "simple_two_team_swap_option"
            and beneficiary
            and option_value
        ):
            contribution_rows.append(
                {
                    "claim_id": (
                        row.claim_id
                    ),
                    "asset_key": (
                        row.asset_key
                    ),
                    "team": (
                        beneficiary
                    ),
                    "current_baseline_value_score": (
                        option_value
                    ),
                    "baseline_component_type": (
                        "simple_swap_option"
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
    new_values = {
        str(
            row.candidate_team
        ): float(
            row.expected_candidate_right_value_score
        )
        for row in candidate_rights.itertuples(
            index=False
        )
    }

    if baseline_contributions.empty:
        baseline_values = {}
    else:
        baseline_values = (
            baseline_contributions.groupby(
                "team"
            )[
                "current_baseline_value_score"
            ]
            .sum()
            .to_dict()
        )

    teams = sorted(
        set(
            new_values
        )
        | set(
            baseline_values
        )
        | set(
            AFFECTED_TEAMS
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
                "joint_denver_right_value_score": (
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
                    "replace_existing_denver_and_2027_swap_chain_accounting"
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
        "after_full_utah_pool_integration_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_denver_joint_integration"
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
        "denver_joint_obligation_adjustment_value_score"
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
        "candidate_total_pick_asset_value_score_after_denver_joint_integration_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_denver_joint_integration"
        ]
        + output[
            "denver_joint_obligation_adjustment_value_score"
        ]
    )

    output[
        "denver_joint_integration_status"
    ] = (
        "physical_2027_2029_assets_allocated_2030_rollover_out_of_horizon"
    )

    output[
        "denver_joint_integration_scope_note"
    ] = (
        "Denver's 2027-2029 first-round obligations, 2029 second-round "
        "conditional ownership, and the 2027 OKC-Clippers-Toronto swap "
        "chain are allocated on aligned simulation rows. A possible 2030 "
        "continuation of the second potential obligation is flagged but "
        "not valued in the current horizon."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_denver_joint_integration_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuations(
    valuations: pd.DataFrame,
    claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
    obligation_events: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    added_defaults = {
        "denver_joint_allocation_modeled_flag": False,
        "denver_joint_source_asset_value_score": np.nan,
        "denver_joint_candidate_allocations_json": "",
        "denver_joint_out_of_horizon_2030_flag": False,
        "denver_joint_out_of_horizon_probability": 0.0,
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

    asset_allocation_json = {}

    for asset_key in SOURCE_ASSETS:
        rows = source_allocations.loc[
            source_allocations[
                "source_asset_key"
            ].eq(
                asset_key
            )
        ]

        asset_allocation_json[
            asset_key
        ] = json.dumps(
            {
                str(
                    row.candidate_team
                ): float(
                    row.expected_allocated_value_score
                )
                for row in rows.itertuples(
                    index=False
                )
            },
            sort_keys=True,
        )

    claim_to_asset = (
        affected_claims.set_index(
            "claim_id"
        )[
            "asset_key"
        ].to_dict()
    )

    affected_mask = output[
        "claim_id"
    ].astype(
        str
    ).isin(
        claim_to_asset
    )

    output.loc[
        affected_mask,
        "denver_joint_allocation_modeled_flag",
    ] = True

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

        rows = source_allocations.loc[
            source_allocations[
                "source_asset_key"
            ].eq(
                asset_key
            )
        ]

        asset_value = float(
            rows[
                "expected_allocated_value_score"
            ].sum()
        )

        output.loc[
            mask,
            "denver_joint_source_asset_value_score",
        ] = asset_value

        output.loc[
            mask,
            "denver_joint_candidate_allocations_json",
        ] = asset_allocation_json[
            asset_key
        ]

        output.loc[
            mask,
            "valuation_method",
        ] = (
            "joint_denver_obligation_source_allocation"
        )

        output.loc[
            mask,
            "valuation_status",
        ] = (
            "valued_source_asset_fully_allocated"
        )

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

    out_of_horizon_match = obligation_events.loc[
        obligation_events[
            "event_name"
        ].eq(
            "second_potential_rolls_to_2030"
        )
    ]

    if len(
        out_of_horizon_match
    ) != 1:
        raise ValueError(
            "Missing second-potential 2030 rollover event."
        )

    out_of_horizon_probability = numeric_value(
        out_of_horizon_match.iloc[
            0
        ][
            "event_probability"
        ]
    )

    second_claim_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        PRIMARY_CLAIM_IDS[
            "SECOND_POTENTIAL"
        ]
    )

    output.loc[
        second_claim_mask,
        "denver_joint_out_of_horizon_2030_flag",
    ] = (
        out_of_horizon_probability
        > 0
    )

    output.loc[
        second_claim_mask,
        "denver_joint_out_of_horizon_probability",
    ] = (
        out_of_horizon_probability
    )

    if (
        "valuation_scope_note"
        in output.columns
    ):
        output.loc[
            affected_mask,
            "valuation_scope_note",
        ] = (
            "Physical source asset value is allocated through the joint "
            "Denver multi-year obligation and 2027 chained-swap model. "
            "Claim-level candidate totals are blank to prevent duplicate "
            "aggregation across overlapping obligations."
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
    print("DENVER JOINT MULTI-YEAR OBLIGATION ALLOCATION")
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
        chain_claims,
    ) = load_inputs()

    validate_source_text(
        chain_claims
    )

    discounts = build_discount_lookup(
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
            asset_reconciliation,
            candidate_rights,
            obligation_events,
            swap_chain_audit,
        ) = evaluate_joint_allocations(
            bank=bank,
            lookup=lookup,
            discounts=discounts,
        )
    finally:
        bank.close()

    if not asset_reconciliation[
        "allocation_reconciliation_passed"
    ].all():
        raise RuntimeError(
            "At least one Denver-joint source asset failed reconciliation."
        )

    (
        baseline_audit,
        baseline_contributions,
    ) = extract_current_baseline(
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
        obligation_events=obligation_events,
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
            "Candidate-right value does not equal source-asset value."
        )

    if abs(
        total_adjustment
        - (
            total_source_value
            - total_baseline
        )
    ) > 1e-8:
        raise RuntimeError(
            "Team adjustments do not reconcile to new rights minus "
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

    obligation_events.to_parquet(
        OBLIGATION_EVENTS_PARQUET_PATH,
        index=False,
    )

    obligation_events.to_csv(
        OBLIGATION_EVENTS_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        V8_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V8_VALUATIONS_CSV_PATH,
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
        V8_TEAM_SUMMARY_PATH,
        index=False,
    )

    asset_reconciliation.to_csv(
        ASSET_RECONCILIATION_PATH,
        index=False,
    )

    swap_chain_audit.to_csv(
        SWAP_CHAIN_AUDIT_PATH,
        index=False,
    )

    event_lookup = (
        obligation_events.set_index(
            "event_name"
        )[
            "event_probability"
        ].to_dict()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
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
        "first_potential_probabilities": {
            "conveys_2027": float(
                event_lookup[
                    "first_potential_conveys_2027"
                ]
            ),
            "conveys_2028": float(
                event_lookup[
                    "first_potential_conveys_2028"
                ]
            ),
            "conveys_2029": float(
                event_lookup[
                    "first_potential_conveys_2029"
                ]
            ),
            "terminal_2029_second": float(
                event_lookup[
                    "first_potential_terminal_2029_second"
                ]
            ),
        },
        "second_potential_2029_probabilities": {
            "conveys_2029_first": float(
                event_lookup[
                    "second_potential_2029_first_conveys"
                ]
            ),
            "rolls_to_2030": float(
                event_lookup[
                    "second_potential_rolls_to_2030"
                ]
            ),
        },
        "all_asset_reconciliations_passed": bool(
            asset_reconciliation[
                "allocation_reconciliation_passed"
            ].all()
        ),
        "accounting_policy": [
            (
                "Every physical source pick is assigned to exactly one "
                "candidate team in every simulation."
            ),
            (
                "Denver's 2028 and 2029 firsts are treated as conditional "
                "stages rather than unconditional Denver assets."
            ),
            (
                "Denver's 2029 first cannot simultaneously satisfy the "
                "first and second potential obligations."
            ),
            (
                "The 2027 OKC-Clippers-Toronto chain is modeled by giving "
                "OKC the most favorable picks permitted by its swap right, "
                "then allowing the Clippers to compare their resulting pick "
                "with Toronto's."
            ),
            (
                "Denver's 2029 second is allocated to Charlotte if the "
                "first potential first conveyed by 2029, otherwise to OKC."
            ),
            (
                "A possible 2030 continuation of the second potential "
                "obligation is reported but not valued in the current bank."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATIONS_PARQUET_PATH
            ),
            "candidate_rights": str(
                CANDIDATE_RIGHTS_PARQUET_PATH
            ),
            "obligation_events": str(
                OBLIGATION_EVENTS_PARQUET_PATH
            ),
            "v8_valuation_layer": str(
                V8_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v8_team_summary": str(
                V8_TEAM_SUMMARY_PATH
            ),
            "asset_reconciliation": str(
                ASSET_RECONCILIATION_PATH
            ),
            "swap_chain_audit": str(
                SWAP_CHAIN_AUDIT_PATH
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
    print("DENVER JOINT OBLIGATION INTEGRATED")
    print("=" * 80)
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
        "All asset reconciliations passed: "
        f"{bool(asset_reconciliation['allocation_reconciliation_passed'].all())}"
    )
    print()

    print("FIRST AND SECOND POTENTIAL EVENTS")
    event_display = obligation_events.copy()

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
        4
    )

    event_display[
        "event_value_score"
    ] = pd.to_numeric(
        event_display[
            "event_value_score"
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

    print("CANDIDATE RIGHTS")
    rights_display = candidate_rights.copy()

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
    adjustment_display = adjustments.copy()

    for column in [
        "joint_denver_right_value_score",
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
    print(SOURCE_ALLOCATIONS_PARQUET_PATH)
    print(SOURCE_ALLOCATIONS_CSV_PATH)
    print(CANDIDATE_RIGHTS_PARQUET_PATH)
    print(CANDIDATE_RIGHTS_CSV_PATH)
    print(OBLIGATION_EVENTS_PARQUET_PATH)
    print(OBLIGATION_EVENTS_CSV_PATH)
    print(V8_VALUATIONS_PARQUET_PATH)
    print(V8_VALUATIONS_CSV_PATH)
    print(BASELINE_AUDIT_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V8_TEAM_SUMMARY_PATH)
    print(ASSET_RECONCILIATION_PATH)
    print(SWAP_CHAIN_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()