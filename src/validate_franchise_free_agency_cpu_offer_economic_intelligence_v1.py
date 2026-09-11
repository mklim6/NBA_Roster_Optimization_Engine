from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import franchise_free_agency_cpu_offer_economic_intelligence_v1 as oe
from franchise_free_agency_cpu_ai_audit_v1 import build_free_agency_cpu_ai_audit
from franchise_free_agency_cpu_offer_generation_v1 import build_cpu_free_agency_offer_board
from franchise_free_agency_live_signing_v1 import controlled_teams_from_durable_checkpoint

VALIDATOR_VERSION = "franchise-free-agency-cpu-offer-economic-intelligence-validator-v1-2026-08-14"
EXPECTED_VERSION = "franchise-free-agency-cpu-offer-economic-intelligence-v1-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _player(pid: str, *, overall: float, age: float) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        player_name=f"Player {pid}",
        overall_rating=overall,
        age=age,
    )


def _preview(pid: str, team: str, salary: float, years: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        offer=SimpleNamespace(
            player_id=pid,
            team_abbreviation=team,
            annual_salary=salary,
            years=years,
            guaranteed=True,
            option_type="",
        )
    )


def _decision(*, status: str, interest: float, threshold: float, money: float = 0.40, role: float = 0.20, winning: float = 0.15, career: float = 0.10, patience: float = 0.50, role_score: float = 70.0, winning_score: float = 50.0, career_score: float = 70.0) -> SimpleNamespace:
    profile = SimpleNamespace(
        money_weight=money,
        role_weight=role,
        winning_weight=winning,
        career_fit_weight=career,
        market_patience=patience,
        acceptance_threshold=threshold,
    )
    return SimpleNamespace(
        status=status,
        utility_score=interest,
        acceptance_threshold=threshold,
        role_score=role_score,
        winning_score=winning_score,
        career_fit_score=career_score,
        preference_profile=profile,
    )


