from __future__ import annotations

import argparse
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

BOOTSTRAP_VERSION = (
    "simulation-module-bootstrap-v1.4-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_module_bootstrap_v1_self_test.json"
)

STATE_MODULE_NAME = "simulation_league_state_v1"
EXPECTED_MINUTES_MODEL_VERSION = (
    "simulation-player-minutes-v1-2026-08-08"
)
EXPECTED_ENGINE_VERSION = (
    "single-game-simulator-v1.6-2026-08-08"
)

REQUIRED_STATE_ATTRIBUTES = (
    "BASELINE_PER_36_FIELDS",
    "MINUTES_MODEL_VERSION",
    "SIMULATION_STATE_VERSION",
    "SimulationLeagueState",
    "create_simulation_league_state",
    "validate_simulation_league_state",
)

# Remove dependents before the foundation module so no imported controller
# retains references to a stale SimulationLeagueState class.
DEPENDENT_MODULE_RESET_ORDER = (
    "franchise_command_center_v1",
    "franchise_calendar_v1",
    "simulation_trade_sync_v1",
    "simulation_postseason_v1",
    "simulation_league_alignment_v1",
    "simulation_player_minutes_v1",
    "regular_season_simulation_controller_v1",
    "regular_season_schedule_v1",
    "simulation_season_transition_controller_v1",
    "simulation_season_transition_v1",
    "single_game_simulator_v1",
    "simulation_roster_validator_v1",
)

FULL_MODULE_RESET_ORDER = (
    *DEPENDENT_MODULE_RESET_ORDER,
    "simulation_league_state_v1",
)


class SimulationModuleBootstrapError(
    ImportError
):
    """Raised when the local simulation module chain cannot be repaired."""


def expected_state_path() -> Path:
    return (
        SRC / "simulation_league_state_v1.py"
    ).resolve()


def missing_state_attributes(
    module: Any,
) -> tuple[str, ...]:
    return tuple(
        name
        for name in REQUIRED_STATE_ATTRIBUTES
        if not hasattr(module, name)
    )


def module_path(
    module: Any,
) -> Path | None:
    value = getattr(
        module,
        "__file__",
        None,
    )

    if not value:
        return None

    try:
        return Path(value).resolve()
    except (OSError, RuntimeError, TypeError):
        return None


def state_module_is_current(
    module: Any,
) -> bool:
    return bool(
        not missing_state_attributes(module)
        and module_path(module)
        == expected_state_path()
        and getattr(
            module,
            "MINUTES_MODEL_VERSION",
            "",
        )
        == EXPECTED_MINUTES_MODEL_VERSION
    )


def purge_module_names(
    module_names: tuple[str, ...],
) -> tuple[str, ...]:
    removed: list[str] = []

    for module_name in module_names:
        if module_name in sys.modules:
            sys.modules.pop(
                module_name,
                None,
            )
            removed.append(module_name)

    importlib.invalidate_caches()
    return tuple(removed)


def purge_dependent_simulation_modules() -> tuple[str, ...]:
    return purge_module_names(
        DEPENDENT_MODULE_RESET_ORDER
    )


def purge_simulation_modules() -> tuple[
    str,
    ...,
]:
    return purge_module_names(
        FULL_MODULE_RESET_ORDER
    )


def ensure_current_simulation_modules() -> Any:
    """Return the exact current local state module and refresh dependents.

    The permanent state foundation is preserved when its contract and path
    are current. Every state-dependent controller and game engine is still
    removed from ``sys.modules`` so Streamlit cannot continue using an older
    allocator after files are replaced in place.
    """
    existing = sys.modules.get(
        STATE_MODULE_NAME
    )

    if (
        existing is not None
        and state_module_is_current(
            existing
        )
    ):
        purge_dependent_simulation_modules()
        return existing

    if existing is None:
        try:
            imported = importlib.import_module(
                STATE_MODULE_NAME
            )
        except ImportError:
            imported = None

        if (
            imported is not None
            and state_module_is_current(
                imported
            )
        ):
            purge_dependent_simulation_modules()
            return imported

    purge_simulation_modules()

    try:
        repaired = importlib.import_module(
            STATE_MODULE_NAME
        )
    except Exception as exc:
        raise SimulationModuleBootstrapError(
            "The local simulation state module "
            "could not be imported after clearing "
            "the stale module chain."
        ) from exc

    missing = missing_state_attributes(
        repaired
    )
    actual_path = module_path(repaired)
    expected_path = expected_state_path()

    if missing:
        raise SimulationModuleBootstrapError(
            "The reloaded local simulation state "
            "module is missing: "
            + ", ".join(missing)
            + f". Loaded from {actual_path}."
        )

    if actual_path != expected_path:
        raise SimulationModuleBootstrapError(
            "The simulation state module resolved "
            f"to {actual_path}, expected "
            f"{expected_path}."
        )

    purge_dependent_simulation_modules()
    return repaired


