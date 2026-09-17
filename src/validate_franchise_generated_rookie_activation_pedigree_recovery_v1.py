from __future__ import annotations

import ast
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path


def _load(path: Path):
    # Stub only the salary schedule dependency needed for importing the module.
    bridge = types.ModuleType("franchise_post_draft_first_round_pick_hold_bridge_v1")
    bridge.rookie_scale_schedule = lambda target_season, draft_year: []
    sys.modules["franchise_post_draft_first_round_pick_hold_bridge_v1"] = bridge

    spec = importlib.util.spec_from_file_location("generated_rookie_activation_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load generated rookie activation module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Contract:
    status: str
    salary: float | None
    years_remaining: int
    option_type: str
    guaranteed: bool


class Player:
    pass


class State:
    pass


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_generated_rookie_contract_activation_v1.py"
    source = path.read_text(encoding="utf-8")
    module = _load(path)

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["recovery_marker_present"] = "GENERATED_ROOKIE_ACTIVATION_PEDIGREE_RECOVERY_V1" in source
    checks["durable_draft_archive_used"] = "franchise_draft_history_v1" in source
    checks["activation_calls_recovery"] = "_recover_generated_rookie_pedigree(" in source

    state = State()
    player = Player()
    player.player_id = "DRAFT-2027-045"
    player.player_name = "Test Rookie"
    player.team_abbreviation = "DEN"
    player.generated_prospect = True
    player.rookie_season = "2027-28"
    player.draft_year = None
    player.draft_round = None
    player.draft_pick = None
    player.drafted_by = ""
    player.synthetic = True
    player.roster_status = "inactive"
    player.contract = Contract(
        status="rookie_scale_pending",
        salary=None,
        years_remaining=4,
        option_type="rookie_scale",
        guaranteed=True,
    )
    state.players = {player.player_id: player}
    state.franchise_draft_history_v1 = [
        {
            "draft_year": 2027,
            "target_season": "2027-28",
            "draft_order": [
                {
                    "prospect_id": player.player_id,
                    "round": 2,
                    "overall_pick": 45,
                    "round_pick": 15,
                    "owner_team": "DEN",
                }
            ],
        }
    ]

    matched = module.activate_generated_rookie_contracts(
        state,
        "2027-28",
    )

    checks["synthetic_missing_pedigree_activates"] = matched == 1
    checks["draft_year_recovered"] = player.draft_year == 2027
    checks["draft_round_recovered"] = player.draft_round == 2
    checks["draft_pick_recovered"] = player.draft_pick == 45
    checks["draft_round_pick_recovered"] = player.draft_round_pick == 15
    checks["drafted_by_recovered"] = player.drafted_by == "DEN"
    checks["contract_activated"] = (
        player.contract.status == "under_contract"
        and player.contract.salary is not None
        and player.contract.salary > 0
    )
    checks["rookie_eligible_after_activation"] = bool(player.rookie_eligible)
    checks["synthetic_flag_cleared"] = player.synthetic is False

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE GENERATED ROOKIE ACTIVATION PEDIGREE RECOVERY V1 VALIDATOR FAILED")
        return 1

    print("FRANCHISE GENERATED ROOKIE ACTIVATION PEDIGREE RECOVERY V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
