# KiCad → FreePCB2 2.428

Конвертер библиотечных footprint-файлов KiCad `.kicad_mod` в самостоятельные
библиотеки FreePCB2 `.fpl`. Написан на Python 3.10+, внешние зависимости не нужны.

**Статус:** разработка продолжается. R_0805_2012Metric, PinHeader PTH,
MountingHole NPTH и численные
регрессии проверены автоматически. Загрузка/сохранение в FreePCB2 2.428 и
физическое совмещение STL в OpenSCAD ещё требуют отдельной Windows-валидации.
Конвертер УГО и полноценная цепочка symbol → footprint → 3D пока не реализованы.

## Что поддерживается

| Данные KiCad | Результат |
|---|---|
| SMD circle / rect / oval / roundrect | Соответствующая форма и размеры, без перестановки X/Y |
| F.Cu / B.Cu | Верхняя / нижняя площадка |
| PTH с круглым drill | Отверстие и площадки; `*.Cu` включает общий inner_pad |
| NPTH с круглым drill | Отверстие без меди; NPTH paste подавляется с диагностикой |
| Origin | Сохраняется; ось Y приводится к системе FreePCB2 |
| Centroid | Вычисляет native reader FreePCB2 по bounds площадок |
| F.SilkS / B.SilkS | Раздельные слои 4 / 5 |
| Dwgs.User / Cmts.User | Контуры и user texts в notes=7 с диагностикой потери различия слоёв |
| Линии, незаполненные прямоугольники и полигоны | Контуры `.fpl` |
| Окружности, дуги start/mid/end | Отрезки с задаваемой точностью, по умолчанию 0.01 мм |
| Reference / value / user texts | Параметры и тексты с явной диагностикой ограничений |
| Mask/paste margins | Pad → footprint → явные defaults; размер и скругление aperture |
| Ссылка KiCad `.3dshapes` | Поиск уже существующего STL, код OpenSCAD; без конвертации моделей |

Fab переносится в слой notes как приближение, courtyard пропускается.
Custom/chamfer/trapezoid pads, oval/offset drills, отдельные InN.Cu,
дробные углы, заполненные фигуры, legacy centre/angle arcs и асимметричный
paste roundrect пока не поддерживаются. Непредставимая геометрия вызывает ошибку.
Полный контракт: [docs/FOOTPRINT_CONVERTER.md](docs/FOOTPRINT_CONVERTER.md).

## Быстрый запуск

Из корня репозитория:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B src/kicad_to_freepcb_footprint.py \
  tests/fixtures/R_0805_2012Metric.kicad_mod \
  output/R_0805_2012Metric.fpl \
  --report output/R_0805_2012Metric.report.json
```

На Windows используйте `py -3` вместо `python3`; команду можно записать в одну
строку. Вход — UTF-8; `.fpl` по умолчанию — CP1251, отчёт — UTF-8 JSON.

Основные тесты запускаются и в новом клоне без 3D-каталогов: они используют
временный файл только для проверки метаданных matcher, а не геометрию STL.
Отдельный интеграционный тест использует реальный R0805 STL, когда он доступен;
аналогичная проверка есть для PinHeader. При отсутствии моделей эти проверки
явно пропускаются. Численные unit tests продолжают работать.

В `output/` также сохранены PTH/NPTH примеры. Их параметры и воспроизводимые
команды: [малая контрольная выборка](docs/SMALL_SAMPLE_VALIDATION.md).
Актуальный SOT-23 из fixtures пока **отвергается** из-за заполненного silk polygon;
он используется для проверки ошибки и сохранения прежнего выходного файла.

Для реальной 3D-привязки положите **существующий** файл по пути:

```text
stl_files/Resistor_SMD.3dshapes/R_0805_2012Metric.stl
```

Либо укажите корень имеющегося набора через `--stl-root /path/to/stl_files`.
Без файла конвертер сгенерирует `.fpl` с `MODEL_MISSING` в отчёте, без `import`.
Он не создаёт модели и не ищет совпадение только по basename.

## Отчёт и строгий режим

`--report` сохраняет целевую ревизию, counts, исходные тексты, настройки apertures,
3D-связи и diagnostics. `loss` означает потерю информации, `assumption` —
непроверенное допущение, `approximation` — ограниченную аппроксимацию.

| Код завершения | Значение |
|---|---|
| 0 | Файл сгенерирован; возможные потери перечислены в отчёте |
| 1 | Ошибка чтения, преобразования или записи |
| 2 | `--strict` запретил результат из-за известных потерь; старый `.fpl` сохранён |

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --strict --report output/part.report.json
```

