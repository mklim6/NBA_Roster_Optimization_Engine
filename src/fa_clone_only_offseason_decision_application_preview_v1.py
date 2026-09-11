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

VERSION = "fa-clone-only-offseason-decision-application-preview-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_POPULATION = 587
EXPECTED_LIFECYCLE = 311
EXPECTED_INITIAL_MARKET = 194
EXPECTED_AUTOMATIC_DECISIONS = 109
EXPECTED_USER_DECISIONS = 2
EXPECTED_AUTOMATIC_ADDITIONS_TO_MARKET = 31
EXPECTED_MARKET_AFTER_AUTOMATIC = 225

TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

AUTOMATIC_KEEP = {"exercise", "retain"}
AUTOMATIC_MARKET = {"decline", "waive"}
USER_PENDING = "user_decision_required"


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


def numeric(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


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

    decision_zip = find_latest(
        root,
        "fa_unified_offseason_decision_preview_v1_1_2026-27_*.zip",
    )
    lifecycle_zip = find_latest(
        root,
        "fa_final_contract_source_manual_resolution_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    v411_zip = find_latest(
        root,
        "fa_official_option_and_zero_game_population_v4_1_1_preview_2026-27_*.zip",
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

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "final_manual_resolution_summary.json",
        )
        lifecycle_rows = read_csv_member(
            archive,
            "unified_lifecycle_final_311.csv",
        )

    with zipfile.ZipFile(branch_zip) as archive:
        branch_rows = read_csv_member(
            archive,
            "branch_reconstruction_all_players.csv",
        )

    with zipfile.ZipFile(v411_zip) as archive:
        supplement_rows = read_csv_member(
            archive,
            "zero_game_population_supplement_5.csv",
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before clone-only application preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    if not bool(decision_summary.get("passed")):
        raise RuntimeError("V1.1 decision preview did not pass upstream.")
    if not bool(lifecycle_summary.get("passed")):
        raise RuntimeError("Final lifecycle did not pass upstream.")

    if len(decision_rows) != 111:
        raise RuntimeError(f"Expected 111 decisions, got {len(decision_rows)}.")
    if len(lifecycle_rows) != EXPECTED_LIFECYCLE:
        raise RuntimeError(
            f"Expected {EXPECTED_LIFECYCLE} lifecycle rows, got {len(lifecycle_rows)}."
        )

    # Build the extended 587-player branch ownership ledger without mutating state.
    owner_before: dict[str, str] = {
        pid(row.get("player_id")): team(row.get("reconstructed_branch_owner"))
        for row in branch_rows
    }

    for row in supplement_rows:
        player_id = pid(row.get("player_id"))
        owner = team(row.get("reconstructed_branch_owner"))
        lifecycle_category = clean(row.get("lifecycle_category"))
        if lifecycle_category == "immediate_market":
            owner_before[player_id] = "FA"
        elif owner in TEAM_CODES:
            owner_before[player_id] = owner
        else:
            owner_before[player_id] = "FA"

    lifecycle_by_id = {
        pid(row.get("player_id")): row
        for row in lifecycle_rows
    }

    # Narrow carry-forward repair already proven in V1.1.
    owner_before["1642354"] = "DEN"

    # Apply final lifecycle opening state before any option/guarantee decisions.
    for player_id, row in lifecycle_by_id.items():
        category = clean(row.get("unified_lifecycle_category"))
        owner = team(row.get("reconstructed_branch_owner"))

        if player_id == "1642354":
            owner = "DEN"

        if category == "immediate_market":
            owner_before[player_id] = "FA"
        elif category in {
            "team_option_decision",
            "player_option_decision",
            "non_guaranteed_or_partial_decision",
            "guaranteed_under_contract",
        }:
            if owner not in TEAM_CODES:
                raise RuntimeError(
                    f"Lifecycle-attached player lacks team before application: "
                    f"{clean(row.get('player_name'))} ({player_id}) owner={owner!r}"
                )
            owner_before[player_id] = owner
        else:
            raise RuntimeError(
                f"Unexpected lifecycle category after final manual resolution: {category}"
            )

    population_ids = set(owner_before)
    if len(population_ids) != EXPECTED_POPULATION:
        raise RuntimeError(
            f"Expected extended population {EXPECTED_POPULATION}, got {len(population_ids)}."
        )

    initial_market_ids = {
        player_id for player_id, owner in owner_before.items()
        if owner == "FA"
    }

    # Clone only.
    owner_after = dict(owner_before)
    applied_rows = []
    user_pending_rows = []
    decision_by_id = {}

    for row in decision_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        team_code = team(row.get("team_abbreviation"))
        recommendation = clean(row.get("recommendation"))
        category = clean(row.get("decision_category"))

        if player_id in decision_by_id:
            raise RuntimeError(f"Duplicate decision row for {player_id}.")
        decision_by_id[player_id] = row

        if owner_before.get(player_id) != team_code:
            raise RuntimeError(
                f"Decision owner mismatch before application for {player_name}: "
                f"ledger={owner_before.get(player_id)!r}; decision={team_code!r}"
            )

        if recommendation == USER_PENDING:
            user_pending_rows.append({
                "player_id": player_id,
                "player_name": player_name,
                "team_abbreviation": team_code,
                "decision_category": category,
                "option_salary_2026_27": numeric(row.get("base_salary_2026_27")),
                "market_reference": numeric(row.get("market_reference")),
                "market_to_option_ratio": (
                    numeric(row.get("market_reference")) / numeric(row.get("base_salary_2026_27"))
                    if numeric(row.get("market_reference")) is not None
                    and numeric(row.get("base_salary_2026_27")) not in {None, 0.0}
                    else None
                ),
                "owner_before": owner_before[player_id],
                "owner_after_automatic_only": owner_after[player_id],
                "decision_applied": False,
            })
            continue

        if recommendation in AUTOMATIC_KEEP:
            new_owner = team_code
        elif recommendation in AUTOMATIC_MARKET:
            new_owner = "FA"
        else:
            raise RuntimeError(
                f"Unexpected non-user recommendation {recommendation!r} "
                f"for {player_name}."
            )

        owner_after[player_id] = new_owner

        applied_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": team_code,
            "decision_category": category,
            "recommendation": recommendation,
            "owner_before": owner_before[player_id],
            "owner_after": new_owner,
            "entered_market": new_owner == "FA",
            "financial_ready": boolish(row.get("financial_ready")),
            "market_reference": numeric(row.get("market_reference")),
            "base_salary_2026_27": numeric(row.get("base_salary_2026_27")),
            "confidence": clean(row.get("confidence")),
            "reason": clean(row.get("reason")),
            "decision_applied_to_clone": True,
            "durable_state_mutated": False,
        })

    automatic_market_additions = {
        row["player_id"] for row in applied_rows
        if row["entered_market"]
    }

    market_after_ids = {
        player_id for player_id, owner in owner_after.items()
        if owner == "FA"
    }

    team_counts_after = Counter(
        owner for owner in owner_after.values()
        if owner in TEAM_CODES
    )

    team_rows = []
    for team_code in sorted(TEAM_CODES):
        before_count = sum(owner == team_code for owner in owner_before.values())
        after_count = team_counts_after.get(team_code, 0)
        pending_user = sum(
            row["team_abbreviation"] == team_code
            for row in user_pending_rows
        )
        team_rows.append({
            "team_abbreviation": team_code,
            "roster_count_before_automatic_decisions": before_count,
            "roster_count_after_automatic_decisions": after_count,
            "automatic_roster_change": after_count - before_count,
            "pending_user_decision_count": pending_user,
            "minimum_final_roster_if_all_user_decline": after_count - pending_user,
            "maximum_final_roster_if_all_user_exercise": after_count,
            "exceeds_offseason_21_after_automatic": after_count > 21,
        })

    over_21 = [
        row["team_abbreviation"]
        for row in team_rows
        if row["exceeds_offseason_21_after_automatic"]
    ]

    # Per-player final clone ledger.
    player_rows = []
    player_name_by_id = {
        pid(row.get("player_id")): clean(row.get("player_name"))
        for row in lifecycle_rows
    }
    for row in branch_rows:
        player_name_by_id.setdefault(
            pid(row.get("player_id")),
            clean(row.get("player_name")),
        )
    for row in supplement_rows:
        player_name_by_id[pid(row.get("player_id"))] = clean(row.get("player_name"))

    for player_id in sorted(population_ids, key=lambda x: int(x) if x.isdigit() else x):
        decision = decision_by_id.get(player_id)
        player_rows.append({
            "player_id": player_id,
            "player_name": player_name_by_id.get(player_id, ""),
            "owner_before_automatic": owner_before.get(player_id, ""),
            "owner_after_automatic": owner_after.get(player_id, ""),
            "decision_category": clean(decision.get("decision_category")) if decision else "",
            "recommendation": clean(decision.get("recommendation")) if decision else "",
            "user_decision_pending": (
                clean(decision.get("recommendation")) == USER_PENDING
                if decision else False
            ),
            "entered_market_from_automatic_decision": (
                player_id in automatic_market_additions
            ),
        })

    recommendation_counts = Counter(
        clean(row.get("recommendation")) for row in decision_rows
    )
    automatic_counts = Counter(
        row["recommendation"] for row in applied_rows
    )

    checks = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 CLONE-ONLY OFFSEASON DECISION APPLICATION PREVIEW V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Extended population:             {len(population_ids)}", flush=True)
    print(f"Initial market:                  {len(initial_market_ids)}", flush=True)
    print(f"Automatic decisions applied:     {len(applied_rows)}", flush=True)
    print(f"User decisions left pending:     {len(user_pending_rows)}", flush=True)
    print(f"Automatic market additions:      {len(automatic_market_additions)}", flush=True)
    print(f"Market after automatic decisions:{len(market_after_ids):>7}", flush=True)
    print("CLONE ONLY. NO DURABLE MUTATION.", flush=True)
    print("", flush=True)
    print("Running strict clone-application checks...", flush=True)

    check(
        "upstream_v1_1_passed",
        bool(decision_summary.get("passed")),
        "Unified decision preview V1.1 passed.",
    )
    check(
        "extended_population_is_587",
        len(population_ids) == EXPECTED_POPULATION,
        f"population={len(population_ids)}",
    )
    check(
        "initial_market_is_194",
        len(initial_market_ids) == EXPECTED_INITIAL_MARKET,
        f"initial_market={len(initial_market_ids)}",
    )
    check(
        "exact_109_automatic_decisions_applied_to_clone",
        len(applied_rows) == EXPECTED_AUTOMATIC_DECISIONS,
        f"applied={len(applied_rows)}",
    )
    check(
        "exact_two_user_decisions_left_pending",
        len(user_pending_rows) == EXPECTED_USER_DECISIONS
        and {row["player_name"] for row in user_pending_rows}
        == {"Leonard Miller", "Mouhamadou Gueye"},
        repr([row["player_name"] for row in user_pending_rows]),
    )
    check(
        "recommendation_counts_match_v1_1",
        recommendation_counts
        == Counter({
            "exercise": 42,
            "decline": 29,
            "retain": 36,
            "waive": 2,
            "user_decision_required": 2,
        }),
        json.dumps(dict(sorted(recommendation_counts.items())), sort_keys=True),
    )
    check(
        "automatic_application_counts_exact",
        automatic_counts
        == Counter({
            "exercise": 42,
            "decline": 29,
            "retain": 36,
            "waive": 2,
        }),
        json.dumps(dict(sorted(automatic_counts.items())), sort_keys=True),
    )
    check(
        "automatic_market_additions_are_31",
        len(automatic_market_additions)
        == EXPECTED_AUTOMATIC_ADDITIONS_TO_MARKET,
        f"market_additions={len(automatic_market_additions)}",
    )
    check(
        "market_after_automatic_is_225",
        len(market_after_ids) == EXPECTED_MARKET_AFTER_AUTOMATIC,
        f"market={len(market_after_ids)}",
    )
    check(
        "market_growth_equals_declines_plus_waives",
        len(market_after_ids) - len(initial_market_ids)
        == recommendation_counts["decline"] + recommendation_counts["waive"],
        (
            f"growth={len(market_after_ids) - len(initial_market_ids)}; "
            f"declines+waives={recommendation_counts['decline'] + recommendation_counts['waive']}"
        ),
    )
    check(
        "user_decisions_not_applied",
        all(not row["decision_applied"] for row in user_pending_rows),
        "Both Chicago choices remain pending.",
    )
    check(
        "no_team_exceeds_offseason_21_after_automatic",
        not over_21,
        "over_21=" + ("|".join(over_21) if over_21 else "<none>"),
    )
    check(
        "all_automatic_decisions_applied_only_to_clone",
        all(row["decision_applied_to_clone"] and not row["durable_state_mutated"] for row in applied_rows),
        "No durable mutation flag is set.",
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
        row["check_id"] for row in checks
        if row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Clone-Only Offseason Decision Application Preview V1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_clone_only_offseason_decision_application_preview_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_clone_decision_apply_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "automatic_decisions_applied_109.csv", applied_rows)
        write_csv(export / "user_decisions_pending_2.csv", user_pending_rows)
        write_csv(export / "market_after_automatic_decisions_225.csv", [
            row for row in player_rows
            if row["owner_after_automatic"] == "FA"
        ])
        write_csv(export / "clone_owner_ledger_587.csv", player_rows)
        write_csv(export / "team_roster_counts_after_automatic.csv", team_rows)
        write_csv(export / "clone_application_checks.csv", checks)

        summary = {
            "version": VERSION,
            "extended_population_count": len(population_ids),
            "initial_market_count": len(initial_market_ids),
            "automatic_decision_count": len(applied_rows),
            "user_decision_pending_count": len(user_pending_rows),
            "automatic_market_addition_count": len(automatic_market_additions),
            "market_after_automatic_count": len(market_after_ids),
            "market_if_both_user_options_exercised": len(market_after_ids),
            "market_if_one_user_option_declined": len(market_after_ids) + 1,
            "market_if_both_user_options_declined": len(market_after_ids) + 2,
            "recommendation_counts": dict(sorted(recommendation_counts.items())),
            "automatic_application_counts": dict(sorted(automatic_counts.items())),
            "teams_over_offseason_21": over_21,
            "user_decisions": user_pending_rows,
            "clone_only": True,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Collect the two Chicago Team Option choices. Apply those two choices "
                "to the clone, producing a final exact simulated market of 225-227 players. "
                "Then rebuild RFA/QO eligibility and QO amounts on that final market before "
                "any durable checkpoint hydration."
            ),
        }
        (export / "clone_application_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 CLONE-ONLY OFFSEASON DECISION APPLICATION PREVIEW V1
==========================================================

This pass applies only the 109 automatic V1.1 recommendations to a cloned
April-12 ownership ledger.

Applied:
- 42 exercise
- 29 decline
- 36 retain
- 2 waive

Left pending:
- Leonard Miller, CHI Team Option
- Mouhamadou Gueye, CHI Team Option

The initial market is 194.
Automatic declines + waives add 31 players.
The market therefore becomes 225 before the two Chicago choices.

Final market range:
- both CHI options exercised: 225
- one declined: 226
- both declined: 227

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
    print("2026 CLONE-ONLY OFFSEASON DECISION APPLICATION PREVIEW V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Extended population:             587", flush=True)
    print("Initial market:                  194", flush=True)
    print("Automatic decisions applied:     109", flush=True)
    print("User decisions pending:            2", flush=True)
    print("Automatic market additions:       31", flush=True)
    print("Market after automatic decisions:225", flush=True)
    print("Final market range:          225-227", flush=True)
    print("Teams over offseason 21:        NONE", flush=True)
    print("State mutation:         NOT PERFORMED", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
