# Franchise Mode Current Status

Updated: September 29, 2026

## Current milestone

The active franchise has advanced into the 2027-28 regular season. The current
release candidate now includes the Morale V3.0.2 experience, CPU morale
responses, morale-aware trade-market and Trade Finder bridges, autonomous
CPU-to-CPU trading, incoming CPU trade offers for the user, and batched
postgame calendar/market persistence.

The Live September 7, 2026 franchise start remains available from Franchise
Mode > League Hub as a read-only preview followed by an explicitly confirmed
launch. It has not replaced the existing franchise save.

The live-start universe currently contains:

- 49 current-reference roster/status moves.
- 19 real players materialized because they were absent from the original
  runtime.
- 601 total players: 415 rostered and 186 free agents.
- 30 game-ready teams, with roster sizes from 10 through 18.
- 10 two-way players and 8 Exhibit 10 players from the reference overlay.
- A complete, unplayed 1,230-game 2026-27 schedule.
- Three post-August 4 draft-capital changes and one international draft-rights
  transfer.
- All five Clippers first-round forfeitures preserved as non-owned,
  non-tradeable audit assets.
- All 8 previously unresolved detailed contracts resolved, while salary, cap
  hit, guaranteed amount, term, and option semantics remain separate.
- All 19 supplemental-player production baselines backed by retained source
  evidence and conservatively translated for competition level and sample
  size: 2 NBA, 9 G League, 7 NCAA, and 1 international profile.
- All 19 supplemental shooting-efficiency profiles now use source percentages
  and attempt-volume shrinkage. Their initial targets remain responsive to
  later scoring, shooting, and efficiency development instead of being frozen.
- 8 of 19 supplemental overall ratings anchored exactly to released current 2K
  ratings. A fresh 31-page team/free-agent scrape found no released rating for
  the other 11; those players now use clearly labeled empirical lower-roster
  proxies from the current 2K distribution plus their retained production,
  competition level, sample size, and position evidence.
- All 19 broader skill profiles are now differentiated across scoring,
  shooting, playmaking, rebounding, defense, efficiency, and availability.
  Potential and future outlook are deterministically calibrated from age and
  the same source-informed performance signal rather than flat defaults.

## Active franchise save

The protected active save is now a live 2027-28 regular-season franchise, not
the September 7 live-start preview:

- 645 players, 320 free agents, and 30 teams with roster sizes from 8 through
  14.
- 755 of 1,230 league games are complete; Chicago is 22-27 through 49 games.
- Chicago is the only user-controlled team.
- Current day index: 108. The saved active workspace is Game Day.
- The latest checkpoint reason is `franchise-auto-managed-routine-events`.
- Active checkpoint SHA-256:
  `6b9cb89d78a9c143a62c9460375b96cdf215dfbf9ac713001755ac7045c8718d`.

The direct recovery backup intentionally represents the previous valid state
and does not need to be byte-identical to the active checkpoint. Both files are
present and remain independently protected.

## September 15 season-boundary repair

The reported `all_team_rosters_playable` failure was reproduced against the
active save without modifying it. The cause was ordering inside repeat-offseason
CPU roster construction: the legal roster-floor rescue was considered only
after ordinary CPU markets were exhausted, so a bounded CPU round could spend
its signing slots on already-playable teams and strand an underfilled team.

The repair does not increase the rescue limit:

- A legal, player-accepted roster-floor signing now takes priority whenever a
  CPU team is below the playable floor.
- The number of completion attempts is derived from the actual roster deficit.
- `Open next season` now completes and reload-verifies CPU opening-night rosters
  before post-Draft trim and the atomic season transition.
- User-controlled roster deficits are never auto-filled; the UI reports the
  team, current count, and number of players still needed.
- On the current save, the transaction stack deterministically finds J'Vonne
  Hadley for Golden State on a one-year, $1,466,384.04 minimum contract.
- The active checkpoint was not changed during diagnosis or validation. The
  next explicit `Open next season` click owns the real signing and transition.

## Verification state

- The current V2-V6.0.1 morale, CPU-trade, offer, calendar-sync, and postgame
  block passes all 24 dedicated validators and behavioral regressions.
- The three validators made stale by the V6.0.1 batched postgame pipeline now
  validate the actual order: controlled game commit, league catch-up,
  autonomous CPU market, incoming-offer scan, one durable checkpoint, then
  next-game selection.
- The older V2 and V2.1 morale contract tests are forward-compatible with the
  current V3 implementation while retaining their original behavior checks.
