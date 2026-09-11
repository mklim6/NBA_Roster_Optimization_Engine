from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from freeform_trade_machine_engine_v3 import (
    RuntimeData,
    normalize_player_id,
    normalize_status,
    normalize_team,
    parse_rounds,
    parse_tokens,
    source_asset_round,
    to_bool,
    to_float,
    to_int,
)
from franchise_draft_forfeitures_v1 import apply_draft_pick_forfeitures


ASSET_LEDGER_VERSION = (
    "franchise-live-asset-ledger-v1.2-pick-forfeitures-2026-09-07"
)
DRAFT_HORIZON_YEARS = 7


class FranchiseLiveAssetLedgerError(RuntimeError):
    """Raised when a live franchise asset ledger cannot be built safely."""


@dataclass(frozen=True)
class FranchiseAssetLedger:
    version: str
    season_label: str
    next_draft_year: int
    horizon_end_year: int
    player_rows: tuple[dict[str, Any], ...]
    draft_rows: tuple[dict[str, Any], ...]

    @property
    def generated_player_count(self) -> int:
        return sum(bool(row.get("generated_player")) for row in self.player_rows)

    @property
    def free_agent_count(self) -> int:
        return sum(row.get("roster_status") == "free_agent" for row in self.player_rows)

    @property
    def draft_manual_review_count(self) -> int:
        return sum(bool(row.get("manual_review_required")) for row in self.draft_rows)

    @property
    def engine_ready_pick_count(self) -> int:
        return sum(bool(row.get("engine_ready")) for row in self.draft_rows)

    @property
    def forfeited_pick_count(self) -> int:
        return sum(
            row.get("forfeiture_status") == "forfeited"
            for row in self.draft_rows
        )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def season_end_year(season_label: str) -> int:
    text = clean_text(season_label)
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", text)
    if not match:
        raise FranchiseLiveAssetLedgerError(
            f"Unsupported season label for asset ledger: {season_label!r}."
        )
    start = int(match.group(1))
    suffix = match.group(2)
    if len(suffix) == 4:
        end = int(suffix)
    else:
        century = (start // 100) * 100
        end = century + int(suffix)
        if end < start:
            end += 100
    if end != start + 1:
        raise FranchiseLiveAssetLedgerError(
            f"Season label is not a one-year NBA season: {season_label!r}."
        )
    return end


def enum_value(value: Any) -> str:
    resolved = getattr(value, "value", value)
    return clean_text(resolved)


def player_role(overall: float) -> str:
    if overall >= 92:
        return "Franchise"
    if overall >= 86:
        return "Star"
    if overall >= 80:
        return "Starter"
    if overall >= 74:
        return "Rotation"
    if overall >= 68:
        return "Bench"
    return "Depth"


def age_runway_score(age: float | None) -> float:
    if age is None:
        return 72.0
    # Keeps age important without allowing it to overwhelm current quality.
    score = 100.0 - max(age - 19.0, 0.0) * 3.15
    return max(35.0, min(100.0, score))


def franchise_asset_score(
    *,
    overall: float,
    potential: float,
    future: float,
    age: float | None,
) -> float:
    score = (
        0.52 * overall
        + 0.25 * potential
        + 0.13 * future
        + 0.10 * age_runway_score(age)
    )
    return round(max(50.0, min(99.5, score)), 1)


def _last_development_delta(player: Any) -> float | None:
    history = getattr(player, "development_history", None)
    if not isinstance(history, (list, tuple)) or not history:
        return None
    item = history[-1]
    if isinstance(item, dict):
        for key in (
            "overall_delta",
            "delta",
            "overall_change",
            "rating_delta",
        ):
            if key in item:
                return finite_float(item.get(key))
    for key in ("overall_delta", "delta", "overall_change", "rating_delta"):
        if hasattr(item, key):
            return finite_float(getattr(item, key))
    return None


def _career_status(state: Any, player_id: str) -> str:
    intents = getattr(state, "career_intent_by_player_id", {})
    if not isinstance(intents, dict):
        return "active"
    record = intents.get(player_id, {})
    if isinstance(record, dict):
        return clean_text(record.get("status")) or "active"
    return clean_text(getattr(record, "status", "")) or "active"


def _availability(state: Any, player_id: str) -> str:
    injury = getattr(state, "injuries", {}).get(player_id)
    if injury is None:
        return "unknown"
    return enum_value(getattr(injury, "status", "")) or "unknown"


def build_player_asset_rows(runtime: RuntimeData, state: Any) -> list[dict[str, Any]]:
    players = getattr(state, "players", {})
    if not isinstance(players, dict):
        raise FranchiseLiveAssetLedgerError("Simulation state does not expose a player dictionary.")

    free_agents = {
        normalize_player_id(player_id)
        for player_id in getattr(state, "free_agent_player_ids", ())
        if normalize_player_id(player_id)
    }
    baseline_ids = set(runtime.trade_by_id)
    rows: list[dict[str, Any]] = []

    for raw_id, player in players.items():
        player_id = normalize_player_id(raw_id)
        if not player_id:
            continue
        team = normalize_team(getattr(player, "team_abbreviation", ""))
        is_fa = player_id in free_agents or not team
        roster_status = "free_agent" if is_fa else "rostered"
        overall = finite_float(getattr(player, "overall_rating", None), 60.0) or 60.0
        potential = finite_float(getattr(player, "potential_rating", None), overall) or overall
        future = finite_float(getattr(player, "future_outlook_rating", None), potential) or potential
        age = finite_float(getattr(player, "age", None))
        contract = getattr(player, "contract", None)
        salary = finite_float(getattr(contract, "salary", None)) if contract is not None else None
        years = to_int(getattr(contract, "years_remaining", None)) if contract is not None else None
        generated = player_id not in baseline_ids or bool(getattr(player, "draft_class_id", ""))
        draft_year = to_int(getattr(player, "draft_year", None))
        role = clean_text(getattr(player, "role_label", "")) or player_role(overall)

        rows.append(
            {
                "player_id": player_id,
                "player_name": clean_text(getattr(player, "player_name", "")) or player_id,
                "team": team,
                "roster_status": roster_status,
                "position": clean_text(getattr(player, "position", "")) or "UNK",
                "age": age,
                "overall": round(overall, 1),
                "potential": round(potential, 1),
                "future_outlook": round(future, 1),
                "role": role,
                "development_direction": clean_text(
                    getattr(player, "development_direction", "")
                ) or "Unknown",
                "last_development_delta": _last_development_delta(player),
                "availability": _availability(state, player_id),
                "career_status": _career_status(state, player_id),
                "contract_status": clean_text(getattr(contract, "status", "")) if contract is not None else "",
                "salary": salary,
                "years_remaining": years,
                "option_type": clean_text(getattr(contract, "option_type", "")) if contract is not None else "",
                "guaranteed": getattr(contract, "guaranteed", None) if contract is not None else None,
                "two_way": bool(getattr(player, "two_way", False)),
                "draft_year": draft_year,
                "draft_class_id": clean_text(getattr(player, "draft_class_id", "")),
                "generated_player": generated,
                "asset_score": franchise_asset_score(
                    overall=overall,
                    potential=potential,
                    future=future,
                    age=age,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            row["team"] == "",
            row["team"],
            -float(row["asset_score"]),
            row["player_name"],
        )
    )
    return rows


def _right_year_bounds(record: dict[str, Any]) -> tuple[int | None, int | None]:
    minimum = to_int(record.get("draft_year_min"))
    maximum = to_int(record.get("draft_year_max"))
    if minimum is None:
        minimum = to_int(record.get("draft_year"))
    if maximum is None:
        maximum = minimum
    return minimum, maximum


def _canonical_right_status(
    runtime: RuntimeData,
    pick_right_id: str,
    record: dict[str, Any],
    owner: str,
) -> tuple[str, bool, bool, str]:
    if to_bool(record.get("standalone_trade_asset_flag")) is not True:
        return "Blocked", True, False, "Not a standalone trade asset."
    decision = runtime.right_legality_by_id.get(pick_right_id)
    if not isinstance(decision, dict):
        return "Manual Review", True, False, "No right-legality decision release covers this canonical right."
    evidence_team = normalize_team(decision.get("candidate_team"))
    if evidence_team and evidence_team != owner:
        return "Manual Review", True, False, "Right-legality evidence is tied to a different current owner."
    determination = normalize_status(decision.get("right_legality_determination"))
    if determination == "not_legal_as_modeled" or to_bool(decision.get("right_legality_blocked")) is True:
        return "Blocked", True, False, clean_text(decision.get("resolution_reason")) or "Right is not legal as modeled."
    if determination == "manual_review_required" or to_bool(decision.get("right_legality_manual_review_required")) is True:
        return "Manual Review", True, False, clean_text(decision.get("resolution_reason")) or "Right requires manual evidence review."
    if determination == "legal_with_conditions" and to_bool(decision.get("right_legality_stage_passed")) is True:
        return "Engine Ready", False, True, "Standalone right-evidence stage passed. Package Stepien/frozen-pick/full-CBA checks still apply."
    return "Manual Review", True, False, "Right-legality decision is incomplete or inconsistent."


def _canonical_draft_rows(
    runtime: RuntimeData,
    trade_state: Any,
    start_year: int,
    end_year: int,
) -> tuple[list[dict[str, Any]], set[str], set[tuple[str, int, int]]]:
    rows: list[dict[str, Any]] = []
    covered_sources: set[str] = set()
    owner_year_round: set[tuple[str, int, int]] = set()
    owner_map = getattr(trade_state, "pick_team_by_id", {})

    for pick_right_id, record in runtime.pick_by_id.items():
        minimum, maximum = _right_year_bounds(record)
        if maximum is not None and maximum < start_year:
            continue
        if minimum is not None and minimum > end_year:
            continue
        owner = normalize_team(owner_map.get(pick_right_id, record.get("candidate_team")))
        if not owner:
            continue
        rounds = sorted(parse_rounds(record.get("round_numbers"))) or [0]
        sources = parse_tokens(record.get("source_assets"))
        years = [year for year in range(max(start_year, minimum or start_year), min(end_year, maximum or end_year) + 1)]
        status, manual, engine_ready, reason = _canonical_right_status(runtime, pick_right_id, record, owner)
        display = clean_text(record.get("right_display_name")) or pick_right_id
        for year in years:
            for round_number in rounds:
                rows.append(
                    {
                        "asset_id": pick_right_id,
                        "draft_year": year,
                        "round": round_number,
                        "origin_team": ", ".join(sorted({normalize_team(x.split("_")[-1]) for x in sources if x})) or "Complex",
                        "current_owner": owner,
                        "asset_type": "canonical_trade_right",
                        "display_name": display,
                        "source_assets": " | ".join(sources),
                        "protection": clean_text(record.get("protection_status")) or clean_text(record.get("protection")),
                        "swap_status": clean_text(record.get("swap_status")),
                        "encumbrance": clean_text(record.get("encumbrance_status")),
                        "stepien_status": "Package evaluation required" if round_number == 1 else "Not applicable",
                        "tradability_status": status,
                        "manual_review_required": manual,
                        "manual_review_reason": reason,
                        "engine_ready": engine_ready,
                        "canonical_pick_right_id": pick_right_id,
                        "evidence_source": "2026-27 canonical Trade Machine right",
                    }
                )
                own_source_id = f"{year}_R{round_number}_{owner}"
                if own_source_id in sources:
                    owner_year_round.add((owner, year, round_number))
        for source in sources:
            covered_sources.add(source)

    return rows, covered_sources, owner_year_round


def _stepien_first_rows(
    runtime: RuntimeData,
    start_year: int,
    end_year: int,
    covered_sources: set[str],
) -> tuple[list[dict[str, Any]], set[tuple[str, int, int]], int | None]:
    frame = runtime.stepien
    rows: list[dict[str, Any]] = []
    covered: set[tuple[str, int, int]] = set()
    max_year: int | None = None
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return rows, covered, max_year
    required = {"team_abbreviation", "draft_year", "own_first_round_source_asset_id", "own_first_round_current_owner_team"}
    if not required.issubset(frame.columns):
        return rows, covered, max_year

    for record in frame.to_dict(orient="records"):
        year = to_int(record.get("draft_year"))
        if year is None:
            continue
        max_year = year if max_year is None else max(max_year, year)
        if year < start_year or year > end_year:
            continue
        source_id = clean_text(record.get("own_first_round_source_asset_id"))
        if not source_id or source_id in covered_sources:
            continue
        origin = normalize_team(record.get("team_abbreviation"))
        owner = normalize_team(record.get("own_first_round_current_owner_team"))
        if not origin or not owner:
            continue
        control = normalize_status(record.get("own_first_round_control_status"))
        retained = normalize_status(record.get("own_first_round_retained_status"))
        outgoing = normalize_status(record.get("own_first_round_outgoing_obligation_status"))
        swap = normalize_status(record.get("own_first_round_swap_status"))
        protection = normalize_status(record.get("own_first_round_protection_status"))
        encumbrance = normalize_status(record.get("own_first_round_encumbrance_status"))
        availability = normalize_status(record.get("deterministic_first_round_availability"))
        frozen = normalize_status(record.get("second_apron_frozen_pick_status"))
        complex_right = any(
            [
                control not in {"", "owned"},
                retained not in {"", "definitely_retained"},
                outgoing not in {"", "none"},
                swap not in {"", "none"},
                protection not in {"", "none", "unprotected"},
                encumbrance not in {"", "clear"},
                availability not in {"", "available"},
                frozen not in {"", "not_applicable", "not_frozen", "none"},
            ]
        )
        if complex_right:
            status = "⚠ Complex right · Manual Review"
            reason = "Protection, swap, obligation, availability, or frozen-pick evidence is not clean enough for automatic trade construction."
        else:
            status = "Verified · Bridge Needed"
            reason = "Physical first-round ownership is verified, but this source asset is not yet mapped to a canonical trade-right ID for automated package legality."
        rows.append(
            {
                "asset_id": source_id,
                "draft_year": year,
                "round": 1,
                "origin_team": origin,
                "current_owner": owner,
                "asset_type": "verified_stepien_physical_first",
                "display_name": f"{origin} {year} own first-round pick",
                "source_assets": source_id,
                "protection": protection or "unprotected",
                "swap_status": swap or "none",
                "encumbrance": encumbrance or "clear",
                "stepien_status": availability or "not_evaluated",
                "tradability_status": status,
                "manual_review_required": True,
                "manual_review_reason": reason,
                "engine_ready": False,
                "canonical_pick_right_id": "",
                "evidence_source": "Verified first-round Stepien calendar",
            }
        )
        covered.add((owner, year, 1))
    return rows, covered, max_year


def _procedural_rows(
    teams: Iterable[str],
    start_year: int,
    end_year: int,
    covered: set[tuple[str, int, int]],
    authoritative_first_max_year: int | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for team in sorted({normalize_team(team) for team in teams if normalize_team(team)}):
        for year in range(start_year, end_year + 1):
            for round_number in (1, 2):
                if (team, year, round_number) in covered:
                    continue
                if round_number == 1 and authoritative_first_max_year is not None and year <= authoritative_first_max_year:
                    # The authoritative first-round calendar covers this year. If no row
                    # resolved to this team, do not invent an own first for the team.
                    continue
                asset_id = f"FRANCHISE-{year}-R{round_number}-{team}"
                reason = (
                    "This future own pick is beyond the current authoritative first-round evidence horizon and is provisional until the franchise trade-right bridge creates/verifies it."
                    if round_number == 1
                    else "No franchise-native second-round ownership roll-forward has been legally reconciled yet; this own-pick placeholder is provisional."
                )
                rows.append(
                    {
                        "asset_id": asset_id,
                        "draft_year": year,
                        "round": round_number,
                        "origin_team": team,
                        "current_owner": team,
                        "asset_type": "procedural_future_own_pick",
                        "display_name": f"{team} {year} own {'first' if round_number == 1 else 'second'}-round pick (provisional)",
                        "source_assets": asset_id,
                        "protection": "unresolved",
                        "swap_status": "unresolved",
                        "encumbrance": "unresolved",
                        "stepien_status": "manual bridge required" if round_number == 1 else "not applicable",
                        "tradability_status": "Provisional · Manual Review",
                        "manual_review_required": True,
                        "manual_review_reason": reason,
                        "engine_ready": False,
                        "canonical_pick_right_id": "",
                        "evidence_source": "Procedural franchise horizon placeholder",
                    }
                )
    return rows


def build_draft_asset_rows(runtime: RuntimeData, state: Any, trade_state: Any) -> list[dict[str, Any]]:
    season = clean_text(getattr(getattr(state, "settings", None), "season_label", ""))
    start_year = season_end_year(season)
    end_year = start_year + DRAFT_HORIZON_YEARS - 1
    canonical, canonical_sources, covered = _canonical_draft_rows(runtime, trade_state, start_year, end_year)
    stepien, stepien_covered, max_stepien_year = _stepien_first_rows(
        runtime, start_year, end_year, canonical_sources
    )
    covered.update(stepien_covered)
    procedural = _procedural_rows(
        getattr(state, "teams", {}).keys(),
        start_year,
        end_year,
        covered,
        max_stepien_year,
    )
    rows = apply_draft_pick_forfeitures(canonical + stepien + procedural)

    # Franchise-native transactions persist draft-right ownership on the
    # SimulationLeagueState. Apply those overrides after rebuilding the
    # canonical / verified / procedural inventory so a traded right cannot
    # snap back to its source owner on a Streamlit rerun or checkpoint load.
    ownership_overrides = getattr(
        state,
        "franchise_draft_right_ownership_v1",
        {},
    )
    if ownership_overrides is None:
        ownership_overrides = {}
    if not isinstance(ownership_overrides, dict):
        raise FranchiseLiveAssetLedgerError(
            "franchise_draft_right_ownership_v1 must be a dictionary."
        )
    known_teams = {
        normalize_team(team)
        for team in getattr(state, "teams", {})
        if normalize_team(team)
    }
    for row in rows:
        if row.get("forfeiture_status") == "forfeited":
            row["franchise_transactional_owner"] = False
            continue
        asset_id = str(row.get("asset_id") or "").strip()
        if asset_id not in ownership_overrides:
            row["franchise_transactional_owner"] = False
            continue
        owner = normalize_team(ownership_overrides.get(asset_id))
        if owner not in known_teams:
            raise FranchiseLiveAssetLedgerError(
                f"Franchise draft ownership override for {asset_id} has "
                f"invalid team {owner or '<blank>'}."
            )
        row["pre_transaction_owner"] = normalize_team(
            row.get("current_owner")
        )
        row["current_owner"] = owner
        row["franchise_transactional_owner"] = True
        row["ownership_source"] = "franchise_transaction_history_v1"

    rows.sort(
        key=lambda row: (
            int(row.get("draft_year") or 9999),
            int(row.get("round") or 9),
            row.get("current_owner", ""),
            row.get("asset_id", ""),
        )
    )
    return rows


def build_live_asset_ledger(runtime: RuntimeData, state: Any, trade_state: Any) -> FranchiseAssetLedger:
    season = clean_text(getattr(getattr(state, "settings", None), "season_label", ""))
    next_year = season_end_year(season)
    players = build_player_asset_rows(runtime, state)
    drafts = build_draft_asset_rows(runtime, state, trade_state)
    if {row["player_id"] for row in players} != {normalize_player_id(x) for x in getattr(state, "players", {})}:
        raise FranchiseLiveAssetLedgerError("Player ledger does not exactly cover live franchise players.")
    return FranchiseAssetLedger(
        version=ASSET_LEDGER_VERSION,
        season_label=season,
        next_draft_year=next_year,
        horizon_end_year=next_year + DRAFT_HORIZON_YEARS - 1,
        player_rows=tuple(players),
        draft_rows=tuple(drafts),
    )


def team_player_rows(ledger: FranchiseAssetLedger, team: str) -> list[dict[str, Any]]:
    resolved = normalize_team(team)
    return [dict(row) for row in ledger.player_rows if row.get("team") == resolved]


def team_draft_rows(ledger: FranchiseAssetLedger, team: str) -> list[dict[str, Any]]:
    resolved = normalize_team(team)
    return [dict(row) for row in ledger.draft_rows if row.get("current_owner") == resolved]


def team_forfeited_draft_rows(
    ledger: FranchiseAssetLedger,
    team: str,
) -> list[dict[str, Any]]:
    resolved = normalize_team(team)
    return [
        dict(row)
        for row in ledger.draft_rows
        if (
            row.get("forfeiture_status") == "forfeited"
            and row.get("penalized_team") == resolved
        )
    ]
