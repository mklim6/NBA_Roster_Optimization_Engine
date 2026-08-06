from __future__ import annotations

import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-valuation-final-release-v2-2026-08-04"
)

RELEASE_NAME = "future_pick_valuation_2027_2029_final_v1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v29_phx_chi_ind_nyk_enriched.parquet"
)

SOURCE_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v29_phx_chi_ind_nyk_provisional.csv"
)

SOURCE_RESIDUAL_CLAIM_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_claim_audit_after_v29.csv"
)

SOURCE_RESIDUAL_GROUP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_dependency_group_audit_after_v29.csv"
)

SOURCE_RESIDUAL_ASSET_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_residual_unique_asset_exposure_after_v29.csv"
)

SOURCE_OUT_OF_HORIZON_TAILS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_modeled_out_of_horizon_tails_after_v29.csv"
)

SOURCE_TEAM_INTEGRITY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_team_summary_integrity_audit_after_v29.csv"
)

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FINAL_VALUATION_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

FINAL_VALUATION_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_final.csv"
)

FINAL_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_final.csv"
)

FINAL_METHOD_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_valuation_method_summary_final.csv"
)

FINAL_TEAM_RANKING_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_ranking_final.csv"
)

FINAL_COMPLETION_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_valuation_completion_audit_final.csv"
)

FINAL_MANIFEST_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_valuation_release_manifest_final.csv"
)

FINAL_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_valuation_completion_metadata_final.json"
)


EXPECTED_CLAIM_ROWS = 185
EXPECTED_TEAM_ROWS = 30
EXPECTED_UNRESOLVED_ROWS = 0
EXPECTED_OUT_OF_HORIZON_TAIL_ROWS = 1

SOURCE_FINAL_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_"
    "after_phx_chi_ind_nyk_component_provisional"
)

CANONICAL_FINAL_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_final"
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


