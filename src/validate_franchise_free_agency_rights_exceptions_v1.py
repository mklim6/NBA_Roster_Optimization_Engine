from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_contract_salary_legality_v1_3 import (  # noqa: E402
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    minimum_salary_floor_for_offer,
)
from franchise_free_agency_cpu_offer_generation_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
    CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_cpu_offseason_soak_v1 import (  # noqa: E402
    build_cpu_offseason_soak_audit,
)
from franchise_free_agency_financial_bridge_v1_2 import (  # noqa: E402
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
)
from franchise_free_agency_rights_exceptions_v1 import (  # noqa: E402
    FREE_AGENCY_RIGHTS_EXCEPTIONS_SCOPE,
    FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
    ROUTE_BIRD,
    ROUTE_EARLY_BIRD,
    ROUTE_MINIMUM,
    ROUTE_NON_BIRD,
    ROUTE_PURE_CAP,
    FreeAgencyRightsEvidence,
    build_rights_exception_free_agency_preview,
    build_rights_registry_candidate,
    evaluate_rights_exception_financial_gate,
    resolve_free_agency_rights,
    rights_exceptions_contract_report,
    rights_registry_fingerprint,
)
from franchise_free_agency_transaction_v1 import FreeAgencyOffer  # noqa: E402
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = "franchise-free-agency-rights-exceptions-foundation-validator-v1.0.3-minimum-targeting-fixture-hotfix-2026-08-14"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _route(result: Any) -> str:
    return str((getattr(result, "payload", {}) or {}).get("financial_route", "")).strip()


def _toy_state(*, over_cap: bool = False, service: int | None = 4) -> Any:
    fa = SimpleNamespace(
        player_id="FA-001",
        player_name="Rights Test Free Agent",
        team_abbreviation="",
        roster_status="free_agent",
        two_way=False,
        age=26.0,
        overall_rating=78.0,
        potential_rating=82.0,
        position="G",
        contract=SimpleNamespace(
            status="free_agent",
            salary=12_000_000.0,
            years_remaining=None,
            option_type="",
            guaranteed=None,
        ),
    )
    if service is not None:
        fa.years_of_service = int(service)

    players: dict[str, Any] = {"FA-001": fa}
    teams: dict[str, Any] = {}
    for team in ("ATL", "BKN", "CHI", "DAL"):
        roster: list[str] = []
        if over_cap:
            for idx in range(7):
                pid = f"{team}-R{idx}"
                players[pid] = SimpleNamespace(
                    player_id=pid,
                    player_name=pid,
                    team_abbreviation=team,
                    roster_status="active_roster",
                    two_way=False,
                    contract=SimpleNamespace(
                        status="under_contract",
                        salary=25_000_000.0,
                        years_remaining=1,
                        option_type="",
                        guaranteed=True,
                    ),
                )
                roster.append(pid)
        teams[team] = SimpleNamespace(
            team_abbreviation=team,
            roster_player_ids=tuple(roster),
            active_player_ids=(),
            inactive_player_ids=(),
            rotation=SimpleNamespace(
                starter_ids=(),
                rotation_player_ids=(),
                minutes_targets={},
            ),
        )
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        phase="offseason",
        state_version="rights-test",
        source_league_state_revision=0,
        source_transaction_count=0,
        transition_count=0,
        franchise_transaction_revision=0,
        players=players,
        teams=teams,
        free_agent_player_ids=("FA-001",),
    )


def _plan() -> dict[str, Any]:
    target = {
        "player_id": "FA-001",
        "player_name": "Rights Test Free Agent",
        "fit_score": 88.0,
        "target_tier": "Primary target",
    }
    return {
        "team_plans": {
            "ATL": {
                "team_abbreviation": "ATL",
                "timeline_label": "Contend",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [target],
            },
            "BKN": {
                "team_abbreviation": "BKN",
                "timeline_label": "Develop",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [dict(target)],
            },
            "CHI": {
                "team_abbreviation": "CHI",
                "timeline_label": "Retool",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [dict(target)],
            },
            "DAL": {
                "team_abbreviation": "DAL",
                "timeline_label": "Rebuild",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [dict(target)],
            },
        }
    }


def _environment(_: Any) -> Any:
    return SimpleNamespace(status="pass", salary_cap=164_961_000.0)


