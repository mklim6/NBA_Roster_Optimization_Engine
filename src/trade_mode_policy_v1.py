from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    CheckResult,
    RuntimeData,
    Status,
    TradeEvaluation,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
    to_float,
)
from mutable_league_state_v1 import (  # noqa: E402
    LeagueState,
    StateMutationError,
    TransactionRecord,
    apply_passed_trade,
    create_league_state,
    find_pass_player_trade,
    validate_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
    validate_state_runtime,
)


POLICY_VERSION = "trade-mode-policy-v1-2026-08-07"
SELF_TEST_REPORT = (
    OUTPUTS / "trade_mode_policy_v1_self_test.json"
)


class TradeMode(str, Enum):
    REALISM = "realism"
    SANDBOX = "sandbox"


class SandboxDisposition(str, Enum):
    VERIFIED = "verified"
    PLAYABLE_WITH_WARNING = "playable_with_warning"
    FORCE_REQUIRED = "force_required"
    INVALID = "invalid"


class TradeModePolicyError(RuntimeError):
    """Raised when a trade cannot be used in the chosen mode."""


STRUCTURAL_BLOCK_CODES = frozenset(
    {
        "same_team_on_both_sides",
        "team_not_found",
        "empty_trade",
        "duplicate_player_on_side",
        "duplicate_pick_on_side",
        "player_not_in_trade_pool",
        "pick_right_not_found",
        "player_roster_mismatch",
        "pick_ownership_mismatch",
    }
)


@dataclass
class ModeTradeEvaluation:
    mode: TradeMode
    strict_evaluation: TradeEvaluation
    disposition: SandboxDisposition
    can_apply_without_force: bool
    force_allowed: bool
    requires_force: bool
    structural_codes: tuple[str, ...]
    blocking_codes: tuple[str, ...]
    manual_review_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    verification_label: str

    @property
    def strict_status(self) -> Status:
        return self.strict_evaluation.status

    @property
    def playable(self) -> bool:
        return (
            self.can_apply_without_force
            or self.force_allowed
        )


@dataclass
class ModeAppliedTransaction:
    policy: ModeTradeEvaluation
    transaction: TransactionRecord
    forced: bool


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def all_checks(
    evaluation: TradeEvaluation,
) -> list[CheckResult]:
    return [
        *evaluation.checks,
        *evaluation.side_a.checks,
        *evaluation.side_b.checks,
    ]


def codes_with_status(
    evaluation: TradeEvaluation,
    status: Status,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                check.code
                for check in all_checks(evaluation)
                if check.status == status
            }
        )
    )


def messages_with_status(
    evaluation: TradeEvaluation,
    status: Status,
) -> tuple[str, ...]:
    values: list[str] = []

    for check in all_checks(evaluation):
        if check.status != status:
            continue

        message = clean_text(check.message)
        if message and message not in values:
            values.append(message)

    return tuple(values)


def request_players(
    request: TradeRequest,
) -> tuple[str, ...]:
    return tuple(
        normalize_player_id(player_id)
        for player_id in [
            *request.side_a.player_ids,
            *request.side_b.player_ids,
        ]
        if normalize_player_id(player_id)
    )


def request_picks(
    request: TradeRequest,
) -> tuple[str, ...]:
    return tuple(
        clean_text(pick_right_id)
        for pick_right_id in [
            *request.side_a.pick_right_ids,
            *request.side_b.pick_right_ids,
        ]
        if clean_text(pick_right_id)
    )


def listed_salary(
    runtime: RuntimeData,
    player_id: str,
) -> float | None:
    record = runtime.trade_by_id.get(
        normalize_player_id(player_id)
    )
    if record is None:
        return None

    return to_float(
        record.get("trade_salary_2026_27")
    )


def listed_salary_total(
    runtime: RuntimeData,
    player_ids: Iterable[str],
) -> float | None:
    values: list[float] = []

    for player_id in player_ids:
        value = listed_salary(
            runtime,
            player_id,
        )
        if value is None:
            return None
        values.append(value)

    return round(sum(values), 2)


def request_financially_modelable(
    runtime: RuntimeData,
    request: TradeRequest,
) -> bool:
    players = request_players(request)

    if not players:
        return True

    return all(
        listed_salary(runtime, player_id)
        is not None
        for player_id in players
    )


