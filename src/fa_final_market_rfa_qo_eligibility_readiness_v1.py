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
from typing import Any, Mapping

VERSION = "fa-final-market-rfa-qo-eligibility-readiness-v1-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_MARKET = 226

ELIGIBLE = "eligible_if_qo_issued"
NOT_ELIGIBLE = "not_eligible"
NOT_APPLICABLE = "not_applicable"
MANUAL = "manual_review"

# Official NBA 2026 article: both "Issued" and "Not issued" regular-QO lists
# consist of players who were structurally eligible for restricted free agency.
# We import only eligibility, never the real-world QO issuance choice.
OFFICIAL_REGULAR_QO_ELIGIBLE_2026 = {
    "Jaylen Clark",
    "Mohamed Diawara",
    "Jalen Duren",
    "Tari Eason",
    "Spencer Jones",
    "Walker Kessler",
    "Bennedict Mathurin",
    "Quinten Post",
    "Peyton Watson",
    "Mark Williams",
    "Ochai Agbaji",
    "Ousmane Dieng",
    "Ariel Hukporti",
    "Keshad Johnson",
    "Pat Spencer",
    "Keaton Wallace",
    "Jalen Wilson",
}

# Official NBA two-way players listed as Restricted in 2026. This is used only
# as affirmative proof that the pre-split service/15-day predicates were met.
# The fact that a QO was actually issued remains audit-only and is never copied.
OFFICIAL_TWO_WAY_RFA_AFFIRMATIVE_2026 = {
    "Brooks Barnhizer",
    "Koby Brea",
    "Moussa Cisse",
    "Isaiah Crawford",
    "Hunter Dickinson",
    "Enrique Freeman",
    "Vladislav Goldin",
    "Harrison Ingram",
    "David Jones Garcia",
    "Chris Mañon",
    "Alijah Martin",
    "Daeqwon Plowden",
    "Jalen Slawson",
}

OFFICIAL_TWO_WAY_UNRESTRICTED_2026 = {
    "Trey Alexander",
    "Alex Antetokounmpo",
    "Patrick Baldwin Jr.",
    "MarJon Beauchamp",
    "Branden Carlson",
    "Sharife Cooper",
    "Tyson Etienne",
    "Elijah Harkless",
    "Trey Jemison III",
    "Curtis Jones",
    "Dillon Jones",
    "Yuki Kawamura",
    "Trevor Keels",
    "Christian Koloko",
    "E.J. Liddell",
    "Isaiah Livers",
    "Caleb Love",
    "Tyrese Martin",
    "Mac McClung",
    "Kevin McCullar Jr.",
    "Wendell Moore Jr.",
    "Josh Oduro",
    "Lachlan Olbrich",
    "Norchad Omier",
    "Antonio Reeves",
    "David Roddy",
    "Rayan Rupert",
    "Olivier Sarr",
    "Drew Timme",
    "John Tonje",
    "Oscar Tshiebwe",
    "TyTy Washington Jr.",
    "Nate Williams",
}

OFFICIAL_QO_SOURCE = (
    "https://www.nba.com/news/2026-free-agency-options-and-qualifying-offers"
)
OFFICIAL_RULES_SOURCE = "https://www.nba.com/news/free-agency-explained"


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def boolish(value: Any) -> bool:
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


def finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


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
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def find_latest_optional(root: Path, pattern: str) -> Path | None:
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return {}
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


