# Графические маркеры и скрытые выводы

Состояние на 2026-10-14: `kicad9-editor-pin-markers-v1` переносит inverted,
clock, inverted_clock, input_low, clock_low, output_low, edge_clock_high и
non_logic как non-electrical body strokes на layer 6. Один numbered layer-8
terminal сохраняет original external point и Node=1. Inversion bubble
сокращает только внутренний segment; номер, source/raw records не меняются.

Профиль следует [SCH_PAINTER KiCad 9.0.0](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_painter.cpp#L944).
Clock triangle в редакторе имеет глубину одного radius; plotter использует
другую геометрию. Default `m_PinSymbolSize=0` задаёт internal radius из name
height (fallback number), external radius из number height. Размеры разрешаются
на KiCad 100nm IU, затем integer /2. Project sizing override отсутствует в
library; выбор default profile, logical style, caps/joins и font layout имеют
явный loss. Bubble имеет прежний centerline tolerance, default .01mm, включая
NM rounding. Marker corners входят в body budgets, включая compound units.
Native marker/ERC interpretation и GUI ещё не подтверждены.

[SCH_PIN::IsGlobalPower](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_pin.cpp#L364)
связывает hidden power_in с implicit global power nets. Поэтому hidden pins
по умолчанию отклоняются. API `hidden_pin_policy='reveal-with-loss'`, CLI
`--hidden-pin-policy reveal-with-loss`, bundle `symbol_hidden_pin_policy`
явно раскрывают numbered terminals с loss visibility/global-name connections.
Такие выводы требуют явного подключения; скрытые надписи регулируются отдельно.
Hidden NC требует также explicit `no_connect_policy='connectable-with-loss'`.
Stacked/coincident terminals, zero-length pins, alternate modes и styled NC
по-прежнему отклоняются; source power/virtual/BOM flags не обходятся.

Reports добавляют `pin_markers`, global record indices, source/target body
anchors, sizes/error bounds, `counts.styled_pins/hidden_pins`, source hidden/
style/global-power flags и `implicit_global_power_transferred=false`.
`SYMBOL_PIN_MARKER_GRAPHICS` и `SYMBOL_HIDDEN_PIN_REVEALED` — loss; bubble
имеет отдельную approximation. В units rebased indices/centers сохраняют
original source frame. Strict отклоняет losses и не заменяет последний CDS.
Неиспользуемая hidden policy не меняет предыдущие standalone reports.
Source hashes/URLs/anchors — `output/symbols/pins-source-evidence.json`.

Шесть целых real controls: legacy SW_PUSH, 74LVC1G125, 74LVC1G79,
74LVC2G79, MIC845H и AVR-PDI-6 (`output/symbols/*_pins.cds`/reports).
74xGxx KiCad9 сохранена целиком: 174 definitions, pinned source provenance
и прежняя KiCad Libraries license в `tests/fixtures/symbols/`. Это выборка,
не coverage всей библиотеки. 74LVC1G80 с markup остаётся явным отказом.

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/74xGxx.kicad_sym \
  output/symbols/74LVC1G79_pins.cds --symbol 74LVC1G79
python3 -B -m src.component_converter tests/fixtures/components/pins.json \
  output/components/pins
python3 -B -m src.component_converter --verify output/components/pins
```

Bundle требует нового каталога: пять complete chains, три existing STL,
553052 source bytes, 23 package files. Clock5/Inverted5/Hidden5 используют
SOT-23-5, DualClock8 — DIP-8, Hidden6 — Header6. Bindings вручную проверяют
source/CDS/FPL number identity; функцию, пригодность корпуса и 3D alignment
не подтверждают. Новый whole SOT-23-5 fixture pinned KiCad 51f8a59...;
provenance в `components/pins-provenance.json`, license прежняя. Модели только
копируются/хешируются. Summary — `output/symbol-pins.summary.json`.

21 новый тест, всего **380**: all shapes/cardinal orientations, literal GUI
geometry/Y-up, bubble error/shortening, source immutability, hidden power/NC,
stacked/default/invalid refusals, budgets/overflow, compound rebasing,
strict/CLI preservation, real controls и relocation. Шесть прежних bundles
воспроизводятся без изменений. Common pins в отдельной view добавлены:
[SYMBOL_COMMON.md](SYMBOL_COMMON.md); всего 398 тестов.
Native hierarchy, implicit nets/ERC/NC enforcement и GUI остаются открытыми.
