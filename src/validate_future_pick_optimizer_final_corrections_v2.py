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
    "future-pick-optimizer-final-correction-validation-v2-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POLICY_TEAM_COMPARISON_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_policy_team_comparison_v1.csv"
)

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

UTAH_POOL_RIGHTS_FILE_STEM = (
    "future_pick_utah_2028_pool_candidate_rights_ledger_v1"
)

UTAH_POOL_ADJUSTMENTS_FILE_STEM = (
    "future_pick_utah_2028_pool_full_team_adjustments_v1"
)

REJECTED_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CORRECTION_LEDGER_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_ledger_v1.csv"
)

CORRECTED_TEAM_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_corrected_team_reconciliation_proof_v1.csv"
)

UTAH_POOL_SCHEMA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_utah_pool_rights_schema_v1.csv"
)

UTAH_POOL_RIGHTS_EXTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_utah_pool_rights_extract_v1.csv"
)

MIA_ROLLOVER_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_mia_rollover_correction_audit_v1.csv"
)

CLE_MIN_UTA_RECOVERY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_cle_min_uta_2027_first_round_recovery_v1.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_validation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_metadata_v1.json"
)


BEST_POLICY = "role_split_swap_to_beneficiary"

UTAH_CORRECTION_TEAMS = {
    "CHA",
    "DET",
    "PHI",
    "UTA",
}

MIA_CLAIM_ID = "2027_R1_MIA_C1"

CLE_MIN_UTA_COMPONENT_FILE = (
    "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet"
)

VALUE_TOLERANCE = 1e-6
EXPECTED_TEAM_ROWS = 30


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


def first_existing_column(
    frame: pd.DataFrame,
    candidates: list[str],
) -> str:
    for column in candidates:
        if column in frame.columns:
            return column

    return ""


def resolve_project_table(
    file_stem: str,
) -> Path:
    search_directories = [
        PROJECT_ROOT / "outputs",
        PROJECT_ROOT / "data" / "processed",
    ]

    candidate_paths = []

    for directory in search_directories:
        for suffix in [
            ".csv",
            ".parquet",
        ]:
            path = directory / f"{file_stem}{suffix}"

            if path.exists():
                candidate_paths.append(
                    path
                )

    if not candidate_paths:
        searched = [
            str(
                directory
                / f"{file_stem}.csv"
            )
            for directory in search_directories
        ] + [
            str(
                directory
                / f"{file_stem}.parquet"
            )
            for directory in search_directories
        ]

        raise FileNotFoundError(
            "Required project table was not found. Searched:\n"
            + "\n".join(
                searched
            )
        )

    preferred = sorted(
        candidate_paths,
        key=lambda path: (
            0
            if path.suffix.lower()
            == ".parquet"
            else 1,
            0
            if "processed" in path.parts
            else 1,
            str(
                path
            ),
        ),
    )

    return preferred[
        0
    ]


def read_project_table(
    path: Path,
) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return normalize_columns(
            pd.read_parquet(
                path
            )
        )

    if path.suffix.lower() == ".csv":
        return normalize_columns(
            pd.read_csv(
                path
            )
        )

    raise ValueError(
        f"Unsupported project-table extension: {path}"
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    utah_pool_rights_path = resolve_project_table(
        UTAH_POOL_RIGHTS_FILE_STEM
    )

    utah_pool_adjustments_path = resolve_project_table(
        UTAH_POOL_ADJUSTMENTS_FILE_STEM
    )

    required_paths = [
        POLICY_TEAM_COMPARISON_PATH,
        FINAL_VALUATION_PATH,
        REJECTED_INVENTORY_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required correction-validation input was not found:\n"
                f"{path}"
            )

    policy_teams = normalize_columns(
        pd.read_csv(
            POLICY_TEAM_COMPARISON_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
        )
    )

    utah_rights = read_project_table(
        utah_pool_rights_path
    )

    utah_adjustments = read_project_table(
        utah_pool_adjustments_path
    )

    utah_rights.attrs[
        "resolved_source_path"
    ] = str(
        utah_pool_rights_path
    )

    utah_adjustments.attrs[
        "resolved_source_path"
    ] = str(
        utah_pool_adjustments_path
    )

    rejected_inventory = normalize_columns(
        pd.read_parquet(
            REJECTED_INVENTORY_PATH
        )
    )

    require_columns(
        policy_teams,
        [
            "policy",
            "candidate_team",
            "canonical_final_team_value_score",
            "component_right_value_score",
            "policy_direct_value_score",
            "policy_inventory_value_score",
            "policy_value_difference",
        ],
        "Policy team comparison",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
        ],
        "Canonical valuation layer",
    )

    return (
        policy_teams,
        valuations,
        utah_rights,
        utah_adjustments,
        rejected_inventory,
    )


