from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pickle
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-qo-cap-hold-readiness-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_QO_PLAYERS = 64

# CBA Article VII, Section 4(d), official 2023 NBA-NBPA CBA.
CBA_SOURCE = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)
NBA_FA_SOURCE = "https://www.nba.com/news/free-agency-explained"

# The 2026-27 zero-YOS full-season minimum established in the prior
# verified QO/minimum-salary work. This is also the special cap-hold amount
# for a player completing a Two-Way Contract under Article VII 4(d)(7).
ZERO_YOS_MINIMUM_2026_27 = 1_357_763.0

RIGHTS_NORMALIZATION = {
    "bird": "bird",
    "qualifying veteran free agent": "bird",
    "qvfa": "bird",
    "early bird": "early_bird",
    "early_bird": "early_bird",
    "early qualifying veteran free agent": "early_bird",
    "eqvfa": "early_bird",
    "non-bird": "non_bird",
    "non bird": "non_bird",
    "non_bird": "non_bird",
    "non-qualifying veteran free agent": "non_bird",
    "nqvfa": "non_bird",
    "n/a": "not_applicable",
    "not applicable": "not_applicable",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = clean(value).lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return {}
    return json.loads(archive.read(member).decode("utf-8-sig"))


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


def normalize_rights(value: Any) -> str:
    text = clean(value).lower().replace("_", " ")
    text = " ".join(text.split())
    return RIGHTS_NORMALIZATION.get(text, "")


def find_rights_registry_zip(root: Path) -> Path | None:
    patterns = [
        "fa_rights_registry_v2_preview_final_2026-27_*.zip",
        "*rights_registry_v2*2026-27*.zip",
        "*rights_registry*v2*.zip",
    ]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                candidates.append(path)

    # Prefer a ZIP that actually contains a 187-row-ish rights registry CSV.
    valid: list[Path] = []
    for path in candidates:
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if any(
                    "rights_registry" in name.lower()
                    and name.lower().endswith(".csv")
                    for name in names
                ):
                    valid.append(path)
        except Exception:
            pass

    return max(valid, key=lambda p: p.stat().st_mtime) if valid else None


def load_rights_rows(path: Path | None) -> tuple[list[dict[str, str]], str]:
    if path is None:
        return [], ""

    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name for name in archive.namelist()
            if name.lower().endswith(".csv")
            and "rights_registry" in name.lower()
        ]

        scored = []
        for name in csv_names:
            try:
                text = archive.read(name).decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(text))) if text.strip() else []
            except Exception:
                continue

            if not rows:
                continue

            fields = {key.lower() for key in rows[0]}
            score = 0
            if any("player_id" == key for key in fields):
                score += 5
            if any("right" in key for key in fields):
                score += 5
            if 150 <= len(rows) <= 220:
                score += 3
            scored.append((score, len(rows), name, rows))

        if not scored:
            return [], ""

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, member, rows = scored[0]
        return rows, member


def extract_rights_fields(row: dict[str, str]) -> tuple[str, str, str, str]:
    rights_value = ""
    prior_salary = ""
    prior_team = ""
    evidence = ""

    for key, value in row.items():
        lk = clean(key).lower()
        if not rights_value and (
            lk in {
                "rights_status",
                "rights",
                "rights_classification",
                "free_agent_rights",
                "final_rights",
                "rights_type",
            }
            or ("right" in lk and "source" not in lk and "reason" not in lk)
        ):
            candidate = normalize_rights(value)
            if candidate:
                rights_value = candidate

        if not prior_salary and (
            lk in {
                "prior_salary",
                "prior_regular_salary",
                "prior_regular_salary_2025_26",
                "season_2025_26_salary",
            }
            or ("prior" in lk and "salary" in lk and "source" not in lk)
        ):
            if finite(value) is not None:
                prior_salary = clean(value)

        if not prior_team and (
            lk in {
                "prior_team",
                "prior_team_abbreviation",
                "team_abbreviation",
            }
        ):
            prior_team = clean(value).upper()

        if not evidence and (
            "evidence" in lk or "source" in lk or "reason" in lk
        ):
            if clean(value):
                evidence = clean(value)

    return rights_value, prior_salary, prior_team, evidence


def formula_family(
    *,
    rights: str,
    qo_formula_family: str,
    eligibility_path: str,
) -> str:
    text = (clean(qo_formula_family) + " " + clean(eligibility_path)).lower()

    if "two_way" in text or "two-way" in text:
        return "two_way_zero_yos_minimum"

    if rights == "bird":
        if "rookie_scale" in text or "rookie scale" in text:
            return "bird_rookie_scale_second_option_250_or_300_pct"
        return "bird_150_or_190_pct"

    if rights == "early_bird":
        return "early_bird_130_pct"

    if rights == "non_bird":
        return "non_bird_120_pct"

    if rights == "not_applicable":
        return "not_applicable"

    return "rights_classification_required"


