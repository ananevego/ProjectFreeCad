"""KiCad S-expression parser and source-to-internal-model translation."""
from __future__ import annotations

import math
import re

from .errors import ConversionError
from .model import (
    ApertureSettings,
    FilledCircle,
    FilledPolygon,
    Footprint,
    FootprintText,
    ModelReference,
    ONE,
    Pad,
    PatternedGraphic,
    Polyline,
    ZERO,
)
from .format_rules import GRAPHIC_LAYERS
from .geometry import arc_points, legacy_arc_points, sample_arc


TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+')


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


def text_flag(node: list, key: str, *, default: bool = False) -> bool:
    """KiCad parseMaybeAbsentBool: bare/key-only enables, explicit no disables."""
    nodes = children(node, key)
    bare = sum(item == key for item in node if isinstance(item, str))
    if len(nodes) + bare > 1:
        raise ConversionError(f'Duplicate text {key}')
    if bare:
        return True
    if not nodes:
        return default
    item = nodes[0]
    if len(item) == 1:
        return True
    if len(item) != 2 or not isinstance(item[1], str) or item[1] not in {'yes', 'no'}:
        raise ConversionError(f'Malformed text {key}')
    return item[1] == 'yes'


def parse_text(node: list) -> FootprintText:
    require_atoms(node, 3, 'text')
    content_index = 2
    if node[0] == 'fp_text' and node[2] == 'locked' and len(node) > 3 and isinstance(node[3], str):
        content_index = 3  # Legacy bare locked before the text string.
    content = node[content_index]
    attributes = node[content_index + 1:]
    kind = node[1].lower() if node[0] == 'property' else node[1]
    if node[0] == 'fp_text' and kind not in {'reference', 'value', 'user'}:
        raise ConversionError(f'Unsupported footprint text type: {kind}')
    for container, keys in ((node, ('at', 'layer', 'effects')),
                            (child(node, 'effects') or [], ('font', 'justify'))):
        for key in keys:
            if len(children(container, key)) > 1:
                raise ConversionError(f'Duplicate text {key}')
    effects = child(node, 'effects')
    font = child(effects, 'font') if effects else None
    if not font:
        raise ConversionError(f'Text {content!r}: missing font')
    if child(font, 'face') or text_flag(font, 'bold') or text_flag(font, 'italic'):
        raise ConversionError(f'Text {content!r}: custom/bold/italic font is unsupported')
    for key in ('size', 'thickness'):
        if len(children(font, key)) > 1:
            raise ConversionError(f'Duplicate text font {key}')
        item = child(font, key)
        if item is not None:
            count = 3 if key == 'size' else 2
            require_atoms(item, count, f'text font {key}')
            if len(item) != count:
                raise ConversionError(f'Malformed text font {key}')
    if child(font, 'line_spacing') is not None:
        raise ConversionError('Custom text line spacing is unsupported')
    justify = child(effects, 'justify')
    if justify and any(item != 'mirror' for item in justify[1:]):
        raise ConversionError(f'Text {content!r}: non-centred justification is unsupported')
    at = child(node, 'at')
    if at is None:
        raise ConversionError('Missing text at')
    require_atoms(at, 3, 'text at')
    tail = at[3:]
    unlocked_at = bool(tail and tail[-1] == 'unlocked')
    if unlocked_at:
        tail = tail[:-1]
    if len(tail) > 1 or any(not isinstance(v, str) for v in tail):
        raise ConversionError('Malformed text at')
    if unlocked_at and (child(attributes, 'unlocked') is not None or 'unlocked' in attributes):
        raise ConversionError('Duplicate text unlocked')
    layer = child(node, 'layer')
    if layer is None or len(layer) < 2:
        raise ConversionError('Missing text layer')
    require_atoms(layer, len(layer), 'text layer')
    if 'knockout' in layer[2:]:
        raise ConversionError('Knockout footprint text is unsupported')
    if len(layer) != 2:
        raise ConversionError('Malformed text layer')
    x, y = pair(at)
    sx, sy = pair(child(font, 'size'))
    if (child(attributes, 'hide') is not None or 'hide' in attributes) and (child(effects, 'hide') is not None or 'hide' in effects):
        raise ConversionError('Duplicate text hide across node/effects')
    hidden = text_flag(attributes, 'hide') or text_flag(effects, 'hide')
    return FootprintText(kind, content, x, y, float(tail[0]) if tail else 0,
                         sx, sy, float(scalar(font, 'thickness', 0.15)),
                         scalar(node, 'layer', ''), hidden,
                         bool(justify and 'mirror' in justify),
                         not (unlocked_at or text_flag(attributes, 'unlocked')),
                         node[1] if node[0] == 'property' else None)


