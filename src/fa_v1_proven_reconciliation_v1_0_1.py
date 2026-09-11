from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-v1-proven-reconciliation-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
BASE = "https://www.salaryswish.com"
TRANSACTION_URL = BASE + "/transactions/players/{slug}"
PLAYER_URL = BASE + "/players/{slug}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

NBA_TEAMS = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
    "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}

TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR", "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2}$"
)

SIGNING_TYPES = {
    "Signed to Veteran Contract",
    "Signed to Two-Way Contract",
    "Signed to Rookie Contract",
    "Signed to Rookie Scale Contract",
    "Signed to 10-Day Contract",
    "Signed to Exhibit 10",
}

SLUG_OVERRIDES = {
    "Gary Payton II": ["gary-payton-ii"],
    "Kevin McCullar Jr.": ["kevin-mccullar-jr"],
}

class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.table_depth = 0
        self.current_table: list[list[str]] | None = None
        self.in_row = False
        self.current_row: list[str] = []
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.in_title = False
        self.title_parts: list[str] = []
        self.in_h1 = False
        self.h1_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.in_h1 = True
        elif tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.current_table = []
        elif self.table_depth == 1 and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.table_depth == 1 and self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []
        elif self.in_cell and tag == "br":
            self.cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)
        if self.in_title:
            self.title_parts.append(data)
        if self.in_h1:
            self.h1_parts.append(data)
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False
        elif self.table_depth == 1 and self.in_row and tag in {"td", "th"}:
            self.current_row.append(" ".join("".join(self.cell_parts).split()))
            self.in_cell = False
            self.cell_parts = []
        elif self.table_depth == 1 and tag == "tr":
            if self.current_table is not None and any(self.current_row):
                self.current_table.append(self.current_row)
            self.current_row = []
            self.in_row = False
        elif tag == "table" and self.table_depth:
            if self.table_depth == 1 and self.current_table is not None:
                self.tables.append(self.current_table)
                self.current_table = None
            self.table_depth -= 1

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def h1(self) -> str:
        return " ".join("".join(self.h1_parts).split())

    @property
    def page_text(self) -> str:
        return "\n".join(self.text_parts)

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def team(value: Any) -> str:
    text = clean(value).upper()
    return text if text in NBA_TEAMS else ""

def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(two-way\)", "", text)
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def names_equivalent(a: str, b: str) -> bool:
    na, nb = norm_name(a), norm_name(b)
    if na == nb:
        return True
    suffixes = {" jr", " sr", " ii", " iii", " iv"}
    stripped_a = na
    stripped_b = nb
    for suffix in suffixes:
        if stripped_a.endswith(suffix):
            stripped_a = stripped_a[:-len(suffix)]
        if stripped_b.endswith(suffix):
            stripped_b = stripped_b[:-len(suffix)]
    return stripped_a == stripped_b

def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def slug_candidates(name: str) -> list[str]:
    result: list[str] = []
    for slug in SLUG_OVERRIDES.get(name, []):
        if slug not in result:
            result.append(slug)
    base = slugify(name)
    for slug in [base, re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base)]:
        slug = slug.strip("-")
        if slug and slug not in result:
            result.append(slug)
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

