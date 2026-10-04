# Batch 32 — Coaching board

Game Day now presents the simulation engine’s current automatic defensive counter on a schematic half court, alongside the opponent’s primary threat portrait and five modeled threat ratings. Staff traits, personnel execution, and the bounded expected suppression explain the selected plan. The rotation shortcut opens the existing preview/apply controls; refreshing after an applied rotation recalculates the plan.

The GET /v3/coaching-plan endpoint runs production planning functions on a deep copy of the checkpoint state. It does not simulate games, advance the calendar, persist changes, or predict a final score. Manual scheme selection is not added: the production engine still selects its own counter. Court positions are illustrative, not tracking data.

Validation: Batch 32 runtime checks and Batch 22 presentation/simulation-safety regression passed. Checks cover live production data, team orientation, bounded effect, cached-state immutability, both protected save hashes, component rendering, rotation shortcut, offline clearing, and no-matchup state. Desktop inspection verified the BOS/SAS board, player portrait, readable threat bars, and schematic court. No live game was simulated or rotation applied during verification.
