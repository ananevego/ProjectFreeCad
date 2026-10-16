"""Independent CDS pin readback against source pins and declared unit placement."""
import hashlib
import json

from .model import SymbolParseError
from .schemator_format import parse_cds


def verify_source_pins(library, name, cds, report):
    document = parse_cds(cds)
    if len(document.components) != 1:
        raise SymbolParseError('Batch CDS must contain one physical component')
    component = document.components[0]
    symbol = library.get_symbol(name)
    layout = report.get('unit_layout')
    if symbol.unit_count == 1:
        if layout:
            raise SymbolParseError('Unexpected compound placement for a single unit')
        groups = [(symbol.pins_for(), (0, 0))]
    else:
        if not layout or layout['source_units'] != symbol.unit_count:
            raise SymbolParseError('Missing source unit placement')
        common = any(block.number == 0 and block.pins for block in symbol.units)
        expected_units = list(range(1, symbol.unit_count + 1)) + ([0] if common else [])
        if [unit['source_unit'] for unit in layout['units']] != expected_units:
            raise SymbolParseError('Compound source view inventory mismatch')
        groups = []
        for unit in layout['units']:
            shift = unit['translation_nm']
            if len(shift) != 2 or any(type(n) is not int for n in shift) or shift[1] != 0:
                raise SymbolParseError('Invalid declared unit translation')
            pins = [pin for block in symbol.units if block.number == unit['source_unit'] for pin in block.pins]
            groups.append((pins, shift))
    expected = {}
    for pins, shift in groups:
        for pin in pins:
            if pin.number in expected:
                raise SymbolParseError('Repeated source physical number in batch readback')
            expected[pin.number] = (round(pin.at[0] * 1e6) + shift[0], round(pin.at[1] * 1e6) + shift[1])
    actual = {}
    for poly in component.polylines:
        if poly.pin:
            if poly.pin.value in actual or len(poly.corners) != 2 or [c.node for c in poly.corners] != [0, 1]:
                raise SymbolParseError('Invalid CDS numbered endpoint')
            actual[poly.pin.value] = (poly.corners[-1].x, poly.corners[-1].y)
    if actual != expected or component.pin_count != len(expected) or report['counts']['pins'] != len(expected):
        raise SymbolParseError('Source/CDS physical number or connection point mismatch')
    if component.footprint.value != 'PART':
        raise SymbolParseError('Unlinked symbol batch must retain the PART placeholder')
    canonical = json.dumps(sorted(expected.items()), separators=(',', ':')).encode()
    return dict(pins=len(expected), source_endpoint_sha256=hashlib.sha256(canonical).hexdigest(),
                source_pin_records_validated=True, physical_footprint_mapping_verified=False,
                native_netlist_verified=False)
