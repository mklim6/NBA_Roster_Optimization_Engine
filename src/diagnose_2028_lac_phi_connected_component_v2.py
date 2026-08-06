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
    "future-pick-2028-lac-phi-connected-component-diagnostic-v2-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_b3d949dfe6a8"

CORE_ASSETS = {
    "2028_R1_LAC",
    "2028_R1_PHI",
}

EXPECTED_CONNECTED_ASSETS = {
    "2028_R1_LAC",
    "2028_R1_PHI",
    "2028_R1_BOS",
    "2028_R1_SAS",
    "2028_R2_PHI",
}

TARGET_TEAMS = {
    "LAC",
    "PHI",
    "BKN",
    "BOS",
    "SAS",
    "PHX",
    "WAS",
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
    / "future_pick_claim_value_layer_2027_2029_v10_eight_second_enriched.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

GROUP_CLAIMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2028_lac_phi_group_claims_v1.csv"
)

GROUP_METADATA_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_2028_lac_phi_diagnostic_metadata_v1.json"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_connected_claims_v2.csv"
)

SOURCE_INVENTORY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_connected_source_inventory_v2.csv"
)

BOS_SAS_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_bos_sas_swap_claims_v2.csv"
)

BKN_PHX_WAS_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_bkn_phx_was_downstream_claims_v2.csv"
)

PHI_SECOND_FALLBACK_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_phi_second_fallback_claims_v2.csv"
)

RULE_STAGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_rule_stages_v2.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_resolution_template_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_connected_diagnostic_metadata_v2.json"
)


TEXT_COLUMNS = [
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
    "full_claim_text",
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
            + "\n".join(missing)
        )


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and np.isnan(value):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def numeric_value(
    value: Any,
) -> float:
    return float(
        pd.to_numeric(
            pd.Series([value]),
            errors="coerce",
        ).iloc[0]
    )


