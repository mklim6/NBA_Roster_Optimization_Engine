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
    "future-pick-2029-orl-mem-protected-swap-rollover-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TARGET_GROUP_ID = "OBL_5bbf674a68e1"
TARGET_ASSET_KEY = "2029_R1_ORL"

PRIMARY_TARGET_TEAMS = {
    "ORL",
    "MEM",
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
    / "future_pick_claim_value_layer_2027_2029_v23_mil_nyk_det_chi_enriched.parquet"
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
    / "future_pick_residual_dependency_group_audit_after_v23.csv"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v23.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

GROUP_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_group_claims_v1.csv"
)

CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_connected_claims_v1.csv"
)

CONNECTED_ASSETS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_connected_assets_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_rule_fragments_v1.csv"
)

CLAUSE_TABLE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_clause_table_v1.csv"
)

YEAR_ROUND_REFERENCES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_year_round_references_v1.csv"
)

SOURCE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_physical_source_candidates_v1.csv"
)

GROUP_RELATIONSHIPS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_group_relationships_v1.csv"
)

VALUED_CONNECTED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_existing_valued_connected_claims_v1.csv"
)

RESOLUTION_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_resolution_template_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2029_orl_mem_protected_swap_rollover_diagnostic_metadata_v1.json"
)


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

    try:
        if pd.isna(
            value
        ):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

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

    try:
        if pd.isna(
            value
        ):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


def first_nonempty_text(
    frame: pd.DataFrame,
    candidates: list[str],
) -> pd.Series:
    output = pd.Series(
        "",
        index=frame.index,
        dtype=object,
    )

    for column in candidates:
        if column not in frame.columns:
            continue

        values = (
            frame[
                column
            ]
            .fillna("")
            .astype(
                str
            )
            .str.strip()
        )

        output = output.mask(
            output.eq("")
            & values.ne(""),
            values,
        )

    return output


