# V3 Expansion 49 — Rebuild HQ + Guided Franchise Experience

Expansion 49 is an information-architecture and onboarding overhaul.

Its goal is not to add another isolated simulator subsystem. It makes the systems already
built easier to discover, easier to understand, and easier to care about.

## Core idea

A new **REBUILD HQ** organizes the franchise around the question:

> What should I care about right now?

Development is intentionally the first major system introduced to a new user.

## Rebuild HQ

The new page includes:

- Team-branded Rebuild HQ hero
- Current rebuild direction
- Development-first Young Core dashboard
- Ranked "What should I care about right now?" recommendations
- Five selectable front-office directions
- Evidence-based Franchise Journey
- Feature Academy explaining why major systems matter
- System map showing how Development, Scouting, Transactions, Game Day, Pulse, Stories,
  Theater and Legacy connect
- Guided six-step startup onboarding
- Direct actions into existing production systems

## Front-office directions

The player can choose one of five UX lenses:

- Develop the Young Core
- Contend Now
- Rebuild Through the Draft
- Create Cap Flexibility
- Balanced Front Office

This is explicitly **not** a gameplay modifier. It does not change player ratings, CPU logic,
rotation minutes, transactions, draft results, development rates or simulation outcomes.
It changes only what Rebuild HQ emphasizes.

The selected strategy is stored in a separate desktop UX metadata file outside every
franchise checkpoint.

## Franchise Journey

Journey progress is reconstructed from actual franchise evidence rather than clicks:

- roster exists
- valid 5-starter / 240-minute rotation
- season development goals committed
- real game sample reached
- scouting weeks completed
- prospect focus selected
- draft capital exists
- sustainable roster size
- committed franchise transaction history
- games played

It is not an achievement system and does not award bonuses.

## Guided onboarding

The old startup tutorial is replaced by a Rebuild HQ onboarding sequence that teaches:

1. the rebuild loop
2. player development first
3. team-building direction
4. scouting before Draft Night
5. using Trades / Free Agency for a reason
6. living with the team through Game Day, Locker Room, Pulse, Stories and Legacy

Finishing startup onboarding routes directly to Development Command Center.

The Settings tutorial remains available and is expanded into a nine-step reference tutorial.

## Navigation overhaul

Permanent sidebar navigation is reduced and reorganized around player goals:

### COMMAND
- Home
- Rebuild HQ
- Inbox

### BUILD YOUR TEAM
- Development
- Roster
- Locker Room

### SEASON
- Game Day
- Season

### BUILD THE FUTURE
- Scouting
- Trades
- Free Agency
- Offseason

### LEAGUE
- League
- Legacy

### SYSTEM
- Franchises
- Settings

Pulse, Theater, Stories and Front Office remain fully functional but become contextual
destinations surfaced through Rebuild HQ, Home, Game Day and other relevant systems.

## Safety

Expansion 49 adds:

- `GET /v3/rebuild-hq`
- `POST /v3/rebuild-hq`

The POST route can only update separate desktop UX metadata:
- selected Rebuild HQ strategy
- onboarding completion state

It cannot write:
- simulation state
- player ratings
- rotation state
- transaction state
- development results
- protected V2

The endpoint hashes both the active V3 working checkpoint and protected V2 checkpoint before
and after every request.

API version advances to **0.26.0**.

## Guided feature discovery polish

Eight contextual page guides now live in the desktop shell: Development, Roster,
Locker Room, Scouting, Trades, Free Agency, Game Day and Offseason. They open on
request above the live page, explain a decision sequence, and link to related
systems. Development starts with the core, fixed season goals, real opportunity,
and the camp/mentoring path. Guides never select goals or execute franchise actions.

Completing a guide stores only its read flag in Godot's local
`user://feature_guides_v1.cfg`. Read flags mean tutorial completion, not gameplay
achievement. Guides can be reopened. Entering another page resets the step and
closes the previous guide.

Rebuild HQ's Team Direction, Franchise Journey, Feature Academy, and System Map
are expandable sections. The young core and immediate priorities remain visible.
Expansion state survives payload refreshes within the page instance.

Runtime coverage exercises every guide, preference reload, related-page navigation,
unsupported-page hiding, and section expansion. Expansion 49 and Development 44
validators pass after this UI change.

Young Core cards also open a focused player review in Development. The review uses
the current development board's real skill ratings, appearances and minutes. An
explicit draft button selects that player in an empty goal slot, preserves other
choices, prevents duplicate selection and reveals the form. It cannot overwrite
committed season targets or save a plan. Preview and confirmation remain required.
Runtime tests cover repeated drafts, other-player and metric preservation,
committed-plan protection and departed-player focus cleanup.