def stroke_settings(node: list) -> tuple[str, float]:
    strokes = children(node, 'stroke')
    if len(strokes) > 1:
        raise ConversionError('Duplicate graphic stroke')
    stroke = strokes[0] if strokes else None
    if stroke is not None:
        if child(node, 'width') is not None:
            raise ConversionError('Mixed modern/legacy graphic stroke width')
        for entry in stroke[1:]:
            if not isinstance(entry, list) or not entry or entry[0] not in {'type', 'width'}:
                raise ConversionError('Unsupported graphic stroke field/color')
    container = stroke if stroke is not None else node
    for key in ('width', 'type') if stroke is not None else ('width',):
        entries = children(container, key)
        if len(entries) > 1:
            raise ConversionError(f'Duplicate graphic stroke {key}')
        if entries and (len(entries[0]) != 2 or not isinstance(entries[0][1], str)):
            raise ConversionError(f'Malformed graphic stroke {key}')
    style = scalar(stroke, 'type', 'solid') if stroke is not None else 'solid'
    if style not in {'default', 'solid', 'dash', 'dot', 'dash_dot', 'dash_dot_dot'}:
        raise ConversionError(f'Non-solid graphic stroke: unsupported type {style}')
    # EDA_SHAPE::GetLineStyle() resolves DEFAULT to SOLID (KiCad 9.0.0).
    return ('solid' if style == 'default' else style), float(scalar(container, 'width', 0.15))


def stroke_width(node: list) -> float:
    return stroke_settings(node)[1]


