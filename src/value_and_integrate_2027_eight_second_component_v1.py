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
    "future-pick-2027-eight-second-connected-component-v1-2026-08-04"
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

V9_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v9_cle_min_uta_pool_enriched.parquet"
)

V9_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v9_cle_min_uta_pool_provisional.csv"
)

CORRECTED_GROUP_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_hou_ind_mia_okc_sas_2027_corrected_group_claims_v2.csv"
)

PHI_LAC_DOWNSTREAM_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_hou_ind_mia_okc_sas_2027_phi_lac_downstream_claims_v2.csv"
)

DIAGNOSTIC_METADATA_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_hou_ind_mia_okc_sas_2027_diagnostic_metadata_v2.json"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_source_allocations_v1.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_source_allocations_v1.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_candidate_rights_v1.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_candidate_rights_v1.csv"
)

SELECTION_EVENTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_selection_events_v1.parquet"
)

SELECTION_EVENTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_eight_second_selection_events_v1.csv"
)

V10_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v10_eight_second_enriched.parquet"
)

V10_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v10_eight_second_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_eight_second_existing_baseline_audit_v1.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_eight_second_team_adjustments_v1.csv"
)

V10_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v10_eight_second_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_eight_second_source_reconciliation_v1.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_eight_second_component_reconciliation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_eight_second_component_metadata_v1.json"
)


PRIMARY_GROUP_ID = "OBL_f60ebafc3d7d"
PHI_OUTGOING_CLAIM_ID = "2027_R2_PHI_C1"

SOURCE_ASSETS = {
    "2027_R2_HOU": (2027, 2, "HOU"),
    "2027_R2_IND": (2027, 2, "IND"),
    "2027_R2_MIA": (2027, 2, "MIA"),
    "2027_R2_OKC": (2027, 2, "OKC"),
    "2027_R2_SAS": (2027, 2, "SAS"),
    "2027_R2_PHI": (2027, 2, "PHI"),
    "2027_R2_GSW": (2027, 2, "GSW"),
    "2027_R2_PHX": (2027, 2, "PHX"),
}

PRIMARY_FOUR = [
    "2027_R2_OKC",
    "2027_R2_HOU",
    "2027_R2_IND",
    "2027_R2_MIA",
]

CANDIDATE_TEAMS = [
    "PHI",
    "LAC",
    "NOP",
    "NYK",
    "SAS",
    "MIA",
    "WAS",
]

EXPECTED_PRIMARY_TEXT = [
    "Philadelphia will receive the most favorable",
    "New Orleans will receive the second most favorable",
    "New York will receive the third most favorable",
    "San Antonio will receive the more favorable",
    "Miami will receive the least favorable of the five",
]

EXPECTED_DOWNSTREAM_TEXT = [
    "The L.A. Clippers will receive the second most favorable",
    "Philadelphia",
    "Golden State",
    "Phoenix",
    "Oklahoma City",
    "Houston",
    "Indiana",
    "Miami",
]


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output.columns = [
        str(column).strip().lower().replace(" ", "_")
        for column in output.columns
    ]
    return output


def require_columns(
    frame: pd.DataFrame,
    columns: list[str],
    frame_name: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{frame_name} is missing required columns:\n"
            + "\n".join(missing)
        )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def numeric_value(value: Any) -> float:
    return float(
        pd.to_numeric(
            pd.Series([value]),
            errors="coerce",
        ).iloc[0]
    )


def finite_or_zero(value: Any) -> float:
    number = numeric_value(value)
    return number if np.isfinite(number) else 0.0


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if pd.isna(value):
        return None
    return value


class SimulationBank:
    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"Simulation bank was not found:\n{path}"
            )

        self.archive = np.load(path, allow_pickle=False)
        self.teams = [
            str(value)
            for value in self.archive["team_abbreviations"].tolist()
        ]
        self.team_to_index = {
            team: index
            for index, team in enumerate(self.teams)
        }
        self.simulation_ids = self.archive[
            "simulation_ids"
        ].astype(int)

        required_teams = {
            team
            for _, _, team in SOURCE_ASSETS.values()
        }
        missing = sorted(required_teams - set(self.teams))
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
            raise KeyError(f"Simulation array was not found: {key}")

        return self.archive[key][
            :,
            self.team_to_index[str(team)],
        ].astype(int)

    def close(self) -> None:
        self.archive.close()


