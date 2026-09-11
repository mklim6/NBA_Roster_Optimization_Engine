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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-full-market-team-salary-charge-readiness-v1-2026-08-15"
SEASON_LABEL = "2026-27"

EXPECTED_MARKET = 226
EXPECTED_RFA_EXACT = 64
ZERO_YOS_MINIMUM_2026_27 = 1_357_763.0
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

CBA_SOURCE = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)

RIGHTS_MAP = {
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

RIGHTS_FIELDS = {
    "rights_classification",
    "rights_status",
    "rights",
    "free_agent_rights",
    "final_rights",
    "rights_type",
}
PRIOR_SALARY_PATTERNS = [
    re.compile(r"prior.*salary", re.I),
    re.compile(r"2025.?26.*salary", re.I),
    re.compile(r"salary.*2025.?26", re.I),
    re.compile(r"prior_regular_salary", re.I),
]
CONTRACT_TYPE_PATTERNS = [
    re.compile(r"contract_type", re.I),
    re.compile(r"active_contract_type", re.I),
]


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def finite(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    try:
        number = float(text)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = clean(value).lower()
    return text in {"1", "true", "yes", "y", "t"}


def normalize_rights(value: Any) -> str:
    text = clean(value).lower().replace("_", " ")
    text = " ".join(text.split())
    return RIGHTS_MAP.get(text, "")


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
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def locate_rights_registry(root: Path) -> Path | None:
    candidates = []
    for pattern in (
        "fa_rights_registry_v2_preview_2026-27_*.zip",
        "*rights_registry*v2*2026-27*.zip",
    ):
        for p in root.rglob(pattern):
            if p.is_file() and p not in candidates:
                candidates.append(p)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def load_best_rights_registry(path: Path | None):
    if path is None:
        return [], ""
    with zipfile.ZipFile(path) as z:
        scored = []
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            if "rights" not in name.lower():
                continue
            try:
                rows = read_csv_member(z, name.split("/")[-1], required=False)
            except Exception:
                # direct read by full member if suffix collision issue
                try:
                    text = z.read(name).decode("utf-8-sig", errors="replace")
                    rows = list(csv.DictReader(io.StringIO(text))) if text.strip() else []
                except Exception:
                    continue
            if not rows:
                continue
            fields = {clean(k).lower() for k in rows[0].keys()}
            score = 0
            if "player_id" in fields:
                score += 5
            if any("right" in f for f in fields):
                score += 5
            if 150 <= len(rows) <= 220:
                score += 3
            scored.append((score, len(rows), name, rows))
        if not scored:
            return [], ""
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, member, rows = scored[0]
        return rows, member


def evidence_from_row(row: dict[str, str]) -> dict[str, Any]:
    rights = ""
    prior_salary = None
    contract_type = ""
    evidence_fields = []

    for key, value in row.items():
        lk = clean(key).lower()
        val = clean(value)
        if not val:
            continue

        if not rights and (
            lk in RIGHTS_FIELDS
            or ("right" in lk and "source" not in lk and "reason" not in lk)
        ):
            normalized = normalize_rights(val)
            if normalized:
                rights = normalized
                evidence_fields.append(f"{key}={val}")

        if prior_salary is None and any(p.search(lk) for p in PRIOR_SALARY_PATTERNS):
            number = finite(val)
            if number is not None and number > 0:
                prior_salary = number
                evidence_fields.append(f"{key}={val}")

        if not contract_type and any(p.search(lk) for p in CONTRACT_TYPE_PATTERNS):
            contract_type = val
            evidence_fields.append(f"{key}={val}")

    if not rights and "two-way" in contract_type.lower():
        rights = "two_way_special"

    return {
        "rights": rights,
        "prior_salary": prior_salary,
        "contract_type": contract_type,
        "evidence": " | ".join(evidence_fields),
    }


def scan_lifecycle_evidence(root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    path = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    if path is None:
        return {}, ""

    with zipfile.ZipFile(path) as z:
        rows = read_csv_member(z, "contract_option_lifecycle_all.csv")
    result = {}
    for row in rows:
        player_id = pid(row.get("player_id"))
        if not player_id:
            continue
        result[player_id] = evidence_from_row(row)
    return result, str(path)


def formula_family(rights: str, exact_rfa: bool) -> str:
    if exact_rfa:
        return "already_exact_rfa_free_agent_amount"
    if rights == "two_way_special":
        return "two_way_zero_yos_minimum"
    if rights == "bird":
        return "bird_threshold_formula"
    if rights == "early_bird":
        return "early_bird_130_pct_with_floor_cap"
    if rights == "non_bird":
        return "non_bird_120_pct_with_floor_cap"
    if rights == "not_applicable":
        return "applicability_review_required"
    return "rights_classification_required"


def main() -> int:
    root = Path.cwd().resolve()

    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )
    cap_zip = find_latest(
        root,
        "fa_qo_cap_hold_completion_v1_0_1_2026-27_*.zip",
    )
    qo_zip = find_latest(
        root,
        "fa_qo_issuance_decision_preview_v1_2026-27_*.zip",
    )

    if scenario_zip is None or cap_zip is None or qo_zip is None:
        raise RuntimeError(
            "Missing required final-market, exact-RFA-cap-hold, or QO preview audit."
        )

    with zipfile.ZipFile(scenario_zip) as z:
        scenario_summary = read_json_member(z, "recommended_scenario_summary.json")
        market_rows = read_csv_member(z, "recommended_final_market_226.csv")

    with zipfile.ZipFile(cap_zip) as z:
        cap_summary = read_json_member(z, "qo_cap_hold_completion_summary.json")
        exact_cap_rows = read_csv_member(z, "qo_exact_cap_holds_completed_64.csv")

    with zipfile.ZipFile(qo_zip) as z:
        qo_summary = read_json_member(z, "qo_issuance_preview_summary.json")
        qo_rows = read_csv_member(z, "qo_issuance_decision_board_64.csv")

    if len(market_rows) != EXPECTED_MARKET:
        raise RuntimeError(f"Expected {EXPECTED_MARKET} final-market rows, got {len(market_rows)}.")
    if len(exact_cap_rows) != EXPECTED_RFA_EXACT:
        raise RuntimeError(f"Expected {EXPECTED_RFA_EXACT} exact RFA cap-hold rows.")
    if len(qo_rows) != EXPECTED_RFA_EXACT:
        raise RuntimeError(f"Expected {EXPECTED_RFA_EXACT} QO decision rows.")

    exact_by_id = {pid(r.get("player_id")): r for r in exact_cap_rows}
    qo_by_id = {pid(r.get("player_id")): r for r in qo_rows}

    rights_zip = locate_rights_registry(root)
    rights_rows, rights_member = load_best_rights_registry(rights_zip)
    rights_by_id = {
        pid(r.get("player_id")): evidence_from_row(r)
        for r in rights_rows
        if pid(r.get("player_id"))
    }
    lifecycle_by_id, lifecycle_source = scan_lifecycle_evidence(root)

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before full-market charge readiness.")

    output_rows = []
    rfa_effective_rows = []
    non_rfa_rows = []

    for market in market_rows:
        player_id = pid(market.get("player_id"))
        player_name = clean(market.get("player_name"))
        prior_team = clean(
            market.get("prior_team")
            or market.get("team")
            or market.get("team_abbreviation")
        ).upper()

        exact = exact_by_id.get(player_id)
        qo = qo_by_id.get(player_id)

        rights_evidence = rights_by_id.get(player_id, {})
        lifecycle_evidence = lifecycle_by_id.get(player_id, {})

        rights = clean(rights_evidence.get("rights"))
        prior_salary = rights_evidence.get("prior_salary")
        contract_type = clean(rights_evidence.get("contract_type"))
        evidence_source = "rights_registry"
        evidence_detail = clean(rights_evidence.get("evidence"))

        if not rights:
            rights = clean(lifecycle_evidence.get("rights"))
            if prior_salary is None:
                prior_salary = lifecycle_evidence.get("prior_salary")
            if not contract_type:
                contract_type = clean(lifecycle_evidence.get("contract_type"))
            if rights:
                evidence_source = "lifecycle"
                evidence_detail = clean(lifecycle_evidence.get("evidence"))

        exact_rfa = exact is not None
        family = formula_family(rights, exact_rfa)

        fa_amount = (
            finite(exact.get("exact_cap_hold_2026_27"))
            if exact_rfa else None
        )
        qo_amount = (
            finite(qo.get("exact_qo_amount"))
            if qo is not None else None
        )
        qo_model = clean(qo.get("model_recommendation")) if qo else ""
        qo_final = clean(qo.get("recommendation")) if qo else ""

        effective_if_rights_retained = None
        effective_issue_qo_scenario = None
        effective_no_qo_scenario = None

        if exact_rfa and fa_amount is not None:
            effective_no_qo_scenario = fa_amount
            if qo_amount is not None:
                effective_issue_qo_scenario = max(fa_amount, qo_amount)

            if qo_final == "issue_qo":
                effective_if_rights_retained = effective_issue_qo_scenario
            elif qo_final == "do_not_issue_qo":
                effective_if_rights_retained = effective_no_qo_scenario
            elif qo_final == "user_decision_required":
                effective_if_rights_retained = None

        exact_non_rfa_ready = False
        provisional_amount = None
        blockers = []

        if not exact_rfa:
            if family == "two_way_zero_yos_minimum":
                provisional_amount = ZERO_YOS_MINIMUM_2026_27
                exact_non_rfa_ready = True
            elif family == "bird_threshold_formula":
                if prior_salary is None:
                    blockers.append("prior_salary_required")
                blockers.append("estimated_average_player_salary_threshold_required")
                blockers.append("minimum_maximum_floor_cap_validation_required")
            elif family in {
                "early_bird_130_pct_with_floor_cap",
                "non_bird_120_pct_with_floor_cap",
            }:
                if prior_salary is None:
                    blockers.append("prior_salary_required")
                blockers.append("minimum_maximum_floor_cap_validation_required")
            elif family == "applicability_review_required":
                blockers.append("free_agent_amount_applicability_review_required")
            else:
                blockers.append("free_agent_rights_classification_required")

        row = {
            "player_id": player_id,
            "player_name": player_name,
            "prior_team_from_market": prior_team,
            "exact_rfa_free_agent_amount_available": exact_rfa,
            "rights_classification": rights,
            "rights_evidence_source": evidence_source if rights else "",
            "rights_evidence_detail": evidence_detail,
            "prior_salary_evidence": prior_salary if prior_salary is not None else "",
            "active_contract_type_at_split": contract_type,
            "free_agent_amount_formula_family": family,
            "exact_free_agent_amount_2026_27": (
                fa_amount if fa_amount is not None
                else provisional_amount if exact_non_rfa_ready
                else ""
            ),
            "exact_non_rfa_amount_ready": exact_non_rfa_ready,
            "readiness_blockers": "|".join(blockers),
            "qo_amount": qo_amount if qo_amount is not None else "",
            "qo_model_recommendation": qo_model,
            "qo_user_or_cpu_recommendation": qo_final,
            "effective_team_salary_charge_if_qo_issued_and_rights_retained": (
                effective_issue_qo_scenario if effective_issue_qo_scenario is not None else ""
            ),
            "effective_team_salary_charge_if_no_qo_and_rights_retained": (
                effective_no_qo_scenario if effective_no_qo_scenario is not None else ""
            ),
            "effective_team_salary_charge_under_current_qo_preview": (
                effective_if_rights_retained if effective_if_rights_retained is not None else ""
            ),
            "renouncement_applied": False,
            "qo_tender_applied": False,
            "team_salary_charge_applied": False,
            "state_mutation_applied": False,
        }
        output_rows.append(row)

        if exact_rfa:
            rfa_effective_rows.append(row)
        else:
            non_rfa_rows.append(row)

    rights_resolved_non_rfa = [
        r for r in non_rfa_rows
        if r["rights_classification"]
    ]
    exact_non_rfa = [
        r for r in non_rfa_rows
        if bool(r["exact_non_rfa_amount_ready"])
    ]
    rights_unresolved = [
        r for r in non_rfa_rows
        if not r["rights_classification"]
    ]
    formula_blocked = [
        r for r in non_rfa_rows
        if r["rights_classification"]
        and not bool(r["exact_non_rfa_amount_ready"])
    ]

    family_counts = Counter(r["free_agent_amount_formula_family"] for r in output_rows)
    rights_counts = Counter(r["rights_classification"] or "unresolved" for r in output_rows)

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
    print("2026 FULL-MARKET TEAM SALARY CHARGE READINESS V1")
    print("=" * 128)
    print("Running checks...")

    add(
        "recommended_final_market_passed",
        bool(scenario_summary.get("passed"))
        and int(scenario_summary.get("recommended_final_market_count", -1)) == 226,
        "226-player recommended final market.",
    )
    add(
        "exact_64_rfa_free_agent_amounts_passed",
        bool(cap_summary.get("passed"))
        and int(cap_summary.get("exact_cap_hold_count", -1)) == 64,
        "64/64 RFA Free Agent Amounts available.",
    )
    add(
        "qo_preview_passed",
        bool(qo_summary.get("passed"))
        and int(qo_summary.get("decision_row_count", -1)) == 64,
        "64-player QO preview available.",
    )
    add(
        "exact_226_market_charge_readiness_rows",
        len(output_rows) == 226
        and len({r["player_id"] for r in output_rows}) == 226,
        f"rows={len(output_rows)}",
    )
    add(
        "rfa_effective_charge_uses_greater_of_hold_or_qo",
        all(
            (
                not clean(r["effective_team_salary_charge_if_qo_issued_and_rights_retained"])
            )
            or float(r["effective_team_salary_charge_if_qo_issued_and_rights_retained"])
            == max(float(r["exact_free_agent_amount_2026_27"]), float(r["qo_amount"]))
            for r in rfa_effective_rows
        ),
        "CBA Article VII 4(a)(2)(ii) reflected.",
    )
    add(
        "non_rfa_amounts_not_guessed",
        all(
            bool(r["exact_non_rfa_amount_ready"])
            or clean(r["readiness_blockers"])
            for r in non_rfa_rows
        ),
        "Every non-RFA row is exact or explicitly blocked.",
    )
    add(
        "no_qo_renouncement_or_team_salary_mutation",
        all(
            not r["renouncement_applied"]
            and not r["qo_tender_applied"]
            and not r["team_salary_charge_applied"]
            and not r["state_mutation_applied"]
            for r in output_rows
        ),
        "Readiness only.",
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
    export_id = (
        f"fa_full_market_team_salary_charge_readiness_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "final_market_count": len(output_rows),
        "exact_rfa_free_agent_amount_count": len(rfa_effective_rows),
        "non_rfa_market_count": len(non_rfa_rows),
        "non_rfa_rights_resolved_count": len(rights_resolved_non_rfa),
        "non_rfa_rights_unresolved_count": len(rights_unresolved),
        "non_rfa_exact_amount_ready_count": len(exact_non_rfa),
        "non_rfa_formula_or_validation_blocked_count": len(formula_blocked),
        "rights_classification_counts": dict(sorted(rights_counts.items())),
        "formula_family_counts": dict(sorted(family_counts.items())),
        "rights_registry_zip": str(rights_zip) if rights_zip else "",
        "rights_registry_member": rights_member,
        "lifecycle_source": lifecycle_source,
        "rfa_qo_effective_charge_rule": "max(free_agent_amount, outstanding_qo)",
        "qo_tenders_applied": 0,
        "renouncements_applied": 0,
        "team_salary_charges_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Resolve only the non-RFA rights-unresolved rows and formula blockers. "
            "Do not calculate true 30-team cap room until every applicable Veteran "
            "Free Agent in the 226-player final market has an exact Free Agent Amount."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_full_market_charge_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)

        write_csv(export / "full_market_team_salary_charge_readiness_226.csv", output_rows)
        write_csv(export / "rfa_effective_charge_readiness_64.csv", rfa_effective_rows)
        write_csv(export / "non_rfa_market_readiness.csv", non_rfa_rows)
        write_csv(export / "non_rfa_rights_unresolved.csv", rights_unresolved)
        write_csv(export / "non_rfa_formula_blocked.csv", formula_blocked)
        write_csv(export / "non_rfa_exact_amount_ready.csv", exact_non_rfa)
        write_csv(export / "full_market_charge_readiness_checks.csv", checks)

        (export / "full_market_charge_readiness_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 FULL-MARKET TEAM SALARY CHARGE READINESS V1
=================================================

Architecture correction
-----------------------
True cap room cannot be calculated using only the 64 RFA/QO players.

Under Article VII Section 4(a)(2):
- an Unrestricted Veteran Free Agent is included in Team Salary at his
  Free Agent Amount;
- a Restricted Veteran Free Agent is included at the greater of his Free
  Agent Amount, outstanding Qualifying Offer, or applicable first-refusal
  notice amount.

This audit therefore maps the entire 226-player recommended final market.

It freezes the exact 64 RFA Free Agent Amounts already completed and calculates
the two QO/no-QO retained-rights charge scenarios for them.

For the other 162 market players it searches the verified rights registry and
contract-lifecycle evidence, then reports whether the exact Free Agent Amount
is already ready or precisely what remains missing.

No free-agent amount is silently treated as zero.
No QO is tendered.
No rights are renounced.
No Team Salary charge is applied.
No checkpoint write occurs.
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
            "Full-Market Team Salary Charge Readiness V1 failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 128)
    print("2026 FULL-MARKET TEAM SALARY CHARGE READINESS V1 PASSED")
    print("=" * 128)
    print("Final market:                       226")
    print("Exact RFA Free Agent Amounts:        64")
    print(f"Non-RFA market rows:                {len(non_rfa_rows)}")
    print(f"Non-RFA rights resolved:            {len(rights_resolved_non_rfa)}")
    print(f"Non-RFA rights unresolved:          {len(rights_unresolved)}")
    print(f"Non-RFA exact amount ready:         {len(exact_non_rfa)}")
    print(f"Non-RFA formula/validation blocked: {len(formula_blocked)}")
    print("QO tenders applied:                   0")
    print("Renouncements applied:                0")
    print("Checkpoint write:         NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
