# Batch 33 — Season Momentum

Franchise HQ now includes a visual season-progress board with four win milestones (1, 10, 25, and 40 wins), a countdown to the next milestone, gold reached cards, and progress bars. After games are completed, a five-game form ribbon shows opponent logos, venue, scores, and wins/losses. A cumulative scoring-margin chart traces points scored minus points allowed across the current saved schedule.

Milestones are presentation goals derived from current standings; they do not award currencies or alter simulation rules. Saved games must belong to the controlled team and have a matching current-season schedule entry. Missing win records stay unknown. The opening-season state has no invented results or margin. The existing HQ refresh and team-switch flow clears previous reports.

Validation: Batch 33 passed production endpoint, cached-state immutability, both protected save hashes, home/away scoring, recent-five selection, milestone thresholds and completion, negative margin, missing records, opening-season, runtime rendering, and offline-clearing checks. Batch 27 HQ regression passed navigation, availability priorities, save-switch safety, and scroll layout. Desktop inspection verified the live Boston 0–0 opening state and a separate fixture preview containing completed results and a chart. No live games were simulated and no live save was changed.