def classify_trade(
    runtime: RuntimeData,
    request: TradeRequest,
    *,
    mode: TradeMode | str = TradeMode.REALISM,
) -> ModeTradeEvaluation:
    selected_mode = TradeMode(mode)
    strict = evaluate_trade(runtime, request)

    blocking_codes = codes_with_status(
        strict,
        Status.BLOCKED,
    )
    manual_codes = codes_with_status(
        strict,
        Status.MANUAL_REVIEW,
    )
    structural_codes = tuple(
        sorted(
            set(blocking_codes).intersection(
                STRUCTURAL_BLOCK_CODES
            )
        )
    )

    if selected_mode == TradeMode.REALISM:
        disposition = (
            SandboxDisposition.VERIFIED
            if strict.status == Status.PASS
            else SandboxDisposition.INVALID
        )
        return ModeTradeEvaluation(
            mode=selected_mode,
            strict_evaluation=strict,
            disposition=disposition,
            can_apply_without_force=(
                strict.status == Status.PASS
            ),
            force_allowed=False,
            requires_force=False,
            structural_codes=structural_codes,
            blocking_codes=blocking_codes,
            manual_review_codes=manual_codes,
            warnings=messages_with_status(
                strict,
                Status.MANUAL_REVIEW,
            ),
            verification_label=(
                "REALISM VERIFIED"
                if strict.status == Status.PASS
                else "REALISM NOT APPROVED"
            ),
        )

    financially_modelable = (
        request_financially_modelable(
            runtime,
            request,
        )
    )

    if strict.status == Status.PASS:
        disposition = SandboxDisposition.VERIFIED
        can_apply = True
        force_allowed = False
        requires_force = False
        label = "CBA VERIFIED"
    elif structural_codes or not financially_modelable:
        disposition = SandboxDisposition.INVALID
        can_apply = False
        force_allowed = False
        requires_force = False
        label = "INVALID PACKAGE"
    elif strict.status == Status.MANUAL_REVIEW:
        disposition = (
            SandboxDisposition.PLAYABLE_WITH_WARNING
        )
        can_apply = True
        force_allowed = False
        requires_force = False
        label = "SANDBOX APPROVED"
    else:
        disposition = SandboxDisposition.FORCE_REQUIRED
        can_apply = False
        force_allowed = True
        requires_force = True
        label = "FORCE TRADE AVAILABLE"

    warnings = list(
        messages_with_status(
            strict,
            Status.MANUAL_REVIEW,
        )
    )

    if disposition == SandboxDisposition.FORCE_REQUIRED:
        warnings.extend(
            messages_with_status(
                strict,
                Status.BLOCKED,
            )
        )

    if not financially_modelable:
        warnings.append(
            "One or more players are missing a usable "
            "listed salary, so the mutable league cannot "
            "be updated safely."
        )

    return ModeTradeEvaluation(
        mode=selected_mode,
        strict_evaluation=strict,
        disposition=disposition,
        can_apply_without_force=can_apply,
        force_allowed=force_allowed,
        requires_force=requires_force,
        structural_codes=structural_codes,
        blocking_codes=blocking_codes,
        manual_review_codes=manual_codes,
        warnings=tuple(dict.fromkeys(warnings)),
        verification_label=label,
    )


def current_financial_values(
    state: LeagueState,
    team: str,
) -> tuple[float, float, str]:
    team = normalize_team(team)
    financial = state.team_financials.get(team)

    if financial is None:
        raise TradeModePolicyError(
            f"{team or '<blank>'} is missing from league state."
        )

    if (
        financial.team_salary is None
        or financial.apron_salary is None
    ):
        raise TradeModePolicyError(
            f"{team} does not have deterministic current "
            "salary values."
        )

    return (
        float(financial.team_salary),
        float(financial.apron_salary),
        clean_text(financial.hard_cap_level).lower()
        or "none",
    )


