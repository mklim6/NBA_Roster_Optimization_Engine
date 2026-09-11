from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "nba-aug04-to-aug14-data-delta-audit-v1.0.2-2026-08-14"
WINDOW_START_EXCLUSIVE = date(2026, 8, 4)
WINDOW_END_INCLUSIVE = date(2026, 8, 14)
PLAYER_MOVEMENT_URL = (
    "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

EXPECTED_ROWS = [
    {
        "date": "2026-08-05",
        "type": "Signing",
        "player_id": "1641759",
        "needle": "Dillon Mitchell",
    },
    {
        "date": "2026-08-05",
        "type": "Signing",
        "player_id": "203484",
        "needle": "Kentavious Caldwell-Pope",
    },
    {
        "date": "2026-08-05",
        "type": "Waive",
        "player_id": "1631120",
        "needle": "JD Davison",
    },
    {
        "date": "2026-08-06",
        "type": "Signing",
        "player_id": "1642481",
        "needle": "Jamarion Sharp",
    },
    {
        "date": "2026-08-06",
        "type": "Waive",
        "player_id": "1642951",
        "needle": "Sean Pedulla",
    },
    {
        "date": "2026-08-08",
        "type": "Signing",
        "player_id": "1628415",
        "needle": "Dillon Brooks",
    },
    {
        "date": "2026-08-12",
        "type": "Signing",
        "player_id": "1629618",
        "needle": "Jalen Pickett",
    },
    {
        "date": "2026-08-12",
        "type": "Waive",
        "player_id": "1629312",
        "needle": "Haywood Highsmith",
    },
    {
        "date": "2026-08-13",
        "type": "Signing",
        "player_id": "203078",
        "needle": "Bradley Beal",
    },
    {
        "date": "2026-08-13",
        "type": "Waive",
        "player_id": "1630679",
        "needle": "Ethan Thompson",
    },
]

TEXT_EXTENSIONS = {
    ".py", ".json", ".csv", ".txt", ".md", ".toml", ".yaml", ".yml",
    ".sql", ".ps1", ".ini", ".cfg",
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
            "player_id": player_id,
            "player_slug": player_slug,
            "group_sort": clean(raw.get("GroupSort")),
            "raw_json": json.dumps(raw, sort_keys=True, default=str),
        })

    return result


def classify_impact(row: Mapping[str, Any]) -> str:
    tx_type = clean(row.get("transaction_type")).lower()
    desc = clean(row.get("transaction_description")).lower()

    if "veteran extension" in desc or "extension" in desc:
        return "contract_reference_extension"
    if "two-way contract" in desc or "two way contract" in desc:
        return "roster_and_two_way_reference_change"
    if tx_type == "waive":
        return "roster_and_contract_status_reference_change"
    if tx_type == "signing":
        return "roster_and_contract_reference_change"
    if tx_type == "trade":
        return "roster_trade_reference_change"
    return "reference_review"


