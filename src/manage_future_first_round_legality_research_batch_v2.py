from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-first-round-legality-research-batch-manager-v2-merge-dtype-safe-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
BATCH_DIRECTORY = OUTPUT_DIRECTORY / "legality_research_batches"

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

MERGE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_batch_merge_audit_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_first_round_legality_batch_manager_metadata_v1.json"
)


DEFAULT_BATCH_ID = "P1-B01"

KEY_COLUMNS = [
    "team_abbreviation",
    "draft_year",
]

IMMUTABLE_CONTEXT_COLUMNS = [
    "evidence_queue_rank",
    "evidence_priority",
    "research_batch_id",
    "research_phase",
    "research_phase_description",
    "team_abbreviation",
    "draft_year",
    "optimizer_candidate_rows",
    "one_for_one_candidate_rows",
    "two_for_one_candidate_rows",
    "unique_first_round_rights",
    "first_round_right_ids",
    "maximum_heuristic_optimizer_score",
    "known_standalone_first_round_right_rows",
    "matched_exposed_right_count",
    "matched_exposed_right_ids",
    "matched_exposed_right_names",
    "matched_exposed_right_structures",
    "matched_exposed_source_assets",
    "matched_exposed_originating_teams",
    "research_query_primary",
    "research_query_secondary",
    "research_query_structure",
]

EDITABLE_EVIDENCE_COLUMNS = [
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
    "research_status",
]

ALLOWED_BATCH_PREFIXES = {
    "P1",
    "P2",
    "P3",
    "P4",
    "P5",
    "P6",
    "P7",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return " ".join(str(value).split()).strip()


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
        return None if np.isnan(value) else value

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


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


def normalize_batch_id(value: str) -> str:
    batch_id = clean_text(value).upper()

    if "-B" not in batch_id:
        raise ValueError(
            "Batch ID must look like P1-B01."
        )

    prefix, batch_number = batch_id.split(
        "-B",
        maxsplit=1,
    )

    if prefix not in ALLOWED_BATCH_PREFIXES:
        raise ValueError(
            f"Unsupported batch phase prefix: {prefix}"
        )

    if not batch_number.isdigit():
        raise ValueError(
            "Batch number must be numeric."
        )

    return f"{prefix}-B{int(batch_number):02d}"


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
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
            BATCH_MANIFEST_PATH,
            "research batch manifest",
        ),
    ]:
        require_file(path, label)

    queue = pd.read_csv(
        RESEARCH_QUEUE_PATH,
        dtype=object,
        keep_default_na=False,
    )

    priority_one = pd.read_csv(
        PRIORITY_ONE_TEMPLATE_PATH,
        dtype=object,
        keep_default_na=False,
    )

    manifest = pd.read_csv(
        BATCH_MANIFEST_PATH,
        dtype=object,
        keep_default_na=False,
    )

    require_columns(
        queue,
        [
            "research_batch_id",
            *KEY_COLUMNS,
            *EDITABLE_EVIDENCE_COLUMNS,
        ],
        "Research packet queue",
    )

    require_columns(
        priority_one,
        [
            "research_batch_id",
            *KEY_COLUMNS,
            *EDITABLE_EVIDENCE_COLUMNS,
        ],
        "Priority-one evidence template",
    )

    require_columns(
        manifest,
        [
            "research_batch_id",
            "evidence_priority",
            "research_phase",
            "batch_row_count",
        ],
        "Research batch manifest",
    )

    return queue, priority_one, manifest


def target_template_path(
    batch_id: str,
) -> Path:
    priority = int(
        batch_id.split(
            "-",
            maxsplit=1,
        )[0][1:]
    )

    if priority == 1:
        return PRIORITY_ONE_TEMPLATE_PATH

    return RESEARCH_QUEUE_PATH


