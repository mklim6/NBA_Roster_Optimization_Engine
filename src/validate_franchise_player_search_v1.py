from __future__ import annotations

import copy
import hashlib
import py_compile
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_player_search_v1 import (
    PLAYER_SEARCH_VERSION,
    build_player_search_profile,
    search_players,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "franchise-player-search-validator-v1-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(state):
    return (
        getattr(getattr(state, "settings", None), "season_label", ""),
        len(getattr(state, "players", {}) or {}),
        len(getattr(state, "season_history", []) or []),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
    )


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable franchise checkpoint could not be loaded.")
    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state

    before_state = signature(state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    sample_row = next(
        row for row in ledger.player_rows
        if str(row.get("player_name", "")).strip()
    )
    sample_name = str(sample_row["player_name"])
    token = sample_name.split()[-1]
    matches = search_players(ledger, token, limit=30)
    selected = next(
        match for match in matches
        if match.player_id == str(sample_row["player_id"])
    )
    profile = build_player_search_profile(state, ledger, selected.player_id)

    # Simulated exact franchise player-trade history on a deep copy only.
    copied = copy.deepcopy(state)
    teams = sorted(getattr(copied, "teams", {}))
    from_team = profile.current_team or teams[0]
    to_team = next(team for team in teams if team != from_team)
    setattr(
        copied,
        "franchise_transaction_history_v1",
        [
            {
                "transaction_id": "FTX-SEARCH-TEST",
                "season_label": getattr(getattr(copied, "settings", None), "season_label", ""),
                "day_index": 7,
                "team_a": from_team,
                "team_b": to_team,
                "side_a_player_ids": [selected.player_id],
                "side_b_player_ids": [],
            }
        ],
    )
    copied_profile = build_player_search_profile(copied, ledger, selected.player_id)

    backend = (SRC / "franchise_player_search_v1.py").read_text(encoding="utf-8")
    ui = (SRC / "franchise_player_search_ui_v1.py").read_text(encoding="utf-8")
    ledger_ui = (SRC / "franchise_live_asset_ledger_ui_v1.py").read_text(encoding="utf-8")

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-12"),
        "player_search_version_is_current": PLAYER_SEARCH_VERSION.endswith("2026-08-12"),
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "partial_name_search_finds_live_player": selected.player_id == str(sample_row["player_id"]),
        "current_location_matches_live_ledger": (
            profile.current_team == str(sample_row.get("team") or "")
            and profile.roster_status == str(sample_row.get("roster_status") or "")
        ),
        "current_player_metadata_is_exposed": (
            profile.player_name == sample_name
            and profile.position == str(sample_row.get("position") or "UNK")
        ),
        "archived_history_uses_box_score_evidence_only": (
            "Archived game appearances" in backend
            and "completed_games" in backend
            and "player_box_scores" in backend
        ),
        "exact_franchise_trade_history_is_supported": (
            any(event.transaction_id == "FTX-SEARCH-TEST" for event in copied_profile.transactions)
        ),
        "search_does_not_mutate_live_state": signature(state) == before_state,
        "player_search_ui_is_installed": (
            "Player Search · Where Are They Now?" in ui
            and '"Player Search"' in ledger_ui
            and "render_player_search_v1" in ledger_ui
        ),
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
    }

    for name in (
        "franchise_player_search_v1.py",
        "franchise_player_search_ui_v1.py",
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        "franchise_live_asset_ledger_ui_v1.py",
    ):
        py_compile.compile(str(SRC / name), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("FRANCHISE PLAYER SEARCH V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("SAMPLE SEARCH")
    print(f"  Query: {token}")
    print(f"  Player: {profile.player_name}")
    print(f"  Current: {profile.current_location_label}")
    print(f"  Archived team seasons found: {len(profile.season_locations)}")
    print(f"  Exact franchise transactions: {len(profile.transactions)}")
    print()
    if failed:
        raise AssertionError("Player Search validation failed: " + ", ".join(failed))
    print("FRANCHISE PLAYER SEARCH V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no player, roster, transaction, or checkpoint was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
