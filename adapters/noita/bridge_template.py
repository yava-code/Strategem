from __future__ import annotations

from bridge_maker import bm


class NoitaBindings:
    """
    Replace this class with imports from the real NoitaRL project.
    Keep Noita-specific logic in this adapter, not in Bridge-Maker core.
    """
    def hp(self) -> float:
        raise RuntimeError("Wire this to NoitaRL's player HP reader.")

    def pos(self) -> tuple[float, float]:
        raise RuntimeError("Wire this to NoitaRL's player position reader.")

    def press(self, key: str) -> None:
        raise RuntimeError(f"Wire this to NoitaRL input for key={key!r}.")


noita = NoitaBindings()


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
