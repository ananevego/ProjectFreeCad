"""Audited symbol preview keeps losses and rejects stale/unverified claims."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from src.symbol_converter.batch import run_batch, json_bytes
from src.symbol_converter.audit import audit_batch
from src.symbol_release import build_release, verify_release, archive_release
from test_symbol_batch import basic
from test_symbol_converter import library


class SymbolReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.batch, self.output = (self.root / p for p in ('source', 'batch', 'preview'))
        self.source.mkdir()
        raw = library(basic(), basic('Hidden', '(hide yes)')).encode()
        (self.source / 'Demo.kicad_sym').write_bytes(raw)
        license_raw = b'upstream license and exception\n'
        (self.source / 'LICENSE.md').write_bytes(license_raw)
        provenance = dict(revision='test', license=dict(file='LICENSE.md', sha256=hashlib.sha256(license_raw).hexdigest()),
            files=[dict(file='Demo.kicad_sym', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob_sha1=hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest())])
        (self.source / 'provenance.json').write_bytes(json_bytes(provenance))
        self.manifest = run_batch(self.source, self.batch)
        self.audit = self.root / 'audit.json'
        self.audit.write_bytes(json_bytes(audit_batch(self.source, self.batch, self.source / 'provenance.json')))

    def build(self):
        return build_release(self.source, self.batch, self.audit, self.output)

    def test_portable_preview_keeps_source_and_loss_reports_and_all_refusals(self):
        release = self.build()
        self.assertEqual((release['generated'], release['omitted'], release['total']), (1, 1, 2))
        self.assertFalse(release['physical_footprint_mapping_verified'])
        self.assertEqual(release['footprint_binding'], 'PART placeholder')
        catalog = json.loads((self.output / 'catalog.json').read_bytes())
        report = json.loads((self.output / catalog[0]['report_file']).read_bytes())
        self.assertEqual(report['source_symbol']['name'], 'Base')
        self.assertTrue(report['diagnostics'])
        self.assertEqual(json.loads((self.output / 'failures.json').read_bytes())[0]['symbol'], 'Hidden')
        self.assertNotIn(str(self.root), ''.join(p.read_text() for p in self.output.rglob('*.json')))
        moved = self.root / 'relocated'
        self.output.rename(moved)
        shutil.rmtree(self.source)
        shutil.rmtree(self.batch)
        self.assertEqual(verify_release(moved), release)

    def test_changed_source_cds_or_report_cannot_be_published(self):
        entry = next(e for e in self.manifest['entries'] if e['output_current'])
        for path in (self.source / entry['source'], self.batch / entry['output_file'], self.batch / entry['report_file']):
            raw = path.read_bytes()
            path.write_bytes(raw + b'\n')
            with self.assertRaises(ValueError):
                self.build()
            self.assertFalse(self.output.exists())
            path.write_bytes(raw)

    def test_archive_is_deterministic_and_extracted_preview_verifies(self):
        result = self.build()
        first, second = self.root / 'first.zip', self.root / 'second.zip'
        self.assertEqual(archive_release(self.output, first), archive_release(self.output, second))
        with zipfile.ZipFile(first) as zipped:
            self.assertIsNone(zipped.testzip())
            zipped.extractall(self.root / 'unpacked')
        self.assertEqual(verify_release(self.root / 'unpacked/schemator-symbols-preview'), result)
        with self.assertRaisesRegex(ValueError, 'must be new'):
            archive_release(self.output, first)

    def test_corruption_extra_files_and_fake_native_claims_fail(self):
        self.build()
        path = next(self.output.rglob('*.cds'))
        raw = path.read_bytes()
        path.write_bytes(raw + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_release(self.output)
        path.write_bytes(raw)
        extra = self.output / 'extra'
        extra.write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'Unindexed'):
            verify_release(self.output)
        extra.unlink()
        release = json.loads((self.output / 'release.json').read_bytes())
        release['physical_footprint_mapping_verified'] = True
        (self.output / 'release.json').write_bytes(json_bytes(release))
        with self.assertRaisesRegex(ValueError, 'unsupported native/binding claim'):
            verify_release(self.output)

    def test_existing_output_incomplete_inventory_and_native_audit_claim_are_rejected(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.build()
        self.output.rmdir()
        original = json.loads(self.audit.read_bytes())
        for change in ('inventory', 'native', 'unexpected'):
            audit = json.loads(json.dumps(original))
            if change == 'inventory':
                audit['summary']['source_inventory_complete'] = False
            elif change == 'native':
                audit['native_netlist_verified'] = True
            else:
                audit['summary']['unexpected_errors'] = 1
            self.audit.write_bytes(json_bytes(audit))
            with self.assertRaisesRegex(ValueError, 'requires matching complete audit'):
                self.build()
            self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
