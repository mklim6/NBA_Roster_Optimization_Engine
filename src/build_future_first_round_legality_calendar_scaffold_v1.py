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
    "future-first-round-legality-calendar-scaffold-v1-2026-08-04"
)

RELEASE_NAME = (
    "future_first_round_legality_calendar_2027_2034_scaffold_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

TEAM_SALARY_PROFILE_PATH = (
    PROCESSED_DIRECTORY
    / "team_trade_salary_profiles_2026_27.csv"
)

HORIZON_YEAR_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_frozen_pick_year_coverage_v1.csv"
)

HORIZON_TEAM_YEAR_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "stepien_first_round_team_year_coverage_v1.csv"
)

CALENDAR_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v1.parquet"
)

CALENDAR_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v1.csv"
)

MANUAL_INPUT_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_manual_input_template_2027_2034_v1.csv"
)

SOURCE_REQUIREMENTS_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_source_requirements_v1.csv"
)

TEAM_HORIZON_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_team_horizon_summary_v1.csv"
)

YEAR_HORIZON_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_year_horizon_summary_v1.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_calendar_validation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_calendar_metadata_v1.json"
)


AS_OF_DATE = date(2026, 8, 4)
DRAFT_YEARS = list(range(2027, 2035))
STEPIEN_DRAFT_YEARS = set(range(2027, 2034))
FROZEN_PICK_TARGET_YEAR = 2034

EXPECTED_TEAMS = 30
EXPECTED_CALENDAR_ROWS = EXPECTED_TEAMS * len(DRAFT_YEARS)
EXPECTED_PICK_INVENTORY_ROWS = 174
EXPECTED_STANDALONE_PICK_ROWS = 172

PICK_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "right_display_name",
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
]

TEAM_REQUIRED_COLUMNS = [
    "team_abbreviation",
]

NBA_TEAM_CODES = {
    "ATL",
    "BKN",
    "BOS",
    "CHA",
    "CHI",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GSW",
    "HOU",
    "IND",
    "LAC",
    "LAL",
    "MEM",
    "MIA",
    "MIL",
    "MIN",
    "NOP",
    "NYK",
    "OKC",
    "ORL",
    "PHI",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "TOR",
    "UTA",
    "WAS",
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


def parse_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    return (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "passed"})
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


def normalize_team(series: pd.Series) -> pd.Series:
    return (
        series
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )


def round_one_flag(series: pd.Series) -> pd.Series:
    return (
        series
        .fillna("")
        .astype(str)
        .str.lower()
        .str.contains(
            r"(?:^|[^0-9])1(?:[^0-9]|$)|first|r1",
            regex=True,
        )
    )


def split_pipe_values(series: pd.Series) -> list[str]:
    values = set()

    for value in series.fillna("").astype(str):
        for token in value.split("|"):
            cleaned = clean_text(token)

            if cleaned:
                values.add(cleaned)

    return sorted(values)


def load_inputs() -> dict[str, pd.DataFrame]:
    for path, label in [
        (
            PICK_INVENTORY_PATH,
            "canonical future-pick inventory",
        ),
        (
            TEAM_SALARY_PROFILE_PATH,
            "team salary profiles",
        ),
        (
            HORIZON_YEAR_COVERAGE_PATH,
            "horizon year coverage",
        ),
        (
            HORIZON_TEAM_YEAR_COVERAGE_PATH,
            "horizon team-year coverage",
        ),
    ]:
        require_file(path, label)

    picks = pd.read_parquet(PICK_INVENTORY_PATH)
    teams = pd.read_csv(TEAM_SALARY_PROFILE_PATH)
    year_coverage = pd.read_csv(
        HORIZON_YEAR_COVERAGE_PATH
    )
    team_year_coverage = pd.read_csv(
        HORIZON_TEAM_YEAR_COVERAGE_PATH
    )

    require_columns(
        picks,
        PICK_REQUIRED_COLUMNS,
        "Canonical future-pick inventory",
    )

    require_columns(
        teams,
        TEAM_REQUIRED_COLUMNS,
        "Team salary profiles",
    )

    return {
        "picks": picks,
        "teams": teams,
        "year_coverage": year_coverage,
        "team_year_coverage": team_year_coverage,
    }


