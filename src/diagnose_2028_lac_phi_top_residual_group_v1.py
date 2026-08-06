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
    "future-pick-2028-lac-phi-top-residual-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_b3d949dfe6a8"

TARGET_TEAMS = {
    "LAC",
    "PHI",
    "BKN",
    "BOS",
}

TEAM_NAME_PATTERNS = {
    "LAC": r"\bL\.?A\.?\s+Clippers\b|\bLos Angeles Clippers\b",
    "PHI": r"\bPhiladelphia\b",
    "BKN": r"\bBrooklyn\b",
    "BOS": r"\bBoston\b",
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

RESIDUAL_GROUP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_dependency_group_audit_after_v10.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v10.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_group_claims_v1.csv"
)

OVERLAP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_overlap_claims_v1.csv"
)

RELATED_TEXT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_related_text_matches_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_rule_fragments_v1.csv"
)

CLAIM_RELATION_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_claim_relation_matrix_v1.csv"
)

ASSET_INVENTORY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_asset_inventory_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2028_lac_phi_diagnostic_metadata_v1.json"
)


TEXT_COLUMNS = [
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
    "full_claim_text",
]

TEAM_FIELD_COLUMNS = [
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
    cleaned = sorted(
        {
            clean_text(value)
            for value in values
            if clean_text(value)
        }
    )

    return "|".join(cleaned)


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


def parse_team_tokens(
    value: Any,
) -> set[str]:
    text = clean_text(value).upper()

    if not text:
        return set()

    tokens = {
        token
        for token in re.split(
            r"[^A-Z]+",
            text,
        )
        if len(token) == 3
    }

    return tokens & TARGET_TEAMS


def row_team_tokens(
    row: pd.Series,
) -> set[str]:
    teams = set()

    for column in TEAM_FIELD_COLUMNS:
        if column in row.index:
            teams.update(
                parse_team_tokens(
                    row[column]
                )
            )

    text = clean_text(
        row.get(
            "_combined_text",
            "",
        )
    )

    for team, pattern in TEAM_NAME_PATTERNS.items():
        if re.search(
            pattern,
            text,
            re.IGNORECASE,
        ):
            teams.add(team)

    return teams


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
        RESIDUAL_GROUP_AUDIT_PATH,
        RESIDUAL_CLAIM_AUDIT_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required 2028 LAC-PHI diagnostic input was not found:\n"
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

    residual_groups = normalize_columns(
        pd.read_csv(RESIDUAL_GROUP_AUDIT_PATH)
    )

    residual_claims = normalize_columns(
        pd.read_csv(RESIDUAL_CLAIM_AUDIT_PATH)
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
        residual_groups,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V10 residual group audit",
    )

    require_columns(
        residual_claims,
        [
            "claim_id",
            "asset_key",
            "claim_unresolved",
        ],
        "V10 residual claim audit",
    )

    return (
        claims,
        valuations,
        dependency_nodes,
        residual_groups,
        residual_claims,
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

    output["parsed_target_teams"] = output.apply(
        lambda row: "|".join(
            sorted(
                row_team_tokens(row)
            )
        ),
        axis=1,
    )

    return output


def validate_target_group(
    residual_groups: pd.DataFrame,
) -> pd.Series:
    match = residual_groups.loc[
        residual_groups[
            "effective_obligation_group_id"
        ]
        .astype(str)
        .eq(TARGET_GROUP_ID)
    ]

    if len(match) != 1:
        raise ValueError(
            "Expected exactly one residual-group row for "
            f"{TARGET_GROUP_ID}; found {len(match)}."
        )

    row = match.iloc[0]

    if int(
        numeric_value(
            row["review_order"]
        )
    ) != 1:
        raise RuntimeError(
            "The configured LAC-PHI group is no longer review order 1. "
            "Rerun the V10 residual audit first."
        )

    return row


def select_group_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    group_claims = merged.loc[
        merged["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    ].copy()

    if group_claims.empty:
        raise ValueError(
            "No claims were found for target group "
            f"{TARGET_GROUP_ID}."
        )

    return group_claims.sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(drop=True)


def select_overlap_claims(
    merged: pd.DataFrame,
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    asset_keys = set(
        group_claims["asset_key"]
        .astype(str)
    )

    overlap = merged.loc[
        merged["asset_key"]
        .astype(str)
        .isin(asset_keys)
    ].copy()

    overlap["is_target_group_claim"] = (
        overlap["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    )

    return overlap.sort_values(
        [
            "asset_key",
            "is_target_group_claim",
            "claim_id",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)


def select_related_text(
    merged: pd.DataFrame,
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    group_assets = set(
        group_claims["asset_key"]
        .astype(str)
    )

    text_pattern = re.compile(
        (
            r"2028\s+1st"
            r"|2028\s+first"
            r"|L\.?A\.?\s+Clippers"
            r"|Philadelphia"
            r"|Brooklyn"
            r"|Boston"
            r"|more\s+favorable"
            r"|less\s+favorable"
            r"|most\s+favorable"
            r"|least\s+favorable"
            r"|\bswap\b"
            r"|\bprotected\b"
            r"|\brollover\b"
            r"|\bconvey\b"
            r"|\bextinguish"
        ),
        re.IGNORECASE,
    )

    text_match = merged[
        "_combined_text"
    ].map(
        lambda text: bool(
            text_pattern.search(text)
        )
    )

    asset_match = merged[
        "asset_key"
    ].astype(str).isin(group_assets)

    team_match = merged.apply(
        lambda row: bool(
            row_team_tokens(row)
        ),
        axis=1,
    )

    related = merged.loc[
        text_match
        & (
            asset_match
            | team_match
        )
    ].copy()

    related["related_text_match"] = True

    return related.sort_values(
        [
            "obligation_group_id",
            "asset_key",
            "claim_id",
        ]
    ).reset_index(drop=True)


def extract_rule_fragments(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    patterns = {
        "favorability_rule": (
            r"[^.;]*\b(?:more favorable|less favorable|most favorable|"
            r"least favorable|better of|worse of)\b[^.;]*"
        ),
        "swap_rule": (
            r"[^.;]*\b(?:right to swap|swap)\b[^.;]*"
        ),
        "protection_rule": (
            r"[^.;]*\b(?:protected|protection|selections? \d+)"
            r"[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if|conditional)"
            r"\b[^.;]*"
        ),
        "rollover_rule": (
            r"[^.;]*\b(?:roll over|rollover|instead|fallback|"
            r"extinguished|extinguish)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Brooklyn|to Boston|"
            r"to Philadelphia|to L\.?A\.? Clippers)\b[^.;]*"
        ),
    }

    rows: list[dict[str, Any]] = []

    for _, row in group_claims.iterrows():
        text = clean_text(
            row.get(
                "full_obligation_text",
                "",
            )
        )

        if not text:
            text = clean_text(
                row.get(
                    "transaction_text",
                    "",
                )
            )

        for rule_type, pattern in patterns.items():
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            for order, fragment in enumerate(
                matches,
                start=1,
            ):
                rows.append(
                    {
                        "claim_id": clean_text(
                            row["claim_id"]
                        ),
                        "asset_key": clean_text(
                            row["asset_key"]
                        ),
                        "rule_type": rule_type,
                        "match_order": order,
                        "rule_fragment": clean_text(
                            fragment
                        ),
                    }
                )

    return pd.DataFrame(
        rows,
        columns=[
            "claim_id",
            "asset_key",
            "rule_type",
            "match_order",
            "rule_fragment",
        ],
    )


def build_relation_matrix(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in group_claims.iterrows():
        text = clean_text(
            row.get(
                "_combined_text",
                "",
            )
        )

        rows.append(
            {
                "claim_id": clean_text(
                    row["claim_id"]
                ),
                "asset_key": clean_text(
                    row["asset_key"]
                ),
                "draft_year": int(
                    numeric_value(
                        row["draft_year"]
                    )
                ),
                "round_number": int(
                    numeric_value(
                        row["round_number"]
                    )
                ),
                "claim_type": clean_text(
                    row.get(
                        "claim_type",
                        "",
                    )
                ),
                "structural_family": clean_text(
                    row.get(
                        "structural_family",
                        "",
                    )
                ),
                "mentions_lac": bool(
                    re.search(
                        TEAM_NAME_PATTERNS["LAC"],
                        text,
                        re.IGNORECASE,
                    )
                ),
                "mentions_phi": bool(
                    re.search(
                        TEAM_NAME_PATTERNS["PHI"],
                        text,
                        re.IGNORECASE,
                    )
                ),
                "mentions_bkn": bool(
                    re.search(
                        TEAM_NAME_PATTERNS["BKN"],
                        text,
                        re.IGNORECASE,
                    )
                ),
                "mentions_bos": bool(
                    re.search(
                        TEAM_NAME_PATTERNS["BOS"],
                        text,
                        re.IGNORECASE,
                    )
                ),
                "contains_swap_language": bool(
                    re.search(
                        r"\bswap\b",
                        text,
                        re.IGNORECASE,
                    )
                ),
                "contains_favorability_language": bool(
                    re.search(
                        r"\b(?:more favorable|less favorable|most favorable|"
                        r"least favorable|better of|worse of)\b",
                        text,
                        re.IGNORECASE,
                    )
                ),
                "contains_protection_language": bool(
                    re.search(
                        r"\b(?:protected|protection)\b",
                        text,
                        re.IGNORECASE,
                    )
                ),
                "contains_rollover_language": bool(
                    re.search(
                        r"\b(?:roll over|rollover|fallback|instead|"
                        r"extinguish|extinguished)\b",
                        text,
                        re.IGNORECASE,
                    )
                ),
                "contains_future_year_reference": bool(
                    re.search(
                        r"\b2029\b|\b2030\b|\b2031\b",
                        text,
                    )
                ),
            }
        )

    return pd.DataFrame(rows)


def build_asset_inventory(
    group_claims: pd.DataFrame,
    overlap_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for asset_key, group in overlap_claims.groupby(
        "asset_key",
        dropna=False,
    ):
        valued_mask = (
            group["valuation_status"]
            .fillna("")
            .astype(str)
            .str.startswith("valued_")
        )

        rows.append(
            {
                "asset_key": clean_text(asset_key),
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
                "group_claim_rows": int(
                    group[
                        "is_target_group_claim"
                    ].sum()
                ),
                "total_claim_rows_for_asset": len(group),
                "valued_claim_rows": int(
                    valued_mask.sum()
                ),
                "valuation_methods": join_unique(
                    group.loc[
                        valued_mask,
                        "valuation_method",
                    ]
                ),
                "valuation_statuses": join_unique(
                    group.loc[
                        valued_mask,
                        "valuation_status",
                    ]
                ),
                "candidate_beneficiary_teams": join_unique(
                    group.loc[
                        valued_mask,
                        "candidate_beneficiary_team",
                    ]
                    if "candidate_beneficiary_team"
                    in group.columns
                    else pd.Series(dtype=str)
                ),
                "obligation_groups": join_unique(
                    group[
                        "obligation_group_id"
                    ]
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        "asset_key"
    ).reset_index(drop=True)


def classify_structure(
    group_claims: pd.DataFrame,
    overlap_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
    relation_matrix: pd.DataFrame,
) -> tuple[str, bool, str]:
    unique_assets = int(
        group_claims["asset_key"]
        .astype(str)
        .nunique()
    )

    claim_rows = len(group_claims)

    rule_types = set(
        rule_fragments["rule_type"]
        .astype(str)
    )

    has_swap = (
        "swap_rule" in rule_types
        or relation_matrix[
            "contains_swap_language"
        ].any()
    )

    has_protection = (
        "protection_rule" in rule_types
        or relation_matrix[
            "contains_protection_language"
        ].any()
    )

    has_rollover = (
        "rollover_rule" in rule_types
        or relation_matrix[
            "contains_rollover_language"
        ].any()
        or relation_matrix[
            "contains_future_year_reference"
        ].any()
    )

    has_favorability = (
        "favorability_rule" in rule_types
        or relation_matrix[
            "contains_favorability_language"
        ].any()
    )

    additional_overlap_rows = (
        len(overlap_claims)
        - len(group_claims)
    )

    if (
        claim_rows == 4
        and unique_assets == 2
        and has_swap
        and has_protection
        and has_rollover
    ):
        return (
            "two_asset_multi_claim_swap_protection_rollover_structure_found",
            False,
            (
                "The complete two-asset, four-claim structure was found. "
                "The exact order of protections, rollover conditions, and "
                "swap or favorability rights must be reconstructed from "
                "the printed claim text before simulation."
                + (
                    " Additional claim rows share at least one source "
                    "asset and must be included in the accounting baseline."
                    if additional_overlap_rows > 0
                    else ""
                )
            ),
        )

    if (
        claim_rows == 4
        and unique_assets == 2
        and has_favorability
    ):
        return (
            "two_asset_multi_claim_favorability_structure_found",
            False,
            (
                "The two source assets and all four claims were found, "
                "but the claim ordering still requires manual parsing."
            ),
        )

    return (
        "group_structure_incomplete_or_changed",
        False,
        (
            "The current group no longer matches the expected four-claim, "
            "two-asset residual structure."
        ),
    )


def build_resolution_template(
    group_claims: pd.DataFrame,
    diagnostic_state: str,
    automatic_value_ready: bool,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "obligation_group_id": TARGET_GROUP_ID,
                "diagnostic_state": diagnostic_state,
                "automatic_value_ready": automatic_value_ready,
                "claim_ids": join_unique(
                    group_claims["claim_id"]
                ),
                "source_assets": join_unique(
                    group_claims["asset_key"]
                ),
                "confirmed_stage_1_rule": "",
                "confirmed_stage_2_rule": "",
                "confirmed_protection_ranges": "",
                "confirmed_rollover_or_fallback_rule": "",
                "confirmed_brooklyn_right": "",
                "confirmed_boston_right": "",
                "confirmed_philadelphia_right": "",
                "confirmed_clippers_retention_right": "",
                "source_verified": "",
                "source_as_of_date": "",
                "review_notes": "",
            }
        ]
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("2028 LAC-PHI TOP RESIDUAL GROUP DIAGNOSTIC")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        residual_groups,
        residual_claims,
    ) = load_inputs()

    target_group_row = validate_target_group(
        residual_groups
    )

    merged = merge_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    group_claims = select_group_claims(
        merged
    )

    overlap_claims = select_overlap_claims(
        merged=merged,
        group_claims=group_claims,
    )

    related_text = select_related_text(
        merged=merged,
        group_claims=group_claims,
    )

    rule_fragments = extract_rule_fragments(
        group_claims
    )

    relation_matrix = build_relation_matrix(
        group_claims
    )

    asset_inventory = build_asset_inventory(
        group_claims=group_claims,
        overlap_claims=overlap_claims,
    )

    (
        diagnostic_state,
        automatic_value_ready,
        diagnostic_note,
    ) = classify_structure(
        group_claims=group_claims,
        overlap_claims=overlap_claims,
        rule_fragments=rule_fragments,
        relation_matrix=relation_matrix,
    )

    group_claims["diagnostic_state"] = diagnostic_state
    group_claims[
        "automatic_value_ready"
    ] = automatic_value_ready
    group_claims[
        "diagnostic_note"
    ] = diagnostic_note

    group_claims.to_csv(
        GROUP_CLAIMS_PATH,
        index=False,
    )

    overlap_claims.to_csv(
        OVERLAP_CLAIMS_PATH,
        index=False,
    )

    related_text.to_csv(
        RELATED_TEXT_PATH,
        index=False,
    )

    rule_fragments.to_csv(
        RULE_FRAGMENTS_PATH,
        index=False,
    )

    relation_matrix.to_csv(
        CLAIM_RELATION_MATRIX_PATH,
        index=False,
    )

    asset_inventory.to_csv(
        ASSET_INVENTORY_PATH,
        index=False,
    )

    build_resolution_template(
        group_claims=group_claims,
        diagnostic_state=diagnostic_state,
        automatic_value_ready=automatic_value_ready,
    ).to_csv(
        RESOLUTION_TEMPLATE_PATH,
        index=False,
    )

    unresolved_group_claims = residual_claims.loc[
        residual_claims["claim_id"]
        .astype(str)
        .isin(
            set(
                group_claims[
                    "claim_id"
                ].astype(str)
            )
        )
        & residual_claims[
            "claim_unresolved"
        ]
        .fillna(False)
        .astype(bool)
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_group_id": TARGET_GROUP_ID,
        "review_order": int(
            numeric_value(
                target_group_row["review_order"]
            )
        ),
        "unique_asset_exposure_score": numeric_value(
            target_group_row[
                "unique_asset_exposure_score"
            ]
        ),
        "group_claim_rows": len(group_claims),
        "group_unresolved_claim_rows": len(
            unresolved_group_claims
        ),
        "group_unique_assets": int(
            group_claims["asset_key"]
            .astype(str)
            .nunique()
        ),
        "group_asset_keys": sorted(
            set(
                group_claims[
                    "asset_key"
                ].astype(str)
            )
        ),
        "overlap_claim_rows": len(overlap_claims),
        "additional_overlap_claim_rows": (
            len(overlap_claims)
            - len(group_claims)
        ),
        "related_text_rows": len(related_text),
        "rule_fragment_rows": len(rule_fragments),
        "diagnostic_state": diagnostic_state,
        "automatic_value_ready": (
            automatic_value_ready
        ),
        "diagnostic_note": diagnostic_note,
        "output_files": {
            "group_claims": str(
                GROUP_CLAIMS_PATH
            ),
            "overlap_claims": str(
                OVERLAP_CLAIMS_PATH
            ),
            "related_text_matches": str(
                RELATED_TEXT_PATH
            ),
            "rule_fragments": str(
                RULE_FRAGMENTS_PATH
            ),
            "claim_relation_matrix": str(
                CLAIM_RELATION_MATRIX_PATH
            ),
            "asset_inventory": str(
                ASSET_INVENTORY_PATH
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
    print("2028 LAC-PHI GROUP DIAGNOSTIC CREATED")
    print("=" * 80)
    print(f"Target group: {TARGET_GROUP_ID}")
    print(
        "Residual review order: "
        f"{int(numeric_value(target_group_row['review_order']))}"
    )
    print(
        "Unique asset exposure score: "
        f"{numeric_value(target_group_row['unique_asset_exposure_score']):.4f}"
    )
    print(
        f"Group claim rows: {len(group_claims):,}"
    )
    print(
        "Group unique assets: "
        f"{group_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Derived source assets: "
        + "|".join(
            sorted(
                set(
                    group_claims[
                        "asset_key"
                    ].astype(str)
                )
            )
        )
    )
    print(
        f"Overlap claim rows: {len(overlap_claims):,}"
    )
    print(
        "Additional overlap claim rows: "
        f"{len(overlap_claims) - len(group_claims):,}"
    )
    print(
        f"Related text rows: {len(related_text):,}"
    )
    print(
        "Rule fragments extracted: "
        f"{len(rule_fragments):,}"
    )
    print(f"Diagnostic state: {diagnostic_state}")
    print(
        f"Automatic value ready: {automatic_value_ready}"
    )
    print()

    print("GROUP CLAIM SUMMARY")
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
            "structural_family",
            "parsed_target_teams",
        ]
        if column in group_claims.columns
    ]

    print(
        group_claims[
            summary_columns
        ].to_string(index=False)
    )
    print()

    print("ASSET INVENTORY")
    print(
        asset_inventory.to_string(index=False)
    )
    print()

    print("CLAIM RELATION MATRIX")
    print(
        relation_matrix.to_string(index=False)
    )
    print()

    print("RULE FRAGMENTS")
    if rule_fragments.empty:
        print("No rule fragments were extracted.")
    else:
        print(
            rule_fragments.to_string(index=False)
        )
    print()

    print("GROUP CLAIM TEXT")
    for row in group_claims.itertuples(
        index=False
    ):
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
    print(GROUP_CLAIMS_PATH)
    print(OVERLAP_CLAIMS_PATH)
    print(RELATED_TEXT_PATH)
    print(RULE_FRAGMENTS_PATH)
    print(CLAIM_RELATION_MATRIX_PATH)
    print(ASSET_INVENTORY_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()