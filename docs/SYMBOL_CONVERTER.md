# Исходный parser УГО KiCad

Состояние на 2026-10-12: реализован отдельный пакет `src/symbol_converter`.
Он читает библиотеку и выдаёт JSON для проверки исходных данных. Отдельный
минимальный writer `.cds` описан в [SCHEMATOR_CONVERTER.md](SCHEMATOR_CONVERTER.md);
его GUI/import ещё не проверены. Описанный здесь inspection CLI сохранён.

## Запуск

Из корня проекта, Python 3.10+; внешние зависимости не требуются:

```sh
python3 -B -m src.symbol_converter KiCad/Pickit-cache.lib \
  output/symbols/Pickit-cache.inspect.json

python3 -B -m src.symbol_converter tests/fixtures/symbols/Comparator.kicad_sym \
  output/symbols/Comparator.inspect.json \
  --symbol LM2903 --symbol LM393 --symbol LM339
```

`--symbol` повторяется; имя ищется точно, без подбора по basename. Без него
выводятся все определения библиотеки. JSON сохраняется атомарно; ошибка
чтения/выбора не заменяет прежний отчёт. Запись в исходник, его hard link,
хранилища STL/STEP и выход с расширением целевой библиотеки запрещена.
CLI не читает meshes и не создаёт 3D-модели.

| Код | Значение |
|---|---|
| 0 | Источник прочитан, выбранные УГО не имеют диагностик источника |
| 1 | Ошибка чтения, структуры, выбора символа или записи; отчёт не обновлён |
| 2 | JSON записан; есть конфликт выводов или неподтверждённая конструкция/версия |

Неверная структура одного символа пока останавливает чтение библиотеки целиком.
Изоляция таких ошибок при будущей пакетной обработке УГО — отдельная задача.

## Внутренняя модель и границы

- Размеры/координаты нормализованы в мм. Система координат исходной библиотеки
  сохранена: Y вверх; целевые повороты/инверсия не выполняются.
- Современные `.kicad_sym`: properties, pin names/numbers/types/styles,
  visibility, lengths, quarter-turn pin angles и альтернативные функции.
  Секции `NAME_UNIT_STYLE`, включая общие unit/style 0, сохраняются раздельно.
- Наследование разрешается независимо от порядка. Свойства дочернего УГО
  заменяют родительские по имени; геометрия/выводы копируются. Отсутствующая
  база, цикл, переопределение геометрии и глубина >100 явно отвергаются.
- У графики сохраняются параметры arc/circle/rectangle/polyline/bezier/text,
  width/fill и исходные effects/stroke. Аппроксимация для target не производится.
- Legacy `.lib` 2.3/2.4: DEF/Fn, aliases, footprint filters, X и S/C/P/A.
  Mils переводятся через 0.0254 мм. У дуг сохраняются отдельно углы в градусах
  и explicit endpoints, даже если историческое округление даёт несовпадение.
- Legacy aliases представлены таблицей alias → parent. При `get_symbol(alias)`
  создаётся отдельное resolved УГО с `alias_of` и Value, равным alias; исходный
  родитель не изменяется. Это проверено по официальному reader KiCad 9.0.0.
- Строки и разметка сохраняются как исходные данные. Старый `~`, overbar,
  свойства шрифта и текстовые effects не превращаются в текст Схематора.
- Legacy T нормализован (size/angle/visibility/style/justification/plain text);
  raw сохраняется. Неизвестные расширения и legacy B сохраняются в raw records с
  `SOURCE_EXTENSION_UNNORMALIZED`. Новее проверенного профиля 20241209 —
  `SOURCE_VERSION_UNVERIFIED`. Это не обещание поддержки будущего формата.
- Ошибочные числа, пропущенные обязательные properties, неизвестные pin
  types/styles, повторяющиеся имена и несовместимые unit identifiers отвергаются.
  Legacy unit count 0 и более старые header versions пока не поддерживаются.

Raw S-expression nodes либо legacy lines сохранены в каждом Symbol, Property,
Pin и нормализованной Graphic; неизвестный legacy graphic остаётся в Symbol.raw.
Metadata библиотеки сохраняется в `raw_metadata`. Raw geometry старого формата
остаётся в mils, современного — в mm; typed geometry всегда в mm.

