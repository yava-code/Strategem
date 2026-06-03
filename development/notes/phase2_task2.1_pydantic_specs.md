# Task 2.1 — Pydantic Code Specs

**File:** `src/codegen_schema.py`

- `ObservationChannelSpec` (index, var_name, role, `mapping_expr`),
  `ActionBindingSpec` (index, name, 2-vector), and `GymEnvCodeSpec` (class name,
  obs/action counts, channels, actions, box bounds, step speed).
- `GymEnvCodeSpec.validate_consistency()` enforces contiguous obs indices and
  count agreement before any render.

These models are the structured contract Instructor forces the LLM to fill,
keeping generated syntax stable.
