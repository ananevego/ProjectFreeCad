"""Disjoint units preserve physical identity under explicit compound placement."""
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
from test_symbol_converter import library, symbol, pin, legacy

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
CONTROLS=('R_Pack02_Split','R_Pack03_Split','R_Pack04_Split','R_Pack02_SIP_Split',
          'R_Potentiometer_Dual_Separate')
RECT='(rectangle (start -1 -1) (end 1 1) (stroke (width 0.1) (type default)) (fill (type none)))'


def multi(extra1='',extra2='',type2='passive'):
    common='(symbol "Base_0_1" '+RECT+')'
    one=(pin('1',name='ONE')+pin('2',name='TWO',at='5.08 0 180')).replace('input line','passive line')
    two=pin('3',name='THREE')+pin('4',name='FOUR',at='5.08 0 180')
    two=two.replace('input line',type2+' line')
    return parse_library(library(symbol(body=common+'(symbol "Base_1_1" '+one+extra1+')'+
                                       '(symbol "Base_2_1" '+two+extra2+')')))


class SymbolMultiUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=parse_library((FIXTURES/'symbols/Device.kicad_sym').read_text())

    def test_literal_compound_pin_coordinates_preserve_one_physical_component(self):
        result=convert_symbol(multi(),'Base');native=parse_cds(result.cds)
        self.assertEqual(len(native.components),1)
        self.assertEqual(result.cds.count('part_end'),1)
        self.assertEqual(result.cds.count('ref_des:'),1)
        part=native.components[0];self.assertEqual(part.pin_count,4)
        pins={p.pin.value:p for p in part.polylines if p.pin}
        # Single-view x bounds include stroke/selection margin: +/-5.2324mm.
        # dx = 5.2324 + 2.54 - (-5.2324) = 13.0048mm.
        expected={'1':(-5080000,-2540000),'2':(5080000,2540000),
                  '3':(7924800,10464800),'4':(18084800,15544800)}
        for number,(external,body) in expected.items():
            self.assertEqual([(c.x,c.y,c.node) for c in pins[number].corners],[(body,0,0),(external,0,1)])
        self.assertEqual(part.reference.value,'U1')

    def test_hierarchy_and_independent_unit_semantics_are_explicitly_lost(self):
        result=convert_symbol(multi(),'Base');report=result.report
        self.assertEqual(report['target']['source_units_profile'],'disjoint-units-layout-v1')
        self.assertFalse(report['unit_layout']['independent_unit_placement_transferred'])
        self.assertFalse(report['unit_layout']['native_hierarchical_merge_generated'])
        self.assertTrue(all((p.merge,p.submerge,p.source,p.source_invert)==(-1,-1,-1,0)
                            for p in result.document.components[0].polylines))
        loss=next(d for d in report['diagnostics'] if d['code']=='SYMBOL_UNITS_FLATTENED')
        self.assertEqual(loss['severity'],'loss')
        self.assertNotIn('BLK',result.cds)
        self.assertNotIn('[merges]',result.cds)
        self.assertFalse(report['physical_pin_mapping_verified'] or report['gui_validated'] or report['target_import_verified'])

    def test_declared_unit_gap_and_view_bounds_have_exact_integer_NM_separation(self):
        for gap in (1.27,2.54,.1234567):
            result=convert_symbol(multi(),'Base',unit_gap=gap)
            a,b=result.report['unit_layout']['units']
            self.assertEqual(a['translation_nm'],(0,0))
            self.assertEqual(b['target_bounds_nm'][0]-a['target_bounds_nm'][2],round(gap*1e6))
            dx=b['translation_nm'][0]
            for i,value in enumerate(b['source_view_bounds_nm']):
                self.assertEqual(b['target_bounds_nm'][i],value+(dx if i in (0,2) else 0))

    def test_source_symbol_units_raw_and_inheritance_are_not_mutated(self):
        source=multi();before=deepcopy(source)
        result=convert_symbol(source,'Base')
        self.assertEqual(source,before)
        self.assertEqual(result.report['source_symbol']['unit_count'],2)
        self.assertEqual([u['number'] for u in result.report['source_symbol']['units']],[0,1,2])
        raw=library(symbol(body='(symbol "Base_0_1" '+RECT+')'+
            '(symbol "Base_1_1" '+pin('1')+')'+'(symbol "Base_2_1" '+pin('2')+')'),
            symbol('Derived',extends='Base'))
        inherited=parse_library(raw);before=deepcopy(inherited)
        result=convert_symbol(inherited,'Derived')
        self.assertEqual(inherited,before)
        self.assertEqual(result.report['source_symbol']['inheritance_chain'],['Base'])
        self.assertEqual(result.document.components[0].value.value,'Derived')

    def test_common_graphics_are_copied_once_per_view_with_source_unit_zero(self):
        result=convert_symbol(multi(),'Base');part=result.document.components[0]
        bodies=[p for p in part.polylines if not p.pin]
        self.assertEqual(len(bodies),2)
        self.assertTrue(all(p.closed for p in bodies))
        for view in result.report['unit_layout']['units']:
            self.assertEqual(view['common_graphics_copied'],
                [dict(source_unit=0,style=1,source_id='Base_0_1',count=1)])
            self.assertEqual(len(view['target_polyline_indices']),3)

    def test_common_pins_are_rejected_without_automatic_deduplication(self):
        with self.assertRaisesRegex(SymbolParseError,'common pins'):
            convert_symbol(self.device,'R_Network03_Split')
        source=multi();common=source.symbols['Base'].units[0]
        common.pins.append(deepcopy(source.symbols['Base'].units[1].pins[0]));common.pins[0].number='5'
        with self.assertRaisesRegex(SymbolParseError,'common pins'):convert_symbol(source,'Base')

    def test_cross_unit_number_repeats_reject_even_when_source_views_are_individually_valid(self):
        source=multi();source.symbols['Base'].units[2].pins[0].number='1'
        self.assertFalse(source.symbols['Base'].diagnostics)
        with self.assertRaisesRegex(SymbolParseError,'must be disjoint'):
            convert_symbol(source,'Base')

    def test_missing_unit_pins_limits_and_body_styles_reject_before_output(self):
        source=multi();source.symbols['Base'].units[2].pins.clear()
        with self.assertRaisesRegex(SymbolParseError,'unit 2 has no physical pins'):convert_symbol(source,'Base')
        source=multi();source.symbols['Base'].unit_count=17
        with self.assertRaisesRegex(SymbolParseError,'2..16'):convert_symbol(source,'Base')
        source=multi();source.symbols['Base'].units[2].style=2
        with self.assertRaisesRegex(SymbolParseError,'body style'):convert_symbol(source,'Base')

    def test_invalid_unit_gap_is_rejected_even_for_single_unit(self):
        for value in (0,-1,.0000001,101,float('nan'),float('inf'),True,'2.54'):
            for source,name in [(multi(),'Base'),(self.device,'R')]:
                with self.subTest(value=value,name=name),self.assertRaisesRegex(SymbolParseError,'Unit gap'):
                    convert_symbol(source,name,unit_gap=value)

    def test_aggregate_body_budgets_apply_across_individually_valid_views(self):
        with patch('src.symbol_converter.multiunit.MAX_BODY_CORNERS',6):
            with self.assertRaisesRegex(SymbolParseError,'aggregate'):convert_symbol(multi(),'Base')
        filled=RECT.replace('type none','type outline')
        with patch('src.symbol_converter.multiunit.MAX_SYMBOL_FILL_STROKES',50):
            with self.assertRaisesRegex(SymbolParseError,'aggregate'):
                convert_symbol(multi(filled,filled),'Base')

    def test_native_range_overflow_rejects_compound_without_silently_reducing_gap(self):
        source=multi();s=source.symbols['Base']
        s.units=[u for u in s.units if u.number!=0]
        for unit in s.units:
            for p in unit.pins:p.at=(p.at[0]+2140,p.at[1],p.at[2])
        with self.assertRaisesRegex(SymbolParseError,'native integer'):
            convert_symbol(source,'Base',unit_gap=10)

    def test_curves_fill_and_text_indices_and_frames_follow_each_native_translation(self):
        circle='(circle (center 0 0) (radius 1) (stroke (width 0.1) (type default)) (fill (type none)))'
        txt='(text "A" (at 0 0 90) (effects (font (size 1 1))))'
        filled=RECT.replace('type none','type outline')
        result=convert_symbol(multi(circle+txt,circle+filled+txt),'Base',unit_gap=.1234567)
        doc=parse_cds(result.cds).components[0]
        by_unit={u['source_unit']:u for u in result.report['unit_layout']['units']}
        self.assertEqual(len(result.report['curves']),2)
        for curve in result.report['curves']:
            u=by_unit[curve['rendered_unit']];dx=u['translation_nm'][0]
            self.assertEqual(curve['source_center_mm'],(0,0))
            self.assertEqual(curve['center_mm'],(dx/1e6,0))
            first=doc.polylines[curve['target_polyline_index']].corners[0]
            self.assertEqual((first.x,first.y),(1000000+dx,0))
        for text in result.report['graphic_texts']:
            native=doc.polylines[text['target_polyline_index']].description
            self.assertEqual((native.x,native.y),text['native_anchor_nm'])
            self.assertEqual(text['source_anchor_mm'],(0,0))
            self.assertEqual(native.angle,270)
        fill=result.report['filled_graphics'][0]
        self.assertEqual(fill['rendered_unit'],2)
        self.assertTrue(all(i in by_unit[2]['target_polyline_indices'] for i in fill['target_polyline_indices']))

    def test_mixed_electrical_profile_covers_passive_and_active_units_without_ERC_claim(self):
        result=convert_symbol(multi(type2='output'),'Base');report=result.report
        entries=report['pin_semantics']['pins']
        self.assertEqual([e['source_electrical_type'] for e in entries],['passive','passive','output','output'])
        self.assertFalse(report['pin_semantics']['electrical_rules_transferred'])
        for entry in entries:
            poly=result.document.components[0].polylines[entry['target_polyline_index']]
            self.assertEqual(poly.pin.value,entry['target_pin_number'])
            self.assertEqual((poly.corners[-1].x,poly.corners[-1].y),entry['connection_point_nm'])
        loss=next(d for d in report['diagnostics'] if d['code']=='SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED')
        self.assertEqual(loss['context']['source_electrical_types'],{'passive':2,'output':2})

    def test_diagnostic_counts_and_record_indices_match_aggregate_metadata(self):
        filled=RECT.replace('type none','type outline')
        result=convert_symbol(multi(filled,filled),'Base');report=result.report
        for key,severity in [('losses','loss'),('assumptions','assumption'),('approximations','approximation')]:
            self.assertEqual(report['counts'][key],sum(d['severity']==severity for d in report['diagnostics']))
        self.assertEqual(sum(d['code']=='SYMBOL_TEXT_RENDERING' for d in report['diagnostics']),1)
        contexts=[d['context'] for d in report['diagnostics'] if d['code']=='SYMBOL_FILL_APPROXIMATED']
        self.assertEqual([d['rendered_unit'] for d in contexts],[1,2])
        self.assertEqual([d['target_polyline_indices'] for d in contexts],
                         [m['target_polyline_indices'] for m in report['filled_graphics']])

    def test_strict_retains_full_original_units_layout_and_proposed_hash(self):
        with self.assertRaises(LossySymbolConversionError) as raised:convert_symbol(multi(),'Base',strict=True)
        report=raised.exception.report
        self.assertFalse(report['target_output_generated'])
        self.assertEqual(report['source_symbol']['unit_count'],2)
        self.assertEqual(len(report['unit_layout']['units']),2)
        self.assertEqual(report['proposed_artifact_sha256'],hashlib.sha256(convert_symbol(multi(),'Base').cds.encode('cp1251')).hexdigest())
        self.assertNotIn('artifact_sha256',report)

    def test_legacy_DEF_units_and_alias_preserve_pin_identity(self):
        src=legacy('S -100 -100 100 100 0 1 10 N\nX A 1 -200 0 100 R 40 50 1 1 I\nX B 2 -200 0 100 R 40 50 2 1 O',extra='ALIAS Alias',units=2)
        source=parse_library(src);before=deepcopy(source)
        result=convert_symbol(source,'Alias')
        self.assertEqual(source,before)
        self.assertEqual(result.report['source_symbol']['alias_of'],'Test')
        self.assertEqual(result.document.components[0].value.value,'Alias')
        self.assertEqual([p.pin.value for p in result.document.components[0].polylines if p.pin],['1','2'])

    def test_real_resistor_arrays_have_exact_disjoint_unit_pin_sets(self):
        for name,expected in [('R_Pack02_Split',[['4','1'],['3','2']]),
                              ('R_Pack04_Split',[['8','1'],['7','2'],['6','3'],['5','4']]),
                              ('R_Pack02_SIP_Split',[['2','1'],['4','3']])]:
            result=convert_symbol(self.device,name)
            self.assertEqual([[p['number'] for p in u['pins']] for u in result.report['unit_layout']['units']],expected)
            self.assertEqual(result.document.components[0].pin_count,sum(map(len,expected)))
            self.assertEqual(result.document.components[0].reference.value,'RN1')
        result=convert_symbol(self.device,'R_Potentiometer_Dual_Separate')
        self.assertEqual((result.report['counts']['source_units'],result.report['counts']['pins']),(2,6))
        self.assertEqual(len(result.report['filled_graphics']),2)

    def test_power_and_common_real_units_reject_instead_of_partial_conversion(self):
        comparator=parse_library((FIXTURES/'symbols/Comparator.kicad_sym').read_text())
        with self.assertRaisesRegex(SymbolParseError,'unsupported electrical type'):convert_symbol(comparator,'LM393')
        with self.assertRaisesRegex(SymbolParseError,'common pins'):convert_symbol(self.device,'D_Dual_CommonAnode_AKK_Split')

    def test_saved_multiunit_controls_and_pinned_footprints_are_reproducible(self):
        provenance=json.loads((FIXTURES/'components/units-provenance.json').read_text())
        for record in provenance['files']:
            data=(FIXTURES/record['file']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
            self.assertEqual(len(data),record['bytes'])
        for name in CONTROLS:
            path=PROJECT/'output/symbols'/(name+'_units.cds')
            result=convert_symbol(self.device,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes())
            old=json.loads(path.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(result.report)),{k:v for k,v in old.items() if k not in ('source','output')})

    def test_all_previous_single_unit_controls_keep_native_and_report_bytes(self):
        cache=parse_library((PROJECT/'KiCad/Pickit-cache.lib').read_text())
        connector=parse_library((FIXTURES/'symbols/Connector.kicad_sym').read_text())
        libs=[cache,self.device,connector]
        for path in (PROJECT/'output/symbols').glob('*.cds'):
            if path.name.endswith('_units.cds'):continue
            old=json.loads(path.with_suffix('.report.json').read_text());name=old['source_symbol']['name']
            lib=next(lib for lib in libs if lib.source_format==old['source_format'] and (name in lib.symbols or name in lib.aliases))
            result=convert_symbol(lib,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes(),path.name)
            self.assertEqual(json.loads(json.dumps(result.report)),{k:v for k,v in old.items() if k not in ('source','output')},path.name)

    def test_unit_bundle_links_each_package_to_one_physical_component_and_relocates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store'
            for category,name in [('Resistor_SMD','R_Array_Concave_2x0603'),('Resistor_SMD','R_Array_Concave_4x0603'),('Resistor_THT','R_Array_SIP4')]:
                path=models/(category+'.3dshapes')/(name+'.stl');path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(('opaque selected '+name).encode())
            out=root/'bundle';manifest=export_bundle(FIXTURES/'components/units.json',out,stl_root=models)
            self.assertEqual(manifest['summary']['complete_chains'],3)
            self.assertEqual(manifest['summary']['generated_components'],3)
            self.assertEqual(manifest['settings']['symbol_unit_gap_mm'],2.54)
            for entry in manifest['components']:
                report=json.loads((out/entry['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['unit_layout']['native_hierarchical_merge_generated'])
                self.assertFalse(report['gui_validated'] or report['target_import_verified'])
                self.assertEqual(parse_cds((out/entry['symbol']).read_text(encoding='cp1251')).components[0].pin_count,
                                 len(entry['pin_mapping']['source_numbers']))
                if entry['id']=='SIP4':self.assertEqual(entry['source']['selection'],'source_property')
            moved=root/'moved';shutil.copytree(out,moved);shutil.rmtree(out);shutil.rmtree(models)
            self.assertEqual(verify_bundle(moved),manifest)

    def test_strict_bundle_has_no_native_outputs_and_keeps_unit_rejection_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'bundle';manifest=export_bundle(FIXTURES/'components/units.json',out,strict=True)
            self.assertEqual(manifest['summary']['generated_components'],0)
            self.assertFalse(list(out.rglob('*.cds')) or list(out.rglob('*.fpl')))
            for entry in manifest['components']:
                report=json.loads((out/entry['report']).read_text())['rejection_report']
                self.assertFalse(report['target_output_generated'])
                self.assertFalse(report['unit_layout']['independent_unit_placement_transferred'])
            self.assertEqual(verify_bundle(out),manifest)

    def test_invalid_bundle_gap_prevents_publication(self):
        config=json.loads((FIXTURES/'components/units.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';out=Path(directory)/'bundle'
            for value in (0,-1,101,True):
                config['symbol_unit_gap']=value;path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):export_bundle(path,out)
                self.assertFalse(out.exists())

    def test_cli_unit_gap_strict_and_common_pin_error_preserve_last_cds(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'units.cds'
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(FIXTURES/'symbols/Device.kicad_sym'),str(out),'--symbol','R_Pack02_Split','--unit-gap','1.27']
            result=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);before=out.read_bytes()
            report=json.loads(out.with_suffix('.report.json').read_text())
            self.assertEqual(report['conversion_settings']['unit_gap_mm'],1.27)
            result=subprocess.run(cmd+['--strict'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr);self.assertEqual(out.read_bytes(),before)
            report_before=out.with_suffix('.report.json').read_bytes()
            result=subprocess.run(cmd+['--symbol','R_Network03_Split'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertEqual(out.read_bytes(),before)
            self.assertEqual(out.with_suffix('.report.json').read_bytes(),report_before)


if __name__=='__main__':unittest.main()
