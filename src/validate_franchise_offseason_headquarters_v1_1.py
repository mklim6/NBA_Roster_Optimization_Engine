from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(
        "ohq_v11_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load HQ module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _state(
    *,
    completed=1230,
    offseason_day=8,
    negotiations=2,
    signings=1,
    roster_count=14,
):
    players = {}
    roster = []
    for index in range(roster_count):
        player_id = f"P{index:02d}"
        roster.append(player_id)
        players[player_id] = SimpleNamespace(
            player_id=player_id,
            display_name=f"Player {index}",
            contract=SimpleNamespace(
                salary=10_000_000.0,
            ),
        )

    history = []
    for index in range(signings):
        history.append(
            {
                "player_id": (
                    roster[index % len(roster)]
                    if roster
                    else f"FA{index}"
                ),
                "team_abbreviation": "CHI",
                "annual_salary": 12_000_000.0,
                "years": 2,
            }
        )

    return SimpleNamespace(
        phase="offseason",
        settings=SimpleNamespace(
            season_label="2027-28",
        ),
        season_history=[],
        completed_games={
            f"G{index}": object()
            for index in range(completed)
        },
        free_agency_market_calendar_v1={
            "offseason_day": offseason_day,
            "active_markets": {
                f"M{index}": {}
                for index in range(negotiations)
            },
        },
        teams={
            "CHI": SimpleNamespace(
                roster_player_ids=tuple(roster),
            )
        },
        players=players,
        free_agent_player_ids=tuple(
            f"FA{index}"
            for index in range(40)
        ),
        free_agency_transaction_history=history,
        offseason_rfa_rights_qo_decisions_v1=[
            {
                "prior_team": "CHI",
                "player_id": "R1",
            }
        ],
        offseason_non_rfa_rights_decisions_v1=[
            {
                "prior_team": "CHI",
                "player_id": "R2",
            }
        ],
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = (
        root
        / "src"
        / "franchise_offseason_headquarters_v1.py"
    )
    source = module_path.read_text(
        encoding="utf-8"
    )
    module = _load(module_path)

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks.update(
        {
            "version_is_v1_1_or_later": (
                module.FRANCHISE_OFFSEASON_HEADQUARTERS_VERSION.startswith(
                    "franchise-offseason-headquarters-v1."
                )
                and "FRANCHISE_OFFSEASON_HEADQUARTERS_V1_1_FRONT_OFFICE_COMMAND"
                in source
            ),
            "front_office_marker_present": (
                "FRANCHISE_OFFSEASON_HEADQUARTERS_V1_1_FRONT_OFFICE_COMMAND"
                in source
            ),
            "decision_checklist_present": (
                "Decision checklist"
                in source
            ),
            "front_office_priorities_present": (
                "Front office priorities"
                in source
            ),
            "recent_activity_present": (
                "Recent team activity"
                in source
            ),
            "next_checkpoint_present": (
                "Next checkpoint"
                in source
            ),
            "continue_action_present": (
                "Continue Offseason ·"
                in source
            ),
            "financial_snapshot_present": (
                "def _ohq_v11_financial_snapshot("
                in source
            ),
            "future_pick_snapshot_present": (
                "def _ohq_v11_future_pick_count("
                in source
            ),
            "no_checkpoint_commit": (
                "save_franchise_checkpoint"
                not in source
                and "commit_franchise_checkpoint"
                not in source
            ),
        }
    )

    state = _state()
    model = module.build_offseason_headquarters_model_v1(
        state=state,
        active_team="CHI",
        postseason_state=SimpleNamespace(
            stage="complete"
        ),
        draft_state_payload={
            "phase": "draft_complete",
            "prospects": [
                {
                    "player_id": "D1",
                }
            ],
        },
        team_name_resolver=lambda _: "Chicago Bulls",
        blocking_count=1,
    )

    decisions = module._ohq_v11_decisions(model)
    priorities = module._ohq_v11_priorities(
        model=model,
        cap_space=20_000_000.0,
        future_pick_count=4,
    )
    recent = module._ohq_v11_recent_activity(
        state,
        "CHI",
    )
    checkpoint = module._ohq_v11_next_checkpoint(
        model.current_key
    )

    checks["eight_decisions"] = (
        len(decisions) == 8
    )
    checks["priorities_present"] = (
        len(priorities) >= 2
    )
    checks["recent_activity_populated"] = (
        bool(recent)
    )
    checks["live_offseason_routes_to_fa"] = (
        model.current_key
        == "free_agency"
    )
    checks[
        "next_checkpoint_is_roster_finalization"
    ] = (
        checkpoint[0]
        == "Roster Finalization"
    )

    opening = _state(
        completed=0,
        offseason_day=0,
        negotiations=0,
        signings=0,
    )
    opening_model = (
        module.build_offseason_headquarters_model_v1(
            state=opening,
            active_team="CHI",
            postseason_state=SimpleNamespace(
                stage="not_started"
            ),
            draft_state_payload={},
            team_name_resolver=lambda _: (
                "Chicago Bulls"
            ),
        )
    )
    opening_decisions = (
        module._ohq_v11_decisions(
            opening_model
        )
    )
    checks[
        "opening_offseason_skips_prior_cycle"
    ] = (
        opening_model.current_key
        == "roster_finalization"
        and sum(
            status == "not_required"
            for _key, _label, status
            in opening_decisions
        )
        >= 6
    )

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    print(
        {
            "checks": checks,
            "failed_checks": failed,
            "passed": not failed,
        }
    )
    if failed:
        print(
            "FRANCHISE OFFSEASON HEADQUARTERS "
            "V1.1 VALIDATOR FAILED"
        )
        return 1

    print(
        "FRANCHISE OFFSEASON HEADQUARTERS "
        "V1.1 VALIDATOR PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
