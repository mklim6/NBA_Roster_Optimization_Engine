from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


VERSION = "fa-team-base-salary-and-rights-posture-preview-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
SALARY_CAP_2026_27 = 164_961_000
ZERO_YOS_MINIMUM_2026_27 = 1_357_763
CBA_URL = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)

# These three active-contract salaries were the only attached-player gaps left
# after the audited checkpoint, decision, and unique-candidate joins.
TARGETED_ACTIVE_SALARIES = {
    "202681": {
        "player_name": "Kyrie Irving",
        "team": "DAL",
        "base_salary_2026_27": 39_491_282,
        "known_likely_incentive_2026_27": 0,
        "known_cap_hit_2026_27": 39_491_282,
        "evidence_url": "https://www.salaryswish.com/players/kyrie-irving",
        "evidence_note": "2026-27 base salary and cap hit",
    },
    "203081": {
        "player_name": "Damian Lillard",
        "team": "POR",
        "base_salary_2026_27": 13_398_800,
        "known_likely_incentive_2026_27": 0,
        "known_cap_hit_2026_27": 13_398_800,
        "evidence_url": "https://www.salaryswish.com/players/damian-lillard",
        "evidence_note": "2026-27 Portland base salary and cap hit",
    },
    "1642850": {
        "player_name": "Thomas Sorber",
        "team": "OKC",
        "base_salary_2026_27": 4_073_100,
        "known_likely_incentive_2026_27": 814_620,
        "known_cap_hit_2026_27": 4_887_720,
        "evidence_url": "https://www.salaryswish.com/players/thomas-sorber",
        "evidence_note": "2026-27 base salary; known likely incentive is reported separately",
    },
}