def run_self_test() -> dict[str, Any]:
    purge_simulation_modules()

    stale = types.ModuleType(
        STATE_MODULE_NAME
    )
    stale.__file__ = str(
        expected_state_path()
    )
    stale.SIMULATION_STATE_VERSION = (
        "stale-test-module"
    )
    sys.modules[
        STATE_MODULE_NAME
    ] = stale

    repaired = (
        ensure_current_simulation_modules()
    )
    repaired_missing = (
        missing_state_attributes(
            repaired
        )
    )

    transition_controller = (
        importlib.import_module(
            "simulation_season_transition_controller_v1"
        )
    )
    season_controller = (
        importlib.import_module(
            "regular_season_simulation_controller_v1"
        )
    )
    calendar_module = (
        importlib.import_module(
            "franchise_calendar_v1"
        )
    )
    alignment_module = (
        importlib.import_module(
            "simulation_league_alignment_v1"
        )
    )
    trade_sync_module = (
        importlib.import_module(
            "simulation_trade_sync_v1"
        )
    )
    postseason_module = (
        importlib.import_module(
            "simulation_postseason_v1"
        )
    )

    checks = {
        "bootstrap_version_is_current": (
            BOOTSTRAP_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "stale_module_is_replaced": (
            repaired is not stale
        ),
        "repaired_module_has_required_contract": (
            not repaired_missing
        ),
        "repaired_module_uses_exact_local_path": (
            module_path(repaired)
            == expected_state_path()
        ),
        "baseline_per_36_contract_is_present": (
            tuple(
                repaired.BASELINE_PER_36_FIELDS
            )
            == (
                "points_per_36",
                "rebounds_per_36",
                "assists_per_36",
                "steals_per_36",
                "blocks_per_36",
                "turnovers_per_36",
                "fouls_per_36",
                "three_attempts_per_36",
                "free_throw_attempts_per_36",
            )
        ),
        "historical_minutes_contract_is_present": (
            getattr(
                repaired,
                "MINUTES_MODEL_VERSION",
                "",
            )
            == EXPECTED_MINUTES_MODEL_VERSION
        ),
        "season_transition_chain_imports": (
            hasattr(
                transition_controller,
                "build_season_transition_preview",
            )
        ),
        "regular_season_chain_imports": (
            hasattr(
                season_controller,
                "simulate_regular_season_scope",
            )
        ),
        "franchise_calendar_chain_imports": (
            hasattr(
                calendar_module,
                "build_team_month_calendar",
            )
        ),
        "league_alignment_chain_imports": (
            hasattr(
                alignment_module,
                "apply_nba_team_alignment",
            )
        ),
        "trade_sync_chain_imports": (
            hasattr(
                trade_sync_module,
                "synchronize_simulation_with_trade_state",
            )
        ),
        "postseason_chain_imports": (
            hasattr(
                postseason_module,
                "initialize_postseason",
            )
            and hasattr(
                postseason_module,
                "advance_postseason",
            )
        ),
        "dependent_modules_are_refreshed_even_when_state_is_current": (
            "single_game_simulator_v1"
            in sys.modules
            and getattr(
                sys.modules[
                    "single_game_simulator_v1"
                ],
                "ENGINE_VERSION",
                "",
            )
            == EXPECTED_ENGINE_VERSION
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": BOOTSTRAP_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "expected_state_path": str(
                expected_state_path()
            ),
            "actual_state_path": str(
                module_path(repaired)
            ),
            "state_version": getattr(
                repaired,
                "SIMULATION_STATE_VERSION",
                "",
            ),
            "required_attributes": list(
                REQUIRED_STATE_ATTRIBUTES
            ),
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Simulation module bootstrap "
            "self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION MODULE BOOTSTRAP "
            "V1 SELF-TEST PASSED"
        )
        return 0

    module = (
        ensure_current_simulation_modules()
    )
    print(
        json.dumps(
            {
                "script": BOOTSTRAP_VERSION,
                "state_module": str(
                    module_path(module)
                ),
                "state_version": getattr(
                    module,
                    "SIMULATION_STATE_VERSION",
                    "",
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
