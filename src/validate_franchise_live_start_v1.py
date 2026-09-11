from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "franchise_live_start_v1_validation.json"
VERSION = "franchise-live-start-validator-v1.4-2026-09-09"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase(state: Any) -> str:
    value = getattr(state, "phase", "")
    return str(getattr(value, "value", value)).strip().lower()


def main() -> int:
    import simulation_franchise_checkpoint_v1 as checkpoint_api
    from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_team
    from franchise_draft_forfeitures_v1 import DRAFT_PICK_FORFEITURES
    from franchise_live_asset_ledger_v1 import build_live_asset_ledger
    from franchise_live_start_v1 import (
        LIVE_CONDITIONAL_SECOND_RIGHT_ID,
        LIVE_RATING_PROFILE_TRANSLATION_VERSION,
        LIVE_REFERENCE_MATERIALIZED_PLAYER_COUNT,
        LIVE_REFERENCE_PLAYER_COUNT,
        LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION,
        LIVE_SKILL_PROFILE_TRANSLATION_VERSION,
        LIVE_START_CUTOFF_DATE,
        LIVE_STAT_PROFILE_TRANSLATION_VERSION,
        LIVE_START_UNIVERSE_ID,
        PRESERVED_DIRECT_LAC_SECOND_RIGHT_ID,
        build_live_starting_franchise,
        live_start_fingerprint,
        load_live_start_config,
    )
    from franchise_opening_regular_season_transition_v1 import (
        preview_opening_regular_season,
    )
    from nba_current_reference_overlay_v1 import load_current_reference_overlay
    from simulation_league_state_v1 import (
        BASELINE_PER_36_FIELDS,
        DEVELOPMENT_SKILL_FIELDS,
        validate_simulation_league_state,
    )
    from simulation_player_stat_fingerprints_v2 import build_player_stat_fingerprint
    from mutable_league_state_v1 import validate_state

    checkpoint_path = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    checkpoint_before = _sha256(checkpoint_path)
    runtime = load_runtime_data()
    config = load_live_start_config()
    overlay = load_current_reference_overlay()
    first = build_live_starting_franchise(runtime)
    second = build_live_starting_franchise(runtime)
    state = first.simulation_state
    trade_state = first.trade_state
    validate_simulation_league_state(state)
    validate_state(trade_state, runtime)
    opening = preview_opening_regular_season(state, trade_state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)

    roster_members = [
        player_id
        for team in state.teams.values()
        for player_id in team.roster_player_ids
    ]
    roster_sizes = {
        team: len(team_state.roster_player_ids)
        for team, team_state in state.teams.items()
    }
    profile_ids = {
        str(row.get("player_id"))
        for row in config.get("missing_player_profiles", [])
    }
    status_counts = {
        status: sum(
            str(row.get("current_reference_status")) == status
            for row in overlay.values()
        )
        for status in ("under_contract", "two_way", "exhibit_10", "free_agent")
    }
    overlay_matches = all(
        normalize_team(getattr(state.players[player_id], "team_abbreviation", ""))
        == normalize_team(row.get("current_reference_team"))
        and str(getattr(state.players[player_id], "roster_status", ""))
        == str(row.get("current_reference_status", "")).replace(
            "under_contract", "active_roster"
        )
        for player_id, row in overlay.items()
    )
    financial_counts_match = all(
        financial.standard_contract_count
        == sum(
            not bool(getattr(state.players[player_id], "two_way", False))
            for player_id in state.teams[team].roster_player_ids
        )
        and financial.two_way_contract_count
        == sum(
            bool(getattr(state.players[player_id], "two_way", False))
            for player_id in state.teams[team].roster_player_ids
        )
        for team, financial in trade_state.team_financials.items()
    )

    ledger_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in ledger.draft_rows:
        ledger_by_id.setdefault(str(row.get("asset_id")), []).append(dict(row))
    five_forfeitures = [
        row
        for row in ledger.draft_rows
        if row.get("forfeiture_status") == "forfeited"
        and row.get("penalized_team") == "LAC"
    ]
    rights = getattr(state, "franchise_international_draft_rights_v1", {}) or {}
    universe = getattr(state, "franchise_start_universe_v1", {}) or {}
    financial_scope = getattr(state, "franchise_live_financial_scope_v1", {}) or {}
    profile_scope = getattr(state, "franchise_live_profile_scope_v1", {}) or {}
    expected_sourced_overalls = {
        "1627732": ("Ben Simmons", 77.0, "PG", "2-Way Power-Slashing Cleaner"),
        "1627777": ("Georges Niang", 71.0, "PF", "Stretch Four"),
        "1630667": ("Kyle Mangas", 68.0, "SG", "Diming Sharpshooter"),
        "1641759": ("Dillon Mitchell", 68.0, "PF", "Rim-Running Hammer"),
        "1642481": ("Jamarion Sharp", 67.0, "C", "Rim Tyrant"),
        "1643552": ("Braden Smith", 70.0, "PG", "Diming Sharpshooter"),
        "1643624": ("Bryce Hopkins", 68.0, "PF", "2-Way Rim-Rocking Stretch"),
        "1643738": ("Malik Dia", 68.0, "PF", "Popper"),
    }
    sourced_overalls_are_exact = all(
        player_id in state.players
        and (
            state.players[player_id].player_name,
            state.players[player_id].overall_rating,
            getattr(state.players[player_id], "live_reference_profile_evidence", {}).get(
                "source_position"
            ),
            getattr(state.players[player_id], "live_reference_profile_evidence", {}).get(
                "source_archetype"
            ),
        )
        == expected
        and state.players[player_id].rating_source == "current_2kratings_snapshot_v1"
        and bool(
            getattr(state.players[player_id], "live_reference_profile_evidence", {}).get(
                "overall_rating_source_url"
            )
        )
        for player_id, expected in expected_sourced_overalls.items()
    )
    expected_empirical_overalls = {
        "1629605": ("Tacko Fall", 69.5, 70.5, 69.5),
        "1631215": ("Khalifa Diop", 68.0, 70.5, 69.5),
        "1641802": ("Matthew Murrell", 68.0, 69.0, 68.5),
        "1641935": ("Jarkel Joiner", 67.5, 68.0, 68.0),
        "1642392": ("Jameer Nelson Jr.", 69.0, 72.0, 71.0),
        "1643102": ("Trey Townsend", 67.0, 68.0, 67.5),
        "1643148": ("Saint Thomas", 68.0, 70.5, 69.5),
        "1643225": ("Kobe Stewart", 68.0, 70.5, 69.5),
        "1643251": ("Josiah Allick", 68.0, 69.5, 69.0),
        "1643572": ("Rafael Castro", 69.5, 75.0, 73.0),
        "1643727": ("J'Vonne Hadley", 68.0, 70.5, 69.5),
    }
    empirical_overalls_are_exact = all(
        player_id in state.players
        and (
            state.players[player_id].player_name,
            state.players[player_id].overall_rating,
            state.players[player_id].potential_rating,
            state.players[player_id].future_outlook_rating,
        )
        == expected
        and state.players[player_id].rating_source
        == "live_empirical_rating_translation_v1"
        and not bool(
            getattr(state.players[player_id], "live_reference_overall_sourced", True)
        )
        and bool(
            getattr(
                state.players[player_id],
                "live_reference_overall_evidence_informed",
                False,
            )
        )
        and (
            evidence := getattr(
                state.players[player_id], "live_reference_profile_evidence", {}
            )
        ).get("translation_version") == LIVE_RATING_PROFILE_TRANSLATION_VERSION
        and evidence.get("overall_rating_evidence_status")
        == "source_informed_empirical_proxy_no_released_game_rating"
        and not bool(evidence.get("released_external_rating"))
        and bool(evidence.get("production_source_url"))
        and evidence.get("reference_released_player_count") == 649
        and float(evidence.get("reference_lower_roster_anchor", 0.0)) == 68.0
        and set(evidence.get("component_scores", {}))
        == {"scoring", "rebounding", "playmaking", "defense", "ball_security"}
        and float(evidence.get("resolved_overall_rating", 0.0)) == expected[1]
        and float(evidence.get("resolved_potential_rating", 0.0)) == expected[2]
        and float(evidence.get("resolved_future_outlook_rating", 0.0)) == expected[3]
        for player_id, expected in expected_empirical_overalls.items()
    )
    expected_stat_profile_sources = {
        "nba": {"1627732", "1627777"},
        "gleague": {
            "1629605",
            "1630667",
            "1641802",
            "1641935",
            "1642392",
            "1642481",
            "1643148",
            "1643225",
            "1643251",
        },
        "ncaa": {
            "1641759",
            "1643102",
            "1643552",
            "1643572",
            "1643624",
            "1643727",
            "1643738",
        },
        "international": {"1631215"},
    }
    stat_profile_source_by_id = {
        player_id: source_level
        for source_level, player_ids in expected_stat_profile_sources.items()
        for player_id in player_ids
    }
    stat_profile_evidence_is_exact = all(
        player_id in state.players
        and (
            evidence := getattr(
                state.players[player_id],
                "live_reference_stat_profile_evidence",
                {},
            )
        ).get("source_level")
        == expected_source
        and evidence.get("translation_version")
        == LIVE_STAT_PROFILE_TRANSLATION_VERSION
        and bool(evidence.get("source_url"))
        and int(evidence.get("games_played", 0) or 0) > 0
        and 0.0 < float(evidence.get("translation_weight", 0.0) or 0.0) <= 0.95
        and set(evidence.get("observed_per_36", {}))
        == set(BASELINE_PER_36_FIELDS)
        and set(evidence.get("simulation_baseline_per_36", {}))
        == set(BASELINE_PER_36_FIELDS)
        and all(
            float(evidence["observed_per_36"][field]) >= 0.0
            and float(evidence["simulation_baseline_per_36"][field]) >= 0.0
            and float(state.players[player_id].baseline_per_36[field])
            == float(evidence["simulation_baseline_per_36"][field])
            for field in BASELINE_PER_36_FIELDS
        )
        for player_id, expected_source in stat_profile_source_by_id.items()
    )
    shooting_profile_evidence_is_exact = all(
        player_id in state.players
        and (
            shooting_evidence := getattr(
                state.players[player_id],
                "live_reference_shooting_evidence",
                {},
            )
        ).get("source_level")
        == expected_source
        and shooting_evidence.get("translation_version")
        == LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION
        and bool(shooting_evidence.get("source_url"))
        and set(shooting_evidence.get("attempts", {}))
        == {
            "field_goal_attempts",
            "three_point_attempts",
            "free_throw_attempts",
        }
        and set(shooting_evidence.get("observed_percentages", {}))
        == {
            "three_point_percentage",
            "two_point_percentage",
            "free_throw_percentage",
            "two_point_attempts",
        }
        and set(shooting_evidence.get("translation_weights", {}))
        == {
            "three_point_percentage",
            "two_point_percentage",
            "free_throw_percentage",
        }
        and set(shooting_evidence.get("simulation_targets", {}))
        == {
            "three_point_percentage",
            "two_point_percentage",
            "free_throw_percentage",
        }
        and set(shooting_evidence.get("development_skill_anchor", {}))
        == {"shooting_rating", "scoring_rating", "efficiency_rating"}
        and all(
            float(value) >= 0.0
            for value in shooting_evidence["attempts"].values()
        )
        and all(
            0.0 <= float(value) <= 0.95
            for value in shooting_evidence["translation_weights"].values()
        )
        and (
            fingerprint := build_player_stat_fingerprint(state.players[player_id])
        ).three_point_percentage
        == float(shooting_evidence["simulation_targets"]["three_point_percentage"])
        and fingerprint.two_point_percentage
        == float(shooting_evidence["simulation_targets"]["two_point_percentage"])
        and fingerprint.free_throw_percentage
        == float(shooting_evidence["simulation_targets"]["free_throw_percentage"])
        for player_id, expected_source in stat_profile_source_by_id.items()
    )
    skill_profile_evidence_is_exact = all(
        player_id in state.players
        and (
            skill_evidence := getattr(
                state.players[player_id],
                "live_reference_skill_rating_evidence",
                {},
            )
        ).get("translation_version") == LIVE_SKILL_PROFILE_TRANSLATION_VERSION
        and skill_evidence.get("source_level") == expected_source
        and bool(skill_evidence.get("source_url"))
        and set(skill_evidence.get("simulation_skill_ratings", {}))
        == set(DEVELOPMENT_SKILL_FIELDS)
        and skill_evidence.get("simulation_skill_ratings")
        == state.players[player_id].skill_ratings
        and len({round(float(value), 1) for value in state.players[player_id].skill_ratings.values()})
        >= 3
        and all(
            55.0 <= float(value) <= 95.0
            for value in state.players[player_id].skill_ratings.values()
        )
        for player_id, expected_source in stat_profile_source_by_id.items()
    )
    potential_and_outlook_evidence_is_exact = all(
        player_id in state.players
        and bool(
            getattr(
                state.players[player_id],
                "live_reference_overall_evidence_informed",
                False,
            )
        )
        and (
            rating_evidence := getattr(
                state.players[player_id],
                "live_reference_profile_evidence",
                {},
            )
        ).get("translation_version") == LIVE_RATING_PROFILE_TRANSLATION_VERSION
        and float(rating_evidence.get("resolved_overall_rating", 0.0))
        == float(state.players[player_id].overall_rating)
        and float(rating_evidence.get("resolved_potential_rating", 0.0))
        == float(state.players[player_id].potential_rating)
        and float(rating_evidence.get("resolved_future_outlook_rating", 0.0))
        == float(state.players[player_id].future_outlook_rating)
        and float(state.players[player_id].potential_rating)
        >= float(state.players[player_id].overall_rating)
        for player_id in profile_ids
    )
    development_probe = copy.deepcopy(state.players["1630667"])
    development_before = build_player_stat_fingerprint(development_probe)
    for skill_name in ("shooting_rating", "scoring_rating", "efficiency_rating"):
        development_probe.skill_ratings[skill_name] += 2.0
    development_after = build_player_stat_fingerprint(development_probe)
    expected_detailed_contracts = {
        "1627777": ("Georges Niang", 3_876_528, 2_449_421, 1_838_009, 1, ""),
        "1630208": ("Nick Richards", 3_066_143, 2_449_421, 0, 1, ""),
        "1630228": (
            "Jonathan Kuminga",
            6_064_000,
            6_064_000,
            12_431_200,
            2,
            "player_option_final_year",
        ),
        "1630314": ("Brandon Williams", 2_625_627, 2_449_421, 0, 1, ""),
        "1630570": ("Trendon Watford", 2_845_883, 2_449_421, 250_000, 1, ""),
        "1631215": (
            "Khalifa Diop",
            1_357_763,
            1_357_763,
            1_357_763,
            4,
            "team_option_final_year",
        ),
        "202691": (
            "Klay Thompson",
            5_600_000,
            5_600_000,
            11_480_000,
            2,
            "player_option_final_year",
        ),
        "203484": (
            "Kentavious Caldwell-Pope",
            3_876_528,
            2_449_421,
            3_876_528,
            1,
            "",
        ),
    }
    detailed_contracts_are_exact = all(
        player_id in state.players
        and (
            state.players[player_id].player_name,
            getattr(state.players[player_id].contract, "salary", None),
            getattr(state.players[player_id], "live_contract_cap_hit", None),
            getattr(state.players[player_id], "live_contract_guaranteed_amount", None),
            getattr(state.players[player_id].contract, "years_remaining", None),
            getattr(state.players[player_id].contract, "option_type", ""),
        )
        == expected
        for player_id, expected in expected_detailed_contracts.items()
    )
    configured_contract_ids = {
        str(player_id) for player_id in config.get("current_contract_overrides", {})
    }
    standard_signing_ids = {
        player_id
        for player_id, row in overlay.items()
        if row.get("current_reference_status") == "under_contract"
        and row.get("contract_reference_action") == "standard_signing"
    }
    standard_signings_are_resolved = all(
        getattr(state.players[player_id].contract, "salary", None) is not None
        and getattr(state.players[player_id], "live_contract_cap_hit", None) is not None
        for player_id in standard_signing_ids
    )
    page_text = (ROOT / "pages" / "5_Franchise_Mode.py").read_text(encoding="utf-8")
    live_start_text = (ROOT / "src" / "franchise_live_start_v1.py").read_text(
        encoding="utf-8"
    )
    ui_text = (ROOT / "src" / "franchise_live_start_ui_v1.py").read_text(
        encoding="utf-8"
    )

    checks = {
        "configuration_and_manifest_are_valid": bool(config),
        "reference_overlay_has_49_players": len(overlay) == LIVE_REFERENCE_PLAYER_COUNT,
        "overlay_status_distribution_is_exact": status_counts
        == {
            "under_contract": 19,
            "two_way": 10,
            "exhibit_10": 8,
            "free_agent": 12,
        },
        "live_build_is_deterministic": first.fingerprint == second.fingerprint,
        "fingerprint_recomputes_exactly": first.fingerprint
        == live_start_fingerprint(state, trade_state),
        "live_universe_metadata_is_exact": universe.get("universe_id")
        == LIVE_START_UNIVERSE_ID
        and universe.get("cutoff_date") == LIVE_START_CUTOFF_DATE,
        "supplemental_player_count_is_19": first.materialized_players
        == LIVE_REFERENCE_MATERIALIZED_PLAYER_COUNT
        and len(profile_ids) == LIVE_REFERENCE_MATERIALIZED_PLAYER_COUNT,
        "supplemental_players_are_real_and_provisional": all(
            player_id in state.players
            and not bool(getattr(state.players[player_id], "synthetic", True))
            and bool(
                getattr(
                    state.players[player_id],
                    "live_reference_profile_provisional",
                    False,
                )
            )
            and float(getattr(state.players[player_id], "profile_reliability", 1.0))
            <= 0.80
            for player_id in profile_ids
        ),
        "eight_current_overall_anchors_are_exact": sourced_overalls_are_exact,
        "eleven_unreleased_overalls_use_exact_empirical_proxies":
        empirical_overalls_are_exact,
        "all_19_source_informed_stat_profiles_are_installed":
        stat_profile_evidence_is_exact,
        "all_19_source_informed_shooting_profiles_are_installed":
        shooting_profile_evidence_is_exact,
        "all_19_source_informed_skill_profiles_are_installed":
        skill_profile_evidence_is_exact,
        "all_19_potential_and_outlook_profiles_are_evidence_calibrated":
        potential_and_outlook_evidence_is_exact,
        "sourced_shooting_targets_remain_development_responsive":
        development_after.three_point_percentage
        > development_before.three_point_percentage
        and development_after.two_point_percentage
        > development_before.two_point_percentage
        and development_after.free_throw_percentage
        > development_before.free_throw_percentage,
        "profile_cleanup_scope_is_explicit": profile_scope.get(
            "materialized_profile_count"
        )
        == 19
        and profile_scope.get("externally_sourced_overall_count") == 8
        and profile_scope.get("empirically_calibrated_overall_count") == 11
        and profile_scope.get("source_informed_overall_count") == 19
        and profile_scope.get("fully_modeled_overall_count") == 0
        and profile_scope.get("rating_profile_translation_version")
        == LIVE_RATING_PROFILE_TRANSLATION_VERSION
        and profile_scope.get("detailed_statistical_profiles_sourced") == 19
        and profile_scope.get("detailed_statistical_profiles_remaining") == 0
        and profile_scope.get("statistical_profile_source_distribution")
        == {"nba": 2, "gleague": 9, "ncaa": 7, "international": 1}
        and profile_scope.get("statistical_profile_translation_version")
        == LIVE_STAT_PROFILE_TRANSLATION_VERSION
        and profile_scope.get("shooting_efficiency_profiles_sourced") == 19
        and profile_scope.get("shooting_efficiency_profiles_remaining") == 0
        and profile_scope.get("shooting_profile_translation_version")
        == LIVE_SHOOTING_PROFILE_TRANSLATION_VERSION
        and profile_scope.get("broader_skill_ratings_source_informed") == 19
        and profile_scope.get("broader_skill_ratings_still_modeled") == 0
        and profile_scope.get("skill_profile_translation_version")
        == LIVE_SKILL_PROFILE_TRANSLATION_VERSION
        and profile_scope.get("potential_profiles_age_and_production_calibrated")
        == 19
        and profile_scope.get("potential_profiles_still_modeled") == 0,
        "total_player_population_is_601": len(state.players) == 601,
        "all_reference_teams_and_statuses_match": overlay_matches,
        "rostered_and_free_agent_counts_partition_population": first.rostered_players
        == 415
        and first.free_agents == 186
        and first.rostered_players + first.free_agents == len(state.players),
        "roster_members_are_unique": len(roster_members) == len(set(roster_members)),
        "all_30_rosters_are_game_ready": len(roster_sizes) == 30
        and min(roster_sizes.values()) >= state.settings.minimum_game_players
        and max(roster_sizes.values()) <= 21,
        "free_agent_pool_matches_blank_teams": set(state.free_agent_player_ids)
        == {
            player_id
            for player_id, player in state.players.items()
            if not normalize_team(getattr(player, "team_abbreviation", ""))
        },
        "trade_player_ownership_matches_simulation": all(
            normalize_team(trade_state.player_team_by_id.get(player_id))
            == normalize_team(getattr(player, "team_abbreviation", ""))
            for player_id, player in state.players.items()
        ),
        "financial_roster_counts_match": financial_counts_match,
        "two_way_and_exhibit_10_counts_are_exact": first.two_way_players == 10
        and first.exhibit_10_players == 8,
        "all_standard_signing_amounts_are_resolved": standard_signings_are_resolved
        and first.unresolved_current_contract_amounts == 0
        and financial_scope.get("unresolved_current_contract_amounts") == 0,
        "eight_detailed_contracts_are_exact": detailed_contracts_are_exact,
        "contract_override_ids_are_exact": configured_contract_ids
        == set(expected_detailed_contracts) | {"1627732", "1631212"}
        and configured_contract_ids <= set(overlay),
        "salary_cap_and_guarantee_semantics_are_separate": financial_scope.get(
            "base_salary_and_cap_hit_separated"
        )
        is True
        and financial_scope.get("configured_contract_count") == 10
        and financial_scope.get("detailed_contracts_resolved") == 8
        and financial_scope.get("cap_hit_differences") == 5,
        "schedule_is_complete_and_unplayed": len(state.schedule) == 1230
        and not state.completed_games
        and _phase(state) == "offseason",
        "opening_regular_season_is_commit_ready": opening.can_commit
        and not opening.blockers
        and opening.schedule_count == 1230
        and opening.scheduled_game_count == 1230,
        "clippers_conditional_second_moved_to_washington": trade_state.pick_team_by_id.get(
            LIVE_CONDITIONAL_SECOND_RIGHT_ID
        )
        == "WAS",
        "separate_direct_clippers_second_stays_with_utah": trade_state.pick_team_by_id.get(
            PRESERVED_DIRECT_LAC_SECOND_RIGHT_ID
        )
        == "UTA",
        "cleveland_2031_first_moved_to_denver": any(
            row.get("current_owner") == "DEN"
            for row in ledger_by_id.get("2031_R1_CLE", [])
        ),
        "sacramento_2032_second_moved_to_denver": any(
            row.get("current_owner") == "DEN"
            for row in ledger_by_id.get("FRANCHISE-2032-R2-SAC", [])
        ),
        "five_clippers_firsts_remain_forfeited": len(five_forfeitures)
        == len(DRAFT_PICK_FORFEITURES)
        == 5,
        "kamagate_rights_moved_to_cleveland": str(
            rights.get("1631130", {}).get("current_owner", "")
        ).upper()
        == "CLE",
        "live_start_ui_is_wired": "render_live_franchise_start(runtime, state, trade_state)"
        in page_text
        and "LIVE_START_CONFIRMATION_PHRASE" in ui_text
        and "Build live-start preview" in ui_text
        and "empirical_overalls" in ui_text
        and "sourced_stat_profiles" in ui_text
        and "sourced_shooting_profiles" in ui_text
        and "sourced_skill_profiles" in ui_text
        and "calibrated_potential_profiles" in ui_text,
        "draft_ui_guard_matches_renderer_contract": 'if "set_section" not in _draft_parameters:'
        in page_text
        and '"advance_next_season" not in _draft_parameters' not in page_text,
        "commit_uses_explicit_checkpoint_path": live_start_text.count(
            "path=primary,"
        )
        >= 3,
    }

    checkpoint_after = _sha256(checkpoint_path)
    checks["validator_does_not_modify_checkpoint"] = checkpoint_before == checkpoint_after
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
        "summary": {
            "cutoff_date": first.cutoff_date,
            "fingerprint": first.fingerprint,
            "players": len(state.players),
            "rostered_players": first.rostered_players,
            "free_agents": first.free_agents,
            "minimum_roster": min(roster_sizes.values()),
            "maximum_roster": max(roster_sizes.values()),
            "schedule_games": len(state.schedule),
            "resolved_detailed_contracts": financial_scope.get(
                "detailed_contracts_resolved"
            ),
            "salary_cap_hit_differences": financial_scope.get("cap_hit_differences"),
            "unresolved_current_contract_amounts": first.unresolved_current_contract_amounts,
            "externally_sourced_overall_ratings": profile_scope.get(
                "externally_sourced_overall_count"
            ),
            "empirically_calibrated_overall_ratings": profile_scope.get(
                "empirically_calibrated_overall_count"
            ),
            "source_informed_overall_ratings": profile_scope.get(
                "source_informed_overall_count"
            ),
            "source_informed_statistical_profiles": profile_scope.get(
                "detailed_statistical_profiles_sourced"
            ),
            "source_informed_shooting_profiles": profile_scope.get(
                "shooting_efficiency_profiles_sourced"
            ),
            "source_informed_skill_profiles": profile_scope.get(
                "broader_skill_ratings_source_informed"
            ),
            "age_and_production_calibrated_potential_profiles": profile_scope.get(
                "potential_profiles_age_and_production_calibrated"
            ),
            "statistical_profile_source_distribution": profile_scope.get(
                "statistical_profile_source_distribution"
            ),
            "statistical_profile_translation_version": profile_scope.get(
                "statistical_profile_translation_version"
            ),
            "empirical_proxy_players": [
                {
                    "player_id": player_id,
                    "player_name": state.players[player_id].player_name,
                    "overall_rating": state.players[player_id].overall_rating,
                    "potential_rating": state.players[player_id].potential_rating,
                    "future_outlook_rating": state.players[player_id].future_outlook_rating,
                    "production_source_url": getattr(
                        state.players[player_id],
                        "live_reference_profile_evidence",
                        {},
                    ).get("production_source_url"),
                    "translated_adjustment": getattr(
                        state.players[player_id],
                        "live_reference_profile_evidence",
                        {},
                    ).get("translated_adjustment"),
                    "skill_ratings": copy.deepcopy(
                        state.players[player_id].skill_ratings
                    ),
                }
                for player_id in sorted(expected_empirical_overalls)
            ],
            "opening_blockers": list(opening.blockers),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError("Live franchise start validation failed: " + ", ".join(failed))
    print()
    print("FRANCHISE LIVE START V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
