"""Serialize normalized source information without claiming target compatibility."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from .model import Library


def inspection_report(library: Library, selected: list[str] | None = None) -> dict:
    names = selected if selected is not None else list(library.symbols)
    symbols = {}
    for requested in names:
        symbol = library.get_symbol(requested)
        if requested in symbols:
            continue
        data = asdict(symbol)
        data['source_ready'] = symbol.source_ready and not library.diagnostics
        data['pin_record_count'] = sum(len(unit.pins) for unit in symbol.units)
        data['physical_pin_numbers'] = sorted({pin.number for unit in symbol.units for pin in unit.pins})
        data['physical_pin_mapping_verified'] = False
        symbols[requested] = data
    diagnostics = [asdict(d) for d in library.diagnostics]
    occurrences = Counter(d['code'] for d in diagnostics)
    for data in symbols.values():
        occurrences.update(d['code'] for d in data['diagnostics'])
    return dict(schema_version=1, kind='kicad_symbol_inspection',
        source_format=library.source_format, source_version=library.version,
        units='mm', coordinates='KiCad symbol library, Y up; no target transform',
        target_format_verified=False, target_output_generated=False, gui_validated=False,
        symbols=symbols, aliases=library.aliases, diagnostics=diagnostics,
        raw_metadata=library.raw_metadata,
        summary=dict(library_symbol_count=len(library.symbols), selected_count=len(symbols),
                     pin_record_count=sum(d['pin_record_count'] for d in symbols.values()),
                     source_ready_count=sum(d['source_ready'] for d in symbols.values()),
                     diagnostic_occurrences=dict(sorted(occurrences.items()))))
