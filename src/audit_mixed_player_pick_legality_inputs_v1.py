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
    "mixed-player-pick-legality-input-audit-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

ONE_FOR_ONE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_mixed_player_pick_candidates_2026_27_v3.parquet"
)

TWO_FOR_ONE_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_mixed_player_pick_candidates_2026_27_v3.parquet"
)

SOURCE_CATALOG_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_legality_source_catalog_v1.csv"
)

CONCEPT_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_legality_concept_coverage_v1.csv"
)

RIGHT_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_right_legality_coverage_v1.csv"
)

PACKAGE_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_package_legality_coverage_v1.csv"
)

MISSING_INPUT_ACTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_legality_missing_input_actions_v1.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_legality_readiness_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_legality_audit_metadata_v1.json"
)


EXPECTED_PICK_ROWS = 174
EXPECTED_STANDALONE_PICK_ROWS = 172
EXPECTED_ONE_FOR_ONE_CANDIDATE_ROWS = 28324
EXPECTED_TWO_FOR_ONE_CANDIDATE_ROWS = 282277

SUPPORTED_SUFFIXES = {
    ".csv",
    ".parquet",
    ".json",
}

EXCLUDED_FILE_PREFIXES = (
    "mixed_player_pick_legality_",
    "optimizer_trade_interface_",
    "optimizer_runtime_",
)

EXCLUDED_FILE_NAMES = {
    ONE_FOR_ONE_CANDIDATES_PATH.name.lower(),
    TWO_FOR_ONE_CANDIDATES_PATH.name.lower(),
}

DISCOVERY_KEYWORDS = {
    "ownership": [
        "ownership",
        "owner",
        "owned_by",
        "candidate_team",
        "current_team",
        "beneficiary",
    ],
    "obligation": [
        "obligation",
        "ledger",
        "claim",
        "dependency",
        "source_assets",
        "originating_team",
    ],
    "protection": [
        "protection",
        "protected",
        "lottery",
        "top_",
        "fallback",
        "rollover",
        "conditional",
    ],
    "stepien": [
        "stepien",
        "consecutive_first",
        "future_first",
        "first_round_availability",
    ],
    "frozen_pick": [
        "frozen_pick",
        "frozen",
        "second_apron",
        "apron_frozen",
    ],
    "encumbrance": [
        "encumbrance",
        "encumbered",
        "committed",
        "pledged",
        "swap",
        "convey",
        "transfer",
    ],
    "trade_date": [
        "trade_date",
        "effective_date",
        "as_of_date",
        "snapshot_date",
        "transaction_date",
    ],
    "tradability": [
        "tradability",
        "tradable",
        "trade_asset",
        "standalone_trade_asset",
        "legal_status",
    ],
    "pick_identity": [
        "future_pick_right_id",
        "asset_key",
        "pick_id",
        "draft_year",
        "round_number",
        "source_asset",
    ],
}

REQUIRED_LEGALITY_CONCEPTS = [
    "pick_identity",
    "ownership",
    "obligation",
    "protection",
    "tradability",
    "trade_date",
    "encumbrance",
    "stepien",
    "frozen_pick",
]

INVENTORY_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "standalone_trade_asset_flag",
    "tradability_status",
    "right_structure",
    "source_assets",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "originating_teams",
    "candidate_right_value_score",
]

PACKAGE_REQUIRED_COLUMNS = [
    "optimizer_candidate_id",
    "optimizer_branch",
    "attached_pick_right_id",
    "attached_pick_team",
    "optimizer_package_legality_status",
    "optimizer_package_final_legal",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


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


def parse_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

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


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required {label} was not found:\n{path}"
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
            + "\n".join(missing)
        )


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def file_is_excluded(path: Path) -> bool:
    name = path.name.lower()

    if name in EXCLUDED_FILE_NAMES:
        return True

    if name.startswith(EXCLUDED_FILE_PREFIXES):
        return True

    return False


