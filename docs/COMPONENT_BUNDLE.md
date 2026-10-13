# Связи компонентов и переносимый комплект

Состояние на 2026-10-13: `src/component_converter` собирает библиотечные
связки УГО → footprint → существующий STL. Проверяются точные идентификаторы,
номера выводов/площадок, записи созданных CDS/FPL и SHA256 копий моделей.
Это проверка библиотечных связей, не перенос схемы Pickit или её netlist.
GUI/import/connectivity, назначение функций выводов и физическое совмещение
3D ещё не подтверждены.

## Запуск

Из корня проекта, Python 3.10+, внешних зависимостей нет:

```sh
python3 -B -m src.component_converter tests/fixtures/components/control.json \
  output/components/control
python3 -B -m src.component_converter --verify output/components/control
```

`--stl-root PATH` задаёт хранилище готовых моделей, по умолчанию `stl_files`.
Входные пути в config разрешаются относительно самого config. Выходной каталог
должен быть **новым**: существующий комплект никогда не перезаписывается.
Для второго запуска выберите новый каталог; результаты воспроизводимы побайтно.

| Код CLI | Значение |
|---|---|
| 0 | Все компоненты сгенерированы или комплект прошёл проверку; известные потери перечислены |
| 1 | Ошибка config/публикации, существующий/защищённый выход или нарушение целостности |
| 2 | Manifest записан/проверен; есть unresolved, ambiguous, failed или strict rejection |

По умолчанию нужны все видимые model references и существующий непустой STL.
`--allow-missing-models` разрешает результат без отсутствующих моделей:
`source_target_mapping_verified=true`, но `chain_complete=false`, и диагностика
missing/unresolved остаётся в отчёте. Код 0 при этой опции означает наличие
библиотечных выходов, не полную 3D-связь. `--strict` отклоняет известные losses;
текущий writer УГО всегда имеет font/layout losses, поэтому controls отвергаются.

## Config v1

```json
{
  "schema_version": 1,
  "footprint_libraries": {"Resistor_SMD": "../Resistor_SMD.pretty"},
  "aperture_defaults": {"mask_margin": 0.05, "paste_margin": 0, "paste_ratio": 0},
  "components": [{
    "id": "R0805",
    "symbol_library": "../Device.kicad_sym",
    "symbol": "R",
    "footprint": "Resistor_SMD:R_0805_2012Metric",
    "reference": "R1"
  }]
}
```

`footprint` можно опустить только при непустом точном source Footprint property.
Explicit config assignment сохраняется вместе с исходным property; filters,
basename или похожие имена не используются для догадки. Проверяются namespace,
точный filename `.kicad_mod` и совпадение root name с выбранным identifier.
Неизвестные JSON fields, duplicate keys/ids (включая Windows case folding),
неверные типы и nonfinite settings отклоняются до публикации.

Опциональный `symbol_curve_tolerance` задаёт mm-допуск unfilled circles/arcs
УГО (default 0.01, finite >0.00001 и <=1); native output остаётся straight
polylines. Legacy resolution и его radius/endpoint losses учитываются
отдельно. Curve controls/политика: [SYMBOL_CURVES.md](SYMBOL_CURVES.md).

Опциональный `model_transform` на компоненте содержит ровно три вектора:
`translation`, `rotation`, `scale`. Он задаёт **полную** target transform в
mm/degrees/unitless и заменяет source transform, как в footprint API.
Неединичная source transform без explicit override отклоняется; наличие
override не подтверждает правильность геометрии/ориентации готового STL.

Mapping требует равенства множества source pin numbers и электрических pad
numbers, без удаления повторов внутри rendering или нескольких pads одного
номера. Такие повторы получают `ambiguous`; несовпадения — `unresolved` с
missing/extra lists. Механические NPTH исключаются из электрического множества.
Source номера в разных units разрешены, alternate styles должны иметь одинаковое
физическое множество; native writer пока поддерживает только один unit.
Функции выводов, механическая пригодность корпуса и ERC этой проверкой не доказаны.

## Содержимое комплекта

```text
manifest.json
README.txt
components/c_<id>_<hash>/symbol.cds
components/c_<id>_<hash>/footprint.fpl
components/c_<id>_<hash>/report.json
models/<category>.3dshapes/<original>.stl
openscad_models/Bundle.3dshapes/mdl_<label>_<path-hash>.stl
```

Native footprint name детерминированно строится из полного `Library:Footprint`;
оно одинаково в `footprint.fpl` и CDS `footprint_name`. Успешная запись проходит
независимый readback CDS/FPL: identity номера, число pins/NPTH, namespace name
и imports. Component report сохраняет source hashes, selection/property,
mapping/occurrences, original model references, source attributes и losses.

STL читаются только для byte copy/hash, не для анализа meshes. Копируются лишь
выбранные модели. `models/` сохраняет категории/имена исходного хранилища;
отдельная runtime copy имеет уникальный ASCII basename, включающий hash полного
пути. Поэтому одинаковые basenames разных категорий не перезаписываются.
Windows-небезопасные paths и case collisions получают явный `ambiguous`.
Обе копии имеют одинаковые bytes/SHA256; несколько ссылок используют общий asset.
Original source files не меняются; STEP→STL не запускается.

Для моделей нескольких категорий writer получает **копию** parser tree, где
только model paths заменены на aliases общей runtime папки. Geometry и source
transforms не меняются; original paths/attributes остаются в report. Это
обходит ограничение отдельных категорий без изменения старого footprint API.

