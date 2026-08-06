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
    "future-pick-hou-ind-mia-okc-2027-top-group-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_f60ebafc3d7d"

EXPECTED_SOURCE_ASSETS = {
    "2027_R1_HOU",
    "2027_R1_IND",
    "2027_R1_MIA",
    "2027_R1_OKC",
}

TARGET_TEAMS = {
    "HOU",
    "IND",
    "MIA",
    "OKC",
    "PHI",
    "NOP",
    "NYK",
    "SAS",
}

TEAM_NAME_PATTERNS = {
    "HOU": r"\bHouston\b",
    "IND": r"\bIndiana\b",
    "MIA": r"\bMiami\b",
    "OKC": r"\bOklahoma City\b",
    "PHI": r"\bPhiladelphia\b",
    "NOP": r"\bNew Orleans\b",
    "NYK": r"\bNew York\b",
    "SAS": r"\bSan Antonio\b",
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

RESIDUAL_GROUP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_dependency_group_audit_after_v9.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v9.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_group_claims_v1.csv"
)

OVERLAP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_overlap_claims_v1.csv"
)

RELATED_TEXT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_related_text_matches_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_rule_fragments_v1.csv"
)

CANDIDATE_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_candidate_edges_v1.csv"
)

SOURCE_MENTION_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_source_mention_matrix_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_hou_ind_mia_okc_2027_group_diagnostic_metadata_v1.json"
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


def join_unique(
    values: pd.Series,
) -> str:
    cleaned = sorted(
        {
            clean_text(
                value
            )
            for value in values
            if clean_text(
                value
            )
        }
    )

    return "|".join(
        cleaned
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
                + frame[
                    column
                ].fillna(
                    ""
                ).astype(
                    str
                )
            )

    return output.map(
        clean_text
    )


