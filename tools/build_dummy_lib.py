"""
Compiles dummy_lib.c into a DLL via cffi so Ghidra has a real binary to analyze.
Run: python tools/build_dummy_lib.py
Output: tools/dummy_lib.dll  (or .pyd on Windows)
"""
import sys, os
from pathlib import Path

SRC = Path(__file__).parent / "dummy_lib.c"
OUT_DIR = Path(__file__).parent

C_SOURCE = r"""
#include <stdlib.h>
#include <string.h>

typedef struct {
    float health;
    float max_health;
    float pos_x;
    float pos_y;
    int   turn;
} PlayerState;

/* Global pointer — the anchor for pointer chains */
static PlayerState* g_player = NULL;

void  game_init(void)   { g_player = (PlayerState*)malloc(sizeof(PlayerState));
                          g_player->health = 100.0f; g_player->max_health = 100.0f;
                          g_player->pos_x  = 5.0f;   g_player->pos_y      = 5.0f;
                          g_player->turn   = 0; }
void  game_tick(void)   { if (!g_player) return;
                          g_player->health -= 10.0f; if (g_player->health < 0) g_player->health = 0;
                          g_player->pos_x  += 1.0f;  g_player->pos_y += 0.5f;
                          g_player->turn   += 1; }
float get_health(void)  { return g_player ? g_player->health : -1.0f; }
float get_pos_x(void)   { return g_player ? g_player->pos_x  : -1.0f; }
void* get_player_ptr(void) { return (void*)g_player; }
void  game_free(void)   { free(g_player); g_player = NULL; }
"""

SRC.write_text(C_SOURCE, encoding="utf-8")

try:
    from cffi import FFI
    ffi = FFI()
    ffi.cdef("""
        void  game_init(void);
        void  game_tick(void);
        float get_health(void);
        float get_pos_x(void);
        void* get_player_ptr(void);
        void  game_free(void);
    """)
    ffi.set_source(
        "_dummy_lib",
        C_SOURCE,
    )
    lib_path = ffi.compile(tmpdir=str(OUT_DIR), verbose=True)
    print(f"[BuildDummyLib] Compiled: {lib_path}")
    sys.exit(0)
except Exception as exc:
    print(f"[BuildDummyLib] cffi compile failed: {exc}")
    print("[BuildDummyLib] Falling back to ctypes-only target (no DLL for Ghidra)")
    sys.exit(1)
