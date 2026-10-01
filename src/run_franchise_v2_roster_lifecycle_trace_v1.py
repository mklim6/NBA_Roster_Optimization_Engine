from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import traceback
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TRACE_VERSION = "franchise-v2-roster-lifecycle-trace-v1.0.4-2026-09-25"
DEFAULT_TARGET_MIN = 14
DEFAULT_TARGET_MAX = 15


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_stage(label: str) -> str:
    text = _clean(label).lower()
    if "frozen live start" in text:
        return "FROZEN_LIVE_START"
    if "restore" in text:
        return "RESTORE"
    if "opening regular season" in text:
        return "REGULAR_SEASON_OPEN"
    if "regular-season-complete" in text or "regular season complete" in text:
        return "REGULAR_SEASON_COMPLETE"
    if "postseason-init" in text or "postseason init" in text:
        return "POSTSEASON_START"
    if "postseason-complete" in text or "postseason complete" in text or "champion" in text:
        return "POSTSEASON_COMPLETE"
    if "closeout" in text:
        return "CONTRACT_CLOSEOUT"
    if "cpu fa round" in text:
        return "FREE_AGENCY_PRE_ROUND"
    if "cpu fa complete" in text:
        return "FREE_AGENCY_CLOSE"
    if "draft-complete" in text or "draft complete" in text:
        return "DRAFT_COMPLETE"
    if "post-draft trim" in text or "post_draft_trim" in text:
        return "POST_DRAFT_TRIM"
    if "second-roundtrip" in text:
        return "NEXT_SEASON_ROUNDTRIP"
    if "boundary" in text:
        return "NEXT_SEASON_BOUNDARY"
    return "OTHER"


def _team_rosters(state: Any) -> dict[str, tuple[str, ...]]:
    rows: dict[str, tuple[str, ...]] = {}
    for team, team_state in sorted((getattr(state, "teams", {}) or {}).items()):
        rows[_team(team)] = tuple(
            _clean(pid)
            for pid in (getattr(team_state, "roster_player_ids", ()) or ())
            if _clean(pid)
        )
    return rows


