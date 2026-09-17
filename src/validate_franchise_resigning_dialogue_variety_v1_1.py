from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys

def _install_dependency_stubs():
    import types

    portraits = types.ModuleType("franchise_generated_player_portraits_v1")
    portraits.player_image_url = lambda *args, **kwargs: ""
    sys.modules["franchise_generated_player_portraits_v1"] = portraits

    branding = types.ModuleType("franchise_ui_branding_v1")
    branding.team_colors = lambda team: ("#e11d48", "#111827")
    branding.team_logo_url = lambda team: ""
    branding.team_name = lambda team: str(team or "")
    sys.modules["franchise_ui_branding_v1"] = branding


def _load(path: Path, name: str):
    _install_dependency_stubs()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def _decision(status="counter", salary=62, role=80, winning=55, security=76, fit=70):
    return SimpleNamespace(
        status=status,
        utility_score=64.0 if status == "counter" else 78.0,
        acceptance_threshold=70.0,
        salary_score=float(salary),
        role_score=float(role),
        winning_score=float(winning),
        security_score=float(security),
        career_fit_score=float(fit),
        market_salary_reference=20_000_000.0,
        counter_salary=22_500_000.0 if status == "counter" else None,
        preference_profile=SimpleNamespace(
            money_weight=.31,
            role_weight=.22,
            winning_weight=.18,
            security_weight=.17,
            career_fit_weight=.12,
        ),
        rationale=("fixture",),
    )

def main() -> int:
    project = Path.cwd()
    sys.path.insert(0, str(project / "src"))
    target = project / "src" / "franchise_resigning_negotiation_suite_v1.py"
    checks = {}

    checks["module_exists"] = target.exists()
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    try:
        ast.parse(text)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    suite = _load(target, "_rsn_dialogue_v11_fixture")
    checks["version_is_v1_1"] = "v1.1-dialogue-variety-2026-09-11" in text
    checks["stable_phrase_selector_exists"] = hasattr(suite, "_stable_pick")
    checks["presentation_voice_is_cosmetic"] = hasattr(suite, "_presentation_voice")
    checks["reason_fragments_exist"] = hasattr(suite, "_reason_fragment")

    # At least 8 distinct opening lines across many deterministic seeds.
    intros = {
        suite._intro_quote(
            returning=False,
            has_persistent_market=False,
            seed=f"PLAYER-{i}|CHI",
        )
        for i in range(100)
    }
    checks["opening_line_diversity"] = len(intros) >= 8

    return_intros = {
        suite._intro_quote(
            returning=True,
            has_persistent_market=True,
            seed=f"RETURN-{i}|CHI",
        )
        for i in range(100)
    }
    checks["return_talk_diversity"] = len(return_intros) >= 8

    decision = _decision()
    reaction_lines = {
        suite._dialogue(
            decision,
            None,
            returning=bool(i % 2),
            seed=f"P{i}|CHI|{15_000_000 + i * 250_000}|3|preview",
        )
        for i in range(100)
    }
    checks["counter_reaction_diversity"] = len(reaction_lines) >= 8

    low_money = _decision(status="decline", salary=20, role=82, winning=70, security=74, fit=69)
    targeted = {
        suite._dialogue(
            low_money,
            None,
            returning=False,
            seed=f"LOWMONEY-{i}",
        )
        for i in range(50)
    }
    checks["decision_factor_can_shape_decline_copy"] = any(
        token in line.lower()
        for line in targeted
        for token in ("money", "value", "financial", "numbers")
    )

    # Same exact state/seed must remain stable across reruns.
    first = suite._dialogue(decision, None, returning=False, seed="STABLE")
    second = suite._dialogue(decision, None, returning=False, seed="STABLE")
    checks["same_offer_same_seed_is_stable"] = first == second

    # Different offer seed should be able to surface different wording.
    variants = {
        suite._dialogue(
            decision,
            None,
            returning=False,
            seed=f"P1|CHI|{salary}|3|preview",
        )
        for salary in range(12_000_000, 30_000_001, 250_000)
    }
    checks["offer_changes_can_change_wording"] = len(variants) >= 4

    # Core decision status is only read by dialogue code, never overwritten.
    checks["dialogue_does_not_assign_decision_status"] = ".status =" not in text
    checks["dialogue_does_not_mutate_utility"] = "utility_score =" not in text

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE RE-SIGNING DIALOGUE VARIETY V1.1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE RE-SIGNING DIALOGUE VARIETY V1.1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
