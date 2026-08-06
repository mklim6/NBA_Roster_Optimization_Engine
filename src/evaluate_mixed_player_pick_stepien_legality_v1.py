from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "mixed-player-pick-stepien-legality-v1-conservative-2026-08-04"
)
RELEASE_NAME = "mixed_player_pick_stepien_legality_2026_27_v1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

CALENDAR_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v5_evidence_ingested.parquet"
)
PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)
ONE_FOR_ONE_INPUT_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_mixed_player_pick_candidates_2026_27_v3.parquet"
)
TWO_FOR_ONE_INPUT_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_mixed_player_pick_candidates_2026_27_v3.parquet"
)

ONE_FOR_ONE_OUTPUT_PATH = (
    OUTPUT_DIRECTORY
    / "one_for_one_mixed_player_pick_candidates_2026_27_v4_stepien_evaluated.parquet"
)
TWO_FOR_ONE_OUTPUT_PATH = (
    OUTPUT_DIRECTORY
    / "two_for_one_mixed_player_pick_candidates_2026_27_v4_stepien_evaluated.parquet"
)
RIGHT_EVALUATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_right_evaluation_v1.csv"
)
PACKAGE_EVALUATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_package_evaluation_v1.parquet"
)
BASELINE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_team_year_baseline_v1.csv"
)
RECOMMENDATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_screened_team_recommendations_2026_27_v1.csv"
)
VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_legality_validation_v1.csv"
)
METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_legality_metadata_v1.json"
)

DEFAULT_TRADE_DATE = date(2026, 8, 4)
STEPIEN_DRAFT_YEARS = list(range(2027, 2034))
FROZEN_PICK_DRAFT_YEAR = 2034
CALENDAR_DRAFT_YEARS = list(range(2027, 2035))
EXPECTED_TEAMS = 30
EXPECTED_CALENDAR_ROWS = 240
EXPECTED_INVENTORY_ROWS = 174
EXPECTED_STANDALONE_RIGHTS = 172
EXPECTED_ONE_FOR_ONE_ROWS = 28324
EXPECTED_TWO_FOR_ONE_ROWS = 282277
TOP_RECOMMENDATIONS_PER_TEAM = 50

TEAM_PATTERN = re.compile(r"^[A-Z]{3}$")

CALENDAR_REQUIRED_COLUMNS = [
    "team_abbreviation",
    "draft_year",
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
    "authoritative_source_as_of_date",
    "source_effective_start_date",
    "source_effective_end_date",
    "source_authority_verified",
    "deterministic_calendar_ready",
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
]

PACKAGE_REQUIRED_COLUMNS = [
    "optimizer_candidate_id",
    "optimizer_branch",
    "team_a",
    "team_b",
    "attached_pick_team",
    "attached_pick_right_id",
    "optimizer_package_legality_status",
    "optimizer_package_final_legal",
]

