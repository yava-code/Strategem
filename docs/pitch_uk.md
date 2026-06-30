# Bridge-Maker: український pitch

## One-liner

Bridge-Maker допомагає indie-розробнику за кілька decorators перетворити гру на
автоматизований QA/RL тестовий стенд і отримати звіт з доказами багів.

## Проблема

Ігри складно тестувати автоматично:

- класичні unit tests не бачать геймплейних станів;
- RL-інструменти потребують Gym environment;
- PDDL/workflow з наукових робіт занадто складний для інді-команд;
- "повністю зрозуміти будь-який `.exe`" через reverse engineering занадто крихко.

## Рішення

Ми просимо розробника не писати формальні planning models, а просто позначити
існуючу семантику:

```python
@bm.hp(bounds=(0, 100))
def hp(): return player.hp

@bm.move("right", key="d")
def move_right(): player.move_right()

@bm.oracle("out_of_bounds")
def out_of_bounds(s): return s.x > level.width
```

Далі Bridge-Maker:

1. збирає semantic contract;
2. експортує state/action/oracle maps;
3. запускає smoke/RL loop;
4. записує trace;
5. формує bug report.

## Що вже готово

- Python decorator SDK.
- Install diagnostics: `bridge-maker doctor`.
- Adapter loader.
- Contract export.
- SDK Gymnasium environment.
- Annotation suggestion scanner.
- JSON/HTML bug reports.
- Reproduction actions, previous state і failing state у bug reports.
- Reproducible trace strategies: burst, cycle, random + seed.
- CI/nightly mode: `--fail-on-bug` plus `run_summary.json`.
- GitHub Actions scaffold: `bridge-maker init-ci`.
- Buggy roguelike demo з oracle finding.
- Noita WebSocket adapter readiness notes.
- Unit tests проходять.

## Чим це краще за PDDL

PDDL підходить для research, але погано підходить для indie UX. Bridge-Maker
залишає головну ідею research-напрямку - потрібна семантика гри - але робить її
локальною, зрозумілою і code-adjacent.

## Чим це краще за black-box bot

Black-box bot бачить пікселі і тисне кнопки. Bridge-Maker знає, що таке HP,
позиція, предмети, дії та інваріанти, тому може відрізняти "просто ходить" від
"знайшов bug evidence".

## Demo story

1. Відкрити `examples/buggy_roguelike.py`.
2. Показати 5-6 decorators.
3. Запустити:

```powershell
bridge-maker demo --out runs/grant_demo
```

4. Показати `state_map.json`.
5. Показати `trace.jsonl`.
6. Відкрити `report.html` з oracle hit `out_of_bounds`.

## Чесний статус

Це не фінальний продукт і не універсальний `.exe`-реверсер. Це вже працюючий
contract-first MVP, який доводить правильну архітектуру: мінімальна семантика
від розробника, автоматизація навколо неї.
