from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pickle
import re
import tempfile
import zipfile
from collections import defaultdict, Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-non-rfa-evidence-gap-harvest-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)

EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_MARKET = 226
EXPECTED_NON_RFA = 162

DATE_FIELDS = (
    "signing_date",
    "transaction_date",
    "contract_date",
    "effective_date",
    "date",
)
SALARY_FIELDS_PRIORITY = (
    "prior_regular_salary",
    "prior_base_salary_numeric",
    "prior_base_salary",
    "salary_2025_26",
    "base_salary_2025_26",
    "2025_26_salary",
)
RIGHTS_SIGNAL_FIELDS = (
    "qualifying_season_count",
    "qualifying_seasons",
    "continuous_prior_seasons",
    "continuity_verified",
    "last_continuity_reset_season",
    "waiver_claim_seasons",
    "years_of_service",
    "final_contract_type",
    "contract_type",
    "signing_method",
    "signing_team",
    "transaction",
    "transaction_date",
    "transaction_date_text",
    "team_abbreviation",
    "team_name",
    "rights_acquired_marker",
    "rights_acquired_text",
    "terminal_kind",
)
SALARY_EXCLUDE_TOKENS = (
    "count", "evidence", "source", "status", "ready", "resolved",
    "resolution", "confidence", "manual", "flag", "method", "percent",
    "pct", "multiplier", "years_of_service", "yos",
)


def clean(v: Any) -> str:
    return str(v or "").strip()


def pid(v: Any) -> str:
    text = clean(v)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def fnum(v: Any) -> float | None:
    text = clean(v).replace("$", "").replace(",", "")
    try:
        x = float(text)
    except Exception:
        return None
    if not math.isfinite(x):
        return None
    return x


