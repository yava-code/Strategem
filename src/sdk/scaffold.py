from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def write_starter_project(
    out_dir: str | Path,
    *,
    game_name: str = "MyGame",
    force: bool = False,
) -> dict[str, Path]:
    root = Path(out_dir).resolve()
    adapter = root / "bridge_adapter.py"
    guide = root / "BRIDGE_MAKER_QUICKSTART.md"

    existing = [str(p) for p in (adapter, guide) if p.exists()]
    if existing and not force:
        raise FileExistsError(
            "Bridge-Maker starter files already exist: "
            + ", ".join(existing)
            + ". Re-run with --force to overwrite them."
        )

    root.mkdir(parents=True, exist_ok=True)
    adapter.write_text(_adapter_template(game_name), encoding="utf-8")
    guide.write_text(_guide_template(game_name), encoding="utf-8")
    return {"adapter": adapter, "guide": guide}


def _adapter_template(game_name: str) -> str:
    return dedent(
        f'''\
        from __future__ import annotations

        from bridge_maker import bm


        class { _safe_class_name(game_name) }Bridge:
            """Replace this class with calls into your game or test harness.

            Keep the decorated functions below small. They should expose existing
            game semantics: read state, invoke one action, or check one invariant.
            """

            width = 12
            height = 8

            def __init__(self):
                self.reset()

            def reset(self):
                self.hp = 10.0
                self.x = 5.0
                self.y = 3.0
                self.turn = 0

            def move_left(self):
                self.x = max(0.0, self.x - 1.0)
                self.turn += 1

            def move_right(self):
                self.x = min(float(self.width - 1), self.x + 1.0)
                self.turn += 1

            def wait(self):
                self.turn += 1


        game = { _safe_class_name(game_name) }Bridge()


        @bm.reset
        def reset_game():
            game.reset()


        @bm.hp(bounds=(0, 10))
        def hp():
            return game.hp


        @bm.position(x="x", y="y", bounds=(0, 12))
        def position():
            return game.x, game.y


        @bm.scalar("turn", bounds=(0, 1000), dtype="int")
        def turn():
            return game.turn


        @bm.move("left", key="a")
        def move_left():
            game.move_left()


        @bm.move("right", key="d")
        def move_right():
            game.move_right()


        @bm.action("wait", key=".")
        def wait():
            game.wait()


        @bm.oracle("out_of_bounds", severity="bug")
        def out_of_bounds(state):
            return state.x < 0 or state.x >= game.width or state.y < 0 or state.y >= game.height


        @bm.oracle("invalid_health", severity="bug")
        def invalid_health(state):
            return state.hp < 0 or state.hp > 10


        @bm.snapshot
        def snapshot():
            return {{"hp": game.hp, "x": game.x, "y": game.y, "turn": game.turn}}
        '''
    )


def _guide_template(game_name: str) -> str:
    return dedent(
        f'''\
        # Bridge-Maker quickstart for {game_name}

        This folder contains a working starter adapter:

        - `bridge_adapter.py` - replace the `*Bridge` class internals with calls
          into your game, debug API, mod API, or test harness.

        Verify the adapter:

        ```powershell
        bridge-maker smoke --adapter bridge_adapter.py --steps 12
        ```

        Validate the contract quality:

        ```powershell
        bridge-maker validate --adapter bridge_adapter.py --out .\\validation
        ```

        Run the full basic QA pipeline:

        ```powershell
        bridge-maker run --adapter bridge_adapter.py --out ..\\runs\\{_safe_slug(game_name)} --game-name "{game_name}"
        ```

        If you want CI-style control, the `run` command can be split into:

        ```powershell
        bridge-maker export --adapter bridge_adapter.py --out ..\\runs\\{_safe_slug(game_name)} --game-name "{game_name}"
        bridge-maker report --contract ..\\runs\\{_safe_slug(game_name)}
        ```

        What to wire first:

        1. Health or another failure-relevant resource.
        2. Position or progress through the level.
        3. Four to twelve legal actions.
        4. Two to five oracles that mark states your QA team would call a bug.

        Keep the first integration small. A useful first Bridge-Maker contract is
        often five state fields, four actions, and two bug checks.
        '''
    )


def _safe_class_name(name: str) -> str:
    chars = [c if c.isalnum() else " " for c in name]
    parts = "".join(chars).split()
    candidate = "".join(p[:1].upper() + p[1:] for p in parts) or "Game"
    if not candidate[0].isalpha():
        return f"Game{candidate}"
    return candidate


def _safe_slug(name: str) -> str:
    chars = [c.lower() if c.isalnum() else "_" for c in name]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "game"
