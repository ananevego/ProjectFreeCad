# KiCad → FreePCB2 2.428

Конвертер библиотечных footprint-файлов KiCad `.kicad_mod` в самостоятельные
библиотеки FreePCB2 `.fpl`. Написан на Python 3.10+, внешние зависимости не нужны.

**Статус:** разработка продолжается. R_0805_2012Metric, PinHeader PTH,
MountingHole NPTH, SOT-23 и численные
регрессии проверены автоматически. Загрузка/сохранение в FreePCB2 2.428 и
физическое совмещение STL в OpenSCAD ещё требуют отдельной Windows-валидации.
Есть также синтетический контроль заполненных окружностей на обоих silk-слоях.
Добавлены legacy-дуги KiCad и контроль HC49-U (явно 2D), аудит текстов,
D_SOD-123, пакетный CLI, исходный parser УГО и минимальный writer Схематора;
добавлен сборщик связей и переносимого комплекта, окружности/дуги УГО
и профиль обычных электрических типов выводов, простой заливки и текста;
добавлены disjoint multi-unit layout, power/NC policy и straight dash/dot profile;
проходят 478 тестов.
Source parser читает `.kicad_sym` и старые `.lib`, сохраняя pins/units/inheritance.
Writer создаёт `.cds` для R/C/connector, составных resistor packs и физических компонентов с power pins. Проверена цепочка
symbol → footprint → существующий STL на трёх controls; GUI и физическое
совмещение 3D ещё впереди.

## Исходные УГО KiCad

```sh
python3 -B -m src.symbol_converter KiCad/Pickit-cache.lib output/symbols/Pickit-cache.inspect.json
python3 -B -m src.symbol_converter tests/fixtures/symbols/Comparator.kicad_sym \
  output/symbols/Comparator.inspect.json --symbol LM393 --symbol LM339
```

Эти команды создают JSON исходных УГО.
Поддержаны секции/общие body styles, наследование и aliases. Конфликты pins
сохраняются с диагностикой: у PIC24 в локальном cache номера 1–16 повторены
по восемь раз, поэтому первый запуск возвращает 2 и сохраняет отчёт.
Официальные Mechanical/Comparator KiCad 9.0.0 и legacy cache проверены автоматически.
Правила: [SYMBOL_CONVERTER.md](docs/SYMBOL_CONVERTER.md).
Исследование target: [SCHEMATOR_FORMAT_RESEARCH.md](docs/SCHEMATOR_FORMAT_RESEARCH.md).

## УГО Схематора

```sh
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/R_control.cds --symbol R
```

Отдельный CLI создаёт один компонент `.cds` 1.429 (CP1251) и JSON losses.
Поддержаны видимые прямые pins девяти обычных electrical types и
rectangles/polylines/circles/arcs, ограниченная foreground
заливка и literal body text, disjoint units и power terminals.
Повторяющиеся pin records, native hierarchy и неподдерживаемая графика остаются ограничениями.
Сохранены R/C/CONN_01X06 controls. Контракт ограниченного профиля проверен по
исходникам и реальной записи R3; отдельный reader проверяет emitted records.
Загрузка и connectivity в Схематоре пока не подтверждены.
Без `--footprint-name` используется placeholder `PART`; назначение имени
не подтверждает соответствие pads. `--strict` отклоняет известные layout losses.
Команды, ограничения и коды выхода: [SCHEMATOR_CONVERTER.md](docs/SCHEMATOR_CONVERTER.md).

`--curve-tolerance 0.01` задаёт mm-допуск для centerline аппроксимации curves,
включая NM rounding. Сохранены семь реальных curve controls; legacy arc
resolution учитывает explicit endpoints/swap и отдельно показывает radius/
endpoint changes. Правила: [SYMBOL_CURVES.md](docs/SYMBOL_CURVES.md).

Input/output/bidirectional/tri_state и другие обычные типы передаются как
нумерованные endpoints с явной потерей ERC; source types остаются в JSON.
Alternate pins пока отклоняются. Добавлены
пять реальных УГО и две linked chains SCR/Speaker с готовыми STL.
Профиль, отчёты и команды: [SYMBOL_ELECTRICAL.md](docs/SYMBOL_ELECTRICAL.md).

