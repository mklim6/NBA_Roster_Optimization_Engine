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

VERSION = "fa-contract-option-lifecycle-readiness-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)

BASE = "https://www.salaryswish.com"
PLAYER_URL = BASE + "/players/{slug}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

FREE_AGENT_STATES = {
    "free_agent_contract_expiry",
    "free_agent_rookie_scale_option_declined_pre_split",
    "free_agent_team_option_declined_pre_split",
    "free_agent_player_option_declined_pre_split",
    "free_agent_eto_exercised_pre_split",
    "free_agent_waiver_terminated",
    "free_agent_ten_day",
}

PENDING_STATES = {
    "pending_team_option_2026_27",
    "pending_player_option_2026_27",
    "pending_eto_2026_27",
    "pending_non_guaranteed_contract_decision_2026_27",
}

UNDER_CONTRACT_STATES = {
    "under_contract_guaranteed_2026_27",
    "under_contract_option_exercised_pre_split",
}

SLUG_OVERRIDES = {
    "Cameron Payne": ["cam-payne"],
    "Bruce Brown": ["bruce-brown-jr"],
    "Xavier Tillman": ["xavier-tillman-sr"],
    "KJ Simpson": ["k-j-simpson"],
    "Darius Brown II": ["darius-brown"],
    "Trey Jemison III": ["trey-jemison"],
    "Gary Payton II": ["gary-payton-ii"],
    "Kevin McCullar Jr.": ["kevin-mccullar-jr"],
    "A.J. Lawson": ["a-j-lawson", "aj-lawson"],
    "David Jones Garcia": ["david-jones-garcia", "david-jones"],
}

KNOWN_EXPECTATIONS = {
    "Egor Demin": "under_contract_guaranteed_2026_27",
    "Jett Howard": "free_agent_rookie_scale_option_declined_pre_split",
    "Kobe Brown": "free_agent_rookie_scale_option_declined_pre_split",
    "Nick Smith Jr.": "pending_team_option_2026_27",
    "Jahmir Young": "pending_team_option_2026_27",
    "Mouhamadou Gueye": "pending_team_option_2026_27",
}


class IdentityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        self.text_parts.append(text)
        if self.in_title:
            self.title_parts.append(text)
        if self.in_h1:
            self.h1_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts)

    @property
    def h1(self) -> str:
        return " ".join(self.h1_parts)

    @property
    def page_text(self) -> str:
        return "\n".join(self.text_parts)


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.depth = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == "tr":
            self.row = []
        elif self.depth == 1 and self.row is not None and tag in {"td", "th"}:
            self.cell = []
        elif self.cell is not None and tag == "br":
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.depth == 1 and self.cell is not None and tag in {"td", "th"}:
            assert self.row is not None
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif self.depth == 1 and self.row is not None and tag == "tr":
            if self.table is not None and any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            if self.depth == 1 and self.table is not None:
                self.tables.append(self.table)
                self.table = None
            self.depth -= 1


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(two-way\)", "", text)
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def names_equivalent(a: str, b: str) -> bool:
    na = norm_name(a)
    nb = norm_name(b)
    if na == nb:
        return True
    suffixes = (" jr", " sr", " ii", " iii", " iv", " v")
    for suffix in suffixes:
        if na.endswith(suffix):
            na = na[:-len(suffix)]
        if nb.endswith(suffix):
            nb = nb[:-len(suffix)]
    return na == nb


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def slug_candidates(name: str) -> list[str]:
    result: list[str] = []
    for item in SLUG_OVERRIDES.get(name, []):
        if item not in result:
            result.append(item)
    base = slugify(name)
    for item in (
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("dj-", "d-j-"),
    ):
        item = item.strip("-")
        if item and item not in result:
            result.append(item)
    return result


