from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-2028-twelve-asset-super-component-v2-baseline-corrected-2026-08-04"
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

V10_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v10_eight_second_enriched.parquet"
)

V10_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v10_eight_second_provisional.csv"
)

GROUP_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2028_lac_phi_group_claims_v1.csv"
)

CONNECTED_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2028_lac_phi_connected_claims_v2.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_source_allocations_v2.parquet"
)

SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_source_allocations_v2.csv"
)

CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_candidate_rights_v2.parquet"
)

CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_candidate_rights_v2.csv"
)

EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_event_summary_v2.parquet"
)

EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2028_twelve_asset_event_summary_v2.csv"
)

V11_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v11_twelve_asset_enriched.parquet"
)

V11_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v11_twelve_asset_enriched.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_existing_baseline_audit_v2.csv"
)

TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_team_adjustments_v2.csv"
)

V11_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v11_twelve_asset_provisional.csv"
)

SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_source_reconciliation_v2.csv"
)

COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_component_reconciliation_v2.csv"
)

SCENARIO_CHECKS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_scenario_checks_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_twelve_asset_component_metadata_v2.json"
)


SOURCE_ASSETS = {
    "2028_R1_BOS": (2028, 1, "BOS"),
    "2028_R1_SAS": (2028, 1, "SAS"),
    "2028_R1_LAC": (2028, 1, "LAC"),
    "2028_R1_PHI": (2028, 1, "PHI"),
    "2028_R1_BKN": (2028, 1, "BKN"),
    "2028_R1_PHX": (2028, 1, "PHX"),
    "2028_R1_NYK": (2028, 1, "NYK"),
    "2028_R1_WAS": (2028, 1, "WAS"),
    "2028_R1_MIL": (2028, 1, "MIL"),
    "2028_R1_POR": (2028, 1, "POR"),
    "2028_R2_BOS": (2028, 2, "BOS"),
    "2028_R2_PHI": (2028, 2, "PHI"),
}

FIRST_ROUND_POOL_ASSETS = {
    asset_key
    for asset_key, (_, round_number, _) in SOURCE_ASSETS.items()
    if round_number == 1
}

SECOND_ROUND_FALLBACK_ASSETS = {
    "2028_R2_BOS",
    "2028_R2_PHI",
}

CANDIDATE_TEAMS = {
    "BOS",
    "SAS",
    "PHI",
    "BKN",
    "NYK",
    "PHX",
    "WAS",
    "MIL",
    "POR",
}

PRIMARY_GROUP_ID = "OBL_b3d949dfe6a8"

REQUIRED_CLAIM_IDS = {
    "2028_R1_BOS_C1",
    "2028_R1_LAC_C1",
    "2028_R1_LAC_C2",
    "2028_R1_PHI_C1",
    "2028_R1_PHI_C2",
    "2028_R1_NYK_C1",
    "2028_R1_PHX_C1",
    "2028_R1_MIL_C1",
}

