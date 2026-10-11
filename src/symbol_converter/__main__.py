"""Atomic JSON source inspection CLI, not a target symbol library generator."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from src.footprint_converter.io import atomic_write, validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from . import SymbolParseError, parse_library
from .reporting import inspection_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Inspect KiCad .kicad_sym/.lib as source JSON (no Schemator output)')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--symbol', action='append', help='Exact symbol or legacy alias; repeatable')
    options = parser.parse_args(argv)
    try:
        if options.input.suffix.lower() not in ('.lib', '.kicad_sym'):
            raise SymbolParseError('Input must be a KiCad .lib or .kicad_sym library')
        if options.output.suffix.lower() != '.json':
            raise SymbolParseError('Inspection output must have .json extension')
        validate_output_path(options.output, options.input, DEFAULT_STL_ROOT)
        if options.output.exists() and options.output.samefile(options.input):
            raise SymbolParseError('Output must differ from input (including hard links)')
        source = options.input.read_bytes()
        library = parse_library(source.decode('utf-8-sig'))
        report = inspection_report(library, options.symbol)
        report['source'] = dict(path=str(options.input.resolve()), sha256=hashlib.sha256(source).hexdigest())
        atomic_write(options.output, (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    except (OSError, ValueError) as error:
        print(f'Symbol inspection failed: {error}', file=sys.stderr)
        return 1
    summary = report['summary']
    print(f"Inspected {summary['selected_count']} symbols, {summary['pin_record_count']} pin records; "
          f"{summary['source_ready_count']} without source diagnostics. No target library generated.")
    return 2 if summary['diagnostic_occurrences'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