def finite_positive(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 and number == number else None


def money_or_zero(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.split("→")[-1]
    match = re.search(r"-?\d[\d,.]*", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


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


def parse_date_text(value: str) -> date | None:
    text = clean(value)
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def option_decision(value: Any) -> tuple[str, date | None]:
    text = clean(value)
    if not text:
        return "", None
    state = ""
    low = text.lower()
    if low.startswith("yes"):
        state = "yes"
    elif low.startswith("no"):
        state = "no"
    date_match = re.search(r"\(([^)]+)\)", text)
    decision_date = parse_date_text(date_match.group(1)) if date_match else None
    return state, decision_date


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


def page_identity(body: bytes, player_name: str) -> tuple[bool, str, str]:
    if not body:
        return False, "", ""
    parser = IdentityParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    target = norm_name(player_name)
    identity = bool(
        target and (
            target in norm_name(parser.title)
            or target in norm_name(parser.h1)
            or target in norm_name(parser.page_text[:120000])
        )
    )
    if not identity:
        identity = any(
            names_equivalent(player_name, candidate)
            for candidate in (parser.title, parser.h1)
            if candidate
        )
    return identity, parser.title, parser.h1


def fetch_verified_page(player_name: str) -> tuple[str, str, int, bytes, str, bool, str, str]:
    last = ("", "", 0, b"", "", False, "", "")
    for slug in slug_candidates(player_name):
        url = PLAYER_URL.format(slug=slug)
        status, body, error = fetch(url)
        identity, title, h1 = page_identity(body, player_name)
        last = (slug, url, status, body, error, identity, title, h1)
        if status == 200 and body and identity:
            return last
        time.sleep(0.3)
    return last


def strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", clean(cell).lower()).strip("_")
        for cell in row
    ]


def parse_contract_blocks(html_text: str) -> list[dict[str, Any]]:
    parts = html_text.split('<div class="sw_playerContract__wrapper">')[1:]
    blocks: list[dict[str, Any]] = []

    for part in parts:
        title_match = re.search(
            r"sw_playerContract__title[^>]*>(.*?)</h6>",
            part,
            flags=re.IGNORECASE | re.DOTALL,
        )
        contract_type = strip_html(title_match.group(1)) if title_match else ""
        page_text = strip_html(part[:120000])

        signing_match = re.search(
            r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            page_text,
        )
        signing_date = parse_date_text(signing_match.group(1)) if signing_match else None

        team_match = re.search(r"Signing Team\s*:\s*([A-Z]{3})(?:\s|$)", page_text)
        method_match = re.search(
            r"Signing Method\s*:\s*(.*?)\s+Signing Date\s*:",
            page_text,
        )
        expiry_match = re.search(
            r"Expiry Status\s*:\s*(.*?)\s+(?:AAV|Cap %|Signing Team|COMPARE)",
            page_text,
            flags=re.IGNORECASE,
        )

        terminal_kind = ""
        terminal_date = None
        terminal_patterns = [
            ("waived", r"WAIVED:\s*.*?\-\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\)"),
            ("voided_conversion", r"VOIDED DUE TO CONVERSION:\s*.*?\-\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\)"),
            ("terminated", r"CONTRACT TERMINATED:\s*.*?\-\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\)"),
        ]
        for kind, pattern in terminal_patterns:
            match = re.search(pattern, page_text, flags=re.IGNORECASE)
            if match:
                terminal_kind = kind
                terminal_date = parse_date_text(match.group(1))
                break

        parser = TableParser()
        parser.feed(part)
        seasons: dict[str, dict[str, Any]] = {}

        for table in parser.tables:
            if not table:
                continue
            header = normalize_header(table[0])
            if "season" not in header:
                continue

            index = {name: i for i, name in enumerate(header)}
            for row in table[1:]:
                season_i = index.get("season")
                if season_i is None or season_i >= len(row):
                    continue
                season_raw = clean(row[season_i])
                match = re.match(r"^(20\d{2}-\d{2})", season_raw)
                if not match:
                    continue
                season = match.group(1)

                def cell(key: str) -> str:
                    i = index.get(key)
                    return clean(row[i]) if i is not None and i < len(row) else ""

                option = cell("option")
                option_used = cell("option_used")
                base_salary = money_or_zero(cell("base_salary"))
                guaranteed = money_or_zero(cell("guaranteed"))
                cap_hit = money_or_zero(cell("cap_hit"))
                decision_state, decision_date = option_decision(option_used)

                seasons[season] = {
                    "season_raw": season_raw,
                    "option": option,
                    "option_used": option_used,
                    "option_decision_state": decision_state,
                    "option_decision_date": decision_date,
                    "base_salary": base_salary,
                    "guaranteed": guaranteed,
                    "cap_hit": cap_hit,
                }

        blocks.append({
            "contract_type": contract_type,
            "signing_date": signing_date,
            "signing_team": clean(team_match.group(1)) if team_match else "",
            "signing_method": clean(method_match.group(1)) if method_match else "",
            "expiry_status": clean(expiry_match.group(1)) if expiry_match else "",
            "terminal_kind": terminal_kind,
            "terminal_date": terminal_date,
            "seasons": seasons,
        })

    return blocks


def block_active_at_split(block: Mapping[str, Any]) -> bool:
    signing_date = block.get("signing_date")
    if signing_date is None or signing_date > SIMULATION_SPLIT_DATE:
        return False
    terminal_date = block.get("terminal_date")
    if terminal_date is not None and terminal_date <= SIMULATION_SPLIT_DATE:
        return False
    return True


def latest_active_pre_split_contract(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        block for block in blocks
        if block_active_at_split(block)
        and (
            "2025-26" in block.get("seasons", {})
            or "2026-27" in block.get("seasons", {})
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda block: block["signing_date"])


def classify_lifecycle(
    registry_row: Mapping[str, Any],
    contract: Mapping[str, Any] | None,
) -> tuple[str, str, bool, bool]:
    category = clean(registry_row.get("free_agent_category"))

    # Terminal special FA categories already proven by the rights campaign
    # override stale salary rows from a terminated contract.
    if category == "waiver_terminated_free_agent":
        return (
            "free_agent_waiver_terminated",
            "Existing rights evidence proves the player's contract was terminated through waivers before the simulation split.",
            True,
            False,
        )
    if category == "ten_day_free_agent":
        return (
            "free_agent_ten_day",
            "Existing rights evidence proves the player's last applicable contract was a completed/expired 10-Day Contract.",
            True,
            False,
        )

    if contract is None:
        return (
            "manual_review_no_verified_active_contract",
            "No identity-verified pre-split active contract block could be resolved.",
            False,
            False,
        )

    row_2026 = contract.get("seasons", {}).get("2026-27")
    contract_type = clean(contract.get("contract_type"))
    is_rookie_scale = "rookie scale" in contract_type.lower()

    if row_2026 is None:
        return (
            "free_agent_contract_expiry",
            "Latest active pre-split contract contains no 2026-27 season, so it expires after 2025-26.",
            True,
            False,
        )

    option = clean(row_2026.get("option")).lower()
    decision = clean(row_2026.get("option_decision_state")).lower()
    decision_date = row_2026.get("option_decision_date")
    base_salary = row_2026.get("base_salary")
    guaranteed = row_2026.get("guaranteed")

    decision_known_pre_split = (
        decision in {"yes", "no"}
        and decision_date is not None
        and decision_date <= SIMULATION_SPLIT_DATE
    )
    decision_known_post_split = (
        decision in {"yes", "no"}
        and decision_date is not None
        and decision_date > SIMULATION_SPLIT_DATE
    )

    if option == "team":
        if decision_known_pre_split:
            if decision == "yes":
                return (
                    "under_contract_option_exercised_pre_split",
                    f"2026-27 Team Option was exercised on {decision_date.isoformat()}, before the simulation split.",
                    False,
                    False,
                )
            if is_rookie_scale:
                return (
                    "free_agent_rookie_scale_option_declined_pre_split",
                    f"Rookie Scale second Option Year was not exercised on {decision_date.isoformat()}; the CBA's first-round option exception applies.",
                    True,
                    True,
                )
            return (
                "free_agent_team_option_declined_pre_split",
                f"2026-27 Team Option was declined on {decision_date.isoformat()}, before the simulation split.",
                True,
                False,
            )

        if is_rookie_scale and not decision:
            return (
                "manual_review_rookie_scale_option_decision_missing",
                "A 2026-27 Rookie Scale Team Option should have a pre-split exercise/non-exercise decision; source does not prove it.",
                False,
                False,
            )

        return (
            "pending_team_option_2026_27",
            (
                "2026-27 Team Option decision occurs after the simulation split and must be decided by the simulator."
                if decision_known_post_split
                else "2026-27 Team Option remained unresolved at the simulation split."
            ),
            False,
            False,
        )

    if option == "player":
        if decision_known_pre_split:
            if decision == "yes":
                return (
                    "under_contract_option_exercised_pre_split",
                    f"2026-27 Player Option was exercised on {decision_date.isoformat()}, before the simulation split.",
                    False,
                    False,
                )
            return (
                "free_agent_player_option_declined_pre_split",
                f"2026-27 Player Option was declined on {decision_date.isoformat()}, before the simulation split.",
                True,
                False,
            )
        return (
            "pending_player_option_2026_27",
            (
                "2026-27 Player Option decision is post-split and belongs to the simulator."
                if decision_known_post_split
                else "2026-27 Player Option remained unresolved at the simulation split."
            ),
            False,
            False,
        )

    if option in {"eto", "early termination", "early termination option"}:
        if decision_known_pre_split:
            if decision == "yes":
                return (
                    "free_agent_eto_exercised_pre_split",
                    f"2026-27 ETO was exercised on {decision_date.isoformat()}, ending the contract.",
                    True,
                    False,
                )
            return (
                "under_contract_option_exercised_pre_split",
                f"2026-27 ETO was not exercised on {decision_date.isoformat()}, so the contract continues.",
                False,
                False,
            )
        return (
            "pending_eto_2026_27",
            (
                "ETO decision is post-split and belongs to the simulator."
                if decision_known_post_split
                else "ETO remained unresolved at the simulation split."
            ),
            False,
            False,
        )

    # A 2026-27 season with no option is still a live contract. If fully
    # protected at split, it is unambiguously under contract. If not fully
    # protected, it stays outside the free-agent market until the team makes
    # the relevant waive/guarantee decision.
    if base_salary is not None:
        if guaranteed is not None and guaranteed >= base_salary - 1:
            return (
                "under_contract_guaranteed_2026_27",
                "Pre-split contract includes a fully protected 2026-27 season with no option.",
                False,
                False,
            )
        return (
            "pending_non_guaranteed_contract_decision_2026_27",
            "Pre-split contract contains a 2026-27 non-guaranteed/partially guaranteed season; player is not yet a free agent at the split.",
            False,
            False,
        )

    return (
        "manual_review_future_contract_terms_unclear",
        "Contract contains a 2026-27 row but its option/protection state could not be resolved safely.",
        False,
        False,
    )


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required input: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix_fragment: str) -> list[dict[str, str]]:
    member = next(
        (name for name in archive.namelist() if suffix_fragment in Path(name).name),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing member containing {suffix_fragment}")
    return list(csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"))))


def read_json_member(archive: zipfile.ZipFile, suffix_fragment: str) -> dict[str, Any]:
    member = next(
        (name for name in archive.namelist() if suffix_fragment in Path(name).name),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing member containing {suffix_fragment}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"


def collect_cached_contract_snapshots(
    root: Path,
    player_ids: set[str],
) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    audits = root / "outputs" / "audits"
    if not audits.exists():
        return cache

    zip_paths = sorted(
        [p for p in audits.rglob("*.zip") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for zip_path in zip_paths:
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for member in archive.namelist():
                    if "/snapshots/" not in member or not member.endswith("_contract.html"):
                        continue
                    match = re.search(r"/snapshots/(\d+)_", member)
                    if not match:
                        continue
                    player_id = match.group(1)
                    if player_id not in player_ids or player_id in cache:
                        continue
                    body = archive.read(member)
                    cache[player_id] = {
                        "body": body,
                        "source_kind": "cached_audit_contract_snapshot",
                        "source_ref": f"{zip_path}::{member}",
                        "source_sha256": sha256_bytes(body),
                    }
        except Exception:
            continue

    return cache


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

    registry_zip = find_latest(
        root,
        "fa_rights_registry_v2_preview_2026-27_*.zip",
    )
    rfa_zip = find_latest(
        root,
        "fa_rfa_qo_eligibility_preview_v1_0_2_2026-27_*.zip",
    )
    qo_zip = find_latest(
        root,
        "fa_qo_amount_readiness_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(registry_zip) as archive:
        registry_summary = read_json_member(archive, "final_rights_summary")
        registry_rows = read_csv_member(archive, "final_rights_registry_preview")

    with zipfile.ZipFile(rfa_zip) as archive:
        rfa_summary = read_json_member(archive, "rfa_qo_summary")
        rfa_rows = read_csv_member(archive, "rfa_qo_eligibility_all")

    with zipfile.ZipFile(qo_zip) as archive:
        qo_summary = read_json_member(archive, "qo_amount_summary")

    rfa_by_id = {pid(row.get("player_id")): row for row in rfa_rows}
    player_ids = {pid(row.get("player_id")) for row in registry_rows}

    checkpoint = checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 124, flush=True)
    print("2026 FREE-AGENT UNIVERSE + CONTRACT OPTION LIFECYCLE READINESS V1", flush=True)
    print("=" * 124, flush=True)
    print(f"Rights universe: {registry_zip}", flush=True)
    print(f"RFA preview:     {rfa_zip}", flush=True)
    print(f"QO audit:        {qo_zip}", flush=True)
    print(f"Simulation split: {SIMULATION_SPLIT_DATE.isoformat()}", flush=True)
    print("", flush=True)
    print(
        "READ-ONLY. Post-split real-world option decisions are retained only as audit evidence and never imported as simulator state.",
        flush=True,
    )
    print("", flush=True)

    cache = collect_cached_contract_snapshots(root, player_ids)
    print(f"Cached identity-linked contract snapshots found: {len(cache)}/187", flush=True)

    fetched_snapshots: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    blocks_by_id: dict[str, list[dict[str, Any]]] = {}

    for index, registry in enumerate(sorted(registry_rows, key=lambda r: clean(r.get("player_name")).lower()), start=1):
        player_id = pid(registry.get("player_id"))
        player_name = clean(registry.get("player_name"))

        cached = cache.get(player_id)
        if cached is not None:
            body = cached["body"]
            identity, title, h1 = page_identity(body, player_name)
            if identity:
                source_kind = cached["source_kind"]
                source_ref = cached["source_ref"]
                source_sha = cached["source_sha256"]
                fetch_status = "verified_cached_snapshot"
                blocks = parse_contract_blocks(body.decode("utf-8", errors="ignore"))
                blocks_by_id[player_id] = blocks
                manifest.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "source_sha256": source_sha,
                    "identity_verified": True,
                    "page_title": title,
                    "page_h1": h1,
                    "contract_block_count": len(blocks),
                    "fetch_status": fetch_status,
                })
                print(f"[{index:03d}/187] {player_name}: cached", flush=True)
                continue

        print(f"[{index:03d}/187] {player_name}: fetching", flush=True)
        slug, url, status, body, error, identity, title, h1 = fetch_verified_page(player_name)
        if status == 200 and body and identity:
            blocks = parse_contract_blocks(body.decode("utf-8", errors="ignore"))
            blocks_by_id[player_id] = blocks
            snapshot_name = f"snapshots/{player_id}_{slug}_contract.html"
            fetched_snapshots[snapshot_name] = body
            manifest.append({
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "fresh_salaryswish_contract_page",
                "source_ref": url,
                "source_sha256": sha256_bytes(body),
                "identity_verified": True,
                "page_title": title,
                "page_h1": h1,
                "contract_block_count": len(blocks),
                "fetch_status": "verified_fresh_fetch",
                "fetch_error": "",
            })
        else:
            manifest.append({
                "player_id": player_id,
                "player_name": player_name,
                "source_kind": "fresh_salaryswish_contract_page",
                "source_ref": url,
                "source_sha256": sha256_bytes(body) if body else "",
                "identity_verified": False,
                "page_title": title,
                "page_h1": h1,
                "contract_block_count": 0,
                "fetch_status": "manual_contract_source",
                "fetch_error": error,
                "http_status": status,
            })

        time.sleep(0.3)

    print("", flush=True)
    print("Resolving contract / option lifecycle at simulation split...", flush=True)

    results: list[dict[str, Any]] = []

    for registry in registry_rows:
        player_id = pid(registry.get("player_id"))
        player_name = clean(registry.get("player_name"))
        blocks = blocks_by_id.get(player_id, [])
        contract = latest_active_pre_split_contract(blocks)

        state, reason, is_market_fa, rookie_option_exception = classify_lifecycle(
            registry,
            contract,
        )

        season_row = (
            contract.get("seasons", {}).get("2026-27")
            if contract else None
        )
        option = clean(season_row.get("option")) if season_row else ""
        option_used = clean(season_row.get("option_used")) if season_row else ""
        option_state, option_date = option_decision(option_used)

        post_split_outcome = ""
        if (
            option_date is not None
            and option_date > SIMULATION_SPLIT_DATE
            and option_state in {"yes", "no"}
        ):
            post_split_outcome = f"{option_state}:{option_date.isoformat()}"

        prior_rfa = rfa_by_id.get(player_id, {})
        prior_eligibility = clean(prior_rfa.get("eligibility_status"))
        prior_path = clean(prior_rfa.get("eligibility_path"))

        if state in UNDER_CONTRACT_STATES or state in PENDING_STATES:
            downstream_rfa_status = "exclude_until_contract_lifecycle_resolved"
        elif rookie_option_exception:
            downstream_rfa_status = "force_ufa_rookie_scale_option_exception"
        elif is_market_fa:
            downstream_rfa_status = "re_evaluate_rfa_on_corrected_free_agent_universe"
        else:
            downstream_rfa_status = "manual_review"

        results.append({
            "player_id": player_id,
            "player_name": player_name,
            "rights_registry_status": clean(registry.get("final_status")),
            "rights_classification": clean(registry.get("rights_classification")),
            "free_agent_category": clean(registry.get("free_agent_category")),
            "prior_team": clean(registry.get("prior_team")),
            "contract_lifecycle_state": state,
            "corrected_2026_free_agent_market_candidate": is_market_fa,
            "rookie_scale_first_round_option_exception": rookie_option_exception,
            "downstream_rfa_status": downstream_rfa_status,
            "prior_rfa_eligibility_status": prior_eligibility,
            "prior_rfa_eligibility_path": prior_path,
            "prior_qo_pipeline_invalidated": (
                prior_eligibility == "eligible_if_qo_issued"
                and (
                    not is_market_fa
                    or rookie_option_exception
                )
            ),
            "active_contract_type_at_split": clean(contract.get("contract_type")) if contract else "",
            "active_contract_signing_date": (
                contract["signing_date"].isoformat()
                if contract and contract.get("signing_date") else ""
            ),
            "active_contract_signing_team": clean(contract.get("signing_team")) if contract else "",
            "active_contract_expiry_status_snapshot": clean(contract.get("expiry_status")) if contract else "",
            "season_2026_27_option": option,
            "season_2026_27_option_used_snapshot": option_used,
            "option_decision_date_snapshot": option_date.isoformat() if option_date else "",
            "post_split_option_outcome_observed_for_audit_only": post_split_outcome,
            "post_split_option_outcome_imported_to_simulator": False,
            "season_2026_27_base_salary": season_row.get("base_salary") if season_row else "",
            "season_2026_27_guaranteed": season_row.get("guaranteed") if season_row else "",
            "reason": reason,
        })

    market_rows = [
        row for row in results
        if row["corrected_2026_free_agent_market_candidate"]
    ]
    pending_rows = [
        row for row in results
        if row["contract_lifecycle_state"] in PENDING_STATES
    ]
    under_contract_rows = [
        row for row in results
        if row["contract_lifecycle_state"] in UNDER_CONTRACT_STATES
    ]
    manual_rows = [
        row for row in results
        if row["contract_lifecycle_state"].startswith("manual_review")
    ]
    invalidated_rfa_rows = [
        row for row in results
        if row["prior_qo_pipeline_invalidated"]
    ]
    rookie_exception_rows = [
        row for row in results
        if row["rookie_scale_first_round_option_exception"]
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
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict contract-option lifecycle checks...", flush=True)

    check(
        "upstream_rights_registry_passed",
        bool(registry_summary.get("passed")),
        "Contract lifecycle starts from the passed 187-player rights evidence universe.",
    )
    check(
        "upstream_rfa_preview_passed",
        bool(rfa_summary.get("passed")),
        "Prior RFA preview is used only as a comparison target.",
    )
    check(
        "upstream_qo_amount_audit_passed",
        bool(qo_summary.get("passed")),
        "QO audit passed its own checks but is explicitly downstream of this lifecycle correction.",
    )
    check(
        "exact_187_player_universe_preserved",
        len(results) == 187 and len({row["player_id"] for row in results}) == 187,
        f"rows={len(results)}",
    )
    check(
        "accepted_contract_pages_are_identity_verified",
        all(
            row["identity_verified"]
            for row in manifest
            if row["fetch_status"] in {"verified_cached_snapshot", "verified_fresh_fetch"}
        ),
        "No generic or mismatched player page enters contract evidence.",
    )
    check(
        "post_split_option_outcomes_are_never_imported",
        all(
            not row["post_split_option_outcome_imported_to_simulator"]
            for row in results
        ),
        "June/July 2026 real-world option decisions remain audit-only.",
    )
    check(
        "pending_options_are_not_free_agents_yet",
        all(
            not row["corrected_2026_free_agent_market_candidate"]
            for row in pending_rows
        ),
        "Counterfactual option decisions must happen inside the simulator first.",
    )
    check(
        "under_contract_players_are_not_free_agents",
        all(
            not row["corrected_2026_free_agent_market_candidate"]
            for row in under_contract_rows
        ),
        "Guaranteed/exercised 2026-27 contracts are excluded from the market.",
    )
    check(
        "rookie_scale_decline_exception_never_enters_ordinary_rfa_path",
        all(
            row["downstream_rfa_status"] == "force_ufa_rookie_scale_option_exception"
            for row in rookie_exception_rows
        ),
        "Article XI first-round option exception is explicit.",
    )

    # Known-case checks must use the same Unicode-insensitive normalization
    # as page identity. Exact display-string lookup incorrectly misses
    # "Egor Dëmin" when the expectation table says "Egor Demin".
    by_normalized_name = {
        norm_name(row["player_name"]): row
        for row in results
    }
    for name, expected in KNOWN_EXPECTATIONS.items():
        matched = by_normalized_name.get(norm_name(name), {})
        actual = clean(matched.get("contract_lifecycle_state"))
        observed_name = clean(matched.get("player_name"))
        check(
            f"known_case_{re.sub(r'[^a-z0-9]+', '_', norm_name(name)).strip('_')}",
            actual == expected,
            (
                f"expected={expected}; actual={actual}; "
                f"observed_player_name={observed_name or '<not found>'}"
            ),
        )

    check(
        "checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        checkpoint_after,
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        overlay_after or "<absent>",
    )

    coverage = sum(
        row["fetch_status"] in {"verified_cached_snapshot", "verified_fresh_fetch"}
        for row in manifest
    )
    coverage_misses = [
        clean(row.get("player_name"))
        for row in manifest
        if row["fetch_status"] not in {
            "verified_cached_snapshot",
            "verified_fresh_fetch",
        }
    ]
    check(
        "contract_evidence_coverage",
        coverage == 187,
        (
            f"verified={coverage}/187; "
            f"manual_sources={'|'.join(coverage_misses) or '<none>'}"
        ),
        severity="coverage",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Contract Option Lifecycle Readiness V1.0.1 failed strict checks: "
            + ", ".join(failed)
        )

    state_counts = Counter(row["contract_lifecycle_state"] for row in results)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_contract_option_lifecycle_readiness_v1_0_1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="faoptlife_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "contract_option_lifecycle_all.csv", results)
        write_csv(export / "corrected_free_agent_market_candidates.csv", market_rows)
        write_csv(export / "pending_contract_option_decisions.csv", pending_rows)
        write_csv(export / "under_contract_2026_27.csv", under_contract_rows)
        write_csv(export / "contract_option_manual_review.csv", manual_rows)
        write_csv(export / "rookie_scale_option_exception_rows.csv", rookie_exception_rows)
        write_csv(export / "prior_rfa_qo_rows_invalidated.csv", invalidated_rfa_rows)
        write_csv(export / "contract_option_source_manifest.csv", manifest)
        write_csv(export / "contract_option_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "total_input_universe": len(results),
            "contract_lifecycle_state_counts": dict(sorted(state_counts.items())),
            "corrected_free_agent_market_candidate_count": len(market_rows),
            "pending_contract_option_decision_count": len(pending_rows),
            "under_contract_2026_27_count": len(under_contract_rows),
            "manual_review_count": len(manual_rows),
            "rookie_scale_option_exception_count": len(rookie_exception_rows),
            "prior_rfa_qo_rows_invalidated_count": len(invalidated_rfa_rows),
            "contract_evidence_verified_count": coverage,
            "contract_evidence_manual_count": 187 - coverage,
            "contract_evidence_manual_players": coverage_misses,
            "post_split_option_outcomes_imported": 0,
            "qo_amount_v1_should_not_be_used_for_live_decisions": True,
            "qo_amount_v1_additional_known_issue": (
                "The four 2022 first-round rookie-scale finishers must use "
                "the Rookie Salary Scale applicable to their 2017-CBA-era "
                "Rookie Scale Contracts, not the 2023 CBA Exhibit B percentage table."
            ),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "state_mutation_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Rebuild the 2026 free-agent rights/RFA universe from corrected "
                "contract-option states. Resolve simulator Team/Player option "
                "decisions before QO issuance. Rebuild rookie-scale QO amounts "
                "using the scale applicable to each 2022 Rookie Scale Contract."
            ),
        }
        (export / "contract_option_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """2026 FREE-AGENT UNIVERSE + CONTRACT OPTION LIFECYCLE READINESS V1
================================================================

WHY THIS SLICE EXISTS
---------------------
The prior QO amount audit passed its own checks, but deeper review found that
the upstream free-agent universe was being evaluated before unresolved
2026-27 contract options.

Examples:
- Egor Demin has a guaranteed 2026-27 Rookie Scale season and is not a 2026 FA.
- Jett Howard and Kobe Brown had their 2026-27 Rookie Scale second options
  declined before the April 12 simulation split. They become UFAs and are
  excluded from the ordinary <=3-YOS RFA pathway.
- Nick Smith Jr., Jahmir Young, and Mouhamadou Gueye had 2026-27 Team Options
  embedded in pre-split contracts, with the real-world decisions occurring
  after the simulation split. Those decisions belong to the simulator.

THIS PACKAGE
------------
Reconciles all 187 apparent free-agent candidates against their actual
pre-split contract state.

States include:
- under contract guaranteed
- option exercised before split
- pending Team Option
- pending Player Option
- pending ETO
- pending non-guaranteed contract decision
- contract expires into free agency
- rookie-scale option declined before split
- waiver-terminated / 10-Day free agents
- manual review

POST-SPLIT SAFETY
-----------------
Real-world June/July 2026 option outcomes may be visible on current contract
pages. They are recorded only for audit. They are NEVER imported as simulator
state.

IMPORTANT QO FOLLOW-UP
----------------------
The prior QO Amount Readiness V1 also used the 2023 CBA Exhibit B QO percentage
table for four 2022 first-rounders. That is not the final correct scale. The CBA
requires the Rookie Salary Scale applicable to the player's own Rookie Scale
Contract. Those four contracts began under the 2017 CBA and will be rebuilt
after this universe correction.

READ ONLY
---------
- no option exercised/declined
- no QO issued
- no RFA status applied
- no rights overlay write
- no checkpoint write
- no roster/contract mutation
"""
        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")
            for member, body in sorted(fetched_snapshots.items()):
                archive.writestr(
                    f"{export_id}/{member}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after lifecycle export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after lifecycle export.")

    print("", flush=True)
    print("=" * 124, flush=True)
    print("2026 CONTRACT OPTION LIFECYCLE READINESS V1.0.1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Corrected FA market candidates: {len(market_rows)}", flush=True)
    print(f"Pending option/contract decisions: {len(pending_rows)}", flush=True)
    print(f"Already under contract 2026-27: {len(under_contract_rows)}", flush=True)
    print(f"Rookie-scale option exceptions: {len(rookie_exception_rows)}", flush=True)
    print(f"Prior RFA/QO rows invalidated: {len(invalidated_rfa_rows)}", flush=True)
    print(f"Manual review: {len(manual_rows)}", flush=True)
    print(f"Contract evidence: {coverage}/187 verified", flush=True)
    print(
        "Manual contract sources: "
        + (" | ".join(coverage_misses) if coverage_misses else "NONE"),
        flush=True,
    )
    print("Post-split option outcomes imported: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