def fetch(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
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

def transaction_identity(parser: PageParser, player_name: str) -> bool:
    target = norm_name(player_name)
    if target and (target in norm_name(parser.title) or target in norm_name(parser.h1)):
        return True
    for table in parser.tables:
        for index, row in enumerate(table[:8]):
            header = normalize_header(row)
            if "player" not in header:
                continue
            player_idx = header.index("player")
            for data_row in table[index + 1:]:
                row2 = list(data_row)
                if row2 and DATE_RE.match(clean(row2[0])):
                    row2 = row2[1:]
                if player_idx < len(row2) and names_equivalent(player_name, row2[player_idx]):
                    return True
    return False

def contract_identity(parser: PageParser, player_name: str) -> bool:
    target = norm_name(player_name)
    return bool(
        target
        and (
            target in norm_name(parser.title)
            or target in norm_name(parser.h1)
            or target in norm_name(parser.page_text[:50000])
        )
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
                transaction_identity(parser, player_name)
                if kind == "transaction"
                else contract_identity(parser, player_name)
            )
        last = (slug, url, status, body, error, identity)
        if status == 200 and body and identity:
            return last
        time.sleep(sleep_seconds)
    return last

def parse_transaction_rows(
    body: bytes,
    player_id: str,
    player_name: str,
    source_url: str,
    source_sha: str,
) -> list[dict[str, Any]]:
    parser = parse_page(body)
    output: list[dict[str, Any]] = []
    for table in parser.tables:
        header_index = None
        header: list[str] = []
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

        for raw_row in table[header_index + 1:]:
            row = list(raw_row)
            if not row:
                continue
            if row and DATE_RE.match(clean(row[0])):
                current_date = clean(row[0])
                row = row[1:]
            if len(row) <= max(team_idx, player_idx, tx_idx):
                continue
            listed_player = clean(row[player_idx])
            if not names_equivalent(player_name, listed_player):
                continue
            try:
                day = datetime.strptime(current_date, "%b %d, %Y").date()
            except Exception:
                continue
            if day > SIMULATION_SPLIT_DATE:
                continue

            team_name = clean(row[team_idx])
            transaction = clean(row[tx_idx])
            if not team_name or not transaction:
                continue
            rights_text = (
                clean(row[rights_idx])
                if rights_idx is not None and rights_idx < len(row)
                else ""
            )
            output.append({
                "player_id": player_id,
                "player_name": player_name,
                "transaction_date": day.isoformat(),
                "transaction_date_text": current_date,
                "team_name": team_name,
                "team_abbreviation": TEAM_NAME_TO_ABBR.get(team_name, ""),
                "listed_player_text": listed_player,
                "transaction": transaction,
                "rights_acquired_marker": bool(rights_text),
                "rights_acquired_text": rights_text,
                "source_url": source_url,
                "source_sha256": source_sha,
            })

    seen = set()
    deduped = []
    for row in output:
        key = (
            row["transaction_date"],
            row["team_name"],
            row["transaction"],
            row["rights_acquired_marker"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped

def event_priority(text: str) -> int:
    if text == "Hold Renounced": return 10
    if text == "Placed on waivers": return 20
    if text == "Contract boughtout": return 25
    if text == "Contract terminated": return 30
    if text == "Cleared waivers": return 40
    if text in SIGNING_TYPES: return 50
    if text.startswith("Claimed on waivers"): return 60
    if text.startswith("Traded from "): return 70
    if text == "Signed to Veteran Extension": return 80
    return 90

def observed_seasons(value: Any) -> set[int]:
    result: set[int] = set()
    for item in clean(value).split("|"):
        match = re.match(r"^(20\d{2})-", item.strip())
        if match:
            year = int(match.group(1))
            if year in {2023, 2024, 2025}:
                result.add(year)
    return result

def analyze_candidate(
    candidate: Mapping[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    events = []
    for raw in rows:
        try:
            day = date.fromisoformat(clean(raw.get("transaction_date")))
        except Exception:
            continue
        events.append({
            **raw,
            "_date": day,
            "_priority": event_priority(clean(raw.get("transaction"))),
        })
    events.sort(key=lambda r: (r["_date"], r["_priority"], clean(r.get("transaction"))))

    prior_team = team(candidate.get("prior_team"))
    current_team = prior_team
    last_team = prior_team
    reset_seasons: list[int] = []
    waiver_claim_seasons: list[int] = []
    material: list[tuple[date, int, str, str, str]] = []
    one_year_trade_candidates: list[str] = []
    signing_records: list[tuple[date, int, str, str]] = []

    for row in events:
        day = row["_date"]
        text = clean(row.get("transaction"))
        event_team = team(row.get("team_abbreviation"))
        season_start = day.year if day.month >= 7 else day.year - 1

        if text == "Hold Renounced":
            if season_start in {2023, 2024, 2025}:
                reset_seasons.append(season_start)
            current_team = ""
            last_team = event_team or last_team
            continue

        if text == "Cleared waivers":
            last_team = current_team or event_team or last_team
            current_team = ""
            material.append((day, event_priority(text), "cleared", event_team, text))
            continue

        if text == "Contract terminated":
            last_team = current_team or event_team or last_team
            current_team = ""
            material.append((day, event_priority(text), "terminated", event_team, text))
            continue

        if text in SIGNING_TYPES:
            reference_team = current_team or last_team
            if reference_team and event_team and event_team != reference_team:
                if season_start in {2023, 2024, 2025}:
                    reset_seasons.append(season_start)
            current_team = event_team or current_team
            last_team = current_team or last_team
            signing_records.append((day, season_start, current_team, text))
            material.append((day, event_priority(text), "sign", current_team, text))
            continue

        if text.startswith("Claimed on waivers"):
            if season_start in {2023, 2024, 2025}:
                waiver_claim_seasons.append(season_start)
            current_team = event_team or current_team
            last_team = current_team or last_team
            material.append((day, event_priority(text), "claim", current_team, text))
            continue

        if text.startswith("Traded from "):
            source_team = team(text.replace("Traded from ", ""))
            # Article VII 8(b) risk flag. We do not try to infer consent.
            preceding = [record for record in signing_records if record[0] < day]
            if preceding:
                signing = max(preceding, key=lambda item: item[0])
                if (
                    signing[1] == season_start
                    and signing[2] == source_team
                    and signing[3] == "Signed to Veteran Contract"
                ):
                    one_year_trade_candidates.append(
                        f"{signing[0].isoformat()} {source_team} signing -> "
                        f"{day.isoformat()} trade to {event_team}"
                    )
            current_team = event_team or current_team
            last_team = current_team or last_team
            material.append((day, event_priority(text), "trade", current_team, text))
            continue

    material.sort(key=lambda item: (item[0], item[1], item[4]))
    terminal = material[-1] if material else None

    if terminal is None:
        terminal_kind = "veteran_free_agent_assumed_from_population"
        terminal_team = prior_team
    elif terminal[2] == "cleared":
        terminal_kind = "waiver_terminated_free_agent"
        terminal_team = ""
    elif terminal[2] == "terminated":
        terminal_kind = "contract_termination_requires_review"
        terminal_team = ""
    elif terminal[2] == "sign" and terminal[4] == "Signed to 10-Day Contract":
        terminal_kind = "ten_day_free_agent"
        terminal_team = terminal[3]
    else:
        terminal_kind = "veteran_free_agent"
        terminal_team = terminal[3] or current_team or prior_team

    coverage = observed_seasons(candidate.get("observed_seasons"))
    last_reset = max(reset_seasons) if reset_seasons else (
        min(coverage) if coverage else None
    )

    old_class = clean(candidate.get("rights_classification"))

    if terminal_kind == "waiver_terminated_free_agent":
        new_class = "not_applicable"
        status = "reclassified_non_vfa"
        reason = "Latest pre-split terminal event is clearing waivers."
    elif terminal_kind == "ten_day_free_agent":
        new_class = "not_applicable"
        status = "reclassified_non_vfa"
        reason = "Latest pre-split contract is a 10-Day Contract."
    elif terminal_kind == "contract_termination_requires_review":
        new_class = "unknown"
        status = "manual_review"
        reason = "Contract termination is observed but the terminal waiver path is not explicit."
    elif one_year_trade_candidates:
        new_class = "unknown"
        status = "manual_review"
        reason = "Article VII Section 8(b) one-year trade-consent provenance could change continuity."
    else:
        bird = (
            {2023, 2024, 2025}.issubset(coverage)
            and last_reset is not None
            and last_reset <= 2023
            and not any(s > 2023 for s in waiver_claim_seasons)
        )
        early = (
            {2024, 2025}.issubset(coverage)
            and last_reset is not None
            and last_reset <= 2024
        )
        if bird:
            new_class = "bird"
            status = "confirmed" if old_class == "bird" else "reclassified"
            reason = "Three observed qualifying Seasons remain continuous through the split."
        elif early:
            new_class = "early_bird"
            status = "confirmed" if old_class == "early_bird" else "reclassified"
            reason = "Two observed qualifying Seasons remain continuous through the split."
        elif last_reset == 2025:
            new_class = "non_bird"
            status = "reclassified"
            reason = "Explicit 2025-26 team-change reset prevents Early Bird continuity."
        else:
            new_class = "unknown"
            status = "manual_review"
            reason = "Transaction evidence is insufficient for a safe deterministic class."

    if (
        status in {"confirmed", "reclassified"}
        and terminal_team
        and terminal_team != prior_team
    ):
        status = "manual_review"
        new_class = "unknown"
        reason = (
            f"Resolved terminal team {terminal_team} conflicts with V1 prior team {prior_team}."
        )

    fingerprint = hashlib.sha256(
        json.dumps(
            [
                {
                    "date": row["_date"].isoformat(),
                    "team": clean(row.get("team_abbreviation")),
                    "transaction": clean(row.get("transaction")),
                    "source_sha256": clean(row.get("source_sha256")),
                }
                for row in events
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "player_id": pid(candidate.get("player_id")),
        "player_name": clean(candidate.get("player_name")),
        "v1_rights_classification": old_class,
        "reconciled_status": status,
        "reconciled_rights_classification": new_class,
        "free_agent_category": terminal_kind,
        "v1_prior_team": prior_team,
        "resolved_terminal_team": terminal_team,
        "observed_qualifying_seasons": "|".join(
            f"{year}-{str(year+1)[-2:]}" for year in sorted(coverage)
        ),
        "last_reset_season_start": last_reset or "",
        "waiver_claim_seasons": "|".join(str(s) for s in sorted(set(waiver_claim_seasons))),
        "article_vii_8b_candidate_count": len(one_year_trade_candidates),
        "article_vii_8b_candidates": "|".join(one_year_trade_candidates),
        "transaction_row_count": len(events),
        "classification_reason": reason,
        "timeline_fingerprint": fingerprint,
    }

def find_population_zip(root: Path) -> Path:
    candidates = [
        path for path in root.rglob("franchise_free_agency_rights_population_2026-27_*.zip")
        if path.is_file()
        and "provenance" not in path.name.lower()
        and "external" not in path.name.lower()
        and "continuity" not in path.name.lower()
    ]
    if not candidates:
        raise RuntimeError("Could not locate the V1 rights-population ZIP.")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"Population ZIP missing {suffix}")
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))

def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"Population ZIP missing {suffix}")
    return json.loads(archive.read(name).decode("utf-8-sig"))

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
    fields: list[str] = []
    seen: set[str] = set()
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

    with zipfile.ZipFile(population_zip) as archive:
        population_summary = read_json_member(archive, "rights_population_summary.json")
        proven = read_csv_member(archive, "rights_population_proven.csv")

    if len(proven) != 26:
        raise RuntimeError(f"Expected 26 V1-proven rows, found {len(proven)}.")

    checkpoint = checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)
    expected_checkpoint = clean(population_summary.get("checkpoint_sha256"))

    if expected_checkpoint and checkpoint_before != expected_checkpoint:
        raise RuntimeError(
            "Canonical checkpoint no longer matches the V1 population anchor. "
            f"expected={expected_checkpoint} current={checkpoint_before}"
        )

    print("=" * 118, flush=True)
    print("V1 PROVEN BIRD-RIGHTS TRANSACTION RECONCILIATION V1.0.1", flush=True)
    print("=" * 118, flush=True)
    print(f"Population input: {population_zip}", flush=True)
    print(f"Target rows:      {len(proven)}", flush=True)
    print(f"Simulation split: {SIMULATION_SPLIT_DATE.isoformat()}", flush=True)
    print("Read-only: no rights overlay or franchise mutation.", flush=True)
    print("", flush=True)

    sleep_seconds = 0.50
    all_transactions: list[dict[str, Any]] = []
    source_manifest: list[dict[str, Any]] = []
    raw_snapshots: dict[str, bytes] = {}
    rows_by_player: dict[str, list[dict[str, Any]]] = {}

    for index, candidate in enumerate(proven, start=1):
        player_id = pid(candidate.get("player_id"))
        player_name = clean(candidate.get("player_name"))
        print(f"[{index:02d}/26] {player_name} ({player_id})", flush=True)

        tx_slug, tx_url, tx_status, tx_body, tx_error, tx_identity = fetch_verified(
            TRANSACTION_URL, player_name, "transaction", sleep_seconds
        )
        tx_sha = sha256_bytes(tx_body) if tx_body else ""
        tx_rows = (
            parse_transaction_rows(
                tx_body, player_id, player_name, tx_url, tx_sha
            )
            if tx_status == 200 and tx_identity and tx_body
            else []
        )
        rows_by_player[player_id] = tx_rows
        all_transactions.extend(tx_rows)

        if tx_status == 200 and tx_identity and tx_body:
            member = f"snapshots/{player_id}_{tx_slug}_transactions.html"
            raw_snapshots[member] = tx_body
        else:
            member = ""

        source_manifest.append({
            "player_id": player_id,
            "player_name": player_name,
            "source_kind": "transaction",
            "slug_used": tx_slug,
            "url": tx_url,
            "http_status": tx_status,
            "identity_verified": tx_identity,
            "body_sha256": tx_sha,
            "body_bytes": len(tx_body),
            "snapshot_member": member,
            "fetch_error": tx_error,
        })

        time.sleep(sleep_seconds)

        c_slug, c_url, c_status, c_body, c_error, c_identity = fetch_verified(
            PLAYER_URL, player_name, "contract", sleep_seconds
        )
        c_sha = sha256_bytes(c_body) if c_body else ""
        if c_status == 200 and c_identity and c_body:
            member = f"snapshots/{player_id}_{c_slug}_contract.html"
            raw_snapshots[member] = c_body
        else:
            member = ""

        source_manifest.append({
            "player_id": player_id,
            "player_name": player_name,
            "source_kind": "contract",
            "slug_used": c_slug,
            "url": c_url,
            "http_status": c_status,
            "identity_verified": c_identity,
            "body_sha256": c_sha,
            "body_bytes": len(c_body),
            "snapshot_member": member,
            "fetch_error": c_error,
        })

        time.sleep(sleep_seconds)

    reconciliation = [
        analyze_candidate(candidate, rows_by_player.get(pid(candidate.get("player_id")), []))
        for candidate in proven
    ]

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []
    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })

    target_ids = {pid(row.get("player_id")) for row in proven}
    reconciled_ids = {row["player_id"] for row in reconciliation}
    transaction_sources = [
        row for row in source_manifest if row["source_kind"] == "transaction"
    ]
    contract_sources = [
        row for row in source_manifest if row["source_kind"] == "contract"
    ]

    check("target_count_is_26", len(target_ids) == 26, "Exact original V1-proven universe.")
    check("reconciliation_ids_match_targets", reconciled_ids == target_ids, "No row was added or omitted.")
    check(
        "all_26_transaction_pages_are_identity_verified",
        sum(bool(row["identity_verified"]) for row in transaction_sources) == 26,
        (
            "Every V1-proven rights classification must have a verified "
            f"player-specific transaction page; verified="
            f"{sum(bool(row['identity_verified']) for row in transaction_sources)}/26."
        ),
    )
    check(
        "accepted_transaction_snapshots_are_identity_verified",
        all(
            not clean(row.get("snapshot_member"))
            or bool(row["identity_verified"])
            for row in transaction_sources
        ),
        "No unverified transaction page may be accepted into the evidence package.",
    )
    check(
        "accepted_contract_snapshots_are_identity_verified",
        all(
            not clean(row.get("snapshot_member"))
            or bool(row["identity_verified"])
            for row in contract_sources
        ),
        (
            "Contract pages are supplemental in this reconciliation; any accepted "
            "snapshot must match the player, while rejected HTTP-200 fallbacks are "
            "quarantined rather than treated as fatal."
        ),
    )
    check(
        "all_exported_transactions_are_pre_split",
        all(
            date.fromisoformat(clean(row["transaction_date"])) <= SIMULATION_SPLIT_DATE
            for row in all_transactions
        ),
        "No real-world post-split transaction can change simulator rights.",
    )
    check(
        "confirmed_bird_rows_keep_three_observed_seasons",
        all(
            len(observed_seasons(
                next(
                    candidate for candidate in proven
                    if pid(candidate.get("player_id")) == row["player_id"]
                ).get("observed_seasons")
            )) == 3
            for row in reconciliation
            if row["reconciled_status"] == "confirmed"
            and row["reconciled_rights_classification"] == "bird"
        ),
        "Bird confirmation never weakens the V1 three-season evidence requirement.",
    )
    check(
        "confirmed_early_bird_rows_keep_two_observed_seasons",
        all(
            {2024, 2025}.issubset(
                observed_seasons(
                    next(
                        candidate for candidate in proven
                        if pid(candidate.get("player_id")) == row["player_id"]
                    ).get("observed_seasons")
                )
            )
            for row in reconciliation
            if row["reconciled_status"] == "confirmed"
            and row["reconciled_rights_classification"] == "early_bird"
        ),
        "Early Bird confirmation preserves both preceding-season evidence.",
    )
    check(
        "waiver_terminal_rows_never_keep_veteran_rights",
        all(
            row["reconciled_rights_classification"] == "not_applicable"
            for row in reconciliation
            if row["free_agent_category"] == "waiver_terminated_free_agent"
        ),
        "CBA waiver-terminated Free Agent category is not a Veteran FA rights class.",
    )
    check(
        "checkpoint_matches_population_anchor",
        not expected_checkpoint or checkpoint_before == expected_checkpoint,
        f"checkpoint={checkpoint_before}",
    )
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "Read-only reconciliation.",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "No rights registry write.",
    )

    check(
        "transaction_page_coverage",
        sum(row["identity_verified"] for row in transaction_sources) == 26,
        f"Verified transaction pages: {sum(row['identity_verified'] for row in transaction_sources)}/26",
        severity="coverage",
    )
    check(
        "contract_page_coverage",
        sum(row["identity_verified"] for row in contract_sources) == 26,
        f"Verified contract pages: {sum(row['identity_verified'] for row in contract_sources)}/26",
        severity="coverage",
    )

    failed_strict = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "V1 proven reconciliation failed strict checks: "
            + ", ".join(failed_strict)
        )

    changed = [
        row for row in reconciliation
        if row["reconciled_status"] != "confirmed"
    ]

    counts = Counter(row["reconciled_status"] for row in reconciliation)
    class_counts = Counter(
        row["reconciled_rights_classification"] for row in reconciliation
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_v1_proven_reconciliation_v1_0_1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fav1r_") as tmp:
        export = Path(tmp) / export_id
        export.mkdir(parents=True)

        write_csv(export / "v1_proven_reconciliation.csv", reconciliation)
        write_csv(export / "v1_proven_changed_or_review.csv", changed)
        write_csv(export / "v1_proven_transaction_rows.csv", all_transactions)
        write_csv(export / "v1_proven_source_manifest.csv", source_manifest)
        write_csv(
            export / "v1_proven_contract_page_review_queue.csv",
            [
                row for row in contract_sources
                if not bool(row["identity_verified"])
            ],
        )
        write_csv(export / "v1_proven_reconciliation_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "target_count": 26,
            "reconciliation_status_counts": dict(sorted(counts.items())),
            "reconciled_classification_counts": dict(sorted(class_counts.items())),
            "changed_or_review_count": len(changed),
            "verified_transaction_page_count": sum(
                row["identity_verified"] for row in transaction_sources
            ),
            "verified_contract_page_count": sum(
                bool(row["identity_verified"]) for row in contract_sources
            ),
            "contract_page_review_queue_count": sum(
                not bool(row["identity_verified"]) for row in contract_sources
            ),
            "population_zip": str(population_zip),
            "population_zip_sha256": sha256_file(population_zip),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "classification_preview_only": True,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "passed": not failed_strict,
            "failed_strict_checks": failed_strict,
            "purpose": (
                "Reconcile the original 26 history-proven Bird/Early Bird rows "
                "against player-specific transaction evidence before any final "
                "runtime rights registry is assembled."
            ),
        }
        (export / "v1_proven_reconciliation_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")
            for member, body in sorted(raw_snapshots.items()):
                archive.writestr(
                    f"{export_id}/{member}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after export.")

    print("", flush=True)
    print("=" * 118, flush=True)
    print("V1 PROVEN BIRD-RIGHTS TRANSACTION RECONCILIATION V1.0.1 PASSED", flush=True)
    print("=" * 118, flush=True)
    print(f"Confirmed unchanged: {counts.get('confirmed', 0)}", flush=True)
    print(f"Reclassified:       {counts.get('reclassified', 0)}", flush=True)
    print(f"Non-VFA corrected:  {counts.get('reclassified_non_vfa', 0)}", flush=True)
    print(f"Manual review:      {counts.get('manual_review', 0)}", flush=True)
    print(
        f"Supplemental contract pages unresolved: "
        f"{sum(not bool(row['identity_verified']) for row in contract_sources)}/26",
        flush=True,
    )
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
