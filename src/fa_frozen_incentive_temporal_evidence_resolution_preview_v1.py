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
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-frozen-incentive-temporal-evidence-resolution-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
UPSTREAM_PATTERN = "fa_frozen_incentive_source_acquisition_hotfix_v1_0_3_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
EXPECTED_UPSTREAM_RESOLVED = 320
EXPECTED_UPSTREAM_UNRESOLVED = 11
EXPECTED_TARGET_IDS = {
    "203114", "203468", "204001", "1628380", "1628381", "1629057",
    "1630604", "1631117", "1631127", "1631131", "1631132",
}
TEXT_SUFFIXES = {".csv", ".json", ".txt", ".md", ".html", ".htm"}
MAX_ARCHIVES = 250
MAX_ARCHIVE_MEMBER_BYTES = 3_000_000
MAX_TOTAL_SCAN_BYTES = 300_000_000
MAX_PLAIN_FILE_BYTES = 8_000_000


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    return isinstance(value, bool) and value or clean(value).lower() in {"true", "1", "yes", "y"}


def key_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def normalize_name(value: Any) -> str:
    text = html.unescape(clean(value)).casefold()
    text = text.replace("ņ", "n").replace("ģ", "g").replace("š", "s").replace("ž", "z")
    return re.sub(r"[^a-z0-9]+", "", text)


def money_or_none(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"\([^)]*→[^)]*\)", "", text)
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    if negative:
        number = -abs(number)
    return int(round(number))


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one ZIP member ending with {suffix}; found {len(matches)}")
    return matches[0]


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = []
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


def latest_upstream(root: Path) -> Path:
    candidates = [
        path for path in root.rglob(UPSTREAM_PATTERN)
        if path.is_file() and ".fa" not in str(path.parent).lower()
    ]
    if not candidates:
        raise RuntimeError(f"Missing required passed V1.0.3 audit: {UPSTREAM_PATTERN}")
    valid: list[Path] = []
    for path in candidates:
        try:
            with zipfile.ZipFile(path) as archive:
                summary = json_suffix(archive, "frozen_incentive_source_acquisition_hotfix_v1_0_3_summary.json")
                if summary.get("passed") is True:
                    valid.append(path)
        except Exception:
            continue
    if not valid:
        raise RuntimeError("No structurally valid passed V1.0.3 audit was found.")
    return max(valid, key=lambda path: path.stat().st_mtime)


def target_match(row: dict[str, Any], text: str, target: dict[str, Any]) -> bool:
    player_id = clean(target.get("player_id"))
    player_name = clean(target.get("player_name"))
    row_ids = [clean(value) for key, value in row.items() if key_name(key) in {"player_id", "nba_player_id", "person_id"}]
    if player_id in row_ids:
        return True
    normalized = normalize_name(player_name)
    row_names = [normalize_name(value) for key, value in row.items() if key_name(key) in {"player", "player_name", "name", "full_name"}]
    if normalized and normalized in row_names:
        return True
    return bool(re.search(rf"(?<!\d){re.escape(player_id)}(?!\d)", text) or normalized in normalize_name(text))


def first_value(row: dict[str, Any], accepted: set[str], contains: tuple[str, ...] = ()) -> tuple[str, Any]:
    for key, value in row.items():
        normalized = key_name(key)
        if normalized in accepted or any(part in normalized for part in contains):
            return key, value
    return "", ""


def incentive_value(row: dict[str, Any], unlikely: bool) -> tuple[str, Any]:
    for key, value in row.items():
        normalized = key_name(key)
        is_unlikely = normalized.startswith("un") or "unlikely" in normalized
        is_incentive = "incentive" in normalized or "inctv" in normalized
        if is_incentive and is_unlikely == unlikely:
            return key, value
    return "", ""


