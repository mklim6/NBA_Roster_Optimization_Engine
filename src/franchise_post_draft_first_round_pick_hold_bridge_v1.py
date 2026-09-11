from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


BRIDGE_VERSION = "franchise-post-draft-first-round-pick-hold-bridge-v1.1-future-season-projection-2026-08-17"
# Legacy exact anchor. The original 2026-27 path remains deterministic.
SEASON_LABEL = "2026-27"
DRAFT_YEAR = 2026
CAP_HOLD_MULTIPLIER = Decimal("1.20")
FUTURE_ANNUAL_CAP_GROWTH = Decimal("0.08")
MAX_FUTURE_PROJECTION_YEARS = 10
FUTURE_SCALE_POLICY_SOURCE = (
    "franchise_financial_cba_bridge_v1.DEFAULT_ANNUAL_CAP_GROWTH=0.08"
)
STATE_LEDGER_ATTR = "post_draft_first_round_pick_holds_v1"
STATE_METADATA_ATTR = "post_draft_first_round_pick_hold_bridge_v1_metadata"
PENDING_CONTRACT_STATUSES = {
    "rookie_scale_pending",
    "unsigned_first_round_pick",
    "draft_rights",
}

# Official NBA salary caps. The CBA rolls the preceding Rookie Salary Scale
# forward by the percentage increase in the Salary Cap, with dollar amounts
# represented to the nearest $100 in the official scale tables.
SALARY_CAP_BY_SEASON = {
    "2022-23": 123_655_000,
    "2023-24": 136_021_000,
    "2024-25": 140_588_000,
    "2025-26": 154_647_000,
    "2026-27": 164_961_000,
}

# 2022-23 baseline first-year Rookie Scale Amounts from 2023 CBA Exhibit B.
BASELINE_FIRST_YEAR_SCALE = {
    1: 9_212_600,
    2: 8_242_700,
    3: 7_402_200,
    4: 6_673_700,
    5: 6_043_500,
    6: 5_489_000,
    7: 5_010_800,
    8: 4_590_500,
    9: 4_219_600,
    10: 4_008_600,
    11: 3_808_200,
    12: 3_617_900,
    13: 3_436_900,
    14: 3_265_300,
    15: 3_101_700,
    16: 2_946_800,
    17: 2_799_300,
    18: 2_659_500,
    19: 2_539_700,
    20: 2_438_000,
    21: 2_340_500,
    22: 2_247_000,
    23: 2_157_200,
    24: 2_071_000,
    25: 1_987_900,
    26: 1_922_100,
    27: 1_866_600,
    28: 1_855_000,
    29: 1_841_700,
    30: 1_828_300,
}

CBA_SOURCE_URL = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)
NBA_2026_27_CAP_SOURCE_URL = "https://pr.nba.com/2026-27-salary-cap/"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except Exception:
        return None
    return int(number) if number == number.to_integral_value() else None


def round_to_nearest_hundred(value: Decimal | int) -> int:
    return int(Decimal(value).quantize(Decimal("1E2"), rounding=ROUND_HALF_UP))


def rookie_scale_amounts_by_season() -> dict[str, dict[int, int]]:
    scales: dict[str, dict[int, int]] = {"2022-23": dict(BASELINE_FIRST_YEAR_SCALE)}
    seasons = list(SALARY_CAP_BY_SEASON)
    for prior, current in zip(seasons, seasons[1:]):
        ratio = Decimal(SALARY_CAP_BY_SEASON[current]) / Decimal(SALARY_CAP_BY_SEASON[prior])
        scales[current] = {
            pick: round_to_nearest_hundred(Decimal(amount) * ratio)
            for pick, amount in scales[prior].items()
        }
    return scales


def rookie_scale_schedule_2026_27() -> list[dict[str, Any]]:
    scale = rookie_scale_amounts_by_season()[SEASON_LABEL]
    return [
        {
            "season": SEASON_LABEL,
            "draft_year": DRAFT_YEAR,
            "overall_pick": pick,
            "rookie_scale_amount": amount,
            "rookie_scale_cap_hold_amount": round_to_nearest_hundred(Decimal(amount) * CAP_HOLD_MULTIPLIER),
            "cap_hold_multiplier": str(CAP_HOLD_MULTIPLIER),
            "derivation": "cba_exhibit_b_rolled_forward_by_official_salary_cap_growth",
            "cba_source_url": CBA_SOURCE_URL,
            "salary_cap_source_url": NBA_2026_27_CAP_SOURCE_URL,
        }
        for pick, amount in sorted(scale.items())
    ]


def season_start(season: str) -> int:
    text = clean(season)
    match = __import__("re").fullmatch(r"(\d{4})-(\d{2})", text)
    if not match:
        raise ValueError(f"Invalid NBA season label {season!r}.")
    start = int(match.group(1))
    end = int(match.group(2))
    expected_end = (start + 1) % 100
    if end != expected_end:
        raise ValueError(f"Season label is not a one-year NBA season: {season!r}.")
    return start


