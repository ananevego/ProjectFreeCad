# Common pins в отдельной секции одного компонента

Состояние на 2026-10-14: `common-pins-view-v1` разрешает original unit=0
pins при explicit `common-view-with-loss`. Каждый исходный pin record
записывается **ровно один раз** в том же ordinary native component. У всей
детали один reference/value/footprint и один `part_end`; отдельные логические
секции не становятся разными физическими компонентами.

Контракт ordinary linked part chain и подсчёт attached numbers подтверждены
[ReadGraphics](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2171)
и [GetNumAllPins](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L12217).
Это позволяет использовать уже проверенный compound layout; native independent
units, hierarchical merge и KiCad ERC не передаются. Evidence сохранён в
`output/symbols/common-source-evidence.json`.

## Политика и размещение

Default `reject` сохраняет прежнее поведение. API:
`convert_symbol(..., common_pin_policy='common-view-with-loss')`; CLI:
`--common-pin-policy common-view-with-loss`; bundle `symbol_common_pin_policy`.
Неизвестные значения отвергаются до записи даже у single-unit symbols.

Логические units идут по порядку 1..N, затем размещается дополнительная view
`source_unit=0`, содержащая только original common pins и их pin decorators.
Common body graphics повторяются в логических views, как раньше; extra view
не добавляет ещё одну копию body. Source geometry не редактируется: используются
private typed copies, original source/raw units полностью сохранены в JSON.

2–16 logical units плюс до одной common view. Каждая logical unit должна иметь
собственные pins; profile не рисует отдельную пустую секцию без terminals.
Все original physical numbers должны быть уникальны между source blocks.
Within-view diagnostics, common/own number conflicts, повторяющиеся номера
положительных units и дубли original common records остаются отказом.
Никакие records не дедуплицируются и номера не меняются. Styles 0/1,
NM translations/gap/bounds, aggregate corner/fill budgets и прежние source
geometry/encoding ограничения сохраняются.

`SYMBOL_COMMON_PINS_PLACED_ONCE` — loss shared-view appearance/placement и
native hierarchy. Reports содержат source logical count, rendered view count,
common numbers, per-view/global native indices, actual terminal points.
`pin_semantics` включает все source physical records и `rendered_unit=0`
для common terminals. Hidden/power/NC/marker policies применяются независимо:
hidden требует reveal, NC требует explicit connectable mode. ERC, implicit
nets и NC enforcement не повышаются после verified number mapping.
Strict отклоняет losses, сохраняя source/layout/proposed hash и последний CDS.
Неиспользуемая common policy не меняет предыдущие reports/records.

## Реальный контроль

| Device KiCad9 control | Logical units | Physical pins | Common |
|---|---:|---:|---|
| R_Network03_Split | 3 | 4 | 1 |
| R_Network04_Split | 4 | 5 | 1 |
| R_Network07_Split | 7 | 8 | 1 |
| R_Network13_Split | 13 | 14 | 1 |

Целые unchanged definitions сохранены; outputs — `output/symbols/*_common`.
Все номера встречаются один раз, common 1 располагается в дополнительной view.
Split-diodes сохраняют отказ для source contours с collapsed/repeated segments;
эта политика не обходит непредставимую graphics. Coverage всей библиотеки
и физическая пригодность корпуса этими controls не доказаны.

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/R_Network03_Split_common.cds --symbol R_Network03_Split \
  --common-pin-policy common-view-with-loss
python3 -B -m src.component_converter tests/fixtures/components/common.json \
  output/components/common
python3 -B -m src.component_converter --verify output/components/common
```

Bundle требует нового каталога. Network3/4/7 используют точные source
Footprint properties SIP4/SIP5/SIP8, включая pad 1: 3 complete file chains,
3 existing assets, 466152 source bytes, 17 package files. Model geometry,
physical suitability, native import/netlist и GUI не подтверждены. Whole
SIP5/SIP8 fixtures pinned KiCad 51f8a59...; source provenance в
`tests/fixtures/components/common-provenance.json`, license прежняя. STL
только копируются/хешируются. Summary — `output/symbol-common.summary.json`.

18 новых тестов, всего **398**. Проверены literal view/pin counts, exact
identity, original/raw immutability, non-deduplication/conflicts, empty/alternate
refusals, hidden power/NC, rebased markers, budgets, strict/CLI preservation,
source properties и relocation. Семь предыдущих bundles воспроизводятся
без изменений. В копии без STL/STEP те же проверки проходят с тремя optional
integration skips. Далее — audit/расширение footprint coverage и подготовка
средней партии; native GUI/3D и scale/release остаются отдельными блоками.
