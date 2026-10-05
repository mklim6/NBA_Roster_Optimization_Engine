# Expansion 46 — Game Night Theater

THEATER presents the latest twelve recorded games for the active franchise as a watchable postgame broadcast. The archive picker selects an existing result; playback does not simulate or save anything. The scoreboard always displays the recorded final score, including overtime metadata.

Broadcast chapters cover the final result, recorded starters, each team's leading scorer, team totals and closing recap. Player spotlights use recorded minutes, points, rebounds, assists, shooting, steals and blocks. Team comparison bars use complete box-score totals; incomplete legacy results explicitly omit team totals. Ties in spotlight selection resolve deterministically by points, assists, rebounds and player ID.

The stylized court is drawn in Godot with wood stripes, court markings, team-colored paint and a decorative crowd motif. Portraits show recorded starters in an illustrative lineup diagram. A spotlight ring identifies the featured player when they are among those starters. This is an illustration of the cast, not recorded on-court positions or movement.

Controls support play/pause, previous/next chapter, a chapter seek slider and 1×/2×/4× pace. Chapters last six presentation seconds at normal pace. Playback stops at the end; Replay begins again from the opening chapter. Hidden pages do not advance playback, and refresh resets the presentation. Optional synthesized transition sound defaults off. The page supports wrapped text, vertical scrolling and a bottom safe area. An empty archive links to Game Day without generating a pretend result.

Navigation is available from the sidebar, Game Day's postgame review and Pulse's recorded weekly results. GET /v3/game-night-theater is read-only and guards both working and protected checkpoint hashes. API version is 0.23.0.

Important scope: the current single-game engine samples final scores and then produces reconciled player box scores. It does not record a chronological possession timeline. Theater therefore does not invent a game clock, scoring runs, shot locations or substitutions. True possession playback requires a separate simulation-engine expansion; the engine and its random draws are untouched here.

Validation uses an actual single-game simulator preview on a copied checkpoint. Checks cover source immutability, exact scores, reconciled totals, starters, deterministic chapters, partial and undated records, the archive limit, API responses, scratch save/reload, Godot game selection, chapter playback, speed, seek, sound waveform and navigation. Expansion 45 and Game Day presentation regressions pass. Desktop fixture checks verified court layout, portraits, chapter controls, spotlight highlighting and the full player card. The user's live franchise was not simulated or changed.
