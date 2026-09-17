from __future__ import annotations

FRANCHISE_UI_POLISH_VERSION = "franchise-ui-polish-v2.1-header-clearance-2026-09-15"


def inject_franchise_ui_polish_v1(*, primary: str, secondary: str) -> None:
    """Apply the V1 presentation layer without changing franchise behavior."""
    import streamlit as st

    st.markdown(
        f"""
<style>
:root {{
  --fmp-primary: {primary};
  --fmp-secondary: {secondary};
  --fmp-bg: #070b12;
  --fmp-surface: rgba(15, 21, 32, .82);
  --fmp-surface-2: rgba(20, 28, 42, .76);
  --fmp-line: rgba(255,255,255,.095);
  --fmp-line-strong: rgba(255,255,255,.16);
  --fmp-text: #f8fafc;
  --fmp-muted: #9aa8ba;
  --fmp-shadow: 0 18px 46px rgba(0,0,0,.22);
}}

html {{ scroll-behavior:smooth; }}
body {{ color:var(--fmp-text); }}
::selection {{ background:color-mix(in srgb,var(--fmp-primary) 58%,#22d3ee);color:#fff; }}
* {{ scrollbar-color:color-mix(in srgb,var(--fmp-primary) 58%,#334155) #0a1019;scrollbar-width:thin; }}

.stApp {{
  background:
    radial-gradient(circle at 86% 4%, color-mix(in srgb, var(--fmp-primary) 18%, transparent), transparent 31rem),
    radial-gradient(circle at 8% 28%, color-mix(in srgb, var(--fmp-secondary) 10%, transparent), transparent 28rem),
    linear-gradient(180deg,#070b12 0%,#0a1019 52%,#070b12 100%) !important;
}}

[data-testid="stHeader"] {{
  background:rgba(7,11,18,.72) !important;
  border-bottom:1px solid rgba(255,255,255,.045);
  backdrop-filter:blur(18px);
}}

.block-container {{
  max-width:1580px !important;
  padding-top:4.25rem !important;
  padding-bottom:5rem !important;
}}
/* Streamlit gives every style-only st.markdown call a flex-row gap. With the
   modular visual layers loaded together, those empty rows accumulated into a
   large blank band above the franchise hero. Keep the styles active while
   removing only containers whose Markdown payload is a lone <style> tag. */
div[data-testid="stElementContainer"]:has(
  div[data-testid="stMarkdownContainer"] > style:only-child
) {{
  display:none !important;
}}
.block-container::before {{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  opacity:.18;
  background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
  background-size:44px 44px;
  mask-image:linear-gradient(to bottom,black,transparent 72%);
}}

/* Sidebar */
[data-testid="stSidebar"] {{
  background:
    radial-gradient(circle at 50% 0%, color-mix(in srgb,var(--fmp-primary) 15%,transparent),transparent 22rem),
    linear-gradient(180deg,#0c121d 0%,#090e16 100%) !important;
  border-right:1px solid var(--fmp-line) !important;
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color:#aeb9c8; }}
[data-testid="stSidebarNav"] a {{
  border-radius:12px !important;
  margin:2px 7px !important;
  min-height:42px;
  transition:background .16s ease,border-color .16s ease,transform .16s ease;
}}
[data-testid="stSidebarNav"] a:hover {{
  background:rgba(255,255,255,.045) !important;
  transform:translateX(2px);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
  background:linear-gradient(110deg,color-mix(in srgb,var(--fmp-primary) 24%,transparent),rgba(255,255,255,.035)) !important;
  box-shadow:inset 3px 0 0 var(--fmp-primary);
}}

/* Hero refinement */
.fxv2-team-hero {{
  border-color:rgba(255,255,255,.16) !important;
  box-shadow:0 30px 80px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.13) !important;
}}
.fxv2-team-hero::before {{
  content:"";
  position:absolute;
  z-index:5;
  left:0; right:0; top:0;
  height:3px;
  background:linear-gradient(90deg,var(--fmp-primary),var(--fmp-secondary),transparent 82%);
  opacity:.9;
}}
.fxv2-kicker {{ color:rgba(255,255,255,.72) !important; }}
.fxv2-next {{ box-shadow:0 10px 28px rgba(0,0,0,.18); }}

/* Primary franchise workspace navigation */
.st-key-franchise_active_section {{
  position:sticky;
  top:3.55rem;
  z-index:40;
  margin:.15rem 0 .85rem;
  padding:.42rem;
  border:1px solid var(--fmp-line);
  border-radius:16px;
  background:rgba(8,13,21,.87);
  box-shadow:0 14px 34px rgba(0,0,0,.18);
  backdrop-filter:blur(16px);
}}
.st-key-franchise_active_section [role="radiogroup"] {{
  gap:.34rem !important;
  padding:0 !important;
  border:0 !important;
  background:transparent !important;
  flex-wrap:wrap !important;
}}
.st-key-franchise_active_section label {{
  min-height:38px;
  padding:.48rem .76rem !important;
  border:1px solid transparent !important;
  border-radius:10px !important;
  background:transparent !important;
  transition:transform .15s ease,background .15s ease,border-color .15s ease !important;
}}
.st-key-franchise_active_section label:hover {{
  transform:translateY(-1px);
  border-color:rgba(255,255,255,.08) !important;
  background:rgba(255,255,255,.045) !important;
}}
.st-key-franchise_active_section label:has(input:checked) {{
  border-color:color-mix(in srgb,var(--fmp-primary) 46%,rgba(255,255,255,.12)) !important;
  background:linear-gradient(110deg,color-mix(in srgb,var(--fmp-primary) 38%,#101722),color-mix(in srgb,var(--fmp-secondary) 20%,#101722)) !important;
  box-shadow:0 8px 22px color-mix(in srgb,var(--fmp-primary) 16%,transparent) !important;
}}
.st-key-franchise_active_section label p {{ font-size:.79rem !important; font-weight:800 !important; }}

/* Route / section guide */
.fm-route-guide {{
  margin:.4rem 0 1rem !important;
  padding:14px 17px !important;
  border:1px solid var(--fmp-line) !important;
  border-left:3px solid var(--fmp-primary) !important;
  border-radius:14px !important;
  background:linear-gradient(110deg,color-mix(in srgb,var(--fmp-primary) 7%,transparent),rgba(255,255,255,.016)) !important;
  box-shadow:0 10px 26px rgba(0,0,0,.10);
}}
.fm-route-title {{ font-size:.94rem !important; letter-spacing:-.01em; }}
.fm-route-detail {{ color:#98a7b9 !important; }}

/* Typography and section hierarchy */
.block-container h1,.block-container h2,.block-container h3 {{
  letter-spacing:-.025em;
  color:#f8fafc;
}}
.block-container h2 {{ margin-top:1.45rem; }}
.block-container h3 {{ margin-top:1.05rem; }}
.fm-section {{
  margin:1.55rem 0 .72rem !important;
  padding-top:.15rem;
  color:#f8fafc !important;
  font-size:.82rem !important;
  font-weight:900 !important;
  letter-spacing:.12em !important;
  text-transform:uppercase;
}}
.fm-section::after {{
  content:"";
  display:block;
  width:54px;
  height:2px;
  margin-top:.42rem;
  border-radius:999px;
  background:linear-gradient(90deg,var(--fmp-primary),var(--fmp-secondary));
}}

/* Metrics become sports-dashboard cards */
div[data-testid="stMetric"] {{
  position:relative;
  min-height:105px !important;
  padding:14px 15px !important;
  overflow:hidden;
  border:1px solid var(--fmp-line) !important;
  border-radius:16px !important;
  background:linear-gradient(145deg,rgba(255,255,255,.045),rgba(255,255,255,.014)) !important;
  box-shadow:0 12px 28px rgba(0,0,0,.12) !important;
  transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease;
}}
div[data-testid="stMetric"]::before {{
  content:"";
  position:absolute;
  left:0; top:0; right:0;
  height:2px;
  background:linear-gradient(90deg,var(--fmp-primary),var(--fmp-secondary),transparent 72%);
  opacity:.82;
}}
div[data-testid="stMetric"]:hover {{
  transform:translateY(-2px);
  border-color:var(--fmp-line-strong) !important;
  box-shadow:0 18px 36px rgba(0,0,0,.18) !important;
}}
div[data-testid="stMetricLabel"] p {{
  color:#98a7b9 !important;
  font-size:.68rem !important;
  font-weight:800 !important;
  letter-spacing:.07em;
  text-transform:uppercase;
}}
div[data-testid="stMetricValue"] {{
  color:#fff !important;
  font-weight:900 !important;
  letter-spacing:-.035em;
}}

/* Buttons */
.stButton > button,.stDownloadButton > button {{
  min-height:40px;
  border-radius:11px !important;
  border:1px solid rgba(255,255,255,.11) !important;
  font-weight:780 !important;
  transition:transform .14s ease,box-shadow .14s ease,border-color .14s ease,background .14s ease !important;
}}
.stButton > button:hover,.stDownloadButton > button:hover {{
  transform:translateY(-1px);
  border-color:rgba(255,255,255,.20) !important;
  box-shadow:0 10px 24px rgba(0,0,0,.18);
}}
.stButton > button:focus-visible,.stDownloadButton > button:focus-visible {{
  outline:2px solid #7dd3fc !important;
  outline-offset:2px !important;
}}
button[kind="primary"] {{
  border:0 !important;
  background:linear-gradient(110deg,var(--fmp-primary),color-mix(in srgb,var(--fmp-secondary) 68%,var(--fmp-primary))) !important;
  box-shadow:0 10px 28px color-mix(in srgb,var(--fmp-primary) 23%,transparent) !important;
}}
button[kind="secondary"] {{ background:rgba(255,255,255,.035) !important; }}

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap:.35rem;
  padding:.35rem;
  border:1px solid var(--fmp-line);
  border-radius:13px;
  background:rgba(8,13,21,.64);
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  min-height:38px;
  padding:0 .85rem;
  border-radius:9px;
  font-weight:760;
}}
[data-testid="stTabs"] [aria-selected="true"] {{
  background:linear-gradient(110deg,color-mix(in srgb,var(--fmp-primary) 30%,transparent),rgba(255,255,255,.035));
}}

/* Expanders and bordered containers */
[data-testid="stExpander"] {{
  overflow:hidden;
  border:1px solid var(--fmp-line) !important;
  border-radius:14px !important;
  background:rgba(255,255,255,.018);
}}
[data-testid="stExpander"] summary:hover {{ background:rgba(255,255,255,.025); }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:16px; }}

/* Inputs */
[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stTextArea"] textarea {{
  border-color:var(--fmp-line) !important;
  border-radius:10px !important;
  background:rgba(7,11,18,.72) !important;
}}
[data-baseweb="select"] > div:focus-within,
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {{
  border-color:color-mix(in srgb,var(--fmp-primary) 66%,white 8%) !important;
  box-shadow:0 0 0 2px color-mix(in srgb,var(--fmp-primary) 16%,transparent) !important;
}}

/* Tables */
[data-testid="stDataFrame"],[data-testid="stDataEditor"] {{
  overflow:hidden;
  border:1px solid var(--fmp-line) !important;
  border-radius:14px !important;
  background:rgba(8,13,21,.58);
  box-shadow:0 12px 30px rgba(0,0,0,.10);
}}

/* Alerts / status messages */
[data-testid="stAlert"] {{
  border-radius:13px !important;
  border-width:1px !important;
  box-shadow:0 8px 22px rgba(0,0,0,.08);
}}

/* Progress */
[data-testid="stProgress"] > div > div > div > div {{
  background:linear-gradient(90deg,var(--fmp-primary),var(--fmp-secondary)) !important;
}}

/* Make status controls read like a modern broadcast dashboard. */
[data-testid="stStatusWidget"], [data-testid="stToast"] {{
  border:1px solid var(--fmp-line) !important;
  border-radius:14px !important;
  background:rgba(8,13,21,.9) !important;
  box-shadow:var(--fmp-shadow) !important;
  backdrop-filter:blur(16px);
}}
[data-testid="stPills"] button,[data-testid="stSegmentedControl"] button {{
  border-radius:999px !important;
  font-weight:800 !important;
}}

/* Captions and dividers */
[data-testid="stCaptionContainer"] {{ color:#8493a7 !important; }}
hr {{ border-color:rgba(255,255,255,.065) !important; }}

/* Keep the dense management UI usable on smaller screens. */
@media (max-width:1100px) {{
  .st-key-franchise_active_section {{ top:3.2rem; }}
  .st-key-franchise_active_section label {{ padding:.42rem .60rem !important; }}
}}
@media (max-width:760px) {{
  .block-container {{ padding-left:.8rem !important; padding-right:.8rem !important; }}
  .st-key-franchise_active_section {{ position:relative; top:auto; }}
  .fxv2-team-hero {{ border-radius:22px !important; }}
  div[data-testid="stMetric"] {{ min-height:92px !important; }}
}}
@media (prefers-reduced-motion:reduce) {{
  html {{ scroll-behavior:auto; }}
  *,*::before,*::after {{ animation-duration:.01ms !important;animation-iteration-count:1 !important;transition-duration:.01ms !important; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
