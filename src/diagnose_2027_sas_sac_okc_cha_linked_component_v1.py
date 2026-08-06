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
    "future-pick-2027-sas-sac-okc-cha-linked-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SAS_GROUP_ID = "OBL_27a6e1df3f73"
CHA_GROUP_ID = "OBL_e29ca4df69da"

TARGET_CLAIM_IDS = {
    "2027_R1_SAS_C1",
    "2027_R2_CHA_C1",
}

PHYSICAL_SOURCE_ASSETS = {
    "2027_R1_SAS",
    "2027_R2_SAC",
    "2027_R2_CHA",
}

EXPECTED_SAS_TEXT_FRAGMENTS = [
    (
        "San Antonio's 2027 1st round pick to Sacramento "
        "protected for selections 17-30"
    ),
    (
        "to Oklahoma City protected for selections 1-16"
    ),
    (
        "if this pick falls within its protected range of 1-16"
    ),
    (
        "Sacramento will instead convey its 2027 2nd round pick "
        "and Charlotte's 2027 2nd round pick to Oklahoma City"
    ),
    (
        "San Antonio's obligation to Oklahoma City and Sacramento "
        "will thereafter be extinguished"
    ),
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
    / "future_pick_claim_value_layer_2027_2029_v20_lal_was_orl_enriched.parquet"
)

RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v20.csv"
)

RESIDUAL_GROUP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_dependency_group_audit_after_v20.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

LINKED_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_linked_claims_v1.csv"
)

SOURCE_ASSET_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_source_asset_audit_v1.csv"
)

BASELINE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_existing_baseline_audit_v1.csv"
)

RULE_FRAGMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_rule_fragments_v1.csv"
)

CLAUSE_TABLE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_clause_table_v1.csv"
)

BRANCH_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_branch_template_v1.csv"
)

GROUP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_group_audit_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_2027_sas_sac_okc_cha_linked_diagnostic_metadata_v1.json"
)

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


