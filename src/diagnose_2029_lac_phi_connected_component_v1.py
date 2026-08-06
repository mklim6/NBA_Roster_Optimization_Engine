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
    "future-pick-2029-lac-phi-connected-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_0af97af48bc4"
TARGET_DRAFT_YEAR = 2029
TARGET_ROUND_NUMBER = 1

PRIMARY_TARGET_TEAMS = {
    "LAC",
    "PHI",
}

TEAM_NAME_PATTERNS = {
    "ATL": r"\bAtlanta\b",
    "BOS": r"\bBoston\b",
    "BKN": r"\b(?:Brooklyn|Nets)\b",
    "CHA": r"\bCharlotte\b",
    "CHI": r"\bChicago\b",
    "CLE": r"\bCleveland\b",
    "DAL": r"\bDallas\b",
    "DEN": r"\bDenver\b",
    "DET": r"\bDetroit\b",
    "GSW": r"\b(?:Golden State|Warriors)\b",
    "HOU": r"\bHouston\b",
    "IND": r"\bIndiana\b",
    "LAC": r"\b(?:L\.?\s*A\.?\s*Clippers|Los Angeles Clippers|Clippers)\b",
    "LAL": r"\b(?:L\.?\s*A\.?\s*Lakers|Los Angeles Lakers|Lakers)\b",
    "MEM": r"\bMemphis\b",
    "MIA": r"\bMiami\b",
    "MIL": r"\bMilwaukee\b",
    "MIN": r"\bMinnesota\b",
    "NOP": r"\b(?:New Orleans|Pelicans)\b",
    "NYK": r"\b(?:New York|Knicks)\b",
    "OKC": r"\b(?:Oklahoma City|Thunder)\b",
    "ORL": r"\bOrlando\b",
    "PHI": r"\b(?:Philadelphia|76ers|Sixers)\b",
    "PHX": r"\bPhoenix\b",
    "POR": r"\bPortland\b",
    "SAC": r"\bSacramento\b",
    "SAS": r"\bSan Antonio\b",
    "TOR": r"\bToronto\b",
    "UTA": r"\bUtah\b",
    "WAS": r"\b(?:Washington|Wizards)\b",
}

TEAM_LONG_NAME_TO_CODE = {
    "atlanta": "ATL",
    "boston": "BOS",
    "brooklyn": "BKN",
    "charlotte": "CHA",
    "chicago": "CHI",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "golden state": "GSW",
    "houston": "HOU",
    "indiana": "IND",
    "la clippers": "LAC",
    "l.a. clippers": "LAC",
    "los angeles clippers": "LAC",
    "la lakers": "LAL",
    "l.a. lakers": "LAL",
    "los angeles lakers": "LAL",
    "memphis": "MEM",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "new orleans": "NOP",
    "new york": "NYK",
    "oklahoma city": "OKC",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "portland": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "toronto": "TOR",
    "utah": "UTA",
    "washington": "WAS",
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
    / "future_pick_claim_value_layer_2027_2029_v18_mil_nop_atl_enriched.parquet"
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
    / "future_pick_residual_dependency_group_audit_after_v18.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v18.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_group_claims_v1.csv"
)

CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_connected_claims_v1.csv"
)

CONNECTED_ASSETS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_connected_assets_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_rule_fragments_v1.csv"
)

CLAUSE_TABLE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_clause_table_v1.csv"
)

SOURCE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_physical_source_candidates_v1.csv"
)

GROUP_RELATIONSHIPS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_group_relationships_v1.csv"
)

VALUED_CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_existing_valued_connected_claims_v1.csv"
)

TEAM_MENTION_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_team_mention_matrix_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_lac_phi_connected_diagnostic_metadata_v1.json"
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
    "parsed_target_teams",
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
            + "\n".join(
                missing
            )
        )


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    if (
        isinstance(
            value,
            float,
        )
        and np.isnan(
            value
        )
    ):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def normalized_text(
    value: Any,
) -> str:
    text = clean_text(
        value
    ).lower()

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
        return (
            None
            if np.isnan(
                value
            )
            else float(
                value
            )
        )

    if isinstance(
        value,
        float,
    ):
        return (
            None
            if math.isnan(
                value
            )
            else value
        )

    if pd.isna(
        value
    ):
        return None

    return value