def attr_or_mapping(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def player_yos(player: Any) -> int | None:
    raw = attr_or_mapping(
        player,
        (
            "years_of_service",
            "years_service",
            "yos",
            "service_years",
            "nba_years",
        ),
    )
    value = finite(raw)
    return int(value) if value is not None and value >= 0 else None


def player_games(player: Any) -> int | None:
    raw = attr_or_mapping(
        player,
        (
            "games_played",
            "gp",
            "regular_season_games_played",
            "games",
        ),
    )
    value = finite(raw)
    return int(value) if value is not None and value >= 0 else None


def player_draft_round(player: Any) -> int | None:
    raw = attr_or_mapping(
        player,
        (
            "draft_round",
            "draft_round_number",
            "round_drafted",
        ),
    )
    text = clean(raw).lower()
    if not text:
        return None
    if text in {"undrafted", "0", "na", "n/a", "none"}:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return None


def contract_type_for_player(state: Any, player_id: str) -> str:
    containers = [
        getattr(state, "contracts", None),
        getattr(state, "contract_states", None),
        getattr(state, "player_contracts", None),
    ]
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        obj = container.get(player_id)
        if obj is None:
            try:
                obj = container.get(int(player_id))
            except Exception:
                pass
        if obj is None:
            continue
        value = attr_or_mapping(
            obj,
            (
                "contract_type",
                "type",
                "deal_type",
                "latest_contract_type",
            ),
            "",
        )
        if clean(value):
            return clean(value)
    return ""


def normalize_old_disposition(value: str) -> str:
    value = clean(value).lower()
    if value in {ELIGIBLE, NOT_ELIGIBLE, NOT_APPLICABLE, MANUAL}:
        return value
    if "eligible_if_qo" in value or value == "eligible":
        return ELIGIBLE
    if "not_applicable" in value or "not applicable" in value:
        return NOT_APPLICABLE
    if "not_eligible" in value or "not eligible" in value:
        return NOT_ELIGIBLE
    if "manual" in value or "review" in value:
        return MANUAL
    return ""


def formula_family_from_path(
    path: str,
    draft_round: int | None,
    yos: int | None,
    contract_type: str,
) -> str:
    p = clean(path).lower()
    c = clean(contract_type).lower()
    if "two_way" in p or "two-way" in c or "two way" in c:
        return "two_way_finisher_qo"
    if (
        "rookie_scale" in p
        or (draft_round == 1 and yos is not None and yos >= 4)
    ):
        return "rookie_scale_qo"
    return "standard_veteran_qo"


def classify_fresh(
    *,
    player_id: str,
    player_name: str,
    player: Any,
    state: Any,
    automatic_decision: Mapping[str, str] | None,
    old_path: str,
) -> tuple[str, str, str, str]:
    """
    Returns disposition, eligibility_path, reason, evidence_tier.
    """
    yos = player_yos(player) if player is not None else None
    games = player_games(player) if player is not None else None
    draft_round = player_draft_round(player) if player is not None else None
    contract_type = contract_type_for_player(state, player_id)
    contract_lower = contract_type.lower()
    is_two_way = "two-way" in contract_lower or "two way" in contract_lower

    # Official affirmative structural proof. We do NOT import issued/not-issued.
    if player_name in OFFICIAL_REGULAR_QO_ELIGIBLE_2026:
        return (
            ELIGIBLE,
            "official_2026_regular_rfa_eligibility_proven",
            (
                "NBA's 2026 qualifying-offer article identifies this player as "
                "structurally eligible for restricted free agency. The actual "
                "issued/not-issued result is ignored."
            ),
            "official_nba_structural_eligibility",
        )

    if player_name in OFFICIAL_TWO_WAY_RFA_AFFIRMATIVE_2026:
        return (
            ELIGIBLE,
            "completing_two_way_contract_15_day_official_rfa_proven",
            (
                "NBA's official 2026 Two-Way RFA list affirmatively proves the "
                "pre-split service/15-day predicates. The real-world QO decision "
                "is not imported."
            ),
            "official_nba_affirmative_pre_split_condition_proof",
        )

    # Market additions from an actual simulator decision have strong structure.
    if automatic_decision:
        decision_category = clean(automatic_decision.get("decision_category"))
        recommendation = clean(automatic_decision.get("recommendation"))

        if recommendation == "waive":
            return (
                NOT_APPLICABLE,
                "waived_contract_enters_unrestricted_market",
                "Player entered the simulated market through a waiver decision, not contract expiration.",
                "simulator_decision_structure",
            )

        if decision_category == "player_option_decision" and recommendation == "decline":
            return (
                NOT_ELIGIBLE,
                "declined_player_option_forces_ufa",
                "NBA free-agency rules state that declining a Player Option produces unrestricted free agency.",
                "official_nba_rule_plus_simulator_decision",
            )

        if decision_category == "team_option_decision" and recommendation == "decline":
            if yos is not None and yos > 3:
                return (
                    NOT_ELIGIBLE,
                    "team_option_decline_veteran_over_three_yos",
                    "Veteran has more than three NBA seasons and is outside ordinary RFA eligibility.",
                    "local_service_time",
                )
            if yos is not None and yos <= 3:
                if draft_round == 1:
                    return (
                        NOT_ELIGIBLE,
                        "rookie_scale_option_decline_forces_ufa",
                        (
                            "First-round pick following a declined second/third-season "
                            "rookie-scale option is the explicit RFA exception and becomes UFA."
                        ),
                        "official_nba_rule_plus_local_draft_service",
                    )
                if is_two_way:
                    if games is not None and games >= 15:
                        return (
                            ELIGIBLE,
                            "completing_two_way_contract_15_day_gp_proven",
                            "At least 15 NBA games provides affirmative 15-day proof for the Two-Way condition.",
                            "local_games_service_evidence",
                        )
                    return (
                        MANUAL,
                        "two_way_15_day_evidence_required",
                        "Two-Way player has <=3 YOS but active/inactive-list 15-day evidence is not proven.",
                        "manual_pre_split_evidence_required",
                    )
                return (
                    ELIGIBLE,
                    "veteran_free_agent_three_or_fewer_yos",
                    "Non-first-round veteran free agent with three or fewer NBA seasons is RFA-eligible if a QO is issued.",
                    "official_nba_rule_plus_local_service",
                )
            return (
                MANUAL,
                "team_option_decline_service_or_draft_status_required",
                "Team-option decline requires service/draft evidence to distinguish RFA eligibility from the rookie-scale exception.",
                "manual_local_metadata_required",
            )

    # Initial market rows.
    if player_name == "Gabe McGlothan":
        return (
            NOT_APPLICABLE,
            "expired_ten_day_contract",
            "Player entered the offseason market after an expired 10-day contract; QO/RFA path is not applicable.",
            "verified_lifecycle_structure",
        )

    if player is None:
        return (
            MANUAL,
            "playerstate_missing_for_rfa_structure",
            "No PlayerState is available to prove service/draft predicates.",
            "manual_population_metadata_required",
        )

    if yos is not None and yos > 3:
        return (
            NOT_ELIGIBLE,
            "veteran_free_agent_over_three_yos",
            "Veteran free agent has more than three NBA seasons.",
            "local_service_time",
        )

    if yos is not None and yos <= 3:
        if is_two_way:
            if games is not None and games >= 15:
                return (
                    ELIGIBLE,
                    "completing_two_way_contract_15_day_gp_proven",
                    "At least 15 NBA games proves the Two-Way 15-day condition.",
                    "local_games_service_evidence",
                )
            return (
                MANUAL,
                "two_way_15_day_evidence_required",
                "Two-Way player has <=3 YOS but the active/inactive-list 15-day threshold is not proven.",
                "manual_pre_split_evidence_required",
            )
        return (
            ELIGIBLE,
            "veteran_free_agent_three_or_fewer_yos",
            "Veteran free agent with three or fewer NBA seasons is RFA-eligible if a QO is issued.",
            "official_nba_rule_plus_local_service",
        )

    return (
        MANUAL,
        "years_of_service_required",
        "Years-of-service evidence is unavailable.",
        "manual_local_metadata_required",
    )


def main() -> int:
    root = Path.cwd().resolve()

    scenario_zip = find_latest(
        root,
        "fa_chicago_recommended_final_market_rfa_input_v1_2026-27_*.zip",
    )
    clone_zip = find_latest(
        root,
        "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip",
    )
    old_rfa_zip = find_latest(
        root,
        "fa_corrected_rfa_qo_universe_v2_preview_2026-27_*.zip",
    )
    old_qo_zip = find_latest_optional(
        root,
        "fa_qo_amount_readiness_v1_2026-27_*.zip",
    )

    with zipfile.ZipFile(scenario_zip) as archive:
        scenario_summary = read_json_member(
            archive,
            "recommended_scenario_summary.json",
        )
        market_rows = read_csv_member(
            archive,
            "rfa_qo_rebuild_input_226.csv",
        )

    with zipfile.ZipFile(clone_zip) as archive:
        applied_rows = read_csv_member(
            archive,
            "automatic_decisions_applied_109.csv",
        )

    with zipfile.ZipFile(old_rfa_zip) as archive:
        old_rfa_rows = read_csv_member(
            archive,
            "corrected_rfa_qo_universe_all.csv",
        )

    old_qo_rows = []
    if old_qo_zip is not None:
        with zipfile.ZipFile(old_qo_zip) as archive:
            old_qo_rows = read_csv_member(
                archive,
                "qo_amount_readiness_all.csv",
                required=False,
            )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    state = checkpoint.simulation_state
    state_digest_before = object_digest(state)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before final-market RFA/QO rebuild.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    if not bool(scenario_summary.get("passed")):
        raise RuntimeError("Chicago recommended-market upstream preview did not pass.")
    if len(market_rows) != EXPECTED_MARKET:
        raise RuntimeError(
            f"Expected {EXPECTED_MARKET} market rows, got {len(market_rows)}."
        )

    players = getattr(state, "players", {}) or {}
    players_by_id = {pid(key): value for key, value in players.items()}

    old_rfa_by_id = {
        pid(row.get("player_id")): row
        for row in old_rfa_rows
    }
    old_qo_by_id = {
        pid(row.get("player_id")): row
        for row in old_qo_rows
    }
    applied_by_id = {
        pid(row.get("player_id")): row
        for row in applied_rows
        if boolish(row.get("entered_market"))
    }

    output_rows = []
    eligibility_sources = Counter()
    disposition_counts = Counter()

    for market in market_rows:
        player_id = pid(market.get("player_id"))
        player_name = clean(market.get("player_name"))
        player = players_by_id.get(player_id)

        prior = old_rfa_by_id.get(player_id, {})
        prior_disposition = normalize_old_disposition(
            prior.get("corrected_rfa_qo_disposition", "")
        )
        prior_path = clean(prior.get("corrected_rfa_qo_path"))

        # Carry prior evidence only when it was already conclusive.
        if prior_disposition and prior_disposition != MANUAL:
            disposition = prior_disposition
            path = prior_path
            reason = clean(prior.get("reason")) or (
                "Conclusive corrected-RFA evidence carried forward from V2."
            )
            evidence_tier = "corrected_rfa_v2_carry_forward"
        else:
            disposition, path, reason, evidence_tier = classify_fresh(
                player_id=player_id,
                player_name=player_name,
                player=player,
                state=state,
                automatic_decision=applied_by_id.get(player_id),
                old_path=prior_path,
            )

        yos = player_yos(player) if player is not None else None
        games = player_games(player) if player is not None else None
        draft_round = player_draft_round(player) if player is not None else None
        contract_type = contract_type_for_player(state, player_id)

        # QO amount readiness is kept separate from eligibility.
        old_amount = old_qo_by_id.get(player_id, {})
        amount_status = ""
        exact_qo = ""
        qo_formula = ""
        amount_reason = ""
        amount_missing_inputs = ""

        if disposition != ELIGIBLE:
            amount_status = "not_applicable_until_eligible"
            qo_formula = ""
            amount_reason = "QO amount is not evaluated for a non-eligible/manual row."
        elif old_amount:
            amount_status = clean(old_amount.get("amount_status"))
            exact_qo = clean(old_amount.get("exact_qo_base_compensation"))
            qo_formula = clean(old_amount.get("qo_formula"))
            amount_reason = clean(old_amount.get("reason"))
            amount_missing_inputs = clean(old_amount.get("missing_inputs"))
        else:
            qo_formula = formula_family_from_path(
                path,
                draft_round,
                yos,
                contract_type,
            )
            amount_status = "fresh_formula_inputs_required"
            amount_reason = (
                "Eligibility is proven, but this player was not in the old QO amount "
                "readiness universe. Exact 2026-27 formula inputs must be rebuilt."
            )
            amount_missing_inputs = "fresh_qo_amount_evidence"

        official_regular_eligible = (
            player_name in OFFICIAL_REGULAR_QO_ELIGIBLE_2026
        )
        official_two_way_restricted = (
            player_name in OFFICIAL_TWO_WAY_RFA_AFFIRMATIVE_2026
        )
        official_two_way_unrestricted = (
            player_name in OFFICIAL_TWO_WAY_UNRESTRICTED_2026
        )

        output_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "final_market_count_context": EXPECTED_MARKET,
            "eligibility_disposition": disposition,
            "eligibility_path": path,
            "eligibility_reason": reason,
            "eligibility_evidence_tier": evidence_tier,
            "years_of_service": yos,
            "games_played_local": games,
            "draft_round_local": draft_round,
            "contract_type_local": contract_type,
            "market_entry_source": clean(market.get("market_entry_source")),
            "automatic_market_decision_category": clean(
                applied_by_id.get(player_id, {}).get("decision_category")
            ),
            "automatic_market_recommendation": clean(
                applied_by_id.get(player_id, {}).get("recommendation")
            ),
            "prior_corrected_rfa_disposition": prior_disposition,
            "prior_corrected_rfa_path": prior_path,
            "official_2026_regular_qo_eligible_list_member_audit": official_regular_eligible,
            "official_2026_two_way_restricted_list_member_audit": official_two_way_restricted,
            "official_2026_two_way_unrestricted_list_member_audit": official_two_way_unrestricted,
            "real_world_qo_issued_not_issued_imported": False,
            "qo_formula_family": qo_formula,
            "qo_amount_status": amount_status,
            "exact_qo_base_compensation": exact_qo,
            "qo_amount_missing_inputs": amount_missing_inputs,
            "qo_amount_reason": amount_reason,
            "qualifying_offer_issued": False,
            "rfa_status_applied": False,
            "state_mutation_applied": False,
        })

        disposition_counts[disposition] += 1
        eligibility_sources[evidence_tier] += 1

    eligible_rows = [
        row for row in output_rows
        if row["eligibility_disposition"] == ELIGIBLE
    ]
    manual_rows = [
        row for row in output_rows
        if row["eligibility_disposition"] == MANUAL
    ]
    exact_amount_rows = [
        row for row in eligible_rows
        if row["qo_amount_status"] == "exact_base_compensation_ready"
        and clean(row["exact_qo_base_compensation"])
    ]
    amount_manual_rows = [
        row for row in eligible_rows
        if row["qo_amount_status"] != "exact_base_compensation_ready"
        or not clean(row["exact_qo_base_compensation"])
    ]

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
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("=" * 128, flush=True)
    print("2026 FINAL-MARKET RFA/QO ELIGIBILITY + READINESS V1", flush=True)
    print("=" * 128, flush=True)
    print(f"Final simulated market:       {len(output_rows)}", flush=True)
    print("Real-world QO decisions used: NO", flush=True)
    print("State/checkpoint mutation:    NONE", flush=True)
    print("", flush=True)
    print("Running strict RFA/QO rebuild checks...", flush=True)

    check(
        "upstream_recommended_market_passed",
        bool(scenario_summary.get("passed")),
        "Recommended 226-player market preview passed.",
    )
    check(
        "exact_226_final_market_rows",
        len(output_rows) == EXPECTED_MARKET
        and len({row["player_id"] for row in output_rows}) == EXPECTED_MARKET,
        f"rows={len(output_rows)}",
    )
    check(
        "every_market_row_has_supported_disposition",
        all(
            row["eligibility_disposition"]
            in {ELIGIBLE, NOT_ELIGIBLE, NOT_APPLICABLE, MANUAL}
            for row in output_rows
        ),
        "No unsupported disposition.",
    )
    check(
        "no_real_world_qo_issuance_imported",
        all(
            not row["real_world_qo_issued_not_issued_imported"]
            and not row["qualifying_offer_issued"]
            and not row["rfa_status_applied"]
            for row in output_rows
        ),
        "Official 2026 lists are structural/audit evidence only.",
    )
    check(
        "declined_player_options_are_not_rfa",
        all(
            row["eligibility_disposition"] == NOT_ELIGIBLE
            for row in output_rows
            if row["automatic_market_decision_category"] == "player_option_decision"
            and row["automatic_market_recommendation"] == "decline"
        ),
        "NBA rule: declined Player Option -> unrestricted free agent.",
    )
    check(
        "waived_players_do_not_enter_qo_path",
        all(
            row["eligibility_disposition"] == NOT_APPLICABLE
            for row in output_rows
            if row["automatic_market_recommendation"] == "waive"
        ),
        "Waiver market entries are not contract-expiration RFA paths.",
    )
    check(
        "qo_amounts_separated_from_eligibility",
        all(
            row["qo_amount_status"] == "not_applicable_until_eligible"
            for row in output_rows
            if row["eligibility_disposition"] != ELIGIBLE
        ),
        "No QO amount is fabricated for unresolved/non-eligible rows.",
    )
    check(
        "checkpoint_file_unchanged",
        sha256_file(checkpoint_path)
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        sha256_file(checkpoint_path),
    )
    check(
        "loaded_simulation_state_unchanged",
        object_digest(state) == state_digest_before,
        object_digest(state),
    )
    check(
        "eligibility_manual_count_is_diagnostic",
        True,
        f"manual={len(manual_rows)}",
        severity="diagnostic",
    )
    check(
        "exact_qo_amount_ready_count_is_diagnostic",
        True,
        f"exact_amount={len(exact_amount_rows)}/{len(eligible_rows)} eligible",
        severity="diagnostic",
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed:
        raise RuntimeError(
            "Final-Market RFA/QO Eligibility + Readiness V1 failed: "
            + ", ".join(failed)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_final_market_rfa_qo_eligibility_readiness_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_rfa_qo_226_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "rfa_qo_eligibility_readiness_all_226.csv", output_rows)
        write_csv(export / "rfa_qo_structurally_eligible.csv", eligible_rows)
        write_csv(export / "rfa_qo_manual_eligibility_review.csv", manual_rows)
        write_csv(export / "rfa_qo_exact_amount_ready.csv", exact_amount_rows)
        write_csv(export / "rfa_qo_amount_inputs_required.csv", amount_manual_rows)
        write_csv(export / "rfa_qo_rebuild_checks.csv", checks)

        summary = {
            "version": VERSION,
            "final_market_count": len(output_rows),
            "eligibility_disposition_counts": dict(sorted(disposition_counts.items())),
            "eligibility_evidence_tier_counts": dict(sorted(eligibility_sources.items())),
            "structurally_eligible_if_qo_issued_count": len(eligible_rows),
            "eligibility_manual_review_count": len(manual_rows),
            "exact_qo_amount_ready_count": len(exact_amount_rows),
            "qo_amount_inputs_required_count": len(amount_manual_rows),
            "old_qo_amount_audit_available": old_qo_zip is not None,
            "official_regular_qo_structural_list_size": len(
                OFFICIAL_REGULAR_QO_ELIGIBLE_2026
            ),
            "official_two_way_affirmative_list_size": len(
                OFFICIAL_TWO_WAY_RFA_AFFIRMATIVE_2026
            ),
            "official_rule_source": OFFICIAL_RULES_SOURCE,
            "official_qo_source": OFFICIAL_QO_SOURCE,
            "real_world_qo_issuance_imported": False,
            "qualifying_offers_issued": 0,
            "rfa_statuses_applied": 0,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": True,
            "next_slice": (
                "Resolve only rfa_qo_manual_eligibility_review.csv using pre-split "
                "Two-Way 15-day/service/draft evidence. In parallel, rebuild exact "
                "QO formula inputs only for structurally eligible rows in "
                "rfa_qo_amount_inputs_required.csv. Do not issue QOs yet."
            ),
        }

        (export / "rfa_qo_rebuild_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 FINAL-MARKET RFA/QO ELIGIBILITY + READINESS V1
====================================================

Input
-----
The exact 226-player recommended simulated market:
- Leonard Miller option exercised
- Mouhamadou Gueye option declined
- user choices remain scenario-only, not durably committed

Eligibility policy
------------------
Conclusive old corrected-RFA evidence is carried forward.
Old manual rows are re-evaluated.

Fresh rows are resolved using:
- official NBA RFA structural rules
- local years of service
- local draft round when available
- simulator market-entry mechanism
- affirmative official NBA Two-Way RFA status only as proof of pre-split
  15-day/service predicates

Never imported:
- whether a real-world QO was issued
- whether a real-world QO was withheld
- resulting real-world RFA/UFA choice as the simulator's QO decision

Important structural rules
--------------------------
- veteran FA <=3 YOS can be RFA if QO issued
- >3 YOS ordinary veteran FA is not RFA-eligible
- first-rounder after declined 2nd/3rd-year rookie-scale option is UFA
- declined Player Option produces UFA
- Two-Way finisher requires <=3 YOS and 15+ active/inactive-list days
- QO amount readiness is tracked separately from eligibility

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 FINAL-MARKET RFA/QO ELIGIBILITY + READINESS V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Final market:                    {len(output_rows)}", flush=True)
    print("Eligibility dispositions:", flush=True)
    for key, value in sorted(disposition_counts.items()):
        print(f"  {key}: {value}", flush=True)
    print(f"Structurally eligible if QO:     {len(eligible_rows)}", flush=True)
    print(f"Eligibility manual review:       {len(manual_rows)}", flush=True)
    print(f"Exact QO amounts ready:          {len(exact_amount_rows)}/{len(eligible_rows)}", flush=True)
    print(f"QO amount inputs still required: {len(amount_manual_rows)}", flush=True)
    print("Real-world QO issuance used:     NO", flush=True)
    print("Qualifying offers issued:         0", flush=True)
    print("RFA statuses applied:             0", flush=True)
    print("Checkpoint write:     NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
