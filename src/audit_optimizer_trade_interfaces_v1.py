from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "optimizer-trade-interface-audit-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_DIRECTORIES = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
]

CONFIG_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
}

PYTHON_EXTENSION = ".py"

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FILE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_file_catalog_v1.csv"
)

SYMBOL_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_symbol_catalog_v1.csv"
)

REFERENCE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_reference_catalog_v1.csv"
)

COLUMN_REFERENCE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_column_reference_audit_v1.csv"
)

IMPORT_EDGE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_import_edges_v1.csv"
)

CALL_EDGE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_call_edges_v1.csv"
)

INTEGRATION_CANDIDATE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_integration_candidates_v1.csv"
)

PICK_SUPPORT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_existing_pick_support_v1.csv"
)

CANONICAL_INVENTORY_COMPATIBILITY_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_inventory_compatibility_v1.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_readiness_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_trade_interface_audit_metadata_v1.json"
)


CANONICAL_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

CANONICAL_INVENTORY_REQUIRED_COLUMNS = [
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
]


CATEGORY_PATTERNS = {
    "package_construction": [
        r"\btrade[_ ]?package",
        r"\bpackage[_ ]?(?:builder|generator|candidate|construction)",
        r"\bbuild[_ ]?(?:trade|package)",
        r"\bconstruct[_ ]?(?:trade|package)",
        r"\bassemble[_ ]?(?:trade|package)",
        r"\bgenerate[_ ]?(?:trade|package)",
        r"\bassets?[_ ]?(?:out|in|sent|received)",
    ],
    "candidate_generation": [
        r"\bcandidate[_ ]?(?:generation|generator|pool|set|search)",
        r"\bgenerate[_ ]?candidates?",
        r"\benumerate[_ ]?candidates?",
        r"\bsearch[_ ]?space",
        r"\bbeam[_ ]?search",
        r"\bcombinations?\b",
        r"\bpermutations?\b",
    ],
    "objective_scoring": [
        r"\bobjective\b",
        r"\bscore[_ ]?(?:trade|package|candidate|deal)",
        r"\btrade[_ ]?score",
        r"\bpackage[_ ]?score",
        r"\bvalue[_ ]?score",
        r"\butility\b",
        r"\bfitness\b",
        r"\brank[_ ]?(?:trade|package|candidate)",
    ],
    "salary_matching": [
        r"\bsalary[_ ]?match",
        r"\bmatching[_ ]?salary",
        r"\bincoming[_ ]?salary",
        r"\boutgoing[_ ]?salary",
        r"\btrade[_ ]?exception",
        r"\bapron\b",
        r"\btax[_ ]?team",
        r"\baggregation\b",
    ],
    "cba_legality": [
        r"\bcba\b",
        r"\blegal(?:ity)?\b",
        r"\bvalid[_ ]?trade",
        r"\btrade[_ ]?rules?",
        r"\bstepien\b",
        r"\bfrozen[_ ]?pick",
        r"\bencumber",
        r"\bconsecutive[_ ]?future[_ ]?first",
        r"\bseven[_ -]?year",
        r"\bsecond[_ ]?apron",
    ],
    "player_asset_model": [
        r"\bplayer[_ ]?(?:asset|inventory|pool|value|score)",
        r"\broster[_ ]?(?:asset|player|inventory)",
        r"\bplayer_id\b",
        r"\bplayer_name\b",
        r"\bplayer_value\b",
        r"\bcontract[_ ]?value",
    ],
    "pick_asset_model": [
        r"\bpick[_ ]?(?:asset|inventory|pool|value|score|right)",
        r"\bfuture[_ ]?pick",
        r"\bdraft[_ ]?pick",
        r"\bsource_assets?\b",
        r"\bexpected_pick_count\b",
        r"\bcandidate_right_value_score\b",
    ],
    "ownership_encumbrance": [
        r"\bownership\b",
        r"\bowner[_ ]?team",
        r"\bbeneficiary\b",
        r"\bencumber",
        r"\bobligation\b",
        r"\bprotection\b",
        r"\brollover\b",
        r"\bswap[_ ]?right",
    ],
    "optimizer_orchestration": [
        r"\boptimizer\b",
        r"\boptimization\b",
        r"\bsolve\b",
        r"\bsolver\b",
        r"\bmain\s*\(",
        r"\brun[_ ]?(?:optimizer|optimization)",
        r"\boptimize[_ ]?(?:trade|roster|package)",
    ],
    "data_loading": [
        r"\bread_parquet\b",
        r"\bread_csv\b",
        r"\bload[_ ]?(?:data|players|roster|assets|picks)",
        r"\bdata[_ ]?loader",
        r"\bprocessed[_ ]?data",
    ],
}


KEY_REFERENCE_PATTERNS = {
    "canonical_future_pick_inventory_file": (
        r"future_pick_optimizer_inventory_2027_2029_final"
    ),
    "future_pick_right_id": r"\bfuture_pick_right_id\b",
    "candidate_right_value_score": (
        r"\bcandidate_right_value_score\b"
    ),
    "standalone_trade_asset_flag": (
        r"\bstandalone_trade_asset_flag\b"
    ),
    "tradability_status": r"\btradability_status\b",
    "source_assets": r"\bsource_assets\b",
    "expected_pick_count": r"\bexpected_pick_count\b",
    "stepien": r"\bstepien\b",
    "frozen_pick": r"\bfrozen[_ ]?pick\b",
    "pick_ownership": (
        r"\bpick[_ ]?ownership\b|\bownership[_ ]?ledger\b"
    ),
    "trade_package": r"\btrade[_ ]?package\b",
    "player_asset": r"\bplayer[_ ]?asset\b",
    "salary_matching": r"\bsalary[_ ]?match",
    "candidate_generation": (
        r"\bgenerate[_ ]?candidates?\b"
        r"|\bcandidate[_ ]?generator\b"
    ),
    "trade_scoring": (
        r"\btrade[_ ]?score\b"
        r"|\bscore[_ ]?trade\b"
        r"|\bpackage[_ ]?score\b"
    ),
}


