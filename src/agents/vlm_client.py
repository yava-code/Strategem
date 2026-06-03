from __future__ import annotations

import base64
import io
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from src.agents.scout_client import VLMObservation, VLMDelta

# ---------------------------------------------------------------------------
# Screenshot backends — dxcam preferred (Windows, lowest latency)
# ---------------------------------------------------------------------------
try:
    import dxcam
    _DXCAM_OK = True
except ImportError:
    _DXCAM_OK = False

try:
    from PIL import ImageGrab, Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    from groq import AsyncGroq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False


@dataclass
class ScreenCapture:
    png_bytes: bytes
    width: int
    height: int
    timestamp: float = field(default_factory=time.time)

    def to_base64(self) -> str:
        return base64.b64encode(self.png_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# Screenshotter
# ---------------------------------------------------------------------------

class Screenshotter:
    """
    Captures the game window.
    Uses dxcam for <1 ms latency on Windows; falls back to PIL ImageGrab.
    """

    def __init__(self, window_title: Optional[str] = None):
        self._window_title = window_title
        self._dxcam_cam = None
        self._region: Optional[tuple[int, int, int, int]] = None  # (l, t, r, b)

        if _DXCAM_OK:
            self._dxcam_cam = dxcam.create()

    def _resolve_region(self) -> Optional[tuple[int, int, int, int]]:
        """Find game window bounding box by title (Windows only)."""
        if not self._window_title:
            return None
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, self._window_title)
            if not hwnd:
                return None
            rect = win32gui.GetWindowRect(hwnd)
            return rect  # (left, top, right, bottom)
        except ImportError:
            return None

    def capture(self) -> ScreenCapture:
        region = self._region or self._resolve_region()
        if region:
            self._region = region  # cache after first resolve

        if _DXCAM_OK and self._dxcam_cam is not None:
            frame = self._dxcam_cam.grab(region=region)
            if frame is not None:
                from PIL import Image as _Image
                img = _Image.fromarray(frame)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return ScreenCapture(
                    png_bytes=buf.getvalue(),
                    width=img.width,
                    height=img.height,
                )

        if _PIL_OK:
            img = ImageGrab.grab(bbox=region)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return ScreenCapture(
                png_bytes=buf.getvalue(),
                width=img.width,
                height=img.height,
            )

        raise RuntimeError("No screenshot backend available. Install dxcam or Pillow.")

    def save_debug(self, path: str = "debug_capture.png") -> None:
        cap = self.capture()
        with open(path, "wb") as f:
            f.write(cap.png_bytes)
        print(f"[VLM] Debug screenshot saved → {path}")


# ---------------------------------------------------------------------------
# VLMClient
# ---------------------------------------------------------------------------

_DELTA_PROMPT = """You are a Game State Observer. Compare the two game screenshots (baseline and current).
Identify all numeric state values that changed (HP, mana, stamina, coordinates, level, etc.).

For each changed value:
- field: short snake_case name (e.g. "hp", "position_x", "gold")
- old_value: numeric value from baseline screenshot (null if not visible)
- new_value: current numeric value
- confidence: 0.0-1.0 (how certain you are about these values)
- ui_region: where on screen (e.g. "top-left health bar", "minimap")

Respond ONLY as JSON matching the VLMObservation schema:
{"deltas": [...], "raw_description": "..."}"""


class VLMClient:
    """
    Captures two screenshots around a state change and asks a vision LLM
    to identify which game state values changed and by how much.

    Phase 1 uses Groq's vision-capable models.
    Falls back to a pure-text diff heuristic if no vision model is available.
    """

    def __init__(
        self,
        window_title: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._shooter = Screenshotter(window_title=window_title)
        self._model = model or os.environ.get("GROQ_VLM_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        self._client: Optional[AsyncGroq] = None

        if _GROQ_OK:
            api_key = os.environ.get("GROQ_API_KEY")
            if api_key:
                self._client = AsyncGroq(api_key=api_key)

    def capture_baseline(self) -> ScreenCapture:
        return self._shooter.capture()

    async def observe_delta(
        self,
        baseline: ScreenCapture,
        current: Optional[ScreenCapture] = None,
    ) -> VLMObservation:
        """
        Compares baseline to current screenshot and returns observed state deltas.
        If current is None, captures a fresh screenshot now.
        """
        if current is None:
            current = self._shooter.capture()

        if self._client is None:
            # No VLM available — return empty observation (manual fallback)
            print("[VLM] Warning: no Groq client available, returning empty observation")
            return VLMObservation(deltas=[], raw_description="vlm_unavailable")

        b64_before = baseline.to_base64()
        b64_after = current.to_base64()

        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _DELTA_PROMPT},
                        {"type": "text", "text": "BASELINE screenshot:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_before}"}},
                        {"type": "text", "text": "CURRENT screenshot:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_after}"}},
                    ],
                }
            ],
        )
        raw = response.choices[0].message.content or '{"deltas":[]}'
        return VLMObservation.model_validate_json(raw)

    def save_debug(self, path: str = "debug_capture.png") -> None:
        self._shooter.save_debug(path)
