# План разработки конвертера KiCad → FreePCB2

Обновлён 2026-10-17 по состоянию репозитория и предыдущего чата.
Цель: перенос библиотечных УГО, footprints и связей с готовыми 3D-моделями.
Полный закреплённый корпус содержит **15 464 footprints в 155 категориях**;
прежние «около 20 000» были ориентиром. Повторно конвертировать ранее полученные
7 225 STL не нужно.

## Уже готово

- Контракт footprint-библиотеки FreePCB2 2.428 изучен по ревизии ver28.
- Модульный parser/model/geometry/validation/writer/matcher/reporting/pipeline/CLI.
  Сохраняются старый Python API и оба способа запуска CLI.
- SMD circle/rect/oval/roundrect, круглые PTH/NPTH, внешние слои,
  mask/paste с приоритетами настроек, origin и инверсия Y.
- Линии, контуры, современные дуги, окружности, простые заполненные фигуры;
  аппроксимация имеет численные допуски и ограничения сложности.
- Основные тексты, JSON-диагностика потерь/допущений, strict и атомарная запись.
- Matcher готовых STL по исходной ссылке .3dshapes и OpenSCAD-код.
- Четыре реальных контрольных footprints и синтетические filled circles.
  До начала текущего этапа проходили 79 тестов.
- Legacy fp_arc center/start/angle, численная проверка обеих ориентаций и
  целевой сетки; официальный HC49-U как явно 2D-контроль. После этапа legacy arcs проходили 87
  тестов; пять прежних FPL, предупреждения и полные отчёты совпадают с HEAD.

Автоматические проверки геометрии ещё не подтверждают работу GUI, Gerber или
физическое совмещение 3D. Минимальный writer УГО уже добавлен (результат ниже),
связки R0805/C0805/Header6 и переносимый STL-комплект проверены для текущего MVP.

## Статус шести направлений

| № | Блок / статус | Где работать | Критерий завершения |
|---|---|---|---|
| 1 | Footprint-конвертер — реализован в заявленном профиле, исключения измерены на полном корпусе | src/footprint_converter, tests/fixtures | Parser/writer, arcs/fills/strokes/texts/pads; графические footprints с нулём pins; явная policy описаний; каталог неподдержанных случаев |
| 2 | Пакетный CLI и отчёт покрытия — выполнен на полном корпусе | batch/audit, library_corpus | Изолированные ошибки, стабильные имена, manifest/resume, pinned provenance, независимый readback успешных records |
| 3 | УГО KiCad → Схематор — полный pinned корпус измерен, профиль расширен | src/symbol_converter, target fixtures | 12 186/21 806 CDS, 9 620 явных отказов; 249 254 pin records проверены; overbar/primary-function loss policies; native import/connectivity — блок 5 |
| 4 | Связи — массовая preview-поставка готова | src/component_converter, config/manifest | 8 210 CDS с назначенными FPL; 878 корпусов, 461 STL, 6 993 полных model dependencies и 1 217 partial/no-model; native alignment — блок 5 |
| 5 | Валидация в целевых программах — ожидает среды | FreePCB2 2.428/Схематор/OpenSCAD, docs | Load/save roundtrip, тексты и слои, NPTH/Gerber, масштабы/положение/ориентация STL; протокол и исправление найденных ошибок |
| 6 | Масштабирование — полный корпус; экспериментальная поставка подготовлена | library_release, docs/output | Полная партия, coverage/исключения, license/provenance, архив и проверка после переноса; production-статус зависит от блока 5 |

Блок 5 можно выполнять параллельно разработке при доступной Windows.
Блок 2 можно разрабатывать до полной поддержки геометрии: ошибки остаются
явными и не считаются успешными конвертациями. Полный диагностический прогон
и 2D preview можно готовить до native-проверки. Production-статус появляется
только после проверки соответствующих форматов в целевых программах.

## Ближайший цикл реализации

1. **Legacy fp_arc (выполнено 2026-10-12).** Подтвердить center/start/signed angle
   по KiCad, переиспользовать sample_arc, проверить оба знака/слоя, углы >180°,
   допуск после записи NM и отказ для вырожденных/смешанных определений.
   Добавить один официальный старый footprint и контрольный 2D-результат.
2. **Тексты и реальная выборка (выполнено 2026-10-12 для текущего профиля).** Отдельно проверить reference/value/user,
   старое %R, переменные, скрытие и расположение. Уточнить потери в отчёте;
   baseline/font не объявлять точными без target validation.
3. **Batch на малой партии (выполнено 2026-10-12).** Построить поверх существующего pipeline,
   не переписывая parser/writer. Добавить manifest/resume и тесты ошибок,
   конфликтов имён, изменения настроек и отсутствующих моделей.
4. **Source parser УГО (выполнено 2026-10-12 для текущего профиля).** Modern
   `.kicad_sym` и legacy `.lib`, pins/units/inheritance/aliases, JSON inspection.
   Найдены официальные исходники Схематора; далее выполнен минимальный target profile.
5. **Target contract и writer УГО (выполнено 2026-10-12 для straight profile).** Проследить schematic import
   групп `.cds`, выделить реальный component fixture, подтвердить pin attributes,
   затем написать минимальный writer. Не переносить footprint FPL records на УГО
   только из-за наличия Shape.cpp в schematic repo.
6. **Связи компонентов (выполнено 2026-10-13 для малого MVP).** Создать отдельный manifest/exporter
   symbol → footprint → готовый STL: точные source identifiers, сравнение
   physical pin/pad numbers, explicit unresolved/ambiguous, проверка ссылок и
   basename-коллизий. Начать с R/C/connector controls; PIC24 duplicates не
   исправлять автоматически. Переносить только связанные существующие модели,
   сохранять исходники; source/readback mapping не считать GUI/3D-совмещением.
7. **Окружности/дуги УГО (выполнено 2026-10-13 для unfilled profile).** Расширить graphics profile по pinned
   target contract: окружности/дуги и новая реальная выборка. Явно сохранять
   electrical metadata/losses; multi-unit/merge разбирать отдельно. Проверять
   новые outputs в component chain и не подменять GUI численной проверкой.
8. **Electrical pin profile (выполнено 2026-10-13 для ordinary visible line pins).** Проверить native представимость
   видимых line pins разных electrical types; сохранить source semantics и
   explicit ERC losses. Не выдавать номер/Node за проверенную функцию pin;
   no-connect/power/hidden/alternates разбирать отдельно. Добавить реальную
   выборку и сквозные проверки; fills/text и multi-unit/merge остаются далее.
