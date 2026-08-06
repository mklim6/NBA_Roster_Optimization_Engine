"""Audit the V4 mixed player-and-pick pool before team-strategy scoring.

This script is intentionally diagnostic. It does not change CBA legality,
protected-player classifications, or release a final team-strategy score.

It:
1. Validates the V4 quality-gate release.
2. Collapses routine/minor packages into unique player-exchange concepts.
3. Audits every surviving player against the centralized V4 protected-player market.
4. Flags possible systematic young-asset protection gaps for review.
5. Builds model-derived team timeline profiles from future team-strength data.
6. Joins roster needs when available.
7. Reports whether the project is ready for a final strategy-ranking layer.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


SCRIPT_VERSION = "mixed-player-pick-strategy-readiness-audit-v2-2026-08-05"
RELEASE_NAME = "mixed_player_pick_strategy_readiness_audit_2026_27_v2"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

ROUTINE_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_routine_recommendation_review_2026_27_v4.csv"
)
MINOR_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_minor_asset_recommendation_review_2026_27_v4.csv"
)
BLOCKBUSTER_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_premium_blockbuster_concepts_2026_27_v4.csv"
)
TEAM_TOP_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_team_quality_gate_top_50_2026_27_v4.csv"
)
QUALITY_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_recommendation_quality_gate_metadata_v4.json"
)

PLAYER_MARKET_PARQUET_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.parquet"
)
PLAYER_MARKET_CSV_PATH = (
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.csv"
)
PROTECTION_OVERRIDE_PATH = (
    DATA_DIRECTORY
    / "player_protection_overrides_2026_27_v1.csv"
)

TEAM_STRENGTH_PARQUET_PATH = (
    DATA_DIRECTORY
    / "future_team_strength_projections_2026_27_to_2032_33_v1.parquet"
)
TEAM_STRENGTH_CSV_PATH = (
    DATA_DIRECTORY
    / "future_team_strength_projections_2026_27_to_2032_33_v1.csv"
)
TEAM_NEEDS_PATH = (
    DATA_DIRECTORY
    / "team_roster_needs_2026_27.csv"
)

CONCEPT_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_concept_audit_2026_27_v2.csv"
)
PLAYER_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_player_audit_2026_27_v2.csv"
)
TEAM_PROFILE_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_team_profiles_2026_27_v2.csv"
)
TEAM_CONCENTRATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_team_concentration_2026_27_v2.csv"
)
BLOCKBUSTER_AUDIT_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_blockbuster_audit_2026_27_v2.csv"
)
VALIDATION_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_readiness_validation_v2.csv"
)
METADATA_OUTPUT = (
    OUTPUT_DIRECTORY
    / "mixed_player_pick_strategy_readiness_metadata_v2.json"
)

EXPECTED_ROUTINE_ROWS = 33
EXPECTED_MINOR_ROWS = 23
EXPECTED_BLOCKBUSTER_ROWS = 11
EXPECTED_ROUTINE_LEVEL_ROWS = 56
EXPECTED_TEAM_PERSPECTIVE_ROWS = 112

PROTECTED_CLASSES = {
    "franchise_caliber",
    "star_caliber",
    "premium_young_asset",
}

# These rules are review flags only. They do not automatically protect a player.
YOUNG_ASSET_REVIEW_RULES = {
    "very_young_market_floor": {
        "maximum_age": 22.0,
        "minimum_market_percentile": 70.0,
    },
    "young_high_market": {
        "maximum_age": 24.0,
        "minimum_market_percentile": 84.0,
    },
    "young_caliber_and_market": {
        "maximum_age": 24.0,
        "minimum_market_percentile": 74.0,
        "minimum_on_court_caliber": 64.0,
    },
    "young_lottery_pick": {
        "maximum_age": 24.0,
        "maximum_draft_pick": 14.0,
    },
}

TEAM_PROFILE_SEASONS = [
    "2026-27",
    "2028-29",
    "2030-31",
    "2032-33",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without project files.",
    )
    return parser.parse_args()


def normalized_text(value: Any) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


def clean_text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


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


def split_players(value: Any) -> list[str]:
    return [
        part.strip()
        for part in str(value).split("|")
        if part.strip()
    ]


def sorted_player_string(value: Any) -> str:
    return "|".join(sorted(split_players(value), key=normalized_text))


def infer_pick_round(value: Any) -> str:
    text = str(value).lower()
    if "first-round" in text or re.search(r"\br1\b|_r1_", text):
        return "first_round"
    if "second-round" in text or re.search(r"\br2\b|_r2_", text):
        return "second_round"
    return "other_or_complex"


def read_table(parquet_path: Path, csv_path: Path) -> tuple[pd.DataFrame, str]:
    if parquet_path.exists():
        return pd.read_parquet(parquet_path), str(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path), str(csv_path)
    raise FileNotFoundError(
        "Neither table representation was found:\n"
        f"{parquet_path}\n{csv_path}"
    )


def first_existing(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def numeric_column(
    frame: pd.DataFrame,
    candidates: Iterable[str],
    default: float = np.nan,
) -> pd.Series:
    column = first_existing(frame, candidates)
    if column is None:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def concept_key(row: pd.Series) -> str:
    sides = sorted(
        [
            (
                f"{clean_text(row['team_a'])}:"
                f"{sorted_player_string(row['side_a_player_names'])}"
            ),
            (
                f"{clean_text(row['team_b'])}:"
                f"{sorted_player_string(row['side_b_player_names'])}"
            ),
        ]
    )
    return "||".join(sides)


def normalize_v4_player_market(
    players: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize the centralized V4 effective protection fields.

    V4 already preserves the original V3 classification, applies the reviewed
    override ledger, and applies the generalized young-core rule. This audit
    must consume that effective market directly and must not reapply any
    protection logic.
    """
    output = players.copy()
    output["player_name_key"] = output["player_name"].map(normalized_text)
    output["team_key"] = output[
        "current_team_2026_27"
    ].astype(str).str.strip()

    required = {
        "recommendation_asset_class_v4",
        "protected_player_flag_v4",
        "protected_player_reason_v4",
        "protection_source_v4",
        "young_core_protection_rule_v4_applied",
        "protection_override_applied",
        "model_recommendation_asset_class_v3",
        "model_protected_player_flag_v3",
        "model_protected_player_reason_v3",
    }
    missing = sorted(required.difference(output.columns))
    if missing:
        raise ValueError(
            "The centralized V4 player market is missing required fields:\n"
            + "\n".join(missing)
        )

    output["effective_protected_player_flag"] = output[
        "protected_player_flag_v4"
    ].map(bool_value)
    output["effective_recommendation_asset_class_v4"] = output[
        "recommendation_asset_class_v4"
    ].astype(str)
    output["effective_protected_player_reason_v4"] = output[
        "protected_player_reason_v4"
    ].astype(str)
    output["young_core_protection_rule_v4_applied"] = output[
        "young_core_protection_rule_v4_applied"
    ].map(bool_value)
    output["protection_override_applied"] = output[
        "protection_override_applied"
    ].map(bool_value)

    return output

