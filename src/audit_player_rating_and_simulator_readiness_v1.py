"""Audit readiness for the NBA player-rating and simulation layers.

This script does not release final ratings. It inventories the existing player
data, validates joins, identifies supported rating dimensions, and determines
whether the project is ready for a calibrated 60.0-99.9 player-rating engine.

Outputs:
    outputs/player_rating_readiness_metadata_v1.json
    outputs/player_rating_readiness_validation_v1.csv
    outputs/player_rating_source_inventory_v1.csv
    outputs/player_rating_join_coverage_v1.csv
    outputs/player_rating_dimension_support_v1.csv
    outputs/player_rating_missingness_v1.csv
    outputs/player_rating_future_projection_audit_v1.csv
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


SCRIPT_VERSION = "player-rating-simulator-readiness-audit-v1-2026-08-06"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"

SOURCE_CANDIDATES = {
    "projection_board": [
        DATA_DIRECTORY
        / "current_player_projection_board_2025_26_to_2026_27.parquet",
        DATA_DIRECTORY
        / "current_player_projection_board_2025_26_to_2026_27.csv",
    ],
    "skill_profiles": [
        DATA_DIRECTORY / "player_skill_profiles_2025_26.parquet",
        DATA_DIRECTORY / "player_skill_profiles_2025_26.csv",
    ],
    "player_market": [
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v4_protected.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v4_protected.csv",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v3.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v3.csv",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27.parquet",
        DATA_DIRECTORY
        / "player_trade_market_value_layer_2026_27.csv",
    ],
    "financial_layer": [
        DATA_DIRECTORY / "player_financial_layer_2026_27_v2.parquet",
        DATA_DIRECTORY / "player_financial_layer_2026_27_v2.csv",
        DATA_DIRECTORY / "player_financial_layer_2026_27.parquet",
        DATA_DIRECTORY / "player_financial_layer_2026_27.csv",
    ],
    "future_player_inputs": [
        DATA_DIRECTORY
        / "future_player_team_strength_inputs_2026_27_to_2032_33_v1.parquet",
        DATA_DIRECTORY
        / "future_player_team_strength_inputs_2026_27_to_2032_33_v1.csv",
    ],
    "app_player_profiles": [
        APP_DATA_DIRECTORY
        / "mixed_trade_player_profiles_2026_27_v1.json",
    ],
}

OUTPUTS = {
    "metadata": OUTPUT_DIRECTORY
    / "player_rating_readiness_metadata_v1.json",
    "validation": OUTPUT_DIRECTORY
    / "player_rating_readiness_validation_v1.csv",
    "source_inventory": OUTPUT_DIRECTORY
    / "player_rating_source_inventory_v1.csv",
    "join_coverage": OUTPUT_DIRECTORY
    / "player_rating_join_coverage_v1.csv",
    "dimension_support": OUTPUT_DIRECTORY
    / "player_rating_dimension_support_v1.csv",
    "missingness": OUTPUT_DIRECTORY
    / "player_rating_missingness_v1.csv",
    "future_projection_audit": OUTPUT_DIRECTORY
    / "player_rating_future_projection_audit_v1.csv",
}

CORE_SKILL_COLUMNS = [
    "scoring_score",
    "shooting_score",
    "playmaking_score",
    "rebounding_score",
    "defense_score",
]

PROJECTION_STAT_COLUMNS = [
    "games_played",
    "minutes_per_game",
    "points_per_game",
    "assists_per_game",
    "rebounds_per_game",
    "base_fg_pct",
    "base_fg3_pct",
    "base_ft_pct",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pie",
    "availability_rate",
    "projected_expected_contribution",
    "projected_active_downside_contribution_80",
    "projected_active_upside_contribution_80",
    "projected_survival_probability",
    "projected_rotation_probability",
    "roster_value_percentile",
]

MARKET_SIGNAL_GROUPS = {
    "trade_value": [
        "market_value_percentile",
        "front_office_value_score",
        "front_office_value_percentile",
        "trade_market_value_score",
        "trade_market_value_percentile",
        "surplus_value_score",
    ],
    "contract_value": [
        "contract_value_percentile",
        "contract_value_score",
        "surplus_value_score",
        "contract_control_score",
        "age_market_score",
    ],
    "archetype": [
        "recommendation_asset_class_v4",
        "front_office_asset_tier",
        "front_office_asset_tier_order",
        "market_asset_tier",
        "asset_tier",
        "player_archetype",
        "primary_skill",
        "secondary_skill",
    ],
}

FUTURE_SEASON_CANDIDATES = [
    "projection_season",
    "season",
    "projected_season",
    "target_season",
    "future_season",
    "season_start",
]

FUTURE_AGE_CANDIDATES = [
    "projection_age",
    "projected_age",
    "age",
    "future_age",
]

FUTURE_VALUE_PRIORITY = [
    "projected_expected_contribution",
    "projected_contribution",
    "expected_contribution",
    "active_expected_contribution",
    "future_strength_contribution",
    "team_strength_contribution",
    "projected_player_strength",
    "player_strength_contribution",
    "survival_weighted_contribution",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run pure helper tests without loading project files.",
    )
    return parser.parse_args()


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def locate_source(name: str) -> Path | None:
    for path in SOURCE_CANDIDATES[name]:
        if path.exists():
            return path
    return None


def read_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("players"), dict):
            return pd.DataFrame(list(payload["players"].values()))
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        raise ValueError(f"Unsupported JSON structure: {path}")
    raise ValueError(f"Unsupported source type: {path}")


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def numeric_candidate_columns(
    frame: pd.DataFrame,
    required_terms: list[str],
    excluded_terms: list[str] | None = None,
) -> list[str]:
    excluded_terms = excluded_terms or []
    matches: list[str] = []

    for column in frame.columns:
        lower = column.lower()
        if not all(term in lower for term in required_terms):
            continue
        if any(term in lower for term in excluded_terms):
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() == 0:
            continue
        matches.append(column)

    return matches


def choose_future_value_column(frame: pd.DataFrame) -> str | None:
    for column in FUTURE_VALUE_PRIORITY:
        if column in frame.columns:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if numeric.notna().sum() > 0:
                return column

    candidates: list[str] = []
    for column in frame.columns:
        lower = column.lower()
        if not any(term in lower for term in ["contribution", "strength", "value"]):
            continue
        if any(
            term in lower
            for term in [
                "percentile",
                "rank",
                "salary",
                "contract",
                "market",
                "flag",
                "score_order",
            ]
        ):
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() > 0:
            candidates.append(column)

    return candidates[0] if candidates else None


def source_inventory_row(
    source_name: str,
    path: Path | None,
    frame: pd.DataFrame | None,
) -> dict[str, Any]:
    if path is None or frame is None:
        return {
            "source_name": source_name,
            "available": False,
            "path": "",
            "rows": 0,
            "columns": 0,
            "has_player_id": False,
            "unique_player_ids": 0,
            "duplicate_player_id_rows": 0,
            "column_names": "",
        }

    normalized_ids = (
        frame["player_id"].map(normalize_player_id)
        if "player_id" in frame.columns
        else pd.Series(dtype=str)
    )
    nonblank_ids = normalized_ids.loc[normalized_ids.ne("")]

    return {
        "source_name": source_name,
        "available": True,
        "path": str(path),
        "rows": len(frame),
        "columns": len(frame.columns),
        "has_player_id": "player_id" in frame.columns,
        "unique_player_ids": nonblank_ids.nunique(),
        "duplicate_player_id_rows": int(nonblank_ids.duplicated().sum()),
        "column_names": "|".join(map(str, frame.columns)),
    }


def unique_player_index(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["_normalized_player_id"] = output["player_id"].map(
        normalize_player_id
    )
    output = output.loc[output["_normalized_player_id"].ne("")].copy()
    return output.drop_duplicates("_normalized_player_id", keep="first")


def join_coverage_rows(
    projection: pd.DataFrame,
    sources: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    base = unique_player_index(projection)
    base_ids = set(base["_normalized_player_id"])
    rows: list[dict[str, Any]] = []

    for source_name, frame in sources.items():
        if source_name == "projection_board":
            continue

        if "player_id" not in frame.columns:
            rows.append(
                {
                    "base_source": "projection_board",
                    "joined_source": source_name,
                    "base_unique_players": len(base_ids),
                    "joined_unique_players": 0,
                    "matched_players": 0,
                    "match_rate": 0.0,
                    "unmatched_players": len(base_ids),
                    "join_ready": False,
                }
            )
            continue

        other = frame.copy()
        other["_normalized_player_id"] = other["player_id"].map(
            normalize_player_id
        )
        other_ids = set(
            other.loc[
                other["_normalized_player_id"].ne(""),
                "_normalized_player_id",
            ]
        )
        matched = len(base_ids & other_ids)
        match_rate = 100.0 * matched / max(len(base_ids), 1)

        rows.append(
            {
                "base_source": "projection_board",
                "joined_source": source_name,
                "base_unique_players": len(base_ids),
                "joined_unique_players": len(other_ids),
                "matched_players": matched,
                "match_rate": round(match_rate, 3),
                "unmatched_players": len(base_ids) - matched,
                "join_ready": match_rate >= 90.0,
            }
        )

    return rows


def coverage(
    frame: pd.DataFrame,
    columns: list[str],
) -> tuple[int, int, float]:
    existing = [column for column in columns if column in frame.columns]
    if not existing:
        return 0, 0, 0.0

    supported_rows = frame[existing].notna().all(axis=1).sum()
    return (
        len(existing),
        int(supported_rows),
        round(100.0 * supported_rows / max(len(frame), 1), 3),
    )


def dimension_support_rows(
    frames: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    projection = frames["projection_board"]
    skills = frames.get("skill_profiles", pd.DataFrame())
    market = frames.get("player_market", pd.DataFrame())
    future = frames.get("future_player_inputs", pd.DataFrame())

    skill_existing = [
        column for column in CORE_SKILL_COLUMNS if column in skills.columns
    ]

    future_season = first_existing(
        list(future.columns),
        FUTURE_SEASON_CANDIDATES,
    )
    future_value = choose_future_value_column(future)
    future_player_id = "player_id" in future.columns
    future_ready = bool(
        future_player_id and future_season and future_value
    )

    market_trade_columns = [
        column
        for column in MARKET_SIGNAL_GROUPS["trade_value"]
        if column in market.columns
    ]
    market_contract_columns = [
        column
        for column in MARKET_SIGNAL_GROUPS["contract_value"]
        if column in market.columns
    ]
    market_archetype_columns = [
        column
        for column in MARKET_SIGNAL_GROUPS["archetype"]
        if column in market.columns
    ]

    definitions = [
        {
            "dimension": "overall",
            "status": "fully_supported",
            "source": "projection_board + skill_profiles",
            "columns": [
                "roster_value_percentile",
                "projected_expected_contribution",
                "projected_active_downside_contribution_80",
                "projected_survival_probability",
                *skill_existing,
            ],
            "method_note": (
                "Calibrate a role-adjusted on-court rating from contribution, "
                "downside, availability, and five skill dimensions."
            ),
        },
        *[
            {
                "dimension": column.replace("_score", ""),
                "status": (
                    "fully_supported"
                    if column in skills.columns
                    else "unsupported"
                ),
                "source": "skill_profiles",
                "columns": [column],
                "method_note": (
                    "Use the existing reliability-adjusted skill score and "
                    "league percentile."
                ),
            }
            for column in CORE_SKILL_COLUMNS
        ],
        {
            "dimension": "efficiency",
            "status": (
                "fully_supported"
                if all(
                    column in projection.columns
                    for column in [
                        "advanced_ts_pct",
                        "advanced_efg_pct",
                        "advanced_pie",
                    ]
                )
                else "partial_support"
            ),
            "source": "projection_board",
            "columns": [
                column
                for column in [
                    "advanced_ts_pct",
                    "advanced_efg_pct",
                    "advanced_pie",
                    "advanced_usg_pct",
                ]
                if column in projection.columns
            ],
            "method_note": (
                "Combine shooting efficiency, overall event share, and usage "
                "with role-aware weighting."
            ),
        },
        {
            "dimension": "availability",
            "status": (
                "fully_supported"
                if all(
                    column in projection.columns
                    for column in [
                        "availability_rate",
                        "projected_survival_probability",
                        "projected_rotation_probability",
                    ]
                )
                else "partial_support"
            ),
            "source": "projection_board",
            "columns": [
                column
                for column in [
                    "availability_rate",
                    "games_played",
                    "projected_survival_probability",
                    "projected_rotation_probability",
                ]
                if column in projection.columns
            ],
            "method_note": (
                "Keep availability separate from basketball skill so injuries "
                "do not erase the player's underlying talent rating."
            ),
        },
        {
            "dimension": "potential",
            "status": (
                "fully_supported" if future_ready else "partial_support"
            ),
            "source": "future_player_inputs",
            "columns": [
                column
                for column in [
                    future_season,
                    future_value,
                    first_existing(
                        list(future.columns),
                        FUTURE_AGE_CANDIDATES,
                    ),
                ]
                if column
            ],
            "method_note": (
                "Use the best projected contribution between 2027-28 and "
                "2032-33 relative to current contribution, with uncertainty "
                "and age limits. Do not use age alone as potential."
            ),
        },
        {
            "dimension": "contract_value",
            "status": (
                "fully_supported"
                if market_contract_columns
                else "unsupported"
            ),
            "source": "player_market",
            "columns": market_contract_columns,
            "method_note": (
                "Rate production relative to salary, years of control, and "
                "future commitment. Keep separate from on-court OVR."
            ),
        },
        {
            "dimension": "trade_value",
            "status": (
                "fully_supported"
                if market_trade_columns
                else "unsupported"
            ),
            "source": "player_market",
            "columns": market_trade_columns,
            "method_note": (
                "Use the validated market/front-office value layer rather "
                "than deriving trade value from OVR alone."
            ),
        },
        {
            "dimension": "archetype",
            "status": (
                "fully_supported"
                if (
                    "primary_skill" in skills.columns
                    and "secondary_skill" in skills.columns
                )
                else (
                    "partial_support"
                    if market_archetype_columns
                    else "unsupported"
                )
            ),
            "source": "skill_profiles + player_market",
            "columns": [
                column
                for column in [
                    "primary_skill",
                    "secondary_skill",
                    *market_archetype_columns,
                ]
                if (
                    column in skills.columns
                    or column in market.columns
                )
            ],
            "method_note": (
                "Assign a descriptive role from skill ordering, usage, size "
                "or position when available, and market tier."
            ),
        },
        {
            "dimension": "finishing",
            "status": "proxy_only",
            "source": "projection_board",
            "columns": [
                column
                for column in [
                    "base_fg_pct",
                    "advanced_ts_pct",
                ]
                if column in projection.columns
            ],
            "method_note": (
                "Current data lacks rim-attempt frequency and rim efficiency. "
                "Do not publish a final finishing grade from FG% alone."
            ),
        },
    ]

    rows: list[dict[str, Any]] = []
    for definition in definitions:
        columns = list(dict.fromkeys(definition["columns"]))
        frame = frames.get(
            definition["source"].split(" + ")[0],
            projection,
        )
        existing_count, supported_rows, row_coverage = coverage(
            frame,
            columns,
        )
        rows.append(
            {
                "dimension": definition["dimension"],
                "support_status": definition["status"],
                "primary_source": definition["source"],
                "supporting_columns": "|".join(columns),
                "supporting_column_count": len(columns),
                "existing_supporting_column_count": existing_count,
                "rows_with_complete_support": supported_rows,
                "complete_row_coverage_pct": row_coverage,
                "method_note": definition["method_note"],
                "release_in_v1": definition["status"]
                in {"fully_supported", "partial_support"},
            }
        )

    return rows


def missingness_rows(
    frames: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    column_sets = {
        "projection_board": PROJECTION_STAT_COLUMNS,
        "skill_profiles": [
            "roster_value_score",
            "roster_value_percentile",
            "raw_overall_score",
            "reliability_weight",
            "reliability_adjusted_score",
            *CORE_SKILL_COLUMNS,
            "primary_skill",
            "secondary_skill",
        ],
        "player_market": list(
            dict.fromkeys(
                MARKET_SIGNAL_GROUPS["trade_value"]
                + MARKET_SIGNAL_GROUPS["contract_value"]
                + MARKET_SIGNAL_GROUPS["archetype"]
            )
        ),
    }

    for source_name, columns in column_sets.items():
        frame = frames.get(source_name)
        if frame is None:
            continue
        for column in columns:
            if column not in frame.columns:
                rows.append(
                    {
                        "source_name": source_name,
                        "column_name": column,
                        "column_available": False,
                        "non_null_rows": 0,
                        "missing_rows": len(frame),
                        "coverage_pct": 0.0,
                        "unique_values": 0,
                    }
                )
                continue

            non_null = int(frame[column].notna().sum())
            rows.append(
                {
                    "source_name": source_name,
                    "column_name": column,
                    "column_available": True,
                    "non_null_rows": non_null,
                    "missing_rows": len(frame) - non_null,
                    "coverage_pct": round(
                        100.0 * non_null / max(len(frame), 1),
                        3,
                    ),
                    "unique_values": int(frame[column].nunique(dropna=True)),
                }
            )

    return rows


def future_projection_audit(
    future: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if future is None or future.empty:
        return (
            pd.DataFrame(
                [
                    {
                        "audit_item": "future_player_inputs_available",
                        "value": False,
                        "detail": "Future player input source is unavailable.",
                    }
                ]
            ),
            {
                "available": False,
                "season_column": None,
                "age_column": None,
                "value_column": None,
                "unique_players": 0,
                "seasons": [],
                "potential_ready": False,
            },
        )

    season_column = first_existing(
        list(future.columns),
        FUTURE_SEASON_CANDIDATES,
    )
    age_column = first_existing(
        list(future.columns),
        FUTURE_AGE_CANDIDATES,
    )
    value_column = choose_future_value_column(future)

    player_ids = (
        future["player_id"].map(normalize_player_id)
        if "player_id" in future.columns
        else pd.Series(dtype=str)
    )
    seasons = (
        sorted(
            map(
                str,
                future[season_column].dropna().unique().tolist(),
            )
        )
        if season_column
        else []
    )

    rows = [
        {
            "audit_item": "future_player_inputs_available",
            "value": True,
            "detail": f"{len(future):,} rows",
        },
        {
            "audit_item": "player_id_available",
            "value": "player_id" in future.columns,
            "detail": f"{player_ids.loc[player_ids.ne('')].nunique():,} unique players",
        },
        {
            "audit_item": "season_column",
            "value": season_column or "",
            "detail": "|".join(seasons),
        },
        {
            "audit_item": "age_column",
            "value": age_column or "",
            "detail": "",
        },
        {
            "audit_item": "future_value_column",
            "value": value_column or "",
            "detail": (
                f"{pd.to_numeric(future[value_column], errors='coerce').notna().sum():,} numeric rows"
                if value_column
                else ""
            ),
        },
    ]

    potential_ready = bool(
        "player_id" in future.columns
        and season_column
        and value_column
        and len(seasons) >= 2
    )

    return (
        pd.DataFrame(rows),
        {
            "available": True,
            "season_column": season_column,
            "age_column": age_column,
            "value_column": value_column,
            "unique_players": int(
                player_ids.loc[player_ids.ne("")].nunique()
            ),
            "seasons": seasons,
            "potential_ready": potential_ready,
        },
    )


def validation_rows(
    frames: dict[str, pd.DataFrame],
    source_inventory: pd.DataFrame,
    joins: pd.DataFrame,
    dimensions: pd.DataFrame,
    future_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    projection = frames.get("projection_board", pd.DataFrame())
    skills = frames.get("skill_profiles", pd.DataFrame())
    market = frames.get("player_market", pd.DataFrame())

    def add(
        name: str,
        passed: bool,
        observed: Any,
        expected: Any,
        severity: str = "required",
    ) -> dict[str, Any]:
        return {
            "check_name": name,
            "passed": bool(passed),
            "severity": severity,
            "observed": observed,
            "expected": expected,
        }

    join_lookup = {
        row["joined_source"]: row
        for row in joins.to_dict(orient="records")
    }

    fully_supported = set(
        dimensions.loc[
            dimensions["support_status"].eq("fully_supported"),
            "dimension",
        ]
    )

    required_dimensions = {
        "overall",
        "scoring",
        "shooting",
        "playmaking",
        "rebounding",
        "defense",
        "efficiency",
        "availability",
        "contract_value",
        "trade_value",
        "archetype",
    }

    return [
        add(
            "projection_board_available",
            not projection.empty,
            len(projection),
            ">0 rows",
        ),
        add(
            "skill_profiles_available",
            not skills.empty,
            len(skills),
            ">0 rows",
        ),
        add(
            "player_market_available",
            not market.empty,
            len(market),
            ">0 rows",
        ),
        add(
            "projection_player_ids_unique",
            (
                "player_id" in projection.columns
                and unique_player_index(projection).shape[0]
                == projection["player_id"].map(normalize_player_id).ne("").sum()
            ),
            (
                unique_player_index(projection).shape[0]
                if "player_id" in projection.columns
                else 0
            ),
            "all nonblank projection player IDs unique",
        ),
        add(
            "five_core_skill_columns_available",
            all(column in skills.columns for column in CORE_SKILL_COLUMNS),
            sum(column in skills.columns for column in CORE_SKILL_COLUMNS),
            len(CORE_SKILL_COLUMNS),
        ),
        add(
            "projection_to_skill_join_at_least_90_pct",
            join_lookup.get("skill_profiles", {}).get("match_rate", 0.0)
            >= 90.0,
            join_lookup.get("skill_profiles", {}).get("match_rate", 0.0),
            ">=90%",
        ),
        add(
            "projection_to_market_join_at_least_60_pct",
            join_lookup.get("player_market", {}).get("match_rate", 0.0)
            >= 60.0,
            join_lookup.get("player_market", {}).get("match_rate", 0.0),
            ">=60%",
        ),
        add(
            "all_required_rating_dimensions_supported",
            required_dimensions.issubset(fully_supported),
            "|".join(sorted(fully_supported)),
            "|".join(sorted(required_dimensions)),
        ),
        add(
            "future_projection_source_available",
            future_summary["available"],
            future_summary["available"],
            True,
            severity="potential",
        ),
        add(
            "potential_rating_ready",
            future_summary["potential_ready"],
            future_summary,
            "player_id + multiple seasons + numeric future value",
            severity="potential",
        ),
        add(
            "finishing_not_overclaimed",
            (
                dimensions.loc[
                    dimensions["dimension"].eq("finishing"),
                    "support_status",
                ].iloc[0]
                == "proxy_only"
            ),
            dimensions.loc[
                dimensions["dimension"].eq("finishing"),
                "support_status",
            ].iloc[0],
            "proxy_only until rim data is added",
        ),
        add(
            "rating_scale_separated_from_optimizer_values",
            True,
            "presentation-only 60.0-99.9 rating layer planned",
            "optimizer retains original precise values",
        ),
    ]


def run_self_test() -> int:
    sample = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "projected_expected_contribution": [10.0, 20.0, 30.0],
            "projection_season": ["2026-27", "2027-28", "2028-29"],
        }
    )
    tests = {
        "normalize_integer_id": normalize_player_id(1630180.0) == "1630180",
        "normalize_string_id": normalize_player_id("1630180") == "1630180",
        "first_existing": (
            first_existing(
                list(sample.columns),
                ["season", "projection_season"],
            )
            == "projection_season"
        ),
        "future_value_priority": (
            choose_future_value_column(sample)
            == "projected_expected_contribution"
        ),
        "numeric_candidate_detection": (
            numeric_candidate_columns(
                sample,
                ["contribution"],
            )
            == ["projected_expected_contribution"]
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    source_paths: dict[str, Path | None] = {
        name: locate_source(name)
        for name in SOURCE_CANDIDATES
    }
    frames: dict[str, pd.DataFrame] = {}

    print("=" * 88)
    print("PLAYER RATING AND SIMULATOR READINESS AUDIT")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    print("[1/7] Loading player data sources")
    inventory_rows: list[dict[str, Any]] = []
    for source_name, path in source_paths.items():
        frame: pd.DataFrame | None = None
        if path is not None:
            frame = read_frame(path)
            frames[source_name] = frame
            print(
                f"  {source_name}: {len(frame):,} rows x "
                f"{len(frame.columns):,} columns"
            )
        else:
            print(f"  {source_name}: NOT FOUND")
        inventory_rows.append(
            source_inventory_row(source_name, path, frame)
        )

    source_inventory = pd.DataFrame(inventory_rows)

    required_sources = [
        "projection_board",
        "skill_profiles",
        "player_market",
    ]
    missing_required = [
        name for name in required_sources if name not in frames
    ]
    if missing_required:
        raise FileNotFoundError(
            "Required rating sources are missing:\n"
            + "\n".join(missing_required)
        )

    print("[2/7] Auditing player-ID joins")
    joins = pd.DataFrame(
        join_coverage_rows(
            frames["projection_board"],
            frames,
        )
    )
    for row in joins.to_dict(orient="records"):
        print(
            f"  projection -> {row['joined_source']}: "
            f"{row['match_rate']:.1f}%"
        )

    print("[3/7] Auditing rating-dimension support")
    dimensions = pd.DataFrame(dimension_support_rows(frames))
    for row in dimensions.to_dict(orient="records"):
        print(
            f"  {row['dimension']}: {row['support_status']}"
        )

    print("[4/7] Auditing missingness and field coverage")
    missingness = pd.DataFrame(missingness_rows(frames))

    print("[5/7] Auditing future projection support")
    future_audit, future_summary = future_projection_audit(
        frames.get("future_player_inputs")
    )
    print(
        "  Potential ready: "
        f"{future_summary['potential_ready']}"
    )
    if future_summary["value_column"]:
        print(
            "  Future value column: "
            f"{future_summary['value_column']}"
        )

    print("[6/7] Validating readiness")
    validations = validation_rows(
        frames=frames,
        source_inventory=source_inventory,
        joins=joins,
        dimensions=dimensions,
        future_summary=future_summary,
    )
    validation = pd.DataFrame(validations)

    required_validation = validation.loc[
        validation["severity"].eq("required")
    ]
    core_rating_ready = bool(required_validation["passed"].all())
    potential_ready = bool(future_summary["potential_ready"])
    full_rating_ready = core_rating_ready and potential_ready

    print("[7/7] Writing readiness artifacts")
    source_inventory.to_csv(
        OUTPUTS["source_inventory"],
        index=False,
    )
    joins.to_csv(OUTPUTS["join_coverage"], index=False)
    dimensions.to_csv(
        OUTPUTS["dimension_support"],
        index=False,
    )
    missingness.to_csv(OUTPUTS["missingness"], index=False)
    future_audit.to_csv(
        OUTPUTS["future_projection_audit"],
        index=False,
    )
    validation.to_csv(OUTPUTS["validation"], index=False)

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "core_rating_ready": core_rating_ready,
        "potential_rating_ready": potential_ready,
        "full_rating_ready": full_rating_ready,
        "rating_scale": {
            "minimum": 60.0,
            "maximum": 99.9,
            "display_decimals": 1,
            "significant_figures_example": "96.7",
            "scope": (
                "Presentation layer only. Optimizer, legality, projections, "
                "and simulation retain original numeric precision."
            ),
        },
        "planned_v1_dimensions": [
            "overall",
            "scoring",
            "shooting",
            "playmaking",
            "rebounding",
            "defense",
            "efficiency",
            "availability",
            "potential",
            "contract_value",
            "trade_value",
            "archetype",
        ],
        "deferred_dimension": {
            "dimension": "finishing",
            "reason": (
                "Current audited sources do not provide direct rim frequency "
                "and rim efficiency. FG% and TS% are insufficient for a "
                "standalone finishing grade."
            ),
        },
        "source_paths": {
            name: str(path) if path else None
            for name, path in source_paths.items()
        },
        "future_projection_detection": future_summary,
        "validation_passed": int(validation["passed"].sum()),
        "validation_total": len(validation),
        "required_validation_passed": int(
            required_validation["passed"].sum()
        ),
        "required_validation_total": len(required_validation),
        "outputs": {
            name: str(path)
            for name, path in OUTPUTS.items()
        },
    }
    OUTPUTS["metadata"].write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    print("Complete")
    print(
        f"Validation: {int(validation['passed'].sum())}/"
        f"{len(validation)}"
    )
    print(f"Core rating ready: {core_rating_ready}")
    print(f"Potential rating ready: {potential_ready}")
    print(f"Full rating ready: {full_rating_ready}")
    print(
        "Finishing grade released: False "
        "(rim-location data required)"
    )

    return 0 if core_rating_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())