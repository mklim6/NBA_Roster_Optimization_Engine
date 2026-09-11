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

VERSION = "fa-chicago-recommended-final-market-rfa-input-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_POPULATION = 587
EXPECTED_AUTOMATIC_MARKET = 225
EXPECTED_FINAL_MARKET = 226

MILLER_ID = "1631159"
GUEYE_ID = "1631338"

RECOMMENDED_USER_CHOICES = {
    MILLER_ID: {
        "player_name": "Leonard Miller",
        "choice": "exercise",
        "expected_team": "CHI",
    },
    GUEYE_ID: {
        "player_name": "Mouhamadou Gueye",
        "choice": "decline",
        "expected_team": "CHI",
    },
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


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


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
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
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

    clone_zip = find_latest(
        root,
        "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip",
    )
    decision_zip = find_latest(
        root,
        "fa_unified_offseason_decision_preview_v1_1_2026-27_*.zip",
    )

    # Older corrected RFA/QO audit is optional for coverage carry-forward.
    old_rfa_candidates = [
        p for p in root.rglob(
            "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip"
        )
        if p.is_file()
    ]
    old_rfa_zip = (
        max(old_rfa_candidates, key=lambda p: p.stat().st_mtime)
        if old_rfa_candidates
        else None
    )

    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = read_json_member(
            archive,
            "clone_application_summary.json",
        )
        owner_ledger = read_csv_member(
            archive,
            "clone_owner_ledger_587.csv",
        )
        pending_user = read_csv_member(
            archive,
            "user_decisions_pending_2.csv",
        )

    with zipfile.ZipFile(decision_zip) as archive:
        decision_summary = read_json_member(
            archive,
            "decision_preview_summary.json",
        )
        decision_rows = read_csv_member(
            archive,
            "unified_decision_preview_111.csv",
        )

    old_rfa_rows = []
    if old_rfa_zip is not None:
        with zipfile.ZipFile(old_rfa_zip) as archive:
            try:
                old_rfa_rows = read_csv_member(
                    archive,
                    "corrected_rfa_qo_universe_all.csv",
                )
            except Exception:
                old_rfa_rows = []

    old_rfa_by_id = {
        pid(row.get("player_id")): row
        for row in old_rfa_rows
    }

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before Chicago scenario preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    if not bool(clone_summary.get("passed")):
        raise RuntimeError("Clone-only automatic application preview did not pass.")
    if not bool(decision_summary.get("passed")):
        raise RuntimeError("Unified V1.1 decision preview did not pass.")

    if len(owner_ledger) != EXPECTED_POPULATION:
        raise RuntimeError(
            f"Expected {EXPECTED_POPULATION} owner-ledger rows, got {len(owner_ledger)}."
        )
    if int(clone_summary.get("market_after_automatic_count", -1)) != EXPECTED_AUTOMATIC_MARKET:
        raise RuntimeError(
            "Upstream automatic market count is not 225."
        )

    pending_by_id = {
        pid(row.get("player_id")): row for row in pending_user
    }

    if set(pending_by_id) != set(RECOMMENDED_USER_CHOICES):
        raise RuntimeError(
            "Pending Chicago decision IDs do not match Leonard Miller and "
            "Mouhamadou Gueye: " + repr(sorted(pending_by_id))
        )

    decision_by_id = {
        pid(row.get("player_id")): row for row in decision_rows
    }

    # Clone the already-automatic ownership ledger.
    owner_after = {
        pid(row.get("player_id")): clean(row.get("owner_after_automatic"))
        for row in owner_ledger
    }
    player_name_by_id = {
        pid(row.get("player_id")): clean(row.get("player_name"))
        for row in owner_ledger
    }

    scenario_rows = []
    for player_id, spec in RECOMMENDED_USER_CHOICES.items():
        pending = pending_by_id[player_id]
        player_name = clean(pending.get("player_name"))
        if player_name != spec["player_name"]:
            raise RuntimeError(
                f"Chicago scenario identity mismatch for {player_id}: "
                f"{player_name!r} != {spec['player_name']!r}"
            )
        if team(pending.get("team_abbreviation")) != spec["expected_team"]:
            raise RuntimeError(
                f"Chicago scenario team mismatch for {player_name}."
            )
        if clean(pending.get("decision_category")) != "team_option_decision":
            raise RuntimeError(
                f"Chicago scenario category mismatch for {player_name}."
            )
        if boolish(pending.get("decision_applied")):
            raise RuntimeError(
                f"Upstream clone already applied user decision for {player_name}."
            )

        before = owner_after[player_id]
        if before != "CHI":
            raise RuntimeError(
                f"Expected {player_name} to remain CHI before user scenario, "
                f"got {before!r}."
            )

        choice = spec["choice"]
        after = "CHI" if choice == "exercise" else "FA"
        owner_after[player_id] = after

        decision = decision_by_id.get(player_id, {})
        scenario_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": "CHI",
            "decision_category": "team_option_decision",
            "recommended_user_choice": choice,
            "owner_before": before,
            "owner_after_recommended_scenario": after,
            "entered_market": after == "FA",
            "option_salary_2026_27": pending.get("option_salary_2026_27", ""),
            "market_reference": pending.get("market_reference", ""),
            "market_to_option_ratio": pending.get("market_to_option_ratio", ""),
            "decision_model_reason": clean(decision.get("reason")),
            "scenario_is_recommendation_only": True,
            "user_choice_committed": False,
            "durable_state_mutated": False,
        })

    final_market_ids = {
        player_id for player_id, owner in owner_after.items()
        if owner == "FA"
    }

    team_counts = Counter(
        owner for owner in owner_after.values()
        if owner in TEAM_CODES
    )

    team_rows = [
        {
            "team_abbreviation": code,
            "recommended_scenario_roster_count": team_counts.get(code, 0),
            "exceeds_offseason_21": team_counts.get(code, 0) > 21,
        }
        for code in sorted(TEAM_CODES)
    ]
    over_21 = [
        row["team_abbreviation"]
        for row in team_rows
        if row["exceeds_offseason_21"]
    ]

    # Build the exact final-market input ledger for the next RFA/QO rebuild.
    rfa_input = []
    carry_forward_count = 0

    for player_id in sorted(
        final_market_ids,
        key=lambda value: int(value) if value.isdigit() else value,
    ):
        prior = old_rfa_by_id.get(player_id, {})
        disposition = clean(
            prior.get("corrected_rfa_qo_disposition")
        )
        path = clean(prior.get("corrected_rfa_qo_path"))

        has_prior = bool(disposition)
        if has_prior:
            carry_forward_count += 1

        rfa_input.append({
            "player_id": player_id,
            "player_name": player_name_by_id.get(player_id, ""),
            "final_market_owner": "FA",
            "market_entry_source": (
                "recommended_chicago_decline"
                if player_id == GUEYE_ID
                else "automatic_or_initial_market"
            ),
            "prior_corrected_rfa_qo_evidence_available": has_prior,
            "prior_corrected_rfa_qo_disposition": disposition,
            "prior_corrected_rfa_qo_path": path,
            "prior_qualifying_offer_issued": clean(
                prior.get("qualifying_offer_issued")
            ),
            "needs_fresh_2026_rfa_qo_rebuild": not has_prior,
            "scenario_is_recommendation_only": True,
        })

    fresh_count = sum(
        bool(row["needs_fresh_2026_rfa_qo_rebuild"])
        for row in rfa_input
    )

    # Four possible Chicago scenarios for reference.
    scenario_matrix = [
        {
            "leonard_miller": "exercise",
            "mouhamadou_gueye": "exercise",
            "final_market_count": 225,
            "chi_roster_count": team_counts.get("CHI", 0) + 1,
        },
        {
            "leonard_miller": "exercise",
            "mouhamadou_gueye": "decline",
            "final_market_count": 226,
            "chi_roster_count": team_counts.get("CHI", 0),
            "recommended": True,
        },
        {
            "leonard_miller": "decline",
            "mouhamadou_gueye": "exercise",
            "final_market_count": 226,
            "chi_roster_count": team_counts.get("CHI", 0),
        },
        {
            "leonard_miller": "decline",
            "mouhamadou_gueye": "decline",
            "final_market_count": 227,
            "chi_roster_count": team_counts.get("CHI", 0) - 1,
        },
    ]

    checks = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 CHICAGO RECOMMENDED FINAL MARKET + RFA INPUT V1", flush=True)
    print("=" * 128, flush=True)
    print("RECOMMENDED SCENARIO ONLY. USER CHOICES ARE NOT COMMITTED.", flush=True)
    print("  Leonard Miller:     EXERCISE", flush=True)
    print("  Mouhamadou Gueye:   DECLINE", flush=True)
    print(f"Final market:         {len(final_market_ids)}", flush=True)
    print(f"Chicago roster count: {team_counts.get('CHI', 0)}", flush=True)
    print("", flush=True)
    print("Running strict scenario checks...", flush=True)

    check(
        "upstream_clone_preview_passed",
        bool(clone_summary.get("passed")),
        "109 automatic decisions already validated on clone.",
    )
    check(
        "exact_two_chicago_user_decisions_detected",
        set(pending_by_id) == {MILLER_ID, GUEYE_ID},
        repr(sorted(pending_by_id)),
    )
    check(
        "leonard_miller_recommended_exercise",
        owner_after[MILLER_ID] == "CHI"
        and next(
            row for row in scenario_rows if row["player_id"] == MILLER_ID
        )["recommended_user_choice"] == "exercise",
        "Leonard Miller stays on CHI in recommended scenario.",
    )
    check(
        "mouhamadou_gueye_recommended_decline",
        owner_after[GUEYE_ID] == "FA"
        and next(
            row for row in scenario_rows if row["player_id"] == GUEYE_ID
        )["recommended_user_choice"] == "decline",
        "Mouhamadou Gueye enters market in recommended scenario.",
    )
    check(
        "recommended_final_market_is_226",
        len(final_market_ids) == EXPECTED_FINAL_MARKET,
        f"market={len(final_market_ids)}",
    )
    check(
        "recommended_chicago_roster_count_is_10",
        team_counts.get("CHI", 0) == 10,
        f"CHI={team_counts.get('CHI', 0)}",
    )
    check(
        "no_team_exceeds_offseason_21",
        not over_21,
        "over_21=" + ("|".join(over_21) if over_21 else "<none>"),
    )
    check(
        "rfa_rebuild_input_has_exact_226_rows",
        len(rfa_input) == EXPECTED_FINAL_MARKET
        and len({row["player_id"] for row in rfa_input}) == EXPECTED_FINAL_MARKET,
        f"rows={len(rfa_input)}",
    )
    check(
        "all_rfa_input_rows_are_final_market_players",
        all(row["final_market_owner"] == "FA" for row in rfa_input),
        "All 226 inputs are final-market players.",
    )
    check(
        "user_choices_not_committed",
        all(not row["user_choice_committed"] for row in scenario_rows),
        "Scenario only.",
    )
    check(
        "durable_state_not_mutated",
        all(not row["durable_state_mutated"] for row in scenario_rows),
        "Scenario applied only to local ownership copy.",
    )

    checkpoint_hash_after = sha256_file(checkpoint_path)
    state_digest_after = object_digest(checkpoint.simulation_state)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_before == state_digest_after,
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
        if row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Chicago Recommended Final Market + RFA Input V1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_chicago_recommended_final_market_rfa_input_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_chi_scenario_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "recommended_chicago_user_choices.csv",
            scenario_rows,
        )
        write_csv(
            export / "chicago_scenario_matrix.csv",
            scenario_matrix,
        )
        write_csv(
            export / "recommended_final_market_226.csv",
            rfa_input,
        )
        write_csv(
            export / "rfa_qo_rebuild_input_226.csv",
            rfa_input,
        )
        write_csv(
            export / "team_counts_recommended_scenario.csv",
            team_rows,
        )
        write_csv(
            export / "recommended_scenario_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "recommended_choices": {
                "Leonard Miller": "exercise",
                "Mouhamadou Gueye": "decline",
            },
            "user_choices_committed": False,
            "automatic_market_count": EXPECTED_AUTOMATIC_MARKET,
            "recommended_final_market_count": len(final_market_ids),
            "recommended_chicago_roster_count": team_counts.get("CHI", 0),
            "rfa_qo_prior_evidence_carry_forward_count": carry_forward_count,
            "rfa_qo_fresh_rebuild_required_count": fresh_count,
            "rfa_qo_rebuild_input_count": len(rfa_input),
            "teams_over_offseason_21": over_21,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Run the 226-player RFA/QO evidence rebuild. Use prior corrected "
                "RFA evidence only as carry-forward provenance, validate all market "
                "players against the official 2026 free-agent/RFA structure, then "
                "compute qualifying-offer readiness. Do not issue QOs or mutate state."
            ),
        }

        (export / "recommended_scenario_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 CHICAGO RECOMMENDED FINAL MARKET + RFA INPUT V1
======================================================

This is a SCENARIO preview, not a committed user decision.

Recommended Chicago choices:
- Leonard Miller: EXERCISE Team Option
- Mouhamadou Gueye: DECLINE Team Option

Reason:
Miller's option is materially below the established market reference.
Gueye's option is materially above the established market reference.

Result:
- 225-player market after automatic decisions
- Gueye adds one player
- 226-player recommended final simulated market
- Chicago has 10 players on the reconstructed offseason roster
- no team exceeds the offseason 21-player limit

The package also creates the exact 226-row input ledger for the next RFA/QO
rebuild and marks which rows have old corrected-RFA evidence available.

No user choice is committed.
No durable state mutation.
No checkpoint write.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 CHICAGO RECOMMENDED FINAL MARKET + RFA INPUT V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Recommended CHI: Miller exercise / Gueye decline", flush=True)
    print("User choices committed:              NO", flush=True)
    print("Final recommended market:           226", flush=True)
    print("Chicago reconstructed roster:        10", flush=True)
    print(f"Prior RFA evidence carry-forward:    {carry_forward_count}", flush=True)
    print(f"Fresh RFA evidence rebuild needed:   {fresh_count}", flush=True)
    print("Teams over offseason 21:           NONE", flush=True)
    print("State mutation:            NOT PERFORMED", flush=True)
    print("Checkpoint write:          NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
