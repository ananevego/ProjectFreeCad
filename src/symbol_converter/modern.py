"""Normalize KiCad 6–9 S-expression symbol libraries; retain raw extensions."""
from __future__ import annotations

from copy import deepcopy
import re

from src.footprint_converter.parser import children, parse_sexpr
from src.footprint_converter.errors import ConversionError
from .common import ELECTRICAL, STYLES, integer, number, unique_name, validate_pins
from .model import Diagnostic, Graphic, Library, Pin, Property, Symbol, SymbolParseError, Unit

GRAPHICS = {'arc', 'circle', 'bezier', 'polyline', 'rectangle', 'text'}


def one(node: list, key: str, *, required: bool = False) -> list | None:
    found = children(node, key)
    if len(found) > 1 or required and not found:
        raise SymbolParseError(f'Missing/duplicate {key}')
    return found[0] if found else None


def atoms(node: list, count: int, context: str) -> None:
    if len(node) < count or any(not isinstance(v, str) for v in node[:count]):
        raise SymbolParseError(f'Malformed {context}')


def scalar(node: list, key: str, default=None, *, required: bool = False):
    item = one(node, key, required=required)
    if item is None:
        return default
    if len(item) != 2 or not isinstance(item[1], str):
        raise SymbolParseError(f'Malformed {key}')
    return item[1]


def flag(node: list, key: str, default=False) -> bool:
    found = one(node, key)
    bare = sum(item == key for item in node if isinstance(item, str))
    if bare > 1 or bare and found is not None:
        raise SymbolParseError(f'Duplicate {key}')
    if bare:
        return True
    if found is None:
        return default
    if len(found) == 1:
        return True
    if len(found) != 2 or found[1] not in ('yes', 'no'):
        raise SymbolParseError(f'Malformed {key}')
    return found[1] == 'yes'


def coords(node: list, key: str, count: int = 2) -> tuple:
    item = one(node, key, required=True)
    if len(item) != count + 1:
        raise SymbolParseError(f'Malformed {key}')
    return tuple(number(v, key) for v in item[1:])


def size(node: list) -> tuple[float, float]:
    effects = one(node, 'effects', required=True)
    font = one(effects, 'font', required=True)
    values = coords(font, 'size')
    if min(values) <= 0:
        raise SymbolParseError('Text size must be positive')
    return values


def extras(node: list, allowed: set, symbol: Symbol, context: str,
           *, positional: int = 1) -> None:
    for item in node[positional:]:
        key = item[0] if isinstance(item, list) and item else item
        if not isinstance(key, str) or key not in allowed:
            symbol.diagnostics.append(Diagnostic('SOURCE_EXTENSION_UNNORMALIZED',
                f'{context}: extension {key!r} retained in raw records'))


def pin(node: list, symbol: Symbol) -> Pin:
    atoms(node, 3, 'pin')
    if node[1] not in ELECTRICAL or node[2] not in STYLES:
        raise SymbolParseError(f'Unknown pin type/style: {node[1:3]}')
    at = coords(node, 'at', 3)
    if at[2] not in (0, 90, 180, 270):
        raise SymbolParseError('Pin angle must be 0/90/180/270 degrees')
    length = number(scalar(node, 'length', required=True), 'pin length', nonnegative=True)
    name = one(node, 'name', required=True)
    num = one(node, 'number', required=True)
    atoms(name, 2, 'pin name')
    atoms(num, 2, 'pin number')
    if not num[1]:
        raise SymbolParseError('Empty pin number')
    alternates = []
    for item in children(node, 'alternate'):
        atoms(item, 4, 'alternate pin')
        if len(item) != 4 or item[2] not in ELECTRICAL or item[3] not in STYLES:
            raise SymbolParseError('Malformed alternate pin function')
        alternates.append(dict(name=item[1], electrical_type=item[2], graphic_style=item[3]))
    extras(node, {'at', 'length', 'name', 'number', 'hide', 'alternate'}, symbol,
           f'pin {num[1]}', positional=3)
    return Pin(num[1], name[1], at, length, node[1], node[2], flag(node, 'hide'),
               size(name), size(num), alternates, deepcopy(node))


