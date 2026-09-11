from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import simulation_franchise_checkpoint_v1 as checkpoint_api

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "franchise_checkpoint_explicit_replace_hotfix_v1_validation.json"
VERSION = "franchise-checkpoint-explicit-replace-hotfix-v1.0-2026-09-09"


def _state(*, phase: str, completed: int, champion: str = ""):
    return SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        season_transition_count=0,
        phase=phase,
        completed_games={index: True for index in range(completed)},
        postseason_state=SimpleNamespace(
            stage="complete" if champion else "not_started",
            completed_games={index: True for index in range(88)} if champion else {},
            champion=champion,
        ),
    )


def main() -> int:
    checks = {}
    signature = inspect.signature(checkpoint_api.save_franchise_checkpoint)
    checks["checkpoint_api_exposes_force_replace"] = "force_replace" in signature.parameters
    checks["checkpoint_implementation_is_v1_3"] = (
        checkpoint_api.CHECKPOINT_IMPLEMENTATION_VERSION
        == "simulation-franchise-checkpoint-v1.3-2026-09-09"
    )

    with tempfile.TemporaryDirectory(prefix="checkpoint_replace_hotfix_") as directory:
        path = Path(directory) / "checkpoint.pkl.gz"
        advanced = _state(phase="offseason", completed=1230, champion="CHI")
        earlier = _state(phase="offseason", completed=0)

        checkpoint_api.save_franchise_checkpoint(
            advanced,
            {"revision": 1},
            reason="advanced",
            path=path,
            copy_payload=False,
        )
        stale_result = checkpoint_api.save_franchise_checkpoint(
            earlier,
            {"revision": 2},
            reason="ordinary-regression",
            path=path,
            copy_payload=False,
        )
        stale_loaded = checkpoint_api.load_franchise_checkpoint(path=path, allow_backup=False)
        checks["ordinary_stale_guard_is_preserved"] = (
            stale_result.reason == "advanced"
            and stale_loaded is not None
            and stale_loaded.reason == "advanced"
            and stale_loaded.trade_state.get("revision") == 1
        )

        forced_result = checkpoint_api.save_franchise_checkpoint(
            earlier,
            {"revision": 3},
            reason="explicit-universe-replace",
            path=path,
            copy_payload=False,
            force_replace=True,
        )
        forced_loaded = checkpoint_api.load_franchise_checkpoint(path=path, allow_backup=False)
        checks["explicit_replace_bypasses_only_progress_guard"] = (
            forced_result.reason == "explicit-universe-replace"
            and forced_loaded is not None
            and forced_loaded.reason == "explicit-universe-replace"
            and forced_loaded.trade_state.get("revision") == 3
            and not forced_loaded.simulation_state.completed_games
        )

    live_text = (ROOT / "src" / "franchise_live_start_v1.py").read_text(encoding="utf-8")
    reset_text = (ROOT / "src" / "franchise_full_reset_v1.py").read_text(encoding="utf-8")
    checks["live_start_uses_explicit_replace"] = (
        'reason="new-live-franchise-start-2026-09-07"' in live_text
        and "force_replace=True" in live_text
    )
    checks["full_reset_uses_explicit_replace"] = (
        'reason="new-franchise-reset-v1"' in reset_text
        and "force_replace=True" in reset_text
    )

    self_test = checkpoint_api.run_self_test()
    checks["checkpoint_self_test_passes"] = bool(self_test.get("passed"))
    checks["checkpoint_self_test_covers_explicit_replace"] = bool(
        self_test.get("checks", {}).get("explicit_universe_replace_can_regress_same_season")
    )

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError("Explicit replace hotfix validation failed: " + ", ".join(failed))
    print("\nFRANCHISE CHECKPOINT EXPLICIT REPLACE HOTFIX V1 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
