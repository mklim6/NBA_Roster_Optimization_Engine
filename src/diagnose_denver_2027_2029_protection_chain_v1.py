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
    "future-pick-denver-2027-2029-chain-diagnostic-v1-2026-08-04"
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
    / "future_pick_claim_value_layer_2027_2029_v7_utah_pool_fully_integrated.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

REFINED_GROUPS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_groups_refined_2027_2029_v2.parquet"
)

ROLLOVER_MANUAL_REVIEW_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_rollover_manual_review_2027_2029_v3.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CHAIN_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_2029_chain_claims_v1.csv"
)

CHAIN_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_2029_chain_edges_v1.csv"
)

LADDER_STAGES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_2029_protection_ladder_stages_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_2029_chain_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_denver_2027_2029_chain_diagnostic_metadata_v1.json"
)


TARGET_ORIGIN_TEAM = "DEN"

TARGET_YEARS = {
    2027,
    2028,
    2029,
}

TARGET_CHAIN_TEAMS = {
    "DEN",
    "OKC",
    "LAC",
    "TOR",
}

TARGET_ASSET_KEYS = {
    "2027_R1_DEN",
    "2028_R1_DEN",
    "2029_R1_DEN",
    "2029_R2_DEN",
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


def text_blob(
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

    return {
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


def row_team_tokens(
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

    text = clean_text(
        row.get(
            "_text_blob",
            "",
        )
    )

    name_patterns = {
        "DEN": r"\bDenver\b",
        "OKC": r"\bOklahoma City\b",
        "LAC": r"\bL\.?A\.? Clippers\b|\bLos Angeles Clippers\b",
        "TOR": r"\bToronto\b",
    }

    for team, pattern in name_patterns.items():
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
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required Denver-chain input was not found:\n"
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

    refined_groups = (
        normalize_columns(
            pd.read_parquet(
                REFINED_GROUPS_PATH
            )
        )
        if REFINED_GROUPS_PATH.exists()
        else pd.DataFrame()
    )

    manual_review = (
        normalize_columns(
            pd.read_csv(
                ROLLOVER_MANUAL_REVIEW_PATH
            )
        )
        if ROLLOVER_MANUAL_REVIEW_PATH.exists()
        else pd.DataFrame()
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
        "V7 valuation layer",
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
        dependency_nodes,
        refined_groups,
        manual_review,
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
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
            "full_source_allocation_modeled_flag",
            "full_utah_pool_integrated_flag",
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
        "_text_blob"
    ] = text_blob(
        output
    )

    output[
        "_team_tokens"
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


def select_denver_chain_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    exact_asset = merged[
        "asset_key"
    ].astype(
        str
    ).isin(
        TARGET_ASSET_KEYS
    )

    exact_denver_year_round = (
        merged[
            "originating_team"
        ].astype(
            str
        ).eq(
            TARGET_ORIGIN_TEAM
        )
        & pd.to_numeric(
            merged[
                "draft_year"
            ],
            errors="coerce",
        ).isin(
            TARGET_YEARS
        )
        & pd.to_numeric(
            merged[
                "round_number"
            ],
            errors="coerce",
        ).isin(
            [
                1,
                2,
            ]
        )
    )

    text_pattern = re.compile(
        (
            r"Denver(?:'s|’s)?\s+(?:2027\s+)?1st\s+round"
            r"|Denver(?:'s|’s)?\s+1st\s+round\s+pick"
            r"|protected\s+for\s+selections\s+1-5\s+in\s+2027"
            r"|1-5\s+in\s+2028"
            r"|1-5\s+in\s+2029"
            r"|Denver\s+will\s+instead\s+convey\s+its\s+2029\s+2nd"
            r"|Oklahoma City\s+may\s+convey\s+the\s+2027\s+pick"
            r"|which\s+may\s+then\s+convey\s+this\s+pick\s+to\s+Toronto"
            r"|Oklahoma City Incoming"
            r"|L\.?A\.?\s+Clippers Incoming"
            r"|2027_R1_DEN"
            r"|2028_R1_DEN"
            r"|2029_R1_DEN"
            r"|2029_R2_DEN"
        ),
        re.IGNORECASE,
    )

    text_match = merged[
        "_text_blob"
    ].map(
        lambda text: bool(
            text_pattern.search(
                text
            )
        )
    )

    chain_team_match = merged.apply(
        lambda row: bool(
            row_team_tokens(
                row
            )
            & TARGET_CHAIN_TEAMS
        ),
        axis=1,
    )

    relevant = merged.loc[
        exact_asset
        | exact_denver_year_round
        | text_match
        | (
            chain_team_match
            & text_match
        )
    ].copy()

    relevant[
        "match_exact_asset_key"
    ] = exact_asset.loc[
        relevant.index
    ].astype(
        bool
    )

    relevant[
        "match_denver_origin_year"
    ] = exact_denver_year_round.loc[
        relevant.index
    ].astype(
        bool
    )

    relevant[
        "match_chain_text"
    ] = text_match.loc[
        relevant.index
    ].astype(
        bool
    )

    relevant[
        "parsed_chain_teams"
    ] = relevant[
        "_team_tokens"
    ]

    return relevant.sort_values(
        [
            "match_exact_asset_key",
            "match_chain_text",
            "draft_year",
            "round_number",
            "claim_id",
        ],
        ascending=[
            False,
            False,
            True,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )


def deduplicate_text(
    text: str,
) -> str:
    text = clean_text(
        text
    )

    if not text:
        return ""

    midpoint = len(
        text
    ) // 2

    if (
        len(
            text
        )
        % 2
        == 0
        and text[
            :midpoint
        ].strip()
        == text[
            midpoint:
        ].strip()
    ):
        return text[
            :midpoint
        ].strip()

    return text


def parse_ladder_stages(
    chain_claims: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    str,
]:
    candidate_texts = []

    for _, row in chain_claims.iterrows():
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

        if (
            "1-5 in 2027" in text
            and "1-5 in 2028" in text
            and "1-5 in 2029" in text
        ):
            candidate_texts.append(
                deduplicate_text(
                    text
                )
            )

    candidate_texts = sorted(
        set(
            candidate_texts
        ),
        key=len,
        reverse=True,
    )

    if not candidate_texts:
        return (
            pd.DataFrame(),
            "",
        )

    canonical_text = candidate_texts[
        0
    ]

    stages = []

    protection_matches = re.findall(
        (
            r"(\d+)\s*-\s*(\d+)\s+in\s+"
            r"(2027|2028|2029)"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    seen = set()

    for start_pick, end_pick, year in protection_matches:
        key = (
            int(
                year
            ),
            int(
                start_pick
            ),
            int(
                end_pick
            ),
            1,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        stages.append(
            {
                "stage_order": len(
                    stages
                )
                + 1,
                "draft_year": int(
                    year
                ),
                "round_number": 1,
                "originating_team": (
                    "DEN"
                ),
                "protection_start_pick": int(
                    start_pick
                ),
                "protection_end_pick": int(
                    end_pick
                ),
                "conveys_when": (
                    f"pick outside {start_pick}-{end_pick}"
                ),
                "fallback_if_protected": (
                    "next_ladder_stage"
                ),
            }
        )

    terminal_match = re.search(
        (
            r"Denver\s+will\s+instead\s+convey\s+its\s+"
            r"(2029)\s+(?:2nd|second)\s+round\s+pick"
        ),
        canonical_text,
        flags=re.IGNORECASE,
    )

    if terminal_match:
        stages.append(
            {
                "stage_order": len(
                    stages
                )
                + 1,
                "draft_year": int(
                    terminal_match.group(
                        1
                    )
                ),
                "round_number": 2,
                "originating_team": (
                    "DEN"
                ),
                "protection_start_pick": np.nan,
                "protection_end_pick": np.nan,
                "conveys_when": (
                    "all first-round stages failed"
                ),
                "fallback_if_protected": (
                    "terminal_asset"
                ),
            }
        )

    return (
        pd.DataFrame(
            stages
        ),
        canonical_text,
    )


def build_chain_edges(
    chain_claims: pd.DataFrame,
    canonical_text: str,
) -> pd.DataFrame:
    rows = []

    if canonical_text:
        rows.append(
            {
                "source_node": (
                    "DEN_MULTI_YEAR_OBLIGATION"
                ),
                "destination_node": (
                    "OKC"
                ),
                "edge_type": (
                    "base_candidate_beneficiary"
                ),
                "edge_condition": (
                    "first eligible Denver asset conveys"
                ),
                "edge_confidence": (
                    "explicit_source_text"
                ),
            }
        )

        if re.search(
            (
                r"Oklahoma City\s+may\s+convey\s+the\s+"
                r"2027\s+pick\s+to\s+the\s+L\.?A\.?\s+Clippers"
            ),
            canonical_text,
            re.IGNORECASE,
        ):
            rows.append(
                {
                    "source_node": (
                        "OKC"
                    ),
                    "destination_node": (
                        "LAC"
                    ),
                    "edge_type": (
                        "possible_onward_conveyance"
                    ),
                    "edge_condition": (
                        "applies to the 2027 Denver pick only"
                    ),
                    "edge_confidence": (
                        "explicit_source_text"
                    ),
                }
            )

        if re.search(
            (
                r"which\s+may\s+then\s+convey\s+this\s+"
                r"pick\s+to\s+Toronto"
            ),
            canonical_text,
            re.IGNORECASE,
        ):
            rows.append(
                {
                    "source_node": (
                        "LAC"
                    ),
                    "destination_node": (
                        "TOR"
                    ),
                    "edge_type": (
                        "possible_onward_conveyance"
                    ),
                    "edge_condition": (
                        "applies if Clippers receive the 2027 Denver pick"
                    ),
                    "edge_confidence": (
                        "explicit_source_text"
                    ),
                }
            )

    for _, row in chain_claims.iterrows():
        source_claim = clean_text(
            row.get(
                "claim_id",
                "",
            )
        )

        source_asset = clean_text(
            row.get(
                "asset_key",
                "",
            )
        )

        for column in [
            "single_destination_team",
            "destination_team_sequence",
            "candidate_beneficiary_team",
        ]:
            if column not in row.index:
                continue

            destinations = parse_team_tokens(
                row[
                    column
                ]
            )

            for destination in sorted(
                destinations
                & TARGET_CHAIN_TEAMS
            ):
                rows.append(
                    {
                        "source_node": (
                            source_asset
                            or source_claim
                        ),
                        "destination_node": (
                            destination
                        ),
                        "edge_type": (
                            f"parsed_{column}"
                        ),
                        "edge_condition": "",
                        "edge_confidence": (
                            "claim_or_valuation_field"
                        ),
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=[
                "source_node",
                "destination_node",
                "edge_type",
                "edge_condition",
                "edge_confidence",
            ]
        )

    return (
        pd.DataFrame(
            rows
        )
        .drop_duplicates()
        .sort_values(
            [
                "source_node",
                "destination_node",
                "edge_type",
            ]
        )
        .reset_index(
            drop=True
        )
    )


def classify_diagnostic(
    ladder_stages: pd.DataFrame,
    canonical_text: str,
    chain_edges: pd.DataFrame,
) -> tuple[
    str,
    bool,
    bool,
    str,
]:
    expected_stage_keys = {
        (
            2027,
            1,
        ),
        (
            2028,
            1,
        ),
        (
            2029,
            1,
        ),
        (
            2029,
            2,
        ),
    }

    parsed_stage_keys = set(
        zip(
            pd.to_numeric(
                ladder_stages[
                    "draft_year"
                ],
                errors="coerce",
            ).astype(
                int
            ),
            pd.to_numeric(
                ladder_stages[
                    "round_number"
                ],
                errors="coerce",
            ).astype(
                int
            ),
        )
    ) if not ladder_stages.empty else set()

    ladder_ready = (
        parsed_stage_keys
        == expected_stage_keys
    )

    okc_lac = bool(
        (
            chain_edges[
                "source_node"
            ].eq(
                "OKC"
            )
            & chain_edges[
                "destination_node"
            ].eq(
                "LAC"
            )
        ).any()
    ) if not chain_edges.empty else False

    lac_tor = bool(
        (
            chain_edges[
                "source_node"
            ].eq(
                "LAC"
            )
            & chain_edges[
                "destination_node"
            ].eq(
                "TOR"
            )
        ).any()
    ) if not chain_edges.empty else False

    downstream_chain_detected = (
        okc_lac
        and lac_tor
    )

    if (
        ladder_ready
        and downstream_chain_detected
    ):
        return (
            "ladder_value_ready_downstream_controller_unresolved",
            True,
            False,
            (
                "The four-stage Denver obligation can be valued on the "
                "joint simulation bank, but the 2027 branch cannot yet be "
                "assigned to one final candidate team because the exact "
                "OKC-to-Clippers and Clippers-to-Toronto controlling "
                "conditions are not resolved."
            ),
        )

    if ladder_ready:
        return (
            "ladder_value_ready_no_complete_downstream_chain_found",
            True,
            False,
            (
                "The multi-year ladder is parseable, but the current claim "
                "layer did not establish the complete downstream 2027 chain."
            ),
        )

    return (
        "denver_ladder_not_ready_for_automatic_valuation",
        False,
        False,
        (
            "The expected 2027, 2028, 2029 first-round stages and terminal "
            "2029 second-round fallback were not all parsed."
        ),
    )


def build_resolution_template(
    diagnostic_state: str,
    obligation_value_ready: bool,
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
                "target_obligation": (
                    "DEN_2027_2029_FIRST_LADDER_TO_2029_SECOND"
                ),
                "diagnostic_state": (
                    diagnostic_state
                ),
                "obligation_value_ready": (
                    obligation_value_ready
                ),
                "candidate_claim_ids": (
                    claim_ids
                ),
                "confirmed_2027_controller": "",
                "confirmed_okc_to_lac_condition": "",
                "confirmed_lac_to_tor_condition": "",
                "confirmed_2028_controller": "",
                "confirmed_2029_controller": "",
                "confirmed_terminal_second_controller": "",
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
    print("DENVER 2027-2029 PROTECTION-LADDER CHAIN DIAGNOSTIC")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        refined_groups,
        manual_review,
    ) = load_inputs()

    merged = merge_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    chain_claims = select_denver_chain_claims(
        merged
    )

    (
        ladder_stages,
        canonical_text,
    ) = parse_ladder_stages(
        chain_claims
    )

    chain_edges = build_chain_edges(
        chain_claims=chain_claims,
        canonical_text=canonical_text,
    )

    (
        diagnostic_state,
        obligation_value_ready,
        automatic_final_controller_ready,
        diagnostic_note,
    ) = classify_diagnostic(
        ladder_stages=ladder_stages,
        canonical_text=canonical_text,
        chain_edges=chain_edges,
    )

    chain_claims[
        "denver_chain_diagnostic_state"
    ] = (
        diagnostic_state
    )

    chain_claims[
        "obligation_value_ready"
    ] = (
        obligation_value_ready
    )

    chain_claims[
        "automatic_final_controller_ready"
    ] = (
        automatic_final_controller_ready
    )

    chain_claims[
        "diagnostic_note"
    ] = (
        diagnostic_note
    )

    chain_claims.to_csv(
        CHAIN_CLAIMS_PATH,
        index=False,
    )

    chain_edges.to_csv(
        CHAIN_EDGES_PATH,
        index=False,
    )

    ladder_stages.to_csv(
        LADDER_STAGES_PATH,
        index=False,
    )

    build_resolution_template(
        diagnostic_state=diagnostic_state,
        obligation_value_ready=obligation_value_ready,
        chain_claims=chain_claims,
    ).to_csv(
        RESOLUTION_TEMPLATE_PATH,
        index=False,
    )

    manual_match_count = 0

    if not manual_review.empty:
        manual_text = text_blob(
            manual_review
        )

        manual_match_count = int(
            manual_text.str.contains(
                r"Denver|2027_R1_DEN|2029_R2_DEN",
                case=False,
                regex=True,
                na=False,
            ).sum()
        )

    refined_group_count = 0

    if not refined_groups.empty:
        possible_columns = [
            column
            for column in [
                "obligation_group_id",
                "claim_ids_list",
                "originating_teams_list",
                "beneficiary_teams_list",
                "dependency_class",
                "refined_candidate_resolution_tier",
            ]
            if column in refined_groups.columns
        ]

        if possible_columns:
            refined_blob = (
                refined_groups[
                    possible_columns
                ]
                .fillna(
                    ""
                )
                .astype(
                    str
                )
                .agg(
                    " ".join,
                    axis=1,
                )
            )

            refined_group_count = int(
                refined_blob.str.contains(
                    r"DEN|OKC|LAC|TOR|2027_R1_DEN",
                    case=False,
                    regex=True,
                    na=False,
                ).sum()
            )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "candidate_claim_rows_found": len(
            chain_claims
        ),
        "parsed_ladder_stages": len(
            ladder_stages
        ),
        "chain_edges_found": len(
            chain_edges
        ),
        "manual_review_rows_matching_denver": (
            manual_match_count
        ),
        "refined_dependency_groups_matching_chain_terms": (
            refined_group_count
        ),
        "diagnostic_state": (
            diagnostic_state
        ),
        "obligation_value_ready": (
            obligation_value_ready
        ),
        "automatic_final_controller_ready": (
            automatic_final_controller_ready
        ),
        "diagnostic_note": (
            diagnostic_note
        ),
        "canonical_ladder_text": (
            canonical_text
        ),
        "output_files": {
            "chain_claims": str(
                CHAIN_CLAIMS_PATH
            ),
            "chain_edges": str(
                CHAIN_EDGES_PATH
            ),
            "ladder_stages": str(
                LADDER_STAGES_PATH
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
    print("DENVER CHAIN DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        f"Candidate claim rows found: "
        f"{len(chain_claims):,}"
    )
    print(
        f"Protection-ladder stages parsed: "
        f"{len(ladder_stages):,}"
    )
    print(
        f"Chain edges found: "
        f"{len(chain_edges):,}"
    )
    print(
        f"Diagnostic state: "
        f"{diagnostic_state}"
    )
    print(
        "Obligation value ready: "
        f"{obligation_value_ready}"
    )
    print(
        "Automatic final-controller assignment ready: "
        f"{automatic_final_controller_ready}"
    )
    print()

    print("PROTECTION LADDER")
    if ladder_stages.empty:
        print(
            "No complete ladder was parsed."
        )
    else:
        print(
            ladder_stages.to_string(
                index=False
            )
        )

    print()
    print("CHAIN CLAIM SUMMARY")
    summary_columns = [
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
            "match_exact_asset_key",
            "match_chain_text",
            "parsed_chain_teams",
        ]
        if column in chain_claims.columns
    ]

    if chain_claims.empty:
        print(
            "No candidate Denver-chain claims were found."
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
    print("CANONICAL LADDER TEXT")
    print(
        canonical_text
        if canonical_text
        else "No canonical ladder text was identified."
    )

    print()
    print("CHAIN CLAIM TEXT")
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
    print("CHAIN EDGES")
    if chain_edges.empty:
        print(
            "No chain edges were parsed."
        )
    else:
        print(
            chain_edges.to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(CHAIN_CLAIMS_PATH)
    print(CHAIN_EDGES_PATH)
    print(LADDER_STAGES_PATH)
    print(RESOLUTION_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()