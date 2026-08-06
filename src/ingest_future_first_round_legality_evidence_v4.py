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
    "future-first-round-legality-evidence-ingestion-v4-field-audit-safe-2026-08-04"
)

RELEASE_NAME = (
    "future_first_round_legality_evidence_ingestion_2027_2034_v4"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

RESEARCH_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_packet_queue_v1.csv"
)

PRIORITY_ONE_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_priority_one_evidence_template_v1.csv"
)

CALENDAR_INPUT_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v1.parquet"
)

CALENDAR_OUTPUT_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v5_evidence_ingested.parquet"
)

CALENDAR_OUTPUT_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v5_evidence_ingested.csv"
)

EVIDENCE_ROW_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_row_audit_v4.csv"
)

EVIDENCE_FIELD_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_field_audit_v4.csv"
)

INGESTED_EVIDENCE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_ingested_evidence_v4.csv"
)

REJECTED_EVIDENCE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_rejected_evidence_v4.csv"
)

CALENDAR_CHANGE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_calendar_change_audit_v4.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_ingestion_readiness_v4.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_ingestion_metadata_v4.json"
)


AS_OF_DATE = date(2026, 8, 4)

EXPECTED_CALENDAR_ROWS = 240
EXPECTED_RESEARCH_QUEUE_ROWS = 240
EXPECTED_PRIORITY_ONE_ROWS = 77

KEY_COLUMNS = [
    "team_abbreviation",
    "draft_year",
]

EVIDENCE_COLUMNS = [
    "own_first_round_source_asset_id",
    "own_first_round_current_owner_team",
    "own_first_round_control_status",
    "own_first_round_retained_status",
    "own_first_round_outgoing_obligation_status",
    "own_first_round_swap_status",
    "own_first_round_protection_status",
    "own_first_round_encumbrance_status",
    "deterministic_first_round_availability",
    "stepien_availability_after_proposed_trade",
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
    "reviewer_name",
    "reviewer_notes",
]

REQUIRED_FOR_COMPLETED_ROW = [
    "own_first_round_source_asset_id",
    "own_first_round_current_owner_team",
    "own_first_round_control_status",
    "own_first_round_retained_status",
    "own_first_round_outgoing_obligation_status",
    "own_first_round_swap_status",
    "own_first_round_protection_status",
    "own_first_round_encumbrance_status",
    "deterministic_first_round_availability",
    "authoritative_source_name",
    "authoritative_source_url",
    "authoritative_source_as_of_date",
    "source_effective_start_date",
    "source_authority_verified",
    "reviewer_name",
]

ALLOWED_VALUES = {
    "own_first_round_control_status": {
        "owned",
        "owed_out",
        "conditional",
        "swap_encumbered",
        "unknown",
    },
    "own_first_round_retained_status": {
        "definitely_retained",
        "not_definitely_retained",
        "unknown",
    },
    "own_first_round_outgoing_obligation_status": {
        "none",
        "active",
        "conditional",
        "exhausted",
        "unknown",
    },
    "own_first_round_swap_status": {
        "none",
        "swap_right_granted",
        "swap_right_received",
        "pooled",
        "unknown",
    },
    "own_first_round_protection_status": {
        "unprotected",
        "protected",
        "conditional",
        "not_applicable",
        "unknown",
    },
    "own_first_round_encumbrance_status": {
        "clear",
        "encumbered",
        "partially_encumbered",
        "unknown",
    },
    "deterministic_first_round_availability": {
        "available",
        "unavailable",
        "conditional_not_counted",
        "unknown",
    },
    "stepien_availability_after_proposed_trade": {
        "available",
        "unavailable",
        "not_evaluated",
        "not_applicable",
        "unknown",
    },
    "second_apron_frozen_pick_status": {
        "not_applicable",
        "not_frozen",
        "frozen",
        "unfrozen",
        "penalized",
        "unknown",
    },
    "draft_pick_penalty_status": {
        "none",
        "active",
        "resolved",
        "unknown",
    },
}

UNRESOLVED_VALUES = {
    "",
    "unknown",
    "unresolved",
    "not_evaluated",
    "not_applicable",
}

URL_PATTERN = re.compile(
    r"^https?://[^\s]+$",
    flags=re.IGNORECASE,
)

TEAM_PATTERN = re.compile(
    r"^[A-Z]{3}$"
)


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


