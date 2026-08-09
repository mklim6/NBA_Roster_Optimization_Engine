from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, MutableMapping


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

CROSS_PAGE_STATE_VERSION = (
    "simulation-cross-page-state-v1.1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_cross_page_state_v1_self_test.json"
)


@dataclass(frozen=True)
class TradeStateDescriptor:
    state_version: str
    state_revision: int
    transaction_count: int


@dataclass(frozen=True)
class SimulationSourceStatus:
    version: str
    trade_descriptor: TradeStateDescriptor
    simulation_revision: int
    simulation_transaction_count: int
    matches: bool


class CrossPageStateError(RuntimeError):
    """Raised when a shared session-state contract is unusable."""


def trade_state_is_compatible(
    trade_state: Any,
    *,
    expected_state_version: str | None = None,
) -> bool:
    if trade_state is None:
        return False

    required = (
        "state_version",
        "state_revision",
        "transaction_history",
    )

    if not all(
        hasattr(trade_state, name)
        for name in required
    ):
        return False

    if (
        expected_state_version is not None
        and str(
            trade_state.state_version
        )
        != str(expected_state_version)
    ):
        return False

    try:
        int(trade_state.state_revision)
        len(trade_state.transaction_history)
    except (TypeError, ValueError):
        return False

    return True


def describe_trade_state(
    trade_state: Any,
) -> TradeStateDescriptor:
    if not trade_state_is_compatible(
        trade_state
    ):
        raise CrossPageStateError(
            "The trade league state does not expose "
            "the required stable revision contract."
        )

    return TradeStateDescriptor(
        state_version=str(
            trade_state.state_version
        ),
        state_revision=int(
            trade_state.state_revision
        ),
        transaction_count=len(
            trade_state.transaction_history
        ),
    )


def simulation_source_status(
    simulation_state: Any,
    trade_state: Any,
) -> SimulationSourceStatus:
    descriptor = describe_trade_state(
        trade_state
    )
    simulation_revision = int(
        getattr(
            simulation_state,
            "source_league_state_revision",
            -1,
        )
    )
    simulation_transaction_count = int(
        getattr(
            simulation_state,
            "source_transaction_count",
            -1,
        )
    )

    return SimulationSourceStatus(
        version=CROSS_PAGE_STATE_VERSION,
        trade_descriptor=descriptor,
        simulation_revision=(
            simulation_revision
        ),
        simulation_transaction_count=(
            simulation_transaction_count
        ),
        matches=(
            simulation_revision
            == descriptor.state_revision
            and simulation_transaction_count
            == descriptor.transaction_count
        ),
    )


def simulation_state_is_compatible(
    simulation_state: Any,
    *,
    expected_state_version: str | None = None,
) -> bool:
    """Use a structural contract instead of Python class identity.

    Streamlit can reload the simulator module between pages. An existing
    in-memory state can then belong to the previous class object even
    though its data contract is still current and valid.
    """
    if simulation_state is None:
        return False

    required = (
        "state_version",
        "source_league_state_revision",
        "source_transaction_count",
        "phase",
        "current_day_index",
        "settings",
        "players",
        "teams",
        "standings",
        "injuries",
        "player_season_totals",
        "schedule",
        "completed_games",
        "season_history",
    )

    if not all(
        hasattr(simulation_state, name)
        for name in required
    ):
        return False

    if (
        expected_state_version is not None
        and str(
            simulation_state.state_version
        )
        != str(expected_state_version)
    ):
        return False

    mappings = (
        "players",
        "teams",
        "standings",
        "injuries",
        "player_season_totals",
        "schedule",
        "completed_games",
    )

    return all(
        isinstance(
            getattr(
                simulation_state,
                name,
                None,
            ),
            dict,
        )
        for name in mappings
    )


def simulation_matches_trade_state(
    simulation_state: Any,
    trade_state: Any,
) -> bool:
    try:
        return simulation_source_status(
            simulation_state,
            trade_state,
        ).matches
    except (
        CrossPageStateError,
        TypeError,
        ValueError,
    ):
        return False


def initialize_persistent_widget(
    store: MutableMapping[str, Any],
    *,
    persistent_key: str,
    widget_key: str,
    default: Any,
) -> Any:
    """Restore a widget from a non-widget shadow key.

    Streamlit removes a widget key when navigating to a page where that
    widget is not rendered. The separate persistent key is never attached
    to a widget, so it survives page navigation and can restore the widget.
    """
    if persistent_key not in store:
        store[persistent_key] = (
            copy.deepcopy(default)
        )

    if widget_key not in store:
        store[widget_key] = copy.deepcopy(
            store[persistent_key]
        )

    return store[widget_key]


