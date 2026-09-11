from __future__ import annotations

import copy
import csv
import dataclasses
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-offseason-contract-state-reconciliation-dry-run-v1-2026-08-14"
SEASON_LABEL = "2026-27"

PENDING_PREFIX = "pending_"
UNDER_CONTRACT_PREFIX = "under_contract_"


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
        data = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        data = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required input: {pattern}")
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


def replace_attr(obj: Any, **changes: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.replace(obj, **changes)

    cloned = copy.deepcopy(obj)
    for key, value in changes.items():
        setattr(cloned, key, value)
    return cloned


def update_state_maps(
    state: Any,
    *,
    players: Mapping[str, Any],
    teams: Mapping[str, Any],
    free_agent_player_ids: tuple[str, ...],
) -> Any:
    changes = {}
    if hasattr(state, "players"):
        changes["players"] = players
    if hasattr(state, "teams"):
        changes["teams"] = teams
    if hasattr(state, "free_agent_player_ids"):
        changes["free_agent_player_ids"] = free_agent_player_ids
    if not changes:
        raise RuntimeError("Simulation state does not expose required maps.")
    return replace_attr(state, **changes)


def update_checkpoint_state(checkpoint: Any, state: Any) -> Any:
    if not hasattr(checkpoint, "simulation_state"):
        raise RuntimeError("Checkpoint lacks simulation_state.")
    return replace_attr(checkpoint, simulation_state=state)


def active_roster_status(state: Any) -> str:
    players = getattr(state, "players", {}) or {}
    teams = getattr(state, "teams", {}) or {}

    counter = Counter()
    rostered = set()
    for team_state in teams.values():
        rostered.update(
            pid(value)
            for value in (
                getattr(team_state, "roster_player_ids", ()) or ()
            )
        )

    for player_id in rostered:
        player = players.get(player_id)
        if player is None:
            continue
        status = clean(getattr(player, "roster_status", ""))
        if status:
            counter[status] += 1

    if counter:
        return counter.most_common(1)[0][0]
    return "roster"


def set_player_roster_status(player: Any, status: str) -> Any:
    if not hasattr(player, "roster_status"):
        return player
    return replace_attr(player, roster_status=status)


def set_team_roster(team_state: Any, roster_ids: tuple[str, ...]) -> Any:
    if not hasattr(team_state, "roster_player_ids"):
        raise RuntimeError("Team state lacks roster_player_ids.")
    return replace_attr(
        team_state,
        roster_player_ids=tuple(roster_ids),
    )


def state_memberships(state: Any) -> dict[str, Any]:
    players = getattr(state, "players", {}) or {}
    teams = getattr(state, "teams", {}) or {}
    free_agents = tuple(
        pid(value)
        for value in (
            getattr(state, "free_agent_player_ids", ()) or ()
        )
    )

    roster_owner: dict[str, str] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)

    for team_code, team_state in teams.items():
        for player_id in (
            getattr(team_state, "roster_player_ids", ()) or ()
        ):
            player_id = pid(player_id)
            duplicates[player_id].append(team(team_code))
            if player_id not in roster_owner:
                roster_owner[player_id] = team(team_code)

    duplicate_roster_players = {
        player_id: owners
        for player_id, owners in duplicates.items()
        if len(owners) > 1
    }

    both = sorted(set(free_agents).intersection(roster_owner))
    unknown_free_agents = sorted(
        player_id for player_id in free_agents
        if player_id not in players
    )

    return {
        "free_agent_ids": free_agents,
        "free_agent_count": len(free_agents),
        "roster_owner": roster_owner,
        "rostered_player_count": len(roster_owner),
        "players_in_both": both,
        "duplicate_roster_players": duplicate_roster_players,
        "unknown_free_agents": unknown_free_agents,
        "team_roster_counts": {
            team(team_code): len(
                getattr(team_state, "roster_player_ids", ()) or ()
            )
            for team_code, team_state in teams.items()
        },
    }


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

    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    corrected_rfa_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )
    transaction_zip = find_latest(
        root,
        "fa_team_option_transaction_readiness_v1_2026-27_*.zip",
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

    with zipfile.ZipFile(corrected_rfa_zip) as archive:
        corrected_summary = read_json_member(
            archive,
            "corrected_rfa_qo_summary.json",
        )
        market_rows = read_csv_member(
            archive,
            "corrected_rfa_qo_universe_all.csv",
        )

    with zipfile.ZipFile(transaction_zip) as archive:
        transaction_summary = read_json_member(
            archive,
            "team_option_transaction_readiness_summary.json",
        )
        memberships = read_csv_member(
            archive,
            "team_option_live_memberships.csv",
        )

    market_ids = {
        pid(row.get("player_id"))
        for row in market_rows
    }

    attached_rows = [
        row for row in lifecycle_rows
        if (
            clean(row.get("contract_lifecycle_state")).startswith(
                PENDING_PREFIX
            )
            or clean(row.get("contract_lifecycle_state")).startswith(
                UNDER_CONTRACT_PREFIX
            )
        )
    ]
    manual_rows = [
        row for row in lifecycle_rows
        if clean(row.get("contract_lifecycle_state")).startswith(
            "manual_review"
        )
    ]

    attached_ids = {
        pid(row.get("player_id"))
        for row in attached_rows
    }
    manual_ids = {
        pid(row.get("player_id"))
        for row in manual_rows
    }

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
        from simulation_franchise_checkpoint_v1 import (
            load_franchise_checkpoint,
        )
        checkpoint = load_franchise_checkpoint()
    except Exception as exc:
        raise RuntimeError(
            "Could not load the durable franchise checkpoint."
        ) from exc

    live_state = checkpoint.simulation_state
    live_state_digest_before = object_digest(live_state)
    live_checkpoint_object_digest_before = object_digest(checkpoint)
    live_membership = state_memberships(live_state)

    print("=" * 126, flush=True)
    print(
        "2026 OFFSEASON CONTRACT-STATE RECONCILIATION DRY RUN V1",
        flush=True,
    )
    print("=" * 126, flush=True)
    print(f"Lifecycle audit:     {lifecycle_zip}", flush=True)
    print(f"Corrected market:    {corrected_rfa_zip}", flush=True)
    print(f"Transaction audit:   {transaction_zip}", flush=True)
    print("", flush=True)
    print(
        "COPY-ON-WRITE ONLY. The durable checkpoint will not be saved.",
        flush=True,
    )
    print(
        f"Live free-agent collection before reconciliation: "
        f"{live_membership['free_agent_count']}",
        flush=True,
    )
    print(
        f"Corrected market target: {len(market_ids)}",
        flush=True,
    )
    print(
        f"Contract-attached/pending players to restore: "
        f"{len(attached_ids)}",
        flush=True,
    )
    print(
        f"Manual contract-source players to quarantine: "
        f"{len(manual_ids)}",
        flush=True,
    )
    print("", flush=True)

    # Deep-copy the entire durable checkpoint. All following changes are made
    # only to this in-memory clone.
    clone_checkpoint = copy.deepcopy(checkpoint)
    clone_state = clone_checkpoint.simulation_state

    players = dict(getattr(clone_state, "players", {}) or {})
    teams = dict(getattr(clone_state, "teams", {}) or {})
    live_free_agents = tuple(
        pid(value)
        for value in (
            getattr(clone_state, "free_agent_player_ids", ()) or ()
        )
    )

    active_status = active_roster_status(clone_state)

    contract_digests_before = {
        player_id: object_digest(
            getattr(players[player_id], "contract", None)
        )
        for player_id in attached_ids
        if player_id in players
    }

    reconciliation_rows: list[dict[str, Any]] = []

    # Canonical free-agent collection in the clone becomes exactly the
    # corrected 132-player market. Manual lifecycle rows are intentionally
    # excluded from market availability until researched.
    new_free_agents = tuple(
        player_id
        for player_id in live_free_agents
        if player_id in market_ids
    )

    if set(new_free_agents) != market_ids:
        # Preserve deterministic order from the live collection, then append
        # any corrected-market id that was unexpectedly absent.
        ordered = list(new_free_agents)
        seen = set(ordered)
        ordered.extend(
            sorted(market_ids - seen)
        )
        new_free_agents = tuple(ordered)

    # Restore every contract-attached or contract-pending player to the prior
    # team roster in the clone. Their contract object is not altered.
    for row in attached_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        team_code = team(row.get("prior_team"))
        lifecycle_state = clean(
            row.get("contract_lifecycle_state")
        )

        if player_id not in players:
            raise RuntimeError(
                f"Attached player missing from state: {player_name} "
                f"({player_id})"
            )
        if team_code not in teams:
            raise RuntimeError(
                f"Prior team missing from state: {team_code}"
            )

        team_state = teams[team_code]
        roster = [
            pid(value)
            for value in (
                getattr(team_state, "roster_player_ids", ()) or ()
            )
        ]

        roster_before = tuple(roster)
        was_in_roster = player_id in set(roster)
        was_in_fa = player_id in set(live_free_agents)

        if not was_in_roster:
            roster.append(player_id)

        teams[team_code] = set_team_roster(
            team_state,
            tuple(roster),
        )
        players[player_id] = set_player_roster_status(
            players[player_id],
            active_status,
        )

        reconciliation_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": team_code,
            "lifecycle_state": lifecycle_state,
            "action": "restore_contract_attached_player",
            "live_was_in_free_agent_pool": was_in_fa,
            "live_was_in_prior_team_roster": was_in_roster,
            "clone_in_free_agent_pool_after": False,
            "clone_in_prior_team_roster_after": True,
            "clone_roster_status_after": active_status,
            "contract_object_mutated": False,
            "roster_count_before": len(roster_before),
            "roster_count_after": len(roster),
        })

    # Manual lifecycle cases are quarantined out of the simulated market.
    # Their roster_status and contract object are intentionally untouched:
    # there is not enough evidence to assign them to a team.
    for row in manual_rows:
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        reconciliation_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": team(row.get("prior_team")),
            "lifecycle_state": clean(
                row.get("contract_lifecycle_state")
            ),
            "action": "quarantine_manual_contract_review",
            "live_was_in_free_agent_pool": (
                player_id in set(live_free_agents)
            ),
            "live_was_in_prior_team_roster": (
                live_membership["roster_owner"].get(player_id)
                == team(row.get("prior_team"))
            ),
            "clone_in_free_agent_pool_after": False,
            "clone_in_prior_team_roster_after": False,
            "clone_roster_status_after": clean(
                getattr(players.get(player_id), "roster_status", "")
            ),
            "contract_object_mutated": False,
            "roster_count_before": "",
            "roster_count_after": "",
        })

    clone_state = update_state_maps(
        clone_state,
        players=players,
        teams=teams,
        free_agent_player_ids=new_free_agents,
    )
    clone_checkpoint = update_checkpoint_state(
        clone_checkpoint,
        clone_state,
    )

    clone_membership = state_memberships(clone_state)

    contract_digests_after = {
        player_id: object_digest(
            getattr(
                getattr(clone_state, "players", {})[player_id],
                "contract",
                None,
            )
        )
        for player_id in attached_ids
        if player_id in getattr(clone_state, "players", {})
    }

    # Round-trip the cloned checkpoint through pickle. This does not use the
    # durable save function and does not write the canonical checkpoint.
    clone_bytes = pickle.dumps(
        clone_checkpoint,
        protocol=pickle.HIGHEST_PROTOCOL,
    )
    reloaded_checkpoint = pickle.loads(clone_bytes)
    reloaded_state = reloaded_checkpoint.simulation_state
    reloaded_membership = state_memberships(reloaded_state)

    live_state_digest_after = object_digest(live_state)
    live_checkpoint_object_digest_after = object_digest(checkpoint)
    checkpoint_after = sha256_file(checkpoint_file)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(
            f"  {check_id}: "
            f"{'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("Running strict copy-on-write checks...", flush=True)

    check(
        "upstream_lifecycle_passed",
        bool(lifecycle_summary.get("passed")),
        "Reconciliation is downstream of the passed lifecycle audit.",
    )
    check(
        "upstream_corrected_rfa_passed",
        bool(corrected_summary.get("passed")),
        "Corrected market is the source of truth for market availability.",
    )
    check(
        "upstream_transaction_readiness_passed",
        bool(transaction_summary.get("passed")),
        "Transaction schema inspection passed before this dry run.",
    )
    check(
        "lifecycle_partition_is_132_plus_51_plus_4",
        len(market_ids) == 132
        and len(attached_ids) == 51
        and len(manual_ids) == 4
        and len(market_ids | attached_ids | manual_ids) == 187
        and not market_ids.intersection(attached_ids)
        and not market_ids.intersection(manual_ids)
        and not attached_ids.intersection(manual_ids),
        (
            f"market={len(market_ids)}; attached={len(attached_ids)}; "
            f"manual={len(manual_ids)}"
        ),
    )
    check(
        "live_checkpoint_still_has_provisional_187_free_agents",
        live_membership["free_agent_count"] == 187,
        f"live_free_agents={live_membership['free_agent_count']}",
    )
    check(
        "clone_free_agent_pool_is_exactly_corrected_132",
        set(clone_membership["free_agent_ids"]) == market_ids
        and clone_membership["free_agent_count"] == 132,
        (
            f"clone_free_agents={clone_membership['free_agent_count']}"
        ),
    )
    check(
        "all_51_attached_players_restored_to_prior_rosters",
        all(
            clone_membership["roster_owner"].get(
                pid(row.get("player_id"))
            )
            == team(row.get("prior_team"))
            for row in attached_rows
        ),
        "Every pending/under-contract player is attached to the proven prior team in the clone.",
    )
    check(
        "all_51_attached_players_removed_from_clone_market",
        not attached_ids.intersection(
            set(clone_membership["free_agent_ids"])
        ),
        "No contract-attached player remains market-available.",
    )
    check(
        "all_4_manual_players_quarantined_from_clone_market",
        not manual_ids.intersection(
            set(clone_membership["free_agent_ids"])
        ),
        "Manual contract-source cases cannot receive offers.",
    )
    check(
        "manual_players_are_not_guessed_onto_rosters",
        not manual_ids.intersection(
            set(clone_membership["roster_owner"])
        ),
        "Manual rows remain unassigned rather than guessed.",
    )
    check(
        "restored_contract_objects_are_bitwise_unchanged",
        contract_digests_before == contract_digests_after,
        f"contracts_checked={len(contract_digests_before)}",
    )
    check(
        "clone_has_no_player_in_roster_and_free_agent_pool",
        not clone_membership["players_in_both"],
        (
            "overlap="
            + "|".join(clone_membership["players_in_both"])
            if clone_membership["players_in_both"]
            else "overlap=<none>"
        ),
    )
    check(
        "clone_has_no_duplicate_roster_membership",
        not clone_membership["duplicate_roster_players"],
        (
            "duplicates="
            + json.dumps(
                clone_membership["duplicate_roster_players"],
                sort_keys=True,
            )
        ),
    )
    check(
        "clone_pickle_round_trip_preserves_memberships",
        reloaded_membership["free_agent_ids"]
        == clone_membership["free_agent_ids"]
        and reloaded_membership["roster_owner"]
        == clone_membership["roster_owner"],
        (
            f"serialized_bytes={len(clone_bytes)}"
        ),
    )
    check(
        "live_state_object_unchanged",
        live_state_digest_before == live_state_digest_after,
        live_state_digest_after,
    )
    check(
        "loaded_checkpoint_object_unchanged",
        live_checkpoint_object_digest_before
        == live_checkpoint_object_digest_after,
        live_checkpoint_object_digest_after,
    )
    check(
        "durable_checkpoint_file_unchanged",
        checkpoint_before == checkpoint_after,
        checkpoint_after,
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        overlay_after or "<absent>",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Offseason Contract-State Reconciliation Dry Run V1 failed: "
            + ", ".join(failed)
        )

    team_delta_rows = []
    all_team_codes = sorted(
        set(live_membership["team_roster_counts"])
        | set(clone_membership["team_roster_counts"])
    )
    for team_code in all_team_codes:
        before = int(
            live_membership["team_roster_counts"].get(team_code, 0)
        )
        after = int(
            clone_membership["team_roster_counts"].get(team_code, 0)
        )
        if before != after:
            team_delta_rows.append({
                "team_abbreviation": team_code,
                "roster_count_before": before,
                "roster_count_after": after,
                "delta": after - before,
            })

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_offseason_contract_state_reconciliation_dry_run_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(
        prefix="fa_contract_reconcile_"
    ) as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "contract_state_reconciliation_actions.csv",
            reconciliation_rows,
        )
        write_csv(
            export / "team_roster_count_deltas.csv",
            team_delta_rows,
        )
        write_csv(
            export / "contract_state_reconciliation_checks.csv",
            checks,
        )
        write_csv(
            export / "manual_contract_quarantine.csv",
            [
                {
                    "player_id": pid(row.get("player_id")),
                    "player_name": clean(row.get("player_name")),
                    "prior_team": team(row.get("prior_team")),
                    "lifecycle_state": clean(
                        row.get("contract_lifecycle_state")
                    ),
                    "market_available": False,
                    "roster_assignment_applied": False,
                    "reason": (
                        "Contract source is unresolved. Player is quarantined "
                        "from the simulated market without guessing team status."
                    ),
                }
                for row in manual_rows
            ],
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "live_free_agent_count_before": (
                live_membership["free_agent_count"]
            ),
            "clone_free_agent_count_after": (
                clone_membership["free_agent_count"]
            ),
            "corrected_market_count": len(market_ids),
            "contract_attached_or_pending_count": len(attached_ids),
            "manual_contract_quarantine_count": len(manual_ids),
            "restored_to_prior_roster_count": len(attached_ids),
            "team_roster_delta_count": len(team_delta_rows),
            "active_roster_status_inferred_from_live_state": active_status,
            "clone_serialized_byte_count": len(clone_bytes),
            "clone_serialization_round_trip_passed": True,
            "contract_objects_mutated": 0,
            "live_state_mutated": False,
            "durable_checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "passed": True,
            "failed_strict_checks": [],
            "critical_finding": (
                "The durable checkpoint still contains the provisional "
                "187-player free-agent collection. A lifecycle-aware "
                "reconciliation layer must run before Team Option commits "
                "or free-agency market execution."
            ),
            "next_slice": (
                "Build a guarded lifecycle-state overlay / transaction layer "
                "that makes the corrected 132-player availability visible to "
                "free-agency UI and CPU execution, restores the 51 known "
                "contract-attached players, and quarantines the 4 manual rows. "
                "Only after that foundation passes should the 12 CPU Team "
                "Option decisions be applied."
            ),
        }

        (
            export / "contract_state_reconciliation_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """2026 OFFSEASON CONTRACT-STATE RECONCILIATION DRY RUN V1
========================================================

Critical upstream finding
-------------------------
The durable checkpoint still has the old provisional 187-player free-agent
collection. Contract lifecycle research later proved that the April-12 branch
state should instead partition those 187 players as:

- 132 corrected free-agent market candidates
- 51 players still attached to their prior team
  - 48 pending option / non-guarantee decisions
  - 3 already under contract for 2026-27
- 4 unresolved contract-source cases that must be quarantined from the market

Therefore Team Option commits cannot safely be applied directly to the current
checkpoint. The market state itself must first become lifecycle-aware.

What this dry run does
----------------------
On a deep-copied checkpoint only:

1. Replaces the provisional 187-player free-agent collection with exactly the
   corrected 132-player market.
2. Restores all 51 known contract-attached / contract-pending players to their
   proven prior-team rosters.
3. Preserves every existing player ContractState object without mutation.
4. Removes all four unresolved contract-source players from market availability
   but does not guess a roster assignment for them.
5. Verifies no player appears in both a roster and free agency.
6. Verifies no duplicate roster membership exists.
7. Pickle-serializes and reloads the cloned checkpoint and confirms membership
   identity survives the round trip.
8. Re-checks the live object, durable checkpoint file hash, and rights overlay.

This package DOES NOT save the cloned checkpoint.

Why the four manual players are not placed on rosters
------------------------------------------------------
Their contract evidence is unresolved. Assigning them to a team would be a new
unsupported fact. Quarantining them from free-agency offers is safe; team
assignment waits for evidence.

Next
----
Use this audit to build the actual lifecycle availability layer / guarded
reconciliation transaction. Only then should the Team Option transaction layer
be allowed to commit exercise/decline decisions.

READ ONLY / COPY ON WRITE ONLY.
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

    # One final durable-state safety check after the audit ZIP itself exists.
    if object_digest(live_state) != live_state_digest_before:
        raise RuntimeError(
            "Live state changed after reconciliation audit export."
        )
    if sha256_file(checkpoint_file) != checkpoint_before:
        raise RuntimeError(
            "Durable checkpoint changed after reconciliation audit export."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed after reconciliation audit export."
        )

    print("", flush=True)
    print("=" * 126, flush=True)
    print(
        "2026 OFFSEASON CONTRACT-STATE RECONCILIATION DRY RUN V1 PASSED",
        flush=True,
    )
    print("=" * 126, flush=True)
    print(
        f"Live provisional free agents:  "
        f"{live_membership['free_agent_count']}",
        flush=True,
    )
    print(
        f"Clone corrected free agents:   "
        f"{clone_membership['free_agent_count']}",
        flush=True,
    )
    print(
        f"Restored to prior rosters:     "
        f"{len(attached_ids)}",
        flush=True,
    )
    print(
        f"Manual market quarantine:      "
        f"{len(manual_ids)}",
        flush=True,
    )
    print(
        f"Contract objects changed:      0",
        flush=True,
    )
    print(
        f"Clone pickle round trip:       PASS",
        flush=True,
    )
    print(
        "Live state mutation:           NOT PERFORMED",
        flush=True,
    )
    print(
        "Checkpoint write:              NOT PERFORMED",
        flush=True,
    )
    print(
        "Rights overlay write:          NOT PERFORMED",
        flush=True,
    )
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
