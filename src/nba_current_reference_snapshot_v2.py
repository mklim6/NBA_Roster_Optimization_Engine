from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import nba_aug04_to_aug14_current_reference_patch_v1 as movement


VERSION = "nba-current-reference-snapshot-v2-2026-09-07"
SCHEMA_VERSION = 2
WINDOW_START_EXCLUSIVE = date(2026, 8, 4)
WINDOW_END_INCLUSIVE = date(2026, 9, 7)
EXPECTED_FEED_ROW_COUNT = 48
EXPECTED_PLAYER_COUNT = 49

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION_CSV_PATH = (
    ROOT
    / "data"
    / "reference"
    / "nba_player_movement_delta_2026_08_04_to_2026_09_07.csv"
)
OVERLAY_CSV_PATH = (
    ROOT / "data" / "reference" / "nba_current_reference_overlay_2026_09_07.csv"
)
OVERLAY_JSON_PATH = ROOT / "app_data" / "nba_current_reference_overlay_2026_09_07.json"
MANIFEST_PATH = ROOT / "app_data" / "nba_current_reference_manifest.json"


def _supplement(
    event_date: str,
    player_id: str,
    player_slug: str,
    team: str,
    description: str,
    status: str,
    source_name: str,
    source_url: str,
    *,
    transaction_type: str = "Signing",
    two_way: bool = False,
) -> dict[str, Any]:
    if transaction_type == "Trade":
        roster_action = "move_to_team"
        contract_action = "trade"
    else:
        roster_action = "add_or_confirm_team_membership"
        contract_action = "exhibit_10_signing" if status == "exhibit_10" else "standard_signing"
    return {
        "transaction_date": event_date,
        "transaction_type": transaction_type,
        "transaction_description": description,
        "team_id": "",
        "team_abbreviation": team,
        "player_id": player_id,
        "player_slug": player_slug,
        "raw_json": "",
        "current_reference_team": team,
        "current_reference_status": status,
        "current_reference_two_way": two_way,
        "roster_reference_action": roster_action,
        "contract_reference_action": contract_action,
        "transaction_team": team,
        "source_name": source_name,
        "source_url": source_url,
        "source_sha256": "",
        "supplemental_event": True,
        "reference_layer_only": True,
        "simulation_branch_eligible": False,
    }


