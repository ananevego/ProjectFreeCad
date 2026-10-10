"""Curve sampling and bounded fill approximation; no filesystem access."""
from __future__ import annotations

import math
from dataclasses import replace
from itertools import chain

from .errors import ConversionError
from .model import FilledCircle, FilledPolygon, Footprint, Polyline
from .format_rules import number


MAX_FILL_STROKES = 4096


MAX_FILL_VERTICES = 512


def sample_arc(center: tuple[float, float], radius: float, start_angle: float,
               sweep: float, tolerance: float) -> tuple[tuple[float, float], ...]:
    if not all(math.isfinite(v) for v in (*center, radius, start_angle, sweep)) or radius <= 0:
        raise ConversionError('Invalid circle/arc geometry')
    # Reserve 10 nm for coordinate quantization in the writer.
    budget = tolerance - 0.00001
    delta = min(math.pi / 4, 2 * math.acos(max(-1, 1 - budget / radius)))
    if delta <= 0:
        raise ConversionError('Arc exceeds the supported tessellation resolution')
    count = max(1, math.ceil(abs(sweep) / delta))
    if count > 4096:
        raise ConversionError('Arc requires more than 4096 segments; increase curve tolerance')
    return tuple((center[0] + radius * math.cos(start_angle + sweep * i / count),
                  center[1] + radius * math.sin(start_angle + sweep * i / count))
                 for i in range(count + 1))


def arc_points(start: tuple, mid: tuple, end: tuple, tolerance: float) -> tuple:
    if not all(math.isfinite(v) for p in (start, mid, end) for v in p):
        raise ConversionError('Invalid arc coordinates')
    # Solve in the local frame for numerical stability far from the origin.
    bx, by = mid[0] - start[0], mid[1] - start[1]
    cx, cy = end[0] - start[0], end[1] - start[1]
    determinant = 2 * (bx * cy - by * cx)
    if abs(determinant) <= 1e-12 * max(bx*bx + by*by, cx*cx + cy*cy, 1e-12):
        raise ConversionError('Arc start/mid/end are coincident or collinear')
    b2, c2 = bx*bx + by*by, cx*cx + cy*cy
    ux = (cy*b2 - by*c2) / determinant
    uy = (bx*c2 - cx*b2) / determinant
    center = (start[0] + ux, start[1] + uy)
    radius = math.hypot(ux, uy)
    angles = [math.atan2(p[1]-center[1], p[0]-center[0]) for p in (start, mid, end)]
    sweep = (angles[2] - angles[0]) % math.tau
    if (angles[1] - angles[0]) % math.tau > sweep:
        sweep -= math.tau
    points = list(sample_arc(center, radius, angles[0], sweep, tolerance))
    points[0], points[-1] = start, end  # Preserve endpoints exactly.
    return tuple(points)


def filled_polygon_points(polygon: FilledPolygon) -> tuple[tuple[int, int], ...]:
    if not math.isfinite(polygon.width) or polygon.width < 0:
        raise ConversionError('Invalid filled polygon stroke width')
    number(polygon.width)
    if not 3 <= len(polygon.points) <= MAX_FILL_VERTICES:
        raise ConversionError(f'Filled polygon requires 3..{MAX_FILL_VERTICES} vertices')
    points = tuple((int(number(x)), int(number(y))) for x, y in polygon.points)
    if len(set(points)) != len(points):
        raise ConversionError('Filled polygon has repeated/collapsed vertices on target grid')

    def cross(a, b, c):
        return (b[0]-a[0]) * (c[1]-a[1]) - (b[1]-a[1]) * (c[0]-a[0])

    def on_segment(a, b, p):
        return (cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))

    edges = list(zip(points, points[1:] + points[:1]))
    for index, (a, b) in enumerate(edges):
        c = points[(index + 2) % len(points)]
        if cross(a, b, c) == 0 and (b[0]-a[0])*(c[0]-b[0]) + (b[1]-a[1])*(c[1]-b[1]) < 0:
            raise ConversionError('Filled polygon has overlapping adjacent edges')
        for other in range(index + 2, len(edges)):
            if index == 0 and other == len(edges) - 1:
                continue
            c, d = edges[other]
            ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
            if ((ab_c * ab_d < 0 and cd_a * cd_b < 0) or on_segment(a, b, c)
                    or on_segment(a, b, d) or on_segment(c, d, a) or on_segment(c, d, b)):
                raise ConversionError('Filled polygon has self-intersecting/touching edges')
    # Translate before the shoelace calculation (also exact for integer NM).
    ox, oy = points[0]
    area = sum((a[0]-ox)*(b[1]-oy) - (b[0]-ox)*(a[1]-oy) for a, b in edges)
    if area == 0:
        raise ConversionError('Filled polygon has zero area on target grid')
    return points


