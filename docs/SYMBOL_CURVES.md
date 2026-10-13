# Окружности и дуги УГО

Состояние на 2026-10-13: writer поддерживает незаполненные окружности modern/
legacy и дуги `.kicad_sym`/`.lib`. Они становятся straight body polylines слоя 6;
окружности — closed outlines. Native record profile остаётся
`schemator-cds-straight-v1`, source graphics profile — `unfilled-curves-v1`.
Все body corners имеют style=0/Node=0; электрические pin records не меняются.
GUI, caps/joins, fonts и native netlist этим этапом не проверены.

## Запуск и допуск

```sh
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Device.kicad_sym \
  output/symbols/L_curves.cds --symbol L --curve-tolerance 0.01
python3 -B -m src.symbol_converter.write tests/fixtures/symbols/Connector.kicad_sym \
  output/symbols/TestPoint_curves.cds --symbol TestPoint
python3 -B -m src.symbol_converter.write KiCad/Pickit-cache.lib \
  output/symbols/INDUCTOR_curves.cds --symbol INDUCTOR
```

Python API `convert_symbol(..., curve_tolerance=0.01)`. Значение — mm,
finite, `0.00001 < tolerance <= 1`. NaN/inf/bool и неверный диапазон вызывают
отказ до записи. CLI exit/strict/path protection сохранены. Известные font/
layout losses по-прежнему отклоняются strict, дополнительно учитываются legacy
resolution losses. Два файла CDS/JSON записываются атомарно по отдельности.

В component config опциональный `symbol_curve_tolerance` задаёт тот же допуск:

```sh
python3 -B -m src.component_converter tests/fixtures/components/curves.json \
  output/components/curves --allow-missing-models
python3 -B -m src.component_converter --verify output/components/curves
```

Bundle destination должен быть новым. В controls TestPoint выбран явно как
2D-компонент: официальный pad footprint не имеет model reference. Его связь
номеров проверена, `chain_complete=false` и MODEL_MISSING сохранён. Два L
bindings имеют полные связи с существующим STL; отсутствие модели TP не
объявляется успешной 3D-связью.

## Современная геометрия

Circle использует source center/radius. Arc вычисляет окружность по
start/mid/end, выбирая направление и большую/малую дугу через midpoint;
оба endpoint сохраняются до округления в NM. Вычисления выполняются в локальном
frame, source Y up не инвертируется. Перевод Y footprint не применяется к УГО.

Используется существующий `sample_arc`/`arc_points` footprint geometry module,
без изменения footprint API или алгоритмов. Шаг ограничивается по sagitta:
`radius * (1 - cos(delta / 2))`; 0.00001 mm зарезервированы для численной
погрешности и финального округления координат. Максимальный шаг — 45°.
CDS coords округляются до 1 NM; circle не повторяет первый corner в конце:
closed outline добавляет последний segment сам.

Report `curves[]` содержит unit/graphic/polyline indices, разрешённые center/
radius/start/sweep, closed flag, corner/segment counts и upper error bound.
`SYMBOL_CURVE_APPROXIMATED` — approximation, не заявление точной native curve.
Допуск относится только к **centerline разрешённой кривой**; caps/joins и
rasterization помечены `SYMBOL_CURVE_STROKE_UNVERIFIED`. Width/default stroke
и font/layout policies остаются прежними и имеют свою диагностику.

## Legacy `.lib`: отдельная политика разрешения

Старый arc содержит center/radius/angles и может содержать explicit endpoints,
которые не лежат точно на объявленной окружности. Просто использовать signed
angle difference или принудительно сохранять оба конца было бы неоднозначно.
Зафиксирован reference profile KiCad **9.0.0**:

