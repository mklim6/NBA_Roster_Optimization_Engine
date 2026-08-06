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


SCRIPT_VERSION = "optimizer-runtime-core-map-v1-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "src"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

TARGET_FILES = [
    "build_base_player_pool.py",
    "build_current_player_projection_board.py",
    "build_trade_salary_precheck_engine_v1.py",
    "build_multi_player_trade_salary_precheck_v1.py",
    "build_trade_basketball_fit_engine_v1.py",
    "build_multi_player_trade_fit_engine_v1.py",
    "build_trade_realism_layer_v1.py",
    "calibrate_trade_realism_layer_v3.py",
    "calibrate_multi_player_trade_realism_v2.py",
]

CANONICAL_PICK_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

FILE_MAP_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_file_map_v1.csv"
)

FUNCTION_MAP_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_function_map_v1.csv"
)

MAIN_CALL_SEQUENCE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_main_call_sequence_v1.csv"
)

PATH_CONSTANTS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_path_constants_v1.csv"
)

DATA_IO_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_data_io_v1.csv"
)

COLUMN_USAGE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_column_usage_v1.csv"
)

INTEGRATION_POINTS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_pick_integration_points_v1.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_readiness_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_core_map_metadata_v1.json"
)


ROLE_PATTERNS = {
    "candidate_enumerator": [
        r"\bitertools\.(?:combinations|permutations|product)\b",
        r"\bcombinations?\(",
        r"\bpermutations?\(",
        r"\bproduct\(",
        r"\benumerate[_ ]?(?:candidate|trade|package)",
        r"\bgenerate[_ ]?(?:candidate|trade|package)",
    ],
    "package_builder": [
        r"\btrade[_ ]?package\b",
        r"\bpackage[_ ]?(?:id|rows?|builder|construction)",
        r"\bplayers?[_ ]?(?:out|in|sent|received)\b",
        r"\bassets?[_ ]?(?:out|in|sent|received)\b",
        r"\bsending[_ ]?team\b",
        r"\breceiving[_ ]?team\b",
    ],
    "salary_validator": [
        r"\boutgoing[_ ]?salary\b",
        r"\bincoming[_ ]?salary\b",
        r"\bsalary[_ ]?(?:match|matching|precheck)\b",
        r"\btrade[_ ]?exception\b",
        r"\bfirst[_ ]?apron\b",
        r"\bsecond[_ ]?apron\b",
        r"\btax[_ ]?apron\b",
    ],
    "fit_scorer": [
        r"\bfit[_ ]?score\b",
        r"\bbasketball[_ ]?fit\b",
        r"\broster[_ ]?fit\b",
        r"\bskill[_ ]?fit\b",
        r"\brole[_ ]?fit\b",
    ],
    "realism_scorer": [
        r"\brealism[_ ]?(?:score|probability|model)\b",
        r"\btrade[_ ]?realism\b",
        r"\bacceptance[_ ]?probability\b",
        r"\bplausibility\b",
    ],
    "value_scorer": [
        r"\btrade[_ ]?value\b",
        r"\bpackage[_ ]?value\b",
        r"\bvalue[_ ]?balance\b",
        r"\bsurplus[_ ]?value\b",
        r"\basset[_ ]?value\b",
        r"\bobjective[_ ]?score\b",
    ],
    "legality_validator": [
        r"\blegal(?:ity)?\b",
        r"\bvalid[_ ]?trade\b",
        r"\bcba\b",
        r"\bstepien\b",
        r"\bfrozen[_ ]?pick\b",
        r"\bencumber",
        r"\bownership\b",
    ],
    "data_loader": [
        r"\bread_csv\(",
        r"\bread_parquet\(",
        r"\bload[_ ]",
    ],
    "output_writer": [
        r"\bto_csv\(",
        r"\bto_parquet\(",
        r"\bwrite_text\(",
        r"\bjson\.dump\(",
    ],
    "orchestrator": [
        r"\bdef main\(",
        r"\brun[_ ]?optimizer\b",
        r"\boptimize[_ ]?(?:trade|roster|package)\b",
        r"\bpipeline\b",
    ],
}

