from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import inspect
import json
import math
import tempfile
import zipfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
)
from franchise_free_agency_rights_exceptions_v1 import (
    FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
    evaluate_rights_exception_financial_gate,
)
from franchise_free_agency_cpu_execution_v1 import (
    CPU_FREE_AGENCY_EXECUTION_VERSION,
    build_cpu_free_agency_execution_plan,
)
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    build_trade_state_free_agency_candidate,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_transaction_v1 import free_agency_state_fingerprint
from franchise_free_agency_transaction_v1_1 import build_free_agency_durable_candidate

CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION = (
    "franchise-free-agency-cpu-offseason-soak-audit-v1-2026-08-14"
)
CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION = (
    "free-agency-cpu-offseason-soak-schema-v1"
)
CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE = (
    "read_only_in_memory_sequential_cpu_free_agency_replay_soak_no_checkpoint_write"
)
DEFAULT_SOAK_REPLAY_COUNT = 20
DEFAULT_SOAK_MAX_DAYS = 15
DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY = 3
DEFAULT_SOAK_MAX_TOTAL_SIGNINGS = 60
DEFAULT_SOAK_MAX_TARGETS_PER_TEAM = 5
MAX_ROSTER_SIZE = 18

CPU_FRONT_OFFICE_MODULE = "franchise_cpu_front_office_v1"
CPU_FRONT_OFFICE_BUILDER = "build_league_front_office_plan"

REQUIRED_FILES = (
    "soak_manifest.csv",
    "soak_behavioral_checks.csv",
    "soak_watch_metrics.csv",
    "soak_replays.csv",
    "soak_day_summaries.csv",
    "soak_signings.csv",
    "soak_market_snapshots.csv",
    "soak_team_summaries.csv",
    "soak_direction_summaries.csv",
    "soak_terminal_free_agents.csv",
    "soak_summary.json",
)


class CPUFreeAgencyOffseasonSoakError(RuntimeError):
    """Raised when the read-only sequential CPU free-agency soak cannot run safely."""


@dataclass(frozen=True)
class CPUFreeAgencyOffseasonReplayResult:
    replay_number: int
    start_simulation_fingerprint: str
    start_trade_fingerprint: str
    final_simulation_fingerprint: str
    final_trade_fingerprint: str
    outcome_fingerprint: str
    initial_free_agent_count: int
    final_free_agent_count: int
    days_used: int
    signing_count: int
    terminal_reason: str
    signing_rows: tuple[dict[str, Any], ...]
    day_rows: tuple[dict[str, Any], ...]
    market_rows: tuple[dict[str, Any], ...]
    terminal_free_agent_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CPUFreeAgencyOffseasonSoakBuildResult:
    version: str
    schema_version: str
    season_label: str
    live_phase: str
    analysis_phase: str
    replay_count: int
    output_zip: str
    zip_sha256: str
    checkpoint_sha256: str
    strict_pass: bool
    failed_checks: tuple[str, ...]
    row_counts: dict[str, int]
    baseline_signing_count: int
    baseline_days_used: int
    baseline_terminal_reason: str
    baseline_outcome_fingerprint: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _checkpoint_contract() -> tuple[Callable[..., Any], Path]:
    module = importlib.import_module("simulation_franchise_checkpoint_v1")
    load_fn = getattr(module, "load_franchise_checkpoint", None)
    checkpoint_path = Path(
        getattr(
            module,
            "DEFAULT_CHECKPOINT_PATH",
            "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz",
        )
    )
    if not callable(load_fn):
        raise CPUFreeAgencyOffseasonSoakError(
            "load_franchise_checkpoint() is unavailable."
        )
    required = [
        parameter
        for parameter in inspect.signature(load_fn).parameters.values()
        if parameter.default is inspect._empty
        and parameter.kind
        not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
    ]
    if required:
        raise CPUFreeAgencyOffseasonSoakError(
            "The durable checkpoint loader unexpectedly requires arguments."
        )
    return load_fn, checkpoint_path


def _isolated_offseason_state(state: Any) -> Any:
    candidate = copy.deepcopy(state)
    if _phase(candidate) == "offseason":
        return candidate
    try:
        from franchise_free_agency_ui_v1 import isolated_offseason_preview_state

        return isolated_offseason_preview_state(candidate)
    except Exception:
        pass
    try:
        from simulation_league_state_v1 import LeaguePhase

        candidate.phase = LeaguePhase.OFFSEASON
    except Exception:
        candidate.phase = "offseason"
    return candidate


def _front_office_builder() -> Callable[..., Any]:
    module = importlib.import_module(CPU_FRONT_OFFICE_MODULE)
    builder = getattr(module, CPU_FRONT_OFFICE_BUILDER, None)
    if not callable(builder):
        raise CPUFreeAgencyOffseasonSoakError(
            f"{CPU_FRONT_OFFICE_MODULE}.{CPU_FRONT_OFFICE_BUILDER}() is unavailable."
        )
    return builder


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    if not fields:
        fields = ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized: dict[str, Any] = {}
            for key in fields:
                value = row.get(key)
                if isinstance(value, (Mapping, list, tuple, set)):
                    normalized[key] = json.dumps(
                        _json_safe(value),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                else:
                    normalized[key] = value
            writer.writerow(normalized)


def _team_roster_count(state: Any, team: str) -> int:
    team_state = getattr(state, "teams", {}).get(_team(team))
    if team_state is None:
        return 0
    return len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))


def _player_row(state: Any, player_id: str) -> dict[str, Any]:
    player = getattr(state, "players", {}).get(_clean(player_id))
    return {
        "player_id": _clean(player_id),
        "player_name": _clean(getattr(player, "player_name", "")),
        "overall_rating": _finite(getattr(player, "overall_rating", None)),
        "potential_rating": _finite(getattr(player, "potential_rating", None)),
        "age": _finite(getattr(player, "age", None)),
        "position": _clean(getattr(player, "position", "")),
    }


