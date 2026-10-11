# Матрица требований и подтверждений

| ID | Требование | Подтверждение | Текущий статус |
|---|---|---|---|
| R-01 | Читать библиотеки KiCad | Тест на эталонных `.kicad_sym` и `.kicad_mod` | Footprint subset и source symbol parser реализованы; 27 legacy DEF + 11 Mechanical + 61 Comparator, pins/units/inheritance/aliases проверены; полные libraries ещё нужны |
| R-02 | Преобразовывать УГО | Импорт результата в Схематор и визуальное сравнение | Source parser и минимальный straight writer `.cds` готовы; contract/readback и реальный R3 fragment проверены; R/C/connector controls созданы; полный профиль и GUI/import/connectivity ещё впереди |
| R-03 | Преобразовывать footprint | Импорт результата в ПлатФорм и визуальное сравнение | SMD/PTH/NPTH, тексты, слои, apertures, контуры и ограниченная аппроксимация реализованы; пять полных реальных примеров, HC49-U в 2D и синтетический filled circle проверяются автоматически; аудит текстов завершён для текущего subset; Windows/GUI/Gerber ещё не проверены |
| R-04 | Переносить метаданные компонентов | Сравнение атрибутов исходного и целевого объекта | Symbol properties/raw metadata сохраняются в JSON; target reference/value/pin numbers передаются, fonts/layout/ERC имеют явные losses; footprint placeholder или explicit unverified name; нужны pad mapping/component links |
| R-05 | Вести журнал ошибок и предупреждений | Отчёт по тестовой партии | Footprint JSON, batch manifest/reports/state, symbol inspection и target conversion reports/strict rejection реализованы; footprint партия 7 fixtures и 3 target УГО controls |
| R-06 | Поддерживать пакетную конвертацию | Повторяемый запуск на тестовой библиотеке | Batch CLI и resume на малой партии реализованы; benchmark полной библиотеки и Windows ещё впереди |
| R-07 | Конвертировать STEP в STL | Контроль геометрии и файлового результата | Ранее получены 7 225 STL, есть исторические скрипты; модели повторно не конвертируются; геометрия на текущем этапе не проверялась |
| R-08 | Сохранять структуру каталогов 3D-библиотек | Сравнение относительных путей до и после | Matcher сохраняет категорию `.3dshapes` в отчёте, исходные каталоги не меняет; переносимый целевой комплект ещё нужен |
| R-09 | Привязывать 3D-модели к компонентам | Отображение модели в ПлатФорм | Сопоставление существующего STL и `openscad_code` реализованы по исходникам 2.428; физическое совмещение и Windows-экспорт не проверены |
| R-10 | Повторно запускаться без ручной настройки | Два запуска с одинаковым результатом | Контрольные FPL, source JSON и R/C/connector CDS воспроизводимы; старые CLI/API сохранены; batch/resume на 7 fixtures проверен, 6 результатов переиспользуются |

## Недостающие данные и проверки

Разработка footprint-конвертера уже идёт; отсутствие Windows её не останавливает.
Для следующих этапов необходимы:

1. Подтверждённая связь УГО → footprint/pads и проверка `.cds` import/connectivity
   в Схематоре. Минимальный source contract и реальный R3 fragment уже проверены;
   multi-unit/merge и более широкий graphics profile ещё не реализованы.
2. Load/save roundtrip полученных `.fpl` в FreePCB2 **2.428**, Gerber/NPTH и физическая проверка 3D. Контракт `.fpl` уже изучен по исходникам зафиксированной ревизии.
3. Полные версии исходных KiCad libraries, правила именования, коллизий и pin mapping для связей компонентов и масштабирования batch.
4. Отдельный учёт ранее полученных 7 225 STL: факт существования не означает подтверждённую связь/трансформацию каждого footprint. Новая работа использует существующие файлы.

Практический порядок продолжения: [PROJECT_PLAN.md](PROJECT_PLAN.md).
Source symbols и проверки: [SYMBOL_CONVERTER.md](SYMBOL_CONVERTER.md).
Минимальный target writer: [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md).
Исходники target и незакрытые вопросы: [SCHEMATOR_FORMAT_RESEARCH.md](SCHEMATOR_FORMAT_RESEARCH.md).
