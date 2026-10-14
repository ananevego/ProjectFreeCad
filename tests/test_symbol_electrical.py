"""Electrical source semantics versus native endpoint identity and bundle scope."""
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
from test_symbol_converter import library, symbol, pin, legacy

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
# Source spelling is the oracle; do not derive coverage from the target allowlist.
TYPES=('input','output','bidirectional','tri_state','passive','unspecified',
       'free','open_collector','open_emitter')
CONTROLS=('Antenna','Antenna_Chip','DelayLine','Q_SCR_AGK','Speaker')


def modern(types=TYPES, graphic=''):
    pins=''.join(pin(str(i+1),name=f'FUNCTION{i+1}',at=f'-5.08 {i*2.54} 0').replace(
        'input line',kind+' line') for i,kind in enumerate(types))
    return parse_library(library(symbol(body='(symbol "Base_1_1" '+graphic+pins+')')))


def fake_models(root):
    for category,name in [('Package_TO_SOT_SMD','SOT-23'),('Buzzer_Beeper','Speaker_CUI_CMR-1206S-67')]:
        path=root/(category+'.3dshapes')/(name+'.stl')
        path.parent.mkdir(parents=True)
        path.write_bytes(('opaque selected asset '+name).encode())


class SymbolElectricalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=parse_library((FIXTURES/'symbols/Device.kicad_sym').read_text())

    def test_each_ordinary_type_emits_same_native_endpoint_records(self):
        baseline=convert_symbol(modern(('passive',)),'Base').cds
        for kind in TYPES:
            with self.subTest(kind=kind):
                result=convert_symbol(modern((kind,)),'Base')
                self.assertEqual(result.cds,baseline)
                self.assertEqual(parse_cds(result.cds),result.document)

    def test_mixed_types_retain_literal_numbers_names_and_connection_points(self):
        result=convert_symbol(modern(),'Base')
        native=parse_cds(result.cds).components[0]
        pins=[p for p in native.polylines if p.pin]
        self.assertEqual(native.pin_count,9)
        self.assertEqual([p.pin.value for p in pins],[str(i) for i in range(1,10)])
        self.assertEqual([p.description.value for p in pins],[f'FUNCTION{i}' for i in range(1,10)])
        for i,p in enumerate(pins):
            self.assertEqual((p.layer,p.pin.layer,p.description.layer),(8,9,14))
            self.assertEqual([(c.x,c.y,c.node) for c in p.corners],
                             [(-2540000,i*2540000,0),(-5080000,i*2540000,1)])

    def test_semantic_report_maps_every_source_type_to_own_native_record(self):
        result=convert_symbol(modern(),'Base');report=result.report
        self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
        self.assertEqual(report['target']['source_pin_profile'],'visible-line-electrical-v1')
        native=parse_cds(result.cds).components[0]
        for i,entry in enumerate(report['pin_semantics']['pins']):
            self.assertEqual(entry['source_electrical_type'],TYPES[i])
            self.assertEqual(entry['source_pin_name'],f'FUNCTION{i+1}')
            p=native.polylines[entry['target_polyline_index']]
            self.assertEqual(entry['source_pin_number'],p.pin.value)
            self.assertEqual(entry['target_pin_number'],p.pin.value)
            self.assertEqual(entry['connection_point_nm'],(p.corners[1].x,p.corners[1].y))

    def test_electrical_loss_has_exact_type_counts_even_for_mixed_passive(self):
        result=convert_symbol(modern(('input','passive','input','open_collector')),'Base')
        losses=[d for d in result.report['diagnostics'] if d['code']=='SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED']
        self.assertEqual(len(losses),1)
        self.assertEqual(losses[0]['severity'],'loss')
        self.assertEqual(losses[0]['context']['source_electrical_types'],
                         {'input':2,'passive':1,'open_collector':1})
        self.assertEqual(result.report['counts']['losses'],
                         sum(d['severity']=='loss' for d in result.report['diagnostics']))

    def test_source_typed_and_raw_pin_semantics_are_unchanged(self):
        source=modern();before=deepcopy(source)
        result=convert_symbol(source,'Base')
        self.assertEqual(source,before)
        pins=result.report['source_symbol']['units'][0]['pins']
        self.assertEqual([p['electrical_type'] for p in pins],list(TYPES))
        self.assertTrue(all(p['raw'][1]==p['electrical_type'] for p in pins))

    def test_strict_retains_semantics_but_rejects_output(self):
        with self.assertRaises(LossySymbolConversionError) as caught:
            convert_symbol(modern(),'Base',strict=True)
        report=caught.exception.report
        self.assertEqual(report['status'],'rejected_loss')
        self.assertFalse(report['target_output_generated'])
        self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
        self.assertEqual(len(report['pin_semantics']['pins']),9)
        self.assertNotIn('artifact_sha256',report)
        self.assertEqual(report['proposed_artifact_sha256'],
                         hashlib.sha256(convert_symbol(modern(),'Base').cds.encode('cp1251')).hexdigest())

    def test_no_connect_is_rejected_by_default_for_modern_and_legacy(self):
        for source,name in [(modern(('no_connect',)),'Base'),
                            (parse_library(legacy('X IN 1 -200 0 100 R 40 50 1 1 N')),'Test')]:
            with self.subTest(name=name),self.assertRaisesRegex(SymbolParseError,'no-connect cannot be enforced'):
                convert_symbol(source,name)

    def test_unknown_type_is_rejected_after_typed_model_mutation(self):
        source=modern(('input',));source.symbols['Base'].pins_for()[0].electrical_type='future_type'
        with self.assertRaisesRegex(SymbolParseError,'unsupported electrical type'):
            convert_symbol(source,'Base')

    def test_nonpassive_hidden_shaped_and_alternate_pins_remain_rejected(self):
        for attr,value in [('hidden',True),('graphic_style','future_style'),
                           ('alternates',[dict(name='ALT',electrical_type='output',graphic_style='line')])]:
            source=modern(('output',));setattr(source.symbols['Base'].pins_for()[0],attr,value)
            with self.subTest(attr=attr),self.assertRaisesRegex(SymbolParseError,'hidden pin|unsupported graphic style|alternate pin modes'):
                convert_symbol(source,'Base')

    def test_legacy_type_codes_keep_number_function_and_external_point(self):
        for letter,kind in [('I','input'),('O','output'),('B','bidirectional'),('T','tri_state'),
                            ('P','passive'),('U','unspecified'),('C','open_collector'),('E','open_emitter')]:
            source=parse_library(legacy(f'X IN 1 -200 0 100 R 40 50 1 1 {letter}'))
            result=convert_symbol(source,'Test');p=parse_cds(result.cds).components[0].polylines[-1]
            self.assertEqual((p.pin.value,p.description.value),('1','IN'))
            self.assertEqual((p.corners[1].x,p.corners[1].y,p.corners[1].node),(-5080000,0,1))
            self.assertEqual(result.report['source_symbol']['units'][0]['pins'][0]['electrical_type'],kind)
            if kind!='passive':
                self.assertEqual(result.report['pin_semantics']['pins'][0]['source_electrical_type'],kind)

    def test_hiding_numbers_and_names_does_not_remove_nonpassive_identity(self):
        source=modern(('input','output'));s=source.symbols['Base']
        s.pin_numbers_hidden=s.pin_names_hidden=True
        result=convert_symbol(source,'Base')
        for p in parse_cds(result.cds).components[0].polylines:
            self.assertEqual(p.pin.size,0)
            self.assertIsNone(p.description)
            self.assertEqual(p.corners[-1].node,1)
        self.assertEqual([p['source_pin_name'] for p in result.report['pin_semantics']['pins']],
                         ['FUNCTION1','FUNCTION2'])

    def test_curves_and_electrical_profiles_have_correct_independent_record_indices(self):
        graphic='(circle (center 0 0) (radius 1) (stroke (width 0.254) (type default)) (fill (type none)))'
        result=convert_symbol(modern(('output','open_collector'),graphic),'Base')
        self.assertEqual(result.report['curves'][0]['target_polyline_index'],0)
        self.assertEqual([p['target_polyline_index'] for p in result.report['pin_semantics']['pins']],[1,2])
        self.assertEqual(result.report['target']['source_graphics_profile'],'unfilled-curves-v1')
        self.assertFalse(parse_cds(result.cds).components[0].polylines[0].corners[0].node)

    def test_real_controls_preserve_source_functions_and_type_sequences(self):
        expected={'Antenna':['input'],'Antenna_Chip':['input','passive'],
                  'DelayLine':['input','passive','passive'],
                  'Q_SCR_AGK':['input','passive','passive'],'Speaker':['input','input']}
        for name,types in expected.items():
            result=convert_symbol(self.device,name);native=parse_cds(result.cds).components[0]
            self.assertEqual([p['source_electrical_type'] for p in result.report['pin_semantics']['pins']],types)
            self.assertEqual(native.pin_count,len(types))
            source_symbol=self.device.get_symbol(name)
            for source,target in zip(source_symbol.pins_for(),[p for p in native.polylines if p.pin]):
                self.assertEqual(target.pin.value,source.number)
                if source_symbol.pin_names_hidden:
                    self.assertIsNone(target.description)
                else:
                    self.assertEqual(target.description.value,source.name)
            self.assertFalse(result.report['gui_validated'] or result.report['physical_pin_mapping_verified'])
        self.assertEqual(len(convert_symbol(self.device,'DelayLine').report['curves']),8)

    def test_real_scr_literal_function_mapping_is_not_an_erc_claim(self):
        result=convert_symbol(self.device,'Q_SCR_AGK')
        pins={p.pin.value:p for p in parse_cds(result.cds).components[0].polylines if p.pin}
        self.assertTrue(all(p.description is None for p in pins.values()))
        self.assertEqual({p['source_pin_number']:p['source_pin_name'] for p in result.report['pin_semantics']['pins']},
                         {'1':'A','2':'G','3':'K'})
        self.assertEqual((pins['2'].corners[1].x,pins['2'].corners[1].y),(-3810000,-2540000))
        self.assertFalse(result.report['pin_semantics']['electrical_rules_transferred'])

    def test_new_official_footprints_have_pinned_unchanged_bytes(self):
        data=json.loads((FIXTURES/'components/electrical-provenance.json').read_text())
        self.assertFalse(data['modified'])
        for record in data['files']:
            source=(FIXTURES/record['file']).read_bytes()
            self.assertEqual(len(source),record['bytes'])
            self.assertEqual(hashlib.sha256(source).hexdigest(),record['sha256'])

    def test_bundle_number_verification_preserves_electrical_loss_and_unverified_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store';fake_models(models)
            out=root/'bundle';manifest=export_bundle(FIXTURES/'components/electrical.json',out,stl_root=models)
            self.assertEqual(manifest['summary']['generated_components'],2)
            self.assertEqual(manifest['summary']['complete_chains'],2)
            self.assertEqual(manifest['summary']['models'],2)
            for entry in manifest['components']:
                report=json.loads((out/entry['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
                self.assertFalse(report['gui_validated'] or report['target_import_verified'])
                self.assertIn('SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED',{d['code'] for d in report['diagnostics'] if d['severity']=='loss'})
            relocated=root/'relocated';shutil.copytree(out,relocated);shutil.rmtree(models);shutil.rmtree(out)
            self.assertEqual(verify_bundle(relocated),manifest)

    def test_strict_bundle_rejects_types_without_publishing_native_components(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'bundle'
            result=export_bundle(FIXTURES/'components/electrical.json',out,strict=True)
            self.assertEqual(result['summary']['generated_components'],0)
            self.assertEqual(result['summary']['models'],0)
            self.assertTrue(all(e['status']=='rejected_loss' for e in result['components']))
            self.assertFalse(list(out.rglob('*.cds')) or list(out.rglob('*.fpl')))
            for entry in result['components']:
                report=json.loads((out/entry['report']).read_text())
                self.assertFalse(report['rejection_report']['pin_semantics']['electrical_rules_transferred'])
            self.assertEqual(verify_bundle(out),result)

    def test_cli_strict_and_unsupported_type_preserve_last_cds(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'electrical.kicad_sym';out=root/'electrical.cds'
            source.write_text(library(symbol(body='(symbol "Base_1_1" '+pin()+')')))
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(source),str(out),'--symbol','Base']
            run=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);before=out.read_bytes()
            run=subprocess.run(cmd+['--strict'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(run.returncode,2,run.stderr)
            self.assertEqual(out.read_bytes(),before)
            report_path=out.with_suffix('.report.json');report_before=report_path.read_bytes()
            report=json.loads(report_before)
            self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
            self.assertEqual(report['status'],'rejected_loss')
            source.write_text(source.read_text().replace('input line','no_connect line'))
            run=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(run.returncode,1,run.stderr)
            self.assertEqual(out.read_bytes(),before)
            self.assertEqual(report_path.read_bytes(),report_before)

    def test_saved_controls_are_reproducible_with_full_semantic_reports(self):
        for name in CONTROLS:
            path=PROJECT/'output/symbols'/(name+'_electrical.cds')
            result=convert_symbol(self.device,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes())
            old=json.loads(path.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(result.report)),
                             {k:v for k,v in old.items() if k not in ('source','output')})


if __name__=='__main__':
    unittest.main()
