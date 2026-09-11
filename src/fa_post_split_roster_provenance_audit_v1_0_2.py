from __future__ import annotations

import csv
import hashlib
import json
import math
import pickle
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-post-split-roster-provenance-audit-v1.0.2-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

# NBA-hosted Player Movement feed used by the Transactions experience.
PLAYER_MOVEMENT_URLS = (
    "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json",
    "https://www.nba.com/stats/js/data/playermovement/NBA_Player_Movement.json",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

TEAM_IDS = {
    "ATL": 1610612737, "BOS": 1610612738, "BKN": 1610612751,
    "CHA": 1610612766, "CHI": 1610612741, "CLE": 1610612739,
    "DAL": 1610612742, "DEN": 1610612743, "DET": 1610612765,
    "GSW": 1610612744, "HOU": 1610612745, "IND": 1610612754,
    "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763,
    "MIA": 1610612748, "MIL": 1610612749, "MIN": 1610612750,
    "NOP": 1610612740, "NYK": 1610612752, "OKC": 1610612760,
    "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759,
    "TOR": 1610612761, "UTA": 1610612762, "WAS": 1610612764,
}
TEAM_CODE_BY_ID = {str(v): k for k, v in TEAM_IDS.items()}

FIELD_ALIASES = {
    "transaction_type": (
        "transaction_type", "transactiontype", "type",
    ),
    "transaction_date": (
        "transaction_date", "transactiondate", "date",
    ),
    "player_id": (
        "player_id", "playerid", "person_id", "personid",
    ),
    "player_name": (
        "player_name", "playername", "player", "name",
    ),
    "team_id": (
        "team_id", "teamid",
    ),
    "team_name": (
        "team_name", "teamname", "team",
    ),
    "description": (
        "description", "transaction_description",
        "transactiondescription", "detail", "details",
    ),
}

DEPARTURE_TYPES = (
    "waiv", "release", "terminate", "assign",
)
ARRIVAL_TYPES = (
    "sign", "trade", "claim", "convert", "receive", "acquir",
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def player_name(player: Any, fallback: str) -> str:
    for attr in ("player_name", "display_name", "name", "full_name"):
        value = clean(getattr(player, attr, ""))
        if value:
            return value
    return fallback


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


def column_names(node: Mapping[str, Any]) -> list[str]:
    raw = node.get("columns") or node.get("Columns") or []
    if isinstance(raw, list):
        names = []
        for item in raw:
            if isinstance(item, Mapping):
                names.append(
                    clean(item.get("Name") or item.get("name") or item.get("Column"))
                )
            else:
                names.append(clean(item))
        return names

    if isinstance(raw, Mapping):
        for key in ("Name", "name", "names"):
            value = raw.get(key)
            if isinstance(value, list):
                return [clean(x) for x in value]
    return []


def rows_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    node = (
        payload.get("NBA_Player_Movement")
        or payload.get("nba_player_movement")
        or payload
    )
    if not isinstance(node, Mapping):
        raise RuntimeError("Player Movement JSON root is not a mapping.")

    raw_rows = node.get("rows") or node.get("Rows") or []
    if not isinstance(raw_rows, list):
        raise RuntimeError("Player Movement JSON rows are not a list.")

    if not raw_rows:
        return []

    if all(isinstance(row, Mapping) for row in raw_rows):
        return [dict(row) for row in raw_rows]

    names = column_names(node)
    if not names:
        raise RuntimeError(
            "Player Movement rows are arrays but column names could not be resolved."
        )

    result = []
    for row in raw_rows:
        if not isinstance(row, (list, tuple)):
            continue
        result.append({
            names[i]: row[i] if i < len(row) else None
            for i in range(len(names))
        })
    return result


def canonicalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {norm_key(k): v for k, v in row.items()}

    def get(alias_group: str) -> Any:
        for alias in FIELD_ALIASES[alias_group]:
            if alias in normalized:
                return normalized[alias]
        return ""

    transaction_date = clean(get("transaction_date"))
    parsed_date = ""
    if transaction_date:
        text = transaction_date[:10]
        try:
            parsed_date = date.fromisoformat(text).isoformat()
        except ValueError:
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    parsed_date = datetime.strptime(transaction_date, fmt).date().isoformat()
                    break
                except ValueError:
                    pass

    team_id = pid(get("team_id"))
    return {
        "transaction_type": clean(get("transaction_type")),
        "transaction_date": parsed_date,
        "player_id": pid(get("player_id")),
        "player_name": clean(get("player_name")),
        "team_id": team_id,
        "team_abbreviation": TEAM_CODE_BY_ID.get(team_id, ""),
        "team_name": clean(get("team_name")),
        "description": clean(get("description")),
        "raw_row_json": json.dumps(row, sort_keys=True, default=str),
    }


def fetch_player_movement() -> tuple[str, bytes, list[dict[str, Any]], list[dict[str, Any]]]:
    attempts = []
    for url in PLAYER_MOVEMENT_URLS:
        status, body, error = fetch(url)
        attempts.append({
            "source_url": url,
            "http_status": status,
            "source_sha256": sha256_bytes(body) if body else "",
            "fetch_error": error,
        })
        if status != 200 or not body:
            continue
        try:
            payload = json.loads(body.decode("utf-8-sig"))
            raw_rows = rows_from_payload(payload)
            rows = [canonicalize_row(row) for row in raw_rows]
        except Exception as exc:
            attempts[-1]["fetch_error"] = (
                attempts[-1]["fetch_error"] + " | " if attempts[-1]["fetch_error"] else ""
            ) + f"parse:{type(exc).__name__}:{exc}"
            continue

        valid = [
            row for row in rows
            if clean(row["transaction_date"])
            and (clean(row["player_id"]) or clean(row["player_name"]))
        ]
        if valid:
            return url, body, rows, attempts

    raise RuntimeError(
        "Could not load a parseable NBA Player Movement JSON feed. "
        + json.dumps(attempts, default=str)
    )


def classify_current_team_event(row: Mapping[str, Any]) -> str:
    event = normalize(
        f"{row.get('transaction_type', '')} {row.get('description', '')}"
    )
    if any(token in event for token in DEPARTURE_TYPES):
        return "post_split_departure_or_termination"
    if any(token in event for token in ARRIVAL_TYPES):
        return "post_split_current_team_transaction"
    return "post_split_current_team_transaction_unclassified_type"


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

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_hash = sha256_file(checkpoint_path)
        checkpoint = checkpoint_module.load_franchise_checkpoint()
    except Exception as exc:
        raise RuntimeError("Could not load canonical franchise checkpoint.") from exc

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Checkpoint changed unexpectedly before provenance hotfix audit.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)

    players = getattr(state, "players", {}) or {}
    teams = getattr(state, "teams", {}) or {}

    roster_owner: dict[str, str] = {}
    current_roster_rows = []
    id_to_name: dict[str, str] = {}
    name_to_ids: dict[str, list[str]] = defaultdict(list)

    for player_id, player in players.items():
        player_id = pid(player_id)
        name = player_name(player, player_id)
        id_to_name[player_id] = name
        if normalize(name):
            name_to_ids[normalize(name)].append(player_id)

    for team_code, team_state in teams.items():
        for raw_id in (getattr(team_state, "roster_player_ids", ()) or ()):
            player_id = pid(raw_id)
            roster_owner[player_id] = clean(team_code).upper()
            player = players.get(player_id)
            current_roster_rows.append({
                "player_id": player_id,
                "player_name": id_to_name.get(player_id, player_id),
                "current_checkpoint_team": clean(team_code).upper(),
                "roster_status": clean(getattr(player, "roster_status", "")) if player else "",
                "contract_status": clean(
                    getattr(getattr(player, "contract", None), "status", "")
                ) if player else "",
            })

    print("=" * 128, flush=True)
    print("2026 POST-SPLIT ROSTER PROVENANCE AUDIT V1.0.2", flush=True)
    print("=" * 128, flush=True)
    print(f"Simulation split: {SIMULATION_SPLIT_DATE.isoformat()}", flush=True)
    print(f"Checkpoint: {checkpoint_hash}", flush=True)
    print(f"Current roster entries: {len(current_roster_rows)}", flush=True)
    print("Source: NBA-hosted Player Movement JSON feed.", flush=True)
    print("READ-ONLY. No roster or checkpoint mutation.", flush=True)
    print("", flush=True)

    source_url, source_body, movement_rows, attempts = fetch_player_movement()

    valid_dated = [
        row for row in movement_rows
        if clean(row["transaction_date"])
    ]
    post_split_rows = [
        row for row in valid_dated
        if date.fromisoformat(row["transaction_date"]) > SIMULATION_SPLIT_DATE
    ]

    matched_rows = []
    current_team_matches = []

    for row in post_split_rows:
        matched_ids: list[str] = []
        source_player_id = pid(row["player_id"])

        if source_player_id and source_player_id in players:
            matched_ids = [source_player_id]
            match_method = "nba_player_id"
        else:
            key = normalize(row["player_name"])
            candidates = name_to_ids.get(key, [])
            matched_ids = candidates[:] if len(candidates) == 1 else []
            match_method = "normalized_name" if matched_ids else ""

        for player_id in matched_ids:
            current_team = roster_owner.get(player_id, "")
            scoped_team = clean(row["team_abbreviation"]).upper()
            record = {
                **row,
                "matched_checkpoint_player_id": player_id,
                "matched_checkpoint_player_name": id_to_name.get(player_id, player_id),
                "match_method": match_method,
                "current_checkpoint_team": current_team,
                "current_roster_player": bool(current_team),
                "same_as_current_checkpoint_team": bool(
                    current_team and scoped_team and current_team == scoped_team
                ),
                "event_imported_into_simulator": False,
            }
            if current_team and scoped_team == current_team:
                record["provenance_class"] = classify_current_team_event(row)
                current_team_matches.append(record)
            elif current_team and scoped_team and scoped_team != current_team:
                record["provenance_class"] = "post_split_other_team_transaction"
            else:
                record["provenance_class"] = "post_split_matched_nonrostered_player"

            matched_rows.append(record)

    current_arrival_candidates = [
        row for row in current_team_matches
        if row["provenance_class"] != "post_split_departure_or_termination"
    ]

    known_memphis = {
        "Jerami Grant": "2026-06-29",
        "D'Angelo Russell": "2026-07-08",
        "AJ Johnson": "2026-07-08",
        "Isaiah Stewart": "2026-07-08",
        "Quinten Post": "2026-07-08",
    }

    known_lookup = {
        (normalize(row["matched_checkpoint_player_name"]), row["transaction_date"])
        for row in current_team_matches
        if row["current_checkpoint_team"] == "MEM"
    }

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

    checks = []
    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("Running strict provenance checks...", flush=True)
    check(
        "canonical_checkpoint_is_still_pre_reconciliation_revision",
        checkpoint_hash == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash,
    )
    check(
        "nba_player_movement_json_loaded",
        bool(movement_rows),
        f"source={source_url}; rows={len(movement_rows)}",
    )
    check(
        "player_movement_has_post_split_rows",
        bool(post_split_rows),
        f"post_split_rows={len(post_split_rows)}",
    )

    for name, expected_date in known_memphis.items():
        slug = re.sub(r"[^a-z0-9]+", "_", normalize(name)).strip("_")
        check(
            f"known_post_split_memphis_{slug}",
            (normalize(name), expected_date) in known_lookup,
            f"expected={name}@{expected_date}",
        )

    check(
        "at_least_one_current_roster_post_split_transaction_detected",
        bool(current_arrival_candidates),
        f"candidates={len(current_arrival_candidates)}",
    )
    check(
        "post_split_events_are_audit_only",
        all(not row["event_imported_into_simulator"] for row in matched_rows),
        "No NBA movement row mutates simulator state.",
    )
    check(
        "live_state_unchanged",
        state_digest_before == state_digest_after,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash == checkpoint_after,
        checkpoint_after,
    )

    failed = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Post-Split Roster Provenance Audit V1.0.2 failed strict checks: "
            + ", ".join(failed)
        )

    by_team = Counter(
        row["current_checkpoint_team"]
        for row in current_arrival_candidates
        if clean(row["current_checkpoint_team"])
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_post_split_roster_provenance_audit_v1_0_2_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    export_dir = Path(tempfile.mkdtemp(prefix="fa_postsplit101_")) / export_id
    export_dir.mkdir(parents=True, exist_ok=True)

    try:
        write_csv(export_dir / "current_checkpoint_roster.csv", current_roster_rows)
        write_csv(export_dir / "player_movement_source_attempts.csv", attempts)
        write_csv(export_dir / "player_movement_rows_canonical.csv", movement_rows)
        write_csv(export_dir / "player_movement_post_split.csv", post_split_rows)
        write_csv(export_dir / "post_split_checkpoint_player_matches.csv", matched_rows)
        write_csv(
            export_dir / "current_roster_post_split_transaction_candidates.csv",
            current_arrival_candidates,
        )
        write_csv(export_dir / "roster_provenance_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "checkpoint_sha256": checkpoint_hash,
            "source_url": source_url,
            "source_sha256": sha256_bytes(source_body),
            "player_movement_row_count": len(movement_rows),
            "dated_movement_row_count": len(valid_dated),
            "post_split_movement_row_count": len(post_split_rows),
            "matched_checkpoint_player_event_count": len(matched_rows),
            "current_roster_post_split_transaction_candidate_count": (
                len(current_arrival_candidates)
            ),
            "current_roster_post_split_candidates_by_team": dict(sorted(by_team.items())),
            "known_memphis_cases": known_memphis,
            "source_parser_hotfix_reason": (
                "NBA transactions webpage is client-rendered in the raw urllib "
                "response. V1.0.2 uses the NBA-hosted Player Movement JSON feed "
                "instead of scraping rendered page text and includes the missing "
                "tempfile import needed to export the audit package."
            ),
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Use the post-split movement map to build a league-wide April-12 "
                "branch roster reconstruction preview. Do not mutate the checkpoint "
                "until every removal/restoration has transaction provenance."
            ),
        }
        (export_dir / "roster_provenance_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export_dir / "README.txt").write_text(
            """2026 POST-SPLIT ROSTER PROVENANCE AUDIT V1.0.1

V1 fetched the NBA transactions webpage successfully but parsed zero
transactions because the transaction list is rendered client-side and is not
present in urllib's raw HTML response.

V1.0.1 uses the NBA-hosted Player Movement JSON feed instead.

Matching order:
1. NBA player ID
2. unique Unicode-normalized player name fallback

Every movement after April 12, 2026 is audit-only.

Strict known cases:
- Jerami Grant -> MEM, 2026-06-29
- D'Angelo Russell -> MEM, 2026-07-08
- AJ Johnson -> MEM, 2026-07-08
- Isaiah Stewart -> MEM, 2026-07-08
- Quinten Post -> MEM, 2026-07-08

No state mutation.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export_dir.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")
            archive.writestr(
                f"{export_id}/snapshots/NBA_Player_Movement.json",
                source_body,
                compress_type=zipfile.ZIP_DEFLATED,
            )
    finally:
        import shutil as _shutil
        _shutil.rmtree(export_dir.parent, ignore_errors=True)

    if object_digest(state) != state_digest_before:
        raise RuntimeError("Live state changed after provenance export.")
    if sha256_file(checkpoint_path) != checkpoint_hash:
        raise RuntimeError("Checkpoint changed after provenance export.")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 POST-SPLIT ROSTER PROVENANCE AUDIT V1.0.1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Player Movement rows:                    {len(movement_rows)}", flush=True)
    print(f"Post-split movement rows:                {len(post_split_rows)}", flush=True)
    print(f"Matched checkpoint player events:        {len(matched_rows)}", flush=True)
    print(
        f"Current-roster post-split candidates:    {len(current_arrival_candidates)}",
        flush=True,
    )
    print("Candidates by current checkpoint team:", flush=True)
    for team_code, count in sorted(by_team.items()):
        print(f"  {team_code}: {count}", flush=True)
    print("State mutation: NOT PERFORMED", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
