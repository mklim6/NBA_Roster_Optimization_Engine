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
    "future-first-round-legality-research-packets-v1-2026-08-04"
)

RELEASE_NAME = (
    "future_first_round_legality_research_packets_2027_2034_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

EVIDENCE_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_evidence_queue_2027_2034_v1.csv"
)

TEAM_EXPOSURE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_team_exposure_summary_v1.csv"
)

RIGHT_EXPOSURE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_right_exposure_summary_v1.csv"
)

CALENDAR_PATH = (
    PROCESSED_DIRECTORY
    / "future_first_round_legality_calendar_2027_2034_v1.parquet"
)

PICK_INVENTORY_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

RESEARCH_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_packet_queue_v1.csv"
)

PRIORITY_ONE_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_priority_one_evidence_template_v1.csv"
)

BATCH_MANIFEST_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_batch_manifest_v1.csv"
)

PACKETS_JSON_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_packets_v1.json"
)

PHASE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_phase_summary_v1.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_packets_validation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_research_packets_metadata_v1.json"
)


EXPECTED_QUEUE_ROWS = 240
EXPECTED_PRIORITY_ONE_ROWS = 77
EXPECTED_TEAMS = 30
EXPECTED_DRAFT_YEARS = 8
EXPECTED_FIRST_ROUND_RIGHTS_USED = 89

BATCH_SIZE = 10

QUEUE_REQUIRED_COLUMNS = [
    "evidence_queue_rank",
    "evidence_priority",
    "team_abbreviation",
    "draft_year",
    "optimizer_candidate_rows",
    "one_for_one_candidate_rows",
    "two_for_one_candidate_rows",
    "unique_first_round_rights",
    "first_round_right_ids",
    "maximum_heuristic_optimizer_score",
    "known_standalone_first_round_right_rows",
    "evidence_priority_reason",
    "required_research_fields",
    "research_status",
    "automatic_legality_ready",
]

RIGHT_REQUIRED_COLUMNS = [
    "attached_pick_right_id",
    "attached_pick_team",
    "right_display_name",
    "right_structure",
    "optimizer_candidate_rows",
    "one_for_one_candidate_rows",
    "two_for_one_candidate_rows",
    "base_packages",
    "draft_years",
    "average_attached_pick_value_score",
    "average_value_gap_improvement",
    "average_heuristic_optimizer_score",
    "maximum_heuristic_optimizer_score",
    "inventory_match_all",
    "team_match_all",
    "final_legal_rows",
]

PICK_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "candidate_team",
    "right_display_name",
    "right_structure",
    "source_assets",
    "originating_teams",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "candidate_right_value_score",
    "expected_pick_count",
    "tradability_status",
    "standalone_trade_asset_flag",
]

