from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import franchise_free_agency_cpu_minimum_exception_targeting_v1 as targeting
from franchise_free_agency_cpu_ai_audit_v1 import build_free_agency_cpu_ai_audit
from franchise_free_agency_cpu_offer_generation_v1 import generation_contract_report

VALIDATOR_VERSION = "franchise-free-agency-cpu-minimum-exception-targeting-validator-v1-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fixture_result(*, overall: float, age: float, salary: float, market: float, interest: float, threshold: float, status: str, fit: float, role: float, direction: str, requested_years: int):
    player = SimpleNamespace(player_id="P1", overall_rating=overall, age=age)
    state = SimpleNamespace(players={"P1": player})
    offer = SimpleNamespace(player_id="P1", annual_salary=salary)
    preview = SimpleNamespace(offer=offer, source_fingerprint="fixture-preview")
    fake_decision = SimpleNamespace(
        status=status,
        utility_score=interest,
        acceptance_threshold=threshold,
        market_salary_reference=market,
        role_score=role,
        winning_score=90.0 if "championship" in direction.lower() else 60.0,
        security_score=74.0,
        career_fit_score=80.0,
    )
    original = targeting.evaluate_free_agent_offer_decision
    targeting.evaluate_free_agent_offer_decision = lambda _state, _preview: fake_decision
    try:
        result = targeting.evaluate_minimum_exception_targeting(
            state,
            preview,
            target_fit_score=fit,
            team_direction=direction,
            strategic_requested_years=requested_years,
        )
    finally:
        targeting.evaluate_free_agent_offer_decision = original
    return result


