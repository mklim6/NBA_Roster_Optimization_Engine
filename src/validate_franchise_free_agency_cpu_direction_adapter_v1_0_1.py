from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from franchise_free_agency_cpu_ai_audit_v1 import build_free_agency_cpu_ai_audit
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    _direction_multiplier,
    resolve_cpu_team_direction,
)

VALIDATOR_VERSION = "franchise-free-agency-cpu-direction-adapter-validator-v1.0.1-2026-08-14"
EXPECTED_ADAPTER_VERSION = "franchise-free-agency-cpu-direction-adapter-v1.0.1-2026-08-14"


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
    checks["base_cpu_offer_generation_version_is_preserved"] = CPU_FREE_AGENCY_OFFER_GENERATION_VERSION == "franchise-free-agency-cpu-offer-generation-v1-2026-08-14"
    checks["direction_adapter_hotfix_version_is_current"] = CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION == EXPECTED_ADAPTER_VERSION

    live_style = {
        "championship": {"timeline_label": "Championship Push", "behavior_label": "All-in contender"},
        "contend": {"timeline_label": "Contend", "behavior_label": "Balanced contender"},
        "retool": {"timeline_label": "Retool", "behavior_label": "Flexible retool"},
        "develop": {"timeline_label": "Develop", "behavior_label": "Development first"},
        "rebuild": {"timeline_label": "Rebuild", "behavior_label": "Asset accumulation"},
    }
    resolved = {key: resolve_cpu_team_direction(value) for key, value in live_style.items()}
    checks["timeline_label_championship_resolves"] = resolved["championship"] == "Championship Push"
    checks["timeline_label_contend_resolves"] = resolved["contend"] == "Contend"
    checks["timeline_label_retool_resolves"] = resolved["retool"] == "Retool"
    checks["timeline_label_develop_resolves"] = resolved["develop"] == "Develop"
    checks["timeline_label_rebuild_resolves"] = resolved["rebuild"] == "Rebuild"
    checks["timeline_label_has_priority_over_legacy_direction"] = resolve_cpu_team_direction({"timeline_label": "Rebuild", "direction": "Championship Push"}) == "Rebuild"
    checks["legacy_direction_remains_supported"] = resolve_cpu_team_direction({"direction": "Contend"}) == "Contend"
    checks["behavior_label_fallback_remains_supported"] = resolve_cpu_team_direction({"behavior_label": "Development first"}) == "Develop"
    checks["championship_aggression_exceeds_rebuild"] = _direction_multiplier("Championship Push") > _direction_multiplier("Rebuild")

    with tempfile.TemporaryDirectory(prefix="fa_direction_adapter_validation_") as tmp:
        result = build_free_agency_cpu_ai_audit(output_dir=tmp)
        with zipfile.ZipFile(result.output_zip, "r") as archive:
            team_rows = _csv_from_zip(archive, "cpu_front_office_team_plans.csv")
            offer_rows = _csv_from_zip(archive, "cpu_free_agency_offers.csv")
            behavior_rows = _csv_from_zip(archive, "behavioral_checks.csv")
            summary_name = next(name for name in archive.namelist() if name.endswith("/audit_summary.json"))
            summary = json.loads(archive.read(summary_name).decode("utf-8"))

        plan_direction = {
            row.get("team_abbreviation", "").strip().upper(): row.get("team_direction", "").strip()
            for row in team_rows
            if row.get("team_abbreviation", "").strip()
        }
        checks["audit_team_plan_directions_are_resolved"] = bool(plan_direction) and all(plan_direction.values())
        checks["audit_generated_offers_exist"] = bool(offer_rows)
        checks["generated_offer_direction_matches_live_plan"] = bool(offer_rows) and all(
            row.get("team_direction", "").strip()
            == plan_direction.get(row.get("team_abbreviation", "").strip().upper(), "")
            for row in offer_rows
        )
        checks["live_offer_directions_do_not_all_fall_back_to_balanced"] = bool(offer_rows) and any(
            row.get("team_direction", "").strip() != "Balanced" for row in offer_rows
        )
        hotfix_check = next((row for row in behavior_rows if row.get("check_id") == "cpu_offer_direction_matches_front_office_plan"), None)
        checks["audit_exports_direction_propagation_strict_check"] = bool(hotfix_check) and hotfix_check.get("status") == "PASS"
        checks["audit_summary_records_direction_adapter_version"] = summary.get("cpu_direction_adapter_version") == EXPECTED_ADAPTER_VERSION

    after = sha256(checkpoint_path)
    checks["validator_did_not_write_checkpoint"] = before == after

    print("=" * 112)
    print("CPU FREE AGENCY DIRECTION ADAPTER V1.0.1 HOTFIX VALIDATION")
    print("=" * 112)
    for key, passed in checks.items():
        print(f"  {key}: {'PASS' if passed else 'FAIL'}")
    print("")
    print("LIVE DIRECTION PROPAGATION")
    if 'team_rows' in locals():
        for team in sorted({row.get('team_abbreviation','') for row in offer_rows}):
            if team:
                directions = sorted({row.get('team_direction','') for row in offer_rows if row.get('team_abbreviation') == team})
                print(f"  {team}: plan={plan_direction.get(team, '')} · offers={','.join(directions)}")
    print(f"  Checkpoint hash unchanged: {before == after}")

    failed = [key for key, value in checks.items() if not value]
    print("")
    print(json.dumps({
        "validator": VALIDATOR_VERSION,
        "adapter": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before,
        "checkpoint_hash_after": after,
        "passed": not failed,
    }, indent=2, sort_keys=True))
    print("")
    if failed:
        print("CPU FREE AGENCY DIRECTION ADAPTER V1.0.1 HOTFIX VALIDATION FAILED")
        return 1
    print("CPU FREE AGENCY DIRECTION ADAPTER V1.0.1 HOTFIX VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no signing, roster move, calendar advance, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