def modeled_posttrade_values(
    runtime: RuntimeData,
    state: LeagueState,
    *,
    team: str,
    outgoing_player_ids: Iterable[str],
    incoming_player_ids: Iterable[str],
) -> tuple[float, float, str]:
    (
        current_salary,
        current_apron_salary,
        current_hard_cap_level,
    ) = current_financial_values(state, team)

    outgoing = listed_salary_total(
        runtime,
        outgoing_player_ids,
    )
    incoming = listed_salary_total(
        runtime,
        incoming_player_ids,
    )

    if outgoing is None or incoming is None:
        raise TradeModePolicyError(
            f"{team} cannot receive a modeled sandbox salary "
            "update because an involved player is missing a "
            "listed salary."
        )

    delta = incoming - outgoing
    return (
        round(current_salary + delta, 2),
        round(current_apron_salary + delta, 2),
        current_hard_cap_level,
    )


def usable_hard_cap_level(
    value: Any,
    fallback: str,
) -> str:
    normalized = clean_text(value).lower()

    if normalized in {
        "none",
        "first_apron",
        "second_apron",
    }:
        return normalized

    return fallback


def build_state_evaluation(
    runtime: RuntimeData,
    state: LeagueState,
    request: TradeRequest,
    policy: ModeTradeEvaluation | None = None,
    *,
    mode: TradeMode | str = TradeMode.REALISM,
    force: bool = False,
) -> TradeEvaluation:
    resolved = policy or classify_trade(
        runtime,
        request,
        mode=mode,
    )

    if resolved.mode == TradeMode.REALISM:
        if (
            resolved.strict_evaluation.status
            != Status.PASS
        ):
            raise TradeModePolicyError(
                "Realism Mode only applies deterministic "
                "PASS transactions."
            )
        return copy.deepcopy(
            resolved.strict_evaluation
        )

    if (
        resolved.disposition
        == SandboxDisposition.INVALID
    ):
        detail = ", ".join(
            resolved.structural_codes
            or resolved.blocking_codes
            or resolved.manual_review_codes
        )
        raise TradeModePolicyError(
            "This package is structurally invalid and cannot "
            "be applied in Sandbox Mode"
            + (f": {detail}" if detail else ".")
        )

    if resolved.requires_force and not force:
        raise TradeModePolicyError(
            "This package violates one or more realism rules. "
            "Set force=True to apply it in Sandbox Mode."
        )

    if force and not (
        resolved.force_allowed
        or resolved.can_apply_without_force
    ):
        raise TradeModePolicyError(
            "A force trade is not available for this package."
        )

    evaluation = copy.deepcopy(
        resolved.strict_evaluation
    )
    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )

    (
        modeled_a_salary,
        modeled_a_apron,
        modeled_a_hard_cap,
    ) = modeled_posttrade_values(
        runtime,
        state,
        team=team_a,
        outgoing_player_ids=(
            request.side_a.player_ids
        ),
        incoming_player_ids=(
            request.side_b.player_ids
        ),
    )
    (
        modeled_b_salary,
        modeled_b_apron,
        modeled_b_hard_cap,
    ) = modeled_posttrade_values(
        runtime,
        state,
        team=team_b,
        outgoing_player_ids=(
            request.side_b.player_ids
        ),
        incoming_player_ids=(
            request.side_a.player_ids
        ),
    )

    evaluation.side_a.posttrade_team_salary = (
        to_float(
            evaluation.side_a.posttrade_team_salary
        )
        if to_float(
            evaluation.side_a.posttrade_team_salary
        )
        is not None
        else modeled_a_salary
    )
    evaluation.side_a.posttrade_apron_team_salary = (
        to_float(
            evaluation.side_a.posttrade_apron_team_salary
        )
        if to_float(
            evaluation.side_a.posttrade_apron_team_salary
        )
        is not None
        else modeled_a_apron
    )
    evaluation.side_a.hard_cap_level_after_trade = (
        usable_hard_cap_level(
            evaluation.side_a.hard_cap_level_after_trade,
            modeled_a_hard_cap,
        )
    )

    evaluation.side_b.posttrade_team_salary = (
        to_float(
            evaluation.side_b.posttrade_team_salary
        )
        if to_float(
            evaluation.side_b.posttrade_team_salary
        )
        is not None
        else modeled_b_salary
    )
    evaluation.side_b.posttrade_apron_team_salary = (
        to_float(
            evaluation.side_b.posttrade_apron_team_salary
        )
        if to_float(
            evaluation.side_b.posttrade_apron_team_salary
        )
        is not None
        else modeled_b_apron
    )
    evaluation.side_b.hard_cap_level_after_trade = (
        usable_hard_cap_level(
            evaluation.side_b.hard_cap_level_after_trade,
            modeled_b_hard_cap,
        )
    )

    evaluation.status = Status.PASS
    evaluation.side_a.status = Status.PASS
    evaluation.side_b.status = Status.PASS

    override_code = (
        "sandbox_force_trade_override"
        if force
        else "sandbox_manual_review_override"
    )
    override_message = (
        "Sandbox Mode force-applied this package despite "
        "one or more realism-rule failures."
        if force
        else (
            "Sandbox Mode approved this package using modeled "
            "salary treatment while preserving the unresolved "
            "realism warnings."
        )
    )
    evaluation.checks.append(
        CheckResult(
            status=Status.PASS,
            code=override_code,
            message=override_message,
        )
    )

    return evaluation


