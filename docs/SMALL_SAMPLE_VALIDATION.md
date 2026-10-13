# Малая контрольная выборка

Проверка выполняется на macOS, без FreePCB2 GUI. Тесты независимо разбирают
записи `.fpl`, сравнивают координаты, формы, размеры, отверстия и apertures.
Это ещё не подтверждение загрузки библиотеки или manufacturing behavior FreePCB2.
Исходники и лицензия: [fixtures](../tests/fixtures/README.md).

## Результаты

| Образец | Проверенные значения | Результат |
|---|---|---|
| R0805 | 2 roundrect pads; X=±0.9125 мм, Y=0; 1.025×1.4 мм | Контрольный `.fpl`, без сдвига origin |
| Вариант B.* R0805 | Та же геометрия; copper/mask/paste только bottom, silk=5 | Unit test; вариация слоёв в памяти, не операция Flip и не проверка 3D |
| PinHeader_1x03_P2.54mm_Vertical | 3 PTH; X=0, target Y=0/−2.54/−5.08 мм; drill=1 мм; copper=1.7×1.7 мм; pin 1 rect, остальные circle | `.fpl`, top/bottom/общий inner_pad; существующий STL найден по точной ссылке |
| MountingHole_3.2mm_M3 | NPTH в (0,0); drill=3.2 мм; copper/paste=NONE; окружность радиуса 3.2 мм в notes=7 | `.fpl`; окружность разбита на отрезки с chord error ≤0.01 мм; plating flag в `.fpl` отсутствует |
| SOT-23 | 3 roundrect pads; target координаты (−0.9375,±0.95), (0.9375,0) мм; copper=1.475×0.6 мм; filled silk marker pin 1 | `.fpl`; маркер — замкнутая граница и 6 перекрывающихся линий, hatch=0; найден существующий STL |
| FilledCircle_Control (синтетический) | 1 rect pad в (0,0), 1.025×1.4 мм; filled circles r=0.3 мм: F.SilkS center=(1.8,−0.8), width=0; B.SilkS center=(−1.8,0.8), width=0.04 мм | `.fpl`; две границы и 60+30 scanlines, hatch=0; исходные circles в отчёте; без 3D-ссылки |

Ось Y инвертируется, `centroid` не записывается: его вычисляет target reader.
Поведение reader ещё требует ручного roundtrip. Dwgs.User и Cmts.User
преобразуются в top notes=7 с loss `USER_LAYER_APPROXIMATED`; `--strict` такую
потерю отвергает. Различие этих исходных слоёв не объявляется сохранённым.

У каждого сгенерированного реального образца остаются потери Fab/courtyard/text.
У MountingHole нет `(model ...)`: `MODEL_MISSING` ожидаем, угадывания по имени нет.
PinHeader использует существующий
`Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x03_P2.54mm_Vertical.stl`.
STL проверяется по пути и метаданным; геометрия, ориентация и высота не проверены.
То же правило используется для `Package_TO_SOT_SMD.3dshapes/SOT-23.stl`.
Варианты B.* SOT-23/R0805 — проверка слоёв, не KiCad Flip и не доказанное 3D-совмещение.

Заполненные polygon/rect поддерживаются как ограниченная аппроксимация.
Контур маркера SOT-23 в target NM: (−1300000,380000), (−1060000,50000),
(−1540000,50000), stroke=120000. Шесть горизонтальных spans имеют ту же толщину;
они сохраняют заполненную область в идеальной модели круглых концов.
`--fill-tolerance` ограничивает расширение записанной геометрии, default=0.01 мм.
Граница численно проверяется независимыми interior/exterior probes, включая
вогнутые полигоны и нулевую source width. Самопересечения/самокасания,
схлопывание на сетке и превышение лимитов дают ошибку до замены `.fpl`.
GUI rasterization и Gerber stroke settings пока не подтверждены;
допуск конвертера не гарантирует такой же допуск на готовом Gerber.

FilledCircle_Control создан в проекте для regression tests, а не взят из
библиотеки реальных компонентов KiCad. Допуск хорды адаптируется к ширине stroke:
0.00499 мм для верхней фигуры, 0.01 мм для нижней при стандартных настройках.
Толщины target strokes — 0.01996 и 0.04 мм. Проверяются покрытие номинального
диска и погрешность границы исходной фигуры: внутрь ≤curve tolerance, наружу
≤fill tolerance в идеальной stroke model. Для контрольных defaults обе
границы — 0.01 мм. `MODEL_MISSING` ожидаем; 3D-модель не угадывается по имени.

