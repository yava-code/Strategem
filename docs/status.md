# Current Status

Last verified in this session:

- `python -m bridge_maker --help` works.
- `python -m unittest discover -s tests` passes: 4 tests OK.
- `python -m bridge_maker demo --out runs/docs_demo` produces:
  - annotation suggestions;
  - `state_map.json`;
  - `action_map.json`;
  - `oracle_map.json`;
  - `trace.jsonl`;
  - generated SDK env;
  - `report.html`.

## Ready

- SDK decorators.
- Contract registry.
- Adapter loader.
- Contract export.
- SDK Gymnasium smoke env.
- Deterministic annotation suggestions.
- Static JSON/HTML report generation.
- Buggy roguelike proof demo.
- Noita WebSocket adapter boundary test with fake client.

## Experimental / optional

- CE MCP and Ghidra MCP grey-box assist.
- Pymem generated live env.
- Ray/RLlib trainer.
- Oracle/dashboard integration.

These are valuable, but the public MVP story should focus on the stable contract
and report loop.

