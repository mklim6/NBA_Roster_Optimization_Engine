from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping


STAFF_SYSTEM_VERSION = "franchise-staff-system-v1.2-scout-market-2026-09-16"
STAFF_STATE_ATTRIBUTE = "franchise_staff_state_v1"
REAL_STAFF_REFERENCE_VERSION = "nba-real-staff-reference-v1-2026-09-11"
REAL_STAFF_REFERENCE_DATE = date(2026, 9, 7)
_REAL_STAFF_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "app_data" / "nba_real_staff_reference_2026_09_07.json"

ROLE_HEAD_COACH = "head_coach"
ROLE_ASSISTANT_COACH = "assistant_coach"
ROLE_DEVELOPMENT_COACH = "development_coach"
ROLE_LEAD_SCOUT = "lead_scout"
ROLE_MEDICAL_DIRECTOR = "medical_director"

STAFF_ROLES = (
    ROLE_HEAD_COACH,
    ROLE_ASSISTANT_COACH,
    ROLE_DEVELOPMENT_COACH,
    ROLE_LEAD_SCOUT,
    ROLE_MEDICAL_DIRECTOR,
)

ROLE_LABELS = {
    ROLE_HEAD_COACH: "Head Coach",
    ROLE_ASSISTANT_COACH: "Lead Assistant",
    ROLE_DEVELOPMENT_COACH: "Player Development Coach",
    ROLE_LEAD_SCOUT: "Lead Scout",
    ROLE_MEDICAL_DIRECTOR: "Medical / Performance Director",
}

_FIRST_NAMES = (
    "Aaron", "Andre", "Caleb", "Cameron", "Darius", "Devin", "Eli", "Eric",
    "Grant", "Isaiah", "Jalen", "Jordan", "Julian", "Marcus", "Miles", "Nate",
    "Noah", "Owen", "Ryan", "Sean", "Terrence", "Trevor", "Victor", "Wes",
)
_LAST_NAMES = (
    "Bennett", "Carter", "Coleman", "Daniels", "Ellis", "Foster", "Grant",
    "Hayes", "Holland", "Jefferson", "Lawson", "Marshall", "Mitchell",
    "Parker", "Reed", "Reynolds", "Simmons", "Sullivan", "Taylor", "Turner",
    "Walker", "Ward", "Warren", "Young",
)

TRAITS_BY_ROLE = {
    ROLE_HEAD_COACH: (
        "Adaptive", "Player-first", "Discipline", "Veteran trust",
        "Youth trust", "Half-court detail", "Tempo control", "Defensive edge",
    ),
    ROLE_ASSISTANT_COACH: (
        "Opponent prep", "Rotation detail", "Shooting development", "Defense lab",
        "Transition offense", "Communication", "Bench development", "Analytics",
    ),
    ROLE_DEVELOPMENT_COACH: (
        "Skill growth", "Young-player trust", "Shooting mechanics", "Decision making",
        "Defensive habits", "Strength program", "Role clarity", "Film study",
    ),
    ROLE_LEAD_SCOUT: (
        "Potential projection", "Medical context", "International", "Guards",
        "Wings", "Bigs", "Character interviews", "Statistical translation",
    ),
    ROLE_MEDICAL_DIRECTOR: (
        "Prevention", "Recovery", "Load management", "Diagnosis",
        "Return-to-play", "Soft-tissue care", "Strength", "Conditioning",
    ),
}


@dataclass
class StaffMember:
    staff_id: str
    team: str
    role: str
    name: str
    age: int
    years_experience: int
    contract_years_remaining: int
    annual_salary_millions: float
    overall_rating: float
    offense_rating: float = 70.0
    defense_rating: float = 70.0
    rotation_management_rating: float = 70.0
    player_development_rating: float = 70.0
    scouting_current_rating: float = 70.0
    scouting_potential_rating: float = 70.0
    medical_prevention_rating: float = 70.0
    medical_recovery_rating: float = 70.0
    communication_rating: float = 70.0
    adaptability_rating: float = 70.0
    traits: tuple[str, ...] = ()
    source: str = "generated_staff_foundation_v1"


