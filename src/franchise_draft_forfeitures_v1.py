from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


DRAFT_FORFEITURE_RULESET_VERSION = (
    "franchise-draft-forfeitures-v1-2026-09-07"
)
NBA_CLIPPERS_SANCTIONS_URL = (
    "https://www.nba.com/news/nba-investigation-findings-la-clippers"
)
CLIPPERS_2029_ASSET_DETAIL_URL = (
    "https://basketball.realgm.com/nba/draft/future_drafts/detailed"
)


@dataclass(frozen=True)
class DraftPickForfeiture:
    penalized_team: str
    draft_year: int
    round_number: int
    source_asset_id: str
    reason: str
    announced_date: str
    authority_url: str
    asset_detail_url: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


_CLIPPERS_REASON = (
    "Forfeited by the LA Clippers under the NBA sanctions announced "
    "September 2, 2026."
)

# The 2029 forfeiture is the Indiana-origin first acquired by the Clippers.
# The Clippers' separate 2029 LAC/PHI swap structure remains in the ledger.
DRAFT_PICK_FORFEITURES: tuple[DraftPickForfeiture, ...] = (
    DraftPickForfeiture(
        penalized_team="LAC",
        draft_year=2029,
        round_number=1,
        source_asset_id="2029_R1_IND",
        reason=_CLIPPERS_REASON,
        announced_date="2026-09-02",
        authority_url=NBA_CLIPPERS_SANCTIONS_URL,
        asset_detail_url=CLIPPERS_2029_ASSET_DETAIL_URL,
    ),
    *(
        DraftPickForfeiture(
            penalized_team="LAC",
            draft_year=year,
            round_number=1,
            source_asset_id=f"{year}_R1_LAC",
            reason=_CLIPPERS_REASON,
            announced_date="2026-09-02",
            authority_url=NBA_CLIPPERS_SANCTIONS_URL,
        )
        for year in range(2030, 2034)
    ),
)

_FORFEITURE_BY_SOURCE_ASSET = {
    item.source_asset_id: item
    for item in DRAFT_PICK_FORFEITURES
}
_SOURCE_ASSET_PATTERN = re.compile(r"\b20\d{2}_R[12]_[A-Z]{3}\b")


def forfeiture_for_source_asset(
    source_asset_id: Any,
) -> DraftPickForfeiture | None:
    return _FORFEITURE_BY_SOURCE_ASSET.get(
        str(source_asset_id or "").strip().upper()
    )


def is_forfeited_source_asset(source_asset_id: Any) -> bool:
    return forfeiture_for_source_asset(source_asset_id) is not None


def forfeitures_for_draft_year(draft_year: Any) -> tuple[DraftPickForfeiture, ...]:
    try:
        year = int(draft_year)
    except (TypeError, ValueError):
        return tuple()
    return tuple(
        item
        for item in DRAFT_PICK_FORFEITURES
        if item.draft_year == year
    )


def expected_draft_pick_count(
    draft_year: Any,
    team_count: int = 30,
    round_count: int = 2,
) -> int:
    base_count = max(0, int(team_count)) * max(0, int(round_count))
    return base_count - len(forfeitures_for_draft_year(draft_year))


def source_asset_ids_for_ledger_row(row: Mapping[str, Any]) -> tuple[str, ...]:
    source_text = str(row.get("source_assets") or "").upper()
    source_ids = tuple(dict.fromkeys(_SOURCE_ASSET_PATTERN.findall(source_text)))
    if source_ids:
        return source_ids

    try:
        draft_year = int(row.get("draft_year"))
        round_number = int(row.get("round"))
    except (TypeError, ValueError):
        return tuple()
    origin_team = str(row.get("origin_team") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", origin_team):
        return tuple()
    return (f"{draft_year}_R{round_number}_{origin_team}",)


def apply_draft_pick_forfeitures(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    resolved_rows: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        source_ids = source_asset_ids_for_ledger_row(row)
        forfeiture = (
            forfeiture_for_source_asset(source_ids[0])
            if len(source_ids) == 1
            else None
        )
        if forfeiture is None:
            row["forfeiture_status"] = "active"
            resolved_rows.append(row)
            continue

        row.update(
            {
                "current_owner_before_forfeiture": row.get("current_owner", ""),
                "current_owner": "",
                "asset_type_before_forfeiture": row.get("asset_type", ""),
                "asset_type": "forfeited_draft_pick",
                "tradability_status": "Forfeited · NBA Sanction",
                "manual_review_required": False,
                "manual_review_reason": "",
                "engine_ready": False,
                "forfeiture_status": "forfeited",
                "forfeited_source_asset_id": forfeiture.source_asset_id,
                "penalized_team": forfeiture.penalized_team,
                "forfeiture_reason": forfeiture.reason,
                "forfeiture_announced_date": forfeiture.announced_date,
                "forfeiture_authority_url": forfeiture.authority_url,
                "forfeiture_asset_detail_url": forfeiture.asset_detail_url,
            }
        )
        resolved_rows.append(row)
    return resolved_rows
