"""Evidence-based rolling seven-day franchise briefing. Never writes a save."""
from __future__ import annotations
from desktop_bridge.development_goals import goals_board
from desktop_bridge.rivalry_story_foundation import build_rivalry_story_universe


def build_franchise_pulse(checkpoint, team, inbox, names=None):
    state = checkpoint.simulation_state
    names = names or {}
    day = int(state.current_day_index)
    start = max(0, day - 6)
    season = str(state.settings.season_label)
    stories, results = [], []
    for gid, game in getattr(state, 'completed_games', {}).items():
        if team not in (game.home_team, game.away_team):
            continue
        scheduled = getattr(state, 'schedule', {}).get(str(gid))
        recorded_day = getattr(scheduled, 'day_index', None)
        # Undated games cannot be asserted to belong to this week's window.
        if recorded_day is None or not start <= int(recorded_day) <= day:
            continue
        home = game.home_team == team
        opponent = game.away_team if home else game.home_team
        score = int(game.home_score if home else game.away_score)
        against = int(game.away_score if home else game.home_score)
        results.append(dict(id=str(gid), day=int(recorded_day), opponent=opponent,
                            score=score, against=against, outcome='W' if score > against else 'L'))
    results.sort(key=lambda r: (r['day'], r['id']), reverse=True)
    def add(id, category, title, detail, destination, evidence, priority=2, **extra):
        stories.append(dict(id=id, category=category, title=title, detail=detail,
                            destination=destination, evidence=evidence, priority=priority, **extra))
    for card in inbox.get('cards', []):
        # These are current decisions, not falsely dated events.
        add('decision:'+card['id'], card['category'], card['title'], card['detail'],
            card['destination'], 'Current saved franchise snapshot',
            0 if card['priority']=='Action' else 3, player_id=card.get('player_id',''))
    standing = getattr(state, 'standings', {}).get(team)
    season_record = None
    if standing is not None:
        season_record = dict(wins=int(standing.wins), losses=int(standing.losses))
    for row in getattr(state, 'franchise_transaction_history_v1', []) or []:
        if not isinstance(row, dict) or row.get('status') != 'committed' or row.get('season_label') != season:
            continue
        recorded_day = row.get('day_index')
        teams = (row.get('team_a'), row.get('team_b'))
        if recorded_day is None or team not in teams or not start <= int(recorded_day) <= day:
            continue
        txid = str(row.get('transaction_id', ''))
        if not txid:
            continue
        opponent = teams[1] if teams[0] == team else teams[0]
        players = len(row.get('side_a_player_ids', [])) + len(row.get('side_b_player_ids', []))
        picks = len(row.get('side_a_pick_asset_ids', [])) + len(row.get('side_b_pick_asset_ids', []))
        add('trade:'+txid, 'TRADE WIRE', 'A deal reshapes your roster',
            f"Completed with {names.get(opponent,opponent)} on league day {recorded_day}: {players} players and {picks} draft assets moved. Review your rotation after the deal.",
            'ROSTER', f'Committed franchise transaction ledger · {txid}', 1)
    if results:
        wins = sum(r['outcome']=='W' for r in results)
        latest = results[0]
        add('week:results', 'ON THE COURT', f'{wins} wins in {len(results)} games this week',
            f"Latest: {latest['outcome']} vs {names.get(latest['opponent'],latest['opponent'])}, {latest['score']}–{latest['against']}. Watch the recorded postgame broadcast, then plan your next matchup.",
            'THEATER', f'Recorded games · league days {start}–{day}', 1)
    board = goals_board(checkpoint, team)
    for goal in board['goals']:
        current = goal.get('current')
        value = 'unavailable' if current is None else f'{current:.1f}'
        met = goal['status']=='target_met'
        add('goal:'+goal['player_id'], 'DEVELOPMENT',
            goal['name'] + (' has reached the current target' if met else ' has a season target to chase'),
            f"{goal['metric'].title()}: {value} now / {goal['target']:.1f} target. " +
            ('Opportunity goals require ten appearances. ' if goal['metric']=='opportunity' else '') +
            'This is current progress; the final season outcome is still open.',
            'DEVELOPMENT', goal.get('evidence','Current recorded progress'), 1 if met else 2,
            player_id=goal['player_id'], name=goal['name'])
    if not board['goals'] and board['can_commit']:
        add('goal:agenda', 'BUILD YOUR CORE', 'Give this season a development agenda',
            'Choose up to three players and fixed skill or opportunity targets. Follow their progress through the season.',
            'DEVELOPMENT', 'No saved development agenda for this team and season', 2)
    try:
        story_universe = build_rivalry_story_universe(checkpoint, team, names)
    except Exception:
        # Pulse remains usable even if the optional story layer cannot be built.
        story_universe = {}
    for card in story_universe.get("pulse_cards", []):
        add(
            str(card.get("id", "story:unknown")),
            str(card.get("category", "RIVALRY WATCH")),
            str(card.get("title", "League story")),
            str(card.get("detail", "Review the current rivalry story desk.")),
            "STORIES",
            str(card.get("evidence", "Saved franchise story evidence")),
            int(card.get("priority", 2)),
            player_id=str(card.get("player_id", "")),
            opponent=str(card.get("opponent", "")),
        )
    if not stories:
        add('quiet', 'FRANCHISE WATCH', 'A quiet week is a chance to plan',
            'No actionable stories are available in the saved snapshot. Review your roster and season calendar.',
            'ROSTER', 'Current saved franchise snapshot', 3)
    stories.sort(key=lambda s:(s['priority'],s['id']))
    return dict(team=team, team_name=names.get(team,team), season=season, day=day,
                window_start=start, phase=str(getattr(state.phase, 'value', state.phase)), stories=stories,
                results=results, season_record=season_record, wins=sum(r['outcome']=='W' for r in results),
                losses=sum(r['outcome']=='L' for r in results), read_only=True,
                headline=stories[0]['title'],
                subtitle='Rolling seven-day results and current decisions. Refresh after advancing your franchise.')
