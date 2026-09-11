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

VERSION = "fa-non-rfa-rights-final15-targeted-resolution-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = "2026-04-12"

EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

NBA_FREE_AGENCY_EXPLAINER = "https://www.nba.com/news/free-agency-explained"
NBA_MOVEMENT_SOURCE = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"

# Explicit targeted evidence bridge. All evidence is pre-split.
TARGETS = {
    "203994": {
        "player_name": "Jusuf Nurkić",
        "prior_team": "UTA",
        "classification": "bird",
        "reason": (
            "Three-season-plus continuity preserved through trades only: "
            "POR re-signing, then trades POR->PHX->CHA->UTA."
        ),
        "required_events": [
            ("2022-07-06", "Signing", "POR"),
            ("2023-09-27", "Trade", "PHX"),
            ("2025-02-06", "Trade", "CHA"),
            ("2025-06-29", "Trade", "UTA"),
        ],
        "supplemental_source": "",
    },
    "1626192": {
        "player_name": "Pat Connaughton",
        "prior_team": "CHA",
        "classification": "bird",
        "reason": (
            "Long-running MIL Bird lineage transferred by trade to CHA in 2025. "
            "CHA waiver and same-team rest-of-season re-signing do not introduce "
            "a new-team free-agent signing."
        ),
        "required_events": [
            ("2022-07-18", "Signing", "MIL"),
            ("2025-07-06", "Trade", "CHA"),
            ("2026-02-04", "Waive", "CHA"),
            ("2026-02-09", "Signing", "CHA"),
        ],
        "supplemental_source": "https://www.nba.com/players/transactions?TeamID=1610612766",
    },
    "1627752": {
        "player_name": "Taurean Prince",
        "prior_team": "MIL",
        "classification": "early_bird",
        "reason": (
            "MIL contracts cover both 2024-25 and 2025-26. The older LAL->MIL "
            "free-agent team change prevents Bird, but two-season MIL continuity "
            "supports Early Bird."
        ),
        "required_events": [
            ("2024-07-09", "Signing", "MIL"),
            ("2025-07-08", "Signing", "MIL"),
        ],
        "supplemental_source": "",
    },
    "1628418": {
        "player_name": "Thomas Bryant",
        "prior_team": "CLE",
        "classification": "non_bird",
        "reason": (
            "Signed with CLE for 2025-26 after playing for IND in 2024-25. "
            "The new-team free-agent signing in the current season resets "
            "Bird/Early Bird continuity."
        ),
        "required_events": [
            ("2024-12-15", "Trade", "IND"),
        ],
        "supplemental_event": ("2025-09-25", "Signing", "CLE"),
        "supplemental_source": "https://www.nba.com/news/cavaliers-sign-thomas-bryant",
    },
    "1628964": {
        "player_name": "Mo Bamba",
        "prior_team": "UTA",
        "classification": "not_applicable",
        "reason": (
            "Last pre-split NBA contract was a second UTA 10-Day Contract, "
            "which ended before the split with no later standard contract."
        ),
        "required_events": [
            ("2026-02-26", "Signing", "UTA"),
            ("2026-03-08", "Signing", "UTA"),
        ],
        "supplemental_source": "https://www.nba.com/jazz/news/utah-jazz-sign-mo-bamba-to-second-10-day-contract",
    },
    "1629013": {
        "player_name": "Landry Shamet",
        "prior_team": "NYK",
        "classification": "early_bird",
        "reason": (
            "NYK contracts cover portions of both 2024-25 and 2025-26, "
            "supporting two-season Early Bird continuity."
        ),
        "required_events": [
            ("2024-12-23", "Signing", "NYK"),
        ],
        "supplemental_event": ("2025-09-16", "Signing", "NYK"),
        "supplemental_source": "https://www.nba.com/knicks/news/new-york-knicks-re-sign-landry-shamet-to-an-exhibit-9-contract",
    },
    "1629028": {
        "player_name": "Deandre Ayton",
        "prior_team": "LAL",
        "classification": "non_bird",
        "reason": (
            "POR waived Ayton, then he signed with LAL for 2025-26. "
            "The new-team free-agent signing creates one-season LAL continuity."
        ),
        "required_events": [
            ("2025-06-29", "Waive", "POR"),
            ("2025-07-06", "Signing", "LAL"),
        ],
        "supplemental_source": "",
    },
    "1629646": {
        "player_name": "Charles Bassey",
        "prior_team": "GSW",
        "classification": "non_bird",
        "reason": (
            "After short contracts with several teams, Bassey signed a standard "
            "GSW contract on Apr. 5, 2026. That is less than two-season continuity."
        ),
        "required_events": [
            ("2026-01-26", "Signing", "PHI"),
            ("2026-02-05", "Signing", "PHI"),
            ("2026-03-15", "Signing", "BOS"),
            ("2026-03-25", "Signing", "BOS"),
            ("2026-04-05", "Signing", "GSW"),
        ],
        "supplemental_source": "https://gleague.nba.com/news/golden-state-warriors-sign-charles-bassey-to-contract",
    },
    "1629680": {
        "player_name": "Matisse Thybulle",
        "prior_team": "POR",
        "classification": "bird",
        "reason": (
            "PHI->POR trade preserved rights and the POR contract signed in 2023 "
            "covers through 2025-26, establishing three-season continuity."
        ),
        "required_events": [
            ("2023-02-09", "Trade", "POR"),
            ("2023-07-10", "Signing", "POR"),
        ],
        "supplemental_source": "",
    },
    "1629750": {
        "player_name": "Javonte Green",
        "prior_team": "DET",
        "classification": "non_bird",
        "reason": (
            "Green signed with DET in Aug. 2025 after ending 2024-25 with CLE, "
            "so DET has only current-season continuity."
        ),
        "required_events": [
            ("2025-02-23", "Signing", "CLE"),
            ("2025-08-14", "Signing", "DET"),
        ],
        "supplemental_source": "",
    },
    "1630173": {
        "player_name": "Precious Achiuwa",
        "prior_team": "SAC",
        "classification": "non_bird",
        "reason": (
            "After the 2025 MIA waiver, Achiuwa signed with SAC in Nov. 2025. "
            "That new-team signing gives SAC one-season continuity."
        ),
        "required_events": [
            ("2025-10-17", "Waive", "MIA"),
            ("2025-11-04", "Signing", "SAC"),
        ],
        "supplemental_source": "",
    },
    "1630572": {
        "player_name": "Sandro Mamukelashvili",
        "prior_team": "TOR",
        "classification": "non_bird",
        "reason": (
            "Mamukelashvili signed with TOR in July 2025 after playing for SAS, "
            "creating one-season TOR continuity."
        ),
        "required_events": [
            ("2024-07-22", "Signing", "SAS"),
            ("2025-07-03", "Signing", "TOR"),
        ],
        "supplemental_source": "",
    },
    "1630579": {
        "player_name": "Jericho Sims",
        "prior_team": "MIL",
        "classification": "bird",
        "reason": (
            "NYK multi-season contract lineage transferred to MIL by trade in "
            "Feb. 2025, and MIL re-signed Sims in July 2025. Trade continuity "
            "preserves the three-season Bird lineage."
        ),
        "required_events": [
            ("2022-07-09", "Signing", "NYK"),
            ("2025-02-06", "Trade", "MIL"),
            ("2025-07-09", "Signing", "MIL"),
        ],
        "supplemental_source": "",
    },
    "1630692": {
        "player_name": "Jordan Goodwin",
        "prior_team": "PHX",
        "classification": "early_bird",
        "reason": (
            "Goodwin had an LAL contract during 2024-25 and was claimed by PHX "
            "via waivers in July 2025. Waiver assignment preserves two-season "
            "Early Bird continuity."
        ),
        "required_events": [
            ("2025-02-07", "Signing", "LAL"),
            ("2025-03-27", "Signing", "LAL"),
            ("2025-07-20", "Waive", "LAL"),
            ("2025-07-23", "AwardOnWaivers", "PHX"),
        ],
        "supplemental_source": "",
    },
    "1642440": {
        "player_name": "Gabe McGlothan",
        "prior_team": "IND",
        "classification": "not_applicable",
        "reason": (
            "Last pre-split NBA contract was the IND 10-Day hardship contract "
            "signed Dec. 16, 2025; no later NBA contract occurred before split."
        ),
        "required_events": [
            ("2025-12-16", "Signing", "IND"),
        ],
        "supplemental_source": "https://gleague.nba.com/news/gabe-mcglothan-earns-nba-call-up-with-indiana-pacers",
    },
}

