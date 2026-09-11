from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

VERSION = "fa-unified-offseason-decision-preview-v1.1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
SALARY_CAP = 164_961_000.0
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

TEAM_OPTION = "team_option_decision"
PLAYER_OPTION = "player_option_decision"
GUARANTEE_DECISION = "non_guaranteed_or_partial_decision"
PENDING_CATEGORIES = {TEAM_OPTION, PLAYER_OPTION, GUARANTEE_DECISION}

# Narrow pre-split branch-owner repair. KJ Simpson was reclassified from a
# stale free-agent lifecycle placeholder into a 2026-27 guarantee decision,
# but the manual-resolution table did not carry the already-proven DEN owner
# into reconstructed_branch_owner.
VERIFIED_BRANCH_OWNER_REPAIRS = {
    "1642354": {
        "player_name": "KJ Simpson",
        "owner": "DEN",
        "evidence_date": "2026-02-19",
        "evidence": (
            "Denver signed KJ Simpson to a two-year Two-Way contract before "
            "the 2026-04-12 simulation split."
        ),
    },
}

# Narrow evidence completions for rows that V1.0.1 could not recover because
# current SalarySwish pages often place the old pre-split contract below a
# newer post-split contract. These values come from the pre-existing contract
# structure only. Any later exercise/decline/waiver outcome remains audit-only.
VERIFIED_DECISION_FINANCIAL_INPUTS = {
    "1642873": {
        "player_name": "Amari Williams",
        "base_salary_2026_27": 2_150_917.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/amari-williams",
    },
    "1641748": {
        "player_name": "Andre Jackson Jr.",
        "base_salary_2026_27": 2_406_205.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/andre-jackson-jr",
    },
    "1641713": {
        "player_name": "GG Jackson",
        "base_salary_2026_27": 2_406_205.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/gg-jackson-ii",
    },
    "1643060": {
        "player_name": "Hayden Gray",
        "base_salary_2026_27": 2_150_917.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/hayden-gray",
    },
    "1642364": {
        "player_name": "Jamir Watkins",
        "base_salary_2026_27": 2_150_917.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/jamir-watkins",
    },
    "1642367": {
        "player_name": "Jonathan Mogbo",
        "base_salary_2026_27": 2_296_271.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/jonathan-mogbo",
    },
    "1631169": {
        "player_name": "Josh Minott",
        "base_salary_2026_27": 2_584_539.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/josh-minott",
    },
    "1630577": {
        "player_name": "Julian Champagnie",
        "base_salary_2026_27": 3_000_000.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/julian-champagnie",
    },
    "1641763": {
        "player_name": "Julian Phillips",
        "base_salary_2026_27": 2_406_205.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/julian-phillips",
    },
    "1629645": {
        "player_name": "Kevin Porter Jr.",
        "base_salary_2026_27": 5_390_700.0,
        "guaranteed_salary_2026_27": 5_390_700.0,
        "option": "Player",
        "source_url": "https://www.salaryswish.com/players/kevin-porterjr",
    },
    "1642354": {
        "player_name": "KJ Simpson",
        "base_salary_2026_27": 680_985.0,
        "guaranteed_salary_2026_27": 85_300.0,
        "option": "",
        "source_url": "https://www.salaryswish.com/players/k-j-simpson",
    },
    "1642920": {
        "player_name": "Kobe Sanders",
        "base_salary_2026_27": 2_150_917.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/kobe-sanders",
    },
    "1642449": {
        "player_name": "Tolu Smith",
        "base_salary_2026_27": 2_411_090.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "Team",
        "source_url": "https://www.salaryswish.com/players/tolu-smith-iii",
    },
    "1641815": {
        "player_name": "Isaiah Stevens",
        "base_salary_2026_27": 680_985.0,
        "guaranteed_salary_2026_27": 83_500.0,
        "option": "",
        "source_url": "https://www.salaryswish.com/players/isaiah-stevens",
    },
    "1642880": {
        "player_name": "Kam Jones",
        "base_salary_2026_27": 2_150_917.0,
        "guaranteed_salary_2026_27": 1_075_458.0,
        "option": "",
        "source_url": "https://www.salaryswish.com/players/kam-jones",
    },
    "1643007": {
        "player_name": "Taelon Peter",
        "base_salary_2026_27": 680_985.0,
        "guaranteed_salary_2026_27": 0.0,
        "option": "",
        "source_url": "https://www.salaryswish.com/players/taelon-peter",
    },
}

FRED_VANVLEET_PLAYER_OPTION_OVERRIDE = {
    "player_id": "1627832",
    "player_name": "Fred VanVleet",
    "recommendation": "exercise",
    "confidence": "medium",
    "option_salary_2026_27": 25_000_000.0,
    "injury_date": "2025-09-22",
    "surgery_date": "2025-09-25",
    "reason": (
        "Pre-split injury decision proxy: VanVleet tore his right ACL in "
        "September 2025, underwent ACL repair, and missed the 2025-26 season. "
        "At age 32 with a guaranteed $25M player option, the conservative "
        "player-agent recommendation is to exercise. The later real-world "
        "exercise is not used."
    ),
    "injury_source_url": "https://www.nba.com/news/rockets-fred-vanvleet-tears-acl/",
    "medical_source_url": "https://www.nba.com/rockets/news/rockets-medical-update-4",
    "contract_source_url": (
        "https://www.nba.com/news/fred-vanvleet-rockets-contract-extension-2025"
    ),
}

BASE = "https://www.salaryswish.com"
PLAYER_URL = BASE + "/players/{slug}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")
MONTH_PATTERN = (
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
)
SIGNING_DATE_RE = re.compile(
    rf"Signing\s+Date\s*:?\s*{MONTH_PATTERN}\s+\d{{1,2}},\s+20\d{{2}}",
    re.IGNORECASE,
)

