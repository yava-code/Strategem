"""
Minimal game-state target for testing the Bridge-Maker discovery pipeline.

Layout (mimics a simple roguelike player struct):
  offset 0x00  float  health      starts at 100.0, decrements 10/tick
  offset 0x04  float  max_health  constant 100.0
  offset 0x08  float  pos_x       increments 1.0/tick
  offset 0x0C  float  pos_y       increments 0.5/tick
  offset 0x10  int32  turn        counter

Auto-ticks every TICK_SECS seconds so CE can be attached without
needing keyboard input. Prints struct address so you can verify CE found
the right location.
"""
import ctypes
import os
import sys
import time

TICK_SECS = 20  # seconds between state changes (gives time for scan rounds)


class PlayerState(ctypes.Structure):
    _fields_ = [
        ("health",     ctypes.c_float),
        ("max_health", ctypes.c_float),
        ("pos_x",      ctypes.c_float),
        ("pos_y",      ctypes.c_float),
        ("turn",       ctypes.c_int32),
    ]


# Allocate in a module-level buffer — keeps address stable within session
_BUF = (ctypes.c_byte * ctypes.sizeof(PlayerState))()
state = PlayerState.from_buffer(_BUF)
state.health     = 100.0
state.max_health = 100.0
state.pos_x      = 5.0
state.pos_y      = 5.0
state.turn       = 0

BASE_ADDR   = ctypes.addressof(state)
HP_ADDR     = BASE_ADDR + PlayerState.health.offset
POS_X_ADDR  = BASE_ADDR + PlayerState.pos_x.offset

# ── Print discovery anchor info ──────────────────────────────────────────────
print(f"[DummyTarget] PID        : {os.getpid()}", flush=True)
print(f"[DummyTarget] struct addr: 0x{BASE_ADDR:016X}", flush=True)
print(f"[DummyTarget] health addr: 0x{HP_ADDR:016X}  (offset 0x{PlayerState.health.offset:02X})", flush=True)
print(f"[DummyTarget] pos_x  addr: 0x{POS_X_ADDR:016X}  (offset 0x{PlayerState.pos_x.offset:02X})", flush=True)
print(f"[DummyTarget] tick every : {TICK_SECS}s", flush=True)
print("-" * 60, flush=True)

def _print_state():
    print(
        f"  Health: {state.health:6.1f} / {state.max_health:.1f}  "
        f"Pos: ({state.pos_x:.1f}, {state.pos_y:.1f})  "
        f"Turn: {state.turn}",
        flush=True,
    )

try:
    while state.health > 0:
        _print_state()
        time.sleep(TICK_SECS)
        state.health  = max(0.0, state.health - 10.0)
        state.pos_x  += 1.0
        state.pos_y  += 0.5
        state.turn   += 1
except KeyboardInterrupt:
    pass

_print_state()
print("[DummyTarget] Game Over", flush=True)
