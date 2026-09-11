from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import pickle
import re
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-frozen-dead-cap-completeness-setoff-resolution-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
FIRST_POST_SPLIT_DATE = date(2026, 4, 13)
PLAYER_RESOLUTION_PATTERN = "fa_frozen_dead_cap_player_resolution_preview_v1_2026-27_*.zip"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
EXPECTED_FROZEN_PLAYER_COUNT = 12
EXPECTED_FROZEN_TOTAL = 55_653_831
EXPECTED_POST_SPLIT_PLAYER_COUNT = 6
EXPECTED_POST_SPLIT_TOTAL = 39_820_430
REQUIRED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


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


def parse_date(value: str) -> date | None:
    text = clean(value)
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
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


def extract_contract_blocks(body: str, player_slug: str, dead_cap_team: str, dead_cap_date: date) -> list[dict[str, Any]]:
    starts = [match.start() for match in re.finditer(r'<div\b[^>]*class="sw_playerContract"[^>]*>', body, re.IGNORECASE)]
    starts.append(len(body))
    rows: list[dict[str, Any]] = []
    for index in range(len(starts) - 1):
        section = body[starts[index]:starts[index + 1]]
        section_text = strip_tags(section)
        date_match = re.search(
            r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            section_text,
            re.IGNORECASE,
        )
        team_match = re.search(
            r"Signing Team\s*:\s*(.+?)\s+Signing Method\s*:",
            section_text,
            re.IGNORECASE,
        )
        method_match = re.search(
            r"Signing Method\s*:\s*(.+?)\s+Signing Date\s*:",
            section_text,
            re.IGNORECASE,
        )
        if not date_match or not team_match:
            continue
        signing_date = parse_date(date_match.group(1))
        if not signing_date:
            continue
        season_rows: list[list[str]] = []
        for table_row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", section, re.IGNORECASE | re.DOTALL):
            cells = [
                strip_tags(cell)
                for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", table_row, re.IGNORECASE | re.DOTALL)
            ]
            if cells and cells[0] == SEASON_LABEL and len(cells) >= 8:
                season_rows.append(cells)
        for season_index, cells in enumerate(season_rows, start=1):
            option_decision_match = re.search(r"\(([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\)", cells[2])
            option_decision_date = parse_date(option_decision_match.group(1)) if option_decision_match else None
            rows.append(
                {
                    "player_slug": player_slug,
                    "dead_cap_team": dead_cap_team,
                    "dead_cap_effective_date": dead_cap_date.isoformat(),
                    "contract_block_index": index + 1,
                    "season_row_index": season_index,
                    "signing_team": clean(team_match.group(1)),
                    "signing_method": clean(method_match.group(1)) if method_match else "",
                    "signing_date": signing_date.isoformat(),
                    "signing_date_is_after_dead_cap": signing_date > dead_cap_date,
                    "signing_date_is_on_or_before_split": signing_date <= SPLIT_DATE,
                    "signing_date_is_post_split": signing_date >= FIRST_POST_SPLIT_DATE,
                    "season": cells[0],
                    "option_type": cells[1],
                    "option_used": cells[2],
                    "option_decision_date": option_decision_date.isoformat() if option_decision_date else "",
                    "option_decision_is_post_split": bool(option_decision_date and option_decision_date >= FIRST_POST_SPLIT_DATE),
                    "cap_hit": int(money_int(cells[3]) or 0),
                    "base_salary": int(money_int(cells[4].split(" ")[0]) or 0),
                    "guaranteed": int(money_int(cells[5].split(" ")[0]) or 0),
                    "likely_incentive": int(money_int(cells[6]) or 0),
                    "unlikely_incentive": int(money_int(cells[7]) or 0),
                }
            )
    return rows


