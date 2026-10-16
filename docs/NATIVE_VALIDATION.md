# Комплект для проверки в целевых программах

Подготовлен 2026-10-17. Цели: **FreePCB2 2.428, Схематор 1.429, MM**.
Native GUI/import/netlist/Gerber и physical 3D alignment пока не проверены.
Фактически выполнены сборка/record checks, hashes, relocation, archive extraction
и CSG compilation трёх previews в установленном OpenSCAD 2021.01.

## Готовые файлы

- Каталог: `output/native-validation-ready/`.
- Архив: `output/native-validation-package/native-validation-kit.zip` —
  1908153 bytes, SHA256
  `eaa9ae83aa24381f0538e8c7cf6f0765ec7fbc10dee654cdae56ec7b898a8012`.
- Tracked summary/hash результата: `output/native-validation.summary.json`;
  scoped environment inventory: `output/native-validation.environment.json`.

Архив содержит только frozen kit, без runtime results. ZIP CRC и standalone
checker после extraction в `/tmp`/Python `-I` прошли. После распаковки можно
работать без исходного repo и model store. STL и архив остаются local/ignored;
Git содержит builder/checker, tests, controls, docs и summary. В новом клоне
готовый архив нужно воспроизвести с существующими STL или собрать partial kit.

| Состав | Количество |
|---|---:|
| Прежние component bundles | 8 |
| Сгенерированные symbol/footprint компоненты | 24 |
| Structural chains с доступным STL | 23 |
| Standalone FPL controls | 5 |
| Global unique STL aliases | 15 |
| Library-local SCAD scenes | 23 |
| Expected refusal controls | 10 |
| Manual native scenarios | 10 |

Frozen index: 251 files, 15690240 bytes до manifest.json. Глобальные STL aliases
занимают 1558560 bytes; bundles также сохраняют свои прежние canonical/runtime
копии. Это только selected existing bytes, meshes не переконвертированы.
Восемь bundles полностью совпадают с предыдущими outputs.

## Сборка и перенос

```sh
python3 -B -m src.native_validation output/native-validation-ready
python3 -B -m src.native_validation --verify output/native-validation-ready
```

Output должен быть новым каталогом; existing kit не заменяется. Source/code/
model directories защищены. Сборка идёт в staging и публикуется после checks.
Имеющийся model store выбирается через `--stl-root`. Обязательные model chains
проверяются; исключение planned 2D TestPoint задано профилем.

`--allow-missing-models` предназначен для explicit partial/2D kit: компоненты
могут быть сгенерированы, но `ready_for_3d_checks=false`, моделей и scenes меньше.
Это не полноценный комплект для 3D. На чистом клоне tests используют opaque
metadata-only assets и не отправляют их в реальный native renderer.

На Windows распакуйте весь архив, например в `C:/native-validation-kit`:

```text
py -3 -B verify_kit.py
py -3 -B verify_kit.py --init-results results/run.json
```

В FreePCB2 выберите MM и полный локальный путь `<kit>/openscad_models/Bundle.3dshapes`
как папку OpenSCAD. Общая flat папка включает aliases всех bundles; внутренние
bundles сохраняют свои отдельные folders для обратной совместимости.
FPL/CDS — CP1251, metadata/SCAD/Markdown — UTF-8. Immutable paths переносимы
между POSIX/Windows: ASCII names, без traversal/symlinks/reserved names/case
collisions. Evidence/native exports размещаются в отдельном `results/`.

`source/` сохраняет выбранные исходники в прежней структуре проекта,
`source-index.json` перечисляет snapshot. Полные symbol libraries и соответствующие
LICENSE/provenance сохранены без изменения; README/provenance могут описывать
более широкую библиотеку. Source frame/license provenance старых STL из имени
не восстанавливается; hashes подтверждают byte identity выбранных файлов.

## Что проверять

`expected-catalog.json` содержит 29 FPL entries: native name, literal pad labels,
координаты/углы, hole и pad/mask/paste records в NM; для 24 компонентов также
CDS paths и source pin mapping. 1mm=1000000NM; полная ширина pad=left+right.
Source/conversion reports поясняют geometry tolerances, text/marker/unit и ERC
losses; catalog не считается результатом native loader.