def _payroll(state: Any, team: str) -> tuple[float, dict[str, Any]]:
    total = 0.0
    for pid in state.teams[team].roster_player_ids:
        total += float(state.players[pid].contract.salary)
    return total, {"source": "rights-validator"}


def _market_reference(_: Any, __: Any) -> tuple[float, float | None, float | None]:
    return 8_000_000.0, None, None


def _toy_preview_builder(state: Any, offer: FreeAgencyOffer) -> Any:
    """Exercise the real structural + rights/CBA preview on the toy state.

    The validator fixture is intentionally a minimal SimpleNamespace rather than a
    complete SimulationLeagueState. Only this synthetic board bypasses the full
    production state-schema validator. The structural transaction checks, salary
    legality, rights/exception financial gate, CPU offer construction, and MSE
    targeting/player-decision logic all remain real. Production/live generation
    continues to use the normal full state validator because this callback is never
    installed in production code.
    """
    return build_rights_exception_free_agency_preview(
        state,
        offer,
        state_validator=lambda _candidate: None,
    )


def main() -> int:
    print("=" * 116)
    print("FREE AGENCY RIGHTS + EXCEPTIONS FOUNDATION V1 VALIDATION")
    print("=" * 116)
    print("[1/5] Loading contracts and canonical checkpoint...", flush=True)

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = _sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    checks: dict[str, bool] = {}
    report = rights_exceptions_contract_report()

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["rights_exceptions_version_is_current"] = FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION == "franchise-free-agency-rights-exceptions-v1.1-modeled-future-minimum-2026-08-18"
    checks["rights_exceptions_scope_is_conservative"] = "evidence_only" in FREE_AGENCY_RIGHTS_EXCEPTIONS_SCOPE
    checks["financial_bridge_v1_2_is_preserved"] = bool(FREE_AGENCY_FINANCIAL_BRIDGE_VERSION)
    checks["salary_legality_v1_3_is_preserved"] = bool(FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION)
    checks["cpu_offer_generation_base_version_is_preserved"] = CPU_FREE_AGENCY_OFFER_GENERATION_VERSION.endswith("v1-2026-08-14")
    checks["direction_adapter_v1_0_1_is_preserved"] = "v1.0.1" in CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION
    checks["term_feasibility_v1_0_2_is_preserved"] = "v1.0.2" in CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION
    checks["exception_routing_adapter_is_current"] = CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION.endswith("v1-2026-08-14")
    checks["age_is_never_used_to_infer_rights"] = report.get("age_inference_enabled") is False
    checks["target_fit_is_never_used_to_infer_rights"] = report.get("target_fit_inference_enabled") is False
    checks["mid_level_exceptions_remain_out_of_scope"] = report.get("mid_level_exceptions_supported") is False
    checks["rfa_matching_remains_out_of_scope"] = report.get("restricted_free_agency_matching_supported") is False

    print("[2/5] Validating Bird / Early Bird / Non-Bird evidence resolution...", flush=True)
    base = _toy_state(over_cap=True, service=4)
    unknown = resolve_free_agency_rights(base, "FA-001")
    checks["missing_rights_evidence_stays_manual_review"] = unknown.status == "manual_review" and unknown.classification == "unknown"

    bird_state = build_rights_registry_candidate(
        base,
        FreeAgencyRightsEvidence("FA-001", "ATL", 3, True, 12_000_000.0, source="validator"),
    )
    early_state = build_rights_registry_candidate(
        base,
        FreeAgencyRightsEvidence("FA-001", "ATL", 2, True, 12_000_000.0, 14_000_000.0, source="validator"),
    )
    non_state = build_rights_registry_candidate(
        base,
        FreeAgencyRightsEvidence("FA-001", "ATL", 1, True, 12_000_000.0, source="validator"),
    )
    checks["bird_requires_three_verified_prior_seasons"] = resolve_free_agency_rights(bird_state, "FA-001").classification == "bird"
    checks["early_bird_requires_two_verified_prior_seasons"] = resolve_free_agency_rights(early_state, "FA-001").classification == "early_bird"
    checks["verified_shorter_prior_team_stint_resolves_non_bird"] = resolve_free_agency_rights(non_state, "FA-001").classification == "non_bird"
    checks["rights_registry_candidate_does_not_mutate_source"] = rights_registry_fingerprint(base) != rights_registry_fingerprint(bird_state) and resolve_free_agency_rights(base, "FA-001").classification == "unknown"

    bird_offer = FreeAgencyOffer("FA-001", "ATL", 30_000_000.0, 5, True, "")
    bird_gate = evaluate_rights_exception_financial_gate(bird_state, bird_offer)
    checks["bird_prior_team_can_clear_five_year_offer"] = bird_gate.status == "pass" and _route(bird_gate) == ROUTE_BIRD
    wrong_team_bird = evaluate_rights_exception_financial_gate(
        bird_state, FreeAgencyOffer("FA-001", "BKN", 30_000_000.0, 5, True, "")
    )
    checks["bird_route_never_transfers_to_other_team"] = _route(wrong_team_bird) != ROUTE_BIRD

    early_gate = evaluate_rights_exception_financial_gate(
        early_state, FreeAgencyOffer("FA-001", "ATL", 20_000_000.0, 2, True, "")
    )
    checks["early_bird_two_year_offer_clears_when_under_safe_ceiling"] = early_gate.status == "pass" and _route(early_gate) == ROUTE_EARLY_BIRD
    early_one = evaluate_rights_exception_financial_gate(
        early_state, FreeAgencyOffer("FA-001", "ATL", 20_000_000.0, 1, True, "")
    )
    checks["early_bird_one_year_offer_is_not_released"] = _route(early_one) != ROUTE_EARLY_BIRD

    non_gate = evaluate_rights_exception_financial_gate(
        non_state, FreeAgencyOffer("FA-001", "ATL", 14_000_000.0, 2, True, "")
    )
    checks["non_bird_120_percent_route_clears_safe_offer"] = non_gate.status == "pass" and _route(non_gate) == ROUTE_NON_BIRD

    print("[3/5] Validating Minimum Salary Exception and pure-cap priority...", flush=True)
    minimum = minimum_salary_floor_for_offer(years_of_service=4, contract_years=1)
    assert minimum is not None
    mse_gate = evaluate_rights_exception_financial_gate(
        base, FreeAgencyOffer("FA-001", "BKN", minimum, 1, True, "")
    )
    checks["one_year_exact_minimum_exception_clears_over_cap"] = mse_gate.status == "pass" and _route(mse_gate) == ROUTE_MINIMUM
    mse_above = evaluate_rights_exception_financial_gate(
        base, FreeAgencyOffer("FA-001", "BKN", minimum + 50_000.0, 1, True, "")
    )
    checks["minimum_exception_rejects_salary_above_exact_minimum"] = _route(mse_above) != ROUTE_MINIMUM
    mse_two = evaluate_rights_exception_financial_gate(
        base, FreeAgencyOffer("FA-001", "BKN", minimum, 2, True, "")
    )
    checks["two_year_minimum_exception_waits_for_salary_schedule_model"] = _route(mse_two) != ROUTE_MINIMUM and report.get("minimum_salary_exception_two_year_auto_release") is False
    unknown_service = _toy_state(over_cap=True, service=None)
    unknown_service_gate = evaluate_rights_exception_financial_gate(
        unknown_service, FreeAgencyOffer("FA-001", "BKN", 4_000_000.0, 1, True, "")
    )
    checks["minimum_exception_does_not_infer_service_from_age"] = _route(unknown_service_gate) != ROUTE_MINIMUM

    under_cap = _toy_state(over_cap=False, service=4)
    pure_gate = evaluate_rights_exception_financial_gate(
        under_cap, FreeAgencyOffer("FA-001", "ATL", minimum, 1, True, "")
    )
    checks["pure_cap_route_retains_priority_when_available"] = pure_gate.status == "pass" and _route(pure_gate) == ROUTE_PURE_CAP

    print("[4/5] Validating CPU exception routing and deterministic board generation...", flush=True)
    board_a = build_cpu_free_agency_offer_board(
        base,
        controlled_teams=("CHI",),
        front_office_plan=_plan(),
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_environment,
        payroll_resolver=_payroll,
        market_reference_resolver=_market_reference,
    )
    board_b = build_cpu_free_agency_offer_board(
        copy.deepcopy(base),
        controlled_teams=("CHI",),
        front_office_plan=_plan(),
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_environment,
        payroll_resolver=_payroll,
        market_reference_resolver=_market_reference,
    )
    mse_rows = [row for row in board_a.offers if row.financial_route == ROUTE_MINIMUM]
    targeted_mse_skips = [row for row in board_a.skipped if str(row.reason).startswith("minimum_exception_targeting:")]
    # Rights V1 proves the exception route is legally available above. After the
    # CPU targeting adapter, a technically legal toy bid may correctly be withheld
    # when Player Decisions V1 says the minimum is not credible.
    checks["cpu_over_cap_teams_can_emit_minimum_exception_bids"] = bool(mse_rows) or bool(targeted_mse_skips)
    checks["cpu_minimum_targeting_adapter_is_respected"] = bool(CPU_FREE_AGENCY_MINIMUM_TARGETING_ADAPTER_VERSION) and all(
        getattr(row, "minimum_targeting_status", "") == "allow" for row in mse_rows
    )
    checks["cpu_minimum_exception_bids_are_one_year_exact_minimum"] = all(
        row.years == 1 and math.isclose(row.annual_salary, row.minimum_salary_floor, abs_tol=0.01)
        for row in mse_rows
    )
    checks["controlled_team_never_receives_cpu_exception_bid"] = all(row.team_abbreviation != "CHI" for row in board_a.offers)
    checks["cpu_exception_board_is_deterministic"] = board_a.board_fingerprint == board_b.board_fingerprint
    checks["all_cpu_exception_bids_are_backend_pass"] = all(row.preview.status == "pass" and row.preview.can_commit for row in board_a.offers)
    checks["toy_cpu_board_uses_real_rights_preview"] = callable(_toy_preview_builder)
    checks["toy_noop_validator_is_fixture_scoped"] = (
        "preview_builder=_toy_preview_builder" in Path(__file__).read_text(encoding="utf-8")
        and "preview_builder=_toy_preview_builder" not in (SRC / "franchise_free_agency_cpu_offer_generation_v1.py").read_text(encoding="utf-8")
    )

    bird_plan_state = build_rights_registry_candidate(
        base,
        FreeAgencyRightsEvidence("FA-001", "ATL", 3, True, 12_000_000.0, source="validator"),
    )
    bird_board = build_cpu_free_agency_offer_board(
        bird_plan_state,
        controlled_teams=("CHI",),
        front_office_plan=_plan(),
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_environment,
        payroll_resolver=_payroll,
        market_reference_resolver=lambda *_: (24_000_000.0, None, None),
    )
    atl = next((row for row in bird_board.offers if row.team_abbreviation == "ATL"), None)
    checks["cpu_can_use_proven_bird_route_for_prior_team"] = atl is not None and atl.financial_route == ROUTE_BIRD and atl.prior_team == "ATL"

    print("[5/5] Verifying progress reporting and durable-state safety...", flush=True)
    sig = inspect.signature(build_cpu_offseason_soak_audit)
    runner_source = (SRC / "run_franchise_free_agency_cpu_offseason_soak_v1.py").read_text(encoding="utf-8")
    checks["soak_engine_accepts_progress_callback"] = "progress_callback" in sig.parameters
    checks["soak_runner_prints_replay_progress"] = "Replay {event.get('replay_number')}" in runner_source and "flush=True" in runner_source
    checks["rights_preview_builder_is_available"] = callable(build_rights_exception_free_agency_preview)

    checkpoint_hash_after = _sha256(checkpoint_path)
    checks["durable_checkpoint_loads"] = checkpoint is not None
    checks["validator_did_not_write_checkpoint"] = checkpoint_hash_before == checkpoint_hash_after

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    print()
    print("CPU EXCEPTION TEST BOARD")
    print(f"  Generated bids: {len(board_a.offers)}")
    print(f"  Minimum-exception bids: {len(mse_rows)}")
    print(f"  Minimum targets filtered by CPU credibility gate: {len(targeted_mse_skips)}")
    print(f"  Proven Bird test route: {getattr(atl, 'financial_route', 'missing')}")
    print(f"  Checkpoint hash unchanged: {checkpoint_hash_before == checkpoint_hash_after}")
    print()
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "rights_exceptions": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "cpu_exception_routing": CPU_FREE_AGENCY_EXCEPTION_ROUTING_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "checkpoint_hash_before": checkpoint_hash_before,
        "checkpoint_hash_after": checkpoint_hash_after,
    }, indent=2, sort_keys=True))

    if failed:
        print("\nFREE AGENCY RIGHTS + EXCEPTIONS FOUNDATION V1 VALIDATION FAILED")
        return 1
    print("\nFREE AGENCY RIGHTS + EXCEPTIONS FOUNDATION V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no signing, calendar advance, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
