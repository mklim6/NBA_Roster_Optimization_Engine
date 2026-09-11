from __future__ import annotations

import copy
import gc
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from franchise_offseason_market_season_v1 import resolve_offseason_market_season
from franchise_free_agency_competing_market_v1 import (
    FREE_AGENCY_COMPETING_MARKET_VERSION,
    FreeAgencyCompetingMarketResult,
    evaluate_competing_offer_market,
    winner_preview_and_decision,
)
from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
    minimum_salary_floor_for_state,
    resolve_years_of_service,
)
from franchise_free_agency_rights_exceptions_v1 import (
    FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
    build_rights_exception_free_agency_preview,
    evaluate_rights_exception_financial_gate,
)
from franchise_free_agency_cpu_offer_generation_v1 import (
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    CPUFreeAgencyOfferBoard,
    CPUFreeAgencyPlayerMarket,
    build_cpu_competing_markets,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    FREE_AGENCY_TRADE_STATE_SYNC_VERSION,
    build_trade_state_free_agency_candidate,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_player_decision_v1 import (
    FREE_AGENCY_PLAYER_DECISION_VERSION,
    evaluate_free_agent_offer_decision,
)
from franchise_free_agency_transaction_v1 import (
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_DURABLE_COMMIT_VERSION,
    build_free_agency_durable_candidate,
    free_agency_durable_state_fingerprint,
)

CPU_FREE_AGENCY_EXECUTION_VERSION = (
    "franchise-free-agency-cpu-execution-v1-2026-08-14"
)
CPU_FREE_AGENCY_EXECUTION_SCOPE = (
    "actual_offseason_cpu_only_market_execution_rebuild_after_each_signing"
)
CPU_FREE_AGENCY_CONFIRMATION_TOKEN = "CPU_FREE_AGENCY_EXECUTION_V1"
DEFAULT_CPU_FREE_AGENCY_MAX_SIGNINGS_PER_ROUND = 3
CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION = (
    "franchise-free-agency-cpu-roster-floor-rescue-v1.1-pruned-revalidation-2026-09-11"
)
CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_SCOPE = (
    "post-market-cpu-only-game-ready-floor-rescue-with-legal-player-accepted-offers"
)
CPU_FREE_AGENCY_ROSTER_FLOOR_MAX_COUNTER_MULTIPLIER = 1.50
CPU_FREE_AGENCY_DEEP_SEASON_PERFORMANCE_VERSION = (
    "franchise-free-agency-deep-season-performance-v2-2026-09-11"
)


class CPUFreeAgencyExecutionError(RuntimeError):
    """Raised when CPU free-agency execution cannot proceed safely."""


@dataclass(frozen=True)
class CPUFreeAgencyExecutionOpportunity:
    player_id: str
    player_name: str
    winner_team_abbreviation: str
    annual_salary: float
    years: int
    winner_utility_score: float
    winning_margin: float | None
    target_fit_score: float
    market_offer_count: int
    market_fingerprint: str


@dataclass(frozen=True)
class CPUFreeAgencyExecutionPlan:
    version: str
    scope: str
    season_label: str
    phase: str
    controlled_teams: tuple[str, ...]
    board_fingerprint: str
    generated_offer_count: int
    market_count: int
    winner_market_count: int
    opportunities: tuple[CPUFreeAgencyExecutionOpportunity, ...]
    plan_fingerprint: str
    board: CPUFreeAgencyOfferBoard
    markets: tuple[CPUFreeAgencyPlayerMarket, ...]

    @property
    def has_action(self) -> bool:
        return bool(self.opportunities)


@dataclass(frozen=True)
class CPUFreeAgencyLiveSigningResult:
    version: str
    scope: str
    market_fingerprint: str
    transaction_id: str
    offer_id: str
    player_id: str
    player_name: str
    team_abbreviation: str
    annual_salary: float
    years: int
    free_agency_revision: int
    source_simulation_fingerprint: str
    committed_simulation_fingerprint: str
    source_trade_fingerprint: str
    committed_trade_fingerprint: str
    trade_state_revision_before: int
    trade_state_revision_after: int
    checkpoint_hash_before: str
    checkpoint_hash_after: str
    checkpoint_saved_at_utc: str
    checkpoint_reason: str
    recovery_path: str


@dataclass(frozen=True)
class CPUFreeAgencyExecutionStepResult:
    version: str
    status: str
    plan_fingerprint: str
    board_fingerprint: str
    market_fingerprint: str | None
    signing: CPUFreeAgencyLiveSigningResult | None
    message: str

    @property
    def committed(self) -> bool:
        return self.signing is not None


@dataclass(frozen=True)
class CPUFreeAgencyRoundResult:
    version: str
    status: str
    requested_max_signings: int
    committed_signing_count: int
    signings: tuple[CPUFreeAgencyLiveSigningResult, ...]
    stop_reason: str
    checkpoint_hash_before: str
    checkpoint_hash_after: str


@dataclass(frozen=True)
class CPUFreeAgencyRosterFloorRescueOpportunity:
    version: str
    scope: str
    team_abbreviation: str
    roster_count_before: int
    minimum_game_players: int
    roster_deficit: int
    player_id: str
    player_name: str
    annual_salary: float
    years: int
    offer_path: str
    player_utility_score: float
    acceptance_threshold: float
    player_overall: float
    preview: Any
    decision_fingerprint: str
    rescue_fingerprint: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _phase(state: Any) -> str:
    value = getattr(state, "phase", "")
    return _clean(getattr(value, "value", value)).lower()


def _season(state: Any) -> str:
    return resolve_offseason_market_season(state)


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _preference_dict(checkpoint: Any) -> dict[str, Any]:
    raw = getattr(checkpoint, "preferences", None)
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _align_simulation_source_to_trade_state(
    simulation_candidate: Any,
    trade_candidate: Any,
) -> None:
    if hasattr(simulation_candidate, "source_league_state_revision"):
        simulation_candidate.source_league_state_revision = int(
            getattr(trade_candidate, "state_revision", 0) or 0
        )
    if hasattr(simulation_candidate, "source_transaction_count"):
        simulation_candidate.source_transaction_count = len(
            list(getattr(trade_candidate, "transaction_history", []) or [])
        )
    history = getattr(
        simulation_candidate,
        "free_agency_transaction_history",
        None,
    )
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )


