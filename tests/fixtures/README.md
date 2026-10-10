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