Foreground rectangles/closed simple polygons/circles покрываются straight
strokes с fill bound, default `--fill-tolerance 0.01`. Background передаётся
только как boundary с occlusion loss; modern graphic text/legacy T — как
body description с font/layout losses. Добавлены шесть real controls и две
linked chains diode/meter. [Правила и проверки](docs/SYMBOL_BODY.md).

2–16 секций с disjoint physical numbers размещаются рядом в одном native
component; independent placement/unit suffixes имеют explicit loss. Common
graphics повторяются; original common pins требуют явного режима отдельной view. `--unit-gap` default
2.54 mm; пять real controls и три array/SIP chains проверены. Native merge/
hierarchy не генерируется. [Профиль и ограничения](docs/SYMBOL_UNITS.md).

Power_in/power_out передаются как нумерованные terminals с явной потерей
power/ERC rules. No-connect по умолчанию отклоняется; явный
`--no-connect-policy connectable-with-loss` сохраняет NC как подключаемый pin
с отдельной диагностикой. Power sections LM393 и шесть real controls проверены;
три chains DIP-8/SOT-23 используют два существующих STL. Native запрет NC
не реализован. [Политика и источники](docs/SYMBOL_POWER.md).

Inverted/clock и другие pin markers переносятся отдельной body graphics.
Hidden pins default reject; `--hidden-pin-policy reveal-with-loss` раскрывает
terminals с потерей visibility/implicit global nets. Шесть real controls и
пять chains проверены. [Профиль и ограничения](docs/SYMBOL_PINS.md).

Original unit=0 pins при `--common-pin-policy common-view-with-loss`
размещаются один раз в отдельной view того же component. Четыре real networks
и три source-property SIP chains проверены; повторяющиеся source records
отклоняются. [Политика и проверки](docs/SYMBOL_COMMON.md).

## Связи и переносимый комплект

```sh
python3 -B -m src.component_converter tests/fixtures/components/control.json \
  output/components/control
python3 -B -m src.component_converter --verify output/components/control
```

Точные identifiers и pin/pad numbers проверяются до генерации и по записанным
CDS/FPL. Комплект содержит R0805/C0805/Header6 и только их существующие STL:
исходное дерево категорий и уникальные flat aliases для одной OpenSCAD папки.
SHA256 подтверждает неизменность копий; geometry/GUI/netlist не проверены.
Выход должен быть новым каталогом. Missing/ambiguous bindings остаются в manifest;
STL не конвертируются повторно. Скопированный комплект проверяется без исходников.
Правила и настройка Windows-папки: [COMPONENT_BUNDLE.md](docs/COMPONENT_BUNDLE.md).

Для проверки в целевых программах добавлен переносимый **native validation kit**:
8 bundles/24 компонента, 5 standalone FPL controls, 15 aliases существующих STL,
10 negative controls и 10 manual scenarios. Checker работает без repo и model
store; original inputs и результаты отделены. Native flags остаются false,
пока GUI/netlist/Gerber/board 3D не проверены фактически.

```sh
python3 -B -m src.native_validation output/native-validation-ready
python3 -B output/native-validation-ready/verify_kit.py
python3 -B output/native-validation-ready/verify_kit.py --init-results results/run.json
```

Для копии repo без моделей доступен `--allow-missing-models`: это явно partial
kit с `ready_for_3d_checks=false`. [Комплект, архив и протокол](docs/NATIVE_VALIDATION.md).

## Пакетная обработка

```sh
python3 -B -m src.footprint_converter.batch tests/fixtures output/batches/control --limit 7
python3 -B -m src.footprint_converter.batch tests/fixtures output/batches/control --limit 7 --resume
```

Каждый footprint получает отдельный FPL/report, стабильное имя и запись в manifest.
Ошибки изолированы; resume проверяет source/options/engine/models и хеши artifacts.
В текущей партии 6 из 7 файлов генерируются с известными потерями; старый HC49-U
получает ожидаемый отказ legacy model(at), поэтому CLI возвращает 2.
GUI и полная библиотека этим прогоном не проверены.
Подробные правила и параметры: [BATCH_CONVERTER.md](docs/BATCH_CONVERTER.md).

