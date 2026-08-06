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
    "future-pick-2029-dal-phx-top-residual-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_71f301b205d0"

TARGET_TEAMS = {
    "DAL",
    "PHX",
    "HOU",
    "BKN",
}

TEAM_NAME_PATTERNS = {
    "DAL": r"\bDallas\b",
    "PHX": r"\bPhoenix\b",
    "HOU": r"\bHouston\b",
    "BKN": r"\bBrooklyn\b",
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
    / "future_pick_claim_value_layer_2027_2029_v13_bos_mil_por_enriched.parquet"
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
    / "future_pick_residual_dependency_group_audit_after_v13.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v13.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_group_claims_v1.csv"
)

OVERLAP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_overlap_claims_v1.csv"
)

RELATED_TEXT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_related_text_matches_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_rule_fragments_v1.csv"
)

RELATION_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_relation_matrix_v1.csv"
)

ASSET_INVENTORY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_asset_inventory_v1.csv"
)

CANDIDATE_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_candidate_edges_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_dal_phx_diagnostic_metadata_v1.json"
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


def finite_or_zero(
    value: Any,
) -> float:
    number = numeric_value(value)
    return number if np.isfinite(number) else 0.0


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


def parse_team_tokens(
    value: Any,
) -> set[str]:
    text = clean_text(value).upper()

    if not text:
        return set()

    return {
        token
        for token in re.split(
            r"[^A-Z]+",
            text,
        )
        if len(token) == 3
    } & TARGET_TEAMS


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
                "Required DAL-PHX diagnostic input was not found:\n"
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
        "V13 valuation layer",
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
        "V13 residual group audit",
    )
    require_columns(
        residual_claims,
        [
            "claim_id",
            "asset_key",
            "claim_unresolved",
        ],
        "V13 residual claim audit",
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
            "The configured DAL-PHX group is no longer review order 1. "
            "Rerun the V12 residual audit first."
        )

    return row


