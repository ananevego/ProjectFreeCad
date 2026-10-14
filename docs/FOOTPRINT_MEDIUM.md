# Средняя партия footprints и проверка покрытия

Состояние на 2026-10-14: 120 неизменённых официальных KiCad footprints из
12 категорий на revision `51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c`.
Выбор — 10 evenly spaced sorted paths на категорию, закреплённый provenance.
908267 source bytes, 2557 raw pad records. Tree metadata на этой revision
содержит 15464 footprint files; около 20000 в плане остаются ориентиром,
не размером локальной поставки. Это engineering sample; доля успеха относится
только к нему. Source provenance/license: `tests/fixtures/medium/`.

## Результат и исправления

Первый прогон дал 85 generated_with_loss /35 failed (70.83%). После двух
подтверждённых extensions — **107 generated_with_loss /13 failed (89.17%)**.
Потери сохраняются в reports; ничего не удаляется из source для увеличения
процента. Unexpected implementation errors — 0.

| Категория, по 10 files | Generated with loss | Failed |
|---|---:|---:|
| Capacitor_SMD | 10 | 0 |
| Connector_PinHeader_2.54mm | 10 | 0 |
| Connector_USB | 3 | 7 |
| Crystal | 10 | 0 |
| Inductor_SMD | 9 | 1 |
| MountingHole | 10 | 0 |
| Package_DFN_QFN | 9 | 1 |
| Package_DIP | 9 | 1 |
| Package_QFP | 10 | 0 |
| Package_TO_SOT_SMD | 7 | 3 |
| Resistor_SMD | 10 | 0 |
| Resistor_THT | 10 | 0 |

Technical-only SMD pads с explicit F/B.Mask/Paste поддержаны как отдельные
native padstack carriers: hole=0, top/bottom/inner copper отсутствуют, только
source apertures. Circle/rect/oval/roundrect и integer angles разрешены;
wildcard/other technical layers, custom shapes, holes и unnamed copper pads
по-прежнему отклоняются. Unnamed carriers получают уникальные `__TECH_<index>`
без коллизий/39-char truncation. Source labels/layers/geometry остаются в JSON;
исходные typed/raw records не меняются.

[KiCad GetSolderMaskExpansion/GetSolderPasteMargin](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L1125)
возвращают zero margin для pads без copper layers, поэтому размер технического
aperture не расширяется даже при заданных defaults/локальных margins.
[FreePCB2 padstack constructor](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L40),
[read fields](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1438)
и [separate paste rendering](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L3150)
подтверждают этот restricted record profile. В 19 successful files сохранены
133 technical carriers; `TECHNICAL_PAD_CARRIER` — loss, native netlist/Gerber
behavior остаётся unverified. Strict отклоняет известную потерю.

Contact `connect` pads имеют zero drill, одну внешнюю copper side и no paste
по [KiCad CheckPad](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/pcbnew/pad.cpp#L2216).
Geometry/mask/layers сохраняются как surface pad; connector attribute остаётся
в JSON с loss `CONNECT_PAD_TYPE_FLATTENED`. Поддержаны 3 MountingHole files
с 5 contact pad records. Paste/hole/inner/both-copper contacts вызывают отказ.
URLs/bytes/SHA256/anchors — `output/footprint-pad-roles.source-evidence.json`.

Оставшиеся **первые причины отказа**: 6 files с oval/offset drills, 4 с
штриховыми/non-solid strokes, 3 с custom pads. Дополнительные unsupported
features могут обнаружиться после устранения первого отказа. Raw inventory
считает всё наличие конструкций, включая failed files: 23 oval/offset drill
records и 3 custom pad records. Они не заменяются round/rect приближением.

## Аудитор и область проверок

Новый read-only `src.footprint_converter.audit` проверяет completed manifest,
source/report/FPL hashes, optional pinned SHA256/Git blob provenance и
source/FPL pad count, literal electrical labels с сохранением multiplicity,
copper shape/size/layers, location/Y flip, drill/angle и technical apertures.
Для всех 107 generated files выполнены эти checks: 2295 written pad records.
Это отдельный structural/source check; glyphs, polylines, native connectivity,
netlist, Gerber и 3D physical alignment не объявлены проверенными.

В 13 successful footprints встречаются повторяющиеся электрические номера
(thermal vias и отдельные pad occurrences). Они сохраняются, а audit отдельно
ставит `unique_number_mapping_possible=false`; component exporter продолжает
отклонять такие ambiguous bindings. FPL generation не означает complete
symbol→footprint chain. В runtime matched 73 model references, у 34 successful
items есть MODEL_MISSING. Models только проверяются по metadata.

Audit JSON имеет relative source paths, options без machine-local stl_root,
feature totals, per-category statuses, failure categories и scoped flags false.
Byte fingerprint относится к конкретному audited manifest. Audit можно повторить
после relocation source+batch без model store. Input/artifact/report corruption,
status/count/geometry contradictions, unsafe paths, incomplete batch и mismatched
provenance отклоняют audit; предыдущий JSON сохраняется при ошибке.

```sh
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0
python3 -B -m src.footprint_converter.batch tests/fixtures/medium \
  output/batches/medium --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0 --resume
python3 -B -m src.footprint_converter.audit tests/fixtures/medium \
  output/batches/medium output/footprint-medium.audit.json \
  --provenance tests/fixtures/medium/provenance.json
```

Batch returns 2 из-за 13 ожидаемых source-profile refusals; resume reuse=107,
failed retries=13. Audit returns 0 при согласованном completed manifest,
даже если batch имеет failed; 1 — ошибка проверки/path. Defaults .05/0/0
выбраны явно для теста и не восстанавливают параметры исходной платы.
Runtime FPL/reports/state игнорируются Git, corpus/audit/benchmark сохраняются.

## Измерения и следующие работы

Один process Python 3.13/macOS arm64: fresh-output batch ~0.455s, resume ~0.233s,
audit ~0.227s; peak process RSS ~41.5MiB. Source filesystem cache мог быть тёплым;
это не cold-cache benchmark и не прогноз для 15464/20000 files или Windows.
Точные значения/среда/summaries — `output/footprint-medium.benchmark.json`.

19 новых тестов, всего **417**, проходят; clone без STL/STEP — с 3 optional
integration skips. Checked primary fields, unmodified corpus/license/blob
hashes, masks/paste, names/limits, contact refusals, strict, readback corruption,
failed inventories, ambiguous numbers, relocation и resume. Восемь прежних
component bundles воспроизводятся без изменений; models не переконвертированы.

Далее — source/native contract штриховых strokes и ограниченный профиль;
custom pads/oval drills, repeated-number component mapping, native Windows
GUI/Gerber/3D и полная библиотека остаются открытыми. **Остаток: 15–25% проекта,
4 крупных блока**; средняя партия начинает блок 6, не завершает поставку.