9. **Filled geometry и graphic text (выполнено 2026-10-13 для ограниченного профиля).** Подтвердить native
   представимость заливок и самостоятельного текста, включая body background.
   Сначала ограниченный профиль с явными losses и реальными controls; проверить
   старые bytes, curved outlines, pin visibility и linked chains. Power/hidden/
   no-connect и multi-unit/merge этим подпунктом не закрываются.
10. **Multi-unit/merge (исследование и disjoint layout выполнены 2026-10-13; hierarchy открыта).** Проследить native представление
    нескольких логических секций одного physical component и привязку к pads.
    Разделить common/source units, power units и alternate body styles;
    не объединять дубли механически. Реализовать только подтверждённый профиль,
    с явными ограничениями и real controls/number mapping.
11. **Power/no-connect pins (выполнено 2026-10-14 для numbered power и explicit lossy NC; NC enforcement открыта).** Разделить power pins ordinary
    components, virtual power symbols и no-connect endpoints. Проверить native
    запись/Node/physical count, сохранить source/ERC semantics и explicit losses.
    Hidden/styled/alternate/shared pins расширять отдельными подтверждёнными
    профилями; GUI и hierarchy этим шагом не закрываются.
12. **Styled/hidden pin policy (выполнено 2026-10-14 для editor markers и explicit reveal).** Проверить native представимость
    inverted/clock markers и скрытых выводов. Сохранить physical number и
    connection point; graphics и implicit/global net semantics разделить.
    Поддержать только подтверждённые варианты, сохранив explicit losses,
    default refusals и strict. Добавить real controls и bundle regression.
13. **Common pins (выполнено 2026-10-14 для original unit=0).** Explicit
    common view одного physical component, один record на исходный pin,
    loss shared appearance/placement; repeated records остаются отказом.
14. **Footprint coverage и средняя партия (выполнено 2026-10-14 для 120 pinned files).** Аудит representative
    pinned source footprints, отчёт successful/loss/failed конструкций,
    исправления наиболее частых представимых исключений. Проверить старые
    baselines, source links и переносимость; GUI выполнять отдельным блоком.
15. **Graphic strokes (выполнено 2026-10-15 для straight unfilled profile).**
    Исправлен `default` → solid; прошлые 4 stroke refusals оказались default,
    а не dash/dot. Добавлены dash/dot/dash_dot/dash_dot_dot по KiCad9 PCB
    defaults с фазой на каждом ребре, лимитом 4096 и explicit style/render loss.
    Curves/filled patterned outlines остаются отказом. Medium: 110/120;
    20 новых tests, восемь прежних bundles и 107 FPL/report baselines неизменны.
16. **Oval/offset drills и custom pads (выполнено 2026-10-16 для exact reductions и native refusals).**
    Подтверждены ограничения centred native padstack: один круглый hole_size,
    historic X extents reader складывает. 6 slot files, 1 offset file и 3
    nonrectangular custom files остаются refusal. Добавлены равные oval axes /
    zero offset и bounded exact centred rectangular unions без изменения anchor;
    aperture restrictions, primitive editing/zone loss и raw source сохраняются.
    Medium 110/120 unchanged; 23 новых tests, всего 460, восемь старых bundles
    byte-identical. Подробности: [PAD_GEOMETRY.md](PAD_GEOMETRY.md).
17. **Комплект для native validation (подготовка выполнена 2026-10-17; native GUI открыта).**
    8 bundles/24 компонента, 5 standalone FPL controls, 15 existing STL aliases,
    10 negative controls, source/license snapshots, record catalog и 10 manual
    scenarios. Standalone integrity/evidence checker, isolated relocation и ZIP
    проверены; три SCAD previews скомпилированы OpenSCAD 2021.01 только в CSG.
    Native flags false, manual checks not_run; 478 tests проходят. Windows-гость
    не найден в зарегистрированных VM; FreePCB2/Схематор в проверенных местах
    не обнаружены. [NATIVE_VALIDATION.md](NATIVE_VALIDATION.md).
18. **Полный корпус и preview-поставка (выполнено 2026-10-17).** Проверить все
    15 464 pinned footprints, выполнить независимый source/FPL audit,
    исправить представимые массовые отказы, сохранить точный каталог исключений
    и собрать проверяемую поставку без повторной обработки STL/STEP.
    Итог: **14 109/15 464 (91,24%)**, +816 к первому полному прогону,
    1 355 классифицированных отказов, 354 192 проверенных pad records,
    resume 14 109 reused без изменения FPL/report hashes; **501 тест**.
    Результаты и команды: [FULL_LIBRARY.md](FULL_LIBRARY.md).
19. **Массовые УГО и pin-name/alternate policies (выполнено 2026-10-17).**
    Закреплены все 224 source libraries / 21 806 УГО. Первый профиль: 8 779 CDS;
    после explicit overbar removal/primary-function policies — **12 186 CDS**,
    +3 407, **9 620 refusals**, unexpected=0. Все 8 779 прежних CDS/report pairs
    byte-identical. Аудит проверил **249 254 pin records**; preview ZIP с полными
    source/loss reports проверен после распаковки/переноса. **533 теста** проходят.
    Смысл новых потерь и команды: [SYMBOL_BATCH.md](SYMBOL_BATCH.md).
20. **Массовая связанная поставка (выполнено 2026-10-17).** Повторно проверены
    оба audited snapshots и выбранные source/model bytes. Собраны **8 210/8 210**
    связанных компонентов вместо PART-CDS: **878** разных FPL names, **461** STL,
    **94 540** проверенных физических pin/pad pairs. У **6 993** найдены все
    model dependencies, **1 217** partial/no-model; отказов и conflicting FPL
    contents при одинаковом target name нет. ZIP **307 265 987B**, CRC и полная
    проверка распакованной копии выполнены. **542 теста** проходят.
    Команды и ограничения: [MASS_COMPONENTS.md](MASS_COMPONENTS.md).
21. **Native roundtrip/connectivity/manufacturing/3D (внешний этап приёмки).** Перенести
    kit в Windows с FreePCB2 2.428 и Схематором 1.429, пройти protocol.json,
    записать версии, измерения и evidence в results/. Разделить known losses
    и новые failures, исправить найденное; library-local CSG не считать board
    alignment. После фактических native checks и исправления найденных дефектов
    — production-статус уже подготовленной поставки поддержанного профиля.
    Порядок передачи и три контрольных компонента из массового архива:
    [WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md).