EXPECTED_TEXT_FRAGMENTS = {
    "2028_R1_BOS_C1": [
        "San Antonio has the right to swap",
        "Boston's 2028 1st round pick protected for selection 1",
        "Boston will instead convey its 2028 2nd round pick",
        "protected for selections 46-60",
    ],
    "2028_R1_LAC_C1": [
        "Clippers' 2028 1st round pick to Boston protected for selections 1-16",
        "less favorable of its 2028 1st round pick and San Antonio's 2028 1st round pick",
        "more favorable of the L.A. Clippers' pick and Philadelphia's 2028 1st round pick",
        "protected for selections 9-30",
    ],
    "2028_R1_PHI_C2": [
        "Philadelphia's 2028 1st round pick to Brooklyn protected for selections 1-8",
        "Philadelphia will instead convey its 2028 2nd round pick to Brooklyn",
    ],
    "2028_R1_NYK_C1": [
        "Brooklyn will receive the most and third most favorable of the four",
        "in all other scenarios, Brooklyn will receive the most / two most favorable",
        "New York will receive the least favorable",
        "Washington will receive the more favorable",
        "Phoenix will receive the less favorable",
    ],
    "2028_R1_MIL_C1": [
        "Portland will receive the more favorable of its 2028 1st round pick and Milwaukee's 2028 1st round pick",
        "Washington will receive the more favorable",
        "Milwaukee will receive the less favorable",
    ],
}


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
            for index, team in enumerate(self.teams)
        }

        self.simulation_ids = self.archive[
            "simulation_ids"
        ].astype(int)

        required_teams = {
            team
            for _, _, team in SOURCE_ASSETS.values()
        }

        missing = sorted(
            required_teams - set(self.teams)
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
    def __init__(self, curve: pd.DataFrame) -> None:
        maximum_pick = int(
            curve["overall_pick"].max()
        )

        self.value = np.full(
            maximum_pick + 1,
            np.nan,
            dtype=float,
        )

        for row in curve.itertuples(index=False):
            self.value[
                int(row.overall_pick)
            ] = float(
                row.historical_pick_value_score
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
        V10_VALUATIONS_PATH,
        V10_TEAM_SUMMARY_PATH,
        GROUP_CLAIMS_PATH,
        CONNECTED_CLAIMS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required twelve-asset component input was not found:\n"
                f"{path}"
            )

    curve = normalize_columns(
        pd.read_parquet(PICK_CURVE_PATH)
    )
    pick_values = normalize_columns(
        pd.read_parquet(PICK_VALUES_PATH)
    )
    claims = normalize_columns(
        pd.read_parquet(CLAIMS_PATH)
    )
    valuations = normalize_columns(
        pd.read_parquet(V10_VALUATIONS_PATH)
    )
    team_summary = normalize_columns(
        pd.read_csv(V10_TEAM_SUMMARY_PATH)
    )
    group_claims = normalize_columns(
        pd.read_csv(GROUP_CLAIMS_PATH)
    )
    connected_claims = normalize_columns(
        pd.read_csv(CONNECTED_CLAIMS_PATH)
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
        "V10 valuation layer",
    )
    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_eight_second_component_provisional"
            ),
        ],
        "V10 provisional team summary",
    )
    require_columns(
        group_claims,
        [
            "claim_id",
            "asset_key",
        ],
        "LAC-PHI group diagnostic",
    )
    require_columns(
        connected_claims,
        [
            "claim_id",
            "asset_key",
        ],
        "LAC-PHI connected diagnostic",
    )

    return (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        connected_claims,
    )


def validate_claim_texts(
    claims: pd.DataFrame,
) -> dict[str, str]:
    claim_ids = set(
        claims["claim_id"].astype(str)
    )

    missing_claim_ids = sorted(
        REQUIRED_CLAIM_IDS - claim_ids
    )

    if missing_claim_ids:
        raise ValueError(
            "Required controlling claims are missing:\n"
            + "\n".join(missing_claim_ids)
        )

    texts: dict[str, str] = {}

    for claim_id, fragments in EXPECTED_TEXT_FRAGMENTS.items():
        match = claims.loc[
            claims["claim_id"]
            .astype(str)
            .eq(claim_id)
        ]

        if len(match) != 1:
            raise ValueError(
                f"Expected one controlling row for {claim_id}; "
                f"found {len(match)}."
            )

        text = clean_text(
            match.iloc[0]["full_obligation_text"]
        )

        missing_fragments = [
            fragment
            for fragment in fragments
            if fragment.lower() not in text.lower()
        ]

        if missing_fragments:
            raise ValueError(
                f"Controlling text for {claim_id} is missing clauses:\n"
                + "\n".join(missing_fragments)
            )

        texts[claim_id] = text

    return texts


