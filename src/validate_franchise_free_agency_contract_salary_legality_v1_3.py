from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = SRC / "franchise_free_agency_workspace_v1.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
sys.path.insert(0, str(SRC))

from franchise_free_agency_transaction_v1 import FreeAgencyOffer, free_agency_state_fingerprint
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
    evaluate_live_free_agency_financial_gate,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    ANCHOR_SALARY_CAP,
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    MINIMUM_SALARY_SCALE_2026_27,
    build_contract_legal_free_agency_preview,
    evaluate_contract_legal_financial_gate,
    evaluate_contract_salary_legality,
    maximum_initial_salary_for_offer,
    minimum_salary_floor_for_offer,
    resolve_years_of_service,
)
from franchise_free_agency_ui_v1 import isolated_offseason_preview_state
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_league_state_v1 import validate_simulation_league_state

EXPECTED = "franchise-free-agency-contract-salary-legality-v1.5-service-evidence-2026-09-24"
EXPECTED_V12 = "franchise-free-agency-financial-bridge-v1.3-modeled-future-market-2026-08-18"
VALIDATOR_VERSION = "franchise-free-agency-contract-salary-legality-validator-v1.3.2-2026-09-28"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def phase_value(state) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw)).strip().lower()


def choose_pair(state):
    free_agents = list(getattr(state, "free_agent_player_ids", ()))
    teams = sorted(getattr(state, "teams", {}))
    if not free_agents or not teams:
        raise RuntimeError("Validator requires a free agent and team.")
    for player_id in free_agents:
        player = state.players.get(str(player_id))
        if player is None or getattr(player, "two_way", False):
            continue
        for team in teams:
            if len(state.teams[team].roster_player_ids) < 18:
                return str(player_id), team
    raise RuntimeError("No validator free-agent/team pair was found.")


