# План разработки конвертера KiCad → FreePCB2

Обновлён 2026-10-13 по состоянию репозитория и предыдущего чата.
Цель: перенос библиотечных УГО, footprints и связей с готовыми 3D-моделями.
Около 20 000 footprints — ориентир масштаба, а не подтверждённый размер
доступных исходников. Повторно конвертировать ранее полученные 7 225 STL не нужно.

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

## Шесть крупных блоков до завершения

| № | Блок / статус | Где работать | Критерий завершения |
|---|---|---|---|
| 1 | Завершить единичные footprints — в работе | src/footprint_converter, tests/fixtures | Legacy arcs; аудит text fields; небольшая реальная выборка; все неподдерживаемые конструкции имеют явную диагностику, прежние результаты воспроизводимы |
| 2 | Пакетный CLI и отчёт покрытия — выполнен для малых партий | Новый batch-модуль поверх convert_detailed и io, tests | Изолированные ошибки, стабильные имена, manifest, resume с проверкой исходника/настроек/выхода; тестовая партия воспроизводима; нет записи в STL/STEP |
| 3 | УГО KiCad → Схематор — parser/writer, curves/pins/fills/text и disjoint-unit layout готовы с losses | src/symbol_converter, target fixtures | Source/native profiles; power/no-connect/shared units/hierarchy/geometry, import/connectivity и сравнение выборки |
| 4 | Связи компонентов и переносимый 3D-комплект — выполнен для малого MVP | src/component_converter, config/manifest | Точные identifiers, pin/pad mapping по source/CDS/FPL; явные unresolved/ambiguous; category tree + уникальные flat STL aliases; hashes и перенос без исходников проверены |
| 5 | Валидация в целевых программах — ожидает среды | FreePCB2 2.428/Схематор/OpenSCAD, docs | Load/save roundtrip, тексты и слои, NPTH/Gerber, масштабы/положение/ориентация STL; протокол и исправление найденных ошибок |
| 6 | Масштабирование и итоговая поставка — не начат | Версионированные библиотеки, batch, docs/output | Малая → средняя → полная проверенная партия; измеренное покрытие, журнал исключений, лицензии и руководство; согласованные требования закрыты |

Блок 5 можно выполнять параллельно разработке при доступной Windows.
Блок 2 можно разрабатывать до полной поддержки геометрии: ошибки остаются
явными и не считаются успешными конвертациями. Массовый выпуск результатов
начинается после проверки соответствующих форматов в целевых программах.

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
11. **Power/no-connect pins (следующий шаг).** Разделить power pins ordinary
    components, virtual power symbols и no-connect endpoints. Проверить native
    запись/Node/physical count, сохранить source/ERC semantics и explicit losses.
    Hidden/styled/alternate/shared pins расширять отдельными подтверждёнными
    профилями; GUI и hierarchy этим шагом не закрываются.

## Зависимости и ограничения

- Для блока 3 source Схематора и минимальный component profile подтверждены;
  нужны расширение units/graphics/electrical semantics и import/connectivity.
  Для блока 4 текущий MVP links/pads/STL готов; полное покрытие ограничено
  существующим symbol/footprint profile и остаётся в блоках 1/3/6.
- Для блока 5 нужна доступная целевая программа; macOS-разработка продолжается.
- Для блока 6 нужны полные KiCad libraries с зафиксированными версиями/лицензиями.
- STL/STEP используются как существующие артефакты; тысячи meshes не открываются.
- Legacy model (at ...) по-прежнему требует отдельного подтверждения единиц;
  поддержка старых дуг не означает поддержку всех исторических model records.
- Filled arcs, Bezier, сложные pads/holes/padstacks расширяются только при
  подтверждённой представимости; остальные случаи имеют явный отказ/потерю.

## Как считать оставшуюся работу

После каждого крупного шага фиксировать: результат, проверки, следующий шаг,
число незавершённых блоков и приблизительный остаток всего проекта.
На начало цикла: **6 незавершённых блоков; ориентировочно 65–75% работ осталось**.
Это инженерная оценка объёма работ, не измеренное покрытие библиотеки.
Завершение небольшого подпункта не закрывает весь блок и не уменьшает
оценку автоматически. После batch и получения эталона УГО оценку пересмотреть.

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
