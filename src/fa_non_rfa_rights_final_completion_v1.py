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


VERSION = "fa-non-rfa-rights-final-completion-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_FINAL_COUNTS = Counter(
    {
        "bird": 44,
        "early_bird": 14,
        "non_bird": 48,
        "not_applicable": 56,
    }
)
ALLOWED_CLASSIFICATIONS = set(EXPECTED_FINAL_COUNTS)
TARGET_EVIDENCE_MODE = "targeted_final15_pre_split_resolution_frozen_v1"


def clean(value: Any) -> str:
    return str(value or "").strip()


def player_id(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def latest(root: Path, pattern: str) -> Path:
    paths = [path for path in root.rglob(pattern) if path.is_file()]
    if not paths:
        raise RuntimeError(f"Missing required audit: {pattern}")
    return max(paths, key=lambda path: path.stat().st_mtime)


def read_csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    if not text.strip():
        return []
    return list(csv.DictReader(io.StringIO(text)))


def read_json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next(
        (name for name in archive.namelist() if name.endswith(suffix)),
        "",
    )
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields: list[str] = []
    seen: set[str] = set()
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

    completion_zip = latest(
        root,
        "fa_non_rfa_rights_evidence_completion_v1_2026-27_*.zip",
    )
    preview_zip = latest(
        root,
        "fa_non_rfa_rights_final15_targeted_resolution_preview_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(completion_zip) as archive:
        completion_summary = read_json_suffix(
            archive,
            "non_rfa_rights_completion_summary.json",
        )
        upstream_162 = read_csv_suffix(
            archive,
            "non_rfa_rights_completed_162.csv",
        )
        upstream_unresolved_15 = read_csv_suffix(
            archive,
            "non_rfa_rights_unresolved_15.csv",
        )

    with zipfile.ZipFile(preview_zip) as archive:
        preview_summary = read_json_suffix(
            archive,
            "final15_targeted_resolution_summary.json",
        )
        target_proposals = read_csv_suffix(
            archive,
            "final15_targeted_rights_proposals.csv",
        )
        preview_162 = read_csv_suffix(
            archive,
            "non_rfa_rights_preview_complete_162.csv",
        )
        preview_missing_events = read_csv_suffix(
            archive,
            "final15_missing_required_events.csv",
        )
        preview_conflicts = read_csv_suffix(
            archive,
            "final15_overwrite_conflicts.csv",
        )
        preview_checks = read_csv_suffix(
            archive,
            "final15_targeted_resolution_checks.csv",
        )

    if not completion_summary.get("passed"):
        raise RuntimeError("Upstream 147-of-162 evidence completion did not pass.")
    if not preview_summary.get("passed"):
        raise RuntimeError("Upstream final-15 targeted preview did not pass.")

    upstream_by_id = {player_id(row.get("player_id")): row for row in upstream_162}
    preview_by_id = {player_id(row.get("player_id")): row for row in preview_162}
    target_by_id = {
        player_id(row.get("player_id")): row for row in target_proposals
    }
    unresolved_ids = {
        player_id(row.get("player_id")) for row in upstream_unresolved_15
    }

    duplicate_upstream_ids = len(upstream_by_id) != len(upstream_162)
    duplicate_preview_ids = len(preview_by_id) != len(preview_162)
    duplicate_target_ids = len(target_by_id) != len(target_proposals)

    strict_preview_failures = [
        clean(row.get("check_id"))
        for row in preview_checks
        if clean(row.get("severity")).lower() == "strict"
        and clean(row.get("status")).upper() != "PASS"
    ]

    merge_conflicts: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []
    frozen_target_rows: list[dict[str, Any]] = []

    for pid in sorted(upstream_by_id, key=lambda value: int(value)):
        upstream = upstream_by_id[pid]
        preview = preview_by_id.get(pid, {})
        proposal = target_by_id.get(pid, {})

        upstream_name = clean(upstream.get("player_name"))
        upstream_team = clean(upstream.get("prior_team"))
        preview_name = clean(preview.get("player_name"))
        preview_team = clean(preview.get("prior_team"))

        if preview_name != upstream_name or preview_team != upstream_team:
            merge_conflicts.append(
                {
                    "player_id": pid,
                    "player_name": upstream_name,
                    "conflict_type": "preview_player_identity_mismatch",
                    "upstream": f"{upstream_name}|{upstream_team}",
                    "preview": f"{preview_name}|{preview_team}",
                }
            )

        if proposal:
            proposal_name = clean(proposal.get("player_name"))
            proposal_team = clean(proposal.get("prior_team"))
            if proposal_name != upstream_name or proposal_team != upstream_team:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": upstream_name,
                        "conflict_type": "target_player_identity_mismatch",
                        "upstream": f"{upstream_name}|{upstream_team}",
                        "preview": f"{proposal_name}|{proposal_team}",
                    }
                )

        upstream_classification = clean(
            upstream.get("final_rights_classification")
        )
        preview_classification = clean(
            preview.get("final_rights_classification")
        )
        proposed_classification = clean(
            proposal.get("proposed_rights_classification")
        )

        if upstream_classification:
            if preview_classification != upstream_classification:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": clean(upstream.get("player_name")),
                        "conflict_type": "existing_147_classification_changed",
                        "upstream": upstream_classification,
                        "preview": preview_classification,
                    }
                )
            if proposed_classification:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": clean(upstream.get("player_name")),
                        "conflict_type": "target_attempted_existing_overwrite",
                        "upstream": upstream_classification,
                        "preview": proposed_classification,
                    }
                )
            final_classification = upstream_classification
            evidence_mode = clean(upstream.get("evidence_mode"))
        else:
            if pid not in unresolved_ids:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": clean(upstream.get("player_name")),
                        "conflict_type": "blank_classification_not_in_unresolved_set",
                        "upstream": "",
                        "preview": preview_classification,
                    }
                )
            if not proposed_classification:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": clean(upstream.get("player_name")),
                        "conflict_type": "unresolved_player_missing_target_proposal",
                        "upstream": "",
                        "preview": preview_classification,
                    }
                )
            if preview_classification != proposed_classification:
                merge_conflicts.append(
                    {
                        "player_id": pid,
                        "player_name": clean(upstream.get("player_name")),
                        "conflict_type": "proposal_preview_mismatch",
                        "upstream": proposed_classification,
                        "preview": preview_classification,
                    }
                )
            final_classification = proposed_classification
            evidence_mode = TARGET_EVIDENCE_MODE

        final_row = {
            "player_id": pid,
            "player_name": upstream_name,
            "prior_team": upstream_team,
            "final_rights_classification": final_classification,
            "evidence_mode": evidence_mode,
            "continuity_reason": clean(upstream.get("continuity_reason")),
            "continuity_start": clean(upstream.get("continuity_start")),
            "targeted_resolution_reason": clean(proposal.get("resolution_reason")),
            "targeted_latest_evidence_date": clean(
                proposal.get("latest_evidence_date")
            ),
            "targeted_all_evidence_pre_split": (
                as_bool(proposal.get("all_evidence_pre_split"))
                if proposal
                else ""
            ),
            "targeted_required_event_count": clean(
                proposal.get("canonical_required_event_count")
            ),
            "targeted_required_events_verified": (
                as_bool(proposal.get("canonical_required_events_verified"))
                if proposal
                else ""
            ),
            "targeted_supplemental_event": clean(
                proposal.get("supplemental_event")
            ),
            "targeted_supplemental_source": clean(
                proposal.get("supplemental_source")
            ),
            "cba_source": clean(proposal.get("cba_source")),
            "movement_source": clean(proposal.get("movement_source")),
            "rights_resolved": bool(final_classification),
            "rights_frozen_into_evidence_table": bool(final_classification),
            "classification_applied_to_simulation": False,
        }
        final_rows.append(final_row)

        if proposal:
            frozen_target_rows.append(
                {
                    **proposal,
                    "final_rights_classification": final_classification,
                    "final_evidence_mode": TARGET_EVIDENCE_MODE,
                    "rights_frozen_into_evidence_table": True,
                    "classification_applied_to_simulation": False,
                }
            )

    final_counts = Counter(
        row["final_rights_classification"] for row in final_rows
    )
    unknown_classifications = sorted(
        set(final_counts) - ALLOWED_CLASSIFICATIONS
    )
    unresolved_final = [
        row for row in final_rows if not row["rights_resolved"]
    ]
    target_provenance_complete = all(
        clean(row.get("resolution_reason"))
        and clean(row.get("latest_evidence_date"))
        and as_bool(row.get("all_evidence_pre_split"))
        and as_bool(row.get("canonical_required_events_verified"))
        and clean(row.get("cba_source"))
        and clean(row.get("movement_source"))
        for row in target_proposals
    )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before final rights evidence completion."
        )

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 NON-RFA RIGHTS FINAL COMPLETION V1")
    print("=" * 132)
    print("Freezing the final 15 classifications into the evidence table...")

    add(
        "upstream_147_of_162_completion_passed",
        bool(completion_summary.get("passed"))
        and int(completion_summary.get("resolved_count", -1)) == 147
        and int(completion_summary.get("unresolved_count", -1)) == 15,
        "147 resolved and 15 unresolved upstream.",
    )
    add(
        "upstream_final15_targeted_preview_passed",
        bool(preview_summary.get("passed"))
        and int(preview_summary.get("preview_resolved_count", -1)) == 162
        and int(preview_summary.get("preview_unresolved_count", -1)) == 0,
        "Final-15 preview resolved 162/162.",
    )
    add(
        "all_upstream_preview_strict_checks_passed",
        not strict_preview_failures,
        f"strict_failures={len(strict_preview_failures)}",
    )
    add(
        "upstream_tables_have_exact_unique_cardinality",
        len(upstream_162) == 162
        and len(preview_162) == 162
        and len(target_proposals) == 15
        and len(upstream_unresolved_15) == 15
        and not duplicate_upstream_ids
        and not duplicate_preview_ids
        and not duplicate_target_ids,
        (
            f"completion={len(upstream_162)}, preview={len(preview_162)}, "
            f"targets={len(target_proposals)}, unresolved={len(upstream_unresolved_15)}"
        ),
    )
    add(
        "exact_15_target_ids_match_unresolved_set",
        set(target_by_id) == unresolved_ids,
        f"matched={len(set(target_by_id) & unresolved_ids)}/15",
    )
    add(
        "all_162_player_ids_match_across_upstreams",
        set(upstream_by_id) == set(preview_by_id),
        f"completion_ids={len(upstream_by_id)}, preview_ids={len(preview_by_id)}",
    )
    add(
        "all_target_evidence_is_pre_split_and_verified",
        target_provenance_complete,
        "All 15 targets retain verified pre-split evidence and source provenance.",
    )
    add(
        "upstream_missing_events_and_conflicts_are_zero",
        not preview_missing_events and not preview_conflicts,
        (
            f"missing_events={len(preview_missing_events)}, "
            f"preview_conflicts={len(preview_conflicts)}"
        ),
    )
    add(
        "no_existing_147_classifications_overwritten",
        not merge_conflicts,
        f"merge_conflicts={len(merge_conflicts)}",
    )
    add(
        "exact_15_targeted_classifications_frozen",
        len(frozen_target_rows) == 15
        and all(
            row["final_evidence_mode"] == TARGET_EVIDENCE_MODE
            for row in frozen_target_rows
        ),
        f"frozen_targets={len(frozen_target_rows)}",
    )
    add(
        "exact_162_of_162_non_rfa_rights_evidence_complete",
        len(final_rows) == 162 and not unresolved_final,
        f"resolved={len(final_rows) - len(unresolved_final)}/162",
    )
    add(
        "final_classification_distribution_expected",
        final_counts == EXPECTED_FINAL_COUNTS
        and not unknown_classifications,
        repr(dict(final_counts)),
    )
    add(
        "all_162_rows_retain_evidence_provenance",
        all(clean(row.get("evidence_mode")) for row in final_rows),
        "Every final classification has an evidence mode.",
    )
    add(
        "classifications_not_applied_to_simulation",
        all(
            not row["classification_applied_to_simulation"]
            for row in final_rows
        ),
        "Evidence freeze only.",
    )

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)

    add(
        "loaded_simulation_state_unchanged",
        simulation_digest_after == simulation_digest_before,
        simulation_digest_after,
    )
    add(
        "checkpoint_file_unchanged",
        checkpoint_hash_after
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [
        row["check_id"] for row in checks if row["status"] == "FAIL"
    ]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_non_rfa_rights_final_completion_v1_{SEASON_LABEL}_{timestamp}"
    )
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "upstream_resolved_count": 147,
        "newly_frozen_targeted_count": len(frozen_target_rows),
        "final_resolved_count": len(final_rows) - len(unresolved_final),
        "final_unresolved_count": len(unresolved_final),
        "final_classification_counts": dict(sorted(final_counts.items())),
        "merge_conflict_count": len(merge_conflicts),
        "target_provenance_complete": target_provenance_complete,
        "classifications_applied": 0,
        "cap_holds_computed": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_completion_audit": completion_zip.name,
        "source_final15_preview_audit": preview_zip.name,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Non-RFA rights evidence is complete at 162/162. Resume the "
            "separate 40-player prior-salary completion workstream before "
            "computing full-market Free Agent Amounts or applying cap holds."
        ),
    }

    with tempfile.TemporaryDirectory(
        prefix="fa_non_rfa_rights_final_completion_"
    ) as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "non_rfa_rights_evidence_complete_162.csv",
            final_rows,
        )
        write_csv(
            export / "non_rfa_rights_final15_frozen_15.csv",
            frozen_target_rows,
        )
        write_csv(
            export / "non_rfa_rights_final_completion_conflicts.csv",
            merge_conflicts,
        )
        write_csv(
            export / "non_rfa_rights_final_completion_checks.csv",
            checks,
        )
        (
            export / "non_rfa_rights_final_completion_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 NON-RFA RIGHTS FINAL COMPLETION V1
================================================

Purpose
-------
Freeze the 15 validated targeted resolutions on top of the previously frozen
147 classifications, yielding one provenance-complete 162-player non-RFA
rights evidence table.

Expected final distribution
---------------------------
- Bird: 44
- Early Bird: 14
- Non-Bird: 48
- Not applicable: 56

This is an EVIDENCE-ONLY completion layer.
No classification is applied to simulation state.
No cap hold or Free Agent Amount is computed.
No roster, contract, QO, renouncement, Team Salary, or checkpoint write occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            audit_zip,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Non-RFA Rights Final Completion V1 failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 132)
    print("2026 NON-RFA RIGHTS FINAL COMPLETION V1 PASSED")
    print("=" * 132)
    print("Previously frozen:       147/162")
    print("New targeted freeze:      15/15")
    print("Final rights completion: 162/162")
    print("Rights applied:            0")
    print("Cap holds computed:         0")
    print("Checkpoint write:          NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