class SlotValueLookup:
    def __init__(self, curve: pd.DataFrame) -> None:
        maximum_pick = int(curve["overall_pick"].max())

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

        for row in curve.itertuples(index=False):
            pick = int(row.overall_pick)
            self.value[pick] = float(
                row.historical_pick_value_score
            )
            self.rating[pick] = float(
                row.historical_pick_value_rating_60_99
            )

        if np.isnan(self.value[1:]).any():
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
        V9_VALUATIONS_PATH,
        V9_TEAM_SUMMARY_PATH,
        CORRECTED_GROUP_CLAIMS_PATH,
        PHI_LAC_DOWNSTREAM_PATH,
        DIAGNOSTIC_METADATA_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required eight-pick component input was not found:\n"
                f"{path}"
            )

    curve = normalize_columns(pd.read_parquet(PICK_CURVE_PATH))
    pick_values = normalize_columns(
        pd.read_parquet(PICK_VALUES_PATH)
    )
    claims = normalize_columns(pd.read_parquet(CLAIMS_PATH))
    valuations = normalize_columns(
        pd.read_parquet(V9_VALUATIONS_PATH)
    )
    team_summary = normalize_columns(
        pd.read_csv(V9_TEAM_SUMMARY_PATH)
    )
    group_claims = normalize_columns(
        pd.read_csv(CORRECTED_GROUP_CLAIMS_PATH)
    )
    downstream_claims = normalize_columns(
        pd.read_csv(PHI_LAC_DOWNSTREAM_PATH)
    )

    with DIAGNOSTIC_METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        diagnostic_metadata = json.load(file)

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
        "V9 valuation layer",
    )
    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_cle_min_uta_pool_provisional"
            ),
        ],
        "V9 provisional team summary",
    )
    require_columns(
        group_claims,
        [
            "claim_id",
            "asset_key",
            "full_obligation_text",
        ],
        "Corrected primary group claims",
    )
    require_columns(
        downstream_claims,
        [
            "claim_id",
            "asset_key",
            "full_obligation_text",
        ],
        "Philadelphia-Clippers downstream claims",
    )

    if not bool(
        diagnostic_metadata.get(
            "primary_pool_value_ready",
            False,
        )
    ):
        raise RuntimeError(
            "Corrected diagnostic did not mark the primary pool ready."
        )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        group_claims,
        downstream_claims,
    )


def validate_source_text(
    group_claims: pd.DataFrame,
    downstream_claims: pd.DataFrame,
) -> tuple[str, str]:
    primary_texts = sorted(
        {
            clean_text(value)
            for value in group_claims["full_obligation_text"]
            if clean_text(value)
        },
        key=len,
        reverse=True,
    )
    if not primary_texts:
        raise ValueError("Primary pool source text is missing.")

    primary_text = primary_texts[0]
    missing_primary = [
        fragment
        for fragment in EXPECTED_PRIMARY_TEXT
        if fragment.lower() not in primary_text.lower()
    ]
    if missing_primary:
        raise ValueError(
            "Primary pool text is missing expected clauses:\n"
            + "\n".join(missing_primary)
        )

    phi_lac = downstream_claims.loc[
        downstream_claims["claim_id"]
        .astype(str)
        .eq(PHI_OUTGOING_CLAIM_ID)
    ]
    if len(phi_lac) != 1:
        raise ValueError(
            "Expected exactly one Philadelphia-to-Clippers claim "
            f"{PHI_OUTGOING_CLAIM_ID}; found {len(phi_lac)}."
        )

    downstream_text = clean_text(
        phi_lac.iloc[0]["full_obligation_text"]
    )
    missing_downstream = [
        fragment
        for fragment in EXPECTED_DOWNSTREAM_TEXT
        if fragment.lower() not in downstream_text.lower()
    ]
    if missing_downstream:
        raise ValueError(
            "Philadelphia-to-Clippers text is missing expected clauses:\n"
            + "\n".join(missing_downstream)
        )

    return primary_text, downstream_text


