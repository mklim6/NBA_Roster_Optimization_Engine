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

VERSION = "fa-additional-lifecycle-targeted-resolution-and-final84-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

TARGETED_EVIDENCE = {
    "1628963": {
        "player_name": "Marvin Bagley III",
        "classification": "expiring_2025_26_free_agent_candidate",
        "signing_date": "2025-07-09",
        "prior_base_salary": "$3,080,921",
        "target_option": "",
        "evidence_fact": (
            "One-year 2025-26 veteran contract. No 2026-27 contract year. "
            "Expiry status UFA."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/marvin-bagleyiii",
        "secondary_source_url": "https://www.nba.com/players/free-agent-tracker/2026",
        "source_tier": "contract_ledger_plus_official_free_agent_tracker",
    },
    "1626162": {
        "player_name": "Kelly Oubre Jr.",
        "classification": "expiring_2025_26_free_agent_candidate",
        "signing_date": "2024-07-07",
        "prior_base_salary": "$8,382,150",
        "target_option": "",
        "evidence_fact": (
            "The 2024 PHI contract ended with the 2025-26 player-option season. "
            "There is no 2026-27 year on that pre-split contract."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/kelly-oubrejr",
        "secondary_source_url": "https://www.nba.com/news/kelly-oubre-jr-pacers-free-agency-2026",
        "source_tier": "contract_ledger_plus_official_free_agency_release",
    },
    "1626204": {
        "player_name": "Larry Nance Jr.",
        "classification": "expiring_2025_26_free_agent_candidate",
        "signing_date": "2025-07-06",
        "prior_base_salary": "$3,634,153",
        "target_option": "",
        "evidence_fact": (
            "One-year 2025-26 veteran contract with Cleveland. "
            "No 2026-27 contract year."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/larry-nancejr",
        "secondary_source_url": "https://gleague.nba.com/news/the-indiana-pacers-have-signed-larry-nance-jr",
        "source_tier": "contract_ledger_plus_official_team_release",
    },
    "203484": {
        "player_name": "Kentavious Caldwell-Pope",
        "classification": "player_option_2026_27_decision",
        "signing_date": "2024-07-06",
        "prior_base_salary": "$21,621,500",
        "target_base_salary": "$21,621,500",
        "target_option": "Player",
        "evidence_fact": (
            "Pre-split Orlando contract contains a 2026-27 Player Option "
            "for $21,621,500. The later exercise/buyout is audit-only."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/kentavious-caldwellpope",
        "secondary_source_url": "https://www.nba.com/grizzlies/player/203484/kentavious-caldwell-pope",
        "source_tier": "contract_ledger_plus_official_nba_player_update",
    },
    "203501": {
        "player_name": "Tim Hardaway Jr.",
        "classification": "expiring_2025_26_free_agent_candidate",
        "signing_date": "2025-07-10",
        "prior_base_salary": "$3,634,153",
        "target_option": "",
        "evidence_fact": (
            "One-year 2025-26 veteran contract with Denver. "
            "No 2026-27 contract year."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/tim-hardawayjr",
        "secondary_source_url": (
            "https://www.reuters.com/sports/reports-tim-hardaway-jr-reaches-deal-with-nuggets-2025-07-01/"
        ),
        "source_tier": "contract_ledger_plus_contemporaneous_report",
    },
    "1629018": {
        "player_name": "Gary Trent Jr.",
        "classification": "player_option_2026_27_decision",
        "signing_date": "2025-07-06",
        "prior_base_salary": "$3,697,106",
        "target_base_salary": "$3,881,962",
        "target_option": "Player",
        "evidence_fact": (
            "Pre-split Milwaukee contract contains a 2026-27 Player Option "
            "for $3,881,962. The later decline/re-signing is audit-only."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/gary-trentjr",
        "secondary_source_url": "https://www.nba.com/news/gary-trent-jr-free-agency-2026",
        "source_tier": "contract_ledger_plus_official_free_agency_release",
    },
    "1630538": {
        "player_name": "Bones Hyland",
        "classification": "expiring_2025_26_free_agent_candidate",
        "signing_date": "2025-09-15",
        "prior_base_salary": "$2,461,463",
        "target_option": "",
        "evidence_fact": (
            "One-year 2025-26 veteran contract with Minnesota. "
            "No 2026-27 contract year."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/nahshon-bones-hyland",
        "secondary_source_url": "https://www.nba.com/player/1630538/bones-hyland",
        "source_tier": "contract_ledger_plus_official_nba_player_page",
    },
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
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


def main() -> int:
    root = Path.cwd().resolve()

    harvest_zip = find_latest(
        root,
        "fa_additional_lifecycle_contract_evidence_harvest_v1_0_1_2026-27_*.zip",
    )
    manual_zip = find_latest(
        root,
        "fa_additional_lifecycle_manual_resolution_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(harvest_zip) as archive:
        harvest_summary = read_json_member(
            archive,
            "additional_lifecycle_contract_summary.json",
        )
        harvest_rows = read_csv_member(
            archive,
            "additional_lifecycle_contract_classification.csv",
        )

    with zipfile.ZipFile(manual_zip) as archive:
        manual_summary = read_json_member(
            archive,
            "manual_resolution_summary.json",
        )
        manual_resolved = read_csv_member(
            archive,
            "manual_resolution_resolved.csv",
        )
        manual_remaining = read_csv_member(
            archive,
            "manual_resolution_remaining.csv",
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash = sha256_file(checkpoint_path)

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before targeted evidence merge.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    if len(harvest_rows) != 84:
        raise RuntimeError(f"Expected 84 harvested rows, got {len(harvest_rows)}.")
    if len(manual_remaining) != 7:
        raise RuntimeError(
            f"Expected 7 targeted holdouts, got {len(manual_remaining)}."
        )

    remaining_ids = {pid(row.get("player_id")) for row in manual_remaining}
    evidence_ids = set(TARGETED_EVIDENCE)

    if remaining_ids != evidence_ids:
        raise RuntimeError(
            "Targeted evidence IDs do not match the seven upstream manual rows.\n"
            f"Upstream: {sorted(remaining_ids)}\n"
            f"Evidence: {sorted(evidence_ids)}"
        )

    manual_resolved_by_id = {
        pid(row.get("player_id")): row
        for row in manual_resolved
    }

    final_rows: list[dict[str, Any]] = []
    targeted_rows: list[dict[str, Any]] = []

    for original in harvest_rows:
        player_id = pid(original.get("player_id"))
        final = dict(original)

        if player_id in manual_resolved_by_id:
            resolved = manual_resolved_by_id[player_id]
            final["lifecycle_contract_classification"] = clean(
                resolved.get("resolved_classification")
            )
            final["classification_reason"] = clean(
                resolved.get("resolution_reason")
            )
            final["final_resolution_method"] = "manual_resolution_v1_pre_split_consensus"
            final["final_source_tier"] = "harvested_pre_split_contract_evidence"
            final["final_manual_review_required"] = False

        elif player_id in TARGETED_EVIDENCE:
            evidence = TARGETED_EVIDENCE[player_id]
            final["lifecycle_contract_classification"] = evidence["classification"]
            final["classification_reason"] = evidence["evidence_fact"]
            final["chosen_contract_signing_date"] = evidence["signing_date"]
            final["chosen_prior_base_salary"] = evidence.get("prior_base_salary", "")
            final["chosen_target_base_salary"] = evidence.get(
                "target_base_salary", ""
            )
            final["chosen_target_option"] = evidence.get("target_option", "")
            final["chosen_target_option_used_text_audit_only"] = ""
            final["final_resolution_method"] = "targeted_source_backed_evidence_v1"
            final["final_source_tier"] = evidence["source_tier"]
            final["final_manual_review_required"] = False
            final["future_outcome_used_for_classification"] = False

            targeted_rows.append({
                "player_id": player_id,
                "player_name": evidence["player_name"],
                "classification": evidence["classification"],
                "contract_signing_date": evidence["signing_date"],
                "prior_base_salary": evidence.get("prior_base_salary", ""),
                "target_base_salary": evidence.get("target_base_salary", ""),
                "target_option": evidence.get("target_option", ""),
                "evidence_fact": evidence["evidence_fact"],
                "primary_source_url": evidence["primary_source_url"],
                "secondary_source_url": evidence["secondary_source_url"],
                "source_tier": evidence["source_tier"],
                "future_real_world_outcome_used": False,
                "checkpoint_mutation_applied": False,
            })
        else:
            final.setdefault(
                "final_resolution_method",
                "contract_harvest_v1_0_1",
            )
            final.setdefault(
                "final_source_tier",
                "harvested_pre_split_contract_evidence",
            )
            final["final_manual_review_required"] = clean(
                final.get("lifecycle_contract_classification")
            ).startswith("manual_")

        final_rows.append(final)

    final_manual = [
        row
        for row in final_rows
        if clean(row.get("lifecycle_contract_classification")).startswith("manual_")
    ]
    counts = Counter(
        clean(row.get("lifecycle_contract_classification"))
        for row in final_rows
    )

    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 ADDITIONAL LIFECYCLE TARGETED RESOLUTION + FINAL 84 V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Harvested universe:       {len(harvest_rows)}", flush=True)
    print(f"Previously auto-resolved: {len(manual_resolved)}", flush=True)
    print(f"Targeted holdouts:        {len(manual_remaining)}", flush=True)
    print("READ-ONLY. No checkpoint mutation.", flush=True)
    print("", flush=True)

    print("Running strict final-84 checks...", flush=True)

    check(
        "upstream_harvest_passed",
        bool(harvest_summary.get("passed")),
        "84-player contract harvest V1.0.1 passed.",
    )
    check(
        "upstream_manual_resolution_passed",
        bool(manual_summary.get("passed")),
        "16-row manual resolver V1 passed.",
    )
    check(
        "exact_84_final_rows",
        len(final_rows) == 84
        and len({pid(row.get("player_id")) for row in final_rows}) == 84,
        f"rows={len(final_rows)}",
    )
    check(
        "exact_seven_targeted_evidence_rows",
        len(targeted_rows) == 7,
        f"targeted={len(targeted_rows)}",
    )
    check(
        "zero_final_manual_rows",
        not final_manual,
        f"manual={len(final_manual)}",
    )
    check(
        "final_classification_counts_are_61_11_10_2",
        counts
        == Counter({
            "expiring_2025_26_free_agent_candidate": 61,
            "team_option_2026_27_decision": 11,
            "player_option_2026_27_decision": 10,
            "partial_or_non_guaranteed_2026_27_decision": 2,
        }),
        json.dumps(dict(sorted(counts.items())), sort_keys=True),
    )
    check(
        "targeted_player_options_only_kcp_and_gary_trent",
        {
            row["player_name"]
            for row in targeted_rows
            if row["classification"] == "player_option_2026_27_decision"
        } == {"Kentavious Caldwell-Pope", "Gary Trent Jr."},
        "Expected KCP and Gary Trent Jr.",
    )
    check(
        "targeted_expiring_five",
        {
            row["player_name"]
            for row in targeted_rows
            if row["classification"] == "expiring_2025_26_free_agent_candidate"
        }
        == {
            "Marvin Bagley III",
            "Kelly Oubre Jr.",
            "Larry Nance Jr.",
            "Tim Hardaway Jr.",
            "Bones Hyland",
        },
        "Five targeted expiring-contract players.",
    )
    check(
        "no_targeted_future_outcome_used",
        all(not row["future_real_world_outcome_used"] for row in targeted_rows),
        "Later option exercise/decline, waiver, or re-signing is audit-only.",
    )
    check(
        "checkpoint_file_unchanged",
        sha256_file(checkpoint_path)
        == checkpoint_hash
        == EXPECTED_CHECKPOINT_SHA256,
        sha256_file(checkpoint_path),
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Targeted Resolution + Final84 V1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_additional_lifecycle_targeted_resolution_and_final84_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_final84_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "targeted_seven_evidence_registry.csv",
            targeted_rows,
        )
        write_csv(
            export / "additional_lifecycle_final_84.csv",
            final_rows,
        )
        write_csv(
            export / "additional_lifecycle_final_manual_rows.csv",
            final_manual,
        )
        write_csv(
            export / "final84_checks.csv",
            checks,
        )

        out_summary = {
            "version": VERSION,
            "final_additional_lifecycle_count": len(final_rows),
            "final_manual_count": len(final_manual),
            "classification_counts": dict(sorted(counts.items())),
            "targeted_resolution_count": len(targeted_rows),
            "future_real_world_outcomes_used": False,
            "checkpoint_write_performed": False,
            "state_mutation_performed": False,
            "passed": True,
            "next_slice": (
                "Merge this zero-manual 84-player additional lifecycle universe "
                "with the original 187 lifecycle rows. Rebuild the complete 2026 "
                "offseason market, option/guarantee decision queues, RFA/QO universe, "
                "and roster-capacity preview before any checkpoint hydration."
            ),
        }

        (export / "final84_summary.json").write_text(
            json.dumps(out_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 ADDITIONAL LIFECYCLE TARGETED RESOLUTION + FINAL 84 V1
================================================================

This package closes the seven remaining manual contract-history rows with
targeted source-backed evidence.

Final additional 84-player lifecycle:
- 61 expiring 2025-26 free-agent candidates
- 11 2026-27 Team Option decisions
- 10 2026-27 Player Option decisions
- 2 partial/non-guaranteed 2026-27 decisions
- 0 manual rows

The two targeted Player Option cases are:
- Kentavious Caldwell-Pope
- Gary Trent Jr.

The five targeted expiring contracts are:
- Marvin Bagley III
- Kelly Oubre Jr.
- Larry Nance Jr.
- Tim Hardaway Jr.
- Bones Hyland

IMPORTANT
---------
Current public sources may display what these players ultimately did after
April 12. Those later choices are never used as branch-state decisions.

Only pre-existing contract structure is imported into the evidence registry.

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 ADDITIONAL LIFECYCLE TARGETED RESOLUTION + FINAL 84 V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Final additional lifecycle rows: 84", flush=True)
    print("Final manual rows:                0", flush=True)
    print("Classification counts:", flush=True)
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("Future outcomes used:             NO", flush=True)
    print("Checkpoint write:                 NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
