"""Read legacy Eeschema .lib 2.3/2.4 (mils, positive Y upward)."""
from __future__ import annotations

import re
import shlex

from .common import integer, number, unique_name, validate_pins
from .model import Diagnostic, Graphic, Library, Pin, Property, Symbol, SymbolParseError, Unit

MIL = 0.0254
ELECTRICAL = dict(I='input', O='output', B='bidirectional', T='tri_state',
                  P='passive', U='unspecified', W='power_in', w='power_out',
                  C='open_collector', E='open_emitter', N='no_connect')
SHAPES = {'': 'line', 'I': 'inverted', 'C': 'clock', 'CI': 'inverted_clock',
          'IC': 'inverted_clock', 'L': 'input_low', 'CL': 'clock_low',
          'V': 'output_low', 'F': 'edge_clock_high', 'X': 'non_logic'}


def mm(value: str, *, nonnegative=False) -> float:
    return number(value, 'legacy mil value', nonnegative=nonnegative) * MIL


def count(tokens: list, valid: tuple, context: str) -> None:
    if len(tokens) not in valid:
        raise SymbolParseError(f'Malformed legacy {context}: {len(tokens)} fields')


def fill(value: str) -> str:
    try:
        return {'N': 'none', 'F': 'outline', 'f': 'background'}[value]
    except KeyError as error:
        raise SymbolParseError(f'Invalid legacy fill {value}') from error


def block_for(symbol: Symbol, unit: str, style: str) -> Unit:
    u, s = integer(unit, 'unit'), integer(style, 'body style')
    if u > symbol.unit_count or s not in (0, 1, 2):
        raise SymbolParseError('Legacy unit/body style outside DEF range')
    for block in symbol.units:
        if (block.number, block.style) == (u, s):
            return block
    block = Unit(u, s, f'{symbol.name}_{u}_{s}')
    symbol.units.append(block)
    return block


def parse_pin(t: list[str], symbol: Symbol) -> None:
    count(t, (12, 13), 'pin')
    if t[6] not in {'R', 'U', 'L', 'D'} or t[11] not in ELECTRICAL or not t[2]:
        raise SymbolParseError('Unknown legacy pin orientation/electrical type/number')
    shape = t[12] if len(t) == 13 else ''
    hidden = 'N' in shape
    shape = ''.join(sorted(set(shape.replace('N', '').replace('~', ''))))
    if shape not in SHAPES:
        raise SymbolParseError(f'Unknown legacy pin shape {shape}')
    at = (mm(t[3]), mm(t[4]), {'R': 0, 'U': 90, 'L': 180, 'D': 270}[t[6]])
    numsize, namesize = mm(t[7], nonnegative=True), mm(t[8], nonnegative=True)
    block_for(symbol, t[9], t[10]).pins.append(Pin(
        t[2], t[1], at, mm(t[5], nonnegative=True), ELECTRICAL[t[11]], SHAPES[shape],
        hidden, (namesize, namesize), (numsize, numsize), raw=t))


