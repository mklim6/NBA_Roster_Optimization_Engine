# NBA Franchise Simulator V2 Roadmap

Status date: September 23, 2026  
Branch: `feature/franchise-v2`  
Stable baseline: `v1.0.0` (`f6e9a49`)

## V2 objective

Build on the protected V1 release without weakening its transaction, save, or
multi-season guarantees. V2 should make the league easier to understand,
faster to operate, and more sustainable across long franchises.

## Completed foundation slice

- Preserved V1 on `main` and the `v1.0.0` tag.
- Added visible five-stage progress while opening the next season.
- Added a read-only League Hub sustainability panel with league-average roster
  size, teams below the 14-player target, free-agent share, roster range, and
  team-level detail.
- Kept the sustainability panel diagnostic: it cannot sign, waive, trade, or
  otherwise mutate the active franchise.
- Added a dedicated V2 foundation validator and passed the project quick gate.

## Recommended implementation order

### 1. Sustainable CPU roster construction

- Diagnose why CPU organizations repeatedly settle below 14 players.
- Improve normal CPU free-agency and post-Draft decision-making rather than
  increasing emergency rescue limits.
- Preserve player acceptance, cap rules, roster limits, and atomic saves.
- Target 14-15 players per organization at opening night, with any exceptions
  explained by an explicit legal constraint.

Acceptance gate: an isolated eight-season protected soak completes with all 30
teams playable, no unexplained roster deterioration, and no active-save change.

### 2. Faster offseason and season-boundary flow

- Profile CPU free agency, roster trimming, and the atomic season transition.
- Remove repeated calculations and cache only immutable/read-only inputs.
- Report timings for each lifecycle stage in the protected soak output.

Acceptance gate: the eight-season protected soak is materially faster than the
V1 benchmark while producing the same validated lifecycle results.

### 3. Front-office decision depth

- Add trade and signing rationale that exposes team need, timeline, cap impact,
  and expected role.
- Add owner and season goals with progress visible from the command center.
- Turn league sustainability signals into recommendations, never silent fixes.

### 4. Presentation and retention polish

- Expand contextual help for first-time users without blocking experienced
  players.
- Add stronger visual summaries for standings, playoff races, awards, roster
  construction, and offseason priorities.
- Keep native Streamlit components, accessible contrast, responsive layouts,
  and a clear primary action on each screen.

## Release discipline

- Develop only on `feature/franchise-v2` until the V2 gate passes.
- Run changes against cloned or temporary franchise state.
- Never use the active franchise as a repair or soak target.
- Require the V2 validator, project quick validation, compilation, save/load
  regression checks, and protected multi-season soak before merging to `main`.

