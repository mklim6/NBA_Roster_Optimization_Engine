from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_cpu_execution_v1 as api


VERSION = "franchise-cpu-free-agency-roster-floor-rescue-hotfix-validator-v1.0-2026-09-10"


def _fake_state(*, den_count: int = 7, controlled_team_count: int = 8, free_ids=("FA_ACCEPT",)):
    players = {}
    for pid in free_ids:
        players[pid] = SimpleNamespace(
            player_id=pid,
            player_name=pid.replace("_", " ").title(),
            overall_rating=70.0 if pid != "FA_COUNTER" else 72.0,
            age=27,
            years_of_service=3,
        )
    return SimpleNamespace(
        settings=SimpleNamespace(minimum_game_players=8, season_label="2027-28"),
        phase="offseason",
        teams={
            "DEN": SimpleNamespace(roster_player_ids=tuple(f"D{i}" for i in range(den_count))),
            "ATL": SimpleNamespace(roster_player_ids=tuple(f"A{i}" for i in range(controlled_team_count))),
        },
        players=players,
        free_agent_player_ids=tuple(free_ids),
    )


def _fake_preview(offer):
    return SimpleNamespace(
        status="pass",
        can_commit=True,
        offer=offer,
        source_fingerprint="synthetic-source",
    )


def _fake_decision(state, preview):
    pid = preview.offer.player_id
    salary = float(preview.offer.annual_salary)
    if pid == "FA_DECLINE":
        return SimpleNamespace(
            accepted=False,
            status="decline",
            counter_salary=None,
            utility_score=40.0,
            acceptance_threshold=70.0,
            decision_fingerprint=f"decline-{pid}-{salary}",
        )
    if pid == "FA_COUNTER" and salary <= 1_000_000.01:
        return SimpleNamespace(
            accepted=False,
            status="counter",
            counter_salary=1_200_000.0,
            utility_score=65.0,
            acceptance_threshold=70.0,
            decision_fingerprint=f"counter-{pid}-{salary}",
        )
    if pid == "FA_OVER_COUNTER" and salary <= 1_000_000.01:
        return SimpleNamespace(
            accepted=False,
            status="counter",
            counter_salary=1_600_000.0,
            utility_score=64.0,
            acceptance_threshold=70.0,
            decision_fingerprint=f"counter-{pid}-{salary}",
        )
    return SimpleNamespace(
        accepted=True,
        status="accept",
        counter_salary=None,
        utility_score=82.0 if pid == "FA_COUNTER" else 75.0,
        acceptance_threshold=70.0,
        decision_fingerprint=f"accept-{pid}-{salary}",
    )


