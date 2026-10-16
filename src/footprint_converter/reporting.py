"""Structured conversion diagnostics and provenance; no filesystem writes."""
from __future__ import annotations

from dataclasses import asdict

from .model import ApertureSettings, Footprint, ModelMatch, ModelTransform
from .format_rules import TARGET_REVISION
from .writer import inherit_apertures, native_pad_names
from .format_rules import is_technical_pad
from .strokes import stroke_report
from .pad_geometry import geometry_report


LOSS_CODES = {
    'GRAPHIC_LAYER_SKIPPED', 'GRAPHIC_SKIPPED', 'FEATURE_SKIPPED',
    'TEXT_FIELD_LAYER', 'TEXT_VARIABLE_UNRESOLVED', 'TEXT_LAYER_SKIPPED',
    'MODEL_MISSING', 'MODEL_UNRESOLVED', 'FAB_LAYER_APPROXIMATED',
    'APERTURE_ASSUMED_ZERO', 'NPTH_PASTE_SKIPPED', 'USER_LAYER_APPROXIMATED',
    'TEXT_PROPERTY_FLATTENED', 'TEXT_MARKUP_UNSUPPORTED',
    'TECHNICAL_PAD_CARRIER','CONNECT_PAD_TYPE_FLATTENED',
    'GRAPHIC_STROKE_FLATTENED',
    'CUSTOM_PAD_RECT_FLATTENED',
    'DESCRIPTION_ASCII_ESCAPED',
}


ASSUMPTION_CODES = {'TEXT_ANCHOR', 'MODEL_FRAME_UNVERIFIED', 'MODEL_TRANSFORM_OVERRIDE',
                    'TEXT_UPRIGHT_UNVERIFIED',
                    'NPTH_LIMIT', 'APERTURE_PROJECT_DEFAULT', 'NPTH_MASK_DEFAULT',
                    'FILL_STROKE_MODEL', 'FILL_EXPORT_UNVERIFIED'}


def diagnostic(warning: str) -> dict:
    code, _, message = warning.partition(':')
    severity = ('loss' if code in LOSS_CODES else 'assumption' if code in ASSUMPTION_CODES
                else 'approximation' if code in {'CURVE_APPROXIMATED', 'FILL_APPROXIMATED'} else 'info')
    return {'code': code, 'severity': severity, 'message': message.strip()}


def build_report(fp: Footprint, render_fp: Footprint, matches: list[ModelMatch],
                 fpl: str, warnings: list[str], *, curve_tolerance: float,
                 fill_tolerance: float, aperture_defaults: ApertureSettings | None,
                 text_variables: dict[str, str] | None,
                 model_transform: ModelTransform | None) -> dict:
    """Describe generated records, losses and unverified target assumptions."""
    diagnostics = [diagnostic(w) for w in warnings]
    counts = {}
    for line in fpl.splitlines():
        key = line.strip().partition(':')[0]
        counts[key] = counts.get(key, 0) + 1
    report = {
        'schema_version': 1,
        'status': 'generated_with_loss' if any(d['severity'] == 'loss' for d in diagnostics) else 'generated',
        'footprint': fp.name,
        'target': {'application': 'FreePCB2', 'version': '2.428', 'source_revision': TARGET_REVISION,
                   'format': 'fpl', 'gui_validated': False},
        'coordinates': {'units': 'NM', 'origin_translation_mm': [0, 0], 'y_inverted': True,
                        'centroid': 'computed_by_target_reader'},
        'curve_tolerance_mm': curve_tolerance,
        'counts': {'source_pads': len(fp.pads), 'source_texts': len(fp.texts),
                   'source_filled_polygons': len(fp.filled_polygons),
                   'written_pins': counts.get('pin', 0), 'written_user_texts': counts.get('text', 0),
                   'written_polylines': counts.get('outline_polyline', 0), 'matched_models': len(matches)},
        # Retain metadata that cannot live in .fpl (dynamic content/layer/hide).
        'source_texts': [asdict(t) for t in fp.texts],
        'fills': {'policy': 'overlapping_strokes', 'tolerance_mm': fill_tolerance,
                  'source_polygons': [asdict(p) for p in fp.filled_polygons],
                  'written_boundary_polylines': sum(p.role == 'fill_boundary' for p in render_fp.polylines),
                  'written_scanline_polylines': sum(p.role == 'fill_scanline' for p in render_fp.polylines),
                  'stroke_model': 'ideal_round_ended', 'gui_validated': False,
                  'manufacturing_validated': False},
        'apertures': {'footprint_settings': asdict(fp.apertures),
                      'defaults': asdict(aperture_defaults or ApertureSettings()),
                      'pads': [{'name': p.name, 'source': asdict(p.apertures),
                                'resolved': asdict(inherit_apertures(p.apertures, fp.apertures,
                                                     aperture_defaults or ApertureSettings()))}
                               for p in fp.pads]},
        'text_variable_bindings': text_variables or {},
        'models': [{'source_reference': asdict(m.reference), 'relative_stl': str(m.relative_path),
                    'existing_stl': str(m.stl_path), 'freepcb_3d_folder': str(m.stl_path.parent),
                    'import_basename': m.stl_path.name,
                    'transform': asdict(model_transform or ModelTransform()),
                    'frame_validated': False} for m in matches],
        'diagnostics': diagnostics,
    }
    if fp.filled_circles:
        # Add circle metadata only when present, preserving the existing report
        # contract byte-for-byte for the four previous control samples.
        report['counts']['source_filled_circles'] = len(fp.filled_circles)
        report['fills'].update({
            'source_circles': [asdict(c) for c in fp.filled_circles],
            'circle_bounds': {
                'nominal_disks_covered': True,
                'max_inward_boundary_error_mm': curve_tolerance,
                'max_outward_boundary_error_mm': fill_tolerance,
                'max_boundary_error_mm': max(curve_tolerance, fill_tolerance),
                'model': 'ideal_round_ended',
            },
        })
    if any(is_technical_pad(p) or p.kind=='connect' for p in fp.pads):
        names=native_pad_names(fp)
        report['pad_roles']=dict(native_netlist_verified=False,manufacturing_validated=False,
            technical_carriers=[dict(source_pad_index=i,source=asdict(p),target_name=names[i],
                target_copper=False,target_hole_size_nm=0) for i,p in enumerate(fp.pads) if is_technical_pad(p)],
            contact_pads=[dict(source_pad_index=i,source=asdict(p),target_name=names[i],
                native_connector_attribute_transferred=False) for i,p in enumerate(fp.pads) if p.kind=='connect'])
        report['counts']['technical_carriers']=len(report['pad_roles']['technical_carriers'])
        report['counts']['contact_pads']=len(report['pad_roles']['contact_pads'])
    if fp.patterned_graphics:
        report['graphic_strokes'] = stroke_report(fp, render_fp)
    if render_fp.pad_geometry_results:
        report['pad_geometry'] = geometry_report(render_fp)
    if render_fp.description != fp.description:
        report['description'] = dict(policy='ascii-escape-with-loss', source=fp.description,
                                     written=render_fp.description)
    return report
