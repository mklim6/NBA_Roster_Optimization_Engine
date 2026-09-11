from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pickle
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

VERSION = "fa-qo-issuance-decision-preview-v1-2026-08-14"
SEASON_LABEL = "2026-27"
SALARY_CAP = 164_961_000.0
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_ELIGIBLE = 64
EXPECTED_FINAL_MARKET = 226
EXPECTED_CONTROLLED_TEAM = "CHI"
EXPECTED_CHI_QO_NAMES = {
    "Mouhamadou Gueye",
    "Yuki Kawamura",
    "Lachlan Olbrich",
}

TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


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


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = clean(value).lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


def sha256_file(path: Path) -> str:
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


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


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


def player_features(player: Any) -> dict[str, Any]:
    return {
        "overall": finite(getattr(player, "overall_rating", None)),
        "potential": finite(getattr(player, "potential_rating", None)),
        "age": finite(getattr(player, "age", None)),
        "position": clean(getattr(player, "position", "")),
        "years_of_service": finite(getattr(player, "years_of_service", None)),
    }


def fallback_market_reference(
    overall: float | None,
    potential: float | None,
    age: float | None,
) -> float | None:
    if overall is None:
        return None

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
        elif age >= 34:
            base *= 0.88
        elif age >= 31:
            base *= 0.94

    return round(base, 2)


def try_canonical_market_reference(
    player: Any,
    qo_amount: float,
) -> tuple[float | None, str, str]:
    try:
        from franchise_free_agency_player_decision_v1 import market_salary_reference
    except Exception as exc:
        return None, "fallback", f"import_failed:{type(exc).__name__}"

    pseudo_offer = SimpleNamespace(
        annual_salary=float(max(qo_amount, 1.0)),
        years=1,
        guaranteed=True,
        option_type="qualifying_offer_preview",
    )
    pseudo_preview = SimpleNamespace(
        offer=pseudo_offer,
        annual_salary=float(max(qo_amount, 1.0)),
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


def controlled_teams_from_state(checkpoint: Any, state: Any) -> set[str]:
    try:
        from franchise_free_agency_ui_v1 import controlled_teams_from_checkpoint
        values = controlled_teams_from_checkpoint(checkpoint, state)
        return {team(value) for value in values if team(value)}
    except Exception:
        return set()


def roster_context(
    prior_team: str,
    team_count_map: Mapping[str, int],
) -> dict[str, Any]:
    count = int(team_count_map.get(prior_team, 0))
    return {
        "team_roster_count": count,
        "roster_need_adjustment": (
            0.05 if count <= 11
            else 0.03 if count <= 13
            else 0.00 if count <= 16
            else -0.03 if count <= 18
            else -0.05
        ),
    }


def qo_decision_score(
    *,
    market_reference: float,
    qo_amount: float,
    overall: float | None,
    potential: float | None,
    age: float | None,
    team_roster_count: int,
) -> dict[str, Any]:
    ratio = market_reference / qo_amount

    # QO tendering has option value: it preserves right-of-first-refusal while
    # the actual downside is that the player can accept the one-year QO.
    retention_optionality = 0.12

    upside_adjustment = 0.0
    if overall is not None and potential is not None and age is not None:
        gap = potential - overall
        if age <= 24 and gap >= 4:
            upside_adjustment = 0.10
        elif age <= 26 and gap >= 3:
            upside_adjustment = 0.07
        elif age <= 28 and gap >= 2:
            upside_adjustment = 0.04

    age_risk_adjustment = 0.0
    if age is not None:
        if age >= 32:
            age_risk_adjustment = -0.05
        elif age >= 29:
            age_risk_adjustment = -0.02

    if team_roster_count <= 11:
        roster_adjustment = 0.05
    elif team_roster_count <= 13:
        roster_adjustment = 0.03
    elif team_roster_count <= 16:
        roster_adjustment = 0.0
    elif team_roster_count <= 18:
        roster_adjustment = -0.03
    else:
        roster_adjustment = -0.05

    absolute_qo_risk = 0.0
    qo_pct_cap = qo_amount / SALARY_CAP
    if qo_pct_cap >= 0.15 and ratio < 1.10:
        absolute_qo_risk -= 0.07
    elif qo_pct_cap >= 0.10 and ratio < 1.00:
        absolute_qo_risk -= 0.04

    score = (
        ratio
        + retention_optionality
        + upside_adjustment
        + age_risk_adjustment
        + roster_adjustment
        + absolute_qo_risk
    )

    if ratio >= 1.05:
        recommendation = "issue_qo"
    elif ratio <= 0.60 and score < 0.90:
        recommendation = "do_not_issue_qo"
    else:
        recommendation = "issue_qo" if score >= 0.98 else "do_not_issue_qo"

    distance = abs(score - 0.98)
    if distance >= 0.35:
        confidence = "high"
    elif distance >= 0.15:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "market_to_qo_ratio": ratio,
        "retention_optionality_adjustment": retention_optionality,
        "upside_adjustment": upside_adjustment,
        "age_risk_adjustment": age_risk_adjustment,
        "roster_adjustment": roster_adjustment,
        "absolute_qo_risk_adjustment": absolute_qo_risk,
        "decision_score": score,
        "recommendation": recommendation,
        "confidence": confidence,
    }


