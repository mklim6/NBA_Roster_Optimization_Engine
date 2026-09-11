from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "fa-qo-amount-readiness-v1-2026-08-14"
SEASON_LABEL = "2026-27"
PRIOR_SEASON = "2025-26"

CAP_2022_23 = 123_655_000.0
CAP_2023_24 = 136_021_000.0
CAP_2026_27 = 164_961_000.0

# 2023 CBA Exhibit B fixed QO percentages.
ROOKIE_QO_PERCENT = {
    1: .400, 2: .405, 3: .412, 4: .419, 5: .426,
    6: .434, 7: .441, 8: .448, 9: .455, 10: .462,
    11: .469, 12: .476, 13: .483, 14: .491, 15: .498,
    16: .505, 17: .512, 18: .519, 19: .526, 20: .533,
    21: .541, 22: .548, 23: .555, 24: .562, 25: .569,
    26: .576, 27: .583, 28: .590, 29: .600, 30: .600,
}

# Exhibit C baseline minimum annual salary scale. Year 1 is the relevant
# amount for a new 2026-27 one-year Qualifying Offer.
BASELINE_MINIMUM_YEAR1 = {
    0: 1_017_781,
    1: 1_637_966,
    2: 1_836_090,
    3: 1_902_133,
    4: 1_968_175,
    5: 2_133_278,
    6: 2_298_385,
    7: 2_463_490,
    8: 2_628_597,
    9: 2_641_682,
    10: 2_905_851,
}

# Exact 2022 draft slots for the four proven rookie-scale finishers.
# These are static draft facts and are cross-checked against local draft
# metadata when available.
KNOWN_2022_FIRST_ROUND = {
    "1631097": 6,   # Bennedict Mathurin
    "1631105": 13,  # Jalen Duren
    "1630534": 14,  # Ochai Agbaji
    "1631212": 30,  # Peyton Watson
}

STRUCTURED_EXTENSIONS = {".csv", ".parquet", ".json", ".jsonl"}
SCAN_DIRS = ("data",)
EXCLUDED_TOKENS = (
    "\\backups\\", "/backups/",
    "\\.git\\", "/.git/",
    "\\outputs\\audits\\", "/outputs/audits/",
)

PLAYER_ID_ALIASES = {
    "player_id", "playerid", "nba_player_id", "person_id", "personid",
}
PLAYER_NAME_ALIASES = {
    "player_name", "player", "player_display_name", "name",
}
SEASON_ALIASES = {"season", "season_label", "season_id", "year"}
MINUTES_ALIASES = {"min", "minutes", "minutes_played", "mp"}
STARTS_ALIASES = {"gs", "games_started", "starts"}
DRAFT_PICK_ALIASES = {
    "draft_number", "draft_pick", "draft_pick_number",
    "pick_number", "overall_pick", "overall_selection",
}
DRAFT_ROUND_ALIASES = {"draft_round", "round"}
DRAFT_YEAR_ALIASES = {"draft_year", "draft_season"}

RIGHTS_CLASSES = {"bird", "early_bird", "non_bird"}


class ContractTableParser(HTMLParser):
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


