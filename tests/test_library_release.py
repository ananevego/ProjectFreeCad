"""Portable release integrity and complete source/failure accounting."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from src.footprint_converter.audit import audit_batch
from src.footprint_converter.batch import run_batch
from src.footprint_converter.model import ApertureSettings
from src.library_release import build_release, verify_release, archive_release, encode_json


class LibraryReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.batch, self.output = (self.base / p for p in ('source', 'batch', 'release'))
        shutil.copytree(Path(__file__).parent / 'fixtures/full-library', self.source)
        slot = self.source / 'Slots.pretty/Slot.kicad_mod'
        slot.parent.mkdir()
        raw = b'(footprint "Slot" (pad "1" thru_hole oval (at 0 0) (size 2 1) (drill oval 1 .5) (layers "*.Cu" "*.Mask")))'
        slot.write_bytes(raw)
        provenance = json.loads((self.source / 'provenance.json').read_text())
        provenance['files'].append(dict(file='Slots.pretty/Slot.kicad_mod', bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), git_blob_sha1=hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()))
        (self.source / 'provenance.json').write_bytes(encode_json(provenance))
        run_batch(self.source, self.batch, stl_root=self.base / 'models', aperture_defaults=ApertureSettings(.05, 0, 0),
                  description_policy='ascii-escape-with-loss')
        self.audit = self.base / 'audit.json'
        self.audit.write_bytes(encode_json(audit_batch(self.source, self.batch, self.source / 'provenance.json')))

    def build(self):
        return build_release(self.source, self.batch, self.audit, self.output)

    def test_successes_and_omissions_are_complete_and_relocation_needs_no_sources(self):
        result = self.build()
        self.assertEqual((result['generated'], result['omitted'], result['source_files']), (3, 1, 4))
        self.assertFalse(result['model_assets_included'])
        self.assertFalse(result['target_gui_validated'])
        self.assertEqual(len(list(self.output.rglob('*.fpl'))), 3)
        self.assertEqual(json.loads((self.output / 'failures.json').read_text())[0]['category'], 'DRILL_SLOT_UNSUPPORTED')
        self.assertNotIn(str(self.base), ''.join(p.read_text() for p in self.output.rglob('*.json')))
        moved = self.base / 'relocated'
        self.output.rename(moved)
        shutil.rmtree(self.source)
        shutil.rmtree(self.batch)
        self.assertEqual(verify_release(moved), result)

    def test_changed_source_fpl_or_audit_cannot_be_published(self):
        manifest = json.loads((self.batch / 'manifest.json').read_bytes())
        entry = next(e for e in manifest['entries'] if e['status'] == 'generated_with_loss')
        for path in (self.source / entry['source'], self.batch / entry['output_file'], self.batch / 'manifest.json'):
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.assertRaises(ValueError):
                self.build()
            self.assertFalse(self.output.exists())
            path.write_bytes(original)

    def test_failed_stale_fpl_is_never_distributed(self):
        manifest = json.loads((self.batch / 'manifest.json').read_bytes())
        failed = next(e for e in manifest['entries'] if e['status'] == 'failed')
        stale = self.batch / failed['output_file']
        stale.parent.mkdir(exist_ok=True)
        stale.write_bytes(b'stale and invalid')
        self.build()
        self.assertTrue(all(b'stale and invalid' != p.read_bytes() for p in self.output.rglob('*.fpl')))

    def test_tampering_extra_files_symlinks_and_native_claims_fail_verification(self):
        self.build()
        fpl = next(self.output.rglob('*.fpl'))
        original = fpl.read_bytes()
        fpl.write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum/size'):
            verify_release(self.output)
        fpl.write_bytes(original)
        extra = self.output / 'unindexed'
        extra.write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'Unindexed'):
            verify_release(self.output)
        extra.unlink()
        fpl.unlink()
        elsewhere = self.base / 'external.fpl'
        elsewhere.write_bytes(original)
        fpl.symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            verify_release(self.output)
        fpl.unlink()
        fpl.write_bytes(original)
        release = json.loads((self.output / 'release.json').read_bytes())
        release['target_gui_validated'] = True
        (self.output / 'release.json').write_bytes(encode_json(release))
        with self.assertRaisesRegex(ValueError, 'validation claim'):
            verify_release(self.output)

    def test_archive_is_deterministic_and_extracts_to_a_verifiable_library(self):
        self.build()
        first, second = self.base / 'first.zip', self.base / 'second.zip'
        self.assertEqual(archive_release(self.output, first), archive_release(self.output, second))
        with zipfile.ZipFile(first) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(self.base / 'unpacked')
        self.assertEqual(verify_release(self.output), verify_release(self.base / 'unpacked/freepcb-footprints-preview'))
        with self.assertRaisesRegex(ValueError, 'must be new'):
            archive_release(self.output, first)

    def test_existing_or_source_output_and_escaping_manifest_paths_are_rejected(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.build()
        with self.assertRaisesRegex(ValueError, 'outside source'):
            build_release(self.source, self.batch, self.audit, self.source / 'release')
        self.output.rmdir()
        self.build()
        release = json.loads((self.output / 'release.json').read_bytes())
        release['files'][0]['file'] = '../../outside'
        (self.output / 'release.json').write_bytes(encode_json(release))
        with self.assertRaisesRegex(ValueError, 'Unsafe corpus path'):
            verify_release(self.output)


if __name__ == '__main__':
    unittest.main()
