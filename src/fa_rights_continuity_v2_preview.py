from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "fa-rights-continuity-resolver-v2-preview-2026-08-14"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)

# CBA "Season" begins on the first day of NBA training camp.
# These are conservative earliest league training-camp dates for each
# qualifying season. The 2025-26 window is intentionally truncated at
# the simulation split rather than importing the real 2026 offseason.
SEASON_WINDOWS = {
    2023: (date(2023, 9, 24), date(2024, 6, 17)),
    2024: (date(2024, 9, 25), date(2025, 6, 22)),
    2025: (date(2025, 9, 24), SIMULATION_SPLIT_DATE),
}
SEASON_LABELS = {
    2023: "2023-24",
    2024: "2024-25",
    2025: "2025-26",
}

EXPECTED_POPULATION_VERSION_PREFIX = (
    "franchise-free-agency-verified-bird-rights-population-v1-"
)
EXPECTED_EVIDENCE_VERSION_PREFIX = (
    "franchise-free-agency-rights-external-evidence-harvest-v1.0.1-"
)

NBA_TEAMS = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
    "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}

SIGNING_TYPES = {
    "Signed to Veteran Contract",
    "Signed to Two-Way Contract",
    "Signed to Rookie Contract",
    "Signed to Rookie Scale Contract",
    "Signed to 10-Day Contract",
    "Signed to Exhibit 10",
}

ON_CONTRACT_EVENTS = {
    "Recalled from G-League",
    "Reassigned to G-League",
    "Assigned to G-League",
    "Inactive List",
    "Activated from Inactive List",
    "Activated from Disabled",
    "Disabled List",
    "Suspended Inactive List",
    "Placed on waivers",
    "Cleared waivers",
    "Contract terminated",
    "Contract boughtout",
    "Team Option: Accepted",
    "Player Option: Accepted",
    "Signed to Veteran Extension",
}

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def team(value: Any) -> str:
    text = clean(value).upper()
    return text if text in NBA_TEAMS else ""

def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"1", "true", "yes", "y"}

def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 0 and number == number and number != float("inf"):
        return number
    return None

def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(name).decode("utf-8-sig"))
        )
    )

def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing {suffix}")
    return json.loads(archive.read(name).decode("utf-8-sig"))

