
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import simulation_franchise_checkpoint_v1 as checkpoint_api
from franchise_draft_engine_v1 import draft_state
from franchise_free_agency_persistent_calendar_v1 import (
    free_agency_calendar_snapshot,
)
from franchise_free_agency_rfa_offer_sheet_v1 import (
    pending_offer_sheet_for_player,
)
from regular_season_schedule_v1 import LEAGUE_GAME_COUNT
from regular_season_simulation_controller_v1 import (
    ensure_regular_season_ready,
)
from simulation_league_state_v1 import (
    LeaguePhase,
    validate_simulation_league_state,
)

OPENING_REGULAR_SEASON_TRANSITION_VERSION = (
    "franchise-opening-regular-season-transition-v1-2026-08-17"
)


class OpeningRegularSeasonTransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpeningRegularSeasonPreview:
    version: str
    season_label: str
    source_phase: str
    target_phase: str
    schedule_count: int
    scheduled_game_count: int
    free_agent_count: int
    active_free_agency_market_count: int
    pending_offer_sheet_count: int
    trade_revision: int
    source_fingerprint: str
    confirmation_token: str
    can_commit: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class OpeningRegularSeasonCommitResult:
    version: str
    season_label: str
    source_phase: str
    target_phase: str
    source_fingerprint: str
    committed_fingerprint: str
    checkpoint_sha256_before: str
    checkpoint_sha256_after: str
    backup_sha256_before: str | None
    backup_sha256_after: str | None
    recovery_primary_path: str
    recovery_backup_path: str | None
    checkpoint_reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _phase(state: Any) -> str:
    phase = getattr(state, "phase", "")
    return _clean(getattr(phase, "value", phase)).lower()


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _status(game: Any) -> str:
    status = getattr(game, "status", "")
    return _clean(getattr(status, "value", status)).lower()


def _score_is_empty(game: Any) -> bool:
    return (
        getattr(game, "home_score", None) is None
        and getattr(game, "away_score", None) is None
    )


def _standing_record_is_zero(standing: Any) -> bool:
    return (
        int(getattr(standing, "wins", 0) or 0) == 0
        and int(getattr(standing, "losses", 0) or 0) == 0
    )


def _postseason_is_absent(state: Any) -> bool:
    postseason = getattr(state, "postseason_state", None)
    if postseason is None:
        return True
    stage = _clean(
        getattr(
            getattr(postseason, "stage", ""),
            "value",
            getattr(postseason, "stage", ""),
        )
    ).lower()
    champion = _clean(getattr(postseason, "champion", ""))
    return not stage and not champion