def main() -> int:
    root = Path.cwd().resolve()

    qo_zip = find_latest(
        root,
        "fa_final_market_qo_amount_completion_v1_0_4_2026-27_*.zip",
    )
    eligibility_zip = find_latest(
        root,
        "fa_final_market_rfa_qo_eligibility_readiness_v1_2026-27_*.zip",
    )
    branch_zip = find_latest(
        root,
        "fa_offseason_opening_branch_reconstruction_preview_v1_0_1_2026-27_*.zip",
    )
    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(qo_zip) as archive:
        qo_summary = read_json_member(
            archive,
            "qo_amount_completion_summary.json",
        )
        qo_rows = read_csv_member(
            archive,
            "qo_exact_amounts_completed_64.csv",
        )

    with zipfile.ZipFile(eligibility_zip) as archive:
        eligibility_summary = read_json_member(
            archive,
            "rfa_qo_rebuild_summary.json",
        )
        eligible_rows = read_csv_member(
            archive,
            "rfa_qo_structurally_eligible.csv",
        )

    with zipfile.ZipFile(branch_zip) as archive:
        branch_rows = read_csv_member(
            archive,
            "branch_reconstruction_all_players.csv",
        )

    with zipfile.ZipFile(scenario_zip) as archive:
        scenario_summary = read_json_member(
            archive,
            "recommended_scenario_summary.json",
        )
        team_rows = read_csv_member(
            archive,
            "team_counts_recommended_scenario.csv",
        )

    if len(qo_rows) != EXPECTED_ELIGIBLE:
        raise RuntimeError(f"Expected 64 exact QO rows, got {len(qo_rows)}.")
    if len(eligible_rows) != EXPECTED_ELIGIBLE:
        raise RuntimeError(f"Expected 64 eligible rows, got {len(eligible_rows)}.")

    qo_by_id = {pid(row.get("player_id")): row for row in qo_rows}
    eligible_by_id = {pid(row.get("player_id")): row for row in eligible_rows}

    if set(qo_by_id) != set(eligible_by_id):
        raise RuntimeError(
            "Exact-QO and structurally-eligible player ID sets do not match."
        )

    branch_by_id = {
        pid(row.get("player_id")): row
        for row in branch_rows
    }
    team_count_map = {
        team(row.get("team_abbreviation")): int(
            float(clean(row.get("recommended_scenario_roster_count")) or 0)
        )
        for row in team_rows
    }

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before QO issuance decision preview.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    controlled_teams = controlled_teams_from_state(checkpoint, state)
    players_raw = getattr(state, "players", {}) or {}
    players = {pid(key): value for key, value in players_raw.items()}

    decision_rows: list[dict[str, Any]] = []
    owner_issues: list[dict[str, Any]] = []
    missing_market: list[dict[str, Any]] = []

    print("=" * 128, flush=True)
    print("2026 QO ISSUANCE DECISION PREVIEW V1", flush=True)
    print("=" * 128, flush=True)
    print("Structurally eligible players:     64", flush=True)
    print("Exact QO amounts:                  64/64", flush=True)
    print(f"Controlled teams:                  {','.join(sorted(controlled_teams)) or '<none>'}", flush=True)
    print("QO issuance:                       NOT PERFORMED", flush=True)
    print("RFA status application:            NOT PERFORMED", flush=True)
    print("", flush=True)

    for index, player_id in enumerate(
        sorted(qo_by_id, key=lambda value: clean(qo_by_id[value].get("player_name")).lower()),
        start=1,
    ):
        qo = qo_by_id[player_id]
        eligible = eligible_by_id[player_id]
        player_name = clean(qo.get("player_name"))

        branch = branch_by_id.get(player_id, {})
        prior_team = team(branch.get("reconstructed_branch_owner"))

        if prior_team not in TEAM_CODES:
            owner_issues.append({
                "player_id": player_id,
                "player_name": player_name,
                "reconstructed_branch_owner": prior_team,
            })

        qo_amount = finite(qo.get("exact_qo_base_compensation"))
        if qo_amount is None or qo_amount <= 0:
            raise RuntimeError(f"Invalid exact QO amount for {player_name}.")

        player = players.get(player_id)
        features = (
            player_features(player)
            if player is not None
            else {
                "overall": None,
                "potential": None,
                "age": None,
                "position": "",
                "years_of_service": None,
            }
        )

        market_reference = None
        market_source = ""
        market_error = ""

        if player is not None:
            market_reference, market_source, market_error = (
                try_canonical_market_reference(player, qo_amount)
            )

        if market_reference is None:
            market_reference = fallback_market_reference(
                features["overall"],
                features["potential"],
                features["age"],
            )
            if market_reference is not None:
                market_source = "transparent_rating_fallback"

        if market_reference is None:
            missing_market.append({
                "player_id": player_id,
                "player_name": player_name,
                "prior_team": prior_team,
                "playerstate_present": player is not None,
            })
            score_data = {
                "market_to_qo_ratio": None,
                "retention_optionality_adjustment": None,
                "upside_adjustment": None,
                "age_risk_adjustment": None,
                "roster_adjustment": None,
                "absolute_qo_risk_adjustment": None,
                "decision_score": None,
                "recommendation": "manual_input_required",
                "confidence": "low",
            }
        else:
            score_data = qo_decision_score(
                market_reference=market_reference,
                qo_amount=qo_amount,
                overall=features["overall"],
                potential=features["potential"],
                age=features["age"],
                team_roster_count=int(team_count_map.get(prior_team, 0)),
            )

        model_recommendation = score_data["recommendation"]
        user_controlled = prior_team in controlled_teams

        if user_controlled:
            final_recommendation = "user_decision_required"
        else:
            final_recommendation = model_recommendation

        reason = (
            f"market/QO={score_data['market_to_qo_ratio']:.3f}; "
            f"rights_optionality={score_data['retention_optionality_adjustment']:+.3f}; "
            f"upside={score_data['upside_adjustment']:+.3f}; "
            f"age={score_data['age_risk_adjustment']:+.3f}; "
            f"roster={score_data['roster_adjustment']:+.3f}; "
            f"absolute_QO_risk={score_data['absolute_qo_risk_adjustment']:+.3f}; "
            f"score={score_data['decision_score']:.3f}"
            if score_data["decision_score"] is not None
            else "Market reference unavailable."
        )

        decision_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": prior_team,
            "controlled_team": user_controlled,
            "eligibility_path": clean(eligible.get("eligibility_path")),
            "formula_family": clean(qo.get("formula_family")),
            "exact_qo_amount": qo_amount,
            "market_reference": market_reference,
            "market_reference_source": market_source,
            "market_reference_error": market_error,
            "market_to_qo_ratio": score_data["market_to_qo_ratio"],
            "overall_rating": features["overall"],
            "potential_rating": features["potential"],
            "age": features["age"],
            "position": features["position"],
            "team_roster_count_before_qo": int(team_count_map.get(prior_team, 0)),
            "retention_optionality_adjustment": score_data["retention_optionality_adjustment"],
            "upside_adjustment": score_data["upside_adjustment"],
            "age_risk_adjustment": score_data["age_risk_adjustment"],
            "roster_adjustment": score_data["roster_adjustment"],
            "absolute_qo_risk_adjustment": score_data["absolute_qo_risk_adjustment"],
            "decision_score": score_data["decision_score"],
            "model_recommendation": model_recommendation,
            "recommendation": final_recommendation,
            "confidence": score_data["confidence"],
            "reason": reason,
            "qo_tender_applied": False,
            "rfa_status_applied": False,
            "real_world_qo_issuance_used": False,
            "cap_hold_opportunity_cost_fully_modeled": False,
            "state_mutation_applied": False,
        })

        print(
            f"[{index:02d}/64] {player_name} | {prior_team} | "
            f"QO ${qo_amount:,.0f} | market "
            f"{('$' + format(market_reference, ',.0f')) if market_reference is not None else '<missing>'} | "
            f"{final_recommendation}",
            flush=True,
        )

    user_rows = [
        row for row in decision_rows
        if row["recommendation"] == "user_decision_required"
    ]
    automatic_rows = [
        row for row in decision_rows
        if row["recommendation"] in {"issue_qo", "do_not_issue_qo"}
    ]
    manual_rows = [
        row for row in decision_rows
        if row["recommendation"] == "manual_input_required"
    ]

    recommendation_counts = Counter(row["recommendation"] for row in decision_rows)
    model_counts = Counter(row["model_recommendation"] for row in decision_rows)

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
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict QO issuance preview checks...", flush=True)

    check(
        "upstream_qo_amount_completion_passed",
        bool(qo_summary.get("passed"))
        and int(qo_summary.get("completed_exact_qo_count", -1)) == 64,
        "V1.0.4 completed 64/64 exact QO amounts.",
    )
    check(
        "upstream_structural_eligibility_passed",
        bool(eligibility_summary.get("passed"))
        and int(eligibility_summary.get("structurally_eligible_if_qo_issued_count", -1)) == 64,
        "64 structurally eligible players.",
    )
    check(
        "recommended_market_scenario_passed",
        bool(scenario_summary.get("passed"))
        and int(scenario_summary.get("recommended_final_market_count", -1)) == EXPECTED_FINAL_MARKET,
        "226-player recommended market scenario.",
    )
    check(
        "exact_64_decision_rows",
        len(decision_rows) == EXPECTED_ELIGIBLE
        and len({row["player_id"] for row in decision_rows}) == EXPECTED_ELIGIBLE,
        f"rows={len(decision_rows)}",
    )
    check(
        "all_64_have_proven_prior_team",
        not owner_issues
        and all(row["prior_team"] in TEAM_CODES for row in decision_rows),
        f"owner_issues={len(owner_issues)}",
    )
    check(
        "controlled_team_is_chicago",
        controlled_teams == {EXPECTED_CONTROLLED_TEAM},
        repr(sorted(controlled_teams)),
    )
    check(
        "exact_three_chicago_qo_user_decisions",
        len(user_rows) == 3
        and {row["player_name"] for row in user_rows} == EXPECTED_CHI_QO_NAMES,
        repr(sorted(row["player_name"] for row in user_rows)),
    )
    check(
        "all_cpu_rows_have_market_reference",
        not missing_market
        and all(row["market_reference"] is not None for row in decision_rows),
        f"missing_market={len(missing_market)}",
    )
    check(
        "all_non_user_rows_have_automatic_recommendation",
        not manual_rows
        and len(automatic_rows) == EXPECTED_ELIGIBLE - len(user_rows),
        (
            f"automatic={len(automatic_rows)} "
            f"user={len(user_rows)} manual={len(manual_rows)}"
        ),
    )
    check(
        "no_qo_tender_or_rfa_status_applied",
        all(
            not row["qo_tender_applied"]
            and not row["rfa_status_applied"]
            and not row["state_mutation_applied"]
            for row in decision_rows
        ),
        "Preview only.",
    )
    check(
        "no_real_world_qo_issuance_used",
        all(not row["real_world_qo_issuance_used"] for row in decision_rows),
        "Simulator recommendations only.",
    )
    check(
        "cap_hold_cost_is_explicitly_not_yet_full_model",
        all(not row["cap_hold_opportunity_cost_fully_modeled"] for row in decision_rows),
        "Prevents overstating decision completeness before cap-hold subsystem.",
        severity="diagnostic",
    )

    checkpoint_hash_after = sha256_file(checkpoint_path)
    state_digest_after = object_digest(state)

    check(
        "loaded_simulation_state_unchanged",
        state_digest_after == state_digest_before,
        state_digest_after,
    )
    check(
        "checkpoint_file_unchanged",
        checkpoint_hash_after
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_qo_issuance_decision_preview_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_qo_issue_board_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "qo_issuance_decision_board_64.csv",
            decision_rows,
        )
        write_csv(
            export / "qo_cpu_automatic_decisions.csv",
            automatic_rows,
        )
        write_csv(
            export / "qo_user_controlled_decisions.csv",
            user_rows,
        )
        write_csv(
            export / "qo_manual_input_required.csv",
            manual_rows,
        )
        write_csv(
            export / "qo_prior_team_owner_issues.csv",
            owner_issues,
        )
        write_csv(
            export / "qo_market_reference_issues.csv",
            missing_market,
        )
        write_csv(
            export / "qo_issuance_preview_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "decision_row_count": len(decision_rows),
            "automatic_decision_count": len(automatic_rows),
            "user_decision_count": len(user_rows),
            "manual_input_count": len(manual_rows),
            "recommendation_counts": dict(sorted(recommendation_counts.items())),
            "model_recommendation_counts_including_user_advisory": dict(
                sorted(model_counts.items())
            ),
            "controlled_teams": sorted(controlled_teams),
            "user_decision_players": [
                {
                    "player_name": row["player_name"],
                    "prior_team": row["prior_team"],
                    "exact_qo_amount": row["exact_qo_amount"],
                    "market_reference": row["market_reference"],
                    "market_to_qo_ratio": row["market_to_qo_ratio"],
                    "model_advisory": row["model_recommendation"],
                    "confidence": row["confidence"],
                }
                for row in user_rows
            ],
            "qo_tenders_applied": 0,
            "rfa_statuses_applied": 0,
            "real_world_qo_issuance_used": False,
            "cap_hold_opportunity_cost_fully_modeled": False,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": not failed,
            "failed_checks": failed,
            "next_slice": (
                "Review CPU recommendation distribution and the three Chicago "
                "QO choices. Before durable QO application, either integrate the "
                "cap-hold/opportunity-cost subsystem or explicitly keep QO issuance "
                "as a provisional decision state. Then apply CPU + user QO choices "
                "to a clone and derive final RFA/UFA statuses."
            ),
        }

        (export / "qo_issuance_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 QO ISSUANCE DECISION PREVIEW V1
=====================================

This is the first simulator-owned qualifying-offer issuance board.

Inputs:
- exact 226-player recommended simulated free-agent market
- exact 64 structurally RFA-eligible players
- exact 64/64 QO amounts
- reconstructed April-12 prior-team ownership
- canonical franchise free-agency market reference where available
- recommended-scenario team roster counts

Decision concept:
Issuing a QO preserves restricted-free-agent right-of-first-refusal.
It does NOT automatically sign the player. The principal downside is that
the player may accept the one-year guaranteed QO.

CPU scoring therefore considers:
- player market value / exact QO amount
- matching-rights optionality
- age and upside
- current reconstructed roster context
- absolute QO acceptance risk for unusually large QOs

User-control:
All QO decisions for user-controlled teams are suppressed and exported to
qo_user_controlled_decisions.csv. The CPU model advisory is still included.

IMPORTANT LIMIT:
Exact RFA cap-hold/opportunity-cost modeling is not yet integrated. The audit
records that explicitly. This preview should not be durably applied until that
financial state is either modeled or deliberately handled in the next slice.

Never used:
- real-world 2026 QO issued/not-issued decisions
- real-world RFA outcomes

No QO tender.
No RFA status application.
No checkpoint write.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "QO Issuance Decision Preview V1 failed: "
            + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 QO ISSUANCE DECISION PREVIEW V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Structurally eligible / exact QO: 64/64", flush=True)
    print(f"Automatic CPU decisions:           {len(automatic_rows)}", flush=True)
    print(f"Chicago user decisions:             {len(user_rows)}", flush=True)
    print(f"Manual inputs required:             {len(manual_rows)}", flush=True)
    print("Recommendation counts:", flush=True)
    for key, value in sorted(recommendation_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print("QO tenders applied:                  0", flush=True)
    print("RFA statuses applied:                0", flush=True)
    print("Cap-hold subsystem fully modeled:   NO", flush=True)
    print("Checkpoint write:        NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
