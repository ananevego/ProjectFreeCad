# Матрица требований и подтверждений

| ID | Требование | Подтверждение | Текущий статус |
|---|---|---|---|
| R-01 | Читать библиотеки KiCad | Тест на эталонных `.kicad_sym` и `.kicad_mod` | Footprint subset и symbol parser реализованы; legacy cache, целые Mechanical/Comparator/Device/Connector KiCad9 fixtures с pinned hashes; pins/units/inheritance/aliases проверены; полное library coverage не измерено |
| R-02 | Преобразовывать УГО | Импорт результата в Схематор и визуальное сравнение | Source parser/straight native writer и unfilled circles/arcs готовы; NM centerline bounds, legacy resolution losses, 7 curve controls и linked L/TP проверены; ordinary electrical types готовы с ERC loss, 5 новых controls; simple fills/body text также готовы с background/font/layout losses и 6 controls; power/no-connect/units/full geometry и GUI ещё впереди |
| R-03 | Преобразовывать footprint | Импорт результата в ПлатФорм и визуальное сравнение | SMD/PTH/NPTH, тексты, слои, apertures, контуры и ограниченная аппроксимация реализованы; пять прежних реальных примеров, новые C0805/PinHeader6 в linked bundle, HC49-U в 2D и synthetic circle проверены автоматически; GUI/Gerber ещё не проверены |
| R-04 | Переносить метаданные компонентов | Сравнение атрибутов исходного и целевого объекта | Properties/raw metadata и исходные curve definitions в JSON; fields/pin numbers передаются, fonts/layout/ERC имеют losses; R/C/Header6/L/TP/SCR/Speaker/diode/meter source/CDS/FPL number identity mapping проверены, per-pin source type/record mapping в JSON; функции/netlist не проверены |
| R-05 | Вести журнал ошибок и предупреждений | Отчёт по тестовой партии | Footprint/batch/symbol reports, component manifest/reports и strict rejection реализованы; partial/missing/ambiguous/errors изолированы, текущие target artifacts при отказе не остаются |
| R-06 | Поддерживать пакетную конвертацию | Повторяемый запуск на тестовой библиотеке | Batch CLI и resume на малой партии реализованы; benchmark полной библиотеки и Windows ещё впереди |
| R-07 | Конвертировать STEP в STL | Контроль геометрии и файлового результата | Ранее получены 7 225 STL, есть исторические скрипты; модели повторно не конвертируются; геометрия на текущем этапе не проверялась |
| R-08 | Сохранять структуру каталогов 3D-библиотек | Сравнение относительных путей до и после | Bundle сохраняет selected category tree и отдельные unique flat aliases; original/canonical/runtime bytes/SHA256 сверены; source stores не изменяются; перенос без исходников проверен |
| R-09 | Привязывать 3D-модели к компонентам | Отображение модели в ПлатФорм | R/C/Header6, оба L, SCR/Speaker и diode/meter имеют complete chains с существующими STL; TP явно 2D с MODEL_MISSING; runtime aliases/hash/relocation проверены, physical alignment/native Windows-export ещё впереди |
| R-10 | Повторно запускаться без ручной настройки | Два запуска с одинаковым результатом | Контрольные FPL/JSON/CDS и два component bundle builds побайтно воспроизводимы; старые CLI/API сохранены; footprint batch/resume проверен; component bundles пока только новые каталоги |

## Недостающие данные и проверки

Разработка footprint-конвертера уже идёт; отсутствие Windows её не останавливает.
Для следующих этапов необходимы:

1. Проверка `.cds` import/connectivity/netlist в Схематоре; текущие source/target
   number mappings уже проверены для R/C/Header6/L/TP/SCR/Speaker/diode/meter. Multi-unit/merge и более
   широкий graphics и power/no-connect/hidden/alternate pin profile остаются открытыми.
2. Load/save roundtrip полученных `.fpl` в FreePCB2 **2.428**, Gerber/NPTH и физическая проверка 3D. Контракт `.fpl` уже изучен по исходникам зафиксированной ревизии.
3. Полные версии исходных KiCad libraries и измеренное покрытие. Точные
   identifiers, stable names, basename/case collisions и identity pin mapping
   готовы для малого component MVP; repeated-pad/non-identity mappings ещё не поддержаны.
4. Отдельный учёт ранее полученных 7 225 STL: факт существования не означает подтверждённую связь/трансформацию каждого footprint. Новая работа использует существующие файлы.

Практический порядок продолжения: [PROJECT_PLAN.md](PROJECT_PLAN.md).
Source symbols и проверки: [SYMBOL_CONVERTER.md](SYMBOL_CONVERTER.md).
Минимальный target writer: [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md).
Кривые и source resolution: [SYMBOL_CURVES.md](SYMBOL_CURVES.md).
Связи и переносимый комплект: [COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md).
Исходники target и незакрытые вопросы: [SCHEMATOR_FORMAT_RESEARCH.md](SCHEMATOR_FORMAT_RESEARCH.md).
