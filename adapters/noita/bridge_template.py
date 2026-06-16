from __future__ import annotations

from typing import Protocol

from bridge_maker import bm


class NoitaBindings(Protocol):
    def hp(self) -> float: ...

    def pos(self) -> tuple[float, float]: ...

    def press(self, key: str) -> None: ...


def bind(noita: NoitaBindings):
    @bm.hp(bounds=(0, 100))
    def hp():
        return noita.hp()

    @bm.position(x="x", y="y", bounds=(-100000, 100000))
    def position():
        return noita.pos()

    @bm.move("left", key="a")
    def move_left():
        noita.press("a")

    @bm.move("right", key="d")
    def move_right():
        noita.press("d")

    @bm.move("up", key="w")
    def move_up():
        noita.press("w")

    @bm.move("down", key="s")
    def move_down():
        noita.press("s")

    return bm.registry
