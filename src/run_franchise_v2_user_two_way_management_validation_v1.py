from __future__ import annotations

import hashlib
from pathlib import Path

from franchise_user_two_way_management_v1 import (
    UserTwoWayManagementError,
    build_user_two_way_release_candidate_v1,
    build_user_two_way_signing_candidate_v1,
    current_two_way_players_v1,
    eligible_two_way_free_agents_v1,
    standard_contract_count_v1,
    two_way_count_v1,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean(value) -> str:
    return str(value or "").strip()


def controlled_from_checkpoint(checkpoint) -> tuple[str, ...]:
    raw = dict(getattr(checkpoint, "preferences", {}) or {}).get(
        "franchise_pref_controlled_teams",
        (),
    ) or ()
    if isinstance(raw, str):
        raw = [raw]
    return tuple(
        sorted(
            {
                clean(value).upper()
                for value in raw
                if clean(value)
            }
        )
    )


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    source_state = checkpoint.simulation_state
    source_trade = checkpoint.trade_state
    controlled = controlled_from_checkpoint(checkpoint)
    if not controlled:
        raise RuntimeError("No controlled team is stored in the durable checkpoint.")

    team = controlled[0]
    work_state = source_state
    work_trade = source_trade

    source_standard = standard_contract_count_v1(source_state, team)
    source_two_way = two_way_count_v1(source_state, team)

    release_result = None
    current = current_two_way_players_v1(work_state, team)

    # If the team is already full, prove that a two-way release opens one slot
    # on a protected candidate before testing a new signing.
    if source_two_way >= 3:
        if not current:
            raise RuntimeError("Two-way count is full but no two-way player is discoverable.")
        work_state, work_trade, release_result = (
            build_user_two_way_release_candidate_v1(
                work_state,
                work_trade,
                team_code=team,
                player_id=current[-1]["player_id"],
                controlled_teams=controlled,
            )
        )

    eligible = eligible_two_way_free_agents_v1(work_state, team)
    if not eligible:
        raise RuntimeError(
            f"No eligible two-way free agent is available for protected validation of {team}."
        )

    target = eligible[0]
    signed_state, signed_trade, sign_result = (
        build_user_two_way_signing_candidate_v1(
            work_state,
            work_trade,
            team_code=team,
            player_id=target["player_id"],
            controlled_teams=controlled,
        )
    )

    checks = {
        "source_standard_count_preserved":
            standard_contract_count_v1(source_state, team) == source_standard,
        "source_two_way_count_preserved":
            two_way_count_v1(source_state, team) == source_two_way,
        "candidate_standard_count_unchanged":
            sign_result.standard_contract_count_before
            == sign_result.standard_contract_count_after,
        "candidate_two_way_count_increments_by_one":
            sign_result.two_way_contract_count_after
            == sign_result.two_way_contract_count_before + 1,
        "candidate_two_way_count_never_exceeds_three":
            sign_result.two_way_contract_count_after <= 3,
        "signed_player_removed_from_free_agents":
            target["player_id"] not in set(signed_state.free_agent_player_ids),
        "signed_player_owned_by_team":
            clean(signed_state.players[target["player_id"]].team_abbreviation).upper()
            == team,
        "signed_player_flagged_two_way":
            bool(signed_state.players[target["player_id"]].two_way),
        "trade_owner_matches_signing":
            clean(signed_trade.player_team_by_id.get(target["player_id"])).upper()
            == team,
        "trade_two_way_count_matches_simulation":
            int(signed_trade.team_financials[team].two_way_contract_count)
            == two_way_count_v1(signed_state, team),
        "trade_revision_incremented":
            sign_result.trade_revision_after == sign_result.trade_revision_before + 1,
    }

    # Prove release semantics too, even when the source team had an open slot.
    released_state, released_trade, second_release = (
        build_user_two_way_release_candidate_v1(
            signed_state,
            signed_trade,
            team_code=team,
            player_id=target["player_id"],
            controlled_teams=controlled,
        )
    )
    released_player = released_state.players[target["player_id"]]
    checks.update({
        "release_standard_count_unchanged":
            second_release.standard_contract_count_before
            == second_release.standard_contract_count_after,
        "release_two_way_count_decrements_by_one":
            second_release.two_way_contract_count_after
            == second_release.two_way_contract_count_before - 1,
        "released_player_returns_to_free_agents":
            target["player_id"] in set(released_state.free_agent_player_ids),
        "released_player_has_no_team":
            clean(released_player.team_abbreviation) == "",
        "released_player_two_way_cleared":
            not bool(released_player.two_way),
        "released_contract_is_free_agent_pool":
            clean(released_player.contract.status).lower() == "free_agent_pool",
        "release_trade_owner_is_blank":
            clean(released_trade.player_team_by_id.get(target["player_id"])) == "",
        "release_trade_two_way_count_matches_simulation":
            int(released_trade.team_financials[team].two_way_contract_count)
            == two_way_count_v1(released_state, team),
    })

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 USER TWO-WAY MANAGEMENT V1 RUNTIME VALIDATION")
    print(f"Controlled team: {team}")
    print(f"Source standard contracts: {source_standard}")
    print(f"Source two-way contracts: {source_two_way}")
    if release_result is not None:
        print(
            "Protected pre-sign release: "
            f"{release_result.player_name} -> "
            f"{release_result.two_way_contract_count_after}/3"
        )
    print(
        "Protected signing target: "
        f"{sign_result.player_name} -> "
        f"{sign_result.two_way_contract_count_after}/3"
    )

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("RUNTIME VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1

    print("RUNTIME VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