Средняя pinned партия: 120 footprints из 12 категорий, 110 FPL с losses и
10 явных отказов (91.67% в этой выборке). Technical mask/paste-only pads и
contact pads добавлены по source/native контракту. Новый read-only audit
проверяет source/FPL records, hashes и отдельно отмечает ambiguous numbers.
[Результаты, ограничения и команды](docs/FOOTPRINT_MEDIUM.md).
Тип stroke `default` исправлен как solid. Dash/dot/dash_dot/dash_dot_dot
для незаполненных линий/прямоугольников/простых полигонов переносятся отдельными
отрезками по фиксированному KiCad9 PCB editor profile с loss; strict отклоняет
его. Кривые и filled patterned outlines остаются отказом.
[Контракт и результаты этапа](docs/FOOTPRINT_STROKES.md).
Добавлен точный перенос custom pads, чьи anchor и прямоугольные примитивы
доказуемо образуют один центрированный прямоугольник. Slots, nonzero offsets
и непрямоугольные unions имеют структурированные причины отказа; средняя
партия остаётся 110/120. [Ограничения native pads](docs/PAD_GEOMETRY.md).

## Что поддерживается

| Данные KiCad | Результат |
|---|---|
| Technical-only F/B.Mask/Paste SMD pads | Отдельные zero-copper/hole padstack carriers, literal aperture sizes; netlist/Gerber unverified |
| Contact pads (`connect`) | Одна внешняя copper side, mask/no paste/no hole; connector attribute имеет loss |
| Custom SMD → exact centred rectangle | До 32 rectangular gr_poly; exact union proof, source anchor сохранён, explicit aperture settings и editing/zone loss |
| SMD circle / rect / oval / roundrect | Соответствующая форма и размеры, без перестановки X/Y |
| F.Cu / B.Cu | Верхняя / нижняя площадка |
| PTH с круглым drill | Отверстие и площадки; `*.Cu` включает общий inner_pad |
| NPTH с круглым drill | Отверстие без меди; NPTH paste подавляется с диагностикой |
| Origin | Сохраняется; ось Y приводится к системе FreePCB2 |
| Centroid | Вычисляет native reader FreePCB2 по bounds площадок |
| F.SilkS / B.SilkS | Раздельные слои 4 / 5 |
| Dwgs.User / Cmts.User | Контуры и user texts в notes=7 с диагностикой потери различия слоёв |
| Линии, незаполненные прямоугольники и полигоны | Контуры `.fpl` |
| Заполненные простые полигоны и прямоугольники | Контур и перекрывающиеся линии с ограниченным расширением, явная аппроксимация |
| Заполненные окружности | Адаптивная граница и перекрывающиеся линии; покрытие диска и ограниченная погрешность |
| Окружности, современные и legacy-дуги | Отрезки с задаваемой точностью, по умолчанию 0.01 мм; старые дуги center/start/signed angle |
| Reference / value / user texts | Параметры и тексты с явной диагностикой ограничений |
| Mask/paste margins | Pad → footprint → явные defaults; размер и скругление aperture |
| Ссылка KiCad `.3dshapes` | Поиск уже существующего STL, код OpenSCAD; без конвертации моделей |

Fab переносится в слой notes как приближение, courtyard пропускается.
Остальные custom/chamfer/trapezoid pads, настоящие slots и nonzero pad offsets, отдельные InN.Cu,
дробные углы, заполненные дуги, полигоны с отверстиями/самопересечениями,
legacy model `(at ...)` и асимметричный
paste roundrect пока не поддерживаются. Непредставимая геометрия вызывает ошибку.
Oval drill с равными осями и explicit zero offset допускаются как та же
круглая геометрия; source spelling сохраняется в JSON.
Полный контракт: [docs/FOOTPRINT_CONVERTER.md](docs/FOOTPRINT_CONVERTER.md).

## Быстрый запуск

Из корня репозитория:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/R_0805_2012Metric.kicad_mod \
  output/R_0805_2012Metric.fpl \
  --report output/R_0805_2012Metric.report.json
