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
    "future-pick-optimizer-inventory-reconciliation-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

FINAL_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_final.csv"
)

DIRECT_RIGHTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_direct_candidate_rows_v1.csv"
)

COMPONENT_RIGHTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_candidate_rights_discovery_v1.parquet"
)

COMPONENT_PRIMARY_ROWS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_component_primary_rows_v1.csv"
)

INVALID_V3_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

INVALID_V3_TEAM_RECONCILIATION_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_inventory_team_reconciliation_final.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

TEAM_DIAGNOSTIC_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_reconciliation_team_diagnostic_v1.csv"
)

POLICY_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_reconciliation_policy_summary_v1.csv"
)

POLICY_TEAM_COMPARISON_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_reconciliation_policy_team_comparison_v1.csv"
)

ROLE_CONTRIBUTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_claim_role_contributions_v1.csv"
)

ROW_ACCOUNTING_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_claim_row_accounting_diagnostic_v1.csv"
)

COMPONENT_FILE_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_component_file_value_reconciliation_v1.csv"
)

COMPONENT_TEAM_TOTALS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_component_team_totals_v1.csv"
)

CURRENT_DIRECT_METHOD_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_current_direct_method_summary_v1.csv"
)

ROLE_METHOD_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_role_method_summary_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_reconciliation_diagnostic_metadata_v1.json"
)


FINAL_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_final"
)

VALUE_TOLERANCE = 1e-6

EXPECTED_TEAM_ROWS = 30
EXPECTED_CURRENT_DIRECT_ROWS = 99
EXPECTED_COMPONENT_RIGHT_ROWS = 66


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


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
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


def finite_or_nan(
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
        else np.nan
    )


def finite_or_zero(
    value: Any,
) -> float:
    number = finite_or_nan(
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
            str(key): json_safe(item)
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
            json_safe(item)
            for item in value
        ]

    if isinstance(
        value,
        np.integer,
    ):
        return int(value)

    if isinstance(
        value,
        np.floating,
    ):
        return (
            None
            if np.isnan(value)
            else float(value)
        )

    if isinstance(
        value,
        float,
    ):
        return (
            None
            if math.isnan(value)
            else value
        )

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


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


def parse_source_assets(
    value: Any,
) -> list[str]:
    text = clean_text(
        value
    ).upper()

    if not text:
        return []

    return sorted(
        set(
            re.findall(
                r"20(?:27|28|29)_R[12]_[A-Z]{3}",
                text,
            )
        )
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        FINAL_VALUATION_PATH,
        FINAL_TEAM_SUMMARY_PATH,
        DIRECT_RIGHTS_PATH,
        COMPONENT_RIGHTS_PATH,
        COMPONENT_PRIMARY_ROWS_PATH,
        INVALID_V3_INVENTORY_PATH,
        INVALID_V3_TEAM_RECONCILIATION_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required reconciliation input was not found:\n"
                f"{path}"
            )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            FINAL_TEAM_SUMMARY_PATH
        )
    )

    direct_rights = normalize_columns(
        pd.read_csv(
            DIRECT_RIGHTS_PATH
        )
    )

    component_rights = normalize_columns(
        pd.read_parquet(
            COMPONENT_RIGHTS_PATH
        )
    )

    component_primary_rows = normalize_columns(
        pd.read_csv(
            COMPONENT_PRIMARY_ROWS_PATH
        )
    )

    invalid_inventory = normalize_columns(
        pd.read_parquet(
            INVALID_V3_INVENTORY_PATH
        )
    )

    invalid_team_reconciliation = normalize_columns(
        pd.read_csv(
            INVALID_V3_TEAM_RECONCILIATION_PATH
        )
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
            "valuation_status",
        ],
        "Canonical valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            FINAL_VALUE_COLUMN,
        ],
        "Canonical team summary",
    )

    require_columns(
        direct_rights,
        [
            "claim_id",
            "asset_key",
            "candidate_team",
            "candidate_asset_value_score",
            "valuation_method",
        ],
        "Current direct-right rows",
    )

    require_columns(
        component_rights,
        [
            "candidate_right_file",
            "candidate_team",
            "expected_candidate_right_value_score",
            "source_assets",
        ],
        "Component candidate rights",
    )

    require_columns(
        component_primary_rows,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
            "source_asset_value_score",
        ],
        "Component primary source rows",
    )

    return (
        valuations,
        team_summary,
        direct_rights,
        component_rights,
        component_primary_rows,
        invalid_inventory,
        invalid_team_reconciliation,
    )