def join_unique(
    values: pd.Series,
) -> str:
    cleaned = {
        clean_text(
            value
        )
        for value in values
        if clean_text(
            value
        )
    }

    return "|".join(
        sorted(
            cleaned
        )
    )


def combined_text_for_row(
    row: pd.Series,
) -> str:
    parts = []

    for column in TEXT_COLUMNS:
        if column not in row.index:
            continue

        value = clean_text(
            row.get(
                column,
                "",
            )
        )

        if value:
            parts.append(
                value
            )

    return " ".join(
        parts
    )


def row_team_tokens(
    row: pd.Series,
) -> set[str]:
    output = set()

    for column in TEAM_FIELD_COLUMNS:
        if column not in row.index:
            continue

        value = clean_text(
            row.get(
                column,
                "",
            )
        )

        for token in re.split(
            r"[^A-Z]+",
            value.upper(),
        ):
            if token in TEAM_NAME_PATTERNS:
                output.add(
                    token
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
            output.add(
                team
            )

    return output


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        RESIDUAL_GROUP_AUDIT_PATH,
        RESIDUAL_CLAIM_AUDIT_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required diagnostic input was not found:\n"
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

    group_audit = normalize_columns(
        pd.read_csv(
            RESIDUAL_GROUP_AUDIT_PATH
        )
    )

    claim_audit = normalize_columns(
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
        "V18 valuation layer",
    )

    require_columns(
        group_audit,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V18 residual group audit",
    )

    require_columns(
        claim_audit,
        [
            "claim_id",
        ],
        "V18 residual claim audit",
    )

    return (
        claims,
        valuations,
        group_audit,
        claim_audit,
    )


def attach_dependency_fields(
    claims: pd.DataFrame,
    claim_audit: pd.DataFrame,
) -> pd.DataFrame:
    output = claims.copy()

    if DEPENDENCY_NODES_PATH.exists():
        dependency_nodes = normalize_columns(
            pd.read_parquet(
                DEPENDENCY_NODES_PATH
            )
        )

        if "claim_id" in dependency_nodes.columns:
            available = [
                column
                for column in [
                    "claim_id",
                    "obligation_group_id",
                    "structural_family",
                    "parsed_target_teams",
                    "parsed_target_team_count",
                ]
                if column in dependency_nodes.columns
            ]

            dependency_nodes = (
                dependency_nodes[
                    available
                ]
                .drop_duplicates(
                    subset=[
                        "claim_id"
                    ]
                )
            )

            output = output.merge(
                dependency_nodes,
                how="left",
                on="claim_id",
                suffixes=(
                    "",
                    "_dependency",
                ),
                validate="one_to_one",
            )

    audit_fields = [
        column
        for column in [
            "claim_id",
            "effective_obligation_group_id",
            "obligation_group_id",
            "structural_family",
            "parsed_target_teams",
            "parsed_target_team_count",
            "unconditional_asset_exposure_score",
        ]
        if column in claim_audit.columns
    ]

    if len(
        audit_fields
    ) > 1:
        audit_subset = (
            claim_audit[
                audit_fields
            ]
            .drop_duplicates(
                subset=[
                    "claim_id"
                ]
            )
        )

        output = output.merge(
            audit_subset,
            how="left",
            on="claim_id",
            suffixes=(
                "",
                "_audit",
            ),
            validate="one_to_one",
        )

    group_candidates = [
        column
        for column in output.columns
        if (
            column
            == "obligation_group_id"
            or column.startswith(
                "obligation_group_id_"
            )
            or column
            == "effective_obligation_group_id"
        )
    ]

    combined_group = pd.Series(
        "",
        index=output.index,
        dtype=object,
    )

    for column in group_candidates:
        values = (
            output[
                column
            ]
            .fillna("")
            .astype(
                str
            )
            .str.strip()
        )

        combined_group = combined_group.mask(
            combined_group.eq("")
            & values.ne(""),
            values,
        )

    output[
        "obligation_group_id"
    ] = combined_group

    for base_column in [
        "structural_family",
        "parsed_target_teams",
        "parsed_target_team_count",
    ]:
        candidates = [
            column
            for column in output.columns
            if (
                column == base_column
                or column.startswith(
                    base_column
                    + "_"
                )
            )
        ]

        if not candidates:
            continue

        if base_column == "parsed_target_team_count":
            combined = pd.Series(
                np.nan,
                index=output.index,
                dtype=float,
            )

            for column in candidates:
                values = pd.to_numeric(
                    output[
                        column
                    ],
                    errors="coerce",
                )

                combined = combined.mask(
                    combined.isna()
                    & values.notna(),
                    values,
                )

        else:
            combined = pd.Series(
                "",
                index=output.index,
                dtype=object,
            )

            for column in candidates:
                values = (
                    output[
                        column
                    ]
                    .fillna("")
                    .astype(
                        str
                    )
                    .str.strip()
                )

                combined = combined.mask(
                    combined.eq("")
                    & values.ne(""),
                    values,
                )

        output[
            base_column
        ] = combined

    if "structural_family" not in output.columns:
        output[
            "structural_family"
        ] = ""

    if "parsed_target_teams" not in output.columns:
        output[
            "parsed_target_teams"
        ] = ""

    return output


def attach_valuations(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    available = [
        column
        for column in VALUATION_COLUMNS
        if column in valuations.columns
    ]

    valuation_subset = (
        valuations[
            available
        ]
        .drop_duplicates(
            subset=[
                "claim_id"
            ]
        )
    )

    output = claims.merge(
        valuation_subset,
        how="left",
        on="claim_id",
        suffixes=(
            "",
            "_valuation",
        ),
        validate="one_to_one",
    )

    output[
        "_combined_text"
    ] = output.apply(
        combined_text_for_row,
        axis=1,
    )

    output[
        "_normalized_text"
    ] = output[
        "_combined_text"
    ].map(
        normalized_text
    )

    return output


def select_group_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    output = merged.loc[
        merged[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
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


def select_connected_claims(
    merged: pd.DataFrame,
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    seed_assets = set(
        group_claims[
            "asset_key"
        ].astype(
            str
        )
    )

    seed_texts = {
        normalized_text(
            value
        )
        for value in group_claims[
            "_combined_text"
        ]
        if normalized_text(
            value
        )
    }

    seed_teams = set(
        PRIMARY_TARGET_TEAMS
    )

    for _, row in group_claims.iterrows():
        seed_teams.update(
            row_team_tokens(
                row
            )
        )

    exact_asset_match = (
        merged[
            "asset_key"
        ]
        .astype(
            str
        )
        .isin(
            seed_assets
        )
    )

    exact_text_match = (
        merged[
            "_normalized_text"
        ]
        .astype(
            str
        )
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
    )

    team_token_sets = merged.apply(
        row_team_tokens,
        axis=1,
    )

    mentions_lac_and_phi = team_token_sets.map(
        lambda teams: {
            "LAC",
            "PHI",
        }.issubset(
            teams
        )
    )

    mentions_two_seed_teams = team_token_sets.map(
        lambda teams: len(
            teams
            & seed_teams
        )
        >= 2
    )

    target_team_origin = (
        year_round_match
        & merged[
            "originating_team"
        ]
        .astype(
            str
        )
        .isin(
            seed_teams
        )
    )

    group_match = (
        merged[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .eq(
            TARGET_GROUP_ID
        )
    )

    selected_mask = (
        group_match
        | exact_asset_match
        | exact_text_match
        | (
            year_round_match
            & mentions_lac_and_phi
        )
        | (
            year_round_match
            & mentions_two_seed_teams
        )
        | target_team_origin
    )

    selected = merged.loc[
        selected_mask
    ].copy()

    selected[
        "match_target_group"
    ] = group_match.loc[
        selected.index
    ].astype(
        bool
    )

    selected[
        "match_seed_asset"
    ] = exact_asset_match.loc[
        selected.index
    ].astype(
        bool
    )

    selected[
        "match_exact_normalized_text"
    ] = exact_text_match.loc[
        selected.index
    ].astype(
        bool
    )

    selected[
        "match_lac_and_phi_2029_first_text"
    ] = (
        year_round_match.loc[
            selected.index
        ]
        & mentions_lac_and_phi.loc[
            selected.index
        ]
    ).astype(
        bool
    )

    selected[
        "match_multi_seed_team_2029_first_text"
    ] = (
        year_round_match.loc[
            selected.index
        ]
        & mentions_two_seed_teams.loc[
            selected.index
        ]
    ).astype(
        bool
    )

    selected[
        "match_seed_team_2029_first"
    ] = target_team_origin.loc[
        selected.index
    ].astype(
        bool
    )

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
        "swap_rule": (
            r"[^.;]*\b(?:right to swap|swap(?:s|ped|ping)?)\b[^.;]*"
        ),
        "favorability_rule": (
            r"[^.;]*\b(?:more favorable|less favorable|most favorable|"
            r"least favorable|better of|worse of)\b[^.;]*"
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
            r"extinguish|extinguished|defer|deferred|convey in|"
            r"convert|converted|becomes)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Philadelphia|"
            r"to the Clippers|to L\.?A\.? Clippers)\b[^.;]*"
        ),
        "future_year_rule": (
            r"[^.;]*\b(?:2030|2031|2032)\b[^.;]*"
        ),
    }

    rows: list[
        dict[str, Any]
    ] = []

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


def build_clause_table(
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
            clean_text(
                value
            )
            for value in re.split(
                r"(?<=[.;])\s+",
                text,
            )
            if clean_text(
                value
            )
        ]

        for clause_order, clause in enumerate(
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
                    "clause_order": clause_order,
                    "mentioned_teams": "|".join(
                        sorted(
                            teams
                        )
                    ),
                    "contains_swap": bool(
                        re.search(
                            r"\bswap\b",
                            clause,
                            re.IGNORECASE,
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
                    "contains_protection": bool(
                        re.search(
                            r"\b(?:protected|protection|top[- ]?\d+|"
                            r"selections?\s+\d+\s*(?:through|-|to)\s*\d+)"
                            r"\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_rollover": bool(
                        re.search(
                            r"\b(?:roll over|rollover|fallback|instead|"
                            r"extinguish|extinguished|defer|deferred|"
                            r"convert|converted|becomes)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_future_year": bool(
                        re.search(
                            r"\b(?:2030|2031|2032)\b",
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
        .astype(
            str
        )
        .tolist()
    )

    discovered_teams = set(
        group_claims[
            "originating_team"
        ]
        .astype(
            str
        )
        .tolist()
    )

    for team, pattern in TEAM_NAME_PATTERNS.items():
        near_year_first = (
            pattern
            + rf".{{0,100}}\b{TARGET_DRAFT_YEAR}\b"
            + r".{0,50}\b(?:1st|first)\b"
        )

        first_near_team = (
            rf"\b{TARGET_DRAFT_YEAR}\b"
            + r".{0,50}\b(?:1st|first)\b"
            + rf".{{0,100}}{pattern}"
        )

        if (
            re.search(
                near_year_first,
                combined,
                re.IGNORECASE,
            )
            or re.search(
                first_near_team,
                combined,
                re.IGNORECASE,
            )
        ):
            discovered_teams.add(
                team
            )

    possessive_pattern = re.compile(
        r"\b("
        + "|".join(
            sorted(
                (
                    re.escape(
                        name
                    )
                    for name in TEAM_LONG_NAME_TO_CODE
                ),
                key=len,
                reverse=True,
            )
        )
        + rf")(?:'s|’s)?\s+{TARGET_DRAFT_YEAR}\s+"
        r"(?:1st|first)\s+round\s+pick",
        re.IGNORECASE,
    )

    for match in possessive_pattern.finditer(
        combined
    ):
        team_name = match.group(
            1
        ).lower()

        if team_name in TEAM_LONG_NAME_TO_CODE:
            discovered_teams.add(
                TEAM_LONG_NAME_TO_CODE[
                    team_name
                ]
            )

    discovered_teams.update(
        PRIMARY_TARGET_TEAMS
    )

    rows = []

    for team in sorted(
        discovered_teams
    ):
        asset_key = (
            f"{TARGET_DRAFT_YEAR}_R"
            f"{TARGET_ROUND_NUMBER}_{team}"
        )

        matches = all_claims.loc[
            all_claims[
                "asset_key"
            ]
            .astype(
                str
            )
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
                    if not matches.empty
                    else ""
                ),
                "valuation_methods": (
                    join_unique(
                        matches[
                            "valuation_method"
                        ]
                    )
                    if (
                        not matches.empty
                        and "valuation_method"
                        in matches.columns
                    )
                    else ""
                ),
                "valuation_statuses": (
                    join_unique(
                        matches[
                            "valuation_status"
                        ]
                    )
                    if (
                        not matches.empty
                        and "valuation_status"
                        in matches.columns
                    )
                    else ""
                ),
                "source_candidate_basis": (
                    "team named near 2029 first-round language, "
                    "originating target-group source, or primary swap team"
                ),
            }
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
        sort=True,
    ):
        valued_mask = (
            group[
                "valuation_status"
            ]
            .fillna("")
            .astype(
                str
            )
            .str.startswith(
                "valued_"
            )
        )

        rows.append(
            {
                "asset_key": asset_key,
                "draft_year": int(
                    pd.to_numeric(
                        group[
                            "draft_year"
                        ],
                        errors="coerce",
                    ).dropna().iloc[
                        0
                    ]
                ),
                "round_number": int(
                    pd.to_numeric(
                        group[
                            "round_number"
                        ],
                        errors="coerce",
                    ).dropna().iloc[
                        0
                    ]
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
                    group[
                        "valuation_method"
                    ]
                    if "valuation_method" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "valuation_statuses": join_unique(
                    group[
                        "valuation_status"
                    ]
                    if "valuation_status" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "candidate_beneficiary_teams": join_unique(
                    group[
                        "candidate_beneficiary_team"
                    ]
                    if "candidate_beneficiary_team" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "contains_target_group_claim": bool(
                    group[
                        "obligation_group_id"
                    ]
                    .fillna("")
                    .astype(
                        str
                    )
                    .eq(
                        TARGET_GROUP_ID
                    )
                    .any()
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_group_relationships(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    group_series = (
        connected_claims[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
    )

    for group_id, group in connected_claims.groupby(
        group_series,
        sort=True,
    ):
        rows.append(
            {
                "obligation_group_id": group_id,
                "is_target_group": bool(
                    group_id
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
                    .astype(
                        str
                    )
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
                    if "claim_type" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "structural_families": join_unique(
                    group[
                        "structural_family"
                    ]
                    if "structural_family" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "valuation_methods": join_unique(
                    group[
                        "valuation_method"
                    ]
                    if "valuation_method" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "valuation_statuses": join_unique(
                    group[
                        "valuation_status"
                    ]
                    if "valuation_status" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
                "parsed_target_teams": join_unique(
                    group[
                        "parsed_target_teams"
                    ]
                    if "parsed_target_teams" in group.columns
                    else pd.Series(
                        dtype=object
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_valued_connected_claims(
    connected_claims: pd.DataFrame,
) -> pd.DataFrame:
    valued = connected_claims.loc[
        connected_claims[
            "valuation_status"
        ]
        .fillna("")
        .astype(
            str
        )
        .str.startswith(
            "valued_"
        )
    ].copy()

    columns = [
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
        columns
    ].sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
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

        rows.append(
            output
        )

    return pd.DataFrame(
        rows
    )


def determine_state(
    group_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
    source_candidates: pd.DataFrame,
    connected_claims: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
    claim_rows = int(
        len(
            group_claims
        )
    )

    unique_assets = int(
        group_claims[
            "asset_key"
        ]
        .astype(
            str
        )
        .nunique()
    )

    rule_types = set(
        rule_fragments[
            "rule_type"
        ].astype(
            str
        )
    )

    has_swap = (
        "swap_rule"
        in rule_types
    )

    has_protection = (
        "protection_rule"
        in rule_types
    )

    has_favorability = (
        "favorability_rule"
        in rule_types
    )

    has_rollover = (
        "rollover_rule"
        in rule_types
        or "future_year_rule"
        in rule_types
    )

    source_count = int(
        source_candidates[
            "claim_row_exists"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        )
        .sum()
    )

    connected_group_count = int(
        connected_claims[
            "obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .replace(
            "",
            np.nan,
        )
        .nunique()
    )

    if (
        claim_rows == 1
        and unique_assets == 1
        and has_swap
        and has_protection
    ):
        return (
            "protected_single_asset_swap_chain_text_found",
            False,
            (
                "The unresolved Clippers 2029 first, swap language, "
                "and protection language were found. The exact swap "
                "counterpart, protection range, exercise rule, retained "
                "pick, and any fallback or future-year consequence must "
                "be reconstructed from the printed claim text before "
                "joint valuation. "
                f"{source_count} candidate physical source rows and "
                f"{connected_group_count} connected obligation groups "
                "were surfaced."
                + (
                    " Favorability language is present."
                    if has_favorability
                    else ""
                )
                + (
                    " Rollover or future-year language is present."
                    if has_rollover
                    else ""
                )
            ),
        )

    return (
        "connected_swap_component_text_found_manual_parse_required",
        False,
        (
            "The target group was found, but it did not match the "
            "expected one-claim protected swap form. Review the exact "
            "claim text and all connected claims before valuation."
        ),
    )


def build_resolution_template(
    group_claims: pd.DataFrame,
    source_candidates: pd.DataFrame,
    diagnostic_state: str,
    diagnostic_note: str,
) -> pd.DataFrame:
    candidate_assets = source_candidates.loc[
        source_candidates[
            "claim_row_exists"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        ),
        "candidate_asset_key",
    ]

    return pd.DataFrame(
        [
            {
                "target_group_id": TARGET_GROUP_ID,
                "diagnostic_state": diagnostic_state,
                "unresolved_source_assets": join_unique(
                    group_claims[
                        "asset_key"
                    ]
                ),
                "candidate_physical_sources": join_unique(
                    candidate_assets
                ),
                "confirmed_physical_sources": "",
                "confirmed_swap_holder": "",
                "confirmed_swap_counterparty": "",
                "confirmed_more_favorable_recipient": "",
                "confirmed_less_favorable_recipient": "",
                "protection_range": "",
                "protection_applies_to_asset": "",
                "swap_exercise_rule": "",
                "branch_when_protection_hits": "",
                "retained_pick_owner": "",
                "fallback_asset_or_year": "",
                "rollover_or_extinguishment": "",
                "existing_baselines_to_remove": "",
                "connected_components_to_preserve": "",
                "source_verified": "",
                "source_as_of_date": "",
                "manual_resolution_note": diagnostic_note,
            }
        ]
    )


def print_claim_text(
    group_claims: pd.DataFrame,
) -> None:
    print(
        "TARGET GROUP CLAIM TEXT"
    )

    for _, row in group_claims.iterrows():
        print(
            "-" * 80
        )
        print(
            "Claim: "
            f"{clean_text(row['claim_id'])} | "
            "Asset: "
            f"{clean_text(row['asset_key'])}"
        )

        for column in [
            "pick_heading",
            "transaction_text",
            "full_obligation_text",
        ]:
            if column in group_claims.columns:
                print(
                    f"{column}: "
                    f"{clean_text(row.get(column, ''))}"
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
        "2029 LAC-PHI CONNECTED SWAP DIAGNOSTIC"
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
        group_audit,
        claim_audit,
    ) = load_inputs()

    claims = attach_dependency_fields(
        claims=claims,
        claim_audit=claim_audit,
    )

    merged = attach_valuations(
        claims=claims,
        valuations=valuations,
    )

    group_claims = select_group_claims(
        merged
    )

    group_row = group_audit.loc[
        group_audit[
            "effective_obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .eq(
            TARGET_GROUP_ID
        )
    ]

    if len(
        group_row
    ) != 1:
        raise ValueError(
            "Expected one residual group audit row for "
            f"{TARGET_GROUP_ID}; found {len(group_row)}."
        )

    group_row = group_row.iloc[
        0
    ]

    connected_claims = select_connected_claims(
        merged=merged,
        group_claims=group_claims,
    )

    rule_fragments = extract_rule_fragments(
        group_claims
    )

    clause_table = build_clause_table(
        group_claims
    )

    source_candidates = extract_source_candidates(
        group_claims=group_claims,
        all_claims=merged,
    )

    connected_assets = build_connected_assets(
        connected_claims
    )

    group_relationships = build_group_relationships(
        connected_claims
    )

    valued_connected_claims = build_valued_connected_claims(
        connected_claims
    )

    team_mention_matrix = build_team_mention_matrix(
        connected_claims
    )

    (
        diagnostic_state,
        automatic_value_ready,
        diagnostic_note,
    ) = determine_state(
        group_claims=group_claims,
        rule_fragments=rule_fragments,
        source_candidates=source_candidates,
        connected_claims=connected_claims,
    )

    resolution_template = build_resolution_template(
        group_claims=group_claims,
        source_candidates=source_candidates,
        diagnostic_state=diagnostic_state,
        diagnostic_note=diagnostic_note,
    )

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

    group_relationships.to_csv(
        GROUP_RELATIONSHIPS_PATH,
        index=False,
    )

    valued_connected_claims.to_csv(
        VALUED_CONNECTED_CLAIMS_PATH,
        index=False,
    )

    team_mention_matrix.to_csv(
        TEAM_MENTION_MATRIX_PATH,
        index=False,
    )

    resolution_template.to_csv(
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
            numeric_value(
                group_row[
                    "review_order"
                ]
            )
        ),
        "unique_asset_exposure_score": numeric_value(
            group_row[
                "unique_asset_exposure_score"
            ]
        ),
        "group_claim_rows": int(
            len(
                group_claims
            )
        ),
        "group_unique_assets": int(
            group_claims[
                "asset_key"
            ]
            .astype(
                str
            )
            .nunique()
        ),
        "unresolved_source_assets": sorted(
            set(
                group_claims[
                    "asset_key"
                ].astype(
                    str
                )
            )
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
            .astype(
                str
            )
            .nunique()
        ),
        "connected_obligation_groups": int(
            connected_claims[
                "obligation_group_id"
            ]
            .fillna("")
            .astype(
                str
            )
            .replace(
                "",
                np.nan,
            )
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
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        ),
        "rule_fragments_extracted": int(
            len(
                rule_fragments
            )
        ),
        "clause_rows_created": int(
            len(
                clause_table
            )
        ),
        "existing_valued_connected_claim_rows": int(
            len(
                valued_connected_claims
            )
        ),
        "diagnostic_state": diagnostic_state,
        "automatic_value_ready": automatic_value_ready,
        "diagnostic_note": diagnostic_note,
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
            "rule_fragments": str(
                RULE_FRAGMENTS_PATH
            ),
            "clause_table": str(
                CLAUSE_TABLE_PATH
            ),
            "physical_source_candidates": str(
                SOURCE_CANDIDATES_PATH
            ),
            "group_relationships": str(
                GROUP_RELATIONSHIPS_PATH
            ),
            "existing_valued_connected_claims": str(
                VALUED_CONNECTED_CLAIMS_PATH
            ),
            "team_mention_matrix": str(
                TEAM_MENTION_MATRIX_PATH
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
        "2029 LAC-PHI CONNECTED DIAGNOSTIC CREATED"
    )
    print(
        "=" * 80
    )
    print(
        f"Target group: {TARGET_GROUP_ID}"
    )
    print(
        "Residual review order: "
        f"{int(numeric_value(group_row['review_order']))}"
    )
    print(
        "Unique asset exposure score: "
        f"{numeric_value(group_row['unique_asset_exposure_score']):.4f}"
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
                    ].astype(
                        str
                    )
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
        f"{connected_claims['obligation_group_id'].fillna('').astype(str).replace('', np.nan).nunique():,}"
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
        f"{len(valued_connected_claims):,}"
    )
    print(
        f"Diagnostic state: {diagnostic_state}"
    )
    print(
        f"Automatic value ready: {automatic_value_ready}"
    )
    print()

    group_columns = [
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
        "TARGET GROUP CLAIM SUMMARY"
    )
    print(
        group_claims[
            group_columns
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

    if group_relationships.empty:
        print(
            "No connected obligation groups were summarized."
        )
    else:
        print(
            group_relationships.to_string(
                index=False
            )
        )

    print()

    print(
        "CONNECTED ASSETS"
    )

    if connected_assets.empty:
        print(
            "No connected assets were summarized."
        )
    else:
        print(
            connected_assets.to_string(
                index=False
            )
        )

    print()

    print(
        "EXISTING VALUED CONNECTED CLAIMS"
    )

    if valued_connected_claims.empty:
        print(
            "No existing valued connected claims were found."
        )
    else:
        print(
            valued_connected_claims.to_string(
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

    print_claim_text(
        group_claims
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
            "match_lac_and_phi_2029_first_text",
            "match_multi_seed_team_2029_first_text",
            "match_seed_team_2029_first",
        ]
        if column in connected_claims.columns
    ]

    print(
        connected_claims[
            connected_columns
        ].to_string(
            index=False
        )
    )

    print()
    print(
        "SAVED FILES"
    )

    for path in [
        GROUP_CLAIMS_PATH,
        CONNECTED_CLAIMS_PATH,
        CONNECTED_ASSETS_PATH,
        RULE_FRAGMENTS_PATH,
        CLAUSE_TABLE_PATH,
        SOURCE_CANDIDATES_PATH,
        GROUP_RELATIONSHIPS_PATH,
        VALUED_CONNECTED_CLAIMS_PATH,
        TEAM_MENTION_MATRIX_PATH,
        RESOLUTION_TEMPLATE_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()