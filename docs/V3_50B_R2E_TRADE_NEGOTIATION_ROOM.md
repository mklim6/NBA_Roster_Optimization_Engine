# V3 50B-R2E — Trade Negotiation Room

## Scope

This pass upgrades the existing Trade Center presentation without changing trade rules,
transaction endpoints, package payloads, preview fingerprints, execution confirmation,
or save behavior.

The visual target is the same premium standard established by the Trophy Room while
giving Trades its own identity: a front-office negotiation room rather than another
award or marketplace screen.

## Presentation changes

- New dual-team Negotiation Room hero with large team marks, team-color light fields,
  selected-asset counts, package state, and current featured asset.
- Premium surfaces for live market status, Trade Finder proposals, package controls,
  asset war rooms, and legality/financial preview.
- Trade Finder proposals are larger team-branded offer cards with response-state color.
- Draft rights read visually as draft capital rather than generic checkboxes.
- Player-facing copy removes most implementation terminology from normal success/status
  paths while preserving the actual safety checks underneath.
- Existing detailed package stage remains in place below the hero, including selected
  player portraits, team logos, draft rights and current salary comparison.

## Protected behavior

The following existing contracts are intentionally preserved:

- `/v3/transaction-foundation?trade_finder=1`
- `/v3/trade/team-assets`
- `/v3/trade/preview`
- `/v3/trade/execute`
- exact side A / side B player and pick IDs
- fresh preview fingerprint requirement
- working-save fingerprint requirement
- confirmation dialog before execution
- rollback/reload verification logic

No trade is executed by the R2E validator.

## Validation

The installer runs:

1. `src/validate_v3_50b_r2e_trade_visual.py`
2. `src/validate_v3_batch20i_trade_presentation.py`
3. `src/validate_v3_batch26_trade_experience.py`
4. `git diff --check`

It also verifies that the active V3 and protected V2 save hashes are unchanged during
the visual validator.

Do not commit after installation. Launch the normal desktop app and visually inspect
Trade Center first.
