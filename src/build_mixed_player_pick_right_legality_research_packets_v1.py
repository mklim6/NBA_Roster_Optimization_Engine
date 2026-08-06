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
    "mixed-player-pick-right-legality-research-packets-v1-2026-08-04"
)
RELEASE_NAME = "mixed_player_pick_right_legality_research_2026_27_v1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"
BATCH_DIRECTORY = OUTPUT_DIRECTORY / "right_legality_research_batches"

INVENTORY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)
INVENTORY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.csv"
)
STEPIEN_RIGHT_EVALUATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_stepien_right_evaluation_v2.csv"
)

RESEARCH_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_right_legality_research_queue_v1.csv"
)
COMPONENT_GROUP_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_right_legality_component_group_summary_v1.csv"
)
READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_right_legality_research_readiness_v1.csv"
)
METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_right_legality_research_metadata_v1.json"
)

AS_OF_DATE = date(2026, 8, 4)
BATCH_SIZE = 10
EXPECTED_INVENTORY_ROWS = 174
EXPECTED_STANDALONE_RIGHTS = 172
EXPECTED_STEPIEN_EVALUATION_ROWS = 172
EXPECTED_STEPIEN_PASSING_RIGHTS = 111
EXPECTED_RESEARCH_BATCHES = 12

INVENTORY_REQUIRED_COLUMNS = [
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
    "accounting_role",
    "standalone_trade_asset_flag",
    "claim_id",
    "valuation_status",
    "component_right_file",
    "component_right_row_number",
    "component_raw_row_json",
    "source_assets_recovery_method",
    "expected_pick_count_recovery_method",
    "tradability_status",
    "inventory_release",
    "inventory_release_version",
]

STEPIEN_REQUIRED_COLUMNS = [
    "future_pick_right_id",
    "inventory_candidate_team",
    "first_round_right_flag",
    "stepien_evaluation_status",
    "stepien_legality_passed",
    "stepien_manual_review_required",
    "stepien_source_match_method",
    "stepien_requested_source_asset_ids",
    "stepien_excluded_non_first_round_source_asset_ids",
    "frozen_pick_evaluation_status",
    "frozen_pick_legality_passed",
    "calendar_authority_and_date_passed",
    "package_pick_legality_stage_passed",
    "package_pick_legality_manual_review_required",
]

INVENTORY_OUTPUT_COLUMNS = [
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
    "accounting_role",
    "claim_id",
    "valuation_status",
    "component_right_file",
    "component_right_row_number",
    "component_raw_row_json",
    "source_assets_recovery_method",
    "expected_pick_count_recovery_method",
    "tradability_status",
    "inventory_release",
    "inventory_release_version",
]

STEPIEN_OUTPUT_COLUMNS = [
    "first_round_right_flag",
    "stepien_evaluation_status",
    "stepien_legality_passed",
    "stepien_manual_review_required",
    "stepien_source_match_method",
    "stepien_requested_source_asset_ids",
    "stepien_excluded_non_first_round_source_asset_ids",
    "frozen_pick_evaluation_status",
    "frozen_pick_legality_passed",
    "calendar_authority_and_date_passed",
    "package_pick_legality_stage_passed",
    "package_pick_legality_manual_review_required",
]

EDITABLE_EVIDENCE_COLUMNS = [
    "research_status",
    "contractual_right_identity_status",
    "current_owner_team_verified",
    "current_owner_verification_status",
    "source_asset_control_status",
    "standalone_tradability_determination",
    "right_separability_status",
    "right_independent_conveyance_status",
    "encumbrance_status",
    "overlapping_claim_status",
    "protection_fallback_status",
    "trade_date_eligibility_status",
    "cba_pick_rule_status",
    "right_legality_determination",
    "right_terms_summary",
    "resolution_reason",
    "authoritative_source_name",
    "authoritative_source_url",
    "authoritative_source_as_of_date",
    "source_effective_start_date",
    "source_effective_end_date",
    "source_authority_verified",
    "reviewer_name",
    "reviewer_notes",
    "manual_review_required",
]