def extract_batch(
    *,
    batch_id: str,
    queue: pd.DataFrame,
    manifest: pd.DataFrame,
) -> Path:
    manifest_row = manifest.loc[
        manifest[
            "research_batch_id"
        ]
        .astype(str)
        .str.upper()
        .eq(batch_id)
    ]

    if manifest_row.empty:
        raise ValueError(
            f"Batch ID was not found in the manifest: {batch_id}"
        )

    batch = queue.loc[
        queue[
            "research_batch_id"
        ]
        .astype(str)
        .str.upper()
        .eq(batch_id)
    ].copy()

    expected_rows = int(
        manifest_row[
            "batch_row_count"
        ].iloc[0]
    )

    if len(batch) != expected_rows:
        raise RuntimeError(
            f"{batch_id} contains {len(batch)} rows but the "
            f"manifest expects {expected_rows}."
        )

    if batch.duplicated(
        subset=KEY_COLUMNS
    ).any():
        raise RuntimeError(
            f"{batch_id} contains duplicate team-year keys."
        )

    output_columns = [
        column
        for column in (
            IMMUTABLE_CONTEXT_COLUMNS
            + EDITABLE_EVIDENCE_COLUMNS
        )
        if column in batch.columns
    ]

    batch = batch[
        output_columns
    ].copy()

    batch[
        "batch_editing_instruction"
    ] = (
        "Edit only the evidence fields. Do not change team, year, "
        "batch ID, ranking, candidate counts, right IDs, names, "
        "structures, source assets, or research queries."
    )

    batch[
        "batch_completion_status"
    ] = "not_started"

    BATCH_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        BATCH_DIRECTORY
        / (
            "future_first_round_legality_"
            f"{batch_id.lower().replace('-', '_')}"
            "_evidence_input_v1.csv"
        )
    )

    batch.to_csv(
        output_path,
        index=False,
    )

    return output_path


def compare_immutable_context(
    expected: pd.DataFrame,
    completed: pd.DataFrame,
) -> list[str]:
    failures = []

    expected_indexed = expected.set_index(
        KEY_COLUMNS
    )

    completed_indexed = completed.set_index(
        KEY_COLUMNS
    )

    for column in IMMUTABLE_CONTEXT_COLUMNS:
        if (
            column in KEY_COLUMNS
            or column not in expected_indexed.columns
            or column not in completed_indexed.columns
        ):
            continue

        expected_values = (
            expected_indexed[column]
            .fillna("")
            .astype(str)
            .map(clean_text)
        )

        completed_values = (
            completed_indexed[column]
            .fillna("")
            .astype(str)
            .map(clean_text)
        )

        mismatch_mask = (
            expected_values
            .ne(completed_values)
        )

        if mismatch_mask.any():
            mismatch_keys = [
                f"{team}|{year}"
                for team, year in (
                    mismatch_mask.loc[
                        mismatch_mask
                    ].index.tolist()
                )
            ]

            failures.append(
                f"{column}: "
                + ",".join(
                    mismatch_keys[:20]
                )
            )

    return failures