def parse_graphic(t: list[str], symbol: Symbol, raw_line: str = '') -> None:
    kind = t[0]
    if kind == 'T':
        count(t,(9,11,13),'graphic text')
        if any(not re.fullmatch(r'-?\d+',value) for value in t[1:8]):
            raise SymbolParseError('Legacy graphic text requires integer fields')
        height=mm(t[4],nonnegative=True)
        if height<=0 or t[5] not in ('0','1'):
            raise SymbolParseError('Invalid legacy graphic text size/visibility')
        quoted=raw_line.split(None,8)[-1].startswith('"')
        text=t[8] if quoted else t[8].replace('~',' ')
        text=text.replace("''",'"')
        if len(t)>=11 and (t[9] not in ('Normal','Italic') or not re.fullmatch(r'\d+',t[10])):
            raise SymbolParseError('Invalid legacy graphic text style')
        if len(t)==13 and (t[11] not in ('L','C','R') or t[12] not in ('T','C','B')):
            raise SymbolParseError('Invalid legacy graphic text justification')
        data=dict(text=text,at=(mm(t[2]),mm(t[3]),int(t[1])/10),size=(height,height),
                  hidden=t[5]=='1',italic=len(t)>=11 and t[9]=='Italic',
                  bold=len(t)>=11 and int(t[10])>0,
                  horizontal_justify=t[11] if len(t)==13 else 'C',
                  vertical_justify=t[12] if len(t)==13 else 'C')
        block_for(symbol,t[6],t[7]).graphics.append(Graphic('text',data,0,'none',t))
        return
    if kind == 'S':
        count(t, (9,), 'rectangle')
        unit, style, width = t[5:8]
        data = dict(start=(mm(t[1]), mm(t[2])), end=(mm(t[3]), mm(t[4])))
        graphic_kind = 'rectangle'
    elif kind == 'C':
        count(t, (8,), 'circle')
        unit, style, width = t[4:7]
        radius = mm(t[3], nonnegative=True)
        if radius == 0:
            raise SymbolParseError('Zero legacy circle radius')
        data = dict(center=(mm(t[1]), mm(t[2])), radius=radius)
        graphic_kind = 'circle'
    elif kind == 'P':
        if len(t) < 6:
            raise SymbolParseError('Malformed legacy polygon')
        n = integer(t[1], 'point count', minimum=2)
        count(t, (6 + 2 * n,), 'polygon')
        unit, style, width = t[2:5]
        data = dict(points=[(mm(t[i]), mm(t[i+1])) for i in range(5, 5+2*n, 2)])
        graphic_kind = 'polyline'
    elif kind == 'A':
        count(t, (10, 14), 'arc')
        unit, style, width = t[6:9]
        radius = mm(t[3], nonnegative=True)
        if radius == 0:
            raise SymbolParseError('Zero legacy arc radius')
        # Retain BOTH angle and explicit endpoint definitions: historical
        # rounded endpoints need not lie exactly on the given circle.
        data = dict(center=(mm(t[1]), mm(t[2])), radius=radius,
                    start_angle=number(t[4], 'arc angle') / 10,
                    end_angle=number(t[5], 'arc angle') / 10)
        if len(t) == 14:
            data.update(start=(mm(t[10]), mm(t[11])), end=(mm(t[12]), mm(t[13])))
        block_for(symbol, unit, style).graphics.append(
            Graphic('legacy_arc', data, mm(width, nonnegative=True), fill(t[9]), t))
        return
    else:
        symbol.diagnostics.append(Diagnostic('SOURCE_EXTENSION_UNNORMALIZED',
            f'Legacy graphic {kind!r} retained in raw symbol records'))
        return
    block_for(symbol, unit, style).graphics.append(
        Graphic(graphic_kind, data, mm(width, nonnegative=True), fill(t[-1]), t))


def parse_field(t: list[str], symbol: Symbol) -> None:
    count(t, (9, 10), 'field')
    index = integer(t[0][1:], 'field index')
    name = ('Reference', 'Value', 'Footprint', 'Datasheet')[index] if index < 4 else (
        t[9] if len(t) == 10 else f'Field{index}')
    unique_name(symbol.properties, name, 'field name')
    if t[5] not in ('H', 'V') or t[6] not in ('I', 'V') or t[7] not in ('L', 'C', 'R'):
        raise SymbolParseError('Invalid legacy field orientation/visibility/justification')
    if not re.fullmatch('[BTC][NI][NB]', t[8]):
        raise SymbolParseError('Invalid legacy field style')
    mm(t[4], nonnegative=True)
    symbol.properties[name] = Property(name, t[1], (mm(t[2]), mm(t[3]),
        0 if t[5] == 'H' else 90), t[6] == 'I', t)