```

На Windows используйте `py -3` вместо `python3`; команду можно записать в одну
строку. Вход — UTF-8; `.fpl` по умолчанию — CP1251, отчёт — UTF-8 JSON.

Из корня репозитория также доступен `python3 -B -m src.footprint_converter`
с теми же аргументами. Старый скрипт можно запускать по абсолютному пути из
другого каталога; прежний Python API `convert` сохранён.

Основные тесты запускаются и в новом клоне без 3D-каталогов: они используют
временный файл только для проверки метаданных matcher, а не геометрию STL.
Отдельный интеграционный тест использует реальный R0805 STL, когда он доступен;
аналогичная проверка есть для PinHeader и SOT-23. При отсутствии моделей эти проверки
явно пропускаются. Численные unit tests продолжают работать.

В `output/` также сохранены PTH/NPTH примеры. Их параметры и воспроизводимые
команды: [малая контрольная выборка](docs/SMALL_SAMPLE_VALIDATION.md).
SOT-23 теперь преобразуется с сохранением заполненной silk-метки pin 1.
Самопересекающийся polygon вызывает ошибку и не заменяет прежний выходной файл.

Для реальной 3D-привязки положите **существующий** файл по пути:

```text
stl_files/Resistor_SMD.3dshapes/R_0805_2012Metric.stl
```

Либо укажите корень имеющегося набора через `--stl-root /path/to/stl_files`.
Без файла конвертер сгенерирует `.fpl` с `MODEL_MISSING` в отчёте, без `import`.
Он не создаёт модели и не ищет совпадение только по basename.

## Отчёт и строгий режим

`--report` сохраняет целевую ревизию, counts, исходные тексты, настройки apertures,
3D-связи и diagnostics. `loss` означает потерю информации, `assumption` —
непроверенное допущение, `approximation` — ограниченную аппроксимацию.

| Код завершения | Значение |
|---|---|
| 0 | Файл сгенерирован; возможные потери перечислены в отчёте |
| 1 | Ошибка чтения, преобразования или записи |
| 2 | `--strict` запретил результат из-за известных потерь; старый `.fpl` сохранён |

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --strict --report output/part.report.json
```

`--strict` допускает указанные в отчёте допущения и ограниченную аппроксимацию;
это не подтверждение корректности в GUI. Для текущего R0805 строгий запуск
завершится кодом 2 из-за courtyard/Fab/text. Сохранённый контрольный `.fpl`
предназначен для дальнейшей валидации, а не объявляется готовой библиотекой.

## Настройки mask/paste

Margins задаются **на сторону**, в мм; ratio — доля, например `-0.05`.
Размер paste: `X + 2*(margin + X*ratio)` и аналогично для Y.

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0 \
  --report output/part.report.json
```

Параметры defaults должны соответствовать выбранным настройкам исходного проекта.
Pad overrides footprint; footprint overrides CLI defaults; явный ноль сохраняется.
Если обе настройки paste отсутствуют, используется FreePCB DEFAULT=99 с
диагностикой зависимости от target project. Если известна лишь одна — другая
считается нулём с диагностикой потери, запрещённой в `--strict`.
Положительный margin rect создаёт roundrect; равномерный margin roundrect
меняет радиус. Схлопнувшаяся aperture записывается как NONE.

## Тексты и 3D

Нативный `.fpl` хранит параметры reference/value, но не их actual content и
независимый слой. Значение компонента необходимо задать при размещении.
Неразрешённые `%R`/`%V`, `${REFERENCE}` и другие user text variables пропускаются с
диагностикой; исходные строки сохраняются в JSON.

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --text-variable REFERENCE=R1 --text-variable VALUE=10k
```

Такая подстановка создаёт **статический** текст. Она не создаёт динамическое поле
FreePCB2. Точное совпадение шрифта и baseline пока не обеспечено.

## Заполненные полигоны

Для `fp_poly` и `fp_rect` с `fill solid` (также `fill yes`) сохраняется исходный
контур, а внутренность покрывается перекрывающимися линиями. Native hatch не
используется. `--fill-tolerance MM` задаёт допустимое расширение записанной
геометрии, по умолчанию 0.01 мм, с учётом округления на сетку FreePCB2.
Нулевая/слишком тонкая исходная обводка расширяется в пределах этого допуска.

