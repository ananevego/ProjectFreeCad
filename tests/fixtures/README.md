# Контрольные KiCad footprints

`R_0805_2012Metric.kicad_mod` — неизменённый файл сообщества KiCad из
[официальной библиотеки Resistor_SMD](https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/master/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod).
Получен 2026-10-10 из master, version=20260206. Это зафиксированный локальный
эталон; тесты не требуют сети. Он не выдаётся за ранее использованный исходник
старого прототипа (тот файл в проекте отсутствовал).

SHA-256: `f050b6a50cc7e6f86291fb7aa8f87b0d02255e21cfbddf291cdccc87e5889794`.

Авторство: KiCad community. Лицензия: CC-BY-SA 4.0 с исключением KiCad Libraries;
оригинальный документ сохранён в `LICENSE.md`. Исходный файл не изменялся.
STL в этот каталог не копируется. Unit tests создают временный metadata-only
файл, который не является 3D-моделью и никогда не парсится как геометрия.
Отдельный интеграционный тест проверяет путь/метаданные существующего файла в
`stl_files/Resistor_SMD.3dshapes`, если он доступен; иначе тест явно пропускается.

## Малая выборка PTH / NPTH / неподдерживаемой графики

Следующие файлы получены 2026-10-10 из официальной библиотеки KiCad, ревизия
`51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c`, version=20260206.
Они сохранены без изменений, под той же лицензией KiCad Libraries из `LICENSE.md`.

| Файл | Исходник | SHA-256 |
|---|---|---|
| `PinHeader_1x03_P2.54mm_Vertical.kicad_mod` | [Connector_PinHeader_2.54mm](https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c/Connector_PinHeader_2.54mm.pretty/PinHeader_1x03_P2.54mm_Vertical.kicad_mod) | `e5f24b6fea852f86171042806da48490229c9c8025b6d266b8cad6485b26e79f` |
| `MountingHole_3.2mm_M3.kicad_mod` | [MountingHole](https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c/MountingHole.pretty/MountingHole_3.2mm_M3.kicad_mod) | `b83ec84428449465df3b459f1bc24b285045c812102a2052b1b7ce0f67e018f2` |
| `SOT-23.kicad_mod` | [Package_TO_SOT_SMD](https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c/Package_TO_SOT_SMD.pretty/SOT-23.kicad_mod) | `0d88c86c1b6d8c1aae4aa8c09386264c089d4451a128b6ccd63ed253f4300b15` |

PinHeader проверяет реальные PTH и отключённый `remove_unused_layers=no`.
MountingHole проверяет NPTH и механический контур `Cmts.User`.
SOT-23 содержит заполненный `fp_poly` на silk: тест проверяет сохранение
маркера pin 1 контуром и шестью перекрывающимися линиями, параметры pads/apertures
и привязку существующего STL. Это численная проверка, не GUI-валидация.

Для B.Cu тест создаёт **в памяти** вариацию R0805, заменяя внешние F.* слои
на B.* при неизменных координатах. Это проверка маршрутизации слоёв и apertures,
не эталон операции Flip KiCad и не проверка переворота/совмещения 3D.
Официальный R0805 fixture не изменяется.

Для переносимых unit tests временный STL-файл с метаданными также создаётся для
PinHeader и SOT-23. Отдельные optional integration tests проверяют реальные
существующие модели в соответствующих `.3dshapes` каталогах без чтения содержимого.

Результаты и команды: [малая контрольная выборка](../../docs/SMALL_SAMPLE_VALIDATION.md).

## Синтетический контроль заполненных окружностей

`FilledCircle_Control.kicad_mod` создан в этом проекте 2026-10-10 для численных
регрессий. Он не получен из KiCad Libraries и не описывает реальный компонент.
Содержит одну SMD rect площадку, reference/value и две заполненные окружности
радиуса 0.3 мм: F.SilkS с нулевой обводкой, B.SilkS с обводкой 0.04 мм.
3D-ссылки нет; отсутствие модели ожидается и явно отражается в отчёте.

SHA-256: `277830ab89f19aef0bb1a9922bcd46a1ec8dd4385f2b8e31da4bd1b9501dd518`.
Сохранён `output/FilledCircle_Control.fpl`; проверяются bytes, слои, pads,
динамические text fields, покрытие диска и погрешность границы. Это не GUI-эталон.

## Реальный контроль legacy-дуг

