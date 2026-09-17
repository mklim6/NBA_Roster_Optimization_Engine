from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable, Iterable

from franchise_league_events_v1 import (
    _append_event,
    ensure_event_state,
    mark_event_read,
    resolve_event,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BIGGEST_NEED,
    GOAL_FUTURE_UPSIDE,
    GOAL_WIN_NOW,
    FranchiseTradeFinderProposal,
    build_team_trade_ai_profiles,
    build_trade_finder_search_context,
    generate_trade_finder_proposals,
)
# Keep these key names local so the non-UI regression suite does not
# need Streamlit installed merely to import the offer engine.
SESSION_PREVIEW_KEY = "franchise_embedded_trade_center_v2_preview"
LEDGER_VIEW_KEY = "franchise_live_asset_ledger_view_v1"
from franchise_trade_transaction_v1 import (
    FranchiseTradeTransactionError,
    commit_live_franchise_trade,
)

CPU_INCOMING_TRADE_OFFERS_VERSION = (
    "franchise-cpu-incoming-trade-offers-v6b-2026-09-17"
)
CPU_INCOMING_TRADE_OFFERS_PERFORMANCE_VERSION = (
    "franchise-cpu-incoming-trade-offers-v6b-perf-v6-0-1-2026-09-17"
)
STATE_ATTRIBUTE = "franchise_cpu_incoming_trade_offers_v1"

MIN_MEDIAN_GAMES = 12
TRADE_DEADLINE_MEDIAN_GAMES = 55
OFFER_COOLDOWN_DAYS = 7
OFFER_SCAN_INTERVAL_DAYS = 2
OFFER_LIFETIME_DAYS = 7
MAX_OFFERS_PER_SEASON = 12
MAX_CPU_TEAMS_SCANNED = 2


class CPUIncomingTradeOfferError(RuntimeError):
    """Raised when CPU incoming-offer generation cannot run safely."""


@dataclass(frozen=True)
class CPUIncomingTradeOfferTickResult:
    version: str
    state: Any
    ran: bool
    changed: bool
    created_offer: bool
    offer_id: str
    user_team: str
    cpu_team: str
    target_player_id: str
    target_player_name: str
    reason: str
    current_day: int
    median_games_played: float
    cpu_teams_scanned: int
    proposals_considered: int
    timing_breakdown: dict[str, float]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("state", None)
        return payload


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _season(state: Any) -> str:
    return _clean(
        getattr(
            getattr(state, "settings", None),
            "season_label",
            "",
        )
    )


def _median_games_played(state: Any) -> float:
    rows: list[int] = []
    for standing in (getattr(state, "standings", {}) or {}).values():
        gp = getattr(standing, "games_played", None)
        if gp is None:
            gp = int(getattr(standing, "wins", 0) or 0) + int(
                getattr(standing, "losses", 0) or 0
            )
        try:
            rows.append(max(0, int(gp)))
        except (TypeError, ValueError):
            continue
    return float(median(rows)) if rows else 0.0


def _offer_id(
    season: str,
    day: int,
    cpu_team: str,
    user_team: str,
    proposal_id: str,
) -> str:
    payload = (
        f"{season}|{day}|{cpu_team}|{user_team}|{proposal_id}"
    ).encode("utf-8")
    return "OFFER_" + hashlib.sha256(payload).hexdigest()[:18].upper()


def _ensure_offer_state(state: Any) -> dict[str, Any]:
    season = _season(state)
    payload = getattr(state, STATE_ATTRIBUTE, None)
    if not isinstance(payload, dict) or payload.get("season") != season:
        payload = {
            "version": CPU_INCOMING_TRADE_OFFERS_VERSION,
            "season": season,
            "last_offer_day": -10_000,
            "last_scan_day": -10_000,
            "scan_cursor": 0,
            "offers_created": 0,
            "offers": [],
            "history": [],
        }
        setattr(state, STATE_ATTRIBUTE, payload)

    payload.setdefault("version", CPU_INCOMING_TRADE_OFFERS_VERSION)
    payload.setdefault("season", season)
    payload.setdefault("last_offer_day", -10_000)
    payload.setdefault("last_scan_day", -10_000)
    payload.setdefault("scan_cursor", 0)
    payload.setdefault("offers_created", 0)
    payload.setdefault("offers", [])
    payload.setdefault("history", [])
    return payload