def normalize_status(
    value: Any,
) -> str:
    return (
        clean_text(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def normalize_team(
    value: Any,
) -> str:
    return clean_text(value).upper()


def json_safe(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
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
    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


def parse_bool_value(
    value: Any,
) -> bool | None:
    if isinstance(
        value,
        (
            bool,
            np.bool_,
        ),
    ):
        return bool(value)

    normalized = normalize_status(value)

    if normalized in {
        "true",
        "1",
        "yes",
        "passed",
    }:
        return True

    if normalized in {
        "false",
        "0",
        "no",
        "failed",
        "",
    }:
        return False

    return None


def parse_bool_series(
    series: pd.Series,
) -> pd.Series:
    return series.map(
        lambda value: bool(
            parse_bool_value(value)
        )
    )


def require_file(
    path: Path,
    label: str,
) -> None:
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


def parse_date_value(
    value: Any,
) -> date | None:
    text = clean_text(value)

    if not text:
        return None

    parsed = pd.to_datetime(
        text,
        errors="coerce",
        utc=False,
    )

    if pd.isna(parsed):
        return None

    return parsed.date()


def row_has_any_evidence(
    row: pd.Series,
) -> bool:
    for column in EVIDENCE_COLUMNS:
        value = row.get(
            column,
            "",
        )

        if column == "source_authority_verified":
            if parse_bool_value(value):
                return True

            continue

        normalized = normalize_status(value)

        if normalized not in UNRESOLVED_VALUES:
            return True

    return False


def build_field_checks(
    row: pd.Series,
) -> list[dict[str, Any]]:
    checks = []

    team = normalize_team(
        row.get(
            "team_abbreviation",
            "",
        )
    )

    draft_year = int(
        pd.to_numeric(
            pd.Series(
                [
                    row.get(
                        "draft_year",
                        np.nan,
                    )
                ]
            ),
            errors="coerce",
        ).iloc[0]
    )

    for column in EVIDENCE_COLUMNS:
        raw_value = row.get(
            column,
            "",
        )

        normalized_value = (
            normalize_status(raw_value)
            if column in ALLOWED_VALUES
            else clean_text(raw_value)
        )

        valid = True
        reason = ""

        if column in ALLOWED_VALUES:
            allowed = ALLOWED_VALUES[
                column
            ]

            valid = (
                normalized_value in allowed
            )

            if not valid:
                reason = (
                    "invalid_allowed_value"
                )

        elif column == (
            "own_first_round_current_owner_team"
        ):
            valid = bool(
                TEAM_PATTERN.fullmatch(
                    normalize_team(
                        raw_value
                    )
                )
            )

            if not valid:
                reason = (
                    "invalid_team_abbreviation"
                )

        elif column == (
            "authoritative_source_url"
        ):
            valid = bool(
                URL_PATTERN.fullmatch(
                    clean_text(
                        raw_value
                    )
                )
            )

            if not valid:
                reason = (
                    "invalid_source_url"
                )

        elif column in {
            "authoritative_source_as_of_date",
            "source_effective_start_date",
        }:
            valid = (
                parse_date_value(
                    raw_value
                )
                is not None
            )

            if not valid:
                reason = (
                    "invalid_or_missing_date"
                )

        elif column == (
            "source_effective_end_date"
        ):
            end_text = clean_text(
                raw_value
            )

            valid = bool(
                not end_text
                or parse_date_value(
                    raw_value
                )
                is not None
            )

            if not valid:
                reason = (
                    "invalid_optional_end_date"
                )

        elif column == (
            "source_authority_verified"
        ):
            parsed_bool = parse_bool_value(
                raw_value
            )

            valid = (
                parsed_bool is not None
            )

            if not valid:
                reason = (
                    "invalid_boolean"
                )

            normalized_value = (
                parsed_bool
            )

        elif column == (
            "second_apron_freeze_trigger_cap_year"
        ):
            text = clean_text(
                raw_value
            )

            if draft_year == 2034:
                valid = bool(text)

                if not valid:
                    reason = (
                        "required_for_2034"
                    )
            else:
                valid = True

        elif column == (
            "second_apron_unfreeze_condition"
        ):
            text = clean_text(
                raw_value
            )

            if draft_year == 2034:
                valid = bool(text)

                if not valid:
                    reason = (
                        "required_for_2034"
                    )
            else:
                valid = True

        elif column in REQUIRED_FOR_COMPLETED_ROW:
            valid = bool(
                clean_text(
                    raw_value
                )
            )

            if not valid:
                reason = (
                    "required_field_missing"
                )

        checks.append(
            {
                "team_abbreviation": team,
                "draft_year": draft_year,
                "field_name": column,
                "raw_value": clean_text(
                    raw_value
                ),
                "normalized_value": (
                    clean_text(
                        normalized_value
                    )
                    if not isinstance(
                        normalized_value,
                        bool,
                    )
                    else normalized_value
                ),
                "field_valid": bool(valid),
                "field_failure_reason": reason,
            }
        )

    return checks


def additional_row_checks(
    row: pd.Series,
) -> list[tuple[str, bool, str]]:
    checks = []

    draft_year = int(
        pd.to_numeric(
            pd.Series(
                [
                    row.get(
                        "draft_year",
                        np.nan,
                    )
                ]
            ),
            errors="coerce",
        ).iloc[0]
    )

    as_of_date = parse_date_value(
        row.get(
            "authoritative_source_as_of_date",
            "",
        )
    )

    effective_start = parse_date_value(
        row.get(
            "source_effective_start_date",
            "",
        )
    )

    effective_end = parse_date_value(
        row.get(
            "source_effective_end_date",
            "",
        )
    )

    checks.append(
        (
            "source_as_of_not_after_audit_date",
            bool(
                as_of_date
                and as_of_date <= AS_OF_DATE
            ),
            (
                ""
                if (
                    as_of_date
                    and as_of_date <= AS_OF_DATE
                )
                else (
                    "source_as_of_date_missing_or_after_audit_date"
                )
            ),
        )
    )

    checks.append(
        (
            "effective_start_not_after_as_of",
            bool(
                effective_start
                and as_of_date
                and effective_start <= as_of_date
            ),
            (
                ""
                if (
                    effective_start
                    and as_of_date
                    and effective_start <= as_of_date
                )
                else (
                    "effective_start_missing_or_after_source_as_of_date"
                )
            ),
        )
    )

    checks.append(
        (
            "effective_end_not_before_start",
            bool(
                effective_end is None
                or (
                    effective_start
                    and effective_end
                    >= effective_start
                )
            ),
            (
                ""
                if (
                    effective_end is None
                    or (
                        effective_start
                        and effective_end
                        >= effective_start
                    )
                )
                else (
                    "effective_end_before_effective_start"
                )
            ),
        )
    )

    authority_verified = (
        parse_bool_value(
            row.get(
                "source_authority_verified",
                False,
            )
        )
    )

    checks.append(
        (
            "source_authority_verified",
            authority_verified is True,
            (
                ""
                if authority_verified is True
                else (
                    "source_authority_not_verified"
                )
            ),
        )
    )

    deterministic = normalize_status(
        row.get(
            "deterministic_first_round_availability",
            "",
        )
    )

    control = normalize_status(
        row.get(
            "own_first_round_control_status",
            "",
        )
    )

    retained = normalize_status(
        row.get(
            "own_first_round_retained_status",
            "",
        )
    )

    encumbrance = normalize_status(
        row.get(
            "own_first_round_encumbrance_status",
            "",
        )
    )

    if deterministic == "available":
        deterministic_consistent = bool(
            control == "owned"
            and retained == (
                "definitely_retained"
            )
            and encumbrance == "clear"
        )
    else:
        deterministic_consistent = True

    checks.append(
        (
            "available_status_internal_consistency",
            deterministic_consistent,
            (
                ""
                if deterministic_consistent
                else (
                    "available_requires_owned_definitely_retained_and_clear"
                )
            ),
        )
    )

    frozen_status = normalize_status(
        row.get(
            "second_apron_frozen_pick_status",
            "",
        )
    )

    if draft_year == 2034:
        frozen_year_consistent = (
            frozen_status
            not in {
                "",
                "not_applicable",
                "unknown",
            }
        )
    else:
        frozen_year_consistent = (
            frozen_status
            == "not_applicable"
        )

    checks.append(
        (
            "frozen_pick_year_consistency",
            frozen_year_consistent,
            (
                ""
                if frozen_year_consistent
                else (
                    "2034_requires_resolved_frozen_status_and_other_years_require_not_applicable"
                )
            ),
        )
    )

    return checks


def normalize_team_year_keys(
    frame: pd.DataFrame,
    frame_name: str,
    *,
    unique_subset: list[str] | None = None,
) -> pd.DataFrame:
    """Normalize team-year keys and validate the requested record grain."""

    output = frame.copy()

    require_columns(
        output,
        KEY_COLUMNS,
        frame_name,
    )

    output[
        "team_abbreviation"
    ] = output[
        "team_abbreviation"
    ].map(
        normalize_team
    )

    parsed_years = pd.to_numeric(
        output[
            "draft_year"
        ],
        errors="coerce",
    )

    invalid_year_mask = parsed_years.isna()

    if invalid_year_mask.any():
        invalid_rows = output.loc[
            invalid_year_mask,
            KEY_COLUMNS,
        ].head(20)

        raise ValueError(
            f"{frame_name} contains invalid draft_year values:\n"
            + invalid_rows.to_string(
                index=False
            )
        )

    non_integer_mask = (
        parsed_years
        .mod(1)
        .ne(0)
    )

    if non_integer_mask.any():
        invalid_rows = output.loc[
            non_integer_mask,
            KEY_COLUMNS,
        ].head(20)

        raise ValueError(
            f"{frame_name} contains non-integer draft_year values:\n"
            + invalid_rows.to_string(
                index=False
            )
        )

    output[
        "draft_year"
    ] = parsed_years.astype(
        "int64"
    )

    uniqueness_columns = (
        KEY_COLUMNS
        if unique_subset is None
        else unique_subset
    )

    require_columns(
        output,
        uniqueness_columns,
        frame_name,
    )

    duplicate_rows = output.duplicated(
        subset=uniqueness_columns,
    )

    if duplicate_rows.any():
        duplicates = output.loc[
            duplicate_rows,
            uniqueness_columns,
        ].head(20)

        raise ValueError(
            f"{frame_name} contains duplicate records at grain "
            f"{uniqueness_columns}:\n"
            + duplicates.to_string(
                index=False
            )
        )

    return output


def coerce_evidence_columns_to_object(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Return a copy with all editable evidence fields safe for text assignment."""

    output = frame.copy()

    for column in EVIDENCE_COLUMNS:
        if column not in output.columns:
            output[column] = ""

        output[column] = (
            output[column]
            .astype("object")
            .where(
                output[column].notna(),
                "",
            )
        )

    return output


def overlay_priority_one_evidence(
    research_queue: pd.DataFrame,
    priority_one: pd.DataFrame,
) -> pd.DataFrame:
    """Overlay the editable priority-one template onto the full queue."""

    output = coerce_evidence_columns_to_object(
        research_queue
    )

    priority_one = coerce_evidence_columns_to_object(
        priority_one
    )

    priority_keys = priority_one[
        KEY_COLUMNS
    ].copy()

    if priority_keys.duplicated().any():
        raise RuntimeError(
            "The priority-one template contains duplicate team-year keys."
        )

    queue_keys = set(
        map(
            tuple,
            output[
                KEY_COLUMNS
            ].itertuples(
                index=False,
                name=None,
            ),
        )
    )

    template_keys = set(
        map(
            tuple,
            priority_keys.itertuples(
                index=False,
                name=None,
            ),
        )
    )

    missing_keys = sorted(
        template_keys - queue_keys
    )

    if missing_keys:
        raise RuntimeError(
            "Priority-one template keys were not found in the full research "
            "queue:\n"
            + "\n".join(
                f"{team}|{year}"
                for team, year in missing_keys
            )
        )

    output = output.set_index(
        KEY_COLUMNS
    )

    overlay = priority_one.set_index(
        KEY_COLUMNS
    )

    for column in EVIDENCE_COLUMNS:
        output[column] = output[column].astype(
            "object"
        )

        overlay[column] = overlay[column].astype(
            "object"
        )

        output.loc[
            overlay.index,
            column,
        ] = overlay[
            column
        ].to_numpy(
            dtype=object
        )

    output = output.reset_index()

    output[
        "evidence_input_source"
    ] = "full_research_queue"

    overlay_key_index = pd.MultiIndex.from_frame(
        priority_keys
    )

    output_key_index = pd.MultiIndex.from_frame(
        output[
            KEY_COLUMNS
        ]
    )

    output.loc[
        output_key_index.isin(
            overlay_key_index
        ),
        "evidence_input_source",
    ] = "priority_one_template_overlay"

    return output


def validate_evidence_rows(
    evidence: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    row_audit_rows = []
    field_audit_rows = []

    for _, row in evidence.iterrows():
        team = normalize_team(
            row[
                "team_abbreviation"
            ]
        )

        draft_year = int(
            row[
                "draft_year"
            ]
        )

        has_any = row_has_any_evidence(
            row
        )

        field_checks = build_field_checks(
            row
        )

        field_audit_rows.extend(
            field_checks
        )

        required_field_failures = [
            check
            for check in field_checks
            if not check[
                "field_valid"
            ]
        ]

        row_checks = additional_row_checks(
            row
        )

        row_check_failures = [
            {
                "check_name": name,
                "failure_reason": reason,
            }
            for name, passed, reason in row_checks
            if not passed
        ]

        accepted = bool(
            has_any
            and not required_field_failures
            and not row_check_failures
        )

        failure_reasons = sorted(
            set(
                [
                    (
                        f"{check['field_name']}:"
                        f"{check['field_failure_reason']}"
                    )
                    for check
                    in required_field_failures
                ]
                + [
                    (
                        f"{check['check_name']}:"
                        f"{check['failure_reason']}"
                    )
                    for check
                    in row_check_failures
                ]
            )
        )

        row_audit_rows.append(
            {
                "team_abbreviation": team,
                "draft_year": draft_year,
                "evidence_row_present": (
                    has_any
                ),
                "field_checks": len(
                    field_checks
                ),
                "field_checks_passed": (
                    len(
                        field_checks
                    )
                    - len(
                        required_field_failures
                    )
                ),
                "additional_row_checks": len(
                    row_checks
                ),
                "additional_row_checks_passed": (
                    len(row_checks)
                    - len(
                        row_check_failures
                    )
                ),
                "evidence_row_accepted": (
                    accepted
                ),
                "evidence_row_status": (
                    "accepted"
                    if accepted
                    else (
                        "not_started"
                        if not has_any
                        else "rejected"
                    )
                ),
                "evidence_rejection_reasons": "|".join(
                    failure_reasons
                ),
            }
        )

    return (
        pd.DataFrame(
            row_audit_rows
        ),
        pd.DataFrame(
            field_audit_rows
        ),
    )


def normalize_accepted_evidence(
    evidence: pd.DataFrame,
    row_audit: pd.DataFrame,
) -> pd.DataFrame:
    accepted_keys = row_audit.loc[
        row_audit[
            "evidence_row_accepted"
        ],
        KEY_COLUMNS,
    ]

    accepted = evidence.merge(
        accepted_keys,
        how="inner",
        on=KEY_COLUMNS,
        validate="one_to_one",
    )

    for column in ALLOWED_VALUES:
        accepted[column] = accepted[
            column
        ].map(
            normalize_status
        )

    accepted[
        "own_first_round_current_owner_team"
    ] = accepted[
        "own_first_round_current_owner_team"
    ].map(
        normalize_team
    )

    accepted[
        "source_authority_verified"
    ] = accepted[
        "source_authority_verified"
    ].map(
        lambda value: (
            parse_bool_value(
                value
            )
            is True
        )
    )

    for column in [
        "authoritative_source_as_of_date",
        "source_effective_start_date",
        "source_effective_end_date",
    ]:
        accepted[column] = accepted[
            column
        ].map(
            lambda value: (
                parse_date_value(
                    value
                ).isoformat()
                if parse_date_value(
                    value
                )
                else ""
            )
        )

    accepted[
        "evidence_ingested_at_utc"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    accepted[
        "evidence_ingestion_version"
    ] = SCRIPT_VERSION

    return accepted


def update_calendar(
    calendar: pd.DataFrame,
    accepted: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    output = calendar.copy()

    output[
        "team_abbreviation"
    ] = output[
        "team_abbreviation"
    ].map(
        normalize_team
    )

    for column in EVIDENCE_COLUMNS:
        if column not in output.columns:
            output[column] = ""

        output[column] = (
            output[column]
            .astype("object")
            .where(
                output[column].notna(),
                "",
            )
        )

    if "evidence_ingested_flag" not in output.columns:
        output[
            "evidence_ingested_flag"
        ] = False

    output[
        "evidence_ingested_flag"
    ] = (
        output[
            "evidence_ingested_flag"
        ]
        .fillna(False)
        .astype(bool)
    )

    for tracking_column in [
        "evidence_ingested_at_utc",
        "evidence_ingestion_version",
    ]:
        if tracking_column not in output.columns:
            output[
                tracking_column
            ] = ""

        output[
            tracking_column
        ] = (
            output[
                tracking_column
            ]
            .astype("object")
            .where(
                output[
                    tracking_column
                ].notna(),
                "",
            )
        )

    change_rows = []

    if accepted.empty:
        return (
            output,
            pd.DataFrame(
                columns=[
                    *KEY_COLUMNS,
                    "field_name",
                    "previous_value",
                    "new_value",
                ]
            ),
        )

    accepted_lookup = accepted.set_index(
        KEY_COLUMNS
    )

    for index, row in output.iterrows():
        key = (
            row[
                "team_abbreviation"
            ],
            int(
                row[
                    "draft_year"
                ]
            ),
        )

        if key not in accepted_lookup.index:
            continue

        evidence_row = accepted_lookup.loc[
            key
        ]

        if isinstance(
            evidence_row,
            pd.DataFrame,
        ):
            evidence_row = (
                evidence_row.iloc[0]
            )

        for column in EVIDENCE_COLUMNS:
            if column not in output.columns:
                output[column] = ""

            previous_value = output.at[
                index,
                column,
            ]

            new_value = evidence_row.get(
                column,
                previous_value,
            )

            output.at[
                index,
                column,
            ] = new_value

            if clean_text(
                previous_value
            ) != clean_text(
                new_value
            ):
                change_rows.append(
                    {
                        "team_abbreviation": (
                            key[0]
                        ),
                        "draft_year": (
                            key[1]
                        ),
                        "field_name": (
                            column
                        ),
                        "previous_value": (
                            clean_text(
                                previous_value
                            )
                        ),
                        "new_value": (
                            clean_text(
                                new_value
                            )
                        ),
                    }
                )

        deterministic = normalize_status(
            evidence_row[
                "deterministic_first_round_availability"
            ]
        )

        resolved = bool(
            deterministic
            not in {
                "",
                "unknown",
            }
        )

        output.at[
            index,
            "source_authority_verified",
        ] = True

        output.at[
            index,
            "deterministic_calendar_ready",
        ] = resolved

        output.at[
            index,
            "manual_review_required",
        ] = not resolved

        output.at[
            index,
            "calendar_readiness_status",
        ] = (
            "authoritative_evidence_ingested_deterministic_status_resolved"
            if resolved
            else (
                "authoritative_evidence_ingested_but_deterministic_status_unresolved"
            )
        )

        output.at[
            index,
            "evidence_ingested_flag",
        ] = True

        output.at[
            index,
            "evidence_ingested_at_utc",
        ] = evidence_row[
            "evidence_ingested_at_utc"
        ]

        output.at[
            index,
            "evidence_ingestion_version",
        ] = SCRIPT_VERSION

    return (
        output,
        pd.DataFrame(
            change_rows
        ),
    )


def build_readiness(
    *,
    calendar_input: pd.DataFrame,
    research_queue: pd.DataFrame,
    priority_one: pd.DataFrame,
    row_audit: pd.DataFrame,
    field_audit: pd.DataFrame,
    accepted: pd.DataFrame,
    calendar_output: pd.DataFrame,
    changes: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_input_keys = int(
        research_queue.duplicated(
            subset=KEY_COLUMNS
        ).sum()
    )

    duplicate_calendar_keys = int(
        calendar_output.duplicated(
            subset=KEY_COLUMNS
        ).sum()
    )

    accepted_rows = int(
        row_audit[
            "evidence_row_accepted"
        ].sum()
    )

    rejected_rows = int(
        row_audit[
            "evidence_row_status"
        ].eq(
            "rejected"
        ).sum()
    )

    not_started_rows = int(
        row_audit[
            "evidence_row_status"
        ].eq(
            "not_started"
        ).sum()
    )

    evidence_ingested_rows = int(
        parse_bool_series(
            calendar_output.get(
                "evidence_ingested_flag",
                pd.Series(
                    False,
                    index=calendar_output.index,
                ),
            )
        ).sum()
    )

    ready_rows = int(
        parse_bool_series(
            calendar_output[
                "deterministic_calendar_ready"
            ]
        ).sum()
    )

    key_dtype_checks = {
        "calendar_input_draft_year_integer": pd.api.types.is_integer_dtype(
            calendar_input[
                "draft_year"
            ]
        ),
        "research_queue_draft_year_integer": pd.api.types.is_integer_dtype(
            research_queue[
                "draft_year"
            ]
        ),
        "priority_one_draft_year_integer": pd.api.types.is_integer_dtype(
            priority_one[
                "draft_year"
            ]
        ),
        "row_audit_draft_year_integer": pd.api.types.is_integer_dtype(
            row_audit[
                "draft_year"
            ]
        ),
        "field_audit_draft_year_integer": pd.api.types.is_integer_dtype(
            field_audit[
                "draft_year"
            ]
        ),
        "accepted_draft_year_integer": (
            True
            if accepted.empty
            else pd.api.types.is_integer_dtype(
                accepted[
                    "draft_year"
                ]
            )
        ),
    }

    duplicate_field_audit_records = int(
        field_audit.duplicated(
            subset=[
                *KEY_COLUMNS,
                "field_name",
            ]
        ).sum()
    )

    expected_field_audit_rows = (
        len(research_queue)
        * len(EVIDENCE_COLUMNS)
    )

    checks = [
        *[
            {
                "check_name": check_name,
                "observed_value": bool(passed),
                "expected_value": True,
                "passed": bool(passed),
            }
            for check_name, passed in key_dtype_checks.items()
        ],
        {
            "check_name": (
                "field_audit_record_count"
            ),
            "observed_value": len(
                field_audit
            ),
            "expected_value": (
                expected_field_audit_rows
            ),
            "passed": (
                len(field_audit)
                == expected_field_audit_rows
            ),
        },
        {
            "check_name": (
                "unique_field_audit_team_year_field_records"
            ),
            "observed_value": (
                duplicate_field_audit_records
            ),
            "expected_value": 0,
            "passed": (
                duplicate_field_audit_records
                == 0
            ),
        },
        {
            "check_name": (
                "input_calendar_row_count"
            ),
            "observed_value": len(
                calendar_input
            ),
            "expected_value": (
                EXPECTED_CALENDAR_ROWS
            ),
            "passed": (
                len(calendar_input)
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": (
                "research_queue_row_count"
            ),
            "observed_value": len(
                research_queue
            ),
            "expected_value": (
                EXPECTED_RESEARCH_QUEUE_ROWS
            ),
            "passed": (
                len(research_queue)
                == EXPECTED_RESEARCH_QUEUE_ROWS
            ),
        },
        {
            "check_name": (
                "priority_one_template_row_count"
            ),
            "observed_value": len(
                priority_one
            ),
            "expected_value": (
                EXPECTED_PRIORITY_ONE_ROWS
            ),
            "passed": (
                len(priority_one)
                == EXPECTED_PRIORITY_ONE_ROWS
            ),
        },
        {
            "check_name": (
                "unique_research_queue_keys"
            ),
            "observed_value": (
                duplicate_input_keys
            ),
            "expected_value": 0,
            "passed": (
                duplicate_input_keys == 0
            ),
        },
        {
            "check_name": (
                "output_calendar_row_count"
            ),
            "observed_value": len(
                calendar_output
            ),
            "expected_value": (
                EXPECTED_CALENDAR_ROWS
            ),
            "passed": (
                len(calendar_output)
                == EXPECTED_CALENDAR_ROWS
            ),
        },
        {
            "check_name": (
                "unique_output_calendar_keys"
            ),
            "observed_value": (
                duplicate_calendar_keys
            ),
            "expected_value": 0,
            "passed": (
                duplicate_calendar_keys
                == 0
            ),
        },
        {
            "check_name": (
                "accepted_evidence_rows_match_audit"
            ),
            "observed_value": len(
                accepted
            ),
            "expected_value": (
                accepted_rows
            ),
            "passed": (
                len(accepted)
                == accepted_rows
            ),
        },
        {
            "check_name": (
                "evidence_ingested_rows_match_accepted"
            ),
            "observed_value": (
                evidence_ingested_rows
            ),
            "expected_value": (
                accepted_rows
            ),
            "passed": (
                evidence_ingested_rows
                == accepted_rows
            ),
        },
        {
            "check_name": (
                "accepted_rows_have_calendar_changes"
            ),
            "observed_value": int(
                changes[
                    KEY_COLUMNS
                ]
                .drop_duplicates()
                .shape[0]
            )
            if not changes.empty
            else 0,
            "expected_value": (
                accepted_rows
            ),
            "passed": (
                (
                    int(
                        changes[
                            KEY_COLUMNS
                        ]
                        .drop_duplicates()
                        .shape[0]
                    )
                    if not changes.empty
                    else 0
                )
                == accepted_rows
            ),
        },
        {
            "check_name": (
                "no_rejected_rows_ingested"
            ),
            "observed_value": (
                evidence_ingested_rows
                - accepted_rows
            ),
            "expected_value": 0,
            "passed": (
                evidence_ingested_rows
                == accepted_rows
            ),
        },
        {
            "check_name": (
                "row_audit_partition_complete"
            ),
            "observed_value": (
                accepted_rows
                + rejected_rows
                + not_started_rows
            ),
            "expected_value": len(
                research_queue
            ),
            "passed": (
                accepted_rows
                + rejected_rows
                + not_started_rows
                == len(
                    research_queue
                )
            ),
        },
        {
            "check_name": (
                "deterministic_ready_rows_not_greater_than_accepted"
            ),
            "observed_value": ready_rows,
            "expected_value": (
                f"<={accepted_rows}"
            ),
            "passed": (
                ready_rows
                <= accepted_rows
            ),
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

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path, label in [
        (
            RESEARCH_QUEUE_PATH,
            "research packet queue",
        ),
        (
            PRIORITY_ONE_TEMPLATE_PATH,
            "priority-one evidence template",
        ),
        (
            CALENDAR_INPUT_PATH,
            "legality calendar",
        ),
    ]:
        require_file(
            path,
            label,
        )

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY EVIDENCE INGESTION")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/8] Loading research evidence and calendar")
    research_queue = pd.read_csv(
        RESEARCH_QUEUE_PATH,
        dtype=object,
        keep_default_na=False,
    )

    priority_one = pd.read_csv(
        PRIORITY_ONE_TEMPLATE_PATH,
        dtype=object,
        keep_default_na=False,
    )

    calendar_input = pd.read_parquet(
        CALENDAR_INPUT_PATH
    )

    require_columns(
        research_queue,
        [
            *KEY_COLUMNS,
            *EVIDENCE_COLUMNS,
        ],
        "Research packet queue",
    )

    require_columns(
        priority_one,
        [
            *KEY_COLUMNS,
            *EVIDENCE_COLUMNS,
        ],
        "Priority-one evidence template",
    )

    require_columns(
        calendar_input,
        [
            *KEY_COLUMNS,
            "deterministic_calendar_ready",
            "manual_review_required",
            "calendar_readiness_status",
        ],
        "Legality calendar",
    )

    research_queue = normalize_team_year_keys(
        research_queue,
        "Research packet queue",
    )

    priority_one = normalize_team_year_keys(
        priority_one,
        "Priority-one evidence template",
    )

    calendar_input = normalize_team_year_keys(
        calendar_input,
        "Legality calendar",
    )

    research_queue = coerce_evidence_columns_to_object(
        research_queue
    )

    priority_one = coerce_evidence_columns_to_object(
        priority_one
    )

    evidence_input = overlay_priority_one_evidence(
        research_queue,
        priority_one,
    )

    print("[2/8] Validating every evidence field")
    (
        row_audit,
        field_audit,
    ) = validate_evidence_rows(
        evidence_input
    )

    row_audit = normalize_team_year_keys(
        row_audit,
        "Evidence row audit",
    )

    field_audit = normalize_team_year_keys(
        field_audit,
        "Evidence field audit",
        unique_subset=[
            *KEY_COLUMNS,
            "field_name",
        ],
    )

    row_audit = row_audit.merge(
        evidence_input[
            [
                *KEY_COLUMNS,
                "evidence_input_source",
            ]
        ],
        how="left",
        on=KEY_COLUMNS,
        validate="one_to_one",
    )

    print("[3/8] Normalizing accepted evidence rows")
    accepted = normalize_accepted_evidence(
        evidence_input,
        row_audit,
    )

    accepted = normalize_team_year_keys(
        accepted,
        "Accepted evidence",
    )

    rejected = evidence_input.merge(
        row_audit.loc[
            row_audit[
                "evidence_row_status"
            ].eq(
                "rejected"
            ),
            [
                *KEY_COLUMNS,
                "evidence_rejection_reasons",
            ],
        ],
        how="inner",
        on=KEY_COLUMNS,
        validate="one_to_one",
    )

    print("[4/8] Updating only accepted calendar rows")
    (
        calendar_output,
        changes,
    ) = update_calendar(
        calendar_input,
        accepted,
    )

    print("[5/8] Revalidating the updated calendar")
    readiness = build_readiness(
        calendar_input=calendar_input,
        research_queue=research_queue,
        priority_one=priority_one,
        row_audit=row_audit,
        field_audit=field_audit,
        accepted=accepted,
        calendar_output=calendar_output,
        changes=changes,
    )

    failed = readiness.loc[
        ~readiness[
            "passed"
        ]
    ]

    print("[6/8] Saving ingestion audits")
    row_audit.to_csv(
        EVIDENCE_ROW_AUDIT_PATH,
        index=False,
    )

    field_audit.to_csv(
        EVIDENCE_FIELD_AUDIT_PATH,
        index=False,
    )

    accepted.to_csv(
        INGESTED_EVIDENCE_PATH,
        index=False,
    )

    rejected.to_csv(
        REJECTED_EVIDENCE_PATH,
        index=False,
    )

    changes.to_csv(
        CALENDAR_CHANGE_AUDIT_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    print("[7/8] Saving the evidence-ingested calendar")
    calendar_output.to_parquet(
        CALENDAR_OUTPUT_PARQUET_PATH,
        index=False,
    )

    calendar_output.to_csv(
        CALENDAR_OUTPUT_CSV_PATH,
        index=False,
    )

    accepted_rows = int(
        row_audit[
            "evidence_row_accepted"
        ].sum()
    )

    rejected_rows = int(
        row_audit[
            "evidence_row_status"
        ].eq(
            "rejected"
        ).sum()
    )

    not_started_rows = int(
        row_audit[
            "evidence_row_status"
        ].eq(
            "not_started"
        ).sum()
    )

    deterministic_ready_rows = int(
        parse_bool_series(
            calendar_output[
                "deterministic_calendar_ready"
            ]
        ).sum()
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "audit_as_of_date": (
            AS_OF_DATE.isoformat()
        ),
        "research_queue_rows": int(
            len(research_queue)
        ),
        "accepted_evidence_rows": (
            accepted_rows
        ),
        "rejected_evidence_rows": (
            rejected_rows
        ),
        "not_started_evidence_rows": (
            not_started_rows
        ),
        "calendar_rows": int(
            len(calendar_output)
        ),
        "calendar_change_rows": int(
            len(changes)
        ),
        "deterministic_calendar_ready_rows": (
            deterministic_ready_rows
        ),
        "readiness_checks": int(
            len(readiness)
        ),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "evidence_ingestion_release_valid": bool(
            failed.empty
        ),
        "scope_note": (
            "Accepted evidence updates only the team-year calendar. "
            "It does not by itself approve any optimizer package. "
            "Package-specific Stepien, frozen-pick, overlapping-right, "
            "and trade-date checks remain separate."
        ),
        "output_files": {
            "calendar_parquet": str(
                CALENDAR_OUTPUT_PARQUET_PATH
            ),
            "calendar_csv": str(
                CALENDAR_OUTPUT_CSV_PATH
            ),
            "row_audit": str(
                EVIDENCE_ROW_AUDIT_PATH
            ),
            "field_audit": str(
                EVIDENCE_FIELD_AUDIT_PATH
            ),
            "ingested_evidence": str(
                INGESTED_EVIDENCE_PATH
            ),
            "rejected_evidence": str(
                REJECTED_EVIDENCE_PATH
            ),
            "calendar_changes": str(
                CALENDAR_CHANGE_AUDIT_PATH
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

    print("[8/8] Evidence ingestion release saved")
    print()

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY EVIDENCE INGESTION COMPLETE")
    print("=" * 80)
    print(
        "Research queue rows: "
        f"{len(research_queue):,}"
    )
    print(
        "Accepted evidence rows: "
        f"{accepted_rows:,}"
    )
    print(
        "Rejected evidence rows: "
        f"{rejected_rows:,}"
    )
    print(
        "Not-started evidence rows: "
        f"{not_started_rows:,}"
    )
    print(
        "Calendar field changes: "
        f"{len(changes):,}"
    )
    print(
        "Deterministic calendar-ready rows: "
        f"{deterministic_ready_rows:,}"
        f"/{len(calendar_output):,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Evidence ingestion release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("EVIDENCE ROW STATUS")
    status_summary = (
        row_audit.groupby(
            "evidence_row_status",
            as_index=False,
        )
        .size()
        .rename(
            columns={
                "size": "row_count",
            }
        )
    )

    print(
        status_summary.to_string(
            index=False
        )
    )
    print()

    if not rejected.empty:
        print("FIRST 20 REJECTED EVIDENCE ROWS")
        print(
            rejected[
                [
                    "team_abbreviation",
                    "draft_year",
                    "evidence_rejection_reasons",
                ]
            ]
            .head(20)
            .to_string(
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
        CALENDAR_OUTPUT_PARQUET_PATH,
        CALENDAR_OUTPUT_CSV_PATH,
        EVIDENCE_ROW_AUDIT_PATH,
        EVIDENCE_FIELD_AUDIT_PATH,
        INGESTED_EVIDENCE_PATH,
        REJECTED_EVIDENCE_PATH,
        CALENDAR_CHANGE_AUDIT_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        raise RuntimeError(
            "Future first-round legality evidence ingestion "
            "failed validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()