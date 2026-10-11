# Аудит текстовых полей — 2026-10-12

Исходный профиль проверен по [parser KiCad, ревизия 82b216e](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L4462)
и [разбору text effects](https://github.com/KiCad/kicad-source-mirror/blob/82b216ea7debfff69519e317dacb1b042cbdee65/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr_parser.cpp#L770).
Целевой subset проверен по [Shape.cpp FreePCB2 2.428](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L1287):
ref/value содержат геометрию native fields; user text хранит literal, size,
позицию, угол, толщину, mirror и layer. Работа GUI всё ещё не проверена.

| Исходная конструкция | Решение конвертера |
|---|---|
| reference/value (`fp_text` или `property`) | Native ref/value, без замены actual component content строкой библиотеки; hidden → размер 0 |
| `%R` / `%V` | При разрешении user text нормализуются в `${REFERENCE}` / `${VALUE}`; исходная строка остаётся в JSON |
| Переменная без explicit binding | User text пропускается с loss `TEXT_VARIABLE_UNRESOLVED`; strict отвергает эту потерю |
| `--text-variable NAME=VALUE` | Статический literal с `TEXT_VARIABLE_BOUND`; runtime substitution не обещается; recursive/unsafe bindings отвергаются |
| bare `hide`, `(hide)`, `(hide yes)` | Скрыты; поддерживаются node и effects, `(hide no)` оставляет видимость |
| Дубли/невалидные flags и размеры | Явная ошибка; конфликт hide в node/effects отвергается как неподдерживаемый профиль |
| bare/list bold/italic | Enabled отвергаются; explicit no не меняет шрифт; custom face/line spacing отвергаются |
| `unlocked` в at, в том числе без угла | Корректный разбор; source keep_upright=False сохраняется в JSON; bare legacy locked перед строкой также разбирается |
| Source keep-upright по умолчанию / `(unlocked no)` | Source policy в JSON, assumption `TEXT_UPRIGHT_UNVERIFIED` для видимых текстов; поведение при вращении детали ещё не проверено |
| Hidden дополнительные property | Сохраняются в source_texts, не выводятся; исходное имя property сохраняется без изменения регистра |
| Visible дополнительные property | Static user text с loss `TEXT_PROPERTY_FLATTENED`; редактируемая identity поля теряется |
| Overbar `~{...}` / `~...~` | User text пропускается с loss `TEXT_MARKUP_UNSUPPORTED`, включая markup в explicit binding |
| Knockout text | Явный отказ: не реализован текущим writer; наличие negative flag у target reader не считается подтверждением совместимости |
| Позиция, mirror, обычный user layer | Прежняя запись NM/Y/angle; layer losses сохранены; точное совпадение font/baseline ещё не обеспечено |

## Проверки и контрольные результаты

Набор содержит 105 тестов: 18 новых проверок аудита/реальной выборки относительно
87 тестов после legacy arcs. Проверяются булевы формы, буквальные строки `hide`/
`unlocked`, prefix locked, свойства, две группы variables, recursive/unsafe
bindings, markup, mirror/layers и отказ CLI с сохранением предыдущего `.fpl`.

Пять прежних `.fpl` (R0805, PinHeader, MountingHole, SOT-23, FilledCircle_Control)
сохранились побайтово. В HC49-U 2D изменён только один record: неверный static
`%R` удалён, теперь даётся `TEXT_VARIABLE_UNRESOLVED`.
Отчёты сознательно обогащены `source_texts.keep_upright/property_name`, hidden
дополнительными properties и assumption upright; их полное побайтовое совпадение
с предыдущей версией больше не является ожидаемым результатом. schema_version=1
сохранён, существующие ключи не удалены.

Добавлен официальный D_SOD-123 с двумя roundrect pads: X=±1.65 мм,
Y=0, 0.9×1.2 мм, radius=0.225 мм. Для выбранных тестовых defaults mask=1×1.3 мм,
radius=0.275 мм, paste равен copper. Три silk и одиннадцать Fab contours сохранены;
${REFERENCE} user text по умолчанию пропускается, explicit REFERENCE=D1 даёт literal.
Hidden Datasheet/Description отражаются в JSON. Готовый STL сопоставлен по
Diode_SMD.3dshapes/D_SOD-123.stl; его геометрия не читалась и не конвертировалась.

B.*-вариант — проверка полей/слоёв, не эталон KiCad Flip или 3D-совмещения.
Команды и source provenance: [выборка](SMALL_SAMPLE_VALIDATION.md) и
[fixtures](../tests/fixtures/README.md). Следующий этап разработки — batch CLI
поверх существующего convert_detailed с manifest/resume и изоляцией ошибок.
