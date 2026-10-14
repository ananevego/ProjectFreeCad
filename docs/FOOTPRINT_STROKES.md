# Graphic strokes: KiCad → FreePCB2

Состояние на 2026-10-15. Поддержаны `default`/solid и ограниченный профиль
`kicad9-pcb-editor-default-strokes-v1` для незаполненных прямых линий,
прямоугольников и простых полигонов на прежних разрешённых graphic layers.
Дуги/окружности/filled outlines с patterned style пока вызывают явный отказ.

## Подтверждённый контракт

[KiCad9 EDA_SHAPE::GetLineStyle](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/common/eda_shape.cpp#L2061)
возвращает SOLID для DEFAULT. Поэтому `type default` проходит тем же путём,
что solid, без новой потери или дополнительных записей. Четыре отказа в
средней партии прошлого этапа были ошибочно классифицированы как non-solid:
все они содержат default; настоящих dash/dot там нет. Raw inventory теперь
отдельно считает типы: 3261 solid и 16 default в 120 unchanged footprints.

[PCB renderer defaults](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pcb_painter.cpp#L125)
задают ratios dash=12, gap=3.
[Render settings](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/common/render_settings.cpp#L57)
с поправкой round caps=1 дают следующие длины **центральных отрезков**:

| Source style | Чередование длин в единицах source width w |
|---|---|
| dash | mark 11w, gap 4w |
| dot | mark .2w, gap 4w |
| dash_dot | mark 11w, gap 4w, mark .2w, gap 4w |
| dash_dot_dot | mark 11w, gap 4w, mark .2w, gap 4w, mark .2w, gap 4w |

[Effective straight shapes](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/common/eda_shape.cpp#L1479)
и [STROKE_PARAMS::Stroke](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/common/stroke_params.cpp#L127)
подтверждают restart фазы на каждом ребре, исходный порядок/направление
координат и clipping последнего mark к endpoint. Длина вычисляется от начала
ребра без накопления ошибки за каждый шаг. Reversed endpoints сохраняются.
Исключение: [inclusive ClipLine](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/libs/kimath/src/geometry/geometry_utils.cpp#L137)
может дать zero-length point mark, если новый mark начинается ровно на endpoint.
Restricted FPL profile кодирует только marks положительной длины: такой
изолированный endpoint cap опускается с явной loss policy
`zero_length_endpoint_marks=omitted_with_loss` в JSON и диагностике.

[FreePCB2 outline reader](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1362)
и [writer](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L2102)
хранят width, visibility, hatch, layer и corners. Native dash field нет,
поэтому каждый mark — открытая двухточечная `outline_polyline`, без линии
между marks или `close_polyline`. Origin/Y flip/layers/10nm grid прежние.
Revision, URL, bytes, SHA256 и anchors сохранены в
`output/footprint-strokes.source-evidence.json`.

## Ограничения и loss policy

В `.kicad_mod` нет настроек renderer/project. Реализован фиксированный PCB
editor default profile KiCad9; plotter, project overrides, zoom/outline mode
и hairline substitutes этим профилем не восстанавливаются. Source style и
geometry остаются в typed/raw source и JSON `graphic_strokes`. Native editable
style не сохраняется; endpoint point marks опускаются, caps/joins и производство пока не проверены.
`GRAPHIC_STROKE_FLATTENED` имеет severity **loss**, `--strict` отклоняет FPL.
Все GUI/manufacturing flags false. Численные endpoints не доказывают visual
или Gerber equivalence в целевой программе.

Лимит — **4096 marks на весь footprint**, polygon — не более 512 corners.
Zero/non-finite widths, marks/edges, исчезающие на target grid, нулевые или
самопересекающиеся polygons, неизвестные styles, mixed modern/legacy widths,
duplicate/malformed stroke fields и source colors отвергаются. Контуры на
неподдерживаемых слоях сохраняют прежнюю GRAPHIC_LAYER_SKIPPED loss policy.
Ограничения проверяются до записи; длинный contour не обрезается по лимиту.
Если endpoint попал в gap, до него не добавляется сплошная линия.

## Контроли и средняя партия

Отдельный **синтетический** `tests/fixtures/strokes/StrokePatterns_Control.kicad_mod`
содержит все четыре patterns, rect и triangle. Он не объявлен официальным
library source. Сохранены `output/StrokePatterns_Control.fpl` (71 marks) и
`output/StrokePatterns_Control.stroke-report.json`; воспроизводимость проверена.
Этот контроль дополняет реальные default cases и medium corpus; medium success
не считается доказательством покрытия dash/dot официальной библиотеки.

После default fix **110/120 FPL с known losses (91.67%)**, раньше 107/120.
Новые successful cases: USB_C_Plug_ShenzhenJingTuoJin_918-118A2021Y40002_Vertical,
L_Wurth_WE-CAIR-5910, Texas_S-PWQFN-N100_EP5.5x5.5mm.
USB3_A_Molex_48393-001 теперь проходит graphic parser, затем получает
oval-drill refusal. Остаются 7 oval/offset-drill и 3 custom-pad failures;
unexpected errors=0. Audit проверил 2429 pad records в 110 outputs, hashes,
Git blob provenance, raw inventory; 14 repeated-number bindings ambiguous.
Native GUI/netlist/Gerber/3D не объявлены подтверждёнными.

Новые snapshots: `output/footprint-strokes-medium.audit.json` и
`output/footprint-strokes-medium.benchmark.json`. Исторические medium snapshots
107/13 не переписаны. Fresh-output/resume/audit ~.454/.236/.246s, process peak
RSS ~45MiB; filesystem cache мог быть тёплым. Измерение не даёт прогноза
для всей библиотеки/Windows. Resume reuse=110, failed retry=10.

```sh
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium-strokes-final --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium-strokes-final --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0 --resume
python3 -B -m src.footprint_converter.audit tests/fixtures/medium \
  output/batches/medium-strokes-final output/footprint-strokes-medium.audit.json \
  --provenance tests/fixtures/medium/provenance.json
```

Batch возвращает 2 для ожидаемых 10 failures; audit — 0 для согласованного
completed manifest. Defaults .05/0/0 выбраны явно. Runtime paths/caches остаются
ignored; настройки API/CLI и resume fingerprint автоматически охватывают
изменённый engine, нового переключателя для patterns нет.

20 новых тестов проверяют literal pattern intervals, gaps, clipping, направление,
phase на closing edges, width scaling, сетку, source immutability, strict/CLI
preservation, complexity limits, corrupt strokes, raw audit и resume invalidation.
Всего 437 tests; portable copy без STL/STEP проходит с 3 optional skips.
Все 107 прежних FPL/reports и восемь component bundles unchanged; bundles также
проверены после relocation. STL geometry не читалась/не конвертировалась.

Далее — native contract oval/offset drills и custom pads. **Остаток: 15–25%
проекта, четыре крупных блока**; ограниченный profile не закрывает полную
поставку и native validation.