@dataclass
class TeamStaffState:
    team: str
    members: dict[str, StaffMember] = field(default_factory=dict)


@dataclass
class FranchiseStaffState:
    version: str
    season_label: str
    teams: dict[str, TeamStaffState] = field(default_factory=dict)
    # SCOUT_CHECKPOINT_COMPAT_V1_0_1: class-level None lets legacy checkpoint objects
    # survive runtime dataclass rebinding before ensure_franchise_staff_state migrates them.
    scouting_history: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class TeamStaffEffects:
    team: str
    overall_quality: float
    development_modifier: float
    injury_risk_multiplier: float
    recovery_multiplier: float
    scouting_current_accuracy: float
    scouting_potential_accuracy: float
    rotation_management: float
    offense_index: float
    defense_index: float


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _stable_rng(*parts: Any) -> random.Random:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    return random.Random(seed)


def _load_real_staff_reference() -> dict[str, Any]:
    try:
        payload = json.loads(_REAL_STAFF_REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if str(payload.get("version") or "") != REAL_STAFF_REFERENCE_VERSION:
        return {}
    teams = payload.get("teams")
    return teams if isinstance(teams, dict) else {}


def _age_on_reference_date(birth_date: str) -> int | None:
    try:
        born = date.fromisoformat(str(birth_date))
    except (TypeError, ValueError):
        return None
    years = REAL_STAFF_REFERENCE_DATE.year - born.year
    if (REAL_STAFF_REFERENCE_DATE.month, REAL_STAFF_REFERENCE_DATE.day) < (born.month, born.day):
        years -= 1
    return years


def _apply_real_head_coach_identity(team_state: TeamStaffState) -> None:
    """Overlay verified Sep. 7, 2026 head-coach identity without changing gameplay ratings."""
    reference = _load_real_staff_reference().get(str(team_state.team).upper())
    if not isinstance(reference, dict):
        return
    coach = reference.get("head_coach")
    member = team_state.members.get(ROLE_HEAD_COACH)
    if not isinstance(coach, dict) or not isinstance(member, StaffMember):
        return
    name = str(coach.get("name") or "").strip()
    if name:
        member.name = name
    age = _age_on_reference_date(str(coach.get("birth_date") or ""))
    if age is not None:
        member.age = age
    # Contract economics, ratings, traits, and experience stay simulation-generated
    # so this identity migration cannot alter team effects or checkpoint behavior.
    member.source = "nba_real_world_head_coach_sep7_2026_simulated_attributes_v1"


def _season_label(state: Any) -> str:
    settings = getattr(state, "settings", None)
    value = getattr(settings, "season_label", "2026-27")
    text = str(value or "2026-27").strip()
    return text or "2026-27"


def _team_codes(state: Any) -> tuple[str, ...]:
    teams = getattr(state, "teams", {})
    if isinstance(teams, Mapping):
        return tuple(sorted(str(team).strip().upper() for team in teams if str(team).strip()))
    return ()


def _rating(rng: random.Random, center: float, spread: float = 10.0) -> float:
    return round(_clamp(rng.gauss(center, spread), 45.0, 96.0), 1)


def _member_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def _salary_for_role(role: str, overall: float, rng: random.Random) -> float:
    base = {
        ROLE_HEAD_COACH: 4.2,
        ROLE_ASSISTANT_COACH: 1.45,
        ROLE_DEVELOPMENT_COACH: 1.25,
        ROLE_LEAD_SCOUT: 0.95,
        ROLE_MEDICAL_DIRECTOR: 1.15,
    }[role]
    premium = max(0.0, overall - 70.0) * {
        ROLE_HEAD_COACH: 0.18,
        ROLE_ASSISTANT_COACH: 0.055,
        ROLE_DEVELOPMENT_COACH: 0.05,
        ROLE_LEAD_SCOUT: 0.04,
        ROLE_MEDICAL_DIRECTOR: 0.045,
    }[role]
    return round(base + premium + rng.uniform(-0.20, 0.30), 2)


def _generate_member(team: str, role: str) -> StaffMember:
    rng = _stable_rng(STAFF_SYSTEM_VERSION, team, role)
    base_center = {
        ROLE_HEAD_COACH: 74.0,
        ROLE_ASSISTANT_COACH: 71.0,
        ROLE_DEVELOPMENT_COACH: 72.0,
        ROLE_LEAD_SCOUT: 72.0,
        ROLE_MEDICAL_DIRECTOR: 73.0,
    }[role]

    offense = _rating(rng, base_center)
    defense = _rating(rng, base_center)
    rotations = _rating(rng, base_center)
    development = _rating(rng, base_center)
    scout_current = _rating(rng, base_center)
    scout_potential = _rating(rng, base_center)
    prevention = _rating(rng, base_center)
    recovery = _rating(rng, base_center)
    communication = _rating(rng, base_center)
    adaptability = _rating(rng, base_center)

    if role == ROLE_HEAD_COACH:
        overall = 0.18 * offense + 0.18 * defense + 0.18 * rotations + 0.14 * development + 0.16 * communication + 0.16 * adaptability
    elif role == ROLE_ASSISTANT_COACH:
        overall = 0.24 * offense + 0.24 * defense + 0.20 * rotations + 0.16 * development + 0.16 * communication
    elif role == ROLE_DEVELOPMENT_COACH:
        overall = 0.55 * development + 0.18 * communication + 0.12 * adaptability + 0.08 * offense + 0.07 * defense
    elif role == ROLE_LEAD_SCOUT:
        overall = 0.46 * scout_current + 0.39 * scout_potential + 0.15 * adaptability
    else:
        overall = 0.48 * prevention + 0.38 * recovery + 0.14 * communication

    overall = round(_clamp(overall, 45.0, 96.0), 1)
    traits = tuple(rng.sample(TRAITS_BY_ROLE[role], k=2))
    age_low, age_high = (38, 66) if role == ROLE_HEAD_COACH else (30, 62)
    age = rng.randint(age_low, age_high)
    experience = max(1, min(age - 24, int(round(rng.uniform(3, max(4, age - 26))))))
    contract_years = rng.randint(1, 5 if role == ROLE_HEAD_COACH else 4)

    return StaffMember(
        staff_id=f"staff_{team.lower()}_{role}",
        team=team,
        role=role,
        name=_member_name(rng),
        age=age,
        years_experience=experience,
        contract_years_remaining=contract_years,
        annual_salary_millions=_salary_for_role(role, overall, rng),
        overall_rating=overall,
        offense_rating=offense,
        defense_rating=defense,
        rotation_management_rating=rotations,
        player_development_rating=development,
        scouting_current_rating=scout_current,
        scouting_potential_rating=scout_potential,
        medical_prevention_rating=prevention,
        medical_recovery_rating=recovery,
        communication_rating=communication,
        adaptability_rating=adaptability,
        traits=traits,
    )


def build_team_staff(team: str) -> TeamStaffState:
    team = str(team or "").strip().upper()
    if not team:
        raise ValueError("A team abbreviation is required to build staff.")
    team_state = TeamStaffState(
        team=team,
        members={role: _generate_member(team, role) for role in STAFF_ROLES},
    )
    _apply_real_head_coach_identity(team_state)
    return team_state


def ensure_franchise_staff_state(state: Any) -> FranchiseStaffState:
    existing = getattr(state, STAFF_STATE_ATTRIBUTE, None)
    season = _season_label(state)
    if not isinstance(existing, FranchiseStaffState):
        existing = FranchiseStaffState(version=STAFF_SYSTEM_VERSION, season_label=season)
        setattr(state, STAFF_STATE_ATTRIBUTE, existing)

    existing.version = STAFF_SYSTEM_VERSION
    existing.season_label = season
    if not isinstance(getattr(existing, "scouting_history", None), list):
        existing.scouting_history = []
    for team in _team_codes(state):
        team_state = existing.teams.get(team)
        if not isinstance(team_state, TeamStaffState):
            existing.teams[team] = build_team_staff(team)
            continue
        for role in STAFF_ROLES:
            if not isinstance(team_state.members.get(role), StaffMember):
                team_state.members[role] = _generate_member(team, role)
        _apply_real_head_coach_identity(team_state)
    return existing


def get_franchise_staff_state(state: Any) -> FranchiseStaffState | None:
    value = getattr(state, STAFF_STATE_ATTRIBUTE, None)
    return value if isinstance(value, FranchiseStaffState) else None


def team_staff(state: Any, team: str, *, ensure: bool = False) -> TeamStaffState | None:
    staff_state = ensure_franchise_staff_state(state) if ensure else get_franchise_staff_state(state)
    if staff_state is None:
        return None
    return staff_state.teams.get(str(team or "").strip().upper())


def _role(team_state: TeamStaffState | None, role: str) -> StaffMember | None:
    if team_state is None:
        return None
    return team_state.members.get(role)


def team_staff_effects(state: Any, team: str, *, ensure: bool = False) -> TeamStaffEffects:
    team_code = str(team or "").strip().upper()
    team_state = team_staff(state, team_code, ensure=ensure)
    if team_state is None:
        return TeamStaffEffects(
            team=team_code,
            overall_quality=70.0,
            development_modifier=0.0,
            injury_risk_multiplier=1.0,
            recovery_multiplier=1.0,
            scouting_current_accuracy=70.0,
            scouting_potential_accuracy=70.0,
            rotation_management=70.0,
            offense_index=70.0,
            defense_index=70.0,
        )

    head = _role(team_state, ROLE_HEAD_COACH)
    assistant = _role(team_state, ROLE_ASSISTANT_COACH)
    dev = _role(team_state, ROLE_DEVELOPMENT_COACH)
    scout = _role(team_state, ROLE_LEAD_SCOUT)
    medical = _role(team_state, ROLE_MEDICAL_DIRECTOR)

    def val(member: StaffMember | None, field_name: str, default: float = 70.0) -> float:
        return float(getattr(member, field_name, default) if member is not None else default)

    development_quality = 0.34 * val(head, "player_development_rating") + 0.66 * val(dev, "player_development_rating")
    development_modifier = _clamp((development_quality - 70.0) / 30.0 * 0.35, -0.30, 0.30)

    prevention = val(medical, "medical_prevention_rating")
    recovery = val(medical, "medical_recovery_rating")
    injury_risk_multiplier = _clamp(1.0 - (prevention - 70.0) * 0.0030, 0.90, 1.10)
    recovery_multiplier = _clamp(1.0 + (recovery - 70.0) * 0.0040, 0.90, 1.12)

    scouting_current = val(scout, "scouting_current_rating")
    scouting_potential = val(scout, "scouting_potential_rating")
    rotation = 0.68 * val(head, "rotation_management_rating") + 0.32 * val(assistant, "rotation_management_rating")
    offense = 0.68 * val(head, "offense_rating") + 0.32 * val(assistant, "offense_rating")
    defense = 0.68 * val(head, "defense_rating") + 0.32 * val(assistant, "defense_rating")
    overall = sum(member.overall_rating for member in team_state.members.values()) / max(1, len(team_state.members))

    return TeamStaffEffects(
        team=team_code,
        overall_quality=round(overall, 2),
        development_modifier=round(development_modifier, 4),
        injury_risk_multiplier=round(injury_risk_multiplier, 4),
        recovery_multiplier=round(recovery_multiplier, 4),
        scouting_current_accuracy=round(scouting_current, 2),
        scouting_potential_accuracy=round(scouting_potential, 2),
        rotation_management=round(rotation, 2),
        offense_index=round(offense, 2),
        defense_index=round(defense, 2),
    )


def team_development_modifier(state: Any, team: str) -> float:
    return team_staff_effects(state, team, ensure=False).development_modifier


def team_injury_risk_multiplier(state: Any, team: str) -> float:
    return team_staff_effects(state, team, ensure=False).injury_risk_multiplier


def team_recovery_multiplier(state: Any, team: str) -> float:
    return team_staff_effects(state, team, ensure=False).recovery_multiplier


def staff_rows(state: Any, team: str, *, ensure: bool = True) -> list[dict[str, Any]]:
    team_state = team_staff(state, team, ensure=ensure)
    if team_state is None:
        return []
    rows: list[dict[str, Any]] = []
    for role in STAFF_ROLES:
        member = team_state.members[role]
        rows.append({
            "role": ROLE_LABELS[role],
            "name": member.name,
            "age": member.age,
            "experience": member.years_experience,
            "contract_years": member.contract_years_remaining,
            "salary_m": member.annual_salary_millions,
            "overall": member.overall_rating,
            "offense": member.offense_rating,
            "defense": member.defense_rating,
            "rotations": member.rotation_management_rating,
            "development": member.player_development_rating,
            "scout_current": member.scouting_current_rating,
            "scout_potential": member.scouting_potential_rating,
            "medical_prevention": member.medical_prevention_rating,
            "medical_recovery": member.medical_recovery_rating,
            "communication": member.communication_rating,
            "adaptability": member.adaptability_rating,
            "traits": ", ".join(member.traits),
            "personnel_basis": (
                "Real-world · Sep 7, 2026"
                if member.source == "nba_real_world_head_coach_sep7_2026_simulated_attributes_v1"
                else "Sim-generated"
            ),
        })
    return rows


def league_staff_summary(state: Any, *, ensure: bool = True) -> list[dict[str, Any]]:
    if ensure:
        ensure_franchise_staff_state(state)
    rows = []
    for team in _team_codes(state):
        effects = team_staff_effects(state, team)
        rows.append(asdict(effects))
    return rows


def scouting_error_band(state: Any, team: str, *, potential: bool = False) -> float:
    effects = team_staff_effects(state, team, ensure=False)
    rating = effects.scouting_potential_accuracy if potential else effects.scouting_current_accuracy
    # Intended for Scouting V1: elite scouts narrow uncertainty without ever
    # making the hidden truth perfectly known.
    return round(_clamp(11.0 - (rating - 50.0) * 0.11, 3.0, 11.0), 2)


SCOUT_MARKET_SIZE = 8
SCOUTING_HISTORY_VERSION = "franchise-scouting-track-record-v1.0-2026-09-16"


def lead_scout_member(state: Any, team: str, *, ensure: bool = True) -> StaffMember | None:
    team_state = team_staff(state, team, ensure=ensure)
    return _role(team_state, ROLE_LEAD_SCOUT)


def scouting_error_band_for_rating(rating: float) -> float:
    """Translate a scouting rating into the same uncertainty scale used in Draft scouting."""
    return round(_clamp(11.0 - (float(rating) - 50.0) * 0.11, 3.0, 11.0), 2)


def _generate_scout_candidate(team: str, season_label: str, slot: int) -> StaffMember:
    team_code = str(team or "").strip().upper()
    season = str(season_label or "").strip() or "unknown"
    rng = _stable_rng(STAFF_SYSTEM_VERSION, "lead_scout_market", team_code, season, int(slot))
    # Markets contain meaningful archetypes rather than eight near-identical scouts.
    archetypes = (
        (82.0, 67.0, "Ready-now evaluator"),
        (67.0, 84.0, "Upside hunter"),
        (77.0, 77.0, "Balanced evaluator"),
        (86.0, 61.0, "Pro-readiness specialist"),
        (63.0, 88.0, "Projection specialist"),
        (74.0, 81.0, "Development projection"),
        (81.0, 73.0, "Film-first evaluator"),
        (72.0, 75.0, "Value generalist"),
    )
    current_center, potential_center, archetype = archetypes[int(slot) % len(archetypes)]
    scout_current = _rating(rng, current_center, 5.4)
    scout_potential = _rating(rng, potential_center, 5.4)
    adaptability = _rating(rng, 73.0, 8.0)
    communication = _rating(rng, 72.0, 8.0)
    overall = round(_clamp(0.46 * scout_current + 0.39 * scout_potential + 0.15 * adaptability, 45.0, 96.0), 1)
    traits = list(rng.sample(TRAITS_BY_ROLE[ROLE_LEAD_SCOUT], k=2))
    if archetype not in traits:
        traits = [archetype, traits[0]]
    age = rng.randint(31, 61)
    experience = max(2, min(age - 24, rng.randint(4, max(5, age - 26))))
    years = rng.randint(2, 4)
    return StaffMember(
        staff_id=f"scout_market_{team_code.lower()}_{season.replace('-', '_')}_{int(slot)+1}",
        team="FA",
        role=ROLE_LEAD_SCOUT,
        name=_member_name(rng),
        age=age,
        years_experience=experience,
        contract_years_remaining=years,
        annual_salary_millions=_salary_for_role(ROLE_LEAD_SCOUT, overall, rng),
        overall_rating=overall,
        offense_rating=70.0,
        defense_rating=70.0,
        rotation_management_rating=70.0,
        player_development_rating=70.0,
        scouting_current_rating=scout_current,
        scouting_potential_rating=scout_potential,
        medical_prevention_rating=70.0,
        medical_recovery_rating=70.0,
        communication_rating=communication,
        adaptability_rating=adaptability,
        traits=tuple(traits),
        source="scout_market_v1",
    )


def scout_market_candidates(state: Any, team: str) -> tuple[StaffMember, ...]:
    season = _season_label(state)
    return tuple(_generate_scout_candidate(team, season, slot) for slot in range(SCOUT_MARKET_SIZE))


def hire_lead_scout(state: Any, team: str, candidate_staff_id: str) -> StaffMember:
    team_code = str(team or "").strip().upper()
    candidate = next(
        (row for row in scout_market_candidates(state, team_code) if row.staff_id == str(candidate_staff_id)),
        None,
    )
    if candidate is None:
        raise ValueError("That scout is not available in the current staff market.")
    team_state = team_staff(state, team_code, ensure=True)
    if team_state is None:
        raise ValueError(f"Staff state is unavailable for {team_code}.")
    hired = StaffMember(**asdict(candidate))
    hired.team = team_code
    hired.source = "user_hired_scout_market_v1"
    team_state.members[ROLE_LEAD_SCOUT] = hired
    return hired


def _draft_prospect_map(draft_state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in draft_state.get("prospects", []) or []:
        if not isinstance(row, Mapping):
            continue
        pid = str(row.get("prospect_id") or "").strip()
        if pid:
            result[pid] = row
    return result


def archive_completed_scouting_accuracy(state: Any, draft_state: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Archive team scouting error after Draft Night without exposing hidden truth beforehand."""
    current = draft_state if isinstance(draft_state, Mapping) else getattr(state, "franchise_draft_state_v1", None)
    if not isinstance(current, Mapping) or str(current.get("phase") or "") != "draft_complete":
        return []
    scouting_root = current.get("scouting_discovery_v1")
    if not isinstance(scouting_root, Mapping):
        return []
    draft_year = int(current.get("draft_year") or 0)
    if draft_year <= 0:
        return []
    staff_state = ensure_franchise_staff_state(state)
    history = getattr(staff_state, "scouting_history", None)
    if not isinstance(history, list):
        history = []
        staff_state.scouting_history = history
    prospects = _draft_prospect_map(current)
    added: list[dict[str, Any]] = []
    teams = scouting_root.get("teams")
    if not isinstance(teams, Mapping):
        return []
    for raw_team, payload in teams.items():
        team_code = str(raw_team or "").strip().upper()
        if not team_code or not isinstance(payload, Mapping):
            continue
        if any(int(row.get("draft_year") or -1) == draft_year and str(row.get("team") or "") == team_code for row in history if isinstance(row, Mapping)):
            continue
        reports = payload.get("reports")
        if not isinstance(reports, Mapping):
            continue
        ovr_errors: list[float] = []
        pot_errors: list[float] = []
        strong_finds = 0
        major_misses = 0
        for pid, report in reports.items():
            prospect = prospects.get(str(pid))
            if not isinstance(prospect, Mapping) or not isinstance(report, Mapping):
                continue
            try:
                true_ovr = float(prospect.get("hidden_overall"))
                true_pot = float(prospect.get("hidden_potential"))
                est_ovr = float(report.get("scouted_overall"))
                est_pot = float(report.get("scouted_potential"))
            except (TypeError, ValueError):
                continue
            oerr = abs(est_ovr - true_ovr)
            perr = abs(est_pot - true_pot)
            ovr_errors.append(oerr)
            pot_errors.append(perr)
            if oerr <= 2.0 and perr <= 4.0:
                strong_finds += 1
            if oerr >= 6.0 or perr >= 10.0:
                major_misses += 1
        if not ovr_errors:
            continue
        scout = lead_scout_member(state, team_code, ensure=True)
        record = {
            "version": SCOUTING_HISTORY_VERSION,
            "draft_year": draft_year,
            "team": team_code,
            "lead_scout": getattr(scout, "name", "Unknown"),
            "lead_scout_id": getattr(scout, "staff_id", ""),
            "reports_graded": len(ovr_errors),
            "overall_mae": round(sum(ovr_errors) / len(ovr_errors), 2),
            "potential_mae": round(sum(pot_errors) / len(pot_errors), 2),
            "strong_finds": int(strong_finds),
            "major_misses": int(major_misses),
        }
        history.append(record)
        added.append(record)
    return added


def scouting_track_record_rows(state: Any, team: str) -> list[dict[str, Any]]:
    archive_completed_scouting_accuracy(state)
    staff_state = ensure_franchise_staff_state(state)
    team_code = str(team or "").strip().upper()
    history = getattr(staff_state, "scouting_history", None)
    if not isinstance(history, list):
        history = []
        staff_state.scouting_history = history
    rows = [dict(row) for row in history if isinstance(row, Mapping) and str(row.get("team") or "").upper() == team_code]
    rows.sort(key=lambda row: int(row.get("draft_year") or 0), reverse=True)
    return rows


__all__ = [
    "STAFF_SYSTEM_VERSION",
    "STAFF_STATE_ATTRIBUTE",
    "REAL_STAFF_REFERENCE_VERSION",
    "STAFF_ROLES",
    "ROLE_LABELS",
    "StaffMember",
    "TeamStaffState",
    "FranchiseStaffState",
    "TeamStaffEffects",
    "ensure_franchise_staff_state",
    "get_franchise_staff_state",
    "team_staff",
    "team_staff_effects",
    "team_development_modifier",
    "team_injury_risk_multiplier",
    "team_recovery_multiplier",
    "staff_rows",
    "league_staff_summary",
    "scouting_error_band",
    "ROLE_LEAD_SCOUT",
    "SCOUT_MARKET_SIZE",
    "SCOUTING_HISTORY_VERSION",
    "lead_scout_member",
    "scouting_error_band_for_rating",
    "scout_market_candidates",
    "hire_lead_scout",
    "archive_completed_scouting_accuracy",
    "scouting_track_record_rows",
]
