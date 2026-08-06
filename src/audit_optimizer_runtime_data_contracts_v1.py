from __future__ import annotations

import ast
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "optimizer-runtime-data-contract-audit-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

RUNTIME_CORE_PATH_CONSTANTS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_path_constants_v1.csv"
)

RUNTIME_CORE_DATA_IO_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_data_io_v1.csv"
)

RUNTIME_CORE_FUNCTION_MAP_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_function_map_v1.csv"
)

CANONICAL_PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

TARGET_SOURCE_FILES = [
    SOURCE_DIRECTORY / "build_base_player_pool.py",
    SOURCE_DIRECTORY / "build_current_player_projection_board.py",
    SOURCE_DIRECTORY / "build_trade_salary_precheck_engine_v1.py",
    SOURCE_DIRECTORY / "build_multi_player_trade_salary_precheck_v1.py",
    SOURCE_DIRECTORY / "build_trade_basketball_fit_engine_v1.py",
    SOURCE_DIRECTORY / "build_multi_player_trade_fit_engine_v1.py",
    SOURCE_DIRECTORY / "build_trade_realism_layer_v1.py",
    SOURCE_DIRECTORY / "calibrate_trade_realism_layer_v3.py",
    SOURCE_DIRECTORY / "calibrate_multi_player_trade_realism_v2.py",
]

FILE_DISCOVERY_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_file_discovery_v1.csv"
)

DATASET_SCHEMA_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_schema_catalog_v1.csv"
)

DATASET_COLUMN_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_column_catalog_v1.csv"
)

DATASET_SAMPLE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_sample_catalog_v1.csv"
)

JOIN_KEY_CANDIDATE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_join_key_candidates_v1.csv"
)

ARTIFACT_ROLE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_artifact_role_catalog_v1.csv"
)

ORCHESTRATOR_CONTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_orchestrator_contract_v1.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_data_contract_readiness_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_data_contract_metadata_v1.json"
)


SUPPORTED_TABULAR_SUFFIXES = {
    ".csv",
    ".parquet",
}

SUPPORTED_METADATA_SUFFIXES = {
    ".json",
}

EXCLUDED_DIRECTORY_PARTS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "venv",
    ".venv",
}

MAX_CSV_SAMPLE_ROWS = 5
MAX_PARQUET_SAMPLE_ROWS = 5
MAX_JSON_SAMPLE_KEYS = 50
MAX_FILE_SIZE_BYTES = 2_000_000_000

TEAM_COLUMN_CANDIDATES = {
    "team",
    "team_abbreviation",
    "team_abbr",
    "candidate_team",
    "sending_team",
    "receiving_team",
    "team_a",
    "team_b",
    "current_team",
    "player_team",
}

PLAYER_ID_COLUMN_CANDIDATES = {
    "player_id",
    "nba_player_id",
    "person_id",
    "player_key",
}

PLAYER_NAME_COLUMN_CANDIDATES = {
    "player_name",
    "player",
    "full_name",
    "display_name",
}

PACKAGE_ID_COLUMN_CANDIDATES = {
    "package_id",
    "trade_id",
    "pair_id",
    "candidate_id",
    "recommendation_id",
}

SALARY_COLUMN_HINTS = {
    "salary",
    "outgoing_salary",
    "incoming_salary",
    "salary_2026_27",
    "current_salary",
    "cap_hit",
}

FIT_COLUMN_HINTS = {
    "fit_score",
    "basketball_fit_score",
    "mutual_fit_score",
    "team_fit_score",
}

REALISM_COLUMN_HINTS = {
    "realism_score",
    "realism_probability",
    "acceptance_probability",
    "trade_realism_score",
}

VALUE_COLUMN_HINTS = {
    "trade_value",
    "player_value",
    "surplus_value",
    "asset_value",
    "candidate_right_value_score",
    "package_value",
}

LEGALITY_COLUMN_HINTS = {
    "legal",
    "is_legal",
    "trade_legal",
    "salary_match_passed",
    "precheck_passed",
    "valid_trade",
    "tradability_status",
    "standalone_trade_asset_flag",
}

PICK_ID_COLUMN_HINTS = {
    "future_pick_right_id",
    "source_assets",
    "primary_source_asset",
}