def _contract_payload(state: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player_id, player in sorted(
        dict(getattr(state, "players", {}) or {}).items(),
        key=lambda item: str(item[0]),
    ):
        contract = getattr(player, "contract", None)
        if contract is None:
            rows.append(
                {
                    "player_id": str(player_id),
                    "contract": None,
                }
            )
            continue
        salary = getattr(contract, "salary", None)
        try:
            salary = None if salary is None else float(salary)
        except (TypeError, ValueError):
            salary = str(salary)
        rows.append(
            {
                "player_id": str(player_id),
                "status": _clean(getattr(contract, "status", "")),
                "salary": salary,
                "years_remaining": getattr(contract, "years_remaining", None),
                "guaranteed": getattr(contract, "guaranteed", None),
                "option_type": _clean(getattr(contract, "option_type", "")),
            }
        )
    return rows


def _roster_payload(state: Any) -> dict[str, tuple[str, ...]]:
    output: dict[str, tuple[str, ...]] = {}
    for team, team_state in sorted(
        dict(getattr(state, "teams", {}) or {}).items()
    ):
        output[str(team)] = tuple(
            str(player_id)
            for player_id in getattr(
                team_state,
                "roster_player_ids",
                (),
            ) or ()
        )
    return output


def _rights_payload(state: Any) -> dict[str, Any]:
    attrs = (
        "offseason_free_agent_amount_candidates_v1",
        "offseason_non_rfa_rights_decisions_v1",
        "offseason_rfa_rights_qo_decisions_v1",
        "offseason_official_team_salary_components_v1",
        "offseason_transaction_application_v1_history",
        "offseason_transaction_application_v1_revision",
    )
    output: dict[str, Any] = {}
    for attr in attrs:
        if hasattr(state, attr):
            output[attr] = copy.deepcopy(getattr(state, attr))
    return output


def _trade_payload(trade_state: Any) -> dict[str, Any]:
    finances = {}
    for team, financial in sorted(
        dict(getattr(trade_state, "team_financials", {}) or {}).items()
    ):
        finances[str(team)] = {
            "team_salary": float(getattr(financial, "team_salary", 0.0) or 0.0),
            "apron_salary": float(getattr(financial, "apron_salary", 0.0) or 0.0),
        }
    return {
        "state_revision": int(getattr(trade_state, "state_revision", 0) or 0),
        "player_team_by_id": {
            str(player_id): str(team)
            for player_id, team in sorted(
                dict(
                    getattr(
                        trade_state,
                        "player_team_by_id",
                        {},
                    )
                    or {}
                ).items()
            )
        },
        "team_financials": finances,
        "rights": _rights_payload(trade_state),
    }


def _schedule_payload(state: Any) -> list[dict[str, Any]]:
    rows = []
    for game_id, game in dict(getattr(state, "schedule", {}) or {}).items():
        rows.append(
            {
                "game_id": str(game_id),
                "status": _status(game),
                "day_index": int(getattr(game, "day_index", 0) or 0),
                "home_team": _clean(getattr(game, "home_team", "")),
                "away_team": _clean(getattr(game, "away_team", "")),
                "home_score": getattr(game, "home_score", None),
                "away_score": getattr(game, "away_score", None),
            }
        )
    return rows


def _pending_offer_sheets(state: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    player_ids = {
        str(value)
        for value in getattr(state, "free_agent_player_ids", ()) or ()
    }
    player_ids.update(str(value) for value in getattr(state, "players", {}) or {})
    for player_id in sorted(player_ids):
        try:
            row = pending_offer_sheet_for_player(state, player_id)
        except Exception as exc:
            raise OpeningRegularSeasonTransitionError(
                "Pending RFA offer-sheet state could not be inspected for "
                f"{player_id}: {type(exc).__name__}: {exc}"
            ) from exc
        if row:
            found.append(copy.deepcopy(dict(row)))
    return found


def _opening_fingerprint(state: Any, trade_state: Any) -> str:
    calendar = free_agency_calendar_snapshot(state)
    payload = {
        "season_label": _season(state),
        "phase": _phase(state),
        "current_day_index": int(getattr(state, "current_day_index", 0) or 0),
        "transition_count": int(getattr(state, "transition_count", 0) or 0),
        "season_history_count": len(getattr(state, "season_history", []) or []),
        "schedule": _schedule_payload(state),
        "standings": {
            str(team): {
                "wins": int(getattr(standing, "wins", 0) or 0),
                "losses": int(getattr(standing, "losses", 0) or 0),
            }
            for team, standing in sorted(
                dict(getattr(state, "standings", {}) or {}).items()
            )
        },
        "contracts": _contract_payload(state),
        "rosters": _roster_payload(state),
        "free_agents": sorted(
            str(value)
            for value in getattr(state, "free_agent_player_ids", ()) or ()
        ),
        "rights": _rights_payload(state),
        "calendar": {
            "initialized": bool(calendar.initialized),
            "season_label": str(calendar.season_label),
            "offseason_day": int(calendar.offseason_day),
            "revision": int(calendar.revision),
            "active_market_count": int(calendar.active_market_count),
            "archived_market_count": int(calendar.archived_market_count),
            "calendar_fingerprint": str(calendar.calendar_fingerprint),
        },
        "pending_offer_sheets": _pending_offer_sheets(state),
        "trade": _trade_payload(trade_state),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _confirmation_token(season_label: str) -> str:
    return f"CONFIRM_OPEN_REGULAR_SEASON::{season_label}"


def preview_opening_regular_season(
    state: Any,
    trade_state: Any,
) -> OpeningRegularSeasonPreview:
    validate_simulation_league_state(state)

    blockers: list[str] = []
    season = _season(state)
    phase = _phase(state)
    schedule = dict(getattr(state, "schedule", {}) or {})
    scheduled_count = sum(
        _status(game) == "scheduled"
        for game in schedule.values()
    )

    if phase != "offseason":
        blockers.append("source_phase_is_not_offseason")
    if int(getattr(state, "current_day_index", 0) or 0) != 0:
        blockers.append("current_day_is_not_zero")
    if int(getattr(state, "transition_count", 0) or 0) != 0:
        blockers.append("not_the_opening_franchise_offseason")
    if len(getattr(state, "season_history", []) or []) != 0:
        blockers.append("season_history_already_exists")
    if len(schedule) != LEAGUE_GAME_COUNT:
        blockers.append("current_regular_season_schedule_is_not_1230_games")
    if scheduled_count != len(schedule):
        blockers.append("current_regular_season_schedule_has_non_scheduled_games")
    if not all(_score_is_empty(game) for game in schedule.values()):
        blockers.append("current_regular_season_schedule_has_recorded_scores")
    if not all(
        _standing_record_is_zero(standing)
        for standing in dict(getattr(state, "standings", {}) or {}).values()
    ):
        blockers.append("standings_are_not_zero_zero")
    if not _postseason_is_absent(state):
        blockers.append("postseason_state_is_not_absent")
    if draft_state(state) is not None:
        blockers.append("draft_state_already_exists")

    calendar = free_agency_calendar_snapshot(state)
    if int(calendar.active_market_count) != 0:
        blockers.append(
            f"active_free_agency_markets_remain:{calendar.active_market_count}"
        )

    pending_sheets = _pending_offer_sheets(state)
    if pending_sheets:
        blockers.append(
            f"pending_rfa_offer_sheets_remain:{len(pending_sheets)}"
        )

    source_fingerprint = _opening_fingerprint(state, trade_state)
    return OpeningRegularSeasonPreview(
        version=OPENING_REGULAR_SEASON_TRANSITION_VERSION,
        season_label=season,
        source_phase=phase,
        target_phase="regular_season",
        schedule_count=len(schedule),
        scheduled_game_count=scheduled_count,
        free_agent_count=len(
            getattr(state, "free_agent_player_ids", ()) or ()
        ),
        active_free_agency_market_count=int(calendar.active_market_count),
        pending_offer_sheet_count=len(pending_sheets),
        trade_revision=int(getattr(trade_state, "state_revision", 0) or 0),
        source_fingerprint=source_fingerprint,
        confirmation_token=_confirmation_token(season),
        can_commit=not blockers,
        blockers=tuple(blockers),
    )


def build_opening_regular_season_candidate(
    checkpoint: Any,
    *,
    expected_fingerprint: str = "",
) -> tuple[Any, Any, OpeningRegularSeasonPreview]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None or trade_state is None:
        raise OpeningRegularSeasonTransitionError(
            "The Franchise checkpoint does not contain simulation + trade state."
        )

    preview = preview_opening_regular_season(state, trade_state)
    if not preview.can_commit:
        raise OpeningRegularSeasonTransitionError(
            "The opening regular season is not ready: "
            + ", ".join(preview.blockers)
        )
    if (
        expected_fingerprint
        and expected_fingerprint != preview.source_fingerprint
    ):
        raise OpeningRegularSeasonTransitionError(
            "The opening-season preview is stale. Refresh before committing."
        )

    candidate = copy.deepcopy(state)
    trade_candidate = copy.deepcopy(trade_state)

    # This boundary is intentionally NOT a season transition. The 2026-27
    # schedule, contracts, rights, financials, ownership, and TradeState all
    # already describe the coming 2026-27 season. Only activate that schedule.
    candidate.phase = LeaguePhase.REGULAR_SEASON

    validate_simulation_league_state(candidate)
    ensure_regular_season_ready(candidate)

    return candidate, trade_candidate, preview


def _checkpoint_path() -> Path:
    return Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH)


def _backup_path(path: Path) -> Path:
    try:
        return Path(checkpoint_api.checkpoint_backup_path(path))
    except TypeError:
        return Path(checkpoint_api.checkpoint_backup_path())


def _post_save_reload(path: Path) -> Any:
    return checkpoint_api.load_franchise_checkpoint(
        path=path,
        allow_backup=False,
    )


def commit_opening_regular_season_live(
    *,
    confirmation_token: str,
    expected_fingerprint: str,
    recovery_directory: str | Path | None = None,
) -> OpeningRegularSeasonCommitResult:
    checkpoint_path = _checkpoint_path()
    backup_path = _backup_path(checkpoint_path)

    checkpoint = checkpoint_api.load_franchise_checkpoint(
        path=checkpoint_path,
        allow_backup=False,
    )
    if checkpoint is None:
        raise OpeningRegularSeasonTransitionError(
            "The durable Franchise checkpoint could not be loaded."
        )

    candidate, trade_candidate, preview = (
        build_opening_regular_season_candidate(
            checkpoint,
            expected_fingerprint=expected_fingerprint,
        )
    )

    if confirmation_token != preview.confirmation_token:
        raise OpeningRegularSeasonTransitionError(
            "The opening regular-season confirmation token is invalid."
        )

    checkpoint_sha_before = _sha256(checkpoint_path)
    backup_existed = backup_path.exists()
    backup_sha_before = _sha256(backup_path) if backup_existed else None

    root = (
        Path(recovery_directory)
        if recovery_directory is not None
        else checkpoint_path.parent.parent
        / "recovery"
        / "opening_regular_season_transition_v1"
    )
    root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery_primary = root / f"pre_open_regular_season_{stamp}_{checkpoint_path.name}"
    shutil.copy2(checkpoint_path, recovery_primary)

    recovery_backup: Path | None = None
    if backup_existed:
        recovery_backup = (
            root
            / f"pre_open_regular_season_{stamp}_{backup_path.name}"
        )
        shutil.copy2(backup_path, recovery_backup)

    reason = (
        "opening-offseason-to-regular-season-"
        f"{preview.season_label}"
    )

    try:
        checkpoint_api.save_franchise_checkpoint(
            candidate,
            trade_candidate,
            preferences=copy.deepcopy(
                dict(getattr(checkpoint, "preferences", {}) or {})
            ),
            reason=reason,
            path=checkpoint_path,
        )

        restored = _post_save_reload(checkpoint_path)
        if restored is None:
            raise OpeningRegularSeasonTransitionError(
                "The committed opening regular-season checkpoint could not be reloaded."
            )

        committed_preview = preview_opening_regular_season_after_commit(
            restored.simulation_state,
            restored.trade_state,
        )
        committed_fingerprint = _opening_fingerprint(
            restored.simulation_state,
            restored.trade_state,
        )
        if not committed_preview["regular_season_ready"]:
            raise OpeningRegularSeasonTransitionError(
                "The durable opening regular-season checkpoint failed post-save verification."
            )

    except Exception as exc:
        shutil.copy2(recovery_primary, checkpoint_path)

        if backup_existed:
            if recovery_backup is None or not recovery_backup.exists():
                raise OpeningRegularSeasonTransitionError(
                    "Opening-season transition failed and the automatic-backup "
                    "recovery copy is missing."
                ) from exc
            shutil.copy2(recovery_backup, backup_path)
        elif backup_path.exists():
            backup_path.unlink()

        restored = checkpoint_api.load_franchise_checkpoint(
            path=checkpoint_path,
            allow_backup=False,
        )
        if restored is None:
            raise OpeningRegularSeasonTransitionError(
                "Opening-season transition failed and checkpoint recovery could not be verified."
            ) from exc

        restored_fp = _opening_fingerprint(
            restored.simulation_state,
            restored.trade_state,
        )
        if restored_fp != preview.source_fingerprint:
            raise OpeningRegularSeasonTransitionError(
                "Opening-season transition failed and recovery did not restore the exact source state."
            ) from exc

        raise OpeningRegularSeasonTransitionError(
            "Opening regular-season transition failed; the exact pre-action "
            "primary checkpoint and automatic backup were restored."
        ) from exc

    return OpeningRegularSeasonCommitResult(
        version=OPENING_REGULAR_SEASON_TRANSITION_VERSION,
        season_label=preview.season_label,
        source_phase=preview.source_phase,
        target_phase="regular_season",
        source_fingerprint=preview.source_fingerprint,
        committed_fingerprint=committed_fingerprint,
        checkpoint_sha256_before=checkpoint_sha_before,
        checkpoint_sha256_after=_sha256(checkpoint_path),
        backup_sha256_before=backup_sha_before,
        backup_sha256_after=(
            _sha256(backup_path)
            if backup_path.exists()
            else None
        ),
        recovery_primary_path=str(recovery_primary),
        recovery_backup_path=(
            str(recovery_backup)
            if recovery_backup is not None
            else None
        ),
        checkpoint_reason=reason,
    )


def preview_opening_regular_season_after_commit(
    state: Any,
    trade_state: Any,
) -> dict[str, Any]:
    validate_simulation_league_state(state)
    schedule = dict(getattr(state, "schedule", {}) or {})
    calendar = free_agency_calendar_snapshot(state)
    pending_sheets = _pending_offer_sheets(state)

    ready = (
        _phase(state) == "regular_season"
        and len(schedule) == LEAGUE_GAME_COUNT
        and all(_status(game) == "scheduled" for game in schedule.values())
        and all(_score_is_empty(game) for game in schedule.values())
        and int(getattr(state, "current_day_index", 0) or 0) == 0
        and int(calendar.active_market_count) == 0
        and not pending_sheets
    )
    if ready:
        ensure_regular_season_ready(state)

    return {
        "version": OPENING_REGULAR_SEASON_TRANSITION_VERSION,
        "season_label": _season(state),
        "phase": _phase(state),
        "regular_season_ready": ready,
        "schedule_count": len(schedule),
        "active_free_agency_market_count": int(calendar.active_market_count),
        "pending_offer_sheet_count": len(pending_sheets),
        "trade_revision": int(getattr(trade_state, "state_revision", 0) or 0),
    }
