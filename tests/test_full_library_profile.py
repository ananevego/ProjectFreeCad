"""Regressions discovered by converting the entire pinned footprint library."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.footprint_converter.audit import audit_batch, read_pads
from src.footprint_converter.batch import run_batch
from src.footprint_converter.errors import ConversionError, LossyConversionError
from src.footprint_converter.model import ApertureSettings
from src.footprint_converter.parser import parse_sexpr
from src.footprint_converter.pipeline import convert_detailed
from test_footprint_converter import decode_fpl, source_pad

FIXTURES = Path(__file__).parent / 'fixtures/full-library'
DEFAULTS = ApertureSettings(.05, 0, 0)


class FullLibraryProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.models = Path(self.temporary.name) / 'models'

    def convert(self, tree, **options):
        return convert_detailed(tree, stl_root=self.models, aperture_defaults=DEFAULTS, **options)

    def test_unchanged_real_source_hashes_and_license_are_fixed(self):
        provenance = json.loads((FIXTURES / 'provenance.json').read_text())
        self.assertEqual(len(provenance['files']), 3)
        for record in provenance['files'] + [provenance['license']]:
            raw = (FIXTURES / record['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
            self.assertEqual(hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest(), record['git_blob_sha1'])

    def test_real_padless_circle_has_outline_bounds_and_no_invented_terminal(self):
        tree = parse_sexpr((FIXTURES / 'Battery.pretty/Battery_CR1225.kicad_mod').read_text())
        before = deepcopy(tree)
        result = self.convert(tree)
        fields, pins, polys = decode_fpl(result.fpl)
        self.assertEqual(pins, [])
        self.assertEqual(fields['n_pins'], [['0']])
        self.assertGreater(len(polys[0]['points']), 10)
        bounds = list(map(int, fields['sel_rect'][0]))
        self.assertLess(bounds[0], -6200000)
        self.assertGreater(bounds[2], 6200000)
        self.assertEqual(result.report['counts']['written_pins'], 0)
        self.assertIn('PADLESS_GRAPHIC', {d['code'] for d in result.report['diagnostics']})
        self.assertEqual(tree, before)

    def test_padless_filled_and_patterned_graphics_are_rendered_before_bounds(self):
        for graphic in ['(fp_rect (start -1 -2) (end 1 2) (stroke (width .1) (type solid)) (fill solid) (layer "F.SilkS"))',
                        '(fp_line (start -1 -2) (end 1 2) (stroke (width .1) (type dash)) (layer "B.SilkS"))']:
            result = self.convert(parse_sexpr('(footprint "Graphic" ' + graphic + ')'))
            self.assertEqual(read_pads(result.fpl)[1], [])
            self.assertIn('outline_polyline:', result.fpl)

    def test_empty_or_only_skipped_graphics_fail_explicitly(self):
        for body in ['', '(fp_line (start 0 0) (end 1 0) (stroke (width .1) (type solid)) (layer "F.CrtYd"))']:
            with self.assertRaisesRegex(ConversionError, 'supported graphic outline'):
                self.convert(parse_sexpr('(footprint "Empty" ' + body + ')'))

    def test_real_unicode_description_requires_explicit_loss_and_retains_source(self):
        tree = parse_sexpr((FIXTURES / 'Capacitor_SMD.pretty/CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D.kicad_mod').read_text())
        before = deepcopy(tree)
        with self.assertRaises(UnicodeEncodeError):
            self.convert(tree).fpl.encode('cp1251')
        result = self.convert(tree, description_policy='ascii-escape-with-loss')
        result.fpl.encode('cp1251')
        self.assertIn('[U+00BA]C', result.fpl)
        self.assertIn('ºC', result.report['description']['source'])
        self.assertTrue(any(d['code'] == 'DESCRIPTION_ASCII_ESCAPED' and d['severity'] == 'loss'
                            for d in result.report['diagnostics']))
        self.assertEqual(tree, before)
        self.assertEqual(read_pads(self.convert(tree).fpl), read_pads(result.fpl))
        with self.assertRaises(LossyConversionError):
            self.convert(tree, description_policy='ascii-escape-with-loss', strict=True)

    def test_ascii_metadata_is_unchanged_and_unicode_pin_labels_are_not_rewritten(self):
        tree = parse_sexpr('(footprint "Demo" (descr "ASCII") ' + source_pad(name='Ω') + ')')
        original = self.convert(tree)
        escaped = self.convert(tree, description_policy='ascii-escape-with-loss')
        self.assertEqual(original, escaped)
        self.assertIn('pin: "Ω"', escaped.fpl)
        with self.assertRaises(UnicodeEncodeError):
            escaped.fpl.encode('cp1251')
        with self.assertRaisesRegex(ValueError, 'description policy'):
            self.convert(tree, description_policy='unknown')

    def test_description_quotes_controls_and_supplementary_unicode_are_explicit_tokens(self):
        tree = parse_sexpr('(footprint "Demo" ' + source_pad() + ')')
        tree.append(['descr', 'Size 0.100"; line\nnext\t😀'])
        with self.assertRaisesRegex(ConversionError, 'quoted field'):
            self.convert(tree)
        escaped = self.convert(tree, description_policy='ascii-escape-with-loss')
        self.assertIn('0.100[U+0022]; line[U+000A]next[U+0009][U+1F600]', escaped.fpl)
        self.assertEqual(escaped.report['description']['source'], 'Size 0.100"; line\nnext\t😀')
        escaped.fpl.encode('cp1251')

    def test_real_samtec_description_quotes_no_longer_block_copper_conversion(self):
        path = next((FIXTURES / 'Connector_Samtec_HLE_SMD.pretty').glob('*.kicad_mod'))
        tree = parse_sexpr(path.read_text())
        with self.assertRaisesRegex(ConversionError, 'quoted field'):
            self.convert(tree)
        result = self.convert(tree, description_policy='ascii-escape-with-loss')
        self.assertIn('.100[U+0022]', result.fpl)
        pads = read_pads(result.fpl)[1]
        self.assertEqual([pad['name'] for pad in pads if pad['records']['top_pad'][0]], ['1', '2', '3', '4'])
        self.assertEqual(sum(pad['hole'] > 0 for pad in pads), 4)
        result.fpl.encode('cp1251')

    def test_batch_and_independent_audit_cover_real_padless_and_unicode_cases(self):
        batch = Path(self.temporary.name) / 'batch'
        result = run_batch(FIXTURES, batch, stl_root=self.models, aperture_defaults=DEFAULTS,
                           description_policy='ascii-escape-with-loss')
        self.assertEqual(result['summary']['generated'], 3)
        audit = audit_batch(FIXTURES, batch, FIXTURES / 'provenance.json')
        self.assertEqual(audit['summary']['target_records_validated'], 3)
        self.assertFalse(audit['target_gui_validated'])
        self.assertEqual(run_batch(FIXTURES, batch, resume=True, stl_root=self.models,
                                  aperture_defaults=DEFAULTS, description_policy='ascii-escape-with-loss')['summary']['reused'], 3)
        # Selecting preserve changes cache identity and restores the encoding refusal.
        changed = run_batch(FIXTURES, batch, resume=True, stl_root=self.models, aperture_defaults=DEFAULTS)
        self.assertEqual((changed['summary']['reused'], changed['summary']['failed']), (0, 2))


if __name__ == '__main__':
    unittest.main()
