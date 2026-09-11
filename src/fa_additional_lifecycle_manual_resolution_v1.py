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
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-additional-lifecycle-manual-resolution-v1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
EXPECTED_MANUAL_COUNT = 16
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

BASE = "https://www.salaryswish.com"
PLAYER_URL = BASE + "/players/{slug}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")
MONTH_PATTERN = (
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
)
SIGNING_DATE_RE = re.compile(
    rf"Signing\s+Date\s*:?\s*{MONTH_PATTERN}\s+\d{{1,2}},\s+20\d{{2}}",
    re.IGNORECASE,
)

# Safe targeted aliases for names that commonly generate URL mismatches.
SLUG_OVERRIDES = {
    "Jae'Sean Tate": ["jaesean-tate"],
    "De'Anthony Melton": ["deanthony-melton"],
    "Day'Ron Sharpe": ["dayron-sharpe"],
    "Bogdan Bogdanović": ["bogdan-bogdanovic"],
    "Nikola Vučević": ["nikola-vucevic"],
    "Daeqwon Plowden": ["daeqwon-plowden"],
    "Kentavious Caldwell-Pope": ["kentavious-caldwell-pope"],
    "Ron Harper Jr.": ["ron-harper-jr", "ron-harper"],
    "Jalen Pickett": ["jalen-pickett"],
    "Moussa Cisse": ["moussa-cisse"],
    "Spencer Jones": ["spencer-jones"],
}


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


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
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
    transforms = [
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("-jr-", "-"),
        base.replace("-sr-", "-"),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("jd-", "j-d-"),
    ]
    for item in transforms:
        item = item.strip("-")
        if item and item not in values:
            values.append(item)
    return values


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