def read_schema(path: Path) -> tuple[list[str], int | None]:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        columns = list(
            pd.read_csv(
                path,
                nrows=0,
            ).columns
        )

        row_count = None

        try:
            with path.open(
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as file:
                row_count = max(
                    sum(1 for _ in file) - 1,
                    0,
                )
        except OSError:
            pass

        return columns, row_count

    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq

            parquet_file = pq.ParquetFile(path)

            return (
                [
                    field.name
                    for field in parquet_file.schema_arrow
                ],
                int(parquet_file.metadata.num_rows),
            )
        except ImportError:
            frame = pd.read_parquet(path)

            return (
                list(frame.columns),
                int(len(frame)),
            )

    if suffix == ".json":
        payload = json.loads(
            path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )

        if isinstance(payload, dict):
            return list(payload.keys()), 1

        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict):
                return list(payload[0].keys()), len(payload)

            return [], len(payload)

        return [], 1

    raise ValueError(
        f"Unsupported file type: {path}"
    )


def concept_hits(
    file_name: str,
    columns: list[str],
) -> dict[str, list[str]]:
    searchable_name = normalize_name(file_name)
    normalized_columns = {
        normalize_name(column): str(column)
        for column in columns
    }

    hits: dict[str, list[str]] = {}

    for concept, keywords in DISCOVERY_KEYWORDS.items():
        concept_hits_list = []

        for keyword in keywords:
            normalized_keyword = normalize_name(keyword)

            if normalized_keyword in searchable_name:
                concept_hits_list.append(
                    f"filename:{keyword}"
                )

            for normalized_column, original_column in (
                normalized_columns.items()
            ):
                if normalized_keyword in normalized_column:
                    concept_hits_list.append(
                        f"column:{original_column}"
                    )

        hits[concept] = sorted(
            set(concept_hits_list)
        )

    return hits


