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
    "future-pick-optimizer-remaining-gap-diagnostic-v3-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POLICY_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_policy_summary_v1.csv"
)

POLICY_TEAM_COMPARISON_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_policy_team_comparison_v1.csv"
)

ROLE_CONTRIBUTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_claim_role_contributions_v1.csv"
)

ROW_ACCOUNTING_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_claim_row_accounting_diagnostic_v1.csv"
)

CURRENT_TEAM_DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_team_diagnostic_v1.csv"
)

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
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

REJECTED_V3_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

BEST_POLICY_REMAINING_TEAMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_best_policy_remaining_teams_v2.csv"
)

BEST_POLICY_CLAIM_EFFECTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_best_policy_claim_effects_v2.csv"
)

REMAINING_TEAM_CLAIM_INVOLVEMENT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_claim_involvement_v2.csv"
)

SOURCE_VALUE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_canonical_source_value_candidates_v2.csv"
)

LEGACY_COMPONENT_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_legacy_component_reconciliation_v2.csv"
)

LEGACY_COMPONENT_TEAM_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_legacy_component_team_rows_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_gap_diagnostic_metadata_v2.json"
)


VALUE_TOLERANCE = 1e-6

LEGACY_COMPONENT_FILES = {
    "future_pick_2027_eight_second_candidate_rights_v1.parquet",
    "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet",
    "future_pick_denver_joint_candidate_rights_v1.parquet",
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
    return sorted(
        set(
            re.findall(
                r"20(?:27|28|29)_R[12]_[A-Z]{3}",
                clean_text(
                    value
                ).upper(),
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
    pd.DataFrame,
    pd.DataFrame,
]:
    paths = [
        POLICY_SUMMARY_PATH,
        POLICY_TEAM_COMPARISON_PATH,
        ROLE_CONTRIBUTIONS_PATH,
        ROW_ACCOUNTING_PATH,
        CURRENT_TEAM_DIAGNOSTIC_PATH,
        FINAL_VALUATION_PATH,
        DIRECT_RIGHTS_PATH,
        COMPONENT_RIGHTS_PATH,
        REJECTED_V3_INVENTORY_PATH,
    ]

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required focused-diagnostic input was not found:\n"
                f"{path}"
            )

    policy_summary = normalize_columns(
        pd.read_csv(
            POLICY_SUMMARY_PATH
        )
    )

    policy_teams = normalize_columns(
        pd.read_csv(
            POLICY_TEAM_COMPARISON_PATH
        )
    )

    role_contributions = normalize_columns(
        pd.read_csv(
            ROLE_CONTRIBUTIONS_PATH
        )
    )

    row_accounting = normalize_columns(
        pd.read_csv(
            ROW_ACCOUNTING_PATH
        )
    )

    current_teams = normalize_columns(
        pd.read_csv(
            CURRENT_TEAM_DIAGNOSTIC_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
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

    rejected_inventory = normalize_columns(
        pd.read_parquet(
            REJECTED_V3_INVENTORY_PATH
        )
    )

    require_columns(
        policy_summary,
        [
            "policy",
            "teams_reconciled",
            "total_absolute_team_difference",
        ],
        "Policy summary",
    )

    require_columns(
        policy_teams,
        [
            "policy",
            "candidate_team",
            "policy_value_difference",
            "absolute_policy_value_difference",
        ],
        "Policy team comparison",
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
        direct_rights,
        [
            "claim_id",
            "candidate_team",
            "candidate_asset_value_score",
        ],
        "Direct rights",
    )

    require_columns(
        rejected_inventory,
        [
            "right_origin",
            "candidate_team",
            "candidate_right_value_score",
            "source_assets",
            "component_right_file",
        ],
        "Rejected V3 inventory",
    )

    return (
        policy_summary,
        policy_teams,
        role_contributions,
        row_accounting,
        current_teams,
        valuations,
        direct_rights,
        component_rights,
        rejected_inventory,
    )


def select_best_policy(
    policy_summary: pd.DataFrame,
) -> str:
    ranked = policy_summary.sort_values(
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
    )

    return clean_text(
        ranked.iloc[
            0
        ][
            "policy"
        ]
    )


def build_remaining_teams(
    best_policy: str,
    policy_teams: pd.DataFrame,
    current_teams: pd.DataFrame,
) -> pd.DataFrame:
    output = policy_teams.loc[
        policy_teams[
            "policy"
        ]
        .fillna("")
        .astype(str)
        .eq(
            best_policy
        )
    ].copy()

    output[
        "absolute_policy_value_difference"
    ] = pd.to_numeric(
        output[
            "absolute_policy_value_difference"
        ],
        errors="coerce",
    )

    output = output.loc[
        output[
            "absolute_policy_value_difference"
        ]
        > VALUE_TOLERANCE
    ].copy()

    current_columns = [
        column
        for column in [
            "candidate_team",
            "current_direct_value_score",
            "canonical_direct_residual_value_score",
            "current_direct_minus_required",
            "v3_value_difference",
        ]
        if column in current_teams.columns
    ]

    current_subset = current_teams[
        current_columns
    ].drop_duplicates(
        subset=[
            "candidate_team",
        ]
    )

    output = output.merge(
        current_subset,
        how="left",
        on="candidate_team",
        validate="one_to_one",
        suffixes=(
            "",
            "_current",
        ),
    )

    return output.sort_values(
        [
            "absolute_policy_value_difference",
            "candidate_team",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_claim_effects(
    best_policy: str,
    role_contributions: pd.DataFrame,
    direct_rights: pd.DataFrame,
) -> pd.DataFrame:
    policy_rows = role_contributions.loc[
        role_contributions[
            "policy"
        ]
        .fillna("")
        .astype(str)
        .eq(
            best_policy
        )
    ].copy()

    policy_grouped = (
        policy_rows.groupby(
            [
                "claim_id",
                "candidate_team",
            ],
            as_index=False,
        )
        .agg(
            best_policy_value_score=(
                "assigned_value_score",
                "sum",
            ),
            best_policy_roles=(
                "assigned_role",
                lambda values: "|".join(
                    sorted(
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
                ),
            ),
            valuation_method=(
                "valuation_method",
                "first",
            ),
            asset_key=(
                "asset_key",
                "first",
            ),
        )
    )

    current = direct_rights.copy()

    current[
        "current_direct_value_score"
    ] = pd.to_numeric(
        current[
            "candidate_asset_value_score"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    current_grouped = (
        current.groupby(
            [
                "claim_id",
                "candidate_team",
            ],
            as_index=False,
        )
        .agg(
            current_direct_value_score=(
                "current_direct_value_score",
                "sum",
            ),
            current_valuation_method=(
                "valuation_method",
                "first",
            )
            if "valuation_method" in current.columns
            else (
                "claim_id",
                "size",
            ),
            current_asset_key=(
                "asset_key",
                "first",
            )
            if "asset_key" in current.columns
            else (
                "claim_id",
                "first",
            ),
        )
    )

    output = current_grouped.merge(
        policy_grouped,
        how="outer",
        on=[
            "claim_id",
            "candidate_team",
        ],
    )

    for column in [
        "current_direct_value_score",
        "best_policy_value_score",
    ]:
        output[
            column
        ] = pd.to_numeric(
            output[
                column
            ],
            errors="coerce",
        ).fillna(
            0.0
        )

    output[
        "best_policy_minus_current_value_score"
    ] = (
        output[
            "best_policy_value_score"
        ]
        - output[
            "current_direct_value_score"
        ]
    )

    output[
        "asset_key"
    ] = (
        output[
            "asset_key"
        ]
        .fillna(
            output[
                "current_asset_key"
            ]
        )
    )

    output[
        "valuation_method"
    ] = (
        output[
            "valuation_method"
        ]
        .fillna(
            output[
                "current_valuation_method"
            ]
        )
    )

    return output.sort_values(
        [
            "candidate_team",
            "best_policy_minus_current_value_score",
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


def build_remaining_team_involvement(
    remaining_teams: set[str],
    valuations: pd.DataFrame,
    direct_rights: pd.DataFrame,
    claim_effects: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    current_lookup = (
        direct_rights.groupby(
            "claim_id"
        )[
            [
                "candidate_team",
                "candidate_asset_value_score",
            ]
        ]
        .apply(
            lambda group: json.dumps(
                [
                    {
                        "candidate_team": clean_text(
                            row.candidate_team
                        ).upper(),
                        "candidate_asset_value_score": (
                            finite_or_nan(
                                row.candidate_asset_value_score
                            )
                        ),
                    }
                    for row in group.itertuples(
                        index=False
                    )
                ],
                sort_keys=True,
            )
        )
        .to_dict()
    )

    effect_lookup = (
        claim_effects.groupby(
            "claim_id"
        )[
            [
                "candidate_team",
                "best_policy_value_score",
                "best_policy_roles",
                "best_policy_minus_current_value_score",
            ]
        ]
        .apply(
            lambda group: json.dumps(
                [
                    {
                        "candidate_team": clean_text(
                            row.candidate_team
                        ).upper(),
                        "best_policy_value_score": (
                            finite_or_nan(
                                row.best_policy_value_score
                            )
                        ),
                        "best_policy_roles": clean_text(
                            row.best_policy_roles
                        ),
                        "best_policy_minus_current_value_score": (
                            finite_or_nan(
                                row.best_policy_minus_current_value_score
                            )
                        ),
                    }
                    for row in group.itertuples(
                        index=False
                    )
                ],
                sort_keys=True,
            )
        )
        .to_dict()
    )

    for _, row in valuations.iterrows():
        beneficiary = clean_text(
            row.get(
                "candidate_beneficiary_team",
                "",
            )
        ).upper()

        retaining = clean_text(
            row.get(
                "candidate_retaining_team",
                "",
            )
        ).upper()

        counterparty = clean_text(
            row.get(
                "candidate_counterparty_team",
                "",
            )
        ).upper()

        involved = (
            {
                beneficiary,
                retaining,
                counterparty,
            }
            & remaining_teams
        )

        if not involved:
            continue

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
                "remaining_teams_involved": "|".join(
                    sorted(
                        involved
                    )
                ),
                "candidate_beneficiary_team": beneficiary,
                "candidate_retaining_team": retaining,
                "candidate_counterparty_team": counterparty,
                "expected_transferred_value_score": (
                    finite_or_nan(
                        row.get(
                            "expected_transferred_value_score",
                            np.nan,
                        )
                    )
                ),
                "expected_retained_value_score": (
                    finite_or_nan(
                        row.get(
                            "expected_retained_value_score",
                            np.nan,
                        )
                    )
                ),
                "expected_swap_option_value_score": (
                    finite_or_nan(
                        row.get(
                            "expected_swap_option_value_score",
                            np.nan,
                        )
                    )
                ),
                "expected_total_candidate_asset_value_score": (
                    finite_or_nan(
                        row.get(
                            "expected_total_candidate_asset_value_score",
                            np.nan,
                        )
                    )
                ),
                "current_direct_assignments_json": (
                    current_lookup.get(
                        clean_text(
                            row.get(
                                "claim_id",
                                "",
                            )
                        ),
                        "[]",
                    )
                ),
                "best_policy_assignments_json": (
                    effect_lookup.get(
                        clean_text(
                            row.get(
                                "claim_id",
                                "",
                            )
                        ),
                        "[]",
                    )
                ),
                "valuation_scope_note": clean_text(
                    row.get(
                        "valuation_scope_note",
                        "",
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "remaining_teams_involved",
            "valuation_method",
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def source_value_columns(
    valuations: pd.DataFrame,
) -> list[str]:
    columns = []

    for column in valuations.columns:
        lowered = column.lower()

        if (
            lowered.endswith(
                "_source_asset_value_score"
            )
            or lowered
            in {
                "source_asset_value_score",
                "unconditional_asset_value_score",
                "unconditional_asset_exposure_score",
                "physical_source_asset_value_score",
                "component_source_asset_value_score",
            }
        ):
            columns.append(
                column
            )

    return sorted(
        set(
            columns
        )
    )


def build_source_value_candidates(
    valuations: pd.DataFrame,
    rejected_inventory: pd.DataFrame,
) -> pd.DataFrame:
    component_rows = rejected_inventory.loc[
        rejected_inventory[
            "right_origin"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "component_candidate_right_file"
        )
        & rejected_inventory[
            "component_right_file"
        ]
        .fillna("")
        .astype(str)
        .isin(
            LEGACY_COMPONENT_FILES
        )
    ].copy()

    source_assets = sorted(
        {
            asset
            for value in component_rows[
                "source_assets"
            ]
            for asset in parse_source_assets(
                value
            )
        }
    )

    value_columns = source_value_columns(
        valuations
    )

    rows = []

    for asset_key in source_assets:
        matches = valuations.loc[
            valuations[
                "asset_key"
            ]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq(
                asset_key
            )
        ]

        if matches.empty:
            rows.append(
                {
                    "asset_key": asset_key,
                    "claim_id": "",
                    "valuation_method": "",
                    "valuation_status": "",
                    "value_column": "",
                    "candidate_value_score": np.nan,
                    "candidate_value_rounded": np.nan,
                    "value_candidate_found": False,
                }
            )
            continue

        found = False

        for _, row in matches.iterrows():
            for column in value_columns:
                value = finite_or_nan(
                    row.get(
                        column,
                        np.nan,
                    )
                )

                if not np.isfinite(
                    value
                ):
                    continue

                found = True

                rows.append(
                    {
                        "asset_key": asset_key,
                        "claim_id": clean_text(
                            row.get(
                                "claim_id",
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
                        "value_column": column,
                        "candidate_value_score": float(
                            value
                        ),
                        "candidate_value_rounded": round(
                            float(
                                value
                            ),
                            10,
                        ),
                        "value_candidate_found": True,
                    }
                )

        if not found:
            rows.append(
                {
                    "asset_key": asset_key,
                    "claim_id": "|".join(
                        sorted(
                            set(
                                matches[
                                    "claim_id"
                                ]
                                .fillna("")
                                .astype(str)
                            )
                        )
                    ),
                    "valuation_method": "|".join(
                        sorted(
                            set(
                                matches[
                                    "valuation_method"
                                ]
                                .fillna("")
                                .astype(str)
                            )
                        )
                    ),
                    "valuation_status": "|".join(
                        sorted(
                            set(
                                matches[
                                    "valuation_status"
                                ]
                                .fillna("")
                                .astype(str)
                            )
                        )
                    ),
                    "value_column": "",
                    "candidate_value_score": np.nan,
                    "candidate_value_rounded": np.nan,
                    "value_candidate_found": False,
                }
            )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "asset_key",
            "candidate_value_rounded",
            "value_column",
            "claim_id",
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )


def build_legacy_component_reconciliation(
    rejected_inventory: pd.DataFrame,
    source_candidates: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    component_rows = rejected_inventory.loc[
        rejected_inventory[
            "right_origin"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "component_candidate_right_file"
        )
        & rejected_inventory[
            "component_right_file"
        ]
        .fillna("")
        .astype(str)
        .isin(
            LEGACY_COMPONENT_FILES
        )
    ].copy()

    team_rows = component_rows[
        [
            column
            for column in [
                "component_right_file",
                "candidate_team",
                "candidate_right_value_score",
                "expected_pick_count",
                "source_assets",
                "source_assets_inference_method",
                "expected_pick_count_inference_method",
            ]
            if column in component_rows.columns
        ]
    ].copy()

    rows = []

    for component_file, group in component_rows.groupby(
        "component_right_file",
        sort=True,
    ):
        assets = sorted(
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

        asset_values = []
        unresolved_assets = []
        ambiguous_assets = []

        for asset in assets:
            matches = source_candidates.loc[
                source_candidates[
                    "asset_key"
                ].eq(
                    asset
                )
                & source_candidates[
                    "value_candidate_found"
                ].fillna(
                    False
                ).astype(
                    bool
                )
            ]

            unique_values = sorted(
                {
                    round(
                        float(
                            value
                        ),
                        10,
                    )
                    for value in pd.to_numeric(
                        matches[
                            "candidate_value_score"
                        ],
                        errors="coerce",
                    ).dropna()
                }
            )

            if len(
                unique_values
            ) == 1:
                asset_values.append(
                    unique_values[
                        0
                    ]
                )
            elif len(
                unique_values
            ) == 0:
                unresolved_assets.append(
                    asset
                )
            else:
                ambiguous_assets.append(
                    (
                        asset
                        + ":"
                        + "|".join(
                            str(
                                value
                            )
                            for value in unique_values
                        )
                    )
                )

        candidate_value = float(
            pd.to_numeric(
                group[
                    "candidate_right_value_score"
                ],
                errors="coerce",
            ).sum()
        )

        source_value = (
            float(
                sum(
                    asset_values
                )
            )
            if (
                not unresolved_assets
                and not ambiguous_assets
                and len(
                    asset_values
                )
                == len(
                    assets
                )
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
                "component_right_file": component_file,
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
                    assets
                ),
                "source_asset_count": len(
                    assets
                ),
                "resolved_source_asset_count": len(
                    asset_values
                ),
                "unresolved_source_assets": "|".join(
                    unresolved_assets
                ),
                "ambiguous_source_assets": "|".join(
                    ambiguous_assets
                ),
                "candidate_right_value_score": candidate_value,
                "canonical_source_value_score": source_value,
                "candidate_minus_source_value": difference,
                "reconciliation_available": bool(
                    np.isfinite(
                        source_value
                    )
                ),
                "component_value_reconciliation_passed": bool(
                    np.isfinite(
                        difference
                    )
                    and abs(
                        difference
                    )
                    <= VALUE_TOLERANCE
                ),
            }
        )

    return (
        pd.DataFrame(
            rows
        ),
        team_rows.sort_values(
            [
                "component_right_file",
                "candidate_team",
            ]
        ).reset_index(
            drop=True
        ),
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER REMAINING-GAP DIAGNOSTIC")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        policy_summary,
        policy_teams,
        role_contributions,
        row_accounting,
        current_teams,
        valuations,
        direct_rights,
        component_rights,
        rejected_inventory,
    ) = load_inputs()

    best_policy = select_best_policy(
        policy_summary
    )

    remaining_teams = build_remaining_teams(
        best_policy=best_policy,
        policy_teams=policy_teams,
        current_teams=current_teams,
    )

    remaining_team_codes = set(
        remaining_teams[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    claim_effects = build_claim_effects(
        best_policy=best_policy,
        role_contributions=role_contributions,
        direct_rights=direct_rights,
    )

    remaining_team_mask = (
        claim_effects[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .isin(
            remaining_team_codes
        )
    )

    current_value_effect_mask = (
        pd.to_numeric(
            claim_effects[
                "current_direct_value_score"
            ],
            errors="coerce",
        )
        .fillna(
            0.0
        )
        .abs()
        .gt(
            VALUE_TOLERANCE
        )
    )

    best_policy_value_effect_mask = (
        pd.to_numeric(
            claim_effects[
                "best_policy_value_score"
            ],
            errors="coerce",
        )
        .fillna(
            0.0
        )
        .abs()
        .gt(
            VALUE_TOLERANCE
        )
    )

    policy_change_effect_mask = (
        pd.to_numeric(
            claim_effects[
                "best_policy_minus_current_value_score"
            ],
            errors="coerce",
        )
        .fillna(
            0.0
        )
        .abs()
        .gt(
            VALUE_TOLERANCE
        )
    )

    nonzero_claim_effect_mask = (
        current_value_effect_mask
        | best_policy_value_effect_mask
        | policy_change_effect_mask
    )

    relevant_claim_effects = claim_effects.loc[
        remaining_team_mask
        & nonzero_claim_effect_mask
    ].copy()

    involvement = build_remaining_team_involvement(
        remaining_teams=remaining_team_codes,
        valuations=valuations,
        direct_rights=direct_rights,
        claim_effects=claim_effects,
    )

    source_candidates = build_source_value_candidates(
        valuations=valuations,
        rejected_inventory=rejected_inventory,
    )

    (
        legacy_reconciliation,
        legacy_team_rows,
    ) = build_legacy_component_reconciliation(
        rejected_inventory=rejected_inventory,
        source_candidates=source_candidates,
    )

    remaining_teams.to_csv(
        BEST_POLICY_REMAINING_TEAMS_PATH,
        index=False,
    )

    relevant_claim_effects.to_csv(
        BEST_POLICY_CLAIM_EFFECTS_PATH,
        index=False,
    )

    involvement.to_csv(
        REMAINING_TEAM_CLAIM_INVOLVEMENT_PATH,
        index=False,
    )

    source_candidates.to_csv(
        SOURCE_VALUE_CANDIDATES_PATH,
        index=False,
    )

    legacy_reconciliation.to_csv(
        LEGACY_COMPONENT_RECONCILIATION_PATH,
        index=False,
    )

    legacy_team_rows.to_csv(
        LEGACY_COMPONENT_TEAM_ROWS_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "best_policy": best_policy,
        "remaining_mismatched_teams": int(
            len(
                remaining_teams
            )
        ),
        "remaining_team_codes": sorted(
            remaining_team_codes
        ),
        "remaining_policy_system_difference": float(
            pd.to_numeric(
                remaining_teams[
                    "policy_value_difference"
                ],
                errors="coerce",
            ).sum()
        ),
        "relevant_claim_effect_rows": int(
            len(
                relevant_claim_effects
            )
        ),
        "remaining_team_claim_involvement_rows": int(
            len(
                involvement
            )
        ),
        "legacy_component_files_checked": int(
            len(
                legacy_reconciliation
            )
        ),
        "legacy_components_with_available_reconciliation": int(
            legacy_reconciliation[
                "reconciliation_available"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        ),
        "outputs": {
            "remaining_teams": str(
                BEST_POLICY_REMAINING_TEAMS_PATH
            ),
            "claim_effects": str(
                BEST_POLICY_CLAIM_EFFECTS_PATH
            ),
            "claim_involvement": str(
                REMAINING_TEAM_CLAIM_INVOLVEMENT_PATH
            ),
            "source_value_candidates": str(
                SOURCE_VALUE_CANDIDATES_PATH
            ),
            "legacy_component_reconciliation": str(
                LEGACY_COMPONENT_RECONCILIATION_PATH
            ),
            "legacy_component_team_rows": str(
                LEGACY_COMPONENT_TEAM_ROWS_PATH
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
    print("FOCUSED REMAINING-GAP DIAGNOSTIC CREATED")
    print("=" * 80)
    print(f"Best accounting policy: {best_policy}")
    print(
        "Remaining mismatched teams: "
        f"{len(remaining_teams):,}"
    )
    print(
        "Remaining system difference: "
        f"{pd.to_numeric(remaining_teams['policy_value_difference'], errors='coerce').sum():.6f}"
    )
    print(
        "Relevant claim-effect rows: "
        f"{len(relevant_claim_effects):,}"
    )
    print(
        "Legacy component files checked: "
        f"{len(legacy_reconciliation):,}"
    )
    print()

    print("REMAINING TEAMS UNDER BEST POLICY")
    display_teams = remaining_teams.copy()

    numeric_columns = [
        column
        for column in [
            "canonical_final_team_value_score",
            "component_right_value_score",
            "policy_direct_value_score",
            "policy_inventory_value_score",
            "policy_value_difference",
            "absolute_policy_value_difference",
            "current_direct_value_score",
            "canonical_direct_residual_value_score",
            "current_direct_minus_required",
            "v3_value_difference",
        ]
        if column in display_teams.columns
    ]

    for column in numeric_columns:
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

    print(
        display_teams.to_string(
            index=False
        )
    )
    print()

    print("BEST-POLICY CLAIM EFFECTS FOR REMAINING TEAMS")

    display_effects = relevant_claim_effects.copy()

    for column in [
        "current_direct_value_score",
        "best_policy_value_score",
        "best_policy_minus_current_value_score",
    ]:
        display_effects[
            column
        ] = pd.to_numeric(
            display_effects[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    if display_effects.empty:
        print(
            "No direct-claim policy effects were found for the "
            "remaining teams."
        )
    else:
        print(
            display_effects[
                [
                    "candidate_team",
                    "claim_id",
                    "asset_key",
                    "valuation_method",
                    "current_direct_value_score",
                    "best_policy_value_score",
                    "best_policy_minus_current_value_score",
                    "best_policy_roles",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("LEGACY COMPONENT VALUE RECONCILIATION")

    display_legacy = legacy_reconciliation.copy()

    for column in [
        "candidate_right_value_score",
        "canonical_source_value_score",
        "candidate_minus_source_value",
    ]:
        display_legacy[
            column
        ] = pd.to_numeric(
            display_legacy[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_legacy.to_string(
            index=False
        )
    )
    print()

    print("UNRESOLVED OR AMBIGUOUS CANONICAL SOURCE VALUES")

    unresolved_assets = source_candidates.loc[
        ~source_candidates[
            "value_candidate_found"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        )
    ]

    ambiguous_assets = (
        source_candidates.loc[
            source_candidates[
                "value_candidate_found"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
        ]
        .groupby(
            "asset_key"
        )[
            "candidate_value_rounded"
        ]
        .nunique(
            dropna=True
        )
    )

    ambiguous_asset_keys = set(
        ambiguous_assets.loc[
            ambiguous_assets
            > 1
        ].index
    )

    ambiguous_rows = source_candidates.loc[
        source_candidates[
            "asset_key"
        ].isin(
            ambiguous_asset_keys
        )
    ]

    if (
        unresolved_assets.empty
        and ambiguous_rows.empty
    ):
        print(
            "Every legacy component source has one canonical value."
        )
    else:
        combined = pd.concat(
            [
                unresolved_assets,
                ambiguous_rows,
            ],
            ignore_index=True,
            sort=False,
        ).drop_duplicates()

        print(
            combined.to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")

    for path in [
        BEST_POLICY_REMAINING_TEAMS_PATH,
        BEST_POLICY_CLAIM_EFFECTS_PATH,
        REMAINING_TEAM_CLAIM_INVOLVEMENT_PATH,
        SOURCE_VALUE_CANDIDATES_PATH,
        LEGACY_COMPONENT_RECONCILIATION_PATH,
        LEGACY_COMPONENT_TEAM_ROWS_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()