def parse_date(v: Any) -> date | None:
    text = clean(v)
    if not text:
        return None
    text = text[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(clean(v).replace("Z", "+00:00")).date()
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def find_latest(root: Path, pattern: str) -> Path | None:
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def read_csv_suffix(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    raw = z.read(name)
    if not raw.strip():
        return []
    return list(
        csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    )


def read_json_suffix(z: zipfile.ZipFile, suffix: str):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(name).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields, seen = [], set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def boolish(v: Any) -> bool:
    return clean(v).lower() in {"true", "1", "yes", "y", "t"}


def candidate_date(row: dict[str, Any]) -> tuple[date | None, str]:
    lowered = {clean(k).lower(): k for k in row}
    for preferred in DATE_FIELDS:
        key = lowered.get(preferred)
        if not key:
            continue
        parsed = parse_date(row.get(key))
        if parsed:
            return parsed, key
    return None, ""


def salary_field_candidates(row: dict[str, Any]) -> list[tuple[str, float]]:
    lowered = {clean(k).lower(): k for k in row}
    out = []

    # Explicit preferred fields first.
    for preferred in SALARY_FIELDS_PRIORITY:
        key = lowered.get(preferred)
        if not key:
            continue
        x = fnum(row.get(key))
        if x is not None and x > 0:
            out.append((key, x))

    # Then conservative generic prior/2025-26 salary fields.
    for key, value in row.items():
        lk = clean(key).lower()
        if any(token in lk for token in SALARY_EXCLUDE_TOKENS):
            continue
        if not (
            ("prior" in lk and "salary" in lk)
            or ("prior" in lk and "base" in lk)
            or ("2025" in lk and ("salary" in lk or "base" in lk))
        ):
            continue
        x = fnum(value)
        if x is not None and x > 0 and (key, x) not in out:
            out.append((key, x))

    return out


def rights_signal_snapshot(row: dict[str, Any]) -> dict[str, str]:
    lowered = {clean(k).lower(): k for k in row}
    result = {}
    for preferred in RIGHTS_SIGNAL_FIELDS:
        key = lowered.get(preferred)
        if key and clean(row.get(key)):
            result[preferred] = clean(row.get(key))
    return result


def evidence_useful(row: dict[str, Any]) -> bool:
    if salary_field_candidates(row):
        return True
    if rights_signal_snapshot(row):
        return True
    fields = {clean(k).lower() for k in row}
    return any(
        token in field
        for field in fields
        for token in ("transaction", "contract", "continuity", "qualifying")
    )


def source_priority(zip_name: str, member: str) -> int:
    text = f"{zip_name}::{member}".lower()

    if "owner_rights_reconciliation" in text:
        return -100
    if "rights_registry_v2_preview" in text:
        return 100
    if "rights_continuity_v2_preview" in text:
        return 98
    if "additional_lifecycle_targeted_resolution_and_final84" in text:
        return 96
    if "contract_option_lifecycle_readiness_v1_0_1" in text:
        return 94
    if "additional_lifecycle_contract_evidence_harvest_v1_0_1" in text:
        return 92
    if "post_split_roster_provenance" in text:
        return 85
    if "rights_external_evidence" in text:
        return 70
    if "rights_population" in text:
        return 45
    return 60


def main() -> int:
    root = Path.cwd().resolve()

    rec_zip = find_latest(
        root,
        "fa_full_market_owner_rights_reconciliation_v1_0_2_2026-27_*.zip",
    )
    if rec_zip is None:
        raise RuntimeError("Missing V1.0.2 owner/rights reconciliation audit.")

    with zipfile.ZipFile(rec_zip) as z:
        rec_summary = read_json_suffix(
            z, "owner_rights_reconciliation_summary.json"
        )
        rec_rows = read_csv_suffix(
            z, "full_market_owner_rights_reconciliation_226.csv"
        )
        top_salary_conflicts = read_csv_suffix(
            z, "prior_salary_conflicts.csv", required=False
        )

    if len(rec_rows) != EXPECTED_MARKET:
        raise RuntimeError(f"Expected 226 reconciliation rows, got {len(rec_rows)}.")

    non_rfa = [
        row for row in rec_rows
        if not boolish(row.get("exact_rfa_free_agent_amount_available"))
    ]
    if len(non_rfa) != EXPECTED_NON_RFA:
        raise RuntimeError(f"Expected 162 non-RFA rows, got {len(non_rfa)}.")

    rights_targets = {
        pid(row["player_id"]): row
        for row in non_rfa
        if not clean(row.get("reconciled_rights_classification"))
    }
    salary_targets = {
        pid(row["player_id"]): row
        for row in non_rfa
        if not clean(row.get("reconciled_prior_salary_evidence"))
    }
    non_rfa_ids = {pid(row["player_id"]) for row in non_rfa}
    salary_conflict_targets = {
        pid(row["player_id"]): row
        for row in top_salary_conflicts
        if pid(row.get("player_id")) in non_rfa_ids
    }

    target_ids = set(rights_targets) | set(salary_targets) | set(salary_conflict_targets)

    audit_dir = root / "outputs" / "audits"
    evidence_rows: list[dict[str, Any]] = []
    source_scan: list[dict[str, Any]] = []

    for zip_path in sorted(audit_dir.glob("*.zip")):
        lower_zip = zip_path.name.lower()
        if "owner_rights_reconciliation" in lower_zip:
            continue

        try:
            with zipfile.ZipFile(zip_path) as z:
                for member in z.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    priority = source_priority(zip_path.name, member)
                    if priority < 0:
                        continue
                    try:
                        raw = z.read(member)
                        if not raw.strip():
                            continue
                        rows = list(
                            csv.DictReader(
                                io.StringIO(
                                    raw.decode("utf-8-sig", errors="replace")
                                )
                            )
                        )
                    except Exception:
                        continue
                    if not rows or "player_id" not in rows[0]:
                        continue

                    matched = 0
                    useful_matched = 0
                    for row in rows:
                        player_id = pid(row.get("player_id"))
                        if player_id not in target_ids:
                            continue
                        matched += 1
                        if not evidence_useful(row):
                            continue
                        useful_matched += 1

                        dt, dt_field = candidate_date(row)
                        salary_candidates = salary_field_candidates(row)
                        rights_signals = rights_signal_snapshot(row)

                        base = {
                            "player_id": player_id,
                            "player_name": clean(
                                row.get("player_name")
                                or rec_rows[
                                    next(
                                        i for i, x in enumerate(rec_rows)
                                        if pid(x["player_id"]) == player_id
                                    )
                                ].get("player_name")
                            ),
                            "source_priority": priority,
                            "source_zip": zip_path.name,
                            "source_member": member,
                            "evidence_date": dt.isoformat() if dt else "",
                            "evidence_date_field": dt_field,
                            "is_pre_split": (
                                dt <= SPLIT_DATE if dt is not None else ""
                            ),
                            "rights_signal_snapshot": json.dumps(
                                rights_signals,
                                sort_keys=True,
                            ),
                        }

                        if salary_candidates:
                            for salary_field, amount in salary_candidates:
                                evidence_rows.append({
                                    **base,
                                    "evidence_kind": "salary",
                                    "salary_field": salary_field,
                                    "salary_amount": amount,
                                })
                        else:
                            evidence_rows.append({
                                **base,
                                "evidence_kind": "rights_or_contract_context",
                                "salary_field": "",
                                "salary_amount": "",
                            })

                    if matched:
                        source_scan.append({
                            "source_zip": zip_path.name,
                            "source_member": member,
                            "source_priority": priority,
                            "matched_target_rows": matched,
                            "useful_matched_rows": useful_matched,
                        })
        except Exception:
            continue

    # Latest-pre-split salary resolution.
    salary_resolution_rows = []
    salary_unresolved_rows = []

    for player_id in sorted(
        set(salary_targets) | set(salary_conflict_targets),
        key=lambda p: clean(
            (salary_targets.get(p) or salary_conflict_targets.get(p) or {}).get(
                "player_name"
            )
        ).lower(),
    ):
        base_row = salary_targets.get(player_id) or salary_conflict_targets[player_id]
        candidates = [
            row for row in evidence_rows
            if row["player_id"] == player_id
            and row["evidence_kind"] == "salary"
            and row["evidence_date"]
            and row["is_pre_split"] is True
        ]

        if not candidates:
            salary_unresolved_rows.append({
                "player_id": player_id,
                "player_name": clean(base_row.get("player_name")),
                "prior_team": clean(base_row.get("resolved_prior_team")),
                "reason": "no_dated_pre_split_salary_candidate",
            })
            continue

        latest_date = max(row["evidence_date"] for row in candidates)
        latest = [row for row in candidates if row["evidence_date"] == latest_date]

        top_priority = max(int(row["source_priority"]) for row in latest)
        latest_top = [
            row for row in latest
            if int(row["source_priority"]) == top_priority
        ]

        values = sorted({float(row["salary_amount"]) for row in latest_top})
        if len(values) == 1:
            amount = values[0]
            salary_resolution_rows.append({
                "player_id": player_id,
                "player_name": clean(base_row.get("player_name")),
                "prior_team": clean(base_row.get("resolved_prior_team")),
                "resolved_prior_salary": amount,
                "latest_pre_split_evidence_date": latest_date,
                "top_source_priority": top_priority,
                "resolution_status": "resolved_unique_latest_pre_split",
                "source_count": len(latest_top),
                "sources": "|".join(
                    sorted(
                        {
                            f"{r['source_zip']}::{r['source_member']}::{r['salary_field']}"
                            for r in latest_top
                            if float(r["salary_amount"]) == amount
                        }
                    )
                ),
            })
        else:
            salary_unresolved_rows.append({
                "player_id": player_id,
                "player_name": clean(base_row.get("player_name")),
                "prior_team": clean(base_row.get("resolved_prior_team")),
                "reason": "conflicting_values_at_latest_pre_split_top_priority",
                "latest_pre_split_evidence_date": latest_date,
                "top_source_priority": top_priority,
                "candidate_values": "|".join(str(v) for v in values),
                "candidate_sources": "|".join(
                    f"{r['source_zip']}::{r['source_member']}::{r['salary_field']}={r['salary_amount']}"
                    for r in latest_top
                ),
            })

    # Rights derivation readiness, but do not invent classifications.
    rights_harvest_rows = []
    rights_derivation_ready = []
    rights_still_unresolved = []

    for player_id, base_row in sorted(
        rights_targets.items(),
        key=lambda kv: clean(kv[1].get("player_name")).lower(),
    ):
        evidence = [
            row for row in evidence_rows
            if row["player_id"] == player_id
            and row["evidence_kind"] == "rights_or_contract_context"
        ]

        qualifying_counts = set()
        continuity_true = False
        signal_sources = []

        for row in evidence:
            try:
                signals = json.loads(row["rights_signal_snapshot"] or "{}")
            except Exception:
                signals = {}

            q = clean(signals.get("qualifying_season_count"))
            if q:
                try:
                    qualifying_counts.add(int(float(q)))
                except Exception:
                    pass

            if clean(signals.get("continuity_verified")).lower() in {
                "true", "1", "yes", "y"
            }:
                continuity_true = True

            if signals:
                signal_sources.append(
                    f"{row['source_zip']}::{row['source_member']}::"
                    f"{row['rights_signal_snapshot']}"
                )

        unique_q = sorted(qualifying_counts)
        ready = continuity_true and len(unique_q) == 1

        row_out = {
            "player_id": player_id,
            "player_name": clean(base_row.get("player_name")),
            "prior_team": clean(base_row.get("resolved_prior_team")),
            "evidence_row_count": len(evidence),
            "continuity_verified_signal": continuity_true,
            "qualifying_season_count_candidates": "|".join(
                str(x) for x in unique_q
            ),
            "derivation_ready": ready,
            "derived_rights_if_applied": (
                "bird" if ready and unique_q[0] >= 3
                else "early_bird" if ready and unique_q[0] == 2
                else "non_bird" if ready and unique_q[0] <= 1
                else ""
            ),
            "evidence_sources": "|".join(signal_sources),
            "classification_applied": False,
        }
        rights_harvest_rows.append(row_out)

        if ready:
            rights_derivation_ready.append(row_out)
        else:
            rights_still_unresolved.append(row_out)

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before gap harvest.")

    checks = []

    def add(cid: str, passed: bool, detail: str, severity: str = "strict"):
        checks.append({
            "check_id": cid,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {cid}: {'PASS' if passed else 'FAIL'}")

    print("=" * 128)
    print("2026 NON-RFA EVIDENCE GAP HARVEST V1")
    print("=" * 128)
    print("Running checks...")

    add(
        "upstream_reconciliation_passed",
        bool(rec_summary.get("passed"))
        and int(rec_summary.get("owner_resolved_count", -1)) == 226
        and int(rec_summary.get("authoritative_owner_conflict_count", -1)) == 0,
        "226/226 prior-team ownership is frozen.",
    )
    add(
        "exact_162_non_rfa_rows",
        len(non_rfa) == 162,
        f"non_rfa={len(non_rfa)}",
    )
    add(
        "target_sets_match_upstream_gaps",
        len(rights_targets) == 63
        and len(salary_targets) == 40
        and len(salary_conflict_targets) == 4,
        (
            f"rights={len(rights_targets)}; salary_missing={len(salary_targets)}; "
            f"non_rfa_salary_conflicts={len(salary_conflict_targets)}"
        ),
    )
    add(
        "evidence_scan_completed",
        len(source_scan) > 0 and len(evidence_rows) > 0,
        f"sources={len(source_scan)}; evidence_rows={len(evidence_rows)}",
    )
    add(
        "salary_resolution_requires_dated_pre_split_evidence",
        all(
            parse_date(row["latest_pre_split_evidence_date"]) <= SPLIT_DATE
            for row in salary_resolution_rows
        ),
        f"resolved_salary_rows={len(salary_resolution_rows)}",
    )
    add(
        "rights_classification_not_applied",
        all(not row["classification_applied"] for row in rights_harvest_rows),
        "Harvest only.",
    )

    after_state = object_digest(checkpoint.simulation_state)
    after_hash = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", after_state == before_state, after_state)
    add(
        "checkpoint_file_unchanged",
        after_hash == before_hash == EXPECTED_CHECKPOINT_SHA256,
        after_hash,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_non_rfa_evidence_gap_harvest_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "non_rfa_count": len(non_rfa),
        "rights_gap_count": len(rights_targets),
        "prior_salary_gap_count": len(salary_targets),
        "non_rfa_top_priority_salary_conflict_count": len(
            salary_conflict_targets
        ),
        "scanned_source_count": len(source_scan),
        "evidence_row_count": len(evidence_rows),
        "salary_rows_resolved_from_latest_pre_split_evidence": len(
            salary_resolution_rows
        ),
        "salary_rows_still_unresolved": len(salary_unresolved_rows),
        "rights_rows_derivation_ready": len(rights_derivation_ready),
        "rights_rows_still_unresolved": len(rights_still_unresolved),
        "rights_classifications_applied": 0,
        "salary_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Freeze only salary rows uniquely resolved by latest dated pre-split "
            "evidence. For rights, apply continuity-derived Bird/Early Bird/Non-Bird "
            "only where continuity_verified and one unique qualifying-season count "
            "are both present. Research only the remainder."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_non_rfa_gap_harvest_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)

        write_csv(export / "target_evidence_rows.csv", evidence_rows)
        write_csv(export / "target_source_scan.csv", source_scan)
        write_csv(
            export / "prior_salary_latest_pre_split_resolved.csv",
            salary_resolution_rows,
        )
        write_csv(
            export / "prior_salary_still_unresolved.csv",
            salary_unresolved_rows,
        )
        write_csv(export / "rights_continuity_harvest_63.csv", rights_harvest_rows)
        write_csv(
            export / "rights_continuity_derivation_ready.csv",
            rights_derivation_ready,
        )
        write_csv(
            export / "rights_still_unresolved.csv",
            rights_still_unresolved,
        )
        write_csv(export / "non_rfa_gap_harvest_checks.csv", checks)

        (export / "non_rfa_gap_harvest_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 NON-RFA EVIDENCE GAP HARVEST V1
======================================

Input state:
- 226/226 prior teams resolved
- 0 authoritative owner conflicts
- 63 non-RFA rights gaps
- 40 non-RFA prior-salary gaps
- 4 non-RFA top-priority salary conflicts

Purpose:
Reuse existing audited project evidence before doing new manual research.

Salary policy:
- only dated evidence on/before April 12, 2026 is eligible
- choose the latest pre-split evidence date
- within that date, use the highest source tier
- resolve only if one unique salary amount remains

Rights policy:
- harvest continuity/qualifying-season signals
- mark derivation-ready only if continuity_verified is affirmative AND one
  unique qualifying-season count exists
- do NOT apply a rights classification in this package

No player state, rights, salary, Team Salary, cap hold, QO, renouncement,
roster, contract, or checkpoint mutation occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(export.iterdir()):
                z.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Non-RFA Evidence Gap Harvest V1 failed: " + ", ".join(failed)
        )

    print("")
    print("=" * 128)
    print("2026 NON-RFA EVIDENCE GAP HARVEST V1 PASSED")
    print("=" * 128)
    print(f"Rights gaps targeted:               {len(rights_targets)}")
    print(f"Salary gaps targeted:               {len(salary_targets)}")
    print(f"Non-RFA salary conflicts targeted:  {len(salary_conflict_targets)}")
    print(f"Salary rows resolved:               {len(salary_resolution_rows)}")
    print(f"Salary rows still unresolved:       {len(salary_unresolved_rows)}")
    print(f"Rights rows derivation-ready:       {len(rights_derivation_ready)}")
    print(f"Rights rows still unresolved:       {len(rights_still_unresolved)}")
    print("Rights classifications applied:      0")
    print("Salary values applied:               0")
    print("Checkpoint write:        NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