def parse_legacy(text: str) -> Library:
    lines = text.splitlines()
    if not lines or not re.fullmatch(r'EESchema-LIBRARY Version 2\.[34](?:\s+.*)?', lines[0].strip()):
        raise SymbolParseError('Expected EESchema-LIBRARY Version 2.3/2.4')
    library = Library('legacy_lib', lines[0].split()[2], {}, raw_metadata=[lines[0]])
    symbol = None
    drawing = False
    drawn = False
    filters = False
    field_indices = set()
    for line_number, line in enumerate(lines[1:], 2):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            t = shlex.split(line, comments=False, posix=True)
            if not t:
                continue
            kind = t[0]
            if symbol is None:
                if kind != 'DEF':
                    raise SymbolParseError('Expected DEF')
                count(t, (10,), 'DEF')
                name = t[1][1:] if t[1].startswith('~') else t[1]
                unique_name(library.symbols, name, 'symbol name')
                units = integer(t[7], 'unit count', minimum=1)
                if units > 1024 or t[5] not in ('Y', 'N') or t[6] not in ('Y', 'N') or t[8] not in ('F', 'L') or t[9] not in ('N', 'P'):
                    raise SymbolParseError('Invalid legacy DEF flags/unit count')
                symbol = Symbol(name, unit_count=units, pin_name_offset=mm(t[4], nonnegative=True),
                    pin_numbers_hidden=t[5] == 'N', pin_names_hidden=t[6] == 'N',
                    in_bom=not t[2].startswith('#'), on_board=not t[2].startswith('#'), power=t[9] == 'P', raw=[line])
                drawn = False
                field_indices = set()
                continue
            symbol.raw.append(line)
            if filters:
                if kind == '$ENDFPLIST':
                    filters = False
                else:
                    # Values/patterns are source strings, never resolved paths.
                    previous = symbol.properties.get('ki_fp_filters')
                    value = (previous.value + ' ' if previous else '') + line
                    symbol.properties['ki_fp_filters'] = Property('ki_fp_filters', value, (0,0,0), True,
                        (previous.raw if previous else []) + [line])
                continue
            if drawing:
                if kind == 'ENDDRAW':
                    count(t, (1,), kind)
                    drawing = False
                elif kind == 'X':
                    parse_pin(t, symbol)
                elif kind in ('S', 'C', 'P', 'A', 'T', 'B'):
                    parse_graphic(t, symbol, line)
                else:
                    raise SymbolParseError(f'Unexpected record in DRAW: {kind}')
            elif re.fullmatch(r'F\d+', kind):
                if integer(kind[1:], 'field index') in field_indices:
                    raise SymbolParseError('Duplicate legacy field index')
                parse_field(t, symbol)
                field_indices.add(integer(kind[1:], 'field index'))
            elif kind == 'ALIAS':
                symbol.aliases.extend(t[1:])
            elif kind == '$FPLIST':
                count(t, (1,), kind)
                filters = True
            elif kind == 'DRAW':
                count(t, (1,), kind)
                if drawn:
                    raise SymbolParseError('Duplicate DRAW')
                drawing = drawn = True
            elif kind == 'ENDDEF':
                count(t, (1,), kind)
                if not drawn or not {'Reference', 'Value'} <= symbol.properties.keys():
                    raise SymbolParseError('Incomplete legacy symbol definition')
                validate_pins(symbol)
                library.symbols[symbol.name] = symbol
                symbol = None
            else:
                raise SymbolParseError(f'Unexpected legacy record: {kind}')
        except (ValueError, IndexError) as error:
            raise SymbolParseError(f'Legacy line {line_number}: {error}') from error
    if symbol is not None or drawing or filters:
        raise SymbolParseError('Unclosed legacy symbol/DRAW/FPLIST')
    for symbol in library.symbols.values():
        for alias in symbol.aliases:
            unique_name(library.aliases, alias, 'alias')
            if alias in library.symbols:
                raise SymbolParseError(f'Alias conflicts with symbol: {alias}')
            library.aliases[alias] = symbol.name
    return library
