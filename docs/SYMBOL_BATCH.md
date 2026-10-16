# Массовый экспорт УГО в Схематор

Корпус: все **224 `.kicad_sym` библиотеки / 21 806 УГО KiCad 9.0.0**, commit
`a9012d8971ef2ea3243ffc9f19a5b4f153d8b334`. Размер исходников — **219 889 181B**.
Файлы не сокращались и не исправлялись; полный Git tree, размеры/Git blob SHA1,
SHA256, URLs и лицензия сохранены. Метрики этого этапа относятся к библиотечным
символам, включая наследованные definitions; не к количеству уникальных корпусов.

## Подготовка и полный запуск

```sh
curl --fail --location --output /tmp/kicad-symbols.tar.gz \
  https://codeload.github.com/KiCad/kicad-symbols/tar.gz/a9012d8971ef2ea3243ffc9f19a5b4f153d8b334
curl --fail --location --output /tmp/kicad-symbols-tree.json \
  'https://api.github.com/repos/KiCad/kicad-symbols/git/trees/a9012d8971ef2ea3243ffc9f19a5b4f153d8b334?recursive=1'
python3 -B -m src.library_corpus /tmp/kicad-symbols.tar.gz \
  /tmp/kicad-symbols-tree.json output/corpus/kicad-symbols-900 --kind symbols
python3 -B -m src.symbol_converter.batch output/corpus/kicad-symbols-900 \
  output/symbol-batches/full-900-final \
  --no-connect-policy connectable-with-loss --hidden-pin-policy reveal-with-loss \
  --common-pin-policy common-view-with-loss \
  --pin-name-policy plain-overbar-with-loss --alternate-pin-policy primary-with-loss
```

Эти пять режимов **выбраны явно** для диагностической поставки. Default каждого
остаётся `reject`. `--strict` отклоняет known losses; старые сохранённые CDS при
отказе остаются на диске и помечаются non-current. Exit 0 означает, что выбранные
символы сгенерированы, 2 — завершённую партию с отказами, 1 — глобальную ошибку.
Прогон всей библиотеки ожидаемо возвращает 2.

Source inventory перечисляет каждый top-level symbol до конвертации. Ошибка
нормализации одной библиотеки даёт отдельный отказ для каждого известного её
символа; остальные библиотеки продолжают работу. Если синтаксис не позволяет
получить список symbols, `inventory_failed_libraries`/`source_inventory_complete`
явно показывают неполный знаменатель. В закреплённом корпусе inventory полный.

CDS/report/state разделены. ASCII-имена стабильны по паре library+symbol,
с hash suffix; не зависят от порядка или расположения source root. Внутри run
одна библиотека нормализуется один раз. Checkpoints растут геометрически,
state сохраняется для каждого элемента, OS lock предотвращает два writer.
Пути source/model storage, symlinks и unowned outputs защищены.

`--resume` переиспользует только successful source/options/engine/output/report
hash matches, failed symbols повторяются. `--limit N` выбирает первые N
library/name identities; полный inventory при этом всё равно выполняется.
Конвертация не читает и не пересоздаёт STL/STEP.

## Два расширения профиля