def _winner_generated_offer(
    board: CPUFreeAgencyOfferBoard,
    market: CPUFreeAgencyPlayerMarket,
) -> Any | None:
    winner_team = _team(market.market.winner_team_abbreviation)
    candidates = [
        offer
        for offer in board.offers
        if offer.player_id == market.player_id
        and _team(offer.team_abbreviation) == winner_team
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            -float(row.target_fit_score),
            -float(row.annual_salary),
            row.offer_fingerprint,
        ),
    )[0]


def build_cpu_free_agency_execution_plan(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    front_office_plan: Any | None = None,
    max_targets_per_team: int = 5,
) -> CPUFreeAgencyExecutionPlan:
    """Build the next CPU execution plan without mutating franchise state.

    Offer Generation V1 and Competing Market V1 remain the authorities for CPU
    bid construction and player destination choice. This plan only orders markets
    that already have an accepted CPU winner.
    """
    controlled = tuple(
        sorted({_team(value) for value in controlled_teams if _team(value)})
    )
    board = build_cpu_free_agency_offer_board(
        state,
        controlled_teams=controlled,
        front_office_plan=front_office_plan,
        max_targets_per_team=max_targets_per_team,
    )
    markets = build_cpu_competing_markets(state, board)

    opportunities: list[CPUFreeAgencyExecutionOpportunity] = []
    for player_market in markets:
        result = player_market.market
        if not result.has_winner:
            continue
        winner = _winner_generated_offer(board, player_market)
        if winner is None:
            raise CPUFreeAgencyExecutionError(
                "A CPU market winner could not be reconciled to its generated offer."
            )
        winner_team = _team(result.winner_team_abbreviation)
        if winner_team in controlled:
            raise CPUFreeAgencyExecutionError(
                "A user-controlled team appeared as a CPU execution winner."
            )
        opportunities.append(
            CPUFreeAgencyExecutionOpportunity(
                player_id=player_market.player_id,
                player_name=player_market.player_name,
                winner_team_abbreviation=winner_team,
                annual_salary=float(winner.annual_salary),
                years=int(winner.years),
                winner_utility_score=float(result.winner_utility_score or 0.0),
                winning_margin=(
                    float(result.winning_margin)
                    if result.winning_margin is not None
                    else None
                ),
                target_fit_score=float(winner.target_fit_score),
                market_offer_count=int(player_market.cpu_offer_count),
                market_fingerprint=result.market_fingerprint,
            )
        )

    # Resolve the most competitive accepted market first. This ordering is fully
    # deterministic. After each real signing the entire board is rebuilt, so the
    # ordering never carries stale cap/roster assumptions into a second signing.
    opportunities.sort(
        key=lambda row: (
            -row.winner_utility_score,
            -row.target_fit_score,
            -row.annual_salary,
            row.player_id,
            row.winner_team_abbreviation,
        )
    )
    payload = {
        "version": CPU_FREE_AGENCY_EXECUTION_VERSION,
        "season": _season(state),
        "phase": _phase(state),
        "controlled": controlled,
        "board_fingerprint": board.board_fingerprint,
        "opportunities": [
            {
                "player": row.player_id,
                "team": row.winner_team_abbreviation,
                "salary": row.annual_salary,
                "years": row.years,
                "utility": row.winner_utility_score,
                "fit": row.target_fit_score,
                "market": row.market_fingerprint,
            }
            for row in opportunities
        ],
    }
    return CPUFreeAgencyExecutionPlan(
        version=CPU_FREE_AGENCY_EXECUTION_VERSION,
        scope=CPU_FREE_AGENCY_EXECUTION_SCOPE,
        season_label=_season(state),
        phase=_phase(state),
        controlled_teams=controlled,
        board_fingerprint=board.board_fingerprint,
        generated_offer_count=board.generated_offer_count,
        market_count=len(markets),
        winner_market_count=len(opportunities),
        opportunities=tuple(opportunities),
        plan_fingerprint=_fingerprint(payload),
        board=board,
        markets=tuple(markets),
    )


def build_cpu_free_agency_execution_plan_from_checkpoint(
    *,
    max_targets_per_team: int = 5,
) -> CPUFreeAgencyExecutionPlan:
    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise CPUFreeAgencyExecutionError(
            "The durable franchise checkpoint is unavailable."
        )
    state = getattr(checkpoint, "simulation_state", None)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    return build_cpu_free_agency_execution_plan(
        state,
        controlled_teams=controlled,
        max_targets_per_team=max_targets_per_team,
    )


