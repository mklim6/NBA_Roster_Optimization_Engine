from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

VERSION = "franchise-free-agency-rights-external-evidence-harvest-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
PRIOR_SEASON = "2025-26"
EVIDENCE_CUTOFF_DATE = date(2026, 8, 4)
EXPECTED_UNRESOLVED = 161
BASE = "https://www.salaryswish.com"
TRANSACTION_URL = BASE + "/transactions/players/{slug}"
PLAYER_URL = BASE + "/players/{slug}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

# Known SalarySwish canonical slug/name differences discovered during V1 review.
SLUG_OVERRIDES = {
    "Cameron Payne": ["cam-payne"],
    "Bruce Brown": ["bruce-brown-jr"],
    "Xavier Tillman": ["xavier-tillman-sr"],
    "KJ Simpson": ["k-j-simpson"],
    "Darius Brown II": ["darius-brown"],
    "Trey Jemison III": ["trey-jemison"],
}

NAME_EQUIVALENTS = {
    "cameron payne": {"cam payne"},
    "bruce brown": {"bruce brown jr"},
    "xavier tillman": {"xavier tillman sr"},
    "kj simpson": {"k j simpson"},
    "darius brown ii": {"darius brown"},
    "trey jemison iii": {"trey jemison"},
}

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

class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._in_row = False
        self._current_row: list[str] = []
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    @property
    def h1(self) -> str:
        return " ".join("".join(self._h1_parts).split())

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "table":
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
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif self._table_depth == 1 and self._in_row and tag in {"td", "th"}:
            self._current_row.append(
                " ".join("".join(self._cell_parts).split())
            )
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
    value = clean(value)
    if value.endswith(".0") and value[:-2].isdigit():
        return value[:-2]
    return value

def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(two-way\)", "", text)
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return " ".join(text.split())

def names_equivalent(target: str, listed: str) -> bool:
    a = normalize_name(target)
    b = normalize_name(listed)
    if a == b:
        return True
    if b in NAME_EQUIVALENTS.get(a, set()):
        return True
    if a in NAME_EQUIVALENTS.get(b, set()):
        return True
    return False

def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def slug_candidates(name: str) -> list[str]:
    result: list[str] = []
    for value in SLUG_OVERRIDES.get(name, []):
        if value not in result:
            result.append(value)

    base = slugify(name)
    generic = [
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("dj-", "d-j-"),
    ]
    for value in generic:
        value = value.strip("-")
        if value and value not in result:
            result.append(value)
    return result

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

def fetch(url: str, timeout: int = 25) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
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

def parse_page(body: bytes) -> PageParser:
    parser = PageParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    return parser

def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", clean(cell).lower()).strip("_")
        for cell in row
    ]

def transaction_page_identity(
    parser: PageParser,
    target_name: str,
) -> bool:
    title = normalize_name(parser.title)
    h1 = normalize_name(parser.h1)
    target = normalize_name(target_name)

    if target and (target in title or target in h1):
        return True

    for equivalent in NAME_EQUIVALENTS.get(target, set()):
        if equivalent in title or equivalent in h1:
            return True

    # Final identity proof: at least one PLAYER cell names the target.
    for table in parser.tables:
        for i, row in enumerate(table[:8]):
            header = normalize_header(row)
            if "player" not in header:
                continue
            player_idx = header.index("player")
            for data_row in table[i + 1:]:
                row2 = list(data_row)
                if row2 and DATE_RE.match(clean(row2[0])):
                    row2 = row2[1:]
                if player_idx < len(row2):
                    if names_equivalent(target_name, row2[player_idx]):
                        return True
    return False

def contract_page_identity(
    parser: PageParser,
    target_name: str,
) -> bool:
    title = normalize_name(parser.title)
    h1 = normalize_name(parser.h1)
    target = normalize_name(target_name)
    if target and (target in title or target in h1):
        return True
    return any(
        equivalent in title or equivalent in h1
        for equivalent in NAME_EQUIVALENTS.get(target, set())
    )

def fetch_verified(
    template: str,
    player_name: str,
    kind: str,
    sleep_seconds: float,
) -> tuple[str, str, int, bytes, str, bool]:
    last = ("", "", 0, b"", "", False)
    for slug in slug_candidates(player_name):
        url = template.format(slug=slug)
        status, body, error = fetch(url)
        identity = False
        if status == 200 and body:
            parser = parse_page(body)
            identity = (
                transaction_page_identity(parser, player_name)
                if kind == "transaction"
                else contract_page_identity(parser, player_name)
            )
            if identity:
                return slug, url, status, body, error, True
        last = (slug, url, status, body, error, identity)
        time.sleep(sleep_seconds)
    return last

