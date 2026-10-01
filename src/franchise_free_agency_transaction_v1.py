from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Mapping


FREE_AGENCY_TRANSACTION_VERSION = (
    "franchise-free-agency-transaction-v1-2026-08-13"
)
FREE_AGENCY_OFFER_VERSION = (
    "franchise-free-agency-offer-v1-2026-08-13"
)
FREE_AGENCY_PREVIEW_CLONE_VERSION = (
    "franchise-free-agency-preview-copy-on-write-v1-2026-09-10"
)
FREE_AGENCY_DEFERRED_PREVIEW_FINGERPRINT_VERSION = (
    "franchise-free-agency-deferred-preview-fingerprint-v1-2026-09-11"
)
FREE_AGENCY_SUBFIVE_ROTATION_REPAIR_VERSION = (
    "franchise-free-agency-subfive-rotation-repair-v1.1-2026-09-11"
)
FREE_AGENCY_SPECULATIVE_TOUCHED_VALIDATION_VERSION = (
    "franchise-free-agency-speculative-touched-validation-v1-2026-09-25"
)
SUPPORTED_OPTION_TYPES = {
    "",
    "team_option",
    "player_option",
}
DEFAULT_MAX_ROSTER_SIZE = 18


class FreeAgencyTransactionError(RuntimeError):
    """Raised when a free-agency transaction cannot safely proceed."""


@dataclass(frozen=True)
class FreeAgencyOffer:
    player_id: str
    team_abbreviation: str
    annual_salary: float
    years: int
    guaranteed: bool = True
    option_type: str = ""
    offer_id: str = ""


@dataclass(frozen=True)
class FreeAgencyFinancialGateResult:
    status: str
    reason: str = ""
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class FreeAgencyTransactionPreview:
    transaction_version: str
    offer_version: str
    offer: FreeAgencyOffer
    player_name: str
    source_fingerprint: str
    candidate_fingerprint: str
    status: str
    can_commit: bool
    checks: dict[str, bool]
    financial_gate: FreeAgencyFinancialGateResult
    roster_count_before: int
    roster_count_after: int
    message: str


@dataclass(frozen=True)
class FreeAgencyCommitResult:
    transaction_version: str
    offer_id: str
    player_id: str
    player_name: str
    team_abbreviation: str
    source_fingerprint: str
    committed_fingerprint: str
    roster_count_before: int
    roster_count_after: int


FinancialGate = Callable[
    [Any, FreeAgencyOffer],
    FreeAgencyFinancialGateResult | Mapping[str, Any] | str,
]
StateValidator = Callable[[Any], Any]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_team(value: Any) -> str:
    return _clean_text(value).upper()


def _normalize_player_id(value: Any) -> str:
    text = _clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(
                value.items(), key=lambda pair: str(pair[0])
            )
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _contract_payload(contract: Any) -> dict[str, Any]:
    return {
        "status": _clean_text(getattr(contract, "status", "")),
        "salary": getattr(contract, "salary", None),
        "years_remaining": getattr(contract, "years_remaining", None),
        "option_type": _clean_text(
            getattr(contract, "option_type", "")
        ),
        "guaranteed": getattr(contract, "guaranteed", None),
    }


