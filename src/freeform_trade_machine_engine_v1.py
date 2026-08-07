from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
APP_DATA = ROOT / "app_data"

TRADE_DATE = "2026-08-04"


class Status(str, Enum):
    PASS = "pass"
    MANUAL_REVIEW = "manual_review"
    BLOCKED = "blocked"


STATUS_PRIORITY = {
    Status.PASS: 0,
    Status.MANUAL_REVIEW: 1,
    Status.BLOCKED: 2,
}


@dataclass(frozen=True)
class TradeSideRequest:
    team_abbreviation: str
    player_ids: tuple[str, ...] = ()
    pick_right_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeRequest:
    side_a: TradeSideRequest
    side_b: TradeSideRequest
    trade_date: str = TRADE_DATE


@dataclass
class CheckResult:
    status: Status
    code: str
    message: str
    team_abbreviation: str | None = None
    player_id: str | None = None
    pick_right_id: str | None = None


@dataclass
class SideEvaluation:
    team_abbreviation: str
    status: Status
    outgoing_salary: float
    player_ids: list[str]
    pick_right_ids: list[str]
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class TradeEvaluation:
    status: Status
    trade_date: str
    side_a: SideEvaluation
    side_b: SideEvaluation
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class RuntimeData:
    trade_pool: pd.DataFrame
    financial: pd.DataFrame
    market: pd.DataFrame
    team_salary: pd.DataFrame
    picks: pd.DataFrame
    stepien: pd.DataFrame
    ratings: pd.DataFrame
    player_cba: pd.DataFrame
    rules: dict[str, Any]
    trade_by_id: dict[str, dict[str, Any]]
    financial_by_id: dict[str, dict[str, Any]]
    market_by_id: dict[str, dict[str, Any]]
    ratings_by_id: dict[str, dict[str, Any]]
    player_cba_by_id: dict[str, dict[str, Any]]
    team_salary_by_team: dict[str, dict[str, Any]]
    pick_by_id: dict[str, dict[str, Any]]


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]

    return text


