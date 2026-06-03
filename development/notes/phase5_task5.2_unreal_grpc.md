# Task 5.2 — Unreal Engine Learning Agents Adaptor

**File:** `src/engine_bridges.py` → `UnrealLearningAgentsBridge`

- gRPC binding via the low-level `channel.unary_unary` generic-stub API (JSON
  serializer/deserializer) — no compiled `.proto` required — against the
  `/UnrealLearningAgents/Exchange` method.
- Length-prefixed JSON **socket IPC** fallback (`TCP_NODELAY`) when `grpcio` is
  absent — the alternate transport from the architecture diagram.
- Shared wire contract: `{"cmd":"step","action":[...]}` ↔
  `{"obs":[...],"reward":...,"terminated":...,"truncated":...,"info":{}}`.
- `timeout=0.003` encodes the <3 ms latency verification target.