def main() -> int:
    root = Path.cwd().resolve()

    issuance_zip = find_latest(
        root,
        "fa_qo_issuance_decision_preview_v1_2026-27_*.zip",
    )
    qo_amount_zip = find_latest(
        root,
        "fa_final_market_qo_amount_completion_v1_0_4_2026-27_*.zip",
    )
    eligibility_zip = find_latest(
        root,
        "fa_final_market_rfa_qo_eligibility_readiness_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(issuance_zip) as archive:
        issuance_summary = read_json_member(
            archive,
            "qo_issuance_preview_summary.json",
        )
        issuance_rows = read_csv_member(
            archive,
            "qo_issuance_decision_board_64.csv",
        )

    with zipfile.ZipFile(qo_amount_zip) as archive:
        qo_amount_summary = read_json_member(
            archive,
            "qo_amount_completion_summary.json",
        )
        qo_amount_rows = read_csv_member(
            archive,
            "qo_exact_amounts_completed_64.csv",
        )

    with zipfile.ZipFile(eligibility_zip) as archive:
        eligibility_summary = read_json_member(
            archive,
            "rfa_qo_rebuild_summary.json",
        )
        eligibility_rows = read_csv_member(
            archive,
            "rfa_qo_structurally_eligible.csv",
        )

    if len(issuance_rows) != EXPECTED_QO_PLAYERS:
        raise RuntimeError(f"Expected 64 issuance rows, got {len(issuance_rows)}.")
    if len(qo_amount_rows) != EXPECTED_QO_PLAYERS:
        raise RuntimeError(f"Expected 64 QO amount rows, got {len(qo_amount_rows)}.")
    if len(eligibility_rows) != EXPECTED_QO_PLAYERS:
        raise RuntimeError(f"Expected 64 eligibility rows, got {len(eligibility_rows)}.")

    rights_zip = find_rights_registry_zip(root)
    rights_rows, rights_member = load_rights_rows(rights_zip)
    rights_by_id = {
        pid(row.get("player_id")): row
        for row in rights_rows
        if pid(row.get("player_id"))
    }

    amount_by_id = {
        pid(row.get("player_id")): row
        for row in qo_amount_rows
    }
    eligibility_by_id = {
        pid(row.get("player_id")): row
        for row in eligibility_rows
    }

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before QO cap-hold readiness.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    output_rows: list[dict[str, Any]] = []

    for issue in issuance_rows:
        player_id = pid(issue.get("player_id"))
        player_name = clean(issue.get("player_name"))
        prior_team = clean(issue.get("prior_team")).upper()

        amount = amount_by_id[player_id]
        eligibility = eligibility_by_id[player_id]

        rights_row = rights_by_id.get(player_id, {})
        rights, prior_salary_text, rights_prior_team, rights_evidence = (
            extract_rights_fields(rights_row) if rights_row else ("", "", "", "")
        )

        qo_formula = clean(amount.get("formula_family"))
        eligibility_path = clean(eligibility.get("eligibility_path"))
        family = formula_family(
            rights=rights,
            qo_formula_family=qo_formula,
            eligibility_path=eligibility_path,
        )

        prior_salary = finite(prior_salary_text)

        exact_cap_hold = None
        exact_ready = False
        blockers: list[str] = []

        if family == "two_way_zero_yos_minimum":
            exact_cap_hold = ZERO_YOS_MINIMUM_2026_27
            exact_ready = True

        elif family == "early_bird_130_pct":
            if prior_salary is None:
                blockers.append("prior_salary_required")
            else:
                exact_cap_hold = prior_salary * 1.30
                exact_ready = True

        elif family == "non_bird_120_pct":
            if prior_salary is None:
                blockers.append("prior_salary_required")
            else:
                exact_cap_hold = prior_salary * 1.20
                exact_ready = True

        elif family in {
            "bird_150_or_190_pct",
            "bird_rookie_scale_second_option_250_or_300_pct",
        }:
            if prior_salary is None:
                blockers.append("prior_salary_required")
            blockers.append(
                "2025_26_estimated_average_player_salary_threshold_required"
            )

        elif family == "rights_classification_required":
            blockers.append("free_agent_rights_classification_required")

        elif family == "not_applicable":
            blockers.append(
                "unexpected_not_applicable_rights_for_structurally_rfa_eligible_player"
            )

        # Even formula-ready rows still need minimum/maximum floor/cap validation
        # before a durable Team Salary amount is claimed.
        if exact_ready and family != "two_way_zero_yos_minimum":
            blockers.append("minimum_and_maximum_free_agent_amount_floor_cap_validation")
            exact_ready = False
            exact_cap_hold = None

        output_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": prior_team,
            "qo_recommendation": clean(issue.get("recommendation")),
            "qo_model_advisory": clean(issue.get("model_recommendation")),
            "exact_qo_amount": clean(issue.get("exact_qo_amount")),
            "rights_registry_match": bool(rights_row),
            "rights_classification": rights,
            "rights_registry_prior_team": rights_prior_team,
            "rights_registry_evidence": rights_evidence,
            "prior_salary_from_rights_registry": prior_salary,
            "qo_formula_family": qo_formula,
            "eligibility_path": eligibility_path,
            "cap_hold_formula_family": family,
            "provisional_formula_cap_hold": (
                exact_cap_hold if exact_cap_hold is not None else ""
            ),
            "exact_cap_hold_ready": exact_ready,
            "readiness_blockers": "|".join(blockers),
            "estimated_average_player_salary_2025_26_required": (
                family in {
                    "bird_150_or_190_pct",
                    "bird_rookie_scale_second_option_250_or_300_pct",
                }
            ),
            "minimum_maximum_floor_cap_validation_required": (
                family in {
                    "bird_150_or_190_pct",
                    "bird_rookie_scale_second_option_250_or_300_pct",
                    "early_bird_130_pct",
                    "non_bird_120_pct",
                }
            ),
            "qo_tender_applied": False,
            "cap_hold_applied": False,
            "renouncement_applied": False,
            "state_mutation_applied": False,
        })

    family_counts = Counter(row["cap_hold_formula_family"] for row in output_rows)
    rights_counts = Counter(
        row["rights_classification"] or "unresolved"
        for row in output_rows
    )
    exact_ready_rows = [
        row for row in output_rows if bool(row["exact_cap_hold_ready"])
    ]
    unresolved_rights = [
        row for row in output_rows
        if row["cap_hold_formula_family"] == "rights_classification_required"
    ]
    aps_blocked = [
        row for row in output_rows
        if bool(row["estimated_average_player_salary_2025_26_required"])
    ]

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
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 QO CAP-HOLD READINESS V1.0.1", flush=True)
    print("=" * 128, flush=True)
    print("QO candidate universe:             64", flush=True)
    print(f"Rights registry ZIP:               {rights_zip or '<not found>'}", flush=True)
    print(f"Rights registry rows:              {len(rights_rows)}", flush=True)
    print("CAP HOLDS:                         NOT APPLIED", flush=True)
    print("QO TENDERS:                        NOT APPLIED", flush=True)
    print("", flush=True)
    print("Running strict readiness checks...", flush=True)

    check(
        "upstream_qo_issuance_preview_passed",
        bool(issuance_summary.get("passed"))
        and int(issuance_summary.get("decision_row_count", -1)) == 64,
        "64-player QO issuance preview passed.",
    )
    check(
        "upstream_qo_amount_completion_passed",
        bool(qo_amount_summary.get("passed"))
        and int(qo_amount_summary.get("completed_exact_qo_count", -1)) == 64,
        "64/64 exact QO amounts.",
    )
    check(
        "upstream_structural_eligibility_passed",
        bool(eligibility_summary.get("passed"))
        and int(
            eligibility_summary.get(
                "structurally_eligible_if_qo_issued_count", -1
            )
        ) == 64,
        "64 structurally eligible RFA candidates.",
    )
    check(
        "exact_64_cap_hold_readiness_rows",
        len(output_rows) == 64
        and len({row["player_id"] for row in output_rows}) == 64,
        f"rows={len(output_rows)}",
    )
    check(
        "all_rows_preserve_prior_team",
        all(clean(row["prior_team"]) for row in output_rows),
        "Every QO candidate retains a reconstructed prior team.",
    )
    check(
        "two_way_cap_hold_rule_is_zero_yos_minimum",
        all(
            row["cap_hold_formula_family"] != "two_way_zero_yos_minimum"
            or float(row["provisional_formula_cap_hold"])
            == ZERO_YOS_MINIMUM_2026_27
            for row in output_rows
        ),
        f"zero_yos_minimum={ZERO_YOS_MINIMUM_2026_27}",
    )
    check(
        "no_qo_or_cap_hold_mutation_applied",
        all(
            not row["qo_tender_applied"]
            and not row["cap_hold_applied"]
            and not row["renouncement_applied"]
            and not row["state_mutation_applied"]
            for row in output_rows
        ),
        "Readiness only.",
    )
    check(
        "rights_registry_coverage_is_diagnostic",
        True,
        (
            f"registry_matches={sum(bool(row['rights_registry_match']) for row in output_rows)}/64; "
            f"rights_unresolved={len(unresolved_rights)}"
        ),
        severity="diagnostic",
    )
    check(
        "estimated_average_salary_blocker_is_diagnostic",
        True,
        f"bird_threshold_rows={len(aps_blocked)}",
        severity="diagnostic",
    )
    check(
        "exact_cap_hold_ready_count_is_diagnostic",
        True,
        f"exact_ready={len(exact_ready_rows)}/64",
        severity="diagnostic",
    )

    checkpoint_hash_after = sha256_file(checkpoint_path)
    state_digest_after = object_digest(checkpoint.simulation_state)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_after == state_digest_before,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash_after
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_qo_cap_hold_readiness_v1_0_1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "qo_candidate_count": len(output_rows),
        "rights_registry_zip": str(rights_zip) if rights_zip else "",
        "rights_registry_member": rights_member,
        "rights_registry_row_count": len(rights_rows),
        "rights_classification_counts": dict(sorted(rights_counts.items())),
        "cap_hold_formula_family_counts": dict(sorted(family_counts.items())),
        "rights_unresolved_count": len(unresolved_rights),
        "estimated_average_player_salary_threshold_required_count": len(
            aps_blocked
        ),
        "exact_cap_hold_ready_count": len(exact_ready_rows),
        "zero_yos_minimum_2026_27": ZERO_YOS_MINIMUM_2026_27,
        "cba_source": CBA_SOURCE,
        "nba_free_agency_source": NBA_FA_SOURCE,
        "qo_tenders_applied": 0,
        "cap_holds_applied": 0,
        "renouncements_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Resolve only the rights-unresolved QO candidates and the exact "
            "2025-26 Estimated Average Player Salary threshold needed for Bird "
            "cap-hold branching. Then validate minimum/maximum Free Agent Amount "
            "floors/caps and produce exact cap holds for all 64 before applying QOs."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_qo_cap_hold_readiness_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "qo_cap_hold_readiness_all_64.csv",
            output_rows,
        )
        write_csv(
            export / "qo_cap_hold_rights_unresolved.csv",
            unresolved_rights,
        )
        write_csv(
            export / "qo_cap_hold_estimated_average_salary_blocked.csv",
            aps_blocked,
        )
        write_csv(
            export / "qo_cap_hold_exact_ready.csv",
            exact_ready_rows,
        )
        write_csv(
            export / "qo_cap_hold_readiness_checks.csv",
            checks,
        )
        (export / "qo_cap_hold_readiness_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 QO CAP-HOLD READINESS V1
================================

Purpose
-------
Determine what is still required before the 64 QO issuance recommendations
can safely include the Team Salary cost of retaining each player's free-agent
rights.

Official CBA Article VII Section 4(d)
-------------------------------------
A Veteran Free Agent remains in his Prior Team's Team Salary until he:
- re-signs with that team,
- signs with another NBA team, or
- is renounced.

Free Agent Amount formula families:
- Bird/QVFA: 150% or 190% of prior Salary depending on Estimated Average
  Player Salary threshold.
- Bird/QVFA after second Rookie Scale Option Year: 250% or 300%.
- Early Bird: 130%.
- Non-Bird: 120%.
- Completing Two-Way player: current zero-YOS Minimum Annual Salary.

Additional CBA minimum/maximum floors/caps still apply.

Important
---------
This is a readiness audit, not a cap-hold application.
No QO is tendered.
No player is made RFA.
No renouncement occurs.
No checkpoint write occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "QO Cap-Hold Readiness V1.0.1 failed: " + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 QO CAP-HOLD READINESS V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("QO candidate universe:             64", flush=True)
    print(
        f"Rights registry matches:           "
        f"{sum(bool(row['rights_registry_match']) for row in output_rows)}/64",
        flush=True,
    )
    print(f"Rights unresolved:                 {len(unresolved_rights)}", flush=True)
    print(
        f"Bird threshold rows needing EAPS:  {len(aps_blocked)}",
        flush=True,
    )
    print(f"Exact cap holds already ready:     {len(exact_ready_rows)}/64", flush=True)
    print("QO tenders applied:                 0", flush=True)
    print("Cap holds applied:                  0", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
