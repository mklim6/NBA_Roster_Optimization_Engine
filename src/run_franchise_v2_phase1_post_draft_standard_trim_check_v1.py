from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator


WORK_ROOT = Path(__file__).resolve().parents[2]
STAGED_SRC = Path(__file__).resolve().parent
PROJECT_SRC = Path(
    r"C:\Users\klima\Python Projects\Projects\NBA_Roster_Optimization_Engine\src"
)

for source in (PROJECT_SRC, STAGED_SRC):
    value = str(source)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)

import franchise_cpu_front_office_v1 as front
import franchise_cpu_post_draft_roster_trim_orchestrator_v1 as trim
import franchise_cpu_post_draft_roster_trim_release_v1 as release
import franchise_free_agency_live_signing_v1 as controls


VERSION = "franchise-v2-phase1-post-draft-standard-trim-check-v1-2026-09-25"
OUTPUT = WORK_ROOT / "outputs" / "v2_phase1_post_draft_standard_trim_check_v1.json"


def _player(
    player_id: str,
    *,
    overall: float,
    two_way: bool = False,
    generated_rookie: bool = False,
) -> Any:
    return SimpleNamespace(
        player_id=player_id,
        player_name=player_id,
        overall_rating=overall,
        roster_status="two_way" if two_way else "active",
        two_way=two_way,
        generated_player=generated_rookie,
        generated_draft_year=2026 if generated_rookie else None,
        synthetic=False,
        contract=SimpleNamespace(
            salary=1_500_000.0,
            years_remaining=1,
            guaranteed=False,
            status="active",
        ),
    )


def _checkpoint(
    *,
    standard_count: int,
    two_way_count: int = 0,
    generated_rookie_ids: tuple[str, ...] = (),
) -> Any:
    players: dict[str, Any] = {}
    roster_ids: list[str] = []
    for index in range(standard_count):
        player_id = f"STD-{index:02d}"
        players[player_id] = _player(
            player_id,
            overall=60.0 + index,
            generated_rookie=player_id in set(generated_rookie_ids),
        )
        roster_ids.append(player_id)
    for index in range(two_way_count):
        player_id = f"TW-{index:02d}"
        players[player_id] = _player(
            player_id,
            overall=40.0 + index,
            two_way=True,
        )
        roster_ids.append(player_id)

    team_state = SimpleNamespace(
        roster_player_ids=tuple(roster_ids),
        rotation=SimpleNamespace(
            starter_ids=(),
            rotation_player_ids=(),
            minutes_by_player_id={},
        ),
    )
    simulation_state = SimpleNamespace(
        phase="offseason",
        teams={"AAA": team_state},
        players=players,
    )
    return SimpleNamespace(
        simulation_state=simulation_state,
        trade_state=SimpleNamespace(),
        preferences={},
    )


@contextmanager
def _patched_dependencies(
    *,
    controlled: tuple[str, ...] = (),
    uncertified: tuple[str, ...] = (),
) -> Iterator[dict[str, int]]:
    originals = {
        "build_plan": front.build_league_front_office_plan,
        "intrinsic": getattr(front, "intrinsic_player_value", None),
        "preview": release.build_cpu_post_draft_release_preview,
        "simulation_fingerprint": release._simulation_fingerprint,
        "trade_fingerprint": release._trade_fingerprint,
        "controlled": controls.controlled_teams_from_durable_checkpoint,
    }
    fingerprint_calls = {"simulation": 0, "trade": 0}

    def build_plan(state: Any, *, controlled_teams: tuple[str, ...]) -> Any:
        return SimpleNamespace(
            team_plans={
                team: SimpleNamespace(
                    player_decisions=(),
                    cut_candidate_ids=(),
                    protected_player_ids=(),
                )
                for team in state.teams
            }
        )

    def preview(
        checkpoint: Any,
        *,
        team: str,
        player_id: str,
        rationale: tuple[str, ...],
        require_non_rotation: bool = True,
        _precomputed_source_fingerprints: tuple[str, str] | None = None,
    ) -> Any:
        if player_id in set(uncertified):
            return SimpleNamespace(
                status="manual_review",
                can_commit_to_clone=False,
                financial_treatment="unknown_future_guarantee",
                blockers=("future guarantee is unresolved",),
            )
        return SimpleNamespace(
            status="pass",
            can_commit_to_clone=True,
            financial_treatment="exact_non_guaranteed_release",
            blockers=(),
        )

    front.build_league_front_office_plan = build_plan
    front.intrinsic_player_value = lambda player: float(player.overall_rating)
    release.build_cpu_post_draft_release_preview = preview
    def simulation_fingerprint(state: Any) -> str:
        fingerprint_calls["simulation"] += 1
        return "simulation-fingerprint"

    def trade_fingerprint(state: Any) -> str:
        fingerprint_calls["trade"] += 1
        return "trade-fingerprint"

    release._simulation_fingerprint = simulation_fingerprint
    release._trade_fingerprint = trade_fingerprint
    controls.controlled_teams_from_durable_checkpoint = lambda checkpoint: controlled
    try:
        yield fingerprint_calls
    finally:
        front.build_league_front_office_plan = originals["build_plan"]
        if originals["intrinsic"] is None:
            delattr(front, "intrinsic_player_value")
        else:
            front.intrinsic_player_value = originals["intrinsic"]
        release.build_cpu_post_draft_release_preview = originals["preview"]
        release._simulation_fingerprint = originals["simulation_fingerprint"]
        release._trade_fingerprint = originals["trade_fingerprint"]
        controls.controlled_teams_from_durable_checkpoint = originals["controlled"]