Критерий «рабочего конвертера» из ТЗ и проба STEP → STL на четырёх реальных
моделях: [WORKING_CONVERTER_ACCEPTANCE.md](WORKING_CONVERTER_ACCEPTANCE.md).
Численные и визуальные проверки образцов выполнены отдельно от прежних
7 225 STL; подтверждение импорта/связей/board 3D остаётся пунктом 21.

## Зависимости и ограничения

- Для блока 3 source Схематора и реализованный component profile подтверждены;
  import/connectivity проверяются в блоке 5. Repeated/alternate pins, native
  hierarchy и ERC/implicit global nets остаются явными ограничениями профиля,
  описанными в документации УГО; они не объявляются реализованными.
- Для блока 5 нужна доступная целевая программа; macOS-разработка продолжается.
- Полные footprint/symbol corpora закреплены и измерены. Это не подтверждение
  100% поддержки KiCad: остаются 1 355 footprint и 9 620 symbol refusals.
- STL/STEP используются как существующие артефакты; тысячи meshes не открываются.
- Legacy model (at ...) по-прежнему требует отдельного подтверждения единиц;
  поддержка старых дуг не означает поддержку всех исторических model records.
- Filled arcs, Bezier, сложные pads/holes/padstacks расширяются только при
  подтверждённой представимости; остальные случаи имеют явный отказ/потерю.

## Как считать оставшуюся работу

**С 2026-10-17 субъективный процент остатка больше не используется.** Старые
65–75%, 15–25% и число открытых блоков ниже сохранены только как журнал
прежних оценок; они не описывают текущий статус и не пересчитываются задним числом.

После крупного шага сообщать измеренный результат и оставшиеся критерии.
Для малого поддержанного MVP код готов; native load/save/connectivity/Gerber/
board 3D остаются внешней приёмкой по 10 сценариям kit. Объём исправлений по её
результатам до проверки неизвестен. Нужной Windows-среды здесь нет.

**Если Windows не считать:** обязательных этапов разработки/упаковки для
первой массовой связанной preview-поставки текущего профиля осталось **0**:
пункт 20 выполнен. Это не 100% поддержки KiCad и не production-приёмка.
Расширение покрытия — отдельная измеренная очередь: 1 355 footprints и
9 620 УГО отказаны; крупнейшая группа УГО — 6 114 совпадающих connection
endpoints. Их нельзя автоматически дедуплицировать с потерей физических выводов.
Из 21 806 УГО связаны 8 210; остальные 13 596 учтены в candidates с точными
причинами. 1 217 выбранных компонентов имеют partial/no-model dependencies.
Не все исключения представимы в текущих native-форматах без дополнительного
профиля/потерь; количество файлов не переводится в процент трудозатрат.

Coverage полной footprint-библиотеки — отдельная измеренная величина, а не
процент готовности проекта. Все отказы остаются в каталогах; расширение их
поддержки составляет следующую очередь разработки.
Текущую реализацию нельзя называть конвертером со 100% покрытием KiCad.

## Журнал текущего цикла

- 2026-10-12: план обновлён по прошлому чату, выделены зависимости и критерии
  шести блоков; исходные 79 тестов прошли.
- 2026-10-12: legacy arcs реализованы; добавлено 8 тестов (всего 87) и один
  официальный fixture. Получен явно 2D-контроль HC49-U; legacy model(at)
  остаётся неподдерживаемым. Блок 1 остаётся в работе.
- Остаток после этого шага: **6 незавершённых блоков; приблизительно 65–75%**.
  Следующий подпункт: аудит текстов и расширение небольшой реальной выборки.
- Проверка переносимости: в копии без STL/STEP 87 тестов проходят,
  включая три явных пропуска optional integration tests реальных моделей.

- 2026-10-12: аудит текстов завершён для текущего subset: legacy %R/%V,
  hide/style flags, unlocked, visible/hidden properties, явные formatting losses.
  Добавлены D_SOD-123 и контрольный FPL. Всего 105 тестов; пять прежних FPL
  неизменны, в HC49-U удалён только ошибочный static %R. Отчёты обогащены
  source text policies/fields, поэтому прежние JSON намеренно изменились.
- Следующий этап: batch CLI/manifest/resume на малой выборке. Расширение
  footprint coverage будет опираться на выявленные ошибки партии; GUI остаётся
  отдельным незавершённым блоком. Оценка остатка пока 65–75%, 6 блоков
  незавершены; аудит текстов закрывает подпункт, не всю footprint-часть.

## Результат пакетного этапа — 2026-10-12

- Реализован отдельный batch CLI поверх convert_detailed: стабильные имена,
  manifest/reports/state, изоляция ошибок, strict, limit и защищённые paths.
- Resume проверяет source bytes, options, engine fingerprint, metadata только
  связанных STL и хеши FPL/report. Per-item state восстанавливает работу после
  прерывания до следующего manifest checkpoint; есть OS advisory lock.
- 131 тест (26 новых batch-проверок). В партии из 7 fixtures получены 6 FPL
  с известными потерями; HC49-U оставлен с ожидаемым отказом model(at).
  Resume переиспользует все 6 successful results и повторяет failed.
- Блок 2 закрыт для текущего MVP; Windows locking, GUI и benchmark на 20 000
  остаются задачами блоков 5/6. Правила: [BATCH_CONVERTER.md](BATCH_CONVERTER.md).
- **Остаток: 5 незавершённых блоков (1, 3, 4, 5, 6), примерно 60–70% проекта**.
  Это уточнённая инженерная оценка работ, не процент успешно обработанных файлов.
- Следующий шаг: исходный parser УГО KiCad и поиск подтверждённого target эталона
  Схематора; writer target не строить по догадке. Расширение footprints далее
  опирается на диагностируемые ошибки малых/средних партий.

## Результат исходного этапа УГО — 2026-10-12

- Отдельный `src/symbol_converter`: `.kicad_sym` 6–9 и legacy `.lib` 2.3/2.4;
  mm/source coordinates, fields, pins, units/styles, aliases, inheritance и
  графика без target аппроксимации. Raw source сохраняется.
- JSON CLI с выбором symbols, source hash, явными extensions/duplicates,
  атомарной записью и защитой исходников/моделей. Это source inspection,
  target библиотека ещё не генерируется.
- Контроль: 27 legacy DEF (268 pin records), 11 Mechanical и 61 Comparator
  из официальных KiCad 9.0.0. У PIC24 16 номеров с восьмикратными повторами;
  записи сохранены, mapping не считается подтверждённым.
- 31 новый тест; всего 162. В копии без STL/STEP те же проверки проходят с
  3 optional integration skips. Правила и команды: [SYMBOL_CONVERTER.md](SYMBOL_CONVERTER.md).