PACKAGE_EVALUATION_COLUMNS = [
    "optimizer_candidate_id",
    "optimizer_branch",
    "attached_pick_team",
    "attached_pick_right_id",
    "pick_right_matched_to_inventory",
    "attached_pick_team_matches_inventory",
    "first_round_right_flag",
    "stepien_evaluation_status",
    "stepien_legality_passed",
    "stepien_manual_review_required",
    "stepien_baseline_violating_pairs",
    "stepien_post_trade_violating_pairs",
    "stepien_evaluated_scenario_count",
    "stepien_source_match_method",
    "stepien_matched_source_asset_ids",
    "stepien_unmatched_source_asset_ids",
    "stepien_worst_case_removed_source_asset_id",
    "stepien_worst_case_removed_draft_year",
    "stepien_worst_case_removed_deterministic_pick_count",
    "frozen_pick_evaluation_status",
    "frozen_pick_legality_passed",
    "calendar_authority_and_date_passed",
    "package_pick_legality_stage_passed",
    "package_pick_legality_manual_review_required",
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


def normalize_status(value: Any) -> str:
    return clean_text(value).lower().replace("-", "_").replace(" ", "_")


def normalize_team(value: Any) -> str:
    return clean_text(value).upper()


def parse_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return normalize_status(value) in {"true", "1", "yes", "passed"}


def parse_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    return series.map(parse_bool).astype(bool)


def parse_date(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_tokens(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return sorted(
                    {
                        clean_text(item)
                        for item in payload
                        if clean_text(item)
                    }
                )
        except json.JSONDecodeError:
            pass

    return sorted(
        {
            clean_text(token)
            for token in re.split(r"[|;]", text)
            if clean_text(token)
        }
    )


def parse_rounds(value: Any) -> set[int]:
    normalized = normalize_status(value)
    rounds = set()
    for match in re.findall(r"(?<!\d)[12](?!\d)", clean_text(value)):
        rounds.add(int(match))
    if "first" in normalized:
        rounds.add(1)
    if "second" in normalized:
        rounds.add(2)
    return rounds


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
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


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required {label} was not found:\n{path}")


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{label} is missing required columns:\n" + "\n".join(missing)
        )


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path, label in [
        (CALENDAR_PATH, "evidence-ingested first-round legality calendar"),
        (PICK_INVENTORY_PATH, "canonical future-pick inventory"),
        (ONE_FOR_ONE_INPUT_PATH, "one-for-one mixed candidates"),
        (TWO_FOR_ONE_INPUT_PATH, "two-for-one mixed candidates"),
    ]:
        require_file(path, label)

    calendar = pd.read_parquet(CALENDAR_PATH)
    inventory = pd.read_parquet(PICK_INVENTORY_PATH)
    one_for_one = pd.read_parquet(ONE_FOR_ONE_INPUT_PATH)
    two_for_one = pd.read_parquet(TWO_FOR_ONE_INPUT_PATH)

    require_columns(calendar, CALENDAR_REQUIRED_COLUMNS, "Legality calendar")
    require_columns(inventory, INVENTORY_REQUIRED_COLUMNS, "Pick inventory")
    require_columns(one_for_one, PACKAGE_REQUIRED_COLUMNS, "One-for-one candidates")
    require_columns(two_for_one, PACKAGE_REQUIRED_COLUMNS, "Two-for-one candidates")

    return calendar, inventory, one_for_one, two_for_one


def normalize_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    output = calendar.copy()
    output["team_abbreviation"] = output["team_abbreviation"].map(normalize_team)
    output["own_first_round_current_owner_team"] = output[
        "own_first_round_current_owner_team"
    ].map(normalize_team)
    output["draft_year"] = pd.to_numeric(output["draft_year"], errors="raise").astype(int)

    status_columns = [
        "own_first_round_control_status",
        "own_first_round_retained_status",
        "own_first_round_outgoing_obligation_status",
        "own_first_round_swap_status",
        "own_first_round_protection_status",
        "own_first_round_encumbrance_status",
        "deterministic_first_round_availability",
        "second_apron_frozen_pick_status",
    ]
    for column in status_columns:
        output[column] = output[column].map(normalize_status)

    output["source_authority_verified"] = parse_bool_series(
        output["source_authority_verified"]
    )
    output["deterministic_calendar_ready"] = parse_bool_series(
        output["deterministic_calendar_ready"]
    )
    output["own_first_round_source_asset_id"] = output[
        "own_first_round_source_asset_id"
    ].map(clean_text)

    if output[["team_abbreviation", "draft_year"]].duplicated().any():
        raise RuntimeError("The legality calendar has duplicate team-year rows.")
    if output["own_first_round_source_asset_id"].eq("").any():
        raise RuntimeError("The legality calendar has blank source-asset IDs.")
    if output["own_first_round_source_asset_id"].duplicated().any():
        duplicates = output.loc[
            output["own_first_round_source_asset_id"].duplicated(False),
            "own_first_round_source_asset_id",
        ].unique()
        raise RuntimeError(
            "The legality calendar has duplicate source-asset IDs:\n"
            + "\n".join(map(str, duplicates[:30]))
        )

    return output.sort_values(["team_abbreviation", "draft_year"]).reset_index(drop=True)


def normalize_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    output = inventory.copy()
    output["future_pick_right_id"] = output["future_pick_right_id"].map(clean_text)
    output["candidate_team"] = output["candidate_team"].map(normalize_team)
    output["standalone_trade_asset_flag"] = parse_bool_series(
        output["standalone_trade_asset_flag"]
    )
    output["draft_year_min"] = pd.to_numeric(
        output["draft_year_min"], errors="coerce"
    )
    output["draft_year_max"] = pd.to_numeric(
        output["draft_year_max"], errors="coerce"
    )
    if output["future_pick_right_id"].eq("").any():
        raise RuntimeError("The pick inventory has blank right IDs.")
    if output["future_pick_right_id"].duplicated().any():
        raise RuntimeError("The pick inventory has duplicate right IDs.")
    return output


def valid_team(value: Any, known_teams: set[str]) -> bool:
    team = normalize_team(value)
    return bool(TEAM_PATTERN.fullmatch(team) and team in known_teams)


def calendar_row_is_current(row: pd.Series, trade_date: date) -> bool:
    if not parse_bool(row.get("source_authority_verified", False)):
        return False
    as_of = parse_date(row.get("authoritative_source_as_of_date"))
    effective_start = parse_date(row.get("source_effective_start_date"))
    effective_end = parse_date(row.get("source_effective_end_date"))
    if as_of is None or effective_start is None:
        return False
    if as_of < trade_date or effective_start > trade_date:
        return False
    if effective_end is not None and effective_end < trade_date:
        return False
    return True


def deterministic_owner_team(row: pd.Series, known_teams: set[str]) -> str:
    origin_team = normalize_team(row["team_abbreviation"])
    current_owner = normalize_team(row["own_first_round_current_owner_team"])
    deterministic = normalize_status(row["deterministic_first_round_availability"])
    control = normalize_status(row["own_first_round_control_status"])
    outgoing = normalize_status(row["own_first_round_outgoing_obligation_status"])
    swap = normalize_status(row["own_first_round_swap_status"])
    protection = normalize_status(row["own_first_round_protection_status"])

    if (
        deterministic == "available"
        and (
            not valid_team(current_owner, known_teams)
            or current_owner == origin_team
        )
    ):
        return origin_team

    deterministic_outgoing_conveyance = bool(
        control == "owed_out"
        and outgoing == "active"
        and swap == "none"
        and protection in {"unprotected", "not_applicable"}
        and valid_team(current_owner, known_teams)
        and current_owner != origin_team
    )
    if deterministic_outgoing_conveyance:
        return current_owner

    return ""


def build_baseline(
    calendar: pd.DataFrame,
    trade_date: date,
) -> tuple[pd.DataFrame, dict[tuple[str, int], int], dict[str, pd.Series]]:
    known_teams = set(calendar["team_abbreviation"].unique())
    working = calendar.copy()
    working["calendar_authority_and_date_passed"] = working.apply(
        calendar_row_is_current, axis=1, trade_date=trade_date
    )
    working["deterministic_owner_team"] = working.apply(
        deterministic_owner_team, axis=1, known_teams=known_teams
    )
    working["counts_as_deterministically_retained_first"] = working[
        "deterministic_owner_team"
    ].ne("")

    count_lookup = {
        (team, year): 0
        for team in sorted(known_teams)
        for year in CALENDAR_DRAFT_YEARS
    }
    for row in working.itertuples(index=False):
        owner = clean_text(row.deterministic_owner_team)
        year = int(row.draft_year)
        if owner and year in CALENDAR_DRAFT_YEARS:
            count_lookup[(owner, year)] = count_lookup.get((owner, year), 0) + 1

    rows = []
    for team in sorted(known_teams):
        for year in CALENDAR_DRAFT_YEARS:
            origin_row = working.loc[
                working["team_abbreviation"].eq(team)
                & working["draft_year"].eq(year)
            ]
            rows.append(
                {
                    "team_abbreviation": team,
                    "draft_year": year,
                    "deterministic_retained_first_count": count_lookup[(team, year)],
                    "own_pick_deterministic_availability": (
                        clean_text(origin_row.iloc[0]["deterministic_first_round_availability"])
                        if len(origin_row) == 1
                        else "missing"
                    ),
                    "calendar_authority_and_date_passed": bool(
                        origin_row.iloc[0]["calendar_authority_and_date_passed"]
                        if len(origin_row) == 1
                        else False
                    ),
                }
            )

    source_lookup = {
        clean_text(row["own_first_round_source_asset_id"]): row
        for _, row in working.iterrows()
    }
    return pd.DataFrame(rows), count_lookup, source_lookup


def violating_pairs(counts: dict[int, int]) -> list[str]:
    return [
        f"{year}-{year + 1}"
        for year in STEPIEN_DRAFT_YEARS[:-1]
        if counts.get(year, 0) + counts.get(year + 1, 0) < 1
    ]


def fallback_source_rows(
    right: pd.Series,
    calendar: pd.DataFrame,
) -> list[pd.Series]:
    origin_teams = [normalize_team(team) for team in parse_tokens(right["originating_teams"])]
    origin_teams = [team for team in origin_teams if team]
    minimum = pd.to_numeric(pd.Series([right["draft_year_min"]]), errors="coerce").iloc[0]
    maximum = pd.to_numeric(pd.Series([right["draft_year_max"]]), errors="coerce").iloc[0]
    if pd.isna(minimum) or pd.isna(maximum) or not origin_teams:
        return []
    years = list(range(int(minimum), int(maximum) + 1))
    matches = calendar.loc[
        calendar["team_abbreviation"].isin(origin_teams)
        & calendar["draft_year"].isin(years)
    ]
    return [row for _, row in matches.iterrows()]


def match_right_to_calendar(
    right: pd.Series,
    calendar: pd.DataFrame,
    source_lookup: dict[str, pd.Series],
) -> tuple[list[pd.Series], str, list[str], list[str]]:
    requested_ids = parse_tokens(right["source_assets"])
    matched_rows = [source_lookup[source_id] for source_id in requested_ids if source_id in source_lookup]
    unmatched_ids = [source_id for source_id in requested_ids if source_id not in source_lookup]

    if requested_ids and not unmatched_ids:
        return matched_rows, "exact_source_asset_id", requested_ids, []

    fallback = fallback_source_rows(right, calendar)
    if fallback:
        deduplicated = {
            clean_text(row["own_first_round_source_asset_id"]): row for row in fallback
        }
        return (
            list(deduplicated.values()),
            "fallback_origin_team_and_year_manual_review",
            requested_ids,
            unmatched_ids,
        )

    return [], "unmatched_manual_review", requested_ids, unmatched_ids


def evaluate_frozen_pick(
    first_round_right: bool,
    matched_rows: list[pd.Series],
    mapping_exact: bool,
    draft_year_max: Any,
) -> tuple[str, bool, bool]:
    if not first_round_right:
        return "not_applicable_non_first_round_right", True, False

    maximum = pd.to_numeric(pd.Series([draft_year_max]), errors="coerce").iloc[0]
    touches_2034 = bool(
        any(int(row["draft_year"]) == FROZEN_PICK_DRAFT_YEAR for row in matched_rows)
        or (not pd.isna(maximum) and int(maximum) >= FROZEN_PICK_DRAFT_YEAR)
    )
    if not touches_2034:
        return "not_applicable_outside_2034", True, False
    if not mapping_exact:
        return "manual_review_2034_source_mapping", False, True

    statuses = {
        normalize_status(row["second_apron_frozen_pick_status"])
        for row in matched_rows
        if int(row["draft_year"]) == FROZEN_PICK_DRAFT_YEAR
    }
    if not statuses:
        return "manual_review_missing_2034_calendar_row", False, True
    if statuses & {"frozen", "penalized"}:
        return "blocked_frozen_or_penalized_2034_first", False, False
    if not statuses.issubset({"not_frozen", "unfrozen"}):
        return "manual_review_unresolved_2034_frozen_status", False, True
    return "passed_2034_not_frozen", True, False


def evaluate_right(
    right: pd.Series,
    calendar: pd.DataFrame,
    baseline_counts: dict[tuple[str, int], int],
    source_lookup: dict[str, pd.Series],
    global_calendar_current: bool,
) -> dict[str, Any]:
    right_id = clean_text(right["future_pick_right_id"])
    team = normalize_team(right["candidate_team"])
    first_round_right = 1 in parse_rounds(right["round_numbers"])
    matched_rows, match_method, requested_ids, unmatched_ids = match_right_to_calendar(
        right, calendar, source_lookup
    )
    mapping_exact = match_method == "exact_source_asset_id"

    team_counts = {
        year: int(baseline_counts.get((team, year), 0))
        for year in STEPIEN_DRAFT_YEARS
    }
    baseline_violations = violating_pairs(team_counts)
    post_trade_violations: set[str] = set()
    worst_source = ""
    worst_year: int | float = np.nan
    worst_removed_count = -1
    scenarios = 0

    relevant_rows = [
        row for row in matched_rows if int(row["draft_year"]) in STEPIEN_DRAFT_YEARS
    ]

    if not first_round_right:
        stepien_status = "not_applicable_non_first_round_right"
        stepien_passed = True
        stepien_manual = False
    elif not mapping_exact:
        stepien_status = "manual_review_source_mapping_not_exact"
        stepien_passed = False
        stepien_manual = True
    elif baseline_violations:
        stepien_status = "blocked_baseline_not_deterministically_clear"
        stepien_passed = False
        stepien_manual = False
    elif not matched_rows:
        stepien_status = "manual_review_no_calendar_source_match"
        stepien_passed = False
        stepien_manual = True
    elif not relevant_rows:
        stepien_status = "not_applicable_outside_stepien_horizon"
        stepien_passed = True
        stepien_manual = False
    else:
        for source_row in relevant_rows:
            scenarios += 1
            scenario_counts = dict(team_counts)
            source_owner = normalize_team(source_row.get("deterministic_owner_team", ""))
            source_year = int(source_row["draft_year"])
            removed_count = 0
            if source_owner == team:
                before = scenario_counts.get(source_year, 0)
                scenario_counts[source_year] = max(before - 1, 0)
                removed_count = before - scenario_counts[source_year]
            scenario_violations = violating_pairs(scenario_counts)
            post_trade_violations.update(scenario_violations)
            if len(scenario_violations) > worst_removed_count:
                worst_removed_count = len(scenario_violations)
                worst_source = clean_text(source_row["own_first_round_source_asset_id"])
                worst_year = source_year
                worst_removed_deterministic_pick_count = removed_count

        if post_trade_violations:
            stepien_status = "blocked_consecutive_future_draft_pair"
            stepien_passed = False
            stepien_manual = False
        else:
            stepien_status = "passed_all_conservative_conveyance_scenarios"
            stepien_passed = True
            stepien_manual = False

    if worst_removed_count < 0:
        worst_removed_deterministic_pick_count = 0

    frozen_status, frozen_passed, frozen_manual = evaluate_frozen_pick(
        first_round_right,
        matched_rows,
        mapping_exact,
        right["draft_year_max"],
    )

    stage_passed = bool(
        global_calendar_current
        and bool(right["standalone_trade_asset_flag"])
        and stepien_passed
        and frozen_passed
        and not stepien_manual
        and not frozen_manual
    )
    manual_review = bool(
        stepien_manual or frozen_manual or not global_calendar_current
    )

    if stage_passed:
        package_status = (
            "stepien_frozen_authority_screen_passed_remaining_trade_date_"
            "ownership_encumbrance_and_full_cba_validation"
        )
    elif manual_review:
        package_status = "manual_review_required_for_stepien_or_frozen_pick_screen"
    else:
        package_status = "blocked_by_stepien_or_frozen_pick_screen"

    return {
        "future_pick_right_id": right_id,
        "inventory_candidate_team": team,
        "inventory_standalone_trade_asset_flag": bool(right["standalone_trade_asset_flag"]),
        "inventory_tradability_status": clean_text(right["tradability_status"]),
        "first_round_right_flag": first_round_right,
        "stepien_evaluation_status": stepien_status,
        "stepien_legality_passed": stepien_passed,
        "stepien_manual_review_required": stepien_manual,
        "stepien_baseline_violating_pairs": "|".join(baseline_violations),
        "stepien_post_trade_violating_pairs": "|".join(sorted(post_trade_violations)),
        "stepien_evaluated_scenario_count": scenarios,
        "stepien_source_match_method": match_method,
        "stepien_requested_source_asset_ids": "|".join(requested_ids),
        "stepien_matched_source_asset_ids": "|".join(
            sorted(
                {
                    clean_text(row["own_first_round_source_asset_id"])
                    for row in matched_rows
                }
            )
        ),
        "stepien_unmatched_source_asset_ids": "|".join(unmatched_ids),
        "stepien_worst_case_removed_source_asset_id": worst_source,
        "stepien_worst_case_removed_draft_year": worst_year,
        "stepien_worst_case_removed_deterministic_pick_count": (
            worst_removed_deterministic_pick_count
        ),
        "frozen_pick_evaluation_status": frozen_status,
        "frozen_pick_legality_passed": frozen_passed,
        "calendar_authority_and_date_passed": global_calendar_current,
        "package_pick_legality_stage_passed": stage_passed,
        "package_pick_legality_manual_review_required": manual_review,
        "stepien_stage_package_legality_status": package_status,
    }


def evaluate_rights(
    inventory: pd.DataFrame,
    calendar: pd.DataFrame,
    baseline_counts: dict[tuple[str, int], int],
    source_lookup: dict[str, pd.Series],
    trade_date: date,
) -> pd.DataFrame:
    standalone = inventory.loc[inventory["standalone_trade_asset_flag"]].copy()
    global_current = bool(
        calendar["deterministic_calendar_ready"].all()
        and calendar["source_authority_verified"].all()
        and calendar.apply(calendar_row_is_current, axis=1, trade_date=trade_date).all()
    )
    rows = [
        evaluate_right(
            right,
            calendar,
            baseline_counts,
            source_lookup,
            global_current,
        )
        for _, right in standalone.iterrows()
    ]
    return pd.DataFrame(rows).sort_values(
        [
            "package_pick_legality_stage_passed",
            "package_pick_legality_manual_review_required",
            "inventory_candidate_team",
            "future_pick_right_id",
        ],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)


def apply_package_specific_stepien_simulation(
    candidates: pd.DataFrame,
    inventory: pd.DataFrame,
    right_evaluation: pd.DataFrame,
) -> pd.DataFrame:
    output = candidates.copy()
    output["attached_pick_team"] = output["attached_pick_team"].map(normalize_team)
    output["attached_pick_right_id"] = output["attached_pick_right_id"].map(clean_text)

    inventory_lookup = inventory[
        ["future_pick_right_id", "candidate_team"]
    ].rename(columns={"candidate_team": "inventory_candidate_team_from_inventory"})

    evaluation = right_evaluation.rename(
        columns={
            "future_pick_right_id": "attached_pick_right_id",
            "inventory_candidate_team": "inventory_candidate_team_from_evaluation",
        }
    )

    output = output.merge(
        inventory_lookup,
        how="left",
        left_on="attached_pick_right_id",
        right_on="future_pick_right_id",
        validate="many_to_one",
    ).drop(columns=["future_pick_right_id"])
    output = output.merge(
        evaluation,
        how="left",
        on="attached_pick_right_id",
        validate="many_to_one",
    )

    output["pick_right_matched_to_inventory"] = output[
        "inventory_candidate_team_from_inventory"
    ].notna()
    output["attached_pick_team_matches_inventory"] = (
        output["pick_right_matched_to_inventory"]
        & output["attached_pick_team"].eq(output["inventory_candidate_team_from_inventory"])
        & output["attached_pick_team"].eq(output["inventory_candidate_team_from_evaluation"])
    )

    output["package_pick_legality_stage_passed"] = (
        output["package_pick_legality_stage_passed"].fillna(False).astype(bool)
        & output["pick_right_matched_to_inventory"]
        & output["attached_pick_team_matches_inventory"]
    )
    output["package_pick_legality_manual_review_required"] = (
        output["package_pick_legality_manual_review_required"].fillna(True).astype(bool)
        | ~output["pick_right_matched_to_inventory"]
        | ~output["attached_pick_team_matches_inventory"]
    )

    passed = output["package_pick_legality_stage_passed"]
    manual = output["package_pick_legality_manual_review_required"]
    output["optimizer_package_legality_status"] = np.select(
        [passed, manual],
        [
            (
                "stepien_frozen_authority_screen_passed_remaining_trade_date_"
                "ownership_encumbrance_and_full_cba_validation"
            ),
            "manual_review_required_for_stepien_or_frozen_pick_screen",
        ],
        default="blocked_by_stepien_or_frozen_pick_screen",
    )

    # This release is a Stepien/frozen-pick screen, not final trade approval.
    output["optimizer_package_final_legal"] = False
    output["stepien_evaluator_release"] = RELEASE_NAME
    output["stepien_evaluator_version"] = SCRIPT_VERSION

    drop_columns = [
        "inventory_candidate_team_from_inventory",
        "inventory_candidate_team_from_evaluation",
        "stepien_stage_package_legality_status",
    ]
    return output.drop(columns=[column for column in drop_columns if column in output.columns])


def build_package_evaluation(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
) -> pd.DataFrame:
    combined = pd.concat([one_for_one, two_for_one], ignore_index=True, sort=False)
    columns = [column for column in PACKAGE_EVALUATION_COLUMNS if column in combined.columns]
    return combined[columns].sort_values(
        ["optimizer_branch", "optimizer_candidate_id"]
    ).reset_index(drop=True)


def build_recommendations(
    one_for_one: pd.DataFrame,
    two_for_one: pd.DataFrame,
) -> pd.DataFrame:
    combined = pd.concat([one_for_one, two_for_one], ignore_index=True, sort=False)
    combined = combined.loc[combined["package_pick_legality_stage_passed"]].copy()
    if combined.empty:
        return pd.DataFrame(
            columns=[
                "recommendation_team",
                "recommendation_rank_for_team",
                "optimizer_candidate_id",
                "optimizer_branch",
                "optimizer_package_legality_status",
                "optimizer_package_final_legal",
            ]
        )

    rows = []
    for side, team_column in [("A", "team_a"), ("B", "team_b")]:
        side_rows = combined.copy()
        side_rows["recommendation_team"] = side_rows[team_column]
        side_rows["recommendation_team_attaches_pick"] = side_rows[
            "attached_pick_side"
        ].eq(side)
        rows.append(side_rows)
    recommendations = pd.concat(rows, ignore_index=True, sort=False)
    recommendations = recommendations.sort_values(
        [
            "recommendation_team",
            "heuristic_optimizer_score_v1",
            "value_gap_improvement_score",
            "adjusted_absolute_value_gap",
            "optimizer_candidate_id",
        ],
        ascending=[True, False, False, True, True],
    )
    recommendations["recommendation_rank_for_team"] = (
        recommendations.groupby("recommendation_team").cumcount() + 1
    )
    recommendations = recommendations.loc[
        recommendations["recommendation_rank_for_team"]
        <= TOP_RECOMMENDATIONS_PER_TEAM
    ].copy()
    selected = [
        "recommendation_team",
        "recommendation_rank_for_team",
        "optimizer_candidate_id",
        "optimizer_branch",
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "attached_pick_team",
        "right_display_name",
        "attached_pick_value_score",
        "value_gap_improvement_score",
        "optimizer_value_balance_score",
        "base_fit_signal",
        "base_realism_signal",
        "heuristic_optimizer_score_v1",
        "recommendation_team_attaches_pick",
        "stepien_evaluation_status",
        "frozen_pick_evaluation_status",
        "package_pick_legality_stage_passed",
        "optimizer_package_legality_status",
        "optimizer_package_final_legal",
    ]
    return recommendations[[column for column in selected if column in recommendations.columns]].reset_index(drop=True)


def build_validation(
    calendar: pd.DataFrame,
    inventory: pd.DataFrame,
    one_input: pd.DataFrame,
    two_input: pd.DataFrame,
    one_output: pd.DataFrame,
    two_output: pd.DataFrame,
    right_evaluation: pd.DataFrame,
    package_evaluation: pd.DataFrame,
    trade_date: date,
) -> pd.DataFrame:
    known_teams = set(calendar["team_abbreviation"])
    calendar_keys = set(
        zip(calendar["team_abbreviation"], calendar["draft_year"], strict=False)
    )
    expected_keys = {
        (team, year) for team in known_teams for year in CALENDAR_DRAFT_YEARS
    }
    combined_output = pd.concat([one_output, two_output], ignore_index=True, sort=False)
    candidate_ids_preserved = bool(
        set(one_input["optimizer_candidate_id"]) == set(one_output["optimizer_candidate_id"])
        and set(two_input["optimizer_candidate_id"]) == set(two_output["optimizer_candidate_id"])
    )
    incorrectly_final_legal = int(
        parse_bool_series(combined_output["optimizer_package_final_legal"]).sum()
    )
    invalid_stage_pass = int(
        (
            combined_output["package_pick_legality_stage_passed"]
            & (
                ~combined_output["stepien_legality_passed"].fillna(False)
                | ~combined_output["frozen_pick_legality_passed"].fillna(False)
                | ~combined_output["calendar_authority_and_date_passed"].fillna(False)
                | ~combined_output["attached_pick_team_matches_inventory"].fillna(False)
            )
        ).sum()
    )
    all_calendar_current = bool(
        calendar.apply(calendar_row_is_current, axis=1, trade_date=trade_date).all()
    )
    standalone_rights = int(inventory["standalone_trade_asset_flag"].sum())

    checks = [
        ("calendar_row_count", len(calendar), EXPECTED_CALENDAR_ROWS, len(calendar) == EXPECTED_CALENDAR_ROWS),
        ("calendar_team_count", len(known_teams), EXPECTED_TEAMS, len(known_teams) == EXPECTED_TEAMS),
        ("calendar_team_year_horizon_complete", len(calendar_keys), len(expected_keys), calendar_keys == expected_keys),
        ("calendar_unique_team_year_keys", int(calendar[["team_abbreviation", "draft_year"]].duplicated().sum()), 0, not calendar[["team_abbreviation", "draft_year"]].duplicated().any()),
        ("calendar_unique_source_asset_ids", int(calendar["own_first_round_source_asset_id"].duplicated().sum()), 0, not calendar["own_first_round_source_asset_id"].duplicated().any()),
        ("calendar_all_rows_deterministic_ready", int(calendar["deterministic_calendar_ready"].sum()), len(calendar), bool(calendar["deterministic_calendar_ready"].all())),
        ("calendar_all_rows_authoritative_and_current", int(all_calendar_current), True, all_calendar_current),
        ("pick_inventory_row_count", len(inventory), EXPECTED_INVENTORY_ROWS, len(inventory) == EXPECTED_INVENTORY_ROWS),
        ("standalone_pick_right_count", standalone_rights, EXPECTED_STANDALONE_RIGHTS, standalone_rights == EXPECTED_STANDALONE_RIGHTS),
        ("right_evaluation_row_count", len(right_evaluation), standalone_rights, len(right_evaluation) == standalone_rights),
        ("one_for_one_input_row_count", len(one_input), EXPECTED_ONE_FOR_ONE_ROWS, len(one_input) == EXPECTED_ONE_FOR_ONE_ROWS),
        ("two_for_one_input_row_count", len(two_input), EXPECTED_TWO_FOR_ONE_ROWS, len(two_input) == EXPECTED_TWO_FOR_ONE_ROWS),
        ("one_for_one_output_row_count_preserved", len(one_output), len(one_input), len(one_output) == len(one_input)),
        ("two_for_one_output_row_count_preserved", len(two_output), len(two_input), len(two_output) == len(two_input)),
        ("candidate_ids_preserved", candidate_ids_preserved, True, candidate_ids_preserved),
        ("all_candidate_rights_match_inventory", int(combined_output["pick_right_matched_to_inventory"].sum()), len(combined_output), bool(combined_output["pick_right_matched_to_inventory"].all())),
        ("all_attached_pick_teams_match_inventory", int(combined_output["attached_pick_team_matches_inventory"].sum()), len(combined_output), bool(combined_output["attached_pick_team_matches_inventory"].all())),
        ("package_evaluation_row_count", len(package_evaluation), len(combined_output), len(package_evaluation) == len(combined_output)),
        ("no_invalid_pick_legality_stage_pass", invalid_stage_pass, 0, invalid_stage_pass == 0),
        ("no_package_preapproved_final_legal", incorrectly_final_legal, 0, incorrectly_final_legal == 0),
    ]
    return pd.DataFrame(
        [
            {
                "check_name": name,
                "observed_value": observed,
                "expected_value": expected,
                "passed": bool(passed),
            }
            for name, observed, expected, passed in checks
        ]
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply conservative package-specific Stepien and 2034 frozen-pick "
            "screens to mixed player-and-pick optimizer candidates."
        )
    )
    parser.add_argument(
        "--trade-date",
        default=DEFAULT_TRADE_DATE.isoformat(),
        help="Proposed trade date in YYYY-MM-DD format. Default: 2026-08-04.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    trade_date = date.fromisoformat(arguments.trade_date)
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK PACKAGE-SPECIFIC STEPIEN LEGALITY EVALUATOR")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print(f"Trade date: {trade_date.isoformat()}")
    print()

    print("[1/8] Loading calendar, inventory, and V3 optimizer candidates")
    calendar_raw, inventory_raw, one_input, two_input = read_inputs()
    calendar = normalize_calendar(calendar_raw)
    inventory = normalize_inventory(inventory_raw)

    print("[2/8] Building deterministic retained-first baseline")
    baseline, baseline_counts, source_lookup = build_baseline(calendar, trade_date)

    print("[3/8] Evaluating each standalone pick right once")
    right_evaluation = evaluate_rights(
        inventory,
        calendar,
        baseline_counts,
        source_lookup,
        trade_date,
    )

    print("[4/8] Applying package-specific Stepien simulation to one-for-one candidates")
    one_output = apply_package_specific_stepien_simulation(
        one_input, inventory, right_evaluation
    )

    print("[5/8] Applying package-specific Stepien simulation to two-for-one candidates")
    two_output = apply_package_specific_stepien_simulation(
        two_input, inventory, right_evaluation
    )

    print("[6/8] Building package audit and Stepien-screened recommendations")
    package_evaluation = build_package_evaluation(one_output, two_output)
    recommendations = build_recommendations(one_output, two_output)

    print("[7/8] Validating the non-destructive legality release")
    validation = build_validation(
        calendar,
        inventory,
        one_input,
        two_input,
        one_output,
        two_output,
        right_evaluation,
        package_evaluation,
        trade_date,
    )
    failed = validation.loc[~validation["passed"]]

    print("[8/8] Saving evaluated candidates and audits")
    one_output.to_parquet(ONE_FOR_ONE_OUTPUT_PATH, index=False)
    two_output.to_parquet(TWO_FOR_ONE_OUTPUT_PATH, index=False)
    right_evaluation.to_csv(RIGHT_EVALUATION_PATH, index=False)
    package_evaluation.to_parquet(PACKAGE_EVALUATION_PATH, index=False)
    baseline.to_csv(BASELINE_PATH, index=False)
    recommendations.to_csv(RECOMMENDATIONS_PATH, index=False)
    validation.to_csv(VALIDATION_PATH, index=False)

    combined = pd.concat([one_output, two_output], ignore_index=True, sort=False)
    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": trade_date.isoformat(),
        "stepien_draft_years": STEPIEN_DRAFT_YEARS,
        "frozen_pick_draft_year": FROZEN_PICK_DRAFT_YEAR,
        "policy": (
            "Conservative deterministic scenario test. Conditional availability "
            "is not counted. Every possible matched first-round source is tested "
            "as a separate outgoing conveyance scenario. Final package legality "
            "remains false pending trade-date, ownership, encumbrance, salary, "
            "roster, and complete CBA validation."
        ),
        "calendar_rows": len(calendar),
        "inventory_rows": len(inventory),
        "standalone_right_rows_evaluated": len(right_evaluation),
        "one_for_one_rows": len(one_output),
        "two_for_one_rows": len(two_output),
        "package_rows": len(package_evaluation),
        "packages_passing_pick_legality_stage": int(
            combined["package_pick_legality_stage_passed"].sum()
        ),
        "packages_requiring_manual_review": int(
            combined["package_pick_legality_manual_review_required"].sum()
        ),
        "stepien_screened_recommendation_rows": len(recommendations),
        "validation_checks": len(validation),
        "validation_checks_passed": int(validation["passed"].sum()),
        "release_valid": bool(failed.empty),
        "output_files": {
            "one_for_one_evaluated": str(ONE_FOR_ONE_OUTPUT_PATH),
            "two_for_one_evaluated": str(TWO_FOR_ONE_OUTPUT_PATH),
            "right_evaluation": str(RIGHT_EVALUATION_PATH),
            "package_evaluation": str(PACKAGE_EVALUATION_PATH),
            "team_year_baseline": str(BASELINE_PATH),
            "screened_recommendations": str(RECOMMENDATIONS_PATH),
            "validation": str(VALIDATION_PATH),
            "metadata": str(METADATA_PATH),
        },
    }
    METADATA_PATH.write_text(
        json.dumps(json_safe(metadata), indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("PACKAGE-SPECIFIC STEPIEN LEGALITY EVALUATION COMPLETE")
    print("=" * 80)
    print(f"Standalone rights evaluated: {len(right_evaluation):,}")
    print(f"One-for-one packages evaluated: {len(one_output):,}")
    print(f"Two-for-one packages evaluated: {len(two_output):,}")
    print(
        "Packages passing this pick-legality stage: "
        f"{int(combined['package_pick_legality_stage_passed'].sum()):,}"
    )
    print(
        "Packages requiring manual review: "
        f"{int(combined['package_pick_legality_manual_review_required'].sum()):,}"
    )
    print(f"Validation checks passed: {int(validation['passed'].sum())}/{len(validation)}")
    print(f"Release valid: {bool(failed.empty)}")
    print("Final-legal packages released: 0")
    print()
    print("SAVED FILES")
    for path in [
        ONE_FOR_ONE_OUTPUT_PATH,
        TWO_FOR_ONE_OUTPUT_PATH,
        RIGHT_EVALUATION_PATH,
        PACKAGE_EVALUATION_PATH,
        BASELINE_PATH,
        RECOMMENDATIONS_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        print()
        print("FAILED VALIDATION CHECKS")
        print(failed.to_string(index=False))
        raise RuntimeError(
            "Package-specific Stepien legality release failed validation."
        )


if __name__ == "__main__":
    main()