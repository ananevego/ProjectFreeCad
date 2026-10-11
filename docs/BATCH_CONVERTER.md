# Пакетный конвертер footprints

Реализован 2026-10-12 поверх существующего `convert_detailed`; одиночные CLI/API
сохранены. Python 3.10+, стандартная библиотека, внешние зависимости не нужны.
Это пакетная генерация самостоятельных `.fpl`, а не объединение в одну библиотеку.
Конвертация УГО и полный перенос компонентов остаются отдельными этапами.

## Запуск

Из корня проекта; на Windows `py -3` вместо `python3`:

```sh
python3 -B -m src.footprint_converter.batch \
  tests/fixtures output/batches/control \
  --default-mask-margin 0.05 --default-paste-margin 0 --default-paste-ratio 0

python3 -B -m src.footprint_converter.batch \
  tests/fixtures output/batches/control \
  --default-mask-margin 0.05 --default-paste-margin 0 --default-paste-ratio 0 \
  --resume
```

Эти defaults выбраны для теста и не восстанавливают настройки исходной платы.
В текущей выборке 7 файлов, 6 генерируются с потерями, один HC49-U имеет
неподдерживаемый legacy model `(at ...)`. Поэтому оба запуска возвращают код 2.
Это ожидаемая диагностика полного официального исходника; отдельный ранее
полученный HC49-U 2D контроль не подставляется вместо него автоматически.

| Код CLI | Значение |
|---|---|
| 0 | Все выбранные footprints сгенерированы; известные потери возможны без strict |
| 1 | Глобальная ошибка input/config/path/manifest/lock; партия не завершена |
| 2 | Партия завершена, есть failed или rejected_loss |

Поддерживаются `--stl-root`, `--encoding`, `--strict`, допуски curve/fill,
mask/paste defaults, `--text-variable` и полное явное model transform — как
у одиночного CLI. `--limit N` выбирает первые N путей в стабильном порядке.
`--name` отсутствует: каждому исходнику назначается собственное уникальное имя.
Обнаружение рекурсивное, только `.kicad_mod`; symlink-каталоги не обходятся,
symlink-файлы получают индивидуальный отказ. Пустая выборка — глобальная ошибка.

## Результаты и имена

```text
output/batches/control/
  manifest.json
  .batch.lock
  footprints/fp_<source-label>_<path-hash>.fpl
  reports/fp_<source-label>_<path-hash>.report.json
  state/fp_<source-label>_<path-hash>.json
```

Имя: безопасный ASCII-префикс `fp_`, до 60 символов label и первые 16 hex-символов
SHA-256 **от относительного source path**. В target `.fpl` используется это же имя,
поэтому одинаковые root names/basenames из разных `.pretty` библиотек не смешиваются.
Исходное имя footprint сохранено в manifest `source_footprint`. Добавление файла
и изменение порядка обхода не переименовывают прежние элементы. Коллизия
сгенерированных имён проверяется до записи; перемещение source path меняет имя.

`manifest.json` schema_version=1, kind=footprint_batch содержит input/output roots,
настройки и fingerprint, discovered/selected, записи элементов, summary, ownership
и not_selected_previous_sources. Это новый формат, независимый от schema_version
одиночного report. `.report.json` сохраняет прежний подробный conversion report.
`state/*.json` содержит данные переиспользования для одного элемента.
Все batch artifacts в `output/batches/` исключены из Git: в них есть локальные пути.

Для каждого элемента: source, target_name, output/report/state paths, status,
output_current, хеш исходника, зависимости моделей, diagnostics и errors при отказе.
Успешный элемент имеет хеши выходного файла и отчёта; `reused` описывает этот запуск.

| status элемента | Смысл |
|---|---|
| pending | Не обработан в последнем snapshot manifest |
| generated | Сгенерирован без известных потерь; assumptions остаются возможны |
| generated_with_loss | Сгенерирован с перечисленными потерями |
| rejected_loss | Strict запретил известную потерю |
| failed | Ошибка source/parser/pipeline/записи |

Summary отдельно считает generated_without_known_loss, generated_with_loss,
failed, rejected_loss, pending и reused. `diagnostic_item_counts` — число
footprints с каждым кодом, не число повторений предупреждения внутри footprint.
`generation_percent` — доля generated + generated_with_loss **в выбранной партии**.
Это не измерение полной библиотеки, точности, GUI-совместимости или готовности проекта.
`target_gui_validated=false` остаётся явным.

