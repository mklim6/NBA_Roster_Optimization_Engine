from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-average-player-salary-readiness-v1-2026-08-14"
TARGET_PRIOR_SEASON = "2025-26"
CURRENT_SEASON = "2026-27"
TEAM_COUNT = 30
CBA_AVERAGE_ROSTER_FACTOR = 13.2
CBA_DENOMINATOR = TEAM_COUNT * CBA_AVERAGE_ROSTER_FACTOR  # 396.0

STRUCTURED_EXTENSIONS = {".csv", ".parquet", ".json", ".jsonl"}
TEXT_EXTENSIONS = {".py", ".txt", ".md", ".yaml", ".yml", ".toml"}
SCAN_DIRS = ("data", "evidence", "outputs", "src")

EXCLUDED_TOKENS = (
    "\\backups\\", "/backups/",
    "\\.git\\", "/.git/",
    "\\.venv\\", "/.venv/",
    "\\site-packages\\", "/site-packages/",
    "\\outputs\\audits\\", "/outputs/audits/",
    "\\.farrv2\\", "/.farrv2/",
    "\\.fav1r", "/.fav1r",
)

AVERAGE_ALIASES = {
    "average_player_salary",
    "prior_average_player_salary",
    "nba_average_player_salary",
}
ESTIMATED_AVERAGE_ALIASES = {
    "estimated_average_player_salary",
}
TOTAL_SALARIES_ALIASES = {
    "total_salaries",
    "league_total_salaries",
    "nba_total_salaries",
}
ESTIMATED_TOTAL_SALARIES_ALIASES = {
    "estimated_total_salaries",
    "league_estimated_total_salaries",
    "nba_estimated_total_salaries",
}

SEASON_ALIASES = {
    "season", "season_label", "salary_cap_year", "league_year", "year",
}

def clean(value: Any) -> str:
    return str(value or "").strip()

