from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "stepien-frozen-pick-horizon-audit-v1-2026-08-04"
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
    / "stepien_frozen_pick_horizon_source_catalog_v1.csv"
)

YEAR_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_year_coverage_v1.csv"
)

TEAM_YEAR_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_first_round_team_year_coverage_v1.csv"
)

RIGHT_HORIZON_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_first_round_right_horizon_v1.csv"
)

REQUIREMENT_MATRIX_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_requirement_matrix_v1.csv"
)

ACTION_PLAN_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_horizon_action_plan_v1.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_horizon_readiness_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_horizon_metadata_v1.json"
)


AS_OF_DATE = date(2026, 8, 4)
CURRENT_CAP_YEAR_START = 2026
FIRST_FUTURE_DRAFT_YEAR = 2027

STEPIEN_REQUIRED_DRAFT_YEARS = list(
    range(
        FIRST_FUTURE_DRAFT_YEAR,
        FIRST_FUTURE_DRAFT_YEAR + 7,
    )
)

SECOND_APRON_FROZEN_PICK_DRAFT_YEAR = (
    CURRENT_CAP_YEAR_START + 8
)

ALL_REQUIRED_DRAFT_YEARS = sorted(
    set(
        STEPIEN_REQUIRED_DRAFT_YEARS
        + [
            SECOND_APRON_FROZEN_PICK_DRAFT_YEAR,
        ]
    )
)

EXPECTED_PICK_ROWS = 174
EXPECTED_STANDALONE_ROWS = 172
EXPECTED_TEAMS = 30
EXPECTED_ONE_FOR_ONE_ROWS = 28324
EXPECTED_TWO_FOR_ONE_ROWS = 282277

SUPPORTED_SUFFIXES = {
    ".csv",
    ".parquet",
    ".json",
}

SOURCE_NAME_TERMS = [
    "future_pick",
    "draft_pick",
    "pick_obligation",
    "obligation_ledger",
    "pick_ownership",
    "pick_inventory",
    "claim_value",
    "source_allocation",
    "source_asset",
]

YEAR_COLUMN_NAMES = {
    "draft_year",
    "year",
    "pick_year",
    "draft_year_min",
    "draft_year_max",
    "season_year",
    "first_draft_year",
    "last_draft_year",
}

ROUND_COLUMN_NAMES = {
    "round",
    "round_number",
    "round_numbers",
    "draft_round",
}

TEAM_COLUMN_NAMES = {
    "team",
    "team_abbreviation",
    "candidate_team",
    "owning_team",
    "owner_team",
    "current_owner",
    "originating_team",
    "originating_teams",
    "source_team",
    "beneficiary_team",
}

PICK_INVENTORY_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "standalone_trade_asset_flag",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "source_assets",
    "originating_teams",
    "right_structure",
    "tradability_status",
]


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


def candidate_source_file(path: Path) -> bool:
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return False

    normalized = normalize_name(path.name)

    return any(
        term in normalized
        for term in SOURCE_NAME_TERMS
    )


