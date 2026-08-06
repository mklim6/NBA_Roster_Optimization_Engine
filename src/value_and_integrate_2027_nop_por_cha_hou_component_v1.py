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
    "future-pick-2027-nop-por-cha-hou-protected-two-second-component-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SIMULATION_BANK_PATH = (
    PROCESSED_DIRECTORY
    / "future_draft_pick_simulation_bank_2027_2029_v3_floor_corrected.npz"
)
PICK_CURVE_PATH = (
    PROCESSED_DIRECTORY
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.parquet"
)
PICK_VALUES_PATH = (
    PROCESSED_DIRECTORY
    / "future_originating_team_pick_values_2027_2029_v3_floor_corrected.parquet"
)
CLAIMS_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_obligation_claims_2027_2029_v3_floor_corrected.parquet"
)
V21_VALUATIONS_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v21_sas_sac_okc_cha_enriched.parquet"
)
V21_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v21_sas_sac_okc_cha_provisional.csv"
)
GROUP_DIAGNOSTIC_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_group_claims_v1.csv"
)

SOURCE_ALLOCATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_source_allocations_v1.parquet"
)
SOURCE_ALLOCATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_source_allocations_v1.csv"
)
CANDIDATE_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_candidate_rights_v1.parquet"
)
CANDIDATE_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_candidate_rights_v1.csv"
)
EVENT_SUMMARY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_event_summary_v1.parquet"
)
EVENT_SUMMARY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_event_summary_v1.csv"
)
V22_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v22_nop_por_cha_hou_enriched.parquet"
)
V22_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v22_nop_por_cha_hou_enriched.csv"
)
BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_existing_baseline_audit_v1.csv"
)
TEAM_ADJUSTMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_team_adjustments_v1.csv"
)
V22_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v22_nop_por_cha_hou_provisional.csv"
)
SOURCE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_source_reconciliation_v1.csv"
)
COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_component_reconciliation_v1.csv"
)
EXHAUSTIVE_SLOT_PROOF_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_exhaustive_slot_proof_v1.csv"
)
METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_nop_por_cha_hou_component_metadata_v1.json"
)

SOURCE_ASSETS = {
    "2027_R2_NOP": (2027, 2, "NOP"),
    "2027_R2_POR": (2027, 2, "POR"),
}
CANDIDATE_TEAMS = ("CHA", "POR", "HOU")
TARGET_GROUP_ID = "OBL_bb3eeccd878b"

REQUIRED_COMPONENT_CLAIMS = {
    "2027_R2_NOP_C1",
    "2027_R2_POR_C1",
    "2027_R2_POR_C2",
}
EXPECTED_DIAGNOSTIC_CLAIMS = {
    "2027_R2_GSW_C1",
    "2027_R2_NOP_C1",
    "2027_R2_PHX_C1",
    "2027_R2_POR_C1",
    "2027_R2_POR_C2",
}
UNRELATED_ALREADY_VALUED_CLAIMS = {
    "2027_R2_GSW_C1",
    "2027_R2_PHX_C1",
}
UNRELATED_METHOD = (
    "joint_eight_second_connected_component_source_allocation"
)

EXPECTED_TEXT_FRAGMENTS = {
    "2027_R2_NOP_C1": [
        (
            "Charlotte will receive the more favorable of New Orleans' "
            "2027 2nd round pick and Portland's 2027 2nd round pick"
        ),
        "Portland will receive the less favorable of the two",
        "Portland may convey the pick it receives to Houston",
    ],
    "2027_R2_POR_C1": [
        (
            "Charlotte will receive the more favorable of New Orleans' "
            "2027 2nd round pick and Portland's 2027 2nd round pick"
        ),
        "Portland will receive the less favorable of the two",
        "Portland may convey the pick it receives to Houston",
    ],
    "2027_R2_POR_C2": [
        (
            "Houston will receive the less favorable of Portland's "
            "2027 2nd round pick and New Orleans' 2027 2nd round pick"
        ),
        "if this pick falls outside its protected range of 31-55",
        (
            "if this pick falls within its protected range and is therefore "
            "not conveyed"
        ),
        "Portland's obligation to Houston will be extinguished",
    ],
}

BRANCH_PORTLAND_RETAINS = (
    "WORSE_PICK_31_55_PROTECTED_PORTLAND_RETAINS"
)
BRANCH_HOUSTON_RECEIVES = (
    "WORSE_PICK_56_60_CONVEYED_TO_HOUSTON"
)


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
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(value)).strip()


def normalized_text(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        clean_text(value).lower(),
    ).strip()


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
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
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
        self.simulation_ids = self.archive["simulation_ids"].astype(int)

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
        if team not in self.team_to_index:
            raise KeyError(f"Team was not found in simulation bank: {team}")
        return self.archive[
            key
        ][:, self.team_to_index[team]].astype(int)

    def close(self) -> None:
        self.archive.close()


