# Noita WS Adapter Readiness

This folder documents the first real reverse-project adapter target for Bridge-Maker:
[`probable-basilisk/noita-ws-api`](https://github.com/probable-basilisk/noita-ws-api).

The repository was inspected locally at commit `47054b0`. It is useful as a developer-control bridge, but it is not yet a high-throughput RL runtime. That makes it a good validation target for Bridge-Maker's contract-first direction: we can expose a semantic adapter without pretending the reverse-engineering layer is invisible.

## What the upstream project provides

- A Noita mod that connects as a WebSocket client to `ws://localhost:9090`.
- Commands sent to Noita are raw Lua source strings.
- Noita replies with JSON payloads or raw strings prefixed with `>`.
- The mod emits heartbeat JSON roughly once per second:
  `{"kind": "heartbeat", "source": "noita"}`.

## Bridge-Maker adapter shape

The first usable adapter should wrap known Lua queries/actions behind normal decorators:

```python
from bridge_maker import bm
from adapters.noita_ws.session import session

@bm.hp(bounds=(0, 100))
def hp():
    return session.eval_float("return get_player_hp()")

@bm.position(x="x", y="y", bounds=(-50000, 50000))
def pos():
    return session.eval_vec2("return get_player_xy()")

@bm.action("move_left", key="a")
def move_left():
    session.exec("bridge_apply_action('move_left')")

@bm.oracle("player_missing", severity="bug")
def player_missing(s):
    return session.eval_bool("return bridge_player_missing()")
```

The core SDK does not need to know that Noita is behind WebSocket/Lua. It only sees state getters, action functions, and oracles.

## Known runtime risks

- Raw Lua execution is flexible but fragile. A syntax/runtime error can stop the mod hook.
- JSON serialization is fine for control/debugging, but too slow for high-frequency RL observations.
- Window focus and aiming are unstable unless the adapter virtualizes control state every frame.
- Multi-instance training needs per-instance ports and isolated save directories.
- Noita does not provide a true headless mode.

## Recommended next milestone

Build a strict lockstep adapter on top of this idea:

1. Python hosts a WebSocket server on a configured port.
2. Noita mod connects and sends heartbeat/ready.
3. Bridge-Maker sends a compact action command.
4. The mod applies the action in `OnWorldPreUpdate`.
5. The mod captures state in `OnWorldPostUpdate`.
6. The mod returns a compact observation payload.

For production RL, replace raw JSON state with a binary FFI struct. The contract-facing Python surface stays the same.

## Tested in this repo

`tests/test_noita_ws_session.py` starts the Python-side Bridge-Maker WebSocket server, connects a fake Noita client, sends the upstream heartbeat shape, responds to generated Lua eval commands, and verifies that `BridgeRuntime` can sample and step through the decorated adapter.

This proves the adapter boundary:

- heartbeat from Noita-style client,
- raw Lua command dispatch,
- scalar/vector/bool eval replies,
- Bridge-Maker decorators over WebSocket-backed getters/actions.

It does not prove live Noita runtime stability.

## MVP status

Live Noita execution is not part of the current MVP because it requires the game, the mod, `pollws.dll`, and per-machine setup. The present MVP proves the contract/export/report loop on annotated Python adapters and provides this Noita path as the first serious external integration target.