def finite_or_zero(
    value: Any,
) -> float:
    number = numeric_value(
        value
    )

    return (
        number
        if np.isfinite(
            number
        )
        else 0.0
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


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        RESIDUAL_CLAIM_AUDIT_PATH,
        RESIDUAL_GROUP_AUDIT_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required linked-diagnostic input was not found:\n"
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

    claim_audit = normalize_columns(
        pd.read_csv(
            RESIDUAL_CLAIM_AUDIT_PATH
        )
    )

    group_audit = normalize_columns(
        pd.read_csv(
            RESIDUAL_GROUP_AUDIT_PATH
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
        "V20 valuation layer",
    )

    require_columns(
        claim_audit,
        [
            "claim_id",
        ],
        "V20 residual claim audit",
    )

    require_columns(
        group_audit,
        [
            "effective_obligation_group_id",
            "review_order",
            "unique_asset_exposure_score",
        ],
        "V20 residual group audit",
    )

    return (
        claims,
        valuations,
        claim_audit,
        group_audit,
    )


def attach_audit_and_valuation_fields(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
    claim_audit: pd.DataFrame,
) -> pd.DataFrame:
    output = claims.copy()

    audit_columns = [
        column
        for column in [
            "claim_id",
            "effective_obligation_group_id",
            "obligation_group_id",
            "structural_family",
            "parsed_target_teams",
            "unconditional_asset_exposure_score",
        ]
        if column in claim_audit.columns
    ]

    if len(
        audit_columns
    ) > 1:
        audit = (
            claim_audit[
                audit_columns
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
                    for column in audit_columns
                }
            )
        )

        output = output.merge(
            audit,
            how="left",
            on="claim_id",
            validate="one_to_one",
        )

    valuation_columns = [
        column
        for column in VALUATION_COLUMNS
        if column in valuations.columns
    ]

    valuation = (
        valuations[
            valuation_columns
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
                for column in valuation_columns
            }
        )
    )

    output = output.merge(
        valuation,
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
            "obligation_group_id",
        ],
    )

    output[
        "structural_family"
    ] = first_nonempty_text(
        output,
        [
            "structural_family_audit",
            "structural_family",
        ],
    )

    output[
        "parsed_target_teams"
    ] = first_nonempty_text(
        output,
        [
            "parsed_target_teams_audit",
            "parsed_target_teams",
        ],
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


def select_linked_claims(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    linked = merged.loc[
        merged[
            "claim_id"
        ]
        .astype(
            str
        )
        .isin(
            TARGET_CLAIM_IDS
        )
    ].copy()

    found_claim_ids = set(
        linked[
            "claim_id"
        ].astype(
            str
        )
    )

    if found_claim_ids != TARGET_CLAIM_IDS:
        raise ValueError(
            "The linked target claim set changed.\nExpected:\n"
            + "\n".join(
                sorted(
                    TARGET_CLAIM_IDS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_claim_ids
                )
            )
        )

    return linked.sort_values(
        [
            "draft_year",
            "round_number",
            "asset_key",
        ]
    ).reset_index(
        drop=True
    )


def validate_sas_controlling_text(
    linked_claims: pd.DataFrame,
) -> tuple[
    bool,
    list[str],
]:
    sas_rows = linked_claims.loc[
        linked_claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            "2027_R1_SAS_C1"
        )
    ]

    if len(
        sas_rows
    ) != 1:
        raise ValueError(
            "Expected exactly one San Antonio controlling claim."
        )

    text = normalized_text(
        sas_rows.iloc[
            0
        ][
            "_combined_text"
        ]
    )

    missing = [
        fragment
        for fragment in EXPECTED_SAS_TEXT_FRAGMENTS
        if normalized_text(
            fragment
        )
        not in text
    ]

    return (
        not missing,
        missing,
    )


def extract_rule_fragments(
    linked_claims: pd.DataFrame,
) -> pd.DataFrame:
    patterns = {
        "protection_rule": (
            r"[^.;]*\b(?:protected|protection|top[- ]?\d+|"
            r"selections?\s*\d+\s*(?:through|-|to)\s*\d+)\b[^.;]*"
        ),
        "conditional_rule": (
            r"[^.;]*\b(?:if|unless|provided that|only if|conditional|"
            r"should)\b[^.;]*"
        ),
        "conveyance_rule": (
            r"[^.;]*\b(?:convey|conveys|conveyed|receive|receives|"
            r"transfer|transfers|transferred)\b[^.;]*"
        ),
        "extinguishment_rule": (
            r"[^.;]*\b(?:extinguish|extinguished|terminate|terminated)"
            r"\b[^.;]*"
        ),
        "destination_rule": (
            r"[^.;]*\b(?:to Sacramento|to Oklahoma City|"
            r"to San Antonio)\b[^.;]*"
        ),
    }

    rows: list[
        dict[str, Any]
    ] = []

    for _, row in linked_claims.iterrows():
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
    linked_claims: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in linked_claims.iterrows():
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
                    "contains_protection": bool(
                        re.search(
                            r"\b(?:protected|protection|top[- ]?\d+|"
                            r"selections?\s*\d+\s*(?:through|-|to)\s*\d+)"
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
                    "contains_extinguishment": bool(
                        re.search(
                            r"\b(?:extinguish|extinguished|terminate|"
                            r"terminated)\b",
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


def build_source_asset_audit(
    merged: pd.DataFrame,
) -> pd.DataFrame:
    source_rows = merged.loc[
        merged[
            "asset_key"
        ]
        .astype(
            str
        )
        .isin(
            PHYSICAL_SOURCE_ASSETS
        )
    ].copy()

    found_assets = set(
        source_rows[
            "asset_key"
        ].astype(
            str
        )
    )

    if found_assets != PHYSICAL_SOURCE_ASSETS:
        raise ValueError(
            "The linked physical source set is incomplete.\nExpected:\n"
            + "\n".join(
                sorted(
                    PHYSICAL_SOURCE_ASSETS
                )
            )
            + "\nFound:\n"
            + "\n".join(
                sorted(
                    found_assets
                )
            )
        )

    columns = [
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
            "effective_obligation_group_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
        ]
        if column in source_rows.columns
    ]

    return source_rows[
        columns
    ].sort_values(
        [
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def build_baseline_audit(
    source_asset_audit: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, row in source_asset_audit.iterrows():
        valuation_status = clean_text(
            row.get(
                "valuation_status",
                "",
            )
        )

        is_valued = valuation_status.startswith(
            "valued_"
        )

        transferred = finite_or_zero(
            row.get(
                "expected_transferred_value_score",
                np.nan,
            )
        )

        retained = finite_or_zero(
            row.get(
                "expected_retained_value_score",
                np.nan,
            )
        )

        swap_value = finite_or_zero(
            row.get(
                "expected_swap_option_value_score",
                np.nan,
            )
        )

        total = numeric_value(
            row.get(
                "expected_total_candidate_asset_value_score",
                np.nan,
            )
        )

        if not np.isfinite(
            total
        ):
            total = (
                transferred
                + retained
                + swap_value
            )

        baseline_value = (
            total
            if is_valued
            and np.isfinite(
                total
            )
            else 0.0
        )

        rows.append(
            {
                "claim_id": clean_text(
                    row.get(
                        "claim_id",
                        "",
                    )
                ),
                "asset_key": clean_text(
                    row.get(
                        "asset_key",
                        "",
                    )
                ),
                "candidate_beneficiary_team": clean_text(
                    row.get(
                        "candidate_beneficiary_team",
                        "",
                    )
                ),
                "valuation_method": clean_text(
                    row.get(
                        "valuation_method",
                        "",
                    )
                ),
                "valuation_status": valuation_status,
                "currently_counted_baseline_value_score": float(
                    baseline_value
                ),
                "baseline_is_currently_counted": bool(
                    baseline_value
                    > 0.0
                ),
                "required_linked_component_treatment": (
                    (
                        "remove_full_direct_baseline_and_replace_with_"
                        "conditional_retained_or_transferred_right"
                    )
                    if clean_text(
                        row.get(
                            "asset_key",
                            "",
                        )
                    )
                    == "2027_R2_SAC"
                    else (
                        "add_linked_conditional_source_value"
                        if clean_text(
                            row.get(
                                "asset_key",
                                "",
                            )
                        )
                        in {
                            "2027_R1_SAS",
                            "2027_R2_CHA",
                        }
                        else ""
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_group_audit(
    group_audit: pd.DataFrame,
) -> pd.DataFrame:
    target = group_audit.loc[
        group_audit[
            "effective_obligation_group_id"
        ]
        .fillna("")
        .astype(
            str
        )
        .isin(
            {
                SAS_GROUP_ID,
                CHA_GROUP_ID,
            }
        )
    ].copy()

    found_groups = set(
        target[
            "effective_obligation_group_id"
        ].astype(
            str
        )
    )

    if found_groups != {
        SAS_GROUP_ID,
        CHA_GROUP_ID,
    }:
        raise ValueError(
            "Both linked residual groups were not found.\nExpected:\n"
            f"{SAS_GROUP_ID}\n{CHA_GROUP_ID}\nFound:\n"
            + "\n".join(
                sorted(
                    found_groups
                )
            )
        )

    return target.sort_values(
        "review_order"
    ).reset_index(
        drop=True
    )


def build_branch_template(
    cha_claim_text: str,
) -> pd.DataFrame:
    cha_has_protection = bool(
        re.search(
            r"\b(?:protected|protection|top[- ]?\d+|"
            r"selections?\s*\d+\s*(?:through|-|to)\s*\d+)\b",
            cha_claim_text,
            re.IGNORECASE,
        )
    )

    cha_has_condition = bool(
        re.search(
            r"\b(?:if|unless|provided that|only if|conditional|"
            r"should)\b",
            cha_claim_text,
            re.IGNORECASE,
        )
    )

    return pd.DataFrame(
        [
            {
                "branch": "SAS_PICK_1_16",
                "branch_trigger": (
                    "San Antonio 2027 first lands in selections 1-16"
                ),
                "sas_first_recipient": "SAC",
                "sac_second_recipient": "OKC",
                "cha_second_recipient": (
                    "OKC, subject to exact Charlotte claim conveyance terms"
                ),
                "san_antonio_obligation_status": "extinguished_after_branch",
                "sacramento_obligation_status": "extinguished_after_branch",
                "existing_sac_second_baseline_treatment": (
                    "remove baseline and allocate source to OKC"
                ),
                "cha_second_claim_has_protection_language": (
                    cha_has_protection
                ),
                "cha_second_claim_has_conditional_language": (
                    cha_has_condition
                ),
                "remaining_resolution_needed": (
                    "Parse exact Charlotte 2027 second-round conveyance "
                    "condition and determine whether Oklahoma City receives "
                    "that source in every SAS 1-16 simulation."
                ),
            },
            {
                "branch": "SAS_PICK_17_30",
                "branch_trigger": (
                    "San Antonio 2027 first lands in selections 17-30"
                ),
                "sas_first_recipient": "OKC",
                "sac_second_recipient": "SAC",
                "cha_second_recipient": (
                    "Resolve independently from Charlotte claim"
                ),
                "san_antonio_obligation_status": "extinguished_after_branch",
                "sacramento_obligation_status": (
                    "fallback seconds not conveyed to OKC"
                ),
                "existing_sac_second_baseline_treatment": (
                    "remove baseline and replace with retained SAC right"
                ),
                "cha_second_claim_has_protection_language": (
                    cha_has_protection
                ),
                "cha_second_claim_has_conditional_language": (
                    cha_has_condition
                ),
                "remaining_resolution_needed": (
                    "Parse exact Charlotte claim to identify its ordinary "
                    "recipient and any non-conveyance branch."
                ),
            },
        ]
    )


def print_claim_text(
    linked_claims: pd.DataFrame,
) -> None:
    print(
        "LINKED CLAIM TEXT"
    )

    for _, row in linked_claims.iterrows():
        print(
            "-" * 80
        )
        print(
            "Claim: "
            f"{clean_text(row['claim_id'])} | "
            "Asset: "
            f"{clean_text(row['asset_key'])} | "
            "Group: "
            f"{clean_text(row['effective_obligation_group_id'])}"
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
        "2027 SAS-SAC-OKC-CHA LINKED COMPONENT DIAGNOSTIC"
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
        claim_audit,
        residual_group_audit,
    ) = load_inputs()

    merged = attach_audit_and_valuation_fields(
        claims=claims,
        valuations=valuations,
        claim_audit=claim_audit,
    )

    linked_claims = select_linked_claims(
        merged
    )

    (
        sas_text_validated,
        missing_sas_fragments,
    ) = validate_sas_controlling_text(
        linked_claims
    )

    if not sas_text_validated:
        raise ValueError(
            "The San Antonio controlling text changed. Missing fragments:\n"
            + "\n".join(
                missing_sas_fragments
            )
        )

    source_asset_audit = build_source_asset_audit(
        merged
    )

    baseline_audit = build_baseline_audit(
        source_asset_audit
    )

    linked_group_audit = build_group_audit(
        residual_group_audit
    )

    rule_fragments = extract_rule_fragments(
        linked_claims
    )

    clause_table = build_clause_table(
        linked_claims
    )

    cha_rows = linked_claims.loc[
        linked_claims[
            "claim_id"
        ]
        .astype(
            str
        )
        .eq(
            "2027_R2_CHA_C1"
        )
    ]

    if len(
        cha_rows
    ) != 1:
        raise ValueError(
            "Expected exactly one Charlotte 2027 second-round claim."
        )

    cha_claim_text = clean_text(
        cha_rows.iloc[
            0
        ][
            "_combined_text"
        ]
    )

    if not cha_claim_text:
        raise ValueError(
            "The Charlotte 2027 second-round claim text is blank."
        )

    branch_template = build_branch_template(
        cha_claim_text
    )

    linked_claims.to_csv(
        LINKED_CLAIMS_PATH,
        index=False,
    )

    source_asset_audit.to_csv(
        SOURCE_ASSET_AUDIT_PATH,
        index=False,
    )

    baseline_audit.to_csv(
        BASELINE_AUDIT_PATH,
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

    branch_template.to_csv(
        BRANCH_TEMPLATE_PATH,
        index=False,
    )

    linked_group_audit.to_csv(
        GROUP_AUDIT_PATH,
        index=False,
    )

    total_existing_baseline = float(
        baseline_audit[
            "currently_counted_baseline_value_score"
        ].sum()
    )

    sac_second_baseline = float(
        baseline_audit.loc[
            baseline_audit[
                "asset_key"
            ]
            .astype(
                str
            )
            .eq(
                "2027_R2_SAC"
            ),
            "currently_counted_baseline_value_score",
        ].sum()
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "linked_group_ids": [
            SAS_GROUP_ID,
            CHA_GROUP_ID,
        ],
        "linked_claim_ids": sorted(
            TARGET_CLAIM_IDS
        ),
        "physical_source_assets": sorted(
            PHYSICAL_SOURCE_ASSETS
        ),
        "sas_controlling_text_validated": sas_text_validated,
        "missing_sas_text_fragments": missing_sas_fragments,
        "linked_claim_rows": int(
            len(
                linked_claims
            )
        ),
        "source_asset_rows": int(
            len(
                source_asset_audit
            )
        ),
        "existing_counted_baseline_value_score": (
            total_existing_baseline
        ),
        "sac_second_existing_baseline_value_score": (
            sac_second_baseline
        ),
        "cha_second_claim_has_protection_language": bool(
            re.search(
                r"\b(?:protected|protection|top[- ]?\d+|"
                r"selections?\s*\d+\s*(?:through|-|to)\s*\d+)\b",
                cha_claim_text,
                re.IGNORECASE,
            )
        ),
        "cha_second_claim_has_conditional_language": bool(
            re.search(
                r"\b(?:if|unless|provided that|only if|conditional|"
                r"should)\b",
                cha_claim_text,
                re.IGNORECASE,
            )
        ),
        "diagnostic_state": (
            "linked_sas_first_and_charlotte_second_claim_text_found"
        ),
        "automatic_value_ready": False,
        "automatic_value_blocker": (
            "Charlotte 2027 second-round conveyance and protection terms "
            "must be read from the printed claim text before the three-source "
            "joint simulation is generated."
        ),
        "output_files": {
            "linked_claims": str(
                LINKED_CLAIMS_PATH
            ),
            "source_asset_audit": str(
                SOURCE_ASSET_AUDIT_PATH
            ),
            "existing_baseline_audit": str(
                BASELINE_AUDIT_PATH
            ),
            "rule_fragments": str(
                RULE_FRAGMENTS_PATH
            ),
            "clause_table": str(
                CLAUSE_TABLE_PATH
            ),
            "branch_template": str(
                BRANCH_TEMPLATE_PATH
            ),
            "group_audit": str(
                GROUP_AUDIT_PATH
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
        "LINKED SAS FIRST AND CHARLOTTE SECOND DIAGNOSTIC CREATED"
    )
    print(
        "=" * 80
    )
    print(
        "Linked residual groups: "
        f"{SAS_GROUP_ID}|{CHA_GROUP_ID}"
    )
    print(
        "Linked claim rows: "
        f"{len(linked_claims):,}"
    )
    print(
        "Physical source assets: "
        + "|".join(
            sorted(
                PHYSICAL_SOURCE_ASSETS
            )
        )
    )
    print(
        "San Antonio controlling text validated: "
        f"{sas_text_validated}"
    )
    print(
        "Existing counted source baseline: "
        f"{total_existing_baseline:.4f}"
    )
    print(
        "Sacramento second baseline: "
        f"{sac_second_baseline:.4f}"
    )
    print(
        "Charlotte claim contains protection language: "
        f"{metadata['cha_second_claim_has_protection_language']}"
    )
    print(
        "Charlotte claim contains conditional language: "
        f"{metadata['cha_second_claim_has_conditional_language']}"
    )
    print(
        "Diagnostic state: "
        f"{metadata['diagnostic_state']}"
    )
    print(
        "Automatic value ready: False"
    )
    print()

    print(
        "LINKED RESIDUAL GROUP AUDIT"
    )
    print(
        linked_group_audit.to_string(
            index=False
        )
    )
    print()

    print(
        "SOURCE ASSET AUDIT"
    )
    print(
        source_asset_audit.to_string(
            index=False
        )
    )
    print()

    print(
        "EXISTING BASELINE AUDIT"
    )
    print(
        baseline_audit.to_string(
            index=False
        )
    )
    print()

    print(
        "BRANCH TEMPLATE"
    )
    print(
        branch_template.to_string(
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
        linked_claims
    )

    print()
    print(
        "SAVED FILES"
    )

    for path in [
        LINKED_CLAIMS_PATH,
        SOURCE_ASSET_AUDIT_PATH,
        BASELINE_AUDIT_PATH,
        RULE_FRAGMENTS_PATH,
        CLAUSE_TABLE_PATH,
        BRANCH_TEMPLATE_PATH,
        GROUP_AUDIT_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()