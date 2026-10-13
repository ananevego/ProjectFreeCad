# Минимальный конвертер УГО KiCad → Схематор

Состояние на 2026-10-13: отдельный writer создаёт один компонент в `.cds`
1.429. Профиль native records `schemator-cds-straight-v1` проверен по исходникам Схематора,
неизменённой записи R3 из существующей схемы и отдельному reader результата.
Импорт, соединение проводов и load/save в Windows-программе ещё не проверены.
Полный контракт `.cds` и блок УГО в плане остаются незавершёнными.

## Запуск

Из корня проекта, Python 3.10+, без внешних зависимостей:

```sh
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/R_control.cds --symbol R
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/C_control.cds --symbol C
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/CONN_01X06_control.cds --symbol CONN_01X06
```

Вход — UTF-8 `.lib`/`.kicad_sym`; выход — CP1251, CRLF, обязательно расширение
`.cds` в нижнем регистре: native library scanner проверяет его буквально.
По умолчанию создаётся соседний `.report.json` в UTF-8; `--report` меняет путь.
Исходный JSON inspection CLI `python3 -B -m src.symbol_converter` сохранён.

`--reference R1` явно задаёт обозначение; по умолчанию source prefix + `1`.
`--footprint-name R_0805_2012Metric` записывает точное native footprint name.
Это назначение имени, а не проверка pad mapping. Без параметра записывается
native placeholder `PART` с loss `SYMBOL_FOOTPRINT_UNRESOLVED`; исходный
KiCad identifier/filters остаётся в JSON.

`--default-line-width` (для нулевой source width) и `--pin-width` задают
толщины в mm, по умолчанию обе 0.254. Source pin stroke не разрешается через
проект KiCad; выбор толщины отмечается assumption.

`--curve-tolerance` задаёт mm-допуск centerline аппроксимации unfilled circles/
arcs, default 0.01; `0.00001 < value <= 1`. Legacy arc resolution и изменения
исходных radius/endpoints учитываются отдельно. Профиль и 7 новых controls:
[SYMBOL_CURVES.md](SYMBOL_CURVES.md).

| Код CLI | Значение |
|---|---|
| 0 | Созданы `.cds` и отчёт с перечисленными известными потерями |
| 1 | Ошибка исходника, неподдерживаемый объект, unsafe path или ошибка записи |
| 2 | `--strict`: записан отчёт отказа, целевой `.cds` не заменён |

Текущий профиль всегда имеет font/layout losses, поэтому strict отклоняет все
три контрольных УГО. Неподдерживаемые конструкции вызывают отказ до записи,
не превращаются в незаметно урезанный рисунок. Исходники, их hard links,
каталоги STL/STEP и совпадающие `.cds`/report paths защищены.
Два выхода записываются атомарно по отдельности: при ошибке записи JSON уже
записанный `.cds` может остаться. `artifact_sha256` позволяет сверить пару.

Python API: `src.symbol_converter.target.convert_symbol(library, name, ...)`
возвращает `cds`, `report` и typed `document`; сам API не записывает файлы.

## Поддержанный профиль

- Один unit, standard body style, common sections; разрешённое source
  inheritance/alias обрабатывает существующий parser.
- Видимые pins девяти обычных electrical types с прямым segment, положительной длиной,
  cardinal angles 0/90/180/270 и без alternates. Hidden pin numbers разрешены:
  номер остаётся электрическим атрибутом с нулевым размером текста.
- Уникальные номера вида `1`, `64`, `A1`: ASCII prefix и положительный suffix
  без ведущих нулей, suffix ≤ 2 147 483 647 (native signed-int `atoi`).
  Ranges, comma lists, apostrophes, совпадающие connection
  terminals и дубли внутри одного rendering отвергаются.
- Незаполненные rectangles/polylines, solid/default stroke, native straight
  segments. Полилиния с повторённой последней точкой становится `outline`.
- Незаполненные circles и modern/legacy arcs: straight approximation с явным
  centerline bound после NM rounding, до 4096 corners/curve и 32768 body corners.
- Filled rectangles/closed simple polygons/circles: boundary + overlapping
  strokes с default fill tolerance 0.01 mm. Background — boundary only с loss.
- Literal modern graphic text/legacy T: body description на существующем
  contour, quarter-turn/hidden state, явные font/layout/z-order losses.
  Команды, markup и нехватка carriers вызывают отказ.
- Reference/value: source anchors, hidden state, quarter-turn angle и height.
  Exact font, justification, baseline и glyph bounds не воспроизводятся.
- CP1251 text без quotes, control characters, крайних пробелов и markup `~`/`^`.
  `@` в value/package зарезервирован native component index. Поддержка encoding
  не доказывает наличие всех glyphs в выбранном native font.