def json_safe(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return (
            None
            if np.isnan(value)
            else float(value)
        )

    if isinstance(value, float):
        return (
            None
            if math.isnan(value)
            else value
        )

    if pd.isna(value):
        return None

    return value


def join_unique(
    values: pd.Series,
) -> str:
    return "|".join(
        sorted(
            {
                clean_text(value)
                for value in values
                if clean_text(value)
            }
        )
    )


def combined_text(
    frame: pd.DataFrame,
) -> pd.Series:
    output = pd.Series(
        "",
        index=frame.index,
        dtype=str,
    )

    for column in TEXT_COLUMNS:
        if column in frame.columns:
            output = (
                output
                + " "
                + frame[column]
                .fillna("")
                .astype(str)
            )

    return output.map(clean_text)


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        DEPENDENCY_NODES_PATH,
        GROUP_CLAIMS_PATH,
        GROUP_METADATA_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required connected-component diagnostic input was not found:\n"
                f"{path}"
            )

    claims = normalize_columns(
        pd.read_parquet(CLAIMS_PATH)
    )
    valuations = normalize_columns(
        pd.read_parquet(VALUATIONS_PATH)
    )
    dependency_nodes = normalize_columns(
        pd.read_parquet(DEPENDENCY_NODES_PATH)
    )
    group_claims = normalize_columns(
        pd.read_csv(GROUP_CLAIMS_PATH)
    )

    with GROUP_METADATA_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        group_metadata = json.load(file)

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
        "V10 valuation layer",
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
        group_claims,
        [
            "claim_id",
            "asset_key",
            "full_obligation_text",
        ],
        "LAC-PHI group diagnostic claims",
    )

    if clean_text(
        group_metadata.get(
            "target_group_id",
            "",
        )
    ) != TARGET_GROUP_ID:
        raise ValueError(
            "The prior diagnostic metadata does not describe the "
            "configured LAC-PHI group."
        )

    return (
        claims,
        valuations,
        dependency_nodes,
        group_claims,
        group_metadata,
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
        valuations[
            valuation_columns
        ].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    output = output.merge(
        dependency_nodes[
            dependency_columns
        ].drop_duplicates(
            subset=["claim_id"]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
        suffixes=("", "_dependency"),
    )

    output["_combined_text"] = combined_text(output)
    return output


def select_connected_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    text = merged["_combined_text"]

    direct_asset_match = (
        merged["asset_key"]
        .astype(str)
        .isin(EXPECTED_CONNECTED_ASSETS)
    )

    bos_sas_match = (
        text.str.contains(
            r"Boston",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"San Antonio",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"2028",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"swap",
            case=False,
            regex=False,
            na=False,
        )
    )

    phi_fallback_match = (
        text.str.contains(
            r"Philadelphia",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"2028 2nd",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"Brooklyn",
            case=False,
            regex=False,
            na=False,
        )
    )

    downstream_match = (
        text.str.contains(
            r"Brooklyn",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"Phoenix",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"Washington",
            case=False,
            regex=False,
            na=False,
        )
    )

    related = merged.loc[
        direct_asset_match
        | bos_sas_match
        | phi_fallback_match
        | downstream_match
    ].copy()

    related["match_direct_connected_asset"] = (
        direct_asset_match.loc[
            related.index
        ].astype(bool)
    )
    related["match_bos_sas_swap"] = (
        bos_sas_match.loc[
            related.index
        ].astype(bool)
    )
    related["match_phi_second_fallback"] = (
        phi_fallback_match.loc[
            related.index
        ].astype(bool)
    )
    related["match_bkn_phx_was_downstream"] = (
        downstream_match.loc[
            related.index
        ].astype(bool)
    )

    return related.sort_values(
        [
            "match_direct_connected_asset",
            "match_bos_sas_swap",
            "match_phi_second_fallback",
            "match_bkn_phx_was_downstream",
            "asset_key",
            "claim_id",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_source_inventory(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for asset_key in sorted(
        set(
            connected_claims[
                "asset_key"
            ].astype(str)
        )
    ):
        group = connected_claims.loc[
            connected_claims[
                "asset_key"
            ].astype(str).eq(asset_key)
        ]

        valued = group.loc[
            group["valuation_status"]
            .fillna("")
            .astype(str)
            .str.startswith("valued_")
        ]

        rows.append(
            {
                "asset_key": asset_key,
                "draft_year": int(
                    pd.to_numeric(
                        group["draft_year"],
                        errors="coerce",
                    )
                    .dropna()
                    .iloc[0]
                ),
                "round_number": int(
                    pd.to_numeric(
                        group["round_number"],
                        errors="coerce",
                    )
                    .dropna()
                    .iloc[0]
                ),
                "originating_team": join_unique(
                    group["originating_team"]
                ),
                "claim_rows": len(group),
                "valued_claim_rows": len(valued),
                "valuation_methods": join_unique(
                    valued["valuation_method"]
                    if not valued.empty
                    else pd.Series(dtype=str)
                ),
                "valuation_statuses": join_unique(
                    valued["valuation_status"]
                    if not valued.empty
                    else pd.Series(dtype=str)
                ),
                "candidate_beneficiary_teams": join_unique(
                    valued["candidate_beneficiary_team"]
                    if (
                        not valued.empty
                        and "candidate_beneficiary_team"
                        in valued.columns
                    )
                    else pd.Series(dtype=str)
                ),
                "obligation_groups": join_unique(
                    group["obligation_group_id"]
                ),
            }
        )

    return pd.DataFrame(rows)


def build_rule_stages() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stage_order": 1,
                "stage_name": "philadelphia_brooklyn_availability",
                "input_assets": "2028_R1_PHI|2028_R2_PHI",
                "known_rule": (
                    "PHI first conveys to BKN at picks 9-30. "
                    "At picks 1-8, PHI retains the first and instead "
                    "conveys its 2028 second to BKN."
                ),
                "ready": True,
            },
            {
                "stage_order": 2,
                "stage_name": "boston_san_antonio_base_swap",
                "input_assets": "2028_R1_BOS|2028_R1_SAS",
                "known_rule": (
                    "Boston's post-swap available pick is referenced as "
                    "the less favorable of the BOS and SAS picks. Exact "
                    "underlying swap protection must be confirmed."
                ),
                "ready": False,
            },
            {
                "stage_order": 3,
                "stage_name": "clippers_direct_boston_transfer",
                "input_assets": "2028_R1_LAC",
                "known_rule": (
                    "LAC first conveys directly to BOS when outside "
                    "protected selections 1-16."
                ),
                "ready": True,
            },
            {
                "stage_order": 4,
                "stage_name": "boston_fallback_swap",
                "input_assets": (
                    "post_BOS_SAS_pick|2028_R1_LAC|available_2028_R1_PHI"
                ),
                "known_rule": (
                    "When LAC is protected 1-16, Boston may exchange its "
                    "post-BOS/SAS pick for the better available LAC or PHI "
                    "pick. PHI is available only at picks 1-8."
                ),
                "ready": True,
            },
            {
                "stage_order": 5,
                "stage_name": "brooklyn_downstream_control",
                "input_assets": (
                    "BKN_received_2028_R1_PHI_or_2028_R2_PHI"
                ),
                "known_rule": (
                    "The first may continue to PHX and then WAS. Exact "
                    "controller and any comparison rule must be confirmed."
                ),
                "ready": False,
            },
        ]
    )


def classify_readiness(
    connected_claims: pd.DataFrame,
    bos_sas_claims: pd.DataFrame,
    downstream_claims: pd.DataFrame,
    fallback_claims: pd.DataFrame,
) -> tuple[str, bool, str]:
    found_assets = set(
        connected_claims[
            "asset_key"
        ].astype(str)
    )

    source_inventory_ready = (
        EXPECTED_CONNECTED_ASSETS
        <= found_assets
    )

    bos_sas_text_ready = not bos_sas_claims.empty
    fallback_ready = not fallback_claims.empty
    downstream_ready = not downstream_claims.empty

    if (
        source_inventory_ready
        and bos_sas_text_ready
        and fallback_ready
        and downstream_ready
    ):
        return (
            "connected_component_text_found_manual_controller_parse_required",
            False,
            (
                "All expected source assets and related claim families "
                "were located. The component is not yet ready for final "
                "simulation because the Boston-San Antonio swap protection "
                "and Brooklyn-Phoenix-Washington downstream controller must "
                "be confirmed from the printed claim texts."
            ),
        )

    missing = []

    if not source_inventory_ready:
        missing.append(
            "one or more expected source assets"
        )

    if not bos_sas_text_ready:
        missing.append(
            "Boston-San Antonio swap claim"
        )

    if not fallback_ready:
        missing.append(
            "Philadelphia second-round fallback claim"
        )

    if not downstream_ready:
        missing.append(
            "Brooklyn-Phoenix-Washington downstream claim"
        )

    return (
        "connected_component_incomplete",
        False,
        "Missing: " + ", ".join(missing),
    )


def build_resolution_template(
    diagnostic_state: str,
    automatic_value_ready: bool,
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "obligation_group_id": TARGET_GROUP_ID,
                "diagnostic_state": diagnostic_state,
                "automatic_value_ready": automatic_value_ready,
                "connected_claim_ids": join_unique(
                    connected_claims[
                        "claim_id"
                    ]
                ),
                "connected_asset_keys": join_unique(
                    connected_claims[
                        "asset_key"
                    ]
                ),
                "confirmed_bos_sas_swap_protection": "",
                "confirmed_bos_sas_post_swap_allocation": "",
                "confirmed_boston_exercise_rule": "",
                "confirmed_brooklyn_first_controller": "",
                "confirmed_brooklyn_second_controller": "",
                "confirmed_phoenix_onward_rule": "",
                "confirmed_washington_onward_rule": "",
                "source_verified": "",
                "source_as_of_date": "",
                "review_notes": "",
            }
        ]
    )


