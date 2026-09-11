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
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


VERSION = "fa-frozen-dead-cap-source-acquisition-v1-2026-08-15"
SEASON_LABEL = "2026-27"
CANONICAL_SPLIT_DATE = "2026-04-12"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
HOTFIX_PATTERN = "fa_salaryswish_team_component_semantic_hotfix_v1_0_1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_UPSTREAM_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
REQUIRED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}
TEAM_NAMES = {
    "ATL": "ATLANTA HAWKS", "BKN": "BROOKLYN NETS", "BOS": "BOSTON CELTICS",
    "CHA": "CHARLOTTE HORNETS", "CHI": "CHICAGO BULLS", "CLE": "CLEVELAND CAVALIERS",
    "DAL": "DALLAS MAVERICKS", "DEN": "DENVER NUGGETS", "DET": "DETROIT PISTONS",
    "GSW": "GOLDEN STATE WARRIORS", "HOU": "HOUSTON ROCKETS", "IND": "INDIANA PACERS",
    "LAC": "LA CLIPPERS", "LAL": "LOS ANGELES LAKERS", "MEM": "MEMPHIS GRIZZLIES",
    "MIA": "MIAMI HEAT", "MIL": "MILWAUKEE BUCKS", "MIN": "MINNESOTA TIMBERWOLVES",
    "NOP": "NEW ORLEANS PELICANS", "NYK": "NEW YORK KNICKS", "OKC": "OKLAHOMA CITY THUNDER",
    "ORL": "ORLANDO MAGIC", "PHI": "PHILADELPHIA 76ERS", "PHX": "PHOENIX SUNS",
    "POR": "PORTLAND TRAIL BLAZERS", "SAC": "SACRAMENTO KINGS", "SAS": "SAN ANTONIO SPURS",
    "TOR": "TORONTO RAPTORS", "UTA": "UTAH JAZZ", "WAS": "WASHINGTON WIZARDS",
}


