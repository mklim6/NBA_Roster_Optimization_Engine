# V3 Godot Client — Phase 1

This directory is the first desktop-client vertical slice for V3.

## What it proves

- Godot can own the presentation layer without rewriting the validated Python simulation engine.
- The client can establish a local connection to the Python V3 bridge.
- The V3 client can evolve independently while V2 Streamlit remains stable.
- Phase 1 is deliberately read-only. It does **not** open or mutate an active franchise save.

## Run the bridge

From the repository root, using the existing project environment:

```powershell
python .\scripts\run_v3_bridge.py
```

The bridge listens only on:

```text
http://127.0.0.1:8765
```

Health endpoint:

```text
http://127.0.0.1:8765/health
```

## Run Godot

1. Install Godot 4.x.
2. In Godot Project Manager, choose **Import**.
3. Select `godot_client/project.godot`.
4. Open the project and press **F6/F5** (Run Project).
5. With the Python bridge running, the Desktop Engine card should change from `CHECKING...` to `CONNECTED`.

## Phase 1 rule

Do not add franchise write endpoints yet. The next milestone is a read-only adapter that exposes a cloned/snapshot view of the current franchise for roster, standings, player profile, schedule, and league hub screens.
