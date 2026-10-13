"""KiCad source -> verified CDS record subset, with explicit losses."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import re

from .model import Library, Property, SymbolParseError
from .schemator_format import (
    CdsDocument, ComponentRecord, Corner, PolylineRecord, TextRecord,
    PART_NAME, PART_VALUE, PART_OUTLINE, FOOTPRINT, PIN_LINE, PIN_NUMBER,
    PIN_DESCRIPTION, PIN_IDENTIFIER, REFERENCE, PROFILE, TARGET_REVISION,
    TARGET_VERSION, native_integer, safe_string, parse_cds,
)
from .schemator_writer import write_cds
from .curves import DEFAULT_CURVE_TOLERANCE, MAX_BODY_CORNERS, render_curve, validate_tolerance
from .body_graphics import (
    DEFAULT_FILL_TOLERANCE, MAX_SYMBOL_FILL_STROKES, validate_fill_tolerance,
    render_fill, render_graphic_text,
)

# These types share the native numbered endpoint representation. Their KiCad
# electrical rules survive in JSON only; power/no-connect need separate policy.
VISIBLE_LINE_ELECTRICAL = frozenset({
    'passive', 'input', 'output', 'bidirectional', 'tri_state', 'unspecified',
    'free', 'open_collector', 'open_emitter',
})


@dataclass
class SymbolConversionResult:
    cds: str
    report: dict
    document: CdsDocument


class LossySymbolConversionError(SymbolParseError):
    def __init__(self, report: dict):
        super().__init__('Strict mode rejected known symbol conversion losses')
        self.report = report


def _nm(value: float) -> int:
    if not isinstance(value,(float,int)) or not math.isfinite(value):
        raise SymbolParseError('Non-finite symbol dimension')
    scaled=value*1_000_000
    if not math.isfinite(scaled):
        raise SymbolParseError('Symbol dimension overflows target nanometre scale')
    return native_integer(round(scaled))


def _positive(value: float, context: str) -> int:
    result = _nm(value)
    if result <= 0:
        raise SymbolParseError(f'{context} is nonpositive/collapses on target grid')
    return result


def _display(value: str) -> str:
    safe_string(value)
    if any(c in value for c in '~^'):
        raise SymbolParseError('Text markup is outside the CDS straight profile')
    return value


def _property_text(prop: Property, value: str, layer: int) -> TextRecord:
    if len(prop.raw) > 1 and prop.raw[0].startswith('F') and prop.raw[0][1:].isdigit():
        size = float(prop.raw[4])*.0254
    else:
        effects = next((n for n in prop.raw if isinstance(n,list) and n and n[0]=='effects'),[])
        font = next((n for n in effects if isinstance(n,list) and n and n[0]=='font'),[])
        sizes = next((n for n in font if isinstance(n,list) and n and n[0]=='size'),[])
        if len(sizes)!=3:
            raise SymbolParseError('Property has no source font size')
        size = float(sizes[2])
    height = _positive(size,'Property text height')
    angle = prop.at[2]
    if not math.isfinite(angle) or angle % 90:
        raise SymbolParseError('Only quarter-turn property text is supported')
    return TextRecord(_display(value),_nm(prop.at[0]),_nm(prop.at[1]),layer,
                      int(-angle)%360,0 if prop.hidden else height,
                      0 if prop.hidden else max(1,height//10))


def convert_symbol(library: Library, name: str, *, footprint_name: str | None = None,
                   reference: str | None = None, project_name: str = 'KiCad_symbol.cds',
                   default_line_width: float = .254, pin_width: float = .254,
                   curve_tolerance: float = DEFAULT_CURVE_TOLERANCE,
                   fill_tolerance: float = DEFAULT_FILL_TOLERANCE,
                   strict: bool = False) -> SymbolConversionResult:
    """Generate one component; physical footprint/GUI verification stays separate.

    Profile: one unit, one standard body style, visible positive-length ordinary
    line pins, simple body fills and quarter-turn property/body texts.
    Unfilled curves are tessellated with an explicit NM-grid error budget.
    Foreground fill is bounded; background occlusion is lost explicitly.
    No Bezier approximations or pin deduplication are performed.
    """
    if library.diagnostics:
        raise SymbolParseError('Library source diagnostics must be resolved before target generation')
    symbol = library.get_symbol(name)
    if symbol.diagnostics:
        raise SymbolParseError(f'{name}: unresolved source diagnostics (including pin duplicates/extensions)')
    if symbol.unit_count!=1 or any(u.style not in (0,1) for u in symbol.units):
        raise SymbolParseError('CDS profile supports one unit and standard body style only')
    if symbol.power or not symbol.in_bom or not symbol.on_board:
        raise SymbolParseError('Power/virtual/BOM-excluded symbols are outside the CDS profile')
    validate_tolerance(curve_tolerance)
    validate_fill_tolerance(fill_tolerance)
    line_width = _positive(default_line_width,'Default line width')
    pin_width_nm = _positive(pin_width,'Pin width')
    safe_string(project_name)
    props = symbol.properties
    if not {'Reference','Value'} <= props.keys():
        raise SymbolParseError('Symbol requires Reference and Value properties')
    if reference is None:
        prefix = props['Reference'].value
        if not re.fullmatch(r'[A-Za-z_]+',prefix):
            raise SymbolParseError('CDS profile requires an ASCII reference prefix or explicit reference')
        reference = prefix+'1'
    if not REFERENCE.fullmatch(reference):
        raise SymbolParseError('CDS reference must have an ASCII prefix and positive numeric suffix')
    _display(footprint_name or 'PART')
    if footprint_name == '':
        raise SymbolParseError('Explicit footprint name cannot be empty')
    diagnostics=[]

    def diagnostic(code, severity, message, **context):
        diagnostics.append(dict(code=code,severity=severity,message=message,context=context))

    diagnostic('SYMBOL_TEXT_RENDERING','loss',
        'SIMPLEX replaces source fonts; source property anchors are used as native baselines. '
        'Justification, text styling and exact glyph bounds are not reproduced.')
    diagnostic('TARGET_PIN_STROKE','assumption',
        'Pin stroke width is a declared conversion setting; the library has no resolved project pin stroke.',
        width_mm=pin_width)
    if footprint_name is None:
        diagnostic('SYMBOL_FOOTPRINT_UNRESOLVED','loss',
            'Native PART placeholder used; source footprint identifier/filters are retained in JSON.')
    else:
        diagnostic('SYMBOL_FOOTPRINT_MAPPING_UNVERIFIED','assumption',
            'An explicit native footprint name was assigned; pad correspondence is not yet verified.',
            footprint=footprint_name)
    metadata = {k:p.value for k,p in props.items() if k not in {'Reference','Value','Footprint'} and p.value not in ('','~')}
    if metadata:
        diagnostic('SYMBOL_METADATA_NOT_TRANSFERRED','loss',
            'Source datasheet/custom properties/footprint filters retained only in JSON.',properties=list(metadata))
    source_footprint = props.get('Footprint')
    if footprint_name is not None and source_footprint and source_footprint.value not in ('','~',footprint_name):
        diagnostic('SYMBOL_FOOTPRINT_REPLACED','loss',
            'Source KiCad identifier replaced with the explicitly assigned native footprint name.',
            source=source_footprint.value,target=footprint_name)
    polylines,curves=[],[]
    fills,texts,owners=[],[],[]
    fill_strokes=0
    body_corners=0
    for unit in symbol.units:
        for index,graphic in enumerate(unit.graphics):
            if graphic.kind=='text':
                if graphic.fill!='none':
                    raise SymbolParseError('Filled graphic text is outside the body profile')
                text,metadata=render_graphic_text(graphic,library.source_format)
                metadata.update(unit=unit.number,graphic=index)
                texts.append((text,metadata))
                continue
            if graphic.kind not in ('rectangle','polyline','circle','arc','legacy_arc') or graphic.fill not in ('none','outline','background'):
                raise SymbolParseError(f'Unsupported CDS graphic: {graphic.kind}/{graphic.fill}')
            if library.source_format=='kicad_sym':
                stroke = next((n for n in graphic.raw if isinstance(n,list) and n and n[0]=='stroke'),[])
                style = next((n[1] for n in stroke if isinstance(n,list) and len(n)==2 and n[0]=='type'),'default')
                if style not in ('default','solid') or any(isinstance(n,list) and n and n[0]=='color' for n in stroke):
                    raise SymbolParseError('Styled/colored graphic strokes are outside the CDS profile')
            if graphic.width < 0:
                raise SymbolParseError('Negative source stroke width')
            width = _positive(graphic.width,'Graphic width') if graphic.width else line_width
            if not graphic.width:
                diagnostic('SOURCE_LINE_WIDTH_DEFAULT','assumption',
                    'Zero source stroke resolves to declared default width.',unit=unit.number,graphic=index,width_mm=default_line_width)
            owners.append(len(polylines))
            if graphic.fill!='none':
                expanded,metadata=render_fill(graphic,library.source_format,width,fill_tolerance,curve_tolerance)
                fill_strokes+=len(expanded)
                if fill_strokes>MAX_SYMBOL_FILL_STROKES:
                    raise SymbolParseError('Symbol fills exceed 4096 emitted polylines')
                body_corners+=sum(len(p.corners) for p in expanded)
                if body_corners>MAX_BODY_CORNERS:
                    raise SymbolParseError('Symbol body exceeds 32768 native corners')
                metadata.update(unit=unit.number,graphic=index,
                    target_polyline_indices=list(range(len(polylines),len(polylines)+len(expanded))))
                fills.append(metadata)
                if graphic.fill=='background':
                    diagnostic('SYMBOL_BACKGROUND_FILL_NOT_TRANSFERRED','loss',
                        'Only the body boundary is retained; source background color and occlusion are not transferred.',
                        **metadata)
                else:
                    diagnostic('SYMBOL_FILL_APPROXIMATED','approximation',
                        'Foreground fill covered by boundary and overlapping straight strokes; tolerance includes quantization.',
                        **metadata)
                polylines.extend(expanded)
                continue
            if graphic.kind in ('circle','arc','legacy_arc'):
                points,closed,metadata = render_curve(graphic,library.source_format,curve_tolerance)
                corners = [Corner(x,y) for x,y in points]
                metadata.update(unit=unit.number,graphic=index,target_polyline_index=len(polylines))
                curves.append(metadata)
                diagnostic('SYMBOL_CURVE_APPROXIMATED','approximation',
                    'Unfilled curve converted to straight segments; tolerance includes NM quantization.',
                    **metadata)
                if 'legacy_resolution' in metadata:
                    resolution = metadata['legacy_resolution']
                    changed = max([resolution['radius_difference_mm'],*resolution['endpoint_shifts_mm']])>1e-6
                    diagnostic('SYMBOL_LEGACY_ARC_RESOLVED','loss' if changed else 'assumption',
                        'Legacy overdefined arc resolved by the explicit KiCad9 geometry profile; raw definitions retained.',
                        unit=unit.number,graphic=index,**resolution)
            elif graphic.kind=='rectangle':
                x1,y1=graphic.geometry['start']
                x2,y2=graphic.geometry['end']
                if x1==x2 or y1==y2:
                    raise SymbolParseError('Degenerate source rectangle')
                points=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
                closed=True
                corners=[Corner(_nm(x),_nm(y)) for x,y in points]
            else:
                points=list(graphic.geometry['points'])
                closed=len(points)>2 and points[0]==points[-1]
                if closed:
                    points.pop()
                corners=[Corner(_nm(x),_nm(y)) for x,y in points]
            body_corners += len(corners)
            if body_corners > MAX_BODY_CORNERS:
                raise SymbolParseError('Symbol body exceeds 32768 native corners')
            polylines.append(PolylineRecord(closed,PART_OUTLINE,width,corners))
    available=set(owners)
    for text,metadata in texts:
        if not available:
            raise SymbolParseError('Graphic text requires a distinct body contour carrier; no carrier available')
        owner=min(available,key=lambda i:(min((c.x-text.x)**2+(c.y-text.y)**2 for c in polylines[i].corners),i))
        available.remove(owner)
        polylines[owner].description=text
        metadata['target_polyline_index']=owner
        diagnostic('SYMBOL_GRAPHIC_TEXT_LAYOUT','loss',
            'Literal graphic text is a body description with SIMPLEX font; source anchor is used as baseline. '
            'Justification, styling, exact glyph bounds and source z-order are not reproduced.',**metadata)
    pins=symbol.pins_for()
    if not pins:
        raise SymbolParseError('CDS profile requires at least one physical pin')
    seen=set()
    pin_semantics=[]
    electrical_counts={}
    for pin in pins:
        if pin.hidden or pin.graphic_style!='line' or pin.alternates:
            raise SymbolParseError(f'Pin {pin.number}: only visible line pins without alternates are supported')
        if pin.electrical_type not in VISIBLE_LINE_ELECTRICAL:
            raise SymbolParseError(f'Pin {pin.number}: unsupported electrical type {pin.electrical_type!r}; '
                                   'power/no-connect types require a separate conversion policy')
        if not PIN_IDENTIFIER.fullmatch(pin.number) or pin.number in seen:
            raise SymbolParseError(f'Pin {pin.number!r}: ambiguous/unsupported native number')
        seen.add(pin.number)
        _positive(pin.length,'Pin length')
        if pin.at[2] not in (0,90,180,270):
            raise SymbolParseError('Pin angle outside quarter-turn profile')
        dx,dy={0:(1,0),90:(0,1),180:(-1,0),270:(0,-1)}[pin.at[2]]
        external=(_nm(pin.at[0]),_nm(pin.at[1]))
        body=(_nm(pin.at[0]+dx*pin.length),_nm(pin.at[1]+dy*pin.length))
        num_size=_positive(pin.number_size[1],'Pin number text height')
        show_number=not symbol.pin_numbers_hidden
        mid=((external[0]+body[0])//2,(external[1]+body[1])//2)
        offset=max(pin_width_nm,num_size//2)
        label=TextRecord(pin.number,mid[0]-dy*offset,mid[1]+dx*offset,PIN_NUMBER,
                         0,num_size if show_number else 0,max(1,num_size//10) if show_number else 0)
        poly=PolylineRecord(False,PIN_LINE,pin_width_nm,[Corner(*body),Corner(*external,node=1)],pin=label)
        if not symbol.pin_names_hidden and pin.name not in ('','~'):
            size=_positive(pin.name_size[1],'Pin name text height')
            distance=_nm(symbol.pin_name_offset)
            poly.description=TextRecord(_display(pin.name),body[0]+dx*distance,body[1]+dy*distance,
                                        PIN_DESCRIPTION,0,size,max(1,size//10))
        pin_semantics.append(dict(source_pin_number=pin.number,source_pin_name=pin.name,
            source_electrical_type=pin.electrical_type,target_pin_number=label.value,
            target_polyline_index=len(polylines),connection_point_nm=external))
        electrical_counts[pin.electrical_type]=electrical_counts.get(pin.electrical_type,0)+1
        polylines.append(poly)
    extended_electrical = any(pin.electrical_type!='passive' for pin in pins)
    if extended_electrical:
        diagnostic('SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED','loss',
            'Source electrical types are retained in JSON only. The confirmed CDS profile stores '
            'a numbered connection endpoint and optional name, without KiCad electrical rules; '
            'input/output direction, drive constraints and ERC semantics are not transferred.',
            source_electrical_types=electrical_counts)
    else:
        # Preserve the original passive-only reports and artifacts exactly.
        diagnostic('SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED','loss',
            'Physical pin numbers/connectivity records are retained; KiCad passive electrical type is not a native ERC attribute.')
    if any(poly.pin and (poly.pin.size or poly.description) for poly in polylines):
        diagnostic('SYMBOL_PIN_LABEL_LAYOUT','loss',
            'Pin numbers/names use a declared horizontal placement policy; exact KiCad automatic label layout is not reproduced.')
    coords=[c for p in polylines for c in p.corners]
    coords.extend(Corner(text.x,text.y) for text,_ in texts)
    margin=max(p.width for p in polylines)//2+25400  # native selection width + 1 mil
    bounds=tuple(native_integer(v) for v in (
        min(c.x for c in coords)-margin,min(c.y for c in coords)-margin,
        max(c.x for c in coords)+margin,max(c.y for c in coords)+margin))
    reference_text=_property_text(props['Reference'],reference,PART_NAME)
    value_text=_property_text(props['Value'],props['Value'].value,PART_VALUE)
    fp_text=TextRecord(footprint_name or 'PART',0,0,FOOTPRINT,0,0,0)
    component=ComponentRecord(len(pins),bounds,reference_text,value_text,fp_text,polylines)
    options=dict(version=TARGET_VERSION,file_version=TARGET_VERSION,project_name=project_name,
        units='MM',default_font='2',default_node_width='-1000000',visible_grid_spacing='2540000',
        polyline_grid_spacing='254000',text_grid_spacing='254000')
    document=CdsDocument(options,[component])
    cds=write_cds(document)
    # Exercise the independent parser against the actual emitted text.
    parsed=parse_cds(cds)
    if parsed!=document:
        raise SymbolParseError('Internal CDS record verification failed')
    data=cds.encode('cp1251')
    report=dict(schema_version=1,kind='schemator_symbol_conversion',
        status='generated_with_loss',target=dict(repository='niconson/Schematic-Constructor',
            revision=TARGET_REVISION,version=TARGET_VERSION,profile=PROFILE,encoding='cp1251',
            coordinates='nanometres, Y up; source library coordinates preserved',
            text_angle_rule='negative source angle modulo 360'),
        contract_verified_against_source=True,target_records_validated=True,
        target_output_generated=True,target_import_verified=False,gui_validated=False,
        source_format=library.source_format,source_version=library.version,source_symbol=asdict(symbol),
        conversion_settings=dict(footprint_name=footprint_name,reference=reference,
            project_name=project_name,default_line_width_mm=default_line_width,pin_width_mm=pin_width),
        target_component=asdict(component),physical_pin_mapping_verified=False,
        diagnostics=diagnostics,artifact_sha256=hashlib.sha256(data).hexdigest(),
        counts=dict(components=1,pins=len(pins),polylines=len(polylines),
            losses=sum(d['severity']=='loss' for d in diagnostics),
            assumptions=sum(d['severity']=='assumption' for d in diagnostics)))
    if extended_electrical:
        report['target']['source_pin_profile']='visible-line-electrical-v1'
        report['pin_semantics']=dict(electrical_rules_transferred=False,
            native_representation='numbered layer-8 segment; body Node=0, external Node=1; optional layer-14 name',
            pins=pin_semantics)
    if curves:
        diagnostic('SYMBOL_CURVE_STROKE_UNVERIFIED','assumption',
            'Curve tolerance covers centerlines; native stroke caps/joins and rasterization are not GUI-verified.')
        report['curves'] = curves
        report['conversion_settings']['curve_tolerance_mm'] = curve_tolerance
        report['target']['source_graphics_profile'] = 'unfilled-curves-v1'
        report['counts']['approximations'] = len(curves)
        report['counts']['assumptions'] += 1
    if fills or texts:
        report['target']['source_body_profile']='bounded-fills-body-text-v1'
        report['counts']['approximations']=len(curves)+sum(f['source_fill']=='outline' for f in fills)
    if fills:
        report['filled_graphics']=fills
        report['conversion_settings']['fill_tolerance_mm']=fill_tolerance
        if any(f['source_kind']=='circle' for f in fills):
            report['conversion_settings']['curve_tolerance_mm']=curve_tolerance
        report['counts']['filled_graphics']=len(fills)
        report['counts']['fill_polylines']=fill_strokes
        if any(f['source_fill']=='outline' for f in fills):
            diagnostic('SYMBOL_FILL_STROKE_UNVERIFIED','assumption',
                'Fill coverage/expansion bounds assume ideal round-ended strokes; native caps/joins, draw order and rasterization are not GUI-verified.')
            report['counts']['assumptions']+=1
    if texts:
        report['graphic_texts']=[metadata for _,metadata in texts]
        report['counts']['graphic_texts']=len(texts)
    if strict and report['counts']['losses']:
        report.update(status='rejected_loss',target_output_generated=False)
        report['proposed_artifact_sha256']=report.pop('artifact_sha256')
        raise LossySymbolConversionError(report)
    return SymbolConversionResult(cds,report,document)
