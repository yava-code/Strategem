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
  (the only safe place to read/mutate game state), applies the action (8-direction
  `GameObject.Move` + wait), and replies with the resulting state frame.
- State is read by field name off `XRL.The.Player` / `The.PlayerCell`
  (`GetStat("Hitpoints").Value`, `Cell.X/Y`, `GetPart<Stomach>().HungerLevel`,
  `Zone.GetObjectsWithPart("Brain")`), so it tolerates content/version drift.

## The oracles (what actually makes it "testing")
Exploration only *finds* states; these decide if a state is a **bug**:
- **EXCEPTION** — a Harmony `Finalizer` on `PlayerTurn` captures any exception
  thrown during the turn (real crashes — the #1 automated-playtest signal), logs
  it, and rethrows so the game behaves exactly as unmodified.
- **INVARIANT** — flags `HP<0`, missing cell, out-of-zone position.
- **SOFTLOCK** — no positional change across many turns.

## Build status
`QABridge.cs` is **compiled-validated against the real game assemblies**
(`Assembly-CSharp.dll`, `0Harmony.dll`, `UnityEngine.CoreModule.dll`) — 0 errors —
so the API calls are correct. CoQ recompiles it at load. If `XRLCore.PlayerTurn`
is ever renamed, repoint the `[HarmonyPatch]`; any once-per-player-turn main-thread
method works.