def parse_team_tokens(
    value: Any,
) -> set[str]:
    text = clean_text(
        value
    ).upper()

    if not text:
        return set()

    tokens = {
        token
        for token in re.split(
            r"[^A-Z]+",
            text,
        )
        if len(
            token
        )
        == 3
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
                    row[
                        column
                    ]
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
            teams.add(
                team
            )

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
                "Required HOU-IND-MIA-OKC diagnostic input was not found:\n"
                f"{path}"
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

    dependency_nodes = normalize_columns(
        pd.read_parquet(
            DEPENDENCY_NODES_PATH
        )
    )

    residual_groups = normalize_columns(
        pd.read_csv(
            RESIDUAL_GROUP_AUDIT_PATH
        )
    )

    residual_claims = normalize_columns(
        pd.read_csv(
            RESIDUAL_CLAIM_AUDIT_PATH
        )
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
        residual_groups,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V9 residual group audit",
    )

    require_columns(
        residual_claims,
        [
            "claim_id",
            "asset_key",
            "claim_unresolved",
        ],
        "V9 residual claim audit",
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
            subset=[
                "claim_id"
            ]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    output = output.merge(
        dependency_nodes[
            dependency_columns
        ].drop_duplicates(
            subset=[
                "claim_id"
            ]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
        suffixes=(
            "",
            "_dependency",
        ),
    )

    output[
        "_combined_text"
    ] = combined_text(
        output
    )

    output[
        "parsed_target_teams"
    ] = output.apply(
        lambda row: "|".join(
            sorted(
                row_team_tokens(
                    row
                )
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
        ].astype(
            str
        ).eq(
            TARGET_GROUP_ID
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected exactly one residual-group row for "
            f"{TARGET_GROUP_ID}; found {len(match)}."
        )

    row = match.iloc[
        0
    ]

    if int(
        numeric_value(
            row[
                "review_order"
            ]
        )
    ) != 1:
        raise RuntimeError(
            "The configured HOU-IND-MIA-OKC group is no longer "
            "review order 1. Rerun the V9 residual audit."
        )

    return row


def select_group_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    group_claims = merged.loc[
        merged[
            "obligation_group_id"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            TARGET_GROUP_ID
        )
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
    ).reset_index(
        drop=True
    )


def select_overlap_claims(
    merged: pd.DataFrame,
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    asset_keys = set(
        group_claims[
            "asset_key"
        ].astype(
            str
        )
    )

    overlap = merged.loc[
        merged[
            "asset_key"
        ].astype(
            str
        ).isin(
            asset_keys
        )
    ].copy()

    overlap[
        "is_target_group_claim"
    ] = overlap[
        "obligation_group_id"
    ].fillna(
        ""
    ).astype(
        str
    ).eq(
        TARGET_GROUP_ID
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
    ).reset_index(
        drop=True
    )


def select_related_text(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    pattern = re.compile(
        (
            r"Houston(?:'s|’s)?\s+2027\s+1st"
            r"|Indiana(?:'s|’s)?\s+2027\s+1st"
            r"|Miami(?:'s|’s)?\s+2027\s+1st"
            r"|Oklahoma City(?:'s|’s)?\s+2027\s+1st"
            r"|2027_R1_(?:HOU|IND|MIA|OKC)"
            r"|most\s+favorable"
            r"|second\s+most\s+favorable"
            r"|third\s+most\s+favorable"
            r"|least\s+favorable"
            r"|more\s+favorable"
            r"|less\s+favorable"
            r"|\bswap\b"
        ),
        re.IGNORECASE,
    )

    text_match = merged[
        "_combined_text"
    ].map(
        lambda text: bool(
            pattern.search(
                text
            )
        )
    )

    team_match = merged.apply(
        lambda row: bool(
            row_team_tokens(
                row
            )
            & TARGET_TEAMS
        ),
        axis=1,
    )

    related = merged.loc[
        text_match
        & team_match
    ].copy()

    related[
        "related_text_match"
    ] = True

    return related.sort_values(
        [
            "obligation_group_id",
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def extract_rule_fragments(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    patterns = {
        "most_favorable": (
            r"[^.;]*\bmost favorable\b[^.;]*"
        ),
        "second_most_favorable": (
            r"[^.;]*\bsecond[-\s]+most favorable\b[^.;]*"
        ),
        "third_most_favorable": (
            r"[^.;]*\bthird[-\s]+most favorable\b[^.;]*"
        ),
        "least_favorable": (
            r"[^.;]*\bleast favorable\b[^.;]*"
        ),
        "more_favorable": (
            r"[^.;]*\bmore favorable\b[^.;]*"
        ),
        "less_favorable": (
            r"[^.;]*\bless favorable\b[^.;]*"
        ),
        "swap_rule": (
            r"[^.;]*\b(?:right to swap|swap)\b[^.;]*"
        ),
        "protection_rule": (
            r"[^.;]*\b(?:protected|barred from selections)\b[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Philadelphia|to New Orleans|"
            r"to New York|to San Antonio|to Miami)\b[^.;]*"
        ),
    }

    for _, row in group_claims.iterrows():
        claim_id = clean_text(
            row[
                "claim_id"
            ]
        )

        asset_key = clean_text(
            row[
                "asset_key"
            ]
        )

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

            for match_order, match in enumerate(
                matches,
                start=1,
            ):
                rows.append(
                    {
                        "claim_id": (
                            claim_id
                        ),
                        "asset_key": (
                            asset_key
                        ),
                        "rule_type": (
                            rule_type
                        ),
                        "match_order": (
                            match_order
                        ),
                        "rule_fragment": clean_text(
                            match
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


def build_source_mention_matrix(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    source_patterns = {
        asset_key: TEAM_NAME_PATTERNS[
            asset_key.split(
                "_"
            )[
                -1
            ]
        ]
        for asset_key in EXPECTED_SOURCE_ASSETS
    }

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

        output_row = {
            "claim_id": clean_text(
                row[
                    "claim_id"
                ]
            ),
            "claim_asset_key": clean_text(
                row[
                    "asset_key"
                ]
            ),
        }

        for asset_key, pattern in sorted(
            source_patterns.items()
        ):
            output_row[
                f"mentions_{asset_key.lower()}"
            ] = bool(
                re.search(
                    pattern,
                    text,
                    re.IGNORECASE,
                )
            )

        output_row[
            "mentions_all_four_sources"
        ] = all(
            output_row[
                f"mentions_{asset_key.lower()}"
            ]
            for asset_key in sorted(
                EXPECTED_SOURCE_ASSETS
            )
        )

        rows.append(
            output_row
        )

    return pd.DataFrame(
        rows
    )


def build_candidate_edges(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in group_claims.iterrows():
        source_asset = clean_text(
            row.get(
                "asset_key",
                "",
            )
        )

        claim_id = clean_text(
            row.get(
                "claim_id",
                "",
            )
        )

        teams = row_team_tokens(
            row
        )

        for team in sorted(
            teams
        ):
            edge_type = (
                "claim_mentions_team"
            )

            confidence = (
                "text_or_field_reference"
            )

            beneficiary = clean_text(
                row.get(
                    "candidate_beneficiary_team",
                    "",
                )
            )

            destination = clean_text(
                row.get(
                    "single_destination_team",
                    "",
                )
            )

            destination_sequence = parse_team_tokens(
                row.get(
                    "destination_team_sequence",
                    "",
                )
            )

            if team == beneficiary:
                edge_type = (
                    "valued_candidate_beneficiary"
                )

                confidence = (
                    "valuation_layer"
                )
            elif team == destination:
                edge_type = (
                    "single_parsed_destination"
                )

                confidence = (
                    "claim_parser"
                )
            elif team in destination_sequence:
                edge_type = (
                    "destination_sequence_member"
                )

                confidence = (
                    "claim_parser"
                )

            rows.append(
                {
                    "claim_id": (
                        claim_id
                    ),
                    "source_asset_key": (
                        source_asset
                    ),
                    "destination_team": (
                        team
                    ),
                    "edge_type": (
                        edge_type
                    ),
                    "edge_confidence": (
                        confidence
                    ),
                }
            )

    return (
        pd.DataFrame(
            rows
        )
        .drop_duplicates()
        .sort_values(
            [
                "source_asset_key",
                "destination_team",
                "edge_type",
            ]
        )
        .reset_index(
            drop=True
        )
    )


def classify_structure(
    group_claims: pd.DataFrame,
    overlap_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
    source_mentions: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
    group_assets = set(
        group_claims[
            "asset_key"
        ].astype(
            str
        )
    )

    exact_source_set = (
        group_assets
        == EXPECTED_SOURCE_ASSETS
    )

    rule_types = set(
        rule_fragments[
            "rule_type"
        ].astype(
            str
        )
    )

    has_rank_language = bool(
        {
            "most_favorable",
            "least_favorable",
            "more_favorable",
            "less_favorable",
        }
        & rule_types
    )

    has_swap_language = (
        "swap_rule"
        in rule_types
        or group_claims[
            "claim_type"
        ].astype(
            str
        ).str.contains(
            "swap",
            case=False,
            regex=False,
        ).any()
    )

    all_sources_described_somewhere = bool(
        source_mentions[
            [
                column
                for column in source_mentions.columns
                if column.startswith(
                    "mentions_2027_r1_"
                )
            ]
        ].any(
            axis=0
        ).all()
    ) if not source_mentions.empty else False

    overlap_count = (
        len(
            overlap_claims
        )
        - len(
            group_claims
        )
    )

    if (
        exact_source_set
        and has_rank_language
        and has_swap_language
        and all_sources_described_somewhere
    ):
        return (
            "hybrid_ranked_pool_and_swap_chain_text_complete_sequence_parse_required",
            False,
            (
                "All four physical source assets and both ranking and "
                "swap language were found. The group is structurally "
                "complete, but the exact order of operations must be "
                "reconstructed from the claim texts before simulation."
                + (
                    " Additional claims share at least one source asset "
                    "and must be included in the accounting baseline."
                    if overlap_count
                    > 0
                    else ""
                )
            ),
        )

    if (
        exact_source_set
        and has_rank_language
        and all_sources_described_somewhere
    ):
        return (
            "four_asset_ranked_pool_parse_ready_no_swap_sequence_detected",
            True,
            (
                "All four source assets and rank-allocation language "
                "were found without a separate swap sequence."
            ),
        )

    if not exact_source_set:
        return (
            "configured_group_asset_set_mismatch",
            False,
            (
                "The group no longer contains exactly the expected "
                "Houston, Indiana, Miami, and Oklahoma City 2027 firsts."
            ),
        )

    return (
        "group_text_found_rule_structure_incomplete",
        False,
        (
            "The group claims were found, but the available text did not "
            "fully establish both the source set and allocation sequence."
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
                "obligation_group_id": (
                    TARGET_GROUP_ID
                ),
                "diagnostic_state": (
                    diagnostic_state
                ),
                "automatic_value_ready": (
                    automatic_value_ready
                ),
                "claim_ids": join_unique(
                    group_claims[
                        "claim_id"
                    ]
                ),
                "source_assets": join_unique(
                    group_claims[
                        "asset_key"
                    ]
                ),
                "confirmed_first_operation": "",
                "confirmed_second_operation": "",
                "confirmed_final_rank_order": "",
                "confirmed_swap_holder": "",
                "confirmed_swap_target": "",
                "confirmed_protection_rules": "",
                "confirmed_philadelphia_right": "",
                "confirmed_new_orleans_right": "",
                "confirmed_new_york_right": "",
                "confirmed_san_antonio_right": "",
                "confirmed_miami_right": "",
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
    print("HOU-IND-MIA-OKC 2027 TOP RESIDUAL GROUP DIAGNOSTIC")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
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
        merged
    )

    rule_fragments = extract_rule_fragments(
        group_claims
    )

    source_mentions = build_source_mention_matrix(
        group_claims
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
        source_mentions=source_mentions,
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

    candidate_edges.to_csv(
        CANDIDATE_EDGES_PATH,
        index=False,
    )

    source_mentions.to_csv(
        SOURCE_MENTION_MATRIX_PATH,
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
        residual_claims[
            "claim_id"
        ].astype(
            str
        ).isin(
            set(
                group_claims[
                    "claim_id"
                ].astype(
                    str
                )
            )
        )
        & residual_claims[
            "claim_unresolved"
        ].fillna(
            False
        ).astype(
            bool
        )
    ]

    group_asset_set = set(
        group_claims[
            "asset_key"
        ].astype(
            str
        )
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_group_id": (
            TARGET_GROUP_ID
        ),
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
            group_claims[
                "asset_key"
            ].astype(
                str
            ).nunique()
        ),
        "group_asset_set": sorted(
            group_asset_set
        ),
        "expected_asset_set_match": (
            group_asset_set
            == EXPECTED_SOURCE_ASSETS
        ),
        "overlap_claim_rows": len(
            overlap_claims
        ),
        "additional_overlap_claim_rows": (
            len(
                overlap_claims
            )
            - len(
                group_claims
            )
        ),
        "related_text_rows": len(
            related_text
        ),
        "rule_fragment_rows": len(
            rule_fragments
        ),
        "candidate_edges": len(
            candidate_edges
        ),
        "diagnostic_state": (
            diagnostic_state
        ),
        "automatic_value_ready": (
            automatic_value_ready
        ),
        "diagnostic_note": (
            diagnostic_note
        ),
        "output_files": {
            "group_claims": str(
                GROUP_CLAIMS_PATH
            ),
            "overlap_claims": str(
                OVERLAP_CLAIMS_PATH
            ),
            "related_text": str(
                RELATED_TEXT_PATH
            ),
            "rule_fragments": str(
                RULE_FRAGMENTS_PATH
            ),
            "candidate_edges": str(
                CANDIDATE_EDGES_PATH
            ),
            "source_mention_matrix": str(
                SOURCE_MENTION_MATRIX_PATH
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
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print("=" * 80)
    print("HOU-IND-MIA-OKC GROUP DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        f"Target group: "
        f"{TARGET_GROUP_ID}"
    )
    print(
        "Residual review order: "
        f"{int(numeric_value(target_group_row['review_order']))}"
    )
    print(
        "Unique asset exposure score: "
        f"{numeric_value(target_group_row['unique_asset_exposure_score']):.4f}"
    )
    print(
        f"Group claim rows: "
        f"{len(group_claims):,}"
    )
    print(
        "Group unique assets: "
        f"{group_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Expected four-asset set matched: "
        f"{group_asset_set == EXPECTED_SOURCE_ASSETS}"
    )
    print(
        f"Overlap claim rows: "
        f"{len(overlap_claims):,}"
    )
    print(
        "Additional overlap claim rows: "
        f"{len(overlap_claims) - len(group_claims):,}"
    )
    print(
        f"Related text rows: "
        f"{len(related_text):,}"
    )
    print(
        f"Rule fragments extracted: "
        f"{len(rule_fragments):,}"
    )
    print(
        f"Diagnostic state: "
        f"{diagnostic_state}"
    )
    print(
        f"Automatic value ready: "
        f"{automatic_value_ready}"
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
        ].to_string(
            index=False
        )
    )
    print()

    print("SOURCE MENTION MATRIX")
    print(
        source_mentions.to_string(
            index=False
        )
    )
    print()

    print("RULE FRAGMENTS")
    if rule_fragments.empty:
        print(
            "No rule fragments were extracted."
        )
    else:
        print(
            rule_fragments.to_string(
                index=False
            )
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
            if hasattr(
                row,
                column,
            ):
                value = clean_text(
                    getattr(
                        row,
                        column,
                        "",
                    )
                )

                if value:
                    print(
                        f"{column}: {value}"
                    )

    print()
    print("CANDIDATE EDGES")
    if candidate_edges.empty:
        print(
            "No candidate edges were parsed."
        )
    else:
        print(
            candidate_edges.to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(GROUP_CLAIMS_PATH)
    print(OVERLAP_CLAIMS_PATH)
    print(RELATED_TEXT_PATH)
    print(RULE_FRAGMENTS_PATH)
    print(CANDIDATE_EDGES_PATH)
    print(SOURCE_MENTION_MATRIX_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()