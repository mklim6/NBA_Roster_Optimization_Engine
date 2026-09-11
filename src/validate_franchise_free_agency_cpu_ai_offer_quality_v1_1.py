from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from franchise_free_agency_cpu_ai_audit_v1 import (
    FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION,
    FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION,
    REQUIRED_FILES,
    audit_contract_report,
    build_free_agency_cpu_ai_audit,
)
from franchise_free_agency_interest_meter_v1 import FREE_AGENCY_INTEREST_METER_VERSION

VALIDATOR_VERSION = "franchise-free-agency-cpu-ai-offer-quality-validator-v1.1-minimum-targeting-2026-08-14"

EXPECTED_QUALITY_COLUMNS = {
    "player_id",
    "player_name",
    "team_abbreviation",
    "team_direction",
    "financial_route",
    "annual_salary",
    "years",
    "strategic_requested_years",
    "term_fallback_applied",
    "player_overall",
    "player_age",
    "interest_score",
    "acceptance_threshold",
    "gap_to_acceptance",
    "player_decision_status",
    "market_salary_reference",
    "salary_to_market_pct",
    "salary_score",
    "role_score",
    "winning_score",
    "security_score",
    "career_fit_score",
    "preference_archetype",
    "money_weight",
    "role_weight",
    "winning_weight",
    "security_weight",
    "career_fit_weight",
    "competitive_offer",
    "hopeless_offer_watch",
    "minimum_targeting_status",
    "minimum_targeting_score",
    "minimum_targeting_reason_code",
    "minimum_targeting_interest",
    "minimum_targeting_gap",
    "minimum_targeting_market_ratio",
}

REQUIRED_WATCH_METRICS = {
    "average_player_interest",
    "median_player_interest",
    "competitive_offer_share_pct",
    "noncompetitive_20_plus_below_threshold_share_pct",
    "median_salary_to_market_pct",
    "interest_by_financial_route",
    "interest_by_team_direction",
    "minimum_exception_competitive_share_pct",
    "minimum_exception_accept_share_pct",
    "minimum_exception_hopeless_offer_count",
    "minimum_exception_premium_player_offer_count",
    "premium_player_markets_without_accepted_destination",
    "lower_salary_winner_count",
    "offer_quality_watch_flag_distribution",
    "minimum_exception_targeting_generated_count",
    "minimum_exception_targeting_filtered_count",
    "minimum_exception_targeting_filter_reason_distribution",
    "minimum_exception_targeting_average_credibility",
}