def main() -> int:
    checks = {}
    details = {}

    checks["execution_protocol_version_preserved"] = (
        api.CPU_FREE_AGENCY_EXECUTION_VERSION
        == "franchise-free-agency-cpu-execution-v1-2026-08-14"
    )
    checks["roster_floor_rescue_version_present"] = bool(
        api.CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION
    )
    checks["counter_premium_is_bounded"] = (
        api.CPU_FREE_AGENCY_ROSTER_FLOOR_MAX_COUNTER_MULTIPLIER == 1.50
    )

    original = {
        "resolve_years_of_service": api.resolve_years_of_service,
        "minimum_salary_floor_for_state": api.minimum_salary_floor_for_state,
        "build_rights_exception_free_agency_preview": api.build_rights_exception_free_agency_preview,
        "evaluate_free_agent_offer_decision": api.evaluate_free_agent_offer_decision,
        "_season": api._season,
    }
    try:
        api.resolve_years_of_service = lambda player: (3, "synthetic")
        api.minimum_salary_floor_for_state = (
            lambda state, years_of_service, contract_years: 1_000_000.0
        )
        api.build_rights_exception_free_agency_preview = (
            lambda state, offer: _fake_preview(offer)
        )
        api.evaluate_free_agent_offer_decision = _fake_decision
        api._season = lambda state: "2027-28"

        state = _fake_state(free_ids=("FA_DECLINE", "FA_ACCEPT"))
        before = copy.deepcopy(state)
        deficits = api._cpu_roster_floor_deficits(state, ())
        checks["underfilled_cpu_team_detected"] = deficits == (("DEN", 7, 1),)
        checks["team_at_floor_is_not_rescued"] = all(row[0] != "ATL" for row in deficits)
        checks["controlled_underfilled_team_is_excluded"] = (
            api._cpu_roster_floor_deficits(state, ("DEN",)) == ()
        )

        opportunity = api.build_cpu_roster_floor_rescue_opportunity(state)
        checks["accepted_exact_minimum_candidate_is_found"] = (
            opportunity is not None and opportunity.player_id == "FA_ACCEPT"
        )
        checks["declining_candidate_is_not_selected"] = (
            opportunity is not None and opportunity.player_id != "FA_DECLINE"
        )
        checks["rescue_offer_is_one_year"] = (
            opportunity is not None and opportunity.years == 1
        )
        checks["rescue_offer_uses_exact_minimum_when_accepted"] = (
            opportunity is not None
            and opportunity.offer_path == "exact_minimum_accept"
            and abs(opportunity.annual_salary - 1_000_000.0) < 0.01
        )
        checks["source_state_is_not_mutated_by_rescue_search"] = (
            state.teams["DEN"].roster_player_ids == before.teams["DEN"].roster_player_ids
            and state.free_agent_player_ids == before.free_agent_player_ids
        )

        counter_state = _fake_state(free_ids=("FA_COUNTER",))
        counter = api.build_cpu_roster_floor_rescue_opportunity(counter_state)
        checks["bounded_player_counter_can_rescue_floor"] = (
            counter is not None
            and counter.offer_path == "bounded_counter_accept"
            and abs(counter.annual_salary - 1_200_000.0) < 0.01
        )

        over_state = _fake_state(free_ids=("FA_OVER_COUNTER",))
        over = api.build_cpu_roster_floor_rescue_opportunity(over_state)
        checks["excessive_counter_is_not_used_for_floor_rescue"] = over is None

        full_state = _fake_state(den_count=8, free_ids=("FA_ACCEPT",))
        checks["rescue_does_not_run_when_all_cpu_teams_meet_floor"] = (
            api.build_cpu_roster_floor_rescue_opportunity(full_state) is None
        )

    finally:
        for name, value in original.items():
            setattr(api, name, value)

    src = (SRC / "franchise_free_agency_cpu_execution_v1.py").read_text(encoding="utf-8")
    no_market = src.find("if not plan.opportunities:")
    rescue_call = src.find("build_cpu_roster_floor_rescue_opportunity(", no_market)
    normal_market = src.find("opportunity = plan.opportunities[0]", no_market)
    checks["rescue_is_only_reached_after_standard_market_exhausts"] = (
        no_market >= 0 and rescue_call > no_market and normal_market > rescue_call
    )
    checks["rescue_does_not_bypass_financial_preview"] = (
        "build_rights_exception_free_agency_preview(state, base_offer)" in src
        and "build_rights_exception_free_agency_preview(" in src
    )
    checks["rescue_requires_player_acceptance"] = (
        "if bool(getattr(decision, \"accepted\", False)):" in src
        and "if not bool(getattr(current_decision, \"accepted\", False)):" in src
    )
    checks["rescue_uses_existing_durable_cpu_commit_stack"] = (
        "return commit_cpu_contract_legal_free_agency_preview_live(" in src
    )
    report = api.cpu_execution_contract_report()
    checks["contract_report_exposes_rescue_safety"] = (
        report.get("roster_floor_rescue_cpu_only") is True
        and report.get("roster_floor_rescue_requires_underfilled_team") is True
        and report.get("roster_floor_rescue_preserves_locked_financial_gate") is True
        and report.get("roster_floor_rescue_requires_player_acceptance") is True
    )

    failed = [name for name, passed in checks.items() if not passed]
    payload = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(payload, indent=2))
    print()
    if failed:
        print("FRANCHISE CPU FREE AGENCY ROSTER FLOOR RESCUE HOTFIX V1 FAILED")
        return 1
    print("FRANCHISE CPU FREE AGENCY ROSTER FLOOR RESCUE HOTFIX V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
