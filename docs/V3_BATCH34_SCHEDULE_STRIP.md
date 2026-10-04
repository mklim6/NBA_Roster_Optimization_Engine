# Batch 34 — Next Five schedule strip

Franchise HQ now shows the controlled team’s next five scheduled games with opponent logos, venue, league day, countdown, and rest between games. Consecutive league-day games receive a back-to-back label. First-game rest remains unknown when no previous saved game establishes the gap. The preparation button navigates to the actual next matchup in Game Day, using the existing coaching, rotation, and confirmation flows.

Validation: Batch 34 passed scheduled-game ordering and filtering, five-game limit, controlled-team orientation, countdowns, rest gaps, back-to-backs, runtime cards and navigation, momentum regressions, cached-state immutability, and both protected save hashes. Batch 27 HQ regression passed. Desktop inspection verified Boston’s live SAS/MIA/MIN/NOP/ORL strip and the preparation button opening BOS/SAS. No game was simulated or live save modified.
