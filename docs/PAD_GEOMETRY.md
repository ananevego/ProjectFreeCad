# Native pad geometry: slots, offsets и custom pads

Состояние на 2026-10-16. Target — FreePCB2 **2.428**, pinned revision
`3af0f9b9a234c97f2d21455c936abeb8439d2d45`. Новый профиль
`freepcb2428-exact-pad-reductions-v1` переносит только доказуемые эквиваленты;
настоящие slots, nonzero offsets и непрямоугольные custom unions имеют refusal.

## Подтверждённые ограничения формата

[Native Shape.h](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.h#L95)
задаёт shape, size_X, size_Y и radius; padstack хранит один `hole_size`, одну
позицию и угол. Shape enum включает none/round/square/rect/roundrect/oval/octagon;
arbitrary custom polygon и независимый hole/shape offset отсутствуют.

[FPL reader](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1454)
складывает два исторических X extent tokens в одну size_X. Асимметричные tokens
не дают asymmetrical pad: [renderer](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/PartList.cpp#L1738)
строит pad симметрично pin position; hole рисуется окружностью относительно
той же позиции. Slot нельзя сохранить одним diameter.

[KiCad9 drill parser](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L5072)
передаёт drill offset в pad SetOffset.
[ShapePos](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L1016)
добавляет повёрнутый offset к позиции copper shape, сохраняя pad/hole anchor.
Перемещение целевого pin изменило бы отверстие и electrical anchor, поэтому
такой перенос не выполняется.

| Source case | Результат |
|---|---|
| Round drill без offset | Прежний native hole_size |
| Oval с **равными** осями / explicit zero offset | Та же круглая геометрия, info и source spelling в JSON |
| Oval с разными осями | DRILL_SLOT_UNSUPPORTED, без FPL |
| Nonzero shape offset | PAD_OFFSET_UNSUPPORTED, без FPL |
| Custom union точно является centred rectangle | Ограниченный exact reduction ниже |
| Custom union nonrectangular или centre≠anchor | CUSTOM_PAD_NONRECTANGULAR / CUSTOM_PAD_OFFSET_UNSUPPORTED |

PadGeometryError сохраняет source pad, dimensions/offset или union proof и
структурированный diagnostic severity=error в single CLI и batch JSON.
Прежний FPL при отказе сохраняется; batch ставит output_current=false,
не считает старый файл успешным. Malformed/duplicate/non-finite drill fields
также отклоняются. Equal axes сравниваются до target rounding: 1 и 1.000001mm
не превращаются в circle только потому, что target grid равна 10nm.

## Exact rectangular reduction custom SMD

[KiCad effective pad](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L635)
включает anchor и [локальные primitives](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L759).
Профиль допускает только hole-free SMD с одной outer copper side, explicit
`anchor rect` / `clearance outline`, до **32** `gr_poly`. Каждый primitive
должен быть заполненным axis-aligned rectangle из четырёх corners, width=0,
без дополнительных полей. Повтор closing corner допускается; empty primitives
при explicit rectangular anchor дают сам anchor.

Proof использует rational vertical slabs: для каждого интервала по X
вычисляется точная длина объединения Y intervals. Union area должна строго
равняться bounding area, а центр bounds — исходному anchor. Сумма площадей
overlapping rectangles не используется как proof; gaps/notches/holes и
disconnected pieces не заполняются. Даже **1nm notch** даёт отказ до native
10nm quantization. Bounding box для произвольного custom pad не подставляется.

Source coordinates должны лежать на 1nm grid, anchor dimensions — содержать
чётное число nm. Это учитывает integer half-size в KiCad и исключает proof
по идеальному float anchor, отличающемуся от source integer geometry.
Остальные варианты остаются outside-profile refusals. Target writer использует
прежнюю 10nm quantization; origin, local orientation, pin number и количество
pin records сохраняются. Native rectangle не сдвигается относительно anchor.

Mask/paste требуют явных resolved **nonnegative absolute margins**, paste
ratio=0. Приоритеты pad→footprint→defaults прежние. По
[GetSolderPasteMargin](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L1210)
ratio зависит от source anchor size; пересчитывать его через bounds union
нельзя. Negative margins/неизвестные defaults требуют отдельного профиля и
получают CUSTOM_PAD_APERTURE_UNSUPPORTED. Для отсутствующих source apertures
соответствующие defaults не требуются. Геометрический audit не объявляет
equivalent_geometry гарантией поддержанных aperture settings.

Source raw/typed custom pad остаётся неизменным. Только render copy становится
rect; JSON содержит source, proposed native pad и area/bounds/proof method.
`CUSTOM_PAD_RECT_FLATTENED` — **loss**: primitive editing и source zone/thermal
settings не переносятся. Strict отклоняет результат. GUI/netlist/manufacturing
flags остаются false, даже когда geometry proof и record readback проходят.

## Реальные отказы и контрольная партия

Неизменённые pinned 120 footprints остаются **110 generated_with_loss /10 failed
(91.67%)**, unexpected errors=0. Причины теперь разделены:

| First refusal | Files | Pad records во всём raw corpus |
|---|---:|---:|
| DRILL_SLOT_UNSUPPORTED | 6 | 22 |
| PAD_OFFSET_UNSUPPORTED | 1 | 1 |
| CUSTOM_PAD_NONRECTANGULAR | 3 | 3 |

Offset case — Vishay_HVM-DIP-3_W7.62mm, pad1 `(offset 0 -0.5)`: copper centre
отличается от hole/connection anchor. Три custom pads не сводятся к rectangle:

| Footprint | Union area mm² | Bounding area mm² | Лишняя медь при bbox replacement mm² |
|---|---:|---:|---:|
| LFPAK33 | 5.1545 | 5.8045 | 0.65 |
| SOT-89-3 | 6.743125 | 7.9718 | 1.228675 |
| Vishay_PowerPAK_SC70-6L_Single | 1.845 | 2.09 | 0.245 |

Raw inventory описывает все special pads, включая failed files. Audit проверяет
hashes, immutable provenance, 2429 pad readbacks в 110 outputs; для accepted
reductions повторяет proof/source/native normalization и сравнивает JSON.
Это тот же normalization engine, не независимый native loader. Независимые
numerical tests задают expected areas/interval geometry и native record values.
14 repeated-number bindings по-прежнему ambiguous; GUI/netlist/Gerber/3D
проверенными не считаются. Все 110 прежних FPL/reports unchanged.

Новые snapshots: `output/footprint-pad-geometry-medium.audit.json`, benchmark
с тем же prefix и `output/footprint-pad-geometry.source-evidence.json`
(revision/URL/bytes/SHA256/anchors). Старые snapshots не переписаны.
Fresh-output/resume/audit ~.823/.506/.669s, peak process RSS ~44.8MiB на
Python3.13/macOS arm64; параллельно выполнялись tests, filesystem cache мог
быть тёплым. Это не прогноз на
полную библиотеку или Windows. Resume reuse=110, failed retry=10.

```sh
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium-pad-geometry-release --default-mask-margin .05 \
  --default-paste-margin 0 --default-paste-ratio 0
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium-pad-geometry-release --default-mask-margin .05 \
  --default-paste-margin 0 --default-paste-ratio 0 --resume
python3 -B -m src.footprint_converter.audit tests/fixtures/medium \
  output/batches/medium-pad-geometry-release output/footprint-pad-geometry-medium.audit.json \
  --provenance tests/fixtures/medium/provenance.json
```

Batch returns2 из-за expected source refusals; audit returns0 для согласованного
completed manifest. Runtime outputs/cache ignored; corpus и portable audit
сохранены. Settings .05/0/0 выбраны явно и не восстанавливают исходную плату.

Отдельный **synthetic** `tests/fixtures/pad-geometry/PadGeometry_Control.kicad_mod`
содержит centred custom rectangle и две формы circular drill equivalence.
Saved FPL и geometry-report reproducible; это не официальный positive corpus.
23 новых tests, всего **460**, проходят; portable copy без STL/STEP — с 3
optional skips. Восемь прежних component bundles byte-identical и проверены
после relocation; новый synthetic custom symbol→footprint case также проверен
без claim complete 3D chain. Meshes не интерпретировались/не конвертировались.

Следующий шаг — комплект для native validation. **Остаток: примерно 15–25%
проекта, четыре крупных блока**; отсутствие прироста medium success отражает
подтверждённые ограничения выбранного native формата.