def free_agency_state_payload(state: Any) -> dict[str, Any]:
    players = getattr(state, "players", {})
    teams = getattr(state, "teams", {})
    settings = getattr(state, "settings", None)
    phase = getattr(state, "phase", "")
    phase_value = getattr(phase, "value", phase)

    return {
        "state_version": _clean_text(
            getattr(state, "state_version", "")
        ),
        "season_label": _clean_text(
            getattr(settings, "season_label", "")
        ),
        "phase": _clean_text(phase_value),
        "source_league_state_revision": int(
            getattr(state, "source_league_state_revision", 0) or 0
        ),
        "source_transaction_count": int(
            getattr(state, "source_transaction_count", 0) or 0
        ),
        "transition_count": int(
            getattr(state, "transition_count", 0) or 0
        ),
        "franchise_transaction_revision": int(
            getattr(state, "franchise_transaction_revision", 0) or 0
        ),
        "free_agents": sorted(
            _normalize_player_id(player_id)
            for player_id in getattr(
                state, "free_agent_player_ids", ()
            )
        ),
        "players": {
            _normalize_player_id(player_id): {
                "team": _normalize_team(
                    getattr(player, "team_abbreviation", "")
                ),
                "roster_status": _clean_text(
                    getattr(player, "roster_status", "")
                ),
                "two_way": bool(
                    getattr(player, "two_way", False)
                ),
                "contract": _contract_payload(
                    getattr(player, "contract", None)
                ),
            }
            for player_id, player in sorted(
                players.items(), key=lambda pair: str(pair[0])
            )
        },
        "teams": {
            _normalize_team(team_id): {
                "roster": [
                    _normalize_player_id(player_id)
                    for player_id in getattr(
                        team, "roster_player_ids", ()
                    )
                ],
                "active": [
                    _normalize_player_id(player_id)
                    for player_id in getattr(
                        team, "active_player_ids", ()
                    )
                ],
                "inactive": [
                    _normalize_player_id(player_id)
                    for player_id in getattr(
                        team, "inactive_player_ids", ()
                    )
                ],
                "rotation": {
                    "starters": [
                        _normalize_player_id(player_id)
                        for player_id in getattr(
                            getattr(team, "rotation", None),
                            "starter_ids",
                            (),
                        )
                    ],
                    "rotation_players": [
                        _normalize_player_id(player_id)
                        for player_id in getattr(
                            getattr(team, "rotation", None),
                            "rotation_player_ids",
                            (),
                        )
                    ],
                    "minutes": _json_safe(
                        getattr(
                            getattr(team, "rotation", None),
                            "minutes_targets",
                            {},
                        )
                    ),
                },
            }
            for team_id, team in sorted(
                teams.items(), key=lambda pair: str(pair[0])
            )
        },
    }


def free_agency_state_fingerprint(state: Any) -> str:
    encoded = json.dumps(
        free_agency_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_offer(offer: FreeAgencyOffer) -> FreeAgencyOffer:
    player_id = _normalize_player_id(offer.player_id)
    team = _normalize_team(offer.team_abbreviation)
    option_type = _clean_text(offer.option_type).lower()
    annual_salary = float(offer.annual_salary)
    years = int(offer.years)

    if offer.offer_id:
        offer_id = _clean_text(offer.offer_id)
    else:
        raw = (
            f"{FREE_AGENCY_OFFER_VERSION}|{player_id}|{team}|"
            f"{annual_salary:.2f}|{years}|{bool(offer.guaranteed)}|"
            f"{option_type}"
        ).encode("utf-8")
        offer_id = "FAO-" + hashlib.sha256(raw).hexdigest()[:16].upper()

    return FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=annual_salary,
        years=years,
        guaranteed=bool(offer.guaranteed),
        option_type=option_type,
        offer_id=offer_id,
    )


def _normalize_gate_result(
    result: FreeAgencyFinancialGateResult | Mapping[str, Any] | str | None,
) -> FreeAgencyFinancialGateResult:
    if result is None:
        return FreeAgencyFinancialGateResult(
            status="manual_review",
            reason=(
                "No financial/CBA gate was supplied. Free Agency V1 "
                "never releases a signing without an explicit PASS."
            ),
            payload={},
        )
    if isinstance(result, FreeAgencyFinancialGateResult):
        status = _clean_text(result.status).lower()
        return FreeAgencyFinancialGateResult(
            status=status,
            reason=_clean_text(result.reason),
            payload=dict(result.payload or {}),
        )
    if isinstance(result, str):
        return FreeAgencyFinancialGateResult(
            status=_clean_text(result).lower(),
            reason="",
            payload={},
        )
    if isinstance(result, Mapping):
        return FreeAgencyFinancialGateResult(
            status=_clean_text(result.get("status", "")).lower(),
            reason=_clean_text(result.get("reason", "")),
            payload=dict(result.get("payload", {}) or {}),
        )
    return FreeAgencyFinancialGateResult(
        status="manual_review",
        reason="Unrecognized financial/CBA gate result.",
        payload={},
    )


