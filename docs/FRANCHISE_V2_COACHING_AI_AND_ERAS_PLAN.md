# Franchise V2 Coaching Intelligence and Eras Plan

Status date: September 30, 2026

## Why this is a priority

The simulator already removes unavailable players, preserves medical minute
limits, reallocates the complete 240 team minutes, and lowers a team's expected
performance when a star is absent. Those are important foundations, but they
do not yet prove that a coach understands why a player matters or how an
opponent should be attacked.

The next coaching milestone must answer three questions with durable evidence:

1. Who replaces an injured player, and which missing basketball roles must be
   redistributed?
2. How does the team change its game plan for the opponent and available
   personnel?
3. Why did this coach choose that response?

This work is part of V2 Coaching Identity and Tactics. Historical starting
points are a separate expansion because they require complete era data as well
as different simulation rules.

## Current implementation audit

### What already works

- Players marked unavailable do not enter a game rotation.
- Medical restrictions and return-to-play minute limits are enforced.
- The simulator fills five starters, constructs a playable rotation, and
  reconciles the team to exactly 240 regulation minutes.
- The saved rotation and health-adjusted player ratings affect team strength,
  expected scoring, the box score, fatigue, and injury risk.
- Rotation Headquarters can recommend a position-balanced starting five from
  the top available rotation candidates.
- All 30 verified current head-coach identities exist in the staff layer.

### What does not yet work

- Automatic game-time injury replacement selects the next healthy player in
  saved rotation priority. It does not optimize the replacement for the
  injured player's position, creation burden, shooting, defense, rebounding,
  or matchup assignment.
- Rotation Headquarters' position optimizer is not the algorithm used by the
  single-game simulator when an injury removes a starter.
- The simulator has no opponent threat model and does not currently select
  drop, switch, hedge, blitz, zone, post-double, help, or rebounding schemes.
- Losing a rim protector can change aggregate team quality and block totals,
  but it does not cause a defensive coverage decision or directly alter the
  opponent's rim/post efficiency.
- Current real-world head-coach data supplies identity and age. Gameplay
  ratings, traits, contracts, and experience are simulator-generated; they are
  not yet evidence-backed reproductions of real coaching systems.
- Staff offense, defense, and rotation indices are displayed and support other
  staff systems, but the current single-game score model does not consume them
  as tactical coaching inputs.

A read-only audit of the active protected save simulated one injury to every
saved starter. Only 57 of 150 automatic replacements shared a listed position
with the missing starter. For injured PF/C starters, 32 of 77 replacements had
a PF/C designation. This is a diagnostic signal, not a final quality metric,
but it confirms that game-time replacement is priority-based rather than
role-aware.

## Coaching Intelligence V2 architecture

### 1. Basketball role layer

Derive transparent roles from existing ratings, positions, per-36 history, and
player fingerprints without changing intrinsic overall ratings:

- primary creator and secondary creator;
- ball handler and pressure release;
- rim scorer, post scorer, screener, and roll threat;
- movement shooter, spot-up spacer, and non-shooter;
- point-of-attack defender and wing stopper;
- rim protector, defensive rebounder, and switchable big;
- transition threat and transition defender.

Each role receives a confidence score and supporting signals. Missing source
data must be labeled as a proxy rather than presented as measured truth.

### 2. Injury impact diagnosis

Before each game, compare the intended rotation with available personnel and
produce a `MissingRoleReport`:

- unavailable player and lost minutes;
- lost usage, playmaking, spacing, rebounding, and defensive role shares;
- starting-position vacancy;
- roles with no viable replacement;
- candidates capable of absorbing each responsibility.

A LeBron-type absence should therefore be understood as more than losing one
forward. It can remove a starter, a primary creator, a transition initiator,
paint pressure, and high-leverage minutes.

### 3. Rotation and lineup optimizer

Score candidate rotations and starting groups on:

- healthy availability and medical caps;
- saved role hierarchy and promised minutes;
- positional and role coverage;
- lineup creation, spacing, point-of-attack defense, rim protection, and
  rebounding;