def _winner_market(plan: Any, player_id: str, market_fingerprint: str) -> Any:
    return next(
        (
            market
            for market in getattr(plan, "markets", ())
            if _clean(getattr(market, "player_id", "")) == _clean(player_id)
            and _clean(getattr(getattr(market, "market", None), "market_fingerprint", ""))
            == _clean(market_fingerprint)
        ),
        None,
    )


def _winner_offer(plan: Any, player_id: str, winner_team: str) -> Any:
    candidates = [
        offer
        for offer in getattr(getattr(plan, "board", None), "offers", ())
        if _clean(getattr(offer, "player_id", "")) == _clean(player_id)
        and _team(getattr(offer, "team_abbreviation", "")) == _team(winner_team)
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            -float(getattr(row, "target_fit_score", 0.0) or 0.0),
            -float(getattr(row, "annual_salary", 0.0) or 0.0),
            _clean(getattr(row, "offer_fingerprint", "")),
        )
    )
    return candidates[0]


def _winner_evaluation(market_result: Any, winner_team: str) -> Any:
    return next(
        (
            row
            for row in getattr(market_result, "evaluations", ())
            if _team(getattr(row, "team_abbreviation", "")) == _team(winner_team)
        ),
        None,
    )


def _align_simulation_source_to_trade_state(simulation_candidate: Any, trade_candidate: Any) -> None:
    if hasattr(simulation_candidate, "source_league_state_revision"):
        simulation_candidate.source_league_state_revision = int(
            getattr(trade_candidate, "state_revision", 0) or 0
        )
    if hasattr(simulation_candidate, "source_transaction_count"):
        simulation_candidate.source_transaction_count = len(
            list(getattr(trade_candidate, "transaction_history", []) or [])
        )
    history = getattr(simulation_candidate, "free_agency_transaction_history", None)
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )


def _apply_signing_in_memory(
    simulation_state: Any,
    trade_state: Any,
    preview: Any,
    *,
    market_fingerprint: str,
) -> tuple[Any, Any, dict[str, Any]]:
    try:
        from simulation_league_state_v1 import validate_simulation_league_state
    except Exception:
        validate_simulation_league_state = None

    player_id = _clean(getattr(getattr(preview, "offer", None), "player_id", ""))
    team = _team(getattr(getattr(preview, "offer", None), "team_abbreviation", ""))
    salary = float(getattr(getattr(preview, "offer", None), "annual_salary", 0.0) or 0.0)
    roster_before = _team_roster_count(simulation_state, team)
    free_before = set(_clean(value) for value in getattr(simulation_state, "free_agent_player_ids", ()) or ())

    simulation_candidate, commit, revision, transaction_id = build_free_agency_durable_candidate(
        simulation_state,
        preview,
        financial_gate=evaluate_rights_exception_financial_gate,
        state_validator=validate_simulation_league_state if callable(validate_simulation_league_state) else None,
        max_roster_size=MAX_ROSTER_SIZE,
    )
    trade_candidate, trade_sync = build_trade_state_free_agency_candidate(
        trade_state,
        preview.offer,
        transaction_id=transaction_id,
        validate=True,
    )
    _align_simulation_source_to_trade_state(simulation_candidate, trade_candidate)
    if callable(validate_simulation_league_state):
        validate_simulation_league_state(simulation_candidate)

    history = getattr(simulation_candidate, "free_agency_transaction_history", None)
    if isinstance(history, list) and history:
        history[-1]["execution_actor"] = "cpu_front_office_soak_audit"
        history[-1]["competing_market_fingerprint"] = _clean(market_fingerprint)
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )

    free_after = set(_clean(value) for value in getattr(simulation_candidate, "free_agent_player_ids", ()) or ())
    roster_after = _team_roster_count(simulation_candidate, team)
    trade_owner = _team(getattr(trade_candidate, "player_team_by_id", {}).get(player_id, ""))

    if player_id not in free_before or player_id in free_after:
        raise CPUFreeAgencyOffseasonSoakError(
            "In-memory CPU signing did not remove the player from the free-agent pool exactly once."
        )
    if roster_after != roster_before + 1:
        raise CPUFreeAgencyOffseasonSoakError(
            "In-memory CPU signing did not add exactly one roster player."
        )
    if roster_after > MAX_ROSTER_SIZE:
        raise CPUFreeAgencyOffseasonSoakError(
            "In-memory CPU signing exceeded the maximum roster size."
        )
    if trade_owner != team:
        raise CPUFreeAgencyOffseasonSoakError(
            "In-memory CPU signing did not synchronize Trade Machine ownership."
        )
    if not math.isclose(
        float(trade_sync.team_salary_after) - float(trade_sync.team_salary_before),
        salary,
        abs_tol=0.01,
    ):
        raise CPUFreeAgencyOffseasonSoakError(
            "In-memory CPU signing did not add the exact offer salary to Trade Machine team salary."
        )

    return simulation_candidate, trade_candidate, {
        "transaction_id": transaction_id,
        "free_agency_revision": revision,
        "roster_before": roster_before,
        "roster_after": roster_after,
        "trade_owner_after": trade_owner,
        "team_salary_before": float(trade_sync.team_salary_before),
        "team_salary_after": float(trade_sync.team_salary_after),
        "apron_salary_before": float(trade_sync.apron_salary_before),
        "apron_salary_after": float(trade_sync.apron_salary_after),
        "trade_revision_before": int(trade_sync.state_revision_before),
        "trade_revision_after": int(trade_sync.state_revision_after),
        "commit_player_id": _clean(getattr(commit, "player_id", "")),
        "commit_team": _team(getattr(commit, "team_abbreviation", "")),
    }