- These 24 suites are registered in the unified full project validation. The
  latest V3.0.2 through V6.0.1 suites are also registered directly in the
  release-candidate gate so `--skip-full` cannot bypass current feature
  coverage.
- Project quick gate passes 39/39 checks; all 734 current source/app/page Python files compile.
- New preseason roster-floor validator: 5/5 checks passed.
- CPU roster-floor rescue validator: 19/19 checks passed.
- CPU Free Agency execution validator: 29/29 checks passed read-only.
- Lifecycle authority, season-boundary snapshot rebase, owner normalization,
  and Draft V1.1.8 validators all passed.
- Cross-page franchise-state validation passes after updating its current Trade
  War Room integration assertion.
- All 13 post-September 11 feature validators pass after superseded-version
  checks were made forward-compatible.
- Live asset ledger and live-cutoff audits pass; the cutoff remains frozen and
  the checkpoint family remains unchanged.
- The running Streamlit app hot-reloaded and rendered Franchise Mode, Schedule,
  League Hub, the season journey, Offseason Headquarters, and next-season
  routing without an app exception.
- The expanded unified full suite passes 120/120 checks after the Free Agency
  performance repair and current UI-validator reconciliation.
- The final non-destructive release-candidate gate passes with the full suite
  skipped only because the same 120-check run had just completed. Its quick
  gate, release worktree audit, frozen-data audits, current feature regressions,
  and isolated live-start commit/rollback all pass.
- A final September 17 gate rerun passes all 28 release stages after packaging,
  including quick validation, worktree classification, current feature
  regressions, and isolated live-start commit/rollback.
- The September 29 V2 dedicated release pass clears every frozen-data,
  live-start, staff, Free Agency, draft, morale, trade, calendar, postgame,
  durable-batch, worktree, and isolated commit/rollback stage. The retained V2
  tools and validators are staged for review, two superseded durability scripts
  were removed, and no untracked production Python remains. Loose patch bundles,
  generated checkpoints, ZIP remnants, and manual-review notes remain unstaged
  and excluded from this release consolidation.
- The standalone Free Agency page now treats an empty RFA ledger during the
  regular season as an inactive overlay instead of an invalid anchor-offseason
  ledger. The strict 64-player check remains enforced when the certified anchor
  offseason is active.
- All six Streamlit pages render from a clean extracted release package without
  an app exception. The packaged protected smoke also passes frozen live start,
  opening night, one game, save/reload, standings and player-total durability,
  and exact recovery of the pre-launch source state.
- The live-start preview, isolated commit/rollback, and 1,230-game shooting
  regression evidence remain valid. Live-start fingerprint:
  `748bfcd58d6cecf8abab666b34b5d44d176d2e3456baef9a0fff6e033e08bd7b`.

## Eight-season protected soak

The protected franchise chain now covers all eight completed seasons from
2026-27 through 2033-34 without modifying the active Streamlit save. Five
seasons passed in the original run. Season six was recovered from its preserved
2031-32 boundary after the user interrupted the slow Free Agency stage; its
2032-33 checkpoint passes all 11 boundary invariants. A protected continuation
then passed seasons seven and eight into 2034-35. The final checkpoint has a
fresh 1,230-game schedule, complete generated-player Trade Machine registry
coverage, and a league-low roster size of 10.

The soak exposed two real repeat-offseason lifecycle defects, both now repaired
without increasing the CPU signing/rescue limit:

- Generated drafted players are registered into Trade Machine ownership at the
  season boundary, so their eventual free agency can be transacted normally.
- Every offseason signing made while a team starts below five players refreshes
  its legal partial rotation. This allows the genuine 3-to-4 and 4-to-5 roster
  rebuild path instead of circularly failing candidate-state validation.

The exact preserved three-player Clippers failure now finds a player-accepted,
CBA-valid minimum-contract rescue. Its resumed 2033-34 offseason completed with
six signings, a 60-pick 2034 draft, and a valid transition into 2034-35. The
five Clippers forfeitures were exercised as 59-pick drafts in 2029 through
2033; the unaffected 2034 draft returned to 60 picks.


## Deep-season Free Agency performance

The root cause of the long soak was a discarded league-wide offer-board build
before every roster-floor rescue signing. The floor rescue is now evaluated
first; the full market is built only when no rescue is required. Financial
legality, player acceptance, per-signing atomic checkpoint writes, byte
verification, and final semantic reload remain intact.