def apply_trade_in_mode(
    state: LeagueState,
    runtime: RuntimeData,
    request: TradeRequest,
    *,
    mode: TradeMode | str = TradeMode.REALISM,
    force: bool = False,
) -> ModeAppliedTransaction:
    policy = classify_trade(
        runtime,
        request,
        mode=mode,
    )
    state_evaluation = build_state_evaluation(
        runtime,
        state,
        request,
        policy,
        force=force,
    )
    transaction = apply_passed_trade(
        state,
        runtime,
        request,
        state_evaluation,
    )
    return ModeAppliedTransaction(
        policy=policy,
        transaction=transaction,
        forced=bool(force),
    )


def policy_to_dict(
    policy: ModeTradeEvaluation,
) -> dict[str, Any]:
    return {
        "mode": policy.mode.value,
        "strict_status": (
            policy.strict_evaluation.status.value
        ),
        "disposition": policy.disposition.value,
        "can_apply_without_force": (
            policy.can_apply_without_force
        ),
        "force_allowed": policy.force_allowed,
        "requires_force": policy.requires_force,
        "structural_codes": list(
            policy.structural_codes
        ),
        "blocking_codes": list(
            policy.blocking_codes
        ),
        "manual_review_codes": list(
            policy.manual_review_codes
        ),
        "warnings": list(policy.warnings),
        "verification_label": (
            policy.verification_label
        ),
    }


def player_team(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    return normalize_team(
        runtime.trade_by_id[
            normalize_player_id(player_id)
        ].get("current_team_2026_27")
    )


def player_name(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    return clean_text(
        runtime.trade_by_id[
            normalize_player_id(player_id)
        ].get("player_name", player_id)
    )


def candidate_player_ids(
    runtime: RuntimeData,
    *,
    missing_cba: bool,
) -> list[str]:
    values: list[tuple[float, str]] = []

    for player_id, record in (
        runtime.trade_by_id.items()
    ):
        team = normalize_team(
            record.get("current_team_2026_27")
        )
        salary = to_float(
            record.get("trade_salary_2026_27")
        )
        has_cba = (
            player_id
            in runtime.player_cba_by_id
        )

        if (
            not team
            or salary is None
            or has_cba == missing_cba
        ):
            continue

        values.append((salary, player_id))

    values.sort(key=lambda item: item[0])
    return [
        player_id
        for _, player_id in values
    ]


def find_missing_cba_manual_trade(
    runtime: RuntimeData,
) -> tuple[TradeRequest, ModeTradeEvaluation]:
    missing_ids = candidate_player_ids(
        runtime,
        missing_cba=True,
    )
    covered_ids = candidate_player_ids(
        runtime,
        missing_cba=False,
    )

    for missing_id in missing_ids:
        missing_team = player_team(
            runtime,
            missing_id,
        )
        missing_salary = (
            listed_salary(runtime, missing_id)
            or 0.0
        )
        nearby = sorted(
            (
                covered_id
                for covered_id in covered_ids
                if player_team(
                    runtime,
                    covered_id,
                )
                != missing_team
            ),
            key=lambda player_id: abs(
                (
                    listed_salary(
                        runtime,
                        player_id,
                    )
                    or 0.0
                )
                - missing_salary
            ),
        )

        for covered_id in nearby[:80]:
            covered_team = player_team(
                runtime,
                covered_id,
            )
            request = TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=missing_team,
                    player_ids=(missing_id,),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=covered_team,
                    player_ids=(covered_id,),
                ),
            )
            policy = classify_trade(
                runtime,
                request,
                mode=TradeMode.SANDBOX,
            )

            if (
                policy.disposition
                == (
                    SandboxDisposition
                    .PLAYABLE_WITH_WARNING
                )
                and "player_cba_evidence_missing"
                in policy.manual_review_codes
            ):
                return request, policy

    raise AssertionError(
        "No missing-CBA Sandbox Mode example was found."
    )