def print_claim_text(
    title: str,
    frame: pd.DataFrame,
) -> None:
    print(title)

    if frame.empty:
        print("No matching claims were found.")
        print()
        return

    summary_columns = [
        column
        for column in [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "claim_type",
            "resolution_status",
            "destination_team_sequence",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "automatic_exclusion_reason",
            "obligation_group_id",
            "structural_family",
        ]
        if column in frame.columns
    ]

    print(
        frame[
            summary_columns
        ].to_string(index=False)
    )
    print()

    for row in frame.itertuples(index=False):
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


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("2028 LAC-PHI CONNECTED COMPONENT DIAGNOSTIC V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        group_claims,
        group_metadata,
    ) = load_inputs()

    group_assets = set(
        group_claims[
            "asset_key"
        ].astype(str)
    )

    if group_assets != CORE_ASSETS:
        raise ValueError(
            "The prior group diagnostic no longer contains exactly "
            "2028_R1_LAC and 2028_R1_PHI."
        )

    merged = merge_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    connected_claims = select_connected_claims(
        merged
    )

    bos_sas_claims = connected_claims.loc[
        connected_claims[
            "match_bos_sas_swap"
        ]
    ].copy()

    downstream_claims = connected_claims.loc[
        connected_claims[
            "match_bkn_phx_was_downstream"
        ]
    ].copy()

    fallback_claims = connected_claims.loc[
        connected_claims[
            "match_phi_second_fallback"
        ]
    ].copy()

    source_inventory = build_source_inventory(
        connected_claims
    )

    rule_stages = build_rule_stages()

    (
        diagnostic_state,
        automatic_value_ready,
        diagnostic_note,
    ) = classify_readiness(
        connected_claims=connected_claims,
        bos_sas_claims=bos_sas_claims,
        downstream_claims=downstream_claims,
        fallback_claims=fallback_claims,
    )

    connected_claims[
        "diagnostic_state"
    ] = diagnostic_state
    connected_claims[
        "automatic_value_ready"
    ] = automatic_value_ready
    connected_claims[
        "diagnostic_note"
    ] = diagnostic_note

    connected_claims.to_csv(
        CONNECTED_CLAIMS_PATH,
        index=False,
    )
    source_inventory.to_csv(
        SOURCE_INVENTORY_PATH,
        index=False,
    )
    bos_sas_claims.to_csv(
        BOS_SAS_CLAIMS_PATH,
        index=False,
    )
    downstream_claims.to_csv(
        BKN_PHX_WAS_CLAIMS_PATH,
        index=False,
    )
    fallback_claims.to_csv(
        PHI_SECOND_FALLBACK_PATH,
        index=False,
    )
    rule_stages.to_csv(
        RULE_STAGES_PATH,
        index=False,
    )

    build_resolution_template(
        diagnostic_state=diagnostic_state,
        automatic_value_ready=automatic_value_ready,
        connected_claims=connected_claims,
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
        "prior_group_review_order": int(
            numeric_value(
                group_metadata[
                    "review_order"
                ]
            )
        ),
        "prior_group_unique_asset_exposure_score": numeric_value(
            group_metadata[
                "unique_asset_exposure_score"
            ]
        ),
        "connected_claim_rows": len(
            connected_claims
        ),
        "connected_asset_keys": sorted(
            set(
                connected_claims[
                    "asset_key"
                ].astype(str)
            )
        ),
        "expected_connected_asset_set_found": bool(
            EXPECTED_CONNECTED_ASSETS
            <= set(
                connected_claims[
                    "asset_key"
                ].astype(str)
            )
        ),
        "bos_sas_claim_rows": len(
            bos_sas_claims
        ),
        "phi_second_fallback_rows": len(
            fallback_claims
        ),
        "bkn_phx_was_downstream_rows": len(
            downstream_claims
        ),
        "diagnostic_state": diagnostic_state,
        "automatic_value_ready": (
            automatic_value_ready
        ),
        "diagnostic_note": diagnostic_note,
        "output_files": {
            "connected_claims": str(
                CONNECTED_CLAIMS_PATH
            ),
            "source_inventory": str(
                SOURCE_INVENTORY_PATH
            ),
            "bos_sas_claims": str(
                BOS_SAS_CLAIMS_PATH
            ),
            "bkn_phx_was_claims": str(
                BKN_PHX_WAS_CLAIMS_PATH
            ),
            "phi_second_fallback": str(
                PHI_SECOND_FALLBACK_PATH
            ),
            "rule_stages": str(
                RULE_STAGES_PATH
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
    print("CONNECTED COMPONENT DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        f"Connected claim rows: "
        f"{len(connected_claims):,}"
    )
    print(
        "Connected unique assets: "
        f"{connected_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Expected five-source set found: "
        f"{EXPECTED_CONNECTED_ASSETS <= set(connected_claims['asset_key'].astype(str))}"
    )
    print(
        f"Boston-San Antonio claim rows: "
        f"{len(bos_sas_claims):,}"
    )
    print(
        "Philadelphia second fallback rows: "
        f"{len(fallback_claims):,}"
    )
    print(
        "Brooklyn-Phoenix-Washington downstream rows: "
        f"{len(downstream_claims):,}"
    )
    print(f"Diagnostic state: {diagnostic_state}")
    print(
        f"Automatic value ready: "
        f"{automatic_value_ready}"
    )
    print()

    print("RULE STAGES")
    print(
        rule_stages.to_string(index=False)
    )
    print()

    print("SOURCE INVENTORY")
    print(
        source_inventory.to_string(index=False)
    )
    print()

    print_claim_text(
        "BOSTON-SAN ANTONIO SWAP CLAIMS",
        bos_sas_claims,
    )

    print_claim_text(
        "PHILADELPHIA SECOND-ROUND FALLBACK CLAIMS",
        fallback_claims,
    )

    print_claim_text(
        "BROOKLYN-PHOENIX-WASHINGTON DOWNSTREAM CLAIMS",
        downstream_claims,
    )

    print()
    print("SAVED FILES")
    print(CONNECTED_CLAIMS_PATH)
    print(SOURCE_INVENTORY_PATH)
    print(BOS_SAS_CLAIMS_PATH)
    print(BKN_PHX_WAS_CLAIMS_PATH)
    print(PHI_SECOND_FALLBACK_PATH)
    print(RULE_STAGES_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()