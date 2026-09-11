from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-corrected-rfa-qo-universe-v2-preview-2026-08-14"
SEASON_LABEL = "2026-27"

VFA_CATEGORY = "veteran_free_agent"
NON_VFA_CATEGORIES = {
    "waiver_terminated_free_agent",
    "ten_day_free_agent",
}

ELIGIBLE_PATHS = {
    "rookie_scale_second_option_year_complete",
    "veteran_free_agent_three_or_fewer_yos",
    "completing_two_way_contract_15_day_gp_proven",
    "completing_two_way_contract_15_day_official_rfa_proven",
}

TWO_WAY_MANUAL_PATH = "completing_two_way_contract_15_day_evidence_required"


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"true", "1", "yes"}


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
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


def classify(row: dict[str, str]) -> tuple[str, str, str]:
    category = clean(row.get("free_agent_category"))
    rights = clean(row.get("rights_classification"))
    prior_status = clean(row.get("prior_rfa_eligibility_status"))
    prior_path = clean(row.get("prior_rfa_eligibility_path"))
    rookie_exception = truthy(
        row.get("rookie_scale_first_round_option_exception")
    )

    if category in NON_VFA_CATEGORIES:
        return (
            "not_applicable",
            "not_veteran_free_agent",
            "Waiver-terminated and 10-Day free agents do not enter this Veteran FA RFA/QO resolver.",
        )

    if category != VFA_CATEGORY:
        return (
            "manual_review",
            "free_agent_category_unresolved",
            "Corrected market candidate is not mapped to the canonical Veteran FA or non-VFA categories.",
        )

    if rookie_exception:
        return (
            "not_eligible",
            "rookie_scale_option_decline_forces_ufa",
            "First-round Rookie Scale option was not exercised before the simulation split, so the ordinary <=3-YOS RFA pathway is excluded.",
        )

    if rights == "unknown":
        return (
            "manual_review",
            "rights_unresolved",
            "Veteran FA rights/category evidence is still unresolved and must not enter automatic QO logic.",
        )

    if prior_status == "eligible_if_qo_issued" and prior_path in ELIGIBLE_PATHS:
        return (
            "eligible_if_qo_issued",
            prior_path,
            "Prior structural RFA proof survives the corrected contract-option lifecycle universe.",
        )

    if prior_status == "manual_review" and prior_path == TWO_WAY_MANUAL_PATH:
        return (
            "manual_review",
            "two_way_15_day_evidence_required",
            "Two-Way contract finish is proven, but the 15-day Active/Inactive List prerequisite remains unresolved.",
        )

    if (
        prior_status == "not_eligible"
        and prior_path == "veteran_free_agent_over_three_yos"
    ):
        return (
            "not_eligible",
            "veteran_free_agent_over_three_yos",
            "Veteran FA has more than three Years of Service and no proven rookie-scale or Two-Way RFA exception.",
        )

    return (
        "manual_review",
        "unmapped_prior_rfa_state",
        f"Corrected market row does not map safely from prior RFA state: status={prior_status}; path={prior_path}.",
    )


