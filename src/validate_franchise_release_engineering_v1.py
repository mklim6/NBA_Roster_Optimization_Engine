from __future__ import annotations

import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DOCS = ROOT / "docs"
VERSION = "franchise-release-engineering-v1-validator-2026-09-11"


def main() -> int:
    gate = SRC / "run_franchise_release_candidate_gate_v1.py"
    audit = SRC / "audit_franchise_release_worktree_v1.py"
    checklist = DOCS / "FRANCHISE_MODE_RELEASE_CHECKLIST_V1.md"
    status = DOCS / "FRANCHISE_MODE_CURRENT_STATUS.md"
    gate_text = gate.read_text(encoding="utf-8") if gate.is_file() else ""
    audit_text = audit.read_text(encoding="utf-8") if audit.is_file() else ""
    checklist_text = checklist.read_text(encoding="utf-8") if checklist.is_file() else ""
    status_text = status.read_text(encoding="utf-8") if status.is_file() else ""

    checks = {
        "worktree_audit_exists": audit.is_file(),
        "worktree_audit_is_read_only": "Remove-Item" not in audit_text and "unlink(" not in audit_text and "rmtree(" not in audit_text,
        "worktree_audit_blocks_untracked_src": "return 2" in audit_text and "untracked_src" in audit_text,
        "release_gate_version_is_v1_2": "franchise-release-candidate-gate-v1.2-2026-09-16" in gate_text,
        "release_gate_runs_worktree_audit": "release_worktree_audit" in gate_text,
        "release_gate_runs_sep7_freeze": "sep7_release_data_freeze" in gate_text,
        "release_gate_runs_staff_validation": "staff_foundation_validation" in gate_text,
        "release_gate_runs_deep_fa_v2": "deep_season_free_agency_performance_v2" in gate_text,
        "release_gate_hashes_active_checkpoint_before_after": "active_before" in gate_text and "active_after" in gate_text and "active_checkpoint_unchanged" in gate_text,
        "release_gate_keeps_isolated_launch_rollback": "isolated_live_start_commit_and_rollback" in gate_text,
        "release_checklist_exists": checklist.is_file(),
        "release_checklist_requires_worktree_classification": "untracked production source" in checklist_text.lower(),
        "release_checklist_marks_9_10_optional": "seasons 9-10" in checklist_text and "optional" in checklist_text.lower(),
        "status_records_deep_fa_v2_probe": "44.19 seconds" in status_text and "2.753" in status_text,
        "status_queue_moves_to_release_packaging": (
            "Classify and package the dirty worktree" in status_text
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        print("FRANCHISE RELEASE ENGINEERING V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE RELEASE ENGINEERING V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
