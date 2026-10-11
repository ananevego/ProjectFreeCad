"""Emit only the verified CDS straight component subset."""
from __future__ import annotations

from .schemator_format import CdsDocument, TextRecord, safe_string, validate_component


def _text(key: str, text: TextRecord) -> str:
    values=(text.x,text.y,text.layer,text.angle,text.size,text.width,
            text.merge,text.submerge,text.font,text.options)
    return f'{key}: "{safe_string(text.value)}" ' + ' '.join(map(str,values))


def write_cds(document: CdsDocument) -> str:
    lines=['[options]','']
    for key,value in document.options.items():
        lines.append(f'{key}: "{safe_string(value)}"' if key=='project_name' else f'{key}: {value}')
    lines+=['','[graphics]','',f'rename_page: "{safe_string(document.page)}"','']
    for component in document.components:
        validate_component(component)
        lines.extend([f'n_pins: {component.pin_count}',
            'rectangle: '+' '.join(map(str,component.bounds)),
            _text('ref_des',component.reference),_text('footprint_name',component.footprint),
            _text('part_value',component.value)])
        for poly in component.polylines:
            key='outline' if poly.closed else 'polyline'
            values=(len(poly.corners),poly.hatch,poly.layer,poly.width,poly.merge,
                    poly.submerge,poly.source,poly.source_invert)
            lines.append(key+': '+' '.join(map(str,values)))
            for i,corner in enumerate(poly.corners,1):
                lines.append(f'  corner: {i} {corner.x} {corner.y} {corner.style} {corner.node}')
            if poly.pin:
                lines.append(_text('pin_name',poly.pin))
            if poly.description:
                lines.append(_text('description',poly.description))
            lines.append('')
        lines.extend(['part_end',''])
    lines.extend(['[end]',''])
    return '\r\n'.join(lines)