def _default_state_validator(state: Any) -> Any:
    from simulation_league_state_v1 import (  # local import by design
        validate_simulation_league_state,
    )

    return validate_simulation_league_state(state)


def _speculative_candidate_validator(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    max_roster_size: int,
) -> dict[str, bool]:
    """Validate only state surfaces a speculative FA signing can mutate.

    Production CPU offer-board construction validates the complete source
    league state once before speculative previews begin. A preview then clones
    only the target player, target team and free-agent tuple. Re-running every
    immutable league-wide invariant for every hypothetical offer is therefore
    redundant.

    This validator intentionally covers every invariant the signing itself can
    change. Durable/winning signings still use the full league validator.
    """
    players = getattr(state, "players", {})
    teams = getattr(state, "teams", {})
    player = players.get(offer.player_id)
    team_state = teams.get(offer.team_abbreviation)
    free_ids = {
        _normalize_player_id(player_id)
        for player_id in getattr(state, "free_agent_player_ids", ())
    }
    roster_ids = [
        _normalize_player_id(player_id)
        for team in teams.values()
        for player_id in getattr(team, "roster_player_ids", ())
    ]
    roster_set = set(roster_ids)
    player_ids = {
        _normalize_player_id(player_id)
        for player_id in players
    }

    phase = _clean_text(
        getattr(
            getattr(state, "phase", ""),
            "value",
            getattr(state, "phase", ""),
        )
    ).lower()

    roster_count = (
        len(getattr(team_state, "roster_player_ids", ()))
        if team_state is not None
        else 0
    )
    rotation = (
        getattr(team_state, "rotation", None)
        if team_state is not None
        else None
    )
    rotation_ids = {
        _normalize_player_id(player_id)
        for player_id in getattr(rotation, "rotation_player_ids", ())
    }
    starter_ids = {
        _normalize_player_id(player_id)
        for player_id in getattr(rotation, "starter_ids", ())
    }
    minute_targets = getattr(rotation, "minutes_targets", {}) or {}

    contract = getattr(player, "contract", None) if player is not None else None

    if phase == "offseason" and roster_count < 5:
        expected_starters = roster_count
        expected_minutes = 0.0
    else:
        expected_starters = 5
        regulation_minutes = float(
            getattr(getattr(state, "settings", None), "regulation_minutes", 48.0)
            or 48.0
        )
        expected_minutes = regulation_minutes * 5.0

    checks = {
        "player_exists": player is not None,
        "team_exists": team_state is not None,
        "signed_player_removed_from_free_agent_pool": (
            offer.player_id not in free_ids
        ),
        "free_agents_exist": free_ids.issubset(player_ids),
        "free_agents_not_on_rosters": not free_ids.intersection(roster_set),
        "all_roster_ids_exist": roster_set.issubset(player_ids),
        "league_roster_ids_unique": len(roster_ids) == len(roster_set),
        "signed_player_rostered_exactly_once": (
            roster_ids.count(offer.player_id) == 1
        ),
        "signed_player_on_target_team": (
            team_state is not None
            and offer.player_id
            in {
                _normalize_player_id(value)
                for value in getattr(team_state, "roster_player_ids", ())
            }
        ),
        "target_roster_within_transaction_ceiling": (
            team_state is not None
            and roster_count <= int(max_roster_size)
        ),
        "player_team_assignment_matches": (
            player is not None
            and _normalize_team(
                getattr(player, "team_abbreviation", "")
            )
            == offer.team_abbreviation
        ),
        "player_status_is_active_roster": (
            player is not None
            and _clean_text(
                getattr(player, "roster_status", "")
            ).lower()
            == "active_roster"
        ),
        "player_remains_non_two_way": (
            player is not None
            and not bool(getattr(player, "two_way", False))
        ),
        "rotation_is_roster_subset": (
            team_state is not None
            and rotation_ids.issubset(
                {
                    _normalize_player_id(value)
                    for value in getattr(team_state, "roster_player_ids", ())
                }
            )
        ),
        "starters_are_rotation_subset": starter_ids.issubset(rotation_ids),
        "starter_count_is_valid": (
            len(getattr(rotation, "starter_ids", ())) == expected_starters
        ),
        "rotation_minutes_reconcile": math.isclose(
            sum(float(value) for value in minute_targets.values()),
            expected_minutes,
            abs_tol=0.1,
        ),
        "contract_exists": contract is not None,
        "contract_status_written": (
            contract is not None
            and _clean_text(getattr(contract, "status", "")).lower()
            == "under_contract"
        ),
        "contract_salary_matches_offer": (
            contract is not None
            and math.isclose(
                float(getattr(contract, "salary", 0.0) or 0.0),
                float(offer.annual_salary),
                rel_tol=0.0,
                abs_tol=0.01,
            )
        ),
        "contract_years_match_offer": (
            contract is not None
            and int(getattr(contract, "years_remaining", -1) or -1)
            == int(offer.years)
        ),
        "contract_option_matches_offer": (
            contract is not None
            and _clean_text(getattr(contract, "option_type", "")).lower()
            == _clean_text(offer.option_type).lower()
        ),
        "contract_guarantee_matches_offer": (
            contract is not None
            and bool(getattr(contract, "guaranteed", False))
            == bool(offer.guaranteed)
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise FreeAgencyTransactionError(
            "Speculative free-agency touched-surface validation failed: "
            + ", ".join(failed)
        )
    return checks


def _rostered_player_ids(state: Any) -> set[str]:
    return {
        _normalize_player_id(player_id)
        for team in getattr(state, "teams", {}).values()
        for player_id in getattr(team, "roster_player_ids", ())
    }


def _structural_checks(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    max_roster_size: int,
) -> tuple[dict[str, bool], str, int]:
    players = getattr(state, "players", {})
    teams = getattr(state, "teams", {})
    phase = getattr(state, "phase", "")
    phase_value = _clean_text(getattr(phase, "value", phase)).lower()
    free_agents = {
        _normalize_player_id(player_id)
        for player_id in getattr(state, "free_agent_player_ids", ())
    }
    player = players.get(offer.player_id)
    team_state = teams.get(offer.team_abbreviation)
    roster_ids = _rostered_player_ids(state)
    roster_count = (
        len(getattr(team_state, "roster_player_ids", ()))
        if team_state is not None
        else 0
    )

    checks = {
        "phase_is_offseason": phase_value == "offseason",
        "player_exists": player is not None,
        "team_exists": team_state is not None,
        "player_is_listed_free_agent": (
            offer.player_id in free_agents
        ),
        "player_is_not_on_any_roster": (
            offer.player_id not in roster_ids
        ),
        "player_team_is_unassigned": (
            player is not None
            and not _normalize_team(
                getattr(player, "team_abbreviation", "")
            )
        ),
        "player_roster_status_is_free_agent": (
            player is not None
            and _clean_text(
                getattr(player, "roster_status", "")
            ).lower()
            in {"free_agent", "free_agent_pool"}
        ),
        "player_is_not_two_way": (
            player is not None
            and not bool(getattr(player, "two_way", False))
        ),
        "salary_is_positive_and_finite": _finite_positive(
            offer.annual_salary
        ),
        "contract_years_are_supported": 1 <= offer.years <= 5,
        "option_type_is_supported": (
            offer.option_type in SUPPORTED_OPTION_TYPES
        ),
        "roster_slot_is_available": (
            team_state is not None
            and roster_count < int(max_roster_size)
        ),
    }
    player_name = (
        _clean_text(getattr(player, "player_name", ""))
        if player is not None
        else ""
    )
    return checks, player_name, roster_count


def _apply_offer_to_candidate(
    candidate: Any,
    offer: FreeAgencyOffer,
) -> Any:
    player = candidate.players[offer.player_id]
    team = candidate.teams[offer.team_abbreviation]
    roster_count_before = len(team.roster_player_ids)

    candidate.free_agent_player_ids = tuple(
        player_id
        for player_id in candidate.free_agent_player_ids
        if _normalize_player_id(player_id) != offer.player_id
    )

    if offer.player_id in {
        _normalize_player_id(player_id)
        for player_id in team.roster_player_ids
    }:
        raise FreeAgencyTransactionError(
            "Candidate signing would duplicate a rostered player."
        )

    team.roster_player_ids = tuple(team.roster_player_ids) + (
        offer.player_id,
    )
    if offer.player_id not in {
        _normalize_player_id(player_id)
        for player_id in getattr(team, "inactive_player_ids", ())
    }:
        team.inactive_player_ids = tuple(
            getattr(team, "inactive_player_ids", ())
        ) + (offer.player_id,)

    # Standard signings deliberately leave the active rotation untouched. A
    # separate coaching/rotation action may activate the newly signed player.
    player.team_abbreviation = offer.team_abbreviation
    player.roster_status = "active_roster"
    contract = getattr(player, "contract", None)
    if contract is None:
        raise FreeAgencyTransactionError(
            "Player contract state is unavailable."
        )
    contract.status = "under_contract"
    contract.salary = float(offer.annual_salary)
    contract.years_remaining = int(offer.years)
    contract.option_type = offer.option_type
    contract.guaranteed = bool(offer.guaranteed)

    # A new franchise transaction supersedes any frozen 2026-27 legacy
    # salary-schedule lineage that may have been attached during migration.
    # Keep this local to avoid introducing an eager dependency cycle.
    from franchise_legacy_contract_continuity_v1 import (
        mark_contract_as_franchise_transaction,
    )

    mark_contract_as_franchise_transaction(
        contract,
        season_label=str(candidate.settings.season_label),
        source="franchise_free_agency_transaction_v1",
    )

    # Completed-season closeout legitimately permits an offseason roster with
    # fewer than five players and therefore a partial, zero-minute rotation.
    # Every signing made while the team starts below five must rebuild that
    # partial rotation. Otherwise a 3->4 signing retains the old three-player
    # rotation and full candidate validation circularly blocks the transaction
    # needed to reach five. Once the fifth player signs, the same refresh builds
    # the first valid 240-minute rotation. Normal signings at five or above keep
    # the established inactive-player behavior.
    phase = _clean_text(
        getattr(
            getattr(candidate, "phase", ""),
            "value",
            getattr(candidate, "phase", ""),
        )
    ).lower()
    if (
        phase == "offseason"
        and roster_count_before < 5
    ):
        # Local import avoids coupling the transaction module's import surface
        # to the season-transition engine. The one-team selector is essential
        # for speculative copy-on-write previews, whose other team objects are
        # intentionally shared read-only with the source state.
        from simulation_season_transition_v1 import refresh_team_rotations

        refresh_team_rotations(
            candidate,
            team_abbreviations=(offer.team_abbreviation,),
        )
    return candidate


def _build_preview_candidate_state(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    state_validator: StateValidator,
) -> Any:
    """Build a read-only preview candidate with copy-on-write semantics.

    CPU Free Agency can evaluate thousands of hypothetical offers against a
    mature franchise. Deep-copying the entire league state for every preview
    scales with completed-game/history volume and becomes prohibitively slow.

    A signing preview mutates only three ownership surfaces: the free-agent
    tuple, the target player (including contract), and the destination team.
    Clone those surfaces and share all unrelated state read-only. The preview
    candidate is never returned as a committed live state.
    """
    candidate = copy.copy(state)
    source_players = getattr(state, "players", {})
    source_teams = getattr(state, "teams", {})

    candidate.players = dict(source_players)
    candidate.teams = dict(source_teams)
    candidate.players[offer.player_id] = copy.deepcopy(
        source_players[offer.player_id]
    )
    candidate.teams[offer.team_abbreviation] = copy.deepcopy(
        source_teams[offer.team_abbreviation]
    )
    candidate.free_agent_player_ids = tuple(
        getattr(state, "free_agent_player_ids", ())
    )

    _apply_offer_to_candidate(candidate, offer)
    state_validator(candidate)
    return candidate


def _build_candidate_state(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    state_validator: StateValidator,
) -> Any:
    # Durable commits keep the original full defensive-copy contract. Only
    # speculative previews use the copy-on-write optimization above.
    candidate = copy.deepcopy(state)
    _apply_offer_to_candidate(candidate, offer)
    state_validator(candidate)
    return candidate


def build_free_agency_preview(
    state: Any,
    offer: FreeAgencyOffer,
    *,
    financial_gate: FinancialGate | None = None,
    state_validator: StateValidator | None = None,
    max_roster_size: int = DEFAULT_MAX_ROSTER_SIZE,
    _source_fingerprint: str | None = None,
    _defer_candidate_fingerprint: bool = False,
    _candidate_sink: list[Any] | None = None,
) -> FreeAgencyTransactionPreview:
    resolved_offer = normalized_offer(offer)
    if state_validator is not None:
        validator = state_validator
    elif _defer_candidate_fingerprint:
        validator = lambda candidate: _speculative_candidate_validator(
            candidate,
            resolved_offer,
            max_roster_size=max_roster_size,
        )
    else:
        validator = _default_state_validator

    source_fingerprint = (
        str(_source_fingerprint)
        if _source_fingerprint is not None
        else free_agency_state_fingerprint(state)
    )

    checks, player_name, roster_count = _structural_checks(
        state,
        resolved_offer,
        max_roster_size=max_roster_size,
    )

    structural_pass = all(checks.values())
    gate = _normalize_gate_result(
        financial_gate(state, resolved_offer)
        if financial_gate is not None and structural_pass
        else None
    )
    checks["financial_cba_gate_passes"] = (
        gate.status == "pass"
    )

    candidate_fingerprint = ""
    message = ""
    status = "blocked"
    can_commit = False

    if not structural_pass:
        failed = [
            name for name, passed in checks.items()
            if name != "financial_cba_gate_passes" and not passed
        ]
        message = "Structural signing checks failed: " + ", ".join(failed)
    elif gate.status != "pass":
        status = (
            "manual_review"
            if gate.status in {"", "manual_review", "review"}
            else "blocked"
        )
        message = gate.reason or (
            "Financial/CBA gate did not return PASS."
        )
    else:
        try:
            candidate = _build_preview_candidate_state(
                state,
                resolved_offer,
                state_validator=validator,
            )
        except Exception as exc:
            checks["candidate_state_valid"] = False
            message = f"Candidate signing state is invalid: {exc}"
        else:
            checks["candidate_state_valid"] = True
            if _candidate_sink is not None:
                _candidate_sink.append(candidate)
            # CPU offer-board and roster-floor discovery can validate the
            # exact candidate shape without hashing the entire mature franchise
            # graph for every speculative offer. The winning offer is rebuilt
            # with a full candidate fingerprint immediately before commit.
            if not _defer_candidate_fingerprint:
                candidate_fingerprint = free_agency_state_fingerprint(
                    candidate
                )
            status = "pass"
            can_commit = True
            message = (
                f"{player_name or resolved_offer.player_id} can sign with "
                f"{resolved_offer.team_abbreviation} under the supplied "
                "financial/CBA gate."
            )

    if "candidate_state_valid" not in checks:
        checks["candidate_state_valid"] = False

    return FreeAgencyTransactionPreview(
        transaction_version=FREE_AGENCY_TRANSACTION_VERSION,
        offer_version=FREE_AGENCY_OFFER_VERSION,
        offer=resolved_offer,
        player_name=player_name,
        source_fingerprint=source_fingerprint,
        candidate_fingerprint=candidate_fingerprint,
        status=status,
        can_commit=can_commit,
        checks=checks,
        financial_gate=gate,
        roster_count_before=roster_count,
        roster_count_after=(roster_count + 1 if can_commit else roster_count),
        message=message,
    )


def commit_free_agency_preview(
    state: Any,
    preview: FreeAgencyTransactionPreview,
    *,
    financial_gate: FinancialGate,
    state_validator: StateValidator | None = None,
    max_roster_size: int = DEFAULT_MAX_ROSTER_SIZE,
    _candidate_copy_on_write: bool = False,
    _source_fingerprint: str | None = None,
) -> tuple[Any, FreeAgencyCommitResult]:
    if preview.transaction_version != FREE_AGENCY_TRANSACTION_VERSION:
        raise FreeAgencyTransactionError(
            "Free-agency preview version is stale or incompatible."
        )
    if not preview.can_commit or preview.status != "pass":
        raise FreeAgencyTransactionError(
            "Only a PASS free-agency preview can be committed."
        )

    source_fingerprint = (
        str(_source_fingerprint)
        if _source_fingerprint is not None
        else free_agency_state_fingerprint(state)
    )
    if source_fingerprint != preview.source_fingerprint:
        raise FreeAgencyTransactionError(
            "Free-agency preview is stale because the franchise state changed."
        )

    rebuilt_candidate_sink: list[Any] | None = (
        [] if _candidate_copy_on_write else None
    )
    rebuilt = build_free_agency_preview(
        state,
        preview.offer,
        financial_gate=financial_gate,
        state_validator=state_validator,
        max_roster_size=max_roster_size,
        _source_fingerprint=source_fingerprint,
        _candidate_sink=rebuilt_candidate_sink,
    )
    if (
        not rebuilt.can_commit
        or rebuilt.candidate_fingerprint != preview.candidate_fingerprint
    ):
        raise FreeAgencyTransactionError(
            "The signing no longer reproduces the approved preview."
        )

    if _candidate_copy_on_write:
        if not rebuilt_candidate_sink or len(rebuilt_candidate_sink) != 1:
            raise FreeAgencyTransactionError(
                "The verified copy-on-write signing candidate was not preserved."
            )
        candidate = rebuilt_candidate_sink[0]
        committed_fingerprint = rebuilt.candidate_fingerprint
    else:
        validator = state_validator or _default_state_validator
        candidate = _build_candidate_state(
            state,
            preview.offer,
            state_validator=validator,
        )
        committed_fingerprint = free_agency_state_fingerprint(candidate)

    if committed_fingerprint != preview.candidate_fingerprint:
        raise FreeAgencyTransactionError(
            "Committed candidate does not match the approved preview."
        )

    result = FreeAgencyCommitResult(
        transaction_version=FREE_AGENCY_TRANSACTION_VERSION,
        offer_id=preview.offer.offer_id,
        player_id=preview.offer.player_id,
        player_name=preview.player_name,
        team_abbreviation=preview.offer.team_abbreviation,
        source_fingerprint=preview.source_fingerprint,
        committed_fingerprint=committed_fingerprint,
        roster_count_before=preview.roster_count_before,
        roster_count_after=preview.roster_count_after,
    )
    return candidate, result


def run_self_test() -> int:
    from dataclasses import dataclass, field

    @dataclass
    class ToyContract:
        status: str
        salary: float | None
        years_remaining: int | None = None
        option_type: str = ""
        guaranteed: bool | None = None

    @dataclass
    class ToyPlayer:
        player_id: str
        player_name: str
        team_abbreviation: str
        roster_status: str
        two_way: bool
        contract: ToyContract

    @dataclass
    class ToyRotation:
        starter_ids: tuple[str, ...]
        rotation_player_ids: tuple[str, ...]
        minutes_targets: dict[str, float]

    @dataclass
    class ToyTeam:
        roster_player_ids: tuple[str, ...]
        active_player_ids: tuple[str, ...]
        inactive_player_ids: tuple[str, ...]
        rotation: ToyRotation

    @dataclass
    class ToySettings:
        season_label: str = "2032-33"

    @dataclass
    class ToyState:
        state_version: str = "toy"
        source_league_state_revision: int = 1
        source_transaction_count: int = 0
        transition_count: int = 6
        franchise_transaction_revision: int = 0
        phase: str = "offseason"
        settings: ToySettings = field(default_factory=ToySettings)
        players: dict[str, ToyPlayer] = field(default_factory=dict)
        teams: dict[str, ToyTeam] = field(default_factory=dict)
        free_agent_player_ids: tuple[str, ...] = ("FA1",)

    roster = tuple(f"P{i}" for i in range(1, 11))
    rotation = ToyRotation(
        starter_ids=roster[:5],
        rotation_player_ids=roster,
        minutes_targets={player_id: 24.0 for player_id in roster},
    )
    state = ToyState(
        players={
            "FA1": ToyPlayer(
                player_id="FA1",
                player_name="Test Free Agent",
                team_abbreviation="",
                roster_status="free_agent",
                two_way=False,
                contract=ToyContract(
                    status="free_agent_pool",
                    salary=None,
                ),
            )
        },
        teams={
            "CHI": ToyTeam(
                roster_player_ids=roster,
                active_player_ids=roster,
                inactive_player_ids=(),
                rotation=rotation,
            )
        },
    )

    def validator(candidate: ToyState) -> None:
        assert "FA1" not in candidate.free_agent_player_ids
        assert "FA1" in candidate.teams["CHI"].roster_player_ids
        assert "FA1" in candidate.teams["CHI"].inactive_player_ids
        assert "FA1" not in candidate.teams["CHI"].active_player_ids

    def pass_gate(_state: Any, _offer: FreeAgencyOffer) -> dict[str, Any]:
        return {"status": "pass", "reason": "self-test"}

    source = free_agency_state_fingerprint(state)
    offer = FreeAgencyOffer(
        player_id="FA1",
        team_abbreviation="chi",
        annual_salary=12_500_000,
        years=3,
    )
    no_gate = build_free_agency_preview(
        state,
        offer,
        state_validator=validator,
    )
    approved = build_free_agency_preview(
        state,
        offer,
        financial_gate=pass_gate,
        state_validator=validator,
    )
    candidate, result = commit_free_agency_preview(
        state,
        approved,
        financial_gate=pass_gate,
        state_validator=validator,
    )

    checks = {
        "version_is_current": (
            FREE_AGENCY_TRANSACTION_VERSION
            == "franchise-free-agency-transaction-v1-2026-08-13"
        ),
        "missing_financial_gate_never_commits": (
            not no_gate.can_commit
            and no_gate.status == "manual_review"
        ),
        "pass_gate_releases_preview": approved.can_commit,
        "source_is_unchanged": (
            source == free_agency_state_fingerprint(state)
        ),
        "candidate_removes_free_agent": (
            "FA1" not in candidate.free_agent_player_ids
        ),
        "candidate_adds_roster_player": (
            "FA1" in candidate.teams["CHI"].roster_player_ids
        ),
        "candidate_starts_inactive": (
            "FA1" in candidate.teams["CHI"].inactive_player_ids
            and "FA1" not in candidate.teams["CHI"].active_player_ids
        ),
        "rotation_is_untouched": (
            candidate.teams["CHI"].rotation == state.teams["CHI"].rotation
        ),
        "contract_is_written": (
            candidate.players["FA1"].contract.salary == 12_500_000
            and candidate.players["FA1"].contract.years_remaining == 3
            and candidate.players["FA1"].contract.status == "under_contract"
        ),
        "commit_matches_preview": (
            result.committed_fingerprint == approved.candidate_fingerprint
        ),
    }
    print(json.dumps(checks, indent=2))
    return 0 if all(checks.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    print(FREE_AGENCY_TRANSACTION_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