- Найдены официальные исходники Схематора, commit
  e7443c374f5c8644fb3483f794a50161de60dd01: `.cds` graphics, component attributes,
  group insertion и список `[prefix] value@package`. Полный контракт pin/merge
  ещё не готов; [SCHEMATOR_FORMAT_RESEARCH.md](SCHEMATOR_FORMAT_RESEARCH.md).
- **Остаток: 5 незавершённых блоков (1, 3, 4, 5, 6), примерно 55–65% проекта**.
  Source parser и нахождение target source уменьшают неопределённость, но не
  закрывают блок 3. Оценка инженерная, не измеренное library coverage.
- Далее: target contract + минимальный writer УГО Схематора, затем связки
  symbol → footprint → существующий STL и GUI/масштабирование.

## Результат минимального writer УГО — 2026-10-12

- Прослежен `FindStrInFile`/`ReadGraphics`; подтверждены native NM/Y up,
  layers, pin_number attributes, free-end Node flags, text options/rotation,
  component index и `part_end`. Выделен точный R3 fragment из detector.cds,
  source/fragment hashes и проверка неизменности сохранены.
- Writer одного component `.cds` 1.429 + отдельный reader/validator, JSON
  source/settings/losses/assumptions и CLI. Поддержаны один unit, passive
  straight pins и unfilled rectangles/polylines; неподдерживаемые случаи
  отклоняются, duplicates не удаляются. Source inspection CLI сохранён.
- Созданы воспроизводимые `R_control.cds`, `C_control.cds` и
  `CONN_01X06_control.cds`: 2/2/6 электрических pins. Пока используется PART
  placeholder; explicit footprint name не подтверждает pad mapping.
- 31 новый тест; всего **193**, все проходят. Копия без STL/STEP проходит
  с 3 optional integration skips. Модели не переконвертировались.
- Source contract/readback подтверждены для ограниченного профиля; native
  import/connectivity/font layout/load-save ещё не проверены. Блок 3 остаётся
  в работе; [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md).
- **Остаток: 5 незавершённых блоков (1, 3, 4, 5, 6), примерно 50–60% проекта**.
  Это инженерная оценка объёма, не измеренное покрытие библиотеки.
- Далее: component manifest и проверка symbol → footprint → существующий
  STL; расширение УГО по выявленным ограничениям, GUI и масштабирование.

## Результат component links и переносимого комплекта — 2026-10-13

- Добавлен `src/component_converter`: explicit JSON config, namespace lookup,
  identity pin/pad mapping, independent CDS/FPL readback, manifest/reports,
  per-item failures, staging/publication и read-only verify после переноса.
- Existing STL snapshots сохраняют category tree и получают unique flat
  aliases для общей OpenSCAD папки FreePCB2 2.428. Source bytes не меняются;
  selected-model SHA256/size проверяются, meshes не интерпретируются.
- Контроль R0805/C0805/Header6: 3 complete library chains, 2/2/6 pin numbers,
  3 существующих STL (294 652 bytes), 17 package files. C0805/PinHeader6 — новые
  неизменённые официальные KiCad fixtures с pinned provenance/license.
- 42 новых теста, всего **235**. Полный набор проходит; копия без STL/STEP
  проходит с 3 optional integration skips. Проверены relocation без source,
  duplicates, NPTH, basename/case collisions, strict/missing policies,
  transforms, checksum/record corruption, fault injection и rollback.
- Блок 4 закрыт для MVP малой партии. Native import/netlist/GUI, физическая
  пригодность корпуса и STL alignment не подтверждены; полнота библиотек
  остаётся ограничена профилями блоков 1/3/6. Правила:
  [COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md).
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 40–50% проекта**.
  Это инженерная оценка работ, не доля покрытой библиотеки.
- Далее: graphics profile и новая реальная выборка УГО; multi-unit/merge,
  расширение footprints, затем native GUI и масштабирование.

## Результат окружностей и дуг УГО — 2026-10-13

- Добавлен source graphics profile `unfilled-curves-v1`: circles и modern/
  legacy arcs превращаются в straight NM polylines; target record profile не
  меняется. Default error bound 0.01 mm включает quantization, limits 4096
  curve corners/32768 body corners. Pin endpoints/Nodes сохраняются.
- Legacy разрешение зафиксировано по KiCad9 loadArc/MapAnglesV6/GetRadius и
  100 nm schematic IU. Raw radius/endpoints остаются в JSON; projection/swap
  учитываются отдельно от tessellation. У INDUCTOR есть ~0.02544 mm endpoint
  shift: это явный loss, а не скрытое превышение 0.01 mm curve tolerance.
- Device/Connector KiCad 9.0.0 сохранены целиком без изменений (531/397 source
  definitions). Созданы 7 CDS/report controls; scope не выдаётся за поддержку
  всей библиотеки. Добавлены official L0805/TestPoint pad fixtures.
- Curve component party: 3 generated bindings, 2 complete chains с одним
  existing L0805 STL (21 384 bytes), 1 явно 2D TestPoint; 13 package files.
  Relocation/repeated build проверены; старые linear CDS/reports и bundle
  остаются byte-identical. STL не конвертируются и не интерпретируются.
- 31 новый тест; всего **266**, все проходят; copy без STL/STEP — с 3 optional
  integration skips. Проверены NM centerline bounds, оба направления/>180°,
  legacy ambiguity/rounding, grid/complexity/fill refusals, strict и links.
  Правила/источники: [SYMBOL_CURVES.md](SYMBOL_CURVES.md).
- Блок 3 остаётся открытым: electrical types, fills/text, multi-unit/merge и
  native import/connectivity/font/caps/joins требуют дальнейшей работы.
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 35–45% проекта**.
  Оценка объёма работ, не измеренное target coverage.
- Далее: electrical pin profile и реальная выборка; затем fills/text,
  multi-unit, расширение footprints, native GUI и масштабирование.

## Результат ordinary electrical pin profile — 2026-10-13

- Разрешены visible line pins: passive/input/output/bidirectional/tri_state/
  unspecified/free/open_collector/open_emitter. Native records не изменены:
  physical number и external Node=1, source electrical semantics остаются
  в JSON с явным loss; ERC rules не передаются. Power/no-connect/hidden/
  styled/alternate pins по-прежнему вызывают отказ.
- Профиль `visible-line-electrical-v1`, per-pin source/target record mapping,
  type counts и electrical_rules_transferred=false. Strict сохраняет отказ
  и source semantics; linked number verification не повышает ERC/GUI flags.
