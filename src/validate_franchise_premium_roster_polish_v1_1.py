from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "franchise_premium_roster_v1.py"
text = MODULE.read_text(encoding="utf-8")

checks = {
    "module_exists": MODULE.is_file(),
    "version_is_v11": 'franchise-premium-roster-v1.1-2026-09-11' in text,
    "court_compacted": "min-height:455px" in text,
    "bottom_guards_raised": "top:66%" in text,
    "five_column_wide_grid": "repeat(5,minmax(0,1fr))" in text,
    "responsive_four_column_grid": "max-width:1350px" in text and "repeat(4,minmax(0,1fr))" in text,
    "bench_photo_compacted": "height:150px" in text,
    "contract_expiring_label": 'term = "1Y · Expiring"' in text,
    "contract_missing_term_not_misleading": 'term = "Term N/A"' in text,
    "morale_still_not_fabricated": "does not store a morale variable" in text,
    "simulation_mutation_absent": all(token not in text for token in (
        "save_franchise_checkpoint(", "set_franchise_state(", "apply_rotation_plan(",
        "simulate_scheduled_game(", "advance_franchise_scope(",
    )),
}

compile_error = ""
try:
    py_compile.compile(str(MODULE), doraise=True)
    checks["python_compile"] = True
except Exception as exc:
    checks["python_compile"] = False
    compile_error = f"{type(exc).__name__}: {exc}"

smoke = r'''
import sys
from types import SimpleNamespace as NS
sys.path.insert(0, SRC)
import franchise_premium_roster_v1 as m
assert m.FRANCHISE_PREMIUM_ROSTER_VERSION.endswith("v1.1-2026-09-11")
c1=NS(status="under_contract", salary=12000000.0, years_remaining=1, option_type="")
c3=NS(status="under_contract", salary=12000000.0, years_remaining=3, option_type="")
cn=NS(status="under_contract", salary=12000000.0, years_remaining=None, option_type="")
p1=NS(contract=c1); p3=NS(contract=c3); pn=NS(contract=cn)
assert m.contract_label_v1(p1)[1] == "1Y · Expiring"
assert m.contract_label_v1(p3)[1] == "3Y LEFT"
assert m.contract_label_v1(pn)[1] == "Term N/A"
print("PREMIUM ROSTER POLISH V1.1 FRESH IMPORT OK")
'''
proc = subprocess.run(
    [sys.executable, "-c", smoke.replace("SRC", repr(str((ROOT / "src").resolve())))],
    cwd=str(ROOT), text=True, capture_output=True,
)
checks["fresh_process_contract"] = proc.returncode == 0 and "FRESH IMPORT OK" in proc.stdout

failed = [k for k,v in checks.items() if not v]
print({
    "version":"franchise-premium-roster-polish-v1.1-validator-2026-09-11",
    "checks":checks,
    "failed_checks":failed,
    "compile_error":compile_error,
    "fresh_import_stdout":proc.stdout.strip(),
    "fresh_import_stderr":proc.stderr.strip(),
    "passed":not failed,
})
if failed:
    raise SystemExit("FRANCHISE PREMIUM ROSTER POLISH V1.1 VALIDATOR FAILED")
print("FRANCHISE PREMIUM ROSTER POLISH V1.1 VALIDATOR PASSED")
