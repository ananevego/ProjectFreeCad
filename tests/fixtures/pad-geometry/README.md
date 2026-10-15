# Synthetic exact pad control

`PadGeometry_Control.kicad_mod` создан 2026-10-16 для проверки конвертера.
Это synthetic source, не файл официальной KiCad library. Pad1 — centred union
rectangular anchor и двух filled zero-width rectangles; pad2 — oval с равными
осями; pad3 — круглый drill с explicit zero offset. Все три native pin anchors
и source labels сохраняются.

Saved outputs: `output/PadGeometry_Control.fpl` и
`output/PadGeometry_Control.geometry-report.json`, settings mask=.05mm,
paste=0mm, ratio=0. Native GUI/Gerber/3D пока не проверены. Primary contract и
ограничения: `docs/PAD_GEOMETRY.md`, hashes/URLs —
`output/footprint-pad-geometry.source-evidence.json`.
Real negative controls остаются unchanged в `tests/fixtures/medium/` с pinned
provenance/license; их slots/offset/custom shapes не исправлялись вручную.