PATH_OPERATION_NAMES = {
    "read_csv",
    "read_parquet",
    "to_csv",
    "to_parquet",
    "read_text",
    "write_text",
    "open",
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


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


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
    return str(path.relative_to(PROJECT_ROOT))


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


def ast_unparse_safe(node: ast.AST | None) -> str:
    if node is None:
        return ""

    try:
        return ast.unparse(node)
    except Exception:
        return ""


def count_patterns(
    text: str,
    patterns: list[str],
) -> int:
    return sum(
        len(re.findall(pattern, text, flags=re.IGNORECASE))
        for pattern in patterns
    )


def infer_roles(text: str) -> dict[str, int]:
    return {
        role: count_patterns(text, patterns)
        for role, patterns in ROLE_PATTERNS.items()
    }


def role_string(counts: dict[str, int]) -> str:
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

    return "|".join(role for role, _ in ranked)


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
                first = child.args[0]

                if isinstance(first, ast.Constant) and isinstance(
                    first.value,
                    str,
                ):
                    columns.add(first.value)

    return columns


def extract_calls(
    node: ast.AST,
) -> list[dict[str, Any]]:
    rows = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        expression = ast_unparse_safe(child.func)

        if not expression:
            continue

        rows.append(
            {
                "line_number": int(
                    getattr(child, "lineno", 0)
                ),
                "call_expression": expression,
                "called_base_name": expression.split(".")[-1],
                "positional_argument_count": len(child.args),
                "keyword_arguments": "|".join(
                    keyword.arg
                    for keyword in child.keywords
                    if keyword.arg is not None
                ),
            }
        )

    return rows


def extract_path_operations(
    node: ast.AST,
) -> list[dict[str, Any]]:
    rows = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        expression = ast_unparse_safe(child.func)
        base_name = expression.split(".")[-1]

        if base_name not in PATH_OPERATION_NAMES:
            continue

        path_expression = (
            ast_unparse_safe(child.args[0])
            if child.args
            else ""
        )

        rows.append(
            {
                "line_number": int(
                    getattr(child, "lineno", 0)
                ),
                "operation": base_name,
                "call_expression": expression,
                "path_expression": path_expression,
            }
        )

    return rows


def extract_path_constants(
    tree: ast.AST,
    file_path: str,
) -> list[dict[str, Any]]:
    rows = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = []

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
                r"(?:PATH|DIRECTORY|DIR|FILE)$",
                name,
                flags=re.IGNORECASE,
            ):
                continue

            rows.append(
                {
                    "file_path": file_path,
                    "constant_name": name,
                    "line_number": int(
                        getattr(node, "lineno", 0)
                    ),
                    "value_expression": ast_unparse_safe(value),
                }
            )

    return rows


