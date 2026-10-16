"""Per-symbol isolation, recovery, source identity and independent pin auditing."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.symbol_converter import parse_library, SymbolParseError
from src.symbol_converter import batch
from src.symbol_converter.audit import audit_batch
from src.symbol_converter.batch_records import verify_source_pins
from src.symbol_converter.target import convert_symbol
from src.symbol_converter.schemator_format import parse_cds
from src.symbol_converter.schemator_writer import write_cds
from test_symbol_converter import library, symbol, pin
from test_symbol_multiunit import multi


def basic(name='Base', extra=''):
    return symbol(name, body=f'(symbol "{name}_1_1" ' + pin(extra=extra) + ')')


class SymbolBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.output = self.root / 'batch'
        self.path = self.source / 'Demo.kicad_sym'
        self.path.write_text(library(basic(), basic('Hidden', '(hide yes)')))

    def run_batch(self, **options):
        return batch.run_batch(self.source, self.output, **options)

    def test_one_failed_symbol_does_not_abort_other_symbols_and_names_are_stable(self):
        result = self.run_batch()
        self.assertEqual((result['summary']['generated'], result['summary']['failed']), (1, 1))
        self.assertTrue(result['summary']['source_inventory_complete'])
        self.assertEqual(result['summary']['unexpected_errors'], 0)
        entry = result['entries'][0]
        doc = parse_cds((self.output / entry['output_file']).read_text(encoding='cp1251'))
        self.assertEqual(doc.components[0].footprint.value, 'PART')
        self.assertEqual(entry['target_name'], batch.item_name('Demo.kicad_sym', 'Base'))
        self.assertNotEqual(batch.item_name('A.kicad_sym', 'Same'), batch.item_name('B.kicad_sym', 'Same'))
        self.assertNotEqual(batch.item_name('A.kicad_sym', 'a/b'), batch.item_name('A.kicad_sym', 'a_b'))

    def test_resume_reuses_only_verified_success_and_retries_failure(self):
        self.run_batch()
        original = batch.convert_symbol
        with patch.object(batch, 'convert_symbol', wraps=original) as converted:
            result = self.run_batch(resume=True)
        self.assertEqual(converted.call_count, 1)
        self.assertEqual(result['summary']['reused'], 1)
        entry = next(e for e in result['entries'] if e['output_current'])
        (self.output / entry['output_file']).write_text('corrupt')
        self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 0)

    def test_source_options_engine_and_corrupt_cache_invalidate_reuse(self):
        for action in ('source', 'options', 'engine', 'cache'):
            with self.subTest(action=action):
                current = self.run_batch()
                extra = {}
                if action == 'source':
                    self.path.write_text(self.path.read_text() + '\n')
                elif action == 'options':
                    extra['pin_width'] = .3
                elif action == 'cache':
                    path = self.output / current['entries'][0]['state_file']
                    cached = json.loads(path.read_bytes())
                    cached['status'] = []
                    path.write_text(json.dumps(cached))
                with patch.object(batch, 'engine_fingerprint', return_value='changed') if action == 'engine' else patch.object(batch, 'digest', wraps=batch.digest):
                    self.assertEqual(self.run_batch(resume=True, **extra)['summary']['reused'], 0)

    def test_explicit_hidden_policy_generates_both_and_strict_keeps_last_cds(self):
        result = self.run_batch(hidden_pin_policy='reveal-with-loss')
        self.assertEqual(result['summary']['generated'], 2)
        before = [(self.output / e['output_file']).read_bytes() for e in result['entries']]
        strict = self.run_batch(strict=True, hidden_pin_policy='reveal-with-loss')
        self.assertEqual(strict['summary']['rejected_loss'], 2)
        self.assertEqual(before, [(self.output / e['output_file']).read_bytes() for e in strict['entries']])
        self.assertTrue(all(not e['output_current'] for e in strict['entries']))

    def test_limit_reorder_and_removed_symbol_do_not_change_identity_or_ownership(self):
        first = self.run_batch(hidden_pin_policy='reveal-with-loss')
        limited = self.run_batch(limit=1, resume=True, hidden_pin_policy='reveal-with-loss')
        self.assertEqual(limited['summary']['reused'], 1)
        self.assertEqual(self.run_batch(resume=True, hidden_pin_policy='reveal-with-loss')['summary']['reused'], 2)
        self.path.write_text(library(basic('Hidden', '(hide yes)'), basic()))
        reordered = self.run_batch(resume=True, hidden_pin_policy='reveal-with-loss')
        self.assertEqual([e['target_name'] for e in first['entries']], [e['target_name'] for e in reordered['entries']])

    def test_parse_failure_in_one_library_is_recorded_and_other_library_continues(self):
        (self.source / 'Broken.kicad_sym').write_text(library(symbol('NoGeometry', extends='Missing')))
        result = self.run_batch()
        self.assertEqual(result['summary']['total'], 3)
        failed = next(e for e in result['entries'] if e['source'] == 'Broken.kicad_sym')
        self.assertEqual(failed['failure_stage'], 'source_library')
        audit = audit_batch(self.source, self.output)
        self.assertEqual(len(audit['library_errors']), 1)
        self.assertEqual(audit['source_pin_records_validated'], 1)

    def test_malformed_library_inventory_is_explicitly_incomplete(self):
        (self.source / 'Broken.kicad_sym').write_text('(broken')
        result = self.run_batch()
        self.assertFalse(result['summary']['source_inventory_complete'])
        self.assertEqual(result['summary']['inventory_failed_libraries'], 1)
        self.assertEqual(result['status'], 'completed_with_errors')

    def test_unowned_artifact_symlink_and_source_overlap_are_rejected(self):
        destination = self.output / 'symbols' / (batch.item_name('Demo.kicad_sym', 'Base') + '.cds')
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'user-owned')
        with self.assertRaisesRegex(ValueError, 'unowned'):
            self.run_batch()
        self.assertEqual(destination.read_bytes(), b'user-owned')
        destination.unlink()
        destination.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'symlink|escapes'):
            self.run_batch()
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            batch.run_batch(self.source, self.source / 'out')

    def test_item_write_failure_is_isolated_and_keyboard_interrupt_can_resume(self):
        write = batch.atomic_write
        def fail_one(path, raw):
            if path.name == batch.item_name('Demo.kicad_sym', 'Base') + '.report.json':
                raise PermissionError('test denied report')
            return write(path, raw)
        with patch.object(batch, 'atomic_write', side_effect=fail_one):
            result = self.run_batch(hidden_pin_policy='reveal-with-loss')
        self.assertEqual((result['summary']['generated'], result['summary']['failed']), (1, 1))
        with patch.object(batch, 'convert_symbol', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_batch()
        self.assertEqual(self.run_batch(resume=True, hidden_pin_policy='reveal-with-loss')['summary']['generated'], 2)

    def test_audit_checks_hashes_source_numbers_and_provenance(self):
        self.run_batch()
        raw = self.path.read_bytes()
        provenance = self.root / 'provenance.json'
        provenance.write_text(json.dumps(dict(files=[dict(file=self.path.name, bytes=len(raw), sha256=batch.digest(raw),
            git_blob_sha1=hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest())])))
        audit = audit_batch(self.source, self.output, provenance)
        self.assertFalse(audit['native_netlist_verified'])
        self.assertFalse(audit['physical_footprint_mapping_verified'])
        self.assertEqual(audit['source_pin_records_validated'], 1)
        self.path.write_text(self.path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            audit_batch(self.source, self.output, provenance)

    def test_readback_rejects_changed_native_number_or_connection_point(self):
        source = parse_library(library(basic()))
        result = convert_symbol(source, 'Base')
        for field in ('number', 'endpoint'):
            document = deepcopy(result.document)
            poly = next(p for p in document.components[0].polylines if p.pin)
            if field == 'number':
                poly.pin.value = '2'
            else:
                poly.corners[-1].x += 100
            with self.assertRaisesRegex(ValueError, 'connection point mismatch'):
                verify_source_pins(source, 'Base', write_cds(document), result.report)

    def test_readback_validates_compound_unit_translations(self):
        source = multi()
        result = convert_symbol(source, 'Base')
        self.assertEqual(verify_source_pins(source, 'Base', result.cds, result.report)['pins'], 4)
        report = deepcopy(result.report)
        report['unit_layout']['units'][1]['translation_nm'] = (0, 0)
        with self.assertRaisesRegex(ValueError, 'connection point mismatch'):
            verify_source_pins(source, 'Base', result.cds, report)

    def test_invalid_global_settings_do_not_publish_artifacts(self):
        for options in ({'limit': 0}, {'no_connect_policy': 'bad'}, {'hidden_pin_policy': 'bad'},
                        {'pin_width': 1e308}, {'curve_tolerance': float('nan')}, {'unit_gap': 0}):
            with self.assertRaises(ValueError):
                self.run_batch(**options)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