- Пять real Device controls: Antenna/Antenna_Chip/DelayLine/Q_SCR_AGK/Speaker.
  Две library chains SCR→SOT-23/Speaker→CUI: 2 existing STL, 263 268 bytes,
  12 package files. Generic SCR binding не доказывает пригодность корпуса.
- 19 новых тестов; всего **285**, все проходят. Copy без STL/STEP — те же
  проверки с 3 optional integration skips. Legacy codes/ordinary types,
  strict/hidden labels/curve indices/relocation проверены. Старые passive
  CDS/reports и control/curves bundles остаются byte-identical.
- Правила и ограничения: [SYMBOL_ELECTRICAL.md](SYMBOL_ELECTRICAL.md).
  Блок 3 остаётся открытым: fills/text, units/merge, power/no-connect/hidden/
  alternates и native import/connectivity/ERC требуют дальнейшей работы.
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 30–40% проекта**.
  Это инженерная оценка объёма; library coverage не измерено.
- Далее: ограниченный filled geometry/graphic text profile и реальная
  выборка, затем multi-unit/merge, footprints, native GUI и масштабирование.

## Результат simple fills и body text — 2026-10-13

- Профиль `bounded-fills-body-text-v1`: foreground rectangles/closed simple
  polygons/circles → bounded straight strokes, default fill tolerance .01 mm.
  Source Y up и 10NM fill grid, 4096 fill polylines/32768 body corners.
  Bounds относятся к идеальным круглым strokes; native caps/joins не проверены.
- Background сохраняет boundary с explicit occlusion loss. Native body
  description attributes сохраняют literal modern text/legacy T, anchor,
  quarter-turn и hidden state; source font/layout/z-order имеют loss.
  Unsafe command text, filled arcs/Bezier/open filled contours отклоняются.
- Шесть real Device controls; две chains D_Filled→SOD-123 и meter text→Header2,
  два existing STL, 126368 source bytes, 12 package files. Generic meter
  binding не доказывает physical suitability. Models не переконвертированы.
- 27 новых проверок; всего **312**, все проходят. Copy без STL/STEP — с
  3 optional integration skips. Coverage/caps/concavity проверены по NM output,
  text ownership/legacy T/strict/protected outputs и relocation подтверждены.
  Прежние passive/curve/electrical controls и три old bundles неизменны.
- Правила: [SYMBOL_BODY.md](SYMBOL_BODY.md). Блок 3 остаётся открытым:
  multi-unit/merge/power/no-connect/hidden/alternates, полное geometry coverage
  и native import/connectivity/font/occlusion требуют дальнейшей работы.
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 25–35% проекта**.
  Это инженерная оценка объёма, не измеренное покрытие библиотек.
- Далее: multi-unit/merge contract и ограниченный profile, footprints,
  native GUI/3D validation и масштабирование.

## Результат disjoint multi-unit layout — 2026-10-13

- Накопленные links/curves/electrical/body изменения отправлены в Git:
  commit 94584fdd7b3de52d7a03dd37cc214b066d5f96c6, origin/master.
  Native CDS CRLF сохранены; runtime bundles и model stores не включены.
- Merge/hierarchy исследованы: ordinary part chain хранит все body/pin
  attributes до part_end; merge indices служат import filtering, BLK/BLK_PTR
  зависят от иерархии/страниц. Native independent units/hierarchy не объявлены
  поддержанными.
- Профиль `disjoint-units-layout-v1`: 2–16 logical units с уникальными
  physical numbers размещаются рядом в одном component. Default gap2.54mm,
  integer NM translations, common graphics повторяются по source views.
  Source/layout/global record indices сохранены; independent placement,
  suffixes/per-unit labels имеют явный loss. Common/repeated/power pins reject.
- Пять real Device controls; Array2/Array4/SIP4 дают 3 file chains, 3 existing
  STL, 204252 source bytes, 17 package files. Source/CDS/FPL numbers 4/8/4
  проверены; physical suitability/GUI/netlist/3D alignment не подтверждены.
- 24 новых проверки; всего **336**, все проходят. Copy без STL/STEP — с
  3 optional integration skips. Literal Nodes/translation, shared/refusals,
  legacy/inheritance, curve/fill/text rebasing, strict/budgets/overflow и
  relocation проверены. Single-unit controls и 4 old bundles неизменны.
- Правила/primary evidence: [SYMBOL_UNITS.md](SYMBOL_UNITS.md).
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 20–30% проекта**.
  Это оценка объёма работ, не измеренное library coverage. Multi-unit
  hierarchy/shared/power/no-connect/hidden/alternates остаются в блоке 3.
- Далее: power/no-connect policy, затем shared/styled/hidden profiles,
  footprint coverage, native GUI/3D validation и масштабирование.

## Результат power/no-connect policy — 2026-10-14

- Профиль `visible-line-power-v1`: ordinary physical power_in/power_out
  сохраняются как numbered terminals; source power/ERC roles остаются в JSON
  с явной потерей. Power-only секции включаются в disjoint compound layout:
  LM393 теперь сохраняет обе signal units и отдельную power unit, все 8 pins.
- Native source показывает, что FindNodeLine может восстановить Node=1,
  а group paste переводит pin attributes на электрический слой. Node=0 или
  декоративный слой не реализуют подтверждённый запрет NC. Default policy
  остаётся reject; explicit `connectable-with-loss` сохраняет NC подключаемыми
  с отдельным loss на каждый pin. Native NC enforcement не закрыта.
- API/CLI/bundle config проверяют policy. Reports содержат power/NC counts,
  source roles, native indices/Nodes/connectability и false ERC/NC flags.
  Strict отклоняет losses и сохраняет прежний CDS. Virtual/global power,
  common/repeated/hidden/styled/alternate pins по-прежнему вызывают отказ.
- Шесть real controls; три complete file chains LM393→DIP-8, MCP1525→SOT-23,
  MCP601_8PIN→DIP-8. Все source/CDS/FPL номера сохранены, включая NC 1/5/8.
  Два existing STL, 287168 source bytes, 15 package files с manifest; models
  только копируются/хешируются. Physical suitability/GUI/3D не подтверждены.
- 23 новых проверки, всего **359**, все проходят. Copy без STL/STEP — с
  3 optional integration skips. Power W/w/NC N, modern types, source/raw
  immutability, multi-unit rebasing, strict/CLI preservation, default/invalid
  policy, number mapping и relocation проверены. Старые controls и пять
  предыдущих bundles воспроизводятся без изменений.