The protected deep-state probe improved from 44.19 seconds for six mixed market
and rescue signings to 21.29 seconds for the five signings actually required to
bring the Clippers from three players to the eight-player game floor. The
real 2031-32 Free Agency stage improved from 1,291.41 seconds before interruption
to 203.93 seconds with the repair. Seasons seven and eight completed their Free
Agency stages in 286.40 and 348.78 seconds respectively, each with 63 legal
signings. The active franchise checkpoint family remained unchanged.

The eight-season evidence also identifies a non-blocking realism calibration:
the 2034-35 league opens with 300 rostered players and 552 free agents, with all
teams at 10 players. That is fully playable and contract-valid, but a later
roster-ecology pass can target NBA-like 14–15-player organizations if desired.

The September 27–28 V2 performance pass then profiled the same preserved
2033-34 mature-offseason checkpoint through the complete protected path. CPU
Free Agency improved from 39.06 seconds to 19.41 seconds, post-Draft trim
improved from 35.28 seconds to 11.94 seconds, and the full Free Agency, Draft,
save/reload, and trim benchmark improved from 98.04 seconds to 47.61 seconds.
The run completed all 12 required signings, left every team at the 14-player
sustainable target, completed all 60 draft selections, passed validation, and
left the active checkpoint unchanged. The principal repair caches the immutable
Trade Machine validation package once per process and avoids redundant deep
copies of mature transaction histories while retaining identical fingerprints.

The September 29 durability pass removed the remaining per-signing checkpoint
serialization bottleneck without weakening crash recovery. CPU Free Agency now
commits accepted transactions in atomic batches of five, verifies the expected
pre-flush checkpoint hash, retains a recovery copy for each batch, and performs
a final semantic reload. A protected full-season run completed in 151.70
seconds: the 155-signing CPU market took 49.21 seconds, all 30 teams reached the
14-player sustainable target, Draft and trim completed, and the next-season
boundary passed. The run observed 31 durable batch saves and zero individual
CPU-signing saves. Both the runtime trace and exact-source hotfix validator pass,
and the active checkpoint family remains unchanged.

## Save protection

The active franchise checkpoint remained unchanged throughout the September 28
read-only validation and protected performance work at SHA-256:
`6b9cb89d78a9c143a62c9460375b96cdf215dfbf9ac713001755ac7045c8718d`.

The active checkpoint and its direct backup are both present and unchanged by
read-only validation. The backup is the previous valid recovery state and is
not expected to be byte-identical to the active save. A live-start launch first
creates a timestamped recovery directory; any installation failure restores
the pre-launch checkpoint automatically.

## Local release package

The clean local release is built at
`outputs/releases/NBA_Franchise_Simulator_V1_2026-09-17.zip`. It contains the
current source, six Streamlit pages, runtime data, frozen-reference evidence,
real-staff reference, generated-player visual assets, documentation, and a
machine-readable file manifest. It excludes the user's active checkpoint,
recovery trees, local scenarios, historical ZIPs/staging folders, generated
probes, and development-only datasets. The adjacent `.sha256` file is the
distribution integrity sidecar.

On Windows the package should be extracted to a short path such as
`C:\NBA_Franchise_Simulator`. The protected smoke passed there; an intentionally
deeply nested staging location exceeded the legacy Windows path-length limit
during recovery-directory creation.

## Immediate work queue

1. Review and classify the accumulated tracked and untracked V2 files, then
   create the release commit/tag when the owner is ready. No staging, commit, or
   tag was created automatically.
2. Optionally calibrate CPU organizations toward 14–15-player rosters and prune
   long-term free-agent population growth. This is realism polish, not a
   lifecycle or release-gate blocker.
3. Optionally add more explicit progress feedback around multi-minute offseason
   automation, even though the protected eight-season run now completes.

Estimated required engineering remaining for the polished local release: none.
Release administration (diff review, commit/tag, and copying the ZIP) should
take about 15–30 minutes. Optional roster-ecology and progress-feedback polish
remains approximately 4–10 hours.

## Longer-term roadmap

Continue against `FRANCHISE_MODE_MASTER_ROADMAP.md`. The deterministic staff
foundation, Morale V3, CPU reactions, morale-driven trade logic, autonomous CPU
trades, and incoming user offers are now present. After consolidation,
performance, soak testing, and packaging, the largest remaining expansion areas
are deeper staff workflows and scouting uncertainty, deeper
relationship/chemistry effects, richer owner/coaching systems, and
possession-by-possession Interactive Coach Mode.
