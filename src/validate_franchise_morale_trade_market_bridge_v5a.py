from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
FRONT = SRC / "franchise_cpu_front_office_v1.py"
BRIDGE = SRC / "franchise_morale_trade_market_v1.py"


def _function_source(
    text: str,
    name: str,
) -> str:
    tree = ast.parse(text)
    target = next(
        (
            node
            for node
            in tree.body
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name == name
        ),
        None,
    )
    if target is None:
        return ""
    lines = text.splitlines()
    return "\n".join(
        lines[
            target.lineno - 1 :
            target.end_lineno
        ]
    )


def main() -> int:
    checks: dict[str, bool] = {}

    for path in (
        PAGE,
        FRONT,
        BRIDGE,
    ):
        checks[
            f"{path.name}_exists"
        ] = path.exists()
        if path.exists():
            try:
                py_compile.compile(
                    str(path),
                    doraise=True,
                )
                checks[
                    f"{path.name}_compiles"
                ] = True
            except Exception:
                checks[
                    f"{path.name}_compiles"
                ] = False

    front_text = (
        FRONT.read_text(
            encoding="utf-8"
        )
        if FRONT.exists()
        else ""
    )
    page_text = (
        PAGE.read_text(
            encoding="utf-8"
        )
        if PAGE.exists()
        else ""
    )

    team_source = _function_source(
        front_text,
        "build_team_front_office_plan",
    )
    value_source = _function_source(
        front_text,
        "intrinsic_player_value",
    )

    bridge_pos = team_source.find(
        "apply_cpu_morale_trade_market_to_decisions_v1("
    )
    intent_pos = team_source.find(
        "build_trade_package_intents("
    )

    checks.update(
        {
            "front_office_version_compatible": (
                "franchise-cpu-front-office-v1.6.2"
                in front_text
            ),
            "bridge_import_present": (
                "from franchise_morale_trade_market_v1 import"
                in front_text
            ),
            "bridge_is_inside_team_plan": (
                bridge_pos >= 0
            ),
            "bridge_runs_before_trade_package_planning": (
                bridge_pos >= 0
                and intent_pos >= 0
                and bridge_pos
                < intent_pos
            ),
            "intrinsic_value_has_no_morale_dependency": (
                bool(value_source)
                and "morale" not in value_source.lower()
                and "trade_response" not in value_source.lower()
            ),
            "league_hub_market_audit_present": (
                "render_morale_trade_market_audit_v1("
                in page_text
                and "Morale-adjusted trade market"
                not in page_text
            ),
            "helper_exposes_context": (
                "def morale_trade_market_context_v1("
                in BRIDGE.read_text(
                    encoding="utf-8"
                )
                if BRIDGE.exists()
                else False
            ),
            "helper_exposes_decision_bridge": (
                "def apply_cpu_morale_trade_market_to_decisions_v1("
                in BRIDGE.read_text(
                    encoding="utf-8"
                )
                if BRIDGE.exists()
                else False
            ),
            "helper_does_not_import_trade_transaction_commit": (
                "franchise_trade_transaction"
                not in (
                    BRIDGE.read_text(
                        encoding="utf-8"
                    )
                    if BRIDGE.exists()
                    else ""
                )
            ),
        }
    )

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE MORALE TRADE MARKET "
        "BRIDGE V5A VALIDATOR PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
