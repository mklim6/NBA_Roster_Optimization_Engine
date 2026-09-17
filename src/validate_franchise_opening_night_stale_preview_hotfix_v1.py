from __future__ import annotations

import json
import py_compile
from pathlib import Path

VERSION = "franchise-opening-night-stale-preview-hotfix-v1-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
OPENING = ROOT / "src" / "franchise_opening_night_ux_v1.py"


def main() -> int:
    text = OPENING.read_text(encoding="utf-8")
    try:
        py_compile.compile(str(OPENING), doraise=True)
        compiles = True
    except Exception:
        compiles = False

    checks = {
        "opening_module_compiles": compiles,
        "durable_source_version_present": "franchise-opening-night-ux-v1.1-durable-source-2026-09-11" in text,
        "durable_checkpoint_loaded_on_commit": "checkpoint = load_franchise_checkpoint(allow_backup=False)" in text,
        "fresh_durable_preview_is_built": "live_preview = preview_opening_regular_season(" in text,
        "false_in_memory_fingerprint_comparison_removed": "live_preview.source_fingerprint != preview.source_fingerprint" not in text,
        "commit_uses_fresh_durable_fingerprint": "expected_fingerprint=live_preview.source_fingerprint" in text,
        "commit_uses_fresh_durable_confirmation": "confirmation_token=live_preview.confirmation_token" in text,
        "durable_roster_readiness_rechecked": "live_roster_blockers = _roster_readiness(" in text,
        "durable_schedule_rechecked": "live_schedule_count" in text and "live_schedule_count != 1230" in text,
        "existing_certified_commit_path_preserved": "commit_opening_regular_season_live(" in text,
        "no_active_save_replacement_added": "replace_active" not in text,
    }
    failed = [k for k, v in checks.items() if not v]
    result = {"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}
    print(json.dumps(result, indent=2))
    print()
    if failed:
        print("FRANCHISE OPENING NIGHT STALE PREVIEW HOTFIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE OPENING NIGHT STALE PREVIEW HOTFIX V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
