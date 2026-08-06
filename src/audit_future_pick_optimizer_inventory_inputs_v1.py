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
    "future-pick-optimizer-inventory-input-audit-v1-2026-08-04"
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

FINAL_COMPLETION_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_valuation_completion_audit_final.csv"
)

FINAL_RELEASE_MANIFEST_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_valuation_release_manifest_final.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FILE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_candidate_rights_file_catalog_v1.csv"
)

NORMALIZED_RIGHTS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_candidate_rights_discovery_v1.parquet"
)

NORMALIZED_RIGHTS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_candidate_rights_discovery_v1.csv"
)

SOURCE_OVERLAP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_source_asset_overlap_audit_v1.csv"
)

VALUATION_SCHEMA_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_valuation_schema_audit_v1.csv"
)

VALUATION_METHOD_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_valuation_method_summary_v1.csv"
)

DIRECT_CANDIDATE_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_direct_candidate_rows_v1.csv"
)

COMPONENT_PRIMARY_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_component_primary_rows_v1.csv"
)

INVENTORY_READINESS_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_readiness_audit_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_input_audit_metadata_v1.json"
)


FINAL_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_final"
)

CANDIDATE_RIGHTS_PATTERN = (
    "future_pick_*_candidate_rights_v*.parquet"
)

GENERIC_TOKENS = {
    "future",
    "pick",
    "candidate",
    "rights",
    "right",
    "source",
    "allocation",
    "component",
    "joint",
    "v",
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


def parse_versioned_file(
    path: Path,
) -> tuple[str, int]:
    match = re.match(
        r"^(.*)_v(\d+)\.parquet$",
        path.name,
        flags=re.IGNORECASE,
    )

    if not match:
        return (
            path.stem,
            0,
        )

    return (
        match.group(
            1
        ),
        int(
            match.group(
                2
            )
        ),
    )


def select_latest_candidate_right_files(
    paths: list[Path],
) -> list[Path]:
    latest: dict[str, tuple[int, Path]] = {}

    for path in paths:
        base_name, version = parse_versioned_file(
            path
        )

        existing = latest.get(
            base_name
        )

        if (
            existing is None
            or version
            > existing[
                0
            ]
        ):
            latest[
                base_name
            ] = (
                version,
                path,
            )

    return [
        value[
            1
        ]
        for _, value in sorted(
            latest.items()
        )
    ]


def tokenize(
    value: str,
) -> set[str]:
    tokens = {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            clean_text(
                value
            ).lower(),
        )
        if token
        and token not in GENERIC_TOKENS
    }

    return tokens


def best_method_match(
    file_base: str,
    methods: list[str],
) -> tuple[str, float]:
    file_tokens = tokenize(
        file_base
    )

    if not file_tokens:
        return (
            "",
            0.0,
        )

    best_method = ""
    best_score = 0.0

    for method in methods:
        method_tokens = tokenize(
            method
        )

        if not method_tokens:
            continue

        intersection = len(
            file_tokens
            & method_tokens
        )

        union = len(
            file_tokens
            | method_tokens
        )

        score = (
            intersection
            / union
            if union
            else 0.0
        )

        if score > best_score:
            best_method = method
            best_score = score

    return (
        best_method,
        float(
            best_score
        ),
    )


def parse_source_assets(
    value: Any,
) -> list[str]:
    text = clean_text(
        value
    )

    if not text:
        return []

    tokens = re.findall(
        r"20(?:27|28|29)_R[12]_[A-Z]{3}",
        text.upper(),
    )

    if tokens:
        return sorted(
            set(
                tokens
            )
        )

    return sorted(
        {
            token.strip()
            for token in re.split(
                r"[|,;]+",
                text,
            )
            if token.strip()
        }
    )


