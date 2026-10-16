"""Formatting/default-function losses preserve source identity and pin geometry."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.symbol_converter import parse_library, SymbolParseError
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.batch import run_batch
from src.symbol_converter.batch_records import verify_source_pins
from src.symbol_converter.pin_labels import plain_pin_name
from src.component_converter import export_bundle, verify_bundle
from test_symbol_converter import library, symbol, pin
from test_symbol_multiunit import multi
from test_footprint_converter import source_pad

FIXTURES = Path(__file__).parent / 'fixtures/symbol-batch'


def source_pin(name='~{RESET}', extra=''):
    return parse_library(library(symbol(body='(symbol "Base_1_1" ' + pin(name=name, extra=extra) + ')')))


class SymbolPinLabelsTests(unittest.TestCase):
    def test_overbar_loss_is_explicit_and_does_not_change_source_or_endpoint(self):
        source = source_pin()
        before = deepcopy(source)
        with self.assertRaisesRegex(SymbolParseError, 'markup'):
            convert_symbol(source, 'Base')
        result = convert_symbol(source, 'Base', pin_name_policy='plain-overbar-with-loss')
        self.assertEqual(source, before)
        poly = next(p for p in result.document.components[0].polylines if p.pin)
        self.assertEqual(poly.description.value, 'RESET')
        self.assertEqual((poly.pin.value, poly.corners[-1].x, poly.corners[-1].y), ('1', -5080000, 0))
        self.assertEqual(result.report['source_symbol']['units'][0]['pins'][0]['name'], '~{RESET}')
        self.assertTrue(any(d['code'] == 'SYMBOL_PIN_OVERBAR_REMOVED' and d['severity'] == 'loss' for d in result.report['diagnostics']))
        self.assertEqual(verify_source_pins(source, 'Base', result.cds, result.report)['pins'], 1)

    def test_balanced_groups_nested_partial_and_malformed_names(self):
        for name, expected in [('~{FO}O', 'FOO'), ('A/~{RESET}', 'A/RESET'), ('~{~{CLK}}', 'CLK')]:
            self.assertEqual(plain_pin_name(name, 'plain-overbar-with-loss'), (expected, True))
        for name in ('~{', '~{}', '~RESET~', '~{A^B}', '~{' * 17 + 'A' + '}' * 17):
            with self.assertRaises(ValueError):
                plain_pin_name(name, 'plain-overbar-with-loss')

    def test_primary_alternate_policy_preserves_raw_definitions_and_default_geometry(self):
        extra='(alternate "~{ALT}" output inverted)'
        source = source_pin(name='MAIN', extra=extra)
        before = deepcopy(source)
        with self.assertRaisesRegex(SymbolParseError, 'alternate pin'):
            convert_symbol(source, 'Base')
        result = convert_symbol(source, 'Base', alternate_pin_policy='primary-with-loss')
        baseline = convert_symbol(source_pin(name='MAIN'), 'Base')
        self.assertEqual(result.cds, baseline.cds)
        self.assertEqual(source, before)
        raw_alternates = result.report['source_symbol']['units'][0]['pins'][0]['alternates']
        self.assertEqual(raw_alternates[0], dict(name='~{ALT}', electrical_type='output', graphic_style='inverted'))
        diagnostic = next(d for d in result.report['diagnostics'] if d['code'] == 'SYMBOL_ALTERNATE_PINS_PRIMARY_ONLY')
        diagnostic['context']['source_alternates'][0]['name'] = 'edited report'
        self.assertEqual(source.get_symbol('Base').units[0].pins[0].alternates[0]['name'], '~{ALT}')

    def test_strict_rejects_losses_and_plain_controls_are_byte_identical(self):
        normal = source_pin(name='NORMAL')
        baseline = convert_symbol(normal, 'Base')
        enabled = convert_symbol(normal, 'Base', pin_name_policy='plain-overbar-with-loss', alternate_pin_policy='primary-with-loss')
        self.assertEqual(baseline, enabled)
        with self.assertRaises(LossySymbolConversionError):
            convert_symbol(source_pin(), 'Base', pin_name_policy='plain-overbar-with-loss', strict=True)
        with self.assertRaises(LossySymbolConversionError):
            convert_symbol(source_pin(name='MAIN', extra='(alternate "ALT" input line)'), 'Base', alternate_pin_policy='primary-with-loss', strict=True)

    def test_compound_settings_are_kept_when_only_later_unit_uses_new_policies(self):
        source = multi()
        source.symbols['Base'].units[-1].pins[0].name = '~{LATER}'
        source.symbols['Base'].units[-1].pins[0].alternates = [dict(name='ALT', electrical_type='input', graphic_style='line')]
        result = convert_symbol(source, 'Base', pin_name_policy='plain-overbar-with-loss', alternate_pin_policy='primary-with-loss')
        self.assertEqual(result.report['conversion_settings']['pin_name_policy'], 'plain-overbar-with-loss')
        self.assertEqual(result.report['conversion_settings']['alternate_pin_policy'], 'primary-with-loss')
        self.assertEqual(verify_source_pins(source, 'Base', result.cds, result.report)['pins'], 4)

    def test_real_libraries_hashes_and_output_source_identity(self):
        provenance = json.loads((FIXTURES / 'provenance.json').read_text())
        for r in provenance['files'] + [provenance['license']]:
            raw = (FIXTURES / r['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), r['sha256'])
        for file, name in [('MCU_Puya.kicad_sym', 'PY32F002AF15P'), ('CPLD_Renesas.kicad_sym', 'SLG46826G')]:
            source = parse_library((FIXTURES / file).read_text())
            result = convert_symbol(source, name, pin_name_policy='plain-overbar-with-loss', alternate_pin_policy='primary-with-loss',
                                    no_connect_policy='connectable-with-loss', hidden_pin_policy='reveal-with-loss')
            self.assertGreater(verify_source_pins(source, name, result.cds, result.report)['pins'], 1)

    def test_batch_policies_invalidate_cache_without_affecting_other_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'source').mkdir()
            (root / 'source/Demo.kicad_sym').write_text(library(symbol(body='(symbol "Base_1_1" ' + pin(name='~{RESET}') + ')')))
            args = (root / 'source', root / 'batch')
            self.assertEqual(run_batch(*args)['summary']['failed'], 1)
            self.assertEqual(run_batch(*args, resume=True, pin_name_policy='plain-overbar-with-loss')['summary']['generated'], 1)
            self.assertEqual(run_batch(*args, resume=True, pin_name_policy='plain-overbar-with-loss')['summary']['reused'], 1)
            self.assertEqual(run_batch(*args, resume=True)['summary']['failed'], 1)

    def test_component_config_passes_explicit_policies_and_preserves_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, footprints = root / 'source', root / 'footprints'
            source.mkdir(); footprints.mkdir()
            (source / 'Demo.kicad_sym').write_text(library(symbol(body='(symbol "Base_1_1" ' +
                pin(name='~{RESET}', extra='(alternate "ALT" output line)') + ')')))
            (footprints / 'One.kicad_mod').write_text('(footprint "One" ' + source_pad() + ')')
            config = dict(schema_version=1, footprint_libraries=dict(Demo='footprints'),
                symbol_pin_name_policy='plain-overbar-with-loss', symbol_alternate_pin_policy='primary-with-loss',
                aperture_defaults=dict(mask_margin=.05, paste_margin=0, paste_ratio=0),
                components=[dict(id='Control', symbol_library='source/Demo.kicad_sym', symbol='Base', footprint='Demo:One')])
            path = root / 'config.json'; path.write_text(json.dumps(config))
            result = export_bundle(path, root / 'bundle', stl_root=root / 'models', allow_missing_models=True)
            self.assertEqual(result['components'][0]['status'], 'generated_with_loss')
            self.assertTrue(result['components'][0]['source_target_mapping_verified'])
            self.assertEqual(result['settings']['symbol_alternate_pin_policy'], 'primary-with-loss')
            self.assertEqual(verify_bundle(root / 'bundle'), result)
            config['symbol_pin_name_policy'] = 'unknown'; path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'Pin name policy'):
                export_bundle(path, root / 'invalid', allow_missing_models=True)


if __name__ == '__main__':
    unittest.main()