def scan_project(root: Path, delta_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = set()
    for row in delta_rows:
        if row["player_id"]:
            terms.add(row["player_id"])
        slug = clean(row["player_slug"])
        if slug:
            terms.add(slug)
        desc = clean(row["transaction_description"])
        # player name sits between action verb and "to"/"from" in current feed.
        for expected in EXPECTED_ROWS:
            if expected["player_id"] == row["player_id"]:
                terms.add(expected["needle"])

    hits = []
    skip_parts = {
        ".git", ".fapostsplit", ".fapostsplit101", ".fapostsplit102",
        ".faaddcontract", ".fadecisionuniverse", ".fabranchpreview",
        ".fabranchpreview101", "__pycache__", "backups",
    }

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > 8_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="cp1252", errors="ignore")
            except Exception:
                continue
        except Exception:
            continue

        found = []
        low = text.lower()
        for term in sorted(terms):
            if term and term.lower() in low:
                found.append(term)

        if found:
            hits.append({
                "path": str(path.resolve()),
                "relative_path": str(path.resolve().relative_to(root)),
                "file_size": path.stat().st_size,
                "matched_terms": "|".join(found),
            })

    return hits


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

    print("=" * 128, flush=True)
    print("NBA AUG 4 -> AUG 14 DATA DELTA AUDIT V1.0.2", flush=True)
    print("=" * 128, flush=True)
    print(
        f"Window: after {WINDOW_START_EXCLUSIVE.isoformat()} "
        f"through {WINDOW_END_INCLUSIVE.isoformat()}",
        flush=True,
    )
    print(
        "REFERENCE-LAYER AUDIT ONLY. This package does not alter the "
        "April-12 simulation branch or durable checkpoint.",
        flush=True,
    )
    print("", flush=True)

    status, body, error = fetch(PLAYER_MOVEMENT_URL)
    if status != 200 or not body:
        raise RuntimeError(
            f"Could not load NBA Player Movement feed: status={status}; error={error}"
        )

    payload = json.loads(body.decode("utf-8-sig"))
    all_rows = parse_rows(payload)

    delta_rows = []
    for row in all_rows:
        try:
            d = date.fromisoformat(row["transaction_date"])
        except ValueError:
            continue
        if WINDOW_START_EXCLUSIVE < d <= WINDOW_END_INCLUSIVE:
            row = dict(row)
            row["reference_impact"] = classify_impact(row)
            row["simulation_branch_import_allowed"] = False
            delta_rows.append(row)

    delta_rows.sort(
        key=lambda row: (
            row["transaction_date"],
            row["transaction_type"],
            row["player_id"],
        )
    )

    print(f"Official Player Movement delta rows: {len(delta_rows)}", flush=True)
    for row in delta_rows:
        print(
            f"  {row['transaction_date']} | {row['transaction_type']:<8} | "
            f"{row['transaction_description']}",
            flush=True,
        )

    checks = []

    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict delta checks...", flush=True)

    check(
        "nba_player_movement_feed_loaded",
        bool(all_rows),
        f"rows={len(all_rows)}",
    )
    check(
        "at_least_ten_official_rows_after_aug4_through_aug14",
        len(delta_rows) >= 10,
        f"delta_rows={len(delta_rows)}",
    )

    actual_keys = {
        (
            row["transaction_date"],
            row["transaction_type"],
            row["player_id"],
        )
        for row in delta_rows
    }

    for expected in EXPECTED_ROWS:
        key = (
            expected["date"],
            expected["type"],
            expected["player_id"],
        )
        matching = [
            row
            for row in delta_rows
            if (
                row["transaction_date"],
                row["transaction_type"],
                row["player_id"],
            ) == key
        ]
        slug = re.sub(
            r"[^a-z0-9]+",
            "_",
            expected["needle"].lower(),
        ).strip("_")
        check(
            f"known_delta_{slug}",
            bool(matching)
            and expected["needle"].lower()
            in matching[0]["transaction_description"].lower(),
            f"expected={key}; found={bool(matching)}",
        )

    check(
        "all_delta_rows_remain_inside_requested_aug4_aug14_window",
        all(
            WINDOW_START_EXCLUSIVE
            < date.fromisoformat(row["transaction_date"])
            <= WINDOW_END_INCLUSIVE
            for row in delta_rows
        ),
        "Every exported movement remains strictly after Aug 4 and no later than Aug 14.",
    )

    known_keys = {
        (item["date"], item["type"], item["player_id"])
        for item in EXPECTED_ROWS
    }
    extra_delta_rows = [
        row for row in delta_rows
        if (
            row["transaction_date"],
            row["transaction_type"],
            row["player_id"],
        ) not in known_keys
    ]

    check(
        "all_ten_known_aug_delta_rows_present",
        all(
            (
                item["date"],
                item["type"],
                item["player_id"],
            ) in {
                (
                    row["transaction_date"],
                    row["transaction_type"],
                    row["player_id"],
                )
                for row in delta_rows
            }
            for item in EXPECTED_ROWS
        ),
        f"known_required={len(EXPECTED_ROWS)}; live_rows={len(delta_rows)}",
    )

    check(
        "additional_same_day_rows_are_captured_not_rejected",
        True,
        f"additional_rows={len(extra_delta_rows)}",
        severity="temporal_snapshot",
    )

    check(
        "delta_rows_are_reference_only",
        all(not row["simulation_branch_import_allowed"] for row in delta_rows),
        "Post-April-12 events may update reference/current-data layers only.",
    )

    project_hits = scan_project(root, delta_rows)

    # Checkpoint fingerprint is informational if the project has the franchise module.
    checkpoint_hash = ""
    checkpoint_exists = False
    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_exists = checkpoint_path.exists()
        if checkpoint_exists:
            h = hashlib.sha256()
            with checkpoint_path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(block)
            checkpoint_hash = h.hexdigest()
    except Exception:
        pass

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "NBA Aug4->Aug14 Data Delta Audit V1.0.2 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"nba_aug04_to_aug14_data_delta_audit_v1_0_2_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="nba_aug_delta_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "official_aug04_to_aug14_delta.csv", delta_rows)
        write_csv(export / "official_aug04_to_aug14_additional_rows.csv", extra_delta_rows)
        write_csv(export / "project_reference_candidate_files.csv", project_hits)
        write_csv(export / "delta_checks.csv", checks)

        summary = {
            "version": VERSION,
            "window_start_exclusive": WINDOW_START_EXCLUSIVE.isoformat(),
            "window_end_inclusive": WINDOW_END_INCLUSIVE.isoformat(),
            "source_url": PLAYER_MOVEMENT_URL,
            "source_sha256": sha256_bytes(body),
            "official_delta_row_count": len(delta_rows),
            "known_required_delta_row_count": len(EXPECTED_ROWS),
            "additional_live_delta_row_count": len(extra_delta_rows),
            "project_reference_candidate_file_count": len(project_hits),
            "checkpoint_exists": checkpoint_exists,
            "checkpoint_sha256": checkpoint_hash,
            "durable_checkpoint_write_performed": False,
            "simulation_branch_write_performed": False,
            "reference_data_write_performed": False,
            "passed": True,
            "next_slice": (
                "Inspect candidate project files and build a reference-layer-only "
                "Aug4->Aug14 patch for current rosters/contracts/transaction metadata. "
                "Do not import these events into the April-12 simulation branch."
            ),
        }

        (export / "delta_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """NBA AUG 4 -> AUG 14 DATA DELTA AUDIT V1.0.1
==========================================

V1 initially knew about six official movement rows, but the NBA Player Movement
feed later added four more rows dated Aug. 12-13.

V1.0.1 requires the ten currently proven rows:
Aug 5
- BOS signed Dillon Mitchell to a Two-Way Contract
- PHI signed Kentavious Caldwell-Pope to a Contract
- HOU waived JD Davison

Aug 6
- LAC signed Jamarion Sharp to a Two-Way Contract
- LAC waived Sean Pedulla

Aug 8
- PHX re-signed Dillon Brooks to a Veteran Extension

Aug 12
- LAC signed Jalen Pickett to a Two-Way Contract
- PHX waived Haywood Highsmith

Aug 13
- LAC re-signed Bradley Beal to a Contract
- IND waived Ethan Thompson

The audit intentionally allows additional Aug. 14 rows if the official NBA
feed changes again later the same day. Extras are exported instead of causing
a stale exact-count failure.

All events remain REFERENCE-LAYER ONLY and may not mutate the April-12
counterfactual franchise branch.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")
            archive.writestr(
                f"{export_id}/snapshots/NBA_Player_Movement.json",
                body,
                compress_type=zipfile.ZIP_DEFLATED,
            )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("NBA AUG 4 -> AUG 14 DATA DELTA AUDIT V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Official delta rows:             {len(delta_rows)}", flush=True)
    print(f"Candidate project files:         {len(project_hits)}", flush=True)
    print("Simulation branch write:         NOT PERFORMED", flush=True)
    print("Durable checkpoint write:        NOT PERFORMED", flush=True)
    print("Reference-data write:            NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
