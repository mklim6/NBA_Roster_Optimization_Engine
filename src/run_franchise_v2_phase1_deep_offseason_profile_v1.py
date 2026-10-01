from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_ROOT = ROOT / "outputs" / "v2_phase1_deep_offseason_profile_v1"
VERSION = "franchise-v2-phase1-deep-offseason-profile-v1-2026-09-26"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _isolated_checkpoint_contract,
    _save_and_assert_roundtrip,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _population(state: Any) -> dict[str, Any]:
    counts = {
        str(team): len(getattr(team_state, "roster_player_ids", []) or [])
        for team, team_state in (getattr(state, "teams", {}) or {}).items()
    }
    return {
        "teams": len(counts),
        "minimum_roster": min(counts.values()) if counts else 0,
        "maximum_roster": max(counts.values()) if counts else 0,
        "roster_counts": dict(sorted(counts.items())),
    }


def _timed(
    rows: list[dict[str, Any]],
    label: str,
    function: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    wall0 = time.perf_counter()
    cpu0 = time.process_time()
    result = function(*args, **kwargs)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    rows.append(
        {
            "label": label,
            "wall_seconds": round(wall, 6),
            "cpu_seconds": round(cpu, 6),
        }
    )
    print(f"  {label}: wall={wall:.3f}s cpu={cpu:.3f}s", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Profile a preserved deep-offseason checkpoint on an isolated clone. "
            "The active franchise checkpoint family is never selected for mutation."
        )
    )
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument(
        "--timing-only",
        action="store_true",
        help=(
            "Measure production-like wall/CPU time without cProfile overhead. "
            "Isolation, validation, and active-checkpoint protection remain enabled."
        ),
    )
    args = parser.parse_args()

    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_draft_engine_v1 as draft_api
    import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
    import franchise_cpu_post_draft_roster_trim_live_v1 as trim_api
    import franchise_season_boundary_durable_transition_v1 as boundary_api
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from simulation_league_state_v1 import validate_simulation_league_state
    from mutable_league_state_v1 import validate_state

    source = Path(args.source_checkpoint).resolve()
    if not source.is_file():
        raise SystemExit(f"Source checkpoint not found: {source}")

    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    if source == active_primary:
        raise SystemExit("Refusing to profile the active franchise checkpoint directly.")

    run_root = OUTPUT_ROOT / f"profile_{_stamp()}"
    run_root.mkdir(parents=True, exist_ok=False)
    clone = run_root / "profile_checkpoint.pkl.gz"
    recovery = run_root / "recovery"
    shutil.copy2(source, clone)

    active_before = _checkpoint_family_hashes(active_primary)
    timings: list[dict[str, Any]] = []
    profiler = cProfile.Profile()
    report: dict[str, Any] = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_checkpoint": str(source),
        "isolated_checkpoint": str(clone),
        "active_checkpoint_path": str(active_primary),
        "active_checkpoint_family_before": active_before,
        "profiling_mode": (
            "timing_only" if args.timing_only else "cprofile"
        ),
        "timings": timings,
        "passed": False,
        "error": "",
    }

    print("FRANCHISE V2 PHASE 1 DEEP OFFSEASON PROFILE V1")
    print(f"Source: {source}")
    print(f"Clone: {clone}")
    print("Active franchise mutation: FORBIDDEN")
    print()

    exit_code = 0
    try:
        with _isolated_checkpoint_contract(clone):
            runtime = load_runtime_data()

            print("Finish preserved CPU Free Agency market", flush=True)
            if not args.timing_only:
                profiler.enable()
            fa_result = _timed(
                timings,
                "finish_cpu_free_agency_round",
                cpu_fa_api.execute_cpu_free_agency_round_durably,
                max_signings=15,
                max_targets_per_team=8,
                recovery_directory=recovery / "free_agency",
            )
            if not args.timing_only:
                profiler.disable()

            fa_checkpoint = checkpoint_api.load_franchise_checkpoint(path=clone)
            if fa_checkpoint is None:
                raise RuntimeError("Isolated checkpoint could not be reloaded after Free Agency.")
            validate_simulation_league_state(fa_checkpoint.simulation_state)
            validate_state(fa_checkpoint.trade_state, runtime)
            deficits = cpu_fa_api.cpu_sustainable_roster_deficits(
                fa_checkpoint.simulation_state,
                (),
            )
            report["free_agency"] = {
                "status": str(fa_result.status),
                "committed_signing_count": int(fa_result.committed_signing_count),
                "stop_reason": str(fa_result.stop_reason),
                "remaining_sustainable_deficits": [list(row) for row in deficits],
                "population": _population(fa_checkpoint.simulation_state),
            }
            if deficits:
                raise RuntimeError(
                    "Preserved Free Agency checkpoint did not finish at the sustainable roster target."
                )

            print("Profile Draft and post-Draft trim", flush=True)
            if not args.timing_only:
                profiler.enable()
            _timed(
                timings,
                "initialize_draft_state",
                draft_api.initialize_draft_state,
                fa_checkpoint.simulation_state,
                runtime,
                controlled_teams=(),
                class_strength=5,
            )
            _timed(
                timings,
                "conduct_lottery",
                draft_api.conduct_lottery,
                fa_checkpoint.simulation_state,
                runtime,
            )
            _timed(
                timings,
                "reveal_draft_class",
                draft_api.reveal_draft_class,
                fa_checkpoint.simulation_state,
            )
            _timed(
                timings,
                "start_draft_night",
                draft_api.start_draft_night,
                fa_checkpoint.simulation_state,
            )
            drafted_count = _timed(
                timings,
                "simulate_rest_of_draft",
                draft_api.simulate_rest_of_draft,
                fa_checkpoint.simulation_state,
                integrate=True,
            )
            current_draft = draft_api.draft_state(fa_checkpoint.simulation_state)
            if current_draft is None:
                raise RuntimeError("Draft state disappeared during profiling.")

            save_wall0 = time.perf_counter()
            save_cpu0 = time.process_time()
            draft_checkpoint, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                clone,
                fa_checkpoint.simulation_state,
                fa_checkpoint.trade_state,
                preferences=fa_checkpoint.preferences,
                reason="v2-phase1-deep-offseason-profile-draft-complete",
            )
            timings.append(
                {
                    "label": "draft_save_and_roundtrip",
                    "wall_seconds": round(time.perf_counter() - save_wall0, 6),
                    "cpu_seconds": round(time.process_time() - save_cpu0, 6),
                }
            )
            print(
                "  draft_save_and_roundtrip: "
                f"wall={timings[-1]['wall_seconds']:.3f}s "
                f"cpu={timings[-1]['cpu_seconds']:.3f}s",
                flush=True,
            )
            if expected != observed:
                raise RuntimeError("Draft checkpoint round-trip fingerprint mismatch.")

            trim_source_fp = boundary_api.checkpoint_boundary_fingerprint(
                draft_checkpoint
            )
            trim_result = _timed(
                timings,
                "commit_atomic_cpu_post_draft_trim_live",
                trim_api.commit_atomic_cpu_post_draft_trim_live,
                expected_source_fingerprint=trim_source_fp,
                confirmation=trim_api.confirmation_token(
                    draft_checkpoint.simulation_state
                ),
                checkpoint_path=clone,
                recovery_directory=recovery / "trim",
            )
            if not args.timing_only:
                profiler.disable()

            final_checkpoint = checkpoint_api.load_franchise_checkpoint(path=clone)
            if final_checkpoint is None:
                raise RuntimeError("Trimmed checkpoint could not be reloaded.")
            validate_simulation_league_state(final_checkpoint.simulation_state)
            validate_state(final_checkpoint.trade_state, runtime)
            final_population = _population(final_checkpoint.simulation_state)
            order_count = len(current_draft.get("draft_order", []) or [])
            report["draft"] = {
                "draft_year": int(current_draft.get("draft_year", 0) or 0),
                "drafted_count": int(drafted_count),
                "draft_order_count": order_count,
                "complete": bool(draft_api.draft_is_complete(draft_checkpoint.simulation_state)),
            }
            report["trim"] = {
                "status": str(trim_result.status),
                "population": final_population,
            }
            report["passed"] = bool(
                drafted_count == order_count
                and order_count > 0
                and final_population["minimum_roster"] >= 14
                and final_population["maximum_roster"] <= 15
            )
            if not report["passed"]:
                raise RuntimeError("Deep-offseason profile completed with failed invariants.")
    except BaseException as exc:
        if not args.timing_only:
            profiler.disable()
        report["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
        traceback.print_exc()
    finally:
        active_after = _checkpoint_family_hashes(active_primary)
        report["active_checkpoint_family_after"] = active_after
        report["active_checkpoint_family_unchanged"] = active_before == active_after
        if not report["active_checkpoint_family_unchanged"]:
            report["passed"] = False
            exit_code = 1

        if not args.timing_only:
            profiler.dump_stats(str(run_root / "deep_offseason_profile.pstats"))
            with (run_root / "deep_offseason_profile.txt").open(
                "w", encoding="utf-8"
            ) as handle:
                stats = pstats.Stats(profiler, stream=handle)
                stats.strip_dirs().sort_stats("cumulative").print_stats(80)
                stats.sort_stats("tottime").print_stats(80)
        (run_root / "deep_offseason_profile.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

    print()
    print(f"Passed: {report['passed']}")
    print(
        "Active checkpoint unchanged: "
        f"{report['active_checkpoint_family_unchanged']}"
    )
    print(f"Output: {run_root}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
