from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_preseason_roster_floor_live_v1 as api


VERSION = "franchise-preseason-roster-floor-live-validator-v1.0-2026-09-15"


def _checkpoint(*, chi: int = 8, gsw: int = 7):
    state = SimpleNamespace(
        phase="offseason",
        settings=SimpleNamespace(minimum_game_players=8),
        teams={
            "CHI": SimpleNamespace(roster_player_ids=tuple(f"C{i}" for i in range(chi))),
            "GSW": SimpleNamespace(roster_player_ids=tuple(f"G{i}" for i in range(gsw))),
        },
    )
    return SimpleNamespace(simulation_state=state)


def main() -> int:
    checks: dict[str, bool] = {}
    original = {
        "load_franchise_checkpoint": api.load_franchise_checkpoint,
        "controlled_teams_from_durable_checkpoint": api.controlled_teams_from_durable_checkpoint,
        "checkpoint_boundary_fingerprint": api.checkpoint_boundary_fingerprint,
        "execute_cpu_free_agency_round_durably": api.execute_cpu_free_agency_round_durably,
    }
    try:
        holder = {"checkpoint": _checkpoint()}
        calls: list[int] = []
        api.load_franchise_checkpoint = lambda allow_backup=False: holder["checkpoint"]
        api.controlled_teams_from_durable_checkpoint = lambda checkpoint: ("CHI",)
        api.checkpoint_boundary_fingerprint = (
            lambda checkpoint: str(
                len(checkpoint.simulation_state.teams["GSW"].roster_player_ids)
            )
        )

        def execute_round(*, max_signings: int):
            calls.append(max_signings)
            team = holder["checkpoint"].simulation_state.teams["GSW"]
            team.roster_player_ids = tuple(team.roster_player_ids) + ("SIGNED",)
            signing = SimpleNamespace(player_name="Floor Rescue", team_abbreviation="GSW")
            return SimpleNamespace(
                committed_signing_count=1,
                signings=(signing,),
            )

        api.execute_cpu_free_agency_round_durably = execute_round
        result = api.complete_preseason_roster_floors_durably(
            expected_source_fingerprint="7"
        )
        checks["actual_deficit_drives_exact_round_size"] = calls == [1]
        checks["cpu_deficit_is_completed"] = (
            result.status == "completed"
            and result.initial_cpu_deficits == (("GSW", 7, 1),)
            and result.final_cpu_deficits == ()
            and result.committed_signing_count == 1
            and result.target_fingerprint == "8"
        )

        holder["checkpoint"] = _checkpoint(chi=7, gsw=8)
        calls.clear()
        try:
            api.complete_preseason_roster_floors_durably(
                expected_source_fingerprint="8"
            )
        except api.PreseasonRosterFloorError as exc:
            checks["controlled_team_underfill_remains_user_blocker"] = (
                "user-controlled roster" in str(exc).lower()
                and "CHI has 7" in str(exc)
                and not calls
            )
        else:
            checks["controlled_team_underfill_remains_user_blocker"] = False
    finally:
        for name, value in original.items():
            setattr(api, name, value)

    page = (ROOT / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")
    floor_pos = page.find("complete_preseason_roster_floors_durably(")
    trim_pos = page.find("commit_atomic_cpu_post_draft_trim_live(")
    transition_pos = page.find("advance_to_next_season_with_schedule(state)", floor_pos)
    checks["season_boundary_wires_floor_before_trim_and_transition"] = (
        0 <= floor_pos < trim_pos < transition_pos
    )
    checks["page_reloads_and_verifies_floor_checkpoint"] = (
        "_preseason_result.target_fingerprint" in page[floor_pos:trim_pos]
        and "allow_backup=False" in page[floor_pos:trim_pos]
    )

    failed = [name for name, passed in checks.items() if not passed]
    payload = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(payload, indent=2))
    if failed:
        raise AssertionError(
            "Preseason roster-floor validation failed: " + ", ".join(failed)
        )
    print("\nFRANCHISE PRESEASON ROSTER FLOOR LIVE V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
