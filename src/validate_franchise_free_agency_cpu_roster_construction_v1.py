from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace

import franchise_free_agency_cpu_roster_construction_v1 as rc
from franchise_free_agency_cpu_ai_audit_v1 import build_free_agency_cpu_ai_audit
from franchise_free_agency_cpu_offer_generation_v1 import build_cpu_free_agency_offer_board
from franchise_free_agency_live_signing_v1 import controlled_teams_from_durable_checkpoint

VALIDATOR_VERSION = "franchise-free-agency-cpu-roster-construction-validator-v1-2026-08-14"
EXPECTED_VERSION = "franchise-free-agency-cpu-roster-construction-intelligence-v1-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def player(pid: str, *, ovr: float, pot: float, age: float, position: str) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        player_name=f"Player {pid}",
        overall_rating=ovr,
        potential_rating=pot,
        age=age,
        position=position,
    )


def plan(*, direction: str, need: float, top: float, second: float, count: int = 3, rotation: int = 3, surplus: float = 0.0, prospect: SimpleNamespace | None = None) -> dict:
    decisions = []
    dev_ids = []
    if prospect is not None:
        dev_ids = [prospect.player_id]
        decisions = [{
            "player_id": prospect.player_id,
            "player_name": prospect.player_name,
            "age": prospect.age,
            "overall": prospect.overall_rating,
            "potential": prospect.potential_rating,
            "position": prospect.position,
            "position_family": "Guard" if "G" in prospect.position else "Center" if "C" in prospect.position else "Wing/Forward",
            "role": "Development",
        }]
    return {
        "team": "TST",
        "timeline_label": direction,
        "development_player_ids": dev_ids,
        "player_decisions": decisions,
        "position_profiles": {
            "Guard": {"need_score": need, "surplus_score": surplus, "count": count, "rotation_count": rotation, "top_overall": top, "second_overall": second, "young_upside_count": 1 if prospect else 0},
            "Wing/Forward": {"need_score": need, "surplus_score": surplus, "count": count, "rotation_count": rotation, "top_overall": top, "second_overall": second, "young_upside_count": 1 if prospect else 0},
            "Center": {"need_score": need, "surplus_score": surplus, "count": count, "rotation_count": rotation, "top_overall": top, "second_overall": second, "young_upside_count": 1 if prospect else 0},
        },
    }


def target(pid: str, *, lane: str = "Best value", family: str = "Guard", fit: float = 50.0) -> dict:
    return {"player_id": pid, "target_lane": lane, "position_family": family, "fit_score": fit}


