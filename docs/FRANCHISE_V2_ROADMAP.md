# NBA Franchise Simulator V2 Roadmap

Status date: September 23, 2026

Development branch: `feature/franchise-v2`

Protected V1 baseline: `v1.0.0` (`f6e9a49`)

V2 foundation checkpoint: `3c9a0dc`

## Product goal

V2 will not try to reproduce NBA 2K's real-time 3D basketball. Its goal is to
rival a major franchise mode where this project can be strongest: transparent
front-office decisions, realistic league evolution, meaningful uncertainty,
fast multi-season play, and durable consequences.

The intended player loop is:

`Decision -> game result -> league reaction -> long-term consequence -> new decision`

## Definition of V2.0

V2.0 is ready when a user can run a franchise for at least eight complete
seasons and consistently see:

- all 30 organizations construct legal, playable and sustainable rosters;
- CPU signings, trades and draft choices that match team direction;
- uncertain scouting and player-development outcomes;
- meaningful owner, staff and player consequences;
- tactical choices that visibly affect simulated games;
- league stories that explain why the universe is changing;
- faster offseason and season-boundary execution;
- exact save/load recovery with no corruption or silent repair.

Expansion, historical eras and multiplayer are valuable, but they are not
required to call the focused V2.0 release complete.

## Current baseline

### Stable systems inherited from V1

- Persistent multi-season franchise state and atomic checkpoints
- Regular season, postseason, awards, lottery, draft and offseason lifecycle
- Trade Machine, Free Agency, player ratings and game simulation
- Contracts, CBA checks, injuries, fatigue, morale, staff and development
- CPU front-office direction, CPU trade activity and incoming trade calls
- Tutorials, progression guidance, season journey and visual command center
- Protected soak, save/load, recovery and release validation tooling

### Completed V2 foundation

- V1 preserved on `main` and tagged `v1.0.0`.
- V2 work isolated on `feature/franchise-v2`.
- Five-stage feedback added to the next-season transition.
- Read-only roster sustainability monitoring added to League Hub.
- Dedicated V2 foundation validation added.
- Proprietary ownership notice added for Matthew Klima and included in release
  packaging.

### Measured starting problem

The protected 2027-28 checkpoint currently reports:

| Signal | Baseline |
| --- | ---: |
| Average roster size | 10.8 |
| Teams below the 14-player V2 target | 29 |
| Teams on target | 1 |
| Free agents | 320 |
| Free-agent share of player population | 50% |
| Roster range | 8-14 |

This concentrates the first V2 milestone on repeat-offseason roster economics.
The solution must improve normal CPU decision-making; increasing emergency
rescue limits is not an acceptable fix.

## Delivery plan

### Phase 1: Sustainable CPU roster construction

Estimated effort: **25-45 hours**

Priority: **Release blocker**

Deliverables:

- Trace every player exit, unsigned free agent, failed offer and roster deficit
  across contract closeout, Free Agency, the Draft and post-Draft trimming.
- Give each CPU team an opening-night roster plan targeting 14-15 players,
  positional depth and legal salary commitments.
- Allow only legal, player-accepted contracts through normal transaction paths.
- Add explicit reason codes for every unresolved roster spot.
- Prevent a trim, rights decision or offseason transition from undoing depth
  acquired earlier in the same offseason.
- Extend the sustainability panel with trend and cause data.

Acceptance gate:

- An isolated eight-season protected soak completes.
- All 30 teams are playable at every regular-season boundary.
- Each team opens with 14-15 players, or reports a specific tested legal reason
  why the target cannot be reached.
- Roster counts do not deteriorate from one offseason to the next.
- No rescue-limit increase is used to manufacture a pass.
- The active franchise checkpoint hash remains unchanged during protected tests.

### Phase 2: Explainable CPU general managers and contract market

Estimated effort: **20-35 hours**

Depends on: **Phase 1**

Deliverables:

- Maintain a durable team direction: title push, contender, retool, develop or
  rebuild.