def _offer_by_id(
    state: Any,
    offer_id: str,
) -> dict[str, Any] | None:
    payload = _ensure_offer_state(state)
    for offer in payload["offers"]:
        if _clean(offer.get("offer_id")) == _clean(offer_id):
            return offer
    return None


def _event_for_offer(
    state: Any,
    offer_id: str,
) -> dict[str, Any] | None:
    events, _ = ensure_event_state(state)
    for event in events:
        metadata = event.get("metadata")
        if (
            isinstance(metadata, dict)
            and _clean(metadata.get("offer_id")) == _clean(offer_id)
        ):
            return event
    return None


def _expire_pending_offers(state: Any) -> int:
    payload = _ensure_offer_state(state)
    day = int(getattr(state, "current_day_index", 0) or 0)
    expired = 0

    for offer in payload["offers"]:
        if offer.get("status") != "pending":
            continue
        if day <= int(offer.get("expires_day", day) or day):
            continue

        offer["status"] = "expired"
        offer["resolved_day"] = day
        expired += 1

        event = _event_for_offer(state, offer["offer_id"])
        if event is not None:
            event["status"] = "expired"
            event["resolved_at_utc"] = datetime.now(
                timezone.utc
            ).isoformat()

        payload["history"].append(
            {
                "offer_id": offer["offer_id"],
                "day_index": day,
                "outcome": "expired",
                "cpu_team": offer["cpu_team"],
                "user_team": offer["user_team"],
                "target_player_name": offer["target_player_name"],
            }
        )

    return expired


def pending_cpu_trade_offers_v1(
    state: Any,
    *,
    user_team: str = "",
) -> list[dict[str, Any]]:
    _expire_pending_offers(state)
    resolved = _team(user_team)
    payload = _ensure_offer_state(state)
    return [
        offer
        for offer in payload["offers"]
        if offer.get("status") == "pending"
        and (
            not resolved
            or _team(offer.get("user_team")) == resolved
        )
    ]


def _player_name(state: Any, player_id: str) -> str:
    player = (getattr(state, "players", {}) or {}).get(str(player_id))
    return _clean(getattr(player, "player_name", "")) or str(player_id)


def _asset_name_maps(
    runtime: Any,
    state: Any,
    trade_state: Any,
) -> tuple[dict[str, str], dict[str, str]]:
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    player_names = {
        str(row.get("player_id")): (
            _clean(row.get("player_name"))
            or str(row.get("player_id"))
        )
        for row in ledger.player_rows
    }
    pick_names = {
        str(row.get("asset_id")): (
            _clean(row.get("display_name"))
            or str(row.get("asset_id"))
        )
        for row in ledger.draft_rows
    }
    return player_names, pick_names


def _side_names(
    player_ids: Iterable[str],
    pick_ids: Iterable[str],
    player_names: dict[str, str],
    pick_names: dict[str, str],
) -> list[str]:
    names = [
        player_names.get(str(pid), str(pid))
        for pid in player_ids
    ]
    names.extend(
        pick_names.get(str(aid), str(aid))
        for aid in pick_ids
    )
    return names


def _summary(
    cpu_team: str,
    user_team: str,
    cpu_sends: Iterable[str],
    user_sends: Iterable[str],
    expires_day: int,
) -> str:
    cpu_text = ", ".join(cpu_sends) or "no assets"
    user_text = ", ".join(user_sends) or "no assets"
    return (
        f"{cpu_team} offers {cpu_text} for {user_team}'s "
        f"{user_text}. Offer expires after league day {expires_day}."
    )


def _goal_for_profile(profile: Any) -> str:
    timeline = _clean(getattr(profile, "timeline", "")).lower()
    if timeline == "contender":
        return GOAL_WIN_NOW
    if timeline == "rebuild":
        return GOAL_FUTURE_UPSIDE
    return GOAL_BIGGEST_NEED


