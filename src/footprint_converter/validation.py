"""Validate whether the internal model fits the supported target subset."""
from __future__ import annotations

import math

from .errors import ConversionError
from .model import Footprint
from .format_rules import copper_sides, integer_angle, number, pad_shape, quote, is_technical_pad
from .geometry import filled_polygon_points, validate_filled_circle


def validate_footprint(fp: Footprint) -> list[str]:
    warnings = list(fp.warnings)
    quote(fp.name)
    if not fp.name.strip() or len(fp.name) > 99:
        raise ConversionError('Footprint name must contain 1..99 characters')
    if not fp.pads:
        if not (fp.polylines or fp.filled_polygons or fp.filled_circles or fp.patterned_graphics):
            raise ConversionError('Footprint requires at least one pad/hole or supported graphic outline')
        warnings.append('PADLESS_GRAPHIC: graphical footprint has zero native pins; no electrical terminals are created')
    for pad in fp.pads:
        if pad.kind not in {'smd', 'connect', 'thru_hole', 'np_thru_hole'}:
            raise ConversionError(f'Pad {pad.name}: unsupported type {pad.kind}')
        quote(pad.name)
        if len(pad.name) > 39 or not pad.name and pad.kind != 'np_thru_hole' and not is_technical_pad(pad):
            raise ConversionError(f'Pad {pad.name!r}: invalid pin name')
        pad_shape(pad.shape)
        integer_angle(pad.rotation)
        values = (pad.x, pad.y, pad.width, pad.height, pad.drill, pad.radius)
        if not all(math.isfinite(v) for v in values) or min(pad.width, pad.height) <= 0:
            raise ConversionError(f'Pad {pad.name}: invalid dimensions/coordinates')
        if pad.shape == 'circle' and not math.isclose(pad.width, pad.height, abs_tol=1e-8):
            raise ConversionError(f'Pad {pad.name}: non-circular circle is unsupported')
        surface=pad.kind in {'smd','connect'}
        if surface and pad.drill != 0 or not surface and pad.drill <= 0:
            raise ConversionError(f'Pad {pad.name}: invalid drill for {pad.kind}')
        if int(number(pad.width / 2)) <= 0 or int(number(pad.height)) <= 0:
            raise ConversionError(f'Pad {pad.name}: dimensions below target resolution')
        if pad.drill and int(number(pad.drill)) <= 0:
            raise ConversionError(f'Pad {pad.name}: drill below target resolution')
        copper_sides(pad)
        if pad.kind == 'np_thru_hole':
            warnings.append('NPTH_LIMIT: hole with no copper; .fpl has no explicit plating flag')
        if is_technical_pad(pad):
            warnings.append('TECHNICAL_PAD_CARRIER: aperture-only source pad uses a native padstack with no copper/hole; native netlist and manufacturing behavior unverified')
        if pad.kind=='connect':
            if any(layer.endswith('.Paste') for layer in pad.layers):
                raise ConversionError(f'Pad {pad.name}: contact pads cannot have paste layers')
            warnings.append('CONNECT_PAD_TYPE_FLATTENED: contact pad geometry/layers preserved; KiCad connector attribute is not a native FPL field')
    for text in fp.texts:
        quote(text.content)
        integer_angle(text.rotation)
        if not all(math.isfinite(v) for v in (text.x, text.y, text.size_x, text.size_y, text.thickness)):
            raise ConversionError('Non-finite text dimensions/coordinates')
        if min(text.size_x, text.size_y, text.thickness) <= 0:
            raise ConversionError('Invalid text dimensions')
        if not math.isclose(text.size_x, text.size_y, abs_tol=1e-8):
            raise ConversionError('Anisotropic text size cannot be expressed by one font_size')
        if not text.hidden and (int(number(text.size_y)) <= 0 or int(number(text.thickness)) <= 0):
            raise ConversionError('Text dimensions below target resolution')
        if not text.hidden and text.keep_upright:
            warnings.append('TEXT_UPRIGHT_UNVERIFIED: KiCad keep-upright behavior on placed component rotation is not validated in FreePCB2')
        if text.kind in {'reference', 'value'}:
            if sum(t.kind == text.kind for t in fp.texts) != 1:
                raise ConversionError(f'Duplicate {text.kind} text')
            if text.layer != 'F.SilkS' or text.mirror:
                warnings.append(f'TEXT_FIELD_LAYER: {text.kind} uses native dynamic field; source {text.layer}/mirror cannot be stored')
            warnings.append(f'TEXT_DYNAMIC: {text.kind} content {text.content!r} belongs to the placed component, not .fpl')
    if fp.texts:
        warnings.append('TEXT_ANCHOR: source text positions retained; target font/baseline differs from KiCad centre anchoring')
    for poly in fp.polylines:
        if not math.isfinite(poly.width) or poly.width <= 0 or not all(
                math.isfinite(v) for point in poly.points for v in point):
            raise ConversionError('Invalid graphic dimensions/coordinates')
    for polygon in fp.filled_polygons:
        filled_polygon_points(polygon)
    for circle in fp.filled_circles:
        validate_filled_circle(circle)
    return warnings