def find_population_zip(root: Path) -> Path:
    candidates = [
        p for p in root.rglob("franchise_free_agency_rights_population_*.zip")
        if p.is_file()
        and "provenance" not in p.name.lower()
        and "external" not in p.name.lower()
        and "continuity" not in p.name.lower()
    ]
    if not candidates:
        raise RuntimeError("Could not locate V1 rights-population audit ZIP.")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def find_external_evidence_zip(root: Path) -> Path:
    candidates = [
        p for p in root.rglob(
            "franchise_free_agency_rights_external_evidence_v1_0_1_*.zip"
        )
        if p.is_file() and "continuity" not in p.name.lower()
    ]
    if not candidates:
        raise RuntimeError(
            "Could not locate corrected V1.0.1 external-evidence ZIP."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return (
            root
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        )

def parse_iso_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

def cap_season_start(day: date) -> int:
    return day.year if day.month >= 7 else day.year - 1

def observed_seasons(value: Any) -> set[int]:
    result: set[int] = set()
    for item in clean(value).split("|"):
        match = re.match(r"^(20\d{2})-", item.strip())
        if match:
            year = int(match.group(1))
            if year in SEASON_WINDOWS:
                result.add(year)
    return result

def event_priority(text: str) -> int:
    # Semantic ordering fixes same-day conversion and sign-and-trade records:
    # termination first, new signing next, assignment/trade last.
    if text == "Hold Renounced":
        return 10
    if text == "Placed on waivers":
        return 20
    if text == "Contract boughtout":
        return 25
    if text == "Contract terminated":
        return 30
    if text == "Cleared waivers":
        return 40
    if text in SIGNING_TYPES:
        return 50
    if text.startswith("Claimed on waivers"):
        return 60
    if text.startswith("Traded from "):
        return 70
    if text == "Signed to Veteran Extension":
        return 80
    return 90

def event_proves_contract(text: str) -> bool:
    return (
        text in SIGNING_TYPES
        or text.startswith("Traded from ")
        or text.startswith("Claimed on waivers")
        or text in ON_CONTRACT_EVENTS
    )

def rows_by_player(
    rows: Iterable[dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        player = pid(raw.get("player_id"))
        day = parse_iso_date(raw.get("transaction_date"))
        if not player or day is None:
            continue
        row: dict[str, Any] = dict(raw)
        row["_date"] = day
        row["_priority"] = event_priority(clean(raw.get("transaction")))
        result.setdefault(player, []).append(row)
    for player_rows in result.values():
        player_rows.sort(
            key=lambda r: (r["_date"], r["_priority"], clean(r.get("transaction")))
        )
    return result

def season_coverage(
    candidate: Mapping[str, Any],
    transactions: list[dict[str, Any]],
) -> set[int]:
    coverage = observed_seasons(candidate.get("observed_seasons"))
    for season_start, (window_start, window_end) in SEASON_WINDOWS.items():
        if season_start in coverage:
            continue
        for row in transactions:
            day = row["_date"]
            if (
                window_start <= day <= window_end
                and event_proves_contract(clean(row.get("transaction")))
            ):
                coverage.add(season_start)
                break
    return coverage

def initial_2023_team(transactions: list[dict[str, Any]]) -> str:
    start, end = SEASON_WINDOWS[2023]
    for row in transactions:
        if not (start <= row["_date"] <= end):
            continue
        if event_proves_contract(clean(row.get("transaction"))):
            resolved = team(row.get("team_abbreviation"))
            if resolved:
                return resolved
    return ""

@dataclass
class TimelineResult:
    final_team: str
    final_contract_type: str
    terminal_kind: str
    coverage: tuple[int, ...]
    last_reset_season: int | None
    waiver_claim_seasons: tuple[int, ...]
    article_vii_8b_candidates: tuple[str, ...]
    timeline_fingerprint: str
    evidence_detail: str

def analyze_timeline(
    candidate: Mapping[str, Any],
    transactions: list[dict[str, Any]],
) -> TimelineResult:
    coverage = season_coverage(candidate, transactions)
    first_team = initial_2023_team(transactions)

    current_team = first_team
    last_team = first_team
    final_contract_type = ""
    reset_seasons: list[int] = []
    waiver_claim_seasons: list[int] = []
    signing_records: list[tuple[date, int, str, str, str, bool]] = []
    trade_records: list[tuple[date, int, str, str]] = []
    renounced_since_contract = False

    material: list[tuple[date, int, str, str, str]] = []
    timeline_for_hash: list[dict[str, Any]] = []

    for row in transactions:
        day = row["_date"]
        text = clean(row.get("transaction"))
        event_team = team(row.get("team_abbreviation"))
        cap_season = cap_season_start(day)

        timeline_for_hash.append({
            "date": day.isoformat(),
            "team": event_team,
            "transaction": text,
            "source_sha256": clean(row.get("source_sha256")),
        })

        if text == "Hold Renounced":
            if cap_season in SEASON_WINDOWS:
                reset_seasons.append(cap_season)
            current_team = ""
            last_team = event_team or last_team
            renounced_since_contract = True
            continue

        if text in {"Cleared waivers", "Contract terminated"}:
            last_team = current_team or event_team or last_team
            current_team = ""
            material.append((
                day,
                event_priority(text),
                "cleared" if text == "Cleared waivers" else "terminated",
                event_team,
                text,
            ))
            continue

        if text in SIGNING_TYPES:
            reference_team = current_team or last_team
            reset = (
                renounced_since_contract
                or (bool(reference_team) and event_team != reference_team)
                or not reference_team
            )
            if reset and cap_season in SEASON_WINDOWS:
                reset_seasons.append(cap_season)

            current_team = event_team
            last_team = event_team
            final_contract_type = text
            renounced_since_contract = False
            signing_records.append((
                day,
                cap_season,
                event_team,
                text,
                reference_team,
                reset,
            ))
            material.append((
                day,
                event_priority(text),
                "sign",
                event_team,
                text,
            ))
            continue

        if text.startswith("Claimed on waivers"):
            if cap_season in SEASON_WINDOWS:
                waiver_claim_seasons.append(cap_season)
            current_team = event_team
            last_team = event_team
            renounced_since_contract = False
            material.append((
                day,
                event_priority(text),
                "claim",
                event_team,
                text,
            ))
            continue

        if text.startswith("Traded from "):
            current_team = event_team
            last_team = event_team
            renounced_since_contract = False
            trade_records.append((
                day,
                cap_season,
                event_team,
                text,
            ))
            material.append((
                day,
                event_priority(text),
                "trade",
                event_team,
                text,
            ))
            continue

        if text == "Signed to Veteran Extension":
            current_team = event_team or current_team
            last_team = current_team or last_team

    material.sort(key=lambda item: (item[0], item[1], item[4]))
    final_material = material[-1] if material else None

    if final_material is None:
        terminal_kind = "no_transaction_evidence"
        final_team = ""
    elif final_material[2] == "cleared":
        terminal_kind = "waiver_terminated_free_agent"
        final_team = ""
    elif final_material[2] == "terminated":
        terminal_kind = "contract_termination_requires_review"
        final_team = ""
    elif (
        final_material[2] == "sign"
        and final_material[4] == "Signed to 10-Day Contract"
    ):
        terminal_kind = "ten_day_free_agent"
        final_team = final_material[3]
    else:
        terminal_kind = "veteran_free_agent"
        final_team = final_material[3] or current_team or last_team

    last_reset = max(reset_seasons) if reset_seasons else (
        min(coverage) if coverage else None
    )

    article_8b: list[str] = []
    for trade_day, trade_season, destination, trade_text in trade_records:
        source_team = team(trade_text.replace("Traded from ", ""))
        preceding = [s for s in signing_records if s[0] < trade_day]
        if not preceding:
            continue
        signing = max(preceding, key=lambda item: item[0])
        sign_day, sign_season, sign_team, sign_type, _, sign_reset = signing

        # Article VII 8(b) excludes Two-Way players. A same-day signing and
        # trade is treated as a sign-and-trade pattern and is not flagged here.
        if (
            sign_season == trade_season
            and sign_type == "Signed to Veteran Contract"
            and sign_team == source_team
            and not sign_reset
        ):
            article_8b.append(
                f"{sign_day.isoformat()} {source_team} veteran signing -> "
                f"{trade_day.isoformat()} trade to {destination}"
            )

    fp = sha256_bytes(
        json.dumps(
            timeline_for_hash,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    return TimelineResult(
        final_team=final_team,
        final_contract_type=final_contract_type,
        terminal_kind=terminal_kind,
        coverage=tuple(sorted(coverage)),
        last_reset_season=last_reset,
        waiver_claim_seasons=tuple(sorted(set(waiver_claim_seasons))),
        article_vii_8b_candidates=tuple(article_8b),
        timeline_fingerprint=fp,
        evidence_detail="; ".join(
            [
                f"terminal={terminal_kind}",
                "coverage=" + "|".join(SEASON_LABELS[s] for s in sorted(coverage)),
                f"last_reset={SEASON_LABELS.get(last_reset, 'unknown') if last_reset else 'unknown'}",
                (
                    "waiver_claims="
                    + "|".join(SEASON_LABELS[s] for s in sorted(set(waiver_claim_seasons)))
                    if waiver_claim_seasons
                    else "waiver_claims=none"
                ),
            ]
        ),
    )

def classify_unresolved(
    candidate: Mapping[str, Any],
    timeline: TimelineResult,
) -> tuple[str, str, str, bool, str]:
    """
    Returns:
      status,
      rights_classification,
      free_agent_category,
      continuity_verified,
      reason
    """
    if timeline.terminal_kind == "waiver_terminated_free_agent":
        return (
            "proven_non_vfa",
            "not_applicable",
            "waiver_terminated_free_agent",
            True,
            (
                "CBA Free Agent category (iii): last contract was terminated "
                "through waivers; Bird/Early Bird/Non-Bird are Veteran Free "
                "Agent classifications and are not applied."
            ),
        )

    if timeline.terminal_kind == "ten_day_free_agent":
        return (
            "proven_non_vfa",
            "not_applicable",
            "ten_day_free_agent",
            True,
            (
                "CBA Free Agent category (iv): last Player Contract was a "
                "10-Day Contract; Veteran Free Agent rights class is not applied."
            ),
        )

    if timeline.terminal_kind != "veteran_free_agent":
        return (
            "manual_review",
            "unknown",
            timeline.terminal_kind,
            False,
            "External evidence does not establish a clean Veteran Free Agent terminal state.",
        )

    coverage = set(timeline.coverage)
    reset = timeline.last_reset_season

    bird_candidate = (
        {2023, 2024, 2025}.issubset(coverage)
        and reset is not None
        and reset <= 2023
        and not any(s > 2023 for s in timeline.waiver_claim_seasons)
    )
    early_candidate = (
        {2024, 2025}.issubset(coverage)
        and reset is not None
        and reset <= 2024
    )

    # Article VII 8(b): a qualifying one-year non-Two-Way contract can turn
    # what looks like a preserving trade into a free-agent team change.
    # Flag only when that uncertainty can alter the candidate class.
    if timeline.article_vii_8b_candidates:
        if bird_candidate:
            return (
                "manual_review",
                "unknown",
                "veteran_free_agent",
                False,
                "Article VII 8(b) one-year trade-consent provenance could change Bird continuity.",
            )
        if early_candidate and any(
            "2025-" in item or "2026-" in item
            for item in timeline.article_vii_8b_candidates
        ):
            return (
                "manual_review",
                "unknown",
                "veteran_free_agent",
                False,
                "Article VII 8(b) one-year trade-consent provenance could change Early Bird continuity.",
            )

    if bird_candidate:
        return (
            "proven",
            "bird",
            "veteran_free_agent",
            True,
            (
                "Contracts cover all three preceding Seasons and every "
                "within-window team change is a permitted continuity path."
            ),
        )

    if early_candidate:
        return (
            "proven",
            "early_bird",
            "veteran_free_agent",
            True,
            (
                "Contracts cover both preceding Seasons and every within-window "
                "team change is permitted for Early Bird continuity."
            ),
        )

    # Non-Bird is only auto-proven when a 2025-26 reset is affirmative.
    # Mere failure to prove older coverage is not used to downgrade rights.
    if reset == 2025:
        return (
            "proven",
            "non_bird",
            "veteran_free_agent",
            True,
            (
                "A continuity-resetting signing/renouncement path is explicitly "
                "observed in 2025-26, so two-season Early Bird continuity cannot exist."
            ),
        )

    return (
        "manual_review",
        "unknown",
        "veteran_free_agent",
        False,
        (
            "Evidence is insufficient to prove Bird/Early Bird, but there is no "
            "affirmative 2025-26 reset that safely proves Non-Bird."
        ),
    )

def salary_index(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        player = pid(row.get("player_id"))
        if player:
            result.setdefault(player, []).append(row)
    return result

def salary_resolution(
    player_id: str,
    timeline: TimelineResult,
    salaries: dict[str, list[dict[str, str]]],
) -> tuple[str, float | None, str]:
    rows = salaries.get(player_id, [])
    if not rows:
        return "missing_2025_26_salary", None, ""

    if len(rows) > 1:
        return (
            "multiple_rows_require_contract_sequence",
            None,
            "|".join(
                clean(row.get("base_salary"))
                for row in rows
                if clean(row.get("base_salary"))
            ),
        )

    row = rows[0]
    base = finite_float(row.get("base_salary_numeric"))
    raw = clean(row.get("base_salary"))

    if base is None:
        return "single_row_non_numeric", None, raw

    if timeline.final_contract_type == "Signed to Two-Way Contract":
        return (
            "two_way_salary_requires_financial_rule_review",
            None,
            raw,
        )

    return "single_standard_salary_ready", base, raw

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def main() -> int:
    root = Path.cwd().resolve()
    population_zip = find_population_zip(root)
    evidence_zip = find_external_evidence_zip(root)

    with zipfile.ZipFile(population_zip) as archive:
        population_summary = read_json_member(
            archive, "rights_population_summary.json"
        )
        population_candidates = read_csv_member(
            archive, "rights_population_candidates.csv"
        )
        population_proven = read_csv_member(
            archive, "rights_population_proven.csv"
        )
        population_unresolved = read_csv_member(
            archive, "rights_population_unresolved.csv"
        )

    with zipfile.ZipFile(evidence_zip) as archive:
        evidence_summary = read_json_member(
            archive, "rights_external_evidence_summary.json"
        )
        transaction_rows = read_csv_member(
            archive, "rights_external_transaction_rows.csv"
        )
        salary_rows = read_csv_member(
            archive, "rights_external_prior_salary_rows.csv"
        )

    print("=" * 118, flush=True)
    print("FREE AGENCY RIGHTS CONTINUITY RESOLVER V2 PREVIEW", flush=True)
    print("=" * 118, flush=True)
    print(f"Population ZIP: {population_zip}", flush=True)
    print(f"Evidence ZIP:   {evidence_zip}", flush=True)
    print(
        f"Simulation evidence split: {SIMULATION_SPLIT_DATE.isoformat()} "
        "(post-split real-world moves are audit-only)",
        flush=True,
    )
    print("", flush=True)

    if not clean(population_summary.get("version")).startswith(
        EXPECTED_POPULATION_VERSION_PREFIX
    ):
        raise RuntimeError("Unexpected rights-population version.")
    if not clean(evidence_summary.get("version")).startswith(
        EXPECTED_EVIDENCE_VERSION_PREFIX
    ):
        raise RuntimeError("Expected corrected V1.0.1 evidence harvest.")

    checkpoint = checkpoint_path(root)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    evidence_checkpoint = clean(
        evidence_summary.get("checkpoint_sha256_after")
    )
    evidence_overlay = clean(
        evidence_summary.get("rights_overlay_sha256_after")
    )

    pre_split_rows: list[dict[str, str]] = []
    post_split_rows: list[dict[str, str]] = []
    for row in transaction_rows:
        day = parse_iso_date(row.get("transaction_date"))
        if day is None:
            continue
        if day <= SIMULATION_SPLIT_DATE:
            pre_split_rows.append(row)
        else:
            copied = dict(row)
            copied["ignored_reason"] = (
                "post-2025-26-regular-season real-world event; "
                "outside simulator counterfactual starting state"
            )
            post_split_rows.append(copied)

    transactions = rows_by_player(pre_split_rows)
    salaries = salary_index(salary_rows)

    unresolved_ids = {
        pid(row.get("player_id")) for row in population_unresolved
    }
    proven_ids = {
        pid(row.get("player_id")) for row in population_proven
    }

    print("[1/5] Resolving 161 previously-unresolved players...", flush=True)
    resolved_rows: list[dict[str, Any]] = []
    timeline_rows: list[dict[str, Any]] = []

    for candidate in population_unresolved:
        player_id = pid(candidate.get("player_id"))
        player_name = clean(candidate.get("player_name"))
        tx = transactions.get(player_id, [])
        timeline = analyze_timeline(candidate, tx)

        (
            status,
            rights_classification,
            free_agent_category,
            continuity_verified,
            reason,
        ) = classify_unresolved(candidate, timeline)

        salary_status, proposed_salary, salary_text = salary_resolution(
            player_id, timeline, salaries
        )

        prior_team = team(candidate.get("prior_team"))
        proposed_prior_team = (
            timeline.final_team
            if free_agent_category == "veteran_free_agent"
            and timeline.final_team
            else prior_team
        )

        resolved_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "season_label": SEASON_LABEL,
            "v1_status": clean(candidate.get("status")),
            "v1_rights_classification": clean(
                candidate.get("rights_classification")
            ),
            "preview_status": status,
            "preview_rights_classification": rights_classification,
            "free_agent_category": free_agent_category,
            "v1_prior_team": prior_team,
            "preview_prior_team": proposed_prior_team,
            "prior_team_matches_v1": (
                not timeline.final_team
                or timeline.final_team == prior_team
            ),
            "continuity_verified": continuity_verified,
            "qualifying_season_count": len(timeline.coverage),
            "qualifying_seasons": "|".join(
                SEASON_LABELS[s] for s in timeline.coverage
            ),
            "last_continuity_reset_season": (
                SEASON_LABELS.get(timeline.last_reset_season, "")
                if timeline.last_reset_season is not None
                else ""
            ),
            "waiver_claim_seasons": "|".join(
                SEASON_LABELS[s] for s in timeline.waiver_claim_seasons
            ),
            "final_contract_type": timeline.final_contract_type,
            "terminal_kind": timeline.terminal_kind,
            "article_vii_8b_candidate_count": len(
                timeline.article_vii_8b_candidates
            ),
            "article_vii_8b_candidates": "|".join(
                timeline.article_vii_8b_candidates
            ),
            "salary_evidence_status": salary_status,
            "proposed_prior_regular_salary": proposed_salary,
            "salary_evidence_text": salary_text,
            "years_of_service": clean(candidate.get("years_of_service")),
            "classification_reason": reason,
            "timeline_evidence_detail": timeline.evidence_detail,
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "external_transaction_row_count": len(tx),
            "rights_overlay_write_performed": False,
        })

        timeline_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "transaction_row_count_through_split": len(tx),
            "coverage": "|".join(
                SEASON_LABELS[s] for s in timeline.coverage
            ),
            "final_team": timeline.final_team,
            "final_contract_type": timeline.final_contract_type,
            "terminal_kind": timeline.terminal_kind,
            "last_reset_season": (
                SEASON_LABELS.get(timeline.last_reset_season, "")
                if timeline.last_reset_season is not None
                else ""
            ),
        })

    print("[2/5] Preserving all 26 V1-proven rows verbatim...", flush=True)
    preserved_rows: list[dict[str, Any]] = []
    for row in population_proven:
        preserved_rows.append({
            "player_id": pid(row.get("player_id")),
            "player_name": clean(row.get("player_name")),
            "season_label": clean(row.get("season_label")),
            "preview_status": "preserved_v1_proven",
            "preview_rights_classification": clean(
                row.get("rights_classification")
            ),
            "free_agent_category": "veteran_free_agent",
            "preview_prior_team": team(row.get("prior_team")),
            "continuity_verified": as_bool(row.get("continuity_verified")),
            "proposed_prior_regular_salary": finite_float(
                row.get("prior_regular_salary")
            ),
            "source": "V1 proven row preserved without reclassification",
            "evidence_fingerprint": clean(row.get("evidence_fingerprint")),
        })

    all_preview_ids = {
        row["player_id"] for row in resolved_rows
    } | {
        row["player_id"] for row in preserved_rows
    }

    print("[3/5] Running strict CBA/snapshot safety checks...", flush=True)
    checks: list[dict[str, Any]] = []
    def check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(
            f"      {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    check(
        "input_population_is_v1",
        clean(population_summary.get("version")).startswith(
            EXPECTED_POPULATION_VERSION_PREFIX
        ),
        "Uses reviewed V1 rights population.",
    )
    check(
        "input_evidence_is_v1_0_1",
        clean(evidence_summary.get("version")).startswith(
            EXPECTED_EVIDENCE_VERSION_PREFIX
        ),
        "Uses identity-verified V1.0.1 external evidence.",
    )
    check(
        "population_partition_is_26_plus_161",
        len(population_proven) == 26
        and len(population_unresolved) == 161
        and len(proven_ids | unresolved_ids) == 187
        and not (proven_ids & unresolved_ids),
        "Original V1 partition is preserved.",
    )
    check(
        "preview_contains_exactly_187_unique_players",
        len(all_preview_ids) == 187
        and len(resolved_rows) == 161
        and len(preserved_rows) == 26,
        "Every original free agent receives exactly one preview disposition.",
    )
    check(
        "all_post_split_transactions_are_excluded",
        all(
            (parse_iso_date(row.get("transaction_date")) or date.min)
            <= SIMULATION_SPLIT_DATE
            for row in pre_split_rows
        ),
        "No transaction after 2026-04-12 can influence classification.",
    )
    check(
        "non_vfa_rows_never_receive_veteran_rights_class",
        all(
            row["preview_rights_classification"] == "not_applicable"
            for row in resolved_rows
            if row["free_agent_category"] in {
                "waiver_terminated_free_agent",
                "ten_day_free_agent",
            }
        ),
        "Waiver-terminated and last-10-day free agents are not forced into Bird/Early/Non-Bird.",
    )
    check(
        "bird_requires_three_qualifying_seasons",
        all(
            row["qualifying_season_count"] == 3
            for row in resolved_rows
            if row["preview_rights_classification"] == "bird"
        ),
        "Bird requires contracts covering all three preceding Seasons.",
    )
    check(
        "early_bird_requires_two_qualifying_seasons",
        all(
            {"2024-25", "2025-26"}.issubset(
                set(clean(row["qualifying_seasons"]).split("|"))
            )
            for row in resolved_rows
            if row["preview_rights_classification"] == "early_bird"
        ),
        "Early Bird requires both immediately preceding Seasons.",
    )
    check(
        "non_bird_requires_affirmative_2025_26_reset",
        all(
            row["last_continuity_reset_season"] == "2025-26"
            for row in resolved_rows
            if row["preview_rights_classification"] == "non_bird"
        ),
        "Absence of older evidence alone can never auto-downgrade a player to Non-Bird.",
    )
    check(
        "automatic_vfa_prior_team_matches_checkpoint_population",
        all(
            row["prior_team_matches_v1"]
            for row in resolved_rows
            if row["preview_status"] == "proven"
            and row["free_agent_category"] == "veteran_free_agent"
        ),
        "Automatic Veteran FA classifications must resolve to the same Prior Team as the simulator population.",
    )
    check(
        "v1_proven_classes_are_preserved",
        all(
            row["preview_rights_classification"]
            == clean(
                next(
                    p for p in population_proven
                    if pid(p.get("player_id")) == row["player_id"]
                ).get("rights_classification")
            )
            for row in preserved_rows
        ),
        "No previously-proven Bird/Early Bird row is reclassified.",
    )
    check(
        "checkpoint_matches_evidence_anchor",
        not evidence_checkpoint
        or checkpoint_before == evidence_checkpoint,
        (
            f"Current checkpoint={checkpoint_before}; "
            f"evidence anchor={evidence_checkpoint}"
        ),
    )
    check(
        "rights_overlay_matches_evidence_anchor",
        overlay_before == evidence_overlay,
        (
            f"Current overlay hash={overlay_before or '<absent>'}; "
            f"evidence anchor={evidence_overlay or '<absent>'}"
        ),
    )

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "Preview is read-only.",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "Preview does not apply the rights overlay.",
    )

    failed_strict = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "Continuity V2 preview failed strict checks: "
            + ", ".join(failed_strict)
        )

    print("[4/5] Building audit package...", flush=True)
    rights_counts = Counter(
        row["preview_rights_classification"]
        for row in resolved_rows
    )
    category_counts = Counter(
        row["free_agent_category"]
        for row in resolved_rows
    )
    salary_counts = Counter(
        row["salary_evidence_status"]
        for row in resolved_rows
    )

    manual_rows = [
        row for row in resolved_rows
        if row["preview_status"] == "manual_review"
        or row["salary_evidence_status"] in {
            "missing_2025_26_salary",
            "multiple_rows_require_contract_sequence",
            "two_way_salary_requires_financial_rule_review",
            "single_row_non_numeric",
        }
    ]

    auto_overlay_candidates = [
        row for row in resolved_rows
        if row["preview_status"] == "proven"
        and row["preview_rights_classification"] in {
            "bird", "early_bird", "non_bird"
        }
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_rights_continuity_v2_preview_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="farcv2_") as tmp:
        export = Path(tmp) / export_id
        export.mkdir(parents=True)

        write_csv(export / "continuity_preview_resolved.csv", resolved_rows)
        write_csv(export / "continuity_preview_preserved_v1.csv", preserved_rows)
        write_csv(export / "continuity_preview_timelines.csv", timeline_rows)
        write_csv(export / "continuity_preview_manual_queue.csv", manual_rows)
        write_csv(
            export / "continuity_preview_overlay_candidates.csv",
            auto_overlay_candidates,
        )
        write_csv(
            export / "continuity_preview_ignored_post_split_transactions.csv",
            post_split_rows,
        )
        write_csv(export / "continuity_preview_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "population_zip": str(population_zip),
            "population_zip_sha256": sha256_file(population_zip),
            "evidence_zip": str(evidence_zip),
            "evidence_zip_sha256": sha256_file(evidence_zip),
            "total_free_agents": 187,
            "v1_proven_preserved": len(preserved_rows),
            "v1_unresolved_reviewed": len(resolved_rows),
            "resolved_rights_classification_counts": dict(
                sorted(rights_counts.items())
            ),
            "resolved_free_agent_category_counts": dict(
                sorted(category_counts.items())
            ),
            "salary_evidence_status_counts": dict(
                sorted(salary_counts.items())
            ),
            "automatic_rights_overlay_candidate_count": len(
                auto_overlay_candidates
            ),
            "manual_or_salary_review_queue_count": len(manual_rows),
            "ignored_post_split_transaction_rows": len(post_split_rows),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "classification_preview_only": True,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "failed_strict_checks": failed_strict,
            "passed": not failed_strict,
            "cba_boundaries": {
                "bird": (
                    "Veteran FA + contracts covering some/all of each of "
                    "three preceding Seasons + permitted team-change paths."
                ),
                "early_bird": (
                    "Veteran FA + contracts covering some/all of each of "
                    "two preceding Seasons + permitted team-change paths."
                ),
                "non_bird": (
                    "Veteran FA that is neither Bird nor Early Bird; preview "
                    "requires an affirmative 2025-26 continuity reset before "
                    "auto-proving this class."
                ),
                "waiver_terminated": (
                    "Separate Free Agent category; no Veteran FA rights class."
                ),
                "last_10_day": (
                    "Separate Free Agent category; no Veteran FA rights class."
                ),
            },
        }
        (export / "continuity_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = f"""FREE AGENCY RIGHTS CONTINUITY RESOLVER V2 PREVIEW

Version: {VERSION}

READ-ONLY PREVIEW
-----------------
This package DOES NOT write a Bird-rights overlay and DOES NOT mutate the
franchise checkpoint, rosters, contracts, trades, or signings.

Simulation split
----------------
The simulator's free-agent population is treated as a counterfactual offseason
branch after the 2025-26 regular season. Classification evidence therefore
stops at {SIMULATION_SPLIT_DATE.isoformat()}. Later real-world transaction rows
remain in the audit under:
  continuity_preview_ignored_post_split_transactions.csv

CBA logic represented
---------------------
1. Bird / Qualifying Veteran Free Agent:
   contracts cover some/all of all three preceding Seasons, with team changes
   restricted to the CBA-permitted continuity paths.

2. Early Bird / Early Qualifying Veteran Free Agent:
   contracts cover some/all of both preceding Seasons, with CBA-permitted
   continuity paths.

3. Non-Bird / Non-Qualifying Veteran Free Agent:
   only auto-proven here when a 2025-26 continuity-resetting event is explicit.
   Missing older evidence alone never downgrades a player.

4. Waiver-terminated free agents:
   a Veteran whose Player Contract was terminated via the NBA waiver procedure
   is a separate CBA Free Agent category. The preview marks Bird/Early/Non-Bird
   not applicable.

5. Last 10-Day Contract:
   also a separate CBA Free Agent category. Bird/Early/Non-Bird is not applied.

6. Article VII Section 8(b):
   a qualifying one-year non-Two-Way contract can make a later trade count as
   a free-agent team change for future Bird-rights purposes. Any case where
   that uncertainty can change the result fails closed to manual review.

Evidence sources
----------------
- Reviewed V1 population audit
- Identity-verified V1.0.1 SalarySwish transaction/contract harvest
- Current 2023 NBA-NBPA CBA as the rule specification

Important financial boundary
----------------------------
This preview separates RIGHTS CLASSIFICATION from PRIOR-SALARY resolution.
A single standard-contract 2025-26 salary row may be marked ready. Multiple
rows remain unresolved until contract sequence is proven. A final Two-Way
salary is not blindly written into prior_regular_salary because the financial
treatment needs its own CBA-aware bridge.

Expected output
---------------
outputs/audits/{export_id}.zip
"""
        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(
            zip_out,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    print("[5/5] Final durable-state verification...", flush=True)
    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed during preview export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed during preview export.")

    print("", flush=True)
    print("=" * 118, flush=True)
    print("FREE AGENCY RIGHTS CONTINUITY RESOLVER V2 PREVIEW PASSED", flush=True)
    print("=" * 118, flush=True)
    print(f"Bird:           {rights_counts.get('bird', 0)}", flush=True)
    print(f"Early Bird:     {rights_counts.get('early_bird', 0)}", flush=True)
    print(f"Non-Bird:       {rights_counts.get('non_bird', 0)}", flush=True)
    print(
        f"Not applicable: {rights_counts.get('not_applicable', 0)}",
        flush=True,
    )
    print(f"Manual review:  {rights_counts.get('unknown', 0)}", flush=True)
    print(
        f"V1 proven preserved: {len(preserved_rows)}",
        flush=True,
    )
    print(
        f"Automatic rights overlay candidates: {len(auto_overlay_candidates)}",
        flush=True,
    )
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
