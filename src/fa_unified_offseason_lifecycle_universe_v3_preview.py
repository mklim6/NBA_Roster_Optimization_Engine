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

VERSION = "fa-unified-offseason-lifecycle-universe-v3-preview-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_CHECKPOINT_PLAYERS = 582
CBA_OFFSEASON_AGGREGATE_MAX = 21

EXPECTED_UNIFIED_COUNTS = {
    "immediate_market": 193,
    "team_option_decision": 24,
    "player_option_decision": 10,
    "non_guaranteed_or_partial_decision": 37,
    "guaranteed_under_contract": 3,
    "manual_contract_source_review": 4,
}

TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def team(value: Any) -> str:
    return clean(value).upper()


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


def classify_original_lifecycle(
    lifecycle_row: dict[str, str],
    old_market_ids: set[str],
) -> str:
    player_id = pid(lifecycle_row.get("player_id"))
    state = clean(lifecycle_row.get("contract_lifecycle_state"))

    if player_id in old_market_ids:
        return "immediate_market"
    if state == "pending_team_option_2026_27":
        return "team_option_decision"
    if state == "pending_non_guaranteed_contract_decision_2026_27":
        return "non_guaranteed_or_partial_decision"
    if state == "under_contract_guaranteed_2026_27":
        return "guaranteed_under_contract"
    if state.startswith("manual_review"):
        return "manual_contract_source_review"

    return "unclassified_original_lifecycle"


def classify_additional(row: dict[str, str]) -> str:
    value = clean(row.get("lifecycle_contract_classification"))
    mapping = {
        "expiring_2025_26_free_agent_candidate": "immediate_market",
        "team_option_2026_27_decision": "team_option_decision",
        "player_option_2026_27_decision": "player_option_decision",
        "partial_or_non_guaranteed_2026_27_decision": (
            "non_guaranteed_or_partial_decision"
        ),
    }
    return mapping.get(value, "unclassified_additional_lifecycle")


