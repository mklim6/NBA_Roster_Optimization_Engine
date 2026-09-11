from __future__ import annotations

import ast
import csv
import hashlib
import inspect
import io
import json
import re
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-team-option-transaction-readiness-v1-2026-08-14"
SEASON_LABEL = "2026-27"

KEYWORDS = (
    "option",
    "contract",
    "salary",
    "guarante",
    "free_agent",
    "free agent",
    "roster",
    "commit",
    "transaction",
)

HIGH_VALUE_SOURCE_PATTERNS = (
    "franchise_free_agency*.py",
    "franchise_*contract*.py",
    "franchise_*transaction*.py",
    "simulation_franchise*.py",
    "*salary*legality*.py",
    "*checkpoint*.py",
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def team(value: Any) -> str:
    return clean(value).upper()


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"true", "1", "yes"}


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return (
            root
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        )


def state_digest(state: Any) -> str:
    payload = {
        "season": clean(
            getattr(getattr(state, "settings", None), "season_label", "")
        ),
        "phase": clean(getattr(state, "phase", "")),
        "free_agents": list(
            getattr(state, "free_agent_player_ids", ()) or ()
        ),
        "teams": {
            str(code): list(
                getattr(ts, "roster_player_ids", ()) or ()
            )
            for code, ts in sorted(
                (getattr(state, "teams", {}) or {}).items()
            )
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def safe_value(value: Any, max_len: int = 500) -> str:
    try:
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = repr(value)
        elif isinstance(value, Mapping):
            text = f"<{type(value).__name__} len={len(value)} keys={list(value)[:20]!r}>"
        elif isinstance(value, (list, tuple, set, frozenset)):
            text = f"<{type(value).__name__} len={len(value)} sample={list(value)[:20]!r}>"
        else:
            text = f"<{type(value).__module__}.{type(value).__name__}>"
    except Exception as exc:
        text = f"<unreadable {type(exc).__name__}>"
    return text[:max_len]


def iter_attrs(obj: Any) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if obj is None:
        return rows

    if isinstance(obj, Mapping):
        rows.extend((str(k), v) for k, v in obj.items())
    else:
        try:
            rows.extend(vars(obj).items())
        except Exception:
            pass

    seen = {name for name, _ in rows}
    for name in dir(obj):
        if name.startswith("_") or name in seen:
            continue
        low = name.lower()
        if not any(token.replace(" ", "_") in low for token in KEYWORDS):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        rows.append((name, value))
        seen.add(name)

    return rows


def relevant_attrs(
    *,
    player_id: str,
    object_role: str,
    obj: Any,
) -> list[dict[str, Any]]:
    result = []
    for name, value in iter_attrs(obj):
        low = name.lower()
        if not any(
            token in low or token.replace(" ", "_") in low
            for token in KEYWORDS
        ):
            continue
        result.append({
            "player_id": player_id,
            "object_role": object_role,
            "object_type": (
                f"{type(obj).__module__}.{type(obj).__name__}"
                if obj is not None else ""
            ),
            "attribute": name,
            "value_summary": safe_value(value),
        })
    return result


def source_files(root: Path) -> list[Path]:
    src = root / "src"
    if not src.exists():
        return []
    found: set[Path] = set()
    for pattern in HIGH_VALUE_SOURCE_PATTERNS:
        found.update(p for p in src.glob(pattern) if p.is_file())
    return sorted(found)


def function_inventory(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252", errors="ignore")
    except Exception:
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines()
    rows = []

    for node in ast.walk(tree):
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue

        name = clean(getattr(node, "name", ""))
        low = name.lower()
        line_start = int(getattr(node, "lineno", 0) or 0)
        line_end = int(getattr(node, "end_lineno", line_start) or line_start)

        snippet = "\n".join(
            lines[max(0, line_start - 1): min(len(lines), line_end)]
        )
        snippet_low = snippet.lower()

        keyword_hits = [
            token
            for token in KEYWORDS
            if token in low or token in snippet_low
        ]

        if not keyword_hits:
            continue

        rows.append({
            "source_path": str(path.resolve()),
            "source_sha256": sha256_file(path),
            "symbol_type": type(node).__name__,
            "symbol_name": name,
            "line_start": line_start,
            "line_end": line_end,
            "keyword_hits": "|".join(keyword_hits),
            "signature_or_header": (
                lines[line_start - 1].strip()
                if line_start and line_start <= len(lines)
                else ""
            )[:500],
        })

    return rows


def source_text_hits(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252", errors="ignore")
    except Exception:
        return []

    lines = text.splitlines()
    rows = []
    patterns = (
        "free_agent_player_ids",
        "roster_player_ids",
        "commit_free_agent",
        "commit_sign",
        "contract_salary",
        "annual_salary",
        "salary_by_season",
        "option_type",
        "team_option",
        "guaranteed",
        "checkpoint",
    )

    for i, line in enumerate(lines, start=1):
        low = line.lower()
        hits = [p for p in patterns if p in low]
        if hits:
            rows.append({
                "source_path": str(path.resolve()),
                "source_sha256": sha256_file(path),
                "line_number": i,
                "keyword_hits": "|".join(hits),
                "line_text": line.strip()[:1000],
            })
    return rows


def collection_membership(
    *,
    player_id: str,
    team_code: str,
    state: Any,
) -> dict[str, Any]:
    free_agents = list(
        getattr(state, "free_agent_player_ids", ()) or ()
    )
    team_state = (
        (getattr(state, "teams", {}) or {}).get(team_code)
    )
    roster = list(
        getattr(team_state, "roster_player_ids", ()) or ()
    )
    return {
        "in_free_agent_collection": player_id in {clean(x) for x in free_agents},
        "in_prior_team_roster": player_id in {clean(x) for x in roster},
        "free_agent_count": len(free_agents),
        "prior_team_roster_count": len(roster),
    }


def infer_required_mutations(
    *,
    recommendation: str,
    memberships: Mapping[str, Any],
) -> list[str]:
    if recommendation == "exercise":
        return [
            "preserve_player_on_prior_team_roster",
            "preserve_player_out_of_free_agent_pool",
            "preserve_or_materialize_2026_27_option_salary_as_active_contract_salary",
            "mark_2026_27_team_option_exercised_in_contract_state_or_transaction_ledger",
            "recompute_team_2026_27_salary_commitments_and_cap_posture",
            "invalidate_or_rebuild_free_agency_rights_status_for_player_as_not_free_agent",
            "persist_atomically_only_after_all_validators_pass",
        ]

    if recommendation == "decline":
        return [
            "end_contract_after_2025_26_at_option_boundary",
            "remove_player_from_prior_team_roster_at_offseason_transition_if_still_rostered",
            "add_player_to_2026_free_agent_pool_exactly_once",
            "classify_corrected_veteran_or_non_veteran_free_agent_category",
            "recompute_bird_early_bird_non_bird_or_not_applicable_rights_from_prior_team",
            "recompute_rfa_qo_eligibility_on_declined-option free-agent state",
            "remove_2026_27_option_salary_from_team_commitments",
            "recompute_team_2026_27 cap posture",
            "persist_atomically_only_after_all_validators_pass",
        ]

    return [
        "no_cpu_mutation_until_user_or_manual_decision_is_resolved",
    ]


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

    option_zip = find_latest(
        root,
        "fa_team_option_cpu_decision_preview_v1_2026-27_*.zip",
    )
    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(option_zip) as archive:
        option_summary = read_json_member(
            archive,
            "team_option_summary.json",
        )
        recommendations = read_csv_member(
            archive,
            "team_option_cpu_recommendations.csv",
        )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )

    checkpoint_file = checkpoint_path(root)
    checkpoint_before = sha256_file(checkpoint_file)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )
    overlay_before = sha256_file(overlay)

    try:
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        checkpoint = load_franchise_checkpoint()
        state = checkpoint.simulation_state
    except Exception as exc:
        raise RuntimeError(
            "Transaction readiness requires the current durable franchise checkpoint."
        ) from exc

    state_before = state_digest(state)

    players = getattr(state, "players", {}) or {}
    teams = getattr(state, "teams", {}) or {}

    print("=" * 124, flush=True)
    print("2026 TEAM OPTION TRANSACTION READINESS V1", flush=True)
    print("=" * 124, flush=True)
    print(f"Decision-board input: {option_zip}", flush=True)
    print(
        "READ-ONLY schema/provenance inspection. No recommendation is committed.",
        flush=True,
    )
    print("", flush=True)

    object_rows: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    transaction_plan_rows: list[dict[str, Any]] = []

    for index, row in enumerate(
        recommendations,
        start=1,
    ):
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        team_code = team(row.get("team_abbreviation"))
        recommendation = clean(row.get("cpu_recommendation"))

        print(
            f"[{index:02d}/{len(recommendations):02d}] "
            f"{player_name} ({team_code}) -> {recommendation}",
            flush=True,
        )

        player = players.get(player_id)
        team_state = teams.get(team_code)

        object_rows.extend(
            relevant_attrs(
                player_id=player_id,
                object_role="player",
                obj=player,
            )
        )
        object_rows.extend(
            relevant_attrs(
                player_id=player_id,
                object_role="prior_team_state",
                obj=team_state,
            )
        )

        memberships = collection_membership(
            player_id=player_id,
            team_code=team_code,
            state=state,
        )

        membership_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": team_code,
            "cpu_recommendation": recommendation,
            **memberships,
        })

        for order, mutation in enumerate(
            infer_required_mutations(
                recommendation=recommendation,
                memberships=memberships,
            ),
            start=1,
        ):
            transaction_plan_rows.append({
                "player_id": player_id,
                "player_name": player_name,
                "team_abbreviation": team_code,
                "cpu_recommendation": recommendation,
                "mutation_order": order,
                "required_atomic_mutation": mutation,
            })

    inventory_rows: list[dict[str, Any]] = []
    text_hit_rows: list[dict[str, Any]] = []
    scanned_paths = source_files(root)

    print("", flush=True)
    print(
        f"Inspecting {len(scanned_paths)} high-value source files for existing commit hooks...",
        flush=True,
    )

    for path in scanned_paths:
        inventory_rows.extend(function_inventory(path))
        text_hit_rows.extend(source_text_hits(path))

    likely_commit_symbols = [
        row for row in inventory_rows
        if (
            "commit" in clean(row.get("symbol_name")).lower()
            or "transaction" in clean(row.get("symbol_name")).lower()
            or "sign" in clean(row.get("symbol_name")).lower()
            or "contract" in clean(row.get("symbol_name")).lower()
        )
    ]

    cpu_rows = [
        row for row in recommendations
        if not truthy(row.get("controlled_team"))
    ]
    user_rows = [
        row for row in recommendations
        if truthy(row.get("controlled_team"))
    ]

    checkpoint_after = sha256_file(checkpoint_file)
    overlay_after = sha256_file(overlay)
    state_after = state_digest(state)

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

    print("", flush=True)
    print("Running strict transaction-readiness checks...", flush=True)

    check(
        "team_option_preview_passed",
        bool(option_summary.get("passed")),
        "Transaction planning starts from the passed 13-player decision board.",
    )
    check(
        "contract_lifecycle_preview_passed",
        bool(lifecycle_summary.get("passed")),
        "Option decisions are downstream of the corrected contract lifecycle.",
    )
    check(
        "exact_13_option_rows_preserved",
        len(recommendations) == 13
        and len({pid(row.get("player_id")) for row in recommendations}) == 13,
        f"rows={len(recommendations)}",
    )
    check(
        "exact_12_cpu_plus_1_user_split",
        len(cpu_rows) == 12 and len(user_rows) == 1,
        f"cpu={len(cpu_rows)}; user={len(user_rows)}",
    )
    check(
        "all_cpu_rows_have_binary_recommendation",
        all(
            clean(row.get("cpu_recommendation"))
            in {"exercise", "decline"}
            for row in cpu_rows
        ),
        "No CPU transaction is planned from a manual or ambiguous recommendation.",
    )
    check(
        "user_row_has_no_cpu_transaction",
        all(
            clean(row.get("cpu_recommendation"))
            == "user_decision_required"
            for row in user_rows
        ),
        "Controlled team remains outside CPU transaction scope.",
    )
    check(
        "every_player_object_resolves",
        all(
            pid(row.get("player_id")) in players
            for row in recommendations
        ),
        "All 13 option players exist in the live checkpoint player map.",
    )
    check(
        "every_prior_team_state_resolves",
        all(
            team(row.get("team_abbreviation")) in teams
            for row in recommendations
        ),
        "All 13 prior teams exist in the live checkpoint team map.",
    )
    check(
        "every_row_has_atomic_transaction_plan",
        all(
            any(
                plan["player_id"] == pid(row.get("player_id"))
                for plan in transaction_plan_rows
            )
            for row in recommendations
        ),
        "Every option row has an explicit mutation sequence.",
    )
    check(
        "source_commit_hook_inventory_is_nonempty",
        bool(likely_commit_symbols),
        f"likely_commit_symbols={len(likely_commit_symbols)}",
    )
    check(
        "live_state_unchanged",
        state_before == state_after,
        state_after,
    )
    check(
        "checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        checkpoint_after,
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        overlay_after or "<absent>",
    )

    option_contract_attr_rows = [
        row for row in object_rows
        if any(
            token in clean(row.get("attribute")).lower()
            for token in ("contract", "salary", "option", "guarante")
        )
    ]
    check(
        "checkpoint_contract_field_visibility",
        bool(option_contract_attr_rows),
        f"relevant_object_attributes={len(option_contract_attr_rows)}",
        severity="coverage",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    if failed:
        raise RuntimeError(
            "Team Option Transaction Readiness V1 failed strict checks: "
            + ", ".join(failed)
        )

    symbol_counts = Counter(
        row["source_path"]
        for row in likely_commit_symbols
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_team_option_transaction_readiness_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_teamopt_txn_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "team_option_transaction_plan.csv",
            transaction_plan_rows,
        )
        write_csv(
            export / "team_option_live_memberships.csv",
            membership_rows,
        )
        write_csv(
            export / "team_option_checkpoint_relevant_attributes.csv",
            object_rows,
        )
        write_csv(
            export / "team_option_source_symbol_inventory.csv",
            inventory_rows,
        )
        write_csv(
            export / "team_option_source_text_hits.csv",
            text_hit_rows,
        )
        write_csv(
            export / "team_option_transaction_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "option_row_count": len(recommendations),
            "cpu_transaction_candidate_count": len(cpu_rows),
            "user_decision_row_count": len(user_rows),
            "exercise_candidate_count": sum(
                clean(row.get("cpu_recommendation")) == "exercise"
                for row in cpu_rows
            ),
            "decline_candidate_count": sum(
                clean(row.get("cpu_recommendation")) == "decline"
                for row in cpu_rows
            ),
            "transaction_plan_step_count": len(transaction_plan_rows),
            "high_value_source_file_count": len(scanned_paths),
            "source_symbol_inventory_count": len(inventory_rows),
            "likely_commit_symbol_count": len(likely_commit_symbols),
            "likely_commit_symbol_counts_by_file": dict(
                sorted(symbol_counts.items())
            ),
            "checkpoint_relevant_attribute_count": len(object_rows),
            "checkpoint_contract_field_visibility_count": len(
                option_contract_attr_rows
            ),
            "option_decisions_applied": 0,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "state_mutation_performed": False,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Use the exported checkpoint attributes + existing commit-hook "
                "inventory to build an atomic copy-on-write Team Option transaction "
                "dry run for the 12 CPU teams. Keep the CHI/user option unresolved. "
                "Validate roster, contract salary, free-agent pool, rights/RFA "
                "reclassification, team cap totals, rollback, and checkpoint "
                "serialization before any durable write."
            ),
        }

        (
            export / "team_option_transaction_readiness_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """2026 TEAM OPTION TRANSACTION READINESS V1
=========================================

This package does NOT exercise or decline a Team Option.

It inspects the live checkpoint and installed source code to determine the
exact mutation surface that an atomic Team Option commit must cover.

Input decision board:
- 13 true Team Options
- 12 CPU-controlled binary recommendations
- 1 user-controlled CHI decision

For each player it records:
- current roster membership
- current free-agent-pool membership
- relevant player contract/salary/option attributes
- relevant team-state contract/salary/roster attributes
- the atomic mutation sequence needed for exercise vs decline

It also inventories installed source functions/classes and source lines related
to:
- free-agent commit paths
- contracts / salary
- transactions
- roster mutations
- checkpoints
- option fields

Why this comes before a real apply:
Team Option exercise/decline is not only a UI flag. The commit must keep roster,
contract salary, team cap commitments, free-agent population, Bird/RFA state,
and checkpoint serialization synchronized atomically.

READ ONLY.
"""
        (export / "README.txt").write_text(
            readme,
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            zip_out,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    if state_digest(state) != state_before:
        raise RuntimeError(
            "Live franchise state changed during transaction readiness."
        )
    if sha256_file(checkpoint_file) != checkpoint_before:
        raise RuntimeError(
            "Checkpoint changed during transaction readiness."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed during transaction readiness."
        )

    print("", flush=True)
    print("=" * 124, flush=True)
    print("2026 TEAM OPTION TRANSACTION READINESS V1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Option rows:                  {len(recommendations)}", flush=True)
    print(f"CPU transaction candidates:  {len(cpu_rows)}", flush=True)
    print(f"User decision rows:          {len(user_rows)}", flush=True)
    print(f"Atomic transaction steps:    {len(transaction_plan_rows)}", flush=True)
    print(f"Source files inspected:      {len(scanned_paths)}", flush=True)
    print(f"Likely commit symbols:       {len(likely_commit_symbols)}", flush=True)
    print(f"Relevant checkpoint attrs:   {len(option_contract_attr_rows)}", flush=True)
    print("Option decisions applied: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
