from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import unicodedata
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-official-option-and-zero-game-population-v4.1.1-preview-2026-08-14"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
MOVEMENT_START = date(2025, 7, 1)
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_BASE_PLAYERS = 582
EXPECTED_EXTENDED_PLAYERS = 587
OFFICIAL_OPTION_SOURCE = (
    "https://www.nba.com/news/2026-free-agency-options-and-qualifying-offers"
)

TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

# The outcome column is audit-only. The simulator imports only option existence/type.
OFFICIAL_OPTIONS = [
    ("Deandre Ayton", "player_option", "LAL", "exercised"),
    ("Kentavious Caldwell-Pope", "player_option", "MEM", "exercised"),
    ("Gary Harris", "player_option", "MIL", "exercised"),
    ("Zach LaVine", "player_option", "SAC", "exercised"),
    ("Kevin Porter Jr.", "player_option", "MIL", "exercised"),
    ("Taurean Prince", "player_option", "MIL", "exercised"),
    ("D'Angelo Russell", "player_option", "WAS", "exercised"),
    ("Jericho Sims", "player_option", "MIL", "exercised"),
    ("Fred VanVleet", "player_option", "HOU", "exercised"),
    ("Andrew Wiggins", "player_option", "MIA", "exercised"),
    ("Jose Alvarado", "player_option", "NYK", "declined"),
    ("Bradley Beal", "player_option", "LAC", "declined"),
    ("Draymond Green", "player_option", "GSW", "declined"),
    ("James Harden", "player_option", "CLE", "declined"),
    ("Al Horford", "player_option", "GSW", "declined"),
    ("Sandro Mamukelashvili", "player_option", "TOR", "declined"),
    ("De'Anthony Melton", "player_option", "GSW", "declined"),
    ("Austin Reaves", "player_option", "LAL", "declined"),
    ("Marcus Smart", "player_option", "LAL", "declined"),
    ("Gary Trent Jr.", "player_option", "MIL", "declined"),
    ("Trae Young", "player_option", "WAS", "declined"),
    ("Dalano Banton", "team_option", "BOS", "exercised"),
    ("Dominick Barlow", "team_option", "PHI", "exercised"),
    ("Jamaree Bouyea", "team_option", "PHX", "exercised"),
    ("Jamal Cain", "team_option", "ORL", "exercised"),
    ("Pat Connaughton", "team_option", "CHA", "exercised"),
    ("JD Davison", "team_option", "HOU", "exercised"),
    ("Luguentz Dort", "team_option", "OKC", "exercised"),
    ("Mouhamadou Gueye", "team_option", "CHI", "exercised"),
    ("Mouhamed Gueye", "team_option", "ATL", "exercised"),
    ("GG Jackson", "team_option", "MEM", "exercised"),
    ("Trayce Jackson-Davis", "team_option", "TOR", "exercised"),
    ("Daniss Jenkins", "team_option", "DET", "exercised"),
    ("Pelle Larsson", "team_option", "MIA", "exercised"),
    ("Brook Lopez", "team_option", "LAC", "exercised"),
    ("Karlo Matković", "team_option", "NOP", "exercised"),
    ("Leonard Miller", "team_option", "CHI", "exercised"),
    ("Ryan Nembhard", "team_option", "DAL", "exercised"),
    ("Craig Porter Jr.", "team_option", "CLE", "exercised"),
    ("Micah Potter", "team_option", "IND", "exercised"),
    ("Olivier-Maxence Prosper", "team_option", "MEM", "exercised"),
    ("Neemias Queta", "team_option", "BOS", "exercised"),
    ("Jamal Shead", "team_option", "TOR", "exercised"),
    ("Malachi Smith", "team_option", "BKN", "exercised"),
    ("Tolu Smith", "team_option", "DET", "exercised"),
    ("Dalen Terry", "team_option", "PHI", "exercised"),
    ("Jordan Walsh", "team_option", "BOS", "exercised"),
    ("Nicolas Batum", "team_option", "LAC", "declined"),
    ("Bogdan Bogdanović", "team_option", "LAC", "declined"),
    ("Julian Champagnie", "team_option", "SAS", "declined"),
    ("Hayden Gray", "team_option", "UTA", "declined"),
    ("Ron Harper Jr.", "team_option", "BOS", "declined"),
    ("Isaiah Hartenstein", "team_option", "OKC", "declined"),
    ("Killian Hayes", "team_option", "SAC", "declined"),
    ("Andre Jackson Jr.", "team_option", "MIL", "declined"),
    ("Jonathan Kuminga", "team_option", "ATL", "declined"),
    ("Kevon Looney", "team_option", "NOP", "declined"),
    ("Bez Mbeng", "team_option", "UTA", "declined"),
    ("Jordan Miller", "team_option", "LAC", "declined"),
    ("Josh Minott", "team_option", "BKN", "declined"),
    ("Jonathan Mogbo", "team_option", "TOR", "declined"),
    ("Julian Phillips", "team_option", "MIN", "declined"),
    ("Jalen Pickett", "team_option", "DEN", "declined"),
    ("Kobe Sanders", "team_option", "LAC", "declined"),
    ("Day'Ron Sharpe", "team_option", "BKN", "declined"),
    ("Max Shulga", "team_option", "BOS", "declined"),
    ("Nick Smith Jr.", "team_option", "LAL", "declined"),
    ("Trendon Watford", "team_option", "PHI", "declined"),
    ("Jamir Watkins", "team_option", "WAS", "declined"),
    ("Amari Williams", "team_option", "BOS", "declined"),
    ("Kenrich Williams", "team_option", "OKC", "declined"),
    ("Ziaire Williams", "team_option", "BKN", "declined"),
    ("Jahmir Young", "team_option", "MIA", "declined"),
]