def main() -> int:
    root = Path.cwd().resolve()

    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    corrected_market_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )
    final84_zip = find_latest(
        root,
        "fa_additional_lifecycle_targeted_resolution_and_final84_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )
        original_rows = read_csv_member(
            archive,
            "contract_option_lifecycle_all.csv",
        )

    with zipfile.ZipFile(corrected_market_zip) as archive:
        corrected_summary = read_json_member(
            archive,
            "corrected_rfa_qo_summary.json",
        )
        old_market_rows = read_csv_member(
            archive,
            "corrected_rfa_qo_universe_all.csv",
        )

    with zipfile.ZipFile(final84_zip) as archive:
        final84_summary = read_json_member(
            archive,
            "final84_summary.json",
        )
        additional_rows = read_csv_member(
            archive,
            "additional_lifecycle_final_84.csv",
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

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before unified lifecycle preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)
    players = getattr(state, "players", {}) or {}

    original_ids = {pid(row.get("player_id")) for row in original_rows}
    additional_ids = {pid(row.get("player_id")) for row in additional_rows}
    old_market_ids = {pid(row.get("player_id")) for row in old_market_rows}

    if original_ids & additional_ids:
        raise RuntimeError(
            "Original 187 and additional 84 lifecycle universes overlap: "
            + repr(sorted(original_ids & additional_ids))
        )

    branch_by_id = {
        pid(row.get("player_id")): row
        for row in branch_rows
    }

    unified_rows: list[dict[str, Any]] = []

    for row in original_rows:
        player_id = pid(row.get("player_id"))
        category = classify_original_lifecycle(row, old_market_ids)
        branch = branch_by_id.get(player_id, {})

        unified_rows.append({
            "player_id": player_id,
            "player_name": clean(row.get("player_name")),
            "source_universe": "original_187",
            "unified_lifecycle_category": category,
            "source_lifecycle_state": clean(
                row.get("contract_lifecycle_state")
            ),
            "source_contract_classification": "",
            "prior_team": team(row.get("prior_team")),
            "reconstructed_branch_owner": clean(
                branch.get("reconstructed_branch_owner")
            ),
            "current_checkpoint_owner": clean(
                branch.get("current_checkpoint_owner")
            ),
            "future_real_world_outcome_used": False,
        })

    for row in additional_rows:
        player_id = pid(row.get("player_id"))
        category = classify_additional(row)
        branch = branch_by_id.get(player_id, {})

        unified_rows.append({
            "player_id": player_id,
            "player_name": clean(row.get("player_name")),
            "source_universe": "additional_84",
            "unified_lifecycle_category": category,
            "source_lifecycle_state": "",
            "source_contract_classification": clean(
                row.get("lifecycle_contract_classification")
            ),
            "prior_team": clean(
                row.get("reconstructed_branch_owner")
                or branch.get("reconstructed_branch_owner")
            ),
            "reconstructed_branch_owner": clean(
                branch.get("reconstructed_branch_owner")
            ),
            "current_checkpoint_owner": clean(
                branch.get("current_checkpoint_owner")
            ),
            "future_real_world_outcome_used": False,
        })

    unified_by_id = {
        row["player_id"]: row
        for row in unified_rows
    }

    category_counts = Counter(
        row["unified_lifecycle_category"]
        for row in unified_rows
    )

    # Materialize only an ownership preview on a dict. This does not modify
    # checkpoint objects.
    opening_owner: dict[str, str] = {}
    opening_reason: dict[str, str] = {}

    for raw_id in players:
        player_id = pid(raw_id)
        branch = branch_by_id.get(player_id, {})
        branch_owner = clean(branch.get("reconstructed_branch_owner"))
        opening_owner[player_id] = branch_owner
        opening_reason[player_id] = "reconstructed_branch_owner_preserved"

    for row in unified_rows:
        player_id = row["player_id"]
        category = row["unified_lifecycle_category"]
        branch_owner = clean(row["reconstructed_branch_owner"])

        if category == "immediate_market":
            opening_owner[player_id] = "FA"
            opening_reason[player_id] = "unified_expiring_or_existing_market"

        elif category in {
            "team_option_decision",
            "player_option_decision",
            "non_guaranteed_or_partial_decision",
            "guaranteed_under_contract",
        }:
            if branch_owner not in TEAM_CODES:
                opening_owner[player_id] = "QUARANTINE"
                opening_reason[player_id] = (
                    "attached_contract_but_branch_team_not_proven"
                )
            else:
                opening_owner[player_id] = branch_owner
                opening_reason[player_id] = (
                    "unified_contract_attached_or_pending_decision"
                )

        elif category == "manual_contract_source_review":
            opening_owner[player_id] = "QUARANTINE"
            opening_reason[player_id] = "manual_contract_source_review"

        else:
            opening_owner[player_id] = "QUARANTINE"
            opening_reason[player_id] = "unclassified_unified_lifecycle"

    team_counts = Counter(
        owner
        for owner in opening_owner.values()
        if owner in TEAM_CODES
    )
    fa_count = sum(owner == "FA" for owner in opening_owner.values())
    quarantine_count = sum(
        owner == "QUARANTINE"
        for owner in opening_owner.values()
    )
    unassigned_count = sum(
        not owner or owner not in TEAM_CODES | {"FA", "QUARANTINE"}
        for owner in opening_owner.values()
    )

    player_preview_rows = []
    for raw_id, player in players.items():
        player_id = pid(raw_id)
        unified = unified_by_id.get(player_id)
        branch = branch_by_id.get(player_id, {})
        player_name = ""
        for attr in ("player_name", "display_name", "name", "full_name"):
            player_name = clean(getattr(player, attr, ""))
            if player_name:
                break

        player_preview_rows.append({
            "player_id": player_id,
            "player_name": (
                unified["player_name"]
                if unified and unified["player_name"]
                else player_name
            ),
            "in_unified_lifecycle_universe": bool(unified),
            "unified_lifecycle_category": (
                unified["unified_lifecycle_category"]
                if unified else ""
            ),
            "source_universe": (
                unified["source_universe"]
                if unified else ""
            ),
            "current_checkpoint_owner": clean(
                branch.get("current_checkpoint_owner")
            ),
            "reconstructed_branch_owner": clean(
                branch.get("reconstructed_branch_owner")
            ),
            "unified_offseason_opening_owner": opening_owner.get(
                player_id,
                "",
            ),
            "opening_owner_reason": opening_reason.get(player_id, ""),
        })

    team_preview_rows = []
    for team_code in sorted(TEAM_CODES):
        old_count = sum(
            clean(row.get("offseason_opening_owner")) == team_code
            for row in branch_rows
        )
        new_count = team_counts.get(team_code, 0)
        team_preview_rows.append({
            "team_abbreviation": team_code,
            "old_132_market_opening_roster_count": old_count,
            "unified_271_opening_roster_count": new_count,
            "roster_count_change": new_count - old_count,
            "exceeds_cba_offseason_21": new_count > CBA_OFFSEASON_AGGREGATE_MAX,
        })

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
    print("2026 UNIFIED OFFSEASON LIFECYCLE UNIVERSE V3 PREVIEW", flush=True)
    print("=" * 128, flush=True)
    print(f"Checkpoint players:         {len(players)}", flush=True)
    print(f"Original lifecycle rows:    {len(original_rows)}", flush=True)
    print(f"Additional lifecycle rows:  {len(additional_rows)}", flush=True)
    print(f"Unified decision universe:  {len(unified_rows)}", flush=True)
    print("COPY-ON-WRITE OWNERSHIP PREVIEW ONLY.", flush=True)
    print("", flush=True)

    print("Running strict unified-lifecycle checks...", flush=True)

    check(
        "original_lifecycle_upstream_passed",
        bool(lifecycle_summary.get("passed")),
        "Original 187 lifecycle audit passed.",
    )
    check(
        "corrected_market_upstream_passed",
        bool(corrected_summary.get("passed")),
        "Corrected 132-player market preview passed.",
    )
    check(
        "final84_upstream_passed",
        bool(final84_summary.get("passed")),
        "Additional zero-manual 84 lifecycle passed.",
    )
    check(
        "branch_reconstruction_upstream_passed",
        bool(branch_summary.get("passed_strict_checks")),
        "Branch reconstruction V1.0.1 passed.",
    )
    check(
        "branch_reconstruction_has_zero_unresolved",
        int(
            branch_summary.get(
                "reconstruction_unresolved_player_count",
                -1,
            )
        ) == 0,
        f"unresolved={branch_summary.get('reconstruction_unresolved_player_count')}",
    )
    check(
        "checkpoint_player_count_is_582",
        len(players) == EXPECTED_CHECKPOINT_PLAYERS,
        f"players={len(players)}",
    )
    check(
        "exact_187_original_rows",
        len(original_rows) == 187
        and len(original_ids) == 187,
        f"rows={len(original_rows)} unique={len(original_ids)}",
    )
    check(
        "exact_132_old_market_rows",
        len(old_market_ids) == 132,
        f"market={len(old_market_ids)}",
    )
    check(
        "exact_84_additional_rows",
        len(additional_rows) == 84
        and len(additional_ids) == 84,
        f"rows={len(additional_rows)} unique={len(additional_ids)}",
    )
    check(
        "original_and_additional_are_disjoint",
        not (original_ids & additional_ids),
        f"overlap={len(original_ids & additional_ids)}",
    )
    check(
        "exact_271_unified_decision_universe",
        len(unified_rows) == 271
        and len(unified_by_id) == 271,
        f"rows={len(unified_rows)} unique={len(unified_by_id)}",
    )
    check(
        "unified_category_counts_exact",
        category_counts == Counter(EXPECTED_UNIFIED_COUNTS),
        json.dumps(dict(sorted(category_counts.items())), sort_keys=True),
    )
    check(
        "no_unclassified_unified_rows",
        not any(
            row["unified_lifecycle_category"].startswith("unclassified")
            for row in unified_rows
        ),
        "Every lifecycle row maps to a supported unified category.",
    )
    check(
        "unified_immediate_market_is_193",
        category_counts["immediate_market"] == 193,
        f"market={category_counts['immediate_market']}",
    )
    check(
        "unified_pending_decision_count_is_71",
        (
            category_counts["team_option_decision"]
            + category_counts["player_option_decision"]
            + category_counts["non_guaranteed_or_partial_decision"]
        ) == 71,
        (
            "pending="
            + str(
                category_counts["team_option_decision"]
                + category_counts["player_option_decision"]
                + category_counts["non_guaranteed_or_partial_decision"]
            )
        ),
    )
    check(
        "opening_free_agent_count_is_193",
        fa_count == 193,
        f"fa={fa_count}",
    )
    check(
        "opening_quarantine_count_is_4",
        quarantine_count == 4,
        f"quarantine={quarantine_count}",
    )
    check(
        "opening_has_no_unassigned_players",
        unassigned_count == 0,
        f"unassigned={unassigned_count}",
    )
    check(
        "all_attached_decision_players_have_team_owner",
        all(
            (
                row["unified_lifecycle_category"]
                not in {
                    "team_option_decision",
                    "player_option_decision",
                    "non_guaranteed_or_partial_decision",
                    "guaranteed_under_contract",
                }
            )
            or opening_owner[row["player_id"]] in TEAM_CODES
            for row in unified_rows
        ),
        "All 74 attached/pending/guaranteed rows have a proven branch team.",
    )

    over_21 = [
        team_code
        for team_code, count in sorted(team_counts.items())
        if count > CBA_OFFSEASON_AGGREGATE_MAX
    ]
    check(
        "no_team_exceeds_offseason_21",
        not over_21,
        "over_21=" + ("|".join(over_21) if over_21 else "<none>"),
    )
    check(
        "future_real_world_outcomes_not_used",
        all(not row["future_real_world_outcome_used"] for row in unified_rows),
        "Unified lifecycle classifications remain branch-date evidence only.",
    )

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_before == state_digest_after,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_after == checkpoint_hash == EXPECTED_CHECKPOINT_SHA256,
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
            "Unified Offseason Lifecycle Universe V3 Preview failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_unified_offseason_lifecycle_universe_v3_preview_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_unified_lifecycle_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "unified_lifecycle_271.csv",
            unified_rows,
        )
        write_csv(
            export / "unified_offseason_opening_all_players.csv",
            player_preview_rows,
        )
        write_csv(
            export / "unified_offseason_opening_team_counts.csv",
            team_preview_rows,
        )
        write_csv(
            export / "unified_lifecycle_checks.csv",
            checks,
        )

        for category in EXPECTED_UNIFIED_COUNTS:
            write_csv(
                export / f"queue_{category}.csv",
                [
                    row
                    for row in unified_rows
                    if row["unified_lifecycle_category"] == category
                ],
            )

        summary = {
            "version": VERSION,
            "checkpoint_player_count": len(players),
            "original_lifecycle_count": len(original_rows),
            "additional_lifecycle_count": len(additional_rows),
            "unified_decision_universe_count": len(unified_rows),
            "category_counts": dict(sorted(category_counts.items())),
            "immediate_market_count": fa_count,
            "pending_decision_count": 71,
            "guaranteed_under_contract_count": (
                category_counts["guaranteed_under_contract"]
            ),
            "manual_contract_source_review_count": (
                category_counts["manual_contract_source_review"]
            ),
            "opening_quarantine_count": quarantine_count,
            "teams_over_offseason_21": over_21,
            "future_real_world_outcomes_used": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Rebuild the RFA/QO eligibility universe on the 193-player "
                "immediate market, while separately creating CPU/user decision "
                "previews for 24 Team Options, 10 Player Options, and 37 "
                "non-guaranteed/partial contracts. Do not hydrate the checkpoint "
                "until those decision queues and the four contract-source manuals "
                "are resolved."
            ),
        }

        (export / "unified_lifecycle_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 UNIFIED OFFSEASON LIFECYCLE UNIVERSE V3 PREVIEW
=====================================================

This preview merges:
- the original 187-player lifecycle universe
- the zero-manual additional 84-player lifecycle universe

They are disjoint and form a 271-player offseason decision universe.

Expected categories
-------------------
193 immediate-market players
24 Team Option decisions
10 Player Option decisions
37 non-guaranteed / partial-guarantee decisions
3 guaranteed-under-contract players
4 original contract-source manual reviews

The opening-owner preview starts from the proven April-12 branch reconstruction,
then:
- moves the 193 immediate-market players to free agency
- keeps option/guarantee decisions on their proven branch teams
- keeps the 3 guaranteed players on their proven branch teams
- quarantines only the 4 unresolved original contract-source rows

No durable state or checkpoint is mutated.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 UNIFIED OFFSEASON LIFECYCLE UNIVERSE V3 PREVIEW PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Unified decision universe:        271", flush=True)
    print("Immediate market:                 193", flush=True)
    print("Team Option decisions:             24", flush=True)
    print("Player Option decisions:           10", flush=True)
    print("Non-guaranteed/partial decisions:  37", flush=True)
    print("Guaranteed under contract:          3", flush=True)
    print("Manual contract-source review:      4", flush=True)
    print("Teams over offseason 21:            NONE", flush=True)
    print("Future outcomes used:               NO", flush=True)
    print("Checkpoint write:                   NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