def main() -> int:
    print("=" * 118, flush=True)
    print("CPU FREE AGENCY ROSTER CONSTRUCTION INTELLIGENCE V1 VALIDATION", flush=True)
    print("=" * 118, flush=True)
    checks: dict[str, bool] = {}

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("v1-2026-08-14")
    checks["roster_construction_version_is_current"] = rc.CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION == EXPECTED_VERSION
    report = rc.roster_construction_contract_report()
    checks["roster_construction_changes_no_cba_legality"] = report.get("cba_legality_changed") is False
    checks["roster_construction_has_no_autonomous_commit"] = report.get("autonomous_commit_enabled") is False
    checks["minimum_exception_targeting_remains_authoritative"] = report.get("minimum_exception_targeting_remains_authoritative") is True

    clear = rc.evaluate_roster_construction_target(
        None,
        player("clear", ovr=86, pot=89, age=25, position="PG"),
        plan(direction="Contend", need=65, top=79, second=76),
        target("clear", lane="Primary need", fit=88),
        team_abbreviation="TST",
        team_direction="Contend",
        target_fit_score=88,
    )
    depth = rc.evaluate_roster_construction_target(
        None,
        player("depth", ovr=73, pot=76, age=29, position="PG"),
        plan(direction="Contend", need=5, top=88, second=84, count=7, rotation=5, surplus=23),
        target("depth", lane="Best value", fit=35),
        team_abbreviation="TST",
        team_direction="Contend",
        target_fit_score=35,
    )
    checks["clear_starter_upgrade_scores_above_redundant_depth"] = clear.score > depth.score
    checks["clear_starter_upgrade_projects_starter_role"] = clear.projected_role in {"clear_starter_upgrade", "starter_upgrade"}
    checks["roster_score_is_bounded"] = all(0 <= x.score <= 100 for x in (clear, depth))
    checks["spending_multiplier_is_conservatively_bounded"] = all(0.94 <= x.spending_multiplier <= 1.06 for x in (clear, depth))

    prospect = player("prospect", ovr=77, pot=89, age=21, position="SF")
    veteran = rc.evaluate_roster_construction_target(
        None,
        player("vet", ovr=77, pot=78, age=31, position="SF"),
        plan(direction="Develop", need=10, top=82, second=78, prospect=prospect),
        target("vet", lane="Best value", family="Wing/Forward", fit=42),
        team_abbreviation="TST",
        team_direction="Develop",
        target_fit_score=42,
    )
    young = rc.evaluate_roster_construction_target(
        None,
        player("young", ovr=79, pot=88, age=23, position="SF"),
        plan(direction="Develop", need=45, top=82, second=78, prospect=prospect),
        target("young", lane="Secondary need", family="Wing/Forward", fit=68),
        team_abbreviation="TST",
        team_direction="Develop",
        target_fit_score=68,
    )
    checks["develop_team_identifies_veteran_prospect_blocking_risk"] = veteran.prospect_blocking_risk > young.prospect_blocking_risk
    checks["young_upside_addition_is_not_treated_like_veteran_blocking"] = young.prospect_blocking_risk <= 25.0
    checks["develop_team_can_filter_true_development_runway_blocker"] = (not veteran.allowed) and veteran.reason_code == "protect_development_runway"

    high_need = rc.evaluate_roster_construction_target(
        None, player("need", ovr=78, pot=82, age=26, position="C"),
        plan(direction="Retool", need=70, top=82, second=78), target("need", lane="Primary need", family="Center", fit=70),
        team_abbreviation="TST", team_direction="Retool", target_fit_score=70,
    )
    low_need = rc.evaluate_roster_construction_target(
        None, player("noneed", ovr=78, pot=82, age=26, position="C"),
        plan(direction="Retool", need=0, top=82, second=78, count=6, rotation=5, surplus=22), target("noneed", lane="Best value", family="Center", fit=45),
        team_abbreviation="TST", team_direction="Retool", target_fit_score=45,
    )
    checks["high_positional_need_increases_roster_score"] = high_need.score > low_need.score
    checks["crowded_position_increases_redundancy_risk"] = low_need.redundancy_risk > high_need.redundancy_risk
    checks["same_target_inputs_are_exactly_deterministic"] = clear == rc.evaluate_roster_construction_target(None, player("clear", ovr=86, pot=89, age=25, position="PG"), plan(direction="Contend", need=65, top=79, second=76), target("clear", lane="Primary need", fit=88), team_abbreviation="TST", team_direction="Contend", target_fit_score=88)

    original_decider = rc.evaluate_free_agent_offer_decision
    try:
        rc.evaluate_free_agent_offer_decision = lambda state, preview: SimpleNamespace(
            status="decline", utility_score=35.0, acceptance_threshold=58.0
        )
        preview = SimpleNamespace(offer=SimpleNamespace(annual_salary=4_000_000.0))
        weak_offer = rc.evaluate_roster_construction_offer(None, player("depth", ovr=73, pot=76, age=29, position="PG"), preview, high_need, market_salary_reference=10_000_000.0, financial_route="pure_cap_space_only")
        checks["noncompetitive_cap_limited_offer_can_be_filtered"] = (not weak_offer.allowed) and weak_offer.reason_code == "noncompetitive_cap_limited_offer"

        rc.evaluate_free_agent_offer_decision = lambda state, preview: SimpleNamespace(
            status="counter", utility_score=54.0, acceptance_threshold=58.0
        )
        mse_offer = rc.evaluate_roster_construction_offer(None, player("mse", ovr=72, pot=78, age=27, position="C"), SimpleNamespace(offer=SimpleNamespace(annual_salary=2_500_000.0)), high_need, market_salary_reference=2_400_000.0, financial_route="minimum_salary_exception")
        checks["minimum_exception_survivor_is_not_second_guessed_by_roster_offer_gate"] = mse_offer.allowed
    finally:
        rc.evaluate_free_agent_offer_decision = original_decider

    print("[1/3] Unit-level roster need, role, timeline, redundancy and prospect tests complete...", flush=True)
    print("[2/3] Building current isolated-offseason CPU board and deep audit...", flush=True)
    live_error = ""
    live_offers = live_skips = roster_filtered = 0
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
        repeat = build_cpu_free_agency_offer_board(analysis_state, controlled_teams=controlled, front_office_plan=front_plan, max_targets_per_team=5)
        live_offers = len(board.offers)
        live_skips = len(board.skipped)
        roster_filtered = sum(str(row.reason).startswith("roster_construction:") for row in board.skipped)
        checks["live_board_contains_generated_offers"] = live_offers > 0
        checks["live_board_same_state_replay_is_exact"] = board.board_fingerprint == repeat.board_fingerprint
        checks["all_live_offers_have_roster_metadata"] = all(0 <= row.roster_construction_score <= 100 and row.roster_target_fingerprint and row.roster_offer_fingerprint for row in board.offers)
        checks["all_live_submitted_offers_pass_roster_gate"] = all(row.roster_offer_status == "pass" for row in board.offers)
        audit = build_free_agency_cpu_ai_audit(checkpoint=durable, output_dir=Path("outputs") / "audits" / "validation_roster_construction_v1", max_targets_per_team=5)
        checks["integration_audit_strict_pass"] = audit.strict_pass
        checks["integration_audit_exports_roster_files"] = audit.row_counts.get("cpu_free_agency_roster_construction.csv", -1) == live_offers and "cpu_free_agency_roster_construction_flags.csv" in audit.row_counts
        checkpoint_hash_after = sha256(checkpoint_path)
        checks["validator_did_not_write_checkpoint"] = checkpoint_hash_before == checkpoint_hash_after
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
        checks["live_board_contains_generated_offers"] = False
        checks["live_board_same_state_replay_is_exact"] = False
        checks["all_live_offers_have_roster_metadata"] = False
        checks["all_live_submitted_offers_pass_roster_gate"] = False
        checks["integration_audit_strict_pass"] = False
        checks["integration_audit_exports_roster_files"] = False
        checks["validator_did_not_write_checkpoint"] = checkpoint_hash_before == checkpoint_hash_after if checkpoint_hash_before else False

    print("[3/3] Finalizing roster-construction validation...", flush=True)
    for key, value in checks.items():
        print(f"  {key}: {'PASS' if value else 'FAIL'}", flush=True)
    failed = [key for key, value in checks.items() if not value]
    print("", flush=True)
    print("LIVE ROSTER-CONSTRUCTION CONTEXT", flush=True)
    print(f"  Generated offers: {live_offers}", flush=True)
    print(f"  Total skipped targets: {live_skips}", flush=True)
    print(f"  Roster-construction filtered targets: {roster_filtered}", flush=True)
    print(f"  Checkpoint hash unchanged: {bool(checkpoint_hash_before and checkpoint_hash_before == checkpoint_hash_after)}", flush=True)
    if live_error:
        print(f"  Live error: {live_error}", flush=True)
    print("", flush=True)
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "roster_construction": rc.CPU_FREE_AGENCY_ROSTER_CONSTRUCTION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "live": {"generated_offers": live_offers, "skipped": live_skips, "roster_filtered": roster_filtered, "error": live_error},
        "checkpoint_hash_before": checkpoint_hash_before,
        "checkpoint_hash_after": checkpoint_hash_after,
        "passed": not failed,
    }, indent=2, sort_keys=True), flush=True)
    if failed:
        print("\nCPU FREE AGENCY ROSTER CONSTRUCTION INTELLIGENCE V1 VALIDATION FAILED", flush=True)
        return 1
    print("\nCPU FREE AGENCY ROSTER CONSTRUCTION INTELLIGENCE V1 VALIDATION PASSED", flush=True)
    print("READ-ONLY VALIDATION: no signing, roster mutation, negotiation advance, Trade Machine mutation, or checkpoint write was performed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