def _cpu_team_order(
    state: Any,
    runtime: Any,
    trade_state: Any,
    *,
    user_team: str,
    controlled_teams: Iterable[str],
    search_context: Any | None = None,
) -> list[tuple[float, str, Any]]:
    if search_context is None:
        ledger = build_live_asset_ledger(runtime, state, trade_state)
        profiles = build_team_trade_ai_profiles(state, ledger)
    else:
        profiles = search_context.profiles
    controlled = {_team(team) for team in controlled_teams if _team(team)}
    user = _team(user_team)

    rows: list[tuple[float, str, Any]] = []
    for team, profile in profiles.items():
        resolved = _team(team)
        if (
            not resolved
            or resolved == user
            or resolved in controlled
        ):
            continue

        needs = list(getattr(profile, "need_scores", {}).values())
        strongest_need = max(needs) if needs else 0.0
        timeline = _clean(getattr(profile, "timeline", "")).lower()
        timeline_bonus = (
            10.0
            if timeline == "contender"
            else 7.0
            if timeline == "retool"
            else 5.0
            if timeline == "rebuild"
            else 4.0
        )
        urgency = (
            float(strongest_need)
            + timeline_bonus
            + 4.0 * abs(float(getattr(profile, "win_pct", 0.5)) - 0.5)
        )
        rows.append((urgency, resolved, profile))

    rows.sort(key=lambda item: (-item[0], item[1]))
    return rows[:MAX_CPU_TEAMS_SCANNED]


def _proposal_is_reasonable_for_cpu(
    proposal: FranchiseTradeFinderProposal,
    *,
    user_roster: set[str],
) -> bool:
    if proposal.cpu_response not in {"accept", "counter"}:
        return False

    target = str(proposal.target_player_id)
    if not target or target not in user_roster:
        return False

    if not proposal.side_b_player_ids:
        return False

    # active_team is the CPU caller. Keep its own value delta close enough
    # to neutral that incoming offers do not become obvious CPU giveaways
    # or cartoonishly one-sided lowballs.
    cpu_delta = float(proposal.user_value_delta)
    if cpu_delta < -3.5 or cpu_delta > 6.0:
        return False

    return True


def _proposal_rank(
    proposal: FranchiseTradeFinderProposal,
) -> tuple:
    response_rank = 0 if proposal.cpu_response == "accept" else 1
    return (
        response_rank,
        abs(float(proposal.user_value_delta)),
        -float(proposal.ranking_score),
        proposal.proposal_id,
    )


