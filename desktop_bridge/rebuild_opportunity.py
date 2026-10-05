"""Read-only opportunity evidence for a rebuilding workflow."""
from desktop_bridge.development_goals import player_rows


def opportunity_board(checkpoint, team):
    state = checkpoint.simulation_state
    rotation = state.teams[team].rotation
    targets = dict(getattr(rotation, 'minutes_targets', {}) or {})
    starters = set(getattr(rotation, 'starter_ids', ()) or ())
    rows = player_rows(state, team)
    for row in rows:
        row['planned_minutes'] = float(targets.get(row['player_id'], 0) or 0)
        row['starter'] = row['player_id'] in starters
        row['young_core'] = row['age'] is not None and row['age'] <= 25
        row['usage_basis'] = 'season average' if row['games'] else 'no appearances'
    rows.sort(key=lambda row: (-row['planned_minutes'], row['name'], row['player_id']))
    total = sum(float(value) for value in targets.values())
    known = sum(row['planned_minutes'] for row in rows)
    return {
        'players': rows,
        'planned_total': round(total, 2),
        'unrepresented_minutes': round(total - known, 2),
        'young_core_minutes': round(sum(row['planned_minutes'] for row in rows if row['young_core']), 2),
        'read_only': True,
        'scope': 'A minutes worksheet, not a growth forecast or a rotation legality check. Actual usage is the recorded season average. No scenario is saved or applied.'
    }