class SlotValueLookup:
    def __init__(self, curve: pd.DataFrame) -> None:
        maximum_pick = int(curve["overall_pick"].max())
        self.value = np.full(maximum_pick + 1, np.nan, dtype=float)
        for row in curve.itertuples(index=False):
            self.value[int(row.overall_pick)] = float(
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
    required_paths = [
        PICK_CURVE_PATH,
        PICK_VALUES_PATH,
        CLAIMS_PATH,
        V21_VALUATIONS_PATH,
        V21_TEAM_SUMMARY_PATH,
        GROUP_DIAGNOSTIC_PATH,
    ]
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required V22 input was not found:\n"
                f"{path}"
            )

    curve = normalize_columns(pd.read_parquet(PICK_CURVE_PATH))
    pick_values = normalize_columns(pd.read_parquet(PICK_VALUES_PATH))
    claims = normalize_columns(pd.read_parquet(CLAIMS_PATH))
    valuations = normalize_columns(pd.read_parquet(V21_VALUATIONS_PATH))
    team_summary = normalize_columns(pd.read_csv(V21_TEAM_SUMMARY_PATH))
    diagnostic = normalize_columns(pd.read_csv(GROUP_DIAGNOSTIC_PATH))

    require_columns(
        curve,
        ["overall_pick", "historical_pick_value_score"],
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
        ["claim_id", "valuation_method", "valuation_status"],
        "V21 valuation layer",
    )
    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_sas_sac_okc_cha_component_provisional"
            ),
        ],
        "V21 provisional team summary",
    )
    require_columns(
        diagnostic,
        ["claim_id", "asset_key"],
        "NOP-POR-CHA-HOU diagnostic",
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
    valuations: pd.DataFrame,
) -> None:
    claim_ids = set(diagnostic["claim_id"].astype(str))
    if claim_ids != EXPECTED_DIAGNOSTIC_CLAIMS:
        raise ValueError(
            "The diagnostic claim set changed.\nExpected:\n"
            + "\n".join(sorted(EXPECTED_DIAGNOSTIC_CLAIMS))
            + "\nFound:\n"
            + "\n".join(sorted(claim_ids))
        )

    asset_keys = set(diagnostic["asset_key"].astype(str))
    if asset_keys != {
        "2027_R2_GSW",
        "2027_R2_NOP",
        "2027_R2_PHX",
        "2027_R2_POR",
    }:
        raise ValueError(
            "The diagnostic asset set changed."
        )

    unrelated = valuations.loc[
        valuations["claim_id"]
        .astype(str)
        .isin(UNRELATED_ALREADY_VALUED_CLAIMS)
    ].copy()

    if set(unrelated["claim_id"].astype(str)) != (
        UNRELATED_ALREADY_VALUED_CLAIMS
    ):
        raise ValueError(
            "The existing GSW-PHX valuation rows were not found."
        )
    if not unrelated["valuation_method"].fillna("").astype(str).eq(
        UNRELATED_METHOD
    ).all():
        raise ValueError(
            "Golden State or Phoenix is no longer represented by the "
            "existing eight-second component."
        )
    if not unrelated["valuation_status"].fillna("").astype(str).eq(
        "valued_source_asset_fully_allocated"
    ).all():
        raise ValueError(
            "Golden State or Phoenix is no longer fully allocated."
        )


def validate_controlling_text(
    claims: pd.DataFrame,
) -> dict[str, str]:
    output: dict[str, str] = {}
    for claim_id, fragments in EXPECTED_TEXT_FRAGMENTS.items():
        match = claims.loc[
            claims["claim_id"].astype(str).eq(claim_id)
        ]
        if len(match) != 1:
            raise ValueError(
                f"Expected one row for {claim_id}; found {len(match)}."
            )
        text = clean_text(match.iloc[0]["full_obligation_text"])
        normalized = normalized_text(text)
        missing = [
            fragment
            for fragment in fragments
            if normalized_text(fragment) not in normalized
        ]
        if missing:
            raise ValueError(
                f"Controlling claim {claim_id} is missing clauses:\n"
                + "\n".join(missing)
            )
        output[claim_id] = text
    return output


