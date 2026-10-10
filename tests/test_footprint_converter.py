import importlib.util
import json
import math
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
MODULE = PROJECT / 'src' / 'kicad_to_freepcb_footprint.py'
SPEC = importlib.util.spec_from_file_location('converter', MODULE)
converter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = converter
SPEC.loader.exec_module(converter)
FIXTURE = Path(__file__).parent / 'fixtures' / 'R_0805_2012Metric.kicad_mod'
FIXTURES = FIXTURE.parent
REAL_STL = PROJECT / 'stl_files' / 'Resistor_SMD.3dshapes' / 'R_0805_2012Metric.stl'
TEST_STL_ROOT = None


def decode_fpl(text):
    """Independent structural reader for the emitted 2.428 subset.

    This is a test oracle, not the native FreePCB loader. Enforces record arity,
    name indexing, pin counts and the six-parameter inner_pad contract.
    """
    fields, pins, polys = {}, [], []
    pin, poly = None, None
    arities = {'name': {1}, 'author': {1}, 'package': {1}, 'description': {1},
               'units': {1}, 'sel_rect': {4}, 'ref_text': {5}, 'value_text': {5},
               'centroid': {4}, 'n_pins': {1}, 'pin': {6}, 'text': {8},
               'outline_polyline': {6}, 'next_corner': {3}, 'close_polyline': {1},
               'openscad_code': {1}}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, raw = line.strip().split(':', 1)
        values = shlex.split(raw, posix=True)
        if key.endswith('_pad'):
            assert len(values) == (6 if key == 'inner_pad' else 5), (key, values)
        elif key.endswith('_mask') or key.endswith('_paste'):
            assert len(values) == 5, (key, values)
        else:
            assert key in arities and len(values) in arities[key], (key, values)
        if key == 'name':
            assert line.startswith('name:'), 'Library index needs name at column zero'
        if key == 'pin':
            pin = {'name': values[0], 'hole': int(values[1]), 'x': int(values[2]),
                   'y': int(values[3]), 'angle': int(values[4]), 'description': values[5]}
            pins.append(pin)
        elif key.endswith(('_pad', '_mask', '_paste')):
            assert pin is not None
            pin[key] = tuple(map(int, values))
        elif key == 'outline_polyline':
            width, x, y, visible, hatch, layer = map(int, values)
            poly = {'width': width, 'points': [(x, y)], 'visible': visible,
                    'hatch': hatch, 'layer': layer, 'closed': False}
            polys.append(poly)
        elif key == 'next_corner':
            assert poly is not None
            x, y, style = map(int, values)
            assert style == 0
            poly['points'].append((x, y))
        elif key == 'close_polyline':
            assert poly is not None and values == ['0']
            poly['closed'] = True
        else:
            fields.setdefault(key, []).append(values)
    assert int(fields['n_pins'][0][0]) == len(pins)
    for p in pins:
        assert 'top_pad' in p, 'Avoid the native default round pad'
        for key in ('top_pad', 'bottom_pad', 'inner_pad'):
            if key in p:
                shape, size_y, left, right, radius = p[key][:5]
                assert shape in range(7) and min(size_y, left, right, radius) >= 0
                assert radius <= min(size_y / 2, (left + right) / 2)
    return fields, pins, polys


def source_pad(shape='rect', kind='smd', layers='"F.Cu" "F.Mask" "F.Paste"',
               size='1.025 1.4', at='-0.9125 0', name='1', extra=''):
    return f'(pad "{name}" {kind} {shape} (at {at}) (size {size}) (layers {layers}) {extra})'


def convert_body(body, **kwargs):
    kwargs.setdefault('stl_root', TEST_STL_ROOT)
    return converter.convert(converter.parse_sexpr(f'(footprint "Demo" {body})'), **kwargs)


def polygon_body(points, width=0, layer='F.SilkS', fill='solid'):
    vertices = ' '.join(f'(xy {x} {y})' for x, y in points)
    return f'(fp_poly (pts {vertices}) (stroke (width {width})) (fill {fill}) (layer "{layer}"))'


def circle_body(center=(0, 0), end=(1, 0), width=0, layer='F.SilkS', fill='solid'):
    return (f'(fp_circle (center {center[0]} {center[1]}) (end {end[0]} {end[1]}) '
            f'(stroke (width {width}) (type solid)) (fill {fill}) (layer "{layer}"))')


def segment_distance(point, a, b):
    # Independent distance oracle for ideal round-ended output strokes.
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0, min(1, ((point[0]-a[0])*dx + (point[1]-a[1])*dy) / (dx*dx+dy*dy))) if dx or dy else 0
    return math.dist(point, (a[0]+t*dx, a[1]+t*dy))