`source_ready` означает лишь отсутствие диагностик текущего source profile.
Не все атрибуты raw records имеют typed-поля; writer должен отдельно разбирать
эффекты текста, stroke settings, metadata, привязку footprint и target losses.
Отчёт всегда содержит `target_format_verified=false`,
`target_output_generated=false`, `gui_validated=false` и
`physical_pin_mapping_verified=false`. Он не является библиотекой Схематора.

## Конфликты выводов

Проверка выполняется для каждого отображаемого unit/style с общими секциями.
Одинаковый physical number в разных секциях/альтернативных body styles разрешён.
Повтор номера в одном отображении сохраняется целиком и отмечается
`SOURCE_PIN_DUPLICATE` для одинаковых записей либо `SOURCE_PIN_CONFLICT` для
различных. Даже намеренно совмещённые выводы требуют target mapping;
автоматического удаления записей нет.

`physical_pin_numbers` — множество исходных номеров, а не проверенное
соответствие площадкам footprint. Номера могут быть буквенными (`A1`).

## Контрольная выборка

| Источник | УГО | Pin records после разрешения наследования | Результат |
|---|---:|---:|---|
| Реальный `KiCad/Pickit-cache.lib` | 27 DEF + 1 alias | 268 | 26 без source diagnostics; у PIC24 16 duplicated numbers |
| Официальный Mechanical, KiCad 9.0.0 | 11 | 9 | Все без source diagnostics |
| Официальный Comparator, KiCad 9.0.0 | 61 | 465 | Все без source diagnostics; включая LM393/LM339 и inheritance |

Количество records включает унаследованные записи в каждом derived symbol;
это не количество разных физических выводов всей библиотеки. У PIC24 —
176 records, 64 разных номера; номера 1–16 встречаются по восемь раз.

Официальные файлы сохранены **целиком и без изменений** в
`tests/fixtures/symbols`; tag/commit/bytes/SHA256 — в `provenance.json`, лицензия
и attribution — в `LICENSE.md`. Выборка не является полным покрытием KiCad.
Контрольные JSON: `output/symbols/Pickit-cache.inspect.json`,
`Mechanical.inspect.json` и выбранные LM2903/LM393/LM339 в `Comparator.inspect.json`.

Добавлены 31 тест: реальные определения, units/common styles, цепочки
inheritance, aliases, численная нормализация, графика, pin conflicts,
extensions, CLI/repeatability/protected outputs. После source этапа было 162
теста; с отдельными 31 target tests было 193. После component links и добавления
42 проверок было 235 тестов; с 31 curve tests было 266, после 19 electrical
tests было 285; body — 312, units — 336, power/NC — 359.
Добавлены markers/common pins: 398. В копии без STL/STEP
проходят те же 398 тестов с тремя явными пропусками
optional integration tests моделей. Исходники cache и контрольные FPL
сохранены в переносимой копии; новые symbol tests не требуют моделей или сети.

## Подтверждающие источники

- [Официальный формат символов KiCad](https://dev-docs.kicad.org/en/file-formats/sexpr-intro/#_symbols).
- [Официальный legacy format](https://dev-docs.kicad.org/en/file-formats/legacy-4-to-6/legacy_file_format_documentation.pdf), раздел 2.
- [Legacy reader KiCad 9.0.0](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_io/kicad_legacy/sch_io_kicad_legacy_lib_cache.cpp#L490): aliases и pin shapes/types.
- [Зафиксированные KiCad libraries](https://gitlab.com/kicad/libraries/kicad-symbols/-/tree/a9012d8971ef2ea3243ffc9f19a5b4f153d8b334), tag 9.0.0.
- [Исследование Схематора](SCHEMATOR_FORMAT_RESEARCH.md): обнаружены официальные
  исходники; минимальный straight component profile подтверждён, полный
  формат и GUI-проверка остаются открытыми.

2026-10-13: source sample дополнена целыми Device (531 definitions) и Connector
(397), той же KiCad symbols 9.0.0 revision/license. Source parser читает их
целиком; target support проверен на ограниченной выборке, не всех 928 УГО.
Modern и legacy curves/политика разрешения: [SYMBOL_CURVES.md](SYMBOL_CURVES.md).
Inspection flags по-прежнему отделены от target generation/links.