def validate_source_claims(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    source_claims = claims.loc[
        claims["asset_key"].astype(str).isin(SOURCE_ASSETS)
    ].copy()

    if set(source_claims["asset_key"].astype(str)) != set(SOURCE_ASSETS):
        raise ValueError(
            "The physical source asset set changed."
        )
    if set(source_claims["claim_id"].astype(str)) != (
        REQUIRED_COMPONENT_CLAIMS
    ):
        raise ValueError(
            "The physical source claim set changed."
        )

    counts = (
        source_claims.groupby("asset_key")["claim_id"]
        .nunique()
        .to_dict()
    )
    if counts != {
        "2027_R2_NOP": 1,
        "2027_R2_POR": 2,
    }:
        raise ValueError(
            "Expected one NOP claim and two POR claims."
        )

    return source_claims.sort_values(
        ["asset_key", "claim_id"]
    ).reset_index(drop=True)


def build_value_lookups(
    pick_values: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float]]:
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
            & pick_values["originating_team"].astype(str).eq(team)
        ]
        if len(match) != 1:
            raise ValueError(
                f"Expected one V3 value row for {asset_key}; "
                f"found {len(match)}."
            )
        discounts[asset_key] = numeric_value(
            match.iloc[0]["time_discount_factor"]
        )
        unconditional_values[asset_key] = numeric_value(
            match.iloc[0]["time_discounted_pick_value_score"]
        )

    return discounts, unconditional_values


def allocate_by_slots(
    nop_pick: int,
    por_pick: int,
) -> tuple[dict[str, list[str]], str, str, str]:
    if nop_pick == por_pick:
        raise ValueError(
            "Physical second-round picks must occupy distinct slots."
        )

    if nop_pick < por_pick:
        better_asset = "2027_R2_NOP"
        worse_asset = "2027_R2_POR"
        worse_pick = por_pick
    else:
        better_asset = "2027_R2_POR"
        worse_asset = "2027_R2_NOP"
        worse_pick = nop_pick

    if 31 <= worse_pick <= 55:
        branch = BRANCH_PORTLAND_RETAINS
        worse_recipient = "POR"
    elif 56 <= worse_pick <= 60:
        branch = BRANCH_HOUSTON_RECEIVES
        worse_recipient = "HOU"
    else:
        raise ValueError(
            f"Less-favorable pick is outside 31-60: {worse_pick}"
        )

    allocation = {
        "CHA": [better_asset],
        "POR": [worse_asset] if worse_recipient == "POR" else [],
        "HOU": [worse_asset] if worse_recipient == "HOU" else [],
    }

    return allocation, branch, better_asset, worse_asset


