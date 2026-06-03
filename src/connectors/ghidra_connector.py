import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from src.connectors.base import Connector, GameTransport

# =====================================================================
# Native-binary rung (DCSS / Brogue / Cataclysm-DDA — real C/C++ roguelikes).
# Drives the GhidraMCP HTTP bridge: an orchestra of agents can search functions,
# decompile, and chase xrefs to locate the player struct + field offsets. That
# yields a *pointer map*; runtime values are then read with pymem (ASLR-resolved).
# NOT used for Unity/LÖVE targets — Ghidra would only see the engine runtime.
# =====================================================================

COORD_KEYWORDS = ("player_x", "playerx", "pos_x", "posx", "coord", "position")
HEALTH_KEYWORDS = ("health", "hp", "hitpoint", "hitpoints")


class GhidraConnector(Connector):
    name = "ghidra-native"

    def __init__(self, mcp_url: str = "http://127.0.0.1:8080", host: str = "127.0.0.1",
                 port: int = 50545):
        self.mcp_url = mcp_url.rstrip("/")
        self.host = host
        self.port = port

    def detect(self, target: str) -> bool:
        # Native if it's a PE/ELF without a managed/LÖVE runtime alongside it.
        if os.path.isdir(target):
            siblings = os.listdir(target)
            if any(s == "MonoBleedingEdge" or s.lower() == "love.dll" for s in siblings):
                return False
            return any(s.lower().endswith(".exe") for s in siblings)
        return target.lower().endswith((".exe", ".elf", ".bin")) or os.access(target, os.X_OK)

    def _get(self, endpoint: str, params: Dict[str, str] = None) -> Any:
        url = f"{self.mcp_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return [ln for ln in body.splitlines() if ln.strip()]

    def discover_schema(self, target: str) -> Dict[str, Any]:
        try:
            functions = self._get("searchFunctions", {"query": "player"})
            strings = self._get("strings", {"filter": "hp"})
        except (urllib.error.URLError, OSError) as e:
            raise ConnectionError(
                f"GhidraMCP not reachable at {self.mcp_url} ({e}). "
                "Open the target in Ghidra, run the GhidraMCP plugin, then retry."
            ) from e

        candidates = self._rank_candidates(functions, strings)
        state_vars = {
            name: {"type": "float", "min": 0.0, "max": 1000.0, "role": role,
                   "importance": 1.0 if role in ("coordinate", "health") else 0.5,
                   "normalize": {"method": "min_max", "low": 0.0, "high": 1000.0},
                   "ghidra_symbol": sym, "source": "ghidra-native"}
            for name, role, sym in candidates
        }
        return {
            "game_name": os.path.basename(target.rstrip("/\\")),
            "engine": "native",
            "observation_dimensions": len(state_vars),
            "state_variables": state_vars,
            "actions": {"discrete_actions_count": 5,
                        "bindings": ["MOVE_N", "MOVE_S", "MOVE_E", "MOVE_W", "WAIT"]},
        }

    @staticmethod
    def _rank_candidates(functions: List[Any], strings: List[Any]) -> List[tuple]:
        out: List[tuple] = []
        for sym in [str(s) for s in (functions or [])]:
            low = sym.lower()
            if any(k in low for k in COORD_KEYWORDS):
                out.append(("native_player_x", "coordinate", sym))
            elif any(k in low for k in HEALTH_KEYWORDS):
                out.append(("native_health", "health", sym))
        if not out:  # ensure a usable minimal schema even on a sparse symbol table
            out = [("native_player_x", "coordinate", "?"),
                   ("native_player_y", "coordinate", "?"),
                   ("native_health", "health", "?")]
        return out

    def open_transport(self, target: str, schema: Dict[str, Any]) -> GameTransport:
        raise NotImplementedError(
            "Native runtime reads require a resolved pointer map (Ghidra offsets -> "
            "pymem ASLR resolution). That milestone follows the CoQ demo; until then "
            "use the dotnet-mono or mock transport."
        )