def _roster_contract_breakdown(
    state: Any,
    roster: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Classify team-associated roster ids without mutating simulation state.

    The legacy lifecycle ``roster_count`` intentionally remains the raw
    ``team_state.roster_player_ids`` count for historical comparison.  Phase 1
    contract acceptance must not use that raw total as a proxy for standard
    contracts because two-way players are also team-associated.

    Classification is deliberately evidence-based:
      * two-way: player.two_way is true OR roster_status == "two_way";
      * other non-standard: explicit exhibit_10 or free_agent status while the
        player id is still present in the team's roster list;
      * standard: a known team-associated player without the above evidence;
      * unclassified: roster id is absent from state.players.

    Unclassified ids are kept separate so the diagnostic never silently turns
    missing player evidence into a standard contract.
    """

    players = getattr(state, "players", {}) or {}
    standard_ids: list[str] = []
    two_way_ids: list[str] = []
    other_ids: list[str] = []
    unclassified_ids: list[str] = []

    for raw_player_id in roster:
        player_id = _clean(raw_player_id)
        if not player_id:
            continue
        player = players.get(player_id)
        if player is None:
            unclassified_ids.append(player_id)
            continue

        roster_status = _clean(getattr(player, "roster_status", "")).lower()
        is_two_way = bool(getattr(player, "two_way", False)) or roster_status == "two_way"

        if is_two_way:
            two_way_ids.append(player_id)
        elif roster_status in {"exhibit_10", "free_agent"}:
            other_ids.append(player_id)
        else:
            standard_ids.append(player_id)

    return {
        "standard_player_ids": tuple(standard_ids),
        "two_way_player_ids": tuple(two_way_ids),
        "other_player_ids": tuple(other_ids),
        "unclassified_player_ids": tuple(unclassified_ids),
    }


def _player_names(state: Any) -> dict[str, str]:
    return {
        _clean(pid): _clean(getattr(player, "player_name", "")) or _clean(pid)
        for pid, player in (getattr(state, "players", {}) or {}).items()
        if _clean(pid)
    }


def _player_locations(state: Any) -> tuple[dict[str, str], dict[str, list[str]]]:
    rosters = _team_rosters(state)
    free_agents = {
        _clean(pid)
        for pid in (getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(pid)
    }
    all_players = {
        _clean(pid)
        for pid in (getattr(state, "players", {}) or {})
        if _clean(pid)
    }
    by_player: dict[str, list[str]] = defaultdict(list)
    for team, roster in rosters.items():
        for player_id in roster:
            by_player[player_id].append(team)

    locations: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for player_id in sorted(all_players | free_agents | set(by_player)):
        teams = sorted(set(by_player.get(player_id, [])))
        if len(teams) > 1:
            locations[player_id] = "MULTI:" + ",".join(teams)
            duplicates[player_id] = teams
        elif len(teams) == 1:
            locations[player_id] = teams[0]
        elif player_id in free_agents:
            locations[player_id] = "FA"
        elif player_id in all_players:
            locations[player_id] = "UNASSIGNED"
        else:
            locations[player_id] = "MISSING"
    return locations, duplicates


def _is_team_location(value: str) -> bool:
    text = _clean(value)
    return bool(text and text not in {"FA", "UNASSIGNED", "MISSING"} and not text.startswith("MULTI:"))


def _classify_location_change(previous: str, current: str, stage: str, label: str) -> str:
    stage_text = f"{stage} {label}".lower()
    prev_team = _is_team_location(previous)
    curr_team = _is_team_location(current)

    if prev_team and current == "FA":
        if "closeout" in stage_text:
            return "contract_expired_or_closeout_release"
        if "post_draft_trim" in stage_text or "post-draft trim" in stage_text:
            return "post_draft_trim_release"
        return "roster_to_free_agency"

    if previous == "FA" and curr_team:
        return "free_agent_signing"

    if previous in {"UNASSIGNED", "MISSING", ""} and curr_team:
        if "draft" in stage_text:
            return "draft_or_rookie_roster_integration"
        return "player_added_to_roster"

    if prev_team and current in {"UNASSIGNED", "MISSING"}:
        if "boundary" in stage_text or "roundtrip" in stage_text:
            return "retirement_or_boundary_removal"
        return "rostered_player_removed_from_population_or_assignment"

    if previous == "FA" and current in {"UNASSIGNED", "MISSING"}:
        if "boundary" in stage_text or "roundtrip" in stage_text:
            return "free_agent_retirement_or_boundary_removal"
        return "free_agent_removed_from_market_or_population"

    if prev_team and curr_team and previous != current:
        return "team_change"

    if previous.startswith("MULTI:") or current.startswith("MULTI:"):
        return "duplicate_ownership_change"

    return "location_change"


class RosterLifecycleTracer:
    def __init__(
        self,
        output_dir: Path,
        *,
        target_min: int = DEFAULT_TARGET_MIN,
        target_max: int = DEFAULT_TARGET_MAX,
    ) -> None:
        self.output_dir = output_dir
        self.target_min = int(target_min)
        self.target_max = int(target_max)
        self.sequence = 0
        self.team_rows: list[dict[str, Any]] = []
        self.population_rows: list[dict[str, Any]] = []
        self.player_events: list[dict[str, Any]] = []
        self.fa_offers: list[dict[str, Any]] = []
        self.fa_skipped_bids: list[dict[str, Any]] = []
        self.fa_markets: list[dict[str, Any]] = []
        self.fa_market_evaluations: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._last_locations: dict[str, str] | None = None
        self._known_names: dict[str, str] = {}
        self._round_calls_by_season: Counter[str] = Counter()
        self._plan_counter = 0
        self._last_stage_by_season: dict[str, str] = {}

    def error(self, where: str, exc: BaseException) -> None:
        self.errors.append(
            {
                "generated_at_utc": _utc_now(),
                "where": where,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

    def capture_state(
        self,
        state: Any,
        *,
        label: str,
        source: str = "checkpoint",
        event_hint: str = "",
    ) -> None:
        try:
            self._capture_state_impl(
                state,
                label=label,
                source=source,
                event_hint=event_hint,
            )
        except Exception as exc:
            self.error(f"capture_state:{label}", exc)

    def _capture_state_impl(
        self,
        state: Any,
        *,
        label: str,
        source: str,
        event_hint: str,
    ) -> None:
        self.sequence += 1
        seq = self.sequence
        season = _season(state)
        phase = _phase(state)
        stage = _canonical_stage(label)
        rosters = _team_rosters(state)
        names = _player_names(state)
        self._known_names.update(names)
        locations, duplicates = _player_locations(state)

        free_agents = {
            _clean(pid)
            for pid in (getattr(state, "free_agent_player_ids", ()) or ())
            if _clean(pid)
        }
        all_players = {
            _clean(pid)
            for pid in (getattr(state, "players", {}) or {})
            if _clean(pid)
        }
        rostered_ids = {pid for roster in rosters.values() for pid in roster}
        unassigned = sorted(all_players - rostered_ids - free_agents)
        counts = [len(roster) for roster in rosters.values()]
        minimum_game_players = int(
            getattr(getattr(state, "settings", None), "minimum_game_players", 8) or 8
        )

        financial_environment: dict[str, Any] = {}
        payroll_by_team: dict[str, float | None] = {}
        payroll_meta_by_team: dict[str, dict[str, Any]] = {}
        if phase == "offseason":
            try:
                from franchise_free_agency_financial_bridge_v1_2 import (
                    resolve_free_agency_financial_environment,
                )
                environment = resolve_free_agency_financial_environment(state)
                financial_environment = {
                    "fa_environment_status": _clean(getattr(environment, "status", "")),
                    "fa_market_season": _clean(getattr(environment, "season_label", "")),
                    "salary_cap": _number(getattr(environment, "salary_cap", None)),
                    "first_apron": _number(getattr(environment, "first_apron", None)),
                    "second_apron": _number(getattr(environment, "second_apron", None)),
                    "financial_source": _clean(getattr(environment, "source", "")),
                    "financial_reason": _clean(getattr(environment, "reason", "")),
                }
            except Exception as exc:
                self.error(f"financial_environment:{label}", exc)
                financial_environment = {
                    "fa_environment_status": "trace_error",
                    "financial_reason": f"{type(exc).__name__}: {exc}",
                }

            try:
                from franchise_free_agency_transaction_v1_1 import team_guaranteed_payroll
                for team in rosters:
                    try:
                        payroll, meta = team_guaranteed_payroll(state, team)
                        payroll_by_team[team] = float(payroll)
                        payroll_meta_by_team[team] = _safe_mapping(meta)
                    except Exception as exc:
                        payroll_by_team[team] = None
                        payroll_meta_by_team[team] = {
                            "error": f"{type(exc).__name__}: {exc}"
                        }
            except Exception as exc:
                self.error(f"payroll_import:{label}", exc)

        salary_cap = _number(financial_environment.get("salary_cap"))
        first_apron = _number(financial_environment.get("first_apron"))
        second_apron = _number(financial_environment.get("second_apron"))
        contract_breakdowns = {
            team: _roster_contract_breakdown(state, roster)
            for team, roster in rosters.items()
        }

        for team, roster in rosters.items():
            roster_count = len(roster)
            contract_breakdown = contract_breakdowns[team]
            standard_player_ids = contract_breakdown["standard_player_ids"]
            two_way_player_ids = contract_breakdown["two_way_player_ids"]
            other_player_ids = contract_breakdown["other_player_ids"]
            unclassified_player_ids = contract_breakdown["unclassified_player_ids"]
            standard_contract_count = len(standard_player_ids)
            two_way_contract_count = len(two_way_player_ids)
            other_roster_count = len(other_player_ids)
            unclassified_roster_count = len(unclassified_player_ids)
            payroll = payroll_by_team.get(team)
            cap_space = None
            first_apron_room = None
            second_apron_room = None
            if payroll is not None:
                if salary_cap is not None:
                    cap_space = salary_cap - payroll
                if first_apron is not None:
                    first_apron_room = first_apron - payroll
                if second_apron is not None:
                    second_apron_room = second_apron - payroll

            self.team_rows.append(
                {
                    "sequence": seq,
                    "generated_at_utc": _utc_now(),
                    "source": source,
                    "season_label": season,
                    "phase": phase,
                    "stage": stage,
                    "stage_label": label,
                    "team": team,
                    "roster_count": roster_count,
                    "total_roster_count": roster_count,
                    "roster_player_ids": "|".join(roster),
                    "standard_contract_count": standard_contract_count,
                    "standard_player_ids": "|".join(standard_player_ids),
                    "two_way_contract_count": two_way_contract_count,
                    "two_way_player_ids": "|".join(two_way_player_ids),
                    "other_roster_count": other_roster_count,
                    "other_roster_player_ids": "|".join(other_player_ids),
                    "unclassified_roster_count": unclassified_roster_count,
                    "unclassified_roster_player_ids": "|".join(unclassified_player_ids),
                    "contract_count_reconciles_to_total": (
                        standard_contract_count
                        + two_way_contract_count
                        + other_roster_count
                        + unclassified_roster_count
                        == roster_count
                    ),
                    "minimum_game_players": minimum_game_players,
                    "meets_game_floor": roster_count >= minimum_game_players,
                    "v2_target_min": self.target_min,
                    "v2_target_max": self.target_max,
                    "v2_target_deficit": max(0, self.target_min - roster_count),
                    "v2_target_slots_to_15": max(0, self.target_max - roster_count),
                    "below_v2_target": roster_count < self.target_min,
                    "above_v2_target": roster_count > self.target_max,
                    "standard_v2_target_deficit": max(
                        0, self.target_min - standard_contract_count
                    ),
                    "standard_v2_target_slots_to_15": max(
                        0, self.target_max - standard_contract_count
                    ),
                    "standard_below_v2_target": (
                        standard_contract_count < self.target_min
                    ),
                    "standard_above_v2_target": (
                        standard_contract_count > self.target_max
                    ),
                    "payroll": payroll,
                    "cap_space_vs_modeled_cap": cap_space,
                    "room_to_first_apron": first_apron_room,
                    "room_to_second_apron": second_apron_room,
                    "salary_rows_known": payroll_meta_by_team.get(team, {}).get(
                        "known_salary_rows"
                    ),
                    "salary_rows_missing_player_ids": "|".join(
                        payroll_meta_by_team.get(team, {}).get(
                            "missing_salary_player_ids", []
                        )
                        or []
                    ),
                    **financial_environment,
                }
            )

        standard_counts = [
            len(contract_breakdowns[team]["standard_player_ids"])
            for team in rosters
        ]
        two_way_counts = [
            len(contract_breakdowns[team]["two_way_player_ids"])
            for team in rosters
        ]
        other_counts = [
            len(contract_breakdowns[team]["other_player_ids"])
            for team in rosters
        ]
        unclassified_counts = [
            len(contract_breakdowns[team]["unclassified_player_ids"])
            for team in rosters
        ]

        self.population_rows.append(
            {
                "sequence": seq,
                "generated_at_utc": _utc_now(),
                "source": source,
                "season_label": season,
                "phase": phase,
                "stage": stage,
                "stage_label": label,
                "teams": len(rosters),
                "players": len(all_players),
                "rostered_players": len(rostered_ids),
                "free_agents": len(free_agents),
                "unassigned_players": len(unassigned),
                "duplicate_owned_players": len(duplicates),
                "minimum_roster": min(counts) if counts else 0,
                "maximum_roster": max(counts) if counts else 0,
                "average_roster": (
                    round(sum(counts) / len(counts), 3) if counts else 0.0
                ),
                "minimum_standard_contracts": (
                    min(standard_counts) if standard_counts else 0
                ),
                "maximum_standard_contracts": (
                    max(standard_counts) if standard_counts else 0
                ),
                "average_standard_contracts": (
                    round(sum(standard_counts) / len(standard_counts), 3)
                    if standard_counts
                    else 0.0
                ),
                "total_two_way_contracts": sum(two_way_counts),
                "maximum_two_way_contracts": (
                    max(two_way_counts) if two_way_counts else 0
                ),
                "total_other_roster_players": sum(other_counts),
                "teams_with_other_roster_players": sum(
                    1 for count in other_counts if count > 0
                ),
                "total_unclassified_roster_players": sum(unclassified_counts),
                "teams_with_unclassified_roster_players": sum(
                    1 for count in unclassified_counts if count > 0
                ),
                "teams_below_standard_v2_target": sum(
                    1 for count in standard_counts if count < self.target_min
                ),
                "teams_above_standard_v2_target": sum(
                    1 for count in standard_counts if count > self.target_max
                ),
                "teams_in_standard_v2_target_range": sum(
                    1
                    for count in standard_counts
                    if self.target_min <= count <= self.target_max
                ),
                "teams_below_game_floor": sum(
                    1 for count in counts if count < minimum_game_players
                ),
                "teams_below_v2_target": sum(
                    1 for count in counts if count < self.target_min
                ),
                "teams_in_v2_target_range": sum(
                    1 for count in counts if self.target_min <= count <= self.target_max
                ),
                "free_agent_share_of_player_population": (
                    round(len(free_agents) / len(all_players), 6)
                    if all_players
                    else 0.0
                ),
                "unassigned_player_ids": "|".join(unassigned),
                "duplicate_ownership": _json_text(duplicates),
                **financial_environment,
            }
        )

        if self._last_locations is not None:
            previous_locations = self._last_locations
            for player_id in sorted(set(previous_locations) | set(locations)):
                before = previous_locations.get(player_id, "MISSING")
                after = locations.get(player_id, "MISSING")
                if before == after:
                    continue
                event_type = _classify_location_change(
                    before,
                    after,
                    event_hint or stage,
                    label,
                )
                self.player_events.append(
                    {
                        "sequence": seq,
                        "generated_at_utc": _utc_now(),
                        "season_label": season,
                        "phase": phase,
                        "stage": stage,
                        "stage_label": label,
                        "event_hint": event_hint,
                        "event_type": event_type,
                        "player_id": player_id,
                        "player_name": self._known_names.get(player_id, player_id),
                        "location_before": before,
                        "location_after": after,
                    }
                )

        self._last_locations = locations
        self._last_stage_by_season[season] = stage

        if stage == "FREE_AGENCY_CLOSE":
            rounds = int(self._round_calls_by_season.get(season, 0))
            minimum_roster = min(counts) if counts else 0
            teams_below_target = sum(1 for count in counts if count < self.target_min)
            if (
                rounds == 0
                and counts
                and minimum_roster >= minimum_game_players
                and teams_below_target > 0
            ):
                self.operations.append(
                    {
                        "generated_at_utc": _utc_now(),
                        "season_label": season,
                        "operation": "free_agency_lifecycle_exit",
                        "status": "diagnostic_signal",
                        "reason": "protected_soak_pre_round_floor_gate_observed",
                        "round_calls": rounds,
                        "minimum_game_players": minimum_game_players,
                        "minimum_roster": minimum_roster,
                        "teams_below_v2_target": teams_below_target,
                        "note": (
                            "The protected lifecycle reached Free Agency close with "
                            "all teams at the game-ready floor, no CPU FA round call, "
                            "and one or more teams still below the V2 14-player target."
                        ),
                    }
                )

    def capture_closeout(self, before_state: Any, result: Any) -> None:
        try:
            after_state = getattr(result, "simulation_state", None)
            season = _season(before_state)
            self.operations.append(
                {
                    "generated_at_utc": _utc_now(),
                    "season_label": season,
                    "operation": "contract_closeout",
                    "status": _clean(getattr(result, "status", "")),
                    "contracts_decremented": int(
                        getattr(result, "contracts_decremented", 0) or 0
                    ),
                    "contracts_expired": int(
                        getattr(result, "contracts_expired", 0) or 0
                    ),
                    "trade_owners_released": int(
                        getattr(result, "trade_owners_released", 0) or 0
                    ),
                    "minimum_roster_after_closeout": int(
                        getattr(result, "minimum_roster_after_closeout", 0) or 0
                    ),
                    "affected_teams": "|".join(
                        getattr(result, "affected_teams", ()) or ()
                    ),
                }
            )
            if after_state is not None:
                self.capture_state(
                    after_state,
                    label=f"{season} closeout candidate",
                    source="closeout_result",
                    event_hint="contract_closeout",
                )
        except Exception as exc:
            self.error("capture_closeout", exc)

    def capture_trim(
        self,
        *,
        before_state: Any | None,
        result: Any,
    ) -> None:
        try:
            season = _season(before_state) if before_state is not None else ""
            roster_before = _team_rosters(before_state) if before_state is not None else {}
            owner_before: dict[str, str] = {}
            for team, roster in roster_before.items():
                for player_id in roster:
                    owner_before[player_id] = team
            released = tuple(
                _clean(pid)
                for pid in (getattr(result, "released_player_ids", ()) or ())
                if _clean(pid)
            )
            self.operations.append(
                {
                    "generated_at_utc": _utc_now(),
                    "season_label": season,
                    "operation": "post_draft_trim",
                    "status": _clean(getattr(result, "status", "")),
                    "released_player_count": len(released),
                    "released_player_ids": "|".join(released),
                    "team_release_counts": _json_text(
                        _safe_mapping(getattr(result, "team_release_counts", {}))
                    ),
                    "released_players_with_pretrim_team": _json_text(
                        {
                            player_id: owner_before.get(player_id, "")
                            for player_id in released
                        }
                    ),
                }
            )
        except Exception as exc:
            self.error("capture_trim", exc)

    def mark_round_call(
        self,
        state: Any,
        *,
        round_result: Any | None = None,
        increment: bool = True,
    ) -> None:
        season = _season(state)
        if increment:
            self._round_calls_by_season[season] += 1
        if round_result is None:
            return
        try:
            current_rosters = _team_rosters(state)
            minimum_game_players = int(
                getattr(getattr(state, "settings", None), "minimum_game_players", 8)
                or 8
            )
            self.operations.append(
                {
                    "generated_at_utc": _utc_now(),
                    "season_label": season,
                    "operation": "cpu_free_agency_round",
                    "status": _clean(getattr(round_result, "status", "")),
                    "committed_signing_count": int(
                        getattr(round_result, "committed_signing_count", 0) or 0
                    ),
                    "stop_reason": _clean(getattr(round_result, "stop_reason", "")),
                    "minimum_game_players": minimum_game_players,
                    "minimum_roster_before_round": (
                        min(map(len, current_rosters.values()))
                        if current_rosters
                        else 0
                    ),
                    "teams_below_v2_target_before_round": sum(
                        1
                        for roster in current_rosters.values()
                        if len(roster) < self.target_min
                    ),
                    "signings": _json_text(
                        [
                            {
                                "player_id": _clean(getattr(row, "player_id", "")),
                                "player_name": _clean(getattr(row, "player_name", "")),
                                "team": _team(
                                    getattr(row, "team_abbreviation", "")
                                ),
                                "annual_salary": _number(
                                    getattr(row, "annual_salary", None)
                                ),
                                "years": int(getattr(row, "years", 0) or 0),
                                "market_fingerprint": _clean(
                                    getattr(row, "market_fingerprint", "")
                                ),
                            }
                            for row in (getattr(round_result, "signings", ()) or ())
                        ]
                    ),
                }
            )
        except Exception as exc:
            self.error("mark_round_call", exc)

    def capture_fa_plan(
        self,
        state: Any,
        plan: Any,
        *,
        context: str,
    ) -> None:
        try:
            self._plan_counter += 1
            plan_id = self._plan_counter
            season = _season(state)
            board = getattr(plan, "board", None)
            offers = tuple(getattr(board, "offers", ()) or ())
            skipped = tuple(getattr(board, "skipped", ()) or ())
            markets = tuple(getattr(plan, "markets", ()) or ())

            self.operations.append(
                {
                    "generated_at_utc": _utc_now(),
                    "season_label": season,
                    "operation": "cpu_free_agency_read_only_plan",
                    "status": "captured",
                    "context": context,
                    "plan_id": plan_id,
                    "generated_offer_count": int(
                        getattr(plan, "generated_offer_count", len(offers)) or 0
                    ),
                    "market_count": int(
                        getattr(plan, "market_count", len(markets)) or 0
                    ),
                    "winner_market_count": int(
                        getattr(plan, "winner_market_count", 0) or 0
                    ),
                    "skipped_bid_count": len(skipped),
                    "plan_fingerprint": _clean(
                        getattr(plan, "plan_fingerprint", "")
                    ),
                }
            )

            for row in offers:
                preview = getattr(row, "preview", None)
                gate = getattr(preview, "financial_gate", None)
                self.fa_offers.append(
                    {
                        "plan_id": plan_id,
                        "context": context,
                        "season_label": season,
                        "player_id": _clean(getattr(row, "player_id", "")),
                        "player_name": _clean(getattr(row, "player_name", "")),
                        "team": _team(getattr(row, "team_abbreviation", "")),
                        "team_direction": _clean(
                            getattr(row, "team_direction", "")
                        ),
                        "target_fit_score": _number(
                            getattr(row, "target_fit_score", None)
                        ),
                        "target_tier": _clean(getattr(row, "target_tier", "")),
                        "market_salary_reference": _number(
                            getattr(row, "market_salary_reference", None)
                        ),
                        "annual_salary": _number(
                            getattr(row, "annual_salary", None)
                        ),
                        "years": int(getattr(row, "years", 0) or 0),
                        "financial_route": _clean(
                            getattr(row, "financial_route", "")
                        ),
                        "rights_classification": _clean(
                            getattr(row, "rights_classification", "")
                        ),
                        "prior_team": _team(getattr(row, "prior_team", "")),
                        "minimum_targeting_status": _clean(
                            getattr(row, "minimum_targeting_status", "")
                        ),
                        "minimum_targeting_reason_code": _clean(
                            getattr(row, "minimum_targeting_reason_code", "")
                        ),
                        "roster_construction_score": _number(
                            getattr(row, "roster_construction_score", None)
                        ),
                        "roster_construction_tier": _clean(
                            getattr(row, "roster_construction_tier", "")
                        ),
                        "roster_construction_reason_code": _clean(
                            getattr(row, "roster_construction_reason_code", "")
                        ),
                        "roster_position_family": _clean(
                            getattr(row, "roster_position_family", "")
                        ),
                        "roster_projected_role": _clean(
                            getattr(row, "roster_projected_role", "")
                        ),
                        "roster_offer_status": _clean(
                            getattr(row, "roster_offer_status", "")
                        ),
                        "roster_offer_reason_code": _clean(
                            getattr(row, "roster_offer_reason_code", "")
                        ),
                        "offer_economic_status": _clean(
                            getattr(row, "offer_economic_status", "")
                        ),
                        "offer_economic_tier": _clean(
                            getattr(row, "offer_economic_tier", "")
                        ),
                        "offer_economic_reason_code": _clean(
                            getattr(row, "offer_economic_reason_code", "")
                        ),
                        "preview_status": _clean(
                            getattr(preview, "status", "")
                        ),
                        "preview_can_commit": bool(
                            getattr(preview, "can_commit", False)
                        ),
                        "preview_message": _clean(
                            getattr(preview, "message", "")
                        ),
                        "financial_gate_status": _clean(
                            getattr(gate, "status", "")
                        ),
                        "financial_gate_reason": _clean(
                            getattr(gate, "reason", "")
                        ),
                        "preview_checks": _json_text(
                            _safe_mapping(getattr(preview, "checks", {}))
                        ),
                        "offer_fingerprint": _clean(
                            getattr(row, "offer_fingerprint", "")
                        ),
                    }
                )

            for row in skipped:
                self.fa_skipped_bids.append(
                    {
                        "plan_id": plan_id,
                        "context": context,
                        "season_label": season,
                        "player_id": _clean(getattr(row, "player_id", "")),
                        "player_name": _clean(getattr(row, "player_name", "")),
                        "team": _team(getattr(row, "team_abbreviation", "")),
                        "reason": _clean(getattr(row, "reason", "")),
                        "roster_construction_score": _number(
                            getattr(row, "roster_construction_score", None)
                        ),
                        "roster_construction_reason_code": _clean(
                            getattr(row, "roster_construction_reason_code", "")
                        ),
                        "offer_economic_score": _number(
                            getattr(row, "offer_economic_score", None)
                        ),
                        "offer_economic_reason_code": _clean(
                            getattr(row, "offer_economic_reason_code", "")
                        ),
                    }
                )

            for player_market in markets:
                market = getattr(player_market, "market", None)
                self.fa_markets.append(
                    {
                        "plan_id": plan_id,
                        "context": context,
                        "season_label": season,
                        "player_id": _clean(
                            getattr(player_market, "player_id", "")
                        ),
                        "player_name": _clean(
                            getattr(player_market, "player_name", "")
                        ),
                        "cpu_offer_count": int(
                            getattr(player_market, "cpu_offer_count", 0) or 0
                        ),
                        "market_status": _clean(getattr(market, "status", "")),
                        "offer_count": int(
                            getattr(market, "offer_count", 0) or 0
                        ),
                        "backend_pass_offer_count": int(
                            getattr(market, "backend_pass_offer_count", 0) or 0
                        ),
                        "accepted_offer_count": int(
                            getattr(market, "accepted_offer_count", 0) or 0
                        ),
                        "winner_team": _team(
                            getattr(market, "winner_team_abbreviation", "")
                        ),
                        "winner_utility_score": _number(
                            getattr(market, "winner_utility_score", None)
                        ),
                        "winning_margin": _number(
                            getattr(market, "winning_margin", None)
                        ),
                        "best_counter_team": _team(
                            getattr(
                                market,
                                "best_counter_team_abbreviation",
                                "",
                            )
                        ),
                        "best_counter_salary": _number(
                            getattr(market, "best_counter_salary", None)
                        ),
                        "rationale": " || ".join(
                            str(item)
                            for item in (
                                getattr(market, "rationale", ()) or ()
                            )
                        ),
                        "market_fingerprint": _clean(
                            getattr(market, "market_fingerprint", "")
                        ),
                    }
                )

                for evaluation in (
                    getattr(market, "evaluations", ()) or ()
                ):
                    self.fa_market_evaluations.append(
                        {
                            "plan_id": plan_id,
                            "context": context,
                            "season_label": season,
                            "player_id": _clean(
                                getattr(player_market, "player_id", "")
                            ),
                            "player_name": _clean(
                                getattr(player_market, "player_name", "")
                            ),
                            "team": _team(
                                getattr(evaluation, "team_abbreviation", "")
                            ),
                            "annual_salary": _number(
                                getattr(evaluation, "annual_salary", None)
                            ),
                            "years": int(
                                getattr(evaluation, "years", 0) or 0
                            ),
                            "utility_score": _number(
                                getattr(evaluation, "utility_score", None)
                            ),
                            "acceptance_threshold": _number(
                                getattr(
                                    evaluation,
                                    "acceptance_threshold",
                                    None,
                                )
                            ),
                            "player_decision_status": _clean(
                                getattr(
                                    evaluation,
                                    "player_decision_status",
                                    "",
                                )
                            ),
                            "accepted": bool(
                                getattr(evaluation, "accepted", False)
                            ),
                            "rank": int(
                                getattr(evaluation, "rank", 0) or 0
                            ),
                            "utility_gap_to_winner": _number(
                                getattr(
                                    evaluation,
                                    "utility_gap_to_winner",
                                    None,
                                )
                            ),
                            "decision_fingerprint": _clean(
                                getattr(
                                    evaluation,
                                    "decision_fingerprint",
                                    "",
                                )
                            ),
                        }
                    )
        except Exception as exc:
            self.error(f"capture_fa_plan:{context}", exc)

    def capture_transition(
        self,
        before_state: Any,
        after_state: Any,
        *,
        label: str,
        preview: Any | None = None,
    ) -> None:
        try:
            season = _season(before_state)
            lifecycle = {}
            retirement_plan = {}
            if isinstance(preview, Mapping):
                lifecycle = _safe_mapping(preview.get("career_lifecycle", {}))
                retirement_plan = _safe_mapping(
                    lifecycle.get("retirement_plan", {})
                )
            self.operations.append(
                {
                    "generated_at_utc": _utc_now(),
                    "season_label": season,
                    "operation": "season_transition_in_memory",
                    "status": "captured",
                    "target_season": _season(after_state),
                    "retirement_count": retirement_plan.get(
                        "retirement_count"
                    ),
                    "rostered_retirements": retirement_plan.get(
                        "rostered_retirements"
                    ),
                    "free_agent_retirements": retirement_plan.get(
                        "free_agent_retirements"
                    ),
                    "players_before": retirement_plan.get("players_before"),
                    "players_after_transition": lifecycle.get(
                        "players_after_transition"
                    ),
                }
            )
            self.capture_state(
                after_state,
                label=label,
                source="season_transition_in_memory",
                event_hint="season_boundary_retirement_transition",
            )
        except Exception as exc:
            self.error("capture_transition", exc)

    def capture_diagnostic_plan_if_useful(
        self,
        state: Any,
        *,
        builder: Any,
        context: str,
        max_targets_per_team: int = 8,
    ) -> None:
        try:
            plan = builder(
                state,
                controlled_teams=(),
                max_targets_per_team=max_targets_per_team,
            )
            self.capture_fa_plan(state, plan, context=context)
        except Exception as exc:
            self.error(f"diagnostic_plan:{context}", exc)

    def _stage_summary(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self.team_rows:
            grouped[
                (
                    _clean(row.get("season_label")),
                    _clean(row.get("stage")),
                    _clean(row.get("stage_label")),
                )
            ].append(row)

        rows: list[dict[str, Any]] = []
        for (season, stage, label), values in sorted(
            grouped.items(),
            key=lambda item: min(int(r["sequence"]) for r in item[1]),
        ):
            counts = [int(row.get("roster_count", 0) or 0) for row in values]
            standard_counts = [
                int(row.get("standard_contract_count", 0) or 0)
                for row in values
            ]
            two_way_counts = [
                int(row.get("two_way_contract_count", 0) or 0)
                for row in values
            ]
            other_counts = [
                int(row.get("other_roster_count", 0) or 0)
                for row in values
            ]
            unclassified_counts = [
                int(row.get("unclassified_roster_count", 0) or 0)
                for row in values
            ]
            rows.append(
                {
                    "season_label": season,
                    "stage": stage,
                    "stage_label": label,
                    "first_sequence": min(
                        int(row.get("sequence", 0) or 0) for row in values
                    ),
                    "teams": len(values),
                    "average_roster": (
                        round(sum(counts) / len(counts), 3)
                        if counts
                        else 0.0
                    ),
                    "minimum_roster": min(counts) if counts else 0,
                    "maximum_roster": max(counts) if counts else 0,
                    "teams_below_v2_target": sum(
                        1 for count in counts if count < self.target_min
                    ),
                    "teams_in_v2_target_range": sum(
                        1
                        for count in counts
                        if self.target_min <= count <= self.target_max
                    ),
                    "total_v2_roster_deficit": sum(
                        max(0, self.target_min - count)
                        for count in counts
                    ),
                    "average_standard_contracts": (
                        round(sum(standard_counts) / len(standard_counts), 3)
                        if standard_counts
                        else 0.0
                    ),
                    "minimum_standard_contracts": (
                        min(standard_counts) if standard_counts else 0
                    ),
                    "maximum_standard_contracts": (
                        max(standard_counts) if standard_counts else 0
                    ),
                    "teams_below_standard_v2_target": sum(
                        1 for count in standard_counts if count < self.target_min
                    ),
                    "teams_above_standard_v2_target": sum(
                        1 for count in standard_counts if count > self.target_max
                    ),
                    "teams_in_standard_v2_target_range": sum(
                        1
                        for count in standard_counts
                        if self.target_min <= count <= self.target_max
                    ),
                    "total_standard_v2_roster_deficit": sum(
                        max(0, self.target_min - count)
                        for count in standard_counts
                    ),
                    "total_two_way_contracts": sum(two_way_counts),
                    "maximum_two_way_contracts": (
                        max(two_way_counts) if two_way_counts else 0
                    ),
                    "total_other_roster_players": sum(other_counts),
                    "teams_with_other_roster_players": sum(
                        1 for count in other_counts if count > 0
                    ),
                    "total_unclassified_roster_players": sum(unclassified_counts),
                    "teams_with_unclassified_roster_players": sum(
                        1 for count in unclassified_counts if count > 0
                    ),
                }
            )
        return rows

    def _first_breaches(self) -> list[dict[str, Any]]:
        rows = sorted(
            self.team_rows,
            key=lambda row: int(row.get("sequence", 0) or 0),
        )
        first: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if not bool(row.get("below_v2_target")):
                continue
            key = (_clean(row.get("season_label")), _team(row.get("team")))
            if key in first:
                continue
            first[key] = {
                "season_label": key[0],
                "team": key[1],
                "first_below_target_sequence": row.get("sequence"),
                "first_below_target_stage": row.get("stage"),
                "first_below_target_stage_label": row.get("stage_label"),
                "roster_count": row.get("roster_count"),
                "v2_target_deficit": row.get("v2_target_deficit"),
                "minimum_game_players": row.get("minimum_game_players"),
                "meets_game_floor": row.get("meets_game_floor"),
            }
        return list(first.values())

    def _first_standard_contract_breaches(self) -> list[dict[str, Any]]:
        rows = sorted(
            self.team_rows,
            key=lambda row: int(row.get("sequence", 0) or 0),
        )
        first: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if not bool(row.get("standard_below_v2_target")):
                continue
            key = (_clean(row.get("season_label")), _team(row.get("team")))
            if key in first:
                continue
            first[key] = {
                "season_label": key[0],
                "team": key[1],
                "first_below_standard_target_sequence": row.get("sequence"),
                "first_below_standard_target_stage": row.get("stage"),
                "first_below_standard_target_stage_label": row.get("stage_label"),
                "total_roster_count": row.get("total_roster_count"),
                "standard_contract_count": row.get("standard_contract_count"),
                "two_way_contract_count": row.get("two_way_contract_count"),
                "other_roster_count": row.get("other_roster_count"),
                "unclassified_roster_count": row.get("unclassified_roster_count"),
                "standard_v2_target_deficit": row.get(
                    "standard_v2_target_deficit"
                ),
            }
        return list(first.values())

    def _signals(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        for row in self.operations:
            if (
                row.get("operation") == "cpu_free_agency_round"
                and row.get("stop_reason") == "all_cpu_teams_meet_roster_floor"
                and int(row.get("teams_below_v2_target_before_round", 0) or 0) > 0
            ):
                signals.append(
                    {
                        "signal": "free_agency_floor_gate_stops_before_v2_target",
                        "season_label": row.get("season_label"),
                        "evidence": (
                            "A CPU Free Agency round stopped because every CPU team met "
                            "minimum_game_players while teams still remained below 14."
                        ),
                    }
                )

            if row.get("reason") == "protected_soak_pre_round_floor_gate_observed":
                signals.append(
                    {
                        "signal": "protected_soak_skips_normal_market_once_game_floor_met",
                        "season_label": row.get("season_label"),
                        "evidence": row.get("note"),
                    }
                )

        stage_rows = self._stage_summary()
        for row in stage_rows:
            if (
                row.get("stage") == "POST_DRAFT_TRIM"
                and int(row.get("teams_below_v2_target", 0) or 0) > 0
            ):
                signals.append(
                    {
                        "signal": "post_draft_trim_leaves_v2_target_deficits",
                        "season_label": row.get("season_label"),
                        "evidence": (
                            f"{row.get('teams_below_v2_target')} teams are below 14 "
                            f"after post-Draft trim; total deficit="
                            f"{row.get('total_v2_roster_deficit')}."
                        ),
                    }
                )

            if (
                row.get("stage") == "POST_DRAFT_TRIM"
                and int(row.get("teams_below_standard_v2_target", 0) or 0) > 0
            ):
                signals.append(
                    {
                        "signal": "post_draft_trim_leaves_standard_contract_deficits",
                        "season_label": row.get("season_label"),
                        "evidence": (
                            f"{row.get('teams_below_standard_v2_target')} teams have "
                            f"fewer than {self.target_min} standard contracts after "
                            f"post-Draft trim; total standard-contract deficit="
                            f"{row.get('total_standard_v2_roster_deficit')}."
                        ),
                    }
                )

            if (
                row.get("stage") == "POST_DRAFT_TRIM"
                and int(row.get("teams_above_standard_v2_target", 0) or 0) > 0
            ):
                signals.append(
                    {
                        "signal": "post_draft_trim_exceeds_standard_contract_target",
                        "season_label": row.get("season_label"),
                        "evidence": (
                            f"{row.get('teams_above_standard_v2_target')} teams have "
                            f"more than {self.target_max} standard contracts after "
                            "post-Draft trim."
                        ),
                    }
                )

            if (
                row.get("stage") == "POST_DRAFT_TRIM"
                and int(row.get("teams_with_unclassified_roster_players", 0) or 0) > 0
            ):
                signals.append(
                    {
                        "signal": "post_draft_trim_has_unclassified_roster_players",
                        "season_label": row.get("season_label"),
                        "evidence": (
                            f"{row.get('teams_with_unclassified_roster_players')} teams "
                            "contain roster ids missing from state.players after "
                            "post-Draft trim."
                        ),
                    }
                )

        if self.fa_skipped_bids:
            reasons = Counter(
                _clean(row.get("reason"))
                or _clean(row.get("roster_construction_reason_code"))
                or _clean(row.get("offer_economic_reason_code"))
                or "unknown"
                for row in self.fa_skipped_bids
            )
            for reason, count in reasons.most_common(5):
                signals.append(
                    {
                        "signal": "frequent_skipped_cpu_bid_reason",
                        "season_label": "",
                        "evidence": f"{reason}: {count} skipped bid(s)",
                    }
                )

        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, Any]] = []
        for row in signals:
            key = (
                _clean(row.get("signal")),
                _clean(row.get("season_label")),
                _clean(row.get("evidence")),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def write(self, *, soak_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stage_summary = self._stage_summary()
        first_breaches = self._first_breaches()
        first_standard_contract_breaches = (
            self._first_standard_contract_breaches()
        )
        signals = self._signals()

        _csv_write(self.output_dir / "roster_lifecycle_team_stages.csv", self.team_rows)
        _csv_write(self.output_dir / "roster_lifecycle_population_stages.csv", self.population_rows)
        _csv_write(self.output_dir / "roster_lifecycle_player_events.csv", self.player_events)
        _csv_write(self.output_dir / "roster_lifecycle_fa_offers.csv", self.fa_offers)
        _csv_write(self.output_dir / "roster_lifecycle_fa_skipped_bids.csv", self.fa_skipped_bids)
        _csv_write(self.output_dir / "roster_lifecycle_fa_markets.csv", self.fa_markets)
        _csv_write(
            self.output_dir / "roster_lifecycle_fa_market_evaluations.csv",
            self.fa_market_evaluations,
        )
        _csv_write(self.output_dir / "roster_lifecycle_operations.csv", self.operations)
        _csv_write(self.output_dir / "roster_lifecycle_stage_summary.csv", stage_summary)
        _csv_write(self.output_dir / "roster_lifecycle_first_breach.csv", first_breaches)
        _csv_write(
            self.output_dir / "roster_lifecycle_first_standard_contract_breach.csv",
            first_standard_contract_breaches,
        )
        _csv_write(self.output_dir / "roster_lifecycle_signals.csv", signals)

        summary = {
            "version": TRACE_VERSION,
            "generated_at_utc": _utc_now(),
            "target_min": self.target_min,
            "target_max": self.target_max,
            "contract_classification": {
                "standard": (
                    "known team-associated roster player without two-way, "
                    "exhibit_10, or free_agent evidence"
                ),
                "two_way": "player.two_way true or roster_status == two_way",
                "other": "explicit exhibit_10 or free_agent roster_status",
                "unclassified": "roster id absent from state.players",
                "legacy_roster_count_semantics": (
                    "raw team_state.roster_player_ids total; retained for "
                    "historical comparison and not valid as a standard-contract cap"
                ),
            },
            "output_dir": str(self.output_dir),
            "counts": {
                "team_stage_rows": len(self.team_rows),
                "population_stage_rows": len(self.population_rows),
                "player_events": len(self.player_events),
                "fa_offers": len(self.fa_offers),
                "fa_skipped_bids": len(self.fa_skipped_bids),
                "fa_markets": len(self.fa_markets),
                "fa_market_evaluations": len(self.fa_market_evaluations),
                "operations": len(self.operations),
                "errors": len(self.errors),
            },
            "first_breaches": first_breaches,
            "first_standard_contract_breaches": first_standard_contract_breaches,
            "signals": signals,
            "errors": self.errors,
            "soak_summary": {
                "passed": bool((soak_report or {}).get("passed")),
                "requested_seasons": (soak_report or {}).get("requested_seasons"),
                "completed_seasons": (soak_report or {}).get("completed_seasons"),
                "failed_checks": list((soak_report or {}).get("failed_checks", []) or []),
                "error": _clean((soak_report or {}).get("error", "")),
            },
        }
        (self.output_dir / "roster_lifecycle_summary.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        return summary



EXPECTED_V1_BASELINE = "f6e9a49"
EXPECTED_V2_FOUNDATION = "3c9a0dc"
EXPECTED_V2_BRANCH = "feature/franchise-v2"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _git_commit_exists(ref: str) -> bool:
    result = _git("cat-file", "-e", f"{ref}^{{commit}}", check=False)
    return result.returncode == 0


def _git_is_ancestor(ancestor: str, descendant: str = "HEAD") -> bool:
    result = _git(
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    return result.returncode == 0


def _v2_provenance_preflight() -> dict[str, Any]:
    """Validate V2 lineage without requiring the current tree to equal V1 bytes.

    The legacy protected soak was written for the Sep. 7 V1 release candidate
    and therefore requires every file in the V1 freeze manifest to retain its
    exact historical SHA-256. V2 intentionally changes some of those source
    files, so that check is not a valid V2 precondition.

    This preflight does NOT disable protected-save safety. The soak still runs
    entirely under its isolated checkpoint contract, and the tracer still
    compares the active checkpoint family before and after the run.

    Instead, V2 proves provenance:
      * the original freeze manifest is present and still describes the V1
        release candidate;
      * tag v1.0.0 resolves to the protected V1 baseline;
      * the current branch descends from that baseline;
      * the recorded V2 foundation checkpoint exists and is an ancestor of HEAD;
      * the active branch is feature/franchise-v2.

    V1 freeze-file differences are reported for audit visibility rather than
    treated as a failure, because V2 development is expected to diverge.
    """
    import run_franchise_protected_launch_smoke_v1 as launch

    manifest_path = Path(launch.FREEZE_MANIFEST)
    if not manifest_path.is_file():
        raise RuntimeError(
            "V2 provenance preflight cannot find the protected V1 freeze manifest."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    try:
        branch = _git("branch", "--show-current").stdout.strip()
        head = _git("rev-parse", "HEAD").stdout.strip()
        v1_commit = _git("rev-parse", "v1.0.0^{commit}").stdout.strip()
    except Exception as exc:
        raise RuntimeError(f"V2 provenance git preflight failed: {exc}") from exc

    checks = {
        "legacy_freeze_manifest_present": True,
        "legacy_freeze_is_immutable": manifest.get("immutable") is True,
        "legacy_release_id_matches": (
            manifest.get("release_id") == launch.EXPECTED_RELEASE_ID
        ),
        "legacy_cutoff_is_sep7": (
            manifest.get("cutoff_date") == launch.EXPECTED_CUTOFF
        ),
        "v2_branch_selected": branch == EXPECTED_V2_BRANCH,
        "v1_tag_matches_protected_baseline": v1_commit.startswith(
            EXPECTED_V1_BASELINE
        ),
        "head_descends_from_v1_baseline": _git_is_ancestor("v1.0.0", "HEAD"),
        "v2_foundation_commit_exists": _git_commit_exists(
            EXPECTED_V2_FOUNDATION
        ),
        "head_descends_from_v2_foundation": (
            _git_is_ancestor(EXPECTED_V2_FOUNDATION, "HEAD")
            if _git_commit_exists(EXPECTED_V2_FOUNDATION)
            else False
        ),
    }

    frozen_rows: list[dict[str, Any]] = []
    for row in manifest.get("frozen_files", []):
        rel = _clean(row.get("path"))
        path = ROOT / rel
        expected = _clean(row.get("sha256"))
        actual = None
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            actual = digest.hexdigest()
        frozen_rows.append(
            {
                "path": rel,
                "v1_expected_sha256": expected,
                "current_v2_sha256": actual,
                "still_matches_v1": bool(
                    expected and actual and expected == actual
                ),
            }
        )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "V2 provenance preflight failed: " + ", ".join(failed)
        )

    changed = [row for row in frozen_rows if not row["still_matches_v1"]]
    return {
        "mode": "v2_provenance_preflight",
        "checks": checks,
        "branch": branch,
        "head": head,
        "protected_v1_tag_commit": v1_commit,
        "v2_foundation": EXPECTED_V2_FOUNDATION,
        "legacy_frozen_files": frozen_rows,
        "legacy_frozen_files_changed_in_v2": len(changed),
        "legacy_frozen_changed_paths": [
            row["path"] for row in changed
        ],
        "note": (
            "V2 intentionally may differ from the V1 frozen file hashes. "
            "Current-run save isolation and active checkpoint-family equality "
            "remain mandatory."
        ),
        "expected_live_start": dict(
            manifest.get("expected_live_start", {}) or {}
        ),
    }


def _install_trace_hooks(
    tracer: RosterLifecycleTracer,
) -> tuple[Any, dict[str, Any]]:
    import run_franchise_protected_multi_season_soak_v1 as soak
    import franchise_completed_season_contract_closeout_v1 as closeout_api
    import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
    import franchise_cpu_post_draft_roster_trim_live_v1 as trim_api
    import franchise_draft_engine_v1 as draft_api
    import career_lifecycle_transition_adapter_v1 as transition_api
    import simulation_franchise_checkpoint_v1 as checkpoint_api

    originals: dict[str, Any] = {
        "soak_validate_release_freeze": soak._validate_release_freeze,
        "soak_checkpoint_or_raise": soak._checkpoint_or_raise,
        "soak_save_and_assert_roundtrip": soak._save_and_assert_roundtrip,
        "transition_commit_season_transition_preview": transition_api.commit_season_transition_preview,
        "closeout_commit": closeout_api.commit_completed_season_contract_closeout_durably,
        "cpu_build_plan": cpu_fa_api.build_cpu_free_agency_execution_plan,
        "cpu_round": cpu_fa_api.execute_cpu_free_agency_round_durably,
        "trim_commit": trim_api.commit_atomic_cpu_post_draft_trim_live,
        "draft_activate_rookies": draft_api.activate_drafted_rookies_after_transition,
    }

    def traced_checkpoint_or_raise(*args: Any, **kwargs: Any) -> Any:
        checkpoint = originals["soak_checkpoint_or_raise"](*args, **kwargs)
        label = ""
        if len(args) >= 3:
            label = _clean(args[2])
        elif "label" in kwargs:
            label = _clean(kwargs.get("label"))

        if _canonical_stage(label) != "RESTORE":
            tracer.capture_state(
                checkpoint.simulation_state,
                label=label or "checkpoint_reload",
                source="checkpoint_reload",
            )

        if _canonical_stage(label) == "FREE_AGENCY_CLOSE":
            tracer.capture_diagnostic_plan_if_useful(
                checkpoint.simulation_state,
                builder=originals["cpu_build_plan"],
                context="free_agency_close_read_only_diagnostic",
                max_targets_per_team=8,
            )
        return checkpoint

    def traced_save_and_assert_roundtrip(*args: Any, **kwargs: Any) -> Any:
        result = originals["soak_save_and_assert_roundtrip"](*args, **kwargs)
        checkpoint = result[0] if isinstance(result, tuple) and result else None
        reason = _clean(kwargs.get("reason"))
        if checkpoint is not None:
            tracer.capture_state(
                checkpoint.simulation_state,
                label=reason or "checkpoint_roundtrip",
                source="checkpoint_roundtrip",
            )
        return result

    def traced_closeout(*args: Any, **kwargs: Any) -> Any:
        before_state = args[0] if args else kwargs.get("state")
        result = originals["closeout_commit"](*args, **kwargs)
        if before_state is not None:
            tracer.capture_closeout(before_state, result)
            after_state = getattr(result, "simulation_state", None)
            if after_state is not None:
                tracer.capture_diagnostic_plan_if_useful(
                    after_state,
                    builder=originals["cpu_build_plan"],
                    context="post_closeout_read_only_diagnostic",
                    max_targets_per_team=8,
                )
        return result

    def traced_build_plan(*args: Any, **kwargs: Any) -> Any:
        plan = originals["cpu_build_plan"](*args, **kwargs)
        state = args[0] if args else kwargs.get("state")
        if state is not None:
            tracer.capture_fa_plan(
                state,
                plan,
                context="cpu_execution_internal_plan",
            )
        return plan

    def traced_round(*args: Any, **kwargs: Any) -> Any:
        checkpoint = checkpoint_api.load_franchise_checkpoint()
        state = getattr(checkpoint, "simulation_state", None) if checkpoint else None
        if state is not None:
            tracer.mark_round_call(state)
        result = originals["cpu_round"](*args, **kwargs)
        if state is not None:
            tracer.mark_round_call(
                state,
                round_result=result,
                increment=False,
            )
        return result

    def traced_trim(*args: Any, **kwargs: Any) -> Any:
        checkpoint = checkpoint_api.load_franchise_checkpoint()
        before_state = getattr(checkpoint, "simulation_state", None) if checkpoint else None
        if before_state is not None:
            tracer.capture_state(
                before_state,
                label=f"{_season(before_state)} draft complete before post-Draft trim",
                source="pre_trim_checkpoint",
                event_hint="draft_complete",
            )
        result = originals["trim_commit"](*args, **kwargs)
        tracer.capture_trim(before_state=before_state, result=result)
        return result

    def traced_transition(*args: Any, **kwargs: Any) -> Any:
        before_state = args[0] if args else kwargs.get("state")
        preview = args[1] if len(args) >= 2 else kwargs.get("preview")
        transitioned, result = originals["transition_commit_season_transition_preview"](
            *args, **kwargs
        )
        if before_state is not None:
            tracer.capture_transition(
                before_state,
                transitioned,
                label=(
                    f"{_season(before_state)} -> {_season(transitioned)} "
                    "career lifecycle transition"
                ),
                preview=preview,
            )
        return transitioned, result

    def traced_activate_rookies(*args: Any, **kwargs: Any) -> Any:
        state = args[0] if args else kwargs.get("state")
        result = originals["draft_activate_rookies"](*args, **kwargs)
        if state is not None:
            tracer.capture_state(
                state,
                label=f"{_season(state)} drafted rookies activated",
                source="rookie_activation",
                event_hint="draft_rookie_activation",
            )
        return result

    soak._validate_release_freeze = _v2_provenance_preflight
    soak._checkpoint_or_raise = traced_checkpoint_or_raise
    soak._save_and_assert_roundtrip = traced_save_and_assert_roundtrip
    transition_api.commit_season_transition_preview = traced_transition
    closeout_api.commit_completed_season_contract_closeout_durably = traced_closeout
    cpu_fa_api.build_cpu_free_agency_execution_plan = traced_build_plan
    cpu_fa_api.execute_cpu_free_agency_round_durably = traced_round
    trim_api.commit_atomic_cpu_post_draft_trim_live = traced_trim
    draft_api.activate_drafted_rookies_after_transition = traced_activate_rookies

    return soak, originals


def _restore_trace_hooks(soak: Any, originals: Mapping[str, Any]) -> None:
    import franchise_completed_season_contract_closeout_v1 as closeout_api
    import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
    import franchise_cpu_post_draft_roster_trim_live_v1 as trim_api
    import franchise_draft_engine_v1 as draft_api
    import career_lifecycle_transition_adapter_v1 as transition_api

    soak._validate_release_freeze = originals["soak_validate_release_freeze"]
    soak._checkpoint_or_raise = originals["soak_checkpoint_or_raise"]
    soak._save_and_assert_roundtrip = originals["soak_save_and_assert_roundtrip"]
    transition_api.commit_season_transition_preview = originals[
        "transition_commit_season_transition_preview"
    ]
    closeout_api.commit_completed_season_contract_closeout_durably = originals[
        "closeout_commit"
    ]
    cpu_fa_api.build_cpu_free_agency_execution_plan = originals["cpu_build_plan"]
    cpu_fa_api.execute_cpu_free_agency_round_durably = originals["cpu_round"]
    trim_api.commit_atomic_cpu_post_draft_trim_live = originals["trim_commit"]
    draft_api.activate_drafted_rookies_after_transition = originals[
        "draft_activate_rookies"
    ]


def run_trace(
    *,
    seasons: int,
    target_min: int,
    target_max: int,
    keep_soak_artifacts: bool,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if seasons < 1 or seasons > 10:
        raise ValueError("--seasons must be between 1 and 10.")
    if target_min < 5 or target_max < target_min:
        raise ValueError("Invalid V2 target roster range.")

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import run_franchise_protected_multi_season_soak_v1 as soak_base

    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = soak_base._checkpoint_family_hashes(active_primary)

    trace_dir = (
        output_dir
        if output_dir is not None
        else ROOT / "outputs" / "v2_roster_lifecycle_trace_v1" / f"trace_{_stamp()}"
    )
    tracer = RosterLifecycleTracer(
        trace_dir,
        target_min=target_min,
        target_max=target_max,
    )

    soak, originals = _install_trace_hooks(tracer)
    soak_report: dict[str, Any] = {}
    run_error = ""
    try:
        soak_report = soak.run_soak(
            seasons=seasons,
            keep_artifacts=keep_soak_artifacts,
        )
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        tracer.error("protected_soak", exc)
    finally:
        _restore_trace_hooks(soak, originals)

    active_after = soak_base._checkpoint_family_hashes(active_primary)
    active_unchanged = active_before == active_after

    if not active_unchanged:
        tracer.operations.append(
            {
                "generated_at_utc": _utc_now(),
                "operation": "active_checkpoint_safety",
                "status": "FAIL",
                "reason": "active_checkpoint_family_changed",
            }
        )

    summary = tracer.write(soak_report=soak_report)
    summary["active_checkpoint_family_unchanged"] = active_unchanged
    summary["active_checkpoint_family_before"] = active_before
    summary["active_checkpoint_family_after"] = active_after
    summary["run_error"] = run_error
    summary["trace_passed"] = bool(
        active_unchanged
        and not run_error
        and soak_report
        and bool(soak_report.get("passed"))
    )
    (trace_dir / "roster_lifecycle_summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the protected Franchise lifecycle with read-only V2 roster "
            "diagnostics. The active franchise checkpoint must remain unchanged."
        )
    )
    parser.add_argument(
        "--seasons",
        type=int,
        default=1,
        help="Complete protected seasons to trace. Start with 1; acceptance later uses 8.",
    )
    parser.add_argument("--target-min", type=int, default=DEFAULT_TARGET_MIN)
    parser.add_argument("--target-max", type=int, default=DEFAULT_TARGET_MAX)
    parser.add_argument(
        "--keep-soak-artifacts",
        action="store_true",
        help="Preserve the protected soak's temporary checkpoint family in addition to trace CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional explicit trace output directory.",
    )
    args = parser.parse_args()

    print("FRANCHISE V2 ROSTER LIFECYCLE TRACE V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Execution target: isolated protected checkpoint")
    print("Active franchise mutation: FORBIDDEN")
    print(f"V2 standard-contract target: {args.target_min}-{args.target_max}")
    print(f"Protected seasons: {args.seasons}")
    print()

    summary = run_trace(
        seasons=args.seasons,
        target_min=args.target_min,
        target_max=args.target_max,
        keep_soak_artifacts=args.keep_soak_artifacts,
        output_dir=args.output_dir,
    )

    print("TRACE SUMMARY")
    counts = summary.get("counts", {})
    print(f"  Team-stage rows: {counts.get('team_stage_rows', 0)}")
    print(f"  Player events: {counts.get('player_events', 0)}")
    print(f"  FA offers: {counts.get('fa_offers', 0)}")
    print(f"  FA skipped bids: {counts.get('fa_skipped_bids', 0)}")
    print(f"  FA market evaluations: {counts.get('fa_market_evaluations', 0)}")
    print(f"  Diagnostic errors: {counts.get('errors', 0)}")
    print(
        "  Active checkpoint unchanged: "
        + ("YES" if summary.get("active_checkpoint_family_unchanged") else "NO")
    )
    print(f"  Output: {summary.get('output_dir')}")
    print()

    signals = list(summary.get("signals", []) or [])
    if signals:
        print("DIAGNOSTIC SIGNALS")
        for signal in signals[:12]:
            season = _clean(signal.get("season_label"))
            prefix = f"{season}: " if season else ""
            print(
                f"  - {prefix}{signal.get('signal')}: "
                f"{signal.get('evidence')}"
            )
        print()

    if summary.get("trace_passed"):
        print("FRANCHISE V2 ROSTER LIFECYCLE TRACE V1 PASSED")
        return 0

    print("FRANCHISE V2 ROSTER LIFECYCLE TRACE V1 DID NOT FULLY PASS")
    if summary.get("run_error"):
        print(f"Run error: {summary['run_error']}")
    soak_summary = dict(summary.get("soak_summary", {}) or {})
    if soak_summary.get("error"):
        print(f"Soak error: {soak_summary['error']}")
    failed_checks = list(soak_summary.get("failed_checks", []) or [])
    if failed_checks:
        print("Soak failed checks:")
        for name in failed_checks:
            print(f"  - {name}")
    if not summary.get("active_checkpoint_family_unchanged"):
        print("CRITICAL: active checkpoint family changed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