EXPECTED_FINAL_COUNTS = Counter({
    "bird": 44,
    "early_bird": 14,
    "non_bird": 48,
    "not_applicable": 56,
})


def clean(v: Any) -> str:
    return str(v or "").strip()


def pid(v: Any) -> str:
    t = clean(v)
    return t[:-2] if t.endswith(".0") and t[:-2].isdigit() else t


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def latest(root: Path, pattern: str) -> Path:
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    if not paths:
        raise RuntimeError(f"Missing required audit: {pattern}")
    return max(paths, key=lambda p: p.stat().st_mtime)


def read_csv_suffix(z: zipfile.ZipFile, suffix: str):
    n = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not n:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = z.read(n).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_suffix(z: zipfile.ZipFile, suffix: str):
    n = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not n:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(n).decode("utf-8-sig"))


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
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def event_exists(
    movement_by_id: dict[str, list[dict[str, str]]],
    player_id: str,
    event: tuple[str, str, str],
) -> bool:
    date_text, transaction_type, team = event
    for row in movement_by_id.get(player_id, []):
        if (
            clean(row.get("transaction_date"))[:10] == date_text
            and clean(row.get("transaction_type")) == transaction_type
            and clean(row.get("team_abbreviation")).upper() == team
        ):
            return True
    return False


