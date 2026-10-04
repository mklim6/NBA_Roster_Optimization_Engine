# Batch 25 — Free Agency experience

Implemented October 4, 2026, over the uncommitted Batch 24 roster work.

## Behavior

- The market board uses player portraits, prominent overall ratings, position, age, potential, and reference salary.
- The contract desk shows the selected player's portrait and identity. Selecting another player updates the portrait and invalidates the previous offer preview.
- Market snapshot reports available players, highest known overall, and lowest known salary reference. Missing references remain unavailable.
- Sort by market order, highest overall, lowest salary, or youngest first. Unknown numeric values sort after known values; ties use name and player ID.
- Search, position, and reference-salary filters combine. Salary ceilings exclude unknown references; an explicit Salary unavailable filter finds those players.
- Load More adds 80 players at a time. Changing discovery filters resets the visible limit and scroll position. All 186 players in the current live market were accessible during inspection.
- Refresh clears selections for players who are no longer in the market.
- Reusing a portrait cancels the previous player's pending request, preventing an old response from updating the new player's portrait or cache entry.

## Validation

Passed: Batch 25 discovery/runtime validation; Batch 20H free agency; Batch 20A portrait media; Batch 20C profiles; Batch 21A.1 roster portraits; Batch 22 franchise presentation; Batch 24 roster/player experience; Batch 24.5 usability; Batch 09 transactional free agency. `git diff --check` passes.

The legacy Batch 20A validator was updated to inspect portraits inside its roster row and player-profile overlay rather than counting all portraits in the application. It recognizes the Batch 24 profile component and exits with named failures instead of leaving Godot running after an assertion.

Desktop checks covered player selection and switching, youngest-first sorting, outer-page scrolling, expansion from 80 to 160 to 186 players, scrolling to the final player, and a live offer preview. The current regular-season preview remained blocked and Sign Player stayed disabled. No signing was submitted.

Every validation confirmed unchanged active V3 and protected V2 save hashes. No Python engine, bridge endpoint, contract rules, or signing execution logic changed.

## Current-data limitation

The current live market supplies no salary references. The screen displays this explicitly; salary-ceiling behavior is verified using fixtures with known, zero, and unknown salaries. References are comparison values, not asking prices or guarantees of eligibility.

## Files

- `godot_client/scripts/free_agency_center_v3.gd`
- `godot_client/scripts/market_player_card_v3.gd`
- `godot_client/scripts/player_portrait_v3.gd`
- `src/validate_v3_batch25_free_agency_experience.py`
- `src/validate_v3_batch20a_visual_media.py`

Batch 24 is recorded in commit `e9af1b3`. Batch 25 is recorded separately with this document, keeping the roster and free-agency changes independently reviewable.