def main() -> int:
    print("=" * 122, flush=True)
    print("CPU FREE AGENCY OFFER ECONOMIC INTELLIGENCE V1 VALIDATION", flush=True)
    print("=" * 122, flush=True)
    checks: dict[str, bool] = {}

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("v1-2026-08-14")
    checks["economic_intelligence_version_is_current"] = oe.CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION == EXPECTED_VERSION
    report = oe.offer_economic_intelligence_contract_report()
    checks["economic_intelligence_changes_no_cba_legality"] = report.get("changes_cba_legality") is False
    checks["economic_intelligence_has_no_autonomous_commit"] = report.get("autonomous_commit_enabled") is False
    checks["minimum_exception_targeting_remains_authoritative"] = report.get("minimum_exception_targeting_remains_authoritative") is True
    checks["player_counter_is_preserved_as_live_negotiation"] = report.get("player_counter_is_preserved_as_live_negotiation") is True

    original = oe.evaluate_free_agent_offer_decision
    try:
        print("[1/4] Testing premium underpay, accepted discounts, counter preservation and MSE authority...", flush=True)
        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="decline", interest=54.0, threshold=58.0, money=0.40, role=0.26, patience=0.30, role_score=100.0, career_score=88.0
        )
        premium_lowball = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("premium", overall=87.0, age=22.0),
            _preview("premium", "TST", 5_700_000.0, 4),
            market_salary_reference=30_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=89.0,
            roster_projected_role="starter_upgrade",
        )
        checks["premium_token_market_offer_is_filtered"] = (not premium_lowball.allowed) and premium_lowball.reason_code in {"token_offer_vs_market", "market_discount_exceeds_player_context"}

        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="accept", interest=63.0, threshold=58.0, money=0.30, role=0.18, winning=0.30, patience=0.25, role_score=80.0, winning_score=96.0, career_score=82.0
        )
        accepted_discount = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("veteran", overall=79.0, age=32.0),
            _preview("veteran", "TST", 8_000_000.0, 2),
            market_salary_reference=11_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=82.0,
            roster_projected_role="rotation_upgrade",
        )
        checks["player_accepted_discount_is_preserved"] = accepted_discount.allowed and accepted_discount.reason_code == "player_accepts_offer"

        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="counter", interest=50.0, threshold=59.0, money=0.42, role_score=72.0
        )
        counter = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("counter", overall=78.0, age=27.0),
            _preview("counter", "TST", 6_000_000.0, 3),
            market_salary_reference=9_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=72.0,
            roster_projected_role="rotation",
        )
        checks["player_counter_keeps_market_live"] = counter.allowed and counter.reason_code == "player_counter_keeps_market_live"

        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="decline", interest=51.0, threshold=56.0, role_score=60.0
        )
        mse = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("mse", overall=73.0, age=28.0),
            _preview("mse", "TST", 2_200_000.0, 1),
            market_salary_reference=2_100_000.0,
            financial_route="minimum_salary_exception",
            roster_construction_score=64.0,
            roster_projected_role="depth",
        )
        checks["mse_survivor_is_not_second_guessed"] = mse.allowed and mse.reason_code == "minimum_exception_targeting_authoritative"

        print("[2/4] Testing contextual floors, discount support and determinism...", flush=True)
        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="decline", interest=51.0, threshold=58.0, money=0.44, role=0.12, winning=0.08, career=0.10, patience=0.90, role_score=55.0, winning_score=55.0, career_score=58.0
        )
        money_focused = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("money", overall=84.0, age=24.0),
            _preview("money", "TST", 13_000_000.0, 3),
            market_salary_reference=20_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=72.0,
            roster_projected_role="rotation",
        )
        oe.evaluate_free_agent_offer_decision = lambda state, preview: _decision(
            status="decline", interest=55.0, threshold=58.0, money=0.27, role=0.24, winning=0.28, career=0.12, patience=0.20, role_score=96.0, winning_score=96.0, career_score=90.0
        )
        fit_discount = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("fit", overall=84.0, age=30.0),
            _preview("fit", "TST", 13_000_000.0, 3),
            market_salary_reference=20_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=90.0,
            roster_projected_role="starter_level",
        )
        checks["strong_role_winning_fit_supports_larger_discount"] = fit_discount.minimum_credible_market_ratio < money_focused.minimum_credible_market_ratio
        checks["contextual_market_ratio_floor_is_bounded"] = all(0.42 <= row.minimum_credible_market_ratio <= 0.82 for row in (premium_lowball, accepted_discount, counter, mse, money_focused, fit_discount))
        checks["economic_credibility_score_is_bounded"] = all(0.0 <= row.economic_credibility_score <= 100.0 for row in (premium_lowball, accepted_discount, counter, mse, money_focused, fit_discount))
        repeat = oe.evaluate_cpu_offer_economic_intelligence(
            None,
            _player("fit", overall=84.0, age=30.0),
            _preview("fit", "TST", 13_000_000.0, 3),
            market_salary_reference=20_000_000.0,
            financial_route="pure_cap_space_only",
            roster_construction_score=90.0,
            roster_projected_role="starter_level",
        )
        checks["same_inputs_are_exactly_deterministic"] = repeat == fit_discount
    finally:
        oe.evaluate_free_agent_offer_decision = original

    print("[3/4] Building current isolated-offseason CPU board and deep audit...", flush=True)
    live_error = ""
    live_offers = live_skips = economic_filtered = 0
    checkpoint_hash_before = checkpoint_hash_after = ""
    try:
        checkpoint_module = __import__("simulation_franchise_checkpoint_v1")
        load_fn = getattr(checkpoint_module, "load_franchise_checkpoint")
        checkpoint_path = Path(getattr(checkpoint_module, "DEFAULT_CHECKPOINT_PATH", "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"))
        checkpoint_hash_before = sha256(checkpoint_path)
        durable = load_fn()
        live_state = getattr(durable, "simulation_state")
        analysis_state = copy.deepcopy(live_state)
        try:
            analysis_state.phase = "offseason"
        except Exception:
            import dataclasses
            if dataclasses.is_dataclass(analysis_state):
                analysis_state = dataclasses.replace(analysis_state, phase="offseason")
        controlled = tuple(sorted(controlled_teams_from_durable_checkpoint(durable)))
        fo_module = __import__("franchise_cpu_front_office_v1")
        front_plan = fo_module.build_league_front_office_plan(analysis_state, controlled_teams=controlled)
        board = build_cpu_free_agency_offer_board(analysis_state, controlled_teams=controlled, front_office_plan=front_plan, max_targets_per_team=5)
        repeat_board = build_cpu_free_agency_offer_board(analysis_state, controlled_teams=controlled, front_office_plan=front_plan, max_targets_per_team=5)
        live_offers = len(board.offers)
        live_skips = len(board.skipped)
        economic_filtered = sum(str(row.reason).startswith("offer_economics:") for row in board.skipped)
        checks["live_board_contains_generated_offers"] = live_offers > 0
        checks["live_board_same_state_replay_is_exact"] = board.board_fingerprint == repeat_board.board_fingerprint
        checks["all_live_submitted_offers_pass_economic_gate"] = all(getattr(row, "offer_economic_status", "") == "pass" for row in board.offers)
        checks["all_live_submitted_offers_have_economic_fingerprint"] = all(bool(getattr(row, "offer_economic_fingerprint", "")) for row in board.offers)
        audit = build_free_agency_cpu_ai_audit(checkpoint=durable, output_dir=Path("outputs") / "audits" / "validation_offer_economics_v1", max_targets_per_team=5)
        checks["integration_audit_strict_pass"] = audit.strict_pass
        checks["integration_audit_exports_offer_economic_files"] = audit.row_counts.get("cpu_free_agency_offer_economics.csv", -1) == live_offers and "cpu_free_agency_offer_economic_flags.csv" in audit.row_counts
        checkpoint_hash_after = sha256(checkpoint_path)
        checks["validator_did_not_write_checkpoint"] = checkpoint_hash_before == checkpoint_hash_after
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
        for key in (
            "live_board_contains_generated_offers",
            "live_board_same_state_replay_is_exact",
            "all_live_submitted_offers_pass_economic_gate",
            "all_live_submitted_offers_have_economic_fingerprint",
            "integration_audit_strict_pass",
            "integration_audit_exports_offer_economic_files",
        ):
            checks[key] = False
        checks["validator_did_not_write_checkpoint"] = checkpoint_hash_before == checkpoint_hash_after if checkpoint_hash_before else False

    print("[4/4] Finalizing Offer Economic Intelligence validation...", flush=True)
    for key, value in checks.items():
        print(f"  {key}: {'PASS' if value else 'FAIL'}", flush=True)
    failed = [key for key, value in checks.items() if not value]
    print("", flush=True)
    print("LIVE OFFER ECONOMIC CONTEXT", flush=True)
    print(f"  Generated offers after economic gate: {live_offers}", flush=True)
    print(f"  Total skipped targets: {live_skips}", flush=True)
    print(f"  Offer-economic filtered targets: {economic_filtered}", flush=True)
    print(f"  Checkpoint hash unchanged: {bool(checkpoint_hash_before and checkpoint_hash_before == checkpoint_hash_after)}", flush=True)
    if live_error:
        print(f"  Live error: {live_error}", flush=True)
    print("", flush=True)
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "offer_economic_intelligence": oe.CPU_FREE_AGENCY_OFFER_ECONOMIC_INTELLIGENCE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "live": {"generated_offers": live_offers, "skipped": live_skips, "economic_filtered": economic_filtered, "error": live_error},
        "checkpoint_hash_before": checkpoint_hash_before,
        "checkpoint_hash_after": checkpoint_hash_after,
        "passed": not failed,
    }, indent=2, sort_keys=True), flush=True)
    if failed:
        print("\nCPU FREE AGENCY OFFER ECONOMIC INTELLIGENCE V1 VALIDATION FAILED", flush=True)
        return 1
    print("\nCPU FREE AGENCY OFFER ECONOMIC INTELLIGENCE V1 VALIDATION PASSED", flush=True)
    print("READ-ONLY VALIDATION: no signing, roster mutation, negotiation advance, Trade Machine mutation, or checkpoint write was performed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