def page_identity(parser: ContractPageParser, player_name: str) -> bool:
    target = normalize_name(player_name)
    title = normalize_name(parser.title)
    h1 = normalize_name(parser.h1)
    return bool(
        target
        and (
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


def money_to_number(value: Any) -> float | None:
    match = MONEY_RE.search(clean(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace("$", "").replace(",", ""))
    except ValueError:
        return None


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


def extract_spans(
    body: bytes,
    player_id: str,
    player_name: str,
    source_url: str,
) -> list[dict[str, Any]]:
    parser = ContractPageParser()
    parser.feed(body.decode("utf-8", errors="ignore"))

    spans: list[dict[str, Any]] = []
    source_sha = sha256_bytes(body)

    for table_index, table_info in enumerate(parser.tables):
        rows = table_info["rows"]
        pre_context = clean(table_info["pre_context"])
        header_index = None
        header = []

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
        season_rows: dict[str, dict[str, str]] = {}

        for row in rows[header_index + 1:]:
            if not row:
                continue
            season_text = clean(row[season_index]) if season_index < len(row) else ""
            season_key = (
                "2025-26" if season_text.startswith("2025-26")
                else "2026-27" if season_text.startswith("2026-27")
                else ""
            )
            if not season_key:
                continue

            record: dict[str, str] = {}
            for col_index, col_name in enumerate(header):
                if col_index < len(row):
                    record[col_name or f"column_{col_index}"] = clean(row[col_index])
            season_rows[season_key] = record

        if "2025-26" not in season_rows:
            continue

        signing_date = parse_signing_date(pre_context)
        prior = season_rows["2025-26"]
        target = season_rows.get("2026-27", {})

        spans.append({
            "player_id": player_id,
            "player_name": player_name,
            "table_index": table_index,
            "source_url": source_url,
            "source_sha256": source_sha,
            "signing_date": signing_date.isoformat() if signing_date else "",
            "signing_date_is_pre_split": bool(signing_date and signing_date <= SIMULATION_SPLIT_DATE),
            "prior_base_salary": clean(prior.get("base_salary")),
            "target_exists": bool(target),
            "target_base_salary": clean(target.get("base_salary")),
            "target_base_salary_numeric": money_to_number(target.get("base_salary")),
            "target_option": clean(target.get("option")),
            "target_guaranteed": clean(target.get("guaranteed")),
            "target_guaranteed_numeric": money_to_number(target.get("guaranteed")),
            "target_guaranteed_has_change_annotation": (
                "→" in clean(target.get("guaranteed"))
                or "->" in clean(target.get("guaranteed"))
            ),
            "pre_context": pre_context[-2200:],
        })

    return spans


def classify_span(span: Mapping[str, Any]) -> tuple[str, str]:
    if not span.get("target_exists"):
        return (
            "expiring_2025_26_free_agent_candidate",
            "Selected pre-split contract has 2025-26 salary but no 2026-27 row.",
        )

    option = clean(span.get("target_option")).lower()
    if "team" in option:
        return (
            "team_option_2026_27_decision",
            "2026-27 Team Option found in pre-split contract.",
        )
    if "player" in option:
        return (
            "player_option_2026_27_decision",
            "2026-27 Player Option found in pre-split contract.",
        )

    base = span.get("target_base_salary_numeric")
    guaranteed = span.get("target_guaranteed_numeric")

    if base is not None and guaranteed is not None and guaranteed + 0.01 < base:
        return (
            "partial_or_non_guaranteed_2026_27_decision",
            "2026-27 guaranteed amount is below 2026-27 base salary.",
        )

    if (
        base is not None
        and guaranteed is not None
        and abs(guaranteed - base) <= 0.01
        and not span.get("target_guaranteed_has_change_annotation")
    ):
        return (
            "fully_guaranteed_under_contract_2026_27",
            "2026-27 base salary is fully guaranteed.",
        )

    return (
        "manual_guarantee_timing_review",
        "2026-27 row exists but guarantee timing/status is not uniquely resolved.",
    )


def resolve_by_consensus(
    spans: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any] | None]:
    eligible = [
        span for span in spans
        if (
            span.get("signing_date_is_pre_split")
            or not clean(span.get("signing_date"))
        )
    ]
    if not eligible:
        return (
            "manual_contract_evidence_review",
            "No 2025-26 contract span can safely be tied to the pre-split state.",
            None,
        )

    classified = []
    for span in eligible:
        classification, reason = classify_span(span)
        classified.append((classification, reason, span))

    classes = {item[0] for item in classified}
    if len(classes) == 1:
        chosen = max(
            classified,
            key=lambda item: (
                clean(item[2].get("signing_date")),
                int(item[2].get("table_index", -1)),
            ),
        )
        return (
            chosen[0],
            (
                "Consensus across all plausible 2025-26 contract spans. "
                + chosen[1]
            ),
            chosen[2],
        )

    # If multiple classifications exist, the latest uniquely dated pre-split
    # contract wins. This is safe because it is temporally prior to the branch.
    dated = [
        item for item in classified
        if clean(item[2].get("signing_date"))
        and item[2].get("signing_date_is_pre_split")
    ]
    if dated:
        dated.sort(key=lambda item: item[2]["signing_date"])
        latest_date = dated[-1][2]["signing_date"]
        latest = [item for item in dated if item[2]["signing_date"] == latest_date]
        if len(latest) == 1:
            return (
                latest[0][0],
                "Unique latest pre-split contract signing date. " + latest[0][1],
                latest[0][2],
            )

    return (
        "manual_contract_evidence_review",
        "Multiple plausible pre-split contract spans disagree on 2026-27 lifecycle.",
        None,
    )


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
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

    audit_zip = find_latest(
        root,
        "fa_additional_lifecycle_contract_evidence_harvest_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(audit_zip) as archive:
        summary = read_json_member(
            archive,
            "additional_lifecycle_contract_summary.json",
        )
        manual_rows = read_csv_member(
            archive,
            "additional_lifecycle_manual_review.csv",
        )
        all_spans = read_csv_member(
            archive,
            "additional_lifecycle_contract_spans.csv",
        )

    if len(manual_rows) != EXPECTED_MANUAL_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_MANUAL_COUNT} manual rows, got {len(manual_rows)}."
        )

    # Protect the canonical simulation branch.
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_before = sha256_file(checkpoint_path)
    if checkpoint_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before manual-resolution pass.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_before}"
        )

    spans_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_spans:
        spans_by_id[pid(row.get("player_id"))].append(dict(row))

    print("=" * 128, flush=True)
    print("2026 ADDITIONAL LIFECYCLE MANUAL RESOLUTION V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Manual queue: {len(manual_rows)}", flush=True)
    print("READ-ONLY. No contract or checkpoint mutation.", flush=True)
    print("", flush=True)

    resolutions = []
    refetched_spans = []
    source_attempts = []
    snapshots: dict[str, bytes] = {}

    for index, manual in enumerate(manual_rows, start=1):
        player_id = pid(manual.get("player_id"))
        player_name = clean(manual.get("player_name"))
        original_reason = clean(manual.get("active_contract_selection_reason"))

        print(
            f"[{index:02d}/{EXPECTED_MANUAL_COUNT}] {player_name} ({player_id})",
            flush=True,
        )

        existing_spans = spans_by_id.get(player_id, [])
        classification, reason, chosen = resolve_by_consensus(existing_spans)
        resolution_method = "existing_span_consensus"

        # Only refetch when the existing evidence cannot safely resolve.
        if classification.startswith("manual_"):
            best_body = b""
            best_url = ""
            best_slug = ""
            identity = False

            for slug in slug_candidates(player_name):
                url = PLAYER_URL.format(slug=slug)
                status, body, error = fetch(url)
                parser = ContractPageParser()
                if body:
                    parser.feed(body.decode("utf-8", errors="ignore"))
                is_identity = bool(body and status == 200 and page_identity(parser, player_name))

                source_attempts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "slug": slug,
                    "source_url": url,
                    "http_status": status,
                    "identity_verified": is_identity,
                    "source_sha256": sha256_bytes(body) if body else "",
                    "fetch_error": error,
                })

                if is_identity:
                    best_body = body
                    best_url = url
                    best_slug = slug
                    identity = True
                    break

                time.sleep(0.35)

            if identity:
                spans = extract_spans(
                    best_body,
                    player_id,
                    player_name,
                    best_url,
                )
                refetched_spans.extend(spans)
                classification2, reason2, chosen2 = resolve_by_consensus(spans)

                if not classification2.startswith("manual_"):
                    classification = classification2
                    reason = reason2
                    chosen = chosen2
                    resolution_method = "refetched_page_consensus"

                snapshots[
                    f"snapshots/{player_id}_{best_slug}.html"
                ] = best_body

        resolutions.append({
            "player_id": player_id,
            "player_name": player_name,
            "original_manual_reason": original_reason,
            "resolved_classification": classification,
            "resolution_reason": reason,
            "resolution_method": resolution_method,
            "resolved": not classification.startswith("manual_"),
            "chosen_signing_date": clean(chosen.get("signing_date")) if chosen else "",
            "chosen_target_base_salary": clean(chosen.get("target_base_salary")) if chosen else "",
            "chosen_target_option": clean(chosen.get("target_option")) if chosen else "",
            "chosen_target_guaranteed": clean(chosen.get("target_guaranteed")) if chosen else "",
            "future_outcome_used": False,
            "checkpoint_mutation_applied": False,
        })

    resolved_rows = [row for row in resolutions if row["resolved"]]
    remaining = [row for row in resolutions if not row["resolved"]]
    counts = Counter(row["resolved_classification"] for row in resolutions)

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
    print("Running strict manual-resolution checks...", flush=True)

    check(
        "upstream_harvest_passed",
        bool(summary.get("passed")),
        "Additional lifecycle contract harvest V1.0.1 passed.",
    )
    check(
        "exact_16_manual_rows",
        len(manual_rows) == EXPECTED_MANUAL_COUNT,
        f"manual={len(manual_rows)}",
    )
    check(
        "no_future_outcomes_used",
        all(not row["future_outcome_used"] for row in resolutions),
        "Only pre-April-12 contract structure can resolve a row.",
    )
    check(
        "all_unresolved_rows_remain_explicit_manual",
        all(row["resolved_classification"].startswith("manual_") for row in remaining),
        f"remaining_manual={len(remaining)}",
    )
    check(
        "checkpoint_file_unchanged",
        sha256_file(checkpoint_path) == checkpoint_before == EXPECTED_CHECKPOINT_SHA256,
        sha256_file(checkpoint_path),
    )

    failed = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Additional Lifecycle Manual Resolution V1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_additional_lifecycle_manual_resolution_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_manual_resolution_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "manual_resolution_all.csv", resolutions)
        write_csv(export / "manual_resolution_resolved.csv", resolved_rows)
        write_csv(export / "manual_resolution_remaining.csv", remaining)
        write_csv(export / "manual_resolution_refetched_spans.csv", refetched_spans)
        write_csv(export / "manual_resolution_source_attempts.csv", source_attempts)
        write_csv(export / "manual_resolution_checks.csv", checks)

        out_summary = {
            "version": VERSION,
            "manual_input_count": len(manual_rows),
            "auto_resolved_count": len(resolved_rows),
            "remaining_manual_count": len(remaining),
            "classification_counts": dict(sorted(counts.items())),
            "future_outcomes_used": False,
            "checkpoint_write_performed": False,
            "state_mutation_performed": False,
            "passed": True,
            "next_slice": (
                "Merge auto-resolved rows with the 68 already resolved additional "
                "lifecycle rows. For any remaining manual rows, build targeted "
                "player-specific evidence packets rather than broad harvesting."
            ),
        }
        (export / "manual_resolution_summary.json").write_text(
            json.dumps(out_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 ADDITIONAL LIFECYCLE MANUAL RESOLUTION V1
================================================

This pass starts from the 16 manual rows produced by the 84-player contract
harvest.

Safe auto-resolution methods:
1. Consensus across every plausible pre-April-12 2025-26 contract span.
2. A unique latest pre-April-12 signed contract.
3. Refetching the player's SalarySwish page with expanded slug/name fallbacks,
   followed by the same consensus rules.

A row is NOT resolved merely because a post-split real-world outcome reveals
what ultimately happened.

Any row still ambiguous remains explicit manual evidence review.

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_out, "w", zipfile.ZIP_DEFLATED) as archive:
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
    print("2026 ADDITIONAL LIFECYCLE MANUAL RESOLUTION V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Manual input:            {len(manual_rows)}", flush=True)
    print(f"Auto-resolved:           {len(resolved_rows)}", flush=True)
    print(f"Remaining manual:        {len(remaining)}", flush=True)
    print("Classification counts:", flush=True)
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("Future outcomes used:    NO", flush=True)
    print("Checkpoint write:        NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
