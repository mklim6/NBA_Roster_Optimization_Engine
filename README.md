# NBA Franchise Simulator

A persistent NBA front-office simulator built with Streamlit. It includes a
multi-season Franchise Mode, Trade Machine, Free Agency workspace, Game
Simulator, player ratings, draft-capital rules, contracts, injuries, staff,
morale, CPU transactions, playoffs, drafts, and durable save/recovery support.

## Run locally

Python 3.12 is recommended.

On Windows, extract the release to a reasonably short location such as
`C:\NBA_Franchise_Simulator`; deeply nested directories can exceed the legacy
path limit when recovery checkpoints are created.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run Home.py
```

Open `http://127.0.0.1:8501/Franchise_Mode` for the main experience. The first
load creates a local save under `outputs/runtime`; the packaged release does
not contain anyone's existing franchise save.

## Validate the release

Run the non-destructive release gate from the project root:

```powershell
python .\src\run_franchise_release_candidate_gate_v1.py
```

To build a clean local ZIP from the current worktree:

```powershell
python .\src\build_franchise_local_release_v1.py
```

The builder writes the archive and its SHA-256 sidecar to `outputs/releases`.
It deliberately excludes active checkpoints, backups, generated probes,
historical staging folders, local scenarios, and development-only datasets.

## Save safety

- Franchise mutations are checkpointed atomically.
- The direct backup represents the previous valid state and may differ from the
  current checkpoint.
- A live-start replacement creates a timestamped recovery directory before it
  installs the new universe.
- Keep `outputs/runtime` when upgrading an existing local installation, but do
  not distribute that directory with a clean release.

See `docs/FRANCHISE_MODE_CURRENT_STATUS.md` and
`docs/FRANCHISE_MODE_RELEASE_CHECKLIST_V1.md` for current verification details.