def build_discount_lookup(
    pick_values: pd.DataFrame,
) -> dict[str, float]:
    output: dict[str, float] = {}

    for asset_key, (
        draft_year,
        round_number,
        team,
    ) in SOURCE_ASSETS.items():
        match = pick_values.loc[
            pd.to_numeric(
                pick_values["draft_year"],
                errors="coerce",
            ).eq(draft_year)
            & pd.to_numeric(
                pick_values["round_number"],
                errors="coerce",
            ).eq(round_number)
            & pick_values["originating_team"]
            .astype(str)
            .eq(team)
        ]

        if len(match) != 1:
            raise ValueError(
                f"Expected one pick-value row for {asset_key}; "
                f"found {len(match)}."
            )

        output[asset_key] = numeric_value(
            match.iloc[0]["time_discount_factor"]
        )

    unique_discounts = {
        round(value, 12)
        for value in output.values()
    }
    if len(unique_discounts) != 1:
        raise ValueError(
            "The eight 2027 second-round sources do not share "
            "one time-discount factor."
        )

    return output


def unconditional_value_lookup(
    pick_values: pd.DataFrame,
) -> dict[str, float]:
    output: dict[str, float] = {}

    for asset_key, (
        draft_year,
        round_number,
        team,
    ) in SOURCE_ASSETS.items():
        match = pick_values.loc[
            pd.to_numeric(
                pick_values["draft_year"],
                errors="coerce",
            ).eq(draft_year)
            & pd.to_numeric(
                pick_values["round_number"],
                errors="coerce",
            ).eq(round_number)
            & pick_values["originating_team"]
            .astype(str)
            .eq(team)
        ]

        if len(match) != 1:
            raise ValueError(
                f"Missing unconditional value for {asset_key}."
            )

        output[asset_key] = numeric_value(
            match.iloc[0][
                "time_discounted_pick_value_score"
            ]
        )

    return output


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

    simulation_count = len(bank.simulation_ids)
    if any(
        len(values) != simulation_count
        for values in slots.values()
    ):
        raise ValueError(
            "Eight-pick simulation arrays do not align."
        )

    discounted_values = {
        asset_key: (
            lookup.value[asset_slots]
            * discounts[asset_key]
        )
        for asset_key, asset_slots in slots.items()
    }

    owners = {
        asset_key: np.full(
            simulation_count,
            "",
            dtype="U3",
        )
        for asset_key in SOURCE_ASSETS
    }

    event_rows: list[dict[str, Any]] = []

    for simulation_index in range(simulation_count):
        primary_order = sorted(
            PRIMARY_FOUR,
            key=lambda asset_key: int(
                slots[asset_key][simulation_index]
            ),
        )

        rank1 = primary_order[0]
        rank2 = primary_order[1]
        rank3 = primary_order[2]
        rank4 = primary_order[3]

        owners[rank2][simulation_index] = "NOP"
        owners[rank3][simulation_index] = "NYK"

        sas_asset = "2027_R2_SAS"

        rank4_slot = int(
            slots[rank4][simulation_index]
        )
        sas_slot = int(
            slots[sas_asset][simulation_index]
        )

        if rank4_slot < sas_slot:
            owners[rank4][simulation_index] = "SAS"
            owners[sas_asset][simulation_index] = "MIA"
            sas_selected_source = rank4
            mia_selected_source = sas_asset
        else:
            owners[sas_asset][simulation_index] = "SAS"
            owners[rank4][simulation_index] = "MIA"
            sas_selected_source = sas_asset
            mia_selected_source = rank4

        gsw_asset = "2027_R2_GSW"
        phx_asset = "2027_R2_PHX"

        if (
            int(slots[gsw_asset][simulation_index])
            < int(slots[phx_asset][simulation_index])
        ):
            gsw_phx_better = gsw_asset
            gsw_phx_worse = phx_asset
        else:
            gsw_phx_better = phx_asset
            gsw_phx_worse = gsw_asset

        owners[gsw_phx_worse][simulation_index] = "WAS"

        phi_candidates = [
            "2027_R2_PHI",
            gsw_phx_better,
            rank1,
        ]

        phi_candidate_order = sorted(
            phi_candidates,
            key=lambda asset_key: int(
                slots[asset_key][simulation_index]
            ),
        )

        best = phi_candidate_order[0]
        median = phi_candidate_order[1]
        worst = phi_candidate_order[2]

        owners[best][simulation_index] = "PHI"
        owners[median][simulation_index] = "LAC"
        owners[worst][simulation_index] = "PHI"

        event_rows.extend(
            [
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "primary_rank_1",
                    "source_asset_key": rank1,
                    "candidate_team": (
                        owners[rank1][simulation_index]
                    ),
                    "overall_pick": int(
                        slots[rank1][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "primary_rank_2",
                    "source_asset_key": rank2,
                    "candidate_team": "NOP",
                    "overall_pick": int(
                        slots[rank2][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "primary_rank_3",
                    "source_asset_key": rank3,
                    "candidate_team": "NYK",
                    "overall_pick": int(
                        slots[rank3][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "san_antonio_comparison_winner",
                    "source_asset_key": sas_selected_source,
                    "candidate_team": "SAS",
                    "overall_pick": int(
                        slots[
                            sas_selected_source
                        ][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "miami_least_of_five",
                    "source_asset_key": mia_selected_source,
                    "candidate_team": "MIA",
                    "overall_pick": int(
                        slots[
                            mia_selected_source
                        ][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "washington_gsw_phx_worse",
                    "source_asset_key": gsw_phx_worse,
                    "candidate_team": "WAS",
                    "overall_pick": int(
                        slots[
                            gsw_phx_worse
                        ][simulation_index]
                    ),
                },
                {
                    "simulation_id": int(
                        bank.simulation_ids[simulation_index]
                    ),
                    "event_type": "clippers_second_best_phi_candidates",
                    "source_asset_key": median,
                    "candidate_team": "LAC",
                    "overall_pick": int(
                        slots[median][simulation_index]
                    ),
                },
            ]
        )

    for asset_key, owner_array in owners.items():
        if np.any(owner_array == ""):
            raise RuntimeError(
                "At least one simulation lacks a final owner for "
                f"{asset_key}."
            )

    allocation_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []

    for asset_key, owner_array in owners.items():
        allocated_sum = 0.0

        for candidate_team in sorted(
            set(owner_array.tolist())
        ):
            condition = owner_array == candidate_team

            expected_value = float(
                np.mean(
                    np.where(
                        condition,
                        discounted_values[asset_key],
                        0.0,
                    )
                )
            )

            allocated_sum += expected_value

            allocation_rows.append(
                {
                    "source_asset_key": asset_key,
                    "source_team": SOURCE_ASSETS[
                        asset_key
                    ][2],
                    "candidate_team": candidate_team,
                    "allocation_probability": float(
                        np.mean(condition)
                    ),
                    "expected_allocated_value_score": (
                        expected_value
                    ),
                    "expected_pick_when_allocated": float(
                        np.mean(
                            slots[asset_key][condition]
                        )
                    ),
                    "simulation_count": simulation_count,
                }
            )

        unconditional_value = float(
            np.mean(discounted_values[asset_key])
        )

        reconciliation_rows.append(
            {
                "source_asset_key": asset_key,
                "unconditional_asset_value_score": (
                    unconditional_value
                ),
                "allocated_value_sum": allocated_sum,
                "allocation_value_difference": (
                    allocated_sum - unconditional_value
                ),
                "allocation_probability_sum": float(
                    sum(
                        np.mean(owner_array == team)
                        for team in set(
                            owner_array.tolist()
                        )
                    )
                ),
                "allocation_reconciliation_passed": (
                    abs(
                        allocated_sum - unconditional_value
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
        )["source_asset_key"]
        .apply(
            lambda series: "|".join(
                sorted(set(series))
            )
        )
        .rename("source_assets")
        .reset_index()
    )

    candidate_rights = candidate_rights.merge(
        source_lists,
        how="left",
        on="candidate_team",
        validate="one_to_one",
    )

    right_descriptions = {
        "PHI": (
            "retains the most and least favorable of its three "
            "post-pool candidate picks"
        ),
        "LAC": (
            "second-most favorable of PHI own, GSW/PHX better, "
            "and OKC/HOU/IND/MIA best"
        ),
        "NOP": (
            "second-most favorable of OKC/HOU/IND/MIA"
        ),
        "NYK": (
            "third-most favorable of OKC/HOU/IND/MIA"
        ),
        "SAS": (
            "more favorable of SAS own and the fourth-ranked "
            "OKC/HOU/IND/MIA pick"
        ),
        "MIA": (
            "least favorable of the five-pick SAS comparison"
        ),
        "WAS": (
            "less favorable of GSW and PHX"
        ),
    }

    candidate_rights[
        "right_description"
    ] = candidate_rights[
        "candidate_team"
    ].map(right_descriptions)

    raw_events = pd.DataFrame(event_rows)

    event_summary = (
        raw_events.groupby(
            [
                "event_type",
                "candidate_team",
                "source_asset_key",
            ],
            as_index=False,
        )
        .agg(
            event_probability=(
                "simulation_id",
                lambda series: (
                    len(series) / simulation_count
                ),
            ),
            expected_pick_when_event_occurs=(
                "overall_pick",
                "mean",
            ),
        )
    )

    component_reconciliation = pd.DataFrame(
        [
            {
                "joint_simulation_count": simulation_count,
                "source_asset_count": len(SOURCE_ASSETS),
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
                        - 8.0
                    )
                    <= 1e-12
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
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    affected_claims = claims.loc[
        claims["asset_key"]
        .astype(str)
        .isin(SOURCE_ASSETS.keys())
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
        valuations[valuation_columns].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    contribution_rows: list[dict[str, Any]] = []

    for row in audit.itertuples(index=False):
        method = clean_text(
            getattr(row, "valuation_method", "")
        )
        status = clean_text(
            getattr(row, "valuation_status", "")
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

        if method == "single_year_protection_component":
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
                        "claim_id": row.claim_id,
                        "asset_key": row.asset_key,
                        "team": beneficiary,
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
                        "claim_id": row.claim_id,
                        "asset_key": row.asset_key,
                        "team": retaining,
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
            status == "valued_direct_candidate"
            or method == "direct_asset_value"
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
                        "claim_id": row.claim_id,
                        "asset_key": row.asset_key,
                        "team": beneficiary,
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
            method == "simple_two_team_swap_option"
            and beneficiary
            and option_value
        ):
            contribution_rows.append(
                {
                    "claim_id": row.claim_id,
                    "asset_key": row.asset_key,
                    "team": beneficiary,
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

    return audit, contributions


def build_team_adjustments(
    candidate_rights: pd.DataFrame,
    baseline_contributions: pd.DataFrame,
) -> pd.DataFrame:
    new_values = (
        candidate_rights.set_index(
            "candidate_team"
        )["expected_candidate_right_value_score"]
        .to_dict()
    )

    baseline_values = (
        baseline_contributions.groupby(
            "team"
        )["current_baseline_value_score"]
        .sum()
        .to_dict()
        if not baseline_contributions.empty
        else {}
    )

    teams = sorted(
        set(new_values)
        | set(baseline_values)
        | set(CANDIDATE_TEAMS)
    )

    rows = []
    for team in teams:
        new_value = float(new_values.get(team, 0.0))
        baseline = float(baseline_values.get(team, 0.0))

        rows.append(
            {
                "team": team,
                "eight_second_component_right_value_score": (
                    new_value
                ),
                "existing_counted_baseline_value_score": (
                    baseline
                ),
                "net_team_adjustment_value_score": (
                    new_value - baseline
                ),
                "adjustment_scope": (
                    "replace_existing_eight_source_accounting_with_"
                    "connected_component_rights"
                ),
            }
        )

    return pd.DataFrame(rows)


def update_team_summary(
    team_summary: pd.DataFrame,
    adjustments: pd.DataFrame,
) -> pd.DataFrame:
    output = team_summary.copy()

    base_column = (
        "candidate_total_pick_asset_value_score_"
        "after_cle_min_uta_pool_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_eight_second_component"
    ] = pd.to_numeric(
        output[base_column],
        errors="coerce",
    )

    adjustment_lookup = (
        adjustments.set_index(
            "team"
        )["net_team_adjustment_value_score"]
        .to_dict()
    )

    output[
        "eight_second_component_adjustment_value_score"
    ] = (
        output["candidate_beneficiary_team"]
        .astype(str)
        .map(adjustment_lookup)
        .fillna(0.0)
    )

    output[
        "candidate_total_pick_asset_value_score_after_eight_second_component_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_eight_second_component"
        ]
        + output[
            "eight_second_component_adjustment_value_score"
        ]
    )

    output[
        "eight_second_component_status"
    ] = (
        "fully_integrated_connected_eight_pick_component"
    )

    output[
        "eight_second_component_scope_note"
    ] = (
        "Eight 2027 second-round source picks are allocated jointly "
        "across Philadelphia, the Clippers, New Orleans, New York, "
        "San Antonio, Miami, and Washington. Existing direct source "
        "values are removed before the connected rights are inserted."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_eight_second_component_provisional"
        ),
        ascending=False,
    ).reset_index(drop=True)


def enrich_valuations(
    valuations: pd.DataFrame,
    claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    defaults = {
        "eight_second_component_modeled_flag": False,
        "eight_second_source_asset_value_score": np.nan,
        "eight_second_candidate_allocations_json": "",
    }

    for column, default in defaults.items():
        if column not in output.columns:
            output[column] = default

    affected_claims = claims.loc[
        claims["asset_key"]
        .astype(str)
        .isin(SOURCE_ASSETS.keys())
    ][["claim_id", "asset_key"]].copy()

    claim_to_asset = (
        affected_claims.set_index(
            "claim_id"
        )["asset_key"]
        .to_dict()
    )

    for claim_id, asset_key in claim_to_asset.items():
        mask = (
            output["claim_id"]
            .astype(str)
            .eq(str(claim_id))
        )

        if int(mask.sum()) != 1:
            raise ValueError(
                f"Expected one valuation row for {claim_id}."
            )

        source_rows = source_allocations.loc[
            source_allocations[
                "source_asset_key"
            ].eq(asset_key)
        ]

        allocation_json = json.dumps(
            {
                str(row.candidate_team): float(
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
            "joint_eight_second_connected_component_source_allocation"
        )
        output.loc[
            mask,
            "valuation_status",
        ] = "valued_source_asset_fully_allocated"
        output.loc[
            mask,
            "candidate_beneficiary_team",
        ] = ""
        output.loc[
            mask,
            "eight_second_component_modeled_flag",
        ] = True
        output.loc[
            mask,
            "eight_second_source_asset_value_score",
        ] = source_value
        output.loc[
            mask,
            "eight_second_candidate_allocations_json",
        ] = allocation_json

        if (
            "expected_total_candidate_asset_value_score"
            in output.columns
        ):
            output.loc[
                mask,
                "expected_total_candidate_asset_value_score",
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
                "This physical pick is fully allocated through the "
                "joint eight-source 2027 second-round connected "
                "component. Candidate rights are stored separately, "
                "and claim-level candidate totals are blank to prevent "
                "duplicate aggregation."
            )

    return output


def main() -> None:
    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("2027 EIGHT-SECOND CONNECTED COMPONENT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        group_claims,
        downstream_claims,
    ) = load_inputs()

    primary_text, downstream_text = validate_source_text(
        group_claims=group_claims,
        downstream_claims=downstream_claims,
    )

    discounts = build_discount_lookup(pick_values)
    unconditional_values = unconditional_value_lookup(
        pick_values
    )

    bank = SimulationBank(SIMULATION_BANK_PATH)
    lookup = SlotValueLookup(curve)

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
            "At least one physical source asset failed reconciliation."
        )

    if not bool(
        component_reconciliation.iloc[
            0
        ]["component_reconciliation_passed"]
    ):
        raise RuntimeError(
            "Eight-pick component reconciliation failed."
        )

    for asset_key, expected_value in unconditional_values.items():
        actual = float(
            source_allocations.loc[
                source_allocations[
                    "source_asset_key"
                ].eq(asset_key),
                "expected_allocated_value_score",
            ].sum()
        )
        if abs(actual - expected_value) > 1e-8:
            raise RuntimeError(
                f"Allocated value for {asset_key} does not match "
                "the V3 originating-team value."
            )

    baseline_audit, baseline_contributions = (
        build_baseline_audit(
            claims=claims,
            valuations=valuations,
        )
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
    total_baseline = (
        float(
            baseline_contributions[
                "current_baseline_value_score"
            ].sum()
        )
        if not baseline_contributions.empty
        else 0.0
    )
    total_adjustment = float(
        adjustments[
            "net_team_adjustment_value_score"
        ].sum()
    )

    if abs(total_source_value - total_candidate_value) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal source value."
        )

    if abs(
        total_adjustment
        - (total_source_value - total_baseline)
    ) > 1e-8:
        raise RuntimeError(
            "Team adjustments do not reconcile to source value "
            "minus the existing baseline."
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
        SELECTION_EVENTS_PARQUET_PATH,
        index=False,
    )
    event_summary.to_csv(
        SELECTION_EVENTS_CSV_PATH,
        index=False,
    )
    enriched_valuations.to_parquet(
        V10_VALUATIONS_PARQUET_PATH,
        index=False,
    )
    enriched_valuations.to_csv(
        V10_VALUATIONS_CSV_PATH,
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
        V10_TEAM_SUMMARY_PATH,
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

    component = component_reconciliation.iloc[0]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_assets_integrated": len(SOURCE_ASSETS),
        "source_allocation_rows": len(source_allocations),
        "candidate_rights_created": len(candidate_rights),
        "joint_simulations": int(
            component["joint_simulation_count"]
        ),
        "total_source_asset_value_score": total_source_value,
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
        "component_reconciliation_passed": bool(
            component["component_reconciliation_passed"]
        ),
        "primary_source_text": primary_text,
        "downstream_source_text": downstream_text,
        "accounting_policy": [
            (
                "Every one of the eight physical second-round picks "
                "is assigned to exactly one candidate team in every "
                "simulation."
            ),
            (
                "The best four-team pool pick enters Philadelphia's "
                "three-candidate outgoing comparison."
            ),
            (
                "Philadelphia retains the best and worst of its three "
                "candidate picks after the Clippers receive the median."
            ),
            (
                "The worse Golden State-Phoenix pick goes to Washington."
            ),
            (
                "Existing valued source assets are removed before the "
                "connected candidate rights are inserted."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATIONS_PARQUET_PATH
            ),
            "candidate_rights": str(
                CANDIDATE_RIGHTS_PARQUET_PATH
            ),
            "selection_events": str(
                SELECTION_EVENTS_PARQUET_PATH
            ),
            "v10_valuation_layer": str(
                V10_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v10_team_summary": str(
                V10_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print("=" * 80)
    print("EIGHT-SECOND COMPONENT FULLY INTEGRATED")
    print("=" * 80)
    print(
        f"Joint simulations: "
        f"{int(component['joint_simulation_count']):,}"
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
        f"Total source-asset value: "
        f"{total_source_value:.4f}"
    )
    print(
        f"Total candidate-right value: "
        f"{total_candidate_value:.4f}"
    )
    print(
        f"Existing counted baseline removed: "
        f"{total_baseline:.4f}"
    )
    print(
        f"Net team-value adjustment: "
        f"{total_adjustment:.4f}"
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

    print("CANDIDATE RIGHTS")
    rights_display = candidate_rights.copy()

    for column in [
        "expected_candidate_right_value_score",
        "expected_pick_count",
    ]:
        rights_display[column] = pd.to_numeric(
            rights_display[column],
            errors="coerce",
        ).round(4)

    print(rights_display.to_string(index=False))
    print()

    print("TEAM ADJUSTMENTS")
    adjustment_display = adjustments.copy()

    for column in [
        "eight_second_component_right_value_score",
        "existing_counted_baseline_value_score",
        "net_team_adjustment_value_score",
    ]:
        adjustment_display[column] = pd.to_numeric(
            adjustment_display[column],
            errors="coerce",
        ).round(4)

    print(adjustment_display.to_string(index=False))
    print()

    print("SOURCE-ASSET RECONCILIATION")
    reconciliation_display = source_reconciliation.copy()

    for column in [
        "unconditional_asset_value_score",
        "allocated_value_sum",
        "allocation_value_difference",
        "allocation_probability_sum",
    ]:
        reconciliation_display[column] = pd.to_numeric(
            reconciliation_display[column],
            errors="coerce",
        ).round(8)

    print(reconciliation_display.to_string(index=False))
    print()

    print("SELECTION EVENT SUMMARY")
    event_display = event_summary.copy()
    event_display[
        "event_probability"
    ] = (
        pd.to_numeric(
            event_display["event_probability"],
            errors="coerce",
        )
        * 100.0
    ).round(2)
    event_display[
        "expected_pick_when_event_occurs"
    ] = pd.to_numeric(
        event_display[
            "expected_pick_when_event_occurs"
        ],
        errors="coerce",
    ).round(4)

    print(event_display.to_string(index=False))
    print()

    print("SAVED FILES")
    print(SOURCE_ALLOCATIONS_PARQUET_PATH)
    print(SOURCE_ALLOCATIONS_CSV_PATH)
    print(CANDIDATE_RIGHTS_PARQUET_PATH)
    print(CANDIDATE_RIGHTS_CSV_PATH)
    print(SELECTION_EVENTS_PARQUET_PATH)
    print(SELECTION_EVENTS_CSV_PATH)
    print(V10_VALUATIONS_PARQUET_PATH)
    print(V10_VALUATIONS_CSV_PATH)
    print(BASELINE_AUDIT_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V10_TEAM_SUMMARY_PATH)
    print(SOURCE_RECONCILIATION_PATH)
    print(COMPONENT_RECONCILIATION_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()