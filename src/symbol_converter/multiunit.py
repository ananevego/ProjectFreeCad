"""Disjoint logical units -> one ordinary CDS component with declared layout.

Native hierarchical merge/BLK records are intentionally outside this profile.
Only already-validated single-unit records are translated, never source meshes.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import math

from .model import Library, SymbolParseError
from .curves import MAX_BODY_CORNERS
from .body_graphics import MAX_SYMBOL_FILL_STROKES
from .schemator_format import ComponentRecord, CdsDocument, PART_OUTLINE, native_integer, parse_cds
from .schemator_writer import write_cds

DEFAULT_UNIT_GAP = 2.54
MAX_COMPOUND_UNITS = 16
PROFILE = 'disjoint-units-layout-v1'
SHARED_DIAGNOSTICS = {
    'SYMBOL_TEXT_RENDERING','TARGET_PIN_STROKE','SYMBOL_FOOTPRINT_UNRESOLVED',
    'SYMBOL_FOOTPRINT_MAPPING_UNVERIFIED','SYMBOL_METADATA_NOT_TRANSFERRED',
    'SYMBOL_FOOTPRINT_REPLACED','SYMBOL_PIN_LABEL_LAYOUT',
    'SYMBOL_CURVE_STROKE_UNVERIFIED','SYMBOL_FILL_STROKE_UNVERIFIED',
}


def validate_unit_gap(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= 100 or round(value*1e6)<1:
        raise SymbolParseError('Unit gap must be finite, positive on the NM grid and <=100 mm')


def _view(library, symbol, unit):
    view=deepcopy(symbol)
    view.unit_count=1
    view.units=[block for block in view.units if block.number in (0,unit)]
    for block in view.units:
        if block.number==unit:block.number=1
    return Library(library.source_format,library.version,{symbol.name:view})


def _move_text(text, dx):
    if text is not None:text.x=native_integer(text.x+dx)


def _placed_metadata(item, unit, dx, start, kind):
    placed=deepcopy(item)
    placed['unit']=0 if item['unit']==0 else unit
    placed.update(rendered_unit=unit,translation_nm=(dx,0))
    if kind=='filled_graphics':
        placed['target_polyline_indices']=[i+start for i in placed['target_polyline_indices']]
        placed['coordinates']='source geometry quantized in the unit frame, then translated exactly in integer NM'
    else:
        placed['target_polyline_index']+=start
    if 'center_mm' in placed:
        placed['source_center_mm']=placed['center_mm']
        placed['center_mm']=(placed['center_mm'][0]+dx/1e6,placed['center_mm'][1])
    if kind=='graphic_texts':
        x,y=placed['source_anchor_mm']
        placed['native_anchor_nm']=(native_integer(round(x*1e6)+dx),native_integer(round(y*1e6)))
    if 'legacy_resolution' in placed:
        placed['legacy_resolution_frame']='source unit before compound placement'
    return placed


def compose_units(library, symbol, *, converter, unit_gap, conversion_settings):
    """Compose only unique physical pins; shared/common pins never deduplicate."""
    validate_unit_gap(unit_gap)
    if not 2 <= symbol.unit_count <= MAX_COMPOUND_UNITS:
        raise SymbolParseError('Compound profile supports 2..16 logical units')
    if any(not 0 <= block.number <= symbol.unit_count for block in symbol.units):
        raise SymbolParseError('Source block outside declared unit range')
    if any(block.pins for block in symbol.units if block.number==0):
        raise SymbolParseError('Multi-unit common pins require a shared-pin policy; no automatic deduplication')
    counts=Counter(pin.number for block in symbol.units for pin in block.pins)
    repeated=sorted(n for n,count in counts.items() if count>1)
    if repeated:
        raise SymbolParseError('Multi-unit physical pin numbers must be disjoint; repeated: '+', '.join(repeated))
    results=[]
    for unit in range(1,symbol.unit_count+1):
        if not symbol.pins_for(unit):
            raise SymbolParseError(f'Logical unit {unit} has no physical pins')
        results.append(converter(_view(library,symbol,unit),symbol.name,strict=False,**conversion_settings))
    first=results[0]
    report=deepcopy(first.report)
    shared_seen=set();diagnostics=[];polylines=[];placements=[]
    metadata={key:[] for key in ('curves','filled_graphics','graphic_texts')}
    electrical_counts=Counter()
    right=None;bounds=[];gap=round(unit_gap*1e6)
    body_corners=fill_strokes=0
    for unit,result in enumerate(results,1):
        part=deepcopy(result.document.components[0])
        dx=0 if right is None else native_integer(right+gap-part.bounds[0])
        placed_bounds=tuple(native_integer(v+(dx if i in (0,2) else 0)) for i,v in enumerate(part.bounds))
        bounds.append(placed_bounds);right=placed_bounds[2]
        start=len(polylines)
        for poly in part.polylines:
            for corner in poly.corners:corner.x=native_integer(corner.x+dx)
            _move_text(poly.pin,dx);_move_text(poly.description,dx)
        body_corners+=sum(len(p.corners) for p in part.polylines if p.layer==PART_OUTLINE)
        fill_strokes+=result.report['counts'].get('fill_polylines',0)
        if body_corners>MAX_BODY_CORNERS or fill_strokes>MAX_SYMBOL_FILL_STROKES:
            raise SymbolParseError('Compound body exceeds aggregate corner/fill limits')
        by_number={p.pin.value:(i+start,p) for i,p in enumerate(part.polylines) if p.pin}
        pins=[]
        for pin in symbol.pins_for(unit):
            i,poly=by_number[pin.number]
            body,external=poly.corners
            pins.append(dict(number=pin.number,name=pin.name,electrical_type=pin.electrical_type,
                source_connection_mm=pin.at[:2],target_polyline_index=i,
                target_body_nm=(body.x,body.y),target_connection_nm=(external.x,external.y)))
            electrical_counts[pin.electrical_type]+=1
        common_graphics=[dict(source_unit=0,style=block.style,source_id=block.source_id,count=len(block.graphics))
                         for block in symbol.units if block.number==0 and block.graphics]
        placements.append(dict(source_unit=unit,translation_nm=(dx,0),
            source_view_bounds_nm=result.document.components[0].bounds,target_bounds_nm=placed_bounds,
            target_polyline_indices=list(range(start,start+len(part.polylines))),
            common_graphics_copied=common_graphics,pins=pins))
        for key in metadata:
            metadata[key].extend(_placed_metadata(item,unit,dx,start,key) for item in result.report.get(key,[]))
        for d in result.report['diagnostics']:
            code=d['code']
            if code=='SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED':continue
            if code in SHARED_DIAGNOSTICS:
                if code in shared_seen:continue
                shared_seen.add(code);diagnostics.append(deepcopy(d));continue
            placed=deepcopy(d)
            context=placed['context']
            context.update(rendered_unit=unit,translation_nm=(dx,0))
            if 'unit' in context:context['unit']=0 if context['unit']==0 else unit
            if 'target_polyline_index' in context:context['target_polyline_index']+=start
            if 'target_polyline_indices' in context:
                context['target_polyline_indices']=[i+start for i in context['target_polyline_indices']]
            if 'center_mm' in context:
                context['source_center_mm']=context['center_mm']
                context['center_mm']=(context['center_mm'][0]+dx/1e6,context['center_mm'][1])
            diagnostics.append(placed)
        polylines.extend(part.polylines)
    diagnostics.append(dict(code='SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED',severity='loss',
        message='Source electrical types remain in JSON; numbered native endpoints do not transfer KiCad ERC rules.',
        context=dict(source_electrical_types=dict(electrical_counts))))
    diagnostics.append(dict(code='SYMBOL_UNITS_FLATTENED',severity='loss',
        message='Logical units are laid out side by side in one physical component. Independent unit placement, '
                'unit suffixes, per-unit reference/value labels and native hierarchical merge semantics are not transferred.',
        context=dict(source_units=symbol.unit_count,unit_gap_mm=unit_gap)))
    total_bounds=(min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds))
    first_part=deepcopy(first.document.components[0])
    component=ComponentRecord(len(counts),total_bounds,first_part.reference,first_part.value,first_part.footprint,polylines)
    document=CdsDocument(deepcopy(first.document.options),[component],first.document.page)
    cds=write_cds(document)
    if parse_cds(cds)!=document:
        raise SymbolParseError('Compound CDS record verification failed')
    report.update(source_symbol=asdict(symbol),target_component=asdict(component),diagnostics=diagnostics,
                  artifact_sha256=hashlib.sha256(cds.encode('cp1251')).hexdigest())
    report['target'].update(source_units_profile=PROFILE,
        coordinates='nanometres, Y up; each source unit translated by its declared integer-NM offset')
    report['conversion_settings']['unit_gap_mm']=unit_gap
    report['unit_layout']=dict(source_units=symbol.unit_count,native_components=1,
        independent_unit_placement_transferred=False,native_hierarchical_merge_generated=False,
        common_pin_policy='reject',unit_order='ascending source unit; X layout from validated geometry/anchor bounds',
        bounds_scope='geometry, source body-text anchors and stroke margin; glyph bounds unverified',units=placements)
    for key,entries in metadata.items():
        report.pop(key,None)
        if entries:report[key]=entries
    report['counts']=dict(components=1,pins=len(counts),source_units=symbol.unit_count,
        polylines=len(polylines),losses=sum(d['severity']=='loss' for d in diagnostics),
        assumptions=sum(d['severity']=='assumption' for d in diagnostics))
    if metadata['curves'] or metadata['filled_graphics'] or metadata['graphic_texts']:
        report['counts']['approximations']=sum(d['severity']=='approximation' for d in diagnostics)
    if metadata['filled_graphics']:
        report['counts'].update(filled_graphics=len(metadata['filled_graphics']),fill_polylines=fill_strokes)
        report['conversion_settings']['fill_tolerance_mm']=conversion_settings['fill_tolerance']
    if metadata['graphic_texts']:report['counts']['graphic_texts']=len(metadata['graphic_texts'])
    if metadata['curves'] or any(f['source_kind']=='circle' for f in metadata['filled_graphics']):
        report['conversion_settings']['curve_tolerance_mm']=conversion_settings['curve_tolerance']
    if metadata['curves']:report['target']['source_graphics_profile']='unfilled-curves-v1'
    if metadata['filled_graphics'] or metadata['graphic_texts']:
        report['target']['source_body_profile']='bounded-fills-body-text-v1'
    if any(kind!='passive' for kind in electrical_counts):
        # Passive records may come from units whose original reports have no
        # extended electrical section. Rebuild it from every physical pin.
        entries=[]
        for placed in placements:
            for pin in placed['pins']:
                entries.append(dict(source_pin_number=pin['number'],source_pin_name=pin['name'],
                    source_electrical_type=pin['electrical_type'],target_pin_number=pin['number'],
                    target_polyline_index=pin['target_polyline_index'],connection_point_nm=pin['target_connection_nm'],
                    rendered_unit=placed['source_unit']))
        report['target']['source_pin_profile']='visible-line-electrical-v1'
        report['pin_semantics']=dict(electrical_rules_transferred=False,
            native_representation='numbered layer-8 segment; body Node=0, external Node=1; optional layer-14 name',pins=entries)
    return cds,report,document