- Правила/primary source evidence: [SYMBOL_POWER.md](SYMBOL_POWER.md).
- **Остаток: 4 незавершённых блока (1, 3, 5, 6), примерно 20–30% проекта**.
  Оценка остаётся прежней: шаг расширяет подтверждённый профиль, но exact NC,
  shared/hierarchy/hidden/styled/alternates, footprint coverage, native GUI
  и масштабирование ещё требуют работы. Это инженерная оценка, не coverage.
- Далее: styled/hidden pin policy, затем shared/hierarchy, footprint coverage,
  native GUI/3D validation и масштабирование.

## Результат styled/hidden pins — 2026-10-14

- Подтверждён KiCad9 editor profile: восемь marker styles → non-electrical
  layer-6 strokes, original external pin point/number сохраняются. Inversion
  bubbles имеют bounded approximation, internal segment сокращён; logical
  style/project sizing/font/caps/joins остаются explicit loss.
- Hidden pins default reject; explicit reveal-with-loss сохраняет terminals
  видимыми, visibility/implicit global power connections теряются. NC требует
  второй explicit policy. Raw source/strict/invalid settings/budgets защищены.
- Шесть real controls, 5 complete file chains, 3 existing STL, 553052 bytes,
  23 files. Source/CDS/FPL number identity и relocation подтверждены;
  physical suitability/GUI/3D не подтверждены. STL не переконвертированы.
- 21 новый тест, всего **380**. Прежние controls и 6 bundles воспроизводятся
  без изменений. Правила: [SYMBOL_PINS.md](SYMBOL_PINS.md).
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Это инженерная
  оценка, не coverage; hierarchy/shared, implicit nets/ERC/NC, footprint
  exceptions, native GUI и scale/release ещё открыты.
- Далее: common pins как отдельная view одного physical component; repeated
  records не дедуплицировать, source/shared placement отразить как loss.

## Результат original common pins — 2026-10-14

- `common-pins-view-v1`: default reject; explicit common-view-with-loss
  размещает original unit=0 pins один раз после logical views в том же
  physical component. Common graphics повторяются по logical views;
  shared appearance/independent placement/native hierarchy имеют loss.
- Source/raw records не меняются и не дедуплицируются. Повторы положительных
  units, common/own conflicts, empty logical views и unsupported graphics
  остаются отказом. Hidden/NC/marker policies применяются независимо.
- Четыре real networks (3/4/7/13 logical units, 4/5/8/14 physical pins),
  три source-property SIP4/SIP5/SIP8 chains, 3 existing STL, 466152 bytes,
  17 files. Source/CDS/FPL identity и relocation проверены; GUI/3D и функция
  pads не подтверждены. Split-diodes сохраняют отказ collapsed segments.
- 18 новых тестов; всего **398**, проходят, copy без STL/STEP — с 3 optional
  integration skips. Семь прежних bundles воспроизводятся без изменений.
  Правила: [SYMBOL_COMMON.md](SYMBOL_COMMON.md).
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Инженерная
  оценка объёма, не library coverage. Native hierarchy/implicit nets/ERC/NC,
  alternate modes, footprint exceptions, Windows GUI/3D и scale/release
  ещё требуют работы.
- Далее: footprint coverage audit и средняя representative партия; затем
  исправления по диагностике, native GUI/3D validation и масштабирование.

## Результат средней footprint партии — 2026-10-14

- Power/markers/common этапы отправлены в origin/master: 890dc79.
- Сохранены whole unchanged 120 official footprints в 12 категориях, pinned
  KiCad51f8a59; 908267 bytes, SHA256/Git blob/license checks. Выбор deterministic,
  не random; tree metadata на revision содержит 15464 footprint files.
- Первый результат 85/120 generated_with_loss (70.83%). Подтверждены
  technical-only mask/paste carriers без copper/hole и contact no-paste pads;
  source roles/names сохранены в JSON, carrier/connector semantics имеют loss.
- Итог этого этапа 107/120 generated_with_loss (89.17%), 13 refusals: 6 oval/offset
  drill, 4 stroke parser refusal, 3 custom pads. Уточнение 2026-10-15: все четыре
  stroke refusal имели `type default`, не dash/dot. Source не редактируется;
  unexpected errors=0. Исходный snapshot audit сохранён для истории.
- Read-only audit проверил все 107 source/FPL records (2295 padstacks), hashes,
  provenance и raw feature inventories (2557 source pads). 133 technical
  carriers сохранены; 13 successful files имеют ambiguous repeated numbers,
  поэтому complete component chain не объявлена подтверждённой. GUI/netlist/
  Gerber/3D flags остаются false. Mesh geometry не читалась/не конвертировалась.
- Fresh-output ~0.455s, resume ~0.233s, audit ~0.227s, peak process RSS ~41.5MiB
  на Python3.13/macOS arm64. File cache мог быть тёплым; прогноз на full library
  и Windows из этого числа не делается. Resume reused107/failed retried13.
- 19 новых tests, всего **417**, проходят; portable clone без STL/STEP — с
  3 optional integration skips. Восемь прежних bundles неизменны.
  Rules/results: [FOOTPRINT_MEDIUM.md](FOOTPRINT_MEDIUM.md).
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Средняя партия
  начинает масштабирование, но native GUI/manufacturing и полная поставка,
  slots/custom/alternate/hierarchy/implicit-net exceptions ещё открыты.
- Далее: restricted non-solid stroke profile, затем дальнейшие исключения,
  native Windows/Gerber/3D validation и full-library coverage/release.

## Результат graphic stroke этапа — 2026-10-15

- Предыдущий commit 91da8d2 подтверждён на origin/master; запрос push выполнен.
- По KiCad9 EDA_SHAPE исправлен `default` → solid без добавления stroke loss.
  Все четыре прошлых stroke refusals были ошибочно названы non-solid; три
  теперь проходят, USB3_A_Molex_48393-001 получает следующий oval-drill refusal.
- `kicad9-pcb-editor-default-strokes-v1`: unfilled line/rect/simple polygon,
  четыре dash/dot styles, centreline 11w/.2w/4w, phase restart на каждом ребре,
  clipping endpoint, 10nm grid и общий лимит 4096 marks без truncation.
  Source typed/raw geometry/style сохраняется; editable style, project/render
  settings, omitted zero-length endpoint marks и unverified native caps/joins
  имеют GRAPHIC_STROKE_FLATTENED loss.
  Strict отклоняет профиль. Curved/filled patterns, zero/collapsed marks,
  malformed/duplicate/colored strokes остаются явными отказами.