def discover_legality_sources() -> pd.DataFrame:
    candidate_paths = []

    for root in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        if not root.exists():
            continue

        for path in root.iterdir():
            if not path.is_file():
                continue

            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue

            if file_is_excluded(path):
                continue

            candidate_paths.append(path)

    rows = []

    for index, path in enumerate(
        sorted(candidate_paths),
        start=1,
    ):
        if index % 25 == 0 or index == 1:
            print(
                f"  Scanning legality source {index:,}/"
                f"{len(candidate_paths):,}: {relative_path(path)}"
            )

        try:
            columns, row_count = read_schema(path)
            hits = concept_hits(
                path.name,
                columns,
            )

            total_hits = sum(
                len(values)
                for values in hits.values()
            )

            if total_hits <= 0:
                continue

            rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(path),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "file_size_bytes": int(path.stat().st_size),
                    "row_count": row_count,
                    "column_count": len(columns),
                    "concept_hit_count": total_hits,
                    "concepts_detected": "|".join(
                        concept
                        for concept, values in hits.items()
                        if values
                    ),
                    **{
                        f"{concept}_hits": "|".join(values)
                        for concept, values in hits.items()
                    },
                    "inspection_passed": True,
                    "inspection_error": "",
                }
            )
        except Exception as error:
            rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(path),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "file_size_bytes": int(path.stat().st_size),
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "concept_hit_count": 0,
                    "concepts_detected": "",
                    **{
                        f"{concept}_hits": ""
                        for concept in DISCOVERY_KEYWORDS
                    },
                    "inspection_passed": False,
                    "inspection_error": clean_text(error),
                }
            )

    output = pd.DataFrame(rows)

    if output.empty:
        return output

    return output.sort_values(
        [
            "inspection_passed",
            "concept_hit_count",
            "relative_file_path",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def build_concept_coverage(
    sources: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for concept in REQUIRED_LEGALITY_CONCEPTS:
        hit_column = f"{concept}_hits"

        if sources.empty or hit_column not in sources.columns:
            matched = pd.DataFrame()
        else:
            matched = sources.loc[
                sources[
                    "inspection_passed"
                ].fillna(False).astype(bool)
                & sources[
                    hit_column
                ].fillna("")
                .astype(str)
                .ne("")
            ].copy()

        data_processed_matches = (
            matched[
                "relative_file_path"
            ]
            .fillna("")
            .astype(str)
            .str.startswith(
                str(
                    PROCESSED_DIRECTORY.relative_to(
                        PROJECT_ROOT
                    )
                )
            )
            .sum()
            if not matched.empty
            else 0
        )

        rows.append(
            {
                "legality_concept": concept,
                "source_files_found": int(len(matched)),
                "processed_data_sources_found": int(
                    data_processed_matches
                ),
                "source_files": "|".join(
                    matched[
                        "relative_file_path"
                    ]
                    .head(30)
                    .tolist()
                ),
                "example_hits": "|".join(
                    matched[
                        hit_column
                    ]
                    .head(10)
                    .tolist()
                ),
                "concept_source_present": bool(
                    len(matched) > 0
                ),
                "processed_source_present": bool(
                    data_processed_matches > 0
                ),
                "automatic_validation_source_ready": bool(
                    data_processed_matches > 0
                ),
            }
        )

    return pd.DataFrame(rows)


def classify_inventory_structure(
    row: pd.Series,
) -> dict[str, Any]:
    searchable = " ".join(
        [
            clean_text(
                row.get(
                    "right_structure",
                    "",
                )
            ),
            clean_text(
                row.get(
                    "right_display_name",
                    "",
                )
            ),
            clean_text(
                row.get(
                    "tradability_status",
                    "",
                )
            ),
            clean_text(
                row.get(
                    "source_assets",
                    "",
                )
            ),
        ]
    ).lower()

    conditional = bool(
        any(
            token in searchable
            for token in [
                "conditional",
                "protected",
                "protection",
                "fallback",
                "rollover",
                "if ",
            ]
        )
    )

    swap = bool(
        "swap" in searchable
    )

    multi_source = bool(
        "|" in clean_text(
            row.get(
                "source_assets",
                "",
            )
        )
        or int(
            pd.to_numeric(
                pd.Series(
                    [
                        row.get(
                            "source_asset_count",
                            1,
                        )
                    ]
                ),
                errors="coerce",
            ).fillna(1).iloc[0]
        )
        > 1
    )

    return {
        "conditional_or_protected_flag": conditional,
        "swap_or_favorability_flag": swap,
        "multi_source_right_flag": multi_source,
        "complex_structure_flag": bool(
            conditional
            or swap
            or multi_source
        ),
    }


def build_right_coverage(
    inventory: pd.DataFrame,
    concept_coverage: pd.DataFrame,
) -> pd.DataFrame:
    standalone = inventory.loc[
        parse_bool_series(
            inventory[
                "standalone_trade_asset_flag"
            ]
        )
    ].copy()

    concept_lookup = (
        concept_coverage.set_index(
            "legality_concept"
        )[
            "automatic_validation_source_ready"
        ]
        .to_dict()
    )

    structural_rows = standalone.apply(
        classify_inventory_structure,
        axis=1,
        result_type="expand",
    )

    output = pd.concat(
        [
            standalone.reset_index(drop=True),
            structural_rows.reset_index(drop=True),
        ],
        axis=1,
    )

    output[
        "identity_fields_complete"
    ] = (
        output[
            "future_pick_right_id"
        ]
        .fillna("")
        .astype(str)
        .ne("")
        & output[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .ne("")
        & output[
            "draft_year_min"
        ].notna()
        & output[
            "round_numbers"
        ]
        .fillna("")
        .astype(str)
        .ne("")
    )

    output[
        "source_assets_present"
    ] = (
        output[
            "source_assets"
        ]
        .fillna("")
        .astype(str)
        .ne("")
    )

    output[
        "structure_terms_present"
    ] = (
        output[
            "right_structure"
        ]
        .fillna("")
        .astype(str)
        .ne("")
    )

    output[
        "tradability_status_present"
    ] = (
        output[
            "tradability_status"
        ]
        .fillna("")
        .astype(str)
        .ne("")
    )

    output[
        "ownership_source_available"
    ] = bool(
        concept_lookup.get(
            "ownership",
            False,
        )
    )

    output[
        "obligation_source_available"
    ] = bool(
        concept_lookup.get(
            "obligation",
            False,
        )
    )

    output[
        "protection_source_available"
    ] = bool(
        concept_lookup.get(
            "protection",
            False,
        )
    )

    output[
        "trade_date_source_available"
    ] = bool(
        concept_lookup.get(
            "trade_date",
            False,
        )
    )

    output[
        "encumbrance_source_available"
    ] = bool(
        concept_lookup.get(
            "encumbrance",
            False,
        )
    )

    output[
        "stepien_source_available"
    ] = bool(
        concept_lookup.get(
            "stepien",
            False,
        )
    )

    output[
        "frozen_pick_source_available"
    ] = bool(
        concept_lookup.get(
            "frozen_pick",
            False,
        )
    )

    required_flags = [
        "identity_fields_complete",
        "source_assets_present",
        "structure_terms_present",
        "tradability_status_present",
        "ownership_source_available",
        "obligation_source_available",
        "protection_source_available",
        "trade_date_source_available",
        "encumbrance_source_available",
        "stepien_source_available",
        "frozen_pick_source_available",
    ]

    output[
        "legality_input_checks_passed"
    ] = output[
        required_flags
    ].sum(
        axis=1
    )

    output[
        "legality_input_checks_required"
    ] = len(
        required_flags
    )

    output[
        "automatic_pick_legality_ready"
    ] = output[
        required_flags
    ].all(
        axis=1
    )

    output[
        "legality_readiness_status"
    ] = np.where(
        output[
            "automatic_pick_legality_ready"
        ],
        "automatic_validation_inputs_complete",
        "blocked_missing_trade_date_legality_inputs",
    )

    output[
        "missing_legality_inputs"
    ] = output.apply(
        lambda row: "|".join(
            flag.replace(
                "_source_available",
                "",
            ).replace(
                "_present",
                "",
            ).replace(
                "_complete",
                "",
            )
            for flag in required_flags
            if not bool(row[flag])
        ),
        axis=1,
    )

    selected_columns = [
        "future_pick_right_id",
        "candidate_team",
        "right_display_name",
        "right_structure",
        "source_assets",
        "draft_year_min",
        "draft_year_max",
        "round_numbers",
        "originating_teams",
        "candidate_right_value_score",
        "tradability_status",
        "conditional_or_protected_flag",
        "swap_or_favorability_flag",
        "multi_source_right_flag",
        "complex_structure_flag",
        *required_flags,
        "legality_input_checks_passed",
        "legality_input_checks_required",
        "automatic_pick_legality_ready",
        "legality_readiness_status",
        "missing_legality_inputs",
    ]

    return output[
        [
            column
            for column in selected_columns
            if column in output.columns
        ]
    ].sort_values(
        [
            "automatic_pick_legality_ready",
            "complex_structure_flag",
            "candidate_team",
            "future_pick_right_id",
        ],
        ascending=[
            True,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_package_coverage(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
    right_coverage: pd.DataFrame,
) -> pd.DataFrame:
    combined = pd.concat(
        [
            one_for_one[
                PACKAGE_REQUIRED_COLUMNS
            ],
            two_for_one[
                PACKAGE_REQUIRED_COLUMNS
            ],
        ],
        ignore_index=True,
        sort=False,
    )

    right_columns = [
        "future_pick_right_id",
        "automatic_pick_legality_ready",
        "legality_readiness_status",
        "missing_legality_inputs",
        "complex_structure_flag",
    ]

    output = combined.merge(
        right_coverage[
            right_columns
        ],
        how="left",
        left_on="attached_pick_right_id",
        right_on="future_pick_right_id",
        validate="many_to_one",
    )

    output[
        "pick_right_matched_to_inventory"
    ] = output[
        "future_pick_right_id"
    ].notna()

    output[
        "package_automatic_legality_ready"
    ] = (
        output[
            "pick_right_matched_to_inventory"
        ]
        & output[
            "automatic_pick_legality_ready"
        ].fillna(False)
    )

    output[
        "package_legality_audit_status"
    ] = np.where(
        output[
            "package_automatic_legality_ready"
        ],
        "ready_for_automatic_pick_legality_evaluation",
        "blocked_pending_pick_legality_inputs",
    )

    return output[
        [
            "optimizer_candidate_id",
            "optimizer_branch",
            "attached_pick_right_id",
            "attached_pick_team",
            "pick_right_matched_to_inventory",
            "complex_structure_flag",
            "automatic_pick_legality_ready",
            "package_automatic_legality_ready",
            "package_legality_audit_status",
            "missing_legality_inputs",
            "optimizer_package_legality_status",
            "optimizer_package_final_legal",
        ]
    ].sort_values(
        [
            "package_automatic_legality_ready",
            "optimizer_branch",
            "optimizer_candidate_id",
        ],
        ascending=[
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)


def build_missing_actions(
    concept_coverage: pd.DataFrame,
) -> pd.DataFrame:
    action_map = {
        "pick_identity": (
            "Maintain a canonical source-asset identifier, year, round, "
            "originating team, and right identifier for every tradable right."
        ),
        "ownership": (
            "Create a dated pick-ownership snapshot keyed by source asset "
            "and owning team."
        ),
        "obligation": (
            "Create or confirm a canonical obligation ledger linking each "
            "source pick to every active conveyance, swap, fallback, and pool."
        ),
        "protection": (
            "Normalize protection thresholds, rollover years, fallback terms, "
            "and exhaustion rules into machine-readable columns."
        ),
        "tradability": (
            "Define whether each candidate right is independently tradable "
            "rather than only an accounting allocation."
        ),
        "trade_date": (
            "Add an as-of date and effective-date range to ownership and "
            "obligation records."
        ),
        "encumbrance": (
            "Create a source-pick encumbrance table showing all overlapping "
            "claims, swaps, conveyances, and conditional commitments."
        ),
        "stepien": (
            "Build a team-year first-round availability calendar for Stepien "
            "testing after applying the proposed outgoing first-round rights."
        ),
        "frozen_pick": (
            "Add second-apron frozen-pick status and the season in which a "
            "frozen pick may or may not be traded."
        ),
    }

    rows = []

    for row in concept_coverage.itertuples(index=False):
        rows.append(
            {
                "legality_concept": row.legality_concept,
                "automatic_validation_source_ready": bool(
                    row.automatic_validation_source_ready
                ),
                "processed_data_sources_found": int(
                    row.processed_data_sources_found
                ),
                "source_files": row.source_files,
                "recommended_action": (
                    "No new source required by this audit. Review the matched "
                    "source for authority and row-level completeness."
                    if bool(
                        row.automatic_validation_source_ready
                    )
                    else action_map[
                        row.legality_concept
                    ]
                ),
                "action_priority": (
                    2
                    if bool(
                        row.automatic_validation_source_ready
                    )
                    else 1
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        [
            "action_priority",
            "legality_concept",
        ]
    ).reset_index(drop=True)


def build_readiness(
    inventory: pd.DataFrame,
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
    sources: pd.DataFrame,
    concept_coverage: pd.DataFrame,
    right_coverage: pd.DataFrame,
    package_coverage: pd.DataFrame,
) -> pd.DataFrame:
    concept_ready = concept_coverage.set_index(
        "legality_concept"
    )[
        "automatic_validation_source_ready"
    ].to_dict()

    missing_package_matches = int(
        (
            ~package_coverage[
                "pick_right_matched_to_inventory"
            ]
        ).sum()
    )

    incorrectly_final_legal = int(
        parse_bool_series(
            package_coverage[
                "optimizer_package_final_legal"
            ]
        ).sum()
    )

    checks = [
        {
            "check_name": "canonical_pick_inventory_rows",
            "observed_value": len(inventory),
            "expected_value": EXPECTED_PICK_ROWS,
            "passed": len(inventory) == EXPECTED_PICK_ROWS,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "standalone_pick_right_rows",
            "observed_value": len(right_coverage),
            "expected_value": EXPECTED_STANDALONE_PICK_ROWS,
            "passed": (
                len(right_coverage)
                == EXPECTED_STANDALONE_PICK_ROWS
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "one_for_one_candidate_rows",
            "observed_value": len(one_for_one),
            "expected_value": (
                EXPECTED_ONE_FOR_ONE_CANDIDATE_ROWS
            ),
            "passed": (
                len(one_for_one)
                == EXPECTED_ONE_FOR_ONE_CANDIDATE_ROWS
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "two_for_one_candidate_rows",
            "observed_value": len(two_for_one),
            "expected_value": (
                EXPECTED_TWO_FOR_ONE_CANDIDATE_ROWS
            ),
            "passed": (
                len(two_for_one)
                == EXPECTED_TWO_FOR_ONE_CANDIDATE_ROWS
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "candidate_pick_rights_match_inventory",
            "observed_value": missing_package_matches,
            "expected_value": 0,
            "passed": missing_package_matches == 0,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "pick_packages_not_preapproved_legal",
            "observed_value": incorrectly_final_legal,
            "expected_value": 0,
            "passed": incorrectly_final_legal == 0,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "legality_source_files_discovered",
            "observed_value": len(sources),
            "expected_value": ">0",
            "passed": len(sources) > 0,
            "blocking_for_legality_engine": True,
        },
    ]

    for concept in REQUIRED_LEGALITY_CONCEPTS:
        ready = bool(
            concept_ready.get(
                concept,
                False,
            )
        )

        checks.append(
            {
                "check_name": (
                    f"{concept}_processed_source_ready"
                ),
                "observed_value": ready,
                "expected_value": True,
                "passed": ready,
                "blocking_for_legality_engine": True,
            }
        )

    all_rights_ready = bool(
        right_coverage[
            "automatic_pick_legality_ready"
        ].all()
    )

    all_packages_ready = bool(
        package_coverage[
            "package_automatic_legality_ready"
        ].all()
    )

    checks.extend(
        [
            {
                "check_name": "all_standalone_rights_have_legality_inputs",
                "observed_value": int(
                    right_coverage[
                        "automatic_pick_legality_ready"
                    ].sum()
                ),
                "expected_value": len(right_coverage),
                "passed": all_rights_ready,
                "blocking_for_legality_engine": True,
            },
            {
                "check_name": "all_optimizer_packages_have_legality_inputs",
                "observed_value": int(
                    package_coverage[
                        "package_automatic_legality_ready"
                    ].sum()
                ),
                "expected_value": len(package_coverage),
                "passed": all_packages_ready,
                "blocking_for_legality_engine": True,
            },
        ]
    )

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path, label in [
        (
            PICK_INVENTORY_PATH,
            "canonical future-pick inventory",
        ),
        (
            ONE_FOR_ONE_CANDIDATES_PATH,
            "one-for-one mixed optimizer candidates",
        ),
        (
            TWO_FOR_ONE_CANDIDATES_PATH,
            "two-for-one mixed optimizer candidates",
        ),
    ]:
        require_file(path, label)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK LEGALITY INPUT AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading optimizer and pick artifacts")
    inventory = pd.read_parquet(
        PICK_INVENTORY_PATH
    )

    one_for_one = pd.read_parquet(
        ONE_FOR_ONE_CANDIDATES_PATH
    )

    two_for_one = pd.read_parquet(
        TWO_FOR_ONE_CANDIDATES_PATH
    )

    require_columns(
        inventory,
        INVENTORY_REQUIRED_COLUMNS,
        "Canonical future-pick inventory",
    )

    require_columns(
        one_for_one,
        PACKAGE_REQUIRED_COLUMNS,
        "One-for-one mixed optimizer candidates",
    )

    require_columns(
        two_for_one,
        PACKAGE_REQUIRED_COLUMNS,
        "Two-for-one mixed optimizer candidates",
    )

    print("[2/7] Discovering local legality data sources")
    sources = discover_legality_sources()

    print("[3/7] Measuring legality concept coverage")
    concept_coverage = build_concept_coverage(
        sources
    )

    print("[4/7] Auditing all standalone pick rights")
    right_coverage = build_right_coverage(
        inventory,
        concept_coverage,
    )

    print("[5/7] Mapping legality readiness to optimizer packages")
    package_coverage = build_package_coverage(
        one_for_one,
        two_for_one,
        right_coverage,
    )

    print("[6/7] Building missing-input action plan")
    missing_actions = build_missing_actions(
        concept_coverage
    )

    readiness = build_readiness(
        inventory=inventory,
        one_for_one=one_for_one,
        two_for_one=two_for_one,
        sources=sources,
        concept_coverage=concept_coverage,
        right_coverage=right_coverage,
        package_coverage=package_coverage,
    )

    sources.to_csv(
        SOURCE_CATALOG_PATH,
        index=False,
    )

    concept_coverage.to_csv(
        CONCEPT_COVERAGE_PATH,
        index=False,
    )

    right_coverage.to_csv(
        RIGHT_COVERAGE_PATH,
        index=False,
    )

    package_coverage.to_csv(
        PACKAGE_COVERAGE_PATH,
        index=False,
    )

    missing_actions.to_csv(
        MISSING_INPUT_ACTIONS_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    blocking_failures = readiness.loc[
        readiness[
            "blocking_for_legality_engine"
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
        "source_files_discovered": int(
            len(sources)
        ),
        "source_files_with_inspection_errors": int(
            (
                ~sources[
                    "inspection_passed"
                ].fillna(False).astype(bool)
            ).sum()
        )
        if not sources.empty
        else 0,
        "legality_concepts_required": (
            REQUIRED_LEGALITY_CONCEPTS
        ),
        "legality_concepts_ready": int(
            concept_coverage[
                "automatic_validation_source_ready"
            ].sum()
        ),
        "standalone_right_rows": int(
            len(right_coverage)
        ),
        "standalone_rights_ready": int(
            right_coverage[
                "automatic_pick_legality_ready"
            ].sum()
        ),
        "optimizer_package_rows": int(
            len(package_coverage)
        ),
        "optimizer_packages_ready": int(
            package_coverage[
                "package_automatic_legality_ready"
            ].sum()
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
        "automatic_legality_engine_ready": bool(
            blocking_failures.empty
        ),
        "scope_note": (
            "This audit discovers local data inputs only. It does not "
            "declare any pick or trade package legally valid."
        ),
        "output_files": {
            "source_catalog": str(
                SOURCE_CATALOG_PATH
            ),
            "concept_coverage": str(
                CONCEPT_COVERAGE_PATH
            ),
            "right_coverage": str(
                RIGHT_COVERAGE_PATH
            ),
            "package_coverage": str(
                PACKAGE_COVERAGE_PATH
            ),
            "missing_input_actions": str(
                MISSING_INPUT_ACTIONS_PATH
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

    print("[7/7] Audit outputs saved")
    print()

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK LEGALITY INPUT AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Local legality source files discovered: "
        f"{len(sources):,}"
    )
    print(
        "Legality concepts ready: "
        f"{int(concept_coverage['automatic_validation_source_ready'].sum()):,}"
        f"/{len(REQUIRED_LEGALITY_CONCEPTS):,}"
    )
    print(
        "Standalone rights ready for automatic validation: "
        f"{int(right_coverage['automatic_pick_legality_ready'].sum()):,}"
        f"/{len(right_coverage):,}"
    )
    print(
        "Optimizer packages ready for automatic validation: "
        f"{int(package_coverage['package_automatic_legality_ready'].sum()):,}"
        f"/{len(package_coverage):,}"
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
        "Automatic legality engine ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("LEGALITY CONCEPT COVERAGE")
    print(
        concept_coverage[
            [
                "legality_concept",
                "processed_data_sources_found",
                "source_files_found",
                "automatic_validation_source_ready",
                "source_files",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("RIGHT READINESS SUMMARY")
    right_summary = (
        right_coverage.groupby(
            [
                "automatic_pick_legality_ready",
                "complex_structure_flag",
                "legality_readiness_status",
            ],
            dropna=False,
        )
        .size()
        .reset_index(
            name="right_rows"
        )
    )

    print(
        right_summary.to_string(
            index=False
        )
    )
    print()

    print("MISSING INPUT ACTIONS")
    print(
        missing_actions[
            [
                "legality_concept",
                "automatic_validation_source_ready",
                "processed_data_sources_found",
                "recommended_action",
            ]
        ].to_string(
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
        SOURCE_CATALOG_PATH,
        CONCEPT_COVERAGE_PATH,
        RIGHT_COVERAGE_PATH,
        PACKAGE_COVERAGE_PATH,
        MISSING_INPUT_ACTIONS_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()