from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT_DIR = ROOT / "outputs" / "v2_release_candidate_gate_v2"
REPORT_JSON = OUTPUT_DIR / "latest_report.json"
REPORT_TXT = OUTPUT_DIR / "latest_summary.txt"
VERSION = "franchise-v2-release-candidate-gate-v2-2026-09-30"


@dataclass(frozen=True)
class Stage:
    key: str
    filename: str
    group: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageResult:
    key: str
    filename: str
    group: str
    command: tuple[str, ...]
    exists: bool
    passed: bool
    returncode: int
    duration_seconds: float
    stdout_tail: tuple[str, ...]
    stderr_tail: tuple[str, ...]


STATIC_STAGES = (
    Stage(
        "v2_validator_consolidation",
        "validate_franchise_v2_validator_consolidation_v1.py",
        "static",
    ),
    Stage(
        "player_population_ecology_static",
        "validate_franchise_v2_player_population_ecology_v1.py",
        "static",
    ),
    Stage(
        "user_two_way_management_static",
        "validate_franchise_v2_user_two_way_management_v1.py",
        "static",
    ),
    Stage(
        "what_if_removal_static",
        "validate_franchise_v2_what_if_lab_removal_v1.py",
        "static",
    ),
    Stage(
        "coaching_roles_static",
        "validate_franchise_v2_coaching_roles_injury_rotation_v1.py",
        "static",
    ),
    Stage(
        "coaching_workload_static",
        "validate_franchise_v2_coaching_workload_redistribution_v1.py",
        "static",
    ),
    Stage(
        "coaching_matchup_static",
        "validate_franchise_v2_coaching_matchup_tactics_v1.py",
        "static",
    ),
    Stage(
        "coaching_identity_game_day_static",
        "validate_franchise_v2_coaching_identity_game_day_v1.py",
        "static",
    ),
    Stage(
        "coaching_counterfactual_static",
        "validate_franchise_v2_coaching_counterfactual_audit_v1.py",
        "static",
    ),
    Stage(
        "saved_rotation_minutes",
        "validate_saved_rotation_minutes_v1.py",
        "static",
    ),
    Stage(
        "command_center",
        "validate_franchise_command_center_v1.py",
        "static",
    ),
    Stage(
        "health_game_day",
        "validate_franchise_health_game_day_repair_v1.py",
        "static",
    ),
    Stage(
        "postseason",
        "validate_simulation_postseason_v1.py",
        "static",
    ),
    Stage(
        "cpu_autonomous_trade_market",
        "validate_franchise_cpu_autonomous_trade_market_v6a.py",
        "static",
    ),
    Stage(
        "cpu_incoming_trade_offers",
        "validate_franchise_cpu_incoming_trade_offers_v6b.py",
        "static",
    ),
    Stage(
        "game_day_league_calendar_sync",
        "validate_franchise_game_day_league_calendar_sync_v1.py",
        "static",
    ),
    Stage(
        "postgame_offer_hotfix",
        "validate_franchise_postgame_performance_offer_hotfix_v6_0_1.py",
        "static",
    ),
)

PROTECTED_RUNTIME_STAGES = (
    Stage(
        "player_population_ecology_runtime",
        "run_franchise_v2_player_population_ecology_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "user_two_way_management_runtime",
        "run_franchise_v2_user_two_way_management_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "coaching_roles_runtime",
        "run_franchise_v2_coaching_roles_injury_rotation_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "coaching_workload_runtime",
        "run_franchise_v2_coaching_workload_redistribution_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "coaching_matchup_runtime",
        "run_franchise_v2_coaching_matchup_tactics_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "coaching_identity_game_day_runtime",
        "run_franchise_v2_coaching_identity_game_day_validation_v1.py",
        "protected_runtime",
    ),
    Stage(
        "coaching_counterfactual_runtime",
        "run_franchise_v2_coaching_counterfactual_audit_v1.py",
        "protected_runtime",
    ),
)

FULL_SEASON_STAGES = (
    Stage(
        "injury_fatigue_full_season",
        "validate_injury_fatigue_v1.py",
        "full_season",
    ),
    Stage(
        "franchise_simulation_realism_full_season",
        "validate_franchise_simulation_realism_v1.py",
        "full_season",
    ),
)