def assert_cpu_live_commit_preconditions(
    checkpoint: Any,
    preview: FreeAgencyTransactionPreview,
) -> None:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None or trade_state is None:
        raise CPUFreeAgencyExecutionError(
            "CPU free-agency execution requires both durable simulation and Trade Machine state."
        )
    if _phase(state) != "offseason":
        raise CPUFreeAgencyExecutionError(
            "CPU free-agent execution is available only during the actual offseason."
        )
    if not bool(getattr(preview, "can_commit", False)) or _clean(
        getattr(preview, "status", "")
    ).lower() != "pass":
        raise CPUFreeAgencyExecutionError(
            "Only a fully PASS CPU free-agency preview can be committed."
        )
    offer = getattr(preview, "offer", None)
    if offer is None:
        raise CPUFreeAgencyExecutionError(
            "CPU execution preview does not contain an offer."
        )
    team = _team(getattr(offer, "team_abbreviation", ""))
    player_id = _clean(getattr(offer, "player_id", ""))
    teams = {_team(value) for value in getattr(state, "teams", {})}
    if not team or team not in teams:
        raise CPUFreeAgencyExecutionError(
            "CPU signing team is not present in the durable league state."
        )
    controlled = set(controlled_teams_from_durable_checkpoint(checkpoint))
    if team in controlled:
        raise CPUFreeAgencyExecutionError(
            "CPU execution cannot sign a player for a user-controlled team."
        )
    if player_id not in {
        _clean(value)
        for value in getattr(state, "free_agent_player_ids", ()) or ()
    }:
        raise CPUFreeAgencyExecutionError(
            "The CPU target is no longer in the durable free-agent pool."
        )
    if free_agency_state_fingerprint(state) != _clean(
        getattr(preview, "source_fingerprint", "")
    ):
        raise CPUFreeAgencyExecutionError(
            "CPU free-agency preview is stale relative to the durable checkpoint."
        )
    ownership = getattr(trade_state, "player_team_by_id", None)
    if not isinstance(ownership, Mapping):
        raise CPUFreeAgencyExecutionError(
            "Trade Machine ownership is unavailable for CPU free-agency execution."
        )
    if player_id not in ownership or _team(ownership.get(player_id, "")):
        raise CPUFreeAgencyExecutionError(
            "Trade Machine state no longer considers the CPU target a free agent."
        )


def commit_cpu_contract_legal_free_agency_preview_live(
    preview: FreeAgencyTransactionPreview,
    *,
    market_fingerprint: str,
    max_roster_size: int = 18,
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
) -> CPUFreeAgencyLiveSigningResult:
    """Commit one accepted CPU signing through the same dual-state FATX stack.

    The only authorization difference from user Live Signing V1 is intentional:
    the destination MUST be a CPU team and MUST NOT be user-controlled. All other
    legality, stale-state, candidate, Trade Machine sync, checkpoint reload, and
    automatic-recovery guarantees are preserved.
    """
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
    )
    from simulation_league_state_v1 import validate_simulation_league_state

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if not checkpoint_path.exists():
        raise CPUFreeAgencyExecutionError(
            "Durable franchise checkpoint does not exist."
        )
    if _checkpoint is not None:
        if not _checkpoint_hash or _sha256(checkpoint_path) != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "CPU signing checkpoint changed after market evaluation."
            )
        checkpoint = _checkpoint
    else:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "Durable franchise checkpoint could not be loaded."
            )
    assert_cpu_live_commit_preconditions(checkpoint, preview)

    source_sim = checkpoint.simulation_state
    source_trade = checkpoint.trade_state
    validate_simulation_league_state(source_sim)
    source_sim_fp = free_agency_state_fingerprint(source_sim)
    source_trade_fp = trade_state_fingerprint(source_trade)

    simulation_candidate, commit, revision, transaction_id = (
        build_free_agency_durable_candidate(
            source_sim,
            preview,
            financial_gate=evaluate_rights_exception_financial_gate,
            state_validator=validate_simulation_league_state,
            max_roster_size=max_roster_size,
            # The candidate is serialized immediately and no untouched shared
            # branch is mutated. Reuse the proven preview copy-on-write shape to
            # avoid cloning years of completed-game history a second time.
            _candidate_copy_on_write=True,
        )
    )
    trade_candidate, trade_sync = build_trade_state_free_agency_candidate(
        source_trade,
        preview.offer,
        transaction_id=transaction_id,
        validate=True,
    )
    _align_simulation_source_to_trade_state(
        simulation_candidate,
        trade_candidate,
    )
    validate_simulation_league_state(simulation_candidate)

    history = getattr(
        simulation_candidate,
        "free_agency_transaction_history",
        None,
    )
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = free_agency_state_fingerprint(
            simulation_candidate
        )
        history[-1]["execution_actor"] = "cpu_front_office"
        history[-1]["competing_market_fingerprint"] = _clean(
            market_fingerprint
        )

    expected_sim_fp = free_agency_durable_state_fingerprint(
        simulation_candidate
    )
    expected_trade_fp = trade_state_fingerprint(trade_candidate)
    checkpoint_hash_before = _sha256(checkpoint_path)

    recovery_root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent / "cpu_free_agency_recovery"
    )
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovery_path = recovery_root / (
        f"pre_cpu_{transaction_id}_{stamp}_{checkpoint_path.name}"
    )
    shutil.copy2(checkpoint_path, recovery_path)
    reason = f"free-agency-cpu-signing-{transaction_id}"

    try:
        saved = save_franchise_checkpoint(
            simulation_candidate,
            trade_candidate,
            preferences=_preference_dict(checkpoint),
            reason=reason,
            # Both candidates are local transaction objects and the verified
            # decoded checkpoint is returned below, so a second full payload
            # deepcopy adds no isolation while dominating deep-season latency.
            copy_payload=False,
            _return_verified=True,
            _existing_checkpoint=checkpoint,
            _expected_existing_sha256=checkpoint_hash_before,
            _verify_encoded_bytes_only=_verify_bytes_only,
        )
        # The writer has already decoded and rebound the just-written primary
        # while verifying its timestamp/reason. Reuse that verified object
        # instead of decoding the same bytes a second time.
        reloaded = saved
        if _verified_checkpoint_sink is not None:
            _verified_checkpoint_sink.append(reloaded)
        observed_sim_fp = free_agency_durable_state_fingerprint(
            reloaded.simulation_state
        )
        observed_trade_fp = trade_state_fingerprint(reloaded.trade_state)
        if observed_sim_fp != expected_sim_fp:
            raise CPUFreeAgencyExecutionError(
                "Reloaded simulation state does not exactly match the approved CPU signing."
            )
        if observed_trade_fp != expected_trade_fp:
            raise CPUFreeAgencyExecutionError(
                "Reloaded Trade Machine state does not exactly match the synchronized CPU signing."
            )
        observed_history = getattr(
            reloaded.simulation_state,
            "free_agency_transaction_history",
            [],
        )
        if (
            not observed_history
            or observed_history[-1].get("transaction_id") != transaction_id
            or observed_history[-1].get("execution_actor") != "cpu_front_office"
        ):
            raise CPUFreeAgencyExecutionError(
                "CPU FATX metadata did not survive checkpoint reload."
            )
        owner = _team(
            reloaded.trade_state.player_team_by_id.get(
                preview.offer.player_id,
                "",
            )
        )
        if owner != _team(preview.offer.team_abbreviation):
            raise CPUFreeAgencyExecutionError(
                "Trade Machine CPU player ownership did not survive checkpoint reload."
            )
    except Exception as exc:
        shutil.copy2(recovery_path, checkpoint_path)
        restored = load_franchise_checkpoint()
        if restored is None:
            raise CPUFreeAgencyExecutionError(
                "CPU signing failed and checkpoint recovery could not be loaded."
            ) from exc
        restored_sim_fp = free_agency_state_fingerprint(
            restored.simulation_state
        )
        restored_trade_fp = trade_state_fingerprint(restored.trade_state)
        if (
            restored_sim_fp != source_sim_fp
            or restored_trade_fp != source_trade_fp
        ):
            raise CPUFreeAgencyExecutionError(
                "CPU signing failed and automatic recovery could not be verified."
            ) from exc
        raise CPUFreeAgencyExecutionError(
            "CPU signing failed. The pre-signing checkpoint was restored: "
            f"{exc}"
        ) from exc

    return CPUFreeAgencyLiveSigningResult(
        version=CPU_FREE_AGENCY_EXECUTION_VERSION,
        scope=CPU_FREE_AGENCY_EXECUTION_SCOPE,
        market_fingerprint=_clean(market_fingerprint),
        transaction_id=transaction_id,
        offer_id=commit.offer_id,
        player_id=commit.player_id,
        player_name=commit.player_name,
        team_abbreviation=commit.team_abbreviation,
        annual_salary=float(preview.offer.annual_salary),
        years=int(preview.offer.years),
        free_agency_revision=revision,
        source_simulation_fingerprint=source_sim_fp,
        committed_simulation_fingerprint=expected_sim_fp,
        source_trade_fingerprint=source_trade_fp,
        committed_trade_fingerprint=expected_trade_fp,
        trade_state_revision_before=trade_sync.state_revision_before,
        trade_state_revision_after=trade_sync.state_revision_after,
        checkpoint_hash_before=checkpoint_hash_before,
        checkpoint_hash_after=_sha256(checkpoint_path),
        checkpoint_saved_at_utc=_clean(getattr(saved, "saved_at_utc", "")),
        checkpoint_reason=reason,
        recovery_path=str(recovery_path),
    )