def find_forceable_blocked_trade(
    runtime: RuntimeData,
) -> tuple[TradeRequest, ModeTradeEvaluation]:
    covered_ids = candidate_player_ids(
        runtime,
        missing_cba=False,
    )
    low = covered_ids[:80]
    high = list(reversed(covered_ids[-80:]))

    for high_id in high:
        high_team = player_team(
            runtime,
            high_id,
        )

        for low_id in low:
            low_team = player_team(
                runtime,
                low_id,
            )
            if not low_team or low_team == high_team:
                continue

            request = TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=high_team,
                    player_ids=(high_id,),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=low_team,
                    player_ids=(low_id,),
                ),
            )
            policy = classify_trade(
                runtime,
                request,
                mode=TradeMode.SANDBOX,
            )

            if (
                policy.disposition
                == SandboxDisposition.FORCE_REQUIRED
                and policy.force_allowed
            ):
                return request, policy

    raise AssertionError(
        "No forceable Sandbox Mode example was found."
    )


def run_self_test() -> dict[str, Any]:
    runtime = load_runtime_data()
    base_runtime = build_state_runtime(
        runtime,
        create_league_state(runtime),
    )
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    pass_request, pass_result = (
        find_pass_player_trade(base_runtime)
    )
    realism_policy = classify_trade(
        base_runtime,
        pass_request,
        mode=TradeMode.REALISM,
    )
    sandbox_pass_policy = classify_trade(
        base_runtime,
        pass_request,
        mode=TradeMode.SANDBOX,
    )

    checks["realism_preserves_strict_pass"] = (
        pass_result.status == Status.PASS
        and realism_policy.can_apply_without_force
        and not realism_policy.force_allowed
    )
    checks["sandbox_preserves_verified_pass"] = (
        sandbox_pass_policy.disposition
        == SandboxDisposition.VERIFIED
        and sandbox_pass_policy.can_apply_without_force
    )

    manual_request, manual_policy = (
        find_missing_cba_manual_trade(
            base_runtime
        )
    )
    checks["missing_cba_becomes_sandbox_warning"] = (
        manual_policy.strict_status
        == Status.MANUAL_REVIEW
        and manual_policy.disposition
        == (
            SandboxDisposition
            .PLAYABLE_WITH_WARNING
        )
        and manual_policy.can_apply_without_force
        and "player_cba_evidence_missing"
        in manual_policy.manual_review_codes
    )

    manual_state = create_league_state(runtime)
    manual_runtime = build_state_runtime(
        runtime,
        manual_state,
    )
    manual_applied = apply_trade_in_mode(
        manual_state,
        manual_runtime,
        manual_request,
        mode=TradeMode.SANDBOX,
    )
    manual_team_a = normalize_team(
        manual_request.side_a.team_abbreviation
    )
    manual_team_b = normalize_team(
        manual_request.side_b.team_abbreviation
    )
    checks["sandbox_warning_trade_applies"] = (
        manual_applied.transaction.transaction_id
        == "TXN-0001"
        and all(
            manual_state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == manual_team_b
            for player_id
            in manual_request.side_a.player_ids
        )
        and all(
            manual_state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == manual_team_a
            for player_id
            in manual_request.side_b.player_ids
        )
    )
    manual_adapted = build_state_runtime(
        runtime,
        manual_state,
    )
    checks["sandbox_warning_runtime_valid"] = (
        all(
            validate_state(
                manual_state,
                runtime,
            ).values()
        )
        and all(
            validate_state_runtime(
                runtime,
                manual_adapted,
                manual_state,
            ).values()
        )
    )

    force_request, force_policy = (
        find_forceable_blocked_trade(
            base_runtime
        )
    )
    checks["blocked_trade_requires_force"] = (
        force_policy.strict_status == Status.BLOCKED
        and force_policy.requires_force
        and force_policy.force_allowed
        and not force_policy.structural_codes
    )

    force_state = create_league_state(runtime)
    force_runtime = build_state_runtime(
        runtime,
        force_state,
    )
    no_force_blocked = False
    try:
        apply_trade_in_mode(
            force_state,
            force_runtime,
            force_request,
            mode=TradeMode.SANDBOX,
            force=False,
        )
    except TradeModePolicyError:
        no_force_blocked = True
    checks["force_confirmation_is_required"] = (
        no_force_blocked
        and not force_state.transaction_history
    )

    force_applied = apply_trade_in_mode(
        force_state,
        force_runtime,
        force_request,
        mode=TradeMode.SANDBOX,
        force=True,
    )
    force_adapted = build_state_runtime(
        runtime,
        force_state,
    )
    checks["force_trade_applies_and_validates"] = (
        force_applied.forced
        and force_applied.transaction.transaction_id
        == "TXN-0001"
        and all(
            validate_state(
                force_state,
                runtime,
            ).values()
        )
        and all(
            validate_state_runtime(
                runtime,
                force_adapted,
                force_state,
            ).values()
        )
    )

    same_team_request = TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=manual_team_a,
            player_ids=(
                manual_request.side_a.player_ids
            ),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=manual_team_a,
            player_ids=(),
        ),
    )
    same_team_policy = classify_trade(
        base_runtime,
        same_team_request,
        mode=TradeMode.SANDBOX,
    )
    checks["structural_invalidity_cannot_be_forced"] = (
        same_team_policy.disposition
        == SandboxDisposition.INVALID
        and not same_team_policy.force_allowed
        and "same_team_on_both_sides"
        in same_team_policy.structural_codes
    )

    structural_state = create_league_state(runtime)
    structural_blocked = False
    try:
        apply_trade_in_mode(
            structural_state,
            base_runtime,
            same_team_request,
            mode=TradeMode.SANDBOX,
            force=True,
        )
    except TradeModePolicyError:
        structural_blocked = True
    checks["structural_force_attempt_rejected"] = (
        structural_blocked
        and not structural_state.transaction_history
    )

    details = {
        "strict_pass": {
            "team_a": (
                pass_request.side_a.team_abbreviation
            ),
            "team_b": (
                pass_request.side_b.team_abbreviation
            ),
            "policy": policy_to_dict(
                sandbox_pass_policy
            ),
        },
        "missing_cba_example": {
            "team_a": (
                manual_request.side_a.team_abbreviation
            ),
            "team_b": (
                manual_request.side_b.team_abbreviation
            ),
            "side_a_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id
                in manual_request.side_a.player_ids
            ],
            "side_b_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id
                in manual_request.side_b.player_ids
            ],
            "policy": policy_to_dict(
                manual_policy
            ),
        },
        "force_trade_example": {
            "team_a": (
                force_request.side_a.team_abbreviation
            ),
            "team_b": (
                force_request.side_b.team_abbreviation
            ),
            "side_a_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id
                in force_request.side_a.player_ids
            ],
            "side_b_players": [
                {
                    "player_id": player_id,
                    "player_name": player_name(
                        base_runtime,
                        player_id,
                    ),
                }
                for player_id
                in force_request.side_b.player_ids
            ],
            "policy": policy_to_dict(
                force_policy
            ),
        },
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": POLICY_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": details,
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Trade Mode Policy V1 self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nTRADE MODE POLICY V1 SELF-TEST PASSED"
        )
        return 0

    runtime = load_runtime_data()
    state = create_league_state(runtime)
    print(
        json.dumps(
            {
                "script": POLICY_VERSION,
                "modes": [
                    mode.value
                    for mode in TradeMode
                ],
                "trade_pool_players": len(
                    runtime.trade_by_id
                ),
                "player_cba_decisions": len(
                    runtime.player_cba_by_id
                ),
                "state_revision": (
                    state.state_revision
                ),
                "status": "initialized",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())