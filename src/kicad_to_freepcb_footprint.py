"""KiCad -> FreePCB2 2.428; never converts or rewrites model files.

Target: niconson/FreePCB-2 commit 3af0f9b9a234c97f2d21455c936abeb8439d2d45.
See docs/FOOTPRINT_CONVERTER.md for the format contract and limitations.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath

TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+')
DEFAULT_STL_ROOT = Path(__file__).resolve().parents[1] / 'stl_files'
PAD_SHAPES = {'circle': 1, 'rect': 3, 'roundrect': 4, 'oval': 5}
GRAPHIC_LAYERS = {'F.SilkS': 4, 'B.SilkS': 5, 'F.Fab': 7, 'B.Fab': 8,
                  'Dwgs.User': 7, 'Cmts.User': 7}
ZERO = (0.0, 0.0, 0.0)
ONE = (1.0, 1.0, 1.0)
TARGET_REVISION = '3af0f9b9a234c97f2d21455c936abeb8439d2d45'
TEXT_VARIABLE_RE = re.compile(r'\$\{([^{}]+)\}')
LOSS_CODES = {
    'GRAPHIC_LAYER_SKIPPED', 'GRAPHIC_SKIPPED', 'FEATURE_SKIPPED',
    'TEXT_FIELD_LAYER', 'TEXT_VARIABLE_UNRESOLVED', 'TEXT_LAYER_SKIPPED',
    'MODEL_MISSING', 'MODEL_UNRESOLVED', 'FAB_LAYER_APPROXIMATED',
    'APERTURE_ASSUMED_ZERO', 'NPTH_PASTE_SKIPPED', 'USER_LAYER_APPROXIMATED',
}
ASSUMPTION_CODES = {'TEXT_ANCHOR', 'MODEL_FRAME_UNVERIFIED', 'MODEL_TRANSFORM_OVERRIDE',
                    'NPTH_LIMIT', 'APERTURE_PROJECT_DEFAULT', 'NPTH_MASK_DEFAULT'}


class ConversionError(ValueError):
    """Input cannot safely be represented by the supported target subset."""


class LossyConversionError(ConversionError):
    def __init__(self, report: dict):
        self.report = report
        codes = sorted({d['code'] for d in report['diagnostics'] if d['severity'] == 'loss'})
        super().__init__('Strict conversion rejected data loss: ' + ', '.join(codes))


@dataclass(frozen=True)
class ConversionResult:
    fpl: str
    warnings: list[str]
    report: dict


# Internal model: dimensions in mm, coordinates in the KiCad frame.
@dataclass(frozen=True)
class ApertureSettings:
    """Margins per side, in mm; ratio is dimensionless. None means inherited."""
    mask_margin: float | None = None
    paste_margin: float | None = None
    paste_ratio: float | None = None


@dataclass(frozen=True)
class Pad:
    name: str
    kind: str
    shape: str
    x: float
    y: float
    rotation: float
    width: float
    height: float
    drill: float
    layers: tuple[str, ...]
    radius: float = 0.0
    apertures: ApertureSettings = field(default_factory=ApertureSettings)


@dataclass(frozen=True)
class FootprintText:
    kind: str
    content: str
    x: float
    y: float
    rotation: float
    size_x: float
    size_y: float
    thickness: float
    layer: str
    hidden: bool = False
    mirror: bool = False


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[float, float], ...]
    width: float
    layer: str
    closed: bool = False


@dataclass(frozen=True)
class ModelReference:
    path: str
    offset: tuple[float, float, float] = ZERO
    rotation: tuple[float, float, float] = ZERO
    scale: tuple[float, float, float] = ONE


@dataclass
class Footprint:
    name: str
    pads: list[Pad]
    texts: list[FootprintText]
    polylines: list[Polyline]
    models: list[ModelReference]
    description: str = ''
    warnings: list[str] = field(default_factory=list)
    apertures: ApertureSettings = field(default_factory=ApertureSettings)


@dataclass(frozen=True)
class ModelMatch:
    reference: ModelReference
    stl_path: Path
    relative_path: PurePosixPath


@dataclass(frozen=True)
class ModelTransform:
    """Full STL -> target OpenSCAD transform: mm, degrees, unitless scale.

    Overrides the KiCad model transform. Default identity assumes the existing
    STL retains KiCad's 3D frame and millimetres; GUI/geometry not validated.
    """
    translation: tuple[float, float, float] = ZERO
    rotation: tuple[float, float, float] = ZERO
    scale: tuple[float, float, float] = ONE


# KiCad parser

def atom(value: str) -> str:
    if not value.startswith('"'):
        return value
    return re.sub(r'\\([\\"nt])', lambda m: {'n': '\n', 't': '\t'}.get(m[1], m[1]), value[1:-1])


def parse_sexpr(text: str) -> list:
    stack: list[list] = []
    root = None
    position = 0
    for match in TOKEN_RE.finditer(text):
        if text[position:match.start()].strip():
            raise ConversionError('Invalid/unclosed KiCad quoted string')
        position = match.end()
        token = match[0]
        if token == '(':
            if not stack and root is not None:
                raise ConversionError('Multiple KiCad root expressions')
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ConversionError('Unexpected closing parenthesis')
            node = stack.pop()
            if not stack:
                root = node
        else:
            if not stack:
                raise ConversionError(f'Unexpected token outside expression: {token}')
            stack[-1].append(atom(token))
    if text[position:].strip() or stack or root is None:
        raise ConversionError('Unbalanced KiCad S-expression')
    return root


def children(node: list, kind: str) -> list[list]:
    return [item for item in node if isinstance(item, list) and item and item[0] == kind]


def child(node: list, kind: str) -> list | None:
    return next(iter(children(node, kind)), None)


def scalar(node: list, kind: str, default=None):
    item = child(node, kind)
    return item[1] if item and len(item) > 1 else default


def pair(node: list | None) -> tuple[float, float]:
    if node is None or len(node) < 3:
        raise ConversionError('Missing coordinate/size pair')
    return float(node[1]), float(node[2])


def require_atoms(node: list, count: int, context: str) -> None:
    if len(node) < count or any(not isinstance(v, str) for v in node[:count]):
        raise ConversionError(f'Malformed {context}: expected {count} atom fields')


def xyz(node: list, kind: str, default: tuple) -> tuple[float, float, float]:
    item = child(node, kind)
    values = child(item, 'xyz') if item else None
    if item and (not values or len(values) != 4):
        raise ConversionError(f'Invalid model {kind}')
    return tuple(map(float, values[1:])) if values else default


def parse_apertures(node: list) -> ApertureSettings:
    values = []
    # KiCad uses solder_paste_ratio on footprints, *_margin_ratio on pads.
    keys = ('solder_mask_margin', 'solder_paste_margin',
            'solder_paste_margin_ratio' if node[0] == 'pad' else 'solder_paste_ratio')
    for key in keys:
        item = child(node, key)
        if item is None:
            values.append(None)
        elif len(item) != 2 or not isinstance(item[1], str):
            raise ConversionError(f'Malformed {key}')
        else:
            value = float(item[1])
            if not math.isfinite(value):
                raise ConversionError(f'Non-finite {key}')
            values.append(value)
    return ApertureSettings(*values)


def parse_pad(node: list) -> Pad:
    require_atoms(node, 4, 'pad')
    at = child(node, 'at')
    x, y = pair(at)
    width, height = pair(child(node, 'size'))
    drill = child(node, 'drill')
    if drill and (len(drill) != 2 or drill[1] == 'oval'):
        raise ConversionError(f'Pad {node[1]}: oval/offset drill is not representable by hole_size')
    radius = 0.0
    if node[3] == 'roundrect':
        ratio = scalar(node, 'roundrect_rratio')
        if ratio is None or not 0 <= float(ratio) <= 0.5:
            raise ConversionError(f'Pad {node[1]}: missing/invalid roundrect_rratio')
        radius = min(width, height) * float(ratio)
    for key in ('chamfer', 'chamfer_ratio', 'rect_delta', 'padstack', 'remove_unused_layer'):
        if child(node, key):
            raise ConversionError(f'Pad {node[1]}: unsupported {key}')
    for key in ('remove_unused_layers', 'keep_end_layers'):
        items = children(node, key)
        if len(items) > 1:
            raise ConversionError(f'Pad {node[1]}: duplicate {key}')
        item = items[0] if items else None
        if item is not None:
            # KiCad parseMaybeAbsentBool(true): absent argument enables the flag.
            # Explicit no is inert; enabled board-dependent padstacks need more
            # than the target's single shared inner_pad and are not approximated.
            if len(item) > 2 or len(item) == 2 and (not isinstance(item[1], str) or item[1] not in {'yes', 'no'}):
                raise ConversionError(f'Pad {node[1]}: malformed {key}')
            if len(item) == 1 or item[1] == 'yes':
                raise ConversionError(f'Pad {node[1]}: unsupported enabled {key}')
    layers = child(node, 'layers')
    return Pad(node[1], node[2], node[3], x, y, float(at[3]) if len(at) > 3 else 0,
               width, height, float(drill[1]) if drill else 0,
               tuple(layers[1:]) if layers else (), radius, parse_apertures(node))


def parse_text(node: list) -> FootprintText:
    require_atoms(node, 3, 'text')
    kind = node[1].lower() if node[0] == 'property' else node[1]
    effects = child(node, 'effects')
    font = child(effects, 'font') if effects else None
    if not font:
        raise ConversionError(f'Text {node[2]!r}: missing font')
    if child(font, 'face') or 'bold' in font or 'italic' in font:
        raise ConversionError(f'Text {node[2]!r}: custom/bold/italic font is unsupported')
    justify = child(effects, 'justify')
    if justify and any(item != 'mirror' for item in justify[1:]):
        raise ConversionError(f'Text {node[2]!r}: non-centred justification is unsupported')
    at = child(node, 'at')
    x, y = pair(at)
    sx, sy = pair(child(font, 'size'))
    hidden = 'hide' in node or scalar(node, 'hide', 'no') == 'yes' or 'hide' in effects
    return FootprintText(kind, node[2], x, y, float(at[3]) if len(at) > 3 else 0,
                         sx, sy, float(scalar(font, 'thickness', 0.15)),
                         scalar(node, 'layer', ''), hidden,
                         bool(justify and 'mirror' in justify))


def stroke_width(node: list) -> float:
    stroke = child(node, 'stroke')
    if stroke and scalar(stroke, 'type', 'solid') != 'solid':
        raise ConversionError('Non-solid graphic stroke is unsupported')
    return float(scalar(stroke or node, 'width', 0.15))


# Graphic geometry is independent of the target writer. Arcs use explicit
# start/mid/end; legacy centre/angle arcs remain unsupported, without guessing.
def sample_arc(center: tuple[float, float], radius: float, start_angle: float,
               sweep: float, tolerance: float) -> tuple[tuple[float, float], ...]:
    if not all(math.isfinite(v) for v in (*center, radius, start_angle, sweep)) or radius <= 0:
        raise ConversionError('Invalid circle/arc geometry')
    # Reserve 10 nm for coordinate quantization in the writer.
    budget = tolerance - 0.00001
    delta = min(math.pi / 4, 2 * math.acos(max(-1, 1 - budget / radius)))
    if delta <= 0:
        raise ConversionError('Arc exceeds the supported tessellation resolution')
    count = max(1, math.ceil(abs(sweep) / delta))
    if count > 4096:
        raise ConversionError('Arc requires more than 4096 segments; increase curve tolerance')
    return tuple((center[0] + radius * math.cos(start_angle + sweep * i / count),
                  center[1] + radius * math.sin(start_angle + sweep * i / count))
                 for i in range(count + 1))


def arc_points(start: tuple, mid: tuple, end: tuple, tolerance: float) -> tuple:
    if not all(math.isfinite(v) for p in (start, mid, end) for v in p):
        raise ConversionError('Invalid arc coordinates')
    # Solve in the local frame for numerical stability far from the origin.
    bx, by = mid[0] - start[0], mid[1] - start[1]
    cx, cy = end[0] - start[0], end[1] - start[1]
    determinant = 2 * (bx * cy - by * cx)
    if abs(determinant) <= 1e-12 * max(bx*bx + by*by, cx*cx + cy*cy, 1e-12):
        raise ConversionError('Arc start/mid/end are coincident or collinear')
    b2, c2 = bx*bx + by*by, cx*cx + cy*cy
    ux = (cy*b2 - by*c2) / determinant
    uy = (bx*c2 - cx*b2) / determinant
    center = (start[0] + ux, start[1] + uy)
    radius = math.hypot(ux, uy)
    angles = [math.atan2(p[1]-center[1], p[0]-center[0]) for p in (start, mid, end)]
    sweep = (angles[2] - angles[0]) % math.tau
    if (angles[1] - angles[0]) % math.tau > sweep:
        sweep -= math.tau
    points = list(sample_arc(center, radius, angles[0], sweep, tolerance))
    points[0], points[-1] = start, end  # Preserve endpoints exactly.
    return tuple(points)


def parse_graphic(item: list, tolerance: float, warnings: list[str]) -> Polyline:
    kind, layer = item[0], scalar(item, 'layer', '')
    if scalar(item, 'fill', 'no') != 'no':
        raise ConversionError(f'Filled {kind} on {layer} is unsupported')
    closed = kind != 'fp_line' and kind != 'fp_arc'
    if kind == 'fp_line':
        points = (pair(child(item, 'start')), pair(child(item, 'end')))
    elif kind == 'fp_rect':
        start, end = pair(child(item, 'start')), pair(child(item, 'end'))
        points = (start, (end[0], start[1]), end, (start[0], end[1]))
    elif kind == 'fp_poly':
        pts = child(item, 'pts')
        if not pts or any(not isinstance(p, list) or not p or p[0] != 'xy' for p in pts[1:]):
            raise ConversionError('Malformed fp_poly points')
        points = tuple(pair(p) for p in pts[1:])
        if points and points[0] == points[-1]:
            points = points[:-1]
        if len(points) < 3:
            raise ConversionError('Polygon requires at least three corners')
    elif kind == 'fp_circle':
        center, end = pair(child(item, 'center')), pair(child(item, 'end'))
        radius = math.dist(center, end)
        points = sample_arc(center, radius, math.atan2(end[1]-center[1], end[0]-center[0]),
                            math.tau, tolerance)[:-1]
    else:
        if child(item, 'mid') is None:
            raise ConversionError('Legacy centre/angle fp_arc is unsupported; start/mid/end required')
        points = arc_points(pair(child(item, 'start')), pair(child(item, 'mid')),
                            pair(child(item, 'end')), tolerance)
    if kind in {'fp_circle', 'fp_arc'}:
        warnings.append(f'CURVE_APPROXIMATED: {kind} on {layer}, chord error <= {tolerance:g} mm')
    if layer in {'F.Fab', 'B.Fab'}:
        warnings.append(f'FAB_LAYER_APPROXIMATED: {layer} exported to FreePCB notes layer')
    if layer in {'Dwgs.User', 'Cmts.User'}:
        warnings.append(f'USER_LAYER_APPROXIMATED: {layer} exported to FreePCB top notes; source layer distinction lost')
    return Polyline(points, stroke_width(item), layer, closed)


def parse_footprint(root: list, footprint_name: str | None = None, *,
                    curve_tolerance: float = 0.01) -> Footprint:
    if not math.isfinite(curve_tolerance) or curve_tolerance <= 0.00001:
        raise ConversionError('Curve tolerance must be greater than 0.00001 mm')
    require_atoms(root, 2, 'footprint')
    if root[0] not in {'footprint', 'module'}:
        raise ConversionError('Expected a KiCad footprint/module expression')
    fp = Footprint(footprint_name or root[1], [], [], [], [], scalar(root, 'descr', ''))
    fp.apertures = parse_apertures(root)
    if child(root, 'at'):
        raise ConversionError('Expected library-local .kicad_mod coordinates, not board placement')
    for item in root:
        if not isinstance(item, list) or not item:
            continue
        require_atoms(item, 1, 'node')
        kind = item[0]
        if kind in {'model', 'property'}:
            require_atoms(item, 2, kind)
        if kind == 'pad':
            fp.pads.append(parse_pad(item))
        elif kind == 'model':
            hide = child(item, 'hide')
            if 'hide' in item or hide is not None and (len(hide) == 1 or hide[1] != 'no'):
                fp.warnings.append(f'MODEL_HIDDEN: skipped {item[1]}')
                continue
            if child(item, 'at'):
                raise ConversionError('Legacy model (at ...) units unsupported; use (offset ...)')
            fp.models.append(ModelReference(item[1], xyz(item, 'offset', ZERO),
                                            xyz(item, 'rotate', ZERO), xyz(item, 'scale', ONE)))
        elif kind == 'fp_text' or kind == 'property' and item[1].lower() in {'reference', 'value'}:
            fp.texts.append(parse_text(item))
        elif kind in {'fp_line', 'fp_rect', 'fp_circle', 'fp_arc', 'fp_poly'}:
            layer = scalar(item, 'layer', '')
            if layer not in GRAPHIC_LAYERS:
                fp.warnings.append(f'GRAPHIC_LAYER_SKIPPED: {kind} on {layer}')
                continue
            fp.polylines.append(parse_graphic(item, curve_tolerance, fp.warnings))
        elif kind.startswith('fp_'):
            fp.warnings.append(f'GRAPHIC_SKIPPED: unsupported {kind} on {scalar(item, "layer", "unknown")}')
        elif kind in {'zone', 'rule_area'}:
            fp.warnings.append(f'FEATURE_SKIPPED: unsupported {kind}')
    return fp


# Validation/reporting

def integer_angle(value: float) -> int:
    if not math.isfinite(value) or not math.isclose(value, round(value), rel_tol=0, abs_tol=1e-8):
        raise ConversionError(f'FreePCB2 stores integer angles; unsupported angle {value}')
    # KiCad positive rotation is CCW; FreePCB pad/text rotation is clockwise.
    return -round(value) % 360


def quote(value: str) -> str:
    # No escaping convention for embedded quotes verified in the target reader.
    if '"' in value or any(ord(c) < 32 for c in value):
        raise ConversionError(f'FreePCB quoted field cannot safely represent {value!r}')
    return f'"{value}"'


def pad_shape(shape: str) -> int:
    if shape not in PAD_SHAPES:
        raise ConversionError(f'Unsupported KiCad pad shape: {shape}')
    return PAD_SHAPES[shape]


def copper_sides(pad: Pad) -> set[str]:
    copper = {layer for layer in pad.layers if layer.endswith('.Cu')}
    if pad.kind == 'np_thru_hole':
        return set()
    if copper == {'*.Cu'} and pad.kind == 'thru_hole':
        return {'top', 'inner', 'bottom'}
    if copper - {'F.Cu', 'B.Cu'}:
        raise ConversionError(f'Pad {pad.name}: selected inner copper layers cannot be expressed by one inner_pad')
    if not copper:
        raise ConversionError(f'Pad {pad.name}: no copper layers')
    if pad.kind == 'smd' and len(copper) != 1:
        raise ConversionError(f'Pad {pad.name}: SMD must have one outer copper layer')
    return {side for layer, side in [('F.Cu', 'top'), ('B.Cu', 'bottom')] if layer in copper}


def validate_footprint(fp: Footprint) -> list[str]:
    warnings = list(fp.warnings)
    quote(fp.name)
    if not fp.name.strip() or len(fp.name) > 99:
        raise ConversionError('Footprint name must contain 1..99 characters')
    if not fp.pads:
        raise ConversionError('This conversion stage requires at least one pad/hole')
    for pad in fp.pads:
        if pad.kind not in {'smd', 'thru_hole', 'np_thru_hole'}:
            raise ConversionError(f'Pad {pad.name}: unsupported type {pad.kind}')
        quote(pad.name)
        if len(pad.name) > 39 or not pad.name and pad.kind != 'np_thru_hole':
            raise ConversionError(f'Pad {pad.name!r}: invalid pin name')
        pad_shape(pad.shape)
        integer_angle(pad.rotation)
        values = (pad.x, pad.y, pad.width, pad.height, pad.drill, pad.radius)
        if not all(math.isfinite(v) for v in values) or min(pad.width, pad.height) <= 0:
            raise ConversionError(f'Pad {pad.name}: invalid dimensions/coordinates')
        if pad.shape == 'circle' and not math.isclose(pad.width, pad.height, abs_tol=1e-8):
            raise ConversionError(f'Pad {pad.name}: non-circular circle is unsupported')
        if pad.kind == 'smd' and pad.drill != 0 or pad.kind != 'smd' and pad.drill <= 0:
            raise ConversionError(f'Pad {pad.name}: invalid drill for {pad.kind}')
        if int(number(pad.width / 2)) <= 0 or int(number(pad.height)) <= 0:
            raise ConversionError(f'Pad {pad.name}: dimensions below target resolution')
        if pad.drill and int(number(pad.drill)) <= 0:
            raise ConversionError(f'Pad {pad.name}: drill below target resolution')
        copper_sides(pad)
        if pad.kind == 'np_thru_hole':
            warnings.append('NPTH_LIMIT: hole with no copper; .fpl has no explicit plating flag')
    for text in fp.texts:
        quote(text.content)
        integer_angle(text.rotation)
        if not all(math.isfinite(v) for v in (text.x, text.y, text.size_x, text.size_y, text.thickness)):
            raise ConversionError('Non-finite text dimensions/coordinates')
        if min(text.size_x, text.size_y, text.thickness) <= 0:
            raise ConversionError('Invalid text dimensions')
        if not math.isclose(text.size_x, text.size_y, abs_tol=1e-8):
            raise ConversionError('Anisotropic text size cannot be expressed by one font_size')
        if text.kind in {'reference', 'value'}:
            if sum(t.kind == text.kind for t in fp.texts) != 1:
                raise ConversionError(f'Duplicate {text.kind} text')
            if text.layer != 'F.SilkS' or text.mirror:
                warnings.append(f'TEXT_FIELD_LAYER: {text.kind} uses native dynamic field; source {text.layer}/mirror cannot be stored')
            warnings.append(f'TEXT_DYNAMIC: {text.kind} content {text.content!r} belongs to the placed component, not .fpl')
    if fp.texts:
        warnings.append('TEXT_ANCHOR: source text positions retained; target font/baseline differs from KiCad centre anchoring')
    for poly in fp.polylines:
        if not math.isfinite(poly.width) or poly.width <= 0 or not all(
                math.isfinite(v) for point in poly.points for v in point):
            raise ConversionError('Invalid graphic dimensions/coordinates')
    return warnings


# Model matcher: references + metadata only, never model contents.

def match_models(references: list[ModelReference], stl_root: Path,
                 warnings: list[str]) -> list[ModelMatch]:
    matches = []
    base = stl_root.resolve()
    if not references:
        warnings.append('MODEL_MISSING: no KiCad model reference; no basename guessing')
    for reference in references:
        parts = PurePosixPath(reference.path.replace('\\', '/')).parts
        indices = [i for i, part in enumerate(parts) if part.endswith('.3dshapes')]
        if len(indices) != 1 or PurePosixPath(reference.path).suffix.lower() not in {'.step', '.stp', '.wrl', '.stl'}:
            warnings.append(f'MODEL_UNRESOLVED: expected a .3dshapes path in {reference.path}')
            continue
        relative = PurePosixPath(*parts[indices[0]:]).with_suffix('.stl')
        if '..' in relative.parts or len(relative.parts) != 2:
            warnings.append(f'MODEL_UNRESOLVED: unsupported relative model path {relative}')
            continue
        candidate = base.joinpath(*relative.parts).resolve()
        if not candidate.is_relative_to(base):
            raise ConversionError(f'Model path escapes STL root: {relative}')
        if not candidate.is_file():
            warnings.append(f'MODEL_MISSING: {relative}')
            continue
        if candidate.stat().st_size == 0:
            raise ConversionError(f'Empty existing STL: {relative}')
        match = ModelMatch(reference, candidate, relative)
        if match not in matches:
            matches.append(match)
    if len({m.stl_path.parent for m in matches}) > 1:
        raise ConversionError('FreePCB2 2.428 basename imports require one 3d_folder; models span multiple folders')
    return matches


def resolve_model_transform(reference: ModelReference, override: ModelTransform | None,
                            warnings: list[str]) -> ModelTransform:
    if override is None:
        if (reference.offset, reference.rotation, reference.scale) != (ZERO, ZERO, ONE):
            raise ConversionError('Non-identity KiCad 3D transform requires an explicit target ModelTransform')
        warnings.append('MODEL_FRAME_UNVERIFIED: identity assumes STL coordinates/units match KiCad 3D (mm)')
        return ModelTransform()
    vectors = (override.translation, override.rotation, override.scale)
    if any(len(v) != 3 for v in vectors) or not all(math.isfinite(n) for v in vectors for n in v) or 0 in override.scale:
        raise ConversionError('Invalid target model transform')
    warnings.append('MODEL_TRANSFORM_OVERRIDE: explicit full target transform replaces KiCad transform; GUI validation pending')
    return override


def openscad_code(match: ModelMatch, transform: ModelTransform) -> list[str]:
    filename = match.stl_path.name
    if any(c in filename for c in '`"\n\r'):
        raise ConversionError('Model basename cannot be represented in OpenSCAD import')
    def vector(values):
        return '[' + ','.join(f'{v:.9g}' for v in values) + ']'
    return [
        'translate([0,0,0]) // (automatic adjustment when moving the footprint origin)',
        'scale([1,1,1]) // (automatic adjustment when changing the project units)',
        '{', f'  translate({vector(transform.translation)})',
        f'  rotate({vector(transform.rotation)})', f'  scale({vector(transform.scale)})',
        f'  import(`{filename}`);', '}',
    ]


# FreePCB2 writer

def number(value: float) -> str:
    """Millimetres -> NM, quantized to the reader's 10 nm grid."""
    if not math.isfinite(value) or abs(value) > 2147.48364:
        raise ConversionError('Dimension exceeds the target signed 32-bit NM range')
    return str(round(value * 100_000) * 10)


