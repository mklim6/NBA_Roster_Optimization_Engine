# V3 Batch 30: Prospect Dossiers and Draft Presentation

The scouting page now has a branded stage that reflects season scouting, the actual team on the clock and pick number during a draft, or draft completion. Selecting a prospect opens a readable dossier and scrolls it into view. Pinning one report and selecting another creates a side-by-side comparison of scouting estimates, position, school/club, archetype, projected range, report status and confidence.

The full-width board uses taller rows, larger text and school/archetype context. Load More exposes the rest of the class beyond the original 50-row limit, including all 80 prospects in the current save. Search resets the display limit and internal scroll. Scouting, Draft Night and roster-decision controls now use wider cards below the board.

Dossiers show only scouting report fields; confidence is identified as report certainty rather than star probability. Missing ratings or confidence remain unavailable. Comparisons are local to the current page report and clear on refresh. Selecting a new prospect continues to invalidate the prior draft preview. Existing six-prospect focus limits, phase gates, confirmation dialogs, execution requests and persistence safeguards remain in place.

This batch adds presentation and comparison, not a new draft simulation, trade-call system, or generated player portraits.

Validation: Batch 30 runtime fixture covers two-report comparison, pin feedback, confidence and unknown values, phase-stage rendering, loading all 80 rows, final-row reachability, search resets, action-card widths, selection preview invalidation, refresh clearing and absence of write requests. Batch 20K scouting and Batch 22 presentation regressions pass. Native Godot inspection verified live Niko Jovanovic/Micah Bennett comparison, report confidence, larger rows, Load More and wider action panels. V3 and protected V2 checkpoint hashes remain unchanged.