## Воспроизведение

Из корня репозитория:

```sh
python3 -B -m unittest discover -s tests -v

python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/PinHeader_1x03_P2.54mm_Vertical.kicad_mod \
  output/PinHeader_1x03_P2.54mm_Vertical.fpl \
  --default-mask-margin 0.05 --default-paste-margin 0 --default-paste-ratio 0 \
  --report output/PinHeader_1x03_P2.54mm_Vertical.report.json

python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/MountingHole_3.2mm_M3.kicad_mod \
  output/MountingHole_3.2mm_M3.fpl \
  --default-mask-margin 0.05 --default-paste-margin 0 --default-paste-ratio 0 \
  --report output/MountingHole_3.2mm_M3.report.json

python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/SOT-23.kicad_mod output/SOT-23.fpl \
  --default-mask-margin 0.05 --default-paste-margin -0.025 --default-paste-ratio 0 \
  --fill-tolerance 0.01 --report output/SOT-23.report.json

python3 -B -m src.footprint_converter \
  tests/fixtures/FilledCircle_Control.kicad_mod output/FilledCircle_Control.fpl \
  --curve-tolerance 0.01 --fill-tolerance 0.01 \
  --report output/FilledCircle_Control.report.json
```

Эти defaults — **выбранные параметры теста**, а не восстановленные параметры
исходной платы и не рекомендация для производства. Получается mask 1.8×1.8 мм
у PinHeader (rect расширяется со скруглением 0.05 мм) и mask diameter=3.3 мм
у MountingHole. Unit test отдельно проверяет NPTH без заданного margin:
там используется source size=3.2 мм с `NPTH_MASK_DEFAULT`.
У SOT-23 mask=1.575×0.7 мм, paste=1.425×0.55 мм; roundrect radius соответственно
0.2 и 0.125 мм. Эти margins также выбраны для проверки, не восстановлены с платы.

Для воспроизведения PinHeader import нужен указанный существующий STL в
`stl_files/` либо альтернативный корень через `--stl-root`. Без модели выход
будет без `openscad_code`, с явным `MODEL_MISSING`. Полный unit-test набор
воспроизводим и без каталога моделей: реальные integration tests пропускаются,
а для структурных проверок matcher создаются временные metadata-only файлы.
JSON-отчёты содержат пути компьютера и не коммитятся.

## Следующий технический шаг

Parser, внутренняя модель, writer, геометрия, matcher и отчёты разделены
на модули. CLI/API, байты всех четырёх `.fpl`, предупреждения и отчёты сохранены.
Filled circle добавлен и проверяется на отдельном синтетическом примере.
Legacy arcs добавлены в текущем этапе; результаты описаны ниже.
Native hatch не используется для подмены заливки; дальнейшие geometry primitives
добавлять после численных проверок, без пересоздания существующих STL.
Windows roundtrip всех успешных примеров и проверка 3D остаются отдельным этапом.

## Legacy arcs: Crystal_HC49-U_Vertical (2D-контроль)

Добавлен 2026-10-12 официальный исходник из KiCad Libraries 5.1.7.
Шесть legacy arcs имеют ±180°: четыре Fab и два silk. Проверяются левая/правая
полуокружности, два PTH в X=0/4.88 мм, Y=0, drill=0.8 мм и количество контуров.
Synthetic tests дополнительно проверяют ±90°, ±270°, ±360°, дробные углы,
B.SilkS, target-grid error, коллапс, дубли/смешанные definitions и безопасный отказ CLI.

У исходника есть model `(at ...)` с историческими единицами. Полная конвертация
его пока отвергает; 2D-контроль явно исключает этот record в отдельном дереве.
3D-модель не подставляется автоматически. `MODEL_MISSING` и прежние потери
Fab/courtyard/text остаются в diagnostics. Исходный файл сохранён без изменений.

Воспроизведение из корня проекта:

```sh
python3 -B - <<'PY'
from pathlib import Path
from src.footprint_converter import parse_sexpr, convert_detailed, atomic_write
source = parse_sexpr(Path('tests/fixtures/Crystal_HC49-U_Vertical.kicad_mod').read_text())
source_2d = [item for item in source if not isinstance(item, list) or item[0] != 'model']
result = convert_detailed(source_2d, 'Crystal_HC49-U_Vertical_2D')
atomic_write(Path('output/Crystal_HC49-U_Vertical_2D.fpl'), result.fpl.encode('cp1251'))
for warning in result.warnings:
    print(warning)
PY
```