def simulate_cpu_offseason_replay(
    simulation_state: Any,
    trade_state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    replay_number: int = 1,
    max_days: int = DEFAULT_SOAK_MAX_DAYS,
    max_signings_per_day: int = DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY,
    max_total_signings: int = DEFAULT_SOAK_MAX_TOTAL_SIGNINGS,
    max_targets_per_team: int = DEFAULT_SOAK_MAX_TARGETS_PER_TEAM,
    front_office_builder: Callable[..., Any] | None = None,
) -> CPUFreeAgencyOffseasonReplayResult:
    """Run one complete CPU-only offseason replay entirely in memory.

    This intentionally follows production ordering. No random number, seed, shuffle,
    or audit-specific decision override is introduced. After every signing both the
    simulation candidate and Trade Machine candidate become the source for a fresh
    CPU front-office plan and a fresh execution plan.
    """
    if max_days < 1 or max_days > 60:
        raise CPUFreeAgencyOffseasonSoakError("max_days must be between 1 and 60.")
    if max_signings_per_day < 1 or max_signings_per_day > 15:
        raise CPUFreeAgencyOffseasonSoakError(
            "max_signings_per_day must be between 1 and 15."
        )
    if max_total_signings < 1 or max_total_signings > 200:
        raise CPUFreeAgencyOffseasonSoakError(
            "max_total_signings must be between 1 and 200."
        )

    sim = _isolated_offseason_state(simulation_state)
    trade = copy.deepcopy(trade_state)
    controlled = tuple(sorted({_team(value) for value in controlled_teams if _team(value)}))
    builder = front_office_builder or _front_office_builder()

    start_sim_fp = free_agency_state_fingerprint(sim)
    start_trade_fp = trade_state_fingerprint(trade)
    initial_free_agents = tuple(_clean(value) for value in getattr(sim, "free_agent_player_ids", ()) or ())

    signing_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    signed_players: set[str] = set()
    terminal_reason = "max_days_reached"
    total_signings = 0
    days_used = 0
    plan_sequence = 0

    for day in range(1, max_days + 1):
        days_used = day
        day_free_start = len(tuple(getattr(sim, "free_agent_player_ids", ()) or ()))
        day_signings = 0
        day_offer_observations = 0
        day_market_observations = 0
        day_accepted_market_observations = 0
        day_terminal_reason = "day_signing_limit_reached"

        while day_signings < max_signings_per_day and total_signings < max_total_signings:
            plan_sequence += 1
            front_office_plan = builder(sim, controlled_teams=controlled)
            plan = build_cpu_free_agency_execution_plan(
                sim,
                controlled_teams=controlled,
                front_office_plan=front_office_plan,
                max_targets_per_team=max_targets_per_team,
            )
            day_offer_observations += int(getattr(plan, "generated_offer_count", 0) or 0)
            day_market_observations += int(getattr(plan, "market_count", 0) or 0)
            day_accepted_market_observations += int(getattr(plan, "winner_market_count", 0) or 0)

            for rank, opportunity in enumerate(getattr(plan, "opportunities", ()), start=1):
                market_rows.append({
                    "replay_number": replay_number,
                    "soak_day": day,
                    "plan_sequence": plan_sequence,
                    "opportunity_rank": rank,
                    "plan_fingerprint": _clean(getattr(plan, "plan_fingerprint", "")),
                    "board_fingerprint": _clean(getattr(plan, "board_fingerprint", "")),
                    "generated_offer_count": int(getattr(plan, "generated_offer_count", 0) or 0),
                    "market_count": int(getattr(plan, "market_count", 0) or 0),
                    "winner_market_count": int(getattr(plan, "winner_market_count", 0) or 0),
                    "player_id": _clean(getattr(opportunity, "player_id", "")),
                    "player_name": _clean(getattr(opportunity, "player_name", "")),
                    "winner_team_abbreviation": _team(getattr(opportunity, "winner_team_abbreviation", "")),
                    "annual_salary": _finite(getattr(opportunity, "annual_salary", None)),
                    "years": getattr(opportunity, "years", None),
                    "winner_utility_score": _finite(getattr(opportunity, "winner_utility_score", None)),
                    "winning_margin": _finite(getattr(opportunity, "winning_margin", None)),
                    "target_fit_score": _finite(getattr(opportunity, "target_fit_score", None)),
                    "market_offer_count": getattr(opportunity, "market_offer_count", None),
                    "market_fingerprint": _clean(getattr(opportunity, "market_fingerprint", "")),
                    "selected_for_execution": rank == 1,
                })

            if not getattr(plan, "opportunities", ()):
                terminal_reason = "no_accepted_cpu_market"
                day_terminal_reason = terminal_reason
                break

            opportunity = plan.opportunities[0]
            player_id = _clean(opportunity.player_id)
            winner_team = _team(opportunity.winner_team_abbreviation)
            if winner_team in controlled:
                raise CPUFreeAgencyOffseasonSoakError(
                    "A user-controlled team appeared as a CPU soak signing winner."
                )
            if player_id in signed_players:
                raise CPUFreeAgencyOffseasonSoakError(
                    "A player was selected for multiple CPU soak signings in one replay."
                )

            player_market = _winner_market(
                plan,
                player_id,
                opportunity.market_fingerprint,
            )
            if player_market is None or not bool(getattr(player_market.market, "has_winner", False)):
                raise CPUFreeAgencyOffseasonSoakError(
                    "The selected CPU opportunity could not be reconciled to an accepted market."
                )
            generated_offer = _winner_offer(plan, player_id, winner_team)
            if generated_offer is None:
                raise CPUFreeAgencyOffseasonSoakError(
                    "The selected CPU market winner could not be reconciled to a generated legal offer."
                )
            preview = getattr(generated_offer, "preview", None)
            if (
                preview is None
                or _clean(getattr(preview, "status", "")).lower() != "pass"
                or not bool(getattr(preview, "can_commit", False))
            ):
                raise CPUFreeAgencyOffseasonSoakError(
                    "The selected CPU soak winner does not have a backend-PASS preview."
                )

            evaluation = _winner_evaluation(player_market.market, winner_team)
            if evaluation is None or not bool(getattr(evaluation, "accepted", False)):
                raise CPUFreeAgencyOffseasonSoakError(
                    "The selected CPU soak winner is not an accepted player destination."
                )

            player_context = _player_row(sim, player_id)
            evaluation_salaries = [
                float(getattr(row, "annual_salary", 0.0) or 0.0)
                for row in getattr(player_market.market, "evaluations", ())
            ]
            highest_market_salary = max(evaluation_salaries) if evaluation_salaries else float(generated_offer.annual_salary)
            winner_salary = float(generated_offer.annual_salary)
            source_sim_fp = free_agency_state_fingerprint(sim)
            source_trade_fp = trade_state_fingerprint(trade)

            sim_candidate, trade_candidate, mutation = _apply_signing_in_memory(
                sim,
                trade,
                preview,
                market_fingerprint=player_market.market.market_fingerprint,
            )
            candidate_sim_fp = free_agency_state_fingerprint(sim_candidate)
            candidate_trade_fp = trade_state_fingerprint(trade_candidate)
            if source_sim_fp == candidate_sim_fp or source_trade_fp == candidate_trade_fp:
                raise CPUFreeAgencyOffseasonSoakError(
                    "A successful in-memory signing did not change both simulation and Trade Machine fingerprints."
                )

            signing_rows.append({
                "replay_number": replay_number,
                "soak_day": day,
                "signing_number": total_signings + 1,
                "plan_sequence": plan_sequence,
                "player_id": player_id,
                "player_name": player_context["player_name"],
                "overall_rating": player_context["overall_rating"],
                "potential_rating": player_context["potential_rating"],
                "age": player_context["age"],
                "position": player_context["position"],
                "team_abbreviation": winner_team,
                "team_direction": _clean(getattr(generated_offer, "team_direction", "")),
                "salary_posture": _clean(getattr(generated_offer, "salary_posture", "")),
                "target_fit_score": _finite(getattr(generated_offer, "target_fit_score", None)),
                "target_tier": _clean(getattr(generated_offer, "target_tier", "")),
                "annual_salary": winner_salary,
                "years": int(getattr(generated_offer, "years", 0) or 0),
                "strategic_requested_years": int(
                    getattr(generated_offer, "strategic_requested_years", getattr(generated_offer, "years", 0)) or 0
                ),
                "term_fallback_applied": bool(getattr(generated_offer, "term_fallback_applied", False)),
                "financial_route": _clean(getattr(generated_offer, "financial_route", "pure_cap_space_only")),
                "rights_classification": _clean(getattr(generated_offer, "rights_classification", "unknown")),
                "prior_team": _team(getattr(generated_offer, "prior_team", "")),
                "cap_space_before": _finite(getattr(generated_offer, "cap_space_before", None)),
                "aggression_multiplier": _finite(getattr(generated_offer, "aggression_multiplier", None)),
                "utility_score": _finite(getattr(evaluation, "utility_score", None)),
                "acceptance_threshold": _finite(getattr(evaluation, "acceptance_threshold", None)),
                "winning_margin": _finite(getattr(player_market.market, "winning_margin", None)),
                "market_offer_count": int(getattr(player_market, "cpu_offer_count", 0) or 0),
                "highest_market_salary": highest_market_salary,
                "highest_salary_won": math.isclose(winner_salary, highest_market_salary, abs_tol=0.01),
                "lower_salary_winner": winner_salary < highest_market_salary - 0.01,
                "market_fingerprint": _clean(getattr(player_market.market, "market_fingerprint", "")),
                "board_fingerprint": _clean(getattr(plan, "board_fingerprint", "")),
                "plan_fingerprint": _clean(getattr(plan, "plan_fingerprint", "")),
                "offer_fingerprint": _clean(getattr(generated_offer, "offer_fingerprint", "")),
                "source_simulation_fingerprint": source_sim_fp,
                "committed_simulation_fingerprint": candidate_sim_fp,
                "source_trade_fingerprint": source_trade_fp,
                "committed_trade_fingerprint": candidate_trade_fp,
                **mutation,
            })

            signed_players.add(player_id)
            sim = sim_candidate
            trade = trade_candidate
            total_signings += 1
            day_signings += 1
            day_terminal_reason = "day_signing_limit_reached"

        day_rows.append({
            "replay_number": replay_number,
            "soak_day": day,
            "free_agents_start": day_free_start,
            "free_agents_end": len(tuple(getattr(sim, "free_agent_player_ids", ()) or ())),
            "signings": day_signings,
            "offer_observations": day_offer_observations,
            "market_observations": day_market_observations,
            "accepted_market_observations": day_accepted_market_observations,
            "day_stop_reason": day_terminal_reason,
            "simulation_fingerprint_end": free_agency_state_fingerprint(sim),
            "trade_fingerprint_end": trade_state_fingerprint(trade),
        })

        if terminal_reason == "no_accepted_cpu_market":
            break
        if total_signings >= max_total_signings:
            terminal_reason = "max_total_signings_reached"
            break

    final_sim_fp = free_agency_state_fingerprint(sim)
    final_trade_fp = trade_state_fingerprint(trade)
    terminal_free_agents = [
        {"replay_number": replay_number, **_player_row(sim, player_id)}
        for player_id in tuple(getattr(sim, "free_agent_player_ids", ()) or ())
    ]
    terminal_free_agents.sort(
        key=lambda row: (
            -(row.get("overall_rating") if row.get("overall_rating") is not None else -1e9),
            row.get("player_name", ""),
            row.get("player_id", ""),
        )
    )

    outcome_payload = {
        "start_sim": start_sim_fp,
        "start_trade": start_trade_fp,
        "signings": [
            {
                "day": row["soak_day"],
                "player": row["player_id"],
                "team": row["team_abbreviation"],
                "salary": row["annual_salary"],
                "years": row["years"],
                "direction": row["team_direction"],
                "market": row["market_fingerprint"],
            }
            for row in signing_rows
        ],
        "final_sim": final_sim_fp,
        "final_trade": final_trade_fp,
        "terminal_reason": terminal_reason,
    }
    return CPUFreeAgencyOffseasonReplayResult(
        replay_number=replay_number,
        start_simulation_fingerprint=start_sim_fp,
        start_trade_fingerprint=start_trade_fp,
        final_simulation_fingerprint=final_sim_fp,
        final_trade_fingerprint=final_trade_fp,
        outcome_fingerprint=_fingerprint(outcome_payload),
        initial_free_agent_count=len(initial_free_agents),
        final_free_agent_count=len(tuple(getattr(sim, "free_agent_player_ids", ()) or ())),
        days_used=days_used,
        signing_count=len(signing_rows),
        terminal_reason=terminal_reason,
        signing_rows=tuple(signing_rows),
        day_rows=tuple(day_rows),
        market_rows=tuple(market_rows),
        terminal_free_agent_rows=tuple(terminal_free_agents),
    )


