# Documentation site and Ukrainian pitch

Date: 2026-06-16

Completed:

- Verified current CLI: `python -m bridge_maker --help`.
- Verified tests: `python -m unittest discover -s tests` -> 4 tests OK.
- Rebuilt a documentation demo: `python -m bridge_maker demo --out runs/docs_demo`.
- Added static documentation site under `docs/`:
  - `index.html`
  - `styles.css`
  - `getting-started.md`
  - `sdk-reference.md`
  - `architecture.md`
  - `pitch_uk.md`
  - `status.md`
- Added Ukrainian presentation source:
  - `grant_materials/presentation_uk.md`

Positioning:

The active story is SDK/adapter-first. Bridge-Maker asks developers to expose a
minimal semantic contract through decorators or adapters, then automates contract
export, env generation, traces, and bug reports. CE/Ghidra/VLM remain optional
assist tooling and should not be presented as the default user onboarding path.