def validate_filled_circle(circle: FilledCircle) -> float:
    """Validate source geometry and return its radius, without sampling."""
    if len(circle.center) != 2 or len(circle.end) != 2:
        raise ConversionError('Filled circle requires 2D center/end coordinates')
    if not all(math.isfinite(v) for v in (*circle.center, *circle.end, circle.width)) or circle.width < 0:
        raise ConversionError('Invalid filled circle geometry/stroke width')
    radius = math.dist(circle.center, circle.end)
    if not math.isfinite(radius) or radius <= 0:
        raise ConversionError('Filled circle requires a positive finite radius')
    number(circle.width)
    if int(number(radius)) <= 0:
        raise ConversionError('Filled circle radius below target resolution')
    for value in (*circle.end, *(v + sign * (radius + circle.width / 2)
                                 for v in circle.center for sign in (-1, 1))):
        number(value)
    return radius


def _circle_polygon(circle: FilledCircle, minimum_width_nm: int,
                    curve_tolerance: float, warnings: list[str]) -> FilledPolygon:
    radius = validate_filled_circle(circle)
    width = max(int(number(circle.width)), minimum_width_nm) / 1e6
    # The inscribed polygon alone misses the circular caps. Bound its sagitta
    # by one quarter of the emitted stroke width, reserving quantization in
    # sample_arc. Half-width boundary strokes then cover the whole nominal disk,
    # not just the polygon. Original nonzero stroke can recede by at most the
    # chord tolerance; outward expansion remains bounded by fill tolerance.
    chord_tolerance = min(curve_tolerance, width / 4)
    if chord_tolerance <= 0.00001:
        raise ConversionError('Filled circle tolerance below supported resolution; increase fill tolerance')
    angle = math.atan2(circle.end[1] - circle.center[1], circle.end[0] - circle.center[0])
    points = sample_arc(circle.center, radius, angle, math.tau, chord_tolerance)[:-1]
    if len(points) > MAX_FILL_VERTICES:
        raise ConversionError(f'Filled circle requires more than {MAX_FILL_VERTICES} vertices; increase curve/fill tolerance')
    warnings.append(f'CURVE_APPROXIMATED: filled fp_circle on {circle.layer}, chord error <= {chord_tolerance:g} mm; nominal disk covered by boundary strokes')
    return FilledPolygon(points, circle.width, circle.layer)


