# SDK Reference

Public entry point:

```python
from bridge_maker import bm
```

## State decorators

### `@bm.state(name=None, role="scalar", bounds=None, dtype="float")`

Generic read-only observation.

```python
@bm.state("mana", role="resource", bounds=(0, 100))
def mana():
    return player.mana
```

### `@bm.hp(name="hp", bounds=None, max_ref=None)`

Health shortcut. Generates a state variable with role `health`.

```python
@bm.hp(bounds=(0, 10))
def hp():
    return game.hp
```

### `@bm.position(x="x", y="y", z=None, bounds=None)`

Splits one function returning coordinates into separate state variables.

```python
@bm.position(x="x", y="y", bounds=(0, 100))
def position():
    return player.x, player.y
```

### `@bm.item(name=None, collection=None)`

Tracks an item/resource count.

```python
@bm.item("gold")
def gold():
    return inventory.gold
```

### `@bm.flag(name=None)`

Boolean observation normalized to `0..1`.

```python
@bm.flag("boss_alive")
def boss_alive():
    return boss.alive
```

### `@bm.scalar(name=None, bounds=None, dtype="float")`

Numeric observation that is not a special semantic role.

```python
@bm.scalar("turn", bounds=(0, 1000), dtype="int")
def turn():
    return game.turn
```

## Action decorators

### `@bm.action(name=None, key=None, cooldown=None)`

Generic action.

```python
@bm.action("wait", key=".")
def wait():
    game.wait()
```

### `@bm.move(direction, key=None)`

Movement shortcut. Produces action name `move_<direction>`.

```python
@bm.move("left", key="a")
def move_left():
    game.move_left()
```

### `@bm.interact(name="interact", key=None)`

Interaction shortcut.

```python
@bm.interact("open_chest", key="e")
def open_chest():
    game.open_chest()
```

### `@bm.use_item(name=None, key=None)`

Item-use shortcut.

### `@bm.attack(name="attack", key=None)`

Combat shortcut.

## Events and oracles

### `@bm.event(name=None)`

Marks state transition events for future action-model learning.

### `@bm.oracle(name=None, severity="bug")`

Defines invalid or suspicious states.

```python
@bm.oracle("out_of_bounds", severity="bug")
def out_of_bounds(state):
    return state.x < 0 or state.x > 9
```

### `@bm.reset`

Defines episode reset if available.

```python
@bm.reset
def reset_game():
    game.reset()
```

### `@bm.snapshot`

Adds a compact game snapshot to traces and reports.

```python
@bm.snapshot
def snapshot():
    return {"hp": game.hp, "x": game.x, "y": game.y}
```

