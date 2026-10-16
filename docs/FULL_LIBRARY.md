# Полная библиотека: воспроизведение и preview-поставка

Проверяется вся официальная `kicad-footprints` на ревизии
`51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c`: **15 464 файла, 155 категорий,
156 078 015 байт исходных footprints**. Это точный размер закреплённого корпуса;
прежние «около 20 000» были ориентиром. Партия 120 файлов остаётся регрессией,
её процент нельзя переносить на полную библиотеку.

## Результат 2026-10-17

| Проверка | Результат |
|---|---|
| Все источники / категории | 15 464 / 155; bytes и Git blobs проверены |
| Первый полный прогон, `preserve` | 13 293 FPL, 2 171 отказ, 85,96% |
| Итоговый профиль с явной description policy | **14 109 FPL, 1 355 отказов, 91,24%** |
| Дополнительные успешные источники | **816**: 38 padless, 341 encoding, 437 quoted-description |
| Потерянные прежние успехи | **0** |
| Старые FPL | 13 291 byte-identical; ещё 2 отличаются только description по явной policy |
| Независимый readback | 14 109 FPL, **354 192 pad records** |
| Raw pads во всём корпусе | 387 314, включая failed sources |
| Дубли электрических номеров | 2 378 files; однозначный component mapping не заявляется |
| Неожиданные исключения | **0**; причины всех 1 355 отказов классифицированы |
| Resume | 14 109 reused; FPL/report hashes до и после идентичны |
| Тесты | **501** проходят; portable clone без STL/STEP — 3 optional skips |
| Preview ZIP | **28 452 652 bytes**, CRC/extraction/relocation verified |

Все 14 109 успешных outputs имеют известные losses. ZIP SHA256:
`1b97442050880c682623ae8e3b36160a9eee40c0e1ed00800c69e57fadca38c5`.
Корпус не уменьшался между прогонами. Description policy — явное изменение
профиля, а не исправление кодировки native reader; геометрия площадок, их номера
и графические тексты не переписываются. Native GUI/manufacturing/netlist/3D flags остаются **false**.

Основные первые причины отказа: custom geometry/profile 493 files,
unnamed copper pad names 255, slots 152, no supported pad/graphic 129,
justification 94, nonidentity matched-model transforms 85, fill geometry/budget
68. Это категории **первого** отказа, а не независимые подсчёты всех конструкций.
Каждый источник и сообщение сохранены в tracked
[`footprint-full.exceptions.jsonl`](../output/footprint-full.exceptions.jsonl)
и `failures.json` внутри ZIP. Отказы не считаются успешными и не маскируются.

Локальные наблюдения macOS ARM64: fresh **131,017 с**, resume **96,089 с**,
audit **75,400 с**, packaging/ZIP/extracted verification **30,251 с**.
Тесты выполнялись одновременно, caches могли быть прогреты; это не изолированное
сравнение производительности. Измеренный peak RSS процессов < 1 GB.

## Подготовка исходников

Скачивание отделено от проверки. Для подготовки нужны архив и полный Git tree
той же ревизии. В preview-комплекте сохранён исходный `source-tree.json`;
его можно использовать вместо повторного запроса API.

```sh
curl --fail --location --output /tmp/kicad-footprints.tar.gz \
  https://codeload.github.com/KiCad/kicad-footprints/tar.gz/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c
curl --fail --location --output /tmp/kicad-footprints-tree.json \
  'https://api.github.com/repos/KiCad/kicad-footprints/git/trees/51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c?recursive=1'
python3 -B -m src.library_corpus /tmp/kicad-footprints.tar.gz \
  /tmp/kicad-footprints-tree.json output/corpus/kicad-footprints-51f8a59
```

`library_corpus` принимает только новую выходную папку. Проверяет pinned SHA256
дерева, revision/truncated/count, размеры и Git blob SHA1 **каждого** footprint
и LICENSE. Сохраняет исходные байты, SHA256, URL, лицензию и дерево; не исполняет
файлы и не переносит executable bit. Links/special files, выход за root,
повторы и case-коллизии отклоняются. При ошибке неполный корпус не публикуется.
Повторный запуск должен использовать новую папку либо ранее проверенный корпус.

## Конвертация и независимый аудит