EXPECTED_SALARY_SOURCE_COUNTS = Counter(
    {
        "checkpoint_contract_salary": 276,
        "automatic_decision_selected_base_salary": 78,
        "targeted_external_contract_evidence": 3,
        "unique_upstream_salary_candidate": 3,
        "final_market_exclusion_implies_user_option_exercised": 1,
    }
)
EXPECTED_ACTIVE_LISTED_SALARY_TOTAL = 5_092_678_785
EXPECTED_STANDARD_CONTRACT_BASE_TOTAL = 5_072_251_338
EXPECTED_TWO_WAY_COMPENSATION_TOTAL = 20_427_447
EXPECTED_ALL_AMOUNT_TOTAL = 1_231_575_573
EXPECTED_ALL_MODEL_QO_EFFECTIVE_TOTAL = 1_244_533_006
EXPECTED_MODEL_SCENARIO_HOLD_TOTAL = 1_118_248_880
EXPECTED_RELEASE_FLOOR_ROSTER_CHARGE_TOTAL = 58_383_809
EXPECTED_SCENARIO_COMPONENT_TOTALS = {
    "all_rights_preserved_no_qo": 6_303_826_911,
    "all_rights_preserved_model_qo": 6_316_784_344,
    "rfa_model_advisory_non_rfa_preserved": 6_190_500_218,
    "all_hold_release_floor": 5_130_635_147,
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def money(value: Any, *, label: str) -> int:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        raise RuntimeError(f"Missing money value for {label}.")
    number = Decimal(text)
    if number < 0 or number != number.to_integral_value():
        raise RuntimeError(f"Invalid whole-dollar value for {label}: {value!r}")
    return int(number)


def decimal_money(value: Any, *, label: str) -> Decimal:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        raise RuntimeError(f"Missing money value for {label}.")
    number = Decimal(text)
    if number < 0:
        raise RuntimeError(f"Invalid money value for {label}: {value!r}")
    return number


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def latest(root: Path, pattern: str) -> Path:
    paths = [path for path in root.rglob(pattern) if path.is_file()]
    if not paths:
        raise RuntimeError(f"Missing required audit: {pattern}")
    return max(paths, key=lambda path: path.stat().st_mtime)


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


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


def unique_by_id(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        player_id = pid(row.get("player_id"))
        if not player_id:
            raise RuntimeError(f"{label} contains a blank player_id.")
        if player_id in result:
            raise RuntimeError(f"{label} contains duplicate player_id {player_id}.")
        result[player_id] = row
    return result


def main() -> int:
    root = Path.cwd().resolve()
    amount_zip = latest(root, "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip")
    clone_zip = latest(root, "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip")
    salary_probe_zip = latest(root, "fa_team_guaranteed_salary_source_probe_v1_2026-27_*.zip")
    posture_zip = latest(root, "fa_team_financial_posture_readiness_v1_2026-27_*.zip")
    lifecycle_zip = latest(root, "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip")
    rights_zip = latest(root, "fa_rights_retention_renouncement_preview_v1_2026-27_*.zip")
    qo_charge_zip = latest(root, "fa_full_market_team_salary_charge_readiness_v1_2026-27_*.zip")

    with zipfile.ZipFile(amount_zip) as archive:
        amount_summary = json_suffix(archive, "full_market_free_agent_amount_summary.json")
        market_rows = csv_suffix(archive, "full_market_free_agent_amounts_complete_226.csv")
        amount_rows = csv_suffix(archive, "full_market_exact_amounts_ready_170.csv")
    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = json_suffix(archive, "clone_application_summary.json")
        ledger_rows = csv_suffix(archive, "clone_owner_ledger_587.csv")
        automatic_rows = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending_option_rows = csv_suffix(archive, "user_decisions_pending_2.csv")
    with zipfile.ZipFile(salary_probe_zip) as archive:
        salary_probe_summary = json_suffix(archive, "salary_source_probe_summary.json")
        checkpoint_salary_rows = csv_suffix(archive, "checkpoint_salary_numeric_candidates.csv")
    with zipfile.ZipFile(posture_zip) as archive:
        posture_summary = json_suffix(archive, "team_financial_posture_readiness_summary.json")
        unique_candidate_rows = csv_suffix(archive, "unique_player_salary_candidates.csv")
        legacy_roster_rows = csv_suffix(archive, "incomplete_roster_charges_30.csv")
    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = json_suffix(archive, "contract_option_summary.json")
        lifecycle_rows = csv_suffix(archive, "contract_option_lifecycle_all.csv")
    with zipfile.ZipFile(rights_zip) as archive:
        rights_summary = json_suffix(archive, "rights_retention_preview_summary.json")
        rights_rows = csv_suffix(archive, "rights_retention_decision_board_64.csv")
    with zipfile.ZipFile(qo_charge_zip) as archive:
        qo_charge_summary = json_suffix(archive, "full_market_charge_readiness_summary.json")
        qo_charge_rows = csv_suffix(archive, "rfa_effective_charge_readiness_64.csv")

    upstream_summaries = [
        amount_summary,
        clone_summary,
        salary_probe_summary,
        posture_summary,
        lifecycle_summary,
        rights_summary,
        qo_charge_summary,
    ]
    if not all(summary.get("passed") for summary in upstream_summaries):
        raise RuntimeError("One or more required upstream audits did not pass.")

    market_by_id = unique_by_id(market_rows, "final market")
    ledger_by_id = unique_by_id(ledger_rows, "clone owner ledger")
    automatic_by_id = unique_by_id(automatic_rows, "automatic decisions")
    pending_by_id = unique_by_id(pending_option_rows, "pending user options")
    checkpoint_salary_by_id = unique_by_id(checkpoint_salary_rows, "checkpoint salary candidates")
    lifecycle_by_id = unique_by_id(lifecycle_rows, "contract-option lifecycle")
    rights_by_id = unique_by_id(rights_rows, "RFA rights preview")
    qo_charge_by_id = unique_by_id(qo_charge_rows, "RFA effective-charge readiness")
    unique_candidate_by_id = {
        pid(row.get("player_key")): row for row in unique_candidate_rows if pid(row.get("player_key"))
    }

    attached_rows = [
        row for player_id, row in ledger_by_id.items() if player_id not in market_by_id
    ]
    attached_ids = {pid(row.get("player_id")) for row in attached_rows}
    conflicts: list[dict[str, Any]] = []
    salary_rows: list[dict[str, Any]] = []

    for ledger_row in sorted(attached_rows, key=lambda row: int(pid(row.get("player_id")))):
        player_id = pid(ledger_row.get("player_id"))
        player_name = clean(ledger_row.get("player_name"))
        team = clean(ledger_row.get("owner_after_automatic"))
        selected_salary: int | None = None
        source = ""
        evidence_url = ""
        evidence_detail = ""
        known_likely_incentive: int | str = ""
        known_cap_hit: int | str = ""

        automatic = automatic_by_id.get(player_id)
        pending = pending_by_id.get(player_id)
        checkpoint_salary = checkpoint_salary_by_id.get(player_id)
        unique_candidate = unique_candidate_by_id.get(player_id)
        targeted = TARGETED_ACTIVE_SALARIES.get(player_id)

        if (
            automatic
            and clean(automatic.get("recommendation")) in {"exercise", "retain"}
            and clean(automatic.get("base_salary_2026_27"))
        ):
            selected_salary = money(
                automatic.get("base_salary_2026_27"),
                label=f"{player_name} automatic-decision base salary",
            )
            source = "automatic_decision_selected_base_salary"
            evidence_detail = clean(automatic.get("reason"))
        elif player_id == "1631159" and pending:
            selected_salary = money(
                pending.get("option_salary_2026_27"),
                label=f"{player_name} pending option salary",
            )
            source = "final_market_exclusion_implies_user_option_exercised"
            evidence_detail = (
                "Leonard Miller is excluded from the validated final 226-player market while "
                "the other CHI pending option player is included."
            )
        elif checkpoint_salary:
            selected_salary = money(
                checkpoint_salary.get("numeric_value"),
                label=f"{player_name} checkpoint contract.salary",
            )
            source = "checkpoint_contract_salary"
            evidence_detail = clean(checkpoint_salary.get("field_path"))
        elif unique_candidate and clean(unique_candidate.get("unique_salary_candidate")):
            selected_salary = money(
                unique_candidate.get("unique_salary_candidate"),
                label=f"{player_name} unique upstream salary candidate",
            )
            source = "unique_upstream_salary_candidate"
            evidence_detail = clean(unique_candidate.get("team_candidates"))
        elif targeted:
            selected_salary = int(targeted["base_salary_2026_27"])
            source = "targeted_external_contract_evidence"
            evidence_url = clean(targeted["evidence_url"])
            evidence_detail = clean(targeted["evidence_note"])
            known_likely_incentive = int(targeted["known_likely_incentive_2026_27"])
            known_cap_hit = int(targeted["known_cap_hit_2026_27"])

        if selected_salary is None:
            conflicts.append(
                {
                    "player_id": player_id,
                    "player_name": player_name,
                    "conflict_type": "missing_active_listed_salary",
                    "detail": team,
                }
            )
            continue

        lifecycle = lifecycle_by_id.get(player_id, {})
        active_contract_type = clean(lifecycle.get("active_contract_type_at_split"))
        two_way = "TWO-WAY" in active_contract_type.upper()
        salary_rows.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "team": team,
                "listed_base_salary_2026_27": selected_salary,
                "salary_source": source,
                "salary_evidence_detail": evidence_detail,
                "salary_evidence_url": evidence_url,
                "active_contract_type_at_split": active_contract_type,
                "two_way_contract": two_way,
                "included_in_team_salary_base_component": not two_way,
                "known_likely_incentive_2026_27": known_likely_incentive,
                "known_cap_hit_2026_27": known_cap_hit,
                "salary_applied_to_simulation": False,
                "state_mutation_applied": False,
            }
        )

    salary_by_id = {row["player_id"]: row for row in salary_rows}
    standard_rows = [row for row in salary_rows if not row["two_way_contract"]]
    two_way_rows = [row for row in salary_rows if row["two_way_contract"]]
    targeted_rows = [
        row for row in salary_rows if row["salary_source"] == "targeted_external_contract_evidence"
    ]
    salary_source_counts = Counter(row["salary_source"] for row in salary_rows)

    standard_count_by_team: Counter[str] = Counter()
    standard_salary_by_team: Counter[str] = Counter()
    two_way_count_by_team: Counter[str] = Counter()
    two_way_salary_by_team: Counter[str] = Counter()
    for row in salary_rows:
        team = clean(row["team"])
        if row["two_way_contract"]:
            two_way_count_by_team[team] += 1
            two_way_salary_by_team[team] += int(row["listed_base_salary_2026_27"])
        else:
            standard_count_by_team[team] += 1
            standard_salary_by_team[team] += int(row["listed_base_salary_2026_27"])

    amount_by_id = unique_by_id(amount_rows, "exact amount-bearing market")
    rights_scenario_rows: list[dict[str, Any]] = []
    amount_total = 0
    all_model_qo_total = 0
    model_retained_count = 0

    for player_id in sorted(amount_by_id, key=int):
        row = amount_by_id[player_id]
        amount = money(
            row.get("final_free_agent_amount_2026_27"),
            label=f"{clean(row.get('player_name'))} Free Agent Amount",
        )
        rfa = clean(row.get("market_category")) == "rfa_exact"
        model_recommendation = ""
        qo_model_recommendation = "not_applicable"
        qo_amount: int | str = ""
        model_qo_effective_charge = amount

        if rfa:
            rights = rights_by_id.get(player_id)
            qo = qo_charge_by_id.get(player_id)
            if not rights or not qo:
                conflicts.append(
                    {
                        "player_id": player_id,
                        "player_name": clean(row.get("player_name")),
                        "conflict_type": "missing_rfa_decision_or_qo_evidence",
                        "detail": "",
                    }
                )
                continue
            qo_source_amount = money(
                qo.get("exact_free_agent_amount_2026_27"),
                label=f"{clean(row.get('player_name'))} older RFA amount",
            )
            if qo_source_amount != amount:
                conflicts.append(
                    {
                        "player_id": player_id,
                        "player_name": clean(row.get("player_name")),
                        "conflict_type": "rfa_amount_mismatch",
                        "detail": f"latest={amount}; qo_source={qo_source_amount}",
                    }
                )
            model_recommendation = clean(rights.get("model_recommendation"))
            qo_model_recommendation = clean(qo.get("qo_model_recommendation"))
            qo_decimal = decimal_money(
                qo.get("qo_amount"), label=f"{clean(row.get('player_name'))} QO amount"
            )
            qo_amount = format(qo_decimal, "f")
            if qo_model_recommendation == "issue_qo":
                effective_decimal = max(Decimal(amount), qo_decimal)
                if effective_decimal != effective_decimal.to_integral_value():
                    conflicts.append(
                        {
                            "player_id": player_id,
                            "player_name": clean(row.get("player_name")),
                            "conflict_type": "fractional_effective_team_salary_charge",
                            "detail": format(effective_decimal, "f"),
                        }
                    )
                else:
                    model_qo_effective_charge = int(effective_decimal)

        model_retained = (not rfa) or model_recommendation == "retain_rights"
        amount_total += amount
        all_model_qo_total += model_qo_effective_charge
        model_retained_count += int(model_retained)
        rights_scenario_rows.append(
            {
                "player_id": player_id,
                "player_name": clean(row.get("player_name")),
                "prior_team": clean(row.get("prior_team")),
                "market_category": clean(row.get("market_category")),
                "rights_classification": clean(row.get("rights_classification")),
                "free_agent_amount_2026_27": amount,
                "rfa_model_recommendation": model_recommendation,
                "qo_model_recommendation": qo_model_recommendation,
                "qo_amount_2026_27": qo_amount,
                "effective_charge_under_model_qo": model_qo_effective_charge,
                "retained_all_rights_preserved": True,
                "retained_rfa_model_non_rfa_preserved": model_retained,
                "retained_all_hold_release_floor": False,
                "rights_decision_applied": False,
                "cap_hold_applied": False,
                "state_mutation_applied": False,
            }
        )

    teams = sorted(set(standard_count_by_team) | {clean(row["prior_team"]) for row in rights_scenario_rows})
    scenarios: list[
        tuple[str, str, Callable[[dict[str, Any]], bool], Callable[[dict[str, Any]], int]]
    ] = [
        (
            "all_rights_preserved_no_qo",
            "All 170 amount-bearing rights preserved; RFA charge equals Free Agent Amount.",
            lambda row: True,
            lambda row: int(row["free_agent_amount_2026_27"]),
        ),
        (
            "all_rights_preserved_model_qo",
            "All 170 rights preserved; RFA charge reflects the audited model QO advisory.",
            lambda row: True,
            lambda row: int(row["effective_charge_under_model_qo"]),
        ),
        (
            "rfa_model_advisory_non_rfa_preserved",
            "All 106 non-RFA rights preserved; 64 RFA rows follow the 49/15 model advisory.",
            lambda row: bool(row["retained_rfa_model_non_rfa_preserved"]),
            lambda row: int(row["effective_charge_under_model_qo"]),
        ),
        (
            "all_hold_release_floor",
            "Mathematical hold-release floor; not an instruction that every RFA can be immediately renounced.",
            lambda row: False,
            lambda row: 0,
        ),
    ]

    holds_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rights_scenario_rows:
        holds_by_team[clean(row["prior_team"])].append(row)

    scenario_rows: list[dict[str, Any]] = []
    scenario_totals: dict[str, dict[str, int]] = {}
    for scenario_id, description, retain, charge in scenarios:
        retained_total = 0
        retained_charge_total = 0
        roster_charge_total = 0
        component_total = 0
        for team in teams:
            team_holds = holds_by_team.get(team, [])
            retained = [row for row in team_holds if retain(row)]
            retained_charge = sum(charge(row) for row in retained)
            standard_count = standard_count_by_team[team]
            players_counted_for_incomplete_roster = standard_count + len(retained)
            incomplete_slots = max(0, 12 - players_counted_for_incomplete_roster)
            incomplete_charge = incomplete_slots * ZERO_YOS_MINIMUM_2026_27
            modeled_component = (
                standard_salary_by_team[team] + retained_charge + incomplete_charge
            )
            room_proxy = SALARY_CAP_2026_27 - modeled_component
            retained_total += len(retained)
            retained_charge_total += retained_charge
            roster_charge_total += incomplete_charge
            component_total += modeled_component
            scenario_rows.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_description": description,
                    "team": team,
                    "standard_contract_count": standard_count,
                    "two_way_contract_count_excluded": two_way_count_by_team[team],
                    "standard_contract_base_salary_subtotal": standard_salary_by_team[team],
                    "two_way_compensation_excluded_subtotal": two_way_salary_by_team[team],
                    "free_agent_amount_candidate_count": len(team_holds),
                    "retained_free_agent_count": len(retained),
                    "released_or_renounced_hold_count": len(team_holds) - len(retained),
                    "retained_free_agent_charge_total": retained_charge,
                    "players_counted_for_incomplete_roster": players_counted_for_incomplete_roster,
                    "incomplete_roster_slots": incomplete_slots,
                    "incomplete_roster_charge": incomplete_charge,
                    "modeled_team_salary_component_total": modeled_component,
                    "room_proxy_before_unmodeled_items": room_proxy,
                    "component_posture": (
                        "positive_room_proxy_before_unmodeled_items"
                        if room_proxy > 0
                        else "over_cap_on_modeled_components"
                    ),
                    "official_team_salary_complete": False,
                    "rights_or_salary_applied": False,
                    "state_mutation_applied": False,
                }
            )
        scenario_totals[scenario_id] = {
            "retained_count": retained_total,
            "retained_charge_total": retained_charge_total,
            "incomplete_roster_charge_total": roster_charge_total,
            "modeled_component_total": component_total,
        }

    scenario_by_team = {
        (row["team"], row["scenario_id"]): row for row in scenario_rows
    }
    wide_rows: list[dict[str, Any]] = []
    for team in teams:
        no_qo = scenario_by_team[(team, "all_rights_preserved_no_qo")]
        all_model_qo = scenario_by_team[(team, "all_rights_preserved_model_qo")]
        model = scenario_by_team[(team, "rfa_model_advisory_non_rfa_preserved")]
        floor = scenario_by_team[(team, "all_hold_release_floor")]
        wide_rows.append(
            {
                "team": team,
                "standard_contract_count": standard_count_by_team[team],
                "two_way_contract_count_excluded": two_way_count_by_team[team],
                "standard_contract_base_salary_subtotal": standard_salary_by_team[team],
                "two_way_compensation_excluded_subtotal": two_way_salary_by_team[team],
                "amount_bearing_free_agent_count": no_qo["free_agent_amount_candidate_count"],
                "all_preserved_hold_total_no_qo": no_qo["retained_free_agent_charge_total"],
                "all_preserved_component_total_no_qo": no_qo["modeled_team_salary_component_total"],
                "all_preserved_hold_total_model_qo": all_model_qo["retained_free_agent_charge_total"],
                "all_preserved_component_total_model_qo": all_model_qo["modeled_team_salary_component_total"],
                "model_scenario_retained_count": model["retained_free_agent_count"],
                "model_scenario_hold_total": model["retained_free_agent_charge_total"],
                "model_scenario_incomplete_roster_charge": model["incomplete_roster_charge"],
                "model_scenario_component_total": model["modeled_team_salary_component_total"],
                "model_scenario_room_proxy_before_unmodeled_items": model[
                    "room_proxy_before_unmodeled_items"
                ],
                "release_floor_incomplete_roster_charge": floor["incomplete_roster_charge"],
                "release_floor_component_total": floor["modeled_team_salary_component_total"],
                "release_floor_room_proxy_before_unmodeled_items": floor[
                    "room_proxy_before_unmodeled_items"
                ],
                "official_team_salary_complete": False,
            }
        )

    legacy_by_team = {clean(row.get("team")): row for row in legacy_roster_rows}
    roster_correction_rows: list[dict[str, Any]] = []
    for team in teams:
        legacy = legacy_by_team.get(team, {})
        legacy_count = int(Decimal(clean(legacy.get("recommended_scenario_roster_count")) or "0"))
        legacy_slots = int(Decimal(clean(legacy.get("incomplete_roster_slots")) or "0"))
        legacy_charge = int(Decimal(clean(legacy.get("incomplete_roster_charge")) or "0"))
        corrected_standard_count = standard_count_by_team[team]
        corrected_floor_slots = max(0, 12 - corrected_standard_count)
        corrected_floor_charge = corrected_floor_slots * ZERO_YOS_MINIMUM_2026_27
        roster_correction_rows.append(
            {
                "team": team,
                "legacy_attached_roster_count_including_two_way": legacy_count,
                "identified_two_way_count": two_way_count_by_team[team],
                "corrected_standard_contract_count": corrected_standard_count,
                "legacy_incomplete_roster_slots": legacy_slots,
                "legacy_incomplete_roster_charge": legacy_charge,
                "corrected_all_hold_release_floor_slots": corrected_floor_slots,
                "corrected_all_hold_release_floor_charge": corrected_floor_charge,
                "correction_reason": (
                    "Two-Way Player Salaries are excluded from Team Salary; retained Free Agents "
                    "must be counted separately for each rights scenario."
                ),
                "cba_authority_url": CBA_URL,
                "legacy_values_applied": False,
                "corrected_values_applied": False,
            }
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before team posture preview.")

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 TEAM BASE SALARY AND RIGHTS POSTURE PREVIEW V1")
    print("=" * 132)
    print("Building scenario-aware team salary components as read-only evidence...")

    add("all_required_upstream_audits_passed", all(summary.get("passed") for summary in upstream_summaries), "Seven upstream audits passed.")
    add("ledger_and_market_have_exact_unique_cardinality", len(ledger_by_id) == 587 and len(market_by_id) == 226, f"ledger={len(ledger_by_id)}, market={len(market_by_id)}")
    add("final_population_partitions_361_attached_plus_226_market", len(attached_ids) == 361 and attached_ids.isdisjoint(market_by_id) and attached_ids | set(market_by_id) == set(ledger_by_id), f"attached={len(attached_ids)}, market={len(market_by_id)}")
    add("final_chicago_option_resolution_matches_market", "1631159" in attached_ids and "1631338" in market_by_id, "Leonard Miller attached; Mouhamadou Gueye in market.")
    add("all_361_attached_salaries_resolved", len(salary_rows) == len(salary_by_id) == 361 and not conflicts, f"resolved={len(salary_rows)}/361, conflicts={len(conflicts)}")
    add("salary_source_distribution_matches_expected", salary_source_counts == EXPECTED_SALARY_SOURCE_COUNTS, repr(dict(salary_source_counts)))
    add("targeted_three_close_final_salary_gap", {row["player_id"] for row in targeted_rows} == set(TARGETED_ACTIVE_SALARIES), repr(sorted(row["player_id"] for row in targeted_rows)))
    add("exact_30_two_way_contracts_identified", len(two_way_rows) == 30, f"two_way={len(two_way_rows)}")
    add("exact_331_standard_contracts_identified", len(standard_rows) == 331, f"standard={len(standard_rows)}")
    add("active_listed_salary_total_matches_expected", sum(int(row["listed_base_salary_2026_27"]) for row in salary_rows) == EXPECTED_ACTIVE_LISTED_SALARY_TOTAL, f"total={sum(int(row['listed_base_salary_2026_27']) for row in salary_rows)}")
    add("standard_contract_base_total_matches_expected", sum(int(row["listed_base_salary_2026_27"]) for row in standard_rows) == EXPECTED_STANDARD_CONTRACT_BASE_TOTAL, f"total={sum(int(row['listed_base_salary_2026_27']) for row in standard_rows)}")
    add("two_way_compensation_total_matches_expected", sum(int(row["listed_base_salary_2026_27"]) for row in two_way_rows) == EXPECTED_TWO_WAY_COMPENSATION_TOTAL, f"total={sum(int(row['listed_base_salary_2026_27']) for row in two_way_rows)}")
    add("exact_30_team_salary_partition_ready", len(teams) == 30 and set(teams) == set(legacy_by_team), f"teams={len(teams)}")
    add("legacy_roster_counts_equal_attached_counts", all(int(Decimal(clean(legacy_by_team[team].get('recommended_scenario_roster_count')))) == standard_count_by_team[team] + two_way_count_by_team[team] for team in teams), "Legacy count is confirmed as standard plus two-way attached players.")
    add("exact_170_amounts_joined", len(rights_scenario_rows) == 170 and len({row["player_id"] for row in rights_scenario_rows}) == 170, f"joined={len(rights_scenario_rows)}")
    add("all_free_agent_amount_total_matches_expected", amount_total == EXPECTED_ALL_AMOUNT_TOTAL, f"total={amount_total}")
    add("all_model_qo_effective_total_matches_expected", all_model_qo_total == EXPECTED_ALL_MODEL_QO_EFFECTIVE_TOTAL, f"total={all_model_qo_total}")
    add("rfa_decision_and_qo_sets_match_exact_64", set(rights_by_id) == set(qo_charge_by_id) == {row["player_id"] for row in rights_scenario_rows if row["market_category"] == "rfa_exact"}, f"rights={len(rights_by_id)}, qo={len(qo_charge_by_id)}")
    rfa_advisory_counts = Counter(clean(row.get("model_recommendation")) for row in rights_rows)
    add("rfa_model_advisory_distribution_is_49_15", rfa_advisory_counts == Counter({"retain_rights": 49, "renounce_rights": 15}), repr(dict(rfa_advisory_counts)))
    add("model_scenario_retains_155_exact_holds", model_retained_count == 155 and scenario_totals["rfa_model_advisory_non_rfa_preserved"]["retained_count"] == 155, f"retained={model_retained_count}")
    add("model_scenario_hold_total_matches_expected", scenario_totals["rfa_model_advisory_non_rfa_preserved"]["retained_charge_total"] == EXPECTED_MODEL_SCENARIO_HOLD_TOTAL, f"total={scenario_totals['rfa_model_advisory_non_rfa_preserved']['retained_charge_total']}")
    add("release_floor_roster_charge_is_scenario_corrected", scenario_totals["all_hold_release_floor"]["incomplete_roster_charge_total"] == EXPECTED_RELEASE_FLOOR_ROSTER_CHARGE_TOTAL, f"total={scenario_totals['all_hold_release_floor']['incomplete_roster_charge_total']}")
    add("all_four_scenario_component_totals_match_expected", {key: value["modeled_component_total"] for key, value in scenario_totals.items()} == EXPECTED_SCENARIO_COMPONENT_TOTALS, repr({key: value['modeled_component_total'] for key, value in scenario_totals.items()}))
    add("scenario_board_has_exact_120_rows", len(scenario_rows) == 120 and len(wide_rows) == 30, f"long={len(scenario_rows)}, wide={len(wide_rows)}")
    add("two_way_salary_excluded_and_retained_holds_counted", all(int(row["players_counted_for_incomplete_roster"]) == int(row["standard_contract_count"]) + int(row["retained_free_agent_count"]) for row in scenario_rows), "CBA Article VII Section 4(f) and 4(j) implementation.")
    add("official_team_salary_explicitly_not_claimed", all(not row["official_team_salary_complete"] for row in scenario_rows), "Dead money, complete incentives, 2026 draft-pick holds, and other adjustments remain outside this component preview.")
    add("salary_and_rights_not_applied_to_simulation", all(not row["state_mutation_applied"] for row in salary_rows + rights_scenario_rows + scenario_rows), "Read-only preview.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_team_base_salary_and_rights_posture_preview_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    model_positive_room_teams = sorted(
        row["team"]
        for row in scenario_rows
        if row["scenario_id"] == "rfa_model_advisory_non_rfa_preserved"
        and int(row["room_proxy_before_unmodeled_items"]) > 0
    )
    summary = {
        "version": VERSION,
        "salary_cap_2026_27": SALARY_CAP_2026_27,
        "zero_yos_minimum_2026_27": ZERO_YOS_MINIMUM_2026_27,
        "final_population_count": len(ledger_by_id),
        "final_market_count": len(market_by_id),
        "attached_player_count": len(salary_rows),
        "standard_contract_count": len(standard_rows),
        "two_way_contract_count": len(two_way_rows),
        "active_listed_salary_total_including_two_way": sum(int(row["listed_base_salary_2026_27"]) for row in salary_rows),
        "standard_contract_base_salary_total": sum(int(row["listed_base_salary_2026_27"]) for row in standard_rows),
        "two_way_compensation_excluded_total": sum(int(row["listed_base_salary_2026_27"]) for row in two_way_rows),
        "salary_source_counts": dict(sorted(salary_source_counts.items())),
        "amount_bearing_free_agent_count": len(rights_scenario_rows),
        "scenario_totals": scenario_totals,
        "model_scenario_positive_room_proxy_team_count": len(model_positive_room_teams),
        "model_scenario_positive_room_proxy_teams": model_positive_room_teams,
        "legacy_roster_charge_total_not_used": sum(int(Decimal(clean(row.get("incomplete_roster_charge")) or "0")) for row in legacy_roster_rows),
        "corrected_release_floor_roster_charge_total": scenario_totals["all_hold_release_floor"]["incomplete_roster_charge_total"],
        "official_team_salary_complete": False,
        "unmodeled_team_salary_items": [
            "dead money and waived/stretched salary",
            "complete likely and unlikely incentive treatment",
            "2026 unsigned first-round pick cap holds and draft-rights timing",
            "offer sheets and other live transaction charges",
            "exceptions and apron-specific adjustments",
        ],
        "rights_or_salary_applied": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_amount_audit": amount_zip.name,
        "source_clone_audit": clone_zip.name,
        "source_salary_probe_audit": salary_probe_zip.name,
        "source_team_posture_audit": posture_zip.name,
        "source_lifecycle_audit": lifecycle_zip.name,
        "source_rights_preview_audit": rights_zip.name,
        "source_qo_charge_audit": qo_charge_zip.name,
        "cba_authority_url": CBA_URL,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Resolve dead money, complete incentive treatment, and 2026 rookie-pick holds; "
            "then promote the component preview into an official Team Salary state model."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_team_base_salary_and_rights_posture_preview_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "active_listed_salary_evidence_361.csv", salary_rows)
        write_csv(export / "standard_contract_salary_base_331.csv", standard_rows)
        write_csv(export / "two_way_salary_excluded_30.csv", two_way_rows)
        write_csv(export / "targeted_salary_resolution_3.csv", targeted_rows)
        write_csv(export / "full_market_rights_scenario_inputs_170.csv", rights_scenario_rows)
        write_csv(export / "team_rights_posture_scenarios_120.csv", scenario_rows)
        write_csv(export / "team_rights_posture_wide_30.csv", wide_rows)
        write_csv(export / "legacy_roster_charge_correction_30.csv", roster_correction_rows)
        write_csv(export / "team_base_salary_and_rights_posture_conflicts.csv", conflicts)
        write_csv(export / "team_base_salary_and_rights_posture_checks.csv", checks)
        (export / "team_base_salary_and_rights_posture_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 TEAM BASE SALARY AND RIGHTS POSTURE PREVIEW V1
===================================================

Purpose
-------
Join the final 361 attached-player salary layer to all 170 exact Free Agent
Amounts and produce four scenario-aware, 30-team cap-component previews.

Important scope
---------------
This is an exact active listed-base-salary and cap-hold component preview, not
an official complete Team Salary ledger. It explicitly excludes Two-Way Player
Salaries from Team Salary and recomputes incomplete-roster charges separately
for each retained-rights scenario.

CBA correction
--------------
Article VII Section 4(f) counts contracted players included in Team Salary and
retained Free Agents when testing for fewer than 12 players. Section 4(j)
excludes Two-Way Player Salaries from Team Salary. The older static roster-charge
table is therefore preserved only for comparison and is not used.

Still outside this layer
------------------------
- dead money and waived/stretched salary
- complete incentive treatment
- 2026 draft-pick cap holds and draft-rights timing
- offer sheets, live transaction charges, exceptions, and apron adjustments

No salary, cap hold, rights decision, roster, simulation, or checkpoint state is
mutated by this preview.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Team Base Salary and Rights Posture Preview V1 failed: " + ", ".join(failed)
        )

    print("")
    print("=" * 132)
    print("2026 TEAM BASE SALARY AND RIGHTS POSTURE PREVIEW V1 PASSED")
    print("=" * 132)
    print("Attached salaries resolved:       361/361")
    print("Standard Team Salary contracts:   331")
    print("Two-Way salaries excluded:         30")
    print("Exact amount-bearing holds:       170/170")
    print("Team scenario rows:               120/120")
    print(f"Standard base salary total: ${EXPECTED_STANDARD_CONTRACT_BASE_TOTAL:,.0f}")
    print(f"Model scenario hold total:  ${EXPECTED_MODEL_SCENARIO_HOLD_TOTAL:,.0f}")
    print("Official Team Salary complete:     NO")
    print("Rights/salaries applied:             0")
    print("Checkpoint write:        NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
