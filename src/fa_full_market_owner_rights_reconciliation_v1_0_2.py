from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import zipfile
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-full-market-owner-rights-reconciliation-v1.0.2-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_MARKET = 226
EXPECTED_RFA = 64
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
TEAM_CODES = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
    "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
}
AUTHORITATIVE_OWNER_FIELDS = (
    "reconstructed_branch_owner",
    "lifecycle_prior_team",
    "prior_team",
    "prior_team_abbreviation",
)
NON_AUTHORITATIVE_TEAM_FIELDS = (
    "team_abbreviation",
    "team",
    "current_team",
    "option_team",
    "roster_team",
)
RIGHTS_FIELDS = (
    "rights_classification",
    "rights_status",
    "final_rights",
    "free_agent_rights",
    "rights_type",
    "rights",
)
RIGHTS_NORMALIZE = {
    "bird": "bird",
    "qvfa": "bird",
    "qualifying veteran free agent": "bird",
    "early bird": "early_bird",
    "early_bird": "early_bird",
    "eqvfa": "early_bird",
    "early qualifying veteran free agent": "early_bird",
    "non-bird": "non_bird",
    "non bird": "non_bird",
    "non_bird": "non_bird",
    "nqvfa": "non_bird",
    "non-qualifying veteran free agent": "non_bird",
    "two-way special": "two_way_special",
    "two_way_special": "two_way_special",
    "not applicable": "not_applicable",
    "n/a": "not_applicable",
}
PRIOR_SALARY_RE = re.compile(
    r"(prior.*salary|2025.?26.*salary|salary.*2025.?26|prior_regular_salary)",
    re.I,
)


GABE_MCGLOTHAN_PLAYER_ID = "1642440"
GABE_MCGLOTHAN_PRIOR_TEAM = "IND"
GABE_MCGLOTHAN_OWNER_SOURCE = (
    "official_nba_gleague_2025-12-16_indiana_10_day"
)
GABE_MCGLOTHAN_OWNER_URL = (
    "https://gleague.nba.com/news/"
    "gabe-mcglothan-earns-nba-call-up-with-indiana-pacers"
)

PRIOR_SALARY_FIELD_EXCLUDE_TOKENS = (
    "count",
    "evidence",
    "source",
    "status",
    "ready",
    "resolved",
    "resolution",
    "confidence",
    "manual",
    "flag",
    "method",
    "percent",
    "pct",
    "multiplier",
    "years_of_service",
    "yos",
)

def is_prior_salary_field(key: Any) -> bool:
    lower = clean(key).lower()
    if not PRIOR_SALARY_RE.search(lower):
        return False
    if any(token in lower for token in PRIOR_SALARY_FIELD_EXCLUDE_TOKENS):
        return False
    return True


def rights_source_priority(source: str) -> int:
    lower = clean(source).lower()

    # Later corrected/final evidence beats early population scaffolding.
    if "fa_rights_registry_v2_preview" in lower:
        return 100
    if "fa_contract_option_lifecycle_readiness_v1_0_1" in lower:
        return 98
    if "fa_corrected_rfa_qo_universe_v2_preview" in lower:
        return 96
    if "fa_final_market_rfa_qo_eligibility_readiness_v1" in lower:
        return 94
    if "fa_rfa_qo_eligibility_preview_v1_0_2" in lower:
        return 90
    if "fa_rights_continuity_v2_preview" in lower:
        return 88
    if "franchise_free_agency_rights_external_evidence_v1_0_1" in lower:
        return 70
    if "franchise_free_agency_rights_external_evidence_" in lower:
        return 65
    if "franchise_free_agency_rights_population" in lower:
        return 40
    return 50


