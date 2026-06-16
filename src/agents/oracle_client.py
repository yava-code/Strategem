"""
Phase 5 — VLM Oracle.

On freeze detection (env obs unchanged for FREEZE_STEPS consecutive steps),
takes a screenshot of the game window, asks a Groq vision model where to
click to resume gameplay, and fires pydirectinput.click() at those coordinates.

Reuses Screenshotter from src.agents.vlm_client (dxcam + PIL fallback).
Uses synchronous Groq() client because LiveEnv.step() is not async.
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional, Tuple

import pydirectinput

try:
    from groq import Groq as _Groq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False

from src.agents.vlm_client import Screenshotter

ORACLE_MODEL = os.environ.get(
    "ORACLE_MODEL",
    "meta-llama/llama-4-scout-17b-16e-instruct",
)

_ORACLE_PROMPT = (
    "The game appears frozen or stuck on a dialog / menu / loading screen. "
    "Analyze this screenshot and identify what needs to be clicked to resume gameplay. "
    "Respond ONLY with the pixel coordinates in exactly this format: x=NNN, y=NNN. "
    "If there is nothing obvious to click, respond with the single word: none"
)


class OracleClient:
    """
    Vision LLM oracle that unblocks a frozen game session.

    Usage (called from _PinnedLiveEnv.step):
        oracle = OracleClient(window_title="My Game")
        action_str = oracle.attempt_unfreeze()   # -> "Oracle #1: click (450,300) <- ..."
        if action_str:
            env._freeze_n = 0           # reset freeze counter
            terminated    = False       # continue episode
    """

    def __init__(
        self,
        window_title: Optional[str] = None,
        min_interval: float = 3.0,
        model: Optional[str] = None,
    ) -> None:
        self._screenshotter = Screenshotter(window_title=window_title or None)
        self._client        = _Groq() if _GROQ_OK else None   # reads GROQ_API_KEY env var
        self._model         = model or ORACLE_MODEL
        self._min_interval  = min_interval
        self._last_ts       = 0.0
        self._count         = 0

    def __reduce__(self):
        # When captured in algo.save() state, serialize as an unstarted instance.
        # Screenshotter (dxcam) and Groq client are not restored from checkpoint.
        return (OracleClient, (None, self._min_interval, self._model))

    @property
    def available(self) -> bool:
        return _GROQ_OK and self._client is not None

    def attempt_unfreeze(self) -> Optional[str]:
        """
        Screenshot -> Groq vision -> parse coords -> pydirectinput.click().

        Returns a human-readable action string, or None if:
          - Groq not available (no API key)
          - Rate-limited (called too soon after last click)
          - LLM returns 'none' (no click target visible)
          - Coordinate parsing fails
          - Any network / API error
        """
        if not self.available:
            return None
        now = time.monotonic()
        if now - self._last_ts < self._min_interval:
            return None

        try:
            cap  = self._screenshotter.capture()
            b64  = cap.to_base64()
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": _ORACLE_PROMPT},
                    ],
                }],
                max_tokens=64,
            )
            text = resp.choices[0].message.content.strip()
            if "none" in text.lower():
                return None
            coords = _parse_coords(text)
            if coords is None:
                print(f"[Oracle] Could not parse coords from: {text!r}", flush=True)
                return None
            x, y = coords
            pydirectinput.click(x, y)
            self._last_ts = time.monotonic()
            self._count  += 1
            msg = f"Oracle #{self._count}: click ({x},{y}) <- {text[:60]}"
            print(f"[Oracle] {msg}", flush=True)
            return msg
        except Exception as exc:
            print(f"[Oracle] Error during unfreeze attempt: {exc}", flush=True)
            return None


def _parse_coords(text: str) -> Optional[Tuple[int, int]]:
    """Extract first (x, y) integer pair from LLM response text."""
    # "x=450, y=300" or "x: 450, y: 300"
    m = re.search(r'x[=:\s]+(\d+)[,\s]+y[=:\s]+(\d+)', text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    # "(450, 300)" or "[450, 300]"
    m = re.search(r'[\(\[]\s*(\d+)\s*,\s*(\d+)\s*[\)\]]', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # bare "450, 300" (2-4 digit numbers)
    m = re.search(r'\b(\d{2,4})\s*,\s*(\d{2,4})\b', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None
