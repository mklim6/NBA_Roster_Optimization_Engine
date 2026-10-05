# Expansion 42 — Player development story

Front Office's Development Lab now displays the selected player's recorded development history: annual changes, focused camp outcomes, overall before/after values, and expandable skill changes. Blue bars mark annual events and gold bars mark camps. Positive and negative changes share a zero baseline. Missing ratings remain unavailable. No growth trajectory is generated for players without history.

The read-only backend maps existing annual history and separate camp history to a shared display schema, preserving service-time behavior. Counts and recorded-change totals use all available events; the response retains the latest 40, the chart displays the latest 12, and the timeline shows the latest eight. Copy distinguishes recorded changes from unrecorded gaps and from model projections. Player selection and report refresh replace the previous player's history.

Also clarifies the camp's locked state outside offseason, where healthy roster cards remain available to inspect but execution stays disabled.

Validation: Expansion 42's focused validator covers ordering, missing/non-finite values, camp opportunity costs, bounded history, production roster mapping, chart construction, skill-detail toggles, empty history and refresh clearing. Development Lab regression passes. Desktop inspection verified the actual Boston save's empty history, and a clearly labeled fixture verified populated positive/negative bars and expanding skill details. The fixture never writes either checkpoint. No live game, camp, or season transition was executed.