- [loadArc/MapAnglesV6](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/eeschema/sch_io/kicad_legacy/sch_io_kicad_legacy_lib_cache.cpp#L789)
  читает explicit endpoints либо вычисляет их из углов, затем определяет swap;
  perturbation 0.1° существенна для выбора стороны при 180°.
- [CalcArcAngles/GetRadius](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/common/eda_shape.cpp#L824)
  определяет sweep по endpoint directions, radius по start после swap.
- [base_units.h:72](https://github.com/KiCad/kicad-source-mirror/blob/9.0.0/include/base_units.h#L72)
  задаёт 10 000 schematic IU/mm (100 nm); KiROUND ties away from zero.

Writer воспроизводит эту математическую политику в source Y-up frame:
clockwise traversal после swap, radius округляется до schematic IU, end direction
проецируется на этот radius. Совпадающие направления образуют ring, не null arc.
Integer mils/tenth-degree fields обязательны для legacy curves. Collinear/
coincident modern definitions, degenerate endpoints/radius, collapsed NM points
и нестабильные вычисления вызывают отказ.

`legacy_resolution` сохраняет исходные endpoints в разрешённом порядке,
resolved endpoints, swap flag, explicit/derived flag, radius difference и
endpoint shifts. Они **не спрятаны в tessellation tolerance**. При изменении
radius/endpoint больше 1 nm `SYMBOL_LEGACY_ARC_RESOLVED` имеет severity loss;
иначе — assumption. Original geometry/raw records остаются в source JSON.

Например, у первого INDUCTOR arc из cache end projection меняет stored endpoint
примерно на **0.02544 mm**, больше default 0.01 mm. Report отдельно показывает
этот resolution loss и bound 0.01 mm аппроксимации уже разрешённой окружности.
У CP1 nominal radius отличается от resolved radius на 0.0016 mm. Это explicit
profile чтения/геометрии; совпадение с каждым renderer/export path или native
GUI KiCad/Схематора не заявляется.

Источник native records — pinned Schematic-Constructor, [PolyLine.h:104](https://github.com/niconson/Schematic-Constructor/blob/e7443c374f5c8644fb3483f794a50161de60dd01/PolyLine.h#L104).
Используется прежний подтверждённый straight representation, не предполагается
произвольный center/radius/sweep record для native ARC_CW/ARC_CCW styles.
Source URLs/hashes/anchors — `output/symbols/curve-source-evidence.json`.

## Ограничения и совместимость

- Для `unfilled-curves-v1` — `fill none`, standard single-unit body, ordinary line pins.
  Simple fills/background loss и graphic text теперь имеют отдельный
  [body profile](SYMBOL_BODY.md). Filled arcs/Bezier, power/no-connect/hidden/styled pins,
  alternates, shared/power/virtual units и source diagnostics остаются отказами.
  Disjoint unit layout с rebased curve metadata: [SYMBOL_UNITS.md](SYMBOL_UNITS.md).
- До 4096 corners на curve, до 32 768 body corners суммарно. Дегенерация или
  слишком малый допуск вызывает отказ; молчаливого ослабления допуска нет.
- Source/derived center/radius/points ограничены signed 32-bit NM range;
  extremely flat arcs с огромным derived radius пока отклоняются.
- Старые R/C/CONN_01X06 CDS **и reports** побайтно/структурно воспроизводимы;
  curve metadata добавляется только при наличии curves. Исходный JSON inspection
  CLI и прежний component bundle остаются совместимыми и неизменными.

## Реальные controls и проверки

Полные неизменённые Device (531 symbols) и Connector (397) из KiCad symbols
9.0.0, commit `a9012d8971ef2ea3243ffc9f19a5b4f153d8b334`, сохранены в fixtures.
Tag/URL/bytes/SHA256 и license/attribution находятся в `symbols/provenance.json`
и `symbols/LICENSE.md`. Это source sample, не заявленное target coverage 928 УГО.

| Сохранённый stem в `output/symbols` | Source | Pins | Curves |
|---|---|---:|---:|
| L_curves | Device:L | 2 | 4 |
| L_Small_curves | Device:L_Small | 2 | 4 |
| C_Polarized_US_curves | Device:C_Polarized_US | 2 | 1 |
| TestPoint_curves | Connector:TestPoint | 1 | 1 |
| Conn_Coaxial_curves | Connector:Conn_Coaxial | 2 | 3 |
| INDUCTOR_curves | legacy INDUCTOR | 2 | 4 |
| CP1_curves | legacy CP1 | 2 | 1 |

Все семь CDS/report controls воспроизводятся. Curve bundle содержит 3 linked
components, 2 complete chains, 1 общий STL asset (21 384 original bytes) и
явный 2D TestPoint; всего 13 files. Новые L0805/TestPoint pad footprints из
официальной KiCad revision 51f8a59... неизменны; hashes/URL —
`components/curves-provenance.json`, license — `fixtures/LICENSE.md`.
Краткий результат: `output/symbol-curves.summary.json`; meshes/runtime bundle
исключены из Git. Перенос и второй build проверены, старый bundle byte-identical.

31 новый тест, всего **266**; copy без STL/STEP проходит с 3 optional model
integration skips. Проверены обе ориентации и >180° sweeps, literal endpoint
probes, dense reference → native segment distances и точные radial extrema
каждого serialized chord; большие translated origins, grid/budgets, native
pin Nodes, invalid/fill/style cases, legacy swap/rounding/resolution losses,
CLI/strict/reproducibility и component relocation. Unit tests моделей используют
opaque temporary bytes; реальные STL не интерпретируются.

2026-10-13: обычные electrical types добавлены с явной потерей ERC;
[SYMBOL_ELECTRICAL.md](SYMBOL_ELECTRICAL.md). Simple fills/body text также
добавлены с явными losses: [SYMBOL_BODY.md](SYMBOL_BODY.md). Disjoint multi-unit
layout готов; native hierarchy/independent units и GUI остаются открытыми.
