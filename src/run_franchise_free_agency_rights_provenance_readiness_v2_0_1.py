from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

RUNNER_VERSION = "franchise-free-agency-rights-provenance-readiness-v2.0.1-2026-08-14"
EXPECTED_POPULATION_PREFIX = "franchise-free-agency-verified-bird-rights-population-v1-"
STRUCTURED_EXTENSIONS = {".csv", ".parquet", ".json", ".jsonl"}
SCAN_DIRS = ("data", "evidence", "outputs")

EXCLUDED_TOKENS = (
    "\\backups\\", "/backups/",
    "\\.git\\", "/.git/",
    "\\.venv\\", "/.venv/",
    "\\site-packages\\", "/site-packages/",
    "\\outputs\\audits\\", "/outputs/audits/",
    "\\free_agency_rights_population_recovery\\",
    "/free_agency_rights_population_recovery/",
)

PLAYER_ID_ALIASES = {
    "player_id", "nba_player_id", "person_id", "personid", "playerid",
}
PLAYER_NAME_ALIASES = {
    "player_name", "player_display_name", "display_name", "player",
}
SEASON_ALIASES = {
    "season", "season_label", "season_year", "league_year", "year",
}

# IMPORTANT: these are exact semantic aliases, not substring patterns.
EVENT_DATE_ALIASES = {
    "transaction_date", "trade_date",
    "acquisition_date", "acquired_date",
    "signing_date", "signed_date",
    "waiver_date", "waived_date",
    "claim_date", "claimed_date",
    "event_date", "effective_date",
}
EVENT_TYPE_ALIASES = {
    "transaction_type", "event_type", "action_type", "move_type",
    "acquisition_type", "signing_type", "waiver_type",
}
FROM_TEAM_ALIASES = {
    "from_team", "old_team", "previous_team", "prior_team",
    "sending_team", "source_team", "originating_team", "team_from",
}
TO_TEAM_ALIASES = {
    "to_team", "new_team", "destination_team", "acquiring_team",
    "receiving_team", "team_to",
}
DESCRIPTION_ALIASES = {
    "transaction_description", "transaction_text", "event_description",
    "description", "details", "evidence_summary", "notes",
}
SOURCE_URL_ALIASES = {
    "primary_source_url", "secondary_source_url", "authoritative_source_url",
    "source_url", "url",
}

# Explicit salary aliases. Generic words like "salary_data_scope_note" are not salary amounts.
GENERIC_SALARY_ALIASES = {
    "salary", "base_salary", "regular_salary", "annual_salary",
    "salary_amount", "cap_hit", "current_salary",
}
PRIOR_SALARY_EXACT_ALIASES = {
    "prior_regular_salary", "prior_salary", "previous_salary",
    "prior_season_salary", "previous_season_salary",
}

TRANSACTION_FILENAME_TOKENS = (
    "transaction", "transactions", "signing", "signings", "waiver", "waivers",
    "acquisition", "acquisitions", "roster_move", "roster_moves",
    "player_movement", "movement_history", "transaction_history",
)
SALARY_FILENAME_TOKENS = (
    "salary", "contract", "payroll", "financial",
)