def _previews_for_player(
    board: CPUFreeAgencyOfferBoard,
    player_id: str,
) -> tuple[Any, ...]:
    return tuple(
        row.preview
        for row in board.offers
        if row.player_id == player_id
    )


def commit_cpu_competing_market_winner_live(
    previews: Iterable[Any],
    result: FreeAgencyCompetingMarketResult,
    *,
    expected_board_fingerprint: str = "",
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
) -> CPUFreeAgencyLiveSigningResult:
    """Re-evaluate and commit one CPU-only market winner on durable state."""
    if not isinstance(result, FreeAgencyCompetingMarketResult) or not result.has_winner:
        raise CPUFreeAgencyExecutionError(
            "Only a CPU competing market with an accepted winner can be committed."
        )

    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if _checkpoint is not None:
        if not _checkpoint_hash or _sha256(checkpoint_path) != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "CPU market checkpoint changed after the execution plan was built."
            )
        checkpoint = _checkpoint
    else:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "The durable franchise checkpoint is unavailable."
            )
    state = getattr(checkpoint, "simulation_state", None)
    values = tuple(previews)
    if not values:
        raise CPUFreeAgencyExecutionError(
            "CPU competing market contains no offer previews."
        )
    current = evaluate_competing_offer_market(state, values)
    if current.market_fingerprint != result.market_fingerprint:
        raise CPUFreeAgencyExecutionError(
            "CPU competing market is stale relative to the durable franchise state."
        )
    preview, decision = winner_preview_and_decision(
        state,
        values,
        current,
    )
    if not bool(getattr(decision, "accepted", False)):
        raise CPUFreeAgencyExecutionError(
            "CPU market winner no longer has an accepted player decision."
        )
    team = _team(getattr(preview.offer, "team_abbreviation", ""))
    controlled = set(controlled_teams_from_durable_checkpoint(checkpoint))
    if team in controlled:
        raise CPUFreeAgencyExecutionError(
            "CPU market winner is user-controlled and cannot be autonomously committed."
        )

    # Offer-board previews deliberately defer the expensive full-franchise
    # candidate fingerprint. Rebuild only the deterministic winning offer with
    # the full fingerprint and require the player decision to reproduce exactly
    # before entering the durable commit stack.
    source_fingerprint = free_agency_state_fingerprint(state)
    commit_preview = build_rights_exception_free_agency_preview(
        state,
        preview.offer,
        _source_fingerprint=source_fingerprint,
    )
    if (
        _clean(getattr(commit_preview, "status", "")).lower() != "pass"
        or not bool(getattr(commit_preview, "can_commit", False))
        or not _clean(getattr(commit_preview, "candidate_fingerprint", ""))
    ):
        raise CPUFreeAgencyExecutionError(
            "CPU market winner no longer reproduces a fully fingerprinted legal preview."
        )
    commit_decision = evaluate_free_agent_offer_decision(state, commit_preview)
    if (
        not bool(getattr(commit_decision, "accepted", False))
        or _clean(getattr(commit_decision, "decision_fingerprint", ""))
        != _clean(getattr(decision, "decision_fingerprint", ""))
    ):
        raise CPUFreeAgencyExecutionError(
            "CPU market winner player decision changed during full preview verification."
        )

    signed = commit_cpu_contract_legal_free_agency_preview_live(
        commit_preview,
        market_fingerprint=current.market_fingerprint,
        recovery_directory=recovery_directory,
        _checkpoint=checkpoint,
        _checkpoint_hash=_sha256(checkpoint_path),
        _verify_bytes_only=_verify_bytes_only,
        _verified_checkpoint_sink=_verified_checkpoint_sink,
    )
    return signed



