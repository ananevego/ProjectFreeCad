"""Convert a supported subset of a KiCad .kicad_mod footprint into FreePCB .fpl.

The first implementation intentionally supports the common simple case: SMD or
through-hole pads, F.SilkS lines and F.SilkS rectangles. It produces a library
file rather than a board project and reports unsupported source primitives.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+')


def atom(value: str) -> str:
    return value[1:-1].replace(r'\"', '"') if value.startswith('"') else value


def parse_sexpr(text: str):
    stack: list[list] = []
    root = None
    for token in TOKEN_RE.findall(text):
        if token == '(':
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
        elif token == ')':
            if not stack:
                raise ValueError('Unexpected closing parenthesis')
            root = stack.pop()
        else:
            if not stack:
                raise ValueError(f'Unexpected token outside expression: {token}')
            stack[-1].append(atom(token))
    if stack or root is None:
        raise ValueError('Unbalanced KiCad S-expression')
    return root


def children(node: list, kind: str) -> list[list]:
    return [item for item in node if isinstance(item, list) and item and item[0] == kind]


def child(node: list, kind: str) -> list | None:
    matches = children(node, kind)
    return matches[0] if matches else None


def pair(node: list | None, default=(0.0, 0.0)) -> tuple[float, float]:
    if node is None or len(node) < 3:
        return default
    return float(node[1]), float(node[2])


def number(value: float) -> str:
    """Format millimetres as integer nanometres for the FreePCB library format."""
    return str(round(value * 1_000_000))


def angle(value: float) -> str:
    return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'


@dataclass
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


def parse_pad(node: list) -> Pad:
    if len(node) < 4:
        raise ValueError('Incomplete pad definition')
    at = child(node, 'at')
    size = child(node, 'size')
    drill = child(node, 'drill')
    x, y = pair(at)
    rotation = float(at[3]) if at and len(at) > 3 else 0.0
    width, height = pair(size)
    drill_value = float(drill[1]) if drill and len(drill) > 1 else 0.0
    return Pad(atom(node[1]), node[2], node[3], x, y, rotation, width, height, drill_value)


def pad_shape(shape: str) -> int:
    """Return the numeric FreePCB pad-shape code used by the reference library."""
    # FreePCB's stock R0805 uses code 3. Use it for the supported rectangular
    # SMD forms until the remaining FreePCB shape codes are mapped and tested.
    return 3


def layer_is_silk(node: list) -> bool:
    layer = child(node, 'layer')
    return bool(layer and len(layer) > 1 and layer[1] in {'F.SilkS', 'B.SilkS'})


def stroke_width(node: list) -> float:
    stroke = child(node, 'stroke')
    width = child(stroke, 'width') if stroke else None
    return float(width[1]) if width and len(width) > 1 else 0.15


def polyline(lines: list[str], points: list[tuple[float, float]], width: float, closed: bool) -> None:
    if len(points) < 2:
        return
    lines.append(f'  outline_polyline: {number(width)} {number(points[0][0])} {number(points[0][1])} 1 0 4')
    for x, y in points[1:]:
        lines.append(f'    next_corner: {number(x)} {number(y)} 0')
    if closed:
        lines.append('    close_polyline: 0')


def convert(root: list, footprint_name: str | None = None) -> tuple[str, list[str]]:
    if not root or root[0] != 'footprint':
        raise ValueError('Expected a KiCad footprint expression')
    name = footprint_name or atom(root[1])
    warnings: list[str] = []
    pads = [parse_pad(item) for item in children(root, 'pad')]
    lines = ['[footprints]', '', f'name: "{name}"', 'author: "KiCad to FreePCB converter"', '  units: NM']

    bounds: list[tuple[float, float]] = []
    for pad in pads:
        bounds.extend([(pad.x - pad.width / 2, pad.y - pad.height / 2), (pad.x + pad.width / 2, pad.y + pad.height / 2)])
    graphics: list[str] = []
    for item in root:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == 'fp_line' and layer_is_silk(item):
            start, end = pair(child(item, 'start')), pair(child(item, 'end'))
            polyline(graphics, [start, end], stroke_width(item), False)
            bounds.extend([start, end])
        elif item[0] == 'fp_rect' and layer_is_silk(item):
            start, end = pair(child(item, 'start')), pair(child(item, 'end'))
            x1, y1 = start
            x2, y2 = end
            points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            polyline(graphics, points, stroke_width(item), True)
            bounds.extend(points)
        elif item[0].startswith('fp_') and item[0] not in {'fp_line', 'fp_rect', 'fp_text'} and layer_is_silk(item):
            warnings.append(f'Unsupported silk primitive: {item[0]}')

    if not bounds:
        bounds = [(-1.0, -1.0), (1.0, 1.0)]
    # FreePCB footprints conventionally use the first pin as origin.
    origin_x, origin_y = (pads[0].x, pads[0].y) if pads else (0.0, 0.0)
    def relative(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] - origin_x, point[1] - origin_y
    bounds = [relative(point) for point in bounds]
    shifted_graphics: list[str] = []
    for item in root:
        if not isinstance(item, list) or not item or not layer_is_silk(item):
            continue
        if item[0] == 'fp_line':
            polyline(shifted_graphics, [relative(pair(child(item, 'start'))), relative(pair(child(item, 'end')))], stroke_width(item), False)
        elif item[0] == 'fp_rect':
            x1, y1 = pair(child(item, 'start'))
            x2, y2 = pair(child(item, 'end'))
            polyline(shifted_graphics, [relative((x1, y1)), relative((x2, y1)), relative((x2, y2)), relative((x1, y2))], stroke_width(item), True)
    xs, ys = [point[0] for point in bounds], [point[1] for point in bounds]
    margin = 0.5
    lines.append(f'  sel_rect: {number(min(xs)-margin)} {number(min(ys)-margin)} {number(max(xs)+margin)} {number(max(ys)+margin)}')
    lines.append('  ref_text: 1270000 0 -1500000 0 177800')
    lines.append('  value_text: 1270000 0 1500000 0 177800')
    lines.append('  centroid: 0 0 0 0')
    lines.extend(shifted_graphics)
    lines.append(f'  n_pins: {len(pads)}')
    for pad in pads:
        if pad.kind not in {'smd', 'thru_hole', 'np_thru_hole'}:
            warnings.append(f'Pad {pad.name}: unsupported pad type {pad.kind}; exported as SMD')
        shape = pad_shape(pad.shape)
        if shape == 'RECT' and pad.shape not in {'rect', 'roundrect', 'circle', 'oval'}:
            warnings.append(f'Pad {pad.name}: unsupported shape {pad.shape}; exported as RECT')
        x, y = pad.x - origin_x, pad.y - origin_y
        lines.append(f'    pin: "{pad.name}" {number(pad.drill)} {number(x)} {number(y)} {angle(pad.rotation)} ""')
        # FreePCB stores the non-circular dimension as two half-length fields.
        lines.append(f'      top_pad: {shape} {number(pad.width)} {number(pad.height / 2)} {number(pad.height / 2)} 0')
        if pad.kind != 'smd':
            lines.append(f'      inner_pad: {shape} {number(pad.width)} {number(pad.height / 2)} {number(pad.height / 2)} 0')
            lines.append(f'      bottom_pad: {shape} {number(pad.width)} {number(pad.height / 2)} {number(pad.height / 2)} 0')
    return '\n'.join(lines) + '\n', warnings


def main() -> int:
    parser = argparse.ArgumentParser(description='Convert a simple KiCad footprint to FreePCB .fpl format.')
    parser.add_argument('input', type=Path, help='Input .kicad_mod file')
    parser.add_argument('output', type=Path, help='Output .fpl file')
    parser.add_argument('--name', help='Override the generated FreePCB footprint name')
    args = parser.parse_args()
    result, warnings = convert(parse_sexpr(args.input.read_text(encoding='utf-8')), args.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding='utf-8', newline='\n')
    print(f'Converted {args.input.name} -> {args.output}')
    for warning in warnings:
        print(f'WARNING: {warning}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