REQUIRED_STRICT_CHECKS = {
    "every_generated_bid_has_offer_quality_evaluation",
    "offer_quality_has_no_evaluation_errors",
    "offer_quality_interest_is_bounded",
    "offer_quality_components_are_bounded",
    "offer_quality_gap_to_acceptance_is_exact",
    "offer_quality_decision_status_is_supported",
    "offer_quality_accept_flag_matches_status",
    "offer_quality_market_reference_is_positive",
    "offer_quality_salary_ratio_is_finite_nonnegative",
    "player_preference_weights_sum_to_one",
    "player_profiles_are_unique_by_player",
    "market_quality_offer_counts_reconcile",
    "offer_quality_same_state_replay_is_exact",
    "quality_flags_are_watch_only",
    "offer_quality_is_not_labeled_as_probability",
    "minimum_exception_targeting_metadata_is_complete",
    "minimum_exception_targeting_does_not_relabel_other_routes",
    "minimum_exception_targeting_interest_matches_player_decision",
    "minimum_exception_targeting_gap_matches_player_decision",
}


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_from_zip(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next(name for name in archive.namelist() if name.endswith("/" + suffix))
    return list(csv.DictReader(archive.read(name).decode("utf-8-sig").splitlines()))


def main() -> int:
    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH

    checkpoint = Path(DEFAULT_CHECKPOINT_PATH)
    before = sha256(checkpoint)
    checks: dict[str, bool] = {}

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["offer_quality_version_is_current"] = FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION == "franchise-free-agency-cpu-ai-audit-offer-quality-v1.1-2026-08-14"
    checks["offer_quality_schema_is_current"] = FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION == "free-agency-cpu-ai-offer-quality-schema-v1.1"
    checks["interest_meter_v1_is_preserved"] = FREE_AGENCY_INTEREST_METER_VERSION == "franchise-free-agency-player-interest-meter-v1-2026-08-14"
    contract = audit_contract_report()
    checks["audit_contract_remains_read_only"] = bool(contract.get("read_only"))
    checks["offer_quality_contract_is_exposed"] = contract.get("offer_quality_version") == FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION

    print("=" * 116, flush=True)
    print("CPU FREE AGENCY AI AUDIT V1.1 · OFFER QUALITY + PLAYER INTEREST VALIDATION", flush=True)
    print("=" * 116, flush=True)
    print("[1/4] Building a full read-only isolated-offseason audit...", flush=True)

    with tempfile.TemporaryDirectory(prefix="fa_cpu_ai_offer_quality_v11_") as tmp:
        result = build_free_agency_cpu_ai_audit(
            output_dir=tmp,
            max_targets_per_team=5,
            progress_callback=lambda msg: print("      " + msg, flush=True),
        )
        zip_path = Path(result.output_zip)
        checks["validation_zip_created"] = zip_path.exists()
        checks["strict_checks_pass"] = bool(result.strict_pass) and not result.failed_checks

        print("[2/4] Inspecting offer-quality, motivation, and market-realism exports...", flush=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            basenames = {Path(name).name for name in archive.namelist()}
            checks["all_required_files_exist"] = all(name in basenames for name in REQUIRED_FILES)
            offer_rows = _csv_from_zip(archive, "cpu_free_agency_offers.csv")
            quality_rows = _csv_from_zip(archive, "cpu_free_agency_offer_quality.csv")
            profile_rows = _csv_from_zip(archive, "cpu_free_agency_player_profiles.csv")
            market_rows = _csv_from_zip(archive, "cpu_free_agency_market_quality.csv")
            flag_rows = _csv_from_zip(archive, "cpu_free_agency_quality_flags.csv")
            watch_rows = _csv_from_zip(archive, "watch_metrics.csv")
            behavior_rows = _csv_from_zip(archive, "behavioral_checks.csv")
            checks["quality_rows_match_generated_offers"] = len(quality_rows) == len(offer_rows) and len(quality_rows) > 0
            checks["player_profiles_are_exported"] = len(profile_rows) > 0
            checks["market_quality_is_exported"] = len(market_rows) > 0
            checks["quality_export_has_expected_columns"] = EXPECTED_QUALITY_COLUMNS.issubset(set(quality_rows[0].keys()) if quality_rows else set())
            checks["interest_is_not_probability_column"] = all("probability" not in key.lower() for key in (quality_rows[0].keys() if quality_rows else []))
            checks["quality_flags_are_watch_only"] = all(row.get("status") == "WATCH" for row in flag_rows)
            metric_names = {row.get("metric") for row in watch_rows}
            checks["required_offer_quality_watch_metrics_exist"] = REQUIRED_WATCH_METRICS.issubset(metric_names)
            behavior_by_id = {row.get("check_id"): row for row in behavior_rows}
            checks["required_offer_quality_strict_checks_exist"] = REQUIRED_STRICT_CHECKS.issubset(behavior_by_id)
            checks["required_offer_quality_strict_checks_pass"] = all(behavior_by_id[key].get("status") == "PASS" for key in REQUIRED_STRICT_CHECKS if key in behavior_by_id)
            summary_name = next(name for name in archive.namelist() if name.endswith("/audit_summary.json"))
            summary = json.loads(archive.read(summary_name).decode("utf-8"))
            checks["summary_records_offer_quality_version"] = summary.get("offer_quality_version") == FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION
            checks["summary_records_interest_meter_version"] = summary.get("interest_meter_version") == FREE_AGENCY_INTEREST_METER_VERSION
            checks["summary_records_quality_fingerprint"] = bool(summary.get("offer_quality_fingerprint"))

            mse = [r for r in quality_rows if r.get("financial_route") == "minimum_salary_exception"]
            competitive = [r for r in quality_rows if r.get("player_decision_status") in {"accept", "counter"}]
            hopeless = [r for r in quality_rows if str(r.get("hopeless_offer_watch", "")).lower() == "true"]
            premium_mse = [r for r in mse if str(r.get("premium_player_watch", "")).lower() == "true"]
            interests = [float(r["interest_score"]) for r in quality_rows if r.get("interest_score") not in {None, ""}]
            avg_interest = sum(interests) / len(interests) if interests else 0.0

    print("[3/4] Verifying protected checkpoint safety...", flush=True)
    after = sha256(checkpoint)
    checks["validator_did_not_write_checkpoint"] = before == after

    print("[4/4] Finalizing validation report...", flush=True)
    for key, passed in checks.items():
        print(f"  {key}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("LIVE OFFER-QUALITY DIAGNOSTIC CONTEXT", flush=True)
    print(f"  Generated legal offers: {len(quality_rows)}", flush=True)
    print(f"  Competitive ACCEPT/COUNTER offers: {len(competitive)}", flush=True)
    print(f"  20+ points below acceptance: {len(hopeless)}", flush=True)
    print(f"  Minimum Salary Exception offers: {len(mse)}", flush=True)
    print(f"  80+ OVR Minimum Salary Exception offers: {len(premium_mse)}", flush=True)
    print(f"  Average deterministic player interest: {avg_interest:.2f}/100", flush=True)
    print(f"  Player profiles: {len(profile_rows)}", flush=True)
    print(f"  Market quality summaries: {len(market_rows)}", flush=True)
    print(f"  WATCH flags: {len(flag_rows)}", flush=True)
    print(f"  Checkpoint hash unchanged: {before == after}", flush=True)

    failed = [key for key, passed in checks.items() if not passed]
    payload = {
        "validator": VALIDATOR_VERSION,
        "offer_quality_version": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_VERSION,
        "offer_quality_schema": FREE_AGENCY_CPU_AI_AUDIT_OFFER_QUALITY_SCHEMA_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before,
        "checkpoint_hash_after": after,
        "diagnostics": {
            "offers": len(quality_rows),
            "competitive_offers": len(competitive),
            "hopeless_offers": len(hopeless),
            "minimum_exception_offers": len(mse),
            "premium_minimum_exception_offers": len(premium_mse),
            "average_interest": round(avg_interest, 3),
            "quality_flags": len(flag_rows),
        },
        "passed": not failed,
    }
    print("")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("")
    if failed:
        print("CPU FREE AGENCY AI AUDIT V1.1 VALIDATION FAILED")
        return 1
    print("CPU FREE AGENCY AI AUDIT V1.1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no signing, negotiation advance, roster mutation, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