def _minimum_game_player_floor(state: Any) -> int:
    settings = getattr(state, "settings", None)
    try:
        floor = int(getattr(settings, "minimum_game_players", 8) or 8)
    except (TypeError, ValueError):
        floor = 8
    return max(5, floor)


def _cpu_roster_floor_deficits(
    state: Any,
    controlled_teams: Iterable[str],
) -> tuple[tuple[str, int, int], ...]:
    floor = _minimum_game_player_floor(state)
    controlled = {_team(value) for value in controlled_teams if _team(value)}
    rows: list[tuple[str, int, int]] = []
    teams = getattr(state, "teams", {}) or {}
    for team, team_state in teams.items():
        abbreviation = _team(team)
        if not abbreviation or abbreviation in controlled:
            continue
        roster = tuple(getattr(team_state, "roster_player_ids", ()) or ())
        count = len(roster)
        if count < floor:
            rows.append((abbreviation, count, floor - count))
    rows.sort(key=lambda row: (-row[2], row[0]))
    return tuple(rows)


def _rescue_offer_and_decision(
    state: Any,
    *,
    team_abbreviation: str,
    player_id: str,
    source_fingerprint: str | None = None,
    defer_candidate_fingerprint: bool = False,
) -> tuple[Any, Any, str] | None:
    """Return a legal player-accepted rescue preview, if one exists.

    Roster-floor rescue does not bypass CBA/financial legality or player agency.
    It first tries an exact one-year applicable minimum. If the player returns a
    bounded counter, the counter is tried only when it is no more than 150% of
    the applicable minimum and the locked backend accepts that salary.
    """
    player = getattr(state, "players", {}).get(_clean(player_id))
    if player is None:
        return None
    service, _ = resolve_years_of_service(player)
    minimum = minimum_salary_floor_for_state(
        state,
        years_of_service=service,
        contract_years=1,
    )
    if minimum is None or float(minimum) <= 0.0:
        return None

    team = _team(team_abbreviation)
    base_offer = FreeAgencyOffer(
        player_id=_clean(player_id),
        team_abbreviation=team,
        annual_salary=round(float(minimum), 2),
        years=1,
        guaranteed=True,
        option_type="",
    )
    try:
        try:
            preview = build_rights_exception_free_agency_preview(
                state,
                base_offer,
                _source_fingerprint=source_fingerprint,
                _defer_candidate_fingerprint=defer_candidate_fingerprint,
            )
        except TypeError as exc:
            # Fixture/custom builders written before the internal shared-
            # fingerprint optimization retain their two-argument contract.
            if not any(
                token in str(exc)
                for token in ("_source_fingerprint", "_defer_candidate_fingerprint")
            ):
                raise
            preview = build_rights_exception_free_agency_preview(state, base_offer)
    except Exception:
        return None
    if _clean(getattr(preview, "status", "")).lower() != "pass" or not bool(
        getattr(preview, "can_commit", False)
    ):
        return None
    try:
        decision = evaluate_free_agent_offer_decision(state, preview)
    except Exception:
        return None
    if bool(getattr(decision, "accepted", False)):
        return preview, decision, "exact_minimum_accept"

    counter = getattr(decision, "counter_salary", None)
    try:
        counter_value = float(counter)
    except (TypeError, ValueError):
        return None
    if not counter_value > float(minimum):
        return None
    if counter_value > float(minimum) * CPU_FREE_AGENCY_ROSTER_FLOOR_MAX_COUNTER_MULTIPLIER + 0.01:
        return None

    counter_offer = FreeAgencyOffer(
        player_id=_clean(player_id),
        team_abbreviation=team,
        annual_salary=round(counter_value, 2),
        years=1,
        guaranteed=True,
        option_type="",
    )
    try:
        try:
            counter_preview = build_rights_exception_free_agency_preview(
                state,
                counter_offer,
                _source_fingerprint=source_fingerprint,
                _defer_candidate_fingerprint=defer_candidate_fingerprint,
            )
        except TypeError as exc:
            if not any(
                token in str(exc)
                for token in ("_source_fingerprint", "_defer_candidate_fingerprint")
            ):
                raise
            counter_preview = build_rights_exception_free_agency_preview(
                state,
                counter_offer,
            )
    except Exception:
        return None
    if _clean(getattr(counter_preview, "status", "")).lower() != "pass" or not bool(
        getattr(counter_preview, "can_commit", False)
    ):
        return None
    try:
        counter_decision = evaluate_free_agent_offer_decision(
            state,
            counter_preview,
        )
    except Exception:
        return None
    if not bool(getattr(counter_decision, "accepted", False)):
        return None
    return counter_preview, counter_decision, "bounded_counter_accept"


