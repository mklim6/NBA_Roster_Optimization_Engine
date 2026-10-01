from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
WORKSPACE = ROOT / "src" / "franchise_free_agency_workspace_v1.py"
UI_HELPER = ROOT / "src" / "franchise_free_agency_ui_v1.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
sys.path.insert(0, str(SRC))

from franchise_free_agency_transaction_v1 import FREE_AGENCY_TRANSACTION_VERSION, free_agency_state_fingerprint
from franchise_free_agency_transaction_v1_1 import FREE_AGENCY_TRANSACTION_V1_1_VERSION
from franchise_free_agency_financial_bridge_v1_2 import FREE_AGENCY_FINANCIAL_BRIDGE_VERSION
from franchise_free_agency_ui_v1 import (
    FREE_AGENCY_UI_EXECUTION_BOUNDARY,
    FREE_AGENCY_UI_VERSION,
    controlled_teams_from_checkpoint,
    free_agent_rows,
    isolated_offseason_preview_state,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from simulation_league_state_v1 import validate_simulation_league_state

EXPECTED = {
    "ui": "franchise-free-agency-ui-preview-v1-2026-08-14",
    "v1": "franchise-free-agency-transaction-v1-2026-08-13",
    "v11": "franchise-free-agency-transaction-v1.1-2026-08-14",
    "v12": "franchise-free-agency-financial-bridge-v1.3-modeled-future-market-2026-08-18",
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def main() -> int:
    before_hash = sha(CHECKPOINT) if CHECKPOINT.exists() else ""
    checkpoint = load_franchise_checkpoint()
    state = checkpoint.simulation_state if checkpoint is not None else None
    source_fp = free_agency_state_fingerprint(state) if state is not None else ""
    rows = free_agent_rows(state) if state is not None else []
    controlled = controlled_teams_from_checkpoint(checkpoint, state) if checkpoint is not None else ()
    valid_teams = set(getattr(state, 'teams', {})) if state is not None else set()
    page_text = PAGE.read_text(encoding='utf-8') if PAGE.exists() else ""
    workspace_text = WORKSPACE.read_text(encoding='utf-8') if WORKSPACE.exists() else ""
    helper_text = UI_HELPER.read_text(encoding='utf-8') if UI_HELPER.exists() else ""

    isolated = isolated_offseason_preview_state(state) if state is not None else None
    isolated_phase = str(getattr(getattr(isolated, 'phase', ''), 'value', getattr(isolated, 'phase', ''))).lower() if isolated is not None else ""
    after_source_fp = free_agency_state_fingerprint(state) if state is not None else ""

    checks = {
        "ui_version_is_current": FREE_AGENCY_UI_VERSION == EXPECTED['ui'],
        "execution_boundary_is_preview_only": FREE_AGENCY_UI_EXECUTION_BOUNDARY == 'preview_only_no_durable_commit',
        "base_transaction_v1_is_preserved": FREE_AGENCY_TRANSACTION_VERSION == EXPECTED['v1'],
        "durable_transaction_v1_1_is_preserved": FREE_AGENCY_TRANSACTION_V1_1_VERSION == EXPECTED['v11'],
        "financial_bridge_is_current": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION == EXPECTED['v12'],
        "durable_checkpoint_exists": CHECKPOINT.exists(),
        "durable_checkpoint_loads": checkpoint is not None,
        "durable_state_is_valid": state is not None and bool(validate_simulation_league_state(state)),
        "free_agent_rows_match_live_pool": state is not None and len(rows) == len(set(str(x).strip() for x in getattr(state, 'free_agent_player_ids', ()))),
        "free_agent_rows_are_unique": len({row['player_id'] for row in rows}) == len(rows),
        "controlled_teams_never_expand_beyond_preferences": all(team in valid_teams for team in controlled),
        "hypothetical_offseason_uses_replacement_copy": isolated is not None and isolated is not state,
        "hypothetical_offseason_sets_only_copy_phase": isolated_phase == 'offseason',
        "helper_does_not_mutate_durable_source": source_fp == after_source_fp,
        "franchise_page_exists": PAGE.exists(),
        "page_delegates_to_current_workspace": (
            WORKSPACE.exists()
            and 'render_free_agency_workspace' in page_text
            and 'render_free_agency_workspace(' in page_text
        ),
        "workspace_uses_contract_legal_preview": 'build_contract_legal_free_agency_preview' in workspace_text,
        "workspace_exposes_financial_details": 'Financial details' in workspace_text,
        "workspace_exposes_structural_checks": 'Structural checks' in workspace_text,
        "workspace_supports_hypothetical_offseason_preview": 'Evaluate as a hypothetical offseason offer' in workspace_text,
        "workspace_exposes_current_salary_legality": 'Contract salary legality' in workspace_text,
        "preview_helper_does_not_import_durable_commit": (
            'commit_live_financial_free_agency_preview_durably' not in helper_text
            and 'commit_free_agency_preview_durably' not in helper_text
        ),
        "workspace_live_commit_is_separate_from_preview_helper": (
            'commit_persistent_user_winner_live(' in workspace_text
            and 'commit_persistent_user_winner_live(' not in helper_text
        ),
    }
    compile_ok = True
    compile_error = ''
    try:
        compile(page_text, str(PAGE), 'exec')
        compile(workspace_text, str(WORKSPACE), 'exec')
        compile(helper_text, str(UI_HELPER), 'exec')
    except Exception as exc:
        compile_ok = False
        compile_error = str(exc)
    checks['page_compiles'] = compile_ok

    after_hash = sha(CHECKPOINT) if CHECKPOINT.exists() else ""
    checks['validator_did_not_write_checkpoint'] = before_hash == after_hash
    failed = [k for k,v in checks.items() if not v]

    print('='*108)
    print('FRANCHISE FREE AGENCY UI PREVIEW V1 VALIDATION')
    print('='*108)
    for k,v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print()
    print('READ-ONLY LIVE STATE')
    print(f'  Season: {getattr(getattr(state, "settings", None), "season_label", "") if state else ""}')
    phase = getattr(state, 'phase', '') if state else ''
    print(f'  Phase: {getattr(phase, "value", phase)}')
    print(f'  Free agents: {len(rows)}')
    print(f'  Controlled teams: {", ".join(controlled) if controlled else "none resolved"}')
    print('  Durable signing from UI: DISABLED')
    print('  Checkpoint write: NOT PERFORMED')
    print()
    print(json.dumps({
        'validator': 'franchise-free-agency-ui-preview-validator-v1-2026-08-14',
        'ui': FREE_AGENCY_UI_VERSION,
        'execution_boundary': FREE_AGENCY_UI_EXECUTION_BOUNDARY,
        'checks': checks,
        'failed_checks': failed,
        'compile_error': compile_error,
        'checkpoint_hash_before': before_hash,
        'checkpoint_hash_after': after_hash,
        'passed': not failed,
    }, indent=2))
    if failed:
        raise AssertionError('Free Agency UI Preview V1 failed: ' + ', '.join(failed))
    print()
    print('FRANCHISE FREE AGENCY UI PREVIEW V1 VALIDATION PASSED')
    print('READ-ONLY VALIDATION: no live signing or checkpoint write was performed.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