def _behavioral_checks(
    replays: Sequence[CPUFreeAgencyOffseasonReplayResult],
    *,
    controlled_teams: Iterable[str],
    source_checkpoint_hash_before: str,
    source_checkpoint_hash_after: str,
    source_sim_fp_before: str,
    source_sim_fp_after: str,
    source_trade_fp_before: str,
    source_trade_fp_after: str,
) -> list[dict[str, Any]]:
    controlled = {_team(value) for value in controlled_teams if _team(value)}
    baseline = replays[0] if replays else None
    all_signings = [row for replay in replays for row in replay.signing_rows]

    checks: list[tuple[str, bool, str]] = []
    checks.append((
        "source_checkpoint_hash_unchanged",
        source_checkpoint_hash_before == source_checkpoint_hash_after,
        "The canonical checkpoint bytes must not change during the soak audit.",
    ))
    checks.append((
        "source_simulation_state_unchanged",
        source_sim_fp_before == source_sim_fp_after,
        "The canonical simulation state must remain unchanged.",
    ))
    checks.append((
        "source_trade_state_unchanged",
        source_trade_fp_before == source_trade_fp_after,
        "The canonical Trade Machine state must remain unchanged.",
    ))
    checks.append((
        "all_replays_start_from_exact_same_state",
        bool(replays)
        and len({row.start_simulation_fingerprint for row in replays}) == 1
        and len({row.start_trade_fingerprint for row in replays}) == 1,
        "Every replay must begin from the same pristine isolated offseason state.",
    ))
    checks.append((
        "same_state_replays_have_exact_same_outcome",
        bool(replays) and len({row.outcome_fingerprint for row in replays}) == 1,
        "Production FA logic is deterministic, so exact-state replays must match.",
    ))
    checks.append((
        "same_state_replays_have_exact_same_final_state",
        bool(replays)
        and len({row.final_simulation_fingerprint for row in replays}) == 1
        and len({row.final_trade_fingerprint for row in replays}) == 1,
        "Exact-state replays must finish with identical simulation and Trade Machine state.",
    ))
    checks.append((
        "cpu_signings_never_target_user_controlled_team",
        all(_team(row["team_abbreviation"]) not in controlled for row in all_signings),
        "The CPU may never sign a player for a user-controlled team.",
    ))
    checks.append((
        "no_player_signs_twice_within_a_replay",
        all(
            len([row["player_id"] for row in replay.signing_rows])
            == len(set(row["player_id"] for row in replay.signing_rows))
            for replay in replays
        ),
        "A free agent can be signed at most once in each replay.",
    ))
    checks.append((
        "every_signing_uses_backend_pass_market_winner",
        all(
            bool(row["market_fingerprint"])
            and bool(row["offer_fingerprint"])
            and float(row["utility_score"] or 0.0) >= float(row["acceptance_threshold"] or 0.0) - 1e-9
            for row in all_signings
        ),
        "Every committed in-memory signing must come from an accepted, backend-PASS winner.",
    ))
    checks.append((
        "every_signing_adds_exactly_one_roster_player",
        all(int(row["roster_after"]) == int(row["roster_before"]) + 1 for row in all_signings),
        "Each signing must add exactly one roster player.",
    ))
    checks.append((
        "every_signing_respects_roster_limit",
        all(int(row["roster_after"]) <= MAX_ROSTER_SIZE for row in all_signings),
        "No signing may exceed the 18-player roster bound.",
    ))
    checks.append((
        "every_signing_updates_trade_ownership",
        all(_team(row["trade_owner_after"]) == _team(row["team_abbreviation"]) for row in all_signings),
        "Trade Machine ownership must match every simulated CPU signing.",
    ))
    checks.append((
        "every_signing_adds_exact_offer_salary",
        all(
            math.isclose(
                float(row["team_salary_after"]) - float(row["team_salary_before"]),
                float(row["annual_salary"]),
                abs_tol=0.01,
            )
            for row in all_signings
        ),
        "Trade Machine team salary must rise by exactly the signed annual salary.",
    ))
    checks.append((
        "term_fallback_only_shortens_strategic_request",
        all(int(row["years"]) <= int(row["strategic_requested_years"]) for row in all_signings),
        "Legal term fallback may only shorten a CPU strategic term request.",
    ))
    checks.append((
        "board_is_rebuilt_after_each_signing",
        all(
            len(replay.day_rows) >= 1
            and (
                replay.signing_count == 0
                or len({row["source_simulation_fingerprint"] for row in replay.signing_rows}) == replay.signing_count
            )
            for replay in replays
        ),
        "Every signing must be sourced from a fresh post-transaction simulation fingerprint.",
    ))
    checks.append((
        "signing_count_never_exceeds_starting_free_agent_pool",
        all(replay.signing_count <= replay.initial_free_agent_count for replay in replays),
        "No replay can sign more players than were present in its starting free-agent pool.",
    ))
    checks.append((
        "terminal_reason_is_recorded_for_every_replay",
        all(bool(_clean(replay.terminal_reason)) for replay in replays),
        "Every replay must stop with an explicit bounded reason.",
    ))
    checks.append((
        "production_determinism_is_preserved_without_fake_seed_variance",
        bool(baseline) and len({row.outcome_fingerprint for row in replays}) == 1,
        "V1 intentionally replays production logic without injecting audit-only randomness.",
    ))

    return [
        {
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "passed": passed,
            "detail": detail,
        }
        for name, passed, detail in checks
    ]


