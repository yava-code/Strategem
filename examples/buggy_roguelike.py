from __future__ import annotations

from bridge_maker import bm


class BuggyRoguelike:
    width = 10
    height = 8

    def __init__(self):
        self.reset()

    def reset(self):
        self.hp = 10.0
        self.x = 8.0
        self.y = 4.0
        self.gold = 0
        self.turn = 0

    def move_right(self):
        self.x += 1.0  # Intentional bug: no right-edge clamp.
        self.turn += 1

    def move_left(self):
        self.x = max(0.0, self.x - 1.0)
        self.turn += 1

    def wait(self):
        self.turn += 1

    def pickup_gold(self):
        if self.x >= 9:
            self.gold += 1
        self.turn += 1


game = BuggyRoguelike()


@bm.reset
def reset_game():
    game.reset()


@bm.hp(bounds=(0, 10))
def hp():
    return game.hp


@bm.position(x="x", y="y", bounds=(0, 9))
def position():
    return game.x, game.y


@bm.item("gold")
def gold():
    return game.gold


@bm.scalar("turn", bounds=(0, 1000), dtype="int")
def turn():
    return game.turn


@bm.move("right", key="d")
def move_right():
    game.move_right()


@bm.move("left", key="a")
def move_left():
    game.move_left()


@bm.action("wait", key=".")
def wait():
    game.wait()


@bm.interact("pickup_gold", key="e")
def pickup_gold():
    game.pickup_gold()


@bm.oracle("out_of_bounds", severity="bug")
def out_of_bounds(state):
    return state.x < 0 or state.x > 9 or state.y < 0 or state.y > 7


@bm.oracle("invalid_health", severity="bug")
def invalid_health(state):
    return state.hp < 0 or state.hp > 10


@bm.snapshot
def snapshot():
    return {"hp": game.hp, "x": game.x, "y": game.y, "gold": game.gold, "turn": game.turn}
