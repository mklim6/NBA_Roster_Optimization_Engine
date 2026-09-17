from __future__ import annotations

import ast
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
AI = SRC / "franchise_trade_finder_ai_v1.py"
UI = SRC / "franchise_trade_finder_ui_v1.py"
TERMS = SRC / "franchise_morale_trade_finder_terms_v1.py"
V5A = SRC / "franchise_morale_trade_market_v1.py"


def _function_source(
    text: str,
    name: str,
) -> str:
    tree = ast.parse(text)
    node = next(
        (
            item
            for item in tree.body
            if isinstance(
                item,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and item.name == name
        ),
        None,
    )
    if node is None:
        return ""
    lines = text.splitlines()
    return "\n".join(
        lines[
            node.lineno - 1 :
            node.end_lineno
        ]
    )


def main() -> int:
    checks: dict[str, bool] = {}

    for path in (
        AI,
        UI,
        TERMS,
        V5A,
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

    ai = (
        AI.read_text(
            encoding="utf-8"
        )
        if AI.exists()
        else ""
    )
    ui = (
        UI.read_text(
            encoding="utf-8"
        )
        if UI.exists()
        else ""
    )
    terms = (
        TERMS.read_text(
            encoding="utf-8"
        )
        if TERMS.exists()
        else ""
    )

    intrinsic = _function_source(
        ai,
        "_intrinsic_player_value",
    )
    values = _function_source(
        ai,
        "_values_for_spec",
    )
    generate = _function_source(
        ai,
        "generate_trade_finder_proposals",
    )
    make_proposal = _function_source(
        ai,
        "_make_proposal",
    )

    checks.update(
        {
            "trade_finder_v1_5_3_compatible": (
                "franchise-trade-finder-cpu-ai-v1.5.3-anchor-preview-resolution-2026-08-13"
                in ai
            ),
            "v5a_dependency_present": (
                "franchise-morale-trade-market-bridge-v5a-2026-09-16"
                in (
                    V5A.read_text(
                        encoding="utf-8"
                    )
                    if V5A.exists()
                    else ""
                )
            ),
            "terms_imported": (
                "from franchise_morale_trade_finder_terms_v1 import"
                in ai
            ),
            "partner_target_pool_uses_morale_availability": (
                generate.count(
                    "_morale_trade_finder_target_available_v1("
                )
                >= 2
            ),
            "target_rank_uses_morale_market_priority": (
                "morale_trade_finder_search_bonus_v1("
                in generate
            ),
            "seller_terms_built_once_per_target": (
                "market_terms_v5b = build_morale_trade_finder_terms_v1("
                in generate
            ),
            "adjusted_floor_drives_cpu_acceptance": (
                "market_terms_v5b.adjusted_accept_floor"
                in generate
            ),
            "proposal_payload_carries_market_terms": (
                "morale_trade_finder_terms_v1"
                in make_proposal
            ),
            "audit_contains_base_and_adjusted_floor": (
                "\"cpu_accept_floor_base\""
                in ai
                and "\"morale_market_floor_adjustment\""
                in ai
                and "\"seller_ask_multiplier\""
                in ai
            ),
            "intrinsic_value_has_no_morale_dependency": (
                bool(intrinsic)
                and "morale" not in intrinsic.lower()
                and "seller" not in intrinsic.lower()
            ),
            "bundle_values_have_no_morale_dependency": (
                bool(values)
                and "morale" not in values.lower()
                and "seller" not in values.lower()
            ),
            "ui_exposes_seller_posture": (
                "Seller posture"
                in ui
                and "morale_trade_finder_terms_v1"
                in ui
            ),
            "audit_export_includes_morale_terms": (
                "\"cpu_accept_floor_base\""
                in ui
                and "\"seller_ask_multiplier\""
                in ui
            ),
            "terms_helper_does_not_import_trade_commit": (
                "franchise_trade_transaction"
                not in terms
            ),
            "terms_helper_does_not_mutate_ratings": (
                "overall_rating ="
                not in terms
                and "potential_rating ="
                not in terms
            ),
        }
    )

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    print(
        json.dumps(
            {
                "checks": checks,
                "failed_checks": failed,
                "passed": not failed,
            },
            indent=2,
        )
    )

    if failed:
        raise SystemExit(1)

    print(
        "FRANCHISE MORALE TRADE FINDER "
        "BRIDGE V5B VALIDATOR PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
