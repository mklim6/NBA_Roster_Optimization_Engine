from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from franchise_coaching_matchup_tactics_v1 import (
    MAX_DEFENSIVE_SUPPRESSION_POINTS,
    SCHEME_BALANCED,
    SCHEME_LABELS,
    SCHEME_LOAD_CREATOR,
    SCHEME_MATCH_SIZE,
    SCHEME_PACK_PAINT,
    SCHEME_STAY_HOME,
    SCHEME_SWITCH,
    _coach_execution,
    _normalized_capacity,
    _personnel_capacities,
    _scheme_utility,
    choose_defensive_tactical_counter_v1,
    opponent_threat_profile_v1,
)
from franchise_staff_system_v1 import (
    ROLE_ASSISTANT_COACH,
    ROLE_HEAD_COACH,
    ensure_franchise_staff_state,
    team_staff,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from single_game_simulator_v1 import (
    GameSimulationConfig,
    build_team_game_plan,
)


AUDIT_VERSION = "franchise-v2-coaching-counterfactual-audit-v1-2026-09-30"

SCHEMES = (
    SCHEME_LOAD_CREATOR,
    SCHEME_PACK_PAINT,
    SCHEME_STAY_HOME,
    SCHEME_SWITCH,
    SCHEME_MATCH_SIZE,
)

# The point of these profiles is not to claim real-world coach behavior.
# They are deliberately separated simulated franchise styles that exercise
# the bounded trait-preference layer while holding ratings and personnel fixed.
COUNTERFACTUAL_STAFF_PROFILES = {
    "switch_aggressive": {
        "head": ("Youth trust", "Defensive edge"),
        "assistant": ("Defense lab", "Analytics"),
    },
    "paint_size_control": {
        "head": ("Tempo control", "Veteran trust"),
        "assistant": ("Rotation detail", "Communication"),
    },
    "shooter_discipline": {
        "head": ("Discipline", "Player-first"),
        "assistant": ("Shooting development", "Analytics"),
    },
    "creator_detail": {
        "head": ("Half-court detail", "Discipline"),
        "assistant": ("Opponent prep", "Communication"),
    },
}

CLOSE_CALL_EXECUTION_GAP = 0.040
STRONG_CALL_EXECUTION_GAP = 0.120
MIN_STRONG_CALL_STABILITY = 0.95
MIN_CLOSE_CALLS_FOR_RATE_GATE = 20
MIN_CLOSE_CALL_DIFFERENTIATION_RATE = 0.02
MIN_TOTAL_DIFFERENTIATED_MATCHUPS = 1


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _decision_board(state: Any, defending_plan: Any, opponent_plan: Any) -> list[dict[str, Any]]:
    threat = opponent_threat_profile_v1(state, opponent_plan)
    capacities = _personnel_capacities(state, defending_plan)
    coach_execution = _coach_execution(
        state,
        _clean(getattr(defending_plan, "team_abbreviation", "")).upper(),
    )

    rows = []
    for scheme in SCHEMES:
        raw_utility = float(_scheme_utility(threat, scheme))
        capacity = float(capacities[scheme])
        raw_execution = (
            max(0.0, raw_utility)
            * float(_normalized_capacity(capacity))
            * float(coach_execution)
        )
        rows.append({
            "scheme": scheme,
            "raw_utility": raw_utility,
            "capacity": capacity,
            "raw_execution": raw_execution,
        })

    rows.sort(
        key=lambda row: (
            -float(row["raw_execution"]),
            -float(row["raw_utility"]),
            -float(row["capacity"]),
            str(row["scheme"]),
        )
    )
    return rows


def _archetype_states(source: Any) -> dict[str, Any]:
    states = {}
    for profile_name, profile in COUNTERFACTUAL_STAFF_PROFILES.items():
        candidate = copy.deepcopy(source)
        ensure_franchise_staff_state(candidate)

        for team in sorted(candidate.teams):
            staff = team_staff(candidate, team, ensure=True)
            if staff is None:
                continue
            head = staff.members.get(ROLE_HEAD_COACH)
            assistant = staff.members.get(ROLE_ASSISTANT_COACH)
            if head is not None:
                head.traits = tuple(profile["head"])
            if assistant is not None:
                assistant.traits = tuple(profile["assistant"])

        states[profile_name] = candidate
    return states


def _plan_map(state: Any, config: GameSimulationConfig) -> dict[str, Any]:
    plans = {}
    for team in sorted(state.teams):
        try:
            plan = build_team_game_plan(
                state,
                team,
                sit_player_ids=set(),
                overtime_periods=0,
                config=config,
            )
        except Exception:
            continue

        if len(tuple(getattr(plan, "player_ids", ()) or ())) >= 5:
            plans[team] = plan

    return plans


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    source = checkpoint.simulation_state
    config = GameSimulationConfig()

    source_plans = _plan_map(source, config)
    if len(source_plans) < 20:
        raise RuntimeError(
            f"Only {len(source_plans)} teams exposed valid current game plans; "
            "counterfactual audit requires at least 20."
        )

    archetype_states = _archetype_states(source)

    # Ratings must be identical between source and every protected staff profile.
    rating_integrity = True
    for profile_state in archetype_states.values():
        for team in source_plans:
            original_staff = team_staff(source, team, ensure=False)
            altered_staff = team_staff(profile_state, team, ensure=False)
            if original_staff is None or altered_staff is None:
                continue
            for role in (ROLE_HEAD_COACH, ROLE_ASSISTANT_COACH):
                original = original_staff.members.get(role)
                altered = altered_staff.members.get(role)
                if original is None or altered is None:
                    continue
                original_ratings = (
                    original.offense_rating,
                    original.defense_rating,
                    original.player_development_rating,
                    original.rotation_management_rating,
                    original.adaptability_rating,
                )
                altered_ratings = (
                    altered.offense_rating,
                    altered.defense_rating,
                    altered.player_development_rating,
                    altered.rotation_management_rating,
                    altered.adaptability_rating,
                )
                if original_ratings != altered_ratings:
                    rating_integrity = False

    scenarios = []
    scheme_counts = {
        profile: Counter()
        for profile in COUNTERFACTUAL_STAFF_PROFILES
    }
    invalid_negative_choices = []
    suppression_violations = []
    differentiated = []
    close_differentiated = []
    strong_total = 0
    strong_stable = 0

    teams = sorted(source_plans)
    for defending_team in teams:
        defending_plan = source_plans[defending_team]

        for opponent_team in teams:
            if opponent_team == defending_team:
                continue

            opponent_plan = source_plans[opponent_team]
            board = _decision_board(source, defending_plan, opponent_plan)
            if not board:
                continue

            top = board[0]
            second = board[1] if len(board) > 1 else None
            gap = (
                float(top["raw_execution"]) - float(second["raw_execution"])
                if second is not None
                else float("inf")
            )

            raw_best_scheme = (
                str(top["scheme"])
                if float(top["raw_execution"]) >= 0.12
                and float(top["raw_utility"]) > 0.0
                else SCHEME_BALANCED
            )

            decisions = {}
            for profile_name, profile_state in archetype_states.items():
                decision = choose_defensive_tactical_counter_v1(
                    profile_state,
                    defending_plan,
                    opponent_plan,
                )
                decisions[profile_name] = decision
                scheme_counts[profile_name][decision.scheme] += 1

                if not (
                    0.0
                    <= float(decision.suppression_points)
                    <= float(MAX_DEFENSIVE_SUPPRESSION_POINTS) + 1e-12
                ):
                    suppression_violations.append({
                        "defending_team": defending_team,
                        "opponent_team": opponent_team,
                        "profile": profile_name,
                        "scheme": decision.scheme,
                        "suppression": decision.suppression_points,
                    })

                if decision.scheme != SCHEME_BALANCED:
                    raw_for_choice = next(
                        (
                            float(row["raw_utility"])
                            for row in board
                            if row["scheme"] == decision.scheme
                        ),
                        -999.0,
                    )
                    if raw_for_choice <= 0.0:
                        invalid_negative_choices.append({
                            "defending_team": defending_team,
                            "opponent_team": opponent_team,
                            "profile": profile_name,
                            "scheme": decision.scheme,
                            "raw_utility": raw_for_choice,
                        })

            unique_schemes = sorted({decision.scheme for decision in decisions.values()})
            is_close = bool(
                second is not None
                and float(top["raw_utility"]) > 0.0
                and float(second["raw_utility"]) > 0.0
                and gap <= CLOSE_CALL_EXECUTION_GAP
            )
            is_strong = bool(
                second is not None
                and float(top["raw_utility"]) > 0.0
                and gap >= STRONG_CALL_EXECUTION_GAP
            )

            if len(unique_schemes) > 1:
                example = {
                    "defending_team": defending_team,
                    "opponent_team": opponent_team,
                    "raw_best_scheme": raw_best_scheme,
                    "raw_execution_gap": round(gap, 5),
                    "close_call": is_close,
                    "strong_call": is_strong,
                    "profile_choices": {
                        name: {
                            "scheme": decision.scheme,
                            "scheme_label": decision.scheme_label,
                            "suppression_points": round(
                                float(decision.suppression_points),
                                4,
                            ),
                        }
                        for name, decision in decisions.items()
                    },
                }
                differentiated.append(example)
                if is_close:
                    close_differentiated.append(example)

            if is_strong:
                strong_total += 1
                if all(
                    decision.scheme == raw_best_scheme
                    for decision in decisions.values()
                ):
                    strong_stable += 1

            scenarios.append({
                "defending_team": defending_team,
                "opponent_team": opponent_team,
                "raw_execution_gap": gap,
                "is_close": is_close,
                "is_strong": is_strong,
                "unique_scheme_count": len(unique_schemes),
            })

    close_scenarios = [row for row in scenarios if row["is_close"]]
    differentiated_rate = (
        len(differentiated) / len(scenarios)
        if scenarios else 0.0
    )
    close_differentiation_rate = (
        len(close_differentiated) / len(close_scenarios)
        if close_scenarios else 0.0
    )
    strong_stability_rate = (
        strong_stable / strong_total
        if strong_total
        else 1.0
    )

    close_gate = (
        len(close_differentiated) >= 1
        if len(close_scenarios) < MIN_CLOSE_CALLS_FOR_RATE_GATE
        else close_differentiation_rate >= MIN_CLOSE_CALL_DIFFERENTIATION_RATE
    )

    checks = {
        "audit_covers_at_least_20_teams": len(source_plans) >= 20,
        "audit_covers_at_least_100_directed_matchups": len(scenarios) >= 100,
        "all_four_counterfactual_staff_profiles_are_used":
            len(archetype_states) == len(COUNTERFACTUAL_STAFF_PROFILES) == 4,
        "staff_ratings_are_held_constant": rating_integrity,
        "at_least_one_matchup_changes_scheme_by_staff_identity":
            len(differentiated) >= MIN_TOTAL_DIFFERENTIATED_MATCHUPS,
        "close_calls_show_staff_identity_differentiation": close_gate,
        "strong_matchups_are_at_least_95_percent_stable":
            strong_stability_rate >= MIN_STRONG_CALL_STABILITY,
        "no_negative_raw_utility_scheme_is_selected":
            not invalid_negative_choices,
        "all_tactical_suppression_remains_bounded":
            not suppression_violations,
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    summary = {
        "version": AUDIT_VERSION,
        "teams_with_valid_plans": len(source_plans),
        "directed_matchups": len(scenarios),
        "counterfactual_profiles": COUNTERFACTUAL_STAFF_PROFILES,
        "differentiated_matchups": len(differentiated),
        "differentiated_matchup_rate": round(differentiated_rate, 4),
        "close_call_matchups": len(close_scenarios),
        "close_call_differentiated": len(close_differentiated),
        "close_call_differentiation_rate": round(
            close_differentiation_rate,
            4,
        ),
        "strong_call_matchups": strong_total,
        "strong_call_stable": strong_stable,
        "strong_call_stability_rate": round(strong_stability_rate, 4),
        "invalid_negative_utility_choices": len(invalid_negative_choices),
        "suppression_violations": len(suppression_violations),
        "scheme_counts_by_profile": {
            profile: dict(counter)
            for profile, counter in scheme_counts.items()
        },
        "top_differentiated_examples": sorted(
            differentiated,
            key=lambda row: (
                float(row["raw_execution_gap"]),
                row["defending_team"],
                row["opponent_team"],
            ),
        )[:12],
        "checks": checks,
        "passed": all(checks.values()),
    }

    print("FRANCHISE V2 COACHING COUNTERFACTUAL AUDIT V1")
    print(f"Teams: {len(source_plans)}")
    print(f"Directed matchups: {len(scenarios)}")
    print(
        "Staff-identity differentiated matchups: "
        f"{len(differentiated)} ({differentiated_rate:.1%})"
    )
    print(
        "Close calls: "
        f"{len(close_scenarios)} | differentiated={len(close_differentiated)} "
        f"({close_differentiation_rate:.1%})"
    )
    print(
        "Strong calls: "
        f"{strong_total} | stable={strong_stable} "
        f"({strong_stability_rate:.1%})"
    )
    print("")

    for profile, counts in scheme_counts.items():
        print(f"{profile}:")
        for scheme, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            label = SCHEME_LABELS.get(scheme, scheme)
            print(f"  {label}: {count}")

    if differentiated:
        print("")
        print("SAMPLE STAFF-IDENTITY DIFFERENTIATION")
        for row in summary["top_differentiated_examples"][:8]:
            choices = ", ".join(
                f"{profile}={payload['scheme_label']}"
                for profile, payload in row["profile_choices"].items()
            )
            print(
                f"  {row['defending_team']} vs {row['opponent_team']} "
                f"| raw gap={row['raw_execution_gap']:.4f} "
                f"| {choices}"
            )

    print("")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    output_dir = (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "v2_coaching_counterfactual_audit_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "latest_audit.json"
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Output: {output_path}")

    if not all(checks.values()):
        print("COUNTERFACTUAL AUDIT FAILED")
        return 1

    print("COUNTERFACTUAL AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
