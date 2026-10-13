"""Read back the emitted FPL link fields independently of the source parser."""
from __future__ import annotations

import re

from src.symbol_converter.schemator_format import _tokens


def read_fpl_links(text: str) -> dict:
    names, declared, pads, imports = [], [], [], []
    current = None
    for line in text.splitlines():
        key, colon, body = line.strip().partition(':')
        if not colon:
            continue
        if key not in {'name', 'n_pins', 'pin', 'top_pad', 'bottom_pad', 'inner_pad', 'openscad_code'}:
            continue
        values = _tokens(body)
        if key == 'name':
            if not line.startswith('name:') or len(values) != 1:
                raise ValueError('Invalid indexed FPL name')
            names.extend(values)
        elif key == 'n_pins':
            if len(values) != 1:
                raise ValueError('Invalid FPL n_pins')
            declared.append(int(values[0]))
        elif key == 'pin':
            if len(values) != 6:
                raise ValueError('Invalid FPL pin record')
            list(map(int, values[1:5]))
            current = dict(number=values[0], copper=False, sides=set())
            pads.append(current)
        elif key.endswith('_pad'):
            if current is None or key in current['sides'] or len(values) != (6 if key == 'inner_pad' else 5):
                raise ValueError('Invalid/duplicate FPL pad record')
            integers = list(map(int, values))
            current['copper'] |= integers[0] != 0
            current['sides'].add(key)
        else:
            if len(values) != 1:
                raise ValueError('Invalid FPL OpenSCAD record')
            code = values[0].strip()
            if 'import(' in code:
                match = re.fullmatch(r'import\(`([A-Za-z0-9_.-]+\.stl)`\);', code)
                if match is None:
                    raise ValueError('Nonportable FPL model import')
                imports.append(match[1])
    if len(names) != 1 or declared != [len(pads)] or any(
            not {'top_pad', 'bottom_pad'} <= p['sides'] for p in pads):
        raise ValueError('Incomplete FPL link records')
    numbers = [p['number'] for p in pads if p['copper']]
    if len(numbers) != len(set(numbers)):
        raise ValueError('Duplicate electrical FPL pin number')
    return dict(name=names[0], numbers=sorted(numbers), imports=imports,
                mechanical_pads=len(pads)-len(numbers))
