# NBA Franchise Simulator

A persistent multi-season NBA franchise and front-office simulation engine built in Python and Streamlit.

The project models roster construction, contracts, trades, free agency, drafts, player development, injuries, fatigue, scouting, staff, coaching decisions, league-wide CPU management, postseason progression, and durable franchise history across multiple seasons.

The goal is not to reproduce a real-time 3D basketball game. The focus is the part of franchise simulation where a data-driven project can go deepest: transparent front-office decisions, long-term league evolution, explainable AI behavior, realistic roster constraints, and persistent consequences.

## V2 Highlights

### 30 autonomous front offices

CPU teams independently manage:

- roster construction
- free-agent offers
- two-way contracts
- trades and incoming offers
- draft selections
- roster trimming
- salary and contract constraints
- long-term team direction

Roster-building logic is designed around normal legal transactions rather than relying on emergency roster repair.

### Multi-season franchise lifecycle

The engine supports a persistent loop across:

- regular season
- playoffs
- lottery
- NBA Draft
- contract transitions
- free agency
- post-Draft roster construction
- player development and aging
- retirement
- the next league year

Generated rookies and long-term player populations remain integrated with contracts, free agency, trades, scouting, and league history.

### CBA-aware transactions

Transaction logic includes:

- contract and salary matching
- roster-size rules
- future first-round pick legality
- Stepien restrictions
- draft-rights ownership
- two-way roster limits
- free-agent acceptance
- durable transaction state

### Coaching Intelligence V2

Game Day includes an explainable coaching layer that evaluates:

- opponent creation
- shooting and spacing
- rim pressure
- size and rebounding
- interior offensive threats
- available defensive personnel
- coach and assistant tendencies

The system can select tactical counters such as loading up on a primary creator, staying home on shooters, packing the paint, switching perimeter actions, or matching size.

Coach identities use simulation-generated franchise attributes and are not presented as claims about real-world coaching behavior.

### Injury-aware rotations and workload

Unavailable players are removed from playable rotations, while the remaining roster absorbs minutes and statistical responsibility according to functional basketball roles.

The model redistributes:

- minutes
- scoring responsibility
- creation
- rebounding
- defensive events

without permanently altering player ratings.

### Scouting, staff, morale, and development

Franchise systems also include:

- prospect scouting
- staff and scout management
- player development
- morale and chemistry
- fatigue and injury risk
- player roles
- awards and league history

## Validation

V2 was validated through a protected release-candidate suite designed not to mutate the active franchise save.

The final deep release gate passed:

- **1/1** compilation stage
- **17/17** static validation stages
- **7/7** protected runtime stages
- **2/2** full-season regression stages
- **2/2** deep multi-season stages
- protected **eight-season roster lifecycle trace**
- protected player-population ecology audit
- exact active checkpoint-family preservation

The final Streamlit release smoke also completed successfully across all seven application surfaces with no Streamlit traceback, server exception, or browser-console error.

The active checkpoint files retained their exact SHA-256 hashes throughout protected release validation.

See [`docs/FRANCHISE_V2_RELEASE_NOTES.md`](docs/FRANCHISE_V2_RELEASE_NOTES.md) for additional release and validation details.

## Run Locally

Python 3.12 is recommended.

On Windows, clone or extract the project to a reasonably short path such as:

```text
C:\NBA_Franchise_Simulator
```

Then:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run Home.py
```

The primary franchise interface is available at:

```text
http://127.0.0.1:8501/Franchise_Mode
```

Local franchise saves are stored under `outputs/runtime` and are intentionally excluded from the repository.

## Validate V2

Run the fast non-destructive V2 release gate:

```powershell
python .\src\run_franchise_v2_release_candidate_gate_v2.py --fast
```

Run the full regression gate:

```powershell
python .\src\run_franchise_v2_release_candidate_gate_v2.py --full
```

Run the deepest protected validation, including the eight-season lifecycle trace:

```powershell
python .\src\run_franchise_v2_release_candidate_gate_v2.py --deep
```

These gates verify the active checkpoint family before and after execution.

## Project Structure

```text
Home.py          Streamlit entry point
pages/           Application interfaces
src/             Simulation, franchise, transaction, AI, and validation systems
app_data/        Runtime reference data
assets/          Visual assets
docs/            Architecture, development, and release documentation
```

## Release Philosophy

Correctness and durability are treated as release requirements.

Protected validation uses cloned or isolated franchise state wherever mutation is required. The active save is not used as a repair or soak target, and checkpoint integrity is explicitly verified during release testing.

Historical development plans and V1 release documents remain in `docs/` as project history.

## Ownership and License

Original source code, simulation logic, documentation, and project design:

**Copyright © 2026 Matthew Klima. All rights reserved.**

This is proprietary software. See [`LICENSE.md`](LICENSE.md) for the complete notice, including treatment of third-party names, trademarks, data, and assets.
