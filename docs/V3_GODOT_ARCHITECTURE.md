# V3 Desktop Architecture — Phase 1

## Goal

Move presentation from Streamlit toward a standalone graphical Godot client while preserving the validated V2 Python simulation engine.

V3 should be an architectural evolution, not a rewrite of the basketball logic that V2 already validated.

## Boundary

```text
Godot desktop client
        |
        | localhost JSON requests
        v
V3 Python desktop bridge
        |
        | explicit adapters / commands
        v
Validated V2 simulation engine
        |
        v
Local runtime save/checkpoint state
```

### Godot owns

- navigation
- layouts
- animation
- graphical presentation
- input and interaction
- desktop packaging
- future 2D game presentation

### Python owns

- simulation rules
- CPU front offices
- contracts / CBA
- trades
- free agency
- drafting
- player development and aging
- injuries, fatigue, morale and chemistry
- coaching intelligence
- league progression
- durable franchise state
- validation of basketball logic

## Why the bridge is separate

Godot should never need to know how a trade, contract, game, or offseason is simulated. It should request a well-defined action from the Python engine and render the response.

Examples of the future API boundary:

```text
GET  /v3/franchise/summary
GET  /v3/team/{team_id}/roster
GET  /v3/league/standings
GET  /v3/player/{player_id}
POST /v3/game/{game_id}/simulate
POST /v3/trade/propose
POST /v3/free-agency/offer
POST /v3/franchise/advance-day
```

Write operations are intentionally excluded from Phase 1.

## Phase 1 vertical slice

Phase 1 should prove only these things:

1. Godot boots into a polished franchise dashboard shell.
2. A local Python bridge launches with the existing Python environment.
3. Godot can call `/health` and display engine connection state.
4. The bridge does not read or write the active franchise save.
5. V2 Streamlit remains fully runnable and unchanged.

## Phase 2: real read-only franchise data

Create an adapter between the existing checkpoint/runtime model and a stable V3 view model.

First screens:

- franchise home
- roster / depth chart
- player profile
- standings
- schedule
- league transactions

The adapter should read a safe snapshot or cloned checkpoint representation rather than inventing a second source of truth.

## Phase 3: one complete gameplay loop

Implement a narrow command surface:

1. open franchise
2. inspect roster
3. open next game
4. simulate/commit one game through the existing engine
5. refresh standings and player/team data
6. save
7. close and reopen successfully

Only after that loop passes should additional Streamlit surfaces be migrated.

## Phase 4: V3-only systems

Once the desktop architecture is stable, build new systems against the engine/UI boundary instead of directly into Streamlit:

- historical Eras framework
- historical rules/economics profiles
- alternate-history draft timelines
- league expansion/relocation and rule evolution
- GM career and ownership expectations
- deeper agent/player personalities
- league news and rumor system
- scouting uncertainty and interviews/workouts
- animated draft/free-agency presentation
- later 2D game viewer

## Eras architecture direction

Do not implement Eras as a collection of UI flags. The simulation engine should eventually resolve a season-level rules profile, for example:

```python
EraDefinition(
    season=1996,
    cap_model=...,
    contract_rules=...,
    roster_rules=...,
    lottery_rules=...,
    pace_environment=...,
    shot_profile=...,
    cpu_strategy_profile=...,
)
```

That allows one simulation engine to support historical, modern, future, and custom leagues without duplicating front-office logic.

## Non-negotiable V3 migration principles

- V2 remains the stable release until a desktop milestone surpasses it.
- No rewrite of validated systems merely to change UI technology.
- Active saves are never development sandboxes.
- Add adapters before adding direct cross-layer imports.
- Every write command needs explicit validation and failure semantics.
- New V3 features should remain deterministic/testable from Python where practical.
