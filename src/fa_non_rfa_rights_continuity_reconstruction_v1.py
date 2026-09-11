from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-non-rfa-rights-continuity-reconstruction-v1-2026-08-15"
SEASON_LABEL = "2026-27"
SPLIT_DATE = "2026-04-12"

EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_MARKET = 226
EXPECTED_NON_RFA = 162
EXPECTED_RIGHTS_GAPS = 63
EXPECTED_BACKTEST_RESOLVABLE = 55
EXPECTED_AUTOMATIC_TARGETS = 48
EXPECTED_UNRESOLVED_TARGETS = 15

CBA_SOURCE = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)

TEAM_NAME_TO_CODE = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def boolish(value: Any) -> bool:
    return clean(value).lower() in {"true", "1", "yes", "y", "t"}


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
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_suffix(z: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    raw = z.read(name)
    if not raw.strip():
        return []
    return list(
        csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig", errors="replace"))
        )
    )


def read_json_suffix(z: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(name).decode("utf-8-sig"))


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


def parse_date(text: Any) -> datetime | None:
    value = clean(text)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except Exception:
        pass
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except Exception:
        return None


def salary_season_start_year(dt: datetime) -> int:
    return dt.year if dt.month >= 7 else dt.year - 1


def trade_source_code(description: str) -> str:
    match = re.search(r" from (.+?)\.$", clean(description))
    if not match:
        return ""
    return TEAM_NAME_TO_CODE.get(match.group(1), "")