- Средняя партия: **110/120 generated_with_loss (91.67%)**, 10 failures:
  7 oval/offset drill, 3 custom pads; unexpected errors=0. Все 110 pad readbacks
  проверены (2429 pad records), 14 repeated-number bindings остаются ambiguous.
  Raw inventory: 3261 solid и 16 default, настоящих dash/dot в этой партии нет.
  Для patterned profile сохранён отдельный явно synthetic контроль с 71 marks.
- 20 новых проверок, всего **437**, проходят; portable copy без STL/STEP —
  с тремя optional skips. 107 прежних FPL/reports неизменны, все восемь bundles
  совпадают byte-for-byte и проходят relocation verification.
- Rules/source evidence/audit: [FOOTPRINT_STROKES.md](FOOTPRINT_STROKES.md).
  Старые medium audit/benchmark не переписаны; новые snapshots имеют strokes prefix.
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Этот профиль
  расширяет footprint coverage, но не закрывает native GUI, manufacturing,
  symbol hierarchy/implicit-net exceptions или full-library release.
- Далее: native slot/offset/custom-pad contract и ограниченные extensions,
  затем Windows/Gerber/3D validation и полная поставка.

## Результат pad geometry этапа — 2026-10-16

- Master 7f2bbb9 уже был синхронизирован с origin; push проверен до разработки.
- FreePCB2 2.428 header/reader/rendering подтверждают только circular hole_size
  и centred native pad shapes. Два исторических X-поля не хранят offset: reader
  складывает их в size_X. Source drill offset KiCad двигает copper shape, не
  hole/connection anchor. Nonzero offset и slots не заменяются/не сдвигаются.
- `freepcb2428-exact-pad-reductions-v1`: равные oval axes и explicit zero offset
  дают прежнюю круглую геометрию с info. Custom SMD с anchor rect/outline и до
  32 filled zero-width axis-aligned rectangular gr_poly допускается, только
  если exact rational union совпал с центрированным прямоугольником. Source
  1nm grid и even-nm anchor исключают расхождение integer half-size geometry;
  proof выполняется до target 10nm quantization, исходный pin anchor не меняется.
- Custom apertures требуют resolved nonnegative margins и zero paste ratio.
  Primitive editing/zone/thermal settings имеют CUSTOM_PAD_RECT_FLATTENED loss,
  strict отвергает результат; native GUI/netlist/Gerber/3D остаются unverified.
  Source raw/typed pad, union proof и proposed native pad записаны в JSON.
- Средняя партия: **110/120 generated_with_loss (91.67%)**, те же 10 refusals:
  **6 slot files (22 records), 1 nonzero offset file, 3 nonrectangular custom pads**.
  Для трёх custom pads bounding-box excess=.65/1.228675/.245 mm² — замена bbox
  добавила бы лишнюю медь. Unexpected errors=0; все 110 FPL/reports неизменны.
- 23 новые проверки, всего **460**, проходят; portable copy без STL/STEP —
  3 optional skips. Проверены synthetic exact reductions, real negative cases,
  1nm notches, raw immutability, apertures, strict/CLI preservation, audit proof
  tampering, pin mapping и component relocation. Восемь прежних bundles
  byte-identical и проходят relocation verification.
- Source contract/evidence/audit: [PAD_GEOMETRY.md](PAD_GEOMETRY.md). Старые
  snapshots сохранены; новые используют footprint-pad-geometry prefix.
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Coverage этой
  выборки не выросло: установлены native ограничения, расширен точный профиль
  и улучшена диагностика. Следующий шаг — комплект для native validation.

## Результат подготовки native validation — 2026-10-17

- Push до разработки: master 5113886 уже синхронизирован с origin.
- `src/native_validation` использует существующие component/footprint pipeline:
  8 прежних bundles (24 компонента), 5 standalone FPL controls, 10 expected
  refusal source/reports, source/license/provenance snapshots и catalog NM.
  23 structural model chains доступны, 15 unique global STL aliases (1558560B),
  23 library-local SCAD previews. Выбранные STL скопированы побайтно.
- Frozen manifest/index (251 files, 15690240B до manifest) и standalone stdlib
  checker позволяют перенос без repo/STL store. `results/` предназначен для
  наблюдений и native exports; template 10 checks=not_run. Passed observation
  требует operator, target version(s), notes и SHA256 evidence; checker проверяет
  структуру/identity, но не удостоверяет действия оператора или screenshots.
- Runtime kit: `output/native-validation-ready`; архив в ignored
  `output/native-validation-package/native-validation-kit.zip` (1908153B).
  ZIP CRC, extraction/relocation и standalone Python -I checker выполнены.
  Восемь bundles byte-identical старым; source snapshots неизменны. STL/ZIP
  не добавляются в Git; tracked summary содержит hashes/counts/scoped results.
- OpenSCAD **2021.01** обнаружен: C0805/Header6/R0805 scenes **3/3** native CLI
  CSG compilation без warnings. Это syntax/CSG, не STL remesh, GUI, native board
  export или physical frame proof. Native 3D/model/GUI flags остаются false.
- FreePCB2 2.428/Схематор 1.429 не найдены в checked workspace/Applications/PATH.
  Sandbox VBox inventory дал IPC error; elevated read-only inventory/showvminfo
  прошли: один Debian ARM64 guest, poweroff, зарегистрированных Windows guests=0.
  Это не исключает unregistered/remote environments; native checks не запускались.
- 18 новых tests, всего **478**, проходят; portable clone без STL/STEP — с 3
  optional skips. Проверены partial kit, source/model hashes, relocation без
  imports repo, corruption/paths/symlinks/case, results identity/evidence/versions,
  bounded CSG execution, warning failures и сохранение предыдущих outputs.
- **Остаток: 4 блока (1, 3, 5, 6), примерно 15–25% проекта**. Блок 5 подготовлен
  к выполнению, но не закрыт. Далее — реальные native проверки по протоколу,
  исправления и full-library coverage/release.


### 2026-10-17 — полный корпус и проверяемая preview-поставка

- Предыдущий push проверен: master 30280f0 был синхронизирован.
- Все **15 464 footprints / 155 категорий** закреплённой библиотеки скачаны;
  156 078 015 source bytes проверены по Git blob SHA1, сохранены SHA256,
  полный tree и upstream license. Corpus/meshes не добавляются в Git.
- Первый полный прогон: 13 293 generated / 2 171 failed (85,96%).
  Добавлены padless graphic footprints (без искусственных electrical pins) и
  явная ASCII-token policy описаний с source retention и strict loss.
- Итог: **14 109 generated_with_loss / 1 355 failed (91,24%)**, **+816**:
  38 padless, 341 encoding и 437 quoted descriptions. Прежние успехи не потеряны;
  13 291 старый FPL byte-identical, два отличаются только description.
