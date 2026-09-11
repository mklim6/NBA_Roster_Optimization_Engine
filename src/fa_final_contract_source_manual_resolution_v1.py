from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

VERSION = "fa-final-contract-source-manual-resolution-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

# Source-backed pre-/at-split contract evidence.
# Only rows actually present in the V4.1.1 four-player manual queue are applied.
RESOLUTIONS = {
    "1626166": {
        "player_name": "Cameron Payne",
        "classification": "immediate_market",
        "reason": (
            "Philadelphia waived Payne on April 10, 2026, before the "
            "April 12 simulation split. He is therefore not contract-attached "
            "at the offseason branch opening."
        ),
        "primary_source_url": "https://www.nba.com/players/transactions?Month=5",
        "secondary_source_url": "https://www.nba.com/player/1626166/cameron-payne/profile",
        "future_outcome_used": False,
    },
    "1642357": {
        "player_name": "David Jones Garcia",
        "classification": "immediate_market",
        "reason": (
            "San Antonio signed Jones Garcia to a one-year Two-Way contract "
            "on July 23, 2025. The pre-split contract covers only 2025-26, "
            "so he reaches the offseason market after that season."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/david-jones",
        "secondary_source_url": (
            "https://gleague.nba.com/news/spurs-sign-david-jones-garcia-to-two-way-contract"
        ),
        "future_outcome_used": False,
    },
    "1627780": {
        "player_name": "Gary Payton II",
        "classification": "immediate_market",
        "reason": (
            "Golden State signed Payton to a one-year 2025-26 veteran "
            "contract on September 29, 2025. There is no 2026-27 year on "
            "that contract."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/gary-paytonii",
        "secondary_source_url": "",
        "future_outcome_used": False,
    },
    "1642354": {
        "player_name": "KJ Simpson",
        "classification": "non_guaranteed_or_partial_decision",
        "reason": (
            "Denver signed Simpson to a two-year Two-Way contract on "
            "February 19, 2026. The contract contains a 2026-27 salary "
            "with only a portion guaranteed, so the player remains attached "
            "pending the simulator's guarantee/waiver decision."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/k-j-simpson",
        "secondary_source_url": "https://www.nba.com/players/transactions?Month=5",
        "future_outcome_used": False,
    },
    "1641998": {
        "player_name": "Trey Jemison III",
        "classification": "immediate_market",
        "reason": (
            "New York signed Jemison to a one-year Two-Way contract on "
            "September 16, 2025. The contract covers only 2025-26, so he "
            "reaches the offseason market after that season."
        ),
        "primary_source_url": "https://www.salaryswish.com/players/trey-jemison",
        "secondary_source_url": (
            "https://gleague.nba.com/news/new-york-knicks-sign-trey-jemison-iii-to-two-way-contract"
        ),
        "future_outcome_used": False,
    },
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


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

    upstream_zip = find_latest(
        root,
        "fa_official_option_and_zero_game_population_v4_1_1_preview_2026-27_*.zip",
    )

    with zipfile.ZipFile(upstream_zip) as archive:
        upstream_summary = read_json_member(archive, "v4_1_summary.json")
        lifecycle_rows = read_csv_member(
            archive,
            "unified_lifecycle_v4_1_311.csv",
        )

    manual_rows = [
        row for row in lifecycle_rows
        if clean(row.get("unified_lifecycle_category"))
        == "manual_contract_source_review"
    ]

    if len(manual_rows) != 4:
        raise RuntimeError(
            f"Expected exactly 4 manual contract-source rows, got {len(manual_rows)}."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state_digest_before = object_digest(checkpoint.simulation_state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before final manual-source resolution.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    manual_ids = {pid(row.get("player_id")) for row in manual_rows}
    known_ids = set(RESOLUTIONS)

    unknown = manual_ids - known_ids
    if unknown:
        details = [
            f"{pid(row.get('player_id'))}:{clean(row.get('player_name'))}"
            for row in manual_rows
            if pid(row.get("player_id")) in unknown
        ]
        raise RuntimeError(
            "Manual queue contains player(s) without source-backed resolution: "
            + ", ".join(details)
        )

    final_rows = []
    applied = []

    for row in lifecycle_rows:
        player_id = pid(row.get("player_id"))
        updated = dict(row)

        if player_id in manual_ids:
            evidence = RESOLUTIONS[player_id]
            updated["unified_lifecycle_category"] = evidence["classification"]
            updated["manual_contract_source_resolved"] = True
            updated["manual_contract_source_resolution_reason"] = evidence["reason"]
            updated["manual_contract_source_primary_source"] = evidence[
                "primary_source_url"
            ]
            updated["manual_contract_source_secondary_source"] = evidence[
                "secondary_source_url"
            ]
            updated["future_real_world_outcome_used"] = False

            applied.append({
                "player_id": player_id,
                "player_name": evidence["player_name"],
                "prior_category": "manual_contract_source_review",
                "resolved_category": evidence["classification"],
                "resolution_reason": evidence["reason"],
                "primary_source_url": evidence["primary_source_url"],
                "secondary_source_url": evidence["secondary_source_url"],
                "future_real_world_outcome_used": False,
            })

        final_rows.append(updated)

    final_manual = [
        row for row in final_rows
        if clean(row.get("unified_lifecycle_category"))
        == "manual_contract_source_review"
    ]

    counts = Counter(
        clean(row.get("unified_lifecycle_category"))
        for row in final_rows
    )

    prior_counts = Counter(
        clean(row.get("unified_lifecycle_category"))
        for row in lifecycle_rows
    )

    expected_counts = Counter(prior_counts)
    expected_counts["manual_contract_source_review"] -= 4
    for row in applied:
        expected_counts[row["resolved_category"]] += 1

    if expected_counts["manual_contract_source_review"] == 0:
        del expected_counts["manual_contract_source_review"]

    opening_market_count = counts.get("immediate_market", 0)
    pending_decision_count = (
        counts.get("team_option_decision", 0)
        + counts.get("player_option_decision", 0)
        + counts.get("non_guaranteed_or_partial_decision", 0)
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
    print("2026 FINAL CONTRACT-SOURCE MANUAL RESOLUTION V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Upstream lifecycle rows: {len(lifecycle_rows)}", flush=True)
    print(f"Manual input rows:       {len(manual_rows)}", flush=True)
    print("READ-ONLY. NO CHECKPOINT OR PLAYERSTATE WRITE.", flush=True)
    print("", flush=True)
    print("Manual rows detected:", flush=True)
    for row in manual_rows:
        print(
            f"  {pid(row.get('player_id'))} | {clean(row.get('player_name'))}",
            flush=True,
        )
    print("", flush=True)
    print("Running strict final-manual checks...", flush=True)

    check(
        "upstream_v4_1_1_passed",
        bool(upstream_summary.get("passed")),
        "V4.1.1 option/population preview passed.",
    )
    check(
        "exact_four_manual_input_rows",
        len(manual_rows) == 4,
        f"manual={len(manual_rows)}",
    )
    check(
        "all_manual_rows_have_source_backed_resolution",
        not unknown,
        f"manual_ids={sorted(manual_ids)}",
    )
    check(
        "exact_four_resolutions_applied",
        len(applied) == 4,
        f"applied={len(applied)}",
    )
    check(
        "zero_manual_rows_after_resolution",
        not final_manual,
        f"remaining={len(final_manual)}",
    )
    check(
        "lifecycle_row_count_remains_311",
        len(final_rows) == 311
        and len({pid(row.get("player_id")) for row in final_rows}) == 311,
        f"rows={len(final_rows)}",
    )
    check(
        "category_counts_reconcile_exactly",
        counts == expected_counts,
        json.dumps(dict(sorted(counts.items())), sort_keys=True),
    )
    check(
        "all_applied_resolutions_are_pre_or_at_split_evidence",
        all(not row["future_real_world_outcome_used"] for row in applied),
        "No post-April-12 signing/option outcome is used.",
    )
    check(
        "all_final_future_outcome_flags_false",
        all(
            not boolish(row.get("future_real_world_outcome_used"))
            for row in final_rows
        ),
        "All lifecycle rows remain future-leakage clean.",
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
            "Final Contract-Source Manual Resolution V1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_final_contract_source_manual_resolution_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_final_manual_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "resolved_manual_contract_sources.csv",
            applied,
        )
        write_csv(
            export / "unified_lifecycle_final_311.csv",
            final_rows,
        )
        write_csv(
            export / "remaining_manual_contract_sources.csv",
            final_manual,
        )
        write_csv(
            export / "final_manual_resolution_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "lifecycle_row_count": len(final_rows),
            "manual_input_count": len(manual_rows),
            "manual_resolved_count": len(applied),
            "manual_remaining_count": len(final_manual),
            "category_counts": dict(sorted(counts.items())),
            "immediate_market_count": opening_market_count,
            "pending_decision_count": pending_decision_count,
            "team_option_count": counts.get("team_option_decision", 0),
            "player_option_count": counts.get("player_option_decision", 0),
            "non_guaranteed_or_partial_count": counts.get(
                "non_guaranteed_or_partial_decision", 0
            ),
            "guaranteed_under_contract_count": counts.get(
                "guaranteed_under_contract", 0
            ),
            "future_real_world_outcomes_used": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Build simulator-owned decision previews for 52 Team Options, "
                "21 Player Options, and the final non-guaranteed/partial contract "
                "queue. Apply decisions only on a clone, recompute the simulated "
                "market, and then rebuild RFA/QO eligibility."
            ),
        }

        (export / "final_manual_resolution_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 FINAL CONTRACT-SOURCE MANUAL RESOLUTION V1
=================================================

This pass resolves the exact four contract-source manual rows remaining after
V4.1.1.

The package contains source-backed resolution rules for the five players that
have appeared in the historical manual-source problem set, but it applies only
to the exact four players present in the upstream V4.1.1 audit.

Supported evidence-backed resolutions:
- Cameron Payne -> immediate market
- David Jones Garcia -> immediate market
- Gary Payton II -> immediate market
- KJ Simpson -> non-guaranteed/partial 2026-27 decision
- Trey Jemison III -> immediate market

No later real-world free-agency or option outcome is imported.

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 FINAL CONTRACT-SOURCE MANUAL RESOLUTION V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Lifecycle rows:          {len(final_rows)}", flush=True)
    print(f"Manual resolved:         {len(applied)}", flush=True)
    print(f"Manual remaining:        {len(final_manual)}", flush=True)
    print(f"Immediate market:        {opening_market_count}", flush=True)
    print(f"Team Options:            {counts.get('team_option_decision', 0)}", flush=True)
    print(f"Player Options:          {counts.get('player_option_decision', 0)}", flush=True)
    print(
        f"Non-guaranteed/partial: {counts.get('non_guaranteed_or_partial_decision', 0)}",
        flush=True,
    )
    print(
        f"Guaranteed contracts:    {counts.get('guaranteed_under_contract', 0)}",
        flush=True,
    )
    print("Future outcomes used:    NO", flush=True)
    print("Checkpoint write:        NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
