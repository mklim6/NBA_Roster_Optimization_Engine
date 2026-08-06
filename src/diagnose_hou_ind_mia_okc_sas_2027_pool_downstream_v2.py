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
    "future-pick-hou-ind-mia-okc-sas-2027-pool-downstream-diagnostic-v2-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_f60ebafc3d7d"

GROUP_SOURCE_ASSETS = {
    "2027_R2_HOU",
    "2027_R2_IND",
    "2027_R2_MIA",
    "2027_R2_OKC",
}

FULL_SOURCE_ASSETS = {
    *GROUP_SOURCE_ASSETS,
    "2027_R2_SAS",
}

TARGET_TEAMS = {
    "HOU",
    "IND",
    "MIA",
    "OKC",
    "SAS",
    "PHI",
    "NOP",
    "NYK",
    "LAC",
}

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
    / "future_pick_claim_value_layer_2027_2029_v9_cle_min_uta_pool_enriched.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

PREVIOUS_GROUP_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_hou_ind_mia_okc_2027_group_claims_v1.csv"
)

RESIDUAL_GROUP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_dependency_group_audit_after_v9.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CORRECTED_GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_corrected_group_claims_v2.csv"
)

FULL_SOURCE_INVENTORY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_source_inventory_v2.csv"
)

PHI_LAC_DOWNSTREAM_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_phi_lac_downstream_claims_v2.csv"
)

POOL_RULE_STAGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_rule_stages_v2.csv"
)

SOURCE_BASELINE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_existing_baseline_v2.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_resolution_template_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_sas_2027_diagnostic_metadata_v2.json"
)


TEXT_COLUMNS = [
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
    "full_claim_text",
]

TEAM_COLUMNS = [
    "originating_team",
    "candidate_current_owner",
    "single_destination_team",
    "destination_team_sequence",
    "candidate_beneficiary_team",
    "candidate_retaining_team",
    "candidate_counterparty_team",
    "mentioned_teams",
    "beneficiary_teams",
]

EXPECTED_POOL_TEXT_FRAGMENTS = [
    "Philadelphia will receive the most favorable",
    "Oklahoma City's 2027 2nd round pick",
    "Houston's 2027 2nd round pick",
    "Indiana's 2027 2nd round pick",
    "Miami's 2027 2nd round pick",
    "New Orleans will receive the second most favorable",
    "New York will receive the third most favorable",
    "San Antonio will receive the more favorable",
    "its 2027 2nd round pick",
    "Miami will receive the least favorable of the five",
    "Philadelphia may convey this pick to the L.A. Clippers",
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


def combined_text(frame: pd.DataFrame) -> pd.Series:
    output = pd.Series("", index=frame.index, dtype=str)
    for column in TEXT_COLUMNS:
        if column in frame.columns:
            output = (
                output
                + " "
                + frame[column].fillna("").astype(str)
            )
    return output.map(clean_text)


def parse_team_tokens(value: Any) -> set[str]:
    text = clean_text(value).upper()
    if not text:
        return set()
    return {
        token
        for token in re.split(r"[^A-Z]+", text)
        if len(token) == 3
    } & TARGET_TEAMS


def join_unique(values: pd.Series) -> str:
    return "|".join(
        sorted(
            {
                clean_text(value)
                for value in values
                if clean_text(value)
            }
        )
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        DEPENDENCY_NODES_PATH,
        PREVIOUS_GROUP_CLAIMS_PATH,
        RESIDUAL_GROUP_AUDIT_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required corrected-pool diagnostic input was not found:\n"
                f"{path}"
            )

    claims = normalize_columns(pd.read_parquet(CLAIMS_PATH))
    valuations = normalize_columns(pd.read_parquet(VALUATIONS_PATH))
    dependency_nodes = normalize_columns(
        pd.read_parquet(DEPENDENCY_NODES_PATH)
    )
    previous_group_claims = normalize_columns(
        pd.read_csv(PREVIOUS_GROUP_CLAIMS_PATH)
    )
    residual_groups = normalize_columns(
        pd.read_csv(RESIDUAL_GROUP_AUDIT_PATH)
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
        ],
        "V9 valuation layer",
    )
    require_columns(
        dependency_nodes,
        [
            "claim_id",
            "obligation_group_id",
            "structural_family",
        ],
        "Dependency claim nodes",
    )
    require_columns(
        previous_group_claims,
        [
            "claim_id",
            "asset_key",
            "full_obligation_text",
        ],
        "Previous group diagnostic",
    )
    require_columns(
        residual_groups,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V9 residual group audit",
    )

    return (
        claims,
        valuations,
        dependency_nodes,
        previous_group_claims,
        residual_groups,
    )