COLUMN_ACCESS_PATTERNS = [
    re.compile(
        r"""\[\s*["']([^"']+)["']\s*\]"""
    ),
    re.compile(
        r"""\.get\(\s*["']([^"']+)["']"""
    ),
    re.compile(
        r"""\.loc\[[^\]]*,\s*["']([^"']+)["']\s*\]"""
    ),
]


FILE_RELEVANCE_WEIGHTS = {
    "package_construction": 8.0,
    "candidate_generation": 7.0,
    "objective_scoring": 7.0,
    "salary_matching": 6.0,
    "cba_legality": 8.0,
    "player_asset_model": 5.0,
    "pick_asset_model": 8.0,
    "ownership_encumbrance": 6.0,
    "optimizer_orchestration": 5.0,
    "data_loading": 2.0,
}


SYMBOL_RELEVANCE_WEIGHTS = {
    "package_construction": 10.0,
    "candidate_generation": 9.0,
    "objective_scoring": 9.0,
    "salary_matching": 7.0,
    "cba_legality": 10.0,
    "player_asset_model": 6.0,
    "pick_asset_model": 9.0,
    "ownership_encumbrance": 8.0,
    "optimizer_orchestration": 6.0,
    "data_loading": 2.0,
}


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
        str(
            value
        ),
    ).strip()


