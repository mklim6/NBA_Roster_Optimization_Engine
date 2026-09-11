from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pickle
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-rights-retention-renouncement-preview-v1-2026-08-14"
SEASON_LABEL = "2026-27"
SALARY_CAP = 164_961_000.0

EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_PLAYERS = 64
EXPECTED_CONTROLLED_TEAM = "CHI"
EXPECTED_CHI_PLAYERS = {
    "Lachlan Olbrich",
    "Mouhamadou Gueye",
    "Yuki Kawamura",
}

RIGHTS_PREMIUM = {
    "bird": 0.15,
    "early_bird": 0.10,
    "non_bird": 0.04,
    "two_way_special": 0.06,
}

CBA_SOURCE = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = clean(value).lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


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
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
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


def rights_type(cap_row: dict[str, str]) -> str:
    rights = clean(cap_row.get("rights_classification"))
    if rights:
        return rights

    if clean(cap_row.get("evidence_mode")) == "frozen_v1_0_1_two_way_exact":
        return "two_way_special"

    return "unknown"


def recommendation_score(
    *,
    market_reference: float,
    cap_hold: float,
    rights: str,
    qo_model_recommendation: str,
    roster_count: int,
) -> dict[str, Any]:
    ratio = market_reference / cap_hold

    rights_premium = RIGHTS_PREMIUM.get(rights, 0.0)

    # Keep QO and rights decisions separate. This is only an alignment
    # adjustment: a positive QO advisory increases the value of preserving
    # RFA optionality, while a negative QO advisory mildly lowers it.
    qo_alignment = (
        0.08 if qo_model_recommendation == "issue_qo"
        else -0.02 if qo_model_recommendation == "do_not_issue_qo"
        else 0.0
    )

    if roster_count <= 13:
        roster_adjustment = 0.03
    elif roster_count <= 16:
        roster_adjustment = 0.00
    elif roster_count <= 18:
        roster_adjustment = -0.03
    else:
        roster_adjustment = -0.05

    cap_hold_pct_cap = cap_hold / SALARY_CAP
    if cap_hold_pct_cap >= 0.12:
        burden_adjustment = -0.12
    elif cap_hold_pct_cap >= 0.08:
        burden_adjustment = -0.08
    elif cap_hold_pct_cap >= 0.04:
        burden_adjustment = -0.04
    else:
        burden_adjustment = 0.0

    score = (
        ratio
        + rights_premium
        + qo_alignment
        + roster_adjustment
        + burden_adjustment
    )

    if ratio >= 1.05:
        model_recommendation = "retain_rights"
    elif ratio <= 0.55 and score < 0.90:
        model_recommendation = "renounce_rights"
    else:
        model_recommendation = (
            "retain_rights" if score >= 0.98 else "renounce_rights"
        )

    distance = abs(score - 0.98)
    confidence = (
        "high" if distance >= 0.35
        else "medium" if distance >= 0.15
        else "low"
    )

    return {
        "market_to_cap_hold_ratio": ratio,
        "rights_premium": rights_premium,
        "qo_alignment_adjustment": qo_alignment,
        "roster_adjustment": roster_adjustment,
        "cap_hold_burden_adjustment": burden_adjustment,
        "decision_score": score,
        "model_recommendation": model_recommendation,
        "confidence": confidence,
    }


