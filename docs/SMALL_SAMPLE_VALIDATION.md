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
| SOT-23 | Заполненный silk polygon — маркер pin 1 | Явная ошибка; `.fpl` не создаётся и не заменяет предыдущий файл |

Ось Y инвертируется, `centroid` не записывается: его вычисляет target reader.
Поведение reader ещё требует ручного roundtrip. Dwgs.User и Cmts.User
преобразуются в top notes=7 с loss `USER_LAYER_APPROXIMATED`; `--strict` такую
потерю отвергает. Различие этих исходных слоёв не объявляется сохранённым.

У каждого сгенерированного реального образца остаются потери Fab/courtyard/text.
У MountingHole нет `(model ...)`: `MODEL_MISSING` ожидаем, угадывания по имени нет.
PinHeader использует существующий
`Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x03_P2.54mm_Vertical.stl`.
STL проверяется по пути и метаданным; геометрия, ориентация и высота не проверены.

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
```

Эти defaults — **выбранные параметры теста**, а не восстановленные параметры
исходной платы и не рекомендация для производства. Получается mask 1.8×1.8 мм
у PinHeader (rect расширяется со скруглением 0.05 мм) и mask diameter=3.3 мм
у MountingHole. Unit test отдельно проверяет NPTH без заданного margin:
там используется source size=3.2 мм с `NPTH_MASK_DEFAULT`.

Для воспроизведения PinHeader import нужен указанный существующий STL в
`stl_files/` либо альтернативный корень через `--stl-root`. Без модели выход
будет без `openscad_code`, с явным `MODEL_MISSING`. Полный unit-test набор
воспроизводим и без каталога моделей: реальные integration tests пропускаются,
а для структурных проверок matcher создаются временные metadata-only файлы.
JSON-отчёты содержат пути компьютера и не коммитятся.

## Следующий технический шаг

Исследовать native возможности заполненных полигонов FreePCB2 на примере
сохранённого SOT-23. Штриховка и сплошная заливка не считаются автоматически
эквивалентными. До подтверждения отображения или проверяемой аппроксимации
оставить явный отказ; существующие pads и STL не пересоздавать.
Windows roundtrip всех успешных примеров и проверка 3D остаются отдельным этапом.