def young_asset_review_flags(row: pd.Series) -> list[str]:
    if bool(row["effective_protected_player_flag"]):
        return []

    age = safe_float(row.get("age"))
    market = safe_float(row.get("market_value_percentile_v2"))
    caliber = safe_float(row.get("on_court_caliber_score"))
    draft_pick = safe_float(row.get("draft_pick_number"))

    flags: list[str] = []

    rule = YOUNG_ASSET_REVIEW_RULES["very_young_market_floor"]
    if (
        math.isfinite(age)
        and math.isfinite(market)
        and age <= rule["maximum_age"]
        and market >= rule["minimum_market_percentile"]
    ):
        flags.append("very_young_market_floor")

    rule = YOUNG_ASSET_REVIEW_RULES["young_high_market"]
    if (
        math.isfinite(age)
        and math.isfinite(market)
        and age <= rule["maximum_age"]
        and market >= rule["minimum_market_percentile"]
    ):
        flags.append("young_high_market")

    rule = YOUNG_ASSET_REVIEW_RULES["young_caliber_and_market"]
    if (
        math.isfinite(age)
        and math.isfinite(market)
        and math.isfinite(caliber)
        and age <= rule["maximum_age"]
        and market >= rule["minimum_market_percentile"]
        and caliber >= rule["minimum_on_court_caliber"]
    ):
        flags.append("young_caliber_and_market")

    rule = YOUNG_ASSET_REVIEW_RULES["young_lottery_pick"]
    if (
        math.isfinite(age)
        and math.isfinite(draft_pick)
        and age <= rule["maximum_age"]
        and draft_pick <= rule["maximum_draft_pick"]
    ):
        flags.append("young_lottery_pick")

    return sorted(set(flags))


