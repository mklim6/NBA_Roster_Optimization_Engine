from __future__ import annotations

import json
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
POSTSEASON = SRC / "simulation_postseason_v1.py"
RUNNER = SRC / "run_project_validation.py"
OUTPUTS = ROOT / "outputs"
REPORT = OUTPUTS / "playoff_stats_ui_validation_v1.json"

VALIDATOR_VERSION = "playoff-stats-ui-validator-v1.0.1-2026-09-11"
EXPECTED_RUNNER_VERSION = "project-validation-runner-v1.26-2026-09-09"


def compile_file(path: Path) -> str:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    return ""


def run_validation() -> dict[str, object]:
    page_text = PAGE.read_text(encoding="utf-8")
    postseason_text = POSTSEASON.read_text(encoding="utf-8")
    runner_text = RUNNER.read_text(encoding="utf-8")

    page_markers = (
        '"Regular Season Leaders"',
        '"Playoff Leaders"',
        '"Playoff Teams"',
        'include_play_in=False',
        'Play-In games are excluded.',
        'postseason_team_rows(',
    )
    backend_markers = (
        "PLAYOFF_STAT_STAGES",
        "def scoped_postseason_player_totals(",
        "def postseason_player_rows(",
        "def postseason_team_rows(",
        '"TO":',
        '"PF":',
        '"FG%":',
        '"3P%":',
        '"FT%":',
        "playoff_player_rows_exclude_play_in_and_have_full_stats",
        "playoff_team_rows_reconcile",
    )

    compile_results = {
        str(path.relative_to(ROOT)): compile_file(path)
        for path in (PAGE, POSTSEASON, RUNNER, Path(__file__))
    }

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "playoff-stats-ui-validator-v1.0.1-2026-09-11"
        ),
        "all_playoff_page_markers_present": all(
            marker in page_text for marker in page_markers
        ),
        "all_playoff_backend_markers_present": all(
            marker in postseason_text for marker in backend_markers
        ),
        "regular_and_playoff_leaders_are_separate": (
            '"Regular Season Leaders"' in page_text
            and '"Playoff Leaders"' in page_text
        ),
        "playoff_ui_excludes_play_in": (
            page_text.count("include_play_in=False") >= 2
            and "Play-In games are excluded." in page_text
        ),
        "playoff_player_table_has_full_box_stats": all(
            marker in postseason_text
            for marker in (
                '"Pos":',
                '"TO":',
                '"PF":',
                '"FG%":',
                '"3P%":',
                '"FT%":',
            )
        ),
        "playoff_team_table_has_record_and_scoring": all(
            marker in postseason_text
            for marker in (
                '"W":',
                '"L":',
                '"Win%":',
                '"PF":',
                '"PA":',
                '"Diff":',
                '"Furthest Round":',
            )
        ),
        "full_suite_includes_playoff_stats_validator": (
            'name="playoff_stats_ui_validation"' in runner_text
            and "validate_playoff_stats_ui_v1.py" in runner_text
            and EXPECTED_RUNNER_VERSION in runner_text
        ),
        "all_modified_files_compile": all(
            not error for error in compile_results.values()
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "missing_page_markers": [
            marker for marker in page_markers if marker not in page_text
        ],
        "missing_backend_markers": [
            marker for marker in backend_markers if marker not in postseason_text
        ],
        "compile_results": compile_results,
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if failed:
        raise AssertionError(
            "Playoff stats UI validation failed: " + ", ".join(failed)
        )

    return report


def main() -> int:
    report = run_validation()
    print(json.dumps(report, indent=2))
    print("\nPLAYOFF STATS UI V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