def inside_polygon(point, points):
    inside = False
    for a, b in zip(points, points[1:] + points[:1]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if point[0] < x:
                inside = not inside
    return inside


def stroke_contains(point, polys):
    for poly in polys:
        points = [(x / 1e6, y / 1e6) for x, y in poly['points']]
        end = points[1:] + points[:1] if poly['closed'] else points[1:]
        if any(segment_distance(point, a, b) <= poly['width'] / 2e6 + 1e-10
               for a, b in zip(points, end)):
            return True
    return False


class FootprintConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Unit tests need only file metadata, never a real mesh. The actual
        # repository STL is checked separately by the optional integration test.
        global TEST_STL_ROOT
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        TEST_STL_ROOT = Path(directory.name)
        model = TEST_STL_ROOT / 'Resistor_SMD.3dshapes' / 'R_0805_2012Metric.stl'
        model.parent.mkdir()
        model.write_bytes(b'metadata-only test fixture, not STL geometry')
        header = TEST_STL_ROOT / 'Connector_PinHeader_2.54mm.3dshapes' / 'PinHeader_1x03_P2.54mm_Vertical.stl'
        header.parent.mkdir()
        header.write_bytes(b'metadata-only test fixture, not STL geometry')
        sot = TEST_STL_ROOT / 'Package_TO_SOT_SMD.3dshapes' / 'SOT-23.stl'
        sot.parent.mkdir()
        sot.write_bytes(b'metadata-only test fixture, not STL geometry')

    def test_modular_api_accepts_shared_records_and_matches_legacy_conversion(self):
        from src import footprint_converter as api
        from src.footprint_converter.model import ApertureSettings, Footprint
        from src.footprint_converter.parser import parse_footprint, parse_sexpr
        from src.footprint_converter.validation import validate_footprint
        from src.footprint_converter.model_matching import match_models
        from src.footprint_converter.writer import write_fpl

        root = parse_sexpr(FIXTURE.read_text(encoding='utf-8'))
        defaults = ApertureSettings(0.05, 0, 0)
        fp = parse_footprint(root)
        self.assertIsInstance(fp, Footprint)
        self.assertIsInstance(fp, converter.Footprint)
        warnings = validate_footprint(fp)
        matches = match_models(fp.models, TEST_STL_ROOT, warnings)
        written = write_fpl(fp, matches, warnings, aperture_defaults=defaults)
        legacy = converter.convert_detailed(root, stl_root=TEST_STL_ROOT,
                                             aperture_defaults=defaults)
        modular = api.convert_detailed(root, stl_root=TEST_STL_ROOT,
                                       aperture_defaults=defaults)
        self.assertEqual(written, legacy.fpl)
        self.assertEqual(modular, legacy)
        self.assertEqual(api.convert(root, stl_root=TEST_STL_ROOT),
                         converter.convert(root, stl_root=TEST_STL_ROOT))

    def test_cli_entrypoints_preserve_outputs_reports_and_exit_codes(self):
        entries = [[str(MODULE)], ['-m', 'src.kicad_to_freepcb_footprint'],
                   ['-m', 'src.footprint_converter']]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            invalid = base / 'invalid.kicad_mod'
            invalid.write_text('(footprint "Broken"', encoding='utf-8')
            output, report = base / 'result.fpl', base / 'report.json'
            for source, flags, exit_code, status in (
                    (FIXTURE, [], 0, 'generated_with_loss'),
                    (invalid, [], 1, 'failed'),
                    (FIXTURE, ['--strict'], 2, 'rejected_loss')):
                outcomes = []
                for entry in entries:
                    with self.subTest(entry=entry, exit_code=exit_code):
                        output.write_bytes(b'previous library')
                        report.unlink(missing_ok=True)
                        result = subprocess.run(
                            [sys.executable, '-B', *entry, str(source), str(output),
                             '--stl-root', str(TEST_STL_ROOT), '--report', str(report), *flags],
                            cwd=PROJECT, capture_output=True, text=True)
                        self.assertEqual(result.returncode, exit_code, result.stderr)
                        metadata = json.loads(report.read_text(encoding='utf-8'))
                        self.assertEqual(metadata['status'], status)
                        if exit_code == 0:
                            self.assertEqual(len(decode_fpl(output.read_text(encoding='cp1251'))[1]), 2)
                            self.assertFalse(metadata['target']['gui_validated'])
                        else:
                            self.assertEqual(output.read_bytes(), b'previous library')
                        outcomes.append((output.read_bytes(), metadata, result.stdout, result.stderr))
                self.assertEqual(outcomes[0], outcomes[1])
                self.assertEqual(outcomes[0], outcomes[2])

    def test_absolute_legacy_cli_works_outside_repository(self):
        expected, _ = converter.convert(converter.parse_sexpr(FIXTURE.read_text(encoding='utf-8')),
                                        stl_root=TEST_STL_ROOT)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.fpl'
            result = subprocess.run(
                [sys.executable, '-B', str(MODULE), str(FIXTURE), str(output),
                 '--stl-root', str(TEST_STL_ROOT)], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), expected.encode('cp1251'))

    def test_importlib_legacy_api_works_outside_repository(self):
        script = '''
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('external_converter', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
result = module.convert_detailed(module.parse_sexpr(Path(sys.argv[2]).read_text(encoding='utf-8')),
                                 stl_root=Path(sys.argv[3]))
print(json.dumps({'fpl': result.fpl, 'warnings': result.warnings, 'report': result.report,
                  'default_root': str(module.DEFAULT_STL_ROOT)}))
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-B', '-c', script, str(MODULE), str(FIXTURE), str(TEST_STL_ROOT)],
                cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        expected = converter.convert_detailed(converter.parse_sexpr(FIXTURE.read_text(encoding='utf-8')),
                                              stl_root=TEST_STL_ROOT)
        self.assertEqual(actual['fpl'], expected.fpl)
        self.assertEqual(actual['warnings'], expected.warnings)
        # JSON serialization turns tuple coordinates into arrays.
        self.assertEqual(actual['report'], json.loads(json.dumps(expected.report)))
        self.assertEqual(Path(actual['default_root']), PROJECT / 'stl_files')

    def test_r0805_complete_structure_and_values(self):
        root = converter.parse_sexpr(FIXTURE.read_text())
        result, warnings = converter.convert(root, stl_root=TEST_STL_ROOT)
        fields, pads, polys = decode_fpl(result)
        self.assertEqual(fields['name'], [['R_0805_2012Metric']])
        self.assertEqual(fields['units'], [['NM']])
        self.assertEqual(len(pads), 2)
        self.assertEqual([(p['name'], p['x'], p['y'], p['hole']) for p in pads],
                         [('1', -912500, 0, 0), ('2', 912500, 0, 0)])
        for p in pads:
            # shape, size_Y, X/2, X/2, radius: X=1.025; Y=1.4 mm.
            self.assertEqual(p['top_pad'], (4, 1400000, 512500, 512500, 250000))
            self.assertEqual(p['bottom_pad'], (0, 0, 0, 0, 0))
            self.assertEqual(p['top_mask'][0], 99)
            self.assertEqual(p['top_paste'][0], 99)
            self.assertEqual(p['bottom_mask'][0], 0)
            self.assertNotIn('inner_pad', p)
        self.assertEqual(fields['ref_text'], [['1000000', '0', '1650000', '0', '150000']])
        self.assertEqual(fields['value_text'], [['1000000', '0', '-1650000', '0', '150000']])
        self.assertNotIn('centroid', fields)  # Native loader computes pad-bounds centre.
        silk = [p for p in polys if p['layer'] == 4]
        self.assertEqual([p['points'] for p in silk],
                         [[(-227060, 735000), (227060, 735000)],
                          [(-227060, -735000), (227060, -735000)]])
        self.assertEqual([p['width'] for p in silk], [120000, 120000])
        self.assertNotIn('text', fields)  # Unresolved dynamic reference is not a literal label.
        self.assertTrue(any(w.startswith('TEXT_VARIABLE_UNRESOLVED:') for w in warnings))
        code = [row[0] for row in fields['openscad_code']]
        self.assertEqual(code[0], 'translate([0,0,0]) // (automatic adjustment when moving the footprint origin)')
        self.assertEqual(code[1], 'scale([1,1,1]) // (automatic adjustment when changing the project units)')
        self.assertEqual(code[-2:], ['  import(`R_0805_2012Metric.stl`);', '}'])
        self.assertTrue(any(w.startswith('MODEL_FRAME_UNVERIFIED:') for w in warnings))
        self.assertFalse(any(w.startswith('MODEL_MISSING:') for w in warnings))

    def test_shape_mapping(self):
        for shape, code, size, extra, radius in [
            ('circle', 1, '1 1', '', 0), ('rect', 3, '1 2', '', 0),
            ('oval', 5, '1 2', '', 0),
            ('roundrect', 4, '1 2', '(roundrect_rratio 0.2)', 200000)]:
            with self.subTest(shape=shape):
                result, _ = convert_body(source_pad(shape=shape, size=size, extra=extra))
                pad = decode_fpl(result)[1][0]
                self.assertEqual(pad['top_pad'], (code, int(size.split()[1])*1000000,
                                                  500000, 500000, radius))

    def test_bottom_smd_no_default_top_copper(self):
        result, _ = convert_body(source_pad(layers='"B.Cu" "B.Mask" "B.Paste"', at='2 3 30'))
        pad = decode_fpl(result)[1][0]
        self.assertEqual((pad['x'], pad['y'], pad['angle']), (2000000, -3000000, 330))
        self.assertEqual(pad['top_pad'], (0, 0, 0, 0, 0))
        self.assertEqual(pad['bottom_pad'], (3, 1400000, 512500, 512500, 0))
        self.assertEqual(pad['top_mask'][0], 0)
        self.assertEqual(pad['bottom_mask'][0], 99)

    def test_pth_all_copper_with_six_parameter_inner_pad(self):
        result, _ = convert_body(source_pad(kind='thru_hole', shape='oval', size='2 3',
                                           layers='"*.Cu" "*.Mask"', extra='(drill 0.8)'))
        pad = decode_fpl(result)[1][0]
        self.assertEqual(pad['hole'], 800000)
        self.assertEqual(pad['top_pad'], (5, 3000000, 1000000, 1000000, 0))
        self.assertEqual(pad['bottom_pad'], pad['top_pad'])
        self.assertEqual(pad['inner_pad'], (*pad['top_pad'], 0))
        self.assertEqual(pad['top_paste'][0], 0)

    def test_pth_outer_only_does_not_invent_inner_copper(self):
        result, _ = convert_body(source_pad(kind='thru_hole', layers='"F.Cu" "B.Cu"', extra='(drill 0.5)'))
        self.assertEqual(decode_fpl(result)[1][0]['inner_pad'], (0, 0, 0, 0, 0, 0))

    def test_real_pinheader_pth_geometry_apertures_and_disabled_layer_removal(self):
        root = converter.parse_sexpr((FIXTURES / 'PinHeader_1x03_P2.54mm_Vertical.kicad_mod').read_text())
        result = converter.convert_detailed(root, stl_root=TEST_STL_ROOT,
                    aperture_defaults=converter.ApertureSettings(0.05, 0, 0))
        fields, pads, polys = decode_fpl(result.fpl)
        self.assertEqual(fields['name'], [['PinHeader_1x03_P2.54mm_Vertical']])
        self.assertEqual([(p['name'], p['x'], p['y'], p['hole']) for p in pads],
                         [('1', 0, 0, 1000000), ('2', 0, -2540000, 1000000),
                          ('3', 0, -5080000, 1000000)])
        for pad, shape in zip(pads, [3, 1, 1]):
            expected = (shape, 1700000, 850000, 850000, 0)
            self.assertEqual(pad['top_pad'], expected)
            self.assertEqual(pad['bottom_pad'], expected)
            self.assertEqual(pad['inner_pad'], (*expected, 0))
            mask = (4 if shape == 3 else 1, 1800000, 900000, 900000,
                    50000 if shape == 3 else 0)
            self.assertEqual(pad['top_mask'], mask)
            self.assertEqual(pad['bottom_mask'], mask)
            self.assertEqual(pad['top_paste'], (0, 0, 0, 0, 0))
            self.assertEqual(pad['bottom_paste'], (0, 0, 0, 0, 0))
        self.assertNotIn('centroid', fields)
        self.assertTrue(any(p['layer'] == 4 for p in polys))
        self.assertFalse(result.report['target']['gui_validated'])

    def test_real_mounting_hole_npth_and_mechanical_outline(self):
        root = converter.parse_sexpr((FIXTURES / 'MountingHole_3.2mm_M3.kicad_mod').read_text())
        result = converter.convert_detailed(root, stl_root=TEST_STL_ROOT)
        fields, pads, polys = decode_fpl(result.fpl)
        self.assertEqual(len(pads), 1)
        self.assertEqual((pads[0]['name'], pads[0]['x'], pads[0]['y'], pads[0]['hole']),
                         ('__NPTH_1', 0, 0, 3200000))
        for key in ('top_pad', 'bottom_pad', 'top_paste', 'bottom_paste'):
            self.assertEqual(pads[0][key], (0, 0, 0, 0, 0))
        self.assertEqual(pads[0]['inner_pad'], (0, 0, 0, 0, 0, 0))
        self.assertEqual(pads[0]['top_mask'], (1, 3200000, 1600000, 1600000, 0))
        self.assertEqual(pads[0]['bottom_mask'], pads[0]['top_mask'])
        self.assertNotIn('centroid', fields)
        self.assertEqual(len(polys), 1)
        self.assertEqual((polys[0]['layer'], polys[0]['width'], polys[0]['closed']), (7, 150000, True))
        points = [(x / 1e6, y / 1e6) for x, y in polys[0]['points']]
        for a, b in zip(points, points[1:] + points[:1]):
            midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            self.assertLessEqual(abs(3.2 - math.hypot(*midpoint)), 0.01)
        severity = {d['code']: d['severity'] for d in result.report['diagnostics']}
        self.assertEqual(severity['USER_LAYER_APPROXIMATED'], 'loss')
        self.assertEqual(severity['CURVE_APPROXIMATED'], 'approximation')
        self.assertIn('MODEL_MISSING', severity)  # Official hole has no 3D reference.

    def test_real_r0805_front_and_explicit_bottom_layer_variant(self):
        source = FIXTURE.read_text()
        # This is a layer-routing variant, not a KiCad GUI flip or a 3D oracle.
        for side, text in [('top', source), ('bottom', source.replace('"F.', '"B.'))]:
            with self.subTest(side=side):
                result = converter.convert_detailed(converter.parse_sexpr(text), stl_root=TEST_STL_ROOT,
                              aperture_defaults=converter.ApertureSettings(0.05, -0.025, 0))
                fields, pads, polys = decode_fpl(result.fpl)
                self.assertEqual([(p['name'], p['x'], p['y']) for p in pads],
                                 [('1', -912500, 0), ('2', 912500, 0)])
                opposite = 'bottom' if side == 'top' else 'top'
                for pad in pads:
                    self.assertEqual(pad['hole'], 0)
                    self.assertEqual(pad[side + '_pad'], (4, 1400000, 512500, 512500, 250000))
                    self.assertEqual(pad[side + '_mask'], (4, 1500000, 562500, 562500, 300000))
                    self.assertEqual(pad[side + '_paste'], (4, 1350000, 487500, 487500, 225000))
                    for suffix in ('pad', 'mask', 'paste'):
                        self.assertEqual(pad[opposite + '_' + suffix], (0, 0, 0, 0, 0))
                silk = [p for p in polys if p['layer'] in {4, 5}]
                self.assertTrue(silk)
                self.assertEqual({p['layer'] for p in silk}, {4 if side == 'top' else 5})
                self.assertEqual(result.report['counts']['source_pads'], 2)

    def test_real_sot23_filled_marker_and_pad_geometry_on_both_sides(self):
        source = (FIXTURES / 'SOT-23.kicad_mod').read_text()
        for side, text in [('F', source), ('B', source.replace('"F.', '"B.'))]:
            with self.subTest(side=side):
                result = converter.convert_detailed(converter.parse_sexpr(text), stl_root=TEST_STL_ROOT,
                               aperture_defaults=converter.ApertureSettings(0.05, -0.025, 0))
                fields, pads, polys = decode_fpl(result.fpl)
                copper, opposite, layer = ('top', 'bottom', 4) if side == 'F' else ('bottom', 'top', 5)
                self.assertEqual([(p['name'], p['x'], p['y'], p['hole']) for p in pads],
                                 [('1', -937500, 950000, 0), ('2', -937500, -950000, 0),
                                  ('3', 937500, 0, 0)])
                for pad in pads:
                    self.assertEqual(pad[copper + '_pad'], (4, 600000, 737500, 737500, 150000))
                    self.assertEqual(pad[copper + '_mask'], (4, 700000, 787500, 787500, 200000))
                    self.assertEqual(pad[copper + '_paste'], (4, 550000, 712500, 712500, 125000))
                    for suffix in ('pad', 'mask', 'paste'):
                        self.assertEqual(pad[opposite + '_' + suffix], (0, 0, 0, 0, 0))
                boundary = [p for p in polys if p['layer'] == layer and p['closed']]
                self.assertEqual(len(boundary), 1)
                self.assertEqual(boundary[0]['points'], [(-1300000, 380000), (-1060000, 50000), (-1540000, 50000)])
                self.assertEqual((boundary[0]['width'], boundary[0]['hatch']), (120000, 0))
                scanlines = [p for p in polys if p['layer'] == layer and not p['closed'] and
                             p['points'][0][1] == p['points'][1][1] and 50000 < p['points'][0][1] < 380000]
                self.assertEqual(len(scanlines), 6)
                self.assertEqual(scanlines[0]['points'], [(-1320000, 352500), (-1280000, 352500)])
                self.assertEqual(scanlines[-1]['points'], [(-1520000, 77500), (-1080000, 77500)])
                self.assertTrue(all(p['width'] == 120000 and p['hatch'] == 0 for p in scanlines))
                self.assertEqual(result.report['fills']['written_scanline_polylines'], 6)
                self.assertEqual(result.report['counts']['source_filled_polygons'], 1)
                self.assertEqual(result.report['fills']['source_polygons'][0]['layer'], side + '.SilkS')
                self.assertFalse(result.report['fills']['manufacturing_validated'])
                self.assertEqual(fields['openscad_code'][-2], ['  import(`SOT-23.stl`);'])
                self.assertNotIn('centroid', fields)

    def test_disabled_padstack_flags_do_not_reject_and_enabled_flags_fail(self):
        for key in ('remove_unused_layers', 'keep_end_layers'):
            with self.subTest(key=key):
                normal, _ = convert_body(source_pad(kind='thru_hole', extra='(drill 0.5)'))
                disabled, _ = convert_body(source_pad(kind='thru_hole', extra=f'(drill 0.5) ({key} no)'))
                self.assertEqual(decode_fpl(disabled)[1], decode_fpl(normal)[1])
                for value in ('', ' yes', ' maybe', ' no extra', ' (no)'):
                    with self.subTest(value=value), self.assertRaises(converter.ConversionError):
                        convert_body(source_pad(kind='thru_hole', extra=f'(drill 0.5) ({key}{value})'))
                with self.assertRaisesRegex(converter.ConversionError, 'duplicate'):
                    convert_body(source_pad(kind='thru_hole', extra=f'(drill 0.5) ({key} no) ({key} yes)'))

    def test_user_graphics_and_texts_keep_notes_and_report_layer_loss(self):
        result, warnings = convert_body(source_pad() + '''
            (fp_line (start 1 2) (end 3 4) (width 0.1) (layer "Dwgs.User"))
            (fp_text user "mechanical" (at 1 2) (layer "Cmts.User")
              (effects (font (size 1 1) (thickness 0.1))))''')
        fields, _, polys = decode_fpl(result)
        self.assertEqual(polys[0]['layer'], 7)
        self.assertEqual(polys[0]['points'], [(1000000, -2000000), (3000000, -4000000)])
        self.assertEqual(fields['text'][0], ['mechanical', '1000000', '1000000', '-2000000', '0', '100000', '0', '7'])
        self.assertTrue(any(w.startswith('USER_LAYER_APPROXIMATED:') for w in warnings))
        with self.assertRaises(converter.LossyConversionError) as caught:
            convert_body(source_pad() + '''
                (fp_line (start 1 2) (end 3 4) (width 0.1) (layer "Dwgs.User"))''', strict=True)
        self.assertIn('USER_LAYER_APPROXIMATED', str(caught.exception))

    @unittest.skipUnless((PROJECT / 'stl_files' / 'Connector_PinHeader_2.54mm.3dshapes' /
                         'PinHeader_1x03_P2.54mm_Vertical.stl').is_file(),
                        'Optional integration: existing PinHeader STL unavailable')
    def test_real_pinheader_model_metadata_binding_without_geometry(self):
        root = converter.parse_sexpr((FIXTURES / 'PinHeader_1x03_P2.54mm_Vertical.kicad_mod').read_text())
        path = PROJECT / 'stl_files' / 'Connector_PinHeader_2.54mm.3dshapes' / 'PinHeader_1x03_P2.54mm_Vertical.stl'
        before = path.stat()
        with patch.object(Path, 'open', side_effect=AssertionError('Do not read STL geometry')):
            result = converter.convert_detailed(root)
        after = path.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino),
                         (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino))
        self.assertEqual(result.report['models'][0]['relative_stl'],
                         'Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x03_P2.54mm_Vertical.stl')
        self.assertEqual(result.report['models'][0]['existing_stl'], str(path.resolve()))
        code = decode_fpl(result.fpl)[0]['openscad_code']
        self.assertEqual(code[-2], ['  import(`PinHeader_1x03_P2.54mm_Vertical.stl`);'])
        self.assertFalse(result.report['models'][0]['frame_validated'])

    def test_invalid_filled_polygon_cli_keeps_previous_library_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            destination, report = Path(temp) / 'previous.fpl', Path(temp) / 'failure.json'
            source = Path(temp) / 'invalid.kicad_mod'
            source.write_text('(footprint Invalid ' + source_pad() +
                              polygon_body([(0, 0), (1, 1), (0, 1), (1, 0)]) + ')')
            destination.write_bytes(b'previous library')
            result = subprocess.run([sys.executable, '-B', str(MODULE),
                         str(source), str(destination), '--report', str(report)],
                         capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(destination.read_bytes(), b'previous library')
            data = json.loads(report.read_text())
            self.assertEqual(data['status'], 'failed')
            self.assertIn('self-intersecting', str(data['errors']))

    def test_saved_small_sample_outputs_are_reproducible(self):
        for name in ('PinHeader_1x03_P2.54mm_Vertical', 'MountingHole_3.2mm_M3', 'SOT-23'):
            with self.subTest(name=name):
                root = converter.parse_sexpr((FIXTURES / (name + '.kicad_mod')).read_text())
                result = converter.convert_detailed(root, stl_root=TEST_STL_ROOT,
                              aperture_defaults=converter.ApertureSettings(0.05, -0.025 if name == 'SOT-23' else 0, 0))
                saved = (PROJECT / 'output' / (name + '.fpl')).read_text(encoding='cp1251')
                self.assertEqual(saved, result.fpl)
                decode_fpl(saved)

    def test_npth_is_hole_without_copper_or_paste(self):
        result, warnings = convert_body(source_pad(kind='np_thru_hole', shape='circle',
                                                  size='2 2', name='', layers='"*.Cu" "*.Mask"', extra='(drill 2)'))
        pad = decode_fpl(result)[1][0]
        self.assertEqual(pad['hole'], 2000000)
        self.assertEqual(pad['name'], '__NPTH_1')
        for key in ('top_pad', 'bottom_pad', 'inner_pad', 'top_paste', 'bottom_paste'):
            self.assertEqual(pad[key][0], 0)
        self.assertTrue(any(w.startswith('NPTH_LIMIT:') for w in warnings))

    def test_silk_sides_old_and_new_width_and_coordinates(self):
        body = source_pad() + '''
          (fp_line (start 1 2) (end 3 4) (width 0.2) (layer "F.SilkS"))
          (fp_rect (start -1 -2) (end 1 2) (stroke (width 0.1)) (layer "B.SilkS"))'''
        polys = decode_fpl(convert_body(body)[0])[2]
        self.assertEqual(polys[0]['layer'], 4)
        self.assertEqual(polys[0]['points'], [(1000000, -2000000), (3000000, -4000000)])
        self.assertEqual(polys[0]['width'], 200000)
        self.assertEqual(polys[1]['layer'], 5)
        self.assertTrue(polys[1]['closed'])

    def test_texts_are_not_constants_and_hidden_field_stays_hidden(self):
        body = source_pad() + '''
          (fp_text reference "R?" (at 2 -3 90) (layer "F.SilkS")
            (effects (font (size 0.8 0.8) (thickness 0.1))))
          (fp_text value "custom" (at 4 5) (layer "F.Fab") hide
            (effects (font (size 0.6 0.6) (thickness 0.07))))
          (fp_text user "bottom label" (at -2 3 45) (layer "B.SilkS")
            (effects (font (size 0.7 0.7) (thickness 0.08)) (justify mirror)))'''
        fields = decode_fpl(convert_body(body)[0])[0]
        self.assertEqual(fields['ref_text'][0], ['800000', '2000000', '3000000', '270', '100000'])
        self.assertEqual(fields['value_text'][0], ['0', '4000000', '-5000000', '0', '70000'])
        self.assertEqual(fields['text'][0], ['bottom label', '700000', '-2000000', '-3000000', '315', '80000', '1', '5'])

    def test_no_first_pad_origin_translation_or_forced_centroid(self):
        body = source_pad(at='2 3', name='1') + source_pad(at='4 5', name='2')
        fields, pads, _ = decode_fpl(convert_body(body)[0])
        self.assertEqual([(p['x'], p['y']) for p in pads], [(2000000, -3000000), (4000000, -5000000)])
        self.assertNotIn('centroid', fields)  # Actual pad-bounds centre is (3,-4), not (0,0).

    def test_missing_model_reports_and_does_not_import(self):
        with tempfile.TemporaryDirectory() as temp:
            body = source_pad() + '(model "${KICAD10_3DMODEL_DIR}/Missing.3dshapes/Absent.step")'
            result, warnings = convert_body(body, stl_root=Path(temp))
        self.assertNotIn('openscad_code', decode_fpl(result)[0])
        self.assertTrue(any(w.startswith('MODEL_MISSING: Missing.3dshapes/Absent.stl') for w in warnings))

    @unittest.skipUnless(REAL_STL.is_file(), 'Optional integration: existing R0805 STL unavailable')
    def test_real_stl_match_without_opening_or_changing_it(self):
        before = REAL_STL.stat()
        ref = converter.ModelReference('${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.step')
        with patch.object(Path, 'open', side_effect=AssertionError('Do not read STL geometry')):
            matches = converter.match_models([ref], PROJECT / 'stl_files', [])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].stl_path, REAL_STL.resolve())
        self.assertEqual(str(matches[0].relative_path), 'Resistor_SMD.3dshapes/R_0805_2012Metric.stl')
        after = REAL_STL.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino),
                         (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino))

    def test_same_basename_in_wrong_category_is_not_matched(self):
        ref = converter.ModelReference('${KICAD10_3DMODEL_DIR}/Wrong.3dshapes/R_0805_2012Metric.step')
        warnings = []
        self.assertEqual(converter.match_models([ref], PROJECT / 'stl_files', warnings), [])
        self.assertTrue(warnings[0].startswith('MODEL_MISSING:'))

    def test_model_frame_override_is_separate_and_explicit(self):
        body = source_pad() + '(model "Resistor_SMD.3dshapes/R_0805_2012Metric.step" (offset (xyz 1 2 3)))'
        with self.assertRaisesRegex(converter.ConversionError, 'explicit target ModelTransform'):
            convert_body(body)
        result, warnings = convert_body(body, model_transform=converter.ModelTransform((1, 2, 3), (0, 0, 90)))
        code = [row[0] for row in decode_fpl(result)[0]['openscad_code']]
        self.assertEqual(code[3:6], ['  translate([1,2,3])', '  rotate([0,0,90])', '  scale([1,1,1])'])
        self.assertTrue(any(w.startswith('MODEL_TRANSFORM_OVERRIDE:') for w in warnings))

    def test_selected_inner_layers_rejected_instead_of_all_inner(self):
        for kind, extra in [('smd', ''), ('thru_hole', '(drill 0.5)')]:
            with self.subTest(kind=kind), self.assertRaisesRegex(converter.ConversionError, 'inner copper'):
                convert_body(source_pad(kind=kind, layers='"F.Cu" "In1.Cu"', extra=extra))

    def test_unsupported_copper_shapes_and_drills_fail_explicitly(self):
        cases = [source_pad(shape='custom'), source_pad(shape='trapezoid'),
                 source_pad(shape='circle', size='1 2'), source_pad(shape='roundrect'),
                 source_pad(extra='(chamfer_ratio 0.1)'),
                 source_pad(kind='thru_hole', extra='(drill oval 1 2)'),
                 source_pad(kind='thru_hole', extra='(drill 1 (offset 0.2 0))'),
                 source_pad(at='0 0 12.5'), source_pad(kind='connect'),
                 source_pad(size='-1 2'), source_pad(layers='"F.Mask"'),
                 source_pad(size='0.000001 1'), source_pad(at='3000 0')]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(converter.ConversionError):
                convert_body(source)

    def test_no_model_reference_does_not_guess_from_footprint_name(self):
        result, warnings = convert_body(source_pad(), footprint_name='R_0805_2012Metric')
        self.assertNotIn('openscad_code', decode_fpl(result)[0])
        self.assertTrue(any('no basename guessing' in w for w in warnings))

    def test_unknown_graphic_is_reported(self):
        result, warnings = convert_body(source_pad() + '(fp_curve (layer "B.SilkS"))')
        decode_fpl(result)
        self.assertTrue(any(w.startswith('GRAPHIC_SKIPPED:') for w in warnings))

    def test_legacy_module_root(self):
        root = converter.parse_sexpr('(module Demo ' + source_pad() + ')')
        self.assertEqual(decode_fpl(converter.convert(root)[0])[0]['name'], [['Demo']])

    def test_parser_rejects_multiple_roots_and_unbalanced_input(self):
        for text in ['(footprint A)(footprint B)', '(footprint A', ')', '(footprint "A)']:
            with self.subTest(text=text), self.assertRaises(converter.ConversionError):
                converter.parse_sexpr(text)

    def test_cli_writes_one_library_and_errors_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'R0805.fpl'
            command = [sys.executable, '-B', str(MODULE), str(FIXTURE), str(destination),
                       '--stl-root', str(TEST_STL_ROOT)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected, _ = converter.convert(converter.parse_sexpr(FIXTURE.read_text()), stl_root=TEST_STL_ROOT)
            self.assertEqual(destination.read_text(encoding='cp1251'), expected)
            decode_fpl(expected)
            invalid = Path(temp) / 'bad.kicad_mod'
            invalid.write_text('(footprint Bad ' + source_pad(shape='custom') + ')')
            result = subprocess.run([sys.executable, '-B', str(MODULE), str(invalid), str(destination)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(destination.read_text(encoding='cp1251'), expected)
            self.assertIn('Unsupported KiCad pad shape', result.stderr)

    def test_cli_refuses_output_in_existing_model_storage(self):
        result = subprocess.run([sys.executable, '-B', str(MODULE), str(FIXTURE), str(REAL_STL)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Output cannot be inside model storage', result.stderr)

    def test_saved_r0805_is_reproducible(self):
        expected, _ = converter.convert(converter.parse_sexpr(FIXTURE.read_text()), stl_root=TEST_STL_ROOT)
        saved = (PROJECT / 'output' / 'R_0805_2012Metric.fpl').read_text(encoding='cp1251')
        self.assertEqual(saved, expected)
        decode_fpl(saved)

    def test_circle_tessellation_bounds_chord_error_and_layer(self):
        body = source_pad() + '''(fp_circle (center 2 3) (end 3 3)
            (stroke (width 0.12)) (fill no) (layer "B.SilkS"))'''
        result, warnings = convert_body(body, curve_tolerance=0.005)
        poly = decode_fpl(result)[2][0]
        self.assertEqual(poly['layer'], 5)
        self.assertEqual(poly['width'], 120000)
        self.assertTrue(poly['closed'])
        points = [(x / 1e6, y / 1e6) for x, y in poly['points']]
        self.assertGreater(len(points), 8)
        for a, b in zip(points, points[1:] + points[:1]):
            midpoint = ((a[0]+b[0])/2, (a[1]+b[1])/2)
            error = abs(1 - math.dist(midpoint, (2, -3)))
            self.assertLessEqual(error, 0.005)
        self.assertTrue(any(w.startswith('CURVE_APPROXIMATED:') for w in warnings))

    def test_arc_keeps_direction_endpoints_and_major_sweep(self):
        for mid, end, expected_sign in [('0 1', '-1 0', -1), ('-1 0', '0 1', 1)]:
            with self.subTest(mid=mid):
                body = source_pad() + f'''(fp_arc (start 1 0) (mid {mid}) (end {end})
                    (stroke (width 0.1)) (layer "F.SilkS"))'''
                poly = decode_fpl(convert_body(body)[0])[2][0]
                self.assertFalse(poly['closed'])
                self.assertEqual(poly['points'][0], (1000000, 0))
                self.assertEqual(poly['points'][-1], tuple(int(float(v)*1e6) * sign
                                                         for v, sign in zip(end.split(), [1, -1])))
                self.assertGreater(poly['points'][1][1] * expected_sign, 0)
                for a, b in zip(poly['points'], poly['points'][1:]):
                    midpoint = ((a[0]+b[0])/2e6, (a[1]+b[1])/2e6)
                    self.assertLessEqual(abs(1 - math.hypot(*midpoint)), 0.01)

    def test_polygon_is_closed_and_preserves_all_corners(self):
        body = source_pad() + '''(fp_poly (pts (xy 0 0) (xy 2 0) (xy 1 2) (xy 0 0))
            (stroke (width 0.1)) (fill no) (layer "F.SilkS"))'''
        poly = decode_fpl(convert_body(body)[0])[2][0]
        self.assertEqual(poly['points'], [(0, 0), (2000000, 0), (1000000, -2000000)])
        self.assertTrue(poly['closed'])

    def test_filled_graphics_preserve_internal_geometry_before_tessellation(self):
        body = source_pad() + polygon_body([(0, 0), (1, 0), (0, 1)], width=0)
        fp = converter.parse_footprint(converter.parse_sexpr('(footprint Demo ' + body + ')'))
        self.assertEqual(fp.polylines, [])
        self.assertEqual(fp.filled_polygons[0].points, ((0, 0), (1, 0), (0, 1)))
        self.assertEqual(fp.filled_polygons[0].width, 0)
        rendered = converter.tessellate_fills(fp, 0.01, [])
        self.assertEqual(rendered.filled_polygons, [])
        self.assertTrue(rendered.polylines)
        self.assertEqual(len(fp.filled_polygons), 1)  # Input model was not mutated.

    def test_filled_polygon_coverage_and_expansion_bound(self):
        # Dense interior/exterior probes use point-in-polygon and distance-to-
        # segment oracles, not the converter's row intersection implementation.
        shapes = [[(0, 0), (1, 0), (0.2, 0.8)],
                  [(0, 0), (0.8, 0), (0.8, 0.8), (0, 0.8)],
                  [(0, 0), (0.8, 0), (0.8, 0.8), (0.6, 0.8),
                   (0.6, 0.2), (0.2, 0.2), (0.2, 0.8), (0, 0.8)]]
        for points in shapes:
            for width in (0, 0.004, 0.12):
                with self.subTest(points=points, width=width):
                    result, _ = convert_body(source_pad() + polygon_body(points, width), fill_tolerance=0.01)
                    polys = decode_fpl(result)[2]
                    target = [(x, -y) for x, y in points]
                    edges = list(zip(target, target[1:] + target[:1]))
                    for xi in range(-8, 109, 2):
                        for yi in range(-88, 9, 2):
                            point = (xi/100, yi/100)
                            inside = inside_polygon(point, target)
                            distance = min(segment_distance(point, a, b) for a, b in edges)
                            covered = stroke_contains(point, polys)
                            if inside or distance <= width / 2 - 0.00002:
                                self.assertTrue(covered, (point, points, width))
                            if not inside and distance > width / 2 + 0.01:
                                self.assertFalse(covered, (point, points, width))

    def test_concave_fill_splits_rows_without_bridging_notch(self):
        points = [(0, 0), (1, 0), (1, 1), (0.7, 1), (0.7, 0.2), (0.3, 0.2), (0.3, 1), (0, 1)]
        polys = decode_fpl(convert_body(source_pad() + polygon_body(points, 0.02))[0])[2]
        rows = [p for p in polys if not p['closed'] and p['points'][0][1] < -300000]
        self.assertTrue(rows)
        self.assertTrue(all(p['points'][1][0] <= 300000 or p['points'][0][0] >= 700000 for p in rows))
        self.assertFalse(stroke_contains((0.5, -0.7), polys))
        self.assertTrue(stroke_contains((0.15, -0.7), polys))
        self.assertTrue(stroke_contains((0.85, -0.7), polys))

    def test_fill_winding_and_duplicate_closing_corner_do_not_change_spans(self):
        points = [(0, 0), (1, 0), (0, 1)]
        rows = []
        for corners in (points, points[::-1], points + points[:1]):
            polys = decode_fpl(convert_body(source_pad() + polygon_body(corners, 0.05))[0])[2]
            rows.append([p for p in polys if not p['closed']])
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0], rows[2])

    def test_filled_rectangle_zero_stroke_and_yes_alias(self):
        rect = '(fp_rect (start 0 0) (end 1 0.5) (stroke (width 0)) (fill solid) (layer "B.SilkS"))'
        result, _ = convert_body(source_pad() + rect, fill_tolerance=0.005)
        polys = decode_fpl(result)[2]
        self.assertTrue(all(p['layer'] == 5 and p['hatch'] == 0 for p in polys))
        self.assertEqual(polys[0]['points'], [(0, 0), (1000000, 0), (1000000, -500000), (0, -500000)])
        self.assertLessEqual(polys[0]['width'] / 2e6 + 0.00002, 0.005)
        self.assertGreater(polys[0]['width'], 0)
        self.assertEqual(decode_fpl(result), decode_fpl(convert_body(source_pad() + rect.replace('fill solid', 'fill yes'),
                                                                  fill_tolerance=0.005)[0]))

    def test_fill_report_records_assumptions_and_source_zero_width(self):
        body = source_pad() + polygon_body([(0, 0), (1, 0), (0, 1)])
        result = converter.convert_detailed(converter.parse_sexpr('(footprint Demo ' + body + ')'),
                                             stl_root=TEST_STL_ROOT, fill_tolerance=0.005)
        report = result.report
        self.assertEqual(report['fills']['policy'], 'overlapping_strokes')
        self.assertEqual(report['fills']['tolerance_mm'], 0.005)
        self.assertEqual(report['fills']['source_polygons'][0]['width'], 0)
        self.assertEqual(report['fills']['written_boundary_polylines'], 1)
        self.assertGreater(report['fills']['written_scanline_polylines'], 0)
        self.assertFalse(report['fills']['gui_validated'])
        severity = {d['code']: d['severity'] for d in report['diagnostics']}
        self.assertEqual(severity['FILL_APPROXIMATED'], 'approximation')
        self.assertEqual(severity['FILL_STROKE_MODEL'], 'assumption')
        self.assertEqual(severity['FILL_EXPORT_UNVERIFIED'], 'assumption')

    def test_strict_accepts_bounded_fill_with_explicit_assumptions(self):
        body = source_pad() + polygon_body([(0, 0), (1, 0), (0, 1)])
        body += '(model "Resistor_SMD.3dshapes/R_0805_2012Metric.step")'
        result, warnings = convert_body(body, strict=True)
        self.assertTrue(decode_fpl(result)[2])
        self.assertTrue(any(w.startswith('FILL_STROKE_MODEL:') for w in warnings))

    def test_invalid_filled_polygons_fail_before_writing(self):
        shapes = [[(0, 0), (1, 1), (0, 1), (1, 0)],  # Crossing edges.
                  [(0, 0), (1, 0), (2, 0)],  # Zero area.
                  [(0, 0), (2, 0), (1, 0), (1, 1), (0, 1)],  # Backtracking edge.
                  [(0, 0), (1, 0), (1, 1), (0.5, 0), (0, 1)],  # Touching edge.
                  [(0, 0), (0.000001, 0), (1, 1)],  # Collapses on target grid.
                  [(0, 0), (math.nan, 0), (1, 1)]]
        for points in shapes:
            with self.subTest(points=points), self.assertRaises(converter.ConversionError):
                convert_body(source_pad() + polygon_body(points))
        with self.assertRaises(converter.ConversionError):
            convert_body(source_pad() + polygon_body([(0, 0), (1, 0), (0, 1)], width=-0.1))

    def test_fill_limits_and_invalid_tolerances_fail_explicitly(self):
        for tolerance in (0, 0.00002, 0.000020001, math.nan, math.inf, 1e308):
            with self.subTest(tolerance=tolerance), self.assertRaises(converter.ConversionError):
                convert_body(source_pad(), fill_tolerance=tolerance)
        with self.assertRaisesRegex(converter.ConversionError, '4096 strokes'):
            convert_body(source_pad() + polygon_body([(0, 0), (100, 0), (0, 100)]))
        many = [(math.cos(i * math.tau / 513), math.sin(i * math.tau / 513)) for i in range(513)]
        with self.assertRaisesRegex(converter.ConversionError, '512 vertices'):
            convert_body(source_pad() + polygon_body(many))

    def test_malformed_fill_flags_and_unsupported_filled_curves_fail(self):
        graphics = ['(fp_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (fill) (layer "F.SilkS"))',
                    '(fp_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (fill (solid)) (layer "F.SilkS"))',
                    '(fp_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (fill no) (fill yes) (layer "F.SilkS"))',
                    '(fp_arc (start 0 0) (mid 0.5 0.5) (end 1 0) (fill solid) (layer "F.SilkS"))']
        for graphic in graphics:
            with self.subTest(graphic=graphic), self.assertRaises(converter.ConversionError):
                convert_body(source_pad() + graphic)

    def test_writer_rejects_unexpanded_filled_model(self):
        for graphic in (polygon_body([(0, 0), (1, 0), (0, 1)]), circle_body()):
            body = source_pad() + graphic
            fp = converter.parse_footprint(converter.parse_sexpr('(footprint Demo ' + body + ')'))
            with self.subTest(graphic=graphic), self.assertRaisesRegex(converter.ConversionError, 'tessellated before'):
                converter.write_fpl(fp, [], [])

    def test_filled_circle_keeps_source_geometry_and_historic_yes_alias(self):
        body = source_pad() + circle_body(center=(2, -3), end=(2.3, -2.6), width=0.02, layer='B.SilkS')
        root = converter.parse_sexpr('(footprint Circle ' + body + ')')
        fp = converter.parse_footprint(root)
        self.assertEqual(fp.filled_polygons, [])
        self.assertEqual(fp.polylines, [])
        self.assertEqual(fp.filled_circles, [converter.FilledCircle((2, -3), (2.3, -2.6), 0.02, 'B.SilkS')])
        rendered = converter.tessellate_fills(fp, 0.01, [])
        self.assertEqual(rendered.filled_circles, [])
        self.assertEqual(len(fp.filled_circles), 1)  # Source is not mutated.
        generated, _ = convert_body(body)
        historic, _ = convert_body(body.replace('fill solid', 'fill yes'))
        self.assertEqual(generated, historic)

    def test_filled_circle_zero_stroke_covers_disk_on_both_silk_layers(self):
        # A loose curve tolerance must not leave circular caps unfilled when
        # fill tolerance (and hence stroke width) is much smaller.
        center, end = (0.731234, -0.456789), (1.031234, -0.056789)
        target_center = (center[0], -center[1])
        for layer, target_layer in (('F.SilkS', 4), ('B.SilkS', 5)):
            with self.subTest(layer=layer):
                result, _ = convert_body(source_pad() + circle_body(center, end, layer=layer),
                                         curve_tolerance=0.2, fill_tolerance=0.005)
                polys = decode_fpl(result)[2]
                self.assertTrue(all(p['layer'] == target_layer and p['hatch'] == 0 for p in polys))
                self.assertEqual(sum(p['closed'] for p in polys), 1)
                self.assertGreater(len(polys[0]['points']), 8)
                # Independent radial/interior probes include the true circle,
                # not just points inside the tessellated polygon.
                for index in range(144):
                    angle = math.tau * index / 144
                    for fraction in (0, 0.1, 0.3, 0.6, 0.9, 0.99, 1):
                        point = (target_center[0] + 0.5 * fraction * math.cos(angle),
                                 target_center[1] + 0.5 * fraction * math.sin(angle))
                        self.assertTrue(stroke_contains(point, polys), point)
                # The largest radial extent of a round-ended straight stroke
                # is bounded by its furthest endpoint plus half its width.
                outer = max(math.dist(target_center, (x / 1e6, y / 1e6)) + p['width'] / 2e6
                            for p in polys for x, y in p['points'])
                self.assertLessEqual(outer - 0.5, 0.005)

    def test_filled_circle_source_stroke_boundary_error_is_bounded(self):
        center, end = (0.1234567, 0.3456789), (0.4234567, 0.7456789)
        target_center = (center[0], -center[1])
        for width, curve_tolerance, fill_tolerance in ((0.08, 0.002, 0.005),
                                                       (0.003, 0.02, 0.004)):
            result, _ = convert_body(source_pad() + circle_body(center, end, width),
                                     curve_tolerance=curve_tolerance, fill_tolerance=fill_tolerance)
            polys = decode_fpl(result)[2]
            edges = []
            for poly in polys:
                points = [(x / 1e6, y / 1e6) for x, y in poly['points']]
                ends = points[1:] + points[:1] if poly['closed'] else points[1:]
                edges.extend((a, b, poly['width'] / 2e6) for a, b in zip(points, ends))
            source_radius = 0.5 + width / 2
            outer = max(math.dist(target_center, point) + half for a, b, half in edges for point in (a, b))
            self.assertLessEqual(outer - source_radius, fill_tolerance)
            for index in range(720):
                angle = index * math.tau / 720
                point = (target_center[0] + source_radius * math.cos(angle),
                         target_center[1] + source_radius * math.sin(angle))
                distance = min(max(0, segment_distance(point, a, b) - half) for a, b, half in edges)
                self.assertLessEqual(distance, curve_tolerance)

    def test_filled_circle_near_grid_resolution_preserves_disk(self):
        center = (0.000003, -0.000007)
        radius = 0.00012
        result, _ = convert_body(source_pad() + circle_body(center, (center[0] + radius, center[1])),
                                 fill_tolerance=0.0001, curve_tolerance=0.00005)
        polys = decode_fpl(result)[2]
        target_center = (center[0], -center[1])
        for index in range(144):
            angle = math.tau * index / 144
            self.assertTrue(stroke_contains((target_center[0] + radius * math.cos(angle),
                                            target_center[1] + radius * math.sin(angle)), polys))
        outer = max(math.dist(target_center, (x / 1e6, y / 1e6)) + p['width'] / 2e6
                    for p in polys for x, y in p['points'])
        self.assertLessEqual(outer - radius, 0.0001)

    def test_filled_circle_report_and_strict_policy_preserve_assumptions(self):
        body = source_pad() + circle_body(width=0.03)
        body += '(model "Resistor_SMD.3dshapes/R_0805_2012Metric.step")'
        result = converter.convert_detailed(converter.parse_sexpr('(footprint Circle ' + body + ')'),
                                             stl_root=TEST_STL_ROOT, strict=True,
                                             curve_tolerance=0.003, fill_tolerance=0.007)
        report = result.report
        self.assertEqual(report['status'], 'generated')
        self.assertEqual(report['counts']['source_filled_circles'], 1)
        self.assertEqual(report['counts']['source_filled_polygons'], 0)
        self.assertEqual(report['fills']['source_circles'], [
            {'center': (0, 0), 'end': (1, 0), 'width': 0.03, 'layer': 'F.SilkS'}])
        self.assertEqual(report['fills']['circle_bounds']['max_boundary_error_mm'], 0.007)
        self.assertEqual(report['fills']['circle_bounds']['max_inward_boundary_error_mm'], 0.003)
        self.assertEqual(report['fills']['written_boundary_polylines'], 1)
        self.assertFalse(report['fills']['manufacturing_validated'])
        codes = {d['code']: d['severity'] for d in report['diagnostics']}
        self.assertEqual(codes['CURVE_APPROXIMATED'], 'approximation')
        self.assertEqual(codes['FILL_EXPORT_UNVERIFIED'], 'assumption')

    def test_filled_circle_invalid_geometry_and_resolution_fail_explicitly(self):
        cases = [circle_body(end=(0, 0)), circle_body(end=(math.nan, 0)),
                 circle_body(center=(math.inf, 0)), circle_body(width=-0.1),
                 circle_body(end=(0.000001, 0)), circle_body(center=(2147, 0), end=(2148, 0))]
        for graphic in cases:
            with self.subTest(graphic=graphic), self.assertRaises(converter.ConversionError):
                convert_body(source_pad() + graphic)
        with self.assertRaisesRegex(converter.ConversionError, 'resolution'):
            convert_body(source_pad() + circle_body(), fill_tolerance=0.00003)

    def test_filled_circle_limits_apply_to_mixed_fills(self):
        with self.assertRaisesRegex(converter.ConversionError, '512 vertices'):
            convert_body(source_pad() + circle_body(end=(300, 0)))
        with self.assertRaisesRegex(converter.ConversionError, '4096 strokes'):
            convert_body(source_pad() + circle_body(end=(25, 0)))
        mixed = polygon_body([(0, 0), (1, 0), (0, 1)])
        mixed += ''.join(circle_body(center=(20 * i, 0), end=(20 * i + 8, 0)) for i in range(3))
        with self.assertRaisesRegex(converter.ConversionError, '4096 strokes'):
            convert_body(source_pad() + mixed)

    def test_saved_filled_circle_control_is_reproducible_and_structurally_correct(self):
        source = (FIXTURES / 'FilledCircle_Control.kicad_mod').read_text(encoding='utf-8')
        result = converter.convert_detailed(converter.parse_sexpr(source), stl_root=TEST_STL_ROOT)
        self.assertEqual(result.fpl.encode('cp1251'), (PROJECT / 'output' / 'FilledCircle_Control.fpl').read_bytes())
        fields, pads, polys = decode_fpl(result.fpl)
        self.assertEqual(fields['name'], [['FilledCircle_Control']])
        self.assertEqual(fields['ref_text'], [['1000000', '0', '2000000', '0', '150000']])
        self.assertEqual(len(pads), 1)
        self.assertEqual(pads[0]['top_pad'], (3, 1400000, 512500, 512500, 0))
        self.assertEqual((pads[0]['x'], pads[0]['y'], pads[0]['hole']), (0, 0, 0))
        self.assertEqual({p['layer'] for p in polys}, {4, 5})
        self.assertEqual(sum(p['closed'] for p in polys), 2)
        for layer, center, width in ((4, (1.8, 0.8), 19960), (5, (-1.8, -0.8), 40000)):
            drawing = [p for p in polys if p['layer'] == layer]
            self.assertTrue(all(p['width'] == width and p['hatch'] == 0 for p in drawing))
            self.assertTrue(stroke_contains(center, drawing))
        self.assertEqual(result.report['counts']['source_filled_circles'], 2)
        self.assertEqual(result.report['fills']['written_scanline_polylines'], 90)
        self.assertNotIn('openscad_code', fields)
        self.assertTrue(any(w.startswith('MODEL_MISSING:') for w in result.warnings))

    def test_filled_circle_cli_reports_source_and_keeps_output_on_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, output, report = base / 'circle.kicad_mod', base / 'circle.fpl', base / 'circle.json'
            text = (FIXTURES / 'FilledCircle_Control.kicad_mod').read_text(encoding='utf-8')
            source.write_text(text, encoding='utf-8')
            command = [sys.executable, '-B', '-m', 'src.footprint_converter', str(source), str(output),
                       '--report', str(report), '--stl-root', str(TEST_STL_ROOT),
                       '--curve-tolerance', '0.002', '--fill-tolerance', '0.004']
            result = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['fills']['source_circles'][0]['center'], [1.8, -0.8])
            self.assertEqual(data['fills']['circle_bounds']['max_boundary_error_mm'], 0.004)
            self.assertFalse(data['target']['gui_validated'])
            previous = output.read_bytes()
            source.write_text(text.replace('(end 2.1 -0.8)', '(end 1.8 -0.8)'), encoding='utf-8')
            result = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['status'], 'failed')


    @unittest.skipUnless((PROJECT / 'stl_files' / 'Package_TO_SOT_SMD.3dshapes' / 'SOT-23.stl').is_file(),
                        'Optional integration: existing SOT-23 STL unavailable')
    def test_real_sot23_model_is_bound_without_opening_or_modifying_stl(self):
        root = converter.parse_sexpr((FIXTURES / 'SOT-23.kicad_mod').read_text())
        path = PROJECT / 'stl_files' / 'Package_TO_SOT_SMD.3dshapes' / 'SOT-23.stl'
        before = path.stat()
        with patch.object(Path, 'open', side_effect=AssertionError('Do not read STL geometry')):
            result = converter.convert_detailed(root)
        after = path.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino),
                         (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino))
        self.assertEqual(result.report['models'][0]['relative_stl'], 'Package_TO_SOT_SMD.3dshapes/SOT-23.stl')
        self.assertEqual(result.report['counts']['matched_models'], 1)
        self.assertFalse(result.report['models'][0]['frame_validated'])

    def test_sot23_cli_report_and_fill_tolerance(self):
        with tempfile.TemporaryDirectory() as temp:
            destination, report = Path(temp) / 'SOT-23.fpl', Path(temp) / 'SOT-23.json'
            command = [sys.executable, '-B', str(MODULE), str(FIXTURES / 'SOT-23.kicad_mod'),
                       str(destination), '--stl-root', str(TEST_STL_ROOT), '--report', str(report)]
            result = subprocess.run(command + ['--fill-tolerance', '0.005'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            decode_fpl(destination.read_text(encoding='cp1251'))
            data = json.loads(report.read_text())
            self.assertEqual(data['fills']['tolerance_mm'], 0.005)
            self.assertEqual(data['counts']['source_filled_polygons'], 1)
            previous = destination.read_bytes()
            result = subprocess.run(command + ['--fill-tolerance', 'nan'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(destination.read_bytes(), previous)
            self.assertEqual(json.loads(report.read_text())['status'], 'failed')

    def test_invalid_curves_fail_instead_of_producing_empty_geometry(self):
        graphics = [
            '(fp_arc (start 0 0) (mid 1 0) (end 2 0) (layer "F.SilkS"))',
            '(fp_arc (start 0 0) (end 1 0) (angle 90) (layer "F.SilkS"))',
            '(fp_circle (center 1 1) (end 1 1) (layer "F.SilkS"))',
            '(fp_poly (pts (xy 0 0) (xy 1 1)) (layer "F.SilkS"))',
            '(fp_circle (center 0 0) (end 0 0) (fill yes) (layer "F.SilkS"))',
        ]
        for graphic in graphics:
            with self.subTest(graphic=graphic), self.assertRaises(converter.ConversionError):
                convert_body(source_pad() + graphic)
        with self.assertRaises(converter.ConversionError):
            convert_body(source_pad(), curve_tolerance=0)
        with self.assertRaisesRegex(converter.ConversionError, '4096 segments'):
            converter.sample_arc((0, 0), 2000, 0, math.tau, 0.00002)

    def test_text_variables_require_explicit_binding_and_are_not_dynamic(self):
        body = source_pad() + '''(fp_text user "Part ${REFERENCE} = ${VALUE}" (at 0 1)
            (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.1))))'''
        result, warnings = convert_body(body)
        self.assertNotIn('text', decode_fpl(result)[0])
        self.assertTrue(any(w.startswith('TEXT_VARIABLE_UNRESOLVED:') for w in warnings))
        result, warnings = convert_body(body, text_variables={'REFERENCE': 'R1', 'VALUE': '10k'})
        self.assertEqual(decode_fpl(result)[0]['text'][0][0], 'Part R1 = 10k')
        self.assertTrue(any(w.startswith('TEXT_VARIABLE_BOUND:') for w in warnings))
        self.assertFalse(any(w.startswith('TEXT_VARIABLE_UNRESOLVED:') for w in warnings))

    def test_report_retains_source_text_and_separates_losses_from_assumptions(self):
        result = converter.convert_detailed(converter.parse_sexpr(FIXTURE.read_text()), stl_root=TEST_STL_ROOT)
        report = result.report
        self.assertEqual(report['status'], 'generated_with_loss')
        self.assertFalse(report['target']['gui_validated'])
        self.assertEqual(report['counts']['written_pins'], 2)
        self.assertEqual(report['counts']['matched_models'], 1)
        self.assertEqual(report['source_texts'][1]['content'], 'R_0805_2012Metric')
        self.assertEqual(report['source_texts'][1]['layer'], 'F.Fab')
        self.assertEqual(report['models'][0]['relative_stl'], 'Resistor_SMD.3dshapes/R_0805_2012Metric.stl')
        self.assertFalse(report['models'][0]['frame_validated'])
        severity = {d['code']: d['severity'] for d in report['diagnostics']}
        self.assertEqual(severity['TEXT_VARIABLE_UNRESOLVED'], 'loss')
        self.assertEqual(severity['MODEL_FRAME_UNVERIFIED'], 'assumption')
        self.assertEqual(json.loads(json.dumps(report))['footprint'], report['footprint'])

    def test_strict_rejects_known_loss_but_accepts_bounded_curve_approximation(self):
        with self.assertRaises(converter.LossyConversionError) as caught:
            converter.convert_detailed(converter.parse_sexpr(FIXTURE.read_text()), strict=True, stl_root=TEST_STL_ROOT)
        self.assertEqual(caught.exception.report['status'], 'rejected_loss')
        body = source_pad() + '''(fp_circle (center 0 0) (end 1 0)
            (layer "F.SilkS") (stroke (width 0.1)))
            (model "Resistor_SMD.3dshapes/R_0805_2012Metric.step")'''
        result, warnings = convert_body(body, strict=True)
        self.assertTrue(decode_fpl(result)[2][0]['closed'])
        self.assertTrue(any(w.startswith('CURVE_APPROXIMATED:') for w in warnings))

    def test_cli_strict_writes_rejection_report_without_overwriting_fpl(self):
        with tempfile.TemporaryDirectory() as temp:
            output, report = Path(temp) / 'out.fpl', Path(temp) / 'report.json'
            output.write_bytes(b'previous library')
            result = subprocess.run([sys.executable, '-B', str(MODULE), str(FIXTURE), str(output),
                                     '--strict', '--report', str(report)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(output.read_bytes(), b'previous library')
            data = json.loads(report.read_text())
            self.assertEqual(data['status'], 'rejected_loss')
            self.assertTrue(data['errors'])

    def test_cli_report_cannot_overwrite_source_model_or_fpl(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'out.fpl'
            for report in [FIXTURE, REAL_STL, output]:
                with self.subTest(report=report):
                    result = subprocess.run([sys.executable, '-B', str(MODULE), str(FIXTURE), str(output),
                                             '--report', str(report)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(output.exists())

    def test_malformed_input_cli_reports_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output, report = (Path(temp) / name for name in ('bad.kicad_mod', 'out.fpl', 'report.json'))
            for contents in ['(footprint () (pad))', '(footprint Demo (property))',
                             '(footprint Demo (pad "1"))', '(footprint Demo (fp_text user))']:
                with self.subTest(contents=contents):
                    source.write_text(contents)
                    result = subprocess.run([sys.executable, '-B', str(MODULE), str(source), str(output),
                                             '--report', str(report)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertFalse(output.exists())
                    self.assertEqual(json.loads(report.read_text())['status'], 'failed')

    def test_atomic_write_failure_preserves_old_file_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'out.fpl'
            destination.write_bytes(b'previous library')
            with patch.object(converter.os, 'replace', side_effect=OSError('replacement failed')):
                with self.assertRaises(OSError):
                    converter.atomic_write(destination, b'new library')
            self.assertEqual(destination.read_bytes(), b'previous library')
            self.assertEqual(list(Path(temp).glob('.freepcb-*')), [])

    def test_quantized_radius_never_exceeds_target_half_dimensions(self):
        result, _ = convert_body(source_pad(shape='roundrect', size='2 1.00001',
                                           extra='(roundrect_rratio 0.5)'))
        self.assertEqual(decode_fpl(result)[1][0]['top_pad'], (4, 1000010, 1000000, 1000000, 500000))

    def test_explicit_rect_mask_expansion_adds_rounded_corners(self):
        result, _ = convert_body(source_pad(size='2 4', at='0 0', extra='(solder_mask_margin 0.1)'))
        fields, pads, _ = decode_fpl(result)
        self.assertEqual(pads[0]['top_pad'], (3, 4000000, 1000000, 1000000, 0))
        self.assertEqual(pads[0]['top_mask'], (4, 4200000, 1100000, 1100000, 100000))
        self.assertEqual(pads[0]['bottom_mask'], (0, 0, 0, 0, 0))
        self.assertEqual(fields['sel_rect'][0], ['-1100000', '-2100000', '1100000', '2100000'])

    def test_paste_margin_and_ratio_are_per_side_and_per_axis(self):
        result, warnings = convert_body(source_pad(size='2 4', extra='''
            (solder_paste_margin -0.1) (solder_paste_margin_ratio -0.05)'''))
        self.assertEqual(decode_fpl(result)[1][0]['top_paste'], (3, 3400000, 800000, 800000, 0))
        self.assertFalse(any(w.startswith('APERTURE_ASSUMED_ZERO:') for w in warnings))

    def test_pad_footprint_default_precedence_keeps_explicit_zero(self):
        defaults = converter.ApertureSettings(0.3, -0.2, -0.1)
        body = '(solder_mask_margin 0.1) (solder_paste_margin -0.05) (solder_paste_ratio 0)'
        body += source_pad(size='2 4', extra='(solder_mask_margin 0)')
        result, _ = convert_body(body, aperture_defaults=defaults)
        pad = decode_fpl(result)[1][0]
        self.assertEqual(pad['top_mask'], pad['top_pad'])
        self.assertEqual(pad['top_paste'], (3, 3900000, 950000, 950000, 0))

    def test_bottom_apertures_follow_bottom_layers(self):
        result, _ = convert_body(source_pad(size='2 4', layers='"B.Cu" "B.Mask" "B.Paste"'),
                                 aperture_defaults=converter.ApertureSettings(0.1, 0, 0))
        pad = decode_fpl(result)[1][0]
        self.assertEqual(pad['bottom_mask'], (4, 4200000, 1100000, 1100000, 100000))
        self.assertEqual(pad['bottom_paste'], pad['bottom_pad'])
        self.assertEqual(pad['top_mask'], (0, 0, 0, 0, 0))

    def test_roundrect_uniform_margin_changes_radius(self):
        result, _ = convert_body(source_pad(shape='roundrect', size='2 4', extra='''
            (roundrect_rratio 0.2) (solder_mask_margin 0.1)
            (solder_paste_margin -0.1) (solder_paste_margin_ratio 0)'''))
        pad = decode_fpl(result)[1][0]
        self.assertEqual(pad['top_mask'], (4, 4200000, 1100000, 1100000, 500000))
        self.assertEqual(pad['top_paste'], (4, 3800000, 900000, 900000, 300000))

    def test_roundrect_asymmetric_paste_is_explicitly_rejected(self):
        with self.assertRaisesRegex(converter.ConversionError, 'asymmetric roundrect'):
            convert_body(source_pad(shape='roundrect', size='2 4', extra='''
                (roundrect_rratio 0.2) (solder_paste_margin 0) (solder_paste_margin_ratio -0.05)'''))

    def test_circle_and_oval_apertures_preserve_supported_shapes(self):
        for shape, size, expected in [('circle', '2 2', (1, 2200000, 1100000, 1100000, 0)),
                                      ('oval', '2 4', (5, 4200000, 1100000, 1100000, 0))]:
            with self.subTest(shape=shape):
                result, _ = convert_body(source_pad(shape=shape, size=size, extra='(solder_mask_margin 0.1)'))
                self.assertEqual(decode_fpl(result)[1][0]['top_mask'], expected)

    def test_closed_aperture_is_none_and_unknown_paste_term_is_reported(self):
        result, warnings = convert_body(source_pad(size='2 4', extra='(solder_mask_margin -1) (solder_paste_margin -0.1)'))
        self.assertEqual(decode_fpl(result)[1][0]['top_mask'], (0, 0, 0, 0, 0))
        self.assertTrue(any(w.startswith('APERTURE_CLOSED:') for w in warnings))
        self.assertTrue(any(w.startswith('APERTURE_ASSUMED_ZERO:') for w in warnings))
        with self.assertRaises(converter.LossyConversionError) as caught:
            convert_body(source_pad(extra='(solder_paste_margin -0.1)'), strict=True)
        self.assertIn('APERTURE_ASSUMED_ZERO', str(caught.exception))

    def test_aperture_report_and_invalid_margins(self):
        root = converter.parse_sexpr('(footprint Demo ' + source_pad(extra='(solder_mask_margin 0.1)') + ')')
        report = converter.convert_detailed(root, aperture_defaults=converter.ApertureSettings(None, 0, 0)).report
        self.assertEqual(report['apertures']['pads'][0]['resolved'],
                         {'mask_margin': 0.1, 'paste_margin': 0, 'paste_ratio': 0})
        for settings in ['(solder_mask_margin nan)', '(solder_paste_margin inf)', '(solder_paste_margin_ratio ())']:
            with self.subTest(settings=settings), self.assertRaises(converter.ConversionError):
                convert_body(source_pad(extra=settings))

    def test_npth_technical_only_mask_ignores_margin_and_selection_covers_drill(self):
        result, _ = convert_body(source_pad(kind='np_thru_hole', shape='circle', size='0.4 0.4',
                                           at='0 0', layers='"F.Mask"', name='',
                                           extra='(drill 1) (solder_mask_margin 0.2)'))
        fields, pads, _ = decode_fpl(result)
        self.assertEqual(pads[0]['top_mask'], (1, 400000, 200000, 200000, 0))
        self.assertEqual(fields['sel_rect'][0], ['-500000', '-500000', '500000', '500000'])


if __name__ == '__main__':
    unittest.main()
