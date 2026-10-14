"""Independent marker geometry, hidden/global-net policy and chain regressions."""
from copy import deepcopy
import hashlib
import json
import math
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
from test_symbol_electrical import modern
from test_symbol_multiunit import multi
from test_symbol_converter import legacy

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
SHAPES=('inverted','clock','inverted_clock','input_low','clock_low','output_low','edge_clock_high','non_logic')


def styled(shape='clock',angle=0,kind='input'):
    source=modern((kind,));p=source.symbols['Base'].pins_for()[0]
    p.graphic_style=shape;p.at=(0,0,angle)
    return source


class SymbolPinGraphicsTests(unittest.TestCase):
    def test_all_editor_shapes_have_one_numbered_terminal_and_only_body_decorators(self):
        expected={'inverted':1,'clock':1,'inverted_clock':2,'input_low':1,
                  'clock_low':2,'output_low':1,'edge_clock_high':2,'non_logic':2}
        for shape in SHAPES:
            for angle in (0,90,180,270):
                with self.subTest(shape=shape,angle=angle):
                    result=convert_symbol(styled(shape,angle),'Base');part=parse_cds(result.cds).components[0]
                    self.assertEqual(part.pin_count,1)
                    terminal=next(p for p in part.polylines if p.pin)
                    self.assertEqual((terminal.pin.value,terminal.layer),('1',8))
                    self.assertEqual((terminal.corners[-1].x,terminal.corners[-1].y,terminal.corners[-1].node),(0,0,1))
                    markers=[p for p in part.polylines if not p.pin]
                    self.assertEqual(len(markers),expected[shape])
                    self.assertTrue(all(p.layer==6 and all(c.node==0 for c in p.corners) for p in markers))
                    self.assertFalse(result.report['pin_markers'][0]['electrical_style_transferred'])

    def test_clock_triangle_uses_editor_one_radius_depth_and_preserves_source_body(self):
        result=convert_symbol(styled(),'Base');terminal,clock=result.document.components[0].polylines
        self.assertEqual([(c.x,c.y) for c in clock.corners],[(2540000,635000),(3175000,0),(2540000,-635000)])
        self.assertEqual((terminal.corners[0].x,terminal.corners[0].y),(2540000,0))

    def test_inversion_bubble_shortens_only_internal_segment_not_external_endpoint(self):
        result=convert_symbol(styled('inverted'),'Base');terminal,bubble=result.document.components[0].polylines
        self.assertEqual((terminal.corners[0].x,terminal.corners[0].y),(1270000,0))
        self.assertEqual((terminal.corners[1].x,terminal.corners[1].y),(0,0))
        meta=result.report['pin_markers'][0]
        self.assertEqual(meta['center_mm'],(1.905,0));self.assertEqual(meta['radius_mm'],.635)
        self.assertTrue(bubble.closed)
        for a,b in zip(bubble.corners,bubble.corners[1:]+bubble.corners[:1]):
            mid=((a.x+b.x)/2/1e6,(a.y+b.y)/2/1e6)
            self.assertLessEqual(.635-math.dist(mid,(1.905,0)),.010001)

    def test_low_input_markers_follow_literal_editor_coordinates_in_Y_up(self):
        expected={0:[(1270000,0),(1270000,1270000),(2540000,0)],
                  90:[(0,1270000),(-1270000,1270000),(0,2540000)],
                  180:[(-1270000,0),(-1270000,1270000),(-2540000,0)],
                  270:[(0,-1270000),(-1270000,-1270000),(0,-2540000)]}
        for angle,points in expected.items():
            marker=convert_symbol(styled('input_low',angle),'Base').document.components[0].polylines[1]
            self.assertEqual([(c.x,c.y) for c in marker.corners],points)

    def test_zero_name_size_uses_number_height_for_clock_when_names_hidden(self):
        source=styled();s=source.symbols['Base'];s.pin_names_hidden=True;s.pins_for()[0].name_size=(0,0)
        self.assertEqual(convert_symbol(source,'Base').report['pin_markers'][0]['internal_radius_nm'],635000)

    def test_marker_size_short_length_and_native_overflow_reject(self):
        source=styled('inverted');source.symbols['Base'].pins_for()[0].length=1.27
        with self.assertRaisesRegex(SymbolParseError,'too short'):convert_symbol(source,'Base')
        source=styled();source.symbols['Base'].pins_for()[0].number_size=(.00001,.00001)
        with self.assertRaisesRegex(SymbolParseError,'collapses'):convert_symbol(source,'Base')
        source=styled();source.symbols['Base'].pins_for()[0].at=(2145,0,0)
        with self.assertRaisesRegex(SymbolParseError,'native integer'):convert_symbol(source,'Base')

    def test_marker_corners_count_toward_aggregate_body_budget(self):
        with patch('src.symbol_converter.target.MAX_BODY_CORNERS',2):
            with self.assertRaisesRegex(SymbolParseError,'including pin markers'):convert_symbol(styled(),'Base')
        with patch('src.symbol_converter.multiunit.MAX_BODY_CORNERS',6):
            source=multi();source.symbols['Base'].units[2].pins[0].graphic_style='clock'
            with self.assertRaisesRegex(SymbolParseError,'aggregate'):convert_symbol(source,'Base')

    def test_legacy_marker_codes_use_the_same_editor_geometry(self):
        for code,shape in [('I','inverted'),('C','clock'),('CI','inverted_clock'),('L','input_low'),
                           ('CL','clock_low'),('V','output_low'),('F','edge_clock_high'),('X','non_logic')]:
            source=parse_library(legacy('X IN 1 0 0 100 R 50 50 1 1 I '+code))
            actual=convert_symbol(source,'Test');modern_result=convert_symbol(styled(shape),'Base')
            self.assertEqual([p.corners for p in actual.document.components[0].polylines],
                             [p.corners for p in modern_result.document.components[0].polylines])

    def test_unknown_shapes_alternates_and_styled_NC_remain_rejected(self):
        with self.assertRaisesRegex(SymbolParseError,'unsupported graphic style'):convert_symbol(styled('future'),'Base')
        source=styled();source.symbols['Base'].pins_for()[0].alternates=[dict(name='ALT')]
        with self.assertRaisesRegex(SymbolParseError,'alternate pin modes'):convert_symbol(source,'Base')
        with self.assertRaisesRegex(SymbolParseError,'Styled NC'):
            convert_symbol(styled('clock',kind='no_connect'),'Base',no_connect_policy='connectable-with-loss')

    def test_hidden_default_refuses_and_reveal_keeps_every_physical_number(self):
        source=modern(('passive','power_in','no_connect'));pins=source.symbols['Base'].pins_for()
        for p in pins:p.hidden=True
        with self.assertRaisesRegex(SymbolParseError,'hidden pin requires'):convert_symbol(source,'Base')
        result=convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss',no_connect_policy='connectable-with-loss')
        report=result.report;self.assertEqual(report['counts']['hidden_pins'],3)
        self.assertEqual([p.pin.value for p in result.document.components[0].polylines],['1','2','3'])
        self.assertEqual([p['source_implicit_global_power'] for p in report['pin_semantics']['pins']],[False,True,False])
        self.assertFalse(report['pin_semantics']['implicit_global_power_transferred'])
        losses=[d for d in report['diagnostics'] if d['code']=='SYMBOL_HIDDEN_PIN_REVEALED']
        self.assertEqual([d['context']['pin_number'] for d in losses],['1','2','3'])

    def test_hidden_NC_requires_both_explicit_policies(self):
        source=modern(('no_connect',));source.symbols['Base'].pins_for()[0].hidden=True
        with self.assertRaisesRegex(SymbolParseError,'no-connect cannot be enforced'):
            convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss')

    def test_legacy_hidden_power_loses_implicit_global_name_connection(self):
        source=parse_library(legacy('X VCC 1 0 0 100 R 50 50 1 1 W N'))
        result=convert_symbol(source,'Test',hidden_pin_policy='reveal-with-loss')
        entry=result.report['pin_semantics']['pins'][0]
        self.assertTrue(entry['source_implicit_global_power'])
        self.assertFalse(entry['native_implicit_global_power_transferred'])
        self.assertEqual(result.document.components[0].polylines[0].description.value,'VCC')

    def test_hidden_stacked_points_are_not_separated_or_deduplicated(self):
        source=modern(('power_in','power_in'));a,b=source.symbols['Base'].pins_for()
        a.hidden=b.hidden=True;b.at=a.at
        with self.assertRaisesRegex(SymbolParseError,'share a connection terminal'):
            convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss')

    def test_source_raw_and_typed_markers_hidden_flags_are_immutable(self):
        source=styled('inverted_clock');source.symbols['Base'].pins_for()[0].hidden=True;before=deepcopy(source)
        result=convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss')
        self.assertEqual(source,before)
        self.assertEqual(result.report['source_symbol']['units'][0]['pins'][0]['graphic_style'],'inverted_clock')

    def test_strict_markers_and_hidden_keep_semantics_without_artifact(self):
        source=styled('inverted_clock');source.symbols['Base'].pins_for()[0].hidden=True
        with self.assertRaises(LossySymbolConversionError) as raised:
            convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss',strict=True)
        report=raised.exception.report
        self.assertFalse(report['target_output_generated'] or report['gui_validated'])
        self.assertTrue(report['pin_semantics']['pins'][0]['source_hidden'])
        self.assertNotIn('artifact_sha256',report)
        self.assertEqual(report['counts']['approximations'],1)

    def test_compound_markers_and_hidden_diagnostics_rebase_global_indices_and_points(self):
        source=multi();p=source.symbols['Base'].units[2].pins[0];p.graphic_style='inverted_clock';p.hidden=True
        result=convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss');report=result.report
        part=parse_cds(result.cds).components[0];marker=report['pin_markers'][0]
        self.assertEqual(marker['rendered_unit'],2)
        self.assertEqual(part.polylines[marker['target_pin_polyline_index']].pin.value,'3')
        self.assertEqual(marker['target_marker_body_nm'][0]-marker['source_body_nm'][0],marker['translation_nm'][0])
        self.assertTrue(all(not part.polylines[i].pin for i in marker['target_polyline_indices']))
        entry=next(p for p in report['pin_semantics']['pins'] if p['source_pin_number']=='3')
        self.assertTrue(entry['source_hidden']);self.assertEqual(entry['source_graphic_style'],'inverted_clock')
        for diagnostic in report['diagnostics']:
            context=diagnostic['context']
            if diagnostic['code']=='SYMBOL_HIDDEN_PIN_REVEALED':
                self.assertEqual(part.polylines[context['target_polyline_index']].pin.value,'3')
            if diagnostic['code']=='SYMBOL_PIN_MARKER_GRAPHICS':
                self.assertEqual(context['target_pin_polyline_index'],marker['target_pin_polyline_index'])

    def test_unused_and_invalid_hidden_policy_keep_old_reports_or_reject_early(self):
        source=modern(('passive',))
        self.assertEqual(convert_symbol(source,'Base'),convert_symbol(source,'Base',hidden_pin_policy='reveal-with-loss'))
        for value in ('ignore',True,None,[],{}):
            with self.assertRaisesRegex(SymbolParseError,'Hidden pin policy'):
                convert_symbol(source,'Base',hidden_pin_policy=value)

    def test_real_controls_reproduce_reports_bytes_and_preserve_unsupported_source(self):
        provenance=json.loads((FIXTURES/'components/pins-provenance.json').read_text())
        self.assertFalse(provenance['modified'])
        for record in provenance['files']:
            raw=(FIXTURES/record['file']).read_bytes()
            self.assertEqual((hashlib.sha256(raw).hexdigest(),len(raw)),(record['sha256'],record['bytes']))
        for name in ('SW_PUSH','74LVC1G125','74LVC1G79','74LVC2G79','MIC845H','AVR-PDI-6'):
            out=PROJECT/'output/symbols'/(name+'_pins.cds');saved=json.loads(out.with_suffix('.report.json').read_text())
            filename=Path(saved['source']['path']).name
            source=PROJECT/'KiCad'/filename if filename.endswith('.lib') else FIXTURES/'symbols'/filename
            settings=saved['conversion_settings'];lib=parse_library(source.read_text())
            result=convert_symbol(lib,name,project_name=out.name,hidden_pin_policy=settings.get('hidden_pin_policy','reject'),
                no_connect_policy=settings.get('no_connect_policy','reject'))
            self.assertEqual(out.read_bytes(),result.cds.encode('cp1251'))
            self.assertEqual({k:v for k,v in saved.items() if k not in ('source','output')},json.loads(json.dumps(result.report)))
        lib=parse_library((FIXTURES/'symbols/74xGxx.kicad_sym').read_text())
        with self.assertRaisesRegex(SymbolParseError,'markup'):convert_symbol(lib,'74LVC1G80')

    def test_bundle_relocation_number_identity_does_not_transfer_global_or_style_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store'
            for category,name in [('Package_TO_SOT_SMD','SOT-23-5'),('Package_DIP','DIP-8_W7.62mm'),
                                  ('Connector_PinHeader_2.54mm','PinHeader_1x06_P2.54mm_Vertical')]:
                p=models/(category+'.3dshapes')/(name+'.stl');p.parent.mkdir(parents=True);p.write_bytes(b'opaque asset')
            out=root/'bundle';manifest=export_bundle(FIXTURES/'components/pins.json',out,stl_root=models)
            self.assertEqual((manifest['summary']['complete_chains'],manifest['summary']['models']),(5,3))
            for e in manifest['components']:
                report=json.loads((out/e['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['pin_semantics']['implicit_global_power_transferred'] or report['gui_validated'])
            moved=root/'moved';shutil.move(out,moved);shutil.rmtree(models)
            self.assertEqual(verify_bundle(moved),manifest)

    def test_invalid_bundle_hidden_policy_prevents_publication(self):
        config=json.loads((FIXTURES/'components/pins.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'config.json';out=root/'bundle'
            for value in ('ignore',True,None,[]):
                config['symbol_hidden_pin_policy']=value;p.write_text(json.dumps(config))
                with self.assertRaisesRegex(SymbolParseError,'Hidden pin policy'):export_bundle(p,out)
                self.assertFalse(out.exists())

    def test_CLI_hidden_policy_strict_and_default_preserve_last_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'pins.cds'
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(FIXTURES/'symbols/Comparator.kicad_sym'),
                str(out),'--symbol','MIC845H','--no-connect-policy','connectable-with-loss']
            def run(extra):return subprocess.run(cmd+extra,cwd=PROJECT,capture_output=True,text=True)
            r=run(['--hidden-pin-policy','reveal-with-loss']);self.assertEqual(r.returncode,0,r.stderr);before=out.read_bytes()
            report_before=out.with_suffix('.report.json').read_bytes();r=run([]);self.assertEqual(r.returncode,1,r.stderr)
            self.assertEqual(out.read_bytes(),before);self.assertEqual(out.with_suffix('.report.json').read_bytes(),report_before)
            r=run(['--hidden-pin-policy','reveal-with-loss','--strict']);self.assertEqual(r.returncode,2,r.stderr)
            self.assertEqual(out.read_bytes(),before)


if __name__=='__main__':unittest.main()
