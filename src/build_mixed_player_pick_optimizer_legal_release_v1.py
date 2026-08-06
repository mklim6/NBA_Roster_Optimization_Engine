"""Build the optimizer-ready release from the final V9 full-CBA package files.

Place this script in the project's ``src`` directory. It reads the two V9
full-CBA-evaluated package parquets from ``outputs``, extracts only packages
whose deterministic final legality was released, creates a direction-invariant
economic-equivalence key, removes economically duplicate rows conservatively,
and writes full and compact legal pools plus team recommendations and audit
artifacts.

This script does not invent a new basketball-value model. Ranking preserves the
existing optimizer heuristic when available and adds transparent CBA robustness
fields for downstream analysis. The original V9 files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-optimizer-legal-release-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_optimizer_legal_release_2026_27_v1"
SOURCE_RELEASE = "mixed_player_pick_final_full_cba_legality_2026_27_v1"

INPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet",
}

FULL_OUTPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_pool.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_pool.parquet",
}

DEDUPED_OUTPUT_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_deduped.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_deduped.parquet",
}

COMBINED_COMPACT_PARQUET = "mixed_player_pick_optimizer_legal_pool_2026_27_v1.parquet"
COMBINED_COMPACT_CSV = "mixed_player_pick_optimizer_legal_pool_2026_27_v1.csv"
TEAM_RECOMMENDATIONS_CSV = "mixed_player_pick_optimizer_legal_team_recommendations_2026_27_v1.csv"
OVERALL_TOP_CSV = "mixed_player_pick_optimizer_legal_top_500_2026_27_v1.csv"
BRANCH_SUMMARY_CSV = "mixed_player_pick_optimizer_legal_branch_summary_2026_27_v1.csv"
TEAM_EXPOSURE_CSV = "mixed_player_pick_optimizer_legal_team_exposure_2026_27_v1.csv"
DUPLICATE_AUDIT_CSV = "mixed_player_pick_optimizer_legal_duplicate_audit_2026_27_v1.csv"
VALIDATION_CSV = "mixed_player_pick_optimizer_legal_validation_2026_27_v1.csv"
METADATA_JSON = "mixed_player_pick_optimizer_legal_metadata_2026_27_v1.json"

EXPECTED_SOURCE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_SOURCE_COLUMNS = {"one_for_one": 271, "two_for_one": 269}
EXPECTED_LEGAL_ROWS = {"one_for_one": 4_214, "two_for_one": 13_247}
EXPECTED_TOTAL_LEGAL_ROWS = 17_461
TOP_RECOMMENDATIONS_PER_TEAM = 50
OVERALL_TOP_N = 500

REQUIRED_COLUMNS = {
    "optimizer_candidate_id",
    "optimizer_branch",
    "team_a",
    "team_b",
    "side_a_player_ids",
    "side_b_player_ids",
    "side_a_player_names",
    "side_b_player_names",
    "attached_pick_side",
    "attached_pick_right_id",
    "optimizer_package_final_legal",
    "full_cba_deterministic_legal",
    "full_cba_manual_review_required",
    "full_cba_blocked",
    "full_cba_evidence_complete",
    "full_cba_salary_matching_passed",
    "full_cba_aggregation_passed",
    "full_cba_roster_passed",
    "full_cba_hard_cap_passed",
    "full_cba_deterministic_status_released",
    "full_cba_status",
}

LEGAL_BOOLEAN_COLUMNS = [
    "optimizer_package_final_legal",
    "full_cba_deterministic_legal",
    "full_cba_evidence_complete",
    "full_cba_salary_matching_passed",
    "full_cba_aggregation_passed",
    "full_cba_roster_passed",
    "full_cba_hard_cap_passed",
    "full_cba_deterministic_status_released",
]

NONLEGAL_BOOLEAN_COLUMNS = [
    "full_cba_manual_review_required",
    "full_cba_blocked",
]

COMPACT_COLUMN_CANDIDATES = [
    "optimizer_candidate_id",
    "optimizer_branch",
    "base_package_id",
    "candidate_variant_type",
    "team_a",
    "team_b",
    "side_a_player_ids",
    "side_b_player_ids",
    "side_a_player_names",
    "side_b_player_names",
    "side_a_player_trade_salary",
    "side_b_player_trade_salary",
    "side_a_player_value_score",
    "side_b_player_value_score",
    "underpaying_side",
    "underpaying_team",
    "attached_pick_side",
    "attached_pick_team",
    "attached_pick_right_id",
    "right_display_name",
    "right_structure",
    "source_assets",
    "draft_year_min",
    "draft_year_max",
    "round_numbers",
    "originating_teams",
    "expected_pick_count",
    "attached_pick_value_score",
    "attached_pick_trade_salary",
    "side_a_total_asset_value_score",
    "side_b_total_asset_value_score",
    "base_absolute_value_gap",
    "adjusted_absolute_value_gap",
    "value_gap_improvement_score",
    "relative_value_gap",
    "optimizer_value_balance_score",
    "base_fit_signal",
    "fit_signal_percentile",
    "base_realism_signal",
    "realism_signal_percentile",
    "heuristic_optimizer_score_v1",
    "pick_option_rank_within_base_package",
    "tradability_status",
    "team_a_final_cba_outgoing_salary",
    "team_a_final_cba_incoming_salary_for_matching",
    "team_a_final_cba_posttrade_team_salary",
    "team_a_final_cba_posttrade_apron_team_salary",
    "team_a_final_cba_salary_matching_route",
    "team_a_final_cba_salary_matching_max_incoming",
    "team_a_final_cba_salary_matching_margin",
    "team_a_final_cba_hard_cap_level_after_trade",
    "team_b_final_cba_outgoing_salary",
    "team_b_final_cba_incoming_salary_for_matching",
    "team_b_final_cba_posttrade_team_salary",
    "team_b_final_cba_posttrade_apron_team_salary",
    "team_b_final_cba_salary_matching_route",
    "team_b_final_cba_salary_matching_max_incoming",
    "team_b_final_cba_salary_matching_margin",
    "team_b_final_cba_hard_cap_level_after_trade",
    "full_cba_status",
    "full_cba_rules_release",
    "full_cba_evaluator_version",
    "optimizer_package_final_legal",
]

APPENDED_COLUMNS = [
    "optimizer_legal_source_package_type",
    "optimizer_economic_equivalence_key",
    "optimizer_economic_equivalent_group_size",
    "optimizer_final_legal_rank_score_v1",
    "optimizer_final_legal_rank_score_source",
    "optimizer_min_salary_matching_margin",
    "optimizer_trade_display",
    "optimizer_cba_route_display",
    "optimizer_legal_release",
    "optimizer_legal_release_version",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free helper tests without reading parquet files.",
    )
    parser.add_argument(
        "--no-csv-pool",
        action="store_true",
        help="Skip the combined legal-pool CSV while still writing parquet outputs.",
    )
    return parser.parse_args()


def project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return script_path.parent


def locate_one(root: Path, filename: str) -> Path:
    preferred = root / "outputs" / filename
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Could not find {filename} beneath {root}")
    if len(matches) > 1:
        joined = "\n  ".join(str(path) for path in matches)
        raise RuntimeError(
            f"Found multiple copies of {filename}; keep exactly one:\n  {joined}"
        )
    return matches[0]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "null", "nan"}:
        return ""
    return re.sub(r"\s+", " ", text)


def normalize_asset_tokens(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = [clean_text(part) for part in re.split(r"[|;,]", text)]
    return sorted({part for part in parts if part})


def side_descriptor(
    team: Any,
    player_ids: Any,
    attached_pick_side: Any,
    attached_pick_right_id: Any,
    side: str,
) -> str:
    team_text = clean_text(team).upper()
    players = normalize_asset_tokens(player_ids)
    pick_side = clean_text(attached_pick_side).upper()
    picks = (
        normalize_asset_tokens(attached_pick_right_id)
        if pick_side == side.upper()
        else []
    )
    return (
        f"team={team_text};players={','.join(players)};"
        f"picks={','.join(picks)}"
    )


def economic_key_from_row(row: dict[str, Any]) -> str:
    branch = clean_text(row.get("optimizer_branch")).lower()
    side_a = side_descriptor(
        row.get("team_a"),
        row.get("side_a_player_ids"),
        row.get("attached_pick_side"),
        row.get("attached_pick_right_id"),
        "A",
    )
    side_b = side_descriptor(
        row.get("team_b"),
        row.get("side_b_player_ids"),
        row.get("attached_pick_side"),
        row.get("attached_pick_right_id"),
        "B",
    )
    ordered = sorted([side_a, side_b])
    raw = f"{branch}||{ordered[0]}||{ordered[1]}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"ECO-{digest}"


def asset_display(players: Any, pick_side: Any, pick_name: Any, side: str) -> str:
    player_text = clean_text(players).replace("|", ", ")
    parts = [player_text] if player_text else []
    if clean_text(pick_side).upper() == side.upper():
        pick_text = clean_text(pick_name)
        if pick_text:
            parts.append(pick_text)
    return " + ".join(parts) if parts else "No listed assets"


def trade_display_from_row(row: dict[str, Any]) -> str:
    team_a = clean_text(row.get("team_a")).upper()
    team_b = clean_text(row.get("team_b")).upper()
    pick_name = (
        clean_text(row.get("right_display_name"))
        or clean_text(row.get("attached_pick_right_id"))
    )
    a_assets = asset_display(
        row.get("side_a_player_names"),
        row.get("attached_pick_side"),
        pick_name,
        "A",
    )
    b_assets = asset_display(
        row.get("side_b_player_names"),
        row.get("attached_pick_side"),
        pick_name,
        "B",
    )
    return f"{team_a} sends {a_assets} to {team_b}; {team_b} sends {b_assets} to {team_a}"


def cba_route_display_from_row(row: dict[str, Any]) -> str:
    a_route = clean_text(row.get("team_a_final_cba_salary_matching_route")) or "unknown"
    b_route = clean_text(row.get("team_b_final_cba_salary_matching_route")) or "unknown"
    return f"Team A: {a_route} | Team B: {b_route}"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def pure_rank_score(row: dict[str, Any]) -> tuple[float, str]:
    for column in [
        "heuristic_optimizer_score_v1",
        "optimizer_value_balance_score",
        "realism_signal_percentile",
        "base_realism_signal",
        "fit_signal_percentile",
        "base_fit_signal",
    ]:
        value = row.get(column)
        if value is not None and clean_text(value) != "":
            return safe_float(value), column
    return 0.0, "constant_zero_fallback"


def run_self_test() -> int:
    base_row = {
        "optimizer_branch": "one_for_one",
        "team_a": "BOS",
        "team_b": "LAL",
        "side_a_player_ids": "2|1",
        "side_b_player_ids": "3",
        "attached_pick_side": "A",
        "attached_pick_right_id": "2028_R1_BOS",
        "side_a_player_names": "Player Two|Player One",
        "side_b_player_names": "Player Three",
        "right_display_name": "2028 BOS first",
        "heuristic_optimizer_score_v1": 88.5,
    }
    swapped_row = {
        **base_row,
        "team_a": "LAL",
        "team_b": "BOS",
        "side_a_player_ids": "3",
        "side_b_player_ids": "1|2",
        "side_a_player_names": "Player Three",
        "side_b_player_names": "Player One|Player Two",
        "attached_pick_side": "B",
    }
    no_pick_row = {**base_row, "attached_pick_side": "", "attached_pick_right_id": ""}
    tests = {
        "asset_tokens_are_sorted": normalize_asset_tokens("2|1|2") == ["1", "2"],
        "economic_key_is_direction_invariant": (
            economic_key_from_row(base_row) == economic_key_from_row(swapped_row)
        ),
        "different_assets_change_key": (
            economic_key_from_row(base_row) != economic_key_from_row(no_pick_row)
        ),
        "trade_display_mentions_both_teams": (
            "BOS sends" in trade_display_from_row(base_row)
            and "LAL sends" in trade_display_from_row(base_row)
        ),
        "existing_heuristic_is_preserved": pure_rank_score(base_row) == (
            88.5,
            "heuristic_optimizer_score_v1",
        ),
        "appended_columns_unique": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
        "final_legality_not_recomputed": (
            "optimizer_package_final_legal" not in APPENDED_COLUMNS
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def frames_equal(left: Any, right: Any) -> bool:
    if hasattr(left, "equals"):
        try:
            return bool(left.equals(right, null_equal=True))
        except TypeError:
            return bool(left.equals(right))
    if hasattr(left, "frame_equal"):
        try:
            return bool(left.frame_equal(right, null_equal=True))
        except TypeError:
            return bool(left.frame_equal(right))
    raise AttributeError("Unsupported Polars DataFrame equality API")


def first_existing(columns: Iterable[str], candidates: list[str]) -> str | None:
    available = set(columns)
    return next((column for column in candidates if column in available), None)


def bool_expr(pl: Any, column: str) -> Any:
    return pl.col(column).fill_null(False).cast(pl.Boolean, strict=False)


def legal_filter_expr(pl: Any) -> Any:
    expression = pl.lit(True)
    for column in LEGAL_BOOLEAN_COLUMNS:
        expression = expression & bool_expr(pl, column)
    for column in NONLEGAL_BOOLEAN_COLUMNS:
        expression = expression & (~bool_expr(pl, column))
    expression = expression & (
        pl.col("full_cba_status") == "final_legal_full_cba_deterministic"
    )
    return expression


def add_optimizer_release_fields(pl: Any, frame: Any, package_type: str) -> Any:
    score_source = first_existing(
        frame.columns,
        [
            "heuristic_optimizer_score_v1",
            "optimizer_value_balance_score",
            "realism_signal_percentile",
            "base_realism_signal",
            "fit_signal_percentile",
            "base_fit_signal",
        ],
    )
    if score_source is None:
        score_expression = pl.lit(0.0)
        score_source_label = "constant_zero_fallback"
    else:
        score_expression = (
            pl.col(score_source).cast(pl.Float64, strict=False).fill_null(0.0)
        )
        score_source_label = score_source

    string_dtype = getattr(pl, "String", pl.Utf8)
    key_struct_columns = [
        "optimizer_branch",
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "attached_pick_side",
        "attached_pick_right_id",
    ]
    display_struct_columns = [
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "attached_pick_side",
        "attached_pick_right_id",
    ]
    if "right_display_name" in frame.columns:
        display_struct_columns.append("right_display_name")

    route_struct_columns = [
        "team_a_final_cba_salary_matching_route",
        "team_b_final_cba_salary_matching_route",
    ]

    margin_a = (
        pl.col("team_a_final_cba_salary_matching_margin")
        .cast(pl.Float64, strict=False)
        .fill_null(0.0)
    )
    margin_b = (
        pl.col("team_b_final_cba_salary_matching_margin")
        .cast(pl.Float64, strict=False)
        .fill_null(0.0)
    )

    output = frame.with_columns(
        [
            pl.lit(package_type).alias("optimizer_legal_source_package_type"),
            pl.struct(key_struct_columns)
            .map_elements(economic_key_from_row, return_dtype=string_dtype)
            .alias("optimizer_economic_equivalence_key"),
            score_expression.alias("optimizer_final_legal_rank_score_v1"),
            pl.lit(score_source_label).alias(
                "optimizer_final_legal_rank_score_source"
            ),
            pl.min_horizontal(margin_a, margin_b).alias(
                "optimizer_min_salary_matching_margin"
            ),
            pl.struct(display_struct_columns)
            .map_elements(trade_display_from_row, return_dtype=string_dtype)
            .alias("optimizer_trade_display"),
            pl.struct(route_struct_columns)
            .map_elements(cba_route_display_from_row, return_dtype=string_dtype)
            .alias("optimizer_cba_route_display"),
            pl.lit(RELEASE_NAME).alias("optimizer_legal_release"),
            pl.lit(SCRIPT_VERSION).alias("optimizer_legal_release_version"),
        ]
    )

    return output.with_columns(
        pl.len()
        .over("optimizer_economic_equivalence_key")
        .alias("optimizer_economic_equivalent_group_size")
    )


def deduplicate_economic_packages(pl: Any, legal: Any) -> tuple[Any, Any]:
    sort_columns = ["optimizer_final_legal_rank_score_v1"]
    descending = [True]

    if "value_gap_improvement_score" in legal.columns:
        sort_columns.append("value_gap_improvement_score")
        descending.append(True)
    if "adjusted_absolute_value_gap" in legal.columns:
        sort_columns.append("adjusted_absolute_value_gap")
        descending.append(False)
    sort_columns.extend(
        ["optimizer_min_salary_matching_margin", "optimizer_candidate_id"]
    )
    descending.extend([True, False])

    sorted_legal = legal.sort(sort_columns, descending=descending)
    deduped = sorted_legal.unique(
        subset=["optimizer_economic_equivalence_key"],
        keep="first",
        maintain_order=True,
    )

    duplicates = sorted_legal.filter(
        pl.col("optimizer_economic_equivalent_group_size") > 1
    ).select(
        [
            column
            for column in [
                "optimizer_economic_equivalence_key",
                "optimizer_economic_equivalent_group_size",
                "optimizer_candidate_id",
                "optimizer_branch",
                "team_a",
                "team_b",
                "side_a_player_names",
                "side_b_player_names",
                "attached_pick_right_id",
                "optimizer_final_legal_rank_score_v1",
                "optimizer_trade_display",
            ]
            if column in sorted_legal.columns
        ]
    )
    return deduped, duplicates


def compact_frame(pl: Any, frame: Any) -> Any:
    columns = [column for column in COMPACT_COLUMN_CANDIDATES if column in frame.columns]
    columns.extend(column for column in APPENDED_COLUMNS if column in frame.columns)
    return frame.select(list(dict.fromkeys(columns)))


def build_recommendations(pl: Any, compact: Any) -> Any:
    common_columns = list(compact.columns)

    side_a = compact.with_columns(
        [
            pl.col("team_a").alias("recommendation_team"),
            pl.lit("A").alias("recommendation_team_side"),
            (
                pl.col("attached_pick_side").fill_null("").str.to_uppercase()
                == "A"
            ).alias("recommendation_team_attaches_pick"),
            pl.col("side_a_player_names").alias(
                "recommendation_team_outgoing_players"
            ),
            pl.col("side_b_player_names").alias(
                "recommendation_team_incoming_players"
            ),
        ]
    )
    side_b = compact.with_columns(
        [
            pl.col("team_b").alias("recommendation_team"),
            pl.lit("B").alias("recommendation_team_side"),
            (
                pl.col("attached_pick_side").fill_null("").str.to_uppercase()
                == "B"
            ).alias("recommendation_team_attaches_pick"),
            pl.col("side_b_player_names").alias(
                "recommendation_team_outgoing_players"
            ),
            pl.col("side_a_player_names").alias(
                "recommendation_team_incoming_players"
            ),
        ]
    )

    recommendations = pl.concat([side_a, side_b], how="diagonal_relaxed")

    sort_columns = ["recommendation_team", "optimizer_final_legal_rank_score_v1"]
    descending = [False, True]
    if "value_gap_improvement_score" in recommendations.columns:
        sort_columns.append("value_gap_improvement_score")
        descending.append(True)
    if "adjusted_absolute_value_gap" in recommendations.columns:
        sort_columns.append("adjusted_absolute_value_gap")
        descending.append(False)
    sort_columns.extend(
        ["optimizer_min_salary_matching_margin", "optimizer_candidate_id"]
    )
    descending.extend([True, False])

    recommendations = recommendations.sort(sort_columns, descending=descending)
    recommendations = recommendations.with_columns(
        pl.col("recommendation_team")
        .cum_count()
        .over("recommendation_team")
        .alias("recommendation_rank_for_team")
    ).filter(pl.col("recommendation_rank_for_team") <= TOP_RECOMMENDATIONS_PER_TEAM)

    preferred = [
        "recommendation_team",
        "recommendation_rank_for_team",
        "recommendation_team_side",
        "recommendation_team_outgoing_players",
        "recommendation_team_incoming_players",
        "recommendation_team_attaches_pick",
        "optimizer_candidate_id",
        "optimizer_branch",
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "attached_pick_team",
        "right_display_name",
        "optimizer_trade_display",
        "optimizer_cba_route_display",
        "optimizer_final_legal_rank_score_v1",
        "optimizer_final_legal_rank_score_source",
        "optimizer_value_balance_score",
        "value_gap_improvement_score",
        "adjusted_absolute_value_gap",
        "base_fit_signal",
        "base_realism_signal",
        "optimizer_min_salary_matching_margin",
        "optimizer_package_final_legal",
        "full_cba_status",
    ]
    return recommendations.select(
        [column for column in preferred if column in recommendations.columns]
    )


def build_team_exposure(pl: Any, compact: Any) -> Any:
    a = compact.select(
        [
            pl.col("team_a").alias("team"),
            pl.lit("A").alias("side"),
            "optimizer_branch",
            "optimizer_candidate_id",
        ]
    )
    b = compact.select(
        [
            pl.col("team_b").alias("team"),
            pl.lit("B").alias("side"),
            "optimizer_branch",
            "optimizer_candidate_id",
        ]
    )
    exposure = pl.concat([a, b], how="vertical")
    return exposure.group_by(["team", "optimizer_branch"]).agg(
        [
            pl.len().alias("legal_package_exposure"),
            pl.col("optimizer_candidate_id").n_unique().alias(
                "unique_legal_candidate_exposure"
            ),
        ]
    ).sort(["team", "optimizer_branch"])


def build_branch_summary(pl: Any, full: dict[str, Any], deduped: dict[str, Any]) -> Any:
    rows = []
    for label in INPUT_FILES:
        full_frame = full[label]
        deduped_frame = deduped[label]
        rows.append(
            {
                "package_type": label,
                "final_legal_rows": full_frame.height,
                "economically_unique_rows": deduped_frame.height,
                "economic_duplicate_rows_removed": full_frame.height - deduped_frame.height,
                "teams_represented": len(
                    set(full_frame["team_a"].to_list())
                    | set(full_frame["team_b"].to_list())
                ),
                "mean_rank_score": float(
                    deduped_frame["optimizer_final_legal_rank_score_v1"].mean()
                    or 0.0
                ),
                "median_rank_score": float(
                    deduped_frame["optimizer_final_legal_rank_score_v1"].median()
                    or 0.0
                ),
            }
        )
    return pl.DataFrame(rows)


def validate_release(
    pl: Any,
    sources: dict[str, Any],
    legal_full: dict[str, Any],
    legal_deduped: dict[str, Any],
    combined_compact: Any,
    recommendations: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(scope: str, name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "scope": scope,
                "check_name": name,
                "passed": bool(passed),
                "observed": observed,
                "expected": expected,
            }
        )

    for label in INPUT_FILES:
        source = sources[label]
        legal = legal_full[label]
        deduped = legal_deduped[label]
        source_legal = source.filter(legal_filter_expr(pl))
        original_columns = list(source.columns)

        check(label, "source_row_count", source.height == EXPECTED_SOURCE_ROWS[label], source.height, EXPECTED_SOURCE_ROWS[label])
        check(label, "source_column_count", source.width == EXPECTED_SOURCE_COLUMNS[label], source.width, EXPECTED_SOURCE_COLUMNS[label])
        check(label, "required_columns_present", not REQUIRED_COLUMNS.difference(source.columns), sorted(REQUIRED_COLUMNS.difference(source.columns)), [])
        check(label, "legal_row_count_exact", legal.height == EXPECTED_LEGAL_ROWS[label], legal.height, EXPECTED_LEGAL_ROWS[label])
        check(label, "source_legal_rows_preserved", frames_equal(source_legal.select(original_columns), legal.select(original_columns)), True, True)
        check(label, "legal_candidate_ids_unique", legal["optimizer_candidate_id"].n_unique() == legal.height, legal["optimizer_candidate_id"].n_unique(), legal.height)
        check(label, "all_final_legal_true", int(legal["optimizer_package_final_legal"].sum()) == legal.height, int(legal["optimizer_package_final_legal"].sum()), legal.height)
        check(label, "all_deterministic_legal_true", int(legal["full_cba_deterministic_legal"].sum()) == legal.height, int(legal["full_cba_deterministic_legal"].sum()), legal.height)
        check(label, "no_manual_rows", int(legal["full_cba_manual_review_required"].sum()) == 0, int(legal["full_cba_manual_review_required"].sum()), 0)
        check(label, "no_blocked_rows", int(legal["full_cba_blocked"].sum()) == 0, int(legal["full_cba_blocked"].sum()), 0)
        check(label, "economic_keys_populated", legal["optimizer_economic_equivalence_key"].null_count() == 0, legal["optimizer_economic_equivalence_key"].null_count(), 0)
        check(label, "deduped_economic_keys_unique", deduped["optimizer_economic_equivalence_key"].n_unique() == deduped.height, deduped["optimizer_economic_equivalence_key"].n_unique(), deduped.height)
        check(label, "deduped_not_larger_than_legal", deduped.height <= legal.height, deduped.height, f"<={legal.height}")

    expected_deduped_total = sum(frame.height for frame in legal_deduped.values())
    recommendation_teams = recommendations["recommendation_team"].n_unique()
    check("global", "total_legal_rows_exact", sum(frame.height for frame in legal_full.values()) == EXPECTED_TOTAL_LEGAL_ROWS, sum(frame.height for frame in legal_full.values()), EXPECTED_TOTAL_LEGAL_ROWS)
    check("global", "combined_compact_matches_deduped", combined_compact.height == expected_deduped_total, combined_compact.height, expected_deduped_total)
    check("global", "combined_candidate_ids_unique", combined_compact["optimizer_candidate_id"].n_unique() == combined_compact.height, combined_compact["optimizer_candidate_id"].n_unique(), combined_compact.height)
    check("global", "recommendations_created", recommendations.height > 0, recommendations.height, ">0")
    check("global", "recommendation_ranks_within_limit", int(recommendations["recommendation_rank_for_team"].max() or 0) <= TOP_RECOMMENDATIONS_PER_TEAM, int(recommendations["recommendation_rank_for_team"].max() or 0), f"<={TOP_RECOMMENDATIONS_PER_TEAM}")
    check("global", "recommendation_teams_nonzero", recommendation_teams > 0, recommendation_teams, ">0")
    check("global", "appended_columns_unique", len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)), len(APPENDED_COLUMNS), len(set(APPENDED_COLUMNS)))

    profile = {
        "release_valid": all(row["passed"] for row in checks),
        "validation_checks_passed": sum(bool(row["passed"]) for row in checks),
        "validation_checks_total": len(checks),
        "source_legal_rows": {label: legal_full[label].height for label in INPUT_FILES},
        "deduped_legal_rows": {label: legal_deduped[label].height for label in INPUT_FILES},
        "economic_duplicate_rows_removed": {
            label: legal_full[label].height - legal_deduped[label].height
            for label in INPUT_FILES
        },
        "combined_deduped_rows": combined_compact.height,
        "recommendation_rows": recommendations.height,
        "recommendation_teams": recommendation_teams,
    }
    return checks, profile


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(
            "Polars is required. Run this script in the nba-roster-optimizer environment."
        ) from exc

    root = project_root()
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("MIXED PLAYER-AND-PICK OPTIMIZER LEGAL RELEASE")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading and validating V9 final full-CBA parquets")
    source_paths = {label: locate_one(root, filename) for label, filename in INPUT_FILES.items()}
    sources: dict[str, Any] = {}
    for label, path in source_paths.items():
        schema = pl.read_parquet_schema(str(path))
        missing = sorted(REQUIRED_COLUMNS.difference(schema))
        if missing:
            raise RuntimeError(f"{path.name} is missing required columns: {missing}")
        preexisting = sorted(set(APPENDED_COLUMNS).intersection(schema))
        if preexisting:
            raise RuntimeError(f"{path.name} already contains legal-release columns: {preexisting}")
        sources[label] = pl.read_parquet(str(path))
        print(f"  {label}: {sources[label].height:,} rows | {sources[label].width:,} columns")

    print("[2/7] Extracting deterministic final-legal rows")
    legal_full: dict[str, Any] = {}
    for label, source in sources.items():
        legal = source.filter(legal_filter_expr(pl))
        legal_full[label] = add_optimizer_release_fields(pl, legal, label)
        print(f"  {label}: {legal_full[label].height:,} legal rows")

    print("[3/7] Building economic-equivalence keys and deduplicating")
    legal_deduped: dict[str, Any] = {}
    duplicate_frames: list[Any] = []
    for label, legal in legal_full.items():
        deduped, duplicates = deduplicate_economic_packages(pl, legal)
        legal_deduped[label] = deduped
        if duplicates.height:
            duplicate_frames.append(duplicates)
        print(f"  {label}: {legal.height:,} -> {deduped.height:,} economically unique rows")

    print("[4/7] Creating compact legal pool and team recommendation tables")
    compact_by_branch = {
        label: compact_frame(pl, frame)
        for label, frame in legal_deduped.items()
    }
    combined_compact = pl.concat(
        list(compact_by_branch.values()),
        how="diagonal_relaxed",
    ).sort(
        ["optimizer_final_legal_rank_score_v1", "optimizer_candidate_id"],
        descending=[True, False],
    )
    recommendations = build_recommendations(pl, combined_compact)
    team_exposure = build_team_exposure(pl, combined_compact)
    branch_summary = build_branch_summary(pl, legal_full, legal_deduped)
    overall_top = combined_compact.head(OVERALL_TOP_N)

    print("[5/7] Validating the optimizer-ready legal release")
    validation_rows, profile = validate_release(
        pl,
        sources,
        legal_full,
        legal_deduped,
        combined_compact,
        recommendations,
    )
    release_valid = profile["release_valid"]

    print("[6/7] Writing legal pools and audit artifacts")
    if release_valid:
        for label in INPUT_FILES:
            legal_full[label].write_parquet(
                str(outputs / FULL_OUTPUT_FILES[label]),
                compression="zstd",
                statistics=True,
            )
            legal_deduped[label].write_parquet(
                str(outputs / DEDUPED_OUTPUT_FILES[label]),
                compression="zstd",
                statistics=True,
            )
        combined_compact.write_parquet(
            str(outputs / COMBINED_COMPACT_PARQUET),
            compression="zstd",
            statistics=True,
        )
        if not args.no_csv_pool:
            combined_compact.write_csv(str(outputs / COMBINED_COMPACT_CSV))

    recommendations.write_csv(str(outputs / TEAM_RECOMMENDATIONS_CSV))
    overall_top.write_csv(str(outputs / OVERALL_TOP_CSV))
    branch_summary.write_csv(str(outputs / BRANCH_SUMMARY_CSV))
    team_exposure.write_csv(str(outputs / TEAM_EXPOSURE_CSV))

    if duplicate_frames:
        duplicate_audit = pl.concat(duplicate_frames, how="diagonal_relaxed")
    else:
        duplicate_audit = pl.DataFrame(
            {
                "optimizer_economic_equivalence_key": [],
                "optimizer_candidate_id": [],
            }
        )
    duplicate_audit.write_csv(str(outputs / DUPLICATE_AUDIT_CSV))

    write_csv(
        outputs / VALIDATION_CSV,
        ["scope", "check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "source_release": SOURCE_RELEASE,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        **profile,
        "inputs": {label: str(path) for label, path in source_paths.items()},
        "outputs": {
            "full_legal": {
                label: str(outputs / filename) if release_valid else None
                for label, filename in FULL_OUTPUT_FILES.items()
            },
            "deduped_legal": {
                label: str(outputs / filename) if release_valid else None
                for label, filename in DEDUPED_OUTPUT_FILES.items()
            },
            "combined_compact_parquet": str(outputs / COMBINED_COMPACT_PARQUET) if release_valid else None,
            "combined_compact_csv": (
                str(outputs / COMBINED_COMPACT_CSV)
                if release_valid and not args.no_csv_pool
                else None
            ),
            "team_recommendations": str(outputs / TEAM_RECOMMENDATIONS_CSV),
            "overall_top": str(outputs / OVERALL_TOP_CSV),
            "branch_summary": str(outputs / BRANCH_SUMMARY_CSV),
            "team_exposure": str(outputs / TEAM_EXPOSURE_CSV),
            "duplicate_audit": str(outputs / DUPLICATE_AUDIT_CSV),
            "validation": str(outputs / VALIDATION_CSV),
        },
        "ranking_policy": {
            "primary": "Preserve heuristic_optimizer_score_v1 when present.",
            "fallback_order": [
                "optimizer_value_balance_score",
                "realism_signal_percentile",
                "base_realism_signal",
                "fit_signal_percentile",
                "base_fit_signal",
                "constant_zero_fallback",
            ],
            "dedupe_tiebreakers": [
                "higher value_gap_improvement_score",
                "lower adjusted_absolute_value_gap",
                "higher minimum salary-matching margin",
                "lower optimizer_candidate_id",
            ],
            "scope_note": (
                "This release filters and ranks already-final-legal packages. It does "
                "not retrain the basketball-value or realism model."
            ),
        },
        "economic_equivalence_policy": (
            "Direction-invariant key based on optimizer branch, each team's sorted "
            "player IDs, and any attached pick right assigned to that team."
        ),
        "final_legality_source_of_truth": "optimizer_package_final_legal from V9",
    }
    write_json(outputs / METADATA_JSON, metadata)

    print("[7/7] Complete")
    print(
        f"Validation: {profile['validation_checks_passed']}/"
        f"{profile['validation_checks_total']}"
    )
    print(f"Release valid: {release_valid}")
    print(
        f"Final legal input: {sum(profile['source_legal_rows'].values()):,} | "
        f"economically unique: {profile['combined_deduped_rows']:,} | "
        f"duplicates removed: {sum(profile['economic_duplicate_rows_removed'].values()):,}"
    )
    print(
        f"Team recommendations: {profile['recommendation_rows']:,} rows across "
        f"{profile['recommendation_teams']} teams"
    )

    if not release_valid:
        failed = [
            f"{row['scope']}::{row['check_name']}"
            for row in validation_rows
            if not row["passed"]
        ]
        print("Failed checks:")
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())