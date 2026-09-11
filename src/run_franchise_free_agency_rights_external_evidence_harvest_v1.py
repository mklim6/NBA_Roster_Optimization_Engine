from __future__ import annotations

import csv
import gzip
import hashlib
import html
import io
import json
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

VERSION = "franchise-free-agency-rights-external-evidence-harvest-v1-2026-08-14"
SEASON_LABEL = "2026-27"
PRIOR_SEASON = "2025-26"
EXPECTED_UNRESOLVED = 161
BASE = "https://www.salaryswish.com"
TRANSACTION_URL = BASE + "/transactions/players/{slug}"
PLAYER_URL = BASE + "/players/{slug}"
OFFICIAL_CBA_EXPLAINER = "https://www.nba.com/news/free-agency-explained"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2}$"
)
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")

TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._in_row = False
        self._current_row: list[str] = []
        self._in_cell = False
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
        elif self._table_depth == 1 and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._table_depth == 1 and self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
        elif self._in_cell and tag == "br":
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._table_depth == 1 and self._in_row and tag in {"td", "th"}:
            text = " ".join("".join(self._cell_parts).split())
            self._current_row.append(text)
            self._in_cell = False
            self._cell_parts = []
        elif self._table_depth == 1 and tag == "tr":
            if self._current_table is not None and any(self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif tag == "table" and self._table_depth:
            if self._table_depth == 1 and self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None
            self._table_depth -= 1

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
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'")
    text = text.lower()
    text = re.sub(r"['.]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def slug_candidates(name: str) -> list[str]:
    base = slugify(name)
    candidates = [base]

    # Some sites drop suffix punctuation but keep suffix tokens.
    suffixless = re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base)
    if suffixless != base:
        candidates.append(suffixless)

    # Common normalized-name variants.
    candidates.append(base.replace("-j-r-", "-jr-"))
    candidates.append(base.replace("-d-j-", "-dj-"))
    candidates.append(base.replace("-a-j-", "-aj-"))

    result: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip("-")
        if candidate and candidate not in result:
            result.append(candidate)
    return result

def fetch(url: str, timeout: int = 25) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return int(getattr(response, "status", 200)), body, ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return int(exc.code), body, f"HTTPError: {exc}"
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}: {exc}"

def fetch_with_slug_candidates(
    template: str,
    player_name: str,
    sleep_seconds: float,
) -> tuple[str, str, int, bytes, str]:
    last = ("", "", 0, b"", "")
    for slug in slug_candidates(player_name):
        url = template.format(slug=slug)
        status, body, error = fetch(url)
        last = (slug, url, status, body, error)
        if status == 200 and body:
            text = body.decode("utf-8", errors="ignore").lower()
            # Guard against soft-404 pages.
            if "page not found" not in text and "404" not in text[:1000]:
                return last
        time.sleep(sleep_seconds)
    return last

def parse_tables(body: bytes) -> list[list[list[str]]]:
    parser = TableParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    return parser.tables

def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", cell.lower()).strip("_")
        for cell in row
    ]

