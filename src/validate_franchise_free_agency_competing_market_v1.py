from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from franchise_free_agency_competing_market_v1 import (
    FREE_AGENCY_COMPETING_MARKET_SCOPE,
    FREE_AGENCY_COMPETING_MARKET_VERSION,
    FreeAgencyCompetingMarketError,
    commit_competing_market_winner_live,
    evaluate_competing_offer_market,
    market_matches_previews,
    winner_preview_and_decision,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    evaluate_free_agent_offer_decision,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = "franchise-free-agency-competing-offer-market-validator-v1-2026-08-14"
EXPECTED_MARKET = "franchise-free-agency-competing-offer-market-v1-2026-08-14"
EXPECTED_PLAYER_DECISION = "franchise-free-agency-player-decision-v1-2026-08-14"
EXPECTED_SCOPE = "multiple_explicit_legal_offers_player_choice_no_cpu_offer_generation"


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
        "FA1": Player("FA1", "Decision Test Wing", 86.0, "SF", 27.0, 88.0, Contract(20_000_000.0)),
        "FA2": Player("FA2", "Other Free Agent", 80.0, "SG", 26.0, 82.0, Contract(8_000_000.0)),
    }
    teams: dict[str, Team] = {}
    base_ratings = [84, 83, 82, 81, 80, 79, 78, 77, 76, 75]
    base_positions = ["SF", "PG", "C", "SG", "PF", "PG", "C", "SG", "PF", "PG"]
    for team in ("CHI", "BOS", "WAS"):
        roster: list[str] = []
        for index, (rating, position) in enumerate(zip(base_ratings, base_positions), start=1):
            pid = f"{team}{index}"
            roster.append(pid)
            players[pid] = Player(pid, pid, float(rating), position, 27.0, float(rating), Contract(8_000_000.0))
        if team == "BOS":
            for index, rating in enumerate([92, 90, 88, 87], start=1):
                pid = f"BOSC{index}"
                roster.append(pid)
                players[pid] = Player(pid, pid, float(rating), "SF", 27.0, float(rating), Contract(12_000_000.0))
        teams[team] = Team(tuple(roster))

    return State(
        settings=SimpleNamespace(season_label="2026-27"),
        players=players,
        teams=teams,
        standings={
            "CHI": Standing(52, 30),
            "BOS": Standing(62, 20),
            "WAS": Standing(20, 62),
        },
    )


