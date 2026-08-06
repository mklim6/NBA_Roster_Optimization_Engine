"""Apply a front-office quality gate to the final-legal mixed trade pool.

This stage does not alter CBA legality. It reads the V10 final-legal deduplicated
parquets, repairs branch-specific player-value aliases, joins the calibrated
player market layer, identifies protected-core players, calculates team-side
retention metrics, and classifies every legal package as one of:

- routine_recommendation_review
- routine_plus_minor_assets_review
- premium_blockbuster_concept
- strategy_specific_manual_review
- filtered_quality_gate

The script also creates team-perspective review rows. Their score is explicitly
a screening score, not a final team-strategy recommendation score. Team direction,
public trade availability, ownership preference, and timeline objectives remain
outside this release and must be added in the next strategy layer.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "mixed-player-pick-recommendation-quality-gate-v3-2026-08-05"
RELEASE_NAME = "mixed_player_pick_recommendation_quality_gate_2026_27_v3"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

INPUT_FILES = {
    "one_for_one": (
        OUTPUT_DIRECTORY
        / "one_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_deduped.parquet"
    ),
    "two_for_one": (
        OUTPUT_DIRECTORY
        / "two_for_one_mixed_player_pick_candidates_2026_27_v10_optimizer_legal_deduped.parquet"
    ),
}
EXPECTED_INPUT_ROWS = {"one_for_one": 4_214, "two_for_one": 13_247}
EXPECTED_TOTAL_ROWS = 17_461

PLAYER_MARKET_V3_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)
PLAYER_MARKET_V2_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v2_calibrated.parquet"
)
PLAYER_MARKET_V1_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27.parquet"
)
TEAM_PROTECTION_PATH = (
    DATA_DIRECTORY
    / "team_trade_protection_profiles_2026_27.csv"
)
PROTECTION_OVERRIDE_PATH = (
    DATA_DIRECTORY
    / "player_protection_overrides_2026_27_v1.csv"
)

OUTPUT_PARQUET = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_2026_27_v3.parquet"
)
ROUTINE_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_routine_recommendation_review_2026_27_v3.csv"
)
MINOR_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_minor_asset_recommendation_review_2026_27_v3.csv"
)
BLOCKBUSTER_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_premium_blockbuster_concepts_2026_27_v3.csv"
)
STRATEGY_MANUAL_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_specific_manual_review_2026_27_v3.csv"
)
FILTERED_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_quality_gate_filtered_audit_2026_27_v3.csv"
)
TEAM_PERSPECTIVE_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_perspective_quality_review_2026_27_v3.csv"
)
TEAM_TOP_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_quality_gate_top_50_2026_27_v3.csv"
)
SUMMARY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_summary_v3.csv"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_validation_v3.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_metadata_v3.json"
)

FRONT_OFFICE_VALUE_WEIGHTS = {
    "market_value_percentile": 0.40,
    "expected_contribution_percentile": 0.25,
    "downside_contribution_percentile": 0.15,
    "roster_value_percentile": 0.10,
    "age_market_score": 0.07,
    "contract_control_score": 0.03,
}

ASSET_TIER_ORDER = {
    "franchise_anchor": 5,
    "core_star": 4,
    "premium_starter": 3,
    "starter_value": 2,
    "rotation_value": 1,
    "depth_development": 0,
}

V3_ASSET_TIER_ORDER = {
    "franchise_caliber": 6,
    "star_caliber": 5,
    "premium_young_asset": 4,
    "high_end_starter": 3,
    "starter_rotation": 2,
    "rotation_depth": 1,
    "development_depth": 0,
}

AUDIT_PREMIUM_PLAYER_NAMES = {
    "Amen Thompson",
    "Alex Sarr",
    "Ausar Thompson",
    "Matas Buzelis",
    "Tre Johnson",
    "Cade Cunningham",
    "Scottie Barnes",
}

QUALITY_THRESHOLDS = {
    "routine_adjusted_value_gap_max": 6.0,
    "minor_adjusted_value_gap_max": 10.0,
    "blockbuster_adjusted_value_gap_max": 8.0,
    "minimum_team_fit": 48.0,
    "minimum_realism_percentile": 55.0,
    "minimum_expected_retention": 0.82,
    "minimum_downside_retention": 0.68,
}

SCREENING_SCORE_WEIGHTS = {
    "package_quality_prior": 0.25,
    "team_fit": 0.25,
    "asset_retention": 0.20,
    "expected_contribution_retention": 0.15,
    "downside_contribution_retention": 0.15,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without reading project files.",
    )
    return parser.parse_args()


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def split_player_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [
            normalize_player_id(item)
            for item in value
            if normalize_player_id(item)
        ]
    text = normalize_player_id(value)
    if not text:
        return []
    return [
        normalize_player_id(part)
        for part in re.split(r"\s*[|;,]\s*", text)
        if normalize_player_id(part)
    ]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def numeric_series(
    frame: pd.DataFrame,
    column: str,
    fill_value: float = 0.0,
) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(fill_value, index=frame.index, dtype=float)
    return (
        pd.to_numeric(frame[column], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(fill_value)
        .astype(float)
    )


def percentile_rank(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    filled = numeric.fillna(numeric.median())
    return filled.rank(method="average", pct=True) * 100.0


def coalesce_numeric(
    frame: pd.DataFrame,
    candidates: Iterable[str],
    default: float = np.nan,
) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for column in candidates:
        if column not in frame.columns:
            continue
        candidate = pd.to_numeric(frame[column], errors="coerce")
        result = result.where(result.notna(), candidate)
    return result.fillna(default)


def first_existing(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def front_office_asset_tier(row: pd.Series) -> str:
    team_rank = int(row["team_front_office_value_rank"])
    value = float(row["front_office_value_score"])
    expected = float(row["expected_contribution_percentile"])
    roster_value = float(row["roster_value_percentile"])

    if (
        team_rank == 1
        and value >= 90.0
        and expected >= 87.0
        and roster_value >= 82.0
    ):
        return "franchise_anchor"
    if team_rank <= 2 and value >= 82.0 and expected >= 76.0:
        return "core_star"
    if value >= 72.0 and expected >= 60.0:
        return "premium_starter"
    if value >= 55.0:
        return "starter_value"
    if value >= 35.0:
        return "rotation_value"
    return "depth_development"


def calibrate_player_market(players: pd.DataFrame) -> pd.DataFrame:
    output = players.copy()
    required = [
        "player_id",
        "player_name",
        "current_team_2026_27",
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
    ]
    missing = [column for column in required if column not in output.columns]
    if missing:
        raise ValueError(f"Player market is missing required columns: {missing}")

    output["player_id_key"] = output["player_id"].map(normalize_player_id)

    for component in FRONT_OFFICE_VALUE_WEIGHTS:
        output[component] = numeric_series(output, component, 50.0).clip(0.0, 100.0)

    output["front_office_value_score"] = 0.0
    for component, weight in FRONT_OFFICE_VALUE_WEIGHTS.items():
        output["front_office_value_score"] += weight * output[component]

    output["front_office_value_percentile"] = percentile_rank(
        output["front_office_value_score"]
    )
    output["team_front_office_value_rank"] = (
        output.groupby("current_team_2026_27")["front_office_value_score"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    output["front_office_asset_tier"] = output.apply(
        front_office_asset_tier,
        axis=1,
    )
    output["front_office_asset_tier_order"] = (
        output["front_office_asset_tier"]
        .map(ASSET_TIER_ORDER)
        .astype(int)
    )
    output["protected_core_flag"] = output["front_office_asset_tier"].isin(
        ["franchise_anchor", "core_star"]
    )
    output["franchise_anchor_flag"] = output["front_office_asset_tier"].eq(
        "franchise_anchor"
    )
    return output


def load_player_market() -> tuple[pd.DataFrame, str, pd.DataFrame]:
    """Load V3 protection data and apply a transparent reviewed override ledger."""
    if not PLAYER_MARKET_V3_PATH.exists():
        raise FileNotFoundError(
            "The V3 protected-player market is required but was not found:\n"
            f"{PLAYER_MARKET_V3_PATH}\n\n"
            "Run src\\calibrate_trade_realism_layer_v3.py first. "
            "Do not fall back to the older V1/V2 protection logic for mixed-package recommendations."
        )
    if not PROTECTION_OVERRIDE_PATH.exists():
        raise FileNotFoundError(
            "The reviewed protection-override ledger is required but was not found:\n"
            f"{PROTECTION_OVERRIDE_PATH}\n\n"
            "Copy player_protection_overrides_2026_27_v1.csv into data\\processed."
        )

    players = pd.read_parquet(PLAYER_MARKET_V3_PATH).copy()
    required = {
        "player_id",
        "player_name",
        "current_team_2026_27",
        "market_value_percentile_v2",
        "recommendation_asset_class_v3",
        "recommendation_asset_class_order_v3",
        "protected_player_flag_v3",
        "protected_player_reason_v3",
        "on_court_caliber_score",
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
    }
    missing = sorted(required.difference(players.columns))
    if missing:
        raise ValueError(
            "The V3 player market is missing required fields:\n"
            + "\n".join(missing)
        )

    override_columns = {
        "player_name",
        "current_team_2026_27",
        "override_protected_flag",
        "override_asset_class",
        "override_reason",
        "review_basis",
        "evidence_as_of_date",
        "active",
    }
    overrides = pd.read_csv(PROTECTION_OVERRIDE_PATH, dtype=str).fillna("")
    missing_override_columns = sorted(override_columns.difference(overrides.columns))
    if missing_override_columns:
        raise ValueError(
            "The protection-override ledger is missing required fields:\n"
            + "\n".join(missing_override_columns)
        )

    overrides["active_bool"] = (
        overrides["active"].astype(str).str.strip().str.lower()
        .isin(["true", "1", "yes", "y"])
    )
    overrides["override_protected_bool"] = (
        overrides["override_protected_flag"].astype(str).str.strip().str.lower()
        .isin(["true", "1", "yes", "y"])
    )
    active_overrides = overrides.loc[overrides["active_bool"]].copy()

    if active_overrides.empty:
        raise ValueError("The protection-override ledger has no active rows.")
    if active_overrides.duplicated(
        ["player_name", "current_team_2026_27"], keep=False
    ).any():
        duplicates = active_overrides.loc[
            active_overrides.duplicated(
                ["player_name", "current_team_2026_27"], keep=False
            ),
            ["player_name", "current_team_2026_27"],
        ]
        raise ValueError(
            "Duplicate active protection overrides were found:\n"
            + duplicates.to_string(index=False)
        )
    invalid_classes = sorted(
        set(active_overrides["override_asset_class"])
        .difference(V3_ASSET_TIER_ORDER)
    )
    if invalid_classes:
        raise ValueError(
            "Unknown override asset classes: " + ", ".join(invalid_classes)
        )
    if not active_overrides["override_protected_bool"].all():
        raise ValueError(
            "V1 supports protective overrides only; every active row must set "
            "override_protected_flag=True."
        )

    players["model_recommendation_asset_class_v3"] = players[
        "recommendation_asset_class_v3"
    ]
    players["model_recommendation_asset_class_order_v3"] = players[
        "recommendation_asset_class_order_v3"
    ]
    players["model_protected_player_flag_v3"] = bool_series(
        players, "protected_player_flag_v3"
    )
    players["model_protected_player_reason_v3"] = players[
        "protected_player_reason_v3"
    ].astype(str)

    merge_columns = [
        "player_name",
        "current_team_2026_27",
        "override_protected_bool",
        "override_asset_class",
        "override_reason",
        "review_basis",
        "evidence_as_of_date",
    ]
    players = players.merge(
        active_overrides[merge_columns],
        on=["player_name", "current_team_2026_27"],
        how="left",
        validate="one_to_one",
    )
    players["protection_override_applied"] = (
        players["override_protected_bool"].fillna(False).astype(bool)
    )

    unmatched_overrides = active_overrides.merge(
        players[["player_name", "current_team_2026_27"]].drop_duplicates(),
        on=["player_name", "current_team_2026_27"],
        how="left",
        indicator=True,
    )
    unmatched_overrides = unmatched_overrides.loc[
        unmatched_overrides["_merge"] != "both"
    ]
    if not unmatched_overrides.empty:
        raise ValueError(
            "Protection overrides did not match the V3 player market:\n"
            + unmatched_overrides[
                ["player_name", "current_team_2026_27"]
            ].to_string(index=False)
        )

    mask = players["protection_override_applied"]
    players.loc[mask, "recommendation_asset_class_v3"] = players.loc[
        mask, "override_asset_class"
    ]
    players.loc[mask, "recommendation_asset_class_order_v3"] = (
        players.loc[mask, "override_asset_class"]
        .map(V3_ASSET_TIER_ORDER)
        .astype(int)
    )
    players.loc[mask, "protected_player_flag_v3"] = True
    players.loc[mask, "protected_player_reason_v3"] = players.loc[
        mask, "override_reason"
    ]

    players["player_id_key"] = players["player_id"].map(normalize_player_id)
    players["front_office_value_score"] = numeric_series(
        players, "market_value_percentile_v2", 0.0
    ).clip(0.0, 100.0)
    players["front_office_asset_tier"] = players[
        "recommendation_asset_class_v3"
    ].astype(str)
    players["front_office_asset_tier_order"] = (
        players["recommendation_asset_class_v3"]
        .map(V3_ASSET_TIER_ORDER)
        .fillna(players["recommendation_asset_class_order_v3"])
        .fillna(0)
        .astype(int)
    )
    players["protected_core_flag"] = bool_series(
        players, "protected_player_flag_v3"
    )
    players["franchise_anchor_flag"] = players[
        "recommendation_asset_class_v3"
    ].eq("franchise_caliber")

    return (
        players,
        "existing_v3_protected_market_plus_reviewed_override_v1",
        active_overrides,
    )


def build_player_lookup(players: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        normalize_player_id(row["player_id"]): row
        for row in players.to_dict(orient="records")
    }


def aggregate_players(
    ids: list[str],
    player_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = [player_lookup[player_id] for player_id in ids if player_id in player_lookup]
    unmatched = [player_id for player_id in ids if player_id not in player_lookup]
    return {
        "player_count": len(ids),
        "matched_player_count": len(rows),
        "unmatched_player_ids": "|".join(unmatched),
        "front_office_value": sum(
            safe_float(row.get("front_office_value_score")) for row in rows
        ),
        "expected_contribution": sum(
            safe_float(row.get("projected_expected_contribution")) for row in rows
        ),
        "downside_contribution": sum(
            safe_float(row.get("survival_weighted_active_downside_score"))
            for row in rows
        ),
        "protected_core_count": sum(
            bool(row.get("protected_core_flag")) for row in rows
        ),
        "franchise_anchor_count": sum(
            bool(row.get("franchise_anchor_flag")) for row in rows
        ),
        "protected_core_names": " | ".join(
            str(row.get("player_name", ""))
            for row in rows
            if bool(row.get("protected_core_flag"))
        ),
        "protected_core_reasons": " | ".join(
            str(row.get("protected_player_reason_v3", ""))
            for row in rows
            if bool(row.get("protected_core_flag"))
        ),
        "asset_classes": " | ".join(
            str(row.get("recommendation_asset_class_v3", ""))
            for row in rows
        ),
        "max_asset_tier_order": max(
            [int(row.get("front_office_asset_tier_order", 0)) for row in rows],
            default=0,
        ),
    }


def ratio(incoming: float, outgoing: float) -> float:
    if outgoing <= 1e-12:
        return 1.0 if incoming >= 0 else 0.0
    return incoming / outgoing


def capped_ratio_score(value: float) -> float:
    return float(np.clip(value * 100.0, 0.0, 120.0))


def repair_value_aliases(frame: pd.DataFrame, branch: str) -> pd.DataFrame:
    output = frame.copy()

    if branch == "one_for_one":
        side_a_candidates = [
            "side_a_player_value_score",
            "player_a_surplus_value_score",
        ]
        side_b_candidates = [
            "side_b_player_value_score",
            "player_b_surplus_value_score",
        ]
    else:
        side_a_candidates = [
            "side_a_player_value_score",
            "side_one_player_value_score",
            "one_side_surplus_value_score",
        ]
        side_b_candidates = [
            "side_b_player_value_score",
            "side_two_player_value_score",
        ]

    output["quality_side_a_player_value_score"] = coalesce_numeric(
        output, side_a_candidates
    )
    output["quality_side_b_player_value_score"] = coalesce_numeric(
        output, side_b_candidates
    )

    if branch == "two_for_one":
        two_sum = (
            coalesce_numeric(
                output,
                [
                    "two_side_player_1_surplus_value_score",
                    "two_side_player_1_player_value_score",
                ],
                default=0.0,
            )
            + coalesce_numeric(
                output,
                [
                    "two_side_player_2_surplus_value_score",
                    "two_side_player_2_player_value_score",
                ],
                default=0.0,
            )
        )
        output["quality_side_b_player_value_score"] = (
            output["quality_side_b_player_value_score"]
            .where(output["quality_side_b_player_value_score"].notna(), two_sum)
        )

    return output


def package_fit_fields(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()

    minimum_fit_column = first_existing(
        output,
        [
            "minimum_team_trade_fit_score",
            "minimum_team_fit_score",
            "base_fit_signal",
        ],
    )
    team_a_fit_column = first_existing(
        output,
        [
            "team_a_trade_fit_score",
            "team_sending_one_trade_fit_score",
            "team_a_fit_score",
        ],
    )
    team_b_fit_column = first_existing(
        output,
        [
            "team_b_trade_fit_score",
            "team_sending_two_trade_fit_score",
            "team_b_fit_score",
        ],
    )

    output["quality_minimum_team_fit_score"] = (
        numeric_series(output, minimum_fit_column, 0.0)
        if minimum_fit_column
        else 0.0
    )
    output["quality_team_a_fit_score"] = (
        numeric_series(output, team_a_fit_column, np.nan)
        if team_a_fit_column
        else output["quality_minimum_team_fit_score"]
    )
    output["quality_team_b_fit_score"] = (
        numeric_series(output, team_b_fit_column, np.nan)
        if team_b_fit_column
        else output["quality_minimum_team_fit_score"]
    )
    output["quality_team_a_fit_score"] = output["quality_team_a_fit_score"].fillna(
        output["quality_minimum_team_fit_score"]
    )
    output["quality_team_b_fit_score"] = output["quality_team_b_fit_score"].fillna(
        output["quality_minimum_team_fit_score"]
    )

    realism_eligible_column = first_existing(
        output,
        ["realism_review_eligible", "recommendation_eligible"],
    )
    if realism_eligible_column:
        output["quality_realism_pass"] = (
            output[realism_eligible_column]
            .fillna(False)
            .astype(bool)
        )
    else:
        output["quality_realism_pass"] = (
            numeric_series(output, "realism_signal_percentile", 0.0)
            >= QUALITY_THRESHOLDS["minimum_realism_percentile"]
        )

    return output


def classify_package(row: pd.Series) -> tuple[str, str]:
    protected_a = int(row["quality_side_a_protected_core_count"])
    protected_b = int(row["quality_side_b_protected_core_count"])
    protected_total = protected_a + protected_b

    expected_pass = bool(
        row["quality_team_a_expected_retention_ratio"]
        >= QUALITY_THRESHOLDS["minimum_expected_retention"]
        and row["quality_team_b_expected_retention_ratio"]
        >= QUALITY_THRESHOLDS["minimum_expected_retention"]
    )
    downside_pass = bool(
        row["quality_team_a_downside_retention_ratio"]
        >= QUALITY_THRESHOLDS["minimum_downside_retention"]
        and row["quality_team_b_downside_retention_ratio"]
        >= QUALITY_THRESHOLDS["minimum_downside_retention"]
    )
    fit_pass = bool(
        row["quality_minimum_team_fit_score"]
        >= QUALITY_THRESHOLDS["minimum_team_fit"]
    )
    realism_pass = bool(row["quality_realism_pass"])
    evidence_complete = bool(row["quality_player_market_evidence_complete"])
    value_gap = safe_float(row["adjusted_absolute_value_gap"], default=999.0)

    if not evidence_complete:
        return (
            "strategy_specific_manual_review",
            "player_market_lookup_incomplete",
        )

    if protected_total == 0:
        if (
            fit_pass
            and realism_pass
            and expected_pass
            and downside_pass
            and value_gap <= QUALITY_THRESHOLDS["routine_adjusted_value_gap_max"]
        ):
            return (
                "routine_recommendation_review",
                "non_core_balanced_fit_realism_retention_pass",
            )
        if (
            fit_pass
            and realism_pass
            and expected_pass
            and downside_pass
            and value_gap <= QUALITY_THRESHOLDS["minor_adjusted_value_gap_max"]
        ):
            return (
                "routine_plus_minor_assets_review",
                "non_core_minor_asset_gap_fit_realism_retention_pass",
            )
        if not expected_pass or not downside_pass:
            return (
                "strategy_specific_manual_review",
                "contribution_retention_requires_team_direction",
            )
        return (
            "filtered_quality_gate",
            "routine_fit_realism_or_value_gap_failed",
        )

    if protected_a > 0 and protected_b > 0:
        if (
            fit_pass
            and realism_pass
            and expected_pass
            and downside_pass
            and value_gap
            <= QUALITY_THRESHOLDS["blockbuster_adjusted_value_gap_max"]
        ):
            return (
                "premium_blockbuster_concept",
                "protected_core_both_sides_strong_fit_retention",
            )
        return (
            "strategy_specific_manual_review",
            "protected_core_blockbuster_conditions_not_met",
        )

    return (
        "strategy_specific_manual_review",
        "one_sided_protected_core_exchange_requires_team_strategy",
    )


def evaluate_frame(
    frame: pd.DataFrame,
    branch: str,
    player_lookup: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    output = repair_value_aliases(frame, branch)
    output = package_fit_fields(output)
    output["quality_source_branch"] = branch

    records: list[dict[str, Any]] = []
    for row in output.to_dict(orient="records"):
        ids_a = split_player_ids(row.get("side_a_player_ids"))
        ids_b = split_player_ids(row.get("side_b_player_ids"))
        profile_a = aggregate_players(ids_a, player_lookup)
        profile_b = aggregate_players(ids_b, player_lookup)

        pick_value = safe_float(row.get("attached_pick_value_score"))
        pick_side = str(row.get("attached_pick_side", "")).upper()
        side_a_pick_value = pick_value if pick_side == "A" else 0.0
        side_b_pick_value = pick_value if pick_side == "B" else 0.0

        # The compact V10 release does not expose transparent side-value aliases
        # for every two-for-one row. Prefer an existing package value when present,
        # but fail over to the calibrated aggregate player-market value rather than
        # silently treating the side as zero value.
        package_player_value_a = safe_float(
            row.get("quality_side_a_player_value_score"),
            default=float("nan"),
        )
        package_player_value_b = safe_float(
            row.get("quality_side_b_player_value_score"),
            default=float("nan"),
        )
        if (
            not math.isfinite(package_player_value_a)
            or package_player_value_a <= 0.0
        ):
            package_player_value_a = float(profile_a["front_office_value"])
        if (
            not math.isfinite(package_player_value_b)
            or package_player_value_b <= 0.0
        ):
            package_player_value_b = float(profile_b["front_office_value"])

        side_a_asset_value = package_player_value_a + side_a_pick_value
        side_b_asset_value = package_player_value_b + side_b_pick_value

        values = {
            **row,
            "quality_side_a_player_value_score": package_player_value_a,
            "quality_side_b_player_value_score": package_player_value_b,
            "quality_side_a_player_value_source": (
                "existing_package_value"
                if (
                    math.isfinite(safe_float(
                        row.get("quality_side_a_player_value_score"),
                        default=float("nan"),
                    ))
                    and safe_float(
                        row.get("quality_side_a_player_value_score"),
                        default=0.0,
                    ) > 0.0
                )
                else "calibrated_player_market_fallback"
            ),
            "quality_side_b_player_value_source": (
                "existing_package_value"
                if (
                    math.isfinite(safe_float(
                        row.get("quality_side_b_player_value_score"),
                        default=float("nan"),
                    ))
                    and safe_float(
                        row.get("quality_side_b_player_value_score"),
                        default=0.0,
                    ) > 0.0
                )
                else "calibrated_player_market_fallback"
            ),
            "quality_side_a_player_market_value": profile_a["front_office_value"],
            "quality_side_b_player_market_value": profile_b["front_office_value"],
            "quality_side_a_expected_contribution": profile_a["expected_contribution"],
            "quality_side_b_expected_contribution": profile_b["expected_contribution"],
            "quality_side_a_downside_contribution": profile_a["downside_contribution"],
            "quality_side_b_downside_contribution": profile_b["downside_contribution"],
            "quality_side_a_protected_core_count": profile_a["protected_core_count"],
            "quality_side_b_protected_core_count": profile_b["protected_core_count"],
            "quality_side_a_franchise_anchor_count": profile_a["franchise_anchor_count"],
            "quality_side_b_franchise_anchor_count": profile_b["franchise_anchor_count"],
            "quality_side_a_protected_core_names": profile_a["protected_core_names"],
            "quality_side_b_protected_core_names": profile_b["protected_core_names"],
            "quality_side_a_protected_core_reasons": profile_a["protected_core_reasons"],
            "quality_side_b_protected_core_reasons": profile_b["protected_core_reasons"],
            "quality_side_a_asset_classes_v3": profile_a["asset_classes"],
            "quality_side_b_asset_classes_v3": profile_b["asset_classes"],
            "quality_side_a_unmatched_player_ids": profile_a["unmatched_player_ids"],
            "quality_side_b_unmatched_player_ids": profile_b["unmatched_player_ids"],
            "quality_player_market_evidence_complete": (
                profile_a["matched_player_count"] == profile_a["player_count"]
                and profile_b["matched_player_count"] == profile_b["player_count"]
            ),
            "quality_side_a_total_asset_value_score": side_a_asset_value,
            "quality_side_b_total_asset_value_score": side_b_asset_value,
            "quality_team_a_asset_retention_ratio": ratio(
                side_b_asset_value, side_a_asset_value
            ),
            "quality_team_b_asset_retention_ratio": ratio(
                side_a_asset_value, side_b_asset_value
            ),
            "quality_team_a_expected_retention_ratio": ratio(
                profile_b["expected_contribution"],
                profile_a["expected_contribution"],
            ),
            "quality_team_b_expected_retention_ratio": ratio(
                profile_a["expected_contribution"],
                profile_b["expected_contribution"],
            ),
            "quality_team_a_downside_retention_ratio": ratio(
                profile_b["downside_contribution"],
                profile_a["downside_contribution"],
            ),
            "quality_team_b_downside_retention_ratio": ratio(
                profile_a["downside_contribution"],
                profile_b["downside_contribution"],
            ),
        }
        records.append(values)

    evaluated = pd.DataFrame(records)
    classes = evaluated.apply(classify_package, axis=1, result_type="expand")
    classes.columns = ["quality_gate_class", "quality_gate_reason"]
    evaluated = pd.concat([evaluated, classes], axis=1)

    evaluated["quality_gate_release"] = RELEASE_NAME
    evaluated["quality_gate_version"] = SCRIPT_VERSION
    evaluated["quality_gate_final_legality_preserved"] = (
        evaluated["optimizer_package_final_legal"].astype(bool)
    )
    evaluated["quality_gate_team_strategy_released"] = False
    return evaluated


def team_perspective_rows(evaluated: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for row in evaluated.to_dict(orient="records"):
        for side in ("A", "B"):
            other = "B" if side == "A" else "A"
            side_lower = side.lower()
            other_lower = other.lower()
            team = row[f"team_{side_lower}"]

            fit_score = safe_float(
                row[f"quality_team_{side_lower}_fit_score"]
            )
            package_prior = safe_float(
                row.get("optimizer_final_legal_rank_score_v1")
            )
            asset_retention = safe_float(
                row[f"quality_team_{side_lower}_asset_retention_ratio"]
            )
            expected_retention = safe_float(
                row[f"quality_team_{side_lower}_expected_retention_ratio"]
            )
            downside_retention = safe_float(
                row[f"quality_team_{side_lower}_downside_retention_ratio"]
            )

            screening_score = (
                SCREENING_SCORE_WEIGHTS["package_quality_prior"] * package_prior
                + SCREENING_SCORE_WEIGHTS["team_fit"] * fit_score
                + SCREENING_SCORE_WEIGHTS["asset_retention"]
                * capped_ratio_score(asset_retention)
                + SCREENING_SCORE_WEIGHTS["expected_contribution_retention"]
                * capped_ratio_score(expected_retention)
                + SCREENING_SCORE_WEIGHTS["downside_contribution_retention"]
                * capped_ratio_score(downside_retention)
            )

            attaches_pick = str(row.get("attached_pick_side", "")).upper() == side
            receives_pick = str(row.get("attached_pick_side", "")).upper() == other

            rows.append(
                {
                    "recommendation_team": team,
                    "recommendation_team_side": side,
                    "optimizer_candidate_id": row["optimizer_candidate_id"],
                    "optimizer_branch": row["optimizer_branch"],
                    "quality_gate_class": row["quality_gate_class"],
                    "quality_gate_reason": row["quality_gate_reason"],
                    "outgoing_players": row[f"side_{side_lower}_player_names"],
                    "incoming_players": row[f"side_{other_lower}_player_names"],
                    "team_attaches_pick": attaches_pick,
                    "team_receives_pick": receives_pick,
                    "right_display_name": row.get("right_display_name", ""),
                    "outgoing_total_asset_value_score": row[
                        f"quality_side_{side_lower}_total_asset_value_score"
                    ],
                    "incoming_total_asset_value_score": row[
                        f"quality_side_{other_lower}_total_asset_value_score"
                    ],
                    "team_asset_retention_ratio": asset_retention,
                    "team_expected_contribution_retention_ratio": expected_retention,
                    "team_downside_contribution_retention_ratio": downside_retention,
                    "team_trade_fit_score": fit_score,
                    "package_quality_prior_score": package_prior,
                    "team_perspective_quality_screening_score": screening_score,
                    "outgoing_protected_core_count": row[
                        f"quality_side_{side_lower}_protected_core_count"
                    ],
                    "outgoing_protected_core_names": row[
                        f"quality_side_{side_lower}_protected_core_names"
                    ],
                    "incoming_protected_core_count": row[
                        f"quality_side_{other_lower}_protected_core_count"
                    ],
                    "incoming_protected_core_names": row[
                        f"quality_side_{other_lower}_protected_core_names"
                    ],
                    "optimizer_trade_display": row.get(
                        "optimizer_trade_display", ""
                    ),
                    "full_cba_status": row.get("full_cba_status", ""),
                    "optimizer_package_final_legal": bool(
                        row.get("optimizer_package_final_legal", False)
                    ),
                    "team_strategy_score_released": False,
                    "screening_scope_note": (
                        "Quality-review score only. Team direction, timeline, ownership "
                        "preference, and public trade availability are not included."
                    ),
                }
            )

    output = pd.DataFrame(rows)
    output = output.sort_values(
        [
            "recommendation_team",
            "quality_gate_class",
            "team_perspective_quality_screening_score",
            "optimizer_candidate_id",
        ],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)

    eligible = output["quality_gate_class"].isin(
        [
            "routine_recommendation_review",
            "routine_plus_minor_assets_review",
        ]
    )
    output["quality_review_rank_for_team"] = np.nan
    output.loc[eligible, "quality_review_rank_for_team"] = (
        output.loc[eligible]
        .groupby("recommendation_team")[
            "team_perspective_quality_screening_score"
        ]
        .rank(method="first", ascending=False)
    )
    return output


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    series = frame[column]
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    return (
        series.astype(str).str.strip().str.lower()
        .isin(["true", "1", "yes", "y"])
    )


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def run_self_test() -> int:
    market = pd.DataFrame(
        [
            {
                "player_id": 1,
                "player_name": "Anchor A",
                "current_team_2026_27": "AAA",
                "market_value_percentile": 99,
                "expected_contribution_percentile": 95,
                "downside_contribution_percentile": 90,
                "roster_value_percentile": 90,
                "age_market_score": 90,
                "contract_control_score": 80,
                "projected_expected_contribution": 20,
                "survival_weighted_active_downside_score": 15,
            },
            {
                "player_id": 2,
                "player_name": "Role B",
                "current_team_2026_27": "BBB",
                "market_value_percentile": 50,
                "expected_contribution_percentile": 50,
                "downside_contribution_percentile": 50,
                "roster_value_percentile": 50,
                "age_market_score": 50,
                "contract_control_score": 50,
                "projected_expected_contribution": 12,
                "survival_weighted_active_downside_score": 9,
            },
            {
                "player_id": 3,
                "player_name": "Role C",
                "current_team_2026_27": "AAA",
                "market_value_percentile": 45,
                "expected_contribution_percentile": 45,
                "downside_contribution_percentile": 45,
                "roster_value_percentile": 45,
                "age_market_score": 45,
                "contract_control_score": 45,
                "projected_expected_contribution": 10,
                "survival_weighted_active_downside_score": 8,
            },
            {
                "player_id": 4,
                "player_name": "Role D",
                "current_team_2026_27": "BBB",
                "market_value_percentile": 46,
                "expected_contribution_percentile": 46,
                "downside_contribution_percentile": 46,
                "roster_value_percentile": 46,
                "age_market_score": 46,
                "contract_control_score": 46,
                "projected_expected_contribution": 10,
                "survival_weighted_active_downside_score": 8,
            },
        ]
    )
    calibrated = calibrate_player_market(market)
    lookup = build_player_lookup(calibrated)

    tests = {
        "player_ids_split": split_player_ids("1|2") == ["1", "2"],
        "anchor_is_protected": bool(
            calibrated.loc[
                calibrated["player_name"] == "Anchor A",
                "protected_core_flag",
            ].iloc[0]
        ),
        "ratio_identity": abs(ratio(10.0, 10.0) - 1.0) < 1e-12,
        "screening_weights_sum_to_one": abs(
            sum(SCREENING_SCORE_WEIGHTS.values()) - 1.0
        ) < 1e-12,
        "aggregate_players_matches": aggregate_players(
            ["1", "3"], lookup
        )["matched_player_count"] == 2,
        "one_sided_anchor_is_manual": classify_package(
            pd.Series(
                {
                    "quality_side_a_protected_core_count": 1,
                    "quality_side_b_protected_core_count": 0,
                    "quality_team_a_expected_retention_ratio": 1.0,
                    "quality_team_b_expected_retention_ratio": 1.0,
                    "quality_team_a_downside_retention_ratio": 1.0,
                    "quality_team_b_downside_retention_ratio": 1.0,
                    "quality_minimum_team_fit_score": 70.0,
                    "quality_realism_pass": True,
                    "quality_player_market_evidence_complete": True,
                    "adjusted_absolute_value_gap": 2.0,
                }
            )
        )[0] == "strategy_specific_manual_review",
        "routine_trade_passes": classify_package(
            pd.Series(
                {
                    "quality_side_a_protected_core_count": 0,
                    "quality_side_b_protected_core_count": 0,
                    "quality_team_a_expected_retention_ratio": 1.0,
                    "quality_team_b_expected_retention_ratio": 1.0,
                    "quality_team_a_downside_retention_ratio": 1.0,
                    "quality_team_b_downside_retention_ratio": 1.0,
                    "quality_minimum_team_fit_score": 70.0,
                    "quality_realism_pass": True,
                    "quality_player_market_evidence_complete": True,
                    "adjusted_absolute_value_gap": 2.0,
                }
            )
        )[0] == "routine_recommendation_review",
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("MIXED PLAYER-AND-PICK RECOMMENDATION QUALITY GATE")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading calibrated player market and protection data")
    players, player_market_source, protection_overrides = load_player_market()
    player_lookup = build_player_lookup(players)
    print(
        f"  Player market: {len(players):,} rows | source={player_market_source}"
    )

    print("[2/7] Loading final-legal deduplicated package parquets")
    frames: dict[str, pd.DataFrame] = {}
    for branch, path in INPUT_FILES.items():
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_parquet(path)
        if len(frame) != EXPECTED_INPUT_ROWS[branch]:
            raise ValueError(
                f"{path.name}: expected {EXPECTED_INPUT_ROWS[branch]:,} rows, "
                f"found {len(frame):,}"
            )
        legal = bool_series(frame, "optimizer_package_final_legal")
        if not legal.all():
            raise ValueError(f"{path.name} contains non-legal rows.")
        frames[branch] = frame
        print(f"  {branch}: {len(frame):,} rows | {len(frame.columns):,} columns")

    print("[3/7] Repairing player-value aliases and joining market profiles")
    evaluated_frames = {
        branch: evaluate_frame(frame, branch, player_lookup)
        for branch, frame in frames.items()
    }
    evaluated = pd.concat(
        [evaluated_frames["one_for_one"], evaluated_frames["two_for_one"]],
        ignore_index=True,
        sort=False,
    )

    print("[4/7] Building team-perspective quality-review rows")
    team_rows = team_perspective_rows(evaluated)

    print("[5/7] Validating classifications")
    class_counts = evaluated["quality_gate_class"].value_counts().to_dict()
    routine_classes = {
        "routine_recommendation_review",
        "routine_plus_minor_assets_review",
    }
    routine_rows_for_validation = evaluated.loc[
        evaluated["quality_gate_class"].isin(routine_classes)
    ].copy()
    protected_routine_rows = routine_rows_for_validation.loc[
        (
            routine_rows_for_validation["quality_side_a_protected_core_count"] > 0
        )
        | (
            routine_rows_for_validation["quality_side_b_protected_core_count"] > 0
        )
    ]
    market_premium_rows = players.loc[
        players["player_name"].isin(AUDIT_PREMIUM_PLAYER_NAMES)
    ].copy()
    premium_players_unprotected = market_premium_rows.loc[
        ~bool_series(market_premium_rows, "protected_player_flag_v3")
    ]
    model_premium_false_negatives = market_premium_rows.loc[
        ~bool_series(market_premium_rows, "model_protected_player_flag_v3")
    ]
    applied_override_names = sorted(
        players.loc[
            bool_series(players, "protection_override_applied"),
            "player_name",
        ].astype(str).tolist()
    )

    validation_rows = [
        {
            "check_name": "expected_total_rows",
            "passed": len(evaluated) == EXPECTED_TOTAL_ROWS,
            "observed": len(evaluated),
            "expected": EXPECTED_TOTAL_ROWS,
        },
        {
            "check_name": "candidate_ids_unique",
            "passed": evaluated["optimizer_candidate_id"].is_unique,
            "observed": evaluated["optimizer_candidate_id"].nunique(),
            "expected": EXPECTED_TOTAL_ROWS,
        },
        {
            "check_name": "final_legality_preserved",
            "passed": bool_series(
                evaluated, "optimizer_package_final_legal"
            ).all(),
            "observed": int(
                bool_series(evaluated, "optimizer_package_final_legal").sum()
            ),
            "expected": EXPECTED_TOTAL_ROWS,
        },
        {
            "check_name": "classification_complete",
            "passed": evaluated["quality_gate_class"].notna().all(),
            "observed": int(evaluated["quality_gate_class"].notna().sum()),
            "expected": EXPECTED_TOTAL_ROWS,
        },
        {
            "check_name": "two_team_perspective_rows_per_package",
            "passed": len(team_rows) == EXPECTED_TOTAL_ROWS * 2,
            "observed": len(team_rows),
            "expected": EXPECTED_TOTAL_ROWS * 2,
        },
        {
            "check_name": "player_value_aliases_complete_or_market_fallback",
            "passed": (
                evaluated["quality_side_a_player_value_score"].notna().all()
                and evaluated["quality_side_b_player_value_score"].notna().all()
            ),
            "observed": {
                "side_a_non_null": int(
                    evaluated["quality_side_a_player_value_score"].notna().sum()
                ),
                "side_b_non_null": int(
                    evaluated["quality_side_b_player_value_score"].notna().sum()
                ),
            },
            "expected": {
                "side_a_non_null": EXPECTED_TOTAL_ROWS,
                "side_b_non_null": EXPECTED_TOTAL_ROWS,
            },
        },
        {
            "check_name": "v3_player_market_plus_reviewed_override_required",
            "passed": (
                player_market_source
                == "existing_v3_protected_market_plus_reviewed_override_v1"
            ),
            "observed": player_market_source,
            "expected": "existing_v3_protected_market_plus_reviewed_override_v1",
        },
        {
            "check_name": "reviewed_protection_overrides_applied_exactly",
            "passed": applied_override_names == sorted(
                protection_overrides["player_name"].astype(str).tolist()
            ),
            "observed": applied_override_names,
            "expected": sorted(
                protection_overrides["player_name"].astype(str).tolist()
            ),
        },
        {
            "check_name": "all_player_market_lookups_complete",
            "passed": bool(
                evaluated["quality_player_market_evidence_complete"].all()
            ),
            "observed": int(
                evaluated["quality_player_market_evidence_complete"].sum()
            ),
            "expected": EXPECTED_TOTAL_ROWS,
        },
        {
            "check_name": "positive_player_asset_values",
            "passed": bool(
                (evaluated["quality_side_a_player_value_score"] > 0).all()
                and (evaluated["quality_side_b_player_value_score"] > 0).all()
            ),
            "observed": {
                "side_a_positive": int(
                    (evaluated["quality_side_a_player_value_score"] > 0).sum()
                ),
                "side_b_positive": int(
                    (evaluated["quality_side_b_player_value_score"] > 0).sum()
                ),
            },
            "expected": {
                "side_a_positive": EXPECTED_TOTAL_ROWS,
                "side_b_positive": EXPECTED_TOTAL_ROWS,
            },
        },
        {
            "check_name": "no_protected_players_in_routine_classes",
            "passed": protected_routine_rows.empty,
            "observed": int(len(protected_routine_rows)),
            "expected": 0,
        },
        {
            "check_name": "audit_premium_players_protected_after_reviewed_overlay",
            "passed": premium_players_unprotected.empty,
            "observed": sorted(
                premium_players_unprotected["player_name"].astype(str).tolist()
            ),
            "expected": [],
        },
        {
            "check_name": "v3_false_negatives_documented_by_override",
            "passed": sorted(
                model_premium_false_negatives["player_name"].astype(str).tolist()
            ) == applied_override_names,
            "observed": sorted(
                model_premium_false_negatives["player_name"].astype(str).tolist()
            ),
            "expected": applied_override_names,
        },
        {
            "check_name": "strategy_score_not_released",
            "passed": not team_rows["team_strategy_score_released"].any(),
            "observed": int(team_rows["team_strategy_score_released"].sum()),
            "expected": 0,
        },
    ]
    release_valid = all(bool(row["passed"]) for row in validation_rows)

    print("[6/7] Writing classifications and audit artifacts")
    evaluated.to_parquet(OUTPUT_PARQUET, index=False)

    output_columns = [
        "optimizer_candidate_id",
        "optimizer_branch",
        "team_a",
        "team_b",
        "side_a_player_names",
        "side_b_player_names",
        "right_display_name",
        "attached_pick_team",
        "quality_gate_class",
        "quality_gate_reason",
        "quality_side_a_protected_core_names",
        "quality_side_b_protected_core_names",
        "quality_side_a_asset_classes_v3",
        "quality_side_b_asset_classes_v3",
        "quality_side_a_protected_core_reasons",
        "quality_side_b_protected_core_reasons",
        "quality_team_a_expected_retention_ratio",
        "quality_team_b_expected_retention_ratio",
        "quality_team_a_downside_retention_ratio",
        "quality_team_b_downside_retention_ratio",
        "quality_minimum_team_fit_score",
        "realism_signal_percentile",
        "adjusted_absolute_value_gap",
        "optimizer_final_legal_rank_score_v1",
        "optimizer_trade_display",
        "full_cba_status",
        "optimizer_package_final_legal",
    ]
    output_columns = [column for column in output_columns if column in evaluated.columns]

    class_outputs = {
        "routine_recommendation_review": ROUTINE_OUTPUT,
        "routine_plus_minor_assets_review": MINOR_OUTPUT,
        "premium_blockbuster_concept": BLOCKBUSTER_OUTPUT,
        "strategy_specific_manual_review": STRATEGY_MANUAL_OUTPUT,
        "filtered_quality_gate": FILTERED_OUTPUT,
    }
    for class_name, path in class_outputs.items():
        write_csv(
            evaluated.loc[
                evaluated["quality_gate_class"] == class_name,
                output_columns,
            ].sort_values(
                ["optimizer_final_legal_rank_score_v1", "optimizer_candidate_id"],
                ascending=[False, True],
            ),
            path,
        )

    write_csv(team_rows, TEAM_PERSPECTIVE_OUTPUT)
    top_team_rows = (
        team_rows.loc[
            team_rows["quality_review_rank_for_team"].notna()
            & (team_rows["quality_review_rank_for_team"] <= 50)
        ]
        .sort_values(
            ["recommendation_team", "quality_review_rank_for_team"]
        )
        .reset_index(drop=True)
    )
    write_csv(top_team_rows, TEAM_TOP_OUTPUT)

    summary_rows = [
        {"metric": "input_legal_rows", "count": len(evaluated)},
        {"metric": "team_perspective_rows", "count": len(team_rows)},
        {"metric": "team_top_review_rows", "count": len(top_team_rows)},
        *[
            {"metric": f"class::{name}", "count": count}
            for name, count in sorted(class_counts.items())
        ],
    ]
    pd.DataFrame(summary_rows).to_csv(SUMMARY_OUTPUT, index=False)
    pd.DataFrame(validation_rows).to_csv(VALIDATION_OUTPUT, index=False)

    metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "player_market_source": player_market_source,
        "protection_override_ledger": str(PROTECTION_OVERRIDE_PATH),
        "protection_override_rows": int(len(protection_overrides)),
        "protection_override_players": sorted(
            protection_overrides["player_name"].astype(str).tolist()
        ),
        "v3_model_false_negative_players": sorted(
            model_premium_false_negatives["player_name"].astype(str).tolist()
        ),
        "input_rows": {
            branch: len(frame) for branch, frame in frames.items()
        },
        "total_input_rows": len(evaluated),
        "class_counts": class_counts,
        "team_perspective_rows": len(team_rows),
        "team_top_review_rows": len(top_team_rows),
        "quality_thresholds": QUALITY_THRESHOLDS,
        "screening_score_weights": SCREENING_SCORE_WEIGHTS,
        "team_strategy_score_released": False,
        "optimizer_package_final_legal_preserved": True,
        "scope_note": (
            "This V3 quality gate requires the project V3 protected-player market plus a versioned reviewed protection-override ledger and separates routine recommendations, blockbuster "
            "concepts, strategy-specific manual cases, and filtered packages. "
            "It does not infer team direction, public trade availability, ownership "
            "preference, or a final team-strategy recommendation score."
        ),
        "outputs": {
            "classified_parquet": str(OUTPUT_PARQUET),
            "routine": str(ROUTINE_OUTPUT),
            "minor_assets": str(MINOR_OUTPUT),
            "blockbusters": str(BLOCKBUSTER_OUTPUT),
            "strategy_manual": str(STRATEGY_MANUAL_OUTPUT),
            "filtered": str(FILTERED_OUTPUT),
            "team_perspective": str(TEAM_PERSPECTIVE_OUTPUT),
            "team_top_review": str(TEAM_TOP_OUTPUT),
            "summary": str(SUMMARY_OUTPUT),
            "validation": str(VALIDATION_OUTPUT),
        },
    }
    METADATA_OUTPUT.write_text(
        json.dumps(json_safe(metadata), indent=2),
        encoding="utf-8",
    )

    print("[7/7] Complete")
    print(
        f"Validation: {sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Release valid: {release_valid}")
    print("Classification counts:")
    for name, count in sorted(class_counts.items()):
        print(f"  {name}: {count:,}")
    print(f"Team-perspective rows: {len(team_rows):,}")
    print(f"Top quality-review rows: {len(top_team_rows):,}")
    print("Team strategy score released: False")

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())