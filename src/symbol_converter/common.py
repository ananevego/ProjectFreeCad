"""Validation shared by source symbol readers."""
from __future__ import annotations

from collections import defaultdict
import math

from .model import Diagnostic, Symbol, SymbolParseError

ELECTRICAL = {'input', 'output', 'bidirectional', 'tri_state', 'passive',
              'free', 'unspecified', 'power_in', 'power_out', 'open_collector',
              'open_emitter', 'no_connect'}
STYLES = {'line', 'inverted', 'clock', 'inverted_clock', 'input_low',
          'clock_low', 'output_low', 'edge_clock_high', 'non_logic'}


def number(value, context: str, *, nonnegative: bool = False) -> float:
    try:
        result = float(value) if isinstance(value, str) else float('nan')
    except ValueError as error:
        raise SymbolParseError(f'Invalid {context}: {value!r}') from error
    if not math.isfinite(result) or nonnegative and result < 0:
        raise SymbolParseError(f'Invalid {context}: {value!r}')
    return result


def integer(value, context: str, *, minimum: int = 0) -> int:
    try:
        result = int(value) if isinstance(value, str) else -1
    except ValueError as error:
        raise SymbolParseError(f'Invalid {context}: {value!r}') from error
    if result < minimum:
        raise SymbolParseError(f'Invalid {context}: {value!r}')
    return result


def validate_pins(symbol: Symbol) -> None:
    """Check each rendered unit/style, avoiding false conflicts across units.

    Pins may legitimately share a physical number across units and body styles.
    Two records for a number in one rendered view are retained and flagged;
    even intentional stacking requires an explicit target mapping later.
    """
    styles = {1} | {b.style for b in symbol.units if b.style > 0}
    for unit in range(1, symbol.unit_count + 1):
        for style in sorted(styles):
            grouped = defaultdict(list)
            for pin in symbol.pins_for(unit, style):
                grouped[pin.number].append(pin)
            for key, pins in grouped.items():
                if len(pins) < 2:
                    continue
                signatures = {(p.name, p.at, p.length, p.electrical_type,
                               p.graphic_style, p.hidden, p.name_size,
                               p.number_size, repr(p.alternates), repr(p.raw)) for p in pins}
                exact = len(signatures) == 1
                symbol.diagnostics.append(Diagnostic(
                    'SOURCE_PIN_DUPLICATE' if exact else 'SOURCE_PIN_CONFLICT',
                    f'{len(pins)} records for pin {key!r} in unit {unit}, style {style}; '
                    'records retained, target pin mapping requires review',
                    'error', unit, style, key))


def unique_name(table: dict, name: str, context: str) -> None:
    if not name or name in table:
        raise SymbolParseError(f'Empty/duplicate {context}: {name!r}')
