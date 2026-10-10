"""In-memory conversion orchestration and the compatible convert API."""
from __future__ import annotations

from pathlib import Path

from .errors import LossyConversionError
from .model import ApertureSettings, ConversionResult, ModelTransform
from .geometry import tessellate_fills
from .parser import parse_footprint
from .validation import validate_footprint
from .model_matching import DEFAULT_STL_ROOT, match_models
from .writer import write_fpl
from .reporting import build_report


def convert_detailed(root: list, footprint_name: str | None = None, *,
                     stl_root: Path = DEFAULT_STL_ROOT,
                     model_transform: ModelTransform | None = None,
                     text_variables: dict[str, str] | None = None,
                     curve_tolerance: float = 0.01, strict: bool = False,
                     aperture_defaults: ApertureSettings | None = None,
                     fill_tolerance: float = 0.01) -> ConversionResult:
    """In-memory conversion and structured report; does not write any file."""
    fp = parse_footprint(root, footprint_name, curve_tolerance=curve_tolerance)
    warnings = validate_footprint(fp)
    render_fp = tessellate_fills(fp, fill_tolerance, warnings)
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
