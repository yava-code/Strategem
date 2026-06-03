import os
import zipfile
from typing import Any, Dict, List

from src.connectors.base import Connector, GameTransport
from src.connectors.socket_transport import SocketTransport

# =====================================================================
# LÖVE / Lua rung (Balatro and friends).
# A fused LÖVE .exe is the runtime with a zip of the game's .lua appended, so we
# can read the actual game source statically (no decompiler needed) and scan for
# state globals. Runtime values come from a Lovely/Steamodded Lua bridge mod that
# speaks the same socket protocol as the CoQ bridge.
# =====================================================================

STATE_KEYWORDS = ("money", "chips", "mult", "score", "ante", "round", "hp", "health", "hand")


class LuaBridgeConnector(Connector):
    name = "love-lua"

    def __init__(self, host: str = "127.0.0.1", port: int = 50545):
        self.host = host
        self.port = port

    def detect(self, target: str) -> bool:
        if os.path.isdir(target):
            return any(s.lower() == "love.dll" for s in os.listdir(target))
        return target.lower().endswith(".exe") and self._read_lua_names(target) != []

    @staticmethod
    def _exe_in(target: str) -> str:
        if os.path.isfile(target):
            return target
        for s in os.listdir(target):
            if s.lower().endswith(".exe") and "crash" not in s.lower():
                return os.path.join(target, s)
        return ""

    def _read_lua_names(self, target: str) -> List[str]:
        exe = self._exe_in(target)
        if not exe or not os.path.isfile(exe):
            return []
        try:
            with zipfile.ZipFile(exe) as z:  # LÖVE appends a readable zip
                return [n for n in z.namelist() if n.endswith(".lua")]
        except (zipfile.BadZipFile, OSError):
            return []

    def discover_schema(self, target: str) -> Dict[str, Any]:
        exe = self._exe_in(target)
        found: Dict[str, str] = {}
        try:
            with zipfile.ZipFile(exe) as z:
                for name in [n for n in z.namelist() if n.endswith(".lua")]:
                    text = z.read(name).decode("utf-8", errors="ignore").lower()
                    for kw in STATE_KEYWORDS:
                        if kw in text and kw not in found:
                            found[kw] = name
        except (zipfile.BadZipFile, OSError, ValueError):
            found = {kw: "?" for kw in ("money", "chips", "mult", "ante")}

        state_vars = {}
        for kw, src in found.items():
            role = "health" if kw in ("hp", "health") else "scalar"
            state_vars[f"lua_{kw}"] = {
                "type": "float", "min": 0.0, "max": 1e6, "role": role,
                "importance": 0.8 if kw in ("score", "chips", "money") else 0.4,
                "normalize": {"method": "min_max", "low": 0.0, "high": 1e6},
                "lua_source": src, "source": "love-lua",
            }
        return {
            "game_name": os.path.basename(target.rstrip("/\\")),
            "engine": "love-lua",
            "observation_dimensions": len(state_vars),
            "state_variables": state_vars,
            "actions": {"discrete_actions_count": 4,
                        "bindings": ["PLAY_HAND", "DISCARD", "BUY", "SKIP"]},
        }

    def open_transport(self, target: str, schema: Dict[str, Any]) -> GameTransport:
        # Requires the Lovely Lua bridge mod to be installed and listening.
        return SocketTransport(host=self.host, port=self.port)
