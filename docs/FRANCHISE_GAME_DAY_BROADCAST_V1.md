# Franchise Game Day Broadcast V1

Version: `franchise-game-day-broadcast-v1.0-2026-09-11`

## Purpose

Game Day now presents each controlled matchup like a compact television broadcast while preserving the existing simulation, health, lineup, what-if, and transactional commit systems.

## Pregame presentation

- Team-color matchup stage with official team marks, records, streaks, recent form, date, season phase, and home/road context.
- Projected starting-five cards built from the currently saved rotations.
- Tale of the tape using top-eight rotation ratings, real season scoring margin, and injury availability.
- Three matchup keys derived from talent, availability, and current season rhythm.
- Responsive desktop and mobile layouts with reduced-motion support.

## Postgame presentation

- Broadcast-style final scoreboard with the real committed score and overtime status.
- Winning-team headline and permanent-franchise-timeline confirmation.
- Three leaders selected from the committed player box score. The display uses points, rebounds, and assists already produced by the simulation.
- The complete existing box-score and medical-result panels remain available below the recap.

## Safety boundary

This module is presentation-only. It does not import checkpoint code, write files, commit games, mutate league state, or generate fictional results. The existing `Simulate game` control remains the only regular-season commit path.

## Validation

Run:

```powershell
C:\Users\klima\miniconda3\envs\nba-roster-optimizer\python.exe src\validate_franchise_game_day_broadcast_v1.py
```

