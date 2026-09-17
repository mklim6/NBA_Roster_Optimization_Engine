from __future__ import annotations

from types import SimpleNamespace

import streamlit as st

from franchise_game_day_broadcast_v1 import (
    inject_game_day_broadcast_visuals_v1,
    render_game_day_broadcast_v1,
    render_game_day_final_v1,
)


def player(player_id: str, name: str, team: str, position: str, rating: int) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id,
        player_name=name,
        team_abbreviation=team,
        position=position,
        overall_rating=rating,
    )


players = {
    "203915": player("203915", "Josh Giddey", "CHI", "PG", 85),
    "1629632": player("1629632", "Coby White", "CHI", "SG", 84),
    "1641824": player("1641824", "Matas Buzelis", "CHI", "SF", 83),
    "1630172": player("1630172", "Patrick Williams", "CHI", "PF", 79),
    "1627739": player("1627739", "Lauri Markkanen", "CHI", "C", 87),
    "chi6": player("chi6", "Ayo Dosunmu", "CHI", "G", 80),
    "chi7": player("chi7", "Julian Phillips", "CHI", "F", 76),
    "chi8": player("chi8", "Jalen Smith", "CHI", "C", 78),
    "1628973": player("1628973", "Jalen Brunson", "NYK", "PG", 92),
    "1628969": player("1628969", "Mikal Bridges", "NYK", "SG", 87),
    "1629628": player("1629628", "RJ Barrett", "NYK", "SF", 84),
    "1628384": player("1628384", "OG Anunoby", "NYK", "PF", 86),
    "1626157": player("1626157", "Karl-Anthony Towns", "NYK", "C", 91),
    "nyk6": player("nyk6", "Miles McBride", "NYK", "G", 79),
    "nyk7": player("nyk7", "Josh Hart", "NYK", "F", 84),
    "nyk8": player("nyk8", "Mitchell Robinson", "NYK", "C", 80),
}


def rotation(ids: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(starter_ids=ids[:5], rotation_player_ids=ids)


chi_ids = tuple(list(players)[:8])
nyk_ids = tuple(list(players)[8:])
state = SimpleNamespace(
    phase="regular_season",
    players=players,
    teams={"CHI": SimpleNamespace(rotation=rotation(chi_ids)), "NYK": SimpleNamespace(rotation=rotation(nyk_ids))},
    standings={
        "CHI": SimpleNamespace(games_played=12, wins=7, losses=5, points_for=1361, points_against=1328, streak_type="W", streak_length=2),
        "NYK": SimpleNamespace(games_played=12, wins=8, losses=4, points_for=1392, points_against=1314, streak_type="W", streak_length=4),
    },
    injuries={"nyk8": SimpleNamespace(status="questionable")},
    schedule={
        "a": SimpleNamespace(day_index=1),
        "b": SimpleNamespace(day_index=2),
        "c": SimpleNamespace(day_index=3),
        "d": SimpleNamespace(day_index=4),
        "e": SimpleNamespace(day_index=5),
    },
    completed_games={
        "a": SimpleNamespace(home_team="CHI", away_team="NYK", home_score=112, away_score=108),
        "b": SimpleNamespace(home_team="CHI", away_team="BOS", home_score=101, away_score=109),
        "c": SimpleNamespace(home_team="MIA", away_team="CHI", home_score=104, away_score=110),
        "d": SimpleNamespace(home_team="NYK", away_team="BKN", home_score=121, away_score=103),
        "e": SimpleNamespace(home_team="BOS", away_team="NYK", home_score=111, away_score=116),
    },
)
game = SimpleNamespace(game_id="preview", day_index=18, away_team="CHI", home_team="NYK")


names = {"CHI": "Chicago Bulls", "NYK": "New York Knicks"}
team_ids = {"CHI": "1610612741", "NYK": "1610612752"}
colors = {"CHI": ("#CE1141", "#000000"), "NYK": ("#006BB6", "#F58426")}
name = lambda team: names.get(team, team)
logo = lambda team: f"https://cdn.nba.com/logos/nba/{team_ids.get(team, '1610612741')}/primary/L/logo.svg"
color = lambda team: colors.get(team, ("#2563eb", "#f59e0b"))

st.set_page_config(page_title="Game Day Broadcast Preview", layout="wide")
st.markdown("<style>.stApp{background:#050a12}.block-container{max-width:1220px;padding-top:2rem}</style>", unsafe_allow_html=True)
inject_game_day_broadcast_visuals_v1()
render_game_day_broadcast_v1(
    state=state,
    game=game,
    active_team="CHI",
    game_date_label="Friday · November 14",
    team_name_resolver=name,
    team_logo_resolver=logo,
    team_colors_resolver=color,
)

st.markdown("## Postgame presentation")
completed = SimpleNamespace(
    away_team="CHI",
    home_team="NYK",
    away_score=117,
    home_score=113,
    overtime_periods=0,
    player_box_scores=(
        SimpleNamespace(player_id="203915", team_abbreviation="CHI", points=28, rebounds=10, assists=12, steals=2, blocks=0),
        SimpleNamespace(player_id="1627739", team_abbreviation="CHI", points=26, rebounds=9, assists=3, steals=1, blocks=1),
        SimpleNamespace(player_id="1628973", team_abbreviation="NYK", points=32, rebounds=3, assists=8, steals=1, blocks=0),
    ),
)
render_game_day_final_v1(
    state=state,
    completed=completed,
    team_name_resolver=name,
    team_logo_resolver=logo,
    team_colors_resolver=color,
)