def main() -> int:
    root = Path.cwd().resolve()

    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )
        market_rows = read_csv_member(
            archive,
            "corrected_free_agent_market_candidates.csv",
        )
        all_lifecycle_rows = read_csv_member(
            archive,
            "contract_option_lifecycle_all.csv",
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

    print("=" * 122, flush=True)
    print("CORRECTED 2026 RFA + QO UNIVERSE V2 PREVIEW", flush=True)
    print("=" * 122, flush=True)
    print(f"Lifecycle input: {lifecycle_zip}", flush=True)
    print(
        f"Corrected FA market candidates: {len(market_rows)}",
        flush=True,
    )
    print(
        "READ-ONLY: no QO, RFA status, option decision, cap hold, rights overlay, or checkpoint mutation.",
        flush=True,
    )
    print("", flush=True)

    output_rows: list[dict[str, Any]] = []

    for row in market_rows:
        disposition, path, reason = classify(row)

        updated = dict(row)
        updated["corrected_rfa_qo_disposition"] = disposition
        updated["corrected_rfa_qo_path"] = path
        updated["corrected_rfa_qo_reason"] = reason
        updated["qualifying_offer_issued"] = False
        updated["rfa_status_applied"] = False
        updated["offer_sheet_created"] = False
        updated["right_of_first_refusal_created"] = False
        updated["prior_qo_amount_v1_live_usable"] = False

        output_rows.append(updated)

    eligible = [
        r for r in output_rows
        if r["corrected_rfa_qo_disposition"]
        == "eligible_if_qo_issued"
    ]
    manual = [
        r for r in output_rows
        if r["corrected_rfa_qo_disposition"]
        == "manual_review"
    ]
    not_eligible = [
        r for r in output_rows
        if r["corrected_rfa_qo_disposition"]
        == "not_eligible"
    ]
    not_applicable = [
        r for r in output_rows
        if r["corrected_rfa_qo_disposition"]
        == "not_applicable"
    ]

    pending_or_under_contract = [
        r for r in all_lifecycle_rows
        if clean(r.get("contract_lifecycle_state")).startswith("pending_")
        or clean(r.get("contract_lifecycle_state")).startswith("under_contract_")
    ]

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("Running strict corrected-universe checks...", flush=True)

    check(
        "lifecycle_preview_passed",
        bool(lifecycle_summary.get("passed")),
        "Corrected RFA universe must start from a passed contract-option lifecycle audit.",
    )
    check(
        "exact_132_market_candidates_preserved",
        len(output_rows) == 132
        and len({pid(r.get("player_id")) for r in output_rows}) == 132,
        f"rows={len(output_rows)}",
    )
    check(
        "market_is_78_vfa_plus_54_non_vfa",
        sum(clean(r.get("free_agent_category")) == VFA_CATEGORY for r in output_rows) == 78
        and sum(clean(r.get("free_agent_category")) in NON_VFA_CATEGORIES for r in output_rows) == 54,
        "Corrected market partition must equal 78 Veteran FAs + 54 waiver/10-Day non-VFAs.",
    )
    check(
        "exact_corrected_rfa_partition",
        len(eligible) == 28
        and len(manual) == 18
        and len(not_eligible) == 32
        and len(not_applicable) == 54,
        (
            f"eligible={len(eligible)}; manual={len(manual)}; "
            f"not_eligible={len(not_eligible)}; not_applicable={len(not_applicable)}"
        ),
    )
    check(
        "eligible_formula_families_are_expected",
        Counter(
            clean(r.get("corrected_rfa_qo_path"))
            for r in eligible
        ) == Counter({
            "rookie_scale_second_option_year_complete": 4,
            "veteran_free_agent_three_or_fewer_yos": 4,
            "completing_two_way_contract_15_day_gp_proven": 14,
            "completing_two_way_contract_15_day_official_rfa_proven": 6,
        }),
        "The 28 proven rows must come only from the four supported structural pathways.",
    )
    check(
        "two_rookie_option_declines_force_ufa",
        sum(
            clean(r.get("corrected_rfa_qo_path"))
            == "rookie_scale_option_decline_forces_ufa"
            for r in not_eligible
        ) == 2,
        "Jett Howard and Kobe Brown must stay outside ordinary RFA/QO logic.",
    )
    check(
        "seventeen_two_way_rows_remain_manual",
        sum(
            clean(r.get("corrected_rfa_qo_path"))
            == "two_way_15_day_evidence_required"
            for r in manual
        ) == 17,
        "Unproven Two-Way 15-day cases stay manual.",
    )
    check(
        "one_rights_unresolved_market_row_remains_manual",
        sum(
            clean(r.get("corrected_rfa_qo_path"))
            == "rights_unresolved"
            for r in manual
        ) == 1,
        "Alex Antetokounmpo remains manual rather than guessed.",
    )
    check(
        "pending_and_under_contract_rows_are_absent_from_market",
        not {
            pid(r.get("player_id"))
            for r in pending_or_under_contract
        }.intersection({
            pid(r.get("player_id"))
            for r in output_rows
        }),
        "No pending-option or under-contract player may enter this corrected market preview.",
    )
    check(
        "old_qo_amount_v1_is_never_live_usable",
        all(
            not r["prior_qo_amount_v1_live_usable"]
            for r in output_rows
        ),
        "Old 55-player QO amount audit is superseded by lifecycle correction.",
    )
    check(
        "no_qo_or_rfa_state_is_applied",
        all(
            not r["qualifying_offer_issued"]
            and not r["rfa_status_applied"]
            and not r["offer_sheet_created"]
            and not r["right_of_first_refusal_created"]
            for r in output_rows
        ),
        "Preview only.",
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
        r["check_id"]
        for r in checks
        if r["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Corrected RFA/QO Universe V2 Preview failed: "
            + ", ".join(failed)
        )

    path_counts = Counter(
        clean(r.get("corrected_rfa_qo_path"))
        for r in output_rows
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_corrected_rfa_qo_universe_v2_preview_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="farfaqov2_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "corrected_rfa_qo_universe_all.csv",
            output_rows,
        )
        write_csv(
            export / "corrected_rfa_qo_proven_eligible.csv",
            eligible,
        )
        write_csv(
            export / "corrected_rfa_qo_manual_review.csv",
            manual,
        )
        write_csv(
            export / "corrected_rfa_qo_not_eligible.csv",
            not_eligible,
        )
        write_csv(
            export / "corrected_rfa_qo_not_applicable.csv",
            not_applicable,
        )
        write_csv(
            export / "corrected_rfa_qo_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "lifecycle_input_zip": str(lifecycle_zip),
            "lifecycle_input_sha256": sha256_file(lifecycle_zip),
            "corrected_market_candidate_count": len(output_rows),
            "veteran_free_agent_count": 78,
            "non_veteran_free_agent_count": 54,
            "eligible_if_qo_issued_count": len(eligible),
            "manual_review_count": len(manual),
            "not_eligible_count": len(not_eligible),
            "not_applicable_count": len(not_applicable),
            "path_counts": dict(sorted(path_counts.items())),
            "prior_qo_amount_v1_superseded": True,
            "qualifying_offer_issued_count": 0,
            "rfa_status_applied_count": 0,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "state_mutation_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Build simulator-side 2026-27 contract option / non-guarantee "
                "decision preview for the 48 pending players. After those "
                "counterfactual decisions are resolved, merge newly-created "
                "free agents into this RFA/QO universe and rebuild QO amounts "
                "from the final corrected eligible set."
            ),
        }

        (export / "corrected_rfa_qo_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """CORRECTED 2026 RFA + QO UNIVERSE V2 PREVIEW
=============================================

Input:
the passed Contract Option Lifecycle Readiness V1.0.1 audit.

The provisional 187-player "free-agent" set was a research universe, not a
final market universe. Contract-option reconciliation reduced the actual
April-12 branch-state market to 132 players:

- 78 Veteran Free Agents
- 34 waiver-terminated free agents
- 20 10-Day free agents

The 48 pending 2026-27 option/non-guarantee decisions and 3 players already
under contract are excluded until the simulator resolves those contract states.

Corrected RFA/QO partition:
- 28 proven eligible if a QO is issued
- 18 manual review
- 32 Veteran FAs not RFA eligible
- 54 non-VFAs / not applicable

The 28 proven set is:
- 4 completed 2022 first-round rookie-scale contracts
- 4 ordinary <=3-YOS Veteran FAs
- 14 Two-Way finishers with >=15-game affirmative proof
- 6 Two-Way finishers with independent official affirmative 15-day proof

Two first-round option-decline cases are forced UFA and cannot use the ordinary
<=3-YOS route.

The prior 55-player QO Amount Readiness V1 is explicitly superseded and must
not be used for live decisions.

READ ONLY:
- no QO
- no RFA status
- no option decision
- no cap hold
- no rights overlay
- no checkpoint write
"""

        (export / "README.txt").write_text(
            readme,
            encoding="utf-8",
        )

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
        raise RuntimeError(
            "Checkpoint changed after corrected RFA/QO preview."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed after corrected RFA/QO preview."
        )

    print("", flush=True)
    print("=" * 122, flush=True)
    print("CORRECTED 2026 RFA + QO UNIVERSE V2 PREVIEW PASSED", flush=True)
    print("=" * 122, flush=True)
    print(f"Corrected market:          {len(output_rows)}", flush=True)
    print(f"Eligible if QO issued:     {len(eligible)}", flush=True)
    print(f"Manual review:             {len(manual)}", flush=True)
    print(f"Not RFA eligible:          {len(not_eligible)}", flush=True)
    print(f"Non-VFA / not applicable:  {len(not_applicable)}", flush=True)
    print("Old QO Amount V1 live usable: NO", flush=True)
    print("QOs issued: 0", flush=True)
    print("RFA statuses applied: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