def build_cpu_roster_floor_rescue_opportunity(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> CPUFreeAgencyRosterFloorRescueOpportunity | None:
    """Find one deterministic legal/willing signing after the normal CPU market exhausts.

    This path exists only to satisfy the simulator's game-ready roster floor. It
    never runs for a team already at the floor, never runs for a controlled team,
    and never bypasses the locked Free Agency financial gate or player decision.
    """
    deficits = _cpu_roster_floor_deficits(state, controlled_teams)
    if not deficits:
        return None

    free_ids = {
        _clean(value)
        for value in (getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(value)
    }
    if not free_ids:
        return None

    source_fingerprint = free_agency_state_fingerprint(state)
    # Every accepted rescue salary is at least the player's applicable minimum.
    # Price candidates first, then stop once that lower bound exceeds the best
    # accepted salary already found. This preserves the exact selection order
    # while avoiding expensive full previews for provably noncompetitive bands.
    priced_free_agents: list[tuple[float, str]] = []
    players = getattr(state, "players", {}) or {}
    for player_id in free_ids:
        player = players.get(player_id)
        if player is None:
            continue
        service, _ = resolve_years_of_service(player)
        minimum = minimum_salary_floor_for_state(
            state,
            years_of_service=service,
            contract_years=1,
        )
        try:
            minimum_value = float(minimum)
        except (TypeError, ValueError):
            continue
        if minimum_value > 0.0:
            priced_free_agents.append((minimum_value, player_id))
    priced_free_agents.sort(key=lambda row: (row[0], row[1]))
    if not priced_free_agents:
        return None

    floor = _minimum_game_player_floor(state)
    for team, roster_count, deficit in deficits:
        candidates: list[CPUFreeAgencyRosterFloorRescueOpportunity] = []
        best_salary: float | None = None
        for minimum_value, player_id in priced_free_agents:
            if best_salary is not None and minimum_value > best_salary + 0.01:
                break
            resolved = _rescue_offer_and_decision(
                state,
                team_abbreviation=team,
                player_id=player_id,
                source_fingerprint=source_fingerprint,
                defer_candidate_fingerprint=True,
            )
            if resolved is None:
                continue
            preview, decision, offer_path = resolved
            player = getattr(state, "players", {}).get(player_id)
            overall_raw = getattr(player, "overall_rating", 0.0)
            try:
                overall = float(overall_raw or 0.0)
            except (TypeError, ValueError):
                overall = 0.0
            utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
            threshold = float(
                getattr(decision, "acceptance_threshold", 0.0) or 0.0
            )
            offer = getattr(preview, "offer", None)
            salary = float(getattr(offer, "annual_salary", 0.0) or 0.0)
            years = int(getattr(offer, "years", 1) or 1)
            fingerprint = _fingerprint(
                {
                    "version": CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION,
                    "season": _season(state),
                    "team": team,
                    "roster_count": roster_count,
                    "floor": floor,
                    "deficit": deficit,
                    "player": player_id,
                    "salary": round(salary, 2),
                    "years": years,
                    "offer_path": offer_path,
                    "decision_fingerprint": _clean(
                        getattr(decision, "decision_fingerprint", "")
                    ),
                    "source_fingerprint": _clean(
                        getattr(preview, "source_fingerprint", "")
                    ),
                }
            )
            candidates.append(
                CPUFreeAgencyRosterFloorRescueOpportunity(
                    version=CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION,
                    scope=CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_SCOPE,
                    team_abbreviation=team,
                    roster_count_before=roster_count,
                    minimum_game_players=floor,
                    roster_deficit=deficit,
                    player_id=player_id,
                    player_name=_clean(getattr(player, "player_name", ""))
                    or player_id,
                    annual_salary=round(salary, 2),
                    years=years,
                    offer_path=offer_path,
                    player_utility_score=round(utility, 3),
                    acceptance_threshold=round(threshold, 3),
                    player_overall=round(overall, 3),
                    preview=preview,
                    decision_fingerprint=_clean(
                        getattr(decision, "decision_fingerprint", "")
                    ),
                    rescue_fingerprint=fingerprint,
                )
            )
            if best_salary is None or salary < best_salary:
                best_salary = salary

        if candidates:
            # Deficits are already ordered by urgency and team. Once this team
            # has a candidate, no later team can outrank it under the established
            # deterministic ordering.
            candidates.sort(
                key=lambda row: (
                    row.annual_salary,
                    -row.player_utility_score,
                    -row.player_overall,
                    row.player_id,
                )
            )
            return candidates[0]

    return None


def _commit_cpu_roster_floor_rescue_durably(
    opportunity: CPUFreeAgencyRosterFloorRescueOpportunity,
    *,
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
) -> CPUFreeAgencyLiveSigningResult:
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if _checkpoint is not None:
        if not _checkpoint_hash or _sha256(checkpoint_path) != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "Roster-floor rescue checkpoint changed after selection."
            )
        checkpoint = _checkpoint
        checkpoint_hash = _checkpoint_hash
    else:
        checkpoint_hash = _sha256(checkpoint_path)
        checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise CPUFreeAgencyExecutionError(
            "The durable franchise checkpoint is unavailable for roster-floor rescue."
        )
    state = checkpoint.simulation_state
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    deficits = _cpu_roster_floor_deficits(state, controlled)
    expected_deficit = (
        opportunity.team_abbreviation,
        opportunity.roster_count_before,
        opportunity.roster_deficit,
    )
    observed_deficit = (
        (deficits[0][0], deficits[0][1], deficits[0][2])
        if deficits
        else None
    )
    if observed_deficit != expected_deficit:
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue is stale because the leading CPU roster deficit changed."
        )

    source_fingerprint = free_agency_state_fingerprint(state)
    expected_source_fingerprint = _clean(
        getattr(opportunity.preview, "source_fingerprint", "")
    )
    if not expected_source_fingerprint or source_fingerprint != expected_source_fingerprint:
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue is stale relative to the durable franchise state."
        )

    resolved = _rescue_offer_and_decision(
        state,
        team_abbreviation=opportunity.team_abbreviation,
        player_id=opportunity.player_id,
        source_fingerprint=source_fingerprint,
    )
    if resolved is None:
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue candidate is no longer legal and accepted."
        )
    current_preview, current_decision, current_offer_path = resolved
    current_offer = getattr(current_preview, "offer", None)
    expected_offer = getattr(opportunity.preview, "offer", None)
    same_offer = bool(
        current_offer is not None
        and expected_offer is not None
        and _clean(getattr(current_offer, "player_id", "")) == opportunity.player_id
        and _team(getattr(current_offer, "team_abbreviation", ""))
        == opportunity.team_abbreviation
        and abs(
            float(getattr(current_offer, "annual_salary", 0.0) or 0.0)
            - float(opportunity.annual_salary)
        )
        < 0.01
        and int(getattr(current_offer, "years", 0) or 0) == opportunity.years
    )
    if (
        not same_offer
        or current_offer_path != opportunity.offer_path
        or not _clean(getattr(current_preview, "candidate_fingerprint", ""))
    ):
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue candidate changed before durable commit."
        )
    if not bool(getattr(current_decision, "accepted", False)):
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue candidate is no longer accepted by the player."
        )
    if _clean(getattr(current_decision, "decision_fingerprint", "")) != opportunity.decision_fingerprint:
        raise CPUFreeAgencyExecutionError(
            "Roster-floor rescue player decision changed before durable commit."
        )

    return commit_cpu_contract_legal_free_agency_preview_live(
        current_preview,
        market_fingerprint=f"roster-floor-rescue:{opportunity.rescue_fingerprint}",
        recovery_directory=recovery_directory,
        _checkpoint=checkpoint,
        _checkpoint_hash=checkpoint_hash,
        _verify_bytes_only=_verify_bytes_only,
        _verified_checkpoint_sink=_verified_checkpoint_sink,
    )



