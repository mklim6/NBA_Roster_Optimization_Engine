from __future__ import annotations

import ast
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "optimizer-trade-interface-focused-audit-v2-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

V1_FILE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_file_catalog_v1.csv"
)

V1_SYMBOL_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_symbol_catalog_v1.csv"
)

V1_IMPORT_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_import_edges_v1.csv"
)

V1_CALL_EDGES_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_call_edges_v1.csv"
)

CANONICAL_PICK_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

PRODUCTION_FILE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_production_files_v2.csv"
)

PRODUCTION_SYMBOL_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_production_symbols_v2.csv"
)

FUNCTION_IO_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_function_io_v2.csv"
)

PRODUCTION_IMPORT_GRAPH_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_production_import_graph_v2.csv"
)

PRODUCTION_CALL_GRAPH_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_production_call_graph_v2.csv"
)

DATASET_PATH_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_dataset_paths_v2.csv"
)

COLUMN_USAGE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_column_usage_v2.csv"
)

INTEGRATION_PLAN_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_integration_plan_v2.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_focused_readiness_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_focused_audit_metadata_v2.json"
)


EXCLUDED_FILE_PREFIXES = (
    "audit_",
    "diagnose_",
    "value_",
    "validate_",
    "finalize_",
    "extract_future_draft_pick_",
    "build_future_pick_optimizer_inventory_",
)

EXCLUDED_FILE_SUBSTRINGS = (
    "_component_",
    "future_pick_residual",
    "future_pick_valuation",
    "draft_pick_probability",
    "pick_simulation",
)

PRODUCTION_NAME_HINTS = (
    "trade",
    "optimizer",
    "roster",
    "salary",
    "player",
    "package",
    "candidate",
    "score",
    "fit",
    "realism",
    "legality",
)

FILE_ROLE_PATTERNS = {
    "salary_engine": [
        r"salary",
        r"incoming_salary",
        r"outgoing_salary",
        r"trade_exception",
        r"apron",
    ],
    "candidate_generator": [
        r"candidate",
        r"combination",
        r"permutation",
        r"enumerate",
        r"generate",
        r"search_space",
    ],
    "trade_package_builder": [
        r"trade_package",
        r"package_builder",
        r"build_package",
        r"construct_package",
        r"players_out",
        r"players_in",
        r"assets_out",
        r"assets_in",
    ],
    "trade_scorer": [
        r"trade_score",
        r"package_score",
        r"objective",
        r"utility",
        r"fitness",
        r"rank_trade",
        r"value_balance",
    ],
    "legality_engine": [
        r"legal",
        r"cba",
        r"stepien",
        r"frozen_pick",
        r"encumber",
        r"ownership",
        r"valid_trade",
    ],
    "player_asset_loader": [
        r"player_asset",
        r"player_value",
        r"roster",
        r"contract",
        r"salary",
    ],
    "pick_asset_loader": [
        r"future_pick",
        r"pick_asset",
        r"draft_pick",
        r"future_pick_right_id",
        r"candidate_right_value_score",
    ],
    "orchestrator": [
        r"main\(",
        r"run_optimizer",
        r"optimize",
        r"build_.*engine",
        r"pipeline",
    ],
}

FUNCTION_ROLE_PATTERNS = {
    "load_data": [
        r"^load_",
        r"^read_",
        r"read_csv",
        r"read_parquet",
    ],
    "candidate_generation": [
        r"candidate",
        r"generate",
        r"enumerate",
        r"combination",
        r"permutation",
    ],
    "package_construction": [
        r"package",
        r"trade",
        r"asset",
        r"players_out",
        r"players_in",
    ],
    "salary_validation": [
        r"salary",
        r"incoming",
        r"outgoing",
        r"apron",
        r"exception",
    ],
    "legality_validation": [
        r"legal",
        r"valid",
        r"cba",
        r"stepien",
        r"ownership",
        r"encumber",
    ],
    "scoring": [
        r"score",
        r"objective",
        r"utility",
        r"fitness",
        r"rank",
        r"value",
    ],
    "output_writer": [
        r"write",
        r"save",
        r"to_csv",
        r"to_parquet",
        r"json.dump",
    ],
    "orchestration": [
        r"^main$",
        r"^run_",
        r"pipeline",
        r"engine",
        r"optimize",
    ],
}

