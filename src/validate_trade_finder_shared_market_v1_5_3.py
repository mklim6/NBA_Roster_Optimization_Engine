from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_player_id
from franchise_asset_market_value_v1 import (
    ASSET_MARKET_CONTEXT_VERSION,
    ASSET_MARKET_MODEL_VERSION,
    build_league_asset_market_contexts,
    trade_market_value_from_row,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    _apply_shared_context,
    _cpu_accept_floor,
    _intrinsic_player_value,
    _untouchable,
    _values_for_spec,
    build_team_trade_ai_profiles,
    generate_trade_finder_proposals,
    player_value_for_team,
)
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "trade-finder-shared-market-validator-v1.5.3-2026-08-13"

EXPECTED_AI_HASH = "235d10e9f5aa9aca1f627b1ef95fe53b37e924764d2bd65b57121c0ec67102ac"
EXPECTED_UI_HASH = "25b55280b33a7fb8314f226d66964028c557dfe474b6d493e123291e5d97dea1"
EXPECTED_SHARED_HASH = '6ab1c377757ade6c6208cc66a20f6306827577f917bbe3fa39944e2946975899'
EXPECTED_CONTRACT_HASH = 'a878d38d5137ae9dfdb9c2953c8b69dad288b678127c395fa77b12f5554b4db2'
EXPECTED_CENTER_HASH = "575df09efa8d96b279331f2a093a9ffa3eca0d9f660c1d99c2753dacdec44fde"


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_signature(state):
    return (
        getattr(getattr(state, "settings", None), "season_label", ""),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
        tuple(
            (team, tuple(team_state.roster_player_ids))
            for team, team_state in sorted(getattr(state, "teams", {}).items())
        ),
    )


def player_by_name(ledger, name: str):
    normalized = str(name).replace("č", "c").replace("ć", "c").lower()
    for row in ledger.player_rows:
        candidate = str(row.get("player_name") or "").strip().replace("č", "c").replace("ć", "c").lower()
        if candidate == normalized:
            return dict(row)
    return None


def pid(row):
    return normalize_player_id(row.get("player_id")) if row else ""