def prepare_teams(teams: pd.DataFrame) -> list[str]:
    team_codes = sorted(
        set(
            normalize_team(
                teams["team_abbreviation"]
            )
        )
    )

    unknown = sorted(
        set(team_codes) - NBA_TEAM_CODES
    )

    missing = sorted(
        NBA_TEAM_CODES - set(team_codes)
    )

    if unknown:
        raise RuntimeError(
            "Unknown team abbreviations were found:\n"
            + "\n".join(unknown)
        )

    if missing:
        raise RuntimeError(
            "NBA teams missing from the salary profile:\n"
            + "\n".join(missing)
        )

    if len(team_codes) != EXPECTED_TEAMS:
        raise RuntimeError(
            "Expected 30 unique NBA teams, found "
            f"{len(team_codes)}."
        )

    return team_codes


def expand_first_round_rights(
    picks: pd.DataFrame,
) -> pd.DataFrame:
    standalone = picks.loc[
        parse_bool_series(
            picks["standalone_trade_asset_flag"]
        )
    ].copy()

    standalone["candidate_team"] = normalize_team(
        standalone["candidate_team"]
    )

    standalone["first_round_flag"] = round_one_flag(
        standalone["round_numbers"]
    )

    standalone = standalone.loc[
        standalone["first_round_flag"]
    ].copy()

    standalone["draft_year_min"] = pd.to_numeric(
        standalone["draft_year_min"],
        errors="coerce",
    )

    standalone["draft_year_max"] = pd.to_numeric(
        standalone["draft_year_max"],
        errors="coerce",
    )

    standalone["candidate_right_value_score"] = (
        pd.to_numeric(
            standalone[
                "candidate_right_value_score"
            ],
            errors="coerce",
        )
    )

    standalone["expected_pick_count"] = pd.to_numeric(
        standalone["expected_pick_count"],
        errors="coerce",
    )

    rows = []

    for row in standalone.itertuples(index=False):
        if pd.isna(row.draft_year_min):
            continue

        start_year = int(row.draft_year_min)

        end_year = (
            int(row.draft_year_max)
            if not pd.isna(row.draft_year_max)
            else start_year
        )

        for draft_year in range(
            start_year,
            end_year + 1,
        ):
            if draft_year not in DRAFT_YEARS:
                continue

            rows.append(
                {
                    "future_pick_right_id": (
                        row.future_pick_right_id
                    ),
                    "candidate_team": (
                        row.candidate_team
                    ),
                    "draft_year": draft_year,
                    "right_display_name": (
                        row.right_display_name
                    ),
                    "right_structure": (
                        row.right_structure
                    ),
                    "source_assets": (
                        row.source_assets
                    ),
                    "source_asset_count": (
                        row.source_asset_count
                    ),
                    "primary_source_asset": (
                        row.primary_source_asset
                    ),
                    "originating_teams": (
                        row.originating_teams
                    ),
                    "expected_pick_count": (
                        row.expected_pick_count
                    ),
                    "candidate_right_value_score": (
                        row.candidate_right_value_score
                    ),
                    "tradability_status": (
                        row.tradability_status
                    ),
                }
            )

    return pd.DataFrame(rows)


def base_calendar(teams: list[str]) -> pd.DataFrame:
    rows = []

    for team in teams:
        for draft_year in DRAFT_YEARS:
            rows.append(
                {
                    "team_abbreviation": team,
                    "draft_year": draft_year,
                    "stepien_horizon_flag": (
                        draft_year
                        in STEPIEN_DRAFT_YEARS
                    ),
                    "second_apron_frozen_pick_target_flag": (
                        draft_year
                        == FROZEN_PICK_TARGET_YEAR
                    ),
                    "calendar_as_of_date": (
                        AS_OF_DATE.isoformat()
                    ),
                }
            )

    return pd.DataFrame(rows)


