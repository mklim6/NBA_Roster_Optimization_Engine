# Franchise Mode Current Status

Updated: September 11, 2026

## Current milestone

The Live September 7, 2026 franchise start is a release candidate. It is
available from Franchise Mode > League Hub as a read-only preview followed by
an explicitly confirmed launch. It has not been activated over the existing
franchise save.

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

## Verification state

- Latest unified full release-candidate validation: 94/94 checks passed after
  the playoff-stats suite-registration repair.
- Live-start validation: 41/41 checks passed after the overall, skill,
  potential, production, and shooting profile integrations.
- Unified quick validation: 39/39 checks passed; 566 Python files compiled.
- Franchise staff foundation validation: 17/17 checks passed.
- Explicit checkpoint replacement hotfix validation: 8/8 checks passed.
- Non-destructive release-candidate read-only gate: unified quick validation,
  live-cutoff evidence, current-reference data, live start, sub-five free-agency
  repair, draft forfeitures, and the live asset ledger all passed.
- September 11 Streamlit smoke: Franchise Home, embedded Free Agency, Draft,
  League Hub, Transactions, and Draft Capital all render from the protected
  checkpoint without an app exception.
- Streamlit live-start preview: 601 players, 415 rostered, 186 free agents,
  30 game-ready teams, roster range 10-18, and all 1,230 scheduled games. The
  launch remains disabled behind explicit acknowledgement and typed confirmation.
- Streamlit Draft workspace: verified to open with the correct postseason gate
  and no renderer/signature error.
- Isolated live-start commit: passed save, reload, fingerprint, and recovery
  manifest checks.
- Isolated forced launch failure: passed automatic rollback and previous-state
  restoration checks.
- Full 1,230-game player-fingerprint regression: 18/18 checks passed, with
  plausible aggregate FG%, 3P%, and FT% and preserved distribution spread.
- Live-start fingerprint:
  `748bfcd58d6cecf8abab666b34b5d44d176d2e3456baef9a0fff6e033e08bd7b`.

## Eight-season protected soak

The protected franchise chain now covers all eight completed seasons from
2026-27 through 2033-34 without modifying the active Streamlit save. The final
checkpoint opens 2034-35 with eight archived seasons, a fresh 1,230-game
schedule, complete generated-player Trade Machine registry coverage, a
league-low roster size of 10, and the Clippers at 10 players.

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

The V2 protected performance probe passes against the preserved 2034-35 deep
state. On the user's release machine the six-signing CPU round completed in
44.19 seconds, the immediate normal checkpoint reload completed in 2.753
seconds, the Clippers reached the 8-player game-ready floor, and the active
franchise checkpoint family remained unchanged. The dedicated V2 validator
also passes checkpoint hot-reload safety, deferred speculative fingerprint
semantics, byte-verified carry-forward, and final semantic reload checks.

## Save protection

The active franchise checkpoint remains unchanged at SHA-256:
`ad23baa483a0bb77c9d52b9182c93bf79cc4162a8f25addbff1f89f41b9d8108`.

The primary checkpoint and its direct backup are byte-identical. The launch
transaction now passes the resolved checkpoint path explicitly to every save
and reload. A launch first creates a timestamped recovery directory; any
installation failure restores the pre-launch checkpoint automatically.

## Immediate work queue

1. Perform final release packaging/worktree cleanup. The worktree contains a
   large amount of historical installer/probe debris and untracked production
   source; classify it before deleting or tagging anything.
2. Run the updated non-destructive release-candidate gate, including the Sep. 7
   freeze, Staff, and deep-season Free Agency V2 performance validators.
3. Optionally extend the protected chain from eight to ten completed seasons for
   extra confidence. This is no longer a first-launch blocker.
4. Launch the live universe only when the user explicitly chooses to replace
   the active save; retain the generated recovery directory.
5. Run the post-launch smoke cycle through opening night, one transaction, one
   free-agent action, Draft Capital, one simulated game, checkpoint reload, and
   rollback recovery.

## Longer-term roadmap

Continue against `FRANCHISE_MODE_MASTER_ROADMAP.md`. The deterministic staff
foundation and its first UI workspace are now present; the largest remaining
product areas are deeper staff workflows and scouting uncertainty,
morale/chemistry and player relationships, richer owner/coaching systems, and
possession-by-possession Interactive Coach Mode.