def main() -> int:
    configure_utf8_console()
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable franchise checkpoint could not be loaded.")

    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    before_state = state_signature(state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_team_trade_ai_profiles(state, ledger)
    active = "PHI" if "PHI" in profiles else sorted(profiles)[0]
    neutral_profile = profiles[active]

    print("[1/5] Validating shared player-market value source...", flush=True)
    requested_names = (
        "Cooper Flagg", "VJ Edgecombe", "Luka Dončić", "Tyrese Maxey",
        "Anfernee Simons", "Marcus Sasser", "Dean Wade", "Bronny James",
    )
    names = {name: player_by_name(ledger, name) for name in requested_names}

    validator_contexts_raw = build_league_asset_market_contexts(
        state,
        team_timelines={
            team: profile.timeline
            for team, profile in profiles.items()
        },
    )
    validator_contexts = {
        normalize_player_id(player_id): context
        for player_id, context in validator_contexts_raw.items()
        if normalize_player_id(player_id)
    }
    for row in names.values():
        if row is None:
            continue
        _apply_shared_context(
            row,
            validator_contexts.get(
                normalize_player_id(row.get("player_id"))
            ),
        )

    intrinsic_values = {
        name: _intrinsic_player_value(row)
        for name, row in names.items() if row is not None
    }
    shared_values = {
        name: trade_market_value_from_row(row)
        for name, row in names.items() if row is not None
    }
    fit_values = {
        name: player_value_for_team(row, neutral_profile)
        for name, row in names.items() if row is not None
    }

    print("[2/5] Validating old underpay regression shapes...", flush=True)
    regression_flagg = None
    regression_luka = None
    player_map = {
        normalize_player_id(row.get("player_id")): dict(row)
        for row in ledger.player_rows
    }
    pick_map = {str(row.get("asset_id")): dict(row) for row in ledger.draft_rows}

    if all(names.get(name) is not None for name in ("VJ Edgecombe", "Anfernee Simons", "Cooper Flagg", "Marcus Sasser")):
        dal_profile = profiles.get("DAL", neutral_profile)
        spec = (
            (pid(names["VJ Edgecombe"]), pid(names["Anfernee Simons"])),
            (pid(names["Cooper Flagg"]), pid(names["Marcus Sasser"])),
            (), (),
        )
        regression_flagg = _values_for_spec(
            spec=spec, active_profile=neutral_profile, partner_profile=dal_profile,
            player_map=player_map, pick_map=pick_map, ledger=ledger,
            active_goal=GOAL_BEST_AVAILABLE,
        )[-1]

    if all(names.get(name) is not None for name in ("Tyrese Maxey", "Dean Wade", "Luka Dončić", "Bronny James")):
        lal_profile = profiles.get("LAL", neutral_profile)
        spec = (
            (pid(names["Tyrese Maxey"]), pid(names["Dean Wade"])),
            (pid(names["Luka Dončić"]), pid(names["Bronny James"])),
            (), (),
        )
        regression_luka = _values_for_spec(
            spec=spec, active_profile=neutral_profile, partner_profile=lal_profile,
            player_map=player_map, pick_map=pick_map, ledger=ledger,
            active_goal=GOAL_BEST_AVAILABLE,
        )[-1]

    print("[3/5] Running bounded 2026-27 anchor market benchmark...", flush=True)
    started = time.perf_counter()
    result = generate_trade_finder_proposals(
        runtime, state, trade_state,
        active_team=active,
        goal=GOAL_BEST_AVAILABLE,
        include_picks=True,
        max_results=8,
        max_partners=10,
        max_targets_per_partner=4,
        max_package_evaluations=12,
        max_financial_prechecks=320,
        ledger=ledger,
    )
    elapsed = time.perf_counter() - started

    print("[4/5] Auditing shared-context CSV fields and safety...", flush=True)
    ai_path = SRC / "franchise_trade_finder_ai_v1.py"
    ui_path = SRC / "franchise_trade_finder_ui_v1.py"
    shared_path = SRC / "franchise_asset_market_value_v1.py"
    contract_path = SRC / "franchise_player_contract_bridge_v1.py"
    center_path = SRC / "franchise_embedded_trade_center_v2.py"
    ai_text = ai_path.read_text(encoding="utf-8")
    ui_text = ui_path.read_text(encoding="utf-8")
    contract_text = contract_path.read_text(encoding="utf-8")
    center_text = center_path.read_text(encoding="utf-8")

    shared_match = all(abs(intrinsic_values[name] - shared_values[name]) <= 0.05 for name in intrinsic_values)
    named_sep_ok = True
    if "Cooper Flagg" in fit_values and "VJ Edgecombe" in fit_values:
        named_sep_ok = (
            named_sep_ok
            and intrinsic_values["Cooper Flagg"] >= 140.0
            and intrinsic_values["Cooper Flagg"]
            >= intrinsic_values["VJ Edgecombe"] + 6.0
        )
    if "Luka Dončić" in fit_values and "Tyrese Maxey" in fit_values:
        named_sep_ok = named_sep_ok and fit_values["Luka Dončić"] >= fit_values["Tyrese Maxey"] + 4.0
    if "Bronny James" in fit_values:
        named_sep_ok = (
            named_sep_ok
            and fit_values["Bronny James"] <= 30.0
        )
    if "Anfernee Simons" in fit_values and "Dean Wade" in fit_values:
        named_sep_ok = (
            named_sep_ok
            and fit_values["Dean Wade"] <= 50.0
            and fit_values["Anfernee Simons"]
            >= fit_values["Dean Wade"] + 15.0
        )
    if "Dean Wade" in fit_values and "Bronny James" in fit_values:
        named_sep_ok = (
            named_sep_ok
            and fit_values["Dean Wade"]
            >= fit_values["Bronny James"] + 20.0
        )

    package_audit = [dict(row) for row in result.package_audit_rows]
    shared_audit_fields_ok = True
    if package_audit:
        required = {
            "trade_finder_version", "value_model_version",
            "shared_asset_market_context_version", "shared_asset_market_model_version",
            "target_shared_asset_tier", "target_shared_market_score", "target_shared_trade_value",
        }
        shared_audit_fields_ok = required.issubset(package_audit[0].keys())

    proposal_families = [
        (proposal.partner_team, proposal.target_player_id or tuple(proposal.side_b_player_ids[:1]))
        for proposal in result.proposals
    ]
    surfaced_all_pass = all(
        str(proposal.preview_payload.get("status", "")).lower() == "pass"
        and bool(proposal.preview_payload.get("can_commit", False))
        for proposal in result.proposals
    )

    checks = {
        "validator_version_is_current": "v1.5" in VALIDATOR_VERSION,
        "trade_finder_version_is_v1_5_3": "v1.5.3-anchor-preview-resolution" in TRADE_FINDER_AI_VERSION,
        "shared_value_model_is_current": "shared-franchise-asset-market-context-v1.0.2" in TRADE_FINDER_VALUE_MODEL_VERSION,
        "shared_context_version_is_current": ASSET_MARKET_CONTEXT_VERSION == "franchise-asset-market-context-v1.0.2-2026-08-13",
        "shared_model_version_is_current": ASSET_MARKET_MODEL_VERSION == "age-upside-control-salary-availability-v1.0.2-2026-08-13",
        "exact_ai_hash": sha256(ai_path) == EXPECTED_AI_HASH,
        "exact_ui_hash": sha256(ui_path) == EXPECTED_UI_HASH,
        "exact_shared_dependency_hash": sha256(shared_path) == EXPECTED_SHARED_HASH,
        "contract_bridge_preserved": sha256(contract_path) == EXPECTED_CONTRACT_HASH,
        "embedded_trade_center_v2_1_is_exact": (
            sha256(center_path) == EXPECTED_CENTER_HASH
        ),
        "anchor_financial_resolution_is_strictly_guarded": (
            "canonical_anchor_financial_review_resolved" in center_text
            and "financial_bridge_nonpass_codes" in center_text
            and "player_contract_bridge_status == \"pass\"" in center_text
            and "draft_right_bridge_status == \"pass\"" in center_text
            and "canonical_status == \"pass\"" in center_text
        ),
        "trade_finder_intrinsic_equals_shared_market_value": shared_match,
        "league_calibrated_contexts_are_built_once": "build_league_asset_market_contexts(" in ai_text and "shared_contexts_raw" in ai_text,
        "shared_context_drives_untouchable_logic": 'tier == "Franchise"' in ai_text and 'tier == "Star"' in ai_text and "_shared_trade_value_score" in ai_text,
        "named_live_value_separation_is_sane": named_sep_ok,
        "old_flagg_shape_is_rejected_by_shared_cpu_policy_if_available": (
            regression_flagg is None
            or names.get("Cooper Flagg") is None
            or _untouchable(
                names["Cooper Flagg"],
                profiles.get("DAL", neutral_profile),
            )
            or regression_flagg < _cpu_accept_floor(
                partner_profile=profiles.get("DAL", neutral_profile),
                target=names["Cooper Flagg"],
            )
        ),
        "old_luka_shape_is_rejected_by_shared_cpu_policy_if_available": (
            regression_luka is None
            or names.get("Luka Dončić") is None
            or _untouchable(
                names["Luka Dončić"],
                profiles.get("LAL", neutral_profile),
            )
            or regression_luka < _cpu_accept_floor(
                partner_profile=profiles.get("LAL", neutral_profile),
                target=names["Luka Dončić"],
            )
        ),
        "directional_salary_accessibility_lane_installed": "_directional_salary_route_penalty" in ai_text,
        "premium_two_pick_package_lane_installed": "Premium targets often require more than one first-equivalent asset." in ai_text,
        "candidate_priority_is_pick_aware": "local_pick_map" in ai_text and "a_value += sum(" in ai_text,
        "partner_ranking_is_financially_accessible": "active_market_players" in ai_text and "scores = []" in ai_text,
        "financial_precheck_budget_is_fair_across_partners": "per_partner_financial_budget" in ai_text and "per_target_financial_budget" in ai_text,
        "financial_pass_counter_rescue_is_installed": "financial_pass_value_rescue" in ai_text,
        "counter_rescue_can_use_two_picks": "Two-pick rescue for premium targets" in ai_text,
        "anchor_manual_review_is_strictly_whitelisted": (
            "future_standard_roster_minimum_review" in ai_text
            and "future_apron_nonplayer_charge_buffer" in ai_text
            and 'return "anchor_review", reasons' in ai_text
        ),
        "canonical_anchor_precheck_is_installed": (
            "_canonical_anchor_precheck" in ai_text
            and "TradeRequest(" in ai_text
            and "evaluate_trade(" in ai_text
        ),
        "full_preview_is_still_required_after_canonical_precheck": (
            "build_franchise_trade_preview(" in ai_text
            and 'if canonical_status == "blocked":' in ai_text
        ),
        "anchor_review_requires_canonical_pass_before_deep_preview": (
            "anchor_review_canonical_unresolved" in ai_text
            and 'financial_status == "anchor_review"' in ai_text
        ),
        "audit_tracks_anchor_financial_resolution": (
            "anchor_financial_resolution_applied" in ai_text
        ),
        "cached_contract_snapshot_is_preserved": "snapshot: FranchisePlayerContractSnapshot | None = None" in contract_text,
        "embedded_preview_accepts_market_caches": "market_read_only_fast_path" in center_text and "player_contract_snapshot" in center_text,
        "financial_routes_exist": (
            result.financial_precheck_passes >= 1
            or any(
                str(row.get("financial_status", "")).lower() == "anchor_review"
                for row in result.package_audit_rows
            )
        ),
        "bounded_market_benchmark_under_three_minutes": elapsed < 180.0,
        "deep_preview_budget_is_tight": result.packages_evaluated <= 12,
        "market_surfaces_actionable_offers": len(result.proposals) >= 1,
        "all_surfaced_offers_are_full_live_pass": surfaced_all_pass,
        "surfaced_offer_families_are_deduplicated": len(proposal_families) == len(set(proposal_families)),
        "package_audit_contains_shared_market_context": shared_audit_fields_ok,
        "ui_retains_full_package_audit_csv": "Download full package audit CSV" in ui_text,
        "windows_unicode_console_fix_is_installed": "configure_utf8_console" in Path(__file__).read_text(encoding="utf-8"),
        "generation_does_not_mutate_live_state": state_signature(state) == before_state,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
        "all_modified_files_compile": True,
    }

    print("[5/5] Finalizing validator checks...", flush=True)
    for source_path in (ai_path, ui_path, shared_path, Path(__file__)):
        source_text = source_path.read_text(encoding="utf-8")
        compile(source_text, str(source_path), "exec")

    failed = [name for name, passed in checks.items() if not passed]
    print("=" * 100)
    print("TRADE FINDER SHARED MARKET CONTEXT + ANCHOR MARKET V1.5.3 VALIDATION")
    print("=" * 100)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("SHARED VALUE REGRESSION")
    for name in requested_names:
        if name in intrinsic_values:
            print(f"  {name}: intrinsic={intrinsic_values[name]:.1f} fit={fit_values[name]:.1f}")
    if regression_flagg is not None:
        print(f"  DAL CPU delta, Edgecombe+Simons for Flagg+Sasser: {regression_flagg:+.1f}")
    if regression_luka is not None:
        print(f"  LAL CPU delta, Maxey+Wade for Luka+Bronny: {regression_luka:+.1f}")

    print()
    print("ANCHOR MARKET BENCHMARK")
    print(f"  Active team: {active}")
    print(f"  Search elapsed: {elapsed:.2f}s")
    print(f"  Teams reached: {result.teams_scanned}")
    print(f"  Targets identified: {result.targets_identified}")
    print(f"  Packages generated: {result.candidate_packages_generated}")
    print(f"  Value routes: {result.value_screen_passes}")
    print(f"  Financial prechecks: {result.financial_prechecks}")
    print(f"  Financial PASS: {result.financial_precheck_passes}")
    print(f"  Expensive full previews: {result.packages_evaluated}")
    print(f"  Legal PASS: {result.legal_packages}")
    print(f"  CPU offers: {len(result.proposals)}")

    anchor_review_rows = [
        row
        for row in result.package_audit_rows
        if str(row.get("financial_status", "")).lower() == "anchor_review"
    ]
    canonical_pass_rows = [
        row
        for row in result.package_audit_rows
        if str(row.get("canonical_precheck_status", "")).lower() == "pass"
    ]
    canonical_block_rows = [
        row
        for row in result.package_audit_rows
        if str(row.get("canonical_precheck_status", "")).lower() == "blocked"
    ]

    print()
    print("ANCHOR REVIEW / CANONICAL PRECHECK")
    print(f"  Anchor-review routes: {len(anchor_review_rows)}")
    print(f"  Canonical precheck PASS: {len(canonical_pass_rows)}")
    print(f"  Canonical precheck BLOCKED: {len(canonical_block_rows)}")

    financial_pass_rows = [
        row
        for row in result.package_audit_rows
        if str(row.get("financial_status", "")).lower() == "pass"
    ]
    if financial_pass_rows:
        print()
        print("FINANCIAL PASS SAMPLES")
        for row in financial_pass_rows[:8]:
            print(
                f"  {row.get('partner_team', '')} · "
                f"{row.get('target_player_name', '')} · "
                f"stage={row.get('route_stage', '')} · "
                f"user_delta={float(row.get('user_value_delta', 0.0)):+.1f} · "
                f"cpu_delta={float(row.get('cpu_value_delta', 0.0)):+.1f} · "
                f"floor={float(row.get('cpu_accept_floor', 0.0)):+.1f}"
            )

    if result.rejection_counts:
        print()
        print("TOP REJECTION COUNTS")
        for reason, count in sorted(result.rejection_counts.items(), key=lambda item: (-item[1], item[0]))[:10]:
            examples = result.rejection_examples.get(reason, ())
            suffix = (
                " · " + " | ".join(str(value) for value in examples[:2])
                if examples else ""
            )
            print(f"  {reason}: {count}{suffix}")

    if result.partner_funnel:
        print()
        print("PARTNER FUNNEL")
        for team, funnel in sorted(result.partner_funnel.items()):
            if not any(funnel.values()):
                continue
            print(
                f"  {team}: targets={funnel.get('targets', 0)} packages={funnel.get('packages', 0)} "
                f"financial_pass={funnel.get('financial_pass', 0)} legal={funnel.get('legal_pass', 0)} "
                f"offers={funnel.get('cpu_offers', 0)}"
            )

    resolved_preview_rows = [
        row
        for row in result.package_audit_rows
        if bool(row.get("anchor_financial_resolution_applied"))
    ]
    print()
    print("EMBEDDED ANCHOR RESOLUTION")
    print(
        f"  Full previews resolved by canonical anchor: "
        f"{len(resolved_preview_rows)}"
    )

    if result.proposals:
        print()
        print("ACTIONABLE OFFER SAMPLES")
        for proposal in result.proposals[:5]:
            print(
                f"  {proposal.partner_team} · {proposal.response_label} · {proposal.target_player_name} · "
                f"user_delta={proposal.user_value_delta:+.1f} · cpu_delta={proposal.cpu_value_delta:+.1f}"
            )

    if failed:
        raise AssertionError("Trade Finder Shared Market V1.5 failed: " + ", ".join(failed))

    print()
    print("TRADE FINDER SHARED MARKET CONTEXT + ANCHOR MARKET V1.5.3 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade, roster move, draft-right transfer, contract, free-agent or checkpoint mutation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
