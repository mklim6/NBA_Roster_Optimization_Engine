"""Evaluate final deterministic CBA legality for mixed player-and-pick packages.

Save this script in the project's ``src`` directory. It reads the V8
player-CBA-evidence package parquets produced by
``propagate_mixed_player_pick_player_cba_evidence_to_packages_v1.py``.

The evaluator:

* preserves every V8 column, except that it intentionally releases the existing
  ``optimizer_package_final_legal`` and ``optimizer_package_legality_status``
  fields in the new V9 outputs;
* uses verified player outgoing and receiving-side matching salaries;
* recalculates simultaneous trade matching under the 2023 NBA-NBPA CBA;
* enforces the official 2026-27 salary cap, first apron, second apron, existing
  hard caps, aggregation restrictions, and offseason roster limits;
* forbids cash and banked trade-exception mechanisms by conservative policy;
* fails closed to manual review whenever the V8 evidence is insufficient for a
  deterministic decision.

This is an analytical compliance screen, not an NBA transaction approval.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_VERSION = "mixed-player-pick-final-full-cba-evaluator-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_final_full_cba_legality_2026_27_v1"

TRADE_DATE = "2026-08-04"
LEAGUE_YEAR = "2026-27"

# Official NBA 2026-27 levels announced June 30, 2026.
SALARY_CAP = 164_961_000.0
MINIMUM_TEAM_SALARY = 148_465_000.0
TAX_LEVEL = 200_428_000.0
FIRST_APRON = 209_015_000.0
SECOND_APRON = 221_686_000.0

# The Expanded Traded Player Exception uses $7.5M scaled by the ratio of the
# current cap to the 2023-24 Salary Cap.
SALARY_CAP_2023_24 = 136_021_000.0
EXPANDED_TPE_SCALED_ADD = 7_500_000.0 * SALARY_CAP / SALARY_CAP_2023_24
TPE_ALLOWANCE = 250_000.0
MONEY_TOLERANCE = 1.0

OFFSEASON_TOTAL_ROSTER_MAX = 21
TWO_WAY_ROSTER_MAX = 3

CAP_SOURCE_URL = "https://www.nba.com/news/nba-salary-cap-2026-27-season"
CBA_SOURCE_URL = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)

INPUT_FILES = {
    "one_for_one": (
        "one_for_one_mixed_player_pick_candidates_2026_27_"
        "v8_player_cba_evidence_evaluated.parquet"
    ),
    "two_for_one": (
        "two_for_one_mixed_player_pick_candidates_2026_27_"
        "v8_player_cba_evidence_evaluated.parquet"
    ),
}
OUTPUT_FILES = {
    "one_for_one": (
        "one_for_one_mixed_player_pick_candidates_2026_27_"
        "v9_final_full_cba_evaluated.parquet"
    ),
    "two_for_one": (
        "two_for_one_mixed_player_pick_candidates_2026_27_"
        "v9_final_full_cba_evaluated.parquet"
    ),
}

EXPECTED_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_INPUT_COLUMNS = {"one_for_one": 206, "two_for_one": 204}
EXPECTED_PLAYER_STAGE = {
    "one_for_one": {"passed": 5_164, "manual": 11_050, "blocked": 12_110},
    "two_for_one": {"passed": 19_012, "manual": 62_134, "blocked": 201_131},
}
EXPECTED_GLOBAL_PLAYER_STAGE = {
    "rows": 310_601,
    "passed": 24_176,
    "manual": 73_184,
    "blocked": 213_241,
}

SUMMARY_FILENAME = "mixed_player_pick_final_full_cba_summary_v1.csv"
ISSUE_SUMMARY_FILENAME = "mixed_player_pick_final_full_cba_issue_summary_v1.csv"
ROUTE_SUMMARY_FILENAME = "mixed_player_pick_final_full_cba_route_summary_v1.csv"
VALIDATION_FILENAME = "mixed_player_pick_final_full_cba_validation_v1.csv"
METADATA_FILENAME = "mixed_player_pick_final_full_cba_metadata_v1.json"
RULES_FILENAME = "mixed_player_pick_final_full_cba_rules_v1.json"

PACKAGE_REQUIRED_COLUMNS = {
    "optimizer_candidate_id",
    "optimizer_package_final_legal",
    "optimizer_package_legality_status",
    "team_a",
    "team_b",
    "side_a_player_trade_salary",
    "side_b_player_trade_salary",
    "package_player_cba_stage_passed",
    "package_player_cba_manual_review_required",
    "package_player_cba_blocked",
    "package_player_cba_status",
    "player_cba_decisions_matched",
    "player_cba_asymmetric_salary_treatment_required",
    "package_player_cba_aggregation_blocked",
    "package_player_cba_consent_required",
    "package_player_cba_trade_bonus_review_required",
    "side_a_player_cba_player_count",
    "side_b_player_cba_player_count",
    "side_a_player_cba_decisions_matched",
    "side_b_player_cba_decisions_matched",
    "side_a_player_cba_verified_outgoing_salary",
    "side_b_player_cba_verified_outgoing_salary",
    "side_a_player_cba_verified_incoming_salary_for_opponent",
    "side_b_player_cba_verified_incoming_salary_for_opponent",
    "side_a_player_cba_base_year_compensation_count",
    "side_b_player_cba_base_year_compensation_count",
    "side_a_player_cba_trade_bonus_active_count",
    "side_b_player_cba_trade_bonus_active_count",
    "side_a_player_cba_consent_required_count",
    "side_b_player_cba_consent_required_count",
    "side_a_player_cba_sign_and_trade_count",
    "side_b_player_cba_sign_and_trade_count",
    "side_a_player_cba_two_way_contract_count",
    "side_b_player_cba_two_way_contract_count",
    "team_a_verified_team_salary_value",
    "team_b_verified_team_salary_value",
    "team_a_verified_apron_team_salary_value",
    "team_b_verified_apron_team_salary_value",
    "team_a_verified_cap_room_value",
    "team_b_verified_cap_room_value",
    "team_a_hard_cap_active",
    "team_b_hard_cap_active",
    "team_a_hard_cap_level",
    "team_b_hard_cap_level",
    "team_a_aggregation_allowed",
    "team_b_aggregation_allowed",
    "team_a_standard_contract_count",
    "team_b_standard_contract_count",
    "team_a_two_way_contract_count",
    "team_b_two_way_contract_count",
    "team_a_cba_stage_pass",
    "team_b_cba_stage_pass",
    "team_a_cba_manual_review_required",
    "team_b_cba_manual_review_required",
    "package_team_cba_evidence_stage_passed",
    "package_team_cba_evidence_manual_review_required",
    "package_team_cba_evidence_blocked",
    "package_right_legality_stage_passed",
    "package_right_legality_manual_review_required",
    "package_right_legality_blocked",
}

SIDE_SUFFIXES = [
    "outgoing_salary",
    "incoming_salary_for_matching",
    "incoming_actual_team_salary",
    "posttrade_team_salary",
    "posttrade_apron_team_salary",
    "outgoing_player_count",
    "incoming_player_count",
    "posttrade_standard_contract_count",
    "posttrade_two_way_contract_count",
    "posttrade_total_roster_count",
    "salary_matching_route",
    "salary_matching_max_incoming",
    "salary_matching_margin",
    "salary_matching_passed",
    "aggregation_passed",
    "roster_passed",
    "existing_hard_cap_passed",
    "hard_cap_level_after_trade",
    "hard_cap_passed",
    "evidence_missing",
    "issue",
]

PACKAGE_APPENDED_COLUMNS = [
    "optimizer_package_final_legal_before_full_cba",
    "optimizer_package_legality_status_before_full_cba",
    "full_cba_trade_date",
    "full_cba_league_year",
    "full_cba_salary_cap",
    "full_cba_tax_level",
    "full_cba_first_apron",
    "full_cba_second_apron",
    "full_cba_cash_consideration_used",
    "full_cba_banked_trade_exception_used",
    "full_cba_player_detail_manual_review_required",
    "full_cba_evidence_complete",
    "full_cba_salary_matching_passed",
    "full_cba_aggregation_passed",
    "full_cba_roster_passed",
    "full_cba_hard_cap_passed",
    "full_cba_deterministic_legal",
    "full_cba_manual_review_required",
    "full_cba_blocked",
    "full_cba_status",
    "full_cba_deterministic_status_released",
    "full_cba_rules_release",
    "full_cba_evaluator_version",
]
APPENDED_COLUMNS = [
    *(f"team_a_final_cba_{suffix}" for suffix in SIDE_SUFFIXES),
    *(f"team_b_final_cba_{suffix}" for suffix in SIDE_SUFFIXES),
    *PACKAGE_APPENDED_COLUMNS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help="Project root. Defaults to the parent of src when saved in src.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free rules tests without reading project files.",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Evaluate and write audit CSV/JSON outputs without writing V9 parquets.",
    )
    return parser.parse_args()


def project_root(explicit_root: Path | None = None) -> Path:
    if explicit_root is not None:
        return explicit_root.expanduser().resolve()
    script = Path(__file__).resolve()
    return script.parent.parent if script.parent.name.lower() == "src" else script.parent


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


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def value_counts_map(frame: Any, column: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in frame.group_by(column).len().to_dicts():
        key = "<null>" if row[column] is None else str(row[column])
        result[key] = int(row["len"])
    return dict(sorted(result.items()))


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


def pure_expanded_tpe_max(outgoing: float) -> float:
    y = min(
        2.0 * outgoing + TPE_ALLOWANCE,
        outgoing + EXPANDED_TPE_SCALED_ADD,
    )
    z = 1.25 * outgoing + TPE_ALLOWANCE
    return max(y, z)


def pure_route(
    *,
    pre_team_salary: float,
    pre_apron_salary: float,
    outgoing: float,
    incoming_matching: float,
    incoming_actual: float,
    outgoing_count: int,
    aggregation_policy_blocked: bool,
) -> tuple[str, float]:
    post_apron = pre_apron_salary - outgoing + incoming_actual
    allowance = 0.0 if post_apron > FIRST_APRON + MONEY_TOLERANCE else TPE_ALLOWANCE
    under_cap = pre_team_salary < SALARY_CAP - MONEY_TOLERANCE

    room_after_outgoing = max(0.0, SALARY_CAP - (pre_team_salary - outgoing))
    room_max = room_after_outgoing + allowance
    standard_max = outgoing + allowance
    expanded_max = pure_expanded_tpe_max(outgoing)

    candidates: list[tuple[str, float]] = []
    if under_cap and incoming_matching <= room_max + MONEY_TOLERANCE:
        candidates.append(("room_under_cap", room_max))
    if (
        not under_cap
        and outgoing_count == 1
        and incoming_matching <= standard_max + MONEY_TOLERANCE
    ):
        candidates.append(("standard_tpe", standard_max))
    if (
        not under_cap
        and outgoing_count >= 2
        and not aggregation_policy_blocked
        and post_apron <= SECOND_APRON + MONEY_TOLERANCE
        and incoming_matching <= standard_max + MONEY_TOLERANCE
    ):
        candidates.append(("aggregated_standard_tpe", standard_max))
    if (
        (outgoing_count == 1 or not aggregation_policy_blocked)
        and post_apron <= FIRST_APRON + MONEY_TOLERANCE
        and incoming_matching <= expanded_max + MONEY_TOLERANCE
    ):
        candidates.append(("expanded_tpe", expanded_max))

    return candidates[0] if candidates else ("none", max(room_max, standard_max, expanded_max))


def pure_final_status(
    *,
    prior_passed: bool,
    prior_manual: bool,
    prior_blocked: bool,
    evidence_missing: bool,
    player_detail_manual: bool,
    side_a_passed: bool,
    side_b_passed: bool,
) -> tuple[bool, bool, bool]:
    prior_inconsistent = not (prior_passed or prior_manual or prior_blocked)
    manual = prior_manual or prior_inconsistent or (
        prior_passed and (evidence_missing or player_detail_manual)
    )
    blocked = prior_blocked or (
        prior_passed
        and not evidence_missing
        and not player_detail_manual
        and not (side_a_passed and side_b_passed)
    )
    legal = prior_passed and not manual and not blocked and side_a_passed and side_b_passed
    return legal, manual, blocked


def run_self_test() -> int:
    scaled_expected = 7_500_000.0 * 164_961_000.0 / 136_021_000.0
    route_standard = pure_route(
        pre_team_salary=190_000_000,
        pre_apron_salary=190_000_000,
        outgoing=10_000_000,
        incoming_matching=10_200_000,
        incoming_actual=10_200_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    route_first_apron = pure_route(
        pre_team_salary=220_000_000,
        pre_apron_salary=220_000_000,
        outgoing=10_000_000,
        incoming_matching=10_100_000,
        incoming_actual=10_100_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    route_aggregated_blocked = pure_route(
        pre_team_salary=220_000_000,
        pre_apron_salary=220_000_000,
        outgoing=20_000_000,
        incoming_matching=19_000_000,
        incoming_actual=19_000_000,
        outgoing_count=2,
        aggregation_policy_blocked=True,
    )
    route_expanded = pure_route(
        pre_team_salary=190_000_000,
        pre_apron_salary=190_000_000,
        outgoing=10_000_000,
        incoming_matching=18_000_000,
        incoming_actual=18_000_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    tests = {
        "scaled_expanded_tpe_amount": math.isclose(
            EXPANDED_TPE_SCALED_ADD, scaled_expected, abs_tol=0.01
        ),
        "standard_tpe_selected": route_standard[0] == "standard_tpe",
        "first_apron_removes_250k_allowance": route_first_apron[0] == "none",
        "blocked_aggregation_cannot_use_aggregated_route": (
            route_aggregated_blocked[0] == "none"
        ),
        "expanded_tpe_selected_when_needed": route_expanded[0] == "expanded_tpe",
        "prior_block_preserved": pure_final_status(
            prior_passed=False,
            prior_manual=False,
            prior_blocked=True,
            evidence_missing=False,
            player_detail_manual=False,
            side_a_passed=True,
            side_b_passed=True,
        ) == (False, False, True),
        "prior_manual_preserved": pure_final_status(
            prior_passed=False,
            prior_manual=True,
            prior_blocked=False,
            evidence_missing=False,
            player_detail_manual=False,
            side_a_passed=True,
            side_b_passed=True,
        ) == (False, True, False),
        "missing_evidence_fails_closed_to_manual": pure_final_status(
            prior_passed=True,
            prior_manual=False,
            prior_blocked=False,
            evidence_missing=True,
            player_detail_manual=False,
            side_a_passed=True,
            side_b_passed=True,
        ) == (False, True, False),
        "deterministic_failure_blocks": pure_final_status(
            prior_passed=True,
            prior_manual=False,
            prior_blocked=False,
            evidence_missing=False,
            player_detail_manual=False,
            side_a_passed=False,
            side_b_passed=True,
        ) == (False, False, True),
        "clear_package_releases_legal": pure_final_status(
            prior_passed=True,
            prior_manual=False,
            prior_blocked=False,
            evidence_missing=False,
            player_detail_manual=False,
            side_a_passed=True,
            side_b_passed=True,
        ) == (True, False, False),
        "appended_columns_unique": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
        "final_field_is_updated_not_appended": (
            "optimizer_package_final_legal" not in APPENDED_COLUMNS
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def lower_string(pl: Any, column: str) -> Any:
    string_dtype = getattr(pl, "String", pl.Utf8)
    return pl.col(column).cast(string_dtype, strict=False).fill_null("").str.to_lowercase()


def bool_column(pl: Any, column: str) -> Any:
    return pl.col(column).cast(pl.Boolean, strict=False).fill_null(False)


def float_column(pl: Any, column: str) -> Any:
    return pl.col(column).cast(pl.Float64, strict=False)


def int_column(pl: Any, column: str) -> Any:
    return pl.col(column).cast(pl.Int64, strict=False)


def add_side_evaluation(pl: Any, frame: Any, side: str) -> Any:
    other = "b" if side == "a" else "a"
    team = f"team_{side}_"
    own_player = f"side_{side}_player_cba_"
    other_player = f"side_{other}_player_cba_"
    out = f"team_{side}_final_cba_"

    frame = frame.with_columns(
        [
            float_column(pl, own_player + "verified_outgoing_salary").alias(
                out + "outgoing_salary"
            ),
            float_column(
                pl, other_player + "verified_incoming_salary_for_opponent"
            ).alias(out + "incoming_salary_for_matching"),
            float_column(pl, other_player + "verified_outgoing_salary").alias(
                out + "incoming_actual_team_salary"
            ),
            int_column(pl, own_player + "player_count").alias(
                out + "outgoing_player_count"
            ),
            int_column(pl, other_player + "player_count").alias(
                out + "incoming_player_count"
            ),
            int_column(pl, own_player + "two_way_contract_count").alias(
                out + "__outgoing_two_way_count"
            ),
            int_column(pl, other_player + "two_way_contract_count").alias(
                out + "__incoming_two_way_count"
            ),
            float_column(pl, team + "verified_team_salary_value").alias(
                out + "__pretrade_team_salary"
            ),
            float_column(pl, team + "verified_apron_team_salary_value").alias(
                out + "__pretrade_apron_salary"
            ),
            float_column(pl, team + "verified_cap_room_value").alias(
                out + "__verified_cap_room"
            ),
            int_column(pl, team + "standard_contract_count").alias(
                out + "__pretrade_standard_count"
            ),
            int_column(pl, team + "two_way_contract_count").alias(
                out + "__pretrade_two_way_count"
            ),
            bool_column(pl, team + "hard_cap_active").alias(
                out + "__hard_cap_active"
            ),
            lower_string(pl, team + "hard_cap_level").alias(
                out + "__hard_cap_level_source"
            ),
            lower_string(pl, team + "aggregation_allowed").alias(
                out + "__aggregation_policy"
            ),
        ]
    )

    frame = frame.with_columns(
        [
            (
                pl.col(out + "__pretrade_team_salary")
                - pl.col(out + "outgoing_salary")
                + pl.col(out + "incoming_actual_team_salary")
            ).alias(out + "posttrade_team_salary"),
            (
                pl.col(out + "__pretrade_apron_salary")
                - pl.col(out + "outgoing_salary")
                + pl.col(out + "incoming_actual_team_salary")
            ).alias(out + "posttrade_apron_team_salary"),
            (
                pl.col(out + "__pretrade_standard_count")
                - (
                    pl.col(out + "outgoing_player_count")
                    - pl.col(out + "__outgoing_two_way_count")
                )
                + (
                    pl.col(out + "incoming_player_count")
                    - pl.col(out + "__incoming_two_way_count")
                )
            ).alias(out + "posttrade_standard_contract_count"),
            (
                pl.col(out + "__pretrade_two_way_count")
                - pl.col(out + "__outgoing_two_way_count")
                + pl.col(out + "__incoming_two_way_count")
            ).alias(out + "posttrade_two_way_contract_count"),
            (
                pl.col(out + "__hard_cap_active")
                & pl.col(out + "__hard_cap_level_source").str.contains("first")
            ).alias(out + "__existing_first_hard_cap"),
            (
                pl.col(out + "__hard_cap_active")
                & pl.col(out + "__hard_cap_level_source").str.contains("second")
            ).alias(out + "__existing_second_hard_cap"),
            (
                pl.col(out + "__aggregation_policy").str.contains(
                    "not_allowed|manual_review|pending"
                )
            ).alias(out + "__aggregation_policy_blocked"),
        ]
    )

    frame = frame.with_columns(
        [
            (
                pl.col(out + "posttrade_standard_contract_count")
                + pl.col(out + "posttrade_two_way_contract_count")
            ).alias(out + "posttrade_total_roster_count"),
            pl.when(
                pl.col(out + "posttrade_apron_team_salary")
                > FIRST_APRON + MONEY_TOLERANCE
            )
            .then(pl.lit(0.0))
            .otherwise(pl.lit(TPE_ALLOWANCE))
            .alias(out + "__allowance"),
            pl.max_horizontal(
                pl.lit(0.0),
                pl.lit(SALARY_CAP)
                - (
                    pl.col(out + "__pretrade_team_salary")
                    - pl.col(out + "outgoing_salary")
                ),
            ).alias(out + "__room_after_outgoing"),
            (
                pl.col(out + "__pretrade_team_salary")
                < SALARY_CAP - MONEY_TOLERANCE
            ).alias(out + "__under_cap"),
            (
                pl.col(out + "__hard_cap_active")
                & ~(
                    pl.col(out + "__existing_first_hard_cap")
                    | pl.col(out + "__existing_second_hard_cap")
                )
            ).alias(out + "__hard_cap_config_invalid"),
        ]
    )

    expanded_y = pl.min_horizontal(
        2.0 * pl.col(out + "outgoing_salary") + TPE_ALLOWANCE,
        pl.col(out + "outgoing_salary") + EXPANDED_TPE_SCALED_ADD,
    )
    expanded_z = 1.25 * pl.col(out + "outgoing_salary") + TPE_ALLOWANCE

    frame = frame.with_columns(
        [
            (
                pl.col(out + "__room_after_outgoing")
                + pl.col(out + "__allowance")
            ).alias(out + "__room_max"),
            (
                pl.col(out + "outgoing_salary")
                + pl.col(out + "__allowance")
            ).alias(out + "__standard_max"),
            pl.max_horizontal(expanded_y, expanded_z).alias(
                out + "__expanded_max"
            ),
            (
                pl.col(out + "__existing_first_hard_cap")
                & (
                    pl.col(out + "posttrade_apron_team_salary")
                    > FIRST_APRON + MONEY_TOLERANCE
                )
            ).alias(out + "__existing_first_hard_cap_failed"),
            (
                pl.col(out + "__existing_second_hard_cap")
                & (
                    pl.col(out + "posttrade_apron_team_salary")
                    > SECOND_APRON + MONEY_TOLERANCE
                )
            ).alias(out + "__existing_second_hard_cap_failed"),
        ]
    )

    frame = frame.with_columns(
        [
            (
                pl.col(out + "__under_cap")
                & (
                    pl.col(out + "incoming_salary_for_matching")
                    <= pl.col(out + "__room_max") + MONEY_TOLERANCE
                )
            ).alias(out + "__room_route_pass"),
            (
                (~pl.col(out + "__under_cap"))
                & (pl.col(out + "outgoing_player_count") == 1)
                & (
                    pl.col(out + "incoming_salary_for_matching")
                    <= pl.col(out + "__standard_max") + MONEY_TOLERANCE
                )
            ).alias(out + "__standard_route_pass"),
            (
                (~pl.col(out + "__under_cap"))
                & (pl.col(out + "outgoing_player_count") >= 2)
                & (~pl.col(out + "__aggregation_policy_blocked"))
                & (
                    pl.col(out + "posttrade_apron_team_salary")
                    <= SECOND_APRON + MONEY_TOLERANCE
                )
                & (
                    pl.col(out + "incoming_salary_for_matching")
                    <= pl.col(out + "__standard_max") + MONEY_TOLERANCE
                )
            ).alias(out + "__aggregated_route_pass"),
            (
                (
                    (pl.col(out + "outgoing_player_count") == 1)
                    | (~pl.col(out + "__aggregation_policy_blocked"))
                )
                & (
                    pl.col(out + "posttrade_apron_team_salary")
                    <= FIRST_APRON + MONEY_TOLERANCE
                )
                & (
                    pl.col(out + "incoming_salary_for_matching")
                    <= pl.col(out + "__expanded_max") + MONEY_TOLERANCE
                )
            ).alias(out + "__expanded_route_pass"),
        ]
    )

    route = (
        pl.when(pl.col(out + "__room_route_pass"))
        .then(pl.lit("room_under_cap"))
        .when(pl.col(out + "__standard_route_pass"))
        .then(pl.lit("standard_tpe"))
        .when(pl.col(out + "__aggregated_route_pass"))
        .then(pl.lit("aggregated_standard_tpe"))
        .when(pl.col(out + "__expanded_route_pass"))
        .then(pl.lit("expanded_tpe"))
        .otherwise(pl.lit("none"))
    )

    max_incoming = (
        pl.when(pl.col(out + "__room_route_pass"))
        .then(pl.col(out + "__room_max"))
        .when(pl.col(out + "__standard_route_pass"))
        .then(pl.col(out + "__standard_max"))
        .when(pl.col(out + "__aggregated_route_pass"))
        .then(pl.col(out + "__standard_max"))
        .when(pl.col(out + "__expanded_route_pass"))
        .then(pl.col(out + "__expanded_max"))
        .otherwise(
            pl.max_horizontal(
                pl.col(out + "__room_max"),
                pl.col(out + "__standard_max"),
                pl.col(out + "__expanded_max"),
            )
        )
    )

    frame = frame.with_columns(
        [
            route.alias(out + "salary_matching_route"),
            max_incoming.alias(out + "salary_matching_max_incoming"),
        ]
    )

    frame = frame.with_columns(
        [
            (
                pl.col(out + "salary_matching_max_incoming")
                - pl.col(out + "incoming_salary_for_matching")
            ).alias(out + "salary_matching_margin"),
            (
                pl.col(out + "salary_matching_route") != "none"
            ).alias(out + "salary_matching_passed"),
            (
                (pl.col(out + "outgoing_player_count") <= 1)
                | (pl.col(out + "salary_matching_route") == "room_under_cap")
                | (~pl.col(out + "__aggregation_policy_blocked"))
            ).alias(out + "aggregation_passed"),
            (
                (pl.col(out + "posttrade_standard_contract_count") >= 0)
                & (pl.col(out + "posttrade_two_way_contract_count") >= 0)
                & (
                    pl.col(out + "posttrade_total_roster_count")
                    <= OFFSEASON_TOTAL_ROSTER_MAX
                )
                & (
                    pl.col(out + "posttrade_two_way_contract_count")
                    <= TWO_WAY_ROSTER_MAX
                )
            ).alias(out + "roster_passed"),
            (
                ~(
                    pl.col(out + "__hard_cap_config_invalid")
                    | pl.col(out + "__existing_first_hard_cap_failed")
                    | pl.col(out + "__existing_second_hard_cap_failed")
                )
            ).alias(out + "existing_hard_cap_passed"),
        ]
    )

    frame = frame.with_columns(
        [
            pl.when(
                pl.col(out + "__existing_first_hard_cap")
                | (pl.col(out + "salary_matching_route") == "expanded_tpe")
            )
            .then(pl.lit("first_apron"))
            .when(
                pl.col(out + "__existing_second_hard_cap")
                | (
                    pl.col(out + "salary_matching_route")
                    == "aggregated_standard_tpe"
                )
            )
            .then(pl.lit("second_apron"))
            .otherwise(pl.lit("none"))
            .alias(out + "hard_cap_level_after_trade"),
        ]
    )

    frame = frame.with_columns(
        [
            pl.when(pl.col(out + "hard_cap_level_after_trade") == "first_apron")
            .then(
                pl.col(out + "posttrade_apron_team_salary")
                <= FIRST_APRON + MONEY_TOLERANCE
            )
            .when(
                pl.col(out + "hard_cap_level_after_trade") == "second_apron"
            )
            .then(
                pl.col(out + "posttrade_apron_team_salary")
                <= SECOND_APRON + MONEY_TOLERANCE
            )
            .otherwise(pl.lit(True))
            .alias(out + "hard_cap_passed"),
            pl.any_horizontal(
                [
                    pl.col(out + "outgoing_salary").is_null(),
                    pl.col(out + "incoming_salary_for_matching").is_null(),
                    pl.col(out + "incoming_actual_team_salary").is_null(),
                    pl.col(out + "outgoing_player_count").is_null(),
                    pl.col(out + "incoming_player_count").is_null(),
                    pl.col(out + "__pretrade_team_salary").is_null(),
                    pl.col(out + "__pretrade_apron_salary").is_null(),
                    pl.col(out + "__pretrade_standard_count").is_null(),
                    pl.col(out + "__pretrade_two_way_count").is_null(),
                    pl.col(out + "__hard_cap_config_invalid"),
                ]
            ).alias(out + "evidence_missing"),
        ]
    )

    frame = frame.with_columns(
        [
            pl.when(pl.col(out + "evidence_missing"))
            .then(pl.lit("evidence_missing_manual_review"))
            .when(~pl.col(out + "roster_passed"))
            .then(pl.lit("offseason_roster_limit_failed"))
            .when(~pl.col(out + "existing_hard_cap_passed"))
            .then(pl.lit("existing_hard_cap_failed"))
            .when(~pl.col(out + "aggregation_passed"))
            .then(pl.lit("team_aggregation_policy_failed"))
            .when(~pl.col(out + "salary_matching_passed"))
            .then(pl.lit("salary_matching_failed"))
            .when(~pl.col(out + "hard_cap_passed"))
            .then(pl.lit("transaction_hard_cap_failed"))
            .otherwise(pl.lit("passed"))
            .alias(out + "issue")
        ]
    )
    return frame


def evaluate_packages(pl: Any, source: Any) -> Any:
    original_columns = list(source.columns)
    frame = source.with_row_index("__final_cba_row_order")

    frame = frame.with_columns(
        [
            pl.col("optimizer_package_final_legal").alias(
                "optimizer_package_final_legal_before_full_cba"
            ),
            pl.col("optimizer_package_legality_status").alias(
                "optimizer_package_legality_status_before_full_cba"
            ),
        ]
    )

    frame = add_side_evaluation(pl, frame, "a")
    frame = add_side_evaluation(pl, frame, "b")

    prior_passed = bool_column(pl, "package_player_cba_stage_passed")
    prior_manual = bool_column(
        pl, "package_player_cba_manual_review_required"
    )
    prior_blocked = bool_column(pl, "package_player_cba_blocked")
    prior_inconsistent = ~(prior_passed | prior_manual | prior_blocked)

    player_detail_manual = (
        int_column(pl, "side_a_player_cba_base_year_compensation_count").fill_null(0)
        + int_column(pl, "side_b_player_cba_base_year_compensation_count").fill_null(0)
        + int_column(pl, "side_a_player_cba_trade_bonus_active_count").fill_null(0)
        + int_column(pl, "side_b_player_cba_trade_bonus_active_count").fill_null(0)
        + int_column(pl, "side_a_player_cba_consent_required_count").fill_null(0)
        + int_column(pl, "side_b_player_cba_consent_required_count").fill_null(0)
        + int_column(pl, "side_a_player_cba_sign_and_trade_count").fill_null(0)
        + int_column(pl, "side_b_player_cba_sign_and_trade_count").fill_null(0)
        + int_column(pl, "side_a_player_cba_two_way_contract_count").fill_null(0)
        + int_column(pl, "side_b_player_cba_two_way_contract_count").fill_null(0)
        > 0
    )

    evidence_missing = (
        bool_column(pl, "team_a_final_cba_evidence_missing")
        | bool_column(pl, "team_b_final_cba_evidence_missing")
        | (~bool_column(pl, "player_cba_decisions_matched"))
        | (~bool_column(pl, "side_a_player_cba_decisions_matched"))
        | (~bool_column(pl, "side_b_player_cba_decisions_matched"))
        | (~bool_column(pl, "team_a_cba_stage_pass"))
        | (~bool_column(pl, "team_b_cba_stage_pass"))
        | bool_column(pl, "team_a_cba_manual_review_required")
        | bool_column(pl, "team_b_cba_manual_review_required")
    )

    salary_passed = (
        bool_column(pl, "team_a_final_cba_salary_matching_passed")
        & bool_column(pl, "team_b_final_cba_salary_matching_passed")
    )
    aggregation_passed = (
        bool_column(pl, "team_a_final_cba_aggregation_passed")
        & bool_column(pl, "team_b_final_cba_aggregation_passed")
        & (~bool_column(pl, "package_player_cba_aggregation_blocked"))
    )
    roster_passed = (
        bool_column(pl, "team_a_final_cba_roster_passed")
        & bool_column(pl, "team_b_final_cba_roster_passed")
    )
    hard_cap_passed = (
        bool_column(pl, "team_a_final_cba_hard_cap_passed")
        & bool_column(pl, "team_b_final_cba_hard_cap_passed")
        & bool_column(pl, "team_a_final_cba_existing_hard_cap_passed")
        & bool_column(pl, "team_b_final_cba_existing_hard_cap_passed")
    )
    deterministic_pass = (
        salary_passed & aggregation_passed & roster_passed & hard_cap_passed
    )

    manual = prior_manual | prior_inconsistent | (
        prior_passed & (evidence_missing | player_detail_manual)
    )
    blocked = prior_blocked | (
        prior_passed
        & (~evidence_missing)
        & (~player_detail_manual)
        & (~deterministic_pass)
    )
    legal = prior_passed & (~manual) & (~blocked) & deterministic_pass

    frame = frame.with_columns(
        [
            pl.lit(TRADE_DATE).alias("full_cba_trade_date"),
            pl.lit(LEAGUE_YEAR).alias("full_cba_league_year"),
            pl.lit(SALARY_CAP).alias("full_cba_salary_cap"),
            pl.lit(TAX_LEVEL).alias("full_cba_tax_level"),
            pl.lit(FIRST_APRON).alias("full_cba_first_apron"),
            pl.lit(SECOND_APRON).alias("full_cba_second_apron"),
            pl.lit(False).alias("full_cba_cash_consideration_used"),
            pl.lit(False).alias("full_cba_banked_trade_exception_used"),
            player_detail_manual.alias(
                "full_cba_player_detail_manual_review_required"
            ),
            (~evidence_missing).alias("full_cba_evidence_complete"),
            salary_passed.alias("full_cba_salary_matching_passed"),
            aggregation_passed.alias("full_cba_aggregation_passed"),
            roster_passed.alias("full_cba_roster_passed"),
            hard_cap_passed.alias("full_cba_hard_cap_passed"),
            legal.alias("full_cba_deterministic_legal"),
            manual.alias("full_cba_manual_review_required"),
            blocked.alias("full_cba_blocked"),
        ]
    )

    status = (
        pl.when(prior_blocked)
        .then(pl.lit("blocked_by_prior_player_cba_stage"))
        .when(prior_manual)
        .then(pl.lit("manual_review_from_prior_player_cba_stage"))
        .when(prior_inconsistent)
        .then(pl.lit("manual_review_prior_stage_inconsistent"))
        .when(evidence_missing)
        .then(pl.lit("manual_review_missing_full_cba_evidence"))
        .when(player_detail_manual)
        .then(pl.lit("manual_review_transaction_specific_player_mechanics"))
        .when(~bool_column(pl, "team_a_final_cba_roster_passed"))
        .then(pl.lit("blocked_team_a_offseason_roster_limit"))
        .when(~bool_column(pl, "team_b_final_cba_roster_passed"))
        .then(pl.lit("blocked_team_b_offseason_roster_limit"))
        .when(~bool_column(pl, "team_a_final_cba_existing_hard_cap_passed"))
        .then(pl.lit("blocked_team_a_existing_hard_cap"))
        .when(~bool_column(pl, "team_b_final_cba_existing_hard_cap_passed"))
        .then(pl.lit("blocked_team_b_existing_hard_cap"))
        .when(~bool_column(pl, "team_a_final_cba_aggregation_passed"))
        .then(pl.lit("blocked_team_a_aggregation_rule"))
        .when(~bool_column(pl, "team_b_final_cba_aggregation_passed"))
        .then(pl.lit("blocked_team_b_aggregation_rule"))
        .when(bool_column(pl, "package_player_cba_aggregation_blocked"))
        .then(pl.lit("blocked_player_aggregation_restriction"))
        .when(~bool_column(pl, "team_a_final_cba_salary_matching_passed"))
        .then(pl.lit("blocked_team_a_salary_matching"))
        .when(~bool_column(pl, "team_b_final_cba_salary_matching_passed"))
        .then(pl.lit("blocked_team_b_salary_matching"))
        .when(~bool_column(pl, "team_a_final_cba_hard_cap_passed"))
        .then(pl.lit("blocked_team_a_transaction_hard_cap"))
        .when(~bool_column(pl, "team_b_final_cba_hard_cap_passed"))
        .then(pl.lit("blocked_team_b_transaction_hard_cap"))
        .otherwise(pl.lit("final_legal_full_cba_deterministic"))
    )

    frame = frame.with_columns(
        [
            status.alias("full_cba_status"),
            (legal | blocked).alias("full_cba_deterministic_status_released"),
            pl.lit(RELEASE_NAME).alias("full_cba_rules_release"),
            pl.lit(SCRIPT_VERSION).alias("full_cba_evaluator_version"),
            legal.alias("optimizer_package_final_legal"),
            status.alias("optimizer_package_legality_status"),
        ]
    )

    # Remove private calculation helpers but preserve all public appended fields.
    private_columns = [
        column
        for column in frame.columns
        if column.startswith("team_a_final_cba___")
        or column.startswith("team_b_final_cba___")
    ]
    if "__final_cba_row_order" in frame.columns:
        private_columns.append("__final_cba_row_order")
    frame = frame.drop(private_columns)

    return frame.select([*original_columns, *APPENDED_COLUMNS])


def validate_input(pl: Any, label: str, source: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, expected: Any) -> None:
        rows.append(
            {
                "package_type": label,
                "check_name": name,
                "passed": bool(passed),
                "observed": observed,
                "expected": expected,
            }
        )

    missing = sorted(PACKAGE_REQUIRED_COLUMNS.difference(source.columns))
    preexisting = sorted(set(APPENDED_COLUMNS).intersection(source.columns))

    passed = int(source["package_player_cba_stage_passed"].sum())
    manual = int(source["package_player_cba_manual_review_required"].sum())
    blocked = int(source["package_player_cba_blocked"].sum())
    expected = EXPECTED_PLAYER_STAGE[label]

    add("input_row_count", source.height == EXPECTED_ROWS[label], source.height, EXPECTED_ROWS[label])
    add(
        "input_column_count",
        source.width == EXPECTED_INPUT_COLUMNS[label],
        source.width,
        EXPECTED_INPUT_COLUMNS[label],
    )
    add("required_columns_present", not missing, missing, [])
    add("no_preexisting_full_cba_columns", not preexisting, preexisting, [])
    add(
        "candidate_ids_unique",
        source["optimizer_candidate_id"].n_unique() == source.height,
        source["optimizer_candidate_id"].n_unique(),
        source.height,
    )
    add(
        "player_stage_partition_exact",
        {"passed": passed, "manual": manual, "blocked": blocked} == expected,
        {"passed": passed, "manual": manual, "blocked": blocked},
        expected,
    )
    add(
        "player_stage_partition_complete",
        passed + manual + blocked == source.height,
        passed + manual + blocked,
        source.height,
    )
    add(
        "input_final_legal_unreleased",
        int(source["optimizer_package_final_legal"].sum()) == 0,
        int(source["optimizer_package_final_legal"].sum()),
        0,
    )
    return rows


def validate_output(
    pl: Any,
    label: str,
    source: Any,
    evaluated: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, expected: Any) -> None:
        rows.append(
            {
                "package_type": label,
                "check_name": name,
                "passed": bool(passed),
                "observed": observed,
                "expected": expected,
            }
        )

    original_columns = list(source.columns)
    unchanged_columns = [
        column
        for column in original_columns
        if column
        not in {"optimizer_package_final_legal", "optimizer_package_legality_status"}
    ]

    legal = int(evaluated["full_cba_deterministic_legal"].sum())
    manual = int(evaluated["full_cba_manual_review_required"].sum())
    blocked = int(evaluated["full_cba_blocked"].sum())

    add("output_row_count_preserved", evaluated.height == source.height, evaluated.height, source.height)
    add(
        "output_column_count",
        evaluated.width == source.width + len(APPENDED_COLUMNS),
        evaluated.width,
        source.width + len(APPENDED_COLUMNS),
    )
    add(
        "unchanged_input_columns_preserved",
        frames_equal(
            source.select(unchanged_columns),
            evaluated.select(unchanged_columns),
        ),
        True,
        True,
    )
    add(
        "pre_final_status_backups_preserved",
        frames_equal(
            source.select(
                [
                    pl.col("optimizer_package_final_legal").alias(
                        "optimizer_package_final_legal_before_full_cba"
                    ),
                    pl.col("optimizer_package_legality_status").alias(
                        "optimizer_package_legality_status_before_full_cba"
                    ),
                ]
            ),
            evaluated.select(
                [
                    "optimizer_package_final_legal_before_full_cba",
                    "optimizer_package_legality_status_before_full_cba",
                ]
            ),
        ),
        True,
        True,
    )
    add(
        "final_partition_complete",
        legal + manual + blocked == evaluated.height,
        legal + manual + blocked,
        evaluated.height,
    )
    add(
        "optimizer_final_legal_matches_full_cba",
        int(evaluated["optimizer_package_final_legal"].sum()) == legal,
        int(evaluated["optimizer_package_final_legal"].sum()),
        legal,
    )
    add(
        "manual_rows_not_final_legal",
        evaluated.filter(
            pl.col("full_cba_manual_review_required")
            & pl.col("optimizer_package_final_legal")
        ).height
        == 0,
        evaluated.filter(
            pl.col("full_cba_manual_review_required")
            & pl.col("optimizer_package_final_legal")
        ).height,
        0,
    )
    add(
        "blocked_rows_not_final_legal",
        evaluated.filter(
            pl.col("full_cba_blocked")
            & pl.col("optimizer_package_final_legal")
        ).height
        == 0,
        evaluated.filter(
            pl.col("full_cba_blocked")
            & pl.col("optimizer_package_final_legal")
        ).height,
        0,
    )
    legal_rows = evaluated.filter(pl.col("optimizer_package_final_legal"))
    add(
        "legal_rows_cleared_prior_player_stage",
        int(legal_rows["package_player_cba_stage_passed"].sum())
        == legal_rows.height,
        int(legal_rows["package_player_cba_stage_passed"].sum()),
        legal_rows.height,
    )
    for gate in (
        "full_cba_evidence_complete",
        "full_cba_salary_matching_passed",
        "full_cba_aggregation_passed",
        "full_cba_roster_passed",
        "full_cba_hard_cap_passed",
    ):
        add(
            f"legal_rows_{gate}",
            int(legal_rows[gate].sum()) == legal_rows.height,
            int(legal_rows[gate].sum()),
            legal_rows.height,
        )
    add(
        "cash_policy_zero",
        int(evaluated["full_cba_cash_consideration_used"].sum()) == 0,
        int(evaluated["full_cba_cash_consideration_used"].sum()),
        0,
    )
    add(
        "banked_tpe_policy_zero",
        int(evaluated["full_cba_banked_trade_exception_used"].sum()) == 0,
        int(evaluated["full_cba_banked_trade_exception_used"].sum()),
        0,
    )

    profile = {
        "rows": evaluated.height,
        "input_columns": source.width,
        "output_columns": evaluated.width,
        "final": {
            "legal": legal,
            "manual": manual,
            "blocked": blocked,
        },
        "status_counts": value_counts_map(evaluated, "full_cba_status"),
        "team_a_route_counts": value_counts_map(
            evaluated, "team_a_final_cba_salary_matching_route"
        ),
        "team_b_route_counts": value_counts_map(
            evaluated, "team_b_final_cba_salary_matching_route"
        ),
        "salary_failures": int(
            (~evaluated["full_cba_salary_matching_passed"]).sum()
        ),
        "aggregation_failures": int(
            (~evaluated["full_cba_aggregation_passed"]).sum()
        ),
        "roster_failures": int((~evaluated["full_cba_roster_passed"]).sum()),
        "hard_cap_failures": int(
            (~evaluated["full_cba_hard_cap_passed"]).sum()
        ),
        "player_detail_manual": int(
            evaluated["full_cba_player_detail_manual_review_required"].sum()
        ),
    }
    return rows, profile


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(
            "Polars is required. Run this script in the nba-roster-optimizer "
            "environment used by the existing pipeline."
        ) from exc

    root = project_root(args.root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("MIXED PLAYER-AND-PICK FINAL FULL-CBA LEGALITY EVALUATION")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Trade date: {TRADE_DATE}")
    print(
        "2026-27 levels: "
        f"cap ${SALARY_CAP:,.0f} | tax ${TAX_LEVEL:,.0f} | "
        f"first apron ${FIRST_APRON:,.0f} | second apron ${SECOND_APRON:,.0f}"
    )
    print()

    print("[1/7] Locating V8 player-CBA-evaluated package parquets")
    input_paths = {
        label: locate_one(root, filename)
        for label, filename in INPUT_FILES.items()
    }

    source_frames: dict[str, Any] = {}
    validation_rows: list[dict[str, Any]] = []
    for label, path in input_paths.items():
        source = pl.read_parquet(str(path))
        source_frames[label] = source
        validation_rows.extend(validate_input(pl, label, source))
        print(
            f"  {label}: {source.height:,} rows | {source.width:,} columns"
        )

    input_valid = all(row["passed"] for row in validation_rows)
    if not input_valid:
        failed = [
            f"{row['package_type']}::{row['check_name']}"
            for row in validation_rows
            if not row["passed"]
        ]
        raise RuntimeError(
            "V8 input validation failed:\n  - " + "\n  - ".join(failed)
        )

    print("[2/7] Recalculating exact sending and receiving salary amounts")
    evaluated_frames = {
        label: evaluate_packages(pl, source)
        for label, source in source_frames.items()
    }

    print("[3/7] Applying salary matching and apron-created hard caps")
    print("[4/7] Applying existing hard caps, aggregation, and roster limits")

    print("[5/7] Validating deterministic final decisions")
    profiles: dict[str, Any] = {}
    for label, evaluated in evaluated_frames.items():
        checks, profile = validate_output(
            pl, label, source_frames[label], evaluated
        )
        validation_rows.extend(checks)
        profiles[label] = profile

    global_prior = {
        "rows": sum(frame.height for frame in source_frames.values()),
        "passed": sum(
            int(frame["package_player_cba_stage_passed"].sum())
            for frame in source_frames.values()
        ),
        "manual": sum(
            int(frame["package_player_cba_manual_review_required"].sum())
            for frame in source_frames.values()
        ),
        "blocked": sum(
            int(frame["package_player_cba_blocked"].sum())
            for frame in source_frames.values()
        ),
    }
    validation_rows.append(
        {
            "package_type": "global",
            "check_name": "global_player_stage_partition_exact",
            "passed": global_prior == EXPECTED_GLOBAL_PLAYER_STAGE,
            "observed": global_prior,
            "expected": EXPECTED_GLOBAL_PLAYER_STAGE,
        }
    )
    validation_rows.append(
        {
            "package_type": "global",
            "check_name": "appended_columns_unique",
            "passed": len(APPENDED_COLUMNS) == len(set(APPENDED_COLUMNS)),
            "observed": len(APPENDED_COLUMNS),
            "expected": len(set(APPENDED_COLUMNS)),
        }
    )

    release_valid = all(bool(row["passed"]) for row in validation_rows)

    print("[6/7] Writing V9 parquets and audit artifacts")
    output_paths = {
        label: outputs / filename for label, filename in OUTPUT_FILES.items()
    }
    if release_valid and not args.audit_only:
        for label, frame in evaluated_frames.items():
            frame.write_parquet(
                str(output_paths[label]),
                compression="zstd",
                statistics=True,
            )

    summary_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for label, frame in evaluated_frames.items():
        metrics = {
            "final_legal": int(frame["full_cba_deterministic_legal"].sum()),
            "manual_review": int(
                frame["full_cba_manual_review_required"].sum()
            ),
            "blocked": int(frame["full_cba_blocked"].sum()),
            "evidence_complete": int(frame["full_cba_evidence_complete"].sum()),
            "salary_matching_passed": int(
                frame["full_cba_salary_matching_passed"].sum()
            ),
            "aggregation_passed": int(
                frame["full_cba_aggregation_passed"].sum()
            ),
            "roster_passed": int(frame["full_cba_roster_passed"].sum()),
            "hard_cap_passed": int(frame["full_cba_hard_cap_passed"].sum()),
            "player_detail_manual": int(
                frame["full_cba_player_detail_manual_review_required"].sum()
            ),
        }
        for metric, count in metrics.items():
            summary_rows.append(
                {"package_type": label, "metric": metric, "count": count}
            )

        for status, count in value_counts_map(frame, "full_cba_status").items():
            issue_rows.append(
                {
                    "package_type": label,
                    "full_cba_status": status,
                    "count": count,
                }
            )
        for side in ("a", "b"):
            column = f"team_{side}_final_cba_salary_matching_route"
            for route_name, count in value_counts_map(frame, column).items():
                route_rows.append(
                    {
                        "package_type": label,
                        "team_side": side.upper(),
                        "salary_matching_route": route_name,
                        "count": count,
                    }
                )

    write_csv(
        outputs / SUMMARY_FILENAME,
        ["package_type", "metric", "count"],
        summary_rows,
    )
    write_csv(
        outputs / ISSUE_SUMMARY_FILENAME,
        ["package_type", "full_cba_status", "count"],
        issue_rows,
    )
    write_csv(
        outputs / ROUTE_SUMMARY_FILENAME,
        ["package_type", "team_side", "salary_matching_route", "count"],
        route_rows,
    )
    write_csv(
        outputs / VALIDATION_FILENAME,
        ["package_type", "check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    rules = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "trade_date": TRADE_DATE,
        "league_year": LEAGUE_YEAR,
        "thresholds": {
            "salary_cap": SALARY_CAP,
            "minimum_team_salary": MINIMUM_TEAM_SALARY,
            "tax_level": TAX_LEVEL,
            "first_apron": FIRST_APRON,
            "second_apron": SECOND_APRON,
            "salary_cap_2023_24": SALARY_CAP_2023_24,
            "expanded_tpe_scaled_add": EXPANDED_TPE_SCALED_ADD,
            "tpe_allowance": TPE_ALLOWANCE,
            "offseason_total_roster_max": OFFSEASON_TOTAL_ROSTER_MAX,
            "two_way_roster_max": TWO_WAY_ROSTER_MAX,
        },
        "salary_matching": {
            "standard_tpe": "100% of outgoing salary plus $250,000; allowance becomes $0 when post-trade apron salary exceeds the first apron",
            "aggregated_standard_tpe": "100% of aggregated outgoing salary plus $250,000; creates second-apron hard cap; allowance becomes $0 above first apron",
            "expanded_tpe": "greater of the CBA 200%/scaled-add branch and 125% branch; creates first-apron hard cap",
            "room_under_cap": "room after outgoing salary plus $250,000; allowance becomes $0 above first apron",
        },
        "conservative_policies": {
            "cash_consideration": "forbidden",
            "banked_trade_exception": "forbidden",
            "base_year_compensation": "manual review",
            "active_trade_bonus": "manual review",
            "player_consent": "manual review",
            "sign_and_trade": "manual review",
            "two_way_contract_in_package": "manual review",
            "missing_evidence": "manual review",
        },
        "sources": {
            "official_2026_27_cap_release": CAP_SOURCE_URL,
            "official_2023_nba_nbpa_cba": CBA_SOURCE_URL,
        },
    }
    write_json(outputs / RULES_FILENAME, rules)

    global_final = {
        "rows": sum(frame.height for frame in evaluated_frames.values()),
        "legal": sum(
            int(frame["full_cba_deterministic_legal"].sum())
            for frame in evaluated_frames.values()
        ),
        "manual": sum(
            int(frame["full_cba_manual_review_required"].sum())
            for frame in evaluated_frames.values()
        ),
        "blocked": sum(
            int(frame["full_cba_blocked"].sum())
            for frame in evaluated_frames.values()
        ),
    }

    metadata = {
        "release_name": RELEASE_NAME,
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": TRADE_DATE,
        "league_year": LEAGUE_YEAR,
        "release_valid": release_valid,
        "audit_only": args.audit_only,
        "inputs": {label: str(path) for label, path in input_paths.items()},
        "outputs": {
            label: (
                str(path)
                if path.exists()
                else None
            )
            for label, path in output_paths.items()
        },
        "audit_outputs": {
            "summary": str(outputs / SUMMARY_FILENAME),
            "issue_summary": str(outputs / ISSUE_SUMMARY_FILENAME),
            "route_summary": str(outputs / ROUTE_SUMMARY_FILENAME),
            "validation": str(outputs / VALIDATION_FILENAME),
            "rules": str(outputs / RULES_FILENAME),
        },
        "appended_columns": APPENDED_COLUMNS,
        "appended_column_count": len(APPENDED_COLUMNS),
        "package_profiles": profiles,
        "global_prior_player_stage": global_prior,
        "global_final": global_final,
        "validation_checks_passed": sum(
            bool(row["passed"]) for row in validation_rows
        ),
        "validation_checks_total": len(validation_rows),
        "optimizer_package_final_legal_released": release_valid
        and not args.audit_only,
        "manual_rows_require_transaction_specific_review": True,
        "scope_note": (
            "Final legal is released only for packages deterministically supported "
            "by the V8 team/player/right evidence and the conservative no-cash, "
            "no-banked-TPE policy. Manual rows remain non-legal."
        ),
    }
    write_json(outputs / METADATA_FILENAME, metadata)

    print("[7/7] Complete")
    print(
        f"Validation: {metadata['validation_checks_passed']}/"
        f"{metadata['validation_checks_total']}"
    )
    print(f"Release valid: {release_valid}")
    print(
        f"Final partition: {global_final['legal']:,} legal | "
        f"{global_final['manual']:,} manual | "
        f"{global_final['blocked']:,} blocked"
    )
    print(
        "optimizer_package_final_legal released: "
        f"{metadata['optimizer_package_final_legal_released']}"
    )

    if not release_valid:
        failed = [
            f"{row['package_type']}::{row['check_name']}"
            for row in validation_rows
            if not row["passed"]
        ]
        print("Failed checks:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())