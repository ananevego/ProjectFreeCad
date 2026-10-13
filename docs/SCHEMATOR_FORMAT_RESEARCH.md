# Исходники и минимальный контракт УГО Схематора

Исследовано 2026-10-12. Найден официальный репозиторий
[niconson/Schematic-Constructor](https://github.com/niconson/Schematic-Constructor),
зафиксирован commit **e7443c374f5c8644fb3483f794a50161de60dd01**. Его существование
проверено по GitHub API; дерево полное (`truncated=false`).
Это снимает прежнее ограничение «нет исходников target», но не подтверждает
импорт или совместимость с установленным Windows-бинарником.

## Что подтверждено чтением кода

1. [SpeedFiles.cpp:107](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/SpeedFiles.cpp#L107)
   обнаруживает `.cds`, исключая служебные `bom.cds` и `tag.cds`.
2. [LibPointer.cpp:102](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/LibPointer.cpp#L102)
   хранит component ValuePackage вместе с path и merge_index;
   [DlgImportMerge.cpp:161](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/DlgImportMerge.cpp#L161)
   получает эти данные и передаёт их `FindStrInFile` для вставки/preview группы.
   Путь single-component reader/index прослежен на следующем шаге (ниже);
   общая поддержка merge в writer пока отсутствует.
3. [Documents.cpp:1462](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L1462)
   сохраняет graphics в `.cds`: component attributes, полилинии и связанные тексты.
   Начало component включает `n_pins`, `rectangle`, `ref_des`, optional
   `footprint_name` и `part_value`. Атрибуты текста имеют строку и десять чисел:
   x/y/layer/angle/font_size/stroke_width/merge/submerge/font_number/pdf_options.
   Чтение связывает attributes с polyline и завершает компонент на `part_end`.
4. [Shape.cpp:1751](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Shape.cpp#L1751)
   содержит `WriteFootprint` и padstack records. Наличие этого файла в schematic
   repo **не делает footprint FPL форматом УГО**; соответствие нужно проверять
   по реальному пути schematic import.
5. [Debug/components.txt](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Debug/components.txt)
   содержит entries вида `[prefix] value@package`, а не графику.
   [Documents.cpp:293](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L293)
   сохраняет этот список при завершении программы. Это не самостоятельный
   эталон графического УГО.

Первичные материалы доступны по pinned-ссылкам; проверенные hashes скачанных
файлов перечислены в `output/symbols/schemator-source-evidence.json`.
Файлы читались как данные; Windows-программы не запускались.

## Эталон и ограничения

Локальный `FreePCB/detector/detector.cds` имеет header 1.429 и sections
`[options]`, `[graphics]`, `[end]`; структура component/geometry соответствует
направлению чтения указанного кода. Это реальный schematic project, а не
отдельная стандартная библиотека.

Официальный `Debug/buf.cds` содержит обычные CRLF-переносы и header 1.429.
Сам факт наличия clipboard project ещё не подтверждает минимальный формат
библиотечного component. Из локального detector выделены точные bytes R3,
строки 507–528, в `tests/fixtures/schemator/Detector_R3.component.txt`.
Проверены flags/attributes/polylines и package field `1X2HDR-100`; физическое
соответствие package/pads этим чтением не подтверждается. Provenance/hashes
сохранены рядом, исходный файл сверяется тестом.
Никакие исходные `.cds` или component lists не изменены.

## Завершённый минимальный профиль — 2026-10-12

- [FreePcbView.cpp:7584](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/FreePcbView.cpp#L7584)
  `FindStrInFile` сканирует `.cds`/components, строит `[prefix] value@package`
  и вызывает `ReadGraphics` для вставки. Проверка расширения буквальная,
  поэтому writer требует lowercase `.cds`; `@` в value/package запрещён.
- [Documents.cpp:1855](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L1855)
  `ReadGraphics` читает component attrs, открытые/закрытые polylines/corners,
  привязывает `pin_name`/`description` к текущей polyline и завершает single
  component на `part_end`.
- [Documents.cpp:12217](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L12217)
  `GetNumAllPins` считает pin attributes, включая скрытые номера.
  `pin_name` — physical number, `description` — функция/имя. Connection code
  [Documents.cpp:7763](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L7763)
  проверяет Node flag внешнего конца; writer использует body first/Node=0,
  external last/Node=1. Это source verification, не native connectivity test.
- [FreeSch.h:33](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/FreeSch.h#L33)
  задаёт NM_PER_MM=1000000 и placeholder `PART`; [layers.h](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/layers.h)
  задаёт outline/name/pin/number/footprint/value/description = 6/7/8/9/12/13/14.
  [Documents.cpp:257](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/Documents.cpp#L257)
  задаёт version 1.429, как в реальном target fixture. Header units влияют на UI;
  geometry хранится в NM с Y вверх.
- [file_io.cpp:81](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/file_io.cpp#L81)
  `ParseKeyString` не поддерживает quote escaping и trim-ит строки; writer
  запрещает quotes/control/крайние пробелы. [utility.cpp:1438](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/utility.cpp#L1438)
  разбирает suffix через signed-int `atoi`; список/range semantics ограничены
  намеренно: только уникальные positive identifiers без ведущих нулей.
- [TextList.cpp:161](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/TextList.cpp#L161)
  вращает text strokes на `-m_angle`: writer меняет знак source text angle.
  [smfontutil.h](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/smfontutil.h)
  задаёт SIMPLEX=2, [TextList.h:14](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/TextList.h#L14)
  — PDF_DEF bit 0 (options=1). Exact baseline/font/justification остаются losses.

Writer и отдельный reader реализованы для `schemator-cds-straight-v1`:
single-unit, ordinary visible straight pins и unfilled rectangles/polylines;
circles/arcs поддержаны через bounded straight approximation.
R/C/CONN_01X06 controls воспроизводимы, 31 target test; после writer было 193
теста, после component links — 235, после curves — 266, electrical — 285.
Команды/ограничения/отчёты: [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md).

2026-10-13: component links и number identity mapping реализованы для малого
MVP; [COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md). Далее — расширение
units/merge/graphics. В Схематоре нужны import/load-save/font layout и
подключение проводов/netlist; `gui_validated=false` сохраняется. Полный
target contract не объявляется завершённым из-за реализации малого профиля.

2026-10-13: unfilled circles/modern+legacy arcs создаются в прежних native
records. Legacy geometry profile уточнён по KiCad9 endpoints/swap/GetRadius;
source resolution losses отделены от tessellation bound. Sources/hashes и
проверки: [SYMBOL_CURVES.md](SYMBOL_CURVES.md). Native arbitrary arc side styles,
fills/units и actual GUI этим не подтверждаются.

2026-10-13: `visible-line-electrical-v1` разрешает девять обычных electrical
types через тот же numbered endpoint. Подтверждённые writer/reader attributes
не содержат KiCad electrical-type field, поэтому ERC semantics сохраняются
только в JSON с loss. Это вывод о поддержанном record profile, не об отсутствии
любых circuit checks в программе. Primary source anchors/hashes, exact scope
и ограничения: [SYMBOL_ELECTRICAL.md](SYMBOL_ELECTRICAL.md).

2026-10-13: simple foreground fill представлен bounded straight strokes с
прежним hatch=0; background остаётся boundary-only с occlusion loss.
Modern text/legacy T представлен description на body polyline; writer/reader
и paste attributes подтверждены по Documents/TextList/FreePcbView. Literal
profile исключает native commands; fonts/layout/z-order остаются losses.
Source anchors/hashes, limits и 27 новых проверок (всего 312):
[SYMBOL_BODY.md](SYMBOL_BODY.md). Native GUI/font/fill rendering не подтверждены.
