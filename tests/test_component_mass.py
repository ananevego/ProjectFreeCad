"""Real audited inputs, assigned native records, shared assets and atomic delivery."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_batch_component_inventory as fixtures
from test_symbol_batch import basic
from src.component_converter import mass
from src.component_converter.bundle import verify_bundle, json_bytes, digest
from src.symbol_converter.schemator_format import parse_cds


class ComponentMassTests(unittest.TestCase):
    def setUp(self):
        fixtures.BatchComponentInventoryTests.setUp(self)
        self.output = self.root / 'linked'
        self.models = self.root / 'models'

    def build(self, output=None):
        return mass.export_mass(self.symbols, self.sb, self.sa, self.footprints, self.fb, self.fa,
                                output or self.output, stl_root=self.models)

    def test_only_audited_exact_candidates_are_assigned_and_exclusions_retained(self):
        summary = self.build()
        self.assertEqual((summary['source_symbols'], summary['candidates'], summary['generated']), (8, 1, 1))
        self.assertEqual(summary['partial_or_no_model_dependencies'], 1)
        self.assertFalse(summary['native_netlist_verified'])
        entry = verify_bundle(self.output)['components'][0]
        doc = parse_cds((self.output / entry['symbol']).read_text(encoding='cp1251'))
        self.assertEqual(doc.components[0].footprint.value, entry['target_footprint'])
        self.assertNotEqual(entry['target_footprint'], 'PART')
        self.assertEqual(mass.verify_mass(self.output), summary)
        self.assertNotIn(str(self.root), (self.output / 'manifest.json').read_text())

    def test_two_symbols_share_one_byte_preserved_model_and_flat_alias(self):
        path = self.symbols / 'Demo.kicad_sym'
        raw = path.read_text().rstrip()
        path.write_text(raw[:-1] + basic('Second').replace('(property "Footprint" ""', '(property "Footprint" "Demo:One"') + ')')
        fixtures.symbol_batch(self.symbols, self.sb)
        self.sa.write_bytes(json_bytes(fixtures.symbol_audit(self.symbols, self.sb)))
        fp = self.footprints / 'Demo.pretty/One.kicad_mod'
        fp.write_text(fp.read_text().rstrip()[:-1] + '(model "Demo.3dshapes/One.step"))')
        model = self.models / 'Demo.3dshapes/One.stl'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'opaque selected bytes; not mesh geometry')
        fixtures.footprint_batch(self.footprints, self.fb, stl_root=self.models,
                                 aperture_defaults=fixtures.ApertureSettings(.05, 0, 0))
        self.fa.write_bytes(json_bytes(fixtures.footprint_audit(self.footprints, self.fb)))
        result = self.build()
        self.assertEqual((result['generated'], result['complete_model_dependencies'], result['unique_existing_models']), (2, 2, 1))
        manifest = verify_bundle(self.output)
        asset = manifest['models'][0]
        for key in ('canonical_path', 'runtime_path'):
            self.assertEqual((self.output / asset[key]).read_bytes(), model.read_bytes())

    def test_source_changed_after_audit_prevents_publication(self):
        path = self.symbols / 'Demo.kicad_sym'
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'Source changed after audit'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_interruption_removes_private_staging_and_leaves_no_public_output(self):
        with patch.object(mass, '_convert_item', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.build()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.linked-preview-*')))

    def test_existing_output_and_protected_sources_are_never_replaced(self):
        self.output.mkdir()
        marker = self.output / 'mine'
        marker.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(marker.read_bytes(), b'keep')
        with self.assertRaises(ValueError):
            self.build(self.symbols / 'nested')
        with self.assertRaises(ValueError):
            self.build(self.models / 'nested')

    def test_archive_crc_and_relocation_verify_without_any_original_sources(self):
        summary = self.build()
        archive = self.root / 'linked.zip'
        shutil.rmtree(self.symbols)
        shutil.rmtree(self.footprints)
        shutil.rmtree(self.sb)
        shutil.rmtree(self.fb)
        result = mass.archive_mass(self.output, archive)
        self.assertTrue(result['crc_verified'] and result['relocated_verified'])
        self.assertEqual(len(result['sha256']), 64)
        self.assertEqual(mass.verify_mass(self.output), summary)
        with self.assertRaises(ValueError):
            mass.archive_mass(self.output, archive)

    def test_rehashed_false_completion_claim_is_rejected(self):
        self.build()
        summary_path = self.output / 'linked-summary.json'
        summary = json.loads(summary_path.read_bytes())
        summary['complete_model_dependencies'] = 1
        summary_path.write_bytes(json_bytes(summary))
        manifest_path = self.output / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        for record in manifest['files']:
            if record['path'] == 'linked-summary.json':
                record.update(bytes=summary_path.stat().st_size, sha256=digest(summary_path.read_bytes()))
        manifest_path.write_bytes(json_bytes(manifest))
        with self.assertRaisesRegex(ValueError, 'summary mismatch'):
            mass.verify_mass(self.output)


if __name__ == '__main__':
    unittest.main()