def parse_transaction_rows(
    body: bytes,
    player_id: str,
    player_name: str,
    url: str,
    body_sha: str,
) -> list[dict[str, Any]]:
    parser = parse_page(body)
    output: list[dict[str, Any]] = []

    for table in parser.tables:
        header_index = None
        header = []
        for i, row in enumerate(table[:8]):
            normalized = normalize_header(row)
            if {"team", "player", "transaction"}.issubset(normalized):
                header_index = i
                header = normalized
                break
        if header_index is None:
            continue

        team_idx = header.index("team")
        player_idx = header.index("player")
        tx_idx = header.index("transaction")
        rights_idx = header.index("rights_acquired") if "rights_acquired" in header else None
        current_date = ""

        for row in table[header_index + 1:]:
            if not row:
                continue
            row = list(row)
            if row and DATE_RE.match(clean(row[0])):
                current_date = clean(row[0])
                row = row[1:]
            if len(row) <= max(team_idx, player_idx, tx_idx):
                continue

            listed_player = clean(row[player_idx])
            if not names_equivalent(player_name, listed_player):
                continue

            try:
                parsed_date = datetime.strptime(current_date, "%b %d, %Y").date()
            except Exception:
                continue

            # Exact canonical evidence cutoff. No future leakage.
            if not (date(2023, 7, 1) <= parsed_date <= EVIDENCE_CUTOFF_DATE):
                continue

            team_name = clean(row[team_idx])
            transaction = clean(row[tx_idx])
            rights_text = (
                clean(row[rights_idx])
                if rights_idx is not None and rights_idx < len(row)
                else ""
            )
            if not team_name or not transaction:
                continue

            output.append({
                "player_id": player_id,
                "player_name": player_name,
                "transaction_date": parsed_date.isoformat(),
                "transaction_date_text": current_date,
                "team_name": team_name,
                "team_abbreviation": TEAM_NAME_TO_ABBR.get(team_name, ""),
                "listed_player_text": listed_player,
                "transaction": transaction,
                "rights_acquired_marker": bool(rights_text),
                "rights_acquired_text": rights_text,
                "source_name": "SalarySwish player transaction ledger",
                "source_url": url,
                "source_sha256": body_sha,
                "evidence_cutoff_date": EVIDENCE_CUTOFF_DATE.isoformat(),
            })

    seen = set()
    deduped = []
    for row in output:
        key = (
            row["transaction_date"],
            row["team_name"],
            row["listed_player_text"],
            row["transaction"],
            row["rights_acquired_marker"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped

def money_to_number(value: Any) -> float | None:
    match = MONEY_RE.search(clean(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace("$", "").replace(",", ""))
    except ValueError:
        return None

def parse_prior_salary_rows(
    body: bytes,
    player_id: str,
    player_name: str,
    url: str,
    body_sha: str,
) -> list[dict[str, Any]]:
    parser = parse_page(body)
    output = []

    for table_index, table in enumerate(parser.tables):
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

            record["base_salary_numeric"] = money_to_number(record.get("base_salary"))
            record["cap_hit_numeric"] = money_to_number(record.get("cap_hit"))
            if (
                record["base_salary_numeric"] is not None
                or record["cap_hit_numeric"] is not None
            ):
                output.append(record)

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

def find_population_zip(root: Path) -> Path:
    candidates = [
        path
        for path in root.rglob("franchise_free_agency_rights_population_*.zip")
        if path.is_file()
        and "provenance" not in path.name.lower()
        and "external_evidence" not in path.name.lower()
    ]
    if not candidates:
        raise RuntimeError("Could not locate the V1 rights-population ZIP.")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_unresolved(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        summary_name = next(n for n in names if n.endswith("rights_population_summary.json"))
        unresolved_name = next(n for n in names if n.endswith("rights_population_unresolved.csv"))
        summary = json.loads(archive.read(summary_name).decode("utf-8-sig"))
        unresolved = list(
            csv.DictReader(
                io.StringIO(archive.read(unresolved_name).decode("utf-8-sig"))
            )
        )
    return summary, unresolved

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

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
    population_zip = find_population_zip(root)
    population_summary, unresolved = read_unresolved(population_zip)

    if len(unresolved) != EXPECTED_UNRESOLVED:
        raise RuntimeError(
            f"Expected {EXPECTED_UNRESOLVED} unresolved players, got {len(unresolved)}."
        )

    checkpoint = checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS EXTERNAL EVIDENCE HARVEST V1.0.1", flush=True)
    print("=" * 124, flush=True)
    print(f"Canonical evidence cutoff: {EVIDENCE_CUTOFF_DATE.isoformat()}", flush=True)
    print("Fixes: page identity, PLAYER-row identity, canonical-name aliases, and future-leakage guard.", flush=True)
    print("", flush=True)

    transaction_rows: list[dict[str, Any]] = []
    salary_rows: list[dict[str, Any]] = []
    player_summary: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []

    sleep_seconds = 0.50

    for index, player in enumerate(unresolved, start=1):
        player_id = pid(player.get("player_id"))
        player_name = clean(player.get("player_name"))
        print(f"[{index:03d}/{EXPECTED_UNRESOLVED}] {player_name} ({player_id})", flush=True)

        tx_slug, tx_url, tx_http, tx_body, tx_error, tx_identity = fetch_verified(
            TRANSACTION_URL, player_name, "transaction", sleep_seconds
        )
        tx_sha = sha256_bytes(tx_body) if tx_body else ""
        parsed_tx = (
            parse_transaction_rows(tx_body, player_id, player_name, tx_url, tx_sha)
            if tx_http == 200 and tx_identity and tx_body
            else []
        )
        transaction_rows.extend(parsed_tx)

        time.sleep(sleep_seconds)

        sal_slug, sal_url, sal_http, sal_body, sal_error, sal_identity = fetch_verified(
            PLAYER_URL, player_name, "contract", sleep_seconds
        )
        sal_sha = sha256_bytes(sal_body) if sal_body else ""
        parsed_salary = (
            parse_prior_salary_rows(sal_body, player_id, player_name, sal_url, sal_sha)
            if sal_http == 200 and sal_identity and sal_body
            else []
        )
        salary_rows.extend(parsed_salary)

        if not tx_identity:
            tx_state = "page_identity_unresolved"
        elif not parsed_tx:
            tx_state = "verified_page_no_pre_cutoff_transaction_rows"
        else:
            tx_state = "verified_player_specific_transaction_rows"

        if not sal_identity:
            salary_state = "page_identity_unresolved"
        elif len(parsed_salary) == 0:
            salary_state = "verified_page_no_2025_26_salary_rows"
        elif len(parsed_salary) == 1:
            salary_state = "single_2025_26_salary_row"
        else:
            salary_state = "multiple_2025_26_salary_rows"

        player_summary.append({
            "player_id": player_id,
            "player_name": player_name,
            "v1_prior_team": clean(player.get("prior_team")).upper(),
            "v1_same_team_streak": clean(player.get("continuous_qualifying_seasons")),
            "years_of_service": clean(player.get("years_of_service")),
            "observed_seasons": clean(player.get("observed_seasons")),
            "observed_teams": clean(player.get("observed_teams")),
            "transaction_slug_used": tx_slug,
            "transaction_source_url": tx_url,
            "transaction_http_status": tx_http,
            "transaction_page_identity_verified": tx_identity,
            "transaction_fetch_error": tx_error,
            "transaction_rows_through_2026_08_04": len(parsed_tx),
            "transaction_evidence_status": tx_state,
            "contract_slug_used": sal_slug,
            "contract_source_url": sal_url,
            "contract_http_status": sal_http,
            "contract_page_identity_verified": sal_identity,
            "contract_fetch_error": sal_error,
            "salary_rows_2025_26": len(parsed_salary),
            "prior_salary_evidence_status": salary_state,
            "needs_manual_transaction_research": not bool(parsed_tx),
            "needs_manual_salary_research": len(parsed_salary) == 0,
            "multiple_prior_salary_rows_need_resolver": len(parsed_salary) > 1,
            "rights_classification_performed": False,
        })

        snapshots.extend([
            {
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "transaction",
                "url": tx_url,
                "slug_used": tx_slug,
                "http_status": tx_http,
                "page_identity_verified": tx_identity,
                "body_sha256": tx_sha,
                "body_bytes": len(tx_body),
                "fetch_error": tx_error,
            },
            {
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "contract",
                "url": sal_url,
                "slug_used": sal_slug,
                "http_status": sal_http,
                "page_identity_verified": sal_identity,
                "body_sha256": sal_sha,
                "body_bytes": len(sal_body),
                "fetch_error": sal_error,
            },
        ])

        time.sleep(sleep_seconds)

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    tx_players = {row["player_id"] for row in transaction_rows}
    salary_players = {row["player_id"] for row in salary_rows}

    checks = []
    def add_check(name: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": name,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })

    target_ids = {pid(row.get("player_id")) for row in unresolved}

    add_check("target_count_is_161", len(target_ids) == EXPECTED_UNRESOLVED, "Exact V1 unresolved universe.")
    add_check(
        "all_exported_transaction_rows_match_target_player",
        all(names_equivalent(row["player_name"], row["listed_player_text"]) for row in transaction_rows),
        "Generic SalarySwish transaction rows can no longer leak into player evidence.",
    )
    add_check(
        "no_transaction_after_canonical_cutoff",
        all(date.fromisoformat(row["transaction_date"]) <= EVIDENCE_CUTOFF_DATE for row in transaction_rows),
        "No event after 2026-08-04 is admissible to the canonical snapshot.",
    )
    add_check(
        "transaction_pages_credit_only_verified_identity",
        all(
            row["transaction_rows_through_2026_08_04"] == 0
            or row["transaction_page_identity_verified"]
            for row in player_summary
        ),
        "Transaction rows require verified target-page identity.",
    )
    add_check(
        "salary_pages_credit_only_verified_identity",
        all(
            row["salary_rows_2025_26"] == 0
            or row["contract_page_identity_verified"]
            for row in player_summary
        ),
        "Salary rows require verified player-page identity.",
    )
    add_check(
        "no_rights_classification_performed",
        all(not row["rights_classification_performed"] for row in player_summary),
        "Evidence harvest remains separate from CBA classification.",
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
        "transaction_evidence_coverage",
        len(tx_players) == EXPECTED_UNRESOLVED,
        f"Verified player-specific transaction evidence for {len(tx_players)}/{EXPECTED_UNRESOLVED}.",
        severity="coverage",
    )
    add_check(
        "prior_salary_evidence_coverage",
        len(salary_players) == EXPECTED_UNRESOLVED,
        f"Verified 2025-26 salary evidence for {len(salary_players)}/{EXPECTED_UNRESOLVED}.",
        severity="coverage",
    )

    failed_strict = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "V1.0.1 external evidence harvest failed strict checks: "
            + ", ".join(failed_strict)
        )

    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"franchise_free_agency_rights_external_evidence_v1_0_1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    zip_out = out_dir / f"{export_id}.zip"

    manual_queue = [
        row for row in player_summary
        if row["needs_manual_transaction_research"]
        or row["needs_manual_salary_research"]
        or row["multiple_prior_salary_rows_need_resolver"]
    ]

    with tempfile.TemporaryDirectory(prefix="fa_rights_external_v101_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "rights_external_evidence_player_summary.csv", player_summary)
        write_csv(export / "rights_external_transaction_rows.csv", transaction_rows)
        write_csv(export / "rights_external_prior_salary_rows.csv", salary_rows)
        write_csv(export / "rights_external_source_snapshots.csv", snapshots)
        write_csv(export / "rights_external_manual_research_queue.csv", manual_queue)
        write_csv(export / "rights_external_evidence_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "canonical_evidence_cutoff_date": EVIDENCE_CUTOFF_DATE.isoformat(),
            "target_players": EXPECTED_UNRESOLVED,
            "verified_transaction_evidence_players": len(tx_players),
            "verified_prior_salary_evidence_players": len(salary_players),
            "manual_or_multi_salary_queue_players": len(manual_queue),
            "transaction_rows_exported": len(transaction_rows),
            "prior_salary_rows_exported": len(salary_rows),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "classification_changes_performed": 0,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "failed_strict_checks": failed_strict,
            "passed": not failed_strict,
            "hotfixes": [
                "SalarySwish page identity must match target player.",
                "Every parsed transaction PLAYER cell must match target player.",
                "Known canonical SalarySwish slug aliases are tried before generic slugs.",
                "Transaction evidence is cut off at the canonical 2026-08-04 snapshot date.",
                "Multiple 2025-26 salary rows are retained for the next contract-sequence resolver rather than treated as a fetch failure.",
            ],
        }
        (export / "rights_external_evidence_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after V1.0.1 export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after V1.0.1 export.")

    print("", flush=True)
    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS EXTERNAL EVIDENCE HARVEST V1.0.1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Verified transaction evidence: {len(tx_players)}/{EXPECTED_UNRESOLVED}", flush=True)
    print(f"Verified 2025-26 salary evidence: {len(salary_players)}/{EXPECTED_UNRESOLVED}", flush=True)
    print(f"Manual / multi-salary queue: {len(manual_queue)}", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Rights classifications changed: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
