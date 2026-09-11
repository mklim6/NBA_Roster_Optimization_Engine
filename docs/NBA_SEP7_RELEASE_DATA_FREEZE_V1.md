# NBA Franchise Simulator — Sep. 7 Release Data Freeze V1

This package freezes the Live Sep. 7, 2026 release-candidate data layer.

## Frozen release identity

- Release ID: `live_2026_09_07_release_candidate_v1`
- Cutoff: `2026-09-07`
- Live-start config: `nba-live-franchise-start-config-v1.4-2026-09-09`
- Expected live-start fingerprint: `748bfcd58d6cecf8abab666b34b5d44d176d2e3456baef9a0fff6e033e08bd7b`

## Locked inputs

The freeze manifest stores exact SHA-256 values for:

- `app_data/nba_current_reference_manifest.json`
- `app_data/nba_current_reference_overlay_2026_09_07.json`
- `app_data/nba_live_franchise_start_2026_09_07.json`
- `data/reference/nba_current_reference_overlay_2026_09_07.csv`
- `data/reference/nba_player_movement_delta_2026_08_04_to_2026_09_07.csv`

Any byte-level change causes validation to fail until a deliberately versioned new freeze is created.

## Locked semantic expectations

The validator also requires:

- 49 current-reference players
- 19 supplemental/materialized players
- 8 released external overall-rating anchors
- 11 explicitly labeled empirical overall-rating proxies
- 19 source-backed production/shooting profiles
- source split: 2 NBA, 9 G League, 7 NCAA, 1 international
- 10 current-contract overrides
- 3 draft-asset overrides
- 1 international draft-rights transfer

The existing live-start, draft-forfeiture, asset-ledger, staff, full-project, and release-candidate validators remain responsible for runtime behavior.

## Update policy

Do **not** edit this frozen release's data files in place after declaring the release candidate. A post-Sep. 7 NBA update should create a new overlay/live-start/freeze version instead.

This lets `live_2026_09_07_release_candidate_v1` remain reproducible even after newer NBA transactions occur.
