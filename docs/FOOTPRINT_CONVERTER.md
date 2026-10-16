# KiCad → FreePCB2 2.428: текущая версия

Статус: автоматически проверяются R0805, PinHeader PTH, MountingHole NPTH и
SOT-23. Загрузка, сохранение и 3D в GUI FreePCB2 пока не проверены.
Синтетический FilledCircle_Control проверяет заполненные окружности на обоих silk-слоях.
Конвертер не читает геометрию моделей, не конвертирует STEP/STL, не копирует модели
и не изменяет каталоги их хранения. Batch/resume проверены на полном корпусе
15 464 footprints; [аудит и preview-поставка](FULL_LIBRARY.md). GUI ещё не проверен.

## Запуск

Требуется Python 3.10+; внешних Python-зависимостей нет.
Optional integration tests проверяют существующие STL R0805, PinHeader и SOT-23
по путям из fixtures. Unit tests работают без моделей на временных metadata-only
файлах. При отсутствии соответствующего STL integration test явно пропускается,
модель не пересоздаётся.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/R_0805_2012Metric.kicad_mod output/R_0805_2012Metric.fpl \
  --report output/R_0805_2012Metric.report.json
```

Вход UTF-8, выход по умолчанию CP1251 для Windows-версии 2.428.
`--encoding` позволяет явно выбрать другую кодировку.
`--description-policy ascii-escape-with-loss` явно заменяет Unicode/кавычки/
control characters только в description печатными `[U+XXXX]` с loss и сохранением
оригинала в JSON. Default `preserve` сохраняет прежнее поведение. Поддержаны
также footprints с нулём площадок и представимой графикой; выводы не добавляются.
Ошибка преобразования обнаруживается до записи `.fpl`. Файлы заменяются
атомарно по отдельности; общей транзакции для `.fpl` и JSON нет. CLI запрещает выход внутри
`stl_files`, `step_files`, выбранного `--stl-root` и поверх входного файла.
Старый публичный интерфейс `convert(root, footprint_name) -> (text, warnings)`
сохранён. Файл скрипта служит совместимым entry point; реализация вынесена в
пакет. Из корня репозитория возможен запуск `python3 -B -m src.footprint_converter`
с теми же аргументами и кодами завершения. Абсолютный путь к старому скрипту
работает из другого каталога.

## Разделение ответственности

Реализация находится в `src/footprint_converter/`:

| Модуль | Ответственность |
|---|---|
| `parser.py` | `parse_sexpr`, `parse_footprint`, pads, texts и исходные graphics |
| `model.py` | Внутренняя модель в мм и системе KiCad; настройки apertures и 3D |
| `format_rules.py` | Формы и слои 2.428, углы, координаты, числа и quoted fields |
| `geometry.py` | Дуги, окружности, проверка контура на целевой сетке и подготовка заполнения |
| `validation.py` | Проверка возможности представить внутреннюю модель в поддержанном target subset |
| `model_matching.py` | Сопоставление существующих STL по путям/метаданным, явный 3D transform и код OpenSCAD |
| `writer.py` | Apertures, текстовые подстановки, bounds и сериализация `.fpl` в строку |
| `reporting.py` | Категории диагностик, исходные данные и структурированный JSON-compatible отчёт |
| `pipeline.py` | Последовательность parser → validation → geometry → matcher → writer → report; strict policy |
| `errors.py` | Ошибки конвертации и strict rejection с отчётом |
| `io.py` | Защита путей и атомарная замена одного выходного файла |
| `cli.py` | Аргументы, кодировки, запись `.fpl`/JSON и коды завершения |

`convert_detailed` работает в памяти; matcher обращается только к метаданным
существующих файлов. CLI и `io.py` отвечают за запись результатов.
Старый скрипт реэкспортирует API пакета, включая классы и вспомогательные функции;
при смешивании старых и новых импортов используются одни и те же классы.

После разделения на модули все четыре сохранённых `.fpl` побайтово воспроизводимы.
Сравнение с предыдущей реализацией также подтвердило прежние предупреждения и
полные отчёты на этих примерах. Тесты проверяют CLI обоими способами, коды 0/1/2,
сохранение прежнего файла при ошибке и importlib/запуск из другого каталога.

## Проверенный по исходникам контракт 2.428

Целевая ревизия: `3af0f9b9a234c97f2d21455c936abeb8439d2d45` (`ver28`).
В `FreePcbDoc.cpp:216` установлена версия `2.428`.

Источники:

- [Shape.h: pad shapes и padstack](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.h#L16)
- [Shape.cpp: чтение .fpl](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1134)
- [Shape.cpp: запись .fpl](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L2021)
- [layers.h: footprint layers](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/layers.h)
- [DlgAddCode.cpp: шаблон OpenSCAD](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/DlgAddCode.cpp#L32)
- [Shape.cpp: экспорт/копирование STL](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L4676)

| Данные | Правило первой версии |
|---|---|
| Библиотека | Отдельный `.fpl`, `name:` в нулевой колонке; секция `[footprints]` не требуется |
| Единицы | `NM`, округление на сетку 10 нм целевого reader; проверка диапазона signed int32 |
| Origin | Сдвига нет; `(x,y)` KiCad → `(x,-y)` FreePCB2 |
| Угол pad/text | KiCad CCW → FreePCB clockwise: `-angle mod 360`; дробные углы отвергаются |
| Pad | `shape size_Y half_X half_X radius`; X/Y не переставляются |
| Формы | circle=1, rect=3, roundrect=4, oval=5; radius=`rratio*min(X,Y)` |
| Медь | F.Cu→top, B.Cu→bottom; PTH `*.Cu`→top+inner+bottom |
| Inner | Шесть чисел, включая connect_flag=0; один общий внутренний padstack. Отдельные InN.Cu отвергаются |
| NONE | Явный top_pad=0 обязателен для отсутствия верхней меди: отсутствие записи означает круг 1 мм |
| PTH | Круглое отверстие в `pin`, исходные размеры медных площадок сохраняются |
| NPTH | Круглое отверстие, все copper shapes=0, paste=0; безымянному отверстию даётся служебное имя |
| Silk | F.SilkS→4, B.SilkS→5; линии, незаполненные прямоугольники/полигоны, окружности и современные дуги start/mid/end |
| Filled polygon/rectangle | Простой контур + перекрывающиеся линии, hatch=0; ограничение расширения `--fill-tolerance` и явная диагностика |
| Filled circle | Исходная окружность сохранена в модели/отчёте; граница адаптируется к толщине заполнения; исходный диск покрыт в идеальной stroke model |
| Fab | F.Fab→notes top=7, B.Fab→notes bottom=8; это явно выбранное приближение |
| User drawing/comments | Dwgs.User и Cmts.User→notes=7; графика и user texts сохраняются, различие source layers теряется с `USER_LAYER_APPROXIMATED` |
| Courtyard | Пропускается с диагностикой, отдельного соответствия пока нет |
| Reference/value | Позиция, угол, размер, толщина и скрытие из источника; строки являются свойствами компонента, `.fpl` хранит только параметры динамических полей |
| User text | Текст, позиция, угол, размер, толщина, зеркало, слой; скрытые тексты не выводятся |
| Centroid | Запись опущена: FreePCB2 `MakeFromFile` вызывает `GetDefaultCentroid`, центр bounds всех padstack |
| Selection | Bounds площадок, отверстий и явных apertures с учётом вращения, линий с толщиной; GUI может пересчитать после отрисовки |
| Mask/paste | Отсутствующий слой→NONE=0; явные margins→рассчитанная геометрия, неизвестные настройки→DEFAULT=99 с диагностикой |

Окружности и дуги аппроксимируются отрезками с максимальным отклонением хорды
`--curve-tolerance` (по умолчанию 0.01 мм, включая запас на округление координат).
На одну кривую разрешено до 4096 сегментов. Концы дуги сохраняются точно до сетки
10 нм, направление определяется по start/mid/end, включая дуги больше 180°.
Legacy дуги centre/angle, вырожденные/заполненные дуги и Bezier пока
не поддерживаются. Fab→notes помечается как изменение семантики слоя, а не
как точное соответствие. Courtyard пропускается с явной потерей.

Численные проверки в тестах выполняются независимым разбором выходных записей,
включая количество параметров и pin count. Это не запуск native reader/GUI.

`remove_unused_layers` и `keep_end_layers` с явным `no` разрешены: они не меняют
padstack. `yes` или отсутствие аргумента включают режим, зависимый от платы,
и пока отвергаются. Неверные значения и повтор одного флага тоже вызывают ошибку.
Правило проверено по [парсеру KiCad](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L7663).

Реальные PTH/NPTH/SOT-23 примеры и проверки отказов описаны в
[SMALL_SAMPLE_VALIDATION.md](SMALL_SAMPLE_VALIDATION.md). Вариант B.Cu является
тестом слоёв, а не подтверждённым эталоном KiCad Flip или 3D.

## Существующий R0805 STL

Сопоставление использует ссылку `(model ...)`, выделяет точную категорию
`.3dshapes` и имя модели, меняет расширение на `.stl`, проверяет путь и наличие
непустого файла. STEP/WRL/STL используются только как ссылки, файлы не открываются.
Поиск только по basename или названию footprint не выполняется.

Для R0805:

```text
${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.step
→ stl_files/Resistor_SMD.3dshapes/R_0805_2012Metric.stl
→ openscad_code: "  import(`R_0805_2012Metric.stl`);"
```

В версии 2.428 копирование при OpenSCAD-экспорте использует
`3d_folder + basename` → `related_files/openscad + basename`. Поэтому в Windows
надо выставить «Папка для Openscad» на каталог существующих моделей
`stl_files\Resistor_SMD.3dshapes`, а единицы проекта — MM. Ссылку с подкаталогом
не используем: в 2.428 копирование не создаёт дерево каталогов назначения.
Для моделей из нескольких категорий первая версия выдаёт ошибку, поскольку
одной общей `3d_folder` и плоских basename недостаточно.

Первые `translate`/`scale` строки сохраняют нативный шаблон автонастройки.
Внутренние translate/rotate/scale задаёт `ModelTransform`. По умолчанию используется
identity с обязательной диагностикой `MODEL_FRAME_UNVERIFIED`: единицы,
ориентация, масштаб и физическое совмещение предыдущих STL ещё не доказаны.
Преобразование 2D Y не применяется автоматически к 3D: системы координат KiCad
2D и его модели различаются. Неединичные source 3D transforms без явной настройки
отвергаются, чтобы не угадывать знак/порядок вращений и единицы.

Явное полное преобразование для эксперимента задаётся через
`--model-translation X Y Z`, `--model-rotation X Y Z`, `--model-scale X Y Z`.
Порядок над геометрией: scale, rotate, translate. Настройка заменяет исходный
model transform, а не добавляется к нему. Она не считается автоматически
верной; нужна ручная проверка.

## Ограничения и следующий шаг

- Native ref/value не имеют в `.fpl` отдельных layer/mirror и literal content.
  Value из F.Fab переносится в native value field с предупреждением. При
  размещении компонента его actual value надо задать отдельно.
- Сохраняем численную позицию текста; шрифт FreePCB2 и его baseline отличаются
  от центральной привязки KiCad. Точная визуальная компенсация не реализована.
- `${REFERENCE}` и другие неразрешённые переменные больше не выводятся буквально:
  текст пропускается с диагностикой потери. Исходная строка сохраняется в JSON.
  `--text-variable REFERENCE=R1` позволяет явно зафиксировать текстовую подстановку;
  такая строка будет статической, не динамическим reference размещённой детали.
- `.fpl` не содержит явного plating flag. NPTH проверен как отверстие без меди;
  поведение fabrication/drill output надо проверить в целевой программе.
- Явные mask/paste margins переносятся; настройки исходной платы не содержатся
  в `.kicad_mod`. Неизвестные настройки нельзя объявлять восстановленными.
  Асимметричный margin для roundrect пока отвергается.
- Custom/trapezoid/chamfer pads, oval/offset drills, fractional angles, индивидуальные
  inner layers отвергаются с ошибкой. Неизвестная графика пропускается с диагностикой.
- Нет утверждения о GUI-совместимости по одному только чтению выходного файла.

Аудит основных text/layer правил выполнен; следующий шаг — batch CLI на малой
выборке. При доступной Windows выполнить отдельный
контрольный roundtrip и OpenSCAD-экспорт. Загружать footprint целиком через выбор
библиотеки при добавлении компонента, далее редактировать footprint выбранной
детали и «Сохранить как...». Меню «Импорт футпринта» в редакторе добавляет группу
геометрии и не подходит для проверки полного переноса метаданных/3D.
Проверить оба pads, centroid=(0,0) для симметричного R0805, слой и baseline текстов,
путь копирования STL, размеры/ориентацию/высоту модели. Сохранить `.fpl` и `.fpc`
средствами FreePCB2 и сравнить. До этого массовый прогон не выполнять.

## Отчёт и строгая конвертация

`--report path.json` записывает UTF-8 JSON schema_version=1 с целевой ревизией,
параметрами координат, количеством записей, исходными текстами, найденными STL,
выбранным 3D transform и diagnostics. JSON сохраняет исходную информацию для
анализа, но не восстанавливает её автоматически в FreePCB2.

Серьёзность diagnostics:

- `loss`: пропущенная/непредставимая информация, отсутствующая 3D-связь,
  изменение source layer (например, Fab→notes).
- `assumption`: 3D frame, baseline текста, ограничение NPTH, требующие проверки.
- `approximation`: кривые с заданным численным пределом ошибки.
- `info`: прочие сведения о преобразовании.

Код завершения 0 означает генерацию с возможными потерями, отражёнными в отчёте.
Код 1 — ошибка чтения/преобразования/записи. `--strict` запрещает известные потери:
код 2, `status=rejected_loss`, существующий `.fpl` остаётся прежним; JSON при этом
содержит причины отказа. Строгий режим допускает ограниченную аппроксимацию и
явно отмеченные допущения. Поэтому даже `--strict` не означает GUI-валидацию.
При успешной генерации статус `generated` или `generated_with_loss`.
Текущий R0805 имеет `generated_with_loss`, поскольку courtyard/Fab/text ещё
нельзя полностью перенести. Это не скрывается при объявлении успеха.

При ошибке записи отчёт получает `failed`; старый `.fpl` сохраняется, если его
атомарная замена не состоялась. Сбой очистки/записи отчёта выводится отдельно.
Защита model storage и входного файла применяется также к пути JSON-отчёта.

## Mask/paste apertures

`ApertureSettings` хранит независимые mask_margin, paste_margin, paste_ratio.
Приоритет каждого поля: pad → footprint → явные CLI defaults. `None` означает
отсутствие настройки, ноль является явным значением в поддерживаемом профиле.

Формулы подтверждены по KiCad source revision
`82b216ea7debfff69519e317dacb1b042cbdee65`:
[GetSolderPasteMargin](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pad.cpp#L2145),
[plotting mask/paste](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/plot_board_layers.cpp#L440).

- mask: `X'=X+2*m`, `Y'=Y+2*m`.
- paste: `mx=m+X*r`, `my=m+Y*r`, затем `X'=X+2*mx`, `Y'=Y+2*my`.
- Положительный margin rect создаёт roundrect с radius=mx, ограниченным размером.
- Равномерный margin roundrect меняет radius на `max(0, radius+margin)`.
- Асимметричный margin roundrect явно отвергается: historical и современные
  KiCad-версии имеют разные corner policies; приближение не выдаётся за точный перенос.
- Circle/oval сохраняют поддерживаемую форму с новыми размерами.
- Схлопнувшееся отверстие mask/paste записывается как NONE, не как нулевая copper pad.
- Technical-only NPTH mask без source copper layers использует исходный размер,
  без expansion, как GetSolderMaskExpansion KiCad. NPTH paste подавляется с loss.

Это зафиксированный профиль геометрии apertures по указанной ревизии KiCad;
старые версии могут иначе скруглять углы. GUI/manufacturing validation в целевых
программах всё ещё требуется.

## Заполненные полигоны

По ревизии FreePCB2 2.428:

- [Shape.cpp:1362](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1362)
  читает `outline_polyline` и hatch; `outline_polygon` выбирает DIAGONAL_FULL.
- [PolyLine.h:57](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/PolyLine.h#L57)
  задаёт NO_HATCH=0, DIAGONAL_FULL=1, DIAGONAL_EDGE=2.
- [PolyLine.cpp:1687](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/PolyLine.cpp#L1687)
  рисует footprint hatch линиями с алгоритмом spacing/пропуска коротких spans.
  Ветка DL_POLYGON относится к ID_BOARD; footprint имеет ID_OUTLINE.
- [Shape.cpp:2102](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L2102)
  сохраняет толщину, координаты, hatch, layer, corners и закрытие контура.
- [Gerber.cpp:2846](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Gerber.cpp#L2846)
  выводит part-outline strokes круглой aperture; minimum silk width может
  увеличить толщину, а слишком тонкие линии могут быть пропущены.

Поэтому hatch=1 не объявляется эквивалентом KiCad solid fill. Вместо этого
`fp_poly`/`fp_rect` с `fill solid` или историческим `fill yes` сохраняются как
`FilledPolygon`. Alias подтверждён [парсером KiCad](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L4153).

`tessellate_fills` отдельно создаёт замкнутую границу и горизонтальные spans:

1. Координаты приводятся к сетке 10 нм. Integer predicates проверяют повторённые
   вершины, нулевую площадь, пересечения/касания и обратный ход соседних рёбер.
2. Толщина — максимум исходной обводки и `2*(fill_tolerance−0.00002 мм)`,
   округлённого вниз до сетки. Это позволяет заполнение с source stroke=0.
3. Шаг рядов ≤половины толщины; пересечения half-open, spans соединяются попарно
   по even-odd. Вогнутый контур может дать несколько отдельных spans в ряду.
4. Writer получает обычные `outline_polyline` с hatch=0, сохранённым слоем,
   толщиной, corners и закрытием только для границы. Source geometry не мутируется.

В идеальной модели круглых концов область polygon покрыта: точки рядом с
границей покрывает её stroke, прочие проецируются на внутренний span ближайшего
ряда. Центры всех линий находятся внутри/на polygon; увеличение source stroke
и rounding могут расширить исходную область не более `fill_tolerance`.
Зарезервировано 20 нм на rounding. Численные тесты используют независимые
point-in-polygon/distance-to-segment oracles на interior/exterior probes.

Допуск по умолчанию 0.01 мм, задаётся `--fill-tolerance`. Значения ≤0.00002 мм,
непредставимые на сетке или превышающие целевой диапазон, отвергаются.
Поддерживается один простой контур без отверстий, включая вогнутый, максимум
512 вершин. Общий лимит — 4096 созданных stroke polylines на footprint.
Source stroke=0 разрешён только для заполненных поддерживаемых фигур.
Filled arc, Bezier и сложные/вырожденные контуры пока отвергаются.

### Заполненные окружности

`fp_circle` с `fill solid`/`yes` сохраняется как `FilledCircle(center, end, width,
layer)`. Радиус вычисляется по center/end; source geometry не заменяется polygon
в parser. Нулевая обводка допустима; нечисловые координаты, нулевой радиус,
отрицательная ширина и выход из диапазона целевой сетки отвергаются.

В geometry после выбора общей толщины `W` граница становится вписанным
многоугольником. Допуск хорды `min(curve_tolerance, W/4)` включает запас 10 нм
на округление. Это строже простого использования curve tolerance: stroke
толщиной W покрывает круговые сегменты между многоугольником и окружностью,
а scanlines покрывают внутренность. Поэтому исходный номинальный диск заполнен
и при большом curve tolerance и тонких линиях заполнения.

В идеальной модели круглых концов линии граница исходной фигуры, включая
исходную обводку, имеет следующие пределы:

- Отклонение внутрь ≤ `curve_tolerance` (аппроксимация обводки хордами).
- Расширение наружу ≤ `fill_tolerance` (увеличение тонкой/нулевой обводки).
- Общая погрешность границы ≤ `max(curve_tolerance, fill_tolerance)`.

Запас на grid rounding учтён; nominal disk coverage и оба направления ошибки
проверяются независимо по записанным NM-координатам, включая смещённый центр,
произвольное направление end, оба silk-слоя и малые размеры около сетки.
Действуют общие пределы 512 вершин на границу и 4096 созданных линий на все
заполненные фигуры footprint; при превышении требуется явно увеличить допуск.

Когда есть circles, schema_version=1 дополнительно содержит
`counts.source_filled_circles`, `fills.source_circles` и `fills.circle_bounds`.
Последний хранит пределы внутрь/наружу, общий предел и `model=ideal_round_ended`.
Для прежних четырёх примеров без filled circles отчёты не изменяются.
GUI и manufacturing flags остаются false; `--strict` не превращает допущение
о stroke model в проверенный факт работы FreePCB2.

Отчёт `fills` сохраняет source polygons, tolerance, количество созданных
границ и spans, `stroke_model=ideal_round_ended`, GUI/manufacturing flags=false.
`FILL_APPROXIMATED` имеет severity=approximation; `FILL_STROKE_MODEL` и
`FILL_EXPORT_UNVERIFIED` — assumption. `--strict` их допускает и продолжает
отвергать известные потери других элементов.

Численный допуск относится к записанной геометрии в указанной stroke model,
не к экранным пикселям или готовому Gerber. Minimum silk stroke/export settings,
GUI rasterization и физическая 3D-привязка требуют отдельной валидации.

`--default-mask-margin`, `--default-paste-margin`, `--default-paste-ratio` позволяют
явно задать недостающие параметры исходного проекта. Если для paste указан только
margin либо только ratio, отсутствующее поле принимается за ноль с loss
`APERTURE_ASSUMED_ZERO`, блокируемой `--strict`. Если обе настройки неизвестны,
используется DEFAULT=99 с assumption `APERTURE_PROJECT_DEFAULT`.

JSON содержит исходные pad/footprint настройки и разрешённые значения. Локальные
`output/*.report.json` исключены из Git, поскольку содержат пути компьютера.
Загружаемый в Git контрольный `.fpl` воспроизводим на том же source fixture;
для 3D-привязки нужен ранее полученный STL, поставляемый отдельно.

## Legacy-дуги KiCad до версии 6

`fp_arc (start cx cy) (end sx sy) (angle degrees)` теперь поддерживается.
Это именно старый S-expression `.kicad_mod`, не текстовый формат `.mod` до 4.0.
По [зафиксированному parser KiCad](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L3824)
`start` задаёт центр, `end` — первую точку дуги, `angle` — градусы.
[SetArcAngleAndEnd](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/common/eda_shape.cpp#L1472)
вычисляет вторую точку поворотом на `-angle` через
[RotatePoint](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/libs/kimath/src/trigo.cpp#L293).
В системе исходных координат Y вниз это соответствует увеличению atan2 на
положительный angle: из (1,0) при +90° получается (0,1).
Writer инвертирует Y: target endpoint=(0,−1). При −90° target endpoint=(0,1).

`legacy_arc_points` переиспользует `sample_arc`: signed sweep, запас 10 нм
на округление и прежний лимит 4096 отрезков. Первая точка сохраняется точно;
при ±360° последняя принудительно совпадает с первой. В отличие от KiCad,
который меняет местами концы при отрицательном угле, список точек здесь сохраняет
подписанное направление обхода. Геометрическое множество дуги совпадает;
полилиния записывается с hatch=0, без дополнительного замыкающего сегмента.

Поддерживаемый профиль: `0 < abs(angle) <= 360°`, конечные координаты,
ненулевой радиус и хотя бы две различные точки на целевой сетке. Нулевые углы,
схлопнувшиеся фигуры, несколько оборотов, превышение лимита, дубли start/end/
mid/angle и смешение mid+angle отвергаются. Современный формат start/mid/end
продолжает работать без изменения прежних результатов. Filled arcs не добавлены.
`CURVE_APPROXIMATED` и общий `curve_tolerance` отражают ту же ограниченную
аппроксимацию; strict по-прежнему отвергает независимые известные потери.

Независимые тесты проверяют фиксированные endpoints/сторону дуги, signed sweep,
углы >180°, оба silk-слоя, смещённый центр и наклонный radius vector. Dense probes
проверяют расстояние от исходной дуги до отрезков после записи NM, а точки
внутри записанных chords — отклонение от исходной окружности. GUI не проверен.

Официальный `Crystal_HC49-U_Vertical` из KiCad Libraries 5.1.7 используется
без изменения исходника. Контроль `Crystal_HC49-U_Vertical_2D.fpl` сознательно
получен из копии дерева без model record: source содержит legacy `(at (xyz ...))`,
который остаётся неподдерживаемым. Это проверка шести старых дуг и двух PTH,
не пример полной 3D-конвертации. Отсутствие модели отмечено `MODEL_MISSING`;
Fab/courtyard/text потери сохранены. Команда воспроизведения приведена в
[контрольной выборке](SMALL_SAMPLE_VALIDATION.md).

## Актуальные текстовые правила

Аудит 2026-10-12: [TEXT_FIELD_AUDIT.md](TEXT_FIELD_AUDIT.md). Legacy `%R`/`%V`
теперь используют те же explicit bindings, что современные variables. Bool flags
hide/bold/italic/unlocked разбираются с проверкой дубликатов. JSON source_texts
сохраняет дополнительные properties, property_name и keep_upright. Неподдерживаемые
markup/property semantics явно диагностируются; точный baseline и поведение GUI
при вращении размещённой детали остаются непроверенными.

## Пакетная обработка

Реализован отдельный `python -m src.footprint_converter.batch` поверх текущего
единичного pipeline. [Контракт batch](BATCH_CONVERTER.md) описывает manifest,
stable names, per-item reports/state, resume/invalidation и CLI exit codes.
Прежние способы единичного запуска и API не изменялись.

2026-10-14: technical-only mask/paste padstacks и contact pads добавлены
с explicit losses; проверены 120 pinned sources, 107 generated with loss /
13 failed. Audit/fields/geometry scopes: [FOOTPRINT_MEDIUM.md](FOOTPRINT_MEDIUM.md).

2026-10-15: `default` подтверждён как solid; ограниченный KiCad9 PCB editor
default profile добавляет unfilled straight dash/dot patterns с явной потерей
editable style/project settings/native caps. Medium: 110 generated /10 failed.
Контракт, numerical checks и snapshots: [FOOTPRINT_STROKES.md](FOOTPRINT_STROKES.md).

2026-10-16: подтверждены native slot/offset ограничения, добавлены точные
circular drill equivalences и bounded centred rectangular custom unions.
Medium остаётся 110/120; native refusals имеют structured reasons, original
source и geometry proof. [Контракт pad geometry](PAD_GEOMETRY.md).