def summarize_known_rights(
    expanded_rights: pd.DataFrame,
) -> pd.DataFrame:
    if expanded_rights.empty:
        return pd.DataFrame(
            columns=[
                "team_abbreviation",
                "draft_year",
            ]
        )

    grouped_rows = []

    for (
        team,
        draft_year,
    ), group in expanded_rights.groupby(
        [
            "candidate_team",
            "draft_year",
        ],
        sort=True,
    ):
        structures = (
            group["right_structure"]
            .fillna("")
            .astype(str)
            .str.lower()
        )

        grouped_rows.append(
            {
                "team_abbreviation": team,
                "draft_year": int(draft_year),
                "known_standalone_first_round_right_rows": int(
                    len(group)
                ),
                "known_first_round_right_ids": "|".join(
                    sorted(
                        group[
                            "future_pick_right_id"
                        ]
                        .astype(str)
                        .unique()
                    )
                ),
                "known_first_round_right_names": "|".join(
                    sorted(
                        group[
                            "right_display_name"
                        ]
                        .fillna("")
                        .astype(str)
                        .unique()
                    )
                ),
                "known_first_round_source_assets": "|".join(
                    split_pipe_values(
                        group["source_assets"]
                    )
                ),
                "known_first_round_originating_teams": "|".join(
                    split_pipe_values(
                        group["originating_teams"]
                    )
                ),
                "known_first_round_expected_pick_count": float(
                    pd.to_numeric(
                        group[
                            "expected_pick_count"
                        ],
                        errors="coerce",
                    )
                    .fillna(0.0)
                    .sum()
                ),
                "known_first_round_value_score": float(
                    pd.to_numeric(
                        group[
                            "candidate_right_value_score"
                        ],
                        errors="coerce",
                    )
                    .fillna(0.0)
                    .sum()
                ),
                "known_conditional_or_protected_right_rows": int(
                    structures.str.contains(
                        "conditional|protected|protection|fallback|rollover",
                        regex=True,
                    ).sum()
                ),
                "known_swap_or_favorability_right_rows": int(
                    structures.str.contains(
                        "swap|favorable|least favorable|most favorable",
                        regex=True,
                    ).sum()
                ),
                "known_multi_source_right_rows": int(
                    (
                        pd.to_numeric(
                            group[
                                "source_asset_count"
                            ],
                            errors="coerce",
                        ).fillna(1)
                        > 1
                    ).sum()
                ),
            }
        )

    return pd.DataFrame(grouped_rows)


def merge_horizon_audit(
    calendar: pd.DataFrame,
    year_coverage: pd.DataFrame,
    team_year_coverage: pd.DataFrame,
) -> pd.DataFrame:
    output = calendar.copy()

    year_columns = [
        column
        for column in [
            "draft_year",
            "processed_source_files_with_year",
            "first_round_source_files_with_year",
            "standalone_first_round_right_rows",
            "teams_with_standalone_first_round_right",
            "all_30_teams_have_first_round_right",
            "automatic_year_legality_ready",
        ]
        if column in year_coverage.columns
    ]

    if year_columns:
        output = output.merge(
            year_coverage[year_columns],
            how="left",
            on="draft_year",
            validate="many_to_one",
        )

    team_year_columns = [
        column
        for column in [
            "candidate_team",
            "draft_year",
            "standalone_first_round_right_rows",
            "first_round_right_ids",
            "source_assets",
            "has_any_standalone_first_round_right",
            "deterministic_stepien_availability_ready",
            "readiness_note",
        ]
        if column in team_year_coverage.columns
    ]

    if team_year_columns:
        team_year = team_year_coverage[
            team_year_columns
        ].rename(
            columns={
                "candidate_team": (
                    "team_abbreviation"
                ),
                "standalone_first_round_right_rows": (
                    "prior_audit_first_round_right_rows"
                ),
                "first_round_right_ids": (
                    "prior_audit_first_round_right_ids"
                ),
                "source_assets": (
                    "prior_audit_source_assets"
                ),
                "has_any_standalone_first_round_right": (
                    "prior_audit_has_any_first_round_right"
                ),
                "deterministic_stepien_availability_ready": (
                    "prior_audit_stepien_ready"
                ),
                "readiness_note": (
                    "prior_audit_readiness_note"
                ),
            }
        )

        output = output.merge(
            team_year,
            how="left",
            on=[
                "team_abbreviation",
                "draft_year",
            ],
            validate="one_to_one",
        )

    return output


