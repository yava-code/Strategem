# Task 2.3 — Syntactic Verification

**File:** `src/agent_generator.py` → `GymEnvironmentCompiler.compile`

- The rendered module string is run through `ast.parse()` before it is allowed
  to touch disk; a `SyntaxError` is re-raised as a hard `RuntimeError`.
- Renderer now also wires `obs`/`next_obs` into the reward generator's
  `state_info`, so the auto-compiled env actually drives the ICM (parity with
  the hand-written env).

**Verified:** `python -m src.agent_generator` reports "AST-validated env (6 obs,
5 actions)"; generated env imports and trains under SB3.
