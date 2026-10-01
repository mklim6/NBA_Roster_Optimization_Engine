from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = ROOT / "franchise_v2_draft_scouting_estimate_cache_v1"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_franchise_checkpoint_v1 as checkpoint_api
import franchise_free_agency_cpu_execution_v1 as cpu_fa_api
import franchise_draft_engine_v1 as patched_draft
import franchise_scouting_discovery_v1 as scouting_api
from freeform_trade_machine_engine_v3 import load_runtime_data
from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _isolated_checkpoint_contract,
)

OUTPUT_ROOT = ROOT / "outputs" / "v2_draft_scouting_estimate_cache_parity_v1"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def load_baseline_module():
    path = PACKAGE / "franchise_draft_engine_v1.BASELINE.py"
    spec = importlib.util.spec_from_file_location("franchise_draft_engine_baseline_parity_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load baseline draft module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sequence(module: Any, state: Any) -> list[tuple[int, str, str]]:
    current = module.draft_state(state)
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


def run_draft(module: Any, state: Any, runtime: Any, counter: dict[str, int]) -> tuple[float, list[tuple[int, str, str]]]:
    original = scouting_api.ai_scouted_estimate_v1

    def counted(*args: Any, **kwargs: Any) -> Any:
        counter["calls"] += 1
        return original(*args, **kwargs)

    scouting_api.ai_scouted_estimate_v1 = counted
    try:
        module.initialize_draft_state(
            state,
            runtime,
            controlled_teams=(),
            class_strength=5,
        )
        module.conduct_lottery(state, runtime)
        module.reveal_draft_class(state)
        module.start_draft_night(state, now_ts=1_800_000_000.0)
        wall0 = time.perf_counter()
        made = module.simulate_rest_of_draft(
            state,
            now_ts=1_800_000_000.0,
            integrate=True,
        )
        wall = time.perf_counter() - wall0
        if made != 60:
            raise RuntimeError(f"Expected 60 picks, got {made}.")
        return wall, sequence(module, state)
    finally:
        scouting_api.ai_scouted_estimate_v1 = original


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
    baseline_module = load_baseline_module()

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
            patched_state = copy.deepcopy(checkpoint.simulation_state)

            baseline_counter = {"calls": 0}
            patched_counter = {"calls": 0}
            baseline_wall, baseline_seq = run_draft(
                baseline_module, baseline_state, runtime, baseline_counter
            )
            patched_wall, patched_seq = run_draft(
                patched_draft, patched_state, runtime, patched_counter
            )

            report = {
                "fa_status": str(fa_result.status),
                "baseline_wall_seconds": baseline_wall,
                "patched_wall_seconds": patched_wall,
                "baseline_scouting_calls": baseline_counter["calls"],
                "patched_scouting_calls": patched_counter["calls"],
                "pick_sequences_match": baseline_seq == patched_seq,
                "baseline_sequence": baseline_seq,
                "patched_sequence": patched_seq,
            }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    active_after = _checkpoint_family_hashes(active)
    report["active_checkpoint_unchanged"] = active_before == active_after
    report["error"] = error
    report["passed"] = bool(
        not error
        and report.get("pick_sequences_match")
        and int(report.get("baseline_scouting_calls", 0)) == 3030
        and 0 < int(report.get("patched_scouting_calls", 0)) < int(report.get("baseline_scouting_calls", 0))
        and report["active_checkpoint_unchanged"]
    )

    path = out / "draft_scouting_estimate_cache_parity.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 86)
    print("FRANCHISE V2 DRAFT SCOUTING ESTIMATE CACHE V1 PARITY")
    print("=" * 86)
    print(f"Pick sequences match: {'YES' if report.get('pick_sequences_match') else 'NO'}")
    print(f"Baseline scouting calls: {report.get('baseline_scouting_calls', 0)}")
    print(f"Patched scouting calls:  {report.get('patched_scouting_calls', 0)}")
    print(f"Baseline draft wall: {float(report.get('baseline_wall_seconds', 0.0)):.3f}s")
    print(f"Patched draft wall:  {float(report.get('patched_wall_seconds', 0.0)):.3f}s")
    print(f"Active checkpoint unchanged: {'YES' if report['active_checkpoint_unchanged'] else 'NO'}")
    if error:
        print(f"ERROR: {error}")
    print(f"Report: {path}")
    print("=" * 86)

    if report["passed"]:
        print("DRAFT SCOUTING ESTIMATE CACHE PARITY PASSED")
        return 0
    print("DRAFT SCOUTING ESTIMATE CACHE PARITY FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
