"""Check exact source identifiers and pin/pad identities, without guessing."""
from __future__ import annotations

from collections import Counter
import hashlib
import re

from src.symbol_converter.model import Symbol
from src.footprint_converter.model import Footprint


class LinkError(ValueError):
    def __init__(self, status: str, code: str, message: str, **details):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details


def stable_name(label: str, prefix: str = 'fp') -> str:
    stem = re.sub(r'[^A-Za-z0-9_.-]', '_', label)[:60].strip('._-')
    return f'{prefix}_{stem}_{hashlib.sha256(label.encode()).hexdigest()[:16]}'


def footprint_identifier(value: str) -> tuple[str, str]:
    # The library namespace is required even when another library has the same
    # basename. Footprint filters are never an automatic selection mechanism.
    if not isinstance(value, str) or value.count(':') != 1:
        raise LinkError('unresolved', 'FOOTPRINT_IDENTIFIER_REQUIRED',
                        'Expected exact Library:Footprint identifier')
    library, name = value.split(':')
    if any(not s or s in ('.', '..') or s != s.strip() or
           any(c in s for c in '/\\*?[]"') or any(ord(c) < 32 for c in s)
           for s in (library, name)):
        raise LinkError('unresolved', 'FOOTPRINT_IDENTIFIER_INVALID', 'Unsafe/wildcard footprint identifier')
    return library, name


def pin_mapping(symbol: Symbol, footprint: Footprint) -> dict:
    """Identity mapping only; repeated pads and within-view pins stay ambiguous.

    Shared numbers across separate units are allowed by the source format.
    Alternate body styles must describe the same set of physical numbers.
    Native symbol generation still has its own smaller single-unit profile.
    """
    if not 1 <= symbol.unit_count <= 256:
        raise LinkError('failed', 'SYMBOL_UNIT_LIMIT', 'Mapping unit count outside profile limit')
    styles = (1, 2) if any(u.style == 2 for u in symbol.units) else (1,)
    duplicates, by_style, occurrences = set(), {}, {}
    for style in styles:
        numbers = set()
        for unit in range(1, symbol.unit_count + 1):
            pins = symbol.pins_for(unit, style)
            counts = Counter(p.number for p in pins)
            duplicates.update(n for n, count in counts.items() if count > 1)
            numbers.update(counts)
            for pin in pins:
                occurrences.setdefault(pin.number, []).append(dict(unit=unit, style=style, name=pin.name))
        by_style[style] = numbers
    electrical = [p for p in footprint.pads if p.kind != 'np_thru_hole' and
                  any(layer.endswith('.Cu') for layer in p.layers)]
    pads = Counter(p.name for p in electrical)
    numbers = by_style[1]
    conflicts = {d.pin_number for d in symbol.diagnostics
                 if d.code in ('SOURCE_PIN_DUPLICATE', 'SOURCE_PIN_CONFLICT')}
    duplicates.update(n for n in conflicts if n is not None)
    repeated_pads = sorted(n for n, count in pads.items() if count > 1)
    style_difference = any(view != numbers for view in by_style.values())
    missing, extra = sorted(numbers - pads.keys()), sorted(pads.keys() - numbers)
    ambiguous = bool(duplicates or repeated_pads or style_difference)
    verified = bool(numbers) and not ambiguous and not missing and not extra
    return dict(status='verified' if verified else 'ambiguous' if ambiguous else 'mismatch',
                verified=verified, source_numbers=sorted(numbers), pad_numbers=sorted(pads),
                missing_pads=missing, extra_pads=extra, duplicate_pin_numbers=sorted(duplicates),
                duplicate_pad_numbers=repeated_pads, alternate_style_mismatch=style_difference,
                mechanical_pads=len(footprint.pads)-len(electrical),
                pairs=[dict(pin=n, pad=n, occurrences=occurrences[n]) for n in sorted(numbers & pads.keys())],
                scope='Exact physical number identity; function, mechanical suitability and native netlist unverified')
