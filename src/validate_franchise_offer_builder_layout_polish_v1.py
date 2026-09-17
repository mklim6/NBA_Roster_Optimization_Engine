from __future__ import annotations
from pathlib import Path
import ast

def main() -> int:
    project = Path.cwd()
    target = project / "src" / "franchise_free_agency_workspace_v1.py"
    checks = {}
    checks["workspace_exists"] = target.exists()
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    try:
        ast.parse(text)
        checks["python_compiles"] = True
    except Exception:
        checks["python_compiles"] = False
    checks["version_upgraded"] = (
        "v1.2-offer-builder-layout-2026-09-11" in text
        or "v1.3-visual-command-desk-2026-09-12" in text
    )
    checks["market_container_present"] = "market_section = st.container()" in text
    checks["offer_container_present"] = "offer_section = st.container()" in text
    checks["full_width_marker_present"] = "FRANCHISE_OFFER_BUILDER_LAYOUT_POLISH_V1" in text
    checks["legacy_two_column_layout_removed"] = 'left, right = st.columns([1.45, 1.0], gap="large")' not in text
    checks["legacy_right_rail_removed"] = 'with right:' not in text
    checks["offer_builder_heading_present"] = 'st.markdown("### Offer builder")' in text
    checks["layout_caption_present"] = 'Full-width negotiation workspace for easier building, previewing and reviewing player reactions.' in text
    checks["negotiation_suite_still_integrated"] = 'render_resigning_watchlist_v1(' in text
    checks["preview_flow_still_present"] = 'Preview offer' in text
    failed = [k for k, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE OFFER BUILDER LAYOUT POLISH V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE OFFER BUILDER LAYOUT POLISH V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
