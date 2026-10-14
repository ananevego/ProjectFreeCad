"""Bounded KiCad 9 PCB editor default patterns as independent FPL segments.

KiCad restarts STROKE_PARAMS::Stroke for each straight edge. The PCB defaults
are dash/gap ratios 12/3 with round-cap correction 1: centreline lengths are
11w / .2w / 4w. Library files do not contain renderer/project configuration.
This fixed profile is therefore reported as a loss, including native caps.
Only positive-length marks are encoded. KiCad's inclusive ClipLine can also
produce an isolated point at an exact endpoint; that cap is omitted with loss.
"""
from __future__ import annotations

from dataclasses import replace
import math

from .errors import ConversionError
from .format_rules import number
from .geometry import filled_polygon_points
from .model import FilledPolygon, Footprint, PatternedGraphic, Polyline


PROFILE = 'kicad9-pcb-editor-default-strokes-v1'
MAX_PATTERN_SEGMENTS = 4096  # Total for the footprint, never silently truncated.
PATTERNS = {
    'dash': (11.0, 4.0),
    'dot': (0.2, 4.0),
    'dash_dot': (11.0, 4.0, 0.2, 4.0),
    'dash_dot_dot': (11.0, 4.0, 0.2, 4.0, 0.2, 4.0),
}


def expand_graphic(graphic: PatternedGraphic, remaining: int) -> list[Polyline]:
    poly = graphic.outline
    if graphic.kind not in {'fp_line', 'fp_rect', 'fp_poly'} or graphic.style not in PATTERNS:
        raise ConversionError('Non-solid graphic stroke: unsupported patterned geometry/style')
    if not math.isfinite(poly.width) or poly.width <= 0 or int(number(poly.width * .2)) <= 0:
        raise ConversionError('Non-solid graphic stroke: invalid width or dot below target resolution')
    number(poly.width)
    if len(poly.points) < 2 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in poly.points):
        raise ConversionError('Non-solid graphic stroke: invalid coordinates')
    if graphic.kind == 'fp_line':
        if len(poly.points) != 2 or poly.closed:
            raise ConversionError('Non-solid graphic stroke: line requires two endpoints')
        for p in poly.points:
            for value in p:
                number(value)
    else:
        if graphic.kind == 'fp_rect' and len(poly.points) != 4:
            raise ConversionError('Non-solid graphic stroke: rectangle requires four corners')
        if not poly.closed:
            raise ConversionError('Non-solid graphic stroke: polygon must be closed')
        # Restrict new polygon patterns to simple, nondegenerate <=512 corners.
        filled_polygon_points(FilledPolygon(poly.points, poly.width, poly.layer))
    edges = zip(poly.points, poly.points[1:] + (poly.points[:1] if poly.closed else ()))
    pattern = tuple(multiplier * poly.width for multiplier in PATTERNS[graphic.style])
    period = sum(pattern)
    prefix = []
    offset = 0.0
    for i, length in enumerate(pattern):
        if i % 2 == 0:
            prefix.append((offset, length))
        offset += length
    result = []
    for a, b in edges:
        distance = math.dist(a, b)
        if distance <= 0 or tuple(map(number, a)) == tuple(map(number, b)):
            raise ConversionError('Non-solid graphic stroke: edge collapses on target grid')
        cycles = math.ceil(distance / period)
        if cycles > remaining - len(result):
            raise ConversionError(f'Non-solid graphic stroke requires more than {MAX_PATTERN_SEGMENTS} segments')
        dx, dy = (b[0] - a[0]) / distance, (b[1] - a[1]) / distance
        for cycle in range(cycles):
            for start, length in prefix:
                begin = cycle * period + start
                if begin >= distance:
                    continue
                if len(result) >= remaining:
                    raise ConversionError(f'Non-solid graphic stroke requires more than {MAX_PATTERN_SEGMENTS} segments')
                finish = min(begin + length, distance)
                p = (a[0] + dx * begin, a[1] + dy * begin) if begin else a
                q = (a[0] + dx * finish, a[1] + dy * finish) if finish < distance else b
                if tuple(map(number, p)) == tuple(map(number, q)):
                    raise ConversionError('Non-solid graphic stroke: clipped mark collapses on target grid')
                result.append(Polyline((p, q), poly.width, poly.layer, role='pattern_segment'))
    return result


def expand_strokes(fp: Footprint, warnings: list[str]) -> Footprint:
    marks = []
    for graphic in fp.patterned_graphics:
        marks.extend(expand_graphic(graphic, MAX_PATTERN_SEGMENTS - len(marks)))
    if marks:
        warnings.append('GRAPHIC_STROKE_FLATTENED: dash/dot style baked into straight records using ' + PROFILE + '; editable style and renderer/project settings lost; zero-length endpoint marks omitted; native caps/joins unvalidated')
    return replace(fp, polylines=list(fp.polylines) + marks)


def stroke_report(fp: Footprint, render_fp: Footprint) -> dict:
    return dict(profile=PROFILE, source_graphics=[
        dict(kind=g.kind, style=g.style, points_mm=g.outline.points,
             width_mm=g.outline.width, layer=g.outline.layer, closed=g.outline.closed)
        for g in fp.patterned_graphics],
        centerline_multipliers=dict(dash=11, dot=.2, gap=4),
        source_renderer_ratios=dict(dash=12, gap=3, round_cap_correction=1),
        phase='restart_at_each_source_edge', clipping='at_source_endpoint',
        zero_length_endpoint_marks='omitted_with_loss',
        coordinate_grid_nm=10, segment_limit_per_footprint=MAX_PATTERN_SEGMENTS,
        written_segments=sum(p.role == 'pattern_segment' for p in render_fp.polylines),
        source_project_settings_available=False, native_style_transferred=False,
        native_caps_joins_validated=False, gui_validated=False, manufacturing_validated=False)
