from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ORCHESTRATOR_VERSION = (
    "franchise-cpu-post-draft-roster-trim-guarded-orchestrator-foundation-v1-2026-08-17"
)
POST_DRAFT_OFFSEASON_ROSTER_CEILING = 21
ORCHESTRATOR_CANONICAL_EXECUTION_ENABLED = False
CERTIFIED_AUTOMATIC_FINANCIAL_ROUTES = frozenset(
    {
        "exact_full_current_salary_one_year_guarantee",
        "exact_non_guaranteed_release",
    }
)


class CPUPostDraftTrimOrchestratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CPUPostDraftTrimSelectedRelease:
    team: str
    player_id: str
    player_name: str
    retention_score: float
    score_rationale: tuple[str, ...]
    financial_treatment: str
    release_status: str
    certified_for_clone_execution: bool
    release_blockers: tuple[str, ...]


@dataclass(frozen=True)
class CPUPostDraftTrimTeamPreview:
    version: str
    team: str
    cpu_managed: bool
    roster_count_before: int
    target_roster_size: int
    required_cut_count: int
    selected_cut_count: int
    roster_count_after_preview: int
    status: str
    selected_releases: tuple[CPUPostDraftTrimSelectedRelease, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CPUPostDraftTrimLeaguePreview:
    version: str
    target_roster_size: int
    controlled_teams: tuple[str, ...]
    phase: str
    team_previews: tuple[CPUPostDraftTrimTeamPreview, ...]
    overflow_cpu_team_count: int
    executable_cpu_team_count: int
    manual_review_team_count: int
    user_controlled_overflow_team_count: int


@dataclass(frozen=True)
class CPUPostDraftTrimCloneExecutionResult:
    version: str
    checkpoint_path: str
    team: str
    roster_count_before: int
    roster_count_after: int
    executed_transaction_ids: tuple[str, ...]
    released_player_ids: tuple[str, ...]
    final_status: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _pid(value: Any) -> str:
    return _clean(value)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _attr(value: Any, names: Iterable[str], default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _bool_attr(value: Any, names: Iterable[str]) -> bool:
    raw = _attr(value, names, None)
    if raw is None:
        return False
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(raw)


def _phase(state: Any) -> str:
    value = _clean(_attr(_attr(state, ("settings",), None), ("phase",), ""))
    if not value:
        value = _clean(_attr(state, ("phase",), ""))
    return value.lower()


def _team_roster_ids(state: Any, team_code: str) -> tuple[str, ...]:
    teams = getattr(state, "teams", {}) or {}
    team_state = teams.get(team_code)
    if team_state is None:
        return ()
    return tuple(
        _pid(value)
        for value in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if _pid(value)
    )


def _rotation_ids(team_state: Any) -> set[str]:
    if team_state is None:
        return set()
    rotation = getattr(team_state, "rotation", None)
    if rotation is None:
        return set()
    out: set[str] = set()
    for attr in ("starter_ids", "rotation_player_ids"):
        out.update(
            _pid(value)
            for value in tuple(getattr(rotation, attr, ()) or ())
            if _pid(value)
        )
    minutes = getattr(rotation, "minutes_by_player_id", None)
    if isinstance(minutes, Mapping):
        for key, value in minutes.items():
            amount = _finite(value) or 0.0
            if amount > 0 and _pid(key):
                out.add(_pid(key))
    return out


def _player_name(player: Any, player_id_value: str) -> str:
    return _clean(
        _attr(
            player,
            ("player_name", "name", "display_name", "full_name"),
            player_id_value,
        )
    ) or player_id_value


def _player_draft_year(player: Any) -> int | None:
    value = _attr(
        player,
        ("draft_year", "generated_draft_year", "rookie_draft_year"),
        None,
    )
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_generated(player: Any) -> bool:
    if _bool_attr(
        player,
        ("generated_player", "is_generated_player", "generated", "is_generated"),
    ):
        return True
    source = _clean(
        _attr(
            player,
            ("source", "player_source", "origin", "contract_model"),
            "",
        )
    ).lower()
    return any(
        token in source
        for token in ("generated", "draft_engine", "rookie_scale_generated")
    )


def _is_synthetic(player: Any) -> bool:
    if _bool_attr(
        player,
        ("synthetic", "is_synthetic", "synthetic_player", "is_synthetic_player"),
    ):
        return True
    source = _clean(
        _attr(player, ("source", "player_source", "origin"), "")
    ).lower()
    return "synthetic" in source


def _latest_generated_draft_year(state: Any) -> int | None:
    players = getattr(state, "players", {}) or {}
    years: list[int] = []
    for team_state in (getattr(state, "teams", {}) or {}).values():
        for value in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
            player = players.get(_pid(value))
            if player is None or not _is_generated(player):
                continue
            year = _player_draft_year(player)
            if year is not None:
                years.append(year)
    return max(years) if years else None


def _extract_team_plans(league_plan: Any) -> dict[str, Any]:
    for name in (
        "team_plans",
        "plans",
        "plans_by_team",
        "team_plan_by_team",
        "teams",
    ):
        value = getattr(league_plan, name, None)
        if isinstance(value, Mapping):
            out = {_team(key): item for key, item in value.items() if _team(key)}
            if out:
                return out
        if isinstance(value, (list, tuple)):
            out: dict[str, Any] = {}
            for item in value:
                code = _team(
                    _attr(
                        item,
                        ("team", "team_abbreviation", "team_code", "abbreviation"),
                        "",
                    )
                )
                if code:
                    out[code] = item
            if out:
                return out
    if hasattr(league_plan, "__dict__"):
        for value in vars(league_plan).values():
            if isinstance(value, Mapping):
                out = {_team(key): item for key, item in value.items() if _team(key)}
                if len(out) >= 20:
                    return out
    return {}


def _decision_map(team_plan: Any) -> dict[str, Any]:
    raw = _attr(
        team_plan,
        ("player_decisions", "roster_decisions", "decisions"),
        (),
    )
    out: dict[str, Any] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            player_id = _pid(_attr(value, ("player_id", "id"), key))
            if player_id:
                out[player_id] = value
        return out
    for value in tuple(raw or ()):
        player_id = _pid(_attr(value, ("player_id", "id"), ""))
        if player_id:
            out[player_id] = value
    return out


def _role_label(player: Any, decision: Any) -> str:
    return _clean(
        _attr(
            decision,
            ("role", "player_role", "projected_role", "roster_role"),
            _attr(player, ("role", "player_role", "projected_role"), ""),
        )
    )


def _contract_cut_cost(player: Any) -> tuple[bool | None, float]:
    contract = getattr(player, "contract", None)
    if contract is None:
        return None, 0.0
    salary = _finite(
        _attr(contract, ("salary", "annual_salary", "current_salary", "cap_hit"), 0.0)
    ) or 0.0
    years_raw = _attr(
        contract,
        ("years_remaining", "remaining_years", "years", "contract_years_remaining"),
        None,
    )
    try:
        years = max(0, int(years_raw)) if years_raw is not None else None
    except (TypeError, ValueError):
        years = None

    guaranteed_raw = _attr(
        contract,
        ("guaranteed", "is_guaranteed", "fully_guaranteed"),
        None,
    )
    guaranteed = None
    if guaranteed_raw is not None:
        guaranteed = _bool_attr(
            contract,
            ("guaranteed", "is_guaranteed", "fully_guaranteed"),
        )

    guaranteed_remaining = _finite(
        _attr(
            contract,
            (
                "guaranteed_remaining",
                "remaining_guaranteed_salary",
                "guaranteed_salary_remaining",
                "guaranteed_amount",
                "guaranteed_salary",
            ),
            None,
        )
    )
    dead_money = _finite(
        _attr(
            contract,
            ("dead_money", "dead_cap", "waive_dead_money", "release_dead_money"),
            None,
        )
    )

    if dead_money is not None:
        cost = max(0.0, dead_money)
    elif guaranteed_remaining is not None:
        cost = max(0.0, guaranteed_remaining)
    elif guaranteed is False:
        cost = 0.0
    elif guaranteed is True:
        cost = max(0.0, salary * max(1, years or 1))
    else:
        cost = 0.0
    return guaranteed, cost


def _intrinsic_value(front: Any, player: Any) -> float | None:
    fn = getattr(front, "intrinsic_player_value", None)
    if not callable(fn):
        return None
    try:
        value = _finite(fn(player))
    except Exception:
        return None
    return value


def _rank_team_candidates(
    *,
    state: Any,
    front: Any,
    team_code: str,
    team_plan: Any,
) -> list[dict[str, Any]]:
    players = getattr(state, "players", {}) or {}
    team_state = (getattr(state, "teams", {}) or {}).get(team_code)
    roster_ids = _team_roster_ids(state, team_code)
    decisions = _decision_map(team_plan)
    existing_cut_ids = {
        _pid(value)
        for value in tuple(_attr(team_plan, ("cut_candidate_ids",), ()) or ())
        if _pid(value)
    }
    protected_ids = {
        _pid(value)
        for value in tuple(_attr(team_plan, ("protected_player_ids",), ()) or ())
        if _pid(value)
    }
    rotation_ids = _rotation_ids(team_state)
    latest_generated_year = _latest_generated_draft_year(state)

    rows: list[dict[str, Any]] = []
    for player_id in roster_ids:
        player = players.get(player_id)
        if player is None:
            rows.append(
                {
                    "player_id": player_id,
                    "player_name": player_id,
                    "eligible": False,
                    "hard_protection_reasons": ("missing_player_record",),
                    "retention_score": 9999.0,
                    "score_rationale": ("missing_player_record",),
                }
            )
            continue

        decision = decisions.get(player_id)
        role = _role_label(player, decision)
        market_stance = _clean(
            _attr(decision, ("market_stance", "roster_stance", "decision"), "")
        )
        roster_fit = _clean(
            _attr(decision, ("roster_fit", "fit_label", "roster_fit_label"), "")
        )
        generated = _is_generated(player)
        synthetic = _is_synthetic(player)
        draft_year = _player_draft_year(player)
        explicit_cut = (
            player_id in existing_cut_ids
            or market_stance.lower() == "waive/cut candidate"
            or "waive/cut" in market_stance.lower()
        )
        listed_protected = player_id in protected_ids
        in_rotation = player_id in rotation_ids
        role_lower = role.lower()

        current_generated_rookie = generated and (
            draft_year is None
            or latest_generated_year is None
            or draft_year == latest_generated_year
        )

        protections: list[str] = []
        if synthetic:
            protections.append("synthetic_player")
        if current_generated_rookie:
            protections.append("current_or_unresolved_generated_rookie")
        if listed_protected and not explicit_cut:
            protections.append("front_office_protected")
        if role_lower in {"cornerstone", "core"} and not explicit_cut:
            protections.append("core_role")
        if in_rotation and not explicit_cut:
            protections.append("active_rotation")
        if role_lower in {"starter", "rotation"} and not explicit_cut:
            protections.append("starter_or_rotation_role")
        if roster_fit.lower() == "need protection" and not explicit_cut:
            protections.append("need_protection_fit")

        intrinsic = _intrinsic_value(front, player)
        overall = _finite(
            _attr(player, ("overall_rating", "overall", "ovr"), None)
        )
        retention = intrinsic if intrinsic is not None else (overall or 60.0)
        reasons: list[str] = []

        if explicit_cut:
            retention -= 18.0
            reasons.append("existing_cpu_model_cut_signal:-18")
        if "surplus" in roster_fit.lower():
            retention -= 6.0
            reasons.append("roster_surplus:-6")
        if "fringe" in role_lower:
            retention -= 5.0
            reasons.append("fringe_role:-5")
        if generated and not current_generated_rookie:
            retention += 6.0
            reasons.append("generated_player_runway:+6")

        guaranteed, cut_cost = _contract_cut_cost(player)
        if cut_cost > 0.0:
            penalty = min(
                18.0,
                4.0 + 2.0 * math.log10(1.0 + cut_cost / 1_000_000.0),
            )
            retention += penalty
            reasons.append(f"guarantee_dead_money_penalty:+{penalty:.3f}")
        if guaranteed is False:
            retention -= 4.0
            reasons.append("explicit_non_guaranteed_contract:-4")
        if protections:
            retention += 1000.0
            reasons.append("hard_protection:+1000")

        rows.append(
            {
                "player_id": player_id,
                "player_name": _player_name(player, player_id),
                "eligible": not protections,
                "hard_protection_reasons": tuple(protections),
                "retention_score": round(retention, 4),
                "score_rationale": tuple(reasons),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            not bool(row["eligible"]),
            float(row["retention_score"]),
            row["player_name"],
            row["player_id"],
        ),
    )


def _controlled_teams(checkpoint: Any) -> tuple[str, ...]:
    from franchise_free_agency_live_signing_v1 import (
        controlled_teams_from_durable_checkpoint,
    )

    return tuple(
        dict.fromkeys(
            _team(value)
            for value in controlled_teams_from_durable_checkpoint(checkpoint)
            if _team(value)
        )
    )


def build_cpu_post_draft_trim_league_preview(
    checkpoint: Any,
) -> CPUPostDraftTrimLeaguePreview:
    simulation_state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if simulation_state is None or trade_state is None:
        raise CPUPostDraftTrimOrchestratorError(
            "Durable checkpoint must expose simulation_state and trade_state."
        )

    phase = _phase(simulation_state)
    controlled = _controlled_teams(checkpoint)
    controlled_set = set(controlled)

    import franchise_cpu_front_office_v1 as front
    import franchise_cpu_post_draft_roster_trim_release_v1 as release

    league_plan = front.build_league_front_office_plan(
        simulation_state,
        controlled_teams=controlled,
    )
    plans = _extract_team_plans(league_plan)
    if not plans:
        raise CPUPostDraftTrimOrchestratorError(
            "Could not recover per-team front-office plans."
        )

    team_previews: list[CPUPostDraftTrimTeamPreview] = []
    overflow_cpu = 0
    executable = 0
    manual_review = 0
    user_overflow = 0

    teams = getattr(simulation_state, "teams", {}) or {}
    for team_code in sorted(_team(value) for value in teams if _team(value)):
        roster_count = len(_team_roster_ids(simulation_state, team_code))
        required = max(
            0,
            roster_count - POST_DRAFT_OFFSEASON_ROSTER_CEILING,
        )
        cpu_managed = team_code not in controlled_set
        blockers: list[str] = []
        selections: list[CPUPostDraftTrimSelectedRelease] = []

        if required == 0:
            status = "no_trim_required"
        elif not cpu_managed:
            status = "user_controlled_overflow_requires_user_decision"
            blockers.append(
                f"{team_code} is user-controlled; CPU trim execution is prohibited."
            )
            user_overflow += 1
        elif "offseason" not in phase:
            status = "blocked_not_offseason"
            blockers.append("CPU post-Draft roster trimming is offseason-only.")
            manual_review += 1
        else:
            overflow_cpu += 1
            ranked = _rank_team_candidates(
                state=simulation_state,
                front=front,
                team_code=team_code,
                team_plan=plans.get(team_code),
            )
            eligible = [row for row in ranked if row["eligible"]]
            chosen = eligible[:required]
            if len(chosen) < required:
                status = "blocked_insufficient_eligible_candidates"
                blockers.append(
                    f"{team_code} needs {required} release(s) but only "
                    f"{len(chosen)} eligible candidate(s) exist."
                )
                manual_review += 1
            else:
                all_certified = True
                for row in chosen:
                    preview = release.build_cpu_post_draft_release_preview(
                        checkpoint,
                        team=team_code,
                        player_id=row["player_id"],
                        rationale=row["score_rationale"],
                    )
                    certified = (
                        preview.status == "pass"
                        and preview.can_commit_to_clone
                        and preview.financial_treatment
                        in CERTIFIED_AUTOMATIC_FINANCIAL_ROUTES
                    )
                    if not certified:
                        all_certified = False
                    selections.append(
                        CPUPostDraftTrimSelectedRelease(
                            team=team_code,
                            player_id=row["player_id"],
                            player_name=row["player_name"],
                            retention_score=float(row["retention_score"]),
                            score_rationale=tuple(row["score_rationale"]),
                            financial_treatment=preview.financial_treatment,
                            release_status=preview.status,
                            certified_for_clone_execution=certified,
                            release_blockers=tuple(preview.blockers),
                        )
                    )
                if all_certified:
                    status = "cpu_trim_plan_executable_on_clone"
                    executable += 1
                else:
                    status = "cpu_trim_plan_requires_manual_review"
                    blockers.append(
                        "At least one selected release is blocked or outside "
                        "the certified automatic financial routes."
                    )
                    manual_review += 1

        team_previews.append(
            CPUPostDraftTrimTeamPreview(
                version=ORCHESTRATOR_VERSION,
                team=team_code,
                cpu_managed=cpu_managed,
                roster_count_before=roster_count,
                target_roster_size=POST_DRAFT_OFFSEASON_ROSTER_CEILING,
                required_cut_count=required,
                selected_cut_count=len(selections),
                roster_count_after_preview=roster_count - len(selections),
                status=status,
                selected_releases=tuple(selections),
                blockers=tuple(blockers),
            )
        )

    return CPUPostDraftTrimLeaguePreview(
        version=ORCHESTRATOR_VERSION,
        target_roster_size=POST_DRAFT_OFFSEASON_ROSTER_CEILING,
        controlled_teams=controlled,
        phase=phase,
        team_previews=tuple(team_previews),
        overflow_cpu_team_count=overflow_cpu,
        executable_cpu_team_count=executable,
        manual_review_team_count=manual_review,
        user_controlled_overflow_team_count=user_overflow,
    )


def build_cpu_post_draft_trim_team_preview(
    checkpoint: Any,
    team: str,
) -> CPUPostDraftTrimTeamPreview:
    code = _team(team)
    league = build_cpu_post_draft_trim_league_preview(checkpoint)
    matches = [item for item in league.team_previews if item.team == code]
    if len(matches) != 1:
        raise CPUPostDraftTrimOrchestratorError(
            f"Could not resolve team preview for {code}."
        )
    return matches[0]


def _load_checkpoint(path: Path) -> Any:
    import simulation_franchise_checkpoint_v1 as cp

    checkpoint = cp.load_franchise_checkpoint(
        path=path,
        allow_backup=False,
    )
    if checkpoint is None:
        raise CPUPostDraftTrimOrchestratorError(
            f"Checkpoint could not be loaded: {path}"
        )
    return checkpoint


def execute_cpu_post_draft_trim_on_clone(
    *,
    checkpoint_path: str | Path,
    team: str,
    inject_failure_after_first_verified_save: bool = False,
) -> CPUPostDraftTrimCloneExecutionResult:
    """
    Execute certified CPU roster trims ONLY on a non-canonical checkpoint clone.

    Canonical automatic execution remains hard-disabled in Foundation V1.
    """
    import simulation_franchise_checkpoint_v1 as cp
    import franchise_cpu_post_draft_roster_trim_release_v1 as release

    path = Path(checkpoint_path).resolve()
    canonical = Path(cp.DEFAULT_CHECKPOINT_PATH).resolve()
    if path == canonical:
        raise CPUPostDraftTrimOrchestratorError(
            "Canonical CPU trim orchestration is disabled in Foundation V1."
        )
    if not path.exists():
        raise CPUPostDraftTrimOrchestratorError(
            "Clone checkpoint path does not exist."
        )

    team_code = _team(team)
    checkpoint = _load_checkpoint(path)
    first_preview = build_cpu_post_draft_trim_team_preview(
        checkpoint,
        team_code,
    )
    before = first_preview.roster_count_before

    if first_preview.required_cut_count == 0:
        return CPUPostDraftTrimCloneExecutionResult(
            version=ORCHESTRATOR_VERSION,
            checkpoint_path=str(path),
            team=team_code,
            roster_count_before=before,
            roster_count_after=before,
            executed_transaction_ids=(),
            released_player_ids=(),
            final_status="no_trim_required",
        )
    if first_preview.status != "cpu_trim_plan_executable_on_clone":
        raise CPUPostDraftTrimOrchestratorError(
            f"{team_code} trim preview is not executable: "
            f"{first_preview.status}; blockers={list(first_preview.blockers)}"
        )

    tx_ids: list[str] = []
    released_ids: list[str] = []
    inject = bool(inject_failure_after_first_verified_save)

    while True:
        checkpoint = _load_checkpoint(path)
        preview = build_cpu_post_draft_trim_team_preview(
            checkpoint,
            team_code,
        )
        if preview.required_cut_count == 0:
            break
        if preview.status != "cpu_trim_plan_executable_on_clone":
            raise CPUPostDraftTrimOrchestratorError(
                "Trim sequence became non-executable after a prior release: "
                f"{preview.status}; blockers={list(preview.blockers)}"
            )
        if not preview.selected_releases:
            raise CPUPostDraftTrimOrchestratorError(
                "Executable trim preview contains no selected release."
            )

        selected = preview.selected_releases[0]
        release_preview = release.build_cpu_post_draft_release_preview(
            checkpoint,
            team=team_code,
            player_id=selected.player_id,
            rationale=selected.score_rationale,
        )
        if (
            release_preview.status != "pass"
            or not release_preview.can_commit_to_clone
            or release_preview.financial_treatment
            not in CERTIFIED_AUTOMATIC_FINANCIAL_ROUTES
        ):
            raise CPUPostDraftTrimOrchestratorError(
                "Selected release failed the final installed release-module gate."
            )

        try:
            durable = release.commit_cpu_post_draft_release_clone_durably(
                release_preview,
                checkpoint_path=path,
                inject_failure_after_verified_save=inject,
            )
        finally:
            inject = False

        tx_ids.append(durable.transaction_id)
        released_ids.append(selected.player_id)

    final_checkpoint = _load_checkpoint(path)
    final_preview = build_cpu_post_draft_trim_team_preview(
        final_checkpoint,
        team_code,
    )
    if final_preview.roster_count_before > POST_DRAFT_OFFSEASON_ROSTER_CEILING:
        raise CPUPostDraftTrimOrchestratorError(
            "Clone trim execution finished above the 21-player ceiling."
        )

    return CPUPostDraftTrimCloneExecutionResult(
        version=ORCHESTRATOR_VERSION,
        checkpoint_path=str(path),
        team=team_code,
        roster_count_before=before,
        roster_count_after=final_preview.roster_count_before,
        executed_transaction_ids=tuple(tx_ids),
        released_player_ids=tuple(released_ids),
        final_status=final_preview.status,
    )


def orchestrator_contract_report() -> dict[str, Any]:
    return {
        "version": ORCHESTRATOR_VERSION,
        "post_draft_offseason_roster_ceiling": POST_DRAFT_OFFSEASON_ROSTER_CEILING,
        "canonical_execution_enabled": ORCHESTRATOR_CANONICAL_EXECUTION_ENABLED,
        "certified_automatic_financial_routes": sorted(
            CERTIFIED_AUTOMATIC_FINANCIAL_ROUTES
        ),
        "public_functions": [
            "build_cpu_post_draft_trim_league_preview",
            "build_cpu_post_draft_trim_team_preview",
            "execute_cpu_post_draft_trim_on_clone",
            "orchestrator_contract_report",
        ],
        "canonical_path_hard_blocked": True,
        "controlled_team_resolver": (
            "franchise_free_agency_live_signing_v1."
            "controlled_teams_from_durable_checkpoint"
        ),
        "release_transaction_authority": (
            "franchise_cpu_post_draft_roster_trim_release_v1."
            "commit_cpu_post_draft_release_clone_durably"
        ),
        "user_controlled_auto_release_allowed": False,
        "uncertified_financial_route_auto_release_allowed": False,
    }
