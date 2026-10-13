# Multi-unit УГО в одном физическом компоненте

Состояние на 2026-10-13: `disjoint-units-layout-v1` размещает 2–16 логических
секций KiCad рядом внутри **одного обычного native component** `.cds` 1.429.
Физические номера сохранены; независимое размещение секций, unit suffixes и
иерархический merge не передаются и имеют явный loss. Это ограниченный
compound layout, а не завершённая поддержка native multi-gate/hierarchy.
Импорт, подключение проводов, renumbering и netlist в GUI ещё не проверены.

## Native контракт и выбор профиля

В закреплённом Схематоре `e7443c374f5c8644fb3483f794a50161de60dd01`:

- [ReadGraphics:2171](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2171)
  присваивает одной цепочке polylines общие part/value/footprint attributes.
  [part_end:2325](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2325)
  завершает этот компонент. Его body может состоять из нескольких контуров.
- [GetNumAllPins:12217](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L12217)
  считает physical pin attributes по всей цепочке, независимо от разделения
  body. В результате один reference/footprint и все уникальные номера корпуса.
- [Merge filtering:2075](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2075)
  отбирает graphics по merge/submerge index при импорте. Сам индекс не
  подтверждает принадлежность нескольких KiCad units одному IC.
- [SelectBlock:15020](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/FreePcbView.cpp#L15020)
  использует BLK/BLK_PTR hierarchy и не разрешает такой block как ordinary
  part owner. [RenumberComplexPart:12972](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L12972)
  зависит от страниц, suffix/link и sidecar state.

Поэтому writer использует подтверждённый ordinary part chain. Он не
изобретает merge indices, BLK-команды, A/B native references или sidecar files.
Native merge/submerge/source/invert остаются `-1/-1/-1/0`. Source contract и
independent readback проверены; это не installed-program validation.
Primary URLs/bytes/SHA256/anchors — `output/symbols/units-source-evidence.json`.

## Ограничения source profile

- 2–16 units; стандартные styles 0/1, без альтернативного body style 2.
- Physical pin numbers должны быть **disjoint** между секциями. Within-view
  duplicates/source diagnostics отвергаются, как прежде; cross-unit repeats
  дополнительно отклоняются. Номера не меняются и не дедуплицируются.
- Common sections unit=0 с **graphics** копируются в каждую выбранную view.
  Common **pins** пока требуют отдельной политики и вызывают отказ: запись
  нельзя просто размножить, сохранив однозначную physical identity.
- Каждая declared unit должна иметь хотя бы один physical pin. Power units,
  no-connect/hidden/styled/alternate pins, virtual/BOM-excluded symbols пока
  отвергаются по существующему pin/symbol profile.
- Graphics/text/fill допускаются только в подтверждённых предыдущих профилях.
  Source common graphics, inheritance и aliases сохраняются без изменения.

Например, R_Pack04_Split имеет pin sets `[8,1]`, `[7,2]`, `[6,3]`, `[5,4]`
и теперь генерируется. R_Network03_Split/common-anode diodes с unit=0 pin
отклоняются. LM393 отклоняется из-за отдельной power unit; PIC24 cache —
по прежним unresolved duplicates. Эти ограничения не исправляют source молча.

## Размещение и отчёты

Секции обрабатываются по ascending unit number существующим single-unit
renderer в private typed copies. Из исходной библиотеки ничего не изменяется.
Готовые NM records переводятся по X, без вращения, масштабирования и Y flip.
Первая секция имеет offset `(0,0)`; каждая следующая начинается за правой
границей предыдущей с заданным gap. Bounds включают geometry/stroke margin
и body-text anchors, но не неизвестные glyph bounds.

`--unit-gap` задаёт mm, default 2.54; finite `0 < value <= 100`, минимум 1 NM
после округления. API — `convert_symbol(..., unit_gap=...)`; bundle config —
optional `symbol_unit_gap`. У native component один Reference/Value/Footprint;
source unit labels/suffixes и независимое перемещение логических частей потеряны.
Ширина промежутка и native bounds не доказывают отсутствие пересечения glyphs.

Aggregate limits: 32768 body corners и 4096 fill polylines для **всего**
compound symbol; каждый contour сохраняет прежний собственный limit. Signed
32-bit NM проверяется для bounds, offsets, corners и attached text. Overflow,
gap collapse или budget breach отклоняют весь symbol до записи.

Отчёт содержит полный original `source_symbol`,
`target.source_units_profile=disjoint-units-layout-v1` и `unit_layout`:

- original source unit, exact `translation_nm`, source/target view bounds;
- copied common graphics и все target polyline indices;
- source number/name/type/connection point → native pin record/body/free end;
- `independent_unit_placement_transferred=false`,
  `native_hierarchical_merge_generated=false`, `common_pin_policy=reject`.

Curves/fills/text metadata и diagnostics имеют global indices, source unit и
`rendered_unit`, translation. `center_mm` относится к размещённому native
curve/fill, `source_center_mm` сохраняет исходный center. Legacy arc resolution
остается в source frame до placement. Text сохраняет source anchor и отдельный
`native_anchor_nm`. Common component losses считаются один раз; конкретные
graphic losses/approximations — по rendered view. ERC rules остаются в JSON.

`SYMBOL_UNITS_FLATTENED` — loss. `strict` возвращает rejection report с
полным source/layout/proposed hash и сохраняет предыдущий CDS. Неподдержанные
shared/power units не публикуют частичные секции. Single-unit CDS/reports
не меняются; source pin mapping и GUI/3D scope остаются раздельными.

## Контроль и команды

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/R_Pack04_Split_units.cds --symbol R_Pack04_Split --unit-gap 2.54
python3 -B -m src.component_converter tests/fixtures/components/units.json \
  output/components/units
python3 -B -m src.component_converter --verify output/components/units
```

Bundle output должен быть новым каталогом. Пять real controls используют целые
unchanged definitions Device KiCad 9.0.0:

| Output stem `*_units` | Source units | Physical pins |
|---|---:|---:|
| R_Pack02_Split | 2 | 4 |
| R_Pack03_Split | 3 | 6 |
| R_Pack04_Split | 4 | 8 |
| R_Pack02_SIP_Split | 2 | 4 |
| R_Potentiometer_Dual_Separate | 2 | 6 |

Последний пример также переносит два экземпляра common filled graphic.
Native outputs всегда содержат один component, не отдельные физические детали
с разными References. Это не полный Device/Comparator coverage.

Партия: Array2 → R_Array_Concave_2x0603, Array4 → R_Array_Concave_4x0603,
SIP4 → source property Resistor_THT:R_Array_SIP4. Проверены source/CDS/FPL
номера 1–4, 1–8 и 1–4: 3 complete file chains, 3 existing STL, 204252 source
bytes, 17 package files. Generic SMD bindings заданы вручную; функция pad,
пригодность конкретному компоненту и physical STL alignment не проверены.
Новые целые footprints pinned KiCad 51f8a59...; URL/bytes/hashes —
`tests/fixtures/components/units-provenance.json`, license — `LICENSE.md`.
Summary — `output/symbol-units.summary.json`; runtime игнорируется Git.
Модели только копируются/хешируются, без mesh parsing/конвертации.

24 новых теста; всего **336**, все проходят, copy без STL/STEP — с тремя
optional integration skips. Literal source/native pin probes, NM gap/bounds,
common graphics, disjoint/shared policies, inheritance/legacy aliases,
curve/fill/text rebasing, aggregate budgets/overflow, strict/CLI preservation
и relocation проверены. Все старые single-unit controls/reports и четыре
предыдущих bundles воспроизводятся без изменений.

Далее — power/no-connect policy. Shared pins, hidden/styled/alternate pins,
native independent units/hierarchy, GUI/3D validation и library scale остаются
незавершёнными задачами.
