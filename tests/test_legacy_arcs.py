"""Legacy arc geometry checked against fixed endpoints and target-grid probes."""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.footprint_converter import ConversionError, LossyConversionError, convert_detailed, parse_sexpr
from test_footprint_converter import decode_fpl, segment_distance, source_pad

PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / 'tests/fixtures/Crystal_HC49-U_Vertical.kicad_mod'


def arc(center=(0, 0), start=(1, 0), angle=90, layer='F.SilkS', extra=''):
    return (f'(fp_arc (start {center[0]} {center[1]}) '
            f'(end {start[0]} {start[1]}) (angle {angle}) '
            f'(layer "{layer}") (width 0.12) {extra})')


def root(body):
    return parse_sexpr(f'(module "LegacyArc" {source_pad()} {body})')


def crystal_2d_root():
    # Keep the official source unchanged. This explicitly named 2D control
    # omits its legacy model(at) record, which remains unsupported.
    source = parse_sexpr(FIXTURE.read_text())
    return [item for item in source if not isinstance(item, list) or item[0] != 'model']


class LegacyArcTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.stl_root = Path(self.directory.name) / 'models'

    def convert(self, body, **options):
        return convert_detailed(root(body), stl_root=self.stl_root, **options)

    def test_fixed_endpoints_and_side_on_both_layers(self):
        # These expectations are literal cardinal coordinates, independent
        # of the converter's angular parameterization and sampling count.
        for angle, end, ysign in [(90, (0, -1000000), -1),
                                 (-90, (0, 1000000), 1),
                                 (180, (-1000000, 0), -1),
                                 (-180, (-1000000, 0), 1)]:
            for layer, target in [('F.SilkS', 4), ('B.SilkS', 5)]:
                with self.subTest(angle=angle, layer=layer):
                    poly = decode_fpl(self.convert(arc(angle=angle, layer=layer)).fpl)[2][0]
                    self.assertEqual(poly['points'][0], (1000000, 0))
                    self.assertEqual(poly['points'][-1], end)
                    self.assertEqual(poly['layer'], target)
                    self.assertEqual(poly['width'], 120000)
                    self.assertFalse(poly['closed'])
                    self.assertTrue(all(y * ysign >= 0 for x, y in poly['points']))
                    self.assertTrue(any(y * ysign > 0 for x, y in poly['points']))

    def test_large_sweeps_preserve_long_arc_and_signed_order(self):
        for angle, end in [(270, (0, 1000000)), (-270, (0, -1000000)),
                           (360, (1000000, 0)), (-360, (1000000, 0))]:
            with self.subTest(angle=angle):
                points = decode_fpl(self.convert(arc(angle=angle)).fpl)[2][0]['points']
                self.assertEqual(points[-1], end)
                # Unwrap target angles; inversion of Y reverses source traversal.
                total = 0
                for a, b in zip(points, points[1:]):
                    delta = math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])
                    total += (delta + math.pi) % math.tau - math.pi
                self.assertAlmostEqual(total, -math.radians(angle), places=6)

    def test_target_grid_distance_bound_with_shift_and_oblique_start(self):
        center = (123.456789, -234.567891)
        dx, dy = 0.75, 1.25
        radius = math.hypot(dx, dy)
        start = (center[0] + dx, center[1] + dy)
        for angle in (23.75, -127.5, 270, -359.9):
            for tolerance in (0.01, 0.002):
                with self.subTest(angle=angle, tolerance=tolerance):
                    poly = decode_fpl(self.convert(arc(center, start, angle),
                                                  curve_tolerance=tolerance).fpl)[2][0]
                    points = [(x / 1e6, y / 1e6) for x, y in poly['points']]
                    segments = list(zip(points, points[1:]))
                    for i in range(1001):
                        theta = math.radians(angle) * i / 1000
                        # Independent rotation of the source radius vector.
                        x = center[0] + dx * math.cos(theta) - dy * math.sin(theta)
                        y = center[1] + dx * math.sin(theta) + dy * math.cos(theta)
                        distance = min(segment_distance((x, -y), a, b) for a, b in segments)
                        self.assertLessEqual(distance, tolerance + 1e-10)
                    # Check the converse at interior points of every written chord.
                    for a, b in segments:
                        for fraction in (0, 0.25, 0.5, 0.75, 1):
                            p = (a[0] + (b[0]-a[0])*fraction, a[1] + (b[1]-a[1])*fraction)
                            self.assertLessEqual(abs(math.dist(p, (center[0], -center[1]))-radius),
                                                 tolerance + 1e-10)

    def test_matches_equivalent_modern_arc_geometry(self):
        legacy = self.convert(arc(angle=180))
        modern = self.convert('(fp_arc (start 1 0) (mid 0 1) (end -1 0) '
                              '(layer F.SilkS) (width 0.12))')
        self.assertEqual(legacy.fpl, modern.fpl)
        self.assertEqual(legacy.warnings, modern.warnings)
        self.assertEqual(legacy.report, modern.report)

    def test_invalid_duplicate_mixed_and_unbounded_arcs_fail(self):
        invalid = [arc(angle=v) for v in (0, 360.01, -361, 'nan', 'inf', 'bad')]
        invalid += [arc(start=(0, 0)), arc(angle=1e-12), arc(start=(1e-9, 0), angle=360),
                    arc(center=('nan', 0)), arc(start=(1, 'inf')),
                    arc(extra='(mid 0 1)'), arc(extra='(start 1 1)'),
                    arc(extra='(end 2 2)'), arc(extra='(angle 90)'),
                    arc().replace('(angle 90)', '(angle)'),
                    arc().replace('(angle 90)', '(angle 90 180)'),
                    arc().replace('(end 1 0)', '(end 1 0 2)'),
                    arc().replace('(start 0 0)', '(start 0)'),
                    arc().replace('(angle 90)', ''), arc(extra='(fill solid)')]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises((ConversionError, ValueError)):
                self.convert(body)
        with self.assertRaisesRegex(ConversionError, '4096 segments'):
            self.convert(arc(start=(2000, 0), angle=360), curve_tolerance=0.00002)

    def test_report_and_strict_keep_approximation_explicit(self):
        result = self.convert(arc())
        diagnostic = next(d for d in result.report['diagnostics'] if d['code'] == 'CURVE_APPROXIMATED')
        self.assertEqual(diagnostic['severity'], 'approximation')
        self.assertFalse(result.report['target']['gui_validated'])
        self.assertTrue(any('chord error <= 0.01 mm' in w for w in result.warnings))
        with self.assertRaises(LossyConversionError) as caught:
            self.convert(arc(), strict=True)
        # The control has no model: strict still rejects that independent loss.
        losses = [d['code'] for d in caught.exception.report['diagnostics']
                  if d['severity'] == 'loss']
        self.assertEqual(losses, ['MODEL_MISSING'])

    def test_official_crystal_2d_control_and_legacy_model_limitation(self):
        result = convert_detailed(crystal_2d_root(), 'Crystal_HC49-U_Vertical_2D',
                                  stl_root=self.stl_root)
        _, pins, polys = decode_fpl(result.fpl)
        self.assertEqual([(p['x'], p['y'], p['hole']) for p in pins],
                         [(0, 0, 800000), (4880000, 0, 800000)])
        self.assertEqual(len(polys), 12)
        self.assertEqual([p['layer'] for p in polys], [7]*4 + [4]*2 + [7]*4 + [4]*2)
        # Left silk arc bulges left; right silk arc bulges right.
        self.assertLess(min(x for x, y in polys[-2]['points']), -3100000)
        self.assertGreater(max(x for x, y in polys[-1]['points']), 7980000)
        self.assertTrue(any(w.startswith('MODEL_MISSING:') for w in result.warnings))
        self.assertNotIn('openscad_code:', result.fpl)
        self.assertEqual((PROJECT / 'output/Crystal_HC49-U_Vertical_2D.fpl').read_bytes(),
                         result.fpl.encode('cp1251'))
        with self.assertRaisesRegex(ConversionError, r'Legacy model \(at'):
            convert_detailed(parse_sexpr(FIXTURE.read_text()), stl_root=self.stl_root)

    def test_cli_keeps_previous_file_when_arc_is_invalid(self):
        base = Path(self.directory.name)
        source, output, report = base/'source.kicad_mod', base/'output.fpl', base/'report.json'
        source.write_text(f'(module "LegacyArc" {source_pad()} {arc()})')
        command = [sys.executable, '-B', '-m', 'src.footprint_converter', str(source), str(output),
                   '--stl-root', str(self.stl_root), '--report', str(report)]
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        previous = output.read_bytes()
        source.write_text(f'(module "LegacyArc" {source_pad()} {arc(angle=0)})')
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertNotIn('Traceback', run.stderr)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(json.loads(report.read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
