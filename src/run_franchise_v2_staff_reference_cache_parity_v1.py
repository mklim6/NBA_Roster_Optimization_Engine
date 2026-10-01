from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_franchise_checkpoint_v1 as checkpoint_api
import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
import franchise_draft_engine_v1 as draft_api
import franchise_staff_system_v1 as staff_api
from freeform_trade_machine_engine_v3 import load_runtime_data
from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _isolated_checkpoint_contract,
)

OUTPUT_ROOT = ROOT / "outputs" / "v2_staff_reference_cache_parity_v1"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sequence(state: Any) -> list[tuple[int, str, str]]:
    current = draft_api.draft_state(state)
    if current is None:
        return []
    return [
        (
            int(pick.get("overall_pick", 0)),
            str(pick.get("owner_team", "")),
            str(pick.get("prospect_id", "")),
        )
        for pick in current.get("draft_order", [])
    ]


def run_draft(state: Any, runtime: Any) -> tuple[float, list[tuple[int, str, str]]]:
    draft_api.initialize_draft_state(
        state,
        runtime,
        controlled_teams=(),
        class_strength=5,
    )
    draft_api.conduct_lottery(state, runtime)
    draft_api.reveal_draft_class(state)
    draft_api.start_draft_night(state, now_ts=1_800_000_000.0)

    wall0 = time.perf_counter()
    made = draft_api.simulate_rest_of_draft(
        state,
        now_ts=1_800_000_000.0,
        integrate=True,
    )
    wall = time.perf_counter() - wall0
    if made != 60:
        raise RuntimeError(f"Expected 60 picks, got {made}.")
    return wall, sequence(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-checkpoint", required=True)
    args = parser.parse_args()

    source = Path(args.source_checkpoint).resolve()
    if not source.is_file():
        raise SystemExit(f"Source checkpoint not found: {source}")

    out = OUTPUT_ROOT / f"parity_{stamp()}"
    out.mkdir(parents=True, exist_ok=False)
    clone = out / "pre_draft_source.pkl.gz"
    recovery = out / "fa_recovery"
    shutil.copy2(source, clone)

    active = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = _checkpoint_family_hashes(active)

    cached_loader = staff_api._load_real_staff_reference
    cached_helper = staff_api._load_real_staff_reference_cached
    baseline_reads = {"count": 0}

    def uncached_loader() -> dict[str, Any]:
        baseline_reads["count"] += 1
        try:
            payload = json.loads(
                staff_api._REAL_STAFF_REFERENCE_PATH.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        if str(payload.get("version") or "") != staff_api.REAL_STAFF_REFERENCE_VERSION:
            return {}
        teams = payload.get("teams")
        return teams if isinstance(teams, dict) else {}

    error = ""
    report: dict[str, Any] = {}
    try:
        with _isolated_checkpoint_contract(clone):
            runtime = load_runtime_data()
            fa_result = cpu_fa_api.execute_cpu_free_agency_round_durably(
                max_signings=15,
                max_targets_per_team=8,
                recovery_directory=recovery,
            )
            checkpoint = checkpoint_api.load_franchise_checkpoint(path=clone)
            if checkpoint is None:
                raise RuntimeError("Could not reload isolated post-FA checkpoint.")

            baseline_state = copy.deepcopy(checkpoint.simulation_state)
            cached_state = copy.deepcopy(checkpoint.simulation_state)

            # Old behavior: every identity overlay parses the JSON again.
            staff_api._load_real_staff_reference = uncached_loader
            baseline_wall, baseline_seq = run_draft(
                baseline_state, runtime
            )

            # Patched behavior: identical staff/scouting code with only the
            # versioned file-signature cache enabled.
            staff_api._load_real_staff_reference = cached_loader
            cached_helper.cache_clear()
            cached_wall, cached_seq = run_draft(
                cached_state, runtime
            )
            cache_info = cached_helper.cache_info()

            report = {
                "fa_status": str(fa_result.status),
                "baseline_wall_seconds": baseline_wall,
                "cached_wall_seconds": cached_wall,
                "baseline_reference_reads": baseline_reads["count"],
                "cached_reference_cache_hits": int(cache_info.hits),
                "cached_reference_cache_misses": int(cache_info.misses),
                "cached_reference_cache_currsize": int(cache_info.currsize),
                "pick_sequences_match": baseline_seq == cached_seq,
                "baseline_sequence": baseline_seq,
                "cached_sequence": cached_seq,
            }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        staff_api._load_real_staff_reference = cached_loader

    active_after = _checkpoint_family_hashes(active)
    report["active_checkpoint_unchanged"] = active_before == active_after
    report["error"] = error
    report["passed"] = bool(
        not error
        and report.get("pick_sequences_match")
        and int(report.get("baseline_reference_reads", 0)) > 1000
        and int(report.get("cached_reference_cache_misses", 0)) == 1
        and int(report.get("cached_reference_cache_hits", 0)) > 1000
        and report["active_checkpoint_unchanged"]
    )

    path = out / "staff_reference_cache_parity.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 88)
    print("FRANCHISE V2 STAFF REFERENCE CACHE V1 PARITY")
    print("=" * 88)
    print(f"Pick sequences match: {'YES' if report.get('pick_sequences_match') else 'NO'}")
    print(f"Baseline reference JSON reads: {report.get('baseline_reference_reads', 0)}")
    print(f"Cached reference misses:       {report.get('cached_reference_cache_misses', 0)}")
    print(f"Cached reference hits:         {report.get('cached_reference_cache_hits', 0)}")
    print(f"Baseline draft wall: {float(report.get('baseline_wall_seconds', 0.0)):.3f}s")
    print(f"Cached draft wall:   {float(report.get('cached_wall_seconds', 0.0)):.3f}s")
    print(f"Active checkpoint unchanged: {'YES' if report['active_checkpoint_unchanged'] else 'NO'}")
    if error:
        print(f"ERROR: {error}")
    print(f"Report: {path}")
    print("=" * 88)

    if report["passed"]:
        print("STAFF REFERENCE CACHE PARITY PASSED")
        return 0

    print("STAFF REFERENCE CACHE PARITY FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
