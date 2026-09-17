from __future__ import annotations
import ast, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'src'; PAGE=ROOT/'pages'/'5_Franchise_Mode.py'
MOD=SRC/'franchise_cpu_morale_response_v1.py'

def main():
    checks={}
    checks['module_exists']=MOD.is_file()
    checks['page_exists']=PAGE.is_file()
    text=MOD.read_text(encoding='utf-8') if MOD.is_file() else ''
    page=PAGE.read_text(encoding='utf-8') if PAGE.is_file() else ''
    try: ast.parse(text); checks['module_compiles']=True
    except Exception: checks['module_compiles']=False
    try: ast.parse(page); checks['page_compiles']=True
    except Exception: checks['page_compiles']=False
    checks['version_present']='franchise-cpu-morale-response-v1-2026-09-16' in text
    checks['controlled_teams_excluded']='team in controlled' in text
    checks['role_repair_present']='minutes_repair' in text and 'rotation_repair' in text
    checks['meeting_response_present']='hold_player_meeting_v1' in text
    checks['trade_response_present']='set_player_trade_response_v1' in text
    checks['core_protection_present']='core_player' in text and '_is_core_player' in text
    checks['no_trade_execution']='apply_trade' not in text and 'commit_trade' not in text
    checks['willingness_adapter_present']='cpu_trade_willingness_modifier_v1' in text
    checks['page_runtime_hook']='FRANCHISE_CPU_MORALE_REACTIONS_V1' in page and 'run_cpu_morale_reactions_v1' in page
    checks['league_audit_ui']='render_cpu_morale_response_audit_v1' in page
    failed=[k for k,v in checks.items() if not v]
    report={'checks':checks,'failed_checks':failed,'passed':not failed}
    print(json.dumps(report,indent=2))
    if failed: raise SystemExit('FRANCHISE CPU MORALE REACTIONS V4 VALIDATOR FAILED')
    print('FRANCHISE CPU MORALE REACTIONS V4 VALIDATOR PASSED')
    return 0
if __name__=='__main__': raise SystemExit(main())
