from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional

from src.sdk.specs import (
    ActionSpec,
    EventSpec,
    OracleSpec,
    REGISTRY,
    StateSpec,
)


def _source(fn: Callable[..., Any]) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


def _as_bounds(bounds: Optional[tuple[float, float]]) -> Optional[tuple[float, float]]:
    if bounds is None:
        return None
    lo, hi = bounds
    return float(lo), float(hi)


class BridgeMakerAnnotations:
    @property
    def registry(self):
        return REGISTRY

    def reset_registry(self) -> None:
        REGISTRY.clear()

    def state(
        self,
        name: Optional[str] = None,
        *,
        role: str = "scalar",
        bounds: Optional[tuple[float, float]] = None,
        dtype: str = "float",
        tags: tuple[str, ...] = (),
    ):
        def deco(fn: Callable[[], Any]):
            field = name or fn.__name__
            REGISTRY.add_state(
                StateSpec(
                    name=field,
                    role=role,
                    getter=fn,
                    bounds=_as_bounds(bounds),
                    dtype=dtype,
                    source=_source(fn),
                    tags=tags,
                )
            )
            return fn

        return deco

    def hp(
        self,
        name: str = "hp",
        *,
        bounds: Optional[tuple[float, float]] = None,
        max_ref: Optional[str] = None,
    ):
        tags = (f"max_ref:{max_ref}",) if max_ref else ()
        return self.state(name, role="health", bounds=bounds, dtype="float", tags=tags)

    def scalar(
        self,
        name: Optional[str] = None,
        *,
        bounds: Optional[tuple[float, float]] = None,
        dtype: str = "float",
    ):
        return self.state(name, role="scalar", bounds=bounds, dtype=dtype)

    def flag(self, name: Optional[str] = None):
        return self.state(name, role="flag", bounds=(0.0, 1.0), dtype="bool")

    def item(self, name: Optional[str] = None, *, collection: Optional[str] = None):
        tags = (f"collection:{collection}",) if collection else ()
        return self.state(name, role="scalar", bounds=(0.0, 9999.0), dtype="int", tags=tags)

    def position(
        self,
        *,
        x: str = "x",
        y: str = "y",
        z: Optional[str] = None,
        bounds: Optional[tuple[float, float]] = None,
    ):
        def deco(fn: Callable[[], Any]):
            names = [x, y] + ([z] if z else [])
            roles = ["coordinate_x", "coordinate_y"] + (["coordinate_z"] if z else [])

            for idx, (field, role) in enumerate(zip(names, roles)):
                def getter(i=idx, f=fn):
                    return f()[i]

                REGISTRY.add_state(
                    StateSpec(
                        name=field,
                        role=role,
                        getter=getter,
                        bounds=_as_bounds(bounds),
                        dtype="float",
                        source=f"{_source(fn)}[{idx}]",
                    )
                )
            return fn

        return deco

    def action(
        self,
        name: Optional[str] = None,
        *,
        key: Optional[str] = None,
        cooldown: Optional[float] = None,
        tags: tuple[str, ...] = (),
    ):
        def deco(fn: Callable[[], Any]):
            action_name = name or fn.__name__
            REGISTRY.add_action(
                ActionSpec(
                    name=action_name,
                    fn=fn,
                    key=key,
                    cooldown=cooldown,
                    source=_source(fn),
                    tags=tags,
                )
            )
            return fn

        return deco

    def move(self, direction: str, *, key: Optional[str] = None):
        return self.action(f"move_{direction}", key=key, tags=("movement", direction))

    def interact(self, name: str = "interact", *, key: Optional[str] = None):
        return self.action(name, key=key, tags=("interaction",))

    def use_item(self, name: Optional[str] = None, *, key: Optional[str] = None):
        return self.action(name or "use_item", key=key, tags=("item",))

    def attack(self, name: str = "attack", *, key: Optional[str] = None):
        return self.action(name, key=key, tags=("combat",))

    def event(self, name: Optional[str] = None, *, tags: tuple[str, ...] = ()):
        def deco(fn: Callable[..., Any]):
            event_name = name or fn.__name__
            REGISTRY.add_event(EventSpec(name=event_name, fn=fn, source=_source(fn), tags=tags))

            @wraps(fn)
            def wrapped(*args, **kwargs):
                return fn(*args, **kwargs)

            return wrapped

        return deco

    def oracle(self, name: Optional[str] = None, *, severity: str = "bug", tags: tuple[str, ...] = ()):
        def deco(fn: Callable[[Any], bool]):
            oracle_name = name or fn.__name__
            REGISTRY.add_oracle(
                OracleSpec(
                    name=oracle_name,
                    fn=fn,
                    severity=severity,
                    source=_source(fn),
                    tags=tags,
                )
            )
            return fn

        return deco

    def reset(self, fn: Callable[[], Any]):
        REGISTRY.reset_hook = fn
        return fn

    def snapshot(self, fn: Callable[[], dict[str, Any]]):
        REGISTRY.snapshot_hook = fn
        return fn


bm = BridgeMakerAnnotations()
