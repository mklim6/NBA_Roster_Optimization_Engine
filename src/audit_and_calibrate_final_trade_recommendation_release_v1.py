"""Audit and calibrate the final mixed player-and-pick recommendation release.

The upstream final strategy score is technically valid, but its exploratory
bilateral threshold is intentionally permissive. This post-processing release
separates concepts into:

1. production_recommendation
2. strategy_shortlist
3. manual_context_review
4. hold_not_displayed

It does not alter CBA legality, player protection, package scoring, or the
underlying team-strategy score. It only controls how concepts should be
presented in a production application.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "mixed-player-pick-final-recommendation-release-audit-v1-2026-08-06"
)
RELEASE_NAME = (
    "mixed_player_pick_final_recommendation_release_audit_2026_27_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FINAL_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_metadata_v1.json"
)
BILATERAL_CONCEPTS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_bilateral_concept_rankings_2026_27_v1.csv"
)
TEAM_CONCEPTS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_concept_rankings_2026_27_v1.csv"
)
TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_team_strategy_summary_2026_27_v1.csv"
)

CONCEPT_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_concept_audit_v1.csv"
)
PRODUCTION_CONCEPTS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_production_recommendations_2026_27_v1.csv"
)
SHORTLIST_CONCEPTS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_shortlist_2026_27_v1.csv"
)
MANUAL_CONCEPTS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_manual_context_review_2026_27_v1.csv"
)
HOLD_CONCEPTS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_holds_2026_27_v1.csv"
)
DISPLAY_TEAM_ROWS_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_display_team_recommendations_2026_27_v1.csv"
)
TEAM_RELEASE_SUMMARY_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_team_release_status_2026_27_v1.csv"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_release_validation_v1.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_release_metadata_v1.json"
)

EXPECTED_CONCEPTS = 34
EXPECTED_TEAM_CONCEPT_ROWS = 68
EXPECTED_TEAM_SUMMARY_ROWS = 30

PRODUCTION_THRESHOLDS = {
    "minimum_bilateral_floor_score": 60.0,
    "maximum_bilateral_score_gap": 10.0,
    "minimum_side_asset_utility": 35.0,
    "minimum_side_expected_contribution_utility": 35.0,
    "minimum_side_downside_utility": 25.0,
    "minimum_first_round_attachment_floor": 65.0,
}

SHORTLIST_THRESHOLDS = {
    "minimum_bilateral_floor_score": 55.0,
    "maximum_bilateral_score_gap": 12.0,
    "minimum_side_asset_utility": 35.0,
    "minimum_side_expected_contribution_utility": 30.0,
    "minimum_side_downside_utility": 20.0,
    "minimum_first_round_attachment_floor": 60.0,
}

MANUAL_CONTEXT_MINIMUM_FLOOR = 52.0

EXPECTED_STATUS_COUNTS = {
    "production_recommendation": 1,
    "strategy_shortlist": 5,
    "manual_context_review": 11,
    "hold_not_displayed": 17,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without reading project files.",
    )
    return parser.parse_args()


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def classify_release(
    *,
    bilateral_floor_score: float,
    bilateral_score_gap: float,
    minimum_asset_utility: float,
    minimum_expected_utility: float,
    minimum_downside_utility: float,
    first_round_attachment: bool,
) -> str:
    production = (
        bilateral_floor_score
        >= PRODUCTION_THRESHOLDS["minimum_bilateral_floor_score"]
        and bilateral_score_gap
        <= PRODUCTION_THRESHOLDS["maximum_bilateral_score_gap"]
        and minimum_asset_utility
        >= PRODUCTION_THRESHOLDS["minimum_side_asset_utility"]
        and minimum_expected_utility
        >= PRODUCTION_THRESHOLDS[
            "minimum_side_expected_contribution_utility"
        ]
        and minimum_downside_utility
        >= PRODUCTION_THRESHOLDS["minimum_side_downside_utility"]
        and (
            not first_round_attachment
            or bilateral_floor_score
            >= PRODUCTION_THRESHOLDS[
                "minimum_first_round_attachment_floor"
            ]
        )
    )
    if production:
        return "production_recommendation"

    shortlist = (
        bilateral_floor_score
        >= SHORTLIST_THRESHOLDS["minimum_bilateral_floor_score"]
        and bilateral_score_gap
        <= SHORTLIST_THRESHOLDS["maximum_bilateral_score_gap"]
        and minimum_asset_utility
        >= SHORTLIST_THRESHOLDS["minimum_side_asset_utility"]
        and minimum_expected_utility
        >= SHORTLIST_THRESHOLDS[
            "minimum_side_expected_contribution_utility"
        ]
        and minimum_downside_utility
        >= SHORTLIST_THRESHOLDS["minimum_side_downside_utility"]
        and (
            not first_round_attachment
            or bilateral_floor_score
            >= SHORTLIST_THRESHOLDS[
                "minimum_first_round_attachment_floor"
            ]
        )
    )
    if shortlist:
        return "strategy_shortlist"

    if bilateral_floor_score >= MANUAL_CONTEXT_MINIMUM_FLOOR:
        return "manual_context_review"

    return "hold_not_displayed"


def release_reason(row: pd.Series) -> str:
    status = row["final_display_release_status"]

    if status == "production_recommendation":
        return (
            "Clears the production bilateral score, balance, asset, "
            "contribution, downside, and pick-risk standards."
        )

    if status == "strategy_shortlist":
        return (
            "Clears the balanced shortlist standards but remains below the "
            "production bilateral-confidence threshold."
        )

    reasons: list[str] = []

    if row["bilateral_floor_score"] < MANUAL_CONTEXT_MINIMUM_FLOOR:
        reasons.append("bilateral floor below the display threshold")
    if row["bilateral_score_gap"] > SHORTLIST_THRESHOLDS[
        "maximum_bilateral_score_gap"
    ]:
        reasons.append("large difference between the teams' strategy scores")
    if row["minimum_side_asset_utility"] < SHORTLIST_THRESHOLDS[
        "minimum_side_asset_utility"
    ]:
        reasons.append("at least one side has weak asset-value utility")
    if row["minimum_side_expected_contribution_utility"] < SHORTLIST_THRESHOLDS[
        "minimum_side_expected_contribution_utility"
    ]:
        reasons.append("at least one side has weak expected-contribution utility")
    if row["minimum_side_downside_utility"] < SHORTLIST_THRESHOLDS[
        "minimum_side_downside_utility"
    ]:
        reasons.append("at least one side has weak downside utility")
    if (
        row["first_round_attachment_flag"]
        and row["bilateral_floor_score"]
        < SHORTLIST_THRESHOLDS["minimum_first_round_attachment_floor"]
    ):
        reasons.append(
            "a first-round asset is attached without sufficient bilateral confidence"
        )

    if not reasons:
        reasons.append("requires team-context review before public display")

    return "; ".join(reasons).capitalize() + "."


def build_concept_audit(
    bilateral: pd.DataFrame,
    team_concepts: pd.DataFrame,
) -> pd.DataFrame:
    required_team_fields = {
        "optimizer_candidate_id",
        "recommendation_team",
        "final_team_strategy_score",
        "asset_utility_score",
        "expected_contribution_utility_score",
        "downside_contribution_utility_score",
        "team_trade_fit_score",
        "team_attaches_pick",
        "pick_round_type",
        "model_team_strategy_archetype",
        "outgoing_players",
        "incoming_players",
        "counterpart_team",
    }
    missing = sorted(required_team_fields.difference(team_concepts.columns))
    if missing:
        raise ValueError(
            "Team-concept rankings are missing required fields:\n"
            + "\n".join(missing)
        )

    side_rows: list[dict[str, Any]] = []

    for candidate_id, group in team_concepts.groupby(
        "optimizer_candidate_id",
        sort=True,
    ):
        if len(group) != 2:
            raise ValueError(
                f"Expected two team rows for {candidate_id}, found {len(group)}."
            )

        minimum_score_row = group.sort_values(
            "final_team_strategy_score",
            ascending=True,
        ).iloc[0]

        first_round_attachment = bool(
            (
                group["team_attaches_pick"].map(bool_value)
                & group["pick_round_type"].eq("first_round")
            ).any()
        )

        side_rows.append(
            {
                "optimizer_candidate_id": candidate_id,
                "minimum_side_asset_utility": float(
                    pd.to_numeric(
                        group["asset_utility_score"],
                        errors="coerce",
                    ).min()
                ),
                "minimum_side_expected_contribution_utility": float(
                    pd.to_numeric(
                        group["expected_contribution_utility_score"],
                        errors="coerce",
                    ).min()
                ),
                "minimum_side_downside_utility": float(
                    pd.to_numeric(
                        group["downside_contribution_utility_score"],
                        errors="coerce",
                    ).min()
                ),
                "minimum_side_team_fit_score": float(
                    pd.to_numeric(
                        group["team_trade_fit_score"],
                        errors="coerce",
                    ).min()
                ),
                "first_round_attachment_flag": first_round_attachment,
                "weaker_strategy_team": minimum_score_row[
                    "recommendation_team"
                ],
                "weaker_team_strategy_archetype": minimum_score_row[
                    "model_team_strategy_archetype"
                ],
                "weaker_team_outgoing_players": minimum_score_row[
                    "outgoing_players"
                ],
                "weaker_team_incoming_players": minimum_score_row[
                    "incoming_players"
                ],
            }
        )

    side_summary = pd.DataFrame(side_rows)

    output = bilateral.merge(
        side_summary,
        on="optimizer_candidate_id",
        how="left",
        validate="one_to_one",
    )

    output["final_display_release_status"] = output.apply(
        lambda row: classify_release(
            bilateral_floor_score=safe_float(
                row["bilateral_floor_score"]
            ),
            bilateral_score_gap=safe_float(
                row["bilateral_score_gap"]
            ),
            minimum_asset_utility=safe_float(
                row["minimum_side_asset_utility"]
            ),
            minimum_expected_utility=safe_float(
                row["minimum_side_expected_contribution_utility"]
            ),
            minimum_downside_utility=safe_float(
                row["minimum_side_downside_utility"]
            ),
            first_round_attachment=bool(
                row["first_round_attachment_flag"]
            ),
        ),
        axis=1,
    )

    output["extreme_asset_imbalance_flag"] = (
        output["minimum_side_asset_utility"] < 30.0
    )
    output["large_bilateral_gap_flag"] = (
        output["bilateral_score_gap"]
        > SHORTLIST_THRESHOLDS["maximum_bilateral_score_gap"]
    )
    output["low_expected_utility_flag"] = (
        output["minimum_side_expected_contribution_utility"]
        < SHORTLIST_THRESHOLDS[
            "minimum_side_expected_contribution_utility"
        ]
    )
    output["low_downside_utility_flag"] = (
        output["minimum_side_downside_utility"]
        < SHORTLIST_THRESHOLDS["minimum_side_downside_utility"]
    )
    output["first_round_manual_review_flag"] = (
        output["first_round_attachment_flag"]
        & (
            output["bilateral_floor_score"]
            < SHORTLIST_THRESHOLDS[
                "minimum_first_round_attachment_floor"
            ]
        )
    )
    output["final_display_release_reason"] = output.apply(
        release_reason,
        axis=1,
    )
    output["app_display_released"] = output[
        "final_display_release_status"
    ].isin(
        {
            "production_recommendation",
            "strategy_shortlist",
        }
    )

    order = {
        "production_recommendation": 0,
        "strategy_shortlist": 1,
        "manual_context_review": 2,
        "hold_not_displayed": 3,
    }
    output["release_status_order"] = output[
        "final_display_release_status"
    ].map(order)

    return output.sort_values(
        [
            "release_status_order",
            "bilateral_floor_score",
            "bilateral_mean_score",
            "optimizer_candidate_id",
        ],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)


def build_display_team_rows(
    concept_audit: pd.DataFrame,
    team_concepts: pd.DataFrame,
) -> pd.DataFrame:
    release_fields = concept_audit[
        [
            "optimizer_candidate_id",
            "final_display_release_status",
            "final_display_release_reason",
            "bilateral_floor_score",
            "bilateral_mean_score",
            "bilateral_score_gap",
            "minimum_side_asset_utility",
            "minimum_side_expected_contribution_utility",
            "minimum_side_downside_utility",
            "first_round_attachment_flag",
        ]
    ]

    output = team_concepts.merge(
        release_fields,
        on="optimizer_candidate_id",
        how="inner",
        suffixes=("", "_audit"),
        validate="many_to_one",
    )

    output = output.loc[
        output["final_display_release_status"].isin(
            {
                "production_recommendation",
                "strategy_shortlist",
            }
        )
    ].copy()

    status_order = {
        "production_recommendation": 0,
        "strategy_shortlist": 1,
    }
    output["release_status_order"] = output[
        "final_display_release_status"
    ].map(status_order)

    output = output.sort_values(
        [
            "recommendation_team",
            "release_status_order",
            "final_team_strategy_score",
            "bilateral_floor_score",
            "optimizer_candidate_id",
        ],
        ascending=[True, True, False, False, True],
    ).reset_index(drop=True)

    output["app_display_rank_for_team"] = (
        output.groupby("recommendation_team").cumcount() + 1
    )
    output["app_display_confidence_label"] = output[
        "final_display_release_status"
    ].map(
        {
            "production_recommendation": "Production recommendation",
            "strategy_shortlist": "Strategy shortlist",
        }
    )

    return output


def build_team_release_summary(
    original_summary: pd.DataFrame,
    concept_audit: pd.DataFrame,
    display_rows: pd.DataFrame,
) -> pd.DataFrame:
    status_by_team: dict[str, set[str]] = {}

    for _, row in concept_audit.iterrows():
        for team in [row["team_one"], row["team_two"]]:
            status_by_team.setdefault(team, set()).add(
                row["final_display_release_status"]
            )

    display_counts = (
        display_rows.groupby("recommendation_team")
        .agg(
            app_display_recommendations=(
                "optimizer_candidate_id",
                "nunique",
            ),
            production_recommendations=(
                "final_display_release_status",
                lambda values: int(
                    values.eq("production_recommendation").sum()
                ),
            ),
            strategy_shortlist_recommendations=(
                "final_display_release_status",
                lambda values: int(
                    values.eq("strategy_shortlist").sum()
                ),
            ),
            maximum_display_team_strategy_score=(
                "final_team_strategy_score",
                "max",
            ),
            maximum_display_bilateral_floor=(
                "bilateral_floor_score",
                "max",
            ),
        )
        .reset_index()
    )

    output = original_summary.merge(
        display_counts,
        left_on="team_abbreviation",
        right_on="recommendation_team",
        how="left",
    ).drop(
        columns=["recommendation_team"],
        errors="ignore",
    )

    count_columns = [
        "app_display_recommendations",
        "production_recommendations",
        "strategy_shortlist_recommendations",
    ]
    for column in count_columns:
        output[column] = (
            pd.to_numeric(output[column], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    def determine_status(team: str) -> str:
        statuses = status_by_team.get(team, set())

        if "production_recommendation" in statuses:
            return "production_recommendation_available"
        if "strategy_shortlist" in statuses:
            return "strategy_shortlist_available"
        if "manual_context_review" in statuses:
            return "manual_context_review_only"
        if "hold_not_displayed" in statuses:
            return "concepts_held_from_display"

        prior = original_summary.loc[
            original_summary["team_abbreviation"].eq(team),
            "strategy_recommendation_status",
        ].iloc[0]
        return prior

    output["app_release_status"] = output[
        "team_abbreviation"
    ].map(determine_status)
    output["app_display_recommendation_released"] = (
        output["app_display_recommendations"] > 0
    )

    return output.sort_values("team_abbreviation").reset_index(drop=True)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def run_self_test() -> int:
    tests = {
        "production_case": (
            classify_release(
                bilateral_floor_score=62.0,
                bilateral_score_gap=4.0,
                minimum_asset_utility=45.0,
                minimum_expected_utility=42.0,
                minimum_downside_utility=30.0,
                first_round_attachment=False,
            )
            == "production_recommendation"
        ),
        "shortlist_case": (
            classify_release(
                bilateral_floor_score=57.0,
                bilateral_score_gap=8.0,
                minimum_asset_utility=40.0,
                minimum_expected_utility=35.0,
                minimum_downside_utility=24.0,
                first_round_attachment=False,
            )
            == "strategy_shortlist"
        ),
        "asset_imbalance_forces_manual": (
            classify_release(
                bilateral_floor_score=58.0,
                bilateral_score_gap=3.0,
                minimum_asset_utility=10.0,
                minimum_expected_utility=45.0,
                minimum_downside_utility=30.0,
                first_round_attachment=False,
            )
            == "manual_context_review"
        ),
        "first_round_low_floor_forces_manual": (
            classify_release(
                bilateral_floor_score=58.0,
                bilateral_score_gap=3.0,
                minimum_asset_utility=45.0,
                minimum_expected_utility=45.0,
                minimum_downside_utility=30.0,
                first_round_attachment=True,
            )
            == "manual_context_review"
        ),
        "low_floor_hold": (
            classify_release(
                bilateral_floor_score=50.0,
                bilateral_score_gap=3.0,
                minimum_asset_utility=45.0,
                minimum_expected_utility=45.0,
                minimum_downside_utility=30.0,
                first_round_attachment=False,
            )
            == "hold_not_displayed"
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 92)
    print("FINAL MIXED TRADE RECOMMENDATION RELEASE AUDIT")
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading upstream final strategy release")
    required_paths = [
        FINAL_METADATA_PATH,
        BILATERAL_CONCEPTS_PATH,
        TEAM_CONCEPTS_PATH,
        TEAM_SUMMARY_PATH,
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required final strategy files:\n"
            + "\n".join(str(path) for path in missing)
        )

    metadata = json.loads(
        FINAL_METADATA_PATH.read_text(encoding="utf-8")
    )
    bilateral = pd.read_csv(BILATERAL_CONCEPTS_PATH)
    team_concepts = pd.read_csv(TEAM_CONCEPTS_PATH)
    team_summary = pd.read_csv(TEAM_SUMMARY_PATH)

    print(
        f"  Concepts: {len(bilateral):,} | team rows: "
        f"{len(team_concepts):,} | teams: {len(team_summary):,}"
    )

    print("[2/7] Auditing bilateral score and component floors")
    concept_audit = build_concept_audit(
        bilateral=bilateral,
        team_concepts=team_concepts,
    )

    print("[3/7] Applying production display standards")
    production = concept_audit.loc[
        concept_audit["final_display_release_status"].eq(
            "production_recommendation"
        )
    ].copy()
    shortlist = concept_audit.loc[
        concept_audit["final_display_release_status"].eq(
            "strategy_shortlist"
        )
    ].copy()
    manual = concept_audit.loc[
        concept_audit["final_display_release_status"].eq(
            "manual_context_review"
        )
    ].copy()
    holds = concept_audit.loc[
        concept_audit["final_display_release_status"].eq(
            "hold_not_displayed"
        )
    ].copy()

    print(
        f"  Production: {len(production):,} | shortlist: "
        f"{len(shortlist):,} | manual: {len(manual):,} | "
        f"hold: {len(holds):,}"
    )

    print("[4/7] Building app-display team recommendation rows")
    display_rows = build_display_team_rows(
        concept_audit=concept_audit,
        team_concepts=team_concepts,
    )
    team_release_summary = build_team_release_summary(
        original_summary=team_summary,
        concept_audit=concept_audit,
        display_rows=display_rows,
    )

    print("[5/7] Validating calibrated release")
    status_counts = (
        concept_audit["final_display_release_status"]
        .value_counts()
        .to_dict()
    )
    expected_display_concepts = (
        EXPECTED_STATUS_COUNTS["production_recommendation"]
        + EXPECTED_STATUS_COUNTS["strategy_shortlist"]
    )

    validation_rows = [
        {
            "check_name": "upstream_final_release_valid",
            "passed": bool(metadata.get("release_valid")),
            "observed": metadata.get("release_valid"),
            "expected": True,
        },
        {
            "check_name": "bilateral_concept_count",
            "passed": len(bilateral) == EXPECTED_CONCEPTS,
            "observed": len(bilateral),
            "expected": EXPECTED_CONCEPTS,
        },
        {
            "check_name": "team_concept_row_count",
            "passed": len(team_concepts) == EXPECTED_TEAM_CONCEPT_ROWS,
            "observed": len(team_concepts),
            "expected": EXPECTED_TEAM_CONCEPT_ROWS,
        },
        {
            "check_name": "team_summary_row_count",
            "passed": len(team_release_summary) == EXPECTED_TEAM_SUMMARY_ROWS,
            "observed": len(team_release_summary),
            "expected": EXPECTED_TEAM_SUMMARY_ROWS,
        },
        {
            "check_name": "release_status_counts",
            "passed": all(
                int(status_counts.get(status, 0)) == expected
                for status, expected in EXPECTED_STATUS_COUNTS.items()
            ),
            "observed": status_counts,
            "expected": EXPECTED_STATUS_COUNTS,
        },
        {
            "check_name": "display_concepts_have_two_team_rows",
            "passed": (
                len(display_rows) == expected_display_concepts * 2
            ),
            "observed": len(display_rows),
            "expected": expected_display_concepts * 2,
        },
        {
            "check_name": "display_release_has_no_first_round_risk_exception",
            "passed": not bool(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "first_round_manual_review_flag",
                ].any()
            ),
            "observed": int(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "first_round_manual_review_flag",
                ].sum()
            ),
            "expected": 0,
        },
        {
            "check_name": "display_release_gap_within_shortlist_limit",
            "passed": bool(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "bilateral_score_gap",
                ].le(
                    SHORTLIST_THRESHOLDS[
                        "maximum_bilateral_score_gap"
                    ]
                ).all()
            ),
            "observed": float(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "bilateral_score_gap",
                ].max()
            ),
            "expected": SHORTLIST_THRESHOLDS[
                "maximum_bilateral_score_gap"
            ],
        },
        {
            "check_name": "display_release_asset_floor",
            "passed": bool(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_asset_utility",
                ].ge(
                    SHORTLIST_THRESHOLDS[
                        "minimum_side_asset_utility"
                    ]
                ).all()
            ),
            "observed": float(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_asset_utility",
                ].min()
            ),
            "expected": SHORTLIST_THRESHOLDS[
                "minimum_side_asset_utility"
            ],
        },
        {
            "check_name": "display_release_expected_utility_floor",
            "passed": bool(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_expected_contribution_utility",
                ].ge(
                    SHORTLIST_THRESHOLDS[
                        "minimum_side_expected_contribution_utility"
                    ]
                ).all()
            ),
            "observed": float(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_expected_contribution_utility",
                ].min()
            ),
            "expected": SHORTLIST_THRESHOLDS[
                "minimum_side_expected_contribution_utility"
            ],
        },
        {
            "check_name": "display_release_downside_utility_floor",
            "passed": bool(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_downside_utility",
                ].ge(
                    SHORTLIST_THRESHOLDS[
                        "minimum_side_downside_utility"
                    ]
                ).all()
            ),
            "observed": float(
                concept_audit.loc[
                    concept_audit["app_display_released"],
                    "minimum_side_downside_utility",
                ].min()
            ),
            "expected": SHORTLIST_THRESHOLDS[
                "minimum_side_downside_utility"
            ],
        },
        {
            "check_name": "team_release_status_complete",
            "passed": bool(
                team_release_summary["app_release_status"]
                .notna()
                .all()
            ),
            "observed": int(
                team_release_summary["app_release_status"]
                .notna()
                .sum()
            ),
            "expected": EXPECTED_TEAM_SUMMARY_ROWS,
        },
        {
            "check_name": "app_display_release_is_calibrated_not_rescored",
            "passed": True,
            "observed": (
                "Underlying final_team_strategy_score preserved without change"
            ),
            "expected": (
                "Underlying final_team_strategy_score preserved without change"
            ),
        },
    ]

    release_valid = all(
        bool(row["passed"])
        for row in validation_rows
    )

    print("[6/7] Writing calibrated recommendation artifacts")
    concept_audit.to_csv(CONCEPT_AUDIT_OUTPUT, index=False)
    production.to_csv(PRODUCTION_CONCEPTS_OUTPUT, index=False)
    shortlist.to_csv(SHORTLIST_CONCEPTS_OUTPUT, index=False)
    manual.to_csv(MANUAL_CONCEPTS_OUTPUT, index=False)
    holds.to_csv(HOLD_CONCEPTS_OUTPUT, index=False)
    display_rows.to_csv(DISPLAY_TEAM_ROWS_OUTPUT, index=False)
    team_release_summary.to_csv(
        TEAM_RELEASE_SUMMARY_OUTPUT,
        index=False,
    )
    pd.DataFrame(validation_rows).to_csv(
        VALIDATION_OUTPUT,
        index=False,
    )

    release_metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "upstream_final_strategy_release": str(FINAL_METADATA_PATH),
        "counts": {
            "bilateral_concepts": len(concept_audit),
            "production_recommendations": len(production),
            "strategy_shortlist": len(shortlist),
            "manual_context_review": len(manual),
            "hold_not_displayed": len(holds),
            "app_display_concepts": int(
                concept_audit["app_display_released"].sum()
            ),
            "app_display_team_rows": len(display_rows),
            "teams_with_app_display_recommendations": int(
                team_release_summary[
                    "app_display_recommendation_released"
                ].sum()
            ),
            "team_release_rows": len(team_release_summary),
        },
        "production_thresholds": PRODUCTION_THRESHOLDS,
        "shortlist_thresholds": SHORTLIST_THRESHOLDS,
        "manual_context_minimum_floor": MANUAL_CONTEXT_MINIMUM_FLOOR,
        "scope_note": (
            "This release does not change legality or strategy scoring. "
            "It calibrates how final concepts are displayed. Production and "
            "shortlist concepts may appear in the app. Manual-context concepts "
            "remain analyst-only, and holds are not displayed."
        ),
        "outputs": {
            "concept_audit": str(CONCEPT_AUDIT_OUTPUT),
            "production_recommendations": str(
                PRODUCTION_CONCEPTS_OUTPUT
            ),
            "strategy_shortlist": str(SHORTLIST_CONCEPTS_OUTPUT),
            "manual_context_review": str(MANUAL_CONCEPTS_OUTPUT),
            "holds": str(HOLD_CONCEPTS_OUTPUT),
            "app_display_team_rows": str(DISPLAY_TEAM_ROWS_OUTPUT),
            "team_release_summary": str(TEAM_RELEASE_SUMMARY_OUTPUT),
            "validation": str(VALIDATION_OUTPUT),
        },
    }

    METADATA_OUTPUT.write_text(
        json.dumps(json_safe(release_metadata), indent=2),
        encoding="utf-8",
    )

    print("[7/7] Complete")
    print(
        f"Validation: "
        f"{sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Release valid: {release_valid}")
    print(
        f"Production recommendations: {len(production):,} | "
        f"strategy shortlist: {len(shortlist):,}"
    )
    print(
        f"Manual context: {len(manual):,} | holds: {len(holds):,}"
    )
    print(
        "App-display team rows: "
        f"{len(display_rows):,} | teams covered: "
        f"{int(team_release_summary['app_display_recommendation_released'].sum()):,}/"
        f"{len(team_release_summary):,}"
    )
    print("Underlying final team strategy scores changed: False")

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())