from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from franchise_free_agency_player_decision_v1 import evaluate_free_agent_offer_decision

FREE_AGENCY_INTEREST_METER_VERSION = "franchise-free-agency-player-interest-meter-v1-2026-08-14"
FREE_AGENCY_INTEREST_METER_UI_VERSION = "franchise-free-agency-player-interest-meter-ui-v1-2026-08-14"
FREE_AGENCY_INTEREST_METER_SCOPE = "display_only_current_offer_utility_not_signing_probability"


@dataclass(frozen=True)
class FreeAgencyInterestRow:
    team_abbreviation: str
    annual_salary: float
    years: int
    guaranteed: bool
    option_type: str
    interest_score: float
    acceptance_threshold: float
    gap_to_acceptance: float
    interest_band: str
    player_decision_status: str
    salary_score: float
    role_score: float
    winning_score: float
    security_score: float
    career_fit_score: float
    is_user_offer: bool
    rank: int


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def interest_meter_value(utility_score: float) -> int:
    """Clamp the deterministic player utility score to a Streamlit-friendly 0-100 meter."""
    try:
        value = float(utility_score)
    except (TypeError, ValueError):
        value = 0.0
    return int(round(max(0.0, min(100.0, value))))


def interest_band(
    utility_score: float,
    acceptance_threshold: float,
    decision_status: str = "",
) -> str:
    """Translate model utility into an intuitive display label without pretending it is a probability."""
    utility = float(utility_score)
    threshold = float(acceptance_threshold)
    status = _clean(decision_status).lower()
    gap = utility - threshold

    if status == "accept" and gap >= 12.0:
        return "Very high"
    if status == "accept" or utility >= threshold:
        return "High"
    if status == "counter" or gap >= -8.0:
        return "Medium"
    if gap >= -18.0:
        return "Some"
    return "Low"


def _rows_from_decisions(
    decisions: Iterable[Any],
    *,
    user_team_abbreviation: str = "",
) -> tuple[FreeAgencyInterestRow, ...]:
    user_team = _team(user_team_abbreviation)
    values = []
    for decision in decisions:
        utility = float(getattr(decision, "utility_score", 0.0) or 0.0)
        threshold = float(getattr(decision, "acceptance_threshold", 0.0) or 0.0)
        team = _team(getattr(decision, "team_abbreviation", ""))
        status = _clean(getattr(decision, "status", "")).lower()
        values.append(
            FreeAgencyInterestRow(
                team_abbreviation=team,
                annual_salary=float(getattr(decision, "annual_salary", 0.0) or 0.0),
                years=int(getattr(decision, "years", 0) or 0),
                guaranteed=bool(getattr(decision, "guaranteed", False)),
                option_type=_clean(getattr(decision, "option_type", "")),
                interest_score=round(utility, 3),
                acceptance_threshold=round(threshold, 3),
                gap_to_acceptance=round(utility - threshold, 3),
                interest_band=interest_band(utility, threshold, status),
                player_decision_status=status,
                salary_score=round(float(getattr(decision, "salary_score", 0.0) or 0.0), 3),
                role_score=round(float(getattr(decision, "role_score", 0.0) or 0.0), 3),
                winning_score=round(float(getattr(decision, "winning_score", 0.0) or 0.0), 3),
                security_score=round(float(getattr(decision, "security_score", 0.0) or 0.0), 3),
                career_fit_score=round(float(getattr(decision, "career_fit_score", 0.0) or 0.0), 3),
                is_user_offer=bool(user_team and team == user_team),
                rank=0,
            )
        )

    values.sort(
        key=lambda row: (
            -row.interest_score,
            -row.annual_salary * max(row.years, 1),
            row.team_abbreviation,
        )
    )
    return tuple(
        FreeAgencyInterestRow(**{**row.__dict__, "rank": index})
        for index, row in enumerate(values, start=1)
    )


def build_player_interest_rows(
    state: Any,
    negotiation: Any,
    *,
    decision_evaluator: Callable[[Any, Any], Any] = evaluate_free_agent_offer_decision,
) -> tuple[FreeAgencyInterestRow, ...]:
    """Evaluate the exact current negotiation previews using the locked Player Decisions V1 model.

    This is display-only. It never generates an offer, changes a market, advances a round,
    commits a transaction, or mutates franchise state.
    """
    previews = tuple(getattr(negotiation, "previews", ()) or ())
    user_team = _team(getattr(negotiation, "user_team_abbreviation", ""))
    decisions = tuple(decision_evaluator(state, preview) for preview in previews)
    return _rows_from_decisions(decisions, user_team_abbreviation=user_team)


__all__ = [
    "FREE_AGENCY_INTEREST_METER_VERSION",
    "FREE_AGENCY_INTEREST_METER_UI_VERSION",
    "FREE_AGENCY_INTEREST_METER_SCOPE",
    "FreeAgencyInterestRow",
    "interest_meter_value",
    "interest_band",
    "build_player_interest_rows",
]