def run_cpu_incoming_trade_offer_tick_v1(
    runtime: Any,
    state: Any,
    trade_state: Any,
    *,
    controlled_teams: Iterable[str],
    proposal_generator: Callable[..., Any] = generate_trade_finder_proposals,
    cpu_team_order_builder: Callable[..., list[tuple[float, str, Any]]] | None = None,
    private_transactional_state: bool = False,
) -> CPUIncomingTradeOfferTickResult:
    """Generate at most one CPU offer with low-cost cadence checks."""
    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_2_1
    # Detailed V6B timing is diagnostic only. It does not change cadence,
    # candidate generation, legality, or transaction behavior.
    _tick_started = time.perf_counter()
    _timings: dict[str, float] = {}

    def _record_timing(name: str, started: float) -> None:
        _timings[name] = round(
            _timings.get(name, 0.0) + (time.perf_counter() - started),
            4,
        )

    working = state
    day = int(getattr(state, "current_day_index", 0) or 0)
    median_games = _median_games_played(state)
    controlled = tuple(sorted({_team(team) for team in controlled_teams if _team(team)}))
    changed = False

    def result(*, ran: bool, created_offer: bool, reason: str,
               offer_id: str = "", user_team: str = "", cpu_team: str = "",
               target_player_id: str = "", target_player_name: str = "",
               teams_scanned: int = 0, proposals_considered: int = 0):
        return CPUIncomingTradeOfferTickResult(
            version=CPU_INCOMING_TRADE_OFFERS_VERSION,
            state=working,
            ran=ran,
            changed=changed or created_offer,
            created_offer=created_offer,
            offer_id=offer_id,
            user_team=user_team,
            cpu_team=cpu_team,
            target_player_id=str(target_player_id),
            target_player_name=target_player_name,
            reason=reason,
            current_day=day,
            median_games_played=round(median_games, 1),
            cpu_teams_scanned=teams_scanned,
            proposals_considered=proposals_considered,
            timing_breakdown={
                **_timings,
                "total": round(time.perf_counter() - _tick_started, 4),
            },
        )

    if not controlled:
        return result(ran=False, created_offer=False, reason="No user-controlled franchise is available for incoming offers.")
    if _phase(state) != "regular_season":
        return result(ran=False, created_offer=False, reason="Incoming CPU offers are limited to the regular season.")
    if median_games < MIN_MEDIAN_GAMES:
        return result(ran=False, created_offer=False, reason=f"Incoming-offer market has not opened yet. Median team games: {median_games:.1f}/{MIN_MEDIAN_GAMES}.")
    if median_games >= TRADE_DEADLINE_MEDIAN_GAMES:
        return result(ran=False, created_offer=False, reason="Incoming CPU offers are closed after the trade-deadline guard.")

    existing = getattr(state, STATE_ATTRIBUTE, None)
    if not isinstance(existing, dict) or existing.get("season") != _season(state):
        source_offers, offers_created = [], 0
        last_offer_day, last_scan_day = -10_000, -10_000
    else:
        source_offers = list(existing.get("offers", ()) or ())
        offers_created = int(existing.get("offers_created", 0) or 0)
        last_offer_day = int(existing.get("last_offer_day", -10_000) or -10_000)
        last_scan_day = int(existing.get("last_scan_day", -10_000) or -10_000)

    active_pending = [
        offer for offer in source_offers
        if offer.get("status") == "pending"
        and day <= int(offer.get("expires_day", day) or day)
    ]
    expired_pending_exists = any(
        offer.get("status") == "pending"
        and day > int(offer.get("expires_day", day) or day)
        for offer in source_offers
    )
    if active_pending:
        return result(ran=False, created_offer=False, reason="A CPU trade offer is already waiting for a user decision.")
    if offers_created >= MAX_OFFERS_PER_SEASON:
        return result(ran=False, created_offer=False, reason="Season cap for incoming CPU trade offers has been reached.")
    if day - last_offer_day < OFFER_COOLDOWN_DAYS:
        return result(ran=False, created_offer=False, reason=f"Incoming-offer market is on post-offer cooldown for {OFFER_COOLDOWN_DAYS - (day - last_offer_day)} more day(s).")
    if not expired_pending_exists and day - last_scan_day < OFFER_SCAN_INTERVAL_DAYS:
        return result(ran=False, created_offer=False, reason=f"Incoming-offer scan is scheduled in {OFFER_SCAN_INTERVAL_DAYS - (day - last_scan_day)} more day(s).")

    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_3
    # Game Day already operates on the private deepcopy created by
    # commit_game_transactionally(). When the caller explicitly certifies that
    # isolation, do not clone the full franchise universe a second time.
    # All other callers retain the original defensive deepcopy by default.
    _stage_started = time.perf_counter()
    working = state if private_transactional_state else copy.deepcopy(state)
    _record_timing("state_copy", _stage_started)

    _stage_started = time.perf_counter()
    payload = _ensure_offer_state(working)
    expired = _expire_pending_offers(working)
    _record_timing("offer_state", _stage_started)
    changed = expired > 0
    payload["last_scan_day"] = day
    changed = True

    order_builder = cpu_team_order_builder or _cpu_team_order
    teams_scanned = 0
    proposals_considered = 0
    # FRANCHISE_TRADE_MARKET_PERFORMANCE_V7_1
    # A due scan may query two CPU teams. Reuse one full market context across
    # those searches while retaining every final legality/transaction check.
    search_context = None
    if (
        order_builder is _cpu_team_order
        or proposal_generator is generate_trade_finder_proposals
    ):
        _stage_started = time.perf_counter()
        search_context = build_trade_finder_search_context(
            runtime,
            working,
            trade_state,
            trusted_read_only_state=private_transactional_state,
        )
        _record_timing("context_build", _stage_started)
        for _ctx_name, _ctx_seconds in dict(
            getattr(search_context, "build_timing", {}) or {}
        ).items():
            _timings[f"ctx_{_ctx_name}"] = round(float(_ctx_seconds), 4)

    for user_team in controlled:
        team_state = (getattr(working, "teams", {}) or {}).get(user_team)
        if team_state is None:
            continue
        user_roster = {str(pid) for pid in tuple(getattr(team_state, "roster_player_ids", ()) or ())}
        _stage_started = time.perf_counter()
        if order_builder is _cpu_team_order:
            cpu_rows = order_builder(
                working, runtime, trade_state,
                user_team=user_team,
                controlled_teams=controlled,
                search_context=search_context,
            )
        else:
            cpu_rows = order_builder(
                working, runtime, trade_state,
                user_team=user_team,
                controlled_teams=controlled,
            )
        _record_timing("team_order", _stage_started)
        if not cpu_rows:
            continue
        cursor = int(payload.get("scan_cursor", 0) or 0) % len(cpu_rows)
        rotated = cpu_rows[cursor:] + cpu_rows[:cursor]
        rows_to_scan = rotated[:MAX_CPU_TEAMS_SCANNED]

        for _urgency, cpu_team, profile in rows_to_scan:
            teams_scanned += 1
            goal = _goal_for_profile(profile)
            _finder_started = time.perf_counter()
            try:
                if proposal_generator is generate_trade_finder_proposals:
                    finder = proposal_generator(
                        runtime, working, trade_state,
                        active_team=cpu_team,
                        goal=goal,
                        partner_team=user_team,
                        include_picks=True,
                        max_results=3,
                        max_partners=1,
                        max_targets_per_partner=2,
                        max_package_evaluations=4,
                        max_financial_prechecks=90,
                        search_context=search_context,
                    )
                else:
                    finder = proposal_generator(
                        runtime, working, trade_state,
                        active_team=cpu_team,
                        goal=goal,
                        partner_team=user_team,
                        include_picks=True,
                        max_results=3,
                        max_partners=1,
                        max_targets_per_partner=2,
                        max_package_evaluations=4,
                        max_financial_prechecks=90,
                    )
            except Exception:
                _record_timing(f"finder_{teams_scanned}", _finder_started)
                continue
            _record_timing(f"finder_{teams_scanned}", _finder_started)

            _stage_started = time.perf_counter()
            proposals = [
                proposal for proposal in tuple(getattr(finder, "proposals", ()) or ())
                if _proposal_is_reasonable_for_cpu(proposal, user_roster=user_roster)
            ]
            proposals_considered += len(proposals)
            if not proposals:
                _record_timing("proposal_filter", _stage_started)
                continue
            proposals.sort(key=_proposal_rank)
            proposal = proposals[0]
            fingerprint = _clean((proposal.preview_payload or {}).get("package_fingerprint"))
            if not fingerprint:
                _record_timing("proposal_filter", _stage_started)
                continue
            _record_timing("proposal_filter", _stage_started)

            _stage_started = time.perf_counter()
            player_names, pick_names = _asset_name_maps(runtime, working, trade_state)
            cpu_sends = _side_names(proposal.side_a_player_ids, proposal.side_a_pick_asset_ids, player_names, pick_names)
            user_sends = _side_names(proposal.side_b_player_ids, proposal.side_b_pick_asset_ids, player_names, pick_names)
            expires_day = day + OFFER_LIFETIME_DAYS
            offer_id = _offer_id(_season(working), day, cpu_team, user_team, proposal.proposal_id)
            target_id = str(proposal.target_player_id)
            target_name = _clean(proposal.target_player_name) or _player_name(working, target_id)
            offer = {
                "version": CPU_INCOMING_TRADE_OFFERS_VERSION,
                "offer_id": offer_id,
                "season": _season(working),
                "created_day": day,
                "expires_day": expires_day,
                "resolved_day": None,
                "status": "pending",
                "user_team": user_team,
                "cpu_team": cpu_team,
                "proposal_id": proposal.proposal_id,
                "goal": proposal.goal,
                "cpu_response": proposal.cpu_response,
                "response_label": proposal.response_label,
                "target_player_id": target_id,
                "target_player_name": target_name,
                "side_a_player_ids": list(proposal.side_a_player_ids),
                "side_b_player_ids": list(proposal.side_b_player_ids),
                "side_a_pick_asset_ids": list(proposal.side_a_pick_asset_ids),
                "side_b_pick_asset_ids": list(proposal.side_b_pick_asset_ids),
                "cpu_sends_names": cpu_sends,
                "user_sends_names": user_sends,
                "cpu_value_delta": float(proposal.user_value_delta),
                "user_model_value_delta": float(proposal.cpu_value_delta),
                "ranking_score": float(proposal.ranking_score),
                "rationale": _clean(proposal.rationale),
                "package_fingerprint": fingerprint,
                "transaction_id": "",
            }
            payload["offers"].append(offer)
            payload["offers_created"] = int(payload.get("offers_created", 0) or 0) + 1
            payload["last_offer_day"] = day
            payload["scan_cursor"] = (cursor + max(1, teams_scanned)) % max(1, len(cpu_rows))
            payload["history"].append({
                "offer_id": offer_id,
                "day_index": day,
                "outcome": "created",
                "cpu_team": cpu_team,
                "user_team": user_team,
                "target_player_name": target_name,
            })
            detail = _summary(cpu_team, user_team, cpu_sends, user_sends, expires_day)
            _append_event(
                working,
                dedupe_key=f"cpu-trade-offer-{offer_id}",
                category="trade",
                event_type="cpu_trade_offer",
                severity="info",
                title=f"{cpu_team} sent {user_team} a trade offer",
                detail=detail,
                action_section="Inbox & League Health",
                blocking=False,
                team=user_team,
                player_id=target_id,
                metadata={"offer_id": offer_id, "cpu_team": cpu_team, "user_team": user_team, "expires_day": expires_day},
            )
            _record_timing("offer_finalize", _stage_started)
            return result(
                ran=True, created_offer=True,
                reason="A CPU team generated a legal incoming trade offer for user review.",
                offer_id=offer_id, user_team=user_team, cpu_team=cpu_team,
                target_player_id=target_id, target_player_name=target_name,
                teams_scanned=teams_scanned, proposals_considered=proposals_considered,
            )

        payload["scan_cursor"] = (cursor + max(1, len(rows_to_scan))) % max(1, len(cpu_rows))

    payload["history"].append({
        "day_index": day,
        "outcome": "no_offer",
        "reason": "CPU teams searched the user-controlled trade market, but no fair actionable package was available.",
        "teams_scanned": teams_scanned,
    })
    return result(
        ran=True, created_offer=False,
        reason="CPU teams searched the user-controlled trade market, but no fair actionable package was available.",
        teams_scanned=teams_scanned,
        proposals_considered=proposals_considered,
    )

