from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-zero-game-playerstate-evidence-probe-v1-2026-08-16"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
CLONE_PATTERN = "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip"
TARGETS = {
    "1627832": {"player_name": "Fred VanVleet", "opening_owner": "HOU", "lifecycle": "player_option_decision"},
    "1642440": {"player_name": "Gabe McGlothan", "opening_owner": "FA", "lifecycle": "immediate_market"},
    "1642850": {"player_name": "Thomas Sorber", "opening_owner": "OKC", "lifecycle": "guaranteed_under_contract"},
    "202681": {"player_name": "Kyrie Irving", "opening_owner": "DAL", "lifecycle": "guaranteed_under_contract"},
    "203081": {"player_name": "Damian Lillard", "opening_owner": "POR", "lifecycle": "guaranteed_under_contract"},
}
ID_FIELDS = ("player_id", "person_id", "nba_player_id", "PLAYER_ID")
SCAN_TOKENS = ("player", "rating", "profile", "position", "stat", "skill", "roster", "development", "population")
MAX_FILE_BYTES = 30_000_000
MAX_TOTAL_BYTES = 350_000_000
MAX_HITS_PER_PLAYER = 100


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    return hashlib.sha256(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).hexdigest()


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one ZIP member ending with {suffix}; found {len(matches)}")
    return matches[0]


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


def find_passed(root: Path) -> Path:
    valid: list[Path] = []
    for path in root.rglob(CLONE_PATTERN):
        try:
            with zipfile.ZipFile(path) as archive:
                summary = json_suffix(archive, "clone_application_summary.json")
                if summary.get("passed") is True and not summary.get("failed_checks"):
                    valid.append(path)
        except Exception:
            continue
    if not valid:
        raise RuntimeError("Missing passed clone-only decision preview audit.")
    return max(valid, key=lambda path: path.stat().st_mtime)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields or [])
    if not fieldnames:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def record_target_id(record: dict[str, Any]) -> str:
    for field in ID_FIELDS:
        if field in record and pid(record.get(field)) in TARGETS:
            return pid(record.get(field))
    return ""


def compact_record(record: dict[str, Any]) -> str:
    preferred = [
        key for key in record
        if any(token in key.lower() for token in ("player", "name", "position", "age", "rating", "overall", "skill", "stat", "team", "salary"))
    ]
    keys = preferred[:35] or list(record)[:20]
    return json.dumps({key: record.get(key) for key in keys}, sort_keys=True, default=str)[:12000]


def json_records(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_records(child)


def scan_payload(source: str, suffix: str, payload: bytes, hits: list[dict[str, Any]]) -> None:
    target_bytes = [target.encode() for target in TARGETS]
    if not any(value in payload for value in target_bytes):
        return
    suffix = suffix.lower()
    records: Iterable[dict[str, Any]] = ()
    try:
        if suffix == ".csv":
            records = csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="replace")))
        elif suffix in {".json", ".jsonl"}:
            text = payload.decode("utf-8-sig", errors="replace")
            if suffix == ".jsonl":
                records = (json.loads(line) for line in text.splitlines() if line.strip())
            else:
                records = json_records(json.loads(text))
    except Exception:
        records = ()
    found: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        target = record_target_id(record)
        if not target:
            continue
        if sum(row["player_id"] == target for row in hits) >= MAX_HITS_PER_PLAYER:
            continue
        hits.append({
            "player_id": target,
            "player_name": TARGETS[target]["player_name"],
            "source": source,
            "record": compact_record(record),
        })
        found.add(target)
    if not found:
        for target in TARGETS:
            if target.encode() in payload and sum(row["player_id"] == target for row in hits) < MAX_HITS_PER_PLAYER:
                hits.append({
                    "player_id": target,
                    "player_name": TARGETS[target]["player_name"],
                    "source": source,
                    "record": "raw_identifier_hit_no_structured_record",
                })


