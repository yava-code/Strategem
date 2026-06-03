# Caves of Qud — QA Bridge mod

Streams live player state over `127.0.0.1:50545` and applies RL-chosen actions
each turn, using the exact length-prefixed JSON protocol that
`tools/mock_coq_server.py` mocks. Swapping the swarm from mock → real game is just
running it with `--transport live` instead of `--transport mock`.

## Install
1. Copy this folder into your CoQ user mods directory:
   `%USERPROFILE%\AppData\LocalLow\Freehold Games\CavesOfQud\Mods\CoQ_QA_Bridge\`
2. Launch Caves of Qud → **Mods** → enable **Bridge-Maker QA Bridge** → restart.
   (CoQ compiles the C# at load and auto-applies the Harmony patch.)
3. Start a character and enter play. The bridge logs
   `[QABridge] Listening on 127.0.0.1:50545` to the Player.log.

## Run the swarm against the live game
```
python -m src.swarm --config configs/coq_qa.yaml --agents 3 --timesteps 6000 \
    --transport live --dashboard
```
The Python side is identical to the mock run — same schema, same protocol.

## How it works
- A background `TcpListener` accepts the protocol; each request is queued.
- A Harmony postfix on `XRLCore.PlayerTurn` drains the queue **on the main thread**
  (the only safe place to read/mutate game state), applies the action, and replies
  with the resulting state frame.
- State is read by field name off `XRL.The.Player` (`GetStat`, `CurrentCell`,
  `Stomach`), so it tolerates content/version drift.

## Version note
Action verbs use `GameObject.Move(direction)`. If a CoQ update renames movement,
edit `ApplyAction()` in `QABridge.cs`; the state-read path is unaffected. If
`XRLCore.PlayerTurn` is renamed, repoint the `[HarmonyPatch]` target — any
once-per-player-turn main-thread method works.