def salary_source_priority(source: str) -> int:
    lower = clean(source).lower()

    # Never let prior reconciliation outputs recursively become evidence.
    if "owner_rights_reconciliation" in lower:
        return -100

    # Final salary resolution/continuity layers are strongest.
    if (
        "fa_rights_registry_v2_preview" in lower
        and "final_rights_salary_resolution.csv" in lower
    ):
        return 110
    if "fa_rights_registry_v2_preview" in lower:
        return 105
    if "fa_rights_continuity_v2_preview" in lower:
        return 100
    if "fa_additional_lifecycle_targeted_resolution_and_final84_v1" in lower:
        return 96
    if "fa_contract_option_lifecycle_readiness_v1_0_1" in lower:
        return 92
    if "fa_corrected_rfa_qo_universe_v2_preview" in lower:
        return 88

    # Historical span harvests may contain several contracts for one player.
    if "fa_additional_lifecycle_contract_evidence_harvest" in lower:
        return 45

    # External evidence summaries frequently contain metadata/count columns;
    # keep them below resolved financial evidence.
    if "franchise_free_agency_rights_external_evidence" in lower:
        return 35

    return 55


def prioritized_choice(
    candidates: list[dict[str, Any]],
    key: str,
    priority_fn,
) -> tuple[Any, str, str, str]:
    usable = [
        row for row in candidates
        if priority_fn(row["source"]) >= 0
    ]
    if not usable:
        return "", "", "", ""

    top_priority = max(priority_fn(row["source"]) for row in usable)
    top = [
        row for row in usable
        if priority_fn(row["source"]) == top_priority
    ]

    values = []
    for row in top:
        value = row[key]
        if value not in values:
            values.append(value)

    lower_disagreements = []
    if len(values) == 1:
        chosen = values[0]
        sources = sorted(
            {
                row["source"]
                for row in top
                if row[key] == chosen
            }
        )
        for row in usable:
            if priority_fn(row["source"]) < top_priority and row[key] != chosen:
                lower_disagreements.append(
                    f"{row['source']}={row[key]}"
                )
        return (
            chosen,
            "|".join(sources),
            "",
            "|".join(lower_disagreements),
        )

    detail = "|".join(
        f"{row['source']}={row[key]}"
        for row in top
    )
    return "", "", detail, ""


def clean(v: Any) -> str:
    return str(v or "").strip()


def pid(v: Any) -> str:
    text = clean(v)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def fnum(v: Any) -> float | None:
    text = clean(v).replace("$", "").replace(",", "")
    try:
        return float(text)
    except Exception:
        return None


