"""Batch behavior, recovery, provenance and protected filesystem boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.footprint_converter import ConversionError
from src.footprint_converter import batch
from test_footprint_converter import decode_fpl, source_pad

PROJECT = Path(__file__).resolve().parents[1]


def footprint(extra='', name='Demo'):
    return f'(footprint "{name}" {source_pad()} {extra})'


class BatchConverterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.input = self.base/'input'
        self.output = self.base/'output'
        self.models = self.base/'models'
        self.input.mkdir()

    def source(self, relative, content=None):
        path = self.input/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content is not None else footprint(), encoding='utf-8')
        return path

    def run_batch(self, **kwargs):
        return batch.run_batch(self.input, self.output, stl_root=self.models, **kwargs)

    def artifact(self, result, index=0, key='output_file'):
        return self.output/result['entries'][index][key]

    def test_mixed_party_keeps_going_and_reports_known_loss_separately(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod', '(footprint "Broken"')
        self.source('c.kicad_mod')
        result = self.run_batch()
        self.assertEqual(result['status'], 'completed_with_errors')
        self.assertEqual([e['status'] for e in result['entries']],
                         ['generated_with_loss', 'failed', 'generated_with_loss'])
        self.assertEqual(result['summary']['generated'], 2)
        self.assertEqual(result['summary']['generated_with_loss'], 2)
        self.assertEqual(result['summary']['failed'], 1)
        self.assertEqual(result['summary']['generation_percent'], 66.67)
        self.assertEqual(result['summary']['diagnostic_item_counts']['MODEL_MISSING'], 2)
        self.assertFalse(result['target_gui_validated'])
        self.assertFalse(self.artifact(result, 1).exists())
        self.assertEqual(json.loads(self.artifact(result, 1, 'report_file').read_text())['status'], 'failed')
        self.assertEqual(decode_fpl(self.artifact(result, 2).read_text())[1][0]['name'], '1')

    def test_malformed_nested_numeric_input_does_not_abort_the_party(self):
        self.source('a.kicad_mod', footprint().replace('(size 1.025 1.4)', '(size (bad) 1.4)'))
        self.source('b.kicad_mod')
        result = self.run_batch()
        self.assertEqual(result['summary']['failed'], 1)
        self.assertEqual(result['summary']['generated'], 1)
        self.assertEqual(result['entries'][0]['error_type'], 'TypeError')
        self.assertTrue(result['entries'][0]['unexpected_error'])

    def test_unexpected_pipeline_exception_is_recorded_and_other_files_continue(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod')
        original = batch.convert_detailed
        def fail_first(root, name, **options):
            if name == batch.item_name('a.kicad_mod'):
                raise RuntimeError('simulated pipeline error')
            return original(root, name, **options)
        with patch.object(batch, 'convert_detailed', side_effect=fail_first):
            result = self.run_batch()
        self.assertEqual(result['summary']['generated'], 1)
        report = json.loads(self.artifact(result, key='report_file').read_text())
        self.assertEqual(report['error_type'], 'RuntimeError')
        self.assertTrue(report['unexpected_error'])

    def test_names_are_stable_unique_and_windows_safe_for_duplicate_source_names(self):
        self.source('a.pretty/CON.kicad_mod')
        self.source('b.pretty/CON.kicad_mod')
        self.source('c.pretty/a:b.kicad_mod')
        self.source('c.pretty/a?b.kicad_mod')
        first = self.run_batch()
        names = {e['source']: e['target_name'] for e in first['entries']}
        self.assertEqual(len(set(names.values())), 4)
        for name in names.values():
            self.assertRegex(name, r'^fp_[A-Za-z0-9_.-]+$')
            self.assertLessEqual(len(name), 99)
        self.source('0.pretty/earlier.kicad_mod')
        second = self.run_batch(resume=True)
        self.assertEqual({e['source']: e['target_name'] for e in second['entries'] if e['source'] in names}, names)
        self.assertEqual(second['summary']['reused'], 4)

    def test_resume_skips_conversion_and_preserves_fpl_and_report_mtimes(self):
        self.source('a.kicad_mod')
        result = self.run_batch()
        output, report = self.artifact(result), self.artifact(result, key='report_file')
        mtimes = output.stat().st_mtime_ns, report.stat().st_mtime_ns
        with patch.object(batch, 'convert_detailed', side_effect=AssertionError('Cache must avoid conversion')):
            resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['reused'], 1)
        self.assertEqual((output.stat().st_mtime_ns, report.stat().st_mtime_ns), mtimes)
        self.assertTrue(resumed['entries'][0]['output_current'])

    def test_input_change_invalidates_only_affected_item_and_failures_are_retried(self):
        a = self.source('a.kicad_mod')
        b = self.source('b.kicad_mod', 'broken')
        self.run_batch()
        b.write_text(footprint())
        resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['generated'], 2)
        self.assertEqual(resumed['summary']['reused'], 1)
        a.write_text(footprint().replace('(at -0.9125 0)', '(at -1 0)'))
        resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['reused'], 1)
        self.assertEqual(decode_fpl(self.artifact(resumed).read_text())[1][0]['x'], -1000000)

    def test_configuration_and_engine_changes_invalidate_cache(self):
        self.source('a.kicad_mod')
        self.run_batch()
        result = self.run_batch(resume=True, curve_tolerance=0.02)
        self.assertEqual(result['summary']['reused'], 0)
        result = self.run_batch(resume=True, encoding='utf-8', curve_tolerance=0.02)
        self.assertEqual(result['summary']['reused'], 0)
        with patch.object(batch, 'engine_fingerprint', return_value='different-engine'):
            result = self.run_batch(resume=True, encoding='utf-8', curve_tolerance=0.02)
        self.assertEqual(result['summary']['reused'], 0)

    def test_binding_margin_strict_and_transform_settings_are_in_fingerprint(self):
        self.source('a.kicad_mod')
        options = [dict(text_variables={'REFERENCE': 'R1'}),
                   dict(aperture_defaults=batch.ApertureSettings(0.05, 0, 0)),
                   dict(model_transform=batch.ModelTransform(translation=(1, 0, 0))),
                   dict(fill_tolerance=0.02)]
        for option in options:
            with self.subTest(option=option):
                self.run_batch()
                self.assertEqual(self.run_batch(resume=True, **option)['summary']['reused'], 0)
        rejected = self.run_batch(resume=True, strict=True)
        self.assertEqual(rejected['summary']['rejected_loss'], 1)
        self.assertEqual(rejected['summary']['reused'], 0)

    def test_corrupt_missing_output_report_and_state_are_regenerated(self):
        self.source('a.kicad_mod')
        result = self.run_batch()
        for key in ('output_file', 'report_file', 'state_file'):
            with self.subTest(key=key):
                path = self.artifact(result, key=key)
                original = path.read_bytes()
                path.write_bytes(b'corrupted')
                self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 0)
                self.assertEqual(path.read_bytes(), original)
                path.unlink()
                self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 0)
                self.assertTrue(path.exists())

    def test_malformed_cache_fields_do_not_crash_or_reuse(self):
        self.source('a.kicad_mod')
        result = self.run_batch()
        state = self.artifact(result, key='state_file')
        for key, value in [('status', []), ('diagnostics', {}), ('diagnostics', [{}]), ('output_current', False)]:
            data = json.loads(state.read_text())
            data[key] = value
            state.write_text(json.dumps(data))
            with self.subTest(key=key, value=value):
                self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 0)

    def test_model_presence_metadata_and_removal_invalidate_without_reading_mesh(self):
        self.source('a.kicad_mod', footprint('(model "${KICAD}/Pkg.3dshapes/Thing.step")'))
        self.run_batch()
        self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 1)
        model = self.models/'Pkg.3dshapes/Thing.stl'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'metadata only')
        real_read = Path.read_bytes
        def read_without_mesh(path):
            if path.suffix == '.stl':
                raise AssertionError('Batch must not read mesh contents')
            return real_read(path)
        with patch.object(Path, 'read_bytes', read_without_mesh):
            appeared = self.run_batch(resume=True)
            self.assertEqual(appeared['summary']['reused'], 0)
            self.assertIn('openscad_code:', self.artifact(appeared).read_text())
            stat = model.stat()
            os.utime(model, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
            changed = self.run_batch(resume=True)
            self.assertEqual(changed['summary']['reused'], 0)
            model.unlink()
            removed = self.run_batch(resume=True)
            self.assertEqual(removed['summary']['reused'], 0)
            self.assertNotIn('openscad_code:', self.artifact(removed).read_text())

    def test_failed_reconversion_keeps_previous_fpl_but_marks_it_not_current(self):
        source = self.source('a.kicad_mod')
        first = self.run_batch()
        output = self.artifact(first)
        previous = output.read_bytes()
        source.write_text('broken')
        second = self.run_batch(resume=True)
        self.assertEqual(second['entries'][0]['status'], 'failed')
        self.assertFalse(second['entries'][0]['output_current'])
        self.assertNotIn('output_sha256', second['entries'][0])
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(second['summary']['generated'], 0)

    def test_strict_is_per_item_and_preserves_previous_outputs(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod')
        first = self.run_batch()
        output = self.artifact(first)
        data = output.read_bytes()
        strict = self.run_batch(strict=True)
        self.assertEqual(strict['summary']['rejected_loss'], 2)
        self.assertEqual(strict['summary']['generated'], 0)
        self.assertEqual(strict['status'], 'completed_with_errors')
        self.assertEqual(output.read_bytes(), data)
        self.assertEqual(json.loads(self.artifact(strict, key='report_file').read_text())['status'], 'rejected_loss')

    def test_interruption_recovers_committed_state_before_manifest_checkpoint(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod')
        original = batch.convert_detailed
        calls = []
        def interrupt_on_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return original(*args, **kwargs)
        with patch.object(batch, 'convert_detailed', side_effect=interrupt_on_second), self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        partial = json.loads((self.output/'manifest.json').read_text())
        self.assertEqual(partial['status'], 'running')
        self.assertEqual(partial['summary']['pending'], 2)
        resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['reused'], 1)
        self.assertEqual(resumed['summary']['generated'], 2)

    def test_interruption_after_output_before_state_can_be_repaired(self):
        self.source('a.kicad_mod')
        original = batch.atomic_write
        def interrupt_report(path, data):
            if path.name.endswith('.report.json'):
                raise KeyboardInterrupt
            return original(path, data)
        with patch.object(batch, 'atomic_write', side_effect=interrupt_report), self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['reused'], 0)
        self.assertEqual(resumed['summary']['generated'], 1)

    def test_report_write_error_marks_item_failed_and_keeps_other_items_running(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod')
        original = batch.atomic_write
        def fail_first_report(path, data):
            if path.name == batch.item_name('a.kicad_mod') + '.report.json':
                raise OSError('simulated report failure')
            return original(path, data)
        with patch.object(batch, 'atomic_write', side_effect=fail_first_report):
            result = self.run_batch()
        self.assertEqual(result['summary']['failed'], 1)
        self.assertEqual(result['summary']['generated'], 1)
        self.assertFalse(result['entries'][0]['output_current'])
        resumed = self.run_batch(resume=True)
        self.assertEqual(resumed['summary']['generated'], 2)
        self.assertEqual(resumed['summary']['reused'], 1)

    def test_limit_change_and_removed_sources_preserve_artifact_ownership(self):
        self.source('a.kicad_mod')
        b = self.source('b.kicad_mod')
        full = self.run_batch()
        b_output = self.artifact(full, 1)
        limited = self.run_batch(resume=True, limit=1)
        self.assertEqual(limited['discovered'], 2)
        self.assertEqual(limited['selected'], 1)
        self.assertEqual(limited['not_selected_previous_sources'], ['b.kicad_mod'])
        self.assertTrue(b_output.exists())
        self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 2)
        b.unlink()
        removed = self.run_batch(resume=True)
        self.assertEqual(removed['summary']['total'], 1)
        self.assertEqual(removed['not_selected_previous_sources'], ['b.kicad_mod'])
        self.assertTrue(b_output.exists())
        self.source('b.kicad_mod')
        self.assertEqual(self.run_batch(resume=True)['summary']['reused'], 2)

    def test_invalid_global_configuration_leaves_previous_manifest_and_output_untouched(self):
        self.source('a.kicad_mod')
        first = self.run_batch()
        manifest = (self.output/'manifest.json').read_bytes()
        output = self.artifact(first).read_bytes()
        for options in ({'encoding': 'missing-codec'}, {'curve_tolerance': float('nan')},
                        {'fill_tolerance': 0}, {'limit': 0}, {'text_variables': {'REF': 'bad"quote'}},
                        {'aperture_defaults': batch.ApertureSettings(float('inf'), 0, 0)}):
            with self.subTest(options=options), self.assertRaises((ConversionError, LookupError)):
                self.run_batch(**options)
            self.assertEqual((self.output/'manifest.json').read_bytes(), manifest)
            self.assertEqual(self.artifact(first).read_bytes(), output)

    def test_nested_output_and_model_storage_are_protected(self):
        self.source('a.kicad_mod')
        for destination in (self.input, self.input/'results', self.base, self.models/'results'):
            with self.subTest(destination=destination), self.assertRaises(ConversionError):
                batch.run_batch(self.input, destination, stl_root=self.models)
        self.assertFalse((self.input/'results').exists())
        self.assertFalse((self.models/'results').exists())

    def test_output_symlink_escape_and_unowned_artifact_are_refused(self):
        self.source('a.kicad_mod')
        self.output.mkdir()
        (self.output/'footprints').symlink_to(self.input, target_is_directory=True)
        with self.assertRaises(ConversionError):
            self.run_batch()
        (self.output/'footprints').unlink()
        target = self.output/'footprints'/f'{batch.item_name("a.kicad_mod")}.fpl'
        target.parent.mkdir()
        target.write_bytes(b'external artifact')
        with self.assertRaisesRegex(ConversionError, 'unowned'):
            self.run_batch()
        self.assertEqual(target.read_bytes(), b'external artifact')

    def test_input_symlink_fails_only_that_item_and_directory_symlinks_are_not_followed(self):
        outside = self.base/'outside.kicad_mod'
        outside.write_text(footprint())
        self.source('a.kicad_mod')
        (self.input/'b.kicad_mod').symlink_to(outside)
        external_directory = self.base/'external'
        external_directory.mkdir()
        (external_directory/'c.kicad_mod').write_text(footprint())
        (self.input/'linked').symlink_to(external_directory, target_is_directory=True)
        result = self.run_batch()
        self.assertEqual(result['summary']['total'], 2)
        self.assertEqual(result['summary']['generated'], 1)
        self.assertEqual(result['summary']['failed'], 1)

    def test_symlinked_artifact_directory_inside_output_is_also_refused(self):
        self.source('a.kicad_mod')
        self.run_batch()
        original = (self.output/'manifest.json').read_bytes()
        (self.output/'reports').rename(self.output/'moved-reports')
        (self.output/'reports').symlink_to(self.output/'moved-reports', target_is_directory=True)
        with self.assertRaisesRegex(ConversionError, 'symlink'):
            self.run_batch(resume=True)
        self.assertEqual((self.output/'manifest.json').read_bytes(), original)

    def test_corrupt_foreign_manifest_and_empty_input_are_global_errors(self):
        self.source('a.kicad_mod')
        self.output.mkdir()
        manifest = self.output/'manifest.json'
        manifest.write_text('broken')
        with self.assertRaises(ConversionError):
            self.run_batch()
        self.assertEqual(manifest.read_text(), 'broken')
        manifest.unlink()
        self.run_batch()
        data = json.loads(manifest.read_text())
        data['input_root'] = 'some-other-root'
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ConversionError):
            self.run_batch(resume=True)
        (self.input/'a.kicad_mod').unlink()
        with self.assertRaisesRegex(ConversionError, 'No .kicad_mod'):
            self.run_batch()

    def test_same_output_directory_cannot_be_used_concurrently(self):
        self.source('a.kicad_mod')
        self.output.mkdir()
        with batch.batch_lock(self.output/'.batch.lock'):
            with self.assertRaises((ConversionError, OSError)):
                self.run_batch()
        self.assertEqual(self.run_batch()['summary']['generated'], 1)

    def test_repeated_full_runs_have_deterministic_manifest_and_reports(self):
        self.source('a.kicad_mod')
        first = self.run_batch()
        manifest = (self.output/'manifest.json').read_bytes()
        report = self.artifact(first, key='report_file').read_bytes()
        second = self.run_batch()
        self.assertEqual(first, second)
        self.assertEqual((self.output/'manifest.json').read_bytes(), manifest)
        self.assertEqual(self.artifact(first, key='report_file').read_bytes(), report)

    def test_cli_summary_exit_codes_resume_and_invalid_bindings(self):
        self.source('a.kicad_mod')
        self.source('b.kicad_mod', 'broken')
        command = [sys.executable, '-B', '-m', 'src.footprint_converter.batch', str(self.input), str(self.output),
                   '--stl-root', str(self.models)]
        run = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn('1 failed', run.stdout)
        resumed = subprocess.run(command+['--resume'], cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(resumed.returncode, 2, resumed.stderr)
        self.assertIn('1 reused', resumed.stdout)
        failed = subprocess.run(command+['--text-variable', 'REF=a', '--text-variable', 'REF=b'],
                                cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertNotIn('Traceback', failed.stderr)
        (self.input/'b.kicad_mod').write_text(footprint())
        completed = subprocess.run(command+['--resume'], cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