def select_group_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    output = merged.loc[
        merged["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    ].copy()

    if output.empty:
        raise ValueError(
            "No claims were found for target group "
            f"{TARGET_GROUP_ID}."
        )

    return output.sort_values(
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

    output = merged.loc[
        merged["asset_key"]
        .astype(str)
        .isin(asset_keys)
    ].copy()

    output["is_target_group_claim"] = (
        output["obligation_group_id"]
        .fillna("")
        .astype(str)
        .eq(TARGET_GROUP_ID)
    )

    return output.sort_values(
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

    text = merged["_combined_text"]

    source_match = (
        text.str.contains(
            r"Dallas",
            case=False,
            regex=False,
            na=False,
        )
        | text.str.contains(
            r"Phoenix",
            case=False,
            regex=False,
            na=False,
        )
    )

    controller_match = (
        text.str.contains(
            r"Houston",
            case=False,
            regex=False,
            na=False,
        )
        | text.str.contains(
            r"Brooklyn",
            case=False,
            regex=False,
            na=False,
        )
    )

    year_round_match = (
        text.str.contains(
            r"2029",
            case=False,
            regex=False,
            na=False,
        )
        & text.str.contains(
            r"1st|first",
            case=False,
            regex=True,
            na=False,
        )
    )

    exact_asset_match = (
        merged["asset_key"]
        .astype(str)
        .isin(group_assets)
    )

    related = merged.loc[
        exact_asset_match
        | (
            source_match
            & controller_match
            & year_round_match
        )
    ].copy()

    related["match_exact_group_asset"] = (
        exact_asset_match.loc[
            related.index
        ].astype(bool)
    )

    related["match_source_and_controller_text"] = (
        (
            source_match
            & controller_match
            & year_round_match
        )
        .loc[
            related.index
        ]
        .astype(bool)
    )

    return related.sort_values(
        [
            "match_exact_group_asset",
            "match_source_and_controller_text",
            "obligation_group_id",
            "asset_key",
            "claim_id",
        ],
        ascending=[
            False,
            False,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)


def extract_rule_fragments(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    patterns = {
        "favorability_rule": (
            r"[^.;]*\b(?:more favorable|less favorable|most favorable|"
            r"least favorable|better of|worse of|two most favorable|"
            r"two least favorable)\b[^.;]*"
        ),
        "swap_rule": (
            r"[^.;]*\b(?:right to swap|swap)\b[^.;]*"
        ),
        "protection_rule": (
            r"[^.;]*\b(?:protected|protection)\b[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if|conditional)"
            r"\b[^.;]*"
        ),
        "rollover_rule": (
            r"[^.;]*\b(?:roll over|rollover|fallback|instead|"
            r"extinguish|extinguished)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Houston|to Brooklyn|"
            r"to Dallas|to Phoenix)\b[^.;]*"
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

            for match_order, fragment in enumerate(
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
                        "match_order": match_order,
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

        output = {
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
                    r"least favorable|better of|worse of|two most favorable|"
                    r"two least favorable)\b",
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
        }

        for team, pattern in TEAM_NAME_PATTERNS.items():
            output[
                f"mentions_{team.lower()}"
            ] = bool(
                re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                )
            )

        rows.append(output)

    return pd.DataFrame(rows)


def build_asset_inventory(
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

        baseline_value = 0.0

        for row in group.loc[
            valued_mask
        ].itertuples(index=False):
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

            if (
                method == "direct_asset_value"
                or status == "valued_direct_candidate"
            ):
                baseline_value += finite_or_zero(
                    getattr(
                        row,
                        "expected_total_candidate_asset_value_score",
                        np.nan,
                    )
                )

            if method == "single_year_protection_component":
                baseline_value += finite_or_zero(
                    getattr(
                        row,
                        "expected_transferred_value_score",
                        np.nan,
                    )
                )
                baseline_value += finite_or_zero(
                    getattr(
                        row,
                        "expected_retained_value_score",
                        np.nan,
                    )
                )

            if method == "simple_two_team_swap_option":
                baseline_value += finite_or_zero(
                    getattr(
                        row,
                        "expected_swap_option_value_score",
                        np.nan,
                    )
                )

        rows.append(
            {
                "asset_key": clean_text(
                    asset_key
                ),
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
                "target_group_claim_rows": int(
                    group[
                        "is_target_group_claim"
                    ].sum()
                ),
                "total_claim_rows_for_asset": len(
                    group
                ),
                "valued_claim_rows": int(
                    valued_mask.sum()
                ),
                "current_counted_baseline_value_score": (
                    baseline_value
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


def build_candidate_edges(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in group_claims.iterrows():
        teams = row_team_tokens(row)

        for team in sorted(teams):
            rows.append(
                {
                    "claim_id": clean_text(
                        row["claim_id"]
                    ),
                    "source_asset_key": clean_text(
                        row["asset_key"]
                    ),
                    "candidate_team": team,
                    "edge_basis": (
                        "parsed_field_or_claim_text"
                    ),
                }
            )

    return (
        pd.DataFrame(
            rows,
            columns=[
                "claim_id",
                "source_asset_key",
                "candidate_team",
                "edge_basis",
            ],
        )
        .drop_duplicates()
        .sort_values(
            [
                "source_asset_key",
                "candidate_team",
                "claim_id",
            ]
        )
        .reset_index(drop=True)
    )


def classify_structure(
    group_claims: pd.DataFrame,
    overlap_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
    relation_matrix: pd.DataFrame,
) -> tuple[str, bool, str]:
    claim_rows = len(
        group_claims
    )

    unique_assets = int(
        group_claims["asset_key"]
        .astype(str)
        .nunique()
    )

    rule_types = set(
        rule_fragments["rule_type"]
        .astype(str)
    )

    has_favorability = bool(
        "favorability_rule" in rule_types
        or relation_matrix[
            "contains_favorability_language"
        ].any()
    )

    has_swap = bool(
        "swap_rule" in rule_types
        or relation_matrix[
            "contains_swap_language"
        ].any()
    )

    has_protection = bool(
        "protection_rule" in rule_types
        or relation_matrix[
            "contains_protection_language"
        ].any()
    )

    has_rollover = bool(
        "rollover_rule" in rule_types
        or relation_matrix[
            "contains_rollover_language"
        ].any()
    )

    additional_overlap_rows = (
        len(overlap_claims)
        - len(group_claims)
    )

    if (
        claim_rows == 2
        and unique_assets == 2
        and has_favorability
        and not has_protection
        and not has_rollover
    ):
        return (
            "two_asset_favorability_pool_text_found",
            False,
            (
                "Both unresolved source assets and the complete "
                "favorability language were found. The full physical "
                "input set and final recipients must be reconstructed "
                "from the claim text before joint simulation."
                + (
                    " Additional claim rows share a source asset and "
                    "must be included in baseline accounting."
                    if additional_overlap_rows > 0
                    else ""
                )
                + (
                    " Swap language also appears and may indicate a "
                    "nested controller."
                    if has_swap
                    else ""
                )
            ),
        )

    if has_protection or has_rollover:
        return (
            "favorability_structure_with_conditional_branch_found",
            False,
            (
                "Protection or rollover language was found. Exact "
                "conditional branches must be parsed before valuation."
            ),
        )

    return (
        "group_structure_incomplete_or_changed",
        False,
        (
            "The current group no longer matches the expected "
            "two-claim, two-asset residual structure."
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
                "visible_source_assets": join_unique(
                    group_claims["asset_key"]
                ),
                "confirmed_full_physical_source_set": "",
                "confirmed_first_rank_recipient": "",
                "confirmed_second_rank_recipient": "",
                "confirmed_third_rank_recipient": "",
                "confirmed_fourth_rank_recipient": "",
                "confirmed_houston_right": "",
                "confirmed_brooklyn_right": "",
                "confirmed_dallas_retained_right": "",
                "confirmed_phoenix_retained_right": "",
                "confirmed_protection_ranges": "",
                "confirmed_rollover_or_fallback_rule": "",
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
    print("2029 DAL-PHX TOP RESIDUAL GROUP DIAGNOSTIC")
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
        overlap_claims
    )

    candidate_edges = build_candidate_edges(
        group_claims
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

    group_claims[
        "diagnostic_state"
    ] = diagnostic_state
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
        RELATION_MATRIX_PATH,
        index=False,
    )
    asset_inventory.to_csv(
        ASSET_INVENTORY_PATH,
        index=False,
    )
    candidate_edges.to_csv(
        CANDIDATE_EDGES_PATH,
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
                target_group_row[
                    "review_order"
                ]
            )
        ),
        "unique_asset_exposure_score": numeric_value(
            target_group_row[
                "unique_asset_exposure_score"
            ]
        ),
        "group_claim_rows": len(
            group_claims
        ),
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
        "overlap_claim_rows": len(
            overlap_claims
        ),
        "additional_overlap_claim_rows": (
            len(overlap_claims)
            - len(group_claims)
        ),
        "related_text_rows": len(
            related_text
        ),
        "rule_fragment_rows": len(
            rule_fragments
        ),
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
            "relation_matrix": str(
                RELATION_MATRIX_PATH
            ),
            "asset_inventory": str(
                ASSET_INVENTORY_PATH
            ),
            "candidate_edges": str(
                CANDIDATE_EDGES_PATH
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
    print("2029 DAL-PHX GROUP DIAGNOSTIC CREATED")
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
    print(
        f"Diagnostic state: {diagnostic_state}"
    )
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

    print("RELATION MATRIX")
    print(
        relation_matrix.to_string(index=False)
    )
    print()

    print("CANDIDATE EDGES")
    if candidate_edges.empty:
        print(
            "No candidate edges were parsed."
        )
    else:
        print(
            candidate_edges.to_string(index=False)
        )
    print()

    print("RULE FRAGMENTS")
    if rule_fragments.empty:
        print(
            "No rule fragments were extracted."
        )
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
                    getattr(
                        row,
                        column,
                        "",
                    )
                )

                if value:
                    print(f"{column}: {value}")

    print()
    print("RELATED TEXT MATCHES")
    related_columns = [
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
            "obligation_group_id",
            "structural_family",
            "match_exact_group_asset",
            "match_source_and_controller_text",
        ]
        if column in related_text.columns
    ]

    if related_text.empty:
        print(
            "No related connected claims were found."
        )
    else:
        print(
            related_text[
                related_columns
            ].head(50).to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(GROUP_CLAIMS_PATH)
    print(OVERLAP_CLAIMS_PATH)
    print(RELATED_TEXT_PATH)
    print(RULE_FRAGMENTS_PATH)
    print(RELATION_MATRIX_PATH)
    print(ASSET_INVENTORY_PATH)
    print(CANDIDATE_EDGES_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()