- opponent threats and likely matchups;
- coach rotation preferences and adaptability;
- fatigue, schedule density, development priority, and playoff context.

The optimizer must retain bounded behavior. It may shorten a rotation or use a
small lineup when justified, but it cannot ignore medical limits, invent a
position, or silently override a user-controlled rotation. Every material
change receives a reason code.

### 4. Opponent threat and scheme engine

Build a read-only opponent profile from the expected rotation:

- primary and secondary creators;
- rim/post scoring pressure;
- pull-up and catch-and-shoot volume;
- offensive rebounding and size;
- turnover pressure and transition frequency;
- weak defenders and players who can be helped off.

The coaching policy then selects bounded tactics such as pace, offensive
emphasis, shot profile, star usage, matchup assignments, pick-and-roll
coverage, post doubles, help intensity, switching, zone frequency, and crash
versus transition balance.

Example: if a team's only strong rim protector is unavailable against a
dominant center, the coach may prioritize the best remaining defensive big,
send earlier post help, reduce pace, emphasize defensive rebounding, and accept
some additional kick-out threes. A switch-heavy small lineup is another
possible response when the roster and coach profile support it. The model must
represent those tradeoffs rather than grant a universal defensive bonus.

### 5. Coach identity and adaptation

Each coach needs a versioned profile containing:

- preferred offensive family, pace, shot profile, and play-type emphasis;
- preferred base defense and pick-and-roll coverages;
- switching, zone, double-team, help, and rebounding tendencies;
- rotation length, starter trust, development tolerance, load management, and
  playoff shortening;
- adaptability, experimentation, and adjustment speed;
- source and as-of date for every real-world tendency.

Real coach identities must not be used to imply authentic strategy unless the
strategy fields have retained evidence. Until then, the UI should distinguish
`verified identity`, `source-derived tendency`, and `simulated attribute`.

Coach quality should affect decision quality, not create hidden rating boosts.
A better or more adaptable coach more often selects a strong response from the
available options, while every coach remains constrained by roster personnel
and imperfect information.

### 6. Simulation integration

Tactics should modify basketball events rather than overwrite player ratings:

- pace and possession count;
- rim, midrange, and three-point attempt mix;
- expected shot quality and contest strength;
- turnover and assist opportunities;
- offensive and defensive rebound rates;
- foul and free-throw pressure;
- usage, touches, and minutes by role;
- matchup-specific scoring and defensive outcomes.

Effects must be capped and calibrated. Fast simulation should consume the same
pregame coaching decision as a future possession gamecast so both paths tell
the same basketball story.

### 7. Explainability and UI

Game Day should show a compact coaching report:

- `Personnel problem`: who is unavailable and which roles are missing;
- `Rotation response`: promoted starter, minutes redistribution, and lineup
  shape;
- `Opponent threat`: the two or three priorities driving the plan;
- `Coach adjustment`: selected tactics and the expected tradeoff;
- `After the game`: whether the adjustment worked, backed by box-score or
  gamecast evidence.

This is legitimate explainable decision AI even if its first version uses a
deterministic utility policy instead of a black-box machine-learning model. The
proof is counterfactual behavior, repeatable tests, bounded decisions, and an
auditable reason trail.

## Required validation

### Primary-creator injury scenario

- Remove a healthy star creator from an otherwise fixed lineup.
- The player must receive zero minutes.
- The replacement starting five must remain position- and role-viable.
- Lost creation and usage must be redistributed to plausible teammates.
- Expected offense must decline by a plausible amount, not collapse to zero.
- The decision record must identify the lost roles and selected replacements.

### Rim-protector injury versus dominant center

- Run the same matchup with the rim protector healthy and unavailable.
- The unavailable player must receive zero minutes.
- The coach must select a personnel and coverage response supported by its
  profile and remaining roster.
- The opponent center's rim/post efficiency or free-throw pressure should
  change detectably across a fixed-seed batch.
