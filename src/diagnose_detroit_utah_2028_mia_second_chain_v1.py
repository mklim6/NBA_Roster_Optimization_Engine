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
    "future-pick-detroit-utah-mia-second-chain-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
    / "future_pick_claim_value_layer_2027_2029_v5_conditional_split_enriched.parquet"
)

BRANCH_LEDGER_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_conditional_branch_ledger_2027_2029_v1.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CHAIN_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_detroit_utah_2028_mia_second_chain_claims_v1.csv"
)

CHAIN_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_detroit_utah_2028_mia_second_candidate_edges_v1.csv"
)

MANUAL_RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_detroit_utah_2028_mia_second_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_detroit_utah_2028_mia_second_chain_diagnostic_metadata_v1.json"
)


TARGET_ASSET_KEY = "2028_R2_MIA"

TARGET_ORIGINATING_TEAM = "MIA"

TARGET_DRAFT_YEAR = 2028

TARGET_ROUND_NUMBER = 2

TARGET_CHAIN_TEAMS = {
    "DET",
    "UTA",
}

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


def boolean_value(
    value: Any,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    return (
        str(
            value
        )
        .strip()
        .lower()
        in {
            "true",
            "1",
            "yes",
            "y",
        }
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


def parse_team_tokens(
    value: Any,
) -> set[str]:
    text = clean_text(
        value
    ).upper()

    if not text:
        return set()

    tokens = re.split(
        r"[^A-Z]+",
        text,
    )

    return {
        token
        for token in tokens
        if len(
            token
        )
        == 3
    }


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


def mentioned_teams_from_row(
    row: pd.Series,
) -> set[str]:
    teams = set()

    for column in TEAM_COLUMNS:
        if column in row.index:
            teams.update(
                parse_team_tokens(
                    row[
                        column
                    ]
                )
            )

    return teams


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        BRANCH_LEDGER_PATH,
        DEPENDENCY_NODES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required Detroit-Utah diagnostic input was not found:\n"
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

    branches = normalize_columns(
        pd.read_parquet(
            BRANCH_LEDGER_PATH
        )
    )

    dependency_nodes = normalize_columns(
        pd.read_parquet(
            DEPENDENCY_NODES_PATH
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
        "V5 valuation layer",
    )

    require_columns(
        branches,
        [
            "fallback_asset_key",
            "branch_candidate_team_group",
            "branch_expected_value_score",
            "branch_allocation_status",
        ],
        "Conditional branch ledger",
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

    return (
        claims,
        valuations,
        branches,
        dependency_nodes,
    )


def merge_claim_context(
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
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
            "conditional_split_value_modeled_flag",
            "conditional_split_resolved_branch_value_score",
            "conditional_split_unresolved_branch_value_score",
            "conditional_split_allocation_status",
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

    merged = claims.merge(
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

    merged = merged.merge(
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

    merged[
        "_combined_text"
    ] = combined_text(
        merged
    )

    return merged


def select_chain_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    exact_asset = merged[
        "asset_key"
    ].astype(
        str
    ).eq(
        TARGET_ASSET_KEY
    )

    exact_origin_year_round = (
        pd.to_numeric(
            merged[
                "draft_year"
            ],
            errors="coerce",
        ).eq(
            TARGET_DRAFT_YEAR
        )
        & pd.to_numeric(
            merged[
                "round_number"
            ],
            errors="coerce",
        ).eq(
            TARGET_ROUND_NUMBER
        )
        & merged[
            "originating_team"
        ].astype(
            str
        ).eq(
            TARGET_ORIGINATING_TEAM
        )
    )

    text_pattern = re.compile(
        (
            r"(?:Miami(?:'s|’s)?\s+2028\s+"
            r"(?:second|2nd)[\s-]+round)"
            r"|(?:2028_R2_MIA)"
            r"|(?:Detroit\s+may\s+convey\s+this\s+pick\s+to\s+Utah)"
            r"|(?:Detroit\s+Outgoing)"
        ),
        re.IGNORECASE,
    )

    text_match = merged[
        "_combined_text"
    ].map(
        lambda text: bool(
            text_pattern.search(
                text
            )
        )
    )

    team_match = merged.apply(
        lambda row: bool(
            mentioned_teams_from_row(
                row
            )
            & TARGET_CHAIN_TEAMS
        ),
        axis=1,
    )

    candidate = merged.loc[
        exact_asset
        | exact_origin_year_round
        | text_match
        | (
            text_match
            & team_match
        )
    ].copy()

    candidate[
        "match_exact_asset_key"
    ] = exact_asset.loc[
        candidate.index
    ].astype(
        bool
    )

    candidate[
        "match_exact_origin_year_round"
    ] = exact_origin_year_round.loc[
        candidate.index
    ].astype(
        bool
    )

    candidate[
        "match_transaction_text"
    ] = text_match.loc[
        candidate.index
    ].astype(
        bool
    )

    candidate[
        "mentions_detroit_or_utah"
    ] = team_match.loc[
        candidate.index
    ].astype(
        bool
    )

    candidate[
        "parsed_team_tokens"
    ] = candidate.apply(
        lambda row: "|".join(
            sorted(
                mentioned_teams_from_row(
                    row
                )
            )
        ),
        axis=1,
    )

    return candidate.sort_values(
        [
            "match_exact_asset_key",
            "match_transaction_text",
            "claim_id",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_candidate_edges(
    chain_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for row in chain_claims.itertuples(
        index=False
    ):
        source_claim = str(
            getattr(
                row,
                "claim_id",
                "",
            )
        )

        asset = str(
            getattr(
                row,
                "asset_key",
                "",
            )
        )

        teams = set()

        for column in TEAM_COLUMNS:
            if hasattr(
                row,
                column,
            ):
                teams.update(
                    parse_team_tokens(
                        getattr(
                            row,
                            column,
                            "",
                        )
                    )
                )

        text = clean_text(
            getattr(
                row,
                "_combined_text",
                "",
            )
        )

        if re.search(
            r"\bDetroit\b",
            text,
            re.IGNORECASE,
        ):
            teams.add(
                "DET"
            )

        if re.search(
            r"\bUtah\b",
            text,
            re.IGNORECASE,
        ):
            teams.add(
                "UTA"
            )

        if re.search(
            r"\bCharlotte\b",
            text,
            re.IGNORECASE,
        ):
            teams.add(
                "CHA"
            )

        if re.search(
            r"\bMiami\b",
            text,
            re.IGNORECASE,
        ):
            teams.add(
                "MIA"
            )

        if not teams:
            rows.append(
                {
                    "claim_id": (
                        source_claim
                    ),
                    "asset_key": (
                        asset
                    ),
                    "source_node": (
                        asset
                        or source_claim
                    ),
                    "destination_team": "",
                    "edge_type": (
                        "no_team_edge_parsed"
                    ),
                    "edge_confidence": (
                        "none"
                    ),
                }
            )

            continue

        for team in sorted(
            teams
        ):
            edge_type = (
                "claim_mentions_team"
            )

            confidence = (
                "text_or_field_reference"
            )

            candidate_beneficiary = clean_text(
                getattr(
                    row,
                    "candidate_beneficiary_team",
                    "",
                )
            )

            single_destination = clean_text(
                getattr(
                    row,
                    "single_destination_team",
                    "",
                )
            )

            destination_sequence = clean_text(
                getattr(
                    row,
                    "destination_team_sequence",
                    "",
                )
            )

            if team == candidate_beneficiary:
                edge_type = (
                    "valued_candidate_beneficiary"
                )

                confidence = (
                    "valuation_layer"
                )
            elif team == single_destination:
                edge_type = (
                    "single_parsed_destination"
                )

                confidence = (
                    "claim_parser"
                )
            elif team in parse_team_tokens(
                destination_sequence
            ):
                edge_type = (
                    "destination_sequence_member"
                )

                confidence = (
                    "claim_parser"
                )
            elif (
                team == "UTA"
                and re.search(
                    r"Detroit\s+may\s+convey\s+this\s+pick\s+to\s+Utah",
                    text,
                    re.IGNORECASE,
                )
            ):
                edge_type = (
                    "explicit_possible_onward_conveyance"
                )

                confidence = (
                    "source_text"
                )

            rows.append(
                {
                    "claim_id": (
                        source_claim
                    ),
                    "asset_key": (
                        asset
                    ),
                    "source_node": (
                        asset
                        or source_claim
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

    return pd.DataFrame(
        rows
    ).drop_duplicates().sort_values(
        [
            "claim_id",
            "destination_team",
            "edge_type",
        ]
    ).reset_index(
        drop=True
    )


def classify_chain_state(
    chain_claims: pd.DataFrame,
    edges: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
    exact = chain_claims.loc[
        chain_claims[
            "match_exact_asset_key"
        ]
    ]

    utah_direct = chain_claims.loc[
        chain_claims[
            "candidate_beneficiary_team"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "UTA"
        )
        & chain_claims[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    det_direct = chain_claims.loc[
        chain_claims[
            "candidate_beneficiary_team"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "DET"
        )
        & chain_claims[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    explicit_utah_edge = edges.loc[
        edges[
            "destination_team"
        ].eq(
            "UTA"
        )
        & edges[
            "edge_type"
        ].eq(
            "explicit_possible_onward_conveyance"
        )
    ]

    if len(
        utah_direct
    ) == 1 and len(
        det_direct
    ) == 0:
        return (
            "single_utah_direct_owner_candidate_found",
            True,
            (
                "One directly valued Utah claim was found and no "
                "competing Detroit direct claim exists."
            ),
        )

    if len(
        det_direct
    ) == 1 and len(
        utah_direct
    ) == 0 and explicit_utah_edge.empty:
        return (
            "single_detroit_direct_owner_candidate_found",
            True,
            (
                "One directly valued Detroit claim was found and no "
                "onward Utah conveyance was detected."
            ),
        )

    if (
        len(
            exact
        )
        == 1
        and not explicit_utah_edge.empty
        and len(
            utah_direct
        )
        == 0
    ):
        return (
            "detroit_claim_with_unresolved_utah_onward_reference",
            False,
            (
                "The exact asset has a Detroit conditional claim, but "
                "the source explicitly permits onward conveyance to Utah "
                "and no separate ownership-resolving Utah claim was found."
            ),
        )

    if (
        len(
            utah_direct
        )
        > 0
        and len(
            det_direct
        )
        > 0
    ):
        return (
            "conflicting_detroit_and_utah_direct_claims",
            False,
            (
                "Both Detroit and Utah appear as direct candidates. "
                "Manual source resolution is required."
            ),
        )

    return (
        "chain_not_resolved_from_current_claim_layer",
        False,
        (
            "The existing claim and valuation layers do not establish "
            "one final candidate owner for the downstream branch."
        ),
    )


def build_resolution_template(
    chain_state: str,
    chain_claims: pd.DataFrame,
) -> pd.DataFrame:
    claim_ids = "|".join(
        sorted(
            set(
                chain_claims[
                    "claim_id"
                ].astype(
                    str
                )
            )
        )
    )

    return pd.DataFrame(
        [
            {
                "target_asset_key": (
                    TARGET_ASSET_KEY
                ),
                "current_chain_state": (
                    chain_state
                ),
                "candidate_claim_ids": (
                    claim_ids
                ),
                "confirmed_final_candidate_team": "",
                "confirmed_intermediate_team": "",
                "confirmed_onward_conveyance_condition": "",
                "confirmed_favorability_or_pool_rule": "",
                "confirmed_asset_share": "",
                "source_verified": "",
                "source_as_of_date": "",
                "review_notes": "",
            }
        ]
    )


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
    print("DETROIT-UTAH 2028 MIAMI SECOND-ROUND CHAIN DIAGNOSTIC")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        claims,
        valuations,
        branches,
        dependency_nodes,
    ) = load_inputs()

    merged = merge_claim_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    chain_claims = select_chain_claims(
        merged
    )

    edges = build_candidate_edges(
        chain_claims
    )

    target_branch = branches.loc[
        branches[
            "fallback_asset_key"
        ].astype(
            str
        ).eq(
            TARGET_ASSET_KEY
        )
        & branches[
            "branch_allocation_status"
        ].astype(
            str
        ).eq(
            "unresolved_downstream_conveyance_chain"
        )
    ]

    if len(
        target_branch
    ) != 1:
        raise ValueError(
            "Expected exactly one unresolved downstream branch for "
            f"{TARGET_ASSET_KEY}; found {len(target_branch)}."
        )

    unallocated_value = numeric_value(
        target_branch.iloc[
            0
        ][
            "branch_expected_value_score"
        ]
    )

    (
        chain_state,
        automatic_owner_ready,
        chain_note,
    ) = classify_chain_state(
        chain_claims=chain_claims,
        edges=edges,
    )

    chain_claims[
        "diagnostic_chain_state"
    ] = chain_state

    chain_claims[
        "automatic_final_owner_ready"
    ] = automatic_owner_ready

    chain_claims[
        "diagnostic_chain_note"
    ] = chain_note

    chain_claims[
        "unallocated_branch_value_score"
    ] = unallocated_value

    chain_claims.to_csv(
        CHAIN_CLAIMS_PATH,
        index=False,
    )

    edges.to_csv(
        CHAIN_EDGES_PATH,
        index=False,
    )

    build_resolution_template(
        chain_state=chain_state,
        chain_claims=chain_claims,
    ).to_csv(
        MANUAL_RESOLUTION_TEMPLATE_PATH,
        index=False,
    )

    exact_rows = int(
        chain_claims[
            "match_exact_asset_key"
        ].sum()
    )

    transaction_matches = int(
        chain_claims[
            "match_transaction_text"
        ].sum()
    )

    det_edges = int(
        edges[
            "destination_team"
        ].eq(
            "DET"
        ).sum()
    )

    uta_edges = int(
        edges[
            "destination_team"
        ].eq(
            "UTA"
        ).sum()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_asset_key": (
            TARGET_ASSET_KEY
        ),
        "unallocated_branch_value_score": (
            unallocated_value
        ),
        "candidate_claim_rows_found": len(
            chain_claims
        ),
        "exact_asset_rows_found": (
            exact_rows
        ),
        "transaction_text_matches_found": (
            transaction_matches
        ),
        "detroit_candidate_edges_found": (
            det_edges
        ),
        "utah_candidate_edges_found": (
            uta_edges
        ),
        "diagnostic_chain_state": (
            chain_state
        ),
        "automatic_final_owner_ready": (
            automatic_owner_ready
        ),
        "diagnostic_chain_note": (
            chain_note
        ),
        "output_files": {
            "chain_claims": str(
                CHAIN_CLAIMS_PATH
            ),
            "candidate_edges": str(
                CHAIN_EDGES_PATH
            ),
            "manual_resolution_template": str(
                MANUAL_RESOLUTION_TEMPLATE_PATH
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
    print("DETROIT-UTAH CHAIN DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        f"Target asset: "
        f"{TARGET_ASSET_KEY}"
    )
    print(
        "Unallocated downstream branch value: "
        f"{unallocated_value:.4f}"
    )
    print(
        f"Candidate claim rows found: "
        f"{len(chain_claims):,}"
    )
    print(
        f"Exact asset rows found: "
        f"{exact_rows:,}"
    )
    print(
        f"Transaction-text matches found: "
        f"{transaction_matches:,}"
    )
    print(
        f"Detroit candidate edges found: "
        f"{det_edges:,}"
    )
    print(
        f"Utah candidate edges found: "
        f"{uta_edges:,}"
    )
    print(
        f"Diagnostic chain state: "
        f"{chain_state}"
    )
    print(
        "Automatic final-owner assignment ready: "
        f"{automatic_owner_ready}"
    )
    print()

    print("CHAIN CLAIM SUMMARY")
    summary_columns = [
        column
        for column in [
            "claim_id",
            "asset_key",
            "claim_type",
            "resolution_status",
            "candidate_current_owner",
            "single_destination_team",
            "destination_team_sequence",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "automatic_exclusion_reason",
            "obligation_group_id",
            "structural_family",
            "match_exact_asset_key",
            "match_transaction_text",
            "parsed_team_tokens",
        ]
        if column in chain_claims.columns
    ]

    if chain_claims.empty:
        print(
            "No candidate chain claims were found."
        )
    else:
        print(
            chain_claims[
                summary_columns
            ].to_string(
                index=False
            )
        )

    print()
    print("CHAIN CLAIM TEXT")
    if chain_claims.empty:
        print(
            "No chain text was available."
        )
    else:
        for row in chain_claims.itertuples(
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
                    text = clean_text(
                        getattr(
                            row,
                            column,
                            "",
                        )
                    )

                    if text:
                        print(
                            f"{column}: {text}"
                        )

    print()
    print("CANDIDATE EDGES")
    if edges.empty:
        print(
            "No candidate edges were parsed."
        )
    else:
        print(
            edges.to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(CHAIN_CLAIMS_PATH)
    print(CHAIN_EDGES_PATH)
    print(MANUAL_RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()