def normalize_team(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    return str(value).strip().upper()


def to_bool(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y"}:
        return True

    if text in {"false", "0", "no", "n"}:
        return False

    return None


def to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def combine_statuses(statuses: list[Status]) -> Status:
    if not statuses:
        return Status.PASS

    return max(statuses, key=lambda status: STATUS_PRIORITY[status])


def dataframe_index(
    frame: pd.DataFrame,
    key: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}

    for record in frame.to_dict(orient="records"):
        value = str(record.get(key, "")).strip()

        if value:
            indexed[value] = record

    return indexed


def load_runtime_data() -> RuntimeData:
    required_paths = {
        "trade_pool": (
            PROCESSED
            / "trade_eligible_player_pool_2026_27.parquet"
        ),
        "financial": (
            PROCESSED
            / "player_financial_layer_2026_27_v2.parquet"
        ),
        "market": (
            PROCESSED
            / "player_trade_market_value_layer_2026_27_v3.parquet"
        ),
        "team_salary": (
            PROCESSED
            / "team_trade_salary_profiles_2026_27.csv"
        ),
        "picks": (
            PROCESSED
            / "future_pick_optimizer_inventory_2027_2029_final.parquet"
        ),
        "stepien": (
            PROCESSED
            / "future_first_round_legality_calendar_2027_2034_v5_evidence_ingested.parquet"
        ),
        "ratings": APP_DATA / "player_ratings_2026_27_v2.json",
        "player_cba": (
            OUTPUTS
            / "mixed_player_pick_player_cba_decision_release_v1.csv"
        ),
        "rules": (
            OUTPUTS
            / "mixed_player_pick_final_full_cba_rules_v1.json"
        ),
    }

    missing = [
        str(path)
        for path in required_paths.values()
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required freeform Trade Machine inputs are missing:\n"
            + "\n".join(missing)
        )

    trade_pool = pd.read_parquet(required_paths["trade_pool"])
    financial = pd.read_parquet(required_paths["financial"])
    market = pd.read_parquet(required_paths["market"])
    team_salary = pd.read_csv(required_paths["team_salary"])
    picks = pd.read_parquet(required_paths["picks"])
    stepien = pd.read_parquet(required_paths["stepien"])
    player_cba = pd.read_csv(required_paths["player_cba"])

    ratings_payload = json.loads(
        required_paths["ratings"].read_text(
            encoding="utf-8-sig"
        )
    )
    ratings = pd.DataFrame(
        list(ratings_payload["players_by_id"].values())
    )

    rules = json.loads(
        required_paths["rules"].read_text(
            encoding="utf-8-sig"
        )
    )

    for frame in [
        trade_pool,
        financial,
        market,
        ratings,
        player_cba,
    ]:
        frame["player_id"] = frame["player_id"].map(
            normalize_player_id
        )

    for frame, column in [
        (trade_pool, "current_team_2026_27"),
        (financial, "current_team_2026_27"),
        (market, "current_team_2026_27"),
        (player_cba, "current_team_2026_27"),
        (team_salary, "team_abbreviation"),
        (picks, "candidate_team"),
        (stepien, "team_abbreviation"),
    ]:
        if column in frame.columns:
            frame[column] = frame[column].map(normalize_team)

    picks["future_pick_right_id"] = (
        picks["future_pick_right_id"]
        .astype(str)
        .str.strip()
    )

    return RuntimeData(
        trade_pool=trade_pool,
        financial=financial,
        market=market,
        team_salary=team_salary,
        picks=picks,
        stepien=stepien,
        ratings=ratings,
        player_cba=player_cba,
        rules=rules,
        trade_by_id=dataframe_index(trade_pool, "player_id"),
        financial_by_id=dataframe_index(financial, "player_id"),
        market_by_id=dataframe_index(market, "player_id"),
        ratings_by_id=dataframe_index(ratings, "player_id"),
        player_cba_by_id=dataframe_index(
            player_cba,
            "player_id",
        ),
        team_salary_by_team=dataframe_index(
            team_salary,
            "team_abbreviation",
        ),
        pick_by_id=dataframe_index(
            picks,
            "future_pick_right_id",
        ),
    )


def evaluate_player(
    runtime: RuntimeData,
    team: str,
    player_id: str,
    outgoing_player_count: int,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    player_id = normalize_player_id(player_id)

    trade_record = runtime.trade_by_id.get(player_id)

    if trade_record is None:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="player_not_in_trade_pool",
                message=(
                    f"Player {player_id} is not in the verified "
                    "2026-27 trade-eligible player pool."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        ]

    player_name = str(
        trade_record.get("player_name", player_id)
    ).strip()
    roster_team = normalize_team(
        trade_record.get("current_team_2026_27")
    )

    if roster_team != team:
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="player_roster_mismatch",
                message=(
                    f"{player_name} belongs to {roster_team}, "
                    f"not {team}, in the runtime roster."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
        return checks

    salary = to_float(
        trade_record.get("trade_salary_2026_27")
    )

    if salary is None:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_salary_missing",
                message=(
                    f"{player_name} does not have a usable "
                    "2026-27 trade salary."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    decision = runtime.player_cba_by_id.get(player_id)

    if decision is None:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_cba_evidence_missing",
                message=(
                    f"{player_name} is in the trade pool but is "
                    "not covered by the 311-player CBA decision "
                    "release."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
        return checks

    determination = str(
        decision.get(
            "player_cba_evidence_determination",
            "",
        )
    ).strip().lower()

    manual = to_bool(
        decision.get("manual_review_required")
    )
    stage_pass = to_bool(
        decision.get("player_cba_stage_pass")
    )
    aggregation_restricted = to_bool(
        decision.get(
            "aggregation_restricted_on_trade_date"
        )
    )
    consent_required = to_bool(
        decision.get("trade_consent_required")
    )
    two_way = to_bool(
        decision.get("two_way_contract_active")
    )
    byc = to_bool(
        decision.get("base_year_compensation_active")
    )
    sign_and_trade = to_bool(
        decision.get("sign_and_trade_player")
    )
    extend_restricted = to_bool(
        decision.get(
            "extend_and_trade_restriction_active"
        )
    )
    trade_bonus = to_float(
        decision.get("trade_bonus_percent")
    ) or 0.0
    restriction_end = str(
        decision.get("restriction_end_date", "")
    ).strip()
    evidence_summary = str(
        decision.get("evidence_summary", "")
    ).strip()

    if determination == "not_trade_eligible":
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="player_not_trade_eligible",
                message=(
                    f"{player_name} is not trade-eligible on "
                    f"{TRADE_DATE}"
                    + (
                        f" through {restriction_end}."
                        if restriction_end
                        else "."
                    )
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
        return checks

    if extend_restricted is True:
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="extend_and_trade_restriction",
                message=(
                    f"{player_name} has an active "
                    "extend-and-trade restriction."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if (
        aggregation_restricted is True
        and outgoing_player_count > 1
    ):
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="player_aggregation_restricted",
                message=(
                    f"{player_name} may not be aggregated with "
                    "another outgoing player on the trade date."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if consent_required is True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_consent_required",
                message=(
                    f"{player_name} requires player consent "
                    "for this transaction."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if trade_bonus > 0:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="active_trade_bonus",
                message=(
                    f"{player_name} has an active trade bonus "
                    f"of {trade_bonus:.1%}; receiving salary "
                    "depends on bonus allocation or waiver."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if byc is True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="base_year_compensation",
                message=(
                    f"{player_name} requires base-year "
                    "compensation treatment."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if sign_and_trade is True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="sign_and_trade",
                message=(
                    f"{player_name} is modeled as a "
                    "sign-and-trade player."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if two_way is True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="two_way_contract",
                message=(
                    f"{player_name} is on a two-way contract."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if manual is True or determination == "manual_review_required":
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_cba_manual_review",
                message=(
                    evidence_summary
                    or (
                        f"{player_name} requires player-level "
                        "CBA review."
                    )
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
    elif (
        determination == "verified_with_conditions"
        and not checks
    ):
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="unresolved_verified_condition",
                message=(
                    evidence_summary
                    or (
                        f"{player_name} is verified with "
                        "conditions that require transaction-"
                        "specific review."
                    )
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
    elif stage_pass is not True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_cba_stage_not_released",
                message=(
                    f"{player_name} did not receive a clear "
                    "player-CBA stage pass."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
    elif not checks:
        checks.append(
            CheckResult(
                status=Status.PASS,
                code="player_cba_verified_clear",
                message=(
                    f"{player_name} is verified clear at the "
                    "player-CBA evidence stage."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    return checks


def evaluate_pick(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
) -> list[CheckResult]:
    pick_right_id = str(pick_right_id).strip()
    record = runtime.pick_by_id.get(pick_right_id)

    if record is None:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="pick_right_not_found",
                message=(
                    f"Draft right {pick_right_id} is not in "
                    "the canonical future-pick inventory."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    candidate_team = normalize_team(
        record.get("candidate_team")
    )

    if candidate_team != team:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="pick_ownership_mismatch",
                message=(
                    f"Draft right {pick_right_id} is assigned "
                    f"to {candidate_team}, not {team}."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    if to_bool(
        record.get("standalone_trade_asset_flag")
    ) is not True:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="pick_not_standalone_asset",
                message=(
                    f"Draft right {pick_right_id} is an "
                    "accounting increment, not a standalone "
                    "trade asset."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    return [
        CheckResult(
            status=Status.MANUAL_REVIEW,
            code="pick_transaction_validation_pending",
            message=(
                f"Draft right {pick_right_id} exists and is "
                f"assigned to {team}, but trade-date ownership, "
                "encumbrance, and package-level Stepien checks "
                "must still run."
            ),
            team_abbreviation=team,
            pick_right_id=pick_right_id,
        )
    ]


def evaluate_side(
    runtime: RuntimeData,
    side: TradeSideRequest,
) -> SideEvaluation:
    team = normalize_team(side.team_abbreviation)
    player_ids = [
        normalize_player_id(value)
        for value in side.player_ids
        if normalize_player_id(value)
    ]
    pick_right_ids = [
        str(value).strip()
        for value in side.pick_right_ids
        if str(value).strip()
    ]
    checks: list[CheckResult] = []

    if team not in runtime.team_salary_by_team:
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="team_not_found",
                message=(
                    f"{team or '<blank>'} is not one of the "
                    "30 runtime teams."
                ),
                team_abbreviation=team or None,
            )
        )

    if len(player_ids) != len(set(player_ids)):
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="duplicate_player_on_side",
                message=(
                    f"{team} contains a duplicate outgoing "
                    "player."
                ),
                team_abbreviation=team,
            )
        )

    if len(pick_right_ids) != len(set(pick_right_ids)):
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="duplicate_pick_on_side",
                message=(
                    f"{team} contains a duplicate outgoing "
                    "draft right."
                ),
                team_abbreviation=team,
            )
        )

    outgoing_salary = 0.0

    for player_id in player_ids:
        record = runtime.trade_by_id.get(player_id)

        if record is not None:
            salary = to_float(
                record.get("trade_salary_2026_27")
            )

            if salary is not None:
                outgoing_salary += salary

        checks.extend(
            evaluate_player(
                runtime=runtime,
                team=team,
                player_id=player_id,
                outgoing_player_count=len(player_ids),
            )
        )

    for pick_right_id in pick_right_ids:
        checks.extend(
            evaluate_pick(
                runtime=runtime,
                team=team,
                pick_right_id=pick_right_id,
            )
        )

    return SideEvaluation(
        team_abbreviation=team,
        status=combine_statuses(
            [check.status for check in checks]
        ),
        outgoing_salary=round(outgoing_salary, 2),
        player_ids=player_ids,
        pick_right_ids=pick_right_ids,
        checks=checks,
    )


def evaluate_trade(
    runtime: RuntimeData,
    request: TradeRequest,
) -> TradeEvaluation:
    global_checks: list[CheckResult] = []
    side_a_team = normalize_team(
        request.side_a.team_abbreviation
    )
    side_b_team = normalize_team(
        request.side_b.team_abbreviation
    )

    if side_a_team == side_b_team:
        global_checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="same_team_on_both_sides",
                message=(
                    "A two-team trade requires two different "
                    "teams."
                ),
            )
        )

    side_a = evaluate_side(runtime, request.side_a)
    side_b = evaluate_side(runtime, request.side_b)

    if (
        side_a.player_ids
        or side_b.player_ids
    ):
        global_checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="salary_route_engine_pending",
                message=(
                    "Player salaries are loaded, but the "
                    "transaction-specific salary-matching and "
                    "hard-cap route engine is not connected in "
                    "V1. Team salary and apron values remain "
                    "proxy-only."
                ),
            )
        )

    statuses = [
        side_a.status,
        side_b.status,
        *[check.status for check in global_checks],
    ]

    return TradeEvaluation(
        status=combine_statuses(statuses),
        trade_date=request.trade_date,
        side_a=side_a,
        side_b=side_b,
        checks=global_checks,
    )


def result_to_dict(result: TradeEvaluation) -> dict[str, Any]:
    payload = asdict(result)

    def convert(value: Any) -> Any:
        if isinstance(value, Status):
            return value.value

        if isinstance(value, dict):
            return {
                key: convert(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [convert(item) for item in value]

        return value

    return convert(payload)


def find_player_id(
    runtime: RuntimeData,
    player_name: str,
) -> str:
    matches = runtime.trade_pool.loc[
        runtime.trade_pool["player_name"]
        .astype(str)
        .str.casefold()
        .eq(player_name.casefold()),
        "player_id",
    ].tolist()

    if len(matches) != 1:
        raise AssertionError(
            f"Expected one trade-pool match for "
            f"{player_name!r}; found {len(matches)}."
        )

    return str(matches[0])


def run_self_test() -> dict[str, Any]:
    runtime = load_runtime_data()

    trade_ids = set(runtime.trade_by_id)
    financial_ids = set(runtime.financial_by_id)
    market_ids = set(runtime.market_by_id)
    ratings_ids = set(runtime.ratings_by_id)
    cba_ids = set(runtime.player_cba_by_id)

    determination_counts = (
        runtime.player_cba[
            "player_cba_evidence_determination"
        ]
        .value_counts()
        .to_dict()
    )

    javonte_id = find_player_id(
        runtime,
        "Javonte Green",
    )
    javonte_team = normalize_team(
        runtime.trade_by_id[javonte_id][
            "current_team_2026_27"
        ]
    )
    javonte_status = evaluate_side(
        runtime,
        TradeSideRequest(
            team_abbreviation=javonte_team,
            player_ids=(javonte_id,),
        ),
    ).status

    zach_id = find_player_id(
        runtime,
        "Zach Collins",
    )
    zach_team = normalize_team(
        runtime.trade_by_id[zach_id][
            "current_team_2026_27"
        ]
    )
    zach_status = evaluate_side(
        runtime,
        TradeSideRequest(
            team_abbreviation=zach_team,
            player_ids=(zach_id,),
        ),
    ).status

    clear_rows = runtime.player_cba.loc[
        runtime.player_cba[
            "player_cba_evidence_determination"
        ].eq("verified_clear")
    ]

    clear_player_id = next(
        player_id
        for player_id in clear_rows["player_id"].tolist()
        if player_id in runtime.trade_by_id
    )
    clear_team = normalize_team(
        runtime.trade_by_id[clear_player_id][
            "current_team_2026_27"
        ]
    )
    clear_status = evaluate_side(
        runtime,
        TradeSideRequest(
            team_abbreviation=clear_team,
            player_ids=(clear_player_id,),
        ),
    ).status

    checks = {
        "trade_pool_rows_395": (
            len(runtime.trade_pool) == 395
        ),
        "financial_rows_582": (
            len(runtime.financial) == 582
        ),
        "market_rows_395": (
            len(runtime.market) == 395
        ),
        "team_salary_rows_30": (
            len(runtime.team_salary) == 30
        ),
        "pick_rows_174": (
            len(runtime.picks) == 174
        ),
        "stepien_rows_240": (
            len(runtime.stepien) == 240
        ),
        "player_cba_rows_311": (
            len(runtime.player_cba) == 311
        ),
        "player_cba_unique_ids_311": (
            len(cba_ids) == 311
        ),
        "trade_pool_missing_market_0": (
            len(trade_ids - market_ids) == 0
        ),
        "trade_pool_missing_financial_0": (
            len(trade_ids - financial_ids) == 0
        ),
        "trade_pool_missing_ratings_0": (
            len(trade_ids - ratings_ids) == 0
        ),
        "trade_pool_missing_player_cba_84": (
            len(trade_ids - cba_ids) == 84
        ),
        "verified_clear_180": (
            determination_counts.get(
                "verified_clear",
                0,
            )
            == 180
        ),
        "not_trade_eligible_81": (
            determination_counts.get(
                "not_trade_eligible",
                0,
            )
            == 81
        ),
        "manual_review_27": (
            determination_counts.get(
                "manual_review_required",
                0,
            )
            == 27
        ),
        "verified_with_conditions_23": (
            determination_counts.get(
                "verified_with_conditions",
                0,
            )
            == 23
        ),
        "known_blocked_player_is_blocked": (
            javonte_status == Status.BLOCKED
        ),
        "known_manual_player_is_manual": (
            zach_status == Status.MANUAL_REVIEW
        ),
        "verified_clear_player_passes": (
            clear_status == Status.PASS
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise AssertionError(
            "Freeform Trade Machine V1 self-test failed: "
            + ", ".join(failed)
        )

    return {
        "script": "freeform_trade_machine_engine_v1",
        "trade_date": TRADE_DATE,
        "checks": checks,
        "summary": {
            "trade_pool_players": len(trade_ids),
            "player_cba_decisions": len(cba_ids),
            "trade_pool_players_without_cba_decision": len(
                trade_ids - cba_ids
            ),
            "known_blocked_player": "Javonte Green",
            "known_manual_player": "Zach Collins",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        print(
            json.dumps(
                run_self_test(),
                indent=2,
            )
        )
        return 0

    runtime = load_runtime_data()

    print(
        json.dumps(
            {
                "script": (
                    "freeform_trade_machine_engine_v1"
                ),
                "trade_date": TRADE_DATE,
                "trade_pool_players": len(
                    runtime.trade_pool
                ),
                "player_cba_decisions": len(
                    runtime.player_cba
                ),
                "teams": len(runtime.team_salary),
                "future_pick_rights": len(runtime.picks),
                "status": "runtime_loaded",
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())