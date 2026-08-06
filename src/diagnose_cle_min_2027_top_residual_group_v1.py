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
    "future-pick-cle-min-2027-top-residual-group-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_a1a4abc01bb0"

TARGET_ASSET_KEYS = {
    "2027_R1_CLE",
    "2027_R1_MIN",
}

TARGET_TEAMS = {
    "CLE",
    "MIN",
    "MEM",
    "UTA",
    "PHX",
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
    / "future_pick_claim_value_layer_2027_2029_v8_denver_joint_enriched.parquet"
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
    / "future_pick_residual_dependency_group_audit_after_v8.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v8.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_group_claims_v1.csv"
)

OVERLAP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_overlap_claims_v1.csv"
)

RELATED_TEXT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_related_text_matches_v1.csv"
)

CANDIDATE_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_candidate_edges_v1.csv"
)

RULE_EXTRACTION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_rule_extraction_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_cle_min_2027_group_diagnostic_metadata_v1.json"
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

TEAM_NAME_PATTERNS = {
    "CLE": r"\bCleveland\b",
    "MIN": r"\bMinnesota\b",
    "MEM": r"\bMemphis\b",
    "UTA": r"\bUtah\b",
    "PHX": r"\bPhoenix\b",
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
                "Required CLE-MIN diagnostic input was not found:\n"
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
        "V8 valuation layer",
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
        "Residual group audit",
    )

    require_columns(
        residual_claims,
        [
            "claim_id",
            "asset_key",
            "claim_unresolved",
        ],
        "Residual claim audit",
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
            "The configured CLE-MIN group is no longer review order 1. "
            "Rerun the residual audit before using this diagnostic."
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
            r"Cleveland(?:'s|’s)?\s+2027\s+1st"
            r"|Minnesota(?:'s|’s)?\s+2027\s+1st"
            r"|2027_R1_CLE"
            r"|2027_R1_MIN"
            r"|more\s+favorable"
            r"|less\s+favorable"
            r"|least\s+favorable"
            r"|most\s+favorable"
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


def extract_rules(
    group_claims: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    str,
]:
    texts = []

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

        if text:
            texts.append(
                text
            )

    unique_texts = sorted(
        set(
            texts
        ),
        key=len,
        reverse=True,
    )

    canonical_text = (
        unique_texts[
            0
        ]
        if unique_texts
        else ""
    )

    direction_matches = re.findall(
        (
            r"\b(more favorable|less favorable|least favorable|"
            r"most favorable|better of|worse of)\b"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    protection_matches = re.findall(
        (
            r"protected\s+for\s+selections?\s+"
            r"(\d+)\s*-\s*(\d+)"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    single_pick_protections = re.findall(
        (
            r"protected\s+for\s+selection\s+(\d+)"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    destination_phrases = re.findall(
        (
            r"(?:to|receive|receives|convey(?:ed)?)\s+"
            r"(Cleveland|Minnesota|Memphis|Utah|Phoenix)"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    rules = [
        {
            "rule_type": (
                "favorability_direction"
            ),
            "parsed_value": "|".join(
                sorted(
                    {
                        match.lower()
                        for match in direction_matches
                    }
                )
            ),
            "parse_success": bool(
                direction_matches
            ),
        },
        {
            "rule_type": (
                "protected_ranges"
            ),
            "parsed_value": "|".join(
                f"{start}-{end}"
                for start, end in protection_matches
            ),
            "parse_success": bool(
                protection_matches
            ),
        },
        {
            "rule_type": (
                "single_pick_protections"
            ),
            "parsed_value": "|".join(
                single_pick_protections
            ),
            "parse_success": bool(
                single_pick_protections
            ),
        },
        {
            "rule_type": (
                "destination_team_names"
            ),
            "parsed_value": "|".join(
                sorted(
                    {
                        match.upper()
                        for match in destination_phrases
                    }
                )
            ),
            "parse_success": bool(
                destination_phrases
            ),
        },
        {
            "rule_type": (
                "source_asset_mentions"
            ),
            "parsed_value": "|".join(
                sorted(
                    asset_key
                    for asset_key in TARGET_ASSET_KEYS
                    if asset_key.split(
                        "_"
                    )[
                        -1
                    ]
                    in row_team_tokens(
                        pd.Series(
                            {
                                "_combined_text": (
                                    canonical_text
                                )
                            }
                        )
                    )
                )
            ),
            "parse_success": all(
                team
                in row_team_tokens(
                    pd.Series(
                        {
                            "_combined_text": (
                                canonical_text
                            )
                        }
                    )
                )
                for team in [
                    "CLE",
                    "MIN",
                ]
            ),
        },
        {
            "rule_type": (
                "swap_language_present"
            ),
            "parsed_value": str(
                bool(
                    re.search(
                        r"\bswap\b",
                        canonical_text,
                        re.IGNORECASE,
                    )
                )
            ),
            "parse_success": True,
        },
        {
            "rule_type": (
                "conditional_language_present"
            ),
            "parsed_value": str(
                bool(
                    re.search(
                        r"\bif\b|\bprovided\b|\bunless\b|\bconditional\b",
                        canonical_text,
                        re.IGNORECASE,
                    )
                )
            ),
            "parse_success": True,
        },
    ]

    return (
        pd.DataFrame(
            rules
        ),
        canonical_text,
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


def classify_readiness(
    group_claims: pd.DataFrame,
    overlap_claims: pd.DataFrame,
    rules: pd.DataFrame,
    canonical_text: str,
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

    has_two_target_assets = (
        TARGET_ASSET_KEYS
        <= group_assets
    )

    direction_row = rules.loc[
        rules[
            "rule_type"
        ].eq(
            "favorability_direction"
        )
    ]

    has_direction = (
        len(
            direction_row
        )
        == 1
        and bool(
            direction_row.iloc[
                0
            ][
                "parse_success"
            ]
        )
    )

    destination_rows = group_claims[
        "destination_team_sequence"
    ] if (
        "destination_team_sequence"
        in group_claims.columns
    ) else pd.Series(
        "",
        index=group_claims.index,
    )

    destination_tokens = set()

    for value in destination_rows:
        destination_tokens.update(
            parse_team_tokens(
                value
            )
        )

    overlap_count = len(
        overlap_claims
    ) - len(
        group_claims
    )

    if (
        has_two_target_assets
        and has_direction
        and destination_tokens
    ):
        return (
            "joint_two_asset_favorability_rule_parse_ready",
            True,
            (
                "Both physical assets, favorability language, and "
                "destination teams were found. A joint simulation can "
                "be built next, but overlap claims must be included in "
                "the accounting baseline."
                if overlap_count
                > 0
                else
                "Both physical assets, favorability language, and "
                "destination teams were found. The group is ready for "
                "a joint simulation-based valuation."
            ),
        )

    if canonical_text:
        return (
            "group_text_found_rule_requires_manual_parse",
            False,
            (
                "Canonical source text was found, but one or more of the "
                "two source assets, comparison direction, or destination "
                "teams were not parsed reliably."
            ),
        )

    return (
        "group_source_text_missing",
        False,
        (
            "No usable canonical source text was found for the group."
        ),
    )


def build_resolution_template(
    group_claims: pd.DataFrame,
    diagnostic_state: str,
    joint_value_ready: bool,
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
                "joint_value_ready": (
                    joint_value_ready
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
                "confirmed_comparison_direction": "",
                "confirmed_primary_beneficiary": "",
                "confirmed_secondary_beneficiary": "",
                "confirmed_protection_rules": "",
                "confirmed_swap_sequence": "",
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
    print("CLE-MIN 2027 TOP RESIDUAL GROUP DIAGNOSTIC")
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

    (
        rules,
        canonical_text,
    ) = extract_rules(
        group_claims
    )

    candidate_edges = build_candidate_edges(
        group_claims
    )

    (
        diagnostic_state,
        joint_value_ready,
        diagnostic_note,
    ) = classify_readiness(
        group_claims=group_claims,
        overlap_claims=overlap_claims,
        rules=rules,
        canonical_text=canonical_text,
    )

    group_claims[
        "diagnostic_state"
    ] = diagnostic_state

    group_claims[
        "joint_value_ready"
    ] = joint_value_ready

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

    candidate_edges.to_csv(
        CANDIDATE_EDGES_PATH,
        index=False,
    )

    rules.to_csv(
        RULE_EXTRACTION_PATH,
        index=False,
    )

    build_resolution_template(
        group_claims=group_claims,
        diagnostic_state=diagnostic_state,
        joint_value_ready=joint_value_ready,
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
        "overlap_claim_rows": len(
            overlap_claims
        ),
        "related_text_rows": len(
            related_text
        ),
        "candidate_edges": len(
            candidate_edges
        ),
        "diagnostic_state": (
            diagnostic_state
        ),
        "joint_value_ready": (
            joint_value_ready
        ),
        "diagnostic_note": (
            diagnostic_note
        ),
        "canonical_text": (
            canonical_text
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
            "candidate_edges": str(
                CANDIDATE_EDGES_PATH
            ),
            "rule_extraction": str(
                RULE_EXTRACTION_PATH
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
    print("CLE-MIN GROUP DIAGNOSTIC CREATED")
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
        f"Overlap claim rows: "
        f"{len(overlap_claims):,}"
    )
    print(
        f"Related text rows: "
        f"{len(related_text):,}"
    )
    print(
        f"Diagnostic state: "
        f"{diagnostic_state}"
    )
    print(
        f"Joint value ready: "
        f"{joint_value_ready}"
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

    print("RULE EXTRACTION")
    print(
        rules.to_string(
            index=False
        )
    )
    print()

    print("CANONICAL GROUP TEXT")
    print(
        canonical_text
        if canonical_text
        else "No canonical group text was identified."
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
    print(CANDIDATE_EDGES_PATH)
    print(RULE_EXTRACTION_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()
