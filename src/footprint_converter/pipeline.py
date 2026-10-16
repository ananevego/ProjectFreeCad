"""In-memory conversion orchestration and the compatible convert API."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from .errors import LossyConversionError
from .model import ApertureSettings, ConversionResult, ModelTransform
from .geometry import tessellate_fills
from .parser import parse_footprint
from .validation import validate_footprint
from .model_matching import DEFAULT_STL_ROOT, match_models
from .writer import write_fpl
from .reporting import build_report
from .strokes import expand_strokes
from .pad_geometry import normalize_pad_geometry


def convert_detailed(root: list, footprint_name: str | None = None, *,
                     stl_root: Path = DEFAULT_STL_ROOT,
                     model_transform: ModelTransform | None = None,
                     text_variables: dict[str, str] | None = None,
                     curve_tolerance: float = 0.01, strict: bool = False,
                     aperture_defaults: ApertureSettings | None = None,
                     fill_tolerance: float = 0.01,
                     description_policy: str = 'preserve') -> ConversionResult:
    """In-memory conversion and structured report; does not write any file."""
    if description_policy not in {'preserve', 'ascii-escape-with-loss'}:
        raise ValueError('Unknown description policy')
    fp = parse_footprint(root, footprint_name, curve_tolerance=curve_tolerance)
    geometry_warnings = []
    geometry_fp = normalize_pad_geometry(fp, aperture_defaults, geometry_warnings)
    warnings = validate_footprint(geometry_fp) + geometry_warnings
    render_fp = expand_strokes(geometry_fp, warnings)
    render_fp = tessellate_fills(render_fp, fill_tolerance, warnings, curve_tolerance=curve_tolerance)
    if description_policy == 'ascii-escape-with-loss':
        description = ''.join(c if 32 <= ord(c) < 128 and c != '"' else f'[U+{ord(c):04X}]' for c in render_fp.description)
    else:
        description = render_fp.description
    if description != render_fp.description:
        render_fp = replace(render_fp, description=description)
        warnings.append('DESCRIPTION_ASCII_ESCAPED: Unicode, quote or control characters in description written as printable [U+XXXX] tokens; source text retained in report')
    matches = match_models(fp.models, Path(stl_root), warnings)
    fpl = write_fpl(render_fp, matches, warnings, model_transform, text_variables, aperture_defaults)
    warnings = list(dict.fromkeys(warnings))
    report = build_report(fp, render_fp, matches, fpl, warnings,
                          curve_tolerance=curve_tolerance, fill_tolerance=fill_tolerance,
                          aperture_defaults=aperture_defaults, text_variables=text_variables,
                          model_transform=model_transform)
    if strict and report['status'] == 'generated_with_loss':
        report['status'] = 'rejected_loss'
        raise LossyConversionError(report)
    return ConversionResult(fpl, warnings, report)


def convert(root: list, footprint_name: str | None = None, **options) -> tuple[str, list[str]]:
    """Prototype-compatible entry point; no filesystem writes."""
    result = convert_detailed(root, footprint_name, **options)
    return result.fpl, result.warnings
