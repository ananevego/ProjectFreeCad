"""Power/NC terminals preserve identity while exposing lost electrical rules."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.symbol_converter import parse_library, SymbolParseError
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.schemator_format import parse_cds
from src.component_converter import export_bundle, verify_bundle
from test_symbol_converter import legacy
from test_symbol_electrical import modern
from test_symbol_multiunit import multi

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
POLICY='connectable-with-loss'
CONTROLS=(('Device.kicad_sym','Fuse_Polarized'),('Device.kicad_sym','Opamp_Dual'),
          ('Comparator.kicad_sym','LM393'),('Comparator.kicad_sym','LM311'),
          ('Pickit-cache.lib','MCP1525'),('Pickit-cache.lib','MCP601_8PIN'))


def fake_models(root):
    for category,name in [('Package_DIP','DIP-8_W7.62mm'),('Package_TO_SOT_SMD','SOT-23')]:
        path=root/(category+'.3dshapes')/(name+'.stl')
        path.parent.mkdir(parents=True)
        path.write_bytes(('opaque selected asset '+name).encode())


class SymbolPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.libraries={name:parse_library((PROJECT/'KiCad'/name if name.endswith('.lib')
            else FIXTURES/'symbols'/name).read_text()) for name in {p[0] for p in CONTROLS}}

    def test_power_roles_emit_ordinary_numbered_terminals(self):
        baseline=convert_symbol(modern(('passive',)),'Base').cds
        for kind in ('power_in','power_out'):
            result=convert_symbol(modern((kind,)),'Base')
            self.assertEqual(result.cds,baseline)
            self.assertEqual(parse_cds(result.cds),result.document)
            self.assertEqual(result.report['counts']['power_pins'],1)
            self.assertFalse(result.report['pin_semantics']['power_roles_transferred'])

    def test_modern_mixed_types_report_loss_and_exact_source_roles(self):
        result=convert_symbol(modern(('power_in','power_out','input','passive')),'Base')
        report=result.report
        self.assertEqual(report['target']['source_pin_profile'],'visible-line-power-v1')
        loss=next(d for d in report['diagnostics'] if d['code']=='SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED')
        self.assertEqual(loss['context']['source_electrical_types'],
                         {'power_in':1,'power_out':1,'input':1,'passive':1})
        self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
        self.assertEqual(report['counts']['power_pins'],2)
        self.assertEqual(report['counts']['no_connect_pins'],0)

    def test_legacy_W_and_w_keep_distinct_roles_and_physical_numbers(self):
        source=parse_library(legacy('X VCC 1 -200 0 100 R 40 50 1 1 W\n'
                                    'X VOUT 2 200 0 100 L 40 50 1 1 w'))
        result=convert_symbol(source,'Test')
        pins=result.report['pin_semantics']['pins']
        self.assertEqual([p['source_electrical_type'] for p in pins],['power_in','power_out'])
        self.assertEqual([p.pin.value for p in parse_cds(result.cds).components[0].polylines],['1','2'])

    def test_default_no_connect_rejects_both_source_formats(self):
        for source,name in [(modern(('no_connect',)),'Base'),
                            (parse_library(legacy('X NC 1 -200 0 100 R 40 50 1 1 N')),'Test')]:
            with self.assertRaisesRegex(SymbolParseError,'explicit connectable-with-loss'):
                convert_symbol(source,name)

    def test_explicit_nc_is_connectable_and_has_a_loss_for_each_pin(self):
        result=convert_symbol(modern(('no_connect','power_in','no_connect','passive')),
                              'Base',no_connect_policy=POLICY)
        report=result.report;part=parse_cds(result.cds).components[0]
        self.assertEqual(part.pin_count,4)
        self.assertEqual(report['counts']['no_connect_pins'],2)
        self.assertEqual(report['conversion_settings']['no_connect_policy'],POLICY)
        self.assertFalse(report['pin_semantics']['native_no_connect_enforced'])
        losses=[d for d in report['diagnostics'] if d['code']=='SYMBOL_NO_CONNECT_AS_TERMINAL']
        self.assertEqual([d['context']['pin_number'] for d in losses],['1','3'])
        self.assertTrue(all(d['severity']=='loss' and not d['context']['native_no_connect_enforced'] for d in losses))
        for entry in report['pin_semantics']['pins']:
            record=part.polylines[entry['target_polyline_index']]
            self.assertEqual([c.node for c in record.corners],entry['target_node_flags'])
            self.assertEqual(entry['target_node_flags'],[0,1])
            self.assertEqual(record.layer,8)
            self.assertTrue(entry['native_connectable'])
            self.assertEqual(record.pin.value,entry['source_pin_number'])

    def test_legacy_N_opt_in_keeps_name_number_and_free_endpoint(self):
        result=convert_symbol(parse_library(legacy('X NC 1 -200 0 100 R 40 50 1 1 N')),
                              'Test',no_connect_policy=POLICY)
        record=parse_cds(result.cds).components[0].polylines[0]
        self.assertEqual((record.pin.value,record.description.value),('1','NC'))
        self.assertEqual((record.corners[-1].x,record.corners[-1].y,record.corners[-1].node),(-5080000,0,1))

    def test_power_and_nc_source_typed_and_raw_records_are_not_mutated(self):
        source=modern(('power_in','power_out','no_connect'));before=deepcopy(source)
        result=convert_symbol(source,'Base',no_connect_policy=POLICY)
        self.assertEqual(source,before)
        pins=result.report['source_symbol']['units'][0]['pins']
        self.assertEqual([p['raw'][1] for p in pins],['power_in','power_out','no_connect'])

    def test_explicit_nc_policy_does_not_bypass_hidden_shapes_or_alternates(self):
        for kind in ('power_in','power_out','no_connect'):
            for attr,value in [('hidden',True),('graphic_style','future_style'),
                               ('alternates',[dict(name='ALT',electrical_type='input',graphic_style='line')])]:
                source=modern((kind,));setattr(source.symbols['Base'].pins_for()[0],attr,value)
                with self.subTest(kind=kind,attr=attr),self.assertRaisesRegex(SymbolParseError,'hidden pin|unsupported graphic style|alternate pin modes'):
                    convert_symbol(source,'Base',no_connect_policy=POLICY)

    def test_power_symbol_and_virtual_flags_remain_rejected(self):
        for attr,value in [('power',True),('in_bom',False),('on_board',False)]:
            source=modern(('power_in',));setattr(source.symbols['Base'],attr,value)
            with self.subTest(attr=attr),self.assertRaisesRegex(SymbolParseError,'Power/virtual/BOM-excluded'):
                convert_symbol(source,'Base',no_connect_policy=POLICY)

    def test_invalid_nc_policy_rejects_even_when_no_nc_pin_exists(self):
        for value in ('ignore','',None,True,1,[],{}):
            for source in (modern(('passive',)),multi()):
                with self.subTest(value=value),self.assertRaisesRegex(SymbolParseError,'No-connect policy'):
                    convert_symbol(source,'Base',no_connect_policy=value)

    def test_strict_power_and_nc_preserve_report_but_reject_artifact(self):
        for kinds in [('power_in','power_out'),('no_connect',)]:
            source=modern(kinds)
            with self.assertRaises(LossySymbolConversionError) as raised:
                convert_symbol(source,'Base',no_connect_policy=POLICY,strict=True)
            report=raised.exception.report
            self.assertFalse(report['target_output_generated'])
            self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
            self.assertEqual(report['status'],'rejected_loss')
            self.assertNotIn('artifact_sha256',report)
            normal=convert_symbol(source,'Base',no_connect_policy=POLICY)
            self.assertEqual(report['proposed_artifact_sha256'],hashlib.sha256(normal.cds.encode('cp1251')).hexdigest())

    def test_disjoint_units_aggregate_power_and_nc_without_losing_record_indices(self):
        source=multi(type2='no_connect')
        source.symbols['Base'].units[1].pins[0].electrical_type='power_out'
        with self.assertRaisesRegex(SymbolParseError,'no-connect cannot be enforced'):convert_symbol(source,'Base')
        result=convert_symbol(source,'Base',no_connect_policy=POLICY)
        report=result.report;part=parse_cds(result.cds).components[0]
        self.assertEqual((report['counts']['power_pins'],report['counts']['no_connect_pins']),(1,2))
        for entry in report['pin_semantics']['pins']:
            p=part.polylines[entry['target_polyline_index']]
            self.assertEqual(p.pin.value,entry['source_pin_number'])
            self.assertEqual((p.corners[-1].x,p.corners[-1].y),entry['connection_point_nm'])
        losses=[d['context'] for d in report['diagnostics'] if d['code']=='SYMBOL_NO_CONNECT_AS_TERMINAL']
        self.assertEqual([d['rendered_unit'] for d in losses],[2,2])
        for context in losses:
            self.assertEqual(part.polylines[context['target_polyline_index']].pin.value,context['pin_number'])

    def test_common_or_repeated_power_nc_numbers_are_not_deduplicated(self):
        for kind in ('power_in','no_connect'):
            source=multi(type2=kind);source.symbols['Base'].units[2].pins[0].number='1'
            with self.assertRaisesRegex(SymbolParseError,'must be disjoint'):
                convert_symbol(source,'Base',no_connect_policy=POLICY)
            source=multi();common=source.symbols['Base'].units[0]
            common.pins.append(deepcopy(source.symbols['Base'].units[1].pins[0]))
            common.pins[0].number='5';common.pins[0].electrical_type=kind
            with self.assertRaisesRegex(SymbolParseError,'common pins'):
                convert_symbol(source,'Base',no_connect_policy=POLICY)

    def test_real_LM393_has_two_signal_units_and_one_power_unit(self):
        result=convert_symbol(self.libraries['Comparator.kicad_sym'],'LM393')
        report=result.report;part=parse_cds(result.cds).components[0]
        self.assertEqual((part.pin_count,report['counts']['source_units'],report['counts']['power_pins']),(8,3,2))
        self.assertEqual(sorted(p.pin.value for p in part.polylines if p.pin),list('12345678'))
        power=[p for p in report['pin_semantics']['pins'] if p['source_electrical_type']=='power_in']
        self.assertEqual([(p['source_pin_number'],p['rendered_unit']) for p in power],[('8',3),('4',3)])
        self.assertFalse(report['unit_layout']['independent_unit_placement_transferred'])

    def test_real_MCP601_NC_numbers_remain_physical_and_connectable(self):
        result=convert_symbol(self.libraries['Pickit-cache.lib'],'MCP601_8PIN',no_connect_policy=POLICY)
        report=result.report
        self.assertEqual((report['counts']['pins'],report['counts']['power_pins'],report['counts']['no_connect_pins']),(8,2,3))
        nc=[p for p in report['pin_semantics']['pins'] if p['source_electrical_type']=='no_connect']
        self.assertEqual([p['source_pin_number'] for p in nc],['1','5','8'])
        self.assertTrue(all(p['native_connectable'] and not p['native_no_connect_enforced'] for p in nc))

    def test_unused_nc_policy_preserves_previously_supported_reports_and_bytes(self):
        for source,name in [(modern(('input','passive')),'Base'),(multi(),'Base'),
                            (self.libraries['Device.kicad_sym'],'R')]:
            default=convert_symbol(source,name);explicit=convert_symbol(source,name,no_connect_policy=POLICY)
            self.assertEqual(default,explicit)
            self.assertNotIn('no_connect_policy',explicit.report['conversion_settings'])

    def test_saved_real_controls_reproduce_native_bytes_and_semantic_reports(self):
        for filename,name in CONTROLS:
            out=PROJECT/'output/symbols'/(name+'_power.cds')
            saved=json.loads(out.with_suffix('.report.json').read_text())
            settings=saved['conversion_settings']
            result=convert_symbol(self.libraries[filename],name,project_name=out.name,
                no_connect_policy=settings.get('no_connect_policy','reject'))
            self.assertEqual(result.cds.encode('cp1251'),out.read_bytes())
            for key in ('source','output'):saved.pop(key)
            self.assertEqual(json.loads(json.dumps(result.report)),saved)

    def test_new_DIP_fixture_is_pinned_and_unchanged(self):
        data=json.loads((FIXTURES/'components/power-provenance.json').read_text())
        self.assertFalse(data['modified'])
        for record in data['files']:
            raw=(FIXTURES/record['file']).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(),len(raw)),(record['sha256'],record['bytes']))

    def test_bundle_NC_number_mapping_does_not_claim_no_connect_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store';fake_models(models);out=root/'bundle'
            manifest=export_bundle(FIXTURES/'components/power.json',out,stl_root=models)
            self.assertEqual((manifest['summary']['generated_components'],manifest['summary']['complete_chains'],manifest['summary']['models']),(3,3,2))
            self.assertEqual(manifest['settings']['symbol_no_connect_policy'],POLICY)
            for entry in manifest['components']:
                report=json.loads((out/entry['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['pin_semantics']['power_roles_transferred'])
                self.assertFalse(report['gui_validated'] or report['target_import_verified'])
                if entry['id']=='Amplifier8NC':
                    self.assertEqual(entry['pin_mapping']['source_numbers'],list('12345678'))
                    self.assertFalse(report['pin_semantics']['native_no_connect_enforced'])
            relocated=root/'moved';shutil.copytree(out,relocated);shutil.rmtree(models);shutil.rmtree(out)
            self.assertEqual(verify_bundle(relocated),manifest)

    def test_strict_bundle_keeps_power_nc_losses_without_native_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'bundle';manifest=export_bundle(FIXTURES/'components/power.json',out,strict=True)
            self.assertEqual(manifest['summary']['generated_components'],0)
            self.assertEqual(manifest['summary']['models'],0)
            self.assertFalse(list(out.rglob('*.cds')) or list(out.rglob('*.fpl')))
            for entry in manifest['components']:
                report=json.loads((out/entry['report']).read_text())['rejection_report']
                self.assertFalse(report['target_output_generated'])
                self.assertFalse(report['pin_semantics']['power_roles_transferred'])
            self.assertEqual(verify_bundle(out),manifest)

    def test_bundle_default_rejects_only_NC_component_and_preserves_power_chains(self):
        config=json.loads((FIXTURES/'components/power.json').read_text())
        config.pop('symbol_no_connect_policy')
        for key in config['footprint_libraries']:config['footprint_libraries'][key]=str(FIXTURES)
        for entry in config['components']:
            entry['symbol_library']=str((FIXTURES/'components'/entry['symbol_library']).resolve())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store';fake_models(models)
            path=root/'config.json';path.write_text(json.dumps(config));out=root/'bundle'
            manifest=export_bundle(path,out,stl_root=models)
            self.assertEqual(manifest['summary']['generated_components'],2)
            self.assertNotIn('symbol_no_connect_policy',manifest['settings'])
            nc=next(e for e in manifest['components'] if e['id']=='Amplifier8NC')
            self.assertNotIn('symbol',nc)
            self.assertIn('no-connect cannot be enforced',json.dumps(nc))
            self.assertEqual(verify_bundle(out),manifest)

    def test_invalid_bundle_policy_prevents_publication(self):
        config=json.loads((FIXTURES/'components/power.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'config.json';out=root/'bundle'
            for value in ('ignore',None,True,[],{}):
                config['symbol_no_connect_policy']=value;path.write_text(json.dumps(config))
                with self.assertRaisesRegex(ValueError,'No-connect policy'):export_bundle(path,out)
                self.assertFalse(out.exists())

    def test_CLI_NC_default_invalid_policy_and_strict_preserve_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'power.cds'
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(PROJECT/'KiCad/Pickit-cache.lib'),
                 str(out),'--symbol','MCP601_8PIN']
            def run(extra):return subprocess.run(cmd+extra,cwd=PROJECT,capture_output=True,text=True)
            result=run(['--no-connect-policy',POLICY]);self.assertEqual(result.returncode,0,result.stderr)
            before=out.read_bytes();report_before=out.with_suffix('.report.json').read_bytes()
            for extra,code in [([],1),(['--no-connect-policy','ignore'],2)]:
                result=run(extra);self.assertEqual(result.returncode,code,result.stderr)
                self.assertEqual(out.read_bytes(),before)
                self.assertEqual(out.with_suffix('.report.json').read_bytes(),report_before)
            result=run(['--no-connect-policy',POLICY,'--strict'])
            self.assertEqual(result.returncode,2,result.stderr);self.assertEqual(out.read_bytes(),before)
            report=json.loads(out.with_suffix('.report.json').read_text())
            self.assertFalse(report['target_output_generated'] or report['pin_semantics']['native_no_connect_enforced'])


if __name__=='__main__':unittest.main()