DEEP_STAGES = (
    Stage(
        "roster_lifecycle_trace_8_seasons",
        "run_franchise_v2_roster_lifecycle_trace_v1.py",
        "deep",
        ("--seasons", "8"),
    ),
    Stage(
        "player_population_ecology_trace_audit",
        "audit_franchise_v2_player_population_ecology_trace_v1.py",
        "deep",
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_family(primary: Path) -> dict[str, str]:
    if not primary.parent.exists():
        return {}
    prefix = primary.name.split(".pkl", 1)[0]
    values = {}
    for candidate in sorted(primary.parent.iterdir(), key=lambda p: p.name):
        if not candidate.is_file():
            continue
        if not candidate.name.startswith(prefix):
            continue
        digest = _sha256(candidate)
        if digest is not None:
            values[candidate.name] = digest
    return values


def _tail(text: str, count: int = 22) -> tuple[str, ...]:
    return tuple(str(text or "").splitlines()[-count:])


def _run_command(
    *,
    key: str,
    filename: str,
    group: str,
    args: Iterable[str] = (),
) -> StageResult:
    path = SRC / filename
    if not path.is_file():
        print(f"[FAIL] {key}: missing {filename}")
        return StageResult(
            key=key,
            filename=filename,
            group=group,
            command=(),
            exists=False,
            passed=False,
            returncode=127,
            duration_seconds=0.0,
            stdout_tail=(),
            stderr_tail=(f"Missing required stage: {path}",),
        )

    env = os.environ.copy()
    current_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (
        os.pathsep + current_pp if current_pp else ""
    )
    command = (
        sys.executable,
        str(path),
        *(str(value) for value in args),
    )

    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
    )
    elapsed = round(time.perf_counter() - started, 3)
    passed = completed.returncode == 0
    print(
        f"[{'PASS' if passed else 'FAIL'}] "
        f"{group}: {key} ({elapsed:.3f}s)"
    )
    if not passed:
        for line in _tail(completed.stderr, 8):
            print(f"  stderr: {line}")
        for line in _tail(completed.stdout, 8):
            print(f"  stdout: {line}")

    return StageResult(
        key=key,
        filename=filename,
        group=group,
        command=tuple(command),
        exists=True,
        passed=passed,
        returncode=int(completed.returncode),
        duration_seconds=elapsed,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def _run_compileall() -> StageResult:
    command = (
        sys.executable,
        "-m",
        "compileall",
        "-q",
        str(SRC),
        str(ROOT / "pages"),
    )
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors="replace",
    )
    elapsed = round(time.perf_counter() - started, 3)
    passed = completed.returncode == 0
    print(f"[{'PASS' if passed else 'FAIL'}] compile: src_and_pages ({elapsed:.3f}s)")
    return StageResult(
        key="compile_src_and_pages",
        filename="<compileall>",
        group="compile",
        command=tuple(command),
        exists=True,
        passed=passed,
        returncode=int(completed.returncode),
        duration_seconds=elapsed,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--fast",
        action="store_true",
        help="Compile + static + protected runtime checks.",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Fast gate plus full-season injury and realism regressions.",
    )
    mode.add_argument(
        "--deep",
        action="store_true",
        help="Full gate plus protected eight-season lifecycle/population audit.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop after the first failing stage.",
    )
    args = parser.parse_args()

    selected_mode = (
        "deep" if args.deep
        else "full" if args.full
        else "fast"
    )

    try:
        import simulation_franchise_checkpoint_v1 as checkpoint_api
        checkpoint_path = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    except Exception:
        checkpoint_path = (
            ROOT
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        ).resolve()

    before = _checkpoint_family(checkpoint_path)

    print("FRANCHISE V2 RELEASE CANDIDATE GATE V2")
    print(f"Mode: {selected_mode}")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print(f"Checkpoint: {checkpoint_path}")
    print("")

    results: list[StageResult] = [_run_compileall()]

    stages = list(STATIC_STAGES) + list(PROTECTED_RUNTIME_STAGES)
    if selected_mode in {"full", "deep"}:
        stages.extend(FULL_SEASON_STAGES)
    if selected_mode == "deep":
        stages.extend(DEEP_STAGES)

    if args.stop_on_failure and not results[-1].passed:
        stages = []

    for stage in stages:
        result = _run_command(
            key=stage.key,
            filename=stage.filename,
            group=stage.group,
            args=stage.args,
        )
        results.append(result)
        if args.stop_on_failure and not result.passed:
            break

    after = _checkpoint_family(checkpoint_path)
    checkpoint_unchanged = before == after

    failed = [result.key for result in results if not result.passed]
    if not checkpoint_unchanged:
        failed.append("active_checkpoint_family_unchanged")

    group_summary: dict[str, dict[str, int]] = {}
    for result in results:
        group = group_summary.setdefault(
            result.group,
            {"passed": 0, "failed": 0, "total": 0},
        )
        group["total"] += 1
        if result.passed:
            group["passed"] += 1
        else:
            group["failed"] += 1

    report = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "mode": selected_mode,
        "project_root": str(ROOT),
        "passed": not failed,
        "failed_stages": failed,
        "group_summary": group_summary,
        "active_checkpoint": {
            "path": str(checkpoint_path),
            "family_before": before,
            "family_after": after,
            "unchanged": checkpoint_unchanged,
        },
        "results": [asdict(result) for result in results],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    lines = [
        "FRANCHISE V2 RELEASE CANDIDATE GATE V2",
        f"Mode: {selected_mode}",
        f"Passed: {'YES' if report['passed'] else 'NO'}",
        f"Checkpoint unchanged: {'YES' if checkpoint_unchanged else 'NO'}",
        "",
    ]
    for group_name, values in group_summary.items():
        lines.append(
            f"{group_name}: {values['passed']}/{values['total']} passed"
        )
    if failed:
        lines.extend(["", "Failed stages:"])
        lines.extend(f"  - {name}" for name in failed)
    REPORT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("")
    print("SUMMARY")
    for group_name, values in group_summary.items():
        print(
            f"  {group_name}: "
            f"{values['passed']}/{values['total']} passed"
        )
    print(
        "  active_checkpoint_family_unchanged: "
        f"{'PASS' if checkpoint_unchanged else 'FAIL'}"
    )
    print(f"Report: {REPORT_JSON}")

    if report["passed"]:
        print("FRANCHISE V2 RELEASE CANDIDATE GATE V2 PASSED")
        return 0

    print("FRANCHISE V2 RELEASE CANDIDATE GATE V2 FAILED")
    for name in failed:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
