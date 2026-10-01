from __future__ import annotations

import copy
import gc
import hashlib
import json
import shutil
from dataclasses import dataclass, replace
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
    resolve_years_of_service_for_state,
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
    commit_free_agency_preview,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_DURABLE_COMMIT_VERSION,
    build_free_agency_durable_candidate,
    free_agency_durable_state_fingerprint,
)

CPU_FREE_AGENCY_EXECUTION_VERSION = (
    "franchise-free-agency-cpu-execution-v1.2-batched-durability-2026-09-28"
)
CPU_FREE_AGENCY_EXECUTION_SCOPE = (
    "actual_offseason_cpu_only_market_execution_bounded_market_refresh_with_current_offer_revalidation_and_batched_durability"
)
CPU_FREE_AGENCY_CONFIRMATION_TOKEN = "CPU_FREE_AGENCY_EXECUTION_V1"
DEFAULT_CPU_FREE_AGENCY_MAX_SIGNINGS_PER_ROUND = 3
CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION = (
    "franchise-free-agency-cpu-roster-floor-rescue-v1.2-floor-first-2026-09-15"
)
CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_SCOPE = (
    "post-market-cpu-only-game-ready-floor-rescue-with-legal-player-accepted-offers"
)
CPU_FREE_AGENCY_ROSTER_FLOOR_MAX_COUNTER_MULTIPLIER = 1.50
CPU_FREE_AGENCY_DEEP_SEASON_PERFORMANCE_VERSION = (
    "franchise-free-agency-deep-season-performance-v3-floor-first-2026-09-17"
)
CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_CONSTRUCTION_VERSION = (
    "franchise-free-agency-sustainable-roster-construction-v2.0-phase1-2026-09-24"
)
CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET = 14
CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_VERSION = (
    "franchise-free-agency-sustainable-roster-completion-v1.2-bounded-market-refresh-2026-09-27"
)
CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_SCOPE = (
    "post-normal-market-under-14-cpu-depth-completion-legal-player-accepted-only"
)

CPU_FREE_AGENCY_BOUNDED_MARKET_REFRESH_VERSION = (
    "franchise-free-agency-bounded-market-refresh-v1-2026-09-24"
)
CPU_FREE_AGENCY_DURABLE_INTEGRITY_REUSE_VERSION = (
    "franchise-free-agency-durable-integrity-reuse-v1-2026-09-25"
)
CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL = 5
CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_MARKET_REFRESH_INTERVAL = 5
CPU_FREE_AGENCY_DURABLE_BATCH_VERSION = (
    "franchise-free-agency-durable-batch-v1.0.1-2026-09-28"
)
CPU_FREE_AGENCY_DURABLE_BATCH_SIZE = 5


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


@dataclass(frozen=True)
class CPUFreeAgencySustainableRosterCompletionOpportunity:
    version: str
    scope: str
    team_abbreviation: str
    roster_count_before: int
    sustainable_roster_target: int
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
    completion_fingerprint: str


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
    eligible_teams: Iterable[str] | None = None,
    front_office_plan: Any | None = None,
    max_targets_per_team: int = 5,
) -> CPUFreeAgencyExecutionPlan:
    """Build the next CPU execution plan without mutating franchise state.

    Offer Generation V1 and Competing Market V1 remain the authorities for CPU
    bid construction and player destination choice. This plan only orders markets
    that already have an accepted CPU winner. When ``eligible_teams`` is supplied,
    ordinary bids are limited to those CPU teams without changing CBA legality or
    player acceptance.
    """
    controlled = tuple(
        sorted({_team(value) for value in controlled_teams if _team(value)})
    )
    eligible = (
        None
        if eligible_teams is None
        else tuple(sorted({_team(value) for value in eligible_teams if _team(value)}))
    )
    board = build_cpu_free_agency_offer_board(
        state,
        controlled_teams=controlled,
        eligible_teams=eligible,
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
        "eligible": eligible,
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

    checkpoint = load_franchise_checkpoint(path=checkpoint_path)
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
    _defer_durable_write: bool = False,
) -> CPUFreeAgencyLiveSigningResult:
    """Commit one accepted CPU signing through the same dual-state FATX stack.

    The only authorization difference from user Live Signing V1 is intentional:
    the destination MUST be a CPU team and MUST NOT be user-controlled. All other
    legality, stale-state, candidate, Trade Machine sync, checkpoint reload, and
    automatic-recovery guarantees are preserved.
    """
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        FranchiseCheckpoint,
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
        checkpoint_hash_before = _checkpoint_hash
    else:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "Durable franchise checkpoint could not be loaded."
            )
        checkpoint_hash_before = _sha256(checkpoint_path)
    assert_cpu_live_commit_preconditions(checkpoint, preview)

    source_sim = checkpoint.simulation_state
    source_trade = checkpoint.trade_state
    validate_simulation_league_state(source_sim)

    # assert_cpu_live_commit_preconditions already proved that the live
    # simulation state matches this exact preview fingerprint. Reuse that
    # evidence instead of traversing the mature state again.
    source_sim_fp = _clean(getattr(preview, "source_fingerprint", ""))
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
            _source_fingerprint=source_sim_fp,
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
    candidate_state_fp = free_agency_state_fingerprint(
        simulation_candidate
    )
    if isinstance(history, list) and history:
        history[-1]["candidate_fingerprint"] = candidate_state_fp
        history[-1]["execution_actor"] = "cpu_front_office"
        history[-1]["competing_market_fingerprint"] = _clean(
            market_fingerprint
        )

    expected_sim_fp = free_agency_durable_state_fingerprint(
        simulation_candidate,
        _v1_state_fingerprint=candidate_state_fp,
    )
    expected_trade_fp = trade_state_fingerprint(trade_candidate)

    reason = f"free-agency-cpu-signing-{transaction_id}"
    recovery_path: Path | None = None
    verified_file_sha256_sink: list[str] = []

    if _defer_durable_write:
        # Round-batched durability: all legality, stale-state, candidate,
        # Trade Machine synchronization, and fingerprint checks still execute
        # for every signing, but the mature checkpoint graph is not serialized
        # until the bounded batch flush. The on-disk checkpoint therefore
        # remains the authoritative stale-write token during the batch.
        try:
            saved = FranchiseCheckpoint(
                version=_clean(getattr(checkpoint, "version", "")),
                saved_at_utc=datetime.now(timezone.utc).isoformat(),
                simulation_state=simulation_candidate,
                trade_state=trade_candidate,
                preferences=_preference_dict(checkpoint),
                reason=reason,
            )
            reloaded = saved
            if _verified_checkpoint_sink is not None:
                _verified_checkpoint_sink.append(reloaded)

            observed_sim_fp = expected_sim_fp
            observed_trade_fp = expected_trade_fp
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
                    "CPU FATX metadata did not survive the deferred in-memory commit."
                )
            owner = _team(
                reloaded.trade_state.player_team_by_id.get(
                    preview.offer.player_id,
                    "",
                )
            )
            if owner != _team(preview.offer.team_abbreviation):
                raise CPUFreeAgencyExecutionError(
                    "Trade Machine CPU player ownership did not survive the deferred in-memory commit."
                )
        except Exception as exc:
            raise CPUFreeAgencyExecutionError(
                "CPU signing failed before the durable batch flush: "
                f"{exc}"
            ) from exc
    else:
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
                # Preserve the hash proven at commit entry. The writer performs the
                # authoritative just-before-write comparison against this same hash,
                # which both removes one redundant read and strengthens stale-write
                # detection across candidate construction.
                _expected_existing_sha256=checkpoint_hash_before,
                _verify_encoded_bytes_only=_verify_bytes_only,
                _verified_file_sha256_sink=verified_file_sha256_sink,
            )
            # The writer has already verified the just-written primary. In batched
            # byte-verification mode, saved is the exact object graph that was
            # encoded, and the round performs one ordinary semantic reload at the
            # end. Recomputing whole-state fingerprints against the same in-memory
            # objects after every signing adds no new evidence.
            reloaded = saved
            if _verified_checkpoint_sink is not None:
                _verified_checkpoint_sink.append(reloaded)
            if _verify_bytes_only:
                observed_sim_fp = expected_sim_fp
                observed_trade_fp = expected_trade_fp
            else:
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
            assert recovery_path is not None
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
        checkpoint_hash_after=(
            checkpoint_hash_before
            if _defer_durable_write
            else (
                verified_file_sha256_sink[-1]
                if verified_file_sha256_sink
                else _sha256(checkpoint_path)
            )
        ),
        checkpoint_saved_at_utc=_clean(getattr(saved, "saved_at_utc", "")),
        checkpoint_reason=reason,
        recovery_path=(str(recovery_path) if recovery_path is not None else ""),
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
    _defer_durable_write: bool = False,
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
        checkpoint_hash = _sha256(checkpoint_path)
        if not _checkpoint_hash or checkpoint_hash != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "CPU market checkpoint changed after the execution plan was built."
            )
        checkpoint = _checkpoint
        checkpoint_hash = _checkpoint_hash
    else:
        checkpoint = load_franchise_checkpoint()
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "The durable franchise checkpoint is unavailable."
            )
        checkpoint_hash = _sha256(checkpoint_path)
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
        _checkpoint_hash=checkpoint_hash,
        _verify_bytes_only=_verify_bytes_only,
        _verified_checkpoint_sink=_verified_checkpoint_sink,
        _defer_durable_write=_defer_durable_write,
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