def merge_context(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
    dependency_nodes: pd.DataFrame,
) -> pd.DataFrame:
    valuation_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
        ]
        if column in valuations.columns
    ]

    dependency_columns = [
        column
        for column in [
            "claim_id",
            "obligation_group_id",
            "structural_family",
            "mentioned_teams",
            "mentioned_years",
            "mentioned_rounds",
            "beneficiary_teams",
            "swap_flag",
            "favorability_pool_flag",
            "protection_flag",
            "rollover_or_fallback_language_flag",
        ]
        if column in dependency_nodes.columns
    ]

    output = claims.merge(
        valuations[valuation_columns].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    output = output.merge(
        dependency_nodes[dependency_columns].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
        suffixes=("", "_dependency"),
    )

    output["_combined_text"] = combined_text(output)
    return output


def validate_group(
    previous_group_claims: pd.DataFrame,
    residual_groups: pd.DataFrame,
) -> tuple[pd.Series, str]:
    group_match = residual_groups.loc[
        residual_groups[
            "effective_obligation_group_id"
        ].astype(str).eq(TARGET_GROUP_ID)
    ]

    if len(group_match) != 1:
        raise ValueError(
            f"Expected one residual group row for {TARGET_GROUP_ID}; "
            f"found {len(group_match)}."
        )

    asset_set = set(
        previous_group_claims["asset_key"].astype(str)
    )

    if asset_set != GROUP_SOURCE_ASSETS:
        raise ValueError(
            "Corrected diagnostic expected the four unresolved "
            "second-round group assets:\n"
            + "\n".join(sorted(GROUP_SOURCE_ASSETS))
            + "\n\nFound:\n"
            + "\n".join(sorted(asset_set))
        )

    texts = sorted(
        {
            clean_text(value)
            for value in previous_group_claims[
                "full_obligation_text"
            ]
            if clean_text(value)
        },
        key=len,
        reverse=True,
    )

    if not texts:
        raise ValueError("No canonical pool text was available.")

    canonical_text = texts[0]

    missing_fragments = [
        fragment
        for fragment in EXPECTED_POOL_TEXT_FRAGMENTS
        if fragment.lower() not in canonical_text.lower()
    ]

    if missing_fragments:
        raise ValueError(
            "Canonical pool text is missing expected clauses:\n"
            + "\n".join(missing_fragments)
        )

    return group_match.iloc[0], canonical_text


def source_inventory(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    inventory = merged.loc[
        merged["asset_key"].astype(str).isin(FULL_SOURCE_ASSETS)
    ].copy()

    inventory["is_unresolved_group_source"] = (
        inventory["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    )

    inventory["is_san_antonio_fifth_source"] = (
        inventory["asset_key"].astype(str).eq("2027_R2_SAS")
    )

    inventory["is_currently_valued"] = (
        inventory["valuation_status"]
        .fillna("")
        .astype(str)
        .str.startswith("valued_")
    )

    inventory["current_counted_value_score"] = 0.0

    direct_mask = (
        inventory["valuation_status"]
        .fillna("")
        .astype(str)
        .eq("valued_direct_candidate")
    )

    if "expected_total_candidate_asset_value_score" in inventory.columns:
        inventory.loc[
            direct_mask,
            "current_counted_value_score",
        ] = pd.to_numeric(
            inventory.loc[
                direct_mask,
                "expected_total_candidate_asset_value_score",
            ],
            errors="coerce",
        ).fillna(0.0)

    return inventory.sort_values(
        [
            "asset_key",
            "is_unresolved_group_source",
            "claim_id",
        ],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def downstream_phi_lac_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    text = merged["_combined_text"]

    exact_reference = text.str.contains(
        r"Philadelphia may convey this pick to the L\.?A\.? Clippers",
        case=False,
        regex=True,
        na=False,
    )

    outgoing_reference = text.str.contains(
        r"Philadelphia Outgoing",
        case=False,
        regex=False,
        na=False,
    )

    explicit_2027_second = (
        pd.to_numeric(
            merged["draft_year"],
            errors="coerce",
        ).eq(2027)
        & pd.to_numeric(
            merged["round_number"],
            errors="coerce",
        ).eq(2)
        & text.str.contains(
            r"Philadelphia",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"Clippers",
            case=False,
            regex=False,
            na=False,
        )
    )

    parsed_lac_destination = pd.Series(
        False,
        index=merged.index,
        dtype=bool,
    )

    for column in [
        "single_destination_team",
        "destination_team_sequence",
        "candidate_beneficiary_team",
    ]:
        if column in merged.columns:
            parsed_lac_destination |= (
                merged[column]
                .fillna("")
                .astype(str)
                .map(lambda value: "LAC" in parse_team_tokens(value))
            )

    result = merged.loc[
        exact_reference
        | outgoing_reference
        | explicit_2027_second
        | parsed_lac_destination
    ].copy()

    result["match_exact_pool_onward_reference"] = (
        exact_reference.loc[result.index].astype(bool)
    )

    result["match_philadelphia_outgoing_reference"] = (
        outgoing_reference.loc[result.index].astype(bool)
    )

    result["match_explicit_2027_second_phi_lac"] = (
        explicit_2027_second.loc[result.index].astype(bool)
    )

    result["match_parsed_lac_destination"] = (
        parsed_lac_destination.loc[result.index].astype(bool)
    )

    return result.sort_values(
        [
            "match_exact_pool_onward_reference",
            "match_philadelphia_outgoing_reference",
            "match_explicit_2027_second_phi_lac",
            "claim_id",
        ],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)


def build_rule_stages() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stage_order": 1,
                "stage_name": "rank_four_incoming_seconds",
                "input_assets": (
                    "2027_R2_OKC|2027_R2_HOU|2027_R2_IND|2027_R2_MIA"
                ),
                "operation": (
                    "sort by overall pick number, lowest is most favorable"
                ),
                "output_allocation": (
                    "rank1_to_PHI|rank2_to_NOP|rank3_to_NYK|rank4_to_stage2"
                ),
                "automatic_rule_ready": True,
            },
            {
                "stage_order": 2,
                "stage_name": "compare_fourth_pick_with_san_antonio",
                "input_assets": (
                    "rank4_from_stage1|2027_R2_SAS"
                ),
                "operation": (
                    "San Antonio receives the lower-numbered pick; "
                    "Miami receives the higher-numbered pick"
                ),
                "output_allocation": (
                    "more_favorable_to_SAS|least_favorable_of_five_to_MIA"
                ),
                "automatic_rule_ready": True,
            },
            {
                "stage_order": 3,
                "stage_name": "philadelphia_possible_onward_conveyance",
                "input_assets": "rank1_from_stage1",
                "operation": (
                    "Philadelphia may convey its acquired pick to the "
                    "L.A. Clippers under Philadelphia Outgoing"
                ),
                "output_allocation": "PHI_or_LAC",
                "automatic_rule_ready": False,
            },
        ]
    )


def build_source_baseline(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for asset_key in sorted(FULL_SOURCE_ASSETS):
        subset = inventory.loc[
            inventory["asset_key"].astype(str).eq(asset_key)
        ]

        valued = subset.loc[
            subset["is_currently_valued"]
        ]

        rows.append(
            {
                "source_asset_key": asset_key,
                "claim_rows": len(subset),
                "valued_claim_rows": len(valued),
                "current_candidate_teams": join_unique(
                    valued["candidate_beneficiary_team"]
                    if "candidate_beneficiary_team" in valued.columns
                    else pd.Series(dtype=str)
                ),
                "current_counted_value_score": float(
                    pd.to_numeric(
                        valued["current_counted_value_score"],
                        errors="coerce",
                    ).fillna(0.0).sum()
                ),
                "valuation_methods": join_unique(
                    valued["valuation_method"]
                    if "valuation_method" in valued.columns
                    else pd.Series(dtype=str)
                ),
                "valuation_statuses": join_unique(
                    valued["valuation_status"]
                    if "valuation_status" in valued.columns
                    else pd.Series(dtype=str)
                ),
            }
        )

    return pd.DataFrame(rows)


def classify_readiness(
    inventory: pd.DataFrame,
    downstream: pd.DataFrame,
) -> tuple[str, bool, bool, str]:
    inventory_assets = set(
        inventory["asset_key"].astype(str)
    )

    full_source_ready = FULL_SOURCE_ASSETS <= inventory_assets

    distinct_downstream = downstream.loc[
        ~downstream["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    ]

    explicit_distinct_claim = distinct_downstream.loc[
        distinct_downstream[
            "match_explicit_2027_second_phi_lac"
        ]
        | distinct_downstream[
            "match_parsed_lac_destination"
        ]
    ]

    primary_pool_ready = full_source_ready

    if not full_source_ready:
        return (
            "five_source_inventory_incomplete",
            False,
            False,
            (
                "The four group sources were found, but San Antonio's "
                "2027 second was not located in the current claim layer."
            ),
        )

    if explicit_distinct_claim.empty:
        return (
            "primary_five_pick_pool_ready_phi_lac_downstream_unresolved",
            True,
            False,
            (
                "The five-pick pool can be valued, but the final owner of "
                "Philadelphia's rank-one pick cannot yet be assigned "
                "because no distinct Philadelphia-to-Clippers controlling "
                "claim was resolved from the current claim layer."
            ),
        )

    return (
        "primary_pool_ready_phi_lac_claim_found_manual_condition_parse_required",
        True,
        False,
        (
            "The five-pick pool is ready and at least one distinct "
            "Philadelphia-to-Clippers claim was found. Its exact condition "
            "must be parsed before final team integration."
        ),
    )


def build_resolution_template(
    diagnostic_state: str,
    primary_pool_ready: bool,
    final_team_integration_ready: bool,
    downstream: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "obligation_group_id": TARGET_GROUP_ID,
                "diagnostic_state": diagnostic_state,
                "primary_pool_value_ready": primary_pool_ready,
                "final_team_integration_ready": (
                    final_team_integration_ready
                ),
                "physical_source_assets": "|".join(
                    sorted(FULL_SOURCE_ASSETS)
                ),
                "rank1_initial_recipient": "PHI",
                "rank2_recipient": "NOP",
                "rank3_recipient": "NYK",
                "rank4_comparison_recipient": "SAS",
                "rank5_recipient": "MIA",
                "phi_lac_candidate_claim_ids": join_unique(
                    downstream["claim_id"]
                    if not downstream.empty
                    else pd.Series(dtype=str)
                ),
                "confirmed_phi_to_lac_condition": "",
                "confirmed_phi_retention_condition": "",
                "source_verified": "",
                "source_as_of_date": "",
                "review_notes": "",
            }
        ]
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("HOU-IND-MIA-OKC-SAS 2027 SECOND-ROUND POOL DIAGNOSTIC V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        previous_group_claims,
        residual_groups,
    ) = load_inputs()

    target_group_row, canonical_text = validate_group(
        previous_group_claims=previous_group_claims,
        residual_groups=residual_groups,
    )

    merged = merge_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    corrected_group_claims = merged.loc[
        merged["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    ].copy()

    inventory = source_inventory(merged)
    downstream = downstream_phi_lac_claims(merged)
    rule_stages = build_rule_stages()
    baseline = build_source_baseline(inventory)

    (
        diagnostic_state,
        primary_pool_ready,
        final_team_integration_ready,
        diagnostic_note,
    ) = classify_readiness(
        inventory=inventory,
        downstream=downstream,
    )

    corrected_group_claims["diagnostic_state"] = diagnostic_state
    corrected_group_claims["primary_pool_value_ready"] = (
        primary_pool_ready
    )
    corrected_group_claims["final_team_integration_ready"] = (
        final_team_integration_ready
    )
    corrected_group_claims["diagnostic_note"] = diagnostic_note

    corrected_group_claims.to_csv(
        CORRECTED_GROUP_CLAIMS_PATH,
        index=False,
    )
    inventory.to_csv(
        FULL_SOURCE_INVENTORY_PATH,
        index=False,
    )
    downstream.to_csv(
        PHI_LAC_DOWNSTREAM_PATH,
        index=False,
    )
    rule_stages.to_csv(
        POOL_RULE_STAGES_PATH,
        index=False,
    )
    baseline.to_csv(
        SOURCE_BASELINE_PATH,
        index=False,
    )

    build_resolution_template(
        diagnostic_state=diagnostic_state,
        primary_pool_ready=primary_pool_ready,
        final_team_integration_ready=final_team_integration_ready,
        downstream=downstream,
    ).to_csv(
        RESOLUTION_TEMPLATE_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_group_id": TARGET_GROUP_ID,
        "residual_review_order": int(
            numeric_value(target_group_row["review_order"])
        ),
        "residual_unique_asset_exposure_score": numeric_value(
            target_group_row["unique_asset_exposure_score"]
        ),
        "corrected_group_round": 2,
        "corrected_group_source_assets": sorted(GROUP_SOURCE_ASSETS),
        "full_pool_source_assets": sorted(FULL_SOURCE_ASSETS),
        "corrected_group_claim_rows": len(corrected_group_claims),
        "full_source_inventory_rows": len(inventory),
        "distinct_source_assets_found": int(
            inventory["asset_key"].astype(str).nunique()
        ),
        "phi_lac_candidate_rows": len(downstream),
        "primary_pool_value_ready": primary_pool_ready,
        "final_team_integration_ready": (
            final_team_integration_ready
        ),
        "diagnostic_state": diagnostic_state,
        "diagnostic_note": diagnostic_note,
        "canonical_pool_text": canonical_text,
        "rule_interpretation": [
            (
                "Sort OKC, Houston, Indiana, and Miami 2027 seconds "
                "from lowest to highest overall pick."
            ),
            (
                "Philadelphia receives rank 1, New Orleans rank 2, "
                "and New York rank 3."
            ),
            (
                "Compare rank 4 with San Antonio's own 2027 second."
            ),
            (
                "San Antonio receives the lower-numbered of those two."
            ),
            (
                "Miami receives the higher-numbered pick, which is the "
                "least favorable of all five."
            ),
            (
                "Philadelphia's rank-one pick may have a separate onward "
                "conveyance to the Clippers that must be resolved before "
                "final team allocation."
            ),
        ],
        "output_files": {
            "corrected_group_claims": str(
                CORRECTED_GROUP_CLAIMS_PATH
            ),
            "source_inventory": str(
                FULL_SOURCE_INVENTORY_PATH
            ),
            "phi_lac_downstream_claims": str(
                PHI_LAC_DOWNSTREAM_PATH
            ),
            "rule_stages": str(
                POOL_RULE_STAGES_PATH
            ),
            "source_baseline": str(
                SOURCE_BASELINE_PATH
            ),
            "resolution_template": str(
                RESOLUTION_TEMPLATE_PATH
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
    print("CORRECTED FIVE-PICK POOL DIAGNOSTIC CREATED")
    print("=" * 80)
    print(f"Target group: {TARGET_GROUP_ID}")
    print("Corrected round: 2")
    print(
        "Group source assets matched: "
        f"{set(corrected_group_claims['asset_key'].astype(str)) == GROUP_SOURCE_ASSETS}"
    )
    print(
        "Full five-source inventory found: "
        f"{FULL_SOURCE_ASSETS <= set(inventory['asset_key'].astype(str))}"
    )
    print(
        "Distinct physical source assets found: "
        f"{inventory['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Philadelphia-Clippers candidate rows: "
        f"{len(downstream):,}"
    )
    print(f"Diagnostic state: {diagnostic_state}")
    print(f"Primary pool value ready: {primary_pool_ready}")
    print(
        "Final team integration ready: "
        f"{final_team_integration_ready}"
    )
    print()

    print("POOL RULE STAGES")
    print(rule_stages.to_string(index=False))
    print()

    print("SOURCE BASELINE")
    baseline_display = baseline.copy()
    baseline_display[
        "current_counted_value_score"
    ] = pd.to_numeric(
        baseline_display["current_counted_value_score"],
        errors="coerce",
    ).round(4)
    print(baseline_display.to_string(index=False))
    print()

    print("FULL SOURCE INVENTORY")
    inventory_columns = [
        column
        for column in [
            "claim_id",
            "asset_key",
            "originating_team",
            "claim_type",
            "resolution_status",
            "destination_team_sequence",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "current_counted_value_score",
            "obligation_group_id",
            "structural_family",
            "is_unresolved_group_source",
            "is_san_antonio_fifth_source",
        ]
        if column in inventory.columns
    ]
    print(inventory[inventory_columns].to_string(index=False))
    print()

    print("PHILADELPHIA-CLIPPERS DOWNSTREAM CANDIDATES")
    if downstream.empty:
        print("No downstream candidate rows were found.")
    else:
        downstream_columns = [
            column
            for column in [
                "claim_id",
                "asset_key",
                "draft_year",
                "round_number",
                "claim_type",
                "resolution_status",
                "destination_team_sequence",
                "valuation_method",
                "valuation_status",
                "candidate_beneficiary_team",
                "automatic_exclusion_reason",
                "obligation_group_id",
                "structural_family",
                "match_exact_pool_onward_reference",
                "match_philadelphia_outgoing_reference",
                "match_explicit_2027_second_phi_lac",
                "match_parsed_lac_destination",
            ]
            if column in downstream.columns
        ]
        print(
            downstream[downstream_columns].to_string(index=False)
        )

        print()
        print("DOWNSTREAM CLAIM TEXT")
        for row in downstream.itertuples(index=False):
            print("-" * 80)
            print(
                f"Claim: {getattr(row, 'claim_id', '')} | "
                f"Asset: {getattr(row, 'asset_key', '')}"
            )
            for column in TEXT_COLUMNS:
                if hasattr(row, column):
                    value = clean_text(
                        getattr(row, column, "")
                    )
                    if value:
                        print(f"{column}: {value}")

    print()
    print("SAVED FILES")
    print(CORRECTED_GROUP_CLAIMS_PATH)
    print(FULL_SOURCE_INVENTORY_PATH)
    print(PHI_LAC_DOWNSTREAM_PATH)
    print(POOL_RULE_STAGES_PATH)
    print(SOURCE_BASELINE_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()