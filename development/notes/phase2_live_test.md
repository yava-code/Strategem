# Phase 2 Live Test — sterile lab results (2026-06-04)

## Target: tools/dummy_target.py (Python ctypes PlayerState)

```
struct PlayerState { float health; float max_health; float pos_x; float pos_y; int32 turn; }
```
Health starts at 100.0, decrements 10 every 20s. Struct allocated on Python heap.

---

## Discovery results

| Step | Result |
|------|--------|
| CE attach (PID 25380) | PASS |
| python.exe module base | 0x7FF7198E0000 (from enum_modules "address" key) |
| First scan (float 100.0) | 12 candidates |
| Wait 2 ticks (health → 80.0) | confirmed via log |
| Exact scan for 80.0 | **1 candidate** |
| Found address | `0x15F6202DD50` |
| Target-reported address | `0x0000015F6202DD50` |
| **Match** | **YES — CONFIRMED** |

## Struct decode at `0x15F6202DD50` (24 bytes)

```
00 00 A0 42  00 00 C8 42  00 00 E0 40  00 00 C0 40  02 00 00 00  00 00 00 00
```

| Offset | Bytes        | Decoded   | Field      | Expected  |
|--------|-------------|-----------|-----------|-----------|
| 0x00   | 00 00 A0 42 | 80.0 (f)  | health    | 80.0 ✓    |
| 0x04   | 00 00 C8 42 | 100.0 (f) | max_health| 100.0 ✓   |
| 0x08   | 00 00 E0 40 | 7.0 (f)   | pos_x     | 5.0+2=7.0 ✓ |
| 0x0C   | 00 00 C0 40 | 6.0 (f)   | pos_y     | 5.0+1=6.0 ✓ |
| 0x10   | 02 00 00 00 | 2 (i32)   | turn      | 2 ✓       |

**All 5 fields decode correctly.**

## state_map_python.json

Written with:
- `health.pointer_chain.base = "0x15F6202DD50"`, `verified = true`
- `health.dynamic_only = false`
- All other fields: `struct_offset` correct, `dynamic_only = true` (heap, no static ptr)

---

## Key lessons

### CE MCP pipe conflict
- Claude Desktop holds `\\.\pipe\CE_MCP_Bridge_v99` as a persistent MCP server.
- `CEClient` (subprocess approach) tries to open a SECOND instance of `mcp_cheatengine.py` which also connects to the same pipe → fails with `"Bridge is not reachable"`.
- **Fix for test_discovery_live.py**: when Claude Desktop CE MCP is active, drive the test via direct `mcp__cheatengine__*` tool calls in the Claude session rather than CEClient subprocess.
- **Fix for production**: orchestrator_v2.py should detect CE MCP availability at startup.

### "decreased" scan mode returns 0
- `persistent_scan_next_scan` with `scan_option="decreased"` returns 0 candidates reliably.
- Root cause: likely a CE Lua bridge limitation or timing issue.
- **Confirmed fix**: read current health from log and use `scan_option="exact"` with the actual new value → finds exactly 1 candidate every time.

### Scan timing
- Target ticks every 20s. With `asyncio.sleep(22)` two ticks can happen if there was startup delay.
- **Fix**: read CURRENT health from log immediately before first_scan (not assume 100.0).
- `test_discovery_live.py` updated to do this.

### scan_option value in first_scan
- `persistent_scan_first_scan` requires `value` to be a string (CE converts to float internally).
- Passing `"100"` or `"100.0"` both work for float scan.
