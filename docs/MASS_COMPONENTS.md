# Массовая связанная preview-библиотека

На 2026-10-17 собраны **8 210/8 210** exact candidates: каждый CDS содержит
настоящее target-имя FPL вместо `PART`. Использованы **878 разных footprints**,
**461 существующий STL**; у **6 993** компонентов найдены все видимые model
references, у **1 217** зависимости неполные или отсутствуют. Отказов экспорта
нет; все результаты содержат явно описанные потери исходного формата.

Это первая массовая связанная поставка поддержанного профиля. Основная
разработка и упаковка этого профиля завершены; Windows-приёмка остаётся
отдельным пунктом плана. Полное покрытие KiCad не заявляется: в общих партиях
отказаны 1 355 footprints и 9 620 УГО. Отдельные unlinked preview-библиотеки
с 14 109 FPL и 12 186 CDS остаются доступны.

## Что проверяется

- Актуальность двух batch manifests и соответствующих audit SHA256; текущие
  CDS/FPL/report bytes повторно читаются перед выбором candidates.
- Точные source Footprint identifiers и равенство уникальных физических номеров
  УГО и медных площадок. Числа не перенумеровываются, повторные площадки не
  объединяются; исходные модели/библиотеки не редактируются.
- SHA256 исходных библиотек и footprints перед конвертацией, в каждом созданном
  report и перед публикацией. УГО обрабатываются по одной source library,
  полные reports сохраняются на диск, а не накапливаются в manifest.
- Независимое чтение каждого нового CDS/FPL: совпадают target footprint name,
  номера pins/Cu pads и количество механических площадок. Проверены imports,
  модельные aliases, относительные пути, все file hashes и report/artifact links.
- Каждый выбранный STL копируется побайтно один раз в category tree и один раз
  в общий native import folder. Геометрия meshes не интерпретируется, STEP не
  читаются и не конвертируются. Повторные компоненты используют те же aliases.
- ZIP проверяется по CRC, затем извлекается в другой каталог и полностью
  проверяется без исходных библиотек и model storage.

`complete_model_dependencies` означает наличие и упаковку всех видимых ссылок,
а не доказанное физическое совмещение модели. Native GUI/import/netlist,
проверка board 3D и manufacturing остаются `false`. Графика, electrical/ERC
семантика и pin labels сохраняют потери, описанные в per-component report.
Отсутствующие модели не подбираются по имени похожего корпуса.

## Содержимое и использование

Локальная поставка: `output/components/full-linked/`.
Переносимый архив: `output/components/linked-components-preview.zip`.
Они исключены из Git; в Git находятся реализация, тесты, документация и
компактный `output/component-linked.summary.json`.

Скопируйте/распакуйте **весь комплект**. `manifest.json` содержит каталог
компонентов с точным source library/name, путями CDS/FPL/report и моделями.
`candidates.json` учитывает также все 13 596 невыбранных УГО с причинами.
`inputs.json` закрепляет source/audit hashes и профиль конвертации.
В `upstream/` находятся provenance и лицензии исходных УГО/footprints;
готовые STL взяты из ранее созданного локального model storage.

Для выбранного компонента загрузите его `symbol.cds` в Схематор 1.429 и
`footprint.fpl` в FreePCB2 2.428. Единицы проекта — **MM**, «Папка для Openscad»:

```text
<перенесённый комплект>/openscad_models/Bundle.3dshapes
```

Это одна папка для всех 8 210 компонентов. `models/` сохраняет исходную
категорийную структуру, но native basename imports используют flat aliases
из `openscad_models/Bundle.3dshapes`. Подробности losses — в `report.json`
каждого компонента; краткие счётчики — в `linked-summary.json`.

## Воспроизведение

Предварительно подготовьте полные pinned source corpora и audited batches:
[footprints](FULL_LIBRARY.md), [УГО](SYMBOL_BATCH.md). Нужны Python 3.10+ и
существующее хранилище `stl_files`; внешних Python-зависимостей нет.

```sh
python3 -B -m src.component_converter.mass build \
  output/corpus/kicad-symbols-900 \
  output/symbol-batches/full-900-final \
  output/full-symbols/final.audit.json \
  output/corpus/kicad-footprints-51f8a59 \
  output/batches/full-final \
  output/full-library/final.audit.json \
  output/components/full-linked

python3 -B -m src.component_converter.mass verify output/components/full-linked
python3 -B -m src.component_converter.mass archive \
  output/components/full-linked output/components/linked-components-preview.zip
```

`--stl-root PATH` меняет хранилище готовых моделей. Выход и архив должны быть
**новыми**; при повторении укажите другие пути. Публикация атомарна: при ошибке
итоговой проверки/прерывании приватный staging удаляется, готовая библиотека
не появляется. Частичное продолжение этой сборки не реализовано; существующие
аудированные symbol/footprint batches сохраняют свой отдельный resume.

Профиль наследует явные policies обоих audited batches, в том числе
`ascii-escape-with-loss` описаний FPL, `plain-overbar-with-loss` имён выводов,
`primary-with-loss` альтернативных функций, reveal/NC/common policies.
Model overrides, иные footprint curve/fill tolerances, text-variable bindings,
нештатные symbol widths и strict batches этот entry point отвергает, чтобы
не менять профиль неявно. Отдельный component exporter поддерживает
`footprint_description_policy` в config; по умолчанию сохраняется `preserve`.