def season_label_for_draft(draft_year: int) -> str:
    year = int(draft_year)
    return f"{year}-{(year + 1) % 100:02d}"


def rookie_scale_amounts_for_season(
    season: str,
    *,
    annual_cap_growth: Decimal = FUTURE_ANNUAL_CAP_GROWTH,
) -> dict[int, int]:
    """Return exact known scales through 2026-27 and bounded modeled future scales."""
    resolved = clean(season)
    known = rookie_scale_amounts_by_season()
    if resolved in known:
        return dict(known[resolved])

    start = season_start(resolved)
    anchor_start = season_start(SEASON_LABEL)
    years = start - anchor_start
    if years <= 0:
        raise ValueError(
            f"Rookie-scale bridge cannot backcast before the frozen {SEASON_LABEL} anchor."
        )
    if years > MAX_FUTURE_PROJECTION_YEARS:
        raise ValueError(
            f"Rookie-scale projection is bounded to {MAX_FUTURE_PROJECTION_YEARS} "
            f"years after {SEASON_LABEL}; received {resolved!r}."
        )

    growth = Decimal(annual_cap_growth)
    if growth < Decimal("0") or growth > Decimal("0.10"):
        raise ValueError("Modeled annual rookie-scale growth must be between 0% and 10%.")

    scale = dict(known[SEASON_LABEL])
    for _ in range(years):
        scale = {
            pick: round_to_nearest_hundred(
                Decimal(amount) * (Decimal("1") + growth)
            )
            for pick, amount in scale.items()
        }
    return scale


def rookie_scale_schedule(
    season: str,
    draft_year: int,
    *,
    annual_cap_growth: Decimal = FUTURE_ANNUAL_CAP_GROWTH,
) -> list[dict[str, Any]]:
    resolved_season = clean(season)
    resolved_year = int(draft_year)
    expected_season = season_label_for_draft(resolved_year)
    if resolved_season != expected_season:
        raise ValueError(
            f"Draft {resolved_year} must feed season {expected_season}; "
            f"received {resolved_season!r}."
        )

    # Preserve the exact established 2026 bridge payload.
    if resolved_year == DRAFT_YEAR and resolved_season == SEASON_LABEL:
        return rookie_scale_schedule_2026_27()

    scale = rookie_scale_amounts_for_season(
        resolved_season,
        annual_cap_growth=annual_cap_growth,
    )
    return [
        {
            "season": resolved_season,
            "draft_year": resolved_year,
            "overall_pick": pick,
            "rookie_scale_amount": amount,
            "rookie_scale_cap_hold_amount": round_to_nearest_hundred(
                Decimal(amount) * CAP_HOLD_MULTIPLIER
            ),
            "cap_hold_multiplier": str(CAP_HOLD_MULTIPLIER),
            "derivation": (
                "cba_exhibit_b_rolled_forward_by_modeled_franchise_cap_growth"
            ),
            "cba_source_url": CBA_SOURCE_URL,
            "salary_cap_source_url": "",
            "projection_policy_source": FUTURE_SCALE_POLICY_SOURCE,
            "modeled_annual_cap_growth": str(annual_cap_growth),
        }
        for pick, amount in sorted(scale.items())
    ]


@dataclass(frozen=True)
class PostDraftFirstRoundPickHold:
    bridge_version: str
    season: str
    draft_year: int
    draft_event_id: str
    overall_pick: int
    round_number: int
    round_pick: int
    player_id: str
    player_name: str
    drafting_team: str
    rights_holder_team: str
    rookie_scale_amount: int
    rookie_scale_cap_hold_amount: int
    cap_hold_multiplier: str
    status: str
    source_record_index: int
    preview_only: bool
    applied_to_team_salary: bool
    state_mutation_applied: bool


