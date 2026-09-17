from __future__ import annotations
import ast,json
from pathlib import Path

def main():
 root=Path.cwd(); m=root/'src'/'franchise_morale_chemistry_v1.py'; h=root/'src'/'franchise_roster_rotation_headquarters_v1.py'; mt=m.read_text(); ht=h.read_text(); checks={}
 try: ast.parse(mt); ast.parse(ht); checks['modules_compile']=True
 except SyntaxError: checks['modules_compile']=False
 checks.update({
  'v3_morale_preserved':'franchise-morale-chemistry-v1.3-2026-09-16' in mt,
  'roster_walk_records_dnp':'ordered_ids = list(dict.fromkeys(roster_ids + list(boxes_by_player)))' in mt and '"dnp": box is None' in mt,
  'missing_box_becomes_zero':'if box is not None else 0.0' in mt,
  'arrow_numeric_recent_min_preserved':'"Recent MIN": _num(row.get("recent_minutes"), float("nan")),' in ht,
  'request_card_uses_markdown':'st.caption("Request")' in ht,
  'compact_trade_columns':'"Trade": row.get("trade_request_status", "None")' in ht and '"FO plan": row.get("trade_availability", "Keep internal")' in ht,
  'primary_reason_removed_from_wide_table':'"Primary reason": row["reasons"][0]' not in ht,
 })
 failed=[k for k,v in checks.items() if not v]; print(json.dumps({'checks':checks,'failed_checks':failed,'passed':not failed},indent=2))
 if failed: raise SystemExit('FRANCHISE MORALE V3.0.2 DNP + UI HOTFIX VALIDATOR FAILED')
 print('FRANCHISE MORALE V3.0.2 DNP + UI HOTFIX VALIDATOR PASSED'); return 0
if __name__=='__main__': raise SystemExit(main())