def build_schema_audit(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for column in frame.columns:
        series = frame[
            column
        ]

        numeric = pd.to_numeric(
            series,
            errors="coerce",
        )

        rows.append(
            {
                "column_name": column,
                "dtype": str(
                    series.dtype
                ),
                "row_count": int(
                    len(
                        series
                    )
                ),
                "non_null_rows": int(
                    series.notna().sum()
                ),
                "non_empty_rows": int(
                    series
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .ne("")
                    .sum()
                ),
                "numeric_rows": int(
                    numeric.notna().sum()
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def extract_utah_pool_rights(
    utah_rights: pd.DataFrame,
) -> pd.DataFrame:
    team_column = first_existing_column(
        utah_rights,
        [
            "candidate_team",
            "candidate_beneficiary_team",
            "team",
        ],
    )

    value_column = first_existing_column(
        utah_rights,
        [
            "expected_candidate_right_value_score",
            "full_integrated_right_value_score",
            "candidate_right_value_score",
            "expected_value_score",
            "net_team_adjustment_value_score",
        ],
    )

    if not team_column or not value_column:
        raise RuntimeError(
            "Could not identify the Utah-pool candidate team and value "
            "columns."
        )

    output = utah_rights.copy()

    output[
        "candidate_team_normalized"
    ] = (
        output[
            team_column
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "utah_pool_candidate_right_value_score"
    ] = pd.to_numeric(
        output[
            value_column
        ],
        errors="coerce",
    )

    output[
        "detected_team_column"
    ] = team_column

    output[
        "detected_value_column"
    ] = value_column

    resolved_source_path = clean_text(
        utah_rights.attrs.get(
            "resolved_source_path",
            "",
        )
    )

    output = output.loc[
        output[
            "candidate_team_normalized"
        ].isin(
            UTAH_CORRECTION_TEAMS
        )
    ].copy()

    output.attrs[
        "resolved_source_path"
    ] = resolved_source_path

    if output[
        "utah_pool_candidate_right_value_score"
    ].isna().any():
        raise RuntimeError(
            "At least one targeted Utah-pool right has no numeric value."
        )

    return output


def aggregate_utah_corrections(
    utah_extract: pd.DataFrame,
) -> pd.DataFrame:
    output = (
        utah_extract.groupby(
            "candidate_team_normalized",
            as_index=False,
        )
        .agg(
            correction_value_score=(
                "utah_pool_candidate_right_value_score",
                "sum",
            ),
            source_right_rows=(
                "utah_pool_candidate_right_value_score",
                "size",
            ),
        )
        .rename(
            columns={
                "candidate_team_normalized": "candidate_team",
            }
        )
    )

    output[
        "correction_type"
    ] = "add_missing_utah_2028_pool_candidate_right"

    resolved_source_path = clean_text(
        utah_extract.attrs.get(
            "resolved_source_path",
            "",
        )
    )

    output[
        "source_reference"
    ] = (
        Path(
            resolved_source_path
        ).name
        if resolved_source_path
        else UTAH_POOL_RIGHTS_FILE_STEM
    )

    output[
        "claim_id"
    ] = ""

    output[
        "correction_sign"
    ] = 1.0

    return output


def build_mia_correction(
    valuations: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    float,
]:
    row = valuations.loc[
        valuations[
            "claim_id"
        ]
        .fillna("")
        .astype(str)
        .eq(
            MIA_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise RuntimeError(
            f"Expected exactly one {MIA_CLAIM_ID} row, "
            f"found {len(row)}."
        )

    fallback_column = first_existing_column(
        row,
        [
            "expected_fallback_transfer_value_score",
            "fallback_transfer_value_score",
        ],
    )

    retained_column = first_existing_column(
        row,
        [
            "expected_retained_value_score",
            "retained_value_score",
        ],
    )

    if not fallback_column or not retained_column:
        raise RuntimeError(
            "The Miami rollover row is missing fallback or retained "
            "value columns."
        )

    fallback_value = finite_or_nan(
        row.iloc[
            0
        ][
            fallback_column
        ]
    )

    retained_value = finite_or_nan(
        row.iloc[
            0
        ][
            retained_column
        ]
    )

    if not np.isfinite(
        fallback_value
    ):
        raise RuntimeError(
            "Miami fallback-transfer value is not finite."
        )

    if not np.isfinite(
        retained_value
    ):
        raise RuntimeError(
            "Miami retained value is not finite."
        )

    audit = row.copy()

    audit[
        "detected_fallback_column"
    ] = fallback_column

    audit[
        "detected_retained_column"
    ] = retained_column

    audit[
        "fallback_value_to_remove_from_mia"
    ] = fallback_value

    audit[
        "mia_net_retained_value_after_fallback"
    ] = (
        retained_value
        - fallback_value
    )

    return (
        audit,
        float(
            fallback_value
        ),
    )


def build_correction_ledger(
    utah_corrections: pd.DataFrame,
    mia_fallback_value: float,
) -> pd.DataFrame:
    mia = pd.DataFrame(
        [
            {
                "candidate_team": "MIA",
                "correction_value_score": (
                    -mia_fallback_value
                ),
                "source_right_rows": 1,
                "correction_type": (
                    "subtract_rollover_fallback_from_retaining_team"
                ),
                "source_reference": MIA_CLAIM_ID,
                "claim_id": MIA_CLAIM_ID,
                "correction_sign": -1.0,
            }
        ]
    )

    return pd.concat(
        [
            utah_corrections,
            mia,
        ],
        ignore_index=True,
        sort=False,
    ).sort_values(
        "candidate_team"
    ).reset_index(
        drop=True
    )


def apply_corrections(
    policy_teams: pd.DataFrame,
    correction_ledger: pd.DataFrame,
) -> pd.DataFrame:
    base = policy_teams.loc[
        policy_teams[
            "policy"
        ]
        .fillna("")
        .astype(str)
        .eq(
            BEST_POLICY
        )
    ].copy()

    if len(
        base
    ) != EXPECTED_TEAM_ROWS:
        raise RuntimeError(
            "Best-policy team row count is not 30."
        )

    corrections = (
        correction_ledger.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            correction_value_score=(
                "correction_value_score",
                "sum",
            ),
            correction_rows=(
                "correction_type",
                "size",
            ),
            correction_types=(
                "correction_type",
                lambda values: "|".join(
                    sorted(
                        set(
                            clean_text(
                                value
                            )
                            for value in values
                        )
                    )
                ),
            ),
        )
    )

    output = base.merge(
        corrections,
        how="left",
        on="candidate_team",
        validate="one_to_one",
    )

    output[
        "correction_value_score"
    ] = pd.to_numeric(
        output[
            "correction_value_score"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    output[
        "correction_rows"
    ] = pd.to_numeric(
        output[
            "correction_rows"
        ],
        errors="coerce",
    ).fillna(
        0
    ).astype(
        int
    )

    output[
        "corrected_inventory_value_score"
    ] = (
        pd.to_numeric(
            output[
                "policy_inventory_value_score"
            ],
            errors="raise",
        )
        + output[
            "correction_value_score"
        ]
    )

    output[
        "corrected_value_difference"
    ] = (
        output[
            "corrected_inventory_value_score"
        ]
        - pd.to_numeric(
            output[
                "canonical_final_team_value_score"
            ],
            errors="raise",
        )
    )

    output[
        "absolute_corrected_value_difference"
    ] = output[
        "corrected_value_difference"
    ].abs()

    output[
        "corrected_team_reconciliation_passed"
    ] = (
        output[
            "absolute_corrected_value_difference"
        ]
        <= VALUE_TOLERANCE
    )

    return output.sort_values(
        [
            "corrected_team_reconciliation_passed",
            "absolute_corrected_value_difference",
            "candidate_team",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def recover_cle_min_uta_sources(
    rejected_inventory: pd.DataFrame,
) -> pd.DataFrame:
    rows = rejected_inventory.loc[
        rejected_inventory[
            "component_right_file"
        ]
        .fillna("")
        .astype(str)
        .eq(
            CLE_MIN_UTA_COMPONENT_FILE
        )
    ].copy()

    output_rows = []

    for row in rows.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        raw_json = clean_text(
            row_dict.get(
                "component_raw_row_json",
                "",
            )
        )

        try:
            raw = (
                json.loads(
                    raw_json
                )
                if raw_json
                else {}
            )
        except json.JSONDecodeError:
            raw = {}

        description = clean_text(
            raw.get(
                "right_description",
                "",
            )
        )

        year_match = re.search(
            r"\b20(?:27|28|29)\b",
            description,
        )

        teams = sorted(
            set(
                re.findall(
                    r"\b(?:CLE|MIN|UTA)\b",
                    description.upper(),
                )
            )
        )

        round_number = (
            1
            if re.search(
                r"\b(?:firsts?|1st(?:-round)?(?:\s+picks?)?)\b",
                description,
                flags=re.IGNORECASE,
            )
            else (
                2
                if re.search(
                    r"\b(?:seconds?|2nd(?:-round)?(?:\s+picks?)?)\b",
                    description,
                    flags=re.IGNORECASE,
                )
                else None
            )
        )

        source_assets = (
            [
                f"{year_match.group(0)}_R{round_number}_{team}"
                for team in teams
            ]
            if (
                year_match
                and round_number is not None
                and teams
            )
            else []
        )

        expected_source_count = finite_or_nan(
            raw.get(
                "source_asset_count",
                np.nan,
            )
        )

        output_rows.append(
            {
                "candidate_team": clean_text(
                    row_dict.get(
                        "candidate_team",
                        "",
                    )
                ).upper(),
                "candidate_right_value_score": finite_or_nan(
                    row_dict.get(
                        "candidate_right_value_score",
                        np.nan,
                    )
                ),
                "expected_pick_count": finite_or_nan(
                    row_dict.get(
                        "expected_pick_count",
                        np.nan,
                    )
                ),
                "right_description": description,
                "recovered_draft_year": (
                    int(
                        year_match.group(
                            0
                        )
                    )
                    if year_match
                    else np.nan
                ),
                "recovered_round_number": round_number,
                "recovered_source_assets": "|".join(
                    source_assets
                ),
                "recovered_source_asset_count": len(
                    source_assets
                ),
                "declared_source_asset_count": (
                    expected_source_count
                ),
                "source_count_reconciliation_passed": bool(
                    source_assets
                    and (
                        not np.isfinite(
                            expected_source_count
                        )
                        or len(
                            source_assets
                        )
                        == int(
                            expected_source_count
                        )
                    )
                ),
            }
        )

    return pd.DataFrame(
        output_rows
    ).sort_values(
        "candidate_team"
    ).reset_index(
        drop=True
    )


def build_validation(
    corrected: pd.DataFrame,
    correction_ledger: pd.DataFrame,
    utah_extract: pd.DataFrame,
    cle_min_uta_recovery: pd.DataFrame,
) -> pd.DataFrame:
    system_difference = float(
        corrected[
            "corrected_value_difference"
        ].sum()
    )

    maximum_team_difference = float(
        corrected[
            "absolute_corrected_value_difference"
        ].max()
    )

    checks = [
        {
            "check_name": "corrected_team_row_count",
            "observed_value": int(
                len(
                    corrected
                )
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": len(
                corrected
            ) == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "all_corrected_teams_reconciled",
            "observed_value": int(
                corrected[
                    "corrected_team_reconciliation_passed"
                ].sum()
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": bool(
                corrected[
                    "corrected_team_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "corrected_system_value_difference",
            "observed_value": system_difference,
            "expected_value": 0.0,
            "passed": abs(
                system_difference
            )
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "maximum_corrected_team_difference",
            "observed_value": maximum_team_difference,
            "expected_value": 0.0,
            "passed": maximum_team_difference
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "correction_team_count",
            "observed_value": int(
                correction_ledger[
                    "candidate_team"
                ].nunique()
            ),
            "expected_value": 5,
            "passed": correction_ledger[
                "candidate_team"
            ].nunique()
            == 5,
        },
        {
            "check_name": "utah_pool_correction_team_count",
            "observed_value": int(
                utah_extract[
                    "candidate_team_normalized"
                ].nunique()
            ),
            "expected_value": 4,
            "passed": utah_extract[
                "candidate_team_normalized"
            ].nunique()
            == 4,
        },
        {
            "check_name": "cle_min_uta_candidate_rows",
            "observed_value": int(
                len(
                    cle_min_uta_recovery
                )
            ),
            "expected_value": 3,
            "passed": len(
                cle_min_uta_recovery
            )
            == 3,
        },
        {
            "check_name": "cle_min_uta_all_sources_recovered",
            "observed_value": int(
                cle_min_uta_recovery[
                    "source_count_reconciliation_passed"
                ].sum()
            ),
            "expected_value": 3,
            "passed": bool(
                len(
                    cle_min_uta_recovery
                )
                == 3
                and cle_min_uta_recovery[
                    "source_count_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "cle_min_uta_round_is_first",
            "observed_value": "|".join(
                sorted(
                    set(
                        pd.to_numeric(
                            cle_min_uta_recovery[
                                "recovered_round_number"
                            ],
                            errors="coerce",
                        )
                        .dropna()
                        .astype(int)
                        .astype(str)
                    )
                )
            ),
            "expected_value": "1",
            "passed": bool(
                pd.to_numeric(
                    cle_min_uta_recovery[
                        "recovered_round_number"
                    ],
                    errors="coerce",
                )
                .eq(
                    1
                )
                .all()
            ),
        },
    ]

    return pd.DataFrame(
        checks
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER FINAL CORRECTION VALIDATION")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        policy_teams,
        valuations,
        utah_rights,
        utah_adjustments,
        rejected_inventory,
    ) = load_inputs()

    schema = build_schema_audit(
        utah_rights
    )

    utah_extract = extract_utah_pool_rights(
        utah_rights
    )

    utah_corrections = aggregate_utah_corrections(
        utah_extract
    )

    (
        mia_audit,
        mia_fallback_value,
    ) = build_mia_correction(
        valuations
    )

    correction_ledger = build_correction_ledger(
        utah_corrections=utah_corrections,
        mia_fallback_value=mia_fallback_value,
    )

    corrected = apply_corrections(
        policy_teams=policy_teams,
        correction_ledger=correction_ledger,
    )

    cle_min_uta_recovery = recover_cle_min_uta_sources(
        rejected_inventory
    )

    validation = build_validation(
        corrected=corrected,
        correction_ledger=correction_ledger,
        utah_extract=utah_extract,
        cle_min_uta_recovery=cle_min_uta_recovery,
    )

    schema.to_csv(
        UTAH_POOL_SCHEMA_PATH,
        index=False,
    )

    utah_extract.to_csv(
        UTAH_POOL_RIGHTS_EXTRACT_PATH,
        index=False,
    )

    mia_audit.to_csv(
        MIA_ROLLOVER_AUDIT_PATH,
        index=False,
    )

    correction_ledger.to_csv(
        CORRECTION_LEDGER_PATH,
        index=False,
    )

    corrected.to_csv(
        CORRECTED_TEAM_RECONCILIATION_PATH,
        index=False,
    )

    cle_min_uta_recovery.to_csv(
        CLE_MIN_UTA_RECOVERY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "best_policy": BEST_POLICY,
        "resolved_utah_pool_rights_path": clean_text(
            utah_rights.attrs.get(
                "resolved_source_path",
                "",
            )
        ),
        "resolved_utah_pool_adjustments_path": clean_text(
            utah_adjustments.attrs.get(
                "resolved_source_path",
                "",
            )
        ),
        "utah_pool_correction_teams": sorted(
            UTAH_CORRECTION_TEAMS
        ),
        "utah_pool_correction_total": float(
            utah_corrections[
                "correction_value_score"
            ].sum()
        ),
        "mia_fallback_value_removed": float(
            mia_fallback_value
        ),
        "net_correction_total": float(
            correction_ledger[
                "correction_value_score"
            ].sum()
        ),
        "teams_reconciled": int(
            corrected[
                "corrected_team_reconciliation_passed"
            ].sum()
        ),
        "team_count": int(
            len(
                corrected
            )
        ),
        "corrected_system_difference": float(
            corrected[
                "corrected_value_difference"
            ].sum()
        ),
        "maximum_corrected_team_difference": float(
            corrected[
                "absolute_corrected_value_difference"
            ].max()
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
        "validation_passed": bool(
            failed.empty
        ),
        "outputs": {
            "correction_ledger": str(
                CORRECTION_LEDGER_PATH
            ),
            "corrected_team_reconciliation": str(
                CORRECTED_TEAM_RECONCILIATION_PATH
            ),
            "utah_pool_schema": str(
                UTAH_POOL_SCHEMA_PATH
            ),
            "utah_pool_rights_extract": str(
                UTAH_POOL_RIGHTS_EXTRACT_PATH
            ),
            "mia_rollover_audit": str(
                MIA_ROLLOVER_AUDIT_PATH
            ),
            "cle_min_uta_recovery": str(
                CLE_MIN_UTA_RECOVERY_PATH
            ),
            "validation": str(
                VALIDATION_PATH
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
    print("FINAL CORRECTION VALIDATION CREATED")
    print("=" * 80)
    print(
        "Resolved Utah-pool rights file: "
        + clean_text(
            utah_rights.attrs.get(
                "resolved_source_path",
                "",
            )
        )
    )
    print(
        "Resolved Utah-pool adjustments file: "
        + clean_text(
            utah_adjustments.attrs.get(
                "resolved_source_path",
                "",
            )
        )
    )
    print(
        "Utah-pool correction teams: "
        f"{utah_corrections['candidate_team'].nunique():,}"
    )
    print(
        "Utah-pool correction total: "
        f"{utah_corrections['correction_value_score'].sum():.6f}"
    )
    print(
        "Miami fallback value removed: "
        f"{mia_fallback_value:.6f}"
    )
    print(
        "Net correction total: "
        f"{correction_ledger['correction_value_score'].sum():.6f}"
    )
    print(
        "Teams reconciled after corrections: "
        f"{int(corrected['corrected_team_reconciliation_passed'].sum()):,}"
        f"/{len(corrected):,}"
    )
    print(
        "Corrected system difference: "
        f"{corrected['corrected_value_difference'].sum():.10f}"
    )
    print(
        "Maximum corrected team difference: "
        f"{corrected['absolute_corrected_value_difference'].max():.10f}"
    )
    print(
        "CLE-MIN-UTA source recoveries passed: "
        f"{int(cle_min_uta_recovery['source_count_reconciliation_passed'].sum()):,}"
        f"/{len(cle_min_uta_recovery):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Final correction model valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("CORRECTION LEDGER")
    display_ledger = correction_ledger.copy()

    display_ledger[
        "correction_value_score"
    ] = pd.to_numeric(
        display_ledger[
            "correction_value_score"
        ],
        errors="coerce",
    ).round(
        6
    )

    print(
        display_ledger.to_string(
            index=False
        )
    )
    print()

    print("CORRECTED TEAM RECONCILIATION")

    display_corrected = corrected.loc[
        corrected[
            "correction_value_score"
        ].abs()
        > VALUE_TOLERANCE
    ].copy()

    for column in [
        "canonical_final_team_value_score",
        "policy_inventory_value_score",
        "correction_value_score",
        "corrected_inventory_value_score",
        "corrected_value_difference",
    ]:
        display_corrected[
            column
        ] = pd.to_numeric(
            display_corrected[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_corrected[
            [
                "candidate_team",
                "canonical_final_team_value_score",
                "policy_inventory_value_score",
                "correction_value_score",
                "corrected_inventory_value_score",
                "corrected_value_difference",
                "corrected_team_reconciliation_passed",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("CLE-MIN-UTA 2027 FIRST-ROUND SOURCE RECOVERY")
    print(
        cle_min_uta_recovery.to_string(
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
        CORRECTION_LEDGER_PATH,
        CORRECTED_TEAM_RECONCILIATION_PATH,
        UTAH_POOL_SCHEMA_PATH,
        UTAH_POOL_RIGHTS_EXTRACT_PATH,
        MIA_ROLLOVER_AUDIT_PATH,
        CLE_MIN_UTA_RECOVERY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )

    if not failed.empty:
        raise RuntimeError(
            "The final correction model failed validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()