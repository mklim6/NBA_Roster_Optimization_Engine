# Franchise Mode V1 Release Checklist

Updated: September 11, 2026

## Release status

The Sep. 7, 2026 live-start universe is the V1 release candidate. The protected
8-season chain through the opening of 2034-35 is green, the five Clippers
forfeiture drafts resolve to 59 picks in 2029-2033, the 2034 draft returns to
60 picks, and deep-season CPU Free Agency now has a dedicated V2 performance
validator/probe.

## Required before launch

1. Run `python src/audit_franchise_release_worktree_v1.py` and classify all
   untracked production source. Do not delete source modules simply because
   they are untracked.
2. Remove or archive only confirmed disposable installers, staging folders,
   old ZIPs, probes, and generated outputs after review.
3. Run the non-destructive release gate:
   `python src/run_franchise_release_candidate_gate_v1.py`.
4. Confirm the gate reports the active checkpoint family unchanged.
5. Review the final Git diff/status and create the V1 release commit/tag.

## Optional confidence extension

A seasons 9-10 protected continuation is optional. The completed eight-season
chain already crosses all five Clippers forfeiture years and repeated
generated-player/free-agency lifecycles.

## Launch

Launch the frozen Sep. 7 universe only after explicit confirmation. Preserve
the generated recovery directory and do not remove the previous active save
until post-launch smoke is complete.

## Required post-launch smoke

- Franchise Home and League Hub render.
- Opening 1,230-game schedule is present.
- One legal Free Agency action commits and survives reload.
- One transaction commits and survives reload.
- Draft Capital renders expected ownership/forfeiture state.
- One scheduled game simulates and standings/player totals survive reload.
- Recovery/rollback restores the pre-launch state when intentionally invoked.

## Release blocker policy

Correctness or durability failures are blockers. Optional seasons 9-10 are not
blockers when the eight-season chain, final full gate, and post-launch smoke are
green. Worktree ambiguity is a blocker until every production file intended for
V1 is explicitly tracked or deliberately excluded.
