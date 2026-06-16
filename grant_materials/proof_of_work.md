# Bridge-Maker Proof of Work

## Commands verified

- python -m compileall bridge_maker src examples adapters
- python -m bridge_maker demo --out runs/grant_demo
- python -m bridge_maker smoke --adapter examples/annotated_dummy.py --steps 20
- python -m bridge_maker report --contract runs/grant_demo
- python -m unittest tests.test_noita_ws_session

## Demo result

- Game: buggy_roguelike
- State fields: 5
- Actions: 4
- Oracles: 2
- Trace frames: 13
- Oracle hits: 3
- Status: bug_found

## Real external target inspected

- Repository: probable-basilisk/noita-ws-api
- Local commit: 47054b0
- Adapter readiness: grant_materials/noita_ws_readiness.md
- Adapter boundary test: fake Noita client heartbeat + raw Lua replies passed.
- Live Noita execution pending game/mod runtime setup.

## First finding

- Oracle: out_of_bounds
- Action: move_right
- State: {"hp": 10.0, "x": 10.0, "y": 4.0, "gold": 0, "turn": 2}