def scan_file(
    path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    text = read_text(path)
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))
    file_path = relative_path(path)

    file_roles = infer_roles(text)

    file_row = {
        "file_path": file_path,
        "line_count": len(lines),
        "file_size_bytes": int(path.stat().st_size),
        "file_roles": role_string(file_roles),
        "file_role_score": int(sum(file_roles.values())),
        **{
            f"{role}_references": count
            for role, count in file_roles.items()
        },
    }

    path_constants = extract_path_constants(
        tree,
        file_path,
    )

    function_rows = []
    call_rows = []
    io_rows = []

    class Visitor(ast.NodeVisitor):
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
                lines[max(0, start_line - 1):end_line]
            )

            roles = infer_roles(
                f"{node.name}\n{source}"
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

            calls = extract_calls(node)
            path_operations = extract_path_operations(node)

            function_rows.append(
                {
                    "file_path": file_path,
                    "qualified_symbol_name": qualified_name,
                    "function_name": node.name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "line_count": end_line - start_line + 1,
                    "arguments": "|".join(
                        function_arguments(node)
                    ),
                    "return_annotation": ast_unparse_safe(
                        node.returns
                    ),
                    "docstring": clean_text(
                        ast.get_docstring(node)
                    ),
                    "function_roles": role_string(roles),
                    "function_role_score": int(
                        sum(roles.values())
                    ),
                    "referenced_columns": "|".join(columns),
                    "canonical_pick_columns_used": int(
                        sum(
                            column in CANONICAL_PICK_COLUMNS
                            for column in columns
                        )
                    ),
                    "call_count": len(calls),
                    "called_functions": "|".join(
                        sorted(
                            {
                                row["call_expression"]
                                for row in calls
                            }
                        )
                    ),
                    **{
                        f"{role}_references": count
                        for role, count in roles.items()
                    },
                }
            )

            for call_order, call in enumerate(
                sorted(
                    calls,
                    key=lambda row: row["line_number"],
                ),
                start=1,
            ):
                call_rows.append(
                    {
                        "file_path": file_path,
                        "caller_symbol": qualified_name,
                        "call_order": call_order,
                        **call,
                    }
                )

            for operation in path_operations:
                io_rows.append(
                    {
                        "file_path": file_path,
                        "qualified_symbol_name": qualified_name,
                        **operation,
                    }
                )

            self.generic_visit(node)

    Visitor().visit(tree)

    return (
        file_row,
        function_rows,
        call_rows,
        path_constants,
        io_rows,
    )


def build_main_call_sequence(
    call_rows: pd.DataFrame,
    function_rows: pd.DataFrame,
) -> pd.DataFrame:
    if call_rows.empty:
        return pd.DataFrame()

    known_functions = set(
        function_rows[
            "function_name"
        ]
    )

    output = call_rows.loc[
        call_rows[
            "caller_symbol"
        ].eq("main")
    ].copy()

    output[
        "called_project_function"
    ] = output[
        "called_base_name"
    ].isin(known_functions)

    return output.sort_values(
        [
            "file_path",
            "line_number",
            "call_order",
        ]
    ).reset_index(drop=True)


def classify_integration_point(
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
        "data_loader" in roles
        and name.startswith("load")
    ):
        return "pick_inventory_loader"

    if "candidate_enumerator" in roles:
        return "candidate_enumerator"

    if "package_builder" in roles:
        return "mixed_asset_package_builder"

    if "salary_validator" in roles:
        return "salary_validator"

    if "fit_scorer" in roles:
        return "fit_scorer"

    if "realism_scorer" in roles:
        return "realism_scorer"

    if "value_scorer" in roles:
        return "value_scorer"

    if "legality_validator" in roles:
        return "pick_legality_validator"

    if name == "main" or "orchestrator" in roles:
        return "orchestrator"

    return "supporting_function"


def recommended_action(point_type: str) -> str:
    mapping = {
        "pick_inventory_loader": (
            "Extend this loader or add a sibling loader for the canonical "
            "future-pick inventory."
        ),
        "candidate_enumerator": (
            "Inject eligible standalone pick rights into the same team "
            "candidate enumeration used for players."
        ),
        "mixed_asset_package_builder": (
            "Add pick-right identifiers to package records without "
            "changing player salary totals."
        ),
        "salary_validator": (
            "Treat pick rights as zero salary and preserve all existing "
            "player salary checks."
        ),
        "fit_scorer": (
            "Keep basketball-fit scoring player-only unless a separate "
            "future-value term is intentionally added."
        ),
        "realism_scorer": (
            "Add pick value, pick count, and right structure as package "
            "realism features."
        ),
        "value_scorer": (
            "Add candidate_right_value_score to outgoing and incoming "
            "asset-value totals."
        ),
        "pick_legality_validator": (
            "Require standalone_trade_asset_flag and trade-date ownership, "
            "encumbrance, Stepien, and frozen-pick checks."
        ),
        "orchestrator": (
            "Wire pick loading, eligibility, package generation, scoring, "
            "salary checks, and legality checks in execution order."
        ),
        "supporting_function": (
            "Review as a dependency only."
        ),
    }

    return mapping[point_type]


def build_integration_points(
    function_rows: pd.DataFrame,
) -> pd.DataFrame:
    output = function_rows.copy()

    output[
        "integration_point_type"
    ] = output.apply(
        classify_integration_point,
        axis=1,
    )

    output[
        "recommended_action"
    ] = output[
        "integration_point_type"
    ].map(
        recommended_action
    )

    priority = {
        "pick_inventory_loader": 1,
        "candidate_enumerator": 2,
        "mixed_asset_package_builder": 3,
        "value_scorer": 4,
        "salary_validator": 5,
        "pick_legality_validator": 6,
        "fit_scorer": 7,
        "realism_scorer": 8,
        "orchestrator": 9,
        "supporting_function": 99,
    }

    output[
        "priority"
    ] = output[
        "integration_point_type"
    ].map(
        priority
    ).fillna(99).astype(int)

    output[
        "integration_score"
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
        * 20
        + output[
            "function_name"
        ]
        .fillna("")
        .astype(str)
        .str.lower()
        .isin(
            {
                "main",
                "load_inputs",
                "generate_candidates",
                "build_trade_packages",
                "score_trade",
                "validate_trade",
            }
        )
        .astype(int)
        * 15
    )

    return output.sort_values(
        [
            "priority",
            "integration_score",
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
    integration_points: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    types = set(
        integration_points[
            "integration_point_type"
        ]
    )

    checks = [
        {
            "check_name": "core_files_scanned",
            "observed_value": len(TARGET_FILES),
            "expected_value": len(TARGET_FILES),
            "passed": True,
        },
        {
            "check_name": "canonical_pick_inventory_rows",
            "observed_value": len(inventory),
            "expected_value": 174,
            "passed": len(inventory) == 174,
        },
        {
            "check_name": "standalone_pick_rows",
            "observed_value": int(
                inventory[
                    "standalone_trade_asset_flag"
                ]
                .fillna(False)
                .astype(bool)
                .sum()
            ),
            "expected_value": ">0",
            "passed": bool(
                inventory[
                    "standalone_trade_asset_flag"
                ]
                .fillna(False)
                .astype(bool)
                .any()
            ),
        },
        {
            "check_name": "pick_inventory_loader_found",
            "observed_value": (
                "pick_inventory_loader" in types
            ),
            "expected_value": True,
            "passed": "pick_inventory_loader" in types,
        },
        {
            "check_name": "candidate_enumerator_found",
            "observed_value": (
                "candidate_enumerator" in types
            ),
            "expected_value": True,
            "passed": "candidate_enumerator" in types,
        },
        {
            "check_name": "mixed_asset_package_builder_found",
            "observed_value": (
                "mixed_asset_package_builder" in types
            ),
            "expected_value": True,
            "passed": (
                "mixed_asset_package_builder" in types
            ),
        },
        {
            "check_name": "salary_validator_found",
            "observed_value": (
                "salary_validator" in types
            ),
            "expected_value": True,
            "passed": "salary_validator" in types,
        },
        {
            "check_name": "fit_scorer_found",
            "observed_value": (
                "fit_scorer" in types
            ),
            "expected_value": True,
            "passed": "fit_scorer" in types,
        },
        {
            "check_name": "realism_scorer_found",
            "observed_value": (
                "realism_scorer" in types
            ),
            "expected_value": True,
            "passed": "realism_scorer" in types,
        },
        {
            "check_name": "value_scorer_found",
            "observed_value": (
                "value_scorer" in types
            ),
            "expected_value": True,
            "passed": "value_scorer" in types,
        },
        {
            "check_name": "pick_legality_validator_found",
            "observed_value": (
                "pick_legality_validator" in types
            ),
            "expected_value": True,
            "passed": "pick_legality_validator" in types,
        },
        {
            "check_name": "orchestrator_found",
            "observed_value": (
                "orchestrator" in types
            ),
            "expected_value": True,
            "passed": "orchestrator" in types,
        },
        {
            "check_name": "canonical_pick_columns_already_used",
            "observed_value": int(
                integration_points[
                    "canonical_pick_columns_used"
                ].sum()
            ),
            "expected_value": ">0",
            "passed": int(
                integration_points[
                    "canonical_pick_columns_used"
                ].sum()
            )
            > 0,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("OPTIMIZER RUNTIME CORE MAP")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    paths = [
        SOURCE_DIRECTORY / file_name
        for file_name in TARGET_FILES
    ]

    missing = [
        path
        for path in paths
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required core files were not found:\n"
            + "\n".join(str(path) for path in missing)
        )

    file_rows = []
    function_rows = []
    call_rows = []
    path_constant_rows = []
    io_rows = []

    for index, path in enumerate(paths, start=1):
        print(
            f"[{index:02d}/{len(paths):02d}] "
            f"Mapping {relative_path(path)}"
        )

        (
            file_row,
            path_function_rows,
            path_call_rows,
            path_constants,
            path_io_rows,
        ) = scan_file(path)

        file_rows.append(file_row)
        function_rows.extend(path_function_rows)
        call_rows.extend(path_call_rows)
        path_constant_rows.extend(path_constants)
        io_rows.extend(path_io_rows)

    file_map = pd.DataFrame(file_rows).sort_values(
        [
            "file_role_score",
            "file_path",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(drop=True)

    function_map = pd.DataFrame(function_rows)

    function_map = function_map.loc[
        function_map[
            "function_role_score"
        ]
        > 0
    ].sort_values(
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
    ).reset_index(drop=True)

    call_map = pd.DataFrame(call_rows)
    path_constants = pd.DataFrame(path_constant_rows)
    data_io = pd.DataFrame(io_rows)

    main_sequence = build_main_call_sequence(
        call_map,
        function_map,
    )

    column_rows = []

    for row in function_map.itertuples(index=False):
        for column in clean_text(
            row.referenced_columns
        ).split("|"):
            if not column:
                continue

            column_rows.append(
                {
                    "file_path": row.file_path,
                    "qualified_symbol_name": (
                        row.qualified_symbol_name
                    ),
                    "column_name": column,
                    "is_canonical_pick_column": bool(
                        column in CANONICAL_PICK_COLUMNS
                    ),
                }
            )

    column_usage = pd.DataFrame(column_rows)

    if not column_usage.empty:
        column_usage = column_usage.drop_duplicates().sort_values(
            [
                "is_canonical_pick_column",
                "column_name",
                "file_path",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        ).reset_index(drop=True)

    integration_points = build_integration_points(
        function_map
    )

    if not CANONICAL_PICK_INVENTORY_PATH.exists():
        raise FileNotFoundError(
            "Canonical future-pick inventory was not found:\n"
            f"{CANONICAL_PICK_INVENTORY_PATH}"
        )

    inventory = pd.read_parquet(
        CANONICAL_PICK_INVENTORY_PATH
    )

    readiness = build_readiness(
        integration_points,
        inventory,
    )

    file_map.to_csv(
        FILE_MAP_PATH,
        index=False,
    )

    function_map.to_csv(
        FUNCTION_MAP_PATH,
        index=False,
    )

    main_sequence.to_csv(
        MAIN_CALL_SEQUENCE_PATH,
        index=False,
    )

    path_constants.to_csv(
        PATH_CONSTANTS_PATH,
        index=False,
    )

    data_io.to_csv(
        DATA_IO_PATH,
        index=False,
    )

    column_usage.to_csv(
        COLUMN_USAGE_PATH,
        index=False,
    )

    integration_points.to_csv(
        INTEGRATION_POINTS_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    top_points = integration_points.loc[
        integration_points[
            "integration_point_type"
        ]
        .ne("supporting_function")
    ].head(40)

    type_counts = (
        integration_points[
            "integration_point_type"
        ]
        .value_counts()
        .rename_axis(
            "integration_point_type"
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
        "target_files": TARGET_FILES,
        "files_mapped": int(len(file_map)),
        "functions_mapped": int(len(function_map)),
        "main_call_rows": int(len(main_sequence)),
        "path_constants": int(len(path_constants)),
        "data_io_rows": int(len(data_io)),
        "integration_points": int(len(integration_points)),
        "canonical_inventory_rows": int(len(inventory)),
        "canonical_pick_columns_already_used": int(
            integration_points[
                "canonical_pick_columns_used"
            ].sum()
        ),
        "readiness_checks": int(len(readiness)),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "runtime_integration_ready": bool(
            readiness[
                "passed"
            ].all()
        ),
        "output_files": {
            "file_map": str(FILE_MAP_PATH),
            "function_map": str(FUNCTION_MAP_PATH),
            "main_call_sequence": str(
                MAIN_CALL_SEQUENCE_PATH
            ),
            "path_constants": str(PATH_CONSTANTS_PATH),
            "data_io": str(DATA_IO_PATH),
            "column_usage": str(COLUMN_USAGE_PATH),
            "integration_points": str(
                INTEGRATION_POINTS_PATH
            ),
            "readiness": str(READINESS_PATH),
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
    print("OPTIMIZER RUNTIME CORE MAP COMPLETE")
    print("=" * 80)
    print(f"Core files mapped: {len(file_map):,}")
    print(f"Relevant functions mapped: {len(function_map):,}")
    print(f"Main call rows mapped: {len(main_sequence):,}")
    print(
        "Canonical pick columns already used by core functions: "
        f"{int(integration_points['canonical_pick_columns_used'].sum()):,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Runtime integration ready: "
        f"{bool(readiness['passed'].all())}"
    )
    print()

    print("CORE FILE MAP")
    print(
        file_map[
            [
                "file_path",
                "file_roles",
                "candidate_enumerator_references",
                "package_builder_references",
                "salary_validator_references",
                "fit_scorer_references",
                "realism_scorer_references",
                "value_scorer_references",
                "legality_validator_references",
                "orchestrator_references",
            ]
        ].to_string(index=False)
    )
    print()

    print("INTEGRATION POINT COUNTS")
    print(
        type_counts.to_string(index=False)
    )
    print()

    print("TOP EXACT INTEGRATION POINTS")

    if top_points.empty:
        print(
            "No exact runtime integration points were identified."
        )
    else:
        print(
            top_points[
                [
                    "integration_point_type",
                    "file_path",
                    "qualified_symbol_name",
                    "start_line",
                    "end_line",
                    "arguments",
                    "canonical_pick_columns_used",
                    "integration_score",
                    "recommended_action",
                ]
            ].to_string(index=False)
        )

    print()
    print("MAIN CALL SEQUENCE")

    if main_sequence.empty:
        print(
            "No main function call sequence was identified."
        )
    else:
        print(
            main_sequence.loc[
                main_sequence[
                    "called_project_function"
                ]
            ][
                [
                    "file_path",
                    "line_number",
                    "call_order",
                    "call_expression",
                    "called_base_name",
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
        FILE_MAP_PATH,
        FUNCTION_MAP_PATH,
        MAIN_CALL_SEQUENCE_PATH,
        PATH_CONSTANTS_PATH,
        DATA_IO_PATH,
        COLUMN_USAGE_PATH,
        INTEGRATION_POINTS_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()