"""Component links, independent record checks and movable opaque STL bundles."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.component_converter import export_bundle, verify_bundle
from src.component_converter import bundle
from src.component_converter.links import footprint_identifier, pin_mapping
from src.component_converter.records import read_fpl_links
from src.footprint_converter.parser import parse_footprint, parse_sexpr
from src.footprint_converter.model import ModelMatch, ModelReference
from pathlib import PurePosixPath
from src.symbol_converter import parse_library
from src.symbol_converter.schemator_format import parse_cds

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT/'tests/fixtures'
MODEL_PATHS = ['Resistor_SMD.3dshapes/R_0805_2012Metric.stl',
               'Capacitor_SMD.3dshapes/C_0805_2012Metric.stl',
               'Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x06_P2.54mm_Vertical.stl']


class ComponentConverterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.models = self.base/'model_store'
        self.fpdir = self.base/'footprints'
        self.fpdir.mkdir()
        self.lib = self.base/'symbols/cache.lib'
        self.lib.parent.mkdir()
        shutil.copyfile(PROJECT/'KiCad/Pickit-cache.lib', self.lib)
        self.config = self.base/'components.json'
        self.output = self.base/'bundle'
        self.settings = deepcopy(json.loads((FIXTURES/'components/control.json').read_text()))
        self.settings['footprint_libraries'] = {key:'footprints' for key in self.settings['footprint_libraries']}
        for entry in self.settings['components']:
            entry['symbol_library'] = 'symbols/cache.lib'
            name = entry['footprint'].split(':')[1]+'.kicad_mod'
            shutil.copyfile(FIXTURES/name, self.fpdir/name)
        for relative in MODEL_PATHS:
            self.model(relative)
        self.save()

    def model(self, relative, data=None):
        path = self.models/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if data is not None else b'opaque test bytes, not an interpreted STL\0'+relative.encode())
        return path

    def save(self):
        self.config.write_text(json.dumps(self.settings, indent=2)+'\n')

    def run_bundle(self, **options):
        self.save()
        return export_bundle(self.config, self.output, stl_root=self.models, **options)

    def r_only(self):
        self.settings['components'] = [e for e in self.settings['components'] if e['id']=='R0805']
        return self.settings['components'][0]

    def edit_r(self, function):
        path = self.fpdir/'R_0805_2012Metric.kicad_mod'
        path.write_text(function(path.read_text()))

    def manifest_write(self, result):
        (self.output/'manifest.json').write_bytes(bundle.json_bytes(result))

    def rehash(self, result, relative):
        data = (self.output/relative).read_bytes()
        for record in result['files']:
            if record['path']==relative:
                record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.manifest_write(result)

    def test_official_new_footprints_are_unchanged(self):
        data = json.loads((FIXTURES/'components/provenance.json').read_text())
        self.assertFalse(data['modified'])
        for record in data['files']:
            source = (FIXTURES/record['file']).read_bytes()
            self.assertEqual(len(source), record['bytes'])
            self.assertEqual(hashlib.sha256(source).hexdigest(), record['sha256'])

    def test_three_complete_chains_with_cds_fpl_and_exact_existing_bytes(self):
        before = {p:p.read_bytes() for p in [self.lib, *self.fpdir.iterdir(), *self.models.rglob('*.stl')]}
        result = self.run_bundle()
        self.assertEqual(result['summary']['generated_components'],3)
        self.assertEqual(result['summary']['complete_chains'],3)
        self.assertEqual(result['summary']['models'],3)
        for entry in result['components']:
            self.assertTrue(entry['source_target_mapping_verified'])
            self.assertTrue(entry['pin_mapping']['verified'])
            cds = parse_cds((self.output/entry['symbol']).read_bytes().decode('cp1251'))
            fpl = read_fpl_links((self.output/entry['footprint']).read_bytes().decode('cp1251'))
            self.assertEqual(cds.components[0].footprint.value, fpl['name'])
            self.assertEqual(fpl['numbers'], entry['pin_mapping']['source_numbers'])
            report = json.loads((self.output/entry['report']).read_text())
            self.assertTrue(report['symbol_conversion']['physical_pin_mapping_verified'])
            self.assertFalse(report['symbol_conversion']['gui_validated'])
            self.assertFalse(report['footprint_conversion']['models'][0]['frame_validated'])
        for model in result['models']:
            original = (self.models/model['source_relative']).read_bytes()
            self.assertEqual((self.output/model['canonical_path']).read_bytes(),original)
            self.assertEqual((self.output/model['runtime_path']).read_bytes(),original)
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))
        self.assertEqual(verify_bundle(self.output),result)

    def test_copy_to_another_directory_verifies_without_original_sources(self):
        result = self.run_bundle()
        relocated = self.base/'relocated/bundle copy'
        shutil.copytree(self.output, relocated)
        shutil.rmtree(self.models)
        shutil.rmtree(self.fpdir)
        self.lib.unlink()
        self.assertEqual(verify_bundle(relocated),result)
        self.assertNotIn(str(self.base), (relocated/'manifest.json').read_text())
        for entry in result['components']:
            self.assertNotIn(str(self.base), (relocated/entry['report']).read_text())

    def test_repeated_builds_have_identical_manifest_and_all_artifact_bytes(self):
        first = self.run_bundle()
        second_root = self.base/'second'
        second = export_bundle(self.config, second_root, stl_root=self.models)
        self.assertEqual(first, second)
        for path in self.output.rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(),(second_root/path.relative_to(self.output)).read_bytes())

    def test_exact_source_property_is_used_without_config_override(self):
        entry = self.r_only()
        entry.pop('footprint')
        self.lib.write_text(self.lib.read_text().replace('F2 "" -70 0 30 V V C CNN',
            'F2 "Resistor_SMD:R_0805_2012Metric" -70 0 30 V V C CNN'))
        result = self.run_bundle()
        self.assertEqual(result['summary']['complete_chains'],1)
        self.assertEqual(result['components'][0]['source']['selection'],'source_property')

    def test_empty_source_footprint_and_filters_do_not_guess_a_match(self):
        entry = self.r_only();entry.pop('footprint')
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'unresolved')
        self.assertEqual(result['components'][0]['error']['code'],'FOOTPRINT_IDENTIFIER_REQUIRED')
        self.assertEqual(result['models'],[])

    def test_invalid_identifiers_never_fall_back_to_basename(self):
        for value in ['R_0805_2012Metric','*:R_0805_2012Metric','A:../R','A:R*','A:B:C',':R','A:',' A:R','A:R\\X']:
            with self.subTest(value=value),self.assertRaises(ValueError): footprint_identifier(value)
        self.r_only()['footprint']='Unknown:R_0805_2012Metric'
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['error']['code'],'FOOTPRINT_LIBRARY_MISSING')

    def test_missing_symbol_file_and_exact_name_are_isolated(self):
        self.settings['components'][0]['symbol']='Missing'
        self.settings['components'][1]['symbol_library']='symbols/missing.lib'
        result = self.run_bundle()
        self.assertEqual(result['summary']['generated_components'],1)
        self.assertEqual(result['summary']['unresolved'],2)

    def test_source_footprint_filename_and_root_name_must_agree(self):
        self.r_only();self.edit_r(lambda s:s.replace('footprint "R_0805_2012Metric"','footprint "Other"',1))
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['error']['code'],'FOOTPRINT_NAME_MISMATCH')

    def test_missing_and_extra_pad_numbers_prevent_target_generation(self):
        self.r_only();self.edit_r(lambda s:s.replace('(pad "2"','(pad "3"',1))
        result = self.run_bundle();entry=result['components'][0]
        self.assertEqual(entry['status'],'unresolved')
        self.assertEqual(entry['pin_mapping']['missing_pads'],['2'])
        self.assertEqual(entry['pin_mapping']['extra_pads'],['3'])
        self.assertNotIn('symbol',entry)
        self.assertEqual(result['models'],[])

    def test_repeated_pads_are_ambiguous_and_not_deduplicated(self):
        self.r_only();self.edit_r(lambda s:s.replace('(pad "2"','(pad "1"',1))
        result = self.run_bundle();entry=result['components'][0]
        self.assertEqual(entry['status'],'ambiguous')
        self.assertEqual(entry['pin_mapping']['duplicate_pad_numbers'],['1'])

    def test_pic24_duplicate_pins_fail_without_mutating_source(self):
        self.settings['components'].append(dict(self.settings['components'][0], id='PIC',symbol='PIC24FJ256GB106'))
        source = self.lib.read_bytes()
        result = self.run_bundle()
        pic = next(e for e in result['components'] if e['id']=='PIC')
        self.assertEqual(pic['status'],'ambiguous')
        self.assertEqual(pic['pin_mapping']['duplicate_pin_numbers'],[str(n) for n in sorted(range(1,17),key=lambda n:str(n))])
        self.assertEqual(len(pic['pin_mapping']['source_numbers']),64)
        self.assertEqual(self.lib.read_bytes(), source)
        self.assertEqual(result['summary']['generated_components'],3)

    def test_mechanical_npth_is_excluded_from_electrical_mapping(self):
        self.r_only()
        self.edit_r(lambda s:s.rstrip()[:-1]+'(pad "" np_thru_hole circle (at 10 0) (size 1 1) (drill 1) (layers "*.Cu" "*.Mask")))')
        result = self.run_bundle();entry=result['components'][0]
        self.assertEqual(entry['pin_mapping']['pad_numbers'],['1','2'])
        self.assertEqual(entry['pin_mapping']['mechanical_pads'],1)
        self.assertTrue(entry['source_target_mapping_verified'])

    def test_same_number_in_separate_units_is_allowed_in_mapping_only(self):
        symbol = parse_library(self.lib.read_text()).get_symbol('R')
        second = deepcopy(next(unit for unit in symbol.units if unit.pins));second.number=2
        symbol.units.append(second);symbol.unit_count=2
        fp = parse_footprint(parse_sexpr((self.fpdir/'R_0805_2012Metric.kicad_mod').read_text()))
        result = pin_mapping(symbol,fp)
        self.assertTrue(result['verified'])
        self.assertEqual(len(result['pairs'][0]['occurrences']),2)

    def test_alternate_body_style_physical_numbers_must_agree(self):
        symbol = parse_library(self.lib.read_text()).get_symbol('R')
        alternate = deepcopy(next(unit for unit in symbol.units if unit.pins));alternate.style=2;alternate.pins[0].number='3'
        symbol.units.append(alternate)
        fp = parse_footprint(parse_sexpr((self.fpdir/'R_0805_2012Metric.kicad_mod').read_text()))
        result = pin_mapping(symbol,fp)
        self.assertEqual(result['status'],'ambiguous')
        self.assertTrue(result['alternate_style_mismatch'])

    def test_missing_models_require_explicit_partial_policy(self):
        self.r_only();shutil.rmtree(self.models)
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'unresolved')
        partial = export_bundle(self.config,self.base/'partial',stl_root=self.models,allow_missing_models=True)
        entry = partial['components'][0]
        self.assertTrue(entry['source_target_mapping_verified'])
        self.assertFalse(entry['chain_complete'])
        self.assertEqual(partial['models'],[])
        self.assertEqual(read_fpl_links((self.base/'partial'/entry['footprint']).read_text())['imports'],[])

    def test_empty_model_is_an_explicit_failure(self):
        self.r_only();self.model(MODEL_PATHS[0],b'')
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'failed')
        self.assertEqual(result['models'],[])

    def test_hidden_model_is_not_copied_and_missing_chain_is_explicit(self):
        self.r_only();self.edit_r(lambda s:s.replace('(offset','hide (offset',1))
        result = self.run_bundle(allow_missing_models=True)
        self.assertFalse(result['components'][0]['chain_complete'])
        self.assertEqual(result['models'],[])

    def test_model_symlink_outside_store_is_not_followed_into_bundle(self):
        self.r_only();original=self.models/MODEL_PATHS[0];original.unlink()
        external=self.base/'external.stl';external.write_bytes(b'external')
        original.symlink_to(external)
        result = self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'failed')
        self.assertEqual(result['models'],[])

    def test_multiple_model_categories_for_one_footprint_use_one_flat_folder(self):
        self.r_only()
        extra='(model "${ANY}/Capacitor_SMD.3dshapes/C_0805_2012Metric.step" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))'
        self.edit_r(lambda s:s.rstrip()[:-1]+extra+')')
        result = self.run_bundle();entry=result['components'][0]
        self.assertEqual(result['summary']['models'],2)
        self.assertTrue(entry['chain_complete'])
        self.assertEqual(len(read_fpl_links((self.output/entry['footprint']).read_text())['imports']),2)

    def test_duplicate_source_reference_has_one_model_import(self):
        self.r_only()
        extra='(model "${ANY}/Resistor_SMD.3dshapes/R_0805_2012Metric.step" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))'
        self.edit_r(lambda s:s.rstrip()[:-1]+extra+')')
        result = self.run_bundle();entry=result['components'][0]
        self.assertEqual(len(entry['source_model_references']),2)
        self.assertEqual(len(entry['models']),1)

    def test_same_basename_across_libraries_and_categories_has_distinct_aliases(self):
        first=self.r_only();first['footprint']='A:R_0805_2012Metric'
        second=dict(first,id='OtherR',footprint='B:R_0805_2012Metric')
        other=self.base/'other.pretty';other.mkdir()
        text=(self.fpdir/'R_0805_2012Metric.kicad_mod').read_text().replace('Resistor_SMD.3dshapes','Other.3dshapes')
        (other/'R_0805_2012Metric.kicad_mod').write_text(text)
        self.model('Other.3dshapes/R_0805_2012Metric.stl',b'different opaque bytes')
        self.settings['components'].append(second)
        self.settings['footprint_libraries']={'A':'footprints','B':'other.pretty'}
        result=self.run_bundle()
        self.assertEqual(result['summary']['complete_chains'],2)
        self.assertEqual(len({m['import_basename'] for m in result['models']}),2)
        self.assertEqual(len({e['target_footprint'] for e in result['components']}),2)

    def test_same_asset_with_different_source_transforms_preserves_both_records(self):
        entry=self.r_only()
        entry['model_transform']={'translation':[0,0,0],'rotation':[0,0,0],'scale':[1,1,1]}
        extra='(model "${ANY}/Resistor_SMD.3dshapes/R_0805_2012Metric.step" (offset (xyz 1 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))'
        self.edit_r(lambda s:s.rstrip()[:-1]+extra+')')
        result=self.run_bundle();models=result['components'][0]['models']
        self.assertEqual(len(models),2)
        self.assertEqual({tuple(m['source_reference']['offset']) for m in models},{(0,0,0),(1,0,0)})
        self.assertEqual(result['summary']['models'],1)

    def test_nonidentity_source_transform_requires_explicit_override(self):
        self.r_only();self.edit_r(lambda s:s.replace('(xyz 0 0 0)','(xyz 1 0 0)',1))
        result=self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'failed')
        self.assertEqual(result['models'],[])

    def test_model_case_collisions_are_rejected_before_a_second_copy(self):
        stage=self.base/'assets';stage.mkdir()
        assets=bundle.Assets(stage)
        source=self.models/MODEL_PATHS[0]
        assets.add(ModelMatch(ModelReference('Category.3dshapes/File.step'),source,
                              PurePosixPath('Category.3dshapes/File.stl')))
        with self.assertRaises(ValueError):
            assets.add(ModelMatch(ModelReference('category.3dshapes/file.step'),source,
                                  PurePosixPath('category.3dshapes/file.stl')))

    def test_windows_unsafe_model_basename_is_ambiguous(self):
        self.r_only();self.model('Resistor_SMD.3dshapes/Bad?.stl')
        self.edit_r(lambda s:s.replace('/R_0805_2012Metric.step','/Bad?.step'))
        result=self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'ambiguous')
        self.assertEqual(result['models'],[])

    def test_malformed_numeric_pad_does_not_abort_other_components(self):
        self.edit_r(lambda s:s.replace('(size 1.025 1.4)','(size (bad) 1.4)',1))
        result=self.run_bundle()
        self.assertEqual(result['summary']['generated_components'],2)
        self.assertEqual(result['summary']['failed'],1)

    def test_readback_corruption_rejects_item_and_rolls_back_model_allocations(self):
        entry=self.r_only();self.settings['components'].append(dict(entry,id='ZGood'))
        original=bundle.convert_detailed
        calls=0
        def corrupt(root,name,**options):
            nonlocal calls
            calls+=1
            result=original(root,name,**options)
            if calls==1:
                return type(result)(result.fpl.replace('pin: "1"','pin: "3"'),result.warnings,result.report)
            return result
        with patch.object(bundle,'convert_detailed',side_effect=corrupt): result=self.run_bundle()
        self.assertEqual([e['status'] for e in result['components']],['failed','generated_with_loss'])
        self.assertEqual(result['summary']['models'],1)
        self.assertEqual(verify_bundle(self.output),result)

    def test_unexpected_pipeline_exception_is_isolated_and_assets_removed(self):
        self.r_only()
        with patch.object(bundle,'convert_detailed',side_effect=RuntimeError('simulated')): result=self.run_bundle()
        self.assertEqual(result['components'][0]['error']['code'],'UNEXPECTED_CONVERSION_ERROR')
        self.assertEqual(result['models'],[])
        self.assertFalse(list(self.output.rglob('*.stl')))

    def test_strict_rejection_has_no_target_artifacts(self):
        result=self.run_bundle(strict=True)
        self.assertEqual(result['summary']['generated_components'],0)
        self.assertEqual(result['summary']['rejected_loss'],3)
        self.assertFalse(list(self.output.rglob('*.cds')))
        self.assertEqual(result['models'],[])

    def test_io_failure_after_symbol_write_removes_partial_target(self):
        self.r_only();original=Path.write_bytes
        def failing(path,data):
            if path.name=='footprint.fpl': raise OSError('simulated FPL write failure')
            return original(path,data)
        with patch.object(Path,'write_bytes',failing): result=self.run_bundle()
        self.assertEqual(result['components'][0]['status'],'failed')
        self.assertFalse(list(self.output.rglob('*.cds')))
        self.assertFalse(list(self.output.rglob('*.stl')))
        report=json.loads((self.output/result['components'][0]['report']).read_text())
        self.assertFalse(report['symbol_conversion']['target_output_generated'])

    def test_existing_output_is_preserved_and_never_replaced(self):
        self.run_bundle();before=(self.output/'manifest.json').read_bytes()
        with self.assertRaises(ValueError): self.run_bundle()
        self.assertEqual((self.output/'manifest.json').read_bytes(),before)

    def test_global_staging_verification_failure_does_not_publish_bundle(self):
        self.r_only()
        with patch.object(bundle,'verify_bundle',side_effect=ValueError('simulated final check failure')):
            with self.assertRaises(ValueError): self.run_bundle()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.base.glob('.component-bundle-*')))

    def test_protected_source_and_model_directories_remain_unchanged(self):
        before=self.lib.read_bytes()
        for output in (self.fpdir/'bundle',self.lib.parent/'bundle',self.models/'bundle',self.config):
            with self.subTest(output=output),self.assertRaises(ValueError): export_bundle(self.config,output,stl_root=self.models)
        self.assertEqual(self.lib.read_bytes(),before)
        self.assertFalse((self.models/'bundle').exists())

    def test_output_symlink_and_input_hardlink_are_rejected(self):
        self.output.symlink_to(self.fpdir,target_is_directory=True)
        with self.assertRaises(ValueError): self.run_bundle()
        self.output.unlink();os.link(self.lib,self.output)
        before=self.lib.read_bytes()
        with self.assertRaises(ValueError): self.run_bundle()
        self.assertEqual(self.lib.read_bytes(),before)

    def test_config_duplicate_keys_casefold_ids_unknown_fields_and_nonfinite_values_rejected(self):
        mutations=[lambda c:c.update(schema_version=2),lambda c:c.update(extra=True),
                   lambda c:c['components'].append(dict(c['components'][0],id='r0805')),
                   lambda c:c['components'][0].update(misspelled=True),
                   lambda c:c.update(aperture_defaults={'mask_margin':float('nan')}),
                   lambda c:c['components'][0].update(model_transform={'scale':[0,1,1]})]
        original=deepcopy(self.settings)
        for mutation in mutations:
            self.settings=deepcopy(original);mutation(self.settings);self.save()
            with self.assertRaises(ValueError): export_bundle(self.config,self.output,stl_root=self.models)
            self.assertFalse(self.output.exists())
        self.settings=original;self.save()
        self.config.write_text(self.config.read_text().replace('"schema_version": 1','"schema_version": 1, "schema_version": 1'))
        with self.assertRaises(ValueError): export_bundle(self.config,self.output,stl_root=self.models)

    def test_model_and_target_artifact_checksum_tampering_is_detected(self):
        result=self.run_bundle()
        for relative in [result['models'][0]['runtime_path'],result['components'][0]['symbol']]:
            path=self.output/relative;original=path.read_bytes();path.write_bytes(original+b'corrupt')
            with self.assertRaises(ValueError): verify_bundle(self.output)
            path.write_bytes(original)

    def test_rehashed_model_copy_disagreement_is_detected(self):
        result=self.run_bundle();model=result['models'][0]
        (self.output/model['runtime_path']).write_bytes(b'changed')
        self.rehash(result,model['runtime_path'])
        with self.assertRaises(ValueError): verify_bundle(self.output)

    def test_rehashed_bad_pin_number_is_detected_by_record_relationships(self):
        result=self.run_bundle();entry=result['components'][0]
        path=self.output/entry['footprint']
        path.write_bytes(path.read_bytes().replace(b'pin: "1"',b'pin: "3"',1))
        self.rehash(result,entry['footprint'])
        with self.assertRaises(ValueError): verify_bundle(self.output)

    def test_unindexed_extra_file_symlink_and_traversal_are_rejected(self):
        result=self.run_bundle();extra=self.output/'foreign.txt';extra.write_text('foreign')
        with self.assertRaises(ValueError): verify_bundle(self.output)
        extra.unlink();extra.symlink_to(self.lib)
        with self.assertRaises(ValueError): verify_bundle(self.output)
        extra.unlink();result['files'][0]['path']='../symbols/cache.lib';self.manifest_write(result)
        with self.assertRaises(ValueError): verify_bundle(self.output)

    def test_false_gui_and_summary_claims_are_rejected(self):
        result=self.run_bundle();original=deepcopy(result)
        result['gui_validated']=True;self.manifest_write(result)
        with self.assertRaises(ValueError): verify_bundle(self.output)
        result=original;result['summary']['complete_chains']=100;self.manifest_write(result)
        with self.assertRaises(ValueError): verify_bundle(self.output)

    def test_cli_build_verify_and_partial_exit_codes(self):
        command=[sys.executable,'-B','-m','src.component_converter']
        built=subprocess.run(command+[str(self.config),str(self.output),'--stl-root',str(self.models)],cwd=PROJECT,capture_output=True,text=True)
        self.assertEqual(built.returncode,0,built.stderr)
        checked=subprocess.run(command+['--verify',str(self.output)],cwd=PROJECT,capture_output=True,text=True)
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.settings['components'][0]['footprint']='Missing:Nope';self.save()
        partial=subprocess.run(command+[str(self.config),str(self.base/'partial'),'--stl-root',str(self.models)],cwd=PROJECT,capture_output=True,text=True)
        self.assertEqual(partial.returncode,2,partial.stderr)
        repeated=subprocess.run(command+[str(self.config),str(self.output)],cwd=PROJECT,capture_output=True,text=True)
        self.assertEqual(repeated.returncode,1)


if __name__ == '__main__':
    unittest.main()
