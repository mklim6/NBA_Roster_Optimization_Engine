"""Expansion 49: Rebuild HQ and guided franchise experience.

This module turns existing franchise systems into an intentional rebuild journey.
It does not simulate games, change ratings, alter rotations, sign players, execute trades,
or write a franchise checkpoint.

The only persistence owned here is desktop UX metadata in a separate JSON document:
selected rebuild strategy and whether the guided Rebuild HQ onboarding was completed.
"""
from __future__ import annotations
from desktop_bridge.rebuild_opportunity import opportunity_board

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import os
import tempfile


REBUILD_EXPERIENCE_VERSION = (
    "v3-expansion49-rebuild-hq-guided-franchise-v1.0.0-2026-10-05"
)

STRATEGIES: tuple[dict[str, str], ...] = (
    {
        "id": "develop_young_core",
        "label": "DEVELOP THE YOUNG CORE",
        "short": "Develop",
        "detail": (
            "Prioritize player growth, opportunity, mentorship and patient roster building."
        ),
    },
    {
        "id": "contend_now",
        "label": "CONTEND NOW",
        "short": "Contend",
        "detail": (
            "Protect the current core and use roster-building tools to maximize the present window."
        ),
    },
    {
        "id": "draft_rebuild",
        "label": "REBUILD THROUGH THE DRAFT",
        "short": "Draft",
        "detail": (
            "Emphasize scouting, draft capital, prospect confidence and long-term asset value."
        ),
    },
    {
        "id": "cap_flexibility",
        "label": "CREATE CAP FLEXIBILITY",
        "short": "Cap",
        "detail": (
            "Favor contract optionality, open roster paths and future financial flexibility."
        ),
    },
    {
        "id": "balanced",
        "label": "BALANCED FRONT OFFICE",
        "short": "Balanced",
        "detail": (
            "Keep development, competition, scouting and roster flexibility in balance."
        ),
    },
)

STRATEGY_IDS = {row["id"] for row in STRATEGIES}

FEATURE_GUIDES: tuple[dict[str, str], ...] = (
    {
        "id": "development",
        "destination": "DEVELOPMENT",
        "eyebrow": "START HERE",
        "title": "DEVELOPMENT COMMAND CENTER",
        "why": (
            "Rebuilds become memorable when young players turn into your core. "
            "Set season goals, track real progress, review growth runway and use training camp."
        ),
        "action": "BUILD YOUR CORE",
    },
    {
        "id": "scouting",
        "destination": "SCOUTING",
        "eyebrow": "BUILD THE FUTURE",
        "title": "SCOUTING + DRAFT",
        "why": (
            "Scout the next class over time, increase confidence, choose focus prospects "
            "and carry that information into Draft Night."
        ),
        "action": "SCOUT THE FUTURE",
    },
    {
        "id": "trades",
        "destination": "TRADES",
        "eyebrow": "CHANGE THE CORE",
        "title": "TRADE CENTER",
        "why": (
            "Explore production trade logic, packages, draft capital and CBA legality "
            "without guessing whether a deal can actually be executed."
        ),
        "action": "EXPLORE TRADES",
    },
    {
        "id": "free_agency",
        "destination": "FREE AGENCY",
        "eyebrow": "USE THE MARKET",
        "title": "FREE AGENCY",
        "why": (
            "Compare the live market against roster need, cap position and contract value "
            "before previewing a write-safe signing."
        ),
        "action": "OPEN FREE AGENCY",
    },
    {
        "id": "locker_room",
        "destination": "LOCKER ROOM",
        "eyebrow": "MANAGE PEOPLE",
        "title": "LOCKER ROOM",
        "why": (
            "Roles, promises, morale and player conversations make roster decisions matter "
            "beyond ratings alone."
        ),
        "action": "ENTER LOCKER ROOM",
    },
    {
        "id": "game_day",
        "destination": "GAME DAY",
        "eyebrow": "PUT IT ON COURT",
        "title": "GAME DAY",
        "why": (
            "Prepare the matchup, inspect coaching intelligence and let the synchronized "
            "league calendar turn your roster plan into results."
        ),
        "action": "PREPARE NEXT GAME",
    },
    {
        "id": "offseason",
        "destination": "OFFSEASON",
        "eyebrow": "THE REBUILD CYCLE",
        "title": "OFFSEASON COMMAND",
        "why": (
            "Draft, roster construction, market decisions, development and training camp "
            "flow into the next season through one offseason command experience."
        ),
        "action": "OPEN OFFSEASON",
    },
    {
        "id": "universe",
        "destination": "PULSE",
        "eyebrow": "LIVE WITH THE SAVE",
        "title": "PULSE + STORIES + LEGACY",
        "why": (
            "Follow weekly franchise developments, rivalry storylines and long-term history "
            "without crowding the permanent navigation."
        ),
        "action": "OPEN FRANCHISE PULSE",
    },
)