def prove_allocation_closure() -> pd.DataFrame:
    rows = []

    for nop_pick in range(31, 61):
        for por_pick in range(31, 61):
            if nop_pick == por_pick:
                continue

            allocation, branch, better_asset, worse_asset = (
                allocate_by_slots(
                    nop_pick=nop_pick,
                    por_pick=por_pick,
                )
            )

            assigned = (
                allocation["CHA"]
                + allocation["POR"]
                + allocation["HOU"]
            )
            worse_pick = max(nop_pick, por_pick)

            protection_logic_passed = bool(
                (
                    branch == BRANCH_PORTLAND_RETAINS
                    and 31 <= worse_pick <= 55
                    and len(allocation["POR"]) == 1
                    and len(allocation["HOU"]) == 0
                )
                or (
                    branch == BRANCH_HOUSTON_RECEIVES
                    and 56 <= worse_pick <= 60
                    and len(allocation["POR"]) == 0
                    and len(allocation["HOU"]) == 1
                )
            )

            closure_passed = bool(
                set(assigned) == set(SOURCE_ASSETS)
                and len(assigned) == len(set(assigned))
                and allocation["CHA"] == [better_asset]
                and protection_logic_passed
            )

            rows.append(
                {
                    "nop_second_pick": nop_pick,
                    "por_second_pick": por_pick,
                    "better_source_asset": better_asset,
                    "worse_source_asset": worse_asset,
                    "worse_overall_pick": worse_pick,
                    "branch": branch,
                    "charlotte_source": allocation["CHA"][0],
                    "portland_source": (
                        allocation["POR"][0]
                        if allocation["POR"]
                        else ""
                    ),
                    "houston_source": (
                        allocation["HOU"][0]
                        if allocation["HOU"]
                        else ""
                    ),
                    "protection_logic_passed": protection_logic_passed,
                    "all_two_sources_assigned_once": closure_passed,
                }
            )

    proof = pd.DataFrame(rows)

    if len(proof) != 870:
        raise RuntimeError(
            "Exhaustive proof did not evaluate all 870 assignments."
        )
    if not proof["all_two_sources_assigned_once"].all():
        raise RuntimeError(
            "At least one exhaustive assignment failed."
        )

    counts = proof["branch"].value_counts().to_dict()
    if counts.get(BRANCH_PORTLAND_RETAINS, 0) != 600:
        raise RuntimeError(
            "Protected Portland branch did not contain 600 assignments."
        )
    if counts.get(BRANCH_HOUSTON_RECEIVES, 0) != 270:
        raise RuntimeError(
            "Houston branch did not contain 270 assignments."
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
    nop_slots = bank.slots(2027, 2, "NOP")
    por_slots = bank.slots(2027, 2, "POR")

    if len(nop_slots) != len(por_slots):
        raise ValueError(
            "NOP and POR simulation arrays do not align."
        )
    if np.any(nop_slots == por_slots):
        raise RuntimeError(
            "Simulation bank assigned duplicate physical slots."
        )

    simulation_count = len(nop_slots)
    slots = {
        "2027_R2_NOP": nop_slots,
        "2027_R2_POR": por_slots,
    }
    discounted_values = {
        asset_key: (
            lookup.value[asset_slots]
            * discounts[asset_key]
        )
        for asset_key, asset_slots in slots.items()
    }

    nop_better = nop_slots < por_slots
    worse_slots = np.maximum(nop_slots, por_slots)
    houston_branch = worse_slots >= 56
    branch_array = np.where(
        houston_branch,
        BRANCH_HOUSTON_RECEIVES,
        BRANCH_PORTLAND_RETAINS,
    )

    worse_recipient = np.where(
        houston_branch,
        "HOU",
        "POR",
    )

    owner_arrays = {
        "2027_R2_NOP": np.where(
            nop_better,
            "CHA",
            worse_recipient,
        ),
        "2027_R2_POR": np.where(
            nop_better,
            worse_recipient,
            "CHA",
        ),
    }

    rank_arrays = {
        "2027_R2_NOP": np.where(
            nop_better,
            "better",
            "worse",
        ),
        "2027_R2_POR": np.where(
            nop_better,
            "worse",
            "better",
        ),
    }

    allocation_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    for asset_key, owner_array in owner_arrays.items():
        allocated_value_sum = 0.0

        for candidate_team in CANDIDATE_TEAMS:
            condition = owner_array == candidate_team
            probability = float(np.mean(condition))
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
                    "source_team": SOURCE_ASSETS[asset_key][2],
                    "candidate_team": candidate_team,
                    "allocation_probability": probability,
                    "expected_allocated_value_score": expected_value,
                    "expected_pick_when_allocated": (
                        float(np.mean(slots[asset_key][condition]))
                        if condition.any()
                        else np.nan
                    ),
                    "simulation_count": simulation_count,
                }
            )

            for allocation_rank in ("better", "worse"):
                event_condition = (
                    condition
                    & (rank_arrays[asset_key] == allocation_rank)
                )
                if not event_condition.any():
                    continue
                event_rows.append(
                    {
                        "event_type": "candidate_receipt",
                        "event_outcome": "",
                        "candidate_team": candidate_team,
                        "source_asset_key": asset_key,
                        "allocation_rank": allocation_rank,
                        "event_count": int(event_condition.sum()),
                        "event_probability": float(
                            np.mean(event_condition)
                        ),
                        "expected_pick_when_received": float(
                            np.mean(slots[asset_key][event_condition])
                        ),
                        "expected_better_pick_when_event_occurs": np.nan,
                        "expected_worse_pick_when_event_occurs": np.nan,
                    }
                )

        unconditional_value = float(
            np.mean(discounted_values[asset_key])
        )
        reconciliation_rows.append(
            {
                "source_asset_key": asset_key,
                "unconditional_asset_value_score": unconditional_value,
                "allocated_value_sum": allocated_value_sum,
                "allocation_value_difference": (
                    allocated_value_sum - unconditional_value
                ),
                "allocation_probability_sum": float(
                    sum(
                        np.mean(owner_array == team)
                        for team in CANDIDATE_TEAMS
                    )
                ),
                "allocation_reconciliation_passed": bool(
                    abs(allocated_value_sum - unconditional_value)
                    <= 1e-8
                ),
            }
        )

    source_allocations = pd.DataFrame(allocation_rows)
    source_reconciliation = pd.DataFrame(reconciliation_rows)

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
        source_allocations.groupby("candidate_team")["source_asset_key"]
        .apply(
            lambda series: "|".join(
                sorted(set(series.astype(str)))
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

    better_slots = np.minimum(nop_slots, por_slots)

    for branch in (
        BRANCH_PORTLAND_RETAINS,
        BRANCH_HOUSTON_RECEIVES,
    ):
        condition = branch_array == branch
        event_rows.append(
            {
                "event_type": "branch",
                "event_outcome": branch,
                "candidate_team": "",
                "source_asset_key": "",
                "allocation_rank": "worse",
                "event_count": int(condition.sum()),
                "event_probability": float(np.mean(condition)),
                "expected_pick_when_received": np.nan,
                "expected_better_pick_when_event_occurs": float(
                    np.mean(better_slots[condition])
                ),
                "expected_worse_pick_when_event_occurs": float(
                    np.mean(worse_slots[condition])
                ),
            }
        )

    event_summary = pd.DataFrame(event_rows).sort_values(
        [
            "event_type",
            "event_outcome",
            "candidate_team",
            "source_asset_key",
        ]
    ).reset_index(drop=True)

    expected_pick_counts = (
        candidate_rights.set_index("candidate_team")[
            "expected_pick_count"
        ].to_dict()
    )
    houston_probability = float(np.mean(houston_branch))
    portland_probability = 1.0 - houston_probability

    total_source_value = float(
        source_allocations["expected_allocated_value_score"].sum()
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
                "source_asset_count": len(SOURCE_ASSETS),
                "candidate_team_count": int(
                    candidate_rights["candidate_team"].nunique()
                ),
                "total_source_asset_value_score": total_source_value,
                "total_candidate_right_value_score": total_candidate_value,
                "total_candidate_pick_count": float(
                    candidate_rights["expected_pick_count"].sum()
                ),
                "charlotte_expected_pick_count": float(
                    expected_pick_counts.get("CHA", np.nan)
                ),
                "portland_expected_pick_count": float(
                    expected_pick_counts.get("POR", np.nan)
                ),
                "houston_expected_pick_count": float(
                    expected_pick_counts.get("HOU", np.nan)
                ),
                "portland_retention_probability": portland_probability,
                "houston_conveyance_probability": houston_probability,
                "value_difference": (
                    total_candidate_value - total_source_value
                ),
                "component_reconciliation_passed": bool(
                    abs(total_candidate_value - total_source_value)
                    <= 1e-8
                    and abs(
                        candidate_rights["expected_pick_count"].sum()
                        - 2.0
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get("CHA", np.nan) - 1.0
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get("POR", np.nan)
                        - portland_probability
                    )
                    <= 1e-10
                    and abs(
                        expected_pick_counts.get("HOU", np.nan)
                        - houston_probability
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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
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
        valuations[columns].drop_duplicates(subset=["claim_id"]),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    valued = audit[
        "valuation_status"
    ].fillna("").astype(str).str.startswith("valued_")
    direct = (
        audit["valuation_method"]
        .fillna("")
        .astype(str)
        .eq("direct_asset_value")
        | audit["valuation_status"]
        .fillna("")
        .astype(str)
        .eq("valued_direct_candidate")
    )

    disallowed = audit.loc[valued & ~direct]
    if not disallowed.empty:
        raise RuntimeError(
            "A NOP-POR source is already represented by another "
            "component:\n"
            + disallowed[
                [
                    "claim_id",
                    "asset_key",
                    "valuation_method",
                    "valuation_status",
                ]
            ].to_string(index=False)
        )

    contributions: list[dict[str, Any]] = []
    for row in audit.loc[direct].itertuples(index=False):
        value = finite_or_zero(
            getattr(
                row,
                "expected_total_candidate_asset_value_score",
                np.nan,
            )
        )
        if value <= 0.0:
            continue
        contributions.append(
            {
                "claim_id": row.claim_id,
                "asset_key": row.asset_key,
                "team": clean_text(
                    getattr(
                        row,
                        "candidate_beneficiary_team",
                        "",
                    )
                ),
                "current_baseline_value_score": value,
                "baseline_component_type": "direct_asset",
            }
        )

    contribution_frame = pd.DataFrame(
        contributions,
        columns=[
            "claim_id",
            "asset_key",
            "team",
            "current_baseline_value_score",
            "baseline_component_type",
        ],
    )
    return audit, contribution_frame


def build_team_adjustments(
    candidate_rights: pd.DataFrame,
    baseline_contributions: pd.DataFrame,
) -> pd.DataFrame:
    new_values = (
        candidate_rights.set_index("candidate_team")[
            "expected_candidate_right_value_score"
        ].to_dict()
    )
    baseline_values = (
        baseline_contributions.groupby("team")[
            "current_baseline_value_score"
        ].sum().to_dict()
        if not baseline_contributions.empty
        else {}
    )

    rows = []
    for team in sorted(set(CANDIDATE_TEAMS) | set(baseline_values)):
        new_value = float(new_values.get(team, 0.0))
        baseline = float(baseline_values.get(team, 0.0))
        rows.append(
            {
                "team": team,
                "nop_por_cha_hou_component_right_value_score": new_value,
                "existing_counted_baseline_value_score": baseline,
                "net_team_adjustment_value_score": (
                    new_value - baseline
                ),
                "adjustment_scope": (
                    "add_joint_nop_por_protected_favorability_"
                    "component_rights"
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
        "after_sas_sac_okc_cha_component_provisional"
    )
    before_column = (
        "candidate_total_pick_asset_value_score_"
        "before_nop_por_cha_hou_component"
    )
    adjustment_column = (
        "nop_por_cha_hou_component_adjustment_value_score"
    )
    after_column = (
        "candidate_total_pick_asset_value_score_"
        "after_nop_por_cha_hou_component_provisional"
    )

    output[before_column] = pd.to_numeric(
        output[base_column],
        errors="coerce",
    )
    adjustment_lookup = adjustments.set_index("team")[
        "net_team_adjustment_value_score"
    ].to_dict()
    output[adjustment_column] = (
        output["candidate_beneficiary_team"]
        .astype(str)
        .map(adjustment_lookup)
        .fillna(0.0)
    )
    output[after_column] = (
        output[before_column] + output[adjustment_column]
    )
    output["nop_por_cha_hou_component_status"] = (
        "fully_integrated_protected_two_second_favorability_component"
    )
    output["nop_por_cha_hou_component_scope_note"] = (
        "Charlotte receives the more favorable of New Orleans and "
        "Portland's 2027 second-round picks. Portland retains the less "
        "favorable pick when it lands 31-55; Houston receives it when "
        "it lands 56-60."
    )

    return output.sort_values(
        after_column,
        ascending=False,
    ).reset_index(drop=True)


def enrich_valuations(
    valuations: pd.DataFrame,
    source_claims: pd.DataFrame,
    source_allocations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    defaults = {
        "nop_por_cha_hou_component_modeled_flag": False,
        "nop_por_cha_hou_component_primary_claim_flag": False,
        "nop_por_cha_hou_source_asset_value_score": np.nan,
        "nop_por_cha_hou_candidate_allocations_json": "",
    }
    for column, default in defaults.items():
        if column not in output.columns:
            output[column] = default

    for asset_key, claim_group in (
        source_claims[
            ["claim_id", "asset_key"]
        ]
        .sort_values(["asset_key", "claim_id"])
        .groupby("asset_key", sort=True)
    ):
        source_rows = source_allocations.loc[
            source_allocations["source_asset_key"].eq(asset_key)
        ]
        source_value = float(
            source_rows["expected_allocated_value_score"].sum()
        )
        allocation_json = json.dumps(
            {
                str(row.candidate_team): {
                    "expected_value_score": float(
                        row.expected_allocated_value_score
                    ),
                    "allocation_probability": float(
                        row.allocation_probability
                    ),
                }
                for row in source_rows.itertuples(index=False)
            },
            sort_keys=True,
        )
        primary_claim_id = str(claim_group.iloc[0]["claim_id"])

        for row in claim_group.itertuples(index=False):
            claim_id = str(row.claim_id)
            mask = output["claim_id"].astype(str).eq(claim_id)
            if int(mask.sum()) != 1:
                raise ValueError(
                    f"Expected one valuation row for {claim_id}."
                )
            primary = claim_id == primary_claim_id

            output.loc[mask, "valuation_method"] = (
                "joint_2027_nop_por_cha_hou_source_allocation"
            )
            output.loc[mask, "valuation_status"] = (
                "valued_source_asset_fully_allocated"
            )

            for team_column in [
                "candidate_beneficiary_team",
                "candidate_retaining_team",
                "candidate_counterparty_team",
            ]:
                if team_column in output.columns:
                    output.loc[mask, team_column] = ""

            output.loc[
                mask,
                "nop_por_cha_hou_component_modeled_flag",
            ] = True
            output.loc[
                mask,
                "nop_por_cha_hou_component_primary_claim_flag",
            ] = primary
            output.loc[
                mask,
                "nop_por_cha_hou_source_asset_value_score",
            ] = source_value if primary else np.nan
            output.loc[
                mask,
                "nop_por_cha_hou_candidate_allocations_json",
            ] = allocation_json if primary else ""

            for value_column in [
                "expected_total_candidate_asset_value_score",
                "expected_transferred_value_score",
                "expected_retained_value_score",
                "expected_swap_option_value_score",
            ]:
                if value_column in output.columns:
                    output.loc[mask, value_column] = np.nan

            if "automatic_exclusion_reason" in output.columns:
                output.loc[mask, "automatic_exclusion_reason"] = ""
            if "valuation_scope_note" in output.columns:
                output.loc[mask, "valuation_scope_note"] = (
                    "This physical pick is fully allocated through the "
                    "joint 2027 New Orleans-Portland-Charlotte-Houston "
                    "protected second-round component. "
                    + (
                        "This primary claim row carries the source value "
                        "and allocation JSON."
                        if primary
                        else
                        "This overlapping Portland claim row carries no "
                        "source value to prevent duplication."
                    )
                )

    return output


def main() -> None:
    for directory in (PROCESSED_DIRECTORY, OUTPUT_DIRECTORY):
        directory.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("2027 NOP-POR-CHA-HOU PROTECTED TWO-SECOND COMPONENT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
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
        diagnostic=diagnostic,
        valuations=valuations,
    )
    controlling_texts = validate_controlling_text(claims)
    source_claims = validate_source_claims(claims)
    exhaustive_slot_proof = prove_allocation_closure()

    discounts, unconditional_values = build_value_lookups(
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
            "At least one physical source failed reconciliation."
        )

    component = component_reconciliation.iloc[0]
    if not bool(component["component_reconciliation_passed"]):
        raise RuntimeError(
            "The NOP-POR-CHA-HOU component failed reconciliation."
        )

    for asset_key, expected_value in unconditional_values.items():
        actual = float(
            source_allocations.loc[
                source_allocations["source_asset_key"].eq(asset_key),
                "expected_allocated_value_score",
            ].sum()
        )
        if abs(actual - expected_value) > 1e-8:
            raise RuntimeError(
                f"Allocated value for {asset_key} does not match V3."
            )

    baseline_audit, baseline_contributions = build_baseline_audit(
        source_claims=source_claims,
        valuations=valuations,
    )
    if not baseline_contributions.empty:
        raise RuntimeError(
            "The NOP-POR component was expected to have zero counted "
            "baselines, but baseline rows were found:\n"
            + baseline_contributions.to_string(index=False)
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

    unrelated_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "expected_total_candidate_asset_value_score",
        ]
        if column in valuations.columns
        and column in enriched_valuations.columns
    ]
    unrelated_before = (
        valuations.loc[
            valuations["claim_id"]
            .astype(str)
            .isin(UNRELATED_ALREADY_VALUED_CLAIMS),
            unrelated_columns,
        ]
        .sort_values("claim_id")
        .reset_index(drop=True)
    )
    unrelated_after = (
        enriched_valuations.loc[
            enriched_valuations["claim_id"]
            .astype(str)
            .isin(UNRELATED_ALREADY_VALUED_CLAIMS),
            unrelated_columns,
        ]
        .sort_values("claim_id")
        .reset_index(drop=True)
    )
    if not unrelated_before.equals(unrelated_after):
        raise RuntimeError(
            "The existing GSW-PHX component changed during V22."
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
    total_baseline = 0.0
    total_adjustment = float(
        adjustments["net_team_adjustment_value_score"].sum()
    )

    if abs(total_source_value - total_candidate_value) > 1e-8:
        raise RuntimeError(
            "Candidate-right value does not equal source value."
        )
    if abs(total_adjustment - total_source_value) > 1e-8:
        raise RuntimeError(
            "Zero-baseline net adjustment must equal source value."
        )
    if set(SOURCE_ASSETS) != {
        "2027_R2_NOP",
        "2027_R2_POR",
    }:
        raise RuntimeError(
            "The physical source set changed."
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
        V22_VALUATIONS_PARQUET_PATH,
        index=False,
    )
    enriched_valuations.to_csv(
        V22_VALUATIONS_CSV_PATH,
        index=False,
    )
    baseline_audit.to_csv(BASELINE_AUDIT_PATH, index=False)
    adjustments.to_csv(TEAM_ADJUSTMENTS_PATH, index=False)
    updated_team_summary.to_csv(V22_TEAM_SUMMARY_PATH, index=False)
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
        "joint_simulations": int(
            component["joint_simulation_count"]
        ),
        "source_assets_integrated": len(SOURCE_ASSETS),
        "source_claim_rows_enriched": len(source_claims),
        "source_allocation_rows": len(source_allocations),
        "candidate_rights_created": len(candidate_rights),
        "exhaustive_slot_assignments_proved": len(
            exhaustive_slot_proof
        ),
        "all_slot_assignments_allocate_sources_once": bool(
            exhaustive_slot_proof[
                "all_two_sources_assigned_once"
            ].all()
        ),
        "total_source_asset_value_score": total_source_value,
        "total_candidate_right_value_score": total_candidate_value,
        "existing_counted_baseline_value_score": total_baseline,
        "net_team_adjustment_value_score": total_adjustment,
        "portland_retention_probability": float(
            component["portland_retention_probability"]
        ),
        "houston_conveyance_probability": float(
            component["houston_conveyance_probability"]
        ),
        "golden_state_and_phoenix_excluded_from_sources": True,
        "only_new_orleans_and_portland_seconds_in_source_set": bool(
            set(SOURCE_ASSETS)
            == {
                "2027_R2_NOP",
                "2027_R2_POR",
            }
        ),
        "all_source_reconciliations_passed": bool(
            source_reconciliation[
                "allocation_reconciliation_passed"
            ].all()
        ),
        "component_reconciliation_passed": bool(
            component["component_reconciliation_passed"]
        ),
        "source_assets": sorted(SOURCE_ASSETS),
        "controlling_claim_texts": controlling_texts,
        "allocation_policy": [
            (
                "Charlotte receives the more favorable of New Orleans "
                "and Portland's 2027 second-round picks."
            ),
            (
                "Portland retains the less favorable pick when it lands "
                "31-55, and the Houston obligation is extinguished."
            ),
            (
                "Houston receives the less favorable pick when it lands "
                "56-60."
            ),
            (
                "All 870 distinct slot assignments allocate both physical "
                "sources exactly once."
            ),
            (
                "Golden State and Phoenix remain in the existing "
                "eight-second component and are not modified."
            ),
        ],
        "output_files": {
            "source_allocations": str(
                SOURCE_ALLOCATIONS_PARQUET_PATH
            ),
            "candidate_rights": str(
                CANDIDATE_RIGHTS_PARQUET_PATH
            ),
            "event_summary": str(EVENT_SUMMARY_PARQUET_PATH),
            "v22_valuation_layer": str(
                V22_VALUATIONS_PARQUET_PATH
            ),
            "baseline_audit": str(BASELINE_AUDIT_PATH),
            "team_adjustments": str(TEAM_ADJUSTMENTS_PATH),
            "v22_team_summary": str(V22_TEAM_SUMMARY_PATH),
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
    with METADATA_PATH.open("w", encoding="utf-8") as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print("=" * 80)
    print("PROTECTED TWO-SECOND COMPONENT FULLY INTEGRATED")
    print("=" * 80)
    print(
        "Joint simulations: "
        f"{int(component['joint_simulation_count']):,}"
    )
    print(f"Source assets integrated: {len(SOURCE_ASSETS):,}")
    print(f"Source claim rows enriched: {len(source_claims):,}")
    print(f"Source allocation rows: {len(source_allocations):,}")
    print(f"Candidate rights created: {len(candidate_rights):,}")
    print(
        "Exhaustive distinct slot assignments proved: "
        f"{len(exhaustive_slot_proof):,}"
    )
    print(
        "Every slot assignment allocates both sources once: "
        f"{bool(exhaustive_slot_proof['all_two_sources_assigned_once'].all())}"
    )
    print(f"Total source-asset value: {total_source_value:.4f}")
    print(f"Total candidate-right value: {total_candidate_value:.4f}")
    print(f"Existing counted baseline removed: {total_baseline:.4f}")
    print(f"Net team-value adjustment: {total_adjustment:.4f}")
    print(
        "Portland protected-retention probability: "
        f"{float(component['portland_retention_probability']) * 100.0:.2f}%"
    )
    print(
        "Houston conveyance probability: "
        f"{float(component['houston_conveyance_probability']) * 100.0:.2f}%"
    )
    print(
        "Golden State and Phoenix excluded from sources: "
        f"{not (set(SOURCE_ASSETS) & {'2027_R2_GSW', '2027_R2_PHX'})}"
    )
    print(
        "Only New Orleans and Portland seconds in source set: "
        f"{set(SOURCE_ASSETS) == {'2027_R2_NOP', '2027_R2_POR'}}"
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
        "nop_por_cha_hou_component_right_value_score",
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

    print("SELECTION AND PROTECTION EVENT SUMMARY")
    event_display = event_summary.copy()
    event_display["event_probability"] = (
        pd.to_numeric(
            event_display["event_probability"],
            errors="coerce",
        )
        * 100.0
    ).round(2)
    for column in [
        "expected_pick_when_received",
        "expected_better_pick_when_event_occurs",
        "expected_worse_pick_when_event_occurs",
    ]:
        event_display[column] = pd.to_numeric(
            event_display[column],
            errors="coerce",
        ).round(4)
    print(event_display.to_string(index=False))
    print()

    print("EXHAUSTIVE SLOT-ASSIGNMENT PROOF")
    proof_summary = (
        exhaustive_slot_proof.groupby(
            "branch",
            as_index=False,
        )
        .agg(
            valid_distinct_slot_assignments=(
                "nop_second_pick",
                "count",
            ),
            protection_logic_passed=(
                "protection_logic_passed",
                "all",
            ),
            all_sources_assigned_once=(
                "all_two_sources_assigned_once",
                "all",
            ),
        )
    )
    print(proof_summary.to_string(index=False))
    print()

    print("SAVED FILES")
    for path in [
        SOURCE_ALLOCATIONS_PARQUET_PATH,
        SOURCE_ALLOCATIONS_CSV_PATH,
        CANDIDATE_RIGHTS_PARQUET_PATH,
        CANDIDATE_RIGHTS_CSV_PATH,
        EVENT_SUMMARY_PARQUET_PATH,
        EVENT_SUMMARY_CSV_PATH,
        V22_VALUATIONS_PARQUET_PATH,
        V22_VALUATIONS_CSV_PATH,
        BASELINE_AUDIT_PATH,
        TEAM_ADJUSTMENTS_PATH,
        V22_TEAM_SUMMARY_PATH,
        SOURCE_RECONCILIATION_PATH,
        COMPONENT_RECONCILIATION_PATH,
        EXHAUSTIVE_SLOT_PROOF_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()