
from __future__ import annotations
import ast
from pathlib import Path

def main() -> int:
    root=Path(__file__).resolve().parents[1]
    op=root/'src/franchise_onboarding_progression_v1.py'; up=root/'src/franchise_ui_polish_v1.py'; pp=root/'pages/5_Franchise_Mode.py'
    o=op.read_text(encoding='utf-8'); u=up.read_text(encoding='utf-8'); p=pp.read_text(encoding='utf-8')
    checks={}
    try: ast.parse(o); ast.parse(u); ast.parse(p); checks['all_modified_files_compile']=True
    except Exception: checks['all_modified_files_compile']=False
    checks['onboarding_version_is_v2_1']='franchise-onboarding-progression-v2.1-persistent-tutorial-2026-09-15' in o
    checks['polish_version_is_v2_1']='franchise-ui-polish-v2.1-header-clearance-2026-09-15' in u
    checks['tutorial_completion_key_is_persisted']='"franchise_tutorial_completed_v1"' in p and '"franchise_tutorial_completed_v1"' in o
    checks['tutorial_defaults_closed_after_completion']='tutorial_completed = bool(' in o and 'not tutorial_completed' in o
    checks['all_tutorial_exit_paths_use_completion_helper']=o.count('_complete_tutorial_v2_1(persist_preferences)') >= 5
    checks['tutorial_completion_calls_preference_writer']='persist_preferences()' in o and 'persist_preferences=_save_franchise_ui_preferences_v1_6' in p
    checks['replay_tour_remains_available']='How to play / replay tour' in o and 'st.session_state["franchise_tutorial_open_v1"] = True' in o
    checks['replay_does_not_clear_completion']='st.session_state["franchise_tutorial_completed_v1"] = False' not in o
    checks['header_clearance_is_large_enough']='padding-top:4.25rem !important;' in u
    checks['no_checkpoint_writes_added']='save_franchise_checkpoint' not in o and 'commit_franchise_checkpoint' not in o and 'save_franchise_checkpoint' not in u
    failed=[k for k,v in checks.items() if not v]
    print({'checks':checks,'failed_checks':failed,'passed':not failed})
    if failed: print('FRANCHISE ONBOARDING + HEADER HOTFIX V1 VALIDATOR FAILED'); return 1
    print('FRANCHISE ONBOARDING + HEADER HOTFIX V1 VALIDATOR PASSED'); return 0
if __name__=='__main__': raise SystemExit(main())