class RebuildExperienceError(RuntimeError):
    """Raised for invalid Rebuild HQ desktop-metadata actions."""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _read_document(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {
            "version": REBUILD_EXPERIENCE_VERSION,
            "updated_at_utc": "",
            "franchises": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RebuildExperienceError(
            f"Rebuild experience metadata could not be read: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RebuildExperienceError(
            "Rebuild experience metadata must be a JSON object."
        )
    franchises = payload.get("franchises", {})
    if not isinstance(franchises, dict):
        franchises = {}
    return {
        "version": REBUILD_EXPERIENCE_VERSION,
        "updated_at_utc": _text(payload.get("updated_at_utc")),
        "franchises": franchises,
    }


def _stable_seed(checkpoint: Any, team: str) -> str:
    preferences = _mapping(getattr(checkpoint, "preferences", {}))
    for key in (
        "franchise_save_id",
        "save_id",
        "slot_id",
        "franchise_id",
        "universe_id",
    ):
        value = _text(preferences.get(key))
        if value:
            return f"{team}:{value}"

    state = getattr(checkpoint, "simulation_state", None)
    season_history = list(getattr(state, "season_history", []) or [])
    first_season = ""
    if season_history:
        first_season = _text(getattr(season_history[0], "season_label", ""))
    if not first_season:
        first_season = _text(
            getattr(getattr(state, "settings", None), "season_label", "")
        )

    # This is UX metadata only. It intentionally avoids a working-save hash
    # because that hash changes after every legitimate franchise write.
    return f"{team}:{first_season or 'franchise'}"


def franchise_experience_key(checkpoint: Any, team: str) -> str:
    seed = _stable_seed(checkpoint, _text(team).upper())
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{_text(team).upper()}-{digest}"


def load_rebuild_experience(
    path: Path,
    checkpoint: Any,
    team: str,
) -> dict[str, Any]:
    document = _read_document(path)
    key = franchise_experience_key(checkpoint, team)
    raw = document["franchises"].get(key, {})
    if not isinstance(raw, Mapping):
        raw = {}

    strategy = _text(raw.get("strategy"))
    if strategy not in STRATEGY_IDS:
        strategy = ""

    return {
        "experience_version": REBUILD_EXPERIENCE_VERSION,
        "franchise_key": key,
        "strategy": strategy,
        "strategy_source": "user" if strategy else "recommended",
        "onboarding_completed": bool(raw.get("onboarding_completed", False)),
        "onboarding_completed_at_utc": _text(
            raw.get("onboarding_completed_at_utc")
        ),
        "updated_at_utc": _text(raw.get("updated_at_utc")),
        "desktop_metadata_only": True,
        "franchise_save_write_performed": False,
        "active_v2_read_only": True,
    }


def update_rebuild_experience(
    path: Path,
    checkpoint: Any,
    team: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise RebuildExperienceError("Rebuild experience request must be an object.")

    action = _text(request.get("action")).lower()
    if action not in {"set_strategy", "complete_onboarding", "reset_onboarding"}:
        raise RebuildExperienceError(
            "Choose set_strategy, complete_onboarding, or reset_onboarding."
        )

    document = _read_document(path)
    key = franchise_experience_key(checkpoint, team)
    current = document["franchises"].get(key, {})
    if not isinstance(current, dict):
        current = {}
    next_row = dict(current)

    if action == "set_strategy":
        strategy = _text(request.get("strategy"))
        if strategy not in STRATEGY_IDS:
            raise RebuildExperienceError(
                "Unknown rebuild strategy. Choose one of: "
                + ", ".join(sorted(STRATEGY_IDS))
            )
        next_row["strategy"] = strategy
    elif action == "complete_onboarding":
        next_row["onboarding_completed"] = True
        next_row["onboarding_completed_at_utc"] = _utc_now()
    elif action == "reset_onboarding":
        next_row["onboarding_completed"] = False
        next_row["onboarding_completed_at_utc"] = ""

    next_row["team"] = _text(team).upper()
    next_row["updated_at_utc"] = _utc_now()
    document["version"] = REBUILD_EXPERIENCE_VERSION
    document["updated_at_utc"] = next_row["updated_at_utc"]
    document["franchises"][key] = next_row
    _atomic_json_write(path, document)

    result = load_rebuild_experience(path, checkpoint, team)
    result["metadata_write_performed"] = True
    result["action"] = action
    return result


def _record(game_day: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(game_day.get("record"))
    wins = _integer(raw.get("wins"))
    losses = _integer(raw.get("losses"))
    games = _integer(raw.get("games_played"), wins + losses)
    return {
        "wins": wins,
        "losses": losses,
        "games": games,
        "display": _text(raw.get("display")) or f"{wins}-{losses}",
        "win_pct": round(wins / games, 4) if games else 0.0,
    }


def _young_core(
    office: Mapping[str, Any],
    goals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    development = _mapping(office.get("development"))
    candidates = _rows(development.get("full_roster"))
    goal_rows = {
        _text(row.get("player_id")): row
        for row in _rows(goals.get("goals"))
        if _text(row.get("player_id"))
    }

    rows: list[dict[str, Any]] = []
    for row in candidates:
        age = row.get("age")
        if age is None or _number(age, 99.0) > 25.0:
            continue
        overall = row.get("overall")
        potential = row.get("potential")
        growth_gap = (
            round(_number(potential) - _number(overall), 1)
            if potential is not None and overall is not None
            else None
        )
        goal = goal_rows.get(_text(row.get("player_id")), {})
        rows.append(
            {
                "player_id": _text(row.get("player_id")),
                "name": _text(row.get("name")),
                "position": _text(row.get("position")),
                "age": age,
                "overall": overall,
                "potential": potential,
                "future_outlook": row.get("future_outlook"),
                "direction": _text(row.get("direction")) or "Stable",
                "growth_gap": growth_gap,
                "goal_active": bool(goal),
                "goal_metric": _text(goal.get("metric")),
                "goal_status": _text(goal.get("status")),
                "goal_progress": goal.get("progress"),
            }
        )

    rows.sort(
        key=lambda row: (
            -_number(row.get("growth_gap"), -999.0),
            -_number(row.get("potential")),
            _number(row.get("age"), 99.0),
            -_number(row.get("overall")),
            row.get("name", ""),
        )
    )
    return rows[:6]


def _draft_asset_context(
    transactions: Mapping[str, Any],
) -> dict[str, Any]:
    draft_assets = _mapping(transactions.get("draft_assets"))
    owned = _rows(draft_assets.get("owned"))
    firsts = [row for row in owned if _integer(row.get("round"), 9) == 1]
    return {
        "owned_count": _integer(draft_assets.get("owned_count"), len(owned)),
        "first_round_count": len(firsts),
        "engine_ready_count": _integer(
            draft_assets.get("engine_ready_count")
        ),
        "manual_review_count": _integer(
            draft_assets.get("manual_review_count")
        ),
        "first_round_assets": firsts[:8],
    }


def _scouting_context(scouting: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(scouting.get("summary"))
    draft = _mapping(scouting.get("draft"))
    focus_ids = summary.get("focus_ids", [])
    if not isinstance(focus_ids, (list, tuple)):
        focus_ids = []
    return {
        "initialized": bool(scouting.get("draft_initialized", False)),
        "draft_year": draft.get("draft_year"),
        "phase": _text(draft.get("phase")),
        "available_prospects": _integer(draft.get("available_prospect_count")),
        "weeks_completed": _integer(summary.get("weeks_completed")),
        "average_confidence": summary.get("average_confidence"),
        "focus_count": len(focus_ids),
        "focus_ids": [str(value) for value in focus_ids],
        "lead_scout": _mapping(scouting.get("lead_scout")),
    }


def _transaction_count(checkpoint: Any, team: str) -> int:
    state = getattr(checkpoint, "simulation_state", None)
    rows = list(
        getattr(state, "franchise_transaction_history_v1", []) or []
    )
    count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if _text(row.get("status")).lower() != "committed":
            continue
        if _text(row.get("team_a")).upper() == team or _text(
            row.get("team_b")
        ).upper() == team:
            count += 1
    return count


def _strategy_recommendation(
    record: Mapping[str, Any],
    young_core: list[dict[str, Any]],
    draft_assets: Mapping[str, Any],
    financial: Mapping[str, Any],
) -> tuple[str, str]:
    young_upside = sum(
        1
        for row in young_core
        if _number(row.get("growth_gap")) >= 4.0
        and _number(row.get("age"), 99.0) <= 24.0
    )
    games = _integer(record.get("games"))
    win_pct = _number(record.get("win_pct"))
    firsts = _integer(draft_assets.get("first_round_count"))

    cap_room = financial.get("cap_room_estimate")
    cap_room_value = _number(cap_room, 0.0) if cap_room is not None else 0.0

    if young_upside >= 3:
        return (
            "develop_young_core",
            f"{young_upside} young players show at least four points of saved potential runway.",
        )
    if games >= 10 and win_pct >= 0.60:
        return (
            "contend_now",
            f"The current team is winning at a {win_pct:.3f} pace through {games} games.",
        )
    if games >= 10 and win_pct < 0.45 and firsts >= 1:
        return (
            "draft_rebuild",
            "The current record is below .450 and the franchise controls first-round draft capital.",
        )
    if cap_room_value > 0:
        return (
            "cap_flexibility",
            "The current financial snapshot exposes positive estimated cap room.",
        )
    return (
        "balanced",
        "No single roster-building path overwhelms the others in the current saved state.",
    )


def _journey_stage(
    stage_id: str,
    title: str,
    subtitle: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = sum(bool(task.get("complete")) for task in tasks)
    return {
        "id": stage_id,
        "title": title,
        "subtitle": subtitle,
        "tasks": tasks,
        "completed": completed,
        "total": len(tasks),
        "progress": round(completed / len(tasks), 3) if tasks else 1.0,
    }


def _journey(
    *,
    roster_count: int,
    goals: Mapping[str, Any],
    rotation: Mapping[str, Any],
    scouting: Mapping[str, Any],
    record: Mapping[str, Any],
    transaction_count: int,
    draft_assets: Mapping[str, Any],
) -> list[dict[str, Any]]:
    starters = _integer(rotation.get("starters"))
    rotation_players = _integer(rotation.get("rotation_players"))
    minutes = _number(rotation.get("total_target_minutes"))
    goal_count = len(_rows(goals.get("goals")))
    scouting_weeks = _integer(scouting.get("weeks_completed"))
    focus_count = _integer(scouting.get("focus_count"))
    games = _integer(record.get("games"))

    return [
        _journey_stage(
            "foundation",
            "FOUNDATION",
            "Know the roster and establish how your team will play.",
            [
                {
                    "id": "roster_loaded",
                    "title": "Review the active roster",
                    "complete": roster_count > 0,
                    "destination": "ROSTER",
                    "evidence": f"{roster_count} roster players are loaded.",
                },
                {
                    "id": "rotation_ready",
                    "title": "Establish a valid rotation",
                    "complete": starters == 5 and abs(minutes - 240.0) <= 0.2,
                    "destination": "ROSTER",
                    "evidence": (
                        f"{starters} starters • {rotation_players} rotation players • "
                        f"{minutes:.0f}/240 target minutes"
                    ),
                },
            ],
        ),
        _journey_stage(
            "development",
            "BUILD YOUR CORE",
            "Give young players a plan before chasing outside fixes.",
            [
                {
                    "id": "development_goals",
                    "title": "Commit season development goals",
                    "complete": bool(goals.get("committed")) and goal_count > 0,
                    "destination": "DEVELOPMENT",
                    "evidence": (
                        f"{goal_count} active goal(s)"
                        if goal_count
                        else "No season development goals are committed."
                    ),
                },
                {
                    "id": "development_sample",
                    "title": "Give development a real sample",
                    "complete": games >= 10,
                    "destination": "DEVELOPMENT",
                    "evidence": f"{games}/10 franchise games played.",
                },
            ],
        ),
        _journey_stage(
            "future",
            "BUILD THE FUTURE",
            "Turn draft information into a long-term advantage.",
            [
                {
                    "id": "scouting_week",
                    "title": "Complete a scouting week",
                    "complete": scouting_weeks > 0,
                    "destination": "SCOUTING",
                    "evidence": f"{scouting_weeks} scouting week(s) completed.",
                },
                {
                    "id": "scouting_focus",
                    "title": "Set a prospect focus",
                    "complete": focus_count > 0,
                    "destination": "SCOUTING",
                    "evidence": f"{focus_count} focused prospect(s).",
                },
                {
                    "id": "draft_assets",
                    "title": "Know your draft capital",
                    "complete": _integer(draft_assets.get("owned_count")) > 0,
                    "destination": "TRADES",
                    "evidence": (
                        f"{_integer(draft_assets.get('owned_count'))} controlled pick asset(s) • "
                        f"{_integer(draft_assets.get('first_round_count'))} first-rounder(s)"
                    ),
                },
            ],
        ),
        _journey_stage(
            "roster_building",
            "SHAPE THE ROSTER",
            "Use the market only after you understand what the internal core can become.",
            [
                {
                    "id": "standard_depth",
                    "title": "Reach a sustainable standard roster",
                    "complete": roster_count >= 14,
                    "destination": "ROSTER",
                    "evidence": f"{roster_count}/14 minimum target roster players.",
                },
                {
                    "id": "transaction_history",
                    "title": "Make a franchise-defining roster decision",
                    "complete": transaction_count > 0,
                    "destination": "TRADES",
                    "evidence": (
                        f"{transaction_count} committed franchise transaction(s)."
                        if transaction_count
                        else "No committed franchise trade is recorded yet."
                    ),
                },
            ],
        ),
        _journey_stage(
            "season",
            "PROVE IT ON COURT",
            "The rebuild only becomes real when the roster produces results.",
            [
                {
                    "id": "first_game",
                    "title": "Play the first franchise game",
                    "complete": games > 0,
                    "destination": "GAME DAY",
                    "evidence": f"{games} game(s) played.",
                },
                {
                    "id": "ten_game_identity",
                    "title": "Reach a ten-game identity sample",
                    "complete": games >= 10,
                    "destination": "PULSE",
                    "evidence": f"{games}/10 games.",
                },
            ],
        ),
    ]


def _next_moves(
    *,
    goals: Mapping[str, Any],
    young_core: list[dict[str, Any]],
    rotation: Mapping[str, Any],
    scouting: Mapping[str, Any],
    office: Mapping[str, Any],
    game_day: Mapping[str, Any],
    roster_count: int,
    phase: str,
) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []

    def add(
        priority: int,
        category: str,
        title: str,
        detail: str,
        destination: str,
        action: str,
    ) -> None:
        moves.append(
            {
                "priority": priority,
                "category": category,
                "title": title,
                "detail": detail,
                "destination": destination,
                "action": action,
            }
        )

    if not bool(goals.get("committed")):
        names = ", ".join(row["name"] for row in young_core[:3])
        detail = (
            f"Your young core starts with {names}. Commit season goals before the year gets away from you."
            if names
            else "Commit a development plan so player growth has an explicit season objective."
        )
        add(
            0,
            "BUILD YOUR CORE",
            "Set development goals first",
            detail,
            "DEVELOPMENT",
            "OPEN DEVELOPMENT HQ",
        )

    starters = _integer(rotation.get("starters"))
    minutes = _number(rotation.get("total_target_minutes"))
    if starters != 5 or abs(minutes - 240.0) > 0.2:
        add(
            1,
            "TEAM FOUNDATION",
            "Finish the rotation",
            f"Current rotation: {starters} starters and {minutes:.0f}/240 target minutes.",
            "ROSTER",
            "FIX THE ROTATION",
        )

    if bool(scouting.get("initialized")) and _integer(
        scouting.get("weeks_completed")
    ) == 0:
        add(
            2,
            "BUILD THE FUTURE",
            "Start scouting before Draft Night",
            (
                f"{_integer(scouting.get('available_prospects'))} prospects are available "
                "and no scouting week has been completed."
            ),
            "SCOUTING",
            "OPEN SCOUTING",
        )
    elif bool(scouting.get("initialized")) and _integer(
        scouting.get("focus_count")
    ) == 0:
        add(
            2,
            "BUILD THE FUTURE",
            "Choose scouting priorities",
            "The scouting board is active but no focus prospects are selected.",
            "SCOUTING",
            "SET DRAFT FOCUS",
        )

    morale = _mapping(office.get("morale"))
    attention_count = _integer(morale.get("attention_count"))
    if attention_count > 0:
        add(
            2,
            "LOCKER ROOM",
            "Handle player concerns",
            f"{attention_count} player(s) currently need morale or role attention.",
            "LOCKER ROOM",
            "OPEN LOCKER ROOM",
        )

    if roster_count < 14:
        destination = "FREE AGENCY" if phase == "offseason" else "TRADES"
        add(
            2,
            "ROSTER BUILDING",
            "Add sustainable roster depth",
            f"Only {roster_count} active roster players are loaded.",
            destination,
            "EXPLORE THE MARKET",
        )

    next_game = _mapping(game_day.get("next_game"))
    if next_game:
        add(
            3,
            "NEXT GAME",
            f"Prepare for {_text(next_game.get('opponent_name')) or 'your opponent'}",
            (
                f"League day {_integer(next_game.get('day_index'))}. "
                "Review the matchup, rotation and coaching intelligence before simulating."
            ),
            "GAME DAY",
            "OPEN GAME PLAN",
        )

    if "offseason" in phase or "draft" in phase:
        add(
            1,
            "OFFSEASON",
            "Run the rebuild cycle",
            "The franchise is in an offseason or Draft phase. Use the Offseason hub to keep the lifecycle coherent.",
            "OFFSEASON",
            "OPEN OFFSEASON",
        )

    if not moves:
        add(
            5,
            "FRANCHISE",
            "Review the weekly pulse",
            "Core setup is healthy. Use Franchise Pulse to see what changed and where the next meaningful decision is forming.",
            "PULSE",
            "OPEN PULSE",
        )

    moves.sort(key=lambda row: (row["priority"], row["category"], row["title"]))
    for index, row in enumerate(moves[:5], start=1):
        row["rank"] = index
    return moves[:5]


def _feature_guides(
    *,
    goals: Mapping[str, Any],
    scouting: Mapping[str, Any],
    phase: str,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in FEATURE_GUIDES]

    # Development is deliberately the first tutorial surface for a rebuild.
    for row in rows:
        if row["id"] == "development":
            row["status"] = (
                "ACTIVE GOALS"
                if bool(goals.get("committed"))
                else "RECOMMENDED FIRST STOP"
            )
        elif row["id"] == "scouting":
            row["status"] = (
                f"{_integer(scouting.get('weeks_completed'))} WEEK(S) COMPLETE"
                if bool(scouting.get("initialized"))
                else "DRAFT STATE NOT INITIALIZED"
            )
        elif row["id"] == "offseason":
            row["status"] = (
                "ACTIVE PHASE"
                if "offseason" in phase or "draft" in phase
                else "AVAILABLE WHEN NEEDED"
            )
        else:
            row["status"] = "AVAILABLE"
    return rows


def build_rebuild_hq_payload(
    checkpoint: Any,
    active_team: str,
    *,
    roster_payload: Mapping[str, Any],
    office_payload: Mapping[str, Any],
    game_day_payload: Mapping[str, Any],
    scouting_payload: Mapping[str, Any],
    transaction_payload: Mapping[str, Any],
    experience: Mapping[str, Any],
    team_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    team_names = dict(team_names or {})
    team = _text(active_team).upper()
    state = getattr(checkpoint, "simulation_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if team not in getattr(state, "teams", {}):
        raise ValueError(f"Unknown active franchise: {team or '<blank>'}.")

    roster = dict(roster_payload or {})
    office = dict(office_payload or {})
    game_day = dict(game_day_payload or {})
    scouting = _scouting_context(dict(scouting_payload or {}))
    transactions = dict(transaction_payload or {})
    goals: dict[str, Any] = {}
    # The server may pass the current goals board through the office payload's
    # Expansion 49 envelope to avoid the foundation importing write-authority code.
    if isinstance(office.get("development_goals"), Mapping):
        goals = dict(office["development_goals"])

    record = _record(game_day)
    young_core = _young_core(office, goals)
    financial = _mapping(office.get("financial"))
    rotation = _mapping(office.get("rotation"))
    draft_assets = _draft_asset_context(transactions)
    roster_count = len(_rows(roster.get("players")))
    transaction_count = _transaction_count(checkpoint, team)
    phase = _text(
        getattr(
            getattr(state, "phase", ""),
            "value",
            getattr(state, "phase", ""),
        )
    ).lower()
    season = _text(getattr(getattr(state, "settings", None), "season_label", ""))
    day = _integer(getattr(state, "current_day_index", 0))

    recommended_strategy, recommendation_reason = _strategy_recommendation(
        record,
        young_core,
        draft_assets,
        financial,
    )
    saved_strategy = _text(experience.get("strategy"))
    active_strategy = (
        saved_strategy if saved_strategy in STRATEGY_IDS else recommended_strategy
    )
    strategy_source = "user" if saved_strategy in STRATEGY_IDS else "recommended"

    strategy_choices = []
    for row in STRATEGIES:
        choice = dict(row)
        choice["selected"] = row["id"] == active_strategy
        choice["recommended"] = row["id"] == recommended_strategy
        strategy_choices.append(choice)

    journey = _journey(
        roster_count=roster_count,
        goals=goals,
        rotation=rotation,
        scouting=scouting,
        record=record,
        transaction_count=transaction_count,
        draft_assets=draft_assets,
    )
    journey_completed = sum(row["completed"] for row in journey)
    journey_total = sum(row["total"] for row in journey)

    return {
        "foundation_version": REBUILD_EXPERIENCE_VERSION,
        "source": "v3_working_checkpoint + desktop_ux_metadata",
        "read_only_franchise_state": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "desktop_metadata_only": True,
        "team": team,
        "team_name": team_names.get(team, team),
        "season": season,
        "phase": phase,
        "day": day,
        "record": record,
        "strategy": {
            "active": active_strategy,
            "source": strategy_source,
            "recommended": recommended_strategy,
            "recommendation_reason": recommendation_reason,
            "choices": strategy_choices,
        },
        "young_core": young_core,
        "opportunity_lab": opportunity_board(checkpoint, team),
        "development": {
            "committed": bool(goals.get("committed")),
            "can_commit": bool(goals.get("can_commit")),
            "active_goal_count": len(_rows(goals.get("goals"))),
            "slots": _integer(goals.get("slots"), 3),
            "rules": _text(goals.get("rules")),
        },
        "roster": {
            "count": roster_count,
            "rotation": rotation,
            "financial": financial,
            "morale": _mapping(office.get("morale")),
            "team_health": _mapping(office.get("team_health")),
        },
        "scouting": scouting,
        "draft_assets": draft_assets,
        "next_game": _mapping(game_day.get("next_game")),
        "next_moves": _next_moves(
            goals=goals,
            young_core=young_core,
            rotation=rotation,
            scouting=scouting,
            office=office,
            game_day=game_day,
            roster_count=roster_count,
            phase=phase,
        ),
        "journey": {
            "stages": journey,
            "completed": journey_completed,
            "total": journey_total,
            "progress": (
                round(journey_completed / journey_total, 3)
                if journey_total
                else 1.0
            ),
        },
        "feature_guides": _feature_guides(
            goals=goals,
            scouting=scouting,
            phase=phase,
        ),
        "experience": dict(experience or {}),
        "navigation": {
            "primary_sidebar": [
                "HOME",
                "REBUILD HQ",
                "INBOX",
                "DEVELOPMENT",
                "ROSTER",
                "LOCKER ROOM",
                "GAME DAY",
                "SEASON",
                "SCOUTING",
                "TRADES",
                "FREE AGENCY",
                "OFFSEASON",
                "LEAGUE",
                "LEGACY",
                "FRANCHISES",
                "SETTINGS",
            ],
            "contextual_only": [
                "PULSE",
                "THEATER",
                "STORIES",
                "FRONT OFFICE",
            ],
            "note": (
                "Deep modules remain available through contextual actions even when "
                "they are removed from permanent sidebar navigation."
            ),
        },
        "scope": {
            "strategy_is_ux_metadata": True,
            "journey_is_evidence_derived": True,
            "ratings_changed": False,
            "rotation_changed": False,
            "transaction_executed": False,
            "franchise_checkpoint_written": False,
            "note": (
                "Rebuild HQ directs attention to existing production systems. "
                "It does not grant development, alter ratings, make trades, sign players, "
                "change rotation minutes, or advance the franchise."
            ),
        },
    }