KiCad определяет надчёркивание имени вывода синтаксисом `~{text}`; альтернативная
функция задаёт другое имя, electrical type и graphic style, выбираемые после
размещения. Источники: [KiCad 9, pin names](https://docs.kicad.org/9.0/en/eeschema/eeschema.html#symbol-pins)
и [alternate functions](https://docs.kicad.org/9.0/en/eeschema/eeschema.html#alternate-pin-functions).

- `--pin-name-policy plain-overbar-with-loss`: только в отображаемом имени
  pin удаляются balanced overbar wrappers. `~{RESET}` → `RESET`, `~{FO}O` →
  `FOO`. Это **потеря обозначения инверсии в имени**, а не точный перенос его
  внешнего вида. Number/type/marker/connection point сохраняются, original name
  остаётся в JSON. Loss `SYMBOL_PIN_OVERBAR_REMOVED` содержит source/displayed.
  До 4096 characters/16 nested overbar groups; malformed/legacy tilde и другие
  неподдержанные markup не угадываются. Value/reference/body text не меняются.
- `--alternate-pin-policy primary-with-loss`: используется исходная основная
  name/type/style pin; переключение на alternate modes не переносится. Все
  alternate definitions сохраняются в source JSON и loss context
  `SYMBOL_ALTERNATE_PINS_PRIMARY_ONLY`. Номера и endpoints не изменяются.

Оба режима проходят через single-symbol CLI, batch и component config
(`symbol_pin_name_policy`/`symbol_alternate_pin_policy`), включая disjoint/common
units. Strict отвергает оба loss. При отсутствии этих конструкций старые
CDS/reports не меняются. Реальные неизменённые MCU_Puya/CPLD_Renesas fixtures
закреплены отдельно; parser/raw trees и primary definitions не редактируются.

## Независимый аудит

```sh
python3 -B -m src.symbol_converter.audit output/corpus/kicad-symbols-900 \
  output/symbol-batches/full-900-final output/full-symbols/final.audit.json \
  --provenance output/corpus/kicad-symbols-900/provenance.json
```

Аудит повторно проверяет source/report/CDS hashes и читает фактические CDS
отдельным reader. Сравнивает буквальные physical numbers, multiplicity и
connection endpoints с исходными pins, с учётом объявленных integer-NM unit
translations. Только один native component на CDS, Node=[0,1], число выводов
совпадает. Compound unit inventory и common view проверяются отдельно.

Feature counts включают **разрешённые наследованием** source pin records, в том
числе failed symbols/alternate body styles. Если typed parser отказал целой
библиотеке, features этой библиотеки неизвестны и она остаётся в `library_errors`;
известные symbol identities всё равно учтены как refusals. Это не native
connectivity/ERC/GUI test и не проверка pin/pad/3D-связки.

## Проверяемая поставка

```sh
python3 -B -m src.symbol_release output/corpus/kicad-symbols-900 \
  output/symbol-batches/full-900-final output/full-symbols/final.audit.json \
  output/full-symbols/preview --archive output/full-symbols/schemator-symbols-preview.zip
python3 -B -m src.symbol_release --verify output/full-symbols/preview
```

В ZIP входят successful CDS и полные source/conversion/loss reports, catalog,
**все** refusals, audit, provenance/tree/license и integrity index. Проверяются
matching audit, current hashes, полный accounting, отсутствие unexpected errors;
failed/stale outputs не включаются. Новая папка публикуется атомарно. Hash/size,
unindexed files, symlinks/path escapes/case collisions и неподтверждённые native
claims проверяются после переноса и распаковки.

Это **библиотека несвязанных УГО**: каждый CDS пока содержит footprint placeholder
`PART`. Наличие source Footprint property не считается назначением корпуса.
STL/STEP не включены; native GUI/netlist/physical mapping flags false.

## Следующий шаг: точные кандидаты связок

```sh
python3 -B -m src.component_converter.batch_inventory \
  output/symbol-batches/full-900-final output/full-symbols/final.audit.json \
  output/batches/full-final output/full-library/final.audit.json \
  output/full-symbols/component-candidates.json
```

Проверка использует два audited snapshots: exact `Library:Footprint`, уникальные
буквальные native pin/copper-pad numbers, actual CDS/FPL hashes. Empty/wildcard
identifiers, absent/refused footprints, duplicate pads и number mismatch имеют
свои статусы. Eligible означает **кандидат для связанного экспорта**; CDS по-прежнему
содержит PART. Число model matches берётся из footprint-аудита, mesh store заново
не читается. Подбор по похожим именам, auto-dedup и назначение функций не выполняются.

Итоговые цифры: [`symbol-full.summary.json`](../output/symbol-full.summary.json).
Полные source/batch/ZIP artifacts остаются локальными и воспроизводимыми.
