"""Independent numerical checks of bounded straight KiCad9 PCB patterns."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.footprint_converter.audit import audit_batch, inventory
from src.footprint_converter.batch import run_batch
from src.footprint_converter.errors import ConversionError, LossyConversionError
from src.footprint_converter.model import ApertureSettings
from src.footprint_converter.parser import parse_footprint, parse_sexpr
from src.footprint_converter.pipeline import convert_detailed
from test_footprint_converter import decode_fpl, source_pad

PROJECT = Path(__file__).resolve().parents[1]
CONTROL = PROJECT / 'tests/fixtures/strokes/StrokePatterns_Control.kicad_mod'
DEFAULTS = ApertureSettings(.05, 0, 0)


def tree(body):
    return parse_sexpr('(footprint "Demo" ' + body + source_pad() + ')')


def line(style='dash', width='.1', start='0 0', end='4 0', layer='F.SilkS', extra=''):
    return f'(fp_line (start {start}) (end {end}) (stroke (width {width}) (type {style}) {extra}) (layer "{layer}"))'


def converted(body, **options):
    return convert_detailed(tree(body), aperture_defaults=DEFAULTS, **options)


def drawing(result):
    return decode_fpl(result.fpl)[2]


class FootprintStrokeTests(unittest.TestCase):
    def test_default_equals_solid_for_line_rectangle_circle_polygon_and_fills(self):
        bodies = [line('default'),
            '(fp_rect (start 0 0) (end 2 1) (stroke (width .1) (type default)) (layer "F.SilkS"))',
            '(fp_circle (center 0 0) (end 1 0) (stroke (width .1) (type default)) (layer "F.SilkS"))',
            '(fp_poly (pts (xy 0 0) (xy 1 0) (xy 0 1)) (stroke (width .1) (type default)) (fill solid) (layer "F.SilkS"))']
        for body in bodies:
            a, b = converted(body), converted(body.replace('type default', 'type solid'))
            self.assertEqual((a.fpl, a.warnings, a.report), (b.fpl, b.warnings, b.report))
            self.assertNotIn('graphic_strokes', a.report)

    def test_default_adds_no_stroke_loss_under_strict(self):
        reports = []
        for style in ('default', 'solid'):
            with self.assertRaises(LossyConversionError) as caught:
                converted(line(style), strict=True)
            reports.append(caught.exception.report)
        self.assertEqual(*reports)
        self.assertNotIn('GRAPHIC_STROKE_FLATTENED', {d['code'] for d in reports[0]['diagnostics']})

    def test_four_patterns_have_source_derived_mark_and_gap_intervals(self):
        # Literal expected 0.1-mm-width centreline intervals; oracle does not
        # import the implementation's pattern table or splitting function.
        expected = {
            'dash': [(0, 1.1), (1.5, 2.6), (3, 4)],
            'dot': [(0, .02), (.42, .44), (.84, .86), (1.26, 1.28), (1.68, 1.7),
                    (2.1, 2.12), (2.52, 2.54), (2.94, 2.96), (3.36, 3.38), (3.78, 3.8)],
            'dash_dot': [(0, 1.1), (1.5, 1.52), (1.92, 3.02), (3.42, 3.44), (3.84, 4)],
            'dash_dot_dot': [(0, 1.1), (1.5, 1.52), (1.92, 1.94), (2.34, 3.44), (3.84, 3.86)]}
        for style, intervals in expected.items():
            marks = drawing(converted(line(style)))
            self.assertEqual([p['points'] for p in marks],
                [[(round(a * 1e6), 0), (round(b * 1e6), 0)] for a, b in intervals])
            self.assertTrue(all(p['width'] == 100000 and not p['closed'] for p in marks))

    def test_short_marks_clip_and_exact_boundary_point_omission_is_reported_loss(self):
        self.assertEqual(drawing(converted(line(end='.01 0')))[0]['points'], [(0, 0), (10000, 0)])
        boundary = converted(line(end='1.5 0'))
        self.assertEqual(len(drawing(boundary)), 1)
        self.assertEqual(boundary.report['graphic_strokes']['zero_length_endpoint_marks'], 'omitted_with_loss')
        self.assertTrue(any(d['code'] == 'GRAPHIC_STROKE_FLATTENED' and d['severity'] == 'loss' for d in boundary.report['diagnostics']))
        self.assertEqual(drawing(converted(line(end='1.12 0')))[0]['points'][-1], (1100000, 0))

    def test_diagonal_reverse_origin_y_flip_and_bottom_silk(self):
        marks = drawing(converted(line(start='5 6', end='2 2', layer='B.SilkS')))
        self.assertEqual(marks[0]['points'], [(5000000, -6000000), (4340000, -5120000)])
        self.assertTrue(all(p['layer'] == 5 for p in marks))
        for p in marks:
            for x, y in p['points']:
                self.assertLessEqual(abs(4 * (x / 1e6 - 5) - 3 * (-y / 1e6 - 6)), .0001)
                self.assertEqual(x % 10, 0); self.assertEqual(y % 10, 0)

    def test_scale_changes_pattern_lengths_without_changing_ratios(self):
        small = drawing(converted(line(width='.1', end='4 0')))
        large = drawing(converted(line(width='.2', end='8 0')))
        self.assertEqual([p['points'] for p in large],
            [[(2 * x, 2 * y) for x, y in p['points']] for p in small])

    def test_rectangle_restarts_each_edge_in_source_corner_order(self):
        body = '(fp_rect (start 2 1) (end 0 0) (stroke (width .1) (type dash)) (fill no) (layer "F.SilkS"))'
        marks = drawing(converted(body))
        self.assertEqual([p['points'][0] for p in marks],
            [(2000000, -1000000), (500000, -1000000), (0, -1000000), (0, 0), (1500000, 0), (2000000, 0)])
        self.assertEqual(marks[-1]['points'][-1], (2000000, -1000000))

    def test_polygon_restarts_edges_and_closing_edge_without_bridging_gaps(self):
        body = '(fp_poly (pts (xy 0 0) (xy 3 0) (xy 3 4) (xy 0 0)) (stroke (width .1) (type dash)) (layer "F.SilkS"))'
        marks = drawing(converted(body))
        self.assertEqual([marks[i]['points'][0] for i in (0, 2, 5)], [(0, 0), (3000000, 0), (3000000, -4000000)])
        self.assertTrue(all(len(p['points']) == 2 and not p['closed'] for p in marks))
        self.assertEqual(marks[-1]['points'][-1], (0, 0))

    def test_raw_typed_source_immutable_and_report_keeps_source_style_geometry(self):
        raw = tree(line('dash_dot')); before = deepcopy(raw)
        fp = parse_footprint(raw)
        self.assertEqual(len(fp.patterned_graphics), 1); self.assertEqual(fp.polylines, [])
        r = convert_detailed(raw, aperture_defaults=DEFAULTS)
        self.assertEqual(raw, before)
        metadata = r.report['graphic_strokes']
        self.assertEqual(metadata['source_graphics'][0]['style'], 'dash_dot')
        self.assertEqual(metadata['source_graphics'][0]['points_mm'], ((0., 0.), (4., 0.)))
        self.assertEqual(metadata['written_segments'], len(drawing(r)))
        self.assertEqual(metadata['phase'], 'restart_at_each_source_edge')
        self.assertFalse(metadata['native_caps_joins_validated'])
        self.assertFalse(metadata['source_project_settings_available'])

    def test_strict_rejects_pattern_loss_with_report(self):
        with self.assertRaises(LossyConversionError) as caught:
            converted(line('dot'), strict=True)
        diagnostics = caught.exception.report['diagnostics']
        self.assertIn({'code': 'GRAPHIC_STROKE_FLATTENED', 'severity': 'loss'},
            [{k: d[k] for k in ('code', 'severity')} for d in diagnostics])
        self.assertEqual(caught.exception.report['status'], 'rejected_loss')

    def test_patterned_curves_and_filled_outlines_remain_explicit_refusals(self):
        for body in [
            '(fp_circle (center 0 0) (end 1 0) (stroke (width .1) (type dash)) (layer "F.SilkS"))',
            '(fp_arc (start 0 0) (mid 1 1) (end 2 0) (stroke (width .1) (type dot)) (layer "F.SilkS"))',
            '(fp_rect (start 0 0) (end 2 1) (stroke (width .1) (type dash_dot)) (fill yes) (layer "F.SilkS"))']:
            with self.assertRaisesRegex(ConversionError, 'straight unfilled profile'):
                converted(body)

    def test_invalid_width_zero_edge_and_grid_collapse_reject(self):
        for body in [line(width='0'), line(width='-1'), line(width='nan'), line(width='inf'),
                     line(width='.000001'), line(end='0 0'), line(end='.000001 0'), line(end='1.500001 0')]:
            with self.assertRaises(ConversionError): converted(body)

    def test_total_footprint_budget_rejects_instead_of_truncating(self):
        with self.assertRaisesRegex(ConversionError, '4096 segments'):
            converted(line(width='.0001', end='10 0'))
        # Each line alone fits; their total exceeds the footprint budget.
        body = line('dot', width='.0001', end='1 0')
        self.assertGreater(len(drawing(converted(body))), 2000)
        with self.assertRaisesRegex(ConversionError, '4096 segments'):
            converted(body + line('dot', width='.0001', start='0 1', end='1 1'))

    def test_invalid_duplicate_mixed_or_colored_stroke_fields_reject(self):
        for body in [line(extra='(type solid)'), line(extra='(width .2)'), line(extra='(color 255 0 0 1)'),
                     line(extra='unexpected'), line('bogus'), line().replace('(type dash)', '(type)'),
                     line().replace('(width .1)', '(width .1 .2)'),
                     line().replace('(layer ', '(width .2) (layer '),
                     line().replace('(layer ', '(stroke (width .1)) (layer '),
                     line().replace('(start 0 0)', '(start 0 0 9)'),
                     line().replace('(end 4 0)', '(end 4 0) (end 5 0)')]:
            with self.assertRaises(ConversionError): converted(body)

    def test_degenerate_self_intersecting_polygon_is_outside_profile(self):
        for pts in ['(xy 0 0) (xy 1 0) (xy 2 0)', '(xy 0 0) (xy 2 2) (xy 0 2) (xy 2 0)']:
            body = f'(fp_poly (pts {pts}) (stroke (width .1) (type dash)) (layer "F.SilkS"))'
            with self.assertRaises(ConversionError): converted(body)

    def test_skipped_source_layer_still_reports_loss_without_expanding(self):
        r = converted(line('dash', layer='F.CrtYd'))
        self.assertEqual(drawing(r), [])
        self.assertNotIn('graphic_strokes', r.report)
        self.assertTrue(any(d['code'] == 'GRAPHIC_LAYER_SKIPPED' for d in r.report['diagnostics']))

    def test_synthetic_control_has_all_patterns_but_medium_has_only_default_and_solid(self):
        r = convert_detailed(parse_sexpr(CONTROL.read_text()), aperture_defaults=DEFAULTS)
        self.assertEqual({g['style'] for g in r.report['graphic_strokes']['source_graphics']},
            {'dash', 'dot', 'dash_dot', 'dash_dot_dot'})
        styles = set()
        for p in (PROJECT / 'tests/fixtures/medium').rglob('*.kicad_mod'):
            styles.update(inventory(parse_sexpr(p.read_text()))['graphic_stroke_types'])
        self.assertEqual(styles, {'solid', 'default'})

    def test_saved_synthetic_native_records_and_report_are_reproducible(self):
        r = convert_detailed(parse_sexpr(CONTROL.read_text()), aperture_defaults=DEFAULTS)
        self.assertEqual(r.fpl.encode('cp1251'), (PROJECT / 'output/StrokePatterns_Control.fpl').read_bytes())
        self.assertEqual(json.loads(json.dumps(r.report)),
            json.loads((PROJECT / 'output/StrokePatterns_Control.stroke-report.json').read_text()))

    def test_batch_resume_invalidation_when_style_changes_and_audit_keeps_raw_types(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base / 'source'; source.mkdir(); path = source / 'Demo.kicad_mod'
            path.write_text('(footprint "Demo" ' + line() + source_pad() + ')')
            out = base / 'batch'
            run_batch(source, out, aperture_defaults=DEFAULTS)
            m = run_batch(source, out, aperture_defaults=DEFAULTS, resume=True)
            self.assertEqual(m['summary']['reused'], 1)
            path.write_text(path.read_text().replace('type dash', 'type dot'))
            m = run_batch(source, out, aperture_defaults=DEFAULTS, resume=True)
            self.assertEqual(m['summary']['reused'], 0)
            self.assertEqual(audit_batch(source, out)['feature_totals']['graphic_stroke_types'], {'dot': 1})

    def test_cli_strict_and_unsupported_preserve_previous_fpl(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); output = base / 'demo.fpl'; report = base / 'report.json'; output.write_bytes(b'previous')
            cmd = [sys.executable, '-B', '-m', 'src.footprint_converter', str(CONTROL), str(output), '--report', str(report), '--strict']
            result = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(output.read_bytes(), b'previous')
            self.assertEqual(json.loads(report.read_text())['status'], 'rejected_loss')
            source = base / 'unsupported.kicad_mod'
            source.write_text('(footprint "Demo" ' + line('bogus') + source_pad() + ')')
            cmd[4] = str(source); cmd.remove('--strict')
            result = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(output.read_bytes(), b'previous')


if __name__ == '__main__':
    unittest.main()
