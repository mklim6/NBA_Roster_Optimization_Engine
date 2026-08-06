"""Build the app-facing mixed player-and-pick recommendation release.

This script consumes the calibrated final recommendation release and produces a
stable application data contract. It does not recompute legality, player
protection, package quality, or strategy scores.

App-facing concepts:
- production_recommendation -> "Model-backed recommendation"
- strategy_shortlist -> "Exploratory strategy shortlist"

Manual-context concepts and held concepts are excluded from app recommendation
cards, but all 30 teams receive an explicit release status and empty-state
message.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "mixed-player-pick-app-integration-release-v1-1-2026-08-06"
)
RELEASE_NAME = (
    "mixed_player_pick_app_integration_release_2026_27_v1_1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

CALIBRATED_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_release_metadata_v1.json"
)
CALIBRATED_VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_release_validation_v1.csv"
)
DISPLAY_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_display_team_recommendations_2026_27_v1.csv"
)
TEAM_RELEASE_STATUS_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_team_release_status_2026_27_v1.csv"
)
CONCEPT_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_final_recommendation_concept_audit_v1.csv"
)

APP_RECOMMENDATIONS_OUTPUT = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_recommendations_2026_27_v1.csv"
)
APP_CONCEPTS_OUTPUT = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_concepts_2026_27_v1.csv"
)
APP_TEAM_STATUS_OUTPUT = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_team_status_2026_27_v1.csv"
)
APP_BUNDLE_OUTPUT = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_release_2026_27_v1.json"
)
APP_METHODOLOGY_OUTPUT = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_methodology_2026_27_v1.json"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_integration_validation_v1.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_app_integration_metadata_v1.json"
)

EXPECTED_APP_CONCEPTS = 6
EXPECTED_APP_TEAM_ROWS = 12
EXPECTED_TEAMS_WITH_RECOMMENDATIONS = 10
EXPECTED_TEAM_ROWS = 30
EXPECTED_PRODUCTION_CONCEPTS = 1
EXPECTED_SHORTLIST_CONCEPTS = 5

DISPLAY_STATUS_LABELS = {
    "production_recommendation": "Model-backed recommendation",
    "strategy_shortlist": "Exploratory strategy shortlist",
}

DISPLAY_STATUS_DESCRIPTIONS = {
    "production_recommendation": (
        "Clears the stricter bilateral balance, utility, contribution, "
        "downside, and pick-risk standards."
    ),
    "strategy_shortlist": (
        "Passes the balanced shortlist screen but remains below the stricter "
        "production confidence threshold."
    ),
}

TEAM_STATUS_LABELS = {
    "production_recommendation_available": (
        "Model-backed recommendation available"
    ),
    "strategy_shortlist_available": "Strategy shortlist available",
    "manual_context_review_only": "Analyst review only",
    "concepts_held_from_display": "No display-ready concept",
    "no_strategy_ready_routine_concepts": "No strategy-ready concept",
    "no_deterministic_legal_pool_exposure": (
        "No deterministic-legal concept"
    ),
    "routine_concepts_below_bilateral_release_threshold": (
        "No concept cleared the bilateral threshold"
    ),
}

TEAM_EMPTY_STATE_MESSAGES = {
    "production_recommendation_available": (
        "A model-backed mixed player-and-pick concept is available."
    ),
    "strategy_shortlist_available": (
        "One or more exploratory strategy concepts are available. "
        "These require additional team-context review."
    ),
    "manual_context_review_only": (
        "Legal concepts exist, but each requires analyst review before "
        "being shown as a recommendation."
    ),
    "concepts_held_from_display": (
        "The model found legal concepts, but none cleared the calibrated "
        "display standards."
    ),
    "no_strategy_ready_routine_concepts": (
        "No routine mixed player-and-pick concept survived the protection, "
        "quality, and strategy-readiness gates."
    ),
    "no_deterministic_legal_pool_exposure": (
        "No deterministic-legal mixed player-and-pick package was available "
        "for this team in the modeled pool."
    ),
    "routine_concepts_below_bilateral_release_threshold": (
        "Routine concepts were identified, but none provided enough value "
        "to both teams to clear the display threshold."
    ),
}

ARCHETYPE_LABELS = {
    "win_now_contender": "Win-now contender",
    "competitive_builder": "Competitive builder",
    "development_rebuild": "Development rebuild",
    "ascending_retool": "Ascending retool",
    "flexible_retool": "Flexible retool",
}

TEAM_STRATEGY_PRIORITY_BY_ARCHETYPE = {
    "win_now_contender": (
        "Prioritize immediate rotation upgrades and consolidation; future "
        "picks may be attached only for clear present-value improvement."
    ),
    "competitive_builder": (
        "Balance present upgrades with contract control and avoid unnecessary "
        "first-round-pick expenditure."
    ),
    "development_rebuild": (
        "Prioritize young controlled players and incoming draft value; avoid "
        "veteran-only upgrades."
    ),
    "ascending_retool": (
        "Favor timeline-compatible players and preserve premium future assets."
    ),
    "flexible_retool": (
        "Favor balanced value, roster fit, and future flexibility without "
        "forcing a win-now or teardown objective."
    ),
}

PICK_ROUND_LABELS = {
    "first_round": "First-round asset",
    "second_round": "Second-round asset",
    "other_or_complex": "Complex draft right",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without project files.",
    )
    return parser.parse_args()


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def rounded_score(value: Any) -> float | None:
    score = safe_float(value)
    return None if not math.isfinite(score) else round(score, 1)


def compact_player_list(value: Any) -> str:
    players = [
        part.strip()
        for part in str(value).split("|")
        if part.strip()
    ]
    if not players:
        return ""
    if len(players) == 1:
        return players[0]
    if len(players) == 2:
        return f"{players[0]} and {players[1]}"
    return ", ".join(players[:-1]) + f", and {players[-1]}"


def pick_direction_phrase(row: pd.Series) -> str:
    pick_round = PICK_ROUND_LABELS.get(
        clean_text(row["pick_round_type"]),
        "Draft asset",
    ).lower()

    if bool_value(row["team_receives_pick"]):
        return f"Receives a {pick_round}."
    if bool_value(row["team_attaches_pick"]):
        return f"Attaches a {pick_round}."
    return "No draft asset changes hands from this team's perspective."


def build_team_headline(row: pd.Series) -> str:
    team = clean_text(row["recommendation_team"])
    incoming = compact_player_list(row["incoming_players"])
    counterpart = clean_text(row["counterpart_team"])

    headline = f"{team} receives {incoming} from {counterpart}"
    if bool_value(row["team_receives_pick"]):
        headline += " plus a draft asset"
    return headline


def build_team_subheadline(row: pd.Series) -> str:
    outgoing = compact_player_list(row["outgoing_players"])
    counterpart = clean_text(row["counterpart_team"])
    sentence = f"Sends {outgoing} to {counterpart}."
    return f"{sentence} {pick_direction_phrase(row)}"


def normalize_fit_summary(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+", " ", text)
    return text


def build_recommendations(display: pd.DataFrame) -> pd.DataFrame:
    output = display.copy()

    output["display_tier"] = output[
        "final_display_release_status"
    ].map(DISPLAY_STATUS_LABELS)
    output["display_tier_description"] = output[
        "final_display_release_status"
    ].map(DISPLAY_STATUS_DESCRIPTIONS)
    output["team_strategy_archetype_label"] = output[
        "model_team_strategy_archetype"
    ].map(ARCHETYPE_LABELS)
    output["team_headline"] = output.apply(
        build_team_headline,
        axis=1,
    )
    output["team_subheadline"] = output.apply(
        build_team_subheadline,
        axis=1,
    )
    output["team_fit_summary"] = output[
        "team_strategy_fit_summary"
    ].map(normalize_fit_summary)
    output["confidence_note"] = output[
        "final_display_release_reason"
    ].map(normalize_fit_summary)

    output["team_strategy_score_display"] = output[
        "final_team_strategy_score"
    ].map(rounded_score)
    output["counterpart_strategy_score_display"] = output[
        "counterpart_final_team_strategy_score"
    ].map(rounded_score)
    output["bilateral_floor_score_display"] = output[
        "bilateral_floor_score"
    ].map(rounded_score)
    output["bilateral_mean_score_display"] = output[
        "bilateral_mean_score"
    ].map(rounded_score)
    output["team_trade_fit_score_display"] = output[
        "team_trade_fit_score"
    ].map(rounded_score)
    output["asset_utility_score_display"] = output[
        "asset_utility_score"
    ].map(rounded_score)
    output["expected_utility_score_display"] = output[
        "expected_contribution_utility_score"
    ].map(rounded_score)
    output["downside_utility_score_display"] = output[
        "downside_contribution_utility_score"
    ].map(rounded_score)

    output["display_sort_tier"] = output[
        "final_display_release_status"
    ].map(
        {
            "production_recommendation": 0,
            "strategy_shortlist": 1,
        }
    )
    output["app_data_contract_version"] = "mixed_trade_app_v1"
    output["score_scope_label"] = (
        "Team-specific strategy score"
    )
    output["legality_label"] = (
        "Deterministic legal under modeled package checks"
    )
    output["availability_disclaimer"] = (
        "This is a model-generated concept, not evidence that either team "
        "or player is available."
    )

    selected_columns = [
        "app_data_contract_version",
        "recommendation_team",
        "app_display_rank_for_team",
        "display_sort_tier",
        "optimizer_candidate_id",
        "player_exchange_key",
        "display_tier",
        "display_tier_description",
        "team_headline",
        "team_subheadline",
        "outgoing_players",
        "incoming_players",
        "counterpart_team",
        "team_attaches_pick",
        "team_receives_pick",
        "right_display_name",
        "pick_round_type",
        "team_strategy_archetype_label",
        "model_team_strategy_archetype",
        "model_team_strategy_priority",
        "model_pick_preference",
        "top_need_1",
        "top_need_2",
        "top_need_3",
        "team_strategy_score_display",
        "counterpart_strategy_score_display",
        "bilateral_floor_score_display",
        "bilateral_mean_score_display",
        "team_trade_fit_score_display",
        "asset_utility_score_display",
        "expected_utility_score_display",
        "downside_utility_score_display",
        "team_fit_summary",
        "confidence_note",
        "optimizer_trade_display",
        "quality_gate_class",
        "full_cba_status",
        "optimizer_package_final_legal",
        "score_scope_label",
        "legality_label",
        "availability_disclaimer",
    ]

    missing = sorted(set(selected_columns).difference(output.columns))
    if missing:
        raise ValueError(
            "Display recommendations are missing app contract fields:\n"
            + "\n".join(missing)
        )

    return output[selected_columns].sort_values(
        [
            "recommendation_team",
            "display_sort_tier",
            "app_display_rank_for_team",
            "optimizer_candidate_id",
        ]
    ).reset_index(drop=True)


def build_concepts(
    concept_audit: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    app_candidate_ids = set(recommendations["optimizer_candidate_id"])
    concepts = concept_audit.loc[
        concept_audit["optimizer_candidate_id"].isin(app_candidate_ids)
    ].copy()

    concepts["display_tier"] = concepts[
        "final_display_release_status"
    ].map(DISPLAY_STATUS_LABELS)
    concepts["display_tier_description"] = concepts[
        "final_display_release_status"
    ].map(DISPLAY_STATUS_DESCRIPTIONS)
    concepts["bilateral_floor_score_display"] = concepts[
        "bilateral_floor_score"
    ].map(rounded_score)
    concepts["bilateral_mean_score_display"] = concepts[
        "bilateral_mean_score"
    ].map(rounded_score)
    concepts["bilateral_score_gap_display"] = concepts[
        "bilateral_score_gap"
    ].map(rounded_score)
    concepts["app_data_contract_version"] = "mixed_trade_app_v1"

    selected_columns = [
        "app_data_contract_version",
        "optimizer_candidate_id",
        "player_exchange_key",
        "optimizer_trade_display",
        "team_one",
        "team_one_strategy_score",
        "team_two",
        "team_two_strategy_score",
        "bilateral_floor_score_display",
        "bilateral_mean_score_display",
        "bilateral_score_gap_display",
        "display_tier",
        "display_tier_description",
        "final_display_release_reason",
        "quality_gate_class",
        "right_display_name",
        "attached_pick_team",
        "pick_round_type",
        "minimum_side_asset_utility",
        "minimum_side_expected_contribution_utility",
        "minimum_side_downside_utility",
        "first_round_attachment_flag",
    ]

    return concepts[selected_columns].sort_values(
        [
            "display_tier",
            "bilateral_floor_score_display",
            "optimizer_candidate_id",
        ],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def build_team_status(
    team_status: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    output = team_status.copy()
    output["app_status_label"] = output[
        "app_release_status"
    ].map(TEAM_STATUS_LABELS)
    output["empty_state_message"] = output[
        "app_release_status"
    ].map(TEAM_EMPTY_STATE_MESSAGES)
    output["team_strategy_archetype_label"] = output[
        "model_team_strategy_archetype"
    ].map(ARCHETYPE_LABELS)

    derived_priority = output[
        "model_team_strategy_archetype"
    ].map(TEAM_STRATEGY_PRIORITY_BY_ARCHETYPE)

    if "model_team_strategy_priority" not in output.columns:
        output["model_team_strategy_priority"] = derived_priority
    else:
        existing_priority = output[
            "model_team_strategy_priority"
        ].fillna("").astype(str).str.strip()
        output["model_team_strategy_priority"] = existing_priority.where(
            existing_priority.ne(""),
            derived_priority,
        )

    displayed_counts = (
        recommendations.groupby("recommendation_team")
        .agg(
            app_recommendation_rows=(
                "optimizer_candidate_id",
                "size",
            ),
            app_unique_concepts=(
                "optimizer_candidate_id",
                "nunique",
            ),
            app_production_rows=(
                "display_tier",
                lambda values: int(
                    values.eq("Model-backed recommendation").sum()
                ),
            ),
            app_shortlist_rows=(
                "display_tier",
                lambda values: int(
                    values.eq("Exploratory strategy shortlist").sum()
                ),
            ),
        )
        .reset_index()
    )

    output = output.merge(
        displayed_counts,
        left_on="team_abbreviation",
        right_on="recommendation_team",
        how="left",
        validate="one_to_one",
    ).drop(
        columns=["recommendation_team"],
        errors="ignore",
    )

    for column in [
        "app_recommendation_rows",
        "app_unique_concepts",
        "app_production_rows",
        "app_shortlist_rows",
    ]:
        output[column] = (
            pd.to_numeric(output[column], errors="coerce")
            .fillna(0)
            .astype(int)
        )

    output["app_has_recommendations"] = (
        output["app_recommendation_rows"] > 0
    )
    output["app_data_contract_version"] = "mixed_trade_app_v1"
    output["availability_disclaimer"] = (
        "Model-generated concepts do not imply real-world availability."
    )

    selected_columns = [
        "app_data_contract_version",
        "team_abbreviation",
        "app_status_label",
        "app_release_status",
        "empty_state_message",
        "app_has_recommendations",
        "app_recommendation_rows",
        "app_unique_concepts",
        "app_production_rows",
        "app_shortlist_rows",
        "team_strategy_archetype_label",
        "model_team_strategy_archetype",
        "model_team_strategy_priority",
        "model_pick_preference",
        "top_need_1",
        "top_need_2",
        "top_need_3",
        "strength_percentile_2026_27",
        "projected_wins_2026_27",
        "deterministic_legal_perspective_rows",
        "routine_package_variants",
        "unique_canonical_concepts",
        "availability_disclaimer",
    ]

    missing = sorted(set(selected_columns).difference(output.columns))
    if missing:
        raise ValueError(
            "Team status is missing app contract fields:\n"
            + "\n".join(missing)
        )

    return output[selected_columns].sort_values(
        "team_abbreviation"
    ).reset_index(drop=True)


def build_bundle(
    recommendations: pd.DataFrame,
    concepts: pd.DataFrame,
    team_status: pd.DataFrame,
) -> dict[str, Any]:
    recommendation_records = recommendations.where(
        pd.notna(recommendations),
        None,
    ).to_dict(orient="records")
    concept_records = concepts.where(
        pd.notna(concepts),
        None,
    ).to_dict(orient="records")
    team_records = team_status.where(
        pd.notna(team_status),
        None,
    ).to_dict(orient="records")

    recommendations_by_team: dict[str, list[dict[str, Any]]] = {}
    for record in recommendation_records:
        recommendations_by_team.setdefault(
            record["recommendation_team"],
            [],
        ).append(record)

    team_status_by_team = {
        record["team_abbreviation"]: record
        for record in team_records
    }

    return {
        "release_name": RELEASE_NAME,
        "data_contract_version": "mixed_trade_app_v1",
        "league_year": "2026-27",
        "recommendation_count": len(recommendations),
        "concept_count": len(concepts),
        "team_count": len(team_status),
        "teams_with_recommendations": int(
            team_status["app_has_recommendations"].sum()
        ),
        "recommendations_by_team": recommendations_by_team,
        "team_status_by_team": team_status_by_team,
        "concepts": concept_records,
    }


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
    row = pd.Series(
        {
            "recommendation_team": "AAA",
            "incoming_players": "Player One|Player Two",
            "counterpart_team": "BBB",
            "team_receives_pick": True,
            "team_attaches_pick": False,
            "pick_round_type": "second_round",
            "outgoing_players": "Player Three",
        }
    )

    tests = {
        "player_list_format": (
            compact_player_list("Player One|Player Two")
            == "Player One and Player Two"
        ),
        "headline_includes_team_and_incoming": (
            build_team_headline(row)
            == "AAA receives Player One and Player Two from BBB plus a draft asset"
        ),
        "subheadline_includes_pick_direction": (
            "Receives a second-round asset."
            in build_team_subheadline(row)
        ),
        "production_label_is_model_backed": (
            DISPLAY_STATUS_LABELS["production_recommendation"]
            == "Model-backed recommendation"
        ),
        "shortlist_label_is_exploratory": (
            DISPLAY_STATUS_LABELS["strategy_shortlist"]
            == "Exploratory strategy shortlist"
        ),
        "all_statuses_have_empty_state_messages": (
            set(TEAM_STATUS_LABELS)
            == set(TEAM_EMPTY_STATE_MESSAGES)
        ),
        "all_archetypes_have_priority_text": (
            set(ARCHETYPE_LABELS)
            == set(TEAM_STRATEGY_PRIORITY_BY_ARCHETYPE)
            and all(
                bool(value.strip())
                for value in TEAM_STRATEGY_PRIORITY_BY_ARCHETYPE.values()
            )
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 92)
    print("MIXED PLAYER-AND-PICK APP INTEGRATION RELEASE")
    print("=" * 92)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading calibrated recommendation release")
    required_paths = [
        CALIBRATED_METADATA_PATH,
        CALIBRATED_VALIDATION_PATH,
        DISPLAY_ROWS_PATH,
        TEAM_RELEASE_STATUS_PATH,
        CONCEPT_AUDIT_PATH,
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing calibrated release files:\n"
            + "\n".join(str(path) for path in missing)
        )

    calibrated_metadata = json.loads(
        CALIBRATED_METADATA_PATH.read_text(encoding="utf-8")
    )
    calibrated_validation = pd.read_csv(CALIBRATED_VALIDATION_PATH)
    display = pd.read_csv(DISPLAY_ROWS_PATH)
    team_release_status = pd.read_csv(TEAM_RELEASE_STATUS_PATH)
    concept_audit = pd.read_csv(CONCEPT_AUDIT_PATH)

    print(
        f"  Display rows: {len(display):,} | teams: "
        f"{len(team_release_status):,} | concepts audited: "
        f"{len(concept_audit):,}"
    )

    print("[2/7] Building stable recommendation data contract")
    recommendations = build_recommendations(display)

    print("[3/7] Building concept and 30-team status tables")
    concepts = build_concepts(
        concept_audit=concept_audit,
        recommendations=recommendations,
    )
    team_status = build_team_status(
        team_status=team_release_status,
        recommendations=recommendations,
    )

    print("[4/7] Building application JSON bundle")
    bundle = build_bundle(
        recommendations=recommendations,
        concepts=concepts,
        team_status=team_status,
    )

    print("[5/7] Validating end-to-end app release")
    display_status_counts = (
        display["final_display_release_status"]
        .value_counts()
        .to_dict()
    )
    recommendation_pair_counts = (
        display.groupby("optimizer_candidate_id")[
            "recommendation_team"
        ].nunique()
    )
    displayed_team_count = int(
        recommendations["recommendation_team"].nunique()
    )

    validation_rows = [
        {
            "check_name": "calibrated_release_valid",
            "passed": bool(calibrated_metadata.get("release_valid")),
            "observed": calibrated_metadata.get("release_valid"),
            "expected": True,
        },
        {
            "check_name": "calibrated_validation_all_passed",
            "passed": bool(
                calibrated_validation["passed"].map(bool_value).all()
            ),
            "observed": int(
                calibrated_validation["passed"].map(bool_value).sum()
            ),
            "expected": len(calibrated_validation),
        },
        {
            "check_name": "app_team_row_count",
            "passed": len(recommendations) == EXPECTED_APP_TEAM_ROWS,
            "observed": len(recommendations),
            "expected": EXPECTED_APP_TEAM_ROWS,
        },
        {
            "check_name": "app_concept_count",
            "passed": len(concepts) == EXPECTED_APP_CONCEPTS,
            "observed": len(concepts),
            "expected": EXPECTED_APP_CONCEPTS,
        },
        {
            "check_name": "two_team_rows_per_app_concept",
            "passed": bool(recommendation_pair_counts.eq(2).all()),
            "observed": recommendation_pair_counts.value_counts().to_dict(),
            "expected": {2: EXPECTED_APP_CONCEPTS},
        },
        {
            "check_name": "production_concept_count",
            "passed": (
                int(
                    concepts["display_tier"]
                    .eq("Model-backed recommendation")
                    .sum()
                )
                == EXPECTED_PRODUCTION_CONCEPTS
            ),
            "observed": int(
                concepts["display_tier"]
                .eq("Model-backed recommendation")
                .sum()
            ),
            "expected": EXPECTED_PRODUCTION_CONCEPTS,
        },
        {
            "check_name": "shortlist_concept_count",
            "passed": (
                int(
                    concepts["display_tier"]
                    .eq("Exploratory strategy shortlist")
                    .sum()
                )
                == EXPECTED_SHORTLIST_CONCEPTS
            ),
            "observed": int(
                concepts["display_tier"]
                .eq("Exploratory strategy shortlist")
                .sum()
            ),
            "expected": EXPECTED_SHORTLIST_CONCEPTS,
        },
        {
            "check_name": "no_manual_or_hold_rows_in_app",
            "passed": set(display_status_counts).issubset(
                {
                    "production_recommendation",
                    "strategy_shortlist",
                }
            ),
            "observed": display_status_counts,
            "expected": {
                "production_recommendation": 2,
                "strategy_shortlist": 10,
            },
        },
        {
            "check_name": "teams_with_recommendations",
            "passed": (
                displayed_team_count
                == EXPECTED_TEAMS_WITH_RECOMMENDATIONS
            ),
            "observed": displayed_team_count,
            "expected": EXPECTED_TEAMS_WITH_RECOMMENDATIONS,
        },
        {
            "check_name": "team_status_covers_30_teams",
            "passed": len(team_status) == EXPECTED_TEAM_ROWS,
            "observed": len(team_status),
            "expected": EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "team_status_matches_display_rows",
            "passed": bool(
                team_status["app_has_recommendations"].sum()
                == displayed_team_count
            ),
            "observed": int(
                team_status["app_has_recommendations"].sum()
            ),
            "expected": displayed_team_count,
        },
        {
            "check_name": "all_app_rows_are_deterministic_legal",
            "passed": bool(
                recommendations["optimizer_package_final_legal"]
                .map(bool_value)
                .all()
            ),
            "observed": int(
                recommendations["optimizer_package_final_legal"]
                .map(bool_value)
                .sum()
            ),
            "expected": len(recommendations),
        },
        {
            "check_name": "all_app_rows_have_labels",
            "passed": bool(
                recommendations[
                    [
                        "display_tier",
                        "team_headline",
                        "team_subheadline",
                        "team_fit_summary",
                        "confidence_note",
                    ]
                ]
                .notna()
                .all()
                .all()
            ),
            "observed": int(
                recommendations[
                    [
                        "display_tier",
                        "team_headline",
                        "team_subheadline",
                        "team_fit_summary",
                        "confidence_note",
                    ]
                ]
                .notna()
                .all(axis=1)
                .sum()
            ),
            "expected": len(recommendations),
        },
        {
            "check_name": "all_30_teams_have_status_messages",
            "passed": bool(
                team_status[
                    ["app_status_label", "empty_state_message"]
                ]
                .notna()
                .all()
                .all()
            ),
            "observed": int(
                team_status[
                    ["app_status_label", "empty_state_message"]
                ]
                .notna()
                .all(axis=1)
                .sum()
            ),
            "expected": EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "team_strategy_priorities_complete",
            "passed": bool(
                team_status["model_team_strategy_priority"]
                .fillna("")
                .astype(str)
                .str.strip()
                .ne("")
                .all()
            ),
            "observed": int(
                team_status["model_team_strategy_priority"]
                .fillna("")
                .astype(str)
                .str.strip()
                .ne("")
                .sum()
            ),
            "expected": EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "data_contract_version_consistent",
            "passed": (
                recommendations["app_data_contract_version"].nunique()
                == 1
                and concepts["app_data_contract_version"].nunique()
                == 1
                and team_status["app_data_contract_version"].nunique()
                == 1
            ),
            "observed": "mixed_trade_app_v1",
            "expected": "mixed_trade_app_v1",
        },
    ]

    release_valid = all(
        bool(row["passed"])
        for row in validation_rows
    )

    print("[6/7] Writing app-ready artifacts")
    recommendations.to_csv(APP_RECOMMENDATIONS_OUTPUT, index=False)
    concepts.to_csv(APP_CONCEPTS_OUTPUT, index=False)
    team_status.to_csv(APP_TEAM_STATUS_OUTPUT, index=False)
    APP_BUNDLE_OUTPUT.write_text(
        json.dumps(json_safe(bundle), indent=2),
        encoding="utf-8",
    )

    methodology = {
        "data_contract_version": "mixed_trade_app_v1",
        "display_tiers": {
            "Model-backed recommendation": (
                DISPLAY_STATUS_DESCRIPTIONS[
                    "production_recommendation"
                ]
            ),
            "Exploratory strategy shortlist": (
                DISPLAY_STATUS_DESCRIPTIONS[
                    "strategy_shortlist"
                ]
            ),
        },
        "score_labels": {
            "team_strategy_score_display": (
                "Team-specific strategy score, 0-100"
            ),
            "counterpart_strategy_score_display": (
                "Counterpart team-specific strategy score, 0-100"
            ),
            "bilateral_floor_score_display": (
                "Lower of the two team strategy scores"
            ),
            "bilateral_mean_score_display": (
                "Average of the two team strategy scores"
            ),
        },
        "display_rules": {
            "manual_context_review": (
                "Analyst-only. Do not show as a public recommendation."
            ),
            "hold_not_displayed": (
                "Excluded from recommendation cards."
            ),
            "protected_player_blockbusters": (
                "Concept-only and outside this app-facing routine release."
            ),
        },
        "disclaimers": [
            (
                "Model-generated concepts do not imply that a player or team "
                "is actually available."
            ),
            (
                "Legality is deterministic within the modeled package checks "
                "and evidence cutoff, not a substitute for official league "
                "approval."
            ),
            (
                "Strategy shortlist concepts require additional team-context "
                "review."
            ),
        ],
    }
    APP_METHODOLOGY_OUTPUT.write_text(
        json.dumps(methodology, indent=2),
        encoding="utf-8",
    )

    pd.DataFrame(validation_rows).to_csv(
        VALIDATION_OUTPUT,
        index=False,
    )

    integration_metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_valid": release_valid,
        "upstream_calibrated_release": str(
            CALIBRATED_METADATA_PATH
        ),
        "data_contract_version": "mixed_trade_app_v1",
        "counts": {
            "app_team_recommendation_rows": len(recommendations),
            "app_concepts": len(concepts),
            "teams_with_recommendations": displayed_team_count,
            "team_status_rows": len(team_status),
            "model_backed_concepts": int(
                concepts["display_tier"]
                .eq("Model-backed recommendation")
                .sum()
            ),
            "exploratory_shortlist_concepts": int(
                concepts["display_tier"]
                .eq("Exploratory strategy shortlist")
                .sum()
            ),
        },
        "scope_note": (
            "This release is the stable app data contract. It does not "
            "recompute or alter legality, protection, quality, or strategy "
            "scores."
        ),
        "outputs": {
            "app_recommendations": str(APP_RECOMMENDATIONS_OUTPUT),
            "app_concepts": str(APP_CONCEPTS_OUTPUT),
            "app_team_status": str(APP_TEAM_STATUS_OUTPUT),
            "app_bundle": str(APP_BUNDLE_OUTPUT),
            "app_methodology": str(APP_METHODOLOGY_OUTPUT),
            "validation": str(VALIDATION_OUTPUT),
        },
    }
    METADATA_OUTPUT.write_text(
        json.dumps(
            json_safe(integration_metadata),
            indent=2,
        ),
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
        f"App concepts: {len(concepts):,} | app team rows: "
        f"{len(recommendations):,}"
    )
    print(
        f"Teams with recommendations: {displayed_team_count:,}/"
        f"{len(team_status):,}"
    )
    print(
        "Model-backed concepts: "
        f"{int(concepts['display_tier'].eq('Model-backed recommendation').sum()):,}"
    )
    print(
        "Exploratory shortlist concepts: "
        f"{int(concepts['display_tier'].eq('Exploratory strategy shortlist').sum()):,}"
    )
    print("Manual and held concepts included in app cards: False")

    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())