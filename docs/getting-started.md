# Швидкий старт Bridge-Maker

Bridge-Maker зараз презентується як contract-first SDK для автоматизованого Game QA.

## 1. Встановлення

```powershell
pip install -r requirements.txt
```

Для базового MVP не потрібні Cheat Engine, Ghidra, Ray, Wandb, Modal або Azure.

## 2. Перевірка CLI

```powershell
python -m bridge_maker --help
```

Команди:

- `suggest` - запропонувати decorators для Python-коду;
- `export` - експортувати контракт з adapter;
- `generate` - згенерувати SDK-backed Gym env;
- `report` - зібрати JSON/HTML звіт;
- `smoke` - зробити короткий env loop;
- `demo` - запустити повний proof demo.

## 3. Запуск demo

```powershell
python -m bridge_maker demo --out runs/grant_demo
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

## 4. Мінімальний adapter

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

## 5. Що відбувається далі

1. SDK збирає registry з decorators.
2. Runtime викликає state getters, actions і oracles.
3. Exporter пише контрактні JSON файли.
4. Env generator створює Gym-compatible wrapper.
5. Reporter збирає trace evidence у HTML/JSON звіт.