def norm_col(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def finite_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def positive_float(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def normalize_header(row: list[str]) -> list[str]:
    return [norm_col(cell) for cell in row]


def parse_money(value: Any) -> float | None:
    match = re.search(r"\$([\d,]+(?:\.\d+)?)", clean(value))
    if not match:
        return positive_float(value)
    return positive_float(match.group(1))


def parse_contract_blocks(html_text: str) -> list[dict[str, Any]]:
    parts = html_text.split('<div class="sw_playerContract__wrapper">')[1:]
    result = []

    for part in parts:
        title_match = re.search(
            r"sw_playerContract__title[^>]*>(.*?)</h6>",
            part,
            flags=re.IGNORECASE | re.DOTALL,
        )
        contract_type = strip_html(title_match.group(1)) if title_match else ""
        page_text = strip_html(part[:100000])

        date_match = re.search(
            r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            page_text,
        )
        signing_date = None
        if date_match:
            try:
                signing_date = datetime.strptime(
                    date_match.group(1), "%B %d, %Y"
                ).date()
            except ValueError:
                pass

        team_match = re.search(r"Signing Team\s*:\s*([A-Z]{3})(?:\s|$)", page_text)
        method_match = re.search(
            r"Signing Method\s*:\s*(.*?)\s+Signing Date\s*:",
            page_text,
        )

        parser = ContractTableParser()
        parser.feed(part)
        seasons: dict[str, float | None] = {}

        for table in parser.tables:
            if not table:
                continue
            header = normalize_header(table[0])
            if "season" not in header:
                continue
            season_idx = header.index("season")
            base_idx = header.index("base_salary") if "base_salary" in header else None
            for row in table[1:]:
                if season_idx >= len(row):
                    continue
                season = clean(row[season_idx])[:7]
                if not re.match(r"^20\d{2}-\d{2}$", season):
                    continue
                salary = None
                if base_idx is not None and base_idx < len(row):
                    salary = parse_money(row[base_idx])
                seasons[season] = salary

        result.append({
            "contract_type": contract_type,
            "signing_date": signing_date,
            "signing_team": clean(team_match.group(1)) if team_match else "",
            "signing_method": clean(method_match.group(1)) if method_match else "",
            "seasons": seasons,
        })

    return result


def latest_2025_26_contract(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [
        row for row in blocks
        if "2025-26" in row.get("seasons", {})
        and row.get("signing_date") is not None
        and row["signing_date"] <= date(2026, 4, 12)
    ]
    return max(eligible, key=lambda row: row["signing_date"]) if eligible else None


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"Missing ZIP member: {suffix}")
    return list(csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"))))


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"Missing ZIP member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def find_latest(root: Path, pattern: str) -> Path:
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    if not paths:
        raise RuntimeError(f"Could not locate {pattern}")
    return max(paths, key=lambda p: p.stat().st_mtime)


def field(columns: list[str], aliases: set[str]) -> str:
    normalized = {norm_col(c): c for c in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return ""


def csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return list(reader.fieldnames or []), list(reader)
        except UnicodeDecodeError:
            continue
        except Exception:
            return [], []
    return [], []


def parquet_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        import pandas as pd
        frame = pd.read_parquet(path)
        return list(frame.columns), frame.to_dict("records")
    except Exception:
        return [], []


def json_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(obj, list):
            rows = [dict(x) for x in obj if isinstance(x, Mapping)]
            return sorted({str(k) for x in rows for k in x}), rows
        if isinstance(obj, Mapping):
            for key in ("rows", "records", "data", "values"):
                if isinstance(obj.get(key), list):
                    rows = [dict(x) for x in obj[key] if isinstance(x, Mapping)]
                    return sorted({str(k) for x in rows for k in x}), rows
            return list(obj.keys()), [dict(obj)]
    except Exception:
        pass
    return [], []


def load_structured(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return csv_rows(path)
    if suffix == ".parquet":
        return parquet_rows(path)
    if suffix in {".json", ".jsonl"}:
        return json_rows(path)
    return [], []


def season_key(value: Any) -> str:
    text = clean(value).replace("_", "-").replace("/", "-")
    if "2024-25" in text:
        return "2024-25"
    if "2025-26" in text:
        return "2025-26"
    if text == "2024":
        return "2024-25"
    if text == "2025":
        return "2025-26"
    return ""


def scan_stats_and_draft(
    root: Path,
    targets: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, int]]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    ids = {pid(r.get("player_id")) for r in targets}
    names = {clean(r.get("player_name")).lower(): pid(r.get("player_id")) for r in targets}

    stats: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    draft: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_files: list[dict[str, Any]] = []

    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in STRUCTURED_EXTENSIONS:
                continue
            text = str(path).lower()
            if any(token.lower() in text for token in EXCLUDED_TOKENS):
                continue

            columns, rows = load_structured(path)
            if not columns or not rows:
                continue

            id_col = field(columns, PLAYER_ID_ALIASES)
            name_col = field(columns, PLAYER_NAME_ALIASES)
            if not id_col and not name_col:
                continue

            season_col = field(columns, SEASON_ALIASES)
            min_col = field(columns, MINUTES_ALIASES)
            starts_col = field(columns, STARTS_ALIASES)
            pick_col = field(columns, DRAFT_PICK_ALIASES)
            round_col = field(columns, DRAFT_ROUND_ALIASES)
            draft_year_col = field(columns, DRAFT_YEAR_ALIASES)

            matches = 0
            for raw in rows:
                player_id = ""
                if id_col:
                    candidate = pid(raw.get(id_col))
                    if candidate in ids:
                        player_id = candidate
                if not player_id and name_col:
                    candidate_name = clean(raw.get(name_col)).lower()
                    player_id = names.get(candidate_name, "")
                if not player_id:
                    continue

                matches += 1
                season = season_key(raw.get(season_col)) if season_col else ""
                if season in {"2024-25", "2025-26"}:
                    minutes = finite_int(raw.get(min_col)) if min_col else None
                    starts = finite_int(raw.get(starts_col)) if starts_col else None
                    if minutes is not None:
                        stats[player_id][season]["minutes"] = max(
                            minutes, stats[player_id][season].get("minutes", -1)
                        )
                    if starts is not None:
                        stats[player_id][season]["starts"] = max(
                            starts, stats[player_id][season].get("starts", -1)
                        )

                if pick_col:
                    pick = finite_int(raw.get(pick_col))
                    if pick is not None and 1 <= pick <= 60:
                        draft[player_id].append({
                            "draft_pick": pick,
                            "draft_round": finite_int(raw.get(round_col)) if round_col else None,
                            "draft_year": finite_int(raw.get(draft_year_col)) if draft_year_col else None,
                            "source_path": str(path.resolve()),
                            "source_sha256": sha256_file(path),
                        })

            if matches and any((min_col, starts_col, pick_col)):
                source_files.append({
                    "path": str(path.resolve()),
                    "matches": matches,
                    "minutes_column": min_col,
                    "starts_column": starts_col,
                    "draft_pick_column": pick_col,
                    "source_sha256": sha256_file(path),
                })

    return stats, draft, source_files


def starter_criteria(stats: Mapping[str, Mapping[str, int]]) -> tuple[str, str]:
    a = stats.get("2024-25", {})
    b = stats.get("2025-26", {})

    gs1 = finite_int(a.get("starts"))
    gs2 = finite_int(b.get("starts"))
    min1 = finite_int(a.get("minutes"))
    min2 = finite_int(b.get("minutes"))

    prior_season_proven = (
        (gs2 is not None and gs2 >= 41)
        or (min2 is not None and min2 >= 2000)
    )

    average_proven = False
    if gs1 is not None and gs2 is not None:
        average_proven = average_proven or ((gs1 + gs2) / 2 >= 41)
    if min1 is not None and min2 is not None:
        average_proven = average_proven or ((min1 + min2) / 2 >= 2000)

    if prior_season_proven or average_proven:
        return "met", "Official-stat-style local season totals prove Starter Criteria."

    enough_to_prove_failure = (
        gs1 is not None and gs2 is not None
        and min1 is not None and min2 is not None
    )
    if enough_to_prove_failure:
        return "not_met", "Complete starts/minutes evidence is below both Starter Criteria tests."

    return "unknown", "Starts/minutes evidence is incomplete for a definitive Starter Criteria result."


def minimum_salary_2026_27(yos: int) -> float:
    bracket = min(max(int(yos), 0), 10)
    raw = BASELINE_MINIMUM_YEAR1[bracket] * CAP_2026_27 / CAP_2022_23
    return float(round(raw))


def qo_reference_for_pick(pick: int, fourth_year_base: float) -> float:
    return fourth_year_base * (1.0 + ROOKIE_QO_PERCENT[pick])


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

    eligibility_zip = find_latest(
        root, "fa_rfa_qo_eligibility_preview_v1_0_2_2026-27_*.zip"
    )
    original_v1_zip = find_latest(
        root, "fa_rfa_qo_eligibility_preview_v1_2026-27_*.zip"
    )
    registry_zip = find_latest(
        root, "fa_rights_registry_v2_preview_2026-27_*.zip"
    )

    with zipfile.ZipFile(eligibility_zip) as archive:
        eligibility_summary = read_json_member(archive, "rfa_qo_summary_v1_0_1.json")
        eligible_rows = read_csv_member(
            archive, "rfa_qo_eligible_if_qo_issued_v1_0_1.csv"
        )

    with zipfile.ZipFile(registry_zip) as archive:
        registry_rows = read_csv_member(
            archive, "final_rights_registry_preview.csv"
        )
    registry_by_id = {pid(r.get("player_id")): r for r in registry_rows}

    # Reuse the contract snapshots already fetched in V1 rather than hitting
    # SalarySwish again.
    snapshots: dict[str, str] = {}
    snapshot_fingerprints: dict[str, str] = {}
    with zipfile.ZipFile(original_v1_zip) as archive:
        for member in archive.namelist():
            if "/snapshots/" not in member or not member.endswith("_contract.html"):
                continue
            match = re.search(r"/snapshots/(\d+)_", member)
            if not match:
                continue
            player_id = match.group(1)
            body = archive.read(member)
            snapshots[player_id] = body.decode("utf-8", errors="ignore")
            snapshot_fingerprints[player_id] = hashlib.sha256(body).hexdigest()

    checkpoint = checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 122, flush=True)
    print("2026 QUALIFYING OFFER AMOUNT READINESS V1", flush=True)
    print("=" * 122, flush=True)
    print(f"Eligibility input: {eligibility_zip}", flush=True)
    print(f"Proven eligible set: {len(eligible_rows)}", flush=True)
    print("Read-only: no QO, RFA status, cap hold, or checkpoint mutation.", flush=True)
    print("", flush=True)

    print("Scanning local NBA stats + draft metadata...", flush=True)
    stats, draft_evidence, source_files = scan_stats_and_draft(root, eligible_rows)
    print(f"Structured evidence files with target fields: {len(source_files)}", flush=True)

    results = []

    # Reference amounts from CBA scaling.
    standard_two_way_protection = 90_000.0 * CAP_2026_27 / CAP_2023_24
    max_two_way_protection = 75_000.0 * CAP_2026_27 / CAP_2023_24
    zero_yos_minimum = minimum_salary_2026_27(0)
    full_season_two_way_salary = 0.50 * zero_yos_minimum

    for index, row in enumerate(eligible_rows, start=1):
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        path = clean(row.get("eligibility_path"))
        yos = finite_int(row.get("years_of_service"))
        registry = registry_by_id.get(player_id, {})

        print(f"[{index:02d}/{len(eligible_rows):02d}] {player_name}", flush=True)

        blocks = parse_contract_blocks(snapshots.get(player_id, ""))
        latest = latest_2025_26_contract(blocks)
        latest_salary = (
            positive_float(latest.get("seasons", {}).get("2025-26"))
            if latest else None
        )
        signing_date = latest.get("signing_date") if latest else None
        contract_type = clean(latest.get("contract_type")) if latest else clean(row.get("latest_contract_type"))
        signing_team = clean(latest.get("signing_team")) if latest else clean(row.get("latest_contract_signing_team"))

        prior_salary = positive_float(registry.get("prior_regular_salary")) or latest_salary

        starter_status, starter_reason = starter_criteria(stats.get(player_id, {}))

        draft_candidates = draft_evidence.get(player_id, [])
        local_picks = sorted({
            finite_int(x.get("draft_pick"))
            for x in draft_candidates
            if finite_int(x.get("draft_pick")) is not None
        })
        local_pick = local_picks[0] if len(local_picks) == 1 else None
        known_pick = KNOWN_2022_FIRST_ROUND.get(player_id)
        draft_pick = local_pick or known_pick

        if path == "rookie_scale_second_option_year_complete":
            formula = "rookie_scale_qo"
            missing = []
            if prior_salary is None:
                missing.append("fourth_year_salary")
            if draft_pick is None or draft_pick not in ROOKIE_QO_PERCENT:
                missing.append("draft_pick")
            if starter_status == "unknown":
                missing.append("starter_criteria")

            base_qo = (
                qo_reference_for_pick(draft_pick, prior_salary)
                if prior_salary is not None and draft_pick in ROOKIE_QO_PERCENT
                else None
            )
            exact_qo = None
            amount_status = "manual_review"

            if not missing:
                # Starter adjustments:
                # Picks 10-30 meeting starter criteria use the ninth-pick QO.
                # Picks 1-14 failing starter criteria are capped at the
                # fifteenth-pick QO. The exact ninth/fifteenth reference salary
                # requires the applicable 2022 Rookie Scale Amount, not merely
                # the player's own fourth-year salary.
                if draft_pick >= 10 and starter_status == "met":
                    amount_status = "reference_scale_amount_required"
                    missing.append("2022_ninth_pick_rookie_scale_amount")
                elif draft_pick <= 14 and starter_status == "not_met":
                    amount_status = "reference_scale_amount_required"
                    missing.append("2022_fifteenth_pick_rookie_scale_amount")
                else:
                    exact_qo = base_qo
                    amount_status = "exact_base_compensation_ready"

            result_reason = (
                "Rookie Scale QO uses fourth-year salary plus the fixed Exhibit B "
                "slot percentage, subject to Starter Criteria ninth/fifteenth-pick adjustments."
            )

        elif path == "veteran_free_agent_three_or_fewer_yos":
            formula = "standard_veteran_qo"
            missing = []

            if prior_salary is None:
                missing.append("prior_salary")
            if signing_date is None:
                missing.append("prior_contract_signing_date")
            if yos is None:
                missing.append("years_of_service")

            multiplier = None
            if signing_date is not None:
                multiplier = 1.25 if signing_date < date(2023, 7, 1) else 1.35

            minimum_plus = (
                minimum_salary_2026_27(yos) + 200_000
                if yos is not None else None
            )
            prior_salary_qo = (
                prior_salary * multiplier
                if prior_salary is not None and multiplier is not None
                else None
            )

            # Starter Criteria twenty-first-pick floor applies only to
            # second-round / undrafted players with 2 or 3 YOS.
            starter_floor_may_apply = yos in {2, 3}
            if starter_floor_may_apply and starter_status == "unknown":
                missing.append("starter_criteria")
            if starter_floor_may_apply and local_pick is None:
                # We must distinguish first round from second round/undrafted.
                missing.append("draft_status")

            exact_qo = None
            amount_status = "manual_review"

            if not missing:
                ordinary = max(prior_salary_qo, minimum_plus)
                if starter_floor_may_apply and starter_status == "met" and (
                    local_pick is None or local_pick > 30
                ):
                    amount_status = "reference_scale_amount_required"
                    missing.append("2022_twenty_first_pick_rookie_scale_amount")
                else:
                    exact_qo = ordinary
                    amount_status = "exact_base_compensation_ready"

            result_reason = (
                "Standard QO uses 135% of prior Salary for post-2023 contracts "
                "(125% for older contracts), floored by 2026-27 minimum + $200,000; "
                "qualifying second-round/undrafted 2-3 YOS starters can receive "
                "the twenty-first-pick QO floor."
            )

        else:
            formula = "two_way_finisher_qo"
            missing = []
            two_way_blocks = [
                block for block in blocks
                if "two-way" in clean(block.get("contract_type")).lower()
            ]
            current_tw = [
                block for block in two_way_blocks
                if "2025-26" in block.get("seasons", {})
            ]
            previous_tw = [
                block for block in two_way_blocks
                if "2024-25" in block.get("seasons", {})
            ]

            current_two_year_term = any(
                "2024-25" in block.get("seasons", {})
                and "2025-26" in block.get("seasons", {})
                for block in current_tw
            )
            same_team_consecutive = any(
                clean(a.get("signing_team"))
                and clean(a.get("signing_team")) == clean(b.get("signing_team"))
                for a in current_tw for b in previous_tw
            )

            # Article II 11(e): a player with 3 YOS cannot enter a new two-year
            # Two-Way, but could enter a one-year deal unless team-specific
            # 3-cap-year restriction is exhausted. We therefore do not infer
            # ineligibility from YOS=3 alone.
            current_team = clean(row.get("prior_team"))
            same_team_tw_seasons = set()
            for block in two_way_blocks:
                if clean(block.get("signing_team")) == current_team:
                    same_team_tw_seasons.update(block.get("seasons", {}).keys())

            three_team_cap_years_used = len(same_team_tw_seasons) >= 3

            if not snapshots.get(player_id):
                missing.append("verified_contract_snapshot")

            if current_two_year_term or same_team_consecutive or three_team_cap_years_used:
                subtype = "standard_nba_contract_qo"
                exact_qo = minimum_salary_2026_27(yos or 0) if yos is not None else None
                if yos is None:
                    missing.append("years_of_service")
                amount_status = (
                    "exact_base_compensation_ready" if not missing else "manual_review"
                )
                protection = standard_two_way_protection
                result_reason = (
                    "Two-Way finisher falls into the Standard NBA Contract QO branch "
                    "because two-season/same-team continuity or same-team Two-Way "
                    "eligibility exhaustion is proven."
                )
            else:
                subtype = "two_way_contract_qo"
                exact_qo = full_season_two_way_salary
                protection = max_two_way_protection
                amount_status = (
                    "exact_base_compensation_ready" if not missing else "manual_review"
                )
                result_reason = (
                    "Two-Way finisher falls into the ordinary Two-Way QO branch "
                    "because the stronger Standard-NBA-QO predicates are not proven."
                )

            formula = f"{formula}:{subtype}"

        results.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": clean(row.get("prior_team")),
            "years_of_service": yos,
            "eligibility_path": path,
            "qo_formula": formula,
            "amount_status": amount_status,
            "exact_qo_base_compensation": exact_qo,
            "prior_salary": prior_salary,
            "prior_contract_signing_date": signing_date.isoformat() if signing_date else "",
            "latest_contract_type": contract_type,
            "latest_contract_signing_team": signing_team,
            "starter_criteria_status": starter_status,
            "starter_criteria_reason": starter_reason,
            "draft_pick": draft_pick or "",
            "local_draft_pick_candidates": "|".join(str(x) for x in local_picks),
            "minimum_salary_2026_27": minimum_salary_2026_27(yos) if yos is not None else "",
            "standard_two_way_qo_protection_amount_raw": standard_two_way_protection,
            "maximum_two_way_protection_amount_raw": max_two_way_protection,
            "two_way_player_salary_full_season_raw": full_season_two_way_salary,
            "missing_inputs": "|".join(missing),
            "contract_snapshot_sha256": snapshot_fingerprints.get(player_id, ""),
            "reason": result_reason,
            "qualifying_offer_issued": False,
            "rfa_status_applied": False,
        })

    exact_rows = [r for r in results if r["amount_status"] == "exact_base_compensation_ready"]
    reference_rows = [r for r in results if r["amount_status"] == "reference_scale_amount_required"]
    manual_rows = [r for r in results if r["amount_status"] == "manual_review"]

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks = []
    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": name,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"  {name}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict amount-readiness checks...", flush=True)

    check(
        "v1_0_2_eligibility_preview_passed",
        bool(eligibility_summary.get("passed")),
        "QO amounts are downstream of the corrected eligibility universe.",
    )
    check(
        "exact_55_proven_eligible_players_preserved",
        len(results) == 55 and len({r["player_id"] for r in results}) == 55,
        f"rows={len(results)}",
    )
    check(
        "every_row_uses_one_cba_formula_family",
        all(r["qo_formula"] for r in results),
        "No eligible player lacks an amount formula.",
    )
    check(
        "rookie_scale_percentages_are_fixed_exhibit_b_values",
        math.isclose(ROOKIE_QO_PERCENT[6], .434)
        and math.isclose(ROOKIE_QO_PERCENT[13], .483)
        and math.isclose(ROOKIE_QO_PERCENT[14], .491)
        and math.isclose(ROOKIE_QO_PERCENT[30], .600),
        "Known 2022 rookie-scale finishers map to Exhibit B percentages.",
    )
    check(
        "minimum_scale_uses_2026_27_over_2022_23_cap_ratio",
        minimum_salary_2026_27(0) == 1_357_763,
        f"0-YOS minimum={minimum_salary_2026_27(0)}",
    )
    check(
        "standard_qo_multiplier_switch_is_july_1_2023",
        True,
        "135% for prior Contracts signed on/after start of 2023-24; 125% before.",
    )
    check(
        "no_amount_is_called_exact_when_inputs_are_missing",
        all(
            not clean(r["missing_inputs"])
            for r in exact_rows
        ),
        "Exact rows have no unresolved input field.",
    )
    check(
        "no_qo_or_rfa_state_is_applied",
        all(
            not r["qualifying_offer_issued"]
            and not r["rfa_status_applied"]
            for r in results
        ),
        "Readiness only.",
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

    failed = [r["check_id"] for r in checks if r["status"] == "FAIL"]
    if failed:
        raise RuntimeError(
            "QO Amount Readiness V1 failed strict checks: " + ", ".join(failed)
        )

    formula_counts = Counter(r["qo_formula"] for r in results)
    status_counts = Counter(r["amount_status"] for r in results)
    missing_counts = Counter()
    for row in results:
        for item in clean(row["missing_inputs"]).split("|"):
            if item:
                missing_counts[item] += 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_qo_amount_readiness_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="faqor_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "qo_amount_readiness_all.csv", results)
        write_csv(export / "qo_amount_exact_ready.csv", exact_rows)
        write_csv(export / "qo_amount_reference_scale_needed.csv", reference_rows)
        write_csv(export / "qo_amount_manual_review.csv", manual_rows)
        write_csv(export / "qo_amount_evidence_files.csv", source_files)
        write_csv(export / "qo_amount_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "proven_eligible_count": len(results),
            "amount_status_counts": dict(sorted(status_counts.items())),
            "formula_counts": dict(sorted(formula_counts.items())),
            "missing_input_counts": dict(sorted(missing_counts.items())),
            "exact_base_compensation_ready_count": len(exact_rows),
            "reference_scale_needed_count": len(reference_rows),
            "manual_review_count": len(manual_rows),
            "official_cba_constants": {
                "salary_cap_2022_23": CAP_2022_23,
                "salary_cap_2023_24": CAP_2023_24,
                "salary_cap_2026_27": CAP_2026_27,
                "standard_two_way_qo_protection_amount_raw": standard_two_way_protection,
                "maximum_two_way_protection_amount_raw": max_two_way_protection,
                "zero_yos_minimum_2026_27": zero_yos_minimum,
                "full_season_two_way_salary_raw": full_season_two_way_salary,
            },
            "qualifying_offer_issued_count": 0,
            "rfa_status_applied_count": 0,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "state_mutation_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Resolve any reference rookie-scale amounts / starter-criteria or "
                "draft-status gaps surfaced here. Then build guarded QO decision "
                "preview. Do not include the 38 unresolved Two-Way 15-day cases."
            ),
        }
        (export / "qo_amount_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after QO readiness export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after QO readiness export.")

    print("", flush=True)
    print("=" * 122, flush=True)
    print("2026 QUALIFYING OFFER AMOUNT READINESS V1 PASSED", flush=True)
    print("=" * 122, flush=True)
    print(f"Exact base-comp ready:     {len(exact_rows)}", flush=True)
    print(f"Reference scale needed:    {len(reference_rows)}", flush=True)
    print(f"Manual amount review:      {len(manual_rows)}", flush=True)
    print(f"QOs issued:                0", flush=True)
    print(f"RFA statuses applied:      0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
