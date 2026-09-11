from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-qo-cap-hold-completion-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_PLAYERS = 64
EXPECTED_FROZEN_EXACT = 38
EXPECTED_BRIDGE_ROWS = 26

CBA_SOURCE = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)
SALARYSWISH_BASE = "https://www.salaryswish.com/players/"

# Exact 2026-27 cap-hold evidence for the 26 rows not already exact in
# QO Cap-Hold Readiness V1.0.1.
#
# For most rows, SalarySwish preserves the historical 2026-27 Cap Hold on the
# player's contract history. We intentionally ignore any later signing,
# renouncement, QO tender, or option outcome as a simulation decision.
#
# Three rows are branch-specific because the real-world option outcome differs
# from the simulator scenario:
# - Mouhamadou Gueye
# - Tolu Smith
# - Trayce Jackson-Davis
# Their branch cap hold is derived from CBA Article VII 4(d)(4)-(5):
# prior salary is <= applicable prior-year minimum, so the Free Agent Amount is
# the then-current unreimbursed minimum amount. For these service levels that
# amount is $2,449,421 in 2026-27.
BRIDGE = {
    "1642873": {  # Amari Williams
        "name": "Amari Williams",
        "cap_hold": 2_185_116.0,
        "rights": "non_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "amari-williams",
    },
    "1641740": {  # Jaylen Clark
        "name": "Jaylen Clark",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "jaylen-clark",
    },
    "1641763": {  # Julian Phillips
        "name": "Julian Phillips",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "julian-phillips",
    },
    "1631109": {  # Mark Williams
        "name": "Mark Williams",
        "cap_hold": 18_829_593.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "mark-williams",
    },
    "1642885": {  # Mohamed Diawara
        "name": "Mohamed Diawara",
        "cap_hold": 2_185_116.0,
        "rights": "non_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "mohamed-diawara",
    },
    "1631172": {  # Ousmane Dieng
        "name": "Ousmane Dieng",
        "cap_hold": 20_012_646.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "ousmane-dieng",
    },
    "1642366": {  # Quinten Post
        "name": "Quinten Post",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "quinten-post",
    },
    "1642461": {  # Spencer Jones
        "name": "Spencer Jones",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "spencer-jones",
    },
    "1631106": {  # Tari Eason
        "name": "Tari Eason",
        "cap_hold": 17_027_298.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "tari-eason",
    },
    "1642449": {  # Tolu Smith
        "name": "Tolu Smith",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "branch_cba_minimum_floor",
        "url": SALARYSWISH_BASE + "tolu-smith-iii",
    },
    "1631218": {  # Trayce Jackson-Davis
        "name": "Trayce Jackson-Davis",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "branch_cba_minimum_floor",
        "url": SALARYSWISH_BASE + "trayce-jackson-davis",
    },
    # Ariel Hukporti ID is resolved by name below if local ID differs.
    "NAME:Ariel Hukporti": {
        "name": "Ariel Hukporti",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "ariel-hukporti",
    },
    "NAME:Andre Jackson Jr.": {
        "name": "Andre Jackson Jr.",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "andre-jackson-jr",
    },
    "NAME:Bennedict Mathurin": {
        "name": "Bennedict Mathurin",
        "cap_hold": 27_562_719.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "bennedict-mathurin",
    },
    "NAME:Jalen Duren": {
        "name": "Jalen Duren",
        "cap_hold": 19_449_432.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "jalen-duren",
    },
    "NAME:Jalen Wilson": {
        "name": "Jalen Wilson",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "jalen-wilson",
    },
    "NAME:Ochai Agbaji": {
        "name": "Ochai Agbaji",
        "cap_hold": 19_150_575.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "ochai-agbaji",
    },
    "NAME:Pat Spencer": {
        "name": "Pat Spencer",
        "cap_hold": 2_449_421.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "pat-spencer",
    },
    "NAME:Peyton Watson": {
        "name": "Peyton Watson",
        "cap_hold": 13_069_428.0,
        "rights": "bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "peyton-watson",
    },
    "NAME:Hayden Gray": {
        "name": "Hayden Gray",
        "cap_hold": 2_185_116.0,
        "rights": "non_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "hayden-gray",
    },
    "NAME:Jahmir Young": {
        "name": "Jahmir Young",
        "cap_hold": 2_449_421.0,
        "rights": "non_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "jahmir-young",
    },
    "NAME:Jonathan Mogbo": {
        "name": "Jonathan Mogbo",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "jonathan-mogbo",
    },
    "NAME:Keaton Wallace": {
        "name": "Keaton Wallace",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "keaton-wallace",
    },
    "NAME:Keshad Johnson": {
        "name": "Keshad Johnson",
        "cap_hold": 2_449_421.0,
        "rights": "early_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "keshad-johnson",
    },
    "NAME:Max Shulga": {
        "name": "Max Shulga",
        "cap_hold": 2_185_116.0,
        "rights": "non_bird",
        "mode": "historical_2026_27_cap_hold_evidence",
        "url": SALARYSWISH_BASE + "max-shulga",
    },
    "NAME:Mouhamadou Gueye": {
        "name": "Mouhamadou Gueye",
        "cap_hold": 2_449_421.0,
        "rights": "non_bird",
        "mode": "branch_cba_minimum_floor",
        "url": SALARYSWISH_BASE + "mouhamadou-gueye",
    },
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


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
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


def bridge_for(row: dict[str, str]) -> dict[str, Any] | None:
    player_id = pid(row.get("player_id"))
    player_name = clean(row.get("player_name"))
    value = BRIDGE.get(player_id)
    if value is not None:
        return value
    return BRIDGE.get("NAME:" + player_name)


def main() -> int:
    root = Path.cwd().resolve()

    readiness_zip = find_latest(
        root,
        "fa_qo_cap_hold_readiness_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(readiness_zip) as archive:
        readiness_summary = read_json_member(
            archive,
            "qo_cap_hold_readiness_summary.json",
        )
        readiness_rows = read_csv_member(
            archive,
            "qo_cap_hold_readiness_all_64.csv",
        )
        frozen_exact = read_csv_member(
            archive,
            "qo_cap_hold_exact_ready.csv",
        )

    if len(readiness_rows) != EXPECTED_PLAYERS:
        raise RuntimeError(
            f"Expected {EXPECTED_PLAYERS} readiness rows, got {len(readiness_rows)}."
        )
    if len(frozen_exact) != EXPECTED_FROZEN_EXACT:
        raise RuntimeError(
            f"Expected {EXPECTED_FROZEN_EXACT} frozen exact rows, got {len(frozen_exact)}."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before QO cap-hold completion.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    frozen_ids = {
        pid(row.get("player_id"))
        for row in frozen_exact
    }
    nonexact = [
        row for row in readiness_rows
        if pid(row.get("player_id")) not in frozen_ids
    ]

    bridge_rows: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for row in nonexact:
        evidence = bridge_for(row)
        if evidence is None:
            unsupported.append({
                "player_id": pid(row.get("player_id")),
                "player_name": clean(row.get("player_name")),
                "prior_team": clean(row.get("prior_team")),
                "readiness_blockers": clean(row.get("readiness_blockers")),
            })
            continue

        bridge_rows.append({
            "player_id": pid(row.get("player_id")),
            "player_name": clean(row.get("player_name")),
            "prior_team": clean(row.get("prior_team")),
            "upstream_rights_classification": clean(
                row.get("rights_classification")
            ),
            "resolved_rights_classification": evidence["rights"],
            "upstream_cap_hold_formula_family": clean(
                row.get("cap_hold_formula_family")
            ),
            "exact_cap_hold_2026_27": evidence["cap_hold"],
            "evidence_mode": evidence["mode"],
            "evidence_url": evidence["url"],
            "cba_authority_url": CBA_SOURCE,
            "post_split_transaction_outcome_imported": False,
            "qo_tender_applied": False,
            "cap_hold_applied": False,
            "renouncement_applied": False,
            "state_mutation_applied": False,
        })

    final_rows: list[dict[str, Any]] = []

    for row in frozen_exact:
        final_rows.append({
            "player_id": pid(row.get("player_id")),
            "player_name": clean(row.get("player_name")),
            "prior_team": clean(row.get("prior_team")),
            "rights_classification": clean(row.get("rights_classification")),
            "exact_cap_hold_2026_27": float(
                clean(row.get("provisional_formula_cap_hold"))
            ),
            "evidence_mode": "frozen_v1_0_1_two_way_exact",
            "evidence_url": "",
            "cba_authority_url": CBA_SOURCE,
            "post_split_transaction_outcome_imported": False,
            "qo_tender_applied": False,
            "cap_hold_applied": False,
            "renouncement_applied": False,
            "state_mutation_applied": False,
        })

    for row in bridge_rows:
        final_rows.append({
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "prior_team": row["prior_team"],
            "rights_classification": row[
                "resolved_rights_classification"
            ],
            "exact_cap_hold_2026_27": row[
                "exact_cap_hold_2026_27"
            ],
            "evidence_mode": row["evidence_mode"],
            "evidence_url": row["evidence_url"],
            "cba_authority_url": row["cba_authority_url"],
            "post_split_transaction_outcome_imported": False,
            "qo_tender_applied": False,
            "cap_hold_applied": False,
            "renouncement_applied": False,
            "state_mutation_applied": False,
        })

    final_ids = {row["player_id"] for row in final_rows}
    readiness_ids = {pid(row.get("player_id")) for row in readiness_rows}
    evidence_counts = Counter(row["evidence_mode"] for row in final_rows)
    rights_counts = Counter(row["rights_classification"] for row in final_rows)

    branch_formula_names = {
        row["player_name"]
        for row in bridge_rows
        if row["evidence_mode"] == "branch_cba_minimum_floor"
    }

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
    print("2026 QO CAP-HOLD COMPLETION V1.0.1", flush=True)
    print("=" * 128, flush=True)
    print(f"Readiness universe:                {len(readiness_rows)}", flush=True)
    print(f"Frozen exact rows:                 {len(frozen_exact)}", flush=True)
    print(f"Bridge rows required:              {len(nonexact)}", flush=True)
    print("CAP HOLDS APPLIED:                 NO", flush=True)
    print("QO TENDERS APPLIED:                NO", flush=True)
    print("", flush=True)
    print("Running strict completion checks...", flush=True)

    check(
        "upstream_cap_hold_readiness_passed",
        bool(readiness_summary.get("passed"))
        and int(readiness_summary.get("qo_candidate_count", -1)) == 64,
        "V1.0.1 readiness audit passed.",
    )
    check(
        "exact_38_upstream_cap_holds_frozen",
        len(frozen_exact) == EXPECTED_FROZEN_EXACT,
        f"frozen={len(frozen_exact)}",
    )
    check(
        "exact_26_bridge_rows_required",
        len(nonexact) == EXPECTED_BRIDGE_ROWS,
        f"nonexact={len(nonexact)}",
    )
    check(
        "all_26_bridge_rows_supported",
        len(bridge_rows) == EXPECTED_BRIDGE_ROWS
        and not unsupported,
        f"resolved={len(bridge_rows)} unsupported={len(unsupported)}",
    )
    check(
        "branch_specific_option_divergence_is_narrow",
        branch_formula_names
        == {
            "Mouhamadou Gueye",
            "Tolu Smith",
            "Trayce Jackson-Davis",
        },
        repr(sorted(branch_formula_names)),
    )
    check(
        "all_exact_cap_holds_positive",
        all(float(row["exact_cap_hold_2026_27"]) > 0 for row in final_rows),
        "Every completed cap hold is positive.",
    )
    check(
        "exact_64_cap_holds_completed",
        len(final_rows) == EXPECTED_PLAYERS
        and final_ids == readiness_ids,
        f"rows={len(final_rows)} unique={len(final_ids)}",
    )
    check(
        "no_post_split_transaction_outcome_imported",
        all(
            not boolish(row["post_split_transaction_outcome_imported"])
            for row in final_rows
        ),
        "Post-split outcomes are audit/evidence context only.",
    )
    check(
        "no_qo_cap_hold_or_renouncement_applied",
        all(
            not boolish(row["qo_tender_applied"])
            and not boolish(row["cap_hold_applied"])
            and not boolish(row["renouncement_applied"])
            and not boolish(row["state_mutation_applied"])
            for row in final_rows
        ),
        "Completion is read-only.",
    )

    state_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)

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
        f"fa_qo_cap_hold_completion_v1_0_1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_qo_cap_hold_complete_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "qo_cap_hold_bridge_26.csv",
            bridge_rows,
        )
        write_csv(
            export / "qo_cap_hold_bridge_unsupported.csv",
            unsupported,
        )
        write_csv(
            export / "qo_exact_cap_holds_completed_64.csv",
            sorted(
                final_rows,
                key=lambda row: clean(row["player_name"]).lower(),
            ),
        )
        write_csv(
            export / "qo_cap_hold_completion_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "qo_candidate_count": len(final_rows),
            "frozen_exact_count": len(frozen_exact),
            "bridge_count": len(bridge_rows),
            "unsupported_count": len(unsupported),
            "exact_cap_hold_count": len(final_rows),
            "evidence_mode_counts": dict(sorted(evidence_counts.items())),
            "rights_classification_counts": dict(sorted(rights_counts.items())),
            "branch_specific_minimum_floor_players": sorted(
                branch_formula_names
            ),
            "post_split_transaction_outcomes_imported": False,
            "qo_tenders_applied": 0,
            "cap_holds_applied": 0,
            "renouncements_applied": 0,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": not failed,
            "failed_checks": failed,
            "next_slice": (
                "Build a rights-retention/renouncement decision preview using "
                "the exact 64 cap holds. QO tendering and Bird-rights retention "
                "must remain separate decisions: declining to tender a QO does "
                "not itself renounce the player's cap hold or Bird rights."
            ),
        }

        (export / "qo_cap_hold_completion_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 QO CAP-HOLD COMPLETION V1
=================================

Completes exact 2026-27 Free Agent Amount / cap-hold evidence for all 64
structurally QO-eligible players.

38 rows are frozen from the already-exact Two-Way zero-YOS rule in
QO Cap-Hold Readiness V1.0.1.

26 remaining rows use:
- preserved historical 2026-27 cap-hold evidence, or
- a narrow CBA minimum-floor calculation when the simulator's option decision
  differs from the later real-world option outcome.

The three branch-specific rows are:
- Mouhamadou Gueye
- Tolu Smith
- Trayce Jackson-Davis

Important lifecycle distinction:
A qualifying-offer decision and a Bird-rights/cap-hold renouncement decision
are NOT the same decision. Not tendering a QO can make a player unrestricted
while the Prior Team still retains applicable free-agent rights/cap hold until
those rights are renounced or otherwise extinguished.

No QO tender.
No cap hold applied.
No renouncement.
No checkpoint write.
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
            "QO Cap-Hold Completion V1.0.1 failed: " + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 QO CAP-HOLD COMPLETION V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Exact cap holds completed:         64/64", flush=True)
    print(f"Frozen upstream exact:             {len(frozen_exact)}", flush=True)
    print(f"Bridge exact:                      {len(bridge_rows)}", flush=True)
    print("Unsupported:                        0", flush=True)
    print("QO tenders applied:                 0", flush=True)
    print("Cap holds applied:                  0", flush=True)
    print("Renouncements applied:              0", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
