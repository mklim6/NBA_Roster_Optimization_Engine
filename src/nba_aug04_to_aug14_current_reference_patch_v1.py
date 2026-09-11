from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "nba-aug04-to-aug14-current-reference-patch-v1-2026-08-14"
WINDOW_START_EXCLUSIVE = date(2026, 8, 4)
WINDOW_END_INCLUSIVE = date(2026, 8, 14)
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

PLAYER_MOVEMENT_URL = (
    "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

TEAM_ABBR = {
    "1610612737": "ATL", "1610612738": "BOS", "1610612751": "BKN",
    "1610612766": "CHA", "1610612741": "CHI", "1610612739": "CLE",
    "1610612742": "DAL", "1610612743": "DEN", "1610612765": "DET",
    "1610612744": "GSW", "1610612745": "HOU", "1610612754": "IND",
    "1610612746": "LAC", "1610612747": "LAL", "1610612763": "MEM",
    "1610612748": "MIA", "1610612749": "MIL", "1610612750": "MIN",
    "1610612740": "NOP", "1610612752": "NYK", "1610612760": "OKC",
    "1610612753": "ORL", "1610612755": "PHI", "1610612756": "PHX",
    "1610612757": "POR", "1610612758": "SAC", "1610612759": "SAS",
    "1610612761": "TOR", "1610612762": "UTA", "1610612764": "WAS",
}

KNOWN_REQUIRED = {
    ("2026-08-05", "Signing", "1641759"),
    ("2026-08-05", "Signing", "203484"),
    ("2026-08-05", "Waive", "1631120"),
    ("2026-08-06", "Signing", "1642481"),
    ("2026-08-06", "Waive", "1642951"),
    ("2026-08-08", "Signing", "1628415"),
    ("2026-08-12", "Signing", "1629618"),
    ("2026-08-12", "Waive", "1629312"),
    ("2026-08-13", "Signing", "203078"),
    ("2026-08-13", "Waive", "1630679"),
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def fetch(url: str, timeout: int = 35) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nba.com/players/transactions",
            "Origin": "https://www.nba.com",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200)), response.read(), ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return int(exc.code), body, f"HTTPError: {exc}"
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}: {exc}"


def parse_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    node = payload.get("NBA_Player_Movement") or payload
    rows = node.get("rows") if isinstance(node, Mapping) else None
    if not isinstance(rows, list):
        raise RuntimeError("NBA Player Movement payload does not contain rows.")

    result = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue

        tx_date = clean(
            raw.get("TRANSACTION_DATE")
            or raw.get("Transaction_Date")
            or raw.get("transaction_date")
        )[:10]
        tx_type = clean(
            raw.get("Transaction_Type")
            or raw.get("TRANSACTION_TYPE")
            or raw.get("transaction_type")
        )
        desc = clean(
            raw.get("TRANSACTION_DESCRIPTION")
            or raw.get("Transaction_Description")
            or raw.get("transaction_description")
        )
        player_id = pid(
            raw.get("PLAYER_ID")
            or raw.get("Player_ID")
            or raw.get("player_id")
        )
        team_id = pid(
            raw.get("TEAM_ID")
            or raw.get("Team_ID")
            or raw.get("team_id")
        )
        player_slug = clean(
            raw.get("PLAYER_SLUG")
            or raw.get("Player_Slug")
            or raw.get("player_slug")
        )

        if not tx_date:
            continue

        result.append({
            "transaction_date": tx_date,
            "transaction_type": tx_type,
            "transaction_description": desc,
            "team_id": team_id,
            "team_abbreviation": TEAM_ABBR.get(team_id, ""),
            "player_id": player_id,
            "player_slug": player_slug,
            "raw_json": json.dumps(raw, sort_keys=True, default=str),
        })

    return result