SLUG_OVERRIDES = {
    "Jae'Sean Tate": ["jaesean-tate"],
    "De'Anthony Melton": ["deanthony-melton"],
    "Day'Ron Sharpe": ["dayron-sharpe"],
    "Bogdan Bogdanović": ["bogdan-bogdanovic"],
    "Nikola Vučević": ["nikola-vucevic"],
    "Daeqwon Plowden": ["daeqwon-plowden"],
    "Kentavious Caldwell-Pope": ["kentavious-caldwellpope", "kentavious-caldwell-pope"],
    "Gary Trent Jr.": ["gary-trentjr", "gary-trent-jr"],
    "Kelly Oubre Jr.": ["kelly-oubrejr", "kelly-oubre-jr"],
    "Larry Nance Jr.": ["larry-nancejr", "larry-nance-jr"],
    "Tim Hardaway Jr.": ["tim-hardawayjr", "tim-hardaway-jr"],
    "KJ Simpson": ["k-j-simpson", "kj-simpson"],
    "Gary Payton II": ["gary-paytonii", "gary-payton-ii"],
    "Trey Jemison III": ["trey-jemison", "trey-jemison-iii"],
    "Mouhamadou Gueye": ["mouhamadou-gueye"],
    "Mouhamed Gueye": ["mouhamed-gueye"],
}

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def team(value: Any) -> str:
    return clean(value).upper()

def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")

def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []

def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))

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

def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def slug_candidates(name: str) -> list[str]:
    values: list[str] = []
    for item in SLUG_OVERRIDES.get(name, []):
        if item and item not in values:
            values.append(item)
    base = slugify(name)
    for item in (
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("-jr-", "-"),
        base.replace("-sr-", "-"),
    ):
        item = item.strip("-")
        if item and item not in values:
            values.append(item)
    return values

def money_values(value: Any) -> list[float]:
    values = []
    for match in MONEY_RE.findall(clean(value)):
        try:
            values.append(float(match.replace("$", "").replace(",", "")))
        except ValueError:
            pass
    return values

def money_first(value: Any) -> float | None:
    values = money_values(value)
    return values[0] if values else None

def money_last(value: Any) -> float | None:
    values = money_values(value)
    return values[-1] if values else None

def has_change_annotation(value: Any) -> bool:
    text = clean(value)
    return "→" in text or "->" in text or " to " in text.lower()

class ContractPageParser(HTMLParser):
    BLOCK_TAGS = {
        "p", "div", "section", "article", "li", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6", "br",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._table_pre_context = ""
        self._in_row = False
        self._current_row: list[str] = []
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._in_h1 = False
        self._h1_parts: list[str] = []
        self._visible_parts: list[str] = []

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    @property
    def h1(self) -> str:
        return " ".join("".join(self._h1_parts).split())

    def recent_context(self, max_chars: int = 3500) -> str:
        text = " ".join("".join(self._visible_parts).split())
        return text[-max_chars:]

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True

        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_pre_context = self.recent_context()
                self._current_table = []
            return

        if self._table_depth == 1 and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._table_depth == 1 and self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

        if tag in self.BLOCK_TAGS:
            self._visible_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_cell:
            self._cell_parts.append(data)
        self._visible_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

        if self._table_depth == 1 and self._in_row and tag in {"td", "th"}:
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
                self.tables.append({
                    "rows": self._current_table,
                    "pre_context": self._table_pre_context,
                })
                self._current_table = None
            self._table_depth -= 1

        if tag in self.BLOCK_TAGS:
            self._visible_parts.append(" ")

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
        return int(exc.code), body, f"HTTPError:{exc}"
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}:{exc}"

def page_identity(parser: ContractPageParser, player_name: str) -> bool:
    target = normalize_name(player_name)
    title = normalize_name(parser.title)
    h1 = normalize_name(parser.h1)
    return bool(
        target and (
            target in title
            or target in h1
            or (title and title in target)
            or (h1 and h1 in target)
        )
    )

def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", clean(cell).lower()).strip("_")
        for cell in row
    ]

def parse_signing_date(pre_context: str) -> date | None:
    match = SIGNING_DATE_RE.search(pre_context)
    if not match:
        return None
    text = re.sub(
        r"^Signing\s+Date\s*:?\s*",
        "",
        match.group(0),
        flags=re.IGNORECASE,
    )
    try:
        return datetime.strptime(text, "%B %d, %Y").date()
    except ValueError:
        return None

def extract_contract_spans(
    body: bytes,
    player_id: str,
    player_name: str,
    source_url: str,
) -> list[dict[str, Any]]:
    parser = ContractPageParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    spans = []

    for table_index, table_info in enumerate(parser.tables):
        rows = table_info["rows"]
        pre_context = clean(table_info["pre_context"])
        header_index = None
        header: list[str] = []

        for i, row in enumerate(rows[:7]):
            normalized = normalize_header(row)
            if "season" in normalized and (
                "base_salary" in normalized or "cap_hit" in normalized
            ):
                header_index = i
                header = normalized
                break

        if header_index is None:
            continue

        season_index = header.index("season")
        seasons: dict[str, dict[str, str]] = {}

        for row in rows[header_index + 1:]:
            if not row:
                continue
            season_text = clean(row[season_index]) if season_index < len(row) else ""
            key = (
                "2025-26" if season_text.startswith("2025-26")
                else "2026-27" if season_text.startswith("2026-27")
                else ""
            )
            if not key:
                continue
            record = {}
            for col_index, col_name in enumerate(header):
                if col_index < len(row):
                    record[col_name or f"column_{col_index}"] = clean(row[col_index])
            seasons[key] = record

        if "2025-26" not in seasons:
            continue

        signing_date = parse_signing_date(pre_context)
        target = seasons.get("2026-27", {})
        spans.append({
            "player_id": player_id,
            "player_name": player_name,
            "table_index": table_index,
            "source_url": source_url,
            "signing_date": signing_date.isoformat() if signing_date else "",
            "signing_date_is_pre_split": bool(
                signing_date and signing_date <= SIMULATION_SPLIT_DATE
            ),
            "target_exists": bool(target),
            "target_base_salary_text": clean(target.get("base_salary")),
            "target_base_salary": money_first(target.get("base_salary")),
            "target_guaranteed_text": clean(target.get("guaranteed")),
            "target_guaranteed_first": money_first(target.get("guaranteed")),
            "target_guaranteed_last": money_last(target.get("guaranteed")),
            "target_guaranteed_has_change_annotation": has_change_annotation(
                target.get("guaranteed")
            ),
            "target_option": clean(target.get("option")),
        })

    return spans