REQUIRED_RESEARCH_FIELDS = [
    "contractual_right_identity_status",
    "current_owner_team_verified",
    "current_owner_verification_status",
    "source_asset_control_status",
    "standalone_tradability_determination",
    "right_separability_status",
    "right_independent_conveyance_status",
    "encumbrance_status",
    "overlapping_claim_status",
    "protection_fallback_status",
    "trade_date_eligibility_status",
    "cba_pick_rule_status",
    "right_legality_determination",
    "authoritative_source_name",
    "authoritative_source_url",
    "authoritative_source_as_of_date",
    "source_effective_start_date",
    "source_authority_verified",
    "reviewer_name",
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


def normalize_team(value: Any) -> str:
    return clean_text(value).upper()


def parse_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return clean_text(value).lower() in {"true", "1", "yes", "passed"}


def parse_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    return series.map(parse_bool).astype(bool)


def parse_tokens(value: Any) -> list[str]:
    return [
        clean_text(token)
        for token in clean_text(value).split("|")
        if clean_text(token)
    ]


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


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns:\n" + "\n".join(missing))


def read_inventory() -> tuple[pd.DataFrame, Path]:
    if INVENTORY_PARQUET_PATH.exists():
        return pd.read_parquet(INVENTORY_PARQUET_PATH), INVENTORY_PARQUET_PATH
    if INVENTORY_CSV_PATH.exists():
        return pd.read_csv(INVENTORY_CSV_PATH, low_memory=False), INVENTORY_CSV_PATH
    raise FileNotFoundError(
        "The canonical future-pick inventory was not found in Parquet or CSV form.\n"
        f"{INVENTORY_PARQUET_PATH}\n{INVENTORY_CSV_PATH}"
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    inventory, inventory_path = read_inventory()
    if not STEPIEN_RIGHT_EVALUATION_PATH.exists():
        raise FileNotFoundError(
            "The V2 Stepien right evaluation was not found:\n"
            f"{STEPIEN_RIGHT_EVALUATION_PATH}"
        )
    stepien = pd.read_csv(STEPIEN_RIGHT_EVALUATION_PATH, low_memory=False)
    require_columns(inventory, INVENTORY_REQUIRED_COLUMNS, "Canonical pick inventory")
    require_columns(stepien, STEPIEN_REQUIRED_COLUMNS, "V2 Stepien right evaluation")
    return inventory, stepien, inventory_path


def normalize_inputs(
    inventory: pd.DataFrame,
    stepien: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    inventory_output = inventory.copy()
    stepien_output = stepien.copy()

    inventory_output["future_pick_right_id"] = inventory_output[
        "future_pick_right_id"
    ].map(clean_text)
    inventory_output["candidate_team"] = inventory_output["candidate_team"].map(
        normalize_team
    )
    inventory_output["standalone_trade_asset_flag"] = parse_bool_series(
        inventory_output["standalone_trade_asset_flag"]
    )
    inventory_output["source_asset_count"] = pd.to_numeric(
        inventory_output["source_asset_count"], errors="coerce"
    )

    stepien_output["future_pick_right_id"] = stepien_output[
        "future_pick_right_id"
    ].map(clean_text)
    stepien_output["inventory_candidate_team"] = stepien_output[
        "inventory_candidate_team"
    ].map(normalize_team)
    for column in [
        "first_round_right_flag",
        "stepien_legality_passed",
        "stepien_manual_review_required",
        "frozen_pick_legality_passed",
        "calendar_authority_and_date_passed",
        "package_pick_legality_stage_passed",
        "package_pick_legality_manual_review_required",
    ]:
        stepien_output[column] = parse_bool_series(stepien_output[column])

    if inventory_output["future_pick_right_id"].duplicated().any():
        raise RuntimeError("The canonical inventory contains duplicate right IDs.")
    if stepien_output["future_pick_right_id"].duplicated().any():
        raise RuntimeError("The Stepien evaluation contains duplicate right IDs.")

    return inventory_output, stepien_output


def evidence_group_key(row: pd.Series) -> str:
    component_file = clean_text(row.get("component_right_file"))
    claim_id = clean_text(row.get("claim_id"))
    if component_file:
        return f"component_file:{component_file}"
    if claim_id:
        return f"claim:{claim_id}"
    return f"right:{clean_text(row['future_pick_right_id'])}"


def research_classification(row: pd.Series) -> tuple[int, str, str]:
    structure = clean_text(row["right_structure"])
    rounds = set(parse_tokens(row["round_numbers"]))
    source_count = int(row["source_asset_count"])
    complex_flag = bool(
        structure != "direct_owned_pick"
        or source_count > 1
        or rounds == {"1", "2"}
    )
    contains_second = "2" in rounds

    if complex_flag:
        return (
            1,
            "complex_contractual_right",
            (
                "Confirm that the modeled component is a real contractual right, "
                "that it is independently conveyable, and that every linked source, "
                "fallback, protection, swap, pool, and overlapping claim is resolved."
            ),
        )
    if contains_second:
        return (
            2,
            "second_round_direct_right",
            (
                "Verify current ownership, source-pick control, trade-date eligibility, "
                "and absence of overlapping second-round claims or conditions."
            ),
        )
    return (
        3,
        "first_round_direct_calendar_backed",
        (
            "Confirm that the calendar-backed first-round source corresponds to an "
            "independently tradable right held by the candidate team on the trade date."
        ),
    )


def build_research_queue(
    inventory: pd.DataFrame,
    stepien: pd.DataFrame,
) -> pd.DataFrame:
    passing = stepien.loc[
        stepien["package_pick_legality_stage_passed"]
        & ~stepien["package_pick_legality_manual_review_required"]
    ].copy()

    joined = passing.merge(
        inventory,
        how="left",
        on="future_pick_right_id",
        validate="one_to_one",
        suffixes=("_stepien", ""),
    )
    if joined["candidate_team"].isna().any():
        missing = joined.loc[
            joined["candidate_team"].isna(), "future_pick_right_id"
        ].tolist()
        raise RuntimeError(
            "Stepien-passing rights did not match the canonical inventory:\n"
            + "\n".join(missing)
        )
    if not joined["candidate_team"].eq(joined["inventory_candidate_team"]).all():
        raise RuntimeError("Candidate-team mismatch between inventory and Stepien output.")

    classification = joined.apply(
        research_classification,
        axis=1,
        result_type="expand",
    )
    classification.columns = [
        "research_priority",
        "research_group",
        "required_evidence_focus",
    ]
    joined = pd.concat(
        [joined.reset_index(drop=True), classification.reset_index(drop=True)],
        axis=1,
    )
    joined["evidence_group_key"] = joined.apply(evidence_group_key, axis=1)
    joined["complex_structure_flag"] = joined["research_priority"].eq(1)
    joined["contains_first_round_source_flag"] = joined["round_numbers"].map(
        lambda value: "1" in set(parse_tokens(value))
    )
    joined["contains_second_round_source_flag"] = joined["round_numbers"].map(
        lambda value: "2" in set(parse_tokens(value))
    )
    joined["required_research_fields"] = "|".join(REQUIRED_RESEARCH_FIELDS)
    joined["research_as_of_date"] = AS_OF_DATE.isoformat()

    joined = joined.sort_values(
        [
            "research_priority",
            "evidence_group_key",
            "candidate_team",
            "draft_year_min",
            "future_pick_right_id",
        ]
    ).reset_index(drop=True)
    joined["research_sequence"] = np.arange(1, len(joined) + 1)
    joined["research_batch_number"] = (
        (joined["research_sequence"] - 1) // BATCH_SIZE + 1
    )
    joined["research_batch_id"] = joined["research_batch_number"].map(
        lambda number: f"RL-B{int(number):02d}"
    )
    joined["research_row_in_batch"] = (
        joined.groupby("research_batch_id").cumcount() + 1
    )

    defaults: dict[str, Any] = {
        "research_status": "not_started",
        "contractual_right_identity_status": "unknown",
        "current_owner_team_verified": "",
        "current_owner_verification_status": "unknown",
        "source_asset_control_status": "unknown",
        "standalone_tradability_determination": "unknown",
        "right_separability_status": "unknown",
        "right_independent_conveyance_status": "unknown",
        "encumbrance_status": "unknown",
        "overlapping_claim_status": "unknown",
        "protection_fallback_status": "unknown",
        "trade_date_eligibility_status": "unknown",
        "cba_pick_rule_status": "unknown",
        "right_legality_determination": "not_evaluated",
        "right_terms_summary": "",
        "resolution_reason": "",
        "authoritative_source_name": "",
        "authoritative_source_url": "",
        "authoritative_source_as_of_date": "",
        "source_effective_start_date": "",
        "source_effective_end_date": "",
        "source_authority_verified": False,
        "reviewer_name": "",
        "reviewer_notes": "",
        "manual_review_required": True,
    }
    for column, default in defaults.items():
        joined[column] = default

    leading_columns = [
        "research_sequence",
        "research_batch_id",
        "research_row_in_batch",
        "research_priority",
        "research_group",
        "evidence_group_key",
        "required_evidence_focus",
        "required_research_fields",
        "research_as_of_date",
        "complex_structure_flag",
        "contains_first_round_source_flag",
        "contains_second_round_source_flag",
    ]
    selected = [
        *leading_columns,
        *INVENTORY_OUTPUT_COLUMNS,
        *STEPIEN_OUTPUT_COLUMNS,
        *EDITABLE_EVIDENCE_COLUMNS,
    ]
    return joined[[column for column in selected if column in joined.columns]]


def build_component_summary(queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group_key, group in queue.groupby("evidence_group_key", sort=True):
        rows.append(
            {
                "evidence_group_key": group_key,
                "research_priority": int(group["research_priority"].min()),
                "research_groups": "|".join(sorted(set(group["research_group"]))),
                "right_count": len(group),
                "candidate_teams": "|".join(sorted(set(group["candidate_team"]))),
                "future_pick_right_ids": "|".join(group["future_pick_right_id"]),
                "source_assets": "|".join(
                    sorted(
                        {
                            source
                            for value in group["source_assets"]
                            for source in parse_tokens(value)
                        }
                    )
                ),
                "round_numbers": "|".join(sorted(set(group["round_numbers"]))),
                "component_right_files": "|".join(
                    sorted(
                        {
                            clean_text(value)
                            for value in group["component_right_file"]
                            if clean_text(value)
                        }
                    )
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["research_priority", "right_count", "evidence_group_key"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def write_batches(queue: pd.DataFrame) -> list[Path]:
    BATCH_DIRECTORY.mkdir(parents=True, exist_ok=True)
    paths = []
    for batch_id, batch in queue.groupby("research_batch_id", sort=True):
        path = (
            BATCH_DIRECTORY
            / f"mixed_player_pick_right_legality_{batch_id.lower().replace('-', '_')}_evidence_input_v1.csv"
        )
        batch.to_csv(path, index=False)
        paths.append(path)
    return paths


def build_readiness(
    inventory: pd.DataFrame,
    stepien: pd.DataFrame,
    queue: pd.DataFrame,
    batch_paths: list[Path],
) -> pd.DataFrame:
    standalone_count = int(inventory["standalone_trade_asset_flag"].sum())
    passing_count = int(stepien["package_pick_legality_stage_passed"].sum())
    source_counts = queue["source_assets"].map(lambda value: len(parse_tokens(value)))
    checks = [
        ("canonical_inventory_row_count", len(inventory), EXPECTED_INVENTORY_ROWS, len(inventory) == EXPECTED_INVENTORY_ROWS),
        ("standalone_inventory_right_count", standalone_count, EXPECTED_STANDALONE_RIGHTS, standalone_count == EXPECTED_STANDALONE_RIGHTS),
        ("stepien_evaluation_row_count", len(stepien), EXPECTED_STEPIEN_EVALUATION_ROWS, len(stepien) == EXPECTED_STEPIEN_EVALUATION_ROWS),
        ("stepien_passing_right_count", passing_count, EXPECTED_STEPIEN_PASSING_RIGHTS, passing_count == EXPECTED_STEPIEN_PASSING_RIGHTS),
        ("research_queue_row_count", len(queue), EXPECTED_STEPIEN_PASSING_RIGHTS, len(queue) == EXPECTED_STEPIEN_PASSING_RIGHTS),
        ("unique_research_queue_right_ids", int(queue["future_pick_right_id"].nunique()), len(queue), queue["future_pick_right_id"].nunique() == len(queue)),
        ("all_queue_rights_stepien_stage_passed", int(queue["package_pick_legality_stage_passed"].sum()), len(queue), bool(queue["package_pick_legality_stage_passed"].all())),
        ("no_queue_rights_require_stepien_manual_review", int(queue["stepien_manual_review_required"].sum()), 0, not bool(queue["stepien_manual_review_required"].any())),
        ("all_queue_rights_have_source_assets", int(queue["source_assets"].ne("").sum()), len(queue), bool(queue["source_assets"].ne("").all())),
        ("source_asset_counts_match_tokens", int((queue["source_asset_count"].astype(int) == source_counts).sum()), len(queue), bool((queue["source_asset_count"].astype(int) == source_counts).all())),
        ("all_queue_rights_have_research_groups", int(queue["research_group"].ne("").sum()), len(queue), bool(queue["research_group"].ne("").all())),
        ("research_batch_count", len(batch_paths), EXPECTED_RESEARCH_BATCHES, len(batch_paths) == EXPECTED_RESEARCH_BATCHES),
        ("all_batch_files_exist", int(sum(path.exists() for path in batch_paths)), len(batch_paths), all(path.exists() for path in batch_paths)),
        ("maximum_batch_size", int(queue.groupby("research_batch_id").size().max()), BATCH_SIZE, int(queue.groupby("research_batch_id").size().max()) <= BATCH_SIZE),
        ("all_rows_initially_not_started", int(queue["research_status"].eq("not_started").sum()), len(queue), bool(queue["research_status"].eq("not_started").all())),
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


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    BATCH_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK RIGHT LEGALITY RESEARCH PACKETS")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/6] Loading canonical inventory and V2 Stepien right evaluation")
    inventory_raw, stepien_raw, inventory_path = load_inputs()
    inventory, stepien = normalize_inputs(inventory_raw, stepien_raw)

    print("[2/6] Selecting the 111 Stepien-passing standalone rights")
    queue = build_research_queue(inventory, stepien)

    print("[3/6] Grouping shared contractual components and source evidence")
    component_summary = build_component_summary(queue)

    print("[4/6] Writing 10-row evidence research batches")
    batch_paths = write_batches(queue)

    print("[5/6] Validating the research release")
    readiness = build_readiness(inventory, stepien, queue, batch_paths)
    failed = readiness.loc[~readiness["passed"]]

    print("[6/6] Saving queue, summaries, readiness, and metadata")
    queue.to_csv(RESEARCH_QUEUE_PATH, index=False)
    component_summary.to_csv(COMPONENT_GROUP_SUMMARY_PATH, index=False)
    readiness.to_csv(READINESS_PATH, index=False)

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_as_of_date": AS_OF_DATE.isoformat(),
        "inventory_path": str(inventory_path),
        "stepien_evaluation_path": str(STEPIEN_RIGHT_EVALUATION_PATH),
        "inventory_rows": len(inventory),
        "standalone_inventory_rights": int(inventory["standalone_trade_asset_flag"].sum()),
        "stepien_passing_rights": int(stepien["package_pick_legality_stage_passed"].sum()),
        "research_queue_rows": len(queue),
        "complex_right_rows": int(queue["complex_structure_flag"].sum()),
        "direct_right_rows": int((~queue["complex_structure_flag"]).sum()),
        "rights_containing_first_round_sources": int(queue["contains_first_round_source_flag"].sum()),
        "rights_containing_second_round_sources": int(queue["contains_second_round_source_flag"].sum()),
        "evidence_groups": len(component_summary),
        "batch_size": BATCH_SIZE,
        "batch_count": len(batch_paths),
        "readiness_checks": len(readiness),
        "readiness_checks_passed": int(readiness["passed"].sum()),
        "release_valid": bool(failed.empty),
        "scope_note": (
            "This release creates evidence packets for right-level contractual "
            "identity, ownership, source control, separability, independent "
            "conveyance, encumbrance, overlapping claims, protection/fallback "
            "terms, trade-date eligibility, and pick-specific CBA compliance. "
            "It does not mark optimizer packages finally legal."
        ),
        "output_files": {
            "research_queue": str(RESEARCH_QUEUE_PATH),
            "component_group_summary": str(COMPONENT_GROUP_SUMMARY_PATH),
            "readiness": str(READINESS_PATH),
            "metadata": str(METADATA_PATH),
            "batch_files": [str(path) for path in batch_paths],
        },
    }
    METADATA_PATH.write_text(
        json.dumps(json_safe(metadata), indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("RIGHT LEGALITY RESEARCH PACKETS COMPLETE")
    print("=" * 80)
    print(f"Canonical inventory rows: {len(inventory):,}")
    print(f"Stepien-passing rights queued: {len(queue):,}")
    print(f"Complex rights: {int(queue['complex_structure_flag'].sum()):,}")
    print(f"Direct rights: {int((~queue['complex_structure_flag']).sum()):,}")
    print(f"Evidence groups: {len(component_summary):,}")
    print(f"Research batches: {len(batch_paths):,}")
    print(f"Readiness checks passed: {int(readiness['passed'].sum())}/{len(readiness)}")
    print(f"Release valid: {bool(failed.empty)}")
    print()
    print("FIRST BATCH")
    print(batch_paths[0])
    print()
    print("SAVED FILES")
    for path in [
        RESEARCH_QUEUE_PATH,
        COMPONENT_GROUP_SUMMARY_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not failed.empty:
        print()
        print("FAILED READINESS CHECKS")
        print(failed.to_string(index=False))
        raise RuntimeError("Right-legality research release failed validation.")


if __name__ == "__main__":
    main()