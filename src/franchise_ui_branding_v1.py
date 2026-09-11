from __future__ import annotations

from html import escape

TEAM_BRAND_VERSION = "franchise-ui-branding-v1.3-2026-08-12"

TEAM_DATA = {
    "ATL": ("Atlanta Hawks", "#E03A3E", "#C1D32F", 1610612737),
    "BOS": ("Boston Celtics", "#007A33", "#BA9653", 1610612738),
    "CLE": ("Cleveland Cavaliers", "#860038", "#FDBB30", 1610612739),
    "NOP": ("New Orleans Pelicans", "#0C2340", "#C8102E", 1610612740),
    "CHI": ("Chicago Bulls", "#CE1141", "#FFFFFF", 1610612741),
    "DAL": ("Dallas Mavericks", "#00538C", "#B8C4CA", 1610612742),
    "DEN": ("Denver Nuggets", "#0E2240", "#FEC524", 1610612743),
    "GSW": ("Golden State Warriors", "#1D428A", "#FFC72C", 1610612744),
    "HOU": ("Houston Rockets", "#CE1141", "#FFFFFF", 1610612745),
    "LAC": ("LA Clippers", "#C8102E", "#1D428A", 1610612746),
    "LAL": ("Los Angeles Lakers", "#552583", "#FDB927", 1610612747),
    "MIA": ("Miami Heat", "#98002E", "#F9A01B", 1610612748),
    "MIL": ("Milwaukee Bucks", "#00471B", "#EEE1C6", 1610612749),
    "MIN": ("Minnesota Timberwolves", "#0C2340", "#78BE20", 1610612750),
    "BKN": ("Brooklyn Nets", "#111111", "#FFFFFF", 1610612751),
    "NYK": ("New York Knicks", "#006BB6", "#F58426", 1610612752),
    "ORL": ("Orlando Magic", "#0077C0", "#C4CED4", 1610612753),
    "IND": ("Indiana Pacers", "#002D62", "#FDBB30", 1610612754),
    "PHI": ("Philadelphia 76ers", "#006BB6", "#ED174C", 1610612755),
    "PHX": ("Phoenix Suns", "#1D1160", "#E56020", 1610612756),
    "POR": ("Portland Trail Blazers", "#E03A3E", "#FFFFFF", 1610612757),
    "SAC": ("Sacramento Kings", "#5A2D81", "#63727A", 1610612758),
    "SAS": ("San Antonio Spurs", "#C4CED4", "#111111", 1610612759),
    "OKC": ("Oklahoma City Thunder", "#007AC1", "#EF3B24", 1610612760),
    "TOR": ("Toronto Raptors", "#CE1141", "#FFFFFF", 1610612761),
    "UTA": ("Utah Jazz", "#002B5C", "#F9A01B", 1610612762),
    "MEM": ("Memphis Grizzlies", "#5D76A9", "#12173F", 1610612763),
    "WAS": ("Washington Wizards", "#002B5C", "#E31837", 1610612764),
    "DET": ("Detroit Pistons", "#C8102E", "#1D42BA", 1610612765),
    "CHA": ("Charlotte Hornets", "#1D1160", "#00788C", 1610612766),
}


def normalize(team: str) -> str:
    return str(team or "").strip().upper()


def team_name(team: str) -> str:
    key = normalize(team)
    return TEAM_DATA.get(key, (key or "NBA Team", "#2563EB", "#F43F5E", 0))[0]


def team_colors(team: str) -> tuple[str, str]:
    key = normalize(team)
    row = TEAM_DATA.get(key)
    return (row[1], row[2]) if row else ("#2563EB", "#F43F5E")


def team_logo_url(team: str) -> str:
    key = normalize(team)
    row = TEAM_DATA.get(key)
    if not row:
        return "https://cdn.nba.com/logos/leagues/logo-nba.svg"
    return f"https://cdn.nba.com/logos/nba/{row[3]}/global/L/logo.svg"


def rgba(hex_color: str, alpha: float) -> str:
    value = str(hex_color).lstrip("#")
    if len(value) != 6:
        return f"rgba(37,99,235,{alpha})"
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def safe(value: object) -> str:
    return escape(str(value))
