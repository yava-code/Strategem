import os
from typing import Any, Dict, List

from src.connectors.base import Connector, GameTransport
from src.connectors.socket_transport import SocketTransport

# =====================================================================
# .NET / Unity-Mono connector (active rung — Caves of Qud).
# Game logic ships as managed CIL in Assembly-CSharp.dll, which decompiles to
# near-source. We confirm the schema by reflecting over that assembly when
# pythonnet is present; otherwise we fall back to a curated CoQ schema so
# discovery always yields a valid state_map. Runtime values arrive over the
# socket from the QA Bridge Harmony mod.
# =====================================================================

# CoQ movement is 8-directional; the bridge maps these to GameObject.Move(dir).
ACTION_BINDINGS = ["MOVE_N", "MOVE_S", "MOVE_E", "MOVE_W",
                   "MOVE_NE", "MOVE_NW", "MOVE_SE", "MOVE_SW", "WAIT"]

# CoQ overworld/zone grid is 80x25 cells; HP/level/turn ranges are nominal
# normalization bounds, not hard limits (the bridge reports raw values).
CURATED_COQ_VARS: Dict[str, Dict[str, Any]] = {
    "coq_hp":       {"role": "health",     "min": 0.0, "max": 100.0,  "importance": 1.0, "csharp": "XRL.World.Statistic[Hitpoints].Value"},
    "coq_hp_max":   {"role": "scalar",     "min": 0.0, "max": 100.0,  "importance": 0.7, "csharp": "XRL.World.Statistic[Hitpoints].BaseValue"},
    "coq_x":        {"role": "coordinate", "min": 0.0, "max": 79.0,   "importance": 1.0, "csharp": "XRL.World.Cell.X"},
    "coq_y":        {"role": "coordinate", "min": 0.0, "max": 24.0,   "importance": 1.0, "csharp": "XRL.World.Cell.Y"},
    "coq_depth":    {"role": "scalar",     "min": 0.0, "max": 50.0,   "importance": 0.6, "csharp": "XRL.World.Zone.Z"},
    "coq_hunger":   {"role": "scalar",     "min": 0.0, "max": 100.0,  "importance": 0.5, "csharp": "XRL.World.Parts.Stomach.HungerLevel"},
    "coq_level":    {"role": "scalar",     "min": 1.0, "max": 40.0,   "importance": 0.5, "csharp": "XRL.World.Statistic[Level].Value"},
    "coq_turn":     {"role": "time",       "min": 0.0, "max": 5000.0, "importance": 0.4, "csharp": "XRL.The.Game.Turns"},
    "coq_threats":  {"role": "scalar",     "min": 0.0, "max": 10.0,   "importance": 0.8, "csharp": "Zone.GetObjectsWithPart(Brain) hostile count"},
}


class DotNetConnector(Connector):
    name = "dotnet-mono"

    def __init__(self, host: str = "127.0.0.1", port: int = 50545):
        self.host = host
        self.port = port

    def detect(self, target: str) -> bool:
        if not os.path.isdir(target):
            return False
        has_mono = os.path.isdir(os.path.join(target, "MonoBleedingEdge"))
        return has_mono and self._find_assembly(target) is not None

    @staticmethod
    def _find_assembly(target: str) -> str:
        for data_dir in os.listdir(target):
            managed = os.path.join(target, data_dir, "Managed", "Assembly-CSharp.dll")
            if os.path.isfile(managed):
                return managed
        return None

    def discover_schema(self, target: str) -> Dict[str, Any]:
        assembly = self._find_assembly(target) if os.path.isdir(target) else None
        confirmed = self._reflect(assembly) if assembly else []

        state_vars: Dict[str, Dict[str, Any]] = {}
        for name, info in CURATED_COQ_VARS.items():
            lo, hi = info["min"], info["max"]
            state_vars[name] = {
                "type": "float", "min": lo, "max": hi, "role": info["role"],
                "importance": info["importance"],
                "normalize": {"method": "min_max", "low": lo, "high": hi},
                "csharp_path": info["csharp"], "source": "dotnet-mono",
                "reflection_confirmed": any(c in info["csharp"] for c in confirmed),
            }

        return {
            "game_name": os.path.basename(target.rstrip("/\\")) or "caves_of_qud",
            "engine": "unity-mono",
            "assembly": assembly,
            "observation_dimensions": len(state_vars),
            "state_variables": state_vars,
            "actions": {"discrete_actions_count": len(ACTION_BINDINGS),
                        "bindings": list(ACTION_BINDINGS)},
        }

    @staticmethod
    def _reflect(assembly_path: str) -> List[str]:
        """Best-effort: list managed type names matching our schema keywords."""
        try:
            import clr  # pythonnet
            from System.Reflection import Assembly
        except ImportError:
            print("[DotNet] pythonnet absent; skipping reflection (curated schema stands).")
            return []
        try:
            asm = Assembly.LoadFile(assembly_path)
            wanted = ("Statistic", "GameObject", "Cell", "Zone", "Stomach")
            found = []
            for t in asm.GetTypes():
                full = getattr(t, "FullName", "") or ""
                if any(w in full for w in wanted):
                    found.append(full)
            print(f"[DotNet] Reflected {len(found)} relevant types from Assembly-CSharp.dll.")
            return found
        except Exception as e:
            print(f"[DotNet] Reflection failed ({e}); curated schema stands.")
            return []

    def open_transport(self, target: str, schema: Dict[str, Any]) -> GameTransport:
        # Ready-to-connect; LiveGameEnv calls connect() so each swarm worker owns
        # its own socket to the bridge/mock.
        return SocketTransport(host=self.host, port=self.port)
