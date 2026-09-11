from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_cpu_execution_v1 import (  # noqa: E402
    build_cpu_roster_floor_rescue_opportunity,
)
from franchise_free_agency_transaction_v1 import (  # noqa: E402
    FREE_AGENCY_SUBFIVE_ROTATION_REPAIR_VERSION,
    FreeAgencyOffer,
    build_free_agency_preview,
    commit_free_agency_preview,
    free_agency_state_fingerprint,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import (  # noqa: E402
    LeaguePhase,
    validate_simulation_league_state,
)
from simulation_season_transition_v1 import (  # noqa: E402
    refresh_team_rotations,
)
from validate_franchise_free_agency_transaction_v1 import (  # noqa: E402
    load_source_state,
)


VERSION = "franchise-free-agency-subfive-rotation-repair-validator-v1.1-2026-09-11"
PRESERVED_FAILURE_CHECKPOINT = (
    ROOT
    / "outputs"
    / "_soak"
    / "r20260910T070426240366Z"
    / "outputs"
    / "runtime"
    / "franchise_mode_checkpoint_v1.pkl.gz"
)
PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT = (
    ROOT
    / "outputs"
    / "_soak_resume"
    / "r20260910T235709761441Z"
    / "outputs"
    / "runtime"
    / "franchise_mode_checkpoint_v1.pkl.gz"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pass_gate(_state: Any, offer: FreeAgencyOffer) -> dict[str, Any]:
    return {
        "status": "pass",
        "reason": "sub-five lifecycle regression fixture",
        "payload": {"annual_salary": offer.annual_salary},
    }


def _rotation_signature(state: Any, team: str) -> tuple[Any, ...]:
    team_state = state.teams[team]
    return (
        tuple(team_state.rotation.starter_ids),
        tuple(team_state.rotation.rotation_player_ids),
        tuple(sorted(team_state.rotation.minutes_targets.items())),
        tuple(team_state.active_player_ids),
        tuple(team_state.inactive_player_ids),
    )


def _build_three_player_fixture(source: Any) -> tuple[Any, str, tuple[str, str]]:
    state = copy.deepcopy(source)
    state.phase = LeaguePhase.OFFSEASON

    team = next(
        (
            team_abbreviation
            for team_abbreviation, team_state in sorted(state.teams.items())
            if len(team_state.roster_player_ids) >= 8
            and len(
                [
                    player_id
                    for player_id in team_state.roster_player_ids[3:]
                    if not bool(
                        getattr(state.players[player_id], "two_way", False)
                    )
                ]
            )
            >= 2
        ),
        "",
    )
    if not team:
        raise AssertionError("No roster can support the three-player regression fixture.")

    team_state = state.teams[team]
    original_roster = tuple(team_state.roster_player_ids)
    kept = original_roster[:3]
    released = original_roster[3:]
    offered_player_ids = tuple(
        player_id
        for player_id in released
        if not bool(getattr(state.players[player_id], "two_way", False))
    )[:2]

    team_state.roster_player_ids = kept
    free_agents = set(state.free_agent_player_ids)
    for player_id in released:
        player = state.players[player_id]
        player.team_abbreviation = ""
        player.roster_status = "free_agent"
        contract = getattr(player, "contract", None)
        if contract is not None:
            contract.status = "free_agent_pool"
        free_agents.add(player_id)
    state.free_agent_player_ids = tuple(sorted(free_agents))

    refresh_team_rotations(
        state,
        team_abbreviations=(team,),
    )
    validate_simulation_league_state(state)
    return state, team, offered_player_ids


def main() -> int:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    source, source_kind = load_source_state()
    source_fingerprint_before = free_agency_state_fingerprint(source)
    fixture, team, player_ids = _build_three_player_fixture(source)
    fixture_fingerprint_before = free_agency_state_fingerprint(fixture)
    source_rotation_before = _rotation_signature(fixture, team)

    fourth_player_id, fifth_player_id = player_ids
    fourth_offer = FreeAgencyOffer(
        player_id=fourth_player_id,
        team_abbreviation=team,
        annual_salary=4_000_000.0,
        years=1,
        guaranteed=True,
    )
    fourth_preview = build_free_agency_preview(
        fixture,
        fourth_offer,
        financial_gate=_pass_gate,
    )
    four_player_state, fourth_result = commit_free_agency_preview(
        fixture,
        fourth_preview,
        financial_gate=_pass_gate,
    )
    four_player_validation = validate_simulation_league_state(
        four_player_state
    )
    four_player_team = four_player_state.teams[team]

    fifth_offer = FreeAgencyOffer(
        player_id=fifth_player_id,
        team_abbreviation=team,
        annual_salary=4_000_000.0,
        years=1,
        guaranteed=True,
    )
    fifth_preview = build_free_agency_preview(
        four_player_state,
        fifth_offer,
        financial_gate=_pass_gate,
    )
    candidate, fifth_result = commit_free_agency_preview(
        four_player_state,
        fifth_preview,
        financial_gate=_pass_gate,
    )
    candidate_validation = validate_simulation_league_state(candidate)
    candidate_team = candidate.teams[team]

    checks.update(
        {
            "repair_version_present": bool(
                FREE_AGENCY_SUBFIVE_ROTATION_REPAIR_VERSION
            ),
            "fixture_starts_with_three_players": len(
                fixture.teams[team].roster_player_ids
            )
            == 3,
            "fixture_partial_rotation_is_valid": (
                len(fixture.teams[team].rotation.starter_ids) == 3
                and not fixture.teams[team].rotation.minutes_targets
            ),
            "fourth_player_preview_passes": (
                fourth_preview.status == "pass"
                and fourth_preview.can_commit
            ),
            "preview_reports_three_to_four": (
                fourth_preview.roster_count_before == 3
                and fourth_preview.roster_count_after == 4
            ),
            "fourth_player_commit_builds_valid_partial_rotation": (
                len(four_player_team.roster_player_ids) == 4
                and len(four_player_team.rotation.starter_ids) == 4
                and set(four_player_team.rotation.starter_ids)
                == set(four_player_team.roster_player_ids)
                and not four_player_team.rotation.minutes_targets
                and all(four_player_validation.values())
            ),
            "fifth_player_preview_passes": (
                fifth_preview.status == "pass" and fifth_preview.can_commit
            ),
            "preview_reports_four_to_five": (
                fifth_preview.roster_count_before == 4
                and fifth_preview.roster_count_after == 5
            ),
            "source_fixture_is_unchanged": (
                fixture_fingerprint_before
                == free_agency_state_fingerprint(fixture)
                and source_rotation_before == _rotation_signature(fixture, team)
            ),
            "commit_adds_exactly_one_player": (
                len(candidate_team.roster_player_ids) == 5
                and fourth_player_id in candidate_team.roster_player_ids
                and fifth_player_id in candidate_team.roster_player_ids
                and fourth_player_id not in candidate.free_agent_player_ids
                and fifth_player_id not in candidate.free_agent_player_ids
            ),
            "commit_builds_five_starters": (
                len(candidate_team.rotation.starter_ids) == 5
                and set(candidate_team.rotation.starter_ids)
                == set(candidate_team.roster_player_ids)
            ),
            "commit_builds_reconciled_minutes": math.isclose(
                sum(candidate_team.rotation.minutes_targets.values()),
                candidate.settings.regulation_minutes * 5,
                abs_tol=0.1,
            ),
            "preview_and_commit_match": (
                fourth_result.committed_fingerprint
                == fourth_preview.candidate_fingerprint
                and fifth_result.committed_fingerprint
                == fifth_preview.candidate_fingerprint
            ),
            "full_candidate_validation_passes": all(candidate_validation.values()),
            "read_only_source_state_is_unchanged": (
                source_fingerprint_before == free_agency_state_fingerprint(source)
            ),
        }
    )
    details["portable_fixture"] = {
        "source_kind": source_kind,
        "team": team,
        "fourth_player_id": fourth_player_id,
        "fifth_player_id": fifth_player_id,
        "fourth_preview_status": fourth_preview.status,
        "fifth_preview_status": fifth_preview.status,
        "roster_count_before": fourth_preview.roster_count_before,
        "roster_count_after": fifth_preview.roster_count_after,
        "starter_count_after_fourth": len(
            four_player_team.rotation.starter_ids
        ),
        "starter_count_after": len(candidate_team.rotation.starter_ids),
        "rotation_minutes_after": sum(
            candidate_team.rotation.minutes_targets.values()
        ),
    }

    # When the original two-season failure artifact is available, probe the
    # exact four-player Denver state through the real locked financial gate and
    # player-decision rescue path. This is read-only and never calls a commit.
    if PRESERVED_FAILURE_CHECKPOINT.is_file():
        preserved_hash_before = _sha256(PRESERVED_FAILURE_CHECKPOINT)
        checkpoint = load_franchise_checkpoint(
            path=PRESERVED_FAILURE_CHECKPOINT,
            allow_backup=False,
        )
        preserved_state = checkpoint.simulation_state
        preserved_fingerprint_before = free_agency_state_fingerprint(
            preserved_state
        )
        den_count = len(preserved_state.teams["DEN"].roster_player_ids)
        rescue = build_cpu_roster_floor_rescue_opportunity(preserved_state)
        checks.update(
            {
                "preserved_failure_starts_denver_at_four": den_count == 4,
                "real_cba_and_acceptance_rescue_now_exists": (
                    rescue is not None
                    and rescue.team_abbreviation == "DEN"
                    and rescue.preview.status == "pass"
                    and rescue.preview.can_commit
                    and rescue.preview.roster_count_after == 5
                ),
                "preserved_failure_probe_is_read_only": (
                    preserved_fingerprint_before
                    == free_agency_state_fingerprint(preserved_state)
                    and preserved_hash_before == _sha256(PRESERVED_FAILURE_CHECKPOINT)
                ),
            }
        )
        details["preserved_failure_probe"] = {
            "checkpoint": str(PRESERVED_FAILURE_CHECKPOINT),
            "denver_roster_before": den_count,
            "rescue_team": (
                rescue.team_abbreviation if rescue is not None else None
            ),
            "rescue_player": rescue.player_name if rescue is not None else None,
            "rescue_salary": rescue.annual_salary if rescue is not None else None,
            "offer_path": rescue.offer_path if rescue is not None else None,
            "preview_status": (
                rescue.preview.status if rescue is not None else None
            ),
        }
    else:
        details["preserved_failure_probe"] = {
            "status": "artifact_not_present_portable_fixture_only"
        }

    # The eight-season soak exposed the earlier edge one player sooner: LAC
    # reached free agency with three players and could not complete the first
    # 3->4 transaction. The real rescue planner must now find a legal offer;
    # this remains a strictly read-only probe of the preserved failure.
    if PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT.is_file():
        preserved_hash_before = _sha256(
            PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT
        )
        checkpoint = load_franchise_checkpoint(
            path=PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT,
            allow_backup=False,
        )
        preserved_state = checkpoint.simulation_state
        preserved_fingerprint_before = free_agency_state_fingerprint(
            preserved_state
        )
        lac_count = len(preserved_state.teams["LAC"].roster_player_ids)
        rescue = build_cpu_roster_floor_rescue_opportunity(preserved_state)
        checks.update(
            {
                "preserved_three_player_failure_starts_lac_at_three": (
                    lac_count == 3
                ),
                "real_three_to_four_cba_and_acceptance_rescue_exists": (
                    rescue is not None
                    and rescue.team_abbreviation == "LAC"
                    and rescue.preview.status == "pass"
                    and rescue.preview.can_commit
                    and rescue.preview.roster_count_before == 3
                    and rescue.preview.roster_count_after == 4
                ),
                "preserved_three_player_probe_is_read_only": (
                    preserved_fingerprint_before
                    == free_agency_state_fingerprint(preserved_state)
                    and preserved_hash_before
                    == _sha256(PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT)
                ),
            }
        )
        details["preserved_three_player_failure_probe"] = {
            "checkpoint": str(PRESERVED_THREE_PLAYER_FAILURE_CHECKPOINT),
            "lac_roster_before": lac_count,
            "rescue_team": (
                rescue.team_abbreviation if rescue is not None else None
            ),
            "rescue_player": rescue.player_name if rescue is not None else None,
            "rescue_salary": rescue.annual_salary if rescue is not None else None,
            "offer_path": rescue.offer_path if rescue is not None else None,
            "preview_status": (
                rescue.preview.status if rescue is not None else None
            ),
        }
    else:
        details["preserved_three_player_failure_probe"] = {
            "status": "artifact_not_present_portable_fixture_only"
        }

    failed = [name for name, passed in checks.items() if not passed]
    payload = {
        "version": VERSION,
        "repair_version": FREE_AGENCY_SUBFIVE_ROTATION_REPAIR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": details,
        "passed": not failed,
    }
    print(json.dumps(payload, indent=2, default=str))
    print()
    if failed:
        print("FRANCHISE FREE AGENCY SUB-FIVE ROTATION REPAIR V1 FAILED")
        return 1
    print("FRANCHISE FREE AGENCY SUB-FIVE ROTATION REPAIR V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
