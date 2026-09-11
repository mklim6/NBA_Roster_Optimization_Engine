from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
VERSION = "franchise-experience-v2.1-awards-validator-v1-2026-08-10"


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    checks = {
        "experience_version": "franchise-experience-v2.1-awards-v1-2026-08-10" in text,
        "awards_helper_layer": "FRANCHISE_EXPERIENCE_AWARDS_VERSION" in text,
        "awards_styles": "inject_awards_styles()" in text,
        "awards_showcase": "render_awards_showcase(state)" in text,
        "mvp_trophy": "Michael Jordan Trophy" in text,
        "dpoy_trophy": "Hakeem Olajuwon Trophy" in text,
        "roy_trophy": "Wilt Chamberlain Trophy" in text,
        "coach_award": "Coach of the Year" in text,
        "executive_award": "Executive of the Year" in text,
        "finals_mvp": "Bill Russell Trophy" in text,
        "championship_trophy": ("Larry O\\'Brien Trophy" in text or "Larry O'Brien Trophy" in text),
        "all_nba": "All-NBA First Team" in text,
        "all_defense": "All-Defensive First Team" in text,
        "all_rookie": "All-Rookie First Team" in text,
        "league_hub_awards_night": "League Honors & Trophy Room" in text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError(
            "Franchise Experience V2.1 validation failed: "
            + ", ".join(failed)
        )
    print()
    print("FRANCHISE EXPERIENCE V2.1 AWARDS VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
