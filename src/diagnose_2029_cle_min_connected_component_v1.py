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
    "future-pick-2029-cle-min-connected-component-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_8fcf36a467d0"

TARGET_TEAMS = {
    "CLE",
    "MIN",
    "CHA",
    "PHX",
    "UTA",
}

TEAM_NAME_PATTERNS = {
    "CLE": r"\bCleveland\b",
    "MIN": r"\bMinnesota\b",
    "CHA": r"\bCharlotte\b",
    "PHX": r"\bPhoenix\b",
    "UTA": r"\bUtah\b",
}

TEAM_LONG_NAME_TO_CODE = {
    "cleveland": "CLE",
    "minnesota": "MIN",
    "charlotte": "CHA",
    "phoenix": "PHX",
    "utah": "UTA",
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
    / "future_pick_claim_value_layer_2027_2029_v14_dal_phx_hou_enriched.parquet"
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
    / "future_pick_residual_dependency_group_audit_after_v14.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v14.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_group_claims_v1.csv"
)

CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_connected_claims_v1.csv"
)

CONNECTED_ASSETS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_connected_assets_v1.csv"
)

TEXT_MATCHES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_text_matches_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_rule_fragments_v1.csv"
)

CLAUSE_TABLE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_clause_table_v1.csv"
)

SOURCE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_physical_source_candidates_v1.csv"
)

TEAM_MENTION_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_team_mention_matrix_v1.csv"
)

GROUP_RELATIONSHIP_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_group_relationships_v1.csv"
)

BASELINE_COMPONENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_existing_baseline_components_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_cle_min_diagnostic_metadata_v1.json"
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

