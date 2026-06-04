
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
