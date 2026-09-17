from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_season_transition_v1 import next_season_label
from franchise_career_lifecycle_v1 import build_retirement_plan


def main() -> int:
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        print("NO DURABLE FRANCHISE CHECKPOINT FOUND")
        return 1

    state = checkpoint.simulation_state
    source = str(state.settings.season_label)
    target = next_season_label(source)
    floor = int(getattr(state.settings, "minimum_game_players", 8) or 8)
    plan = build_retirement_plan(state, target_season=target)

    counts = {
        str(team): len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        for team, team_state in state.teams.items()
    }
    retiring_by_team = {}
    for player_id in plan.retirement_player_ids:
        player = state.players.get(player_id)
        team = str(getattr(player, "team_abbreviation", "") or "").strip().upper() if player else ""
        if team in counts:
            retiring_by_team.setdefault(team, []).append(
                str(getattr(player, "player_name", player_id))
            )

    projected = {
        team: counts[team] - len(retiring_by_team.get(team, []))
        for team in counts
    }
    deficits = {
        team: (count, floor - count, tuple(retiring_by_team.get(team, [])))
        for team, count in projected.items()
        if count < floor
    }

    print("FRANCHISE POST-RETIREMENT ROSTER-FLOOR DIAGNOSTIC V2")
    print("source season:", source)
    print("target season:", target)
    print("minimum_game_players:", floor)
    print("projected retirements:", len(plan.retirement_player_ids))
    print("projected teams below floor after retirement:")
    if not deficits:
        print("  NONE")
    else:
        for team, (count, deficit, names) in sorted(deficits.items()):
            print(
                f"  {team}: projected_roster={count}, deficit={deficit}, "
                f"retiring={', '.join(names) if names else 'unknown'}"
            )
    print("\nREAD-ONLY: checkpoint was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