В FreePCB2 2.428 OpenSCAD export копирует `3d_folder + basename`, не создавая
дерево подкаталогов ([Shape.cpp:4687](https://github.com/niconson/FreePCB-2/blob/3af0f9b9a234c97f2d21455c936abeb8439d2d45/Shape.cpp#L4687)).
После копирования всего комплекта на Windows выберите в программе «Папка для
Openscad» = полный Windows path к `openscad_models/Bundle.3dshapes`, единицы MM.
Manifest хранит относительный путь настройки; `.fpl` не выдаёт project-global
`3d_folder` за свой локальный атрибут. Этот шаг пока не проверен в native GUI.

## Публикация и проверка

Работа идёт в private staging directory рядом с выходом. Ошибка одного
компонента не останавливает остальные: остаётся report, target files этого
item и новые неиспользуемые assets удаляются. Источники/model stores защищены.
После сборки проверяются все файлы/ссылки; каталог публикуется одним rename.
При глобальной ошибке незавершённый комплект не публикуется. Resume/replace
для component bundles пока отсутствуют; footprint batch CLI сохранён.

`--verify` работает без оригинальных библиотек и STL root: сверяет file index,
SHA256/size, canonical/runtime copies, CDS/FPL numbers/names/imports, reports,
summary и verification scope. Лишние files, symlinks и path traversal отклоняются.
Это consistency/integrity check, не цифровая подпись происхождения manifest.

`source_target_mapping_verified` становится true только для сгенерированных и
прочитанных обратно outputs. `pin_mapping.verified` отдельно отражает source
numbers check и может быть true при последующем отказе writer. В linked symbol
report `physical_pin_mapping_verified=true` имеет явный ограниченный scope;
native import/netlist/GUI и model geometry/frame flags остаются false.

## Контроль и тесты

| Binding | Source symbol | Footprint | Pins | Existing STL bytes |
|---|---|---|---:|---:|
| R0805 | legacy R | Resistor_SMD:R_0805_2012Metric | 2 | 15 084 |
| C0805 | legacy C | Capacitor_SMD:C_0805_2012Metric | 2 | 21 384 |
| Header6 | legacy CONN_01X06 | Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical | 6 | 258 184 |

Три complete chains; 17 файлов в комплекте, включая manifest, 3 CDS/3 FPL,
3 component reports, README и 6 STL copies. Выбраны 294 652 bytes исходных
моделей; структура и aliases сохраняются двумя копиями. Все outputs имеют
известные losses. Это manually assigned библиотечная выборка, не BOM Pickit.
Новые официальные C0805/PinHeader6 fixtures закреплены на KiCad revision
`51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c`, без изменений; hashes/URL —
`tests/fixtures/components/provenance.json`, лицензия — `tests/fixtures/LICENSE.md`.

42 новых теста: complete/partial chains, duplicates/NPTH/units, missing data,
настоящий перенос без исходников, basename/case conflicts, model transforms,
byte preservation, fault injection/rollback, checksums и record corruption,
protected outputs и CLI. После component stage было **235**, после curves —
266; после electrical — **285 тестов**, проходят и в копии без STL/STEP
с 3 optional integration skips. Tests создают fake opaque model bytes только
во временном каталоге; контрольный комплект использует существующие реальные STL.

Bundle runtime не коммитится: `.gitignore` исключает `output/components/`.
Воспроизводимый config и `output/component-control.summary.json` сохраняются
в Git. Далее: расширение УГО/footprint coverage, затем native GUI и полный масштаб.

Дополнительная партия `components/curves.json`: modern L, legacy INDUCTOR и
TestPoint с unfilled curves, `symbol_curve_tolerance=0.01`. Runtime command
добавляет `--allow-missing-models`: два L имеют complete chains и один общий
existing L0805 STL; TP — явно 2D (source footprint без модели), mapping true,
chain_complete false. Сохранён `output/symbol-curves.summary.json`; relocation/
repeat проверены, предыдущий linear bundle остаётся byte-identical.

Партия `components/electrical.json`: generic SCR_AGK → SOT-23 и Speaker →
CUI CMR-1206S-67. Две complete chains, два existing STL (263 268 source bytes),
12 package files; summary `output/symbol-electrical.summary.json`. Номера
1/2/3 и 1/2 проверены по source/CDS/FPL. `pin_semantics.electrical_rules_transferred`
остаётся false даже при `physical_pin_mapping_verified=true`: ERC правила
не переданы, физическая пригодность generic SCR корпуса не подтверждена.
Controls/strict/relocation и ограничения: [SYMBOL_ELECTRICAL.md](SYMBOL_ELECTRICAL.md).

Партия `components/body.json`: D_Filled → D_SOD-123 и Ammeter_DC → Header2.
Две chains, два existing STL (126368 source bytes), 12 package files; summary
`output/symbol-body.summary.json`. `symbol_fill_tolerance` — optional config
setting в mm, default .01, `.00002 < value <= 1`; распространяется только на
УГО. `filled_graphics`/`graphic_texts` имеют independent record indices;
body text не добавляет electrical pins. Mapping true подтверждает только
номер 1/2, physical suitability meter/header и native GUI не проверены.
Общий набор — 312 тестов; старые три bundles неизменны. [SYMBOL_BODY.md](SYMBOL_BODY.md).
