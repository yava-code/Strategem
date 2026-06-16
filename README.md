# The Bridge-Maker

Contract-first automated game QA for indie developers.

Bridge-Maker turns a small set of annotated gameplay functions into a semantic contract, a Gymnasium-compatible environment, and a bug report. The default path does not require Cheat Engine, Ghidra, Ray, cloud credentials, or reverse-engineering setup.

## Why this exists

Fully automatic "point at any `.exe` and understand the game" is not a credible onboarding promise for ordinary teams. Bridge-Maker uses a smaller and more honest contract:

1. The developer or adapter author marks important state/actions/oracles.
2. Bridge-Maker exports `state_map.json`, `action_map.json`, `oracle_map.json`, and `trace.jsonl`.
3. A generated SDK env or direct SDK runtime can be used by RL/training layers.
4. Reports show concrete bug evidence from traces.

## Minimal example

```python
from bridge_maker import bm

@bm.hp(bounds=(0, 100))
def hp():
    return player.hp

@bm.position(x="x", y="y", bounds=(0, 100))
def position():
    return player.x, player.y

@bm.move("right", key="d")
def move_right():
    player.move_right()

@bm.oracle("out_of_bounds")
def out_of_bounds(state):
    return state.x < 0 or state.x > 99
```

## Demo

The repository includes a tiny annotated roguelike with an intentional right-edge movement bug.

```powershell
python -m bridge_maker demo --out runs/grant_demo
```

Outputs:

- `runs/grant_demo/state_map.json`
- `runs/grant_demo/action_map.json`
- `runs/grant_demo/oracle_map.json`
- `runs/grant_demo/trace.jsonl`
- `runs/grant_demo/report.json`
- `runs/grant_demo/report.html`

Run a direct Gymnasium smoke loop:

```powershell
python -m bridge_maker smoke --adapter examples/buggy_roguelike.py --steps 20
```

Generate annotation suggestions:

```powershell
python -m bridge_maker suggest --repo examples --out runs/example_suggestions
```

## Documentation and pitch

Open the static documentation site:

```powershell
start docs\index.html
```

Key docs:

- `docs/getting-started.md`
- `docs/sdk-reference.md`
- `docs/architecture.md`
- `docs/status.md`
- `grant_materials/presentation_uk.md`

## Current MVP status

Working:

- Python decorator SDK (`bridge_maker.bm`)
- Adapter loading from a Python file
- Contract export
- Direct SDK Gymnasium environment
- Deterministic annotation suggestions
- JSON/HTML bug report
- NoitaRL adapter template
- Noita WebSocket API readiness notes from a real external repo inspection
- Executable Noita WebSocket session test using a fake Noita client

Optional/research:

- CE MCP and Ghidra MCP are retained as future grey-box assist tools.
- Ray/RLlib training code exists, but the grant demo currently proves the lower-level contract and QA report path first.

## Project direction

See `master_roadmap_v3.md`. Older CoQ/Harmony/socket experiments were removed from the active tree to keep the product context focused.

## Real adapter target

`adapters/noita_ws/README.md` records the first serious external target inspection: `probable-basilisk/noita-ws-api` at commit `47054b0`. `tests/test_noita_ws_session.py` also verifies the adapter boundary with a fake Noita client that sends heartbeat messages and replies to raw Lua eval commands. The live Noita adapter is intentionally not claimed as complete; it needs the game/mod runtime and a stricter lockstep protocol. The important product point is that Bridge-Maker's core consumes a semantic contract, so Noita-specific transport details stay in the adapter.
