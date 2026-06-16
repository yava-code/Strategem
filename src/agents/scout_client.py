from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, field_validator

try:
    from groq import AsyncGroq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False

T = TypeVar("T", bound=BaseModel)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_BASE_SYSTEM = (_PROMPT_DIR / "scout_base.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Scout response schemas
# ---------------------------------------------------------------------------

class MemoryScanOutput(BaseModel):
    field: str
    scan_round: int
    candidate_count: int
    top_addresses: list[str]     # up to 5 most likely candidates
    scan_type: str               # "float" | "dword" | "string"
    notes: Optional[str] = None


class PointerChainOutput(BaseModel):
    field: str
    base: str                    # "Module.dll+0xOFFSET"
    offsets: list[int]
    verified: bool
    final_value: Optional[str] = None
    notes: Optional[str] = None


class StructAnalysisOutput(BaseModel):
    class_name: Optional[str] = None
    known_field_offset: int = 0       # offset of the field we started from
    adjacent_fields: list[dict] = []  # [{offset, guessed_type, candidate_name}]
    fields: list[dict] = []           # fallback key some LLMs emit
    notes: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if self.fields and not self.adjacent_fields:
            self.adjacent_fields = self.fields


class StaticAnalysisOutput(BaseModel):
    field: str
    static_offset: str           # hex string
    write_functions: list[str]   # addresses of functions that write to this field
    struct_fields: list[dict]    # [{name, offset, type, semantic_role}] from decompile
    class_name: Optional[str] = None
    notes: Optional[str] = None


class ActionManifestOutput(BaseModel):
    actions: list[dict]          # [{id, name, key_binding, entry_point_addr}]
    input_handler_addr: Optional[str] = None
    notes: Optional[str] = None


class VLMDelta(BaseModel):
    field: str                   # "hp", "position_x", etc.
    old_value: Optional[float]
    new_value: float
    confidence: float            # 0.0–1.0
    ui_region: Optional[str] = None  # "top-left", "health bar", etc.


class VLMObservation(BaseModel):
    deltas: list[VLMDelta]
    raw_description: Optional[str] = None


class SynthesisJudgment(BaseModel):
    """General LLM output when synthesizing Scout results into state_map fields."""
    accepted_fields: list[dict] = []
    rejected_fields: list[str] = []
    action_bindings: list[str] = []
    fields: list[dict] = []           # fallback: some LLMs emit this instead of accepted_fields
    notes: Optional[str] = None

    @field_validator("fields", "accepted_fields", mode="before")
    @classmethod
    def _coerce_to_list(cls, v: Any) -> list:
        if isinstance(v, dict):
            return list(v.values()) if v else []
        return v or []

    def model_post_init(self, __context: Any) -> None:
        if self.fields and not self.accepted_fields:
            self.accepted_fields = self.fields


# ---------------------------------------------------------------------------
# GroqScout
# ---------------------------------------------------------------------------

class GroqScout:
    """
    Lightweight async Groq client for Scout agents.
    All responses are JSON parsed into a Pydantic model.

    Each Scout gets its own instance with a task-specific system prompt appended
    to the shared base prompt.
    """

    def __init__(
        self,
        task_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ):
        if not _GROQ_OK:
            raise ImportError("groq package not installed. Run: pip install groq>=0.9.0")
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not set in environment")
        self._client = AsyncGroq(api_key=api_key)
        self._model = model or os.environ.get("GROQ_MODEL", "moonshotai/kimi-k2-instruct")
        self._temperature = temperature
        self._system = f"{_BASE_SYSTEM}\n\nYOUR SPECIFIC TASK:\n{task_prompt}"

    async def ask(self, user_content: str, schema: Type[T]) -> T:
        """Send a message and parse the JSON response into the given Pydantic model."""
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        return schema.model_validate_json(raw)

    async def ask_raw(self, user_content: str) -> dict:
        """Same as ask() but returns a plain dict (for unstructured synthesis tasks)."""
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)


# ---------------------------------------------------------------------------
# Preconfigured Scout factories
# ---------------------------------------------------------------------------

def memory_scout() -> GroqScout:
    return GroqScout(
        task_prompt=(
            "You receive a list of CE scan results (addresses and values) plus the "
            "observed state delta. Select the most likely true candidate addresses "
            "for the field. Output as MemoryScanOutput schema."
        )
    )

def pointer_scout() -> GroqScout:
    return GroqScout(
        task_prompt=(
            "You receive pointer scan results for a field across multiple game restarts. "
            "Choose the most stable chain (fewest offsets, consistent base module). "
            "Output as PointerChainOutput schema."
        )
    )

def struct_scout() -> GroqScout:
    return GroqScout(
        task_prompt=(
            "You receive CE struct dissection output: raw field bytes around a known address. "
            "Given the known offset of one field, identify adjacent fields by type and offset patterns. "
            "Output as StructAnalysisOutput schema."
        )
    )

def static_scout() -> GroqScout:
    return GroqScout(
        task_prompt=(
            "You receive Ghidra decompiled pseudocode for a function that writes to a known struct field. "
            "Extract ALL struct fields accessed via the same base pointer. "
            "Assign semantic roles: health, coordinate_x, coordinate_y, coordinate_z, depth, time, threat, scalar. "
            "Output as StaticAnalysisOutput schema."
        )
    )

def action_scout() -> GroqScout:
    return GroqScout(
        task_prompt=(
            "You receive a Ghidra call graph summary and AOB scan results for the input handler. "
            "Identify discrete player actions (move directions, abilities, menu interactions). "
            "Map them to key bindings where possible. "
            "Output as ActionManifestOutput schema."
        )
    )

def general_synthesizer(model: Optional[str] = None) -> GroqScout:
    """The General — uses a larger/smarter model for synthesis."""
    return GroqScout(
        task_prompt=(
            "You are the General LLM. You receive compiled Scout findings: struct fields, "
            "pointer chains, action manifest. Resolve conflicts, assign final semantic roles, "
            "determine normalization bounds. "
            "Output as SynthesisJudgment schema."
        ),
        model=model or os.environ.get("GROQ_GENERAL_MODEL", "moonshotai/kimi-k2-instruct"),
        temperature=0.0,
    )
