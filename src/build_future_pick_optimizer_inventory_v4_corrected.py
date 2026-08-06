from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-optimizer-inventory-build-v4-corrected-2026-08-04"
)

RELEASE_NAME = (
    "future_pick_optimizer_inventory_2027_2029_final_v2"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

V3_BUILDER_PATH = (
    Path(__file__).resolve().with_name(
        "build_future_pick_optimizer_inventory_v3.py"
    )
)

ROLE_CONTRIBUTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_claim_role_contributions_v1.csv"
)

POLICY_TEAM_COMPARISON_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_policy_team_comparison_v1.csv"
)

CORRECTION_LEDGER_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_final_correction_ledger_v2.csv"
)

CORRECTION_VALIDATION_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_final_correction_validation_v2.csv"
)

CORRECTED_TEAM_PROOF_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_corrected_team_reconciliation_proof_v2.csv"
)

UTAH_SELECTED_CORRECTIONS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_utah_pool_selected_corrections_v2.csv"
)

CLE_MIN_UTA_RECOVERY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_cle_min_uta_2027_first_round_recovery_v2.csv"
)

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

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FINAL_INVENTORY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

FINAL_INVENTORY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.csv"
)

TEAM_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_team_reconciliation_final.csv"
)

SOURCE_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_source_coverage_final.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_validation_final.csv"
)

INVENTORY_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_summary_final.csv"
)

MANIFEST_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_manifest_final.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_metadata_final.json"
)

ROLE_INVENTORY_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_role_inventory_audit_final.csv"
)

CORRECTION_APPLICATION_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_correction_application_audit_final.csv"
)

SOURCE_OVERLAP_AUDIT_PATH_V4 = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_source_overlap_audit_final.csv"
)

STAGING_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "_future_pick_inventory_v4_staging"
)


BEST_POLICY = "role_split_swap_to_beneficiary"

FINAL_TEAM_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_final"
)

CLE_MIN_UTA_COMPONENT_FILE = (
    "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet"
)

MIA_CLAIM_ID = "2027_R1_MIA_C1"

EXPECTED_COMPONENT_RIGHT_ROWS = 66
EXPECTED_CORRECTION_ROWS = 5
EXPECTED_UTAH_CORRECTION_ROWS = 4
EXPECTED_TEAM_ROWS = 30
EXPECTED_COMPONENT_PRIMARY_SOURCES = 59

VALUE_TOLERANCE = 1e-6
PICK_COUNT_TOLERANCE = 1e-10


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


def finite_or_nan(
    value: Any,
) -> float:
    number = pd.to_numeric(
        pd.Series(
            [
                value
            ]
        ),
        errors="coerce",
    ).iloc[
        0
    ]

    return (
        float(
            number
        )
        if pd.notna(
            number
        )
        and np.isfinite(
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


def parse_bool_series(
    series: pd.Series,
) -> pd.Series:
    if pd.api.types.is_bool_dtype(
        series
    ):
        return series.fillna(
            False
        ).astype(
            bool
        )

    return (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "passed",
            }
        )
    )


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


def parse_json_dict(
    value: Any,
) -> dict[str, Any]:
    text = clean_text(
        value
    )

    if not text:
        return {}

    try:
        parsed = json.loads(
            text
        )
    except json.JSONDecodeError:
        return {}

    return (
        parsed
        if isinstance(
            parsed,
            dict,
        )
        else {}
    )