def build_player_audit(
    packages: pd.DataFrame,
    players: pd.DataFrame,
) -> pd.DataFrame:
    appearances: list[dict[str, Any]] = []

    for _, row in packages.iterrows():
        for side in ("a", "b"):
            names = split_players(row[f"side_{side}_player_names"])
            classes = [
                part.strip()
                for part in str(
                    row[f"quality_side_{side}_asset_classes_v4"]
                ).split("|")
            ]

            for index, player_name in enumerate(names):
                appearances.append(
                    {
                        "player_name": player_name,
                        "player_name_key": normalized_text(player_name),
                        "team_abbreviation": clean_text(row[f"team_{side}"]),
                        "package_asset_class_v4": (
                            classes[index] if index < len(classes) else ""
                        ),
                        "optimizer_candidate_id": row["optimizer_candidate_id"],
                        "quality_gate_class": row["quality_gate_class"],
                        "package_score": safe_float(
                            row["optimizer_final_legal_rank_score_v1"],
                            0.0,
                        ),
                        "player_exchange_key": row["player_exchange_key"],
                    }
                )

    appearance_frame = pd.DataFrame(appearances)

    appearance_summary = (
        appearance_frame.groupby(
            [
                "player_name",
                "player_name_key",
                "team_abbreviation",
                "package_asset_class_v4",
            ],
            dropna=False,
        )
        .agg(
            routine_level_package_appearances=(
                "optimizer_candidate_id",
                "size",
            ),
            unique_player_exchange_concepts=(
                "player_exchange_key",
                "nunique",
            ),
            maximum_package_score=(
                "package_score",
                "max",
            ),
        )
        .reset_index()
    )

    player_lookup = players.copy()
    player_lookup["team_abbreviation"] = player_lookup[
        "current_team_2026_27"
    ].astype(str).str.strip()

    market_columns = [
        "player_name_key",
        "team_abbreviation",
        "player_id",
        "age",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "player_quality_score",
        "expected_contribution_percentile",
        "roster_value_percentile",
        "projected_expected_contribution",
        "survival_weighted_active_downside_score",
        "model_recommendation_asset_class_v3",
        "model_protected_player_flag_v3",
        "model_protected_player_reason_v3",
        "post_override_recommendation_asset_class_v3",
        "post_override_protected_player_flag_v3",
        "recommendation_asset_class_v4",
        "protected_player_flag_v4",
        "protected_player_reason_v4",
        "effective_recommendation_asset_class_v4",
        "effective_protected_player_flag",
        "effective_protected_player_reason_v4",
        "protection_source_v4",
        "protection_override_applied",
        "young_core_protection_rule_v4_applied",
    ]

    draft_column = first_existing(
        player_lookup,
        [
            "draft_pick_number",
            "draft_pick",
            "draft_number",
            "overall_pick",
            "pick_number",
        ],
    )
    if draft_column is not None:
        player_lookup["draft_pick_number"] = pd.to_numeric(
            player_lookup[draft_column],
            errors="coerce",
        )
    else:
        player_lookup["draft_pick_number"] = np.nan

    for column in market_columns:
        if column not in player_lookup.columns:
            player_lookup[column] = np.nan

    market_columns.append("draft_pick_number")

    audit = appearance_summary.merge(
        player_lookup[market_columns],
        on=["player_name_key", "team_abbreviation"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )

    audit["player_market_match"] = audit["_merge"].eq("both")
    audit = audit.drop(columns=["_merge"])

    flags = audit.apply(young_asset_review_flags, axis=1)
    audit["young_asset_review_flags"] = [
        "|".join(value) for value in flags
    ]
    audit["young_asset_review_required"] = [
        bool(value) for value in flags
    ]

    audit["young_asset_review_priority"] = np.select(
        [
            (
                audit["young_asset_review_required"]
                & (audit["routine_level_package_appearances"] >= 3)
            ),
            audit["young_asset_review_required"],
        ],
        ["high", "standard"],
        default="none",
    )

    return audit.sort_values(
        [
            "young_asset_review_required",
            "young_asset_review_priority",
            "maximum_package_score",
            "routine_level_package_appearances",
        ],
        ascending=[False, True, False, False],
    ).reset_index(drop=True)


def build_concept_audit(packages: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for key, group in packages.groupby("player_exchange_key", sort=True):
        ordered = group.sort_values(
            [
                "optimizer_final_legal_rank_score_v1",
                "adjusted_absolute_value_gap",
                "optimizer_candidate_id",
            ],
            ascending=[False, True, True],
        )
        best = ordered.iloc[0]

        rows.append(
            {
                "player_exchange_key": key,
                "team_a": best["team_a"],
                "team_b": best["team_b"],
                "side_a_player_names": best["side_a_player_names"],
                "side_b_player_names": best["side_b_player_names"],
                "package_variants": len(group),
                "routine_variants": int(
                    group["quality_gate_class"]
                    .eq("routine_recommendation_review")
                    .sum()
                ),
                "minor_asset_variants": int(
                    group["quality_gate_class"]
                    .eq("routine_plus_minor_assets_review")
                    .sum()
                ),
                "pick_round_types": "|".join(
                    sorted(set(group["pick_round_type"].astype(str)))
                ),
                "attached_pick_teams": "|".join(
                    sorted(set(group["attached_pick_team"].astype(str)))
                ),
                "best_optimizer_candidate_id": best["optimizer_candidate_id"],
                "best_quality_gate_class": best["quality_gate_class"],
                "best_right_display_name": best["right_display_name"],
                "best_attached_pick_team": best["attached_pick_team"],
                "best_quality_minimum_team_fit_score": safe_float(
                    best["quality_minimum_team_fit_score"]
                ),
                "best_realism_signal_percentile": safe_float(
                    best["realism_signal_percentile"]
                ),
                "best_adjusted_absolute_value_gap": safe_float(
                    best["adjusted_absolute_value_gap"]
                ),
                "best_package_quality_score": safe_float(
                    best["optimizer_final_legal_rank_score_v1"]
                ),
                "concept_requires_pick_variant_deduplication": len(group) > 1,
            }
        )

    return pd.DataFrame(rows).sort_values(
        [
            "best_package_quality_score",
            "package_variants",
            "player_exchange_key",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def classify_team_strategy(row: pd.Series) -> tuple[str, str]:
    near_strength = safe_float(row.get("strength_percentile_2026_27"), 50.0)
    medium_strength = safe_float(row.get("strength_percentile_2028_29"), 50.0)
    long_strength = safe_float(row.get("strength_percentile_2030_31"), 50.0)
    near_wins = safe_float(row.get("projected_wins_2026_27"), 41.0)
    age = safe_float(row.get("average_age_top_eight_2026_27"), 27.0)
    young_core = safe_float(row.get("young_core_contribution_2026_27"), 0.0)

    future_delta = long_strength - near_strength

    if near_strength >= 75.0 and near_wins >= 46.0:
        return (
            "win_now_contender",
            "prioritize immediate rotation upgrades and consolidation; "
            "future picks may be attached only for clear present-value improvement",
        )

    if near_strength >= 55.0:
        return (
            "competitive_builder",
            "balance present upgrades with contract control and avoid unnecessary "
            "first-round-pick expenditure",
        )

    if (
        near_strength < 40.0
        and (
            future_delta >= 10.0
            or age <= 25.0
            or young_core > 0.0
        )
    ):
        return (
            "development_rebuild",
            "prioritize young controlled players and incoming draft value; "
            "avoid veteran-only upgrades",
        )

    if medium_strength >= near_strength + 8.0:
        return (
            "ascending_retool",
            "favor timeline-compatible players and preserve premium future assets",
        )

    return (
        "flexible_retool",
        "favor balanced value, roster fit, and future flexibility without "
        "forcing a win-now or teardown objective",
    )


def build_team_profiles(
    strength: pd.DataFrame,
    needs: pd.DataFrame | None,
) -> pd.DataFrame:
    season_column = first_existing(
        strength,
        ["projection_season", "season"],
    )
    team_column = first_existing(
        strength,
        ["team_abbreviation", "team"],
    )
    if season_column is None or team_column is None:
        raise ValueError(
            "Future team-strength data lacks projection season or team columns."
        )

    strength = strength.copy()
    strength[season_column] = strength[season_column].astype(str)
    strength[team_column] = strength[team_column].astype(str).str.strip()

    strength_percentile_column = first_existing(
        strength,
        ["team_strength_percentile"],
    )
    wins_column = first_existing(
        strength,
        ["projected_mean_wins_proxy", "projected_wins"],
    )
    age_column = first_existing(
        strength,
        ["average_projected_age_top_eight", "average_age_top_eight"],
    )
    young_core_column = first_existing(
        strength,
        ["young_core_contribution"],
    )

    if strength_percentile_column is None or wins_column is None:
        raise ValueError(
            "Future team-strength data lacks team strength percentile or wins."
        )

    rows: list[dict[str, Any]] = []
    teams = sorted(strength[team_column].dropna().unique())

    for team in teams:
        row: dict[str, Any] = {"team_abbreviation": team}
        team_rows = strength.loc[strength[team_column] == team]

        for season in TEAM_PROFILE_SEASONS:
            season_rows = team_rows.loc[
                team_rows[season_column] == season
            ]
            if season_rows.empty:
                row[f"strength_percentile_{season.replace('-', '_')}"] = np.nan
                row[f"projected_wins_{season.replace('-', '_')}"] = np.nan
                continue

            record = season_rows.iloc[0]
            suffix = season.replace("-", "_")
            row[f"strength_percentile_{suffix}"] = safe_float(
                record[strength_percentile_column]
            )
            row[f"projected_wins_{suffix}"] = safe_float(
                record[wins_column]
            )

            if age_column is not None:
                row[f"average_age_top_eight_{suffix}"] = safe_float(
                    record[age_column]
                )
            if young_core_column is not None:
                row[f"young_core_contribution_{suffix}"] = safe_float(
                    record[young_core_column]
                )

        rows.append(row)

    profiles = pd.DataFrame(rows)
    profiles = profiles.rename(
        columns={
            "strength_percentile_2026_27": "strength_percentile_2026_27",
            "strength_percentile_2028_29": "strength_percentile_2028_29",
            "strength_percentile_2030_31": "strength_percentile_2030_31",
            "strength_percentile_2032_33": "strength_percentile_2032_33",
            "projected_wins_2026_27": "projected_wins_2026_27",
            "average_age_top_eight_2026_27": "average_age_top_eight_2026_27",
            "young_core_contribution_2026_27": "young_core_contribution_2026_27",
        }
    )

    classifications = profiles.apply(
        classify_team_strategy,
        axis=1,
        result_type="expand",
    )
    classifications.columns = [
        "model_team_strategy_archetype",
        "model_team_strategy_priority",
    ]
    profiles = pd.concat([profiles, classifications], axis=1)

    profiles["model_pick_preference"] = profiles[
        "model_team_strategy_archetype"
    ].map(
        {
            "win_now_contender": "player_upgrade_over_pick_accumulation",
            "competitive_builder": "balanced_preserve_firsts",
            "development_rebuild": "receive_future_assets",
            "ascending_retool": "preserve_firsts_add_young_players",
            "flexible_retool": "balanced_flexibility",
        }
    )

    if needs is not None and not needs.empty:
        needs = needs.copy()
        needs_team_column = first_existing(
            needs,
            ["team_abbreviation", "team"],
        )
        if needs_team_column is not None:
            needs[needs_team_column] = (
                needs[needs_team_column].astype(str).str.strip()
            )
            needs_columns = [
                column
                for column in [
                    needs_team_column,
                    "top_need_1",
                    "top_need_2",
                    "top_need_3",
                    "scoring_need_score",
                    "shooting_need_score",
                    "playmaking_need_score",
                    "rebounding_need_score",
                    "defense_need_score",
                ]
                if column in needs.columns
            ]
            needs_join = needs[needs_columns].drop_duplicates(
                needs_team_column
            )
            profiles = profiles.merge(
                needs_join,
                left_on="team_abbreviation",
                right_on=needs_team_column,
                how="left",
                validate="one_to_one",
            )
            if needs_team_column != "team_abbreviation":
                profiles = profiles.drop(columns=[needs_team_column])

    return profiles.sort_values("team_abbreviation").reset_index(drop=True)


def build_team_concentration(
    packages: pd.DataFrame,
    concepts: pd.DataFrame,
) -> pd.DataFrame:
    package_rows: list[dict[str, Any]] = []
    concept_rows: list[dict[str, Any]] = []

    for _, row in packages.iterrows():
        for team in (row["team_a"], row["team_b"]):
            package_rows.append(
                {
                    "team_abbreviation": team,
                    "optimizer_candidate_id": row["optimizer_candidate_id"],
                    "player_exchange_key": row["player_exchange_key"],
                }
            )

    for _, row in concepts.iterrows():
        for team in (row["team_a"], row["team_b"]):
            concept_rows.append(
                {
                    "team_abbreviation": team,
                    "player_exchange_key": row["player_exchange_key"],
                }
            )

    package_frame = pd.DataFrame(package_rows)
    concept_frame = pd.DataFrame(concept_rows)

    package_counts = (
        package_frame.groupby("team_abbreviation")
        .agg(
            routine_level_package_rows=("optimizer_candidate_id", "size"),
            unique_player_exchange_concepts=(
                "player_exchange_key",
                "nunique",
            ),
        )
        .reset_index()
    )

    concept_variant_counts = (
        concept_frame.groupby("team_abbreviation")
        .size()
        .rename("concept_rows_after_deduplication")
        .reset_index()
    )

    output = package_counts.merge(
        concept_variant_counts,
        on="team_abbreviation",
        how="outer",
    ).fillna(0)

    output["duplicate_pick_variant_rows"] = (
        output["routine_level_package_rows"]
        - output["unique_player_exchange_concepts"]
    )

    return output.sort_values(
        [
            "routine_level_package_rows",
            "unique_player_exchange_concepts",
            "team_abbreviation",
        ],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_blockbuster_audit(blockbusters: pd.DataFrame) -> pd.DataFrame:
    output = blockbusters.copy()
    output["player_exchange_key"] = output.apply(concept_key, axis=1)
    output["pick_round_type"] = output["right_display_name"].map(
        infer_pick_round
    )
    output["strategy_release_status"] = "concept_only_not_team_strategy_released"
    output["strategy_release_reason"] = (
        "Protected-player trade; public availability, team direction, and "
        "ownership willingness are outside the model."
    )
    return output.sort_values(
        "optimizer_final_legal_rank_score_v1",
        ascending=False,
    ).reset_index(drop=True)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
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
            "team_a": "AAA",
            "team_b": "BBB",
            "side_a_player_names": "Player Two|Player One",
            "side_b_player_names": "Player Three",
        }
    )
    young = pd.Series(
        {
            "effective_protected_player_flag": False,
            "age": 21,
            "market_value_percentile_v2": 88,
            "on_court_caliber_score": 70,
            "draft_pick_number": 10,
        }
    )
    protected = young.copy()
    protected["effective_protected_player_flag"] = True
    protected["effective_recommendation_asset_class_v4"] = (
        "premium_young_asset"
    )

    tests = {
        "player_sorting": sorted_player_string(
            "Player Two|Player One"
        ) == "Player One|Player Two",
        "concept_key_direction_structure": (
            concept_key(row)
            == "AAA:Player One|Player Two||BBB:Player Three"
        ),
        "first_round_detection": infer_pick_round(
            "AAA 2028 first-round component right"
        ) == "first_round",
        "second_round_detection": infer_pick_round(
            "AAA beneficiary transferred for 2029_R2_AAA"
        ) == "second_round",
        "young_asset_review_flags_fire": bool(
            young_asset_review_flags(young)
        ),
        "protected_player_not_flagged": not young_asset_review_flags(
            protected
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("MIXED PLAYER-AND-PICK STRATEGY READINESS AUDIT")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading and validating V4 quality-gate outputs")
    required_paths = [
        ROUTINE_PATH,
        MINOR_PATH,
        BLOCKBUSTER_PATH,
        TEAM_TOP_PATH,
        QUALITY_METADATA_PATH,
    ]
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        raise FileNotFoundError(
            "Missing required V4 quality-gate files:\n"
            + "\n".join(str(path) for path in missing_paths)
        )

    routine = pd.read_csv(ROUTINE_PATH)
    minor = pd.read_csv(MINOR_PATH)
    blockbusters = pd.read_csv(BLOCKBUSTER_PATH)
    team_top = pd.read_csv(TEAM_TOP_PATH)
    quality_metadata = json.loads(
        QUALITY_METADATA_PATH.read_text(encoding="utf-8")
    )

    packages = pd.concat(
        [routine, minor],
        ignore_index=True,
        sort=False,
    )
    packages["player_exchange_key"] = packages.apply(
        concept_key,
        axis=1,
    )
    packages["pick_round_type"] = packages[
        "right_display_name"
    ].map(infer_pick_round)

    print(
        f"  Routine: {len(routine):,} | Minor assets: {len(minor):,} | "
        f"Blockbusters: {len(blockbusters):,}"
    )

    print("[2/7] Loading centralized V4 protected-player market")
    players, player_market_source = read_table(
        PLAYER_MARKET_PARQUET_PATH,
        PLAYER_MARKET_CSV_PATH,
    )
    required_player_columns = {
        "player_id",
        "player_name",
        "current_team_2026_27",
        "age",
        "market_value_percentile_v2",
        "on_court_caliber_score",
        "recommendation_asset_class_v4",
        "protected_player_flag_v4",
        "protected_player_reason_v4",
        "protection_source_v4",
        "young_core_protection_rule_v4_applied",
    }
    missing_player_columns = sorted(
        required_player_columns.difference(players.columns)
    )
    if missing_player_columns:
        raise ValueError(
            "V3 player market is missing required columns:\n"
            + "\n".join(missing_player_columns)
        )
    players = normalize_v4_player_market(players)
    override_count = int(
        players["protection_override_applied"].sum()
    )
    generalized_rule_count = int(
        players["young_core_protection_rule_v4_applied"].sum()
    )
    print(
        f"  Player rows: {len(players):,} | reviewed overrides: "
        f"{override_count:,} | generalized-rule additions: "
        f"{generalized_rule_count:,}"
    )

    print("[3/7] Building concept-level and player-level audits")
    concept_audit = build_concept_audit(packages)
    player_audit = build_player_audit(packages, players)
    team_concentration = build_team_concentration(
        packages,
        concept_audit,
    )
    blockbuster_audit = build_blockbuster_audit(blockbusters)

    print(
        f"  Routine-level packages: {len(packages):,} -> "
        f"{len(concept_audit):,} unique player-exchange concepts"
    )
    print(
        "  Young-asset review candidates: "
        f"{int(player_audit['young_asset_review_required'].sum()):,}"
    )

    print("[4/7] Building model-derived team timeline profiles")
    team_strength_available = (
        TEAM_STRENGTH_PARQUET_PATH.exists()
        or TEAM_STRENGTH_CSV_PATH.exists()
    )
    team_needs_available = TEAM_NEEDS_PATH.exists()

    if team_strength_available:
        strength, team_strength_source = read_table(
            TEAM_STRENGTH_PARQUET_PATH,
            TEAM_STRENGTH_CSV_PATH,
        )
        needs = (
            pd.read_csv(TEAM_NEEDS_PATH)
            if team_needs_available
            else None
        )
        team_profiles = build_team_profiles(strength, needs)
    else:
        team_strength_source = ""
        team_profiles = pd.DataFrame(
            columns=[
                "team_abbreviation",
                "model_team_strategy_archetype",
                "model_team_strategy_priority",
                "model_pick_preference",
            ]
        )

    print(
        f"  Team strength available: {team_strength_available} | "
        f"team needs available: {team_needs_available}"
    )

    print("[5/7] Validating strategy readiness")
    unmatched_players = player_audit.loc[
        ~player_audit["player_market_match"]
    ]
    young_review = player_audit.loc[
        player_audit["young_asset_review_required"]
    ]

    validation_rows = [
        {
            "check_name": "v4_quality_gate_release_valid",
            "passed": bool(quality_metadata.get("release_valid")),
            "observed": quality_metadata.get("release_valid"),
            "expected": True,
        },
        {
            "check_name": "v4_quality_gate_script_version",
            "passed": "quality-gate-v4" in str(
                quality_metadata.get("script_version", "")
            ),
            "observed": quality_metadata.get("script_version"),
            "expected": "mixed-player-pick-recommendation-quality-gate-v4",
        },
        {
            "check_name": "centralized_v4_market_contains_protection_sources",
            "passed": (
                override_count >= 4
                and generalized_rule_count >= 1
            ),
            "observed": {
                "reviewed_overrides": override_count,
                "generalized_rule_additions": generalized_rule_count,
            },
            "expected": {
                "reviewed_overrides_minimum": 4,
                "generalized_rule_additions_minimum": 1,
            },
        },
        {
            "check_name": "routine_row_count",
            "passed": len(routine) == EXPECTED_ROUTINE_ROWS,
            "observed": len(routine),
            "expected": EXPECTED_ROUTINE_ROWS,
        },
        {
            "check_name": "minor_row_count",
            "passed": len(minor) == EXPECTED_MINOR_ROWS,
            "observed": len(minor),
            "expected": EXPECTED_MINOR_ROWS,
        },
        {
            "check_name": "blockbuster_row_count",
            "passed": len(blockbusters) == EXPECTED_BLOCKBUSTER_ROWS,
            "observed": len(blockbusters),
            "expected": EXPECTED_BLOCKBUSTER_ROWS,
        },
        {
            "check_name": "routine_level_total",
            "passed": len(packages) == EXPECTED_ROUTINE_LEVEL_ROWS,
            "observed": len(packages),
            "expected": EXPECTED_ROUTINE_LEVEL_ROWS,
        },
        {
            "check_name": "team_perspective_top_rows",
            "passed": len(team_top) == EXPECTED_TEAM_PERSPECTIVE_ROWS,
            "observed": len(team_top),
            "expected": EXPECTED_TEAM_PERSPECTIVE_ROWS,
        },
        {
            "check_name": "concept_deduplication_reduces_rows",
            "passed": len(concept_audit) < len(packages),
            "observed": {
                "packages": len(packages),
                "unique_concepts": len(concept_audit),
            },
            "expected": "unique_concepts_less_than_packages",
        },
        {
            "check_name": "all_surviving_players_match_v4_market",
            "passed": unmatched_players.empty,
            "observed": unmatched_players["player_name"].tolist(),
            "expected": [],
        },
        {
            "check_name": "no_protected_players_in_routine_level_pool",
            "passed": not player_audit[
                "effective_protected_player_flag"
            ].fillna(False).astype(bool).any(),
            "observed": player_audit.loc[
                player_audit[
                    "effective_protected_player_flag"
                ].fillna(False).astype(bool),
                "player_name",
            ].tolist(),
            "expected": [],
        },
        {
            "check_name": "young_asset_review_queue_empty",
            "passed": young_review.empty,
            "observed": young_review[
                [
                    "player_name",
                    "team_abbreviation",
                    "young_asset_review_flags",
                ]
            ].to_dict(orient="records"),
            "expected": [],
        },
        {
            "check_name": "future_team_strength_available",
            "passed": team_strength_available,
            "observed": team_strength_source,
            "expected": str(TEAM_STRENGTH_PARQUET_PATH),
        },
        {
            "check_name": "team_roster_needs_available",
            "passed": team_needs_available,
            "observed": str(TEAM_NEEDS_PATH) if team_needs_available else "",
            "expected": str(TEAM_NEEDS_PATH),
        },
        {
            "check_name": "team_profiles_cover_30_teams",
            "passed": len(team_profiles) == 30,
            "observed": len(team_profiles),
            "expected": 30,
        },
        {
            "check_name": "final_team_strategy_score_not_released",
            "passed": True,
            "observed": False,
            "expected": False,
        },
    ]

    structural_checks = [
        row
        for row in validation_rows
        if row["check_name"]
        not in {
            "young_asset_review_queue_empty",
            "future_team_strength_available",
            "team_roster_needs_available",
            "team_profiles_cover_30_teams",
        }
    ]
    structural_valid = all(bool(row["passed"]) for row in structural_checks)
    strategy_ready = all(bool(row["passed"]) for row in validation_rows)

    print("[6/7] Writing audit artifacts")
    concept_audit.to_csv(CONCEPT_AUDIT_OUTPUT, index=False)
    player_audit.to_csv(PLAYER_AUDIT_OUTPUT, index=False)
    team_profiles.to_csv(TEAM_PROFILE_OUTPUT, index=False)
    team_concentration.to_csv(
        TEAM_CONCENTRATION_OUTPUT,
        index=False,
    )
    blockbuster_audit.to_csv(
        BLOCKBUSTER_AUDIT_OUTPUT,
        index=False,
    )
    pd.DataFrame(validation_rows).to_csv(
        VALIDATION_OUTPUT,
        index=False,
    )

    metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "structural_valid": structural_valid,
        "strategy_ready": strategy_ready,
        "quality_gate_source": str(QUALITY_METADATA_PATH),
        "player_market_source": player_market_source,
        "centralized_v4_market": str(
            PLAYER_MARKET_PARQUET_PATH
        ),
        "reviewed_override_players_in_v4_market": override_count,
        "generalized_rule_players_in_v4_market": generalized_rule_count,
        "team_strength_source": (
            team_strength_source
            if team_strength_available
            else None
        ),
        "team_needs_source": (
            str(TEAM_NEEDS_PATH)
            if team_needs_available
            else None
        ),
        "counts": {
            "routine_packages": len(routine),
            "minor_asset_packages": len(minor),
            "routine_level_packages": len(packages),
            "unique_player_exchange_concepts": len(concept_audit),
            "duplicate_pick_variant_rows": (
                len(packages) - len(concept_audit)
            ),
            "blockbuster_concepts": len(blockbusters),
            "surviving_unique_players": len(player_audit),
            "young_asset_review_candidates": int(
                player_audit[
                    "young_asset_review_required"
                ].sum()
            ),
            "team_profiles": len(team_profiles),
        },
        "young_asset_review_rules": YOUNG_ASSET_REVIEW_RULES,
        "scope_note": (
            "This V2 release consumes the centralized V4 protected-player market and audits readiness only. Young-asset flags are "
            "review candidates, not automatic protected-player decisions. "
            "Blockbusters remain concept-only. No final team-strategy score "
            "or recommendation is released."
        ),
        "outputs": {
            "concept_audit": str(CONCEPT_AUDIT_OUTPUT),
            "player_audit": str(PLAYER_AUDIT_OUTPUT),
            "team_profiles": str(TEAM_PROFILE_OUTPUT),
            "team_concentration": str(
                TEAM_CONCENTRATION_OUTPUT
            ),
            "blockbuster_audit": str(
                BLOCKBUSTER_AUDIT_OUTPUT
            ),
            "validation": str(VALIDATION_OUTPUT),
        },
    }
    METADATA_OUTPUT.write_text(
        json.dumps(json_safe(metadata), indent=2),
        encoding="utf-8",
    )

    print("[7/7] Complete")
    print(
        f"Validation: "
        f"{sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Structural valid: {structural_valid}")
    print(f"Strategy ready: {strategy_ready}")
    print(
        f"Routine-level packages: {len(packages):,} | "
        f"unique player-exchange concepts: {len(concept_audit):,} | "
        f"duplicate pick variants: {len(packages) - len(concept_audit):,}"
    )
    print(
        "Young-asset review candidates: "
        f"{int(player_audit['young_asset_review_required'].sum()):,}"
    )
    print("Final team strategy score released: False")

    return 0 if structural_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())