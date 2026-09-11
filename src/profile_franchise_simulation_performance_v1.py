from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pstats
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROFILE_VERSION = "franchise-simulation-performance-profiling-v1.0.1-2026-08-13"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_ROOT = ROOT / "outputs" / "performance_profiles"
BATCH_ROOT = ROOT / "outputs" / "batch_simulation_audits"
BATCH_SCRIPT = SRC / "run_franchise_batch_simulation_audit_v2.py"
GAME = SRC / "single_game_simulator_v1.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
CHECKPOINT_MODULE = SRC / "simulation_franchise_checkpoint_v1.py"

EXPECTED = {
    "seed": 2026081300,
    "champion": "PHI",
    "runner_up": "MIN",
    "champion_regular_wins": 58.0,
    "regular_games": 1230.0,
    "league_team_ppg": 116.1426,
    "aggregate_fg_pct": 46.579383,
    "aggregate_3p_pct": 36.084233,
    "aggregate_ft_pct": 76.943323,
    "reg_fta_per_team_game": 25.174797,
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def category_for(filename: str, funcname: str) -> str:
    f = _norm(filename).lower()
    n = funcname.lower()
    joined = f + " " + n
    if "single_game_simulator_v1.py" in f:
        if "identity_" in n or "scoring" in n:
            return "shooting_identity_and_scoring"
        if "box" in n:
            return "player_box_score_generation"
        if "rotation" in n or "game_plan" in n or "minutes" in n:
            return "rotation_and_game_plan"
        return "single_game_simulator_other"
    if "simulation_postseason" in f or "postseason" in joined or "playoff" in joined:
        return "postseason"
    if any(k in joined for k in ("fatigue", "medical", "injury", "availability")):
        return "medical_fatigue"
    if any(k in f for k in ("simulation_league_state", "mutable_league_state", "state_runtime_adapter")):
        return "league_state_and_validation"
    if "run_franchise_batch_simulation_audit" in f:
        return "batch_audit_and_aggregation"
    if f.endswith("/copy.py") and "deepcopy" in n:
        return "deepcopy"
    if any(k in f for k in ("pandas/", "numpy/", "polars/", "duckdb")):
        return "dataframe_numeric"
    if any(k in joined for k in ("json", "csv", "zipfile", "write_", "to_csv", "serialize")):
        return "serialization_output"
    if str(ROOT).replace("\\", "/").lower() in f:
        return "other_project_code"
    return "python_or_dependency"


def is_project(filename: str) -> bool:
    root = str(ROOT).replace("\\", "/").lower()
    return root in _norm(filename).lower()


def analyze_pstats(profile_path: Path) -> dict[str, Any]:
    stats = pstats.Stats(str(profile_path))
    rows = []
    for (filename, line, funcname), values in stats.stats.items():
        cc, nc, tt, ct, callers = values
        rows.append({
            "filename": filename,
            "line": int(line),
            "function": funcname,
            "primitive_calls": int(cc),
            "total_calls": int(nc),
            "self_seconds": float(tt),
            "cumulative_seconds": float(ct),
            "category": category_for(filename, funcname),
            "project_code": is_project(filename),
        })
    total_self = sum(r["self_seconds"] for r in rows) or 1.0
    for r in rows:
        r["self_pct"] = 100.0 * r["self_seconds"] / total_self
    by_self = sorted(rows, key=lambda r: (-r["self_seconds"], -r["cumulative_seconds"], r["function"]))
    by_cum = sorted(rows, key=lambda r: (-r["cumulative_seconds"], -r["self_seconds"], r["function"]))
    project_self = [r for r in by_self if r["project_code"]]
    project_cum = [r for r in by_cum if r["project_code"]]
    cats: dict[str, dict[str, float]] = {}
    for r in rows:
        rec = cats.setdefault(r["category"], {"self_seconds": 0.0, "functions": 0})
        rec["self_seconds"] += r["self_seconds"]
        rec["functions"] += 1
    cat_rows = [
        {"category": k, "self_seconds": v["self_seconds"], "functions": int(v["functions"])}
        for k, v in cats.items()
    ]
    cat_rows.sort(key=lambda r: -r["self_seconds"])
    return {
        "profile_total_self_seconds": float(total_self),
        "all_by_self": by_self,
        "all_by_cumulative": by_cum,
        "project_by_self": project_self,
        "project_by_cumulative": project_cum,
        "categories_by_self": cat_rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def newest_batch_dir(before: set[Path]) -> Path:
    after = {p.resolve() for p in BATCH_ROOT.glob("batch_2026-27_1runs_*") if p.is_dir()}
    created = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
    if not created:
        raise RuntimeError("Profiler could not identify the newly created one-run batch directory.")
    return created[0]


def read_run_summary(batch_dir: Path) -> dict[str, Any]:
    path = batch_dir / "batch_run_summary.csv"
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    out: dict[str, Any] = dict(row)
    for key, value in list(out.items()):
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            pass
    return out


def assert_exact_contract(row: dict[str, Any]) -> None:
    for key, expected in EXPECTED.items():
        observed = row.get(key)
        if isinstance(expected, str):
            if str(observed) != expected:
                raise RuntimeError(f"Same-seed behavior changed: {key}={observed!r}, expected={expected!r}")
        else:
            if abs(float(observed) - float(expected)) > 5e-4:
                raise RuntimeError(f"Same-seed behavior changed: {key}={observed!r}, expected={expected!r}")


def concise_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": _norm(r["filename"]),
        "line": r["line"],
        "function": r["function"],
        "calls": r["total_calls"],
        "self_seconds": round(r["self_seconds"], 6),
        "cumulative_seconds": round(r["cumulative_seconds"], 6),
        "self_pct": round(r["self_pct"], 3),
        "category": r["category"],
    }


def choose_next_target(analysis: dict[str, Any]) -> dict[str, Any]:
    excluded = {"batch_audit_and_aggregation", "serialization_output", "python_or_dependency"}
    project = [r for r in analysis["project_by_self"] if r["category"] not in excluded]
    if not project:
        project = analysis["project_by_self"]
    top = project[0] if project else analysis["all_by_self"][0]
    return concise_row(top)


def self_test() -> int:
    import cProfile
    def burn(n: int) -> int:
        return sum(i * i for i in range(n))
    with tempfile.TemporaryDirectory() as td:
        pp = Path(td) / "toy.pstats"
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(20):
            burn(5000)
        pr.disable()
        pr.dump_stats(str(pp))
        analysis = analyze_pstats(pp)
        if not analysis["all_by_self"]:
            raise RuntimeError("Profiler self-test produced no function rows.")
        if not analysis["categories_by_self"]:
            raise RuntimeError("Profiler self-test produced no categories.")
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V1.0.1 SELF-TEST PASSED")
    return 0


def run_profile() -> int:
    game_text = GAME.read_text(encoding="utf-8")
    required = [
        '_SHOOTING_IDENTITY_PERFORMANCE_OPTIMIZATION_V1 = True',
        'SHOOTING_IDENTITY_PERFORMANCE_VERSION = "shooting-identity-performance-optimization-v1-2026-08-13"',
        '_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3 = True',
    ]
    missing = [m for m in required if m not in game_text]
    if missing:
        raise RuntimeError("Profiling V1 requires the live optimized V1.0.3 simulator. Missing: " + ", ".join(missing))
    if not BATCH_SCRIPT.is_file():
        raise RuntimeError(f"Missing batch audit script: {BATCH_SCRIPT}")
    if not CHECKPOINT_MODULE.is_file():
        raise RuntimeError(f"Missing canonical checkpoint module: {CHECKPOINT_MODULE}")
    if not CHECKPOINT.is_file():
        raise RuntimeError(f"Missing durable checkpoint: {CHECKPOINT}")

    # The checkpoint backend deliberately exposes a zero-argument loader.
    # Validate that contract without passing or inventing an alternate path.
    sys.path.insert(0, str(SRC))
    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
    loaded_checkpoint = load_franchise_checkpoint()
    if loaded_checkpoint is None or getattr(loaded_checkpoint, "simulation_state", None) is None:
        raise RuntimeError("Canonical zero-argument checkpoint loader did not return a usable franchise checkpoint.")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = OUTPUT_ROOT / f"franchise_simulation_performance_v1_{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    profile_path = out / "franchise_simulation_performance_v1.pstats"
    stdout_path = out / "profiled_batch_stdout.txt"
    checkpoint_before = sha(CHECKPOINT)
    game_before = sha(GAME)
    before_batches = {p.resolve() for p in BATCH_ROOT.glob("batch_2026-27_1runs_*") if p.is_dir()}

    command = [
        sys.executable, "-m", "cProfile", "-o", str(profile_path),
        str(BATCH_SCRIPT), "--runs", "1",
    ]
    print("=" * 104)
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V1.0.1")
    print("=" * 104)
    print("Profiling deterministic seed 2026081300 through Batch Audit V2.1...")
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    wall = time.perf_counter() - started
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    print(proc.stdout, end="")
    if proc.returncode:
        raise RuntimeError(f"Profiled one-run batch failed with exit code {proc.returncode}")

    batch_dir = newest_batch_dir(before_batches)
    run = read_run_summary(batch_dir)
    assert_exact_contract(run)
    checkpoint_after = sha(CHECKPOINT)
    game_after = sha(GAME)
    if checkpoint_after != checkpoint_before:
        raise RuntimeError("Durable franchise checkpoint changed during read-only profiling.")
    if game_after != game_before:
        raise RuntimeError("Simulator source changed during profiling.")

    analysis = analyze_pstats(profile_path)
    fields = ["filename", "line", "function", "primitive_calls", "total_calls", "self_seconds", "cumulative_seconds", "self_pct", "category", "project_code"]
    write_csv(out / "top_functions_by_self_time.csv", analysis["all_by_self"], fields)
    write_csv(out / "top_functions_by_cumulative_time.csv", analysis["all_by_cumulative"], fields)
    write_csv(out / "project_functions_by_self_time.csv", analysis["project_by_self"], fields)
    write_csv(out / "project_functions_by_cumulative_time.csv", analysis["project_by_cumulative"], fields)
    write_csv(out / "categories_by_self_time.csv", analysis["categories_by_self"], ["category", "self_seconds", "functions"])

    next_target = choose_next_target(analysis)
    summary = {
        "version": PROFILE_VERSION,
        "wall_seconds": wall,
        "profile_total_self_seconds": analysis["profile_total_self_seconds"],
        "same_seed_exact_match": True,
        "seed": 2026081300,
        "champion": run["champion"],
        "runner_up": run["runner_up"],
        "regular_season_seconds": run.get("regular_season_seconds"),
        "postseason_seconds": run.get("postseason_seconds"),
        "total_run_seconds": run.get("total_run_seconds"),
        "checkpoint_sha256": checkpoint_after,
        "simulator_sha256": game_after,
        "profiled_batch_dir": str(batch_dir),
        "top_project_self_time": [concise_row(r) for r in analysis["project_by_self"][:25]],
        "top_project_cumulative_time": [concise_row(r) for r in analysis["project_by_cumulative"][:25]],
        "categories_by_self_time": analysis["categories_by_self"],
        "recommended_next_target": next_target,
    }
    (out / "franchise_simulation_performance_summary_v1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "FRANCHISE SIMULATION PERFORMANCE PROFILING V1",
        "=" * 104,
        f"Wall time: {wall:.2f}s",
        f"Batch-reported regular season: {float(run.get('regular_season_seconds', 0)):.2f}s",
        f"Batch-reported postseason: {float(run.get('postseason_seconds', 0)):.2f}s",
        f"Batch-reported total run: {float(run.get('total_run_seconds', 0)):.2f}s",
        "Same-seed behavior: EXACT MATCH to V1.0.3 seed 2026081300",
        f"Checkpoint SHA256 unchanged: {checkpoint_after}",
        "",
        "TOP PROJECT FUNCTIONS BY SELF TIME",
    ]
    for i, r in enumerate(analysis["project_by_self"][:20], 1):
        rr = concise_row(r)
        lines.append(f"{i:>2}. {rr['self_seconds']:>8.3f}s self | {rr['cumulative_seconds']:>8.3f}s cum | {rr['calls']:>8} calls | {rr['function']} | {Path(rr['filename']).name}:{rr['line']} | {rr['category']}")
    lines += ["", "TOP PROJECT FUNCTIONS BY CUMULATIVE TIME"]
    for i, r in enumerate(analysis["project_by_cumulative"][:20], 1):
        rr = concise_row(r)
        lines.append(f"{i:>2}. {rr['cumulative_seconds']:>8.3f}s cum | {rr['self_seconds']:>8.3f}s self | {rr['calls']:>8} calls | {rr['function']} | {Path(rr['filename']).name}:{rr['line']} | {rr['category']}")
    lines += ["", "SELF-TIME CATEGORIES"]
    for r in analysis["categories_by_self"]:
        lines.append(f"{r['self_seconds']:>8.3f}s | {r['category']} | {r['functions']} functions")
    lines += ["", "RECOMMENDED NEXT TARGET", json.dumps(next_target, indent=2), "", f"Output directory: {out}"]
    report = "\n".join(lines) + "\n"
    (out / "franchise_simulation_performance_report_v1.txt").write_text(report, encoding="utf-8")

    print("\n" + "=" * 104)
    print("PROFILE COMPLETE")
    print("=" * 104)
    print(f"Wall time: {wall:.2f}s")
    print(f"Regular season: {float(run.get('regular_season_seconds', 0)):.2f}s")
    print(f"Postseason: {float(run.get('postseason_seconds', 0)):.2f}s")
    print("Same-seed behavior: EXACT MATCH")
    print("\nTOP 10 PROJECT SELF-TIME HOTSPOTS")
    for i, r in enumerate(analysis["project_by_self"][:10], 1):
        rr = concise_row(r)
        print(f"  #{i:<2} {rr['self_seconds']:.3f}s self | {rr['cumulative_seconds']:.3f}s cum | {rr['calls']} calls | {rr['function']} | {Path(rr['filename']).name}:{rr['line']}")
    print("\nRECOMMENDED NEXT TARGET")
    print(f"  {next_target['function']} | {Path(next_target['filename']).name}:{next_target['line']} | {next_target['self_seconds']:.3f}s self | {next_target['category']}")
    print(f"\nOutput directory: {out}")
    print(f"Upload this report next: {out / 'franchise_simulation_performance_summary_v1.json'}")
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V1.0.1 PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else run_profile()


if __name__ == "__main__":
    raise SystemExit(main())