Пять standalone controls: NPTH 3.2mm, filled circles, четыре patterned styles,
точные pad reductions и synthetic TechnicalContact_Control. Последний использует
__TECH_1 без copper/hole только на F.Paste и contact1 на B.Cu/B.Mask без paste.
Carrier netlist exposure и contact semantics остаются предметом native проверки.
10 negative controls сохраняют slots/offset/nonrectangular source и refusal
reports без FPL. Средняя партия остаётся 110/120; kit не меняет эту статистику.

`protocol.json` задаёт десять сценариев и evidence/pass criteria:

1. FPL load/save/reopen и сравнение native records.
2. Слои, тексты, fills, dash/dot и native cap/join behavior.
3. Mask/paste, PTH/NPTH и hole dimensions.
4. Zero-copper carrier/contact и неожиданные electrical connections.
5. Фактические Gerber/drill files с независимым просмотром/измерениями.
6. CDS load/save/reopen, pin numbers/connection endpoints.
7. Netlist УГО→footprint в обоих приложениях.
8. Disjoint/common views, hidden/power/NC policies и declared losses.
9. Native board SCAD export, масштаб/origin/pin1/rotation/flip/height STL.
10. Перенос в другой каталог/на машину без прежних external paths.

Оригинальные sources/models ради relocation не удаляются. Native save/export
направляйте в results/, сохраняя immutable inputs. Найденные различия фиксируются
как findings; known ERC/implicit-net/hierarchy/plating losses не скрываются.

## Протокол наблюдений

`--init-results` создаёт новый JSON с manifest SHA256 и всеми statuses=not_run.
Заполните operator, observed versions, notes и evidence paths/SHA256. Возможны
passed/failed/blocked/not_run; failed/blocked требуют причины. Passed требует
operator, нужную target version (для netlist — обе), notes и существующее
непустое evidence с совпадающим SHA256. Пути ограничены results/ и безопасными
ASCII names. Повторный init не перезаписывает предыдущий протокол.

```text
py -3 -B verify_kit.py --results results/run.json
```

Checker проверяет структуру/hashes/kit identity, но не удостоверяет действия
оператора и содержание screenshots. Immutable native flags остаются false;
наблюдения существуют отдельными records. Без `--results` проверка целостности
не делает вывода о native status. Exit0 — согласованный kit/protocol, а не
производственная сертификация; --results возвращает2 при failed/blocked.

## Выполненная часть OpenSCAD и окружение

Локально установлен OpenSCAD **2021.01**. Через его native CLI скомпилированы
C0805/Header6/R0805 library-local scenes: **3/3 CSG**, без warnings. Три CSG
outputs/probe.json хранятся только в runtime results; scoped probe также включён
в tracked summary. Остальные 20 scenes подготовлены, не объявляются выполненными.

```text
py -3 -B verify_kit.py --compile-openscad C:/path/openscad.exe --run-id csg-new
```

По умолчанию команда компилирует все имеющиеся scenes; `--scene control.R0805`
ограничивает выбор. Subprocess без shell, version timeout20s, scene timeout30s,
nonzero exit/warnings/отсутствующий output дают failure. Старые run directories
не заменяются. Эта команда не изменяет manual observations. CSG может содержать
абсолютные пути запуска, поэтому после relocation компилируйте заново.
CSG compilation не является STL remesh, mesh validation, GUI, native board export
или доказательством physical alignment. Все соответствующие flags=false.

FreePCB2/Схематор не обнаружены в проверенных workspace/Applications/PATH locations;
wine/wine64 не найдены в PATH. Elevated readonly VirtualBox inventory подтвердил
один Debian ARM64 guest (poweroff), Windows guest не зарегистрирован. Первый
sandbox query дал IPC error; это исправлено уточняющим read-only запросом.
Inventory не исключает unregistered/remote environments. GUI проверки не запускались.

18 новых tests, всего **478**, проходят; копия repo без STL/STEP — с 3 optional
integration skips. Проверены full/partial model presence, source hashes, 2D
controls/refusals, isolated standalone relocation, corrupt index/paths/symlinks/
scope, results identity/versions/evidence и bounded/warning-sensitive CSG calls.

Далее — фактический протокол в целевых Windows-программах, исправления и полная
библиотека. **Остаток: 15–25% проекта, четыре блока**; подготовка kit не закрывает
native validation.