def active_non_source_rows(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    method = (
        valuations[
            "valuation_method"
        ]
        .fillna("")
        .astype(str)
    )

    status = (
        valuations[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
    )

    source_mask = (
        method.str.contains(
            "_source_allocation",
            regex=False,
        )
        | status.eq(
            "valued_source_asset_fully_allocated"
        )
    )

    return valuations.loc[
        ~source_mask
    ].copy()


def append_contribution(
    rows: list[dict[str, Any]],
    *,
    source_row: pd.Series,
    policy: str,
    role: str,
    candidate_team: str,
    value: float,
    value_column: str,
) -> None:
    team = clean_text(
        candidate_team
    ).upper()

    if (
        not team
        or not np.isfinite(
            value
        )
        or abs(
            value
        )
        <= 1e-14
    ):
        return

    rows.append(
        {
            "policy": policy,
            "claim_id": clean_text(
                source_row.get(
                    "claim_id",
                    "",
                )
            ),
            "asset_key": clean_text(
                source_row.get(
                    "asset_key",
                    "",
                )
            ),
            "valuation_method": clean_text(
                source_row.get(
                    "valuation_method",
                    "",
                )
            ),
            "valuation_status": clean_text(
                source_row.get(
                    "valuation_status",
                    "",
                )
            ),
            "candidate_team": team,
            "assigned_role": role,
            "assigned_value_score": float(
                value
            ),
            "source_value_column": value_column,
            "candidate_beneficiary_team": clean_text(
                source_row.get(
                    "candidate_beneficiary_team",
                    "",
                )
            ).upper(),
            "candidate_retaining_team": clean_text(
                source_row.get(
                    "candidate_retaining_team",
                    "",
                )
            ).upper(),
            "candidate_counterparty_team": clean_text(
                source_row.get(
                    "candidate_counterparty_team",
                    "",
                )
            ).upper(),
            "expected_transferred_value_score": finite_or_nan(
                source_row.get(
                    "expected_transferred_value_score",
                    np.nan,
                )
            ),
            "expected_retained_value_score": finite_or_nan(
                source_row.get(
                    "expected_retained_value_score",
                    np.nan,
                )
            ),
            "expected_swap_option_value_score": finite_or_nan(
                source_row.get(
                    "expected_swap_option_value_score",
                    np.nan,
                )
            ),
            "expected_total_candidate_asset_value_score": (
                finite_or_nan(
                    source_row.get(
                        "expected_total_candidate_asset_value_score",
                        np.nan,
                    )
                )
            ),
        }
    )


def build_role_contributions(
    valuations: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    rows = []
    accounting_rows = []

    active = active_non_source_rows(
        valuations
    )

    for _, source_row in active.iterrows():
        beneficiary = clean_text(
            source_row.get(
                "candidate_beneficiary_team",
                "",
            )
        ).upper()

        retaining = clean_text(
            source_row.get(
                "candidate_retaining_team",
                "",
            )
        ).upper()

        counterparty = clean_text(
            source_row.get(
                "candidate_counterparty_team",
                "",
            )
        ).upper()

        transferred = finite_or_nan(
            source_row.get(
                "expected_transferred_value_score",
                np.nan,
            )
        )

        retained = finite_or_nan(
            source_row.get(
                "expected_retained_value_score",
                np.nan,
            )
        )

        swap_option = finite_or_nan(
            source_row.get(
                "expected_swap_option_value_score",
                np.nan,
            )
        )

        total = finite_or_nan(
            source_row.get(
                "expected_total_candidate_asset_value_score",
                np.nan,
            )
        )

        finite_role_values = [
            value
            for value in [
                transferred,
                retained,
                swap_option,
            ]
            if np.isfinite(
                value
            )
        ]

        role_sum = float(
            sum(
                finite_role_values
            )
        )

        has_role_detail = bool(
            finite_role_values
        )

        remainder = (
            float(
                total
                - role_sum
            )
            if (
                np.isfinite(
                    total
                )
                and has_role_detail
            )
            else np.nan
        )

        accounting_rows.append(
            {
                "claim_id": clean_text(
                    source_row.get(
                        "claim_id",
                        "",
                    )
                ),
                "asset_key": clean_text(
                    source_row.get(
                        "asset_key",
                        "",
                    )
                ),
                "valuation_method": clean_text(
                    source_row.get(
                        "valuation_method",
                        "",
                    )
                ),
                "valuation_status": clean_text(
                    source_row.get(
                        "valuation_status",
                        "",
                    )
                ),
                "candidate_beneficiary_team": beneficiary,
                "candidate_retaining_team": retaining,
                "candidate_counterparty_team": counterparty,
                "expected_transferred_value_score": transferred,
                "expected_retained_value_score": retained,
                "expected_swap_option_value_score": swap_option,
                "expected_total_candidate_asset_value_score": total,
                "finite_role_value_sum": role_sum,
                "total_minus_role_sum": remainder,
                "has_role_detail": has_role_detail,
                "total_matches_role_sum": bool(
                    np.isfinite(
                        total
                    )
                    and abs(
                        total
                        - role_sum
                    )
                    <= VALUE_TOLERANCE
                ),
            }
        )

        # Policy: total value goes to the listed beneficiary.
        if (
            beneficiary
            and np.isfinite(
                total
            )
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="total_to_beneficiary",
                role="beneficiary_total",
                candidate_team=beneficiary,
                value=total,
                value_column=(
                    "expected_total_candidate_asset_value_score"
                ),
            )

        # Policy: split transfer, retained value, and option value
        # among their corresponding roles. The swap option is held by
        # the beneficiary under the candidate-right schema.
        if np.isfinite(
            transferred
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_beneficiary",
                role="beneficiary_transferred",
                candidate_team=beneficiary,
                value=transferred,
                value_column="expected_transferred_value_score",
            )

        if np.isfinite(
            retained
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_beneficiary",
                role="retaining_retained",
                candidate_team=retaining,
                value=retained,
                value_column="expected_retained_value_score",
            )

        if np.isfinite(
            swap_option
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_beneficiary",
                role="beneficiary_swap_option",
                candidate_team=beneficiary,
                value=swap_option,
                value_column="expected_swap_option_value_score",
            )

        if (
            not has_role_detail
            and beneficiary
            and np.isfinite(
                total
            )
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_beneficiary",
                role="beneficiary_total_fallback",
                candidate_team=beneficiary,
                value=total,
                value_column=(
                    "expected_total_candidate_asset_value_score"
                ),
            )

        # Same split, but any value remaining beyond the explicit role
        # columns is assigned to the beneficiary.
        for role, team, value, column in [
            (
                "beneficiary_transferred",
                beneficiary,
                transferred,
                "expected_transferred_value_score",
            ),
            (
                "retaining_retained",
                retaining,
                retained,
                "expected_retained_value_score",
            ),
            (
                "beneficiary_swap_option",
                beneficiary,
                swap_option,
                "expected_swap_option_value_score",
            ),
        ]:
            if np.isfinite(
                value
            ):
                append_contribution(
                    rows,
                    source_row=source_row,
                    policy=(
                        "role_split_plus_remainder_to_beneficiary"
                    ),
                    role=role,
                    candidate_team=team,
                    value=value,
                    value_column=column,
                )

        if (
            not has_role_detail
            and beneficiary
            and np.isfinite(
                total
            )
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy=(
                    "role_split_plus_remainder_to_beneficiary"
                ),
                role="beneficiary_total_fallback",
                candidate_team=beneficiary,
                value=total,
                value_column=(
                    "expected_total_candidate_asset_value_score"
                ),
            )
        elif (
            beneficiary
            and np.isfinite(
                remainder
            )
            and abs(
                remainder
            )
            > 1e-14
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy=(
                    "role_split_plus_remainder_to_beneficiary"
                ),
                role="beneficiary_unallocated_remainder",
                candidate_team=beneficiary,
                value=remainder,
                value_column="total_minus_role_sum",
            )

        # Alternative test: assign swap-option value to the explicitly
        # listed counterparty. This is diagnostic only.
        if np.isfinite(
            transferred
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_counterparty",
                role="beneficiary_transferred",
                candidate_team=beneficiary,
                value=transferred,
                value_column="expected_transferred_value_score",
            )

        if np.isfinite(
            retained
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_counterparty",
                role="retaining_retained",
                candidate_team=retaining,
                value=retained,
                value_column="expected_retained_value_score",
            )

        if np.isfinite(
            swap_option
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_counterparty",
                role="counterparty_swap_option",
                candidate_team=counterparty,
                value=swap_option,
                value_column="expected_swap_option_value_score",
            )

        if (
            not has_role_detail
            and beneficiary
            and np.isfinite(
                total
            )
        ):
            append_contribution(
                rows,
                source_row=source_row,
                policy="role_split_swap_to_counterparty",
                role="beneficiary_total_fallback",
                candidate_team=beneficiary,
                value=total,
                value_column=(
                    "expected_total_candidate_asset_value_score"
                ),
            )

    return (
        pd.DataFrame(
            rows
        ),
        pd.DataFrame(
            accounting_rows
        ),
    )


def current_direct_team_totals(
    direct_rights: pd.DataFrame,
) -> pd.DataFrame:
    return (
        direct_rights.assign(
            candidate_team=(
                direct_rights[
                    "candidate_team"
                ]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.strip()
            ),
            candidate_asset_value_score=pd.to_numeric(
                direct_rights[
                    "candidate_asset_value_score"
                ],
                errors="coerce",
            ).fillna(
                0.0
            ),
        )
        .groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            current_direct_right_rows=(
                "claim_id",
                "size",
            ),
            current_direct_value_score=(
                "candidate_asset_value_score",
                "sum",
            ),
        )
    )


def current_direct_method_summary(
    direct_rights: pd.DataFrame,
) -> pd.DataFrame:
    frame = direct_rights.copy()

    frame[
        "candidate_asset_value_score"
    ] = pd.to_numeric(
        frame[
            "candidate_asset_value_score"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    return (
        frame.groupby(
            [
                "valuation_method",
                "candidate_team",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            direct_rows=(
                "claim_id",
                "size",
            ),
            direct_value_score=(
                "candidate_asset_value_score",
                "sum",
            ),
        )
        .sort_values(
            [
                "valuation_method",
                "candidate_team",
            ]
        )
        .reset_index(
            drop=True
        )
    )


def role_method_summary(
    role_contributions: pd.DataFrame,
) -> pd.DataFrame:
    if role_contributions.empty:
        return pd.DataFrame()

    return (
        role_contributions.groupby(
            [
                "policy",
                "valuation_method",
                "candidate_team",
                "assigned_role",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            contribution_rows=(
                "claim_id",
                "size",
            ),
            contribution_value_score=(
                "assigned_value_score",
                "sum",
            ),
        )
        .sort_values(
            [
                "policy",
                "valuation_method",
                "candidate_team",
                "assigned_role",
            ]
        )
        .reset_index(
            drop=True
        )
    )


def component_team_totals(
    component_rights: pd.DataFrame,
) -> pd.DataFrame:
    frame = component_rights.copy()

    frame[
        "candidate_team"
    ] = (
        frame[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    frame[
        "expected_candidate_right_value_score"
    ] = pd.to_numeric(
        frame[
            "expected_candidate_right_value_score"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    return (
        frame.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            component_right_rows=(
                "candidate_right_file",
                "size",
            ),
            component_right_value_score=(
                "expected_candidate_right_value_score",
                "sum",
            ),
        )
    )


def component_file_reconciliation(
    component_rights: pd.DataFrame,
    component_primary_rows: pd.DataFrame,
) -> pd.DataFrame:
    primary = component_primary_rows.copy()

    primary[
        "asset_key"
    ] = (
        primary[
            "asset_key"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    primary[
        "source_asset_value_score"
    ] = pd.to_numeric(
        primary[
            "source_asset_value_score"
        ],
        errors="coerce",
    )

    rows = []

    for component_file, group in component_rights.groupby(
        "candidate_right_file",
        sort=True,
    ):
        source_assets = sorted(
            {
                asset
                for value in group[
                    "source_assets"
                ]
                for asset in parse_source_assets(
                    value
                )
            }
        )

        primary_matches = primary.loc[
            primary[
                "asset_key"
            ].isin(
                source_assets
            )
        ].copy()

        duplicate_primary_assets = int(
            primary_matches[
                "asset_key"
            ].duplicated().sum()
        )

        unique_primary = (
            primary_matches.sort_values(
                [
                    "asset_key",
                    "claim_id",
                ]
            )
            .drop_duplicates(
                subset=[
                    "asset_key",
                ],
                keep="first",
            )
        )

        candidate_value = float(
            pd.to_numeric(
                group[
                    "expected_candidate_right_value_score"
                ],
                errors="coerce",
            ).sum()
        )

        source_value = float(
            pd.to_numeric(
                unique_primary[
                    "source_asset_value_score"
                ],
                errors="coerce",
            ).sum(
                min_count=1
            )
        )

        source_value = (
            source_value
            if np.isfinite(
                source_value
            )
            else np.nan
        )

        difference = (
            candidate_value
            - source_value
            if np.isfinite(
                source_value
            )
            else np.nan
        )

        rows.append(
            {
                "candidate_right_file": component_file,
                "candidate_right_rows": int(
                    len(
                        group
                    )
                ),
                "candidate_teams": "|".join(
                    sorted(
                        set(
                            group[
                                "candidate_team"
                            ]
                            .fillna("")
                            .astype(str)
                        )
                    )
                ),
                "source_assets": "|".join(
                    source_assets
                ),
                "source_asset_count": len(
                    source_assets
                ),
                "primary_source_rows_found": int(
                    len(
                        primary_matches
                    )
                ),
                "unique_primary_sources_found": int(
                    unique_primary[
                        "asset_key"
                    ].nunique()
                ),
                "duplicate_primary_asset_rows": (
                    duplicate_primary_assets
                ),
                "candidate_right_value_score": (
                    candidate_value
                ),
                "primary_source_value_score": source_value,
                "candidate_minus_source_value": difference,
                "component_value_reconciliation_passed": bool(
                    np.isfinite(
                        difference
                    )
                    and abs(
                        difference
                    )
                    <= VALUE_TOLERANCE
                    and len(
                        source_assets
                    )
                    == unique_primary[
                        "asset_key"
                    ].nunique()
                ),
                "matched_valuation_methods": "|".join(
                    sorted(
                        set(
                            unique_primary[
                                "valuation_method"
                            ]
                            .fillna("")
                            .astype(str)
                        )
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "component_value_reconciliation_passed",
            "candidate_minus_source_value",
            "candidate_right_file",
        ],
        ascending=[
            True,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_policy_comparisons(
    team_summary: pd.DataFrame,
    component_totals: pd.DataFrame,
    current_direct_totals: pd.DataFrame,
    role_contributions: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    canonical = team_summary[
        [
            "candidate_beneficiary_team",
            FINAL_VALUE_COLUMN,
        ]
    ].copy()

    canonical = canonical.rename(
        columns={
            "candidate_beneficiary_team": "candidate_team",
            FINAL_VALUE_COLUMN: (
                "canonical_final_team_value_score"
            ),
        }
    )

    canonical[
        "candidate_team"
    ] = (
        canonical[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    canonical[
        "canonical_final_team_value_score"
    ] = pd.to_numeric(
        canonical[
            "canonical_final_team_value_score"
        ],
        errors="raise",
    )

    base = (
        canonical.merge(
            component_totals,
            how="left",
            on="candidate_team",
            validate="one_to_one",
        )
        .merge(
            current_direct_totals,
            how="left",
            on="candidate_team",
            validate="one_to_one",
        )
    )

    for column in [
        "component_right_rows",
        "component_right_value_score",
        "current_direct_right_rows",
        "current_direct_value_score",
    ]:
        base[
            column
        ] = pd.to_numeric(
            base[
                column
            ],
            errors="coerce",
        ).fillna(
            0.0
        )

    base[
        "canonical_direct_residual_value_score"
    ] = (
        base[
            "canonical_final_team_value_score"
        ]
        - base[
            "component_right_value_score"
        ]
    )

    base[
        "current_direct_minus_required"
    ] = (
        base[
            "current_direct_value_score"
        ]
        - base[
            "canonical_direct_residual_value_score"
        ]
    )

    policy_team_rows = []
    summary_rows = []

    current_policy = base.copy()

    current_policy[
        "policy"
    ] = "current_direct_file"

    current_policy[
        "policy_direct_value_score"
    ] = current_policy[
        "current_direct_value_score"
    ]

    policies = {
        "current_direct_file": current_policy[
            [
                "candidate_team",
                "policy_direct_value_score",
            ]
        ]
    }

    for policy, group in role_contributions.groupby(
        "policy",
        sort=True,
    ):
        totals = (
            group.groupby(
                "candidate_team",
                as_index=False,
            )
            .agg(
                policy_direct_value_score=(
                    "assigned_value_score",
                    "sum",
                )
            )
        )

        policies[
            policy
        ] = totals

    for policy, policy_totals in policies.items():
        comparison = base.merge(
            policy_totals,
            how="left",
            on="candidate_team",
            validate="one_to_one",
        )

        comparison[
            "policy_direct_value_score"
        ] = pd.to_numeric(
            comparison[
                "policy_direct_value_score"
            ],
            errors="coerce",
        ).fillna(
            0.0
        )

        comparison[
            "policy"
        ] = policy

        comparison[
            "policy_inventory_value_score"
        ] = (
            comparison[
                "policy_direct_value_score"
            ]
            + comparison[
                "component_right_value_score"
            ]
        )

        comparison[
            "policy_value_difference"
        ] = (
            comparison[
                "policy_inventory_value_score"
            ]
            - comparison[
                "canonical_final_team_value_score"
            ]
        )

        comparison[
            "absolute_policy_value_difference"
        ] = comparison[
            "policy_value_difference"
        ].abs()

        comparison[
            "policy_team_reconciliation_passed"
        ] = (
            comparison[
                "absolute_policy_value_difference"
            ]
            <= VALUE_TOLERANCE
        )

        policy_team_rows.append(
            comparison
        )

        summary_rows.append(
            {
                "policy": policy,
                "teams_reconciled": int(
                    comparison[
                        "policy_team_reconciliation_passed"
                    ].sum()
                ),
                "team_count": int(
                    len(
                        comparison
                    )
                ),
                "system_inventory_value_score": float(
                    comparison[
                        "policy_inventory_value_score"
                    ].sum()
                ),
                "canonical_system_value_score": float(
                    comparison[
                        "canonical_final_team_value_score"
                    ].sum()
                ),
                "system_value_difference": float(
                    comparison[
                        "policy_value_difference"
                    ].sum()
                ),
                "absolute_system_value_difference": float(
                    abs(
                        comparison[
                            "policy_value_difference"
                        ].sum()
                    )
                ),
                "total_absolute_team_difference": float(
                    comparison[
                        "absolute_policy_value_difference"
                    ].sum()
                ),
                "maximum_absolute_team_difference": float(
                    comparison[
                        "absolute_policy_value_difference"
                    ].max()
                ),
                "all_teams_reconciled": bool(
                    comparison[
                        "policy_team_reconciliation_passed"
                    ].all()
                ),
            }
        )

    policy_team_comparison = pd.concat(
        policy_team_rows,
        ignore_index=True,
        sort=False,
    )

    policy_summary = pd.DataFrame(
        summary_rows
    ).sort_values(
        [
            "teams_reconciled",
            "total_absolute_team_difference",
            "absolute_system_value_difference",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )

    return (
        base.sort_values(
            "absolute_value_difference"
            if "absolute_value_difference" in base.columns
            else "current_direct_minus_required",
            ascending=False,
        ).reset_index(
            drop=True
        ),
        policy_summary,
        policy_team_comparison,
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER INVENTORY RECONCILIATION DIAGNOSTIC")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        valuations,
        team_summary,
        direct_rights,
        component_rights,
        component_primary_rows,
        invalid_inventory,
        invalid_team_reconciliation,
    ) = load_inputs()

    if len(
        team_summary
    ) != EXPECTED_TEAM_ROWS:
        raise RuntimeError(
            "Canonical team-summary row count changed."
        )

    if len(
        direct_rights
    ) != EXPECTED_CURRENT_DIRECT_ROWS:
        raise RuntimeError(
            "Current direct-right row count changed."
        )

    if len(
        component_rights
    ) != EXPECTED_COMPONENT_RIGHT_ROWS:
        raise RuntimeError(
            "Component candidate-right row count changed."
        )

    role_contributions, row_accounting = (
        build_role_contributions(
            valuations
        )
    )

    current_direct_totals = current_direct_team_totals(
        direct_rights
    )

    current_method_summary = current_direct_method_summary(
        direct_rights
    )

    role_summary = role_method_summary(
        role_contributions
    )

    component_totals = component_team_totals(
        component_rights
    )

    component_reconciliation = component_file_reconciliation(
        component_rights=component_rights,
        component_primary_rows=component_primary_rows,
    )

    (
        team_diagnostic,
        policy_summary,
        policy_team_comparison,
    ) = build_policy_comparisons(
        team_summary=team_summary,
        component_totals=component_totals,
        current_direct_totals=current_direct_totals,
        role_contributions=role_contributions,
    )

    current_v3 = invalid_team_reconciliation[
        [
            column
            for column in [
                "candidate_team",
                "optimizer_inventory_value_score",
                "canonical_final_team_value_score",
                "value_difference",
                "absolute_value_difference",
                "team_reconciliation_passed",
            ]
            if column in invalid_team_reconciliation.columns
        ]
    ].copy()

    if not current_v3.empty:
        current_v3 = current_v3.rename(
            columns={
                "optimizer_inventory_value_score": (
                    "v3_inventory_value_score"
                ),
                "canonical_final_team_value_score": (
                    "v3_canonical_value_score"
                ),
                "value_difference": (
                    "v3_value_difference"
                ),
                "absolute_value_difference": (
                    "v3_absolute_value_difference"
                ),
                "team_reconciliation_passed": (
                    "v3_team_reconciliation_passed"
                ),
            }
        )

        team_diagnostic = team_diagnostic.merge(
            current_v3,
            how="left",
            on="candidate_team",
            validate="one_to_one",
        )

    team_diagnostic[
        "current_direct_absolute_gap"
    ] = team_diagnostic[
        "current_direct_minus_required"
    ].abs()

    team_diagnostic = team_diagnostic.sort_values(
        [
            "current_direct_absolute_gap",
            "candidate_team",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    team_diagnostic.to_csv(
        TEAM_DIAGNOSTIC_PATH,
        index=False,
    )

    policy_summary.to_csv(
        POLICY_SUMMARY_PATH,
        index=False,
    )

    policy_team_comparison.to_csv(
        POLICY_TEAM_COMPARISON_PATH,
        index=False,
    )

    role_contributions.to_csv(
        ROLE_CONTRIBUTIONS_PATH,
        index=False,
    )

    row_accounting.to_csv(
        ROW_ACCOUNTING_PATH,
        index=False,
    )

    component_reconciliation.to_csv(
        COMPONENT_FILE_RECONCILIATION_PATH,
        index=False,
    )

    component_totals.to_csv(
        COMPONENT_TEAM_TOTALS_PATH,
        index=False,
    )

    current_method_summary.to_csv(
        CURRENT_DIRECT_METHOD_SUMMARY_PATH,
        index=False,
    )

    role_summary.to_csv(
        ROLE_METHOD_SUMMARY_PATH,
        index=False,
    )

    mismatched_teams = team_diagnostic.loc[
        team_diagnostic[
            "current_direct_absolute_gap"
        ]
        > VALUE_TOLERANCE
    ]

    failed_components = component_reconciliation.loc[
        ~component_reconciliation[
            "component_value_reconciliation_passed"
        ]
    ]

    best_policy = (
        policy_summary.iloc[
            0
        ].to_dict()
        if not policy_summary.empty
        else {}
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "canonical_team_rows": int(
            len(
                team_summary
            )
        ),
        "current_direct_rows": int(
            len(
                direct_rights
            )
        ),
        "component_candidate_right_rows": int(
            len(
                component_rights
            )
        ),
        "invalid_v3_inventory_rows": int(
            len(
                invalid_inventory
            )
        ),
        "current_mismatched_teams": int(
            len(
                mismatched_teams
            )
        ),
        "component_files_checked": int(
            len(
                component_reconciliation
            )
        ),
        "component_files_failed_value_reconciliation": int(
            len(
                failed_components
            )
        ),
        "policies_tested": int(
            len(
                policy_summary
            )
        ),
        "best_policy": json_safe(
            best_policy
        ),
        "output_files": {
            "team_diagnostic": str(
                TEAM_DIAGNOSTIC_PATH
            ),
            "policy_summary": str(
                POLICY_SUMMARY_PATH
            ),
            "policy_team_comparison": str(
                POLICY_TEAM_COMPARISON_PATH
            ),
            "role_contributions": str(
                ROLE_CONTRIBUTIONS_PATH
            ),
            "row_accounting": str(
                ROW_ACCOUNTING_PATH
            ),
            "component_file_reconciliation": str(
                COMPONENT_FILE_RECONCILIATION_PATH
            ),
            "component_team_totals": str(
                COMPONENT_TEAM_TOTALS_PATH
            ),
            "current_direct_method_summary": str(
                CURRENT_DIRECT_METHOD_SUMMARY_PATH
            ),
            "role_method_summary": str(
                ROLE_METHOD_SUMMARY_PATH
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
    print("RECONCILIATION DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        "Canonical teams: "
        f"{len(team_summary):,}"
    )
    print(
        "Current direct rows: "
        f"{len(direct_rights):,}"
    )
    print(
        "Component candidate-right rows: "
        f"{len(component_rights):,}"
    )
    print(
        "Current mismatched teams: "
        f"{len(mismatched_teams):,}"
    )
    print(
        "Component files checked: "
        f"{len(component_reconciliation):,}"
    )
    print(
        "Component files failing source-value reconciliation: "
        f"{len(failed_components):,}"
    )
    print(
        "Accounting policies tested: "
        f"{len(policy_summary):,}"
    )
    print()

    print("POLICY SUMMARY")
    display_policies = policy_summary.copy()

    for column in [
        "system_inventory_value_score",
        "canonical_system_value_score",
        "system_value_difference",
        "absolute_system_value_difference",
        "total_absolute_team_difference",
        "maximum_absolute_team_difference",
    ]:
        display_policies[
            column
        ] = pd.to_numeric(
            display_policies[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_policies.to_string(
            index=False
        )
    )
    print()

    print("CURRENT TEAM GAPS")
    display_teams = team_diagnostic.loc[
        team_diagnostic[
            "current_direct_absolute_gap"
        ]
        > VALUE_TOLERANCE
    ].copy()

    display_columns = [
        column
        for column in [
            "candidate_team",
            "canonical_final_team_value_score",
            "component_right_value_score",
            "canonical_direct_residual_value_score",
            "current_direct_value_score",
            "current_direct_minus_required",
            "v3_value_difference",
        ]
        if column in display_teams.columns
    ]

    for column in display_columns:
        if column != "candidate_team":
            display_teams[
                column
            ] = pd.to_numeric(
                display_teams[
                    column
                ],
                errors="coerce",
            ).round(
                6
            )

    if display_teams.empty:
        print(
            "No current team gaps remain."
        )
    else:
        print(
            display_teams[
                display_columns
            ].to_string(
                index=False
            )
        )

    print()
    print("COMPONENT FILE VALUE RECONCILIATION FAILURES")

    if failed_components.empty:
        print(
            "Every component candidate-right file reconciles to its "
            "matched physical source values."
        )
    else:
        display_components = failed_components.copy()

        for column in [
            "candidate_right_value_score",
            "primary_source_value_score",
            "candidate_minus_source_value",
        ]:
            display_components[
                column
            ] = pd.to_numeric(
                display_components[
                    column
                ],
                errors="coerce",
            ).round(
                6
            )

        print(
            display_components.to_string(
                index=False
            )
        )

    print()
    print("ROWS WHERE TOTAL VALUE DOES NOT MATCH ROLE-SPLIT VALUES")

    row_gaps = row_accounting.loc[
        row_accounting[
            "expected_total_candidate_asset_value_score"
        ].notna()
        & (
            row_accounting[
                "total_minus_role_sum"
            ].abs()
            > VALUE_TOLERANCE
        )
    ].copy()

    if row_gaps.empty:
        print(
            "No row-level total-versus-role gaps were found."
        )
    else:
        display_row_columns = [
            "claim_id",
            "asset_key",
            "valuation_method",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "finite_role_value_sum",
            "total_minus_role_sum",
        ]

        for column in display_row_columns:
            if (
                column
                not in {
                    "claim_id",
                    "asset_key",
                    "valuation_method",
                    "candidate_beneficiary_team",
                    "candidate_retaining_team",
                    "candidate_counterparty_team",
                }
            ):
                row_gaps[
                    column
                ] = pd.to_numeric(
                    row_gaps[
                        column
                    ],
                    errors="coerce",
                ).round(
                    6
                )

        print(
            row_gaps[
                display_row_columns
            ].to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")

    for path in [
        TEAM_DIAGNOSTIC_PATH,
        POLICY_SUMMARY_PATH,
        POLICY_TEAM_COMPARISON_PATH,
        ROLE_CONTRIBUTIONS_PATH,
        ROW_ACCOUNTING_PATH,
        COMPONENT_FILE_RECONCILIATION_PATH,
        COMPONENT_TEAM_TOTALS_PATH,
        CURRENT_DIRECT_METHOD_SUMMARY_PATH,
        ROLE_METHOD_SUMMARY_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()
