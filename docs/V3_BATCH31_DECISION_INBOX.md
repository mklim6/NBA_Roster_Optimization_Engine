# V3 Batch 31: Franchise Decision Inbox

Adds a dedicated Inbox page in the sidebar and a direct HQ shortcut. Cards group current franchise situations as Action, Watch and Next, with category filters, player portraits where applicable, clear stakes and navigation to the existing decision tools.

The new GET /v3/decision-inbox endpoint reads the saved incoming-offer dictionary directly. It never calls the incoming-offer generation, expiration or resolution functions. It excludes expired, resolved, other-team and previous-season offers and exposes both package names and expiry day. An uninitialized queue is identified separately from a loaded queue with no pending offers.

The inbox also reports saved injuries, morale attention, game-day coaching alerts, invalid rotation allocations, a controlled draft pick, draft completion and the next scheduled game. It derives these from existing production reports and does not generate deadlines or narrative events.

Offer cards are review-only: opening Trade Center does not accept, reject or automatically load an offer package. Existing transaction tools retain their own preview and confirmation gates. This batch does not add offer-resolution endpoints or persistent dismissals. Refresh clears old cards, and save switching cancels the inbox request and invalidates cached results. Other-team responses and checkpoint safety failures are rejected.

Validation: Batch 31 checks saved-offer filtering, expiration-day boundaries, pure builder immutability, injuries/rotation decisions, uninitialized queue handling, the live read-only endpoint, native sidebar activation, action routing, counts, filters, portrait construction, refresh clearing, other-team response rejection, offline states and width bounds. Batch 27 HQ and Batch 22 presentation regressions pass. Native desktop inspection verified Boston's workload warning and SAS preparation card, sidebar activation and navigation to Game Day. Both checkpoint hashes remain unchanged.
