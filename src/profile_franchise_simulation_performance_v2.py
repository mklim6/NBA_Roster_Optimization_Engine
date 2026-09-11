from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pstats
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROFILE_VERSION = "franchise-simulation-performance-profiling-v2-2026-08-13"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_ROOT = ROOT / "outputs" / "performance_profiles"
BATCH_ROOT = ROOT / "outputs" / "batch_simulation_audits"
BATCH_SCRIPT = SRC / "run_franchise_batch_simulation_audit_v2.py"
GAME = SRC / "single_game_simulator_v1.py"
FINGERPRINT_V3 = SRC / "simulation_player_stat_fingerprints_v3.py"
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
    if "simulation_player_stat_fingerprints_v3.py" in f or "simulation_player_stat_fingerprints_v2.py" in f:
        if "cache" in n or "freeze" in n:
            return "player_fingerprint_cache_overhead"
        return "player_fingerprints"
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
    excluded = {
        "batch_audit_and_aggregation",
        "serialization_output",
        "python_or_dependency",
    }
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
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V2 SELF-TEST PASSED")
    return 0


def run_profile() -> int:
    game_text = GAME.read_text(encoding="utf-8")
    fingerprint_text = FINGERPRINT_V3.read_text(encoding="utf-8")
    game_required = [
        '_FRANCHISE_SIMULATION_PERFORMANCE_OPTIMIZATION_V2 = True',
        'FRANCHISE_SIMULATION_PERFORMANCE_VERSION_V2 = "franchise-simulation-performance-optimization-v2-2026-08-13"',
        '_SHOOTING_IDENTITY_PERFORMANCE_OPTIMIZATION_V1 = True',
        '_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3 = True',
    ]
    fingerprint_required = [
        '_PLAYER_FINGERPRINT_RUNTIME_CACHE_V1 = True',
        'PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION = "player-fingerprint-runtime-cache-v1-2026-08-13"',
    ]
    missing_game = [m for m in game_required if m not in game_text]
    missing_fp = [m for m in fingerprint_required if m not in fingerprint_text]
    if missing_game or missing_fp:
        raise RuntimeError(
            "Profiling V2 requires live Performance V2 + Fingerprint Runtime Cache V1. Missing: "
            + ", ".join(missing_game + missing_fp)
        )
    for p in (BATCH_SCRIPT, CHECKPOINT_MODULE, CHECKPOINT, FINGERPRINT_V3):
        if not p.is_file():
            raise RuntimeError(f"Missing required file: {p}")

    sys.path.insert(0, str(SRC))
    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
    loaded_checkpoint = load_franchise_checkpoint()
    if loaded_checkpoint is None or getattr(loaded_checkpoint, "simulation_state", None) is None:
        raise RuntimeError("Canonical zero-argument checkpoint loader did not return a usable franchise checkpoint.")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = OUTPUT_ROOT / f"franchise_simulation_performance_v2_{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    profile_path = out / "franchise_simulation_performance_v2.pstats"
    stdout_path = out / "profiled_batch_stdout.txt"
    cache_stats_path = out / "fingerprint_cache_stats_profiled_run.json"

    protected_before = {
        GAME: sha(GAME),
        FINGERPRINT_V3: sha(FINGERPRINT_V3),
        CHECKPOINT: sha(CHECKPOINT),
        CHECKPOINT_MODULE: sha(CHECKPOINT_MODULE),
    }
    before_batches = {p.resolve() for p in BATCH_ROOT.glob("batch_2026-27_1runs_*") if p.is_dir()}

    command = [
        sys.executable,
        "-m",
        "cProfile",
        "-o",
        str(profile_path),
        str(BATCH_SCRIPT),
        "--runs",
        "1",
    ]
    env = os.environ.copy()
    env["NBA_FINGERPRINT_CACHE_STATS_PATH"] = str(cache_stats_path)

    print("=" * 104)
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V2")
    print("=" * 104)
    print("Profiling CURRENT post-V2 + Fingerprint Cache engine at deterministic seed 2026081300...")
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    wall = time.perf_counter() - started
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    print(proc.stdout, end="")
    if proc.returncode:
        raise RuntimeError(f"Profiled one-run batch failed with exit code {proc.returncode}")

    batch_dir = newest_batch_dir(before_batches)
    run = read_run_summary(batch_dir)
    assert_exact_contract(run)
    for p, digest in protected_before.items():
        if sha(p) != digest:
            raise RuntimeError(f"Protected file changed during profiling: {p}")

    analysis = analyze_pstats(profile_path)
    fields = [
        "filename", "line", "function", "primitive_calls", "total_calls",
        "self_seconds", "cumulative_seconds", "self_pct", "category", "project_code",
    ]
    write_csv(out / "top_functions_by_self_time.csv", analysis["all_by_self"], fields)
    write_csv(out / "top_functions_by_cumulative_time.csv", analysis["all_by_cumulative"], fields)
    write_csv(out / "project_functions_by_self_time.csv", analysis["project_by_self"], fields)
    write_csv(out / "project_functions_by_cumulative_time.csv", analysis["project_by_cumulative"], fields)
    write_csv(
        out / "categories_by_self_time.csv",
        analysis["categories_by_self"],
        ["category", "self_seconds", "functions"],
    )

    cache_stats: dict[str, Any] = {}
    if cache_stats_path.is_file():
        try:
            cache_stats = json.loads(cache_stats_path.read_text(encoding="utf-8"))
        except Exception:
            cache_stats = {"read_error": True}

    next_target = choose_next_target(analysis)
    summary = {
        "version": PROFILE_VERSION,
        "wall_seconds": wall,
        "unprofiled_baseline_seconds": 31.27,
        "profile_total_self_seconds": analysis["profile_total_self_seconds"],
        "same_seed_exact_match": True,
        "seed": 2026081300,
        "champion": run["champion"],
        "runner_up": run["runner_up"],
        "regular_season_seconds": run.get("regular_season_seconds"),
        "postseason_seconds": run.get("postseason_seconds"),
        "total_run_seconds": run.get("total_run_seconds"),
        "checkpoint_sha256": protected_before[CHECKPOINT],
        "simulator_sha256": protected_before[GAME],
        "fingerprint_v3_sha256": protected_before[FINGERPRINT_V3],
        "profiled_batch_dir": str(batch_dir),
        "fingerprint_cache_stats": cache_stats,
        "top_project_self_time": [concise_row(r) for r in analysis["project_by_self"][:30]],
        "top_project_cumulative_time": [concise_row(r) for r in analysis["project_by_cumulative"][:30]],
        "categories_by_self_time": analysis["categories_by_self"],
        "recommended_next_target": next_target,
    }
    summary_path = out / "franchise_simulation_performance_summary_v2.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "FRANCHISE SIMULATION PERFORMANCE PROFILING V2",
        "=" * 104,
        f"Wall time under cProfile: {wall:.2f}s",
        f"Unprofiled baseline before this profiler: 31.27s",
        f"Batch-reported regular season under profile: {float(run.get('regular_season_seconds', 0)):.2f}s",
        f"Batch-reported postseason under profile: {float(run.get('postseason_seconds', 0)):.2f}s",
        "Same-seed behavior: EXACT MATCH to seed 2026081300",
        f"Checkpoint SHA256 unchanged: {protected_before[CHECKPOINT]}",
        "",
        "TOP PROJECT FUNCTIONS BY SELF TIME",
    ]
    for i, r in enumerate(analysis["project_by_self"][:25], 1):
        rr = concise_row(r)
        lines.append(
            f"{i:>2}. {rr['self_seconds']:>8.3f}s self | {rr['cumulative_seconds']:>8.3f}s cum | "
            f"{rr['calls']:>9} calls | {rr['function']} | {Path(rr['filename']).name}:{rr['line']} | {rr['category']}"
        )
    lines += ["", "SELF-TIME CATEGORIES"]
    for r in analysis["categories_by_self"]:
        lines.append(f"{r['self_seconds']:>8.3f}s | {r['category']} | {r['functions']} functions")
    lines += [
        "",
        "FINGERPRINT CACHE DURING PROFILE",
        json.dumps(cache_stats, indent=2),
        "",
        "RECOMMENDED NEXT TARGET",
        json.dumps(next_target, indent=2),
        "",
        f"Output directory: {out}",
    ]
    (out / "franchise_simulation_performance_report_v2.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 104)
    print("POST-OPTIMIZATION PROFILE COMPLETE")
    print("=" * 104)
    print(f"Wall time under cProfile: {wall:.2f}s")
    print(f"Unprofiled baseline: 31.27s")
    print(f"Regular season under profile: {float(run.get('regular_season_seconds', 0)):.2f}s")
    print(f"Postseason under profile: {float(run.get('postseason_seconds', 0)):.2f}s")
    print("Same-seed behavior: EXACT MATCH")
    if cache_stats:
        print(
            "Fingerprint cache under profile: "
            f"hits={cache_stats.get('hits')} misses={cache_stats.get('misses')} "
            f"hit_rate={100.0 * float(cache_stats.get('hit_rate', 0.0)):.1f}%"
        )
    print("\nTOP 12 CURRENT PROJECT SELF-TIME HOTSPOTS")
    for i, r in enumerate(analysis["project_by_self"][:12], 1):
        rr = concise_row(r)
        print(
            f"  #{i:<2} {rr['self_seconds']:.3f}s self | {rr['cumulative_seconds']:.3f}s cum | "
            f"{rr['calls']} calls | {rr['function']} | {Path(rr['filename']).name}:{rr['line']}"
        )
    print("\nRECOMMENDED NEXT TARGET")
    print(
        f"  {next_target['function']} | {Path(next_target['filename']).name}:{next_target['line']} | "
        f"{next_target['self_seconds']:.3f}s self | {next_target['category']}"
    )
    print(f"\nOutput directory: {out}")
    print(f"Upload this report next: {summary_path}")
    print("FRANCHISE SIMULATION PERFORMANCE PROFILING V2 PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else run_profile()


if __name__ == "__main__":
    raise SystemExit(main())