def _resolve_traded_player_context(
    state: Any,
    player_ids: Iterable[str],
) -> None:
    payload = getattr(state, "franchise_morale_chemistry_v1", None)
    if not isinstance(payload, dict):
        return

    for raw_pid in player_ids:
        pid = str(raw_pid)
        row = (payload.get("players") or {}).get(pid)
        if isinstance(row, dict):
            score = float(row.get("score", 65.0) or 65.0)
            refreshed = max(58.0, min(75.0, score + 8.0))
            row["previous_score"] = round(refreshed, 1)
            row["score"] = round(refreshed, 1)
            row["trade_request_active"] = False
            row["trade_request_status"] = "Resolved by trade"
            row["trade_request_risk"] = 0.0
            row["low_morale_games"] = 0
            row["high_risk_games"] = 0
            row["recent_games"] = []

        for key in ("role_promises", "trade_responses", "meetings"):
            mapping = payload.get(key)
            if isinstance(mapping, dict):
                mapping.pop(pid, None)


def _finalize_offer(
    state: Any,
    offer: dict[str, Any],
    *,
    outcome: str,
    transaction_id: str = "",
) -> None:
    payload = _ensure_offer_state(state)
    offer["status"] = outcome
    offer["resolved_day"] = int(
        getattr(state, "current_day_index", 0) or 0
    )
    offer["transaction_id"] = transaction_id

    event = _event_for_offer(state, offer["offer_id"])
    if event is not None:
        resolve_event(state, event["event_id"])

    payload["history"].append(
        {
            "offer_id": offer["offer_id"],
            "day_index": int(
                getattr(state, "current_day_index", 0) or 0
            ),
            "outcome": outcome,
            "cpu_team": offer["cpu_team"],
            "user_team": offer["user_team"],
            "target_player_name": offer["target_player_name"],
            "transaction_id": transaction_id,
        }
    )


