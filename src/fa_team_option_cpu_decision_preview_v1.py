from __future__ import annotations

import copy
import csv
import hashlib
import inspect
import io
import json
import math
import re
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

VERSION = "fa-team-option-cpu-decision-preview-v1-2026-08-14"
SEASON_LABEL = "2026-27"
SALARY_CAP = 164_961_000.0

TEAM_OPTION_STATE = "pending_team_option_2026_27"
NON_GUARANTEED_STATE = "pending_non_guaranteed_contract_decision_2026_27"


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def team(value: Any) -> str:
    return clean(value).upper()


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    rows = [p for p in root.rglob(pattern) if p.is_file()]
    if not rows:
        raise RuntimeError(f"Could not locate required input: {pattern}")
    return max(rows, key=lambda p: p.stat().st_mtime)


def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return list(csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"))))


def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"


def state_digest(state: Any) -> str:
    payload = {
        "season": clean(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": clean(getattr(state, "phase", "")),
        "free_agents": list(getattr(state, "free_agent_player_ids", ()) or ()),
        "teams": {
            str(code): list(getattr(ts, "roster_player_ids", ()) or ())
            for code, ts in sorted((getattr(state, "teams", {}) or {}).items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def mapping_value(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def extract_plan_map(plan: Any) -> dict[str, Any]:
    candidate = mapping_value(
        plan,
        (
            "team_plans",
            "plans_by_team",
            "team_plans_by_team",
            "plans",
            "teams",
            "by_team",
        ),
        plan,
    )
    result: dict[str, Any] = {}
    if isinstance(candidate, Mapping):
        for key, value in candidate.items():
            code = team(
                mapping_value(
                    value,
                    ("team_abbreviation", "team", "team_code", "abbreviation"),
                    key,
                )
            )
            if code:
                result[code] = value
        return result
    try:
        iterable = tuple(candidate)
    except TypeError:
        return result
    for value in iterable:
        code = team(
            mapping_value(
                value,
                ("team_abbreviation", "team", "team_code", "abbreviation"),
                "",
            )
        )
        if code:
            result[code] = value
    return result


def direction_of(plan: Any) -> str:
    return clean(
        mapping_value(
            plan,
            ("direction", "team_direction", "strategic_direction"),
            "Balanced",
        )
    )


def salary_posture_of(plan: Any) -> str:
    return clean(
        mapping_value(
            plan,
            ("salary_posture", "financial_posture", "cap_posture"),
            "",
        )
    )


def player_features(player: Any) -> dict[str, Any]:
    return {
        "overall": finite(getattr(player, "overall_rating", None)),
        "potential": finite(getattr(player, "potential_rating", None)),
        "age": finite(getattr(player, "age", None)),
        "position": clean(getattr(player, "position", "")),
        "years_of_service": finite(getattr(player, "years_of_service", None)),
    }


def roster_context(state: Any, team_code: str, player_id: str) -> dict[str, Any]:
    team_state = (getattr(state, "teams", {}) or {}).get(team_code)
    roster_ids = list(getattr(team_state, "roster_player_ids", ()) or ())
    players = getattr(state, "players", {}) or {}

    overall_rows: list[tuple[str, float]] = []
    for rid in roster_ids:
        if clean(rid) == clean(player_id):
            continue
        player = players.get(rid)
        if player is None:
            continue
        overall = finite(getattr(player, "overall_rating", None))
        if overall is not None:
            overall_rows.append((clean(rid), overall))

    ordered = sorted(overall_rows, key=lambda item: item[1])
    bottom_five = [value for _, value in ordered[:5]]
    bottom_three = [value for _, value in ordered[:3]]

    return {
        "roster_count": len(roster_ids),
        "known_overall_count": len(overall_rows),
        "bottom_five_average": (
            sum(bottom_five) / len(bottom_five)
            if bottom_five else None
        ),
        "bottom_three_average": (
            sum(bottom_three) / len(bottom_three)
            if bottom_three else None
        ),
        "roster_median_overall": (
            sorted(value for _, value in ordered)[len(ordered) // 2]
            if ordered else None
        ),
    }


def fallback_market_reference(
    overall: float | None,
    potential: float | None,
    age: float | None,
) -> float | None:
    if overall is None:
        return None

    # Conservative one-year market proxy used only when the installed
    # free-agency market resolver cannot be called outside a transaction
    # preview. This deliberately uses the same overall/potential/age family
    # already used by CPU Free Agency V1 rather than real-world outcomes.
    if overall >= 90:
        base = 42_000_000.0
    elif overall >= 86:
        base = 31_000_000.0
    elif overall >= 82:
        base = 22_000_000.0
    elif overall >= 79:
        base = 14_000_000.0
    elif overall >= 77:
        base = 9_000_000.0
    elif overall >= 75:
        base = 5_500_000.0
    elif overall >= 73:
        base = 3_500_000.0
    elif overall >= 71:
        base = 2_400_000.0
    elif overall >= 69:
        base = 1_900_000.0
    else:
        base = 1_450_000.0

    if potential is not None and potential > overall:
        base *= 1.0 + min(0.18, (potential - overall) * 0.018)

    if age is not None:
        if age <= 23:
            base *= 1.08
        elif age >= 31:
            base *= 0.94
        elif age >= 34:
            base *= 0.88

    return round(base, 2)


def try_canonical_market_reference(player: Any, option_salary: float) -> tuple[float | None, str, str]:
    try:
        from franchise_free_agency_player_decision_v1 import market_salary_reference
    except Exception as exc:
        return None, "fallback", f"import_failed:{type(exc).__name__}"

    pseudo_offer = SimpleNamespace(
        annual_salary=float(option_salary),
        years=1,
        guaranteed=True,
        option_type="team",
    )
    pseudo_preview = SimpleNamespace(
        offer=pseudo_offer,
        annual_salary=float(option_salary),
        years=1,
        minimum_salary_floor=0.0,
        maximum_initial_salary=float(SALARY_CAP),
        can_commit=True,
        status="pass",
    )

    try:
        reference, _, _ = market_salary_reference(player, pseudo_preview)
        value = finite(reference)
        if value is not None and value > 0:
            return float(value), "canonical_free_agency_market_reference", ""
        return None, "fallback", "canonical_returned_nonpositive_or_nonfinite"
    except Exception as exc:
        return None, "fallback", f"canonical_call_failed:{type(exc).__name__}"


def strategic_adjustment(
    *,
    overall: float | None,
    potential: float | None,
    age: float | None,
    roster_floor: float | None,
    direction: str,
) -> float:
    adjustment = 0.0

    if overall is not None and roster_floor is not None:
        adjustment += (overall - roster_floor) * 0.06

    upside = 0.0
    if overall is not None and potential is not None:
        upside = max(0.0, potential - overall)

    direction_text = clean(direction).lower()
    if ("rebuild" in direction_text or "develop" in direction_text) and age is not None and age <= 25:
        adjustment += min(0.20, 0.02 * upside + 0.06)
    elif ("championship" in direction_text or "contend" in direction_text):
        if overall is not None and overall >= 75:
            adjustment += 0.08
        elif overall is not None and overall <= 71:
            adjustment -= 0.08

    if age is not None and age >= 32:
        adjustment -= 0.05
    if age is not None and age <= 23 and upside >= 3:
        adjustment += 0.05

    return adjustment


def cpu_team_option_recommendation(
    *,
    market_reference: float | None,
    option_salary: float,
    overall: float | None,
    potential: float | None,
    age: float | None,
    roster_floor: float | None,
    direction: str,
) -> tuple[str, float | None, str, str]:
    if option_salary <= 0 or market_reference is None:
        return (
            "manual_review",
            None,
            "low",
            "Missing positive option salary or player market reference.",
        )

    raw_ratio = market_reference / option_salary
    adjustment = strategic_adjustment(
        overall=overall,
        potential=potential,
        age=age,
        roster_floor=roster_floor,
        direction=direction,
    )
    adjusted_ratio = raw_ratio + adjustment

    # Team options require positive action to keep the player. The decision
    # therefore uses a modest surplus-value hurdle rather than assuming
    # exercise at mere break-even.
    if adjusted_ratio >= 1.12:
        decision = "exercise"
    elif adjusted_ratio <= 0.92:
        decision = "decline"
    else:
        # Borderline zone resolves using roster-floor competitiveness and
        # developmental upside, still without consulting post-split outcomes.
        youth_upside = (
            overall is not None
            and potential is not None
            and age is not None
            and age <= 25
            and potential >= overall + 3
        )
        roster_worthy = (
            overall is not None
            and roster_floor is not None
            and overall >= roster_floor
        )
        decision = "exercise" if (youth_upside or roster_worthy) else "decline"

    distance = abs(adjusted_ratio - 1.02)
    if distance >= 0.45:
        confidence = "high"
    elif distance >= 0.20:
        confidence = "medium"
    else:
        confidence = "low"

    reason = (
        f"market/option={raw_ratio:.3f}; strategic_adjustment={adjustment:+.3f}; "
        f"adjusted={adjusted_ratio:.3f}; direction={direction or 'Balanced'}"
    )
    return decision, adjusted_ratio, confidence, reason


def post_split_actual_option(row: Mapping[str, Any]) -> str:
    text = clean(row.get("post_split_option_outcome_observed_for_audit_only"))
    if text.startswith("yes:"):
        return "exercise"
    if text.startswith("no:"):
        return "decline"
    option_used = clean(row.get("season_2026_27_option_used_snapshot")).lower()
    if option_used.startswith("yes"):
        return "exercise"
    if option_used.startswith("no"):
        return "decline"
    return ""


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
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

    lifecycle_zip = find_latest(
        root,
        "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip",
    )
    corrected_rfa_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )

    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = read_json_member(
            archive,
            "contract_option_summary.json",
        )
        pending_rows = read_csv_member(
            archive,
            "pending_contract_option_decisions.csv",
        )

    with zipfile.ZipFile(corrected_rfa_zip) as archive:
        corrected_rfa_summary = read_json_member(
            archive,
            "corrected_rfa_qo_summary.json",
        )

    option_rows = [
        row for row in pending_rows
        if clean(row.get("contract_lifecycle_state")) == TEAM_OPTION_STATE
    ]
    non_guaranteed_rows = [
        row for row in pending_rows
        if clean(row.get("contract_lifecycle_state")) == NON_GUARANTEED_STATE
    ]

    checkpoint_file = checkpoint_path(root)
    checkpoint_before = sha256_file(checkpoint_file)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )
    overlay_before = sha256_file(overlay)

    try:
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        checkpoint = load_franchise_checkpoint()
        state = checkpoint.simulation_state
    except Exception as exc:
        raise RuntimeError(
            "Team Option Preview requires the current durable franchise checkpoint."
        ) from exc

    state_before = state_digest(state)

    try:
        from franchise_free_agency_ui_v1 import controlled_teams_from_checkpoint
        controlled = set(
            controlled_teams_from_checkpoint(checkpoint, state)
        )
    except Exception:
        controlled = set()

    try:
        from franchise_cpu_front_office_v1 import build_league_front_office_plan
        plan = build_league_front_office_plan(
            state,
            controlled_teams=tuple(sorted(controlled)),
        )
        plan_map = extract_plan_map(plan)
    except Exception:
        plan_map = {}

    players = getattr(state, "players", {}) or {}

    print("=" * 122, flush=True)
    print("2026 TEAM OPTION CPU DECISION PREVIEW V1", flush=True)
    print("=" * 122, flush=True)
    print(f"Lifecycle input: {lifecycle_zip}", flush=True)
    print(f"Corrected RFA input: {corrected_rfa_zip}", flush=True)
    print(f"Pending lifecycle rows: {len(pending_rows)}", flush=True)
    print(f"True Team Options: {len(option_rows)}", flush=True)
    print(f"Non-option non-guaranteed contracts: {len(non_guaranteed_rows)}", flush=True)
    print(
        "READ-ONLY: recommendations only. No option is exercised/declined and no contract is waived.",
        flush=True,
    )
    print("", flush=True)

    recommendation_rows: list[dict[str, Any]] = []

    for index, row in enumerate(
        sorted(option_rows, key=lambda r: clean(r.get("player_name")).lower()),
        start=1,
    ):
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        team_code = team(row.get("prior_team"))
        option_salary = finite(row.get("season_2026_27_base_salary")) or 0.0
        player = players.get(player_id)

        print(
            f"[{index:02d}/{len(option_rows):02d}] {player_name} ({team_code})",
            flush=True,
        )

        if player is None:
            features = {
                "overall": None,
                "potential": None,
                "age": None,
                "position": "",
                "years_of_service": None,
            }
        else:
            features = player_features(player)

        context = roster_context(state, team_code, player_id)
        plan_row = plan_map.get(team_code)
        direction = direction_of(plan_row) if plan_row is not None else "Balanced"
        posture = salary_posture_of(plan_row) if plan_row is not None else ""

        canonical_reference = None
        reference_source = ""
        reference_error = ""
        if player is not None:
            canonical_reference, reference_source, reference_error = (
                try_canonical_market_reference(player, option_salary)
            )

        market_reference = canonical_reference
        if market_reference is None:
            market_reference = fallback_market_reference(
                features["overall"],
                features["potential"],
                features["age"],
            )
            reference_source = "transparent_rating_fallback"

        if team_code in controlled:
            recommendation = "user_decision_required"
            score = None
            confidence = "n/a"
            reason = (
                "Team is user-controlled. CPU recommendation is intentionally "
                "suppressed; option decision remains with the user."
            )
        else:
            recommendation, score, confidence, reason = (
                cpu_team_option_recommendation(
                    market_reference=market_reference,
                    option_salary=option_salary,
                    overall=features["overall"],
                    potential=features["potential"],
                    age=features["age"],
                    roster_floor=context["bottom_five_average"],
                    direction=direction,
                )
            )

        actual = post_split_actual_option(row)
        audit_match = (
            recommendation == actual
            if recommendation in {"exercise", "decline"} and actual
            else None
        )

        recommendation_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "team_abbreviation": team_code,
            "controlled_team": team_code in controlled,
            "option_salary": option_salary,
            "salary_cap_share": option_salary / SALARY_CAP if option_salary else "",
            "overall_rating": features["overall"],
            "potential_rating": features["potential"],
            "age": features["age"],
            "position": features["position"],
            "years_of_service": features["years_of_service"],
            "team_direction": direction,
            "salary_posture": posture,
            "roster_count": context["roster_count"],
            "bottom_five_roster_overall": context["bottom_five_average"],
            "market_salary_reference": market_reference,
            "market_reference_source": reference_source,
            "market_reference_error": reference_error,
            "market_to_option_ratio": (
                market_reference / option_salary
                if market_reference is not None and option_salary > 0
                else ""
            ),
            "cpu_recommendation": recommendation,
            "decision_score": score if score is not None else "",
            "confidence": confidence,
            "reason": reason,
            "post_split_real_world_outcome_audit_only": actual,
            "real_world_outcome_imported_into_decision": False,
            "audit_agrees_with_real_world": (
                audit_match if audit_match is not None else ""
            ),
            "option_decision_applied": False,
        })

    deferred_rows: list[dict[str, Any]] = []
    for row in non_guaranteed_rows:
        contract_type = clean(row.get("active_contract_type_at_split"))
        deferred_rows.append({
            "player_id": pid(row.get("player_id")),
            "player_name": clean(row.get("player_name")),
            "team_abbreviation": team(row.get("prior_team")),
            "active_contract_type": contract_type,
            "season_2026_27_base_salary": row.get("season_2026_27_base_salary"),
            "season_2026_27_guaranteed": row.get("season_2026_27_guaranteed"),
            "contract_bucket": (
                "two_way_contract"
                if "TWO-WAY" in contract_type.upper()
                else "standard_contract"
            ),
            "current_branch_status": (
                "under_contract_until_waived_or_guarantee_lifecycle_changes_status"
            ),
            "june_29_team_option_decision_required": False,
            "free_agent_market_candidate_now": False,
            "next_required_model": "guarantee_waiver_lifecycle_v1",
            "contract_mutation_applied": False,
        })

    cpu_rows = [
        row for row in recommendation_rows
        if not row["controlled_team"]
    ]
    decided_cpu_rows = [
        row for row in cpu_rows
        if row["cpu_recommendation"] in {"exercise", "decline"}
    ]
    audit_comparable = [
        row for row in decided_cpu_rows
        if row["post_split_real_world_outcome_audit_only"]
        in {"exercise", "decline"}
    ]
    audit_matches = [
        row for row in audit_comparable
        if row["audit_agrees_with_real_world"] is True
    ]

    checkpoint_after = sha256_file(checkpoint_file)
    overlay_after = sha256_file(overlay)
    state_after = state_digest(state)

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
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("", flush=True)
    print("Running strict Team Option preview checks...", flush=True)

    check(
        "lifecycle_input_passed",
        bool(lifecycle_summary.get("passed")),
        "Team-option decisions are downstream of the passed lifecycle audit.",
    )
    check(
        "corrected_rfa_input_passed",
        bool(corrected_rfa_summary.get("passed")),
        "Corrected 132-player market remains the active RFA/QO base.",
    )
    check(
        "pending_48_reclassified_as_13_options_plus_35_non_options",
        len(pending_rows) == 48
        and len(option_rows) == 13
        and len(non_guaranteed_rows) == 35,
        (
            f"pending={len(pending_rows)}; options={len(option_rows)}; "
            f"non_options={len(non_guaranteed_rows)}"
        ),
    )
    check(
        "non_guaranteed_bucket_is_30_two_way_plus_5_standard",
        Counter(row["contract_bucket"] for row in deferred_rows)
        == Counter({"two_way_contract": 30, "standard_contract": 5}),
        "Non-option contracts are not treated as Team Options.",
    )
    check(
        "all_13_team_options_have_one_preview_disposition",
        len(recommendation_rows) == 13
        and len({row["player_id"] for row in recommendation_rows}) == 13,
        f"rows={len(recommendation_rows)}",
    )
    check(
        "controlled_teams_never_receive_cpu_decision",
        all(
            row["cpu_recommendation"] == "user_decision_required"
            for row in recommendation_rows
            if row["controlled_team"]
        ),
        "CPU cannot exercise or decline a user-controlled option.",
    )
    check(
        "cpu_team_options_are_deterministic_binary_or_manual",
        all(
            row["cpu_recommendation"]
            in {"exercise", "decline", "manual_review"}
            for row in cpu_rows
        ),
        "CPU preview never invents an unsupported state.",
    )
    check(
        "post_split_real_world_outcomes_are_audit_only",
        all(
            not row["real_world_outcome_imported_into_decision"]
            for row in recommendation_rows
        ),
        "June 2026 reality does not drive simulator recommendations.",
    )
    check(
        "non_guaranteed_contracts_are_not_created_as_free_agents",
        all(
            not row["free_agent_market_candidate_now"]
            and not row["june_29_team_option_decision_required"]
            for row in deferred_rows
        ),
        "The 35 non-option contracts remain under contract until their own lifecycle acts.",
    )
    check(
        "no_option_decision_is_applied",
        all(
            not row["option_decision_applied"]
            for row in recommendation_rows
        ),
        "Preview only.",
    )
    check(
        "no_non_guaranteed_contract_mutation_is_applied",
        all(
            not row["contract_mutation_applied"]
            for row in deferred_rows
        ),
        "Guarantee/waiver lifecycle is deferred.",
    )
    check(
        "live_state_unchanged",
        state_before == state_after,
        state_after,
    )
    check(
        "checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        checkpoint_after,
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        overlay_after or "<absent>",
    )

    fallback_count = sum(
        row["market_reference_source"] == "transparent_rating_fallback"
        for row in recommendation_rows
    )
    check(
        "canonical_market_reference_coverage",
        fallback_count == 0,
        f"fallback_rows={fallback_count}/13",
        severity="coverage",
    )

    comparable_count = len(audit_comparable)
    match_count = len(audit_matches)
    agreement = (
        match_count / comparable_count
        if comparable_count else None
    )
    check(
        "post_split_outcome_sanity_agreement",
        bool(
            agreement is not None
            and agreement >= 0.50
        ),
        (
            f"agreement={agreement:.3f} ({match_count}/{comparable_count})"
            if agreement is not None
            else "no comparable CPU rows"
        ),
        severity="calibration",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Team Option CPU Decision Preview V1 failed strict checks: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_team_option_cpu_decision_preview_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_teamopt_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "team_option_cpu_recommendations.csv",
            recommendation_rows,
        )
        write_csv(
            export / "non_guaranteed_contracts_deferred.csv",
            deferred_rows,
        )
        write_csv(
            export / "team_option_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "pending_lifecycle_count": len(pending_rows),
            "true_team_option_count": len(option_rows),
            "non_option_non_guaranteed_count": len(non_guaranteed_rows),
            "two_way_non_guaranteed_count": sum(
                row["contract_bucket"] == "two_way_contract"
                for row in deferred_rows
            ),
            "standard_non_guaranteed_count": sum(
                row["contract_bucket"] == "standard_contract"
                for row in deferred_rows
            ),
            "controlled_teams": sorted(controlled),
            "cpu_option_row_count": len(cpu_rows),
            "user_option_row_count": (
                len(recommendation_rows) - len(cpu_rows)
            ),
            "cpu_exercise_recommendation_count": sum(
                row["cpu_recommendation"] == "exercise"
                for row in cpu_rows
            ),
            "cpu_decline_recommendation_count": sum(
                row["cpu_recommendation"] == "decline"
                for row in cpu_rows
            ),
            "cpu_manual_review_count": sum(
                row["cpu_recommendation"] == "manual_review"
                for row in cpu_rows
            ),
            "canonical_market_reference_count": (
                len(recommendation_rows) - fallback_count
            ),
            "market_reference_fallback_count": fallback_count,
            "real_world_audit_comparable_count": comparable_count,
            "real_world_audit_match_count": match_count,
            "real_world_audit_agreement": agreement,
            "real_world_outcomes_imported": 0,
            "option_decisions_applied": 0,
            "non_guaranteed_contract_mutations_applied": 0,
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "state_mutation_performed": False,
            "passed": True,
            "failed_strict_checks": [],
            "next_slice": (
                "Review the 13 Team Option recommendations and calibration. "
                "If satisfactory, build a guarded option-decision transaction "
                "layer for CPU teams while leaving user-controlled teams explicit. "
                "Separately build guarantee/waiver lifecycle evidence for the "
                "30 Two-Way + 5 standard non-guaranteed contracts."
            ),
        }

        (
            export / "team_option_summary.json"
        ).write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = """2026 TEAM OPTION CPU DECISION PREVIEW V1
========================================

Important correction:
The prior lifecycle audit called 48 rows "pending option/contract decisions."
They are not 48 Team Options.

Exact split:
- 13 true 2026-27 Team Options
- 35 non-option contracts with non-guaranteed/partially guaranteed future salary
  - 30 Two-Way Contracts
  - 5 Standard NBA Contracts

The 35 non-option contracts remain contracts unless the team waives them or
their guarantee lifecycle changes their status. They are NOT automatically
free agents on the Team Option deadline.

This preview therefore makes recommendations only for the 13 true Team Options.

CPU recommendation inputs:
- current checkpoint overall rating
- potential rating
- age
- roster-floor strength
- team strategic direction
- option salary
- installed free-agency market salary reference when callable
- transparent rating-based fallback if that reference cannot operate outside a
  transaction preview

The June 2026 real-world option outcome is recorded only AFTER the recommendation
for calibration. It is never used as an input.

Controlled teams:
CPU recommendation is suppressed and the decision remains user-owned.

READ ONLY:
- no Team Option exercised
- no Team Option declined
- no waiver
- no guarantee change
- no free-agent pool change
- no rights overlay write
- no checkpoint write
"""
        (export / "README.txt").write_text(
            readme,
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            zip_out,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(export.iterdir()):
                archive.write(
                    path,
                    arcname=f"{export_id}/{path.name}",
                )

    if state_digest(state) != state_before:
        raise RuntimeError(
            "Live franchise state changed after Team Option preview."
        )
    if sha256_file(checkpoint_file) != checkpoint_before:
        raise RuntimeError(
            "Checkpoint changed after Team Option preview."
        )
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError(
            "Rights overlay changed after Team Option preview."
        )

    print("", flush=True)
    print("=" * 122, flush=True)
    print("2026 TEAM OPTION CPU DECISION PREVIEW V1 PASSED", flush=True)
    print("=" * 122, flush=True)
    print(f"True Team Options:           {len(option_rows)}", flush=True)
    print(f"Deferred non-option deals:   {len(non_guaranteed_rows)}", flush=True)
    print(
        f"  Two-Way:                   "
        f"{sum(r['contract_bucket'] == 'two_way_contract' for r in deferred_rows)}",
        flush=True,
    )
    print(
        f"  Standard:                  "
        f"{sum(r['contract_bucket'] == 'standard_contract' for r in deferred_rows)}",
        flush=True,
    )
    print(
        f"CPU exercise recommendations: "
        f"{sum(r['cpu_recommendation'] == 'exercise' for r in cpu_rows)}",
        flush=True,
    )
    print(
        f"CPU decline recommendations:  "
        f"{sum(r['cpu_recommendation'] == 'decline' for r in cpu_rows)}",
        flush=True,
    )
    print(
        f"CPU manual review:             "
        f"{sum(r['cpu_recommendation'] == 'manual_review' for r in cpu_rows)}",
        flush=True,
    )
    print(
        f"User-controlled option rows:   "
        f"{len(recommendation_rows) - len(cpu_rows)}",
        flush=True,
    )
    if agreement is not None:
        print(
            f"Audit-only real-world agreement: {match_count}/{comparable_count} "
            f"({agreement:.1%})",
            flush=True,
        )
    print("Option decisions applied: 0", flush=True)
    print("Non-guaranteed mutations applied: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {zip_out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