`fp_circle` с `fill solid`/`yes` тоже поддерживается. Исходные center/end/width
сохраняются до выбора толщины заполнения. Допуск хорды автоматически ограничен
четвертью этой толщины: так покрывается весь исходный диск, включая области вне
вписанного многоугольника. Для ненулевой исходной обводки отклонение внутрь
ограничено `--curve-tolerance`, расширение наружу — `--fill-tolerance`; общая
погрешность границы не больше максимума этих двух допусков в идеальной модели.
При допусках по умолчанию это 0.01 мм. Контрольный пример:

```sh
python3 -B -m src.footprint_converter \
  tests/fixtures/FilledCircle_Control.kicad_mod output/FilledCircle_Control.fpl \
  --report output/FilledCircle_Control.report.json
```

Это синтетический тест геометрии, без модели; `MODEL_MISSING` ожидаем.
Он не является реальным компонентом KiCad или подтверждением GUI-импорта.

Граница проверена численно **в модели круглых концов линий**. `FILL_APPROXIMATED`,
`FILL_STROKE_MODEL` и `FILL_EXPORT_UNVERIFIED` отражают аппроксимацию и ограничения.
Растеризация GUI и Gerber не проверены; минимальная толщина silk в настройках
FreePCB2 может увеличить линии. Допуск конвертера не гарантирует такой же допуск
на готовом Gerber. `--strict` допускает эту ограниченную аппроксимацию и явно
отмеченные допущения, как для существующих кривых.

Поддерживается один простой контур без отверстий, в том числе вогнутый.
Лимиты: 512 вершин на polygon/границу circle, суммарно 4096 линий заполнения
и границ на footprint. Чрезмерная детализация окружности также вызывает ошибку.
Самопересечения, самокасания и геометрия, схлопнувшаяся на целевой сетке,
вызывают ошибку. Подробности: [контракт заполнения](docs/FOOTPRINT_CONVERTER.md#заполненные-полигоны).

## Настройка и проверка 3D

STL frame по умолчанию identity с `MODEL_FRAME_UNVERIFIED`. Его можно явно задать
через `--model-translation X Y Z`, `--model-rotation X Y Z`, `--model-scale X Y Z`.
Это полное target-преобразование, заменяющее исходный model transform;
неединичные KiCad 3D transforms без явной настройки отвергаются.

Для будущей проверки R0805 в FreePCB2 2.428 выставить единицы проекта **MM** и
«Папка для Openscad» на Windows-копию `stl_files\Resistor_SMD.3dshapes`.
Загружать footprint целиком через библиотеку при добавлении детали; затем
редактировать footprint выбранной детали и сохранять `.fpl`/`.fpc`.
Меню «Импорт футпринта» добавляет геометрию группой и не проверяет полный roundtrip.

## Структура

- `src/kicad_to_freepcb_footprint.py` — совместимый Python/CLI entry point.
- `src/footprint_converter/` — реализация: `parser.py`, `model.py`,
  `geometry.py`, `format_rules.py`, `validation.py`, `model_matching.py`,
  `writer.py`, `reporting.py`, `pipeline.py`, `io.py`, `cli.py` и `errors.py`.
  Parser разбирает источник, matcher проверяет только пути и метаданные моделей,
  writer формирует строку `.fpl`; запись на диск выполняется отдельно.
- `tests/` — численные и структурные регрессии; `tests/fixtures/` — контрольный
  KiCad footprint с происхождением и лицензией KiCad Libraries.
- `output/` — контрольный `.fpl`; JSON-отчёты генерируются локально и не коммитятся,
  поскольку содержат пути конкретного компьютера.
- `FreePCB/`, `Эталон R_0805_2012Metric/` — прежние демонстрационные проекты.
- `stl_files/`, `step_files/` — ранее полученные модели, доступны отдельно
  (в том числе на Яндекс Диске), исключены из Git. Не пересоздавать их.
- STEP → STL скрипты в корне — история предыдущей конвертации;
  запускать их для использования footprint-конвертера не требуется.

[План дальнейшей работы](docs/PROJECT_PLAN.md): расширение небольшой реальной
выборки, уточнение оставшихся правил, УГО по подтверждённому эталону, затем batch.
Массовая конвертация 20 000 элементов на текущем этапе не выполняется.

Правила hide/formatting/unlocked и проверки текстов: [аудит](docs/TEXT_FIELD_AUDIT.md).
