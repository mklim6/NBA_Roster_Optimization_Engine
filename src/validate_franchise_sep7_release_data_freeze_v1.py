from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
APP_DATA = ROOT / "app_data"
DATA_REFERENCE = ROOT / "data" / "reference"
OUTPUTS = ROOT / "outputs"

FREEZE_MANIFEST_PATH = APP_DATA / "nba_sep7_release_freeze_v1.json"
REPORT_PATH = OUTPUTS / "franchise_sep7_release_data_freeze_v1_validation.json"
VALIDATOR_VERSION = "franchise-sep7-release-data-freeze-validator-v1.0-2026-09-09"


class ReleaseDataFreezeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReleaseDataFreezeError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseDataFreezeError(f"Expected JSON object at {path}.")
    return payload


def _load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception as exc:
        raise ReleaseDataFreezeError(f"Could not read CSV {path}: {exc}") from exc


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _clean(value).lower() in {"1", "true", "yes", "y"}


def _checkpoint_family_hashes() -> dict[str, str | None]:
    runtime = OUTPUTS / "runtime"
    candidates = [
        runtime / "franchise_mode_checkpoint_v1.pkl.gz",
        runtime / "franchise_mode_checkpoint_v1.backup.pkl.gz",
        runtime / "franchise_mode_checkpoint_v1.pkl.gz.backup",
    ]
    return {
        str(path.relative_to(ROOT)): (_sha256(path) if path.exists() else None)
        for path in candidates
    }


def _record(
    checks: dict[str, bool],
    details: dict[str, Any],
    name: str,
    passed: bool,
    detail: Any = None,
) -> None:
    checks[name] = bool(passed)
    if detail is not None:
        details[name] = detail


