"""Portable native kit, immutable controls and evidence-scoped observations."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.native_validation.kit import build_kit
from src.native_validation.portable import (compile_scenes, digest, init_results, json_bytes,
    load_json, member, validate_results, verify_kit)
from src.footprint_converter.parser import parse_sexpr, children

PROJECT = Path(__file__).resolve().parents[1]


class NativeValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name)
        cls.partial = cls.base/'partial'
        build_kit(PROJECT, cls.partial, stl_root=cls.base/'missing-models', allow_missing_models=True)
        cls.models = cls.base/'opaque-models'
        # Opaque test bytes verify metadata/copying only. Never send them to a
        # native mesh renderer; the OpenSCAD unit test mocks its subprocess.
        for r in load_json(cls.partial/'source-index.json')['files']:
            if not r.endswith('.kicad_mod') or '/medium/' in r: continue
            for model in children(parse_sexpr((cls.partial/'source'/r).read_text()), 'model'):
                parts = PurePosixPath(model[1]).parts
                indices = [i for i,p in enumerate(parts) if p.endswith('.3dshapes')]
                if len(indices) != 1: continue
                relative = PurePosixPath(*parts[indices[0]:]).with_suffix('.stl')
                target = cls.models/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(('opaque asset '+str(relative)).encode())
        cls.full = cls.base/'full'
        build_kit(PROJECT, cls.full, stl_root=cls.models)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'kit'; shutil.copytree(self.full, self.root)

    def manifest(self): return load_json(self.root/'manifest.json')

    def save_manifest(self, m): (self.root/'manifest.json').write_bytes(json_bytes(m))

    def test_full_and_explicit_partial_kits_separate_presence_from_native_validation(self):
        m=verify_kit(self.root)
        self.assertEqual(m['summary'], dict(bundles=8,components=24,generated_components=24,
            complete_chains=23,models=15,footprints=5,refusals=10,scenes=23,manual_checks=10))
        self.assertTrue(m['ready_for_3d_checks'])
        self.assertFalse(m['native_import_verified']);self.assertFalse(m['model_geometry_validated'])
        partial=verify_kit(self.partial)
        self.assertFalse(partial['ready_for_3d_checks'])
        self.assertEqual((partial['summary']['models'],partial['summary']['complete_chains']),(0,0))

    def test_only_selected_existing_model_bytes_are_copied_under_unique_global_aliases(self):
        m=self.manifest()
        for model in m['models']:
            raw=(self.models/model['source_relative']).read_bytes()
            self.assertEqual((self.root/model['path']).read_bytes(),raw)
            self.assertEqual(model['sha256'],digest(raw))
        self.assertEqual(len({m['import_basename'].casefold() for m in m['models']}),15)

    def test_source_snapshots_keep_original_bytes_and_relative_config_layout(self):
        for relative in load_json(self.root/'source-index.json')['files']:
            self.assertEqual((self.root/'source'/relative).read_bytes(),(PROJECT/relative).read_bytes())
        for entry in self.manifest()['bundles']:
            sub=load_json(self.root/entry['path']/'manifest.json')
            self.assertEqual(sub['summary']['generated_components'],entry['summary']['generated_components'])

    def test_catalog_exposes_npht_carrier_contact_and_original_pin_mapping(self):
        entries={e['id']:e for e in load_json(self.root/'expected-catalog.json')['entries']}
        npth=entries['npth']['pads'][0]
        self.assertEqual(npth['hole'],3200000)
        self.assertEqual(npth['records']['top_pad'][0],0)
        technical,contact=entries['technical-contact']['pads']
        self.assertEqual((technical['name'],technical['hole']),('__TECH_1',0))
        self.assertEqual(technical['records']['top_paste'][0],3)
        self.assertEqual(technical['records']['top_pad'][0],0)
        self.assertEqual(contact['records']['bottom_pad'][0],3)
        self.assertEqual(contact['records']['bottom_paste'][0],0)
        self.assertEqual(entries['control.Header6']['source_pin_numbers'],['1','2','3','4','5','6'])

    def test_negative_sources_keep_refusals_and_have_no_fpl(self):
        refusals=self.manifest()['refusals']
        from collections import Counter
        self.assertEqual(Counter(r['code'] for r in refusals),dict(DRILL_SLOT_UNSUPPORTED=6,PAD_OFFSET_UNSUPPORTED=1,CUSTOM_PAD_NONRECTANGULAR=3))
        self.assertFalse(list((self.root/'refusals').glob('*.fpl')))

    def test_standalone_verifier_after_relocation_does_not_import_repository(self):
        moved=Path(self.temp.name)/'moved';self.root.rename(moved)
        result=subprocess.run([sys.executable,'-I','-B',str(moved/'verify_kit.py')],cwd=self.temp.name,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('file integrity verified',result.stdout)

    def test_checksum_unindexed_file_and_symlink_tampering_reject(self):
        p=self.root/'README.md';p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):verify_kit(self.root)
        shutil.copyfile(self.full/'README.md',p)
        extra=self.root/'extra.txt';extra.write_text('extra')
        with self.assertRaisesRegex(ValueError,'Unindexed'):verify_kit(self.root)
        extra.unlink();(self.root/'results').symlink_to(Path(self.temp.name),target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlink'):verify_kit(self.root)

    def test_unsafe_windows_paths_case_collisions_and_native_scope_claims_reject(self):
        baseline=self.manifest()
        for relative in ('../outside','C:/x','a\\b','source/CON.txt','source/file.'):
            m=deepcopy(baseline);m['files'][0]['path']=relative;self.save_manifest(m)
            with self.assertRaises(ValueError):verify_kit(self.root)
        m=deepcopy(baseline);m['files'].append(dict(m['files'][0],path=m['files'][0]['path'].upper()));self.save_manifest(m)
        with self.assertRaises(ValueError):verify_kit(self.root)
        m=deepcopy(baseline);m['gui_validated']=True;self.save_manifest(m)
        with self.assertRaises(ValueError):verify_kit(self.root)

    def test_summary_and_scene_identity_cannot_forge_a_different_target(self):
        m=self.manifest();m['summary']['complete_chains']=99;self.save_manifest(m)
        with self.assertRaisesRegex(ValueError,'summary'):verify_kit(self.root)
        m=load_json(self.full/'manifest.json');m['scenes'][0]['id']='../escape';self.save_manifest(m)
        with self.assertRaisesRegex(ValueError,'scene'):verify_kit(self.root)

    def init_run(self):
        init_results(self.root,'results/run.json')
        return load_json(self.root/'results/run.json')

    def test_initial_observations_are_pending_and_do_not_modify_immutable_assets(self):
        before=digest((self.root/'manifest.json').read_bytes())
        self.init_run();counts=validate_results(self.root,'results/run.json')
        self.assertEqual(counts,dict(passed=0,failed=0,blocked=0,not_run=10))
        self.assertEqual(digest((self.root/'manifest.json').read_bytes()),before)
        with self.assertRaises(FileExistsError):init_results(self.root,'results/run.json')

    def test_pass_needs_operator_versions_notes_and_real_hashed_evidence(self):
        r=self.init_run();r['checks'][0]['status']='passed';p=self.root/'results/run.json'
        p.write_bytes(json_bytes(r))
        with self.assertRaisesRegex(ValueError,'Passed'):validate_results(self.root,'results/run.json')
        evidence=self.root/'results/observed.txt';evidence.write_text('operator observation, not a native renderer test')
        r.update(operator='Tester',versions=dict(freepcb='2.428',schemator=None,openscad=None))
        r['checks'][0].update(notes='manual observation',evidence=[dict(path='results/observed.txt',sha256=digest(evidence.read_bytes()))])
        p.write_bytes(json_bytes(r));self.assertEqual(validate_results(self.root,'results/run.json')['passed'],1)
        self.assertFalse(verify_kit(self.root)['gui_validated'])
        evidence.write_text('changed')
        with self.assertRaisesRegex(ValueError,'evidence checksum'):validate_results(self.root,'results/run.json')

    def test_results_require_exact_kit_identity_matching_ids_and_block_reason(self):
        original=self.init_run();p=self.root/'results/run.json'
        for mode in ('kit','duplicate','block'):
            r=deepcopy(original)
            if mode=='kit':r['kit_manifest_sha256']='0'*64
            elif mode=='duplicate':r['checks'][1]['id']=r['checks'][0]['id']
            else:r['checks'][0]['status']='blocked'
            p.write_bytes(json_bytes(r))
            with self.assertRaises(ValueError):validate_results(self.root,'results/run.json')

    def test_multi_application_check_requires_both_target_versions(self):
        r=self.init_run();r['operator']='Tester';r['versions']['schemator']='1.429'
        case=next(c for c in r['checks'] if c['id']=='PIN_MAPPING_NETLIST')
        evidence=self.root/'results/evidence.txt';evidence.write_text('placeholder operator evidence')
        case.update(status='passed',notes='recorded',evidence=[dict(path='results/evidence.txt',sha256=digest(evidence.read_bytes()))])
        p=self.root/'results/run.json';p.write_bytes(json_bytes(r))
        with self.assertRaisesRegex(ValueError,'target version'):validate_results(self.root,'results/run.json')
        r['versions']['freepcb']='2.428';p.write_bytes(json_bytes(r))
        self.assertEqual(validate_results(self.root,'results/run.json')['passed'],1)

    def test_results_and_evidence_cannot_escape_mutable_namespace(self):
        for path in ('README.md','results/../README.md','results/C:/x'):
            with self.assertRaises(ValueError):init_results(self.root,path)
        r=self.init_run();r['checks'][0]['evidence']=[dict(path='README.md',sha256=digest((self.root/'README.md').read_bytes()))]
        (self.root/'results/run.json').write_bytes(json_bytes(r))
        with self.assertRaises(ValueError):validate_results(self.root,'results/run.json')

    def test_duplicate_json_keys_and_nonfinite_observation_values_reject(self):
        p=self.root/'results';p.mkdir();f=p/'bad.json'
        for text in ('{"a":1,"a":2}', '{"value":NaN}'):
            f.write_text(text)
            with self.assertRaises(ValueError):load_json(f)

    def test_compile_subprocess_is_bounded_and_never_promotes_native_flags(self):
        exe=Path(self.temp.name)/'openscad';exe.write_text('not executable; mocked')
        def run(args,**kwargs):
            self.assertNotIn('shell',kwargs);self.assertLessEqual(kwargs['timeout'],30)
            if '--version' in args:return subprocess.CompletedProcess(args,0,'','OpenSCAD 2021.01')
            Path(args[args.index('-o')+1]).write_text('group();')
            return subprocess.CompletedProcess(args,0,'','')
        with patch('src.native_validation.portable.subprocess.run',side_effect=run):
            report=compile_scenes(self.root,exe,'mock-csg',['control.R0805'])
        self.assertEqual(report['scenes'][0]['status'],'passed')
        self.assertFalse(report['model_geometry_validated']);self.assertFalse(verify_kit(self.root)['gui_validated'])
        self.assertFalse((self.root/'results/run.json').exists())

    def test_openscad_warnings_fail_compile_and_existing_runs_are_preserved(self):
        exe=Path(self.temp.name)/'openscad';exe.write_text('mock')
        def run(args,**kwargs):
            if '--version' in args:return subprocess.CompletedProcess(args,0,'OpenSCAD version 2021.01','')
            Path(args[args.index('-o')+1]).write_text('group();')
            return subprocess.CompletedProcess(args,0,'','WARNING: missing file')
        with patch('src.native_validation.portable.subprocess.run',side_effect=run):
            report=compile_scenes(self.root,exe,'warn',['control.R0805'])
            self.assertEqual(report['scenes'][0]['status'],'failed')
            with self.assertRaises(FileExistsError):compile_scenes(self.root,exe,'warn',['control.R0805'])

    def test_builder_does_not_replace_existing_output_or_publish_missing_required_models(self):
        with self.assertRaises(ValueError):build_kit(PROJECT,self.root,stl_root=self.models)
        destination=Path(self.temp.name)/'missing'
        with self.assertRaises(ValueError):build_kit(PROJECT,destination,stl_root=Path(self.temp.name)/'absent')
        self.assertFalse(destination.exists())
        for protected in (PROJECT/'src/native-test',PROJECT/'tests/fixtures/native-test',self.models/'bad'):
            with self.assertRaises(ValueError):build_kit(PROJECT,protected,stl_root=self.models)


if __name__=='__main__':unittest.main()
