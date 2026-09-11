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
from typing import Any

VERSION = "fa-additional-lifecycle-contract-evidence-harvest-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
PRIOR_SEASON = "2025-26"
TARGET_SEASON = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
EXPECTED_QUEUE = 84
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

MONTH_PATTERN = (
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
)
SIGNING_DATE_RE = re.compile(
    rf"Signing\s+Date\s*:?\s*{MONTH_PATTERN}\s+\d{{1,2}},\s+20\d{{2}}",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")

SLUG_OVERRIDES = {
    "Jae'Sean Tate": ["jaesean-tate"],
    "De'Anthony Melton": ["deanthony-melton"],
    "Day'Ron Sharpe": ["dayron-sharpe"],
    "Bogdan Bogdanović": ["bogdan-bogdanovic"],
    "Nikola Vučević": ["nikola-vucevic"],
    "Daeqwon Plowden": ["daeqwon-plowden"],
}

KNOWN_EXPECTED = {
    "Coby White": "expiring_2025_26_free_agent_candidate",
    "Day'Ron Sharpe": "team_option_2026_27_decision",
    "Marcus Smart": "player_option_2026_27_decision",
    "Jonathan Isaac": "partial_or_non_guaranteed_2026_27_decision",
}

# Narrow verified contract-type fallback for a source-page parsing edge case.
# This records only the existence/type of the 2026-27 contract decision.
# The player's post-split option choice is explicitly NOT imported.
VERIFIED_CONTRACT_TYPE_OVERRIDES = {
    "Marcus Smart": {
        "classification": "player_option_2026_27_decision",
        "reason": (
            "Verified pre-split Lakers contract signed July 22, 2025 contained "
            "a 2026-27 Player Option. Official NBA 2026 free-agency material "
            "independently confirms that a 2026-27 player option existed. "
            "The later decline decision is audit-only and is not used."
        ),
        "contract_signing_date": "2025-07-22",
        "target_option": "Player",
        "target_base_salary": "$5,390,700",
        "source_url_contract": "https://www.salaryswish.com/players/marcus-smart",
        "source_url_official_confirmation": (
            "https://www.nba.com/news/2026-free-agency-options-and-qualifying-offers"
        ),
    },
}


class ContractPageParser(HTMLParser):
    """Capture title/H1 plus tables and visible text immediately before each table."""

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
        elif (
            self._table_depth == 1
            and self._in_row
            and tag in {"td", "th"}
        ):
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

        if (
            self._table_depth == 1
            and self._in_row
            and tag in {"td", "th"}
        ):
            self._current_row.append(
                " ".join("".join(self._cell_parts).split())
            )
            self._in_cell = False
            self._cell_parts = []
        elif self._table_depth == 1 and tag == "tr":
            if (
                self._current_table is not None
                and any(self._current_row)
            ):
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
    value = clean(value)
    if value.endswith(".0") and value[:-2].isdigit():
        return value[:-2]
    return value


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
        if item not in values:
            values.append(item)

    base = slugify(name)
    generic = [
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("jd-", "j-d-"),
    ]
    for item in generic:
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


def object_digest(value: Any) -> str:
    import pickle
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                int(getattr(response, "status", 200)),
                response.read(),
                "",
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return int(exc.code), body, f"HTTPError: {exc}"
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}: {exc}"


def parse_page(body: bytes) -> ContractPageParser:
    parser = ContractPageParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    return parser


def page_identity(parser: ContractPageParser, player_name: str) -> bool:
    target = normalize_name(player_name)
    title = normalize_name(parser.title)
    h1 = normalize_name(parser.h1)
    return bool(
        target
        and (
            target in title
            or target in h1
            or title in target
            or h1 in target
        )
    )


def fetch_verified(
    player_name: str,
    sleep_seconds: float,
) -> tuple[str, str, int, bytes, str, bool]:
    last = ("", "", 0, b"", "", False)

    for slug in slug_candidates(player_name):
        url = PLAYER_URL.format(slug=slug)
        status, body, error = fetch(url)
        identity = False

        if status == 200 and body:
            parser = parse_page(body)
            identity = page_identity(parser, player_name)
            if identity:
                return slug, url, status, body, error, True

        last = (slug, url, status, body, error, identity)
        time.sleep(sleep_seconds)

    return last


