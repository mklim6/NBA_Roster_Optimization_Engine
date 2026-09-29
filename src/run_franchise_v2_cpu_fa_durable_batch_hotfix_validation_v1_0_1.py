from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_franchise_checkpoint_v1 as checkpoint_api
import run_franchise_v2_roster_lifecycle_trace_v1 as trace_api

VERSION = "franchise-v2-cpu-fa-durable-batch-hotfix-runtime-v1.0.1-2026-09-28"
OUTPUT_ROOT = ROOT / "outputs" / "v2_cpu_fa_durable_batch_hotfix_v1_0_1"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def main() -> int:
    out_dir = OUTPUT_ROOT / f"validation_{stamp()}"
    trace_dir = out_dir / "trace"
    out_dir.mkdir(parents=True, exist_ok=False)

    original_save = checkpoint_api.save_franchise_checkpoint
    reasons: list[str] = []

    def traced_save(*args: Any, **kwargs: Any) -> Any:
        reasons.append(str(kwargs.get("reason", "") or ""))
        return original_save(*args, **kwargs)

    checkpoint_api.save_franchise_checkpoint = traced_save
    raised_error = ""
    summary: dict[str, Any] = {}
    try:
        summary = trace_api.run_trace(
            seasons=1,
            target_min=trace_api.DEFAULT_TARGET_MIN,
            target_max=trace_api.DEFAULT_TARGET_MAX,
            keep_soak_artifacts=False,
            output_dir=trace_dir,
        )
    except Exception as exc:
        raised_error = f"{type(exc).__name__}: {exc}"
    finally:
        checkpoint_api.save_franchise_checkpoint = original_save

    soak = dict(summary.get("soak_summary") or {})
    returned_error = str(
        summary.get("run_error")
        or soak.get("error")
        or ""
    )
    error = raised_error or returned_error

    batch_reasons = [
        value for value in reasons
        if value.startswith("free-agency-cpu-round-batch-")
    ]
    individual_cpu_reasons = [
        value for value in reasons
        if value.startswith("free-agency-cpu-signing-")
    ]

    report = {
        "version": VERSION,
        "trace_passed": bool(summary.get("trace_passed")),
        "active_checkpoint_unchanged": bool(
            summary.get("active_checkpoint_family_unchanged")
        ),
        "error": error,
        "soak_summary": soak,
        "total_checkpoint_saves_observed": len(reasons),
        "cpu_fa_batch_saves": len(batch_reasons),
        "cpu_fa_individual_signing_saves": len(individual_cpu_reasons),
        "cpu_fa_batch_reasons": batch_reasons,
        "all_save_reasons": reasons,
        "trace_output": str(summary.get("output_dir", trace_dir)),
    }
    report["passed"] = bool(
        not error
        and report["trace_passed"]
        and report["active_checkpoint_unchanged"]
        and report["cpu_fa_batch_saves"] > 0
        and report["cpu_fa_individual_signing_saves"] == 0
    )

    report_path = out_dir / "cpu_fa_durable_batch_hotfix_validation.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 88)
    print("FRANCHISE V2 CPU FA DURABLE BATCH HOTFIX V1.0.1 RUNTIME VALIDATION")
    print("=" * 88)
    print(f"Trace passed: {'YES' if report['trace_passed'] else 'NO'}")
    print(
        "Active checkpoint unchanged: "
        + ("YES" if report["active_checkpoint_unchanged"] else "NO")
    )
    print(f"Total checkpoint saves observed: {report['total_checkpoint_saves_observed']}")
    print(f"CPU FA durable batch saves:      {report['cpu_fa_batch_saves']}")
    print(f"CPU FA per-signing saves:        {report['cpu_fa_individual_signing_saves']}")
    if error:
        print(f"TRACE ERROR: {error}")
    print("Batch save reasons:")
    for reason in batch_reasons:
        print(f"  - {reason}")
    print(f"Report: {report_path}")
    print("=" * 88)

    if report["passed"]:
        print("CPU FA DURABLE BATCH HOTFIX RUNTIME VALIDATION PASSED")
        return 0

    print("CPU FA DURABLE BATCH HOTFIX RUNTIME VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