def row_candidate(
    target: dict[str, Any], row: dict[str, Any], source_path: str, source_member: str,
    source_sha256: str, source_kind: str,
) -> dict[str, Any]:
    row_text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    likely_key, likely_raw = incentive_value(row, unlikely=False)
    unlikely_key, unlikely_raw = incentive_value(row, unlikely=True)
    base_key, base_raw = first_value(row, {"base_salary", "salary", "frozen_listed_base_salary", "listed_base_salary"}, ("base_salary",))
    cap_key, cap_raw = first_value(row, {"cap_hit", "salary_cap_hit"}, ("cap_hit",))
    date_key, date_raw = first_value(
        row,
        {"signing_date", "effective_date", "contract_date", "transaction_date", "event_date"},
        ("signing_date", "effective_date", "contract_date", "transaction_date"),
    )
    season_key, season_raw = first_value(row, {"season", "season_label", "salary_season", "cap_season"}, ("season_label",))
    likely = money_or_none(likely_raw)
    unlikely = money_or_none(unlikely_raw)
    base_salary = money_or_none(base_raw)
    cap_hit = money_or_none(cap_raw)
    evidence_date = parse_date(date_raw)
    season_text = f"{clean(season_raw)} {row_text} {source_member} {source_path}"
    season_matches = SEASON_LABEL in season_text or "2026_27" in season_text
    frozen_salary = money_or_none(target.get("frozen_listed_base_salary")) or 0
    salary_match = frozen_salary in {value for value in (base_salary, cap_hit) if value is not None}
    values_explicit = likely is not None and unlikely is not None
    pre_split = evidence_date is not None and evidence_date <= SPLIT_DATE
    status_text = row_text.casefold()
    disallowed = any(token in status_text for token in ("post_split_contract_only", "unresolved_post_split", "context_only"))
    eligible = values_explicit and season_matches and pre_split and salary_match and not disallowed
    reasons: list[str] = []
    if not values_explicit:
        reasons.append("missing_explicit_likely_or_unlikely_value")
    if not season_matches:
        reasons.append("season_not_explicitly_2026_27")
    if evidence_date is None:
        reasons.append("missing_contract_effective_date")
    elif evidence_date > SPLIT_DATE:
        reasons.append("post_split_date")
    if not salary_match:
        reasons.append("frozen_salary_not_matched")
    if disallowed:
        reasons.append("source_marks_row_temporally_ineligible")
    return {
        "player_id": clean(target.get("player_id")),
        "player_name": clean(target.get("player_name")),
        "frozen_team": clean(target.get("frozen_team")),
        "frozen_listed_base_salary": frozen_salary,
        "source_path": source_path,
        "source_member": source_member,
        "source_kind": source_kind,
        "source_sha256": source_sha256,
        "likely_field": likely_key,
        "unlikely_field": unlikely_key,
        "date_field": date_key,
        "season_field": season_key,
        "base_salary_field": base_key,
        "cap_hit_field": cap_key,
        "evidence_date": evidence_date.isoformat() if evidence_date else "",
        "base_salary": "" if base_salary is None else base_salary,
        "cap_hit": "" if cap_hit is None else cap_hit,
        "likely_incentive": "" if likely is None else likely,
        "unlikely_incentive": "" if unlikely is None else unlikely,
        "season_matches": season_matches,
        "salary_matches_frozen": salary_match,
        "eligible_pre_split_evidence": eligible,
        "ineligibility_reason": "|".join(reasons),
        "row_excerpt": row_text[:1000],
    }


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script\b[^>]*>.*?</script>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<style\b[^>]*>.*?</style>", " ", fragment, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def html_candidates(target: dict[str, Any], body: str, source_path: str, source_member: str, source_sha256: str) -> list[dict[str, Any]]:
    starts = [match.start() for match in re.finditer(r'<div\b[^>]*class="sw_playerContract"[^>]*>', body, re.I)]
    if not starts:
        return []
    starts.append(len(body))
    rows: list[dict[str, Any]] = []
    for index in range(len(starts) - 1):
        section = body[starts[index]:starts[index + 1]]
        section_text = strip_tags(section)
        date_match = re.search(r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", section_text, re.I)
        signing_date = clean(date_match.group(1)) if date_match else ""
        for table_row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", section, re.I | re.S):
            cells = [strip_tags(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", table_row, re.I | re.S)]
            if len(cells) < 8 or not cells[0].startswith(SEASON_LABEL):
                continue
            row = {
                "player_id": clean(target.get("player_id")),
                "player_name": clean(target.get("player_name")),
                "season": cells[0],
                "signing_date": signing_date,
                "cap_hit": cells[3],
                "base_salary": cells[4].split(" ")[0],
                "likely_incentive": cells[6],
                "unlikely_incentive": cells[7],
            }
            rows.append(row_candidate(target, row, source_path, source_member, source_sha256, "salaryswish_contract_html"))
    return rows


def text_has_target(text: str, target: dict[str, Any]) -> bool:
    player_id = clean(target.get("player_id"))
    return bool(re.search(rf"(?<!\d){re.escape(player_id)}(?!\d)", text) or normalize_name(target.get("player_name")) in normalize_name(text))


def inspect_text(payload: bytes, source_path: str, source_member: str, targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = payload.decode("utf-8-sig", errors="replace")
    digest = sha256_bytes(payload)
    candidates: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    suffix = Path(source_member or source_path).suffix.lower()
    if suffix == ".csv":
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error:
            rows = []
        for row_number, row in enumerate(rows, start=2):
            row_text = json.dumps(row, ensure_ascii=False, sort_keys=True)
            for target in targets:
                if not target_match(row, row_text, target):
                    continue
                candidate = row_candidate(target, row, source_path, source_member, digest, "csv_row")
                candidate["source_row_number"] = row_number
                candidates.append(candidate)
                hits.append({
                    "player_id": target["player_id"], "player_name": target["player_name"],
                    "source_path": source_path, "source_member": source_member,
                    "source_kind": "csv_row", "source_sha256": digest,
                    "source_row_number": row_number, "excerpt": row_text[:1000],
                })
        return candidates, hits
    if suffix in {".html", ".htm"}:
        for target in targets:
            if text_has_target(text, target):
                parsed = html_candidates(target, text, source_path, source_member, digest)
                candidates.extend(parsed)
                hits.append({
                    "player_id": target["player_id"], "player_name": target["player_name"],
                    "source_path": source_path, "source_member": source_member,
                    "source_kind": "html", "source_sha256": digest,
                    "source_row_number": "", "excerpt": strip_tags(text)[:1000],
                })
        return candidates, hits
    for target in targets:
        if text_has_target(text, target):
            location = normalize_name(text).find(normalize_name(target.get("player_name")))
            start = max(0, location - 250) if location >= 0 else 0
            hits.append({
                "player_id": target["player_id"], "player_name": target["player_name"],
                "source_path": source_path, "source_member": source_member,
                "source_kind": suffix.lstrip(".") or "text", "source_sha256": digest,
                "source_row_number": "", "excerpt": re.sub(r"\s+", " ", text[start:start + 1000]),
            })
    return candidates, hits


def excluded_path(path: Path, upstream_zip: Path) -> bool:
    lowered = str(path).lower()
    if path.resolve() == upstream_zip.resolve():
        return True
    return any(token in lowered for token in ("/.git/", "\\.git\\", "__pycache__", ".fanon", "installer_test_stage"))


def scan_repository(root: Path, upstream_zip: Path, targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    stats = {"archives_scanned": 0, "members_scanned": 0, "plain_files_scanned": 0, "bytes_scanned": 0, "scan_errors": 0}
    archives = [path for path in root.rglob("*.zip") if path.is_file() and not excluded_path(path, upstream_zip)]
    archives.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for archive_path in archives[:MAX_ARCHIVES]:
        if stats["bytes_scanned"] >= MAX_TOTAL_SCAN_BYTES:
            break
        try:
            with zipfile.ZipFile(archive_path) as archive:
                stats["archives_scanned"] += 1
                for info in archive.infolist():
                    if stats["bytes_scanned"] >= MAX_TOTAL_SCAN_BYTES:
                        break
                    if info.is_dir() or Path(info.filename).suffix.lower() not in TEXT_SUFFIXES:
                        continue
                    if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                        continue
                    payload = archive.read(info)
                    stats["members_scanned"] += 1
                    stats["bytes_scanned"] += len(payload)
                    found_candidates, found_hits = inspect_text(payload, str(archive_path.relative_to(root)), info.filename, targets)
                    candidates.extend(found_candidates)
                    hits.extend(found_hits)
        except Exception:
            stats["scan_errors"] += 1
        if stats["archives_scanned"] and stats["archives_scanned"] % 25 == 0:
            print(
                f"  scanned {stats['archives_scanned']} archives / "
                f"{stats['members_scanned']} members / {stats['bytes_scanned']:,} bytes"
            )
    plain_files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and not excluded_path(path, upstream_zip)
    ]
    for path in plain_files:
        if stats["bytes_scanned"] >= MAX_TOTAL_SCAN_BYTES:
            break
        try:
            size = path.stat().st_size
            if size > MAX_PLAIN_FILE_BYTES:
                continue
            payload = path.read_bytes()
            stats["plain_files_scanned"] += 1
            stats["bytes_scanned"] += len(payload)
            found_candidates, found_hits = inspect_text(payload, str(path.relative_to(root)), "", targets)
            candidates.extend(found_candidates)
            hits.extend(found_hits)
        except Exception:
            stats["scan_errors"] += 1
    return candidates, hits, stats


def dedupe(rows: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        signature = tuple(row.get(key) for key in keys)
        if signature not in seen:
            seen.add(signature)
            result.append(row)
    return result


def main() -> int:
    root = Path.cwd().resolve()
    upstream_zip = latest_upstream(root)
    with zipfile.ZipFile(upstream_zip) as archive:
        upstream_summary = json_suffix(archive, "frozen_incentive_source_acquisition_hotfix_v1_0_3_summary.json")
        upstream_checks = csv_suffix(archive, "frozen_incentive_source_acquisition_hotfix_v1_0_3_checks.csv")
        upstream_resolution = csv_suffix(archive, "validated_frozen_incentive_resolution_preview_331.csv")
        upstream_unresolved = csv_suffix(archive, "validated_unresolved_incentive_targets_11.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before the temporal evidence preview.")

    targets = sorted(upstream_unresolved, key=lambda row: clean(row.get("player_id")))
    print("=" * 132)
    print("2026 FROZEN INCENTIVE TEMPORAL EVIDENCE RESOLUTION PREVIEW V1")
    print("=" * 132)
    print("Scanning existing project evidence for only the exact 11-player quarantine queue...")
    candidates, hits, stats = scan_repository(root, upstream_zip, targets)
    candidates = dedupe(candidates, (
        "player_id", "source_path", "source_member", "source_row_number", "evidence_date",
        "base_salary", "cap_hit", "likely_incentive", "unlikely_incentive",
    ))
    hits = dedupe(hits, ("player_id", "source_path", "source_member", "source_row_number", "source_sha256"))
    eligible = [row for row in candidates if as_bool(row.get("eligible_pre_split_evidence"))]

    resolutions: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for target in targets:
        player_id = clean(target.get("player_id"))
        player_candidates = [row for row in eligible if clean(row.get("player_id")) == player_id]
        signatures = {
            (money_or_none(row.get("likely_incentive")), money_or_none(row.get("unlikely_incentive")))
            for row in player_candidates
        }
        if len(signatures) == 1:
            likely, unlikely = next(iter(signatures))
            sources = sorted({f"{row['source_path']}::{row['source_member']}" for row in player_candidates})
            resolution = dict(target)
            resolution.update({
                "resolution_status": "resolved_exact_pre_split_repository_evidence",
                "resolution_detail": "all eligible pre-split salary-matched evidence agrees",
                "likely_incentive": int(likely or 0),
                "unlikely_incentive": int(unlikely or 0),
                "eligible_evidence_row_count": len(player_candidates),
                "eligible_evidence_sources": "|".join(sources),
                "incentive_values_frozen": False,
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            })
        else:
            resolution = dict(target)
            resolution.update({
                "resolution_status": "unresolved_no_unique_pre_split_repository_evidence" if not signatures else "unresolved_conflicting_pre_split_repository_evidence",
                "resolution_detail": "no eligible candidate" if not signatures else "eligible candidates disagree",
                "likely_incentive": "",
                "unlikely_incentive": "",
                "eligible_evidence_row_count": len(player_candidates),
                "eligible_evidence_sources": "",
                "incentive_values_frozen": False,
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            })
            remaining.append(resolution)
        resolutions.append(resolution)

    newly_resolved = [row for row in resolutions if clean(row.get("resolution_status")).startswith("resolved_")]
    upstream_resolved = [row for row in upstream_resolution if not clean(row.get("resolution_status")).startswith("unresolved_")]
    combined: list[dict[str, Any]] = []
    resolution_by_id = {clean(row.get("player_id")): row for row in resolutions}
    for row in upstream_resolution:
        player_id = clean(row.get("player_id"))
        if player_id in resolution_by_id and resolution_by_id[player_id]["resolution_status"].startswith("resolved_"):
            replacement = dict(row)
            replacement.update(resolution_by_id[player_id])
            combined.append(replacement)
        else:
            combined.append(row)

    final_resolved = [row for row in combined if not clean(row.get("resolution_status")).startswith("unresolved_")]
    final_unresolved = [row for row in combined if clean(row.get("resolution_status")).startswith("unresolved_")]
    likely_total = sum(money_or_none(row.get("likely_incentive")) or 0 for row in final_resolved)
    unlikely_total = sum(money_or_none(row.get("unlikely_incentive")) or 0 for row in final_resolved)

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("")
    print("Validating the targeted temporal evidence preview...")
    add("upstream_v1_0_3_passed_all_strict_checks", upstream_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in upstream_checks), "passed V1.0.3")
    add("upstream_registry_is_exactly_331_unique", len(upstream_resolution) == 331 and len({clean(row.get("player_id")) for row in upstream_resolution}) == 331, "331/331")
    add("upstream_split_is_exactly_april_12", clean(upstream_summary.get("canonical_split_date")) == SPLIT_DATE.isoformat(), SPLIT_DATE.isoformat())
    add("upstream_resolution_signature_is_320_plus_11", len(upstream_resolved) == EXPECTED_UPSTREAM_RESOLVED and len(targets) == EXPECTED_UPSTREAM_UNRESOLVED, f"{len(upstream_resolved)} + {len(targets)}")
    add("exact_11_target_ids_are_preserved", {clean(row.get("player_id")) for row in targets} == EXPECTED_TARGET_IDS, f"{len(targets)}/11")
    add(
        "repository_scan_completed_with_bounded_scope",
        stats["archives_scanned"] <= MAX_ARCHIVES and stats["bytes_scanned"] <= MAX_TOTAL_SCAN_BYTES + MAX_ARCHIVE_MEMBER_BYTES,
        json.dumps(stats, sort_keys=True),
    )
    add("only_exact_11_targets_were_considered", all(clean(row.get("player_id")) in EXPECTED_TARGET_IDS for row in candidates + hits + resolutions), f"{len(resolutions)}/11")
    add("eligible_rows_are_pre_split_and_salary_matched", all(parse_date(row.get("evidence_date")) and parse_date(row.get("evidence_date")) <= SPLIT_DATE and as_bool(row.get("salary_matches_frozen")) for row in eligible), f"{len(eligible)} rows")
    add("new_resolutions_require_unique_agreement", all(row.get("eligible_evidence_row_count", 0) and clean(row.get("eligible_evidence_sources")) for row in newly_resolved), f"{len(newly_resolved)}/11")
    add("combined_registry_remains_exactly_331_unique", len(combined) == 331 and len({clean(row.get("player_id")) for row in combined}) == 331, "331/331")
    add("no_post_split_candidate_is_selected", all(not as_bool(row.get("eligible_pre_split_evidence")) for row in candidates if parse_date(row.get("evidence_date")) and parse_date(row.get("evidence_date")) > SPLIT_DATE), "post-split excluded")
    add("all_values_remain_preview_only", all(not as_bool(row.get("incentive_values_frozen")) and not as_bool(row.get("applied_to_team_salary")) and not as_bool(row.get("state_mutation_applied")) for row in resolutions), "0 frozen / 0 applied")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_frozen_incentive_temporal_evidence_resolution_preview_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "upstream_audit_zip": upstream_zip.name,
        "repository_scan": stats,
        "repository_evidence_hit_count": len(hits),
        "structured_candidate_count": len(candidates),
        "eligible_pre_split_candidate_count": len(eligible),
        "newly_resolved_target_count": len(newly_resolved),
        "remaining_temporal_queue_count": len(remaining),
        "combined_resolved_count": len(final_resolved),
        "combined_unresolved_count": len(final_unresolved),
        "preview_likely_incentive_total": likely_total,
        "preview_unlikely_incentive_total": unlikely_total,
        "incentive_values_frozen": 0,
        "incentive_values_applied": 0,
        "network_requests_performed": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": "Freeze the complete 331-player/30-team incentive ledger if the remaining queue is zero; otherwise resolve only the exact remaining evidence queue reported here.",
    }

    with tempfile.TemporaryDirectory(prefix="fa_frozen_incentive_temporal_preview_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "temporal_repository_evidence_hits.csv", hits)
        write_csv(export / "temporal_structured_candidates.csv", candidates)
        write_csv(export / "eligible_pre_split_salary_matched_candidates.csv", eligible)
        write_csv(export / "targeted_temporal_resolution_preview_11.csv", resolutions)
        write_csv(export / f"remaining_temporal_evidence_queue_{len(remaining)}.csv", remaining)
        write_csv(export / "combined_frozen_incentive_resolution_preview_331.csv", combined)
        write_csv(export / "frozen_incentive_temporal_evidence_resolution_preview_checks.csv", checks)
        (export / "frozen_incentive_temporal_evidence_resolution_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FROZEN INCENTIVE TEMPORAL EVIDENCE RESOLUTION PREVIEW V1
==================================================================

This offline preview consumes the passed V1.0.3 acquisition result and scans
existing project evidence only for the exact 11-player temporal quarantine.
A row is eligible only when it contains explicit likely and unlikely incentive
values for 2026-27, has a contract/effective date on or before April 12, 2026,
and matches the frozen player's base salary or cap hit. Conflicting eligible
rows remain unresolved.

No network request is made. No value is frozen or applied. Team Salary, roster,
contracts, simulation state, overlays, and the canonical checkpoint are not
mutated.
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
        raise RuntimeError("Frozen Incentive Temporal Evidence Resolution Preview V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FROZEN INCENTIVE TEMPORAL EVIDENCE RESOLUTION PREVIEW V1 PASSED")
    print("=" * 132)
    print(f"Repository evidence hits:       {len(hits):>5}")
    print(f"Structured candidate rows:      {len(candidates):>5}")
    print(f"Eligible pre-split candidates:  {len(eligible):>5}")
    print(f"Newly resolved targets:         {len(newly_resolved):>5}/11")
    print(f"Remaining temporal queue:       {len(remaining):>5}/11")
    print(f"Combined resolution:            {len(final_resolved):>5}/331")
    print(f"Preview likely incentives:      ${likely_total:,}")
    print(f"Preview unlikely incentives:    ${unlikely_total:,}")
    print("Incentive values frozen:             0")
    print("Incentive values applied:            0")
    print("Checkpoint write:                 NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
