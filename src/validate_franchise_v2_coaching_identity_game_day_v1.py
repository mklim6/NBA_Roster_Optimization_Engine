from __future__ import annotations
import hashlib
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED = {
    "tactics": "3aff0b031fadabb4a8aca6fb5cf862788e8d453aeecf5db8d13d4e32d4b84a26",
    "ui": "5abb572ea910bef312089100a855134df058dccf13bd16b7fd050b6e494c37a3",
    "page": "d2c1e07b11797d988c341659a979863c510880e716e7cf3feab19b3aebf74514",
    "sim": "84a192ad6243240fa566a4df1e7e2f1ab6a7ae5898176ee8db754564accc60ec",
    "role": "871554483ccc0fad20ebd53af37eeba8c640a6ffbd5913da2f58bd894a16f6a8",
    "staff": "c76edaf317cc3371868e9fdc833b57c3b917da7aefbd88f4ae8f42847fd554ab",
    "m3": "93746851517645fd997bb086e1a44dc9ba9da6ab9fd2fe1d132b8ed35c4d8105",
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""
    paths = {
        "tactics": SRC / "franchise_coaching_matchup_tactics_v1.py",
        "ui": SRC / "franchise_coaching_game_day_ui_v1.py",
        "page": PAGE,
        "sim": SRC / "single_game_simulator_v1.py",
        "role": SRC / "franchise_coaching_role_rotation_v1.py",
        "staff": SRC / "franchise_staff_system_v1.py",
        "m3": SRC / "validate_franchise_v2_coaching_matchup_tactics_v1.py",
    }
    texts = {key: path.read_text(encoding="utf-8") for key, path in paths.items()}
    checks = {
        "exact_tactics": sha(paths["tactics"]) == EXPECTED["tactics"],
        "exact_ui": sha(paths["ui"]) == EXPECTED["ui"],
        "exact_page": sha(paths["page"]) == EXPECTED["page"],
        "simulator_unchanged": sha(paths["sim"]) == EXPECTED["sim"],
        "role_engine_unchanged": sha(paths["role"]) == EXPECTED["role"],
        "staff_system_unchanged": sha(paths["staff"]) == EXPECTED["staff"],
        "m3_validator_refreshed": sha(paths["m3"]) == EXPECTED["m3"],
        "coach_tendency_profile_present": "CoachTendencyProfile" in texts["tactics"],
        "head_trait_biases_present": "_HEAD_TRAIT_SCHEME_BIASES" in texts["tactics"],
        "assistant_trait_biases_present": "_ASSISTANT_TRAIT_SCHEME_BIASES" in texts["tactics"],
        "bias_is_bounded": "_MAX_TENDENCY_BIAS = 0.085" in texts["tactics"],
        "bad_scheme_cannot_be_rescued": "if raw_utility > 0.0" in texts["tactics"],
        "game_day_panel_present": "Coaching plan" in texts["ui"],
        "threat_profile_visible": "Opponent threat profile" in texts["ui"],
        "availability_adjustment_visible": "Availability adjustment" in texts["ui"],
        "truth_in_labeling_present": "not a claim that the real" in texts["ui"],
        "no_game_result_preview": (
            "without previewing a game result" in texts["ui"]
            and "simulate_scheduled_game" not in texts["ui"]
            and "simulate_scores" not in texts["ui"]
        ),
        "page_imports_ui": "render_game_day_coaching_plan_v1" in texts["page"],
        "page_passes_sit_ids": "sit_player_ids=tuple(sit_ids)" in texts["page"],
        "page_renders_before_lock": (
            texts["page"].find("render_game_day_coaching_plan_v1(")
            < texts["page"].find('st.markdown("### Lock game plan")')
        ),
    }
    for path in paths.values():
        py_compile.compile(str(path), doraise=True)
    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after
    print("FRANCHISE V2 COACHING IDENTITY / GAME DAY V1 STATIC VALIDATION")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("VALIDATION FAILED")
        for name in failed:
            print("  - " + name)
        return 1
    print("VALIDATION PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
