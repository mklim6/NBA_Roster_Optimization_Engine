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
    "future-first-round-legality-evidence-queue-v1-2026-08-04"
)

RELEASE_NAME = (
    "future_first_round_legality_evidence_queue_2027_2034_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

CALENDAR_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v1.parquet"
)

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

EVIDENCE_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_queue_2027_2034_v1.csv"
)

TEAM_EXPOSURE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_team_exposure_summary_v1.csv"
)

RIGHT_EXPOSURE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_right_exposure_summary_v1.csv"
)

YEAR_EXPOSURE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_year_exposure_summary_v1.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_queue_validation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_queue_metadata_v1.json"
)


EXPECTED_CALENDAR_ROWS = 240
EXPECTED_TEAMS = 30
EXPECTED_DRAFT_YEARS = 8
EXPECTED_ONE_FOR_ONE_ROWS = 28324
EXPECTED_TWO_FOR_ONE_ROWS = 282277

CALENDAR_REQUIRED_COLUMNS = [
    "team_abbreviation",
    "draft_year",
    "stepien_horizon_flag",
    "second_apron_frozen_pick_target_flag",
    "known_standalone_first_round_right_rows",
    "known_first_round_right_ids",
    "known_first_round_value_score",
    "deterministic_calendar_ready",
    "manual_review_required",
    "calendar_readiness_status",
]

PICK_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "right_display_name",
    "right_structure",
    "candidate_right_value_score",
    "standalone_trade_asset_flag",
]

PACKAGE_REQUIRED_COLUMNS = [
    "optimizer_candidate_id",
    "optimizer_branch",
    "base_package_id",
    "attached_pick_team",
    "attached_pick_right_id",
    "round_numbers",
    "draft_year_min",
    "draft_year_max",
    "attached_pick_value_score",
    "value_gap_improvement_score",
    "heuristic_optimizer_score_v1",
    "optimizer_package_final_legal",
]

