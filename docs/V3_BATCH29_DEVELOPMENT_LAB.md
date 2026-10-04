# V3 Batch 29: Development Lab

Adds a portrait-based Development Lab at the top of Front Office, using all rows in the production full-roster development report rather than only the eight-player core summary.

Players can sort by future outlook, potential-minus-overall gap, or age, and filter Rising / Stable / Declining directions. Unknown values sort behind known values. Selecting a card highlights it, updates the outlook panel, and scrolls that panel into view. The panel distinguishes current ability, model potential and future outlook, and shows profile reliability and recorded history count. Missing ratings remain unavailable with no fabricated bars. Refresh clears old roster cards before loading the current report.

This is a development exploration interface. Training, mentorship and role writes require dedicated production integration; no new simulated development actions or fabricated historical growth curves are introduced here.

Validation: Batch 29 runtime fixture passes selection, sorting, filters, empty results, unknown ratings, refresh clearing, grid bounds and compact filter controls. Batch 22 franchise presentation regression passes. Native desktop inspection verified Boston's full 14-player roster, loaded portraits, readable ratings and filter row. V3/V2 checkpoint hashes remain unchanged.
