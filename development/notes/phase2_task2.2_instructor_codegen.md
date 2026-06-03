# Task 2.2 — Structured LLM Code Generation

**File:** `src/agent_generator.py` → `InstructorCodeSynthesizer`

- `instructor.from_gemini` / `instructor.from_openai` patched clients request a
  `GymEnvCodeSpec` as `response_model` (structured, not free text).
- Backend chosen by env key (`GEMINI_API_KEY` → Gemini, else `OPENAI_API_KEY`).
- Graceful, layered fallback to the deterministic `build_spec_from_state_map`
  when `instructor`, the API key, or the call itself is unavailable.
- Enabled via `--use-llm`; default path stays fully offline.

**Verified:** offline run reports "instructor not installed; using deterministic
spec builder" and still compiles a valid env.
