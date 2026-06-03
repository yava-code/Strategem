import os
from typing import Any, Dict

from src.connectors.base import Connector, GameTransport

# =====================================================================
# Universal fallback rung: screen capture + input injection + curiosity.
# Works on ANY engine because it treats the screen as the API. A VLM pass labels
# semantic scalars (HP bar, score) to fill the schema; a CNN policy consumes the
# frame stack. Heaviest path (more samples, needs a VLM) — last resort when no
# code/memory/SDK connector applies.
# =====================================================================


class VisionConnector(Connector):
    name = "vision-fallback"

    def __init__(self, frame_size: int = 84, host: str = "127.0.0.1", port: int = 50545):
        self.frame_size = frame_size
        self.host = host
        self.port = port

    def detect(self, target: str) -> bool:
        # Universal: anything launchable can be screen-captured.
        return os.path.exists(target)

    def discover_schema(self, target: str) -> Dict[str, Any]:
        # Semantic scalars a VLM is expected to localize on the HUD. Until the
        # VLM pass exists these are declared, not yet auto-detected.
        semantic = {
            "vis_player_x": "coordinate", "vis_player_y": "coordinate",
            "vis_health": "health", "vis_score": "scalar",
        }
        state_vars = {
            name: {"type": "float", "min": 0.0, "max": 1.0, "role": role,
                   "importance": 1.0 if role in ("coordinate", "health") else 0.5,
                   "normalize": {"method": "min_max", "low": 0.0, "high": 1.0},
                   "source": "vision-fallback", "needs_vlm": True}
            for name, role in semantic.items()
        }
        return {
            "game_name": os.path.basename(target.rstrip("/\\")),
            "engine": "vision",
            "frame_size": self.frame_size,
            "observation_dimensions": len(state_vars),
            "state_variables": state_vars,
            "actions": {"discrete_actions_count": 5,
                        "bindings": ["MOVE_N", "MOVE_S", "MOVE_E", "MOVE_W", "WAIT"]},
        }

    def open_transport(self, target: str, schema: Dict[str, Any]) -> GameTransport:
        raise NotImplementedError(
            "Vision transport needs the screen-capture + input-injection loop "
            "(dxcam/mss + pydirectinput) and a VLM HUD-labeler. Planned milestone; "
            "use a code/memory/SDK connector or the mock transport for now."
        )
