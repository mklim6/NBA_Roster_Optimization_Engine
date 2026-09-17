from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_draft_forfeitures_v1 import DRAFT_PICK_FORFEITURES  # noqa: E402
import simulation_franchise_checkpoint_v1 as checkpoint_api  # noqa: E402


VERSION = "franchise-live-cutoff-audit-v1-2026-09-09"
CUTOFF_DATE = date(2026, 9, 7)
WINDOW_START_EXCLUSIVE = date(2026, 8, 4)

MANIFEST_PATH = ROOT / "app_data" / "nba_current_reference_manifest.json"
OVERLAY_PATH = ROOT / "app_data" / "nba_current_reference_overlay_2026_09_07.json"
CONFIG_PATH = ROOT / "app_data" / "nba_live_franchise_start_2026_09_07.json"
TRANSACTION_PATH = (
    ROOT
    / "data"
    / "reference"
    / "nba_player_movement_delta_2026_08_04_to_2026_09_07.csv"
)
REPORT_PATH = ROOT / "outputs" / "franchise_live_cutoff_audit_v1.json"

EXPECTED_STATUS_COUNTS = {
    "under_contract": 19,
    "free_agent": 12,
    "two_way": 10,
    "exhibit_10": 8,
}
EXPECTED_TWO_WAY_IDS = {
    "1629618",  # Jalen Pickett, LAC
    "1641759",  # Dillon Mitchell, BOS
    "1641761",  # Grant Nelson, BKN
    "1642352",  # Keshad Johnson, MIA
    "1642481",  # Jamarion Sharp, LAC
    "1642951",  # Sean Pedulla, HOU
    "1643552",  # Braden Smith, IND
    "1643572",  # Rafael Castro, HOU
    "1643624",  # Bryce Hopkins, DEN
    "1643738",  # Malik Dia, NOP
}
EXPECTED_EXHIBIT_10_IDS = {
    "1629605",  # Tacko Fall, PHI
    "1631103",  # Malaki Branham, ORL
    "1631120",  # JD Davison, ORL
    "1631207",  # Dalen Terry, GSW
    "1641869",  # Malachi Smith, TOR
    "1642392",  # Jameer Nelson Jr., PHI
    "1643148",  # Saint Thomas, PHI
    "1643727",  # J'Vonne Hadley, MIA
}
EXPECTED_SECONDARY_ACTIVE_EVIDENCE_IDS = {
    "1629605",
    "1631207",
    "1641869",
    "1642392",
}
EXPECTED_DRAFT_ASSET_OWNERS = {
    "FPR_AFD12DB20C9F72A2": "WAS",
    "2031_R1_CLE": "DEN",
    "2032_R2_SAC": "DEN",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _date(value: Any) -> date:
    return date.fromisoformat(str(value or "").strip())


def _is_https(value: Any) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def _source_tier(row: Mapping[str, Any]) -> str:
    host = urlparse(str(row.get("source_url") or "")).netloc.lower()
    if host == "nba.com" or host.endswith(".nba.com"):
        return "nba_or_team_official"
    if host == "basketball-reference.com" or host.endswith(
        ".basketball-reference.com"
    ):
        return "independent_transaction_ledger"
    return "unclassified"


def _csv_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _overlay_matches_latest_ledger_row(
    overlay: Mapping[str, Any], ledger: Mapping[str, Any]
) -> bool:
    pairs = {
        "latest_event_date": "transaction_date",
        "latest_event_type": "transaction_type",
        "latest_description": "transaction_description",
        "transaction_team": "transaction_team",
        "current_reference_team": "current_reference_team",
        "current_reference_status": "current_reference_status",
        "roster_reference_action": "roster_reference_action",
        "contract_reference_action": "contract_reference_action",
        "source_name": "source_name",
        "source_url": "source_url",
        "source_sha256": "source_sha256",
    }
    if any(str(overlay.get(left) or "") != str(ledger.get(right) or "") for left, right in pairs.items()):
        return False
    return (
        bool(overlay.get("current_reference_two_way"))
        == _csv_bool(ledger.get("current_reference_two_way"))
        and bool(overlay.get("supplemental_event"))
        == _csv_bool(ledger.get("supplemental_event"))
    )


def main() -> int:
    checkpoint_path = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH)
    # Resolve the sidecar through the checkpoint API so the default checkpoint
    # uses DEFAULT_BACKUP_PATH while isolated checkpoints retain the
    # ``<name>.backup`` convention.
    backup_path = checkpoint_api.checkpoint_backup_path(checkpoint_path)
    checkpoint_before = _sha256(checkpoint_path)
    backup_before = _sha256(backup_path)

    manifest = _load_json(MANIFEST_PATH)
    overlay_payload = _load_json(OVERLAY_PATH)
    config = _load_json(CONFIG_PATH)
    overlay_rows = list(overlay_payload.get("players") or [])
    overlay_by_id = {
        str(row.get("player_id") or ""): row
        for row in overlay_rows
        if isinstance(row, Mapping)
    }
    with TRANSACTION_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        transaction_rows = list(csv.DictReader(handle))

    latest_ledger_by_id: dict[str, dict[str, str]] = {}
    for row in transaction_rows:
        player_id = str(row.get("player_id") or "").strip()
        if player_id:
            latest_ledger_by_id[player_id] = row

    status_counts = Counter(
        str(row.get("current_reference_status") or "") for row in overlay_rows
    )
    two_way_ids = {
        str(row.get("player_id"))
        for row in overlay_rows
        if row.get("current_reference_status") == "two_way"
    }
    exhibit_10_ids = {
        str(row.get("player_id"))
        for row in overlay_rows
        if row.get("current_reference_status") == "exhibit_10"
    }
    source_tiers = {
        str(row.get("player_id")): _source_tier(row) for row in overlay_rows
    }
    source_tier_counts = Counter(source_tiers.values())
    secondary_active_ids = {
        player_id
        for player_id, tier in source_tiers.items()
        if tier == "independent_transaction_ledger"
    }

    special_contract_rows = [
        row
        for row in overlay_rows
        if row.get("current_reference_status") in {"two_way", "exhibit_10"}
    ]
    explicit_special_descriptions = all(
        (
            row.get("current_reference_status") == "two_way"
            and "two-way" in str(row.get("latest_description") or "").lower()
        )
        or (
            row.get("current_reference_status") == "exhibit_10"
            and "exhibit 10" in str(row.get("latest_description") or "").lower()
        )
        for row in special_contract_rows
    )

    draft_overrides = list(config.get("draft_asset_overrides") or [])
    draft_by_id = {
        str(row.get("asset_id") or ""): row
        for row in draft_overrides
        if isinstance(row, Mapping)
    }
    international_rights = list(config.get("international_draft_rights") or [])

    forfeiture_rows = [item.as_row() for item in DRAFT_PICK_FORFEITURES]
    forfeited_source_ids = {row["source_asset_id"] for row in forfeiture_rows}
    expected_forfeited_source_ids = {"2029_R1_IND"} | {
        f"{year}_R1_LAC" for year in range(2030, 2034)
    }

    checks: dict[str, bool] = {
        "manifest_freezes_september_7_cutoff": (
            manifest.get("active_cutoff_date") == CUTOFF_DATE.isoformat()
            and config.get("cutoff_date") == CUTOFF_DATE.isoformat()
            and overlay_payload.get("reference_window_end_inclusive")
            == CUTOFF_DATE.isoformat()
        ),
        "manifest_points_to_frozen_overlay": (
            manifest.get("active_overlay") == OVERLAY_PATH.name
            and manifest.get("active_overlay_sha256") == _sha256(OVERLAY_PATH)
        ),
        "overlay_is_reference_only": (
            overlay_payload.get("reference_layer_only") is True
            and overlay_payload.get("simulation_branch_eligible") is False
            and all(
                row.get("reference_layer_only") is True
                and row.get("simulation_branch_eligible") is False
                for row in overlay_rows
            )
        ),
        "transaction_ledger_has_62_rows": len(transaction_rows) == 62,
        "transaction_ledger_has_48_feed_and_14_supplemental_rows": (
            sum(not _csv_bool(row.get("supplemental_event")) for row in transaction_rows)
            == 48
            and sum(_csv_bool(row.get("supplemental_event")) for row in transaction_rows)
            == 14
        ),
        "transaction_dates_are_inside_frozen_window": all(
            WINDOW_START_EXCLUSIVE < _date(row.get("transaction_date")) <= CUTOFF_DATE
            for row in transaction_rows
        ),
        "overlay_has_49_unique_players": (
            len(overlay_rows) == len(overlay_by_id) == 49
            and set(overlay_by_id) == set(latest_ledger_by_id)
        ),
        "overlay_is_exact_latest_ledger_projection": all(
            _overlay_matches_latest_ledger_row(row, latest_ledger_by_id[player_id])
            for player_id, row in overlay_by_id.items()
            if player_id in latest_ledger_by_id
        ),
        "overlay_status_counts_are_exact": dict(status_counts)
        == EXPECTED_STATUS_COUNTS,
        "two_way_identity_set_is_exact": two_way_ids == EXPECTED_TWO_WAY_IDS,
        "exhibit_10_identity_set_is_exact": exhibit_10_ids
        == EXPECTED_EXHIBIT_10_IDS,
        "two_way_semantics_are_exact": all(
            row.get("current_reference_two_way") is True
            and row.get("contract_reference_action") == "two_way_signing"
            and bool(row.get("current_reference_team"))
            for row in special_contract_rows
            if row.get("current_reference_status") == "two_way"
        ),
        "exhibit_10_semantics_are_exact": all(
            row.get("current_reference_two_way") is False
            and row.get("contract_reference_action") == "exhibit_10_signing"
            and bool(row.get("current_reference_team"))
            for row in special_contract_rows
            if row.get("current_reference_status") == "exhibit_10"
        ),
        "special_contract_descriptions_are_explicit": explicit_special_descriptions,
        "all_roster_rows_have_retained_https_sources": all(
            bool(str(row.get("source_name") or "").strip())
            and _is_https(row.get("source_url"))
            for row in overlay_rows
        ),
        "all_roster_sources_have_known_evidence_tiers": (
            set(source_tier_counts)
            <= {"nba_or_team_official", "independent_transaction_ledger"}
            and source_tier_counts.get("unclassified", 0) == 0
        ),
        "secondary_active_evidence_is_explicit_and_bounded": (
            secondary_active_ids == EXPECTED_SECONDARY_ACTIVE_EVIDENCE_IDS
        ),
        "primary_feed_rows_retain_frozen_source_hash": all(
            str(row.get("source_sha256") or "")
            == str(overlay_payload.get("source_sha256") or "")
            for row in overlay_rows
            if not row.get("supplemental_event")
        ),
        "draft_asset_override_set_is_exact": set(draft_by_id)
        == set(EXPECTED_DRAFT_ASSET_OWNERS),
        "draft_asset_owners_are_exact": all(
            str(draft_by_id.get(asset_id, {}).get("to_team") or "").upper()
            == owner
            for asset_id, owner in EXPECTED_DRAFT_ASSET_OWNERS.items()
        ),
        "draft_asset_evidence_is_complete_and_pre_cutoff": all(
            _date(row.get("transaction_date")) <= CUTOFF_DATE
            and _is_https(row.get("source_url"))
            for row in draft_overrides
        ),
        "conditional_second_has_component_level_evidence": (
            _is_https(
                draft_by_id.get("FPR_AFD12DB20C9F72A2", {}).get(
                    "asset_detail_source_url"
                )
            )
            and "second-most-favorable"
            in str(
                draft_by_id.get("FPR_AFD12DB20C9F72A2", {}).get("description")
                or ""
            ).lower()
        ),
        "kamagate_rights_transfer_is_exact": (
            len(international_rights) == 1
            and str(international_rights[0].get("player_id") or "") == "1631130"
            and str(international_rights[0].get("from_team") or "").upper()
            == "LAC"
            and str(international_rights[0].get("current_owner") or "").upper()
            == "CLE"
            and _date(international_rights[0].get("transaction_date"))
            <= CUTOFF_DATE
            and _is_https(international_rights[0].get("source_url"))
        ),
        "clippers_forfeiture_set_is_exact": (
            len(forfeiture_rows) == 5
            and {row["draft_year"] for row in forfeiture_rows}
            == set(range(2029, 2034))
            and forfeited_source_ids == expected_forfeited_source_ids
        ),
        "clippers_forfeitures_are_first_round_and_pre_cutoff": all(
            row.get("penalized_team") == "LAC"
            and row.get("round_number") == 1
            and _date(row.get("announced_date")) <= CUTOFF_DATE
            for row in forfeiture_rows
        ),
        "clippers_forfeitures_retain_official_nba_authority": all(
            row.get("authority_url")
            == "https://www.nba.com/news/nba-investigation-findings-la-clippers"
            for row in forfeiture_rows
        ),
        "active_checkpoint_and_direct_backup_are_present": bool(
            checkpoint_before and backup_before
        ),
    }

    checkpoint_after = _sha256(checkpoint_path)
    backup_after = _sha256(backup_path)
    checks["audit_did_not_change_active_save"] = (
        checkpoint_before == checkpoint_after
        and backup_before == backup_after
    )

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "passed": not failed,
        "cutoff_status": "frozen" if not failed else "not_frozen",
        "cutoff_date": CUTOFF_DATE.isoformat(),
        "failed_checks": failed,
        "checks": checks,
        "roster_evidence_summary": {
            "transaction_rows": len(transaction_rows),
            "feed_rows": sum(
                not _csv_bool(row.get("supplemental_event"))
                for row in transaction_rows
            ),
            "supplemental_rows": sum(
                _csv_bool(row.get("supplemental_event")) for row in transaction_rows
            ),
            "latest_players": len(overlay_rows),
            "status_counts": dict(sorted(status_counts.items())),
            "active_source_tier_counts": dict(sorted(source_tier_counts.items())),
            "secondary_active_evidence_player_ids": sorted(secondary_active_ids),
            "two_way_players": [
                {
                    "player_id": row.get("player_id"),
                    "player_slug": row.get("player_slug"),
                    "team": row.get("current_reference_team"),
                    "event_date": row.get("latest_event_date"),
                    "source_url": row.get("source_url"),
                }
                for row in special_contract_rows
                if row.get("current_reference_status") == "two_way"
            ],
            "exhibit_10_players": [
                {
                    "player_id": row.get("player_id"),
                    "player_slug": row.get("player_slug"),
                    "team": row.get("current_reference_team"),
                    "event_date": row.get("latest_event_date"),
                    "source_tier": source_tiers.get(str(row.get("player_id"))),
                    "source_url": row.get("source_url"),
                }
                for row in special_contract_rows
                if row.get("current_reference_status") == "exhibit_10"
            ],
        },
        "asset_evidence_summary": {
            "draft_asset_overrides": draft_overrides,
            "international_draft_rights": international_rights,
            "clippers_first_round_forfeitures": forfeiture_rows,
        },
        "evidence_policy": {
            "nba_or_team_official": (
                "Official NBA data, league release, team release, roster, or "
                "NBA-hosted player-news evidence."
            ),
            "independent_transaction_ledger": (
                "Transaction-specific independent ledger retained only where an "
                "official contract-type release was unavailable."
            ),
            "freeze_rule": (
                "No event after 2026-09-07 is admitted. Any future cutoff change "
                "must regenerate the ledger and pass this audit again."
            ),
        },
        "checkpoint": {
            "path": str(checkpoint_path.resolve()),
            "direct_backup_path": str(backup_path.resolve()),
            "sha256": checkpoint_after,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    print(f"cutoff_status={report['cutoff_status']}")
    print(f"report={REPORT_PATH}")
    if failed:
        raise RuntimeError("Live cutoff audit failed: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