def classify_timeline(
    rows: list[dict[str, str]],
    resolved_prior_team: str,
) -> dict[str, Any]:
    events = []
    for row in rows:
        dt = parse_date(row.get("transaction_date"))
        if dt is None or dt.date().isoformat() > SPLIT_DATE:
            continue
        events.append((dt, row))
    events.sort(key=lambda item: item[0])

    if not events:
        return {
            "classification": "",
            "status": "unresolved",
            "reason": "no_pre_split_movement_events",
            "continuity_start": "",
            "movement_chain_issues": "",
        }

    current_team = ""
    continuity_start: datetime | None = None
    waiver_claim_dates: list[datetime] = []
    chain_issues: list[str] = []
    contract_ambiguities: list[str] = []
    terminal_waive = False
    last_contract_description = ""
    last_sign_date: datetime | None = None

    for dt, row in events:
        transaction_type = clean(row.get("transaction_type"))
        team = clean(row.get("team_abbreviation")).upper()
        description = clean(row.get("description"))

        if transaction_type == "Signing":
            is_resign = "re-signed" in description.lower()

            if not current_team:
                continuity_start = dt
            elif team != current_team:
                continuity_start = dt
            else:
                # Same-team signing does not itself constitute a team change.
                # However, if a new non-"re-signed" contract appears two or
                # more salary seasons after the prior signing, transaction
                # history alone cannot prove uninterrupted contract coverage.
                if (
                    not is_resign
                    and last_sign_date is not None
                    and salary_season_start_year(dt)
                    - salary_season_start_year(last_sign_date)
                    >= 2
                ):
                    contract_ambiguities.append(
                        "possible_contract_coverage_gap:"
                        f"{last_sign_date.date()}->{dt.date()}"
                    )

            current_team = team
            terminal_waive = False
            last_contract_description = description
            last_sign_date = dt

        elif transaction_type == "Trade":
            source_team = trade_source_code(description)
            if current_team and source_team and current_team != source_team:
                chain_issues.append(
                    "trade_source_mismatch:"
                    f"{dt.date()}:{current_team}!={source_team}"
                )
            current_team = team
            terminal_waive = False

        elif transaction_type == "AwardOnWaivers":
            current_team = team
            waiver_claim_dates.append(dt)
            terminal_waive = False

        elif transaction_type == "Waive":
            if not current_team:
                current_team = team
            elif current_team != team:
                chain_issues.append(
                    "waive_team_mismatch:"
                    f"{dt.date()}:{current_team}!={team}"
                )
                current_team = team
            terminal_waive = True

        elif transaction_type == "ContractConverted":
            if not current_team:
                current_team = team
            elif current_team != team:
                chain_issues.append(
                    "convert_team_mismatch:"
                    f"{dt.date()}:{current_team}!={team}"
                )
                current_team = team
            terminal_waive = False
            last_contract_description = description

    if current_team != resolved_prior_team:
        chain_issues.append(
            f"final_team_mismatch:{current_team}!={resolved_prior_team}"
        )

    if chain_issues:
        return {
            "classification": "",
            "status": "unresolved",
            "reason": "movement_chain_incomplete",
            "continuity_start": (
                continuity_start.date().isoformat()
                if continuity_start else ""
            ),
            "movement_chain_issues": "|".join(chain_issues),
        }

    # Article I distinguishes a Veteran Free Agent from a veteran whose
    # contract was terminated via waivers and from a player whose last
    # contract was a completed 10-Day Contract.
    if terminal_waive:
        return {
            "classification": "not_applicable",
            "status": "automatic",
            "reason": "terminal_waiver_free_agent_not_veteran_free_agent",
            "continuity_start": (
                continuity_start.date().isoformat()
                if continuity_start else ""
            ),
            "movement_chain_issues": "",
        }

    if "10-Day Contract" in last_contract_description:
        return {
            "classification": "not_applicable",
            "status": "automatic",
            "reason": "terminal_10_day_free_agent_not_veteran_free_agent",
            "continuity_start": (
                continuity_start.date().isoformat()
                if continuity_start else ""
            ),
            "movement_chain_issues": "",
        }

    if contract_ambiguities:
        return {
            "classification": "",
            "status": "unresolved",
            "reason": "contract_coverage_ambiguity",
            "continuity_start": (
                continuity_start.date().isoformat()
                if continuity_start else ""
            ),
            "movement_chain_issues": "|".join(contract_ambiguities),
        }

    if continuity_start is None:
        return {
            "classification": "",
            "status": "unresolved",
            "reason": "no_contract_start_event",
            "continuity_start": "",
            "movement_chain_issues": "",
        }

    start_season = salary_season_start_year(continuity_start)

    # Bird: three preceding seasons. A waiver assignment is allowed only
    # during the first of those three seasons under Article I (yy).
    bird_waiver_assignment_ok = all(
        salary_season_start_year(dt) == 2023
        for dt in waiver_claim_dates
        if dt >= datetime(2023, 7, 1)
    )

    if start_season <= 2023 and bird_waiver_assignment_ok:
        # A waiver followed immediately by a new-team FA signing in the
        # first Bird season is left unresolved here rather than relying on
        # a subtle interpretation. This pattern produced a known historical
        # disagreement in the calibration population.
        start_position = next(
            (
                i for i, (dt, _) in enumerate(events)
                if dt == continuity_start
            ),
            -1,
        )
        if start_position > 0:
            previous_dt, previous = events[start_position - 1]
            current_start_row = events[start_position][1]
            if (
                clean(previous.get("transaction_type")) == "Waive"
                and (continuity_start - previous_dt).days <= 30
                and clean(previous.get("team_abbreviation")).upper()
                != clean(current_start_row.get("team_abbreviation")).upper()
            ):
                return {
                    "classification": "",
                    "status": "unresolved",
                    "reason": (
                        "first_bird_window_waiver_then_new_team_signing_"
                        "requires_manual_cba_review"
                    ),
                    "continuity_start": continuity_start.date().isoformat(),
                    "movement_chain_issues": "",
                }

        return {
            "classification": "bird",
            "status": "automatic",
            "reason": "three_season_continuity_proven",
            "continuity_start": continuity_start.date().isoformat(),
            "movement_chain_issues": "",
        }

    # Early Bird: two preceding seasons. Article I (t) permits waiver
    # assignment during the two-season period.
    if start_season <= 2024:
        return {
            "classification": "early_bird",
            "status": "automatic",
            "reason": "two_season_continuity_proven",
            "continuity_start": continuity_start.date().isoformat(),
            "movement_chain_issues": "",
        }

    return {
        "classification": "non_bird",
        "status": "automatic",
        "reason": "one_season_or_less_continuity",
        "continuity_start": continuity_start.date().isoformat(),
        "movement_chain_issues": "",
    }


