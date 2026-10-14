"""KiCad 9 editor pin decorators as non-electrical CDS body strokes.

The screen painter and plotter differ. This profile follows SCH_PAINTER,
with m_PinSymbolSize=0 (text-derived radii), in source library Y-up coordinates.
"""
import math
from .model import Graphic, SymbolParseError
from .curves import render_curve
from .schemator_format import Corner, PolylineRecord, PART_OUTLINE, native_integer

PROFILE='kicad9-editor-pin-markers-v1'
STYLES=frozenset({'line','inverted','clock','inverted_clock','input_low',
    'clock_low','output_low','edge_clock_high','non_logic'})
HIDDEN_POLICIES=('reject','reveal-with-loss')


def validate_hidden_policy(value):
    if not isinstance(value,str) or value not in HIDDEN_POLICIES:
        raise SymbolParseError('Hidden pin policy must be reject or reveal-with-loss')


def render_markers(pin, body, external, direction, width, tolerance):
    """Return decorators, the terminal's body end, and source sizing metadata."""
    if pin.graphic_style not in STYLES:
        raise SymbolParseError(f'Pin {pin.number}: unsupported graphic style {pin.graphic_style!r}')
    if pin.graphic_style=='line':return [],body,None
    if pin.electrical_type=='no_connect':
        raise SymbolParseError('Styled NC pins require a separate source NC-marker profile')
    dx,dy=direction;bx,by=body
    # KiCad schematic IU is 100nm; default size is integer text height / 2.
    number_iu=math.floor(pin.number_size[1]*10000+.5)
    name_iu=math.floor(pin.name_size[1]*10000+.5)
    radius=(number_iu//2)*100
    clock_size=((name_iu or number_iu)//2)*100
    if radius<=0 or clock_size<=0:
        raise SymbolParseError('Pin marker size collapses on the KiCad 100nm grid')
    records=[];terminal=body;curve=None
    def point(x,y):return Corner(native_integer(x),native_integer(y))
    def stroke(points):
        records.append(PolylineRecord(False,PART_OUTLINE,width,[point(x,y) for x,y in points]))
    shape=pin.graphic_style
    if shape in ('inverted','inverted_clock'):
        if abs(external[0]-bx)+abs(external[1]-by)<=2*radius:
            raise SymbolParseError('Pin too short for inversion bubble and a positive terminal segment')
        center=(bx-dx*radius,by-dy*radius)
        corners,closed,curve=render_curve(Graphic('circle',dict(center=tuple(v/1e6 for v in center),
            radius=radius/1e6),width/1e6,'none',[]),'kicad_sym',tolerance)
        records.append(PolylineRecord(closed,PART_OUTLINE,width,[point(x,y) for x,y in corners]))
        terminal=(native_integer(bx-dx*2*radius),native_integer(by-dy*2*radius))
    if shape in ('clock','inverted_clock','clock_low','edge_clock_high'):
        stroke([(bx-dy*clock_size,by+dx*clock_size),
                (bx+dx*clock_size,by+dy*clock_size),(bx+dy*clock_size,by-dx*clock_size)])
    if shape in ('input_low','clock_low','edge_clock_high'):
        if dx:
            stroke([(bx-dx*2*radius,by),(bx-dx*2*radius,by+2*radius),(bx,by)])
        else:
            stroke([(bx,by-dy*2*radius),(bx-2*radius,by-dy*2*radius),(bx,by)])
    if shape=='output_low':
        if dx:stroke([(bx,by+2*radius),(bx-dx*2*radius,by)])
        else:stroke([(bx-2*radius,by),(bx,by-dy*2*radius)])
    if shape=='non_logic':
        stroke([(bx-(dx-dy)*radius,by-(dx+dy)*radius),(bx+(dx-dy)*radius,by+(dx+dy)*radius)])
        stroke([(bx-(dx+dy)*radius,by+(dx-dy)*radius),(bx+(dx+dy)*radius,by-(dx-dy)*radius)])
    metadata=dict(source_pin_number=pin.number,source_graphic_style=shape,
        source_body_nm=body,target_marker_body_nm=body,external_radius_nm=radius,
        internal_radius_nm=clock_size,source_geometry_profile=PROFILE,
        sizing_policy='KiCad9 editor default m_PinSymbolSize=0; integer 100nm text heights / 2',
        electrical_style_transferred=False,gui_validated=False)
    if curve:metadata.update(center_mm=curve['center_mm'],radius_mm=curve['radius_mm'],
        max_centerline_error_mm=curve['max_centerline_error_mm'],curve_corners=curve['corners'])
    return records,terminal,metadata


def add_presentation_semantics(report, pins, policy):
    if not any(p.hidden or p.graphic_style!='line' for p in pins):return
    report['target']['source_pin_presentation_profile']=PROFILE
    report['counts']['hidden_pins']=sum(p.hidden for p in pins)
    report['counts']['styled_pins']=sum(p.graphic_style!='line' for p in pins)
    report['pin_semantics']['implicit_global_power_transferred']=False
    if any(p.hidden for p in pins):
        report['conversion_settings']['hidden_pin_policy']=policy
        report['pin_semantics']['hidden_pin_policy']=policy
    for source,entry in zip(pins,report['pin_semantics']['pins']):
        entry.update(source_hidden=source.hidden,source_graphic_style=source.graphic_style,
            source_implicit_global_power=source.hidden and source.electrical_type=='power_in',
            native_implicit_global_power_transferred=False,native_connectable=True,
            target_node_flags=[0,1],native_pin_visible=True)