def scan_repository(root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    hits: list[dict[str, Any]] = []
    files = 0
    members = 0
    scanned_bytes = 0
    roots = [root / "app_data", root / "data" / "processed", root / "outputs"]
    candidates: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".csv", ".json", ".jsonl", ".zip"}:
                continue
            lowered = path.name.lower()
            if any(token in lowered for token in SCAN_TOKENS):
                candidates.append(path)
    for path in sorted(set(candidates), key=lambda item: str(item)):
        if scanned_bytes >= MAX_TOTAL_BYTES:
            break
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            files += 1
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        suffix = Path(info.filename).suffix.lower()
                        lowered = info.filename.lower()
                        if suffix not in {".csv", ".json", ".jsonl"} or info.file_size > MAX_FILE_BYTES:
                            continue
                        if not any(token in lowered for token in SCAN_TOKENS):
                            continue
                        if scanned_bytes + info.file_size > MAX_TOTAL_BYTES:
                            break
                        payload = archive.read(info)
                        scanned_bytes += len(payload)
                        members += 1
                        scan_payload(f"{path.relative_to(root)}::{info.filename}", suffix, payload, hits)
            else:
                payload = path.read_bytes()
                scanned_bytes += len(payload)
                scan_payload(str(path.relative_to(root)), path.suffix, payload, hits)
        except Exception:
            continue
    return hits, {"files": files, "archive_members": members, "bytes": scanned_bytes}


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from simulation_player_stat_profiles_v1 import load_player_stat_profiles
    from simulation_roster_validator_v1 import RosterValidationConfig, simulation_player_from_runtime

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before zero-game PlayerState probe.")
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    state_digest_before = object_digest(checkpoint.simulation_state)
    trade_digest_before = object_digest(checkpoint.trade_state)

    clone_zip = find_passed(root)
    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = json_suffix(archive, "clone_application_summary.json")
        owner_rows = csv_suffix(archive, "clone_owner_ledger_587.csv")
    owner_ids = {pid(row.get("player_id")) for row in owner_rows}
    checkpoint_ids = set(checkpoint.simulation_state.players)
    gap = owner_ids - checkpoint_ids

    print("=" * 132)
    print("2026 ZERO-GAME PLAYERSTATE EVIDENCE PROBE V1")
    print("=" * 132)
    print("Inspecting only the exact five-player checkpoint population supplement...")

    runtime = load_runtime_data()
    profiles = load_player_stat_profiles()
    config = RosterValidationConfig(
        minimum_game_players=int(getattr(checkpoint.simulation_state.settings, "minimum_game_players", 8) or 8),
        target_rotation_size=int(getattr(checkpoint.simulation_state.settings, "rotation_size", 10) or 10),
    )
    coverage: list[dict[str, Any]] = []
    runtime_maps = ("ratings_by_id", "trade_by_id", "financial_by_id", "market_by_id", "player_cba_by_id")
    for target, expected in TARGETS.items():
        player = simulation_player_from_runtime(
            runtime,
            player_id=target,
            team="" if expected["opening_owner"] == "FA" else expected["opening_owner"],
            config=config,
        )
        profile = dict(profiles.get(target, {}) or {})
        map_hits = [name for name in runtime_maps if target in (getattr(runtime, name, {}) or {})]
        coverage.append({
            "player_id": target,
            "expected_player_name": expected["player_name"],
            "opening_owner": expected["opening_owner"],
            "lifecycle": expected["lifecycle"],
            "checkpoint_present": target in checkpoint_ids,
            "runtime_map_hits": "|".join(map_hits),
            "canonical_runtime_name": clean(player.player_name),
            "canonical_runtime_position": clean(player.position),
            "canonical_runtime_overall_rating": float(player.overall_rating),
            "canonical_rating_source": clean(player.rating_source),
            "stat_profile_present": bool(profile),
            "profile_age": profile.get("age_2026_27", profile.get("age")),
            "profile_position": profile.get("position"),
            "profile_reliability": profile.get("profile_reliability"),
            "profile_field_count": len(profile),
            "canonical_identity_ready": clean(player.player_name).casefold() == expected["player_name"].casefold(),
            "canonical_position_ready": clean(player.position).upper() not in {"", "UNK"},
            "canonical_profile_ready": bool(profile),
        })

    evidence_hits, scan = scan_repository(root)
    hit_ids = {row["player_id"] for row in evidence_hits}
    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating targeted probe invariants...")
    add("upstream_clone_preview_passed", clone_summary.get("passed") is True, clone_zip.name)
    add("checkpoint_population_is_exactly_582", len(checkpoint_ids) == 582, str(len(checkpoint_ids)))
    add("ownership_universe_is_exactly_587", len(owner_ids) == 587, str(len(owner_ids)))
    add("population_gap_is_exactly_the_audited_five", gap == set(TARGETS), repr(sorted(gap)))
    add("runtime_coverage_exported_for_exact_five", len(coverage) == 5 and {row["player_id"] for row in coverage} == set(TARGETS), "5/5")
    add("repository_scan_completed_with_bounded_scope", scan["bytes"] <= MAX_TOTAL_BYTES, json.dumps(scan, sort_keys=True))
    add("only_target_player_evidence_exported", all(row["player_id"] in TARGETS for row in evidence_hits), f"hits={len(evidence_hits)}")
    add("loaded_simulation_state_unchanged", object_digest(checkpoint.simulation_state) == state_digest_before, state_digest_before)
    add("loaded_trade_state_unchanged", object_digest(checkpoint.trade_state) == trade_digest_before, trade_digest_before)
    add("checkpoint_file_unchanged", sha256_file(checkpoint_path) == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_before)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    gameplay_ready_ids = {
        row["player_id"] for row in coverage
        if row["canonical_identity_ready"] and row["canonical_position_ready"] and row["canonical_profile_ready"]
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_zero_game_playerstate_evidence_probe_v1_{SEASON_LABEL}_{stamp}"
    output = root / "outputs" / "audits" / f"{name}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": not failed,
        "failed_checks": failed,
        "checkpoint_population_count": len(checkpoint_ids),
        "ownership_universe_count": len(owner_ids),
        "exact_population_gap_ids": sorted(gap),
        "runtime_identity_ready_count": sum(bool(row["canonical_identity_ready"]) for row in coverage),
        "runtime_position_ready_count": sum(bool(row["canonical_position_ready"]) for row in coverage),
        "canonical_profile_ready_count": sum(bool(row["canonical_profile_ready"]) for row in coverage),
        "repository_evidence_hit_count": len(evidence_hits),
        "repository_evidence_target_count": len(hit_ids),
        "gameplay_materialization_ready_ids": sorted(gameplay_ready_ids),
        "gameplay_materialization_blocked_ids": sorted(set(TARGETS) - gameplay_ready_ids),
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "next_slice": "Build the exact five-player clone-only PlayerState supplement from the exported canonical and repository evidence, then rerun the 111-decision transaction candidate.",
    }
    with tempfile.TemporaryDirectory(prefix="fa_zero_game_playerstate_probe_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "zero_game_playerstate_runtime_coverage_5.csv", coverage)
        write_csv(folder / "zero_game_playerstate_repository_evidence_hits.csv", evidence_hits, ["player_id", "player_name", "source", "record"])
        write_csv(folder / "zero_game_playerstate_probe_checks.csv", checks, ["check_id", "status", "severity", "detail"])
        (folder / "zero_game_playerstate_probe_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(
            "2026 ZERO-GAME PLAYERSTATE EVIDENCE PROBE V1\n\n"
            "This audit inspects only Fred VanVleet, Gabe McGlothan, Thomas Sorber, Kyrie Irving, and Damian Lillard.\n"
            "It does not create PlayerState objects, apply lifecycle decisions, or write the checkpoint.\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 ZERO-GAME PLAYERSTATE EVIDENCE PROBE V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print(f"Checkpoint population:          {len(checkpoint_ids)}")
    print(f"Ownership universe:             {len(owner_ids)}")
    print(f"Exact population gap:           {len(gap)}/5")
    print(f"Runtime identity ready:         {summary['runtime_identity_ready_count']}/5")
    print(f"Runtime position ready:         {summary['runtime_position_ready_count']}/5")
    print(f"Canonical profile ready:        {summary['canonical_profile_ready_count']}/5")
    print(f"Repository evidence hits:       {len(evidence_hits)}")
    print(f"PlayerState objects created:    0")
    print(f"Checkpoint write:               NOT PERFORMED")
    print(f"Audit ZIP: {output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
