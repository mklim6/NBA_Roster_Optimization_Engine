from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def _future_state():
    return SimpleNamespace(
        phase=SimpleNamespace(value="offseason"),
        settings=SimpleNamespace(season_label="2026-27"),
        franchise_completed_season_contract_closeout_v1={
            "status": "applied",
            "source_season": "2026-27",
            "target_market_season": "2027-28",
        },
        offseason_rfa_rights_qo_decisions_v1=[],
    )

def _anchor_state():
    return SimpleNamespace(
        phase=SimpleNamespace(value="offseason"),
        settings=SimpleNamespace(season_label="2026-27"),
        franchise_completed_season_contract_closeout_v1=None,
        offseason_rfa_rights_qo_decisions_v1=[],
    )

def _regular_season_state():
    return SimpleNamespace(
        phase=SimpleNamespace(value="regular_season"),
        settings=SimpleNamespace(season_label="2027-28"),
        franchise_completed_season_contract_closeout_v1=None,
        offseason_rfa_rights_qo_decisions_v1=[],
    )

def main() -> int:
    project = Path.cwd()
    sys.path.insert(0, str(project / "src"))
    rfa_path = project / "src" / "franchise_free_agency_rfa_qo_lifecycle_v1.py"
    ws_path = project / "src" / "franchise_free_agency_workspace_v1.py"
    checks = {}

    for label, path in (("rfa", rfa_path), ("workspace", ws_path)):
        checks[f"{label}_exists"] = path.exists()
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            checks[f"{label}_compiles"] = True
        except Exception:
            checks[f"{label}_compiles"] = False

    module = _load(rfa_path, "_future_rfa_overlay_fixture")
    checks["future_market_empty_anchor_ledger_returns_empty_overlay"] = (
        module.rfa_market_metadata(_future_state()) == {}
    )
    checks["regular_season_empty_ledger_returns_empty_overlay"] = (
        module.rfa_market_metadata(_regular_season_state()) == {}
    )

    strict = False
    try:
        module.rfa_market_metadata(_anchor_state())
    except module.RFAQOLifecycleError:
        strict = True
    checks["anchor_market_missing_ledger_still_fails_strictly"] = strict

    ws = ws_path.read_text(encoding="utf-8")
    checks["workspace_detects_modeled_future_market"] = (
        "modeled_future_market_enabled" in ws
        and "_fa_future_market_without_anchor_rfa" in ws
    )
    checks["workspace_explains_anchor_overlay_not_reused"] = (
        "historical 2026-27 RFA/QO" in ws
    )

    failed = [k for k, v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FUTURE MARKET RFA OVERLAY HOTFIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE FUTURE MARKET RFA OVERLAY HOTFIX V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