def tessellate_fills(fp: Footprint, tolerance: float, warnings: list[str], *,
                     curve_tolerance: float = 0.01) -> Footprint:
    """Cover simple filled polygons by boundary + overlapping horizontal strokes.

    In the ideal round-ended stroke model, every source interior point is
    covered: a point close to the boundary belongs to its thick stroke; any
    other point projects to an interior scanline within half the row pitch.
    All centre-lines lie inside/on the polygon. Increasing zero/thin source
    width introduces at most tolerance expansion (including grid rounding).
    Circles keep their source geometry until the stroke width is known; an
    adaptive boundary also covers the caps outside the inscribed polygon.
    This bounds the encoded geometry, not GUI rasterization or Gerber settings.
    """
    if not math.isfinite(tolerance) or tolerance <= 0.00002:
        raise ConversionError('Fill tolerance must be greater than 0.00002 mm')
    if tolerance > 1073:
        raise ConversionError('Fill tolerance exceeds the target dimension range')
    if not math.isfinite(curve_tolerance) or curve_tolerance <= 0.00001:
        raise ConversionError('Curve tolerance must be greater than 0.00001 mm')
    polylines = list(fp.polylines)
    written = 0
    # Reserve 20 nm for target coordinate/width quantization. Use integer grid
    # units to keep stroke width and pitch stable even for very thin polygons.
    minimum_width_nm = math.floor(2 * (tolerance - 0.00002) * 100_000) * 10
    if minimum_width_nm < 20:
        raise ConversionError('Fill tolerance is below the supported target resolution')
    # Sample circles lazily so the common stroke budget stops work before
    # tessellating the rest of a footprint with excessive filled graphics.
    figures = chain(
        ((f'polygon {index}', polygon) for index, polygon in enumerate(fp.filled_polygons, 1)),
        ((f'circle {index}', _circle_polygon(circle, minimum_width_nm, curve_tolerance, warnings))
         for index, circle in enumerate(fp.filled_circles, 1)),
    )
    for label, polygon in figures:
        vertices_nm = filled_polygon_points(polygon)
        points = tuple((x / 1e6, y / 1e6) for x, y in vertices_nm)
        width_nm = max(int(number(polygon.width)), minimum_width_nm)
        number(width_nm / 1e6)  # Expanded dimensions must fit the target range.
        width = width_nm / 1e6
        low, high = min(y for _, y in vertices_nm), max(y for _, y in vertices_nm)
        rows = math.ceil(2 * (high - low) / width_nm)
        if written + rows + 1 > MAX_FILL_STROKES:
            raise ConversionError(f'Filled graphics require more than {MAX_FILL_STROKES} strokes; increase fill tolerance')
        polylines.append(Polyline(points, width, polygon.layer, True, 'fill_boundary'))
        written += 1
        step = (high - low) / rows
        # Centre rows, half-open intersections: a vertex is counted only once.
        # All interpolation is local to the polygon, in target-grid units.
        edges = list(zip(vertices_nm, vertices_nm[1:] + vertices_nm[:1]))
        spans = 0
        for row in range(rows):
            y = low + (row + 0.5) * step
            xs = []
            for (ax, ay), (bx, by) in edges:
                if min(ay, by) <= y < max(ay, by):
                    xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
            xs.sort()
            if len(xs) % 2:
                raise ConversionError('Filled polygon has odd scanline intersections')
            for left, right in zip(xs[::2], xs[1::2]):
                if left == right:
                    continue
                if written >= MAX_FILL_STROKES:
                    raise ConversionError(f'Filled graphics require more than {MAX_FILL_STROKES} strokes; increase fill tolerance')
                # Even a collapsed span is retained as a zero-length stroke;
                # the boundary stroke covers such narrow/tip regions as well.
                polylines.append(Polyline(((left / 1e6, y / 1e6), (right / 1e6, y / 1e6)),
                                          width, polygon.layer, False, 'fill_scanline'))
                spans += 1
                written += 1
        warnings.append(f'FILL_APPROXIMATED: {label} on {polygon.layer}; boundary + {spans} overlapping strokes, encoded expansion <= {tolerance:g} mm')
    if fp.filled_polygons or fp.filled_circles:
        warnings.append('FILL_STROKE_MODEL: fill bound assumes ideal round-ended target strokes; GUI rasterization not validated')
        warnings.append('FILL_EXPORT_UNVERIFIED: FreePCB Gerber minimum stroke settings can widen lines or suppress very thin lines; manufacturing validation pending')
    return replace(fp, polylines=polylines, filled_polygons=[], filled_circles=[])
