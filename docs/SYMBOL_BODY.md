# Заливка и графический текст УГО

Состояние на 2026-10-13: профиль `bounded-fills-body-text-v1` поддерживает
простую foreground заливку и literal graphic text односекционных УГО.
Используются прежние native straight records `.cds` 1.429. Background fill
сохраняется как граница с явной потерей перекрытия. Импорт, шрифты, порядок
отрисовки и caps/joins в установленном Схематоре ещё не проверены.

## Что передаётся

| Source | Native результат | Ограничение |
|---|---|---|
| Rectangle, `fill outline` | Boundary + перекрывающиеся горизонтальные strokes | Численный bound в идеальной модели round-ended strokes |
| Closed simple polygon, `fill outline` | Boundary + scanline strokes, включая concave contours | До 512 вершин, без holes/self-intersections/touching edges |
| Circle, `fill outline` | Адаптивная polygon boundary + strokes | Диск покрыт; curve/fill tolerances учитывают округление |
| Rectangle/polygon/circle, `fill background` | Только validated boundary | `SYMBOL_BACKGROUND_FILL_NOT_TRANSFERRED`: цвет и occlusion потеряны |
| Modern `text`, legacy `T` | `description` на contour тела, слой 14 | Literal text, quarter-turn; source anchor используется как native baseline |

Filled arcs/Bezier и незамкнутые filled polylines пока вызывают отказ.
Implicitly closed legacy triangles, repeated/collapsed vertices и вырожденные
rectangles автоматически не исправляются. В частности, legacy LED/Schottky
из cache и современные LED_RGB со zero-size body rectangles остаются отказами.
Поддержка нескольких реальных примеров не означает поддержку всего Device.

Foreground fill переиспользует чистую геометрию существующего footprint
tessellator, сохраняя source **Y up**. Footprint writer и его Y inversion не
вызываются. Запись fill geometry идёт по сетке 10 NM; остальная symbol geometry
сохраняет прежнюю сетку 1 NM. Native hatch=0, Node=0 на всех body strokes.
Pins/physical numbers/external Nodes не добавляются и не удаляются.

`--fill-tolerance` — mm-допуск расширения относительно исходной заливки **с
разрешённой source stroke width**, default 0.01, `0.00002 < value <= 1`.
Он не ограничивает полную толщину source stroke. Minimum fill stroke width
выбирается из допуска с резервом 20 NM; overlapping rows покрывают интерьер
в идеальной модели круглых caps. Circle chord error ограничен меньшим из
curve tolerance и четверти фактической fill stroke width; boundary strokes
покрывают circular caps вне вписанного многоугольника. Очень узкие spans,
схлопнувшиеся на target grid, пропускаются как уже покрытые boundary stroke;
число пропусков записывается. Это не правило для electrical pins.

Limits: 4096 emitted fill polylines на symbol и 32768 body corners суммарно.
Ошибка сетки/геометрии/лимита вызывает полный отказ, допуск не ослабляется.
Source stroke=0 разрешается прежним `--default-line-width`, с assumption.

## Native текст и background