def normalize_rights(v: Any) -> str:
    text = clean(v).lower().replace("_", " ")
    text = " ".join(text.split())
    return RIGHTS_NORMALIZE.get(text, "")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def find_latest(root: Path, pattern: str) -> Path | None:
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def read_csv_suffix(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    text = z.read(name).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_suffix(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return {}
    return json.loads(z.read(name).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields, seen = [], set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def authoritative_owner_from_row(
    row: dict[str, Any],
) -> tuple[str, str]:
    lowered = {clean(k).lower(): k for k in row}
    for preferred in AUTHORITATIVE_OWNER_FIELDS:
        key = lowered.get(preferred)
        if not key:
            continue
        value = clean(row.get(key)).upper()
        if value in TEAM_CODES:
            return value, key
    return "", ""


def non_authoritative_team_observations(
    row: dict[str, Any],
) -> list[tuple[str, str]]:
    lowered = {clean(k).lower(): k for k in row}
    observations: list[tuple[str, str]] = []
    for preferred in NON_AUTHORITATIVE_TEAM_FIELDS:
        key = lowered.get(preferred)
        if not key:
            continue
        value = clean(row.get(key)).upper()
        if value in TEAM_CODES:
            observations.append((value, key))
    return observations


def rights_and_salary_from_row(row: dict[str, Any]) -> tuple[str, float | None, list[str]]:
    lowered = {clean(k).lower(): k for k in row}
    rights = ""
    prior_salary = None
    evidence = []

    for preferred in RIGHTS_FIELDS:
        key = lowered.get(preferred)
        if key:
            normalized = normalize_rights(row.get(key))
            if normalized:
                rights = normalized
                evidence.append(f"{key}={clean(row.get(key))}")
                break

    for key, value in row.items():
        if is_prior_salary_field(key):
            amount = fnum(value)
            if amount is not None and amount > 0:
                prior_salary = amount
                evidence.append(f"{key}={clean(value)}")
                break

    return rights, prior_salary, evidence


def collect_source_rows(
    source_name: str,
    rows: list[dict[str, Any]],
    market_ids: set[str],
    owner_candidates: dict[str, list[dict[str, Any]]],
    rights_candidates: dict[str, list[dict[str, Any]]],
    salary_candidates: dict[str, list[dict[str, Any]]],
    team_observations: dict[str, list[dict[str, Any]]],
) -> None:
    for row in rows:
        player_id = pid(row.get("player_id"))
        if not player_id or player_id not in market_ids:
            continue

        owner, owner_field = authoritative_owner_from_row(row)
        if owner:
            owner_candidates[player_id].append({
                "source": source_name,
                "owner": owner,
                "field": owner_field,
                "authority": "explicit_prior_team_field",
            })

        for observed_team, observed_field in non_authoritative_team_observations(row):
            team_observations[player_id].append({
                "source": source_name,
                "observed_team": observed_team,
                "field": observed_field,
                "authority": "non_authoritative_team_observation",
            })

        rights, prior_salary, evidence = rights_and_salary_from_row(row)
        if rights:
            rights_candidates[player_id].append({
                "source": source_name,
                "rights": rights,
                "evidence": " | ".join(evidence),
            })
        if prior_salary is not None:
            salary_candidates[player_id].append({
                "source": source_name,
                "prior_salary": prior_salary,
                "evidence": " | ".join(evidence),
            })


def scan_relevant_audit_csvs(
    root: Path,
    market_ids: set[str],
    owner_candidates,
    rights_candidates,
    salary_candidates,
    team_observations,
) -> list[dict[str, Any]]:
    scan_log = []
    audit_dir = root / "outputs" / "audits"
    if not audit_dir.exists():
        return scan_log

    allowed_name_tokens = (
        "rights",
        "lifecycle",
        "branch_reconstruction",
        "qo_amount",
        "rfa_qo",
        "free_agency",
        "contract_option",
    )

    for zip_path in sorted(audit_dir.glob("*.zip")):
        lower_name = zip_path.name.lower()
        if "owner_rights_reconciliation" in lower_name:
            continue
        if not any(token in lower_name for token in allowed_name_tokens):
            continue
        try:
            with zipfile.ZipFile(zip_path) as z:
                for member in z.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    try:
                        raw = z.read(member)
                        if not raw.strip():
                            continue
                        rows = list(
                            csv.DictReader(
                                io.StringIO(raw.decode("utf-8-sig", errors="replace"))
                            )
                        )
                    except Exception:
                        continue
                    if not rows or "player_id" not in rows[0]:
                        continue

                    fields = {clean(k).lower() for k in rows[0]}
                    useful = (
                        any(f in fields for f in AUTHORITATIVE_OWNER_FIELDS)
                        or any(f in fields for f in NON_AUTHORITATIVE_TEAM_FIELDS)
                        or any(f in fields for f in RIGHTS_FIELDS)
                        or any(is_prior_salary_field(f) for f in fields)
                    )
                    if not useful:
                        continue

                    source = f"{zip_path.name}::{member}"
                    collect_source_rows(
                        source,
                        rows,
                        market_ids,
                        owner_candidates,
                        rights_candidates,
                        salary_candidates,
                        team_observations,
                    )
                    scan_log.append({
                        "source_zip": zip_path.name,
                        "member": member,
                        "row_count": len(rows),
                        "fields": "|".join(sorted(fields)),
                    })
        except Exception:
            continue

    return scan_log


def unique_choice(candidates: list[dict[str, Any]], key: str) -> tuple[Any, str, str]:
    values = []
    for row in candidates:
        value = row[key]
        if value not in values:
            values.append(value)

    if len(values) == 1:
        sources = sorted({row["source"] for row in candidates if row[key] == values[0]})
        return values[0], "|".join(sources), ""
    if len(values) > 1:
        detail = "|".join(
            f"{row['source']}={row[key]}"
            for row in candidates
        )
        return "", "", detail
    return "", "", ""


def main() -> int:
    root = Path.cwd().resolve()

    readiness_zip = find_latest(
        root,
        "fa_full_market_team_salary_charge_readiness_v1_2026-27_*.zip",
    )
    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )
    qo_zip = find_latest(
        root,
        "fa_qo_issuance_decision_preview_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )

    if not all([readiness_zip, scenario_zip, qo_zip]):
        raise RuntimeError(
            "Missing full-market readiness, recommended market, or QO preview audit."
        )

    with zipfile.ZipFile(readiness_zip) as z:
        readiness_summary = read_json_suffix(
            z, "full_market_charge_readiness_summary.json"
        )
        readiness_rows = read_csv_suffix(
            z, "full_market_team_salary_charge_readiness_226.csv"
        )

    with zipfile.ZipFile(scenario_zip) as z:
        market_rows = read_csv_suffix(z, "recommended_final_market_226.csv")

    with zipfile.ZipFile(qo_zip) as z:
        qo_rows = read_csv_suffix(z, "qo_issuance_decision_board_64.csv")

    if len(market_rows) != EXPECTED_MARKET or len(readiness_rows) != EXPECTED_MARKET:
        raise RuntimeError("Expected exact 226-player market/readiness universe.")
    if len(qo_rows) != EXPECTED_RFA:
        raise RuntimeError("Expected exact 64-player QO universe.")

    market_ids = {pid(r.get("player_id")) for r in market_rows}
    readiness_by_id = {pid(r.get("player_id")): r for r in readiness_rows}

    owner_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rights_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    salary_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    team_observations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # QO owner evidence is already proven for 64 RFA candidates.
    collect_source_rows(
        "qo_issuance_preview",
        qo_rows,
        market_ids,
        owner_candidates,
        rights_candidates,
        salary_candidates,
        team_observations,
    )

    # High-value deterministic branch/lifecycle sources.
    if branch_zip:
        with zipfile.ZipFile(branch_zip) as z:
            rows = read_csv_suffix(z, "branch_reconstruction_all_players.csv", required=False)
            collect_source_rows(
                "opening_branch_reconstruction",
                rows,
                market_ids,
                owner_candidates,
                rights_candidates,
                salary_candidates,
                team_observations,
            )

    if lifecycle_zip:
        with zipfile.ZipFile(lifecycle_zip) as z:
            rows = read_csv_suffix(z, "contract_option_lifecycle_all.csv", required=False)
            collect_source_rows(
                "contract_option_lifecycle",
                rows,
                market_ids,
                owner_candidates,
                rights_candidates,
                salary_candidates,
                team_observations,
            )

    scan_log = scan_relevant_audit_csvs(
        root,
        market_ids,
        owner_candidates,
        rights_candidates,
        salary_candidates,
        team_observations,
    )

    # The zero-game supplement is absent from participation-derived branch
    # tables. Official NBA G League evidence proves his last pre-split NBA
    # contract was a 10-day with Indiana on Dec. 16, 2025.
    if GABE_MCGLOTHAN_PLAYER_ID in market_ids:
        owner_candidates[GABE_MCGLOTHAN_PLAYER_ID].append({
            "source": GABE_MCGLOTHAN_OWNER_SOURCE,
            "owner": GABE_MCGLOTHAN_PRIOR_TEAM,
            "field": "official_pre_split_10_day_team",
            "authority": "official_transaction_bridge",
            "source_url": GABE_MCGLOTHAN_OWNER_URL,
        })

    reconciliation_rows = []
    owner_conflicts = []
    owner_unresolved = []
    rights_conflicts = []
    prior_salary_conflicts = []
    lower_priority_rights_disagreements = []
    lower_priority_prior_salary_disagreements = []
    non_authoritative_team_disagreements = []

    for market in market_rows:
        player_id = pid(market.get("player_id"))
        player_name = clean(market.get("player_name"))
        upstream = readiness_by_id[player_id]

        owner, owner_sources, owner_conflict = unique_choice(
            owner_candidates[player_id], "owner"
        )
        (
            rights,
            rights_sources,
            rights_conflict,
            rights_lower_disagreement,
        ) = prioritized_choice(
            rights_candidates[player_id],
            "rights",
            rights_source_priority,
        )
        (
            prior_salary,
            salary_sources,
            salary_conflict,
            salary_lower_disagreement,
        ) = prioritized_choice(
            salary_candidates[player_id],
            "prior_salary",
            salary_source_priority,
        )

        if owner_conflict:
            owner_conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_detail": owner_conflict,
            })

        if owner:
            disagreeing_observations = [
                obs
                for obs in team_observations[player_id]
                if obs["observed_team"] != owner
            ]
            if disagreeing_observations:
                non_authoritative_team_disagreements.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "authoritative_prior_team": owner,
                    "authoritative_sources": owner_sources,
                    "non_authoritative_observations": "|".join(
                        f"{obs['source']}::{obs['field']}={obs['observed_team']}"
                        for obs in disagreeing_observations
                    ),
                })
        if not owner:
            owner_unresolved.append({
                "player_id": player_id,
                "player_name": player_name,
                "owner_candidate_count": len(owner_candidates[player_id]),
            })
        if rights_conflict:
            rights_conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_detail": rights_conflict,
            })
        if rights_lower_disagreement:
            lower_priority_rights_disagreements.append({
                "player_id": player_id,
                "player_name": player_name,
                "selected_rights": rights,
                "selected_sources": rights_sources,
                "lower_priority_disagreements": rights_lower_disagreement,
            })

        if salary_conflict:
            prior_salary_conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_detail": salary_conflict,
            })
        if salary_lower_disagreement:
            lower_priority_prior_salary_disagreements.append({
                "player_id": player_id,
                "player_name": player_name,
                "selected_prior_salary": prior_salary,
                "selected_sources": salary_sources,
                "lower_priority_disagreements": salary_lower_disagreement,
            })

        existing_rights = clean(upstream.get("rights_classification"))
        existing_prior_salary = fnum(upstream.get("prior_salary_evidence"))

        reconciliation_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "resolved_prior_team": owner,
            "owner_sources": owner_sources,
            "owner_candidate_count": len(owner_candidates[player_id]),
            "owner_conflict": bool(owner_conflict),
            "non_authoritative_team_observation_count": len(
                team_observations[player_id]
            ),
            "non_authoritative_team_observations": "|".join(
                f"{obs['source']}::{obs['field']}={obs['observed_team']}"
                for obs in team_observations[player_id]
            ),
            "upstream_rights_classification": existing_rights,
            "reconciled_rights_classification": rights,
            "rights_sources": rights_sources,
            "rights_candidate_count": len(rights_candidates[player_id]),
            "rights_conflict": bool(rights_conflict),
            "lower_priority_rights_disagreement": bool(
                rights_lower_disagreement
            ),
            "upstream_prior_salary_evidence": (
                existing_prior_salary if existing_prior_salary is not None else ""
            ),
            "reconciled_prior_salary_evidence": prior_salary,
            "prior_salary_sources": salary_sources,
            "prior_salary_candidate_count": len(salary_candidates[player_id]),
            "prior_salary_conflict": bool(salary_conflict),
            "lower_priority_prior_salary_disagreement": bool(
                salary_lower_disagreement
            ),
            "exact_rfa_free_agent_amount_available": clean(
                upstream.get("exact_rfa_free_agent_amount_available")
            ),
            "upstream_formula_family": clean(
                upstream.get("free_agent_amount_formula_family")
            ),
            "upstream_readiness_blockers": clean(
                upstream.get("readiness_blockers")
            ),
        })

    owner_resolved_count = sum(bool(r["resolved_prior_team"]) for r in reconciliation_rows)

    non_rfa_rows = [
        r for r in reconciliation_rows
        if clean(r["exact_rfa_free_agent_amount_available"]).lower()
        not in {"true", "1", "yes"}
    ]
    non_rfa_rights_resolved = sum(
        bool(r["reconciled_rights_classification"])
        for r in non_rfa_rows
    )
    non_rfa_prior_salary_resolved = sum(
        bool(r["reconciled_prior_salary_evidence"])
        for r in non_rfa_rows
    )

    import simulation_franchise_checkpoint_v1 as checkpoint_module
    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before owner/rights reconciliation.")

    checks = []

    def add(cid: str, passed: bool, detail: str, severity: str = "strict"):
        checks.append({
            "check_id": cid,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(f"  {cid}: {'PASS' if passed else 'FAIL'}")

    print("=" * 128)
    print("2026 FULL-MARKET OWNER / RIGHTS RECONCILIATION V1.0.2")
    print("=" * 128)
    print("Running checks...")

    add(
        "upstream_full_market_charge_readiness_passed",
        bool(readiness_summary.get("passed"))
        and int(readiness_summary.get("final_market_count", -1)) == 226,
        "226-player full-market readiness passed.",
    )
    add(
        "exact_226_reconciliation_rows",
        len(reconciliation_rows) == 226
        and len({r["player_id"] for r in reconciliation_rows}) == 226,
        f"rows={len(reconciliation_rows)}",
    )
    add(
        "owner_source_scan_completed",
        len(scan_log) > 0,
        f"scanned_csv_sources={len(scan_log)}",
    )
    add(
        "all_64_rfa_prior_teams_preserved",
        all(
            any(c["source"] == "qo_issuance_preview" for c in owner_candidates[r["player_id"]])
            for r in reconciliation_rows
            if clean(r["exact_rfa_free_agent_amount_available"]).lower()
            in {"true", "1", "yes"}
        ),
        "QO preview provides prior-team evidence for all exact-RFA rows.",
    )
    add(
        "authoritative_owner_conflicts_are_fail_closed",
        len(owner_conflicts) == 0,
        f"authoritative_owner_conflicts={len(owner_conflicts)}",
    )
    add(
        "non_authoritative_team_disagreements_are_diagnostic",
        True,
        (
            f"players_with_disagreeing_generic_team_observations="
            f"{len(non_authoritative_team_disagreements)}"
        ),
        severity="diagnostic",
    )
    add(
        "exact_226_prior_teams_resolved",
        owner_resolved_count == 226 and not owner_unresolved,
        f"owner_resolved={owner_resolved_count}/226; unresolved={len(owner_unresolved)}",
    )
    add(
        "top_priority_rights_conflicts_are_exposed",
        True,
        (
            f"top_priority_rights_conflicts={len(rights_conflicts)}; "
            f"lower_priority_disagreements={len(lower_priority_rights_disagreements)}"
        ),
        severity="diagnostic",
    )
    add(
        "top_priority_prior_salary_conflicts_are_exposed",
        True,
        (
            f"top_priority_prior_salary_conflicts={len(prior_salary_conflicts)}; "
            f"lower_priority_disagreements={len(lower_priority_prior_salary_disagreements)}"
        ),
        severity="diagnostic",
    )
    add(
        "non_rfa_reconciliation_counts_are_diagnostic",
        True,
        (
            f"non_rfa={len(non_rfa_rows)}; "
            f"rights_resolved={non_rfa_rights_resolved}; "
            f"prior_salary_resolved={non_rfa_prior_salary_resolved}"
        ),
        severity="diagnostic",
    )
    add(
        "prior_salary_metadata_fields_are_excluded",
        all(
            all(
                token not in clean(candidate.get("evidence")).lower()
                for token in (
                    "candidate_count=",
                    "evidence_count=",
                    "source_count=",
                    "resolved_count=",
                )
            )
            for candidates in salary_candidates.values()
            for candidate in candidates
        ),
        "Count/metadata fields cannot become prior-salary evidence.",
    )

    after_state = object_digest(checkpoint.simulation_state)
    after_hash = sha256_file(checkpoint_path)

    add("loaded_simulation_state_unchanged", after_state == before_state, after_state)
    add(
        "checkpoint_file_unchanged",
        after_hash == before_hash == EXPECTED_CHECKPOINT_SHA256,
        after_hash,
    )

    failed = [
        row["check_id"] for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_full_market_owner_rights_reconciliation_v1_0_2_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "market_count": 226,
        "owner_resolved_count": owner_resolved_count,
        "owner_unresolved_count": len(owner_unresolved),
        "authoritative_owner_conflict_count": len(owner_conflicts),
        "non_authoritative_team_disagreement_count": len(
            non_authoritative_team_disagreements
        ),
        "non_rfa_count": len(non_rfa_rows),
        "non_rfa_rights_resolved_count": non_rfa_rights_resolved,
        "non_rfa_prior_salary_resolved_count": non_rfa_prior_salary_resolved,
        "top_priority_rights_conflict_count": len(rights_conflicts),
        "lower_priority_rights_disagreement_count": len(
            lower_priority_rights_disagreements
        ),
        "top_priority_prior_salary_conflict_count": len(prior_salary_conflicts),
        "lower_priority_prior_salary_disagreement_count": len(
            lower_priority_prior_salary_disagreements
        ),
        "gabe_mcglothan_prior_team_bridge": {
            "player_id": GABE_MCGLOTHAN_PLAYER_ID,
            "prior_team": GABE_MCGLOTHAN_PRIOR_TEAM,
            "source": GABE_MCGLOTHAN_OWNER_SOURCE,
            "source_url": GABE_MCGLOTHAN_OWNER_URL,
        },
        "scanned_csv_source_count": len(scan_log),
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Use the exact 226/226 owner map as the team-assignment input. "
            "Then resolve only non-RFA rights/prior-salary rows still absent or "
            "conflicted at the highest evidence tier. Lower-priority provisional "
            "disagreements remain audit-only."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_owner_rights_reconcile_") as td:
        export = Path(td) / export_id
        export.mkdir(parents=True)

        write_csv(export / "full_market_owner_rights_reconciliation_226.csv", reconciliation_rows)
        write_csv(export / "prior_team_unresolved.csv", owner_unresolved)
        write_csv(export / "prior_team_conflicts.csv", owner_conflicts)
        write_csv(
            export / "non_authoritative_team_disagreements.csv",
            non_authoritative_team_disagreements,
        )
        write_csv(export / "rights_conflicts.csv", rights_conflicts)
        write_csv(
            export / "lower_priority_rights_disagreements.csv",
            lower_priority_rights_disagreements,
        )
        write_csv(export / "prior_salary_conflicts.csv", prior_salary_conflicts)
        write_csv(
            export / "lower_priority_prior_salary_disagreements.csv",
            lower_priority_prior_salary_disagreements,
        )
        write_csv(export / "relevant_audit_source_scan.csv", scan_log)
        write_csv(export / "owner_rights_reconciliation_checks.csv", checks)

        (export / "owner_rights_reconciliation_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (export / "README.txt").write_text(
            """2026 FULL-MARKET OWNER / RIGHTS RECONCILIATION V1
===================================================

Why this audit exists
---------------------
The 226-player Full-Market Team Salary Charge Readiness audit passed its own
readiness gates, but the final-market CSV did not contain prior-team ownership.
As a result, `prior_team_from_market` was blank on all 226 rows.

This audit repairs the evidence path without mutating anything:
- uses the already-proven QO issuance board for the 64 RFA prior teams
- checks opening-branch reconstruction and lifecycle sources
- scans relevant prior audit CSVs for explicit prior-team, rights, and prior-salary fields
- treats generic `team` / `team_abbreviation` columns only as non-authoritative observations
- chooses an owner only from explicit prior-team/branch-owner fields
- exposes true authoritative conflicts instead of silently prioritizing contradictory data

It also tells us how much of the 162-player non-RFA rights/salary gap is already
recoverable from existing project evidence versus requiring genuinely new
research.

No rights classification is invented.
No cap hold is calculated.
No QO or renouncement is applied.
No checkpoint write occurs.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for item in sorted(export.iterdir()):
                z.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Full-Market Owner / Rights Reconciliation V1.0.2 failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 128)
    print("2026 FULL-MARKET OWNER / RIGHTS RECONCILIATION V1 PASSED")
    print("=" * 128)
    print(f"Prior teams resolved:              {owner_resolved_count}/226")
    print(f"Authoritative prior-team conflicts:{len(owner_conflicts)}")
    print(f"Non-RFA rights resolved:           {non_rfa_rights_resolved}/{len(non_rfa_rows)}")
    print(f"Non-RFA prior salary resolved:     {non_rfa_prior_salary_resolved}/{len(non_rfa_rows)}")
    print(f"Top-priority rights conflicts:     {len(rights_conflicts)}")
    print(f"Top-priority salary conflicts:     {len(prior_salary_conflicts)}")
    print("Checkpoint write:       NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