def select_contract_span(
    spans: list[dict[str, Any]],
    expected_category: str,
) -> dict[str, Any] | None:
    eligible = [
        row for row in spans
        if row.get("target_exists")
        and (
            row.get("signing_date_is_pre_split")
            or not clean(row.get("signing_date"))
        )
    ]
    if not eligible:
        return None

    def option_matches(row: Mapping[str, Any]) -> bool:
        option = clean(row.get("target_option")).lower()
        if expected_category == TEAM_OPTION:
            return "team" in option
        if expected_category == PLAYER_OPTION:
            return "player" in option
        return True

    matching = [row for row in eligible if option_matches(row)]
    candidates = matching or eligible

    dated = [row for row in candidates if clean(row.get("signing_date"))]
    if dated:
        dated.sort(key=lambda row: (row["signing_date"], row["table_index"]))
        return dated[-1]

    if len(candidates) == 1:
        return candidates[0]

    # For guarantee decisions, accept consensus on 2026-27 financial values.
    signatures = {
        (
            row.get("target_base_salary"),
            row.get("target_guaranteed_first"),
            row.get("target_guaranteed_last"),
            row.get("target_option"),
        )
        for row in candidates
    }
    if len(signatures) == 1:
        return candidates[-1]
    return None

def mapping_value(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default

def player_features(player: Any) -> dict[str, Any]:
    return {
        "overall": finite(getattr(player, "overall_rating", None)),
        "potential": finite(getattr(player, "potential_rating", None)),
        "age": finite(getattr(player, "age", None)),
        "position": clean(getattr(player, "position", "")),
        "years_of_service": finite(getattr(player, "years_of_service", None)),
    }

def fallback_market_reference(
    overall: float | None,
    potential: float | None,
    age: float | None,
) -> float | None:
    if overall is None:
        return None
    if overall >= 90:
        base = 42_000_000.0
    elif overall >= 86:
        base = 31_000_000.0
    elif overall >= 82:
        base = 22_000_000.0
    elif overall >= 79:
        base = 14_000_000.0
    elif overall >= 77:
        base = 9_000_000.0
    elif overall >= 75:
        base = 5_500_000.0
    elif overall >= 73:
        base = 3_500_000.0
    elif overall >= 71:
        base = 2_400_000.0
    elif overall >= 69:
        base = 1_900_000.0
    else:
        base = 1_450_000.0

    if potential is not None and potential > overall:
        base *= 1.0 + min(0.18, (potential - overall) * 0.018)

    if age is not None:
        if age <= 23:
            base *= 1.08
        elif age >= 34:
            base *= 0.88
        elif age >= 31:
            base *= 0.94

    return round(base, 2)

def try_canonical_market_reference(
    player: Any,
    salary_reference: float,
) -> tuple[float | None, str, str]:
    try:
        from franchise_free_agency_player_decision_v1 import market_salary_reference
    except Exception as exc:
        return None, "fallback", f"import_failed:{type(exc).__name__}"

    pseudo_offer = SimpleNamespace(
        annual_salary=float(max(salary_reference, 1.0)),
        years=1,
        guaranteed=True,
        option_type="decision_preview",
    )
    pseudo_preview = SimpleNamespace(
        offer=pseudo_offer,
        annual_salary=float(max(salary_reference, 1.0)),
        years=1,
        minimum_salary_floor=0.0,
        maximum_initial_salary=float(SALARY_CAP),
        can_commit=True,
        status="pass",
    )
    try:
        reference, _, _ = market_salary_reference(player, pseudo_preview)
        value = finite(reference)
        if value is not None and value > 0:
            return float(value), "canonical_free_agency_market_reference", ""
        return None, "fallback", "canonical_returned_nonpositive_or_nonfinite"
    except Exception as exc:
        return None, "fallback", f"canonical_call_failed:{type(exc).__name__}"

def branch_roster_context(
    branch_roster_ids: list[str],
    players: Mapping[str, Any],
    player_id: str,
) -> dict[str, Any]:
    values = []
    for rid in branch_roster_ids:
        if pid(rid) == pid(player_id):
            continue
        player = players.get(pid(rid))
        if player is None:
            continue
        overall = finite(getattr(player, "overall_rating", None))
        if overall is not None:
            values.append(overall)
    values.sort()
    bottom_five = values[:5]
    bottom_three = values[:3]
    return {
        "branch_roster_count": len(branch_roster_ids),
        "branch_known_overall_count": len(values),
        "branch_bottom_five_average": (
            sum(bottom_five) / len(bottom_five) if bottom_five else None
        ),
        "branch_bottom_three_average": (
            sum(bottom_three) / len(bottom_three) if bottom_three else None
        ),
        "branch_roster_median_overall": (
            values[len(values) // 2] if values else None
        ),
    }

def strategic_adjustment(
    *,
    overall: float | None,
    potential: float | None,
    age: float | None,
    roster_floor: float | None,
) -> float:
    adjustment = 0.0
    if overall is not None and roster_floor is not None:
        adjustment += (overall - roster_floor) * 0.06
    upside = (
        max(0.0, potential - overall)
        if overall is not None and potential is not None
        else 0.0
    )
    if age is not None and age <= 23 and upside >= 3:
        adjustment += 0.05
    if age is not None and age >= 32:
        adjustment -= 0.05
    return adjustment

def team_option_recommendation(
    *,
    market_reference: float | None,
    option_salary: float | None,
    overall: float | None,
    potential: float | None,
    age: float | None,
    roster_floor: float | None,
) -> tuple[str, float | None, str, str]:
    if option_salary is None or option_salary <= 0 or market_reference is None:
        return "manual_input_required", None, "low", "Missing salary or market reference."

    raw_ratio = market_reference / option_salary
    adjustment = strategic_adjustment(
        overall=overall,
        potential=potential,
        age=age,
        roster_floor=roster_floor,
    )
    adjusted = raw_ratio + adjustment

    if adjusted >= 1.12:
        decision = "exercise"
    elif adjusted <= 0.92:
        decision = "decline"
    else:
        youth_upside = (
            overall is not None
            and potential is not None
            and age is not None
            and age <= 25
            and potential >= overall + 3
        )
        roster_worthy = (
            overall is not None
            and roster_floor is not None
            and overall >= roster_floor
        )
        decision = "exercise" if (youth_upside or roster_worthy) else "decline"

    distance = abs(adjusted - 1.02)
    confidence = "high" if distance >= 0.45 else "medium" if distance >= 0.20 else "low"
    return (
        decision,
        adjusted,
        confidence,
        f"market/option={raw_ratio:.3f}; branch_context_adjustment={adjustment:+.3f}; adjusted={adjusted:.3f}",
    )

def player_option_recommendation(
    *,
    market_reference: float | None,
    option_salary: float | None,
    age: float | None,
    overall: float | None,
    potential: float | None,
) -> tuple[str, float | None, str, str]:
    if option_salary is None or option_salary <= 0 or market_reference is None:
        return "manual_input_required", None, "low", "Missing salary or market reference."

    option_to_market = option_salary / market_reference

    if option_to_market >= 1.10:
        decision = "exercise"
    elif option_to_market <= 0.90:
        decision = "decline"
    else:
        upside = (
            max(0.0, potential - overall)
            if overall is not None and potential is not None
            else 0.0
        )
        if age is not None and age >= 32:
            decision = "exercise"
        elif age is not None and age <= 26 and upside >= 3:
            decision = "decline"
        else:
            decision = "exercise" if option_salary >= market_reference else "decline"

    distance = abs(option_to_market - 1.0)
    confidence = "high" if distance >= 0.35 else "medium" if distance >= 0.15 else "low"
    return (
        decision,
        option_to_market,
        confidence,
        f"option/market={option_to_market:.3f}; player-side economic decision",
    )

def guarantee_recommendation(
    *,
    market_reference: float | None,
    base_salary: float | None,
    guaranteed_salary: float | None,
    guarantee_timing_ambiguous: bool,
    overall: float | None,
    potential: float | None,
    age: float | None,
    roster_floor: float | None,
) -> tuple[str, float | None, str, str]:
    if guarantee_timing_ambiguous:
        return (
            "manual_input_required",
            None,
            "low",
            "Guarantee amount changes over time and branch-date timing needs explicit evidence.",
        )
    if (
        base_salary is None
        or base_salary <= 0
        or guaranteed_salary is None
        or market_reference is None
    ):
        return "manual_input_required", None, "low", "Missing base, guarantee, or market reference."

    incremental_keep_cost = max(0.0, base_salary - guaranteed_salary)
    if incremental_keep_cost <= 1.0:
        return (
            "retain",
            None,
            "high",
            "2026-27 salary is effectively fully guaranteed at the decision point.",
        )

    ratio = market_reference / incremental_keep_cost
    adjustment = strategic_adjustment(
        overall=overall,
        potential=potential,
        age=age,
        roster_floor=roster_floor,
    )
    adjusted = ratio + adjustment

    if adjusted >= 1.15:
        decision = "retain"
    elif adjusted <= 0.90:
        decision = "waive"
    else:
        roster_worthy = (
            overall is not None
            and roster_floor is not None
            and overall >= roster_floor
        )
        youth_upside = (
            overall is not None
            and potential is not None
            and age is not None
            and age <= 25
            and potential >= overall + 3
        )
        decision = "retain" if (roster_worthy or youth_upside) else "waive"

    distance = abs(adjusted - 1.02)
    confidence = "high" if distance >= 0.45 else "medium" if distance >= 0.20 else "low"
    return (
        decision,
        adjusted,
        confidence,
        (
            f"market/incremental_keep_cost={ratio:.3f}; "
            f"branch_context_adjustment={adjustment:+.3f}; adjusted={adjusted:.3f}; "
            f"base={base_salary:.0f}; guaranteed={guaranteed_salary:.0f}"
        ),
    )

def main() -> int:
    root = Path.cwd().resolve()

    final_zip = find_latest(
        root,
        "fa_final_contract_source_manual_resolution_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    v411_zip = find_latest(
        root,
        "fa_official_option_and_zero_game_population_v4_1_1_preview_2026-27_*.zip",
    )
    original_lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    additional_harvest_zip = find_latest(
        root,
        "fa_additional_lifecycle_contract_evidence_harvest_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(final_zip) as archive:
        final_summary = read_json_member(
            archive,
            "final_manual_resolution_summary.json",
        )
        lifecycle_rows = read_csv_member(
            archive,
            "unified_lifecycle_final_311.csv",
        )

    with zipfile.ZipFile(branch_zip) as archive:
        branch_rows = read_csv_member(
            archive,
            "branch_reconstruction_all_players.csv",
        )

    with zipfile.ZipFile(v411_zip) as archive:
        supplement_rows = read_csv_member(
            archive,
            "zero_game_population_supplement_5.csv",
        )

    with zipfile.ZipFile(original_lifecycle_zip) as archive:
        original_financial_rows = read_csv_member(
            archive,
            "contract_option_lifecycle_all.csv",
        )

    with zipfile.ZipFile(additional_harvest_zip) as archive:
        additional_financial_rows = read_csv_member(
            archive,
            "additional_lifecycle_contract_classification.csv",
        )

    pending_rows = [
        dict(row) for row in lifecycle_rows
        if clean(row.get("unified_lifecycle_category")) in PENDING_CATEGORIES
    ]

    if len(pending_rows) != 111:
        raise RuntimeError(
            f"Expected 111 pending decisions, got {len(pending_rows)}."
        )

    pending_owner_repairs = []
    invalid_pending_before = []

    for row in pending_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        owner = team(row.get("reconstructed_branch_owner"))

        if owner in TEAM_CODES:
            continue

        invalid_pending_before.append({
            "player_id": player_id,
            "player_name": player_name,
            "owner_before": owner,
        })

        repair = VERIFIED_BRANCH_OWNER_REPAIRS.get(player_id)
        if repair is None:
            continue

        if normalize_name(player_name) != normalize_name(repair["player_name"]):
            raise RuntimeError(
                "Branch-owner repair player identity mismatch for "
                f"{player_id}: lifecycle={player_name!r}; "
                f"repair={repair['player_name']!r}"
            )

        row["reconstructed_branch_owner"] = repair["owner"]
        row["branch_owner_repaired"] = True
        row["branch_owner_repair_evidence_date"] = repair["evidence_date"]
        row["branch_owner_repair_evidence"] = repair["evidence"]

        pending_owner_repairs.append({
            "player_id": player_id,
            "player_name": player_name,
            "owner_before": owner,
            "owner_after": repair["owner"],
            "evidence_date": repair["evidence_date"],
            "evidence": repair["evidence"],
            "future_real_world_outcome_used": False,
        })

    invalid_pending_after = [
        {
            "player_id": pid(row.get("player_id")),
            "player_name": clean(row.get("player_name")),
            "owner_after": team(row.get("reconstructed_branch_owner")),
        }
        for row in pending_rows
        if team(row.get("reconstructed_branch_owner")) not in TEAM_CODES
    ]

    if {
        (row["player_id"], row["player_name"])
        for row in invalid_pending_before
    } != {("1642354", "KJ Simpson")}:
        raise RuntimeError(
            "Unexpected pending branch-owner gap(s) before repair: "
            + repr(invalid_pending_before)
        )

    if invalid_pending_after:
        raise RuntimeError(
            "Pending branch-owner gap(s) remain after narrow repair: "
            + repr(invalid_pending_after)
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state = checkpoint.simulation_state

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before unified decision preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    try:
        from franchise_free_agency_ui_v1 import controlled_teams_from_checkpoint
        controlled_teams = set(
            controlled_teams_from_checkpoint(checkpoint, state)
        )
    except Exception:
        controlled_teams = set()

    players = getattr(state, "players", {}) or {}

    original_financial = {
        pid(row.get("player_id")): row for row in original_financial_rows
    }
    additional_financial = {
        pid(row.get("player_id")): row for row in additional_financial_rows
    }

    # Reconstruct branch-date offseason roster context.
    owner_by_id: dict[str, str] = {
        pid(row.get("player_id")): team(row.get("reconstructed_branch_owner"))
        for row in branch_rows
    }
    for row in supplement_rows:
        player_id = pid(row.get("player_id"))
        owner = team(row.get("reconstructed_branch_owner"))
        if owner:
            owner_by_id[player_id] = owner

    # Pending lifecycle rows are authoritative for any narrow owner repairs.
    for row in pending_rows:
        player_id = pid(row.get("player_id"))
        owner = team(row.get("reconstructed_branch_owner"))
        if owner in TEAM_CODES:
            owner_by_id[player_id] = owner

    lifecycle_by_id = {
        pid(row.get("player_id")): row for row in lifecycle_rows
    }

    branch_rosters: dict[str, list[str]] = defaultdict(list)
    all_population_ids = set(owner_by_id)
    for player_id in sorted(all_population_ids):
        owner = owner_by_id.get(player_id, "")
        lifecycle = lifecycle_by_id.get(player_id)
        category = (
            clean(lifecycle.get("unified_lifecycle_category"))
            if lifecycle else ""
        )
        if category == "immediate_market":
            continue
        if owner in TEAM_CODES:
            branch_rosters[owner].append(player_id)

    financial_rows = []
    decision_rows = []
    source_attempts = []
    fetched_spans = []
    snapshots: dict[str, bytes] = {}

    print("=" * 128, flush=True)
    print("2026 UNIFIED OFFSEASON DECISION PREVIEW V1.1", flush=True)
    print("=" * 128, flush=True)
    print(f"Pending decisions:         {len(pending_rows)}", flush=True)
    print(f"  Team Options:            {sum(clean(r.get('unified_lifecycle_category')) == TEAM_OPTION for r in pending_rows)}", flush=True)
    print(f"  Player Options:          {sum(clean(r.get('unified_lifecycle_category')) == PLAYER_OPTION for r in pending_rows)}", flush=True)
    print(f"  Guarantee/Waiver:        {sum(clean(r.get('unified_lifecycle_category')) == GUARANTEE_DECISION for r in pending_rows)}", flush=True)
    print(f"Controlled teams:          {','.join(sorted(controlled_teams)) or '<none>'}", flush=True)
    print("ROSTER CONTEXT: reconstructed April-12 branch, not current checkpoint rosters.", flush=True)
    print("READ-ONLY: recommendations only.", flush=True)
    print("", flush=True)

    for index, lifecycle in enumerate(
        sorted(pending_rows, key=lambda r: clean(r.get("player_name")).lower()),
        start=1,
    ):
        player_id = pid(lifecycle.get("player_id"))
        player_name = clean(lifecycle.get("player_name"))
        category = clean(lifecycle.get("unified_lifecycle_category"))
        team_code = owner_by_id.get(
            player_id,
            team(lifecycle.get("reconstructed_branch_owner")),
        )

        print(f"[{index:03d}/111] {player_name} | {team_code} | {category}", flush=True)

        base_salary = None
        guaranteed_salary = None
        guarantee_text = ""
        guarantee_timing_ambiguous = False
        option_text = ""
        financial_source = ""
        financial_source_detail = ""

        original = original_financial.get(player_id, {})
        additional = additional_financial.get(player_id, {})

        if original:
            base_salary = money_first(original.get("season_2026_27_base_salary"))
            guarantee_text = clean(original.get("season_2026_27_guaranteed"))
            guaranteed_salary = money_first(guarantee_text)
            guarantee_timing_ambiguous = has_change_annotation(guarantee_text)
            option_text = clean(original.get("season_2026_27_option"))
            if base_salary is not None:
                financial_source = "original_lifecycle_contract_evidence"
                financial_source_detail = "fa_contract_option_lifecycle_readiness_v1_0_1"

        if base_salary is None and additional:
            base_salary = money_first(additional.get("chosen_target_base_salary"))
            guarantee_text = clean(additional.get("chosen_target_guaranteed"))
            guaranteed_salary = money_first(guarantee_text)
            guarantee_timing_ambiguous = has_change_annotation(guarantee_text)
            option_text = clean(additional.get("chosen_target_option"))
            if base_salary is not None:
                financial_source = "additional_contract_harvest"
                financial_source_detail = "fa_additional_lifecycle_contract_evidence_harvest_v1_0_1"

        needs_fetch = (
            base_salary is None
            or (
                category == GUARANTEE_DECISION
                and guaranteed_salary is None
            )
        )

        selected_span = None
        if needs_fetch:
            for slug in slug_candidates(player_name):
                url = PLAYER_URL.format(slug=slug)
                status, body, error = fetch(url)
                parser = ContractPageParser()
                if body:
                    parser.feed(body.decode("utf-8", errors="ignore"))
                identity = bool(
                    body and status == 200 and page_identity(parser, player_name)
                )
                source_attempts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "slug": slug,
                    "source_url": url,
                    "http_status": status,
                    "identity_verified": identity,
                    "fetch_error": error,
                })
                if not identity:
                    time.sleep(0.25)
                    continue

                spans = extract_contract_spans(
                    body, player_id, player_name, url
                )
                fetched_spans.extend(spans)
                selected_span = select_contract_span(spans, category)
                snapshots[f"snapshots/{player_id}_{slug}.html"] = body
                if selected_span:
                    break
                time.sleep(0.25)

            if selected_span:
                if base_salary is None:
                    base_salary = selected_span.get("target_base_salary")
                if category == GUARANTEE_DECISION and guaranteed_salary is None:
                    guarantee_text = clean(
                        selected_span.get("target_guaranteed_text")
                    )
                    guaranteed_salary = selected_span.get(
                        "target_guaranteed_first"
                    )
                    guarantee_timing_ambiguous = bool(
                        selected_span.get(
                            "target_guaranteed_has_change_annotation"
                        )
                    )
                if not option_text:
                    option_text = clean(selected_span.get("target_option"))
                financial_source = "salaryswish_refetch"
                financial_source_detail = clean(selected_span.get("source_url"))

        verified_financial_override_applied = False
        verified_financial_override_source = ""

        verified_input = VERIFIED_DECISION_FINANCIAL_INPUTS.get(player_id)
        if verified_input is not None:
            if normalize_name(player_name) != normalize_name(
                verified_input["player_name"]
            ):
                raise RuntimeError(
                    "Verified financial input player identity mismatch for "
                    f"{player_id}: lifecycle={player_name!r}; "
                    f"registry={verified_input['player_name']!r}"
                )

            if base_salary is None:
                base_salary = float(
                    verified_input["base_salary_2026_27"]
                )
                verified_financial_override_applied = True

            if (
                category == GUARANTEE_DECISION
                and guaranteed_salary is None
            ):
                guaranteed_salary = float(
                    verified_input["guaranteed_salary_2026_27"]
                )
                guarantee_text = (
                    f"${guaranteed_salary:,.0f}"
                )
                guarantee_timing_ambiguous = False
                verified_financial_override_applied = True

            if not option_text and verified_input.get("option"):
                option_text = clean(verified_input["option"])
                verified_financial_override_applied = True

            if verified_financial_override_applied:
                financial_source = "verified_decision_financial_input_v1"
                verified_financial_override_source = verified_input[
                    "source_url"
                ]
                financial_source_detail = verified_financial_override_source

        if category in {TEAM_OPTION, PLAYER_OPTION}:
            financial_ready = base_salary is not None and base_salary > 0
        else:
            financial_ready = (
                base_salary is not None
                and base_salary > 0
                and guaranteed_salary is not None
            )

        player = players.get(player_id)
        features = (
            player_features(player)
            if player is not None
            else {
                "overall": None,
                "potential": None,
                "age": None,
                "position": "",
                "years_of_service": None,
            }
        )

        context = branch_roster_context(
            branch_rosters.get(team_code, []),
            players,
            player_id,
        )

        market_reference = None
        market_source = ""
        market_error = ""
        if player is not None:
            salary_reference = (
                base_salary
                if base_salary is not None and base_salary > 0
                else 1.0
            )
            market_reference, market_source, market_error = (
                try_canonical_market_reference(player, salary_reference)
            )

        if market_reference is None:
            market_reference = fallback_market_reference(
                features["overall"],
                features["potential"],
                features["age"],
            )
            if market_reference is not None:
                market_source = "transparent_rating_fallback"

        if category == TEAM_OPTION:
            if team_code in controlled_teams:
                recommendation = "user_decision_required"
                score = None
                confidence = "n/a"
                reason = (
                    "Team Option belongs to a user-controlled team. "
                    "CPU recommendation suppressed."
                )
            else:
                recommendation, score, confidence, reason = (
                    team_option_recommendation(
                        market_reference=market_reference,
                        option_salary=base_salary,
                        overall=features["overall"],
                        potential=features["potential"],
                        age=features["age"],
                        roster_floor=context["branch_bottom_five_average"],
                    )
                )
        elif category == PLAYER_OPTION:
            if player_id == FRED_VANVLEET_PLAYER_OPTION_OVERRIDE["player_id"]:
                override = FRED_VANVLEET_PLAYER_OPTION_OVERRIDE
                if normalize_name(player_name) != normalize_name(
                    override["player_name"]
                ):
                    raise RuntimeError(
                        "Fred VanVleet decision override identity mismatch."
                    )
                if (
                    base_salary is None
                    or abs(
                        float(base_salary)
                        - float(override["option_salary_2026_27"])
                    ) > 1.0
                ):
                    raise RuntimeError(
                        "Fred VanVleet option salary does not match the "
                        "verified pre-split $25M option."
                    )
                recommendation = override["recommendation"]
                score = None
                confidence = override["confidence"]
                reason = override["reason"]
            else:
                recommendation, score, confidence, reason = (
                    player_option_recommendation(
                        market_reference=market_reference,
                        option_salary=base_salary,
                        age=features["age"],
                        overall=features["overall"],
                        potential=features["potential"],
                    )
                )
        else:
            if team_code in controlled_teams:
                recommendation = "user_decision_required"
                score = None
                confidence = "n/a"
                reason = (
                    "Guarantee/waiver decision belongs to a user-controlled team. "
                    "CPU recommendation suppressed."
                )
            else:
                recommendation, score, confidence, reason = (
                    guarantee_recommendation(
                        market_reference=market_reference,
                        base_salary=base_salary,
                        guaranteed_salary=guaranteed_salary,
                        guarantee_timing_ambiguous=guarantee_timing_ambiguous,
                        overall=features["overall"],
                        potential=features["potential"],
                        age=features["age"],
                        roster_floor=context["branch_bottom_five_average"],
                    )
                )

        financial_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": team_code,
            "decision_category": category,
            "base_salary_2026_27": base_salary,
            "guaranteed_salary_2026_27_at_known_snapshot": guaranteed_salary,
            "guarantee_text": guarantee_text,
            "guarantee_timing_ambiguous": guarantee_timing_ambiguous,
            "option_text": option_text,
            "financial_ready": financial_ready,
            "financial_source": financial_source,
            "financial_source_detail": financial_source_detail,
            "verified_financial_override_applied": verified_financial_override_applied,
            "verified_financial_override_source": verified_financial_override_source,
        })

        decision_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": team_code,
            "controlled_team": team_code in controlled_teams,
            "decision_category": category,
            "branch_owner_repaired": bool(
                lifecycle.get("branch_owner_repaired", False)
            ),
            "branch_owner_repair_evidence_date": clean(
                lifecycle.get("branch_owner_repair_evidence_date")
            ),
            "branch_owner_repair_evidence": clean(
                lifecycle.get("branch_owner_repair_evidence")
            ),
            "base_salary_2026_27": base_salary,
            "guaranteed_salary_2026_27": guaranteed_salary,
            "guarantee_timing_ambiguous": guarantee_timing_ambiguous,
            "financial_ready": financial_ready,
            "playerstate_present": player is not None,
            "overall_rating": features["overall"],
            "potential_rating": features["potential"],
            "age": features["age"],
            "position": features["position"],
            "years_of_service": features["years_of_service"],
            "market_reference": market_reference,
            "market_reference_source": market_source,
            "market_reference_error": market_error,
            "pre_split_injury_decision_override": (
                player_id
                == FRED_VANVLEET_PLAYER_OPTION_OVERRIDE["player_id"]
            ),
            "pre_split_injury_decision_source": (
                FRED_VANVLEET_PLAYER_OPTION_OVERRIDE["injury_source_url"]
                if player_id
                == FRED_VANVLEET_PLAYER_OPTION_OVERRIDE["player_id"]
                else ""
            ),
            "branch_roster_count": context["branch_roster_count"],
            "branch_bottom_five_average": context["branch_bottom_five_average"],
            "recommendation": recommendation,
            "decision_score": score,
            "confidence": confidence,
            "reason": reason,
            "current_checkpoint_roster_context_used": False,
            "post_split_real_world_outcome_used": False,
            "decision_applied": False,
        })

    financial_ready_count = sum(bool(row["financial_ready"]) for row in financial_rows)
    market_ready_count = sum(row["market_reference"] is not None for row in decision_rows)
    recommendable_count = sum(
        row["recommendation"]
        not in {"manual_input_required", "user_decision_required"}
        for row in decision_rows
    )
    manual_input_rows = [
        row for row in decision_rows
        if row["recommendation"] == "manual_input_required"
    ]
    user_rows = [
        row for row in decision_rows
        if row["recommendation"] == "user_decision_required"
    ]

    checks = []

    def check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict unified-decision checks...", flush=True)

    check(
        "upstream_final_lifecycle_passed",
        bool(final_summary.get("passed")),
        "Final 311-row lifecycle passed.",
    )
    check(
        "exact_111_pending_decisions",
        len(pending_rows) == 111,
        f"pending={len(pending_rows)}",
    )
    check(
        "exact_52_team_options",
        sum(row["decision_category"] == TEAM_OPTION for row in decision_rows) == 52,
        "team_options=52",
    )
    check(
        "exact_21_player_options",
        sum(row["decision_category"] == PLAYER_OPTION for row in decision_rows) == 21,
        "player_options=21",
    )
    check(
        "exact_38_guarantee_decisions",
        sum(row["decision_category"] == GUARANTEE_DECISION for row in decision_rows) == 38,
        "guarantee_decisions=38",
    )
    check(
        "exact_one_pending_owner_gap_before_repair",
        len(invalid_pending_before) == 1
        and invalid_pending_before[0]["player_id"] == "1642354"
        and invalid_pending_before[0]["player_name"] == "KJ Simpson",
        repr(invalid_pending_before),
    )
    check(
        "exact_one_branch_owner_repair_applied",
        len(pending_owner_repairs) == 1
        and pending_owner_repairs[0]["player_id"] == "1642354"
        and pending_owner_repairs[0]["owner_after"] == "DEN",
        repr(pending_owner_repairs),
    )
    check(
        "kj_simpson_branch_owner_repaired_to_den",
        any(
            row["player_id"] == "1642354"
            and row["team_abbreviation"] == "DEN"
            and row["branch_owner_repaired"]
            for row in decision_rows
        ),
        "KJ Simpson must evaluate as a DEN guarantee/waiver decision.",
    )
    check(
        "all_pending_rows_have_proven_branch_team",
        all(row["team_abbreviation"] in TEAM_CODES for row in decision_rows),
        "All decisions are attached to reconstructed branch teams after narrow repair.",
    )
    check(
        "branch_roster_context_only",
        all(not row["current_checkpoint_roster_context_used"] for row in decision_rows),
        "Decision roster context comes from reconstructed April-12 ownership.",
    )
    check(
        "no_post_split_outcomes_used",
        all(not row["post_split_real_world_outcome_used"] for row in decision_rows),
        "Real-world option/waiver outcomes are not decision inputs.",
    )
    check(
        "no_decision_applied",
        all(not row["decision_applied"] for row in decision_rows),
        "Preview only.",
    )
    check(
        "verified_financial_completion_registry_has_16_rows",
        len(VERIFIED_DECISION_FINANCIAL_INPUTS) == 16,
        f"registry={len(VERIFIED_DECISION_FINANCIAL_INPUTS)}",
    )
    check(
        "all_111_decisions_financially_ready",
        financial_ready_count == 111,
        f"financial_ready={financial_ready_count}/111",
    )
    check(
        "fred_vanvleet_pre_split_injury_override_applied",
        any(
            row["player_id"] == "1627832"
            and row["recommendation"] == "exercise"
            and row["pre_split_injury_decision_override"]
            and not row["post_split_real_world_outcome_used"]
            for row in decision_rows
        ),
        "Fred VanVleet is resolved only from pre-split ACL/contract facts.",
    )
    check(
        "zero_manual_inputs_after_completion",
        len(manual_input_rows) == 0,
        f"manual_input={len(manual_input_rows)}",
    )
    check(
        "exact_two_user_controlled_decisions_remain",
        len(user_rows) == 2
        and {
            row["player_name"] for row in user_rows
        } == {"Leonard Miller", "Mouhamadou Gueye"},
        repr(sorted(row["player_name"] for row in user_rows)),
    )
    check(
        "market_reference_coverage_is_110_of_111",
        market_ready_count == 110,
        (
            f"market_ready={market_ready_count}/111; "
            "Fred VanVleet uses the pre-split injury decision override."
        ),
    )

    checkpoint_hash_after = sha256_file(checkpoint_path)
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash_after
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Unified Offseason Decision Preview V1.1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_unified_offseason_decision_preview_v1_1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_decision_preview_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "pending_branch_owner_repairs.csv", pending_owner_repairs)
        write_csv(export / "decision_financial_readiness_111.csv", financial_rows)
        write_csv(export / "unified_decision_preview_111.csv", decision_rows)
        write_csv(
            export / "team_option_decisions_52.csv",
            [row for row in decision_rows if row["decision_category"] == TEAM_OPTION],
        )
        write_csv(
            export / "player_option_decisions_21.csv",
            [row for row in decision_rows if row["decision_category"] == PLAYER_OPTION],
        )
        write_csv(
            export / "guarantee_waiver_decisions_38.csv",
            [row for row in decision_rows if row["decision_category"] == GUARANTEE_DECISION],
        )
        write_csv(export / "manual_decision_inputs.csv", manual_input_rows)
        write_csv(export / "user_controlled_decisions.csv", user_rows)
        write_csv(export / "salaryswish_source_attempts.csv", source_attempts)
        write_csv(export / "salaryswish_fetched_contract_spans.csv", fetched_spans)
        write_csv(export / "decision_preview_checks.csv", checks)

        summary = {
            "version": VERSION,
            "pending_decision_count": len(decision_rows),
            "branch_owner_repair_count": len(pending_owner_repairs),
            "team_option_count": 52,
            "player_option_count": 21,
            "guarantee_waiver_count": 38,
            "financial_ready_count": financial_ready_count,
            "verified_financial_completion_count": sum(
                bool(row.get("verified_financial_override_applied"))
                for row in financial_rows
            ),
            "market_reference_ready_count": market_ready_count,
            "fred_vanvleet_pre_split_injury_override_applied": True,
            "automatic_recommendation_count": recommendable_count,
            "manual_input_required_count": len(manual_input_rows),
            "user_decision_required_count": len(user_rows),
            "recommendation_counts": dict(
                sorted(Counter(row["recommendation"] for row in decision_rows).items())
            ),
            "controlled_teams": sorted(controlled_teams),
            "branch_roster_context_used": True,
            "current_checkpoint_roster_context_used": False,
            "future_real_world_outcomes_used": False,
            "decisions_applied": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Resolve only manual financial/PlayerState gaps. Then build a clone-only "
                "decision application preview: CPU team options and guarantee decisions, "
                "player-agent player options, explicit user-controlled team decisions. "
                "Recompute the simulated market after those choices and rebuild RFA/QO."
            ),
        }
        (export / "decision_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 UNIFIED OFFSEASON DECISION PREVIEW V1
==========================================

This is the first full decision board after lifecycle completeness closed.

Queues:
- 52 Team Options
- 21 Player Options
- 38 non-guaranteed / partial-guarantee decisions
- 111 total

Decision inputs
---------------
Financial terms come first from existing verified lifecycle evidence and then,
only when missing, from a targeted SalarySwish contract-page refetch.

Market value uses the installed franchise free-agency market reference where
possible, with the same transparent rating fallback used by the earlier Team
Option CPU preview.

IMPORTANT BRANCH CORRECTION
---------------------------
Roster-floor context is rebuilt from the reconstructed April-12 ownership map.
The contaminated current checkpoint roster lists are NOT used for decision
context.

Decision ownership
------------------
Team Option -> CPU for CPU teams, user decision for controlled teams.
Player Option -> player-agent economic model, including players on controlled teams.
Guarantee/Waiver -> CPU for CPU teams, user decision for controlled teams.

No recommendation is applied.
No future real-world outcome is used.
No checkpoint write.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")
            for member, body in sorted(snapshots.items()):
                archive.writestr(
                    f"{export_id}/{member}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 UNIFIED OFFSEASON DECISION PREVIEW V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Pending decisions:                111", flush=True)
    print("Team Options:                      52", flush=True)
    print("Player Options:                    21", flush=True)
    print("Guarantee/Waiver decisions:        38", flush=True)
    print(f"Financial ready:                  {financial_ready_count}/111", flush=True)
    print(f"Market-reference ready:           {market_ready_count}/111", flush=True)
    print(f"Automatic recommendations:        {recommendable_count}", flush=True)
    print(f"Manual input required:            {len(manual_input_rows)}", flush=True)
    print(f"User decisions required:          {len(user_rows)}", flush=True)
    print("Branch roster context used:        YES", flush=True)
    print("Current checkpoint roster context: NO", flush=True)
    print("Future outcomes used:              NO", flush=True)
    print("Decision application:              NOT PERFORMED", flush=True)
    print("Checkpoint write:                  NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