def _load_counter_workspace(
    offer: dict[str, Any],
) -> None:
    import streamlit as st

    user = _team(offer["user_team"])
    cpu = _team(offer["cpu_team"])

    st.session_state[
        f"franchise_trade_center_v2_partner_{user}"
    ] = cpu
    st.session_state[
        f"franchise_trade_center_v2_side_a_players_{user}_{cpu}"
    ] = list(offer["side_b_player_ids"])
    st.session_state[
        f"franchise_trade_center_v2_side_b_players_{user}_{cpu}"
    ] = list(offer["side_a_player_ids"])
    st.session_state[
        f"franchise_trade_center_v2_side_a_picks_{user}_{cpu}"
    ] = list(offer["side_b_pick_asset_ids"])
    st.session_state[
        f"franchise_trade_center_v2_side_b_picks_{user}_{cpu}"
    ] = list(offer["side_a_pick_asset_ids"])
    st.session_state.pop(SESSION_PREVIEW_KEY, None)
    st.session_state[LEDGER_VIEW_KEY] = "Trade Builder"


def render_cpu_incoming_trade_offer_actions_v1(
    runtime: Any,
    state: Any,
    trade_state: Any,
    event: dict[str, Any],
    *,
    controlled_teams: Iterable[str],
    commit_state_callback: Callable[..., Any],
    set_section_callback: Callable[[str], Any],
) -> bool:
    """Render specialized inbox controls for a CPU incoming trade offer.

    Returns True when the event was a CPU offer and generic inbox actions should
    be skipped.
    """
    if _clean(event.get("event_type")) != "cpu_trade_offer":
        return False

    import streamlit as st

    metadata = event.get("metadata")
    offer_id = (
        _clean(metadata.get("offer_id"))
        if isinstance(metadata, dict)
        else ""
    )
    offer = _offer_by_id(state, offer_id)

    if offer is None:
        st.warning(
            "This trade-offer event no longer has a matching persistent offer record."
        )
        return True

    if offer.get("status") != "pending":
        st.caption(
            f"Offer status: {_clean(offer.get('status')).replace('_', ' ').title()}."
        )
        return True

    current_day = int(getattr(state, "current_day_index", 0) or 0)
    if current_day > int(offer.get("expires_day", current_day) or current_day):
        _expire_pending_offers(state)
        commit_state_callback(
            state,
            checkpoint_reason="franchise-cpu-trade-offer-expired-v6b",
        )
        st.rerun()

    cpu_sends = ", ".join(offer.get("cpu_sends_names", ())) or "No assets"
    user_sends = ", ".join(offer.get("user_sends_names", ())) or "No assets"

    st.markdown(
        f"**{offer['cpu_team']} sends:** {cpu_sends}  \n"
        f"**{offer['user_team']} sends:** {user_sends}"
    )
    st.caption(
        f"Expires after league day {offer['expires_day']} · "
        f"CPU proposal model: {offer['response_label']} · "
        f"Target: {offer['target_player_name']}"
    )

    cols = st.columns([1, 1, 1, 2])

    if cols[0].button(
        "Accept offer",
        type="primary",
        key=f"cpu_offer_accept_{offer_id}",
        width="stretch",
    ):
        if _team(offer["user_team"]) not in {
            _team(team)
            for team in controlled_teams
        }:
            st.error("This offer is not addressed to a currently controlled team.")
            return True

        try:
            committed = commit_live_franchise_trade(
                runtime,
                state,
                trade_state,
                team_a=_team(offer["cpu_team"]),
                team_b=_team(offer["user_team"]),
                side_a_player_ids=tuple(offer["side_a_player_ids"]),
                side_b_player_ids=tuple(offer["side_b_player_ids"]),
                side_a_pick_asset_ids=tuple(offer["side_a_pick_asset_ids"]),
                side_b_pick_asset_ids=tuple(offer["side_b_pick_asset_ids"]),
                expected_fingerprint=_clean(
                    offer["package_fingerprint"]
                ),
            )
        except FranchiseTradeTransactionError as exc:
            st.error(
                "The offer could not be committed. The package may have become "
                f"stale or illegal since it was created. {exc}"
            )
            return True

        committed_state = committed.committed_state
        committed_offer = _offer_by_id(committed_state, offer_id)
        if committed_offer is not None:
            _finalize_offer(
                committed_state,
                committed_offer,
                outcome="accepted",
                transaction_id=committed.transaction_id,
            )

        _resolve_traded_player_context(
            committed_state,
            tuple(offer["side_a_player_ids"])
            + tuple(offer["side_b_player_ids"]),
        )

        commit_state_callback(
            committed_state,
            checkpoint_reason="franchise-cpu-trade-offer-accepted-v6b",
        )
        st.session_state["franchise_notice"] = (
            f"Accepted {offer['cpu_team']}'s trade offer. "
            f"Transaction {committed.transaction_id} is complete."
        )
        st.rerun()

    if cols[1].button(
        "Reject",
        key=f"cpu_offer_reject_{offer_id}",
        width="stretch",
    ):
        _finalize_offer(
            state,
            offer,
            outcome="rejected",
        )
        commit_state_callback(
            state,
            checkpoint_reason="franchise-cpu-trade-offer-rejected-v6b",
        )
        st.session_state["franchise_notice"] = (
            f"Rejected {offer['cpu_team']}'s trade offer."
        )
        st.rerun()

    if cols[2].button(
        "Counter",
        key=f"cpu_offer_counter_{offer_id}",
        width="stretch",
    ):
        _load_counter_workspace(offer)
        _finalize_offer(
            state,
            offer,
            outcome="countered",
        )
        commit_state_callback(
            state,
            checkpoint_reason="franchise-cpu-trade-offer-countered-v6b",
        )
        set_section_callback("Trade Center")
        st.session_state["franchise_notice"] = (
            f"Loaded {offer['cpu_team']}'s offer into Trade Center. "
            "Adjust the package and submit your counter when ready."
        )
        st.rerun()

    cols[3].caption(
        "Accept commits the exact legal package. Counter opens the same assets "
        "in Trade Center without auto-executing anything."
    )
    return True


