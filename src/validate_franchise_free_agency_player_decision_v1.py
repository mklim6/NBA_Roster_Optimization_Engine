from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
WORKSPACE = ROOT / "src" / "franchise_free_agency_workspace_v1.py"
PERSISTENT = ROOT / "src" / "franchise_free_agency_persistent_calendar_v1.py"
NEGOTIATION = ROOT / "src" / "franchise_free_agency_negotiation_rounds_v1.py"

from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_SCOPE,
    FREE_AGENCY_PLAYER_DECISION_UI_VERSION,
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    FreeAgencyPlayerDecisionError,
    commit_player_accepted_free_agency_preview_live,
    decision_matches_preview,
    evaluate_free_agent_offer_decision,
    preference_profile,
    role_opportunity_score,
    salary_value_score,
    winning_environment_score,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = "franchise-free-agency-player-decision-validator-v1.0.1-2026-09-28"
EXPECTED_LIVE_SIGNING = "franchise-free-agency-live-signing-v1-2026-08-14"
EXPECTED_DECISION = "franchise-free-agency-player-decision-v1-2026-08-14"
EXPECTED_UI = "franchise-free-agency-player-decision-ui-v1-2026-08-14"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Contract:
    salary: float | None


@dataclass
class Player:
    player_id: str
    player_name: str
    overall_rating: float
    position: str
    age: float
    potential_rating: float
    contract: Contract


@dataclass
class Team:
    roster_player_ids: tuple[str, ...]


@dataclass
class Standing:
    wins: int
    losses: int


@dataclass
class State:
    settings: Any
    players: dict[str, Player]
    teams: dict[str, Team]
    standings: dict[str, Standing]
    season_history: list[Any] = field(default_factory=list)


def build_toy_state() -> State:
    players: dict[str, Player] = {
        "FA1": Player(
            "FA1",
            "Decision Test Wing",
            86.0,
            "SF",
            27.0,
            88.0,
            Contract(20_000_000.0),
        )
    }
    roster: list[str] = []
    ratings = [84, 83, 82, 81, 80, 79, 78, 77, 76, 75]
    positions = ["SF", "PG", "C", "SG", "PF", "PG", "C", "SG", "PF", "PG"]
    for index, (rating, position) in enumerate(zip(ratings, positions), start=1):
        pid = f"CHI{index}"
        roster.append(pid)
        players[pid] = Player(
            pid,
            pid,
            float(rating),
            position,
            27.0,
            float(rating),
            Contract(8_000_000.0),
        )
    for index, rating in enumerate([92, 90, 88, 87], start=1):
        pid = f"CROWD{index}"
        players[pid] = Player(
            pid,
            pid,
            float(rating),
            "SF",
            27.0,
            float(rating),
            Contract(12_000_000.0),
        )

    return State(
        settings=SimpleNamespace(season_label="2026-27"),
        players=players,
        teams={
            "CHI": Team(tuple(roster)),
            "BOS": Team(tuple(roster + [f"CROWD{i}" for i in range(1, 5)])),
            "WAS": Team(tuple(roster)),
        },
        standings={
            "CHI": Standing(52, 30),
            "BOS": Standing(62, 20),
            "WAS": Standing(20, 62),
        },
    )


def build_preview(
    salary: float,
    *,
    team: str = "CHI",
    status: str = "pass",
    can_commit: bool = True,
    source_fingerprint: str = "TOY-SOURCE-FP",
) -> FreeAgencyTransactionPreview:
    offer = FreeAgencyOffer(
        player_id="FA1",
        team_abbreviation=team,
        annual_salary=float(salary),
        years=3,
        guaranteed=True,
        option_type="",
    )
    contract = {
        "minimum_salary_floor": 2_100_000.0,
        "maximum_initial_salary": 41_240_250.0,
        "prior_salary": 20_000_000.0,
        "anchor_salary_cap": 164_961_000.0,
    }
    payload = {
        "salary_cap": 164_961_000.0,
        "cap_space_before": 42_000_000.0,
        "cap_space_after": 42_000_000.0 - float(salary),
        "contract_salary_legality": contract,
    }
    gate = FreeAgencyFinancialGateResult(
        status=status,
        reason="toy financial gate",
        payload=payload,
    )
    return FreeAgencyTransactionPreview(
        transaction_version="toy-v1",
        offer_version="toy-offer-v1",
        offer=offer,
        player_name="Decision Test Wing",
        source_fingerprint=source_fingerprint,
        candidate_fingerprint="TOY-CANDIDATE-FP",
        status=status,
        can_commit=bool(can_commit),
        checks={"toy": status == "pass"},
        financial_gate=gate,
        roster_count_before=15,
        roster_count_after=16,
        message="toy preview",
    )