Multi-unit/power/virtual/BOM-excluded symbols, power_in/power_out/no_connect/hidden/styled pins,
alternate body styles, filled arcs/Bezier/open filled polygons, цветные/dashed
strokes, source diagnostics и будущие неизвестные records пока отклоняются.
PIC24 из cache отклоняется из-за duplicates; LM393 — из-за нескольких units.
Библиотека читается целиком, writer выбирает ровно один symbol; batch УГО пока нет.

## Подтверждённые native записи

Исходники закреплены на `niconson/Schematic-Constructor`, revision
`e7443c374f5c8644fb3483f794a50161de60dd01`. Ссылки и hashes:
[SCHEMATOR_FORMAT_RESEARCH.md](SCHEMATOR_FORMAT_RESEARCH.md) и
`output/symbols/schemator-source-evidence.json`.

| Запись | Назначение в этом профиле |
|---|---|
| `[options]`, `[graphics]`, `[end]` | Header/version 1.429 и graphics section |
| `n_pins`, `rectangle` | Число электрических pin records и bounds геометрии |
| `ref_des`, `part_value`, `footprint_name` | Строка и 10 native text attributes; слои 7/13/12 |
| `outline` / `polyline` | Число corners, hatch, layer, width, merge/submerge/source/invert |
| `corner` | Индекс, x/y, side style, contour index (closed) или Node flag (open) |
| `pin_name` | **Физический номер**, слой 9, принадлежит предыдущему pin segment |
| `description` | Имя/функция pin, слой 14; не заменяет физический номер |
| `part_end` | Завершает component, используется reader при group insertion |

Geometry — signed native NM, 1 mm = 1 000 000 NM; header `units: MM` задаёт
UI units. KiCad symbol coordinates сохраняются с Y вверх. Native text rotation
применяется с обратным знаком, поэтому text angle = `-source_angle mod 360`.
Body layer 6, pin segment layer 8; его первая точка — body, последняя — source
external endpoint с `Node=1`. Native connection code проверяет этот флаг;
без него рисунок pin не был бы подтверждённым электрическим концом.

Bounds включают geometry и margin `max_width/2 + 25400 NM`, как в реальном R3.
Merges/submerges/pictures отключены (`-1/-1/-1/0`), hatch=0, side style=0;
native font SIMPLEX=2, text options PDF_DEF=1. Default/reference properties
и pin labels имеют явные layout losses; metadata/electrical type сохраняются
в JSON. Writer не передаёт KiCad ERC rules. Профиль типов, per-pin semantic
mapping и пять реальных controls: [SYMBOL_ELECTRICAL.md](SYMBOL_ELECTRICAL.md).

## Проверки и результаты

`tests/fixtures/schemator/Detector_R3.component.txt` — точные bytes строк
507–528 локального `FreePCB/detector/detector.cds`; происхождение и hashes
сохранены в `provenance.json`. Это фрагмент для теста, не импортируемый файл.
Reader принимает исходную запись R3, проверяет её два номера/free endpoints,
hidden pin labels, layers и semantic write/read roundtrip.

| Сохранённый результат | Pins | Polylines | Losses / assumptions |
|---|---:|---:|---:|
| `output/symbols/R_control.cds` | 2 | 3 | 4 / 1 |
| `output/symbols/C_control.cds` | 2 | 4 | 4 / 1 |
| `output/symbols/CONN_01X06_control.cds` | 6 | 13 | 5 / 8 |

31 новый тест: реальные records, literal coordinate probes, все cardinal
направления, номера/имена/Nodes, settings, losses/strict, malformed native
records, целевая сетка/overflow, защита файлов и воспроизводимость CLI.
После writer было 193, component stage — 235, curves stage — 266;
electrical stage добавил 19 (285); body stage — 27, всего 312 тестов.
Копия без STL/STEP проходит с 3 optional integration
skips моделей. Контрольные `.cds` воспроизводятся побайтно.

Отчёт явно разделяет `contract_verified_against_source=true`,
`target_records_validated=true`, `target_output_generated=true` и
`target_import_verified=false`, `gui_validated=false`,
`physical_pin_mapping_verified=false`. В strict rejection
`target_output_generated=false`, hash предложения назван
`proposed_artifact_sha256`. Результаты не являются проверкой installed binary.

2026-10-13: component manifest и проверка symbol → footprint → существующий
STL реализованы для R/C/Header6; [COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md).
Standalone writer по-прежнему не проверяет pads. Linked exporter отдельно
подтверждает number identity по source/CDS/FPL и меняет scoped mapping flag
в своих reports. 2026-10-13 добавлены unfilled curves и реальная выборка;
обычные electrical types — с явной потерей ERC. Simple fills и body text
реализованы: [SYMBOL_BODY.md](SYMBOL_BODY.md), `--fill-tolerance` default .01.
Далее units/merge и отдельная power/no-connect политика. В Windows нужны import,
визуальное сравнение, подключение проводов, netlist и load/save roundtrip.
