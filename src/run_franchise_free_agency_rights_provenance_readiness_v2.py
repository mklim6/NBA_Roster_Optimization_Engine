from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

RUNNER_VERSION = "franchise-free-agency-rights-provenance-readiness-v2-2026-08-14"
EXPECTED_POPULATION_PREFIX = "franchise-free-agency-verified-bird-rights-population-v1-"
OUTPUT_PREFIX = "franchise_free_agency_rights_provenance_readiness"

STRUCTURED_EXTENSIONS = {".csv", ".parquet", ".json", ".jsonl"}
SCAN_TOP_LEVEL_DIRS = ("data", "evidence", "outputs")
EXCLUDED_PATH_TOKENS = (
    "\\backups\\", "/backups/",
    "\\.git\\", "/.git/",
    "\\.venv\\", "/.venv/",
    "\\site-packages\\", "/site-packages/",
    "\\outputs\\audits\\", "/outputs/audits/",
    "\\free_agency_rights_population_recovery\\",
    "/free_agency_rights_population_recovery/",
)

PLAYER_ID_ALIASES = (
    "player_id", "nba_player_id", "person_id", "personid", "playerid",
)
PLAYER_NAME_ALIASES = (
    "player_name", "player", "player_display_name", "display_name", "name",
)
SEASON_ALIASES = (
    "season", "season_label", "season_year", "league_year", "year",
)
DATE_PATTERNS = (
    r"(^|_)(transaction|trade)(_date)?($|_)",
    r"(^|_)(acquired|acquisition)(_date)?($|_)",
    r"(^|_)(signed|signing)(_date)?($|_)",
    r"(^|_)(waived|waiver|claim|claimed)(_date)?($|_)",
    r"(^|_)(effective|event)(_date)?($|_)",
)
TYPE_PATTERNS = (
    r"(^|_)(transaction|event|action|move|acquisition|signing|waiver|trade)(_type)?($|_)",
    r"(^|_)transaction_description($|_)",
)
FROM_TEAM_PATTERNS = (
    r"(^|_)(from|old|previous|sending|source|originating|prior)_team($|_)",
    r"(^|_)team_from($|_)",
)
TO_TEAM_PATTERNS = (
    r"(^|_)(to|new|destination|acquiring|receiving|current)_team($|_)",
    r"(^|_)team_to($|_)",
    r"(^|_)team_abbreviation($|_)",
    r"(^|_)team_abbr($|_)",
)
DESCRIPTION_PATTERNS = (
    r"(^|_)(description|details|summary|notes|evidence_summary|transaction_text|transaction_description)($|_)",
)
SALARY_PATTERNS = (
    r"(^|_)(prior_)?regular_salary($|_)",
    r"(^|_)(base|annual|player|trade|matching|current|cap)_?salary($|_)",
    r"(^|_)salary(_amount)?($|_)",
    r"(^|_)cap_hit($|_)",
    r"(^|_)salary_\d{4}_\d{2}($|_)",
)
CONTRACT_PATTERNS = (
    r"(^|_)contract(_type|_status|_start|_end|_date)?($|_)",
    r"(^|_)contract_type($|_)",
)
SOURCE_PATTERNS = (
    r"(^|_)(primary|secondary|authoritative)?_?source(_url|_name|_authority)?($|_)",
    r"(^|_)url($|_)",
)

