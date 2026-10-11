"""Source text semantics and explicit losses in the FreePCB text subset."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.footprint_converter import ApertureSettings, ConversionError, LossyConversionError, convert_detailed, parse_sexpr
from test_footprint_converter import decode_fpl, source_pad

PROJECT = Path(__file__).resolve().parents[1]


def text(content='label', kind='user', extra='', effects='', font='', at='1 2 90',
         layer='F.SilkS', property_name=None):
    prefix = f'property "{property_name}"' if property_name else f'fp_text {kind}'
    return (f'({prefix} "{content}" (at {at}) (layer {layer}) {extra} '
            f'(effects (font (size 0.8 0.8) (thickness 0.1) {font}) {effects}))')


class TextFieldsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.stl_root = Path(self.directory.name)

    def convert(self, body, **options):
        return convert_detailed(parse_sexpr(f'(footprint "Texts" {source_pad()} {body})'),
                                stl_root=self.stl_root, **options)

    def test_legacy_reference_value_tokens_require_explicit_binding(self):
        for content in ('%R', '%V', 'ref=%R value=%V', '%R/${REFERENCE} %V/${VALUE}'):
            with self.subTest(content=content):
                result = self.convert(text(content))
                self.assertNotIn('text', decode_fpl(result.fpl)[0])
                self.assertEqual(result.report['source_texts'][0]['content'], content)
                diagnostic = next(d for d in result.report['diagnostics'] if d['code']=='TEXT_VARIABLE_UNRESOLVED')
                self.assertEqual(diagnostic['severity'], 'loss')
                with self.assertRaises(LossyConversionError):
                    self.convert(text(content), strict=True)

    def test_legacy_and_modern_bindings_produce_same_static_text(self):
        bindings = {'REFERENCE': 'R17', 'VALUE': '10k'}
        for content in ('ref=%R value=%V', 'ref=${REFERENCE} value=${VALUE}'):
            result = self.convert(text(content), text_variables=bindings)
            record = decode_fpl(result.fpl)[0]['text'][0]
            self.assertEqual(record, ['ref=R17 value=10k', '800000', '1000000', '-2000000', '270', '100000', '0', '4'])
            self.assertTrue(any(w.startswith('TEXT_VARIABLE_BOUND:') for w in result.warnings))
            self.assertEqual(result.report['text_variable_bindings'], bindings)

    def test_unrelated_percent_sequences_and_plain_tilde_are_literal(self):
        for content in ('50% tolerance', '%r %v %X', '~approx', 'at 100%'):
            result = self.convert(text(content))
            self.assertEqual(decode_fpl(result.fpl)[0]['text'][0][0], content)

    def test_text_content_named_like_a_flag_is_not_an_attribute(self):
        for content in ('hide', 'unlocked', 'bold', 'italic', 'knockout'):
            with self.subTest(content=content):
                result = self.convert(text(content))
                self.assertEqual(decode_fpl(result.fpl)[0]['text'][0][0], content)
                self.assertFalse(result.report['source_texts'][0]['hidden'])
                self.assertTrue(result.report['source_texts'][0]['keep_upright'])

    def test_legacy_locked_prefix_and_literal_locked_content_are_distinct(self):
        source = text('label').replace('fp_text user "label"', 'fp_text user locked "label"')
        result = self.convert(source)
        self.assertEqual(decode_fpl(result.fpl)[0]['text'][0][0], 'label')
        literal = self.convert(text('locked'))
        self.assertEqual(decode_fpl(literal.fpl)[0]['text'][0][0], 'locked')

    def test_recursive_and_unrepresentable_binding_values_are_rejected(self):
        for value in ('${VALUE}', '%R', '%V', 'unsafe"quote', 'unsafe\nnewline'):
            with self.subTest(value=value), self.assertRaises(ConversionError):
                self.convert(text('%R'), text_variables={'REFERENCE': value})

    def test_all_supported_hide_syntaxes_suppress_user_and_native_fields(self):
        for extra, effects in [('hide', ''), ('(hide)', ''), ('(hide yes)', ''),
                               ('', 'hide'), ('', '(hide)'), ('', '(hide yes)')]:
            for kind in ('user', 'reference', 'value'):
                with self.subTest(extra=extra, effects=effects, kind=kind):
                    result = self.convert(text('%R', kind, extra, effects))
                    fields = decode_fpl(result.fpl)[0]
                    self.assertTrue(result.report['source_texts'][0]['hidden'])
                    self.assertNotIn('text', fields)
                    if kind != 'user':
                        self.assertEqual(fields['ref_text' if kind=='reference' else 'value_text'][0][0], '0')
                    self.assertFalse(any(w.startswith('TEXT_VARIABLE_UNRESOLVED:') for w in result.warnings))

    def test_explicit_hide_no_is_visible_in_both_locations(self):
        for extra, effects in [('(hide no)', ''), ('', '(hide no)')]:
            result = self.convert(text(extra=extra, effects=effects))
            self.assertFalse(result.report['source_texts'][0]['hidden'])
            self.assertEqual(len(decode_fpl(result.fpl)[0]['text']), 1)

    def test_malformed_and_duplicate_text_flags_fail_explicitly(self):
        invalid = [text(extra=x) for x in ('(hide maybe)', '(hide yes no)', '(hide (yes))',
                                           'hide (hide no)', '(hide) (hide yes)',
                                           '(unlocked maybe)', '(unlocked yes) (unlocked no)')]
        invalid += [text(extra='(hide no)', effects='hide'),
                    text(at='1 2 unlocked', extra='(unlocked yes)'),
                    text(extra='(effects (font (size 1 1)))')]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ConversionError):
                self.convert(body)

    def test_font_boolean_no_is_inert_and_enabled_styles_fail(self):
        for font in ('(bold no)', '(italic no)', '(bold no) (italic no)'):
            self.assertIn('text', decode_fpl(self.convert(text(font=font)).fpl)[0])
        for font in ('bold', '(bold)', '(bold yes)', 'italic', '(italic)', '(italic yes)',
                     '(bold maybe)', '(italic (yes))', '(bold no) (bold yes)',
                     '(face "Other")', '(line_spacing 1.5)'):
            with self.subTest(font=font), self.assertRaises(ConversionError):
                self.convert(text(font=font))

    def test_unlocked_without_angle_and_modern_flag_retain_source_policy(self):
        for at, extra, keep_upright, angle in [('1 2', '', True, '0'),
                ('1 2 unlocked', '', False, '0'), ('1 2 90 unlocked', '', False, '270'),
                ('1 2 90', '(unlocked yes)', False, '270'),
                ('1 2 90', '(unlocked no)', True, '270')]:
            with self.subTest(at=at, extra=extra):
                result = self.convert(text(at=at, extra=extra))
                self.assertEqual(result.report['source_texts'][0]['keep_upright'], keep_upright)
                self.assertEqual(decode_fpl(result.fpl)[0]['text'][0][4], angle)
                warning = any(w.startswith('TEXT_UPRIGHT_UNVERIFIED:') for w in result.warnings)
                self.assertEqual(warning, keep_upright)
                if warning:
                    self.assertEqual(next(d['severity'] for d in result.report['diagnostics']
                                          if d['code']=='TEXT_UPRIGHT_UNVERIFIED'), 'assumption')

    def test_native_reference_value_keep_dynamic_identity_and_hide(self):
        result = self.convert(text('REF**', kind='reference') +
                              text('100k', kind='value', extra='(hide yes)'))
        fields = decode_fpl(result.fpl)[0]
        self.assertEqual(fields['ref_text'][0], ['800000', '1000000', '-2000000', '270', '100000'])
        self.assertEqual(fields['value_text'][0][0], '0')
        self.assertNotIn('text', fields)
        self.assertNotIn('100k', result.fpl)
        self.assertEqual(result.report['source_texts'][1]['content'], '100k')

    def test_knockout_and_collapsed_text_fail(self):
        for body in (text(layer='F.SilkS knockout'), text(font='(size 1 1)'),
                     text(at='1 2 90 180'), text().replace('(thickness 0.1)', '(thickness 0.000001)'),
                     text(font='(thickness (0.1))')):
            with self.subTest(body=body), self.assertRaises(ConversionError):
                self.convert(body)

    def test_overbar_markup_is_skipped_with_loss_including_bound_values(self):
        for content, bindings in [('~{RESET}', {}), ('~RESET~', {}),
                                  ('%V', {'VALUE': '~{RESET}'})]:
            result = self.convert(text(content), text_variables=bindings)
            self.assertNotIn('text', decode_fpl(result.fpl)[0])
            self.assertEqual(next(d['severity'] for d in result.report['diagnostics']
                                  if d['code']=='TEXT_MARKUP_UNSUPPORTED'), 'loss')

    def test_visible_custom_property_is_static_with_loss_hidden_is_retained(self):
        result = self.convert(text('Maker', property_name='Manufacturer') +
                              text('secret', property_name='Vendor', extra='(hide yes)'))
        self.assertEqual([r[0] for r in decode_fpl(result.fpl)[0]['text']], ['Maker'])
        self.assertEqual(len(result.report['source_texts']), 2)
        self.assertTrue(result.report['source_texts'][1]['hidden'])
        self.assertEqual(result.report['source_texts'][0]['property_name'], 'Manufacturer')
        self.assertEqual(next(d['severity'] for d in result.report['diagnostics']
                              if d['code']=='TEXT_PROPERTY_FLATTENED'), 'loss')
        with self.assertRaises(LossyConversionError):
            self.convert(text('Maker', property_name='Manufacturer'), strict=True)
        user_named_property = self.convert(text('field', property_name='User'))
        self.assertTrue(any(w.startswith('TEXT_PROPERTY_FLATTENED:') for w in user_named_property.warnings))

    def test_cli_legacy_binding_and_invalid_hide_preserve_existing_output(self):
        base = Path(self.directory.name)
        source, output, report = base/'input.kicad_mod', base/'output.fpl', base/'report.json'
        source.write_text(f'(footprint "Texts" {source_pad()} {text("%R")})')
        command = [sys.executable, '-B', '-m', 'src.footprint_converter', str(source), str(output),
                   '--stl-root', str(base/'models'), '--report', str(report), '--text-variable', 'REFERENCE=R17']
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(decode_fpl(output.read_text(encoding='cp1251'))[0]['text'][0][0], 'R17')
        self.assertEqual(json.loads(report.read_text())['source_texts'][0]['content'], '%R')
        previous = output.read_bytes()
        source.write_text(f'(footprint "Texts" {source_pad()} {text(extra="(hide (yes))")})')
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertNotIn('Traceback', run.stderr)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(json.loads(report.read_text())['status'], 'failed')

    def test_official_sod123_control_preserves_pads_fields_and_existing_model_link(self):
        model = self.stl_root/'Diode_SMD.3dshapes/D_SOD-123.stl'
        model.parent.mkdir()
        model.write_bytes(b'metadata-only fixture, no geometry')
        source = parse_sexpr((PROJECT/'tests/fixtures/D_SOD-123.kicad_mod').read_text())
        result = convert_detailed(source, stl_root=self.stl_root,
                                  aperture_defaults=ApertureSettings(0.05, 0, 0))
        fields, pins, polys = decode_fpl(result.fpl)
        self.assertEqual([(p['name'], p['x'], p['y']) for p in pins],
                         [('1', -1650000, 0), ('2', 1650000, 0)])
        for p in pins:
            self.assertEqual(p['top_pad'], (4, 1200000, 450000, 450000, 225000))
            self.assertEqual(p['top_mask'], (4, 1300000, 500000, 500000, 275000))
            self.assertEqual(p['top_paste'], p['top_pad'])
        self.assertEqual(fields['ref_text'][0], ['1000000', '0', '2000000', '0', '150000'])
        self.assertEqual(fields['value_text'][0], ['1000000', '0', '-2100000', '0', '150000'])
        self.assertNotIn('text', fields)
        self.assertEqual(len(result.report['source_texts']), 5)
        self.assertTrue(all(t['hidden'] for t in result.report['source_texts'][2:4]))
        self.assertEqual([p['layer'] for p in polys].count(4), 3)
        self.assertEqual([p['layer'] for p in polys].count(7), 11)
        self.assertEqual(result.report['models'][0]['relative_stl'], 'Diode_SMD.3dshapes/D_SOD-123.stl')
        self.assertFalse(result.report['models'][0]['frame_validated'])
        self.assertEqual((PROJECT/'output/D_SOD-123.fpl').read_bytes(), result.fpl.encode('cp1251'))
        bound = convert_detailed(source, stl_root=self.stl_root,
                                 text_variables={'REFERENCE': 'D1'})
        self.assertEqual(decode_fpl(bound.fpl)[0]['text'][0][0], 'D1')

    def test_sod123_bottom_layer_variation_keeps_copper_and_reports_text_layer_loss(self):
        source = (PROJECT/'tests/fixtures/D_SOD-123.kicad_mod').read_text().replace('"F.', '"B.')
        result = convert_detailed(parse_sexpr(source), stl_root=self.stl_root,
                                  text_variables={'REFERENCE': 'D1'})
        fields, pins, polys = decode_fpl(result.fpl)
        for p in pins:
            self.assertEqual(p['top_pad'], (0, 0, 0, 0, 0))
            self.assertEqual(p['bottom_pad'], (4, 1200000, 450000, 450000, 225000))
        self.assertEqual(fields['text'][0][-1], '8')  # B.Fab -> bottom notes.
        self.assertEqual([p['layer'] for p in polys].count(5), 3)
        self.assertTrue(any(w.startswith('TEXT_FIELD_LAYER: reference') for w in result.warnings))


if __name__ == '__main__':
    unittest.main()