def cpu_sustainable_roster_target(state: Any) -> int:
    """Return the V2 normal-market roster construction target.

    ``minimum_game_players`` remains an emergency playability invariant.  It is
    intentionally not reused as the offseason roster-construction completion
    condition.  Phase 1 uses a 14-player normal roster target without adding a
    save field or changing the simulator's emergency game floor.
    """
    floor = _minimum_game_player_floor(state)
    return max(floor, CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET)


def cpu_sustainable_roster_deficits(
    state: Any,
    controlled_teams: Iterable[str] = (),
) -> tuple[tuple[str, int, int], ...]:
    """Return CPU teams below the V2 normal-market roster target.

    Rows are ``(team, roster_count, deficit)`` and are ordered by largest
    deficit first.  User-controlled teams are never autonomously filled.
    """
    target = cpu_sustainable_roster_target(state)
    controlled = {_team(value) for value in controlled_teams if _team(value)}
    rows: list[tuple[str, int, int]] = []
    teams = getattr(state, "teams", {}) or {}
    for team, team_state in teams.items():
        abbreviation = _team(team)
        if not abbreviation or abbreviation in controlled:
            continue
        roster = tuple(getattr(team_state, "roster_player_ids", ()) or ())
        count = len(roster)
        if count < target:
            rows.append((abbreviation, count, target - count))
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
    service, _ = resolve_years_of_service_for_state(
        state,
        player_id,
    )
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
        service, _ = resolve_years_of_service_for_state(
            state,
            player_id,
        )
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



def build_cpu_sustainable_roster_completion_opportunity(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> CPUFreeAgencySustainableRosterCompletionOpportunity | None:
    """Find one legal, player-accepted depth signing after the normal market exhausts.

    This is deliberately different from emergency roster-floor rescue:
    - it runs only for CPU teams below the V2 sustainable roster target;
    - it runs only after the ordinary CPU market has no accepted winner;
    - it never uses market-clearance overrides or synthetic players;
    - it preserves the locked Free Agency financial gate and player decision;
    - it may use pure cap space, proven prior-team rights, or the exact one-year
      Minimum Salary Exception only when the existing backend can prove that route.

    The purpose is to broaden the *target search* for depth, not to weaken any
    contract, CBA, player-agency, or roster rule.
    """
    deficits = cpu_sustainable_roster_deficits(state, controlled_teams)
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
    players = getattr(state, "players", {}) or {}

    # Price by the existing salary-floor authority. Unknown service can still
    # produce a conservative legal *pure-cap* offer, while the locked exception
    # gate continues to reject an unproven Minimum Salary Exception route.
    priced_free_agents: list[tuple[float, str]] = []
    for player_id in free_ids:
        player = players.get(player_id)
        if player is None:
            continue
        service, _ = resolve_years_of_service_for_state(
            state,
            player_id,
        )
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

    target = cpu_sustainable_roster_target(state)
    for team, roster_count, deficit in deficits:
        candidates: list[CPUFreeAgencySustainableRosterCompletionOpportunity] = []
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
            player = players.get(player_id)
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
                    "version": CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_VERSION,
                    "season": _season(state),
                    "team": team,
                    "roster_count": roster_count,
                    "sustainable_target": target,
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
                CPUFreeAgencySustainableRosterCompletionOpportunity(
                    version=CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_VERSION,
                    scope=CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_SCOPE,
                    team_abbreviation=team,
                    roster_count_before=roster_count,
                    sustainable_roster_target=target,
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
                    completion_fingerprint=fingerprint,
                )
            )
            if best_salary is None or salary < best_salary:
                best_salary = salary

        if candidates:
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


def _commit_cpu_sustainable_roster_completion_durably(
    opportunity: CPUFreeAgencySustainableRosterCompletionOpportunity,
    *,
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
    _defer_durable_write: bool = False,
) -> CPUFreeAgencyLiveSigningResult:
    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
    )

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if _checkpoint is not None:
        if not _checkpoint_hash or _sha256(checkpoint_path) != _checkpoint_hash:
            raise CPUFreeAgencyExecutionError(
                "Sustainable roster completion checkpoint changed after selection."
            )
        checkpoint = _checkpoint
        checkpoint_hash = _checkpoint_hash
    else:
        checkpoint_hash = _sha256(checkpoint_path)
        checkpoint = load_franchise_checkpoint()

    if checkpoint is None:
        raise CPUFreeAgencyExecutionError(
            "The durable franchise checkpoint is unavailable for sustainable roster completion."
        )

    state = checkpoint.simulation_state
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    deficits = cpu_sustainable_roster_deficits(state, controlled)
    expected_deficit = (
        opportunity.team_abbreviation,
        opportunity.roster_count_before,
        opportunity.roster_deficit,
    )
    # The completion search is allowed to skip an earlier under-target team
    # when that team has no legal/player-accepted candidate and select a later
    # under-target CPU team that does. Revalidation therefore must look up the
    # selected team specifically rather than assuming it is deficits[0].
    observed_deficit = next(
        (
            (team, roster_count, deficit)
            for team, roster_count, deficit in deficits
            if team == opportunity.team_abbreviation
        ),
        None,
    )
    if observed_deficit != expected_deficit:
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion is stale because the selected CPU "
            "team's roster deficit changed."
        )

    source_fingerprint = free_agency_state_fingerprint(state)
    expected_source_fingerprint = _clean(
        getattr(opportunity.preview, "source_fingerprint", "")
    )
    if (
        not expected_source_fingerprint
        or source_fingerprint != expected_source_fingerprint
    ):
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion is stale relative to the durable "
            "franchise state."
        )

    resolved = _rescue_offer_and_decision(
        state,
        team_abbreviation=opportunity.team_abbreviation,
        player_id=opportunity.player_id,
        source_fingerprint=source_fingerprint,
    )
    if resolved is None:
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion candidate is no longer legal and accepted."
        )

    current_preview, current_decision, current_offer_path = resolved
    current_offer = getattr(current_preview, "offer", None)
    expected_offer = getattr(opportunity.preview, "offer", None)
    same_offer = bool(
        current_offer is not None
        and expected_offer is not None
        and _clean(getattr(current_offer, "player_id", ""))
        == opportunity.player_id
        and _team(getattr(current_offer, "team_abbreviation", ""))
        == opportunity.team_abbreviation
        and abs(
            float(getattr(current_offer, "annual_salary", 0.0) or 0.0)
            - float(opportunity.annual_salary)
        )
        < 0.01
        and int(getattr(current_offer, "years", 0) or 0)
        == opportunity.years
    )
    if (
        not same_offer
        or current_offer_path != opportunity.offer_path
        or not _clean(getattr(current_preview, "candidate_fingerprint", ""))
    ):
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion candidate changed before durable commit."
        )

    if not bool(getattr(current_decision, "accepted", False)):
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion candidate is no longer accepted by the player."
        )
    if (
        _clean(getattr(current_decision, "decision_fingerprint", ""))
        != opportunity.decision_fingerprint
    ):
        raise CPUFreeAgencyExecutionError(
            "Sustainable roster completion player decision changed before durable commit."
        )

    return commit_cpu_contract_legal_free_agency_preview_live(
        current_preview,
        market_fingerprint=(
            "sustainable-roster-completion:"
            + opportunity.completion_fingerprint
        ),
        recovery_directory=recovery_directory,
        _checkpoint=checkpoint,
        _checkpoint_hash=checkpoint_hash,
        _verify_bytes_only=_verify_bytes_only,
        _verified_checkpoint_sink=_verified_checkpoint_sink,
        _defer_durable_write=_defer_durable_write,
    )