class EvidenceTextParser(HTMLParser):
    BLOCK_TAGS = {
        "br", "p", "div", "tr", "td", "th", "li", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS:
            self.skip_depth += 1
        elif lowered in self.BLOCK_TAGS and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif lowered in self.BLOCK_TAGS and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def line_text(self) -> str:
        lines = [normalize_text(line) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)

    def flat_text(self) -> str:
        return normalize_text(" ".join(self.parts))


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def as_int(value: Any) -> int | None:
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


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


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


def extract_label_amount(text: str, label: str) -> int | None:
    label_pattern = re.escape(label).replace(r"\ ", r"\s+")
    pattern = re.compile(
        rf"(?<![A-Z]){label_pattern}\s*(?::\s*)?(\-?\$[\d,]+|\$?0|[-–—])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 16):match.start()].upper()
        if label.upper() == "CAP HIT" and (prefix.endswith("ROSTER ") or prefix.endswith("DEAD ")):
            continue
        return as_int(match.group(1))
    return None


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


def dead_cap_contexts(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(re.finditer(r"DEAD\s+CAP", text, re.IGNORECASE), start=1):
        start = max(0, match.start() - 500)
        end = min(len(text), match.end() + 1800)
        context = text[start:end]
        rows.append(
            {
                "context_index": index,
                "match_offset": match.start(),
                "context_start": start,
                "context_end": end,
                "context_text": context,
            }
        )
    return rows


def money_tokens(context: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    money_pattern = r"\-?\$[\d,]+|(?<![\d$])\$?0(?!\d)|(?<![\w$])[-–—](?!\w)"
    for index, match in enumerate(re.finditer(money_pattern, context), start=1):
        amount = as_int(match.group(0))
        rows.append(
            {
                "token_index": index,
                "raw_money_token": match.group(0),
                "numeric_amount": amount,
                "left_context": normalize_text(context[max(0, match.start() - 180):match.start()]),
                "right_context": normalize_text(context[match.end():min(len(context), match.end() + 180)]),
            }
        )
    return rows


def main() -> int:
    root = Path.cwd().resolve()
    boundary_zip = latest(root, BOUNDARY_PATTERN)
    hotfix_zip = latest(root, HOTFIX_PATTERN)
    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")
    with zipfile.ZipFile(hotfix_zip) as archive:
        hotfix_summary = json_suffix(archive, "semantic_hotfix_summary.json")
        hotfix_checks = csv_suffix(archive, "semantic_hotfix_checks.csv")
        upstream_dead_rows = csv_suffix(archive, "dead_cap_team_evidence_30.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before frozen dead-cap source acquisition.")

    upstream_by_team: dict[str, dict[str, str]] = {}
    for row in upstream_dead_rows:
        team = clean(row.get("team")).upper()
        if team in upstream_by_team:
            raise RuntimeError(f"Duplicate upstream dead-cap row: {team}")
        upstream_by_team[team] = row

    capture_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    money_rows: list[dict[str, Any]] = []
    change_rows: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []
    html_snapshots: dict[str, bytes] = {}

    print("=" * 132)
    print("2026 FROZEN DEAD-CAP SOURCE ACQUISITION V1")
    print("=" * 132)
    print("Capturing raw 30-team dead-cap source evidence without applying values...")
    for index, team in enumerate(sorted(REQUIRED_TEAMS), start=1):
        upstream = upstream_by_team.get(team, {})
        url = clean(upstream.get("source_url"))
        prior_total = as_int(upstream.get("dead_cap_hit_2026_27"))
        print(f"  [{index:02d}/30] {team}: {url or 'MISSING URL'}")
        try:
            if not url.startswith("https://www.salaryswish.com/teams/"):
                raise RuntimeError("Missing or unexpected SalarySwish team URL.")
            payload, body, status, final_url = fetch_page(url)
            parser = EvidenceTextParser()
            parser.feed(body)
            flat_text = parser.flat_text()
            line_text = parser.line_text()
            current_total = extract_label_amount(flat_text, "DEAD CAP HIT")
            contexts = dead_cap_contexts(flat_text)
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            source_hash = sha256_bytes(payload)
            capture_rows.append(
                {
                    "team": team,
                    "team_name": TEAM_NAMES[team].title(),
                    "source_url": url,
                    "final_url": final_url,
                    "http_status": status,
                    "fetched_at_utc": fetched_at,
                    "source_sha256": source_hash,
                    "source_byte_count": len(payload),
                    "team_identity_verified": TEAM_NAMES[team] in flat_text.upper(),
                    "season_2026_27_present": SEASON_LABEL in flat_text,
                    "upstream_live_dead_cap_total": prior_total,
                    "refetched_live_dead_cap_total": current_total,
                    "refetched_minus_upstream_total": (
                        current_total - prior_total
                        if current_total is not None and prior_total is not None
                        else ""
                    ),
                    "source_hash_matches_upstream_capture": source_hash == clean(upstream.get("source_sha256")),
                    "dead_cap_context_count": len(contexts),
                    "line_text_character_count": len(line_text),
                    "snapshot_filename": f"snapshots/{team.lower()}_team_salary.html",
                    "temporal_status": "post_split_candidate_discovery_only",
                    "applied_to_team_salary": False,
                    "state_mutation_applied": False,
                }
            )
            html_snapshots[team] = payload
            for context in contexts:
                context_row = {
                    "team": team,
                    "source_url": url,
                    "fetched_at_utc": fetched_at,
                    "source_sha256": source_hash,
                    **context,
                    "candidate_only_not_temporally_resolved": True,
                }
                context_rows.append(context_row)
                for token in money_tokens(context["context_text"]):
                    money_rows.append(
                        {
                            "team": team,
                            "context_index": context["context_index"],
                            **token,
                            "equals_refetched_team_dead_cap_total": (
                                token["numeric_amount"] is not None
                                and current_total is not None
                                and token["numeric_amount"] == current_total
                            ),
                            "candidate_only_not_player_level_verified": True,
                            "source_url": url,
                            "source_sha256": source_hash,
                        }
                    )
            if current_total != prior_total or source_hash != clean(upstream.get("source_sha256")):
                change_rows.append(
                    {
                        "team": team,
                        "upstream_total": prior_total,
                        "refetched_total": current_total,
                        "total_changed": current_total != prior_total,
                        "source_hash_changed": source_hash != clean(upstream.get("source_sha256")),
                        "upstream_fetched_at_utc": clean(upstream.get("fetched_at_utc")),
                        "refetched_at_utc": fetched_at,
                        "interpretation": "source_refresh_difference_not_frozen_snapshot_evidence",
                    }
                )
        except Exception as exc:
            fetch_errors.append(
                {
                    "team": team,
                    "source_url": url,
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )

    capture_rows.sort(key=lambda row: row["team"])
    positive_priority_rows = []
    for team in sorted(REQUIRED_TEAMS):
        upstream = upstream_by_team[team]
        upstream_total = int(as_int(upstream.get("dead_cap_hit_2026_27")) or 0)
        if upstream_total <= 0:
            continue
        capture = next((row for row in capture_rows if row["team"] == team), {})
        positive_priority_rows.append(
            {
                "priority": 0,
                "team": team,
                "upstream_live_dead_cap_total": upstream_total,
                "refetched_live_dead_cap_total": capture.get("refetched_live_dead_cap_total", ""),
                "dead_cap_context_count": capture.get("dead_cap_context_count", 0),
                "money_token_count": sum(row["team"] == team for row in money_rows),
                "required_resolution": "identify_player_charge_amount_origin_and_effective_date_then_test_against_2026_04_12",
                "direct_application_allowed": False,
            }
        )
    positive_priority_rows.sort(key=lambda row: (-int(row["upstream_live_dead_cap_total"]), row["team"]))
    for index, row in enumerate(positive_priority_rows, start=1):
        row["priority"] = index

    boundary_checkpoint = next(
        (
            clean(row.get("detail"))
            for row in boundary_checks
            if clean(row.get("check_id")) == "checkpoint_file_unchanged" and clean(row.get("status")) == "PASS"
        ),
        "",
    )
    hotfix_checkpoint = next(
        (
            clean(row.get("detail"))
            for row in hotfix_checks
            if clean(row.get("check_id")) == "checkpoint_file_unchanged" and clean(row.get("status")) == "PASS"
        ),
        "",
    )

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

    add("effective_boundary_freeze_passed", bool(boundary_summary.get("passed")) and not boundary_summary.get("failed_checks"), boundary_zip.name)
    add("salaryswish_semantic_hotfix_passed", bool(hotfix_summary.get("passed")) and not hotfix_summary.get("failed_checks"), hotfix_zip.name)
    add("canonical_split_date_is_2026_04_12", clean(boundary_summary.get("canonical_split_date")) == CANONICAL_SPLIT_DATE and bool(boundary_summary.get("canonical_split_date_inclusive")), CANONICAL_SPLIT_DATE)
    add("both_upstreams_reference_canonical_checkpoint", boundary_checkpoint == hotfix_checkpoint == EXPECTED_UPSTREAM_CHECKPOINT_SHA256, EXPECTED_UPSTREAM_CHECKPOINT_SHA256)
    add("upstream_dead_cap_registry_is_exactly_30_unique_teams", set(upstream_by_team) == REQUIRED_TEAMS and len(upstream_dead_rows) == 30, f"rows={len(upstream_dead_rows)}")
    add("upstream_positive_queue_is_exactly_11_teams", len(positive_priority_rows) == 11, f"teams={len(positive_priority_rows)}")
    add("upstream_live_dead_cap_total_is_preserved", sum(int(as_int(row.get("dead_cap_hit_2026_27")) or 0) for row in upstream_dead_rows) == 95474261, "$95,474,261")
    add("all_30_team_pages_refetched_without_error", len(capture_rows) == 30 and not fetch_errors, f"captured={len(capture_rows)}, errors={len(fetch_errors)}")
    add("all_30_source_html_snapshots_retained", len(html_snapshots) == 30, f"snapshots={len(html_snapshots)}")
    add("all_30_team_and_season_identities_verified", len(capture_rows) == 30 and all(row["team_identity_verified"] and row["season_2026_27_present"] for row in capture_rows), "30/30")
    add("all_30_refetched_dead_cap_totals_extractable", len(capture_rows) == 30 and all(row["refetched_live_dead_cap_total"] is not None for row in capture_rows), "30/30")
    add("dead_cap_context_captured_for_every_team", {row["team"] for row in context_rows} == REQUIRED_TEAMS, f"contexts={len(context_rows)}")
    add("every_positive_priority_team_has_money_context", all(any(row["team"] == item["team"] for row in money_rows) for item in positive_priority_rows), f"tokens={len(money_rows)}")
    add("all_source_changes_are_quarantined_as_refresh_differences", all(row["interpretation"] == "source_refresh_difference_not_frozen_snapshot_evidence" for row in change_rows), f"changed_rows={len(change_rows)}")
    add("no_dead_cap_candidate_promoted_to_frozen_ledger", all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in capture_rows), "candidate evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_dead_cap_source_acquisition_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": CANONICAL_SPLIT_DATE,
        "team_page_capture_count": len(capture_rows),
        "source_fetch_error_count": len(fetch_errors),
        "html_snapshot_count": len(html_snapshots),
        "upstream_positive_dead_cap_team_count": len(positive_priority_rows),
        "upstream_live_dead_cap_total": sum(int(as_int(row.get("dead_cap_hit_2026_27")) or 0) for row in upstream_dead_rows),
        "refetched_live_dead_cap_total": sum(int(row["refetched_live_dead_cap_total"] or 0) for row in capture_rows),
        "dead_cap_context_row_count": len(context_rows),
        "candidate_money_token_count": len(money_rows),
        "source_refresh_difference_count": len(change_rows),
        "frozen_player_level_dead_cap_rows_resolved": 0,
        "dead_cap_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Parse the retained 30-page HTML snapshots into player-level dead-cap candidates, then crosswalk each candidate to dated waiver/stretch/retained-salary evidence. "
            "Only charges effective on or before 2026-04-12 and valid for 2026-27 may enter the frozen ledger."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_frozen_dead_cap_source_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        snapshot_dir = export / "snapshots"
        snapshot_dir.mkdir(parents=True)
        write_csv(export / "dead_cap_source_capture_30.csv", capture_rows)
        write_csv(export / "positive_dead_cap_team_priority_queue_11.csv", positive_priority_rows)
        write_csv(export / "dead_cap_visible_contexts.csv", context_rows)
        write_csv(export / "dead_cap_context_money_tokens.csv", money_rows)
        write_csv(export / "source_refresh_differences.csv", change_rows)
        write_csv(export / "source_fetch_errors.csv", fetch_errors)
        write_csv(export / "frozen_dead_cap_source_acquisition_checks.csv", checks)
        (export / "frozen_dead_cap_source_acquisition_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN DEAD-CAP SOURCE ACQUISITION V1
================================================

Purpose
-------
Acquire the raw player-level source material needed to reconstruct the frozen
2026-27 dead-cap and waiver ledger. All 30 project-linked SalarySwish team
pages are refetched and retained as HTML snapshots. Dead-cap text contexts and
money tokens are exported for deterministic follow-up parsing.

Temporal rule
-------------
These pages are post-split sources. Their values are candidate-discovery and
comparison evidence only. A charge may enter the frozen ledger only after its
player, amount, origin, and effective date are verified against the inclusive
April 12, 2026 boundary.

Safety
------
No dead-cap value, salary, cap hold, rights decision, roster, simulation,
overlay, or checkpoint mutation occurs.
""",
            encoding="utf-8",
        )
        for team, payload in html_snapshots.items():
            (snapshot_dir / f"{team.lower()}_team_salary.html").write_bytes(payload)
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.rglob("*")):
                if item.is_file():
                    archive.write(item, arcname=f"{export_id}/{item.relative_to(export)}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Dead-Cap Source Acquisition V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN DEAD-CAP SOURCE ACQUISITION V1 PASSED")
    print("=" * 132)
    print(f"Team pages captured:              {len(capture_rows):>3}/30")
    print(f"HTML snapshots retained:          {len(html_snapshots):>3}/30")
    print(f"Positive-team priority queue:     {len(positive_priority_rows):>3}")
    print(f"Dead-cap context rows:            {len(context_rows):>3}")
    print(f"Candidate money tokens:           {len(money_rows):>3}")
    print("Frozen player rows resolved:        0")
    print("Dead-cap values applied:             0")
    print("Checkpoint write:        NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