def cpu_incoming_trade_offer_snapshot_v1(
    state: Any,
) -> dict[str, Any]:
    _expire_pending_offers(state)
    payload = _ensure_offer_state(state)
    day = int(getattr(state, "current_day_index", 0) or 0)
    pending = [dict(offer) for offer in payload["offers"] if offer.get("status") == "pending"]
    last_scan = int(payload.get("last_scan_day", -10_000) or -10_000)
    last_offer = int(payload.get("last_offer_day", -10_000) or -10_000)
    return {
        "version": CPU_INCOMING_TRADE_OFFERS_VERSION,
        "performance_version": CPU_INCOMING_TRADE_OFFERS_PERFORMANCE_VERSION,
        "season": _season(state),
        "current_day": day,
        "offers_created": int(payload.get("offers_created", 0) or 0),
        "last_scan_day": last_scan,
        "last_offer_day": last_offer,
        "scan_cursor": int(payload.get("scan_cursor", 0) or 0),
        "days_until_next_scan": max(0, OFFER_SCAN_INTERVAL_DAYS - (day - last_scan)),
        "days_until_offer_cooldown_clear": max(0, OFFER_COOLDOWN_DAYS - (day - last_offer)),
        "pending": pending,
        "history": list(payload.get("history", ())),
    }