def _watch_metrics(replays: Sequence[CPUFreeAgencyOffseasonReplayResult]) -> list[dict[str, Any]]:
    if not replays:
        return []
    baseline = replays[0]
    signings = list(baseline.signing_rows)
    salaries = [float(row["annual_salary"]) for row in signings]
    years = [int(row["years"]) for row in signings]
    lower_salary = sum(1 for row in signings if bool(row["lower_salary_winner"]))
    highest_salary = sum(1 for row in signings if bool(row["highest_salary_won"]))
    term_fallbacks = sum(1 for row in signings if bool(row["term_fallback_applied"]))
    route_counts: dict[str, int] = {}
    for row in signings:
        route = _clean(row.get("financial_route")) or "unknown"
        route_counts[route] = route_counts.get(route, 0) + 1

    team_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for row in signings:
        team_counts[_team(row["team_abbreviation"])] = team_counts.get(_team(row["team_abbreviation"]), 0) + 1
        direction = _clean(row["team_direction"]) or "Unknown"
        direction_counts[direction] = direction_counts.get(direction, 0) + 1
    max_team_share = (
        100.0 * max(team_counts.values()) / len(signings)
        if signings and team_counts
        else 0.0
    )
    hhi = (
        sum((count / len(signings)) ** 2 for count in team_counts.values()) * 10_000.0
        if signings
        else 0.0
    )

    terminal = list(baseline.terminal_free_agent_rows)
    unsigned_80 = sum(
        1
        for row in terminal
        if row.get("overall_rating") is not None and float(row["overall_rating"]) >= 80.0
    )
    unsigned_75 = sum(
        1
        for row in terminal
        if row.get("overall_rating") is not None and float(row["overall_rating"]) >= 75.0
    )

    raw = [
        ("replay_count", len(replays), "count"),
        ("signings_per_replay", baseline.signing_count, "count"),
        ("days_used", baseline.days_used, "days"),
        ("initial_free_agent_count", baseline.initial_free_agent_count, "count"),
        ("final_free_agent_count", baseline.final_free_agent_count, "count"),
        ("average_signing_salary", sum(salaries) / len(salaries) if salaries else 0.0, "dollars"),
        ("average_contract_years", sum(years) / len(years) if years else 0.0, "years"),
        ("highest_salary_wins_share_pct", 100.0 * highest_salary / len(signings) if signings else 0.0, "percent"),
        ("lower_salary_winner_count", lower_salary, "count"),
        ("term_fallback_count", term_fallbacks, "count"),
        ("financial_route_distribution", json.dumps(route_counts, sort_keys=True), "json"),
        ("minimum_exception_signing_count", route_counts.get("minimum_salary_exception", 0), "count"),
        ("prior_team_rights_signing_count", sum(route_counts.get(key, 0) for key in ("bird_exception", "early_bird_exception", "non_bird_exception")), "count"),
        ("max_single_team_signing_share_pct", max_team_share, "percent"),
        ("team_signing_hhi", hhi, "hhi_0_10000"),
        ("unsigned_80_plus_after_terminal", unsigned_80, "count"),
        ("unsigned_75_plus_after_terminal", unsigned_75, "count"),
        ("terminal_reason", baseline.terminal_reason, "text"),
        ("distinct_signing_teams", len(team_counts), "count"),
        ("distinct_signing_directions", len(direction_counts), "count"),
    ]
    return [
        {"metric": metric, "value": value, "unit": unit, "scope": "baseline_replay"}
        for metric, value, unit in raw
    ]