```sh
python3 -B -m src.footprint_converter.batch \
  output/corpus/kicad-footprints-51f8a59 output/batches/full-final \
  --default-mask-margin .05 --default-paste-margin 0 --default-paste-ratio 0 \
  --description-policy ascii-escape-with-loss
python3 -B -m src.footprint_converter.audit \
  output/corpus/kicad-footprints-51f8a59 output/batches/full-final \
  output/full-library/final.audit.json \
  --provenance output/corpus/kicad-footprints-51f8a59/provenance.json
```

Batch возвращает **2**, если есть изолированные отказы; это ожидаемый результат
для полной библиотеки. Только current successful outputs считаются созданными.
`--resume` проверяет engine/options/source/model metadata и output/report hashes;
неудачные записи повторяются. Аудит проверяет hashes исходников/отчётов/FPL,
каждую записанную площадку, число и буквальные номера с multiplicity,
геометрию меди/слои, drill, координаты и угол. Дубли номеров не объявляются
однозначным symbol/pad mapping.

Полный прогон выявил два исправленных ограничения:

- **Графические footprints без pads.** При наличии поддержанной геометрии
  writer создаёт `n_pins: 0`; selection bounds включают контуры и их толщину.
  FreePCB2 `Shape.cpp` rev `3af0f9b9a234c97f2d21455c936abeb8439d2d45`,
  `MakeFromFile`/`GetAllPadBounds` допускают ноль выводов и используют outline
  bounds. Выводы не добавляются. Empty/text-only/только пропущенные слои
  отклоняются; старые ограничения fill/stroke сохраняются.
- **Описания с Unicode, кавычками и control characters.** Явный
  `--description-policy ascii-escape-with-loss` заменяет их печатными токенами
  `[U+00B2]`, `[U+0022]`, `[U+000A]` и т. п. Только поле description;
  номера площадок, пользовательские надписи и имена моделей сохраняются.
  JSON содержит source/written и loss `DESCRIPTION_ASCII_ESCAPED`;
  `--strict` отклоняет потерю. Default `preserve` сохраняет прежнее поведение.
  Это не UTF-8 импорт в ANSI-программу и не молчаливая замена `?`.

Settings `.05/0/0` выбраны явно для этого диагностического профиля. Они не
восстанавливают неизвестные project-specific настройки всех исходных проектов.
Имеющиеся STL проверяются matcher только по путям/метаданным; meshes не читаются
массово и не пересоздаются.

## Сборка и проверка поставки

```sh
python3 -B -m src.library_release \
  output/corpus/kicad-footprints-51f8a59 output/batches/full-final \
  output/full-library/final.audit.json output/full-library/preview \
  --archive output/full-library/freepcb-footprints-preview.zip
python3 -B -m src.library_release --verify output/full-library/preview
```

Выходная папка/ZIP должны быть новыми. Перед сборкой повторно проверяются
совпадение audit/manifest/provenance, исходные SHA256 и текущие FPL hashes.
Failed/stale файлы исключены. Внутри:

- `libraries/<исходная категория>/<стабильное имя>.fpl`;
- `catalog.json`: исходное имя, SHA256, имя библиотеки, losses, число model links;
- `failures.json`: каждый исключённый источник и конкретная причина;
- `audit.json`, `provenance.json`, `source-tree.json`, `LICENSE.md`, `README.txt`;
- `release.json`: индекс размеров/SHA256 всех файлов, counts и scope flags.

Verifier работает с перемещённой папкой без первоначальных sources/models,
проверяет индекс, каталог и полноту accounting; rejects corruption, extra files,
links/path escapes/case collisions и неподтверждённые native claims. Сам verifier
запускается из исходников проекта; отдельный standalone checker существует
только у [native validation kit](NATIVE_VALIDATION.md).

ZIP содержит **2D preview**. Записанные model references сохранены, но STL/STEP
в него не входят: для 3D нужна соответствующая ранее полученная `.3dshapes`
папка и единицы MM. Native GUI/load-save/connectivity/Gerber/3D alignment пока
не подтверждены. Полный coverage-прогон закрывает измерение масштаба и
экспериментальную упаковку; production release требует native-приёмки.

Итоговые численные результаты и hashes хранятся в
[`output/footprint-full.summary.json`](../output/footprint-full.summary.json).
Полные исходники, batch artifacts и ZIP исключены из Git и воспроизводятся
этими командами. Исторические medium/native-kit snapshots не переписываются.
