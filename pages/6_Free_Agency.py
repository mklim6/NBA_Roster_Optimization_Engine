from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
while str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

from franchise_free_agency_workspace_v1 import render_free_agency_workspace

st.set_page_config(page_title="NBA Free Agency", page_icon="📝", layout="wide")
render_free_agency_workspace(embedded=False)