def _single_preview(checkpoint: Any) -> Any:
    league = trim.build_cpu_post_draft_trim_league_preview(checkpoint)
    assert len(league.team_previews) == 1
    return league.team_previews[0]


def main() -> int:
    checks: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check": name,
                "passed": bool(passed),
                "detail": detail,
            }
        )

    with _patched_dependencies() as fingerprint_calls:
        row = _single_preview(
            _checkpoint(
                standard_count=16,
                generated_rookie_ids=("STD-00",),
            )
        )
        record(
            "sixteen_standard_contracts_requires_one_cut",
            row.required_cut_count == 1
            and row.standard_contract_count_before == 16
            and row.standard_contract_count_after_preview == 15,
            f"required={row.required_cut_count}; after={row.standard_contract_count_after_preview}",
        )
        record(
            "current_generated_rookie_is_protected",
            tuple(item.player_id for item in row.selected_releases) == ("STD-01",),
            "selected=" + ",".join(item.player_id for item in row.selected_releases),
        )
        record(
            "cpu_standard_trim_is_executable",
            row.status == "cpu_trim_plan_executable_on_clone",
            row.status,
        )
        record(
            "league_preview_fingerprints_immutable_source_once",
            fingerprint_calls == {"simulation": 1, "trade": 1},
            json.dumps(fingerprint_calls, sort_keys=True),
        )

    with _patched_dependencies(uncertified=("STD-00",)):
        row = _single_preview(_checkpoint(standard_count=16))
        record(
            "uncertified_lowest_candidate_does_not_block_later_legal_candidate",
            row.status == "cpu_trim_plan_executable_on_clone"
            and tuple(item.player_id for item in row.selected_releases) == ("STD-01",),
            f"status={row.status}; selected="
            + ",".join(item.player_id for item in row.selected_releases),
        )

    with _patched_dependencies():
        row = _single_preview(_checkpoint(standard_count=15, two_way_count=1))
        record(
            "two_way_contract_does_not_trigger_standard_trim",
            row.status == "no_trim_required"
            and row.required_cut_count == 0
            and row.standard_contract_count_before == 15
            and row.roster_count_before == 16,
            f"status={row.status}; standard={row.standard_contract_count_before}; total={row.roster_count_before}",
        )

    with _patched_dependencies(controlled=("AAA",)):
        row = _single_preview(_checkpoint(standard_count=16))
        record(
            "user_controlled_team_is_never_auto_cut",
            row.status == "user_controlled_overflow_requires_user_decision"
            and row.selected_cut_count == 0,
            row.status,
        )

    with _patched_dependencies():
        row = _single_preview(_checkpoint(standard_count=15, two_way_count=7))
        record(
            "unsupported_nonstandard_overflow_fails_closed",
            row.status == "blocked_nonstandard_roster_overflow"
            and row.selected_cut_count == 0,
            row.status,
        )

    one_year_player = _player("ONE-YEAR", overall=60.0)
    one_year_player.contract.guaranteed = None
    one_year_player.contract.years_remaining = 1
    route, current_dead, future_dead, blockers = release._financial_treatment(
        one_year_player
    )
    record(
        "one_year_unknown_guarantee_books_full_salary_conservatively",
        route == "conservative_full_current_salary_one_year_unknown_guarantee"
        and current_dead == one_year_player.contract.salary
        and future_dead == 0.0
        and not blockers,
        f"route={route}; current_dead={current_dead}; future_dead={future_dead}",
    )

    multi_year_player = _player("MULTI-YEAR", overall=60.0)
    multi_year_player.contract.guaranteed = None
    multi_year_player.contract.years_remaining = 2
    route, _, _, blockers = release._financial_treatment(multi_year_player)
    record(
        "multi_year_unknown_guarantee_still_fails_closed",
        route == "blocked_guarantee_status_unknown" and bool(blockers),
        f"route={route}; blockers={list(blockers)}",
    )

    generated_checkpoint = _checkpoint(standard_count=2)
    current_rookie = generated_checkpoint.simulation_state.players["STD-00"]
    older_generated = generated_checkpoint.simulation_state.players["STD-01"]
    current_rookie.generated_player = True
    current_rookie.generated_draft_year = 2029
    current_rookie.rating_source = "generated-draft-class-v1"
    current_rookie.contract.years_remaining = 4
    current_rookie.contract.guaranteed = True
    current_rookie.contract.option_type = "rookie_scale"
    older_generated.generated_player = True
    older_generated.generated_draft_year = 2028
    older_generated.rating_source = "generated-draft-class-v1"
    older_generated.contract.years_remaining = 3
    older_generated.contract.guaranteed = True
    older_generated.contract.option_type = "rookie_scale"
    state = generated_checkpoint.simulation_state
    route, current_dead, future_dead, blockers = release._financial_treatment(
        older_generated
    )
    record(
        "current_rookie_protected_but_older_generated_option_is_releasable",
        release._current_or_unresolved_generated_rookie(state, current_rookie)
        and not release._current_or_unresolved_generated_rookie(
            state,
            older_generated,
        )
        and route == "conservative_generated_rookie_option_current_salary"
        and current_dead == older_generated.contract.salary
        and future_dead == 0.0
        and not blockers,
        f"route={route}; current_dead={current_dead}; future_dead={future_dead}; "
        f"blockers={list(blockers)}",
    )

    contract = trim.orchestrator_contract_report()
    record(
        "contract_report_exposes_both_roster_limits",
        contract.get("post_draft_offseason_roster_ceiling") == 21
        and contract.get("post_draft_standard_contract_ceiling") == 15,
        json.dumps(contract, sort_keys=True),
    )

    report = {
        "version": VERSION,
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "production_state_mutated": False,
        "active_checkpoint_loaded": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