def validate_source_claim_coverage(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    source_claims = claims.loc[
        claims["asset_key"]
        .astype(str)
        .isin(SOURCE_ASSETS.keys())
    ].copy()

    found_assets = set(
        source_claims["asset_key"].astype(str)
    )

    missing_assets = sorted(
        set(SOURCE_ASSETS) - found_assets
    )

    if missing_assets:
        raise ValueError(
            "The claim layer is missing source assets:\n"
            + "\n".join(missing_assets)
        )

    return source_claims


def build_value_lookups(
    pick_values: pd.DataFrame,
) -> tuple[
    dict[str, float],
    dict[str, float],
]:
    discounts: dict[str, float] = {}
    unconditional_values: dict[str, float] = {}

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

        discounts[asset_key] = numeric_value(
            match.iloc[0]["time_discount_factor"]
        )

        unconditional_values[asset_key] = numeric_value(
            match.iloc[0][
                "time_discounted_pick_value_score"
            ]
        )

    return discounts, unconditional_values


def better_asset(
    asset_a: str,
    asset_b: str,
    slots: dict[str, np.ndarray],
    simulation_index: int,
) -> str:
    if int(
        slots[asset_a][simulation_index]
    ) <= int(
        slots[asset_b][simulation_index]
    ):
        return asset_a

    return asset_b


def worse_asset(
    asset_a: str,
    asset_b: str,
    slots: dict[str, np.ndarray],
    simulation_index: int,
) -> str:
    if int(
        slots[asset_a][simulation_index]
    ) >= int(
        slots[asset_b][simulation_index]
    ):
        return asset_a

    return asset_b


def ordered_assets(
    assets: list[str],
    slots: dict[str, np.ndarray],
    simulation_index: int,
) -> list[str]:
    return sorted(
        assets,
        key=lambda asset_key: (
            int(
                slots[asset_key][simulation_index]
            ),
            asset_key,
        ),
    )


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
        len(values) != simulation_count
        for values in slots.values()
    ):
        raise ValueError(
            "Twelve-asset simulation arrays do not align."
        )

    discounted_values = {
        asset_key: (
            lookup.value[asset_slots]
            * discounts[asset_key]
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

    event_counts: Counter[tuple[str, str, str]] = Counter()
    event_pick_sums: defaultdict[
        tuple[str, str, str],
        float
    ] = defaultdict(float)

    scenario_rows: list[dict[str, Any]] = []

    for simulation_index in range(simulation_count):
        owners = {
            asset_key: source_team
            for asset_key, (
                _,
                _,
                source_team,
            ) in SOURCE_ASSETS.items()
        }

        bos_first = "2028_R1_BOS"
        sas_first = "2028_R1_SAS"
        lac_first = "2028_R1_LAC"
        phi_first = "2028_R1_PHI"
        bkn_first = "2028_R1_BKN"
        phx_first = "2028_R1_PHX"
        nyk_first = "2028_R1_NYK"
        was_first = "2028_R1_WAS"
        mil_first = "2028_R1_MIL"
        por_first = "2028_R1_POR"
        bos_second = "2028_R2_BOS"
        phi_second = "2028_R2_PHI"

        # LAC's unprotected transfer initially places its first with PHI.
        owners[lac_first] = "PHI"

        # Stage 1: San Antonio's BOS-SAS swap, with BOS No. 1 protected.
        bos_number_one_protected = (
            int(
                slots[bos_first][simulation_index]
            )
            == 1
        )

        bos_second_fallback_conveyed = False
        bos_sas_swap_exercised = False

        if bos_number_one_protected:
            bos_stake = bos_first

            if int(
                slots[bos_second][simulation_index]
            ) <= 45:
                owners[bos_second] = "SAS"
                bos_second_fallback_conveyed = True
        else:
            if int(
                slots[bos_first][simulation_index]
            ) < int(
                slots[sas_first][simulation_index]
            ):
                owners[bos_first] = "SAS"
                owners[sas_first] = "BOS"
                bos_stake = sas_first
                bos_sas_swap_exercised = True
            else:
                bos_stake = bos_first

        # Stage 2: PHI-BKN protection and PHI second fallback.
        phi_first_conveyed_to_pool = (
            int(
                slots[phi_first][simulation_index]
            )
            >= 9
        )

        if phi_first_conveyed_to_pool:
            owners[phi_first] = "BKN"
        else:
            owners[phi_first] = "PHI"
            owners[phi_second] = "BKN"

        # Stage 3: LAC direct conveyance to BOS or BOS fallback swap.
        lac_direct_to_boston = (
            int(
                slots[lac_first][simulation_index]
            )
            >= 17
        )

        boston_fallback_swap_exercised = False
        boston_fallback_target = ""

        if lac_direct_to_boston:
            owners[lac_first] = "BOS"
        else:
            owners[lac_first] = "PHI"

            available_targets = [lac_first]

            if not phi_first_conveyed_to_pool:
                available_targets.append(phi_first)

            target = ordered_assets(
                available_targets,
                slots,
                simulation_index,
            )[0]

            if int(
                slots[target][simulation_index]
            ) < int(
                slots[bos_stake][simulation_index]
            ):
                if owners[target] != "PHI":
                    raise RuntimeError(
                        "Boston fallback target was not held by PHI."
                    )

                if owners[bos_stake] != "BOS":
                    raise RuntimeError(
                        "Boston fallback stake was not held by BOS."
                    )

                owners[target] = "BOS"
                owners[bos_stake] = "PHI"
                boston_fallback_swap_exercised = True
                boston_fallback_target = target

        # Stage 4: BKN-NYK-PHX-WAS pool.
        special_brooklyn_case = False

        if phi_first_conveyed_to_pool:
            four_assets = [
                phi_first,
                bkn_first,
                phx_first,
                nyk_first,
            ]

            four_order = ordered_assets(
                four_assets,
                slots,
                simulation_index,
            )

            rank_map = {
                asset_key: rank
                for rank, asset_key in enumerate(
                    four_order,
                    start=1,
                )
            }

            special_brooklyn_case = (
                rank_map[phi_first] == 3
                and rank_map[nyk_first] in {1, 2}
            )

            if special_brooklyn_case:
                brooklyn_assets = {
                    four_order[0],
                    phi_first,
                }
            else:
                brooklyn_assets = {
                    four_order[0],
                    four_order[1],
                }

            nyk_asset = max(
                [
                    nyk_first,
                    bkn_first,
                    phx_first,
                ],
                key=lambda asset_key: (
                    int(
                        slots[asset_key][simulation_index]
                    ),
                    asset_key,
                ),
            )

            if nyk_asset in brooklyn_assets:
                raise RuntimeError(
                    "BKN and NYK allocations overlap in the "
                    "PHI-conveyed branch."
                )

            residual_candidates = (
                set(four_assets)
                - brooklyn_assets
                - {nyk_asset}
            )

            if len(residual_candidates) != 1:
                raise RuntimeError(
                    "PHI-conveyed pool did not leave exactly one "
                    "WAS-PHX comparison asset."
                )

            downstream_asset = next(
                iter(residual_candidates)
            )

            for asset_key in brooklyn_assets:
                owners[asset_key] = "BKN"

            owners[nyk_asset] = "NYK"
        else:
            three_assets = [
                bkn_first,
                phx_first,
                nyk_first,
            ]

            three_order = ordered_assets(
                three_assets,
                slots,
                simulation_index,
            )

            brooklyn_asset = three_order[0]

            nyk_is_worst = (
                three_order[-1] == nyk_first
            )

            if nyk_is_worst:
                nyk_asset = nyk_first
            else:
                nyk_asset = three_order[1]

            residual_candidates = (
                set(three_assets)
                - {brooklyn_asset, nyk_asset}
            )

            if len(residual_candidates) != 1:
                raise RuntimeError(
                    "PHI-protected pool did not leave exactly one "
                    "WAS-PHX comparison asset."
                )

            downstream_asset = next(
                iter(residual_candidates)
            )

            owners[brooklyn_asset] = "BKN"
            owners[nyk_asset] = "NYK"

        was_preliminary_asset = better_asset(
            was_first,
            downstream_asset,
            slots,
            simulation_index,
        )

        phoenix_final_asset = worse_asset(
            was_first,
            downstream_asset,
            slots,
            simulation_index,
        )

        owners[phoenix_final_asset] = "PHX"

        # Stage 5: POR-MIL swap and Washington's final comparison.
        portland_asset = better_asset(
            por_first,
            mil_first,
            slots,
            simulation_index,
        )

        milwaukee_comparison_asset = worse_asset(
            por_first,
            mil_first,
            slots,
            simulation_index,
        )

        washington_final_asset = better_asset(
            was_preliminary_asset,
            milwaukee_comparison_asset,
            slots,
            simulation_index,
        )

        milwaukee_final_asset = worse_asset(
            was_preliminary_asset,
            milwaukee_comparison_asset,
            slots,
            simulation_index,
        )

        owners[portland_asset] = "POR"
        owners[washington_final_asset] = "WAS"
        owners[milwaukee_final_asset] = "MIL"

        # The preliminary WAS asset not retained by WAS moves to MIL
        # when Washington upgrades through the POR-MIL comparison.
        if washington_final_asset == milwaukee_comparison_asset:
            owners[was_preliminary_asset] = "MIL"

        # The POR-MIL comparison asset not retained by MIL moves to WAS.
        if milwaukee_final_asset == was_preliminary_asset:
            owners[milwaukee_comparison_asset] = "WAS"

        # Final assignment validation.
        if set(owners) != set(SOURCE_ASSETS):
            raise RuntimeError(
                "Final owner dictionary does not cover all source assets."
            )

        invalid_owners = sorted(
            set(owners.values()) - CANDIDATE_TEAMS
        )

        if invalid_owners:
            raise RuntimeError(
                "Unexpected final candidate teams:\n"
                + "\n".join(invalid_owners)
            )

        for asset_key, candidate_team in owners.items():
            owner_arrays[asset_key][simulation_index] = (
                candidate_team
            )

        events = [
            (
                "bos_number_one_protected",
                "BOS" if bos_number_one_protected else "NOT_BOS",
                bos_first,
            ),
            (
                "bos_sas_swap_exercised",
                "SAS" if bos_sas_swap_exercised else "NO_SWAP",
                bos_first,
            ),
            (
                "bos_second_fallback",
                "SAS" if bos_second_fallback_conveyed else "BOS",
                bos_second,
            ),
            (
                "lac_direct_transfer",
                "BOS" if lac_direct_to_boston else "PHI_CHAIN",
                lac_first,
            ),
            (
                "boston_fallback_swap",
                (
                    "BOS"
                    if boston_fallback_swap_exercised
                    else "NO_SWAP"
                ),
                (
                    boston_fallback_target
                    if boston_fallback_target
                    else bos_stake
                ),
            ),
            (
                "phi_first_brooklyn_availability",
                (
                    "BKN_POOL"
                    if phi_first_conveyed_to_pool
                    else "PHI_PROTECTED"
                ),
                phi_first,
            ),
            (
                "brooklyn_special_case",
                (
                    "SPECIAL"
                    if special_brooklyn_case
                    else "STANDARD"
                ),
                phi_first,
            ),
            (
                "washington_preliminary_source",
                "WAS",
                was_preliminary_asset,
            ),
            (
                "phoenix_final_source",
                "PHX",
                phoenix_final_asset,
            ),
            (
                "portland_final_source",
                "POR",
                portland_asset,
            ),
            (
                "washington_final_source",
                "WAS",
                washington_final_asset,
            ),
            (
                "milwaukee_final_source",
                "MIL",
                milwaukee_final_asset,
            ),
        ]

        for event_type, event_outcome, asset_key in events:
            key = (
                event_type,
                event_outcome,
                asset_key,
            )

            event_counts[key] += 1
            event_pick_sums[key] += float(
                slots[asset_key][simulation_index]
            )

        if simulation_index < 25:
            final_team_counts = Counter(
                owners.values()
            )

            scenario_rows.append(
                {
                    "simulation_id": int(
                        bank.simulation_ids[
                            simulation_index
                        ]
                    ),
                    "bos_pick": int(
                        slots[bos_first][simulation_index]
                    ),
                    "sas_pick": int(
                        slots[sas_first][simulation_index]
                    ),
                    "lac_pick": int(
                        slots[lac_first][simulation_index]
                    ),
                    "phi_pick": int(
                        slots[phi_first][simulation_index]
                    ),
                    "phi_first_conveyed_to_pool": (
                        phi_first_conveyed_to_pool
                    ),
                    "lac_direct_to_boston": (
                        lac_direct_to_boston
                    ),
                    "boston_fallback_swap_exercised": (
                        boston_fallback_swap_exercised
                    ),
                    "boston_fallback_target": (
                        boston_fallback_target
                    ),
                    "brooklyn_special_case": (
                        special_brooklyn_case
                    ),
                    "final_pick_count_sum": int(
                        sum(final_team_counts.values())
                    ),
                    "final_owner_counts_json": json.dumps(
                        dict(
                            sorted(
                                final_team_counts.items()
                            )
                        ),
                        sort_keys=True,
                    ),
                    "final_owners_json": json.dumps(
                        dict(
                            sorted(
                                owners.items()
                            )
                        ),
                        sort_keys=True,
                    ),
                }
            )

    for asset_key, owner_array in owner_arrays.items():
        if np.any(owner_array == ""):
            raise RuntimeError(
                f"At least one {asset_key} simulation lacks an owner."
            )

    allocation_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []

    for asset_key, owner_array in owner_arrays.items():
        allocated_value_sum = 0.0

        for candidate_team in sorted(
            set(owner_array.tolist())
        ):
            condition = (
                owner_array == candidate_team
            )

            expected_value = float(
                np.mean(
                    np.where(
                        condition,
                        discounted_values[asset_key],
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
            np.mean(
                discounted_values[asset_key]
            )
        )

        reconciliation_rows.append(
            {
                "source_asset_key": asset_key,
                "unconditional_asset_value_score": (
                    unconditional_value
                ),
                "allocated_value_sum": (
                    allocated_value_sum
                ),
                "allocation_value_difference": (
                    allocated_value_sum
                    - unconditional_value
                ),
                "allocation_probability_sum": float(
                    sum(
                        np.mean(
                            owner_array == team
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

    event_rows = []

    for (
        event_type,
        event_outcome,
        asset_key,
    ), count in sorted(
        event_counts.items()
    ):
        event_rows.append(
            {
                "event_type": event_type,
                "event_outcome": event_outcome,
                "source_asset_key": asset_key,
                "event_probability": (
                    count / simulation_count
                ),
                "event_count": count,
                "expected_pick_when_event_occurs": (
                    event_pick_sums[
                        (
                            event_type,
                            event_outcome,
                            asset_key,
                        )
                    ]
                    / count
                ),
            }
        )

    event_summary = pd.DataFrame(
        event_rows
    )

    scenario_checks = pd.DataFrame(
        scenario_rows
    )

    component_reconciliation = pd.DataFrame(
        [
            {
                "joint_simulation_count": simulation_count,
                "source_asset_count": len(SOURCE_ASSETS),
                "first_round_source_count": len(
                    FIRST_ROUND_POOL_ASSETS
                ),
                "second_round_fallback_source_count": len(
                    SECOND_ROUND_FALLBACK_ASSETS
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
                        - len(SOURCE_ASSETS)
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
        scenario_checks,
        component_reconciliation,
    )


def build_baseline_audit(
    source_claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
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

    audit = source_claims.merge(
        valuations[
            valuation_columns
        ].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    supported_existing_methods = {
        "",
        "not_automatically_valued",
        "direct_asset_value",
        "single_year_protection_component",
    }

    valued_mask = (
        audit["valuation_status"]
        .fillna("")
        .astype(str)
        .str.startswith("valued_")
    )

    unsupported = audit.loc[
        valued_mask
        & ~audit["valuation_method"]
        .fillna("")
        .astype(str)
        .isin(supported_existing_methods)
    ]

    if not unsupported.empty:
        raise RuntimeError(
            "A source asset is already represented by an unsupported "
            "valued component. Review before integration:\n"
            + unsupported[
                [
                    "claim_id",
                    "asset_key",
                    "valuation_method",
                    "valuation_status",
                ]
            ].to_string(index=False)
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
                        "current_baseline_value_score": transferred,
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
                        "current_baseline_value_score": retained,
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
                        "current_baseline_value_score": total_value,
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
        | CANDIDATE_TEAMS
    )

    rows = []

    for team in teams:
        new_value = float(
            new_values.get(team, 0.0)
        )

        baseline = float(
            baseline_values.get(team, 0.0)
        )

        rows.append(
            {
                "team": team,
                "twelve_asset_component_right_value_score": (
                    new_value
                ),
                "existing_counted_baseline_value_score": (
                    baseline
                ),
                "net_team_adjustment_value_score": (
                    new_value - baseline
                ),
                "adjustment_scope": (
                    "replace_existing_twelve_source_accounting_"
                    "with_joint_component_rights"
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
        "after_eight_second_component_provisional"
    )

    output[
        "candidate_total_pick_asset_value_score_before_twelve_asset_component"
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
        "twelve_asset_component_adjustment_value_score"
    ] = (
        output["candidate_beneficiary_team"]
        .astype(str)
        .map(adjustment_lookup)
        .fillna(0.0)
    )

    output[
        "candidate_total_pick_asset_value_score_after_twelve_asset_component_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_twelve_asset_component"
        ]
        + output[
            "twelve_asset_component_adjustment_value_score"
        ]
    )

    output[
        "twelve_asset_component_status"
    ] = (
        "fully_integrated_2028_first_round_super_component"
    )

    output[
        "twelve_asset_component_scope_note"
    ] = (
        "Ten 2028 first-round picks plus the Boston and Philadelphia "
        "conditional second-round fallbacks are allocated jointly. "
        "The component includes BOS-SAS, LAC-PHI-BOS, PHI-BKN, "
        "BKN-NYK-PHX-WAS, and POR-MIL-WAS rights."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_twelve_asset_component_provisional"
        ),
        ascending=False,
    ).reset_index(drop=True)


def enrich_valuations(
    valuations: pd.DataFrame,
    source_claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    defaults = {
        "twelve_asset_component_modeled_flag": False,
        "twelve_asset_component_primary_claim_flag": False,
        "twelve_asset_source_asset_value_score": np.nan,
        "twelve_asset_candidate_allocations_json": "",
    }

    for column, default in defaults.items():
        if column not in output.columns:
            output[column] = default

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
            ].eq(asset_key)
        ]

        source_value = float(
            source_rows[
                "expected_allocated_value_score"
            ].sum()
        )

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

        primary_claim_id = str(
            claim_group.iloc[0]["claim_id"]
        )

        for row in claim_group.itertuples(index=False):
            claim_id = str(row.claim_id)

            mask = (
                output["claim_id"]
                .astype(str)
                .eq(claim_id)
            )

            if int(mask.sum()) != 1:
                raise ValueError(
                    f"Expected one valuation row for {claim_id}."
                )

            primary_flag = (
                claim_id == primary_claim_id
            )

            output.loc[
                mask,
                "valuation_method",
            ] = (
                "joint_2028_twelve_asset_component_source_allocation"
            )

            output.loc[
                mask,
                "valuation_status",
            ] = (
                "valued_source_asset_fully_allocated"
            )

            output.loc[
                mask,
                "candidate_beneficiary_team",
            ] = ""

            output.loc[
                mask,
                "twelve_asset_component_modeled_flag",
            ] = True

            output.loc[
                mask,
                "twelve_asset_component_primary_claim_flag",
            ] = primary_flag

            output.loc[
                mask,
                "twelve_asset_source_asset_value_score",
            ] = (
                source_value
                if primary_flag
                else np.nan
            )

            output.loc[
                mask,
                "twelve_asset_candidate_allocations_json",
            ] = (
                allocation_json
                if primary_flag
                else ""
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

            if (
                "valuation_scope_note"
                in output.columns
            ):
                output.loc[
                    mask,
                    "valuation_scope_note",
                ] = (
                    "This physical asset is fully allocated through "
                    "the joint 2028 twelve-asset component. "
                    + (
                        "This is the primary claim row carrying the "
                        "source value and allocation JSON."
                        if primary_flag
                        else
                        "This is an alias or overlapping claim row. "
                        "Its source value is stored only on the primary "
                        "claim row to prevent duplication."
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

    print("=" * 80)
    print("2028 TWELVE-ASSET SUPER COMPONENT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        curve,
        pick_values,
        claims,
        valuations,
        team_summary,
        connected_claims,
    ) = load_inputs()

    controlling_texts = validate_claim_texts(
        claims
    )

    source_claims = validate_source_claim_coverage(
        claims
    )

    discounts, unconditional_values = (
        build_value_lookups(
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
            source_reconciliation,
            candidate_rights,
            event_summary,
            scenario_checks,
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
            "At least one source asset failed allocation reconciliation."
        )

    if not bool(
        component_reconciliation.iloc[0][
            "component_reconciliation_passed"
        ]
    ):
        raise RuntimeError(
            "Twelve-asset component reconciliation failed."
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

    (
        baseline_audit,
        baseline_contributions,
    ) = build_baseline_audit(
        source_claims=source_claims,
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
            "minus existing baseline."
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
        V11_VALUATIONS_PARQUET_PATH,
        index=False,
    )
    enriched_valuations.to_csv(
        V11_VALUATIONS_CSV_PATH,
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
        V11_TEAM_SUMMARY_PATH,
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
    scenario_checks.to_csv(
        SCENARIO_CHECKS_PATH,
        index=False,
    )

    component = component_reconciliation.iloc[0]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "primary_group_id": PRIMARY_GROUP_ID,
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
        "controlling_claim_texts": (
            controlling_texts
        ),
        "allocation_policy": [
            (
                "San Antonio may take Boston's first when it is more "
                "favorable, except Boston's No. 1 pick is protected."
            ),
            (
                "When Boston's No. 1 is protected, Boston's second "
                "conveys to San Antonio only at selections 31-45."
            ),
            (
                "The Clippers first conveys directly to Boston at "
                "selections 17-30."
            ),
            (
                "At selections 1-16, Boston may exchange its post-SAS "
                "first for the better available Clippers or protected "
                "Philadelphia first."
            ),
            (
                "Philadelphia's first enters the Brooklyn pool at "
                "selections 9-30; otherwise Philadelphia's second "
                "conveys to Brooklyn."
            ),
            (
                "Brooklyn, New York, Phoenix, Washington, Milwaukee, "
                "and Portland rights are resolved in the nested order "
                "stated in the controlling claims."
            ),
            (
                "Every physical pick is assigned exactly once in every "
                "simulation before any output is written."
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
            "v11_valuation_layer": str(
                V11_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "team_adjustments": str(
                TEAM_ADJUSTMENTS_PATH
            ),
            "v11_team_summary": str(
                V11_TEAM_SUMMARY_PATH
            ),
            "source_reconciliation": str(
                SOURCE_RECONCILIATION_PATH
            ),
            "component_reconciliation": str(
                COMPONENT_RECONCILIATION_PATH
            ),
            "scenario_checks": str(
                SCENARIO_CHECKS_PATH
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
    print("TWELVE-ASSET COMPONENT FULLY INTEGRATED")
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
        f"Source claim rows enriched: "
        f"{len(source_claims):,}"
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

    print(
        rights_display.to_string(index=False)
    )
    print()

    print("TEAM ADJUSTMENTS")
    adjustment_display = adjustments.copy()

    for column in [
        "twelve_asset_component_right_value_score",
        "existing_counted_baseline_value_score",
        "net_team_adjustment_value_score",
    ]:
        adjustment_display[column] = pd.to_numeric(
            adjustment_display[column],
            errors="coerce",
        ).round(4)

    print(
        adjustment_display.to_string(index=False)
    )
    print()

    print("SOURCE-ASSET RECONCILIATION")
    reconciliation_display = (
        source_reconciliation.copy()
    )

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

    print(
        reconciliation_display.to_string(
            index=False
        )
    )
    print()

    print("KEY EVENT SUMMARY")
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
    ).round(2)

    event_display[
        "expected_pick_when_event_occurs"
    ] = pd.to_numeric(
        event_display[
            "expected_pick_when_event_occurs"
        ],
        errors="coerce",
    ).round(4)

    print(
        event_display.to_string(index=False)
    )
    print()

    print("SAVED FILES")
    print(SOURCE_ALLOCATIONS_PARQUET_PATH)
    print(SOURCE_ALLOCATIONS_CSV_PATH)
    print(CANDIDATE_RIGHTS_PARQUET_PATH)
    print(CANDIDATE_RIGHTS_CSV_PATH)
    print(EVENT_SUMMARY_PARQUET_PATH)
    print(EVENT_SUMMARY_CSV_PATH)
    print(V11_VALUATIONS_PARQUET_PATH)
    print(V11_VALUATIONS_CSV_PATH)
    print(BASELINE_AUDIT_PATH)
    print(TEAM_ADJUSTMENTS_PATH)
    print(V11_TEAM_SUMMARY_PATH)
    print(SOURCE_RECONCILIATION_PATH)
    print(COMPONENT_RECONCILIATION_PATH)
    print(SCENARIO_CHECKS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()