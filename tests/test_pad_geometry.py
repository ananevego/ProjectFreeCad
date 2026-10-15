"""Native pad restrictions and exact custom-rectangle proof, before quantization."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.footprint_converter.audit import audit_batch, inventory, read_pads
from src.footprint_converter.batch import run_batch
from src.footprint_converter.errors import ConversionError, LossyConversionError, PadGeometryError
from src.footprint_converter.model import ApertureSettings
from src.footprint_converter.parser import parse_footprint, parse_sexpr
from src.footprint_converter.pipeline import convert_detailed
from test_footprint_converter import source_pad

PROJECT = Path(__file__).resolve().parents[1]
MEDIUM = PROJECT/'tests/fixtures/medium'
DEFAULTS = ApertureSettings(.05, 0, 0)


def primitive(x1, y1, x2, y2):
    return f'(gr_poly (pts (xy {x1} {y1})(xy {x2} {y1})(xy {x2} {y2})(xy {x1} {y2})) (width 0)(fill yes))'


def custom(primitives=None, size='1 1', at='1 2 90', layers='"F.Cu" "F.Mask" "F.Paste"', extra=''):
    if primitives is None:
        primitives = primitive(-1, -.5, 1, .5)
    return source_pad(shape='custom', size=size, at=at, layers=layers,
        extra=f'(options (anchor rect)(clearance outline)) (primitives {primitives}) {extra}')


def root(body):
    return parse_sexpr('(footprint "Demo" ' + body + ')')


def converted(body, **kwargs):
    kwargs.setdefault('aperture_defaults', DEFAULTS)
    return convert_detailed(root(body), **kwargs)


class PadGeometryTests(unittest.TestCase):
    def test_circular_equivalents_keep_same_native_hole_and_pad_bytes(self):
        baseline = converted(source_pad(kind='thru_hole', layers='"*.Cu" "*.Mask"', extra='(drill .9)'))
        for drill in ('(drill oval .9 .9)', '(drill .9 (offset 0 0))', '(drill oval .9 (offset -0 0))'):
            r = converted(source_pad(kind='thru_hole', layers='"*.Cu" "*.Mask"', extra=drill))
            self.assertEqual(r.fpl, baseline.fpl)
            d = [d for d in r.report['diagnostics'] if d['code'] == 'DRILL_EQUIVALENT_NORMALIZED']
            self.assertEqual(len(d), 1); self.assertEqual(d[0]['severity'], 'info')
            self.assertEqual(r.report['pad_geometry']['normalized_pads'][0]['drill_equivalence']['circular_diameter_mm'], .9)

    def test_slots_and_nonzero_offsets_return_structured_native_reasons(self):
        cases = [('(drill oval .6 1.7)', 'DRILL_SLOT_UNSUPPORTED'),
                 ('(drill .9 (offset 0 -.5))', 'PAD_OFFSET_UNSUPPORTED'),
                 ('(drill oval .9 .9 (offset .1 0))', 'PAD_OFFSET_UNSUPPORTED')]
        for drill, code in cases:
            raw = root(source_pad(kind='thru_hole', layers='"*.Cu" "*.Mask"', extra=drill)); before = deepcopy(raw)
            with self.assertRaises(PadGeometryError) as caught:
                convert_detailed(raw, aperture_defaults=DEFAULTS)
            self.assertEqual(raw, before)
            r = caught.exception.report
            self.assertEqual((r['status'], r['diagnostics'][0]['code']), ('failed', code))
            self.assertEqual(r['pad_geometry']['source_pad'], raw[2])
            self.assertFalse(r['pad_geometry']['manufacturing_validated'])

    def test_distinct_slot_axes_are_not_rounded_into_a_circular_hole(self):
        with self.assertRaisesRegex(PadGeometryError, 'slot drill'):
            converted(source_pad(kind='thru_hole', extra='(drill oval 1 1.000001)'))

    def test_malformed_duplicate_or_nonfinite_drill_fields_reject(self):
        for drill in ('(drill)', '(drill oval)', '(drill -1)', '(drill nan)', '(drill inf)',
                      '(drill .9 .8)', '(drill .9 (offset 0))', '(drill .9 (offset 0 nan))',
                      '(drill .9 (offset 0 0)(offset 0 0))', '(drill .9)(drill .9)', '(drill .9 (other 0 0))'):
            with self.assertRaises(ConversionError):
                converted(source_pad(kind='thru_hole', extra=drill))

    def test_custom_rectangle_preserves_one_electrical_anchor_and_native_geometry(self):
        r = converted(custom())
        expected = converted(source_pad(shape='rect', size='2 1', at='1 2 90'))
        self.assertEqual(r.fpl, expected.fpl)
        pads = read_pads(r.fpl)[1]
        self.assertEqual(len(pads), 1)
        self.assertEqual((pads[0]['name'], pads[0]['x'], pads[0]['y'], pads[0]['angle']), ('1', 1000000, -2000000, 270))
        self.assertEqual(r.report['pad_geometry']['normalized_pads'][0]['rectangle_proof']['union_area_mm2'], 2)

    def test_reduction_keeps_raw_and_typed_source_custom_anchor_unchanged(self):
        raw = root(custom()); before = deepcopy(raw); fp = parse_footprint(raw)
        self.assertEqual((fp.pads[0].shape, fp.pads[0].width, fp.pads[0].height), ('custom', 1., 1.))
        r = convert_detailed(raw, aperture_defaults=DEFAULTS)
        detail = r.report['pad_geometry']['normalized_pads'][0]
        self.assertEqual(raw, before); self.assertEqual(detail['source_raw'], raw[2])
        self.assertEqual(detail['source']['shape'], 'custom'); self.assertEqual(detail['native']['shape'], 'rect')
        self.assertTrue(detail['rectangle_proof']['union_equals_centred_rectangle'])

    def test_union_proof_handles_tiling_overlap_duplicates_and_empty_primitives(self):
        for shapes in (primitive(-1, -.5, 0, .5) + primitive(0, -.5, 1, .5),
                       primitive(-1, -.5, 1, .5) * 3):
            p = converted(custom(shapes)).report['pad_geometry']['normalized_pads'][0]['rectangle_proof']
            self.assertEqual((p['union_area_mm2'], p['bounding_area_mm2'], p['uncovered_area_mm2']), (2, 2, 0))
        r = converted(custom(''))
        self.assertEqual(r.fpl, converted(source_pad(at='1 2 90', size='1 1')).fpl)

    def test_nonrectangular_disconnected_or_holed_union_never_uses_its_bounding_box(self):
        cases = [primitive(-1, .5, 1, 1) + primitive(-1, -1, 1, -.5),
                 primitive(2, -.5, 3, .5),
                 primitive(-1, -1, -.75, 1) + primitive(.75, -1, 1, 1) + primitive(-1, -1, 1, -.75) + primitive(-1, .75, 1, 1)]
        for shapes in cases:
            with self.assertRaises(PadGeometryError) as caught: converted(custom(shapes))
            r = caught.exception.report
            self.assertEqual(r['diagnostics'][0]['code'], 'CUSTOM_PAD_NONRECTANGULAR')
            self.assertGreater(r['pad_geometry']['proof']['uncovered_area_mm2'], 0)

    def test_one_nm_notch_is_detected_before_ten_nm_grid_rounding(self):
        shapes = primitive(-1, .5, 1, 1) + primitive(-1, -1, 1, -.5)
        with self.assertRaises(PadGeometryError) as caught:
            converted(custom(shapes, size='1.999998 1'))
        self.assertAlmostEqual(caught.exception.report['pad_geometry']['proof']['uncovered_area_mm2'], .000002, places=12)

    def test_sub_nm_coordinates_and_odd_nm_anchor_are_outside_exact_integer_source_profile(self):
        for body in (custom(size='1.000001 1'), custom(primitive(-1.0000001, -.5, 1, .5))):
            with self.assertRaises(ConversionError): converted(body)

    def test_duplicate_or_extra_custom_geometry_and_aperture_fields_do_not_choose_one_silently(self):
        for extra in ('(at 3 4)', '(size 2 2)', '(layers F.Cu)',
                      '(solder_mask_margin .1)(solder_mask_margin .2)'):
            with self.assertRaises(ConversionError): converted(custom(extra=extra))
        with self.assertRaises(ConversionError):
            converted(custom().replace('(at 1 2 90)', '(at 1 2 90 extra)'))
        with self.assertRaises(ConversionError):
            converted('(solder_paste_ratio 0)(solder_paste_ratio .1)'+custom())

    def test_offset_rectangular_union_does_not_move_source_connection_point(self):
        with self.assertRaises(PadGeometryError) as caught:
            converted(custom(primitive(-.5, -.5, 1.5, .5)))
        self.assertEqual(caught.exception.report['diagnostics'][0]['code'], 'CUSTOM_PAD_OFFSET_UNSUPPORTED')

    def test_profile_rejects_circle_anchor_stroked_polygon_other_primitives_and_excess_complexity(self):
        cases = [custom().replace('(anchor rect)', '(anchor circle)'),
                 custom().replace('(width 0)', '(width .1)'),
                 custom().replace('(fill yes)', '(fill no)'),
                 custom('(gr_circle (center 0 0)(end 1 0)(width 0)(fill yes))'),
                 custom(primitive(-1, -.5, 1, .5) * 33),
                 custom().replace('(xy 1 -0.5)', '(xy .8 -.3)'),
                 custom().replace('(clearance outline)', '(clearance convexhull)'),
                 custom().replace('(width 0)', '(width 0)(width 0)'),
                 custom(primitive(-2000, -.5, 2000, .5), at='0 0 90')]
        for body in cases:
            with self.assertRaises(ConversionError): converted(body)

    def test_custom_apertures_require_resolved_nonnegative_margins_and_zero_paste_ratio(self):
        for options in (ApertureSettings(), ApertureSettings(-.01, 0, 0),
                        ApertureSettings(.05, -.01, 0), ApertureSettings(.05, 0, .1)):
            with self.assertRaises(PadGeometryError) as caught: converted(custom(), aperture_defaults=options)
            self.assertEqual(caught.exception.report['diagnostics'][0]['code'], 'CUSTOM_PAD_APERTURE_UNSUPPORTED')
        # No source apertures: no default mask/paste values need to be guessed.
        converted(custom(layers='"F.Cu"'), aperture_defaults=ApertureSettings())

    def test_custom_margin_inheritance_local_override_bottom_and_rotation(self):
        body = custom(at='1 2 45', layers='"B.Cu" "B.Mask" "B.Paste"', extra='(solder_mask_margin .1)(solder_paste_margin .2)(solder_paste_margin_ratio 0)')
        r = converted(body)
        p = read_pads(r.fpl)[1][0]
        self.assertEqual(p['angle'], 315)
        self.assertEqual(p['records']['top_pad'], [0, 0, 0, 0, 0])
        self.assertEqual(p['records']['bottom_pad'], [3, 1000000, 1000000, 1000000, 0])
        self.assertEqual(p['records']['bottom_mask'], [4, 1200000, 1100000, 1100000, 100000])
        self.assertEqual(p['records']['bottom_paste'], [4, 1400000, 1200000, 1200000, 200000])

    def test_custom_primitive_settings_loss_is_explicit_and_strict_rejects(self):
        with self.assertRaises(LossyConversionError) as caught: converted(custom(), strict=True)
        diagnostics = caught.exception.report['diagnostics']
        self.assertTrue(any(d['code'] == 'CUSTOM_PAD_RECT_FLATTENED' and d['severity'] == 'loss' for d in diagnostics))
        self.assertEqual(caught.exception.report['counts']['written_pins'], 1)

    def test_electrical_identity_mapping_and_native_record_count_stay_one_to_one(self):
        from src.component_converter.links import pin_mapping
        from src.component_converter.records import read_fpl_links
        from test_symbol_electrical import modern
        mapping = pin_mapping(modern(('passive',)).get_symbol('Base'), parse_footprint(root(custom())))
        self.assertTrue(mapping['verified'])
        self.assertEqual(read_fpl_links(converted(custom()).fpl)['numbers'], ['1'])

    def test_real_medium_remaining_reasons_and_exact_missing_areas_are_fixed(self):
        expected = {'LFPAK33': .65, 'SOT-89-3': 1.228675, 'Vishay_PowerPAK_SC70-6L_Single': .245}
        for name, missing in expected.items():
            raw = parse_sexpr((MEDIUM/'Package_TO_SOT_SMD.pretty'/(name+'.kicad_mod')).read_text())
            with self.assertRaises(PadGeometryError) as caught: convert_detailed(raw, aperture_defaults=DEFAULTS)
            self.assertEqual(caught.exception.report['diagnostics'][0]['code'], 'CUSTOM_PAD_NONRECTANGULAR')
            self.assertAlmostEqual(caught.exception.report['pad_geometry']['proof']['uncovered_area_mm2'], missing)
        p = MEDIUM/'Package_DIP.pretty/Vishay_HVM-DIP-3_W7.62mm.kicad_mod'
        with self.assertRaises(PadGeometryError) as caught: convert_detailed(parse_sexpr(p.read_text()))
        self.assertEqual(caught.exception.report['pad_geometry']['shape_offset_mm'], (0., -.5))

    def test_inventory_distinguishes_literal_source_shapes_and_native_limitations(self):
        r = inventory(root(custom()))
        self.assertEqual(r['pad_shapes'], {'custom': 1})
        self.assertEqual(r['pad_geometry_cases'][0]['geometry_status'], 'equivalent_geometry')
        r = inventory(root(source_pad(kind='thru_hole', extra='(drill oval .6 1.7)')))
        self.assertEqual(r['pad_geometry_cases'][0]['code'], 'DRILL_SLOT_UNSUPPORTED')

    def test_saved_synthetic_pad_control_is_reproducible(self):
        path = PROJECT/'tests/fixtures/pad-geometry/PadGeometry_Control.kicad_mod'
        r = convert_detailed(parse_sexpr(path.read_text()), aperture_defaults=DEFAULTS)
        self.assertEqual(r.fpl.encode('cp1251'), (PROJECT/'output/PadGeometry_Control.fpl').read_bytes())
        self.assertEqual(json.loads(json.dumps(r.report)), json.loads((PROJECT/'output/PadGeometry_Control.geometry-report.json').read_text()))

    def test_custom_component_bundle_keeps_one_pin_and_relocates_without_models(self):
        from src.component_converter import export_bundle, verify_bundle
        from test_symbol_converter import library, symbol, pin
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'source'; source.mkdir()
            (source/'Demo.kicad_mod').write_text('(footprint Demo '+custom()+')')
            (source/'Demo.kicad_sym').write_text(library(symbol(body='(symbol "Base_1_1" '+pin('1').replace('input line','passive line')+')')))
            config = dict(schema_version=1, footprint_libraries={'Test':'source'},
                aperture_defaults=dict(mask_margin=.05,paste_margin=0,paste_ratio=0),
                components=[dict(id='CustomRect',symbol_library='source/Demo.kicad_sym',symbol='Base',footprint='Test:Demo',reference='U1')])
            path=base/'components.json';path.write_text(json.dumps(config))
            out=base/'bundle';r=export_bundle(path,out,stl_root=base/'missing-models',allow_missing_models=True)
            self.assertEqual(r['summary']['generated_components'],1)
            self.assertEqual(r['summary']['complete_chains'],0)
            self.assertTrue(r['components'][0]['pin_mapping']['verified'])
            verify_bundle(out);moved=base/'relocated';out.rename(moved);verify_bundle(moved)

    def test_audit_recomputes_normalization_proof_and_rejects_rehashed_report_tampering(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'source'; source.mkdir(); (source/'Demo.kicad_mod').write_text('(footprint Demo '+custom()+')')
            out = base/'batch'; run_batch(source, out, aperture_defaults=DEFAULTS)
            self.assertEqual(audit_batch(source, out)['summary']['target_records_validated'], 1)
            manifest = out/'manifest.json'; m = json.loads(manifest.read_text()); e = m['entries'][0]; report = out/e['report_file']
            r = json.loads(report.read_text()); r['pad_geometry']['normalized_pads'][0]['rectangle_proof']['union_area_mm2'] = 99
            report.write_text(json.dumps(r)); e['report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest(); manifest.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, 'normalization'): audit_batch(source, out)

    def test_cli_native_refusal_and_strict_preserve_previous_fpl_and_structured_report(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'Demo.kicad_mod'; output = base/'Demo.fpl'; report = base/'Demo.json'
            output.write_bytes(b'previous')
            cmd = [sys.executable, '-B', '-m', 'src.footprint_converter', str(source), str(output), '--report', str(report)]
            source.write_text('(footprint Demo '+source_pad(kind='thru_hole', extra='(drill oval .6 1.7)')+')')
            r = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr); self.assertEqual(output.read_bytes(), b'previous')
            self.assertEqual(json.loads(report.read_text())['diagnostics'][0]['code'], 'DRILL_SLOT_UNSUPPORTED')
            source.write_text('(footprint Demo '+custom()+')')
            r = subprocess.run(cmd+['--strict','--default-mask-margin','.05','--default-paste-margin','0','--default-paste-ratio','0'], cwd=PROJECT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr); self.assertEqual(output.read_bytes(), b'previous')


if __name__ == '__main__': unittest.main()