def execute_next_cpu_free_agency_signing_durably(
    *,
    max_targets_per_team: int = 5,
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
) -> CPUFreeAgencyExecutionStepResult:
    """Commit at most one CPU free-agent winner, rebuilding from durable state."""
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if _checkpoint is not None:
        checkpoint_hash = _sha256(checkpoint_path)
        if not _checkpoint_hash or checkpoint_hash != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "CPU Free Agency checkpoint changed before the next market rebuild."
            )
        checkpoint = _checkpoint
    else:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "The durable franchise checkpoint is unavailable."
            )
        checkpoint_hash = _sha256(checkpoint_path)
    state = checkpoint.simulation_state
    if _phase(state) != "offseason":
        raise CPUFreeAgencyExecutionError(
            "CPU free-agency execution can run only during the actual offseason."
        )
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    plan = build_cpu_free_agency_execution_plan(
        state,
        controlled_teams=controlled,
        max_targets_per_team=max_targets_per_team,
    )
    if not plan.opportunities:
        rescue = build_cpu_roster_floor_rescue_opportunity(
            state,
            controlled_teams=controlled,
        )
        if rescue is not None:
            signed = _commit_cpu_roster_floor_rescue_durably(
                rescue,
                recovery_directory=recovery_directory,
                _checkpoint=checkpoint,
                _checkpoint_hash=checkpoint_hash,
                _verify_bytes_only=_verify_bytes_only,
                _verified_checkpoint_sink=_verified_checkpoint_sink,
            )
            return CPUFreeAgencyExecutionStepResult(
                version=CPU_FREE_AGENCY_EXECUTION_VERSION,
                status="committed_roster_floor_rescue",
                plan_fingerprint=plan.plan_fingerprint,
                board_fingerprint=plan.board_fingerprint,
                market_fingerprint=f"roster-floor-rescue:{rescue.rescue_fingerprint}",
                signing=signed,
                message=(
                    f"Roster-floor rescue: {signed.player_name} signed with "
                    f"{signed.team_abbreviation} for ${signed.annual_salary:,.0f} per year."
                ),
            )
        return CPUFreeAgencyExecutionStepResult(
            version=CPU_FREE_AGENCY_EXECUTION_VERSION,
            status="no_accepted_cpu_market",
            plan_fingerprint=plan.plan_fingerprint,
            board_fingerprint=plan.board_fingerprint,
            market_fingerprint=None,
            signing=None,
            message="No current CPU-only market has an accepted player destination and no underfilled CPU team has a legal player-accepted roster-floor rescue.",
        )

    opportunity = plan.opportunities[0]
    player_market = next(
        (
            item
            for item in plan.markets
            if item.player_id == opportunity.player_id
            and item.market.market_fingerprint == opportunity.market_fingerprint
        ),
        None,
    )
    if player_market is None:
        raise CPUFreeAgencyExecutionError(
            "Top CPU execution opportunity could not be reconciled to the market plan."
        )
    previews = _previews_for_player(plan.board, opportunity.player_id)
    signed = commit_cpu_competing_market_winner_live(
        previews,
        player_market.market,
        expected_board_fingerprint=plan.board_fingerprint,
        recovery_directory=recovery_directory,
        _checkpoint=checkpoint,
        _checkpoint_hash=checkpoint_hash,
        _verify_bytes_only=_verify_bytes_only,
        _verified_checkpoint_sink=_verified_checkpoint_sink,
    )
    return CPUFreeAgencyExecutionStepResult(
        version=CPU_FREE_AGENCY_EXECUTION_VERSION,
        status="committed",
        plan_fingerprint=plan.plan_fingerprint,
        board_fingerprint=plan.board_fingerprint,
        market_fingerprint=opportunity.market_fingerprint,
        signing=signed,
        message=(
            f"{signed.player_name} signed with {signed.team_abbreviation} "
            f"for ${signed.annual_salary:,.0f} per year."
        ),
    )


