from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
APP_DATA = ROOT / "app_data"

TRADE_DATE = "2026-08-04"
MONEY_TOLERANCE = 0.01
VALIDATION_REVISION = "v3-right-evidence-and-package-stepien"
STEPIEN_DRAFT_YEARS = tuple(range(2027, 2034))
FROZEN_PICK_DRAFT_YEAR = 2034
CALENDAR_DRAFT_YEARS = tuple(range(2027, 2035))
MAX_PACKAGE_STEPIEN_STATES = 10_000


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
    listed_outgoing_salary: float = 0.0
    incoming_salary_for_matching: float = 0.0
    incoming_actual_team_salary: float = 0.0
    pretrade_team_salary: float | None = None
    pretrade_apron_team_salary: float | None = None
    posttrade_team_salary: float | None = None
    posttrade_apron_team_salary: float | None = None
    salary_matching_route: str = "not_evaluated"
    salary_matching_max_incoming: float | None = None
    salary_matching_margin: float | None = None
    salary_matching_passed: bool | None = None
    aggregation_passed: bool | None = None
    roster_passed: bool | None = None
    existing_hard_cap_passed: bool | None = None
    hard_cap_level_after_trade: str = "not_evaluated"
    hard_cap_passed: bool | None = None
    salary_issue: str = "not_evaluated"
    team_cba_evidence_complete: bool = False


@dataclass
class TradeEvaluation:
    status: Status
    trade_date: str
    side_a: SideEvaluation
    side_b: SideEvaluation
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class PlayerSalaryProfile:
    listed_salary: float = 0.0
    verified_outgoing_salary: float = 0.0
    verified_incoming_salary_for_opponent: float = 0.0
    player_count: int = 0
    two_way_count: int = 0
    evidence_complete: bool = True
    player_detail_manual: bool = False
    aggregation_blocked: bool = False


@dataclass
class RuntimeData:
    trade_pool: pd.DataFrame
    financial: pd.DataFrame
    market: pd.DataFrame
    team_salary: pd.DataFrame
    team_cba: pd.DataFrame
    picks: pd.DataFrame
    stepien: pd.DataFrame
    ratings: pd.DataFrame
    player_cba: pd.DataFrame
    right_legality: pd.DataFrame
    rules: dict[str, Any]
    trade_by_id: dict[str, dict[str, Any]]
    financial_by_id: dict[str, dict[str, Any]]
    market_by_id: dict[str, dict[str, Any]]
    ratings_by_id: dict[str, dict[str, Any]]
    player_cba_by_id: dict[str, dict[str, Any]]
    team_salary_by_team: dict[str, dict[str, Any]]
    team_cba_by_team: dict[str, dict[str, Any]]
    pick_by_id: dict[str, dict[str, Any]]
    right_legality_by_id: dict[str, dict[str, Any]]


def normalize_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]

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
        result = float(value)
    except (TypeError, ValueError):
        return None

    return result if math.isfinite(result) else None


def to_int(value: Any) -> int | None:
    number = to_float(value)

    if number is None:
        return None

    return int(number)


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
        "team_cba": (
            OUTPUTS
            / "mixed_player_pick_team_cba_decision_release_v1.csv"
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
        "right_legality": (
            OUTPUTS
            / "mixed_player_pick_right_legality_decision_release_v1.csv"
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
            "Required freeform Trade Machine V3 inputs are missing:\n"
            + "\n".join(missing)
        )

    trade_pool = pd.read_parquet(required_paths["trade_pool"])
    financial = pd.read_parquet(required_paths["financial"])
    market = pd.read_parquet(required_paths["market"])
    team_salary = pd.read_csv(required_paths["team_salary"])
    team_cba = pd.read_csv(required_paths["team_cba"])
    picks = pd.read_parquet(required_paths["picks"])
    stepien = pd.read_parquet(required_paths["stepien"])
    player_cba = pd.read_csv(required_paths["player_cba"])
    right_legality = pd.read_csv(
        required_paths["right_legality"]
    )

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
        (team_cba, "team_abbreviation"),
        (picks, "candidate_team"),
        (stepien, "team_abbreviation"),
        (right_legality, "candidate_team"),
    ]:
        if column in frame.columns:
            frame[column] = frame[column].map(normalize_team)

    picks["future_pick_right_id"] = (
        picks["future_pick_right_id"]
        .astype(str)
        .str.strip()
    )
    right_legality["future_pick_right_id"] = (
        right_legality["future_pick_right_id"]
        .astype(str)
        .str.strip()
    )

    return RuntimeData(
        trade_pool=trade_pool,
        financial=financial,
        market=market,
        team_salary=team_salary,
        team_cba=team_cba,
        picks=picks,
        stepien=stepien,
        ratings=ratings,
        player_cba=player_cba,
        right_legality=right_legality,
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
        team_cba_by_team=dataframe_index(
            team_cba,
            "team_abbreviation",
        ),
        pick_by_id=dataframe_index(
            picks,
            "future_pick_right_id",
        ),
        right_legality_by_id=dataframe_index(
            right_legality,
            "future_pick_right_id",
        ),
    )


def player_name(runtime: RuntimeData, player_id: str) -> str:
    record = runtime.trade_by_id.get(player_id, {})
    return str(record.get("player_name", player_id)).strip()


def player_verified_salary_values(
    runtime: RuntimeData,
    player_id: str,
) -> tuple[float | None, float | None, float | None]:
    player_id = normalize_player_id(player_id)
    trade_record = runtime.trade_by_id.get(player_id, {})
    decision = runtime.player_cba_by_id.get(player_id)

    listed = to_float(
        trade_record.get("trade_salary_2026_27")
    )

    if decision is None:
        return listed, None, None

    verified_outgoing = to_float(
        decision.get("trade_bonus_adjusted_outgoing_salary")
    )
    verified_incoming = to_float(
        decision.get("poison_pill_incoming_salary")
    )

    return listed, verified_outgoing, verified_incoming


