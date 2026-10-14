"""Original common records emit once; repeated source records never deduplicate."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.symbol_converter import parse_library, SymbolParseError
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.schemator_format import parse_cds
from src.component_converter import export_bundle, verify_bundle
from test_symbol_multiunit import multi
from test_symbol_electrical import modern

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
POLICY='common-view-with-loss'


def common(kind='passive',hidden=False,shape='line'):
    source=multi();s=source.symbols['Base'];p=deepcopy(s.units[1].pins[0])
    p.number='5';p.name='COMMON';p.at=(0,-5.08,90)
    p.electrical_type=kind;p.hidden=hidden;p.graphic_style=shape;s.units[0].pins.append(p)
    return source


class SymbolCommonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=parse_library((FIXTURES/'symbols/Device.kicad_sym').read_text())

    def test_default_common_policy_remains_a_refusal(self):
        with self.assertRaisesRegex(SymbolParseError,'common pins'):convert_symbol(common(),'Base')

    def test_one_component_one_common_terminal_and_extra_unit_zero_view(self):
        result=convert_symbol(common(),'Base',common_pin_policy=POLICY);report=result.report
        native=parse_cds(result.cds);self.assertEqual(len(native.components),1)
        self.assertEqual(native.components[0].pin_count,5)
        self.assertEqual(result.cds.count('part_end'),1)
        self.assertEqual(sorted(p.pin.value for p in native.components[0].polylines if p.pin),list('12345'))
        self.assertEqual(report['counts']['common_pins'],1)
        self.assertEqual(report['counts']['rendered_views'],3)
        self.assertEqual(report['target']['source_units_profile'],'common-pins-view-v1')
        self.assertEqual([u['source_unit'] for u in report['unit_layout']['units']],[1,2,0])
        self.assertEqual([p['number'] for p in report['unit_layout']['units'][-1]['pins']],['5'])
        self.assertEqual(report['unit_layout']['common_pin_policy'],POLICY)
        self.assertFalse(report['unit_layout']['native_hierarchical_merge_generated'])

    def test_common_graphics_still_repeat_per_logical_view_without_extra_common_body(self):
        result=convert_symbol(common(),'Base',common_pin_policy=POLICY)
        views=result.report['unit_layout']['units']
        self.assertTrue(views[0]['common_graphics_copied'] and views[1]['common_graphics_copied'])
        self.assertEqual(views[2]['common_graphics_copied'],[])
        bodies=[p for p in result.document.components[0].polylines if not p.pin]
        self.assertEqual(len(bodies),2)

    def test_common_translation_number_mapping_and_loss_indices_match_readback(self):
        result=convert_symbol(common(),'Base',common_pin_policy=POLICY,unit_gap=1.27)
        report=result.report;part=parse_cds(result.cds).components[0]
        a,b,c=report['unit_layout']['units']
        self.assertEqual(c['target_bounds_nm'][0]-b['target_bounds_nm'][2],1270000)
        pin=c['pins'][0];p=part.polylines[pin['target_polyline_index']]
        self.assertEqual((p.corners[-1].x,p.corners[-1].y),(c['translation_nm'][0],-5080000))
        self.assertEqual(p.pin.value,'5')
        loss=next(d for d in report['diagnostics'] if d['code']=='SYMBOL_COMMON_PINS_PLACED_ONCE')
        self.assertEqual(loss['severity'],'loss')
        self.assertEqual(loss['context']['target_polyline_indices'],[pin['target_polyline_index']])
        entry=next(p for p in report['pin_semantics']['pins'] if p['source_pin_number']=='5')
        self.assertEqual(entry['rendered_unit'],0)
        self.assertEqual(entry['connection_point_nm'],pin['target_connection_nm'])

    def test_source_raw_common_records_and_original_units_are_immutable(self):
        source=common();before=deepcopy(source)
        result=convert_symbol(source,'Base',common_pin_policy=POLICY)
        self.assertEqual(source,before)
        units=result.report['source_symbol']['units']
        self.assertEqual([u['number'] for u in units],[0,1,2]);self.assertEqual(units[0]['pins'][0]['number'],'5')

    def test_common_overlapping_number_and_cross_unit_repeats_still_reject(self):
        source=common();source.symbols['Base'].units[0].pins[0].number='1'
        with self.assertRaisesRegex(SymbolParseError,'must be disjoint'):convert_symbol(source,'Base',common_pin_policy=POLICY)
        source=multi();source.symbols['Base'].units[2].pins[0].number='1'
        with self.assertRaisesRegex(SymbolParseError,'must be disjoint'):convert_symbol(source,'Base',common_pin_policy=POLICY)

    def test_common_duplicate_records_are_not_reduced_to_one_pin(self):
        source=common();block=source.symbols['Base'].units[0];block.pins.append(deepcopy(block.pins[0]))
        with self.assertRaisesRegex(SymbolParseError,'must be disjoint'):convert_symbol(source,'Base',common_pin_policy=POLICY)

    def test_empty_logical_unit_alternate_body_and_limit_still_reject(self):
        source=common();source.symbols['Base'].units[2].pins.clear()
        with self.assertRaisesRegex(SymbolParseError,'unit 2 has no physical pins'):convert_symbol(source,'Base',common_pin_policy=POLICY)
        source=common();source.symbols['Base'].units[0].style=2
        with self.assertRaisesRegex(SymbolParseError,'body style'):convert_symbol(source,'Base',common_pin_policy=POLICY)
        source=common();source.symbols['Base'].unit_count=17
        with self.assertRaisesRegex(SymbolParseError,'2..16'):convert_symbol(source,'Base',common_pin_policy=POLICY)

    def test_common_hidden_power_requires_reveal_and_keeps_global_net_loss(self):
        source=common('power_in',True)
        with self.assertRaisesRegex(SymbolParseError,'hidden pin requires'):convert_symbol(source,'Base',common_pin_policy=POLICY)
        result=convert_symbol(source,'Base',common_pin_policy=POLICY,hidden_pin_policy='reveal-with-loss')
        report=result.report;self.assertEqual(report['counts']['power_pins'],1)
        entry=next(p for p in report['pin_semantics']['pins'] if p['source_pin_number']=='5')
        self.assertTrue(entry['source_implicit_global_power'])
        self.assertFalse(entry['native_implicit_global_power_transferred'])
        self.assertEqual(entry['rendered_unit'],0)

    def test_common_hidden_NC_retains_both_losses_and_actual_pin_index(self):
        source=common('no_connect',True)
        with self.assertRaisesRegex(SymbolParseError,'no-connect cannot be enforced'):
            convert_symbol(source,'Base',common_pin_policy=POLICY,hidden_pin_policy='reveal-with-loss')
        result=convert_symbol(source,'Base',common_pin_policy=POLICY,hidden_pin_policy='reveal-with-loss',
                              no_connect_policy='connectable-with-loss')
        report=result.report;part=result.document.components[0]
        self.assertEqual(report['counts']['no_connect_pins'],1)
        for d in report['diagnostics']:
            if d['code'] in ('SYMBOL_NO_CONNECT_AS_TERMINAL','SYMBOL_HIDDEN_PIN_REVEALED'):
                self.assertEqual(d['context']['rendered_unit'],0)
                self.assertEqual(part.polylines[d['context']['target_polyline_index']].pin.value,'5')

    def test_common_styled_markers_rebase_to_common_view_and_enter_budget(self):
        result=convert_symbol(common(shape='inverted_clock'),'Base',common_pin_policy=POLICY)
        m=result.report['pin_markers'][0];self.assertEqual((m['unit'],m['rendered_unit']),(0,0))
        self.assertEqual(result.document.components[0].polylines[m['target_pin_polyline_index']].pin.value,'5')
        self.assertEqual(m['target_marker_body_nm'][0]-m['source_body_nm'][0],m['translation_nm'][0])
        with patch('src.symbol_converter.multiunit.MAX_BODY_CORNERS',8):
            with self.assertRaisesRegex(SymbolParseError,'aggregate'):
                convert_symbol(common(shape='inverted_clock'),'Base',common_pin_policy=POLICY)

    def test_strict_retains_full_source_extra_view_policy_and_proposed_hash(self):
        source=common()
        with self.assertRaises(LossySymbolConversionError) as raised:
            convert_symbol(source,'Base',common_pin_policy=POLICY,strict=True)
        report=raised.exception.report;self.assertFalse(report['target_output_generated'])
        self.assertEqual(report['conversion_settings']['common_pin_policy'],POLICY)
        self.assertEqual(len(report['unit_layout']['units']),3)
        self.assertEqual(report['proposed_artifact_sha256'],hashlib.sha256(convert_symbol(source,'Base',common_pin_policy=POLICY).cds.encode('cp1251')).hexdigest())

    def test_unused_policy_is_byte_report_identical_and_invalid_policy_rejects(self):
        for source in (modern(('passive',)),multi()):
            self.assertEqual(convert_symbol(source,'Base'),convert_symbol(source,'Base',common_pin_policy=POLICY))
            for value in ('ignore',None,True,[],{}):
                with self.assertRaisesRegex(SymbolParseError,'Common pin policy'):
                    convert_symbol(source,'Base',common_pin_policy=value)

    def test_real_network_controls_have_every_number_once_and_reproduce(self):
        provenance=json.loads((FIXTURES/'components/common-provenance.json').read_text())
        self.assertFalse(provenance['modified'])
        for record in provenance['files']:
            raw=(FIXTURES/record['file']).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(),len(raw)),(record['sha256'],record['bytes']))
        for name,logical,pins in [('R_Network03_Split',3,4),('R_Network04_Split',4,5),
                                  ('R_Network07_Split',7,8),('R_Network13_Split',13,14)]:
            out=PROJECT/'output/symbols'/(name+'_common.cds')
            result=convert_symbol(self.device,name,common_pin_policy=POLICY,project_name=out.name)
            self.assertEqual(result.cds.encode('cp1251'),out.read_bytes())
            report=result.report;self.assertEqual((report['counts']['source_units'],report['counts']['pins']),(logical,pins))
            self.assertEqual(report['counts']['rendered_views'],logical+1)
            self.assertEqual(report['unit_layout']['common_pin_numbers'],['1'])
            self.assertEqual({p.pin.value for p in result.document.components[0].polylines if p.pin},{str(i) for i in range(1,pins+1)})
            saved=json.loads(out.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(report)),{k:v for k,v in saved.items() if k not in ('source','output')})
        with self.assertRaisesRegex(SymbolParseError,'collapsed segments'):
            convert_symbol(self.device,'D_Dual_CommonAnode_AKK_Split',common_pin_policy=POLICY)

    def test_bundle_source_properties_readback_and_relocation_with_common_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store'
            for n in (4,5,8):
                p=models/'Resistor_THT.3dshapes'/f'R_Array_SIP{n}.stl';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'opaque asset')
            out=root/'bundle';m=export_bundle(FIXTURES/'components/common.json',out,stl_root=models)
            self.assertEqual((m['summary']['complete_chains'],m['summary']['models']),(3,3))
            for e in m['components']:
                self.assertEqual(e['source']['selection'],'source_property')
                report=json.loads((out/e['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['gui_validated'] or report['unit_layout']['native_hierarchical_merge_generated'])
                self.assertEqual(report['unit_layout']['common_pin_numbers'],['1'])
            moved=root/'moved';shutil.move(out,moved);shutil.rmtree(models);self.assertEqual(verify_bundle(moved),m)

    def test_invalid_bundle_policy_prevents_publication(self):
        config=json.loads((FIXTURES/'components/common.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'config.json';out=root/'bundle'
            for value in ('ignore',True,None,[]):
                config['symbol_common_pin_policy']=value;p.write_text(json.dumps(config))
                with self.assertRaisesRegex(SymbolParseError,'Common pin policy'):export_bundle(p,out)
                self.assertFalse(out.exists())

    def test_strict_bundle_keeps_common_layout_without_native_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'bundle';m=export_bundle(FIXTURES/'components/common.json',out,strict=True)
            self.assertEqual(m['summary']['generated_components'],0)
            self.assertFalse(list(out.rglob('*.cds')) or list(out.rglob('*.fpl')))
            for e in m['components']:
                report=json.loads((out/e['report']).read_text())['rejection_report']
                self.assertEqual(report['unit_layout']['common_pin_numbers'],['1'])
            self.assertEqual(verify_bundle(out),m)

    def test_CLI_default_and_strict_preserve_previous_common_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'common.cds'
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(FIXTURES/'symbols/Device.kicad_sym'),
                 str(out),'--symbol','R_Network03_Split']
            def run(extra):return subprocess.run(cmd+extra,cwd=PROJECT,capture_output=True,text=True)
            r=run(['--common-pin-policy',POLICY]);self.assertEqual(r.returncode,0,r.stderr);before=out.read_bytes()
            report_before=out.with_suffix('.report.json').read_bytes();r=run([]);self.assertEqual(r.returncode,1,r.stderr)
            self.assertEqual(out.read_bytes(),before);self.assertEqual(out.with_suffix('.report.json').read_bytes(),report_before)
            r=run(['--common-pin-policy',POLICY,'--strict']);self.assertEqual(r.returncode,2,r.stderr)
            self.assertEqual(out.read_bytes(),before)


if __name__=='__main__':unittest.main()
