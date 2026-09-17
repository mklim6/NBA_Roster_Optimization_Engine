from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


def main() -> int:
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        print("NO DURABLE FRANCHISE CHECKPOINT FOUND")
        return 1
    state = checkpoint.simulation_state
    floor = int(getattr(state.settings, "minimum_game_players", 8) or 8)
    teams = []
    for abbr, team_state in sorted((getattr(state, "teams", {}) or {}).items()):
        roster = tuple(getattr(team_state, "roster_player_ids", ()) or ())
        pending = 0
        for pid in roster:
            player = (getattr(state, "players", {}) or {}).get(pid)
            contract = getattr(player, "contract", None) if player is not None else None
            if str(getattr(contract, "status", "") or "").strip().lower() == "rookie_scale_pending":
                pending += 1
        teams.append((str(abbr), len(roster), pending))

    print("FRANCHISE NEXT-SEASON ROSTER-FLOOR DIAGNOSTIC V1")
    print("season:", getattr(state.settings, "season_label", ""))
    print("phase:", getattr(getattr(state, "phase", None), "value", getattr(state, "phase", "")))
    print("minimum_game_players:", floor)
    print("teams below game-ready floor:")
    deficits = [row for row in teams if row[1] < floor]
    if not deficits:
        print("  NONE")
    else:
        for abbr, count, pending in deficits:
            print(f"  {abbr}: roster={count}, deficit={floor-count}, pending_rookies={pending}")
    print("\nlowest rosters:")
    for abbr, count, pending in sorted(teams, key=lambda row: (row[1], row[0]))[:12]:
        print(f"  {abbr}: roster={count}, pending_rookies={pending}")
    print("\nREAD-ONLY: checkpoint was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
