from __future__ import annotations
import ast
import importlib.util
import sys
from pathlib import Path

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    retention_path = root / "src" / "franchise_retention_experience_v1.py"
    returning_path = root / "src" / "franchise_returning_gm_v1.py"
    retention_source = retention_path.read_text(encoding="utf-8")
    returning_source = returning_path.read_text(encoding="utf-8")
    retention = _load("retention_progression_test", retention_path)
    returning = _load("returning_progression_test", returning_path)

    checks = {}
    try:
        ast.parse(retention_source)
        ast.parse(returning_source)
        checks["modules_compile"] = True
    except Exception:
        checks["modules_compile"] = False

    checks["retention_version"] = (
        "franchise-retention-experience-v1.1-progression-clarity-2026-09-16"
        == retention.FRANCHISE_RETENTION_EXPERIENCE_VERSION
    )
    checks["returning_version"] = (
        "franchise-returning-gm-v1.1-progression-clarity-2026-09-16"
        == returning.RETURNING_GM_VERSION
    )
    checks["quest_summary_present"] = (
        "Quest progress" in retention_source
        and "Next objective" in retention_source
        and "Up next" in retention_source
    )
    checks["quest_rewards_explicit"] = "<strong>REWARD</strong>" in retention_source
    checks["milestone_requirements_present"] = (
        "def _milestone_display_rows(" in retention_source
        and "Next milestone" in retention_source
    )
    checks["milestone_xp_copy_present"] = "+30 XP per milestone" in retention_source
    checks["career_rank_is_explicit"] = (
        "Career rank" in returning_source
        and "Career rank is independent" in returning_source
    )
    checks["selected_path_is_explicit"] = "Selected GM challenge path" in returning_source
    checks["xp_sources_present"] = all(
        marker in returning_source
        for marker in (
            "<small>Wins</small>",
            "<small>Games</small>",
            "<small>Moves</small>",
            "<small>Legacy</small>",
        )
    )
    checks["return_recap_preserved"] = "Since your last visit" in returning_source
    checks["franchise_identity_preserved"] = "Franchise identity" in returning_source
    checks["no_checkpoint_writes"] = all(
        token not in retention_source + returning_source
        for token in ("save_franchise_checkpoint", "commit_franchise_checkpoint")
    )

    career = returning.gm_career_profile(
        wins=29,
        games=82,
        moves=0,
        seasons=0,
        championships=0,
        milestones=2,
    )
    checks["screenshot_case_is_team_builder_rank"] = (
        career["label"] == "Team Builder"
        and career["xp"] == 224
        and career["level"] == 3
    )
    checks["xp_sources_sum_to_total"] = sum(career["xp_sources"].values()) == career["xp"]
    checks["path_copy_is_separate"] = (
        returning._gm_path_copy_v1("Builder")
        != returning._gm_path_copy_v1("Balanced")
    )

    rows = retention._milestone_display_rows(
        rotation_ready=True,
        games=82,
        wins=29,
        moves=0,
        seasons=0,
        championships=0,
    )
    checks["milestone_catalog_has_six"] = len(rows) == 6
    checks["milestone_conditions_are_visible"] = all(
        bool(item.get("requirement")) for item in rows
    )
    checks["deal_maker_correctly_locked_without_moves"] = (
        next(item for item in rows if item["name"] == "Deal Maker")["unlocked"] is False
    )

    failed = [name for name, passed in checks.items() if not passed]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE GM PROGRESSION + QUEST POLISH V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE GM PROGRESSION + QUEST POLISH V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