def target_point(x: float, y: float) -> tuple[str, str]:
    # KiCad Y down -> FreePCB2 Y up. No translation of the footprint origin.
    return number(x), number(-y)


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


def diagnostic(warning: str) -> dict:
    code, _, message = warning.partition(':')
    severity = ('loss' if code in LOSS_CODES else 'assumption' if code in ASSUMPTION_CODES
                else 'approximation' if code == 'CURVE_APPROXIMATED' else 'info')
    return {'code': code, 'severity': severity, 'message': message.strip()}


def convert_detailed(root: list, footprint_name: str | None = None, *,
                     stl_root: Path = DEFAULT_STL_ROOT,
                     model_transform: ModelTransform | None = None,
                     text_variables: dict[str, str] | None = None,
                     curve_tolerance: float = 0.01, strict: bool = False,
                     aperture_defaults: ApertureSettings | None = None) -> ConversionResult:
    """In-memory conversion and structured report; does not write any file."""
    fp = parse_footprint(root, footprint_name, curve_tolerance=curve_tolerance)
    warnings = validate_footprint(fp)
    matches = match_models(fp.models, Path(stl_root), warnings)
    fpl = write_fpl(fp, matches, warnings, model_transform, text_variables, aperture_defaults)
    warnings = list(dict.fromkeys(warnings))
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
                   'written_pins': counts.get('pin', 0), 'written_user_texts': counts.get('text', 0),
                   'written_polylines': counts.get('outline_polyline', 0), 'matched_models': len(matches)},
        # Retain metadata that cannot live in .fpl (dynamic content/layer/hide).
        'source_texts': [asdict(t) for t in fp.texts],
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
    if strict and report['status'] == 'generated_with_loss':
        report['status'] = 'rejected_loss'
        raise LossyConversionError(report)
    return ConversionResult(fpl, warnings, report)


def convert(root: list, footprint_name: str | None = None, **options) -> tuple[str, list[str]]:
    """Prototype-compatible entry point; no filesystem writes."""
    result = convert_detailed(root, footprint_name, **options)
    return result.fpl, result.warnings


def validate_output_path(path: Path, source: Path, stl_root: Path) -> None:
    resolved = path.resolve()
    if resolved == source.resolve():
        raise ConversionError('Output must differ from input')
    for protected in (DEFAULT_STL_ROOT, DEFAULT_STL_ROOT.parent / 'step_files', stl_root):
        if resolved.is_relative_to(protected.resolve()):
            raise ConversionError('Output cannot be inside model storage')


def atomic_write(path: Path, data: bytes) -> None:
    """Replace an output only after all bytes are written successfully."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.freepcb-', delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


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


if __name__ == '__main__':
    raise SystemExit(main())