## Повторный запуск и восстановление

Без `--resume` выбранные элементы конвертируются заново. С `--resume` successful
result переиспользуется только при совпадении:

- SHA-256 исходных bytes и всех conversion options, включая encoding/strict/bindings;
- fingerprint Python-модулей конвертера (изменение кода отменяет cache);
- metadata candidates STL: разрешённый путь, наличие, size/mtime/ctime/inode;
- SHA-256 текущего `.fpl` и `.report.json` с сохранёнными хешами.

Дерево S-expression читается для определения model dependencies; тяжёлые стадии
conversion/tessellation/writer при reuse пропускаются. Missing STL тоже учитывается:
его появление/удаление отменяет cache. Mesh contents не открываются; это проверка
метаданных, не геометрии или полного хеша STL. Изменение irrelevant hidden model
может дать консервативный extra rerun. Failed/rejected results всегда проверяются заново.
Повреждённый/missing output/report/state приводит к повторной конвертации.

Перед записью фиксируются planned paths и ownership в initial manifest.
Каждый результат атомарно записывает FPL, report и затем state по отдельности.
Таким образом, state — commit record; несколько файлов не являются общей
транзакцией. Прерывание до state заставляет повторить этот элемент. Успешные state
восстанавливаются даже если очередной manifest snapshot ещё не записан.
Полные snapshots делаются после 50, 100, 200, ... элементов и в конце, чтобы
не переписывать большой manifest после каждого файла; между snapshots entries
могут показывать pending, хотя state уже готов. У завершённой партии pending=0.
Атомарность замены не объявляется гарантией сохранности при сбое питания.

Ошибки одного footprint не прерывают соседние. Неожиданные исключения pipeline
также записываются как failed с error_type/unexpected_error; их следует изучать
как ошибки реализации. KeyboardInterrupt/SystemExit не поглощаются.
Manifest/lock/configuration failure остаётся глобальным отказом, с последующим
восстановлением через `--resume`.

## Границы записи и оставшиеся файлы

Input/output должны быть непересекающимися каталогами. Запись в source/STL/STEP
storage, внешние symlink targets и symlink artifact directories запрещена.
Неподтверждённый существующий artifact не перезаписывается; corrupt/foreign
manifest требует отдельного output directory либо восстановления manifest.
OS advisory lock позволяет только одну cooperating batch-запись в output root.
Lock освобождается при выходе или гибели процесса; оставшийся `.batch.lock` —
обычный файл, его существование само по себе не блокирует resume.

Если повторная конвертация отказала, прежний `.fpl` может остаться на диске;
`output_current=false`, он не учитывается в generated и не должен попадать
в поставку по текущему manifest. Ошибка записи report/state тоже делает результат
failed и не подтверждает его как готовый. Не выбирать результат glob-ом по каталогу:
для поставки брать только successful entries с output_current=true.
Удалённые/не выбранные из-за limit sources и их artifacts не удаляются автоматически;
ownership сохраняется для их будущего возвращения.

## Контроль 2026-10-12

131 тест, включая 26 новых batch-проверок. Проверены ошибки/strict, collisions,
стабильность имён, input/options/engine/model invalidation, intact artifact reuse,
повреждение файлов, прерывание в двух местах, ошибка записи report, ownership,
защищённые пути, symlinks, lock и CLI exit codes.

Реальная малая партия:

| Источник | Результат |
|---|---|
| Crystal_HC49-U_Vertical | failed: legacy model(at), ожидаемая несовместимость |
| D_SOD-123 | generated_with_loss |
| FilledCircle_Control | generated_with_loss; synthetic, без модели |
| MountingHole_3.2mm_M3 | generated_with_loss; source без модели |
| PinHeader_1x03_P2.54mm_Vertical | generated_with_loss |
| R_0805_2012Metric | generated_with_loss |
| SOT-23 | generated_with_loss |

Первый запуск: 6 generated, 1 failed. Resume: 6 reused, 1 failed retried.
Существующие модели не переконвертированы. Производительность на 20 000 элементах
и Windows locking/GUI ещё не подтверждены; средняя и полная партии относятся
к этапу масштабирования после проверки target behavior.
