from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import math
import pickle
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-team-guaranteed-salary-source-probe-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

SALARY_FIELD_RE = re.compile(
    r"(salary|compensation|guarantee|guaranteed|cap.?hit|contract.?amount|amount)",
    re.I,
)
CONTRACT_FIELD_RE = re.compile(
    r"(contract|salary|guarantee|option|cap|team|roster|status|year|season)",
    re.I,
)
TEAM_CODES = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
    "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def finite(value: Any) -> float | None:
    try:
        x = float(value)
    except Exception:
        return None
    if not math.isfinite(x):
        return None
    return x


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


def read_csv_member(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    text = z.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return {}
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


def simple_mapping(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if dataclasses.is_dataclass(obj):
        try:
            return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
        except Exception:
            pass
    try:
        return dict(vars(obj))
    except Exception:
        return {}


def flatten_candidate_fields(
    obj: Any,
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 3,
    seen: set[int] | None = None,
) -> list[tuple[str, Any, str]]:
    if seen is None:
        seen = set()

    if obj is None or depth > max_depth:
        return []

    oid = id(obj)
    if oid in seen:
        return []
    seen.add(oid)

    out: list[tuple[str, Any, str]] = []
    mapping = simple_mapping(obj)

    if not mapping:
        return out

    for key, value in mapping.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        scalar = isinstance(value, (str, int, float, bool, type(None)))

        if scalar:
            if CONTRACT_FIELD_RE.search(path):
                out.append((path, value, type(value).__name__))
            continue

        # Recurse only through contract/salary/team-ish branches, plus one
        # initial level so opaque nested objects can be discovered.
        if depth == 0 or CONTRACT_FIELD_RE.search(path):
            out.extend(
                flatten_candidate_fields(
                    value,
                    prefix=path,
                    depth=depth + 1,
                    max_depth=max_depth,
                    seen=seen,
                )
            )

    return out


def salary_numeric_rows(
    player_id: str,
    player_name: str,
    player: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_fields = []
    salary_rows = []

    for path, value, value_type in flatten_candidate_fields(player):
        row = {
            "player_id": player_id,
            "player_name": player_name,
            "field_path": path,
            "raw_value": clean(value),
            "value_type": value_type,
        }
        all_fields.append(row)

        if SALARY_FIELD_RE.search(path):
            number = finite(value)
            if number is not None and number >= 0:
                salary_rows.append({
                    **row,
                    "numeric_value": number,
                    "field_path_lower": path.lower(),
                    "looks_2026_27_specific": bool(
                        re.search(r"(2026|26.?27|year.?2|season.?2)", path, re.I)
                    ),
                    "looks_guaranteed_specific": bool(
                        re.search(r"(guarantee|guaranteed)", path, re.I)
                    ),
                    "looks_base_salary_specific": bool(
                        re.search(r"(base.?salary|salary)", path, re.I)
                    ),
                })

    return all_fields, salary_rows


def roster_membership_candidates(state: Any) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    state_map = simple_mapping(state)

    for root_key, root_val in state_map.items():
        if not re.search(r"(roster|team|lineup)", root_key, re.I):
            continue

        if isinstance(root_val, Mapping):
            for k, v in root_val.items():
                team_code = clean(k).upper()
                if team_code not in TEAM_CODES:
                    continue
                if isinstance(v, Mapping):
                    iterable = list(v.keys())
                elif isinstance(v, (list, tuple, set)):
                    iterable = list(v)
                else:
                    continue
                for item in iterable:
                    if isinstance(item, (str, int)):
                        result[pid(item)].add(team_code)
                    else:
                        item_map = simple_mapping(item)
                        candidate = ""
                        for id_key in ("player_id", "person_id", "id"):
                            if id_key in item_map:
                                candidate = pid(item_map[id_key])
                                break
                        if candidate:
                            result[candidate].add(team_code)

    return result


def main() -> int:
    root = Path.cwd().resolve()

    readiness_zip = find_latest(
        root,
        "fa_team_financial_posture_readiness_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )

    if readiness_zip is None or branch_zip is None or scenario_zip is None:
        raise RuntimeError(
            "Missing one or more required upstream audits: "
            "financial posture readiness, branch reconstruction, recommended scenario."
        )

    with zipfile.ZipFile(readiness_zip) as z:
        readiness_summary = read_json_member(
            z, "team_financial_posture_readiness_summary.json"
        )
        upstream_candidates = read_csv_member(z, "salary_candidate_values.csv")
        unique_candidates = read_csv_member(z, "unique_player_salary_candidates.csv")
        ambiguous_candidates = read_csv_member(z, "ambiguous_player_salary_candidates.csv")

    with zipfile.ZipFile(branch_zip) as z:
        branch_rows = read_csv_member(z, "branch_reconstruction_all_players.csv")

    with zipfile.ZipFile(scenario_zip) as z:
        final_market = read_csv_member(z, "recommended_final_market_226.csv")
        team_counts = read_csv_member(z, "team_counts_recommended_scenario.csv")

    market_ids = {pid(r.get("player_id")) for r in final_market if pid(r.get("player_id"))}
    branch_by_id = {pid(r.get("player_id")): r for r in branch_rows if pid(r.get("player_id"))}

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state = checkpoint.simulation_state
    before_state = object_digest(state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            f"Checkpoint mismatch. Expected {EXPECTED_CHECKPOINT_SHA256}, got {before_hash}"
        )

    players_raw = getattr(state, "players", {}) or {}
    players = {pid(k): v for k, v in players_raw.items()}
    roster_memberships = roster_membership_candidates(state)

    schema_fields: list[dict[str, Any]] = []
    checkpoint_salary_rows: list[dict[str, Any]] = []
    field_counter = Counter()
    salary_field_counter = Counter()

    for player_id, player in players.items():
        player_name = clean(
            getattr(player, "name", "")
            or getattr(player, "player_name", "")
            or getattr(player, "display_name", "")
        )
        fields, salaries = salary_numeric_rows(player_id, player_name, player)
        schema_fields.extend(fields)
        checkpoint_salary_rows.extend(salaries)
        for row in fields:
            field_counter[row["field_path"]] += 1
        for row in salaries:
            salary_field_counter[row["field_path"]] += 1

    field_summary = [
        {
            "field_path": field,
            "player_coverage_count": count,
            "coverage_pct_of_checkpoint_players": (
                count / len(players) if players else 0
            ),
            "is_salary_numeric_path": field in salary_field_counter,
            "salary_numeric_coverage_count": salary_field_counter.get(field, 0),
        }
        for field, count in field_counter.most_common()
    ]

    salary_path_summary = [
        {
            "field_path": field,
            "numeric_player_coverage_count": count,
            "coverage_pct_of_checkpoint_players": (
                count / len(players) if players else 0
            ),
            "looks_guaranteed_specific": bool(
                re.search(r"(guarantee|guaranteed)", field, re.I)
            ),
            "looks_2026_27_specific": bool(
                re.search(r"(2026|26.?27|year.?2|season.?2)", field, re.I)
            ),
        }
        for field, count in salary_field_counter.most_common()
    ]

    upstream_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in upstream_candidates:
        player_id = pid(row.get("player_id"))
        if player_id:
            upstream_by_id[player_id].append(row)

    checkpoint_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in checkpoint_salary_rows:
        checkpoint_by_id[row["player_id"]].append(row)

    crosswalk_rows = []
    attached_branch_rows = []

    for player_id, branch in branch_by_id.items():
        player_name = clean(branch.get("player_name"))
        owner = clean(
            branch.get("reconstructed_branch_owner")
            or branch.get("lifecycle_prior_team")
            or branch.get("prior_team")
        ).upper()
        in_market = player_id in market_ids

        # For the 582-player branch population, "not in final market" is the
        # branch-attached side. Supplements are audited separately downstream.
        branch_attached = not in_market

        if branch_attached:
            attached_branch_rows.append({
                "player_id": player_id,
                "player_name": player_name,
                "branch_owner": owner,
                "branch_attached": True,
            })

        cp_rows = checkpoint_by_id.get(player_id, [])
        up_rows = upstream_by_id.get(player_id, [])

        for cp in cp_rows or [None]:
            for up in up_rows or [None]:
                crosswalk_rows.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "branch_owner": owner,
                    "branch_attached": branch_attached,
                    "final_market": in_market,
                    "checkpoint_salary_field_path": (
                        cp["field_path"] if cp else ""
                    ),
                    "checkpoint_salary_numeric_value": (
                        cp["numeric_value"] if cp else ""
                    ),
                    "checkpoint_salary_looks_guaranteed": (
                        cp["looks_guaranteed_specific"] if cp else ""
                    ),
                    "checkpoint_salary_looks_2026_27": (
                        cp["looks_2026_27_specific"] if cp else ""
                    ),
                    "upstream_salary_candidate": (
                        up.get("salary_amount_candidate", "") if up else ""
                    ),
                    "upstream_salary_column": (
                        up.get("salary_column", "") if up else ""
                    ),
                    "upstream_status_context": (
                        up.get("status_context", "") if up else ""
                    ),
                    "upstream_source_member": (
                        up.get("source_member", "") if up else ""
                    ),
                    "roster_membership_candidates": "|".join(
                        sorted(roster_memberships.get(player_id, set()))
                    ),
                })

    # Candidate canonical paths are reported, not selected.
    likely_paths = [
        row for row in salary_path_summary
        if row["numeric_player_coverage_count"] >= max(1, int(len(players) * 0.25))
    ]

    exact_match_rows = []
    for player_id, cp_rows in checkpoint_by_id.items():
        ups = upstream_by_id.get(player_id, [])
        if not ups:
            continue
        up_values = {
            float(row["salary_amount_candidate"])
            for row in ups
            if finite(row.get("salary_amount_candidate")) is not None
        }
        for cp in cp_rows:
            if float(cp["numeric_value"]) in up_values:
                exact_match_rows.append({
                    "player_id": player_id,
                    "field_path": cp["field_path"],
                    "checkpoint_value": cp["numeric_value"],
                    "matches_upstream_candidate": True,
                })

    path_match_counts = Counter(row["field_path"] for row in exact_match_rows)
    path_match_summary = [
        {
            "field_path": path,
            "exact_value_match_count_against_upstream_candidates": count,
            "checkpoint_numeric_coverage_count": salary_field_counter.get(path, 0),
        }
        for path, count in path_match_counts.most_common()
    ]

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
    print("2026 TEAM GUARANTEED SALARY SOURCE PROBE V1")
    print("=" * 120)
    print("Running checks...")

    add(
        "upstream_financial_posture_readiness_passed",
        bool(readiness_summary.get("passed"))
        and int(readiness_summary.get("exact_roster_charge_team_count", -1)) == 30,
        "30-team financial posture readiness passed.",
    )
    add(
        "checkpoint_players_loaded",
        len(players) > 0,
        f"checkpoint_players={len(players)}",
    )
    add(
        "checkpoint_contract_salary_schema_discovered",
        len(checkpoint_salary_rows) > 0,
        (
            f"salary_numeric_rows={len(checkpoint_salary_rows)}; "
            f"distinct_salary_paths={len(salary_field_counter)}"
        ),
    )
    add(
        "branch_crosswalk_built",
        len(crosswalk_rows) > 0 and len(branch_by_id) == len(branch_rows),
        f"branch_rows={len(branch_rows)}; crosswalk_rows={len(crosswalk_rows)}",
    )
    add(
        "authoritative_salary_path_not_guessed",
        True,
        (
            "Probe exports field coverage and exact upstream value matches; "
            "it does not select a field or sum team salary."
        ),
    )
    add(
        "no_team_salary_total_declared",
        True,
        "Guaranteed team salary remains unresolved by design.",
    )

    after_state = object_digest(state)
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
    export_id = f"fa_team_guaranteed_salary_source_probe_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "checkpoint_player_count": len(players),
        "branch_player_count": len(branch_rows),
        "branch_attached_count": len(attached_branch_rows),
        "checkpoint_salary_numeric_row_count": len(checkpoint_salary_rows),
        "distinct_checkpoint_salary_field_path_count": len(salary_field_counter),
        "likely_high_coverage_salary_path_count": len(likely_paths),
        "exact_checkpoint_to_upstream_value_match_count": len(exact_match_rows),
        "unique_upstream_salary_candidate_count": len(unique_candidates),
        "ambiguous_upstream_salary_candidate_count": len(ambiguous_candidates),
        "authoritative_salary_path_selected": False,
        "guaranteed_team_salary_totals_computed": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Inspect salary_path_summary.csv and salary_path_upstream_match_summary.csv. "
            "Select the checkpoint field path only if its semantics and value matches prove "
            "it is the branch-safe 2026-27 guaranteed salary source. Then build exact team "
            "guaranteed salary totals, including the five zero-game supplement players and "
            "the simulator's option/guarantee decisions."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_guaranteed_salary_probe_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)

        write_csv(export / "checkpoint_contract_relevant_fields.csv", schema_fields)
        write_csv(export / "checkpoint_salary_numeric_candidates.csv", checkpoint_salary_rows)
        write_csv(export / "salary_field_path_summary.csv", salary_path_summary)
        write_csv(export / "salary_field_path_high_coverage.csv", likely_paths)
        write_csv(export / "salary_path_upstream_exact_matches.csv", exact_match_rows)
        write_csv(export / "salary_path_upstream_match_summary.csv", path_match_summary)
        write_csv(export / "branch_attached_players_582_population.csv", attached_branch_rows)
        write_csv(export / "checkpoint_upstream_salary_crosswalk.csv", crosswalk_rows)
        write_csv(export / "salary_source_probe_checks.csv", checks)

        (export / "salary_source_probe_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 TEAM GUARANTEED SALARY SOURCE PROBE V1

Purpose
-------
Identify the actual contract/salary schema stored in the canonical checkpoint
before calculating guaranteed 2026-27 team salary.

Why this exists
---------------
The financial-posture readiness audit found 739 salary candidates, but several
players have multiple values because upstream sources mix:
- base salary
- guaranteed salary
- Two-Way guarantee portions
- option salary
- partial guarantees

Selecting a number by uniqueness would therefore be unsafe.

This probe:
- introspects PlayerState and nested contract-like objects
- exports every salary/guarantee/contract field path
- measures player coverage by field path
- crosswalks checkpoint values against the 739 audited upstream candidates
- annotates reconstructed branch attachment and market status

It does NOT select an authoritative field.
It does NOT compute team salary totals.
It does NOT mutate state.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(export.iterdir()):
                z.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Team Guaranteed Salary Source Probe V1 failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 120)
    print("2026 TEAM GUARANTEED SALARY SOURCE PROBE V1 PASSED")
    print("=" * 120)
    print(f"Checkpoint players:                 {len(players)}")
    print(f"Branch attached players:            {len(attached_branch_rows)}")
    print(f"Checkpoint salary numeric rows:     {len(checkpoint_salary_rows)}")
    print(f"Distinct salary field paths:        {len(salary_field_counter)}")
    print(f"High-coverage salary paths:         {len(likely_paths)}")
    print(f"Exact checkpoint/upstream matches:  {len(exact_match_rows)}")
    print("Authoritative salary path selected: NO")
    print("Guaranteed team salary totals:      NOT COMPUTED")
    print("Checkpoint write:                   NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
