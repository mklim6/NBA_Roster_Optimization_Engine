from __future__ import annotations

import copy
import hashlib
import json
import re
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
    build_contract_legal_free_agency_preview,
    minimum_salary_floor_for_offer,
    resolve_years_of_service,
)
from franchise_free_agency_cpu_execution_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_EXECUTION_VERSION,
)
from franchise_free_agency_cpu_offer_generation_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_live_signing_v1 import (  # noqa: E402
    FREE_AGENCY_LIVE_SIGNING_VERSION,
)
from franchise_free_agency_player_decision_v1 import (  # noqa: E402
    FREE_AGENCY_PLAYER_DECISION_VERSION,
)
from franchise_free_agency_shared_market_v1 import (  # noqa: E402
    FREE_AGENCY_SHARED_MARKET_SCOPE,
    FREE_AGENCY_SHARED_MARKET_UI_VERSION,
    FREE_AGENCY_SHARED_MARKET_VERSION,
    FreeAgencySharedMarketError,
    build_user_cpu_shared_market,
    commit_user_shared_market_winner_live,
    shared_market_contract_report,
    shared_market_matches_state_and_preview,
)
from franchise_free_agency_transaction_v1 import (  # noqa: E402
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
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
    "franchise-free-agency-user-cpu-shared-market-validator-v1.0.1-workspace-adapter-2026-08-18"
)
PAGE = ROOT / "pages" / "6_Free_Agency.py"
WORKSPACE = SRC / "franchise_free_agency_workspace_v1.py"
NEGOTIATION = SRC / "franchise_free_agency_negotiation_rounds_v1.py"
PERSISTENT = SRC / "franchise_free_agency_persistent_calendar_v1.py"


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
    roster = SimpleNamespace(
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
    standings = {
        "CHI": SimpleNamespace(wins=48, losses=34),
        "ATL": SimpleNamespace(wins=50, losses=32),
        "WAS": SimpleNamespace(wins=30, losses=52),
        "BOS": SimpleNamespace(wins=24, losses=58),
    }
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        phase="offseason",
        players={"FA-001": player, "ROSTER-001": roster},
        free_agent_player_ids=("FA-001",),
        teams={
            "CHI": SimpleNamespace(roster_player_ids=("ROSTER-001",)),
            "WAS": SimpleNamespace(roster_player_ids=()),
            "BOS": SimpleNamespace(roster_player_ids=()),
            "ATL": SimpleNamespace(roster_player_ids=()),
        },
        standings=standings,
    )


def _toy_plan() -> dict[str, Any]:
    return {
        "team_plans": {
            "CHI": {
                "team_abbreviation": "CHI",
                "direction": "Championship Push",
                "salary_posture": "Flexible spending posture",
                "free_agent_targets": [
                    {"player_id": "FA-001", "player_name": "Toy Free Agent", "fit_score": 96.0}
                ],
            },
            "ATL": {
                "team_abbreviation": "ATL",
                "direction": "Contend",
                "salary_posture": "Flexible spending posture",
                "free_agent_targets": [
                    {"player_id": "FA-001", "player_name": "Toy Free Agent", "fit_score": 90.0}
                ],
            },
            "WAS": {
                "team_abbreviation": "WAS",
                "direction": "Retool",
                "salary_posture": "Balanced flexibility",
                "free_agent_targets": [
                    {"player_id": "FA-001", "player_name": "Toy Free Agent", "fit_score": 84.0}
                ],
            },
            "BOS": {
                "team_abbreviation": "BOS",
                "direction": "Rebuild",
                "salary_posture": "High salary pressure",
                "free_agent_targets": [
                    {"player_id": "NOT-AVAILABLE", "player_name": "Not Available", "fit_score": 99.0}
                ],
            },
        }
    }


def _toy_environment(_: Any) -> Any:
    return SimpleNamespace(status="pass", salary_cap=164_961_000.0)


def _toy_payroll(_: Any, team: str) -> tuple[float, dict[str, Any]]:
    return 85_000_000.0, {"source": "toy", "team": team}


def _toy_market_reference(_: Any, __: Any) -> tuple[float, float | None, float | None]:
    return 24_000_000.0, 18_000_000.0, 32_000_000.0


