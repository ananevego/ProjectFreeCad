"""Archive/provenance checks without downloading the upstream library."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from src import library_corpus as corpus


class LibraryCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.archive = self.base / 'source.tar.gz'
        self.tree = self.base / 'tree.json'
        self.output = self.base / 'verified'
        self.files = {'Demo.pretty/A.kicad_mod': b'(footprint "A")', 'LICENSE.md': b'upstream license\n'}
        self.metadata = dict(sha=corpus.REVISION, truncated=False, tree=[
            dict(path=name, type='blob', mode='100755', size=len(raw),
                 sha=hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest())
            for name, raw in self.files.items()])

    def write_archive(self, members=None):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, data, kind in members or [(corpus.ARCHIVE_ROOT + '/' + name, raw, tarfile.REGTYPE) for name, raw in self.files.items()]:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind == tarfile.SYMTYPE:
                    info.linkname = '/outside'
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(data) if info.size else None)

    def prepare(self):
        self.tree.write_text(json.dumps(self.metadata), encoding='utf-8')
        with ExitStack() as patches:
            patches.enter_context(patch.object(corpus, 'FOOTPRINT_COUNT', 1))
            patches.enter_context(patch.object(corpus, 'TREE_SHA256', corpus.sha256_file(self.tree)))
            return corpus.prepare_corpus(self.archive, self.tree, self.output)

    def test_every_copied_byte_and_license_are_verified_and_provenance_is_portable(self):
        self.write_archive()
        result = self.prepare()
        self.assertEqual(len(result['files']), 1)
        self.assertFalse(result['modified'])
        self.assertEqual(result['category_populations'], {'Demo.pretty': 1})
        for name, raw in self.files.items():
            self.assertEqual((self.output / name).read_bytes(), raw)
        self.assertEqual(result['archive']['sha256'], corpus.sha256_file(self.archive))
        self.assertEqual(result['files'][0]['sha256'], hashlib.sha256(self.files['Demo.pretty/A.kicad_mod']).hexdigest())
        self.assertNotIn(str(self.base), (self.output / 'provenance.json').read_text())
        self.assertEqual((self.output / 'source-tree.json').read_bytes(), self.tree.read_bytes())

    def test_same_size_source_corruption_is_rejected_before_publication(self):
        self.files['Demo.pretty/A.kicad_mod'] = b'(footprint "B")'
        self.write_archive()
        with self.assertRaisesRegex(ValueError, 'Git blob mismatch'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_missing_source_or_license_is_rejected(self):
        for missing in self.files:
            self.write_archive([(corpus.ARCHIVE_ROOT + '/' + name, raw, tarfile.REGTYPE)
                                for name, raw in self.files.items() if name != missing])
            with self.assertRaisesRegex(ValueError, 'missing pinned'):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_duplicate_archive_member_is_rejected(self):
        member = (corpus.ARCHIVE_ROOT + '/LICENSE.md', self.files['LICENSE.md'], tarfile.REGTYPE)
        self.write_archive([member, member])
        with self.assertRaisesRegex(ValueError, 'duplicate member'):
            self.prepare()

    def test_links_special_files_and_escaping_paths_are_rejected(self):
        for name, kind in [(corpus.ARCHIVE_ROOT + '/link', tarfile.SYMTYPE),
                           (corpus.ARCHIVE_ROOT + '/fifo', tarfile.FIFOTYPE),
                           (corpus.ARCHIVE_ROOT + '/../outside', tarfile.REGTYPE),
                           ('/absolute', tarfile.REGTYPE), ('other-root/file', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                self.write_archive([(name, b'', kind)])
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_existing_output_and_symlink_are_not_overwritten(self):
        self.write_archive()
        self.output.mkdir()
        sentinel = self.output / 'user-file'
        sentinel.write_text('retain')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.prepare()
        self.assertEqual(sentinel.read_text(), 'retain')
        link = self.base / 'link'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            corpus.prepare_corpus(self.archive, self.tree, link)

    def test_pinned_metadata_checksum_is_required(self):
        self.write_archive()
        self.tree.write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            corpus.prepare_corpus(self.archive, self.tree, self.output)

    def test_symbol_corpus_uses_its_own_pin_and_preserves_library_bytes(self):
        raw = b'(kicad_symbol_lib (version 20241209))'
        self.files = {'Demo.kicad_sym': raw, 'LICENSE.md': b'license'}
        self.metadata = dict(sha=corpus.SYMBOLS_REVISION, truncated=False, tree=[
            dict(path=name, type='blob', mode='100644', size=len(data),
                 sha=hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()) for name, data in self.files.items()])
        self.tree.write_text(json.dumps(self.metadata))
        self.write_archive([('kicad-symbols-' + corpus.SYMBOLS_REVISION + '/' + name, data, tarfile.REGTYPE)
                            for name, data in self.files.items()])
        with patch.object(corpus, 'SYMBOL_LIBRARY_COUNT', 1), patch.object(corpus, 'SYMBOLS_TREE_SHA256', corpus.sha256_file(self.tree)):
            result = corpus.prepare_corpus(self.archive, self.tree, self.output, kind='symbols')
        self.assertEqual(result['revision'], corpus.SYMBOLS_REVISION)
        self.assertEqual(result['source_tree_metadata']['library_count'], 1)
        self.assertEqual((self.output / 'Demo.kicad_sym').read_bytes(), raw)

    def test_unknown_corpus_kind_is_rejected_without_output(self):
        with self.assertRaisesRegex(ValueError, 'corpus kind'):
            corpus.prepare_corpus(self.archive, self.tree, self.output, kind='unknown')
        self.assertFalse(self.output.exists())

    def test_truncated_wrong_revision_duplicate_or_case_collision_tree_is_rejected(self):
        self.write_archive()
        original = self.metadata.copy()
        for changed in [dict(truncated=True), dict(sha='0' * 40),
                        dict(tree=original['tree'] + [original['tree'][0]]),
                        dict(tree=original['tree'] + [dict(original['tree'][0], path='demo.pretty/a.kicad_mod')])]:
            with self.subTest(changed=changed):
                self.metadata = dict(original, **changed)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