TEAM_RE = re.compile(r"^[A-Z]{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEASON_RE = re.compile(r"^(20\d{2})[-_](\d{2}|20\d{2})$")

def clean(value: Any) -> str:
    return str(value or "").strip()

def norm_col(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def first_exact(columns: list[str], aliases: set[str]) -> str:
    normalized = {norm_col(c): c for c in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return ""

def exact_matches(columns: list[str], aliases: set[str]) -> list[str]:
    return [c for c in columns if norm_col(c) in aliases]

def season_salary_columns(columns: list[str]) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for c in columns:
        n = norm_col(c)
        m = re.fullmatch(r"(?:salary|base_salary|regular_salary|cap_hit)_(20\d{2})_(\d{2}|20\d{2})", n)
        if m:
            results.append((c, int(m.group(1))))
    return results

def path_excluded(path: Path) -> bool:
    text = str(path).lower()
    return any(token.lower() in text for token in EXCLUDED_TOKENS)

def csv_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    last = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                cols = [clean(c) for c in (reader.fieldnames or []) if clean(c)]
                rows = []
                for i, row in enumerate(reader):
                    rows.append(row)
                    if limit is not None and i + 1 >= limit:
                        break
                return cols, rows
        except UnicodeDecodeError as exc:
            last = exc
            continue
        except Exception:
            return [], []
    return [], []

def parquet_rows(path: Path, columns: list[str] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        import pandas as pd
        frame = pd.read_parquet(path, columns=columns)
        return list(frame.columns), frame.to_dict("records")
    except Exception:
        return [], []

def json_rows(path: Path, limit: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        if path.suffix.lower() == ".jsonl":
            rows = []
            with path.open("r", encoding="utf-8-sig") as handle:
                for line in handle:
                    if line.strip():
                        obj = json.loads(line)
                        if isinstance(obj, Mapping):
                            rows.append(dict(obj))
                    if limit is not None and len(rows) >= limit:
                        break
            cols = sorted({str(k) for row in rows for k in row})
            return cols, rows

        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = obj if isinstance(obj, list) else None
        if rows is None and isinstance(obj, Mapping):
            for key in ("rows", "records", "data", "transactions", "players", "history"):
                if isinstance(obj.get(key), list):
                    rows = obj[key]
                    break
        if not rows:
            return (list(obj.keys()) if isinstance(obj, Mapping) else []), []
        mapped = [dict(r) for r in rows if isinstance(r, Mapping)]
        if limit is not None:
            mapped = mapped[:limit]
        cols = sorted({str(k) for row in mapped for k in row})
        return cols, mapped
    except Exception:
        return [], []

def load_rows(path: Path, columns: list[str] | None = None, limit: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return csv_rows(path, limit=limit)
    if suffix == ".parquet":
        return parquet_rows(path, columns=columns)
    if suffix in {".json", ".jsonl"}:
        return json_rows(path, limit=limit)
    return [], []

def header_only(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        cols, _ = csv_rows(path, limit=0)
        return cols
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
            return list(pq.ParquetFile(path).schema.names)
        except Exception:
            cols, _ = parquet_rows(path)
            return cols
    if suffix in {".json", ".jsonl"}:
        cols, _ = json_rows(path, limit=5)
        return cols
    return []

def parse_season_start(value: Any) -> int | None:
    text = clean(value).replace("/", "-")
    m = re.match(r"^(20\d{2})", text)
    if not m:
        return None
    return int(m.group(1))

def is_date_like(value: Any) -> bool:
    text = clean(value)
    if not text:
        return False
    if DATE_RE.match(text):
        return True
    try:
        from datetime import date
        date.fromisoformat(text[:10])
        return True
    except Exception:
        return False

def is_team_like(value: Any) -> bool:
    return bool(TEAM_RE.match(clean(value).upper()))

def is_numeric_like(value: Any) -> bool:
    text = clean(value).replace(",", "").replace("$", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False

def read_population(zip_path: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        def member(suffix: str) -> str:
            found = next((n for n in names if n.endswith(suffix)), "")
            if not found:
                raise RuntimeError(f"Population ZIP missing {suffix}")
            return found
        summary = json.loads(archive.read(member("rights_population_summary.json")).decode("utf-8-sig"))
        unresolved = list(csv.DictReader(io.StringIO(
            archive.read(member("rights_population_unresolved.csv")).decode("utf-8-sig")
        )))
        proven = list(csv.DictReader(io.StringIO(
            archive.read(member("rights_population_proven.csv")).decode("utf-8-sig")
        )))
        return summary, unresolved, proven

def find_population_zip(root: Path) -> Path:
    candidates = [
        p for p in root.rglob("franchise_free_agency_rights_population_*.zip")
        if p.is_file() and "provenance" not in p.name.lower()
    ]
    if not candidates:
        raise RuntimeError("Could not locate franchise_free_agency_rights_population_*.zip.")
    return max(candidates, key=lambda p: p.stat().st_mtime)

@dataclass(frozen=True)
class SourceRow:
    path: str
    extension: str
    size_bytes: int
    player_id_column: str
    player_name_column: str
    season_column: str
    event_date_column: str
    event_type_column: str
    from_team_column: str
    to_team_column: str
    description_column: str
    source_url_column: str
    prior_salary_columns: str
    current_or_future_salary_columns: str
    transaction_schema_status: str
    transaction_value_validation: str
    prior_salary_schema_status: str
    prior_salary_value_validation: str
    unresolved_players_with_transaction_rows: int
    unresolved_players_with_prior_salary_rows: int
    filename_transaction_signal: bool
    filename_salary_signal: bool
    source_fingerprint: str

def validate_transaction_values(
    path: Path,
    id_col: str,
    date_col: str,
    from_col: str,
    to_col: str,
    type_col: str,
    desc_col: str,
    unresolved_ids: set[str],
) -> tuple[str, set[str]]:
    needed = [c for c in (id_col, date_col, from_col, to_col, type_col, desc_col) if c]
    if not needed:
        return "not_applicable", set()
    cols, rows = load_rows(path, columns=needed)
    if not rows:
        return "no_rows_read", set()

    relevant = [r for r in rows if pid(r.get(id_col)) in unresolved_ids]
    if not relevant:
        return "no_unresolved_player_rows", set()

    valid_ids: set[str] = set()
    for row in relevant:
        date_ok = is_date_like(row.get(date_col))
        from_ok = is_team_like(row.get(from_col))
        to_ok = is_team_like(row.get(to_col))
        event_ok = bool(clean(row.get(type_col)) or clean(row.get(desc_col)))
        if date_ok and from_ok and to_ok and event_ok:
            valid_ids.add(pid(row.get(id_col)))

    if len(valid_ids) == len({pid(r.get(id_col)) for r in relevant}):
        return "all_relevant_rows_structurally_valid", valid_ids
    if valid_ids:
        return "some_relevant_rows_structurally_valid", valid_ids
    return "no_structurally_valid_transaction_rows", set()

def validate_prior_salary_values(
    path: Path,
    id_col: str,
    season_col: str,
    prior_exact_cols: list[str],
    season_salary_cols: list[tuple[str, int]],
    generic_salary_col: str,
    unresolved_ids: set[str],
    current_season_start: int,
) -> tuple[str, set[str]]:
    needed = [id_col]
    if season_col:
        needed.append(season_col)
    needed += prior_exact_cols
    needed += [c for c, _ in season_salary_cols]
    if generic_salary_col:
        needed.append(generic_salary_col)
    needed = list(dict.fromkeys(c for c in needed if c))
    if not needed:
        return "not_applicable", set()

    _, rows = load_rows(path, columns=needed)
    if not rows:
        return "no_rows_read", set()

    valid_ids: set[str] = set()
    for row in rows:
        player = pid(row.get(id_col))
        if player not in unresolved_ids:
            continue

        # Explicit prior salary fields are acceptable if numeric.
        if any(is_numeric_like(row.get(c)) for c in prior_exact_cols):
            valid_ids.add(player)
            continue

        # Wide prior-season salary columns must precede 2026-27.
        if any(
            season_start < current_season_start and is_numeric_like(row.get(c))
            for c, season_start in season_salary_cols
        ):
            valid_ids.add(player)
            continue

        # Long-form salary requires a prior season row.
        if season_col and generic_salary_col:
            season_start = parse_season_start(row.get(season_col))
            if (
                season_start is not None
                and season_start < current_season_start
                and is_numeric_like(row.get(generic_salary_col))
            ):
                valid_ids.add(player)

    if valid_ids:
        return "verified_prior_salary_rows_found", valid_ids
    return "no_verified_prior_salary_rows", set()

def main() -> int:
    root = Path.cwd().resolve()
    pop_zip = find_population_zip(root)
    summary, unresolved, proven = read_population(pop_zip)
    unresolved_ids = {pid(r.get("player_id")) for r in unresolved if pid(r.get("player_id"))}
    season_label = clean(summary.get("season_label")) or "2026-27"
    current_start = parse_season_start(season_label) or 2026

    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        checkpoint_path = root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

    overlay_path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256(checkpoint_path)
    overlay_before = sha256(overlay_path)

    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS PROVENANCE READINESS V2.0.1", flush=True)
    print("=" * 124, flush=True)
    print("[1/6] Loading reviewed V1 population...", flush=True)
    print(f"      Unresolved players: {len(unresolved_ids)}", flush=True)

    print("[2/6] Scanning structured project files with exact semantic field matching...", flush=True)
    source_rows: list[SourceRow] = []
    tx_coverage_by_player: dict[str, list[str]] = {p: [] for p in unresolved_ids}
    salary_coverage_by_player: dict[str, list[str]] = {p: [] for p in unresolved_ids}

    seen: set[Path] = set()
    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if (
                not path.is_file()
                or path in seen
                or path.suffix.lower() not in STRUCTURED_EXTENSIONS
                or path_excluded(path)
            ):
                continue
            seen.add(path)
            columns = header_only(path)
            if not columns:
                continue

            id_col = first_exact(columns, PLAYER_ID_ALIASES)
            if not id_col:
                continue

            name_col = first_exact(columns, PLAYER_NAME_ALIASES)
            season_col = first_exact(columns, SEASON_ALIASES)
            date_col = first_exact(columns, EVENT_DATE_ALIASES)
            type_col = first_exact(columns, EVENT_TYPE_ALIASES)
            from_col = first_exact(columns, FROM_TEAM_ALIASES)
            to_col = first_exact(columns, TO_TEAM_ALIASES)
            desc_col = first_exact(columns, DESCRIPTION_ALIASES)
            url_col = first_exact(columns, SOURCE_URL_ALIASES)

            prior_exact = exact_matches(columns, PRIOR_SALARY_EXACT_ALIASES)
            wide_salary = season_salary_columns(columns)
            generic_salary = first_exact(columns, GENERIC_SALARY_ALIASES)

            current_future = [
                c for c, start in wide_salary if start >= current_start
            ]
            prior_wide = [
                (c, start) for c, start in wide_salary if start < current_start
            ]

            filename_lower = path.name.lower()
            tx_signal = any(t in filename_lower for t in TRANSACTION_FILENAME_TOKENS)
            salary_signal = any(t in filename_lower for t in SALARY_FILENAME_TOKENS)

            tx_schema = "none"
            if date_col and from_col and to_col and (type_col or desc_col):
                tx_schema = "structured_transaction_schema"
            elif date_col and (type_col or desc_col) and (from_col or to_col):
                tx_schema = "partial_transaction_schema"
            elif tx_signal and (date_col or desc_col or type_col):
                tx_schema = "transaction_candidate_schema"

            prior_salary_schema = "none"
            if prior_exact or prior_wide:
                prior_salary_schema = "explicit_prior_salary_schema"
            elif season_col and generic_salary:
                prior_salary_schema = "long_form_salary_history_schema"
            elif salary_signal and (generic_salary or wide_salary):
                prior_salary_schema = "current_or_future_salary_only_candidate"

            if tx_schema == "none" and prior_salary_schema == "none":
                continue

            tx_validation = "not_applicable"
            tx_ids: set[str] = set()
            if tx_schema == "structured_transaction_schema":
                tx_validation, tx_ids = validate_transaction_values(
                    path, id_col, date_col, from_col, to_col, type_col, desc_col,
                    unresolved_ids,
                )
                for player in tx_ids:
                    tx_coverage_by_player[player].append(str(path.resolve()))

            salary_validation = "not_applicable"
            sal_ids: set[str] = set()
            if prior_salary_schema in {
                "explicit_prior_salary_schema",
                "long_form_salary_history_schema",
            }:
                salary_validation, sal_ids = validate_prior_salary_values(
                    path, id_col, season_col, prior_exact, wide_salary, generic_salary,
                    unresolved_ids, current_start,
                )
                for player in sal_ids:
                    salary_coverage_by_player[player].append(str(path.resolve()))

            source_rows.append(SourceRow(
                path=str(path.resolve()),
                extension=path.suffix.lower().lstrip("."),
                size_bytes=int(path.stat().st_size),
                player_id_column=id_col,
                player_name_column=name_col,
                season_column=season_col,
                event_date_column=date_col,
                event_type_column=type_col,
                from_team_column=from_col,
                to_team_column=to_col,
                description_column=desc_col,
                source_url_column=url_col,
                prior_salary_columns="|".join(
                    prior_exact + [c for c, _ in prior_wide]
                ),
                current_or_future_salary_columns="|".join(current_future),
                transaction_schema_status=tx_schema,
                transaction_value_validation=tx_validation,
                prior_salary_schema_status=prior_salary_schema,
                prior_salary_value_validation=salary_validation,
                unresolved_players_with_transaction_rows=len(tx_ids),
                unresolved_players_with_prior_salary_rows=len(sal_ids),
                filename_transaction_signal=tx_signal,
                filename_salary_signal=salary_signal,
                source_fingerprint=sha256(path),
            ))

    print("[3/6] Building corrected player-level coverage...", flush=True)
    coverage: list[dict[str, Any]] = []
    for row in unresolved:
        player = pid(row.get("player_id"))
        tx = sorted(set(tx_coverage_by_player.get(player, [])))
        sal = sorted(set(salary_coverage_by_player.get(player, [])))
        if tx and sal:
            status = "transaction_and_prior_salary_local"
        elif tx:
            status = "transaction_local_salary_missing"
        elif sal:
            status = "prior_salary_local_transaction_missing"
        else:
            status = "local_provenance_incomplete"

        coverage.append({
            "player_id": player,
            "player_name": clean(row.get("player_name")),
            "prior_team": clean(row.get("prior_team")).upper(),
            "years_of_service": clean(row.get("years_of_service")),
            "v1_same_team_streak": clean(row.get("continuous_qualifying_seasons")),
            "v1_status": clean(row.get("status")),
            "corrected_readiness_status": status,
            "verified_transaction_source_count": len(tx),
            "verified_prior_salary_source_count": len(sal),
            "verified_transaction_sources": "|".join(tx),
            "verified_prior_salary_sources": "|".join(sal),
        })

    tx_players = sum(int(r["verified_transaction_source_count"]) > 0 for r in coverage)
    salary_players = sum(int(r["verified_prior_salary_source_count"]) > 0 for r in coverage)
    both_players = sum(
        int(r["verified_transaction_source_count"]) > 0
        and int(r["verified_prior_salary_source_count"]) > 0
        for r in coverage
    )
    neither_players = sum(
        int(r["verified_transaction_source_count"]) == 0
        and int(r["verified_prior_salary_source_count"]) == 0
        for r in coverage
    )

    coverage.sort(
        key=lambda r: (
            r["corrected_readiness_status"] != "transaction_and_prior_salary_local",
            -int(float(r["v1_same_team_streak"] or 0)),
            -int(float(r["years_of_service"] or 0)),
            r["player_name"].lower(),
        )
    )
    for i, row in enumerate(coverage, start=1):
        row["priority_rank"] = i

    print(f"      Verified transaction-path players: {tx_players}/{len(coverage)}", flush=True)
    print(f"      Verified prior-salary players: {salary_players}/{len(coverage)}", flush=True)
    print(f"      Both locally available: {both_players}/{len(coverage)}", flush=True)
    print(f"      Neither locally verified: {neither_players}/{len(coverage)}", flush=True)

    print("[4/6] Running strict anti-false-positive checks...", flush=True)
    checks: list[dict[str, Any]] = []
    def check(name: str, passed: bool, detail: str):
        checks.append({
            "check_id": name,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"      {name}: {'PASS' if passed else 'FAIL'}", flush=True)

    check(
        "input_population_is_verified_v1",
        clean(summary.get("version")).startswith(EXPECTED_POPULATION_PREFIX),
        "Uses the reviewed V1 population.",
    )
    check(
        "unresolved_count_matches_v1",
        len(unresolved_ids) == int(summary.get("unresolved_count", -1)),
        "Exact V1 unresolved universe preserved.",
    )
    check(
        "no_trade_value_field_used_as_event_date",
        all(
            norm_col(s.event_date_column) not in {
                "old_trade_value", "trade_value", "model_trade_value",
                "trade_value_rating", "trade_salary_2026_27",
            }
            for s in source_rows
        ),
        "Valuation/salary fields may never masquerade as transaction dates.",
    )
    check(
        "no_trade_value_field_used_as_event_type",
        all(
            norm_col(s.event_type_column) not in {
                "old_trade_value", "trade_value", "model_trade_value",
                "trade_value_rating", "trade_salary_2026_27",
            }
            for s in source_rows
        ),
        "Valuation/salary fields may never masquerade as transaction types.",
    )
    check(
        "current_2026_27_salary_not_counted_as_prior_salary",
        all(
            "salary_2026_27" not in s.prior_salary_columns.split("|")
            for s in source_rows
            if s.prior_salary_columns
        ),
        "Current-season salary cannot satisfy prior-regular-salary evidence.",
    )
    check(
        "transaction_coverage_requires_value_validation",
        all(
            s.unresolved_players_with_transaction_rows == 0
            or s.transaction_value_validation in {
                "all_relevant_rows_structurally_valid",
                "some_relevant_rows_structurally_valid",
            }
            for s in source_rows
        ),
        "Transaction coverage is credited only after row-value validation.",
    )
    check(
        "prior_salary_coverage_requires_prior_season_value",
        all(
            s.unresolved_players_with_prior_salary_rows == 0
            or s.prior_salary_value_validation == "verified_prior_salary_rows_found"
            for s in source_rows
        ),
        "Prior salary coverage requires a numeric prior-season value.",
    )

    checkpoint_after = sha256(checkpoint_path)
    overlay_after = sha256(overlay_path)
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "Read-only scan must not touch the durable checkpoint.",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "Read-only scan must not create or alter the V1 rights overlay.",
    )

    failed = [r["check_id"] for r in checks if r["status"] == "FAIL"]
    if failed:
        raise RuntimeError(f"V2.0.1 strict checks failed: {failed}")

    print("[5/6] Exporting corrected readiness audit...", flush=True)
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"franchise_free_agency_rights_provenance_readiness_v2_0_1_{season_label}_{stamp}"
    zip_path = out_dir / f"{export_id}.zip"

    def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        fields: list[str] = []
        seen = set()
        for row in rows:
            for k in row:
                if k not in seen:
                    seen.add(k)
                    fields.append(k)
        with path.open("w", encoding="utf-8-sig", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    with tempfile.TemporaryDirectory(prefix="fa_rights_v201_") as tmp:
        export = Path(tmp) / export_id
        export.mkdir(parents=True)
        write_csv(export / "corrected_source_inventory.csv", [asdict(s) for s in source_rows])
        write_csv(export / "corrected_candidate_coverage.csv", coverage)
        write_csv(export / "corrected_checks.csv", checks)
        (export / "corrected_summary.json").write_text(
            json.dumps({
                "version": RUNNER_VERSION,
                "season_label": season_label,
                "input_population_zip": str(pop_zip),
                "input_population_zip_sha256": sha256(pop_zip),
                "unresolved_count": len(coverage),
                "verified_transaction_path_players": tx_players,
                "verified_prior_salary_players": salary_players,
                "verified_both_players": both_players,
                "verified_neither_players": neither_players,
                "source_count_reviewed": len(source_rows),
                "checkpoint_sha256_before": checkpoint_before,
                "checkpoint_sha256_after": checkpoint_after,
                "rights_overlay_sha256_before": overlay_before,
                "rights_overlay_sha256_after": overlay_after,
                "checkpoint_write_performed": False,
                "overlay_write_performed": False,
                "classification_changes_performed": 0,
                "failed_checks": failed,
                "passed": not failed,
                "note": (
                    "V2.0.1 fixes the V2 false positive where trade-value fields "
                    "were interpreted as transaction dates/types and current-season "
                    "salary was treated as prior salary evidence."
                ),
            }, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(export.iterdir()):
                z.write(p, arcname=f"{export_id}/{p.name}")

    print("[6/6] Final durable-state verification...", flush=True)
    if sha256(checkpoint_path) != checkpoint_before:
        raise RuntimeError("Checkpoint changed during V2.0.1 export.")
    if sha256(overlay_path) != overlay_before:
        raise RuntimeError("Rights overlay changed during V2.0.1 export.")

    print("", flush=True)
    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS PROVENANCE READINESS V2.0.1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Audit ZIP: {zip_path}", flush=True)
    print("Rights classifications changed: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