def persist_widget_value(
    store: MutableMapping[str, Any],
    *,
    persistent_key: str,
    widget_key: str,
) -> Any:
    if widget_key not in store:
        raise CrossPageStateError(
            f"Widget state {widget_key!r} "
            "is not available to persist."
        )

    store[persistent_key] = copy.deepcopy(
        store[widget_key]
    )
    return store[persistent_key]


def persistent_value(
    store: MutableMapping[str, Any],
    *,
    persistent_key: str,
    default: Any,
) -> Any:
    if persistent_key not in store:
        store[persistent_key] = (
            copy.deepcopy(default)
        )

    return store[persistent_key]


def run_self_test() -> dict[str, Any]:
    trade_a = SimpleNamespace(
        state_version="league-state-v1",
        state_revision=4,
        transaction_history=[
            "TXN-0001",
            "TXN-0002",
        ],
    )
    trade_b = SimpleNamespace(
        state_version="league-state-v1",
        state_revision=4,
        transaction_history=[
            "TXN-0001",
            "TXN-0002",
        ],
    )
    trade_changed = SimpleNamespace(
        state_version="league-state-v1",
        state_revision=5,
        transaction_history=[
            "TXN-0001",
            "TXN-0002",
            "TXN-0003",
        ],
    )
    simulation = SimpleNamespace(
        state_version=(
            "simulation-league-state-v1.2"
        ),
        source_league_state_revision=4,
        source_transaction_count=2,
        phase="regular_season",
        current_day_index=81,
        settings=SimpleNamespace(),
        players={},
        teams={},
        standings={},
        injuries={},
        player_season_totals={},
        schedule={},
        completed_games={},
        season_history=[],
    )

    store: dict[str, Any] = {}
    initialize_persistent_widget(
        store,
        persistent_key=(
            "franchise_pref_team"
        ),
        widget_key=(
            "_franchise_team_widget"
        ),
        default="CHI",
    )
    store[
        "_franchise_team_widget"
    ] = "OKC"
    persist_widget_value(
        store,
        persistent_key=(
            "franchise_pref_team"
        ),
        widget_key=(
            "_franchise_team_widget"
        ),
    )
    store.pop(
        "_franchise_team_widget"
    )
    restored_team = (
        initialize_persistent_widget(
            store,
            persistent_key=(
                "franchise_pref_team"
            ),
            widget_key=(
                "_franchise_team_widget"
            ),
            default="CHI",
        )
    )

    list_store: dict[str, Any] = {}
    original_default = ["CHI"]
    initialize_persistent_widget(
        list_store,
        persistent_key="persistent",
        widget_key="_widget",
        default=original_default,
    )
    list_store["_widget"].append(
        "OKC"
    )

    checks = {
        "cross_page_state_version_is_current": (
            CROSS_PAGE_STATE_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "different_trade_objects_can_be_equivalent": (
            trade_a is not trade_b
            and describe_trade_state(
                trade_a
            )
            == describe_trade_state(
                trade_b
            )
        ),
        "equivalent_trade_object_does_not_invalidate_simulation": (
            simulation_matches_trade_state(
                simulation,
                trade_b,
            )
        ),
        "simulation_structural_contract_survives_reload": (
            simulation_state_is_compatible(
                simulation,
                expected_state_version=(
                    "simulation-league-state-v1.2"
                ),
            )
        ),
        "simulation_class_identity_is_not_required": (
            type(simulation).__name__
            == "SimpleNamespace"
            and simulation_state_is_compatible(
                simulation
            )
        ),
        "changed_trade_revision_is_detected": (
            not simulation_matches_trade_state(
                simulation,
                trade_changed,
            )
        ),
        "widget_shadow_value_survives_cleanup": (
            restored_team == "OKC"
        ),
        "widget_default_is_deep_copied": (
            original_default == ["CHI"]
            and list_store[
                "persistent"
            ]
            == ["CHI"]
        ),
        "trade_state_duck_contract_is_supported": (
            trade_state_is_compatible(
                trade_a,
                expected_state_version=(
                    "league-state-v1"
                ),
            )
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": CROSS_PAGE_STATE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "trade_a": asdict(
                describe_trade_state(
                    trade_a
                )
            ),
            "trade_b": asdict(
                describe_trade_state(
                    trade_b
                )
            ),
            "changed_status": asdict(
                simulation_source_status(
                    simulation,
                    trade_changed,
                )
            ),
            "restored_team": restored_team,
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
            "Cross-page simulation state "
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
            "\nSIMULATION CROSS-PAGE STATE "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    CROSS_PAGE_STATE_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "stable source matching and "
                    "cross-page widget persistence."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
