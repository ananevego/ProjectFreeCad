"""Independent source controls: official symbols, legacy cache and bad inputs."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.symbol_converter import SymbolParseError, parse_library
from src.symbol_converter.reporting import inspection_report

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / 'tests/fixtures/symbols'


def prop(name, value):
    return f'(property "{name}" "{value}" (at 0 0 0) (effects (font (size 1.27 1.27))))'


def pin(number='1', name='IN', at='-5.08 0 0', extra=''):
    return (f'(pin input line (at {at}) (length 2.54) '
            f'(name "{name}" (effects (font (size 1.27 1.27)))) '
            f'(number "{number}" (effects (font (size 1.27 1.27)))) {extra})')


def symbol(name='Base', body='', *, extends=None, value=None):
    properties = prop('Value', value or name)
    if extends is None:
        properties += ''.join(prop(k, v) for k,v in [('Reference','U'),('Footprint',''),('Datasheet','')])
    return f'(symbol "{name}" ' + (f'(extends "{extends}") ' if extends is not None else '') + properties + body + ')'


def library(*symbols, version='20241209', extra=''):
    return f'(kicad_symbol_lib (version {version}) (generator "test") {extra}' + ''.join(symbols) + ')'


def legacy(draw='X IN 1 -200 0 100 R 40 50 1 1 I', fields='', extra='', units=1):
    return (f'EESchema-LIBRARY Version 2.4\nDEF Test U 0 40 Y Y {units} F N\n'
            'F0 "U" 0 100 50 H V C CNN\nF1 "Test" 0 -100 50 H V C CNN\n'
            f'{fields}\n{extra}\nDRAW\n{draw}\nENDDRAW\nENDDEF\n#End Library\n')


class SymbolSourceTests(unittest.TestCase):
    def test_official_files_unchanged(self):
        provenance=json.loads((FIXTURES/'provenance.json').read_text())
        for record in provenance['files']:
            data=(FIXTURES/record['file']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
            self.assertEqual(len(data),record['bytes'])

    def test_official_mechanical_library(self):
        lib=parse_library((FIXTURES/'Mechanical.kicad_sym').read_text())
        report=inspection_report(lib)
        self.assertEqual(report['summary']['library_symbol_count'],11)
        self.assertEqual(report['summary']['pin_record_count'],9)
        self.assertEqual(report['summary']['source_ready_count'],11)
        hole=lib.get_symbol('MountingHole_Pad').pins_for()[0]
        self.assertEqual(hole.number,'1')
        self.assertEqual(hole.electrical_type,'input')

    def test_official_multiunit_and_inheritance(self):
        lib=parse_library((FIXTURES/'Comparator.kicad_sym').read_text())
        self.assertEqual(len(lib.symbols),61)
        self.assertFalse(inspection_report(lib)['summary']['diagnostic_occurrences'])
        base,derived=lib.get_symbol('LM2903'),lib.get_symbol('LM393')
        self.assertEqual(derived.extends,'LM2903')
        self.assertEqual(derived.inheritance_chain,['LM2903'])
        self.assertEqual(derived.unit_count,3)
        self.assertEqual({p.number for p in derived.pins_for(1)}, {'1','2','3'})
        self.assertEqual({p.number for p in derived.pins_for(2)}, {'5','6','7'})
        self.assertEqual({p.number for p in derived.pins_for(3)}, {'4','8'})
        self.assertEqual(derived.properties['Value'].value,'LM393')
        self.assertEqual(base.properties['Value'].value,'LM2903')
        self.assertEqual(base.units,derived.units)
        self.assertIsNot(base.units,derived.units)
        self.assertEqual(lib.get_symbol('LM339').unit_count,5)

    def test_real_legacy_cache_and_duplicates(self):
        lib=parse_library((PROJECT/'KiCad/Pickit-cache.lib').read_text())
        report=inspection_report(lib)
        self.assertEqual(len(lib.symbols),27)
        self.assertEqual(report['summary']['pin_record_count'],268)
        self.assertEqual(report['summary']['source_ready_count'],26)
        alias=lib.get_symbol('+3.3V')
        self.assertEqual(alias.alias_of,'+3V3')
        self.assertEqual(alias.properties['Value'].value,'+3.3V')
        self.assertEqual(lib.get_symbol('+3V3').properties['Value'].value,'+3V3')
        pic=lib.get_symbol('PIC24FJ256GB106')
        self.assertEqual(len(pic.pins_for()),176)
        self.assertEqual(len({p.number for p in pic.pins_for()}),64)
        self.assertEqual({d.pin_number for d in pic.diagnostics},{str(n) for n in range(1,17)})
        self.assertTrue(all(d.code=='SOURCE_PIN_DUPLICATE' for d in pic.diagnostics))
        self.assertFalse(pic.source_ready)

    def test_legacy_resistor_geometry_and_units(self):
        s=parse_library((PROJECT/'KiCad/Pickit-cache.lib').read_text()).get_symbol('R')
        pins={p.number:p for p in s.pins_for()}
        self.assertEqual(pins['1'].at,(0,3.81,270))
        self.assertEqual(pins['2'].at,(0,-3.81,90))
        self.assertEqual(pins['1'].length,1.27)
        self.assertEqual(s.properties['Reference'].value,'R')
        self.assertIn('Resistor_*',s.properties['ki_fp_filters'].value)
        rectangle=next(g for u in s.units for g in u.graphics if g.kind=='rectangle')
        self.assertEqual(rectangle.geometry,{'start':(-1.016,-2.54),'end':(1.016,2.54)})

    def test_legacy_arc_native_angles_and_endpoints_retained(self):
        s=parse_library(legacy('A 0 0 100 900 -900 0 1 10 N 0 100 0 -100')).get_symbol('Test')
        g=s.units[0].graphics[0]
        self.assertEqual(g.kind,'legacy_arc')
        self.assertEqual(g.geometry,dict(center=(0,0),radius=2.54,start_angle=90,
                                        end_angle=-90,start=(0,2.54),end=(0,-2.54)))
        self.assertAlmostEqual(g.width,.254)

    def test_forward_and_multilevel_inheritance_override(self):
        source=library(symbol('C',extends='B',value='child'),
                       symbol('B',extends='Base',value='middle'),
                       symbol(body='(symbol "Base_1_1" '+pin()+')'))
        lib=parse_library(source)
        self.assertEqual(list(lib.symbols),['C','B','Base'])
        self.assertEqual(lib.symbols['C'].inheritance_chain,['B','Base'])
        self.assertEqual(lib.symbols['C'].pins_for()[0].at,(-5.08,0,0))
        self.assertEqual(lib.symbols['C'].properties['Reference'].value,'U')
        self.assertEqual(lib.symbols['Base'].properties['Value'].value,'Base')

    def test_inheritance_missing_cycle_and_geometry_override_rejected(self):
        inputs=[library(symbol('A',extends='Missing')),
                library(symbol('A',extends='B'),symbol('B',extends='A')),
                library(symbol(),symbol('Child',extends='Base',body='(symbol "Child_1_1")')),
                library(symbol('Child',extends=''))]
        for source in inputs:
            with self.subTest(source=source),self.assertRaises(SymbolParseError): parse_library(source)

    def test_common_units_and_body_styles_are_selected(self):
        body=''.join(f'(symbol "Base_{u}_{s}" {pin(n)})' for u,s,n in
                     [(0,0,'P'),(1,1,'A'),(1,2,'B'),(2,1,'C')])
        s=parse_library(library(symbol(body=body))).get_symbol('Base')
        self.assertEqual([p.number for p in s.pins_for(1,1)],['P','A'])
        self.assertEqual([p.number for p in s.pins_for(1,2)],['P','B'])
        self.assertEqual([p.number for p in s.pins_for(2,1)],['P','C'])
        for u,style in [(0,1),(3,1),(1,0)]:
            with self.assertRaises(SymbolParseError): s.pins_for(u,style)

    def test_shared_pin_number_in_separate_views_is_valid(self):
        body=''.join(f'(symbol "Base_{u}_{s}" {pin("8")})' for u,s in [(1,1),(1,2),(2,1)])
        self.assertTrue(parse_library(library(symbol(body=body))).get_symbol('Base').source_ready)

    def test_conflicting_pin_number_in_one_view_is_flagged(self):
        s=parse_library(library(symbol(body='(symbol "Base_0_0" '+pin()+')'
            '(symbol "Base_1_1" '+pin(name='OTHER')+')'))).get_symbol('Base')
        self.assertEqual(s.diagnostics[0].code,'SOURCE_PIN_CONFLICT')
        self.assertEqual(len(s.pins_for()),2)

    def test_pin_alternates_and_hidden(self):
        p=parse_library(library(symbol(body='(symbol "Base_1_1" '+
            pin('A1',extra='(hide yes) (alternate "OUT" output inverted)')+')'))).get_symbol('Base').pins_for()[0]
        self.assertTrue(p.hidden)
        self.assertEqual(p.alternates,[dict(name='OUT',electrical_type='output',graphic_style='inverted')])

    def test_legacy_pin_shape_hidden_and_orientation(self):
        s=parse_library(legacy('X CLK A1 100 -50 150 L 40 50 1 1 T NC')).get_symbol('Test')
        p=s.pins_for()[0]
        self.assertEqual(p.at,(2.54,-1.27,180))
        self.assertEqual(p.graphic_style,'clock')
        self.assertTrue(p.hidden)
        self.assertEqual(p.electrical_type,'tri_state')
        p=parse_library(legacy('X CLK A1 0 0 100 R 40 50 1 1 I ~ICN')).get_symbol('Test').pins_for()[0]
        self.assertEqual(p.graphic_style,'inverted_clock')
        self.assertTrue(p.hidden)

    def test_modern_pin_visibility_offsets_and_properties(self):
        body='(pin_names (offset 1.016) hide) (pin_numbers hide) (in_bom no) (on_board no) (power)'
        body+=prop('Manufacturer','A company')
        s=parse_library(library(symbol(body=body))).get_symbol('Base')
        self.assertTrue(s.pin_names_hidden and s.pin_numbers_hidden and s.power)
        self.assertFalse(s.in_bom or s.on_board)
        self.assertEqual(s.pin_name_offset,1.016)
        self.assertEqual(s.properties['Manufacturer'].value,'A company')

    def test_duplicate_symbol_property_unit_rejected(self):
        cases=[library(symbol(),symbol()), library(symbol(body=prop('Value','duplicate'))),
               library(symbol(body='(symbol "Base_1_1") (symbol "Base_1_1")')),
               library(symbol(body='(symbol "Other_1_1")')),
               library(symbol(body='(symbol "Base_1025_1")'))]
        for source in cases:
            with self.subTest(source=source),self.assertRaises(SymbolParseError): parse_library(source)

    def test_missing_mandatory_properties_rejected(self):
        with self.assertRaisesRegex(SymbolParseError,'mandatory'):
            parse_library(library('(symbol "Broken" '+prop('Value','Broken')+')'))

    def test_invalid_numeric_pin_records_rejected(self):
        for at in ['nan 0 0','0 inf 0','0 0 45','0 0','(bad) 0 0']:
            with self.subTest(at=at),self.assertRaises(SymbolParseError):
                parse_library(library(symbol(body='(symbol "Base_1_1" '+pin(at=at)+')')))
        for record in [pin().replace('(length 2.54)','(length -1)'),
                       pin().replace('(length 2.54)','(length 1) (length 2)'),
                       pin().replace('input line','mystery line'),
                       pin().replace('(number "1"','(number ""')]:
            with self.assertRaises(SymbolParseError):
                parse_library(library(symbol(body='(symbol "Base_1_1" '+record+')')))

    def test_unknown_extensions_preserved_and_not_ready(self):
        src=library(symbol(body='(future_option "retained") (symbol "Base_1_1" '+
                           pin(extra='(future_pin "retained")')+')'))
        lib=parse_library(src)
        report=inspection_report(lib)
        self.assertEqual(report['summary']['diagnostic_occurrences'],{'SOURCE_EXTENSION_UNNORMALIZED':2})
        self.assertIn('future_option',repr(lib.symbols['Base'].raw))
        self.assertIn('future_pin',repr(lib.symbols['Base'].pins_for()[0].raw))
        self.assertFalse(report['symbols']['Base']['source_ready'])

    def test_future_version_and_metadata_diagnostic(self):
        lib=parse_library(library(symbol(),version='20991231',extra='(future "retain")'))
        report=inspection_report(lib)
        self.assertEqual(set(report['summary']['diagnostic_occurrences']),
                         {'SOURCE_VERSION_UNVERIFIED','SOURCE_EXTENSION_UNNORMALIZED'})
        self.assertEqual(report['summary']['source_ready_count'],0)

    def test_graphic_primitives_normalized_without_tessellation(self):
        stroke='(stroke (width 0.254) (type default)) (fill (type background))'
        graphics=[f'(arc (start 1 0) (mid 0 1) (end -1 0) {stroke})',
                  f'(circle (center 1 2) (radius 3) {stroke})',
                  f'(rectangle (start -1 2) (end 1 -2) {stroke})',
                  f'(polyline (pts (xy 0 0) (xy 1 2)) {stroke})',
                  f'(bezier (pts (xy 0 0) (xy 1 2) (xy 2 3) (xy 4 0)) {stroke})',
                  '(text "label" (at 3 4 90) (effects (font (size 1 2))))']
        s=parse_library(library(symbol(body='(symbol "Base_0_1" '+''.join(graphics)+')'))).get_symbol('Base')
        self.assertEqual([g.kind for g in s.units[0].graphics],['arc','circle','rectangle','polyline','bezier','text'])
        self.assertEqual(s.units[0].graphics[0].geometry['mid'],(0,1))
        self.assertEqual(s.units[0].graphics[1].fill,'background')
        self.assertEqual(s.units[0].graphics[-1].geometry['size'],(1,2))

    def test_malformed_graphics_rejected(self):
        stroke='(stroke (width 0) (type default)) (fill (type none))'
        for g in [f'(circle (center 0 0) (radius nan) {stroke})',
                  f'(circle (center 0 0) (radius 0) {stroke})',
                  f'(polyline (pts (xy 0 0)) {stroke})',
                  f'(bezier (pts (xy 0 0) (xy 1 1)) {stroke})']:
            with self.assertRaises(SymbolParseError):
                parse_library(library(symbol(body='(symbol "Base_0_1" '+g+')')))

    def test_legacy_unknown_graphics_retained(self):
        lib=parse_library(legacy('B 0 0 0 50 0 1 1 "label"'))
        self.assertFalse(lib.get_symbol('Test').source_ready)
        self.assertIn('label',repr(lib.get_symbol('Test').raw))

    def test_legacy_alias_conflicts_and_field_duplicates_rejected(self):
        for source in [legacy(extra='ALIAS Test'),legacy(extra='ALIAS Alias Alias'),
                       legacy(fields='F0 "Other" 0 0 50 H V C CNN'),
                       legacy(fields='F4 "A" 0 0 50 H V C CNN "Maker"\nF4 "B" 0 0 50 H V C CNN "Other"')]:
            with self.assertRaises(SymbolParseError): parse_library(source)

    def test_incomplete_or_invalid_legacy_records_rejected(self):
        for source in [legacy().replace('ENDDRAW\n',''),legacy().replace('ENDDEF\n',''),
                       legacy().replace('DRAW\n','DRAW extra\n',1),
                       legacy().replace('2.4','1.0',1),legacy('X IN 1 nan 0 100 R 40 50 1 1 I'),
                       legacy('X IN 1 0 0 100 R 40 50 2 1 I'),legacy('P 2 0 1 0 0 0 N'),
                       legacy('C 0 0 -10 0 1 0 N')]:
            with self.subTest(source=source),self.assertRaises(SymbolParseError): parse_library(source)

    def test_wrong_root_and_broken_sexpr_rejected(self):
        for source in ['(kicad_sch (version 1))','(footprint "part")','(kicad_symbol_lib',
                       library(symbol())+' (extra)','(kicad_symbol_lib (version 1) (symbol))']:
            with self.assertRaises(SymbolParseError): parse_library(source)

    def test_report_keeps_source_separate_from_target_claims(self):
        lib=parse_library(library(symbol(body='(symbol "Base_1_1" '+pin('A1')+')')))
        before=deepcopy(lib)
        report=inspection_report(lib,['Base','Base'])
        self.assertEqual(lib,before)
        self.assertEqual(report['summary']['selected_count'],1)
        self.assertEqual(report['symbols']['Base']['physical_pin_numbers'],['A1'])
        self.assertFalse(report['target_output_generated'] or report['target_format_verified'] or report['gui_validated'])
        self.assertFalse(report['symbols']['Base']['physical_pin_mapping_verified'])
        json.dumps(report,allow_nan=False)
        with self.assertRaises(SymbolParseError): inspection_report(lib,['Missing'])


class SymbolCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)/'source.lib'
        self.output=Path(self.tmp.name)/'report.json'
        self.source.write_text(legacy())

    def run_cli(self,*args):
        return subprocess.run([sys.executable,'-B','-m','src.symbol_converter',str(self.source),
                               str(self.output),*args],cwd=PROJECT,text=True,capture_output=True)

    def test_cli_repeatable_json_and_source_digest(self):
        self.assertEqual(self.run_cli('--symbol','Test').returncode,0)
        first=self.output.read_bytes()
        self.assertEqual(self.run_cli('--symbol','Test').returncode,0)
        self.assertEqual(first,self.output.read_bytes())
        report=json.loads(first)
        self.assertEqual(report['source']['sha256'],hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_diagnostics_write_report_and_exit_two(self):
        self.source.write_text(legacy('X A 1 0 0 100 R 40 50 1 1 I\nX B 1 100 0 100 L 40 50 1 1 O'))
        self.assertEqual(self.run_cli().returncode,2)
        self.assertEqual(json.loads(self.output.read_text())['summary']['diagnostic_occurrences'],
                         {'SOURCE_PIN_CONFLICT':1})

    def test_bad_source_or_selection_preserves_previous_report(self):
        self.output.write_text('previous result')
        self.assertEqual(self.run_cli('--symbol','Missing').returncode,1)
        self.assertEqual(self.output.read_text(),'previous result')
        self.source.write_text('broken')
        self.assertEqual(self.run_cli().returncode,1)
        self.assertEqual(self.output.read_text(),'previous result')

    def test_output_hardlink_and_target_extension_rejected(self):
        os.link(self.source,self.output)
        before=self.source.read_bytes()
        self.assertEqual(self.run_cli().returncode,1)
        self.assertEqual(self.source.read_bytes(),before)
        self.output=Path(self.tmp.name)/'output.fpl'
        self.assertEqual(self.run_cli().returncode,1)
        self.assertFalse(self.output.exists())

    def test_model_storage_output_rejected(self):
        self.output=PROJECT/'stl_files'/'symbol-inspection-must-not-exist.json'
        self.assertEqual(self.run_cli().returncode,1)
        self.assertFalse(self.output.exists())


if __name__=='__main__':
    unittest.main()
