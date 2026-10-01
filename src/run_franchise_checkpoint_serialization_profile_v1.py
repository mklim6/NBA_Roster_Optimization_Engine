from __future__ import annotations

import argparse
import cProfile
import copy
import gc
import hashlib
import inspect
import io
import json
import pstats
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_franchise_checkpoint_v1 as checkpoint_module

PROFILE_VERSION = "franchise-checkpoint-serialization-profile-v1-2026-09-28"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "v2_checkpoint_serialization_profile_v1"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "mean_s": statistics.mean(values) if values else None,
        "median_s": statistics.median(values) if values else None,
        "min_s": min(values) if values else None,
        "max_s": max(values) if values else None,
        "p90_s": percentile(values, 0.90),
    }


def time_call(label: str, fn: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - started
    print(f"{label:<46} {elapsed:9.3f}s")
    return result, elapsed


def maybe_runtime_graph_current(value: Any) -> tuple[bool | None, float | None]:
    fn = getattr(checkpoint_module, "runtime_graph_is_current", None)
    if fn is None:
        return None, None
    result, elapsed = time_call("runtime_graph_is_current(checkpoint)", lambda: fn(value))
    return bool(result), elapsed


def checkpoint_kwargs_supported(**requested: Any) -> dict[str, Any]:
    signature = inspect.signature(checkpoint_module.save_franchise_checkpoint)
    supported = {}
    for key, value in requested.items():
        if key in signature.parameters:
            supported[key] = value
    return supported


def run_save_probe(
    *,
    name: str,
    target_path: Path,
    checkpoint: Any,
    extra_kwargs: dict[str, Any],
) -> tuple[Any, float, dict[str, Any]]:
    kwargs = dict(
        preferences=checkpoint.preferences,
        reason=f"{PROFILE_VERSION}:{name}",
        path=target_path,
    )
    kwargs.update(checkpoint_kwargs_supported(
        copy_payload=extra_kwargs.pop("copy_payload", True),
        force_replace=True,
        _return_verified=extra_kwargs.pop("_return_verified", False),
        _existing_checkpoint=extra_kwargs.pop("_existing_checkpoint", None),
        _expected_existing_sha256=extra_kwargs.pop("_expected_existing_sha256", ""),
        _verify_encoded_bytes_only=extra_kwargs.pop("_verify_encoded_bytes_only", False),
    ))
    kwargs.update(extra_kwargs)

    result, elapsed = time_call(
        f"save_franchise_checkpoint [{name}]",
        lambda: checkpoint_module.save_franchise_checkpoint(
            checkpoint.simulation_state,
            checkpoint.trade_state,
            **kwargs,
        ),
    )
    metadata = {
        "path": str(target_path),
        "size_bytes": target_path.stat().st_size if target_path.exists() else None,
        "sha256": sha256_file(target_path) if target_path.exists() else None,
        "kwargs": {
            key: (
                "<checkpoint-object>"
                if key == "_existing_checkpoint" and value is not None
                else value
            )
            for key, value in kwargs.items()
            if key not in {"preferences"}
        },
    }
    return result, elapsed, metadata


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only performance profiler for franchise checkpoint deepcopy, "
            "serialization, gzip/disk write, decode/reload, and save fast paths."
        )
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=checkpoint_module.DEFAULT_CHECKPOINT_PATH,
        help="Source checkpoint to profile. It is never modified.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=2,
        help="Repeat isolated in-memory stages this many times (default: 2).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument(
        "--cprofile",
        action="store_true",
        help="Also cProfile one no-copy byte-verified save to a disposable checkpoint.",
    )
    args = parser.parse_args()

    source_path = args.checkpoint.resolve()
    if not source_path.exists():
        raise SystemExit(f"Checkpoint not found: {source_path}")
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")

    run_dir = args.output_root / f"profile_{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)

    source_before = {
        "path": str(source_path),
        "size_bytes": source_path.stat().st_size,
        "mtime_ns": source_path.stat().st_mtime_ns,
        "sha256": sha256_file(source_path),
    }

    print("=" * 74)
    print("V2 CHECKPOINT SERIALIZATION / DEEP-COPY PROFILE")
    print("=" * 74)
    print(f"Version:    {PROFILE_VERSION}")
    print(f"Source:     {source_path}")
    print(f"Source MB:  {source_before['size_bytes'] / (1024 * 1024):.2f}")
    print(f"Repeat:     {args.repeat}")
    print(f"Output:     {run_dir}")
    print()
    print("SAFETY: the source checkpoint is read-only; all probe writes are disposable.")
    print()

    checkpoint, source_load_s = time_call(
        "load_franchise_checkpoint(source)",
        lambda: checkpoint_module.load_franchise_checkpoint(
            path=source_path,
            allow_backup=False,
        ),
    )
    if checkpoint is None:
        raise RuntimeError("Source checkpoint resolved to None.")

    graph_current, graph_scan_s = maybe_runtime_graph_current(checkpoint)

    stage_times: dict[str, list[float]] = {
        "deepcopy_simulation_state": [],
        "deepcopy_trade_state": [],
        "deepcopy_preferences": [],
        "encode_checkpoint": [],
        "decode_checkpoint_in_memory": [],
        "write_encoded_checkpoint": [],
        "load_checkpoint_path": [],
    }
    encoded_sizes: list[int] = []

    encode_fn = checkpoint_module.encode_checkpoint
    decode_fn = checkpoint_module.decode_checkpoint
    write_fn = checkpoint_module.write_encoded_checkpoint
    load_path_fn = checkpoint_module.load_checkpoint_path

    latest_encoded: bytes | None = None

    for iteration in range(1, args.repeat + 1):
        print()
        print(f"--- isolated stage pass {iteration}/{args.repeat} ---")

        sim_copy, elapsed = time_call(
            "copy.deepcopy(simulation_state)",
            lambda: copy.deepcopy(checkpoint.simulation_state),
        )
        stage_times["deepcopy_simulation_state"].append(elapsed)
        del sim_copy
        gc.collect()

        trade_copy, elapsed = time_call(
            "copy.deepcopy(trade_state)",
            lambda: copy.deepcopy(checkpoint.trade_state),
        )
        stage_times["deepcopy_trade_state"].append(elapsed)
        del trade_copy
        gc.collect()

        pref_copy, elapsed = time_call(
            "copy.deepcopy(preferences)",
            lambda: copy.deepcopy(checkpoint.preferences),
        )
        stage_times["deepcopy_preferences"].append(elapsed)
        del pref_copy
        gc.collect()

        encoded, elapsed = time_call(
            "encode_checkpoint(checkpoint)",
            lambda: encode_fn(checkpoint),
        )
        stage_times["encode_checkpoint"].append(elapsed)
        encoded_sizes.append(len(encoded))
        latest_encoded = encoded

        decoded, elapsed = time_call(
            "decode_checkpoint(encoded) [memory]",
            lambda: decode_fn(encoded),
        )
        stage_times["decode_checkpoint_in_memory"].append(elapsed)
        del decoded
        gc.collect()

        write_path = run_dir / f"isolated_write_{iteration}.pkl.gz"
        _, elapsed = time_call(
            "write_encoded_checkpoint(temp)",
            lambda: write_fn(write_path, encoded),
        )
        stage_times["write_encoded_checkpoint"].append(elapsed)

        loaded, elapsed = time_call(
            "load_checkpoint_path(temp)",
            lambda: load_path_fn(write_path),
        )
        stage_times["load_checkpoint_path"].append(elapsed)
        del loaded
        gc.collect()

    print()
    print("--- end-to-end save path probes ---")
    save_probes: dict[str, Any] = {}

    baseline_path = run_dir / "save_baseline_copy_semantic.pkl.gz"
    baseline_result, baseline_s, baseline_meta = run_save_probe(
        name="baseline_copy_semantic",
        target_path=baseline_path,
        checkpoint=checkpoint,
        extra_kwargs={
            "copy_payload": True,
            "_return_verified": True,
        },
    )
    save_probes["baseline_copy_semantic"] = {
        "elapsed_s": baseline_s,
        **baseline_meta,
    }
    del baseline_result
    gc.collect()

    nocopy_path = run_dir / "save_no_copy_semantic.pkl.gz"
    nocopy_result, nocopy_s, nocopy_meta = run_save_probe(
        name="no_copy_semantic",
        target_path=nocopy_path,
        checkpoint=checkpoint,
        extra_kwargs={
            "copy_payload": False,
            "_return_verified": True,
        },
    )
    save_probes["no_copy_semantic"] = {
        "elapsed_s": nocopy_s,
        **nocopy_meta,
    }
    del nocopy_result
    gc.collect()

    fast_path_available = (
        "_verify_encoded_bytes_only"
        in inspect.signature(checkpoint_module.save_franchise_checkpoint).parameters
    )

    byte_verified_result = None
    byte_verified_s = None
    byte_verified_path = run_dir / "save_no_copy_byte_verified.pkl.gz"
    if fast_path_available:
        byte_verified_result, byte_verified_s, byte_meta = run_save_probe(
            name="no_copy_byte_verified",
            target_path=byte_verified_path,
            checkpoint=checkpoint,
            extra_kwargs={
                "copy_payload": False,
                "_return_verified": True,
                "_verify_encoded_bytes_only": True,
            },
        )
        save_probes["no_copy_byte_verified"] = {
            "elapsed_s": byte_verified_s,
            **byte_meta,
        }
    else:
        save_probes["no_copy_byte_verified"] = {
            "available": False,
            "reason": "_verify_encoded_bytes_only not supported by current save signature",
        }

    repeated_fast_available = all(
        name in inspect.signature(checkpoint_module.save_franchise_checkpoint).parameters
        for name in (
            "_existing_checkpoint",
            "_expected_existing_sha256",
            "_verify_encoded_bytes_only",
        )
    )
    if repeated_fast_available and byte_verified_result is not None:
        existing_sha = sha256_file(byte_verified_path)
        repeated_result, repeated_s, repeated_meta = run_save_probe(
            name="repeat_with_existing_evidence",
            target_path=byte_verified_path,
            checkpoint=checkpoint,
            extra_kwargs={
                "copy_payload": False,
                "_return_verified": True,
                "_existing_checkpoint": byte_verified_result,
                "_expected_existing_sha256": existing_sha,
                "_verify_encoded_bytes_only": True,
            },
        )
        save_probes["repeat_with_existing_evidence"] = {
            "elapsed_s": repeated_s,
            **repeated_meta,
        }
        del repeated_result
    else:
        save_probes["repeat_with_existing_evidence"] = {
            "available": False,
            "reason": "existing-checkpoint evidence fast path not supported",
        }

    cprofile_report = None
    if args.cprofile and fast_path_available:
        print()
        print("--- cProfile: no-copy byte-verified save ---")
        profile_path = run_dir / "cprofile_probe.pkl.gz"
        profiler = cProfile.Profile()
        profiler.enable()
        checkpoint_module.save_franchise_checkpoint(
            checkpoint.simulation_state,
            checkpoint.trade_state,
            preferences=checkpoint.preferences,
            reason=f"{PROFILE_VERSION}:cprofile",
            path=profile_path,
            **checkpoint_kwargs_supported(
                copy_payload=False,
                force_replace=True,
                _return_verified=True,
                _verify_encoded_bytes_only=True,
            ),
        )
        profiler.disable()
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(60)
        cprofile_report = stream.getvalue()
        (run_dir / "cprofile_top60.txt").write_text(cprofile_report, encoding="utf-8")
        print("Wrote cprofile_top60.txt")

    source_after = {
        "path": str(source_path),
        "size_bytes": source_path.stat().st_size,
        "mtime_ns": source_path.stat().st_mtime_ns,
        "sha256": sha256_file(source_path),
    }
    source_unchanged = source_before == source_after

    stage_summary = {name: summarize(values) for name, values in stage_times.items()}
    baseline_elapsed = save_probes["baseline_copy_semantic"]["elapsed_s"]
    nocopy_elapsed = save_probes["no_copy_semantic"]["elapsed_s"]
    byte_elapsed = (
        save_probes["no_copy_byte_verified"].get("elapsed_s")
        if isinstance(save_probes["no_copy_byte_verified"], dict)
        else None
    )
    repeat_elapsed = (
        save_probes["repeat_with_existing_evidence"].get("elapsed_s")
        if isinstance(save_probes["repeat_with_existing_evidence"], dict)
        else None
    )

    def savings(base: float | None, optimized: float | None) -> dict[str, float | None]:
        if not base or optimized is None:
            return {"seconds_saved": None, "percent_saved": None, "speedup_x": None}
        return {
            "seconds_saved": base - optimized,
            "percent_saved": (base - optimized) / base * 100.0,
            "speedup_x": base / optimized if optimized > 0 else None,
        }

    conclusions = {
        "copy_payload_savings": savings(baseline_elapsed, nocopy_elapsed),
        "byte_verification_savings_vs_baseline": savings(baseline_elapsed, byte_elapsed),
        "existing_evidence_savings_vs_baseline": savings(baseline_elapsed, repeat_elapsed),
    }

    report = {
        "profile_version": PROFILE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_checkpoint_before": source_before,
        "source_checkpoint_after": source_after,
        "source_checkpoint_unchanged": source_unchanged,
        "checkpoint_module_version": getattr(
            checkpoint_module, "CHECKPOINT_IMPLEMENTATION_VERSION", ""
        ),
        "checkpoint_format_version": getattr(
            checkpoint_module, "CHECKPOINT_VERSION", ""
        ),
        "source_load_s": source_load_s,
        "runtime_graph_is_current": graph_current,
        "runtime_graph_scan_s": graph_scan_s,
        "repeat": args.repeat,
        "encoded_size_bytes": encoded_sizes,
        "encoded_size_mean_bytes": statistics.mean(encoded_sizes) if encoded_sizes else None,
        "isolated_stage_summary": stage_summary,
        "save_probes": save_probes,
        "comparisons": conclusions,
        "fast_path_support": {
            "byte_verification": fast_path_available,
            "existing_checkpoint_evidence": repeated_fast_available,
        },
        "cprofile_written": bool(cprofile_report),
        "safety": {
            "source_writes_attempted": 0,
            "all_probe_writes_below": str(run_dir),
        },
    }

    report_path = run_dir / "checkpoint_serialization_profile.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    lines = [
        "=" * 74,
        "PROFILE SUMMARY",
        "=" * 74,
        f"Source unchanged: {'YES' if source_unchanged else 'NO'}",
        f"Source load: {source_load_s:.3f}s",
        f"Runtime graph current: {graph_current}",
        "",
        "Isolated median times:",
    ]
    for name, summary in stage_summary.items():
        median = summary["median_s"]
        lines.append(f"  {name:<34} {median:.3f}s" if median is not None else f"  {name:<34} n/a")

    lines.extend([
        "",
        "End-to-end save probes:",
        f"  baseline copy + semantic reload: {baseline_elapsed:.3f}s",
        f"  no-copy + semantic reload:       {nocopy_elapsed:.3f}s",
    ])
    if byte_elapsed is not None:
        lines.append(f"  no-copy + byte verification:     {byte_elapsed:.3f}s")
    if repeat_elapsed is not None:
        lines.append(f"  repeated + existing evidence:    {repeat_elapsed:.3f}s")

    copy_cmp = conclusions["copy_payload_savings"]
    if copy_cmp["percent_saved"] is not None:
        lines.append(
            f"  no-copy savings:                 {copy_cmp['percent_saved']:.1f}% "
            f"({copy_cmp['speedup_x']:.2f}x)"
        )
    byte_cmp = conclusions["byte_verification_savings_vs_baseline"]
    if byte_cmp["percent_saved"] is not None:
        lines.append(
            f"  byte-verify savings:             {byte_cmp['percent_saved']:.1f}% "
            f"({byte_cmp['speedup_x']:.2f}x)"
        )
    evidence_cmp = conclusions["existing_evidence_savings_vs_baseline"]
    if evidence_cmp["percent_saved"] is not None:
        lines.append(
            f"  existing-evidence savings:       {evidence_cmp['percent_saved']:.1f}% "
            f"({evidence_cmp['speedup_x']:.2f}x)"
        )

    lines.extend([
        "",
        f"JSON report: {report_path}",
    ])
    if cprofile_report:
        lines.append(f"cProfile:    {run_dir / 'cprofile_top60.txt'}")
    lines.append("=" * 74)

    summary_text = "\n".join(lines) + "\n"
    (run_dir / "checkpoint_serialization_profile_summary.txt").write_text(
        summary_text, encoding="utf-8"
    )
    print()
    print(summary_text)

    if not source_unchanged:
        print("ERROR: source checkpoint metadata/hash changed during profiling.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