def main() -> int:
    root = Path.cwd().resolve()

    completion_zip = latest(
        root,
        "fa_non_rfa_rights_evidence_completion_v1_2026-27_*.zip",
    )
    movement_zip = latest(
        root,
        "fa_post_split_roster_provenance_audit_v1_0_2_2026-27_*.zip",
    )

    with zipfile.ZipFile(completion_zip) as z:
        completion_summary = read_json_suffix(
            z, "non_rfa_rights_completion_summary.json"
        )
        completed_162 = read_csv_suffix(
            z, "non_rfa_rights_completed_162.csv"
        )
        unresolved_15 = read_csv_suffix(
            z, "non_rfa_rights_unresolved_15.csv"
        )

    with zipfile.ZipFile(movement_zip) as z:
        movement_rows = read_csv_suffix(
            z, "player_movement_rows_canonical.csv"
        )

    if not completion_summary.get("passed"):
        raise RuntimeError("Upstream rights completion did not pass.")
    if len(completed_162) != 162 or len(unresolved_15) != 15:
        raise RuntimeError("Expected 162 completed rows and exact unresolved 15.")

    unresolved_ids = {pid(r["player_id"]) for r in unresolved_15}
    if unresolved_ids != set(TARGETS):
        raise RuntimeError(
            "Target 15 IDs do not exactly match the upstream unresolved set."
        )

    movement_by_id: dict[str, list[dict[str, str]]] = {}
    for row in movement_rows:
        p = pid(row.get("player_id"))
        movement_by_id.setdefault(p, []).append(row)

    target_rows = []
    missing_required_events = []

    for player_id, evidence in TARGETS.items():
        missing = []
        for event in evidence.get("required_events", []):
            if not event_exists(movement_by_id, player_id, event):
                missing.append(event)

        # Supplemental event facts are independently verified official
        # pre-split evidence and are not expected to exist in the canonical
        # movement JSON when the feed omitted the row.
        supplemental_event = evidence.get("supplemental_event")
        if supplemental_event:
            date_text = supplemental_event[0]
            if date_text > SPLIT_DATE:
                raise RuntimeError(
                    f"Post-split supplemental event forbidden for {player_id}."
                )

        if missing:
            missing_required_events.append({
                "player_id": player_id,
                "player_name": evidence["player_name"],
                "missing_events": "|".join(
                    f"{d}:{t}:{team}" for d, t, team in missing
                ),
            })

        latest_required_date = max(
            [e[0] for e in evidence.get("required_events", [])]
            + ([supplemental_event[0]] if supplemental_event else [])
        )

        target_rows.append({
            "player_id": player_id,
            "player_name": evidence["player_name"],
            "prior_team": evidence["prior_team"],
            "proposed_rights_classification": evidence["classification"],
            "resolution_reason": evidence["reason"],
            "latest_evidence_date": latest_required_date,
            "all_evidence_pre_split": latest_required_date <= SPLIT_DATE,
            "canonical_required_event_count": len(
                evidence.get("required_events", [])
            ),
            "canonical_required_events_verified": not missing,
            "supplemental_event": (
                ":".join(supplemental_event)
                if supplemental_event else ""
            ),
            "supplemental_source": evidence.get(
                "supplemental_source", ""
            ),
            "cba_source": NBA_FREE_AGENCY_EXPLAINER,
            "movement_source": NBA_MOVEMENT_SOURCE,
            "classification_applied_to_simulation": False,
        })

    # Merge proposals into a complete 162-row preview.
    target_by_id = {r["player_id"]: r for r in target_rows}
    final_preview = []
    overwrite_conflicts = []

    for row in completed_162:
        p = pid(row["player_id"])
        existing = clean(row.get("final_rights_classification"))
        proposed = clean(
            target_by_id.get(p, {}).get(
                "proposed_rights_classification"
            )
        )

        if existing and proposed and existing != proposed:
            overwrite_conflicts.append({
                "player_id": p,
                "player_name": clean(row.get("player_name")),
                "existing": existing,
                "proposed": proposed,
            })

        final_classification = existing or proposed
        final_preview.append({
            "player_id": p,
            "player_name": clean(row.get("player_name")),
            "prior_team": clean(row.get("prior_team")),
            "final_rights_classification": final_classification,
            "evidence_mode": (
                clean(row.get("evidence_mode"))
                if existing
                else "targeted_final15_pre_split_resolution_preview_v1"
            ),
            "rights_resolved": bool(final_classification),
            "classification_applied_to_simulation": False,
        })

    final_counts = Counter(
        row["final_rights_classification"]
        for row in final_preview
        if row["final_rights_classification"]
    )
    still_unresolved = [
        row for row in final_preview if not row["rights_resolved"]
    ]

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before final15 preview.")

    checks = []

    def add(cid: str, ok: bool, detail: str):
        checks.append({
            "check_id": cid,
            "status": "PASS" if ok else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"  {cid}: {'PASS' if ok else 'FAIL'}")

    print("=" * 128)
    print("2026 NON-RFA RIGHTS FINAL 15 TARGETED RESOLUTION PREVIEW V1")
    print("=" * 128)
    print("Running checks...")

    add(
        "upstream_147_of_162_completion_passed",
        bool(completion_summary.get("passed"))
        and int(completion_summary.get("resolved_count", -1)) == 147,
        "147/162 frozen evidence completion is upstream.",
    )
    add(
        "exact_15_target_ids_match_unresolved_set",
        unresolved_ids == set(TARGETS),
        f"targets={len(TARGETS)}",
    )
    add(
        "all_canonical_required_events_verified",
        len(missing_required_events) == 0,
        f"missing_required_event_players={len(missing_required_events)}",
    )
    add(
        "all_target_evidence_is_pre_split",
        all(row["all_evidence_pre_split"] for row in target_rows),
        f"split_date={SPLIT_DATE}",
    )
    add(
        "no_existing_rights_overwritten",
        len(overwrite_conflicts) == 0,
        f"overwrite_conflicts={len(overwrite_conflicts)}",
    )
    add(
        "exact_162_of_162_preview_rights_resolved",
        len(still_unresolved) == 0
        and len(final_preview) == 162,
        f"resolved={162-len(still_unresolved)}/162",
    )
    add(
        "final_distribution_is_expected",
        final_counts == EXPECTED_FINAL_COUNTS,
        repr(dict(final_counts)),
    )
    add(
        "classifications_not_applied_to_simulation",
        all(
            not row["classification_applied_to_simulation"]
            for row in final_preview
        ),
        "Preview only.",
    )

    after_state = object_digest(checkpoint.simulation_state)
    after_hash = sha256_file(checkpoint_path)

    add(
        "loaded_simulation_state_unchanged",
        after_state == before_state,
        after_state,
    )
    add(
        "checkpoint_file_unchanged",
        after_hash
        == before_hash
        == EXPECTED_CHECKPOINT_SHA256,
        after_hash,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_non_rfa_rights_final15_targeted_resolution_preview_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "upstream_resolved_count": 147,
        "targeted_resolution_count": 15,
        "preview_resolved_count": 162,
        "preview_unresolved_count": len(still_unresolved),
        "final_classification_counts": dict(
            sorted(final_counts.items())
        ),
        "missing_required_event_count": len(
            missing_required_events
        ),
        "overwrite_conflict_count": len(overwrite_conflicts),
        "all_evidence_pre_split": all(
            row["all_evidence_pre_split"]
            for row in target_rows
        ),
        "classifications_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "If this preview passes, freeze the 15 targeted classifications "
            "into the non-RFA rights evidence table, yielding 162/162 rights "
            "completion. Keep prior-salary completion separate before computing "
            "full-market Free Agent Amounts."
        ),
    }

    with tempfile.TemporaryDirectory(
        prefix="fa_non_rfa_final15_preview_"
    ) as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "final15_targeted_rights_proposals.csv",
            target_rows,
        )
        write_csv(
            export / "final15_missing_required_events.csv",
            missing_required_events,
        )
        write_csv(
            export / "final15_overwrite_conflicts.csv",
            overwrite_conflicts,
        )
        write_csv(
            export / "non_rfa_rights_preview_complete_162.csv",
            final_preview,
        )
        write_csv(
            export / "final15_targeted_resolution_checks.csv",
            checks,
        )

        (export / "final15_targeted_resolution_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 NON-RFA RIGHTS FINAL 15 TARGETED RESOLUTION PREVIEW V1
================================================================

Purpose
-------
Resolve the final 15 fail-closed non-RFA rights timelines using explicit,
player-specific pre-split evidence.

Evidence sources
----------------
1. Official NBA Player Movement JSON already audited into the project.
2. Targeted official NBA/team sources only where the movement feed omitted
   a necessary pre-split event.
3. NBA Free Agency Explained for the Bird / Early Bird / Non-Bird framework.

No post-April-12, 2026 transaction outcome is permitted to determine a
classification.

Expected 162-player final preview:
- Bird: 44
- Early Bird: 14
- Non-Bird: 48
- Not applicable: 56

This package is READ ONLY.
No rights are applied to simulation state.
No cap hold is computed.
No checkpoint write occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            audit_zip, "w", zipfile.ZIP_DEFLATED
        ) as z:
            for item in sorted(export.iterdir()):
                z.write(
                    item,
                    arcname=f"{export_id}/{item.name}",
                )

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Final 15 targeted rights preview failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 128)
    print("2026 NON-RFA RIGHTS FINAL 15 TARGETED RESOLUTION PREVIEW V1 PASSED")
    print("=" * 128)
    print("Upstream rights resolved: 147/162")
    print("Targeted proposals:        15/15")
    print("Preview rights resolved:   162/162")
    print("Rights applied:            0")
    print("Checkpoint write:          NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