ROLE_PATTERNS = {
    "player_pool": [
        r"base_player_pool",
        r"current_player",
        r"projection_board",
        r"player_pool",
    ],
    "salary_precheck": [
        r"salary_precheck",
        r"salary_match",
        r"trade_salary",
    ],
    "basketball_fit": [
        r"basketball_fit",
        r"multi_player_trade_fit",
        r"fit_engine",
    ],
    "trade_realism": [
        r"trade_realism",
        r"realism_layer",
        r"realism_calibration",
    ],
    "future_pick_inventory": [
        r"future_pick_optimizer_inventory",
        r"future_pick_right",
    ],
    "team_targets": [
        r"team_targets",
        r"recommendations",
        r"team_recommendation",
    ],
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def normalize_name(value: Any) -> str:
    return (
        clean_text(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
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

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def safe_read_text(path: Path) -> str:
    for encoding in (
        "utf-8",
        "utf-8-sig",
        "cp1252",
    ):
        try:
            return path.read_text(
                encoding=encoding,
            )
        except UnicodeDecodeError:
            continue

    return path.read_text(
        encoding="utf-8",
        errors="replace",
    )


def ast_unparse_safe(node: ast.AST | None) -> str:
    if node is None:
        return ""

    try:
        return ast.unparse(node)
    except Exception:
        return ""


def evaluate_path_expression(
    expression: str,
) -> list[Path]:
    text = clean_text(expression)

    if not text:
        return []

    candidates = []

    quoted_strings = re.findall(
        r"""["']([^"']+\.(?:csv|parquet|json))["']""",
        text,
        flags=re.IGNORECASE,
    )

    for value in quoted_strings:
        path = Path(value)

        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend(
                [
                    PROJECT_ROOT / path,
                    OUTPUT_DIRECTORY / path.name,
                    PROCESSED_DIRECTORY / path.name,
                ]
            )

    filename_match = re.search(
        r"""["']([^"']+)["']""",
        text,
    )

    if filename_match:
        value = filename_match.group(1)

        if Path(value).suffix.lower() in (
            SUPPORTED_TABULAR_SUFFIXES
            | SUPPORTED_METADATA_SUFFIXES
        ):
            path = Path(value)

            if path.is_absolute():
                candidates.append(path)
            else:
                candidates.extend(
                    [
                        PROJECT_ROOT / path,
                        OUTPUT_DIRECTORY / path.name,
                        PROCESSED_DIRECTORY / path.name,
                    ]
                )

    return sorted(set(candidates))


def extract_source_path_constants(
    path: Path,
) -> list[dict[str, Any]]:
    text = safe_read_text(path)
    tree = ast.parse(
        text,
        filename=str(path),
    )

    rows = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            (
                ast.Assign,
                ast.AnnAssign,
            ),
        ):
            continue

        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        else:
            targets = [node.target]
            value = node.value

        for target in targets:
            if not isinstance(target, ast.Name):
                continue

            name = target.id

            if not re.search(
                r"(?:PATH|FILE|DIRECTORY|DIR)$",
                name,
                flags=re.IGNORECASE,
            ):
                continue

            expression = ast_unparse_safe(value)

            rows.append(
                {
                    "source_file": relative_path(path),
                    "constant_name": name,
                    "line_number": int(
                        getattr(node, "lineno", 0)
                    ),
                    "value_expression": expression,
                }
            )

    return rows


def discover_referenced_files() -> pd.DataFrame:
    rows = []

    for path in TARGET_SOURCE_FILES:
        if not path.exists():
            raise FileNotFoundError(
                "Required runtime source file was not found:\n"
                f"{path}"
            )

        for row in extract_source_path_constants(path):
            expressions = evaluate_path_expression(
                row["value_expression"]
            )

            if expressions:
                for candidate in expressions:
                    rows.append(
                        {
                            **row,
                            "candidate_file_path": str(candidate),
                            "candidate_file_exists": candidate.exists(),
                            "candidate_file_suffix": (
                                candidate.suffix.lower()
                            ),
                            "discovery_method": (
                                "source_path_constant_expression"
                            ),
                        }
                    )
            else:
                rows.append(
                    {
                        **row,
                        "candidate_file_path": "",
                        "candidate_file_exists": False,
                        "candidate_file_suffix": "",
                        "discovery_method": (
                            "unresolved_source_path_constant"
                        ),
                    }
                )

    for audit_path in [
        RUNTIME_CORE_PATH_CONSTANTS_PATH,
        RUNTIME_CORE_DATA_IO_PATH,
    ]:
        if not audit_path.exists():
            continue

        frame = pd.read_csv(audit_path)

        for row in frame.to_dict(
            orient="records"
        ):
            text_values = [
                clean_text(value)
                for value in row.values()
            ]

            for text in text_values:
                for candidate in evaluate_path_expression(text):
                    rows.append(
                        {
                            "source_file": relative_path(audit_path),
                            "constant_name": clean_text(
                                row.get(
                                    "constant_name",
                                    row.get(
                                        "qualified_symbol_name",
                                        "",
                                    ),
                                )
                            ),
                            "line_number": row.get(
                                "line_number",
                                np.nan,
                            ),
                            "value_expression": text,
                            "candidate_file_path": str(candidate),
                            "candidate_file_exists": candidate.exists(),
                            "candidate_file_suffix": (
                                candidate.suffix.lower()
                            ),
                            "discovery_method": (
                                "runtime_core_audit_output"
                            ),
                        }
                    )

    for root in [
        OUTPUT_DIRECTORY,
        PROCESSED_DIRECTORY,
    ]:
        if not root.exists():
            continue

        for path in root.iterdir():
            if not path.is_file():
                continue

            if path.suffix.lower() not in (
                SUPPORTED_TABULAR_SUFFIXES
                | SUPPORTED_METADATA_SUFFIXES
            ):
                continue

            name = path.name.lower()

            if not any(
                token in name
                for token in [
                    "player",
                    "trade",
                    "salary",
                    "fit",
                    "realism",
                    "projection",
                    "roster",
                    "recommendation",
                    "future_pick_optimizer_inventory",
                ]
            ):
                continue

            rows.append(
                {
                    "source_file": relative_path(root),
                    "constant_name": "",
                    "line_number": np.nan,
                    "value_expression": path.name,
                    "candidate_file_path": str(path),
                    "candidate_file_exists": True,
                    "candidate_file_suffix": (
                        path.suffix.lower()
                    ),
                    "discovery_method": (
                        "artifact_directory_scan"
                    ),
                }
            )

    canonical_row = {
        "source_file": "canonical_future_pick_inventory",
        "constant_name": "CANONICAL_PICK_INVENTORY_PATH",
        "line_number": np.nan,
        "value_expression": str(
            CANONICAL_PICK_INVENTORY_PATH
        ),
        "candidate_file_path": str(
            CANONICAL_PICK_INVENTORY_PATH
        ),
        "candidate_file_exists": (
            CANONICAL_PICK_INVENTORY_PATH.exists()
        ),
        "candidate_file_suffix": (
            CANONICAL_PICK_INVENTORY_PATH.suffix.lower()
        ),
        "discovery_method": "required_canonical_input",
    }

    rows.append(canonical_row)

    output = pd.DataFrame(rows)

    if output.empty:
        return output

    output[
        "candidate_file_path"
    ] = output[
        "candidate_file_path"
    ].fillna("").astype(str)

    output = output.drop_duplicates(
        subset=[
            "candidate_file_path",
            "source_file",
            "constant_name",
            "discovery_method",
        ]
    )

    output[
        "candidate_file_name"
    ] = output[
        "candidate_file_path"
    ].map(
        lambda value: (
            Path(value).name
            if clean_text(value)
            else ""
        )
    )

    output[
        "file_size_bytes"
    ] = output[
        "candidate_file_path"
    ].map(
        lambda value: (
            int(Path(value).stat().st_size)
            if clean_text(value)
            and Path(value).exists()
            else np.nan
        )
    )

    return output.sort_values(
        [
            "candidate_file_exists",
            "candidate_file_name",
            "candidate_file_path",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def infer_artifact_role(
    path: Path,
    columns: list[str],
) -> str:
    searchable = (
        path.name.lower()
        + " "
        + " ".join(columns).lower()
    )

    counts = {
        role: sum(
            len(
                re.findall(
                    pattern,
                    searchable,
                    flags=re.IGNORECASE,
                )
            )
            for pattern in patterns
        )
        for role, patterns in ROLE_PATTERNS.items()
    }

    ranked = sorted(
        [
            (role, count)
            for role, count in counts.items()
            if count > 0
        ],
        key=lambda item: (
            -item[1],
            item[0],
        ),
    )

    return (
        ranked[0][0]
        if ranked
        else "other_runtime_artifact"
    )


def read_tabular_schema(
    path: Path,
) -> tuple[
    int | None,
    list[dict[str, Any]],
    pd.DataFrame,
]:
    if path.suffix.lower() == ".csv":
        header = pd.read_csv(
            path,
            nrows=0,
        )

        sample = pd.read_csv(
            path,
            nrows=MAX_CSV_SAMPLE_ROWS,
        )

        try:
            row_count = sum(
                1
                for _ in path.open(
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                )
            ) - 1

            row_count = max(
                0,
                row_count,
            )
        except OSError:
            row_count = None

        column_rows = []

        for column in header.columns:
            sample_series = (
                sample[column]
                if column in sample.columns
                else pd.Series(
                    dtype="object"
                )
            )

            column_rows.append(
                {
                    "column_name": str(column),
                    "normalized_column_name": normalize_name(
                        column
                    ),
                    "dtype": str(
                        sample_series.dtype
                    ),
                    "sample_non_null_count": int(
                        sample_series.notna().sum()
                    ),
                    "sample_unique_count": int(
                        sample_series.nunique(
                            dropna=True
                        )
                    ),
                }
            )

        return (
            row_count,
            column_rows,
            sample,
        )

    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq

            parquet_file = pq.ParquetFile(
                path
            )

            schema = parquet_file.schema_arrow
            row_count = int(
                parquet_file.metadata.num_rows
            )

            column_rows = [
                {
                    "column_name": field.name,
                    "normalized_column_name": normalize_name(
                        field.name
                    ),
                    "dtype": str(field.type),
                    "sample_non_null_count": np.nan,
                    "sample_unique_count": np.nan,
                }
                for field in schema
            ]

            sample = pd.read_parquet(
                path
            ).head(
                MAX_PARQUET_SAMPLE_ROWS
            )

            for row in column_rows:
                column = row[
                    "column_name"
                ]

                if column in sample.columns:
                    row[
                        "sample_non_null_count"
                    ] = int(
                        sample[column].notna().sum()
                    )

                    row[
                        "sample_unique_count"
                    ] = int(
                        sample[column].nunique(
                            dropna=True
                        )
                    )

            return (
                row_count,
                column_rows,
                sample,
            )
        except ImportError:
            sample = pd.read_parquet(
                path
            )

            row_count = int(
                len(sample)
            )

            column_rows = [
                {
                    "column_name": str(column),
                    "normalized_column_name": normalize_name(
                        column
                    ),
                    "dtype": str(
                        sample[column].dtype
                    ),
                    "sample_non_null_count": int(
                        sample[column]
                        .head(
                            MAX_PARQUET_SAMPLE_ROWS
                        )
                        .notna()
                        .sum()
                    ),
                    "sample_unique_count": int(
                        sample[column]
                        .head(
                            MAX_PARQUET_SAMPLE_ROWS
                        )
                        .nunique(
                            dropna=True
                        )
                    ),
                }
                for column in sample.columns
            ]

            return (
                row_count,
                column_rows,
                sample.head(
                    MAX_PARQUET_SAMPLE_ROWS
                ),
            )

    raise ValueError(
        f"Unsupported tabular file: {path}"
    )


def inspect_discovered_files(
    discovery: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    schema_rows = []
    column_rows = []
    sample_rows = []
    role_rows = []

    existing_paths = sorted(
        {
            Path(value)
            for value in discovery.loc[
                discovery[
                    "candidate_file_exists"
                ].fillna(False).astype(bool)
                & discovery[
                    "candidate_file_suffix"
                ].isin(
                    SUPPORTED_TABULAR_SUFFIXES
                ),
                "candidate_file_path",
            ]
            if clean_text(value)
        }
    )

    for index, path in enumerate(
        existing_paths,
        start=1,
    ):
        print(
            f"[{index:02d}/{len(existing_paths):02d}] "
            f"Inspecting {relative_path(path)}"
        )

        file_size = int(
            path.stat().st_size
        )

        if file_size > MAX_FILE_SIZE_BYTES:
            schema_rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(
                        path
                    ),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "file_size_bytes": file_size,
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "artifact_role": (
                        "skipped_oversized_artifact"
                    ),
                    "inspection_status": (
                        "skipped_file_too_large"
                    ),
                    "inspection_error": "",
                }
            )
            continue

        try:
            (
                row_count,
                file_column_rows,
                sample,
            ) = read_tabular_schema(path)

            columns = [
                row["column_name"]
                for row in file_column_rows
            ]

            artifact_role = infer_artifact_role(
                path,
                columns,
            )

            schema_rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(
                        path
                    ),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "file_size_bytes": file_size,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "artifact_role": artifact_role,
                    "inspection_status": "inspected",
                    "inspection_error": "",
                }
            )

            for column_row in file_column_rows:
                normalized = column_row[
                    "normalized_column_name"
                ]

                column_rows.append(
                    {
                        "file_path": str(path),
                        "relative_file_path": relative_path(
                            path
                        ),
                        "artifact_role": artifact_role,
                        **column_row,
                        "is_team_key_candidate": (
                            normalized
                            in TEAM_COLUMN_CANDIDATES
                        ),
                        "is_player_id_candidate": (
                            normalized
                            in PLAYER_ID_COLUMN_CANDIDATES
                        ),
                        "is_player_name_candidate": (
                            normalized
                            in PLAYER_NAME_COLUMN_CANDIDATES
                        ),
                        "is_package_id_candidate": (
                            normalized
                            in PACKAGE_ID_COLUMN_CANDIDATES
                        ),
                        "is_salary_column": any(
                            hint in normalized
                            for hint in SALARY_COLUMN_HINTS
                        ),
                        "is_fit_column": any(
                            hint in normalized
                            for hint in FIT_COLUMN_HINTS
                        ),
                        "is_realism_column": any(
                            hint in normalized
                            for hint in REALISM_COLUMN_HINTS
                        ),
                        "is_value_column": any(
                            hint in normalized
                            for hint in VALUE_COLUMN_HINTS
                        ),
                        "is_legality_column": any(
                            hint in normalized
                            for hint in LEGALITY_COLUMN_HINTS
                        ),
                        "is_pick_identifier_column": (
                            normalized
                            in PICK_ID_COLUMN_HINTS
                        ),
                    }
                )

            sample_payload = sample.copy()

            for column in sample_payload.columns:
                sample_payload[column] = sample_payload[
                    column
                ].map(
                    lambda value: clean_text(
                        json_safe(value)
                    )
                )

            for row_number, row in sample_payload.iterrows():
                sample_rows.append(
                    {
                        "file_path": str(path),
                        "relative_file_path": relative_path(
                            path
                        ),
                        "artifact_role": artifact_role,
                        "sample_row_number": int(
                            row_number
                        ),
                        "sample_row_json": json.dumps(
                            json_safe(
                                row.to_dict()
                            ),
                            sort_keys=True,
                        ),
                    }
                )

            role_rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(
                        path
                    ),
                    "artifact_role": artifact_role,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "team_key_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_team_key_candidate"
                            ]
                        )
                    ),
                    "player_id_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_player_id_candidate"
                            ]
                        )
                    ),
                    "package_id_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_package_id_candidate"
                            ]
                        )
                    ),
                    "salary_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_salary_column"
                            ]
                        )
                    ),
                    "fit_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_fit_column"
                            ]
                        )
                    ),
                    "realism_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_realism_column"
                            ]
                        )
                    ),
                    "value_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_value_column"
                            ]
                        )
                    ),
                    "legality_columns": "|".join(
                        sorted(
                            row[
                                "column_name"
                            ]
                            for row in column_rows
                            if row[
                                "file_path"
                            ]
                            == str(path)
                            and row[
                                "is_legality_column"
                            ]
                        )
                    ),
                }
            )
        except Exception as error:
            schema_rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(
                        path
                    ),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "file_size_bytes": file_size,
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "artifact_role": (
                        "inspection_failed"
                    ),
                    "inspection_status": "failed",
                    "inspection_error": clean_text(
                        error
                    ),
                }
            )

    return (
        pd.DataFrame(schema_rows),
        pd.DataFrame(column_rows),
        pd.DataFrame(sample_rows),
        pd.DataFrame(role_rows),
    )