- More help must carry a measurable cost such as kick-out three quality,
  offensive rebounding exposure, or fouls.

### Coach identity scenario

- Give two coaches the same roster, opponent, health, and random seed.
- Their profiles must be able to produce different, explainable plans.
- Replacing a coach must not directly change any player rating.
- A coach's decision and rationale must survive save/load.

### Calibration gate

- Run at least 500 controlled games per major tactic comparison.
- Require statistically detectable directional effects, not a guaranteed
  outcome in every game.
- Run a full 1,230-game season and retain plausible league pace, efficiency,
  shot distribution, rebounds, assists, turnovers, fouls, and player identity.
- Add the scenarios to unified validation and protected save/load regression.

## Delivery sequence and estimate

| Step | Deliverable | Estimate |
| --- | --- | ---: |
| 1 | Role model plus current-behavior benchmark | 4-7 hours |
| 2 | Injury impact report and role-aware rotation optimizer | 7-12 hours |
| 3 | Opponent threat model and bounded scheme policy | 8-14 hours |
| 4 | Simulator event integration and coaching rationale | 8-14 hours |
| 5 | Game Day coaching report and calibration suite | 6-10 hours |
| **Coaching Intelligence V2 total** |  | **33-57 hours** |

The first demonstrable milestone is Steps 1-2. It can answer the meeting's
LeBron-style injury question with working code and tests before the full scheme
engine is complete.

## Real-life coaching profiles

Realistic coaching identity is feasible, but it requires a retained source
layer rather than hand-written reputation labels. A seasonal ingestion should
collect or derive team and coach tendencies such as pace, three-point attempt
rate, rim and midrange mix, assist rate, transition frequency, offensive
rebounding, rotation size, starter minutes, and documented defensive coverage.

The current repository contains verified coach names but not a complete
coverage/play-type dataset. It also explicitly identifies missing direct rim
frequency and rim-efficiency data. Initial coach profiles can use transparent
team-level proxies, but the UI and audit output must label which tendencies are
measured, inferred, or simulated.

## Historical Eras mode

Eras are technically feasible because the persistent league, schedule,
postseason, development, transaction, and checkpoint engines can be reused.
They are not merely historical rosters. Each era package needs:

- teams, franchises, relocations, conferences, divisions, logos, and schedule;
- complete opening rosters, ages, ratings, skills, contracts, and free agents;
- coaches and source-backed tactical profiles;
- real draft classes and pick ownership for the starting horizon;
- salary cap, roster rules, free-agency rules, trade rules, lottery, playoff
  format, and expansion timeline;
- era-specific pace, efficiency, three-point volume, foul environment, minutes,
  injury, development, and aging calibration;
- presentation theme and legally distributable visual assets.

The repository already has strong player-season data from 2014-15 through
2025-26 and draft-outcome data covering 2014 through 2022. It does not contain
a complete set of historical rosters, contracts, transaction rights, coaches,
or rule packages for classic decades.

### Recommended eras path

1. Build an `EraManifest` interface while keeping the current 2026-27 universe
   as the default manifest.
2. Prove engine parameterization with a fictional rules fixture.
3. Create one Modern Era pilot, preferably a season within the existing
   2014-15 through 2025-26 statistical coverage.
4. Validate its roster, schedule, rules, contracts, Draft, and full-season
   statistical environment.
5. Only then scope classic 1980s, 1990s, or 2000s packages, which require major
   new data acquisition and licensing review.

| Eras scope | Estimate |
| --- | ---: |
| Era-manifest architecture and migration tests | 12-20 hours |
| One modern historical pilot with available statistical data | 30-55 hours |
| Each well-researched additional modern era | 20-40 hours |
| A classic-era foundation with new data/rules pipeline | 80-150+ hours |

Historical Eras should remain V2.1/V3 expansion work. Coaching Intelligence
belongs in focused V2 because it improves every game in the current franchise
and directly answers the strongest technical question raised in the meeting.