def first_numeric(
    frame: pd.DataFrame,
    candidates: list[str],
) -> pd.Series:
    output = pd.Series(
        np.nan,
        index=frame.index,
        dtype=float,
    )

    for column in candidates:
        if column not in frame.columns:
            continue

        values = pd.to_numeric(
            frame[
                column
            ],
            errors="coerce",
        )

        output = output.mask(
            output.isna()
            & values.notna(),
            values,
        )

    return output


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
        "V23 valuation layer",
    )

    require_columns(
        group_audit,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V23 residual group audit",
    )

    require_columns(
        claim_audit,
        [
            "claim_id",
        ],
        "V23 residual claim audit",
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
        nodes = normalize_columns(
            pd.read_parquet(
                DEPENDENCY_NODES_PATH
            )
        )

        if "claim_id" in nodes.columns:
            available = [
                column
                for column in [
                    "claim_id",
                    "obligation_group_id",
                    "structural_family",
                    "parsed_target_teams",
                    "parsed_target_team_count",
                ]
                if column in nodes.columns
            ]

            nodes = (
                nodes[
                    available
                ]
                .drop_duplicates(
                    subset=[
                        "claim_id"
                    ]
                )
                .rename(
                    columns={
                        column: (
                            column
                            if column == "claim_id"
                            else f"{column}_dependency"
                        )
                        for column in available
                    }
                )
            )

            output = output.merge(
                nodes,
                how="left",
                on="claim_id",
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
        audit = (
            claim_audit[
                audit_fields
            ]
            .drop_duplicates(
                subset=[
                    "claim_id"
                ]
            )
            .rename(
                columns={
                    column: (
                        column
                        if column == "claim_id"
                        else f"{column}_audit"
                    )
                    for column in audit_fields
                }
            )
        )

        output = output.merge(
            audit,
            how="left",
            on="claim_id",
            validate="one_to_one",
        )

    output[
        "effective_obligation_group_id"
    ] = first_nonempty_text(
        output,
        [
            "effective_obligation_group_id_audit",
            "obligation_group_id_audit",
            "obligation_group_id_dependency",
            "obligation_group_id",
        ],
    )

    output[
        "structural_family"
    ] = first_nonempty_text(
        output,
        [
            "structural_family_audit",
            "structural_family_dependency",
            "structural_family",
        ],
    )

    output[
        "parsed_target_teams"
    ] = first_nonempty_text(
        output,
        [
            "parsed_target_teams_audit",
            "parsed_target_teams_dependency",
            "parsed_target_teams",
        ],
    )

    output[
        "parsed_target_team_count"
    ] = first_numeric(
        output,
        [
            "parsed_target_team_count_audit",
            "parsed_target_team_count_dependency",
            "parsed_target_team_count",
        ],
    ).fillna(
        0
    )

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
        .rename(
            columns={
                column: (
                    column
                    if column == "claim_id"
                    else f"{column}_valuation"
                )
                for column in available
            }
        )
    )

    output = claims.merge(
        valuation_subset,
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    for field in [
        "valuation_method",
        "valuation_status",
        "candidate_beneficiary_team",
        "candidate_retaining_team",
        "candidate_counterparty_team",
        "automatic_exclusion_reason",
        "valuation_scope_note",
    ]:
        output[
            field
        ] = first_nonempty_text(
            output,
            [
                f"{field}_valuation",
                field,
            ],
        )

    for field in [
        "expected_transferred_value_score",
        "expected_retained_value_score",
        "expected_swap_option_value_score",
        "expected_total_candidate_asset_value_score",
    ]:
        output[
            field
        ] = first_numeric(
            output,
            [
                f"{field}_valuation",
                field,
            ],
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
    group_match = (
        merged[
            "effective_obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .eq(
            TARGET_GROUP_ID
        )
    )

    asset_match = (
        merged[
            "asset_key"
        ]
        .astype(
            str
        )
        .eq(
            TARGET_ASSET_KEY
        )
    )

    output = merged.loc[
        group_match
        | asset_match
    ].copy()

    if output.empty:
        raise ValueError(
            "No target claim was found for group "
            f"{TARGET_GROUP_ID} or asset {TARGET_ASSET_KEY}."
        )

    target_asset_rows = output.loc[
        output[
            "asset_key"
        ]
        .astype(
            str
        )
        .eq(
            TARGET_ASSET_KEY
        )
    ]

    if len(
        target_asset_rows
    ) != 1:
        raise ValueError(
            "Expected exactly one Orlando 2029 first-round claim; "
            f"found {len(target_asset_rows)}."
        )

    output = target_asset_rows.copy()

    return output.sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def extract_rule_fragments(
    group_claims: pd.DataFrame,
) -> pd.DataFrame:
    patterns = {
        "swap_rule": (
            r"[^.;]*\b(?:right to swap|swap(?:s|ped|ping)?|"
            r"exchange|exchanges)\b[^.;]*"
        ),
        "favorability_rule": (
            r"[^.;]*\b(?:more favorable|less favorable|"
            r"most favorable|least favorable|better of|worse of)\b[^.;]*"
        ),
        "protection_rule": (
            r"[^.;]*\b(?:protected|protection|top[- ]?\d+|"
            r"selections?\s+\d+\s*(?:through|-|to)\s*\d+)\b[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if|"
            r"conditional|should)\b[^.;]*"
        ),
        "rollover_rule": (
            r"[^.;]*\b(?:roll over|rollover|fallback|instead|"
            r"extinguish|extinguished|defer|deferred|convey in|"
            r"convert|converted|becomes|result in|replacement)\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:receive|receives|to Memphis|to Orlando|"
            r"Memphis may|Orlando may)\b[^.;]*"
        ),
        "future_year_rule": (
            r"[^.;]*\b(?:2027|2028|2029|2030|2031|2032)\b[^.;]*"
        ),
        "round_rule": (
            r"[^.;]*\b(?:1st|first|2nd|second)\s+round\b[^.;]*"
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

            years = sorted(
                {
                    int(
                        year
                    )
                    for year in re.findall(
                        r"\b(20\d{2})\b",
                        clause,
                    )
                }
            )

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
                    "mentioned_years": "|".join(
                        str(
                            year
                        )
                        for year in years
                    ),
                    "contains_swap": bool(
                        re.search(
                            r"\b(?:swap|exchange)\b",
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
                    "contains_conditional": bool(
                        re.search(
                            r"\b(?:if|unless|provided that|only if|"
                            r"conditional|should)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    ),
                    "contains_rollover_or_fallback": bool(
                        re.search(
                            r"\b(?:roll over|rollover|fallback|instead|"
                            r"extinguish|extinguished|defer|deferred|"
                            r"convert|converted|becomes|replacement)\b",
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


def extract_year_round_references(
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

        years = sorted(
            {
                int(
                    year
                )
                for year in re.findall(
                    r"\b(20\d{2})\b",
                    text,
                )
            }
        )

        for year in years:
            windows = re.findall(
                rf".{{0,140}}\b{year}\b.{{0,140}}",
                text,
                flags=re.IGNORECASE,
            )

            if not windows:
                windows = [
                    text
                ]

            for window_order, window in enumerate(
                windows,
                start=1,
            ):
                rounds = []

                if re.search(
                    r"\b(?:1st|first)\s+round\b",
                    window,
                    re.IGNORECASE,
                ):
                    rounds.append(
                        1
                    )

                if re.search(
                    r"\b(?:2nd|second)\s+round\b",
                    window,
                    re.IGNORECASE,
                ):
                    rounds.append(
                        2
                    )

                teams = [
                    team
                    for team, pattern in TEAM_NAME_PATTERNS.items()
                    if re.search(
                        pattern,
                        window,
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
                        "referenced_year": year,
                        "window_order": window_order,
                        "referenced_rounds": "|".join(
                            str(
                                round_number
                            )
                            for round_number in sorted(
                                set(
                                    rounds
                                )
                            )
                        ),
                        "referenced_teams": "|".join(
                            sorted(
                                teams
                            )
                        ),
                        "reference_window": clean_text(
                            window
                        ),
                    }
                )

    return pd.DataFrame(
        rows,
        columns=[
            "claim_id",
            "asset_key",
            "referenced_year",
            "window_order",
            "referenced_rounds",
            "referenced_teams",
            "reference_window",
        ],
    )


def select_connected_claims(
    merged: pd.DataFrame,
    group_claims: pd.DataFrame,
    year_round_references: pd.DataFrame,
) -> pd.DataFrame:
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

    referenced_years = {
        int(
            value
        )
        for value in year_round_references[
            "referenced_year"
        ].dropna()
        if 2027
        <= int(
            value
        )
        <= 2029
    }

    if not referenced_years:
        referenced_years = {
            2029
        }

    target_group_match = (
        merged[
            "effective_obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .eq(
            TARGET_GROUP_ID
        )
    )

    target_asset_match = (
        merged[
            "asset_key"
        ]
        .astype(
            str
        )
        .eq(
            TARGET_ASSET_KEY
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

    team_sets = merged.apply(
        row_team_tokens,
        axis=1,
    )

    multi_seed_team_match = team_sets.map(
        lambda teams: len(
            teams
            & seed_teams
        )
        >= 2
    )

    year_match = pd.to_numeric(
        merged[
            "draft_year"
        ],
        errors="coerce",
    ).isin(
        referenced_years
    )

    seed_origin_match = (
        year_match
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

    selected_mask = (
        target_group_match
        | target_asset_match
        | exact_text_match
        | (
            year_match
            & multi_seed_team_match
        )
        | seed_origin_match
    )

    selected = merged.loc[
        selected_mask
    ].copy()

    selected[
        "match_target_group"
    ] = target_group_match.loc[
        selected.index
    ].astype(
        bool
    )

    selected[
        "match_target_asset"
    ] = target_asset_match.loc[
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
        "match_multi_seed_team_text"
    ] = (
        year_match.loc[
            selected.index
        ]
        & multi_seed_team_match.loc[
            selected.index
        ]
    ).astype(
        bool
    )

    selected[
        "match_seed_originating_team"
    ] = seed_origin_match.loc[
        selected.index
    ].astype(
        bool
    )

    return selected.sort_values(
        [
            "match_target_group",
            "match_exact_normalized_text",
            "match_target_asset",
            "draft_year",
            "round_number",
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
            True,
        ],
    ).reset_index(
        drop=True
    )


def extract_source_candidates(
    group_claims: pd.DataFrame,
    merged: pd.DataFrame,
    year_round_references: pd.DataFrame,
) -> pd.DataFrame:
    candidate_keys = {
        TARGET_ASSET_KEY
    }

    combined_text = " ".join(
        group_claims[
            "_combined_text"
        ]
        .fillna("")
        .astype(
            str
        )
        .tolist()
    )

    mentioned_teams = set(
        PRIMARY_TARGET_TEAMS
    )

    for team, pattern in TEAM_NAME_PATTERNS.items():
        if re.search(
            pattern,
            combined_text,
            re.IGNORECASE,
        ):
            mentioned_teams.add(
                team
            )

    reference_rows = year_round_references.copy()

    for row in reference_rows.itertuples(
        index=False
    ):
        year = int(
            row.referenced_year
        )

        if not (
            2027
            <= year
            <= 2029
        ):
            continue

        rounds = {
            int(
                token
            )
            for token in str(
                row.referenced_rounds
            ).split(
                "|"
            )
            if token.strip()
            in {
                "1",
                "2",
            }
        }

        if not rounds:
            rounds = {
                1,
                2,
            }

        teams = {
            token
            for token in str(
                row.referenced_teams
            ).split(
                "|"
            )
            if token
        }

        if not teams:
            teams = mentioned_teams

        for round_number in rounds:
            for team in teams:
                candidate_keys.add(
                    f"{year}_R{round_number}_{team}"
                )

    for team in mentioned_teams:
        candidate_keys.add(
            f"2029_R1_{team}"
        )
        candidate_keys.add(
            f"2029_R2_{team}"
        )

    rows = []

    for asset_key in sorted(
        candidate_keys
    ):
        matches = merged.loc[
            merged[
                "asset_key"
            ]
            .astype(
                str
            )
            .eq(
                asset_key
            )
        ]

        parts = asset_key.split(
            "_"
        )

        rows.append(
            {
                "candidate_asset_key": asset_key,
                "candidate_draft_year": (
                    int(
                        parts[
                            0
                        ]
                    )
                    if len(
                        parts
                    )
                    >= 4
                    and parts[
                        0
                    ].isdigit()
                    else np.nan
                ),
                "candidate_round_number": (
                    int(
                        parts[
                            1
                        ][
                            1:
                        ]
                    )
                    if len(
                        parts
                    )
                    >= 4
                    and parts[
                        1
                    ].startswith(
                        "R"
                    )
                    else np.nan
                ),
                "candidate_source_team": (
                    parts[
                        -1
                    ]
                    if len(
                        parts
                    )
                    >= 4
                    else ""
                ),
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
                            "effective_obligation_group_id"
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
                    if not matches.empty
                    else ""
                ),
                "valuation_statuses": (
                    join_unique(
                        matches[
                            "valuation_status"
                        ]
                    )
                    if not matches.empty
                    else ""
                ),
                "is_target_unresolved_asset": bool(
                    asset_key
                    == TARGET_ASSET_KEY
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
                        "effective_obligation_group_id"
                    ]
                ),
                "valued_claim_rows": int(
                    valued_mask.sum()
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
                "candidate_beneficiary_teams": join_unique(
                    group[
                        "candidate_beneficiary_team"
                    ]
                ),
                "contains_target_group_claim": bool(
                    group[
                        "effective_obligation_group_id"
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
            "effective_obligation_group_id"
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
                "effective_obligation_group_id": group_id,
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
                    if "claim_type"
                    in group.columns
                    else pd.Series(
                        dtype=object
                    )
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
            "effective_obligation_group_id",
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


def determine_state(
    group_claims: pd.DataFrame,
    rule_fragments: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
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

    has_favorability = (
        "favorability_rule"
        in rule_types
    )

    has_protection = (
        "protection_rule"
        in rule_types
    )

    has_conditional = (
        "conditional_rule"
        in rule_types
    )

    has_rollover = bool(
        {
            "rollover_rule",
            "future_year_rule",
        }
        & rule_types
    )

    if (
        len(
            group_claims
        )
        == 1
        and group_claims[
            "asset_key"
        ]
        .astype(
            str
        )
        .nunique()
        == 1
        and has_swap
        and has_protection
        and has_rollover
    ):
        return (
            "protected_single_asset_swap_rollover_dependency_text_found",
            False,
            (
                "The expected Orlando 2029 first-round claim was found "
                "with swap, protection, and rollover or fallback language. "
                "Read the printed controlling text to identify the physical "
                "swap source, option holder, protection range, exercised "
                "branch, non-exercised or protected branch, replacement "
                "asset, and extinguishment rule before valuation."
                + (
                    " Explicit favorability language is present."
                    if has_favorability
                    else ""
                )
                + (
                    " Explicit conditional language is present."
                    if has_conditional
                    else ""
                )
            ),
        )

    return (
        "connected_protected_swap_rollover_text_found_manual_parse_required",
        False,
        (
            "The target Orlando claim was found, but its text did not match "
            "the expected protected single-asset swap and rollover form. "
            "Review the printed claim text and all connected assets before "
            "building the integration."
        ),
    )


def build_resolution_template(
    group_claims: pd.DataFrame,
    source_candidates: pd.DataFrame,
    diagnostic_state: str,
    diagnostic_note: str,
) -> pd.DataFrame:
    existing_candidates = source_candidates.loc[
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
                "unresolved_source_asset": TARGET_ASSET_KEY,
                "candidate_connected_assets": join_unique(
                    existing_candidates
                ),
                "confirmed_physical_swap_sources": "",
                "swap_option_holder": "",
                "swap_counterparty_or_pool": "",
                "swap_direction": "",
                "more_favorable_recipient": "",
                "less_favorable_recipient": "",
                "protection_range": "",
                "branch_when_swap_is_exercised": "",
                "branch_when_protection_hits": "",
                "retained_asset_owner": "",
                "replacement_or_rollover_asset_key": "",
                "replacement_year": "",
                "replacement_round": "",
                "extinguishment_rule": "",
                "out_of_horizon_tail": "",
                "existing_baselines_to_remove": "",
                "connected_components_to_preserve": "",
                "source_verified": "",
                "source_as_of_date": "",
                "manual_resolution_note": diagnostic_note,
            }
        ]
    )


def print_target_claim_text(
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
        "2029 ORL-MEM PROTECTED SWAP-ROLLOVER DIAGNOSTIC"
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

    rule_fragments = extract_rule_fragments(
        group_claims
    )

    clause_table = build_clause_table(
        group_claims
    )

    year_round_references = extract_year_round_references(
        group_claims
    )

    connected_claims = select_connected_claims(
        merged=merged,
        group_claims=group_claims,
        year_round_references=year_round_references,
    )

    source_candidates = extract_source_candidates(
        group_claims=group_claims,
        merged=merged,
        year_round_references=year_round_references,
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

    (
        diagnostic_state,
        automatic_value_ready,
        diagnostic_note,
    ) = determine_state(
        group_claims=group_claims,
        rule_fragments=rule_fragments,
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

    year_round_references.to_csv(
        YEAR_ROUND_REFERENCES_PATH,
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
        "target_asset_key": TARGET_ASSET_KEY,
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
                "effective_obligation_group_id"
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
        "candidate_asset_rows": int(
            len(
                source_candidates
            )
        ),
        "candidate_assets_with_claim_rows": int(
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
        "year_round_reference_rows": int(
            len(
                year_round_references
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
            "year_round_references": str(
                YEAR_ROUND_REFERENCES_PATH
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
        "2029 ORL-MEM PROTECTED SWAP-ROLLOVER DIAGNOSTIC CREATED"
    )
    print(
        "=" * 80
    )
    print(
        f"Target group: {TARGET_GROUP_ID}"
    )
    print(
        f"Target asset: {TARGET_ASSET_KEY}"
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
        f"Connected claim rows: {len(connected_claims):,}"
    )
    print(
        "Connected unique assets: "
        f"{connected_claims['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Connected obligation groups: "
        f"{connected_claims['effective_obligation_group_id'].fillna('').astype(str).replace('', np.nan).nunique():,}"
    )
    print(
        "Candidate connected assets with claim rows: "
        f"{int(source_candidates['claim_row_exists'].fillna(False).astype(bool).sum()):,}"
    )
    print(
        f"Rule fragments extracted: {len(rule_fragments):,}"
    )
    print(
        f"Clause rows created: {len(clause_table):,}"
    )
    print(
        "Year-round reference rows: "
        f"{len(year_round_references):,}"
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
        "YEAR AND ROUND REFERENCES"
    )

    if year_round_references.empty:
        print(
            "No year-round references were extracted."
        )
    else:
        print(
            year_round_references.to_string(
                index=False
            )
        )

    print()

    print(
        "CANDIDATE CONNECTED ASSETS"
    )

    if source_candidates.empty:
        print(
            "No candidate connected assets were extracted."
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

    print_target_claim_text(
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
            "effective_obligation_group_id",
            "structural_family",
            "parsed_target_teams",
            "match_target_group",
            "match_target_asset",
            "match_exact_normalized_text",
            "match_multi_seed_team_text",
            "match_seed_originating_team",
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
        YEAR_ROUND_REFERENCES_PATH,
        SOURCE_CANDIDATES_PATH,
        GROUP_RELATIONSHIPS_PATH,
        VALUED_CONNECTED_CLAIMS_PATH,
        RESOLUTION_TEMPLATE_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()