def _team_summaries(signings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in signings:
        groups.setdefault(_team(row["team_abbreviation"]), []).append(row)
    rows: list[dict[str, Any]] = []
    for team, values in sorted(groups.items()):
        salaries = [float(row["annual_salary"]) for row in values]
        rows.append({
            "team_abbreviation": team,
            "signing_count": len(values),
            "total_annual_salary_added": sum(salaries),
            "average_annual_salary": sum(salaries) / len(salaries),
            "directions_seen": sorted({_clean(row["team_direction"]) for row in values}),
            "term_fallback_count": sum(1 for row in values if row["term_fallback_applied"]),
            "lower_salary_winner_count": sum(1 for row in values if row["lower_salary_winner"]),
            "player_ids": [row["player_id"] for row in values],
            "player_names": [row["player_name"] for row in values],
        })
    return rows


def _direction_summaries(signings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in signings:
        groups.setdefault(_clean(row["team_direction"]) or "Unknown", []).append(row)
    rows: list[dict[str, Any]] = []
    for direction, values in sorted(groups.items()):
        salaries = [float(row["annual_salary"]) for row in values]
        rows.append({
            "team_direction": direction,
            "signing_count": len(values),
            "total_annual_salary_added": sum(salaries),
            "average_annual_salary": sum(salaries) / len(salaries),
            "average_target_fit": sum(float(row["target_fit_score"] or 0.0) for row in values) / len(values),
            "average_utility": sum(float(row["utility_score"] or 0.0) for row in values) / len(values),
            "term_fallback_count": sum(1 for row in values if row["term_fallback_applied"]),
            "lower_salary_winner_count": sum(1 for row in values if row["lower_salary_winner"]),
        })
    return rows


def _emit_soak_progress(progress_callback: Callable[[dict[str, Any]], None] | None, **event: Any) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(dict(event))
    except Exception:
        # Progress reporting is diagnostic only and must never change audit behavior.
        return


def build_cpu_offseason_soak_audit(
    *,
    output_directory: str | Path = "outputs/audits",
    replay_count: int = DEFAULT_SOAK_REPLAY_COUNT,
    max_days: int = DEFAULT_SOAK_MAX_DAYS,
    max_signings_per_day: int = DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY,
    max_total_signings: int = DEFAULT_SOAK_MAX_TOTAL_SIGNINGS,
    max_targets_per_team: int = DEFAULT_SOAK_MAX_TARGETS_PER_TEAM,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> CPUFreeAgencyOffseasonSoakBuildResult:
    if replay_count < 2 or replay_count > 100:
        raise CPUFreeAgencyOffseasonSoakError(
            "replay_count must be between 2 and 100 for a determinism soak."
        )

    _emit_soak_progress(progress_callback, stage="loading_checkpoint", replay_count=replay_count)
    load_fn, checkpoint_path = _checkpoint_contract()
    if not checkpoint_path.exists():
        raise CPUFreeAgencyOffseasonSoakError(
            "The durable franchise checkpoint does not exist."
        )
    checkpoint_hash_before = _sha256(checkpoint_path)
    checkpoint = load_fn()
    if checkpoint is None:
        raise CPUFreeAgencyOffseasonSoakError(
            "The durable franchise checkpoint could not be loaded."
        )
    source_simulation = getattr(checkpoint, "simulation_state", None)
    source_trade = getattr(checkpoint, "trade_state", None)
    if source_simulation is None or source_trade is None:
        raise CPUFreeAgencyOffseasonSoakError(
            "The soak requires both simulation and Trade Machine state."
        )
    source_sim_fp_before = free_agency_state_fingerprint(source_simulation)
    source_trade_fp_before = trade_state_fingerprint(source_trade)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    analysis_template = _isolated_offseason_state(source_simulation)
    analysis_phase = _phase(analysis_template)
    if analysis_phase != "offseason":
        raise CPUFreeAgencyOffseasonSoakError(
            "The isolated soak analysis state could not be placed in offseason phase."
        )

    replays: list[CPUFreeAgencyOffseasonReplayResult] = []
    for index in range(1, replay_count + 1):
        _emit_soak_progress(
            progress_callback,
            stage="replay_start",
            replay_number=index,
            replay_count=replay_count,
        )
        replay = simulate_cpu_offseason_replay(
            analysis_template,
            source_trade,
            controlled_teams=controlled,
            replay_number=index,
            max_days=max_days,
            max_signings_per_day=max_signings_per_day,
            max_total_signings=max_total_signings,
            max_targets_per_team=max_targets_per_team,
        )
        replays.append(replay)
        _emit_soak_progress(
            progress_callback,
            stage="replay_complete",
            replay_number=index,
            replay_count=replay_count,
            signing_count=replay.signing_count,
            days_used=replay.days_used,
            terminal_reason=replay.terminal_reason,
        )

    reloaded = load_fn()
    if reloaded is None:
        raise CPUFreeAgencyOffseasonSoakError(
            "The checkpoint could not be reloaded after the read-only soak."
        )
    checkpoint_hash_after = _sha256(checkpoint_path)
    source_sim_fp_after = free_agency_state_fingerprint(reloaded.simulation_state)
    source_trade_fp_after = trade_state_fingerprint(reloaded.trade_state)

    checks = _behavioral_checks(
        replays,
        controlled_teams=controlled,
        source_checkpoint_hash_before=checkpoint_hash_before,
        source_checkpoint_hash_after=checkpoint_hash_after,
        source_sim_fp_before=source_sim_fp_before,
        source_sim_fp_after=source_sim_fp_after,
        source_trade_fp_before=source_trade_fp_before,
        source_trade_fp_after=source_trade_fp_after,
    )
    failed = [row["check"] for row in checks if row["status"] != "PASS"]
    watch = _watch_metrics(replays)

    replay_rows = [
        {
            "replay_number": replay.replay_number,
            "initial_free_agent_count": replay.initial_free_agent_count,
            "final_free_agent_count": replay.final_free_agent_count,
            "days_used": replay.days_used,
            "signing_count": replay.signing_count,
            "terminal_reason": replay.terminal_reason,
            "start_simulation_fingerprint": replay.start_simulation_fingerprint,
            "start_trade_fingerprint": replay.start_trade_fingerprint,
            "final_simulation_fingerprint": replay.final_simulation_fingerprint,
            "final_trade_fingerprint": replay.final_trade_fingerprint,
            "outcome_fingerprint": replay.outcome_fingerprint,
        }
        for replay in replays
    ]
    all_day_rows = [row for replay in replays for row in replay.day_rows]
    all_signing_rows = [row for replay in replays for row in replay.signing_rows]
    all_market_rows = [row for replay in replays for row in replay.market_rows]
    baseline_signings = list(replays[0].signing_rows)
    team_rows = _team_summaries(baseline_signings)
    direction_rows = _direction_summaries(baseline_signings)
    terminal_rows = list(replays[0].terminal_free_agent_rows)

    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    season = _season(source_simulation) or "unknown-season"
    zip_path = output_root / f"franchise_free_agency_cpu_offseason_soak_{season}_{stamp}.zip"

    model_versions = {
        "soak": CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
        "schema": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION,
        "cpu_execution": CPU_FREE_AGENCY_EXECUTION_VERSION,
        "cpu_offer_generation": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "direction_adapter": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
        "term_feasibility": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
        "rights_exceptions": FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        "salary_legality": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "live_signing": FREE_AGENCY_LIVE_SIGNING_VERSION,
    }

    _emit_soak_progress(progress_callback, stage="packaging", replay_count=replay_count, baseline_signings=replays[0].signing_count)
    with tempfile.TemporaryDirectory(prefix="cpu_fa_soak_") as temp_dir:
        root = Path(temp_dir)
        rows_by_file: dict[str, list[dict[str, Any]]] = {
            "soak_behavioral_checks.csv": checks,
            "soak_watch_metrics.csv": watch,
            "soak_replays.csv": replay_rows,
            "soak_day_summaries.csv": all_day_rows,
            "soak_signings.csv": all_signing_rows,
            "soak_market_snapshots.csv": all_market_rows,
            "soak_team_summaries.csv": team_rows,
            "soak_direction_summaries.csv": direction_rows,
            "soak_terminal_free_agents.csv": terminal_rows,
        }
        for filename, rows in rows_by_file.items():
            _write_csv(root / filename, rows)

        manifest_rows = [
            {"key": "audit_version", "value": CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION},
            {"key": "schema_version", "value": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION},
            {"key": "scope", "value": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE},
            {"key": "season_label", "value": season},
            {"key": "live_phase", "value": _phase(source_simulation)},
            {"key": "analysis_phase", "value": analysis_phase},
            {"key": "replay_count", "value": replay_count},
            {"key": "max_days", "value": max_days},
            {"key": "max_signings_per_day", "value": max_signings_per_day},
            {"key": "max_total_signings", "value": max_total_signings},
            {"key": "max_targets_per_team", "value": max_targets_per_team},
            {"key": "checkpoint_sha256", "value": checkpoint_hash_before},
            {"key": "source_simulation_fingerprint", "value": source_sim_fp_before},
            {"key": "source_trade_fingerprint", "value": source_trade_fp_before},
            {"key": "controlled_teams", "value": ",".join(controlled)},
            {"key": "production_randomness_injected", "value": False},
            {"key": "same_state_replays_expected_identical", "value": True},
        ]
        manifest_rows.extend(
            {"key": f"model_version.{key}", "value": value}
            for key, value in model_versions.items()
        )
        _write_csv(root / "soak_manifest.csv", manifest_rows)

        summary = {
            "version": CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
            "schema_version": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION,
            "scope": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE,
            "season_label": season,
            "live_phase": _phase(source_simulation),
            "analysis_phase": analysis_phase,
            "replay_count": replay_count,
            "controlled_teams": list(controlled),
            "checkpoint_sha256_before": checkpoint_hash_before,
            "checkpoint_sha256_after": checkpoint_hash_after,
            "source_simulation_fingerprint_before": source_sim_fp_before,
            "source_simulation_fingerprint_after": source_sim_fp_after,
            "source_trade_fingerprint_before": source_trade_fp_before,
            "source_trade_fingerprint_after": source_trade_fp_after,
            "strict_pass": not failed,
            "failed_checks": failed,
            "model_versions": model_versions,
            "baseline": {
                "signing_count": replays[0].signing_count,
                "days_used": replays[0].days_used,
                "initial_free_agent_count": replays[0].initial_free_agent_count,
                "final_free_agent_count": replays[0].final_free_agent_count,
                "terminal_reason": replays[0].terminal_reason,
                "outcome_fingerprint": replays[0].outcome_fingerprint,
            },
            "replay_outcome_fingerprints": [row.outcome_fingerprint for row in replays],
            "production_randomness_injected": False,
            "note": (
                "These are exact-state deterministic production-logic replays, not independent random seeds. "
                "V1 measures dynamic cap/roster consumption, board rebuild behavior, and repeatability without inventing audit-only randomness."
            ),
        }
        (root / "soak_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.iterdir()):
                archive.write(path, arcname=path.name)

    row_counts = {
        "soak_manifest.csv": len(manifest_rows),
        "soak_behavioral_checks.csv": len(checks),
        "soak_watch_metrics.csv": len(watch),
        "soak_replays.csv": len(replay_rows),
        "soak_day_summaries.csv": len(all_day_rows),
        "soak_signings.csv": len(all_signing_rows),
        "soak_market_snapshots.csv": len(all_market_rows),
        "soak_team_summaries.csv": len(team_rows),
        "soak_direction_summaries.csv": len(direction_rows),
        "soak_terminal_free_agents.csv": len(terminal_rows),
        "soak_summary.json": 1,
    }
    _emit_soak_progress(progress_callback, stage="complete", replay_count=replay_count, strict_pass=not bool(failed), output_zip=str(zip_path))
    return CPUFreeAgencyOffseasonSoakBuildResult(
        version=CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
        schema_version=CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION,
        season_label=season,
        live_phase=_phase(source_simulation),
        analysis_phase=analysis_phase,
        replay_count=replay_count,
        output_zip=str(zip_path),
        zip_sha256=_sha256(zip_path),
        checkpoint_sha256=checkpoint_hash_before,
        strict_pass=not failed,
        failed_checks=tuple(failed),
        row_counts=row_counts,
        baseline_signing_count=replays[0].signing_count,
        baseline_days_used=replays[0].days_used,
        baseline_terminal_reason=replays[0].terminal_reason,
        baseline_outcome_fingerprint=replays[0].outcome_fingerprint,
    )


def soak_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_OFFSEASON_SOAK_VERSION,
        "schema_version": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCHEMA_VERSION,
        "scope": CPU_FREE_AGENCY_OFFSEASON_SOAK_SCOPE,
        "default_replay_count": DEFAULT_SOAK_REPLAY_COUNT,
        "default_max_days": DEFAULT_SOAK_MAX_DAYS,
        "default_max_signings_per_day": DEFAULT_SOAK_MAX_SIGNINGS_PER_DAY,
        "default_max_total_signings": DEFAULT_SOAK_MAX_TOTAL_SIGNINGS,
        "cpu_execution_version": CPU_FREE_AGENCY_EXECUTION_VERSION,
        "offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "direction_adapter_version": CPU_FREE_AGENCY_DIRECTION_ADAPTER_VERSION,
        "term_feasibility_version": CPU_FREE_AGENCY_TERM_FEASIBILITY_VERSION,
        "read_only": True,
        "checkpoint_write_allowed": False,
        "production_randomness_injected": False,
        "same_state_replays_expected_identical": True,
        "board_rebuilt_after_each_signing": True,
        "simulation_and_trade_candidates_both_advanced_in_memory": True,
    }
