from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nba_current_reference_overlay_v1 import (  # noqa: E402
    CurrentReferenceOverlayError,
    DEFAULT_MANIFEST_PATH,
    load_current_reference_overlay,
    overlay_current_reference,
)
from nba_current_reference_snapshot_v2 import (  # noqa: E402
    EXPECTED_FEED_ROW_COUNT,
    EXPECTED_PLAYER_COUNT,
    OVERLAY_JSON_PATH,
    TRANSACTION_CSV_PATH,
    sha256_file,
)
VERSION = "validate-nba-current-reference-v2-2026-09-07"
REPORT_PATH = OUTPUTS / "nba_current_reference_v2_validation.json"
CHECKPOINT_PATH = OUTPUTS / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"


def main() -> int:
    checkpoint_path = CHECKPOINT_PATH
    checkpoint_before = sha256_file(checkpoint_path)
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = json.loads(OVERLAY_JSON_PATH.read_text(encoding="utf-8"))
    rows = load_current_reference_overlay()
    ratings_page = (ROOT / "pages" / "2_Player_Ratings.py").read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "manifest_points_to_sep07_overlay": (
            manifest.get("active_cutoff_date") == "2026-09-07"
            and manifest.get("active_overlay") == OVERLAY_JSON_PATH.name
        ),
        "manifest_hash_matches_overlay": (
            manifest.get("active_overlay_sha256") == sha256_file(OVERLAY_JSON_PATH)
        ),
        "payload_schema_v2": payload.get("schema_version") == 2,
        "feed_row_count_is_frozen": payload.get("feed_row_count") == EXPECTED_FEED_ROW_COUNT,
        "overlay_has_49_unique_players": (
            len(rows) == EXPECTED_PLAYER_COUNT == len(set(rows))
        ),
        "transaction_ledger_has_62_rows": (
            sum(1 for _ in TRANSACTION_CSV_PATH.open("r", encoding="utf-8-sig")) - 1 == 62
        ),
        "all_rows_reference_only": all(
            row.get("reference_layer_only") is True
            and row.get("simulation_branch_eligible") is False
            for row in rows.values()
        ),
        "free_agents_have_no_team": all(
            not row.get("current_reference_team")
            for row in rows.values()
            if row.get("current_reference_status") == "free_agent"
        ),
        "two_way_rows_have_flag": all(
            row.get("current_reference_two_way") is True
            for row in rows.values()
            if row.get("current_reference_status") == "two_way"
        ),
        "ben_simmons_is_sacramento": (
            rows["1627732"]["current_reference_team"] == "SAC"
            and rows["1627732"]["current_reference_status"] == "under_contract"
        ),
        "jd_davison_latest_event_is_orlando_exhibit10": (
            rows["1631120"]["current_reference_team"] == "ORL"
            and rows["1631120"]["current_reference_status"] == "exhibit_10"
        ),
        "sean_pedulla_latest_event_is_houston_two_way": (
            rows["1642951"]["current_reference_team"] == "HOU"
            and rows["1642951"]["current_reference_status"] == "two_way"
        ),
        "klay_thompson_latest_event_is_miami": (
            rows["202691"]["current_reference_team"] == "MIA"
        ),
        "cam_whitmore_is_free_agent": (
            rows["1641715"]["current_reference_status"] == "free_agent"
        ),
        "john_konchar_is_free_agent": (
            rows["1629723"]["current_reference_status"] == "free_agent"
        ),
        "ratings_page_wires_read_only_reference_tab": (
            '"Current-reference changes"' in ratings_page
            and "render_current_reference(st, records)" in ratings_page
            and "does not alter the " in ratings_page
            and "April 12 Franchise Mode scenario" in ratings_page
        ),
    }

    enriched = overlay_current_reference({"player_name": "Ben Simmons"}, "1627732")
    checks["overlay_exposes_action_and_source_fields"] = (
        enriched.get("current_reference_contract_action") == "standard_signing"
        and enriched.get("current_reference_source_url")
        == "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
    )

    with tempfile.TemporaryDirectory(prefix="nba_current_ref_validation_") as tmp:
        malformed = Path(tmp) / "malformed.json"
        malformed.write_text('{"player_count": 1, "players": []}', encoding="utf-8")
        try:
            load_current_reference_overlay(malformed)
            rejected = False
        except CurrentReferenceOverlayError:
            rejected = True
        checks["malformed_overlay_fails_closed"] = rejected

    checkpoint_after = sha256_file(checkpoint_path)
    checks["canonical_franchise_checkpoint_unchanged"] = (
        checkpoint_before == checkpoint_after
    )

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "passed": not failed,
        "failed_checks": failed,
        "checks": checks,
        "summary": {
            "active_cutoff_date": manifest.get("active_cutoff_date"),
            "feed_rows": payload.get("feed_row_count"),
            "supplemental_rows": payload.get("supplemental_row_count"),
            "players": len(rows),
            "source_sha256": payload.get("source_sha256"),
            "checkpoint_sha256": checkpoint_after,
        },
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    print(f"report={REPORT_PATH}")
    if failed:
        raise RuntimeError("Current-reference validation failed: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