# These player-level actions are absent from the NBA Player Movement JSON but
# are needed to reconstruct the complete sequence. Later feed events (for
# example, a waiver) still win when producing the latest-status overlay.
SUPPLEMENTAL_EVENTS = [
    _supplement(
        "2026-08-17", "1629312", "haywood-highsmith", "PHX",
        "Phoenix Suns re-signed forward Haywood Highsmith.", "under_contract",
        "NBA transactions — Phoenix Suns",
        "https://www.nba.com/players/transactions?TeamID=1610612756",
    ),
    _supplement(
        "2026-08-17", "1641869", "malachi-smith", "TOR",
        "Toronto Raptors signed guard Malachi Smith to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-08-20", "1642882", "julian-reese", "DEN",
        "Denver Nuggets received forward Julian Reese in the five-team trade.",
        "two_way", "NBA 2026 offseason trade tracker",
        "https://www.nba.com/news/2026-offseason-trade-tracker",
        transaction_type="Trade", two_way=True,
    ),
    _supplement(
        "2026-08-27", "1643727", "jvonne-hadley", "MIA",
        "Miami Heat signed forward J'Vonne Hadley to an Exhibit 10 contract.",
        "exhibit_10", "Miami Heat official roster",
        "https://www.nba.com/heat/roster",
    ),
    _supplement(
        "2026-08-27", "1631207", "dalen-terry", "GSW",
        "Golden State Warriors signed forward Dalen Terry to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-08-31", "1643251", "josiah-allick", "CHA",
        "Charlotte Hornets signed forward Josiah Allick to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-08-31", "1641802", "matthew-murrell", "UTA",
        "Utah Jazz signed guard Matthew Murrell to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-09-01", "1643102", "trey-townsend", "CHA",
        "Charlotte Hornets signed forward Trey Townsend to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-09-01", "1643148", "saint-thomas", "PHI",
        "Philadelphia 76ers signed forward Saint Thomas to an Exhibit 10 contract.",
        "exhibit_10", "NBA player profile",
        "https://www.nba.com/player/1643148/saint-thomas",
    ),
    _supplement(
        "2026-09-01", "1642392", "jameer-nelson-jr", "PHI",
        "Philadelphia 76ers signed guard Jameer Nelson Jr. to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-09-01", "1629605", "tacko-fall", "PHI",
        "Philadelphia 76ers signed center Tacko Fall to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-09-02", "1630667", "kyle-mangas", "CHA",
        "Charlotte Hornets signed guard Kyle Mangas to an Exhibit 10 contract.",
        "exhibit_10", "Basketball-Reference 2026-27 transaction ledger",
        "https://www.basketball-reference.com/leagues/NBA_2027_transactions.html",
    ),
    _supplement(
        "2026-09-03", "1631103", "malaki-branham", "ORL",
        "Orlando Magic signed guard Malaki Branham to an Exhibit 10 contract.",
        "exhibit_10", "Orlando Magic",
        "https://www.nba.com/magic/news/orlando-magic-sign-free-agents-malaki-branham-jd-davison-20260903",
    ),
    _supplement(
        "2026-09-03", "1631120", "jd-davison", "ORL",
        "Orlando Magic signed guard JD Davison to an Exhibit 10 contract.",
        "exhibit_10", "Orlando Magic",
        "https://www.nba.com/magic/news/orlando-magic-sign-free-agents-malaki-branham-jd-davison-20260903",
    ),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def overlay_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "player_id": str(row["player_id"]),
        "player_slug": row.get("player_slug", ""),
        "latest_event_date": row["transaction_date"],
        "latest_event_type": row["transaction_type"],
        "latest_description": row["transaction_description"],
        "transaction_team": row.get("transaction_team", ""),
        "current_reference_team": row.get("current_reference_team", ""),
        "current_reference_status": row.get("current_reference_status", ""),
        "current_reference_two_way": bool(row.get("current_reference_two_way", False)),
        "roster_reference_action": row.get("roster_reference_action", ""),
        "contract_reference_action": row.get("contract_reference_action", ""),
        "source_name": row.get("source_name", ""),
        "source_url": row.get("source_url", ""),
        "source_sha256": row.get("source_sha256", ""),
        "supplemental_event": bool(row.get("supplemental_event", False)),
        "reference_layer_only": True,
        "simulation_branch_eligible": False,
    }


def build_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    status, body, error = movement.fetch(movement.PLAYER_MOVEMENT_URL)
    if status != 200 or not body:
        raise RuntimeError(f"NBA movement fetch failed: status={status}; error={error}")

    source_sha = movement.sha256_bytes(body)
    parsed = movement.parse_rows(json.loads(body.decode("utf-8-sig")))
    feed_rows: list[dict[str, Any]] = []
    for original in parsed:
        event_date = date.fromisoformat(original["transaction_date"])
        if not WINDOW_START_EXCLUSIVE < event_date <= WINDOW_END_INCLUSIVE:
            continue
        row = dict(original)
        row.update(movement.classify_event(row))
        row.update({
            "source_name": "NBA Player Movement",
            "source_url": movement.PLAYER_MOVEMENT_URL,
            "source_sha256": source_sha,
            "supplemental_event": False,
            "reference_layer_only": True,
            "simulation_branch_eligible": False,
        })
        feed_rows.append(row)

    if len(feed_rows) != EXPECTED_FEED_ROW_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_FEED_ROW_COUNT} NBA feed rows through Sep. 7; "
            f"found {len(feed_rows)}. Review the source before installing."
        )

    all_rows = feed_rows + [dict(row) for row in SUPPLEMENTAL_EVENTS]
    all_rows.sort(key=lambda row: (
        row["transaction_date"],
        0 if row.get("supplemental_event") else 1,
        row.get("transaction_type", ""),
        row.get("player_id", ""),
    ))

    latest_by_player: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        player_id = str(row.get("player_id", "")).strip()
        if player_id:
            latest_by_player[player_id] = row

    overlay_rows = [
        overlay_row(row)
        for _, row in sorted(latest_by_player.items(), key=lambda item: item[0])
    ]
    if len(overlay_rows) != EXPECTED_PLAYER_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_PLAYER_COUNT} unique players; found {len(overlay_rows)}."
        )

    return all_rows, overlay_rows, source_sha


