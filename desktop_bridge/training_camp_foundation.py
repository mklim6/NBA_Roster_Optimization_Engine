"""One bounded, deterministic skill camp per offseason; identical CPU rules."""
from __future__ import annotations

import copy
import hashlib
import math
import random

FOCUSES = {"shooting": "shooting_rating", "playmaking": "playmaking_rating", "defense": "defense_rating", "rebounding": "rebounding_rating"}
WEIGHTS = {"scoring_rating": .24, "shooting_rating": .12, "playmaking_rating": .16, "rebounding_rating": .12, "defense_rating": .18, "efficiency_rating": .13, "availability_rating": .05}
HISTORY_KEY = "v3_training_camp_history"
MENTOR_MIN_AGE = 28
LEARNER_MAX_AGE = 24
MENTOR_SKILL_EDGE = 8.0


def mentor_options(players, learner_id, focus):
    learner = next((row for row in players if row["player_id"] == learner_id), None)
    if learner is None or learner["age"] > LEARNER_MAX_AGE or focus not in FOCUSES:
        return []
    return sorted([dict(player_id=row["player_id"], name=row["name"], skill=row["skills"][focus],
                        edge=round(row["skills"][focus]-learner["skills"][focus], 2))
                   for row in players if row["player_id"] != learner_id and row["age"] >= MENTOR_MIN_AGE
                   and row["skills"][focus]-learner["skills"][focus] >= MENTOR_SKILL_EDGE],
                  key=lambda row: (-row["skill"], row["player_id"]))


def validate_mentors(report, plans, mentors):
    if not isinstance(mentors, dict):
        raise ValueError("Mentorships must be a player-to-mentor object.")
    used = set()
    for learner, mentor in mentors.items():
        if learner not in plans or not isinstance(mentor, str) or mentor in plans or mentor in used:
            raise ValueError("Mentors serve one focused learner and cannot train in the same camp.")
        if mentor not in {row["player_id"] for row in mentor_options(report["players"], learner, plans[learner])}:
            raise ValueError("Mentorship requires a healthy roster veteran age 28+, a learner age 24 or younger, and an 8-point skill advantage.")
        used.add(mentor)


def _number(player, field):
    value = float(getattr(player, "skill_ratings", {}).get(field, getattr(player, field, None)))
    if not math.isfinite(value):
        raise ValueError("Player ratings must be finite.")
    return value


def camp_summary(checkpoint, team):
    state = checkpoint.simulation_state
    season = str(state.settings.season_label)
    phase = str(getattr(state.phase, "value", state.phase)).lower()
    history = checkpoint.preferences.get(HISTORY_KEY, {})
    completed = history.get(season)
    rows = []
    for pid in state.teams[team].roster_player_ids:
        p = state.players[pid]
        if bool(getattr(p, "synthetic", False)):
            continue
        injury = getattr(state, "injuries", {}).get(pid)
        if injury is not None and str(getattr(getattr(injury, "status", "healthy"), "value", getattr(injury, "status", "healthy"))).lower() != "healthy":
            continue
        try:
            skills = {focus: _number(p, field) for focus, field in FOCUSES.items()}
            for field in WEIGHTS:
                _number(p, field)
            age = _number(p, "age")
            overall = _number(p, "overall_rating")
            potential = _number(p, "potential_rating")
            if any(not 60.0 <= value <= 99.9 for value in skills.values()) or age < 0:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        rows.append(dict(player_id=str(pid), name=str(p.player_name), age=age,
                         overall=overall, potential=potential, skills=skills))
    return dict(team=team, season=season, phase=phase, available=phase == "offseason" and completed is None,
                completed=completed is not None, slots=3, focuses=list(FOCUSES), players=rows,
                results=[] if completed is None else completed.get(team, []),
                mentor_rules=dict(minimum_age=MENTOR_MIN_AGE, learner_maximum_age=LEARNER_MAX_AGE, skill_edge=MENTOR_SKILL_EDGE, gain_multiplier=1.2),
                detail="One camp per offseason. Up to three focused players; gains are uncertain and capped at 1.5 skill points. Focus trades 0.25 points from another skill. Eligible mentors increase modeled gains by 20% before the cap. Annual development remains separate.")


