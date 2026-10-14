# Power pins и явная политика no-connect

Состояние на 2026-10-14: `visible-line-power-v1` разрешает видимые прямые
`power_in`/`power_out` у физических компонентов. Номер и точка подключения
сохраняются; power/ERC rules остаются в JSON с явной потерей. `no_connect`
по умолчанию вызывает отказ. Явный `connectable-with-loss` сохраняет номер NC
как **обычный подключаемый вывод** и отмечает потерю запрета подключения.
Native records по-прежнему относятся к `schemator-cds-straight-v1`.

## Что подтвердили исходники Схематора

Закреплённая ревизия — `e7443c374f5c8644fb3483f794a50161de60dd01`:

- [ReadGraphics:2148](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2148)
  читает Node flags и pin number/name attributes. В используемом subset
  нет поля для KiCad electrical type, power role или запрета NC.
- [FindNodeLine:7894](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L7894)
  определяет соединения по геометрии electrical layers.
  [8032–8044](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L8032)
  восстанавливает Node=1 у совпавших концов, ранее имевших Node=0.
- [Group paste:10873](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/FreePcbView.cpp#L10873)
  при вставке из файла переводит любую polyline с pin attribute на
  `LAY_PIN_LINE`. Выбор другого слоя не обеспечивает постоянный запрет NC.
- [GetNumPins/GetNumAllPins:12200](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L12200)
  считает attached pin attributes. Удаление NC-номера нарушило бы физическую
  pin/pad identity корпуса.

Вывод из этого кода: Node=0 и декоративный слой нельзя использовать как
подтверждённую реализацию no-connect. Writer сохраняет прежние terminals:
layer 8, body Node=0, external Node=1, number на layer 9, optional name на 14.
Схематор имеет собственные проверки цепей; перенос KiCad ERC этим профилем
не подтверждён. Это исследование исходников, а не тест установленной программы.
URL/bytes/SHA256/anchors сохранены в `output/symbols/power-source-evidence.json`.

## Политика, отчёт и ограничения

| Source type | Legacy code | Поведение |
|---|---|---|
| power_in | W | Обычный нумерованный terminal; power role только в JSON |
| power_out | w | Обычный нумерованный terminal; power role только в JSON |
| no_connect | N | Default `reject`; explicit `connectable-with-loss` создаёт подключаемый terminal |

API: `convert_symbol(..., no_connect_policy='reject')`. CLI:
`--no-connect-policy reject|connectable-with-loss`. Bundle config:
`symbol_no_connect_policy`, default `reject`; значение проверяется до публикации
даже для партии без NC. Явный lossy режим действует на всю конфигурацию.

`pin_semantics` сохраняет номер, имя, source type, global native record index,
точку подключения, `target_node_flags=[0,1]`, `native_connectable=true`.
Power pins имеют `native_power_role_transferred=false`; NC —
`native_no_connect_enforced=false`. Aggregate flags также false.
`counts.power_pins/no_connect_pins` считают исходные физические terminals.
`SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED` содержит все source type counts;
каждый NC дополнительно имеет loss `SYMBOL_NO_CONNECT_AS_TERMINAL` с номером
и native index. В multi-unit отчёте сохраняется `rendered_unit` и rebased index.

Power-only sections допустимы при disjoint physical numbers и остальных
условиях [unit profile](SYMBOL_UNITS.md). Global power symbols, virtual/
BOM-excluded components и repeated/alternate pins отклоняются. Original
common pins требуют [common-view policy](SYMBOL_COMMON.md), hidden pins —
[explicit reveal](SYMBOL_PINS.md). Styled markers добавлены в editor profile;
styled NC и implicit global nets остаются отказом/потерей. Неподдержанный текст/graphic style не удаляется для
обхода отказа. Source definitions/typed/raw records остаются неизменными.

`strict` отклоняет power/ERC и NC losses, не создаёт новые CDS/FPL и сохраняет
предыдущий CDS; rejection report сохраняет policy, source/layout и proposed hash.
Прежние ordinary/passive-only reports и records не меняются; неиспользуемая
NC policy не добавляет новые поля в старые standalone reports.
Подтверждённая number identity в bundle не повышает ERC/NC/GUI flags.

## Реальные controls и комплект

Шесть `output/symbols/*_power.cds`/reports используют целые unchanged symbols:

| Control | Source | Units | Pins | Power | NC |
|---|---|---:|---:|---:|---:|
| Fuse_Polarized | Device KiCad 9.0.0 | 1 | 2 | 2 | 0 |
| Opamp_Dual | Device KiCad 9.0.0 | 3 | 8 | 2 | 0 |
| LM393 | Comparator KiCad 9.0.0, inherited LM2903 | 3 | 8 | 2 | 0 |
| LM311 | Comparator KiCad 9.0.0 | 1 | 8 | 2 | 0 |
| MCP1525 | Local Pickit-cache.lib | 1 | 3 | 3 | 0 |
| MCP601_8PIN | Local Pickit-cache.lib | 1 | 8 | 2 | 3 |

Последний control использует explicit lossy policy: NC 1/5/8 сохраняются
подключаемыми. Global GND, hidden pins и LTC4411 с unsupported markup
остаются вне профиля. Эти controls не измеряют coverage всей библиотеки.

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Comparator.kicad_sym \
  output/symbols/LM393_power.cds --symbol LM393
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/MCP601_8PIN_power.cds --symbol MCP601_8PIN \
  --no-connect-policy connectable-with-loss
python3 -B -m src.component_converter tests/fixtures/components/power.json \
  output/components/power
python3 -B -m src.component_converter --verify output/components/power
```

Bundle output должен быть новым каталогом. Партия содержит LM393→DIP-8,
MCP1525→SOT-23, MCP601_8PIN→DIP-8: 3 complete file chains, 2 existing STL,
287168 source bytes, 15 package files с manifest. Два DIP-компонента делят
один asset. Source/CDS/FPL numbers проверены: 1–8, 1–3, 1–8, включая NC.
Bindings заданы вручную для проверки библиотечных связей; pin functions,
пригодность конкретного корпуса и physical 3D alignment не подтверждены.
Новый DIP footprint сохранён целиком из pinned KiCad `51f8a59...`; provenance
в `tests/fixtures/components/power-provenance.json`, license в `LICENSE.md`.
STL только копируются/хешируются, без mesh parsing и повторной конвертации.

Summary — `output/symbol-power.summary.json`; runtime bundle игнорируется Git.
Повторная сборка и relocation проверены. 23 новых теста; всего **359**,
копия без STL/STEP проходит с 3 optional integration skips. Старые controls
и пять прежних bundles воспроизводятся без изменений.

Styled/hidden и original common-pin policies уже добавлены:
[SYMBOL_PINS.md](SYMBOL_PINS.md), [SYMBOL_COMMON.md](SYMBOL_COMMON.md).
Далее: footprint coverage, hierarchy/alternate modes,
native GUI/3D validation и масштабирование. Инженерная оценка остатка —
**15–25%, четыре незавершённых блока**; точная native NC enforcement пока
не реализована и учитывается в ограничениях.

Актуальные extensions: [SYMBOL_PINS.md](SYMBOL_PINS.md),
[SYMBOL_COMMON.md](SYMBOL_COMMON.md); всего 398 тестов.
