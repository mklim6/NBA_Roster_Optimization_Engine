# V3 Batch 28: Postgame Spotlight

Adds a portrait scoring-leader card for each team and a visual comparison of recorded rebounds, assists, turnovers and made threes between the final scoreboard and existing full box scores. Totals derive from saved player lines, and incomplete fields remain unavailable. Controlled-team orientation works for home and away games. Resetting the postgame panel removes the previous game and portraits.

No shot coordinates or possession feed are exposed by this payload, so this batch does not invent a shot map, momentum timeline or interactive replay. Existing simulation confirmation and persistence gates remain unchanged.

Validation: Batch 28 fixture passes portrait rendering, away orientation, totals, missing/empty data, reset and simulation inactivity. Batch 21B.1 cinematic regression passes. Native desktop inspection used explicitly constructed sample box-score data and verified both portrait cards and comparison bars. Protected V3/V2 checkpoint hashes are unchanged.
