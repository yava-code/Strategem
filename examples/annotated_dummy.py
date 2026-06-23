from __future__ import annotations

from bridge_maker import bm


class TinyRoguelike:
    def __init__(self):
        self.reset()

    def reset(self):
        self.hp = 100.0
        self.x = 5.0
        self.y = 5.0
        self.gold = 0
        self.turn = 0

    def move(self, dx: float, dy: float):
        self.x += dx
        self.y += dy
        self.turn += 1

    def attack(self):
        self.hp = max(0.0, self.hp - 1.0)
        self.gold += 1
        self.turn += 1


game = TinyRoguelike()


@bm.reset
def reset_game():
    game.reset()


@bm.hp(bounds=(0, 100))
def hp():
    return game.hp


@bm.position(x="x", y="y", bounds=(0, 100))
def position():
    return game.x, game.y


@bm.item("gold")
def gold():
    return game.gold


@bm.scalar("turn", bounds=(0, 10_000), dtype="int")
def turn():
    return game.turn


@bm.move("left", key="a")
def move_left():
    game.move(-1.0, 0.0)


@bm.move("right", key="d")
def move_right():
    game.move(1.0, 0.0)


@bm.move("up", key="w")
def move_up():
    game.move(0.0, -1.0)


@bm.move("down", key="s")
def move_down():
    game.move(0.0, 1.0)


@bm.attack("attack", key="space")
def attack():
    game.attack()


@bm.event("damage")
def take_damage(amount: float):
    game.hp = max(0.0, game.hp - amount)


@bm.oracle("invalid_health")
def invalid_health(state):
    return state.hp < 0 or state.hp > 100


@bm.snapshot
def snapshot():
    return {"hp": game.hp, "x": game.x, "y": game.y, "gold": game.gold, "turn": game.turn}
