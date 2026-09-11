from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import pickle
import re
import ssl
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-frozen-dead-cap-player-resolution-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
ACQUISITION_PATTERN = "fa_frozen_dead_cap_source_acquisition_v1_2026-27_*.zip"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
CONTRACT_PATTERN = "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_UPSTREAM_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
TEAM_NAME_TO_ABBR = {
    "Atlanta Hawks": "ATL", "Brooklyn Nets": "BKN", "Boston Celtics": "BOS",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}
REQUIRED_TEAMS = set(TEAM_NAME_TO_ABBR.values())


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def money_int(value: Any) -> int | None:
    text = clean(value).replace("$", "").replace(",", "")
    if text in {"", "-", "–", "—"}:
        return 0 if text else None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return int(number) if number == number.to_integral_value() else None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def strip_tags(value: str) -> str:
    return normalize_text(re.sub(r"<[^>]+>", " ", value))


def slugify_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", errors="ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_name.lower())).strip("-")


def parse_date(value: str) -> date | None:
    text = clean(value)
    for pattern in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def latest(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return member


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


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


def check_detail(rows: list[dict[str, str]], check_id: str) -> str:
    row = next(
        (
            item for item in rows
            if clean(item.get("check_id")) == check_id and clean(item.get("status")) == "PASS"
        ),
        {},
    )
    return clean(row.get("detail"))


def fetch_page(url: str) -> tuple[bytes, str, int, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                payload = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
                return payload, body, int(response.status), clean(response.geturl())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
    raise RuntimeError(f"Fetch failed after two attempts: {type(last_error).__name__}: {last_error}")


def parse_team_dead_cap_candidates(team: str, body: str, source_member: str) -> list[dict[str, Any]]:
    heading = re.search(
        r"<h3\b[^>]*>\s*DEAD\s+CAP\s*</h3>(.*?)(?=<h3\b[^>]*>.*?ACQUIRED\s+METHOD\s+SUMMARY)",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not heading:
        # SalarySwish omits the entire section for teams with no live dead cap.
        return []
    section = heading.group(1)
    candidates: list[dict[str, Any]] = []
    for table_index, table_match in enumerate(
        re.finditer(r"<table\b[^>]*>.*?</table>", section, re.IGNORECASE | re.DOTALL),
        start=1,
    ):
        table = table_match.group(0)
        header_match = re.search(r"<thead\b[^>]*>(.*?)</thead>", table, re.IGNORECASE | re.DOTALL)
        if not header_match:
            continue
        # The live source closes its first TH with TD. Split on the next TH start
        # instead of requiring valid closing tags so the season-column index stays exact.
        headers = [
            strip_tags(item)
            for item in re.findall(
                r"<th\b[^>]*>(.*?)(?=<th\b|</tr>)",
                header_match.group(1),
                re.IGNORECASE | re.DOTALL,
            )
        ]
        if not headers or SEASON_LABEL not in headers:
            continue
        method_match = re.match(r"(.+?)\s*\((\d+)\s*-\s*\$([\d,]+)\)", headers[0])
        if not method_match:
            continue
        method = clean(method_match.group(1))
        declared_count = int(method_match.group(2))
        declared_subtotal = int(method_match.group(3).replace(",", ""))
        season_column = headers.index(SEASON_LABEL)
        tbody_match = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", table, re.IGNORECASE | re.DOTALL)
        if not tbody_match:
            continue
        parsed_in_table = 0
        for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", tbody_match.group(1), re.IGNORECASE | re.DOTALL):
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_match.group(1), re.IGNORECASE | re.DOTALL)
            if not cells or season_column >= len(cells):
                continue
            player_match = re.search(
                r'<a\b[^>]*href="(/players/[^"]+)"[^>]*>(.*?)</a>',
                cells[0],
                re.IGNORECASE | re.DOTALL,
            )
            if not player_match:
                continue
            cap_hit_match = re.search(
                r'<span\b[^>]*class="[^"]*\bcap_hit\b[^"]*"[^>]*>(.*?)</span>',
                cells[season_column],
                re.IGNORECASE | re.DOTALL,
            )
            amount = money_int(strip_tags(cap_hit_match.group(1))) if cap_hit_match else 0
            candidates.append(
                {
                    "team": team,
                    "method": method,
                    "player_display_name": strip_tags(player_match.group(2)),
                    "player_href": player_match.group(1),
                    "player_source_url": "https://www.salaryswish.com" + player_match.group(1),
                    "season": SEASON_LABEL,
                    "dead_cap_amount": int(amount or 0),
                    "table_index": table_index,
                    "table_declared_player_count": declared_count,
                    "table_declared_2026_27_subtotal": declared_subtotal,
                    "team_snapshot_member": source_member,
                    "candidate_source_role": "post_split_player_discovery",
                    "applied_to_frozen_ledger": False,
                }
            )
            parsed_in_table += 1
        if parsed_in_table != declared_count:
            raise RuntimeError(
                f"{team} {method} declared {declared_count} players but parser found {parsed_in_table}."
            )
    return candidates


def parse_player_dead_cap_records(body: str, source_url: str, source_sha256: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page_title_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", body, re.IGNORECASE | re.DOTALL)
    page_title = strip_tags(page_title_match.group(1)) if page_title_match else ""
    heading_matches = list(
        re.finditer(r"<h4\b[^>]*>\s*DEAD\s+CAP\s*</h4>", body, re.IGNORECASE | re.DOTALL)
    )
    for heading_index, heading in enumerate(heading_matches, start=1):
        end_match = re.search(
            r"<h4\b[^>]*>\s*(?:SALARY\s+PROGRESSION|CAREER\s+STATS)",
            body[heading.end():],
            re.IGNORECASE | re.DOTALL,
        )
        end = heading.end() + end_match.start() if end_match else len(body)
        section = body[heading.end():end]
        section_text = strip_tags(section)
        meta_matches = list(
            re.finditer(
                r"TYPE:\s*(.+?)\s+TEAM:\s*(.+?)\s+LENGTH:\s*(.+?)\s+VALUE:\s*(\$[\d,]+|\$?0)\s+DATE:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                section_text,
                re.IGNORECASE,
            )
        )
        if not meta_matches:
            continue
        for record_index, meta in enumerate(meta_matches, start=1):
            method = clean(meta.group(1)).title()
            team_name = clean(meta.group(2))
            team = TEAM_NAME_TO_ABBR.get(team_name, "")
            length = clean(meta.group(3))
            declared_value = int(money_int(meta.group(4)) or 0)
            effective_date_text = clean(meta.group(5))
            effective_date = parse_date(effective_date_text)
            meta_pos = section_text.find(meta.group(0))
            next_meta_pos = (
                section_text.find(meta_matches[record_index].group(0))
                if record_index < len(meta_matches)
                else len(section_text)
            )
            text_chunk = section_text[meta_pos:next_meta_pos]
            season_match = re.search(
                rf"{re.escape(SEASON_LABEL)}\s+(\$[\d,]+|\$?0|[-–—])\s+(\$[\d,]+|\$?0|[-–—])",
                text_chunk,
                re.IGNORECASE,
            )
            base_salary = money_int(season_match.group(1)) if season_match else None
            cap_hit = money_int(season_match.group(2)) if season_match else None
            records.append(
                {
                    "page_title": page_title,
                    "source_url": source_url,
                    "source_sha256": source_sha256,
                    "heading_index": heading_index,
                    "record_index": record_index,
                    "method": method,
                    "team_name": team_name,
                    "team": team,
                    "length": length,
                    "declared_dead_cap_value": declared_value,
                    "effective_date_text": effective_date_text,
                    "effective_date": effective_date.isoformat() if effective_date else "",
                    "season": SEASON_LABEL,
                    "base_salary": base_salary,
                    "cap_hit": cap_hit,
                    "date_is_on_or_before_split": bool(effective_date and effective_date <= SPLIT_DATE),
                }
            )
    return records


def main() -> int:
    root = Path.cwd().resolve()
    acquisition_zip = latest(root, ACQUISITION_PATTERN)
    boundary_zip = latest(root, BOUNDARY_PATTERN)
    contract_zip = latest(root, CONTRACT_PATTERN)

    with zipfile.ZipFile(acquisition_zip) as archive:
        acquisition_summary = json_suffix(archive, "frozen_dead_cap_source_acquisition_summary.json")
        acquisition_checks = csv_suffix(archive, "frozen_dead_cap_source_acquisition_checks.csv")
        capture_rows = csv_suffix(archive, "dead_cap_source_capture_30.csv")
        team_candidates: list[dict[str, Any]] = []
        for capture in capture_rows:
            team = clean(capture.get("team"))
            member = member_suffix(archive, clean(capture.get("snapshot_filename")))
            body = archive.read(member).decode("utf-8", errors="replace")
            team_candidates.extend(parse_team_dead_cap_candidates(team, body, member))

    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")

    with zipfile.ZipFile(contract_zip) as archive:
        contract_summary = json_suffix(archive, "contract_option_summary.json")
        lifecycle_rows = csv_suffix(archive, "contract_option_lifecycle_all.csv")
        waiver_lifecycle_rows = [
            row for row in lifecycle_rows
            if clean(row.get("contract_lifecycle_state")) == "free_agent_waiver_terminated"
        ]
        lifecycle_snapshot_rows: list[dict[str, Any]] = []
        lifecycle_snapshot_missing: list[dict[str, Any]] = []
        for row in waiver_lifecycle_rows:
            player_id = clean(row.get("player_id"))
            member = next(
                (
                    name for name in archive.namelist()
                    if re.search(rf"/snapshots/{re.escape(player_id)}_.*\.html$", name)
                ),
                "",
            )
            if not member:
                lifecycle_snapshot_missing.append(
                    {
                        "player_id": player_id,
                        "player_name": clean(row.get("player_name")),
                        "prior_team": clean(row.get("prior_team")),
                        "player_slug": slugify_name(clean(row.get("player_name"))),
                    }
                )
                continue
            member_name = Path(member).name
            slug_match = re.match(r"\d+_(.+?)_contract\.html$", member_name)
            player_slug = slug_match.group(1) if slug_match else slugify_name(clean(row.get("player_name")))
            payload = archive.read(member)
            records = parse_player_dead_cap_records(
                payload.decode("utf-8", errors="replace"),
                f"audit://{contract_zip.name}/{member}",
                sha256_bytes(payload),
            )
            for record in records:
                lifecycle_snapshot_rows.append(
                    {
                        "player_id": player_id,
                        "player_name": clean(row.get("player_name")),
                        "prior_team": clean(row.get("prior_team")),
                        "contract_lifecycle_state": clean(row.get("contract_lifecycle_state")),
                        "player_slug": player_slug,
                        "snapshot_member": member,
                        "evidence_origin": "retained_contract_lifecycle_audit_snapshot",
                        **record,
                    }
                )

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before frozen dead-cap player resolution preview.")

    player_page_captures: list[dict[str, Any]] = []
    player_page_records: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []
    player_snapshots: dict[str, bytes] = {}
    lifecycle_fallback_captures: list[dict[str, Any]] = []
    lifecycle_fallback_fetch_errors: list[dict[str, Any]] = []
    lifecycle_fallback_snapshots: dict[str, bytes] = {}
    print("=" * 132)
    print("2026 FROZEN DEAD-CAP PLAYER RESOLUTION PREVIEW V1")
    print("=" * 132)
    print("Fetching and date-resolving the 18 exact player-level dead-cap candidates...")
    for index, candidate in enumerate(team_candidates, start=1):
        url = clean(candidate.get("player_source_url"))
        slug = clean(candidate.get("player_href")).split("/")[-1]
        print(f"  [{index:02d}/{len(team_candidates):02d}] {candidate['team']} {candidate['player_display_name']}: {url}")
        try:
            payload, body, status, final_url = fetch_page(url)
            source_hash = sha256_bytes(payload)
            records = parse_player_dead_cap_records(body, url, source_hash)
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            player_page_captures.append(
                {
                    "team_candidate": candidate["team"],
                    "player_display_name": candidate["player_display_name"],
                    "player_slug": slug,
                    "source_url": url,
                    "final_url": final_url,
                    "http_status": status,
                    "fetched_at_utc": fetched_at,
                    "source_sha256": source_hash,
                    "source_byte_count": len(payload),
                    "season_2026_27_present": SEASON_LABEL in strip_tags(body),
                    "dead_cap_record_count": len(records),
                    "snapshot_filename": f"player_snapshots/{slug}_contract.html",
                    "applied_to_frozen_ledger": False,
                }
            )
            player_snapshots[slug] = payload
            for record in records:
                player_page_records.append(
                    {
                        "candidate_team": candidate["team"],
                        "candidate_method": candidate["method"],
                        "candidate_player_display_name": candidate["player_display_name"],
                        "candidate_player_slug": slug,
                        "candidate_dead_cap_amount": candidate["dead_cap_amount"],
                        **record,
                    }
                )
        except Exception as exc:
            fetch_errors.append(
                {
                    "team": candidate["team"],
                    "player_display_name": candidate["player_display_name"],
                    "source_url": url,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )

    if lifecycle_snapshot_missing:
        print("Fetching the five lifecycle pages absent from the retained upstream archive...")
    for index, missing in enumerate(lifecycle_snapshot_missing, start=1):
        slug = clean(missing.get("player_slug"))
        url = f"https://www.salaryswish.com/players/{slug}"
        print(f"  [{index:02d}/{len(lifecycle_snapshot_missing):02d}] {missing['player_name']}: {url}")
        try:
            payload, body, status, final_url = fetch_page(url)
            source_hash = sha256_bytes(payload)
            records = parse_player_dead_cap_records(body, url, source_hash)
            lifecycle_fallback_captures.append(
                {
                    **missing,
                    "source_url": url,
                    "final_url": final_url,
                    "http_status": status,
                    "fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source_sha256": source_hash,
                    "source_byte_count": len(payload),
                    "dead_cap_record_count": len(records),
                    "snapshot_filename": f"lifecycle_fallback_snapshots/{slug}_contract.html",
                }
            )
            lifecycle_fallback_snapshots[slug] = payload
            for record in records:
                lifecycle_snapshot_rows.append(
                    {
                        "player_id": missing["player_id"],
                        "player_name": missing["player_name"],
                        "prior_team": missing["prior_team"],
                        "contract_lifecycle_state": "free_agent_waiver_terminated",
                        "player_slug": slug,
                        "snapshot_member": "",
                        "evidence_origin": "live_fallback_for_missing_contract_snapshot",
                        **record,
                    }
                )
        except Exception as exc:
            lifecycle_fallback_fetch_errors.append(
                {
                    **missing,
                    "source_url": url,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )

    resolved_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    for candidate in team_candidates:
        slug = clean(candidate.get("player_href")).split("/")[-1]
        matches = [
            row for row in player_page_records
            if row["candidate_player_slug"] == slug
            and row["team"] == candidate["team"]
            and clean(row["method"]).lower().rstrip("s") == clean(candidate["method"]).lower().rstrip("s")
            and row["cap_hit"] == candidate["dead_cap_amount"]
        ]
        if len(matches) != 1:
            conflict_rows.append(
                {
                    **candidate,
                    "matching_player_page_record_count": len(matches),
                    "resolution_status": "unresolved_or_conflicting_player_page_match",
                }
            )
            continue
        match = matches[0]
        effective_date = date.fromisoformat(match["effective_date"])
        frozen_eligible = effective_date <= SPLIT_DATE
        resolved_rows.append(
            {
                **candidate,
                "player_page_source_url": match["source_url"],
                "player_page_source_sha256": match["source_sha256"],
                "player_page_team_name": match["team_name"],
                "player_page_method": match["method"],
                "player_page_declared_dead_cap_value": match["declared_dead_cap_value"],
                "dead_cap_effective_date": match["effective_date"],
                "dead_cap_effective_date_text": match["effective_date_text"],
                "date_is_on_or_before_split": frozen_eligible,
                "temporal_classification": (
                    "frozen_snapshot_eligible_positive_candidate"
                    if frozen_eligible
                    else "post_split_dead_cap_excluded_from_opening_snapshot"
                ),
                "frozen_2026_27_dead_cap_amount": candidate["dead_cap_amount"] if frozen_eligible else 0,
                "post_split_excluded_amount": 0 if frozen_eligible else candidate["dead_cap_amount"],
                "player_level_resolution_complete": True,
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            }
        )

    frozen_eligible_rows = [row for row in resolved_rows if row["date_is_on_or_before_split"]]
    post_split_rows = [row for row in resolved_rows if not row["date_is_on_or_before_split"]]
    lifecycle_positive_2026_27_rows: list[dict[str, Any]] = []
    for lifecycle_row in lifecycle_snapshot_rows:
        cap_hit = int(lifecycle_row.get("cap_hit") or 0)
        if cap_hit <= 0:
            continue
        matches = [
            candidate for candidate in team_candidates
            if clean(candidate.get("player_href")).split("/")[-1] == lifecycle_row["player_slug"]
            and candidate["team"] == lifecycle_row["team"]
            and clean(candidate["method"]).lower().rstrip("s") == clean(lifecycle_row["method"]).lower().rstrip("s")
            and candidate["dead_cap_amount"] == cap_hit
        ]
        lifecycle_positive_2026_27_rows.append(
            {
                **lifecycle_row,
                "matching_team_candidate_count": len(matches),
                "matches_exact_team_candidate": len(matches) == 1,
            }
        )
    team_reconciliation_rows: list[dict[str, Any]] = []
    capture_by_team = {clean(row.get("team")): row for row in capture_rows}
    for team in sorted(REQUIRED_TEAMS):
        live_total = int(money_int(capture_by_team[team].get("refetched_live_dead_cap_total")) or 0)
        parsed_total = sum(row["dead_cap_amount"] for row in team_candidates if row["team"] == team)
        frozen_total = sum(row["frozen_2026_27_dead_cap_amount"] for row in resolved_rows if row["team"] == team)
        post_split_total = sum(row["post_split_excluded_amount"] for row in resolved_rows if row["team"] == team)
        team_reconciliation_rows.append(
            {
                "team": team,
                "live_team_dead_cap_total": live_total,
                "parsed_player_candidate_total": parsed_total,
                "frozen_eligible_player_total": frozen_total,
                "post_split_excluded_player_total": post_split_total,
                "unresolved_player_candidate_total": parsed_total - frozen_total - post_split_total,
                "live_total_equals_parsed_candidates": live_total == parsed_total,
                "positive_candidate_count": sum(row["team"] == team for row in team_candidates),
                "frozen_eligible_candidate_count": sum(row["team"] == team for row in frozen_eligible_rows),
                "post_split_candidate_count": sum(row["team"] == team for row in post_split_rows),
                "historical_zero_completeness_proven": False,
                "applied_to_team_salary": False,
            }
        )

    acquisition_checkpoint = check_detail(acquisition_checks, "checkpoint_file_unchanged")
    boundary_checkpoint = check_detail(boundary_checks, "checkpoint_file_unchanged")
    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    add("dead_cap_source_acquisition_passed", bool(acquisition_summary.get("passed")) and not acquisition_summary.get("failed_checks"), acquisition_zip.name)
    add("effective_boundary_freeze_passed", bool(boundary_summary.get("passed")) and not boundary_summary.get("failed_checks"), boundary_zip.name)
    add("contract_option_lifecycle_passed", bool(contract_summary.get("passed")) and not contract_summary.get("failed_strict_checks"), contract_zip.name)
    add("all_upstreams_reference_canonical_checkpoint", acquisition_checkpoint == boundary_checkpoint == EXPECTED_UPSTREAM_CHECKPOINT_SHA256 and contract_summary.get("checkpoint_sha256_after") == EXPECTED_UPSTREAM_CHECKPOINT_SHA256, EXPECTED_UPSTREAM_CHECKPOINT_SHA256)
    add("team_html_parses_exactly_18_player_candidates", len(team_candidates) == 18, f"rows={len(team_candidates)}")
    add("candidate_method_distribution_is_13_waiver_5_buyout", sum(row["method"].lower().startswith("waiver") for row in team_candidates) == 13 and sum(row["method"].lower().startswith("buyout") for row in team_candidates) == 5, "waiver=13, buyout=5")
    add("candidate_rows_reconcile_exact_11_team_live_total", sum(row["dead_cap_amount"] for row in team_candidates) == 95474261 and len({row["team"] for row in team_candidates}) == 11, "$95,474,261")
    add("all_18_player_pages_fetched_without_error", len(player_page_captures) == 18 and not fetch_errors, f"captured={len(player_page_captures)}, errors={len(fetch_errors)}")
    add("all_18_player_page_html_snapshots_retained", len(player_snapshots) == 18, f"snapshots={len(player_snapshots)}")
    add("all_18_player_pages_retain_2026_27_evidence", len(player_page_captures) == 18 and all(row["season_2026_27_present"] for row in player_page_captures), "18/18")
    add("all_18_candidates_match_one_exact_player_page_record", len(resolved_rows) == 18 and not conflict_rows, f"resolved={len(resolved_rows)}, conflicts={len(conflict_rows)}")
    add("all_player_level_effective_dates_are_parseable", len(resolved_rows) == 18 and all(clean(row.get("dead_cap_effective_date")) for row in resolved_rows), "18/18")
    add("frozen_and_post_split_partitions_reconcile_all_18", len(frozen_eligible_rows) + len(post_split_rows) == 18, f"frozen={len(frozen_eligible_rows)}, post_split={len(post_split_rows)}")
    add("frozen_and_post_split_amounts_reconcile_live_total", sum(row["frozen_2026_27_dead_cap_amount"] for row in frozen_eligible_rows) + sum(row["post_split_excluded_amount"] for row in post_split_rows) == 95474261, "exact")
    add("contract_lifecycle_has_exact_34_pre_split_waiver_terminated_rows", len(waiver_lifecycle_rows) == 34, f"rows={len(waiver_lifecycle_rows)}")
    add("upstream_retains_29_of_34_lifecycle_player_snapshots", len(waiver_lifecycle_rows) - len(lifecycle_snapshot_missing) == 29 and len(lifecycle_snapshot_missing) == 5, f"retained={len(waiver_lifecycle_rows) - len(lifecycle_snapshot_missing)}, fallback_required={len(lifecycle_snapshot_missing)}")
    add("all_five_missing_lifecycle_pages_fetched_without_error", len(lifecycle_fallback_captures) == 5 and not lifecycle_fallback_fetch_errors, f"captured={len(lifecycle_fallback_captures)}, errors={len(lifecycle_fallback_fetch_errors)}")
    add("all_34_lifecycle_players_have_snapshot_evidence", len(waiver_lifecycle_rows) - len(lifecycle_snapshot_missing) + len(lifecycle_fallback_captures) == 34, "29 retained + 5 fallback")
    add("all_positive_2026_27_lifecycle_records_match_team_candidates", bool(lifecycle_positive_2026_27_rows) and all(row["matches_exact_team_candidate"] for row in lifecycle_positive_2026_27_rows), f"positive_records={len(lifecycle_positive_2026_27_rows)}")
    add("retained_dante_crosscheck_is_exact", any(row["player_slug"] == "nfaly-dante" and row["team"] == "ATL" and int(row.get("cap_hit") or 0) == 2411090 and row["effective_date"] == "2026-02-05" for row in lifecycle_positive_2026_27_rows), "ATL / 2026-02-05 / $2,411,090")
    add("thirty_team_player_totals_reconcile_live_team_totals", len(team_reconciliation_rows) == 30 and all(row["live_total_equals_parsed_candidates"] for row in team_reconciliation_rows), "30/30")
    add("historical_zero_completeness_not_overclaimed", all(not row["historical_zero_completeness_proven"] for row in team_reconciliation_rows), "30/30 remain explicitly unproven")
    add("no_dead_cap_value_applied_to_team_salary", all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in resolved_rows), "evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_dead_cap_player_resolution_preview_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "team_html_player_candidate_count": len(team_candidates),
        "candidate_method_counts": {
            "waivers": sum(row["method"].lower().startswith("waiver") for row in team_candidates),
            "buyout": sum(row["method"].lower().startswith("buyout") for row in team_candidates),
        },
        "candidate_live_total": sum(row["dead_cap_amount"] for row in team_candidates),
        "player_page_capture_count": len(player_page_captures),
        "player_page_fetch_error_count": len(fetch_errors),
        "player_level_resolved_count": len(resolved_rows),
        "player_level_conflict_count": len(conflict_rows),
        "frozen_eligible_player_count": len(frozen_eligible_rows),
        "frozen_eligible_dead_cap_total": sum(row["frozen_2026_27_dead_cap_amount"] for row in frozen_eligible_rows),
        "post_split_excluded_player_count": len(post_split_rows),
        "post_split_excluded_dead_cap_total": sum(row["post_split_excluded_amount"] for row in post_split_rows),
        "pre_split_waiver_lifecycle_player_count": len(waiver_lifecycle_rows),
        "lifecycle_upstream_snapshot_count": len(waiver_lifecycle_rows) - len(lifecycle_snapshot_missing),
        "lifecycle_fallback_capture_count": len(lifecycle_fallback_captures),
        "lifecycle_fallback_fetch_error_count": len(lifecycle_fallback_fetch_errors),
        "lifecycle_all_dead_cap_record_count": len(lifecycle_snapshot_rows),
        "lifecycle_positive_2026_27_dead_cap_record_count": len(lifecycle_positive_2026_27_rows),
        "lifecycle_positive_2026_27_dead_cap_total": sum(int(row["cap_hit"] or 0) for row in lifecycle_positive_2026_27_rows),
        "historical_zero_completeness_proven": False,
        "dead_cap_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Use the dated player-level partition plus the 34-player waiver-lifecycle scan to build the frozen ledger completeness proof. "
            "Resolve historical-zero coverage and any set-off-sensitive amounts before applying dead cap or computing Team Salary."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_dead_cap_player_resolution_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        player_snapshot_dir = export / "player_snapshots"
        player_snapshot_dir.mkdir(parents=True)
        lifecycle_fallback_snapshot_dir = export / "lifecycle_fallback_snapshots"
        lifecycle_fallback_snapshot_dir.mkdir(parents=True)
        write_csv(export / "team_page_dead_cap_candidates_18.csv", team_candidates)
        write_csv(export / "player_page_capture_18.csv", player_page_captures)
        write_csv(export / "player_page_dead_cap_records.csv", player_page_records)
        write_csv(export / "resolved_player_dead_cap_rows_18.csv", resolved_rows)
        write_csv(export / "frozen_eligible_dead_cap_rows.csv", frozen_eligible_rows)
        write_csv(export / "post_split_excluded_dead_cap_rows.csv", post_split_rows)
        write_csv(export / "player_resolution_conflicts.csv", conflict_rows)
        write_csv(export / "pre_split_waiver_lifecycle_players_34.csv", waiver_lifecycle_rows)
        write_csv(export / "waiver_lifecycle_snapshot_dead_cap_records.csv", lifecycle_snapshot_rows)
        write_csv(export / "waiver_lifecycle_positive_2026_27_dead_cap_records.csv", lifecycle_positive_2026_27_rows)
        write_csv(export / "waiver_lifecycle_snapshot_missing.csv", lifecycle_snapshot_missing)
        write_csv(export / "waiver_lifecycle_fallback_capture_5.csv", lifecycle_fallback_captures)
        write_csv(export / "waiver_lifecycle_fallback_fetch_errors.csv", lifecycle_fallback_fetch_errors)
        write_csv(export / "dead_cap_team_reconciliation_30.csv", team_reconciliation_rows)
        write_csv(export / "dead_cap_player_resolution_checks.csv", checks)
        (export / "dead_cap_player_resolution_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN DEAD-CAP PLAYER RESOLUTION PREVIEW V1
=====================================================

Purpose
-------
Parse the 30 retained team HTML snapshots into exact player-level 2026-27
dead-cap rows, fetch each linked player page, and resolve the charge origin date
against the inclusive April 12, 2026 simulation split.

Coverage
--------
The team pages must reconcile exactly to 18 player rows, 13 waiver charges,
five buyouts, 11 teams, and $95,474,261. The package also scans the 34 players
already classified as waiver-terminated before the split in the contract-option
lifecycle audit. It uses 29 retained player snapshots plus five explicit
read-only fallback captures as an independent coverage crosscheck.

Safety
------
Resolved dates partition candidates into frozen-eligible and post-split-only
evidence. No amount is applied. Historical zero-team completeness remains
explicitly unproven until the next slice.
""",
            encoding="utf-8",
        )
        for slug, payload in player_snapshots.items():
            (player_snapshot_dir / f"{slug}_contract.html").write_bytes(payload)
        for slug, payload in lifecycle_fallback_snapshots.items():
            (lifecycle_fallback_snapshot_dir / f"{slug}_contract.html").write_bytes(payload)
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.rglob("*")):
                if item.is_file():
                    archive.write(item, arcname=f"{export_id}/{item.relative_to(export)}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Dead-Cap Player Resolution Preview V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN DEAD-CAP PLAYER RESOLUTION PREVIEW V1 PASSED")
    print("=" * 132)
    print(f"Team-page candidates:            {len(team_candidates):>3}/18")
    print(f"Player pages captured:           {len(player_page_captures):>3}/18")
    print(f"Exact player rows resolved:      {len(resolved_rows):>3}/18")
    print(f"Frozen-eligible player rows:     {len(frozen_eligible_rows):>3}")
    print(f"Frozen-eligible amount:          ${sum(row['frozen_2026_27_dead_cap_amount'] for row in frozen_eligible_rows):,}")
    print(f"Post-split excluded rows:        {len(post_split_rows):>3}")
    print(f"Post-split excluded amount:      ${sum(row['post_split_excluded_amount'] for row in post_split_rows):,}")
    print("Historical zero completeness:     NOT YET PROVEN")
    print("Dead-cap values applied:          0")
    print("Checkpoint write:                 NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