def initialize_legality_fields(
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    output = calendar.copy()

    numeric_zero_columns = [
        "known_standalone_first_round_right_rows",
        "known_first_round_expected_pick_count",
        "known_first_round_value_score",
        "known_conditional_or_protected_right_rows",
        "known_swap_or_favorability_right_rows",
        "known_multi_source_right_rows",
    ]

    for column in numeric_zero_columns:
        if column not in output.columns:
            output[column] = 0

        output[column] = pd.to_numeric(
            output[column],
            errors="coerce",
        ).fillna(0)

    text_columns = [
        "known_first_round_right_ids",
        "known_first_round_right_names",
        "known_first_round_source_assets",
        "known_first_round_originating_teams",
    ]

    for column in text_columns:
        if column not in output.columns:
            output[column] = ""

        output[column] = (
            output[column]
            .fillna("")
            .astype(str)
        )

    output["canonical_inventory_year_flag"] = (
        output["draft_year"] <= 2029
    )

    output["extended_horizon_placeholder_flag"] = (
        output["draft_year"] >= 2030
    )

    output["own_first_round_source_asset_id"] = ""
    output["own_first_round_current_owner_team"] = ""
    output["own_first_round_control_status"] = "unresolved"
    output["own_first_round_retained_status"] = "unresolved"
    output["own_first_round_outgoing_obligation_status"] = (
        "unresolved"
    )
    output["own_first_round_swap_status"] = "unresolved"
    output["own_first_round_protection_status"] = (
        "unresolved"
    )
    output["own_first_round_encumbrance_status"] = (
        "unresolved"
    )
    output["deterministic_first_round_availability"] = (
        "unknown"
    )
    output["stepien_availability_after_proposed_trade"] = (
        "not_evaluated"
    )
    output["second_apron_frozen_pick_status"] = (
        "not_applicable"
    )
    output.loc[
        output[
            "second_apron_frozen_pick_target_flag"
        ],
        "second_apron_frozen_pick_status",
    ] = "unresolved"

    output["second_apron_freeze_trigger_cap_year"] = ""
    output["second_apron_unfreeze_condition"] = ""
    output["draft_pick_penalty_status"] = "unresolved"
    output["authoritative_source_name"] = ""
    output["authoritative_source_url"] = ""
    output["authoritative_source_as_of_date"] = ""
    output["source_effective_start_date"] = ""
    output["source_effective_end_date"] = ""
    output["source_authority_verified"] = False
    output["manual_review_required"] = True

    output["deterministic_calendar_ready"] = False

    output["calendar_readiness_status"] = np.where(
        output[
            "extended_horizon_placeholder_flag"
        ],
        "missing_2030_2034_authoritative_source_record",
        "known_rights_integrated_but_own_pick_control_unresolved",
    )

    output["calendar_scope_note"] = (
        "Known candidate first-round rights are summarized from the "
        "2027-2029 optimizer inventory. They do not prove control or "
        "retention of the team's own first-round pick. No row is legally "
        "approved until authoritative ownership, obligation, protection, "
        "swap, encumbrance, effective-date, Stepien, and frozen-pick fields "
        "are resolved."
    )

    output["calendar_release"] = RELEASE_NAME
    output["calendar_release_version"] = SCRIPT_VERSION

    return output


def build_manual_template(
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "team_abbreviation",
        "draft_year",
        "stepien_horizon_flag",
        "second_apron_frozen_pick_target_flag",
        "own_first_round_source_asset_id",
        "own_first_round_current_owner_team",
        "own_first_round_control_status",
        "own_first_round_retained_status",
        "own_first_round_outgoing_obligation_status",
        "own_first_round_swap_status",
        "own_first_round_protection_status",
        "own_first_round_encumbrance_status",
        "deterministic_first_round_availability",
        "second_apron_frozen_pick_status",
        "second_apron_freeze_trigger_cap_year",
        "second_apron_unfreeze_condition",
        "draft_pick_penalty_status",
        "authoritative_source_name",
        "authoritative_source_url",
        "authoritative_source_as_of_date",
        "source_effective_start_date",
        "source_effective_end_date",
        "source_authority_verified",
        "manual_review_required",
    ]

    output = calendar[columns].copy()

    output["manual_input_status"] = "pending"
    output["reviewer_notes"] = ""

    return output


def build_source_requirements() -> pd.DataFrame:
    rows = [
        {
            "field_name": "own_first_round_source_asset_id",
            "required": True,
            "allowed_values_or_format": (
                "Canonical team-year first-round source asset identifier"
            ),
            "purpose": (
                "Links the team-year row to the physical first-round pick."
            ),
        },
        {
            "field_name": "own_first_round_current_owner_team",
            "required": True,
            "allowed_values_or_format": "Three-letter NBA team code",
            "purpose": (
                "Establishes dated ownership of the team's own first-round pick."
            ),
        },
        {
            "field_name": "own_first_round_control_status",
            "required": True,
            "allowed_values_or_format": (
                "owned|owed_out|conditional|swap_encumbered|unknown"
            ),
            "purpose": (
                "Summarizes current legal control of the physical pick."
            ),
        },
        {
            "field_name": "own_first_round_retained_status",
            "required": True,
            "allowed_values_or_format": (
                "definitely_retained|not_definitely_retained|unknown"
            ),
            "purpose": (
                "Supports conservative Stepien availability testing."
            ),
        },
        {
            "field_name": "own_first_round_outgoing_obligation_status",
            "required": True,
            "allowed_values_or_format": (
                "none|active|conditional|exhausted|unknown"
            ),
            "purpose": (
                "Tracks conveyance obligations affecting the team-year pick."
            ),
        },
        {
            "field_name": "own_first_round_swap_status",
            "required": True,
            "allowed_values_or_format": (
                "none|swap_right_granted|swap_right_received|pooled|unknown"
            ),
            "purpose": (
                "Tracks swap and favorability structures."
            ),
        },
        {
            "field_name": "own_first_round_protection_status",
            "required": True,
            "allowed_values_or_format": (
                "unprotected|protected|conditional|not_applicable|unknown"
            ),
            "purpose": (
                "Tracks protection and rollover conditions."
            ),
        },
        {
            "field_name": "own_first_round_encumbrance_status",
            "required": True,
            "allowed_values_or_format": (
                "clear|encumbered|partially_encumbered|unknown"
            ),
            "purpose": (
                "Prevents overlapping rights from being treated independently."
            ),
        },
        {
            "field_name": "deterministic_first_round_availability",
            "required": True,
            "allowed_values_or_format": (
                "available|unavailable|conditional_not_counted|unknown"
            ),
            "purpose": (
                "The conservative team-year availability result used by Stepien."
            ),
        },
        {
            "field_name": "second_apron_frozen_pick_status",
            "required": (
                True
            ),
            "allowed_values_or_format": (
                "not_applicable|not_frozen|frozen|unfrozen|penalized|unknown"
            ),
            "purpose": (
                "Tracks the 2034 first-round pick restriction for the 2026-27 cap year."
            ),
        },
        {
            "field_name": "authoritative_source_url",
            "required": True,
            "allowed_values_or_format": "Source URL",
            "purpose": (
                "Provides traceable authority for ownership and obligation facts."
            ),
        },
        {
            "field_name": "authoritative_source_as_of_date",
            "required": True,
            "allowed_values_or_format": "YYYY-MM-DD",
            "purpose": (
                "Ensures the record is valid for the proposed trade date."
            ),
        },
        {
            "field_name": "source_effective_start_date",
            "required": True,
            "allowed_values_or_format": "YYYY-MM-DD",
            "purpose": (
                "Defines when the ownership or obligation state became effective."
            ),
        },
        {
            "field_name": "source_authority_verified",
            "required": True,
            "allowed_values_or_format": "TRUE|FALSE",
            "purpose": (
                "Blocks automatic legality until source authority is reviewed."
            ),
        },
    ]

    return pd.DataFrame(rows)


def build_team_summary(
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    return (
        calendar.groupby(
            "team_abbreviation",
            as_index=False,
        )
        .agg(
            calendar_rows=(
                "draft_year",
                "size",
            ),
            first_calendar_year=(
                "draft_year",
                "min",
            ),
            last_calendar_year=(
                "draft_year",
                "max",
            ),
            years_with_known_first_round_rights=(
                "known_standalone_first_round_right_rows",
                lambda series: int(
                    (series > 0).sum()
                ),
            ),
            known_first_round_right_rows=(
                "known_standalone_first_round_right_rows",
                "sum",
            ),
            known_first_round_value_score=(
                "known_first_round_value_score",
                "sum",
            ),
            deterministic_calendar_ready_rows=(
                "deterministic_calendar_ready",
                "sum",
            ),
            unresolved_rows=(
                "manual_review_required",
                "sum",
            ),
        )
        .sort_values(
            "team_abbreviation"
        )
        .reset_index(drop=True)
    )


def build_year_summary(
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    return (
        calendar.groupby(
            "draft_year",
            as_index=False,
        )
        .agg(
            calendar_rows=(
                "team_abbreviation",
                "size",
            ),
            teams=(
                "team_abbreviation",
                "nunique",
            ),
            teams_with_known_first_round_rights=(
                "known_standalone_first_round_right_rows",
                lambda series: int(
                    (series > 0).sum()
                ),
            ),
            known_first_round_right_rows=(
                "known_standalone_first_round_right_rows",
                "sum",
            ),
            known_first_round_value_score=(
                "known_first_round_value_score",
                "sum",
            ),
            deterministic_calendar_ready_rows=(
                "deterministic_calendar_ready",
                "sum",
            ),
            unresolved_rows=(
                "manual_review_required",
                "sum",
            ),
        )
        .sort_values("draft_year")
        .reset_index(drop=True)
    )


def build_validation(
    *,
    inputs: dict[str, pd.DataFrame],
    teams: list[str],
    expanded_rights: pd.DataFrame,
    calendar: pd.DataFrame,
    manual_template: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_rows = int(
        calendar.duplicated(
            subset=[
                "team_abbreviation",
                "draft_year",
            ]
        ).sum()
    )

    unknown_teams = sorted(
        set(
            calendar[
                "team_abbreviation"
            ]
        )
        - NBA_TEAM_CODES
    )

    missing_years = sorted(
        set(DRAFT_YEARS)
        - set(
            calendar[
                "draft_year"
            ]
        )
    )

    unexpected_years = sorted(
        set(
            calendar[
                "draft_year"
            ]
        )
        - set(DRAFT_YEARS)
    )

    standalone_rows = int(
        parse_bool_series(
            inputs[
                "picks"
            ][
                "standalone_trade_asset_flag"
            ]
        ).sum()
    )

    future_placeholder_rows = int(
        calendar[
            "extended_horizon_placeholder_flag"
        ].sum()
    )

    deterministic_ready_rows = int(
        calendar[
            "deterministic_calendar_ready"
        ].sum()
    )

    manually_blocked_rows = int(
        calendar[
            "manual_review_required"
        ].sum()
    )

    checks = [
        {
            "check_name": "canonical_pick_inventory_rows",
            "observed_value": len(
                inputs["picks"]
            ),
            "expected_value": (
                EXPECTED_PICK_INVENTORY_ROWS
            ),
            "passed": (
                len(
                    inputs["picks"]
                )
                == EXPECTED_PICK_INVENTORY_ROWS
            ),
        },
        {
            "check_name": "standalone_pick_inventory_rows",
            "observed_value": standalone_rows,
            "expected_value": (
                EXPECTED_STANDALONE_PICK_ROWS
            ),
            "passed": (
                standalone_rows
                == EXPECTED_STANDALONE_PICK_ROWS
            ),
        },
        {
            "check_name": "nba_team_count",
            "observed_value": len(teams),
            "expected_value": EXPECTED_TEAMS,
            "passed": len(teams) == EXPECTED_TEAMS,
        },
        {
            "check_name": "calendar_row_count",
            "observed_value": len(calendar),
            "expected_value": EXPECTED_CALENDAR_ROWS,
            "passed": (
                len(calendar)
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": "unique_team_year_rows",
            "observed_value": duplicate_rows,
            "expected_value": 0,
            "passed": duplicate_rows == 0,
        },
        {
            "check_name": "unknown_team_codes",
            "observed_value": len(unknown_teams),
            "expected_value": 0,
            "passed": len(unknown_teams) == 0,
        },
        {
            "check_name": "missing_required_draft_years",
            "observed_value": len(missing_years),
            "expected_value": 0,
            "passed": len(missing_years) == 0,
        },
        {
            "check_name": "unexpected_draft_years",
            "observed_value": len(unexpected_years),
            "expected_value": 0,
            "passed": len(unexpected_years) == 0,
        },
        {
            "check_name": "manual_template_row_count",
            "observed_value": len(
                manual_template
            ),
            "expected_value": EXPECTED_CALENDAR_ROWS,
            "passed": (
                len(manual_template)
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": "extended_horizon_placeholder_rows",
            "observed_value": future_placeholder_rows,
            "expected_value": (
                EXPECTED_TEAMS * 5
            ),
            "passed": (
                future_placeholder_rows
                == EXPECTED_TEAMS * 5
            ),
        },
        {
            "check_name": "no_calendar_rows_marked_automatically_ready",
            "observed_value": deterministic_ready_rows,
            "expected_value": 0,
            "passed": deterministic_ready_rows == 0,
        },
        {
            "check_name": "all_calendar_rows_require_manual_review",
            "observed_value": manually_blocked_rows,
            "expected_value": EXPECTED_CALENDAR_ROWS,
            "passed": (
                manually_blocked_rows
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": "known_first_round_rights_integrated",
            "observed_value": len(
                expanded_rights
            ),
            "expected_value": ">0",
            "passed": len(
                expanded_rights
            ) > 0,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY CALENDAR SCAFFOLD")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print(
        "Calendar horizon: "
        f"{min(DRAFT_YEARS)}-{max(DRAFT_YEARS)}"
    )
    print()

    print("[1/8] Loading canonical inventory and horizon audits")
    inputs = load_inputs()

    print("[2/8] Validating the 30-team universe")
    teams = prepare_teams(
        inputs["teams"]
    )

    print("[3/8] Expanding known standalone first-round rights")
    expanded_rights = expand_first_round_rights(
        inputs["picks"]
    )

    print("[4/8] Building the 30-team by 8-year calendar")
    calendar = base_calendar(teams)

    known_right_summary = summarize_known_rights(
        expanded_rights
    )

    calendar = calendar.merge(
        known_right_summary,
        how="left",
        on=[
            "team_abbreviation",
            "draft_year",
        ],
        validate="one_to_one",
    )

    calendar = merge_horizon_audit(
        calendar,
        inputs["year_coverage"],
        inputs["team_year_coverage"],
    )

    print("[5/8] Initializing unresolved legality fields")
    calendar = initialize_legality_fields(
        calendar
    )

    manual_template = build_manual_template(
        calendar
    )

    source_requirements = (
        build_source_requirements()
    )

    print("[6/8] Building team and year summaries")
    team_summary = build_team_summary(
        calendar
    )

    year_summary = build_year_summary(
        calendar
    )

    print("[7/8] Validating scaffold completeness")
    validation = build_validation(
        inputs=inputs,
        teams=teams,
        expanded_rights=expanded_rights,
        calendar=calendar,
        manual_template=manual_template,
    )

    failed = validation.loc[
        ~validation["passed"]
    ]

    calendar = calendar.sort_values(
        [
            "team_abbreviation",
            "draft_year",
        ]
    ).reset_index(drop=True)

    manual_template = manual_template.sort_values(
        [
            "team_abbreviation",
            "draft_year",
        ]
    ).reset_index(drop=True)

    calendar.to_parquet(
        CALENDAR_PARQUET_PATH,
        index=False,
    )

    calendar.to_csv(
        CALENDAR_CSV_PATH,
        index=False,
    )

    manual_template.to_csv(
        MANUAL_INPUT_TEMPLATE_PATH,
        index=False,
    )

    source_requirements.to_csv(
        SOURCE_REQUIREMENTS_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_HORIZON_SUMMARY_PATH,
        index=False,
    )

    year_summary.to_csv(
        YEAR_HORIZON_SUMMARY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "as_of_date": AS_OF_DATE.isoformat(),
        "draft_years": DRAFT_YEARS,
        "stepien_draft_years": sorted(
            STEPIEN_DRAFT_YEARS
        ),
        "frozen_pick_target_year": (
            FROZEN_PICK_TARGET_YEAR
        ),
        "team_rows": len(teams),
        "calendar_rows": len(calendar),
        "known_first_round_right_year_rows": int(
            len(expanded_rights)
        ),
        "calendar_rows_with_known_first_round_rights": int(
            (
                calendar[
                    "known_standalone_first_round_right_rows"
                ]
                > 0
            ).sum()
        ),
        "extended_horizon_placeholder_rows": int(
            calendar[
                "extended_horizon_placeholder_flag"
            ].sum()
        ),
        "deterministic_calendar_ready_rows": int(
            calendar[
                "deterministic_calendar_ready"
            ].sum()
        ),
        "manual_review_required_rows": int(
            calendar[
                "manual_review_required"
            ].sum()
        ),
        "validation_checks": len(validation),
        "validation_checks_passed": int(
            validation["passed"].sum()
        ),
        "scaffold_release_valid": bool(
            failed.empty
        ),
        "scope_note": (
            "This release is a data-contract scaffold, not a legality "
            "determination. It intentionally leaves every team-year row "
            "unresolved until authoritative ownership, obligation, "
            "protection, swap, encumbrance, effective-date, Stepien, and "
            "frozen-pick records are supplied."
        ),
        "output_files": {
            "calendar_parquet": str(
                CALENDAR_PARQUET_PATH
            ),
            "calendar_csv": str(
                CALENDAR_CSV_PATH
            ),
            "manual_input_template": str(
                MANUAL_INPUT_TEMPLATE_PATH
            ),
            "source_requirements": str(
                SOURCE_REQUIREMENTS_PATH
            ),
            "team_horizon_summary": str(
                TEAM_HORIZON_SUMMARY_PATH
            ),
            "year_horizon_summary": str(
                YEAR_HORIZON_SUMMARY_PATH
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
            json_safe(metadata),
            file,
            indent=2,
        )

    print("[8/8] Scaffold outputs saved")
    print()

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY CALENDAR SCAFFOLD CREATED")
    print("=" * 80)
    print(
        "Calendar rows: "
        f"{len(calendar):,}"
    )
    print(
        "Teams represented: "
        f"{calendar['team_abbreviation'].nunique():,}"
        f"/{EXPECTED_TEAMS}"
    )
    print(
        "Draft years represented: "
        f"{calendar['draft_year'].nunique():,}"
        f"/{len(DRAFT_YEARS)}"
    )
    print(
        "Known first-round right-year rows integrated: "
        f"{len(expanded_rights):,}"
    )
    print(
        "2030-2034 placeholder rows: "
        f"{int(calendar['extended_horizon_placeholder_flag'].sum()):,}"
    )
    print(
        "Deterministic ready rows: "
        f"{int(calendar['deterministic_calendar_ready'].sum()):,}"
    )
    print(
        "Manual-review rows: "
        f"{int(calendar['manual_review_required'].sum()):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Scaffold release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("YEAR HORIZON SUMMARY")
    print(
        year_summary.to_string(
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
        CALENDAR_PARQUET_PATH,
        CALENDAR_CSV_PATH,
        MANUAL_INPUT_TEMPLATE_PATH,
        SOURCE_REQUIREMENTS_PATH,
        TEAM_HORIZON_SUMMARY_PATH,
        YEAR_HORIZON_SUMMARY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        raise RuntimeError(
            "Future first-round legality calendar scaffold "
            "failed validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()