# Электрические типы выводов УГО

Состояние на 2026-10-13: `visible-line-electrical-v1` расширяет source profile
writer, сохраняя прежний native `schemator-cds-straight-v1`. Обычные видимые
прямые выводы передаются как номер, segment и external Node=1; исходный
электрический тип остаётся в JSON с явным loss. ERC-правила KiCad в `.cds`
не передаются. Импорт, соединение проводов и netlist в Схематоре не проверены.

## Разрешённые типы и ограничения

| Source electrical type | Legacy code | Native результат |
|---|---|---|
| passive | P | Нумерованный endpoint, как прежде |
| input | I | Нумерованный endpoint; input/ERC semantics только в JSON |
| output | O | Нумерованный endpoint; output/drive rules только в JSON |
| bidirectional | B | Нумерованный endpoint; direction rules только в JSON |
| tri_state | T | Нумерованный endpoint; drive rules только в JSON |
| unspecified | U | Нумерованный endpoint; source classification в JSON |
| free | — | Нумерованный endpoint; source classification в JSON |
| open_collector | C | Нумерованный endpoint; drive rules только в JSON |
| open_emitter | E | Нумерованный endpoint; drive rules только в JSON |

`power_in`, `power_out`, `no_connect` пока вызывают явный отказ: требуется
отдельная политика power/no-connect. Hidden pins, alternates, clock/inverted
и другие graphic styles тоже отклоняются. Тип и graphic style проверяются
раздельно. Удалять неподдержанные выводы или превращать no-connect в обычную
точку подключения writer не будет.

Сохраняются прежние ограничения: один unit/standard body style, положительная
длина, cardinal directions, уникальные native identifiers и endpoints,
CP1251, явные font/layout losses. Simple fills/body text добавлены в отдельном
[body profile](SYMBOL_BODY.md). Hidden **имена/номера**
допустимы: physical number сохраняется с size=0, скрытое имя не рисуется,
но остаётся в source metadata. Hidden pin целиком остаётся отказом.

## Подтверждение native контракта

Закреплённая ревизия Схематора — `e7443c374f5c8644fb3483f794a50161de60dd01`.
[Documents.cpp:1607–1688](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L1607)
записывает полилинию, corners/Node, `pin_name` и `description`.
[ReadGraphics:2217–2313](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2217)
читает их как geometry и text attributes. В этом подтверждённом наборе
records нет поля электрического типа KiCad. `pin_name` — физический номер,
`description` — отображаемое имя, а не native ERC declaration.

[Connection code:7763–7838](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L7763)
использует Node flags. Флаг определяет endpoint, а не input/output direction.
В программе есть собственные проверки цепей; исследование этого record
profile не доказывает отсутствие любых электрических проверок во всей программе.
Legacy коды сверены с
[официальным KiCad9 reader:1236–1246](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_io/kicad_legacy/sch_io_kicad_legacy_lib_cache.cpp#L1236).
URL/bytes/SHA256/anchors сохранены в `output/symbols/electrical-source-evidence.json`.

## JSON и strict

Для УГО с хотя бы одним non-passive выводом отчёт дополнен:

- `target.source_pin_profile=visible-line-electrical-v1`;
- `pin_semantics.electrical_rules_transferred=false`;
- `pin_semantics.pins`: source number/name/type, target number, индекс
  polyline и координаты external endpoint в NM для **каждого** вывода;
- `SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED`, severity `loss`, с числом
  выводов каждого исходного типа в context.

Полный `source_symbol` содержит typed/raw свойства без изменений. Имена
выводов не дополняются type annotations, лишние native поля не изобретаются.
Pure-passive отчёты и CDS сохраняют прежние bytes/structure; расширенные
поля появляются только при новых типах. Curves и electrical profiles независимы.

`--strict` возвращает 2 и rejection report с source semantics/proposed hash,
сохраняя прежний CDS. Неподдержанный тип возвращает 1 до записи CDS/JSON.
В bundle strict отказ изолирован по компоненту; native outputs и model copies
для отклонённого компонента не публикуются.

`physical_pin_mapping_verified=true` в linked report подтверждает только
source/CDS/FPL number identity. `electrical_rules_transferred` остаётся false;
номер корпуса, функция вывода, ERC и проверенный native netlist не эквивалентны.

## Реальная выборка и переносимый комплект

Пять controls из целой неизменённой Device KiCad symbols 9.0.0:

| Symbol / output stem | Pins | Source types | Body |
|---|---:|---|---|
| Antenna / Antenna_electrical | 1 | input | Polylines |
| Antenna_Chip / Antenna_Chip_electrical | 2 | input, passive | Polylines |
| DelayLine / DelayLine_electrical | 3 | input, passive, passive | 8 arcs |
| Q_SCR_AGK / Q_SCR_AGK_electrical | 3 | input, passive, passive | Polylines |
| Speaker / Speaker_electrical | 2 | input, input | Rectangle/polyline |

Все source pin names здесь скрыты; они сохранены в JSON. Реальная выборка
подтверждает input/mixed profiles, остальные обычные типы — synthetic modern/
legacy probes. Это не заявка на поддержку всех IC: многие требуют power pins,
filled body, styled pins или нескольких units.

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/Q_SCR_AGK_electrical.cds --symbol Q_SCR_AGK
python3 -B -m src.component_converter tests/fixtures/components/electrical.json \
  output/components/electrical
python3 -B -m src.component_converter --verify output/components/electrical
```

Bundle output должен быть новым каталогом. Config вручную задаёт SCR_AGK →
Package_TO_SOT_SMD:SOT-23 и Speaker → Buzzer_Beeper:Speaker_CUI_CMR-1206S-67.
Для SCR это тестовая библиотечная привязка generic symbol: пригодность корпуса
конкретному тиристору и функция площадок не подтверждены.

Созданы две complete chains: numbers 1/2/3 и 1/2, два existing STL,
263 268 source bytes, 12 package files с manifest. SOT-23 fixture переиспользован
без изменений; новый Speaker footprint целиком сохранён из KiCad pinned
51f8a59..., provenance — `tests/fixtures/components/electrical-provenance.json`,
лицензия — `tests/fixtures/LICENSE.md`. Модели только скопированы и хешированы.
Summary — `output/symbol-electrical.summary.json`; runtime игнорируется Git.

Добавлено 19 проверок; всего **285 тестов**, все проходят. Проверены modern и
legacy codes, literal Nodes/numbers/names, source immutability, loss counts,
strict/unsupported output preservation, hidden labels, curves/record indices,
real controls, linked verification scope и relocation. Копия без STL/STEP
проходит тот же набор с тремя optional integration skips. Прежние linear/
curve CDS/reports и оба старых комплекта воспроизводятся без изменений.

2026-10-13: simple fills/body text добавлены; [SYMBOL_BODY.md](SYMBOL_BODY.md).
Далее multi-unit/merge. Power/no-connect, hidden/alternate pins и native GUI
остаются отдельными незавершёнными задачами.