`Crystal_HC49-U_Vertical.kicad_mod` получен 2026-10-12 без изменений из
[официальной KiCad Libraries, tag 5.1.7](https://github.com/KiCad/kicad-footprints/blob/5.1.7/Crystal.pretty/Crystal_HC49-U_Vertical.kicad_mod).
Лицензия KiCad Libraries сохранена в `LICENSE.md`.
SHA-256: `e5d25be9e2933569e662963236dcef3fd606510d7ecc1b04dbef7fc3005e880c`.

Он содержит шесть дуг center/start/angle на F.Fab/F.SilkS и два PTH.
Сохранённый `output/Crystal_HC49-U_Vertical_2D.fpl` — явно 2D-контроль:
только при построении копии parser tree исключается source model с legacy
`at` units. Сам fixture не редактируется. Тест полного исходника проверяет
сохранение явного отказа для неподдерживаемого model record.

## Реальный контроль текстов D_SOD-123

`D_SOD-123.kicad_mod` получен 2026-10-12 без изменений из
[официальной библиотеки KiCad, ревизия 51f8a59](https://github.com/KiCad/kicad-footprints/blob/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c/Diode_SMD.pretty/D_SOD-123.kicad_mod).
Лицензия — KiCad Libraries из `LICENSE.md`.
SHA-256: `fd16785935b01254e1076f490e12f0f096da73cf087adefce51225585c62557a`.

Проверяются два roundrect pad, mask/paste, native fields, скрытые дополнительные
properties, unresolved/bound user reference и metadata существующей STL-ссылки.
`output/D_SOD-123.fpl` воспроизводится с defaults mask=0.05, paste=0/0.
B.*-вариант создаётся только в памяти; это проверка слоёв, не Flip или 3D.

После аудита текстов HC49-U 2D больше не содержит буквального `%R`:
исходная строка сохранена в fixture, user text пропущен с loss, как современная
неразрешённая `${REFERENCE}`. Контрольный `.fpl` обновлён только в этом месте.

## Контроль УГО

Каталог `symbols/` содержит целые, неизменённые официальные Mechanical и
Comparator из KiCad symbols 9.0.0 (commit a9012d8971ef2ea3243ffc9f19a5b4f153d8b334).
Источники/SHA256/bytes — `symbols/provenance.json`, лицензия/attribution —
`symbols/LICENSE.md`. Legacy контроль использует существующий
`KiCad/Pickit-cache.lib`; дубликаты PIC24 не исправляются в source.
См. [SYMBOL_CONVERTER.md](../../docs/SYMBOL_CONVERTER.md).

## Реальная запись компонента Схематора

`schemator/Detector_R3.component.txt` содержит точные bytes строк 507–528
существующего `FreePCB/detector/detector.cds`: resistor R3, два pin segments,
rectangle и attributes. Координаты, flags и CRLF не изменены. Whole-source
и fragment SHA256 записаны в `schemator/provenance.json` и проверяются тестом.
Это component fragment, не самостоятельный `.cds` для импорта. Отдельный
reader проверяет physical numbers/free-end Nodes и semantic roundtrip.
Новые R/C/CONN_01X06 controls в `output/symbols` генерируются из cache, а не
из этого фрагмента. См. [SCHEMATOR_CONVERTER.md](../../docs/SCHEMATOR_CONVERTER.md).

## Контроль связанных компонентов

`components/control.json` вручную назначает R/C/CONN_01X06 из cache точным
Resistor_SMD:R_0805_2012Metric, Capacitor_SMD:C_0805_2012Metric и
Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical. Это library bindings,
не восстановленные реальные BOM instances Pickit.

Новые целые C0805/PinHeader6 `.kicad_mod` получены без изменений из официальной
KiCad Libraries, pinned revision 51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c.
URL/SHA256/size — `components/provenance.json`, license — `LICENSE.md`.
Tests проверяют fixture bytes и весь component chain, используя opaque fake
STL bytes во временных каталогах; реальные models не нужны для unit tests.
Локальный runtime bundle использует только три существующие настоящие модели.
Правила: [COMPONENT_BUNDLE.md](../../docs/COMPONENT_BUNDLE.md).

## Реальный контроль curves УГО

Целые неизменённые Device (531 definitions) и Connector (397), той же KiCad
symbols 9.0.0 revision/license, дополнены в `symbols/`; provenance содержит
URL/bytes/SHA256. Они используются как source sample; не все definitions
поддержаны target writer. L/L_Small/C_Polarized_US/TestPoint/Conn_Coaxial и
legacy CP1/INDUCTOR дают семь воспроизводимых CDS/report controls.

`components/curves.json` задаёт modern L и legacy INDUCTOR → L0805, TestPoint
→ pad D1.0mm. Новые целые L0805/TestPoint footprints из pinned KiCad 51f8a59...
сохраняются без изменений; hashes/URL — `components/curves-provenance.json`,
license — `LICENSE.md`. TP source не имеет model reference: пакет строится с
explicit `--allow-missing-models`, его chain_complete false. Остальные два
bindings используют один existing STL. Models в unit tests — временные opaque
bytes; реальные meshes не читаются для geometry. [SYMBOL_CURVES.md](../../docs/SYMBOL_CURVES.md).

## Контроль электрических типов УГО

Пять `*_electrical` controls получены из неизменённой Device KiCad9:
Antenna/Antenna_Chip/DelayLine/Q_SCR_AGK/Speaker. Source names у них скрыты;
сохранены в JSON вместе с типами. Остальные обычные типы проверяются synthetic
modern/legacy probes, это не coverage всей библиотеки.

`components/electrical.json` вручную назначает SCR_AGK → SOT-23 и Speaker →
Speaker_CUI_CMR-1206S-67. Generic SCR binding проверяет number identity,
не пригодность корпуса конкретному компоненту. SOT-23 переиспользован без
изменений; Speaker footprint добавлен целиком из той же pinned KiCad 51f8a59...
URL/bytes/hashes — `components/electrical-provenance.json`; license — `LICENSE.md`.
В тестах models — temporary opaque bytes; runtime использует два существующих
STL. [Профиль и source evidence](../../docs/SYMBOL_ELECTRICAL.md).

## Контроль заливки и текста УГО

Шесть `*_body` controls созданы из целых unchanged Device KiCad9:
D_Filled/C_Polarized/Antenna_Shield/C_Network04/Ammeter_DC/FrequencyCounter.
Проверяются rectangles/polygons/circles, background occlusion loss и literal
A/Hz в native body descriptions. Source fill/text flags не редактируются.
Синтетические probes проверяют concavity, fill bound, text effects/legacy T.

`components/body.json` задаёт D_Filled → D_SOD-123 и Ammeter_DC → Header2.
Meter/header — тестовая привязка, не доказанная physical suitability прибора.
Новый PinHeader_1x02_P2.54mm_Vertical сохранён целиком из KiCad pinned 51f8a59...
URL/bytes/SHA256 — `components/body-provenance.json`, license — `LICENSE.md`.
Два real STL только копируются/хешируются; tests используют temporary opaque
bytes. [Правила и source evidence](../../docs/SYMBOL_BODY.md).

## Контроль disjoint multi-unit

Пять `*_units` controls получены из unchanged Device KiCad9:
R_Pack02_Split/R_Pack03_Split/R_Pack04_Split/R_Pack02_SIP_Split и
R_Potentiometer_Dual_Separate. Common graphics повторяются по views; disjoint
pin numbers сохраняются в одном ordinary component. Source symbols не
разбираются на отдельные физические детали. Shared/common pins отклоняются.

`components/units.json` назначает Array2/Array4 точным Resistor_SMD concave
footprints; SIP4 использует собственный source Footprint property. Новые целые
R_Array_Concave_2x0603/R_Array_Concave_4x0603/R_Array_SIP4 из pinned KiCad
51f8a59... сохранены без изменений; URL/bytes/SHA256 — `units-provenance.json`
в `components/`, license — `LICENSE.md`. Три existing STL только копируются.
Tests используют opaque temporary bytes, проверяют source/CDS/FPL identities
и relocation; physical suitability/GUI/netlist/hierarchy не подтверждены.
[Профиль и ограничения](../../docs/SYMBOL_UNITS.md).

## Контроль power/NC pins

Шесть `*_power` controls используют целые Device/Comparator KiCad9 definitions
и unchanged local Pickit-cache.lib: Fuse_Polarized/Opamp_Dual/LM393/LM311/
MCP1525/MCP601_8PIN. Последний сохраняет NC 1/5/8 как подключаемые terminals
только при explicit lossy policy; без неё ожидается отказ.

`components/power.json` назначает Comparator8/Amplifier8NC→DIP-8_W7.62mm и
Regulator3→SOT-23. Это тестовые bindings с подтверждённой number identity;
function, mechanical suitability, native import и 3D alignment не подтверждены.
Новый whole DIP footprint из pinned KiCad 51f8a59... сохранён без изменений;
URL/bytes/SHA256 — `components/power-provenance.json`, license — `LICENSE.md`.
SOT-23 переиспользован. Runtime копирует/хеширует два existing STL; unit tests
создают temporary opaque bytes и не разбирают mesh geometry.
[Power/NC policy и source evidence](../../docs/SYMBOL_POWER.md).

## Styled/hidden controls

Целая unchanged 74xGxx KiCad9 (174 definitions) добавлена в `symbols/`;
URL/bytes/hashes — `symbols/provenance.json`, license прежняя. Шесть real
controls и `components/pins.json` проверяют markers/hidden policy. Новый
whole SOT-23-5 из pinned KiCad51f8a59... имеет provenance в
`components/pins-provenance.json`; models не конвертируются. Тестовые bindings
не подтверждают physical suitability. [Профиль](../../docs/SYMBOL_PINS.md).

## Original common pins

Четыре unchanged Device networks имеют 3/4/7/13 logical units и original
common pin 1. `components/common.json` использует точные source Footprint
properties SIP4/SIP5/SIP8. SIP5/SIP8 сохранены целиком из pinned KiCad51f8a59;
URL/bytes/hashes — `components/common-provenance.json`, license прежняя.
3 existing STL только копируются/хешируются. [Профиль](../../docs/SYMBOL_COMMON.md).
