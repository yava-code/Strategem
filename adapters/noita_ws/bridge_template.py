from __future__ import annotations

from bridge_maker import bm

from adapters.noita_ws.session import NoitaWsSession


def bind(session: NoitaWsSession):
    @bm.hp(bounds=(0, 100))
    def hp():
        return session.eval_float("return get_player_hp()")

    @bm.position(x="x", y="y", bounds=(-50000, 50000))
    def pos():
        return session.eval_vec2("return get_player_xy()")

    @bm.action("move_left", key="a")
    def move_left():
        session.exec("bridge_apply_action('move_left')")

    @bm.action("move_right", key="d")
    def move_right():
        session.exec("bridge_apply_action('move_right')")

    @bm.oracle("player_missing", severity="bug")
    def player_missing(_state):
        return session.eval_bool("return bridge_player_missing()")

    return bm.registry
