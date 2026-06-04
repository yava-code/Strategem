"""
Aggregates struct field discoveries from multiple sources:
  - CE dissect_structure (heuristic, low confidence)
  - Ghidra decompile_function (static, high confidence)
  - Scout LLM inference (semantic role assignment)

Deduplicates by offset, preferring higher-confidence sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


_ROLE_KEYWORDS: dict[str, list[str]] = {
    "health":       ["hp", "health", "hitpoint", "life", "cur_hp"],
    "coordinate_x": ["pos_x", "posx", "x_pos", "loc_x", "position_x", "coordx"],
    "coordinate_y": ["pos_y", "posy", "y_pos", "loc_y", "position_y", "coordy"],
    "coordinate_z": ["pos_z", "posz", "z_pos", "loc_z", "position_z", "coordz"],
    "depth":        ["depth", "floor", "level", "zone_z", "dungeon_level"],
    "time":         ["turn", "tick", "time", "frame", "clock"],
    "threat":       ["threat", "aggro", "enemy_count", "hostile", "danger"],
    "flag":         ["flag", "bool", "is_", "has_", "can_", "dead", "alive"],
}

_SOURCE_CONFIDENCE = {
    "ghidra_decompile": 0.95,
    "scout_inference":  0.80,
    "ce_dissect":       0.55,
    "manual":           1.00,
}


@dataclass
class DiscoveredField:
    name: str
    offset: int
    type_name: str          # "float" | "int" | "double" | "bool" | ...
    semantic_role: str      # matches SemanticRole enum values
    source: str
    confidence: float = 1.0
    size_bytes: int = 4
    notes: Optional[str] = None


def _infer_role(name: str) -> str:
    lower = name.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return role
    return "scalar"


class StructBuilder:
    """
    Accumulates field discoveries from heterogeneous sources and deduplicates.
    Higher-confidence sources always win at the same offset.
    """

    def __init__(self, class_name: Optional[str] = None):
        self.class_name = class_name
        self._fields: dict[int, DiscoveredField] = {}   # keyed by offset

    def _put(self, f: DiscoveredField) -> None:
        existing = self._fields.get(f.offset)
        if existing is None or f.confidence > existing.confidence:
            self._fields[f.offset] = f

    def add_from_dissect(
        self,
        raw_fields: list[dict],
        known_offsets: Optional[dict[str, int]] = None,
    ) -> None:
        """
        Ingests CE dissect_structure output.
        known_offsets: {field_name: offset} lets us label CE's anonymous fields.
        """
        known_offsets = known_offsets or {}
        reverse_map = {v: k for k, v in known_offsets.items()}

        for f in raw_fields:
            offset = int(f.get("offset", 0))
            known_name = reverse_map.get(offset)
            type_hint = f.get("guessed_type", f.get("type", "float"))
            name = known_name or f"field_{offset:03X}"
            self._put(DiscoveredField(
                name=name,
                offset=offset,
                type_name=type_hint,
                semantic_role=_infer_role(name),
                source="ce_dissect",
                confidence=_SOURCE_CONFIDENCE["ce_dissect"],
                size_bytes=_type_size(type_hint),
            ))

    def add_from_static_analysis(self, static_fields: list[dict]) -> None:
        """
        Ingests Ghidra-decompile Scout output (StaticAnalysisOutput.struct_fields).
        Fields here have explicit names from source and are most authoritative.
        """
        for f in static_fields:
            offset = int(f.get("offset", 0))
            name = f.get("name", f"field_{offset:03X}")
            type_hint = f.get("type", "float")
            role = f.get("semantic_role") or _infer_role(name)
            self._put(DiscoveredField(
                name=name,
                offset=offset,
                type_name=type_hint,
                semantic_role=role,
                source="ghidra_decompile",
                confidence=_SOURCE_CONFIDENCE["ghidra_decompile"],
                size_bytes=_type_size(type_hint),
            ))

    def add_from_scout(self, scout_fields: list[dict]) -> None:
        """Ingests Groq Scout inference output."""
        for f in scout_fields:
            offset = int(f.get("offset", 0))
            name = f.get("name", f"field_{offset:03X}")
            type_hint = f.get("type", "float")
            role = f.get("semantic_role") or _infer_role(name)
            self._put(DiscoveredField(
                name=name,
                offset=offset,
                type_name=type_hint,
                semantic_role=role,
                source="scout_inference",
                confidence=_SOURCE_CONFIDENCE["scout_inference"],
                size_bytes=_type_size(type_hint),
            ))

    def finalize(self) -> list[DiscoveredField]:
        """Return fields sorted by offset, deduped."""
        return sorted(self._fields.values(), key=lambda f: f.offset)

    def to_state_map_format(
        self,
        pointer_chains: dict[str, dict],
        known_value_ranges: Optional[dict[str, tuple[float, float]]] = None,
    ) -> dict[str, dict]:
        """
        Converts to the state_variables format expected by StateMap.
        Fields without a pointer chain are tagged dynamic_only=True.
        """
        known_value_ranges = known_value_ranges or {}
        result: dict[str, dict] = {}

        for f in self.finalize():
            chain = pointer_chains.get(f.name)
            lo, hi = known_value_ranges.get(f.name, (0.0, 100.0))
            result[f.name] = {
                "type": f.type_name,
                "min": lo,
                "max": hi,
                "role": f.semantic_role,
                "pointer_chain": chain,
                "struct_offset": f.offset,
                "dynamic_only": chain is None,
                "source": f.source,
            }

        return result


def _type_size(type_name: str) -> int:
    t = type_name.lower()
    if t in ("double", "int64", "uint64", "long"):
        return 8
    if t in ("float", "int", "uint", "dword", "bool", "byte"):
        return 4
    if t in ("short", "word", "uint16"):
        return 2
    if t == "byte":
        return 1
    return 4
