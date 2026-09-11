from __future__ import annotations

import copy
import hashlib
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

from franchise_free_agency_competing_market_v1 import (  # noqa: E402
    FREE_AGENCY_COMPETING_MARKET_VERSION,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (  # noqa: E402
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
)
from franchise_free_agency_financial_bridge_v1_2 import (  # noqa: E402
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
)
from franchise_free_agency_player_decision_v1 import (  # noqa: E402
    FREE_AGENCY_PLAYER_DECISION_VERSION,
)
from franchise_free_agency_transaction_v1 import (  # noqa: E402
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
)
from franchise_free_agency_cpu_offer_generation_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    _extract_targets,
    _extract_team_plans,
    _front_office_plan_from_runtime,
    build_cpu_free_agency_offer_board,
    generation_contract_report,
)
from franchise_free_agency_ui_v1 import (  # noqa: E402
    controlled_teams_from_checkpoint,
    isolated_offseason_preview_state,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-cpu-offer-generation-validator-v1.1-exception-routing-2026-08-14"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _state_digest(state: Any) -> str:
    payload = {
        "season": str(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": str(getattr(state, "phase", "")),
        "free_agents": list(getattr(state, "free_agent_player_ids", ()) or ()),
        "teams": {
            str(team): list(getattr(team_state, "roster_player_ids", ()) or ())
            for team, team_state in sorted((getattr(state, "teams", {}) or {}).items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _toy_state() -> Any:
    player = SimpleNamespace(
        player_id="FA-001",
        player_name="Toy Free Agent",
        position="G",
        age=26.0,
        overall_rating=84.0,
        potential_rating=86.0,
        years_of_service=4,
        career_seasons=4,
        contract=SimpleNamespace(salary=12_000_000.0),
    )
    other = SimpleNamespace(
        player_id="ROSTER-001",
        player_name="Roster Player",
        position="G",
        age=27.0,
        overall_rating=78.0,
        potential_rating=79.0,
        years_of_service=5,
        career_seasons=5,
        contract=SimpleNamespace(salary=8_000_000.0),
    )
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        phase="offseason",
        players={"FA-001": player, "ROSTER-001": other},
        free_agent_player_ids=("FA-001",),
        teams={
            "CHI": SimpleNamespace(roster_player_ids=("ROSTER-001",)),
            "WAS": SimpleNamespace(roster_player_ids=()),
            "BOS": SimpleNamespace(roster_player_ids=()),
            "ATL": SimpleNamespace(roster_player_ids=()),
        },
    )


def _toy_plan(*, chi_fit: float = 96.0, chi_direction: str = "Championship Push") -> dict[str, Any]:
    target_chi = {
        "player_id": "FA-001",
        "player_name": "Toy Free Agent",
        "fit_score": chi_fit,
        "target_tier": "Primary target",
    }
    return {
        "team_plans": {
            "CHI": {
                "team_abbreviation": "CHI",
                "direction": chi_direction,
                "salary_posture": "Flexible spending posture",
                "free_agent_targets": [target_chi, dict(target_chi)],
            },
            "WAS": {
                "team_abbreviation": "WAS",
                "direction": "Retool",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [
                    {
                        "player_name": "Toy Free Agent",
                        "fit_score": 84.0,
                        "target_tier": "Secondary target",
                    }
                ],
            },
            "BOS": {
                "team_abbreviation": "BOS",
                "direction": "Rebuild",
                "salary_posture": "High salary pressure",
                "free_agent_targets": [
                    {
                        "player_id": "NOT-A-FREE-AGENT",
                        "player_name": "Not Available",
                        "fit_score": 99.0,
                    }
                ],
            },
            "ATL": {
                "team_abbreviation": "ATL",
                "direction": "Contend",
                "salary_posture": "Flexible spending posture",
                "free_agent_targets": [
                    {
                        "player_id": "FA-001",
                        "player_name": "Toy Free Agent",
                        "fit_score": 90.0,
                    }
                ],
            },
        }
    }


def _toy_environment(_: Any) -> Any:
    return SimpleNamespace(status="pass", salary_cap=164_961_000.0)


def _toy_payroll(_: Any, team: str) -> tuple[float, dict[str, Any]]:
    payrolls = {
        "CHI": 85_000_000.0,
        "WAS": 85_000_000.0,
        "BOS": 85_000_000.0,
        "ATL": 85_000_000.0,
    }
    return payrolls.get(team, 85_000_000.0), {"source": "toy"}


def _toy_market_reference(_: Any, __: Any) -> tuple[float, float | None, float | None]:
    return 24_000_000.0, 18_000_000.0, 32_000_000.0


def _toy_preview_builder(state: Any, offer: FreeAgencyOffer) -> FreeAgencyTransactionPreview:
    payload = {
        "player": offer.player_id,
        "team": offer.team_abbreviation,
        "salary": round(float(offer.annual_salary), 2),
        "years": int(offer.years),
    }
    source = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return FreeAgencyTransactionPreview(
        transaction_version="toy-preview-v1",
        offer_version="toy-offer-v1",
        offer=offer,
        player_name=getattr(state.players[offer.player_id], "player_name", offer.player_id),
        source_fingerprint=source,
        candidate_fingerprint=source,
        status="pass",
        can_commit=True,
        checks={"toy_pass": True},
        financial_gate=FreeAgencyFinancialGateResult(
            status="pass",
            reason="toy",
            payload={"salary_cap": 164_961_000.0, "route": "pure_cap_space_only"},
        ),
        roster_count_before=1,
        roster_count_after=2,
        message="toy pass",
    )


def _build_toy_board(
    *,
    controlled: tuple[str, ...] = (),
    chi_fit: float = 96.0,
    chi_direction: str = "Championship Push",
):
    state = _toy_state()
    board = build_cpu_free_agency_offer_board(
        state,
        controlled_teams=controlled,
        front_office_plan=_toy_plan(chi_fit=chi_fit, chi_direction=chi_direction),
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_toy_environment,
        payroll_resolver=_toy_payroll,
        market_reference_resolver=_toy_market_reference,
        max_targets_per_team=5,
    )
    return state, board


def main() -> int:
    print("=" * 108)
    print("FRANCHISE FREE AGENCY CPU OFFER GENERATION V1 VALIDATION")
    print("=" * 108)

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    hash_before = _sha256(checkpoint_path)
    checks: dict[str, bool] = {}

    contract = generation_contract_report()
    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["cpu_offer_generation_version_is_current"] = (
        CPU_FREE_AGENCY_OFFER_GENERATION_VERSION
        == "franchise-free-agency-cpu-offer-generation-v1-2026-08-14"
    )
    checks["cpu_offer_generation_scope_is_read_only"] = (
        CPU_FREE_AGENCY_OFFER_GENERATION_SCOPE
        == "read_only_cpu_bid_construction_from_existing_front_office_target_boards"
    )
    checks["competing_market_v1_is_preserved"] = bool(FREE_AGENCY_COMPETING_MARKET_VERSION)
    checks["player_decision_v1_is_preserved"] = bool(FREE_AGENCY_PLAYER_DECISION_VERSION)
    checks["salary_legality_v1_3_is_preserved"] = bool(FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION)
    checks["financial_bridge_v1_2_is_preserved"] = bool(FREE_AGENCY_FINANCIAL_BRIDGE_VERSION)
    checks["autonomous_commit_is_disabled"] = contract.get("autonomous_commit_enabled") is False
    checks["pure_cap_space_remains_first_choice"] = contract.get("pure_cap_space_remains_first_choice") is True
    checks["one_year_minimum_exception_route_is_enabled"] = contract.get("minimum_salary_exception_one_year_enabled") is True
    checks["prior_team_rights_require_explicit_evidence"] = contract.get("prior_team_rights_routes_enabled_with_explicit_evidence") is True
    checks["cpu_offer_max_term_is_four_years"] = contract.get("max_contract_term_years") == 4
    checks["cpu_offer_contracts_are_guaranteed_only"] = contract.get("guaranteed_contracts_only") is True

    # Deterministic injected market tests. These exercise bid construction without
    # touching any durable franchise object.
    toy_state, board = _build_toy_board()
    toy_digest_before = _state_digest(toy_state)
    _, board_repeat = _build_toy_board()
    checks["toy_board_generates_legal_cpu_bids"] = board.generated_offer_count >= 3
    checks["toy_board_is_deterministic"] = board.board_fingerprint == board_repeat.board_fingerprint
    checks["toy_board_has_no_duplicate_team_player_bids"] = len(
        {(row.team_abbreviation, row.player_id) for row in board.offers}
    ) == len(board.offers)
    checks["targets_outside_live_fa_pool_are_skipped"] = any(
        row.reason == "target_not_in_live_free_agent_pool" for row in board.skipped
    )
    checks["generated_bids_clear_locked_preview_contract"] = all(
        str(getattr(row.preview, "status", "")).lower() == "pass"
        and bool(getattr(row.preview, "can_commit", False))
        for row in board.offers
    )
    checks["generated_bids_are_one_to_four_years"] = all(1 <= row.years <= 4 for row in board.offers)
    checks["generated_bids_are_guaranteed_without_options"] = all(
        row.guaranteed and not row.option_type for row in board.offers
    )
    checks["generated_salary_respects_minimum_floor"] = all(
        row.annual_salary + 0.01 >= row.minimum_salary_floor for row in board.offers
    )
    checks["generated_salary_respects_v1_3_maximum"] = all(
        row.annual_salary <= row.maximum_initial_salary + 0.01 for row in board.offers
    )
    checks["generated_salary_respects_financial_route"] = all(
        (
            getattr(row, "financial_route", "pure_cap_space_only") != "pure_cap_space_only"
            or row.annual_salary <= row.cap_space_before + 0.01
        )
        and (
            getattr(row, "financial_route", "") != "minimum_salary_exception"
            or (row.years == 1 and math.isclose(row.annual_salary, row.minimum_salary_floor, abs_tol=0.01))
        )
        for row in board.offers
    )

    by_team = {row.team_abbreviation: row for row in board.offers if row.player_id == "FA-001"}
    checks["front_office_fit_changes_cpu_bid_strength"] = (
        "CHI" in by_team and "WAS" in by_team and by_team["CHI"].annual_salary > by_team["WAS"].annual_salary
    )

    _, controlled_board = _build_toy_board(controlled=("CHI",))
    checks["controlled_team_never_receives_cpu_bid"] = all(
        row.team_abbreviation != "CHI" for row in controlled_board.offers
    )
    checks["controlled_team_is_removed_from_cpu_team_count"] = controlled_board.cpu_team_count == 3

    _, lower_fit_board = _build_toy_board(chi_fit=72.0)
    lower_chi = next((row for row in lower_fit_board.offers if row.team_abbreviation == "CHI"), None)
    high_chi = by_team.get("CHI")
    checks["higher_fit_does_not_reduce_same_team_offer"] = bool(
        high_chi and lower_chi and high_chi.annual_salary >= lower_chi.annual_salary
    )
    checks["fit_change_changes_board_fingerprint"] = board.board_fingerprint != lower_fit_board.board_fingerprint

    _, rebuild_board = _build_toy_board(chi_direction="Rebuild")
    rebuild_chi = next((row for row in rebuild_board.offers if row.team_abbreviation == "CHI"), None)
    checks["championship_direction_is_more_aggressive_than_rebuild"] = bool(
        high_chi and rebuild_chi and high_chi.annual_salary > rebuild_chi.annual_salary
    )
    checks["toy_generation_does_not_mutate_source_state"] = _state_digest(toy_state) == toy_digest_before

    source_text = Path(__file__).with_name("franchise_free_agency_cpu_offer_generation_v1.py").read_text(
        encoding="utf-8"
    )
    checks["cpu_offer_generator_contains_no_commit_call"] = (
        "commit_free_agency" not in source_text
        and "commit_player" not in source_text
        and "commit_competing" not in source_text
    )

    # Real-project read-only integration. This proves the adapter can consume the
    # current CPU front-office planner and the current durable checkpoint.
    checkpoint = None
    live_error = ""
    live_plan_count = 0
    live_cpu_team_count = 0
    live_target_rows = 0
    live_generated = 0
    live_skipped = 0
    controlled: tuple[str, ...] = ()
    try:
        checkpoint = load_franchise_checkpoint()
        live_state = checkpoint.simulation_state
        controlled = controlled_teams_from_checkpoint(checkpoint, live_state)
        state_digest_before = _state_digest(live_state)
        live_plan = _front_office_plan_from_runtime(live_state, controlled)
        plan_rows = _extract_team_plans(live_plan)
        live_plan_count = len(plan_rows)
        live_cpu_team_count = sum(team not in set(controlled) for team, _ in plan_rows)
        live_target_rows = sum(len(_extract_targets(plan)) for _, plan in plan_rows)
        isolated = isolated_offseason_preview_state(live_state)
        live_board = build_cpu_free_agency_offer_board(
            isolated,
            controlled_teams=controlled,
            front_office_plan=live_plan,
            max_targets_per_team=1,
        )
        live_generated = live_board.generated_offer_count
        live_skipped = live_board.skipped_bid_count
        checks["durable_checkpoint_exists"] = checkpoint_path.exists()
        checks["durable_checkpoint_loads"] = checkpoint is not None
        checks["cpu_front_office_live_adapter_returns_30_team_plans"] = live_plan_count == 30
        checks["cpu_front_office_live_target_boards_are_visible"] = live_target_rows > 0
        checks["live_cpu_count_excludes_controlled_teams"] = (
            live_board.cpu_team_count == live_cpu_team_count
        )
        checks["live_generated_offers_exclude_controlled_teams"] = all(
            row.team_abbreviation not in set(controlled) for row in live_board.offers
        )
        checks["live_generated_offers_are_backend_pass_only"] = all(
            str(getattr(row.preview, "status", "")).lower() == "pass"
            and bool(getattr(row.preview, "can_commit", False))
            for row in live_board.offers
        )
        checks["live_cpu_generation_does_not_mutate_durable_state"] = (
            _state_digest(live_state) == state_digest_before
        )
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
        for name in (
            "durable_checkpoint_exists",
            "durable_checkpoint_loads",
            "cpu_front_office_live_adapter_returns_30_team_plans",
            "cpu_front_office_live_target_boards_are_visible",
            "live_cpu_count_excludes_controlled_teams",
            "live_generated_offers_exclude_controlled_teams",
            "live_generated_offers_are_backend_pass_only",
            "live_cpu_generation_does_not_mutate_durable_state",
        ):
            checks[name] = False

    hash_after = _sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = bool(hash_before) and hash_before == hash_after

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\nREAD-ONLY LIVE CPU OFFER CONTEXT")
    print(f"  Season: {getattr(getattr(getattr(checkpoint, 'simulation_state', None), 'settings', None), 'season_label', '') if checkpoint else ''}")
    print(f"  Controlled teams: {', '.join(controlled) if controlled else '<none>'}")
    print(f"  Team plans: {live_plan_count}")
    print(f"  CPU teams: {live_cpu_team_count}")
    print(f"  Target-board rows: {live_target_rows}")
    print(f"  Generated backend-PASS bids (top target/team scan): {live_generated}")
    print(f"  Skipped bid attempts: {live_skipped}")
    print("  Autonomous signing: NOT PERFORMED")
    if live_error:
        print(f"  Live adapter error: {live_error}")

    report = {
        "validator": VALIDATOR_VERSION,
        "cpu_offer_generation": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy_board": {
            "offers": [
                {
                    "team": row.team_abbreviation,
                    "player": row.player_name,
                    "fit": row.target_fit_score,
                    "salary": row.annual_salary,
                    "years": row.years,
                    "direction": row.team_direction,
                }
                for row in board.offers
            ],
            "skipped": [
                {
                    "team": row.team_abbreviation,
                    "player": row.player_name,
                    "reason": row.reason,
                }
                for row in board.skipped
            ],
        },
        "live": {
            "team_plans": live_plan_count,
            "cpu_team_count": live_cpu_team_count,
            "target_rows": live_target_rows,
            "generated_offers": live_generated,
            "skipped": live_skipped,
            "controlled_teams": list(controlled),
            "error": live_error,
        },
        "checkpoint_hash_before": hash_before,
        "checkpoint_hash_after": hash_after,
        "passed": not failed,
    }
    print("\n" + json.dumps(report, indent=2, default=str))

    if failed:
        raise AssertionError(
            "CPU Free Agency Offer Generation V1 validation failed: " + ", ".join(failed)
        )

    print("\nFRANCHISE FREE AGENCY CPU OFFER GENERATION V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no CPU offer was committed and no checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