def graphic(node: list, symbol: Symbol) -> Graphic:
    kind = node[0]
    data = {}
    if kind == 'arc':
        data = {key: coords(node, key) for key in ('start', 'mid', 'end')}
    elif kind == 'rectangle':
        data = {key: coords(node, key) for key in ('start', 'end')}
    elif kind == 'circle':
        radius = number(scalar(node, 'radius', required=True), 'circle radius', nonnegative=True)
        if radius == 0:
            raise SymbolParseError('Zero circle radius')
        data = dict(center=coords(node, 'center'), radius=radius)
    elif kind in ('polyline', 'bezier'):
        pts = one(node, 'pts', required=True)
        points = []
        for item in pts[1:]:
            if not isinstance(item, list) or len(item) != 3 or item[0] != 'xy':
                raise SymbolParseError('Malformed graphic point list')
            points.append(tuple(number(v, 'graphic point') for v in item[1:]))
        if len(points) < 2 or kind == 'bezier' and len(points) != 4:
            raise SymbolParseError('Invalid graphic point count')
        data = dict(points=points)
    elif kind == 'text':
        atoms(node, 2, 'graphic text')
        data = dict(text=node[1], at=coords(node, 'at', 3), size=size(node))
    stroke = one(node, 'stroke', required=kind != 'text')
    width = number(scalar(stroke, 'width', required=True), 'stroke width', nonnegative=True) if stroke else 0
    fill_node = one(node, 'fill', required=kind != 'text')
    fill = scalar(fill_node, 'type', required=True) if fill_node else 'none'
    if fill not in ('none', 'outline', 'background'):
        raise SymbolParseError(f'Invalid graphic fill: {fill}')
    keys = {'stroke', 'fill'} | ({'start', 'mid', 'end'} if kind == 'arc' else
           {'start', 'end'} if kind == 'rectangle' else {'center', 'radius'} if kind == 'circle'
           else {'pts'} if kind in ('polyline', 'bezier') else {'at', 'effects'})
    extras(node, keys, symbol, kind, positional=2 if kind == 'text' else 1)
    return Graphic(kind, data, width, fill, deepcopy(node))


def property_record(node: list) -> Property:
    atoms(node, 3, 'property')
    # Effects are retained, including justification, font, bold and italic.
    size(node)
    return Property(node[1], node[2], coords(node, 'at', 3),
                    flag(node, 'hide') or flag(one(node, 'effects'), 'hide'), deepcopy(node))


def unit_record(node: list, symbol: Symbol, *, direct=False) -> Unit:
    if direct:
        block = Unit(0, 0, symbol.name + '_direct')
    else:
        atoms(node, 2, 'symbol unit')
        match = re.fullmatch(re.escape(symbol.name) + r'_(\d+)_(\d+)', node[1])
        if not match:
            raise SymbolParseError(f'Invalid unit identifier: {node[1]!r}')
        unit, style = map(int, match.groups())
        if unit > 1024 or style not in (0, 1, 2):
            raise SymbolParseError(f'Invalid unit/body style: {node[1]}')
        block = Unit(unit, style, node[1], scalar(node, 'unit_name'))
    for item in node[1 if direct else 2:]:
        if not isinstance(item, list) or not item:
            raise SymbolParseError('Malformed symbol unit content')
        if item[0] == 'pin':
            block.pins.append(pin(item, symbol))
        elif item[0] in GRAPHICS:
            block.graphics.append(graphic(item, symbol))
        elif item[0] != 'unit_name':
            symbol.diagnostics.append(Diagnostic('SOURCE_EXTENSION_UNNORMALIZED',
                f'Unit {block.source_id}: {item[0]!r} retained in raw records'))
    return block