# These five were found by comparing the saved official NBA movement history
# from the 2025 offseason through Apr. 12 against the 582-player checkpoint.
ZERO_GAME_SUPPLEMENT = {
    "202681": {
        "player_name": "Kyrie Irving",
        "branch_team": "DAL",
        "latest_pre_split_event_date": "2025-07-06",
        "latest_pre_split_event": "Dallas Mavericks re-signed guard Kyrie Irving to a Contract.",
        "lifecycle_category": "guaranteed_under_contract",
        "contract_structure_reason": (
            "Three-year Dallas contract signed in 2025. The final season is the "
            "later player-option year, so 2026-27 is an attached guaranteed season."
        ),
        "primary_source_url": (
            "https://www.nba.com/news/kyrie-irving-to-sign-extension-with-dallas-mavericks"
        ),
    },
    "203081": {
        "player_name": "Damian Lillard",
        "branch_team": "POR",
        "latest_pre_split_event_date": "2025-07-19",
        "latest_pre_split_event": "Portland Trail Blazers signed guard Damian Lillard to a Contract.",
        "lifecycle_category": "guaranteed_under_contract",
        "contract_structure_reason": (
            "Three-year Portland contract signed in 2025 with an opt-out only "
            "after two seasons, making 2026-27 an attached guaranteed season."
        ),
        "primary_source_url": (
            "https://www.nba.com/news/damian-lillard-to-return-to-trail-blazers"
        ),
    },
    "1627832": {
        "player_name": "Fred VanVleet",
        "branch_team": "HOU",
        "latest_pre_split_event_date": "2025-07-06",
        "latest_pre_split_event": "Houston Rockets re-signed guard Fred VanVleet to a Contract.",
        "lifecycle_category": "player_option_decision",
        "contract_structure_reason": (
            "Houston contract contains a 2026-27 Player Option. The later exercise "
            "is audit-only."
        ),
        "primary_source_url": (
            "https://www.nba.com/news/2026-free-agency-options-and-qualifying-offers"
        ),
    },
    "1642440": {
        "player_name": "Gabe McGlothan",
        "branch_team": "",
        "latest_pre_split_event_date": "2025-12-16",
        "latest_pre_split_event": "Indiana Pacers signed forward Gabe McGlothan to a 10-Day Contract.",
        "lifecycle_category": "immediate_market",
        "contract_structure_reason": (
            "A December 2025 10-Day contract cannot remain attached through the "
            "Apr. 12 branch date without a later contract event. No later movement "
            "event exists in the saved official feed."
        ),
        "primary_source_url": (
            "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
        ),
    },
    "1642850": {
        "player_name": "Thomas Sorber",
        "branch_team": "OKC",
        "latest_pre_split_event_date": "2025-07-03",
        "latest_pre_split_event": "Oklahoma City Thunder re-signed center Thomas Sorber to a Rookie Scale Contract.",
        "lifecycle_category": "guaranteed_under_contract",
        "contract_structure_reason": (
            "2025 first-round rookie-scale contract. The first two rookie-scale "
            "seasons are guaranteed; team options begin before seasons three and four."
        ),
        "primary_source_url": "https://www.nba.com/thunder/news/thomas-sorber-250703",
    },
}

