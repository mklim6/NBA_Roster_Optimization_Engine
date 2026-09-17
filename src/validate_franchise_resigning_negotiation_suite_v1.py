from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys
import types

def _install_streamlit_stub():
    if "streamlit" in sys.modules:
        return
    stub = types.ModuleType("streamlit")
    sys.modules["streamlit"] = stub

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def _decision(status: str, utility: float, threshold: float, counter=None):
    profile = SimpleNamespace(
        money_weight=.31,
        role_weight=.22,
        winning_weight=.18,
        security_weight=.17,
        career_fit_weight=.12,
    )
    return SimpleNamespace(
        status=status,
        utility_score=utility,
        acceptance_threshold=threshold,
        salary_score=65.0,
        role_score=80.0,
        winning_score=55.0,
        security_score=84.0,
        career_fit_score=71.0,
        market_salary_reference=20_000_000.0,
        counter_salary=counter,
        preference_profile=profile,
        rationale=("fixture",),
    )

def main() -> int:
    project = Path.cwd()
    sys.path.insert(0, str(project / "src"))
    module_path = project / "src" / "franchise_resigning_negotiation_suite_v1.py"
    workspace_path = project / "src" / "franchise_free_agency_workspace_v1.py"

    checks = {}
    for label, path in (("suite", module_path), ("workspace", workspace_path)):
        checks[f"{label}_exists"] = path.exists()
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            checks[f"{label}_compiles"] = True
        except Exception:
            checks[f"{label}_compiles"] = False

    # Import only after source compile checks.
    _install_streamlit_stub()
    suite = _load(module_path, "_rsn_suite_fixture")

    accept = _decision("accept", 78.0, 70.0)
    counter = _decision("counter", 64.0, 70.0, 22_500_000.0)
    decline = _decision("decline", 35.0, 70.0)
    checks["accept_maps_to_positive_mood"] = suite._mood(accept, None)[1] == "good"
    checks["counter_maps_to_negotiating_mood"] = suite._mood(counter, None)[0] == "WANTS A COUNTER"
    checks["severe_decline_can_show_disdain"] = suite._mood(decline, None)[0] in {"UNSATISFIED", "INSULTED"}
    checks["counter_dialogue_uses_backend_counter"] = "$22.5M" in suite._dialogue(counter, None, returning=True)

    # Recent-team context fixture.
    box = SimpleNamespace(player_id="P1", team_abbreviation="CHI")
    game = SimpleNamespace(day_index=82, game_id="G82", player_box_scores=(box,))
    state = SimpleNamespace(
        completed_games={"G82": game},
        players={},
    )
    row = {"player_id": "P1", "player_name": "Player One", "prior_team": ""}
    ctx = suite.prior_team_context_v1(state, row)
    checks["recent_saved_game_can_supply_presentation_context"] = (
        ctx.team == "CHI" and ctx.source == "recent saved game appearances"
    )

    ws = workspace_path.read_text(encoding="utf-8")
    checks["workspace_imports_suite"] = "franchise_resigning_negotiation_suite_v1" in ws
    checks["workspace_renders_watchlist"] = "render_resigning_watchlist_v1(" in ws
    checks["workspace_renders_negotiation_intro"] = "render_negotiation_room_intro_v1(" in ws
    checks["workspace_renders_player_reaction"] = "render_player_reaction_v1(" in ws
    checks["preview_offer_gets_immediate_player_decision"] = "evaluate_free_agent_offer_decision(" in ws
    checks["quick_counter_staging_exists"] = "fa_resign_suite_pending_salary" in ws
    checks["future_market_does_not_reuse_stale_prior_team"] = (
        "if not modeled_future_market_enabled(state):" in ws
        and 'else:\n                # Do not reuse stale 2026-27 rights/market evidence' in ws
    )
    checks["existing_live_signing_commit_preserved"] = "commit_persistent_user_winner_live(" in ws
    checks["existing_rfa_offer_sheet_flow_preserved"] = "commit_external_offer_sheet_live(" in ws
    checks["existing_calendar_advance_preserved"] = "advance_free_agency_day_with_rfa_offer_sheets_durably(" in ws

    failed = [k for k, v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE RE-SIGNING NEGOTIATION SUITE V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE RE-SIGNING NEGOTIATION SUITE V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