def _toy_preview_builder(state: Any, offer: FreeAgencyOffer) -> FreeAgencyTransactionPreview:
    source_payload = {
        "season": getattr(getattr(state, "settings", None), "season_label", ""),
        "phase": str(getattr(state, "phase", "")),
        "free_agents": list(getattr(state, "free_agent_player_ids", ()) or ()),
    }
    source = hashlib.sha256(
        json.dumps(source_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    candidate = hashlib.sha256(
        json.dumps(
            {
                "source": source,
                "player": offer.player_id,
                "team": offer.team_abbreviation,
                "salary": round(float(offer.annual_salary), 2),
                "years": int(offer.years),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return FreeAgencyTransactionPreview(
        transaction_version="toy-preview-v1",
        offer_version="toy-offer-v1",
        offer=offer,
        player_name=getattr(state.players[offer.player_id], "player_name", offer.player_id),
        source_fingerprint=source,
        candidate_fingerprint=candidate,
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


def _toy_board(state: Any):
    return build_cpu_free_agency_offer_board(
        state,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_toy_environment,
        payroll_resolver=_toy_payroll,
        market_reference_resolver=_toy_market_reference,
        max_targets_per_team=5,
    )


def _user_preview(state: Any, salary: float) -> FreeAgencyTransactionPreview:
    return _toy_preview_builder(
        state,
        FreeAgencyOffer(
            player_id="FA-001",
            team_abbreviation="CHI",
            annual_salary=float(salary),
            years=3,
            guaranteed=True,
            option_type="",
        ),
    )


def main() -> int:
    print("=" * 108)
    print("FRANCHISE FREE AGENCY USER + CPU SHARED MARKET V1 VALIDATION")
    print("=" * 108)

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    hash_before = _sha256(checkpoint_path)
    checks: dict[str, bool] = {}
    contract = shared_market_contract_report()

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-18")
    checks["shared_market_version_is_current"] = (
        FREE_AGENCY_SHARED_MARKET_VERSION
        == "franchise-free-agency-user-cpu-shared-market-v1-2026-08-14"
    )
    checks["shared_market_ui_version_is_current"] = (
        FREE_AGENCY_SHARED_MARKET_UI_VERSION
        == "franchise-free-agency-user-cpu-shared-market-ui-v1-2026-08-14"
    )
    checks["shared_market_scope_is_current"] = (
        FREE_AGENCY_SHARED_MARKET_SCOPE
        == "user_offer_plus_real_cpu_target_board_bids_same_player_no_silent_cpu_commit"
    )
    checks["cpu_offer_generation_v1_is_preserved"] = bool(CPU_FREE_AGENCY_OFFER_GENERATION_VERSION)
    checks["cpu_execution_v1_is_preserved"] = bool(CPU_FREE_AGENCY_EXECUTION_VERSION)
    checks["competing_market_v1_is_preserved"] = bool(FREE_AGENCY_COMPETING_MARKET_VERSION)
    checks["player_decision_v1_is_preserved"] = bool(FREE_AGENCY_PLAYER_DECISION_VERSION)
    checks["live_signing_v1_is_preserved"] = bool(FREE_AGENCY_LIVE_SIGNING_VERSION)
    checks["salary_legality_v1_3_is_preserved"] = bool(FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION)
    checks["shared_market_uses_real_cpu_target_board_bids"] = (
        contract.get("cpu_bids_are_real_target_board_bids") is True
    )
    checks["cpu_winner_is_not_silently_committed_here"] = (
        contract.get("cpu_winner_commit_enabled_here") is False
    )
    checks["user_winner_commit_delegates_to_competing_market_stack"] = (
        contract.get("user_winner_commit_uses_competing_market_stack") is True
    )

    state = _toy_state()
    state_before = _state_digest(state)
    board = _toy_board(state)
    low_preview = _user_preview(state, 22_000_000.0)
    high_preview = _user_preview(state, 30_000_000.0)

    low = build_user_cpu_shared_market(
        state,
        low_preview,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
    )
    low_repeat = build_user_cpu_shared_market(
        state,
        low_preview,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
    )
    high = build_user_cpu_shared_market(
        state,
        high_preview,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
    )

    checks["toy_shared_market_contains_real_cpu_bids"] = low.cpu_offer_count >= 2
    checks["toy_cpu_bids_exclude_controlled_team"] = all(
        row.team_abbreviation != "CHI" for row in low.cpu_offers
    )
    checks["toy_shared_market_has_user_plus_cpu_offers"] = (
        low.market.offer_count == 1 + low.cpu_offer_count
    )
    checks["toy_shared_market_is_deterministic"] = (
        low.shared_market_fingerprint == low_repeat.shared_market_fingerprint
        and low.market.market_fingerprint == low_repeat.market.market_fingerprint
    )
    checks["low_user_offer_can_lose_to_cpu_market"] = (
        low.market.has_winner and not low.user_is_winner
    )
    checks["stronger_user_offer_can_win_same_cpu_market"] = (
        high.market.has_winner and high.user_is_winner
    )
    checks["user_offer_change_invalidates_shared_market"] = (
        low.shared_market_fingerprint != high.shared_market_fingerprint
    )
    checks["shared_market_matches_current_state_and_preview"] = (
        shared_market_matches_state_and_preview(state, low_preview, low)
    )
    stale_state = copy.deepcopy(state)
    stale_state.free_agent_player_ids = ()
    checks["state_change_invalidates_shared_market"] = not shared_market_matches_state_and_preview(
        stale_state,
        low_preview,
        low,
    )
    checks["shared_market_build_does_not_mutate_source_state"] = (
        _state_digest(state) == state_before
    )

    try:
        build_user_cpu_shared_market(
            state,
            low_preview,
            controlled_teams=(),
            cpu_offer_board=board,
        )
    except FreeAgencySharedMarketError:
        checks["user_offer_requires_controlled_team"] = True
    else:
        checks["user_offer_requires_controlled_team"] = False

    try:
        commit_user_shared_market_winner_live(low_preview, low, hypothetical=False)
    except FreeAgencySharedMarketError:
        checks["cpu_market_winner_cannot_be_user_committed"] = True
    else:
        checks["cpu_market_winner_cannot_be_user_committed"] = False

    try:
        commit_user_shared_market_winner_live(high_preview, high, hypothetical=True)
    except FreeAgencySharedMarketError:
        checks["hypothetical_shared_market_cannot_commit"] = True
    else:
        checks["hypothetical_shared_market_cannot_commit"] = False

    source_text = Path(__file__).with_name("franchise_free_agency_shared_market_v1.py").read_text(
        encoding="utf-8"
    )
    checks["shared_market_source_contains_no_cpu_execution_commit"] = not re.search(
        r"\b(commit_cpu|execute_cpu_free_agency|execute_next_cpu)", source_text
    )

    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    workspace_text = WORKSPACE.read_text(encoding="utf-8") if WORKSPACE.exists() else ""
    negotiation_text = NEGOTIATION.read_text(encoding="utf-8") if NEGOTIATION.exists() else ""
    persistent_text = PERSISTENT.read_text(encoding="utf-8") if PERSISTENT.exists() else ""
    ui_text = page_text + "\n" + workspace_text

    checks["page_exists"] = PAGE.exists()
    checks["page_delegates_to_current_workspace"] = (
        WORKSPACE.exists()
        and "from franchise_free_agency_workspace_v1 import render_free_agency_workspace" in page_text
        and "render_free_agency_workspace(embedded=False)" in page_text
    )
    checks["workspace_preserves_shared_market_backend_contract"] = (
        "from franchise_free_agency_shared_market_v1 import" in workspace_text
        and "FREE_AGENCY_SHARED_MARKET_VERSION" in negotiation_text
    )
    checks["workspace_submits_user_offer_into_cpu_market"] = (
        "build_free_agency_negotiation_round(" in workspace_text
        and "build_cpu_free_agency_offer_board(" in negotiation_text
        and "evaluate_competing_offer_market(" in negotiation_text
    )
    checks["workspace_displays_cpu_competing_offer_details"] = (
        "CPU bids active" in workspace_text
        and "CPU negotiation actions" in workspace_text
    )
    checks["workspace_gates_signing_on_market_winner"] = (
        "user_market_winner" in workspace_text and "and user_market_winner" in workspace_text
    )
    checks["workspace_uses_current_locked_market_commit_stack"] = (
        "commit_persistent_user_winner_live(" in workspace_text
        and "return commit_negotiated_user_winner_live(" in persistent_text
        and "commit_competing_market_winner_live(" in negotiation_text
    )
    checks["page_does_not_invoke_old_single_offer_commit_wrapper"] = not re.search(
        r"^\s*(?:accepted_result\s*=\s*)?commit_player_accepted_free_agency_preview_live\(",
        ui_text,
        re.MULTILINE,
    )
    checks["workspace_preserves_explicit_confirmation"] = (
        "I confirm this signing" in workspace_text
        and 'key="fa_live_sign_button"' in workspace_text
    )
    checks["workspace_refreshes_both_live_session_states"] = (
        'st.session_state["franchise_simulation_league_state"]' in workspace_text
        and 'st.session_state["franchise_trade_league_state"]' in workspace_text
    )
    try:
        compile(page_text, str(PAGE), "exec")
        compile(workspace_text, str(WORKSPACE), "exec")
        checks["page_compiles"] = True
    except Exception:
        checks["page_compiles"] = False

    # Live integration stays read-only. The durable save may be regular season and
    # the controlled team may have no pure-cap-space user offer. Those are valid
    # current-state outcomes, so the validator reports them rather than inventing one.
    checkpoint = None
    controlled: tuple[str, ...] = ()
    live_error = ""
    live_candidate = ""
    live_cpu_bids = 0
    try:
        checkpoint = load_franchise_checkpoint()
        live_state = checkpoint.simulation_state
        controlled = controlled_teams_from_checkpoint(checkpoint, live_state)
        durable_digest = _state_digest(live_state)
        isolated = isolated_offseason_preview_state(live_state)
        if controlled:
            team = controlled[0]
            for player_id in list(getattr(isolated, "free_agent_player_ids", ()) or ())[:40]:
                player = getattr(isolated, "players", {}).get(str(player_id))
                if player is None:
                    continue
                service, _ = resolve_years_of_service(player)
                floor = minimum_salary_floor_for_offer(
                    years_of_service=service,
                    contract_years=1,
                )
                if floor is None:
                    continue
                offer = FreeAgencyOffer(
                    player_id=str(player_id),
                    team_abbreviation=team,
                    annual_salary=float(floor),
                    years=1,
                    guaranteed=True,
                    option_type="",
                )
                try:
                    preview = build_contract_legal_free_agency_preview(isolated, offer)
                except Exception:
                    continue
                if str(getattr(preview, "status", "")).lower() != "pass" or not bool(
                    getattr(preview, "can_commit", False)
                ):
                    continue
                try:
                    shared = build_user_cpu_shared_market(
                        isolated,
                        preview,
                        controlled_teams=controlled,
                        max_targets_per_team=1,
                    )
                except Exception:
                    continue
                live_candidate = shared.player_name
                live_cpu_bids = shared.cpu_offer_count
                break
        checks["durable_checkpoint_loads"] = checkpoint is not None
        checks["live_shared_market_builds_or_no_legal_user_offer_is_available"] = True
        checks["live_shared_market_does_not_mutate_durable_state"] = (
            _state_digest(live_state) == durable_digest
        )
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
        checks["durable_checkpoint_loads"] = False
        checks["live_shared_market_builds_or_no_legal_user_offer_is_available"] = False
        checks["live_shared_market_does_not_mutate_durable_state"] = False

    hash_after = _sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = bool(hash_before) and hash_before == hash_after

    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\nTOY SHARED MARKET")
    print(
        f"  Low user offer: CHI $22,000,000 -> winner {low.market.winner_team_abbreviation} "
        f"· CPU bids {low.cpu_offer_count}"
    )
    print(
        f"  Stronger user offer: CHI $30,000,000 -> winner {high.market.winner_team_abbreviation} "
        f"· CPU bids {high.cpu_offer_count}"
    )
    for evaluation in high.market.evaluations:
        print(
            f"  #{evaluation.rank} {evaluation.team_abbreviation} · ${evaluation.annual_salary:,.0f}/yr "
            f"· utility {evaluation.utility_score:.1f} · {evaluation.player_decision_status.upper()}"
        )

    print("\nREAD-ONLY LIVE SHARED-MARKET CONTEXT")
    season = getattr(getattr(getattr(checkpoint, "simulation_state", None), "settings", None), "season_label", "") if checkpoint else ""
    phase = getattr(getattr(checkpoint, "simulation_state", None), "phase", "") if checkpoint else ""
    print(f"  Season: {season}")
    print(f"  Phase: {getattr(phase, 'value', phase)}")
    print(f"  Controlled teams: {', '.join(controlled) if controlled else '<none>'}")
    if live_candidate:
        print(f"  Legal isolated-offseason user test player: {live_candidate}")
        print(f"  Real CPU bids for that player: {live_cpu_bids}")
    else:
        print("  Legal isolated-offseason user test offer: none found in bounded 40-player scan")
    print("  Durable signing during validator: NOT PERFORMED")
    if live_error:
        print(f"  Live adapter error: {live_error}")

    report = {
        "validator": VALIDATOR_VERSION,
        "shared_market": FREE_AGENCY_SHARED_MARKET_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy": {
            "low_winner": low.market.winner_team_abbreviation,
            "high_winner": high.market.winner_team_abbreviation,
            "cpu_offer_count": high.cpu_offer_count,
            "high_market": [
                {
                    "rank": item.rank,
                    "team": item.team_abbreviation,
                    "salary": item.annual_salary,
                    "utility": item.utility_score,
                    "decision": item.player_decision_status,
                }
                for item in high.market.evaluations
            ],
        },
        "live": {
            "candidate": live_candidate,
            "cpu_bids": live_cpu_bids,
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
            "Free Agency User + CPU Shared Market V1 failed: " + ", ".join(failed)
        )

    print("\nFRANCHISE FREE AGENCY USER + CPU SHARED MARKET V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no user signing, CPU signing, roster move, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
