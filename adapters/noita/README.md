# NoitaRL Adapter Spike

This folder is intentionally a template, not a hardcoded Noita integration.

The contract-first architecture treats NoitaRL-style reverse projects as first-class adapters. A real adapter should import the existing NoitaRL memory/action helpers, decorate them with `bm`, and export a Bridge-Maker contract without moving Noita-specific details into `src/`.

Expected shape:

```python
from src.sdk import bm
from noita_rl_project import memory, controls

@bm.hp(bounds=(0, 100))
def hp():
    return memory.player_hp()

@bm.position(x="x", y="y", bounds=(-100000, 100000))
def pos():
    return memory.player_x(), memory.player_y()

@bm.action("move_left", key="a")
def move_left():
    controls.press("a")
```

Once the NoitaRL repo path is available, create a tiny `bridge.py` that imports the real bindings and calls `bind(real_noita)`.

```python
from adapters.noita.bridge_template import bind
from noita_rl_project import noita

bind(noita)
```

The template does not fake Noita. It defines the contract shape that a real NoitaRL binding must satisfy.
