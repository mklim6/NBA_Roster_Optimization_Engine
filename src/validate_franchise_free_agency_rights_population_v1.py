from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import franchise_free_agency_rights_exceptions_v1 as rights
from franchise_free_agency_rights_population_v1 import (
    FREE_AGENCY_RIGHTS_OVERLAY_ENV,
    FREE_AGENCY_RIGHTS_POPULATION_VERSION,
    build_overlay_payload,
    build_rights_population_preview,
    load_overlay_for_state,
    strict_preview_checks,
    write_overlay_atomic,
)

VALIDATOR_VERSION = "franchise-free-agency-verified-bird-rights-population-validator-v1-2026-08-14"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def player(pid: str, name: str, service: int, salary: float) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        player_name=name,
        years_of_service=service,
        contract=SimpleNamespace(status="free_agent", salary=salary),
    )


def build_state() -> SimpleNamespace:
    players = {
        "BIRD": player("BIRD", "Bird Player", 4, 18_000_000.0),
        "EARLY": player("EARLY", "Early Player", 2, 8_000_000.0),
        "UNKNOWN": player("UNKNOWN", "Unknown Player", 4, 12_000_000.0),
        "ONE": player("ONE", "One Season Player", 1, 2_500_000.0),
        "EXPLICIT": player("EXPLICIT", "Explicit Player", 6, 4_000_000.0),
    }
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        players=players,
        free_agent_player_ids=tuple(players),
        season_history=[],
        free_agency_rights_registry_v1={
            "EXPLICIT": {
                "version": "free-agency-rights-evidence-v1",
                "player_id": "EXPLICIT",
                "prior_team": "CHA",
                "continuous_prior_seasons": 1,
                "continuity_verified": True,
                "prior_regular_salary": 4_000_000.0,
                "prior_average_player_salary": None,
                "restricted_free_agent": False,
                "qualifying_offer_amount": None,
                "source": "validator_explicit",
            }
        },
    )
    return state