def file_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:
        for chunk in iter(
            lambda: file.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


def file_manifest_row(
    path: Path,
    file_role: str,
) -> dict[str, Any]:
    return {
        "file_role": file_role,
        "file_name": path.name,
        "file_path": str(path),
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "sha256": file_sha256(
            path
        ),
    }


def read_csv_allow_empty(
    path: Path,
) -> pd.DataFrame:
    try:
        return normalize_columns(
            pd.read_csv(
                path
            )
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def count_unresolved_claim_audit_rows(
    frame: pd.DataFrame,
) -> int:
    if frame.empty:
        return 0

    if "claim_unresolved" in frame.columns:
        values = frame[
            "claim_unresolved"
        ]

        if pd.api.types.is_bool_dtype(
            values
        ):
            return int(
                values.fillna(
                    False
                ).sum()
            )

        normalized = (
            values
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        return int(
            normalized.isin(
                {
                    "true",
                    "1",
                    "yes",
                }
            ).sum()
        )

    if "audit_state" in frame.columns:
        return int(
            frame[
                "audit_state"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .eq(
                "unresolved_in_current_horizon"
            )
            .sum()
        )

    if "valuation_status" in frame.columns:
        unresolved_status = (
            frame[
                "valuation_status"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .eq(
                "requires_dependency_review"
            )
        )

        if "valuation_method" in frame.columns:
            unresolved_method = (
                frame[
                    "valuation_method"
                ]
                .fillna("")
                .astype(str)
                .str.strip()
                .eq(
                    "not_automatically_valued"
                )
            )
        else:
            unresolved_method = pd.Series(
                False,
                index=frame.index,
                dtype=bool,
            )

        return int(
            (
                unresolved_status
                | unresolved_method
            ).sum()
        )

    raise ValueError(
        "The residual claim audit does not contain a recognized "
        "unresolved-row indicator."
    )


def detect_integrity_passed(
    frame: pd.DataFrame,
) -> bool:
    if frame.empty:
        return False

    candidate_columns = [
        column
        for column in frame.columns
        if "integrity" in column
        and "pass" in column
    ]

    if not candidate_columns:
        candidate_columns = [
            column
            for column in frame.columns
            if column.endswith(
                "_passed"
            )
        ]

    if not candidate_columns:
        raise ValueError(
            "Could not identify an integrity-passed column in the "
            "team-summary audit."
        )

    values = []

    for column in candidate_columns:
        series = frame[
            column
        ]

        if pd.api.types.is_bool_dtype(
            series
        ):
            values.extend(
                series.dropna().tolist()
            )
            continue

        normalized = (
            series
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
        )

        values.extend(
            normalized.isin(
                {
                    "true",
                    "1",
                    "yes",
                    "passed",
                }
            ).tolist()
        )

    return bool(
        values
        and all(
            values
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
        SOURCE_VALUATION_PATH,
        SOURCE_TEAM_SUMMARY_PATH,
        SOURCE_RESIDUAL_CLAIM_AUDIT_PATH,
        SOURCE_RESIDUAL_GROUP_AUDIT_PATH,
        SOURCE_RESIDUAL_ASSET_AUDIT_PATH,
        SOURCE_OUT_OF_HORIZON_TAILS_PATH,
        SOURCE_TEAM_INTEGRITY_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required final-release input was not found:\n"
                f"{path}"
            )

    valuations = normalize_columns(
        pd.read_parquet(
            SOURCE_VALUATION_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            SOURCE_TEAM_SUMMARY_PATH
        )
    )

    residual_claims = read_csv_allow_empty(
        SOURCE_RESIDUAL_CLAIM_AUDIT_PATH
    )

    residual_groups = read_csv_allow_empty(
        SOURCE_RESIDUAL_GROUP_AUDIT_PATH
    )

    residual_assets = read_csv_allow_empty(
        SOURCE_RESIDUAL_ASSET_AUDIT_PATH
    )

    out_of_horizon_tails = read_csv_allow_empty(
        SOURCE_OUT_OF_HORIZON_TAILS_PATH
    )

    team_integrity = normalize_columns(
        pd.read_csv(
            SOURCE_TEAM_INTEGRITY_PATH
        )
    )

    return (
        valuations,
        team_summary,
        residual_claims,
        residual_groups,
        residual_assets,
        out_of_horizon_tails,
        team_integrity,
    )


def validate_release(
    valuations: pd.DataFrame,
    team_summary: pd.DataFrame,
    residual_claims: pd.DataFrame,
    residual_groups: pd.DataFrame,
    residual_assets: pd.DataFrame,
    out_of_horizon_tails: pd.DataFrame,
    team_integrity: pd.DataFrame,
) -> pd.DataFrame:
    require_columns(
        valuations,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
            "valuation_status",
        ],
        "V29 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            SOURCE_FINAL_VALUE_COLUMN,
        ],
        "V29 provisional team summary",
    )

    total_claim_rows = int(
        len(
            valuations
        )
    )

    unique_claim_ids = int(
        valuations[
            "claim_id"
        ]
        .astype(str)
        .nunique()
    )

    valued_mask = (
        valuations[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .str.startswith(
            "valued_"
        )
    )

    unresolved_status_mask = (
        valuations[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "requires_dependency_review"
        )
    )

    unresolved_method_mask = (
        valuations[
            "valuation_method"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "not_automatically_valued"
        )
    )

    valued_claim_rows = int(
        valued_mask.sum()
    )

    unresolved_claim_rows = int(
        (
            unresolved_status_mask
            | unresolved_method_mask
        ).sum()
    )

    team_rows = int(
        len(
            team_summary
        )
    )

    unique_teams = int(
        team_summary[
            "candidate_beneficiary_team"
        ]
        .astype(str)
        .nunique()
    )

    duplicate_team_rows = int(
        team_summary[
            "candidate_beneficiary_team"
        ]
        .astype(str)
        .duplicated()
        .sum()
    )

    final_values = pd.to_numeric(
        team_summary[
            SOURCE_FINAL_VALUE_COLUMN
        ],
        errors="coerce",
    )

    nonfinite_team_values = int(
        (
            ~np.isfinite(
                final_values
            )
        ).sum()
    )

    integrity_passed = detect_integrity_passed(
        team_integrity
    )

    residual_claim_unresolved_rows = (
        count_unresolved_claim_audit_rows(
            residual_claims
        )
    )

    checks = [
        {
            "check_name": "expected_claim_row_count",
            "observed_value": total_claim_rows,
            "expected_value": EXPECTED_CLAIM_ROWS,
            "passed": total_claim_rows == EXPECTED_CLAIM_ROWS,
        },
        {
            "check_name": "unique_claim_id_count",
            "observed_value": unique_claim_ids,
            "expected_value": EXPECTED_CLAIM_ROWS,
            "passed": unique_claim_ids == EXPECTED_CLAIM_ROWS,
        },
        {
            "check_name": "fully_valued_claim_rows",
            "observed_value": valued_claim_rows,
            "expected_value": EXPECTED_CLAIM_ROWS,
            "passed": valued_claim_rows == EXPECTED_CLAIM_ROWS,
        },
        {
            "check_name": "unresolved_valuation_rows",
            "observed_value": unresolved_claim_rows,
            "expected_value": EXPECTED_UNRESOLVED_ROWS,
            "passed": unresolved_claim_rows == EXPECTED_UNRESOLVED_ROWS,
        },
        {
            "check_name": "residual_claim_audit_unresolved_rows",
            "observed_value": residual_claim_unresolved_rows,
            "expected_value": EXPECTED_UNRESOLVED_ROWS,
            "passed": (
                residual_claim_unresolved_rows
                == EXPECTED_UNRESOLVED_ROWS
            ),
        },
        {
            "check_name": "residual_group_audit_rows",
            "observed_value": int(
                len(
                    residual_groups
                )
            ),
            "expected_value": EXPECTED_UNRESOLVED_ROWS,
            "passed": len(
                residual_groups
            ) == EXPECTED_UNRESOLVED_ROWS,
        },
        {
            "check_name": "residual_asset_audit_rows",
            "observed_value": int(
                len(
                    residual_assets
                )
            ),
            "expected_value": EXPECTED_UNRESOLVED_ROWS,
            "passed": len(
                residual_assets
            ) == EXPECTED_UNRESOLVED_ROWS,
        },
        {
            "check_name": "modeled_out_of_horizon_tail_rows",
            "observed_value": int(
                len(
                    out_of_horizon_tails
                )
            ),
            "expected_value": EXPECTED_OUT_OF_HORIZON_TAIL_ROWS,
            "passed": len(
                out_of_horizon_tails
            ) == EXPECTED_OUT_OF_HORIZON_TAIL_ROWS,
        },
        {
            "check_name": "team_summary_row_count",
            "observed_value": team_rows,
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": team_rows == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "unique_team_count",
            "observed_value": unique_teams,
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": unique_teams == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "duplicate_team_rows",
            "observed_value": duplicate_team_rows,
            "expected_value": 0,
            "passed": duplicate_team_rows == 0,
        },
        {
            "check_name": "nonfinite_final_team_values",
            "observed_value": nonfinite_team_values,
            "expected_value": 0,
            "passed": nonfinite_team_values == 0,
        },
        {
            "check_name": "source_team_summary_integrity",
            "observed_value": integrity_passed,
            "expected_value": True,
            "passed": integrity_passed,
        },
    ]

    audit = pd.DataFrame(
        checks
    )

    if not audit[
        "passed"
    ].all():
        failed = audit.loc[
            ~audit[
                "passed"
            ]
        ]

        raise RuntimeError(
            "The future-pick final release failed validation:\n"
            + failed.to_string(
                index=False
            )
        )

    return audit


def build_final_valuation_layer(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    output[
        "future_pick_valuation_release"
    ] = RELEASE_NAME

    output[
        "future_pick_valuation_release_version"
    ] = SCRIPT_VERSION

    output[
        "future_pick_valuation_is_final"
    ] = True

    output[
        "future_pick_valuation_finalized_at_utc"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    return output


def build_final_team_summary(
    team_summary: pd.DataFrame,
) -> pd.DataFrame:
    output = team_summary.copy()

    output[
        CANONICAL_FINAL_VALUE_COLUMN
    ] = pd.to_numeric(
        output[
            SOURCE_FINAL_VALUE_COLUMN
        ],
        errors="raise",
    )

    output[
        "future_pick_valuation_release"
    ] = RELEASE_NAME

    output[
        "future_pick_valuation_release_version"
    ] = SCRIPT_VERSION

    output[
        "future_pick_valuation_is_final"
    ] = True

    output[
        "future_pick_value_rank"
    ] = (
        output[
            CANONICAL_FINAL_VALUE_COLUMN
        ]
        .rank(
            method="min",
            ascending=False,
        )
        .astype(int)
    )

    return output.sort_values(
        [
            "future_pick_value_rank",
            "candidate_beneficiary_team",
        ]
    ).reset_index(
        drop=True
    )


def build_method_summary(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    summary = (
        valuations.groupby(
            [
                "valuation_method",
                "valuation_status",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            claim_rows=(
                "claim_id",
                "size",
            ),
            unique_claims=(
                "claim_id",
                "nunique",
            ),
            unique_assets=(
                "asset_key",
                "nunique",
            ),
        )
        .sort_values(
            [
                "claim_rows",
                "valuation_method",
                "valuation_status",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )

    return summary


def build_team_ranking(
    final_team_summary: pd.DataFrame,
) -> pd.DataFrame:
    preferred_columns = [
        "future_pick_value_rank",
        "candidate_beneficiary_team",
        CANONICAL_FINAL_VALUE_COLUMN,
    ]

    optional_columns = [
        column
        for column in [
            "candidate_asset_count",
            "candidate_first_round_asset_count",
            "candidate_second_round_asset_count",
            "candidate_expected_pick_count",
        ]
        if column in final_team_summary.columns
    ]

    columns = preferred_columns + optional_columns

    return final_team_summary[
        columns
    ].copy()


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
    print("FUTURE PICK VALUATION FINAL RELEASE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    (
        valuations,
        team_summary,
        residual_claims,
        residual_groups,
        residual_assets,
        out_of_horizon_tails,
        team_integrity,
    ) = load_inputs()

    completion_audit = validate_release(
        valuations=valuations,
        team_summary=team_summary,
        residual_claims=residual_claims,
        residual_groups=residual_groups,
        residual_assets=residual_assets,
        out_of_horizon_tails=out_of_horizon_tails,
        team_integrity=team_integrity,
    )

    final_valuations = build_final_valuation_layer(
        valuations
    )

    final_team_summary = build_final_team_summary(
        team_summary
    )

    method_summary = build_method_summary(
        final_valuations
    )

    team_ranking = build_team_ranking(
        final_team_summary
    )

    final_valuations.to_parquet(
        FINAL_VALUATION_PARQUET_PATH,
        index=False,
    )

    final_valuations.to_csv(
        FINAL_VALUATION_CSV_PATH,
        index=False,
    )

    final_team_summary.to_csv(
        FINAL_TEAM_SUMMARY_PATH,
        index=False,
    )

    method_summary.to_csv(
        FINAL_METHOD_SUMMARY_PATH,
        index=False,
    )

    team_ranking.to_csv(
        FINAL_TEAM_RANKING_PATH,
        index=False,
    )

    completion_audit.to_csv(
        FINAL_COMPLETION_AUDIT_PATH,
        index=False,
    )

    source_manifest_rows = [
        file_manifest_row(
            SOURCE_VALUATION_PATH,
            "source_v29_valuation_layer",
        ),
        file_manifest_row(
            SOURCE_TEAM_SUMMARY_PATH,
            "source_v29_team_summary",
        ),
        file_manifest_row(
            SOURCE_RESIDUAL_CLAIM_AUDIT_PATH,
            "source_final_residual_claim_audit",
        ),
        file_manifest_row(
            SOURCE_RESIDUAL_GROUP_AUDIT_PATH,
            "source_final_residual_group_audit",
        ),
        file_manifest_row(
            SOURCE_RESIDUAL_ASSET_AUDIT_PATH,
            "source_final_residual_asset_audit",
        ),
        file_manifest_row(
            SOURCE_OUT_OF_HORIZON_TAILS_PATH,
            "source_out_of_horizon_tail_audit",
        ),
        file_manifest_row(
            SOURCE_TEAM_INTEGRITY_PATH,
            "source_team_summary_integrity_audit",
        ),
    ]

    final_manifest_rows = [
        file_manifest_row(
            FINAL_VALUATION_PARQUET_PATH,
            "final_valuation_layer_parquet",
        ),
        file_manifest_row(
            FINAL_VALUATION_CSV_PATH,
            "final_valuation_layer_csv",
        ),
        file_manifest_row(
            FINAL_TEAM_SUMMARY_PATH,
            "final_team_summary",
        ),
        file_manifest_row(
            FINAL_METHOD_SUMMARY_PATH,
            "final_method_summary",
        ),
        file_manifest_row(
            FINAL_TEAM_RANKING_PATH,
            "final_team_ranking",
        ),
        file_manifest_row(
            FINAL_COMPLETION_AUDIT_PATH,
            "final_completion_audit",
        ),
    ]

    manifest = pd.DataFrame(
        source_manifest_rows
        + final_manifest_rows
    )

    manifest[
        "release_name"
    ] = RELEASE_NAME

    manifest[
        "release_version"
    ] = SCRIPT_VERSION

    manifest.to_csv(
        FINAL_MANIFEST_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "claim_rows": int(
            len(
                final_valuations
            )
        ),
        "fully_valued_claim_rows": int(
            final_valuations[
                "valuation_status"
            ]
            .fillna("")
            .astype(str)
            .str.startswith(
                "valued_"
            )
            .sum()
        ),
        "unresolved_claim_rows": 0,
        "unresolved_dependency_groups": 0,
        "unresolved_unique_assets": 0,
        "unresolved_asset_exposure_score": 0.0,
        "modeled_out_of_horizon_tail_rows": int(
            len(
                out_of_horizon_tails
            )
        ),
        "team_rows": int(
            len(
                final_team_summary
            )
        ),
        "team_summary_integrity_passed": True,
        "canonical_final_team_value_column": (
            CANONICAL_FINAL_VALUE_COLUMN
        ),
        "completion_checks_passed": bool(
            completion_audit[
                "passed"
            ].all()
        ),
        "outputs": {
            "final_valuation_parquet": str(
                FINAL_VALUATION_PARQUET_PATH
            ),
            "final_valuation_csv": str(
                FINAL_VALUATION_CSV_PATH
            ),
            "final_team_summary": str(
                FINAL_TEAM_SUMMARY_PATH
            ),
            "final_method_summary": str(
                FINAL_METHOD_SUMMARY_PATH
            ),
            "final_team_ranking": str(
                FINAL_TEAM_RANKING_PATH
            ),
            "final_completion_audit": str(
                FINAL_COMPLETION_AUDIT_PATH
            ),
            "final_manifest": str(
                FINAL_MANIFEST_PATH
            ),
        },
    }

    with FINAL_METADATA_PATH.open(
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
    print("FINAL RELEASE CREATED")
    print("=" * 80)
    print(
        "Claim rows: "
        f"{len(final_valuations):,}"
    )
    print(
        "Fully valued claim rows: "
        f"{int(final_valuations['valuation_status'].fillna('').astype(str).str.startswith('valued_').sum()):,}"
    )
    print("Unresolved claim rows: 0")
    print("Unresolved dependency groups: 0")
    print("Unresolved unique assets: 0")
    print("Unresolved asset exposure score: 0.0000")
    print(
        "Modeled out-of-horizon tail rows: "
        f"{len(out_of_horizon_tails):,}"
    )
    print(
        "Team rows: "
        f"{len(final_team_summary):,}"
    )
    print(
        "All completion checks passed: "
        f"{bool(completion_audit['passed'].all())}"
    )
    print()

    print("TOP 10 TEAMS BY FINAL FUTURE-PICK VALUE")
    print(
        team_ranking.head(
            10
        ).to_string(
            index=False
        )
    )
    print()

    print("VALUATION METHOD SUMMARY")
    print(
        method_summary.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")

    for path in [
        FINAL_VALUATION_PARQUET_PATH,
        FINAL_VALUATION_CSV_PATH,
        FINAL_TEAM_SUMMARY_PATH,
        FINAL_METHOD_SUMMARY_PATH,
        FINAL_TEAM_RANKING_PATH,
        FINAL_COMPLETION_AUDIT_PATH,
        FINAL_MANIFEST_PATH,
        FINAL_METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()