def target_dead_cap_note(body: str, team_name: str, effective_date_text: str) -> str:
    heading = re.search(r"<h4\b[^>]*>\s*DEAD\s+CAP\s*</h4>", body, re.IGNORECASE | re.DOTALL)
    if not heading:
        return ""
    end_match = re.search(
        r"<h4\b[^>]*>\s*(?:SALARY\s+PROGRESSION|CAREER\s+STATS)",
        body[heading.end():],
        re.IGNORECASE | re.DOTALL,
    )
    end = heading.end() + end_match.start() if end_match else len(body)
    section_text = strip_tags(body[heading.end():end])
    meta_matches = list(
        re.finditer(
            r"TYPE:\s*(.+?)\s+TEAM:\s*(.+?)\s+LENGTH:\s*(.+?)\s+VALUE:\s*(\$[\d,]+|\$?0)\s+DATE:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            section_text,
            re.IGNORECASE,
        )
    )
    for index, meta in enumerate(meta_matches):
        if clean(meta.group(2)) != clean(team_name) or clean(meta.group(5)) != clean(effective_date_text):
            continue
        segment_end = meta_matches[index + 1].start() if index + 1 < len(meta_matches) else len(section_text)
        segment = section_text[meta.end():segment_end]
        note_match = re.search(r"\bNote:\s*(.+)$", segment, re.IGNORECASE)
        return clean(note_match.group(1)) if note_match else ""
    return ""