FILENAME_SIGNAL_TOKENS = (
    "transaction", "trade", "signing", "signed", "waiver", "waived",
    "acquired", "acquisition", "contract", "salary", "payroll",
    "player_financial", "player-cba", "player_cba", "restriction",
    "eligibility", "roster", "free_agency", "free-agent", "free_agent",
)

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def norm_col(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

def first_alias(columns: list[str], aliases: Iterable[str]) -> str:
    mapping = {norm_col(c): c for c in columns}
    for alias in aliases:
        if norm_col(alias) in mapping:
            return mapping[norm_col(alias)]
    return ""

def first_pattern(columns: list[str], patterns: Iterable[str]) -> str:
    for column in columns:
        n = norm_col(column)
        if any(re.search(pattern, n) for pattern in patterns):
            return column
    return ""

def all_pattern(columns: list[str], patterns: Iterable[str]) -> list[str]:
    result: list[str] = []
    for column in columns:
        n = norm_col(column)
        if any(re.search(pattern, n) for pattern in patterns):
            result.append(column)
    return result

def read_csv_header(path: Path) -> list[str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                return [clean(v) for v in next(reader, []) if clean(v)]
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []

def read_json_columns(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            if path.suffix.lower() == ".jsonl":
                line = handle.readline()
                obj = json.loads(line) if line.strip() else {}
            else:
                obj = json.load(handle)
        if isinstance(obj, list) and obj and isinstance(obj[0], Mapping):
            return [str(k) for k in obj[0].keys()]
        if isinstance(obj, Mapping):
            for key in ("rows", "data", "records", "transactions", "players", "registry"):
                value = obj.get(key)
                if isinstance(value, list) and value and isinstance(value[0], Mapping):
                    return [str(k) for k in value[0].keys()]
            return [str(k) for k in obj.keys()]
    except Exception:
        pass
    return []

def parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.ParquetFile(path).schema.names)
    except Exception:
        try:
            import pandas as pd
            return list(pd.read_parquet(path).head(0).columns)
        except Exception:
            return []

def structured_columns(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_header(path)
    if suffix == ".parquet":
        return parquet_columns(path)
    if suffix in {".json", ".jsonl"}:
        return read_json_columns(path)
    return []

def read_ids(path: Path, id_column: str) -> set[str]:
    if not id_column:
        return set()
    suffix = path.suffix.lower()
    try:
        import pandas as pd
        if suffix == ".csv":
            frame = pd.read_csv(
                path,
                usecols=[id_column],
                dtype={id_column: "string"},
                low_memory=False,
                encoding="utf-8-sig",
            )
            return {pid(v) for v in frame[id_column].dropna().tolist() if pid(v)}
        if suffix == ".parquet":
            frame = pd.read_parquet(path, columns=[id_column])
            return {pid(v) for v in frame[id_column].dropna().tolist() if pid(v)}
        if suffix in {".json", ".jsonl"}:
            if suffix == ".jsonl":
                values = []
                with path.open("r", encoding="utf-8-sig") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        if isinstance(obj, Mapping) and id_column in obj:
                            values.append(obj[id_column])
                return {pid(v) for v in values if pid(v)}
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = obj if isinstance(obj, list) else None
            if rows is None and isinstance(obj, Mapping):
                for key in ("rows", "data", "records", "transactions", "players"):
                    if isinstance(obj.get(key), list):
                        rows = obj[key]
                        break
            if rows:
                return {
                    pid(row.get(id_column))
                    for row in rows
                    if isinstance(row, Mapping) and pid(row.get(id_column))
                }
    except UnicodeDecodeError:
        try:
            import pandas as pd
            if suffix == ".csv":
                frame = pd.read_csv(
                    path,
                    usecols=[id_column],
                    dtype={id_column: "string"},
                    low_memory=False,
                    encoding="cp1252",
                )
                return {pid(v) for v in frame[id_column].dropna().tolist() if pid(v)}
        except Exception:
            return set()
    except Exception:
        return set()
    return set()

def path_excluded(path: Path) -> bool:
    text = str(path).lower()
    return any(token.lower() in text for token in EXCLUDED_PATH_TOKENS)

@dataclass(frozen=True)
class SourceInventoryRow:
    path: str
    extension: str
    size_bytes: int
    filename_signal: bool
    player_id_column: str
    player_name_column: str
    season_column: str
    event_date_column: str
    event_type_column: str
    from_team_column: str
    to_team_column: str
    description_column: str
    salary_columns: str
    contract_column: str
    source_reference_column: str
    transaction_path_capability: str
    salary_capability: str
    unresolved_players_covered: int
    source_fingerprint: str

def classify_source(path: Path, columns: list[str], unresolved_ids: set[str]) -> SourceInventoryRow | None:
    if not columns:
        return None

    id_col = first_alias(columns, PLAYER_ID_ALIASES)
    name_col = first_alias(columns, PLAYER_NAME_ALIASES)
    season_col = first_alias(columns, SEASON_ALIASES)
    date_col = first_pattern(columns, DATE_PATTERNS)
    type_col = first_pattern(columns, TYPE_PATTERNS)
    from_col = first_pattern(columns, FROM_TEAM_PATTERNS)
    to_col = first_pattern(columns, TO_TEAM_PATTERNS)
    desc_col = first_pattern(columns, DESCRIPTION_PATTERNS)
    salary_cols = all_pattern(columns, SALARY_PATTERNS)
    contract_col = first_pattern(columns, CONTRACT_PATTERNS)
    source_col = first_pattern(columns, SOURCE_PATTERNS)

    filename_signal = any(token in path.name.lower() for token in FILENAME_SIGNAL_TOKENS)

    transaction_capability = "none"
    if id_col and date_col and from_col and to_col and (type_col or desc_col):
        transaction_capability = "strong_event_path"
    elif id_col and date_col and (type_col or desc_col) and (from_col or to_col):
        transaction_capability = "partial_event_path"
    elif id_col and date_col and (type_col or desc_col):
        transaction_capability = "dated_event_text"
    elif id_col and (type_col or desc_col) and (from_col or to_col):
        transaction_capability = "undated_event_partial"

    salary_capability = "none"
    if id_col and salary_cols and (season_col or date_col):
        salary_capability = "strong_prior_salary_candidate"
    elif id_col and salary_cols:
        salary_capability = "salary_candidate"

    if (
        transaction_capability == "none"
        and salary_capability == "none"
        and not (filename_signal and id_col)
    ):
        return None

    covered = set()
    if id_col:
        covered = read_ids(path, id_col).intersection(unresolved_ids)

    return SourceInventoryRow(
        path=str(path.resolve()),
        extension=path.suffix.lower().lstrip("."),
        size_bytes=int(path.stat().st_size),
        filename_signal=bool(filename_signal),
        player_id_column=id_col,
        player_name_column=name_col,
        season_column=season_col,
        event_date_column=date_col,
        event_type_column=type_col,
        from_team_column=from_col,
        to_team_column=to_col,
        description_column=desc_col,
        salary_columns="|".join(salary_cols),
        contract_column=contract_col,
        source_reference_column=source_col,
        transaction_path_capability=transaction_capability,
        salary_capability=salary_capability,
        unresolved_players_covered=len(covered),
        source_fingerprint=sha256(path),
    )

def find_population_zip(root: Path) -> Path:
    candidates: list[Path] = []
    patterns = (
        "franchise_free_agency_rights_population_*.zip",
        "*rights_population*2026-27*.zip",
    )
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file() and "provenance_readiness" not in path.name:
                candidates.append(path)
    if not candidates:
        raise RuntimeError(
            "Could not locate the V1 rights-population audit ZIP. "
            "Keep the generated franchise_free_agency_rights_population_*.zip "
            "under the project root or outputs/audits."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)

def extract_population_inputs(zip_path: Path, tmp: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        summary_name = next((n for n in names if n.endswith("/rights_population_summary.json") or n == "rights_population_summary.json"), "")
        unresolved_name = next((n for n in names if n.endswith("/rights_population_unresolved.csv") or n == "rights_population_unresolved.csv"), "")
        proven_name = next((n for n in names if n.endswith("/rights_population_proven.csv") or n == "rights_population_proven.csv"), "")
        if not summary_name or not unresolved_name or not proven_name:
            raise RuntimeError("Population ZIP is missing summary/proven/unresolved exports.")
        summary = json.loads(archive.read(summary_name).decode("utf-8-sig"))
        unresolved_text = archive.read(unresolved_name).decode("utf-8-sig")
        proven_text = archive.read(proven_name).decode("utf-8-sig")

    unresolved_reader = csv.DictReader(unresolved_text.splitlines())
    proven_reader = csv.DictReader(proven_text.splitlines())
    return summary, list(unresolved_reader), list(proven_reader)

def checkpoint_path_and_hash() -> tuple[Path | None, str]:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        path = Path(DEFAULT_CHECKPOINT_PATH)
        return path, sha256(path)
    except Exception:
        return None, ""

def overlay_path_and_hash(root: Path) -> tuple[Path, str]:
    path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    return path, sha256(path)

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def scan_sources(root: Path, unresolved_ids: set[str]) -> list[SourceInventoryRow]:
    result: list[SourceInventoryRow] = []
    seen_paths: set[Path] = set()
    for dirname in SCAN_TOP_LEVEL_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() not in STRUCTURED_EXTENSIONS
                or path_excluded(path)
                or path in seen_paths
            ):
                continue
            seen_paths.add(path)
            try:
                columns = structured_columns(path)
                row = classify_source(path, columns, unresolved_ids)
            except Exception:
                row = None
            if row is not None:
                result.append(row)
    result.sort(
        key=lambda row: (
            row.transaction_path_capability == "none",
            row.salary_capability == "none",
            -row.unresolved_players_covered,
            row.path.lower(),
        )
    )
    return result

def candidate_coverage_rows(
    unresolved: list[dict[str, str]],
    sources: list[SourceInventoryRow],
) -> list[dict[str, Any]]:
    source_id_cache: dict[str, set[str]] = {}
    for source in sources:
        if source.unresolved_players_covered <= 0 or not source.player_id_column:
            continue
        path = Path(source.path)
        source_id_cache[source.path] = read_ids(path, source.player_id_column)

    rows: list[dict[str, Any]] = []
    for candidate in unresolved:
        player_id = pid(candidate.get("player_id"))
        strong_tx: list[str] = []
        partial_tx: list[str] = []
        salary: list[str] = []
        research: list[str] = []
        for source in sources:
            ids = source_id_cache.get(source.path)
            if not ids or player_id not in ids:
                continue
            if source.transaction_path_capability == "strong_event_path":
                strong_tx.append(source.path)
            elif source.transaction_path_capability != "none":
                partial_tx.append(source.path)
            if source.salary_capability != "none":
                salary.append(source.path)
            if source.source_reference_column or source.description_column:
                research.append(source.path)

        if strong_tx:
            readiness = "strong_transaction_source_available"
        elif partial_tx:
            readiness = "partial_transaction_source_available"
        elif salary:
            readiness = "salary_source_only"
        elif research:
            readiness = "research_evidence_only"
        else:
            readiness = "no_local_provenance_source_found"

        try:
            streak = int(float(candidate.get("continuous_qualifying_seasons") or 0))
        except Exception:
            streak = 0
        try:
            service = int(float(candidate.get("years_of_service") or 0))
        except Exception:
            service = 0

        rows.append({
            "player_id": player_id,
            "player_name": clean(candidate.get("player_name")),
            "prior_team": clean(candidate.get("prior_team")).upper(),
            "years_of_service": service,
            "v1_same_team_streak": streak,
            "v1_rights_classification": clean(candidate.get("rights_classification")),
            "v1_status": clean(candidate.get("status")),
            "readiness_status": readiness,
            "strong_transaction_source_count": len(strong_tx),
            "partial_transaction_source_count": len(partial_tx),
            "salary_source_count": len(salary),
            "research_evidence_source_count": len(research),
            "strong_transaction_sources": "|".join(strong_tx),
            "partial_transaction_sources": "|".join(partial_tx),
            "salary_sources": "|".join(salary),
            "research_sources": "|".join(research),
            "v2_priority_score": (
                (100 if streak >= 2 else 0)
                + min(service, 12) * 2
                + 50 * bool(strong_tx)
                + 20 * bool(partial_tx)
                + 10 * bool(salary)
                + 5 * bool(research)
            ),
        })
    rows.sort(
        key=lambda row: (
            -int(row["v2_priority_score"]),
            -int(row["v1_same_team_streak"]),
            -int(row["years_of_service"]),
            str(row["player_name"]).lower(),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["v2_priority_rank"] = index
    return rows

def source_rows(sources: list[SourceInventoryRow]) -> list[dict[str, Any]]:
    return [asdict(row) for row in sources]

def main() -> int:
    root = Path.cwd().resolve()
    population_zip = find_population_zip(root)

    checkpoint_path, checkpoint_before = checkpoint_path_and_hash()
    overlay_path, overlay_before = overlay_path_and_hash(root)

    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS PROVENANCE READINESS V2", flush=True)
    print("=" * 124, flush=True)
    print("[1/6] Loading the reviewed V1 rights-population audit...", flush=True)

    with tempfile.TemporaryDirectory(prefix="fa_rights_provenance_readiness_") as tmpdir:
        summary, unresolved, proven = extract_population_inputs(
            population_zip,
            Path(tmpdir),
        )

    population_version = clean(summary.get("version"))
    season_label = clean(summary.get("season_label")) or "unknown-season"
    unresolved_ids = {pid(row.get("player_id")) for row in unresolved if pid(row.get("player_id"))}

    print(f"      Population ZIP: {population_zip}", flush=True)
    print(f"      Population version: {population_version}", flush=True)
    print(f"      Unresolved queue: {len(unresolved_ids)}", flush=True)
    print("[2/6] Scanning local structured data for transaction and salary provenance...", flush=True)

    sources = scan_sources(root, unresolved_ids)
    strong_sources = [s for s in sources if s.transaction_path_capability == "strong_event_path"]
    partial_sources = [s for s in sources if s.transaction_path_capability not in {"none", "strong_event_path"}]
    salary_sources = [s for s in sources if s.salary_capability != "none"]

    print(
        f"      Relevant structured sources: {len(sources)} · "
        f"strong transaction {len(strong_sources)} · partial transaction {len(partial_sources)} · "
        f"salary {len(salary_sources)}",
        flush=True,
    )

    print("[3/6] Mapping the 161-player V1 unresolved queue to local evidence...", flush=True)
    coverage = candidate_coverage_rows(unresolved, sources)
    covered_strong = sum(row["strong_transaction_source_count"] > 0 for row in coverage)
    covered_partial = sum(
        row["strong_transaction_source_count"] == 0
        and row["partial_transaction_source_count"] > 0
        for row in coverage
    )
    covered_salary = sum(row["salary_source_count"] > 0 for row in coverage)
    no_local = sum(row["readiness_status"] == "no_local_provenance_source_found" for row in coverage)
    print(
        f"      Strong transaction coverage: {covered_strong} · "
        f"partial-only transaction coverage: {covered_partial} · "
        f"salary coverage: {covered_salary} · no local provenance hit: {no_local}",
        flush=True,
    )

    checkpoint_after = sha256(checkpoint_path) if checkpoint_path else ""
    overlay_after = sha256(overlay_path)

    checks: list[dict[str, Any]] = []
    def add_check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })

    print("[4/6] Running fail-closed readiness checks...", flush=True)
    add_check(
        "input_population_is_verified_v1",
        population_version.startswith(EXPECTED_POPULATION_PREFIX),
        "V2 readiness must consume the reviewed V1 population format.",
    )
    add_check(
        "input_unresolved_count_matches_summary",
        len(unresolved_ids) == int(summary.get("unresolved_count", -1)),
        "The unresolved CSV must exactly match its V1 summary count.",
    )
    add_check(
        "proven_plus_unresolved_matches_free_agent_count",
        len(proven) + len(unresolved) == int(summary.get("free_agent_count", -1)),
        "The V1 partition must still cover the complete current free-agent pool.",
    )
    add_check(
        "coverage_preserves_exact_unresolved_ids",
        {row["player_id"] for row in coverage} == unresolved_ids,
        "Readiness output must contain exactly the unresolved player IDs and no others.",
    )
    add_check(
        "readiness_never_reclassifies_rights",
        all(row["v1_status"] == "unresolved" and row["v1_rights_classification"] in {"", "unknown"} for row in coverage),
        "This diagnostic may surface evidence sources but may not change Bird classifications.",
    )
    add_check(
        "strong_transaction_sources_have_structured_path_fields",
        all(
            s.player_id_column
            and s.event_date_column
            and s.from_team_column
            and s.to_team_column
            and (s.event_type_column or s.description_column)
            for s in strong_sources
        ),
        "A strong source requires player, date, from-team, to-team, and event type/text.",
    )
    add_check(
        "salary_sources_have_player_and_salary_fields",
        all(s.player_id_column and s.salary_columns for s in salary_sources),
        "Salary candidates require a player ID and explicit salary field.",
    )
    add_check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "The canonical franchise checkpoint must remain byte-for-byte unchanged.",
    )
    add_check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "The V1 runtime rights overlay must not be created, changed, or deleted.",
    )

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    for row in checks:
        print(f"      {row['check_id']}: {row['status']}", flush=True)
    if failed:
        raise RuntimeError(f"Rights provenance readiness failed strict checks: {failed}")

    print("[5/6] Packaging source inventory and V2 priority queue...", flush=True)
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"{OUTPUT_PREFIX}_{season_label}_{stamp}"
    zip_path = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_rights_provenance_export_") as tmpdir:
        export_root = Path(tmpdir) / export_id
        export_root.mkdir(parents=True, exist_ok=True)

        write_csv(export_root / "rights_provenance_source_inventory.csv", source_rows(sources))
        write_csv(export_root / "rights_provenance_candidate_coverage.csv", coverage)
        write_csv(export_root / "rights_provenance_priority_queue.csv", coverage)
        write_csv(export_root / "rights_provenance_checks.csv", checks)

        summary_out = {
            "version": RUNNER_VERSION,
            "season_label": season_label,
            "input_population_zip": str(population_zip),
            "input_population_zip_sha256": sha256(population_zip),
            "input_population_version": population_version,
            "input_population_preview_fingerprint": clean(summary.get("preview_fingerprint")),
            "checkpoint_path": str(checkpoint_path) if checkpoint_path else "",
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_path": str(overlay_path),
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "unresolved_count": len(unresolved_ids),
            "relevant_source_count": len(sources),
            "strong_transaction_source_count": len(strong_sources),
            "partial_transaction_source_count": len(partial_sources),
            "salary_source_count": len(salary_sources),
            "players_with_strong_transaction_source": covered_strong,
            "players_with_partial_only_transaction_source": covered_partial,
            "players_with_salary_source": covered_salary,
            "players_with_no_local_provenance_hit": no_local,
            "classification_changes_performed": 0,
            "overlay_write_performed": False,
            "checkpoint_write_performed": False,
            "failed_checks": failed,
            "passed": not failed,
        }
        (export_root / "rights_provenance_summary.json").write_text(
            json.dumps(summary_out, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export_root.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    print("[6/6] Rechecking durable-state fingerprints after export...", flush=True)
    final_checkpoint_hash = sha256(checkpoint_path) if checkpoint_path else ""
    final_overlay_hash = sha256(overlay_path)
    if final_checkpoint_hash != checkpoint_before:
        raise RuntimeError("Checkpoint changed during provenance readiness scan.")
    if final_overlay_hash != overlay_before:
        raise RuntimeError("Rights overlay changed during provenance readiness scan.")

    print("", flush=True)
    print("=" * 124, flush=True)
    print("FREE AGENCY RIGHTS PROVENANCE READINESS V2 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Audit ZIP: {zip_path}", flush=True)
    print(f"Audit ZIP SHA256: {sha256(zip_path)}", flush=True)
    print("Classification changes: 0", flush=True)
    print("Runtime rights overlay write: NOT PERFORMED", flush=True)
    print("Canonical checkpoint write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
