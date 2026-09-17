from __future__ import annotations

import base64
import csv
import hashlib
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from typing import Any


GENERATED_PORTRAIT_VERSION = (
    "franchise-pexels-goofy-player-portraits-v3-2026-09-12"
)

ROOT = Path(__file__).resolve().parents[1]
STOCK_DIR = ROOT / "assets" / "generated_player_stock_portraits"
MANIFEST = STOCK_DIR / "manifest.csv"

TEAM_COLORS: dict[str, tuple[str, str]] = {
    "ATL": ("#E03A3E", "#C1D32F"),
    "BOS": ("#007A33", "#BA9653"),
    "BKN": ("#111111", "#FFFFFF"),
    "CHA": ("#1D1160", "#00788C"),
    "CHI": ("#CE1141", "#111111"),
    "CLE": ("#860038", "#FDBB30"),
    "DAL": ("#00538C", "#B8C4CA"),
    "DEN": ("#0E2240", "#FEC524"),
    "DET": ("#C8102E", "#1D42BA"),
    "GSW": ("#1D428A", "#FFC72C"),
    "HOU": ("#CE1141", "#111111"),
    "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"),
    "LAL": ("#552583", "#FDB927"),
    "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"),
    "MIL": ("#00471B", "#EEE1C6"),
    "MIN": ("#0C2340", "#78BE20"),
    "NOP": ("#0C2340", "#C8102E"),
    "NYK": ("#006BB6", "#F58426"),
    "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"),
    "PHI": ("#006BB6", "#ED174C"),
    "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#111111"),
    "SAC": ("#5A2D81", "#63727A"),
    "SAS": ("#111111", "#C4CED4"),
    "TOR": ("#CE1141", "#111111"),
    "UTA": ("#002B5C", "#F9A01B"),
    "WAS": ("#002B5C", "#E31837"),
}


def _digest(value: Any) -> bytes:
    return hashlib.sha256(str(value or "").encode("utf-8")).digest()


def _initials(name: str) -> str:
    parts = [part for part in str(name or "").replace("-", " ").split() if part]
    if not parts:
        return "NBA"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@lru_cache(maxsize=1)
def _stock_rows() -> tuple[dict[str, str], ...]:
    if not MANIFEST.exists():
        return tuple()

    rows: list[dict[str, str]] = []
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            filename = str(row.get("file", "")).strip()
            if not filename:
                continue
            path = STOCK_DIR / filename
            if not path.is_file():
                continue
            rows.append({str(k): str(v or "") for k, v in row.items()})

    return tuple(rows)


@lru_cache(maxsize=512)
def _file_data_url(path_text: str) -> str:
    path = Path(path_text)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def stock_portrait_available() -> bool:
    return bool(_stock_rows())


def _stock_portrait_index(player_id: Any, row_count: int) -> int:
    if row_count <= 0:
        return 0

    text = str(player_id or "").strip()
    match = re.match(r"^(.*?)(\d+)$", text)
    if match:
        prefix = match.group(1)
        ordinal = int(match.group(2))
        offset = int.from_bytes(_digest(prefix)[:8], "big") % row_count
        return (offset + max(0, ordinal - 1)) % row_count

    seed = _digest(text)
    return int.from_bytes(seed[:8], "big") % row_count


def stock_portrait_metadata(player_id: Any) -> dict[str, str] | None:
    rows = _stock_rows()
    if not rows:
        return None
    index = _stock_portrait_index(player_id, len(rows))
    return dict(rows[index])


def _fallback_nonface_card(
    player_id: Any,
    *,
    team: str,
    player_name: str,
) -> str:
    """Non-AI fallback used until a licensed stock-photo pool is installed."""
    seed = _digest(player_id)
    primary, secondary = TEAM_COLORS.get(
        str(team or "").upper(),
        ("#1D428A", "#C8102E"),
    )
    initials = _initials(player_name)
    number = 1 + (int.from_bytes(seed[8:10], "big") % 99)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{primary}"/>
    <stop offset="1" stop-color="#090D15"/>
  </linearGradient>
</defs>
<rect width="240" height="240" rx="28" fill="url(#bg)"/>
<circle cx="193" cy="43" r="72" fill="{secondary}" opacity=".18"/>
<path d="M40 240 Q55 162 120 153 Q185 162 200 240 Z" fill="#111827"/>
<path d="M75 240 Q86 184 120 176 Q154 184 165 240 Z" fill="{primary}"/>
<path d="M92 177 L120 207 L148 177" fill="none" stroke="{secondary}" stroke-width="7"/>
<circle cx="120" cy="105" r="47" fill="#182132"/>
<circle cx="120" cy="98" r="31" fill="#26354B"/>
<rect x="72" y="27" width="96" height="32" rx="16" fill="#070B12" opacity=".82"/>
<text x="120" y="49" text-anchor="middle" font-family="Arial,sans-serif" font-size="14" font-weight="800" fill="#FFFFFF">STOCK PHOTO NEEDED</text>
<text x="120" y="226" text-anchor="middle" font-family="Arial,sans-serif" font-size="30" font-weight="900" fill="#FFFFFF">{number}</text>
<text x="120" y="139" text-anchor="middle" font-family="Arial,sans-serif" font-size="22" font-weight="900" fill="#FFFFFF">{initials}</text>
</svg>"""

    return "data:image/svg+xml;charset=UTF-8," + quote(svg, safe="")


def generated_player_portrait_url(
    player_id: Any,
    *,
    team: str = "",
    player_name: str = "",
) -> str:
    rows = _stock_rows()
    if rows:
        index = _stock_portrait_index(player_id, len(rows))
        path = STOCK_DIR / rows[index]["file"]
        return _file_data_url(str(path.resolve()))

    return _fallback_nonface_card(
        player_id,
        team=team,
        player_name=player_name,
    )


def player_image_url(
    player_id: Any,
    *,
    team: str = "",
    player_name: str = "",
    generated: bool | None = None,
) -> str:
    resolved = str(player_id or "").strip()

    generated_prefix = resolved.upper().startswith(
        (
            "GEN-",
            "DRAFT-",
            "ROOKIE-",
            "SYN-",
        )
    )
    use_generated = bool(
        generated is True
        or generated_prefix
        or (
            generated is None
            and resolved
            and not resolved.isdigit()
        )
    )

    if use_generated:
        return generated_player_portrait_url(
            resolved or f"anonymous|{team}|{player_name}",
            team=team,
            player_name=player_name,
        )

    if resolved.isdigit():
        return (
            "https://cdn.nba.com/headshots/nba/latest/"
            f"1040x760/{resolved}.png"
        )

    return generated_player_portrait_url(
        resolved or f"anonymous|{team}|{player_name}",
        team=team,
        player_name=player_name,
    )