def render_cpu_incoming_trade_offer_market_status_v1(state: Any) -> None:
    import pandas as pd
    import streamlit as st

    snapshot = cpu_incoming_trade_offer_snapshot_v1(state)
    pending = snapshot["pending"]
    history = snapshot["history"]

    st.markdown("### Incoming CPU trade calls")
    st.caption(
        "CPU teams scan the user-controlled market in small rotating batches. "
        "A failed scan retries after two league days; an actual offer starts a seven-day cooldown."
    )
    cols = st.columns(4)
    cols[0].metric("Offers this season", snapshot["offers_created"])
    cols[1].metric("Pending", len(pending))
    cols[2].metric("Next scan", f'{snapshot["days_until_next_scan"]} day(s)')
    cols[3].metric("Post-offer cooldown", f'{snapshot["days_until_offer_cooldown_clear"]} day(s)')

    if pending:
        offer = pending[0]
        st.info(f'{offer["cpu_team"]} has an offer waiting for {offer["user_team"]} in the Decision Inbox.')
    elif history and history[-1].get("outcome") == "no_offer":
        st.caption("Last scan found no fair actionable package. The next CPU batch will be checked automatically.")

    if history:
        frame = pd.DataFrame(history[-8:])
        keep = ["day_index", "outcome", "cpu_team", "user_team", "target_player_name", "teams_scanned", "offer_id"]
        frame = frame[[column for column in keep if column in frame.columns]]
        st.dataframe(frame.iloc[::-1], hide_index=True, width="stretch")


__all__ = [
    "CPU_INCOMING_TRADE_OFFERS_VERSION",
    "CPUIncomingTradeOfferError",
    "CPUIncomingTradeOfferTickResult",
    "run_cpu_incoming_trade_offer_tick_v1",
    "render_cpu_incoming_trade_offer_actions_v1",
    "pending_cpu_trade_offers_v1",
    "cpu_incoming_trade_offer_snapshot_v1",
    "render_cpu_incoming_trade_offer_market_status_v1",
]