def read_schema(path: Path) -> tuple[list[str], int | None]:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        header = pd.read_csv(
            path,
            nrows=0,
        )

        return list(header.columns), None

    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq

            parquet_file = pq.ParquetFile(path)

            return (
                [
                    field.name
                    for field in parquet_file.schema_arrow
                ],
                int(
                    parquet_file.metadata.num_rows
                ),
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

        if (
            isinstance(payload, list)
            and payload
            and isinstance(payload[0], dict)
        ):
            return list(payload[0].keys()), len(payload)

        return [], (
            len(payload)
            if isinstance(payload, list)
            else 1
        )

    raise ValueError(
        f"Unsupported source type: {path}"
    )


def relevant_columns(
    columns: list[str],
) -> dict[str, list[str]]:
    normalized_lookup = {
        normalize_name(column): str(column)
        for column in columns
    }

    return {
        "year_columns": [
            original
            for normalized, original
            in normalized_lookup.items()
            if normalized in YEAR_COLUMN_NAMES
            or (
                "draft" in normalized
                and "year" in normalized
            )
            or normalized.endswith(
                "_year"
            )
        ],
        "round_columns": [
            original
            for normalized, original
            in normalized_lookup.items()
            if normalized in ROUND_COLUMN_NAMES
            or (
                "round" in normalized
                and "value" not in normalized
            )
        ],
        "team_columns": [
            original
            for normalized, original
            in normalized_lookup.items()
            if normalized in TEAM_COLUMN_NAMES
            or normalized.endswith(
                "_team"
            )
        ],
        "right_id_columns": [
            original
            for normalized, original
            in normalized_lookup.items()
            if normalized
            == "future_pick_right_id"
            or (
                "pick" in normalized
                and normalized.endswith(
                    "_id"
                )
            )
            or (
                "source_asset" in normalized
            )
        ],
    }


def read_selected_columns(
    path: Path,
    columns: list[str],
) -> pd.DataFrame:
    if not columns:
        return pd.DataFrame()

    suffix = path.suffix.lower()

    if suffix == ".parquet":
        return pd.read_parquet(
            path,
            columns=columns,
        )

    if suffix == ".csv":
        return pd.read_csv(
            path,
            usecols=columns,
            low_memory=False,
        )

    if suffix == ".json":
        payload = json.loads(
            path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )

        if isinstance(payload, dict):
            return pd.DataFrame(
                [
                    {
                        column: payload.get(column)
                        for column in columns
                    }
                ]
            )

        if isinstance(payload, list):
            return pd.DataFrame(payload)[
                [
                    column
                    for column in columns
                    if column
                    in pd.DataFrame(payload).columns
                ]
            ]

    return pd.DataFrame()


def extract_years(
    frame: pd.DataFrame,
    year_columns: list[str],
) -> list[int]:
    years = set()

    for column in year_columns:
        if column not in frame.columns:
            continue

        series = frame[column]

        numeric = pd.to_numeric(
            series,
            errors="coerce",
        )

        for value in numeric.dropna():
            integer = int(value)

            if 2000 <= integer <= 2100:
                years.add(integer)

        text_values = (
            series
            .dropna()
            .astype(str)
        )

        for value in text_values:
            for match in re.findall(
                r"\b20\d{2}\b",
                value,
            ):
                integer = int(match)

                if 2000 <= integer <= 2100:
                    years.add(integer)

    return sorted(years)


def extract_rounds(
    frame: pd.DataFrame,
    round_columns: list[str],
) -> list[int]:
    rounds = set()

    for column in round_columns:
        if column not in frame.columns:
            continue

        for value in (
            frame[column]
            .dropna()
            .astype(str)
        ):
            normalized = value.lower()

            if re.search(
                r"\b1\b|first|r1",
                normalized,
            ):
                rounds.add(1)

            if re.search(
                r"\b2\b|second|r2",
                normalized,
            ):
                rounds.add(2)

    return sorted(rounds)


def extract_teams(
    frame: pd.DataFrame,
    team_columns: list[str],
) -> list[str]:
    teams = set()

    for column in team_columns:
        if column not in frame.columns:
            continue

        for value in (
            frame[column]
            .dropna()
            .astype(str)
            .str.upper()
            .str.strip()
        ):
            for token in re.findall(
                r"\b[A-Z]{3}\b",
                value,
            ):
                teams.add(token)

    return sorted(teams)


def discover_horizon_sources() -> pd.DataFrame:
    paths = []

    for root in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        if not root.exists():
            continue

        for path in root.iterdir():
            if (
                path.is_file()
                and candidate_source_file(path)
            ):
                paths.append(path)

    rows = []

    for index, path in enumerate(
        sorted(paths),
        start=1,
    ):
        if index == 1 or index % 25 == 0:
            print(
                f"  Inspecting source {index:,}/"
                f"{len(paths):,}: {relative_path(path)}"
            )

        try:
            columns, row_count = read_schema(path)
            groups = relevant_columns(columns)

            selected = sorted(
                set(
                    groups["year_columns"]
                    + groups["round_columns"]
                    + groups["team_columns"]
                    + groups["right_id_columns"]
                )
            )

            frame = read_selected_columns(
                path,
                selected,
            )

            years = extract_years(
                frame,
                groups[
                    "year_columns"
                ],
            )

            rounds = extract_rounds(
                frame,
                groups[
                    "round_columns"
                ],
            )

            teams = extract_teams(
                frame,
                groups[
                    "team_columns"
                ],
            )

            rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(path),
                    "source_surface": (
                        "data_processed"
                        if path.parent
                        == PROCESSED_DIRECTORY
                        else "outputs"
                    ),
                    "file_suffix": path.suffix.lower(),
                    "row_count": row_count,
                    "column_count": len(columns),
                    "year_columns": "|".join(
                        groups["year_columns"]
                    ),
                    "round_columns": "|".join(
                        groups["round_columns"]
                    ),
                    "team_columns": "|".join(
                        groups["team_columns"]
                    ),
                    "right_id_columns": "|".join(
                        groups["right_id_columns"]
                    ),
                    "minimum_year_found": (
                        min(years)
                        if years
                        else np.nan
                    ),
                    "maximum_year_found": (
                        max(years)
                        if years
                        else np.nan
                    ),
                    "years_found": "|".join(
                        str(year)
                        for year in years
                    ),
                    "first_round_signal_found": (
                        1 in rounds
                    ),
                    "rounds_found": "|".join(
                        str(round_number)
                        for round_number in rounds
                    ),
                    "team_count_found": len(teams),
                    "teams_found": "|".join(teams),
                    "required_horizon_years_found": "|".join(
                        str(year)
                        for year
                        in ALL_REQUIRED_DRAFT_YEARS
                        if year in years
                    ),
                    "required_horizon_year_count": sum(
                        year in years
                        for year
                        in ALL_REQUIRED_DRAFT_YEARS
                    ),
                    "inspection_passed": True,
                    "inspection_error": "",
                }
            )
        except Exception as error:
            rows.append(
                {
                    "file_path": str(path),
                    "relative_file_path": relative_path(path),
                    "source_surface": (
                        "data_processed"
                        if path.parent
                        == PROCESSED_DIRECTORY
                        else "outputs"
                    ),
                    "file_suffix": path.suffix.lower(),
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "year_columns": "",
                    "round_columns": "",
                    "team_columns": "",
                    "right_id_columns": "",
                    "minimum_year_found": np.nan,
                    "maximum_year_found": np.nan,
                    "years_found": "",
                    "first_round_signal_found": False,
                    "rounds_found": "",
                    "team_count_found": 0,
                    "teams_found": "",
                    "required_horizon_years_found": "",
                    "required_horizon_year_count": 0,
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
            "source_surface",
            "required_horizon_year_count",
            "first_round_signal_found",
            "relative_file_path",
        ],
        ascending=[
            False,
            True,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def build_right_horizon(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    standalone = inventory.loc[
        parse_bool_series(
            inventory[
                "standalone_trade_asset_flag"
            ]
        )
    ].copy()

    standalone[
        "draft_year_min_numeric"
    ] = pd.to_numeric(
        standalone[
            "draft_year_min"
        ],
        errors="coerce",
    )

    standalone[
        "draft_year_max_numeric"
    ] = pd.to_numeric(
        standalone[
            "draft_year_max"
        ],
        errors="coerce",
    )

    standalone[
        "first_round_flag"
    ] = (
        standalone[
            "round_numbers"
        ]
        .fillna("")
        .astype(str)
        .str.lower()
        .str.contains(
            r"(^|[^0-9])1([^0-9]|$)|first|r1",
            regex=True,
        )
    )

    rows = []

    for row in standalone.itertuples(index=False):
        start_year = getattr(
            row,
            "draft_year_min_numeric",
        )

        end_year = getattr(
            row,
            "draft_year_max_numeric",
        )

        if pd.isna(start_year):
            years = []
        else:
            start = int(start_year)
            end = (
                int(end_year)
                if not pd.isna(end_year)
                else start
            )

            years = list(
                range(
                    start,
                    end + 1,
                )
            )

        for year in years:
            rows.append(
                {
                    "future_pick_right_id": (
                        row.future_pick_right_id
                    ),
                    "candidate_team": (
                        row.candidate_team
                    ),
                    "draft_year": year,
                    "first_round_flag": bool(
                        row.first_round_flag
                    ),
                    "round_numbers": (
                        row.round_numbers
                    ),
                    "source_assets": (
                        row.source_assets
                    ),
                    "originating_teams": (
                        row.originating_teams
                    ),
                    "right_structure": (
                        row.right_structure
                    ),
                    "tradability_status": (
                        row.tradability_status
                    ),
                    "inside_stepien_horizon": (
                        year
                        in STEPIEN_REQUIRED_DRAFT_YEARS
                    ),
                    "is_frozen_pick_target_year": (
                        year
                        == SECOND_APRON_FROZEN_PICK_DRAFT_YEAR
                    ),
                }
            )

    output = pd.DataFrame(rows)

    if output.empty:
        return output

    return output.sort_values(
        [
            "candidate_team",
            "draft_year",
            "first_round_flag",
            "future_pick_right_id",
        ],
        ascending=[
            True,
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)


def build_year_coverage(
    sources: pd.DataFrame,
    right_horizon: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for year in ALL_REQUIRED_DRAFT_YEARS:
        if sources.empty:
            source_mask = pd.Series(
                dtype=bool
            )
        else:
            source_mask = (
                sources[
                    "inspection_passed"
                ].fillna(False).astype(bool)
                & sources[
                    "years_found"
                ]
                .fillna("")
                .astype(str)
                .str.split("|")
                .map(
                    lambda values: str(year)
                    in values
                )
            )

        matched_sources = (
            sources.loc[
                source_mask
            ]
            if not sources.empty
            else pd.DataFrame()
        )

        processed_sources = (
            matched_sources.loc[
                matched_sources[
                    "source_surface"
                ].eq(
                    "data_processed"
                )
            ]
            if not matched_sources.empty
            else pd.DataFrame()
        )

        first_round_sources = (
            matched_sources.loc[
                matched_sources[
                    "first_round_signal_found"
                ].fillna(False).astype(bool)
            ]
            if not matched_sources.empty
            else pd.DataFrame()
        )

        rights = (
            right_horizon.loc[
                right_horizon[
                    "draft_year"
                ].eq(year)
            ]
            if not right_horizon.empty
            else pd.DataFrame()
        )

        first_round_rights = (
            rights.loc[
                rights[
                    "first_round_flag"
                ]
            ]
            if not rights.empty
            else pd.DataFrame()
        )

        teams_with_first = (
            int(
                first_round_rights[
                    "candidate_team"
                ].nunique()
            )
            if not first_round_rights.empty
            else 0
        )

        rows.append(
            {
                "draft_year": year,
                "required_for_stepien": (
                    year
                    in STEPIEN_REQUIRED_DRAFT_YEARS
                ),
                "required_for_second_apron_frozen_pick": (
                    year
                    == SECOND_APRON_FROZEN_PICK_DRAFT_YEAR
                ),
                "local_source_files_with_year": int(
                    len(matched_sources)
                ),
                "processed_source_files_with_year": int(
                    len(processed_sources)
                ),
                "first_round_source_files_with_year": int(
                    len(first_round_sources)
                ),
                "standalone_right_rows": int(
                    len(rights)
                ),
                "standalone_first_round_right_rows": int(
                    len(first_round_rights)
                ),
                "teams_with_standalone_first_round_right": (
                    teams_with_first
                ),
                "all_30_teams_have_first_round_right": (
                    teams_with_first
                    == EXPECTED_TEAMS
                ),
                "processed_year_source_present": bool(
                    len(processed_sources) > 0
                ),
                "first_round_year_source_present": bool(
                    len(first_round_sources) > 0
                ),
                "canonical_right_horizon_present": bool(
                    len(rights) > 0
                ),
                "automatic_year_legality_ready": bool(
                    len(processed_sources) > 0
                    and len(first_round_sources) > 0
                    and teams_with_first
                    == EXPECTED_TEAMS
                ),
                "example_source_files": "|".join(
                    matched_sources[
                        "relative_file_path"
                    ]
                    .head(10)
                    .tolist()
                )
                if not matched_sources.empty
                else "",
            }
        )

    return pd.DataFrame(rows)


def build_team_year_coverage(
    right_horizon: pd.DataFrame,
) -> pd.DataFrame:
    teams = sorted(
        right_horizon[
            "candidate_team"
        ].dropna().astype(str).unique()
    )

    rows = []

    for team in teams:
        for year in STEPIEN_REQUIRED_DRAFT_YEARS:
            subset = right_horizon.loc[
                right_horizon[
                    "candidate_team"
                ].eq(team)
                & right_horizon[
                    "draft_year"
                ].eq(year)
                & right_horizon[
                    "first_round_flag"
                ]
            ]

            rows.append(
                {
                    "candidate_team": team,
                    "draft_year": year,
                    "standalone_first_round_right_rows": int(
                        len(subset)
                    ),
                    "first_round_right_ids": "|".join(
                        sorted(
                            subset[
                                "future_pick_right_id"
                            ].astype(str)
                        )
                    ),
                    "source_assets": "|".join(
                        sorted(
                            set(
                                subset[
                                    "source_assets"
                                ]
                                .fillna("")
                                .astype(str)
                            )
                        )
                    ),
                    "has_any_standalone_first_round_right": bool(
                        len(subset) > 0
                    ),
                    "deterministic_stepien_availability_ready": False,
                    "readiness_note": (
                        "A right count alone does not prove deterministic "
                        "availability. Conditional, protected, swap, pooled, "
                        "and already-encumbered rights require source-level "
                        "resolution through the full seven-draft horizon."
                    ),
                }
            )

    return pd.DataFrame(rows)


def build_requirement_matrix(
    year_coverage: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for year in STEPIEN_REQUIRED_DRAFT_YEARS:
        coverage = year_coverage.loc[
            year_coverage[
                "draft_year"
            ].eq(year)
        ].iloc[0]

        rows.append(
            {
                "requirement_type": "stepien_future_first_calendar",
                "draft_year": year,
                "required_reason": (
                    "Seven-future-draft first-round availability horizon."
                ),
                "processed_source_present": bool(
                    coverage[
                        "processed_year_source_present"
                    ]
                ),
                "canonical_right_horizon_present": bool(
                    coverage[
                        "canonical_right_horizon_present"
                    ]
                ),
                "all_30_teams_covered": bool(
                    coverage[
                        "all_30_teams_have_first_round_right"
                    ]
                ),
                "requirement_ready": bool(
                    coverage[
                        "automatic_year_legality_ready"
                    ]
                ),
            }
        )

    frozen = year_coverage.loc[
        year_coverage[
            "draft_year"
        ].eq(
            SECOND_APRON_FROZEN_PICK_DRAFT_YEAR
        )
    ].iloc[0]

    rows.append(
        {
            "requirement_type": (
                "second_apron_frozen_first_round_pick"
            ),
            "draft_year": (
                SECOND_APRON_FROZEN_PICK_DRAFT_YEAR
            ),
            "required_reason": (
                "First draft after the seventh season following the "
                "2026-27 cap year."
            ),
            "processed_source_present": bool(
                frozen[
                    "processed_year_source_present"
                ]
            ),
            "canonical_right_horizon_present": bool(
                frozen[
                    "canonical_right_horizon_present"
                ]
            ),
            "all_30_teams_covered": bool(
                frozen[
                    "all_30_teams_have_first_round_right"
                ]
            ),
            "requirement_ready": bool(
                frozen[
                    "automatic_year_legality_ready"
                ]
            ),
        }
    )

    return pd.DataFrame(rows)


def build_action_plan(
    requirement_matrix: pd.DataFrame,
) -> pd.DataFrame:
    actions = [
        {
            "action_priority": 1,
            "action_name": (
                "extend_first_round_inventory_through_2033"
            ),
            "required_for": "Stepien",
            "action_description": (
                "Build a source-level first-round ownership and obligation "
                "inventory for every team and draft from 2030 through 2033, "
                "then combine it with the existing 2027-2029 layer."
            ),
        },
        {
            "action_priority": 2,
            "action_name": (
                "add_2034_frozen_pick_tracking"
            ),
            "required_for": "Second apron frozen-pick rule",
            "action_description": (
                "Add each team's 2034 own first-round pick, current frozen "
                "status, freeze trigger cap year, unfreeze conditions, and "
                "draft-pick-penalty status."
            ),
        },
        {
            "action_priority": 3,
            "action_name": (
                "build_deterministic_first_round_availability_calendar"
            ),
            "required_for": "Stepien",
            "action_description": (
                "Resolve conditional protections, swaps, pools, fallbacks, "
                "and overlapping claims into retained-first availability by "
                "team and draft year rather than relying on expected counts."
            ),
        },
        {
            "action_priority": 4,
            "action_name": (
                "apply_package_specific_stepien_simulation"
            ),
            "required_for": "Optimizer legality",
            "action_description": (
                "For each proposed outgoing first-round right, remove that "
                "right from the team's calendar and test every consecutive "
                "future-draft pair under a conservative deterministic policy."
            ),
        },
        {
            "action_priority": 5,
            "action_name": (
                "validate_authority_and_as_of_dates"
            ),
            "required_for": "All pick legality checks",
            "action_description": (
                "Require authoritative source provenance and effective dates "
                "for ownership, obligations, protections, freezes, and "
                "encumbrances before any package can be marked finally legal."
            ),
        },
    ]

    output = pd.DataFrame(actions)

    output[
        "requirements_currently_ready"
    ] = int(
        requirement_matrix[
            "requirement_ready"
        ].sum()
    )

    output[
        "requirements_total"
    ] = int(
        len(requirement_matrix)
    )

    return output


def build_readiness(
    inventory: pd.DataFrame,
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
    sources: pd.DataFrame,
    year_coverage: pd.DataFrame,
    requirement_matrix: pd.DataFrame,
) -> pd.DataFrame:
    standalone_rows = int(
        parse_bool_series(
            inventory[
                "standalone_trade_asset_flag"
            ]
        ).sum()
    )

    canonical_max_year = int(
        pd.to_numeric(
            inventory[
                "draft_year_max"
            ],
            errors="coerce",
        ).max()
    )

    stepien_rows = requirement_matrix.loc[
        requirement_matrix[
            "requirement_type"
        ].eq(
            "stepien_future_first_calendar"
        )
    ]

    frozen_rows = requirement_matrix.loc[
        requirement_matrix[
            "requirement_type"
        ].eq(
            "second_apron_frozen_first_round_pick"
        )
    ]

    checks = [
        {
            "check_name": "canonical_pick_inventory_rows",
            "observed_value": len(inventory),
            "expected_value": EXPECTED_PICK_ROWS,
            "passed": len(inventory) == EXPECTED_PICK_ROWS,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "standalone_pick_inventory_rows",
            "observed_value": standalone_rows,
            "expected_value": EXPECTED_STANDALONE_ROWS,
            "passed": standalone_rows == EXPECTED_STANDALONE_ROWS,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "one_for_one_optimizer_rows",
            "observed_value": len(one_for_one),
            "expected_value": EXPECTED_ONE_FOR_ONE_ROWS,
            "passed": len(one_for_one) == EXPECTED_ONE_FOR_ONE_ROWS,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "two_for_one_optimizer_rows",
            "observed_value": len(two_for_one),
            "expected_value": EXPECTED_TWO_FOR_ONE_ROWS,
            "passed": len(two_for_one) == EXPECTED_TWO_FOR_ONE_ROWS,
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "canonical_inventory_maximum_draft_year",
            "observed_value": canonical_max_year,
            "expected_value": (
                f">={max(STEPIEN_REQUIRED_DRAFT_YEARS)}"
            ),
            "passed": (
                canonical_max_year
                >= max(
                    STEPIEN_REQUIRED_DRAFT_YEARS
                )
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "stepien_seven_draft_horizon_complete",
            "observed_value": int(
                stepien_rows[
                    "requirement_ready"
                ].sum()
            ),
            "expected_value": len(
                STEPIEN_REQUIRED_DRAFT_YEARS
            ),
            "passed": bool(
                stepien_rows[
                    "requirement_ready"
                ].all()
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "second_apron_2034_pick_horizon_complete",
            "observed_value": int(
                frozen_rows[
                    "requirement_ready"
                ].sum()
            ),
            "expected_value": 1,
            "passed": bool(
                frozen_rows[
                    "requirement_ready"
                ].all()
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "all_required_years_have_processed_sources",
            "observed_value": int(
                year_coverage[
                    "processed_year_source_present"
                ].sum()
            ),
            "expected_value": len(
                ALL_REQUIRED_DRAFT_YEARS
            ),
            "passed": bool(
                year_coverage[
                    "processed_year_source_present"
                ].all()
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "all_required_years_cover_30_teams",
            "observed_value": int(
                year_coverage[
                    "all_30_teams_have_first_round_right"
                ].sum()
            ),
            "expected_value": len(
                ALL_REQUIRED_DRAFT_YEARS
            ),
            "passed": bool(
                year_coverage[
                    "all_30_teams_have_first_round_right"
                ].all()
            ),
            "blocking_for_legality_engine": True,
        },
        {
            "check_name": "automatic_stepien_and_frozen_pick_engine_ready",
            "observed_value": bool(
                requirement_matrix[
                    "requirement_ready"
                ].all()
            ),
            "expected_value": True,
            "passed": bool(
                requirement_matrix[
                    "requirement_ready"
                ].all()
            ),
            "blocking_for_legality_engine": True,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path, label in [
        (
            PICK_INVENTORY_PATH,
            "canonical pick inventory",
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
    print("STEPIEN AND FROZEN-PICK HORIZON AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"As-of date: {AS_OF_DATE.isoformat()}")
    print(
        "Stepien draft horizon: "
        f"{min(STEPIEN_REQUIRED_DRAFT_YEARS)}-"
        f"{max(STEPIEN_REQUIRED_DRAFT_YEARS)}"
    )
    print(
        "Second-apron frozen-pick target year for 2026-27: "
        f"{SECOND_APRON_FROZEN_PICK_DRAFT_YEAR}"
    )
    print()

    print("[1/7] Loading optimizer and canonical inventory")
    inventory = pd.read_parquet(
        PICK_INVENTORY_PATH
    )

    one_for_one = pd.read_parquet(
        ONE_FOR_ONE_CANDIDATES_PATH,
        columns=[
            "optimizer_candidate_id",
            "attached_pick_right_id",
        ],
    )

    two_for_one = pd.read_parquet(
        TWO_FOR_ONE_CANDIDATES_PATH,
        columns=[
            "optimizer_candidate_id",
            "attached_pick_right_id",
        ],
    )

    require_columns(
        inventory,
        PICK_INVENTORY_REQUIRED_COLUMNS,
        "Canonical pick inventory",
    )

    print("[2/7] Discovering local future-pick horizon sources")
    sources = discover_horizon_sources()

    print("[3/7] Expanding canonical rights by draft year")
    right_horizon = build_right_horizon(
        inventory
    )

    print("[4/7] Measuring required-year coverage")
    year_coverage = build_year_coverage(
        sources,
        right_horizon,
    )

    print("[5/7] Building team-year first-round coverage")
    team_year_coverage = build_team_year_coverage(
        right_horizon
    )

    print("[6/7] Building requirement matrix and action plan")
    requirement_matrix = build_requirement_matrix(
        year_coverage
    )

    action_plan = build_action_plan(
        requirement_matrix
    )

    readiness = build_readiness(
        inventory=inventory,
        one_for_one=one_for_one,
        two_for_one=two_for_one,
        sources=sources,
        year_coverage=year_coverage,
        requirement_matrix=requirement_matrix,
    )

    sources.to_csv(
        SOURCE_CATALOG_PATH,
        index=False,
    )

    year_coverage.to_csv(
        YEAR_COVERAGE_PATH,
        index=False,
    )

    team_year_coverage.to_csv(
        TEAM_YEAR_COVERAGE_PATH,
        index=False,
    )

    right_horizon.to_csv(
        RIGHT_HORIZON_PATH,
        index=False,
    )

    requirement_matrix.to_csv(
        REQUIREMENT_MATRIX_PATH,
        index=False,
    )

    action_plan.to_csv(
        ACTION_PLAN_PATH,
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
        "as_of_date": AS_OF_DATE.isoformat(),
        "current_cap_year": "2026-27",
        "stepien_required_draft_years": (
            STEPIEN_REQUIRED_DRAFT_YEARS
        ),
        "second_apron_frozen_pick_draft_year": (
            SECOND_APRON_FROZEN_PICK_DRAFT_YEAR
        ),
        "all_required_draft_years": (
            ALL_REQUIRED_DRAFT_YEARS
        ),
        "canonical_inventory_rows": int(
            len(inventory)
        ),
        "canonical_inventory_max_year": int(
            pd.to_numeric(
                inventory[
                    "draft_year_max"
                ],
                errors="coerce",
            ).max()
        ),
        "local_horizon_sources_inspected": int(
            len(sources)
        ),
        "requirement_rows": int(
            len(requirement_matrix)
        ),
        "requirement_rows_ready": int(
            requirement_matrix[
                "requirement_ready"
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
        "automatic_stepien_and_frozen_pick_engine_ready": bool(
            blocking_failures.empty
        ),
        "scope_note": (
            "Read-only horizon audit. No trade or pick right is declared "
            "legally valid."
        ),
        "output_files": {
            "source_catalog": str(
                SOURCE_CATALOG_PATH
            ),
            "year_coverage": str(
                YEAR_COVERAGE_PATH
            ),
            "team_year_coverage": str(
                TEAM_YEAR_COVERAGE_PATH
            ),
            "right_horizon": str(
                RIGHT_HORIZON_PATH
            ),
            "requirement_matrix": str(
                REQUIREMENT_MATRIX_PATH
            ),
            "action_plan": str(
                ACTION_PLAN_PATH
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
    print("STEPIEN AND FROZEN-PICK HORIZON AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Canonical inventory maximum draft year: "
        f"{int(pd.to_numeric(inventory['draft_year_max'], errors='coerce').max())}"
    )
    print(
        "Stepien horizon years ready: "
        f"{int(requirement_matrix.loc[requirement_matrix['requirement_type'].eq('stepien_future_first_calendar'), 'requirement_ready'].sum())}"
        f"/{len(STEPIEN_REQUIRED_DRAFT_YEARS)}"
    )
    print(
        "2034 frozen-pick horizon ready: "
        f"{bool(requirement_matrix.loc[requirement_matrix['requirement_type'].eq('second_apron_frozen_first_round_pick'), 'requirement_ready'].all())}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum())}"
        f"/{len(readiness)}"
    )
    print(
        "Blocking failures: "
        f"{len(blocking_failures)}"
    )
    print(
        "Automatic Stepien and frozen-pick engine ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("REQUIRED-YEAR COVERAGE")
    print(
        year_coverage[
            [
                "draft_year",
                "required_for_stepien",
                "required_for_second_apron_frozen_pick",
                "processed_source_files_with_year",
                "first_round_source_files_with_year",
                "standalone_first_round_right_rows",
                "teams_with_standalone_first_round_right",
                "all_30_teams_have_first_round_right",
                "automatic_year_legality_ready",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("REQUIREMENT MATRIX")
    print(
        requirement_matrix.to_string(
            index=False
        )
    )
    print()

    print("ACTION PLAN")
    print(
        action_plan[
            [
                "action_priority",
                "action_name",
                "required_for",
                "action_description",
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
        YEAR_COVERAGE_PATH,
        TEAM_YEAR_COVERAGE_PATH,
        RIGHT_HORIZON_PATH,
        REQUIREMENT_MATRIX_PATH,
        ACTION_PLAN_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)


if __name__ == "__main__":
    main()