`--strict` допускает указанные в отчёте допущения и ограниченную аппроксимацию;
это не подтверждение корректности в GUI. Для текущего R0805 строгий запуск
завершится кодом 2 из-за courtyard/Fab/text. Сохранённый контрольный `.fpl`
предназначен для дальнейшей валидации, а не объявляется готовой библиотекой.

## Настройки mask/paste

Margins задаются **на сторону**, в мм; ratio — доля, например `-0.05`.
Размер paste: `X + 2*(margin + X*ratio)` и аналогично для Y.

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --default-mask-margin 0.05 \
  --default-paste-margin 0 --default-paste-ratio 0 \
  --report output/part.report.json
```

Параметры defaults должны соответствовать выбранным настройкам исходного проекта.
Pad overrides footprint; footprint overrides CLI defaults; явный ноль сохраняется.
Если обе настройки paste отсутствуют, используется FreePCB DEFAULT=99 с
диагностикой зависимости от target project. Если известна лишь одна — другая
считается нулём с диагностикой потери, запрещённой в `--strict`.
Положительный margin rect создаёт roundrect; равномерный margin roundrect
меняет радиус. Схлопнувшаяся aperture записывается как NONE.

## Тексты и 3D

Нативный `.fpl` хранит параметры reference/value, но не их actual content и
независимый слой. Значение компонента необходимо задать при размещении.
Неразрешённые `${REFERENCE}` и другие user text variables пропускаются с
диагностикой; исходные строки сохраняются в JSON.

```sh
python3 -B src/kicad_to_freepcb_footprint.py input.kicad_mod output/part.fpl \
  --text-variable REFERENCE=R1 --text-variable VALUE=10k
```

Такая подстановка создаёт **статический** текст. Она не создаёт динамическое поле
FreePCB2. Точное совпадение шрифта и baseline пока не обеспечено.

STL frame по умолчанию identity с `MODEL_FRAME_UNVERIFIED`. Его можно явно задать
через `--model-translation X Y Z`, `--model-rotation X Y Z`, `--model-scale X Y Z`.
Это полное target-преобразование, заменяющее исходный model transform;
неединичные KiCad 3D transforms без явной настройки отвергаются.

Для будущей проверки R0805 в FreePCB2 2.428 выставить единицы проекта **MM** и
«Папка для Openscad» на Windows-копию `stl_files\Resistor_SMD.3dshapes`.
Загружать footprint целиком через библиотеку при добавлении детали; затем
редактировать footprint выбранной детали и сохранять `.fpl`/`.fpc`.
Меню «Импорт футпринта» добавляет геометрию группой и не проверяет полный roundtrip.

## Структура

- `src/kicad_to_freepcb_footprint.py` — parser, внутренняя модель, writer,
  matcher, validation/reporting и CLI.
- `tests/` — численные и структурные регрессии; `tests/fixtures/` — контрольный
  KiCad footprint с происхождением и лицензией KiCad Libraries.
- `output/` — контрольный `.fpl`; JSON-отчёты генерируются локально и не коммитятся,
  поскольку содержат пути конкретного компьютера.
- `FreePCB/`, `Эталон R_0805_2012Metric/` — прежние демонстрационные проекты.
- `stl_files/`, `step_files/` — ранее полученные модели, доступны отдельно
  (в том числе на Яндекс Диске), исключены из Git. Не пересоздавать их.
- STEP → STL скрипты в корне — история предыдущей конвертации;
  запускать их для использования footprint-конвертера не требуется.

[План дальнейшей работы](docs/PROJECT_PLAN.md): расширение небольшой реальной
выборки, уточнение оставшихся правил, УГО по подтверждённому эталону, затем batch.
Массовая конвертация 20 000 элементов на текущем этапе не выполняется.
