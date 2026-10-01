# NBA Franchise Simulator V2 Release Notes

## Release Candidate

Branch: `feature/franchise-v2`

Validated source snapshot:

`d2b2b47` — `Complete NBA franchise simulator V2 release candidate`

## V2 Scope

V2 expands the project from a functioning persistent franchise simulator into a deeper multi-season league-management engine.

Major V2 systems include:

- sustainable CPU roster construction
- CPU two-way roster management
- undrafted rookie free-agent integration
- long-term free-agent population ecology
- repeated offseason roster lifecycle support
- scouting and staff workflows
- injury-aware rotation replacement
- workload and statistical-responsibility redistribution
- opponent threat modeling
- tactical defensive counters
- coach-identity differentiation
- Game Day coaching explanations
- protected multi-season regression tooling
- consolidated V2 release-candidate validation

## Coaching Intelligence V2

The coaching system was validated with a protected league-wide counterfactual audit covering all 30 teams and 870 directed matchups.

Results included:

- 60 staff-identity differentiated matchups
- 259 close-call tactical scenarios
- 54 close calls changed by staff identity
- 20.8% close-call differentiation
- 94 strong tactical calls
- 94/94 strong calls remained stable
- no selected non-balanced scheme had negative raw matchup utility
- tactical suppression remained within its configured bound
- active franchise state remained unchanged

This allows staff identity to influence genuinely close decisions without overpowering strong basketball matchup signals.

## Deep Release Validation

The final protected deep release gate passed:

- Compile: **1/1**
- Static: **17/17**
- Protected runtime: **7/7**
- Full-season regressions: **2/2**
- Deep multi-season checks: **2/2**
- Active checkpoint family unchanged: **PASS**

The deep gate included an eight-season roster-lifecycle trace and player-population ecology audit.

## Streamlit Release Smoke

The committed V2 snapshot also passed the final Streamlit release smoke.

Verified application surfaces included:

- Franchise Mode
- Trade Lab
- Player Ratings
- Trade Machine
- Game Simulator
- Free Agency
- remaining primary navigation surface

Observed results:

- project quick gate: **39/39**
- Python compilation: **773 files passed**
- V2 fast release gate: **1/1 compile, 17/17 static, 7/7 protected runtime**
- all seven Streamlit surfaces rendered
- no Streamlit traceback
- no browser-console warning or error
- no server exception
- all protected checkpoint files retained their exact SHA-256 hashes

No franchise mutation was performed during the smoke test.

## Save Safety

Protected tests are designed to preserve the active franchise checkpoint.

Release validation hashes the checkpoint family before and after execution. Mutation-oriented validation uses isolated or cloned state rather than treating the user's active franchise as a test target.

## Known Non-Blocking UX Note

The Game Day medical table currently labels the stored rotation field as `Planned MIN`.

For unavailable players this can display saved rotation minutes even though the player is correctly removed from the actual game plan.

This is a presentation issue only and does not affect injury enforcement, rotation allocation, or simulation behavior. A future UI-only polish can relabel the field as `Saved rotation MIN`.

## Historical Documentation

Earlier files such as the V1 release checklist, V2 roadmap, and development status reports are retained in `docs/` as development history.

They should not be interpreted as the current V2 release procedure.

The authoritative V2 validation entry point is:

```powershell
python .\src\run_franchise_v2_release_candidate_gate_v2.py
```

with `--fast`, `--full`, or `--deep` depending on the desired validation depth.