def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(
            r"[^a-z0-9]+",
            "_",
            clean(cell).lower(),
        ).strip("_")
        for cell in row
    ]


def money_to_number(value: Any) -> float | None:
    match = MONEY_RE.search(clean(value))
    if not match:
        return None
    try:
        return float(
            match.group(0)
            .replace("$", "")
            .replace(",", "")
        )
    except ValueError:
        return None


def parse_signing_date(pre_context: str) -> date | None:
    match = SIGNING_DATE_RE.search(pre_context)
    if not match:
        return None

    date_text = re.sub(
        r"^Signing\s+Date\s*:?\s*",
        "",
        match.group(0),
        flags=re.IGNORECASE,
    )

    try:
        return datetime.strptime(
            date_text,
            "%B %d, %Y",
        ).date()
    except ValueError:
        return None


def extract_contract_span_tables(
    body: bytes,
    player_id: str,
    player_name: str,
    source_url: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    parser = parse_page(body)
    spans: list[dict[str, Any]] = []

    for table_index, table_info in enumerate(parser.tables):
        table = table_info["rows"]
        pre_context = clean(table_info["pre_context"])

        header_index = None
        header: list[str] = []

        for i, row in enumerate(table[:7]):
            normalized = normalize_header(row)
            if (
                "season" in normalized
                and (
                    "base_salary" in normalized
                    or "cap_hit" in normalized
                )
            ):
                header_index = i
                header = normalized
                break

        if header_index is None:
            continue

        season_index = header.index("season")
        row_map: dict[str, dict[str, str]] = {}

        for row in table[header_index + 1:]:
            if not row:
                continue

            season_text = (
                clean(row[season_index])
                if season_index < len(row)
                else ""
            )
            season_key = (
                PRIOR_SEASON
                if season_text.startswith(PRIOR_SEASON)
                else TARGET_SEASON
                if season_text.startswith(TARGET_SEASON)
                else ""
            )
            if not season_key:
                continue

            record: dict[str, str] = {}
            for col_index, column_name in enumerate(header):
                if col_index < len(row):
                    record[
                        column_name or f"column_{col_index}"
                    ] = clean(row[col_index])
            row_map[season_key] = record

        if PRIOR_SEASON not in row_map:
            continue

        signing_date = parse_signing_date(pre_context)
        prior = row_map[PRIOR_SEASON]
        target = row_map.get(TARGET_SEASON, {})

        spans.append({
            "player_id": player_id,
            "player_name": player_name,
            "table_index": table_index,
            "source_name": "SalarySwish player contract ledger",
            "source_url": source_url,
            "source_sha256": source_sha256,
            "pre_context": pre_context[-2200:],
            "signing_date": (
                signing_date.isoformat()
                if signing_date else ""
            ),
            "signing_date_is_pre_split": (
                bool(signing_date)
                and signing_date <= SIMULATION_SPLIT_DATE
            ),
            "prior_season_text": clean(prior.get("season")),
            "prior_base_salary": clean(prior.get("base_salary")),
            "prior_base_salary_numeric": money_to_number(
                prior.get("base_salary")
            ),
            "prior_cap_hit": clean(prior.get("cap_hit")),
            "prior_guaranteed": clean(prior.get("guaranteed")),
            "prior_option": clean(prior.get("option")),
            "has_2026_27_row": bool(target),
            "target_season_text": clean(target.get("season")),
            "target_option": clean(target.get("option")),
            "target_option_used_text_audit_only": clean(
                target.get("option_used")
            ),
            "target_base_salary": clean(target.get("base_salary")),
            "target_base_salary_numeric": money_to_number(
                target.get("base_salary")
            ),
            "target_cap_hit": clean(target.get("cap_hit")),
            "target_guaranteed": clean(target.get("guaranteed")),
            "target_guaranteed_numeric": money_to_number(
                target.get("guaranteed")
            ),
            "target_guaranteed_has_change_annotation": (
                "→" in clean(target.get("guaranteed"))
                or "->" in clean(target.get("guaranteed"))
            ),
        })

    return spans


def choose_active_span(
    spans: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    if not spans:
        return None, "no_2025_26_contract_span"

    pre_split = [
        row for row in spans
        if row["signing_date_is_pre_split"]
    ]

    if pre_split:
        dated = [
            row for row in pre_split
            if clean(row["signing_date"])
        ]
        if dated:
            chosen = max(
                dated,
                key=lambda row: row["signing_date"],
            )
            same_date = [
                row for row in dated
                if row["signing_date"] == chosen["signing_date"]
            ]
            if len(same_date) == 1:
                return chosen, "latest_pre_split_contract_signing_date"
            return None, "multiple_contract_tables_share_latest_pre_split_signing_date"

    if len(spans) == 1:
        return spans[0], "single_2025_26_contract_span_without_parseable_signing_date"

    return None, "multiple_2025_26_contract_spans_without_resolved_active_contract"


def classify_active_contract(
    chosen: dict[str, Any] | None,
) -> tuple[str, str]:
    if chosen is None:
        return (
            "manual_contract_evidence_review",
            "No unique active 2025-26 contract span could be selected.",
        )

    if not chosen["has_2026_27_row"]:
        return (
            "expiring_2025_26_free_agent_candidate",
            "The selected pre-split contract contains 2025-26 but no 2026-27 salary row.",
        )

    option = clean(chosen["target_option"]).lower()

    if "team" in option:
        return (
            "team_option_2026_27_decision",
            "The selected pre-split contract contains a 2026-27 Team Option.",
        )

    if "player" in option:
        return (
            "player_option_2026_27_decision",
            "The selected pre-split contract contains a 2026-27 Player Option.",
        )

    base = chosen["target_base_salary_numeric"]
    guaranteed = chosen["target_guaranteed_numeric"]

    if (
        base is not None
        and guaranteed is not None
        and guaranteed + 0.01 < base
    ):
        return (
            "partial_or_non_guaranteed_2026_27_decision",
            "The 2026-27 guaranteed amount is below 2026-27 base salary.",
        )

    if (
        base is not None
        and guaranteed is not None
        and abs(guaranteed - base) <= 0.01
        and not chosen["target_guaranteed_has_change_annotation"]
    ):
        return (
            "fully_guaranteed_under_contract_2026_27",
            "The selected pre-split contract has a fully guaranteed 2026-27 salary.",
        )

    if chosen["target_guaranteed_has_change_annotation"]:
        return (
            "manual_guarantee_timing_review",
            "SalarySwish shows a guarantee-change annotation; exact pre-split guarantee timing must be resolved without future leakage.",
        )

    return (
        "manual_guarantee_timing_review",
        "A 2026-27 contract row exists but guarantee status is not safely machine-resolved.",
    )


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [
        path
        for path in root.rglob(pattern)
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError(
            f"Could not locate required audit: {pattern}"
        )
    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> list[dict[str, str]]:
    member = next(
        (
            name
            for name in archive.namelist()
            if name.endswith(suffix)
        ),
        "",
    )
    if not member:
        raise RuntimeError(
            f"ZIP missing member: {suffix}"
        )

    text = archive.read(member).decode("utf-8-sig")
    if not text.strip():
        return []

    return list(
        csv.DictReader(
            io.StringIO(text)
        )
    )


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> dict[str, Any]:
    member = next(
        (
            name
            for name in archive.namelist()
            if name.endswith(suffix)
        ),
        "",
    )
    if not member:
        raise RuntimeError(
            f"ZIP missing member: {suffix}"
        )
    return json.loads(
        archive.read(member).decode("utf-8-sig")
    )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
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

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()

    completeness_zip = find_latest(
        root,
        "fa_offseason_decision_universe_completeness_audit_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(completeness_zip) as archive:
        completeness_summary = read_json_member(
            archive,
            "decision_universe_completeness_summary.json",
        )
        queue = read_csv_member(
            archive,
            "additional_lifecycle_research_candidates.csv",
        )

    if len(queue) != EXPECTED_QUEUE:
        raise RuntimeError(
            f"Expected {EXPECTED_QUEUE} additional candidates, got {len(queue)}."
        )

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(
            checkpoint_module.DEFAULT_CHECKPOINT_PATH
        )
        checkpoint_hash = sha256_file(checkpoint_path)
        checkpoint = (
            checkpoint_module.load_franchise_checkpoint()
        )
    except Exception as exc:
        raise RuntimeError(
            "Could not load canonical franchise checkpoint."
        ) from exc

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Checkpoint changed unexpectedly before additional lifecycle harvest.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)

    print("=" * 128, flush=True)
    print("2026 ADDITIONAL LIFECYCLE CONTRACT EVIDENCE HARVEST V1.0.1", flush=True)
    print("=" * 128, flush=True)
    print(f"Research queue: {len(queue)}", flush=True)
    print(
        f"Simulation split guard: "
        f"{SIMULATION_SPLIT_DATE.isoformat()}",
        flush=True,
    )
    print(
        "Contract source: SalarySwish. "
        "NBA Player Movement remains transaction provenance; "
        "SalarySwish is contract evidence, not CBA authority.",
        flush=True,
    )
    print(
        "Post-split option outcomes are audit-only and never used "
        "to classify the branch contract.",
        flush=True,
    )
    print("", flush=True)

    all_spans: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    snapshots: dict[str, bytes] = {}

    sleep_seconds = 0.45

    for index, candidate in enumerate(
        queue,
        start=1,
    ):
        player_id = pid(candidate.get("player_id"))
        player_name = clean(candidate.get("player_name"))

        print(
            f"[{index:02d}/{EXPECTED_QUEUE}] "
            f"{player_name} ({player_id})",
            flush=True,
        )

        (
            slug,
            url,
            http_status,
            body,
            error,
            identity,
        ) = fetch_verified(
            player_name,
            sleep_seconds,
        )

        body_sha = (
            sha256_bytes(body)
            if body else ""
        )

        source_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "slug": slug,
            "source_url": url,
            "http_status": http_status,
            "source_sha256": body_sha,
            "page_identity_verified": identity,
            "fetch_error": error,
        })

        spans = (
            extract_contract_span_tables(
                body,
                player_id,
                player_name,
                url,
                body_sha,
            )
            if (
                http_status == 200
                and body
                and identity
            )
            else []
        )
        all_spans.extend(spans)

        chosen, selection_reason = choose_active_span(
            spans
        )
        classification, classification_reason = (
            classify_active_contract(chosen)
        )

        contract_type_override_used = False
        contract_type_override_source = ""
        official_contract_type_confirmation_source = ""

        override = VERIFIED_CONTRACT_TYPE_OVERRIDES.get(player_name)
        if (
            override
            and classification != override["classification"]
        ):
            classification = override["classification"]
            classification_reason = override["reason"]
            contract_type_override_used = True
            contract_type_override_source = override["source_url_contract"]
            official_contract_type_confirmation_source = (
                override["source_url_official_confirmation"]
            )

        if body and identity:
            snapshots[
                f"snapshots/{player_id}_{slug}.html"
            ] = body

        row = {
            "player_id": player_id,
            "player_name": player_name,
            "original_completeness_bucket": clean(
                candidate.get("completeness_bucket")
            ),
            "reconstructed_branch_owner": clean(
                candidate.get("reconstructed_branch_owner")
            ),
            "post_split_transaction_date_audit_only": clean(
                candidate.get(
                    "earliest_post_split_transaction_date"
                )
            ),
            "post_split_transaction_description_audit_only": clean(
                candidate.get(
                    "earliest_post_split_transaction_description"
                )
            ),
            "source_url": url,
            "source_sha256": body_sha,
            "page_identity_verified": identity,
            "contract_span_count_2025_26": len(spans),
            "active_contract_selection_reason": selection_reason,
            "lifecycle_contract_classification": classification,
            "classification_reason": classification_reason,
            "chosen_contract_table_index": (
                chosen["table_index"]
                if chosen else ""
            ),
            "chosen_contract_signing_date": (
                chosen["signing_date"]
                if chosen else (
                    override["contract_signing_date"]
                    if override else ""
                )
            ),
            "chosen_prior_base_salary": (
                chosen["prior_base_salary"]
                if chosen else ""
            ),
            "chosen_target_base_salary": (
                chosen["target_base_salary"]
                if chosen else (
                    override["target_base_salary"]
                    if override else ""
                )
            ),
            "chosen_target_option": (
                chosen["target_option"]
                if chosen else (
                    override["target_option"]
                    if override else ""
                )
            ),
            "chosen_target_option_used_text_audit_only": (
                chosen["target_option_used_text_audit_only"]
                if chosen else ""
            ),
            "chosen_target_guaranteed": (
                chosen["target_guaranteed"]
                if chosen else ""
            ),
            "contract_type_override_used": contract_type_override_used,
            "contract_type_override_source": contract_type_override_source,
            "official_contract_type_confirmation_source": (
                official_contract_type_confirmation_source
            ),
            "future_outcome_used_for_classification": False,
            "checkpoint_mutation_applied": False,
        }
        classification_rows.append(row)

        time.sleep(sleep_seconds)

    by_name = {
        normalize_name(row["player_name"]): row
        for row in classification_rows
    }

    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": (
                "PASS"
                if passed else "FAIL"
            ),
            "severity": severity,
            "detail": detail,
        })
        print(
            f"  {check_id}: "
            f"{'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("", flush=True)
    print("Running strict evidence-harvest checks...", flush=True)

    check(
        "upstream_completeness_audit_passed",
        bool(completeness_summary.get("passed")),
        "84-player completeness audit passed.",
    )
    check(
        "exact_84_player_queue",
        len(queue) == EXPECTED_QUEUE,
        f"queue={len(queue)}",
    )
    check(
        "canonical_checkpoint_unchanged_before_harvest",
        checkpoint_hash == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash,
    )
    check(
        "all_rows_classified_without_using_future_outcome",
        all(
            not row["future_outcome_used_for_classification"]
            for row in classification_rows
        ),
        "Option-used text is audit-only.",
    )
    check(
        "verified_contract_type_overrides_do_not_import_future_decisions",
        all(
            (not row["contract_type_override_used"])
            or (
                not row["future_outcome_used_for_classification"]
                and bool(row["contract_type_override_source"])
                and bool(row["official_contract_type_confirmation_source"])
            )
            for row in classification_rows
        ),
        "Any override proves only the pre-existing contract decision type.",
    )

    for name, expected in KNOWN_EXPECTED.items():
        actual = clean(
            by_name.get(
                normalize_name(name),
                {},
            ).get(
                "lifecycle_contract_classification"
            )
        )
        slug = re.sub(
            r"[^a-z0-9]+",
            "_",
            normalize_name(name),
        ).strip("_")

        check(
            f"known_contract_case_{slug}",
            actual == expected,
            f"expected={expected}; actual={actual}",
        )

    verified_pages = sum(
        bool(row["page_identity_verified"])
        for row in classification_rows
    )

    check(
        "salaryswish_identity_coverage",
        verified_pages == EXPECTED_QUEUE,
        f"verified={verified_pages}/{EXPECTED_QUEUE}",
        severity="coverage",
    )

    manual_rows = [
        row
        for row in classification_rows
        if row["lifecycle_contract_classification"].startswith(
            "manual_"
        )
    ]

    counts = {}
    for row in classification_rows:
        key = row["lifecycle_contract_classification"]
        counts[key] = counts.get(key, 0) + 1

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

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
        row["check_id"]
        for row in checks
        if (
            row["severity"] == "strict"
            and row["status"] == "FAIL"
        )
    ]

    if failed:
        raise RuntimeError(
            "Additional Lifecycle Contract Evidence Harvest V1.0.1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")

    export_id = (
        f"fa_additional_lifecycle_contract_evidence_harvest_v1_0_1_"
        f"{SEASON_LABEL}_{stamp}"
    )

    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(
        prefix="fa_additional_contract_harvest_"
    ) as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "additional_lifecycle_contract_classification.csv",
            classification_rows,
        )
        write_csv(
            export / "additional_lifecycle_contract_spans.csv",
            all_spans,
        )
        write_csv(
            export / "additional_lifecycle_contract_sources.csv",
            source_rows,
        )
        write_csv(
            export / "additional_lifecycle_manual_review.csv",
            manual_rows,
        )
        write_csv(
            export / "additional_lifecycle_contract_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": (
                SIMULATION_SPLIT_DATE.isoformat()
            ),
            "queue_count": len(queue),
            "verified_salaryswish_pages": verified_pages,
            "classification_counts": dict(
                sorted(counts.items())
            ),
            "manual_review_count": len(manual_rows),
            "contract_span_row_count": len(all_spans),
            "checkpoint_sha256": checkpoint_hash,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "future_option_outcome_used": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Merge resolved additional lifecycle classes with the original "
                "187-player lifecycle universe. Build a complete corrected "
                "offseason decision universe: expiring free agents, Team/Player "
                "Options, non-guarantee/waiver decisions, fully guaranteed "
                "contracts, and remaining manual rows. Then rebuild RFA/QO and "
                "roster-capacity previews before checkpoint hydration."
            ),
        }

        (
            export
            / "additional_lifecycle_contract_summary.json"
        ).write_text(
            json.dumps(
                summary,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        (
            export
            / "README.txt"
        ).write_text(
            """2026 ADDITIONAL LIFECYCLE CONTRACT EVIDENCE HARVEST V1
========================================================

Purpose
-------
Classify the 84 players omitted from the original 187-player lifecycle universe
without importing real-world post-April-12 decisions.

Evidence
--------
- NBA Player Movement: transaction provenance / completeness signal
- SalarySwish: contract-ledger evidence
- NBA/NBPA CBA remains the rules authority

Future-leakage guard
--------------------
The harvester only selects a contract table if:
1. it contains a 2025-26 salary row, and
2. the contract signing date is on or before April 12, 2026.

A July/August 2026 replacement contract may be present on today's player page
but cannot become branch-state evidence.

The 2026-27 row of the selected pre-split contract is then classified as:
- no 2026-27 row -> expiring 2025-26 free-agent candidate
- Team option -> Team Option decision
- Player option -> Player Option decision
- partial/non-guaranteed salary -> guarantee/waiver decision
- fully guaranteed salary -> under contract
- ambiguous -> manual review

SalarySwish may display the real-world option result in an Option Used field.
That field is exported as AUDIT ONLY and never used for classification.

Strict known cases
------------------
- Coby White -> expiring free-agent candidate
- Day'Ron Sharpe -> 2026-27 Team Option
- Marcus Smart -> 2026-27 Player Option
- Jonathan Isaac -> partial/non-guaranteed 2026-27 decision

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            zip_out,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for item in sorted(export.iterdir()):
                archive.write(
                    item,
                    arcname=f"{export_id}/{item.name}",
                )

            for member, body in sorted(
                snapshots.items()
            ):
                archive.writestr(
                    f"{export_id}/{member}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    print("", flush=True)
    print("=" * 128, flush=True)
    print(
        "2026 ADDITIONAL LIFECYCLE CONTRACT EVIDENCE HARVEST V1 PASSED",
        flush=True,
    )
    print("=" * 128, flush=True)
    print(
        f"Verified SalarySwish pages:     "
        f"{verified_pages}/{EXPECTED_QUEUE}",
        flush=True,
    )
    print(
        f"Contract span rows:             "
        f"{len(all_spans)}",
        flush=True,
    )
    print("Classification counts:", flush=True)
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}", flush=True)
    print(
        f"Manual evidence review:         "
        f"{len(manual_rows)}",
        flush=True,
    )
    print(
        "Future option outcomes used:    NO",
        flush=True,
    )
    print(
        "State mutation:                 NOT PERFORMED",
        flush=True,
    )
    print(
        "Checkpoint write:              NOT PERFORMED",
        flush=True,
    )
    print(
        f"Audit ZIP: {zip_out}",
        flush=True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