EXPECTED_FINAL_COUNTS = {
    "immediate_market": 191,
    "team_option_decision": 52,
    "player_option_decision": 21,
    "non_guaranteed_or_partial_decision": 37,
    "guaranteed_under_contract": 6,
    "manual_contract_source_review": 4,
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def boolish(value: Any) -> bool:
    """Normalize booleans serialized through CSV/JSON/text."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False

    text = str(value).strip().lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True

    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = []
    seen = set()
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

    v3_zip = find_latest(
        root,
        "fa_unified_offseason_lifecycle_universe_v3_preview_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    provenance_zip = find_latest(
        root,
        "fa_post_split_roster_provenance_audit_v1_0_2_2026-27_*.zip",
    )

    with zipfile.ZipFile(v3_zip) as archive:
        v3_summary = read_json_member(archive, "unified_lifecycle_summary.json")
        v3_rows = read_csv_member(archive, "unified_lifecycle_271.csv")

    with zipfile.ZipFile(branch_zip) as archive:
        branch_summary = read_json_member(
            archive,
            "branch_reconstruction_summary.json",
        )
        branch_rows = read_csv_member(
            archive,
            "branch_reconstruction_all_players.csv",
        )

    with zipfile.ZipFile(provenance_zip) as archive:
        movement_rows = read_csv_member(
            archive,
            "player_movement_rows_canonical.csv",
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()

    if checkpoint_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before V4.1 preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash}"
        )

    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)
    players = getattr(state, "players", {}) or {}
    base_ids = {pid(raw_id) for raw_id in players}

    if len(base_ids) != EXPECTED_BASE_PLAYERS:
        raise RuntimeError(
            f"Expected {EXPECTED_BASE_PLAYERS} checkpoint players, got {len(base_ids)}."
        )

    branch_by_name = {
        normalize_name(row.get("player_name")): row
        for row in branch_rows
        if clean(row.get("player_name"))
    }
    branch_by_id = {
        pid(row.get("player_id")): row
        for row in branch_rows
    }

    # Dynamically reproduce the zero-game population finding from saved NBA history.
    movement_window = []
    for row in movement_rows:
        player_id = pid(row.get("player_id"))
        if not player_id or not player_id.isdigit():
            continue
        try:
            tx_date = date.fromisoformat(clean(row.get("transaction_date"))[:10])
        except ValueError:
            continue
        if MOVEMENT_START <= tx_date <= SPLIT_DATE:
            movement_window.append({
                **row,
                "_pid": player_id,
                "_date": tx_date,
            })

    latest_by_id = {}
    for row in sorted(
        movement_window,
        key=lambda item: (
            item["_pid"],
            item["_date"],
        ),
    ):
        latest_by_id[row["_pid"]] = row

    missing_latest_signings = []
    for player_id, row in sorted(latest_by_id.items()):
        if player_id in base_ids:
            continue
        if clean(row.get("transaction_type")) != "Signing":
            continue
        missing_latest_signings.append(row)

    missing_signing_ids = {row["_pid"] for row in missing_latest_signings}
    expected_supplement_ids = set(ZERO_GAME_SUPPLEMENT)

    # Build extended population registry, not PlayerState objects.
    supplement_rows = []
    for player_id, evidence in ZERO_GAME_SUPPLEMENT.items():
        movement = next(
            (
                row
                for row in missing_latest_signings
                if row["_pid"] == player_id
            ),
            None,
        )
        supplement_rows.append({
            "player_id": player_id,
            "player_name": evidence["player_name"],
            "reconstructed_branch_owner": evidence["branch_team"],
            "lifecycle_category": evidence["lifecycle_category"],
            "latest_pre_split_event_date": evidence[
                "latest_pre_split_event_date"
            ],
            "latest_pre_split_event": evidence["latest_pre_split_event"],
            "movement_feed_event_verified": bool(movement),
            "contract_structure_reason": evidence["contract_structure_reason"],
            "primary_source_url": evidence["primary_source_url"],
            "population_supplement_required": True,
            "future_real_world_outcome_used": False,
        })

    # Start with V3 lifecycle rows and correct/add option structure.
    final_by_name = {
        normalize_name(row.get("player_name")): dict(row)
        for row in v3_rows
    }

    option_registry_rows = []
    corrections = []

    for player_name, option_type, official_team, actual_outcome in OFFICIAL_OPTIONS:
        key = normalize_name(player_name)
        expected_category = (
            "player_option_decision"
            if option_type == "player_option"
            else "team_option_decision"
        )

        existing = final_by_name.get(key)
        branch = branch_by_name.get(key, {})

        supplement = next(
            (
                row for row in supplement_rows
                if normalize_name(row["player_name"]) == key
            ),
            None,
        )

        if existing:
            player_id = pid(existing.get("player_id"))
            branch_owner = clean(existing.get("reconstructed_branch_owner"))
            if branch_owner not in TEAM_CODES:
                branch_owner = clean(branch.get("reconstructed_branch_owner"))
        elif supplement:
            player_id = supplement["player_id"]
            branch_owner = supplement["reconstructed_branch_owner"]
        else:
            player_id = pid(branch.get("player_id"))
            branch_owner = clean(branch.get("reconstructed_branch_owner"))

        current_category = (
            clean(existing.get("unified_lifecycle_category"))
            if existing else ""
        )

        option_registry_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "official_option_type": option_type,
            "expected_category": expected_category,
            "official_team_audit_only": official_team,
            "real_world_outcome_audit_only": actual_outcome,
            "v3_present": bool(existing),
            "v3_category": current_category,
            "reconstructed_branch_owner": branch_owner,
            "population_supplement_required": bool(supplement),
            "official_source_url": OFFICIAL_OPTION_SOURCE,
            "option_existence_used": True,
            "real_world_outcome_used": False,
        })

        if existing:
            if current_category != expected_category:
                existing["unified_lifecycle_category"] = expected_category
                existing["official_option_structure_override"] = True
                existing["option_structure_source"] = OFFICIAL_OPTION_SOURCE
                existing["future_real_world_outcome_used"] = False
                corrections.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "correction_type": "reclassify_existing_v3_row",
                    "prior_category": current_category,
                    "corrected_category": expected_category,
                    "branch_owner": branch_owner,
                })
        else:
            if not player_id:
                raise RuntimeError(
                    f"Could not resolve player ID for official option: {player_name}"
                )
            if branch_owner not in TEAM_CODES:
                raise RuntimeError(
                    f"Could not resolve branch owner for official option: "
                    f"{player_name} owner={branch_owner!r}"
                )

            new_row = {
                "player_id": player_id,
                "player_name": player_name,
                "source_universe": (
                    "zero_game_population_supplement"
                    if supplement
                    else "official_nba_option_registry_supplement"
                ),
                "unified_lifecycle_category": expected_category,
                "source_lifecycle_state": "",
                "source_contract_classification": option_type,
                "prior_team": branch_owner,
                "reconstructed_branch_owner": branch_owner,
                "current_checkpoint_owner": clean(
                    branch.get("current_checkpoint_owner")
                ),
                "future_real_world_outcome_used": False,
                "official_option_structure_override": True,
                "option_structure_source": OFFICIAL_OPTION_SOURCE,
                "population_supplement_required": bool(supplement),
            }
            final_by_name[key] = new_row
            corrections.append({
                "player_id": player_id,
                "player_name": player_name,
                "correction_type": (
                    "add_missing_option_and_population_player"
                    if supplement
                    else "add_missing_option_decision"
                ),
                "prior_category": "",
                "corrected_category": expected_category,
                "branch_owner": branch_owner,
            })

    # Add non-option zero-game supplement rows.
    for supplement in supplement_rows:
        key = normalize_name(supplement["player_name"])
        if key in final_by_name:
            continue

        category = supplement["lifecycle_category"]
        final_by_name[key] = {
            "player_id": supplement["player_id"],
            "player_name": supplement["player_name"],
            "source_universe": "zero_game_population_supplement",
            "unified_lifecycle_category": category,
            "source_lifecycle_state": "",
            "source_contract_classification": (
                "expired_10_day"
                if category == "immediate_market"
                else "contract_attached_zero_game"
            ),
            "prior_team": supplement["reconstructed_branch_owner"],
            "reconstructed_branch_owner": supplement[
                "reconstructed_branch_owner"
            ],
            "current_checkpoint_owner": "",
            "future_real_world_outcome_used": False,
            "population_supplement_required": True,
        }
        corrections.append({
            "player_id": supplement["player_id"],
            "player_name": supplement["player_name"],
            "correction_type": "add_zero_game_population_lifecycle",
            "prior_category": "",
            "corrected_category": category,
            "branch_owner": supplement["reconstructed_branch_owner"],
        })

    final_rows = list(final_by_name.values())
    final_ids = {pid(row.get("player_id")) for row in final_rows}
    category_counts = Counter(
        clean(row.get("unified_lifecycle_category"))
        for row in final_rows
    )

    extended_population_ids = set(base_ids) | set(ZERO_GAME_SUPPLEMENT)

    # Extended ownership preview.
    opening_owner = {
        pid(row.get("player_id")): clean(
            row.get("reconstructed_branch_owner")
        )
        for row in branch_rows
    }

    for supplement in supplement_rows:
        player_id = supplement["player_id"]
        if supplement["lifecycle_category"] == "immediate_market":
            opening_owner[player_id] = "FA"
        else:
            opening_owner[player_id] = supplement["reconstructed_branch_owner"]

    for row in final_rows:
        player_id = pid(row.get("player_id"))
        category = clean(row.get("unified_lifecycle_category"))
        owner = clean(row.get("reconstructed_branch_owner"))

        if category == "immediate_market":
            opening_owner[player_id] = "FA"
        elif category in {
            "team_option_decision",
            "player_option_decision",
            "non_guaranteed_or_partial_decision",
            "guaranteed_under_contract",
        }:
            if owner not in TEAM_CODES:
                raise RuntimeError(
                    f"Attached lifecycle row lacks branch owner: "
                    f"{row.get('player_name')} owner={owner!r}"
                )
            opening_owner[player_id] = owner
        elif category == "manual_contract_source_review":
            opening_owner[player_id] = "QUARANTINE"

    team_counts = Counter(
        owner
        for owner in opening_owner.values()
        if owner in TEAM_CODES
    )
    over_21 = sorted(
        team_code
        for team_code, count in team_counts.items()
        if count > 21
    )

    checks = []

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
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("=" * 128, flush=True)
    print("2026 OFFICIAL OPTION + ZERO-GAME POPULATION V4.1.1 PREVIEW", flush=True)
    print("=" * 128, flush=True)
    print(f"Base checkpoint players:       {len(base_ids)}", flush=True)
    print(f"Population supplement players: {len(supplement_rows)}", flush=True)
    print(f"Extended branch population:    {len(extended_population_ids)}", flush=True)
    print(f"Final lifecycle rows:          {len(final_rows)}", flush=True)
    print("READ-ONLY. NO PLAYERSTATE OR CHECKPOINT WRITE.", flush=True)
    print("", flush=True)
    print("Running strict V4.1 checks...", flush=True)

    check(
        "upstream_v3_passed",
        bool(v3_summary.get("passed")),
        "Unified lifecycle V3 passed.",
    )
    check(
        "upstream_branch_passed",
        bool(branch_summary.get("passed_strict_checks")),
        "Branch reconstruction V1.0.1 passed.",
    )
    check(
        "base_checkpoint_player_count_is_582",
        len(base_ids) == EXPECTED_BASE_PLAYERS,
        f"base={len(base_ids)}",
    )
    check(
        "saved_movement_detects_exact_five_missing_latest_signings",
        missing_signing_ids == expected_supplement_ids,
        (
            f"detected={sorted(missing_signing_ids)}; "
            f"expected={sorted(expected_supplement_ids)}"
        ),
    )
    check(
        "zero_game_supplement_count_is_5",
        len(supplement_rows) == 5,
        f"supplement={len(supplement_rows)}",
    )
    check(
        "zero_game_supplement_exact_ids",
        {row["player_id"] for row in supplement_rows}
        == expected_supplement_ids,
        repr(sorted(expected_supplement_ids)),
    )
    check(
        "fred_vanvleet_is_population_supplement_player_option",
        any(
            row["player_name"] == "Fred VanVleet"
            and row["lifecycle_category"] == "player_option_decision"
            and row["reconstructed_branch_owner"] == "HOU"
            for row in supplement_rows
        ),
        "Fred VanVleet -> HOU Player Option.",
    )
    check(
        "kyrie_dame_sorber_are_guaranteed_supplements",
        {
            row["player_name"]
            for row in supplement_rows
            if row["lifecycle_category"] == "guaranteed_under_contract"
        }
        == {"Kyrie Irving", "Damian Lillard", "Thomas Sorber"},
        "Expected three guaranteed zero-game contract players.",
    )
    check(
        "gabe_mcglothan_is_expired_10_day_market",
        any(
            row["player_name"] == "Gabe McGlothan"
            and row["lifecycle_category"] == "immediate_market"
            for row in supplement_rows
        ),
        "Expired 10-day -> immediate market.",
    )
    check(
        "extended_branch_population_is_587",
        len(extended_population_ids) == EXPECTED_EXTENDED_PLAYERS,
        f"extended={len(extended_population_ids)}",
    )
    check(
        "official_option_registry_count_is_73",
        len(OFFICIAL_OPTIONS) == 73,
        f"options={len(OFFICIAL_OPTIONS)}",
    )
    check(
        "all_73_option_rows_have_branch_owner",
        all(
            row["reconstructed_branch_owner"] in TEAM_CODES
            for row in option_registry_rows
        ),
        "Every option holder has reconstructed owner evidence.",
    )
    check(
        "all_73_options_have_correct_final_category",
        all(
            clean(
                final_by_name[
                    normalize_name(row["player_name"])
                ].get("unified_lifecycle_category")
            )
            == row["expected_category"]
            for row in option_registry_rows
        ),
        "All official option structures represented.",
    )
    check(
        "final_lifecycle_count_is_311",
        len(final_rows) == 311
        and len(final_ids) == 311,
        f"rows={len(final_rows)} unique_ids={len(final_ids)}",
    )
    check(
        "final_category_counts_exact",
        category_counts == Counter(EXPECTED_FINAL_COUNTS),
        json.dumps(dict(sorted(category_counts.items())), sort_keys=True),
    )
    check(
        "final_immediate_market_is_191",
        category_counts["immediate_market"] == 191,
        f"market={category_counts['immediate_market']}",
    )
    check(
        "final_option_decisions_are_73",
        (
            category_counts["team_option_decision"]
            + category_counts["player_option_decision"]
        ) == 73,
        (
            f"team={category_counts['team_option_decision']} "
            f"player={category_counts['player_option_decision']}"
        ),
    )
    check(
        "no_team_exceeds_offseason_21",
        not over_21,
        "over_21=" + ("|".join(over_21) if over_21 else "<none>"),
    )
    check(
        "future_option_outcomes_not_used",
        all(
            not row["real_world_outcome_used"]
            for row in option_registry_rows
        )
        and all(
            not boolish(row.get("future_real_world_outcome_used"))
            for row in final_rows
        ),
        "Only contract structure is imported; CSV string 'False' is normalized safely.",
    )
    check(
        "serialized_false_boolean_normalizes_to_false",
        boolish("False") is False
        and boolish(False) is False
        and boolish("") is False,
        "CSV/text false values cannot trigger a false-positive future-leakage failure.",
    )

    state_digest_after = object_digest(state)
    checkpoint_after = sha256_file(checkpoint_path)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_before == state_digest_after,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_after
        == checkpoint_hash
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    if failed:
        raise RuntimeError(
            "Official Option + Zero-Game Population V4.1.1 Preview failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_official_option_and_zero_game_population_v4_1_1_preview_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_v41_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "zero_game_population_supplement_5.csv",
            supplement_rows,
        )
        write_csv(
            export / "official_option_registry_73.csv",
            option_registry_rows,
        )
        write_csv(
            export / "v4_1_lifecycle_corrections.csv",
            corrections,
        )
        write_csv(
            export / "unified_lifecycle_v4_1_311.csv",
            final_rows,
        )
        write_csv(
            export / "v4_1_checks.csv",
            checks,
        )

        team_rows = [
            {
                "team_abbreviation": team_code,
                "v4_1_opening_roster_count": team_counts.get(team_code, 0),
                "exceeds_offseason_21": team_counts.get(team_code, 0) > 21,
            }
            for team_code in sorted(TEAM_CODES)
        ]
        write_csv(
            export / "v4_1_opening_team_counts.csv",
            team_rows,
        )

        summary = {
            "version": VERSION,
            "base_checkpoint_player_count": len(base_ids),
            "population_supplement_count": len(supplement_rows),
            "extended_branch_population_count": len(extended_population_ids),
            "official_option_structure_count": len(OFFICIAL_OPTIONS),
            "final_lifecycle_count": len(final_rows),
            "final_category_counts": dict(sorted(category_counts.items())),
            "teams_over_offseason_21": over_21,
            "future_real_world_outcomes_used": False,
            "playerstate_objects_created": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Treat V3 and failed V4 as superseded. Resolve the four original "
                "manual contract-source rows. Then build CPU/user decision previews "
                "for 52 Team Options, 21 Player Options, and 37 non-guaranteed/"
                "partial contracts. Only after option decisions should RFA/QO be "
                "rebuilt on the resulting simulated market. Separately design the "
                "five-player PlayerState population supplement before checkpoint hydration."
            ),
        }
        (
            export / "v4_1_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 OFFICIAL OPTION + ZERO-GAME POPULATION V4.1 PREVIEW
============================================================

This preview fixes two completeness problems before RFA/QO:

1. Official 2026-27 option structure
   The NBA identifies 73 Player/Team Option contracts.

2. Zero-game contracted player population
   The 582-player checkpoint was participation-derived and omitted five players
   with official 2025-26 contract events but no checkpoint player row:
   - Kyrie Irving
   - Damian Lillard
   - Fred VanVleet
   - Gabe McGlothan
   - Thomas Sorber

Lifecycle treatment:
- Kyrie Irving -> guaranteed under contract
- Damian Lillard -> guaranteed under contract
- Fred VanVleet -> Player Option
- Gabe McGlothan -> immediate market after expired 10-day
- Thomas Sorber -> guaranteed under contract

Expected V4.1:
587 extended branch-population players
311 lifecycle rows
191 immediate market
52 Team Options
21 Player Options
37 non-guaranteed/partial
6 guaranteed
4 manual contract-source rows

No PlayerState objects are created.
No checkpoint/state mutation.
No real-world option exercise/decline outcome is used.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            audit_zip,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for item in sorted(export.iterdir()):
                archive.write(
                    item,
                    arcname=f"{export_id}/{item.name}",
                )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 OFFICIAL OPTION + ZERO-GAME POPULATION V4.1 PREVIEW PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Base checkpoint players:          582", flush=True)
    print("Population supplement:              5", flush=True)
    print("Extended branch population:       587", flush=True)
    print("Official option structures:        73", flush=True)
    print("Final lifecycle rows:             311", flush=True)
    print("Immediate market:                 191", flush=True)
    print("Team Options:                      52", flush=True)
    print("Player Options:                    21", flush=True)
    print("Non-guaranteed/partial:            37", flush=True)
    print("Guaranteed under contract:          6", flush=True)
    print("Manual contract-source:             4", flush=True)
    print("Teams over offseason 21:            NONE", flush=True)
    print("Future option outcomes used:        NO", flush=True)
    print("PlayerState creation:               NOT PERFORMED", flush=True)
    print("Checkpoint write:                   NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
