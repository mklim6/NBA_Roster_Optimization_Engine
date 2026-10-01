from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import run_franchise_v2_roster_lifecycle_trace_v1 as trace_api

VERSION = "franchise-v2-deep-season-performance-profile-v1-2026-09-28"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "v2_deep_season_performance_profile_v1"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_path(value: str) -> str:
    try:
        return str(Path(value).resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(value)


def row_from_stat(key: tuple[str, int, str], value: tuple[Any, ...]) -> dict[str, Any]:
    filename, line, funcname = key
    cc, nc, tt, ct, callers = value
    return {
        "file": clean_path(filename),
        "line": int(line),
        "function": str(funcname),
        "primitive_calls": int(cc),
        "total_calls": int(nc),
        "self_time_s": float(tt),
        "cumulative_time_s": float(ct),
        "self_ms_per_call": (float(tt) * 1000.0 / nc) if nc else None,
        "cumulative_ms_per_call": (float(ct) * 1000.0 / nc) if nc else None,
    }


def category(row: dict[str, Any]) -> str:
    text = (
        f"{row['file']} {row['function']}"
    ).lower()

    if any(
        token in text
        for token in (
            "simulation_franchise_checkpoint",
            "save_franchise_checkpoint",
            "load_franchise_checkpoint",
            "load_checkpoint_path",
            "encode_checkpoint",
            "decode_checkpoint",
            "checkpoint",
            "cloudpickle",
            "pickle",
            "gzip",
            "deepcopy",
        )
    ):
        return "checkpoint_persistence"

    if any(
        token in text
        for token in (
            "free_agency",
            "free agency",
            "cpu_fa",
            "market",
            "offer_board",
            "offer_generation",
            "player_decision",
            "live_signing",
            "rights_lifecycle",
            "offer_sheet",
        )
    ):
        return "free_agency"

    if any(
        token in text
        for token in (
            "draft",
            "roster_trim",
            "post_draft",
            "rookie",
        )
    ):
        return "draft_trim"

    if any(
        token in text
        for token in (
            "season_transition",
            "season_boundary",
            "career_lifecycle",
            "contract_closeout",
            "retirement",
            "development",
        )
    ):
        return "season_transition"

    if any(
        token in text
        for token in (
            "regular_season",
            "game_sim",
            "simulation_game",
            "postseason",
            "playoff",
        )
    ):
        return "game_simulation"

    return "other"


def write_rankings(
    stats: pstats.Stats,
    out_dir: Path,
    *,
    top_n: int,
) -> dict[str, Any]:
    rows = [
        row_from_stat(key, value)
        for key, value in stats.stats.items()
    ]

    by_cumulative = sorted(
        rows,
        key=lambda row: row["cumulative_time_s"],
        reverse=True,
    )
    by_self = sorted(
        rows,
        key=lambda row: row["self_time_s"],
        reverse=True,
    )

    categorized: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        categorized.setdefault(category(row), []).append(row)

    for key in categorized:
        categorized[key] = sorted(
            categorized[key],
            key=lambda row: row["cumulative_time_s"],
            reverse=True,
        )

    report = {
        "top_cumulative": by_cumulative[:top_n],
        "top_self": by_self[:top_n],
        "categories": {
            key: value[:top_n]
            for key, value in categorized.items()
        },
    }

    (out_dir / "deep_season_profile_rankings.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("=" * 110)
    lines.append("DEEP-SEASON PROFILE RANKINGS")
    lines.append("=" * 110)

    def section(title: str, data: list[dict[str, Any]], limit: int = 35) -> None:
        lines.append("")
        lines.append(title)
        lines.append("-" * len(title))
        lines.append(
            f"{'cum(s)':>10} {'self(s)':>10} {'calls':>10}  function"
        )
        for row in data[:limit]:
            lines.append(
                f"{row['cumulative_time_s']:10.3f} "
                f"{row['self_time_s']:10.3f} "
                f"{row['total_calls']:10d}  "
                f"{row['file']}:{row['line']}::{row['function']}"
            )

    section("TOP CUMULATIVE TIME", by_cumulative)
    section("TOP SELF TIME", by_self)

    friendly = [
        ("checkpoint_persistence", "CHECKPOINT / PERSISTENCE"),
        ("free_agency", "FREE AGENCY"),
        ("draft_trim", "DRAFT / POST-DRAFT TRIM"),
        ("season_transition", "SEASON TRANSITION / LIFECYCLE"),
        ("game_simulation", "GAME / POSTSEASON SIMULATION"),
    ]
    for key, title in friendly:
        section(title, categorized.get(key, []), limit=25)

    text = "\n".join(lines) + "\n"
    (out_dir / "deep_season_profile_rankings.txt").write_text(
        text,
        encoding="utf-8",
    )
    return report


def likely_bottlenecks(rankings: dict[str, Any]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    # Favor project code over stdlib/framework internals, while still keeping
    # major serialization functions when they genuinely dominate.
    for row in rankings["top_cumulative"]:
        file_text = str(row["file"]).lower()
        project_like = (
            file_text.startswith("src")
            or "franchise_" in file_text
            or "simulation_" in file_text
            or "run_franchise_" in file_text
        )
        important_external = any(
            token in file_text
            for token in ("pickle", "cloudpickle", "gzip", "copy.py")
        )
        if not (project_like or important_external):
            continue

        key = (row["file"], row["line"], row["function"])
        if key in seen:
            continue
        seen.add(key)
        chosen.append(row)
        if len(chosen) >= 15:
            break

    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Profile a protected multi-season V2 lifecycle run and rank the "
            "post-fastpath performance bottlenecks without mutating the active save."
        )
    )
    parser.add_argument(
        "--seasons",
        type=int,
        default=8,
        help="Protected seasons to profile. Default: 8.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="Functions retained in each machine-readable ranking. Default: 100.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    args = parser.parse_args()

    if not 1 <= args.seasons <= 10:
        raise SystemExit("--seasons must be between 1 and 10.")

    run_dir = args.output_root / f"profile_{stamp()}"
    trace_dir = run_dir / "trace"
    run_dir.mkdir(parents=True, exist_ok=False)

    print("=" * 86)
    print("FRANCHISE V2 DEEP-SEASON PERFORMANCE PROFILE V1")
    print("=" * 86)
    print(f"Version: {VERSION}")
    print(f"Project: {ROOT}")
    print(f"Seasons: {args.seasons}")
    print(f"Output:  {run_dir}")
    print("Execution target: isolated protected checkpoint")
    print("Active franchise mutation: FORBIDDEN")
    print()

    profile = cProfile.Profile()
    started = time.perf_counter()
    trace_summary: dict[str, Any] = {}
    error = ""

    try:
        profile.enable()
        trace_summary = trace_api.run_trace(
            seasons=args.seasons,
            target_min=trace_api.DEFAULT_TARGET_MIN,
            target_max=trace_api.DEFAULT_TARGET_MAX,
            keep_soak_artifacts=False,
            output_dir=trace_dir,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        profile.disable()

    wall_s = time.perf_counter() - started

    stats_path = run_dir / "deep_season_profile.pstats"
    profile.dump_stats(str(stats_path))
    stats = pstats.Stats(profile)
    rankings = write_rankings(stats, run_dir, top_n=args.top)
    bottlenecks = likely_bottlenecks(rankings)

    passed = bool(
        not error
        and trace_summary
        and trace_summary.get("trace_passed")
        and trace_summary.get("active_checkpoint_family_unchanged")
    )

    report = {
        "version": VERSION,
        "generated_at_utc": utc_now(),
        "seasons": args.seasons,
        "wall_time_s": wall_s,
        "error": error,
        "trace_passed": bool(trace_summary.get("trace_passed")),
        "active_checkpoint_family_unchanged": bool(
            trace_summary.get("active_checkpoint_family_unchanged")
        ),
        "profile_passed": passed,
        "trace_output": str(trace_summary.get("output_dir", trace_dir)),
        "likely_project_bottlenecks": bottlenecks,
        "category_top5": {
            key: values[:5]
            for key, values in rankings.get("categories", {}).items()
            if key != "other"
        },
    }

    json_path = run_dir / "deep_season_performance_profile_summary.json"
    json_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print()
    print("=" * 86)
    print("PROFILE SUMMARY")
    print("=" * 86)
    print(f"Wall time: {wall_s:.3f}s")
    print(
        "Active checkpoint unchanged: "
        + ("YES" if report["active_checkpoint_family_unchanged"] else "NO")
    )
    print("Trace passed: " + ("YES" if report["trace_passed"] else "NO"))
    if error:
        print(f"Error: {error}")

    print()
    print("LIKELY PROJECT BOTTLENECKS")
    for index, row in enumerate(bottlenecks[:12], start=1):
        print(
            f"  {index:>2}. {row['cumulative_time_s']:8.3f}s cumulative | "
            f"{row['self_time_s']:8.3f}s self | "
            f"{row['total_calls']:>8} calls | "
            f"{row['file']}:{row['line']}::{row['function']}"
        )

    print()
    print("Artifacts:")
    print(f"  {stats_path}")
    print(f"  {run_dir / 'deep_season_profile_rankings.txt'}")
    print(f"  {run_dir / 'deep_season_profile_rankings.json'}")
    print(f"  {json_path}")
    print("=" * 86)

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