def merge_completed_batch(
    *,
    completed_path: Path,
    queue: pd.DataFrame,
    priority_one: pd.DataFrame,
    manifest: pd.DataFrame,
) -> tuple[Path, pd.DataFrame]:
    require_file(
        completed_path,
        "completed batch file",
    )

    completed = pd.read_csv(
        completed_path,
        dtype=object,
        keep_default_na=False,
    )

    require_columns(
        completed,
        [
            "research_batch_id",
            *KEY_COLUMNS,
            *EDITABLE_EVIDENCE_COLUMNS,
        ],
        "Completed research batch",
    )

    batch_ids = sorted(
        set(
            completed[
                "research_batch_id"
            ]
            .fillna("")
            .astype(str)
            .str.upper()
            .str.strip()
        )
    )

    if len(batch_ids) != 1:
        raise ValueError(
            "Completed batch file must contain exactly one "
            "research_batch_id."
        )

    batch_id = normalize_batch_id(
        batch_ids[0]
    )

    manifest_row = manifest.loc[
        manifest[
            "research_batch_id"
        ]
        .astype(str)
        .str.upper()
        .eq(batch_id)
    ]

    if manifest_row.empty:
        raise ValueError(
            f"Completed batch ID is not present in the manifest: {batch_id}"
        )

    expected = queue.loc[
        queue[
            "research_batch_id"
        ]
        .astype(str)
        .str.upper()
        .eq(batch_id)
    ].copy()

    expected_keys = set(
        map(
            tuple,
            expected[
                KEY_COLUMNS
            ].itertuples(
                index=False,
                name=None,
            ),
        )
    )

    completed_keys = set(
        map(
            tuple,
            completed[
                KEY_COLUMNS
            ].itertuples(
                index=False,
                name=None,
            ),
        )
    )

    missing_keys = sorted(
        expected_keys - completed_keys
    )

    unexpected_keys = sorted(
        completed_keys - expected_keys
    )

    duplicate_rows = int(
        completed.duplicated(
            subset=KEY_COLUMNS
        ).sum()
    )

    immutable_failures = compare_immutable_context(
        expected,
        completed,
    )

    validation_rows = [
        {
            "check_name": "completed_batch_id",
            "observed_value": batch_id,
            "expected_value": batch_id,
            "passed": True,
        },
        {
            "check_name": "completed_batch_row_count",
            "observed_value": len(completed),
            "expected_value": len(expected),
            "passed": len(completed) == len(expected),
        },
        {
            "check_name": "duplicate_team_year_rows",
            "observed_value": duplicate_rows,
            "expected_value": 0,
            "passed": duplicate_rows == 0,
        },
        {
            "check_name": "missing_expected_team_year_keys",
            "observed_value": len(missing_keys),
            "expected_value": 0,
            "passed": len(missing_keys) == 0,
        },
        {
            "check_name": "unexpected_team_year_keys",
            "observed_value": len(unexpected_keys),
            "expected_value": 0,
            "passed": len(unexpected_keys) == 0,
        },
        {
            "check_name": "immutable_context_changes",
            "observed_value": len(immutable_failures),
            "expected_value": 0,
            "passed": len(immutable_failures) == 0,
        },
    ]

    validation = pd.DataFrame(
        validation_rows
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    if not failed.empty:
        failure_details = []

        if missing_keys:
            failure_details.append(
                "Missing keys: "
                + "|".join(
                    f"{team}:{year}"
                    for team, year in missing_keys
                )
            )

        if unexpected_keys:
            failure_details.append(
                "Unexpected keys: "
                + "|".join(
                    f"{team}:{year}"
                    for team, year in unexpected_keys
                )
            )

        if immutable_failures:
            failure_details.append(
                "Immutable changes: "
                + "|".join(
                    immutable_failures
                )
            )

        raise RuntimeError(
            "Completed batch failed merge validation:\n"
            + validation.to_string(
                index=False
            )
            + (
                "\n\n"
                + "\n".join(
                    failure_details
                )
                if failure_details
                else ""
            )
        )

    template_path = target_template_path(
        batch_id
    )

    template = (
        priority_one.copy()
        if template_path
        == PRIORITY_ONE_TEMPLATE_PATH
        else queue.copy()
    )

    if template.duplicated(
        subset=KEY_COLUMNS
    ).any():
        raise RuntimeError(
            "Target template contains duplicate team-year keys."
        )

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    backup_path = template_path.with_name(
        f"{template_path.stem}_backup_{timestamp}"
        f"{template_path.suffix}"
    )

    shutil.copy2(
        template_path,
        backup_path,
    )

    for column in EDITABLE_EVIDENCE_COLUMNS:
        template[column] = (
            template[column]
            .astype("object")
            .where(
                template[column].notna(),
                "",
            )
        )

        completed[column] = (
            completed[column]
            .astype("object")
            .where(
                completed[column].notna(),
                "",
            )
        )

    target = template.set_index(
        KEY_COLUMNS
    )

    completed_indexed = completed.set_index(
        KEY_COLUMNS
    )

    for column in EDITABLE_EVIDENCE_COLUMNS:
        target[column] = target[column].astype(
            "object"
        )

        completed_indexed[column] = (
            completed_indexed[column].astype(
                "object"
            )
        )

    change_rows = []

    for key in sorted(expected_keys):
        for column in EDITABLE_EVIDENCE_COLUMNS:
            previous_value = target.at[
                key,
                column,
            ]

            new_value = completed_indexed.at[
                key,
                column,
            ]

            if clean_text(
                previous_value
            ) != clean_text(
                new_value
            ):
                change_rows.append(
                    {
                        "merged_at_utc": datetime.now(
                            timezone.utc
                        ).isoformat(),
                        "research_batch_id": batch_id,
                        "team_abbreviation": key[0],
                        "draft_year": key[1],
                        "field_name": column,
                        "previous_value": clean_text(
                            previous_value
                        ),
                        "new_value": clean_text(
                            new_value
                        ),
                        "target_template": str(
                            template_path
                        ),
                        "backup_template": str(
                            backup_path
                        ),
                    }
                )

            target.at[
                key,
                column,
            ] = new_value

    merged = target.reset_index()

    merged.to_csv(
        template_path,
        index=False,
    )

    audit = pd.DataFrame(
        change_rows
    )

    if MERGE_AUDIT_PATH.exists():
        previous_audit = pd.read_csv(
            MERGE_AUDIT_PATH,
            dtype=object,
            keep_default_na=False,
        )

        audit = pd.concat(
            [
                previous_audit,
                audit,
            ],
            ignore_index=True,
            sort=False,
        )

    audit.to_csv(
        MERGE_AUDIT_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "updated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "last_merged_batch_id": batch_id,
        "last_completed_batch_file": str(
            completed_path
        ),
        "target_template": str(
            template_path
        ),
        "backup_template": str(
            backup_path
        ),
        "last_merge_change_rows": len(
            change_rows
        ),
        "merge_validation": validation.to_dict(
            orient="records"
        ),
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

    return template_path, validation


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a legality research batch or merge a completed "
            "batch back into the canonical editable template."
        )
    )

    parser.add_argument(
        "--batch-id",
        default=DEFAULT_BATCH_ID,
        help=(
            "Batch to extract, such as P1-B01. "
            f"Default: {DEFAULT_BATCH_ID}"
        ),
    )

    parser.add_argument(
        "--merge-completed",
        type=Path,
        default=None,
        help=(
            "Path to a completed batch CSV. When supplied, the "
            "script validates and merges only editable evidence fields."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    BATCH_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE FIRST-ROUND LEGALITY RESEARCH BATCH MANAGER")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    queue, priority_one, manifest = load_inputs()

    if args.merge_completed is not None:
        print("[1/3] Loading and validating completed batch")
        target_path, validation = (
            merge_completed_batch(
                completed_path=(
                    args.merge_completed
                ),
                queue=queue,
                priority_one=priority_one,
                manifest=manifest,
            )
        )

        print("[2/3] Merging editable evidence fields")
        print("[3/3] Saving merge audit and backup")
        print()
        print("=" * 80)
        print("COMPLETED LEGALITY RESEARCH BATCH MERGED")
        print("=" * 80)
        print(
            "Updated template: "
            f"{target_path}"
        )
        print(
            "Merge validation checks passed: "
            f"{int(validation['passed'].sum())}"
            f"/{len(validation)}"
        )
        print(
            "Merge audit: "
            f"{MERGE_AUDIT_PATH}"
        )
        return

    batch_id = normalize_batch_id(
        args.batch_id
    )

    print("[1/3] Locating requested batch")
    print("[2/3] Validating batch rows and immutable context")
    output_path = extract_batch(
        batch_id=batch_id,
        queue=queue,
        manifest=manifest,
    )
    print("[3/3] Saving editable batch worksheet")
    print()
    print("=" * 80)
    print("LEGALITY RESEARCH BATCH EXTRACTED")
    print("=" * 80)
    print(f"Batch ID: {batch_id}")
    print(f"Editable worksheet: {output_path}")
    print(
        "After completing the worksheet, merge it with:\n"
        f'python ".\\src\\manage_future_first_round_legality_research_batch_v2.py" '
        f'--merge-completed "{output_path}"'
    )


if __name__ == "__main__":
    main()