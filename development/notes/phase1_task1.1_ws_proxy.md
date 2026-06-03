# Task 1.1 — Web & WebSocket Proxy Interceptor

**File:** `src/auto_analyzer.py` → `NetworkProxyStrategy`

- Added a real RFC 6455 frame decoder (`_decode_ws_frame`): parses FIN/len/mask
  bytes, unmasks the payload, and JSON-decodes text frames.
- Two capture paths: passive `scapy.sniff` on `tcp port 8080` (when Scapy is
  present) and a short-lived loopback proxy that accepts one client and decodes
  its first WS frame.
- Nested JSON state objects are flattened (`_flatten`) into `net_*` channels and
  the JSON path is recorded per field for runtime re-reads.

**Verified:** `python -m src.auto_analyzer --strategy network` decodes/falls back
cleanly and writes a 6-dim schema.
