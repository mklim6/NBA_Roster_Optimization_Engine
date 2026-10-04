# V3 Batch 27: Living Franchise HQ

Replaces the static HQ league-news examples with a team-branded briefing derived from the current working save. The existing branded team hero and next-game spotlight remain above the new briefing.

- Opening-season, streak and offseason headlines from actual record and phase.
- Next-move navigation prioritizes reported injuries, then invalid starter/minute allocations, then game preparation or season transition.
- Season and draft journey cards link to the existing season and scouting tools.
- Finance and availability decision cards open Front Office and Roster; cap estimates and unevaluated morale are explicitly identified.
- League pulse shows up to three actual completed results, with honest loading, empty and unavailable states.
- A full-page scroll keeps every card and the existing metrics accessible.
- Summary refresh triggers a read-only intelligence refresh. A new summary clears previous intelligence; other-team responses are ignored.

This batch provides decision navigation, not a new offer-resolution inbox or simulated consequence engine. It does not add persistent quests, transactions, or simulation actions. Future event-inbox and goal integrations can build on this component.

Validation: Batch 27 Godot runtime fixture covers opening and offseason briefings, action routing, injury and rotation priorities, completed results, team switching, late other-team responses, offline clearing and layout reachability. Batch 22 franchise presentation regression passes. Both protected checkpoints retain their hashes. Native desktop inspection verified Boston's actual 0-0 briefing, SAS matchup, live availability report, empty league report, scrolling and Finance navigation.
