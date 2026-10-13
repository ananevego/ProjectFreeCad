"""Unfilled symbol curves -> bounded straight segments in the source Y-up frame.

Legacy arcs use KiCad 9.0.0 loadArc/MapAnglesV6/CalcArcAngles/GetRadius as an
explicit resolution profile. Stored endpoint/radius disagreements are reported
separately from the tessellation tolerance; raw source records remain intact.
"""
from __future__ import annotations

import math
import re

from src.footprint_converter.geometry import sample_arc, arc_points
from src.footprint_converter.errors import ConversionError
from .model import Graphic, SymbolParseError
from .schemator_format import INT_MAX, native_integer

DEFAULT_CURVE_TOLERANCE = .01
MAX_BODY_CORNERS = 32768
SCH_IU_PER_MM = 10000  # KiCad 9.0.0 include/base_units.h, 100 nm schematic IU


def validate_tolerance(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or not .00001 < value <= 1:
        raise SymbolParseError('Symbol curve tolerance must be finite, >0.00001 and <=1 mm')


def _dimension(value: float, *, positive=False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > INT_MAX/1e6 or positive and value <= 0:
        raise SymbolParseError('Invalid/out-of-range symbol curve geometry')
    return value


def _point(value) -> tuple:
    if len(value) != 2:
        raise SymbolParseError('Invalid symbol curve point')
    return tuple(_dimension(v) for v in value)


def _round_iu(value: float) -> int:
    # KiROUND rounds ties away from zero, unlike Python's built-in round.
    return math.floor(value+.5) if value >= 0 else math.ceil(value-.5)


def _legacy_raw(graphic: Graphic, kind: str) -> None:
    raw = graphic.raw
    slots = raw[1:9]+raw[10:14] if kind=='A' else raw[1:7]
    if not raw or raw[0] != kind or len(raw) not in ((10,14) if kind=='A' else (8,)) or any(
            not isinstance(v,str) or not re.fullmatch(r'-?[0-9]+',v) or
            len(v.lstrip('-')) > 10 or abs(int(v)) > INT_MAX for v in slots):
        raise SymbolParseError('Legacy curve profile requires native integer mils/tenth-degree fields')


def _legacy_swap(start_tenths: int, end_tenths: int) -> bool:
    # Algebraic form of pinned MapAnglesV6. Its 0.1-degree perturbation is
    # essential for deciding which semicircle to retain at exactly 180 degrees.
    a, b = start_tenths % 3600, end_tenths % 3600
    if b-a >= 1800:
        a -= 1
        b += 1
    a, b = (-a) % 3600, (-b) % 3600
    if b < a:
        b += 3600
    return b-a > 1800


def _legacy_arc(graphic: Graphic):
    _legacy_raw(graphic,'A')
    data = graphic.geometry
    center = _point(data['center'])
    nominal_radius = _dimension(data['radius'],positive=True)
    angles = data['start_angle'], data['end_angle']
    if not all(math.isfinite(a) and math.isclose(a*10,round(a*10),abs_tol=1e-8,rel_tol=0) for a in angles):
        raise SymbolParseError('Legacy arc angles must be integral tenths of degrees')
    center_iu = tuple(_round_iu(v*SCH_IU_PER_MM) for v in center)
    if ('start' in data) != ('end' in data):
        raise SymbolParseError('Legacy arc needs both explicit endpoints')
    if 'start' in data:
        endpoints_iu = [tuple(_round_iu(v*SCH_IU_PER_MM) for v in _point(data[key])) for key in ('start','end')]
    else:
        radius_iu = _round_iu(nominal_radius*SCH_IU_PER_MM)
        endpoints_iu = [(center_iu[0]+_round_iu(radius_iu*math.cos(math.radians(a%360))),
                         center_iu[1]+_round_iu(radius_iu*math.sin(math.radians(a%360)))) for a in angles]
    swapped = _legacy_swap(round(angles[0]*10),round(angles[1]*10))
    if swapped:
        endpoints_iu.reverse()
    radial = [(x-center_iu[0],y-center_iu[1]) for x,y in endpoints_iu]
    if any(x==y==0 for x,y in radial):
        raise SymbolParseError('Legacy arc endpoint coincides with center')
    radius = _dimension(_round_iu(math.hypot(*radial[0]))/SCH_IU_PER_MM,positive=True)
    start_angle, end_angle = [math.atan2(y,x) for x,y in radial]
    sweep = -((start_angle-end_angle)%math.tau)
    closed = sweep==0
    if closed:
        sweep = -math.tau
    center = tuple(v/SCH_IU_PER_MM for v in center_iu)
    resolved_ends = [(center[0]+radius*math.cos(a),center[1]+radius*math.sin(a)) for a in (start_angle,end_angle)]
    stored_ends = [tuple(v/SCH_IU_PER_MM for v in point) for point in endpoints_iu]
    shifts = [math.dist(a,b) for a,b in zip(resolved_ends,stored_ends)]
    resolution = dict(profile='kicad-9.0.0-legacy-arc',schematic_iu_per_mm=SCH_IU_PER_MM,
        endpoints_swapped=swapped,explicit_endpoints='start' in data,
        radius_difference_mm=abs(radius-nominal_radius),endpoint_shifts_mm=shifts,
        original_endpoints_in_resolved_order=stored_ends,resolved_endpoints_mm=resolved_ends,
        policy='KiCad9 endpoint swap, clockwise in source Y-up frame; GetRadius rounded to 100nm IU; end direction projected to that radius')
    return center,radius,start_angle,sweep,closed,resolution


def _modern_geometry(data: dict):
    start, mid, end = (_point(data[key]) for key in ('start','mid','end'))
    bx, by = mid[0]-start[0], mid[1]-start[1]
    cx, cy = end[0]-start[0], end[1]-start[1]
    determinant = 2*(bx*cy-by*cx)
    if abs(determinant) <= 1e-12*max(bx*bx+by*by,cx*cx+cy*cy,1e-12):
        raise SymbolParseError('Arc start/mid/end are coincident or collinear')
    b2, c2 = bx*bx+by*by, cx*cx+cy*cy
    ux, uy = (cy*b2-by*c2)/determinant, (bx*c2-cx*b2)/determinant
    center = _point((start[0]+ux,start[1]+uy))
    radius = _dimension(math.hypot(ux,uy),positive=True)
    if any(abs(math.dist(center,p)-radius)>1e-6 for p in (start,mid,end)):
        raise SymbolParseError('Numerically unstable arc circle')
    angles = [math.atan2(p[1]-center[1],p[0]-center[0]) for p in (start,mid,end)]
    sweep = (angles[2]-angles[0])%math.tau
    if (angles[1]-angles[0])%math.tau > sweep:
        sweep -= math.tau
    return center,radius,angles[0],sweep


def render_curve(graphic: Graphic, source_format: str, tolerance: float) -> tuple[list[tuple[int,int]],bool,dict]:
    """Return rounded native NM corners and the declared error/resolution data."""
    validate_tolerance(tolerance)
    resolution = None
    try:
        if graphic.fill != 'none':
            raise SymbolParseError('Filled symbol curves are outside the profile')
        if graphic.kind=='circle':
            if source_format=='legacy_lib':
                _legacy_raw(graphic,'C')
            center = _point(graphic.geometry['center'])
            radius = _dimension(graphic.geometry['radius'],positive=True)
            start, sweep, closed = 0, math.tau, True
            points = sample_arc(center,radius,start,sweep,tolerance)
        elif graphic.kind=='arc':
            center,radius,start,sweep = _modern_geometry(graphic.geometry)
            closed = False
            points = arc_points(graphic.geometry['start'],graphic.geometry['mid'],graphic.geometry['end'],tolerance)
        elif graphic.kind=='legacy_arc':
            center,radius,start,sweep,closed,resolution = _legacy_arc(graphic)
            points = sample_arc(center,radius,start,sweep,tolerance)
        else:
            raise SymbolParseError('Unknown symbol curve')
    except (ConversionError, KeyError, TypeError, OverflowError) as error:
        raise SymbolParseError(f'Invalid symbol curve: {error}') from error
    if closed:
        points = points[:-1]  # native outline closes the final segment itself
    corners = [tuple(native_integer(round(_dimension(v)*1e6)) for v in point) for point in points]
    if not (3 if closed else 2) <= len(corners) <= 4096 or len(set(corners)) != len(corners):
        raise SymbolParseError('Symbol curve collapses on the native grid or exceeds 4096 corners')
    metadata = dict(source_kind=graphic.kind,center_mm=center,radius_mm=radius,
        start_angle_radians=start,sweep_radians=sweep,closed=closed,
        corners=len(corners),segments=len(corners) if closed else len(corners)-1,
        tolerance_mm=tolerance,max_centerline_error_mm=tolerance,
        error_scope='Resolved curve centerline -> straight native NM segments; source-resolution changes are separate',
        quantization_budget_mm=.00001)
    if resolution is not None:
        metadata['legacy_resolution'] = resolution
    return corners,closed,metadata
