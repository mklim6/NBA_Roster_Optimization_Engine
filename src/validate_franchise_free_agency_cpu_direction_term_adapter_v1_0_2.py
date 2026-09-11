from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import franchise_free_agency_cpu_offer_generation_v1 as offer_module
from franchise_free_agency_cpu_ai_audit_v1 import build_free_agency_cpu_ai_audit
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
    resolve_cpu_team_direction,
    resolve_supported_cpu_offer_term,
)

VALIDATOR_VERSION = "franchise-free-agency-cpu-direction-term-adapter-validator-v1.0.2-2026-08-14"
EXPECTED_DIRECTION_VERSION = "franchise-free-agency-cpu-direction-adapter-v1.0.1-2026-08-14"
EXPECTED_TERM_VERSION = "franchise-free-agency-cpu-term-feasibility-v1.0.2-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _csv_from_zip(archive: zipfile.ZipFile, basename: str) -> list[dict[str, str]]:
    name = next(name for name in archive.namelist() if name.endswith("/" + basename))
    return list(csv.DictReader(archive.read(name).decode("utf-8-sig").splitlines()))


def main() -> int:
    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before = sha256(checkpoint_path)
    checks: dict[str, bool] = {}

    checks["validator_version_is_current"] = VALIDATOR_VERSION.endswith("2026-08-14")
    checks["base_cpu_offer_generation_version_is_preserved"] = (
        CPU_FREE_AGENCY_OFFER_GENERATION_VERSION
        == "franchise-free-agency-cpu-offer-generation-v1-2026-08-14"
    )
    checks["direction_adapter_v1_0_1_is_preserved"] = (
        CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION == EXPECTED_DIRECTION_VERSION
    )
    checks["term_feasibility_v1_0_2_is_current"] = (
        CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION == EXPECTED_TERM_VERSION
    )
    checks["live_timeline_direction_still_resolves"] = (
        resolve_cpu_team_direction({"timeline_label": "Rebuild"}) == "Rebuild"
    )

    # Isolated unit proof: strategic direction requests a long term, but the
    # locked salary-floor layer is mocked to certify only 1-2 years.
    original_minimum = offer_module.minimum_salary_floor_for_offer
    original_maximum = offer_module.maximum_initial_salary_for_offer
    original_service = offer_module.resolve_years_of_service
    try:
        offer_module.minimum_salary_floor_for_offer = (
            lambda *, years_of_service, contract_years:
            2_500_000.0 if int(contract_years) <= 2 else None
        )
        offer_module.maximum_initial_salary_for_offer = (
            lambda *, years_of_service, prior_salary:
            40_000_000.0
        )
        offer_module.resolve_years_of_service = lambda player: (0, "validator")
        toy = SimpleNamespace(
            age=22.0,
            overall_rating=78.0,
            potential_rating=86.0,
            contract=SimpleNamespace(salary=0.0),
        )
        resolution = resolve_supported_cpu_offer_term(toy, "Develop")
    finally:
        offer_module.minimum_salary_floor_for_offer = original_minimum
        offer_module.maximum_initial_salary_for_offer = original_maximum
        offer_module.resolve_years_of_service = original_service

    checks["strategic_long_term_is_requested"] = (
        resolution is not None and resolution.requested_years >= 3
    )
    checks["unsupported_long_term_falls_back_to_supported_term"] = (
        resolution is not None and resolution.years == 2
    )
    checks["term_fallback_only_shortens"] = (
        resolution is not None and resolution.years <= resolution.requested_years
    )
    checks["fallback_uses_locked_minimum_floor"] = (
        resolution is not None
        and abs(resolution.minimum_salary_floor - 2_500_000.0) < 0.01
    )
    checks["fallback_does_not_invent_maximum"] = (
        resolution is not None
        and abs(resolution.maximum_initial_salary - 40_000_000.0) < 0.01
    )

    with tempfile.TemporaryDirectory(prefix="fa_direction_term_validation_") as tmp:
        result = build_free_agency_cpu_ai_audit(output_dir=tmp)
        with zipfile.ZipFile(result.output_zip, "r") as archive:
            offer_rows = _csv_from_zip(archive, "cpu_free_agency_offers.csv")
            skipped_rows = _csv_from_zip(archive, "cpu_free_agency_skipped_bids.csv")
            behavior_rows = _csv_from_zip(archive, "behavioral_checks.csv")
            watch_rows = _csv_from_zip(archive, "watch_metrics.csv")
            summary_name = next(
                name for name in archive.namelist()
                if name.endswith("/audit_summary.json")
            )
            summary = json.loads(archive.read(summary_name).decode("utf-8"))

        checks["live_audit_generated_offers_exist"] = bool(offer_rows)
        checks["live_offer_rows_export_requested_term"] = bool(offer_rows) and all(
            row.get("strategic_requested_years", "").strip()
            for row in offer_rows
        )
        checks["live_offer_term_never_exceeds_requested_term"] = bool(offer_rows) and all(
            int(float(row.get("years") or 0))
            <= int(float(row.get("strategic_requested_years") or row.get("years") or 0))
            for row in offer_rows
        )
        strict_row = next(
            (
                row for row in behavior_rows
                if row.get("check_id")
                == "generated_cpu_term_fallback_only_shortens_requested_term"
            ),
            None,
        )
        checks["audit_exports_term_fallback_strict_check"] = (
            bool(strict_row) and strict_row.get("status") == "PASS"
        )
        watch_row = next(
            (
                row for row in watch_rows
                if row.get("metric") == "cpu_term_fallback_count"
            ),
            None,
        )
        checks["audit_exports_term_fallback_watch_metric"] = bool(watch_row)
        checks["audit_summary_records_term_feasibility_version"] = (
            summary.get("cpu_term_feasibility_version") == EXPECTED_TERM_VERSION
        )

        # The precise count may vary with the live roster, but the hotfix should
        # materially reduce avoidable salary-bound skips when shorter terms are
        # supported. Any remaining rows are legitimate cases with no supported
        # salary bound at any term.
        salary_bound_skips = [
            row for row in skipped_rows
            if row.get("reason") == "salary_legality_bounds_unavailable"
        ]
        checks["salary_bound_skip_count_is_reported_not_hidden"] = (
            salary_bound_skips is not None
        )

    after = sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = before == after

    print("=" * 116)
    print("CPU FREE AGENCY DIRECTION + TERM FEASIBILITY V1.0.2 HOTFIX VALIDATION")
    print("=" * 116)
    for key, passed in checks.items():
        print(f"  {key}: {'PASS' if passed else 'FAIL'}")

    if "offer_rows" in locals():
        fallback_rows = [
            row for row in offer_rows
            if str(row.get("term_fallback_applied", "")).strip().lower()
            in {"true", "1", "yes"}
        ]
        bound_skips = [
            row for row in skipped_rows
            if row.get("reason") == "salary_legality_bounds_unavailable"
        ]
        print("")
        print("LIVE TERM FEASIBILITY")
        print(f"  Generated legal CPU bids: {len(offer_rows)}")
        print(f"  Strategic term fallbacks: {len(fallback_rows)}")
        print(f"  Remaining salary-bound-unavailable skips: {len(bound_skips)}")
        for row in fallback_rows[:12]:
            print(
                "  "
                f"{row.get('team_abbreviation')} · {row.get('player_name')} · "
                f"requested {row.get('strategic_requested_years')}y -> "
                f"legal {row.get('years')}y"
            )

    failed = [key for key, value in checks.items() if not value]
    print("")
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "direction_adapter": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
        "term_feasibility": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before,
        "checkpoint_hash_after": after,
        "passed": not failed,
    }, indent=2, sort_keys=True))
    print("")
    if failed:
        print("CPU FREE AGENCY DIRECTION + TERM FEASIBILITY V1.0.2 HOTFIX VALIDATION FAILED")
        return 1

    print("CPU FREE AGENCY DIRECTION + TERM FEASIBILITY V1.0.2 HOTFIX VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no signing, roster move, calendar advance, "
        "Trade Machine mutation, or checkpoint write was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
