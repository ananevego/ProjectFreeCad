# Synthetic stroke control

`StrokePatterns_Control.kicad_mod` создан для numerical regression конвертера
2026-10-15. Это синтетический source, не выгрузка официальной KiCad library.
Четыре unfilled styles (dash, dot, dash_dot, dash_dot_dot), reverse line,
rectangle и closed polygon проверяют KiCad9 PCB editor default profile.

Настройки apertures для saved output: mask=.05mm, paste=0mm, ratio=0.
Выход: `output/StrokePatterns_Control.fpl` и отдельный stroke-report JSON.
Native GUI/Gerber/caps не проверены. Primary formulas/source hashes:
`output/footprint-strokes.source-evidence.json`, contract:
`docs/FOOTPRINT_STROKES.md`. Реальные default controls хранятся неизменёнными
в `tests/fixtures/medium/` с pinned provenance/license.