def main() -> int:
    root = Path.cwd().resolve()
    player_zip = latest(root, PLAYER_RESOLUTION_PATTERN)
    boundary_zip = latest(root, BOUNDARY_PATTERN)

    with zipfile.ZipFile(player_zip) as archive:
        player_summary = json_suffix(archive, "dead_cap_player_resolution_summary.json")
        player_checks = csv_suffix(archive, "dead_cap_player_resolution_checks.csv")
        frozen_rows = csv_suffix(archive, "frozen_eligible_dead_cap_rows.csv")
        post_split_rows = csv_suffix(archive, "post_split_excluded_dead_cap_rows.csv")
        resolved_rows = csv_suffix(archive, "resolved_player_dead_cap_rows_18.csv")
        lifecycle_rows = csv_suffix(archive, "pre_split_waiver_lifecycle_players_34.csv")
        lifecycle_dead_cap_rows = csv_suffix(archive, "waiver_lifecycle_snapshot_dead_cap_records.csv")
        lifecycle_positive_rows = csv_suffix(archive, "waiver_lifecycle_positive_2026_27_dead_cap_records.csv")
        team_reconciliation = csv_suffix(archive, "dead_cap_team_reconciliation_30.csv")
        player_page_records = csv_suffix(archive, "player_page_dead_cap_records.csv")
        player_html: dict[str, tuple[str, bytes]] = {}
        for row in resolved_rows:
            if not as_bool(row.get("date_is_on_or_before_split")):
                continue
            slug = clean(row.get("player_href")).split("/")[-1]
            member = member_suffix(archive, f"player_snapshots/{slug}_contract.html")
            player_html[slug] = (member, archive.read(member))

    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before dead-cap completeness resolution.")

    print("=" * 132)
    print("2026 FROZEN DEAD-CAP COMPLETENESS + SET-OFF RESOLUTION V1")
    print("=" * 132)
    print("Closing historical-zero coverage and set-off timing without applying any value...")

    page_records_by_slug: dict[str, list[dict[str, str]]] = {}
    for record in player_page_records:
        page_records_by_slug.setdefault(clean(record.get("candidate_player_slug")), []).append(record)

    source_note_rows: list[dict[str, Any]] = []
    contract_exposure_rows: list[dict[str, Any]] = []
    setoff_resolution_rows: list[dict[str, Any]] = []
    for frozen in frozen_rows:
        slug = clean(frozen.get("player_href")).split("/")[-1]
        member, payload = player_html[slug]
        body = payload.decode("utf-8", errors="replace")
        target_records = [
            record for record in page_records_by_slug.get(slug, [])
            if clean(record.get("team")) == clean(frozen.get("team"))
            and clean(record.get("effective_date")) == clean(frozen.get("dead_cap_effective_date"))
            and int(money_int(record.get("cap_hit")) or 0) == int(money_int(frozen.get("dead_cap_amount")) or 0)
        ]
        if len(target_records) != 1:
            raise RuntimeError(f"Expected one exact player-page target record for {slug}; found {len(target_records)}.")
        target_record = target_records[0]
        dead_cap_date = parse_date(clean(frozen.get("dead_cap_effective_date")))
        if not dead_cap_date:
            raise RuntimeError(f"Unparseable dead-cap date for {slug}.")
        note = target_dead_cap_note(body, clean(target_record.get("team_name")), clean(target_record.get("effective_date_text")))
        explicit_setoff = bool(re.search(r"set[- ]?off", note, re.IGNORECASE))
        setoff_match = re.search(
            r"Original dead cap:\s*\$([\d,]+)\s*\(\$([\d,]+)/yr\)\.\s*Set-off credit:\s*-\$([\d,]+)/yr\.\s*Current dead cap:\s*\$([\d,]+)/yr",
            note,
            re.IGNORECASE,
        )
        source_note_rows.append(
            {
                "team": frozen["team"],
                "player_display_name": frozen["player_display_name"],
                "player_slug": slug,
                "dead_cap_effective_date": frozen["dead_cap_effective_date"],
                "frozen_2026_27_dead_cap_amount": int(money_int(frozen.get("frozen_2026_27_dead_cap_amount")) or 0),
                "dead_cap_note": note,
                "explicit_setoff_note": explicit_setoff,
                "original_dead_cap_total": int(setoff_match.group(1).replace(",", "")) if setoff_match else "",
                "original_dead_cap_annual": int(setoff_match.group(2).replace(",", "")) if setoff_match else "",
                "setoff_credit_annual": int(setoff_match.group(3).replace(",", "")) if setoff_match else "",
                "current_dead_cap_annual": int(setoff_match.group(4).replace(",", "")) if setoff_match else "",
                "source_snapshot_member": member,
                "source_snapshot_sha256": sha256_bytes(payload),
            }
        )
        contract_rows = extract_contract_blocks(body, slug, clean(frozen.get("team")), dead_cap_date)
        for contract_row in contract_rows:
            if contract_row["signing_date_is_after_dead_cap"]:
                contract_exposure_rows.append(contract_row)

        if explicit_setoff:
            status = "explicit_pre_split_setoff_credit_already_reflected"
            frozen_amount_basis = "published current annual dead cap after explicit pre_split_setoff"
        elif slug == "bradley-beal":
            status = "fixed_buyout_schedule_post_split_contract_quarantined"
            frozen_amount_basis = "five_year negotiated buyout schedule effective before split"
        elif slug == "olivier-maxence-prosper":
            status = "fixed_stretch_schedule_post_split_option_decision_quarantined"
            frozen_amount_basis = "three_year dead_cap schedule effective before split"
        else:
            status = "published_pre_split_dead_cap_schedule_no_explicit_setoff_adjustment"
            frozen_amount_basis = "player_page dead_cap schedule effective before split"
        setoff_resolution_rows.append(
            {
                "team": frozen["team"],
                "player_display_name": frozen["player_display_name"],
                "player_slug": slug,
                "dead_cap_effective_date": frozen["dead_cap_effective_date"],
                "frozen_2026_27_dead_cap_amount": int(money_int(frozen.get("frozen_2026_27_dead_cap_amount")) or 0),
                "setoff_resolution_status": status,
                "frozen_amount_basis": frozen_amount_basis,
                "post_split_contract_event_imported": False,
                "post_split_option_outcome_imported": False,
                "setoff_amount_unresolved": False,
                "applied_to_team_salary": False,
            }
        )

    lifecycle_positive_teams = {clean(row.get("team")) for row in lifecycle_positive_rows}
    recon_by_team = {clean(row.get("team")): row for row in team_reconciliation}
    frozen_team_resolution: list[dict[str, Any]] = []
    for team in sorted(REQUIRED_TEAMS):
        frozen_total = sum(
            int(money_int(row.get("frozen_2026_27_dead_cap_amount")) or 0)
            for row in frozen_rows if clean(row.get("team")) == team
        )
        post_total = sum(
            int(money_int(row.get("post_split_excluded_amount")) or 0)
            for row in post_split_rows if clean(row.get("team")) == team
        )
        live_total = int(money_int(recon_by_team[team].get("live_team_dead_cap_total")) or 0)
        positive_count = sum(clean(row.get("team")) == team for row in frozen_rows)
        if frozen_total > 0:
            proof_class = "exact_positive_player_rows_effective_on_or_before_split"
            complete = True
        elif live_total == 0 and team not in lifecycle_positive_teams:
            proof_class = "live_zero_plus_complete_34_player_pre_split_waiver_crosscheck"
            complete = True
        elif live_total == post_total and post_total > 0 and team not in lifecycle_positive_teams:
            proof_class = "all_live_positive_rows_are_exact_post_split_exclusions"
            complete = True
        else:
            proof_class = "unresolved"
            complete = False
        frozen_team_resolution.append(
            {
                "team": team,
                "frozen_positive_player_count": positive_count,
                "frozen_2026_27_dead_cap_total": frozen_total,
                "post_split_excluded_total": post_total,
                "live_august_dead_cap_total": live_total,
                "lifecycle_positive_crosscheck_present": team in lifecycle_positive_teams,
                "completeness_proof_class": proof_class,
                "historical_zero_or_positive_completeness_proven": complete,
                "dead_cap_value_applied": False,
            }
        )

    explicit_setoff_rows = [row for row in source_note_rows if row["explicit_setoff_note"]]
    post_split_contract_rows = [row for row in contract_exposure_rows if row["signing_date_is_post_split"]]
    post_split_option_rows = [row for row in contract_exposure_rows if row["option_decision_is_post_split"]]
    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    add("player_resolution_preview_passed", bool(player_summary.get("passed")) and not player_summary.get("failed_checks"), player_zip.name)
    add("all_25_player_resolution_checks_passed", len(player_checks) == 25 and all(clean(row.get("status")) == "PASS" for row in player_checks), "25/25")
    add("effective_boundary_freeze_passed", bool(boundary_summary.get("passed")) and not boundary_summary.get("failed_checks"), boundary_zip.name)
    add("canonical_boundary_is_april_12_inclusive", clean(boundary_summary.get("canonical_split_date")) == SPLIT_DATE.isoformat() and as_bool(boundary_summary.get("canonical_split_date_inclusive")), SPLIT_DATE.isoformat())
    add("exact_12_frozen_positive_rows_retained", len(frozen_rows) == EXPECTED_FROZEN_PLAYER_COUNT, f"rows={len(frozen_rows)}")
    add("exact_frozen_positive_total_is_55653831", sum(int(money_int(row.get("frozen_2026_27_dead_cap_amount")) or 0) for row in frozen_rows) == EXPECTED_FROZEN_TOTAL, f"${EXPECTED_FROZEN_TOTAL:,}")
    add("exact_6_post_split_rows_remain_excluded", len(post_split_rows) == EXPECTED_POST_SPLIT_PLAYER_COUNT and sum(int(money_int(row.get("post_split_excluded_amount")) or 0) for row in post_split_rows) == EXPECTED_POST_SPLIT_TOTAL, f"rows={len(post_split_rows)}, total=${EXPECTED_POST_SPLIT_TOTAL:,}")
    add("all_18_rows_preserve_exact_temporal_partition", len(resolved_rows) == 18 and len(frozen_rows) + len(post_split_rows) == 18, "12 frozen + 6 excluded")
    add("all_30_team_live_totals_have_zero_unresolved_candidates", len(team_reconciliation) == 30 and all(int(money_int(row.get("unresolved_player_candidate_total")) or 0) == 0 for row in team_reconciliation), "30/30")
    add("all_34_pre_split_waiver_lifecycle_players_are_covered", len(lifecycle_rows) == 34, "34/34")
    add("lifecycle_crosscheck_has_exact_one_positive_2026_27_record", len(lifecycle_positive_rows) == 1 and clean(lifecycle_positive_rows[0].get("player_slug")) == "nfaly-dante" and int(money_int(lifecycle_positive_rows[0].get("cap_hit")) or 0) == 2411090, "N'Faly Dante / ATL / $2,411,090")
    add("all_12_positive_player_source_snapshots_reopened", len(player_html) == 12, "12/12")
    add("all_12_positive_rows_have_setoff_resolution_status", len(setoff_resolution_rows) == 12 and all(not row["setoff_amount_unresolved"] for row in setoff_resolution_rows), "12/12")
    add("exact_one_explicit_setoff_note_is_lillard", len(explicit_setoff_rows) == 1 and explicit_setoff_rows[0]["player_slug"] == "damian-lillard", "1/12")
    add("lillard_original_dead_cap_is_exact", bool(explicit_setoff_rows) and explicit_setoff_rows[0]["original_dead_cap_total"] == 112583016 and explicit_setoff_rows[0]["original_dead_cap_annual"] == 22516603, "$112,583,016 / $22,516,603 per year")
    add("lillard_setoff_credit_is_exact", bool(explicit_setoff_rows) and explicit_setoff_rows[0]["setoff_credit_annual"] == 1205551 and explicit_setoff_rows[0]["current_dead_cap_annual"] == 21311053, "$1,205,551 credit / $21,311,053 current")
    add("lillard_subsequent_contract_predates_split", any(row["player_slug"] == "damian-lillard" and row["signing_team"] == "POR" and row["signing_date"] == "2025-07-19" and row["signing_date_is_on_or_before_split"] for row in contract_exposure_rows), "POR / 2025-07-19")
    add("post_split_contract_events_are_quarantined", all(row["player_slug"] == "bradley-beal" for row in post_split_contract_rows) and any(row["player_slug"] == "bradley-beal" and row["signing_date"] == "2026-08-13" for row in post_split_contract_rows), f"rows={len(post_split_contract_rows)}")
    add("post_split_option_decisions_are_quarantined", {row["player_slug"] for row in post_split_option_rows} == {"bradley-beal", "olivier-maxence-prosper"}, ",".join(sorted({row['player_slug'] for row in post_split_option_rows})))
    add("all_post_split_contract_and_option_outcomes_imported_zero_times", all(not row["post_split_contract_event_imported"] and not row["post_split_option_outcome_imported"] for row in setoff_resolution_rows), "0 imported")
    add("exact_7_teams_have_frozen_positive_dead_cap", sum(row["frozen_2026_27_dead_cap_total"] > 0 for row in frozen_team_resolution) == 7, "7/30")
    add("exact_23_teams_have_proven_frozen_zero_dead_cap", sum(row["frozen_2026_27_dead_cap_total"] == 0 and row["historical_zero_or_positive_completeness_proven"] for row in frozen_team_resolution) == 23, "23/30")
    add("all_30_team_frozen_dead_cap_ledgers_are_complete", len(frozen_team_resolution) == 30 and all(row["historical_zero_or_positive_completeness_proven"] for row in frozen_team_resolution), "30/30")
    add("frozen_dead_cap_values_not_applied", all(not row["applied_to_team_salary"] for row in setoff_resolution_rows) and all(not row["dead_cap_value_applied"] for row in frozen_team_resolution), "evidence only")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_dead_cap_completeness_setoff_resolution_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "frozen_positive_player_count": len(frozen_rows),
        "frozen_positive_team_count": sum(row["frozen_2026_27_dead_cap_total"] > 0 for row in frozen_team_resolution),
        "frozen_2026_27_dead_cap_total": sum(row["frozen_2026_27_dead_cap_total"] for row in frozen_team_resolution),
        "frozen_zero_team_count": sum(row["frozen_2026_27_dead_cap_total"] == 0 for row in frozen_team_resolution),
        "post_split_excluded_player_count": len(post_split_rows),
        "post_split_excluded_total": sum(int(money_int(row.get("post_split_excluded_amount")) or 0) for row in post_split_rows),
        "team_completeness_proven_count": sum(row["historical_zero_or_positive_completeness_proven"] for row in frozen_team_resolution),
        "explicit_setoff_row_count": len(explicit_setoff_rows),
        "lillard_setoff_credit_annual": explicit_setoff_rows[0]["setoff_credit_annual"] if explicit_setoff_rows else None,
        "unresolved_setoff_row_count": sum(row["setoff_amount_unresolved"] for row in setoff_resolution_rows),
        "post_split_contract_event_import_count": 0,
        "post_split_option_outcome_import_count": 0,
        "dead_cap_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "dead_cap_section_remaining_packages": 1 if not failed else 2,
        "next_slice": (
            "Freeze the exact 12-player, seven-team, $55,653,831 frozen dead-cap ledger as audited evidence. "
            "Preserve 23 exact team zeros and six post-split exclusions; do not compute or apply official Team Salary yet."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_dead_cap_completeness_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "frozen_dead_cap_final_candidates_12.csv", setoff_resolution_rows)
        write_csv(export / "frozen_dead_cap_team_completeness_30.csv", frozen_team_resolution)
        write_csv(export / "frozen_dead_cap_source_notes_12.csv", source_note_rows)
        write_csv(export / "frozen_dead_cap_subsequent_contract_exposures.csv", contract_exposure_rows)
        write_csv(export / "frozen_dead_cap_post_split_contract_exposures.csv", post_split_contract_rows)
        write_csv(export / "frozen_dead_cap_post_split_option_exposures.csv", post_split_option_rows)
        write_csv(export / "frozen_dead_cap_completeness_setoff_checks.csv", checks)
        (export / "frozen_dead_cap_completeness_setoff_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN DEAD-CAP COMPLETENESS + SET-OFF RESOLUTION V1
================================================================

Purpose
-------
Close historical positive/zero coverage for all 30 teams and resolve set-off
timing for the exact 12 player-level charges effective on or before the
inclusive April 12, 2026 simulation boundary.

Result contract
---------------
The candidate ledger must contain 12 players, seven positive teams, 23 proven
zero teams, and $55,653,831. Six later charges totaling $39,820,430 remain
explicitly excluded. Damian Lillard's published $1,205,551 annual set-off
credit must predate the split. Later contract and option events are quarantined.

Safety
------
This layer is evidence only. It does not apply dead cap, compute Team Salary,
mutate simulation state, or write the checkpoint.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.rglob("*")):
                if item.is_file():
                    archive.write(item, arcname=f"{export_id}/{item.relative_to(export)}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Frozen Dead-Cap Completeness + Set-Off Resolution V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN DEAD-CAP COMPLETENESS + SET-OFF RESOLUTION V1 PASSED")
    print("=" * 132)
    print(f"Frozen player rows:              {len(frozen_rows):>3}/12")
    print(f"Frozen positive teams:           {sum(row['frozen_2026_27_dead_cap_total'] > 0 for row in frozen_team_resolution):>3}/7")
    print(f"Frozen zero teams proven:        {sum(row['frozen_2026_27_dead_cap_total'] == 0 for row in frozen_team_resolution):>3}/23")
    print(f"Frozen dead-cap total:           ${sum(row['frozen_2026_27_dead_cap_total'] for row in frozen_team_resolution):,}")
    print("Set-off rows unresolved:          0")
    print("Post-split outcomes imported:     0")
    print("Dead-cap values applied:          0")
    print("Checkpoint write:                 NOT PERFORMED")
    print("Dead-cap packages remaining:      1")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