def build_player_salary_profile(
    runtime: RuntimeData,
    player_ids: list[str],
) -> PlayerSalaryProfile:
    profile = PlayerSalaryProfile(player_count=len(player_ids))

    for player_id in player_ids:
        listed, outgoing, incoming = player_verified_salary_values(
            runtime,
            player_id,
        )
        decision = runtime.player_cba_by_id.get(player_id)

        if listed is not None:
            profile.listed_salary += listed

        if outgoing is None or incoming is None or decision is None:
            profile.evidence_complete = False
            if listed is not None:
                profile.verified_outgoing_salary += listed
                profile.verified_incoming_salary_for_opponent += listed
        else:
            profile.verified_outgoing_salary += outgoing
            profile.verified_incoming_salary_for_opponent += incoming

        if decision is None:
            profile.player_detail_manual = True
            continue

        determination = str(
            decision.get(
                "player_cba_evidence_determination",
                "",
            )
        ).strip().lower()

        manual = to_bool(
            decision.get("manual_review_required")
        ) is True
        consent = to_bool(
            decision.get("trade_consent_required")
        ) is True
        sign_and_trade = to_bool(
            decision.get("sign_and_trade_player")
        ) is True
        byc = to_bool(
            decision.get("base_year_compensation_active")
        ) is True
        two_way = to_bool(
            decision.get("two_way_contract_active")
        ) is True
        aggregation_restricted = to_bool(
            decision.get(
                "aggregation_restricted_on_trade_date"
            )
        ) is True
        trade_bonus_percent = to_float(
            decision.get("trade_bonus_percent")
        ) or 0.0
        remaining_bonus = to_float(
            decision.get("remaining_trade_bonus_amount")
        ) or 0.0
        active_trade_bonus = (
            trade_bonus_percent > 0
            and remaining_bonus > 0
        )

        if two_way:
            profile.two_way_count += 1

        if aggregation_restricted and len(player_ids) > 1:
            profile.aggregation_blocked = True

        if (
            manual
            or consent
            or sign_and_trade
            or byc
            or two_way
            or active_trade_bonus
            or determination == "manual_review_required"
        ):
            profile.player_detail_manual = True

    profile.listed_salary = round(profile.listed_salary, 2)
    profile.verified_outgoing_salary = round(
        profile.verified_outgoing_salary,
        2,
    )
    profile.verified_incoming_salary_for_opponent = round(
        profile.verified_incoming_salary_for_opponent,
        2,
    )

    return profile


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

    name = player_name(runtime, player_id)
    roster_team = normalize_team(
        trade_record.get("current_team_2026_27")
    )

    if roster_team != team:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="player_roster_mismatch",
                message=(
                    f"{name} belongs to {roster_team}, not "
                    f"{team}, in the runtime roster."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        ]

    listed, verified_outgoing, verified_incoming = (
        player_verified_salary_values(runtime, player_id)
    )

    if listed is None:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_salary_missing",
                message=(
                    f"{name} does not have a usable listed "
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
                    f"{name} is in the trade pool but is not "
                    "covered by the 311-player CBA decision "
                    "release."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
        return checks

    if verified_outgoing is None or verified_incoming is None:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="verified_salary_treatment_missing",
                message=(
                    f"{name} is missing exact sending- or "
                    "receiving-side salary treatment."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

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
    trade_eligible = to_bool(
        decision.get("trade_eligible_on_trade_date")
    )
    aggregation_restricted = to_bool(
        decision.get(
            "aggregation_restricted_on_trade_date"
        )
    )
    consent_required = to_bool(
        decision.get("trade_consent_required")
    )
    no_trade_clause = to_bool(
        decision.get("no_trade_clause_active")
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
    poison_pill = to_bool(
        decision.get("poison_pill_active")
    )
    trade_bonus_percent = to_float(
        decision.get("trade_bonus_percent")
    ) or 0.0
    remaining_bonus = to_float(
        decision.get("remaining_trade_bonus_amount")
    ) or 0.0
    active_trade_bonus = (
        trade_bonus_percent > 0
        and remaining_bonus > 0
    )
    restriction_end = str(
        decision.get("restriction_end_date", "")
    ).strip()
    evidence_summary = str(
        decision.get("evidence_summary", "")
    ).strip()

    if (
        determination == "not_trade_eligible"
        or trade_eligible is False
    ):
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="player_not_trade_eligible",
                message=(
                    f"{name} is not trade-eligible on "
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
        ]

    if extend_restricted is True:
        checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="extend_and_trade_restriction",
                message=(
                    f"{name} has an active extend-and-trade "
                    "restriction."
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
                    f"{name} may not be aggregated with "
                    "another outgoing player on the trade date."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if consent_required is True or no_trade_clause is True:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="player_consent_required",
                message=(
                    f"{name} requires player consent for this "
                    "transaction."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    if active_trade_bonus:
        checks.append(
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="active_trade_bonus",
                message=(
                    f"{name} has an active trade bonus of "
                    f"{trade_bonus_percent:.1%}; the exact "
                    "salary values are loaded, but waiver and "
                    "allocation mechanics require review."
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
                    f"{name} requires base-year compensation "
                    "treatment."
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
                    f"{name} is modeled as a sign-and-trade "
                    "player."
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
                message=f"{name} is on a two-way contract.",
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
                    or f"{name} requires player-level CBA review."
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
                    f"{name} did not receive a clear "
                    "player-CBA stage pass."
                ),
                team_abbreviation=team,
                player_id=player_id,
            )
        )
    elif not checks:
        if determination == "verified_with_conditions":
            code = "player_cba_verified_with_conditions"
            message = (
                evidence_summary
                or (
                    f"{name}'s verified condition is satisfied "
                    "by the selected package structure."
                )
            )
        elif poison_pill is True:
            code = "player_cba_asymmetric_salary_loaded"
            message = (
                f"{name}'s asymmetric salary treatment is "
                "loaded for both teams."
            )
        else:
            code = "player_cba_verified_clear"
            message = (
                f"{name} is verified clear at the player-CBA "
                "evidence stage."
            )

        checks.append(
            CheckResult(
                status=Status.PASS,
                code=code,
                message=message,
                team_abbreviation=team,
                player_id=player_id,
            )
        )

    return checks



def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_status(value: Any) -> str:
    return (
        clean_text(value)
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def parse_date_value(value: Any) -> date | None:
    text = clean_text(value)

    if not text:
        return None

    parsed = pd.to_datetime(text, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.date()


def parse_tokens(value: Any) -> list[str]:
    text = clean_text(value)

    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            payload = json.loads(text)

            if isinstance(payload, list):
                return sorted(
                    {
                        clean_text(item)
                        for item in payload
                        if clean_text(item)
                    }
                )
        except json.JSONDecodeError:
            pass

    return sorted(
        {
            clean_text(token)
            for token in re.split(r"[|;]", text)
            if clean_text(token)
        }
    )


def parse_rounds(value: Any) -> set[int]:
    normalized = normalize_status(value)
    rounds = {
        int(match)
        for match in re.findall(
            r"(?<!\d)[12](?!\d)",
            clean_text(value),
        )
    }

    if "first" in normalized:
        rounds.add(1)

    if "second" in normalized:
        rounds.add(2)

    return rounds


def source_asset_round(value: Any) -> int | None:
    match = re.search(
        r"(?:^|[_-])R([12])(?:[_-]|$)",
        clean_text(value).upper(),
    )

    return int(match.group(1)) if match else None


def calendar_row_is_current(
    row: pd.Series,
    trade_date: date,
) -> bool:
    if to_bool(
        row.get("source_authority_verified")
    ) is not True:
        return False

    as_of = parse_date_value(
        row.get("authoritative_source_as_of_date")
    )
    effective_start = parse_date_value(
        row.get("source_effective_start_date")
    )
    effective_end = parse_date_value(
        row.get("source_effective_end_date")
    )

    if as_of is None or effective_start is None:
        return False

    if as_of < trade_date or effective_start > trade_date:
        return False

    if (
        effective_end is not None
        and effective_end < trade_date
    ):
        return False

    return True


def deterministic_owner_team(
    row: pd.Series,
    known_teams: set[str],
) -> str:
    origin_team = normalize_team(
        row.get("team_abbreviation")
    )
    current_owner = normalize_team(
        row.get("own_first_round_current_owner_team")
    )
    deterministic = normalize_status(
        row.get("deterministic_first_round_availability")
    )
    control = normalize_status(
        row.get("own_first_round_control_status")
    )
    outgoing = normalize_status(
        row.get(
            "own_first_round_outgoing_obligation_status"
        )
    )
    swap = normalize_status(
        row.get("own_first_round_swap_status")
    )
    protection = normalize_status(
        row.get("own_first_round_protection_status")
    )

    if (
        deterministic == "available"
        and (
            current_owner not in known_teams
            or current_owner == origin_team
        )
    ):
        return origin_team

    deterministic_outgoing_conveyance = bool(
        control == "owed_out"
        and outgoing == "active"
        and swap == "none"
        and protection
        in {"unprotected", "not_applicable"}
        and current_owner in known_teams
        and current_owner != origin_team
    )

    if deterministic_outgoing_conveyance:
        return current_owner

    return ""


def build_stepien_baseline(
    runtime: RuntimeData,
    trade_date: date,
) -> tuple[
    pd.DataFrame,
    dict[tuple[str, int], int],
    dict[str, pd.Series],
    bool,
]:
    calendar = runtime.stepien.copy()
    calendar["draft_year"] = pd.to_numeric(
        calendar["draft_year"],
        errors="raise",
    ).astype(int)

    known_teams = set(
        calendar["team_abbreviation"]
        .map(normalize_team)
        .unique()
    )
    calendar["calendar_authority_and_date_passed"] = (
        calendar.apply(
            calendar_row_is_current,
            axis=1,
            trade_date=trade_date,
        )
    )
    calendar["deterministic_owner_team"] = (
        calendar.apply(
            deterministic_owner_team,
            axis=1,
            known_teams=known_teams,
        )
    )

    counts = {
        (team, year): 0
        for team in sorted(known_teams)
        for year in CALENDAR_DRAFT_YEARS
    }

    for row in calendar.itertuples(index=False):
        owner = clean_text(
            getattr(row, "deterministic_owner_team")
        )
        year = int(getattr(row, "draft_year"))

        if owner and year in CALENDAR_DRAFT_YEARS:
            counts[(owner, year)] = (
                counts.get((owner, year), 0) + 1
            )

    source_lookup = {
        clean_text(
            row.get("own_first_round_source_asset_id")
        ): row
        for _, row in calendar.iterrows()
        if clean_text(
            row.get("own_first_round_source_asset_id")
        )
    }

    global_current = bool(
        calendar["deterministic_calendar_ready"]
        .map(to_bool)
        .eq(True)
        .all()
        and calendar["source_authority_verified"]
        .map(to_bool)
        .eq(True)
        .all()
        and calendar[
            "calendar_authority_and_date_passed"
        ].all()
    )

    return (
        calendar,
        counts,
        source_lookup,
        global_current,
    )


def violating_pairs(
    counts: dict[int, int],
) -> list[str]:
    return [
        f"{year}-{year + 1}"
        for year in STEPIEN_DRAFT_YEARS[:-1]
        if (
            counts.get(year, 0)
            + counts.get(year + 1, 0)
            < 1
        )
    ]


def fallback_source_rows(
    right: dict[str, Any] | pd.Series,
    calendar: pd.DataFrame,
) -> list[pd.Series]:
    origin_teams = [
        normalize_team(team)
        for team in parse_tokens(
            right.get("originating_teams")
        )
    ]
    origin_teams = [
        team for team in origin_teams if team
    ]
    minimum = to_int(right.get("draft_year_min"))
    maximum = to_int(right.get("draft_year_max"))

    if (
        minimum is None
        or maximum is None
        or not origin_teams
    ):
        return []

    matches = calendar.loc[
        calendar["team_abbreviation"]
        .map(normalize_team)
        .isin(origin_teams)
        & calendar["draft_year"].between(
            minimum,
            maximum,
        )
    ]

    return [
        row
        for _, row in matches.iterrows()
    ]


def match_right_to_calendar(
    right: dict[str, Any] | pd.Series,
    calendar: pd.DataFrame,
    source_lookup: dict[str, pd.Series],
) -> tuple[
    list[pd.Series],
    str,
    list[str],
    list[str],
    list[str],
]:
    all_requested_ids = parse_tokens(
        right.get("source_assets")
    )
    first_round_right = (
        1 in parse_rounds(right.get("round_numbers"))
    )

    if not first_round_right:
        return (
            [],
            "not_applicable_non_first_round_right",
            [],
            [],
            all_requested_ids,
        )

    excluded_non_first_round_ids = [
        source_id
        for source_id in all_requested_ids
        if source_asset_round(source_id) == 2
    ]
    requested_ids = [
        source_id
        for source_id in all_requested_ids
        if source_asset_round(source_id) != 2
    ]
    matched_rows = [
        source_lookup[source_id]
        for source_id in requested_ids
        if source_id in source_lookup
    ]
    unmatched_ids = [
        source_id
        for source_id in requested_ids
        if source_id not in source_lookup
    ]

    if requested_ids and not unmatched_ids:
        return (
            matched_rows,
            "exact_source_asset_id",
            requested_ids,
            [],
            excluded_non_first_round_ids,
        )

    fallback = fallback_source_rows(
        right,
        calendar,
    )

    if fallback:
        deduplicated = {
            clean_text(
                row.get(
                    "own_first_round_source_asset_id"
                )
            ): row
            for row in fallback
        }

        return (
            list(deduplicated.values()),
            (
                "fallback_origin_team_and_year_"
                "manual_review"
            ),
            requested_ids,
            unmatched_ids,
            excluded_non_first_round_ids,
        )

    return (
        [],
        "unmatched_manual_review",
        requested_ids,
        unmatched_ids,
        excluded_non_first_round_ids,
    )


def evaluate_frozen_pick(
    first_round_right: bool,
    matched_rows: list[pd.Series],
    mapping_exact: bool,
    draft_year_max: Any,
) -> tuple[str, bool, bool]:
    if not first_round_right:
        return (
            "not_applicable_non_first_round_right",
            True,
            False,
        )

    maximum = to_int(draft_year_max)
    touches_2034 = bool(
        any(
            int(row["draft_year"])
            == FROZEN_PICK_DRAFT_YEAR
            for row in matched_rows
        )
        or (
            maximum is not None
            and maximum >= FROZEN_PICK_DRAFT_YEAR
        )
    )

    if not touches_2034:
        return (
            "not_applicable_outside_2034",
            True,
            False,
        )

    if not mapping_exact:
        return (
            "manual_review_2034_source_mapping",
            False,
            True,
        )

    statuses = {
        normalize_status(
            row.get(
                "second_apron_frozen_pick_status"
            )
        )
        for row in matched_rows
        if int(row["draft_year"])
        == FROZEN_PICK_DRAFT_YEAR
    }

    if not statuses:
        return (
            "manual_review_missing_2034_calendar_row",
            False,
            True,
        )

    if statuses & {"frozen", "penalized"}:
        return (
            "blocked_frozen_or_penalized_2034_first",
            False,
            False,
        )

    if not statuses.issubset(
        {"not_frozen", "unfrozen"}
    ):
        return (
            "manual_review_unresolved_2034_"
            "frozen_status",
            False,
            True,
        )

    return "passed_2034_not_frozen", True, False


def evaluate_single_right_stepien(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
    trade_date_text: str,
) -> dict[str, Any]:
    right = runtime.pick_by_id.get(pick_right_id)

    if right is None:
        return {
            "stepien_evaluation_status": (
                "manual_review_no_inventory_right"
            ),
            "stepien_legality_passed": False,
            "stepien_manual_review_required": True,
            "stepien_baseline_violating_pairs": "",
            "stepien_post_trade_violating_pairs": "",
            "stepien_evaluated_scenario_count": 0,
            "stepien_source_match_method": (
                "unmatched_manual_review"
            ),
            "stepien_requested_source_asset_ids": "",
            "stepien_matched_source_asset_ids": "",
            "stepien_unmatched_source_asset_ids": "",
            (
                "stepien_excluded_non_first_round_"
                "source_asset_ids"
            ): "",
            "frozen_pick_evaluation_status": (
                "manual_review_no_inventory_right"
            ),
            "frozen_pick_legality_passed": False,
            "calendar_authority_and_date_passed": False,
            "package_pick_legality_stage_passed": False,
            (
                "package_pick_legality_manual_"
                "review_required"
            ): True,
        }

    trade_date = date.fromisoformat(trade_date_text)
    (
        calendar,
        baseline_counts,
        source_lookup,
        global_current,
    ) = build_stepien_baseline(runtime, trade_date)

    normalized_team = normalize_team(team)
    first_round_right = (
        1 in parse_rounds(right.get("round_numbers"))
    )
    (
        matched_rows,
        match_method,
        requested_ids,
        unmatched_ids,
        excluded_non_first_round_ids,
    ) = match_right_to_calendar(
        right,
        calendar,
        source_lookup,
    )
    mapping_exact = (
        match_method == "exact_source_asset_id"
    )
    team_counts = {
        year: int(
            baseline_counts.get(
                (normalized_team, year),
                0,
            )
        )
        for year in STEPIEN_DRAFT_YEARS
    }
    baseline_violations = violating_pairs(
        team_counts
    )
    post_trade_violations: set[str] = set()
    worst_source = ""
    worst_year: int | None = None
    worst_removed_count = -1
    worst_removed_deterministic_pick_count = 0
    scenarios = 0
    relevant_rows = [
        row
        for row in matched_rows
        if int(row["draft_year"])
        in STEPIEN_DRAFT_YEARS
    ]

    if not first_round_right:
        stepien_status = (
            "not_applicable_non_first_round_right"
        )
        stepien_passed = True
        stepien_manual = False
    elif not mapping_exact:
        stepien_status = (
            "manual_review_source_mapping_not_exact"
        )
        stepien_passed = False
        stepien_manual = True
    elif baseline_violations:
        stepien_status = (
            "blocked_baseline_not_deterministically_clear"
        )
        stepien_passed = False
        stepien_manual = False
    elif not matched_rows:
        stepien_status = (
            "manual_review_no_calendar_source_match"
        )
        stepien_passed = False
        stepien_manual = True
    elif not relevant_rows:
        stepien_status = (
            "not_applicable_outside_stepien_horizon"
        )
        stepien_passed = True
        stepien_manual = False
    else:
        for source_row in relevant_rows:
            scenarios += 1
            scenario_counts = dict(team_counts)
            source_owner = normalize_team(
                source_row.get(
                    "deterministic_owner_team"
                )
            )
            source_year = int(
                source_row["draft_year"]
            )
            removed_count = 0

            if source_owner == normalized_team:
                before = scenario_counts.get(
                    source_year,
                    0,
                )
                scenario_counts[source_year] = max(
                    before - 1,
                    0,
                )
                removed_count = (
                    before
                    - scenario_counts[source_year]
                )

            scenario_violations = violating_pairs(
                scenario_counts
            )
            post_trade_violations.update(
                scenario_violations
            )

            if (
                len(scenario_violations)
                > worst_removed_count
            ):
                worst_removed_count = len(
                    scenario_violations
                )
                worst_source = clean_text(
                    source_row.get(
                        "own_first_round_source_asset_id"
                    )
                )
                worst_year = source_year
                worst_removed_deterministic_pick_count = (
                    removed_count
                )

        if post_trade_violations:
            stepien_status = (
                "blocked_consecutive_future_draft_pair"
            )
            stepien_passed = False
            stepien_manual = False
        else:
            stepien_status = (
                "passed_all_conservative_"
                "conveyance_scenarios"
            )
            stepien_passed = True
            stepien_manual = False

    frozen_status, frozen_passed, frozen_manual = (
        evaluate_frozen_pick(
            first_round_right,
            matched_rows,
            mapping_exact,
            right.get("draft_year_max"),
        )
    )
    stage_passed = bool(
        global_current
        and to_bool(
            right.get("standalone_trade_asset_flag")
        )
        is True
        and stepien_passed
        and frozen_passed
        and not stepien_manual
        and not frozen_manual
    )
    manual_review = bool(
        stepien_manual
        or frozen_manual
        or not global_current
    )

    return {
        "future_pick_right_id": pick_right_id,
        "inventory_candidate_team": (
            normalize_team(
                right.get("candidate_team")
            )
        ),
        "inventory_standalone_trade_asset_flag": (
            to_bool(
                right.get(
                    "standalone_trade_asset_flag"
                )
            )
            is True
        ),
        "first_round_right_flag": (
            first_round_right
        ),
        "stepien_evaluation_status": (
            stepien_status
        ),
        "stepien_legality_passed": (
            stepien_passed
        ),
        "stepien_manual_review_required": (
            stepien_manual
        ),
        "stepien_baseline_violating_pairs": (
            "|".join(baseline_violations)
        ),
        "stepien_post_trade_violating_pairs": (
            "|".join(
                sorted(post_trade_violations)
            )
        ),
        "stepien_evaluated_scenario_count": (
            scenarios
        ),
        "stepien_source_match_method": (
            match_method
        ),
        "stepien_requested_source_asset_ids": (
            "|".join(requested_ids)
        ),
        "stepien_matched_source_asset_ids": (
            "|".join(
                sorted(
                    {
                        clean_text(
                            row.get(
                                "own_first_round_"
                                "source_asset_id"
                            )
                        )
                        for row in matched_rows
                    }
                )
            )
        ),
        "stepien_unmatched_source_asset_ids": (
            "|".join(unmatched_ids)
        ),
        (
            "stepien_excluded_non_first_round_"
            "source_asset_ids"
        ): "|".join(
            excluded_non_first_round_ids
        ),
        (
            "stepien_worst_case_removed_"
            "source_asset_id"
        ): worst_source,
        (
            "stepien_worst_case_removed_"
            "draft_year"
        ): worst_year,
        (
            "stepien_worst_case_removed_"
            "deterministic_pick_count"
        ): worst_removed_deterministic_pick_count,
        "frozen_pick_evaluation_status": (
            frozen_status
        ),
        "frozen_pick_legality_passed": (
            frozen_passed
        ),
        "calendar_authority_and_date_passed": (
            global_current
        ),
        "package_pick_legality_stage_passed": (
            stage_passed
        ),
        (
            "package_pick_legality_manual_"
            "review_required"
        ): manual_review,
    }


def evaluate_pick(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
) -> list[CheckResult]:
    pick_right_id = clean_text(pick_right_id)
    record = runtime.pick_by_id.get(
        pick_right_id
    )

    if record is None:
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="pick_right_not_found",
                message=(
                    f"Draft right {pick_right_id} is "
                    "not in the canonical future-pick "
                    "inventory."
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
                    f"Draft right {pick_right_id} is "
                    f"assigned to {candidate_team}, "
                    f"not {team}."
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
                    f"Draft right {pick_right_id} is "
                    "an accounting increment, not a "
                    "standalone trade asset."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    decision = runtime.right_legality_by_id.get(
        pick_right_id
    )
    display_name = clean_text(
        record.get("right_display_name")
    ) or pick_right_id

    if decision is None:
        return [
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="pick_right_evidence_missing",
                message=(
                    f"{display_name} is in the canonical "
                    "inventory but is not covered by the "
                    "111-right legality decision release."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    evidence_team = normalize_team(
        decision.get("candidate_team")
    )

    if evidence_team != team:
        return [
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="pick_right_evidence_team_mismatch",
                message=(
                    f"{display_name}'s right-evidence "
                    f"team is {evidence_team}, not {team}."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    determination = normalize_status(
        decision.get(
            "right_legality_determination"
        )
    )
    reason = clean_text(
        decision.get("resolution_reason")
    )
    terms = clean_text(
        decision.get("right_terms_summary")
    )
    detail = reason or terms

    if (
        determination == "not_legal_as_modeled"
        or to_bool(
            decision.get("right_legality_blocked")
        )
        is True
    ):
        return [
            CheckResult(
                status=Status.BLOCKED,
                code="pick_right_not_legal_as_modeled",
                message=(
                    f"{display_name} is not legal as "
                    f"modeled."
                    + (
                        f" {detail}"
                        if detail
                        else ""
                    )
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    if (
        determination == "manual_review_required"
        or to_bool(
            decision.get(
                "right_legality_manual_review_required"
            )
        )
        is True
    ):
        return [
            CheckResult(
                status=Status.MANUAL_REVIEW,
                code="pick_right_manual_review_required",
                message=(
                    f"{display_name} requires manual "
                    f"right-legality review."
                    + (
                        f" {detail}"
                        if detail
                        else ""
                    )
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    if (
        determination == "legal_with_conditions"
        and to_bool(
            decision.get(
                "right_legality_stage_passed"
            )
        )
        is True
    ):
        return [
            CheckResult(
                status=Status.PASS,
                code="pick_right_evidence_passed",
                message=(
                    f"{display_name} passes the "
                    "trade-date ownership, encumbrance, "
                    "and standalone-right evidence stage."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )
        ]

    return [
        CheckResult(
            status=Status.MANUAL_REVIEW,
            code="pick_right_evidence_inconsistent",
            message=(
                f"{display_name} has an inconsistent "
                "right-legality decision record."
            ),
            team_abbreviation=team,
            pick_right_id=pick_right_id,
        )
    ]


def right_evidence_status(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
) -> Status:
    return combine_statuses(
        [
            result.status
            for result in evaluate_pick(
                runtime,
                team,
                pick_right_id,
            )
        ]
    )


def combined_pick_status_code(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
    stepien: dict[str, Any],
) -> tuple[Status, str]:
    if not bool(
        stepien.get(
            "package_pick_legality_stage_passed"
        )
    ):
        if bool(
            stepien.get(
                "package_pick_legality_manual_"
                "review_required"
            )
        ):
            return (
                Status.MANUAL_REVIEW,
                (
                    "manual_review_required_for_"
                    "stepien_or_frozen_pick_screen"
                ),
            )

        return (
            Status.BLOCKED,
            (
                "blocked_by_stepien_or_"
                "frozen_pick_screen"
            ),
        )

    evidence_status = right_evidence_status(
        runtime,
        team,
        pick_right_id,
    )

    if evidence_status == Status.MANUAL_REVIEW:
        return (
            Status.MANUAL_REVIEW,
            "right_legality_manual_review_required",
        )

    if evidence_status == Status.BLOCKED:
        return (
            Status.BLOCKED,
            "blocked_by_right_legality_evidence",
        )

    return (
        Status.PASS,
        (
            "passed_stepien_frozen_and_right_"
            "legality_evidence_remaining_full_"
            "cba_validation"
        ),
    )


def evaluate_multi_right_stepien(
    runtime: RuntimeData,
    team: str,
    pick_right_ids: list[str],
    trade_date_text: str,
) -> CheckResult:
    single_results = [
        evaluate_single_right_stepien(
            runtime,
            team,
            pick_right_id,
            trade_date_text,
        )
        for pick_right_id in pick_right_ids
    ]

    blocked = [
        result
        for result in single_results
        if (
            not result[
                "package_pick_legality_stage_passed"
            ]
            and not result[
                "package_pick_legality_manual_"
                "review_required"
            ]
        )
    ]

    if blocked:
        statuses = sorted(
            {
                str(
                    result[
                        "stepien_evaluation_status"
                    ]
                )
                for result in blocked
            }
        )

        return CheckResult(
            status=Status.BLOCKED,
            code="pick_package_stepien_blocked",
            message=(
                f"{team}'s selected draft-right "
                "package fails the Stepien or frozen-"
                "pick screen: "
                + ", ".join(statuses)
                + "."
            ),
            team_abbreviation=team,
        )

    manual = [
        result
        for result in single_results
        if result[
            "package_pick_legality_manual_"
            "review_required"
        ]
    ]

    if manual:
        statuses = sorted(
            {
                str(
                    result[
                        "stepien_evaluation_status"
                    ]
                )
                for result in manual
            }
        )

        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="pick_package_stepien_manual_review",
            message=(
                f"{team}'s selected draft-right "
                "package requires Stepien or frozen-"
                "pick review: "
                + ", ".join(statuses)
                + "."
            ),
            team_abbreviation=team,
        )

    first_round_ids = [
        pick_right_id
        for pick_right_id, result in zip(
            pick_right_ids,
            single_results,
            strict=True,
        )
        if result["first_round_right_flag"]
    ]

    if not first_round_ids:
        return CheckResult(
            status=Status.PASS,
            code="pick_package_stepien_not_applicable",
            message=(
                f"{team}'s selected rights contain "
                "no first-round source assets, so the "
                "Stepien rule is not applicable."
            ),
            team_abbreviation=team,
        )

    if len(first_round_ids) == 1:
        result = next(
            result
            for result in single_results
            if result["first_round_right_flag"]
        )

        return CheckResult(
            status=Status.PASS,
            code="pick_package_stepien_passed",
            message=(
                f"{team}'s selected right passes all "
                f"{result['stepien_evaluated_scenario_count']} "
                "conservative Stepien conveyance "
                "scenarios and the frozen-pick screen."
            ),
            team_abbreviation=team,
            pick_right_id=first_round_ids[0],
        )

    trade_date = date.fromisoformat(trade_date_text)
    (
        calendar,
        baseline_counts,
        source_lookup,
        global_current,
    ) = build_stepien_baseline(
        runtime,
        trade_date,
    )

    if not global_current:
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="pick_package_calendar_not_current",
            message=(
                "The authoritative first-round "
                "calendar is not current for the "
                f"requested trade date {trade_date_text}."
            ),
            team_abbreviation=team,
        )

    normalized_team = normalize_team(team)
    option_sets: list[list[pd.Series | None]] = []
    seen_source_sets: list[set[str]] = []

    for pick_right_id in first_round_ids:
        right = runtime.pick_by_id[pick_right_id]
        (
            matched_rows,
            match_method,
            _requested_ids,
            _unmatched_ids,
            _excluded_ids,
        ) = match_right_to_calendar(
            right,
            calendar,
            source_lookup,
        )

        if match_method != "exact_source_asset_id":
            return CheckResult(
                status=Status.MANUAL_REVIEW,
                code=(
                    "pick_package_source_mapping_"
                    "not_exact"
                ),
                message=(
                    f"{pick_right_id} does not have "
                    "an exact first-round source-asset "
                    "mapping."
                ),
                team_abbreviation=team,
                pick_right_id=pick_right_id,
            )

        relevant_rows = [
            row
            for row in matched_rows
            if int(row["draft_year"])
            in STEPIEN_DRAFT_YEARS
        ]
        option_sets.append(
            relevant_rows if relevant_rows else [None]
        )
        seen_source_sets.append(
            {
                clean_text(
                    row.get(
                        "own_first_round_source_asset_id"
                    )
                )
                for row in matched_rows
            }
        )

    overlapping_sources: set[str] = set()

    for index, current in enumerate(
        seen_source_sets
    ):
        for other in seen_source_sets[
            index + 1:
        ]:
            overlapping_sources.update(
                current.intersection(other)
            )

    if overlapping_sources:
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code=(
                "pick_package_overlapping_source_"
                "assets"
            ),
            message=(
                f"{team}'s selected rights overlap "
                "on physical source assets "
                + ", ".join(
                    sorted(overlapping_sources)
                )
                + "; simultaneous conveyance requires "
                "package-specific claim review."
            ),
            team_abbreviation=team,
        )

    baseline = tuple(
        int(
            baseline_counts.get(
                (normalized_team, year),
                0,
            )
        )
        for year in STEPIEN_DRAFT_YEARS
    )
    states: set[tuple[int, ...]] = {baseline}
    scenario_count = 1

    for options in option_sets:
        scenario_count *= len(options)
        next_states: set[tuple[int, ...]] = set()

        for state in states:
            for source_row in options:
                values = list(state)

                if source_row is not None:
                    owner = normalize_team(
                        source_row.get(
                            "deterministic_owner_team"
                        )
                    )
                    year = int(
                        source_row["draft_year"]
                    )

                    if (
                        owner == normalized_team
                        and year
                        in STEPIEN_DRAFT_YEARS
                    ):
                        position = (
                            year
                            - STEPIEN_DRAFT_YEARS[0]
                        )
                        values[position] = max(
                            values[position] - 1,
                            0,
                        )

                next_states.add(tuple(values))

                if (
                    len(next_states)
                    > MAX_PACKAGE_STEPIEN_STATES
                ):
                    return CheckResult(
                        status=Status.MANUAL_REVIEW,
                        code=(
                            "pick_package_stepien_"
                            "state_limit"
                        ),
                        message=(
                            f"{team}'s selected rights "
                            "create more than "
                            f"{MAX_PACKAGE_STEPIEN_STATES:,} "
                            "distinct Stepien states."
                        ),
                        team_abbreviation=team,
                    )

        states = next_states

    violations: set[str] = set()

    for state in states:
        counts = {
            year: state[index]
            for index, year in enumerate(
                STEPIEN_DRAFT_YEARS
            )
        }
        violations.update(
            violating_pairs(counts)
        )

    if violations:
        return CheckResult(
            status=Status.BLOCKED,
            code="pick_package_stepien_blocked",
            message=(
                f"{team}'s selected first-round "
                "rights can leave the team without a "
                "deterministically retained first in "
                "consecutive future drafts: "
                + ", ".join(sorted(violations))
                + f". Evaluated {scenario_count:,} "
                "conservative conveyance combinations."
            ),
            team_abbreviation=team,
        )

    return CheckResult(
        status=Status.PASS,
        code="pick_package_stepien_passed",
        message=(
            f"{team}'s selected first-round rights "
            f"pass {scenario_count:,} conservative "
            "combined conveyance scenarios with no "
            "consecutive-draft Stepien violation."
        ),
        team_abbreviation=team,
    )


def evaluate_pick_package(
    runtime: RuntimeData,
    team: str,
    pick_right_ids: list[str],
    trade_date_text: str,
) -> CheckResult:
    return evaluate_multi_right_stepien(
        runtime,
        team,
        pick_right_ids,
        trade_date_text,
    )



def evaluate_side_base(
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

    profile = build_player_salary_profile(runtime, player_ids)

    for player_id in player_ids:
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
        outgoing_salary=profile.verified_outgoing_salary,
        listed_outgoing_salary=profile.listed_salary,
        player_ids=player_ids,
        pick_right_ids=pick_right_ids,
        checks=checks,
    )


def rule_number(
    runtime: RuntimeData,
    key: str,
) -> float:
    value = runtime.rules.get("thresholds", {}).get(key)
    number = to_float(value)

    if number is None:
        raise ValueError(
            f"Missing numeric CBA threshold: {key}"
        )

    return number


def expanded_tpe_max(
    outgoing: float,
    salary_cap: float,
    salary_cap_2023_24: float,
    tpe_allowance: float,
) -> float:
    scaled_add = 7_500_000.0 * (
        salary_cap / salary_cap_2023_24
    )
    y = min(
        2.0 * outgoing + tpe_allowance,
        outgoing + scaled_add,
    )
    z = 1.25 * outgoing + tpe_allowance
    return max(y, z)


def salary_route(
    *,
    pre_team_salary: float,
    pre_apron_salary: float,
    outgoing: float,
    incoming_matching: float,
    incoming_actual: float,
    outgoing_count: int,
    aggregation_policy_blocked: bool,
    salary_cap: float,
    first_apron: float,
    second_apron: float,
    salary_cap_2023_24: float,
    tpe_allowance: float,
) -> tuple[str, float]:
    post_apron = pre_apron_salary - outgoing + incoming_actual
    allowance = (
        0.0
        if post_apron > first_apron + MONEY_TOLERANCE
        else tpe_allowance
    )
    under_cap = pre_team_salary < salary_cap - MONEY_TOLERANCE
    room_after_outgoing = max(
        0.0,
        salary_cap - (pre_team_salary - outgoing),
    )
    room_max = room_after_outgoing + allowance
    standard_max = outgoing + allowance
    expanded_max = expanded_tpe_max(
        outgoing,
        salary_cap,
        salary_cap_2023_24,
        tpe_allowance,
    )

    candidates: list[tuple[str, float]] = []

    if (
        under_cap
        and incoming_matching
        <= room_max + MONEY_TOLERANCE
    ):
        candidates.append(("room_under_cap", room_max))

    if (
        not under_cap
        and outgoing_count == 1
        and incoming_matching
        <= standard_max + MONEY_TOLERANCE
    ):
        candidates.append(("standard_tpe", standard_max))

    if (
        not under_cap
        and outgoing_count >= 2
        and not aggregation_policy_blocked
        and post_apron <= second_apron + MONEY_TOLERANCE
        and incoming_matching
        <= standard_max + MONEY_TOLERANCE
    ):
        candidates.append(
            ("aggregated_standard_tpe", standard_max)
        )

    if (
        (outgoing_count == 1 or not aggregation_policy_blocked)
        and post_apron <= first_apron + MONEY_TOLERANCE
        and incoming_matching
        <= expanded_max + MONEY_TOLERANCE
    ):
        candidates.append(("expanded_tpe", expanded_max))

    if candidates:
        return candidates[0]

    return (
        "none",
        max(room_max, standard_max, expanded_max),
    )


def aggregation_policy_is_blocked(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(
        re.search(r"not_allowed|manual_review|pending", text)
    )


def evaluate_salary_side(
    runtime: RuntimeData,
    side: SideEvaluation,
    own_profile: PlayerSalaryProfile,
    incoming_profile: PlayerSalaryProfile,
    transaction_player_detail_manual: bool,
) -> CheckResult:
    team = side.team_abbreviation
    team_record = runtime.team_cba_by_team.get(team)

    side.outgoing_salary = own_profile.verified_outgoing_salary
    side.listed_outgoing_salary = own_profile.listed_salary
    side.incoming_salary_for_matching = (
        incoming_profile.verified_incoming_salary_for_opponent
    )
    side.incoming_actual_team_salary = (
        incoming_profile.verified_outgoing_salary
    )

    if team_record is None:
        side.salary_issue = "team_cba_evidence_missing"
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="team_cba_evidence_missing",
            message=(
                f"{team} is missing from the verified 30-team "
                "CBA decision release."
            ),
            team_abbreviation=team,
        )

    pre_team_salary = to_float(
        team_record.get("verified_team_salary_value")
    )
    pre_apron_salary = to_float(
        team_record.get("verified_apron_team_salary_value")
    )
    standard_count = to_int(
        team_record.get("standard_contract_count")
    )
    two_way_count = to_int(
        team_record.get("two_way_contract_count")
    )
    hard_cap_active = to_bool(
        team_record.get("hard_cap_active")
    )
    hard_cap_level_source = str(
        team_record.get("hard_cap_level", "")
    ).strip().lower()
    team_manual = to_bool(
        team_record.get("team_cba_manual_review_required")
    ) is True
    team_stage_pass = to_bool(
        team_record.get("team_cba_stage_pass")
    ) is True

    evidence_missing = any(
        value is None
        for value in [
            pre_team_salary,
            pre_apron_salary,
            standard_count,
            two_way_count,
            hard_cap_active,
        ]
    ) or not own_profile.evidence_complete or not incoming_profile.evidence_complete

    side.pretrade_team_salary = pre_team_salary
    side.pretrade_apron_team_salary = pre_apron_salary
    side.team_cba_evidence_complete = (
        not evidence_missing
        and team_stage_pass
        and not team_manual
    )

    if evidence_missing:
        side.salary_issue = "evidence_missing_manual_review"
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="salary_evidence_missing",
            message=(
                f"{team}'s exact salary route cannot be released "
                "because team or player salary evidence is "
                "incomplete."
            ),
            team_abbreviation=team,
        )

    assert pre_team_salary is not None
    assert pre_apron_salary is not None
    assert standard_count is not None
    assert two_way_count is not None
    assert hard_cap_active is not None

    salary_cap = rule_number(runtime, "salary_cap")
    first_apron = rule_number(runtime, "first_apron")
    second_apron = rule_number(runtime, "second_apron")
    salary_cap_2023_24 = rule_number(
        runtime,
        "salary_cap_2023_24",
    )
    tpe_allowance = rule_number(runtime, "tpe_allowance")
    offseason_roster_max = int(
        rule_number(runtime, "offseason_total_roster_max")
    )
    two_way_roster_max = int(
        rule_number(runtime, "two_way_roster_max")
    )

    outgoing = own_profile.verified_outgoing_salary
    incoming_matching = (
        incoming_profile.verified_incoming_salary_for_opponent
    )
    incoming_actual = incoming_profile.verified_outgoing_salary
    outgoing_count = own_profile.player_count
    incoming_count = incoming_profile.player_count
    post_team = pre_team_salary - outgoing + incoming_actual
    post_apron = pre_apron_salary - outgoing + incoming_actual

    existing_first_hard_cap = (
        hard_cap_active
        and "first" in hard_cap_level_source
    )
    existing_second_hard_cap = (
        hard_cap_active
        and "second" in hard_cap_level_source
    )
    hard_cap_config_invalid = (
        hard_cap_active
        and not (
            existing_first_hard_cap
            or existing_second_hard_cap
        )
    )
    aggregation_policy_blocked = (
        aggregation_policy_is_blocked(
            team_record.get("aggregation_allowed")
        )
    )

    route, max_incoming = salary_route(
        pre_team_salary=pre_team_salary,
        pre_apron_salary=pre_apron_salary,
        outgoing=outgoing,
        incoming_matching=incoming_matching,
        incoming_actual=incoming_actual,
        outgoing_count=outgoing_count,
        # Team salary matching must evaluate the team's aggregation
        # policy independently from player-level aggregation restrictions.
        # A restricted player can block the overall trade while the team's
        # salary route itself still passes, matching the validated V9 design.
        aggregation_policy_blocked=aggregation_policy_blocked,
        salary_cap=salary_cap,
        first_apron=first_apron,
        second_apron=second_apron,
        salary_cap_2023_24=salary_cap_2023_24,
        tpe_allowance=tpe_allowance,
    )

    post_standard_count = (
        standard_count
        - (outgoing_count - own_profile.two_way_count)
        + (incoming_count - incoming_profile.two_way_count)
    )
    post_two_way_count = (
        two_way_count
        - own_profile.two_way_count
        + incoming_profile.two_way_count
    )
    post_total_count = post_standard_count + post_two_way_count

    roster_passed = (
        post_standard_count >= 0
        and post_two_way_count >= 0
        and post_total_count <= offseason_roster_max
        and post_two_way_count <= two_way_roster_max
    )
    existing_hard_cap_passed = not (
        hard_cap_config_invalid
        or (
            existing_first_hard_cap
            and post_apron > first_apron + MONEY_TOLERANCE
        )
        or (
            existing_second_hard_cap
            and post_apron > second_apron + MONEY_TOLERANCE
        )
    )
    aggregation_passed = (
        outgoing_count <= 1
        or route == "room_under_cap"
        or not aggregation_policy_blocked
    )
    salary_matching_passed = route != "none"

    if existing_first_hard_cap or route == "expanded_tpe":
        hard_cap_after = "first_apron"
    elif (
        existing_second_hard_cap
        or route == "aggregated_standard_tpe"
    ):
        hard_cap_after = "second_apron"
    else:
        hard_cap_after = "none"

    if hard_cap_after == "first_apron":
        transaction_hard_cap_passed = (
            post_apron <= first_apron + MONEY_TOLERANCE
        )
    elif hard_cap_after == "second_apron":
        transaction_hard_cap_passed = (
            post_apron <= second_apron + MONEY_TOLERANCE
        )
    else:
        transaction_hard_cap_passed = True

    if not roster_passed:
        issue = "offseason_roster_limit_failed"
    elif not existing_hard_cap_passed:
        issue = "existing_hard_cap_failed"
    elif not aggregation_passed:
        issue = "team_aggregation_policy_failed"
    elif not salary_matching_passed:
        issue = "salary_matching_failed"
    elif not transaction_hard_cap_passed:
        issue = "transaction_hard_cap_failed"
    else:
        issue = "passed"

    side.posttrade_team_salary = round(post_team, 2)
    side.posttrade_apron_team_salary = round(post_apron, 2)
    side.salary_matching_route = route
    side.salary_matching_max_incoming = round(max_incoming, 2)
    side.salary_matching_margin = round(
        max_incoming - incoming_matching,
        2,
    )
    side.salary_matching_passed = salary_matching_passed
    side.aggregation_passed = aggregation_passed
    side.roster_passed = roster_passed
    side.existing_hard_cap_passed = existing_hard_cap_passed
    side.hard_cap_level_after_trade = hard_cap_after
    side.hard_cap_passed = transaction_hard_cap_passed
    side.salary_issue = issue

    deterministic_release_allowed = (
        team_stage_pass
        and not team_manual
        and not transaction_player_detail_manual
    )

    if issue != "passed":
        status = (
            Status.BLOCKED
            if deterministic_release_allowed
            else Status.MANUAL_REVIEW
        )
        return CheckResult(
            status=status,
            code=issue,
            message=(
                f"{team} salary route result: {issue.replace('_', ' ')}. "
                f"Route={route}; incoming for matching "
                f"${incoming_matching:,.0f}; maximum "
                f"${max_incoming:,.0f}; post-trade apron salary "
                f"${post_apron:,.0f}."
            ),
            team_abbreviation=team,
        )

    if team_manual or not team_stage_pass:
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="team_cba_manual_review",
            message=(
                f"{team}'s calculated salary route is {route}, "
                "but its team-CBA decision remains manual review."
            ),
            team_abbreviation=team,
        )

    if transaction_player_detail_manual:
        return CheckResult(
            status=Status.MANUAL_REVIEW,
            code="transaction_player_mechanics_manual_review",
            message=(
                f"{team} passes the {route} salary route with "
                f"${side.salary_matching_margin:,.0f} of margin, "
                "but transaction-specific player mechanics "
                "prevent deterministic release."
            ),
            team_abbreviation=team,
        )

    return CheckResult(
        status=Status.PASS,
        code="salary_route_passed",
        message=(
            f"{team} passes the {route} route. Incoming salary "
            f"for matching is ${incoming_matching:,.0f} against "
            f"a ${max_incoming:,.0f} maximum, leaving "
            f"${side.salary_matching_margin:,.0f} of margin."
        ),
        team_abbreviation=team,
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

    side_a = evaluate_side_base(runtime, request.side_a)
    side_b = evaluate_side_base(runtime, request.side_b)

    if not (
        side_a.player_ids
        or side_a.pick_right_ids
        or side_b.player_ids
        or side_b.pick_right_ids
    ):
        global_checks.append(
            CheckResult(
                status=Status.BLOCKED,
                code="empty_trade",
                message=(
                    "A trade must include at least one player "
                    "or draft right."
                ),
            )
        )

    if side_a.pick_right_ids:
        side_a.checks.append(
            evaluate_pick_package(
                runtime,
                side_a.team_abbreviation,
                side_a.pick_right_ids,
                request.trade_date,
            )
        )

    if side_b.pick_right_ids:
        side_b.checks.append(
            evaluate_pick_package(
                runtime,
                side_b.team_abbreviation,
                side_b.pick_right_ids,
                request.trade_date,
            )
        )

    a_profile = build_player_salary_profile(
        runtime,
        side_a.player_ids,
    )
    b_profile = build_player_salary_profile(
        runtime,
        side_b.player_ids,
    )

    if side_a.player_ids or side_b.player_ids:
        transaction_player_detail_manual = (
            a_profile.player_detail_manual
            or b_profile.player_detail_manual
        )

        side_a.checks.append(
            evaluate_salary_side(
                runtime,
                side_a,
                a_profile,
                b_profile,
                transaction_player_detail_manual,
            )
        )
        side_b.checks.append(
            evaluate_salary_side(
                runtime,
                side_b,
                b_profile,
                a_profile,
                transaction_player_detail_manual,
            )
        )
    side_a.status = combine_statuses(
        [check.status for check in side_a.checks]
    )
    side_b.status = combine_statuses(
        [check.status for check in side_b.checks]
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
    name: str,
) -> str:
    matches = runtime.trade_pool.loc[
        runtime.trade_pool["player_name"]
        .astype(str)
        .str.casefold()
        .eq(name.casefold()),
        "player_id",
    ].tolist()

    if len(matches) != 1:
        raise AssertionError(
            f"Expected one trade-pool match for {name!r}; "
            f"found {len(matches)}."
        )

    return str(matches[0])


def pure_route_self_tests(runtime: RuntimeData) -> dict[str, bool]:
    salary_cap = rule_number(runtime, "salary_cap")
    first_apron = rule_number(runtime, "first_apron")
    second_apron = rule_number(runtime, "second_apron")
    salary_cap_2023_24 = rule_number(
        runtime,
        "salary_cap_2023_24",
    )
    allowance = rule_number(runtime, "tpe_allowance")

    def route(**kwargs: Any) -> tuple[str, float]:
        return salary_route(
            salary_cap=salary_cap,
            first_apron=first_apron,
            second_apron=second_apron,
            salary_cap_2023_24=salary_cap_2023_24,
            tpe_allowance=allowance,
            **kwargs,
        )

    standard = route(
        pre_team_salary=190_000_000,
        pre_apron_salary=190_000_000,
        outgoing=10_000_000,
        incoming_matching=10_200_000,
        incoming_actual=10_200_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    first_apron_case = route(
        pre_team_salary=220_000_000,
        pre_apron_salary=220_000_000,
        outgoing=10_000_000,
        incoming_matching=10_100_000,
        incoming_actual=10_100_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    aggregation_blocked = route(
        pre_team_salary=220_000_000,
        pre_apron_salary=220_000_000,
        outgoing=20_000_000,
        incoming_matching=19_000_000,
        incoming_actual=19_000_000,
        outgoing_count=2,
        aggregation_policy_blocked=True,
    )
    expanded = route(
        pre_team_salary=190_000_000,
        pre_apron_salary=190_000_000,
        outgoing=10_000_000,
        incoming_matching=18_000_000,
        incoming_actual=18_000_000,
        outgoing_count=1,
        aggregation_policy_blocked=False,
    )
    expected_scaled = (
        7_500_000.0
        * salary_cap
        / salary_cap_2023_24
    )
    observed_scaled = rule_number(
        runtime,
        "expanded_tpe_scaled_add",
    )

    return {
        "scaled_expanded_tpe_amount": math.isclose(
            observed_scaled,
            expected_scaled,
            abs_tol=0.01,
        ),
        "standard_tpe_selected": standard[0] == "standard_tpe",
        "first_apron_removes_250k_allowance": (
            first_apron_case[0] == "none"
        ),
        "blocked_aggregation_has_no_route": (
            aggregation_blocked[0] == "none"
        ),
        "expanded_tpe_selected_when_needed": (
            expanded[0] == "expanded_tpe"
        ),
    }


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
    right_determination_counts = (
        runtime.right_legality[
            "right_legality_determination"
        ]
        .value_counts()
        .to_dict()
    )
    standalone_right_count = int(
        runtime.picks[
            "standalone_trade_asset_flag"
        ]
        .map(to_bool)
        .eq(True)
        .sum()
    )
    deterministic_calendar_rows = int(
        runtime.stepien[
            "deterministic_calendar_ready"
        ]
        .map(to_bool)
        .eq(True)
        .sum()
    )
    team_manual = runtime.team_cba.loc[
        runtime.team_cba[
            "team_cba_manual_review_required"
        ].map(to_bool).eq(True),
        "team_abbreviation",
    ].tolist()
    team_stage_pass_count = int(
        runtime.team_cba["team_cba_stage_pass"]
        .map(to_bool)
        .eq(True)
        .sum()
    )

    javonte_id = find_player_id(runtime, "Javonte Green")
    javonte_team = normalize_team(
        runtime.trade_by_id[javonte_id][
            "current_team_2026_27"
        ]
    )
    javonte_status = evaluate_side_base(
        runtime,
        TradeSideRequest(
            team_abbreviation=javonte_team,
            player_ids=(javonte_id,),
        ),
    ).status

    zach_id = find_player_id(runtime, "Zach Collins")
    zach_team = normalize_team(
        runtime.trade_by_id[zach_id][
            "current_team_2026_27"
        ]
    )
    zach_status = evaluate_side_base(
        runtime,
        TradeSideRequest(
            team_abbreviation=zach_team,
            player_ids=(zach_id,),
        ),
    ).status

    conditional_rows = runtime.player_cba.loc[
        runtime.player_cba[
            "player_cba_evidence_determination"
        ].eq("verified_with_conditions")
    ]
    conditional_single_id = next(
        player_id
        for player_id in conditional_rows["player_id"].tolist()
        if (
            player_id in runtime.trade_by_id
            and to_bool(
                runtime.player_cba_by_id[player_id].get(
                    "manual_review_required"
                )
            )
            is False
            and to_bool(
                runtime.player_cba_by_id[player_id].get(
                    "trade_consent_required"
                )
            )
            is False
            and to_bool(
                runtime.player_cba_by_id[player_id].get(
                    "sign_and_trade_player"
                )
            )
            is False
            and to_bool(
                runtime.player_cba_by_id[player_id].get(
                    "base_year_compensation_active"
                )
            )
            is False
            and to_bool(
                runtime.player_cba_by_id[player_id].get(
                    "two_way_contract_active"
                )
            )
            is False
            and not (
                (
                    to_float(
                        runtime.player_cba_by_id[player_id].get(
                            "trade_bonus_percent"
                        )
                    )
                    or 0.0
                )
                > 0
                and (
                    to_float(
                        runtime.player_cba_by_id[player_id].get(
                            "remaining_trade_bonus_amount"
                        )
                    )
                    or 0.0
                )
                > 0
            )
        )
    )
    conditional_team = normalize_team(
        runtime.trade_by_id[conditional_single_id][
            "current_team_2026_27"
        ]
    )
    conditional_single_status = evaluate_side_base(
        runtime,
        TradeSideRequest(
            team_abbreviation=conditional_team,
            player_ids=(conditional_single_id,),
        ),
    ).status

    legal_right_id = str(
        runtime.right_legality.loc[
            runtime.right_legality[
                "right_legality_determination"
            ].eq("legal_with_conditions"),
            "future_pick_right_id",
        ].iloc[0]
    )
    legal_right_team = normalize_team(
        runtime.right_legality_by_id[
            legal_right_id
        ].get("candidate_team")
    )
    legal_right_evidence_status = (
        right_evidence_status(
            runtime,
            legal_right_team,
            legal_right_id,
        )
    )

    manual_right_id = str(
        runtime.right_legality.loc[
            runtime.right_legality[
                "right_legality_determination"
            ].eq("manual_review_required"),
            "future_pick_right_id",
        ].iloc[0]
    )
    manual_right_team = normalize_team(
        runtime.right_legality_by_id[
            manual_right_id
        ].get("candidate_team")
    )
    manual_right_evidence_status = (
        right_evidence_status(
            runtime,
            manual_right_team,
            manual_right_id,
        )
    )

    blocked_right_id = str(
        runtime.right_legality.loc[
            runtime.right_legality[
                "right_legality_determination"
            ].eq("not_legal_as_modeled"),
            "future_pick_right_id",
        ].iloc[0]
    )
    blocked_right_team = normalize_team(
        runtime.right_legality_by_id[
            blocked_right_id
        ].get("candidate_team")
    )
    blocked_right_evidence_status = (
        right_evidence_status(
            runtime,
            blocked_right_team,
            blocked_right_id,
        )
    )

    known_teams = sorted(runtime.team_salary_by_team)
    empty_trade_status = evaluate_trade(
        runtime,
        TradeRequest(
            side_a=TradeSideRequest(
                team_abbreviation=known_teams[0],
            ),
            side_b=TradeSideRequest(
                team_abbreviation=known_teams[1],
            ),
        ),
    ).status

    checks = {
        "empty_trade_is_blocked": (
            empty_trade_status == Status.BLOCKED
        ),
        "trade_pool_rows_395": len(runtime.trade_pool) == 395,
        "financial_rows_582": len(runtime.financial) == 582,
        "market_rows_395": len(runtime.market) == 395,
        "team_salary_rows_30": len(runtime.team_salary) == 30,
        "team_cba_rows_30": len(runtime.team_cba) == 30,
        "team_cba_unique_teams_30": (
            len(runtime.team_cba_by_team) == 30
        ),
        "team_cba_stage_pass_24": team_stage_pass_count == 24,
        "team_cba_manual_teams_exact": (
            set(team_manual)
            == {"CHA", "IND", "LAL", "MEM", "MIN", "SAS"}
        ),
        "pick_rows_174": len(runtime.picks) == 174,
        "standalone_pick_rights_172": (
            standalone_right_count == 172
        ),
        "stepien_rows_240": len(runtime.stepien) == 240,
        "stepien_deterministic_ready_240": (
            deterministic_calendar_rows == 240
        ),
        "right_legality_rows_111": (
            len(runtime.right_legality) == 111
        ),
        "right_legality_unique_ids_111": (
            len(runtime.right_legality_by_id) == 111
        ),
        "right_legal_with_conditions_106": (
            right_determination_counts.get(
                "legal_with_conditions",
                0,
            )
            == 106
        ),
        "right_manual_review_3": (
            right_determination_counts.get(
                "manual_review_required",
                0,
            )
            == 3
        ),
        "right_not_legal_as_modeled_2": (
            right_determination_counts.get(
                "not_legal_as_modeled",
                0,
            )
            == 2
        ),
        "known_legal_right_evidence_passes": (
            legal_right_evidence_status
            == Status.PASS
        ),
        "known_manual_right_is_manual": (
            manual_right_evidence_status
            == Status.MANUAL_REVIEW
        ),
        "known_blocked_right_is_blocked": (
            blocked_right_evidence_status
            == Status.BLOCKED
        ),
        "player_cba_rows_311": len(runtime.player_cba) == 311,
        "player_cba_unique_ids_311": len(cba_ids) == 311,
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
            determination_counts.get("verified_clear", 0) == 180
        ),
        "not_trade_eligible_81": (
            determination_counts.get("not_trade_eligible", 0)
            == 81
        ),
        "manual_review_27": (
            determination_counts.get("manual_review_required", 0)
            == 27
        ),
        "verified_with_conditions_23": (
            determination_counts.get("verified_with_conditions", 0)
            == 23
        ),
        "known_blocked_player_is_blocked": (
            javonte_status == Status.BLOCKED
        ),
        "known_manual_player_is_manual": (
            zach_status == Status.MANUAL_REVIEW
        ),
        "conditional_single_player_can_pass": (
            conditional_single_status == Status.PASS
        ),
        **pure_route_self_tests(runtime),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise AssertionError(
            "Freeform Trade Machine V3 self-test failed: "
            + ", ".join(failed)
        )

    return {
        "script": "freeform_trade_machine_engine_v3",
        "trade_date": TRADE_DATE,
        "validation_revision": VALIDATION_REVISION,
        "checks": checks,
        "summary": {
            "trade_pool_players": len(trade_ids),
            "player_cba_decisions": len(cba_ids),
            "team_cba_decisions": len(runtime.team_cba_by_team),
            "team_cba_stage_pass": team_stage_pass_count,
            "right_legality_decisions": (
                len(runtime.right_legality_by_id)
            ),
            "standalone_pick_rights": (
                standalone_right_count
            ),
            "deterministic_stepien_team_years": (
                deterministic_calendar_rows
            ),
            "team_cba_manual_teams": sorted(team_manual),
            "known_blocked_player": "Javonte Green",
            "known_manual_player": "Zach Collins",
            "conditional_single_player": player_name(
                runtime,
                conditional_single_id,
            ),
        },
    }


def values_close(
    observed: Any,
    expected: Any,
    tolerance: float = 0.02,
) -> bool:
    observed_float = to_float(observed)
    expected_float = to_float(expected)

    if observed_float is None and expected_float is None:
        return True

    if observed_float is None or expected_float is None:
        return False

    return math.isclose(
        observed_float,
        expected_float,
        abs_tol=tolerance,
    )


def validate_against_v9(
    runtime: RuntimeData,
    sample_size: int,
) -> dict[str, Any]:
    files = {
        "one_for_one": (
            OUTPUTS
            / "one_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
        "two_for_one": (
            OUTPUTS
            / "two_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
    }

    missing = [
        str(path)
        for path in files.values()
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "V9 validation files are missing:\n"
            + "\n".join(missing)
        )

    columns = [
        "optimizer_candidate_id",
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "full_cba_evidence_complete",
        "player_cba_decisions_matched",
        "package_player_cba_stage_passed",
        "full_cba_player_detail_manual_review_required",
        "team_a_final_cba_outgoing_salary",
        "team_b_final_cba_outgoing_salary",
        "team_a_final_cba_incoming_salary_for_matching",
        "team_b_final_cba_incoming_salary_for_matching",
        "team_a_final_cba_incoming_actual_team_salary",
        "team_b_final_cba_incoming_actual_team_salary",
        "team_a_final_cba_posttrade_team_salary",
        "team_b_final_cba_posttrade_team_salary",
        "team_a_final_cba_posttrade_apron_team_salary",
        "team_b_final_cba_posttrade_apron_team_salary",
        "team_a_final_cba_salary_matching_route",
        "team_b_final_cba_salary_matching_route",
        "team_a_final_cba_salary_matching_max_incoming",
        "team_b_final_cba_salary_matching_max_incoming",
        "team_a_final_cba_hard_cap_level_after_trade",
        "team_b_final_cba_hard_cap_level_after_trade",
        "team_a_final_cba_issue",
        "team_b_final_cba_issue",
    ]

    comparison_fields = {
        "outgoing_salary": "outgoing_salary",
        "incoming_salary_for_matching": (
            "incoming_salary_for_matching"
        ),
        "incoming_actual_team_salary": (
            "incoming_actual_team_salary"
        ),
        "posttrade_team_salary": "posttrade_team_salary",
        "posttrade_apron_team_salary": (
            "posttrade_apron_team_salary"
        ),
        "salary_matching_route": "salary_matching_route",
        "salary_matching_max_incoming": (
            "salary_matching_max_incoming"
        ),
        "hard_cap_level_after_trade": (
            "hard_cap_level_after_trade"
        ),
        "issue": "salary_issue",
    }

    branch_results: dict[str, Any] = {}
    total_compared = 0
    total_mismatches = 0
    examples: list[dict[str, Any]] = []

    for branch, path in files.items():
        frame = pd.read_parquet(path, columns=columns)

        # V9 contains every upstream package, including rows that
        # intentionally failed closed because player/team evidence was
        # incomplete. Those rows carry zero/null salary placeholders in
        # V9, while the freeform engine preserves listed salary values for
        # display before returning manual review. They are not equivalent
        # inputs and must not be used to validate the exact salary-route
        # calculation.
        comparable = frame.loc[
            frame["full_cba_evidence_complete"].eq(True)
            & frame["player_cba_decisions_matched"].eq(True)
        ].copy()

        if comparable.empty:
            raise AssertionError(
                f"No evidence-complete V9 rows were available for {branch}."
            )

        selected = comparable.sample(
            n=min(sample_size, len(comparable)),
            random_state=20260806,
        )
        branch_mismatches = 0

        for row in selected.to_dict(orient="records"):
            request = TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=row["team_a"],
                    player_ids=tuple(
                        split_player_ids(row["side_a_player_ids"])
                    ),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=row["team_b"],
                    player_ids=tuple(
                        split_player_ids(row["side_b_player_ids"])
                    ),
                ),
            )
            result = evaluate_trade(runtime, request)

            for side_name, side_result in [
                ("a", result.side_a),
                ("b", result.side_b),
            ]:
                for expected_suffix, attribute in comparison_fields.items():
                    expected_column = (
                        f"team_{side_name}_final_cba_{expected_suffix}"
                    )
                    expected = row[expected_column]
                    observed = getattr(side_result, attribute)

                    if isinstance(expected, str):
                        matched = str(observed) == expected
                    else:
                        matched = values_close(observed, expected)

                    total_compared += 1

                    if not matched:
                        total_mismatches += 1
                        branch_mismatches += 1

                        if len(examples) < 20:
                            examples.append(
                                {
                                    "branch": branch,
                                    "candidate_id": row[
                                        "optimizer_candidate_id"
                                    ],
                                    "side": side_name,
                                    "field": expected_suffix,
                                    "observed": observed,
                                    "expected": expected,
                                }
                            )

        branch_results[branch] = {
            "total_v9_rows": len(frame),
            "evidence_complete_rows": len(comparable),
            "sampled_rows": len(selected),
            "comparisons": len(selected)
            * 2
            * len(comparison_fields),
            "mismatches": branch_mismatches,
        }

    report = {
        "script": "freeform_trade_machine_engine_v3",
        "validation": "v9_evidence_complete_salary_route_sample",
        "validation_revision": VALIDATION_REVISION,
        "sample_size_per_branch": sample_size,
        "branches": branch_results,
        "total_comparisons": total_compared,
        "total_mismatches": total_mismatches,
        "passed": total_mismatches == 0,
        "mismatch_examples": examples,
    }

    if total_mismatches:
        raise AssertionError(
            "V3 salary-route validation found "
            f"{total_mismatches} mismatches.\n"
            + json.dumps(report, indent=2, default=str)
        )

    return report



def combined_pick_pipeline_result(
    runtime: RuntimeData,
    team: str,
    pick_right_id: str,
    stepien: dict[str, Any],
) -> dict[str, Any]:
    stepien_passed = bool(
        stepien.get(
            "package_pick_legality_stage_passed"
        )
    )
    decision = runtime.right_legality_by_id.get(
        pick_right_id
    )
    decision_matched = decision is not None
    team_matched = bool(
        decision_matched
        and normalize_team(
            decision.get("candidate_team")
        )
        == normalize_team(team)
    )
    evidence_passed = bool(
        decision_matched
        and to_bool(
            decision.get(
                "right_legality_stage_passed"
            )
        )
        is True
    )
    evidence_manual = bool(
        decision_matched
        and to_bool(
            decision.get(
                "right_legality_manual_review_required"
            )
        )
        is True
    )
    evidence_blocked = bool(
        decision_matched
        and to_bool(
            decision.get(
                "right_legality_blocked"
            )
        )
        is True
    )

    if not stepien_passed:
        passed = False
        manual = False
        blocked = True
        status = (
            "blocked_by_stepien_or_frozen_pick_screen"
        )
    elif not decision_matched:
        passed = False
        manual = True
        blocked = False
        status = (
            "right_legality_decision_unmatched_"
            "internal_review"
        )
    elif not team_matched:
        passed = False
        manual = True
        blocked = False
        status = (
            "right_legality_team_mismatch_"
            "internal_review"
        )
    elif evidence_manual:
        passed = False
        manual = True
        blocked = False
        status = (
            "right_legality_manual_review_required"
        )
    elif evidence_blocked:
        passed = False
        manual = False
        blocked = True
        status = (
            "blocked_by_right_legality_evidence"
        )
    elif evidence_passed:
        passed = True
        manual = False
        blocked = False
        status = (
            "passed_stepien_frozen_and_right_"
            "legality_evidence_remaining_full_"
            "cba_validation"
        )
    else:
        passed = False
        manual = True
        blocked = False
        status = (
            "right_legality_inconsistent_"
            "decision_internal_review"
        )

    return {
        "package_right_legality_stage_passed": (
            passed
        ),
        (
            "package_right_legality_manual_"
            "review_required"
        ): manual,
        "package_right_legality_blocked": (
            blocked
        ),
        "package_right_legality_status": status,
        "right_legality_decision_matched": (
            decision_matched
        ),
        (
            "right_evidence_team_matches_"
            "attached_pick_team"
        ): team_matched,
    }


def normalized_comparison_text(value: Any) -> str:
    return clean_text(value)


def validate_pick_pipeline_against_v9(
    runtime: RuntimeData,
    sample_size: int,
) -> dict[str, Any]:
    files = {
        "one_for_one": (
            OUTPUTS
            / "one_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
        "two_for_one": (
            OUTPUTS
            / "two_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
    }

    missing = [
        str(path)
        for path in files.values()
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "V9 pick validation files are missing:\n"
            + "\n".join(missing)
        )

    columns = [
        "optimizer_candidate_id",
        "attached_pick_team",
        "attached_pick_right_id",
        "pick_right_matched_to_inventory",
        "attached_pick_team_matches_inventory",
        "stepien_evaluation_status",
        "stepien_legality_passed",
        "stepien_manual_review_required",
        "stepien_baseline_violating_pairs",
        "stepien_post_trade_violating_pairs",
        "stepien_evaluated_scenario_count",
        "stepien_source_match_method",
        "stepien_requested_source_asset_ids",
        "stepien_matched_source_asset_ids",
        "stepien_unmatched_source_asset_ids",
        (
            "stepien_excluded_non_first_round_"
            "source_asset_ids"
        ),
        (
            "stepien_worst_case_removed_"
            "source_asset_id"
        ),
        (
            "stepien_worst_case_removed_"
            "draft_year"
        ),
        (
            "stepien_worst_case_removed_"
            "deterministic_pick_count"
        ),
        "frozen_pick_evaluation_status",
        "frozen_pick_legality_passed",
        "package_pick_legality_stage_passed",
        (
            "package_pick_legality_manual_"
            "review_required"
        ),
        "right_legality_decision_matched",
        (
            "right_evidence_team_matches_"
            "attached_pick_team"
        ),
        "package_right_legality_stage_passed",
        (
            "package_right_legality_manual_"
            "review_required"
        ),
        "package_right_legality_blocked",
        "package_right_legality_status",
    ]

    stepien_fields = [
        "stepien_evaluation_status",
        "stepien_legality_passed",
        "stepien_manual_review_required",
        "stepien_baseline_violating_pairs",
        "stepien_post_trade_violating_pairs",
        "stepien_evaluated_scenario_count",
        "stepien_source_match_method",
        "stepien_requested_source_asset_ids",
        "stepien_matched_source_asset_ids",
        "stepien_unmatched_source_asset_ids",
        (
            "stepien_excluded_non_first_round_"
            "source_asset_ids"
        ),
        (
            "stepien_worst_case_removed_"
            "source_asset_id"
        ),
        (
            "stepien_worst_case_removed_"
            "draft_year"
        ),
        (
            "stepien_worst_case_removed_"
            "deterministic_pick_count"
        ),
        "frozen_pick_evaluation_status",
        "frozen_pick_legality_passed",
        "package_pick_legality_stage_passed",
        (
            "package_pick_legality_manual_"
            "review_required"
        ),
    ]
    final_fields = [
        "right_legality_decision_matched",
        (
            "right_evidence_team_matches_"
            "attached_pick_team"
        ),
        "package_right_legality_stage_passed",
        (
            "package_right_legality_manual_"
            "review_required"
        ),
        "package_right_legality_blocked",
        "package_right_legality_status",
    ]
    numeric_fields = {
        "stepien_evaluated_scenario_count",
        (
            "stepien_worst_case_removed_"
            "draft_year"
        ),
        (
            "stepien_worst_case_removed_"
            "deterministic_pick_count"
        ),
    }
    boolean_fields = {
        "stepien_legality_passed",
        "stepien_manual_review_required",
        "frozen_pick_legality_passed",
        "package_pick_legality_stage_passed",
        (
            "package_pick_legality_manual_"
            "review_required"
        ),
        "right_legality_decision_matched",
        (
            "right_evidence_team_matches_"
            "attached_pick_team"
        ),
        "package_right_legality_stage_passed",
        (
            "package_right_legality_manual_"
            "review_required"
        ),
        "package_right_legality_blocked",
    }

    branch_results: dict[str, Any] = {}
    total_comparisons = 0
    total_mismatches = 0
    examples: list[dict[str, Any]] = []

    for branch, path in files.items():
        frame = pd.read_parquet(
            path,
            columns=columns,
        )
        selected = frame.sample(
            n=min(sample_size, len(frame)),
            random_state=20260807,
        )
        branch_mismatches = 0

        for row in selected.to_dict(
            orient="records"
        ):
            team = normalize_team(
                row["attached_pick_team"]
            )
            pick_right_id = clean_text(
                row["attached_pick_right_id"]
            )
            observed_stepien = (
                evaluate_single_right_stepien(
                    runtime,
                    team,
                    pick_right_id,
                    TRADE_DATE,
                )
            )
            observed_final = (
                combined_pick_pipeline_result(
                    runtime,
                    team,
                    pick_right_id,
                    observed_stepien,
                )
            )

            observed_inventory_match = bool(
                pick_right_id in runtime.pick_by_id
            )
            observed_team_match = bool(
                observed_inventory_match
                and normalize_team(
                    runtime.pick_by_id[
                        pick_right_id
                    ].get("candidate_team")
                )
                == team
            )
            inventory_pairs = {
                "pick_right_matched_to_inventory": (
                    observed_inventory_match
                ),
                (
                    "attached_pick_team_matches_"
                    "inventory"
                ): observed_team_match,
            }

            for field in [
                *inventory_pairs,
                *stepien_fields,
                *final_fields,
            ]:
                if field in inventory_pairs:
                    observed = inventory_pairs[field]
                elif field in observed_stepien:
                    observed = observed_stepien[field]
                else:
                    observed = observed_final[field]

                expected = row[field]

                if field in boolean_fields:
                    matched = (
                        bool(observed)
                        == (
                            to_bool(expected)
                            is True
                        )
                    )
                elif field in numeric_fields:
                    matched = values_close(
                        observed,
                        expected,
                    )
                else:
                    matched = (
                        normalized_comparison_text(
                            observed
                        )
                        == normalized_comparison_text(
                            expected
                        )
                    )

                total_comparisons += 1

                if not matched:
                    total_mismatches += 1
                    branch_mismatches += 1

                    if len(examples) < 25:
                        examples.append(
                            {
                                "branch": branch,
                                "candidate_id": row[
                                    "optimizer_candidate_id"
                                ],
                                "pick_right_id": (
                                    pick_right_id
                                ),
                                "field": field,
                                "observed": observed,
                                "expected": expected,
                            }
                        )

        branch_results[branch] = {
            "total_v9_rows": len(frame),
            "sampled_rows": len(selected),
            "comparisons": (
                len(selected)
                * (
                    len(inventory_pairs)
                    + len(stepien_fields)
                    + len(final_fields)
                )
            ),
            "mismatches": branch_mismatches,
        }

    report = {
        "script": (
            "freeform_trade_machine_engine_v3"
        ),
        "validation": (
            "v9_pick_right_stepien_pipeline_sample"
        ),
        "validation_revision": (
            VALIDATION_REVISION
        ),
        "sample_size_per_branch": sample_size,
        "branches": branch_results,
        "total_comparisons": total_comparisons,
        "total_mismatches": total_mismatches,
        "passed": total_mismatches == 0,
        "mismatch_examples": examples,
    }

    if total_mismatches:
        raise AssertionError(
            "V3 pick-right and Stepien validation "
            f"found {total_mismatches} mismatches.\n"
            + json.dumps(
                report,
                indent=2,
                default=str,
            )
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--validate-v9",
        action="store_true",
        help=(
            "Validate V3 salary routes against V9."
        ),
    )
    parser.add_argument(
        "--validate-v9-picks",
        action="store_true",
        help=(
            "Validate V3 pick-right and Stepien "
            "results against V9."
        ),
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
    )
    args = parser.parse_args()

    if args.self_test:
        print(json.dumps(run_self_test(), indent=2))
        return 0

    runtime = load_runtime_data()

    if args.validate_v9:
        print(
            json.dumps(
                validate_against_v9(
                    runtime,
                    max(1, args.sample_size),
                ),
                indent=2,
                default=str,
            )
        )
        return 0

    if args.validate_v9_picks:
        print(
            json.dumps(
                validate_pick_pipeline_against_v9(
                    runtime,
                    max(1, args.sample_size),
                ),
                indent=2,
                default=str,
            )
        )
        return 0

    print(
        json.dumps(
            {
                "script": "freeform_trade_machine_engine_v3",
                "trade_date": TRADE_DATE,
                "validation_revision": VALIDATION_REVISION,
                "trade_pool_players": len(runtime.trade_pool),
                "player_cba_decisions": len(runtime.player_cba),
                "team_cba_decisions": len(runtime.team_cba),
                "teams": len(runtime.team_salary),
                "future_pick_rights": len(runtime.picks),
                "right_legality_decisions": (
                    len(runtime.right_legality)
                ),
                "stepien_team_years": (
                    len(runtime.stepien)
                ),
                "status": "runtime_loaded",
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
