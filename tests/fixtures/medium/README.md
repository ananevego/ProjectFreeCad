# Средняя контрольная партия KiCad footprints

120 whole unchanged files от KiCad community, revision
`51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c`, получены 2026-10-14.
12 выбранных категорий, по 10 путей с evenly spaced indices в sorted list:
`round(i*(N-1)/9)` для i=0..9, Python ties-to-even. Категории/размеры исходных
списков и выбранные files закреплены в `provenance.json`.

Это deterministic stratified engineering sample, не случайная выборка и
не оценка success rate всей библиотеки. Tree metadata без truncation содержит
15464 .kicad_mod на данной revision; локально скачаны только эти 120 (908267 bytes).
Каждый файл проверен по API Git blob SHA-1, размеру и SHA256. Official license
`LICENSE.md` также соответствует pinned Git blob: CC-BY-SA 4.0 с исключением
KiCad Libraries. Атрибуция: KiCad community / KiCad Libraries.

Source pads/texts/models/graphics не редактировались для обхода отказов.
STL/STEP здесь отсутствуют. Unit tests используют missing/metadata-only model
roots; runtime batch обращается только к метаданным соответствующих existing
STL, без mesh parsing/копирования/конвертации.

[Результаты и команды](../../../docs/FOOTPRINT_MEDIUM.md).
