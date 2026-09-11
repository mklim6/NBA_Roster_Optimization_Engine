from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-offseason-decision-universe-completeness-audit-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

CANDIDATE_BUCKETS = {
    "resigning_contract_fa_signal",
    "new_team_or_generic_signing_fa_signal",
    "waive_decision_signal",
    "two_way_signing_signal",
}

NO_FA_BUCKETS = {
    "trade_no_fa",
    "extension_no_fa",
    "contract_conversion_no_fa",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
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
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    if not text.strip():
        return []
    return list(csv.DictReader(io.StringIO(text)))


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def player_name(player: Any, fallback: str) -> str:
    for attr in ("player_name", "display_name", "name", "full_name"):
        value = clean(getattr(player, attr, ""))
        if value:
            return value
    return fallback


def classify_event(row: dict[str, str]) -> tuple[str, str]:
    tx_type = clean(row.get("transaction_type")).lower()
    desc = clean(row.get("description"))
    low = desc.lower()

    if tx_type == "signing":
        if "extension" in low:
            return (
                "extension_no_fa",
                "Post-split extension does not itself create a free-agent market entry.",
            )
        if "re-signed" in low or "re signed" in low:
            return (
                "resigning_contract_fa_signal",
                "Same-team re-signing to a new Contract signals a potential expired/free-agent contract that is not represented by the old 187 universe.",
            )
        if "two-way" in low or "two way" in low:
            return (
                "two_way_signing_signal",
                "Post-split Two-Way signing requires contract/free-agent/new-entrant classification before branch materialization.",
            )
        if "rookie contract" in low:
            return (
                "rookie_contract_new_entrant_signal",
                "Rookie Contract signing is a new-entry/draft onboarding event rather than presumptive veteran free agency.",
            )
        return (
            "new_team_or_generic_signing_fa_signal",
            "Generic post-split Contract signing is a potential free-agent signing and requires pre-signing contract-expiry classification.",
        )

    if tx_type == "waive":
        return (
            "waive_decision_signal",
            "Post-split waiver is a simulator-owned roster/guarantee decision point and cannot be imported as branch state.",
        )

    if tx_type == "trade":
        return (
            "trade_no_fa",
            "Trade changes roster ownership but does not itself create a free-agent market entry.",
        )

    if tx_type == "awardonwaivers":
        return (
            "waiver_claim_signal",
            "Waiver claim is downstream of a waiver decision and requires lifecycle reconstruction.",
        )

    if tx_type == "contractconverted":
        return (
            "contract_conversion_no_fa",
            "Contract conversion preserves team membership and is not presumptive free agency.",
        )

    return (
        "other_or_no_post_split_event",
        "No qualifying completeness signal from the earliest post-split movement row.",
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


def main() -> int:
    root = Path.cwd().resolve()

    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    provenance_zip = find_latest(
        root,
        "fa_post_split_roster_provenance_audit_v1_0_2_2026-27_*.zip",
    )
    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(branch_zip) as archive:
        branch_summary = read_json_member(
            archive,
            "branch_reconstruction_summary.json",
        )
        branch_rows = read_csv_member(
            archive,
            "branch_reconstruction_all_players.csv",
        )

    with zipfile.ZipFile(provenance_zip) as archive:
        provenance_summary = read_json_member(
            archive,
            "roster_provenance_summary.json",
        )
        movement_post = read_csv_member(
            archive,
            "player_movement_post_split.csv",
        )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )
        lifecycle_rows = read_csv_member(
            archive,
            "contract_option_lifecycle_all.csv",
        )

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_hash = sha256_file(checkpoint_path)
        checkpoint = checkpoint_module.load_franchise_checkpoint()
    except Exception as exc:
        raise RuntimeError(
            "Could not load the canonical franchise checkpoint."
        ) from exc

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Checkpoint changed unexpectedly before decision-universe audit.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)
    players = getattr(state, "players", {}) or {}

    branch_by_id = {
        pid(row.get("player_id")): row
        for row in branch_rows
    }
    lifecycle_ids = {
        pid(row.get("player_id"))
        for row in lifecycle_rows
    }

    movement_by_player: dict[str, list[dict[str, str]]] = {}
    for row in movement_post:
        player_id = pid(row.get("player_id"))
        if not player_id or player_id not in players:
            continue
        movement_by_player.setdefault(player_id, []).append(row)

    for rows in movement_by_player.values():
        rows.sort(
            key=lambda row: (
                clean(row.get("transaction_date")),
                clean(row.get("transaction_type")),
            )
        )

    audit_rows: list[dict[str, Any]] = []

    for raw_id, player in players.items():
        player_id = pid(raw_id)
        name = player_name(player, player_id)
        branch = branch_by_id.get(player_id, {})
        earliest = (
            movement_by_player.get(player_id, [])[0]
            if movement_by_player.get(player_id)
            else {}
        )

        bucket, reason = classify_event(earliest)

        row = {
            "player_id": player_id,
            "player_name": name,
            "in_original_187_lifecycle_universe": player_id in lifecycle_ids,
            "current_checkpoint_owner": clean(
                branch.get("current_checkpoint_owner")
            ),
            "reconstructed_branch_owner": clean(
                branch.get("reconstructed_branch_owner")
            ),
            "previous_preview_offseason_opening_owner": clean(
                branch.get("offseason_opening_owner")
            ),
            "earliest_post_split_transaction_type": clean(
                earliest.get("transaction_type")
            ),
            "earliest_post_split_transaction_date": clean(
                earliest.get("transaction_date")
            ),
            "earliest_post_split_transaction_team": clean(
                earliest.get("team_abbreviation")
            ),
            "earliest_post_split_transaction_description": clean(
                earliest.get("description")
            ),
            "completeness_bucket": bucket,
            "completeness_reason": reason,
            "requires_additional_offseason_lifecycle_research": (
                player_id not in lifecycle_ids
                and bucket in CANDIDATE_BUCKETS
            ),
            "safe_to_preserve_old_187_classification": (
                player_id in lifecycle_ids
            ),
            "checkpoint_mutation_applied": False,
        }
        audit_rows.append(row)

    omitted_candidates = [
        row for row in audit_rows
        if row["requires_additional_offseason_lifecycle_research"]
    ]
    extension_rows = [
        row for row in audit_rows
        if (
            not row["in_original_187_lifecycle_universe"]
            and row["completeness_bucket"] == "extension_no_fa"
        )
    ]
    trade_rows = [
        row for row in audit_rows
        if (
            not row["in_original_187_lifecycle_universe"]
            and row["completeness_bucket"] == "trade_no_fa"
        )
    ]
    rookie_rows = [
        row for row in audit_rows
        if (
            not row["in_original_187_lifecycle_universe"]
            and row["completeness_bucket"] == "rookie_contract_new_entrant_signal"
        )
    ]

    candidate_counts = Counter(
        row["completeness_bucket"]
        for row in omitted_candidates
    )

    by_name = {
        normalize(row["player_name"]): row
        for row in audit_rows
    }

    print("=" * 128, flush=True)
    print("2026 OFFSEASON DECISION-UNIVERSE COMPLETENESS AUDIT V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Checkpoint players:                {len(players)}", flush=True)
    print(f"Original lifecycle universe:       {len(lifecycle_ids)}", flush=True)
    print(
        f"Players outside original universe: {len(players) - len(lifecycle_ids)}",
        flush=True,
    )
    print(
        "READ-ONLY. This audit does not declare every signal to be a free "
        "agent; it identifies players requiring lifecycle research.",
        flush=True,
    )
    print("", flush=True)

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
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("Running strict completeness checks...", flush=True)

    check(
        "branch_reconstruction_preview_passed",
        bool(branch_summary.get("passed_strict_checks")),
        "Branch reconstruction V1.0.1 passed strict checks.",
    )
    check(
        "branch_reconstruction_has_zero_unresolved",
        int(branch_summary.get("reconstruction_unresolved_player_count", -1)) == 0,
        f"unresolved={branch_summary.get('reconstruction_unresolved_player_count')}",
    )
    check(
        "branch_reconstruction_has_no_over_21_teams",
        not list(branch_summary.get("teams_over_cba_21_raw") or []),
        f"over_21={branch_summary.get('teams_over_cba_21_raw')}",
    )
    check(
        "provenance_audit_passed",
        bool(provenance_summary.get("passed")),
        "NBA Player Movement provenance V1.0.2 passed.",
    )
    check(
        "original_lifecycle_audit_passed",
        bool(lifecycle_summary.get("passed")),
        "Original 187-player contract lifecycle audit passed.",
    )
    check(
        "checkpoint_player_count_is_582",
        len(players) == 582,
        f"players={len(players)}",
    )
    check(
        "original_lifecycle_universe_is_187",
        len(lifecycle_ids) == 187,
        f"lifecycle={len(lifecycle_ids)}",
    )
    check(
        "additional_lifecycle_research_candidates_detected",
        bool(omitted_candidates),
        f"candidates={len(omitted_candidates)}",
    )

    # Stable known examples from the saved official movement feed.
    known_cases = {
        "Coby White": "resigning_contract_fa_signal",
        "Marcus Smart": "new_team_or_generic_signing_fa_signal",
        "Jonathan Isaac": "waive_decision_signal",
        "Victor Wembanyama": "extension_no_fa",
    }
    for name, expected in known_cases.items():
        actual = clean(
            by_name.get(normalize(name), {}).get("completeness_bucket")
        )
        slug = re.sub(r"[^a-z0-9]+", "_", normalize(name)).strip("_")
        check(
            f"known_completeness_case_{slug}",
            actual == expected,
            f"expected={expected}; actual={actual}",
        )

    check(
        "post_split_events_remain_audit_only",
        all(not row["checkpoint_mutation_applied"] for row in audit_rows),
        "No transaction event was imported into simulator state.",
    )

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

    check(
        "live_state_unchanged",
        state_digest_before == state_digest_after,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash == checkpoint_after,
        checkpoint_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Offseason Decision-Universe Completeness Audit V1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_offseason_decision_universe_completeness_audit_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_decision_universe_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "decision_universe_completeness_all_players.csv",
            audit_rows,
        )
        write_csv(
            export / "additional_lifecycle_research_candidates.csv",
            omitted_candidates,
        )
        write_csv(
            export / "post_split_extensions_no_fa_signal.csv",
            extension_rows,
        )
        write_csv(
            export / "post_split_trades_no_fa_signal.csv",
            trade_rows,
        )
        write_csv(
            export / "rookie_contract_new_entrant_signals.csv",
            rookie_rows,
        )
        write_csv(
            export / "decision_universe_completeness_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "checkpoint_sha256": checkpoint_hash,
            "checkpoint_player_count": len(players),
            "original_lifecycle_universe_count": len(lifecycle_ids),
            "players_outside_original_lifecycle_universe": (
                len(players) - len(lifecycle_ids)
            ),
            "additional_lifecycle_research_candidate_count": (
                len(omitted_candidates)
            ),
            "additional_candidate_counts_by_signal": dict(
                sorted(candidate_counts.items())
            ),
            "extension_no_fa_signal_count": len(extension_rows),
            "trade_no_fa_signal_count": len(trade_rows),
            "rookie_contract_new_entrant_signal_count": len(rookie_rows),
            "old_132_market_can_be_treated_as_complete": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "critical_finding": (
                "The original 187-player lifecycle universe was not sufficient "
                "to prove a complete 2026 offseason decision universe because "
                "the checkpoint already contained post-split signings, "
                "re-signings, waives, and other decisions for players outside "
                "those 187 rows."
            ),
            "next_slice": (
                "Research/classify the additional lifecycle candidates using "
                "pre-split contract evidence. Separate true 2026 free agents, "
                "team/player option or guarantee decisions, waiver decisions, "
                "Two-Way/new-entrant cases, and false-positive/no-op signals. "
                "Only then rebuild the complete free-agent and contract-attached "
                "universes before checkpoint hydration."
            ),
        }

        (
            export / "decision_universe_completeness_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 OFFSEASON DECISION-UNIVERSE COMPLETENESS AUDIT V1
=======================================================

Why this audit exists
---------------------
The original contract-lifecycle research started from 187 players identified
by the existing durable checkpoint. Later provenance work proved that checkpoint
already includes real-world roster transactions after the April 12 simulation
split.

Therefore a player who was a real 2026 free agent but signed/re-signed before
the checkpoint snapshot may be on a roster and absent from the original 187.

This audit does NOT automatically add every post-split transaction to free
agency.

It flags additional players outside the original 187 when their earliest
post-split movement is a decision signal such as:
- same-team re-signing to a new Contract
- new-team/generic Contract signing
- waiver
- Two-Way signing

It separately preserves no-FA signals such as:
- trades
- Veteran/Rookie Scale extensions
- contract conversions

Examples:
- Coby White re-signing -> additional FA/lifecycle research signal
- Marcus Smart new-team signing -> additional FA/lifecycle research signal
- Jonathan Isaac waiver -> waiver/guarantee decision signal
- Victor Wembanyama Rookie Scale Extension -> no FA signal

The output is a RESEARCH QUEUE, not a final free-agent list.

No checkpoint mutation occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 OFFSEASON DECISION-UNIVERSE COMPLETENESS AUDIT V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(
        f"Original lifecycle universe:           {len(lifecycle_ids)}",
        flush=True,
    )
    print(
        f"Additional lifecycle research queue:   {len(omitted_candidates)}",
        flush=True,
    )
    for key, value in sorted(candidate_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print(
        f"Extensions excluded from FA signal:    {len(extension_rows)}",
        flush=True,
    )
    print(
        f"Trades excluded from FA signal:        {len(trade_rows)}",
        flush=True,
    )
    print("Old 132-player market complete:         NO", flush=True)
    print("State mutation:                         NOT PERFORMED", flush=True)
    print("Checkpoint write:                      NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
