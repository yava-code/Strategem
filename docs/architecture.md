# Architecture

Bridge-Maker is split into layers so game-specific semantics do not leak into
the training or reporting core.

## Layers

1. **Contract layer** - decorators, adapter functions, registry, trace logger.
2. **Compilation layer** - registry and traces become `state_map.json`,
   `action_map.json`, and `oracle_map.json`.
3. **Runtime layer** - SDK Gym env or generated env.
4. **Training layer** - Ray/RLlib + curiosity, optional and not required for the
   current proof demo.
5. **Reporting layer** - static JSON/HTML reports and dashboard telemetry.
6. **Assist layer** - CE/Ghidra/VLM tools for advanced grey-box workflows.

## Active product path

```text
Developer annotations or adapter
  -> Bridge-Maker registry
  -> Contract export
  -> Trace generation
  -> Gym wrapper
  -> Bug report
```

## Why not pure black-box

The earlier CE/Ghidra-first plan proved that binary-level discovery is fragile:
permissions, ASLR, stale pointers, GUI setup and action discovery are not a good
default onboarding experience for indie developers.

The new product makes the semantic contract explicit. Agents can still help, but
they amplify a contract instead of inventing one silently.

## Agent roles

- `CodeScout`: scans code/adapters for decorated functions and likely missing annotations.
- `TraceScout`: validates that fields change and actions produce useful traces.
- `SchemaScout`: compiles registry + trace evidence into contract maps.
- `ActionModelScout`: learns rough preconditions/effects from traces.
- `GreyBoxScout`: optional CE/Ghidra/VLM helper.
- `General`: synthesizes report narratives, test goals and missing-contract advice.