def build_camp_candidate(checkpoint, team, assignments, mentors=None):
    summary = camp_summary(checkpoint, team)
    if not summary["available"]:
        raise ValueError("Camp requires an offseason and may run only once per season.")
    if not isinstance(assignments, dict) or not 1 <= len(assignments) <= 3:
        raise ValueError("Choose one to three players.")
    eligible = {p["player_id"] for p in summary["players"]}
    if any(pid not in eligible or not isinstance(focus, str) or focus not in FOCUSES for pid, focus in assignments.items()):
        raise ValueError("Choose roster players with valid ratings and a supported focus.")
    mentors = {} if mentors is None else mentors
    validate_mentors(summary, assignments, mentors)
    candidate = copy.deepcopy(checkpoint)
    state = candidate.simulation_state
    league_results = {}
    for abbreviation in sorted(state.teams):
        report = camp_summary(candidate, abbreviation)
        plans = assignments if abbreviation == team else {
            p["player_id"]: min(p["skills"], key=p["skills"].get)
            for p in sorted(report["players"], key=lambda p: (-(p["potential"] - p["overall"]), p["age"], p["player_id"]))[:3]
        }
        partnerships = dict(mentors) if abbreviation == team else {}
        if abbreviation != team:
            used = set()
            for pid, focus in plans.items():
                options = [row for row in mentor_options(report["players"], pid, focus)
                           if row["player_id"] not in plans and row["player_id"] not in used]
                if options:
                    partnerships[pid] = options[0]["player_id"]
                    used.add(options[0]["player_id"])
        validate_mentors(report, plans, partnerships)
        results = []
        for pid, focus in sorted(plans.items()):
            p = state.players[pid]
            seed = hashlib.sha256(f"camp41:{summary['season']}:{pid}:{focus}".encode()).digest()
            rng = random.Random(int.from_bytes(seed[:8], "big"))
            field = FOCUSES[focus]
            before = _number(p, field)
            other = FOCUSES[next(f for f in FOCUSES if f != focus)]
            other_before = _number(p, other)
            youth = max(.15, min(1.0, (35 - float(p.age)) / 15))
            headroom = max(0.0, min(1.0, (float(p.potential_rating) + .75 - float(p.overall_rating)) / 4))
            base_gain = rng.uniform(.15, 1.5) * youth * headroom
            mentor_id = partnerships.get(pid)
            gain = round(min(1.5, base_gain * (1.2 if mentor_id else 1.0)), 2)
            after = round(min(99.9, before + gain), 2)
            # No opportunity cost when camp produces no gain.
            other_after = round(max(60.0, other_before - .25), 2) if after > before else other_before
            old_overall = float(p.overall_rating)
            p.skill_ratings = {**getattr(p, "skill_ratings", {}), field: after, other: other_after}
            from player_development_engine_v1 import projected_stat_factors
            deltas = {skill: 0.0 for skill in WEIGHTS}
            deltas[field] = after - before
            deltas[other] = other_after - other_before
            previous_factors = dict(getattr(p, "stat_factors", {}) or {})
            p.stat_factors = {**previous_factors, **projected_stat_factors({"stat_factors": previous_factors}, deltas)}
            if hasattr(p, "baseline_per_36"):
                from simulation_season_transition_v1 import projected_baseline_per_36
                p.baseline_per_36 = projected_baseline_per_36(p.baseline_per_36, previous_factors, p.stat_factors)
            p.overall_rating = round(max(60.0, min(99.9, old_overall + (after-before)*WEIGHTS[field] + (other_after-other_before)*WEIGHTS[other])), 3)
            entry = dict(player_id=pid, name=str(p.player_name), focus=focus, before=before, after=after,
                         gain=round(after-before, 2), tradeoff=other.removesuffix("_rating"), tradeoff_before=other_before,
                         tradeoff_after=other_after, overall_before=old_overall, overall_after=p.overall_rating,
                         season=summary["season"], event="training_camp", engine_version="expansion43-v1",
                         mentor_id=mentor_id, mentor_name=str(state.players[mentor_id].player_name) if mentor_id else "",
                         unmentored_gain=round(min(99.9-before, base_gain), 2))
            # Annual history length is used as a service-time fallback.
            # Camp events must not add a year of service.
            if not hasattr(p, "training_camp_history"):
                p.training_camp_history = []
            p.training_camp_history.append(copy.deepcopy(entry))
            if mentor_id:
                mentor = state.players[mentor_id]
                if not hasattr(mentor, "mentorship_history"):
                    mentor.mentorship_history = []
                mentor.mentorship_history.append(dict(season=summary["season"], learner_id=pid,
                    learner_name=str(p.player_name), focus=focus, gain=entry["gain"],
                    overall_before=float(mentor.overall_rating), overall_after=float(mentor.overall_rating)))
            results.append(entry)
        league_results[abbreviation] = results
    candidate.preferences.setdefault(HISTORY_KEY, {})[summary["season"]] = league_results
    return candidate
