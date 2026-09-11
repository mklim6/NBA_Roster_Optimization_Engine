from __future__ import annotations

import copy
import hashlib
import inspect
import json
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_negotiation_rounds_v1 import (  # noqa: E402
    FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION,
    MAX_FREE_AGENCY_NEGOTIATION_ROUNDS,
)
from franchise_free_agency_persistent_calendar_v1 import (  # noqa: E402
    FREE_AGENCY_CALENDAR_ATTR,
    FREE_AGENCY_PERSISTENT_CALENDAR_SCOPE,
    FREE_AGENCY_PERSISTENT_CALENDAR_UI_VERSION,
    FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
    MAX_FREE_AGENCY_CALENDAR_DAYS,
    FreeAgencyPersistentCalendarError,
    advance_free_agency_day_candidate,
    build_persistent_negotiation_result,
    free_agency_calendar_snapshot,
    initialize_free_agency_calendar_candidate,
    persist_negotiation_candidate,
    persistent_calendar_contract_report,
    persistent_calendar_fingerprint,
    persistent_market_for_player_team,
)
from franchise_free_agency_transaction_v1 import (  # noqa: E402
    FreeAgencyOffer,
    free_agency_state_fingerprint,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from validate_franchise_free_agency_shared_market_v1 import (  # noqa: E402
    _toy_board,
    _toy_plan,
    _toy_preview_builder,
    _toy_state,
    _user_preview,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-persistent-offseason-market-calendar-validator-v1-2026-08-14"
)
PAGE = ROOT / "pages" / "6_Free_Agency.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _state_digest(state: Any) -> str:
    payload = {
        "base": free_agency_state_fingerprint(state),
        "calendar_present": hasattr(state, FREE_AGENCY_CALENDAR_ATTR),
        "calendar": getattr(state, FREE_AGENCY_CALENDAR_ATTR, None),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _second_player_state() -> Any:
    state = _toy_state()
    second = copy.deepcopy(state.players["FA-001"])
    second.player_id = "FA-002"
    second.player_name = "Second Toy Free Agent"
    second.overall_rating = 80.0
    second.potential_rating = 82.0
    state.players["FA-002"] = second
    state.free_agent_player_ids = ("FA-001", "FA-002")
    return state


def _second_preview(state: Any, salary: float = 20_000_000.0) -> Any:
    return _toy_preview_builder(
        state,
        FreeAgencyOffer(
            player_id="FA-002",
            team_abbreviation="CHI",
            annual_salary=float(salary),
            years=3,
            guaranteed=True,
            option_type="",
        ),
    )


def main() -> int:
    print("=" * 112)
    print("FRANCHISE FREE AGENCY PERSISTENT OFFSEASON MARKET STATE + CALENDAR V1 VALIDATION")
    print("=" * 112)

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    hash_before = _sha256(checkpoint_path)
    checks: dict[str, bool] = {}
    contract = persistent_calendar_contract_report()

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("v1-2026-08-14")
    checks["persistent_calendar_version_is_current"] = (
        contract.get("version") == FREE_AGENCY_PERSISTENT_CALENDAR_VERSION
    )
    checks["persistent_calendar_ui_version_is_current"] = (
        FREE_AGENCY_PERSISTENT_CALENDAR_UI_VERSION
        == "franchise-free-agency-persistent-offseason-market-calendar-ui-v1-2026-08-14"
    )
    checks["persistent_calendar_scope_is_current"] = (
        contract.get("scope") == FREE_AGENCY_PERSISTENT_CALENDAR_SCOPE
    )
    checks["negotiation_rounds_v1_is_preserved"] = (
        contract.get("negotiation_rounds_version") == FREE_AGENCY_NEGOTIATION_ROUNDS_VERSION
    )
    checks["max_negotiation_rounds_remains_five"] = (
        contract.get("max_negotiation_rounds") == MAX_FREE_AGENCY_NEGOTIATION_ROUNDS == 5
    )
    checks["calendar_has_bounded_v1_horizon"] = (
        contract.get("max_calendar_days") == MAX_FREE_AGENCY_CALENDAR_DAYS == 30
    )
    checks["checkpoint_is_source_of_truth"] = bool(contract.get("checkpoint_owned"))
    checks["multiple_user_markets_are_supported"] = bool(contract.get("supports_multiple_user_markets"))
    checks["explicit_day_advance_is_required"] = bool(contract.get("explicit_day_advance_required"))
    checks["background_advancement_is_disabled"] = not bool(contract.get("background_advancement_enabled"))
    checks["background_cpu_signing_is_disabled"] = not bool(contract.get("background_cpu_signing_enabled"))
    checks["calendar_layer_does_not_write_trade_state"] = not bool(contract.get("writes_trade_state"))
    checks["calendar_layer_does_not_write_roster_or_contract_state"] = not bool(
        contract.get("writes_roster_or_contract_state")
    )

    state = _second_player_state()
    base_state_fingerprint = free_agency_state_fingerprint(state)
    source_digest = _state_digest(state)
    initial_snapshot = free_agency_calendar_snapshot(state)
    checks["missing_calendar_reads_as_safe_uninitialized_state"] = (
        not initial_snapshot.initialized
        and initial_snapshot.offseason_day == 0
        and initial_snapshot.active_market_count == 0
    )

    initialized = initialize_free_agency_calendar_candidate(state)
    initialized_snapshot = free_agency_calendar_snapshot(initialized)
    checks["calendar_initialization_is_candidate_only"] = _state_digest(state) == source_digest
    checks["calendar_initializes_at_day_one"] = (
        initialized_snapshot.initialized and initialized_snapshot.offseason_day == 1
    )
    checks["calendar_initialization_preserves_base_franchise_fingerprint"] = (
        free_agency_state_fingerprint(initialized) == base_state_fingerprint
    )
    checks["calendar_fingerprint_is_deterministic"] = (
        persistent_calendar_fingerprint(initialized)
        == persistent_calendar_fingerprint(copy.deepcopy(initialized))
    )

    board = _toy_board(state)
    preview1 = _user_preview(state, 30_000_000.0)
    candidate1, record1, round1 = persist_negotiation_candidate(
        state,
        preview1,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    snap1 = free_agency_calendar_snapshot(candidate1)
    checks["opening_market_is_persisted_at_round_one"] = (
        record1.current_round == 1
        and record1.market_id.startswith("FAMKT-")
        and snap1.active_market_count == 1
    )
    checks["persisting_market_does_not_mutate_source"] = _state_digest(state) == source_digest
    checks["persistent_market_preserves_negotiation_fingerprint"] = (
        record1.negotiation_fingerprint == round1.negotiation_fingerprint
    )
    checks["persistent_market_records_exact_offer_terms"] = (
        record1.annual_salary == 30_000_000.0
        and record1.years == 3
        and record1.guaranteed
    )
    checks["persistent_market_records_cpu_market_snapshot"] = (
        record1.active_cpu_offer_count == len(round1.cpu_offers)
        and len(record1.current_evaluations) == len(round1.market.evaluations)
    )
    checks["persistent_market_survives_pickle_reload"] = (
        free_agency_calendar_snapshot(pickle.loads(pickle.dumps(candidate1))).calendar_fingerprint
        == snap1.calendar_fingerprint
    )
    checks["persistent_market_lookup_is_player_team_keyed"] = (
        persistent_market_for_player_team(candidate1, "FA-001", "CHI") is not None
        and persistent_market_for_player_team(candidate1, "FA-001", "ATL") is None
    )

    preview2 = _second_preview(candidate1, 20_000_000.0)
    candidate2, record2, _ = persist_negotiation_candidate(
        candidate1,
        preview2,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    snap2 = free_agency_calendar_snapshot(candidate2)
    checks["two_user_negotiations_can_coexist"] = (
        snap2.active_market_count == 2
        and {row.player_id for row in snap2.active_markets} == {"FA-001", "FA-002"}
        and record1.market_id != record2.market_id
    )

    replaced, replaced_record, _ = persist_negotiation_candidate(
        candidate1,
        _user_preview(candidate1, 29_500_000.0),
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    replaced_snapshot = free_agency_calendar_snapshot(replaced)
    checks["new_user_offer_replaces_same_player_market"] = (
        replaced_snapshot.active_market_count == 1
        and replaced_record.market_id == record1.market_id
        and replaced_record.annual_salary == 29_500_000.0
    )
    checks["replaced_user_offer_archives_prior_market"] = replaced_snapshot.archived_market_count >= 1

    advanced, detail = advance_free_agency_day_candidate(
        candidate1,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    advanced_snapshot = free_agency_calendar_snapshot(advanced)
    advanced_record = persistent_market_for_player_team(advanced, "FA-001", "CHI")
    checks["one_day_advance_increments_calendar_once"] = (
        detail["prior_day"] == 1
        and detail["current_day"] == 2
        and advanced_snapshot.offseason_day == 2
    )
    checks["one_day_advances_open_market_at_most_one_round"] = (
        detail["markets_advanced"] == 1
        and advanced_record is not None
        and advanced_record.current_round == 2
    )
    checks["round_history_is_append_only_across_calendar_days"] = (
        advanced_record is not None
        and [row["round_number"] for row in advanced_record.round_history] == [1, 2]
    )
    checks["day_history_records_advancement_summary"] = (
        len(advanced_snapshot.day_history) >= 2
        and advanced_snapshot.day_history[-1].get("action") == "advance_free_agency_day"
        and int(advanced_snapshot.day_history[-1].get("markets_advanced", -1)) == 1
    )
    checks["calendar_advance_preserves_base_franchise_fingerprint"] = (
        free_agency_state_fingerprint(advanced) == base_state_fingerprint
    )

    rebuilt = build_persistent_negotiation_result(
        advanced,
        advanced_record,
        controlled_teams=("CHI",),
        front_office_plan=_toy_plan(),
        cpu_offer_board=board,
        preview_builder=_toy_preview_builder,
    )
    checks["reloaded_market_rebuilds_same_current_round"] = (
        rebuilt.round_number == advanced_record.current_round
        and rebuilt.negotiation_fingerprint == advanced_record.negotiation_fingerprint
    )

    unavailable = copy.deepcopy(candidate1)
    unavailable.free_agent_player_ids = tuple(
        pid for pid in unavailable.free_agent_player_ids if pid != "FA-001"
    )
    checks["signed_or_unavailable_player_disappears_from_effective_active_market_view"] = (
        persistent_market_for_player_team(unavailable, "FA-001", "CHI") is None
    )

    regular = copy.deepcopy(state)
    regular.phase = "regular_season"
    regular_rejected = False
    try:
        initialize_free_agency_calendar_candidate(regular)
    except FreeAgencyPersistentCalendarError:
        regular_rejected = True
    checks["persistent_calendar_write_requires_actual_offseason"] = regular_rejected

    source_text = inspect.getsource(sys.modules["franchise_free_agency_persistent_calendar_v1"])
    checks["calendar_engine_contains_no_cpu_signing_commit"] = (
        "commit_cpu_free_agency" not in source_text
        and "run_cpu_free_agency" not in source_text
    )
    checks["calendar_durable_write_has_recovery_copy"] = "shutil.copy2(checkpoint_path, recovery_path)" in source_text
    checks["calendar_durable_write_reloads_checkpoint"] = "observed_calendar = persistent_calendar_fingerprint(reloaded.simulation_state)" in source_text
    checks["calendar_durable_write_verifies_trade_state_unchanged"] = (
        "trade_state_fingerprint(reloaded.trade_state) != source_trade_fp" in source_text
    )
    checks["persistent_user_commit_delegates_to_locked_negotiation_stack"] = (
        "return commit_negotiated_user_winner_live(" in source_text
    )

    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
    checks["page_exists"] = PAGE.exists()
    checks["page_imports_persistent_calendar_engine"] = "franchise_free_agency_persistent_calendar_v1" in page_text
    checks["page_exposes_start_calendar_action"] = "Start free agency calendar" in page_text
    checks["page_exposes_advance_free_agency_day_action"] = "Advance free agency day" in page_text
    checks["page_exposes_active_persistent_negotiations"] = "Active persistent negotiations" in page_text
    checks["page_persists_user_negotiation"] = "persist_user_negotiation_durably(" in page_text
    checks["page_uses_persistent_user_commit_wrapper"] = "commit_persistent_user_winner_live(" in page_text
    checks["page_does_not_call_checkpoint_save_directly"] = "save_franchise_checkpoint(" not in page_text
    checks["page_keeps_hypothetical_negotiations_read_only"] = (
        "Hypothetical offer/negotiation previews remain read-only" in page_text
        and "if actual_offseason:" in page_text
    )
    try:
        compile(page_text, str(PAGE), "exec")
        checks["page_compiles"] = True
    except Exception:
        checks["page_compiles"] = False

    live_error = ""
    live_phase = ""
    live_calendar = None
    try:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is not None:
            live_state = checkpoint.simulation_state
            live_phase_obj = getattr(live_state, "phase", "")
            live_phase = str(getattr(live_phase_obj, "value", live_phase_obj))
            live_calendar = free_agency_calendar_snapshot(live_state)
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"
    checks["durable_checkpoint_loads"] = not bool(live_error)

    hash_after = _sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = bool(hash_before) and hash_before == hash_after

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print("\nTOY PERSISTENT FREE-AGENCY CALENDAR")
    print(
        f"  Day {snap1.offseason_day}: {snap1.active_market_count} active market · "
        f"{record1.player_name} round {record1.current_round} · response {record1.player_response}"
    )
    print(
        f"  Multi-market test: {snap2.active_market_count} simultaneous user negotiations"
    )
    print(
        f"  Day {advanced_snapshot.offseason_day}: advanced {detail['markets_advanced']} market(s) · "
        f"current round {advanced_record.current_round if advanced_record else 'closed'}"
    )
    print(
        f"  Reload fingerprint stable: "
        f"{rebuilt.negotiation_fingerprint == advanced_record.negotiation_fingerprint if advanced_record else False}"
    )

    print("\nREAD-ONLY LIVE CALENDAR CONTEXT")
    print(f"  Phase: {live_phase or 'unknown'}")
    if live_calendar is not None:
        print(f"  Calendar initialized: {live_calendar.initialized}")
        print(f"  Free Agency Day: {live_calendar.offseason_day}")
        print(f"  Active persistent markets: {live_calendar.active_market_count}")
    print("  Durable calendar write during validator: NOT PERFORMED")
    print(f"  Checkpoint hash unchanged: {hash_before == hash_after}")

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator": VALIDATOR_VERSION,
        "persistent_calendar": FREE_AGENCY_PERSISTENT_CALENDAR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "toy": {
            "day1_active_markets": snap1.active_market_count,
            "multi_market_count": snap2.active_market_count,
            "day2_round": advanced_record.current_round if advanced_record else None,
            "day_history_rows": len(advanced_snapshot.day_history),
            "archived_after_replace": replaced_snapshot.archived_market_count,
        },
        "live": {
            "phase": live_phase,
            "calendar_initialized": live_calendar.initialized if live_calendar is not None else None,
            "offseason_day": live_calendar.offseason_day if live_calendar is not None else None,
            "active_markets": live_calendar.active_market_count if live_calendar is not None else None,
            "error": live_error,
        },
        "checkpoint_hash_before": hash_before,
        "checkpoint_hash_after": hash_after,
        "passed": not failed,
    }
    print("\n" + json.dumps(report, indent=2, default=str))

    if failed:
        print("\nPersistent Offseason Market State + Calendar V1 validation failed: " + ", ".join(failed))
        return 1
    print("\nFRANCHISE FREE AGENCY PERSISTENT OFFSEASON MARKET STATE + CALENDAR V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no user signing, CPU signing, roster move, calendar write, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