Native foreground hatch изучен по
[PolyLine.cpp:1863](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/PolyLine.cpp#L1863):
он зависит от stroke width/layer и добавляет линии. Поэтому текущий профиль
использует собственные ограниченные strokes, а не объявляет native hatch
точным эквивалентом KiCad fill. Background color/occlusion этим кодом не
подтверждены; loss оставлен явно, фон не заменяется foreground заливкой.

[WriteOutlinesPoly:1676](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L1676)
записывает description любого owning polyline, независимо от наличия pin.
[ReadGraphics:2306](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L2306)
привязывает его к текущему polyline;
[group paste:11358](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/FreePcbView.cpp#L11358)
копирует description attributes. Reader/validator расширен для body descriptions;
их layer=14, владелец layer=6/Node=0. Они не считаются physical pins.

Каждый text получает отдельный существующий body carrier — representative
polyline исходной фигуры, ближайший по вершинам к anchor; native text position
хранится независимо. При нехватке carriers происходит отказ. Дополнительные
линии для текста не создаются; source z-order и точная компоновка не сохраняются.
Это source contract/readback, не доказанный GUI insertion.

SIMPLEX заменяет исходный шрифт; X/Y anchor, height, hidden state и угол с
обратным знаком сохраняются. Source justification/bold/italic/font face,
anisotropic size, точные baseline/glyph bounds не воспроизводятся и имеют
`SYMBOL_GRAPHIC_TEXT_LAYOUT` loss. Bounds включают anchor и geometry, не
неизвестные glyph bounds. Hidden body text хранится с size/width=0. Функции
pins остаются отдельными description attributes их собственных pin segments.

[TextList.cpp:137](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/TextList.cpp#L137)
использует apostrophe/backtick/pipe как служебный синтаксис;
[IsCommand:400](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/TextList.cpp#L400)
распознаёт BLK/BOM/PATH/DATE/ZONE и другие команды. Новый literal profile
отклоняет этот синтаксис, `${...}`, `~`/`^`, quotes/control characters и
непредставимый CP1251. Это точные ограничения native text, не silent rewriting.

Legacy `T` нормализован по
[KiCad9 loadText:960](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_io/kicad_legacy/sch_io_kicad_legacy_lib_cache.cpp#L960):
integer tenth-degree angle/mils, visibility, unit/style, size, optional italic/
bold/justification. Unquoted `~` превращается в пробел; quoted markup остаётся
для явного target отказа. Raw line/records сохранены. Unknown legacy `B`
по-прежнему имеет source-extension diagnostic.

Primary source URLs/bytes/SHA256/anchors:
`output/symbols/body-source-evidence.json`. Full target contract остаётся открытым.

## API, CLI и отчёты

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/D_Filled_body.cds --symbol D_Filled --fill-tolerance 0.01
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/Ammeter_DC_body.cds --symbol Ammeter_DC
python3 -B -m src.component_converter tests/fixtures/components/body.json \
  output/components/body
python3 -B -m src.component_converter --verify output/components/body
```

Bundle output должен быть новым каталогом. Python `convert_symbol` принимает
`fill_tolerance`; config bundle — optional `symbol_fill_tolerance`. Для старых
configs новые поля в manifest не появляются. Старые CDS/reports совместимы.

Только при новых body constructs добавляются `target.source_body_profile`,
`filled_graphics`/`graphic_texts`, source/target polyline indices, native policies,
error scopes, limits/counts/settings. Фон имеет loss, foreground fill —
approximation и `SYMBOL_FILL_STROKE_UNVERIFIED` assumption. Font/layout — loss.
`strict` сохраняет rejection report/proposed hash и прежний CDS; unsupported
constructs не заменяют CDS/JSON. Native GUI/import/3D flags остаются false.

## Контрольные результаты

| Modern Device symbol / stem `*_body` | Pins | Проверяемый объект |
|---|---:|---|
| D_Filled | 2 | Filled triangle |
| C_Polarized | 2 | Filled rectangle plate |
| Antenna_Shield | 2 | Filled circle + unfilled arcs, input/passive |
| C_Network04 | 5 | Background rectangle loss + 3 filled circles |
| Ammeter_DC | 2 | Literal A + unfilled circle |
| FrequencyCounter | 2 | Literal Hz + unfilled circle |

Это целые unchanged Device definitions KiCad 9.0.0; source font/filled flags
не удалялись для обхода ограничения. Шесть CDS/JSON controls сохранены.

`components/body.json` вручную задаёт D_Filled → D_SOD-123 и Ammeter_DC →
PinHeader_1x02_P2.54mm_Vertical. Meter/header — тестовая библиотечная привязка,
не подтверждённый footprint конкретного прибора. Проверены номера 1/2 по
source/CDS/FPL, две complete chains, два existing STL, 126368 source bytes,
12 package files. PinHeader2 — новый unchanged KiCad fixture pinned 51f8a59...;
URL/bytes/hashes — `components/body-provenance.json`, license — `LICENSE.md`.
Summary — `output/symbol-body.summary.json`; runtime игнорируется Git.
Модели копируются/хешируются, meshes не интерпретируются и не конвертируются.

27 новых тестов; всего **312**, все проходят. Interior probes и caps/chord
extrema проверяются по serialized NM strokes, отдельно от собственного
tessellator; concave notch остаётся пустой, background остаётся boundary only.
Проверены literal text/Nodes/ownership/rotation/hidden/control syntax, legacy T,
strict/CLI/geometry budgets, source immutability, linked scope и relocation.
Copy без STL/STEP проходит с 3 optional integration skips. Прежние passive/
curve/electrical controls и три старых bundles остаются byte-identical.

2026-10-13: disjoint units могут использовать этот body profile после exact
NM placement; [SYMBOL_UNITS.md](SYMBOL_UNITS.md). Далее power/no-connect policy.
Native hierarchy/shared/hidden/alternate pins, full geometry и GUI остаются открытыми.