def parse_transaction_rows(
    body: bytes,
    player_id: str,
    player_name: str,
    url: str,
    body_sha: str,
) -> list[dict[str, Any]]:
    tables = parse_tables(body)
    output: list[dict[str, Any]] = []

    for table in tables:
        header_index = None
        header = []
        for i, row in enumerate(table[:8]):
            normalized = normalize_header(row)
            if "transaction" in normalized and "team" in normalized and "player" in normalized:
                header_index = i
                header = normalized
                break
        if header_index is None:
            continue

        try:
            team_idx = header.index("team")
            player_idx = header.index("player")
            tx_idx = header.index("transaction")
        except ValueError:
            continue

        rights_idx = (
            header.index("rights_acquired")
            if "rights_acquired" in header
            else None
        )
        current_date = ""

        for row in table[header_index + 1:]:
            if not row:
                continue

            # Date separator rows commonly have one meaningful cell.
            if DATE_RE.match(row[0]):
                current_date = row[0]
                if len(row) == 1:
                    continue
                row = row[1:]

            # Some layouts prepend the date as its own column.
            if row and DATE_RE.match(row[0]):
                current_date = row[0]
                row = row[1:]

            if len(row) <= max(team_idx, player_idx, tx_idx):
                continue

            team_name = clean(row[team_idx])
            listed_player = clean(row[player_idx])
            transaction = clean(row[tx_idx])
            rights_acquired_text = (
                clean(row[rights_idx])
                if rights_idx is not None and rights_idx < len(row)
                else ""
            )

            if not team_name or not listed_player or not transaction:
                continue

            output.append({
                "player_id": player_id,
                "player_name": player_name,
                "transaction_date_text": current_date,
                "team_name": team_name,
                "team_abbreviation": TEAM_NAME_TO_ABBR.get(team_name, ""),
                "listed_player_text": listed_player,
                "transaction": transaction,
                "rights_acquired_marker": bool(rights_acquired_text),
                "rights_acquired_text": rights_acquired_text,
                "source_name": "SalarySwish player transaction ledger",
                "source_url": url,
                "source_sha256": body_sha,
            })

    # Deduplicate identical parsed rows.
    seen = set()
    deduped = []
    for row in output:
        key = (
            row["transaction_date_text"],
            row["team_name"],
            row["transaction"],
            row["rights_acquired_marker"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped

def parse_prior_salary_rows(
    body: bytes,
    player_id: str,
    player_name: str,
    url: str,
    body_sha: str,
) -> list[dict[str, Any]]:
    tables = parse_tables(body)
    output: list[dict[str, Any]] = []

    for table_index, table in enumerate(tables):
        header_index = None
        header = []
        for i, row in enumerate(table[:6]):
            normalized = normalize_header(row)
            if "season" in normalized and (
                "base_salary" in normalized or "cap_hit" in normalized
            ):
                header_index = i
                header = normalized
                break
        if header_index is None:
            continue

        for row in table[header_index + 1:]:
            if not row or clean(row[0]) != PRIOR_SEASON:
                continue
            record: dict[str, Any] = {
                "player_id": player_id,
                "player_name": player_name,
                "season": PRIOR_SEASON,
                "source_name": "SalarySwish player contract ledger",
                "source_url": url,
                "source_sha256": body_sha,
                "table_index": table_index,
            }
            for col_index, column_name in enumerate(header):
                if col_index < len(row):
                    record[column_name or f"column_{col_index}"] = clean(row[col_index])

            base_salary_text = clean(record.get("base_salary"))
            cap_hit_text = clean(record.get("cap_hit"))
            record["base_salary_numeric"] = money_to_number(base_salary_text)
            record["cap_hit_numeric"] = money_to_number(cap_hit_text)
            output.append(record)

    # Deduplicate rows that appear more than once in page layout.
    seen = set()
    deduped = []
    for row in output:
        key = (
            row.get("season"),
            row.get("base_salary"),
            row.get("cap_hit"),
            row.get("option"),
            row.get("guaranteed"),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped

def money_to_number(value: Any) -> float | None:
    text = clean(value)
    match = MONEY_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace("$", "").replace(",", ""))
    except ValueError:
        return None

def relevant_transaction_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relevant = []
    for row in rows:
        date_text = clean(row.get("transaction_date_text"))
        try:
            parsed = datetime.strptime(date_text, "%b %d, %Y").date()
        except Exception:
            continue
        if datetime(2023, 7, 1).date() <= parsed <= datetime(2026, 8, 14).date():
            relevant.append(row)
    return relevant

def population_zip(root: Path) -> Path:
    candidates = [
        path for path in root.rglob(
            "franchise_free_agency_rights_population_*.zip"
        )
        if path.is_file()
        and "provenance" not in path.name.lower()
        and "external_evidence" not in path.name.lower()
    ]
    if not candidates:
        raise RuntimeError(
            "Could not locate franchise_free_agency_rights_population_*.zip."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_unresolved(zip_path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        summary_name = next(
            n for n in names if n.endswith("rights_population_summary.json")
        )
        unresolved_name = next(
            n for n in names if n.endswith("rights_population_unresolved.csv")
        )
        summary = json.loads(
            archive.read(summary_name).decode("utf-8-sig")
        )
        unresolved = list(
            csv.DictReader(
                io.StringIO(
                    archive.read(unresolved_name).decode("utf-8-sig")
                )
            )
        )
        return summary, unresolved

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return (
            root
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        )

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
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
    pop_zip = population_zip(root)
    population_summary, unresolved = read_unresolved(pop_zip)

    checkpoint = checkpoint_path(root)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS EXTERNAL EVIDENCE HARVEST V1", flush=True)
    print("=" * 124, flush=True)
    print(f"Population input: {pop_zip}", flush=True)
    print(f"Unresolved target: {len(unresolved)} players", flush=True)
    print(
        "Source strategy: SalarySwish transaction + contract ledgers; "
        "NBA.com official CBA explainer retained as rule anchor.",
        flush=True,
    )
    print(
        "This run harvests evidence only. It does NOT classify Bird rights.",
        flush=True,
    )
    print("", flush=True)

    if len(unresolved) != EXPECTED_UNRESOLVED:
        raise RuntimeError(
            f"Expected {EXPECTED_UNRESOLVED} unresolved players, found "
            f"{len(unresolved)}."
        )

    all_transactions: list[dict[str, Any]] = []
    all_salary_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []

    sleep_seconds = 0.55

    for index, player in enumerate(unresolved, start=1):
        player_id = pid(player.get("player_id"))
        player_name = clean(player.get("player_name"))
        print(
            f"[{index:03d}/{len(unresolved):03d}] {player_name} ({player_id})",
            flush=True,
        )

        tx_slug, tx_url, tx_status, tx_body, tx_error = (
            fetch_with_slug_candidates(
                TRANSACTION_URL,
                player_name,
                sleep_seconds,
            )
        )
        tx_sha = sha256_bytes(tx_body) if tx_body else ""
        tx_rows = (
            parse_transaction_rows(
                tx_body,
                player_id,
                player_name,
                tx_url,
                tx_sha,
            )
            if tx_status == 200 and tx_body
            else []
        )
        tx_relevant = relevant_transaction_rows(tx_rows)
        all_transactions.extend(tx_relevant)

        time.sleep(sleep_seconds)

        salary_slug, salary_url, salary_status, salary_body, salary_error = (
            fetch_with_slug_candidates(
                PLAYER_URL,
                player_name,
                sleep_seconds,
            )
        )
        salary_sha = sha256_bytes(salary_body) if salary_body else ""
        salary_rows = (
            parse_prior_salary_rows(
                salary_body,
                player_id,
                player_name,
                salary_url,
                salary_sha,
            )
            if salary_status == 200 and salary_body
            else []
        )
        all_salary_rows.extend(salary_rows)

        tx_status_label = (
            "parsed"
            if tx_relevant
            else (
                "page_fetched_no_relevant_rows"
                if tx_status == 200
                else "fetch_failed"
            )
        )
        salary_status_label = (
            "single_2025_26_salary_row"
            if len(salary_rows) == 1
            else (
                "multiple_2025_26_salary_rows"
                if len(salary_rows) > 1
                else (
                    "page_fetched_no_2025_26_salary"
                    if salary_status == 200
                    else "fetch_failed"
                )
            )
        )

        player_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "v1_prior_team": clean(player.get("prior_team")).upper(),
            "v1_same_team_streak": clean(
                player.get("continuous_qualifying_seasons")
            ),
            "years_of_service": clean(player.get("years_of_service")),
            "observed_seasons": clean(player.get("observed_seasons")),
            "observed_teams": clean(player.get("observed_teams")),
            "transaction_slug_used": tx_slug,
            "transaction_source_url": tx_url,
            "transaction_http_status": tx_status,
            "transaction_fetch_error": tx_error,
            "transaction_rows_2023_07_01_forward": len(tx_relevant),
            "transaction_evidence_status": tx_status_label,
            "contract_slug_used": salary_slug,
            "contract_source_url": salary_url,
            "contract_http_status": salary_status,
            "contract_fetch_error": salary_error,
            "salary_rows_2025_26": len(salary_rows),
            "prior_salary_evidence_status": salary_status_label,
            "needs_manual_transaction_research": not bool(tx_relevant),
            "needs_manual_salary_research": len(salary_rows) != 1,
            "rights_classification_performed": False,
            "research_complete": bool(tx_relevant) and len(salary_rows) == 1,
        })

        snapshot_rows.extend([
            {
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "transaction",
                "url": tx_url,
                "http_status": tx_status,
                "body_sha256": tx_sha,
                "body_bytes": len(tx_body),
                "slug_used": tx_slug,
                "fetch_error": tx_error,
            },
            {
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "contract",
                "url": salary_url,
                "http_status": salary_status,
                "body_sha256": salary_sha,
                "body_bytes": len(salary_body),
                "slug_used": salary_slug,
                "fetch_error": salary_error,
            },
        ])

        time.sleep(sleep_seconds)

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    transaction_players = {
        row["player_id"] for row in all_transactions
    }
    salary_players = {
        row["player_id"] for row in all_salary_rows
    }
    research_complete_players = {
        row["player_id"]
        for row in player_rows
        if row["research_complete"]
    }

    strict_checks: list[dict[str, Any]] = []
    def add_check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        strict_checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })

    target_ids = {pid(row.get("player_id")) for row in unresolved}
    exported_ids = {row["player_id"] for row in player_rows}

    add_check(
        "target_count_is_161",
        len(unresolved) == EXPECTED_UNRESOLVED,
        "Exact V1 unresolved population retained.",
    )
    add_check(
        "target_player_ids_are_unique",
        len(target_ids) == EXPECTED_UNRESOLVED,
        "One unique player ID per unresolved candidate.",
    )
    add_check(
        "exported_player_ids_match_target",
        exported_ids == target_ids,
        "Evidence summary contains exactly the V1 unresolved IDs.",
    )
    add_check(
        "no_rights_classification_is_performed",
        all(not row["rights_classification_performed"] for row in player_rows),
        "Harvester gathers evidence only.",
    )
    add_check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "Checkpoint remains byte-for-byte unchanged.",
    )
    add_check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "Runtime rights overlay remains untouched.",
    )
    add_check(
        "fetched_transaction_pages_have_fingerprints",
        all(
            row["http_status"] != 200 or bool(row["body_sha256"])
            for row in snapshot_rows
            if row["source_kind"] == "transaction"
        ),
        "Every successful transaction fetch is fingerprinted.",
    )
    add_check(
        "fetched_contract_pages_have_fingerprints",
        all(
            row["http_status"] != 200 or bool(row["body_sha256"])
            for row in snapshot_rows
            if row["source_kind"] == "contract"
        ),
        "Every successful contract fetch is fingerprinted.",
    )

    # Coverage metrics are intentionally informational, not safety gates.
    add_check(
        "transaction_evidence_coverage",
        len(transaction_players) == EXPECTED_UNRESOLVED,
        f"Parsed transaction evidence for {len(transaction_players)}/{EXPECTED_UNRESOLVED} players.",
        severity="coverage",
    )
    add_check(
        "prior_salary_evidence_coverage",
        len(salary_players) == EXPECTED_UNRESOLVED,
        f"Parsed at least one {PRIOR_SEASON} salary row for {len(salary_players)}/{EXPECTED_UNRESOLVED} players.",
        severity="coverage",
    )
    add_check(
        "single_salary_row_and_transaction_ready",
        len(research_complete_players) == EXPECTED_UNRESOLVED,
        f"Fully machine-harvested evidence for {len(research_complete_players)}/{EXPECTED_UNRESOLVED} players.",
        severity="coverage",
    )

    failed_strict = [
        row["check_id"]
        for row in strict_checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "External evidence harvest failed strict safety checks: "
            + ", ".join(failed_strict)
        )

    print("", flush=True)
    print("HARVEST SUMMARY", flush=True)
    print(
        f"  Transaction evidence: {len(transaction_players)}/{EXPECTED_UNRESOLVED}",
        flush=True,
    )
    print(
        f"  2025-26 salary evidence: {len(salary_players)}/{EXPECTED_UNRESOLVED}",
        flush=True,
    )
    print(
        f"  Fully machine-harvested: {len(research_complete_players)}/{EXPECTED_UNRESOLVED}",
        flush=True,
    )

    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"franchise_free_agency_rights_external_evidence_"
        f"{SEASON_LABEL}_{stamp}"
    )
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(
        prefix="fa_rights_external_evidence_"
    ) as tmp:
        export = Path(tmp) / export_id
        export.mkdir(parents=True, exist_ok=True)

        write_csv(
            export / "rights_external_evidence_player_summary.csv",
            player_rows,
        )
        write_csv(
            export / "rights_external_transaction_rows.csv",
            all_transactions,
        )
        write_csv(
            export / "rights_external_prior_salary_rows.csv",
            all_salary_rows,
        )
        write_csv(
            export / "rights_external_source_snapshots.csv",
            snapshot_rows,
        )
        write_csv(
            export / "rights_external_evidence_checks.csv",
            strict_checks,
        )

        manual_queue = [
            row for row in player_rows
            if row["needs_manual_transaction_research"]
            or row["needs_manual_salary_research"]
        ]
        write_csv(
            export / "rights_external_manual_research_queue.csv",
            manual_queue,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "prior_salary_season": PRIOR_SEASON,
            "input_population_zip": str(pop_zip),
            "input_population_sha256": sha256_file(pop_zip),
            "input_population_version": clean(
                population_summary.get("version")
            ),
            "target_players": EXPECTED_UNRESOLVED,
            "transaction_evidence_players": len(transaction_players),
            "prior_salary_evidence_players": len(salary_players),
            "fully_machine_harvested_players": len(
                research_complete_players
            ),
            "manual_research_queue_players": len(manual_queue),
            "transaction_rows_exported": len(all_transactions),
            "prior_salary_rows_exported": len(all_salary_rows),
            "official_rule_anchor_url": OFFICIAL_CBA_EXPLAINER,
            "evidence_source": "SalarySwish",
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "classification_changes_performed": 0,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "failed_strict_checks": failed_strict,
            "passed": not failed_strict,
            "important_boundary": (
                "Parsed transaction and salary rows are evidence inputs only. "
                "They are not Bird/Early Bird/Non-Bird determinations. "
                "A separate CBA-aware resolver must review continuity-breaking "
                "free-agent signings, waivers that cleared, qualifying trades/"
                "waiver assignments, two-way/standard-contract context, and "
                "the actual rights-holder team."
            ),
        }
        (export / "rights_external_evidence_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = f"""FREE AGENCY RIGHTS EXTERNAL EVIDENCE HARVEST V1

This export contains web-harvested evidence for the {EXPECTED_UNRESOLVED}
players left unresolved by Verified Bird-Rights Population V1.

Sources:
- SalarySwish player transaction ledgers
- SalarySwish player contract ledgers
- NBA.com Free Agency Explained is retained as the official rule anchor:
  {OFFICIAL_CBA_EXPLAINER}

This export DOES NOT classify any player's rights.

Important:
A transaction row marked "RIGHTS ACQUIRED" is evidence, not by itself a
final CBA determination. The next resolver must reconstruct the qualifying
continuity chain and determine the actual rights-holder team, especially
where a player was traded and then waived, cleared waivers and signed
elsewhere, or moved between two-way and standard contracts.

Files:
- rights_external_evidence_player_summary.csv
- rights_external_transaction_rows.csv
- rights_external_prior_salary_rows.csv
- rights_external_source_snapshots.csv
- rights_external_manual_research_queue.csv
- rights_external_evidence_checks.csv
- rights_external_evidence_summary.json

Safety:
- no franchise checkpoint write
- no rights overlay write
- no roster, contract, trade, or signing mutation
- no Bird-rights classification change
"""
        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(
            zip_out,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError(
            "Checkpoint changed after export."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed after export."
        )

    print("", flush=True)
    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS EXTERNAL EVIDENCE HARVEST V1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Rights classifications changed: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
