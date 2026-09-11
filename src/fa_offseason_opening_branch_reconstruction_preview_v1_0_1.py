from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "fa-offseason-opening-branch-reconstruction-preview-v1.0.1-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
CBA_OFFSEASON_AGGREGATE_MAX = 21

TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}
TEAM_BY_NORMALIZED_NAME = {
    None: None,
    **{
        " ".join(
            re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        ): code
        for code, name in TEAM_NAMES.items()
    },
}

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
    return list(csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"))))


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


def current_owners(state: Any) -> dict[str, str]:
    result = {}
    for team_code, team_state in (getattr(state, "teams", {}) or {}).items():
        for raw_id in (getattr(team_state, "roster_player_ids", ()) or ()):
            result[pid(raw_id)] = team(team_code)
    for raw_id in (getattr(state, "free_agent_player_ids", ()) or ()):
        result.setdefault(pid(raw_id), "FA")
    return result


def parse_source_team(description: str) -> str:
    text = clean(description)
    if " from " not in text.lower():
        return ""
    after = re.split(r"\s+from\s+", text, flags=re.IGNORECASE, maxsplit=1)[1]
    after_norm = normalize(after)
    # Prefer the longest team-name match to avoid "LA" style collisions.
    matches = []
    for code, name in TEAM_NAMES.items():
        n = normalize(name)
        if after_norm.startswith(n) or n in after_norm:
            matches.append((len(n), code))
    return max(matches)[1] if matches else ""


def movement_owner_after(row: Mapping[str, Any]) -> str:
    tx_type = clean(row.get("transaction_type")).lower()
    scoped_team = team(row.get("team_abbreviation"))
    if tx_type in {"signing", "trade", "awardonwaivers", "contractconverted"}:
        return scoped_team
    if tx_type == "waive":
        return "FA"
    return ""


def pre_split_owner_from_history(
    player_id: str,
    all_rows_by_player: Mapping[str, list[dict[str, str]]],
) -> tuple[str, str]:
    rows = [
        row
        for row in all_rows_by_player.get(player_id, [])
        if clean(row.get("transaction_date"))
        and date.fromisoformat(row["transaction_date"]) <= SIMULATION_SPLIT_DATE
    ]
    if not rows:
        return "", "no_pre_split_movement_history"

    rows = sorted(rows, key=lambda r: r["transaction_date"])
    latest = rows[-1]
    owner = movement_owner_after(latest)

    if owner:
        return owner, (
            f"latest_pre_split_{clean(latest.get('transaction_type')).lower()}"
            f"_{latest['transaction_date']}"
        )
    return "", "latest_pre_split_event_not_membership_resolving"


def lifecycle_branch_hint(row: Mapping[str, Any]) -> tuple[str, str]:
    state = clean(row.get("contract_lifecycle_state"))
    prior_team = team(row.get("prior_team"))

    # These two categories were already free agents at the April-12 branch.
    if state in {
        "free_agent_waiver_terminated",
        "free_agent_ten_day",
    }:
        return "FA", state

    # All other resolved lifecycle states with a prior team imply the player
    # was attached to that team at the branch date, even if he later becomes a
    # market free agent at the offseason opening.
    if prior_team and not state.startswith("manual_review"):
        return prior_team, f"lifecycle_prior_team:{state}"

    return "", "no_safe_lifecycle_branch_hint"


def earliest_post_split_before_owner(
    player_id: str,
    post_rows_by_player: Mapping[str, list[dict[str, str]]],
    all_rows_by_player: Mapping[str, list[dict[str, str]]],
    lifecycle_by_id: Mapping[str, dict[str, str]],
) -> tuple[str, str, str]:
    rows = post_rows_by_player.get(player_id, [])
    if not rows:
        return "", "no_post_split_movement", ""

    rows = sorted(rows, key=lambda r: r["transaction_date"])
    earliest = rows[0]
    tx_type = clean(earliest.get("transaction_type")).lower()
    scoped_team = team(earliest.get("team_abbreviation"))
    desc = clean(earliest.get("description"))

    if tx_type == "trade":
        source = parse_source_team(desc)
        if source:
            return source, "reverse_earliest_post_split_trade", desc
        return "", "trade_source_team_unresolved", desc

    if tx_type == "waive":
        if scoped_team:
            return scoped_team, "reverse_earliest_post_split_waive", desc
        return "", "waive_team_unresolved", desc

    if tx_type == "awardonwaivers":
        pre_owner, evidence = pre_split_owner_from_history(
            player_id,
            all_rows_by_player,
        )
        if pre_owner:
            return pre_owner, f"claim_pre_split_history:{evidence}", desc
        hint, hint_evidence = lifecycle_branch_hint(
            lifecycle_by_id.get(player_id, {})
        )
        if hint:
            return hint, f"claim_lifecycle_hint:{hint_evidence}", desc
        return "", "waiver_claim_pre_split_owner_unresolved", desc

    if tx_type == "signing":
        low = desc.lower()
        if "re-signed" in low or "re signed" in low or "extension" in low:
            if scoped_team:
                return scoped_team, "same_team_resigning_or_extension_no_membership_change", desc

        pre_owner, evidence = pre_split_owner_from_history(
            player_id,
            all_rows_by_player,
        )
        if pre_owner:
            return pre_owner, f"new_signing_pre_split_history:{evidence}", desc

        hint, hint_evidence = lifecycle_branch_hint(
            lifecycle_by_id.get(player_id, {})
        )
        if hint:
            return hint, f"new_signing_lifecycle_hint:{hint_evidence}", desc

        # If a post-split player has no pre-split movement history at all, he
        # may be a draft/international/new-NBA entrant. Do not guess that from
        # the absence alone. Quarantine for reconstruction review.
        return "", "new_signing_pre_split_owner_unresolved", desc

    return "", "unsupported_earliest_post_split_transaction_type", desc


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

    provenance_zip = find_latest(
        root,
        "fa_post_split_roster_provenance_audit_v1_0_2_2026-27_*.zip",
    )
    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    corrected_rfa_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )

    with zipfile.ZipFile(provenance_zip) as archive:
        provenance_summary = read_json_member(
            archive,
            "roster_provenance_summary.json",
        )
        movement_all = read_csv_member(
            archive,
            "player_movement_rows_canonical.csv",
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

    with zipfile.ZipFile(corrected_rfa_zip) as archive:
        corrected_summary = read_json_member(
            archive,
            "corrected_rfa_qo_summary.json",
        )
        corrected_rows = read_csv_member(
            archive,
            "corrected_rfa_qo_universe_all.csv",
        )

    lifecycle_by_id = {
        pid(row.get("player_id")): row for row in lifecycle_rows
    }
    market_ids = {
        pid(row.get("player_id")) for row in corrected_rows
    }
    attached_rows = [
        row for row in lifecycle_rows
        if (
            clean(row.get("contract_lifecycle_state")).startswith(PENDING_PREFIX)
            or clean(row.get("contract_lifecycle_state")).startswith(UNDER_CONTRACT_PREFIX)
        )
    ]
    attached_ids = {
        pid(row.get("player_id")) for row in attached_rows
    }
    manual_rows = [
        row for row in lifecycle_rows
        if clean(row.get("contract_lifecycle_state")).startswith("manual_review")
    ]
    manual_ids = {
        pid(row.get("player_id")) for row in manual_rows
    }

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_module
        checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
        checkpoint_hash = sha256_file(checkpoint_path)
        checkpoint = checkpoint_module.load_franchise_checkpoint()
    except Exception as exc:
        raise RuntimeError("Could not load canonical franchise checkpoint.") from exc

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Checkpoint changed unexpectedly before branch reconstruction.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)
    players = getattr(state, "players", {}) or {}
    current_owner = current_owners(state)

    all_rows_by_player: dict[str, list[dict[str, str]]] = defaultdict(list)
    post_rows_by_player: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in movement_all:
        player_id = pid(row.get("player_id"))
        if player_id and player_id in players and clean(row.get("transaction_date")):
            all_rows_by_player[player_id].append(row)

    for row in movement_post:
        player_id = pid(row.get("player_id"))
        if player_id and player_id in players and clean(row.get("transaction_date")):
            post_rows_by_player[player_id].append(row)

    # First reconstruct branch-date ownership for every checkpoint player.
    branch_owner: dict[str, str] = {}
    branch_evidence: dict[str, str] = {}
    branch_trigger: dict[str, str] = {}
    unresolved_ids = set()

    for raw_id, player in players.items():
        player_id = pid(raw_id)
        current = current_owner.get(player_id, "UNASSIGNED")

        hint, hint_evidence = lifecycle_branch_hint(
            lifecycle_by_id.get(player_id, {})
        )
        if hint:
            branch_owner[player_id] = hint
            branch_evidence[player_id] = hint_evidence
            branch_trigger[player_id] = "lifecycle"
            continue

        owner, evidence, trigger = earliest_post_split_before_owner(
            player_id,
            post_rows_by_player,
            all_rows_by_player,
            lifecycle_by_id,
        )
        if owner:
            branch_owner[player_id] = owner
            branch_evidence[player_id] = evidence
            branch_trigger[player_id] = trigger
            continue

        # No post-split membership event and no lifecycle correction means the
        # current owner is safe to carry backward.
        if not post_rows_by_player.get(player_id):
            branch_owner[player_id] = current
            branch_evidence[player_id] = "no_post_split_movement_current_owner_preserved"
            branch_trigger[player_id] = ""
            continue

        branch_owner[player_id] = "QUARANTINE"
        branch_evidence[player_id] = evidence
        branch_trigger[player_id] = trigger
        unresolved_ids.add(player_id)

    # Now transition branch ownership into the corrected offseason-opening
    # contract lifecycle. Market players become FA. The 51 attached players
    # remain on proven prior teams. Four unresolved contract-source rows are
    # quarantined. This is the phase we actually want the simulator to enter.
    offseason_owner = dict(branch_owner)
    offseason_evidence = {
        player_id: f"branch:{branch_evidence[player_id]}"
        for player_id in branch_owner
    }

    for player_id in market_ids:
        offseason_owner[player_id] = "FA"
        offseason_evidence[player_id] = "corrected_2026_free_agent_market_v2"

    for row in attached_rows:
        player_id = pid(row.get("player_id"))
        prior_team = team(row.get("prior_team"))
        offseason_owner[player_id] = prior_team
        offseason_evidence[player_id] = (
            "contract_lifecycle_attached:"
            + clean(row.get("contract_lifecycle_state"))
        )

    for player_id in manual_ids:
        offseason_owner[player_id] = "QUARANTINE"
        offseason_evidence[player_id] = "manual_contract_source_quarantine"

    player_rows = []
    changed_rows = []

    for raw_id, player in players.items():
        player_id = pid(raw_id)
        current = current_owner.get(player_id, "UNASSIGNED")
        branch = branch_owner.get(player_id, "UNASSIGNED")
        opening = offseason_owner.get(player_id, "UNASSIGNED")

        row = {
            "player_id": player_id,
            "player_name": player_name(player, player_id),
            "current_checkpoint_owner": current,
            "reconstructed_branch_owner": branch,
            "branch_evidence": branch_evidence.get(player_id, ""),
            "branch_trigger_transaction": branch_trigger.get(player_id, ""),
            "offseason_opening_owner": opening,
            "offseason_opening_evidence": offseason_evidence.get(player_id, ""),
            "has_post_split_movement": bool(post_rows_by_player.get(player_id)),
            "post_split_movement_count": len(post_rows_by_player.get(player_id, [])),
            "lifecycle_state": clean(
                lifecycle_by_id.get(player_id, {}).get("contract_lifecycle_state")
            ),
            "lifecycle_prior_team": team(
                lifecycle_by_id.get(player_id, {}).get("prior_team")
            ),
            "offseason_owner_changed_from_current_checkpoint": opening != current,
        }
        player_rows.append(row)
        if opening != current:
            changed_rows.append(row)

    roster_counts = Counter(
        owner
        for owner in offseason_owner.values()
        if owner in TEAM_NAMES
    )
    branch_roster_counts = Counter(
        owner
        for owner in branch_owner.values()
        if owner in TEAM_NAMES
    )

    team_rows = []
    for code in sorted(TEAM_NAMES):
        team_rows.append({
            "team_abbreviation": code,
            "current_checkpoint_roster_count": sum(
                1 for owner in current_owner.values() if owner == code
            ),
            "reconstructed_branch_roster_count": branch_roster_counts.get(code, 0),
            "offseason_opening_roster_count": roster_counts.get(code, 0),
            "offseason_opening_exceeds_cba_21": roster_counts.get(code, 0) > CBA_OFFSEASON_AGGREGATE_MAX,
        })

    # Known-case branch targets from official post-split movement history.
    known_targets = {
        "Jerami Grant": "POR",
        "D'Angelo Russell": "WAS",
        "AJ Johnson": "DAL",
        "Isaiah Stewart": "DET",
        "Quinten Post": "GSW",
        "Ja Morant": "MEM",
        "Moussa Cisse": "DAL",
        "Spencer Jones": "DEN",
    }
    rows_by_name = {
        row["player_name"]: row for row in player_rows
    }

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

    checks = []

    def check(check_id: str, passed: bool, detail: str, severity: str = "strict") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 OFFSEASON OPENING BRANCH RECONSTRUCTION PREVIEW V1.0.1", flush=True)
    print("=" * 128, flush=True)
    print(f"Checkpoint: {checkpoint_hash}", flush=True)
    print(f"Post-split movement rows: {len(movement_post)}", flush=True)
    print(f"Corrected market players: {len(market_ids)}", flush=True)
    print(f"Contract-attached players: {len(attached_ids)}", flush=True)
    print(f"Manual contract quarantine: {len(manual_ids)}", flush=True)
    print("COPY-ON-WRITE / READ-ONLY. No durable state is written.", flush=True)
    print("", flush=True)

    print("Running strict reconstruction checks...", flush=True)

    check(
        "upstream_provenance_audit_passed",
        bool(provenance_summary.get("passed")),
        "V1.0.2 movement provenance audit passed.",
    )
    check(
        "upstream_lifecycle_audit_passed",
        bool(lifecycle_summary.get("passed")),
        "Contract lifecycle audit passed.",
    )
    check(
        "upstream_corrected_market_passed",
        bool(corrected_summary.get("passed")),
        "Corrected RFA/QO market preview passed.",
    )
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_hash == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash,
    )
    check(
        "exact_279_post_split_movement_rows_preserved",
        len(movement_post) == 279,
        f"rows={len(movement_post)}",
    )
    check(
        "lifecycle_partition_is_132_51_4",
        len(market_ids) == 132
        and len(attached_ids) == 51
        and len(manual_ids) == 4,
        f"market={len(market_ids)} attached={len(attached_ids)} manual={len(manual_ids)}",
    )

    for name, expected in known_targets.items():
        actual = clean(rows_by_name.get(name, {}).get("reconstructed_branch_owner"))
        slug = re.sub(r"[^a-z0-9]+", "_", normalize(name)).strip("_")
        check(
            f"known_branch_owner_{slug}",
            actual == expected,
            f"expected={expected}; actual={actual}",
        )

    check(
        "offseason_market_is_exactly_132",
        sum(1 for owner in offseason_owner.values() if owner == "FA") == 132,
        f"fa={sum(1 for owner in offseason_owner.values() if owner == 'FA')}",
    )
    check(
        "all_51_attached_players_on_proven_prior_teams",
        all(
            offseason_owner.get(pid(row.get("player_id")))
            == team(row.get("prior_team"))
            for row in attached_rows
        ),
        f"attached={len(attached_rows)}",
    )
    check(
        "all_4_manual_contract_rows_quarantined",
        all(offseason_owner.get(player_id) == "QUARANTINE" for player_id in manual_ids),
        f"manual={len(manual_ids)}",
    )
    check(
        "no_live_state_mutation",
        state_digest_before == state_digest_after,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash == checkpoint_after,
        checkpoint_after,
    )

    over_21 = [
        row["team_abbreviation"]
        for row in team_rows
        if row["offseason_opening_exceeds_cba_21"]
    ]
    check(
        "offseason_opening_raw_rosters_fit_cba_21",
        not over_21,
        "over_21=" + ("|".join(over_21) if over_21 else "<none>"),
        severity="capacity",
    )
    check(
        "branch_owner_reconstruction_coverage",
        not unresolved_ids,
        (
            "unresolved="
            + ("|".join(sorted(unresolved_ids)) if unresolved_ids else "<none>")
        ),
        severity="coverage",
    )

    failed = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Offseason Opening Branch Reconstruction Preview V1.0.1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_offseason_opening_branch_reconstruction_preview_v1_0_1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_branch_reconstruct_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "branch_reconstruction_all_players.csv", player_rows)
        write_csv(export / "branch_reconstruction_changed_players.csv", changed_rows)
        write_csv(export / "branch_reconstruction_team_counts.csv", team_rows)
        write_csv(
            export / "branch_reconstruction_unresolved_players.csv",
            [row for row in player_rows if row["player_id"] in unresolved_ids],
        )
        write_csv(export / "branch_reconstruction_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "checkpoint_sha256": checkpoint_hash,
            "checkpoint_player_count": len(players),
            "post_split_movement_row_count": len(movement_post),
            "players_with_post_split_movement": len(post_rows_by_player),
            "players_changed_vs_current_checkpoint": len(changed_rows),
            "reconstruction_unresolved_player_count": len(unresolved_ids),
            "reconstruction_unresolved_player_ids": sorted(unresolved_ids),
            "branch_roster_counts_by_team": dict(sorted(branch_roster_counts.items())),
            "offseason_opening_roster_counts_by_team": dict(sorted(roster_counts.items())),
            "offseason_opening_free_agent_count": sum(
                1 for owner in offseason_owner.values() if owner == "FA"
            ),
            "offseason_opening_contract_attached_count": len(attached_ids),
            "offseason_opening_manual_quarantine_count": len(manual_ids),
            "teams_over_cba_21_raw": over_21,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed_strict_checks": True,
            "next_slice_if_coverage_and_capacity_pass": (
                "Build a copy-on-write checkpoint reconstruction dry run that "
                "materializes the previewed owner map, validates roster/free-agent "
                "membership, and hydrates the 51 attached ContractState records "
                "from lifecycle evidence before any durable write."
            ),
            "next_slice_if_unresolved_or_over_21": (
                "Resolve only the exported unresolved player provenance or roster "
                "capacity conflicts. Do not mutate the durable checkpoint."
            ),
        }

        (export / "branch_reconstruction_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 OFFSEASON OPENING BRANCH RECONSTRUCTION PREVIEW V1
======================================================

Purpose
-------
Reconstruct a coherent counterfactual 2026 offseason opening state without
stacking real-world post-April-12 roster moves on top of simulator decisions.

The preview has two conceptual stages:

1. Reconstruct branch ownership immediately before post-split real-world
   movement:
   - reverse trade arrivals to the sending team
   - reverse waives to the waiving team
   - use pre-split Player Movement history for later new signings
   - keep same-team re-signings/extensions as membership no-ops
   - use contract-lifecycle prior-team evidence where available
   - quarantine anything that still cannot be proven

2. Transition that branch state into the simulator's corrected offseason
   opening lifecycle:
   - 132 corrected market players -> free agent
   - 51 contract-attached/pending players -> proven prior team
   - 4 unresolved contract-source rows -> quarantine

This preserves the intended sequence:
April-12 branch evidence -> offseason contract lifecycle -> simulator decisions.

It does NOT write the checkpoint.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 OFFSEASON OPENING BRANCH RECONSTRUCTION PREVIEW V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Players changed vs current checkpoint: {len(changed_rows)}", flush=True)
    print(f"Unresolved branch owners:              {len(unresolved_ids)}", flush=True)
    print("Known Memphis chain:                   PASS", flush=True)
    print("Offseason-opening free agents:         132", flush=True)
    print("Contract-attached players:             51", flush=True)
    print("Manual contract quarantine:            4", flush=True)
    print(
        "Teams raw >21 at opening:             "
        + (", ".join(over_21) if over_21 else "NONE"),
        flush=True,
    )
    print("State mutation:                         NOT PERFORMED", flush=True)
    print("Checkpoint write:                      NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
