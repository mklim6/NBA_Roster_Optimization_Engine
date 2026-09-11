from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_competing_market_v1 import (  # noqa: E402
    FREE_AGENCY_COMPETING_MARKET_VERSION,
)
from franchise_free_agency_cpu_execution_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_EXECUTION_VERSION,
)
from franchise_free_agency_cpu_offer_generation_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_negotiation_rounds_v1 import (  # noqa: E402
    FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE,
    FREE_AGENCY_NEGOTIATION_ROUNDS_UI_VERSION,
    FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
    FreeAgencyNegotiationRoundsError,
    build_free_agency_negotiation_round,
    commit_negotiated_user_winner_live,
    negotiation_round_matches_state_and_preview,
    negotiation_rounds_contract_report,
)
from franchise_free_agency_player_decision_v1 import (  # noqa: E402
    FREE_AGENCY_PLAYER_DECISION_VERSION,
)
from franchise_free_agency_shared_market_v1 import (  # noqa: E402
    FREE_AGENCY_SHARED_MARKET_VERSION,
)
from validate_franchise_free_agency_shared_market_v1 import (  # noqa: E402
    _toy_board,
    _toy_environment,
    _toy_market_reference,
    _toy_payroll,
    _toy_plan,
    _toy_preview_builder,
    _toy_state,
    _user_preview,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-negotiation-market-rounds-validator-v1.0.1-workspace-adapter-2026-08-18"
)
PAGE = ROOT / "pages" / "6_Free_Agency.py"
WORKSPACE = SRC / "franchise_free_agency_workspace_v1.py"
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
        "standings": {
            str(team): (
                int(getattr(row, "wins", 0) or 0),
                int(getattr(row, "losses", 0) or 0),
            )
            for team, row in sorted((getattr(state, "standings", {}) or {}).items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _low_fit_board(state: Any):
    plan = copy.deepcopy(_toy_plan())
    plan["team_plans"]["WAS"]["free_agent_targets"][0]["fit_score"] = 60.0
    return build_cpu_free_agency_offer_board(
        state,
        controlled_teams=("CHI",),
        front_office_plan=plan,
        preview_builder=_toy_preview_builder,
        financial_environment_resolver=_toy_environment,
        payroll_resolver=_toy_payroll,
        market_reference_resolver=_toy_market_reference,
        max_targets_per_team=5,
    )


def main() -> int:
    print("=" * 108)
    print("FRANCHISE FREE AGENCY NEGOTIATION & MARKET ROUNDS V1 VALIDATION")
    print("=" * 108)

    cp_path = Path(DEFAULT_CHECKPOINT_PATH)
    hash_before = _sha256(cp_path)
    checks: dict[str, bool] = {}
    contract = negotiation_rounds_contract_report()

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-18")
    checks["negotiation_rounds_version_is_current"] = (
        contract.get("version") == FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION
    )
    checks["negotiation_rounds_ui_version_is_current"] = (
        FREE_AGENCY_NEGOTIATION_ROUNDS_UI_VERSION
        == "franchise-free-agency-negotiation-market-rounds-ui-v1-2026-08-14"
    )
    checks["negotiation_scope_is_current"] = (
        contract.get("scope") == FREE_AGENCY_NEGOTIATION_ROUNDS_SCOPE
    )
    checks["shared_market_v1_is_preserved"] = (
        contract.get("shared_market_version") == FREE_AGENCY_SHARED_MARKET_VERSION
    )
    checks["cpu_offer_generation_v1_is_preserved"] = (
        contract.get("cpu_offer_generation_version") == CPU_FREE_AGENCY_OFFER_GENERATION_VERSION
    )
    checks["cpu_execution_v1_is_preserved"] = CPU_FREE_AGENCY_EXECUTION_VERSION.endswith("v1-2026-08-14")
    checks["competing_market_v1_is_preserved"] = (
        contract.get("competing_market_version") == FREE_AGENCY_COMPETING_MARKET_VERSION
    )
    checks["player_decision_v1_is_preserved"] = (
        contract.get("player_decision_version") == FREE_AGENCY_PLAYER_DECISION_VERSION
    )
    checks["max_negotiation_rounds_is_five"] = (
        MAX_FREE_AGENCY_NEGOTIATION_ROUNDS == 5 and contract.get("max_rounds") == 5
    )
    checks["explicit_round_advance_is_required"] = bool(contract.get("explicit_advance_required"))
    checks["background_autonomy_is_disabled"] = not bool(contract.get("background_autonomy_enabled"))
    checks["cpu_winner_silent_commit_is_disabled"] = not bool(contract.get("cpu_winner_silent_commit_enabled"))
    checks["user_commit_requires_ready_to_sign"] = bool(contract.get("user_commit_requires_ready_to_sign"))
    checks["user_commit_requires_market_win"] = bool(contract.get("user_commit_requires_market_win"))

    state = _toy_state()
    state_before = _state_digest(state)
    board = _toy_board(state)
    user_preview = _user_preview(state, 30_000_000.0)

    round1 = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=1,
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    round1_again = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=1,
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    round2 = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=2,
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    round4 = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=4,
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    round5 = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=5,
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )

    checks["opening_round_contains_real_cpu_bids"] = len(round1.cpu_offers) == 2
    checks["opening_round_can_hold_accepted_market"] = (
        round1.market.has_winner and round1.player_response == "hold"
    )
    checks["same_round_is_deterministic"] = (
        round1.negotiation_fingerprint == round1_again.negotiation_fingerprint
    )
    checks["round_number_changes_negotiation_fingerprint"] = (
        round1.negotiation_fingerprint != round2.negotiation_fingerprint
    )
    checks["cpu_offer_can_increase_between_rounds"] = any(
        row.action == "increase" and row.annual_salary > row.prior_salary
        for row in round2.cpu_offers
    )
    checks["cpu_offer_never_decreases_when_active"] = all(
        row.annual_salary + 0.01 >= row.prior_salary
        for result in (round1, round2, round4, round5)
        for row in result.cpu_offers
    )
    checks["cpu_offer_increases_remain_backend_pass"] = all(
        str(getattr(row.preview, "status", "")).lower() == "pass"
        and bool(getattr(row.preview, "can_commit", False))
        for result in (round2, round4, round5)
        for row in result.cpu_offers
    )
    checks["final_round_resolves_accepted_winner"] = (
        round5.market.has_winner and round5.player_response == "ready_to_sign"
    )
    checks["history_contains_every_advanced_round"] = (
        len(round5.history) == 5
        and [row.round_number for row in round5.history] == [1, 2, 3, 4, 5]
    )
    checks["history_market_fingerprints_are_recorded"] = all(
        bool(row.market_fingerprint) for row in round5.history
    )

    low_fit_board = _low_fit_board(state)
    low_fit_round4 = build_free_agency_negotiation_round(
        state,
        user_preview,
        controlled_teams=("CHI",),
        round_number=4,
        cpu_offer_board=low_fit_board,
        preview_builder=_toy_preview_builder,
    )
    checks["low_fit_trailing_cpu_team_can_withdraw"] = (
        low_fit_round4.history[-1].withdrawn_cpu_offer_count >= 1
        and "WAS" not in {row.team_abbreviation for row in low_fit_round4.cpu_offers}
    )

    checks["negotiation_build_does_not_mutate_source_state"] = _state_digest(state) == state_before
    checks["current_round_matches_current_state_and_offer"] = negotiation_round_matches_state_and_preview(
        state,
        user_preview,
        round2,
        controlled_teams=("CHI",),
    )
    changed_offer = _user_preview(state, 29_500_000.0)
    checks["user_offer_change_invalidates_negotiation"] = not negotiation_round_matches_state_and_preview(
        state,
        changed_offer,
        round2,
        controlled_teams=("CHI",),
    )
    changed_state = copy.deepcopy(state)
    changed_state.free_agent_player_ids = ()
    checks["state_change_invalidates_negotiation"] = not negotiation_round_matches_state_and_preview(
        changed_state,
        user_preview,
        round2,
        controlled_teams=("CHI",),
    )

    checks["user_cannot_commit_while_player_holds"] = not round1.user_can_commit
    checks["cpu_winner_cannot_be_user_committed"] = not round5.user_can_commit

    strong_user_state = _toy_state()
    strong_user_state.standings["CHI"].wins = 60
    strong_user_state.standings["CHI"].losses = 22
    strong_user_state.standings["ATL"].wins = 40
    strong_user_state.standings["ATL"].losses = 42
    strong_board = _toy_board(strong_user_state)
    strong_preview = _user_preview(strong_user_state, 30_000_000.0)
    strong_round = build_free_agency_negotiation_round(
        strong_user_state,
        strong_preview,
        controlled_teams=("CHI",),
        round_number=1,
        cpu_offer_board=strong_board,
        preview_builder=_toy_preview_builder,
    )
    checks["user_can_win_ready_to_sign_negotiation"] = (
        strong_round.user_is_winner
        and strong_round.ready_to_sign
        and strong_round.user_can_commit
    )

    hypothetical_rejected = False
    try:
        commit_negotiated_user_winner_live(
            strong_preview,
            strong_round,
            hypothetical=True,
        )
    except FreeAgencyNegotiationRoundsError:
        hypothetical_rejected = True
    checks["hypothetical_negotiation_cannot_commit"] = hypothetical_rejected

    cpu_winner_rejected = False
    try:
        commit_negotiated_user_winner_live(
            user_preview,
            round5,
            hypothetical=False,
        )
    except FreeAgencyNegotiationRoundsError:
        cpu_winner_rejected = True
    checks["cpu_market_winner_is_rejected_before_user_commit"] = cpu_winner_rejected

    source_text = inspect.getsource(sys.modules["franchise_free_agency_negotiation_rounds_v1"])
    checks["negotiation_engine_contains_no_cpu_execution_commit"] = (
        "commit_cpu_free_agency" not in source_text
        and "run_cpu_free_agency" not in source_text
    )
    checks["negotiation_engine_rebuilds_before_user_commit"] = (
        "current = build_free_agency_negotiation_round(" in source_text
        and "current.negotiation_fingerprint != result.negotiation_fingerprint" in source_text
    )
    checks["negotiated_user_commit_uses_locked_competing_market_stack"] = (
        "commit_competing_market_winner_live(" in source_text
    )

    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    workspace_text = WORKSPACE.read_text(encoding="utf-8") if WORKSPACE.exists() else ""
    persistent_text = PERSISTENT.read_text(encoding="utf-8") if PERSISTENT.exists() else ""
    checks["page_exists"] = PAGE.exists()
    checks["page_delegates_to_current_workspace"] = (
        WORKSPACE.exists()
        and "from franchise_free_agency_workspace_v1 import render_free_agency_workspace" in page_text
        and "render_free_agency_workspace(embedded=False)" in page_text
    )
    checks["workspace_imports_negotiation_round_engine"] = "build_free_agency_negotiation_round" in workspace_text
    checks["workspace_opens_round_one_explicitly"] = "Open negotiation round 1" in workspace_text
    checks["workspace_advances_round_only_by_button"] = "Advance market one round" in workspace_text
    checks["workspace_exposes_cpu_hold_raise_withdraw_actions"] = "CPU negotiation actions" in workspace_text
    checks["workspace_exposes_negotiation_round_history"] = "Negotiation round history" in workspace_text
    checks["workspace_exposes_player_hold_state"] = "Player response: HOLD" in workspace_text
    checks["workspace_gates_signing_on_player_ready"] = (
        "player_ready_to_sign" in workspace_text
        and "and player_ready_to_sign" in workspace_text
    )
    checks["workspace_uses_negotiated_commit_stack"] = (
        "commit_persistent_user_winner_live(" in workspace_text
        and "return commit_negotiated_user_winner_live(" in persistent_text
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

    live_error = ""
    live_phase = ""
    controlled_text = ""
    live_state_unchanged = True
    try:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is not None:
            live_state = getattr(checkpoint, "simulation_state", None)
            live_phase_obj = getattr(live_state, "phase", "")
            live_phase = str(getattr(live_phase_obj, "value", live_phase_obj))
            preferences = getattr(checkpoint, "preferences", {}) or {}
            controlled = preferences.get("user_controlled_teams", ()) if isinstance(preferences, dict) else ()
            controlled_text = ", ".join(sorted(str(value) for value in controlled))
            before = _state_digest(live_state)
            # Read-only fingerprint and source-shape inspection only. The current
            # durable save may be regular season, so no live negotiation is forced.
            _ = getattr(live_state, "free_agent_player_ids", ())
            live_state_unchanged = _state_digest(live_state) == before
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
        live_state_unchanged = False

    checks["durable_checkpoint_loads"] = not bool(live_error)
    checks["live_validation_does_not_mutate_durable_state"] = live_state_unchanged

    hash_after = _sha256(cp_path)
    checks["validator_did_not_write_checkpoint"] = bool(hash_before) and hash_before == hash_after

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\nTOY NEGOTIATION MARKET")
    print(
        f"  Round 1: {round1.player_response} · winner {round1.market.winner_team_abbreviation} · "
        f"CPU bids {len(round1.cpu_offers)}"
    )
    print(
        f"  Round 2: {round2.player_response} · winner {round2.market.winner_team_abbreviation} · "
        f"CPU actions "
        + ", ".join(
            f"{row.team_abbreviation}:{row.action}:${row.annual_salary:,.0f}"
            for row in round2.cpu_offers
        )
    )
    print(
        f"  Round 4 low-fit withdrawal test: active CPU teams "
        + ", ".join(row.team_abbreviation for row in low_fit_round4.cpu_offers)
    )
    print(
        f"  Round 5: {round5.player_response} · winner {round5.market.winner_team_abbreviation}"
    )
    print(
        f"  Strong-user test: {strong_round.player_response} · winner {strong_round.market.winner_team_abbreviation}"
    )

    print("\nREAD-ONLY LIVE NEGOTIATION CONTEXT")
    print(f"  Phase: {live_phase or 'unknown'}")
    print(f"  Controlled teams: {controlled_text or 'not resolved in validator'}")
    print("  Durable user/CPU signing during validator: NOT PERFORMED")
    print(f"  Checkpoint hash unchanged: {hash_before == hash_after}")

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator": VALIDATOR_VERSION,
        "negotiation_rounds": FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy": {
            "round1_response": round1.player_response,
            "round1_winner": round1.market.winner_team_abbreviation,
            "round2_actions": [
                {
                    "team": row.team_abbreviation,
                    "action": row.action,
                    "salary": row.annual_salary,
                }
                for row in round2.cpu_offers
            ],
            "low_fit_round4_active_teams": [row.team_abbreviation for row in low_fit_round4.cpu_offers],
            "round5_response": round5.player_response,
            "round5_winner": round5.market.winner_team_abbreviation,
            "strong_user_response": strong_round.player_response,
            "strong_user_winner": strong_round.market.winner_team_abbreviation,
        },
        "live": {
            "phase": live_phase,
            "controlled_teams": controlled_text,
            "error": live_error,
        },
        "checkpoint_hash_before": hash_before,
        "checkpoint_hash_after": hash_after,
        "passed": not failed,
    }
    print("\n" + json.dumps(report, indent=2, default=str))

    if failed:
        print("\nNegotiation & Market Rounds V1 validation failed: " + ", ".join(failed))
        return 1
    print("\nFRANCHISE FREE AGENCY NEGOTIATION & MARKET ROUNDS V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no user signing, CPU signing, roster move, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