def build_join_key_candidates(
    columns: pd.DataFrame,
) -> pd.DataFrame:
    if columns.empty:
        return pd.DataFrame()

    key_columns = columns.loc[
        columns[
            [
                "is_team_key_candidate",
                "is_player_id_candidate",
                "is_player_name_candidate",
                "is_package_id_candidate",
                "is_pick_identifier_column",
            ]
        ].any(axis=1)
    ].copy()

    rows = []

    for normalized_column, group in key_columns.groupby(
        "normalized_column_name",
        sort=True,
    ):
        files = sorted(
            set(
                group[
                    "relative_file_path"
                ]
            )
        )

        roles = sorted(
            set(
                group[
                    "artifact_role"
                ]
            )
        )

        rows.append(
            {
                "normalized_column_name": (
                    normalized_column
                ),
                "file_count": len(files),
                "files": "|".join(files),
                "artifact_roles": "|".join(roles),
                "is_cross_artifact_join_candidate": (
                    len(files) >= 2
                ),
                "is_team_key_candidate": bool(
                    group[
                        "is_team_key_candidate"
                    ].any()
                ),
                "is_player_id_candidate": bool(
                    group[
                        "is_player_id_candidate"
                    ].any()
                ),
                "is_player_name_candidate": bool(
                    group[
                        "is_player_name_candidate"
                    ].any()
                ),
                "is_package_id_candidate": bool(
                    group[
                        "is_package_id_candidate"
                    ].any()
                ),
                "is_pick_identifier_column": bool(
                    group[
                        "is_pick_identifier_column"
                    ].any()
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        [
            "is_cross_artifact_join_candidate",
            "file_count",
            "normalized_column_name",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def choose_artifact(
    roles: pd.DataFrame,
    role: str,
) -> pd.Series | None:
    candidates = roles.loc[
        roles[
            "artifact_role"
        ].eq(role)
    ].copy()

    if candidates.empty:
        return None

    candidates[
        "row_count_numeric"
    ] = pd.to_numeric(
        candidates[
            "row_count"
        ],
        errors="coerce",
    ).fillna(-1)

    return candidates.sort_values(
        [
            "row_count_numeric",
            "column_count",
            "relative_file_path",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).iloc[0]


def build_orchestrator_contract(
    roles: pd.DataFrame,
) -> pd.DataFrame:
    steps = [
        (
            1,
            "load_player_assets",
            "player_pool",
            "Player-level candidate inventory and projections.",
        ),
        (
            2,
            "load_future_pick_assets",
            "future_pick_inventory",
            "Canonical standalone future-pick rights and accounting metadata.",
        ),
        (
            3,
            "generate_player_trade_candidates",
            "salary_precheck",
            "Existing one-for-one and multi-player package candidates.",
        ),
        (
            4,
            "attach_pick_candidates",
            "future_pick_inventory",
            "Eligible pick rights joined by candidate_team.",
        ),
        (
            5,
            "calculate_asset_value",
            "future_pick_inventory",
            "Player value plus candidate_right_value_score.",
        ),
        (
            6,
            "run_salary_validation",
            "salary_precheck",
            "Pick rights contribute zero salary.",
        ),
        (
            7,
            "run_basketball_fit_scoring",
            "basketball_fit",
            "Existing player basketball-fit features.",
        ),
        (
            8,
            "run_trade_realism_scoring",
            "trade_realism",
            "Existing realism model plus pick package features.",
        ),
        (
            9,
            "run_pick_legality_validation",
            "future_pick_inventory",
            "Standalone flag plus trade-date ownership, Stepien, frozen-pick, and encumbrance rules.",
        ),
        (
            10,
            "rank_legal_trade_packages",
            "team_targets",
            "Final legal package ranking and team recommendations.",
        ),
    ]

    rows = []

    for (
        order,
        stage,
        preferred_role,
        description,
    ) in steps:
        artifact = choose_artifact(
            roles,
            preferred_role,
        )

        rows.append(
            {
                "execution_order": order,
                "stage_name": stage,
                "preferred_artifact_role": preferred_role,
                "selected_artifact_file": (
                    artifact[
                        "relative_file_path"
                    ]
                    if artifact is not None
                    else ""
                ),
                "selected_artifact_row_count": (
                    artifact[
                        "row_count"
                    ]
                    if artifact is not None
                    else np.nan
                ),
                "selected_team_key_columns": (
                    artifact[
                        "team_key_columns"
                    ]
                    if artifact is not None
                    else ""
                ),
                "selected_player_id_columns": (
                    artifact[
                        "player_id_columns"
                    ]
                    if artifact is not None
                    else ""
                ),
                "selected_package_id_columns": (
                    artifact[
                        "package_id_columns"
                    ]
                    if artifact is not None
                    else ""
                ),
                "stage_description": description,
                "artifact_found": artifact is not None,
            }
        )

    return pd.DataFrame(rows)


def build_readiness(
    schemas: pd.DataFrame,
    columns: pd.DataFrame,
    roles: pd.DataFrame,
    joins: pd.DataFrame,
    contract: pd.DataFrame,
) -> pd.DataFrame:
    inspected = schemas.loc[
        schemas[
            "inspection_status"
        ].eq("inspected")
    ]

    failed = schemas.loc[
        schemas[
            "inspection_status"
        ].eq("failed")
    ]

    role_set = set(
        roles[
            "artifact_role"
        ]
    )

    player_key_found = bool(
        columns[
            "is_player_id_candidate"
        ].any()
        or columns[
            "is_player_name_candidate"
        ].any()
    ) if not columns.empty else False

    team_key_found = bool(
        columns[
            "is_team_key_candidate"
        ].any()
    ) if not columns.empty else False

    package_key_found = bool(
        columns[
            "is_package_id_candidate"
        ].any()
    ) if not columns.empty else False

    pick_value_found = bool(
        columns[
            "normalized_column_name"
        ].eq(
            "candidate_right_value_score"
        ).any()
    ) if not columns.empty else False

    salary_output_found = bool(
        columns[
            "is_salary_column"
        ].any()
    ) if not columns.empty else False

    fit_output_found = bool(
        columns[
            "is_fit_column"
        ].any()
    ) if not columns.empty else False

    realism_output_found = bool(
        columns[
            "is_realism_column"
        ].any()
    ) if not columns.empty else False

    legality_output_found = bool(
        columns[
            "is_legality_column"
        ].any()
    ) if not columns.empty else False

    checks = [
        {
            "check_name": "runtime_artifacts_inspected",
            "observed_value": len(inspected),
            "expected_value": ">0",
            "passed": len(inspected) > 0,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "artifact_inspection_failures",
            "observed_value": len(failed),
            "expected_value": 0,
            "passed": len(failed) == 0,
            "blocking_for_orchestrator": False,
        },
        {
            "check_name": "player_artifact_found",
            "observed_value": (
                "player_pool" in role_set
            ),
            "expected_value": True,
            "passed": "player_pool" in role_set,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "salary_precheck_artifact_found",
            "observed_value": (
                "salary_precheck" in role_set
            ),
            "expected_value": True,
            "passed": "salary_precheck" in role_set,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "basketball_fit_artifact_found",
            "observed_value": (
                "basketball_fit" in role_set
            ),
            "expected_value": True,
            "passed": "basketball_fit" in role_set,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "trade_realism_artifact_found",
            "observed_value": (
                "trade_realism" in role_set
            ),
            "expected_value": True,
            "passed": "trade_realism" in role_set,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "future_pick_inventory_found",
            "observed_value": (
                "future_pick_inventory"
                in role_set
            ),
            "expected_value": True,
            "passed": (
                "future_pick_inventory"
                in role_set
            ),
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "team_join_key_found",
            "observed_value": team_key_found,
            "expected_value": True,
            "passed": team_key_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "player_join_key_found",
            "observed_value": player_key_found,
            "expected_value": True,
            "passed": player_key_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "package_join_key_found",
            "observed_value": package_key_found,
            "expected_value": True,
            "passed": package_key_found,
            "blocking_for_orchestrator": False,
        },
        {
            "check_name": "pick_value_column_found",
            "observed_value": pick_value_found,
            "expected_value": True,
            "passed": pick_value_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "salary_output_columns_found",
            "observed_value": salary_output_found,
            "expected_value": True,
            "passed": salary_output_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "fit_output_columns_found",
            "observed_value": fit_output_found,
            "expected_value": True,
            "passed": fit_output_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "realism_output_columns_found",
            "observed_value": realism_output_found,
            "expected_value": True,
            "passed": realism_output_found,
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "legality_output_columns_found",
            "observed_value": legality_output_found,
            "expected_value": True,
            "passed": legality_output_found,
            "blocking_for_orchestrator": False,
        },
        {
            "check_name": "cross_artifact_join_candidate_found",
            "observed_value": int(
                joins[
                    "is_cross_artifact_join_candidate"
                ].sum()
            ) if not joins.empty else 0,
            "expected_value": ">0",
            "passed": bool(
                not joins.empty
                and joins[
                    "is_cross_artifact_join_candidate"
                ].any()
            ),
            "blocking_for_orchestrator": True,
        },
        {
            "check_name": "orchestrator_contract_stages_resolved",
            "observed_value": int(
                contract[
                    "artifact_found"
                ].sum()
            ),
            "expected_value": int(
                len(contract)
            ),
            "passed": bool(
                contract[
                    "artifact_found"
                ].all()
            ),
            "blocking_for_orchestrator": False,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("OPTIMIZER RUNTIME DATA-CONTRACT AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    discovery = discover_referenced_files()

    (
        schemas,
        columns,
        samples,
        roles,
    ) = inspect_discovered_files(
        discovery
    )

    joins = build_join_key_candidates(
        columns
    )

    contract = build_orchestrator_contract(
        roles
    )

    readiness = build_readiness(
        schemas=schemas,
        columns=columns,
        roles=roles,
        joins=joins,
        contract=contract,
    )

    discovery.to_csv(
        FILE_DISCOVERY_CATALOG_PATH,
        index=False,
    )

    schemas.to_csv(
        DATASET_SCHEMA_CATALOG_PATH,
        index=False,
    )

    columns.to_csv(
        DATASET_COLUMN_CATALOG_PATH,
        index=False,
    )

    samples.to_csv(
        DATASET_SAMPLE_CATALOG_PATH,
        index=False,
    )

    joins.to_csv(
        JOIN_KEY_CANDIDATE_PATH,
        index=False,
    )

    roles.to_csv(
        ARTIFACT_ROLE_CATALOG_PATH,
        index=False,
    )

    contract.to_csv(
        ORCHESTRATOR_CONTRACT_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    blocking_failures = readiness.loc[
        readiness[
            "blocking_for_orchestrator"
        ]
        & ~readiness[
            "passed"
        ]
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "discovered_file_references": int(
            len(discovery)
        ),
        "existing_tabular_artifacts_inspected": int(
            schemas[
                "inspection_status"
            ].eq("inspected").sum()
        ),
        "inspection_failures": int(
            schemas[
                "inspection_status"
            ].eq("failed").sum()
        ),
        "dataset_columns_cataloged": int(
            len(columns)
        ),
        "sample_rows_cataloged": int(
            len(samples)
        ),
        "join_key_candidates": int(
            len(joins)
        ),
        "cross_artifact_join_key_candidates": int(
            joins[
                "is_cross_artifact_join_candidate"
            ].sum()
        ) if not joins.empty else 0,
        "artifact_roles_found": sorted(
            set(
                roles[
                    "artifact_role"
                ]
            )
        ),
        "orchestrator_contract_stages": int(
            len(contract)
        ),
        "readiness_checks": int(
            len(readiness)
        ),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "blocking_failures": int(
            len(blocking_failures)
        ),
        "orchestrator_contract_ready": bool(
            blocking_failures.empty
        ),
        "output_files": {
            "file_discovery": str(
                FILE_DISCOVERY_CATALOG_PATH
            ),
            "schema_catalog": str(
                DATASET_SCHEMA_CATALOG_PATH
            ),
            "column_catalog": str(
                DATASET_COLUMN_CATALOG_PATH
            ),
            "sample_catalog": str(
                DATASET_SAMPLE_CATALOG_PATH
            ),
            "join_key_candidates": str(
                JOIN_KEY_CANDIDATE_PATH
            ),
            "artifact_roles": str(
                ARTIFACT_ROLE_CATALOG_PATH
            ),
            "orchestrator_contract": str(
                ORCHESTRATOR_CONTRACT_PATH
            ),
            "readiness": str(
                READINESS_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print()
    print("=" * 80)
    print("OPTIMIZER RUNTIME DATA-CONTRACT AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Discovered file references: "
        f"{len(discovery):,}"
    )
    print(
        "Tabular artifacts inspected: "
        f"{int(schemas['inspection_status'].eq('inspected').sum()):,}"
    )
    print(
        "Inspection failures: "
        f"{int(schemas['inspection_status'].eq('failed').sum()):,}"
    )
    print(
        "Dataset columns cataloged: "
        f"{len(columns):,}"
    )
    print(
        "Cross-artifact join candidates: "
        f"{int(joins['is_cross_artifact_join_candidate'].sum()) if not joins.empty else 0:,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Blocking failures: "
        f"{len(blocking_failures):,}"
    )
    print(
        "Orchestrator contract ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("ARTIFACT ROLE CATALOG")

    if roles.empty:
        print(
            "No runtime artifacts were classified."
        )
    else:
        display_roles = roles.sort_values(
            [
                "artifact_role",
                "row_count",
                "relative_file_path",
            ],
            ascending=[
                True,
                False,
                True,
            ],
        )

        print(
            display_roles[
                [
                    "artifact_role",
                    "relative_file_path",
                    "row_count",
                    "column_count",
                    "team_key_columns",
                    "player_id_columns",
                    "package_id_columns",
                    "salary_columns",
                    "fit_columns",
                    "realism_columns",
                    "value_columns",
                    "legality_columns",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("CROSS-ARTIFACT JOIN KEY CANDIDATES")

    if joins.empty:
        print(
            "No join-key candidates were found."
        )
    else:
        print(
            joins.loc[
                joins[
                    "is_cross_artifact_join_candidate"
                ]
            ].head(
                30
            ).to_string(
                index=False
            )
        )

    print()
    print("ORCHESTRATOR CONTRACT")
    print(
        contract.to_string(
            index=False
        )
    )

    print()
    print("READINESS")
    print(
        readiness.to_string(
            index=False
        )
    )

    print()
    print("SAVED FILES")

    for path in [
        FILE_DISCOVERY_CATALOG_PATH,
        DATASET_SCHEMA_CATALOG_PATH,
        DATASET_COLUMN_CATALOG_PATH,
        DATASET_SAMPLE_CATALOG_PATH,
        JOIN_KEY_CANDIDATE_PATH,
        ARTIFACT_ROLE_CATALOG_PATH,
        ORCHESTRATOR_CONTRACT_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()