def norm_col(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")

def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def finite_positive(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number

def path_excluded(path: Path) -> bool:
    text = str(path).lower()
    return any(token.lower() in text for token in EXCLUDED_TOKENS)

def season_is_2025_26(value: Any) -> bool:
    text = clean(value).lower().replace("_", "-").replace("/", "-")
    if text in {"2025-26", "2025-2026", "2025", "25-26"}:
        return True
    return "2025-26" in text or "2025_26" in clean(value).lower()

def filename_has_2025_26(path: Path) -> bool:
    text = path.name.lower()
    return "2025-26" in text or "2025_26" in text or "2025to26" in text

def csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                cols = [clean(c) for c in (reader.fieldnames or []) if clean(c)]
                return cols, list(reader)
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
        if path.suffix.lower() == ".jsonl":
            rows = []
            with path.open("r", encoding="utf-8-sig") as handle:
                for line in handle:
                    if line.strip():
                        value = json.loads(line)
                        if isinstance(value, Mapping):
                            rows.append(dict(value))
            cols = sorted({str(k) for row in rows for k in row})
            return cols, rows

        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(obj, list):
            rows = [dict(row) for row in obj if isinstance(row, Mapping)]
            cols = sorted({str(k) for row in rows for k in row})
            return cols, rows

        if isinstance(obj, Mapping):
            rows = [dict(obj)]
            for key in ("rows", "records", "data", "values"):
                if isinstance(obj.get(key), list):
                    rows = [dict(row) for row in obj[key] if isinstance(row, Mapping)]
                    break
            cols = sorted({str(k) for row in rows for k in row})
            return cols, rows
    except Exception:
        pass
    return [], []

def load_structured(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if path.suffix.lower() == ".csv":
        return csv_rows(path)
    if path.suffix.lower() == ".parquet":
        return parquet_rows(path)
    if path.suffix.lower() in {".json", ".jsonl"}:
        return json_rows(path)
    return [], []

def field(columns: list[str], aliases: set[str]) -> str:
    normalized = {norm_col(c): c for c in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return ""

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

def rights_overlay_path(root: Path) -> Path:
    return root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"

def find_final_registry_preview(root: Path) -> Path:
    candidates = [
        path
        for path in root.rglob("fa_rights_registry_v2_preview_2026-27_*.zip")
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError(
            "Could not locate fa_rights_registry_v2_preview_2026-27_*.zip."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_final_summary(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        member = next(
            name for name in archive.namelist()
            if name.endswith("final_rights_summary.json")
        )
        return json.loads(archive.read(member).decode("utf-8-sig"))

def main() -> int:
    root = Path.cwd().resolve()
    final_registry_zip = find_final_registry_preview(root)
    final_summary = read_final_summary(final_registry_zip)

    checkpoint = checkpoint_path(root)
    overlay = rights_overlay_path(root)
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 118, flush=True)
    print("2025-26 AVERAGE PLAYER SALARY EVIDENCE READINESS V1", flush=True)
    print("=" * 118, flush=True)
    print(f"Final rights preview: {final_registry_zip}", flush=True)
    print(f"CBA denominator: {TEAM_COUNT} teams x {CBA_AVERAGE_ROSTER_FACTOR} = {CBA_DENOMINATOR}", flush=True)
    print("Read-only scan. No salary constant, rights overlay, or checkpoint will be written.", flush=True)
    print("", flush=True)

    structured_candidates: list[dict[str, Any]] = []
    text_candidates: list[dict[str, Any]] = []
    files_scanned = 0

    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue

        for path in base.rglob("*"):
            if not path.is_file() or path_excluded(path):
                continue

            suffix = path.suffix.lower()

            if suffix in STRUCTURED_EXTENSIONS:
                files_scanned += 1
                columns, rows = load_structured(path)
                if not columns or not rows:
                    continue

                season_col = field(columns, SEASON_ALIASES)
                avg_col = field(columns, AVERAGE_ALIASES)
                est_avg_col = field(columns, ESTIMATED_AVERAGE_ALIASES)
                total_col = field(columns, TOTAL_SALARIES_ALIASES)
                est_total_col = field(columns, ESTIMATED_TOTAL_SALARIES_ALIASES)

                if not any((avg_col, est_avg_col, total_col, est_total_col)):
                    continue

                for row_index, row in enumerate(rows):
                    season_match = (
                        season_is_2025_26(row.get(season_col))
                        if season_col
                        else filename_has_2025_26(path)
                    )

                    for evidence_kind, column in (
                        ("average_player_salary", avg_col),
                        ("estimated_average_player_salary", est_avg_col),
                        ("total_salaries", total_col),
                        ("estimated_total_salaries", est_total_col),
                    ):
                        if not column:
                            continue
                        raw = row.get(column)
                        value = finite_positive(raw)
                        if value is None:
                            continue

                        derived_average = None
                        if evidence_kind in {"total_salaries", "estimated_total_salaries"}:
                            derived_average = value / CBA_DENOMINATOR
                        elif evidence_kind == "average_player_salary":
                            derived_average = value

                        if evidence_kind == "estimated_average_player_salary":
                            # This is a different CBA defined term. It cannot be
                            # substituted for prior-year Average Player Salary.
                            admissibility = "not_admissible_different_cba_term"
                        elif not season_match:
                            admissibility = "manual_review_season_not_proven_2025_26"
                        elif evidence_kind == "average_player_salary":
                            admissibility = "strong_explicit_2025_26_average"
                        elif evidence_kind == "total_salaries":
                            admissibility = "strong_if_leaguewide_total_salaries"
                        else:
                            admissibility = "strong_if_interim_audit_estimated_total_salaries"

                        structured_candidates.append({
                            "path": str(path.resolve()),
                            "row_index": row_index,
                            "season_column": season_col,
                            "season_value": clean(row.get(season_col)) if season_col else "",
                            "season_match_2025_26": season_match,
                            "evidence_kind": evidence_kind,
                            "evidence_column": column,
                            "raw_value": raw,
                            "numeric_value": value,
                            "derived_average_player_salary": derived_average,
                            "cba_denominator": CBA_DENOMINATOR if derived_average is not None else "",
                            "admissibility": admissibility,
                            "source_sha256": sha256_file(path),
                        })

            elif suffix in TEXT_EXTENSIONS:
                files_scanned += 1
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                lowered = text.lower()
                if not any(
                    token in lowered
                    for token in (
                        "average_player_salary",
                        "average player salary",
                        "estimated_total_salaries",
                        "estimated total salaries",
                        "total_salaries",
                        "total salaries",
                    )
                ):
                    continue

                for line_number, line in enumerate(text.splitlines(), start=1):
                    norm = line.lower()
                    if not any(
                        token in norm
                        for token in (
                            "average_player_salary",
                            "average player salary",
                            "estimated_total_salaries",
                            "estimated total salaries",
                            "total_salaries",
                            "total salaries",
                        )
                    ):
                        continue
                    if len(line.strip()) > 1000:
                        continue

                    numbers = re.findall(
                        r"(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?",
                        line,
                    )
                    text_candidates.append({
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "line_text": line.strip(),
                        "numeric_tokens": "|".join(numbers),
                        "contains_2025_26": (
                            "2025-26" in line
                            or "2025_26" in line
                            or filename_has_2025_26(path)
                        ),
                        "source_sha256": sha256_file(path),
                    })

    admissible = [
        row for row in structured_candidates
        if row["admissibility"] in {
            "strong_explicit_2025_26_average",
            "strong_if_leaguewide_total_salaries",
            "strong_if_interim_audit_estimated_total_salaries",
        }
    ]

    exact_average_candidates = sorted({
        round(float(row["derived_average_player_salary"]), 6)
        for row in admissible
        if row["derived_average_player_salary"] is not None
    })

    # Do not auto-select a league total unless it is the only candidate and
    # the source itself explicitly establishes the semantics.
    auto_selected = None
    auto_selected_status = "none"
    explicit_average_rows = [
        row for row in admissible
        if row["admissibility"] == "strong_explicit_2025_26_average"
    ]
    if len({
        round(float(row["derived_average_player_salary"]), 6)
        for row in explicit_average_rows
    }) == 1 and explicit_average_rows:
        auto_selected = float(explicit_average_rows[0]["derived_average_player_salary"])
        auto_selected_status = "explicit_2025_26_average_player_salary"
    else:
        interim_rows = [
            row for row in admissible
            if row["admissibility"] == "strong_if_interim_audit_estimated_total_salaries"
            and "interim" in row["path"].lower()
            and "audit" in row["path"].lower()
        ]
        interim_values = {
            round(float(row["derived_average_player_salary"]), 6)
            for row in interim_rows
        }
        if len(interim_values) == 1 and interim_rows:
            auto_selected = float(interim_rows[0]["derived_average_player_salary"])
            auto_selected_status = "interim_audit_estimated_total_salaries"

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []
    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("[1/3] Validating rights-registry prerequisite...", flush=True)
    check(
        "final_registry_preview_passed",
        bool(final_summary.get("passed")),
        "Average-salary work begins only after the final 187-player registry preview passes.",
    )
    check(
        "final_registry_has_16_early_bird_rows",
        int(final_summary.get("rights_classification_counts", {}).get("early_bird", -1)) == 16,
        "Expected 16 Early Bird rows.",
    )
    check(
        "all_16_prior_regular_salaries_are_already_resolved",
        int(final_summary.get("salary_resolved_candidate_count", -1))
        == int(final_summary.get("salary_dependent_candidate_count", -2))
        == 106,
        "The remaining issue is leaguewide Average Player Salary only.",
    )

    print("[2/3] Validating CBA evidence handling...", flush=True)
    check(
        "cba_denominator_is_396",
        math.isclose(CBA_DENOMINATOR, 396.0),
        "30 non-expansion teams x 13.2.",
    )
    check(
        "estimated_average_player_salary_is_never_used_as_prior_average",
        all(
            row["admissibility"] == "not_admissible_different_cba_term"
            for row in structured_candidates
            if row["evidence_kind"] == "estimated_average_player_salary"
        ),
        "CBA Estimated Average Player Salary is a distinct defined term.",
    )
    check(
        "auto_selection_requires_explicit_average_or_interim_audit_total",
        auto_selected is None
        or auto_selected_status in {
            "explicit_2025_26_average_player_salary",
            "interim_audit_estimated_total_salaries",
        },
        f"auto_selected_status={auto_selected_status}",
    )

    print("[3/3] Verifying read-only safety...", flush=True)
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        f"checkpoint={checkpoint_after}",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        f"overlay={overlay_after or '<absent>'}",
    )

    failed = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Average Player Salary readiness V1 failed strict checks: "
            + ", ".join(failed)
        )

    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_average_player_salary_readiness_v1_{CURRENT_SEASON}_{stamp}"
    zip_out = out_dir / f"{export_id}.zip"

    def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    with tempfile.TemporaryDirectory(prefix="faaps_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "average_salary_structured_candidates.csv", structured_candidates)
        write_csv(export / "average_salary_text_candidates.csv", text_candidates)
        write_csv(export / "average_salary_checks.csv", checks)

        summary = {
            "version": VERSION,
            "current_season": CURRENT_SEASON,
            "target_prior_season": TARGET_PRIOR_SEASON,
            "files_scanned": files_scanned,
            "structured_candidate_count": len(structured_candidates),
            "text_candidate_count": len(text_candidates),
            "admissible_structured_candidate_count": len(admissible),
            "distinct_derived_average_candidates": exact_average_candidates,
            "auto_selected_prior_average_player_salary": auto_selected,
            "auto_selected_status": auto_selected_status,
            "ready_for_early_bird_engine_patch": auto_selected is not None,
            "cba_formula": {
                "average_player_salary": (
                    "Total Salaries / (number of non-expansion Teams x 13.2)"
                ),
                "team_count": TEAM_COUNT,
                "roster_factor": CBA_AVERAGE_ROSTER_FACTOR,
                "denominator": CBA_DENOMINATOR,
                "interim_rule": (
                    "If the prior-year Audit Report is not completed, substitute "
                    "Estimated Total Salaries from the Interim Audit Report."
                ),
            },
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "failed_strict_checks": failed,
            "passed": not failed,
        }
        (export / "average_salary_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    print("", flush=True)
    print("=" * 118, flush=True)
    print("2025-26 AVERAGE PLAYER SALARY EVIDENCE READINESS V1 PASSED", flush=True)
    print("=" * 118, flush=True)
    print(f"Files scanned: {files_scanned}", flush=True)
    print(f"Structured candidates: {len(structured_candidates)}", flush=True)
    print(f"Admissible candidates: {len(admissible)}", flush=True)
    print(f"Auto-selected APS: {auto_selected if auto_selected is not None else 'NONE'}", flush=True)
    print(f"Ready for Early Bird patch: {'YES' if auto_selected is not None else 'NO'}", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