- Give every signing, trade, waiver and draft decision an auditable rationale.
- Combine team need, role, age curve, cap impact, roster timeline, asset value
  and player acceptance in one decision context.
- Improve multi-year salary planning, exception use, tax/apron awareness and
  minimum-contract behavior.
- Add player role and minutes expectations to negotiations.
- Prevent circular sign-and-waive behavior and repeated low-value market scans.

Acceptance gate:

- A sampled transaction from every CPU team has a coherent reason record.
- Team actions agree with team direction and owned assets.
- Contract values pass the existing market-value audit plus new distribution
  checks by age, role, overall and salary-cap percentage.
- CPU activity never silently bypasses CBA, roster or acceptance rules.

### Phase 3: Scouting uncertainty, Draft Night and development

Estimated effort: **20-35 hours**

Depends on: **stable player and contract population from Phases 1-2**

Deliverables:

- Replace universal exact prospect knowledge with scouted attribute ranges and
  confidence levels.
- Add scouting assignments, combine results, interviews, medical information,
  workouts and player comparisons.
- Add dynamic mock drafts and visible draft-stock movement.
- Create durable personality, work ethic, development and risk traits.
- Produce believable sleepers, late bloomers, busts and stars without arbitrary
  one-season rating jumps.
- Make CPU draft boards reflect team need, upside, readiness and organizational
  timeline.

Acceptance gate:

- Draft outcomes are deterministic under a fixed seed and variable under a new
  seed.
- Hidden truth never leaks into user-facing screens before it is scouted.
- CPU teams do not repeatedly draft redundant players without a documented
  best-player-available reason.
- Ten-season development distributions remain within calibrated bounds.

### Phase 4: GM career, goals and relationships

Estimated effort: **15-25 hours**

Depends on: **Phases 1-2**

Deliverables:

- Add owner expectations, season goals and multi-year organizational mandates.
- Track fan approval, owner trust, player trust, staff relationships, GM
  reputation and job security.
- Support promises involving role, minutes, contention and development.
- Add a concise decision inbox with a small number of meaningful conversations.
- Record a GM resume with championships, awards, draft successes, trades,
  financial performance and franchise records.
- Allow future offers from other teams after meaningful career milestones.

Acceptance gate:

- Goals are measurable from durable state and cannot complete through UI-only
  flags.
- Broken and completed promises produce visible, proportionate consequences.
- Relationship changes survive save/load and season transitions.
- No decision can mutate league state before explicit user confirmation.

### Phase 5: Coaching identity, tactics and gamecast

Estimated effort: **25-45 hours**

Depends on: **stable ratings, roles and staff state**

Deliverables:

- Add offensive scheme, defensive coverage, pace, shot-profile and rotation
  priorities.
- Add matchup assignments, bench staggering, playoff rotation shortening,
  development minutes and load management.
- Make coach strengths, roster fit and tactical counters affect simulations in
  explainable ways.
- Add a visual gamecast with score flow, win probability, rotation timeline,
  shot distribution, momentum events and key tactical adjustments.
- Preserve a fast simulation path for users who do not want possession-level
  presentation.

Acceptance gate:

- Changing a meaningful tactic produces a statistically detectable effect over
  controlled simulation batches.
- Tactical effects do not directly overwrite player ratings.
- Team statistical profiles remain plausible across a full season.
- Gamecast totals reconcile exactly with the committed box score.

### Phase 6: Living league and retention loop

Estimated effort: **15-25 hours**

Depends on: **events emitted by Phases 2-5**

Deliverables:

- Weekly league digest and transaction ticker
- Trade rumors, power rankings and playoff-race summaries
- Draft-stock, contract-year and player-development stories
- Rivalries, milestones, records and farewell tours
- Championship banners, dynasty rankings and franchise timelines
- A complete visual season recap with decisions, turning points and legacy
  changes
- Return-to-franchise summary explaining what changed since the previous visit

Acceptance gate:

- Every generated story links to durable league evidence.
- Duplicate and contradictory stories are suppressed.
- The home screen always presents one clear next action.
- Story generation adds negligible time to bulk simulation.

### Phase 7: Performance, regression and V2 release gate

Estimated effort: **15-25 hours**

Depends on: **Phases 1-6**

Deliverables:

- Profile Free Agency, CPU decisions, Draft processing and season boundaries.
- Remove repeated calculations and cache only immutable or read-only inputs.
- Record stage timings and population checks in protected soak reports.
- Add backward-compatible migration for every new V2 save field.
- Complete responsive Streamlit review, recovery test and clean release build.
- Produce V2 release notes and update the ownership-bearing packaged archive.

Acceptance gate:

- Project quick and full validations pass.
- All project Python files compile.
- V1 saves load into V2 through an explicit tested migration.
- Save/load round trips preserve operational signatures.
- Eight-season protected soak passes; seasons 9-10 are an optional confidence
  extension.
- Protected lifecycle runtime improves by at least 30% from the stored V1
  benchmark on the same machine, unless profiling documents a justified limit.
- The active franchise and recovery family remain byte-for-byte unchanged.

## Schedule and effort

| Milestone | Included phases | Estimated hours |
| --- | --- | ---: |
| Simulation trust | 1-2 | 45-80 |
| Franchise depth | 3-4 | 35-60 |
| Game and league immersion | 5-6 | 40-70 |
| Optimization and release | 7 | 15-25 |
| **Focused V2.0 total** | **1-7** | **135-235** |

These are focused implementation and verification hours, not calendar time.
Unexpected legacy-state migrations or deep-season defects should be handled
inside the phase that exposes them rather than deferred to the final gate.

## V2.1 stretch backlog

Begin only after the V2.0 gate passes:

- Expansion teams and expansion Draft
- Relocation, rebranding and custom team identity
- League-rule voting and commissioner settings
- Custom rosters and shareable franchise scenarios
- Salary-cap, lottery and playoff-format controls
- Historic starting points and era-specific presentation
- Cloud or multiplayer leagues

Estimated additional effort: **35-70 hours** for commissioner customization;
historical eras and multiplayer require separate project plans.

## Explicitly outside V2.0

- A real-time 3D basketball engine
- Licensed NBA broadcasts or unlicensed redistribution of protected media
- A complete set of historical rosters and contracts
- Competitive online infrastructure
- Monetization, virtual currency or card-collection systems

## Engineering rules

- Develop V2 only on `feature/franchise-v2` until its release gate passes.
- Never use the active franchise as a repair, migration or soak target.
- Run mutation tests against cloned or temporary checkpoint families.
- Route every state change through the existing legal transaction and atomic
  checkpoint paths.
- Add new save fields with versioning, safe defaults and tested V1 migration.
- Preserve deterministic seeds in tests and include the seed in failure reports.
- Prefer explanation and reason codes over silent correction.
- Do not weaken validation to make a failing soak pass.
- Keep Streamlit views responsive, accessible and based on native components
  unless a custom visual materially improves the experience.

## Validation matrix

Every phase must provide proportionate coverage:

| Layer | Minimum evidence |
| --- | --- |
| Unit | Pure decision and calculation tests |
| Scenario | Healthy, edge and failure fixtures |
| Integration | Full lifecycle path through durable state |
| Save/load | Exact operational-signature round trip |
| Multi-season | Protected soak with stage and population reporting |
| UI | Read-only rendering plus guarded mutation controls |
| Release | Clean archive, license inclusion and recovery smoke test |

## Immediate next checkpoint

Start Phase 1 with a protected roster-lifecycle trace. For every team and every
offseason stage, capture:

- roster count before and after the stage;
- expired, waived, drafted and signed player IDs;
- attempted offers and rejection reasons;
- available roster slots and legal spending mechanism;
- any player removed during post-Draft trimming;
- the first stage where the team falls below its sustainable target.

That evidence will identify the real lifecycle defect before any roster-building
algorithm is changed.
