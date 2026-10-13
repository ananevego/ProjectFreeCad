"""Bounded body fills and literal text attributes; no file or model access."""
from dataclasses import replace
import math

from src.footprint_converter.errors import ConversionError
from src.footprint_converter.geometry import filled_polygon_points, tessellate_fills
from src.footprint_converter.model import Footprint, FilledCircle, FilledPolygon
from .curves import render_curve
from .model import SymbolParseError
from .modern import one, flag, scalar
from .schemator_format import (
    Corner, PolylineRecord, TextRecord, PART_OUTLINE, PIN_DESCRIPTION,
    native_integer, safe_body_text,
)

DEFAULT_FILL_TOLERANCE = .01
MAX_SYMBOL_FILL_STROKES = 4096


def validate_fill_tolerance(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not .00002 < value <= 1:
        raise SymbolParseError('Symbol fill tolerance must be finite, >0.00002 and <=1 mm')


def _nm(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise SymbolParseError('Non-finite body text dimension')
    scaled=value*1e6
    if not math.isfinite(scaled):
        raise SymbolParseError('Body text dimension overflows target scale')
    return native_integer(round(scaled))


def render_fill(graphic, source_format, width_nm, fill_tolerance, curve_tolerance):
    """Foreground fills share the existing pure geometry tessellator, in Y-up.

    Its 10nm grid and round-ended stroke assumptions are stated in the report.
    Background fill is represented by a validated boundary with explicit loss.
    """
    validate_fill_tolerance(fill_tolerance)
    if graphic.fill not in ('outline','background') or graphic.kind not in ('rectangle','polyline','circle'):
        raise SymbolParseError('Filled profile supports rectangles, closed simple polygons and circles only')
    width=width_nm/1e6
    empty=Footprint('symbol',[],[],[],[])
    metadata=dict(source_kind=graphic.kind,source_fill=graphic.fill,
        coordinates='source Y up; foreground fills use 10nm grid; background curves use 1nm grid')
    try:
        if graphic.kind=='circle':
            _,_,curve=render_curve(replace(graphic,fill='none'),source_format,curve_tolerance)
            center=tuple(curve['center_mm']);radius=curve['radius_mm']
            empty.filled_circles=[FilledCircle(center,(center[0]+radius,center[1]),width,'symbol')]
            metadata.update(center_mm=center,radius_mm=radius)
            if graphic.fill=='background':
                points,closed,_=render_curve(replace(graphic,fill='none'),source_format,curve_tolerance)
                result=[PolylineRecord(closed,PART_OUTLINE,width_nm,[Corner(x,y) for x,y in points])]
                metadata['boundary_centerline_error_mm']=curve_tolerance
            else:
                # Same chord budget used by the shared filled-circle sampler.
                minimum_width_nm=math.floor(2*(fill_tolerance-.00002)*100_000)*10
                metadata['boundary_centerline_error_mm']=min(curve_tolerance,max(width_nm,minimum_width_nm)/4e6)
        else:
            if graphic.kind=='rectangle':
                (x1,y1),(x2,y2)=graphic.geometry['start'],graphic.geometry['end']
                points=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
            else:
                points=list(graphic.geometry['points'])
                if len(points)<4 or points[0]!=points[-1]:
                    raise SymbolParseError('Filled polyline requires an explicitly closed contour')
                points.pop()
            polygon=FilledPolygon(tuple(points),width,'symbol')
            vertices=filled_polygon_points(polygon)
            empty.filled_polygons=[polygon]
            if graphic.fill=='background':
                result=[PolylineRecord(True,PART_OUTLINE,width_nm,[Corner(x,y) for x,y in vertices])]
        if graphic.fill=='background':
            metadata.update(native_policy='boundary_only',background_occlusion_transferred=False,
                            emitted_polylines=1,collapsed_spans_skipped=0)
            return result,metadata
        warnings=[]
        expanded=tessellate_fills(empty,fill_tolerance,warnings,curve_tolerance=curve_tolerance)
        result=[];collapsed=0
        for poly in expanded.polylines:
            # Encode precisely on the tessellator's proven 10nm grid, without
            # applying the footprint writer's Y inversion to symbol geometry.
            corners=[Corner(native_integer(round(x*100_000)*10),native_integer(round(y*100_000)*10))
                     for x,y in poly.points]
            if not poly.closed and corners[0]==corners[-1]:
                collapsed+=1  # Narrow tip already covered by the boundary stroke.
                continue
            result.append(PolylineRecord(poly.closed,PART_OUTLINE,
                native_integer(round(poly.width*100_000)*10),corners))
        metadata.update(native_policy='boundary_and_overlapping_strokes',
            nominal_interior_covered=True,encoded_expansion_bound_mm=fill_tolerance,
            bound_scope='ideal round-ended strokes relative to source fill plus resolved source stroke; native caps/rasterization unverified',
            emitted_polylines=len(result),collapsed_spans_skipped=collapsed,
            stroke_width_nm=result[0].width)
        return result,metadata
    except ConversionError as error:
        raise SymbolParseError(str(error)) from error


def render_graphic_text(graphic, source_format):
    data=graphic.geometry
    value=safe_body_text(data['text'])
    x,y,angle=data['at']
    if not math.isfinite(angle) or angle%90:
        raise SymbolParseError('Graphic text requires quarter-turn angle')
    height=_nm(data['size'][1])
    if height<=0:
        raise SymbolParseError('Graphic text height collapses on target grid')
    if source_format=='legacy_lib':
        hidden=data['hidden'];thickness=height//10
    else:
        effects=one(graphic.raw,'effects',required=True)
        font=one(effects,'font',required=True)
        for node,allowed in ((effects,{'font','justify','hide'}),(font,{'size','face','thickness','bold','italic'})):
            if any((item[0] if isinstance(item,list) and item else item) not in allowed for item in node[1:]):
                raise SymbolParseError('Unknown graphic text effect/font option')
        hidden=flag(effects,'hide')
        source_thickness=scalar(font,'thickness')
        try:
            thickness=_nm(float(source_thickness)) if source_thickness is not None else height//10
        except ValueError as error:
            raise SymbolParseError('Invalid graphic text thickness') from error
    if thickness<=0:
        raise SymbolParseError('Graphic text stroke must be positive on target grid')
    text=TextRecord(value,_nm(x),_nm(y),PIN_DESCRIPTION,int(-angle)%360,
                    0 if hidden else height,0 if hidden else thickness)
    metadata=dict(source_text=value,source_anchor_mm=(x,y),source_angle_degrees=angle,
        source_size_mm=data['size'],hidden=hidden,native_record='body description',
        native_layer=PIN_DESCRIPTION,font_layout_transferred=False,
        glyph_bounds_verified=False,anchor_policy='source anchor used as native baseline; glyph bounds excluded')
    return text,metadata