PATH_CALL_NAMES = {
    "read_csv",
    "read_parquet",
    "to_csv",
    "to_parquet",
    "open",
    "read_text",
    "write_text",
}

CANONICAL_PICK_COLUMNS = {
    "future_pick_right_id",
    "candidate_team",
    "right_display_name",
    "right_origin",
    "right_structure",
    "source_assets",
    "source_asset_count",
    "primary_source_asset",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "originating_teams",
    "expected_pick_count",
    "candidate_right_value_score",
    "standalone_trade_asset_flag",
    "tradability_status",
    "inventory_release",
    "inventory_release_version",
}

PLAYER_ASSET_COLUMN_HINTS = {
    "player_id",
    "player_name",
    "team",
    "salary",
    "contract",
    "player_value",
    "surplus_value",
    "fit_score",
    "trade_value",
}

TRADE_PACKAGE_COLUMN_HINTS = {
    "sending_team",
    "receiving_team",
    "team_a",
    "team_b",
    "players_out",
    "players_in",
    "assets_out",
    "assets_in",
    "outgoing_salary",
    "incoming_salary",
    "package_value",
    "trade_score",
}

VALUE_TOLERANCE = 1e-9


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output.columns = [
        clean_text(column).lower().replace(" ", "_")
        for column in output.columns
    ]
    return output


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)

    if isinstance(value, float):
        return None if math.isnan(value) else value

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


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    return path.read_text(
        encoding="utf-8",
        errors="replace",
    )


def load_v1_outputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    paths = [
        V1_FILE_CATALOG_PATH,
        V1_SYMBOL_CATALOG_PATH,
        V1_IMPORT_EDGES_PATH,
        V1_CALL_EDGES_PATH,
    ]

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required V1 audit output is missing:\n"
                f"{path}"
            )

    return (
        normalize_columns(pd.read_csv(V1_FILE_CATALOG_PATH)),
        normalize_columns(pd.read_csv(V1_SYMBOL_CATALOG_PATH)),
        normalize_columns(pd.read_csv(V1_IMPORT_EDGES_PATH)),
        normalize_columns(pd.read_csv(V1_CALL_EDGES_PATH)),
    )


def is_excluded_file(file_path: str) -> bool:
    name = Path(file_path).name.lower()

    if name.startswith(EXCLUDED_FILE_PREFIXES):
        return True

    if any(
        substring in name
        for substring in EXCLUDED_FILE_SUBSTRINGS
    ):
        return True

    return False


def production_name_score(file_path: str) -> int:
    name = Path(file_path).stem.lower()

    return sum(
        1
        for hint in PRODUCTION_NAME_HINTS
        if hint in name
    )


def count_patterns(
    text: str,
    patterns: list[str],
) -> int:
    return sum(
        len(re.findall(pattern, text, flags=re.IGNORECASE))
        for pattern in patterns
    )


def infer_file_roles(text: str) -> dict[str, int]:
    return {
        role: count_patterns(text, patterns)
        for role, patterns in FILE_ROLE_PATTERNS.items()
    }


def infer_function_roles(
    name: str,
    source: str,
) -> dict[str, int]:
    searchable = f"{name}\n{source}"

    return {
        role: count_patterns(
            searchable,
            patterns,
        )
        for role, patterns in FUNCTION_ROLE_PATTERNS.items()
    }


def role_string(role_counts: dict[str, int]) -> str:
    ranked = sorted(
        [
            (role, count)
            for role, count in role_counts.items()
            if count > 0
        ],
        key=lambda item: (
            -item[1],
            item[0],
        ),
    )

    return "|".join(
        role
        for role, _ in ranked
    )


def ast_unparse_safe(node: ast.AST | None) -> str:
    if node is None:
        return ""

    try:
        return ast.unparse(node)
    except Exception:
        return ""


def literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(
        node.value,
        str,
    ):
        return node.value

    if isinstance(node, ast.JoinedStr):
        parts = []

        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append("{expr}")

        return "".join(parts)

    return ""


def extract_column_references(
    node: ast.AST,
) -> set[str]:
    columns = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Subscript):
            slice_node = child.slice

            if isinstance(slice_node, ast.Constant) and isinstance(
                slice_node.value,
                str,
            ):
                columns.add(slice_node.value)

        if isinstance(child, ast.Call):
            function_name = ast_unparse_safe(child.func)

            if function_name.endswith(".get") and child.args:
                value = literal_string(child.args[0])

                if value:
                    columns.add(value)

    return columns


