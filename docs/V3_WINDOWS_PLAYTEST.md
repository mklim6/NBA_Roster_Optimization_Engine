# Private Windows playtest bundle

`scripts/build_v3_playtest.py` creates a portable staging directory from the current working tree. It includes the Godot runtime, isolated embeddable Python, wheels, source project, required simulation inputs, and a certified fresh franchise checkpoint. It excludes creator runtime saves and Godot editor caches/import metadata. The builder refuses to overwrite an existing destination and verifies source checkpoints remain unchanged.

Run with the source Python environment and supply `--destination`, `--python-zip`, `--wheels`, and `--godot`. Use the official Python 3.12.10 Windows x64 embeddable ZIP and compatible Windows CPython 3.12 dependency wheels. The October 5 build used Godot 4.0. Retain Python/package license files and Godot license attribution. Archive the staging directory with its top-level folder, and refresh the manifest file hashes after any staged correction.

Users extract to a writable folder and launch Play.cmd. The copied launcher only uses package-owned Python and Godot, owns its bridge process, requires port 8765 to be free, and shuts down the bridge when Godot exits. Godot preferences use a separate playtest user-data directory.

This is a private runtime/source bundle, not a signed installer or Godot export. Validate a relocated extraction, real simulation/save/relaunch, UI assets, and shutdown before distribution. The first package was checked on the development Windows machine; recipient-machine and full multiseason testing remain necessary.
