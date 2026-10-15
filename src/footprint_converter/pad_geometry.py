"""Exact reductions into the centred FreePCB2 padstack contract, never a bbox fit.

Native 2.428 has one circular hole diameter and centred pads; its two historic
X extents are summed on import. Slots, nonzero shape offsets and nonrectangular
custom unions therefore stay refusals. A bounded, centred rectangular union
of a rectangular anchor and filled zero-width rectangles can use one native
rectangle. Proof uses exact rational vertical slabs before 10-nm encoding.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import math

from .errors import ConversionError, PadGeometryError
from .format_rules import copper_sides, number
from .model import ApertureSettings, Footprint, Pad
from .writer import inherit_apertures

PROFILE = 'freepcb2428-exact-pad-reductions-v1'
MAX_CUSTOM_PRIMITIVES = 32


def nodes(node, key):
    return [v for v in node if isinstance(v, list) and v and v[0] == key]


def one(node, key, count=None, required=False):
    items = nodes(node, key)
    if len(items) > 1 or required and not items:
        raise ConversionError('Missing/duplicate pad geometry ' + key)
    result = items[0] if items else None
    if result is not None and count is not None and (
            len(result) != count or any(not isinstance(v, str) for v in result)):
        raise ConversionError('Malformed pad geometry ' + key)
    return result


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ConversionError('Non-finite pad geometry dimension')
    return value


def read_drill(source: list) -> tuple[float, dict | None]:
    drill = one(source, 'drill')
    if drill is None:
        return 0., None
    offset = one(drill, 'offset', 3)
    atoms = [v for v in drill[1:] if isinstance(v, str)]
    if any(not isinstance(v, (str, list)) or isinstance(v, list) and (not v or v[0] != 'offset') for v in drill[1:]):
        raise ConversionError('Malformed pad drill field')
    oval = bool(atoms and atoms[0] == 'oval')
    sizes = atoms[1:] if oval else atoms
    if len(sizes) not in ({1, 2} if oval else {1}):
        raise ConversionError('Malformed pad drill dimensions')
    dimensions = [finite(v) for v in sizes]
    if min(dimensions) < 0:
        raise ConversionError('Negative pad drill dimension')
    dimensions = (dimensions + dimensions[:1])[:2]
    shift = tuple(finite(v) for v in offset[1:]) if offset else (0., 0.)
    if oval and dimensions[0] != dimensions[1]:
        raise PadGeometryError('DRILL_SLOT_UNSUPPORTED',
            f'Pad {source[1]}: oval/offset drill: slot drill is not representable by one native hole_size',
            source, drill_size_mm=dimensions, shape_offset_mm=shift,
            native_limitation='one_circular_hole_diameter')
    if shift != (0., 0.):
        raise PadGeometryError('PAD_OFFSET_UNSUPPORTED',
            f'Pad {source[1]}: oval/offset drill: nonzero shape offset cannot be stored in centred native padstacks',
            source, drill_size_mm=dimensions, shape_offset_mm=shift,
            native_limitation='reader_sums_historic_x_extents_into_centred_width')
    equivalent = dict(source_drill=deepcopy(drill), circular_diameter_mm=dimensions[0],
        shape_offset_mm=shift, equivalence='equal_axes_and_zero_offset') if oval or offset else None
    return dimensions[0], equivalent


def fraction(value):
    # Canonical finite float text bounds the rational's exponent/size. No
    # tolerance is used to hide small notches before the native quantization.
    value = finite(value)
    number(value)
    result = Fraction(str(value))
    if (result * 1_000_000).denominator != 1:
        raise ConversionError('Custom pad geometry requires exact source 1 nm grid coordinates')
    return result


def custom_rectangle(pad: Pad, source: list) -> tuple[Pad, dict]:
    def reject(code, message, **details):
        raise PadGeometryError(code, f'Pad {pad.name}: {message}', source, **details)
    if pad.kind != 'smd' or pad.drill:
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires a hole-free SMD in the rectangular reduction profile')
    at, size, layers = one(source, 'at', required=True), one(source, 'size', 3, True), one(source, 'layers', required=True)
    if len(at) not in {3, 4} or len(layers) < 2 or any(not isinstance(v, str) for v in at + layers):
        raise ConversionError('Malformed custom pad placement/layers')
    copper_sides(pad)
    if not any(v.endswith('.Cu') for v in pad.layers):
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires one outer copper side')
    options = one(source, 'options')
    if options is None:
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires explicit rectangular anchor/outline options')
    anchor, clearance = one(options, 'anchor', 2), one(options, 'clearance', 2)
    if anchor != ['anchor', 'rect'] or clearance != ['clearance', 'outline'] or len(options) != 3:
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires exactly anchor rect and clearance outline')
    if not all(math.isfinite(v) and v > 0 for v in (pad.width, pad.height)):
        raise ConversionError('Invalid custom anchor dimensions')
    w, h = fraction(pad.width), fraction(pad.height)
    if any((v * 1_000_000).numerator % 2 for v in (w, h)):
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires even-nm anchor dimensions; integer half-size rounding is outside the exact profile')
    rectangles = [(-w/2, -h/2, w/2, h/2)]
    primitives = one(source, 'primitives', required=True)
    if len(primitives) - 1 > MAX_CUSTOM_PRIMITIVES:
        reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', f'custom pad shape exceeds {MAX_CUSTOM_PRIMITIVES} primitives')
    for primitive in primitives[1:]:
        if not isinstance(primitive, list) or not primitive or primitive[0] != 'gr_poly':
            reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape supports only rectangular gr_poly primitives')
        pts, width, fill = one(primitive, 'pts', required=True), one(primitive, 'width', 2, True), one(primitive, 'fill', 2, True)
        if len(primitive) != 4 or finite(width[1]) != 0 or fill[1] not in {'yes', 'solid'}:
            reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape requires filled zero-width polygons without extra fields')
        if len(pts) not in {5, 6}:
            reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape primitive requires four rectangle corners')
        points = []
        for point in pts[1:]:
            if not isinstance(point, list) or len(point) != 3 or point[0] != 'xy' or not all(isinstance(v, str) for v in point):
                raise ConversionError('Malformed custom pad polygon coordinate')
            points.append((fraction(point[1]), fraction(point[2])))
        if points and points[0] == points[-1]:
            points.pop()
        xs, ys = {p[0] for p in points}, {p[1] for p in points}
        if (len(points) != 4 or len(set(points)) != 4 or len(xs) != 2 or len(ys) != 2
                or any(a[0] != b[0] and a[1] != b[1] for a, b in zip(points, points[1:] + points[:1]))):
            reject('CUSTOM_PAD_PROFILE_UNSUPPORTED', 'custom pad shape primitive is not an axis-aligned rectangle')
        rectangles.append((min(xs), min(ys), max(xs), max(ys)))
    xmin, ymin = min(r[0] for r in rectangles), min(r[1] for r in rectangles)
    xmax, ymax = max(r[2] for r in rectangles), max(r[3] for r in rectangles)
    cuts = sorted({v for r in rectangles for v in (r[0], r[2])})
    area = Fraction(0)
    for left, right in zip(cuts, cuts[1:]):
        intervals = sorted((r[1], r[3]) for r in rectangles if r[0] <= left and r[2] >= right)
        covered, end = Fraction(0), ymin
        for lo, hi in intervals:
            if hi > end:
                covered += hi - max(lo, end)
                end = hi
        area += (right - left) * covered
    bounding_area = (xmax - xmin) * (ymax - ymin)
    proof = dict(algorithm='exact_rational_vertical_slabs', rectangles=len(rectangles),
        vertical_slabs=len(cuts)-1, union_area_mm2=float(area), bounding_area_mm2=float(bounding_area),
        uncovered_area_mm2=float(bounding_area-area), bounds_mm=list(map(float, (xmin, ymin, xmax, ymax))))
    if area != bounding_area:
        reject('CUSTOM_PAD_NONRECTANGULAR', 'custom pad shape union is nonrectangular; bounding-box replacement refused', proof=proof)
    if xmin + xmax != 0 or ymin + ymax != 0:
        reject('CUSTOM_PAD_OFFSET_UNSUPPORTED', 'custom pad shape union centre differs from its source electrical anchor', proof=proof)
    # Native reader adds the two legacy extents into a signed 32-bit size_X.
    # Valid endpoint coordinates alone do not guarantee a valid total width.
    number(float(xmax-xmin))
    number(float(ymax-ymin))
    proof['union_equals_centred_rectangle'] = True
    return replace(pad, shape='rect', width=float(xmax-xmin), height=float(ymax-ymin), radius=0), proof


def normalize_pad_geometry(fp: Footprint, defaults: ApertureSettings | None, warnings: list[str]) -> Footprint:
    pads, results = list(fp.pads), []
    for index, source in fp.pad_geometry_sources.items():
        pad = pads[index]
        _, drill = read_drill(source)
        result = dict(source_pad_index=index, source=asdict(pad), source_raw=deepcopy(source))
        if drill:
            result['drill_equivalence'] = drill
            warnings.append('DRILL_EQUIVALENT_NORMALIZED: equal oval axes and/or explicit zero offset use the same circular native hole')
        if pad.shape == 'custom':
            normalized, proof = custom_rectangle(pad, source)
            settings = inherit_apertures(pad.apertures, fp.apertures, defaults or ApertureSettings())
            mask = any(v in {'F.Mask', 'B.Mask', '*.Mask'} for v in pad.layers)
            paste = any(v in {'F.Paste', 'B.Paste', '*.Paste'} for v in pad.layers)
            if (mask and (settings.mask_margin is None or settings.mask_margin < 0)
                    or paste and (settings.paste_ratio != 0 or settings.paste_margin is None or settings.paste_margin < 0)):
                raise PadGeometryError('CUSTOM_PAD_APERTURE_UNSUPPORTED',
                    f'Pad {pad.name}: custom pad shape needs explicit nonnegative aperture margins and zero paste ratio; anchor-based clamping/ratios are not reinterpreted', source)
            pads[index] = normalized
            result['rectangle_proof'] = proof
            warnings.append('CUSTOM_PAD_RECT_FLATTENED: exact centred rectangular union uses one native padstack; custom primitive editing and zone/thermal settings are not transferred')
        result['native'] = asdict(pads[index])
        results.append(result)
    return replace(fp, pads=pads, pad_geometry_results=results)


def geometry_report(fp: Footprint) -> dict:
    return dict(profile=PROFILE, normalized_pads=fp.pad_geometry_results,
        max_custom_primitives=MAX_CUSTOM_PRIMITIVES, source_proof_grid_nm=1, coordinate_grid_nm=10,
        native_gui_validated=False, native_netlist_verified=False, manufacturing_validated=False)