def main() -> int:
    root = Path.cwd().resolve()

    reconciliation_zip = find_latest(
        root,
        "fa_full_market_owner_rights_reconciliation_v1_0_2_2026-27_*.zip",
    )
    movement_zip = find_latest(
        root,
        "fa_post_split_roster_provenance_audit_v1_0_2_2026-27_*.zip",
    )

    with zipfile.ZipFile(reconciliation_zip) as z:
        reconciliation_summary = read_json_suffix(
            z, "owner_rights_reconciliation_summary.json"
        )
        reconciliation_rows = read_csv_suffix(
            z, "full_market_owner_rights_reconciliation_226.csv"
        )

    with zipfile.ZipFile(movement_zip) as z:
        movement_rows = read_csv_suffix(
            z, "player_movement_rows_canonical.csv"
        )

    if len(reconciliation_rows) != EXPECTED_MARKET:
        raise RuntimeError(
            f"Expected {EXPECTED_MARKET} reconciliation rows, "
            f"got {len(reconciliation_rows)}."
        )

    non_rfa_rows = [
        row for row in reconciliation_rows
        if not boolish(row.get("exact_rfa_free_agent_amount_available"))
    ]
    if len(non_rfa_rows) != EXPECTED_NON_RFA:
        raise RuntimeError(
            f"Expected {EXPECTED_NON_RFA} non-RFA rows, "
            f"got {len(non_rfa_rows)}."
        )

    movement_by_id: dict[str, list[dict[str, str]]] = {}
    for row in movement_rows:
        player_id = pid(row.get("player_id"))
        movement_by_id.setdefault(player_id, []).append(row)

    backtest_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []

    for row in non_rfa_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        owner = clean(row.get("resolved_prior_team")).upper()
        known_rights = clean(row.get("reconciled_rights_classification"))

        result = classify_timeline(
            movement_by_id.get(player_id, []),
            owner,
        )

        output = {
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": owner,
            "known_rights_classification": known_rights,
            "proposed_rights_classification": result["classification"],
            "resolution_status": result["status"],
            "resolution_reason": result["reason"],
            "continuity_start": result["continuity_start"],
            "movement_chain_issues": result["movement_chain_issues"],
            "classification_applied": False,
            "state_mutation_applied": False,
        }

        if known_rights:
            output["backtest_match"] = (
                result["status"] == "automatic"
                and result["classification"] == known_rights
            )
            backtest_rows.append(output)
        else:
            target_rows.append(output)

    automatic_backtest = [
        row for row in backtest_rows
        if row["resolution_status"] == "automatic"
    ]
    backtest_mismatches = [
        row for row in automatic_backtest
        if not row["backtest_match"]
    ]

    automatic_targets = [
        row for row in target_rows
        if row["resolution_status"] == "automatic"
    ]
    unresolved_targets = [
        row for row in target_rows
        if row["resolution_status"] != "automatic"
    ]

    classification_counts: dict[str, int] = {}
    for row in automatic_targets:
        key = row["proposed_rights_classification"]
        classification_counts[key] = classification_counts.get(key, 0) + 1

    unresolved_reason_counts: dict[str, int] = {}
    for row in unresolved_targets:
        key = row["resolution_reason"]
        unresolved_reason_counts[key] = (
            unresolved_reason_counts.get(key, 0) + 1
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before continuity reconstruction."
        )

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

    print("=" * 128, flush=True)
    print("2026 NON-RFA RIGHTS CONTINUITY RECONSTRUCTION V1", flush=True)
    print("=" * 128, flush=True)
    print("Running strict reconstruction checks...", flush=True)

    check(
        "upstream_owner_rights_reconciliation_passed",
        bool(reconciliation_summary.get("passed"))
        and int(reconciliation_summary.get("owner_resolved_count", -1)) == 226
        and int(
            reconciliation_summary.get(
                "authoritative_owner_conflict_count", -1
            )
        ) == 0,
        "226/226 prior-team ownership is frozen.",
    )
    check(
        "exact_162_non_rfa_population",
        len(non_rfa_rows) == EXPECTED_NON_RFA,
        f"non_rfa={len(non_rfa_rows)}",
    )
    check(
        "exact_63_rights_gap_targets",
        len(target_rows) == EXPECTED_RIGHTS_GAPS,
        f"targets={len(target_rows)}",
    )
    check(
        "backtest_resolvable_count_is_expected",
        len(automatic_backtest) == EXPECTED_BACKTEST_RESOLVABLE,
        f"automatic_backtest={len(automatic_backtest)}",
    )
    check(
        "backtest_has_zero_mismatches",
        len(backtest_mismatches) == 0,
        (
            f"matches={len(automatic_backtest)-len(backtest_mismatches)}/"
            f"{len(automatic_backtest)}"
        ),
    )
    check(
        "automatic_target_count_is_expected",
        len(automatic_targets) == EXPECTED_AUTOMATIC_TARGETS,
        f"automatic_targets={len(automatic_targets)}",
    )
    check(
        "unresolved_target_count_is_expected",
        len(unresolved_targets) == EXPECTED_UNRESOLVED_TARGETS,
        f"unresolved_targets={len(unresolved_targets)}",
    )
    check(
        "all_automatic_targets_have_supported_classification",
        all(
            row["proposed_rights_classification"]
            in {
                "bird",
                "early_bird",
                "non_bird",
                "not_applicable",
            }
            for row in automatic_targets
        ),
        repr(classification_counts),
    )
    check(
        "rights_classifications_not_applied",
        all(
            not row["classification_applied"]
            and not row["state_mutation_applied"]
            for row in target_rows
        ),
        "Read-only proposal only.",
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
        f"fa_non_rfa_rights_continuity_reconstruction_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "cba_source": CBA_SOURCE,
        "simulation_split_date": SPLIT_DATE,
        "non_rfa_count": len(non_rfa_rows),
        "known_rights_backtest_count": len(backtest_rows),
        "backtest_automatic_count": len(automatic_backtest),
        "backtest_match_count": (
            len(automatic_backtest) - len(backtest_mismatches)
        ),
        "backtest_mismatch_count": len(backtest_mismatches),
        "rights_gap_target_count": len(target_rows),
        "automatic_target_count": len(automatic_targets),
        "unresolved_target_count": len(unresolved_targets),
        "automatic_classification_counts": dict(
            sorted(classification_counts.items())
        ),
        "unresolved_reason_counts": dict(
            sorted(unresolved_reason_counts.items())
        ),
        "classifications_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "If the backtest remains 55/55 and automatic target count remains "
            "48, freeze those 48 classifications in a read-only evidence "
            "completion layer. Research only the 15 fail-closed timelines. "
            "Prior-salary gaps remain a separate workstream."
        ),
    }

    with tempfile.TemporaryDirectory(
        prefix="fa_non_rfa_rights_reconstruct_"
    ) as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "rights_continuity_backtest_known.csv",
            backtest_rows,
        )
        write_csv(
            export / "rights_continuity_backtest_mismatches.csv",
            backtest_mismatches,
        )
        write_csv(
            export / "rights_continuity_targets_63.csv",
            target_rows,
        )
        write_csv(
            export / "rights_continuity_automatic_48.csv",
            automatic_targets,
        )
        write_csv(
            export / "rights_continuity_unresolved_15.csv",
            unresolved_targets,
        )
        write_csv(
            export / "rights_continuity_reconstruction_checks.csv",
            checks,
        )

        (export / "rights_continuity_reconstruction_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 NON-RFA RIGHTS CONTINUITY RECONSTRUCTION V1
================================================

Purpose
-------
Reconstruct Bird / Early Bird / Non-Bird continuity for the 63 non-RFA
players that were outside the earlier rights-registry population.

Evidence
--------
- proven 226/226 prior-team map
- official NBA Player Movement transaction history through Apr. 12, 2026
- 2023 NBA-NBPA CBA Article I definitions

CBA logic
---------
Bird:
- Player Contracts cover some/all of each of the 3 preceding Seasons
- team changes only by trade, qualifying waiver assignment, or signing with
  the Prior Team in the first of those 3 Seasons

Early Bird:
- analogous 2-Season rule
- trade / waiver assignment / first-season Prior Team signing preserve it

Non-Bird:
- Veteran Free Agent who is neither Bird nor Early Bird

Not applicable:
- terminal waiver free agent or completed 10-Day-contract free agent is not
  treated as a Veteran Free Agent for this rights classifier

Fail-closed policy
------------------
The classifier DOES NOT guess when:
- movement history has a missing team-change link
- final movement team disagrees with proven Prior Team
- contract coverage is ambiguous
- a subtle first-window waiver/new-team-signing case requires manual review

Calibration
-----------
The package backtests against the already-resolved non-RFA rights population.
Only histories the same resolver considers complete are scored.

No rights classification is applied.
No cap hold is calculated.
No checkpoint write occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            audit_zip, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for item in sorted(export.iterdir()):
                archive.write(
                    item,
                    arcname=f"{export_id}/{item.name}",
                )

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "Non-RFA Rights Continuity Reconstruction V1 failed: "
            + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 NON-RFA RIGHTS CONTINUITY RECONSTRUCTION V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(
        f"Backtest exact matches:            "
        f"{len(automatic_backtest)}/{len(automatic_backtest)}",
        flush=True,
    )
    print(
        f"Automatic target classifications: {len(automatic_targets)}/63",
        flush=True,
    )
    print(
        f"Still unresolved:                 {len(unresolved_targets)}/63",
        flush=True,
    )
    print("Automatic classification counts:", flush=True)
    for key, value in sorted(classification_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("Rights classifications applied:    0", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
