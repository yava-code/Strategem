# Bridge-Maker - українська презентація

## Слайд 1 - Назва

**Bridge-Maker**  
Contract-first automated Game QA for indie teams.

Кілька decorators у коді гри - і на виході semantic contract, Gym environment,
trace evidence та bug report.

## Слайд 2 - Проблема

Інді-команди не мають часу будувати повну QA automation stack:

- manual regression testing повільний;
- RL потребує Gym environment;
- PDDL занадто складний;
- reverse engineering кожного `.exe` занадто крихкий;
- black-box bots часто просто тиснуть кнопки без розуміння гри.

## Слайд 3 - Інсайт

Повна магія не потрібна. Розробник вже знає семантику гри:

- де HP;
- де позиція;
- які дії легальні;
- які стани є багами;
- як reset-нути епізод.

Bridge-Maker робить цю семантику маленьким контрактом.

## Слайд 4 - Рішення

```python
from bridge_maker import bm

@bm.hp(bounds=(0, 100))
def hp(): return player.hp

@bm.move("right", key="d")
def move_right(): player.move_right()

@bm.oracle("out_of_bounds")
def out_of_bounds(s): return s.x > level.width
```

Після цього:

```powershell
bridge-maker init --out bridge_maker_starter --game-name "My Game"
bridge-maker validate --adapter bridge_maker_starter\bridge_adapter.py
bridge-maker run --adapter bridge_maker_starter\bridge_adapter.py --out runs\my_game
```

## Слайд 5 - Pipeline

1. Developer annotates existing functions.
2. Bridge-Maker builds registry.
3. Contract exporter writes `state_map`, `action_map`, `oracle_map`.
4. Runtime records traces.
5. Reporter creates HTML/JSON bug evidence.
6. Training layer can consume the same contract later.

## Слайд 6 - Що вже працює

- Python decorator SDK.
- Install/diagnostic command: `bridge-maker doctor`.
- First-run scaffold: `bridge-maker init`.
- Adapter validation: `bridge-maker validate`.
- One-command QA run: `bridge-maker run`.
- Adapter loading.
- Contract export.
- SDK Gymnasium env.
- Annotation suggestions.
- JSON/HTML reports.
- Reproduction actions and failing state in reports.
- Reproducible trace strategies with seed control.
- CI/nightly mode with `--fail-on-bug`.
- GitHub Actions scaffold with `bridge-maker init-ci`.
- Buggy roguelike with intentional bug.
- Noita WebSocket adapter readiness note.
- Unit tests green.

## Слайд 7 - Demo

Показати:

1. `examples/buggy_roguelike.py`
2. `bridge-maker demo --out runs/grant_demo`
3. `runs/grant_demo/state_map.json`
4. `runs/grant_demo/trace.jsonl`
5. `runs/grant_demo/report.html`

Ключовий момент: звіт містить oracle hit, тобто це не випадкове натискання кнопок,
а bug evidence.

## Слайд 8 - Чому не PDDL

Research-підхід правильний у головному: потрібна семантика гри. Але PDDL UX
занадто дорогий для indie developer.

Bridge-Maker замінює PDDL на decorators і adapter functions.

## Слайд 9 - Чому не full black-box

Black-box automation крихка:

- HUD parsing помиляється;
- memory pointers ламаються;
- menus/focus/ASLR створюють шум;
- action discovery не має гарантій.

Bridge-Maker залишає CE/Ghidra/VLM як assist layer, але не робить це happy path.

## Слайд 10 - Бізнесова позиція

Цільовий користувач:

- indie developer;
- reverse-project maintainer;
- QA automation researcher.

Value:

- менше ручного regression testing;
- швидший bug discovery;
- shareable reports;
- reusable game contract.

## Слайд 11 - Roadmap

1. Harden SDK MVP.
2. Live Noita/NoitaRL adapter.
3. Agent-assisted annotation mining.
4. Contract-backed RL training.
5. Overnight command: report + replay + trainer artifacts.

## Слайд 12 - Ask

Ми вже маємо working proof loop. Наступний funding/dev milestone - перетворити
це на продуктову workflow:

**annotate once, run overnight, receive actionable QA evidence.**