VALUATION_COLUMNS = [
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


def normalized_text(
    value: Any,
) -> str:
    text = clean_text(value).lower()
    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )
    return re.sub(
        r"\s+",
        " ",
        text,
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
        "V14 valuation layer",
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
        "V14 residual group audit",
    )

    require_columns(
        residual_claims,
        [
            "claim_id",
            "asset_key",
            "claim_unresolved",
        ],
        "V14 residual claim audit",
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
        for column in VALUATION_COLUMNS
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

    output["_combined_text"] = combined_text(
        output
    )

    output["_normalized_text"] = output[
        "_combined_text"
    ].map(
        normalized_text
    )

    output["parsed_target_teams"] = output.apply(
        lambda row: "|".join(
            sorted(
                row_team_tokens(row)
            )
        ),
        axis=1,
    )

    output["parsed_target_team_count"] = (
        output[
            "parsed_target_teams"
        ]
        .map(
            lambda value: len(
                [
                    token
                    for token in str(value).split("|")
                    if token
                ]
            )
        )
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
        .eq(
            TARGET_GROUP_ID
        )
    ]

    if len(match) != 1:
        raise ValueError(
            "Expected exactly one residual-group row for "
            f"{TARGET_GROUP_ID}; found {len(match)}."
        )

    row = match.iloc[0]

    if int(
        numeric_value(
            row[
                "review_order"
            ]
        )
    ) != 1:
        raise RuntimeError(
            "The configured CLE-MIN group is no longer review order 1. "
            "Rerun the V14 residual audit first."
        )

    return row


def select_group_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    output = merged.loc[
        merged[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(str)
        .eq(
            TARGET_GROUP_ID
        )
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
    ).reset_index(
        drop=True
    )


def build_seed_information(
    group_claims: pd.DataFrame,
) -> tuple[
    set[str],
    set[str],
    set[str],
]:
    seed_assets = set(
        group_claims[
            "asset_key"
        ].astype(str)
    )

    seed_texts = {
        normalized_text(value)
        for value in group_claims[
            "_combined_text"
        ]
        if normalized_text(value)
    }

    seed_teams = set()

    for _, row in group_claims.iterrows():
        seed_teams.update(
            row_team_tokens(
                row
            )
        )

    return (
        seed_assets,
        seed_texts,
        seed_teams,
    )


def select_connected_claims(
    merged: pd.DataFrame,
    seed_assets: set[str],
    seed_texts: set[str],
    seed_teams: set[str],
) -> pd.DataFrame:
    exact_asset_match = (
        merged[
            "asset_key"
        ]
        .astype(str)
        .isin(
            seed_assets
        )
    )

    exact_text_match = (
        merged[
            "_normalized_text"
        ]
        .astype(str)
        .isin(
            seed_texts
        )
    )

    year_round_match = (
        pd.to_numeric(
            merged[
                "draft_year"
            ],
            errors="coerce",
        ).eq(
            2029
        )
        & pd.to_numeric(
            merged[
                "round_number"
            ],
            errors="coerce",
        ).eq(
            1
        )
    )

    multi_team_text_match = (
        merged[
            "parsed_target_team_count"
        ]
        .ge(
            3
        )
    )

    seed_team_asset_match = (
        year_round_match
        & merged[
            "originating_team"
        ]
        .astype(str)
        .isin(
            seed_teams
        )
    )

    group_match = (
        merged[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(str)
        .eq(
            TARGET_GROUP_ID
        )
    )

    selected = merged.loc[
        group_match
        | exact_asset_match
        | exact_text_match
        | (
            year_round_match
            & multi_team_text_match
        )
        | seed_team_asset_match
    ].copy()

    selected[
        "match_target_group"
    ] = group_match.loc[
        selected.index
    ].astype(bool)

    selected[
        "match_seed_asset"
    ] = exact_asset_match.loc[
        selected.index
    ].astype(bool)

    selected[
        "match_exact_normalized_text"
    ] = exact_text_match.loc[
        selected.index
    ].astype(bool)

    selected[
        "match_multi_target_team_text"
    ] = (
        (
            year_round_match
            & multi_team_text_match
        )
        .loc[
            selected.index
        ]
        .astype(bool)
    )

    selected[
        "match_seed_team_2029_first"
    ] = seed_team_asset_match.loc[
        selected.index
    ].astype(bool)

    return selected.sort_values(
        [
            "match_target_group",
            "match_exact_normalized_text",
            "match_seed_asset",
            "obligation_group_id",
            "asset_key",
            "claim_id",
        ],
        ascending=[
            False,
            False,
            False,
            True,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )


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
            r"[^.;]*\b(?:protected|protection|top[- ]?\d+|"
            r"selections?\s+\d+\s*(?:through|-|to)\s*\d+)\b[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if|conditional)"
            r"\b[^.;]*"
        ),
        "rollover_rule": (
            r"[^.;]*\b(?:roll over|rollover|fallback|instead|"
            r"extinguish|extinguished|defer|deferred|convey in)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Charlotte|to Phoenix|"
            r"to Utah|to Cleveland|to Minnesota)\b[^.;]*"
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
                            row[
                                "claim_id"
                            ]
                        ),
                        "asset_key": clean_text(
                            row[
                                "asset_key"
                            ]
                        ),
                        "rule_type": (
                            rule_type
                        ),
                        "match_order": (
                            match_order
                        ),
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


def split_clauses(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

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

        clauses = [
            clean_text(value)
            for value in re.split(
                r"(?<=[.;])\s+|\s+\[(?=[^\]]+\]$)",
                text,
            )
            if clean_text(value)
        ]

        for order, clause in enumerate(
            clauses,
            start=1,
        ):
            teams = [
                team
                for team, pattern in TEAM_NAME_PATTERNS.items()
                if re.search(
                    pattern,
                    clause,
                    re.IGNORECASE,
                )
            ]

            rows.append(
                {
                    "claim_id": clean_text(
                        row[
                            "claim_id"
                        ]
                    ),
                    "asset_key": clean_text(
                        row[
                            "asset_key"
                        ]
                    ),
                    "clause_order": order,
                    "mentioned_target_teams": "|".join(
                        sorted(
                            teams
                        )
                    ),
                    "contains_favorability": bool(
                        re.search(
                            r"\b(?:more favorable|less favorable|"
                            r"most favorable|least favorable|better of|"
                            r"worse of)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_swap": bool(
                        re.search(
                            r"\bswap\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_protection": bool(
                        re.search(
                            r"\b(?:protected|protection|top[- ]?\d+)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_rollover": bool(
                        re.search(
                            r"\b(?:roll over|rollover|fallback|instead|"
                            r"extinguish|extinguished|defer|deferred)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "clause_text": clause,
                }
            )

    return pd.DataFrame(
        rows
    )


def extract_source_candidates(
    group_claims: pd.DataFrame,
    all_claims: pd.DataFrame,
) -> pd.DataFrame:
    combined = " ".join(
        group_claims[
            "_combined_text"
        ]
        .fillna("")
        .astype(str)
        .tolist()
    )

    discovered_teams = set()

    possessive_pattern = re.compile(
        r"\b(Cleveland|Minnesota|Charlotte|Phoenix|Utah)"
        r"(?:'s|’s)\s+2029\s+(?:1st|first)\s+round\s+pick",
        re.IGNORECASE,
    )

    for match in possessive_pattern.finditer(
        combined
    ):
        discovered_teams.add(
            TEAM_LONG_NAME_TO_CODE[
                match.group(1).lower()
            ]
        )

    for team, pattern in TEAM_NAME_PATTERNS.items():
        if re.search(
            pattern
            + r".{0,50}\b2029\b.{0,30}\b(?:1st|first)\b",
            combined,
            re.IGNORECASE,
        ):
            discovered_teams.add(
                team
            )

    discovered_teams.update(
        group_claims[
            "originating_team"
        ]
        .astype(str)
        .tolist()
    )

    rows = []

    for team in sorted(
        discovered_teams
    ):
        asset_key = f"2029_R1_{team}"

        matches = all_claims.loc[
            all_claims[
                "asset_key"
            ]
            .astype(str)
            .eq(
                asset_key
            )
        ]

        rows.append(
            {
                "candidate_source_team": team,
                "candidate_asset_key": asset_key,
                "claim_row_exists": bool(
                    not matches.empty
                ),
                "claim_rows": int(
                    len(
                        matches
                    )
                ),
                "claim_ids": (
                    join_unique(
                        matches[
                            "claim_id"
                        ]
                    )
                    if not matches.empty
                    else ""
                ),
                "obligation_groups": (
                    join_unique(
                        matches[
                            "obligation_group_id"
                        ]
                    )
                    if (
                        not matches.empty
                        and "obligation_group_id"
                        in matches.columns
                    )
                    else ""
                ),
                "source_candidate_basis": (
                    "team named near 2029 first-round language "
                    "or originating target-group asset"
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_team_mention_matrix(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in connected_claims.iterrows():
        text = clean_text(
            row.get(
                "_combined_text",
                "",
            )
        )

        output = {
            "claim_id": clean_text(
                row[
                    "claim_id"
                ]
            ),
            "asset_key": clean_text(
                row[
                    "asset_key"
                ]
            ),
            "obligation_group_id": clean_text(
                row.get(
                    "obligation_group_id",
                    "",
                )
            ),
            "valuation_method": clean_text(
                row.get(
                    "valuation_method",
                    "",
                )
            ),
            "valuation_status": clean_text(
                row.get(
                    "valuation_status",
                    "",
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

        output[
            "contains_2029_first"
        ] = bool(
            re.search(
                r"\b2029\b.{0,40}\b(?:1st|first)\b",
                text,
                re.IGNORECASE,
            )
        )

        output[
            "contains_swap"
        ] = bool(
            re.search(
                r"\bswap\b",
                text,
                re.IGNORECASE,
            )
        )

        output[
            "contains_protection"
        ] = bool(
            re.search(
                r"\b(?:protected|protection|top[- ]?\d+)\b",
                text,
                re.IGNORECASE,
            )
        )

        output[
            "contains_rollover"
        ] = bool(
            re.search(
                r"\b(?:roll over|rollover|fallback|instead|"
                r"extinguish|extinguished|defer|deferred)\b",
                text,
                re.IGNORECASE,
            )
        )

        rows.append(
            output
        )

    return pd.DataFrame(
        rows
    )


def build_connected_assets(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for asset_key, group in connected_claims.groupby(
        "asset_key",
        dropna=False,
    ):
        valued_mask = (
            group[
                "valuation_status"
            ]
            .fillna("")
            .astype(str)
            .str.startswith(
                "valued_"
            )
        )

        rows.append(
            {
                "asset_key": clean_text(
                    asset_key
                ),
                "draft_year": int(
                    pd.to_numeric(
                        group[
                            "draft_year"
                        ],
                        errors="coerce",
                    )
                    .dropna()
                    .iloc[0]
                ),
                "round_number": int(
                    pd.to_numeric(
                        group[
                            "round_number"
                        ],
                        errors="coerce",
                    )
                    .dropna()
                    .iloc[0]
                ),
                "originating_team": join_unique(
                    group[
                        "originating_team"
                    ]
                ),
                "claim_rows": int(
                    len(
                        group
                    )
                ),
                "claim_ids": join_unique(
                    group[
                        "claim_id"
                    ]
                ),
                "obligation_groups": join_unique(
                    group[
                        "obligation_group_id"
                    ]
                ),
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
                "candidate_beneficiary_teams": (
                    join_unique(
                        group.loc[
                            valued_mask,
                            "candidate_beneficiary_team",
                        ]
                    )
                    if "candidate_beneficiary_team" in group.columns
                    else ""
                ),
                "contains_target_group_claim": bool(
                    group[
                        "obligation_group_id"
                    ]
                    .fillna("")
                    .astype(str)
                    .eq(
                        TARGET_GROUP_ID
                    )
                    .any()
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "contains_target_group_claim",
            "asset_key",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_group_relationships(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for group_id, group in connected_claims.groupby(
        "obligation_group_id",
        dropna=False,
    ):
        rows.append(
            {
                "obligation_group_id": clean_text(
                    group_id
                ),
                "is_target_group": bool(
                    clean_text(
                        group_id
                    )
                    == TARGET_GROUP_ID
                ),
                "claim_rows": int(
                    len(
                        group
                    )
                ),
                "unique_assets": int(
                    group[
                        "asset_key"
                    ]
                    .astype(str)
                    .nunique()
                ),
                "asset_keys": join_unique(
                    group[
                        "asset_key"
                    ]
                ),
                "originating_teams": join_unique(
                    group[
                        "originating_team"
                    ]
                ),
                "claim_types": join_unique(
                    group[
                        "claim_type"
                    ]
                ),
                "structural_families": join_unique(
                    group[
                        "structural_family"
                    ]
                ),
                "valuation_methods": join_unique(
                    group[
                        "valuation_method"
                    ]
                ),
                "valuation_statuses": join_unique(
                    group[
                        "valuation_status"
                    ]
                ),
                "parsed_target_teams": join_unique(
                    group[
                        "parsed_target_teams"
                    ]
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "is_target_group",
            "claim_rows",
            "obligation_group_id",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_baseline_components(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    valued = connected_claims.loc[
        connected_claims[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .str.startswith(
            "valued_"
        )
    ].copy()

    output_columns = [
        column
        for column in [
            "claim_id",
            "asset_key",
            "obligation_group_id",
            "originating_team",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "valuation_scope_note",
        ]
        if column in valued.columns
    ]

    return valued[
        output_columns
    ].sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def classify_state(
    group_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
    source_candidates: pd.DataFrame,
    connected_claims: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
    rule_types = set(
        rule_fragments[
            "rule_type"
        ].astype(str)
    )

    has_protection = (
        "protection_rule"
        in rule_types
    )

    has_rollover = (
        "rollover_rule"
        in rule_types
    )

    has_swap = (
        "swap_rule"
        in rule_types
    )

    has_favorability = (
        "favorability_rule"
        in rule_types
    )

    candidate_source_count = int(
        source_candidates[
            "claim_row_exists"
        ]
        .fillna(False)
        .astype(bool)
        .sum()
    )

    connected_group_count = int(
        connected_claims[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(str)
        .nunique()
    )

    if (
        len(
            group_claims
        )
        == 3
        and group_claims[
            "asset_key"
        ]
        .astype(str)
        .nunique()
        == 2
        and has_favorability
        and has_swap
        and has_protection
    ):
        return (
            "protected_multi_claim_swap_favorability_structure_found",
            False,
            (
                "The expected three-claim, two-unresolved-asset structure "
                "was found with favorability, swap, and protection rules. "
                "Rollover or fallback language is "
                + (
                    "also present. "
                    if has_rollover
                    else "not detected by the fragment parser. "
                )
                + (
                    f"{candidate_source_count} candidate 2029 first-round "
                    "physical sources have matching claim rows. "
                )
                + (
                    f"The broad connected search surfaced "
                    f"{connected_group_count} obligation groups. "
                )
                + (
                    "The exact branch controller and source ownership must "
                    "be reconstructed from the printed clauses before "
                    "joint simulation."
                )
            ),
        )

    return (
        "connected_component_text_found_manual_controller_parse_required",
        False,
        (
            "The target group was found, but its current parsed structure "
            "does not exactly match the expected three-claim protected "
            "swap and favorability pattern."
        ),
    )


def build_resolution_template(
    group_claims: pd.DataFrame,
    source_candidates: pd.DataFrame,
    diagnostic_state: str,
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
                    False
                ),
                "claim_ids": join_unique(
                    group_claims[
                        "claim_id"
                    ]
                ),
                "unresolved_source_assets": join_unique(
                    group_claims[
                        "asset_key"
                    ]
                ),
                "candidate_physical_sources": join_unique(
                    source_candidates.loc[
                        source_candidates[
                            "claim_row_exists"
                        ]
                        .fillna(False)
                        .astype(bool),
                        "candidate_asset_key",
                    ]
                ),
                "confirmed_stage_1_rule": "",
                "confirmed_stage_2_rule": "",
                "confirmed_stage_3_rule": "",
                "confirmed_charlotte_right": "",
                "confirmed_phoenix_right": "",
                "confirmed_utah_right": "",
                "confirmed_cleveland_retained_right": "",
                "confirmed_minnesota_retained_right": "",
                "confirmed_protection_ranges": "",
                "confirmed_rollover_year_and_asset": "",
                "confirmed_fallback_recipient": "",
                "confirmed_extinguishment_rule": "",
                "confirmed_existing_baselines_to_remove": "",
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

    print(
        "=" * 80
    )
    print(
        "2029 CLE-MIN CONNECTED-COMPONENT DIAGNOSTIC"
    )
    print(
        "=" * 80
    )
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

    (
        seed_assets,
        seed_texts,
        seed_teams,
    ) = build_seed_information(
        group_claims
    )

    connected_claims = select_connected_claims(
        merged=merged,
        seed_assets=seed_assets,
        seed_texts=seed_texts,
        seed_teams=seed_teams,
    )

    rule_fragments = extract_rule_fragments(
        group_claims
    )

    clause_table = split_clauses(
        group_claims
    )

    source_candidates = extract_source_candidates(
        group_claims=group_claims,
        all_claims=merged,
    )

    team_mention_matrix = build_team_mention_matrix(
        connected_claims
    )

    connected_assets = build_connected_assets(
        connected_claims
    )

    group_relationships = build_group_relationships(
        connected_claims
    )

    baseline_components = build_baseline_components(
        connected_claims
    )

    (
        diagnostic_state,
        automatic_value_ready,
        diagnostic_note,
    ) = classify_state(
        group_claims=group_claims,
        rule_fragments=rule_fragments,
        source_candidates=source_candidates,
        connected_claims=connected_claims,
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

    connected_claims.to_csv(
        CONNECTED_CLAIMS_PATH,
        index=False,
    )

    connected_assets.to_csv(
        CONNECTED_ASSETS_PATH,
        index=False,
    )

    connected_claims.loc[
        connected_claims[
            "match_exact_normalized_text"
        ]
        | connected_claims[
            "match_multi_target_team_text"
        ]
    ].to_csv(
        TEXT_MATCHES_PATH,
        index=False,
    )

    rule_fragments.to_csv(
        RULE_FRAGMENTS_PATH,
        index=False,
    )

    clause_table.to_csv(
        CLAUSE_TABLE_PATH,
        index=False,
    )

    source_candidates.to_csv(
        SOURCE_CANDIDATES_PATH,
        index=False,
    )

    team_mention_matrix.to_csv(
        TEAM_MENTION_MATRIX_PATH,
        index=False,
    )

    group_relationships.to_csv(
        GROUP_RELATIONSHIP_PATH,
        index=False,
    )

    baseline_components.to_csv(
        BASELINE_COMPONENTS_PATH,
        index=False,
    )

    build_resolution_template(
        group_claims=group_claims,
        source_candidates=source_candidates,
        diagnostic_state=diagnostic_state,
    ).to_csv(
        RESOLUTION_TEMPLATE_PATH,
        index=False,
    )

    unresolved_group_claims = residual_claims.loc[
        residual_claims[
            "claim_id"
        ]
        .astype(str)
        .isin(
            set(
                group_claims[
                    "claim_id"
                ]
                .astype(str)
            )
        )
        & residual_claims[
            "claim_unresolved"
        ]
        .fillna(False)
        .astype(bool)
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
        "group_claim_rows": int(
            len(
                group_claims
            )
        ),
        "group_unresolved_claim_rows": int(
            len(
                unresolved_group_claims
            )
        ),
        "group_unique_assets": int(
            group_claims[
                "asset_key"
            ]
            .astype(str)
            .nunique()
        ),
        "group_asset_keys": sorted(
            set(
                group_claims[
                    "asset_key"
                ]
                .astype(str)
            )
        ),
        "seed_teams": sorted(
            seed_teams
        ),
        "connected_claim_rows": int(
            len(
                connected_claims
            )
        ),
        "connected_unique_assets": int(
            connected_claims[
                "asset_key"
            ]
            .astype(str)
            .nunique()
        ),
        "connected_obligation_groups": int(
            connected_claims[
                "obligation_group_id"
            ]
            .fillna("")
            .astype(str)
            .nunique()
        ),
        "candidate_physical_source_rows": int(
            len(
                source_candidates
            )
        ),
        "candidate_sources_with_claim_rows": int(
            source_candidates[
                "claim_row_exists"
            ]
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        "rule_fragment_rows": int(
            len(
                rule_fragments
            )
        ),
        "clause_rows": int(
            len(
                clause_table
            )
        ),
        "existing_valued_connected_claim_rows": int(
            len(
                baseline_components
            )
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
            "connected_claims": str(
                CONNECTED_CLAIMS_PATH
            ),
            "connected_assets": str(
                CONNECTED_ASSETS_PATH
            ),
            "text_matches": str(
                TEXT_MATCHES_PATH
            ),
            "rule_fragments": str(
                RULE_FRAGMENTS_PATH
            ),
            "clause_table": str(
                CLAUSE_TABLE_PATH
            ),
            "physical_source_candidates": str(
                SOURCE_CANDIDATES_PATH
            ),
            "team_mention_matrix": str(
                TEAM_MENTION_MATRIX_PATH
            ),
            "group_relationships": str(
                GROUP_RELATIONSHIP_PATH
            ),
            "baseline_components": str(
                BASELINE_COMPONENTS_PATH
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

    print(
        "=" * 80
    )
    print(
        "2029 CLE-MIN CONNECTED DIAGNOSTIC CREATED"
    )
    print(
        "=" * 80
    )
    print(
        f"Target group: {TARGET_GROUP_ID}"
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
        f"Group claim rows: {len(group_claims):,}"
    )
    print(
        "Group unique assets: "
        f"{group_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Unresolved source assets: "
        + "|".join(
            sorted(
                set(
                    group_claims[
                        "asset_key"
                    ]
                    .astype(str)
                )
            )
        )
    )
    print(
        f"Connected claim rows: {len(connected_claims):,}"
    )
    print(
        "Connected unique assets: "
        f"{connected_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Connected obligation groups: "
        f"{connected_claims['obligation_group_id'].fillna('').astype(str).nunique():,}"
    )
    print(
        "Candidate physical sources with claim rows: "
        f"{int(source_candidates['claim_row_exists'].fillna(False).astype(bool).sum()):,}"
    )
    print(
        f"Rule fragments extracted: {len(rule_fragments):,}"
    )
    print(
        f"Clause rows created: {len(clause_table):,}"
    )
    print(
        "Existing valued connected claim rows: "
        f"{len(baseline_components):,}"
    )
    print(
        f"Diagnostic state: {diagnostic_state}"
    )
    print(
        f"Automatic value ready: {automatic_value_ready}"
    )
    print()

    print(
        "TARGET GROUP CLAIM SUMMARY"
    )

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

    print(
        "PHYSICAL SOURCE CANDIDATES"
    )

    if source_candidates.empty:
        print(
            "No candidate physical sources were extracted."
        )
    else:
        print(
            source_candidates.to_string(
                index=False
            )
        )
    print()

    print(
        "CONNECTED OBLIGATION GROUPS"
    )

    print(
        group_relationships.to_string(
            index=False
        )
    )
    print()

    print(
        "CONNECTED ASSETS"
    )

    print(
        connected_assets.to_string(
            index=False
        )
    )
    print()

    print(
        "EXISTING VALUED CONNECTED CLAIMS"
    )

    if baseline_components.empty:
        print(
            "No existing valued connected claims were found."
        )
    else:
        print(
            baseline_components.to_string(
                index=False
            )
        )
    print()

    print(
        "RULE FRAGMENTS"
    )

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

    print(
        "TARGET GROUP CLAIM TEXT"
    )

    for row in group_claims.itertuples(
        index=False
    ):
        print(
            "-" * 80
        )
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
    print(
        "CONNECTED CLAIM SUMMARY"
    )

    connected_columns = [
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
            "parsed_target_teams",
            "match_target_group",
            "match_seed_asset",
            "match_exact_normalized_text",
            "match_multi_target_team_text",
            "match_seed_team_2029_first",
        ]
        if column in connected_claims.columns
    ]

    print(
        connected_claims[
            connected_columns
        ].head(
            80
        ).to_string(
            index=False
        )
    )

    print()
    print(
        "SAVED FILES"
    )
    print(
        GROUP_CLAIMS_PATH
    )
    print(
        CONNECTED_CLAIMS_PATH
    )
    print(
        CONNECTED_ASSETS_PATH
    )
    print(
        TEXT_MATCHES_PATH
    )
    print(
        RULE_FRAGMENTS_PATH
    )
    print(
        CLAUSE_TABLE_PATH
    )
    print(
        SOURCE_CANDIDATES_PATH
    )
    print(
        TEAM_MENTION_MATRIX_PATH
    )
    print(
        GROUP_RELATIONSHIP_PATH
    )
    print(
        BASELINE_COMPONENTS_PATH
    )
    print(
        RESOLUTION_TEMPLATE_PATH
    )
    print(
        METADATA_PATH
    )


if __name__ == "__main__":
    main()