def build_preview(
    team: str,
    salary: float,
    *,
    player_id: str = "FA1",
    status: str = "pass",
    can_commit: bool = True,
    years: int = 3,
) -> FreeAgencyTransactionPreview:
    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=float(salary),
        years=years,
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
        player_name=("Decision Test Wing" if player_id == "FA1" else "Other Free Agent"),
        source_fingerprint=f"TOY-{player_id}-{team}-{salary:.0f}-{status}",
        candidate_fingerprint=f"TOY-CANDIDATE-{player_id}-{team}-{salary:.0f}",
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

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["competing_market_version_is_current"] = FREE_AGENCY_COMPETING_MARKET_VERSION == EXPECTED_MARKET
    checks["player_decision_v1_is_preserved"] = FREE_AGENCY_PLAYER_DECISION_VERSION == EXPECTED_PLAYER_DECISION
    checks["market_scope_does_not_generate_cpu_offers"] = FREE_AGENCY_COMPETING_MARKET_SCOPE == EXPECTED_SCOPE

    checkpoint = load_franchise_checkpoint()
    checks["durable_checkpoint_exists"] = checkpoint is not None and checkpoint_path.exists()
    checks["durable_checkpoint_loads"] = checkpoint is not None

    state = build_toy_state()
    chi = build_preview("CHI", 25_000_000.0)
    bos = build_preview("BOS", 25_000_000.0)
    was = build_preview("WAS", 27_000_000.0)
    previews = (chi, bos, was)
    market = evaluate_competing_offer_market(state, previews)
    market_repeat = evaluate_competing_offer_market(state, previews)
    market_reordered = evaluate_competing_offer_market(state, (was, chi, bos))

    checks["three_offer_market_is_evaluated"] = market.offer_count == 3
    checks["all_backend_pass_offers_are_counted"] = market.backend_pass_offer_count == 3
    checks["toy_market_has_multiple_accepted_offers"] = market.accepted_offer_count >= 2
    checks["toy_market_selects_a_winner"] = market.status == "winner_selected" and market.has_winner
    checks["market_is_deterministic"] = market == market_repeat
    checks["market_fingerprint_is_order_independent"] = market.market_fingerprint == market_reordered.market_fingerprint
    checks["winner_is_highest_total_utility"] = (
        market.winner_utility_score is not None
        and market.winner_utility_score == max(row.utility_score for row in market.evaluations if row.accepted)
    )
    checks["higher_salary_does_not_automatically_win"] = (
        market.winner_team_abbreviation == "CHI"
        and was.offer.annual_salary > chi.offer.annual_salary
    )
    checks["winning_margin_is_nonnegative"] = market.winning_margin is None or market.winning_margin >= 0.0
    checks["market_ranks_every_offer_once"] = (
        sorted(row.rank for row in market.evaluations) == [1, 2, 3]
        and len({row.team_abbreviation for row in market.evaluations}) == 3
    )
    checks["market_matches_current_previews"] = market_matches_previews(state, previews, market)

    changed = (build_preview("CHI", 25_250_000.0), bos, was)
    checks["offer_change_invalidates_market_fingerprint"] = not market_matches_previews(state, changed, market)

    winner_preview, winner_decision = winner_preview_and_decision(state, previews, market)
    checks["winner_reconciles_to_accepted_player_decision"] = (
        winner_decision.status == "accept"
        and winner_decision.team_abbreviation == market.winner_team_abbreviation
        and evaluate_free_agent_offer_decision(state, winner_preview).decision_fingerprint
        == market.winner_decision_fingerprint
    )

    low_market = evaluate_competing_offer_market(
        state,
        (
            build_preview("CHI", 2_500_000.0),
            build_preview("BOS", 2_500_000.0),
            build_preview("WAS", 2_500_000.0),
        ),
    )
    checks["lowball_market_has_no_false_winner"] = not low_market.has_winner
    checks["lowball_market_is_counter_or_no_offer"] = low_market.status in {"counter_market", "no_acceptable_offer"}

    mixed_pass = build_preview("CHI", 20_000_000.0)
    mixed_blocked = build_preview("BOS", 41_000_000.0, status="manual_review", can_commit=False)
    mixed_market = evaluate_competing_offer_market(state, (mixed_pass, mixed_blocked))
    checks["nonpass_offer_cannot_become_market_winner"] = (
        mixed_market.winner_team_abbreviation != "BOS"
        and next(row for row in mixed_market.evaluations if row.team_abbreviation == "BOS").player_decision_status == "not_evaluated"
    )

    try:
        evaluate_competing_offer_market(state, (chi, build_preview("CHI", 26_000_000.0)))
    except FreeAgencyCompetingMarketError:
        checks["duplicate_team_offers_are_rejected"] = True
    else:
        checks["duplicate_team_offers_are_rejected"] = False

    try:
        evaluate_competing_offer_market(state, (chi, build_preview("BOS", 20_000_000.0, player_id="FA2")))
    except FreeAgencyCompetingMarketError:
        checks["mixed_player_market_is_rejected"] = True
    else:
        checks["mixed_player_market_is_rejected"] = False

    try:
        commit_competing_market_winner_live(previews, market, hypothetical=True)
    except FreeAgencyCompetingMarketError:
        checks["hypothetical_competing_market_cannot_commit"] = True
    else:
        checks["hypothetical_competing_market_cannot_commit"] = False

    try:
        commit_competing_market_winner_live(
            (
                build_preview("CHI", 2_500_000.0),
                build_preview("BOS", 2_500_000.0),
            ),
            evaluate_competing_offer_market(
                state,
                (
                    build_preview("CHI", 2_500_000.0),
                    build_preview("BOS", 2_500_000.0),
                ),
            ),
            hypothetical=False,
        )
    except FreeAgencyCompetingMarketError:
        checks["market_without_winner_cannot_commit"] = True
    else:
        checks["market_without_winner_cannot_commit"] = False

    single = evaluate_competing_offer_market(state, (chi,))
    single_decision = evaluate_free_agent_offer_decision(state, chi)
    checks["single_explicit_offer_matches_single_offer_decision"] = (
        single.has_winner == (single_decision.status == "accept")
        and single.winner_decision_fingerprint == (
            single_decision.decision_fingerprint if single_decision.status == "accept" else None
        )
    )

    after_hash = _sha256(checkpoint_path) if checkpoint_path.exists() else ""
    checks["validator_did_not_write_checkpoint"] = before_hash == after_hash
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "validator": VALIDATOR_VERSION,
        "competing_market": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "player_decision": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy_market": {
            "status": market.status,
            "winner": market.winner_team_abbreviation,
            "winner_utility": market.winner_utility_score,
            "runner_up": market.runner_up_team_abbreviation,
            "runner_up_utility": market.runner_up_utility_score,
            "winning_margin": market.winning_margin,
            "offers": [
                {
                    "rank": row.rank,
                    "team": row.team_abbreviation,
                    "salary": row.annual_salary,
                    "utility": row.utility_score,
                    "decision": row.player_decision_status,
                }
                for row in market.evaluations
            ],
        },
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }

    print("=" * 108)
    print("FRANCHISE FREE AGENCY COMPETING OFFER MARKET V1 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print("\nTOY COMPETING MARKET")
    print(f"  Status: {market.status}")
    print(f"  Winner: {market.winner_team_abbreviation} · utility {market.winner_utility_score:.1f}")
    if market.runner_up_team_abbreviation:
        print(f"  Runner-up: {market.runner_up_team_abbreviation} · utility {market.runner_up_utility_score:.1f}")
    for row in market.evaluations:
        print(
            f"  #{row.rank} {row.team_abbreviation} · ${row.annual_salary:,.0f}/yr · "
            f"utility {row.utility_score:.1f} · {row.player_decision_status.upper()}"
        )
    print("\n" + json.dumps(report, indent=2, default=str))

    if failed:
        raise AssertionError(
            "Free Agency Competing Offer Market V1 failed: " + ", ".join(failed)
        )

    print("\nFRANCHISE FREE AGENCY COMPETING OFFER MARKET V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no CPU offer, free-agent signing, roster move, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
