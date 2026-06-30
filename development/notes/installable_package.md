# Installable SDK package

Date: 2026-06-17

Completed:

- Added `pyproject.toml`.
- Added console script:
  - `bridge-maker = "src.bridge_maker:main"`
- Kept core dependencies small:
  - `gymnasium`
  - `numpy`
  - `pydantic`
- Split advanced layers into optional extras:
  - `training`
  - `greybox`
  - `mlops`
  - `noita`
- Updated README and docs to prefer:
  - `pip install -e .`
  - `bridge-maker ...`

Verification:

- `python -m pip install -e . --no-deps`
- `bridge-maker --help`
- `bridge-maker init --out runs\\package_demo\\starter --game-name "Package Quest"`
- `bridge-maker smoke --adapter runs\\package_demo\\starter\\bridge_adapter.py --steps 6`
- `bridge-maker run --adapter runs\\package_demo\\starter\\bridge_adapter.py --out runs\\package_demo\\contract --game-name "Package Quest"`
- `python -m unittest discover -s tests` -> 7 tests OK.

Product impact:

The SDK now has a normal installable shape and a buyer-facing command name. The
base install no longer has to imply Ray, CE/Ghidra, cloud tooling, or reverse
engineering dependencies. Advanced capabilities remain available through extras.

