"""CLI for the CDS straight component MVP; source inspection CLI is unchanged."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from src.footprint_converter.io import atomic_write, validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from . import parse_library
from .model import SymbolParseError
from .target import convert_symbol, LossySymbolConversionError


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description='Generate one Schemator CDS component in the verified straight profile')
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--footprint-name',help='Explicit native footprint name; otherwise PART placeholder')
    parser.add_argument('--reference',help='Numbered reference; default source prefix + 1')
    parser.add_argument('--default-line-width',type=float,default=.254)
    parser.add_argument('--pin-width',type=float,default=.254)
    parser.add_argument('--curve-tolerance',type=float,default=.01,help='Maximum resolved curve centerline error in mm, default 0.01')
    parser.add_argument('--fill-tolerance',type=float,default=.01,help='Maximum ideal fill expansion beyond source fill/stroke in mm, default 0.01')
    parser.add_argument('--unit-gap',type=float,default=2.54,help='Gap between compound unit bounds in mm, default 2.54')
    parser.add_argument('--strict',action='store_true')
    args=parser.parse_args(argv)
    report_path=args.report or args.output.with_suffix('.report.json')
    exit_code=0
    try:
        if args.input.suffix.lower() not in ('.lib','.kicad_sym') or args.output.suffix!='.cds' or report_path.suffix.lower()!='.json':
            raise SymbolParseError('Expected KiCad .lib/.kicad_sym input, lowercase .cds output and .json report')
        for path in (args.output,report_path):
            validate_output_path(path,args.input,DEFAULT_STL_ROOT)
            if path.exists() and path.samefile(args.input):
                raise SymbolParseError('Output cannot be a hard link to source')
        if args.output.resolve()==report_path.resolve() or (
                args.output.exists() and report_path.exists() and args.output.samefile(report_path)):
            raise SymbolParseError('CDS and JSON report paths must differ')
        source=args.input.read_bytes()
        library=parse_library(source.decode('utf-8-sig'))
        result=None
        try:
            result=convert_symbol(library,args.symbol,footprint_name=args.footprint_name,
                reference=args.reference,project_name=args.output.name,
                default_line_width=args.default_line_width,pin_width=args.pin_width,
                curve_tolerance=args.curve_tolerance,fill_tolerance=args.fill_tolerance,unit_gap=args.unit_gap,strict=args.strict)
            report=result.report
        except LossySymbolConversionError as error:
            report=error.report
            exit_code=2
        report['source']=dict(path=str(args.input.resolve()),sha256=hashlib.sha256(source).hexdigest())
        report['output']=str(args.output.resolve())
        if result is not None:
            atomic_write(args.output,result.cds.encode('cp1251'))
        atomic_write(report_path,(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
    except (OSError,ValueError) as error:
        print(f'Symbol conversion failed: {error}',file=sys.stderr)
        return 1
    print(f"{report['status']}: {args.symbol}, {report['counts']['pins']} pins, "
          f"{report['counts']['losses']} losses; GUI import unverified. Report: {report_path}")
    return exit_code


if __name__=='__main__':
    raise SystemExit(main())