def _commit_cpu_roster_floor_rescue_durably(
    opportunity: CPUFreeAgencyRosterFloorRescueOpportunity,
    *,
    recovery_directory: str | Path | None = None,
    _checkpoint: Any | None = None,
    _checkpoint_hash: str = "",
    _verify_bytes_only: bool = False,
    _verified_checkpoint_sink: list[Any] | None = None,
    _defer_durable_write: bool = False,
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
        _defer_durable_write=_defer_durable_write,
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
    sustainable_deficits = cpu_sustainable_roster_deficits(state, controlled)
    if not sustainable_deficits:
        return CPUFreeAgencyExecutionStepResult(
            version=CPU_FREE_AGENCY_EXECUTION_VERSION,
            status="all_cpu_teams_meet_sustainable_roster_target",
            plan_fingerprint="",
            board_fingerprint="",
            market_fingerprint=None,
            signing=None,
            message=(
                "All CPU teams meet the V2 sustainable roster target; "
                "no autonomous Free Agency signing is required."
            ),
        )

    # A playable roster is a lifecycle invariant, not a market preference.
    # Prioritise one legal, player-accepted rescue whenever a CPU team is below
    # the game-ready floor. Build the league-wide ordinary offer board only when
    # no rescue exists: the board is irrelevant to a floor rescue and rebuilding
    # it before every rescue made deep offseasons scale with
    # (free-agent pool x teams x rescue signings).
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
        rescue_plan_fingerprint = (
            f"roster-floor-rescue:{rescue.rescue_fingerprint}"
        )
        return CPUFreeAgencyExecutionStepResult(
            version=CPU_FREE_AGENCY_EXECUTION_VERSION,
            status="committed_roster_floor_rescue",
            plan_fingerprint=rescue_plan_fingerprint,
            board_fingerprint=rescue_plan_fingerprint,
            market_fingerprint=f"roster-floor-rescue:{rescue.rescue_fingerprint}",
            signing=signed,
            message=(
                f"Roster-floor rescue: {signed.player_name} signed with "
                f"{signed.team_abbreviation} for ${signed.annual_salary:,.0f} per year."
            ),
        )
    eligible_teams = tuple(row[0] for row in sustainable_deficits)
    plan = build_cpu_free_agency_execution_plan(
        state,
        controlled_teams=controlled,
        eligible_teams=eligible_teams,
        max_targets_per_team=max_targets_per_team,
    )
    if not plan.opportunities:
        completion = build_cpu_sustainable_roster_completion_opportunity(
            state,
            controlled_teams=controlled,
        )
        if completion is not None:
            signed = _commit_cpu_sustainable_roster_completion_durably(
                completion,
                recovery_directory=recovery_directory,
                _checkpoint=checkpoint,
                _checkpoint_hash=checkpoint_hash,
                _verify_bytes_only=_verify_bytes_only,
                _verified_checkpoint_sink=_verified_checkpoint_sink,
            )
            completion_plan_fingerprint = (
                "sustainable-roster-completion:"
                + completion.completion_fingerprint
            )
            return CPUFreeAgencyExecutionStepResult(
                version=CPU_FREE_AGENCY_EXECUTION_VERSION,
                status="committed_sustainable_roster_completion",
                plan_fingerprint=completion_plan_fingerprint,
                board_fingerprint=plan.board_fingerprint,
                market_fingerprint=completion_plan_fingerprint,
                signing=signed,
                message=(
                    f"Sustainable roster completion: {signed.player_name} "
                    f"signed with {signed.team_abbreviation} for "
                    f"${signed.annual_salary:,.0f} per year through an "
                    "existing legal, player-accepted Free Agency route."
                ),
            )

        return CPUFreeAgencyExecutionStepResult(
            version=CPU_FREE_AGENCY_EXECUTION_VERSION,
            status="no_legal_player_accepted_sustainable_roster_completion",
            plan_fingerprint=plan.plan_fingerprint,
            board_fingerprint=plan.board_fingerprint,
            market_fingerprint=None,
            signing=None,
            message=(
                "CPU teams remain below the V2 sustainable roster target. "
                "The ordinary market has no accepted winner, and a full "
                "free-agent depth scan found no additional contract that both "
                "passes the existing financial/CBA gate and is accepted by "
                "the player. No emergency market-clearance or synthetic path "
                "was used."
            ),
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



# FRANCHISE_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_V1
CPU_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_VERSION = (
    "franchise-next-season-roster-floor-bridge-v1-2026-09-16"
)


def execute_cpu_roster_floor_bridge_durably(
    *,
    max_signings: int = 60,
    recovery_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Fill only under-minimum CPU rosters before the season-boundary validator.

    This is deliberately narrower than a normal CPU Free Agency round. It never
    reopens the general market, never touches a user-controlled team, and uses
    the already-certified roster-floor rescue offer/decision/financial gates.
    Every rescue signing is committed atomically through the existing durable
    Free Agency transaction path, then the checkpoint is reloaded before the
    next deficit is evaluated.
    """
    if max_signings < 1 or max_signings > 60:
        raise CPUFreeAgencyExecutionError(
            "max_signings must be between 1 and 60 for the season-boundary roster-floor bridge."
        )

    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise CPUFreeAgencyExecutionError(
            "The durable franchise checkpoint is unavailable for the season-boundary roster-floor bridge."
        )
    state = checkpoint.simulation_state
    if _phase(state) != "offseason":
        raise CPUFreeAgencyExecutionError(
            "The season-boundary roster-floor bridge can run only during the actual offseason."
        )

    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    floor = _minimum_game_player_floor(state)
    before = _cpu_roster_floor_deficits(state, controlled)
    committed: list[CPUFreeAgencyLiveSigningResult] = []

    while True:
        controlled = controlled_teams_from_durable_checkpoint(checkpoint)
        deficits = _cpu_roster_floor_deficits(state, controlled)
        if not deficits:
            break
        if len(committed) >= max_signings:
            raise CPUFreeAgencyExecutionError(
                "The season-boundary roster-floor bridge reached its bounded signing limit "
                f"with unresolved CPU deficits: {deficits}."
            )

        opportunity = build_cpu_roster_floor_rescue_opportunity(
            state,
            controlled_teams=controlled,
        )
        if opportunity is None:
            raise CPUFreeAgencyExecutionError(
                "No legal player-accepted minimum/counter rescue could satisfy the remaining "
                f"CPU roster-floor deficit(s): {deficits}."
            )

        signing = _commit_cpu_roster_floor_rescue_durably(
            opportunity,
            recovery_directory=recovery_directory,
        )
        committed.append(signing)

        checkpoint = load_franchise_checkpoint(allow_backup=False)
        if checkpoint is None:
            raise CPUFreeAgencyExecutionError(
                "The durable checkpoint could not be reloaded after a roster-floor rescue signing."
            )
        state = checkpoint.simulation_state
        if _phase(state) != "offseason":
            raise CPUFreeAgencyExecutionError(
                "A roster-floor rescue unexpectedly changed the franchise phase."
            )

    all_counts = {
        _team(team): len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        for team, team_state in (getattr(state, "teams", {}) or {}).items()
        if _team(team)
    }
    unresolved_all = tuple(
        sorted(
            (team, count, floor - count)
            for team, count in all_counts.items()
            if count < floor
        )
    )

    return {
        "version": CPU_NEXT_SEASON_ROSTER_FLOOR_BRIDGE_VERSION,
        "minimum_game_players": floor,
        "cpu_deficits_before": before,
        "committed_signing_count": len(committed),
        "signings": tuple(
            (
                item.player_id,
                item.player_name,
                item.team_abbreviation,
                float(item.annual_salary),
            )
            for item in committed
        ),
        "unresolved_all_team_deficits": unresolved_all,
    }


# FRANCHISE_POST_RETIREMENT_ROSTER_FLOOR_IN_MEMORY_BRIDGE_V2
CPU_POST_RETIREMENT_ROSTER_FLOOR_BRIDGE_VERSION = (
    "franchise-post-retirement-roster-floor-bridge-v2-2026-09-16"
)



# FRANCHISE_POST_RETIREMENT_MARKET_CLEARANCE_V3
CPU_POST_RETIREMENT_MARKET_CLEARANCE_VERSION = (
    "franchise-post-retirement-market-clearance-v3-2026-09-16"
)


def _build_cpu_roster_compliance_market_clearance_v3(
    state: Any,
    *,
    team_abbreviation: str,
) -> tuple[Any, dict[str, Any]] | None:
    """Find one legal replacement-level minimum signing for a CPU floor deficit.

    This path is deliberately narrower than normal Free Agency:
    - the caller has already proven the CPU team is below minimum_game_players;
    - every normal player-accepted minimum / bounded-counter route has failed;
    - only a one-year fully guaranteed applicable minimum is considered;
    - structural/CBA/financial gates must still PASS;
    - the candidate must be replacement-level by rating/market criteria.

    The player-decision model is still evaluated for ranking and diagnostics,
    but the final employment decision is treated as a roster-lock market-
    clearing acceptance for the lowest-demand eligible replacement player.
    """
    team = _team(team_abbreviation)
    free_ids = sorted(
        {
            _clean(value)
            for value in (getattr(state, "free_agent_player_ids", ()) or ())
            if _clean(value)
        }
    )
    if not team or not free_ids:
        return None

    candidates: list[tuple[tuple[Any, ...], Any, dict[str, Any]]] = []
    players = getattr(state, "players", {}) or {}

    for player_id in free_ids:
        player = players.get(player_id)
        if player is None:
            continue

        service, _ = resolve_years_of_service_for_state(
            state,
            player_id,
        )
        minimum = minimum_salary_floor_for_state(
            state,
            years_of_service=service,
            contract_years=1,
        )
        try:
            minimum_value = float(minimum)
        except (TypeError, ValueError):
            continue
        if minimum_value <= 0.0:
            continue

        offer = FreeAgencyOffer(
            player_id=player_id,
            team_abbreviation=team,
            annual_salary=round(minimum_value, 2),
            years=1,
            guaranteed=True,
            option_type="",
        )
        try:
            preview = build_rights_exception_free_agency_preview(
                state,
                offer,
                max_roster_size=18,
            )
        except Exception:
            continue
        if (
            _clean(getattr(preview, "status", "")).lower() != "pass"
            or not bool(getattr(preview, "can_commit", False))
        ):
            continue

        try:
            decision = evaluate_free_agent_offer_decision(state, preview)
        except Exception:
            decision = None

        overall = 0.0
        try:
            overall = float(getattr(player, "overall_rating", 0.0) or 0.0)
        except (TypeError, ValueError):
            overall = 0.0

        market_reference = minimum_value
        utility = 0.0
        threshold = 100.0
        if decision is not None:
            try:
                market_reference = float(
                    getattr(decision, "market_salary_reference", minimum_value)
                    or minimum_value
                )
            except (TypeError, ValueError):
                market_reference = minimum_value
            try:
                utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
            except (TypeError, ValueError):
                utility = 0.0
            try:
                threshold = float(
                    getattr(decision, "acceptance_threshold", 100.0) or 100.0
                )
            except (TypeError, ValueError):
                threshold = 100.0

        market_ratio = market_reference / max(minimum_value, 1.0)
        utility_gap = max(0.0, threshold - utility)

        # Replacement-level guardrail. Tier 1 captures clear minimum-market
        # players. Tier 2 allows a slightly stronger fringe player only when
        # his market reference and decision gap are still modest.
        tier = None
        if overall <= 76.0 or market_ratio <= 1.75:
            tier = 1
        elif overall <= 79.0 and market_ratio <= 2.50 and utility_gap <= 30.0:
            tier = 2
        if tier is None:
            continue

        meta = {
            "version": CPU_POST_RETIREMENT_MARKET_CLEARANCE_VERSION,
            "team": team,
            "player_id": player_id,
            "player_name": _clean(getattr(player, "player_name", "")) or player_id,
            "overall": round(overall, 3),
            "minimum_salary": round(minimum_value, 2),
            "market_reference": round(market_reference, 2),
            "market_ratio": round(market_ratio, 4),
            "utility_score": round(utility, 3),
            "acceptance_threshold": round(threshold, 3),
            "utility_gap": round(utility_gap, 3),
            "replacement_tier": tier,
            "offer_path": "post_retirement_roster_compliance_market_clearance",
        }
        rank = (
            tier,
            market_ratio,
            utility_gap,
            overall,
            player_id,
        )
        candidates.append((rank, preview, meta))

    if not candidates:
        return None

    candidates.sort(key=lambda row: row[0])
    _, preview, meta = candidates[0]
    return preview, meta


# FRANCHISE_SYNTHETIC_EMERGENCY_REPLACEMENT_V4
CPU_SYNTHETIC_EMERGENCY_REPLACEMENT_VERSION = (
    "franchise-synthetic-emergency-replacement-v4-2026-09-16"
)


def _add_synthetic_emergency_replacement_v4(
    state: Any,
    *,
    team_abbreviation: str,
) -> dict[str, Any]:
    """Add one simulation-only emergency player to an underfilled CPU roster.

    This is the final roster-compliance fallback after:
      1) normal player-accepted Free Agency rescue; and
      2) replacement-level legal minimum market clearance.

    The base simulator already models synthetic emergency replacements at state
    creation. This helper reuses the same state semantics at a season boundary.
    The player:
      - is synthetic;
      - is non-tradable through the existing contract bridge;
      - has a `simulation_replacement` zero-salary contract;
      - does not receive career development;
      - is removed automatically at the following season boundary.
    """
    from simulation_league_state_v1 import (
        ContractState,
        InjuryState,
        PlayerSeasonTotals,
        SimulationPlayerState,
    )
    from simulation_injury_fatigue_v1 import ensure_injury_fatigue_state

    team = _team(team_abbreviation)
    if team not in (getattr(state, "teams", {}) or {}):
        raise CPUFreeAgencyExecutionError(
            f"Emergency replacement team {team!r} does not exist."
        )

    season = _season(state)
    season_start = _clean(season).split("-", 1)[0] or "season"
    prefix = f"SIM_REPL_{team}_{season_start}_"

    existing_ids = set(getattr(state, "players", {}) or {})
    sequence = 1
    while f"{prefix}{sequence:02d}" in existing_ids:
        sequence += 1
    player_id = f"{prefix}{sequence:02d}"

    player = SimulationPlayerState(
        player_id=player_id,
        player_name=f"{team} Emergency Replacement {sequence}",
        team_abbreviation=team,
        roster_status="emergency_replacement",
        overall_rating=66.0,
        position="UNK",
        synthetic=True,
        rating_source="replacement",
        two_way=False,
        contract=ContractState(
            status="simulation_replacement",
            salary=0.0,
            years_remaining=0,
            option_type="",
            guaranteed=False,
        ),
        age=None,
        potential_rating=66.0,
        future_outlook_rating=66.0,
        development_direction="Stable",
        profile_reliability=0.0,
        skill_ratings={},
        stat_factors={},
        baseline_per_36={},
        development_history=[],
    )
    setattr(
        player,
        "emergency_replacement_version_v4",
        CPU_SYNTHETIC_EMERGENCY_REPLACEMENT_VERSION,
    )
    setattr(player, "emergency_replacement_season_v4", season)
    setattr(player, "emergency_replacement_reason_v4", "cpu_roster_floor")

    state.players[player_id] = player

    team_state = state.teams[team]
    roster = list(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
    if player_id not in roster:
        roster.append(player_id)
    team_state.roster_player_ids = tuple(roster)

    active = list(tuple(getattr(team_state, "active_player_ids", ()) or ()))
    if player_id not in active:
        active.append(player_id)
    team_state.active_player_ids = tuple(active)

    state.injuries[player_id] = InjuryState(player_id=player_id)
    state.player_season_totals[player_id] = PlayerSeasonTotals(
        player_id=player_id
    )

    # Never expose a synthetic emergency replacement as a normal FA.
    state.free_agent_player_ids = tuple(
        value
        for value in (getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(value) != player_id
    )

    # Keep the optional medical-profile map exactly aligned with players.
    ensure_injury_fatigue_state(state)

    return {
        "version": CPU_SYNTHETIC_EMERGENCY_REPLACEMENT_VERSION,
        "team": team,
        "player_id": player_id,
        "player_name": player.player_name,
        "overall": 66.0,
        "contract_status": "simulation_replacement",
        "salary": 0.0,
    }

def execute_cpu_roster_floor_bridge_in_memory_v2(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    max_signings: int = 60,
) -> tuple[Any, dict[str, Any]]:
    """Repair post-retirement CPU roster deficits on the transition copy.

    The career-lifecycle adapter can remove retiring players after the base
    season transition. This function runs on that *in-memory transition copy*
    before schedule installation and before the durable season-boundary commit.

    It uses the existing roster-floor rescue offer builder, minimum/CBA gate,
    and player-decision model. The only special handling is temporary OFFSEASON
    phase semantics while signings are evaluated, because the copy has already
    advanced to PRESEASON but cannot legally validate there until its floor
    deficits are repaired.
    """
    if max_signings < 1 or max_signings > 60:
        raise CPUFreeAgencyExecutionError(
            "max_signings must be between 1 and 60 for the post-retirement bridge."
        )

    from simulation_league_state_v1 import (
        LeaguePhase,
        validate_simulation_league_state,
    )
    from simulation_season_transition_v1 import refresh_team_rotations

    original_phase = getattr(state, "phase", None)
    working = copy.deepcopy(state)
    controlled = tuple(sorted({_team(value) for value in controlled_teams if _team(value)}))
    floor = _minimum_game_player_floor(working)
    committed: list[tuple[str, str, str, float]] = []
    market_clearance_signings: list[dict[str, Any]] = []
    synthetic_emergency_replacements: list[dict[str, Any]] = []

    # Free Agency structural checks and the certified financial gate require
    # actual offseason semantics. This is a private transition copy only.
    working.phase = LeaguePhase.OFFSEASON

    while True:
        deficits = _cpu_roster_floor_deficits(working, controlled)
        if not deficits:
            break
        if len(committed) >= max_signings:
            raise CPUFreeAgencyExecutionError(
                "Post-retirement roster repair hit its bounded signing limit "
                f"with unresolved CPU deficits: {deficits}."
            )

        opportunity = build_cpu_roster_floor_rescue_opportunity(
            working,
            controlled_teams=controlled,
        )
        if opportunity is None:
            deficit_team = deficits[0][0]
            clearance = _build_cpu_roster_compliance_market_clearance_v3(
                working,
                team_abbreviation=deficit_team,
            )
            if clearance is None:
                replacement_meta = _add_synthetic_emergency_replacement_v4(
                    working,
                    team_abbreviation=deficit_team,
                )
                synthetic_emergency_replacements.append(
                    dict(replacement_meta)
                )
                continue

            clearance_preview, clearance_meta = clearance
            working, clearance_commit = commit_free_agency_preview(
                working,
                clearance_preview,
                financial_gate=evaluate_rights_exception_financial_gate,
                max_roster_size=18,
            )
            committed.append(
                (
                    _clean(getattr(clearance_commit, "player_id", "")),
                    _clean(getattr(clearance_commit, "player_name", "")),
                    _team(getattr(clearance_commit, "team_abbreviation", "")),
                    float(
                        getattr(clearance_preview.offer, "annual_salary", 0.0)
                        or 0.0
                    ),
                )
            )
            market_clearance_signings.append(dict(clearance_meta))
            continue

        # Rescue discovery deliberately defers the expensive candidate
        # fingerprint. Rebuild the selected offer once with the full fingerprint
        # before the pure in-memory commit.
        preview = build_rights_exception_free_agency_preview(
            working,
            opportunity.preview.offer,
            max_roster_size=18,
        )
        if (
            _clean(getattr(preview, "status", "")).lower() != "pass"
            or not bool(getattr(preview, "can_commit", False))
        ):
            raise CPUFreeAgencyExecutionError(
                "The selected post-retirement roster rescue no longer passes "
                "the certified Free Agency transaction gate."
            )

        decision = evaluate_free_agent_offer_decision(
            working,
            preview,
        )
        if not bool(getattr(decision, "accepted", False)):
            raise CPUFreeAgencyExecutionError(
                "The selected post-retirement roster rescue is no longer "
                "accepted by the free agent."
            )

        working, commit = commit_free_agency_preview(
            working,
            preview,
            financial_gate=evaluate_rights_exception_financial_gate,
            max_roster_size=18,
        )
        committed.append(
            (
                _clean(getattr(commit, "player_id", "")),
                _clean(getattr(commit, "player_name", "")),
                _team(getattr(commit, "team_abbreviation", "")),
                float(getattr(preview.offer, "annual_salary", 0.0) or 0.0),
            )
        )

    # A controlled roster is never auto-filled. Report it explicitly rather
    # than falling back to a generic all_team_rosters_playable failure.
    all_deficits = []
    for team, team_state in sorted((getattr(working, "teams", {}) or {}).items()):
        count = len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        if count < floor:
            all_deficits.append((_team(team), count, floor - count))
    if all_deficits:
        raise CPUFreeAgencyExecutionError(
            "Post-retirement roster repair left a user-controlled or otherwise "
            f"unrepairable team below the {floor}-player floor: {all_deficits}."
        )

    working.phase = original_phase
    refresh_team_rotations(working)
    validate_simulation_league_state(working)

    return working, {
        "version": CPU_POST_RETIREMENT_ROSTER_FLOOR_BRIDGE_VERSION,
        "minimum_game_players": floor,
        "committed_signing_count": len(committed),
        "signings": tuple(committed),
        "market_clearance_signing_count": len(market_clearance_signings),
        "market_clearance_signings": tuple(
            dict(row) for row in market_clearance_signings
        ),
        "synthetic_emergency_replacement_count": len(
            synthetic_emergency_replacements
        ),
        "synthetic_emergency_replacements": tuple(
            dict(row) for row in synthetic_emergency_replacements
        ),
    }



def _commit_execution_plan_top_opportunity_durably(
    plan: CPUFreeAgencyExecutionPlan,
    *,
    checkpoint: Any,
    checkpoint_hash: str,
    recovery_directory: str | Path | None,
    verify_bytes_only: bool,
    verified_checkpoint_sink: list[Any],
    defer_durable_write: bool = False,
) -> CPUFreeAgencyLiveSigningResult:
    """Commit the top opportunity from a plan built against current state."""
    if not plan.opportunities:
        raise CPUFreeAgencyExecutionError(
            "Cannot commit a CPU execution plan without an accepted opportunity."
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
            "CPU execution opportunity could not be reconciled to its current market."
        )
    previews = _previews_for_player(plan.board, opportunity.player_id)
    return commit_cpu_competing_market_winner_live(
        previews,
        player_market.market,
        expected_board_fingerprint=plan.board_fingerprint,
        recovery_directory=recovery_directory,
        _checkpoint=checkpoint,
        _checkpoint_hash=checkpoint_hash,
        _verify_bytes_only=verify_bytes_only,
        _verified_checkpoint_sink=verified_checkpoint_sink,
        _defer_durable_write=defer_durable_write,
    )


def _revalidate_queued_player_market(
    plan: CPUFreeAgencyExecutionPlan,
    *,
    player_id: str,
    state: Any,
    eligible_teams: Iterable[str],
    changed_teams: Iterable[str],
) -> tuple[tuple[Any, ...], FreeAgencyCompetingMarketResult] | None:
    """Rebuild only still-applicable offers for one queued player.

    A full plan is authoritative when built. After another signing, offers from
    teams whose own roster/cap changed are intentionally discarded until the
    next full-plan refresh. Offers from unchanged teams keep their exact salary
    and term, but are rebuilt through the CURRENT CBA/financial preview and
    CURRENT player-decision market before they can be committed.

    This removes stale-state risk without regenerating thousands of unrelated
    team/player bids after every signing.
    """
    player_id = _clean(player_id)
    if not player_id:
        return None

    current_free_agents = {
        _clean(value)
        for value in (getattr(state, "free_agent_player_ids", ()) or ())
        if _clean(value)
    }
    if player_id not in current_free_agents:
        return None

    eligible = {_team(value) for value in eligible_teams if _team(value)}
    changed = {_team(value) for value in changed_teams if _team(value)}
    if not eligible:
        return None

    source_fingerprint = free_agency_state_fingerprint(state)
    rebuilt: list[Any] = []
    for generated in plan.board.offers:
        if generated.player_id != player_id:
            continue
        team = _team(generated.team_abbreviation)
        if team not in eligible or team in changed:
            continue
        original_preview = generated.preview
        offer = getattr(original_preview, "offer", None)
        if offer is None:
            continue
        try:
            preview = build_rights_exception_free_agency_preview(
                state,
                offer,
                _source_fingerprint=source_fingerprint,
                _defer_candidate_fingerprint=True,
            )
        except Exception:
            continue
        rebuilt.append(preview)

    if not rebuilt:
        return None

    current_market = evaluate_competing_offer_market(state, rebuilt)
    if not current_market.has_winner:
        return None
    return tuple(rebuilt), current_market



def execute_cpu_free_agency_round_durably(
    *,
    max_signings: int = DEFAULT_CPU_FREE_AGENCY_MAX_SIGNINGS_PER_ROUND,
    max_targets_per_team: int = 5,
    recovery_directory: str | Path | None = None,
) -> CPUFreeAgencyRoundResult:
    """Run a bounded CPU free-agency round with bounded full-market refreshes.

    The full CPU offer board used to be regenerated after every ordinary
    signing. Profiling showed that behavior dominated deep-season offseason
    runtime. This version preserves the existing durable legality path while
    refreshing the complete market every five ordinary signings.

    Between full refreshes:
      * queued player order comes from the last complete current-state plan;
      * any team that already signed in the batch has all of its stale queued
        offers discarded;
      * each selected player's remaining offers are rebuilt through the CURRENT
        CBA/financial preview and CURRENT player-decision market;
      * the winning offer is still fully fingerprinted and revalidated again
        by the existing durable commit stack.

    Emergency floor rescue behavior is unchanged. Once the complete ordinary
    market produces no opportunities, sustainable completion may commit up to
    five exact current-state candidates before the complete ordinary market is
    checked again. Every completion candidate is still rebuilt, accepted,
    fingerprinted, and durably revalidated against the current checkpoint.
    """
    if max_signings < 1 or max_signings > 15:
        raise CPUFreeAgencyExecutionError(
            "max_signings must be between 1 and 15."
        )

    from simulation_franchise_checkpoint_v1 import (
        DEFAULT_CHECKPOINT_PATH,
        load_franchise_checkpoint,
        save_franchise_checkpoint,
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

    # The on-disk checkpoint remains fixed while up to five fully validated
    # signings are applied to the in-memory checkpoint graph. Each bounded batch
    # is then written atomically and semantically reloaded before execution
    # continues. This preserves stale-write detection and regular recovery
    # boundaries while avoiding one mature checkpoint serialization per signing.
    durable_checkpoint = checkpoint
    durable_hash = before
    checkpoint_hash = durable_hash
    pending_batch_start = 0
    durable_batch_number = 0

    batch_plan: CPUFreeAgencyExecutionPlan | None = None
    queued_opportunities: list[CPUFreeAgencyExecutionOpportunity] = []
    changed_teams: set[str] = set()
    ordinary_since_refresh = CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL
    stale_candidate_skips = 0
    completion_market_exhausted = False
    completion_signings_since_market_refresh = 0

    def flush_pending_durable_batch(*, boundary: str) -> None:
        nonlocal checkpoint
        nonlocal durable_checkpoint
        nonlocal durable_hash
        nonlocal checkpoint_hash
        nonlocal pending_batch_start
        nonlocal durable_batch_number

        if len(committed) <= pending_batch_start:
            return

        expected_sim = free_agency_durable_state_fingerprint(
            checkpoint.simulation_state
        )
        expected_trade = trade_state_fingerprint(checkpoint.trade_state)

        recovery_root = (
            Path(recovery_directory)
            if recovery_directory is not None
            else checkpoint_path.parent / "cpu_free_agency_recovery"
        )
        recovery_root.mkdir(parents=True, exist_ok=True)
        durable_batch_number += 1
        batch_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        first_tx = committed[pending_batch_start].transaction_id
        last_tx = committed[-1].transaction_id
        recovery_path = recovery_root / (
            f"pre_cpu_round_batch_{durable_batch_number:02d}_"
            f"{first_tx}_to_{last_tx}_{batch_stamp}_{checkpoint_path.name}"
        )
        shutil.copy2(checkpoint_path, recovery_path)

        flush_reason = (
            f"free-agency-cpu-round-batch-{durable_batch_number:02d}-"
            f"{boundary}-{first_tx}-to-{last_tx}"
        )
        # The batch's stale-write evidence must refer to the exact same
        # checkpoint path that the writer will verify and replace. Protected
        # soak isolation rewrites checkpoint paths dynamically, so do not rely
        # on the save function's Python-bound default path here.
        observed_hash_before_flush = _sha256(checkpoint_path)
        if observed_hash_before_flush != durable_hash:
            raise CPUFreeAgencyExecutionError(
                "CPU Free Agency durable batch checkpoint changed before flush "
                f"at {checkpoint_path}. expected={durable_hash} "
                f"observed={observed_hash_before_flush}"
            )

        verified_file_sha256_sink: list[str] = []
        try:
            verified = save_franchise_checkpoint(
                checkpoint.simulation_state,
                checkpoint.trade_state,
                preferences=_preference_dict(checkpoint),
                reason=flush_reason,
                path=checkpoint_path,
                copy_payload=False,
                _return_verified=True,
                _existing_checkpoint=durable_checkpoint,
                _expected_existing_sha256=durable_hash,
                # Intermediate FA batches already hold the exact object graph
                # that is being encoded. Verify the written gzip payload
                # byte-for-byte here and reserve the full semantic decode for
                # the mandatory round-end reload below.
                _verify_encoded_bytes_only=True,
                _verified_file_sha256_sink=verified_file_sha256_sink,
            )
            # Byte verification proves that the durable file contains the exact
            # encoded form of this in-memory checkpoint. Recomputing whole-state
            # fingerprints against the same object graph adds no new evidence.
            observed_sim = expected_sim
            observed_trade = expected_trade
            if observed_sim != expected_sim or observed_trade != expected_trade:
                raise CPUFreeAgencyExecutionError(
                    "CPU Free Agency durable batch byte verification did not match "
                    "the fully validated in-memory batch state."
                )
        except Exception as exc:
            shutil.copy2(recovery_path, checkpoint_path)
            restored = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)
            if restored is None:
                raise CPUFreeAgencyExecutionError(
                    "CPU Free Agency batch flush failed and recovery could not "
                    "be loaded."
                ) from exc
            restored_sim = free_agency_durable_state_fingerprint(
                restored.simulation_state
            )
            restored_trade = trade_state_fingerprint(restored.trade_state)
            durable_sim = free_agency_durable_state_fingerprint(
                durable_checkpoint.simulation_state
            )
            durable_trade = trade_state_fingerprint(
                durable_checkpoint.trade_state
            )
            if restored_sim != durable_sim or restored_trade != durable_trade:
                raise CPUFreeAgencyExecutionError(
                    "CPU Free Agency batch flush failed and automatic recovery "
                    "could not be verified."
                ) from exc
            raise CPUFreeAgencyExecutionError(
                "CPU Free Agency durable batch flush failed. The prior durable "
                f"checkpoint was restored: {exc}"
            ) from exc

        final_hash = (
            verified_file_sha256_sink[-1]
            if verified_file_sha256_sink
            else _sha256(checkpoint_path)
        )
        durable_checkpoint = verified
        durable_hash = final_hash
        checkpoint_hash = final_hash
        checkpoint = verified

        for index in range(pending_batch_start, len(committed)):
            committed[index] = replace(
                committed[index],
                checkpoint_hash_after=final_hash,
                checkpoint_saved_at_utc=_clean(
                    getattr(verified, "saved_at_utc", "")
                ),
                checkpoint_reason=flush_reason,
                recovery_path=str(recovery_path),
            )
        pending_batch_start = len(committed)

    while len(committed) < max_signings:
        state = checkpoint.simulation_state
        controlled = controlled_teams_from_durable_checkpoint(checkpoint)
        sustainable_deficits = cpu_sustainable_roster_deficits(
            state,
            controlled,
        )
        if not sustainable_deficits:
            stop_reason = "all_cpu_teams_meet_sustainable_roster_target"
            break

        # Preserve emergency playability priority exactly.
        rescue = build_cpu_roster_floor_rescue_opportunity(
            state,
            controlled_teams=controlled,
        )
        if rescue is not None:
            verified_sink: list[Any] = []
            try:
                signing = _commit_cpu_roster_floor_rescue_durably(
                    rescue,
                    recovery_directory=recovery_directory,
                    _checkpoint=checkpoint,
                    _checkpoint_hash=checkpoint_hash,
                    _verify_bytes_only=True,
                    _verified_checkpoint_sink=verified_sink,
                    _defer_durable_write=True,
                )
            except Exception as exc:
                if committed:
                    partial_error = f"{type(exc).__name__}: {exc}"
                    stop_reason = partial_error
                    break
                raise
            if not verified_sink:
                raise CPUFreeAgencyExecutionError(
                    "CPU roster-floor rescue did not return its byte-verified checkpoint."
                )
            committed.append(signing)
            checkpoint = verified_sink[-1]
            checkpoint_hash = signing.checkpoint_hash_after
            if (
                len(committed) - pending_batch_start
                >= CPU_FREE_AGENCY_DURABLE_BATCH_SIZE
            ):
                flush_pending_durable_batch(boundary="roster-floor-rescue")
            batch_plan = None
            queued_opportunities.clear()
            changed_teams.clear()
            ordinary_since_refresh = CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL
            stale_candidate_skips = 0
            completion_market_exhausted = False
            completion_signings_since_market_refresh = 0
            continue

        # Refresh the complete market periodically or when the prior queue is
        # exhausted. This is the only step that evaluates every target/player.
        if (
            batch_plan is None
            or not queued_opportunities
            or ordinary_since_refresh >= CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL
        ):
            should_refresh_complete_market = bool(
                not completion_market_exhausted
                or completion_signings_since_market_refresh
                >= CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_MARKET_REFRESH_INTERVAL
            )
            if should_refresh_complete_market:
                eligible_teams = tuple(row[0] for row in sustainable_deficits)
                batch_plan = build_cpu_free_agency_execution_plan(
                    state,
                    controlled_teams=controlled,
                    eligible_teams=eligible_teams,
                    max_targets_per_team=max_targets_per_team,
                )
                queued_opportunities = list(batch_plan.opportunities)
                changed_teams.clear()
                ordinary_since_refresh = 0
                stale_candidate_skips = 0
                completion_market_exhausted = not queued_opportunities
                completion_signings_since_market_refresh = 0

            if not queued_opportunities:
                completion = build_cpu_sustainable_roster_completion_opportunity(
                    state,
                    controlled_teams=controlled,
                )
                if completion is None:
                    if not should_refresh_complete_market:
                        # A bounded completion batch exhausted its exact
                        # candidates early. Recheck the complete ordinary
                        # market before declaring that no legal path remains.
                        completion_market_exhausted = False
                        completion_signings_since_market_refresh = 0
                        continue
                    stop_reason = (
                        "no_legal_player_accepted_sustainable_roster_completion"
                    )
                    break

                verified_sink = []
                try:
                    signing = _commit_cpu_sustainable_roster_completion_durably(
                        completion,
                        recovery_directory=recovery_directory,
                        _checkpoint=checkpoint,
                        _checkpoint_hash=checkpoint_hash,
                        _verify_bytes_only=True,
                        _verified_checkpoint_sink=verified_sink,
                        _defer_durable_write=True,
                    )
                except Exception as exc:
                    if committed:
                        partial_error = f"{type(exc).__name__}: {exc}"
                        stop_reason = partial_error
                        break
                    raise
                if not verified_sink:
                    raise CPUFreeAgencyExecutionError(
                        "Sustainable roster completion did not return its byte-verified checkpoint."
                    )
                committed.append(signing)
                checkpoint = verified_sink[-1]
                checkpoint_hash = signing.checkpoint_hash_after
                if (
                    len(committed) - pending_batch_start
                    >= CPU_FREE_AGENCY_DURABLE_BATCH_SIZE
                ):
                    flush_pending_durable_batch(
                        boundary="sustainable-completion"
                    )
                batch_plan = None
                queued_opportunities.clear()
                changed_teams.clear()
                ordinary_since_refresh = CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL
                completion_market_exhausted = True
                completion_signings_since_market_refresh += 1
                continue

        opportunity = queued_opportunities.pop(0)

        # The first opportunity after a full refresh is already built against
        # exact current state. Subsequent ones use narrow current-state market
        # revalidation rather than a new league-wide offer board.
        if ordinary_since_refresh == 0 and not changed_teams:
            verified_sink = []
            try:
                signing = _commit_execution_plan_top_opportunity_durably(
                    batch_plan,
                    checkpoint=checkpoint,
                    checkpoint_hash=checkpoint_hash,
                    recovery_directory=recovery_directory,
                    verify_bytes_only=True,
                    verified_checkpoint_sink=verified_sink,
                    defer_durable_write=True,
                )
            except Exception as exc:
                if committed:
                    partial_error = f"{type(exc).__name__}: {exc}"
                    stop_reason = partial_error
                    break
                raise
        else:
            state = checkpoint.simulation_state
            controlled = controlled_teams_from_durable_checkpoint(checkpoint)
            current_deficits = cpu_sustainable_roster_deficits(
                state,
                controlled,
            )
            eligible_teams = tuple(row[0] for row in current_deficits)
            revalidated = _revalidate_queued_player_market(
                batch_plan,
                player_id=opportunity.player_id,
                state=state,
                eligible_teams=eligible_teams,
                changed_teams=changed_teams,
            )
            if revalidated is None:
                stale_candidate_skips += 1
                if stale_candidate_skips >= CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL:
                    batch_plan = None
                    queued_opportunities.clear()
                    changed_teams.clear()
                    ordinary_since_refresh = CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL
                continue

            previews, current_market = revalidated
            verified_sink = []
            try:
                signing = commit_cpu_competing_market_winner_live(
                    previews,
                    current_market,
                    expected_board_fingerprint=batch_plan.board_fingerprint,
                    recovery_directory=recovery_directory,
                    _checkpoint=checkpoint,
                    _checkpoint_hash=checkpoint_hash,
                    _verify_bytes_only=True,
                    _verified_checkpoint_sink=verified_sink,
                    _defer_durable_write=True,
                )
            except Exception as exc:
                if committed:
                    partial_error = f"{type(exc).__name__}: {exc}"
                    stop_reason = partial_error
                    break
                raise

        if not verified_sink:
            raise CPUFreeAgencyExecutionError(
                "CPU Free Agency commit did not return its byte-verified checkpoint."
            )

        committed.append(signing)
        checkpoint = verified_sink[-1]
        checkpoint_hash = signing.checkpoint_hash_after
        if (
            len(committed) - pending_batch_start
            >= CPU_FREE_AGENCY_DURABLE_BATCH_SIZE
        ):
            flush_pending_durable_batch(boundary="ordinary-market")
        ordinary_since_refresh += 1
        stale_candidate_skips = 0
        completion_market_exhausted = False
        completion_signings_since_market_refresh = 0
        signed_team = _team(signing.team_abbreviation)
        if signed_team:
            changed_teams.add(signed_team)

        # Drop the signed player and any queued market whose original winner was
        # a team already changed in this refresh window. Those teams are rebuilt
        # from their new roster at the next complete refresh.
        queued_opportunities = [
            row
            for row in queued_opportunities
            if (
                row.player_id != signing.player_id
                and _team(row.winner_team_abbreviation) not in changed_teams
            )
        ]

    flush_pending_durable_batch(boundary="round-end")

    expected_sim = free_agency_durable_state_fingerprint(
        checkpoint.simulation_state
    )
    expected_trade = trade_state_fingerprint(checkpoint.trade_state)
    checkpoint = None
    try:
        verified_sink.clear()
    except NameError:
        pass
    gc.collect()

    semantic = load_franchise_checkpoint(path=checkpoint_path, allow_backup=False)
    if semantic is None:
        raise CPUFreeAgencyExecutionError(
            "The durable checkpoint could not be semantically reloaded after the CPU Free Agency round."
        )
    observed_sim = free_agency_durable_state_fingerprint(
        semantic.simulation_state
    )
    observed_trade = trade_state_fingerprint(semantic.trade_state)
    if observed_sim != expected_sim or observed_trade != expected_trade:
        raise CPUFreeAgencyExecutionError(
            "Final semantic checkpoint reload does not match the byte-verified CPU Free Agency round state."
        )

    return CPUFreeAgencyRoundResult(
        version=CPU_FREE_AGENCY_EXECUTION_VERSION,
        status=("committed" if committed else "no_action"),
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
        "board_rebuilt_after_each_signing": False,
        "bounded_market_refresh_version": CPU_FREE_AGENCY_BOUNDED_MARKET_REFRESH_VERSION,
        "full_plan_refresh_interval": CPU_FREE_AGENCY_FULL_PLAN_REFRESH_INTERVAL,
        "queued_offers_from_changed_teams_discarded": True,
        "queued_player_market_rebuilt_through_current_cba_gate": True,
        "queued_player_decision_market_recomputed": True,
        "winning_offer_full_preview_revalidated_before_commit": True,
        "deep_season_performance_version": CPU_FREE_AGENCY_DEEP_SEASON_PERFORMANCE_VERSION,
        "speculative_candidate_fingerprints_deferred": True,
        "round_carries_byte_verified_checkpoint": True,
        "round_reuses_verified_checkpoint_sha256": True,
        "durable_batch_version": CPU_FREE_AGENCY_DURABLE_BATCH_VERSION,
        "durable_batch_size": CPU_FREE_AGENCY_DURABLE_BATCH_SIZE,
        "round_deferred_signings_validate_before_batch_flush": True,
        "round_batch_flush_uses_atomic_checkpoint_save": True,
        "round_batch_flush_semantic_reload_required": True,
        "byte_verified_commit_skips_same_object_postsave_fingerprints": True,
        "durable_commit_reuses_verified_preview_candidate": True,
        "durable_commit_reuses_precomputed_state_fingerprint": True,
        "round_final_semantic_reload_required": True,
        "round_stops_when_roster_floor_complete": False,
        "round_stops_when_sustainable_roster_target_complete": True,
        "sustainable_roster_construction_version": CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_CONSTRUCTION_VERSION,
        "sustainable_roster_target": CPU_FREE_AGENCY_SUSTAINABLE_ROSTER_TARGET,
        "minimum_game_players_reserved_for_emergency_playability": True,
        "ordinary_market_restricted_to_under_target_cpu_teams": True,
        "sustainable_completion_version": CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_VERSION,
        "sustainable_completion_runs_only_after_ordinary_market_exhausts": True,
        "sustainable_completion_uses_bounded_market_rechecks": True,
        "sustainable_completion_market_refresh_interval": CPU_FREE_AGENCY_SUSTAINABLE_COMPLETION_MARKET_REFRESH_INTERVAL,
        "sustainable_completion_requires_under_target_cpu_team": True,
        "sustainable_completion_preserves_locked_financial_gate": True,
        "sustainable_completion_requires_player_acceptance": True,
        "sustainable_completion_uses_market_clearance_override": False,
        "sustainable_completion_uses_synthetic_players": False,
        "autonomous_background_execution": False,
        "cpu_only_markets": True,
        "user_offer_injection": False,
        "roster_floor_rescue_version": CPU_FREE_AGENCY_ROSTER_FLOOR_RESCUE_VERSION,
        "roster_floor_rescue_runs_only_after_standard_market_exhausts": False,
        "roster_floor_rescue_prioritized_before_standard_market": True,
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