def main() -> int:
    root = Path.cwd().resolve()

    cap_zip = find_latest(
        root,
        "fa_qo_cap_hold_completion_v1_0_1_2026-27_*.zip",
    )
    issuance_zip = find_latest(
        root,
        "fa_qo_issuance_decision_preview_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(cap_zip) as archive:
        cap_summary = read_json_member(
            archive,
            "qo_cap_hold_completion_summary.json",
        )
        cap_rows = read_csv_member(
            archive,
            "qo_exact_cap_holds_completed_64.csv",
        )

    with zipfile.ZipFile(issuance_zip) as archive:
        issuance_summary = read_json_member(
            archive,
            "qo_issuance_preview_summary.json",
        )
        issuance_rows = read_csv_member(
            archive,
            "qo_issuance_decision_board_64.csv",
        )

    if len(cap_rows) != EXPECTED_PLAYERS:
        raise RuntimeError(f"Expected 64 cap-hold rows, got {len(cap_rows)}.")
    if len(issuance_rows) != EXPECTED_PLAYERS:
        raise RuntimeError(f"Expected 64 issuance rows, got {len(issuance_rows)}.")

    cap_by_id = {pid(row.get("player_id")): row for row in cap_rows}
    issue_by_id = {pid(row.get("player_id")): row for row in issuance_rows}

    if set(cap_by_id) != set(issue_by_id):
        raise RuntimeError(
            "Cap-hold and QO issuance player ID sets do not match."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before rights-retention preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    decision_rows: list[dict[str, Any]] = []
    unknown_rights: list[dict[str, Any]] = []
    missing_market: list[dict[str, Any]] = []

    for player_id in sorted(
        issue_by_id,
        key=lambda value: clean(issue_by_id[value].get("player_name")).lower(),
    ):
        issue = issue_by_id[player_id]
        cap = cap_by_id[player_id]

        player_name = clean(issue.get("player_name"))
        prior_team = clean(issue.get("prior_team")).upper()

        market_reference = finite(issue.get("market_reference"))
        cap_hold = finite(cap.get("exact_cap_hold_2026_27"))
        roster_count = int(float(clean(issue.get("team_roster_count_before_qo")) or 0))
        rights = rights_type(cap)

        if market_reference is None or market_reference <= 0:
            missing_market.append({
                "player_id": player_id,
                "player_name": player_name,
            })

        if cap_hold is None or cap_hold <= 0:
            raise RuntimeError(
                f"Missing or invalid exact cap hold for {player_name}."
            )

        if rights == "unknown":
            unknown_rights.append({
                "player_id": player_id,
                "player_name": player_name,
                "evidence_mode": clean(cap.get("evidence_mode")),
            })

        if market_reference is None or market_reference <= 0:
            score = {
                "market_to_cap_hold_ratio": None,
                "rights_premium": None,
                "qo_alignment_adjustment": None,
                "roster_adjustment": None,
                "cap_hold_burden_adjustment": None,
                "decision_score": None,
                "model_recommendation": "manual_input_required",
                "confidence": "low",
            }
        else:
            score = recommendation_score(
                market_reference=market_reference,
                cap_hold=cap_hold,
                rights=rights,
                qo_model_recommendation=clean(
                    issue.get("model_recommendation")
                ),
                roster_count=roster_count,
            )

        controlled = clean(issue.get("recommendation")) == "user_decision_required"

        recommendation = (
            "user_decision_required"
            if controlled
            else score["model_recommendation"]
        )

        reason = (
            f"market/cap_hold={score['market_to_cap_hold_ratio']:.3f}; "
            f"rights={score['rights_premium']:+.3f}; "
            f"QO_alignment={score['qo_alignment_adjustment']:+.3f}; "
            f"roster={score['roster_adjustment']:+.3f}; "
            f"hold_burden={score['cap_hold_burden_adjustment']:+.3f}; "
            f"score={score['decision_score']:.3f}"
            if score["decision_score"] is not None
            else "Market reference unavailable."
        )

        decision_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": prior_team,
            "controlled_team": controlled,
            "rights_classification": rights,
            "exact_cap_hold_2026_27": cap_hold,
            "market_reference": market_reference,
            "market_to_cap_hold_ratio": score["market_to_cap_hold_ratio"],
            "qo_model_recommendation": clean(
                issue.get("model_recommendation")
            ),
            "qo_user_or_cpu_recommendation": clean(
                issue.get("recommendation")
            ),
            "team_roster_count_before_qo": roster_count,
            "rights_premium": score["rights_premium"],
            "qo_alignment_adjustment": score[
                "qo_alignment_adjustment"
            ],
            "roster_adjustment": score["roster_adjustment"],
            "cap_hold_burden_adjustment": score[
                "cap_hold_burden_adjustment"
            ],
            "decision_score": score["decision_score"],
            "model_recommendation": score["model_recommendation"],
            "recommendation": recommendation,
            "confidence": score["confidence"],
            "reason": reason,
            "qo_tender_applied": False,
            "rights_retention_applied": False,
            "renouncement_applied": False,
            "cap_hold_applied": False,
            "state_mutation_applied": False,
            "team_aggregate_cap_room_optimization_fully_modeled": False,
        })

    automatic_rows = [
        row for row in decision_rows
        if row["recommendation"] in {"retain_rights", "renounce_rights"}
    ]
    user_rows = [
        row for row in decision_rows
        if row["recommendation"] == "user_decision_required"
    ]
    manual_rows = [
        row for row in decision_rows
        if row["recommendation"] == "manual_input_required"
    ]

    recommendation_counts = Counter(
        row["recommendation"] for row in decision_rows
    )
    advisory_counts = Counter(
        row["model_recommendation"] for row in decision_rows
    )
    rights_counts = Counter(
        row["rights_classification"] for row in decision_rows
    )

    # Team-level projection for visibility only. This does not solve the full
    # team cap-space optimization problem.
    team_summary_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "candidate_count": 0,
            "model_retain_count": 0,
            "model_renounce_count": 0,
            "model_retained_cap_hold_total": 0.0,
            "model_renounced_cap_hold_total": 0.0,
            "user_decision_count": 0,
        }
    )

    for row in decision_rows:
        entry = team_summary_map[row["prior_team"]]
        entry["candidate_count"] += 1
        model = row["model_recommendation"]

        if model == "retain_rights":
            entry["model_retain_count"] += 1
            entry["model_retained_cap_hold_total"] += float(
                row["exact_cap_hold_2026_27"]
            )
        elif model == "renounce_rights":
            entry["model_renounce_count"] += 1
            entry["model_renounced_cap_hold_total"] += float(
                row["exact_cap_hold_2026_27"]
            )

        if row["recommendation"] == "user_decision_required":
            entry["user_decision_count"] += 1

    team_summary_rows = []
    for team_code, values in sorted(team_summary_map.items()):
        team_summary_rows.append({
            "team": team_code,
            **values,
            "team_aggregate_cap_room_optimization_fully_modeled": False,
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
    print("2026 RIGHTS RETENTION / RENOUNCEMENT PREVIEW V1", flush=True)
    print("=" * 128, flush=True)
    print("Exact cap holds:                    64/64", flush=True)
    print("Decision universe:                  64", flush=True)
    print("RIGHTS RETENTION APPLIED:           NO", flush=True)
    print("RENOUNCEMENTS APPLIED:              NO", flush=True)
    print("", flush=True)
    print("Running strict preview checks...", flush=True)

    check(
        "upstream_cap_hold_completion_passed",
        bool(cap_summary.get("passed"))
        and int(cap_summary.get("exact_cap_hold_count", -1)) == 64,
        "64/64 exact cap holds available.",
    )
    check(
        "upstream_qo_issuance_preview_passed",
        bool(issuance_summary.get("passed"))
        and int(issuance_summary.get("decision_row_count", -1)) == 64,
        "64-player QO issuance preview available.",
    )
    check(
        "exact_64_rights_decision_rows",
        len(decision_rows) == 64
        and len({row["player_id"] for row in decision_rows}) == 64,
        f"rows={len(decision_rows)}",
    )
    check(
        "all_rows_have_exact_positive_cap_hold",
        all(float(row["exact_cap_hold_2026_27"]) > 0 for row in decision_rows),
        "Exact cap-hold opportunity cost is present for every row.",
    )
    check(
        "all_rows_have_supported_rights_type",
        not unknown_rights
        and all(
            row["rights_classification"]
            in {"bird", "early_bird", "non_bird", "two_way_special"}
            for row in decision_rows
        ),
        f"unknown={len(unknown_rights)}",
    )
    check(
        "all_rows_have_market_reference",
        not missing_market
        and all(row["market_reference"] is not None for row in decision_rows),
        f"missing_market={len(missing_market)}",
    )
    check(
        "exact_three_chicago_user_decisions",
        len(user_rows) == 3
        and {row["player_name"] for row in user_rows}
        == EXPECTED_CHI_PLAYERS
        and all(row["prior_team"] == EXPECTED_CONTROLLED_TEAM for row in user_rows),
        repr(sorted(row["player_name"] for row in user_rows)),
    )
    check(
        "all_non_user_rows_have_automatic_recommendation",
        not manual_rows
        and len(automatic_rows) == 61,
        (
            f"automatic={len(automatic_rows)} "
            f"user={len(user_rows)} manual={len(manual_rows)}"
        ),
    )
    check(
        "qo_and_rights_decisions_are_separate",
        all(
            row["qo_user_or_cpu_recommendation"]
            in {
                "issue_qo",
                "do_not_issue_qo",
                "user_decision_required",
            }
            and row["recommendation"]
            in {
                "retain_rights",
                "renounce_rights",
                "user_decision_required",
            }
            for row in decision_rows
        ),
        "QO tendering is not treated as a rights-renouncement decision.",
    )
    check(
        "no_rights_or_qo_mutation_applied",
        all(
            not row["qo_tender_applied"]
            and not row["rights_retention_applied"]
            and not row["renouncement_applied"]
            and not row["cap_hold_applied"]
            and not row["state_mutation_applied"]
            for row in decision_rows
        ),
        "Preview only.",
    )
    check(
        "team_aggregate_cap_room_optimization_is_explicitly_pending",
        all(
            not row["team_aggregate_cap_room_optimization_fully_modeled"]
            for row in decision_rows
        ),
        "Prevents overstating the preview as a full team cap-space optimizer.",
        severity="diagnostic",
    )

    state_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_after == state_digest_before,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash_after
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_rights_retention_renouncement_preview_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_rights_retention_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "rights_retention_decision_board_64.csv",
            decision_rows,
        )
        write_csv(
            export / "rights_retention_cpu_automatic.csv",
            automatic_rows,
        )
        write_csv(
            export / "rights_retention_user_controlled.csv",
            user_rows,
        )
        write_csv(
            export / "rights_retention_manual_input_required.csv",
            manual_rows,
        )
        write_csv(
            export / "rights_retention_team_summary.csv",
            team_summary_rows,
        )
        write_csv(
            export / "rights_retention_unknown_rights.csv",
            unknown_rights,
        )
        write_csv(
            export / "rights_retention_missing_market.csv",
            missing_market,
        )
        write_csv(
            export / "rights_retention_preview_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "decision_row_count": len(decision_rows),
            "automatic_decision_count": len(automatic_rows),
            "user_decision_count": len(user_rows),
            "manual_input_count": len(manual_rows),
            "recommendation_counts": dict(
                sorted(recommendation_counts.items())
            ),
            "model_advisory_counts_including_user_rows": dict(
                sorted(advisory_counts.items())
            ),
            "rights_classification_counts": dict(
                sorted(rights_counts.items())
            ),
            "user_decision_players": [
                {
                    "player_name": row["player_name"],
                    "exact_cap_hold_2026_27": row[
                        "exact_cap_hold_2026_27"
                    ],
                    "market_reference": row["market_reference"],
                    "market_to_cap_hold_ratio": row[
                        "market_to_cap_hold_ratio"
                    ],
                    "qo_model_advisory": row[
                        "qo_model_recommendation"
                    ],
                    "rights_model_advisory": row[
                        "model_recommendation"
                    ],
                    "confidence": row["confidence"],
                }
                for row in user_rows
            ],
            "rights_retention_applied": 0,
            "renouncements_applied": 0,
            "qo_tenders_applied": 0,
            "cap_holds_applied": 0,
            "team_aggregate_cap_room_optimization_fully_modeled": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": not failed,
            "failed_checks": failed,
            "next_slice": (
                "Build team-level aggregate cap-room pressure / renouncement "
                "optimization using current guaranteed salary, exact retained "
                "cap holds, roster charges, and exception strategy. Only after "
                "that should CPU rights decisions and QO decisions be clone-applied."
            ),
        }

        (export / "rights_retention_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 RIGHTS RETENTION / RENOUNCEMENT PREVIEW V1
================================================

This preview keeps two offseason decisions separate:

1. Qualifying Offer decision
   - determines whether the player can be a Restricted Free Agent
   - carries one-year QO acceptance risk

2. Rights-retention / renouncement decision
   - determines whether the Prior Team continues carrying the player's
     exact Free Agent Amount / cap hold and associated free-agent rights

A team can decline to tender a QO and still retain applicable Bird/Early
Bird/Non-Bird rights until those rights are renounced or otherwise extinguished.

Inputs:
- exact 64/64 QO cap holds
- 64-player QO issuance preview
- canonical player market references
- roster-count context

Decision score:
- market value / exact cap hold
- strength of retained rights
- QO-model alignment
- roster context
- cap-hold burden as a percentage of the Salary Cap

User-controlled Chicago decisions remain user_decision_required.

LIMIT:
This is not yet a complete team-level cap-space optimizer. Multiple retained
cap holds interact jointly with guaranteed team salary, incomplete roster
charges, exceptions, and renouncements. A team-level aggregate optimizer is
the next slice before any durable or clone application.

No QO tender.
No rights retention applied.
No renouncement.
No cap hold applied.
No checkpoint write.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "Rights Retention / Renouncement Preview V1 failed: "
            + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 RIGHTS RETENTION / RENOUNCEMENT PREVIEW V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Exact cap holds / decisions:       64/64", flush=True)
    print(f"Automatic CPU decisions:           {len(automatic_rows)}", flush=True)
    print(f"Chicago user decisions:             {len(user_rows)}", flush=True)
    print(f"Manual inputs required:             {len(manual_rows)}", flush=True)
    print("Recommendation counts:", flush=True)
    for key, value in sorted(recommendation_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("Model advisories incl. Chicago:", flush=True)
    for key, value in sorted(advisory_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("Rights retention applied:           0", flush=True)
    print("Renouncements applied:              0", flush=True)
    print("QO tenders applied:                 0", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