- Независимый аудит всех FPL: **354 192 pad records**, pinned source/report/FPL
  hashes, source numbers/multiplicity, copper shape/size/layers, drill/placement.
  2 378 files с duplicate numbers не объявляются unique component mappings.
  Unexpected errors=0; все 1 355 первых причин классифицированы.
- Полный resume: 14 109 reused, все successful FPL/report hashes неизменны.
  Fresh 131,017 с, resume 96,089 с, audit 75,400 с, peak RSS <1 GB; проверки
  выполнялись одновременно с тестами, caches не изолированы.
- Preview: 14 109 FPL по категориям, portable catalog, полный failures/audit,
  provenance/tree/license/index. ZIP **28 452 652B**; SHA256
  `1b97442050880c682623ae8e3b36160a9eee40c0e1ed00800c69e57fadca38c5`.
  CRC, extraction и verification после переноса выполнены. STL/STEP не включены,
  model references остаются внешними зависимостями; native flags false.
- **23 новых теста; всего 501** проходят. В копии без STL/STEP — 3 optional
  skips. Tracked summary и JSONL exception catalog не содержат local paths.
- Старый процент «15–25% осталось» отменён. Для первой production-поставки
  поддержанного профиля остаётся **одно приёмочное направление**: native
  roundtrip/connectivity/Gerber/physical board 3D по 10 сценариям kit и исправления
  по результатам. Среда FreePCB2/Схематор здесь пока недоступна. Полная поддержка
  исключений и всех УГО остаётся следующей явной очередью, не скрытым процентом.


### 2026-10-17 — полный корпус УГО, расширение labels/functions и candidates

- В начале push был актуален (7033665). Реализация batch/audit, pin labels и
  primary alternate functions отправлена отдельным коммитом **66633a2**.
- Закреплены **224 библиотеки / 21 806 УГО** KiCad 9.0.0, 219 889 181 source
  bytes; Git blobs/SHA256/tree/license сохранены, source files не редактировались.
- Первый полный профиль: **8779 generated / 13027 refused (40,26%)**.
  Добавлены explicit `plain-overbar-with-loss` и `primary-with-loss`; default
  reject, строгий режим запрещает потери, source/raw/alternates сохраняются.
- Повторный полный профиль: **12186 generated_with_loss / 9620 refused (55,88%)**,
  **+3407** (3045 markup-first, 362 alternate-first). Все 8779 предыдущих
  CDS/report pairs byte-identical. Unexpected errors=0, inventory missing=0.
- Independent audit: **12186 CDS / 249254 numbered endpoints**, source/current
  hashes, literal numbers/multiplicity и declared unit translations проверены.
  Пять библиотек с unsupported source stroke widths остаются typed parse refusals;
  их raw symbol names полностью учтены, resolved feature counts не заявляются.
- **533 теста** проходят, portable copy без STL/STEP — 3 optional skips. Новые
  policies проверены на неизменённых MCU_Puya/CPLD_Renesas и в component bundle.
- Preview содержит CDS, полные source/conversion/loss reports, все refusals,
  audit/provenance/tree/license/index; model assets не включены, PART сохранён.
  ZIP **107070374B**, SHA256
  `cfd949d34fc12b0369162809c9fbb18ed62e6b91dd9d47e930942c7b6f39b776`.
  CRC, extraction/relocation выполнены. Native/physical mapping flags false.
- Прогон 561,984 с, audit 265,380 с, packaging/CRC/relocation 88,960 с;
  тесты шли одновременно, caches не изолированы; peak process RSS <500 MB.
- Между двумя audited snapshots найдены **8210 exact candidates**, **6993** с
  model match по footprint audit. Ещё 2389 successful symbols без фиксированного
  Footprint, 620 number mismatches, 482 ambiguous, 343 refused FP, 142 absent FP.
  Никакие guesses/renumbering/dedup/mesh reads/назначения PART не выполнялись.
- **Без Windows до первой массовой связанной поставки — 1 крупный этап:**
  назначить actual target footprints и собрать проверяемые linked bundles по
  candidates, с current source/model checks. До 100% поддержки остаётся очередь
  1355 FP / 9620 УГО; крупнейшая группа — 6114 совпадающих pin endpoints.
  Это измеренные отказы, а не субъективный процент оставшейся разработки.


### 2026-10-17 — массовые связанные компоненты: этап 20 закрыт

- Push исходного состояния **8c2ac78** подтверждён; далее выполнена массовая
  сборка, без остановки на очередном подготовительном подэтапе.
- Новый `component_converter.mass`: повторная проверка audited CDS/FPL/reports,
  точных source identifiers и hashes; по одной source library в cache;
  общие model assets/flat aliases, полные per-component reports на диске,
  атомарная публикация нового каталога, существующий output не заменяется.
- **149 source libraries / 8 210 кандидатов / 8 210 generated_with_loss**, 0 отказов,
  **94 540** literal numbered pin/pad pairs; **878** уникальных target footprints
  с одинаковыми байтами при повторном имени. Для каждого CDS назначено имя FPL.
- **461** выбранный STL, **353 302 324** уникальных model bytes сохранены
  побайтно в canonical tree и общей import folder. Геометрия meshes не интерпретировалась,
  STEP не конвертировались. **6 993** полных model dependency sets, **1 217**
  partial/no-model. Это не claim физического совмещения 3D.
- Поставка: 25 560 indexed files / 1 616 369 336 indexed bytes плюс manifest.
  ZIP **307 265 987B**, SHA256
  `edf38976a78205886aafa01e8f887c6615ffd6a165df0a9b1bb762fb7b8cdcd8`.
  CRC/extraction/relocated verification выполнены; provenance/licenses included.
- Wall-clock наблюдения: build/final verify **1127,76 с**, archive/CRC/extracted
  verify **835,44 с**; тесты шли одновременно, caches не изолированы. RSS не
  измерен: macOS отказала `/usr/bin/time -l` в sysctl после успешной сборки.
- **9 новых тестов, всего 542** прошли; после последней проверки единственности
  FPL contents повторно прошли 51 component tests. Проверены source mutation,
  прерывание/atomic cleanup, exclusions, partial models, shared aliases,
  relocation без originals, corruption/false claims и explicit description policy.
- **Без Windows до первой связанной preview-поставки осталось 0 крупных этапов.**
  Native-приёмка остаётся пунктом 21, расширения полного покрытия — явной очередью,
  указанной выше. Субъективный процент остатка не возвращается.