### Актуальный следующий шаг

Legacy arcs, тексты, batch, source/native УГО, links, curves и ordinary
electrical profile и simple fills/body text реализованы; актуальный следующий
подпункт — power/no-connect УГО после disjoint unit layout. Windows roundtrip/
independent units/hierarchy/3D/Gerber остаются незавершёнными.

## Аудит текстов и D_SOD-123

Аудит выполнен 2026-10-12: [правила и результаты](TEXT_FIELD_AUDIT.md).
Общий набор — 105 тестов. Пять прежних `.fpl` не изменены; в HC49-U 2D
удалён только буквальный user text `%R`, теперь он явно unresolved.
JSON дополнен source policy keep_upright, original property_name и hidden fields;
для видимых source upright есть assumption о неподтверждённом target behavior.

D_SOD-123: pads 1/2 в X=−1.65/+1.65 мм, Y=0, roundrect 0.9×1.2 мм,
radius=0.225 мм. Reference в target (0,2) мм, value=(0,−2.1) мм.
Hidden Datasheet/Description не рисуются. Три F.SilkS и одиннадцать F.Fab
контуров записаны в silk=4/notes=7; courtyard пропущен с loss.
Существующий Diode_SMD.3dshapes/D_SOD-123.stl найден; ориентация/высота не проверены.

```sh
python3 -B -m src.footprint_converter \
  tests/fixtures/D_SOD-123.kicad_mod output/D_SOD-123.fpl \
  --default-mask-margin 0.05 --default-paste-margin 0 --default-paste-ratio 0 \
  --report output/D_SOD-123.report.json
```

Это выбранные defaults теста, не восстановленные manufacturing настройки.
Без STL получится результат без OpenSCAD import с loss MODEL_MISSING;
unit tests используют metadata-only файл, не mesh. С `--text-variable REFERENCE=D1`
user text экспортируется как literal D1 в notes, не динамический reference.
Следующий этап — batch CLI на малой партии; массовой конвертации пока нет.

## Пакетная малая выборка

2026-10-12: весь каталог fixtures (7 файлов) обработан batch CLI: 6 FPL
сгенерированы с известными потерями, 1 HC49-U отказ model(at). Resume переиспользует
6 результатов; failed повторяется. Общий набор — 131 тест. Это партия footprints,
не полный перенос компонентов/УГО и не оценка полной библиотеки. Подробности и
команды: [BATCH_CONVERTER.md](BATCH_CONVERTER.md).
## Контроль component links — 2026-10-13

Собран `output/components/control`: R0805/C0805/Header6, 2/2/6 pin numbers,
три existing STL snapshots. Native footprint names совпадают в CDS и FPL,
number identity проверена по source и по readback целевых записей. SHA256
подтверждает обе model copies (category tree и flat runtime aliases).
Новые C0805/PinHeader6 — unchanged official fixtures с pinned provenance.

Полный комплект содержит 17 файлов; selected original model bytes — 294 652.
Краткий результат сохранён в `output/component-control.summary.json`;
runtime bundle/models исключены из Git. Commands/schema:
[COMPONENT_BUNDLE.md](COMPONENT_BUNDLE.md). Этот контроль не подтверждает
native GUI/netlist, функции pins, механическую пригодность или alignment STL.

## Контроль curves УГО — 2026-10-13

Сохранены 7 CDS/report controls для modern/legacy curves. Численные probes
проверяют обе ориентации, >180° sweeps и centerline error после записи NM;
native cap/join/font/rendering не подтверждены. Legacy INDUCTOR endpoint
projection ~0.02544 mm сохранена как отдельный resolution loss, а не скрыта
в default tessellation bound 0.01 mm.

`output/components/curves` содержит modern L/legacy INDUCTOR/TestPoint: 3
generated mappings, 2 complete chains, 1 existing L0805 STL и явно 2D TP.
Selected model 21 384 bytes, всего 13 package files; summary —
`output/symbol-curves.summary.json`. Relocation/repeated build и старый linear
bundle byte identity проверены. [SYMBOL_CURVES.md](SYMBOL_CURVES.md).
