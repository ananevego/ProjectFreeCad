"""Single-footprint command line entry point."""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

from .errors import ConversionError, LossyConversionError
from .model import ApertureSettings, ModelTransform, ONE, ZERO
from .format_rules import quote
from .parser import parse_sexpr
from .model_matching import DEFAULT_STL_ROOT
from .pipeline import convert_detailed
from .io import atomic_write, validate_output_path


def main() -> int:
    parser = argparse.ArgumentParser(description='Convert one KiCad footprint to FreePCB2 2.428 .fpl.')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--name')
    parser.add_argument('--stl-root', type=Path, default=DEFAULT_STL_ROOT)
    parser.add_argument('--encoding', default='cp1251', help='Target library encoding (default: cp1251)')
    parser.add_argument('--model-translation', type=float, nargs=3)
    parser.add_argument('--model-rotation', type=float, nargs=3)
    parser.add_argument('--model-scale', type=float, nargs=3)
    parser.add_argument('--curve-tolerance', type=float, default=0.01, metavar='MM')
    parser.add_argument('--fill-tolerance', type=float, default=0.01, metavar='MM',
                        help='Maximum encoded expansion for filled graphics (default: 0.01 mm)')
    parser.add_argument('--text-variable', action='append', default=[], metavar='NAME=VALUE',
                        help='Explicitly freeze a KiCad text variable to a literal value')
    parser.add_argument('--report', type=Path, help='Optional JSON conversion report (UTF-8)')
    parser.add_argument('--strict', action='store_true', help='Reject known data loss before writing .fpl')
    parser.add_argument('--default-mask-margin', type=float, metavar='MM')
    parser.add_argument('--default-paste-margin', type=float, metavar='MM')
    parser.add_argument('--default-paste-ratio', type=float, metavar='RATIO',
                        help='Dimensionless per-side ratio, e.g. -0.05')
    args = parser.parse_args()
    safe_report = False
    try:
        validate_output_path(args.output, args.input, args.stl_root)
        if args.report:
            validate_output_path(args.report, args.input, args.stl_root)
            if args.report.resolve() == args.output.resolve():
                raise ConversionError('Report must differ from .fpl output')
            safe_report = True
        variables = {}
        for binding in args.text_variable:
            key, sep, value = binding.partition('=')
            if not sep or not key or key in variables:
                raise ConversionError('Text binding must be unique NAME=VALUE')
            quote(value)
            variables[key] = value
        transform = None
        if any(v is not None for v in (args.model_translation, args.model_rotation, args.model_scale)):
            transform = ModelTransform(tuple(args.model_translation or ZERO),
                                       tuple(args.model_rotation or ZERO), tuple(args.model_scale or ONE))
        result = convert_detailed(parse_sexpr(args.input.read_text(encoding='utf-8')), args.name,
                                  stl_root=args.stl_root, model_transform=transform,
                                  text_variables=variables, curve_tolerance=args.curve_tolerance,
                                  fill_tolerance=args.fill_tolerance,
                                  strict=args.strict, aperture_defaults=ApertureSettings(
                                      args.default_mask_margin, args.default_paste_margin, args.default_paste_ratio))
        data = result.fpl.encode(args.encoding)
        if args.report:
            report = dict(result.report, input_file=str(args.input.resolve()),
                          output_file=str(args.output.resolve()), output_encoding=args.encoding)
            atomic_write(args.report, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        atomic_write(args.output, data)
    except (ValueError, OSError, LookupError) as exc:
        if args.report and safe_report:
            report = dict(exc.report) if isinstance(exc, LossyConversionError) else {'schema_version': 1, 'status': 'failed'}
            report['errors'] = [str(exc)]
            try:
                atomic_write(args.report, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            except OSError as report_exc:
                print(f'ERROR writing report: {report_exc}', file=sys.stderr)
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2 if isinstance(exc, LossyConversionError) else 1
    print(f'Converted {args.input.name} -> {args.output}')
    for warning in result.warnings:
        print(f'WARNING: {warning}')
    return 0