def parse_graphic(item: list, tolerance: float, warnings: list[str]) -> Polyline | FilledPolygon | FilledCircle | PatternedGraphic:
    kind, layer = item[0], scalar(item, 'layer', '')
    style, width = stroke_settings(item)
    fill_nodes = children(item, 'fill')
    if len(fill_nodes) > 1 or fill_nodes and (len(fill_nodes[0]) != 2 or not isinstance(fill_nodes[0][1], str)):
        raise ConversionError('Malformed graphic fill')
    fill = fill_nodes[0][1] if fill_nodes else 'no'
    # KiCad's native parser treats the historic yes as a solid fill.
    if fill == 'yes':
        fill = 'solid'
    if fill not in {'no', 'solid'}:
        raise ConversionError(f'Unsupported graphic fill mode: {fill}')
    if style != 'solid' and (fill != 'no' or kind not in {'fp_line', 'fp_rect', 'fp_poly'}):
        raise ConversionError(f'Non-solid graphic stroke: {kind} with fill {fill} is outside the straight unfilled profile')
    if fill == 'solid' and kind not in {'fp_poly', 'fp_rect', 'fp_circle'}:
        raise ConversionError(f'Filled {kind} on {layer} is unsupported')
    if fill == 'solid' and kind == 'fp_circle':
        # Do not sample here: fill width constrains the chord tolerance needed
        # to cover the disk, and is only known in the geometry stage.
        circle = FilledCircle(pair(child(item, 'center')), pair(child(item, 'end')),
                              width, layer)
        if layer in {'F.Fab', 'B.Fab'}:
            warnings.append(f'FAB_LAYER_APPROXIMATED: {layer} exported to FreePCB notes layer')
        if layer in {'Dwgs.User', 'Cmts.User'}:
            warnings.append(f'USER_LAYER_APPROXIMATED: {layer} exported to FreePCB top notes; source layer distinction lost')
        return circle
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
        # Mixed/duplicate arc definitions must never silently select a format.
        for key in ('start', 'mid', 'end', 'angle'):
            nodes = children(item, key)
            if len(nodes) > 1:
                raise ConversionError(f'Duplicate fp_arc {key}')
            if nodes:
                require_atoms(nodes[0], 2 if key == 'angle' else 3, f'fp_arc {key}')
                if len(nodes[0]) != (2 if key == 'angle' else 3):
                    raise ConversionError(f'Malformed fp_arc {key}')
        mid, angle = child(item, 'mid'), child(item, 'angle')
        if mid is not None and angle is not None:
            raise ConversionError('Mixed modern/legacy fp_arc geometry')
        if mid is not None:
            points = arc_points(pair(child(item, 'start')), pair(mid),
                                pair(child(item, 'end')), tolerance)
        elif angle is not None:
            points = legacy_arc_points(pair(child(item, 'start')), pair(child(item, 'end')),
                                       float(angle[1]), tolerance)
        else:
            raise ConversionError('fp_arc requires either mid or legacy angle')
    if kind in {'fp_circle', 'fp_arc'}:
        warnings.append(f'CURVE_APPROXIMATED: {kind} on {layer}, chord error <= {tolerance:g} mm')
    if layer in {'F.Fab', 'B.Fab'}:
        warnings.append(f'FAB_LAYER_APPROXIMATED: {layer} exported to FreePCB notes layer')
    if layer in {'Dwgs.User', 'Cmts.User'}:
        warnings.append(f'USER_LAYER_APPROXIMATED: {layer} exported to FreePCB top notes; source layer distinction lost')
    if fill == 'solid':
        return FilledPolygon(points, width, layer)
    outline = Polyline(points, width, layer, closed)
    if style != 'solid':
        # Do not silently discard extra coordinate fields in the new profile.
        coordinates = children(child(item, 'pts') or [], 'xy') if kind == 'fp_poly' else [child(item, 'start'), child(item, 'end')]
        if any(p is None or len(p) != 3 or any(not isinstance(v, str) for v in p) for p in coordinates):
            raise ConversionError('Malformed patterned graphic coordinates')
        for key in ('start', 'end', 'pts', 'layer'):
            if len(children(item, key)) > 1:
                raise ConversionError(f'Duplicate patterned graphic {key}')
        return PatternedGraphic(kind, style, outline)
    return outline


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
        elif kind == 'fp_text' or kind == 'property' and (
                item[1].lower() in {'reference', 'value'} or child(item, 'at') or child(item, 'effects')):
            fp.texts.append(parse_text(item))
        elif kind in {'fp_line', 'fp_rect', 'fp_circle', 'fp_arc', 'fp_poly'}:
            layer = scalar(item, 'layer', '')
            if layer not in GRAPHIC_LAYERS:
                fp.warnings.append(f'GRAPHIC_LAYER_SKIPPED: {kind} on {layer}')
                continue
            graphic = parse_graphic(item, curve_tolerance, fp.warnings)
            if isinstance(graphic, FilledPolygon):
                fp.filled_polygons.append(graphic)
            elif isinstance(graphic, FilledCircle):
                fp.filled_circles.append(graphic)
            elif isinstance(graphic, PatternedGraphic):
                fp.patterned_graphics.append(graphic)
            else:
                fp.polylines.append(graphic)
        elif kind.startswith('fp_'):
            fp.warnings.append(f'GRAPHIC_SKIPPED: unsupported {kind} on {scalar(item, "layer", "unknown")}')
        elif kind in {'zone', 'rule_area'}:
            fp.warnings.append(f'FEATURE_SKIPPED: unsupported {kind}')
    return fp
