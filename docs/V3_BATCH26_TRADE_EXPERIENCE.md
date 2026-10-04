# Batch 26 — Trade Center visual experience

Implemented October 4, 2026, after committed Batches 24 and 25.

## Changes

- Two team-branded package panels show outgoing and incoming players with large portraits, team logos, positions, ratings, draft rights, and current salary totals.
- A live package-state indicator reflects the existing preview gate, including Ready to confirm and Preview rejected.
- Player assets are selectable portrait cards with salary, age, overall, and selection borders. Draft rights retain exact asset IDs and readiness labels.
- The builder uses branded asset-board headers. Asset lists have usable minimum heights and scroll independently within the full page.
- Trade Finder proposals use larger cards and partner logos. Finder appears after the builder and legality preview, prioritizing package construction.
- Package views show up to three portraits and two named draft rights per side, with additional counts and tooltips. Request payloads retain every selected ID.
- Unknown salaries remain unavailable and suppress numeric salary differences. Current salary comparisons do not replace the engine's season-specific salary matching or legality calculation.

## Verification

Passed validators: Batch 26 trade experience, Batch 20I trade presentation, Batch 22 franchise presentation, Batch 25 free agency, Batch 24 roster/player experience, Batch 24.5 roster usability, and Batch 08 transactional trade execution. `git diff --check` passes.

Runtime fixtures exercise native checkbox selection, exact request IDs, player portraits and team logos, draft-right summaries, known and unknown salaries, larger packages, proposal loading, clear-package behavior, stale preview rejection, scroll reachability, unclipped layouts, and execution gating.

Desktop inspection covered the loaded BOS/ATL assets, selection of both package sides, larger feature portraits, asset-board scrolling, page scrolling, and a read-only legality preview. The live test package was rejected by the engine's financial rules and Execute Trade remained disabled. The live Trade Finder returned no proposals; populated proposal cards were verified with fixtures.

All validation checks confirmed unchanged active V3 and protected V2 save hashes. No trade was executed, no simulation rules changed, and no bridge or Python engine code changed.

## Files

- `godot_client/scripts/trade_center_v3.gd`
- `godot_client/scripts/trade_asset_card_v3.gd`
- `godot_client/scripts/trade_package_stage_v3.gd`
- `src/validate_v3_batch26_trade_experience.py`

Recorded as a separate Batch 26 commit. Existing Batch 24 and 25 commits are preserved.