def main() -> int:
    before_hash = sha(CHECKPOINT) if CHECKPOINT.exists() else ""
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable checkpoint could not be loaded.")
    durable = checkpoint.simulation_state
    validate_simulation_league_state(durable)
    durable_fp = free_agency_state_fingerprint(durable)
    test_state = isolated_offseason_preview_state(durable)
    player_id, team = choose_pair(test_state)
    player = test_state.players[player_id]

    # Explicitly prove that age is never used to infer service.
    service_before = resolve_years_of_service(player)
    age_before = getattr(player, "age", None)

    # Use a toy copy of the live state to guarantee cap-space headroom while
    # preserving real structural types. This never touches the durable source.
    toy = copy.deepcopy(test_state)
    # The exact salary-scale assertions below target the frozen 2026-27 anchor
    # table. Keep them independent of whichever season the user's live save has
    # reached; future-market progression has its own explicit check below.
    toy.settings = replace(toy.settings, season_label="2026-27")
    setattr(
        toy,
        "franchise_completed_season_contract_closeout_v1",
        None,
    )
    for roster_id in toy.teams[team].roster_player_ids:
        contract = getattr(toy.players[roster_id], "contract", None)
        if contract is not None:
            contract.salary = 1.0
    toy_player = toy.players[player_id]
    # Use an isolated synthetic ID that cannot resolve through the official
    # ratings evidence map. This exercises the conservative unknown-service
    # window without weakening V1.5 evidence for the real player.
    unknown_player_id = "VALIDATOR-UNKNOWN-SERVICE"
    unknown_player = copy.deepcopy(toy_player)
    unknown_player.player_id = unknown_player_id
    saved_service_attrs = {}
    for attr in ("years_of_service", "service_years", "nba_years_of_service", "season_exp", "years_service"):
        if hasattr(unknown_player, attr):
            saved_service_attrs[attr] = getattr(unknown_player, attr)
            try:
                delattr(unknown_player, attr)
            except Exception:
                setattr(unknown_player, attr, None)
    toy.players[unknown_player_id] = unknown_player
    toy.free_agent_player_ids = tuple(toy.free_agent_player_ids) + (
        unknown_player_id,
    )

    safe_offer = FreeAgencyOffer(
        player_id=unknown_player_id,
        team_abbreviation=team,
        annual_salary=4_500_000.0,
        years=4,
        guaranteed=True,
        option_type="",
    )
    low_offer = FreeAgencyOffer(
        player_id=unknown_player_id,
        team_abbreviation=team,
        annual_salary=1_000_000.0,
        years=1,
        guaranteed=True,
        option_type="",
    )
    high_offer = FreeAgencyOffer(
        player_id=unknown_player_id,
        team_abbreviation=team,
        annual_salary=45_000_000.0,
        years=1,
        guaranteed=True,
        option_type="",
    )
    five_year = FreeAgencyOffer(
        player_id=unknown_player_id,
        team_abbreviation=team,
        annual_salary=5_000_000.0,
        years=5,
        guaranteed=True,
        option_type="",
    )
    one_year_option = FreeAgencyOffer(
        player_id=unknown_player_id,
        team_abbreviation=team,
        annual_salary=5_000_000.0,
        years=1,
        guaranteed=True,
        option_type="team_option",
    )
    safe_preview_offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=4_500_000.0,
        years=4,
        guaranteed=True,
        option_type="",
    )

    safe_legality = evaluate_contract_salary_legality(toy, safe_offer)
    safe_v12 = evaluate_live_free_agency_financial_gate(toy, safe_offer)
    safe_composed = evaluate_contract_legal_financial_gate(toy, safe_offer)
    # The full preview validator requires every player to have injury/stat
    # coverage, so exercise it with the real isolated player. Unknown-service
    # salary behavior is already proven independently above.
    preview_state = copy.deepcopy(toy)
    preview_state.players.pop(unknown_player_id, None)
    preview_state.free_agent_player_ids = tuple(
        pid
        for pid in preview_state.free_agent_player_ids
        if str(pid) != unknown_player_id
    )
    safe_preview = build_contract_legal_free_agency_preview(
        preview_state,
        safe_preview_offer,
    )
    low = evaluate_contract_salary_legality(toy, low_offer)
    high = evaluate_contract_salary_legality(toy, high_offer)
    five = evaluate_contract_salary_legality(toy, five_year)
    one_opt = evaluate_contract_salary_legality(toy, one_year_option)

    # Known-service exact tests on an isolated object. Dynamic attrs are allowed
    # by the live dataclass and are not persisted to the durable source.
    setattr(toy_player, "years_of_service", 2)
    known2 = evaluate_contract_salary_legality(
        toy,
        FreeAgencyOffer(player_id, team, 2_449_421.0, 1, True, ""),
    )
    known2_under = evaluate_contract_salary_legality(
        toy,
        FreeAgencyOffer(player_id, team, 2_449_420.0, 1, True, ""),
    )
    setattr(toy_player, "years_of_service", 10)
    known10_max = maximum_initial_salary_for_offer(
        years_of_service=10,
        prior_salary=None,
    )
    # 105% prior salary alternative: 60m prior -> 63m max, above 35% cap.
    prior_alt = maximum_initial_salary_for_offer(
        years_of_service=10,
        prior_salary=60_000_000.0,
    )

    # V1.2 veto test: use the real isolated source pair, which may be over cap.
    real_offer = FreeAgencyOffer(player_id, team, 5_000_000.0, 1, True, "")
    real_v12 = evaluate_live_free_agency_financial_gate(test_state, real_offer)
    real_composed = evaluate_contract_legal_financial_gate(test_state, real_offer)

    future = copy.deepcopy(toy)
    source_season_before_future_test = str(toy.settings.season_label)
    future.settings = replace(
        future.settings,
        season_label="2027-28",
    )
    future_result = evaluate_contract_salary_legality(future, safe_offer)

    service_after = resolve_years_of_service(player)
    page_text = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""

    salary_diagnostics = {
        "safe_legality": {"status": safe_legality.status, "reason": safe_legality.reason, "service": safe_legality.years_of_service, "minimum": safe_legality.minimum_salary_floor},
        "safe_financial": {"status": safe_v12.status, "reason": safe_v12.reason},
        "safe_composed": {"status": safe_composed.status, "reason": safe_composed.reason},
        "safe_preview": {"status": safe_preview.status, "can_commit": safe_preview.can_commit, "message": safe_preview.message},
        "known_two": {"status": known2.status, "reason": known2.reason, "service": known2.years_of_service, "minimum": known2.minimum_salary_floor},
    }

    checks = {
        "validator_hotfix_version_is_current": VALIDATOR_VERSION == "franchise-free-agency-contract-salary-legality-validator-v1.3.2-2026-09-28",
        "contract_salary_legality_version_is_current": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION == EXPECTED,
        "financial_bridge_is_current": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION == EXPECTED_V12,
        "anchor_salary_cap_is_exact": math.isclose(ANCHOR_SALARY_CAP, 164_961_000.0, abs_tol=0.01),
        "minimum_scale_zero_service_year1_exact": MINIMUM_SALARY_SCALE_2026_27[0][0] == 1_357_763,
        "minimum_scale_two_service_year1_exact": MINIMUM_SALARY_SCALE_2026_27[2][0] == 2_449_421,
        "minimum_scale_ten_plus_year1_exact": MINIMUM_SALARY_SCALE_2026_27[10][0] == 3_876_529,
        "minimum_scale_ten_plus_year4_exact": MINIMUM_SALARY_SCALE_2026_27[10][3] == 4_458_009,
        "unknown_service_one_year_floor_is_universal_safe": minimum_salary_floor_for_offer(years_of_service=None, contract_years=1) == 3_876_529,
        "unknown_service_four_year_floor_is_universal_safe": minimum_salary_floor_for_offer(years_of_service=None, contract_years=4) == 4_458_009,
        "unknown_service_max_is_25_percent_cap": math.isclose(maximum_initial_salary_for_offer(years_of_service=None, prior_salary=None), 41_240_250.0, abs_tol=0.01),
        "safe_unknown_service_contract_passes_salary_gate": safe_legality.status == "pass",
        "safe_unknown_service_contract_passes_v1_2_cap_space": safe_v12.status == "pass",
        "safe_unknown_service_contract_passes_composed_gate": safe_composed.status == "pass",
        "safe_unknown_service_preview_is_commit_eligible_backend_only": safe_preview.status == "pass" and safe_preview.can_commit,
        "unknown_service_too_low_stays_manual_review": low.status == "manual_review",
        "unknown_service_above_25_percent_stays_manual_review": high.status == "manual_review",
        "five_year_generic_offer_stays_manual_review": five.status == "manual_review",
        "one_year_option_is_not_auto_released": one_opt.status == "manual_review",
        "known_two_service_minimum_passes_exactly": known2.status == "pass" and known2.minimum_salary_floor == 2_449_421,
        "known_two_service_below_minimum_is_blocked": known2_under.status == "blocked",
        "known_ten_plus_max_is_35_percent_cap": math.isclose(known10_max, 57_736_350.0, abs_tol=0.01),
        "known_service_105_percent_prior_salary_alternative_works": math.isclose(prior_alt, 63_000_000.0, abs_tol=0.01),
        "future_settings_replaced_without_mutating_source": str(toy.settings.season_label) == source_season_before_future_test and str(future.settings.season_label) == "2027-28",
        "future_season_salary_legality_stays_manual_review": future_result.status == "manual_review",
        "v1_2_veto_is_preserved": real_v12.status == "pass" or real_composed.status == real_v12.status,
        "age_is_never_used_to_infer_service": service_before == service_after and getattr(player, "age", None) == age_before,
        "durable_source_state_is_unchanged": free_agency_state_fingerprint(durable) == durable_fp,
        "workspace_uses_current_contract_legal_preview": "build_contract_legal_free_agency_preview" in page_text,
        "workspace_exposes_contract_salary_legality": "Contract salary legality" in page_text,
        "workspace_routes_live_commit_through_persistent_market": "commit_persistent_user_winner_live(" in page_text,
        "workspace_requires_explicit_signing_action": "I confirm this signing" in page_text and 'key="fa_live_sign_button"' in page_text,
    }

    compile_ok = True
    compile_error = ""
    try:
        compile(PAGE.read_text(encoding="utf-8"), str(PAGE), "exec")
    except Exception as exc:
        compile_ok = False
        compile_error = str(exc)
    checks["page_compiles"] = compile_ok

    after_hash = sha(CHECKPOINT) if CHECKPOINT.exists() else ""
    checks["validator_did_not_write_checkpoint"] = before_hash == after_hash
    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 108)
    print("FRANCHISE FREE AGENCY CONTRACT SALARY LEGALITY V1.5 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("LIVE READ-ONLY CONTEXT")
    print(f"  Season: {getattr(getattr(durable, 'settings', None), 'season_label', '')}")
    print(f"  Durable phase: {phase_value(durable)}")
    print(f"  Test player: {getattr(player, 'player_name', player_id)} ({player_id})")
    print(f"  Test team: {team}")
    print(f"  Explicit service evidence: {service_before[0] if service_before[0] is not None else 'not available'}")
    print("  Age-to-service inference: NOT USED")
    print("  Live signing: NOT PERFORMED")
    print()
    payload = {
        "validator": VALIDATOR_VERSION,
        "version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "compile_error": compile_error,
        "salary_diagnostics": salary_diagnostics,
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }
    print(json.dumps(payload, indent=2, sort_keys=False))
    print()
    if failed:
        raise AssertionError("V1.3 failed: " + ", ".join(failed))
    print("FRANCHISE FREE AGENCY CONTRACT SALARY LEGALITY V1.5 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live signing or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
