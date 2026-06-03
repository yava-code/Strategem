# MVP Step 1 — Connector framework + transport

**Files:** `src/connectors/{__init__,base,socket_transport}.py`

- `base.py`: `Connector` ABC (detect / discover_schema / open_transport),
  `GameTransport` ABC (connect / reset / step / close), `StateFrame` dataclass
  with `from_wire`.
- `socket_transport.py`: length-prefixed (4-byte BE) JSON TCP client with connect
  retries + `TCP_NODELAY`. Lifted framing from `engine_bridges.py` so the mock and
  the CoQ mod share one wire format.

**Verified:** imports + AST clean; used live by the swarm against the mock.
