"""Verified FreePCB2 2.428 encoding rules and target limits."""
from __future__ import annotations

import math

from .errors import ConversionError
from .model import Pad


PAD_SHAPES = {'circle': 1, 'rect': 3, 'roundrect': 4, 'oval': 5}


GRAPHIC_LAYERS = {'F.SilkS': 4, 'B.SilkS': 5, 'F.Fab': 7, 'B.Fab': 8,
                  'Dwgs.User': 7, 'Cmts.User': 7}


TARGET_REVISION = '3af0f9b9a234c97f2d21455c936abeb8439d2d45'


def integer_angle(value: float) -> int:
    if not math.isfinite(value) or not math.isclose(value, round(value), rel_tol=0, abs_tol=1e-8):
        raise ConversionError(f'FreePCB2 stores integer angles; unsupported angle {value}')
    # KiCad positive rotation is CCW; FreePCB pad/text rotation is clockwise.
    return -round(value) % 360


def quote(value: str) -> str:
    # No escaping convention for embedded quotes verified in the target reader.
    if '"' in value or any(ord(c) < 32 for c in value):
        raise ConversionError(f'FreePCB quoted field cannot safely represent {value!r}')
    return f'"{value}"'


def pad_shape(shape: str) -> int:
    if shape not in PAD_SHAPES:
        raise ConversionError(f'Unsupported KiCad pad shape: {shape}')
    return PAD_SHAPES[shape]


def is_technical_pad(pad: Pad) -> bool:
    """Restricted aperture-only SMD profile; no implicit copper or wildcard layers."""
    return pad.kind=='smd' and bool(pad.layers) and set(pad.layers)<= {'F.Mask','B.Mask','F.Paste','B.Paste'}


def copper_sides(pad: Pad) -> set[str]:
    if is_technical_pad(pad):
        return set()
    copper = {layer for layer in pad.layers if layer.endswith('.Cu')}
    if pad.kind == 'np_thru_hole':
        return set()
    if copper == {'*.Cu'} and pad.kind == 'thru_hole':
        return {'top', 'inner', 'bottom'}
    if copper - {'F.Cu', 'B.Cu'}:
        raise ConversionError(f'Pad {pad.name}: selected inner copper layers cannot be expressed by one inner_pad')
    if not copper:
        raise ConversionError(f'Pad {pad.name}: no copper layers')
    if pad.kind in {'smd','connect'} and len(copper) != 1:
        raise ConversionError(f'Pad {pad.name}: surface pad must have one outer copper layer')
    return {side for layer, side in [('F.Cu', 'top'), ('B.Cu', 'bottom')] if layer in copper}


def number(value: float) -> str:
    """Millimetres -> NM, quantized to the reader's 10 nm grid."""
    if not math.isfinite(value) or abs(value) > 2147.48364:
        raise ConversionError('Dimension exceeds the target signed 32-bit NM range')
    return str(round(value * 100_000) * 10)


def target_point(x: float, y: float) -> tuple[str, str]:
    # KiCad Y down -> FreePCB2 Y up. No translation of the footprint origin.
    return number(x), number(-y)
