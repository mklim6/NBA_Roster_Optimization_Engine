from __future__ import annotations

import argparse
import csv
import functools
import importlib
import json
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_ROOT = ROOT / "outputs" / "v2_phase1_fa_performance_profile_v1"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import run_franchise_v2_protected_multi_season_soak_v1 as v2_soak


VERSION = "franchise-v2-phase1-fa-performance-profiler-v1-2026-09-24"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _season_from_object(value: Any) -> str:
    if value is None:
        return ""

    settings = getattr(value, "settings", None)
    season = _clean(getattr(settings, "season_label", ""))
    if season:
        return season

    simulation_state = getattr(value, "simulation_state", None)
    if simulation_state is not None and simulation_state is not value:
        season = _season_from_object(simulation_state)
        if season:
            return season

    checkpoint = getattr(value, "checkpoint", None)
    if checkpoint is not None and checkpoint is not value:
        season = _season_from_object(checkpoint)
        if season:
            return season

    return ""


def _extract_season(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    for value in args:
        season = _season_from_object(value)
        if season:
            return season
    for key in ("state", "checkpoint", "_checkpoint"):
        season = _season_from_object(kwargs.get(key))
        if season:
            return season
    return ""


class TargetedProfiler:
    def __init__(self, *, slow_call_seconds: float = 5.0) -> None:
        self.slow_call_seconds = float(slow_call_seconds)
        self.events: list[dict[str, Any]] = []
        self.stats: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
            lambda: {
                "calls": 0,
                "wall_seconds": 0.0,
                "cpu_seconds": 0.0,
                "max_wall_seconds": 0.0,
                "max_cpu_seconds": 0.0,
            }
        )
        self._originals: list[tuple[Any, str, Any]] = []
        self._event_index = 0

    def wrap(self, module: Any, attribute: str, label: str | None = None) -> bool:
        fn = getattr(module, attribute, None)
        if not callable(fn):
            return False

        if getattr(fn, "__v2_profile_wrapped__", False):
            return False

        resolved_label = label or f"{module.__name__}.{attribute}"
        profiler = self

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            season = _extract_season(args, kwargs)
            wall0 = time.perf_counter()
            cpu0 = time.process_time()
            status = "ok"
            exc_name = ""
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:
                status = "error"
                exc_name = type(exc).__name__
                raise
            finally:
                wall = time.perf_counter() - wall0
                cpu = time.process_time() - cpu0
                profiler._event_index += 1
                event = {
                    "event_index": profiler._event_index,
                    "label": resolved_label,
                    "season": season,
                    "wall_seconds": round(wall, 6),
                    "cpu_seconds": round(cpu, 6),
                    "status": status,
                    "exception_type": exc_name,
                }
                profiler.events.append(event)

                stat = profiler.stats[(resolved_label, season)]
                stat["calls"] = int(stat["calls"]) + 1
                stat["wall_seconds"] = float(stat["wall_seconds"]) + wall
                stat["cpu_seconds"] = float(stat["cpu_seconds"]) + cpu
                stat["max_wall_seconds"] = max(
                    float(stat["max_wall_seconds"]), wall
                )
                stat["max_cpu_seconds"] = max(
                    float(stat["max_cpu_seconds"]), cpu
                )

                if wall >= profiler.slow_call_seconds:
                    ratio = (cpu / wall) if wall > 0 else 0.0
                    print(
                        f"[PROFILE SLOW] {resolved_label} "
                        f"season={season or '?'} "
                        f"wall={wall:.2f}s cpu={cpu:.2f}s "
                        f"cpu/wall={ratio:.2f}"
                    )

        wrapped.__v2_profile_wrapped__ = True
        self._originals.append((module, attribute, fn))
        setattr(module, attribute, wrapped)
        return True

    def restore(self) -> None:
        for module, attribute, original in reversed(self._originals):
            setattr(module, attribute, original)
        self._originals.clear()

    def summary_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (label, season), values in self.stats.items():
            calls = int(values["calls"])
            wall = float(values["wall_seconds"])
            cpu = float(values["cpu_seconds"])
            rows.append(
                {
                    "label": label,
                    "season": season,
                    "calls": calls,
                    "wall_seconds": round(wall, 6),
                    "cpu_seconds": round(cpu, 6),
                    "avg_wall_seconds": round(wall / calls, 6) if calls else 0.0,
                    "avg_cpu_seconds": round(cpu / calls, 6) if calls else 0.0,
                    "max_wall_seconds": round(
                        float(values["max_wall_seconds"]), 6
                    ),
                    "max_cpu_seconds": round(
                        float(values["max_cpu_seconds"]), 6
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                -float(row["cpu_seconds"]),
                -float(row["wall_seconds"]),
                row["label"],
                row["season"],
            )
        )
        return rows


def _import_optional(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def _install_targets(profiler: TargetedProfiler) -> list[str]:
    installed: list[str] = []

    modules: dict[str, Any | None] = {
        "execution": _import_optional("franchise_free_agency_cpu_execution_v1"),
        "offers": _import_optional("franchise_free_agency_cpu_offer_generation_v1"),
        "rights": _import_optional("franchise_free_agency_rights_exceptions_v1"),
        "rights_population": _import_optional(
            "franchise_free_agency_rights_population_v1"
        ),
        "salary": _import_optional(
            "franchise_free_agency_contract_salary_legality_v1_3"
        ),
        "minimum": _import_optional(
            "franchise_free_agency_cpu_minimum_exception_targeting_v1"
        ),
        "financial": _import_optional(
            "franchise_free_agency_financial_bridge_v1_2"
        ),
        "front_office": _import_optional("franchise_cpu_front_office_v1"),
    }

    target_map: dict[str, tuple[str, ...]] = {
        "execution": (
            "execute_cpu_free_agency_round_durably",
            "execute_next_cpu_free_agency_signing_durably",
            "build_cpu_free_agency_execution_plan",
            "build_cpu_free_agency_offer_board",
            "build_cpu_competing_markets",
            "build_cpu_roster_floor_rescue_opportunity",
            "build_cpu_sustainable_roster_completion_opportunity",
            "_rescue_offer_and_decision",
            "free_agency_state_fingerprint",
        ),
        "offers": (
            "build_cpu_free_agency_offer_board",
            "build_cpu_competing_markets",
            "_front_office_plan_from_runtime",
            "resolve_free_agency_rights",
            "resolve_prior_team_exception_route",
            "build_rights_exception_free_agency_preview",
            "evaluate_minimum_exception_targeting",
            "evaluate_roster_construction_target",
            "evaluate_roster_construction_offer",
            "evaluate_cpu_offer_economic_intelligence",
            "team_guaranteed_payroll",
            "market_salary_reference",
            "free_agency_state_fingerprint",
            "resolve_years_of_service_for_state",
            "minimum_salary_floor_for_state",
        ),
        "rights": (
            "rights_registry_from_state",
            "rights_registry_fingerprint",
            "resolve_free_agency_rights",
            "resolve_prior_team_exception_route",
            "_minimum_exception_gate",
            "evaluate_rights_exception_financial_gate",
            "build_rights_exception_free_agency_preview",
            "resolve_years_of_service_for_state",
            "minimum_salary_floor_for_state",
        ),
        "rights_population": (
            "load_overlay_for_state",
        ),
        "salary": (
            "resolve_years_of_service_for_state",
            "_v2_baseline_career_seasons_by_player",
            "minimum_salary_floor_for_state",
            "maximum_initial_salary_for_state",
            "evaluate_contract_salary_legality",
        ),
        "minimum": (
            "evaluate_minimum_exception_targeting",
        ),
        "financial": (
            "resolve_free_agency_financial_environment",
        ),
        "front_office": (
            "build_league_front_office_plan",
        ),
    }

    for key, attributes in target_map.items():
        module = modules.get(key)
        if module is None:
            continue
        for attribute in attributes:
            label = f"{module.__name__}.{attribute}"
            if profiler.wrap(module, attribute, label):
                installed.append(label)

    return installed


def _write_outputs(
    profiler: TargetedProfiler,
    output_dir: Path,
    *,
    report: dict[str, Any] | None,
    run_error: str,
    wall_seconds: float,
    cpu_seconds: float,
    installed_targets: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    events_path = output_dir / "fa_profile_events.csv"
    with events_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "event_index",
            "label",
            "season",
            "wall_seconds",
            "cpu_seconds",
            "status",
            "exception_type",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(profiler.events)

    rows = profiler.summary_rows()
    summary_path = output_dir / "fa_profile_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "label",
            "season",
            "calls",
            "wall_seconds",
            "cpu_seconds",
            "avg_wall_seconds",
            "avg_cpu_seconds",
            "max_wall_seconds",
            "max_cpu_seconds",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    payload = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(wall_seconds, 6),
        "cpu_seconds": round(cpu_seconds, 6),
        "wall_includes_sleep_or_suspension": True,
        "cpu_seconds_excludes_sleep_and_is_primary_for_hotspot_ranking": True,
        "installed_target_count": len(installed_targets),
        "installed_targets": installed_targets,
        "run_error": run_error,
        "soak_report": report,
        "top_cpu_hotspots": rows[:25],
    }
    (output_dir / "fa_profile_report.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seasons",
        type=int,
        default=3,
        help="Protected seasons to run. Three reaches the first observed deep-FA slowdown.",
    )
    parser.add_argument(
        "--slow-call-seconds",
        type=float,
        default=5.0,
        help="Print any profiled call whose wall time exceeds this threshold.",
    )
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    if args.seasons < 1 or args.seasons > v2_soak.soak.MAX_SEASONS:
        raise SystemExit(
            f"--seasons must be between 1 and {v2_soak.soak.MAX_SEASONS}."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = OUTPUT_ROOT / f"profile_{stamp}"

    profiler = TargetedProfiler(
        slow_call_seconds=max(0.0, args.slow_call_seconds)
    )
    installed = _install_targets(profiler)

    print("FRANCHISE V2 PHASE 1 FA PERFORMANCE PROFILER V1")
    print(f"Project root: {ROOT}")
    print(f"Protected seasons: {args.seasons}")
    print(f"Profile targets installed: {len(installed)}")
    print("Active franchise mutation: FORBIDDEN")
    print(
        "IMPORTANT: wall time can include computer sleep; "
        "CPU time does not and is the primary optimization signal."
    )
    print(
        "You may press Ctrl+C during a very slow FA stage. "
        "Partial profile files will still be written."
    )
    print()

    original_freeze = v2_soak.soak._validate_release_freeze
    wall0 = time.perf_counter()
    cpu0 = time.process_time()
    report: dict[str, Any] | None = None
    run_error = ""
    exit_code = 0

    try:
        v2_soak.soak._validate_release_freeze = v2_soak._v2_provenance_preflight
        report = v2_soak.soak.run_soak(
            seasons=args.seasons,
            keep_artifacts=args.keep_artifacts,
        )
        if not report.get("passed"):
            exit_code = 1
    except KeyboardInterrupt:
        run_error = "KeyboardInterrupt"
        exit_code = 130
        print()
        print("Profiler interrupted by user. Saving partial profile...")
    except BaseException as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        exit_code = 1
        traceback.print_exc()
    finally:
        wall = time.perf_counter() - wall0
        cpu = time.process_time() - cpu0
        v2_soak.soak._validate_release_freeze = original_freeze
        profiler.restore()
        _write_outputs(
            profiler,
            output_dir,
            report=report,
            run_error=run_error,
            wall_seconds=wall,
            cpu_seconds=cpu,
            installed_targets=installed,
        )

    print()
    print("PROFILE SUMMARY")
    print(f"Wall elapsed: {wall:.2f}s")
    print(f"Python CPU time: {cpu:.2f}s")
    print(f"Output: {output_dir}")
    print()
    print("TOP CPU HOTSPOTS")
    for row in profiler.summary_rows()[:15]:
        print(
            f"  {row['cpu_seconds']:10.2f}s CPU | "
            f"{row['wall_seconds']:10.2f}s wall | "
            f"{row['calls']:7d} calls | "
            f"{row['season'] or '?':8s} | "
            f"{row['label']}"
        )

    if report is not None:
        print()
        print(
            f"Completed seasons: {report.get('completed_seasons', 0)}/"
            f"{report.get('requested_seasons', args.seasons)}"
        )
        print(
            "Protected soak result: "
            + ("PASS" if report.get("passed") else "FAIL")
        )

    if run_error:
        print(f"Run status: {run_error}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
