# Швидкий старт Bridge-Maker

Bridge-Maker зараз презентується як contract-first SDK для автоматизованого Game QA.

## 1. Встановлення

Для core SDK:

```powershell
pip install -e .
bridge-maker --help
bridge-maker doctor
```

Для базового MVP не потрібні Cheat Engine, Ghidra, Ray, Wandb, Modal або Azure.
Якщо потрібні продвинуті шари, вони встановлюються окремо:

```powershell
pip install -e ".[training]"
pip install -e ".[greybox]"
pip install -e ".[mlops]"
pip install -e ".[noita]"
```

## 2. Перевірка CLI

```powershell
bridge-maker --help
```

Команди:

- `suggest` - запропонувати decorators для Python-коду;
- `validate` - перевірити якість adapter-контракту;
- `run` - validate + export + generate + report в одну папку;
- `doctor` - перевірити встановлення SDK, core dependencies і optional extras;
- `export` - експортувати контракт з adapter;
- `generate` - згенерувати SDK-backed Gym env;
- `report` - зібрати JSON/HTML звіт;
- `smoke` - зробити короткий env loop;
- `demo` - запустити повний proof demo.

## 3. 15-minute start for your game

Створіть starter adapter:

```powershell
bridge-maker init --out bridge_maker_starter --game-name "My Game"
```

Перевірте, що adapter запускається:

```powershell
bridge-maker smoke --adapter bridge_maker_starter\bridge_adapter.py --steps 12
```

Перевірте якість контракту:

```powershell
bridge-maker validate --adapter bridge_maker_starter\bridge_adapter.py --out runs\my_game_validation
```

`validate` пояснює, чи вистачає state/actions/oracles для корисного QA-звіту,
і вказує, що треба додати перед довшими прогонами.

Запустіть повний basic QA pipeline:

```powershell
bridge-maker run --adapter bridge_maker_starter\bridge_adapter.py --out runs\my_game --game-name "My Game"
```

`run` збирає в одну папку:

- validation report;
- state/action/oracle maps;
- trace;
- generated SDK env;
- JSON/HTML bug report з reproduction actions, previous state і failing state для oracle findings.

Для довших відтворюваних прогонів:

```powershell
bridge-maker run --adapter bridge_maker_starter\bridge_adapter.py --out runs\my_game_random --trace-actions 200 --trace-strategy random --seed 42
```

Доступні стратегії trace:

- `burst` - поточний дефолт, кілька повторів кожної дії підряд;
- `cycle` - рівномірний перебір actions;
- `random` - псевдовипадковий порядок з фіксованим `--seed`.

Для CI/nightly прогонів:

```powershell
bridge-maker run --adapter bridge_maker_starter\bridge_adapter.py --out runs\nightly --trace-actions 500 --trace-strategy random --seed 42 --fail-on-bug
```

`--fail-on-bug` повертає exit code `2`, якщо report містить oracle hits, але все
одно записує `report.html`, `report.json` і `run_summary.json`.

Щоб створити GitHub Actions workflow:

```powershell
bridge-maker init-ci --adapter bridge_maker_starter\bridge_adapter.py
```

`bridge_adapter.py` одразу працює як маленький sandbox. Для реальної гри замініть
внутрішність bridge-класу на виклики вашого рушія, debug API, mod API або test harness.

## 4. Запуск bundled demo

```powershell
bridge-maker demo --out runs/grant_demo
```

Очікувані файли:

- `state_map.json`
- `action_map.json`
- `oracle_map.json`
- `trace.jsonl`
- `contract.json`
- `sdk_env_generated.py`
- `report.json`
- `report.html`

## 5. Мінімальний adapter

```python
from bridge_maker import bm

@bm.hp(bounds=(0, 100))
def hp():
    return player.hp

@bm.action("jump", key="space")
def jump():
    player.jump()

@bm.oracle("invalid_health")
def invalid_health(state):
    return state.hp < 0 or state.hp > 100
```

## 6. Що відбувається далі

1. SDK збирає registry з decorators.
2. Runtime викликає state getters, actions і oracles.
3. Exporter пише контрактні JSON файли.
4. Env generator створює Gym-compatible wrapper.
5. Reporter збирає trace evidence у HTML/JSON звіт.