def validate_semantics(overlay_rows: list[dict[str, Any]]) -> None:
    by_id = {row["player_id"]: row for row in overlay_rows}
    expected = {
        "1627732": ("SAC", "under_contract"),  # Ben Simmons
        "1643225": ("", "free_agent"),        # Kobe Stewart
        "1641935": ("", "free_agent"),        # Jarkel Joiner
        "1631120": ("ORL", "exhibit_10"),     # JD Davison
        "1629312": ("PHX", "under_contract"), # Haywood Highsmith
        "1642951": ("HOU", "two_way"),        # Sean Pedulla
        "202691": ("MIA", "under_contract"),  # Klay Thompson
        "1641715": ("", "free_agent"),        # Cam Whitmore
        "1629723": ("", "free_agent"),        # John Konchar
        "1641708": ("HOU", "under_contract"), # Amen Thompson
    }
    failures = []
    for player_id, outcome in expected.items():
        row = by_id.get(player_id, {})
        actual = (
            row.get("current_reference_team", ""),
            row.get("current_reference_status", ""),
        )
        if actual != outcome:
            failures.append(f"{player_id}: expected={outcome}; actual={actual}")
    if failures:
        raise RuntimeError("Semantic validation failed: " + "; ".join(failures))


def main() -> int:
    checkpoint_path: Path | None = None
    checkpoint_hash_before = ""
    try:
        import simulation_franchise_checkpoint_v1 as checkpoint
        checkpoint_path = Path(checkpoint.DEFAULT_CHECKPOINT_PATH)
        checkpoint_hash_before = sha256_file(checkpoint_path)
    except Exception:
        pass

    all_rows, overlay_rows, source_sha = build_snapshot()
    validate_semantics(overlay_rows)

    write_csv(TRANSACTION_CSV_PATH, all_rows)
    write_csv(OVERLAY_CSV_PATH, overlay_rows)

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "simulation_split_date": "2026-04-12",
        "reference_window_start_exclusive": WINDOW_START_EXCLUSIVE.isoformat(),
        "reference_window_end_inclusive": WINDOW_END_INCLUSIVE.isoformat(),
        "source_name": "NBA Player Movement plus sourced supplemental roster actions",
        "source_url": movement.PLAYER_MOVEMENT_URL,
        "source_sha256": source_sha,
        "feed_row_count": EXPECTED_FEED_ROW_COUNT,
        "supplemental_row_count": len(SUPPLEMENTAL_EVENTS),
        "player_count": len(overlay_rows),
        "reference_layer_only": True,
        "simulation_branch_eligible": False,
        "players": overlay_rows,
    }
    OVERLAY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY_JSON_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "version": "nba-current-reference-manifest-v1",
        "schema_version": 1,
        "active_cutoff_date": WINDOW_END_INCLUSIVE.isoformat(),
        "active_overlay": OVERLAY_JSON_PATH.name,
        "active_overlay_sha256": sha256_file(OVERLAY_JSON_PATH),
        "active_overlay_player_count": len(overlay_rows),
        "reference_layer_only": True,
        "simulation_branch_eligible": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    if checkpoint_path is not None:
        checkpoint_hash_after = sha256_file(checkpoint_path)
        if checkpoint_hash_after != checkpoint_hash_before:
            raise RuntimeError("Canonical franchise checkpoint changed during reference generation.")

    print(f"PASS {VERSION}")
    print(f"feed_rows={EXPECTED_FEED_ROW_COUNT}")
    print(f"supplemental_rows={len(SUPPLEMENTAL_EVENTS)}")
    print(f"players={len(overlay_rows)}")
    print(f"source_sha256={source_sha}")
    print(f"overlay={OVERLAY_JSON_PATH}")
    print(f"manifest={MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
