# V3 Expansion 48 — Rivalries + League Stories

Expansion 48 adds a read-only living-story layer built from the franchise universe itself.

## Evidence model

Rivalry heat is reconstructed from saved V3 games, playoff meetings, close finishes, overtime,
Finals pairings, and completed best-of-seven playoff series. Historical real-world NBA rivalries
are not assumed. A franchise that has never played an opponent in the V3 universe begins at
`HISTORY BUILDING`.

The tiers are:
- HISTORY BUILDING
- EMERGING
- HEATED
- MAJOR
- HISTORIC

Playoff eliminations are deliberately conservative. Expansion 48 credits a series winner only
when one team has at least four saved wins against the other in that postseason meeting.

## Storylines

The story engine can surface:
- Finals rematches
- playoff rematches
- rivalry games
- revenge opportunities after a saved loss
- current star matchups
- former-player return games supported by committed franchise trade history
- .600+ contender clashes after both teams have played at least ten games
- five-game-or-longer streak games
- league-wide Finals rematches

## Presentation

The new STORIES page includes:
- a next-game matchup poster
- current star-vs-star presentation
- Rivalry Heat Board
- selectable Rivalry Dossier
- postseason chapter history
- head-to-head timeline
- active story feed
- former-player return watch
- league story wire
- links to Game Day, Theater, Legacy, Locker Room and Franchise Pulse

Franchise Pulse receives evidence-backed story cards from the same foundation.

## Safety

`GET /v3/rivalry-stories` is read-only. The endpoint checks the V3 working checkpoint and
protected V2 checkpoint hashes before and after building the story payload. Expansion 48 adds
no POST route and no save function.

API version: 0.25.0