def main() -> int:
    checks: dict[str, bool] = {}
    old_env = os.environ.get(FREE_AGENCY_RIGHTS_OVERLAY_ENV)
    try:
        print("=" * 120, flush=True)
        print("VERIFIED BIRD-RIGHTS POPULATION V1 VALIDATION", flush=True)
        print("=" * 120, flush=True)
        print("[1/5] Building exact player-team history fixtures...", flush=True)
        with tempfile.TemporaryDirectory(prefix="bird_rights_population_v1_") as tmp:
            root = Path(tmp)
            history = root / "verified_player_team_season_history.csv"
            history.write_text(
                "player_id,player_name,season,team_abbreviation,salary\n"
                "BIRD,Bird Player,2023-24,ATL,16000000\n"
                "BIRD,Bird Player,2024-25,ATL,17000000\n"
                "BIRD,Bird Player,2025-26,ATL,18000000\n"
                "EARLY,Early Player,2024-25,BOS,7000000\n"
                "EARLY,Early Player,2025-26,BOS,8000000\n"
                "UNKNOWN,Unknown Player,2025-26,DET,12000000\n"
                "ONE,One Season Player,2025-26,BKN,2500000\n",
                encoding="utf-8",
            )
            state = build_state()
            preview = build_rights_population_preview(state, root=root, explicit_history_paths=[history])
            by_id = {row.player_id: row for row in preview.candidates}

            checks["population_version_is_current"] = preview.version == FREE_AGENCY_RIGHTS_POPULATION_VERSION
            checks["bird_requires_three_explicit_consecutive_seasons"] = by_id["BIRD"].rights_classification == "bird" and by_id["BIRD"].prior_team == "ATL"
            checks["early_bird_requires_exact_two_season_service"] = by_id["EARLY"].rights_classification == "early_bird" and by_id["EARLY"].prior_team == "BOS"
            checks["one_observed_season_does_not_guess_non_bird"] = by_id["ONE"].status == "unresolved" and by_id["ONE"].rights_classification == "unknown"
            checks["insufficient_history_does_not_downgrade_possible_bird"] = by_id["UNKNOWN"].status == "unresolved" and by_id["UNKNOWN"].rights_classification == "unknown"
            checks["existing_explicit_registry_remains_authoritative"] = by_id["EXPLICIT"].status == "proven_existing_registry" and by_id["EXPLICIT"].rights_classification == "non_bird" and by_id["EXPLICIT"].prior_team == "CHA"
            checks["prior_salary_is_preserved_from_verified_history_or_state"] = by_id["BIRD"].prior_regular_salary == 18_000_000.0 and by_id["EARLY"].prior_regular_salary == 8_000_000.0
            checks["preview_strict_checks_pass"] = not [row for row in strict_preview_checks(preview) if row["status"] == "FAIL"]

            print("[2/5] Writing and loading a season-scoped overlay...", flush=True)
            overlay_path = root / "rights_overlay.json"
            payload = build_overlay_payload(preview, checkpoint_sha256="validator")
            written, recovery = write_overlay_atomic(payload, path=overlay_path)
            checks["overlay_writes_atomically"] = written == overlay_path.resolve() and recovery is None and overlay_path.exists()
            os.environ[FREE_AGENCY_RIGHTS_OVERLAY_ENV] = str(overlay_path)
            active = load_overlay_for_state(state)
            checks["overlay_exposes_only_verified_rows"] = set(active) == {"BIRD", "EARLY", "EXPLICIT"}

            print("[3/5] Verifying the locked rights engine consumes overlay evidence conservatively...", flush=True)
            bird = rights.resolve_free_agency_rights(state, "BIRD")
            early = rights.resolve_free_agency_rights(state, "EARLY")
            one = rights.resolve_free_agency_rights(state, "ONE")
            checks["rights_engine_consumes_verified_bird_overlay"] = bird.status == "pass" and bird.classification == "bird" and bird.prior_team == "ATL"
            checks["rights_engine_consumes_verified_early_bird_overlay"] = early.status == "pass" and early.classification == "early_bird" and early.prior_team == "BOS"
            bird_route = rights.resolve_prior_team_exception_route(
                state,
                rights.FreeAgencyOffer(
                    player_id="BIRD",
                    team_abbreviation="ATL",
                    annual_salary=20_000_000.0,
                    years=4,
                    guaranteed=True,
                    option_type="",
                ),
            )
            checks["overlay_drives_locked_bird_exception_route"] = bird_route.status == "pass" and bird_route.financial_route == rights.ROUTE_BIRD and bird_route.prior_team == "ATL"
            checks["rights_engine_ignores_unresolved_overlay_candidates"] = one.status == "manual_review" and one.classification == "unknown"

            explicit_override = copy.deepcopy(state)
            explicit_override.free_agency_rights_registry_v1["BIRD"] = {
                "version": "free-agency-rights-evidence-v1",
                "player_id": "BIRD",
                "prior_team": "LAL",
                "continuous_prior_seasons": 3,
                "continuity_verified": True,
                "prior_regular_salary": 18_000_000.0,
                "prior_average_player_salary": None,
                "restricted_free_agent": False,
                "qualifying_offer_amount": None,
                "source": "validator_override",
            }
            overridden = rights.resolve_free_agency_rights(explicit_override, "BIRD")
            checks["explicit_state_registry_overrides_overlay"] = overridden.prior_team == "LAL" and overridden.classification == "bird"

            wrong_season = copy.deepcopy(state)
            wrong_season.settings.season_label = "2027-28"
            checks["season_mismatched_overlay_is_ignored"] = load_overlay_for_state(wrong_season) == {}
            signed = copy.deepcopy(state)
            signed.free_agent_player_ids = tuple(pid for pid in signed.free_agent_player_ids if pid != "BIRD")
            checks["signed_player_overlay_row_is_ignored"] = "BIRD" not in load_overlay_for_state(signed)

            print("[4/5] Verifying live project preview is read-only...", flush=True)
            checkpoint_before = checkpoint_after = ""
            live_error = ""
            try:
                from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint
                checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
                checkpoint_before = sha256(checkpoint_path)
                durable = load_franchise_checkpoint()
                live_state = getattr(durable, "simulation_state")
                _ = build_rights_population_preview(live_state, root=Path.cwd())
                checkpoint_after = sha256(checkpoint_path)
                checks["live_preview_does_not_write_checkpoint"] = checkpoint_before == checkpoint_after
            except Exception as exc:
                live_error = f"{type(exc).__name__}: {exc}"
                checks["live_preview_does_not_write_checkpoint"] = False

            print("[5/5] Finalizing validation report...", flush=True)
            for key, value in checks.items():
                print(f"  {key}: {'PASS' if value else 'FAIL'}", flush=True)
            failed = [key for key, value in checks.items() if not value]
            print("", flush=True)
            print(json.dumps({
                "validator": VALIDATOR_VERSION,
                "rights_population": FREE_AGENCY_RIGHTS_POPULATION_VERSION,
                "checks": checks,
                "failed_checks": failed,
                "fixture": {
                    "free_agents": preview.free_agent_count,
                    "proven": preview.proven_count,
                    "bird": preview.bird_count,
                    "early_bird": preview.early_bird_count,
                    "non_bird": preview.non_bird_count,
                    "unresolved": preview.unresolved_count,
                },
                "live_checkpoint_hash_before": checkpoint_before,
                "live_checkpoint_hash_after": checkpoint_after,
                "live_error": live_error,
                "passed": not failed,
            }, indent=2, sort_keys=True), flush=True)
            if failed:
                print("\nVERIFIED BIRD-RIGHTS POPULATION V1 VALIDATION FAILED", flush=True)
                return 1
    finally:
        if old_env is None:
            os.environ.pop(FREE_AGENCY_RIGHTS_OVERLAY_ENV, None)
        else:
            os.environ[FREE_AGENCY_RIGHTS_OVERLAY_ENV] = old_env

    print("\nVERIFIED BIRD-RIGHTS POPULATION V1 VALIDATION PASSED", flush=True)
    print("READ-ONLY VALIDATION: no rights overlay, signing, roster mutation, Trade Machine mutation, or checkpoint write was persisted.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