def execute_cpu_free_agency_round_durably(
    *,
    max_signings: int = DEFAULT_CPU_FREE_AGENCY_MAX_SIGNINGS_PER_ROUND,
    max_targets_per_team: int = 5,
    recovery_directory: str | Path | None = None,
) -> CPUFreeAgencyRoundResult:
    """Run a bounded CPU free-agency round with one atomic FATX at a time.

    Consecutive signings carry forward the exact in-memory checkpoint that was
    just atomically encoded and byte-verified. This avoids repeatedly decoding
    and hot-rebinding a mature franchise graph. A normal semantic checkpoint
    reload is still mandatory once at the end of every round.
    """
    if max_signings < 1 or max_signings > 15:
        raise CPUFreeAgencyExecutionError(
            "max_signings must be between 1 and 15."
        )

    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before = _sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise CPUFreeAgencyExecutionError(
            "The durable franchise checkpoint is unavailable."
        )
    if _phase(checkpoint.simulation_state) != "offseason":
        raise CPUFreeAgencyExecutionError(
            "CPU free-agency rounds can run only during the actual offseason."
        )

    committed: list[CPUFreeAgencyLiveSigningResult] = []
    stop_reason = "round_limit_reached"
    partial_error = ""
    checkpoint_hash = before

    for _ in range(max_signings):
        controlled = controlled_teams_from_durable_checkpoint(checkpoint)
        if not _cpu_roster_floor_deficits(checkpoint.simulation_state, controlled):
            stop_reason = "all_cpu_teams_meet_roster_floor"
            break

        verified_sink: list[Any] = []
        try:
            step = execute_next_cpu_free_agency_signing_durably(
                max_targets_per_team=max_targets_per_team,
                recovery_directory=recovery_directory,
                _checkpoint=checkpoint,
                _checkpoint_hash=checkpoint_hash,
                _verify_bytes_only=True,
                _verified_checkpoint_sink=verified_sink,
            )
        except Exception as exc:
            if committed:
                partial_error = f"{type(exc).__name__}: {exc}"
                stop_reason = partial_error
                break
            raise

        if not step.committed:
            stop_reason = step.status
            break
        if not verified_sink:
            raise CPUFreeAgencyExecutionError(
                "CPU Free Agency commit did not return its byte-verified checkpoint."
            )

        committed.append(step.signing)
        checkpoint = verified_sink[-1]
        checkpoint_hash = _sha256(checkpoint_path)

        controlled = controlled_teams_from_durable_checkpoint(checkpoint)
        if not _cpu_roster_floor_deficits(checkpoint.simulation_state, controlled):
            stop_reason = "all_cpu_teams_meet_roster_floor"
            break

    if len(committed) >= max_signings and stop_reason == "round_limit_reached":
        stop_reason = "round_limit_reached"

    # Byte verification protects every atomic write. Capture the expected
    # semantic fingerprints, then release the carried mature graph before the
    # ordinary final hot-rebind reload. Holding two deep-season checkpoint
    # graphs simultaneously can cause severe allocator/memory-pressure stalls.
    expected_sim = free_agency_durable_state_fingerprint(checkpoint.simulation_state)
    expected_trade = trade_state_fingerprint(checkpoint.trade_state)
    checkpoint = None
    try:
        verified_sink.clear()
    except NameError:
        pass
    gc.collect()

    semantic = load_franchise_checkpoint()
    if semantic is None:
        raise CPUFreeAgencyExecutionError(
            "CPU Free Agency final semantic checkpoint reload returned no state."
        )
    observed_sim = free_agency_durable_state_fingerprint(semantic.simulation_state)
    observed_trade = trade_state_fingerprint(semantic.trade_state)
    if expected_sim != observed_sim or expected_trade != observed_trade:
        raise CPUFreeAgencyExecutionError(
            "CPU Free Agency final semantic reload does not match the byte-verified round state."
        )
    # Do not retain a second mature checkpoint graph after verification. The
    # lifecycle caller immediately reloads the durable checkpoint for its next
    # stage, so release this verification graph before returning.
    semantic = None
    gc.collect()

    status = (
        "partial_failure"
        if partial_error
        else ("completed" if committed else "no_action")
    )
    return CPUFreeAgencyRoundResult(
        version=CPU_FREE_AGENCY_EXECUTION_VERSION,
        status=status,
        requested_max_signings=max_signings,
        committed_signing_count=len(committed),
        signings=tuple(committed),
        stop_reason=stop_reason,
        checkpoint_hash_before=before,
        checkpoint_hash_after=_sha256(checkpoint_path),
    )


def cpu_execution_contract_report() -> dict[str, Any]:
    return {
        "version": CPU_FREE_AGENCY_EXECUTION_VERSION,
        "scope": CPU_FREE_AGENCY_EXECUTION_SCOPE,
        "confirmation_token": CPU_FREE_AGENCY_CONFIRMATION_TOKEN,
        "default_round_limit": DEFAULT_CPU_FREE_AGENCY_MAX_SIGNINGS_PER_ROUND,
        "offer_generation_version": CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "competing_market_version": FREE_AGENCY_COMPETING_MARKET_VERSION,
        "player_decision_version": FREE_AGENCY_PLAYER_DECISION_VERSION,
        "live_signing_version_preserved": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "trade_sync_version_preserved": FREE_AGENCY_TRADE_STATE_SYNC_VERSION,
        "salary_legality_version": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
        "durable_commit_version": FREE_AGENCY_DURABLE_COMMIT_VERSION,
        "user_controlled_team_commit_allowed": False,
        "actual_offseason_required": True,
        "board_rebuilt_after_each_signing": True,
        "deep_season_performance_version": CPU_FREE_AGENCY_DEEP_SEASON_PERFORMANCE_VERSION,
        "speculative_candidate_fingerprints_deferred": True,
        "round_carries_byte_verified_checkpoint": True,
        "round_final_semantic_reload_required": True,
        "round_stops_when_roster_floor_complete": True,
        "autonomous_background_execution": False,
        "cpu_only_markets": True,
        "user_offer_injection": False,
        "roster_floor_rescue_version": CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION,
        "roster_floor_rescue_runs_only_after_standard_market_exhausts": True,
        "roster_floor_rescue_cpu_only": True,
        "roster_floor_rescue_requires_underfilled_team": True,
        "roster_floor_rescue_preserves_locked_financial_gate": True,
        "roster_floor_rescue_requires_player_acceptance": True,
        "roster_floor_rescue_counter_cap_multiplier": CPU_FREE_AGENCY_ROSTER_FLOOR_MAX_COUNTER_MULTIPLIER,
        "roster_floor_rescue_salary_lower_bound_pruning": True,
        "roster_floor_rescue_commit_revalidates_source_fingerprint": True,
        "roster_floor_rescue_commit_rechecks_exact_candidate_only": True,
        "cpu_durable_candidate_copy_on_write": True,
        "cpu_save_skips_redundant_payload_copy": True,
    }
