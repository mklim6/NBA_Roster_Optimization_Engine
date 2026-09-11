from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-team-financial-posture-readiness-v1-2026-08-15"
SEASON_LABEL = "2026-27"

SALARY_CAP = 164_961_000.0
ZERO_YOS_MINIMUM = 1_357_763.0
INCOMPLETE_ROSTER_STANDARD = 12

EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
TEAM_CODES = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
    "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}

SOURCE_PATTERNS = [
    "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip",
    "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    "fa_unified_offseason_decision_preview_v1_1_2026-27_*.zip",
    "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
]

SALARY_HINT = re.compile(r"(salary|compensation|cap[_ ]?hit|amount)", re.I)
SEASON_HINT = re.compile(r"(2026.?27|26.?27|salary_2026|2026_salary)", re.I)
PLAYER_ID_HINTS = {"player_id", "person_id", "nba_player_id"}
PLAYER_NAME_HINTS = {"player_name", "name", "player"}
TEAM_HINTS = {
    "team", "team_abbreviation", "team_code", "branch_owner",
    "reconstructed_branch_owner", "prior_team", "current_team",
}
STATUS_HINT = re.compile(
    r"(status|lifecycle|decision|contract|roster|market|classification)", re.I
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
    return x if x >= 0 else None


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


def read_csv_member(z: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    text = z.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(z: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(name).decode("utf-8-sig"))


def read_csv_suffix(z: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return read_csv_member(z, name)


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


def find_col(fields: list[str], candidates: set[str]) -> str:
    lowered = {clean(f).lower(): f for f in fields}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    return ""


def discover_salary_candidates(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    schema_rows: list[dict[str, Any]] = []
    value_rows: list[dict[str, Any]] = []

    source_zips = []
    for pattern in SOURCE_PATTERNS:
        p = find_latest(root, pattern)
        if p and p not in source_zips:
            source_zips.append(p)

    for zip_path in source_zips:
        try:
            with zipfile.ZipFile(zip_path) as z:
                for member in z.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    try:
                        rows = read_csv_member(z, member)
                    except Exception:
                        continue
                    if not rows:
                        continue

                    fields = list(rows[0].keys())
                    id_col = find_col(fields, PLAYER_ID_HINTS)
                    name_col = find_col(fields, PLAYER_NAME_HINTS)
                    team_col = find_col(fields, TEAM_HINTS)

                    salary_cols = [
                        f for f in fields
                        if SALARY_HINT.search(clean(f))
                        and (
                            SEASON_HINT.search(clean(f))
                            or "salary" in clean(f).lower()
                        )
                    ]
                    status_cols = [f for f in fields if STATUS_HINT.search(clean(f))]

                    schema_rows.append({
                        "source_zip": str(zip_path),
                        "member": member,
                        "row_count": len(rows),
                        "player_id_col": id_col,
                        "player_name_col": name_col,
                        "team_col": team_col,
                        "salary_columns": "|".join(salary_cols),
                        "status_columns": "|".join(status_cols),
                    })

                    if not salary_cols or not (id_col or name_col):
                        continue

                    for row in rows:
                        player_id = pid(row.get(id_col)) if id_col else ""
                        player_name = clean(row.get(name_col)) if name_col else ""
                        team = clean(row.get(team_col)).upper() if team_col else ""
                        status_blob = " | ".join(
                            f"{c}={clean(row.get(c))}"
                            for c in status_cols
                            if clean(row.get(c))
                        )

                        for salary_col in salary_cols:
                            amount = fnum(row.get(salary_col))
                            if amount is None or amount <= 0:
                                continue
                            value_rows.append({
                                "player_id": player_id,
                                "player_name": player_name,
                                "team": team,
                                "salary_amount_candidate": amount,
                                "salary_column": salary_col,
                                "status_context": status_blob,
                                "source_zip": str(zip_path),
                                "source_member": member,
                            })
        except Exception:
            continue

    return schema_rows, value_rows


def team_counts_from_pressure(team_pressure_rows: list[dict[str, str]]) -> dict[str, int]:
    # This is candidate count, not roster count. Kept separate on purpose.
    return {
        clean(r["team"]).upper(): int(float(clean(r["candidate_count"]) or 0))
        for r in team_pressure_rows
    }


def main() -> int:
    root = Path.cwd().resolve()

    pressure_zip = find_latest(
        root,
        "fa_team_aggregate_rights_pressure_preview_v1_2026-27_*.zip",
    )
    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )

    if pressure_zip is None:
        raise RuntimeError("Missing team aggregate rights pressure audit.")
    if scenario_zip is None:
        raise RuntimeError("Missing recommended final market scenario audit.")

    with zipfile.ZipFile(pressure_zip) as z:
        pressure_summary = read_json_member(z, "team_rights_pressure_summary.json")
        pressure_rows = read_csv_suffix(z, "team_rights_pressure_summary.csv")
        marginal_rows = read_csv_suffix(z, "marginal_retain_candidates.csv")

    with zipfile.ZipFile(scenario_zip) as z:
        scenario_summary = read_json_member(z, "recommended_scenario_summary.json")
        team_rows = read_csv_suffix(z, "team_counts_recommended_scenario.csv")

    # Resolve recommended scenario roster-count column flexibly.
    roster_count_by_team: dict[str, int] = {}
    roster_schema_issue = ""
    if team_rows:
        fields = list(team_rows[0].keys())
        team_col = find_col(fields, {"team", "team_abbreviation", "team_code"})
        count_candidates = [
            f for f in fields
            if "roster" in clean(f).lower() and "count" in clean(f).lower()
        ]
        preferred = next(
            (f for f in count_candidates if "recommended" in clean(f).lower()),
            count_candidates[0] if count_candidates else "",
        )
        if team_col and preferred:
            for row in team_rows:
                t = clean(row.get(team_col)).upper()
                v = fnum(row.get(preferred))
                if t in TEAM_CODES and v is not None:
                    roster_count_by_team[t] = int(v)
        else:
            roster_schema_issue = (
                f"team_col={team_col!r}; roster_count_candidates={count_candidates!r}"
            )

    schema_rows, salary_candidate_rows = discover_salary_candidates(root)

    # This readiness layer refuses to guess guaranteed salary from candidate
    # salary fields. It only reports unique player-level values and ambiguity.
    player_salary_values: dict[str, set[float]] = defaultdict(set)
    player_names: dict[str, str] = {}
    player_teams: dict[str, set[str]] = defaultdict(set)

    for row in salary_candidate_rows:
        key = row["player_id"] or ("NAME:" + row["player_name"])
        if not key or key == "NAME:":
            continue
        player_salary_values[key].add(float(row["salary_amount_candidate"]))
        if row["player_name"]:
            player_names[key] = row["player_name"]
        if row["team"] in TEAM_CODES:
            player_teams[key].add(row["team"])

    unique_salary_rows, ambiguous_salary_rows = [], []
    for key, values in sorted(player_salary_values.items()):
        row = {
            "player_key": key,
            "player_name": player_names.get(key, ""),
            "salary_values": "|".join(str(v) for v in sorted(values)),
            "team_candidates": "|".join(sorted(player_teams.get(key, set()))),
            "candidate_value_count": len(values),
        }
        if len(values) == 1:
            row["unique_salary_candidate"] = next(iter(values))
            unique_salary_rows.append(row)
        else:
            ambiguous_salary_rows.append(row)

    # Exact roster charges can be computed independently once scenario roster
    # count is known. They are diagnostics until guaranteed salary is solved.
    roster_charge_rows = []
    for team in sorted(TEAM_CODES):
        count = roster_count_by_team.get(team)
        if count is None:
            roster_charge_rows.append({
                "team": team,
                "recommended_scenario_roster_count": "",
                "incomplete_roster_slots": "",
                "incomplete_roster_charge": "",
                "ready": False,
            })
            continue

        slots = max(0, INCOMPLETE_ROSTER_STANDARD - count)
        charge = slots * ZERO_YOS_MINIMUM
        roster_charge_rows.append({
            "team": team,
            "recommended_scenario_roster_count": count,
            "incomplete_roster_slots": slots,
            "incomplete_roster_charge": charge,
            "ready": True,
        })

    exact_roster_charge_count = sum(bool(r["ready"]) for r in roster_charge_rows)

    # Team financial posture cannot be declared exact until guaranteed salary
    # source is proven. Still export a targeted worklist for the next slice.
    posture_rows = []
    for team in sorted(TEAM_CODES):
        pressure = next((r for r in pressure_rows if clean(r["team"]).upper() == team), None)
        roster = next(r for r in roster_charge_rows if r["team"] == team)
        posture_rows.append({
            "team": team,
            "recommended_scenario_roster_count": roster["recommended_scenario_roster_count"],
            "incomplete_roster_charge": roster["incomplete_roster_charge"],
            "model_retained_cap_hold_total": (
                pressure["model_retained_cap_hold_total"] if pressure else 0
            ),
            "rights_hold_pressure_tier": (
                pressure["rights_hold_pressure_tier"] if pressure else "none"
            ),
            "guaranteed_2026_27_team_salary": "",
            "guaranteed_salary_ready": False,
            "cap_space_before_rights": "",
            "cap_space_after_model_retained_rights": "",
            "preliminary_exception_posture": "pending_guaranteed_salary",
            "full_team_financial_posture_ready": False,
        })

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before team financial posture readiness."
        )

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
    print("2026 TEAM FINANCIAL POSTURE READINESS V1")
    print("=" * 120)
    print("Running checks...")

    add(
        "upstream_team_rights_pressure_preview_passed",
        bool(pressure_summary.get("passed"))
        and int(pressure_summary.get("rights_candidate_count", -1)) == 64,
        "64-player aggregate rights pressure preview passed.",
    )
    add(
        "recommended_market_scenario_passed",
        bool(scenario_summary.get("passed")),
        "Recommended scenario audit passed.",
    )
    add(
        "all_30_team_roster_counts_resolved",
        exact_roster_charge_count == 30,
        f"resolved={exact_roster_charge_count}/30; schema_issue={roster_schema_issue}",
    )
    add(
        "incomplete_roster_charge_rule_ready",
        all(
            (not r["ready"])
            or float(r["incomplete_roster_charge"])
            == max(0, INCOMPLETE_ROSTER_STANDARD - int(r["recommended_scenario_roster_count"])) * ZERO_YOS_MINIMUM
            for r in roster_charge_rows
        ),
        f"standard={INCOMPLETE_ROSTER_STANDARD}; zero_yos_minimum={ZERO_YOS_MINIMUM}",
    )
    add(
        "salary_source_discovery_completed",
        len(schema_rows) > 0,
        f"csv_sources_scanned={len(schema_rows)}; salary_candidates={len(salary_candidate_rows)}",
        severity="diagnostic",
    )
    add(
        "guaranteed_salary_is_not_guessed",
        all(not r["guaranteed_salary_ready"] for r in posture_rows),
        "Readiness layer deliberately refuses to infer guaranteed team salary from ambiguous candidate fields.",
    )
    add(
        "marginal_rights_decisions_not_revised",
        len(marginal_rows) == int(pressure_summary.get("low_confidence_retain_candidate_count", -1)),
        f"marginal={len(marginal_rows)}; decisions_revised=0",
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
    export_id = f"fa_team_financial_posture_readiness_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary_out = {
        "version": VERSION,
        "team_count": 30,
        "exact_roster_charge_team_count": exact_roster_charge_count,
        "salary_source_schema_count": len(schema_rows),
        "salary_candidate_row_count": len(salary_candidate_rows),
        "unique_player_salary_candidate_count": len(unique_salary_rows),
        "ambiguous_player_salary_candidate_count": len(ambiguous_salary_rows),
        "guaranteed_salary_team_count_ready": 0,
        "full_team_financial_posture_ready_count": 0,
        "marginal_rights_decision_count": len(marginal_rows),
        "rights_decisions_revised": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Use the exported salary-source schema and candidate tables to select the exact "
            "pre-split 2026-27 guaranteed salary source for each attached player. Once all "
            "30 guaranteed team-salary totals are proven, combine them with the exact roster "
            "charges and retained cap holds to compute true cap-space posture and revise only "
            "the marginal rights decisions."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_team_financial_ready_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)
        write_csv(export / "team_financial_posture_readiness_30.csv", posture_rows)
        write_csv(export / "incomplete_roster_charges_30.csv", roster_charge_rows)
        write_csv(export / "salary_source_schema_discovery.csv", schema_rows)
        write_csv(export / "salary_candidate_values.csv", salary_candidate_rows)
        write_csv(export / "unique_player_salary_candidates.csv", unique_salary_rows)
        write_csv(export / "ambiguous_player_salary_candidates.csv", ambiguous_salary_rows)
        write_csv(export / "marginal_rights_candidates_carried_forward.csv", marginal_rows)
        write_csv(export / "team_financial_posture_readiness_checks.csv", checks)
        (export / "team_financial_posture_readiness_summary.json").write_text(
            json.dumps(summary_out, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 TEAM FINANCIAL POSTURE READINESS V1

Purpose:
Assemble the remaining inputs needed before the team-level rights optimizer
is allowed to revise any marginal retain/renounce decisions.

This audit resolves exact incomplete-roster charges from the recommended
scenario roster counts and scans all relevant upstream audit ZIPs for candidate
2026-27 salary fields.

It intentionally DOES NOT guess guaranteed team salary from ambiguous fields.
Instead it exports:
- salary source schemas
- every numeric salary candidate
- unique player-level candidates
- ambiguous player-level candidates

Once the exact pre-split guaranteed salary source is identified, the next
slice can compute true cap-space posture and then reconsider only the marginal
rights-retention calls.

No rights decision, QO, cap hold, roster, contract, or checkpoint mutation.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(export.iterdir()):
                z.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Team Financial Posture Readiness V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 120)
    print("2026 TEAM FINANCIAL POSTURE READINESS V1 PASSED")
    print("=" * 120)
    print(f"Exact incomplete-roster charges:   {exact_roster_charge_count}/30")
    print(f"Salary source schemas discovered:  {len(schema_rows)}")
    print(f"Salary candidate rows:             {len(salary_candidate_rows)}")
    print(f"Unique player salary candidates:   {len(unique_salary_rows)}")
    print(f"Ambiguous player salary candidates:{len(ambiguous_salary_rows)}")
    print("Guaranteed team salary finalized:  0/30")
    print("Rights decisions revised:          0")
    print("Checkpoint write:       NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