def parse_modern(text: str) -> Library:
    try:
        root = parse_sexpr(text)
    except ConversionError as error:
        raise SymbolParseError(str(error)) from error
    if not root or root[0] != 'kicad_symbol_lib':
        raise SymbolParseError('Expected kicad_symbol_lib, not a schematic or footprint')
    version = scalar(root, 'version', required=True)
    numeric_version = integer(version, 'library version', minimum=1)
    definitions = {}
    for node in children(root, 'symbol'):
        atoms(node, 2, 'symbol')
        unique_name(definitions, node[1], 'symbol name')
        definitions[node[1]] = node
    library = Library('kicad_sym', version, {}, raw_metadata=deepcopy(
        [n for n in root[1:] if not isinstance(n, list) or not n or n[0] != 'symbol']))
    if numeric_version > 20241209:
        library.diagnostics.append(Diagnostic('SOURCE_VERSION_UNVERIFIED',
            f'Library version {version} is newer than the verified KiCad 9 profile'))
    for item in root[1:]:
        if not isinstance(item, list) or not item or item[0] not in {
                'symbol', 'version', 'generator', 'generator_version'}:
            library.diagnostics.append(Diagnostic('SOURCE_EXTENSION_UNNORMALIZED',
                'Library metadata extension retained in raw_metadata'))
    resolving = set()

    def resolve(name: str) -> Symbol:
        if name in library.symbols:
            return library.symbols[name]
        if name in resolving:
            raise SymbolParseError(f'Cyclic symbol inheritance at {name}')
        if name not in definitions:
            raise SymbolParseError(f'Missing inherited symbol {name}')
        if len(resolving) >= 100:
            raise SymbolParseError('Symbol inheritance depth exceeds 100')
        resolving.add(name)
        node = definitions[name]
        base = scalar(node, 'extends')
        if base == '':
            raise SymbolParseError('Empty inherited symbol name')
        if base:
            if children(node, 'symbol') or children(node, 'pin') or any(children(node, k) for k in GRAPHICS):
                raise SymbolParseError(f'Extended symbol {name} cannot redefine geometry/pins')
            symbol = deepcopy(resolve(base))
            symbol.name, symbol.extends = name, base
            symbol.inheritance_chain = [base] + symbol.inheritance_chain
        else:
            symbol = Symbol(name)
        symbol.raw = deepcopy(node)
        seen_properties = {}
        for item in children(node, 'property'):
            prop = property_record(item)
            unique_name(seen_properties, prop.name, 'property name')
            seen_properties[prop.name] = prop
            symbol.properties[prop.name] = prop
        if not base:
            missing = {'Reference', 'Value', 'Footprint', 'Datasheet'} - symbol.properties.keys()
            if missing:
                raise SymbolParseError(f'{name}: missing mandatory properties {sorted(missing)}')
            seen_units = {}
            for item in children(node, 'symbol'):
                block = unit_record(item, symbol)
                unique_name(seen_units, block.source_id, 'unit identifier')
                seen_units[block.source_id] = block
                symbol.units.append(block)
            direct = [item for item in node[2:] if isinstance(item, list) and item and item[0] in GRAPHICS | {'pin'}]
            if direct:
                symbol.units.append(unit_record(['symbol'] + direct, symbol, direct=True))
            symbol.unit_count = max([1] + [b.number for b in symbol.units])
        for key in ('in_bom', 'on_board'):
            value = scalar(node, key)
            if value is not None:
                if value not in ('yes', 'no'):
                    raise SymbolParseError(f'Malformed {key}')
                setattr(symbol, key, value == 'yes')
        names = one(node, 'pin_names')
        if names is not None:
            symbol.pin_names_hidden = flag(names, 'hide')
            symbol.pin_name_offset = number(scalar(names, 'offset', '0.508'), 'pin name offset', nonnegative=True)
        nums = one(node, 'pin_numbers')
        if nums is not None:
            symbol.pin_numbers_hidden = flag(nums, 'hide')
        symbol.power = flag(node, 'power', symbol.power)
        extras(node, {'extends', 'property', 'symbol', 'pin', 'pin_names', 'pin_numbers',
                     'in_bom', 'on_board', 'power', 'exclude_from_sim', 'embedded_fonts'} | GRAPHICS,
               symbol, name, positional=2)
        if not base:
            validate_pins(symbol)
        resolving.remove(name)
        library.symbols[name] = symbol
        return symbol

    for name in definitions:
        resolve(name)
    # Restore source order even when a derived symbol precedes its parent.
    library.symbols = {name: library.symbols[name] for name in definitions}
    return library