def extract_path_operations(
    node: ast.AST,
) -> list[dict[str, Any]]:
    rows = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        expression = ast_unparse_safe(child.func)
        base_name = expression.split(".")[-1]

        if base_name not in PATH_CALL_NAMES:
            continue

        path_expression = ""

        if child.args:
            path_expression = ast_unparse_safe(child.args[0])

        rows.append(
            {
                "operation": base_name,
                "call_expression": expression,
                "path_expression": path_expression,
                "line_number": int(
                    getattr(child, "lineno", 0)
                ),
            }
        )

    return rows


def extract_called_names(
    node: ast.AST,
) -> list[str]:
    names = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        expression = ast_unparse_safe(child.func)

        if expression:
            names.append(expression)

    return sorted(set(names))


def function_arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    arguments = []

    for argument in (
        list(node.args.posonlyargs)
        + list(node.args.args)
    ):
        arguments.append(argument.arg)

    if node.args.vararg is not None:
        arguments.append("*" + node.args.vararg.arg)

    for argument in node.args.kwonlyargs:
        arguments.append(argument.arg)

    if node.args.kwarg is not None:
        arguments.append("**" + node.args.kwarg.arg)

    return arguments


def function_return_annotation(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    return ast_unparse_safe(node.returns)


def scan_production_file(
    path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    text = read_text(path)
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))

    file_roles = infer_file_roles(text)

    file_row = {
        "file_path": relative_path(path),
        "file_name": path.name,
        "line_count": len(lines),
        "file_size_bytes": int(path.stat().st_size),
        "production_name_score": production_name_score(
            relative_path(path)
        ),
        "file_roles": role_string(file_roles),
        "file_role_score": int(sum(file_roles.values())),
        **{
            f"{role}_references": count
            for role, count in file_roles.items()
        },
    }

    function_rows = []
    io_rows = []
    path_rows = []

    class FunctionScanner(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(
            self,
            node: ast.ClassDef,
        ) -> None:
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(
            self,
            node: ast.FunctionDef,
        ) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            self._visit_function(node)

        def _visit_function(
            self,
            node: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> None:
            start_line = int(getattr(node, "lineno", 1))
            end_line = int(
                getattr(node, "end_lineno", start_line)
            )

            source = "\n".join(
                lines[
                    max(0, start_line - 1):end_line
                ]
            )

            roles = infer_function_roles(
                node.name,
                source,
            )

            qualified_name = ".".join(
                [
                    *self.class_stack,
                    node.name,
                ]
            )

            columns = sorted(
                extract_column_references(node)
            )

            called_names = extract_called_names(node)
            operations = extract_path_operations(node)

            docstring = clean_text(
                ast.get_docstring(node)
            )

            function_rows.append(
                {
                    "file_path": relative_path(path),
                    "qualified_symbol_name": qualified_name,
                    "function_name": node.name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "line_count": end_line - start_line + 1,
                    "arguments": "|".join(
                        function_arguments(node)
                    ),
                    "return_annotation": function_return_annotation(
                        node
                    ),
                    "docstring": docstring,
                    "function_roles": role_string(roles),
                    "function_role_score": int(
                        sum(roles.values())
                    ),
                    "referenced_column_count": len(columns),
                    "referenced_columns": "|".join(columns),
                    "called_function_count": len(called_names),
                    "called_functions": "|".join(called_names),
                    **{
                        f"{role}_references": count
                        for role, count in roles.items()
                    },
                }
            )

            for operation in operations:
                path_rows.append(
                    {
                        "file_path": relative_path(path),
                        "qualified_symbol_name": qualified_name,
                        **operation,
                    }
                )

            io_rows.append(
                {
                    "file_path": relative_path(path),
                    "qualified_symbol_name": qualified_name,
                    "read_operations": "|".join(
                        sorted(
                            {
                                operation["operation"]
                                for operation in operations
                                if operation["operation"]
                                in {
                                    "read_csv",
                                    "read_parquet",
                                    "read_text",
                                    "open",
                                }
                            }
                        )
                    ),
                    "write_operations": "|".join(
                        sorted(
                            {
                                operation["operation"]
                                for operation in operations
                                if operation["operation"]
                                in {
                                    "to_csv",
                                    "to_parquet",
                                    "write_text",
                                    "open",
                                }
                            }
                        )
                    ),
                    "path_expressions": "|".join(
                        sorted(
                            {
                                clean_text(
                                    operation["path_expression"]
                                )
                                for operation in operations
                                if clean_text(
                                    operation["path_expression"]
                                )
                            }
                        )
                    ),
                    "referenced_columns": "|".join(columns),
                }
            )

            self.generic_visit(node)

    FunctionScanner().visit(tree)

    return (
        file_row,
        function_rows,
        io_rows,
        path_rows,
    )


def select_production_files(
    v1_file_catalog: pd.DataFrame,
) -> list[Path]:
    candidates = []

    for row in v1_file_catalog.itertuples(index=False):
        file_path = clean_text(row.file_path)

        if not file_path.lower().startswith("src"):
            continue

        if is_excluded_file(file_path):
            continue

        name_score = production_name_score(file_path)

        role_score = (
            float(
                getattr(
                    row,
                    "package_construction_references",
                    0,
                )
            )
            + float(
                getattr(
                    row,
                    "candidate_generation_references",
                    0,
                )
            )
            + float(
                getattr(
                    row,
                    "objective_scoring_references",
                    0,
                )
            )
            + float(
                getattr(
                    row,
                    "salary_matching_references",
                    0,
                )
            )
            + float(
                getattr(
                    row,
                    "cba_legality_references",
                    0,
                )
            )
            + float(
                getattr(
                    row,
                    "player_asset_model_references",
                    0,
                )
            )
        )

        if name_score <= 0 and role_score <= 0:
            continue

        path = PROJECT_ROOT / file_path

        if path.exists() and path.suffix.lower() == ".py":
            candidates.append(path)

    return sorted(set(candidates))


def build_production_import_graph(
    imports: pd.DataFrame,
    production_files: set[str],
) -> pd.DataFrame:
    if imports.empty:
        return pd.DataFrame()

    output = imports.loc[
        imports[
            "file_path"
        ]
        .fillna("")
        .astype(str)
        .isin(production_files)
    ].copy()

    if "resolved_project_file" in output.columns:
        output[
            "target_is_production_file"
        ] = (
            output[
                "resolved_project_file"
            ]
            .fillna("")
            .astype(str)
            .isin(production_files)
        )
    else:
        output[
            "target_is_production_file"
        ] = False

    return output.sort_values(
        [
            "target_is_production_file",
            "file_path",
            "line_number",
        ],
        ascending=[
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_production_call_graph(
    calls: pd.DataFrame,
    production_files: set[str],
) -> pd.DataFrame:
    if calls.empty:
        return pd.DataFrame()

    output = calls.loc[
        calls[
            "file_path"
        ]
        .fillna("")
        .astype(str)
        .isin(production_files)
    ].copy()

    if "resolved_target_file" in output.columns:
        output[
            "target_is_production_file"
        ] = (
            output[
                "resolved_target_file"
            ]
            .fillna("")
            .astype(str)
            .isin(production_files)
        )
    else:
        output[
            "target_is_production_file"
        ] = False

    return output.sort_values(
        [
            "target_is_production_file",
            "resolution_status",
            "file_path",
            "line_number",
        ],
        ascending=[
            False,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_column_usage(
    function_catalog: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for row in function_catalog.itertuples(index=False):
        columns = [
            column
            for column in clean_text(
                row.referenced_columns
            ).split("|")
            if column
        ]

        for column in columns:
            rows.append(
                {
                    "file_path": row.file_path,
                    "qualified_symbol_name": (
                        row.qualified_symbol_name
                    ),
                    "column_name": column,
                    "is_canonical_pick_column": bool(
                        column in CANONICAL_PICK_COLUMNS
                    ),
                    "is_player_asset_hint": bool(
                        column in PLAYER_ASSET_COLUMN_HINTS
                    ),
                    "is_trade_package_hint": bool(
                        column in TRADE_PACKAGE_COLUMN_HINTS
                    ),
                }
            )

    output = pd.DataFrame(rows)

    if output.empty:
        return output

    return output.drop_duplicates().sort_values(
        [
            "is_canonical_pick_column",
            "is_trade_package_hint",
            "is_player_asset_hint",
            "column_name",
            "file_path",
        ],
        ascending=[
            False,
            False,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def integration_role(
    row: pd.Series,
) -> str:
    roles = set(
        clean_text(
            row.get(
                "function_roles",
                "",
            )
        ).split("|")
    )

    name = clean_text(
        row.get(
            "function_name",
            "",
        )
    ).lower()

    if (
        "load_data" in roles
        and (
            "asset" in name
            or "player" in name
            or "roster" in name
            or "load" in name
        )
    ):
        return "pick_inventory_loader"

    if "candidate_generation" in roles:
        return "pick_candidate_pool_injection"

    if "package_construction" in roles:
        return "mixed_player_pick_package_construction"

    if "scoring" in roles:
        return "pick_value_scoring"

    if "salary_validation" in roles:
        return "salary_validation_boundary"

    if "legality_validation" in roles:
        return "pick_legality_filter"

    if "orchestration" in roles:
        return "optimizer_orchestration_entrypoint"

    return "supporting_function"


def build_integration_plan(
    production_functions: pd.DataFrame,
    io_catalog: pd.DataFrame,
    column_usage: pd.DataFrame,
) -> pd.DataFrame:
    if production_functions.empty:
        return pd.DataFrame()

    output = production_functions.copy()

    output[
        "integration_role"
    ] = output.apply(
        integration_role,
        axis=1,
    )

    io_lookup = (
        io_catalog.set_index(
            [
                "file_path",
                "qualified_symbol_name",
            ]
        )
        if not io_catalog.empty
        else None
    )

    read_operations = []
    write_operations = []
    path_expressions = []

    for row in output.itertuples(index=False):
        key = (
            row.file_path,
            row.qualified_symbol_name,
        )

        if (
            io_lookup is not None
            and key in io_lookup.index
        ):
            io_row = io_lookup.loc[key]

            if isinstance(io_row, pd.DataFrame):
                io_row = io_row.iloc[0]

            read_operations.append(
                clean_text(io_row.read_operations)
            )
            write_operations.append(
                clean_text(io_row.write_operations)
            )
            path_expressions.append(
                clean_text(io_row.path_expressions)
            )
        else:
            read_operations.append("")
            write_operations.append("")
            path_expressions.append("")

    output[
        "read_operations"
    ] = read_operations

    output[
        "write_operations"
    ] = write_operations

    output[
        "path_expressions"
    ] = path_expressions

    pick_usage_counts = (
        column_usage.loc[
            column_usage[
                "is_canonical_pick_column"
            ]
        ]
        .groupby(
            [
                "file_path",
                "qualified_symbol_name",
            ]
        )
        .size()
        .to_dict()
        if not column_usage.empty
        else {}
    )

    player_usage_counts = (
        column_usage.loc[
            column_usage[
                "is_player_asset_hint"
            ]
        ]
        .groupby(
            [
                "file_path",
                "qualified_symbol_name",
            ]
        )
        .size()
        .to_dict()
        if not column_usage.empty
        else {}
    )

    trade_usage_counts = (
        column_usage.loc[
            column_usage[
                "is_trade_package_hint"
            ]
        ]
        .groupby(
            [
                "file_path",
                "qualified_symbol_name",
            ]
        )
        .size()
        .to_dict()
        if not column_usage.empty
        else {}
    )

    output[
        "canonical_pick_columns_used"
    ] = [
        int(
            pick_usage_counts.get(
                (
                    row.file_path,
                    row.qualified_symbol_name,
                ),
                0,
            )
        )
        for row in output.itertuples(index=False)
    ]

    output[
        "player_asset_columns_used"
    ] = [
        int(
            player_usage_counts.get(
                (
                    row.file_path,
                    row.qualified_symbol_name,
                ),
                0,
            )
        )
        for row in output.itertuples(index=False)
    ]

    output[
        "trade_package_columns_used"
    ] = [
        int(
            trade_usage_counts.get(
                (
                    row.file_path,
                    row.qualified_symbol_name,
                ),
                0,
            )
        )
        for row in output.itertuples(index=False)
    ]

    role_priority = {
        "pick_inventory_loader": 1,
        "pick_candidate_pool_injection": 2,
        "mixed_player_pick_package_construction": 3,
        "pick_value_scoring": 4,
        "pick_legality_filter": 5,
        "salary_validation_boundary": 6,
        "optimizer_orchestration_entrypoint": 7,
        "supporting_function": 99,
    }

    output[
        "role_priority"
    ] = output[
        "integration_role"
    ].map(
        role_priority
    ).fillna(99).astype(int)

    output[
        "integration_priority_score"
    ] = (
        pd.to_numeric(
            output[
                "function_role_score"
            ],
            errors="coerce",
        ).fillna(0)
        + output[
            "canonical_pick_columns_used"
        ]
        * 15
        + output[
            "player_asset_columns_used"
        ]
        * 5
        + output[
            "trade_package_columns_used"
        ]
        * 10
        + output[
            "function_name"
        ]
        .fillna("")
        .astype(str)
        .str.lower()
        .isin(
            {
                "main",
                "run",
                "run_optimizer",
                "optimize",
                "build_candidates",
                "generate_candidates",
                "score_trade",
                "build_trade_package",
            }
        )
        .astype(int)
        * 20
    )

    output[
        "recommended_action"
    ] = output[
        "integration_role"
    ].map(
        {
            "pick_inventory_loader": (
                "Load the canonical future-pick inventory and normalize "
                "tradable rows into the engine's asset schema."
            ),
            "pick_candidate_pool_injection": (
                "Add eligible standalone pick rights to each team's "
                "candidate asset pool."
            ),
            "mixed_player_pick_package_construction": (
                "Permit packages containing players and pick rights "
                "while preserving source-right identifiers."
            ),
            "pick_value_scoring": (
                "Include candidate_right_value_score in package value "
                "and balance calculations."
            ),
            "pick_legality_filter": (
                "Reject accounting increments and require trade-date "
                "ownership, Stepien, frozen-pick, and encumbrance checks."
            ),
            "salary_validation_boundary": (
                "Keep pick rights salary-neutral while validating player "
                "salary matching separately."
            ),
            "optimizer_orchestration_entrypoint": (
                "Wire the pick loader, legality filter, candidate pool, "
                "package builder, and scoring stages together."
            ),
            "supporting_function": (
                "Review as a supporting dependency before modifying."
            ),
        }
    )

    return output.sort_values(
        [
            "role_priority",
            "integration_priority_score",
            "file_path",
            "start_line",
        ],
        ascending=[
            True,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_readiness(
    production_files: pd.DataFrame,
    functions: pd.DataFrame,
    integration_plan: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    roles = set(
        integration_plan[
            "integration_role"
        ].fillna("")
    )

    standalone_rows = int(
        inventory[
            "standalone_trade_asset_flag"
        ].fillna(False)
        .astype(bool)
        .sum()
    )

    accounting_increment_rows = int(
        (
            ~inventory[
                "standalone_trade_asset_flag"
            ]
            .fillna(False)
            .astype(bool)
        ).sum()
    )

    checks = [
        {
            "check_name": "production_files_identified",
            "observed_value": len(production_files),
            "expected_value": ">0",
            "passed": len(production_files) > 0,
        },
        {
            "check_name": "production_functions_identified",
            "observed_value": len(functions),
            "expected_value": ">0",
            "passed": len(functions) > 0,
        },
        {
            "check_name": "pick_inventory_loader_candidate_found",
            "observed_value": (
                "pick_inventory_loader" in roles
            ),
            "expected_value": True,
            "passed": "pick_inventory_loader" in roles,
        },
        {
            "check_name": "candidate_pool_injection_candidate_found",
            "observed_value": (
                "pick_candidate_pool_injection" in roles
            ),
            "expected_value": True,
            "passed": (
                "pick_candidate_pool_injection" in roles
            ),
        },
        {
            "check_name": "package_construction_candidate_found",
            "observed_value": (
                "mixed_player_pick_package_construction"
                in roles
            ),
            "expected_value": True,
            "passed": (
                "mixed_player_pick_package_construction"
                in roles
            ),
        },
        {
            "check_name": "pick_scoring_candidate_found",
            "observed_value": (
                "pick_value_scoring" in roles
            ),
            "expected_value": True,
            "passed": "pick_value_scoring" in roles,
        },
        {
            "check_name": "salary_boundary_candidate_found",
            "observed_value": (
                "salary_validation_boundary" in roles
            ),
            "expected_value": True,
            "passed": (
                "salary_validation_boundary" in roles
            ),
        },
        {
            "check_name": "legality_filter_candidate_found",
            "observed_value": (
                "pick_legality_filter" in roles
            ),
            "expected_value": True,
            "passed": "pick_legality_filter" in roles,
        },
        {
            "check_name": "optimizer_entrypoint_candidate_found",
            "observed_value": (
                "optimizer_orchestration_entrypoint"
                in roles
            ),
            "expected_value": True,
            "passed": (
                "optimizer_orchestration_entrypoint"
                in roles
            ),
        },
        {
            "check_name": "canonical_inventory_rows_present",
            "observed_value": len(inventory),
            "expected_value": 174,
            "passed": len(inventory) == 174,
        },
        {
            "check_name": "standalone_pick_right_rows_present",
            "observed_value": standalone_rows,
            "expected_value": ">0",
            "passed": standalone_rows > 0,
        },
        {
            "check_name": "accounting_only_rows_identified",
            "observed_value": accounting_increment_rows,
            "expected_value": ">0",
            "passed": accounting_increment_rows > 0,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FOCUSED OPTIMIZER TRADE INTERFACE AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        v1_files,
        v1_symbols,
        v1_imports,
        v1_calls,
    ) = load_v1_outputs()

    production_paths = select_production_files(
        v1_files
    )

    if not production_paths:
        raise RuntimeError(
            "No production workflow files were identified."
        )

    file_rows = []
    function_rows = []
    io_rows = []
    dataset_path_rows = []

    for index, path in enumerate(
        production_paths,
        start=1,
    ):
        print(
            f"[{index:02d}/{len(production_paths):02d}] "
            f"Scanning {relative_path(path)}"
        )

        (
            file_row,
            path_function_rows,
            path_io_rows,
            path_dataset_rows,
        ) = scan_production_file(path)

        file_rows.append(file_row)
        function_rows.extend(path_function_rows)
        io_rows.extend(path_io_rows)
        dataset_path_rows.extend(path_dataset_rows)

    production_files = pd.DataFrame(file_rows).sort_values(
        [
            "file_role_score",
            "production_name_score",
            "file_path",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    production_functions = pd.DataFrame(function_rows)

    if not production_functions.empty:
        production_functions = (
            production_functions.loc[
                production_functions[
                    "function_role_score"
                ]
                > 0
            ]
            .sort_values(
                [
                    "function_role_score",
                    "file_path",
                    "start_line",
                ],
                ascending=[
                    False,
                    True,
                    True,
                ],
            )
            .reset_index(drop=True)
        )

    function_io = pd.DataFrame(io_rows)

    dataset_paths = pd.DataFrame(dataset_path_rows)

    production_file_set = set(
        production_files[
            "file_path"
        ]
    )

    import_graph = build_production_import_graph(
        v1_imports,
        production_file_set,
    )

    call_graph = build_production_call_graph(
        v1_calls,
        production_file_set,
    )

    column_usage = build_column_usage(
        production_functions
    )

    integration_plan = build_integration_plan(
        production_functions=production_functions,
        io_catalog=function_io,
        column_usage=column_usage,
    )

    if not CANONICAL_PICK_INVENTORY_PATH.exists():
        raise FileNotFoundError(
            "Canonical pick inventory was not found:\n"
            f"{CANONICAL_PICK_INVENTORY_PATH}"
        )

    inventory = pd.read_parquet(
        CANONICAL_PICK_INVENTORY_PATH
    )

    readiness = build_readiness(
        production_files=production_files,
        functions=production_functions,
        integration_plan=integration_plan,
        inventory=inventory,
    )

    production_files.to_csv(
        PRODUCTION_FILE_CATALOG_PATH,
        index=False,
    )

    production_functions.to_csv(
        PRODUCTION_SYMBOL_CATALOG_PATH,
        index=False,
    )

    function_io.to_csv(
        FUNCTION_IO_CATALOG_PATH,
        index=False,
    )

    import_graph.to_csv(
        PRODUCTION_IMPORT_GRAPH_PATH,
        index=False,
    )

    call_graph.to_csv(
        PRODUCTION_CALL_GRAPH_PATH,
        index=False,
    )

    dataset_paths.to_csv(
        DATASET_PATH_CATALOG_PATH,
        index=False,
    )

    column_usage.to_csv(
        COLUMN_USAGE_CATALOG_PATH,
        index=False,
    )

    integration_plan.to_csv(
        INTEGRATION_PLAN_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    top_files = production_files.head(15)
    top_plan = integration_plan.loc[
        integration_plan[
            "integration_role"
        ]
        .ne("supporting_function")
    ].head(30)

    role_counts = (
        integration_plan[
            "integration_role"
        ]
        .value_counts()
        .rename_axis(
            "integration_role"
        )
        .reset_index(
            name="function_count"
        )
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "production_files_scanned": int(
            len(production_files)
        ),
        "production_functions_found": int(
            len(production_functions)
        ),
        "integration_plan_rows": int(
            len(integration_plan)
        ),
        "integration_roles_found": sorted(
            set(
                integration_plan[
                    "integration_role"
                ]
            )
        ),
        "canonical_inventory_rows": int(
            len(inventory)
        ),
        "standalone_trade_asset_rows": int(
            inventory[
                "standalone_trade_asset_flag"
            ]
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        "accounting_only_rows": int(
            (
                ~inventory[
                    "standalone_trade_asset_flag"
                ]
                .fillna(False)
                .astype(bool)
            ).sum()
        ),
        "readiness_checks": int(
            len(readiness)
        ),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "focused_integration_ready": bool(
            readiness[
                "passed"
            ].all()
        ),
        "output_files": {
            "production_files": str(
                PRODUCTION_FILE_CATALOG_PATH
            ),
            "production_symbols": str(
                PRODUCTION_SYMBOL_CATALOG_PATH
            ),
            "function_io": str(
                FUNCTION_IO_CATALOG_PATH
            ),
            "import_graph": str(
                PRODUCTION_IMPORT_GRAPH_PATH
            ),
            "call_graph": str(
                PRODUCTION_CALL_GRAPH_PATH
            ),
            "dataset_paths": str(
                DATASET_PATH_CATALOG_PATH
            ),
            "column_usage": str(
                COLUMN_USAGE_CATALOG_PATH
            ),
            "integration_plan": str(
                INTEGRATION_PLAN_PATH
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
    print("FOCUSED OPTIMIZER TRADE INTERFACE AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Production files scanned: "
        f"{len(production_files):,}"
    )
    print(
        "Relevant production functions: "
        f"{len(production_functions):,}"
    )
    print(
        "Integration-plan rows: "
        f"{len(integration_plan):,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Focused integration ready: "
        f"{bool(readiness['passed'].all())}"
    )
    print()

    print("TOP PRODUCTION FILES")
    print(
        top_files[
            [
                "file_path",
                "file_role_score",
                "production_name_score",
                "file_roles",
                "salary_engine_references",
                "candidate_generator_references",
                "trade_package_builder_references",
                "trade_scorer_references",
                "legality_engine_references",
                "player_asset_loader_references",
                "pick_asset_loader_references",
            ]
        ].to_string(index=False)
    )
    print()

    print("INTEGRATION ROLE COUNTS")
    print(
        role_counts.to_string(index=False)
    )
    print()

    print("TOP INTEGRATION FUNCTIONS")

    if top_plan.empty:
        print(
            "No non-supporting integration functions were identified."
        )
    else:
        print(
            top_plan[
                [
                    "integration_role",
                    "file_path",
                    "qualified_symbol_name",
                    "start_line",
                    "end_line",
                    "arguments",
                    "integration_priority_score",
                    "canonical_pick_columns_used",
                    "player_asset_columns_used",
                    "trade_package_columns_used",
                    "recommended_action",
                ]
            ].to_string(index=False)
        )

    print()
    print("READINESS")
    print(
        readiness.to_string(index=False)
    )
    print()

    print("SAVED FILES")

    for path in [
        PRODUCTION_FILE_CATALOG_PATH,
        PRODUCTION_SYMBOL_CATALOG_PATH,
        FUNCTION_IO_CATALOG_PATH,
        PRODUCTION_IMPORT_GRAPH_PATH,
        PRODUCTION_CALL_GRAPH_PATH,
        DATASET_PATH_CATALOG_PATH,
        COLUMN_USAGE_CATALOG_PATH,
        INTEGRATION_PLAN_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()