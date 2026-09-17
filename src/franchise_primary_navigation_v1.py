"""Franchise-first application navigation and lightweight flagship styling.

Presentation-only. This module does not import or mutate simulation state.
"""
from __future__ import annotations

from pathlib import Path

FRANCHISE_PRIMARY_NAV_VERSION = "franchise-primary-navigation-v1-2026-09-11"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _page_exists(relative_path: str) -> bool:
    return (_project_root() / relative_path).exists()


def _safe_page_link(st, path: str, label: str, icon: str) -> None:
    if _page_exists(path):
        st.page_link(path, label=label, icon=icon, width="stretch")


def render_franchise_primary_navigation_v1() -> None:
    """Replace Streamlit's flat page list with a franchise-first hierarchy."""
    import streamlit as st

    st.markdown(
        r"""
<style>
/* FRANCHISE_PRIMARY_NAV_V1 */
[data-testid="stSidebarNav"] { display:none !important; }

section[data-testid="stSidebar"] {
    border-right:1px solid rgba(148,163,184,.12);
}

section[data-testid="stSidebar"] > div {
    padding-top:.55rem;
}

.fpnav-brand {
    margin:.3rem .15rem 1rem;
    padding:1rem 1rem .9rem;
    border:1px solid rgba(96,165,250,.20);
    border-radius:18px;
    background:
      radial-gradient(circle at 85% 5%, rgba(59,130,246,.28), transparent 42%),
      linear-gradient(145deg, rgba(15,23,42,.92), rgba(17,24,39,.72));
    box-shadow:0 14px 34px rgba(0,0,0,.18);
}
.fpnav-brand-kicker {
    color:#93C5FD;
    font-size:.66rem;
    font-weight:800;
    letter-spacing:.13em;
    text-transform:uppercase;
}
.fpnav-brand-title {
    margin:.28rem 0 .22rem;
    color:#F8FAFC;
    font-size:1.05rem;
    font-weight:850;
    letter-spacing:-.02em;
}
.fpnav-brand-copy {
    color:rgba(203,213,225,.64);
    font-size:.73rem;
    line-height:1.45;
}
.fpnav-section {
    margin:1.05rem .35rem .38rem;
    color:rgba(148,163,184,.70);
    font-size:.61rem;
    font-weight:800;
    letter-spacing:.14em;
    text-transform:uppercase;
}
.fpnav-caption {
    margin:.18rem .35rem .8rem;
    color:rgba(148,163,184,.54);
    font-size:.68rem;
    line-height:1.38;
}
.fpnav-divider {
    height:1px;
    margin:.85rem .25rem .25rem;
    background:linear-gradient(90deg, transparent, rgba(148,163,184,.17), transparent);
}

section[data-testid="stSidebar"] [data-testid="stPageLink"] a {
    margin:.12rem 0;
    padding:.58rem .72rem;
    border:1px solid transparent;
    border-radius:12px;
    color:rgba(226,232,240,.82);
    transition:background .16s ease, border-color .16s ease, transform .16s ease;
}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
    background:rgba(148,163,184,.08);
    border-color:rgba(148,163,184,.12);
    transform:translateX(2px);
}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
    background:rgba(59,130,246,.13);
    border-color:rgba(96,165,250,.24);
    color:#F8FAFC;
}

/* Make the flagship link read like the product, not another utility. */
section[data-testid="stSidebar"] [data-testid="stPageLink"]:has(a[href*="Franchise_Mode"]) a {
    min-height:56px;
    padding:.78rem .82rem;
    border-color:rgba(96,165,250,.30);
    background:
      linear-gradient(110deg, rgba(37,99,235,.24), rgba(14,165,233,.10)),
      rgba(15,23,42,.62);
    box-shadow:0 10px 26px rgba(0,0,0,.14);
    color:#F8FAFC;
    font-weight:800;
}
section[data-testid="stSidebar"] [data-testid="stPageLink"]:has(a[href*="Franchise_Mode"]) a:hover {
    border-color:rgba(125,211,252,.48);
    background:
      linear-gradient(110deg, rgba(37,99,235,.34), rgba(14,165,233,.15)),
      rgba(15,23,42,.74);
}

/* Home page: visually establish Franchise Mode as the flagship product. */
.product-grid {
    grid-template-columns:1fr !important;
}
.product-grid .product-card:nth-child(2) {
    order:-1;
    min-height:285px;
    border-color:rgba(96,165,250,.30) !important;
    background:
      radial-gradient(circle at 88% 10%, rgba(59,130,246,.24), transparent 36%),
      linear-gradient(145deg, rgba(30,64,175,.24), rgba(15,23,42,.78)) !important;
    box-shadow:0 18px 50px rgba(2,6,23,.22);
}
.product-grid .product-card:nth-child(2) h3 {
    font-size:1.65rem !important;
}
.product-grid .product-card:nth-child(1) {
    opacity:.88;
}

@media (max-width: 900px) {
    .fpnav-brand { padding:.85rem; }
}
</style>
""",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            """
<div class="fpnav-brand">
  <div class="fpnav-brand-kicker">NBA Management Simulator</div>
  <div class="fpnav-brand-title">Franchise Simulator</div>
  <div class="fpnav-brand-copy">Build a roster, run seasons, navigate the CBA, draft, develop and manage a persistent league.</div>
</div>
<div class="fpnav-section">Main Experience</div>
""",
            unsafe_allow_html=True,
        )

        _safe_page_link(st, "pages/5_Franchise_Mode.py", "Franchise Mode", "🏆")
        st.markdown(
            '<div class="fpnav-caption">The flagship persistent multi-season experience.</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="fpnav-divider"></div><div class="fpnav-section">Supporting Tools</div>', unsafe_allow_html=True)
        _safe_page_link(st, "pages/3_Trade_Machine.py", "Trade Machine", "🔄")
        _safe_page_link(st, "pages/6_Free_Agency.py", "Free Agency", "📝")

        st.markdown('<div class="fpnav-section">Sandboxes & Analysis</div>', unsafe_allow_html=True)
        _safe_page_link(st, "pages/4_Game_Simulator.py", "Game Simulator", "🎮")
        _safe_page_link(st, "pages/2_Player_Ratings.py", "Player Ratings", "⭐")
        _safe_page_link(st, "pages/1_Trade_Lab.py", "Trade Lab", "🧪")

        st.markdown('<div class="fpnav-divider"></div><div class="fpnav-section">Project</div>', unsafe_allow_html=True)
        _safe_page_link(st, "Home.py", "Project Overview", "🏠")
        st.markdown(
            '<div class="fpnav-caption">Standalone tools remain available for testing, analysis and portfolio demonstration.</div>',
            unsafe_allow_html=True,
        )