def main() -> int:
    checkpoint_before = _checkpoint_family_hashes()
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    try:
        freeze = _load_json(FREEZE_MANIFEST_PATH)
        expected = freeze.get("expected_live_start", {})
        frozen_files = freeze.get("frozen_files", [])

        _record(
            checks,
            details,
            "freeze_manifest_is_immutable_sep7_release",
            freeze.get("immutable") is True
            and freeze.get("cutoff_date") == "2026-09-07"
            and freeze.get("release_id") == "live_2026_09_07_release_candidate_v1",
            {
                "version": freeze.get("version"),
                "release_id": freeze.get("release_id"),
                "cutoff_date": freeze.get("cutoff_date"),
            },
        )

        hash_results: dict[str, dict[str, Any]] = {}
        all_hashes_match = True
        for row in frozen_files:
            rel = _clean(row.get("path"))
            expected_hash = _clean(row.get("sha256")).lower()
            path = ROOT / rel
            actual_hash = _sha256(path) if path.exists() else None
            matched = bool(actual_hash and actual_hash.lower() == expected_hash)
            all_hashes_match = all_hashes_match and matched
            hash_results[rel] = {
                "exists": path.exists(),
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "matched": matched,
            }

        _record(
            checks,
            details,
            "all_frozen_file_hashes_match",
            len(frozen_files) == 5 and all_hashes_match,
            hash_results,
        )

        current_manifest = _load_json(APP_DATA / "nba_current_reference_manifest.json")
        overlay = _load_json(APP_DATA / "nba_current_reference_overlay_2026_09_07.json")
        live_config = _load_json(APP_DATA / "nba_live_franchise_start_2026_09_07.json")
        overlay_rows = _load_csv(DATA_REFERENCE / "nba_current_reference_overlay_2026_09_07.csv")
        movement_rows = _load_csv(
            DATA_REFERENCE / "nba_player_movement_delta_2026_08_04_to_2026_09_07.csv"
        )

        overlay_hash = _sha256(APP_DATA / "nba_current_reference_overlay_2026_09_07.json")
        _record(
            checks,
            details,
            "current_reference_manifest_points_exactly_to_frozen_overlay",
            current_manifest.get("active_cutoff_date") == "2026-09-07"
            and current_manifest.get("active_overlay") == "nba_current_reference_overlay_2026_09_07.json"
            and int(current_manifest.get("active_overlay_player_count", -1)) == 49
            and _clean(current_manifest.get("active_overlay_sha256")).lower() == overlay_hash.lower()
            and current_manifest.get("reference_layer_only") is True
            and current_manifest.get("simulation_branch_eligible") is False,
        )

        players = overlay.get("players", [])
        player_ids = [_clean(row.get("player_id")) for row in players if isinstance(row, Mapping)]
        latest_dates = [_clean(row.get("latest_event_date")) for row in players if isinstance(row, Mapping)]
        _record(
            checks,
            details,
            "overlay_semantics_are_frozen",
            overlay.get("version") == "nba-current-reference-snapshot-v2-2026-09-07"
            and overlay.get("reference_window_end_inclusive") == "2026-09-07"
            and int(overlay.get("player_count", -1)) == 49
            and len(players) == 49
            and len(player_ids) == len(set(player_ids)) == 49
            and all(date <= "2026-09-07" for date in latest_dates if date)
            and overlay.get("reference_layer_only") is True
            and overlay.get("simulation_branch_eligible") is False,
            {
                "player_count": len(players),
                "feed_row_count": overlay.get("feed_row_count"),
                "supplemental_row_count": overlay.get("supplemental_row_count"),
                "source_sha256": overlay.get("source_sha256"),
            },
        )

        csv_ids = [_clean(row.get("player_id")) for row in overlay_rows]
        json_by_id = {
            _clean(row.get("player_id")): row
            for row in players
            if isinstance(row, Mapping)
        }
        csv_by_id = {_clean(row.get("player_id")): row for row in overlay_rows}
        semantic_fields = [
            "current_reference_team",
            "current_reference_status",
            "roster_reference_action",
            "contract_reference_action",
        ]
        csv_json_match = (
            len(overlay_rows) == 49
            and len(csv_by_id) == 49
            and set(csv_by_id) == set(json_by_id)
            and all(
                _clean(csv_by_id[player_id].get(field))
                == _clean(json_by_id[player_id].get(field))
                for player_id in json_by_id
                for field in semantic_fields
            )
        )
        _record(
            checks,
            details,
            "overlay_json_and_csv_reconcile",
            csv_json_match,
            {"csv_rows": len(overlay_rows), "unique_player_ids": len(set(csv_ids))},
        )

        supplemental_movement_count = sum(
            1 for row in movement_rows if _truthy(row.get("supplemental_event"))
        )
        official_movement_count = len(movement_rows) - supplemental_movement_count
        _record(
            checks,
            details,
            "movement_delta_is_complete_through_cutoff",
            len(movement_rows) == 62
            and supplemental_movement_count == 14
            and official_movement_count == 48
            and all(
                _clean(row.get("transaction_date")) <= "2026-09-07"
                for row in movement_rows
                if _clean(row.get("transaction_date"))
            ),
            {
                "rows": len(movement_rows),
                "official_rows": official_movement_count,
                "supplemental_rows": supplemental_movement_count,
            },
        )

        missing_profiles = live_config.get("missing_player_profiles", [])
        stat_profiles = live_config.get("statistical_profile_overrides", {})
        rating_statuses = Counter(
            _clean(row.get("overall_rating_evidence_status"))
            for row in missing_profiles
            if isinstance(row, Mapping)
        )
        source_counts = Counter(
            _clean(row.get("source_level"))
            for row in stat_profiles.values()
            if isinstance(row, Mapping)
        )

        _record(
            checks,
            details,
            "live_start_profile_evidence_is_frozen",
            live_config.get("version") == expected.get("config_version")
            and live_config.get("cutoff_date") == "2026-09-07"
            and live_config.get("source_overlay") == "nba_current_reference_overlay_2026_09_07.json"
            and len(missing_profiles) == int(expected.get("materialized_player_count", -1))
            and len(stat_profiles) == int(expected.get("materialized_player_count", -1))
            and rating_statuses["released_external_game_rating"]
            == int(expected.get("released_external_rating_count", -1))
            and rating_statuses[
                "source_informed_empirical_proxy_no_released_game_rating"
            ]
            == int(expected.get("empirical_proxy_rating_count", -1))
            and dict(source_counts) == expected.get("profile_source_counts"),
            {
                "rating_status_counts": dict(rating_statuses),
                "profile_source_counts": dict(source_counts),
            },
        )

        contracts = live_config.get("current_contract_overrides", {})
        draft_assets = live_config.get("draft_asset_overrides", [])
        international_rights = live_config.get("international_draft_rights", [])
        _record(
            checks,
            details,
            "live_start_transaction_data_is_frozen",
            len(contracts) == int(expected.get("contract_override_count", -1))
            and len(draft_assets) == int(expected.get("draft_asset_override_count", -1))
            and len(international_rights)
            == int(expected.get("international_rights_transfer_count", -1)),
            {
                "contract_overrides": len(contracts),
                "draft_asset_overrides": len(draft_assets),
                "international_rights": len(international_rights),
            },
        )

        contract_semantics_ok = all(
            isinstance(row, Mapping)
            and row.get("salary") is not None
            and row.get("cap_hit") is not None
            and row.get("years_remaining") is not None
            and _clean(row.get("evidence_status"))
            for row in contracts.values()
        )
        _record(
            checks,
            details,
            "all_frozen_contract_overrides_retain_financial_semantics",
            contract_semantics_ok,
        )

        _record(
            checks,
            details,
            "freeze_records_expected_live_start_fingerprint",
            len(_clean(expected.get("live_start_fingerprint"))) == 64
            and _clean(expected.get("live_start_fingerprint"))
            == "748bfcd58d6cecf8abab666b34b5d44d176d2e3456baef9a0fff6e033e08bd7b",
            {"fingerprint": expected.get("live_start_fingerprint")},
        )

        checkpoint_after = _checkpoint_family_hashes()
        _record(
            checks,
            details,
            "freeze_validation_does_not_modify_checkpoint_family",
            checkpoint_before == checkpoint_after,
            {"before": checkpoint_before, "after": checkpoint_after},
        )

    except Exception as exc:
        checks["validator_completed_without_exception"] = False
        details["validator_exception"] = f"{type(exc).__name__}: {exc}"

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VALIDATOR_VERSION,
        "freeze_manifest": str(FREEZE_MANIFEST_PATH.relative_to(ROOT)),
        "checks": checks,
        "details": details,
        "failed_checks": failed,
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

    if failed:
        print("\nFRANCHISE SEP. 7 RELEASE DATA FREEZE V1 FAILED")
        return 1

    print("\nFRANCHISE SEP. 7 RELEASE DATA FREEZE V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
