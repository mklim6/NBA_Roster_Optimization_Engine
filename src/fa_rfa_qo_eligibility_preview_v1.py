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
from typing import Any, Iterable, Mapping

VERSION = "fa-rfa-qo-eligibility-preview-v1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)

BASE = "https://www.salaryswish.com"
PLAYER_URL = BASE + "/players/{slug}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

RIGHTS_CLASSES = {"bird", "early_bird", "non_bird"}

SLUG_OVERRIDES = {
    "Cameron Payne": ["cam-payne"],
    "Bruce Brown": ["bruce-brown-jr"],
    "Xavier Tillman": ["xavier-tillman-sr"],
    "KJ Simpson": ["k-j-simpson"],
    "Darius Brown II": ["darius-brown"],
    "Trey Jemison III": ["trey-jemison"],
    "Gary Payton II": ["gary-payton-ii"],
    "Kevin McCullar Jr.": ["kevin-mccullar-jr"],
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


def finite_int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def positive_float(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0 or number != number:
        return None
    return number


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
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def slug_candidates(name: str) -> list[str]:
    result: list[str] = []

    for slug in SLUG_OVERRIDES.get(name, []):
        if slug not in result:
            result.append(slug)

    base = slugify(name)
    variants = [
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("dj-", "d-j-"),
    ]

    for slug in variants:
        slug = slug.strip("-")
        if slug and slug not in result:
            result.append(slug)

    return result


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
    title = norm_name(parser.title)
    h1 = norm_name(parser.h1)
    text = norm_name(parser.page_text[:100000])

    identity = bool(
        target
        and (
            target in title
            or target in h1
            or target in text
        )
    )

    if not identity:
        for candidate in (parser.title, parser.h1):
            if names_equivalent(player_name, candidate):
                identity = True
                break

    return identity, parser.title, parser.h1


def fetch_verified_contract_page(
    player_name: str,
    sleep_seconds: float,
) -> tuple[str, str, int, bytes, str, bool, str, str]:
    last = ("", "", 0, b"", "", False, "", "")

    for slug in slug_candidates(player_name):
        url = PLAYER_URL.format(slug=slug)
        status, body, error = fetch(url)
        identity, title, h1 = page_identity(body, player_name)

        last = (
            slug,
            url,
            status,
            body,
            error,
            identity,
            title,
            h1,
        )

        if status == 200 and body and identity:
            return last

        time.sleep(sleep_seconds)

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
        page_text = strip_html(part[:90000])

        date_match = re.search(
            r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            page_text,
        )
        signing_date: date | None = None
        if date_match:
            try:
                signing_date = datetime.strptime(
                    date_match.group(1),
                    "%B %d, %Y",
                ).date()
            except ValueError:
                signing_date = None

        team_match = re.search(
            r"Signing Team\s*:\s*([A-Z]{3})(?:\s|$)",
            page_text,
        )
        method_match = re.search(
            r"Signing Method\s*:\s*(.*?)\s+Signing Date\s*:",
            page_text,
        )

        parser = TableParser()
        parser.feed(part)

        seasons: dict[str, float | None] = {}

        for table in parser.tables:
            if not table:
                continue
            header = normalize_header(table[0])
            if "season" not in header:
                continue

            season_idx = header.index("season")
            base_idx = (
                header.index("base_salary")
                if "base_salary" in header
                else None
            )

            for row in table[1:]:
                if season_idx >= len(row):
                    continue
                season_text = clean(row[season_idx])
                if not re.match(r"^20\d{2}-\d{2}", season_text):
                    continue

                salary = None
                if base_idx is not None and base_idx < len(row):
                    salary = positive_float(row[base_idx])

                seasons[season_text[:7]] = salary

        blocks.append({
            "contract_type": contract_type,
            "signing_date": signing_date,
            "signing_team": clean(team_match.group(1)) if team_match else "",
            "signing_method": clean(method_match.group(1)) if method_match else "",
            "seasons": seasons,
        })

    return blocks


def latest_applicable_2025_26_block(
    blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        block for block in blocks
        if block.get("signing_date") is not None
        and block["signing_date"] <= SIMULATION_SPLIT_DATE
        and "2025-26" in block.get("seasons", {})
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda block: block["signing_date"],
    )


def rookie_scale_history(
    blocks: list[dict[str, Any]],
) -> tuple[bool, bool, bool]:
    rookie_blocks = [
        block for block in blocks
        if "rookie scale" in clean(block.get("contract_type")).lower()
    ]

    had_rookie_scale = bool(rookie_blocks)
    has_2025_26_rookie_scale = any(
        "2025-26" in block.get("seasons", {})
        for block in rookie_blocks
    )
    has_earlier_rookie_scale_without_2025_26 = any(
        block.get("seasons")
        and "2025-26" not in block.get("seasons", {})
        for block in rookie_blocks
    )

    return (
        had_rookie_scale,
        has_2025_26_rookie_scale,
        has_earlier_rookie_scale_without_2025_26,
    )


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [
        path
        for path in root.rglob(pattern)
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError(f"Could not locate required input: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> list[dict[str, str]]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing {suffix}")

    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> dict[str, Any]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing {suffix}")

    return json.loads(
        archive.read(member).decode("utf-8-sig")
    )


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

    registry_zip = find_latest(
        root,
        "fa_rights_registry_v2_preview_2026-27_*.zip",
    )
    continuity_zip = find_latest(
        root,
        "fa_rights_continuity_v2_preview_2026-27_*.zip",
    )

    with zipfile.ZipFile(registry_zip) as archive:
        registry_summary = read_json_member(
            archive,
            "final_rights_summary.json",
        )
        registry_rows = read_csv_member(
            archive,
            "final_rights_registry_preview.csv",
        )

    with zipfile.ZipFile(continuity_zip) as archive:
        continuity_rows = read_csv_member(
            archive,
            "continuity_preview_resolved.csv",
        )

    continuity_by_id = {
        pid(row.get("player_id")): row
        for row in continuity_rows
    }

    checkpoint = checkpoint_path(root)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )

    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 120, flush=True)
    print("2026 RFA + QUALIFYING OFFER ELIGIBILITY PREVIEW V1", flush=True)
    print("=" * 120, flush=True)
    print(f"Final rights registry: {registry_zip}", flush=True)
    print(f"Continuity evidence:    {continuity_zip}", flush=True)
    print(f"Simulation split:       {SIMULATION_SPLIT_DATE.isoformat()}", flush=True)
    print("", flush=True)
    print(
        "READ-ONLY: this preview does not issue, withdraw, accept, or match any Qualifying Offer.",
        flush=True,
    )
    print("", flush=True)

    # Fetch full contract pages only for players who could plausibly fall
    # into Article XI Section 4(a)/(b). This includes verified Veteran FAs
    # with <= 4 YOS plus any Continuity V2 player whose final contract is
    # a Two-Way Contract.
    fetch_targets: list[dict[str, str]] = []

    for row in registry_rows:
        if clean(row.get("final_status")) != "verified_veteran_fa":
            continue

        player_id = pid(row.get("player_id"))
        yos = finite_int(row.get("years_of_service"))
        continuity = continuity_by_id.get(player_id, {})
        final_contract_type = clean(
            continuity.get("final_contract_type")
        )

        if (
            (yos is not None and yos <= 4)
            or "two-way" in final_contract_type.lower()
        ):
            fetch_targets.append({
                "player_id": player_id,
                "player_name": clean(row.get("player_name")),
            })

    fetch_targets.sort(
        key=lambda row: row["player_name"].lower()
    )

    print(
        f"Potential RFA contract pages to verify: {len(fetch_targets)}",
        flush=True,
    )

    sleep_seconds = 0.35
    contract_snapshots: dict[str, bytes] = {}
    source_manifest: list[dict[str, Any]] = []
    contract_blocks_by_id: dict[str, list[dict[str, Any]]] = {}

    for index, target in enumerate(fetch_targets, start=1):
        player_id = target["player_id"]
        player_name = target["player_name"]

        print(
            f"[{index:03d}/{len(fetch_targets):03d}] {player_name}",
            flush=True,
        )

        (
            slug,
            url,
            status,
            body,
            error,
            identity,
            title,
            h1,
        ) = fetch_verified_contract_page(
            player_name,
            sleep_seconds,
        )

        body_sha = sha256_bytes(body) if body else ""
        snapshot_member = ""

        if status == 200 and body and identity:
            snapshot_member = (
                f"snapshots/{player_id}_{slug}_contract.html"
            )
            contract_snapshots[snapshot_member] = body
            blocks = parse_contract_blocks(
                body.decode("utf-8", errors="ignore")
            )
            contract_blocks_by_id[player_id] = blocks
            fetch_state = "verified_contract_page"
        else:
            blocks = []
            fetch_state = "manual_contract_research"

        source_manifest.append({
            "player_id": player_id,
            "player_name": player_name,
            "slug_used": slug,
            "source_url": url,
            "http_status": status,
            "page_identity_verified": identity,
            "page_title": title,
            "page_h1": h1,
            "source_sha256": body_sha,
            "source_bytes": len(body),
            "snapshot_member": snapshot_member,
            "fetch_state": fetch_state,
            "fetch_error": error,
            "contract_block_count": len(blocks),
        })

        time.sleep(sleep_seconds)

    print("", flush=True)
    print("Resolving structural RFA/QO eligibility...", flush=True)

    result_rows: list[dict[str, Any]] = []

    for row in registry_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        final_status = clean(row.get("final_status"))
        rights_class = clean(row.get("rights_classification"))
        yos = finite_int(row.get("years_of_service"))
        continuity = continuity_by_id.get(player_id, {})
        continuity_contract_type = clean(
            continuity.get("final_contract_type")
        )

        blocks = contract_blocks_by_id.get(player_id, [])
        latest = latest_applicable_2025_26_block(blocks)
        latest_contract_type = (
            clean(latest.get("contract_type"))
            if latest
            else continuity_contract_type
        )
        latest_signing_date = (
            latest["signing_date"].isoformat()
            if latest and latest.get("signing_date")
            else ""
        )
        latest_signing_team = (
            clean(latest.get("signing_team"))
            if latest
            else ""
        )

        (
            had_rookie_scale,
            rookie_scale_covers_2025_26,
            earlier_rookie_scale_without_2025_26,
        ) = rookie_scale_history(blocks)

        completes_two_way = (
            "two-way" in latest_contract_type.lower()
        )
        full_rookie_scale_finish = (
            "rookie scale" in latest_contract_type.lower()
            and rookie_scale_covers_2025_26
            and yos == 4
        )

        if final_status != "verified_veteran_fa":
            eligibility_status = "not_eligible"
            eligibility_path = "not_veteran_free_agent"
            qo_decision_state = "not_applicable"
            qo_amount_path = "not_applicable"
            reason = (
                "RFA/QO preview applies only to verified Veteran Free Agents."
            )

        elif rights_class not in RIGHTS_CLASSES:
            eligibility_status = "manual_review"
            eligibility_path = "rights_not_resolved"
            qo_decision_state = "not_issued_preview"
            qo_amount_path = "manual_review"
            reason = (
                "Veteran Free Agent rights classification is not resolved."
            )

        elif full_rookie_scale_finish:
            eligibility_status = "eligible_if_qo_issued"
            eligibility_path = "rookie_scale_second_option_year_complete"
            qo_decision_state = "not_issued_preview"
            qo_amount_path = (
                "rookie_scale_qo_requires_draft_slot_and_starter_criteria"
            )
            reason = (
                "Completed the second Option Year / fourth season of a "
                "Rookie Scale Contract. Prior Team may create RFA status "
                "by timely Qualifying Offer."
            )

        elif (
            had_rookie_scale
            and earlier_rookie_scale_without_2025_26
            and not full_rookie_scale_finish
            and yos is not None
            and yos <= 4
        ):
            eligibility_status = "manual_review"
            eligibility_path = "first_round_option_exception_risk"
            qo_decision_state = "not_issued_preview"
            qo_amount_path = "manual_review"
            reason = (
                "Player has prior Rookie Scale evidence but did not finish "
                "2025-26 on that Rookie Scale Contract. Article XI 4(b) "
                "excludes a First Round Pick whose first or second Option "
                "Year was not exercised; exact option history must be proven."
            )

        elif completes_two_way:
            eligibility_status = "eligible_if_qo_issued"
            eligibility_path = "completing_two_way_contract"
            qo_decision_state = "not_issued_preview"
            qo_amount_path = (
                "two_way_qo_subtype_requires_term_continuity_and_two_way_eligibility"
            )
            reason = (
                "Verified Veteran Free Agent is completing a Two-Way "
                "Contract and is structurally QO-eligible unless the "
                "First Round option exception applies."
            )

        elif yos is not None and yos <= 3:
            eligibility_status = "eligible_if_qo_issued"
            eligibility_path = "veteran_free_agent_three_or_fewer_yos"
            qo_decision_state = "not_issued_preview"

            if yos in {2, 3}:
                qo_amount_path = (
                    "standard_qo_requires_prior_salary_contract_date_minimum_plus_200k_and_starter_criteria"
                )
            else:
                qo_amount_path = (
                    "standard_qo_requires_prior_salary_contract_date_and_minimum_plus_200k"
                )

            reason = (
                "Verified Veteran Free Agent will have three or fewer "
                "Years of Service as of June 30 and is structurally "
                "QO-eligible."
            )

        else:
            eligibility_status = "not_eligible"
            eligibility_path = "veteran_free_agent_over_three_yos"
            qo_decision_state = "not_applicable"
            qo_amount_path = "not_applicable"
            reason = (
                "Veteran Free Agent has more than three Years of Service "
                "and is not completing a Two-Way Contract or finishing "
                "the second Option Year of a Rookie Scale Contract."
            )

        result_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": clean(row.get("prior_team")),
            "rights_classification": rights_class,
            "free_agent_category": clean(row.get("free_agent_category")),
            "years_of_service": yos,
            "eligibility_status": eligibility_status,
            "eligibility_path": eligibility_path,
            "qualifying_offer_decision_state": qo_decision_state,
            "qualifying_offer_amount_path": qo_amount_path,
            "latest_contract_type": latest_contract_type,
            "latest_contract_signing_date": latest_signing_date,
            "latest_contract_signing_team": latest_signing_team,
            "completes_two_way_contract": completes_two_way,
            "had_rookie_scale_contract": had_rookie_scale,
            "rookie_scale_covers_2025_26": rookie_scale_covers_2025_26,
            "full_rookie_scale_finish": full_rookie_scale_finish,
            "first_round_option_exception_risk": (
                eligibility_path == "first_round_option_exception_risk"
            ),
            "rfa_status_applied": False,
            "qualifying_offer_issued": False,
            "offer_sheet_created": False,
            "right_of_first_refusal_created": False,
            "reason": reason,
        })

    eligible_rows = [
        row for row in result_rows
        if row["eligibility_status"] == "eligible_if_qo_issued"
    ]
    manual_rows = [
        row for row in result_rows
        if row["eligibility_status"] == "manual_review"
    ]
    not_eligible_rows = [
        row for row in result_rows
        if row["eligibility_status"] == "not_eligible"
    ]

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []

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
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("", flush=True)
    print("Running strict preview checks...", flush=True)

    ids = [row["player_id"] for row in result_rows]

    check(
        "final_rights_registry_preview_passed",
        bool(registry_summary.get("passed")),
        "RFA work is downstream of the passed 187-player rights registry.",
    )
    check(
        "exact_187_player_universe_preserved",
        len(result_rows) == 187
        and len(ids) == len(set(ids)) == 187,
        "Exactly one RFA/QO disposition exists for every free agent.",
    )
    check(
        "eligible_rows_are_verified_veteran_free_agents",
        all(
            row["rights_classification"] in RIGHTS_CLASSES
            and row["free_agent_category"] == "veteran_free_agent"
            for row in eligible_rows
        ),
        "No non-VFA player can enter the QO-eligible set.",
    )
    check(
        "no_qo_or_rfa_state_is_applied",
        all(
            not row["rfa_status_applied"]
            and not row["qualifying_offer_issued"]
            and not row["offer_sheet_created"]
            and not row["right_of_first_refusal_created"]
            for row in result_rows
        ),
        "This package is eligibility preview only.",
    )
    check(
        "rookie_scale_auto_eligibility_requires_full_2025_26_finish",
        all(
            row["full_rookie_scale_finish"]
            for row in eligible_rows
            if row["eligibility_path"]
            == "rookie_scale_second_option_year_complete"
        ),
        "Special rookie-scale RFA path requires a proven four-season finish.",
    )
    check(
        "first_round_option_exception_fails_closed",
        all(
            row["eligibility_status"] == "manual_review"
            for row in result_rows
            if row["first_round_option_exception_risk"]
        ),
        "Potential non-exercised rookie-scale option cases are never auto-RFA.",
    )
    check(
        "over_three_yos_requires_two_way_or_rookie_scale_path",
        all(
            (
                row["years_of_service"] is None
                or row["years_of_service"] <= 3
                or row["completes_two_way_contract"]
                or row["full_rookie_scale_finish"]
            )
            for row in eligible_rows
        ),
        "Article XI 4(b) service-time gate is enforced.",
    )
    check(
        "accepted_contract_snapshots_are_identity_verified",
        all(
            row["fetch_state"] != "verified_contract_page"
            or row["page_identity_verified"]
            for row in source_manifest
        ),
        "No generic SalarySwish fallback page can enter evidence.",
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

    coverage_verified = sum(
        row["fetch_state"] == "verified_contract_page"
        for row in source_manifest
    )
    check(
        "contract_page_coverage",
        coverage_verified == len(source_manifest),
        f"verified={coverage_verified}/{len(source_manifest)}",
        severity="coverage",
    )

    failed_strict = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    if failed_strict:
        raise RuntimeError(
            "RFA/QO Eligibility Preview V1 failed strict checks: "
            + ", ".join(failed_strict)
        )

    counts = Counter(
        row["eligibility_status"]
        for row in result_rows
    )
    path_counts = Counter(
        row["eligibility_path"]
        for row in result_rows
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_rfa_qo_eligibility_preview_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="farfaqo_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "rfa_qo_eligibility_all.csv",
            result_rows,
        )
        write_csv(
            export / "rfa_qo_eligible_if_qo_issued.csv",
            eligible_rows,
        )
        write_csv(
            export / "rfa_qo_manual_review.csv",
            manual_rows,
        )
        write_csv(
            export / "rfa_qo_not_eligible.csv",
            not_eligible_rows,
        )
        write_csv(
            export / "rfa_qo_contract_source_manifest.csv",
            source_manifest,
        )
        write_csv(
            export / "rfa_qo_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "total_free_agents": len(result_rows),
            "eligibility_status_counts": dict(
                sorted(counts.items())
            ),
            "eligibility_path_counts": dict(
                sorted(path_counts.items())
            ),
            "eligible_if_qo_issued_count": len(eligible_rows),
            "manual_review_count": len(manual_rows),
            "not_eligible_count": len(not_eligible_rows),
            "contract_fetch_target_count": len(fetch_targets),
            "verified_contract_page_count": coverage_verified,
            "contract_page_manual_count": (
                len(source_manifest) - coverage_verified
            ),
            "qo_issued_count": 0,
            "rfa_status_applied_count": 0,
            "offer_sheet_created_count": 0,
            "right_of_first_refusal_created_count": 0,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "state_mutation_performed": False,
            "passed": not failed_strict,
            "failed_strict_checks": failed_strict,
            "next_slice": (
                "Resolve exact Qualifying Offer amount inputs for the eligible "
                "set, then implement guarded team QO decisions / RFA lifecycle. "
                "Cap-hold + renouncement modeling follows because RFA status "
                "changes both the special rookie-scale cap hold and whether a "
                "player may be renounced."
            ),
        }

        (
            export / "rfa_qo_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = f"""2026 RFA + QUALIFYING OFFER ELIGIBILITY PREVIEW V1
==================================================

Version: {VERSION}

WHY THIS COMES BEFORE CAP HOLDS
------------------------------
The 2023 NBA-NBPA CBA gives players finishing the second Option Year of a
Rookie Scale Contract a special Qualifying Offer pathway. If the team issues
the QO, the player becomes a Restricted Free Agent on July 1.

The CBA also allows a Prior Team to create RFA status by timely Qualifying
Offer for a Veteran Free Agent who:
- will have three or fewer Years of Service as of June 30, OR
- is completing a Two-Way Contract,
subject to the first-round Option-Year exception.

This dependency must be solved before cap holds because:
- a qualifying rookie-scale RFA has a special 250% / 300% Bird Free Agent Amount
  depending on the Estimated Average Player Salary comparison; and
- a Team cannot renounce a Restricted Free Agent.

WHAT THIS PREVIEW DOES
----------------------
For all 187 free agents it determines only structural QO eligibility:
- rookie_scale_second_option_year_complete
- veteran_free_agent_three_or_fewer_yos
- completing_two_way_contract
- first_round_option_exception_risk
- not_eligible
- manual_review

It does NOT issue a QO and does NOT create RFA status.

QO AMOUNT PATHS
---------------
This preview records which amount formula needs to be solved next.

Rookie Scale:
- needs draft slot / rookie scale QO percentage
- needs Official NBA Starter Criteria

Two-Way:
- needs exact Two-Way term/continuity subtype
- may require Standard NBA minimum salary + scaled protection amount
- otherwise Two-Way salary + Maximum Two-Way Protection Amount

Other <=3 YOS Veteran Free Agents:
- prior Salary
- prior Contract signing date to choose 135% vs legacy 125%
- current applicable Minimum Annual Salary + $200,000
- for second-round / undrafted players with 2-3 YOS, Starter Criteria may
  trigger the twenty-first-pick floor

SAFETY
------
- no Qualifying Offer issued
- no RFA status applied
- no Offer Sheet created
- no Right of First Refusal created
- no rights overlay write
- no checkpoint write
- no roster/signing/trade/contract mutation

Expected audit:
outputs/audits/{export_id}.zip
"""
        (
            export / "README.txt"
        ).write_text(
            readme,
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            zip_out,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

            for member, body in sorted(
                contract_snapshots.items()
            ):
                archive.writestr(
                    f"{export_id}/{member}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError(
            "Checkpoint changed after RFA/QO preview export."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed after RFA/QO preview export."
        )

    print("", flush=True)
    print("=" * 120, flush=True)
    print("2026 RFA + QUALIFYING OFFER ELIGIBILITY PREVIEW V1 PASSED", flush=True)
    print("=" * 120, flush=True)
    print(
        f"Eligible if QO issued: {len(eligible_rows)}",
        flush=True,
    )
    print(
        f"Manual review:         {len(manual_rows)}",
        flush=True,
    )
    print(
        f"Not eligible:          {len(not_eligible_rows)}",
        flush=True,
    )
    print(
        f"Contract pages:        {coverage_verified}/{len(source_manifest)} verified",
        flush=True,
    )
    print("Qualifying Offers issued: 0", flush=True)
    print("RFA statuses applied:      0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
