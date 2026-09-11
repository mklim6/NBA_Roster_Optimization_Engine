from __future__ import annotations
import ast, hashlib, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    before = sha(CHECKPOINT) if CHECKPOINT.is_file() else ""
    text = PAGE.read_text(encoding="utf-8")
    checks = {
        "exact_ui_repair_page_hash": sha(PAGE) == EXPECTED,
        "page_compiles": True,
        "compact_intro_hero_installed": "Run the season, roster, transactions, draft and long-term league" in text,
        "postseason_html_is_contiguous": "fm-postseason-matchup" in text and "return f\"\"\"" not in text[text.find("def postseason_matchup_html"):text.find("@st.cache_resource", text.find("def postseason_matchup_html"))],
        "postseason_css_classes_installed": ".fm-matchup-grid" in text and ".fm-matchup-team" in text,
        "restore_notice_is_compact": "str(notice).startswith(\"Restored the durable Franchise Mode\")" in text,
        "legacy_stats_warning_is_collapsible": "Why this season is flagged" in text,
        "cpu_front_office_preserved": "render_cpu_front_office_v1(" in text,
        "v1_7_performance_preserved": "V1.7 deep startup profile" in text and "_franchise_module_source_signature_v1_6" in text,
        "checkpoint_exists": CHECKPOINT.is_file(),
    }
    try:
        ast.parse(text); compile(text, str(PAGE), "exec")
    except Exception:
        checks["page_compiles"] = False
    if CHECKPOINT.is_file():
        checks["checkpoint_hash_unchanged"] = sha(CHECKPOINT) == before
    print("="*88)
    print("FRANCHISE UI REPAIR V1 VALIDATION")
    print("="*88)
    for k,v in checks.items(): print(f"  {k}: {'PASS' if v else 'FAIL'}")
    if not all(checks.values()): return 1
    print()
    print("FRANCHISE UI REPAIR V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no franchise state or checkpoint write was performed.")
    return 0
if __name__ == "__main__": raise SystemExit(main())