RESEARCH_INPUT_COLUMNS = [
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

PHASE_MAP = {
    1: {
        "research_phase": "phase_1_direct_optimizer_exposure",
        "phase_description": (
            "Resolve 2027-2029 team-year records directly affecting "
            "existing first-round pick-attached optimizer packages."
        ),
    },
    2: {
        "research_phase": "phase_2_stepien_extension_exposed_teams",
        "phase_description": (
            "Resolve 2030-2033 Stepien-horizon records for teams currently "
            "attaching first-round rights."
        ),
    },
    3: {
        "research_phase": "phase_3_frozen_pick_exposed_teams",
        "phase_description": (
            "Resolve 2034 frozen-pick records for teams currently attaching "
            "first-round rights."
        ),
    },
    4: {
        "research_phase": "phase_4_known_unused_first_round_rights",
        "phase_description": (
            "Resolve known 2027-2029 first-round rights not currently used "
            "by optimizer packages."
        ),
    },
    5: {
        "research_phase": "phase_5_leaguewide_stepien_completion",
        "phase_description": (
            "Complete remaining 2030-2033 Stepien calendar rows."
        ),
    },
    6: {
        "research_phase": "phase_6_leaguewide_frozen_pick_completion",
        "phase_description": (
            "Complete remaining 2034 frozen-pick tracking."
        ),
    },
    7: {
        "research_phase": "phase_7_baseline_own_first_control",
        "phase_description": (
            "Complete unresolved 2027-2029 own-first control records with "
            "no direct package exposure."
        ),
    },
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


def split_pipe(value: Any) -> list[str]:
    return [
        clean_text(token)
        for token in clean_text(value).split("|")
        if clean_text(token)
    ]


def load_inputs() -> dict[str, pd.DataFrame]:
    for path, label in [
        (
            EVIDENCE_QUEUE_PATH,
            "legality evidence queue",
        ),
        (
            TEAM_EXPOSURE_PATH,
            "team exposure summary",
        ),
        (
            RIGHT_EXPOSURE_PATH,
            "right exposure summary",
        ),
        (
            CALENDAR_PATH,
            "future first-round legality calendar",
        ),
        (
            PICK_INVENTORY_PATH,
            "canonical future-pick inventory",
        ),
    ]:
        require_file(path, label)

    queue = pd.read_csv(EVIDENCE_QUEUE_PATH)
    teams = pd.read_csv(TEAM_EXPOSURE_PATH)
    rights = pd.read_csv(RIGHT_EXPOSURE_PATH)
    calendar = pd.read_parquet(CALENDAR_PATH)
    picks = pd.read_parquet(PICK_INVENTORY_PATH)

    require_columns(
        queue,
        QUEUE_REQUIRED_COLUMNS,
        "Legality evidence queue",
    )

    require_columns(
        rights,
        RIGHT_REQUIRED_COLUMNS,
        "Right exposure summary",
    )

    require_columns(
        picks,
        PICK_REQUIRED_COLUMNS,
        "Canonical future-pick inventory",
    )

    return {
        "queue": queue,
        "teams": teams,
        "rights": rights,
        "calendar": calendar,
        "picks": picks,
    }


def prepare_right_lookup(
    rights: pd.DataFrame,
    picks: pd.DataFrame,
) -> pd.DataFrame:
    right_summary = rights.copy()

    right_summary["attached_pick_team"] = normalize_team(
        right_summary["attached_pick_team"]
    )

    inventory = picks.copy()

    inventory["candidate_team"] = normalize_team(
        inventory["candidate_team"]
    )

    inventory["standalone_trade_asset_flag"] = (
        parse_bool_series(
            inventory["standalone_trade_asset_flag"]
        )
    )

    inventory = inventory.loc[
        inventory["standalone_trade_asset_flag"]
    ].copy()

    inventory_columns = [
        "future_pick_right_id",
        "candidate_team",
        "source_assets",
        "originating_teams",
        "draft_year_min",
        "draft_year_max",
        "round_numbers",
        "candidate_right_value_score",
        "expected_pick_count",
        "tradability_status",
    ]

    inventory = inventory[
        inventory_columns
    ].rename(
        columns={
            "candidate_team": "inventory_candidate_team",
            "candidate_right_value_score": (
                "inventory_right_value_score"
            ),
        }
    )

    output = right_summary.merge(
        inventory,
        how="left",
        left_on="attached_pick_right_id",
        right_on="future_pick_right_id",
        validate="one_to_one",
    )

    output["inventory_right_match"] = (
        output["future_pick_right_id"].notna()
    )

    output["inventory_team_match"] = (
        output["attached_pick_team"]
        .eq(
            output["inventory_candidate_team"]
        )
    )

    return output


def create_research_queries(
    team: str,
    draft_year: int,
    right_names: list[str],
) -> tuple[str, str, str]:
    right_context = " ".join(
        right_names[:3]
    )

    query_one = (
        f"{team} {draft_year} NBA first round pick current owner "
        f"protection swap obligation"
    )

    query_two = (
        f"{team} future draft picks {draft_year} first round "
        f"transactions ownership"
    )

    query_three = (
        f"{team} {draft_year} own first round pick Stepien "
        f"encumbrance {right_context}"
    ).strip()

    return (
        query_one,
        query_two,
        query_three,
    )


def summarize_queue_rights(
    queue: pd.DataFrame,
    right_lookup: pd.DataFrame,
) -> pd.DataFrame:
    lookup = (
        right_lookup.set_index(
            "attached_pick_right_id"
        )
        if not right_lookup.empty
        else pd.DataFrame()
    )

    rows = []

    for row in queue.itertuples(index=False):
        right_ids = split_pipe(
            row.first_round_right_ids
        )

        matched_rows = []

        for right_id in right_ids:
            if (
                not right_lookup.empty
                and right_id in lookup.index
            ):
                matched = lookup.loc[
                    right_id
                ]

                if isinstance(
                    matched,
                    pd.DataFrame,
                ):
                    matched = matched.iloc[0]

                matched_rows.append(
                    matched
                )

        right_names = sorted(
            {
                clean_text(
                    matched.get(
                        "right_display_name",
                        "",
                    )
                )
                for matched in matched_rows
                if clean_text(
                    matched.get(
                        "right_display_name",
                        "",
                    )
                )
            }
        )

        right_structures = sorted(
            {
                clean_text(
                    matched.get(
                        "right_structure",
                        "",
                    )
                )
                for matched in matched_rows
                if clean_text(
                    matched.get(
                        "right_structure",
                        "",
                    )
                )
            }
        )

        source_assets = sorted(
            {
                asset
                for matched in matched_rows
                for asset in split_pipe(
                    matched.get(
                        "source_assets",
                        "",
                    )
                )
            }
        )

        originating_teams = sorted(
            {
                team
                for matched in matched_rows
                for team in split_pipe(
                    matched.get(
                        "originating_teams",
                        "",
                    )
                )
            }
        )

        (
            query_one,
            query_two,
            query_three,
        ) = create_research_queries(
            clean_text(
                row.team_abbreviation
            ),
            int(row.draft_year),
            right_names,
        )

        phase = PHASE_MAP[
            int(row.evidence_priority)
        ]

        rows.append(
            {
                **row._asdict(),
                "research_phase": (
                    phase[
                        "research_phase"
                    ]
                ),
                "research_phase_description": (
                    phase[
                        "phase_description"
                    ]
                ),
                "matched_exposed_right_count": len(
                    matched_rows
                ),
                "matched_exposed_right_ids": "|".join(
                    right_ids
                ),
                "matched_exposed_right_names": "|".join(
                    right_names
                ),
                "matched_exposed_right_structures": "|".join(
                    right_structures
                ),
                "matched_exposed_source_assets": "|".join(
                    source_assets
                ),
                "matched_exposed_originating_teams": "|".join(
                    originating_teams
                ),
                "all_referenced_rights_matched": (
                    len(matched_rows)
                    == len(right_ids)
                ),
                "research_query_primary": query_one,
                "research_query_secondary": query_two,
                "research_query_structure": query_three,
            }
        )

    return pd.DataFrame(rows)


def assign_batches(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    output_parts = []

    for priority, group in queue.groupby(
        "evidence_priority",
        sort=True,
    ):
        ordered = group.sort_values(
            [
                "evidence_queue_rank",
                "team_abbreviation",
                "draft_year",
            ]
        ).reset_index(drop=True)

        ordered["phase_row_number"] = (
            np.arange(
                1,
                len(ordered) + 1,
            )
        )

        ordered["phase_batch_number"] = (
            (
                ordered[
                    "phase_row_number"
                ]
                - 1
            )
            // BATCH_SIZE
            + 1
        )

        ordered["research_batch_id"] = (
            "P"
            + str(int(priority))
            + "-B"
            + ordered[
                "phase_batch_number"
            ]
            .astype(int)
            .astype(str)
            .str.zfill(2)
        )

        output_parts.append(ordered)

    output = pd.concat(
        output_parts,
        ignore_index=True,
        sort=False,
    )

    return output.sort_values(
        [
            "evidence_priority",
            "phase_batch_number",
            "phase_row_number",
        ]
    ).reset_index(drop=True)


def initialize_evidence_fields(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    output = queue.copy()

    defaults: dict[str, Any] = {
        "own_first_round_source_asset_id": "",
        "own_first_round_current_owner_team": "",
        "own_first_round_control_status": "unresolved",
        "own_first_round_retained_status": "unresolved",
        "own_first_round_outgoing_obligation_status": "unresolved",
        "own_first_round_swap_status": "unresolved",
        "own_first_round_protection_status": "unresolved",
        "own_first_round_encumbrance_status": "unresolved",
        "deterministic_first_round_availability": "unknown",
        "stepien_availability_after_proposed_trade": "not_evaluated",
        "second_apron_frozen_pick_status": "not_applicable",
        "second_apron_freeze_trigger_cap_year": "",
        "second_apron_unfreeze_condition": "",
        "draft_pick_penalty_status": "unresolved",
        "authoritative_source_name": "",
        "authoritative_source_url": "",
        "authoritative_source_as_of_date": "",
        "source_effective_start_date": "",
        "source_effective_end_date": "",
        "source_authority_verified": False,
        "reviewer_name": "",
        "reviewer_notes": "",
    }

    for column, default in defaults.items():
        output[column] = default

    output.loc[
        output["draft_year"].eq(2034),
        "second_apron_frozen_pick_status",
    ] = "unresolved"

    output["research_status"] = "not_started"
    output["automatic_legality_ready"] = False
    output["manual_review_required"] = True

    return output


def build_batch_manifest(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for batch_id, group in queue.groupby(
        "research_batch_id",
        sort=False,
    ):
        rows.append(
            {
                "research_batch_id": batch_id,
                "evidence_priority": int(
                    group[
                        "evidence_priority"
                    ].iloc[0]
                ),
                "research_phase": (
                    group[
                        "research_phase"
                    ].iloc[0]
                ),
                "research_phase_description": (
                    group[
                        "research_phase_description"
                    ].iloc[0]
                ),
                "batch_row_count": int(
                    len(group)
                ),
                "first_queue_rank": int(
                    group[
                        "evidence_queue_rank"
                    ].min()
                ),
                "last_queue_rank": int(
                    group[
                        "evidence_queue_rank"
                    ].max()
                ),
                "teams": "|".join(
                    sorted(
                        group[
                            "team_abbreviation"
                        ]
                        .astype(str)
                        .unique()
                    )
                ),
                "draft_years": "|".join(
                    str(year)
                    for year in sorted(
                        group[
                            "draft_year"
                        ].unique()
                    )
                ),
                "optimizer_candidate_rows": int(
                    pd.to_numeric(
                        group[
                            "optimizer_candidate_rows"
                        ],
                        errors="coerce",
                    )
                    .fillna(0)
                    .sum()
                ),
                "unique_referenced_rights": int(
                    len(
                        {
                            right_id
                            for value in group[
                                "matched_exposed_right_ids"
                            ]
                            for right_id in split_pipe(
                                value
                            )
                        }
                    )
                ),
                "research_status": "not_started",
                "completed_rows": 0,
                "automatic_legality_ready_rows": 0,
            }
        )

    return pd.DataFrame(rows)


def build_phase_summary(
    queue: pd.DataFrame,
) -> pd.DataFrame:
    return (
        queue.groupby(
            [
                "evidence_priority",
                "research_phase",
                "research_phase_description",
            ],
            as_index=False,
        )
        .agg(
            queue_rows=(
                "evidence_queue_rank",
                "size",
            ),
            research_batches=(
                "research_batch_id",
                "nunique",
            ),
            teams=(
                "team_abbreviation",
                "nunique",
            ),
            first_draft_year=(
                "draft_year",
                "min",
            ),
            last_draft_year=(
                "draft_year",
                "max",
            ),
            optimizer_candidate_rows=(
                "optimizer_candidate_rows",
                "sum",
            ),
            referenced_right_rows=(
                "matched_exposed_right_count",
                "sum",
            ),
            automatic_legality_ready_rows=(
                "automatic_legality_ready",
                "sum",
            ),
        )
        .sort_values(
            "evidence_priority"
        )
        .reset_index(drop=True)
    )


def build_packet_json(
    queue: pd.DataFrame,
    manifest: pd.DataFrame,
) -> dict[str, Any]:
    batches = []

    for manifest_row in manifest.itertuples(
        index=False
    ):
        rows = queue.loc[
            queue[
                "research_batch_id"
            ].eq(
                manifest_row.research_batch_id
            )
        ]

        batches.append(
            {
                "research_batch_id": (
                    manifest_row.research_batch_id
                ),
                "evidence_priority": int(
                    manifest_row.evidence_priority
                ),
                "research_phase": (
                    manifest_row.research_phase
                ),
                "research_phase_description": (
                    manifest_row.research_phase_description
                ),
                "batch_row_count": int(
                    manifest_row.batch_row_count
                ),
                "teams": split_pipe(
                    manifest_row.teams
                ),
                "draft_years": [
                    int(value)
                    for value in split_pipe(
                        manifest_row.draft_years
                    )
                ],
                "records": [
                    json_safe(record)
                    for record in rows.to_dict(
                        orient="records"
                    )
                ],
            }
        )

    return {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "batch_size": BATCH_SIZE,
        "research_input_columns": (
            RESEARCH_INPUT_COLUMNS
        ),
        "batches": batches,
    }


def build_validation(
    *,
    inputs: dict[str, pd.DataFrame],
    right_lookup: pd.DataFrame,
    queue: pd.DataFrame,
    priority_one: pd.DataFrame,
    manifest: pd.DataFrame,
    phase_summary: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_queue_rows = int(
        queue.duplicated(
            subset=[
                "team_abbreviation",
                "draft_year",
            ]
        ).sum()
    )

    duplicate_batch_assignments = int(
        queue[
            "evidence_queue_rank"
        ].duplicated().sum()
    )

    referenced_rows = queue.loc[
        queue[
            "matched_exposed_right_ids"
        ]
        .fillna("")
        .astype(str)
        .ne("")
    ]

    unmatched_referenced_rows = int(
        (
            ~referenced_rows[
                "all_referenced_rights_matched"
            ]
        ).sum()
    )

    missing_query_rows = int(
        queue[
            [
                "research_query_primary",
                "research_query_secondary",
                "research_query_structure",
            ]
        ]
        .fillna("")
        .astype(str)
        .eq("")
        .any(axis=1)
        .sum()
    )

    missing_input_columns = [
        column
        for column in RESEARCH_INPUT_COLUMNS
        if column not in queue.columns
    ]

    priority_one_bad_exposure = int(
        (
            pd.to_numeric(
                priority_one[
                    "optimizer_candidate_rows"
                ],
                errors="coerce",
            )
            .fillna(0)
            <= 0
        ).sum()
    )

    phase_two_rows = int(
        (
            queue[
                "evidence_priority"
            ]
            == 2
        ).sum()
    )

    phase_three_rows = int(
        (
            queue[
                "evidence_priority"
            ]
            == 3
        ).sum()
    )

    checks = [
        {
            "check_name": "source_evidence_queue_rows",
            "observed_value": len(
                inputs["queue"]
            ),
            "expected_value": EXPECTED_QUEUE_ROWS,
            "passed": (
                len(inputs["queue"])
                == EXPECTED_QUEUE_ROWS
            ),
        },
        {
            "check_name": "research_queue_rows",
            "observed_value": len(queue),
            "expected_value": EXPECTED_QUEUE_ROWS,
            "passed": len(queue) == EXPECTED_QUEUE_ROWS,
        },
        {
            "check_name": "priority_one_rows",
            "observed_value": len(priority_one),
            "expected_value": EXPECTED_PRIORITY_ONE_ROWS,
            "passed": (
                len(priority_one)
                == EXPECTED_PRIORITY_ONE_ROWS
            ),
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
            "check_name": "right_exposure_rows",
            "observed_value": len(
                right_lookup
            ),
            "expected_value": (
                EXPECTED_FIRST_ROUND_RIGHTS_USED
            ),
            "passed": (
                len(right_lookup)
                == EXPECTED_FIRST_ROUND_RIGHTS_USED
            ),
        },
        {
            "check_name": "right_inventory_matches",
            "observed_value": int(
                (
                    ~right_lookup[
                        "inventory_right_match"
                    ]
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                right_lookup[
                    "inventory_right_match"
                ].all()
            ),
        },
        {
            "check_name": "right_team_matches",
            "observed_value": int(
                (
                    ~right_lookup[
                        "inventory_team_match"
                    ]
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                right_lookup[
                    "inventory_team_match"
                ].all()
            ),
        },
        {
            "check_name": "unique_queue_team_year_rows",
            "observed_value": duplicate_queue_rows,
            "expected_value": 0,
            "passed": duplicate_queue_rows == 0,
        },
        {
            "check_name": "unique_batch_assignment_per_queue_row",
            "observed_value": duplicate_batch_assignments,
            "expected_value": 0,
            "passed": duplicate_batch_assignments == 0,
        },
        {
            "check_name": "all_referenced_rights_matched",
            "observed_value": unmatched_referenced_rows,
            "expected_value": 0,
            "passed": unmatched_referenced_rows == 0,
        },
        {
            "check_name": "all_research_queries_populated",
            "observed_value": missing_query_rows,
            "expected_value": 0,
            "passed": missing_query_rows == 0,
        },
        {
            "check_name": "all_research_input_columns_present",
            "observed_value": len(
                missing_input_columns
            ),
            "expected_value": 0,
            "passed": len(
                missing_input_columns
            )
            == 0,
        },
        {
            "check_name": "priority_one_rows_have_direct_exposure",
            "observed_value": priority_one_bad_exposure,
            "expected_value": 0,
            "passed": priority_one_bad_exposure == 0,
        },
        {
            "check_name": "phase_two_stepien_rows",
            "observed_value": phase_two_rows,
            "expected_value": 120,
            "passed": phase_two_rows == 120,
        },
        {
            "check_name": "phase_three_frozen_pick_rows",
            "observed_value": phase_three_rows,
            "expected_value": 30,
            "passed": phase_three_rows == 30,
        },
        {
            "check_name": "batch_manifest_covers_all_rows",
            "observed_value": int(
                manifest[
                    "batch_row_count"
                ].sum()
            ),
            "expected_value": EXPECTED_QUEUE_ROWS,
            "passed": int(
                manifest[
                    "batch_row_count"
                ].sum()
            )
            == EXPECTED_QUEUE_ROWS,
        },
        {
            "check_name": "phase_summary_covers_all_rows",
            "observed_value": int(
                phase_summary[
                    "queue_rows"
                ].sum()
            ),
            "expected_value": EXPECTED_QUEUE_ROWS,
            "passed": int(
                phase_summary[
                    "queue_rows"
                ].sum()
            )
            == EXPECTED_QUEUE_ROWS,
        },
        {
            "check_name": "no_rows_marked_automatic_legal",
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
    print("FUTURE FIRST-ROUND LEGALITY RESEARCH PACKETS")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/8] Loading evidence queue and supporting artifacts")
    inputs = load_inputs()

    queue = inputs["queue"].copy()

    queue["team_abbreviation"] = normalize_team(
        queue["team_abbreviation"]
    )

    queue["automatic_legality_ready"] = (
        parse_bool_series(
            queue["automatic_legality_ready"]
        )
    )

    print("[2/8] Building right-level evidence lookup")
    right_lookup = prepare_right_lookup(
        inputs["rights"],
        inputs["picks"],
    )

    print("[3/8] Attaching known right context and search queries")
    research_queue = summarize_queue_rights(
        queue,
        right_lookup,
    )

    print("[4/8] Assigning research phases and batches")
    research_queue = assign_batches(
        research_queue
    )

    print("[5/8] Initializing the evidence-input contract")
    research_queue = initialize_evidence_fields(
        research_queue
    )

    priority_one = research_queue.loc[
        research_queue[
            "evidence_priority"
        ].eq(1)
    ].copy()

    manifest = build_batch_manifest(
        research_queue
    )

    phase_summary = build_phase_summary(
        research_queue
    )

    packet_json = build_packet_json(
        research_queue,
        manifest,
    )

    print("[6/8] Validating research packet integrity")
    validation = build_validation(
        inputs=inputs,
        right_lookup=right_lookup,
        queue=research_queue,
        priority_one=priority_one,
        manifest=manifest,
        phase_summary=phase_summary,
    )

    failed = validation.loc[
        ~validation["passed"]
    ]

    print("[7/8] Saving packet and template outputs")
    research_queue.to_csv(
        RESEARCH_QUEUE_PATH,
        index=False,
    )

    priority_one.to_csv(
        PRIORITY_ONE_TEMPLATE_PATH,
        index=False,
    )

    manifest.to_csv(
        BATCH_MANIFEST_PATH,
        index=False,
    )

    phase_summary.to_csv(
        PHASE_SUMMARY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    with PACKETS_JSON_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(packet_json),
            file,
            indent=2,
        )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "research_queue_rows": int(
            len(research_queue)
        ),
        "priority_one_rows": int(
            len(priority_one)
        ),
        "research_batches": int(
            len(manifest)
        ),
        "research_phases": int(
            phase_summary[
                "research_phase"
            ].nunique()
        ),
        "teams": int(
            research_queue[
                "team_abbreviation"
            ].nunique()
        ),
        "draft_years": int(
            research_queue[
                "draft_year"
            ].nunique()
        ),
        "right_exposure_rows": int(
            len(right_lookup)
        ),
        "validation_checks": int(
            len(validation)
        ),
        "validation_checks_passed": int(
            validation["passed"].sum()
        ),
        "research_packet_release_valid": bool(
            failed.empty
        ),
        "scope_note": (
            "These packets organize evidence collection only. Search "
            "queries are research prompts, not evidence. No row or package "
            "is marked legally valid until authoritative records are entered "
            "and separately validated."
        ),
        "output_files": {
            "research_queue": str(
                RESEARCH_QUEUE_PATH
            ),
            "priority_one_template": str(
                PRIORITY_ONE_TEMPLATE_PATH
            ),
            "batch_manifest": str(
                BATCH_MANIFEST_PATH
            ),
            "packet_json": str(
                PACKETS_JSON_PATH
            ),
            "phase_summary": str(
                PHASE_SUMMARY_PATH
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

    print("[8/8] Research packet release saved")
    print()

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY RESEARCH PACKETS CREATED")
    print("=" * 80)
    print(
        "Research queue rows: "
        f"{len(research_queue):,}"
    )
    print(
        "Priority-one rows: "
        f"{len(priority_one):,}"
    )
    print(
        "Research batches: "
        f"{len(manifest):,}"
    )
    print(
        "Research phases: "
        f"{phase_summary['research_phase'].nunique():,}"
    )
    print(
        "Teams represented: "
        f"{research_queue['team_abbreviation'].nunique():,}"
        f"/{EXPECTED_TEAMS}"
    )
    print(
        "Draft years represented: "
        f"{research_queue['draft_year'].nunique():,}"
        f"/{EXPECTED_DRAFT_YEARS}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Research packet release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("RESEARCH PHASE SUMMARY")
    print(
        phase_summary.to_string(
            index=False
        )
    )
    print()

    print("FIRST 20 PRIORITY-ONE RECORDS")
    print(
        priority_one[
            [
                "evidence_queue_rank",
                "research_batch_id",
                "team_abbreviation",
                "draft_year",
                "optimizer_candidate_rows",
                "matched_exposed_right_count",
                "matched_exposed_right_names",
                "research_query_primary",
            ]
        ]
        .head(20)
        .to_string(index=False)
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
        RESEARCH_QUEUE_PATH,
        PRIORITY_ONE_TEMPLATE_PATH,
        BATCH_MANIFEST_PATH,
        PACKETS_JSON_PATH,
        PHASE_SUMMARY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        raise RuntimeError(
            "Future first-round legality research packets "
            "failed validation:\n"
            + failed.to_string(index=False)
        )


if __name__ == "__main__":
    main()