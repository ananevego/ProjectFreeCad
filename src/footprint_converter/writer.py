"""Serialize an internal footprint into the supported FreePCB2 .fpl subset."""
from __future__ import annotations

import math
import re
from dataclasses import replace

from .errors import ConversionError
from .model import ApertureSettings, Footprint, ModelMatch, ModelTransform, Pad
from .format_rules import (
    GRAPHIC_LAYERS,
    copper_sides,
    integer_angle,
    number,
    pad_shape,
    quote,
    target_point,
)
from .model_matching import openscad_code, resolve_model_transform


TEXT_VARIABLE_RE = re.compile(r'\$\{([^{}]+)\}')


def pad_record(pad: Pad, present: bool) -> str:
    if not present:
        return '0 0 0 0 0'
    height, half_x = int(number(pad.height)), int(number(pad.width / 2))
    # Radius is constrained after size quantization, avoiding reader-side changes.
    radius = min(int(number(pad.radius)), half_x, (height // 20) * 10)
    return f'{pad_shape(pad.shape)} {height} {half_x} {half_x} {radius}'


def inherit_apertures(pad: ApertureSettings, footprint: ApertureSettings,
                      defaults: ApertureSettings) -> ApertureSettings:
    values = []
    for key in ('mask_margin', 'paste_margin', 'paste_ratio'):
        value = next((getattr(s, key) for s in (pad, footprint, defaults)
                      if getattr(s, key) is not None), None)
        if value is not None and not math.isfinite(value):
            raise ConversionError(f'Non-finite aperture default: {key}')
        values.append(value)
    return ApertureSettings(*values)


def aperture_record(pad: Pad, kind: str, present: bool, settings: ApertureSettings,
                    warnings: list[str]) -> str:
    if not present:
        return '0 0 0 0 0'
    if pad.kind == 'np_thru_hole' and kind == 'paste':
        warnings.append(f'NPTH_PASTE_SKIPPED: pad {pad.name!r}; NPTH paste is suppressed')
        return '0 0 0 0 0'
    if not any(layer.endswith('.Cu') for layer in pad.layers):
        # KiCad technical-only pads use their source shape without expansion.
        return pad_record(pad, True)
    if kind == 'mask':
        margin = settings.mask_margin
        if margin is None:
            if pad.kind == 'np_thru_hole':
                warnings.append(f'NPTH_MASK_DEFAULT: pad {pad.name!r}; source size used with zero expansion')
                return pad_record(pad, True)
            warnings.append('APERTURE_PROJECT_DEFAULT: missing mask margin uses FreePCB project settings (99)')
            return '99 0 0 0 0'
        mx = my = margin
    else:
        margin, ratio = settings.paste_margin, settings.paste_ratio
        if margin is None and ratio is None:
            warnings.append('APERTURE_PROJECT_DEFAULT: missing paste margins use FreePCB project settings (99)')
            return '99 0 0 0 0'
        if margin is None or ratio is None:
            warnings.append('APERTURE_ASSUMED_ZERO: unspecified paste margin/ratio assumed zero; supply explicit defaults')
        margin = 0 if margin is None else margin
        ratio = 0 if ratio is None else ratio
        # KiCad GetSolderPasteMargin: per-axis margin = absolute + size * ratio.
        mx, my = margin + pad.width * ratio, margin + pad.height * ratio
    width, height = max(0, pad.width + 2 * mx), max(0, pad.height + 2 * my)
    if width == 0 or height == 0:
        warnings.append(f'APERTURE_CLOSED: pad {pad.name!r} {kind}; resulting opening has zero size')
        return '0 0 0 0 0'
    shape, radius = pad.shape, pad.radius
    if shape == 'roundrect':
        if not math.isclose(mx, my, rel_tol=0, abs_tol=1e-9):
            raise ConversionError(f'Pad {pad.name}: asymmetric roundrect {kind} margin is unsupported')
        radius = max(0, radius + mx)
    elif shape == 'rect' and mx > 0:
        # KiCad plotter inflates rectangles into rounded rectangles.
        shape, radius = 'roundrect', mx
    expanded = replace(pad, shape=shape, width=width, height=height, radius=radius)
    if int(number(width / 2)) <= 0 or int(number(height)) <= 0:
        raise ConversionError(f'Pad {pad.name}: {kind} opening below target resolution')
    warnings.append(f'APERTURE_EXPLICIT: pad {pad.name!r} {kind}, size {width:g} x {height:g} mm')
    return pad_record(expanded, True)


def pad_apertures(pad: Pad, footprint: ApertureSettings, defaults: ApertureSettings,
                  warnings: list[str]) -> dict[str, str]:
    settings = inherit_apertures(pad.apertures, footprint, defaults)
    records = {}
    for side, prefix in [('top', 'F'), ('bottom', 'B')]:
        for kind, layer in [('mask', 'Mask'), ('paste', 'Paste')]:
            present = f'{prefix}.{layer}' in pad.layers or f'*.{layer}' in pad.layers
            records[f'{side}_{kind}'] = aperture_record(pad, kind, present, settings, warnings)
    return records


def selection_bounds(fp: Footprint, apertures: list[dict[str, str]] | None = None) -> tuple[float, float, float, float]:
    points = []
    for index, pad in enumerate(fp.pads):
        width, height = pad.width, pad.height
        if apertures:
            for record in apertures[index].values():
                shape, y, x1, x2, _ = map(int, record.split())
                if shape not in {0, 99}:
                    width, height = max(width, (x1+x2)/1e6), max(height, y/1e6)
        theta = math.radians(pad.rotation)
        hx = max(abs(math.cos(theta)) * width / 2 + abs(math.sin(theta)) * height / 2, pad.drill / 2)
        hy = max(abs(math.sin(theta)) * width / 2 + abs(math.cos(theta)) * height / 2, pad.drill / 2)
        points.extend([(pad.x-hx, -pad.y-hy), (pad.x+hx, -pad.y+hy)])
    for poly in fp.polylines:
        for x, y in poly.points:
            points.extend([(x-poly.width/2, -y-poly.width/2), (x+poly.width/2, -y+poly.width/2)])
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def write_fpl(fp: Footprint, matches: list[ModelMatch], warnings: list[str],
              model_transform: ModelTransform | None = None,
              text_variables: dict[str, str] | None = None,
              aperture_defaults: ApertureSettings | None = None) -> str:
    if fp.filled_polygons:
        raise ConversionError('Filled polygons must be tessellated before calling the writer')
    apertures = [pad_apertures(pad, fp.apertures, aperture_defaults or ApertureSettings(), warnings)
                 for pad in fp.pads]
    lines = [f'name: {quote(fp.name)}', 'author: "KiCad to FreePCB converter"',
             f'package: {quote(fp.name)}', '  units: NM']
    if fp.description:
        lines.append(f'description: {quote(fp.description)}')
    lines.append('  sel_rect: ' + ' '.join(number(v) for v in selection_bounds(fp, apertures)))
    # No centroid record: MakeFromFile computes the actual centre of pad bounds.
    for kind, key in [('reference', 'ref_text'), ('value', 'value_text')]:
        text = next((t for t in fp.texts if t.kind == kind), None)
        if text:
            x, y = target_point(text.x, text.y)
            lines.append(f'  {key}: {number(0 if text.hidden else text.size_y)} {x} {y} {integer_angle(text.rotation)} {number(text.thickness)}')
        else:
            lines.append(f'  {key}: 0 0 0 0 0')
            warnings.append(f'TEXT_MISSING: no {kind}; native field suppressed')
    for text in fp.texts:
        if text.kind in {'reference', 'value'} or text.hidden:
            continue
        if text.layer not in GRAPHIC_LAYERS:
            warnings.append(f'TEXT_LAYER_SKIPPED: {text.content!r} on {text.layer}')
            continue
        content = resolve_text_variables(text.content, text_variables or {}, warnings)
        if content is None:
            continue
        if text.layer in {'F.Fab', 'B.Fab'}:
            warnings.append(f'FAB_LAYER_APPROXIMATED: {text.layer} exported to FreePCB notes layer')
        if text.layer in {'Dwgs.User', 'Cmts.User'}:
            warnings.append(f'USER_LAYER_APPROXIMATED: {text.layer} exported to FreePCB top notes; source layer distinction lost')
        x, y = target_point(text.x, text.y)
        lines.append(f'  text: {quote(content)} {number(text.size_y)} {x} {y} {integer_angle(text.rotation)} {number(text.thickness)} {int(text.mirror)} {GRAPHIC_LAYERS[text.layer]}')
    for poly in fp.polylines:
        x, y = target_point(*poly.points[0])
        lines.append(f'  outline_polyline: {number(poly.width)} {x} {y} 1 0 {GRAPHIC_LAYERS[poly.layer]}')
        for point in poly.points[1:]:
            x, y = target_point(*point)
            lines.append(f'    next_corner: {x} {y} 0')
        if poly.closed:
            lines.append('    close_polyline: 0')
    lines.append(f'  n_pins: {len(fp.pads)}')
    used_names = {pad.name for pad in fp.pads}
    for index, pad in enumerate(fp.pads, 1):
        name = pad.name
        if not name:
            name = f'__NPTH_{index}'
            while name in used_names:
                name += '_'
            used_names.add(name)
            warnings.append(f'NPTH_NAME: unnamed hole assigned {name}')
        x, y = target_point(pad.x, pad.y)
        lines.append(f'    pin: {quote(name)} {number(pad.drill)} {x} {y} {integer_angle(pad.rotation)} ""')
        sides = copper_sides(pad)
        # Omitted top_pad defaults to ROUND 1 mm; write explicit NONE.
        lines.append('      top_pad: ' + pad_record(pad, 'top' in sides))
        lines.append('      bottom_pad: ' + pad_record(pad, 'bottom' in sides))
        if pad.drill:
            lines.append('      inner_pad: ' + pad_record(pad, 'inner' in sides) + ' 0')
        for key, record in apertures[index-1].items():
            lines.append(f'      {key}: {record}')
    for match in matches:
        transform = resolve_model_transform(match.reference, model_transform, warnings)
        for code in openscad_code(match, transform):
            lines.append(f'  openscad_code: {quote(code)}')
        warnings.append(f'MODEL_FOLDER: set FreePCB2 3d_folder to the Windows copy of {match.stl_path.parent}; project units MM')
    return '\n'.join(lines) + '\n'


def resolve_text_variables(content: str, variables: dict[str, str],
                           warnings: list[str]) -> str | None:
    keys = TEXT_VARIABLE_RE.findall(content)
    unresolved = sorted(set(keys) - variables.keys())
    if unresolved or '${' in TEXT_VARIABLE_RE.sub('', content):
        warnings.append(f'TEXT_VARIABLE_UNRESOLVED: skipped {content!r}; explicit binding required')
        return None
    if keys:
        warnings.append(f'TEXT_VARIABLE_BOUND: {content!r} frozen to supplied values (no runtime substitution)')
    resolved = TEXT_VARIABLE_RE.sub(lambda m: variables[m[1]], content)
    if '${' in resolved:
        raise ConversionError('Recursive text variable binding is unsupported')
    return resolved