def main() -> int:
    checks: dict[str, bool] = {}
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = _sha256(checkpoint_path) if checkpoint_path.exists() else ""

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("v1.0.1-2026-09-28")
    checks["player_decision_version_is_current"] = FREE_AGENCY_PLAYER_DECISION_VERSION == EXPECTED_DECISION
    checks["player_decision_ui_version_is_current"] = FREE_AGENCY_PLAYER_DECISION_UI_VERSION == EXPECTED_UI
    checks["live_signing_v1_is_preserved"] = FREE_AGENCY_LIVE_SIGNING_VERSION == EXPECTED_LIVE_SIGNING
    checks["decision_scope_is_single_offer_not_fake_competing_market"] = (
        FREE_AGENCY_PLAYER_DECISION_SCOPE == "single_offer_deterministic_no_competing_market"
    )

    checkpoint = load_franchise_checkpoint()
    checks["durable_checkpoint_exists"] = checkpoint is not None and checkpoint_path.exists()
    checks["durable_checkpoint_loads"] = checkpoint is not None

    state = build_toy_state()
    player = state.players["FA1"]
    profile_one = preference_profile(state, player)
    profile_two = preference_profile(state, player)
    checks["player_preference_profile_is_deterministic"] = profile_one == profile_two
    checks["preference_weights_sum_to_one"] = math.isclose(
        profile_one.money_weight
        + profile_one.role_weight
        + profile_one.winning_weight
        + profile_one.security_weight
        + profile_one.career_fit_weight,
        1.0,
        abs_tol=1e-5,
    )
    checks["acceptance_threshold_is_bounded"] = 50.0 <= profile_one.acceptance_threshold <= 68.0

    low_salary_score = salary_value_score(5_000_000.0, 20_000_000.0, True)
    fair_salary_score = salary_value_score(20_000_000.0, 20_000_000.0, True)
    rich_salary_score = salary_value_score(35_000_000.0, 20_000_000.0, True)
    checks["salary_preference_is_monotonic"] = low_salary_score < fair_salary_score < rich_salary_score

    role_open = role_opportunity_score(state, player, "CHI")
    role_crowded = role_opportunity_score(state, player, "BOS")
    checks["role_model_penalizes_crowded_position_depth"] = role_open > role_crowded
    checks["winning_model_ranks_strong_team_over_weak_team"] = (
        winning_environment_score(state, "BOS") > winning_environment_score(state, "WAS")
    )

    decisions = []
    for salary in range(2_500_000, 41_000_001, 250_000):
        decisions.append(evaluate_free_agent_offer_decision(state, build_preview(float(salary))))
    accept = next((item for item in decisions if item.status == "accept"), None)
    counter = next((item for item in decisions if item.status == "counter"), None)
    decline = next((item for item in decisions if item.status == "decline"), None)
    checks["toy_market_produces_accept_path"] = accept is not None
    checks["toy_market_produces_counter_path"] = counter is not None
    checks["toy_market_produces_decline_or_lowball_path"] = decline is not None or decisions[0].status in {"counter", "decline"}

    probe = evaluate_free_agent_offer_decision(state, build_preview(20_000_000.0))
    probe_repeat = evaluate_free_agent_offer_decision(state, build_preview(20_000_000.0))
    checks["same_state_same_offer_same_decision"] = probe == probe_repeat
    checks["decision_fingerprint_is_deterministic"] = probe.decision_fingerprint == probe_repeat.decision_fingerprint
    changed = evaluate_free_agent_offer_decision(state, build_preview(20_250_000.0))
    checks["offer_change_changes_decision_fingerprint"] = probe.decision_fingerprint != changed.decision_fingerprint
    checks["decision_matches_preview_helper_passes_current_decision"] = decision_matches_preview(
        state,
        build_preview(20_000_000.0),
        probe,
    )

    blocked = evaluate_free_agent_offer_decision(
        state,
        build_preview(20_000_000.0, status="manual_review", can_commit=False),
    )
    checks["nonpass_backend_offer_is_not_evaluated"] = blocked.status == "not_evaluated"

    if counter is not None:
        checks["counter_is_above_original_offer"] = (
            counter.counter_salary is not None and counter.counter_salary > counter.annual_salary
        )
        checks["counter_respects_salary_legality_ceiling"] = (
            counter.counter_salary is not None
            and counter.maximum_legal_salary is not None
            and counter.counter_salary <= counter.maximum_legal_salary + 0.01
        )
        checks["counter_respects_verified_cap_space"] = (
            counter.counter_salary is not None
            and counter.maximum_affordable_salary is not None
            and counter.counter_salary <= counter.maximum_affordable_salary + 0.01
        )
    else:
        checks["counter_is_above_original_offer"] = False
        checks["counter_respects_salary_legality_ceiling"] = False
        checks["counter_respects_verified_cap_space"] = False

    if accept is not None:
        try:
            commit_player_accepted_free_agency_preview_live(
                build_preview(accept.annual_salary),
                accept,
                hypothetical=True,
            )
        except FreeAgencyPlayerDecisionError:
            checks["hypothetical_player_acceptance_cannot_commit"] = True
        else:
            checks["hypothetical_player_acceptance_cannot_commit"] = False
    else:
        checks["hypothetical_player_acceptance_cannot_commit"] = False

    nonaccept = counter or decline or blocked
    try:
        commit_player_accepted_free_agency_preview_live(
            build_preview(nonaccept.annual_salary),
            nonaccept,
            hypothetical=False,
        )
    except FreeAgencyPlayerDecisionError:
        checks["counter_or_decline_cannot_commit"] = True
    else:
        checks["counter_or_decline_cannot_commit"] = False

    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    workspace_text = WORKSPACE.read_text(encoding="utf-8") if WORKSPACE.exists() else ""
    persistent_text = PERSISTENT.read_text(encoding="utf-8") if PERSISTENT.exists() else ""
    negotiation_text = NEGOTIATION.read_text(encoding="utf-8") if NEGOTIATION.exists() else ""
    checks["page_exists"] = PAGE.exists()
    checks["page_delegates_to_current_workspace"] = (
        WORKSPACE.exists()
        and "render_free_agency_workspace" in page_text
        and "render_free_agency_workspace(" in page_text
    )
    checks["workspace_imports_player_decision_engine"] = (
        "from franchise_free_agency_player_decision_v1 import" in workspace_text
        and "evaluate_free_agent_offer_decision(" in workspace_text
    )
    checks["workspace_submits_offer_explicitly"] = (
        '"Preview offer"' in workspace_text
        and '"Open negotiation round 1"' in workspace_text
    )
    checks["workspace_exposes_player_response_paths"] = all(
        marker in workspace_text
        for marker in (
            "Player response: READY TO SIGN",
            "Player response: COUNTER MARKET",
            "Player response: NO ACCEPTABLE OFFER",
        )
    )
    checks["workspace_exposes_player_preference_profile"] = (
        "Player preference profile" in workspace_text
    )
    checks["workspace_gates_durable_signing_on_player_acceptance"] = (
        "player_accepted" in workspace_text and "and player_accepted" in workspace_text
    )
    checks["workspace_uses_persistent_commit_wrapper"] = (
        "commit_persistent_user_winner_live(" in workspace_text
        and "return commit_negotiated_user_winner_live(" in persistent_text
        and "commit_competing_market_winner_live(" in negotiation_text
    )
    checks["page_does_not_call_live_signing_directly"] = (
        "commit_contract_legal_free_agency_preview_live(" not in page_text
        and "commit_contract_legal_free_agency_preview_live(" not in workspace_text
    )
    checks["workspace_preserves_explicit_confirmation"] = (
        "I confirm this signing" in workspace_text
        and 'key="fa_live_sign_button"' in workspace_text
    )
    checks["workspace_preserves_live_sign_button"] = "Confirm and sign" in workspace_text
    checks["workspace_preserves_hypothetical_commit_block"] = "preview_is_hypothetical" in workspace_text
    checks["workspace_preserves_non_offseason_commit_block"] = 'phase == "offseason"' in workspace_text
    checks["workspace_refreshes_both_live_session_states"] = (
        'st.session_state["franchise_simulation_league_state"]' in workspace_text
        and 'st.session_state["franchise_trade_league_state"]' in workspace_text
    )
    try:
        compile(page_text, str(PAGE), "exec")
        compile(workspace_text, str(WORKSPACE), "exec")
        compile(persistent_text, str(PERSISTENT), "exec")
        compile(negotiation_text, str(NEGOTIATION), "exec")
        checks["page_compiles"] = True
    except Exception:
        checks["page_compiles"] = False

    after_hash = _sha256(checkpoint_path) if checkpoint_path.exists() else ""
    checks["validator_did_not_write_checkpoint"] = before_hash == after_hash
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "validator": VALIDATOR_VERSION,
        "player_decision": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "live_signing": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy_profile": {
            "archetype": profile_one.archetype,
            "acceptance_threshold": profile_one.acceptance_threshold,
            "open_role_score": role_open,
            "crowded_role_score": role_crowded,
            "accept_salary": accept.annual_salary if accept is not None else None,
            "counter_offer_salary": counter.annual_salary if counter is not None else None,
            "counter_requested_salary": counter.counter_salary if counter is not None else None,
        },
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }

    print("=" * 108)
    print("FRANCHISE FREE AGENCY PLAYER OFFER DECISIONS V1 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print("\nTOY PLAYER MARKET")
    print(f"  Archetype: {profile_one.archetype}")
    print(f"  Acceptance threshold: {profile_one.acceptance_threshold:.1f}")
    print(f"  Open role score: {role_open:.1f}")
    print(f"  Crowded role score: {role_crowded:.1f}")
    if counter is not None:
        print(f"  Counter path: ${counter.annual_salary:,.0f} offer -> ${counter.counter_salary:,.0f} counter")
    if accept is not None:
        print(f"  First accepted salary in toy scan: ${accept.annual_salary:,.0f}")
    print("\n" + json.dumps(report, indent=2, default=str))

    if failed:
        raise AssertionError(
            "Free Agency Player Offer Decisions V1 failed: " + ", ".join(failed)
        )

    print("\nFRANCHISE FREE AGENCY PLAYER OFFER DECISIONS V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live signing, roster move, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