def load_core_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        FINAL_VALUATION_PATH,
        FINAL_TEAM_SUMMARY_PATH,
        FINAL_COMPLETION_AUDIT_PATH,
        FINAL_RELEASE_MANIFEST_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required canonical future-pick file was not found:\n"
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

    completion_audit = normalize_columns(
        pd.read_csv(
            FINAL_COMPLETION_AUDIT_PATH
        )
    )

    manifest = normalize_columns(
        pd.read_csv(
            FINAL_RELEASE_MANIFEST_PATH
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
        completion_audit,
        [
            "check_name",
            "passed",
        ],
        "Final completion audit",
    )

    return (
        valuations,
        team_summary,
        completion_audit,
        manifest,
    )


def completion_audit_passed(
    completion_audit: pd.DataFrame,
) -> bool:
    values = completion_audit[
        "passed"
    ]

    if pd.api.types.is_bool_dtype(
        values
    ):
        return bool(
            values.fillna(
                False
            ).all()
        )

    normalized = (
        values
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return bool(
        normalized.isin(
            {
                "true",
                "1",
                "yes",
                "passed",
            }
        ).all()
    )


def build_valuation_schema_audit(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for column in valuations.columns:
        series = valuations[
            column
        ]

        non_null = int(
            series.notna().sum()
        )

        non_empty = int(
            series
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        )

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
                "non_null_rows": non_null,
                "non_empty_rows": non_empty,
                "numeric_rows": int(
                    numeric.notna().sum()
                ),
                "is_component_flag_column": bool(
                    column.endswith(
                        "_component_modeled_flag"
                    )
                    or column.endswith(
                        "_component_primary_claim_flag"
                    )
                ),
                "is_source_value_column": bool(
                    column.endswith(
                        "_source_asset_value_score"
                    )
                ),
                "is_allocation_json_column": bool(
                    column.endswith(
                        "_candidate_allocations_json"
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_method_summary(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    return (
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
            ],
            ascending=[
                False,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )


def build_direct_candidate_rows(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    candidate_team_column = first_existing_column(
        valuations,
        [
            "candidate_beneficiary_team",
            "candidate_team",
        ],
    )

    value_column = first_existing_column(
        valuations,
        [
            "expected_total_candidate_asset_value_score",
            "expected_transferred_value_score",
        ],
    )

    if (
        not candidate_team_column
        or not value_column
    ):
        return pd.DataFrame()

    direct_mask = (
        valuations[
            candidate_team_column
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
        & pd.to_numeric(
            valuations[
                value_column
            ],
            errors="coerce",
        ).notna()
        & ~valuations[
            "valuation_method"
        ]
        .fillna("")
        .astype(str)
        .str.contains(
            "_source_allocation",
            regex=False,
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
            candidate_team_column,
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "valuation_method",
            "valuation_status",
            value_column,
            "conveyance_probability",
            "retention_probability",
            "valuation_scope_note",
        ]
        if column in valuations.columns
    ]

    output = valuations.loc[
        direct_mask,
        columns,
    ].copy()

    output = output.rename(
        columns={
            candidate_team_column: "candidate_team",
            value_column: "candidate_asset_value_score",
        }
    )

    return output.sort_values(
        [
            "candidate_team",
            "asset_key",
            "claim_id",
        ]
    ).reset_index(
        drop=True
    )


def build_component_primary_rows(
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    primary_columns = [
        column
        for column in valuations.columns
        if column.endswith(
            "_component_primary_claim_flag"
        )
    ]

    rows = []

    for primary_column in primary_columns:
        prefix = primary_column.removesuffix(
            "_component_primary_claim_flag"
        )

        source_value_column = (
            f"{prefix}_source_asset_value_score"
        )

        allocation_json_column = (
            f"{prefix}_candidate_allocations_json"
        )

        mask = (
            valuations[
                primary_column
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
        )

        for row in valuations.loc[
            mask
        ].itertuples(
            index=False
        ):
            row_dict = row._asdict()

            rows.append(
                {
                    "component_prefix": prefix,
                    "primary_flag_column": primary_column,
                    "claim_id": clean_text(
                        row_dict.get(
                            "claim_id",
                            "",
                        )
                    ),
                    "asset_key": clean_text(
                        row_dict.get(
                            "asset_key",
                            "",
                        )
                    ),
                    "valuation_method": clean_text(
                        row_dict.get(
                            "valuation_method",
                            "",
                        )
                    ),
                    "valuation_status": clean_text(
                        row_dict.get(
                            "valuation_status",
                            "",
                        )
                    ),
                    "source_asset_value_score": finite_or_zero(
                        row_dict.get(
                            source_value_column,
                            np.nan,
                        )
                    ),
                    "allocation_json_present": bool(
                        clean_text(
                            row_dict.get(
                                allocation_json_column,
                                "",
                            )
                        )
                    ),
                    "allocation_json_column": (
                        allocation_json_column
                    ),
                }
            )

    return pd.DataFrame(
        rows
    )


def normalize_candidate_right_file(
    path: Path,
    active_methods: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = normalize_columns(
        pd.read_parquet(
            path
        )
    )

    file_base, file_version = parse_versioned_file(
        path
    )

    candidate_team_column = first_existing_column(
        frame,
        [
            "candidate_team",
            "candidate_beneficiary_team",
            "team",
        ],
    )

    value_column = first_existing_column(
        frame,
        [
            "expected_candidate_right_value_score",
            "candidate_right_value_score",
            "expected_total_candidate_asset_value_score",
            "expected_value_score",
        ],
    )

    pick_count_column = first_existing_column(
        frame,
        [
            "expected_pick_count",
            "candidate_expected_pick_count",
        ],
    )

    source_assets_column = first_existing_column(
        frame,
        [
            "source_assets",
            "source_asset_key",
            "source_asset_keys",
        ],
    )

    best_method, match_score = best_method_match(
        file_base,
        active_methods,
    )

    normalized_rows = []

    if candidate_team_column and value_column:
        for row_number, row in frame.iterrows():
            source_assets = (
                parse_source_assets(
                    row.get(
                        source_assets_column,
                        "",
                    )
                )
                if source_assets_column
                else []
            )

            normalized_rows.append(
                {
                    "candidate_right_file": path.name,
                    "candidate_right_file_base": file_base,
                    "candidate_right_file_version": file_version,
                    "row_number": int(
                        row_number
                    ),
                    "candidate_team": clean_text(
                        row.get(
                            candidate_team_column,
                            "",
                        )
                    ),
                    "expected_candidate_right_value_score": (
                        finite_or_zero(
                            row.get(
                                value_column,
                                np.nan,
                            )
                        )
                    ),
                    "expected_pick_count": (
                        finite_or_zero(
                            row.get(
                                pick_count_column,
                                np.nan,
                            )
                        )
                        if pick_count_column
                        else np.nan
                    ),
                    "source_assets": "|".join(
                        source_assets
                    ),
                    "source_asset_count": len(
                        source_assets
                    ),
                    "best_matching_final_valuation_method": (
                        best_method
                    ),
                    "method_match_score": match_score,
                    "raw_row_json": json.dumps(
                        json_safe(
                            row.to_dict()
                        ),
                        sort_keys=True,
                    ),
                }
            )

    normalized = pd.DataFrame(
        normalized_rows
    )

    catalog_row = {
        "candidate_right_file": path.name,
        "candidate_right_file_base": file_base,
        "candidate_right_file_version": file_version,
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "row_count": int(
            len(
                frame
            )
        ),
        "column_count": int(
            len(
                frame.columns
            )
        ),
        "columns": "|".join(
            frame.columns
        ),
        "candidate_team_column": candidate_team_column,
        "value_column": value_column,
        "pick_count_column": pick_count_column,
        "source_assets_column": source_assets_column,
        "normalizable": bool(
            candidate_team_column
            and value_column
        ),
        "normalized_row_count": int(
            len(
                normalized
            )
        ),
        "normalized_total_value_score": (
            float(
                normalized[
                    "expected_candidate_right_value_score"
                ].sum()
            )
            if not normalized.empty
            else np.nan
        ),
        "normalized_total_expected_pick_count": (
            float(
                normalized[
                    "expected_pick_count"
                ].sum(
                    min_count=1
                )
            )
            if (
                not normalized.empty
                and "expected_pick_count"
                in normalized.columns
            )
            else np.nan
        ),
        "best_matching_final_valuation_method": best_method,
        "method_match_score": match_score,
        "probable_active_component_file": bool(
            match_score
            >= 0.35
        ),
    }

    return (
        normalized,
        catalog_row,
    )


def build_source_overlap_audit(
    normalized_rights: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    if normalized_rights.empty:
        return pd.DataFrame()

    active = normalized_rights.loc[
        normalized_rights[
            "method_match_score"
        ]
        .fillna(
            0.0
        )
        .ge(
            0.35
        )
    ].copy()

    exploded_rows = []

    for row in active.itertuples(
        index=False
    ):
        for source_asset in parse_source_assets(
            row.source_assets
        ):
            exploded_rows.append(
                {
                    "source_asset_key": source_asset,
                    "candidate_right_file": (
                        row.candidate_right_file
                    ),
                    "candidate_team": (
                        row.candidate_team
                    ),
                    "best_matching_final_valuation_method": (
                        row.best_matching_final_valuation_method
                    ),
                }
            )

    if not exploded_rows:
        return pd.DataFrame()

    exploded = pd.DataFrame(
        exploded_rows
    )

    for source_asset, group in exploded.groupby(
        "source_asset_key",
        sort=True,
    ):
        files = sorted(
            set(
                group[
                    "candidate_right_file"
                ].astype(str)
            )
        )

        methods = sorted(
            set(
                group[
                    "best_matching_final_valuation_method"
                ].astype(str)
            )
        )

        teams = sorted(
            set(
                group[
                    "candidate_team"
                ].astype(str)
            )
        )

        rows.append(
            {
                "source_asset_key": source_asset,
                "candidate_right_files": "|".join(
                    files
                ),
                "candidate_right_file_count": len(
                    files
                ),
                "matched_valuation_methods": "|".join(
                    methods
                ),
                "candidate_teams": "|".join(
                    teams
                ),
                "cross_file_overlap_flag": bool(
                    len(
                        files
                    )
                    > 1
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "cross_file_overlap_flag",
            "candidate_right_file_count",
            "source_asset_key",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_readiness_audit(
    valuations: pd.DataFrame,
    team_summary: pd.DataFrame,
    completion_audit: pd.DataFrame,
    file_catalog: pd.DataFrame,
    normalized_rights: pd.DataFrame,
    source_overlap: pd.DataFrame,
    direct_candidates: pd.DataFrame,
    component_primary_rows: pd.DataFrame,
) -> pd.DataFrame:
    completion_passed = completion_audit_passed(
        completion_audit
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

    team_summary_valid = bool(
        len(
            team_summary
        )
        == 30
        and team_summary[
            "candidate_beneficiary_team"
        ]
        .astype(str)
        .nunique()
        == 30
        and pd.to_numeric(
            team_summary[
                FINAL_VALUE_COLUMN
            ],
            errors="coerce",
        ).notna().all()
    )

    normalizable_files = int(
        file_catalog[
            "normalizable"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        )
        .sum()
    )

    probable_active_files = int(
        file_catalog[
            "probable_active_component_file"
        ]
        .fillna(
            False
        )
        .astype(
            bool
        )
        .sum()
    )

    overlap_count = (
        int(
            source_overlap[
                "cross_file_overlap_flag"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        )
        if not source_overlap.empty
        else 0
    )

    checks = [
        {
            "check_name": "canonical_completion_audit_passed",
            "observed_value": completion_passed,
            "expected_value": True,
            "passed": completion_passed,
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "all_valuation_claims_fully_valued",
            "observed_value": all_claims_valued,
            "expected_value": True,
            "passed": all_claims_valued,
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "canonical_team_summary_valid",
            "observed_value": team_summary_valid,
            "expected_value": True,
            "passed": team_summary_valid,
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "latest_candidate_right_files_found",
            "observed_value": int(
                len(
                    file_catalog
                )
            ),
            "expected_value": ">0",
            "passed": bool(
                len(
                    file_catalog
                )
                > 0
            ),
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "normalizable_candidate_right_files",
            "observed_value": normalizable_files,
            "expected_value": int(
                len(
                    file_catalog
                )
            ),
            "passed": bool(
                normalizable_files
                == len(
                    file_catalog
                )
            ),
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "probable_active_component_files",
            "observed_value": probable_active_files,
            "expected_value": "review",
            "passed": True,
            "blocking_for_inventory_build": False,
        },
        {
            "check_name": "normalized_candidate_right_rows",
            "observed_value": int(
                len(
                    normalized_rights
                )
            ),
            "expected_value": ">0",
            "passed": bool(
                len(
                    normalized_rights
                )
                > 0
            ),
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "direct_candidate_rows",
            "observed_value": int(
                len(
                    direct_candidates
                )
            ),
            "expected_value": ">0",
            "passed": bool(
                len(
                    direct_candidates
                )
                > 0
            ),
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "component_primary_rows",
            "observed_value": int(
                len(
                    component_primary_rows
                )
            ),
            "expected_value": ">0",
            "passed": bool(
                len(
                    component_primary_rows
                )
                > 0
            ),
            "blocking_for_inventory_build": True,
        },
        {
            "check_name": "cross_file_source_overlaps_requiring_resolution",
            "observed_value": overlap_count,
            "expected_value": 0,
            "passed": bool(
                overlap_count
                == 0
            ),
            "blocking_for_inventory_build": True,
        },
    ]

    return pd.DataFrame(
        checks
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
    print("FUTURE PICK OPTIMIZER INVENTORY INPUT AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        valuations,
        team_summary,
        completion_audit,
        manifest,
    ) = load_core_inputs()

    valuation_schema = build_valuation_schema_audit(
        valuations
    )

    method_summary = build_method_summary(
        valuations
    )

    direct_candidates = build_direct_candidate_rows(
        valuations
    )

    component_primary_rows = build_component_primary_rows(
        valuations
    )

    all_candidate_right_files = sorted(
        PROCESSED_DIRECTORY.glob(
            CANDIDATE_RIGHTS_PATTERN
        )
    )

    latest_candidate_right_files = (
        select_latest_candidate_right_files(
            all_candidate_right_files
        )
    )

    active_methods = sorted(
        set(
            valuations[
                "valuation_method"
            ]
            .fillna("")
            .astype(str)
        )
    )

    catalog_rows = []
    normalized_frames = []

    for path in latest_candidate_right_files:
        normalized, catalog_row = (
            normalize_candidate_right_file(
                path=path,
                active_methods=active_methods,
            )
        )

        catalog_rows.append(
            catalog_row
        )

        if not normalized.empty:
            normalized_frames.append(
                normalized
            )

    file_catalog = pd.DataFrame(
        catalog_rows
    )

    normalized_rights = (
        pd.concat(
            normalized_frames,
            ignore_index=True,
            sort=False,
        )
        if normalized_frames
        else pd.DataFrame()
    )

    source_overlap = build_source_overlap_audit(
        normalized_rights
    )

    readiness_audit = build_readiness_audit(
        valuations=valuations,
        team_summary=team_summary,
        completion_audit=completion_audit,
        file_catalog=file_catalog,
        normalized_rights=normalized_rights,
        source_overlap=source_overlap,
        direct_candidates=direct_candidates,
        component_primary_rows=component_primary_rows,
    )

    file_catalog.to_csv(
        FILE_CATALOG_PATH,
        index=False,
    )

    normalized_rights.to_parquet(
        NORMALIZED_RIGHTS_PARQUET_PATH,
        index=False,
    )

    normalized_rights.to_csv(
        NORMALIZED_RIGHTS_CSV_PATH,
        index=False,
    )

    source_overlap.to_csv(
        SOURCE_OVERLAP_AUDIT_PATH,
        index=False,
    )

    valuation_schema.to_csv(
        VALUATION_SCHEMA_AUDIT_PATH,
        index=False,
    )

    method_summary.to_csv(
        VALUATION_METHOD_SUMMARY_PATH,
        index=False,
    )

    direct_candidates.to_csv(
        DIRECT_CANDIDATE_ROWS_PATH,
        index=False,
    )

    component_primary_rows.to_csv(
        COMPONENT_PRIMARY_ROWS_PATH,
        index=False,
    )

    readiness_audit.to_csv(
        INVENTORY_READINESS_AUDIT_PATH,
        index=False,
    )

    blocking_failures = readiness_audit.loc[
        readiness_audit[
            "blocking_for_inventory_build"
        ].fillna(
            False
        ).astype(
            bool
        )
        & ~readiness_audit[
            "passed"
        ].fillna(
            False
        ).astype(
            bool
        )
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "canonical_claim_rows": int(
            len(
                valuations
            )
        ),
        "canonical_team_rows": int(
            len(
                team_summary
            )
        ),
        "all_candidate_right_files_found": int(
            len(
                all_candidate_right_files
            )
        ),
        "latest_candidate_right_files_selected": int(
            len(
                latest_candidate_right_files
            )
        ),
        "normalizable_candidate_right_files": int(
            file_catalog[
                "normalizable"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        ),
        "probable_active_component_files": int(
            file_catalog[
                "probable_active_component_file"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        ),
        "normalized_candidate_right_rows": int(
            len(
                normalized_rights
            )
        ),
        "direct_candidate_rows": int(
            len(
                direct_candidates
            )
        ),
        "component_primary_rows": int(
            len(
                component_primary_rows
            )
        ),
        "cross_file_source_overlap_rows": int(
            source_overlap[
                "cross_file_overlap_flag"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        )
        if not source_overlap.empty
        else 0,
        "automatic_inventory_build_ready": bool(
            blocking_failures.empty
        ),
        "blocking_failures": (
            blocking_failures[
                "check_name"
            ].astype(str).tolist()
        ),
        "release_manifest_rows": int(
            len(
                manifest
            )
        ),
        "output_files": {
            "candidate_rights_file_catalog": str(
                FILE_CATALOG_PATH
            ),
            "normalized_candidate_rights": str(
                NORMALIZED_RIGHTS_PARQUET_PATH
            ),
            "source_asset_overlap_audit": str(
                SOURCE_OVERLAP_AUDIT_PATH
            ),
            "valuation_schema_audit": str(
                VALUATION_SCHEMA_AUDIT_PATH
            ),
            "valuation_method_summary": str(
                VALUATION_METHOD_SUMMARY_PATH
            ),
            "direct_candidate_rows": str(
                DIRECT_CANDIDATE_ROWS_PATH
            ),
            "component_primary_rows": str(
                COMPONENT_PRIMARY_ROWS_PATH
            ),
            "inventory_readiness_audit": str(
                INVENTORY_READINESS_AUDIT_PATH
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
    print("OPTIMIZER INVENTORY INPUT AUDIT CREATED")
    print("=" * 80)
    print(
        "Canonical claim rows: "
        f"{len(valuations):,}"
    )
    print(
        "Canonical team rows: "
        f"{len(team_summary):,}"
    )
    print(
        "All candidate-right files found: "
        f"{len(all_candidate_right_files):,}"
    )
    print(
        "Latest candidate-right files selected: "
        f"{len(latest_candidate_right_files):,}"
    )
    print(
        "Normalizable candidate-right files: "
        f"{int(file_catalog['normalizable'].fillna(False).astype(bool).sum()):,}"
    )
    print(
        "Probable active component files: "
        f"{int(file_catalog['probable_active_component_file'].fillna(False).astype(bool).sum()):,}"
    )
    print(
        "Normalized candidate-right rows: "
        f"{len(normalized_rights):,}"
    )
    print(
        "Direct candidate rows: "
        f"{len(direct_candidates):,}"
    )
    print(
        "Component primary rows: "
        f"{len(component_primary_rows):,}"
    )

    overlap_count = (
        int(
            source_overlap[
                "cross_file_overlap_flag"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
            .sum()
        )
        if not source_overlap.empty
        else 0
    )

    print(
        "Cross-file source overlaps requiring resolution: "
        f"{overlap_count:,}"
    )
    print(
        "Automatic inventory build ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("INVENTORY READINESS AUDIT")
    print(
        readiness_audit.to_string(
            index=False
        )
    )
    print()

    print("LATEST CANDIDATE-RIGHTS FILE CATALOG")
    display_catalog = file_catalog[
        [
            "candidate_right_file",
            "row_count",
            "normalizable",
            "best_matching_final_valuation_method",
            "method_match_score",
            "probable_active_component_file",
        ]
    ].copy()

    display_catalog[
        "method_match_score"
    ] = pd.to_numeric(
        display_catalog[
            "method_match_score"
        ],
        errors="coerce",
    ).round(
        4
    )

    print(
        display_catalog.to_string(
            index=False
        )
    )
    print()

    print("CROSS-FILE SOURCE OVERLAPS")
    if source_overlap.empty:
        print(
            "No source assets were parsed from probable active files."
        )
    else:
        flagged = source_overlap.loc[
            source_overlap[
                "cross_file_overlap_flag"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
        ]

        if flagged.empty:
            print(
                "No cross-file source overlaps were found."
            )
        else:
            print(
                flagged.to_string(
                    index=False
                )
            )

    print()
    print("SAVED FILES")

    for path in [
        FILE_CATALOG_PATH,
        NORMALIZED_RIGHTS_PARQUET_PATH,
        NORMALIZED_RIGHTS_CSV_PATH,
        SOURCE_OVERLAP_AUDIT_PATH,
        VALUATION_SCHEMA_AUDIT_PATH,
        VALUATION_METHOD_SUMMARY_PATH,
        DIRECT_CANDIDATE_ROWS_PATH,
        COMPONENT_PRIMARY_ROWS_PATH,
        INVENTORY_READINESS_AUDIT_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()