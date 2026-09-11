from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-team-aggregate-rights-pressure-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SALARY_CAP = 164_961_000.0
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)


def clean(v: Any) -> str:
    return str(v or "").strip()


def fnum(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


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
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    if not paths:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(paths, key=lambda p: p.stat().st_mtime)


def read_csv_member(z: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = z.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(z: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(name).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    rights_zip = find_latest(
        root,
        "fa_rights_retention_renouncement_preview_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(rights_zip) as z:
        summary = read_json_member(z, "rights_retention_preview_summary.json")
        board = read_csv_member(z, "rights_retention_decision_board_64.csv")

    if len(board) != 64:
        raise RuntimeError(f"Expected 64 rights rows, got {len(board)}.")

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            f"Checkpoint mismatch. Expected {EXPECTED_CHECKPOINT_SHA256}, got {before_hash}"
        )

    by_team = defaultdict(list)
    for row in board:
        by_team[clean(row["prior_team"]).upper()].append(row)

    team_rows = []
    marginal_rows = []

    for team, rows in sorted(by_team.items()):
        model_retain = [r for r in rows if clean(r["model_recommendation"]) == "retain_rights"]
        model_renounce = [r for r in rows if clean(r["model_recommendation"]) == "renounce_rights"]
        low_conf = [r for r in rows if clean(r["confidence"]).lower() == "low"]
        low_conf_retain = [r for r in model_retain if clean(r["confidence"]).lower() == "low"]

        retained_total = sum(fnum(r["exact_cap_hold_2026_27"]) for r in model_retain)
        renounced_total = sum(fnum(r["exact_cap_hold_2026_27"]) for r in model_renounce)
        candidate_total = sum(fnum(r["exact_cap_hold_2026_27"]) for r in rows)
        retained_pct_cap = retained_total / SALARY_CAP

        if retained_pct_cap >= 0.10:
            pressure = "high"
        elif retained_pct_cap >= 0.05:
            pressure = "medium"
        else:
            pressure = "low"

        team_rows.append({
            "team": team,
            "candidate_count": len(rows),
            "model_retain_count": len(model_retain),
            "model_renounce_count": len(model_renounce),
            "user_decision_count": sum(
                clean(r["recommendation"]) == "user_decision_required" for r in rows
            ),
            "candidate_cap_hold_total": candidate_total,
            "model_retained_cap_hold_total": retained_total,
            "model_renounced_cap_hold_total": renounced_total,
            "model_retained_hold_pct_salary_cap": retained_pct_cap,
            "rights_hold_pressure_tier": pressure,
            "low_confidence_count": len(low_conf),
            "low_confidence_retain_count": len(low_conf_retain),
            "full_guaranteed_team_salary_integrated": False,
            "incomplete_roster_charges_integrated": False,
            "exception_strategy_integrated": False,
            "decisions_revised": False,
        })

        for r in low_conf_retain:
            marginal_rows.append({
                "team": team,
                "player_id": clean(r["player_id"]),
                "player_name": clean(r["player_name"]),
                "exact_cap_hold_2026_27": fnum(r["exact_cap_hold_2026_27"]),
                "market_reference": fnum(r["market_reference"]),
                "market_to_cap_hold_ratio": fnum(r["market_to_cap_hold_ratio"]),
                "decision_score": fnum(r["decision_score"]),
                "current_model_advisory": clean(r["model_recommendation"]),
                "confidence": clean(r["confidence"]),
                "team_model_retained_cap_hold_total": retained_total,
                "team_model_retained_hold_pct_salary_cap": retained_pct_cap,
                "rights_hold_pressure_tier": pressure,
                "status": "marginal_retain_candidate_for_future_full_cap_optimizer",
            })

    checks = []

    def add(cid: str, passed: bool, detail: str, severity: str = "strict"):
        checks.append({
            "check_id": cid,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {cid}: {'PASS' if passed else 'FAIL'}")

    print("=" * 120)
    print("2026 TEAM-AGGREGATE RIGHTS PRESSURE PREVIEW V1")
    print("=" * 120)
    print("Rights decision universe: 64")
    print("DECISIONS REVISED: NO")
    print("")
    print("Running checks...")

    add(
        "upstream_rights_preview_passed",
        bool(summary.get("passed")) and int(summary.get("decision_row_count", -1)) == 64,
        "64-player rights preview passed.",
    )
    add(
        "all_64_rows_grouped_once",
        sum(len(v) for v in by_team.values()) == 64,
        f"rows={sum(len(v) for v in by_team.values())}",
    )
    add(
        "all_30_teams_not_required_but_team_codes_present",
        all(team for team in by_team),
        f"teams_with_candidates={len(by_team)}",
        severity="diagnostic",
    )
    add(
        "marginal_rows_are_low_confidence_retains_only",
        all(
            r["confidence"].lower() == "low"
            and r["current_model_advisory"] == "retain_rights"
            for r in marginal_rows
        ),
        f"marginal={len(marginal_rows)}",
    )
    add(
        "no_decisions_revised_before_full_cap_inputs",
        all(not r["decisions_revised"] for r in team_rows),
        "Aggregate pressure is diagnostic only.",
    )
    add(
        "full_team_cap_room_model_explicitly_pending",
        all(
            not r["full_guaranteed_team_salary_integrated"]
            and not r["incomplete_roster_charges_integrated"]
            and not r["exception_strategy_integrated"]
            for r in team_rows
        ),
        "Guaranteed salary, roster charges, and exception strategy remain next inputs.",
        severity="diagnostic",
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
        r["check_id"] for r in checks
        if r["severity"] == "strict" and r["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_team_aggregate_rights_pressure_preview_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary_out = {
        "version": VERSION,
        "team_count_with_rights_candidates": len(team_rows),
        "rights_candidate_count": 64,
        "low_confidence_retain_candidate_count": len(marginal_rows),
        "high_pressure_team_count": sum(r["rights_hold_pressure_tier"] == "high" for r in team_rows),
        "medium_pressure_team_count": sum(r["rights_hold_pressure_tier"] == "medium" for r in team_rows),
        "low_pressure_team_count": sum(r["rights_hold_pressure_tier"] == "low" for r in team_rows),
        "decisions_revised": False,
        "full_guaranteed_team_salary_integrated": False,
        "incomplete_roster_charges_integrated": False,
        "exception_strategy_integrated": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Integrate exact guaranteed 2026-27 team salary, incomplete-roster charges, "
            "and exception strategy. Then allow only marginal rights decisions to move "
            "under team-level cap-room optimization before clone application."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_team_rights_pressure_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)
        write_csv(export / "team_rights_pressure_summary.csv", team_rows)
        write_csv(export / "marginal_retain_candidates.csv", marginal_rows)
        write_csv(export / "team_rights_pressure_checks.csv", checks)
        (export / "team_rights_pressure_summary.json").write_text(
            json.dumps(summary_out, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 TEAM-AGGREGATE RIGHTS PRESSURE PREVIEW V1

This layer is intentionally diagnostic.

It aggregates the already-passed 64-player rights-retention board by team and
identifies where retained cap holds are concentrated, plus the low-confidence
retain decisions most likely to change once full team cap-room inputs are added.

It DOES NOT revise any player decision yet.

Required before revision:
- exact guaranteed 2026-27 team salary
- incomplete-roster charges
- exception strategy / cap-space posture

No QO tender, rights retention, renouncement, cap hold, roster, or checkpoint
mutation occurs.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(export.iterdir()):
                z.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Team aggregate rights pressure preview failed: " + ", ".join(failed))

    print("")
    print("=" * 120)
    print("2026 TEAM-AGGREGATE RIGHTS PRESSURE PREVIEW V1 PASSED")
    print("=" * 120)
    print(f"Teams with rights candidates:      {len(team_rows)}")
    print(f"Low-confidence retain candidates: {len(marginal_rows)}")
    print("Decisions revised:                0")
    print("Checkpoint write:     NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