def _csv(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next(name for name in archive.namelist() if name.endswith("/" + suffix))
    return list(csv.DictReader(archive.read(name).decode("utf-8-sig").splitlines()))


def main() -> int:
    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH

    checkpoint = Path(DEFAULT_CHECKPOINT_PATH)
    before = sha256(checkpoint)
    checks: dict[str, bool] = {}

    print("=" * 118, flush=True)
    print("CPU FREE AGENCY MINIMUM-EXCEPTION TARGETING INTELLIGENCE V1 VALIDATION", flush=True)
    print("=" * 118, flush=True)
    print("[1/5] Validating deterministic targeting policy and protected boundaries...", flush=True)

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["targeting_version_is_current"] = targeting.CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION == "franchise-free-agency-cpu-minimum-exception-targeting-v1-2026-08-14"
    contract = targeting.targeting_contract_report()
    checks["targeting_changes_no_legality"] = contract.get("changes_legality") is False
    checks["targeting_has_no_autonomous_commit"] = contract.get("autonomous_commit_enabled") is False
    checks["interest_is_not_probability"] = contract.get("interest_is_probability") is False
    generator_contract = generation_contract_report()
    checks["offer_generator_exposes_targeting_version"] = generator_contract.get("minimum_exception_targeting_version") == targeting.CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION
    checks["pure_cap_remains_first_choice"] = bool(generator_contract.get("pure_cap_space_remains_first_choice"))

    print("[2/5] Testing accepted, near-market, premium-mismatch and hopeless minimum bids...", flush=True)
    accepted = _fixture_result(overall=72, age=24, salary=2_200_000, market=2_100_000, interest=60, threshold=57, status="accept", fit=55, role=60, direction="Retool", requested_years=2)
    near_market = _fixture_result(overall=72, age=23, salary=2_200_000, market=2_100_000, interest=52, threshold=57, status="decline", fit=40, role=40, direction="Retool", requested_years=2)
    premium = _fixture_result(overall=87, age=23, salary=2_600_000, market=30_000_000, interest=52, threshold=58, status="decline", fit=95, role=100, direction="Contend", requested_years=4)
    hopeless = _fixture_result(overall=76, age=26, salary=2_200_000, market=5_000_000, interest=30, threshold=57, status="decline", fit=80, role=90, direction="Develop", requested_years=3)
    checks["accepted_exact_minimum_is_preserved"] = accepted.allowed and accepted.reason_code == "player_accepts_exact_minimum"
    checks["credible_near_market_minimum_can_survive"] = near_market.allowed and near_market.reason_code == "credible_minimum_pitch"
    checks["premium_token_minimum_is_filtered"] = (not premium.allowed) and premium.reason_code == "premium_player_market_mismatch"
    checks["hopeless_interest_gap_is_filtered"] = (not hopeless.allowed) and hopeless.reason_code == "interest_far_below_acceptance"
    checks["targeting_score_is_bounded"] = all(0.0 <= row.credibility_score <= 100.0 for row in (accepted, near_market, premium, hopeless))
    repeat = _fixture_result(overall=87, age=23, salary=2_600_000, market=30_000_000, interest=52, threshold=58, status="decline", fit=95, role=100, direction="Contend", requested_years=4)
    checks["same_inputs_are_exactly_deterministic"] = premium == repeat

    print("[3/5] Building a full isolated-offseason V1.1 CPU AI audit through the patched offer generator...", flush=True)
    with tempfile.TemporaryDirectory(prefix="fa_mse_targeting_v1_") as tmp:
        result = build_free_agency_cpu_ai_audit(output_dir=tmp, max_targets_per_team=5, progress_callback=lambda msg: print("      " + msg, flush=True))
        checks["integration_audit_strict_pass"] = bool(result.strict_pass) and not result.failed_checks
        with zipfile.ZipFile(result.output_zip, "r") as archive:
            offers = _csv(archive, "cpu_free_agency_offers.csv")
            quality = _csv(archive, "cpu_free_agency_offer_quality.csv")
            skipped = _csv(archive, "cpu_free_agency_skipped_bids.csv")
            behavior = _csv(archive, "behavioral_checks.csv")
            watch = _csv(archive, "watch_metrics.csv")
            summary_name = next(name for name in archive.namelist() if name.endswith("/audit_summary.json"))
            summary = json.loads(archive.read(summary_name).decode("utf-8"))

    print("[4/5] Verifying live audit targeting metadata, deterministic interest reuse, and replacement scanning...", flush=True)
    mse = [r for r in quality if r.get("financial_route") == "minimum_salary_exception"]
    non_mse = [r for r in quality if r.get("financial_route") != "minimum_salary_exception"]
    targeting_skips = [r for r in skipped if str(r.get("reason", "")).startswith("minimum_exception_targeting:")]
    checks["all_submitted_mse_bids_are_explicitly_allowed"] = all(r.get("minimum_targeting_status") == "allow" for r in mse)
    checks["all_submitted_mse_bids_have_reason_and_score"] = all(r.get("minimum_targeting_reason_code") and r.get("minimum_targeting_score") not in {None, ""} for r in mse)
    checks["non_mse_routes_remain_outside_targeting_gate"] = all(r.get("minimum_targeting_status") in {"", "not_applicable"} for r in non_mse)
    checks["targeting_interest_reuses_player_decision_exactly"] = all(abs(float(r["minimum_targeting_interest"]) - float(r["interest_score"])) <= 0.002 for r in mse)
    checks["targeting_gap_reuses_player_decision_exactly"] = all(abs(float(r["minimum_targeting_gap"]) - float(r["gap_to_acceptance"])) <= 0.002 for r in mse)
    checks["audit_summary_records_targeting_version"] = summary.get("cpu_minimum_exception_targeting_version") == targeting.CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION
    behavior_map = {r.get("check_id"): r.get("status") for r in behavior}
    for check_id in (
        "minimum_exception_targeting_metadata_is_complete",
        "minimum_exception_targeting_does_not_relabel_other_routes",
        "minimum_exception_targeting_interest_matches_player_decision",
        "minimum_exception_targeting_gap_matches_player_decision",
    ):
        checks[f"audit_{check_id}"] = behavior_map.get(check_id) == "PASS"
    watch_names = {r.get("metric") for r in watch}
    checks["audit_exports_targeting_watch_metrics"] = {
        "minimum_exception_targeting_generated_count",
        "minimum_exception_targeting_filtered_count",
        "minimum_exception_targeting_filter_reason_distribution",
        "minimum_exception_targeting_average_credibility",
    }.issubset(watch_names)

    print("[5/5] Verifying canonical checkpoint safety...", flush=True)
    after = sha256(checkpoint)
    checks["validator_did_not_write_checkpoint"] = before == after

    for key, passed in checks.items():
        print(f"  {key}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("LIVE TARGETING CONTEXT", flush=True)
    print(f"  Generated legal CPU bids: {len(offers)}", flush=True)
    print(f"  Submitted MSE bids after credibility gate: {len(mse)}", flush=True)
    print(f"  Filtered MSE targets: {len(targeting_skips)}", flush=True)
    if mse:
        competitive = sum(r.get("player_decision_status") in {"accept", "counter"} for r in mse)
        print(f"  Submitted MSE competitive share: {100.0 * competitive / len(mse):.2f}%", flush=True)
    print(f"  Checkpoint hash unchanged: {before == after}", flush=True)

    failed = [key for key, passed in checks.items() if not passed]
    payload = {
        "validator": VALIDATOR_VERSION,
        "targeting_version": targeting.CPU_FREE_AGENCY_MINIMUM_EXCEPTION_TARGETING_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before,
        "checkpoint_hash_after": after,
        "live": {
            "generated_offers": len(offers),
            "submitted_mse_offers": len(mse),
            "filtered_mse_targets": len(targeting_skips),
        },
        "passed": not failed,
    }
    print("")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("")
    if failed:
        print("CPU FREE AGENCY MINIMUM-EXCEPTION TARGETING INTELLIGENCE V1 VALIDATION FAILED")
        return 1
    print("CPU FREE AGENCY MINIMUM-EXCEPTION TARGETING INTELLIGENCE V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no signing, roster mutation, negotiation advance, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
