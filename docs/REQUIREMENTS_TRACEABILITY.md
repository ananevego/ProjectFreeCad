# Матрица требований и подтверждений

| ID | Требование | Подтверждение | Текущий статус |
|---|---|---|---|
| R-01 | Читать библиотеки KiCad | Тест на эталонных `.kicad_sym` и `.kicad_mod` | Полные закреплённые корпуса: 224 библиотеки / 21 806 УГО и 15 464 footprints / 155 категорий. Source bytes и provenance проверены; все исходники учтены в batch/audit. |
| R-02 | Преобразовывать УГО | Импорт результата в Схематор и визуальное сравнение | 12 186 CDS с явными потерями и 9 620 классифицированных отказов; 249 254 pin records проверены автоматически. Native import, connectivity, ERC и GUI ещё не проверены. |
| R-03 | Преобразовывать footprint | Импорт результата в ПлатФорм и визуальное сравнение | 14 109 FPL с явными потерями и 1 355 классифицированных отказов; 354 192 pad records проверены автоматически. Native import, Gerber и GUI ещё не проверены. |
| R-04 | Переносить метаданные компонентов | Сравнение атрибутов исходного и целевого объекта | Raw metadata и исходные определения остаются в JSON. Для 8 210 связанных CDS/FPL проверены 94 540 точных пар физических номеров; fonts/layout/ERC имеют явные losses, native функции/netlist ещё не проверены. |
| R-05 | Вести журнал ошибок и предупреждений | Отчёт по тестовой партии | Footprint/batch/symbol reports, component manifest/reports и strict rejection реализованы; partial/missing/ambiguous/errors изолированы, текущие target artifacts при отказе не остаются |
| R-06 | Поддерживать пакетную конвертацию | Повторяемый запуск на тестовой библиотеке | Полные партии, resume, независимый audit и переносимые preview-архивы проверены; Windows-приёмка выделена отдельно. |
| R-07 | Конвертировать STEP в STL | Контроль геометрии и файлового результата | Ранее получены 7 225 STL; отдельно заново преобразованы 4 реальные STEP через Gmsh 4.15.2. Бинарная структура, замкнутость, bbox, объём и повторяемость новых STL проверены; образцы осмотрены на PNG. Полное качество всех моделей и board alignment не заявляются. |
| R-08 | Сохранять структуру каталогов 3D-библиотек | Сравнение относительных путей до и после | Bundle сохраняет selected category tree и отдельные unique flat aliases; original/canonical/runtime bytes/SHA256 сверены; source stores не изменяются; перенос без исходников проверен |
| R-09 | Привязывать 3D-модели к компонентам | Отображение модели в ПлатФорм | В массовой связанной preview-поставке 461 существующий STL; у 6 993 компонентов комплект зависимостей полный, у 1 217 частичный/отсутствует. Hashes и перенос проверены; physical alignment/native board export ещё впереди. |
| R-10 | Повторно запускаться без ручной настройки | Два запуска с одинаковым результатом | Полные footprint/symbol batches проверены с resume и неизменными hashes успешных результатов. Массовая связанная сборка атомарно публикуется в новый каталог; ZIP проверен после распаковки и переноса. Старые CLI/API сохранены. |

## Недостающие данные и проверки

Разработка footprint-конвертера уже идёт; отсутствие Windows её не останавливает.
Для следующих этапов необходимы:

1. Проверка `.cds` import/connectivity/netlist в Схематоре; текущие source/target
   number mappings уже проверены автоматически для 8 210 связанных компонентов.
   NC/implicit net enforcement, repeated records/alternate modes и native
   hierarchy остаются ограничениями профиля.
2. Load/save roundtrip полученных `.fpl` в FreePCB2 **2.428**, Gerber/NPTH и физическая проверка 3D. Контракт `.fpl` уже изучен по исходникам зафиксированной ревизии.
3. Полные закреплённые исходные KiCad libraries и измеренное покрытие уже есть.
   Остались явно учтённые 1 355 footprint и 9 620 symbol refusals;
   repeated-pad/non-identity mappings не объявляются поддержанными.
4. Отдельный учёт ранее полученных 7 225 STL: факт существования не означает подтверждённую связь/трансформацию каждого footprint. Новая работа использует существующие файлы.

Практический порядок Windows-приёмки: [WINDOWS_HANDOFF.md](WINDOWS_HANDOFF.md).
Критерии рабочего конвертера и STEP → STL-проба: [WORKING_CONVERTER_ACCEPTANCE.md](WORKING_CONVERTER_ACCEPTANCE.md).
Общий план: [PROJECT_PLAN.md](PROJECT_PLAN.md).
Source symbols и проверки: [SYMBOL_CONVERTER.md](SYMBOL_CONVERTER.md).
Минимальный target writer: [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md).
Кривые и source resolution: [SYMBOL_CURVES.md](SYMBOL_CURVES.md).
Связи и переносимый комплект: [COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md).
Исходники target и незакрытые вопросы: [SCHEMATOR_FORMAT_RESEARCH.md](SCHEMATOR_FORMAT_RESEARCH.md).