def json_safe(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return {
            str(
                key
            ): json_safe(
                item
            )
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
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


def relative_path(
    path: Path,
) -> str:
    try:
        return str(
            path.relative_to(
                PROJECT_ROOT
            )
        )
    except ValueError:
        return str(
            path
        )


def safe_read_text(
    path: Path,
) -> str:
    for encoding in [
        "utf-8",
        "utf-8-sig",
        "cp1252",
    ]:
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


def discover_project_files() -> list[
    Path
]:
    files = []

    for directory in SOURCE_DIRECTORIES:
        if not directory.exists():
            continue

        for path in directory.rglob(
            "*"
        ):
            if not path.is_file():
                continue

            if "__pycache__" in path.parts:
                continue

            if path.suffix.lower() == PYTHON_EXTENSION:
                files.append(
                    path
                )
            elif path.suffix.lower() in CONFIG_EXTENSIONS:
                files.append(
                    path
                )

    return sorted(
        set(
            files
        )
    )


def match_categories(
    text: str,
) -> dict[
    str,
    int
]:
    lowered = text.lower()

    counts = {}

    for category, patterns in CATEGORY_PATTERNS.items():
        count = 0

        for pattern in patterns:
            count += len(
                re.findall(
                    pattern,
                    lowered,
                    flags=re.IGNORECASE,
                )
            )

        counts[
            category
        ] = int(
            count
        )

    return counts


def match_key_references(
    text: str,
) -> dict[
    str,
    int
]:
    return {
        name: int(
            len(
                re.findall(
                    pattern,
                    text,
                    flags=re.IGNORECASE,
                )
            )
        )
        for name, pattern in KEY_REFERENCE_PATTERNS.items()
    }


def category_score(
    counts: dict[
        str,
        int
    ],
    weights: dict[
        str,
        float
    ],
) -> float:
    return float(
        sum(
            min(
                count,
                10,
            )
            * weights.get(
                category,
                1.0,
            )
            for category, count in counts.items()
        )
    )


def dominant_categories(
    counts: dict[
        str,
        int
    ],
) -> str:
    ranked = sorted(
        [
            (
                category,
                count,
            )
            for category, count in counts.items()
            if count
            > 0
        ],
        key=lambda item: (
            -item[
                1
            ],
            item[
                0
            ],
        ),
    )

    return "|".join(
        category
        for category, _ in ranked[
            :5
        ]
    )


def source_segment(
    lines: list[
        str
    ],
    start_line: int,
    end_line: int,
) -> str:
    start_index = max(
        0,
        start_line
        - 1,
    )

    end_index = min(
        len(
            lines
        ),
        end_line,
    )

    return "\n".join(
        lines[
            start_index:end_index
        ]
    )


def ast_unparse_safe(
    node: ast.AST | None,
) -> str:
    if node is None:
        return ""

    try:
        return ast.unparse(
            node
        )
    except Exception:
        return ""


def function_arguments(
    node: ast.FunctionDef
    | ast.AsyncFunctionDef,
) -> list[
    str
]:
    args = []

    for argument in (
        list(
            node.args.posonlyargs
        )
        + list(
            node.args.args
        )
    ):
        args.append(
            argument.arg
        )

    if node.args.vararg is not None:
        args.append(
            "*"
            + node.args.vararg.arg
        )

    for argument in node.args.kwonlyargs:
        args.append(
            argument.arg
        )

    if node.args.kwarg is not None:
        args.append(
            "**"
            + node.args.kwarg.arg
        )

    return args


def extract_docstring(
    node: ast.AST,
) -> str:
    try:
        return clean_text(
            ast.get_docstring(
                node
            )
        )
    except TypeError:
        return ""


class SymbolVisitor(
    ast.NodeVisitor
):
    def __init__(
        self,
        *,
        path: Path,
        lines: list[
            str
        ],
    ) -> None:
        self.path = path
        self.lines = lines
        self.symbol_rows: list[
            dict[
                str,
                Any,
            ]
        ] = []
        self.import_rows: list[
            dict[
                str,
                Any,
            ]
        ] = []
        self.call_rows: list[
            dict[
                str,
                Any,
            ]
        ] = []
        self.scope_stack: list[
            str
        ] = []
        self.class_stack: list[
            str
        ] = []

    def current_scope(
        self,
    ) -> str:
        return ".".join(
            self.scope_stack
        )

    def add_symbol(
        self,
        *,
        node: ast.AST,
        symbol_type: str,
        name: str,
        arguments: list[
            str
        ],
    ) -> None:
        start_line = int(
            getattr(
                node,
                "lineno",
                1,
            )
        )

        end_line = int(
            getattr(
                node,
                "end_lineno",
                start_line,
            )
        )

        text = source_segment(
            self.lines,
            start_line,
            end_line,
        )

        categories = match_categories(
            text
        )

        key_references = match_key_references(
            text
        )

        self.symbol_rows.append(
            {
                "file_path": relative_path(
                    self.path
                ),
                "symbol_type": symbol_type,
                "symbol_name": name,
                "qualified_symbol_name": (
                    ".".join(
                        [
                            *self.class_stack,
                            name,
                        ]
                    )
                    if self.class_stack
                    else name
                ),
                "start_line": start_line,
                "end_line": end_line,
                "line_count": (
                    end_line
                    - start_line
                    + 1
                ),
                "arguments": "|".join(
                    arguments
                ),
                "argument_count": len(
                    arguments
                ),
                "docstring": extract_docstring(
                    node
                ),
                "dominant_categories": dominant_categories(
                    categories
                ),
                "relevance_score": category_score(
                    categories,
                    SYMBOL_RELEVANCE_WEIGHTS,
                ),
                **{
                    f"{category}_references": count
                    for category, count in categories.items()
                },
                **{
                    f"key_{name}_references": count
                    for name, count in key_references.items()
                },
            }
        )

    def visit_ClassDef(
        self,
        node: ast.ClassDef,
    ) -> None:
        self.add_symbol(
            node=node,
            symbol_type="class",
            name=node.name,
            arguments=[
                ast_unparse_safe(
                    base
                )
                for base in node.bases
            ],
        )

        self.class_stack.append(
            node.name
        )

        self.scope_stack.append(
            node.name
        )

        self.generic_visit(
            node
        )

        self.scope_stack.pop()
        self.class_stack.pop()

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:
        self.add_symbol(
            node=node,
            symbol_type="function",
            name=node.name,
            arguments=function_arguments(
                node
            ),
        )

        self.scope_stack.append(
            node.name
        )

        self.generic_visit(
            node
        )

        self.scope_stack.pop()

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self.add_symbol(
            node=node,
            symbol_type="async_function",
            name=node.name,
            arguments=function_arguments(
                node
            ),
        )

        self.scope_stack.append(
            node.name
        )

        self.generic_visit(
            node
        )

        self.scope_stack.pop()

    def visit_Import(
        self,
        node: ast.Import,
    ) -> None:
        for alias in node.names:
            self.import_rows.append(
                {
                    "file_path": relative_path(
                        self.path
                    ),
                    "line_number": int(
                        getattr(
                            node,
                            "lineno",
                            0,
                        )
                    ),
                    "import_type": "import",
                    "module_name": alias.name,
                    "imported_name": "",
                    "alias": clean_text(
                        alias.asname
                    ),
                    "scope": self.current_scope(),
                }
            )

        self.generic_visit(
            node
        )

    def visit_ImportFrom(
        self,
        node: ast.ImportFrom,
    ) -> None:
        module_name = (
            "." * int(
                node.level
            )
            + clean_text(
                node.module
            )
        )

        for alias in node.names:
            self.import_rows.append(
                {
                    "file_path": relative_path(
                        self.path
                    ),
                    "line_number": int(
                        getattr(
                            node,
                            "lineno",
                            0,
                        )
                    ),
                    "import_type": "from_import",
                    "module_name": module_name,
                    "imported_name": alias.name,
                    "alias": clean_text(
                        alias.asname
                    ),
                    "scope": self.current_scope(),
                }
            )

        self.generic_visit(
            node
        )

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:
        call_name = ast_unparse_safe(
            node.func
        )

        if call_name:
            self.call_rows.append(
                {
                    "file_path": relative_path(
                        self.path
                    ),
                    "line_number": int(
                        getattr(
                            node,
                            "lineno",
                            0,
                        )
                    ),
                    "caller_scope": self.current_scope(),
                    "called_expression": call_name,
                    "called_base_name": call_name.split(
                        "."
                    )[
                        -1
                    ],
                    "positional_argument_count": len(
                        node.args
                    ),
                    "keyword_argument_names": "|".join(
                        clean_text(
                            keyword.arg
                        )
                        for keyword in node.keywords
                        if keyword.arg is not None
                    ),
                }
            )

        self.generic_visit(
            node
        )


def scan_python_file(
    path: Path,
) -> tuple[
    dict[
        str,
        Any,
    ],
    list[
        dict[
            str,
            Any,
        ]
    ],
    list[
        dict[
            str,
            Any,
        ]
    ],
    list[
        dict[
            str,
            Any,
        ]
    ],
    list[
        dict[
            str,
            Any,
        ]
    ],
]:
    text = safe_read_text(
        path
    )

    lines = text.splitlines()

    categories = match_categories(
        text
    )

    key_references = match_key_references(
        text
    )

    syntax_valid = True
    syntax_error = ""

    symbol_rows = []
    import_rows = []
    call_rows = []

    try:
        tree = ast.parse(
            text,
            filename=str(
                path
            ),
        )

        visitor = SymbolVisitor(
            path=path,
            lines=lines,
        )

        visitor.visit(
            tree
        )

        symbol_rows = visitor.symbol_rows
        import_rows = visitor.import_rows
        call_rows = visitor.call_rows
    except SyntaxError as error:
        syntax_valid = False
        syntax_error = clean_text(
            error
        )

    column_rows = []

    seen_columns = set()

    for line_number, line in enumerate(
        lines,
        start=1,
    ):
        for pattern in COLUMN_ACCESS_PATTERNS:
            for match in pattern.finditer(
                line
            ):
                column_name = clean_text(
                    match.group(
                        1
                    )
                )

                if not column_name:
                    continue

                key = (
                    line_number,
                    column_name,
                )

                if key in seen_columns:
                    continue

                seen_columns.add(
                    key
                )

                column_rows.append(
                    {
                        "file_path": relative_path(
                            path
                        ),
                        "line_number": line_number,
                        "column_name": column_name,
                        "line_text": clean_text(
                            line
                        ),
                        "matches_canonical_inventory_column": bool(
                            column_name
                            in CANONICAL_INVENTORY_REQUIRED_COLUMNS
                        ),
                    }
                )

    file_row = {
        "file_path": relative_path(
            path
        ),
        "file_name": path.name,
        "file_extension": path.suffix.lower(),
        "line_count": len(
            lines
        ),
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "syntax_valid": syntax_valid,
        "syntax_error": syntax_error,
        "dominant_categories": dominant_categories(
            categories
        ),
        "relevance_score": category_score(
            categories,
            FILE_RELEVANCE_WEIGHTS,
        ),
        **{
            f"{category}_references": count
            for category, count in categories.items()
        },
        **{
            f"key_{name}_references": count
            for name, count in key_references.items()
        },
    }

    return (
        file_row,
        symbol_rows,
        import_rows,
        call_rows,
        column_rows,
    )


def scan_config_file(
    path: Path,
) -> dict[
    str,
    Any,
]:
    text = safe_read_text(
        path
    )

    lines = text.splitlines()

    categories = match_categories(
        text
    )

    key_references = match_key_references(
        text
    )

    return {
        "file_path": relative_path(
            path
        ),
        "file_name": path.name,
        "file_extension": path.suffix.lower(),
        "line_count": len(
            lines
        ),
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "syntax_valid": True,
        "syntax_error": "",
        "dominant_categories": dominant_categories(
            categories
        ),
        "relevance_score": category_score(
            categories,
            FILE_RELEVANCE_WEIGHTS,
        ),
        **{
            f"{category}_references": count
            for category, count in categories.items()
        },
        **{
            f"key_{name}_references": count
            for name, count in key_references.items()
        },
    }


def build_reference_catalog(
    files: list[
        Path
    ],
) -> pd.DataFrame:
    rows = []

    for path in files:
        text = safe_read_text(
            path
        )

        lines = text.splitlines()

        for reference_name, pattern in KEY_REFERENCE_PATTERNS.items():
            compiled = re.compile(
                pattern,
                flags=re.IGNORECASE,
            )

            for line_number, line in enumerate(
                lines,
                start=1,
            ):
                matches = list(
                    compiled.finditer(
                        line
                    )
                )

                if not matches:
                    continue

                rows.append(
                    {
                        "file_path": relative_path(
                            path
                        ),
                        "line_number": line_number,
                        "reference_name": reference_name,
                        "match_count_on_line": len(
                            matches
                        ),
                        "line_text": clean_text(
                            line
                        ),
                    }
                )

    return pd.DataFrame(
        rows
    )


def build_import_edges(
    import_rows: pd.DataFrame,
    project_files: list[
        Path
    ],
) -> pd.DataFrame:
    if import_rows.empty:
        return pd.DataFrame()

    module_lookup = {}

    for path in project_files:
        if path.suffix.lower() != ".py":
            continue

        relative = path.relative_to(
            PROJECT_ROOT
        )

        parts = list(
            relative.with_suffix(
                ""
            ).parts
        )

        if parts and parts[
            -1
        ] == "__init__":
            parts = parts[
                :-1
            ]

        module_name = ".".join(
            parts
        )

        module_lookup[
            module_name
        ] = relative_path(
            path
        )

        if parts and parts[
            0
        ] == "src":
            short_name = ".".join(
                parts[
                    1:
                ]
            )

            module_lookup[
                short_name
            ] = relative_path(
                path
            )

    output = import_rows.copy()

    resolved_paths = []

    for row in output.itertuples(
        index=False
    ):
        module_name = clean_text(
            row.module_name
        ).lstrip(
            "."
        )

        imported_name = clean_text(
            row.imported_name
        )

        candidates = [
            module_name,
        ]

        if imported_name:
            candidates.append(
                ".".join(
                    value
                    for value in [
                        module_name,
                        imported_name,
                    ]
                    if value
                )
            )

        resolved = ""

        for candidate in candidates:
            if candidate in module_lookup:
                resolved = module_lookup[
                    candidate
                ]
                break

        resolved_paths.append(
            resolved
        )

    output[
        "resolved_project_file"
    ] = resolved_paths

    output[
        "is_internal_project_import"
    ] = (
        output[
            "resolved_project_file"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .ne("")
    )

    return output


def build_call_edges(
    call_rows: pd.DataFrame,
    symbol_rows: pd.DataFrame,
) -> pd.DataFrame:
    if call_rows.empty:
        return pd.DataFrame()

    symbol_lookup = defaultdict(
        list
    )

    for row in symbol_rows.itertuples(
        index=False
    ):
        symbol_lookup[
            clean_text(
                row.symbol_name
            )
        ].append(
            (
                clean_text(
                    row.file_path
                ),
                clean_text(
                    row.qualified_symbol_name
                ),
            )
        )

    output_rows = []

    for row in call_rows.itertuples(
        index=False
    ):
        called_name = clean_text(
            row.called_base_name
        )

        matches = symbol_lookup.get(
            called_name,
            [],
        )

        if not matches:
            output_rows.append(
                {
                    **row._asdict(),
                    "resolved_target_file": "",
                    "resolved_target_symbol": "",
                    "resolution_status": "unresolved_or_external",
                }
            )
            continue

        resolution_status = (
            "resolved_unique"
            if len(
                matches
            )
            == 1
            else "resolved_ambiguous"
        )

        for target_file, target_symbol in matches:
            output_rows.append(
                {
                    **row._asdict(),
                    "resolved_target_file": target_file,
                    "resolved_target_symbol": target_symbol,
                    "resolution_status": resolution_status,
                }
            )

    return pd.DataFrame(
        output_rows
    )


def build_integration_candidates(
    file_catalog: pd.DataFrame,
    symbol_catalog: pd.DataFrame,
    reference_catalog: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    if not symbol_catalog.empty:
        for row in symbol_catalog.itertuples(
            index=False
        ):
            categories = clean_text(
                row.dominant_categories
            ).split(
                "|"
            )

            categories = [
                category
                for category in categories
                if category
            ]

            if not categories:
                continue

            interface_roles = []

            if (
                "package_construction"
                in categories
            ):
                interface_roles.append(
                    "package_asset_insertion"
                )

            if (
                "candidate_generation"
                in categories
            ):
                interface_roles.append(
                    "candidate_pool_expansion"
                )

            if (
                "objective_scoring"
                in categories
            ):
                interface_roles.append(
                    "asset_value_scoring"
                )

            if (
                "salary_matching"
                in categories
            ):
                interface_roles.append(
                    "salary_constraint_boundary"
                )

            if (
                "cba_legality"
                in categories
                or "ownership_encumbrance"
                in categories
            ):
                interface_roles.append(
                    "trade_legality_filter"
                )

            if (
                "player_asset_model"
                in categories
            ):
                interface_roles.append(
                    "player_pick_asset_unification"
                )

            if (
                "pick_asset_model"
                in categories
            ):
                interface_roles.append(
                    "existing_pick_asset_interface"
                )

            if (
                "optimizer_orchestration"
                in categories
            ):
                interface_roles.append(
                    "optimizer_entrypoint"
                )

            if not interface_roles:
                continue

            rows.append(
                {
                    "candidate_type": "symbol",
                    "file_path": row.file_path,
                    "symbol_name": row.qualified_symbol_name,
                    "start_line": row.start_line,
                    "end_line": row.end_line,
                    "interface_roles": "|".join(
                        sorted(
                            set(
                                interface_roles
                            )
                        )
                    ),
                    "dominant_categories": row.dominant_categories,
                    "relevance_score": float(
                        row.relevance_score
                    ),
                    "arguments": row.arguments,
                    "docstring": row.docstring,
                    "evidence_basis": (
                        "AST symbol body and name references"
                    ),
                }
            )

    if not file_catalog.empty:
        for row in file_catalog.itertuples(
            index=False
        ):
            if float(
                row.relevance_score
            ) <= 0:
                continue

            rows.append(
                {
                    "candidate_type": "file",
                    "file_path": row.file_path,
                    "symbol_name": "",
                    "start_line": np.nan,
                    "end_line": np.nan,
                    "interface_roles": "",
                    "dominant_categories": row.dominant_categories,
                    "relevance_score": float(
                        row.relevance_score
                    ),
                    "arguments": "",
                    "docstring": "",
                    "evidence_basis": (
                        "whole-file keyword and interface reference scan"
                    ),
                }
            )

    output = pd.DataFrame(
        rows
    )

    if output.empty:
        return output

    reference_counts = (
        reference_catalog.groupby(
            "file_path"
        )[
            "reference_name"
        ]
        .nunique()
        .to_dict()
        if not reference_catalog.empty
        else {}
    )

    output[
        "distinct_key_reference_types_in_file"
    ] = (
        output[
            "file_path"
        ]
        .map(
            reference_counts
        )
        .fillna(
            0
        )
        .astype(
            int
        )
    )

    output[
        "integration_priority_score"
    ] = (
        pd.to_numeric(
            output[
                "relevance_score"
            ],
            errors="coerce",
        ).fillna(
            0.0
        )
        + output[
            "distinct_key_reference_types_in_file"
        ]
        * 5.0
        + output[
            "candidate_type"
        ].eq(
            "symbol"
        ).astype(
            int
        )
        * 10.0
    )

    output[
        "integration_priority_rank"
    ] = (
        output[
            "integration_priority_score"
        ]
        .rank(
            method="dense",
            ascending=False,
        )
        .astype(
            int
        )
    )

    return output.sort_values(
        [
            "integration_priority_rank",
            "candidate_type",
            "file_path",
            "start_line",
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )


def build_pick_support_audit(
    file_catalog: pd.DataFrame,
    symbol_catalog: pd.DataFrame,
    reference_catalog: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    reference_summary = (
        reference_catalog.groupby(
            "reference_name"
        )
        .agg(
            reference_rows=(
                "line_number",
                "size",
            ),
            files_with_reference=(
                "file_path",
                "nunique",
            ),
        )
        .reset_index()
        if not reference_catalog.empty
        else pd.DataFrame(
            columns=[
                "reference_name",
                "reference_rows",
                "files_with_reference",
            ]
        )
    )

    reference_lookup = {
        clean_text(
            row.reference_name
        ): {
            "reference_rows": int(
                row.reference_rows
            ),
            "files_with_reference": int(
                row.files_with_reference
            ),
        }
        for row in reference_summary.itertuples(
            index=False
        )
    }

    pick_symbols = (
        symbol_catalog.loc[
            pd.to_numeric(
                symbol_catalog.get(
                    "pick_asset_model_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ]
        if not symbol_catalog.empty
        else pd.DataFrame()
    )

    categories = [
        (
            "canonical_inventory_file_consumed",
            "canonical_future_pick_inventory_file",
        ),
        (
            "future_pick_right_id_referenced",
            "future_pick_right_id",
        ),
        (
            "candidate_right_value_referenced",
            "candidate_right_value_score",
        ),
        (
            "standalone_trade_asset_flag_referenced",
            "standalone_trade_asset_flag",
        ),
        (
            "tradability_status_referenced",
            "tradability_status",
        ),
        (
            "source_assets_referenced",
            "source_assets",
        ),
        (
            "expected_pick_count_referenced",
            "expected_pick_count",
        ),
        (
            "stepien_logic_referenced",
            "stepien",
        ),
        (
            "frozen_pick_logic_referenced",
            "frozen_pick",
        ),
        (
            "pick_ownership_logic_referenced",
            "pick_ownership",
        ),
        (
            "trade_package_logic_referenced",
            "trade_package",
        ),
        (
            "candidate_generation_logic_referenced",
            "candidate_generation",
        ),
        (
            "trade_scoring_logic_referenced",
            "trade_scoring",
        ),
    ]

    for check_name, reference_name in categories:
        values = reference_lookup.get(
            reference_name,
            {
                "reference_rows": 0,
                "files_with_reference": 0,
            },
        )

        rows.append(
            {
                "check_name": check_name,
                "reference_name": reference_name,
                "reference_rows": values[
                    "reference_rows"
                ],
                "files_with_reference": values[
                    "files_with_reference"
                ],
                "support_present": bool(
                    values[
                        "reference_rows"
                    ]
                    > 0
                ),
            }
        )

    rows.append(
        {
            "check_name": "pick_related_symbols_present",
            "reference_name": "pick_asset_model",
            "reference_rows": int(
                len(
                    pick_symbols
                )
            ),
            "files_with_reference": int(
                pick_symbols[
                    "file_path"
                ].nunique()
            )
            if not pick_symbols.empty
            else 0,
            "support_present": bool(
                not pick_symbols.empty
            ),
        }
    )

    pick_files = (
        file_catalog.loc[
            pd.to_numeric(
                file_catalog.get(
                    "pick_asset_model_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ]
        if not file_catalog.empty
        else pd.DataFrame()
    )

    rows.append(
        {
            "check_name": "pick_related_files_present",
            "reference_name": "pick_asset_model",
            "reference_rows": int(
                len(
                    pick_files
                )
            ),
            "files_with_reference": int(
                len(
                    pick_files
                )
            ),
            "support_present": bool(
                not pick_files.empty
            ),
        }
    )

    return pd.DataFrame(
        rows
    )


def build_inventory_compatibility(
    column_references: pd.DataFrame,
) -> pd.DataFrame:
    if not CANONICAL_INVENTORY_PATH.exists():
        raise FileNotFoundError(
            "Canonical future-pick optimizer inventory was not found:\n"
            f"{CANONICAL_INVENTORY_PATH}"
        )

    inventory = pd.read_parquet(
        CANONICAL_INVENTORY_PATH
    )

    inventory_columns = set(
        str(
            column
        )
        for column in inventory.columns
    )

    reference_lookup = defaultdict(
        set
    )

    if not column_references.empty:
        for row in column_references.itertuples(
            index=False
        ):
            reference_lookup[
                clean_text(
                    row.column_name
                )
            ].add(
                clean_text(
                    row.file_path
                )
            )

    rows = []

    for column in CANONICAL_INVENTORY_REQUIRED_COLUMNS:
        files = sorted(
            reference_lookup.get(
                column,
                set(),
            )
        )

        rows.append(
            {
                "column_name": column,
                "present_in_canonical_inventory": bool(
                    column
                    in inventory_columns
                ),
                "referenced_anywhere_in_project_source": bool(
                    files
                ),
                "referencing_file_count": len(
                    files
                ),
                "referencing_files": "|".join(
                    files
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_readiness_audit(
    *,
    file_catalog: pd.DataFrame,
    symbol_catalog: pd.DataFrame,
    pick_support: pd.DataFrame,
    compatibility: pd.DataFrame,
    integration_candidates: pd.DataFrame,
) -> pd.DataFrame:
    syntax_failures = int(
        (
            ~file_catalog[
                "syntax_valid"
            ].fillna(
                False
            ).astype(
                bool
            )
        ).sum()
    )

    relevant_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "relevance_score",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    package_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "package_construction_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    candidate_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "candidate_generation_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    scoring_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "objective_scoring_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    legality_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "cba_legality_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    salary_symbols = int(
        (
            pd.to_numeric(
                symbol_catalog.get(
                    "salary_matching_references",
                    0,
                ),
                errors="coerce",
            ).fillna(
                0
            )
            > 0
        ).sum()
    )

    inventory_file_support = bool(
        pick_support.loc[
            pick_support[
                "check_name"
            ].eq(
                "canonical_inventory_file_consumed"
            ),
            "support_present",
        ].any()
    )

    inventory_id_support = bool(
        pick_support.loc[
            pick_support[
                "check_name"
            ].eq(
                "future_pick_right_id_referenced"
            ),
            "support_present",
        ].any()
    )

    legality_support = bool(
        pick_support.loc[
            pick_support[
                "check_name"
            ].isin(
                [
                    "stepien_logic_referenced",
                    "frozen_pick_logic_referenced",
                    "pick_ownership_logic_referenced",
                ]
            ),
            "support_present",
        ].any()
    )

    required_columns_present = bool(
        compatibility[
            "present_in_canonical_inventory"
        ].all()
    )

    integration_points_found = bool(
        not integration_candidates.empty
    )

    checks = [
        {
            "check_name": "project_python_syntax_valid",
            "observed_value": syntax_failures,
            "expected_value": 0,
            "passed": syntax_failures
            == 0,
            "blocking_for_integration": True,
        },
        {
            "check_name": "relevant_trade_symbols_found",
            "observed_value": relevant_symbols,
            "expected_value": ">0",
            "passed": relevant_symbols
            > 0,
            "blocking_for_integration": True,
        },
        {
            "check_name": "package_construction_symbols_found",
            "observed_value": package_symbols,
            "expected_value": ">0",
            "passed": package_symbols
            > 0,
            "blocking_for_integration": True,
        },
        {
            "check_name": "candidate_generation_symbols_found",
            "observed_value": candidate_symbols,
            "expected_value": ">0",
            "passed": candidate_symbols
            > 0,
            "blocking_for_integration": True,
        },
        {
            "check_name": "objective_scoring_symbols_found",
            "observed_value": scoring_symbols,
            "expected_value": ">0",
            "passed": scoring_symbols
            > 0,
            "blocking_for_integration": True,
        },
        {
            "check_name": "salary_matching_symbols_found",
            "observed_value": salary_symbols,
            "expected_value": ">0",
            "passed": salary_symbols
            > 0,
            "blocking_for_integration": False,
        },
        {
            "check_name": "cba_legality_symbols_found",
            "observed_value": legality_symbols,
            "expected_value": ">0",
            "passed": legality_symbols
            > 0,
            "blocking_for_integration": False,
        },
        {
            "check_name": "canonical_inventory_file_already_consumed",
            "observed_value": inventory_file_support,
            "expected_value": True,
            "passed": inventory_file_support,
            "blocking_for_integration": False,
        },
        {
            "check_name": "future_pick_right_id_already_consumed",
            "observed_value": inventory_id_support,
            "expected_value": True,
            "passed": inventory_id_support,
            "blocking_for_integration": False,
        },
        {
            "check_name": "pick_legality_support_present",
            "observed_value": legality_support,
            "expected_value": True,
            "passed": legality_support,
            "blocking_for_integration": False,
        },
        {
            "check_name": "canonical_inventory_required_columns_present",
            "observed_value": int(
                compatibility[
                    "present_in_canonical_inventory"
                ].sum()
            ),
            "expected_value": int(
                len(
                    compatibility
                )
            ),
            "passed": required_columns_present,
            "blocking_for_integration": True,
        },
        {
            "check_name": "integration_candidate_interfaces_identified",
            "observed_value": int(
                len(
                    integration_candidates
                )
            ),
            "expected_value": ">0",
            "passed": integration_points_found,
            "blocking_for_integration": True,
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
    print("OPTIMIZER TRADE INTERFACE AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    project_files = discover_project_files()

    if not project_files:
        raise RuntimeError(
            "No Python or configuration files were found under src or "
            "tests."
        )

    file_rows = []
    symbol_rows = []
    import_rows = []
    call_rows = []
    column_rows = []

    for path in project_files:
        if path.suffix.lower() == PYTHON_EXTENSION:
            (
                file_row,
                path_symbol_rows,
                path_import_rows,
                path_call_rows,
                path_column_rows,
            ) = scan_python_file(
                path
            )

            file_rows.append(
                file_row
            )

            symbol_rows.extend(
                path_symbol_rows
            )

            import_rows.extend(
                path_import_rows
            )

            call_rows.extend(
                path_call_rows
            )

            column_rows.extend(
                path_column_rows
            )
        else:
            file_rows.append(
                scan_config_file(
                    path
                )
            )

    file_catalog = pd.DataFrame(
        file_rows
    ).sort_values(
        [
            "relevance_score",
            "file_path",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    symbol_catalog = pd.DataFrame(
        symbol_rows
    )

    if not symbol_catalog.empty:
        symbol_catalog = symbol_catalog.sort_values(
            [
                "relevance_score",
                "file_path",
                "start_line",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        ).reset_index(
            drop=True
        )

    raw_imports = pd.DataFrame(
        import_rows
    )

    raw_calls = pd.DataFrame(
        call_rows
    )

    column_references = pd.DataFrame(
        column_rows
    )

    if not column_references.empty:
        column_references = column_references.sort_values(
            [
                "matches_canonical_inventory_column",
                "column_name",
                "file_path",
                "line_number",
            ],
            ascending=[
                False,
                True,
                True,
                True,
            ],
        ).reset_index(
            drop=True
        )

    reference_catalog = build_reference_catalog(
        project_files
    )

    if not reference_catalog.empty:
        reference_catalog = reference_catalog.sort_values(
            [
                "reference_name",
                "file_path",
                "line_number",
            ]
        ).reset_index(
            drop=True
        )

    import_edges = build_import_edges(
        raw_imports,
        project_files,
    )

    if not import_edges.empty:
        import_edges = import_edges.sort_values(
            [
                "is_internal_project_import",
                "file_path",
                "line_number",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        ).reset_index(
            drop=True
        )

    call_edges = build_call_edges(
        raw_calls,
        symbol_catalog,
    )

    if not call_edges.empty:
        call_edges = call_edges.sort_values(
            [
                "resolution_status",
                "file_path",
                "line_number",
            ]
        ).reset_index(
            drop=True
        )

    integration_candidates = build_integration_candidates(
        file_catalog=file_catalog,
        symbol_catalog=symbol_catalog,
        reference_catalog=reference_catalog,
    )

    pick_support = build_pick_support_audit(
        file_catalog=file_catalog,
        symbol_catalog=symbol_catalog,
        reference_catalog=reference_catalog,
    )

    compatibility = build_inventory_compatibility(
        column_references
    )

    readiness = build_readiness_audit(
        file_catalog=file_catalog,
        symbol_catalog=symbol_catalog,
        pick_support=pick_support,
        compatibility=compatibility,
        integration_candidates=integration_candidates,
    )

    file_catalog.to_csv(
        FILE_CATALOG_PATH,
        index=False,
    )

    symbol_catalog.to_csv(
        SYMBOL_CATALOG_PATH,
        index=False,
    )

    reference_catalog.to_csv(
        REFERENCE_CATALOG_PATH,
        index=False,
    )

    column_references.to_csv(
        COLUMN_REFERENCE_PATH,
        index=False,
    )

    import_edges.to_csv(
        IMPORT_EDGE_PATH,
        index=False,
    )

    call_edges.to_csv(
        CALL_EDGE_PATH,
        index=False,
    )

    integration_candidates.to_csv(
        INTEGRATION_CANDIDATE_PATH,
        index=False,
    )

    pick_support.to_csv(
        PICK_SUPPORT_PATH,
        index=False,
    )

    compatibility.to_csv(
        CANONICAL_INVENTORY_COMPATIBILITY_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    syntax_failures = file_catalog.loc[
        ~file_catalog[
            "syntax_valid"
        ]
    ]

    top_files = file_catalog.loc[
        file_catalog[
            "relevance_score"
        ]
        > 0
    ].head(
        15
    )

    top_symbols = (
        symbol_catalog.loc[
            symbol_catalog[
                "relevance_score"
            ]
            > 0
        ].head(
            20
        )
        if not symbol_catalog.empty
        else pd.DataFrame()
    )

    blocking_failures = readiness.loc[
        readiness[
            "blocking_for_integration"
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
        "project_root": str(
            PROJECT_ROOT
        ),
        "project_files_scanned": int(
            len(
                project_files
            )
        ),
        "python_files_scanned": int(
            sum(
                path.suffix.lower()
                == PYTHON_EXTENSION
                for path in project_files
            )
        ),
        "config_files_scanned": int(
            sum(
                path.suffix.lower()
                in CONFIG_EXTENSIONS
                for path in project_files
            )
        ),
        "syntax_failures": int(
            len(
                syntax_failures
            )
        ),
        "symbols_found": int(
            len(
                symbol_catalog
            )
        ),
        "relevant_symbols": int(
            (
                pd.to_numeric(
                    symbol_catalog.get(
                        "relevance_score",
                        0,
                    ),
                    errors="coerce",
                ).fillna(
                    0
                )
                > 0
            ).sum()
        ),
        "references_found": int(
            len(
                reference_catalog
            )
        ),
        "column_references_found": int(
            len(
                column_references
            )
        ),
        "internal_import_edges": int(
            import_edges[
                "is_internal_project_import"
            ].sum()
        )
        if not import_edges.empty
        else 0,
        "resolved_call_edges": int(
            call_edges[
                "resolution_status"
            ]
            .fillna("")
            .astype(str)
            .str.startswith(
                "resolved_"
            )
            .sum()
        )
        if not call_edges.empty
        else 0,
        "integration_candidates": int(
            len(
                integration_candidates
            )
        ),
        "readiness_checks": int(
            len(
                readiness
            )
        ),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "blocking_readiness_failures": int(
            len(
                blocking_failures
            )
        ),
        "automatic_integration_ready": bool(
            blocking_failures.empty
        ),
        "canonical_inventory_path": str(
            CANONICAL_INVENTORY_PATH
        ),
        "important_constraint": (
            "This audit identifies software interfaces only. It does "
            "not certify that any future-pick right is legally tradable "
            "on a particular date."
        ),
        "output_files": {
            "file_catalog": str(
                FILE_CATALOG_PATH
            ),
            "symbol_catalog": str(
                SYMBOL_CATALOG_PATH
            ),
            "reference_catalog": str(
                REFERENCE_CATALOG_PATH
            ),
            "column_reference_audit": str(
                COLUMN_REFERENCE_PATH
            ),
            "import_edges": str(
                IMPORT_EDGE_PATH
            ),
            "call_edges": str(
                CALL_EDGE_PATH
            ),
            "integration_candidates": str(
                INTEGRATION_CANDIDATE_PATH
            ),
            "existing_pick_support": str(
                PICK_SUPPORT_PATH
            ),
            "inventory_compatibility": str(
                CANONICAL_INVENTORY_COMPATIBILITY_PATH
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
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print("=" * 80)
    print("OPTIMIZER TRADE INTERFACE AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Project files scanned: "
        f"{len(project_files):,}"
    )
    print(
        "Python files scanned: "
        f"{metadata['python_files_scanned']:,}"
    )
    print(
        "Configuration files scanned: "
        f"{metadata['config_files_scanned']:,}"
    )
    print(
        "Python syntax failures: "
        f"{len(syntax_failures):,}"
    )
    print(
        "Symbols found: "
        f"{len(symbol_catalog):,}"
    )
    print(
        "Relevant trade or optimizer symbols: "
        f"{metadata['relevant_symbols']:,}"
    )
    print(
        "Key interface references found: "
        f"{len(reference_catalog):,}"
    )
    print(
        "Integration candidates identified: "
        f"{len(integration_candidates):,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Blocking readiness failures: "
        f"{len(blocking_failures):,}"
    )
    print(
        "Automatic integration ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("TOP RELEVANT FILES")

    if top_files.empty:
        print(
            "No relevant trade or optimizer files were detected."
        )
    else:
        print(
            top_files[
                [
                    "file_path",
                    "relevance_score",
                    "dominant_categories",
                    "package_construction_references",
                    "candidate_generation_references",
                    "objective_scoring_references",
                    "salary_matching_references",
                    "cba_legality_references",
                    "pick_asset_model_references",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("TOP RELEVANT SYMBOLS")

    if top_symbols.empty:
        print(
            "No relevant trade or optimizer symbols were detected."
        )
    else:
        print(
            top_symbols[
                [
                    "file_path",
                    "qualified_symbol_name",
                    "symbol_type",
                    "start_line",
                    "end_line",
                    "relevance_score",
                    "dominant_categories",
                    "arguments",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("EXISTING PICK SUPPORT")
    print(
        pick_support.to_string(
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
        FILE_CATALOG_PATH,
        SYMBOL_CATALOG_PATH,
        REFERENCE_CATALOG_PATH,
        COLUMN_REFERENCE_PATH,
        IMPORT_EDGE_PATH,
        CALL_EDGE_PATH,
        INTEGRATION_CANDIDATE_PATH,
        PICK_SUPPORT_PATH,
        CANONICAL_INVENTORY_COMPATIBILITY_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()