def load_v3_module() -> Any:
    if not V3_BUILDER_PATH.exists():
        raise FileNotFoundError(
            "The V4 builder requires the V3 builder beside it:\n"
            f"{V3_BUILDER_PATH}"
        )

    spec = importlib.util.spec_from_file_location(
        "future_pick_inventory_v3_dependency",
        V3_BUILDER_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Could not create the V3 builder import specification."
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


def file_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:
        for chunk in iter(
            lambda: file.read(
                1024
                * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


def manifest_row(
    path: Path,
    role: str,
) -> dict[str, Any]:
    return {
        "file_role": role,
        "file_name": path.name,
        "file_path": str(
            path
        ),
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "sha256": file_sha256(
            path
        ),
        "release_name": RELEASE_NAME,
        "release_version": SCRIPT_VERSION,
    }


def load_required_csv(
    path: Path,
    label: str,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Required {label} was not found:\n{path}"
        )

    return normalize_columns(
        pd.read_csv(
            path
        )
    )


def load_inputs(
    v3: Any,
) -> dict[str, Any]:
    (
        direct_rights,
        component_rights,
        component_primary_rows,
        file_catalog,
        source_overlap,
        readiness_audit,
        valuations,
        team_summary,
    ) = v3.load_inputs()

    v3.validate_inputs(
        direct_rights=direct_rights,
        component_rights=component_rights,
        component_primary_rows=component_primary_rows,
        file_catalog=file_catalog,
        source_overlap=source_overlap,
        readiness_audit=readiness_audit,
        valuations=valuations,
        team_summary=team_summary,
    )

    role_contributions = load_required_csv(
        ROLE_CONTRIBUTIONS_PATH,
        "role-contribution audit",
    )

    policy_team_comparison = load_required_csv(
        POLICY_TEAM_COMPARISON_PATH,
        "policy team comparison",
    )

    correction_ledger = load_required_csv(
        CORRECTION_LEDGER_PATH,
        "validated correction ledger",
    )

    correction_validation = load_required_csv(
        CORRECTION_VALIDATION_PATH,
        "correction validation",
    )

    corrected_team_proof = load_required_csv(
        CORRECTED_TEAM_PROOF_PATH,
        "corrected team-reconciliation proof",
    )

    utah_selected = load_required_csv(
        UTAH_SELECTED_CORRECTIONS_PATH,
        "selected Utah-pool corrections",
    )

    cle_recovery = load_required_csv(
        CLE_MIN_UTA_RECOVERY_PATH,
        "CLE-MIN-UTA source recovery",
    )

    require_columns(
        role_contributions,
        [
            "policy",
            "claim_id",
            "asset_key",
            "valuation_method",
            "valuation_status",
            "candidate_team",
            "assigned_role",
            "assigned_value_score",
            "source_value_column",
        ],
        "Role contributions",
    )

    require_columns(
        policy_team_comparison,
        [
            "policy",
            "candidate_team",
            "policy_inventory_value_score",
            "canonical_final_team_value_score",
            "policy_value_difference",
        ],
        "Policy team comparison",
    )

    require_columns(
        correction_ledger,
        [
            "candidate_team",
            "correction_value_score",
            "correction_type",
            "source_reference",
            "value_column",
        ],
        "Correction ledger",
    )

    require_columns(
        correction_validation,
        [
            "check_name",
            "passed",
        ],
        "Correction validation",
    )

    require_columns(
        corrected_team_proof,
        [
            "candidate_team",
            "canonical_final_team_value_score",
            "corrected_inventory_value_score",
            "corrected_value_difference",
            "corrected_team_reconciliation_passed",
        ],
        "Corrected team proof",
    )

    require_columns(
        utah_selected,
        [
            "candidate_team",
            "required_correction",
            "source_kind",
            "source_file",
            "source_path",
            "source_row_number",
            "value_column",
            "candidate_correction_value_score",
            "exact_required_correction_match",
            "source_row_json",
        ],
        "Selected Utah corrections",
    )

    require_columns(
        cle_recovery,
        [
            "candidate_team",
            "recovered_source_assets",
            "recovered_source_asset_count",
            "source_count_reconciliation_passed",
            "recovered_round_number",
        ],
        "CLE-MIN-UTA source recovery",
    )

    if not parse_bool_series(
        correction_validation[
            "passed"
        ]
    ).all():
        raise RuntimeError(
            "The final correction validation does not pass every check."
        )

    proof_passed = parse_bool_series(
        corrected_team_proof[
            "corrected_team_reconciliation_passed"
        ]
    )

    if (
        len(
            corrected_team_proof
        )
        != EXPECTED_TEAM_ROWS
        or not proof_passed.all()
    ):
        raise RuntimeError(
            "The corrected team proof is not a 30-team exact "
            "reconciliation."
        )

    proof_differences = pd.to_numeric(
        corrected_team_proof[
            "corrected_value_difference"
        ],
        errors="coerce",
    )

    if (
        proof_differences.isna().any()
        or proof_differences.abs().max()
        > VALUE_TOLERANCE
    ):
        raise RuntimeError(
            "The corrected team proof contains a nonzero team gap."
        )

    if len(
        correction_ledger
    ) != EXPECTED_CORRECTION_ROWS:
        raise RuntimeError(
            "The validated correction ledger no longer contains five "
            "rows."
        )

    if len(
        utah_selected
    ) != EXPECTED_UTAH_CORRECTION_ROWS:
        raise RuntimeError(
            "The selected Utah-pool correction table no longer "
            "contains four rows."
        )

    if not parse_bool_series(
        utah_selected[
            "exact_required_correction_match"
        ]
    ).all():
        raise RuntimeError(
            "At least one selected Utah correction no longer exactly "
            "matches its required gap."
        )

    cle_passed = parse_bool_series(
        cle_recovery[
            "source_count_reconciliation_passed"
        ]
    )

    cle_rounds = pd.to_numeric(
        cle_recovery[
            "recovered_round_number"
        ],
        errors="coerce",
    )

    if (
        len(
            cle_recovery
        )
        != 3
        or not cle_passed.all()
        or not cle_rounds.eq(
            1
        ).all()
    ):
        raise RuntimeError(
            "The CLE-MIN-UTA recovery is not a complete three-row "
            "2027 first-round recovery."
        )

    return {
        "direct_rights": direct_rights,
        "component_rights": component_rights,
        "component_primary_rows": component_primary_rows,
        "file_catalog": file_catalog,
        "source_overlap": source_overlap,
        "readiness_audit": readiness_audit,
        "valuations": valuations,
        "team_summary": team_summary,
        "role_contributions": role_contributions,
        "policy_team_comparison": policy_team_comparison,
        "correction_ledger": correction_ledger,
        "correction_validation": correction_validation,
        "corrected_team_proof": corrected_team_proof,
        "utah_selected": utah_selected,
        "cle_recovery": cle_recovery,
    }


def prepare_component_rights(
    component_rights: pd.DataFrame,
    cle_recovery: pd.DataFrame,
) -> pd.DataFrame:
    output = component_rights.copy()

    recovery_lookup = (
        cle_recovery.assign(
            candidate_team=(
                cle_recovery[
                    "candidate_team"
                ]
                .fillna("")
                .astype(str)
                .str.upper()
                .str.strip()
            )
        )
        .set_index(
            "candidate_team"
        )
    )

    component_file_mask = (
        output[
            "candidate_right_file"
        ]
        .fillna("")
        .astype(str)
        .eq(
            CLE_MIN_UTA_COMPONENT_FILE
        )
    )

    found_teams = set()

    for index, row in output.loc[
        component_file_mask
    ].iterrows():
        team = clean_text(
            row.get(
                "candidate_team",
                "",
            )
        ).upper()

        if team not in recovery_lookup.index:
            raise RuntimeError(
                "A CLE-MIN-UTA candidate team has no validated source "
                f"recovery: {team}"
            )

        recovery_row = recovery_lookup.loc[
            team
        ]

        source_assets = clean_text(
            recovery_row[
                "recovered_source_assets"
            ]
        )

        output.at[
            index,
            "source_assets",
        ] = source_assets

        output.at[
            index,
            "source_asset_count",
        ] = int(
            finite_or_zero(
                recovery_row[
                    "recovered_source_asset_count"
                ]
            )
        )

        output.at[
            index,
            "expected_pick_count",
        ] = finite_or_zero(
            recovery_row.get(
                "expected_pick_count",
                1.0,
            )
        )

        found_teams.add(
            team
        )

    expected_teams = set(
        recovery_lookup.index
    )

    if found_teams != expected_teams:
        raise RuntimeError(
            "The component-right table did not receive every validated "
            "CLE-MIN-UTA recovery."
        )

    return output


def valuation_lookup(
    valuations: pd.DataFrame,
) -> dict[str, pd.Series]:
    lookup = {}

    for claim_id, group in valuations.groupby(
        "claim_id",
        sort=False,
    ):
        lookup[
            clean_text(
                claim_id
            )
        ] = group.iloc[
            0
        ]

    return lookup


def role_expected_pick_count(
    *,
    v3: Any,
    valuation_row: pd.Series,
    assigned_role: str,
) -> float:
    role = clean_text(
        assigned_role
    ).lower()

    base_count = float(
        v3.direct_expected_pick_count(
            valuation_row
        )
    )

    if "swap_option" in role:
        return 0.0

    if "retaining" in role or "retained" in role:
        method = clean_text(
            valuation_row.get(
                "valuation_method",
                "",
            )
        ).lower()

        conveyance_probability = finite_or_nan(
            valuation_row.get(
                "conveyance_probability",
                np.nan,
            )
        )

        if (
            np.isfinite(
                conveyance_probability
            )
            and 0.0
            <= conveyance_probability
            <= 1.0
            and (
                "rollover"
                in method
                or "protection"
                in method
                or "conditional"
                in method
            )
        ):
            return float(
                max(
                    0.0,
                    1.0
                    - conveyance_probability,
                )
            )

        return 1.0

    return base_count


def role_structure(
    *,
    v3: Any,
    valuation_method: str,
    assigned_role: str,
) -> str:
    role = clean_text(
        assigned_role
    ).lower()

    if "retaining" in role or "retained" in role:
        return "retained_or_fallback_right"

    if "swap_option" in role:
        return "swap_option_value_right"

    if "remainder" in role:
        return "candidate_right_value_remainder"

    return v3.classify_direct_structure(
        valuation_method
    )


def build_role_inventory(
    *,
    v3: Any,
    role_contributions: pd.DataFrame,
    valuations: pd.DataFrame,
    correction_ledger: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    policy_rows = role_contributions.loc[
        role_contributions[
            "policy"
        ]
        .fillna("")
        .astype(str)
        .eq(
            BEST_POLICY
        )
    ].copy()

    if policy_rows.empty:
        raise RuntimeError(
            "No role contributions were found for the validated policy."
        )

    policy_rows[
        "candidate_team"
    ] = (
        policy_rows[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    policy_rows[
        "assigned_value_score"
    ] = pd.to_numeric(
        policy_rows[
            "assigned_value_score"
        ],
        errors="raise",
    )

    group_columns = [
        "claim_id",
        "asset_key",
        "valuation_method",
        "valuation_status",
        "candidate_team",
        "assigned_role",
        "source_value_column",
    ]

    grouped = (
        policy_rows.groupby(
            group_columns,
            dropna=False,
            as_index=False,
        )
        .agg(
            base_assigned_value_score=(
                "assigned_value_score",
                "sum",
            ),
            contribution_rows=(
                "assigned_value_score",
                "size",
            ),
        )
    )

    mia_correction_rows = correction_ledger.loc[
        correction_ledger[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .eq(
            "MIA"
        )
        & correction_ledger[
            "correction_type"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "subtract_rollover_fallback_from_retaining_team"
        )
    ].copy()

    if len(
        mia_correction_rows
    ) != 1:
        raise RuntimeError(
            "Expected exactly one validated Miami fallback correction."
        )

    mia_correction_value = float(
        pd.to_numeric(
            mia_correction_rows[
                "correction_value_score"
            ],
            errors="raise",
        ).iloc[
            0
        ]
    )

    mia_mask = (
        grouped[
            "claim_id"
        ]
        .fillna("")
        .astype(str)
        .eq(
            MIA_CLAIM_ID
        )
        & grouped[
            "candidate_team"
        ]
        .eq(
            "MIA"
        )
        & grouped[
            "assigned_role"
        ]
        .fillna("")
        .astype(str)
        .str.lower()
        .str.contains(
            "retaining|retained",
            regex=True,
        )
    )

    if int(
        mia_mask.sum()
    ) != 1:
        raise RuntimeError(
            "Could not identify exactly one Miami retaining-right role "
            "row for the validated fallback correction."
        )

    grouped[
        "inventory_value_adjustment_score"
    ] = 0.0

    grouped[
        "value_adjustment_type"
    ] = ""

    grouped[
        "value_adjustment_source"
    ] = ""

    grouped.loc[
        mia_mask,
        "inventory_value_adjustment_score",
    ] = mia_correction_value

    grouped.loc[
        mia_mask,
        "value_adjustment_type",
    ] = (
        "subtract_rollover_fallback_from_retaining_team"
    )

    grouped.loc[
        mia_mask,
        "value_adjustment_source",
    ] = MIA_CLAIM_ID

    grouped[
        "candidate_right_value_score"
    ] = (
        grouped[
            "base_assigned_value_score"
        ]
        + grouped[
            "inventory_value_adjustment_score"
        ]
    )

    if grouped[
        "candidate_right_value_score"
    ].lt(
        -VALUE_TOLERANCE
    ).any():
        raise RuntimeError(
            "The role-accounting correction created a negative right "
            "value."
        )

    grouped.loc[
        grouped[
            "candidate_right_value_score"
        ].abs()
        <= VALUE_TOLERANCE,
        "candidate_right_value_score",
    ] = 0.0

    lookup = valuation_lookup(
        valuations
    )

    rows = []

    for row in grouped.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        claim_id = clean_text(
            row_dict.get(
                "claim_id",
                "",
            )
        )

        asset_key = clean_text(
            row_dict.get(
                "asset_key",
                "",
            )
        ).upper()

        candidate_team = clean_text(
            row_dict.get(
                "candidate_team",
                "",
            )
        ).upper()

        assigned_role = clean_text(
            row_dict.get(
                "assigned_role",
                "",
            )
        )

        valuation_method = clean_text(
            row_dict.get(
                "valuation_method",
                "",
            )
        )

        if claim_id not in lookup:
            raise RuntimeError(
                "A role contribution could not be joined to the "
                f"canonical valuation row: {claim_id}"
            )

        valuation_row = lookup[
            claim_id
        ]

        year, round_number, source_team = v3.parse_asset_key(
            asset_key
        )

        structure = role_structure(
            v3=v3,
            valuation_method=valuation_method,
            assigned_role=assigned_role,
        )

        source_reference = (
            f"{claim_id}|{assigned_role}|"
            f"{clean_text(row_dict.get('source_value_column', ''))}"
        )

        rows.append(
            {
                "future_pick_right_id": v3.stable_right_id(
                    right_type="role",
                    candidate_team=candidate_team,
                    source_assets=asset_key,
                    source_reference=source_reference,
                ),
                "candidate_team": candidate_team,
                "right_display_name": (
                    f"{candidate_team} {assigned_role.replace('_', ' ')} "
                    f"for {asset_key}"
                ),
                "right_origin": "canonical_claim_role_split",
                "right_structure": structure,
                "source_assets": asset_key,
                "source_asset_count": 1,
                "primary_source_asset": asset_key,
                "draft_year_min": year,
                "draft_year_max": year,
                "round_numbers": (
                    str(
                        round_number
                    )
                    if round_number is not None
                    else ""
                ),
                "originating_teams": source_team,
                "expected_pick_count": role_expected_pick_count(
                    v3=v3,
                    valuation_row=valuation_row,
                    assigned_role=assigned_role,
                ),
                "candidate_right_value_score": float(
                    row_dict[
                        "candidate_right_value_score"
                    ]
                ),
                "base_candidate_right_value_score": float(
                    row_dict[
                        "base_assigned_value_score"
                    ]
                ),
                "inventory_value_adjustment_score": float(
                    row_dict[
                        "inventory_value_adjustment_score"
                    ]
                ),
                "value_adjustment_type": clean_text(
                    row_dict.get(
                        "value_adjustment_type",
                        "",
                    )
                ),
                "value_adjustment_source": clean_text(
                    row_dict.get(
                        "value_adjustment_source",
                        "",
                    )
                ),
                "accounting_role": assigned_role,
                "source_value_column": clean_text(
                    row_dict.get(
                        "source_value_column",
                        "",
                    )
                ),
                "standalone_trade_asset_flag": bool(
                    "remainder"
                    not in assigned_role.lower()
                ),
                "claim_id": claim_id,
                "valuation_method": valuation_method,
                "valuation_status": clean_text(
                    row_dict.get(
                        "valuation_status",
                        "",
                    )
                ),
                "component_right_file": "",
                "component_right_row_number": np.nan,
                "component_method_match_score": np.nan,
                "component_raw_row_json": "",
                "source_assets_recovery_method": (
                    "canonical_claim_asset_key"
                ),
                "expected_pick_count_recovery_method": (
                    "role_aware_canonical_claim_rule"
                ),
                "tradability_status": (
                    "requires_trade_date_cba_and_ownership_validation"
                ),
                "inventory_release": RELEASE_NAME,
                "inventory_release_version": SCRIPT_VERSION,
            }
        )

    inventory = pd.DataFrame(
        rows
    )

    audit = grouped.copy()

    audit[
        "final_inventory_value_score"
    ] = audit[
        "candidate_right_value_score"
    ]

    return (
        inventory,
        audit,
    )


def resolve_utah_rights_table(
    selected: pd.DataFrame,
) -> tuple[
    Path,
    pd.DataFrame,
]:
    rights_rows = selected.loc[
        selected[
            "source_kind"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "rights"
        )
    ]

    candidate_paths = []

    for value in rights_rows[
        "source_path"
    ].fillna(
        ""
    ):
        path = Path(
            clean_text(
                value
            )
        )

        if path.exists():
            candidate_paths.append(
                path
            )

    if not candidate_paths:
        stem = (
            "future_pick_utah_2028_pool_candidate_rights_ledger_v1"
        )

        for directory in [
            OUTPUT_DIRECTORY,
            PROCESSED_DIRECTORY,
        ]:
            for suffix in [
                ".parquet",
                ".csv",
            ]:
                path = directory / f"{stem}{suffix}"

                if path.exists():
                    candidate_paths.append(
                        path
                    )

    if not candidate_paths:
        raise FileNotFoundError(
            "Could not resolve the Utah 2028 pool candidate-right "
            "ledger."
        )

    path = sorted(
        set(
            candidate_paths
        ),
        key=lambda item: (
            0
            if item.suffix.lower()
            == ".parquet"
            else 1,
            str(
                item
            ),
        ),
    )[
        0
    ]

    frame = (
        normalize_columns(
            pd.read_parquet(
                path
            )
        )
        if path.suffix.lower()
        == ".parquet"
        else normalize_columns(
            pd.read_csv(
                path
            )
        )
    )

    return (
        path,
        frame,
    )


def source_assets_from_row_payload(
    row_dict: dict[str, Any],
) -> list[str]:
    direct = parse_source_assets(
        row_dict.get(
            "source_assets",
            "",
        )
    )

    if direct:
        return direct

    payload = parse_json_dict(
        row_dict.get(
            "source_row_json",
            "",
        )
    )

    assets = parse_source_assets(
        json.dumps(
            json_safe(
                payload
            ),
            sort_keys=True,
        )
    )

    return assets


def locate_utah_right_row(
    *,
    team: str,
    rights: pd.DataFrame,
) -> pd.Series:
    team_column = ""

    for column in [
        "candidate_team",
        "candidate_beneficiary_team",
        "team",
    ]:
        if column in rights.columns:
            team_column = column
            break

    if not team_column:
        raise RuntimeError(
            "The Utah pool rights ledger has no candidate-team column."
        )

    matches = rights.loc[
        rights[
            team_column
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
        .eq(
            team
        )
    ]

    if len(
        matches
    ) != 1:
        raise RuntimeError(
            "Expected exactly one Utah pool ledger row for "
            f"{team}, found {len(matches)}."
        )

    return matches.iloc[
        0
    ]


def recover_utah_source_assets(
    *,
    selected_row: dict[str, Any],
    rights_row: pd.Series,
) -> list[str]:
    assets = source_assets_from_row_payload(
        selected_row
    )

    if assets:
        return assets

    assets = parse_source_assets(
        json.dumps(
            json_safe(
                rights_row.to_dict()
            ),
            sort_keys=True,
        )
    )

    if assets:
        return assets

    raise RuntimeError(
        "A validated Utah pool correction has no recoverable source "
        f"assets for {selected_row.get('candidate_team', '')}."
    )


def recover_utah_expected_pick_count(
    *,
    selected_row: dict[str, Any],
    rights_row: pd.Series,
) -> tuple[
    float,
    str,
]:
    source_kind = clean_text(
        selected_row.get(
            "source_kind",
            "",
        )
    ).lower()

    if source_kind == "adjustments":
        return (
            0.0,
            "incremental_value_right_no_additional_physical_pick",
        )

    payload = parse_json_dict(
        selected_row.get(
            "source_row_json",
            "",
        )
    )

    for source_name, source in [
        (
            "selected_row",
            selected_row,
        ),
        (
            "selected_raw_json",
            payload,
        ),
        (
            "utah_rights_ledger",
            rights_row.to_dict(),
        ),
    ]:
        for column in [
            "expected_pick_count",
            "expected_source_pick_count",
            "candidate_expected_pick_count",
            "pick_count",
        ]:
            value = finite_or_nan(
                source.get(
                    column,
                    np.nan,
                )
            )

            if np.isfinite(
                value
            ):
                return (
                    float(
                        value
                    ),
                    f"{source_name}:{column}",
                )

    return (
        1.0,
        "validated_full_candidate_right_default_one",
    )


def build_utah_correction_inventory(
    *,
    v3: Any,
    selected: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    Path,
]:
    rights_path, rights = resolve_utah_rights_table(
        selected
    )

    rows = []
    audit_rows = []

    for row in selected.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        team = clean_text(
            row_dict.get(
                "candidate_team",
                "",
            )
        ).upper()

        source_kind = clean_text(
            row_dict.get(
                "source_kind",
                "",
            )
        ).lower()

        value = finite_or_nan(
            row_dict.get(
                "candidate_correction_value_score",
                np.nan,
            )
        )

        required = finite_or_nan(
            row_dict.get(
                "required_correction",
                np.nan,
            )
        )

        if (
            not np.isfinite(
                value
            )
            or not np.isfinite(
                required
            )
            or abs(
                value
                - required
            )
            > VALUE_TOLERANCE
        ):
            raise RuntimeError(
                "A selected Utah correction no longer matches its "
                f"required value for {team}."
            )

        rights_row = locate_utah_right_row(
            team=team,
            rights=rights,
        )

        source_assets = recover_utah_source_assets(
            selected_row=row_dict,
            rights_row=rights_row,
        )

        (
            expected_pick_count,
            count_method,
        ) = recover_utah_expected_pick_count(
            selected_row=row_dict,
            rights_row=rights_row,
        )

        years = sorted(
            {
                v3.parse_asset_key(
                    asset
                )[
                    0
                ]
                for asset in source_assets
                if v3.parse_asset_key(
                    asset
                )[
                    0
                ]
                is not None
            }
        )

        rounds = sorted(
            {
                v3.parse_asset_key(
                    asset
                )[
                    1
                ]
                for asset in source_assets
                if v3.parse_asset_key(
                    asset
                )[
                    1
                ]
                is not None
            }
        )

        teams = sorted(
            {
                v3.parse_asset_key(
                    asset
                )[
                    2
                ]
                for asset in source_assets
                if v3.parse_asset_key(
                    asset
                )[
                    2
                ]
            }
        )

        source_assets_text = "|".join(
            source_assets
        )

        source_reference = (
            f"{clean_text(row_dict.get('source_file', ''))}"
            f"#{int(finite_or_zero(row_dict.get('source_row_number', 0)))}"
            f"|{clean_text(row_dict.get('value_column', ''))}"
        )

        is_increment = (
            source_kind
            == "adjustments"
        )

        rows.append(
            {
                "future_pick_right_id": v3.stable_right_id(
                    right_type=(
                        "validated_increment"
                        if is_increment
                        else "validated_component"
                    ),
                    candidate_team=team,
                    source_assets=source_assets_text,
                    source_reference=source_reference,
                ),
                "candidate_team": team,
                "right_display_name": (
                    f"{team} validated Utah 2028 pool "
                    + (
                        "value increment"
                        if is_increment
                        else "candidate right"
                    )
                ),
                "right_origin": "validated_canonical_correction",
                "right_structure": (
                    "integrated_pool_value_increment"
                    if is_increment
                    else "integrated_pool_candidate_right"
                ),
                "source_assets": source_assets_text,
                "source_asset_count": len(
                    source_assets
                ),
                "primary_source_asset": (
                    source_assets[
                        0
                    ]
                    if len(
                        source_assets
                    )
                    == 1
                    else ""
                ),
                "draft_year_min": (
                    min(
                        years
                    )
                    if years
                    else np.nan
                ),
                "draft_year_max": (
                    max(
                        years
                    )
                    if years
                    else np.nan
                ),
                "round_numbers": "|".join(
                    str(
                        value
                    )
                    for value in rounds
                ),
                "originating_teams": "|".join(
                    teams
                ),
                "expected_pick_count": expected_pick_count,
                "candidate_right_value_score": float(
                    value
                ),
                "base_candidate_right_value_score": 0.0,
                "inventory_value_adjustment_score": float(
                    value
                ),
                "value_adjustment_type": (
                    "validated_utah_2028_pool_increment"
                    if is_increment
                    else "validated_utah_2028_pool_full_right"
                ),
                "value_adjustment_source": source_reference,
                "accounting_role": (
                    "incremental_option_value"
                    if is_increment
                    else "full_component_candidate_right"
                ),
                "source_value_column": clean_text(
                    row_dict.get(
                        "value_column",
                        "",
                    )
                ),
                "standalone_trade_asset_flag": bool(
                    not is_increment
                ),
                "claim_id": "",
                "valuation_method": (
                    "validated_utah_2028_pool_correction"
                ),
                "valuation_status": (
                    "valued_validated_canonical_correction"
                ),
                "component_right_file": clean_text(
                    row_dict.get(
                        "source_file",
                        "",
                    )
                ),
                "component_right_row_number": int(
                    finite_or_zero(
                        row_dict.get(
                            "source_row_number",
                            0,
                        )
                    )
                ),
                "component_method_match_score": 1.0,
                "component_raw_row_json": clean_text(
                    row_dict.get(
                        "source_row_json",
                        "",
                    )
                ),
                "source_assets_recovery_method": (
                    "validated_utah_rights_ledger"
                ),
                "expected_pick_count_recovery_method": (
                    count_method
                ),
                "tradability_status": (
                    "accounting_increment_not_standalone_trade_asset"
                    if is_increment
                    else (
                        "requires_trade_date_cba_and_ownership_validation"
                    )
                ),
                "inventory_release": RELEASE_NAME,
                "inventory_release_version": SCRIPT_VERSION,
            }
        )

        audit_rows.append(
            {
                "candidate_team": team,
                "source_kind": source_kind,
                "source_file": clean_text(
                    row_dict.get(
                        "source_file",
                        "",
                    )
                ),
                "source_row_number": int(
                    finite_or_zero(
                        row_dict.get(
                            "source_row_number",
                            0,
                        )
                    )
                ),
                "value_column": clean_text(
                    row_dict.get(
                        "value_column",
                        "",
                    )
                ),
                "required_correction": float(
                    required
                ),
                "applied_correction": float(
                    value
                ),
                "source_assets": source_assets_text,
                "expected_pick_count": expected_pick_count,
                "expected_pick_count_method": count_method,
                "standalone_trade_asset_flag": bool(
                    not is_increment
                ),
                "correction_application_passed": bool(
                    abs(
                        value
                        - required
                    )
                    <= VALUE_TOLERANCE
                ),
            }
        )

    return (
        pd.DataFrame(
            rows
        ),
        pd.DataFrame(
            audit_rows
        ),
        rights_path,
    )


def enrich_component_inventory(
    component_inventory: pd.DataFrame,
) -> pd.DataFrame:
    output = component_inventory.copy()

    output[
        "base_candidate_right_value_score"
    ] = pd.to_numeric(
        output[
            "candidate_right_value_score"
        ],
        errors="raise",
    )

    output[
        "inventory_value_adjustment_score"
    ] = 0.0

    output[
        "value_adjustment_type"
    ] = ""

    output[
        "value_adjustment_source"
    ] = ""

    output[
        "accounting_role"
    ] = "component_candidate_right"

    output[
        "source_value_column"
    ] = "expected_candidate_right_value_score"

    output[
        "standalone_trade_asset_flag"
    ] = True

    output[
        "inventory_release"
    ] = RELEASE_NAME

    output[
        "inventory_release_version"
    ] = SCRIPT_VERSION

    return output


def build_source_overlap_audit(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    exploded_rows = []

    for row in inventory.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        for asset in parse_source_assets(
            row_dict.get(
                "source_assets",
                "",
            )
        ):
            exploded_rows.append(
                {
                    "source_asset": asset,
                    "future_pick_right_id": clean_text(
                        row_dict.get(
                            "future_pick_right_id",
                            "",
                        )
                    ),
                    "candidate_team": clean_text(
                        row_dict.get(
                            "candidate_team",
                            "",
                        )
                    ),
                    "right_origin": clean_text(
                        row_dict.get(
                            "right_origin",
                            "",
                        )
                    ),
                    "right_structure": clean_text(
                        row_dict.get(
                            "right_structure",
                            "",
                        )
                    ),
                    "standalone_trade_asset_flag": bool(
                        row_dict.get(
                            "standalone_trade_asset_flag",
                            False,
                        )
                    ),
                }
            )

    exploded = pd.DataFrame(
        exploded_rows
    )

    if exploded.empty:
        return pd.DataFrame(
            columns=[
                "source_asset",
                "right_rows",
                "candidate_teams",
                "right_origins",
                "right_structures",
                "standalone_trade_asset_rows",
                "contains_validated_increment",
            ]
        )

    for source_asset, group in exploded.groupby(
        "source_asset",
        sort=True,
    ):
        rows.append(
            {
                "source_asset": source_asset,
                "right_rows": int(
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
                        )
                    )
                ),
                "right_origins": "|".join(
                    sorted(
                        set(
                            group[
                                "right_origin"
                            ]
                        )
                    )
                ),
                "right_structures": "|".join(
                    sorted(
                        set(
                            group[
                                "right_structure"
                            ]
                        )
                    )
                ),
                "standalone_trade_asset_rows": int(
                    group[
                        "standalone_trade_asset_flag"
                    ].sum()
                ),
                "contains_validated_increment": bool(
                    group[
                        "right_structure"
                    ].eq(
                        "integrated_pool_value_increment"
                    ).any()
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_validation(
    *,
    inventory: pd.DataFrame,
    role_inventory: pd.DataFrame,
    component_inventory: pd.DataFrame,
    correction_inventory: pd.DataFrame,
    role_audit: pd.DataFrame,
    correction_audit: pd.DataFrame,
    team_reconciliation: pd.DataFrame,
    source_coverage: pd.DataFrame,
    corrected_team_proof: pd.DataFrame,
    correction_validation: pd.DataFrame,
    cle_recovery: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    values = pd.to_numeric(
        inventory[
            "candidate_right_value_score"
        ],
        errors="coerce",
    )

    pick_counts = pd.to_numeric(
        inventory[
            "expected_pick_count"
        ],
        errors="coerce",
    )

    duplicate_ids = int(
        inventory[
            "future_pick_right_id"
        ].duplicated().sum()
    )

    invalid_team_rows = int(
        inventory[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.fullmatch(
            r"[A-Z]{3}"
        )
        .eq(
            False
        )
        .sum()
    )

    expected_total_rows = (
        len(
            role_inventory
        )
        + len(
            component_inventory
        )
        + len(
            correction_inventory
        )
    )

    all_claims_valued = bool(
        valuations[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .str.startswith(
            "valued_"
        )
        .all()
    )

    proof = corrected_team_proof[
        [
            "candidate_team",
            "corrected_inventory_value_score",
        ]
    ].copy()

    proof = proof.rename(
        columns={
            "corrected_inventory_value_score": (
                "proof_inventory_value_score"
            ),
        }
    )

    proof_comparison = team_reconciliation.merge(
        proof,
        how="left",
        on="candidate_team",
        validate="one_to_one",
    )

    proof_comparison[
        "inventory_minus_proof_value"
    ] = (
        proof_comparison[
            "optimizer_inventory_value_score"
        ]
        - pd.to_numeric(
            proof_comparison[
                "proof_inventory_value_score"
            ],
            errors="coerce",
        )
    )

    max_proof_difference = float(
        proof_comparison[
            "inventory_minus_proof_value"
        ].abs().max()
    )

    mia_adjustment = float(
        role_audit.loc[
            role_audit[
                "claim_id"
            ]
            .fillna("")
            .astype(str)
            .eq(
                MIA_CLAIM_ID
            )
            & role_audit[
                "candidate_team"
            ]
            .fillna("")
            .astype(str)
            .eq(
                "MIA"
            ),
            "inventory_value_adjustment_score",
        ].sum()
    )

    checks = [
        {
            "check_name": "inventory_row_count_matches_components",
            "observed_value": int(
                len(
                    inventory
                )
            ),
            "expected_value": int(
                expected_total_rows
            ),
            "passed": len(
                inventory
            )
            == expected_total_rows,
        },
        {
            "check_name": "role_inventory_rows_present",
            "observed_value": int(
                len(
                    role_inventory
                )
            ),
            "expected_value": ">0",
            "passed": len(
                role_inventory
            )
            > 0,
        },
        {
            "check_name": "expected_component_right_rows",
            "observed_value": int(
                len(
                    component_inventory
                )
            ),
            "expected_value": EXPECTED_COMPONENT_RIGHT_ROWS,
            "passed": len(
                component_inventory
            )
            == EXPECTED_COMPONENT_RIGHT_ROWS,
        },
        {
            "check_name": "expected_validated_correction_rows",
            "observed_value": int(
                len(
                    correction_inventory
                )
            ),
            "expected_value": EXPECTED_UTAH_CORRECTION_ROWS,
            "passed": len(
                correction_inventory
            )
            == EXPECTED_UTAH_CORRECTION_ROWS,
        },
        {
            "check_name": "unique_future_pick_right_ids",
            "observed_value": duplicate_ids,
            "expected_value": 0,
            "passed": duplicate_ids
            == 0,
        },
        {
            "check_name": "finite_inventory_values",
            "observed_value": int(
                values.notna().sum()
            ),
            "expected_value": int(
                len(
                    inventory
                )
            ),
            "passed": values.notna().all(),
        },
        {
            "check_name": "nonnegative_inventory_values",
            "observed_value": int(
                values.lt(
                    -VALUE_TOLERANCE
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                not values.lt(
                    -VALUE_TOLERANCE
                ).any()
            ),
        },
        {
            "check_name": "finite_expected_pick_counts",
            "observed_value": int(
                pick_counts.notna().sum()
            ),
            "expected_value": int(
                len(
                    inventory
                )
            ),
            "passed": pick_counts.notna().all(),
        },
        {
            "check_name": "nonnegative_expected_pick_counts",
            "observed_value": int(
                pick_counts.lt(
                    -PICK_COUNT_TOLERANCE
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                not pick_counts.lt(
                    -PICK_COUNT_TOLERANCE
                ).any()
            ),
        },
        {
            "check_name": "valid_candidate_team_codes",
            "observed_value": invalid_team_rows,
            "expected_value": 0,
            "passed": invalid_team_rows
            == 0,
        },
        {
            "check_name": "team_reconciliation_rows",
            "observed_value": int(
                len(
                    team_reconciliation
                )
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": len(
                team_reconciliation
            )
            == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "all_team_value_reconciliations",
            "observed_value": int(
                team_reconciliation[
                    "team_reconciliation_passed"
                ].sum()
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": bool(
                team_reconciliation[
                    "team_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "system_value_reconciliation",
            "observed_value": float(
                team_reconciliation[
                    "value_difference"
                ].sum()
            ),
            "expected_value": 0.0,
            "passed": abs(
                float(
                    team_reconciliation[
                        "value_difference"
                    ].sum()
                )
            )
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "matches_validated_corrected_team_proof",
            "observed_value": max_proof_difference,
            "expected_value": 0.0,
            "passed": max_proof_difference
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "all_component_primary_sources_covered",
            "observed_value": int(
                source_coverage[
                    "source_covered_by_inventory"
                ].sum()
            ),
            "expected_value": int(
                len(
                    source_coverage
                )
            ),
            "passed": bool(
                len(
                    source_coverage
                )
                == EXPECTED_COMPONENT_PRIMARY_SOURCES
                and source_coverage[
                    "source_covered_by_inventory"
                ].all()
            ),
        },
        {
            "check_name": "validated_corrections_applied_exactly",
            "observed_value": int(
                correction_audit[
                    "correction_application_passed"
                ].sum()
            ),
            "expected_value": EXPECTED_UTAH_CORRECTION_ROWS,
            "passed": bool(
                len(
                    correction_audit
                )
                == EXPECTED_UTAH_CORRECTION_ROWS
                and correction_audit[
                    "correction_application_passed"
                ].all()
            ),
        },
        {
            "check_name": "miami_fallback_correction_applied",
            "observed_value": mia_adjustment,
            "expected_value": float(
                -41.315077
            ),
            "passed": abs(
                mia_adjustment
                - (
                    -41.315077
                )
            )
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "correction_validation_still_passes",
            "observed_value": int(
                parse_bool_series(
                    correction_validation[
                        "passed"
                    ]
                ).sum()
            ),
            "expected_value": int(
                len(
                    correction_validation
                )
            ),
            "passed": bool(
                parse_bool_series(
                    correction_validation[
                        "passed"
                    ]
                ).all()
            ),
        },
        {
            "check_name": "cle_min_uta_sources_recovered",
            "observed_value": int(
                parse_bool_series(
                    cle_recovery[
                        "source_count_reconciliation_passed"
                    ]
                ).sum()
            ),
            "expected_value": 3,
            "passed": bool(
                len(
                    cle_recovery
                )
                == 3
                and parse_bool_series(
                    cle_recovery[
                        "source_count_reconciliation_passed"
                    ]
                ).all()
            ),
        },
        {
            "check_name": "canonical_claim_layer_fully_valued",
            "observed_value": all_claims_valued,
            "expected_value": True,
            "passed": all_claims_valued,
        },
    ]

    return pd.DataFrame(
        checks
    )


def write_staging_outputs(
    *,
    inventory: pd.DataFrame,
    team_reconciliation: pd.DataFrame,
    source_coverage: pd.DataFrame,
    validation: pd.DataFrame,
    inventory_summary: pd.DataFrame,
    role_audit: pd.DataFrame,
    correction_audit: pd.DataFrame,
    overlap_audit: pd.DataFrame,
) -> dict[str, Path]:
    STAGING_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = {
        "inventory_parquet": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_2027_2029_final.parquet"
        ),
        "inventory_csv": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_2027_2029_final.csv"
        ),
        "team_reconciliation": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_team_reconciliation_final.csv"
        ),
        "source_coverage": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_source_coverage_final.csv"
        ),
        "validation": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_validation_final.csv"
        ),
        "inventory_summary": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_summary_final.csv"
        ),
        "role_audit": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_role_inventory_audit_final.csv"
        ),
        "correction_audit": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_correction_application_audit_final.csv"
        ),
        "overlap_audit": (
            STAGING_DIRECTORY
            / "future_pick_optimizer_inventory_source_overlap_audit_final.csv"
        ),
    }

    inventory.to_parquet(
        paths[
            "inventory_parquet"
        ],
        index=False,
    )

    inventory.to_csv(
        paths[
            "inventory_csv"
        ],
        index=False,
    )

    team_reconciliation.to_csv(
        paths[
            "team_reconciliation"
        ],
        index=False,
    )

    source_coverage.to_csv(
        paths[
            "source_coverage"
        ],
        index=False,
    )

    validation.to_csv(
        paths[
            "validation"
        ],
        index=False,
    )

    inventory_summary.to_csv(
        paths[
            "inventory_summary"
        ],
        index=False,
    )

    role_audit.to_csv(
        paths[
            "role_audit"
        ],
        index=False,
    )

    correction_audit.to_csv(
        paths[
            "correction_audit"
        ],
        index=False,
    )

    overlap_audit.to_csv(
        paths[
            "overlap_audit"
        ],
        index=False,
    )

    return paths


def publish_staging_outputs(
    staging_paths: dict[str, Path],
) -> None:
    destinations = {
        "inventory_parquet": FINAL_INVENTORY_PARQUET_PATH,
        "inventory_csv": FINAL_INVENTORY_CSV_PATH,
        "team_reconciliation": TEAM_RECONCILIATION_PATH,
        "source_coverage": SOURCE_COVERAGE_PATH,
        "validation": VALIDATION_PATH,
        "inventory_summary": INVENTORY_SUMMARY_PATH,
        "role_audit": ROLE_INVENTORY_AUDIT_PATH,
        "correction_audit": CORRECTION_APPLICATION_AUDIT_PATH,
        "overlap_audit": SOURCE_OVERLAP_AUDIT_PATH_V4,
    }

    for key, destination in destinations.items():
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        os.replace(
            staging_paths[
                key
            ],
            destination,
        )


def main() -> None:
    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER INVENTORY BUILD")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    v3 = load_v3_module()

    inputs = load_inputs(
        v3
    )

    prepared_component_rights = prepare_component_rights(
        component_rights=inputs[
            "component_rights"
        ],
        cle_recovery=inputs[
            "cle_recovery"
        ],
    )

    role_inventory, role_audit = build_role_inventory(
        v3=v3,
        role_contributions=inputs[
            "role_contributions"
        ],
        valuations=inputs[
            "valuations"
        ],
        correction_ledger=inputs[
            "correction_ledger"
        ],
    )

    component_inventory = enrich_component_inventory(
        v3.build_component_inventory(
            prepared_component_rights
        )
    )

    (
        correction_inventory,
        correction_audit,
        utah_rights_path,
    ) = build_utah_correction_inventory(
        v3=v3,
        selected=inputs[
            "utah_selected"
        ],
    )

    inventory = pd.concat(
        [
            role_inventory,
            component_inventory,
            correction_inventory,
        ],
        ignore_index=True,
        sort=False,
    )

    inventory[
        "candidate_right_value_score"
    ] = pd.to_numeric(
        inventory[
            "candidate_right_value_score"
        ],
        errors="raise",
    )

    inventory[
        "expected_pick_count"
    ] = pd.to_numeric(
        inventory[
            "expected_pick_count"
        ],
        errors="raise",
    )

    inventory[
        "standalone_trade_asset_flag"
    ] = (
        inventory[
            "standalone_trade_asset_flag"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        )
    )

    inventory[
        "inventory_release"
    ] = RELEASE_NAME

    inventory[
        "inventory_release_version"
    ] = SCRIPT_VERSION

    inventory = inventory.sort_values(
        [
            "candidate_team",
            "draft_year_min",
            "round_numbers",
            "right_origin",
            "right_structure",
            "future_pick_right_id",
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )

    team_reconciliation = v3.build_team_reconciliation(
        inventory=inventory,
        team_summary=inputs[
            "team_summary"
        ],
    )

    source_coverage = v3.build_source_coverage(
        inventory=inventory,
        component_primary_rows=inputs[
            "component_primary_rows"
        ],
    )

    inventory_summary = v3.build_inventory_summary(
        inventory
    )

    overlap_audit = build_source_overlap_audit(
        inventory
    )

    validation = build_validation(
        inventory=inventory,
        role_inventory=role_inventory,
        component_inventory=component_inventory,
        correction_inventory=correction_inventory,
        role_audit=role_audit,
        correction_audit=correction_audit,
        team_reconciliation=team_reconciliation,
        source_coverage=source_coverage,
        corrected_team_proof=inputs[
            "corrected_team_proof"
        ],
        correction_validation=inputs[
            "correction_validation"
        ],
        cle_recovery=inputs[
            "cle_recovery"
        ],
        valuations=inputs[
            "valuations"
        ],
    )

    staging_paths = write_staging_outputs(
        inventory=inventory,
        team_reconciliation=team_reconciliation,
        source_coverage=source_coverage,
        validation=validation,
        inventory_summary=inventory_summary,
        role_audit=role_audit,
        correction_audit=correction_audit,
        overlap_audit=overlap_audit,
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    if not failed.empty:
        print("=" * 80)
        print("INVENTORY RELEASE REJECTED")
        print("=" * 80)
        print(
            "The corrected inventory was written only to the staging "
            "directory and was not published."
        )
        print()
        print(
            failed.to_string(
                index=False
            )
        )

        raise RuntimeError(
            "The V4 corrected inventory failed release validation. "
            "Canonical outputs were not replaced."
        )

    publish_staging_outputs(
        staging_paths
    )

    manifest_inputs = [
        (
            V3_BUILDER_PATH,
            "input_v3_builder_dependency",
        ),
        (
            ROLE_CONTRIBUTIONS_PATH,
            "input_role_contributions",
        ),
        (
            POLICY_TEAM_COMPARISON_PATH,
            "input_policy_team_comparison",
        ),
        (
            CORRECTION_LEDGER_PATH,
            "input_validated_correction_ledger",
        ),
        (
            CORRECTION_VALIDATION_PATH,
            "input_correction_validation",
        ),
        (
            CORRECTED_TEAM_PROOF_PATH,
            "input_corrected_team_proof",
        ),
        (
            UTAH_SELECTED_CORRECTIONS_PATH,
            "input_selected_utah_corrections",
        ),
        (
            CLE_MIN_UTA_RECOVERY_PATH,
            "input_cle_min_uta_recovery",
        ),
        (
            FINAL_VALUATION_PATH,
            "input_canonical_valuation_layer",
        ),
        (
            FINAL_TEAM_SUMMARY_PATH,
            "input_canonical_team_summary",
        ),
        (
            utah_rights_path,
            "input_utah_pool_candidate_rights",
        ),
    ]

    manifest_outputs = [
        (
            FINAL_INVENTORY_PARQUET_PATH,
            "final_optimizer_inventory_parquet",
        ),
        (
            FINAL_INVENTORY_CSV_PATH,
            "final_optimizer_inventory_csv",
        ),
        (
            TEAM_RECONCILIATION_PATH,
            "final_team_reconciliation",
        ),
        (
            SOURCE_COVERAGE_PATH,
            "final_source_coverage",
        ),
        (
            VALIDATION_PATH,
            "final_inventory_validation",
        ),
        (
            INVENTORY_SUMMARY_PATH,
            "final_inventory_summary",
        ),
        (
            ROLE_INVENTORY_AUDIT_PATH,
            "final_role_inventory_audit",
        ),
        (
            CORRECTION_APPLICATION_AUDIT_PATH,
            "final_correction_application_audit",
        ),
        (
            SOURCE_OVERLAP_AUDIT_PATH_V4,
            "final_source_overlap_audit",
        ),
    ]

    manifest = pd.DataFrame(
        [
            manifest_row(
                path,
                role,
            )
            for path, role in (
                manifest_inputs
                + manifest_outputs
            )
        ]
    )

    manifest.to_csv(
        MANIFEST_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "inventory_rows": int(
            len(
                inventory
            )
        ),
        "role_split_right_rows": int(
            len(
                role_inventory
            )
        ),
        "component_right_rows": int(
            len(
                component_inventory
            )
        ),
        "validated_correction_right_rows": int(
            len(
                correction_inventory
            )
        ),
        "candidate_teams": int(
            inventory[
                "candidate_team"
            ].nunique()
        ),
        "total_expected_pick_count": float(
            inventory[
                "expected_pick_count"
            ].sum()
        ),
        "total_inventory_value_score": float(
            inventory[
                "candidate_right_value_score"
            ].sum()
        ),
        "canonical_team_value_score": float(
            team_reconciliation[
                "canonical_final_team_value_score"
            ].sum()
        ),
        "maximum_team_value_difference": float(
            team_reconciliation[
                "absolute_value_difference"
            ].max()
        ),
        "component_primary_sources": int(
            len(
                source_coverage
            )
        ),
        "component_primary_sources_covered": int(
            source_coverage[
                "source_covered_by_inventory"
            ].sum()
        ),
        "standalone_trade_asset_rows": int(
            inventory[
                "standalone_trade_asset_flag"
            ].sum()
        ),
        "accounting_increment_rows": int(
            inventory[
                "right_structure"
            ].eq(
                "integrated_pool_value_increment"
            ).sum()
        ),
        "validation_checks": int(
            len(
                validation
            )
        ),
        "validation_checks_passed": int(
            validation[
                "passed"
            ].sum()
        ),
        "release_valid": True,
        "legal_tradability_note": (
            "Inventory valuation is complete, but each asset still "
            "requires trade-date CBA, ownership, encumbrance, Stepien, "
            "and frozen-pick validation before use in a legal package."
        ),
        "output_files": {
            "inventory_parquet": str(
                FINAL_INVENTORY_PARQUET_PATH
            ),
            "inventory_csv": str(
                FINAL_INVENTORY_CSV_PATH
            ),
            "team_reconciliation": str(
                TEAM_RECONCILIATION_PATH
            ),
            "source_coverage": str(
                SOURCE_COVERAGE_PATH
            ),
            "validation": str(
                VALIDATION_PATH
            ),
            "inventory_summary": str(
                INVENTORY_SUMMARY_PATH
            ),
            "role_inventory_audit": str(
                ROLE_INVENTORY_AUDIT_PATH
            ),
            "correction_application_audit": str(
                CORRECTION_APPLICATION_AUDIT_PATH
            ),
            "source_overlap_audit": str(
                SOURCE_OVERLAP_AUDIT_PATH_V4
            ),
            "manifest": str(
                MANIFEST_PATH
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
    print("CORRECTED OPTIMIZER INVENTORY RELEASE COMPLETE")
    print("=" * 80)
    print(
        "Inventory rows: "
        f"{len(inventory):,}"
    )
    print(
        "Role-split claim rights: "
        f"{len(role_inventory):,}"
    )
    print(
        "Component candidate rights: "
        f"{len(component_inventory):,}"
    )
    print(
        "Validated correction rights or increments: "
        f"{len(correction_inventory):,}"
    )
    print(
        "Candidate teams: "
        f"{inventory['candidate_team'].nunique():,}"
    )
    print(
        "Total expected pick count: "
        f"{inventory['expected_pick_count'].sum():.4f}"
    )
    print(
        "Total inventory value score: "
        f"{inventory['candidate_right_value_score'].sum():.4f}"
    )
    print(
        "Canonical team value score: "
        f"{team_reconciliation['canonical_final_team_value_score'].sum():.4f}"
    )
    print(
        "Maximum team value difference: "
        f"{team_reconciliation['absolute_value_difference'].max():.10f}"
    )
    print(
        "Component primary sources covered: "
        f"{int(source_coverage['source_covered_by_inventory'].sum()):,}"
        f"/{len(source_coverage):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print("Inventory release valid: True")
    print()

    print("INVENTORY SUMMARY")
    display_summary = inventory_summary.copy()

    for column in [
        "expected_pick_count",
        "total_value_score",
    ]:
        display_summary[
            column
        ] = pd.to_numeric(
            display_summary[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        display_summary.to_string(
            index=False
        )
    )
    print()

    print("TOP 10 TEAMS BY INVENTORY VALUE")
    display_teams = team_reconciliation.head(
        10
    ).copy()

    for column in [
        "optimizer_inventory_expected_pick_count",
        "optimizer_inventory_value_score",
        "canonical_final_team_value_score",
        "value_difference",
    ]:
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

    print("VALIDATION")
    print(
        validation.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")

    for path in [
        FINAL_INVENTORY_PARQUET_PATH,
        FINAL_INVENTORY_CSV_PATH,
        TEAM_RECONCILIATION_PATH,
        SOURCE_COVERAGE_PATH,
        VALIDATION_PATH,
        INVENTORY_SUMMARY_PATH,
        ROLE_INVENTORY_AUDIT_PATH,
        CORRECTION_APPLICATION_AUDIT_PATH,
        SOURCE_OVERLAP_AUDIT_PATH_V4,
        MANIFEST_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()