RESEARCH_FIELDS = [
    "own_first_round_source_asset_id",
    "own_first_round_current_owner_team",
    "own_first_round_control_status",
    "own_first_round_retained_status",
    "own_first_round_outgoing_obligation_status",
    "own_first_round_swap_status",
    "own_first_round_protection_status",
    "own_first_round_encumbrance_status",
    "deterministic_first_round_availability",
    "authoritative_source_url",
    "authoritative_source_as_of_date",
    "source_effective_start_date",
    "source_authority_verified",
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


def normalize_team(series: pd.Series) -> pd.Series:
    return (
        series
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
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


def first_round_flag(series: pd.Series) -> pd.Series:
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


def load_inputs() -> dict[str, pd.DataFrame]:
    for path, label in [
        (
            CALENDAR_PATH,
            "future first-round legality calendar",
        ),
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

    calendar = pd.read_parquet(CALENDAR_PATH)
    picks = pd.read_parquet(PICK_INVENTORY_PATH)

    one_for_one = pd.read_parquet(
        ONE_FOR_ONE_CANDIDATES_PATH,
        columns=PACKAGE_REQUIRED_COLUMNS,
    )

    two_for_one = pd.read_parquet(
        TWO_FOR_ONE_CANDIDATES_PATH,
        columns=PACKAGE_REQUIRED_COLUMNS,
    )

    require_columns(
        calendar,
        CALENDAR_REQUIRED_COLUMNS,
        "Future first-round legality calendar",
    )

    require_columns(
        picks,
        PICK_REQUIRED_COLUMNS,
        "Canonical pick inventory",
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

    return {
        "calendar": calendar,
        "picks": picks,
        "one_for_one": one_for_one,
        "two_for_one": two_for_one,
    }


def prepare_pick_map(picks: pd.DataFrame) -> pd.DataFrame:
    output = picks.copy()

    output["candidate_team"] = normalize_team(
        output["candidate_team"]
    )

    output["standalone_trade_asset_flag"] = (
        parse_bool_series(
            output["standalone_trade_asset_flag"]
        )
    )

    output["first_round_flag"] = first_round_flag(
        output["round_numbers"]
    )

    output["draft_year_min"] = pd.to_numeric(
        output["draft_year_min"],
        errors="coerce",
    )

    output["draft_year_max"] = pd.to_numeric(
        output["draft_year_max"],
        errors="coerce",
    )

    output["candidate_right_value_score"] = (
        pd.to_numeric(
            output["candidate_right_value_score"],
            errors="coerce",
        )
    )

    output = output.loc[
        output["standalone_trade_asset_flag"]
        & output["first_round_flag"]
    ].copy()

    if output["future_pick_right_id"].duplicated().any():
        duplicates = output.loc[
            output["future_pick_right_id"].duplicated(
                keep=False
            )
        ]

        raise RuntimeError(
            "Duplicate standalone first-round right IDs were found:\n"
            + duplicates.head(20).to_string(index=False)
        )

    return output


def prepare_packages(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
) -> pd.DataFrame:
    output = pd.concat(
        [
            one_for_one,
            two_for_one,
        ],
        ignore_index=True,
        sort=False,
    )

    output["attached_pick_team"] = normalize_team(
        output["attached_pick_team"]
    )

    output["first_round_flag"] = first_round_flag(
        output["round_numbers"]
    )

    output["draft_year_min"] = pd.to_numeric(
        output["draft_year_min"],
        errors="coerce",
    )

    output["draft_year_max"] = pd.to_numeric(
        output["draft_year_max"],
        errors="coerce",
    )

    output["attached_pick_value_score"] = pd.to_numeric(
        output["attached_pick_value_score"],
        errors="coerce",
    )

    output["value_gap_improvement_score"] = (
        pd.to_numeric(
            output["value_gap_improvement_score"],
            errors="coerce",
        )
    )

    output["heuristic_optimizer_score_v1"] = (
        pd.to_numeric(
            output["heuristic_optimizer_score_v1"],
            errors="coerce",
        )
    )

    output["optimizer_package_final_legal"] = (
        parse_bool_series(
            output["optimizer_package_final_legal"]
        )
    )

    return output.loc[
        output["first_round_flag"]
    ].copy()


def expand_package_years(
    packages: pd.DataFrame,
    pick_map: pd.DataFrame,
) -> pd.DataFrame:
    pick_lookup = pick_map[
        [
            "future_pick_right_id",
            "candidate_team",
            "draft_year_min",
            "draft_year_max",
            "right_display_name",
            "right_structure",
            "candidate_right_value_score",
        ]
    ].rename(
        columns={
            "candidate_team": "inventory_candidate_team",
            "draft_year_min": "inventory_draft_year_min",
            "draft_year_max": "inventory_draft_year_max",
            "candidate_right_value_score": (
                "inventory_pick_value_score"
            ),
        }
    )

    merged = packages.merge(
        pick_lookup,
        how="left",
        left_on="attached_pick_right_id",
        right_on="future_pick_right_id",
        validate="many_to_one",
    )

    merged["pick_right_inventory_match"] = (
        merged["future_pick_right_id"].notna()
    )

    merged["pick_team_inventory_match"] = (
        merged["attached_pick_team"]
        .eq(
            merged["inventory_candidate_team"]
        )
    )

    rows = []

    for row in merged.itertuples(index=False):
        start_year = (
            int(row.inventory_draft_year_min)
            if not pd.isna(
                row.inventory_draft_year_min
            )
            else (
                int(row.draft_year_min)
                if not pd.isna(row.draft_year_min)
                else None
            )
        )

        end_year = (
            int(row.inventory_draft_year_max)
            if not pd.isna(
                row.inventory_draft_year_max
            )
            else (
                int(row.draft_year_max)
                if not pd.isna(row.draft_year_max)
                else start_year
            )
        )

        if start_year is None:
            continue

        if end_year is None:
            end_year = start_year

        for draft_year in range(
            start_year,
            end_year + 1,
        ):
            rows.append(
                {
                    "optimizer_candidate_id": (
                        row.optimizer_candidate_id
                    ),
                    "optimizer_branch": (
                        row.optimizer_branch
                    ),
                    "base_package_id": (
                        row.base_package_id
                    ),
                    "attached_pick_team": (
                        row.attached_pick_team
                    ),
                    "attached_pick_right_id": (
                        row.attached_pick_right_id
                    ),
                    "draft_year": draft_year,
                    "right_display_name": (
                        row.right_display_name
                    ),
                    "right_structure": (
                        row.right_structure
                    ),
                    "attached_pick_value_score": (
                        row.attached_pick_value_score
                    ),
                    "inventory_pick_value_score": (
                        row.inventory_pick_value_score
                    ),
                    "value_gap_improvement_score": (
                        row.value_gap_improvement_score
                    ),
                    "heuristic_optimizer_score_v1": (
                        row.heuristic_optimizer_score_v1
                    ),
                    "pick_right_inventory_match": bool(
                        row.pick_right_inventory_match
                    ),
                    "pick_team_inventory_match": bool(
                        row.pick_team_inventory_match
                    ),
                    "optimizer_package_final_legal": bool(
                        row.optimizer_package_final_legal
                    ),
                }
            )

    return pd.DataFrame(rows)


def summarize_right_exposure(
    package_years: pd.DataFrame,
) -> pd.DataFrame:
    if package_years.empty:
        return pd.DataFrame()

    rows = []

    for right_id, group in package_years.groupby(
        "attached_pick_right_id",
        sort=True,
    ):
        rows.append(
            {
                "attached_pick_right_id": right_id,
                "attached_pick_team": (
                    group[
                        "attached_pick_team"
                    ].iloc[0]
                ),
                "right_display_name": (
                    group[
                        "right_display_name"
                    ].iloc[0]
                ),
                "right_structure": (
                    group[
                        "right_structure"
                    ].iloc[0]
                ),
                "optimizer_candidate_rows": int(
                    group[
                        "optimizer_candidate_id"
                    ].nunique()
                ),
                "one_for_one_candidate_rows": int(
                    group.loc[
                        group[
                            "optimizer_branch"
                        ].eq("one_for_one"),
                        "optimizer_candidate_id",
                    ].nunique()
                ),
                "two_for_one_candidate_rows": int(
                    group.loc[
                        group[
                            "optimizer_branch"
                        ].eq("two_for_one"),
                        "optimizer_candidate_id",
                    ].nunique()
                ),
                "base_packages": int(
                    group[
                        "base_package_id"
                    ].nunique()
                ),
                "draft_years": "|".join(
                    str(year)
                    for year in sorted(
                        group[
                            "draft_year"
                        ].unique()
                    )
                ),
                "average_attached_pick_value_score": float(
                    group[
                        "attached_pick_value_score"
                    ].mean()
                ),
                "average_value_gap_improvement": float(
                    group[
                        "value_gap_improvement_score"
                    ].mean()
                ),
                "average_heuristic_optimizer_score": float(
                    group[
                        "heuristic_optimizer_score_v1"
                    ].mean()
                ),
                "maximum_heuristic_optimizer_score": float(
                    group[
                        "heuristic_optimizer_score_v1"
                    ].max()
                ),
                "inventory_match_all": bool(
                    group[
                        "pick_right_inventory_match"
                    ].all()
                ),
                "team_match_all": bool(
                    group[
                        "pick_team_inventory_match"
                    ].all()
                ),
                "final_legal_rows": int(
                    group[
                        "optimizer_package_final_legal"
                    ].sum()
                ),
            }
        )

    output = pd.DataFrame(rows)

    return output.sort_values(
        [
            "optimizer_candidate_rows",
            "maximum_heuristic_optimizer_score",
            "attached_pick_right_id",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def summarize_team_year_exposure(
    package_years: pd.DataFrame,
) -> pd.DataFrame:
    if package_years.empty:
        return pd.DataFrame(
            columns=[
                "team_abbreviation",
                "draft_year",
            ]
        )

    rows = []

    for (
        team,
        draft_year,
    ), group in package_years.groupby(
        [
            "attached_pick_team",
            "draft_year",
        ],
        sort=True,
    ):
        rows.append(
            {
                "team_abbreviation": team,
                "draft_year": int(draft_year),
                "optimizer_candidate_rows": int(
                    group[
                        "optimizer_candidate_id"
                    ].nunique()
                ),
                "one_for_one_candidate_rows": int(
                    group.loc[
                        group[
                            "optimizer_branch"
                        ].eq("one_for_one"),
                        "optimizer_candidate_id",
                    ].nunique()
                ),
                "two_for_one_candidate_rows": int(
                    group.loc[
                        group[
                            "optimizer_branch"
                        ].eq("two_for_one"),
                        "optimizer_candidate_id",
                    ].nunique()
                ),
                "unique_first_round_rights": int(
                    group[
                        "attached_pick_right_id"
                    ].nunique()
                ),
                "first_round_right_ids": "|".join(
                    sorted(
                        group[
                            "attached_pick_right_id"
                        ].astype(str)
                        .unique()
                    )
                ),
                "average_pick_value_score": float(
                    group[
                        "attached_pick_value_score"
                    ].mean()
                ),
                "total_candidate_value_gap_improvement": float(
                    group[
                        "value_gap_improvement_score"
                    ].sum()
                ),
                "average_candidate_value_gap_improvement": float(
                    group[
                        "value_gap_improvement_score"
                    ].mean()
                ),
                "average_heuristic_optimizer_score": float(
                    group[
                        "heuristic_optimizer_score_v1"
                    ].mean()
                ),
                "maximum_heuristic_optimizer_score": float(
                    group[
                        "heuristic_optimizer_score_v1"
                    ].max()
                ),
            }
        )

    return pd.DataFrame(rows)


def assign_priority(
    row: pd.Series,
    teams_with_first_round_exposure: set[str],
) -> tuple[int, str]:
    team = clean_text(
        row["team_abbreviation"]
    )

    year = int(row["draft_year"])

    candidate_rows = int(
        pd.to_numeric(
            pd.Series(
                [
                    row.get(
                        "optimizer_candidate_rows",
                        0,
                    )
                ]
            ),
            errors="coerce",
        )
        .fillna(0)
        .iloc[0]
    )

    known_right_rows = int(
        pd.to_numeric(
            pd.Series(
                [
                    row.get(
                        "known_standalone_first_round_right_rows",
                        0,
                    )
                ]
            ),
            errors="coerce",
        )
        .fillna(0)
        .iloc[0]
    )

    if candidate_rows > 0 and year <= 2029:
        return (
            1,
            "Directly affects existing first-round pick-attached optimizer packages.",
        )

    if (
        team in teams_with_first_round_exposure
        and 2030 <= year <= 2033
    ):
        return (
            2,
            "Required Stepien-horizon record for a team currently attaching first-round rights.",
        )

    if (
        team in teams_with_first_round_exposure
        and year == 2034
    ):
        return (
            3,
            "Required 2034 frozen-pick record for a team currently attaching first-round rights.",
        )

    if known_right_rows > 0 and year <= 2029:
        return (
            4,
            "Known first-round right exists, but no current optimizer package uses it.",
        )

    if 2030 <= year <= 2033:
        return (
            5,
            "Required to complete the leaguewide Stepien calendar.",
        )

    if year == 2034:
        return (
            6,
            "Required to complete leaguewide second-apron frozen-pick tracking.",
        )

    return (
        7,
        "Required for complete 2027-2029 own-first control coverage.",
    )


def build_evidence_queue(
    calendar: pd.DataFrame,
    team_year_exposure: pd.DataFrame,
) -> pd.DataFrame:
    output = calendar.copy()

    output["team_abbreviation"] = normalize_team(
        output["team_abbreviation"]
    )

    output = output.merge(
        team_year_exposure,
        how="left",
        on=[
            "team_abbreviation",
            "draft_year",
        ],
        validate="one_to_one",
    )

    numeric_zero_columns = [
        "optimizer_candidate_rows",
        "one_for_one_candidate_rows",
        "two_for_one_candidate_rows",
        "unique_first_round_rights",
        "average_pick_value_score",
        "total_candidate_value_gap_improvement",
        "average_candidate_value_gap_improvement",
        "average_heuristic_optimizer_score",
        "maximum_heuristic_optimizer_score",
    ]

    for column in numeric_zero_columns:
        if column not in output.columns:
            output[column] = 0

        output[column] = pd.to_numeric(
            output[column],
            errors="coerce",
        ).fillna(0)

    if "first_round_right_ids" not in output.columns:
        output["first_round_right_ids"] = ""

    output["first_round_right_ids"] = (
        output["first_round_right_ids"]
        .fillna("")
        .astype(str)
    )

    teams_with_exposure = set(
        output.loc[
            output["optimizer_candidate_rows"] > 0,
            "team_abbreviation",
        ]
    )

    priorities = output.apply(
        lambda row: assign_priority(
            row,
            teams_with_exposure,
        ),
        axis=1,
    )

    output["evidence_priority"] = [
        value[0]
        for value in priorities
    ]

    output["evidence_priority_reason"] = [
        value[1]
        for value in priorities
    ]

    output["required_research_fields"] = "|".join(
        RESEARCH_FIELDS
    )

    output["research_status"] = "not_started"
    output["authoritative_source_count"] = 0
    output["authoritative_source_ready"] = False
    output["automatic_legality_ready"] = False

    candidate_rank = (
        output[
            "optimizer_candidate_rows"
        ]
        .rank(
            method="dense",
            ascending=False,
        )
        .astype(int)
    )

    score_rank = (
        output[
            "maximum_heuristic_optimizer_score"
        ]
        .rank(
            method="dense",
            ascending=False,
        )
        .astype(int)
    )

    output["candidate_exposure_rank"] = (
        candidate_rank
    )

    output["candidate_score_rank"] = score_rank

    output = output.sort_values(
        [
            "evidence_priority",
            "optimizer_candidate_rows",
            "maximum_heuristic_optimizer_score",
            "known_standalone_first_round_right_rows",
            "team_abbreviation",
            "draft_year",
        ],
        ascending=[
            True,
            False,
            False,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)

    output["evidence_queue_rank"] = (
        np.arange(
            1,
            len(output) + 1,
        )
    )

    return output


def build_team_summary(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for team, group in queue.groupby(
        "team_abbreviation",
        sort=True,
    ):
        rows.append(
            {
                "team_abbreviation": team,
                "calendar_rows": int(
                    len(group)
                ),
                "direct_package_exposure_rows": int(
                    (
                        group[
                            "optimizer_candidate_rows"
                        ]
                        > 0
                    ).sum()
                ),
                "optimizer_candidate_rows": int(
                    group[
                        "optimizer_candidate_rows"
                    ].sum()
                ),
                "one_for_one_candidate_rows": int(
                    group[
                        "one_for_one_candidate_rows"
                    ].sum()
                ),
                "two_for_one_candidate_rows": int(
                    group[
                        "two_for_one_candidate_rows"
                    ].sum()
                ),
                "unique_first_round_rights": int(
                    len(
                        {
                            right_id
                            for value in group[
                                "first_round_right_ids"
                            ]
                            for right_id in clean_text(
                                value
                            ).split("|")
                            if right_id
                        }
                    )
                ),
                "highest_priority": int(
                    group[
                        "evidence_priority"
                    ].min()
                ),
                "first_queue_rank": int(
                    group[
                        "evidence_queue_rank"
                    ].min()
                ),
                "unresolved_rows": int(
                    (
                        ~group[
                            "automatic_legality_ready"
                        ]
                    ).sum()
                ),
            }
        )

    return pd.DataFrame(rows).sort_values(
        [
            "highest_priority",
            "optimizer_candidate_rows",
            "team_abbreviation",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(drop=True)


def build_year_summary(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    return (
        queue.groupby(
            "draft_year",
            as_index=False,
        )
        .agg(
            calendar_rows=(
                "team_abbreviation",
                "size",
            ),
            teams_with_package_exposure=(
                "optimizer_candidate_rows",
                lambda series: int(
                    (series > 0).sum()
                ),
            ),
            optimizer_candidate_rows=(
                "optimizer_candidate_rows",
                "sum",
            ),
            unique_first_round_rights=(
                "unique_first_round_rights",
                "sum",
            ),
            known_first_round_right_rows=(
                "known_standalone_first_round_right_rows",
                "sum",
            ),
            priority_one_rows=(
                "evidence_priority",
                lambda series: int(
                    (series == 1).sum()
                ),
            ),
            unresolved_rows=(
                "automatic_legality_ready",
                lambda series: int(
                    (~series).sum()
                ),
            ),
        )
        .sort_values("draft_year")
        .reset_index(drop=True)
    )


def build_validation(
    *,
    inputs: dict[str, pd.DataFrame],
    pick_map: pd.DataFrame,
    packages: pd.DataFrame,
    package_years: pd.DataFrame,
    queue: pd.DataFrame,
    right_summary: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_queue_rows = int(
        queue.duplicated(
            subset=[
                "team_abbreviation",
                "draft_year",
            ]
        ).sum()
    )

    missing_inventory_matches = int(
        (
            ~package_years[
                "pick_right_inventory_match"
            ]
        ).sum()
    )

    team_mismatches = int(
        (
            ~package_years[
                "pick_team_inventory_match"
            ]
        ).sum()
    )

    final_legal_rows = int(
        packages[
            "optimizer_package_final_legal"
        ].sum()
    )

    queue_exposure_rows = int(
        (
            queue[
                "optimizer_candidate_rows"
            ]
            > 0
        ).sum()
    )

    package_year_keys = set(
        zip(
            package_years[
                "attached_pick_team"
            ],
            package_years[
                "draft_year"
            ],
        )
    )

    queue_keys = set(
        zip(
            queue[
                "team_abbreviation"
            ],
            queue[
                "draft_year"
            ],
        )
    )

    unmatched_package_year_keys = len(
        package_year_keys - queue_keys
    )

    checks = [
        {
            "check_name": "calendar_row_count",
            "observed_value": len(
                inputs["calendar"]
            ),
            "expected_value": EXPECTED_CALENDAR_ROWS,
            "passed": (
                len(inputs["calendar"])
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": "one_for_one_candidate_rows",
            "observed_value": len(
                inputs["one_for_one"]
            ),
            "expected_value": EXPECTED_ONE_FOR_ONE_ROWS,
            "passed": (
                len(inputs["one_for_one"])
                == EXPECTED_ONE_FOR_ONE_ROWS
            ),
        },
        {
            "check_name": "two_for_one_candidate_rows",
            "observed_value": len(
                inputs["two_for_one"]
            ),
            "expected_value": EXPECTED_TWO_FOR_ONE_ROWS,
            "passed": (
                len(inputs["two_for_one"])
                == EXPECTED_TWO_FOR_ONE_ROWS
            ),
        },
        {
            "check_name": "standalone_first_round_rights_found",
            "observed_value": len(pick_map),
            "expected_value": ">0",
            "passed": len(pick_map) > 0,
        },
        {
            "check_name": "first_round_package_rows_found",
            "observed_value": len(packages),
            "expected_value": ">0",
            "passed": len(packages) > 0,
        },
        {
            "check_name": "package_right_inventory_matches",
            "observed_value": missing_inventory_matches,
            "expected_value": 0,
            "passed": missing_inventory_matches == 0,
        },
        {
            "check_name": "package_pick_team_matches",
            "observed_value": team_mismatches,
            "expected_value": 0,
            "passed": team_mismatches == 0,
        },
        {
            "check_name": "pick_packages_not_final_legal",
            "observed_value": final_legal_rows,
            "expected_value": 0,
            "passed": final_legal_rows == 0,
        },
        {
            "check_name": "evidence_queue_row_count",
            "observed_value": len(queue),
            "expected_value": EXPECTED_CALENDAR_ROWS,
            "passed": len(queue) == EXPECTED_CALENDAR_ROWS,
        },
        {
            "check_name": "unique_evidence_queue_team_year_rows",
            "observed_value": duplicate_queue_rows,
            "expected_value": 0,
            "passed": duplicate_queue_rows == 0,
        },
        {
            "check_name": "queue_team_count",
            "observed_value": int(
                queue[
                    "team_abbreviation"
                ].nunique()
            ),
            "expected_value": EXPECTED_TEAMS,
            "passed": (
                queue[
                    "team_abbreviation"
                ].nunique()
                == EXPECTED_TEAMS
            ),
        },
        {
            "check_name": "queue_draft_year_count",
            "observed_value": int(
                queue[
                    "draft_year"
                ].nunique()
            ),
            "expected_value": EXPECTED_DRAFT_YEARS,
            "passed": (
                queue[
                    "draft_year"
                ].nunique()
                == EXPECTED_DRAFT_YEARS
            ),
        },
        {
            "check_name": "package_year_keys_map_to_queue",
            "observed_value": unmatched_package_year_keys,
            "expected_value": 0,
            "passed": unmatched_package_year_keys == 0,
        },
        {
            "check_name": "direct_exposure_queue_rows_found",
            "observed_value": queue_exposure_rows,
            "expected_value": ">0",
            "passed": queue_exposure_rows > 0,
        },
        {
            "check_name": "right_exposure_summary_created",
            "observed_value": len(
                right_summary
            ),
            "expected_value": ">0",
            "passed": len(right_summary) > 0,
        },
        {
            "check_name": "no_queue_rows_marked_automatic_legal",
            "observed_value": int(
                queue[
                    "automatic_legality_ready"
                ].sum()
            ),
            "expected_value": 0,
            "passed": int(
                queue[
                    "automatic_legality_ready"
                ].sum()
            )
            == 0,
        },
    ]

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY EVIDENCE QUEUE")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/8] Loading calendar, inventory, and optimizer candidates")
    inputs = load_inputs()

    print("[2/8] Preparing standalone first-round right map")
    pick_map = prepare_pick_map(
        inputs["picks"]
    )

    print("[3/8] Filtering first-round optimizer packages")
    packages = prepare_packages(
        inputs["one_for_one"],
        inputs["two_for_one"],
    )

    print("[4/8] Expanding package exposure by draft year")
    package_years = expand_package_years(
        packages,
        pick_map,
    )

    print("[5/8] Summarizing right and team-year exposure")
    right_summary = summarize_right_exposure(
        package_years
    )

    team_year_exposure = (
        summarize_team_year_exposure(
            package_years
        )
    )

    print("[6/8] Ranking the 240-row evidence queue")
    queue = build_evidence_queue(
        inputs["calendar"],
        team_year_exposure,
    )

    team_summary = build_team_summary(queue)
    year_summary = build_year_summary(queue)

    print("[7/8] Validating exposure and queue integrity")
    validation = build_validation(
        inputs=inputs,
        pick_map=pick_map,
        packages=packages,
        package_years=package_years,
        queue=queue,
        right_summary=right_summary,
    )

    failed = validation.loc[
        ~validation["passed"]
    ]

    queue.to_csv(
        EVIDENCE_QUEUE_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_EXPOSURE_SUMMARY_PATH,
        index=False,
    )

    right_summary.to_csv(
        RIGHT_EXPOSURE_SUMMARY_PATH,
        index=False,
    )

    year_summary.to_csv(
        YEAR_EXPOSURE_SUMMARY_PATH,
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
        "calendar_rows": int(
            len(queue)
        ),
        "standalone_first_round_rights": int(
            len(pick_map)
        ),
        "first_round_optimizer_package_rows": int(
            len(packages)
        ),
        "first_round_package_year_rows": int(
            len(package_years)
        ),
        "first_round_rights_used_by_optimizer": int(
            len(right_summary)
        ),
        "teams_with_first_round_package_exposure": int(
            queue.loc[
                queue[
                    "optimizer_candidate_rows"
                ]
                > 0,
                "team_abbreviation",
            ].nunique()
        ),
        "direct_package_exposure_team_year_rows": int(
            (
                queue[
                    "optimizer_candidate_rows"
                ]
                > 0
            ).sum()
        ),
        "priority_one_rows": int(
            (
                queue[
                    "evidence_priority"
                ]
                == 1
            ).sum()
        ),
        "validation_checks": int(
            len(validation)
        ),
        "validation_checks_passed": int(
            validation[
                "passed"
            ].sum()
        ),
        "evidence_queue_release_valid": bool(
            failed.empty
        ),
        "scope_note": (
            "This queue prioritizes evidence collection only. It does not "
            "declare any team-year first-round record or optimizer package "
            "legally valid."
        ),
        "output_files": {
            "evidence_queue": str(
                EVIDENCE_QUEUE_PATH
            ),
            "team_exposure_summary": str(
                TEAM_EXPOSURE_SUMMARY_PATH
            ),
            "right_exposure_summary": str(
                RIGHT_EXPOSURE_SUMMARY_PATH
            ),
            "year_exposure_summary": str(
                YEAR_EXPOSURE_SUMMARY_PATH
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

    print("[8/8] Evidence queue outputs saved")
    print()

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY EVIDENCE QUEUE CREATED")
    print("=" * 80)
    print(
        "Evidence queue rows: "
        f"{len(queue):,}"
    )
    print(
        "Standalone first-round rights: "
        f"{len(pick_map):,}"
    )
    print(
        "First-round optimizer package rows: "
        f"{len(packages):,}"
    )
    print(
        "First-round package-year rows: "
        f"{len(package_years):,}"
    )
    print(
        "First-round rights used by optimizer: "
        f"{len(right_summary):,}"
    )
    print(
        "Teams with direct first-round exposure: "
        f"{queue.loc[queue['optimizer_candidate_rows'] > 0, 'team_abbreviation'].nunique():,}"
        f"/{EXPECTED_TEAMS}"
    )
    print(
        "Priority-one team-year rows: "
        f"{int((queue['evidence_priority'] == 1).sum()):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Evidence queue release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("TOP 30 EVIDENCE QUEUE ROWS")
    print(
        queue[
            [
                "evidence_queue_rank",
                "evidence_priority",
                "team_abbreviation",
                "draft_year",
                "optimizer_candidate_rows",
                "one_for_one_candidate_rows",
                "two_for_one_candidate_rows",
                "unique_first_round_rights",
                "maximum_heuristic_optimizer_score",
                "known_standalone_first_round_right_rows",
                "evidence_priority_reason",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )
    print()

    print("YEAR EXPOSURE SUMMARY")
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
        EVIDENCE_QUEUE_PATH,
        TEAM_EXPOSURE_SUMMARY_PATH,
        RIGHT_EXPOSURE_SUMMARY_PATH,
        YEAR_EXPOSURE_SUMMARY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        raise RuntimeError(
            "Future first-round legality evidence queue "
            "failed validation:\n"
            + failed.to_string(index=False)
        )


if __name__ == "__main__":
    main()