def classify_event(row: Mapping[str, Any]) -> dict[str, Any]:
    tx_type = clean(row["transaction_type"]).lower()
    desc = clean(row["transaction_description"])
    low = desc.lower()
    team = clean(row["team_abbreviation"])

    if tx_type == "waive":
        return {
            "current_reference_team": "",
            "current_reference_status": "free_agent",
            "current_reference_two_way": False,
            "roster_reference_action": "remove_from_team",
            "contract_reference_action": "waived",
            "transaction_team": team,
        }

    if tx_type == "signing":
        two_way = "two-way contract" in low or "two way contract" in low
        extension = "extension" in low
        return {
            "current_reference_team": team,
            "current_reference_status": (
                "two_way" if two_way else "under_contract"
            ),
            "current_reference_two_way": two_way,
            "roster_reference_action": (
                "preserve_team_membership"
                if extension
                else "add_or_confirm_team_membership"
            ),
            "contract_reference_action": (
                "extension"
                if extension
                else "two_way_signing"
                if two_way
                else "standard_signing"
            ),
            "transaction_team": team,
        }

    if tx_type == "trade":
        return {
            "current_reference_team": team,
            "current_reference_status": "under_contract",
            "current_reference_two_way": False,
            "roster_reference_action": "move_to_team",
            "contract_reference_action": "trade",
            "transaction_team": team,
        }

    return {
        "current_reference_team": team,
        "current_reference_status": "reference_review",
        "current_reference_two_way": False,
        "roster_reference_action": "review",
        "contract_reference_action": clean(row["transaction_type"]),
        "transaction_team": team,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    package_dir = Path(__file__).resolve().parent

    # Protect the counterfactual franchise checkpoint.
    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_before = sha256_file(checkpoint_path)
        checkpoint = checkpoint_module.load_franchise_checkpoint()
        state_digest_before = object_digest(checkpoint.simulation_state)
    except Exception as exc:
        raise RuntimeError("Could not load canonical franchise checkpoint.") from exc

    if checkpoint_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint is not at the guarded pre-reference-patch revision.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_before}"
        )

    status, body, error = fetch(PLAYER_MOVEMENT_URL)
    if status != 200 or not body:
        raise RuntimeError(
            f"Could not load NBA Player Movement feed: status={status}; error={error}"
        )

    source_sha = sha256_bytes(body)
    all_rows = parse_rows(json.loads(body.decode("utf-8-sig")))

    delta_rows = []
    for row in all_rows:
        try:
            d = date.fromisoformat(row["transaction_date"])
        except ValueError:
            continue
        if WINDOW_START_EXCLUSIVE < d <= WINDOW_END_INCLUSIVE:
            row = dict(row)
            row.update(classify_event(row))
            row["source_name"] = "NBA Player Movement"
            row["source_url"] = PLAYER_MOVEMENT_URL
            row["source_sha256"] = source_sha
            row["simulation_branch_eligible"] = False
            row["reference_layer_only"] = True
            delta_rows.append(row)

    delta_rows.sort(
        key=lambda row: (
            row["transaction_date"],
            row["transaction_type"],
            row["player_id"],
        )
    )

    live_keys = {
        (
            row["transaction_date"],
            row["transaction_type"],
            row["player_id"],
        )
        for row in delta_rows
    }
    missing = sorted(KNOWN_REQUIRED - live_keys)
    if missing:
        raise RuntimeError(
            "Live NBA feed is missing known required Aug4->Aug14 rows: "
            + repr(missing)
        )

    # Latest event per player wins for current-reference status.
    latest_by_player: dict[str, dict[str, Any]] = {}
    for row in delta_rows:
        latest_by_player[row["player_id"]] = row

    overlay_rows = []
    for player_id, row in sorted(
        latest_by_player.items(),
        key=lambda item: (
            item[1]["transaction_date"],
            item[0],
        ),
    ):
        overlay_rows.append({
            "player_id": player_id,
            "player_slug": row["player_slug"],
            "latest_event_date": row["transaction_date"],
            "latest_event_type": row["transaction_type"],
            "latest_description": row["transaction_description"],
            "transaction_team": row["transaction_team"],
            "current_reference_team": row["current_reference_team"],
            "current_reference_status": row["current_reference_status"],
            "current_reference_two_way": row["current_reference_two_way"],
            "roster_reference_action": row["roster_reference_action"],
            "contract_reference_action": row["contract_reference_action"],
            "source_name": row["source_name"],
            "source_url": row["source_url"],
            "source_sha256": row["source_sha256"],
            "reference_layer_only": True,
            "simulation_branch_eligible": False,
        })

    # Install only dedicated current/reference artifacts. Do not rewrite
    # historical inputs, rating releases, saved scenarios, model outputs, or
    # the durable simulation checkpoint.
    reference_dir = root / "data" / "reference"
    app_dir = root / "app_data"
    reference_dir.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)

    tx_path = reference_dir / "nba_player_movement_delta_2026_08_04_to_2026_08_14.csv"
    overlay_csv_path = reference_dir / "nba_current_reference_overlay_2026_08_14.csv"
    overlay_json_path = app_dir / "nba_current_reference_overlay_2026_08_14.json"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / "backups" / f"nba_current_reference_patch_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    targets = [tx_path, overlay_csv_path, overlay_json_path]
    for target in targets:
        if target.exists():
            shutil.copy2(target, backup_dir / target.name)

    write_csv(tx_path, delta_rows)
    write_csv(overlay_csv_path, overlay_rows)

    overlay_payload = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
        "reference_window_start_exclusive": WINDOW_START_EXCLUSIVE.isoformat(),
        "reference_window_end_inclusive": WINDOW_END_INCLUSIVE.isoformat(),
        "source_name": "NBA Player Movement",
        "source_url": PLAYER_MOVEMENT_URL,
        "source_sha256": source_sha,
        "reference_layer_only": True,
        "simulation_branch_eligible": False,
        "player_count": len(overlay_rows),
        "players": overlay_rows,
    }
    overlay_json_path.write_text(
        json.dumps(overlay_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Validate exact semantic outcomes for all ten known rows.
    outcome_by_id = {row["player_id"]: row for row in overlay_rows}
    expected_semantics = {
        "1641759": ("BOS", "two_way"),
        "203484": ("PHI", "under_contract"),
        "1631120": ("", "free_agent"),
        "1642481": ("LAC", "two_way"),
        "1642951": ("", "free_agent"),
        "1628415": ("PHX", "under_contract"),
        "1629618": ("LAC", "two_way"),
        "1629312": ("", "free_agent"),
        "203078": ("LAC", "under_contract"),
        "1630679": ("", "free_agent"),
    }

    checks = []
    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("NBA AUG 4 -> AUG 14 CURRENT REFERENCE PATCH V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Official in-window transactions: {len(delta_rows)}", flush=True)
    print(f"Player-level overlay rows:       {len(overlay_rows)}", flush=True)
    print("REFERENCE LAYER ONLY.", flush=True)
    print("", flush=True)
    print("Running strict patch checks...", flush=True)

    check(
        "all_ten_known_rows_present",
        not missing,
        f"known_required={len(KNOWN_REQUIRED)}; live_rows={len(delta_rows)}",
    )
    check(
        "all_rows_are_reference_only",
        all(
            row["reference_layer_only"]
            and not row["simulation_branch_eligible"]
            for row in delta_rows
        ),
        "No delta row is eligible for April-12 branch import.",
    )

    for player_id, (expected_team, expected_status) in expected_semantics.items():
        row = outcome_by_id.get(player_id, {})
        check(
            f"expected_reference_semantics_{player_id}",
            clean(row.get("current_reference_team")) == expected_team
            and clean(row.get("current_reference_status")) == expected_status,
            (
                f"expected_team={expected_team or '<FA>'}; "
                f"expected_status={expected_status}; "
                f"actual_team={clean(row.get('current_reference_team')) or '<FA>'}; "
                f"actual_status={clean(row.get('current_reference_status'))}"
            ),
        )

    check(
        "transaction_snapshot_written",
        tx_path.exists() and tx_path.stat().st_size > 0,
        str(tx_path),
    )
    check(
        "overlay_csv_written",
        overlay_csv_path.exists() and overlay_csv_path.stat().st_size > 0,
        str(overlay_csv_path),
    )
    check(
        "overlay_json_written",
        overlay_json_path.exists() and overlay_json_path.stat().st_size > 0,
        str(overlay_json_path),
    )

    checkpoint_after = sha256_file(checkpoint_path)
    state_digest_after = object_digest(checkpoint.simulation_state)
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_after == checkpoint_before == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_after,
    )
    check(
        "loaded_simulation_state_unchanged",
        state_digest_after == state_digest_before,
        state_digest_after,
    )

    failed = [
        row["check_id"] for row in checks
        if row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Current Reference Patch V1 failed strict checks: "
            + ", ".join(failed)
        )

    audit_id = f"nba_aug04_to_aug14_current_reference_patch_v1_{stamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = audit_dir / f"{audit_id}.zip"

    with tempfile.TemporaryDirectory(prefix="nba_current_ref_patch_") as tmpdir:
        export = Path(tmpdir) / audit_id
        export.mkdir(parents=True)

        write_csv(export / "installed_transaction_delta.csv", delta_rows)
        write_csv(export / "installed_player_reference_overlay.csv", overlay_rows)
        write_csv(export / "patch_checks.csv", checks)

        installed_manifest = []
        for installed in [tx_path, overlay_csv_path, overlay_json_path]:
            installed_manifest.append({
                "path": str(installed.resolve()),
                "sha256": sha256_file(installed),
                "size": installed.stat().st_size,
            })
        write_csv(export / "installed_reference_manifest.csv", installed_manifest)

        summary = {
            "version": VERSION,
            "official_delta_row_count": len(delta_rows),
            "player_overlay_count": len(overlay_rows),
            "known_required_count": len(KNOWN_REQUIRED),
            "additional_live_rows": len(delta_rows) - len(KNOWN_REQUIRED),
            "source_sha256": source_sha,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "simulation_branch_mutation_performed": False,
            "durable_checkpoint_write_performed": False,
            "historical_data_rewrite_performed": False,
            "rating_release_rewrite_performed": False,
            "saved_scenario_rewrite_performed": False,
            "reference_overlay_write_performed": True,
            "passed": True,
            "next_slice": (
                "Wire the current-reference overlay into only those UI/reference "
                "surfaces that intentionally display present-day NBA affiliation. "
                "Keep franchise simulation initialization pinned to the reconstructed "
                "April-12 branch. Then resume the 16-row lifecycle manual-evidence queue."
            ),
        }
        (export / "patch_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """NBA AUG 4 -> AUG 14 CURRENT REFERENCE PATCH V1
================================================

Installed reference artifacts
-----------------------------
data/reference/nba_player_movement_delta_2026_08_04_to_2026_08_14.csv
data/reference/nba_current_reference_overlay_2026_08_14.csv
app_data/nba_current_reference_overlay_2026_08_14.json
src/nba_current_reference_overlay_v1.py

Design rule
-----------
These files describe CURRENT real-world NBA affiliation/status only.

They do NOT rewrite:
- the canonical franchise checkpoint
- the reconstructed April-12 simulation branch
- historical player stats
- player rating releases
- trade-model outputs
- old batch simulation outputs
- saved test scenarios
- old CBA evidence artifacts

Waived players become current-reference free agents.
Two-Way signings are marked as current-reference Two-Way players.
Standard signings update current-reference team/status.
Extensions preserve team membership and update contract-event provenance.

No salary or guarantee amount is invented from a transaction record.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{audit_id}/{item.name}")
            archive.writestr(
                f"{audit_id}/snapshots/NBA_Player_Movement.json",
                body,
                compress_type=zipfile.ZIP_DEFLATED,
            )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("NBA AUG 4 -> AUG 14 CURRENT REFERENCE PATCH V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Transactions installed:          {len(delta_rows)}", flush=True)
    print(f"Player reference overlay rows:   {len(overlay_rows)}", flush=True)
    print("Historical/rating rewrites:      NONE", flush=True)
    print("Simulation branch mutation:      NOT PERFORMED", flush=True)
    print("Durable checkpoint write:        NOT PERFORMED", flush=True)
    print("Reference overlay write:         PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
