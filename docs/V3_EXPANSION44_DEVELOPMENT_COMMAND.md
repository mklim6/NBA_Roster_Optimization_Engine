# Expansion 44 — Development Command Center

The DEVELOPMENT page provides a season agenda for up to three roster players, one goal each. Managers can preview and commit shooting, playmaking, defense or rebounding growth of one to three skill points. Regular-season opportunity goals track 10, 15, 20, 25 or 30 minutes per game and require ten appearances. Targets are fixed once committed for that team and season.

The board shows player portraits, captured baselines, current measurements, targets and progress bars. Green indicates a currently met target; blue indicates ongoing progress. Current targets can regress as actual ratings or minutes change. The archive evaluates past seasons using recorded development events or season statistics; missing closing evidence is explicitly unverified. Departed players retain their commitments. The agenda does not change ratings, rotations, morale or owner rewards.

Training Camp displays each selected player's season commitment, connecting planning with existing focused development and mentorship. Buttons lead to camp and recorded career histories. The growing main sidebar now scrolls so all navigation remains reachable.

API 0.21.0 adds GET/POST /v3/development-goals. Preview operates on a deep copy. Execution uses the working-checkpoint hash guard, temporary candidate persistence, reload verification, recovery copy and atomic replacement. Only checkpoint preferences change; simulation state remains intact. Plans persist across reloads, and duplicate commitments are rejected.

Validation covers actual rating and appearance progress, archived evidence, invalid inputs, stale requests, repeated commitments, durable reload, unchanged simulation state, protected save hashes, Godot forms/cards and navigation registration. Expansion 40 and 43 regressions pass. Desktop checks verified the live Boston planner and read-only preview (75.1 shooting baseline to 76.1 target), plus populated progress cards and archive expansion in an isolated visual fixture. No goals were committed and no games or camp were executed on the live franchise.
