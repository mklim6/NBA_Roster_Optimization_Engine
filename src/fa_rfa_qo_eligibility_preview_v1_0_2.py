from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "fa-rfa-qo-eligibility-preview-v1.0.2-2026-08-14"
SEASON_LABEL = "2026-27"
TARGET_PRIOR_SEASON = "2025-26"

OFFICIAL_2026_TWO_WAY_RFA_SOURCE = (
    "https://www.nba.com/news/2026-free-agency-options-and-qualifying-offers"
)

# NBA.com lists these players as Restricted in its 2026 Two-Way free-agent
# section. We use that post-split outcome ONLY as affirmative evidence that the
# pre-split 15-day Active/Inactive List prerequisite was satisfied. We do not
# import the real-world QO decision or RFA market state into the simulator.
OFFICIAL_2026_TWO_WAY_RESTRICTED = {
    "Brooks Barnhizer",
    "Koby Brea",
    "Moussa Cisse",
    "Isaiah Crawford",
    "Hunter Dickinson",
    "Enrique Freeman",
    "Vladislav Goldin",
    "Harrison Ingram",
    "David Jones Garcia",
    "Chris Mañon",
    "Alijah Martin",
    "Daeqwon Plowden",
    "Jalen Slawson",
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
SEASON_ALIASES = {
    "season", "season_label", "season_id", "year",
}
GP_ALIASES = {
    "gp", "games_played", "games", "g",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def norm_col(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def norm_name(value: Any) -> str:
    text = clean(value).lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def names_equivalent(a: str, b: str) -> bool:
    na = norm_name(a)
    nb = norm_name(b)
    if na == nb:
        return True
    suffixes = (" jr", " sr", " ii", " iii", " iv", " v")
    for suffix in suffixes:
        if na.endswith(suffix):
            na = na[:-len(suffix)]
        if nb.endswith(suffix):
            nb = nb[:-len(suffix)]
    return na == nb


def finite_nonnegative_int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def season_is_2025_26(value: Any) -> bool:
    text = clean(value).lower().replace("_", "-").replace("/", "-")
    if text in {"2025-26", "2025-2026", "25-26"}:
        return True
    # Common NBA stats season IDs are sometimes 2025.
    if text == "2025":
        return True
    return "2025-26" in text or "2025_26" in clean(value).lower()


def filename_is_2025_26(path: Path) -> bool:
    text = path.name.lower()
    return (
        "2025-26" in text
        or "2025_26" in text
        or "2025to26" in text
        or "2026" in text
    )


def path_excluded(path: Path) -> bool:
    text = str(path).lower()
    return any(token.lower() in text for token in EXCLUDED_TOKENS)


def field(columns: list[str], aliases: set[str]) -> str:
    normalized = {norm_col(column): column for column in columns}
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

        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, list):
            rows = [dict(row) for row in value if isinstance(row, Mapping)]
            cols = sorted({str(k) for row in rows for k in row})
            return cols, rows

        if isinstance(value, Mapping):
            for key in ("rows", "records", "data", "values"):
                nested = value.get(key)
                if isinstance(nested, list):
                    rows = [
                        dict(row) for row in nested
                        if isinstance(row, Mapping)
                    ]
                    cols = sorted({str(k) for row in rows for k in row})
                    return cols, rows
            return list(value.keys()), [dict(value)]
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


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [
        path for path in root.rglob(pattern)
        if path.is_file()
    ]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> list[dict[str, str]]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> dict[str, Any]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return (
            root
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        )


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


def collect_gp_evidence(
    root: Path,
    two_way_rows: list[dict[str, Any]],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    int,
]:
    target_ids = {
        pid(row.get("player_id"))
        for row in two_way_rows
    }
    target_names = {
        norm_name(row.get("player_name")): pid(row.get("player_id"))
        for row in two_way_rows
    }

    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_files: list[dict[str, Any]] = []
    files_scanned = 0

    for dirname in SCAN_DIRS:
        base = root / dirname
        if not base.exists():
            continue

        for path in base.rglob("*"):
            if (
                not path.is_file()
                or path_excluded(path)
                or path.suffix.lower() not in STRUCTURED_EXTENSIONS
            ):
                continue

            files_scanned += 1
            columns, rows = load_structured(path)
            if not columns or not rows:
                continue

            gp_col = field(columns, GP_ALIASES)
            if not gp_col:
                continue

            id_col = field(columns, PLAYER_ID_ALIASES)
            name_col = field(columns, PLAYER_NAME_ALIASES)
            season_col = field(columns, SEASON_ALIASES)

            if not id_col and not name_col:
                continue

            matches = 0

            for row_index, raw in enumerate(rows):
                if season_col:
                    if not season_is_2025_26(raw.get(season_col)):
                        continue
                elif not filename_is_2025_26(path):
                    continue

                player_id = ""
                if id_col:
                    candidate_id = pid(raw.get(id_col))
                    if candidate_id in target_ids:
                        player_id = candidate_id

                if not player_id and name_col:
                    candidate_name = norm_name(raw.get(name_col))
                    if candidate_name in target_names:
                        player_id = target_names[candidate_name]

                if not player_id:
                    continue

                gp = finite_nonnegative_int(raw.get(gp_col))
                if gp is None:
                    continue

                matches += 1
                evidence[player_id].append({
                    "player_id": player_id,
                    "path": str(path.resolve()),
                    "row_index": row_index,
                    "season_column": season_col,
                    "season_value": clean(raw.get(season_col)) if season_col else "",
                    "player_id_column": id_col,
                    "player_name_column": name_col,
                    "gp_column": gp_col,
                    "games_played": gp,
                    "source_sha256": sha256_file(path),
                })

            if matches:
                candidate_files.append({
                    "path": str(path.resolve()),
                    "match_count": matches,
                    "gp_column": gp_col,
                    "player_id_column": id_col,
                    "player_name_column": name_col,
                    "season_column": season_col,
                    "source_sha256": sha256_file(path),
                })

    return evidence, candidate_files, files_scanned


def main() -> int:
    root = Path.cwd().resolve()

    previous_zip = find_latest(
        root,
        "fa_rfa_qo_eligibility_preview_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(previous_zip) as archive:
        previous_summary = read_json_member(
            archive,
            "rfa_qo_summary.json",
        )
        previous_rows = read_csv_member(
            archive,
            "rfa_qo_eligibility_all.csv",
        )
        previous_manifest = read_csv_member(
            archive,
            "rfa_qo_contract_source_manifest.csv",
        )

    checkpoint = checkpoint_path(root)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    two_way_rows = [
        row for row in previous_rows
        if clean(row.get("eligibility_path"))
        == "completing_two_way_contract"
    ]

    print("=" * 122, flush=True)
    print("2026 RFA + QO ELIGIBILITY PREVIEW V1.0.2 HOTFIX", flush=True)
    print("=" * 122, flush=True)
    print(f"Input preview: {previous_zip}", flush=True)
    print(f"Two-Way rows requiring 15-day gate: {len(two_way_rows)}", flush=True)
    print("", flush=True)
    print(
        "Rule hotfix: completing a Two-Way Contract alone is NOT sufficient. "
        "The 15-day NBA Active/Inactive List condition must be affirmatively proven.",
        flush=True,
    )
    print("", flush=True)

    print("Scanning local 2025-26 player data for conservative GP evidence...", flush=True)
    gp_evidence, gp_files, files_scanned = collect_gp_evidence(
        root,
        two_way_rows,
    )

    print(f"Structured data files scanned: {files_scanned}", flush=True)
    print(f"Files with matching GP evidence: {len(gp_files)}", flush=True)

    output_rows: list[dict[str, Any]] = []
    two_way_evidence_rows: list[dict[str, Any]] = []

    for row in previous_rows:
        updated = dict(row)
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        path = clean(row.get("eligibility_path"))

        updated["v1_0_1_rule_reviewed"] = True
        updated["two_way_15_day_requirement"] = (
            path == "completing_two_way_contract"
        )
        updated["two_way_15_day_status"] = "not_applicable"
        updated["two_way_15_day_evidence_kind"] = ""
        updated["two_way_15_day_evidence_value"] = ""
        updated["two_way_15_day_evidence_source"] = ""
        updated["two_way_real_world_qo_state_imported"] = False

        if path != "completing_two_way_contract":
            output_rows.append(updated)
            continue

        candidates = gp_evidence.get(player_id, [])
        max_gp = max(
            (
                finite_nonnegative_int(item.get("games_played")) or 0
                for item in candidates
            ),
            default=0,
        )

        official_affirmative = (
            player_name in OFFICIAL_2026_TWO_WAY_RESTRICTED
        )

        if max_gp >= 15:
            updated["eligibility_status"] = "eligible_if_qo_issued"
            updated["eligibility_path"] = (
                "completing_two_way_contract_15_day_gp_proven"
            )
            updated["two_way_15_day_status"] = "proven"
            updated["two_way_15_day_evidence_kind"] = (
                "2025_26_nba_games_played_sufficient_active_list_days"
            )
            updated["two_way_15_day_evidence_value"] = max_gp

            max_sources = [
                item for item in candidates
                if finite_nonnegative_int(item.get("games_played")) == max_gp
            ]
            updated["two_way_15_day_evidence_source"] = "|".join(
                sorted({
                    clean(item.get("path"))
                    for item in max_sources
                    if clean(item.get("path"))
                })
            )
            updated["reason"] = (
                "Player finished on a Two-Way Contract and local 2025-26 "
                f"NBA data records {max_gp} games played. Playing in at "
                "least 15 distinct NBA games is sufficient proof of at "
                "least 15 Active List days."
            )

        elif official_affirmative:
            updated["eligibility_status"] = "eligible_if_qo_issued"
            updated["eligibility_path"] = (
                "completing_two_way_contract_15_day_official_rfa_proven"
            )
            updated["two_way_15_day_status"] = "proven"
            updated["two_way_15_day_evidence_kind"] = (
                "official_2026_nba_rfa_status_implies_pre_split_15_day_gate"
            )
            updated["two_way_15_day_evidence_value"] = "affirmative"
            updated["two_way_15_day_evidence_source"] = (
                OFFICIAL_2026_TWO_WAY_RFA_SOURCE
            )
            updated["reason"] = (
                "NBA.com's official 2026 Two-Way free-agent list identifies "
                "this player as Restricted. That post-split outcome is used "
                "only as affirmative proof that the pre-split 15-day "
                "Active/Inactive List prerequisite was satisfied. The actual "
                "real-world QO/RFA decision is not imported into the simulator."
            )

        else:
            updated["eligibility_status"] = "manual_review"
            updated["eligibility_path"] = (
                "completing_two_way_contract_15_day_evidence_required"
            )
            updated["two_way_15_day_status"] = "unresolved"
            updated["two_way_15_day_evidence_kind"] = (
                "insufficient_affirmative_active_inactive_list_evidence"
            )
            updated["two_way_15_day_evidence_value"] = (
                max_gp if candidates else ""
            )
            updated["two_way_15_day_evidence_source"] = "|".join(
                sorted({
                    clean(item.get("path"))
                    for item in candidates
                    if clean(item.get("path"))
                })
            )
            updated["reason"] = (
                "Player finished on a Two-Way Contract, but the required "
                "15 NBA Active/Inactive List days are not affirmatively "
                "proven. Fewer than 15 games played cannot prove ineligibility "
                "because Inactive List days also count. Fail closed to manual review."
            )

        output_rows.append(updated)

        two_way_evidence_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_eligibility_status": clean(row.get("eligibility_status")),
            "updated_eligibility_status": updated["eligibility_status"],
            "updated_eligibility_path": updated["eligibility_path"],
            "max_local_2025_26_games_played": max_gp if candidates else "",
            "local_gp_evidence_row_count": len(candidates),
            "official_2026_restricted_two_way_affirmative": official_affirmative,
            "official_source": (
                OFFICIAL_2026_TWO_WAY_RFA_SOURCE
                if official_affirmative
                else ""
            ),
            "post_split_qo_decision_imported": False,
            "two_way_15_day_status": updated["two_way_15_day_status"],
            "evidence_kind": updated["two_way_15_day_evidence_kind"],
            "evidence_source": updated["two_way_15_day_evidence_source"],
        })

    eligible_rows = [
        row for row in output_rows
        if clean(row.get("eligibility_status"))
        == "eligible_if_qo_issued"
    ]
    manual_rows = [
        row for row in output_rows
        if clean(row.get("eligibility_status"))
        == "manual_review"
    ]
    not_eligible_rows = [
        row for row in output_rows
        if clean(row.get("eligibility_status"))
        == "not_eligible"
    ]

    missing_contract_rows = [
        row for row in previous_manifest
        if clean(row.get("fetch_state"))
        != "verified_contract_page"
    ]

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("", flush=True)
    print("Running strict V1.0.2 checks...", flush=True)

    check(
        "v1_preview_passed_strict_checks",
        bool(previous_summary.get("passed")),
        "Hotfix starts from passed V1 preview.",
    )
    check(
        "exact_187_player_universe_preserved",
        len(output_rows) == 187
        and len({pid(row.get("player_id")) for row in output_rows}) == 187,
        "No free agent added or omitted.",
    )
    check(
        "all_69_two_way_rows_re_evaluated",
        len(two_way_evidence_rows) == 69,
        f"reviewed={len(two_way_evidence_rows)}",
    )
    check(
        "two_way_auto_eligibility_requires_affirmative_15_day_proof",
        all(
            clean(row.get("two_way_15_day_status")) == "proven"
            for row in output_rows
            if clean(row.get("eligibility_status")) == "eligible_if_qo_issued"
            and clean(row.get("latest_contract_type")).lower().find("two-way") >= 0
        ),
        "No Two-Way finisher remains auto-eligible from contract type alone.",
    )
    check(
        "unproven_two_way_15_day_cases_fail_closed",
        all(
            clean(row.get("eligibility_status")) == "manual_review"
            for row in output_rows
            if clean(row.get("two_way_15_day_status")) == "unresolved"
        ),
        "Unresolved 15-day evidence is manual, never auto-eligible or auto-ineligible.",
    )
    check(
        "official_post_split_evidence_never_imports_qo_state",
        all(
            not bool(row.get("post_split_qo_decision_imported"))
            for row in two_way_evidence_rows
        )
        and all(
            not bool(row.get("two_way_real_world_qo_state_imported"))
            for row in output_rows
        ),
        "NBA.com post-split list is used only to prove a pre-split prerequisite.",
    )
    check(
        "non_two_way_v1_dispositions_are_preserved",
        all(
            clean(new.get("eligibility_status"))
            == clean(old.get("eligibility_status"))
            and clean(new.get("eligibility_path"))
            == clean(old.get("eligibility_path"))
            for old, new in zip(previous_rows, output_rows)
            if clean(old.get("eligibility_path"))
            != "completing_two_way_contract"
        ),
        "Rookie-scale and ordinary <=3 YOS results are unchanged.",
    )
    check(
        "no_qo_or_rfa_state_is_applied",
        all(
            clean(row.get("qualifying_offer_issued")).lower() != "true"
            and clean(row.get("rfa_status_applied")).lower() != "true"
            and clean(row.get("offer_sheet_created")).lower() != "true"
            and clean(row.get("right_of_first_refusal_created")).lower() != "true"
            for row in output_rows
        ),
        "Eligibility only. No market state imported.",
    )
    missing_contract_names = {
        clean(row.get("player_name"))
        for row in missing_contract_rows
    }
    missing_contract_resolutions = [
        row for row in output_rows
        if clean(row.get("player_name")) in missing_contract_names
    ]

    check(
        "contract_page_misses_require_manual_or_independent_two_way_proof",
        all(
            (
                clean(row.get("eligibility_status")) == "manual_review"
            )
            or (
                clean(row.get("eligibility_status")) == "eligible_if_qo_issued"
                and "two-way" in clean(row.get("latest_contract_type")).lower()
                and clean(row.get("two_way_15_day_status")) == "proven"
                and clean(row.get("eligibility_path")) in {
                    "completing_two_way_contract_15_day_gp_proven",
                    "completing_two_way_contract_15_day_official_rfa_proven",
                }
                and bool(clean(row.get("two_way_15_day_evidence_source")))
            )
            for row in missing_contract_resolutions
        ),
        (
            "A supplemental contract-page miss may remain automatic only when "
            "the existing Two-Way contract classification is present and the "
            "15-day prerequisite is independently proven. Otherwise it must "
            "remain manual review."
        ),
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

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "RFA/QO Eligibility Preview V1.0.2 failed strict checks: "
            + ", ".join(failed)
        )

    status_counts = Counter(
        clean(row.get("eligibility_status"))
        for row in output_rows
    )
    path_counts = Counter(
        clean(row.get("eligibility_path"))
        for row in output_rows
    )

    two_way_proven = sum(
        clean(row.get("two_way_15_day_status")) == "proven"
        for row in output_rows
        if bool(row.get("two_way_15_day_requirement"))
    )
    two_way_manual = sum(
        clean(row.get("two_way_15_day_status")) == "unresolved"
        for row in output_rows
        if bool(row.get("two_way_15_day_requirement"))
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_rfa_qo_eligibility_preview_v1_0_2_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="farfaqo101_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "rfa_qo_eligibility_all_v1_0_1.csv",
            output_rows,
        )
        write_csv(
            export / "rfa_qo_eligible_if_qo_issued_v1_0_1.csv",
            eligible_rows,
        )
        write_csv(
            export / "rfa_qo_manual_review_v1_0_1.csv",
            manual_rows,
        )
        write_csv(
            export / "rfa_qo_not_eligible_v1_0_1.csv",
            not_eligible_rows,
        )
        write_csv(
            export / "rfa_qo_two_way_15_day_evidence.csv",
            two_way_evidence_rows,
        )
        write_csv(
            export / "rfa_qo_gp_evidence_files.csv",
            gp_files,
        )
        write_csv(
            export / "rfa_qo_previous_contract_page_misses.csv",
            missing_contract_rows,
        )
        write_csv(
            export / "rfa_qo_contract_page_miss_resolutions.csv",
            missing_contract_resolutions,
        )
        write_csv(
            export / "rfa_qo_checks_v1_0_2.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "input_preview_zip": str(previous_zip),
            "input_preview_sha256": sha256_file(previous_zip),
            "total_free_agents": len(output_rows),
            "eligibility_status_counts": dict(sorted(status_counts.items())),
            "eligibility_path_counts": dict(sorted(path_counts.items())),
            "eligible_if_qo_issued_count": len(eligible_rows),
            "manual_review_count": len(manual_rows),
            "not_eligible_count": len(not_eligible_rows),
            "two_way_rows_reviewed": len(two_way_evidence_rows),
            "two_way_15_day_proven_count": two_way_proven,
            "two_way_15_day_manual_count": two_way_manual,
            "structured_data_files_scanned": files_scanned,
            "gp_evidence_file_count": len(gp_files),
            "prior_contract_page_miss_count": len(missing_contract_rows),
            "qualifying_offer_issued_count": 0,
            "rfa_status_applied_count": 0,
            "real_world_qo_decisions_imported": 0,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "state_mutation_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Build exact QO amount readiness only for V1.0.1 proven "
                "eligible players. Keep unresolved Two-Way 15-day cases "
                "outside the automatic QO decision set."
            ),
        }

        (
            export / "rfa_qo_summary_v1_0_1.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """RFA + QO ELIGIBILITY PREVIEW V1.0.1
===================================

Hotfix:
V1 treated every verified Two-Way finisher as structurally QO-eligible.
That was too permissive.

Current NBA guidance requires the player coming off a Two-Way Contract to
have been on the NBA team Active or Inactive List for at least 15 regular
season days before the QO can create RFA status.

V1.0.1 therefore requires affirmative 15-day evidence.

Accepted affirmative evidence:
1. Local 2025-26 NBA games played >= 15.
   Playing in 15 NBA games is sufficient proof of at least 15 Active List days.

2. Official NBA.com 2026 Two-Way RFA status.
   If NBA.com identifies the player as Restricted, the 15-day prerequisite
   necessarily occurred during the already-completed regular season.
   The actual post-split QO decision is NOT imported into the simulator.

Important:
Local GP < 15 is never treated as ineligible because Inactive List days also
count. Those cases stay manual until fuller Active/Inactive List evidence exists.

Safety:
- no QO issued
- no RFA status applied
- no real-world 2026 QO decision imported
- no rights overlay write
- no checkpoint write
"""
        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(
            zip_out,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after V1.0.1 export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after V1.0.1 export.")

    print("", flush=True)
    print("=" * 122, flush=True)
    print("2026 RFA + QO ELIGIBILITY PREVIEW V1.0.2 PASSED", flush=True)
    print("=" * 122, flush=True)
    print(f"Eligible if QO issued: {len(eligible_rows)}", flush=True)
    print(f"Manual review:         {len(manual_rows)}", flush=True)
    print(f"Not eligible:          {len(not_eligible_rows)}", flush=True)
    print(
        f"Two-Way 15-day proven: {two_way_proven}/{len(two_way_evidence_rows)}",
        flush=True,
    )
    print(
        f"Two-Way 15-day manual: {two_way_manual}",
        flush=True,
    )
    print("Qualifying Offers issued: 0", flush=True)
    print("RFA statuses applied:      0", flush=True)
    print("Real-world QO decisions imported: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