def first(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if clean(value):
            return value
    return None


def selection_identity(selection: Mapping[str, Any]) -> dict[str, Any]:
    overall_pick = integer(first(selection, ("overall_pick", "pick_number", "pick", "selection_number")))
    round_number = integer(first(selection, ("round", "round_number", "draft_round")))
    if round_number is None and overall_pick is not None:
        round_number = 1 if 1 <= overall_pick <= 30 else 2 if 31 <= overall_pick <= 60 else None
    round_pick = integer(first(selection, ("round_pick", "pick_in_round")))
    if round_pick is None and overall_pick is not None and round_number in {1, 2}:
        round_pick = overall_pick if round_number == 1 else overall_pick - 30
    return {
        "overall_pick": overall_pick,
        "round_number": round_number,
        "round_pick": round_pick,
        "player_id": clean(first(selection, ("player_id", "prospect_id", "selected_player_id"))),
        "player_name": clean(first(selection, ("player_name", "prospect_name", "selected_player_name"))),
        "drafting_team": clean(first(selection, ("drafting_team", "owner_team", "team", "selected_by_team"))).upper(),
        "rights_holder_team": clean(first(selection, ("rights_holder_team", "current_owner_team_verified", "owner_team", "drafting_team", "team"))).upper(),
    }


def build_post_draft_first_round_pick_hold_preview(
    selections: Iterable[Mapping[str, Any]],
    *,
    draft_event_id: str,
    draft_year: int = DRAFT_YEAR,
    season: str = SEASON_LABEL,
    signed_player_ids: Iterable[Any] = (),
    rights_holder_by_player_id: Mapping[str, str] | None = None,
    hold_excluded_player_ids: Iterable[Any] = (),
) -> list[PostDraftFirstRoundPickHold]:
    resolved_season = clean(season)
    resolved_draft_year = int(draft_year)
    schedule_rows = rookie_scale_schedule(
        resolved_season,
        resolved_draft_year,
    )
    event_id = clean(draft_event_id)
    if not event_id:
        raise ValueError("A durable draft_event_id is required.")

    signed = {clean(value) for value in signed_player_ids if clean(value)}
    excluded = {clean(value) for value in hold_excluded_player_ids if clean(value)}
    assignments = {clean(key): clean(value).upper() for key, value in (rights_holder_by_player_id or {}).items()}
    schedule = {row["overall_pick"]: row for row in schedule_rows}
    rows: list[PostDraftFirstRoundPickHold] = []
    seen_picks: set[int] = set()
    seen_players: set[str] = set()

    for index, raw in enumerate(selections):
        if not isinstance(raw, Mapping):
            raise TypeError(f"Selection {index} is not a mapping.")
        identity = selection_identity(raw)
        overall_pick = identity["overall_pick"]
        round_number = identity["round_number"]
        if round_number != 1:
            continue
        if overall_pick not in schedule:
            raise ValueError(f"First-round selection {index} has invalid overall pick {overall_pick!r}.")
        player_id = identity["player_id"]
        if not player_id:
            raise ValueError(f"First-round selection at pick {overall_pick} has no player/prospect id.")
        if overall_pick in seen_picks:
            raise ValueError(f"Duplicate first-round overall pick {overall_pick}.")
        if player_id in seen_players:
            raise ValueError(f"Duplicate first-round selected player {player_id}.")
        seen_picks.add(overall_pick)
        seen_players.add(player_id)
        if player_id in signed or player_id in excluded:
            continue

        rights_holder = assignments.get(player_id, identity["rights_holder_team"])
        if not rights_holder:
            raise ValueError(f"First-round selection at pick {overall_pick} has no rights holder.")
        scale = schedule[overall_pick]
        rows.append(PostDraftFirstRoundPickHold(
            bridge_version=BRIDGE_VERSION,
            season=resolved_season,
            draft_year=resolved_draft_year,
            draft_event_id=event_id,
            overall_pick=overall_pick,
            round_number=1,
            round_pick=int(identity["round_pick"] or overall_pick),
            player_id=player_id,
            player_name=identity["player_name"],
            drafting_team=identity["drafting_team"],
            rights_holder_team=rights_holder,
            rookie_scale_amount=int(scale["rookie_scale_amount"]),
            rookie_scale_cap_hold_amount=int(scale["rookie_scale_cap_hold_amount"]),
            cap_hold_multiplier=str(CAP_HOLD_MULTIPLIER),
            status="unsigned_first_round_pick_hold_preview",
            source_record_index=index,
            preview_only=True,
            applied_to_team_salary=False,
            state_mutation_applied=False,
        ))
    return sorted(rows, key=lambda row: row.overall_pick)


def hold_rows(records: Iterable[PostDraftFirstRoundPickHold]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]


def team_hold_totals(records: Iterable[PostDraftFirstRoundPickHold]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        totals[record.rights_holder_team] = totals.get(record.rights_holder_team, 0) + record.rookie_scale_cap_hold_amount
    return totals


def pending_contract_player_ids(state: Any) -> set[str]:
    players = getattr(state, "players", {})
    if not isinstance(players, dict):
        return set()
    pending: set[str] = set()
    for raw_id, player in players.items():
        player_id = clean(raw_id)
        contract = getattr(player, "contract", None)
        status = clean(getattr(contract, "status", "")).lower()
        if player_id and status in PENDING_CONTRACT_STATUSES:
            pending.add(player_id)
    return pending


def completed_selection_rows(current: Mapping[str, Any]) -> list[dict[str, Any]]:
    draft_order = current.get("draft_order", [])
    if not isinstance(draft_order, list):
        raise ValueError("Draft state does not expose a draft_order list.")
    rows: list[dict[str, Any]] = []
    for raw in draft_order:
        if not isinstance(raw, Mapping):
            continue
        if not clean(first(raw, ("prospect_id", "player_id", "selected_player_id"))):
            continue
        rows.append(dict(raw))
    return rows


def sync_post_draft_first_round_pick_hold_ledger(
    state: Any,
    current: Mapping[str, Any],
    *,
    draft_event_id: str | None = None,
    rights_holder_by_player_id: Mapping[str, str] | None = None,
    hold_excluded_player_ids: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Synchronize the dynamic ledger after a simulated Draft selection.

    This function mutates only the supplied simulation candidate. The durable
    checkpoint is written exclusively by the caller's existing transaction
    flow. Repeated calls with the same Draft state are idempotent.
    """
    if not isinstance(current, Mapping):
        raise TypeError("Current Draft state must be a mapping.")
    draft_year = integer(current.get("draft_year"))
    if draft_year is None:
        raise ValueError("Current Draft state has no valid draft_year.")
    source_season = clean(current.get("source_season"))
    target_season = (
        clean(current.get("target_season"))
        or season_label_for_draft(draft_year)
    )
    # Resolve/validate the modeled scale before mutating the supplied state.
    rookie_scale_schedule(target_season, draft_year)
    event_id = clean(draft_event_id) or f"DRAFT-{draft_year}"
    selections = completed_selection_rows(current)
    pending = pending_contract_player_ids(state)
    all_selected_ids = {
        clean(first(row, ("prospect_id", "player_id", "selected_player_id")))
        for row in selections
    }
    signed = all_selected_ids - pending
    records = build_post_draft_first_round_pick_hold_preview(
        selections,
        draft_event_id=event_id,
        draft_year=draft_year,
        season=target_season,
        signed_player_ids=signed,
        rights_holder_by_player_id=rights_holder_by_player_id,
        hold_excluded_player_ids=hold_excluded_player_ids,
    )
    rows = hold_rows(records)
    setattr(state, STATE_LEDGER_ATTR, rows)
    setattr(state, STATE_METADATA_ATTR, {
        "bridge_version": BRIDGE_VERSION,
        "draft_event_id": event_id,
        "draft_year": draft_year,
        "source_season": source_season,
        "target_season": target_season,
        "completed_selection_count": len(selections),
        "active_hold_count": len(rows),
        "active_hold_total": sum(int(row["rookie_scale_cap_hold_amount"]) for row in rows),
        "last_sync_reason": "simulated_draft_selection",
        "applied_to_opening_snapshot": False,
        "financial_snapshot_bridge_enabled": True,
    })
    return rows


def active_post_draft_first_round_pick_hold_rows(state: Any) -> list[dict[str, Any]]:
    ledger = getattr(state, STATE_LEDGER_ATTR, [])
    if not isinstance(ledger, list):
        raise ValueError("Post-draft first-round pick-hold ledger is not a list.")
    pending = pending_contract_player_ids(state)
    active: list[dict[str, Any]] = []
    seen_players: set[str] = set()
    seen_picks: set[int] = set()
    for raw in ledger:
        if not isinstance(raw, Mapping):
            raise ValueError("Post-draft pick-hold ledger contains a non-mapping row.")
        player_id = clean(raw.get("player_id"))
        overall_pick = integer(raw.get("overall_pick"))
        if player_id not in pending:
            continue
        if overall_pick not in range(1, 31):
            raise ValueError(f"Active first-round hold has invalid pick {overall_pick!r}.")
        if player_id in seen_players or overall_pick in seen_picks:
            raise ValueError("Active post-draft pick-hold ledger contains a duplicate player or pick.")
        row_season = clean(raw.get("season"))
        row_draft_year = integer(raw.get("draft_year"))
        if (
            row_draft_year is None
            or row_season != season_label_for_draft(row_draft_year)
        ):
            raise ValueError(
                "Active post-draft pick-hold row has an invalid season/draft relationship."
            )
        # Also enforce the bounded scale authority for the persisted row's season.
        rookie_scale_amounts_for_season(row_season)
        if not clean(raw.get("rights_holder_team")):
            raise ValueError("Active post-draft pick-hold row has no rights holder.")
        if bool(raw.get("applied_to_team_salary")) or bool(raw.get("state_mutation_applied")):
            raise ValueError("Persisted bridge evidence row incorrectly claims direct application.")
        seen_players.add(player_id)
        seen_picks.add(int(overall_pick))
        active.append(dict(raw))
    return sorted(active, key=lambda row: int(row["overall_pick"]))


def active_team_pick_hold_totals(state: Any) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in active_post_draft_first_round_pick_hold_rows(state):
        team = clean(row.get("rights_holder_team")).upper()
        totals[team] = totals.get(team, 0) + int(row["rookie_scale_cap_hold_amount"])
    return totals
