"""CDS contracts checked against a real component and literal terminal probes."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.symbol_converter import SymbolParseError, parse_library
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.schemator_format import parse_cds, CdsDocument, validate_component
from src.symbol_converter.schemator_writer import write_cds
from test_symbol_converter import library, symbol, pin

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures/schemator'
CACHE=PROJECT/'KiCad/Pickit-cache.lib'


def modern(body=None):
    if body is None:
        body=pin('A1').replace('input line','passive line')
    return parse_library(library(symbol(body='(symbol "Base_1_1" '+body+')')))


class SchematorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy=parse_library(CACHE.read_text())

    def test_real_component_fixture_is_exact_source_slice(self):
        provenance=json.loads((FIXTURES/'provenance.json').read_text())
        source=(PROJECT/provenance['source']).read_bytes()
        fixture=(FIXTURES/provenance['fixture']).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),provenance['source_sha256'])
        self.assertEqual(hashlib.sha256(fixture).hexdigest(),provenance['fixture_sha256'])
        self.assertEqual(fixture,b''.join(source.splitlines(keepends=True)[
            provenance['first_line']-1:provenance['last_line']]))

    def test_real_r3_record_has_numbered_electrical_terminals(self):
        doc=parse_cds((FIXTURES/'Detector_R3.component.txt').read_text(encoding='cp1251'),component_fragment=True)
        part=doc.components[0]
        self.assertEqual(part.reference.value,'R3')
        self.assertEqual(part.value.value,'330k')
        self.assertEqual(part.footprint.value,'1X2HDR-100')
        self.assertEqual(part.pin_count,2)
        self.assertEqual(part.bounds,(103474600,101724600,111775400,104275400))
        pins={p.pin.value:p for p in part.polylines if p.pin}
        self.assertEqual(set(pins),{'1','2'})
        self.assertEqual((pins['1'].corners[1].x,pins['1'].corners[1].y),(103750000,103000000))
        self.assertEqual((pins['2'].corners[1].x,pins['2'].corners[1].y),(111500000,103000000))
        self.assertTrue(all(p.layer==8 and [c.node for c in p.corners]==[0,1] for p in pins.values()))
        self.assertEqual(part.reference.options,65)
        self.assertEqual(pins['1'].pin.size,0)

    def test_real_record_semantic_roundtrip_through_independent_reader(self):
        fragment=parse_cds((FIXTURES/'Detector_R3.component.txt').read_text(encoding='cp1251'),component_fragment=True)
        doc=CdsDocument(dict(version='1.429',file_version='1.429',units='MM',project_name='R3.cds'),fragment.components)
        encoded=write_cds(doc)
        self.assertEqual(parse_cds(encoded),doc)
        self.assertEqual(encoded.count('part_end'),1)
        self.assertIn('\r\n',encoded)

    def test_legacy_r_preserves_terminal_identity_and_y_up(self):
        result=convert_symbol(self.legacy,'R',footprint_name='R_0805_2012Metric')
        part=parse_cds(result.cds).components[0]
        pins={p.pin.value:p for p in part.polylines if p.pin}
        self.assertEqual((pins['1'].corners[0].x,pins['1'].corners[0].y),(0,2540000))
        self.assertEqual((pins['1'].corners[1].x,pins['1'].corners[1].y),(0,3810000))
        self.assertEqual((pins['2'].corners[0].x,pins['2'].corners[0].y),(0,-2540000))
        self.assertEqual((pins['2'].corners[1].x,pins['2'].corners[1].y),(0,-3810000))
        self.assertEqual([c.node for c in pins['1'].corners],[0,1])
        self.assertEqual(part.reference.value,'R1')
        self.assertEqual(part.reference.angle,270)
        self.assertEqual((part.reference.x,part.reference.y),(2032000,0))
        self.assertEqual(part.reference.size,1270000)
        self.assertEqual(part.footprint.value,'R_0805_2012Metric')
        self.assertTrue(all(p.pin.size==0 and p.pin.width==0 for p in pins.values()))

    def test_legacy_c_and_connector_native_records(self):
        cap=convert_symbol(self.legacy,'C').document.components[0]
        self.assertEqual((cap.pin_count,len(cap.polylines)),(2,4))
        connector=convert_symbol(self.legacy,'CONN_01X06')
        part=connector.document.components[0]
        pins=[p for p in part.polylines if p.pin]
        self.assertEqual(part.pin_count,6)
        self.assertEqual([(p.corners[1].x,p.corners[1].y) for p in pins],
                         [(-5080000,y) for y in (6350000,3810000,1270000,-1270000,-3810000,-6350000)])
        self.assertTrue(all(p.pin.size>0 for p in pins))
        self.assertEqual(len([p for p in part.polylines if p.closed]),7)
        self.assertEqual(len([d for d in connector.report['diagnostics'] if d['code']=='SOURCE_LINE_WIDTH_DEFAULT']),7)

    def test_all_cardinal_pin_directions_use_free_end_as_source_at(self):
        # Literal external/body points, independent of writer direction table.
        expected={0:((-5080000,0),(-2540000,0)),90:((0,-5080000),(0,-2540000)),
                  180:((5080000,0),(2540000,0)),270:((0,5080000),(0,2540000))}
        for angle,(external,body) in expected.items():
            p=pin(at=f'{external[0]/1e6} {external[1]/1e6} {angle}').replace('input line','passive line')
            poly=convert_symbol(modern(p),'Base').document.components[0].polylines[-1]
            self.assertEqual([(c.x,c.y) for c in poly.corners],[body,external])
            self.assertEqual([c.node for c in poly.corners],[0,1])

    def test_pin_names_attach_as_description_not_physical_number(self):
        part=convert_symbol(modern(),'Base').document.components[0]
        p=part.polylines[-1]
        self.assertEqual((p.pin.value,p.pin.layer),('A1',9))
        self.assertEqual((p.description.value,p.description.layer),('IN',14))

    def test_declared_widths_and_reference_are_applied(self):
        part=convert_symbol(self.legacy,'CONN_01X06',reference='J12',default_line_width=.15,pin_width=.2).document.components[0]
        self.assertEqual(part.reference.value,'J12')
        self.assertTrue(all(p.width==200000 if p.pin else p.width==150000 for p in part.polylines))

    def test_project_header_uses_native_version_and_graphics_grid(self):
        result=convert_symbol(self.legacy,'R',project_name='sample.cds')
        doc=parse_cds(result.cds)
        self.assertEqual(doc.options['version'],'1.429')
        self.assertEqual(doc.options['file_version'],'1.429')
        self.assertEqual(doc.options['units'],'MM')
        self.assertEqual(doc.options['project_name'],'sample.cds')
        self.assertEqual(doc.components[0].pin_count,2)

    def test_symbol_and_mesh_stores_are_not_mutated(self):
        before=deepcopy(self.legacy)
        convert_symbol(self.legacy,'R')
        self.assertEqual(self.legacy,before)

    def test_report_has_explicit_loss_and_unverified_mapping_gui(self):
        result=convert_symbol(self.legacy,'R')
        report=result.report
        self.assertEqual(report['status'],'generated_with_loss')
        self.assertTrue(report['contract_verified_against_source'] and report['target_records_validated'])
        self.assertFalse(report['gui_validated'] or report['target_import_verified'] or report['physical_pin_mapping_verified'])
        self.assertEqual(report['artifact_sha256'],hashlib.sha256(result.cds.encode('cp1251')).hexdigest())
        self.assertIn('SYMBOL_FOOTPRINT_UNRESOLVED',{d['code'] for d in report['diagnostics']})
        self.assertIn('SYMBOL_ELECTRICAL_TYPE_NOT_TRANSFERRED',
                      {entry['code'] for entry in report['diagnostics']})
        self.assertTrue(all(pin['electrical_type'] == 'passive'
                            for unit in report['source_symbol']['units']
                            for pin in unit['pins']))
        self.assertGreater(report['counts']['losses'],0)

    def test_strict_rejects_proposed_output_with_report(self):
        with self.assertRaises(LossySymbolConversionError) as caught:
            convert_symbol(self.legacy,'R',strict=True)
        report=caught.exception.report
        self.assertEqual(report['status'],'rejected_loss')
        self.assertFalse(report['target_output_generated'])
        self.assertNotIn('artifact_sha256',report)
        self.assertIn('proposed_artifact_sha256',report)

    def test_no_automatic_pin_duplicate_removal(self):
        with self.assertRaisesRegex(SymbolParseError,'source diagnostics'):
            convert_symbol(self.legacy,'PIC24FJ256GB106')

    def test_multiunit_body_styles_and_power_are_explicitly_rejected(self):
        lib=parse_library((PROJECT/'tests/fixtures/symbols/Comparator.kicad_sym').read_text())
        with self.assertRaisesRegex(SymbolParseError,'one unit'):
            convert_symbol(lib,'LM393')
        with self.assertRaisesRegex(SymbolParseError,'Power/virtual'):
            convert_symbol(self.legacy,'GND')
        bad=modern();bad.symbols['Base'].units[0].style=2
        with self.assertRaisesRegex(SymbolParseError,'body style'):
            convert_symbol(bad,'Base')

    def test_nonpassive_hidden_shaped_or_alternate_pins_rejected(self):
        for change in [('electrical_type','input'),('hidden',True),('graphic_style','inverted'),
                       ('alternates',[dict(name='ALT',electrical_type='output',graphic_style='line')])]:
            lib=modern();setattr(lib.symbols['Base'].pins_for()[0],*change)
            with self.subTest(change=change),self.assertRaisesRegex(SymbolParseError,'only visible passive'):
                convert_symbol(lib,'Base')

    def test_unsupported_graphics_and_fills_rejected(self):
        for name in ['CP1','INDUCTOR','LED']:
            with self.subTest(name=name),self.assertRaises(SymbolParseError): convert_symbol(self.legacy,name)

    def test_unsafe_index_strings_and_unencodable_text_rejected(self):
        for value in ['"quoted"','trailing ','with\nnewline','A@B','A~B','emoji😀']:
            lib=modern();lib.symbols['Base'].properties['Value'].value=value
            with self.subTest(value=value),self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')
        for footprint in ['','A@B','"unsafe"']:
            with self.assertRaises(SymbolParseError): convert_symbol(self.legacy,'R',footprint_name=footprint)
        for reference in ['R','R0','R01','R1.1','R 1','R2147483648']:
            with self.assertRaises(SymbolParseError): convert_symbol(self.legacy,'R',reference=reference)

    def test_unsupported_pin_number_forms_rejected(self):
        for number in ['01','0','1,2','1-2','1\'2','A','A01','A 1','A2147483648','9'*5000]:
            lib=modern();lib.symbols['Base'].pins_for()[0].number=number
            with self.subTest(number=number),self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')
        lib=modern();lib.symbols['Base'].pins_for()[0].number='A2147483647'
        result=convert_symbol(lib,'Base',reference='R2147483647')
        self.assertEqual(result.document.components[0].reference.value,'R2147483647')
        self.assertIn('A2147483647',{p.pin.value for p in result.document.components[0].polylines if p.pin})

    def test_numeric_ranges_nonfinite_widths_and_grid_collapse_rejected(self):
        for value in [0,-1,math.nan,math.inf,1e308]:
            with self.subTest(value=value),self.assertRaises(SymbolParseError):
                convert_symbol(self.legacy,'R',pin_width=value)
        for at,length in [((3000,0,0),2.54),((0,0,0),1e-9),((math.nan,0,0),2.54)]:
            lib=modern();p=lib.symbols['Base'].pins_for()[0];p.at=at;p.length=length
            with self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')

    def test_source_extensions_future_version_and_empty_pins_block_output(self):
        for lib in [parse_library(library(symbol(),version='20991231')),
                    parse_library(library(symbol(body='(future_feature yes)'))),
                    parse_library(library(symbol()))]:
            with self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')

    def test_coincident_target_terminals_and_duplicate_pin_numbers_rejected(self):
        p=pin('1').replace('input line','passive line')
        for other in [p,p.replace('(number "1"','(number "2"')]:
            lib=modern(p+other)
            with self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')

    def test_independent_reader_detects_topology_corruption(self):
        good=convert_symbol(self.legacy,'R').cds
        edits=[('n_pins: 2','n_pins: 3'),('0 3810000 0 1','0 3810000 0 0'),
               ('pin_name: "1"','pin_name: "2"'),('polyline: 2 0 8','polyline: 2 0 6'),
               ('corner: 2 0 3810000','corner: 3 0 3810000'),('outline: 4','outline: 5'),
               ('version: 1.429','version: 2.428'),('part_end',''),('[end]',''),
               ('pin_name: "1"','unrecognized: "1"')]
        for old,new in edits:
            self.assertIn(old,good)
            with self.subTest(old=old),self.assertRaises(SymbolParseError): parse_cds(good.replace(old,new,1))

    def test_native_component_validator_detects_missing_pin_attribute(self):
        part=deepcopy(convert_symbol(self.legacy,'R').document.components[0])
        part.polylines[-1].pin=None
        with self.assertRaises(SymbolParseError): validate_component(part)

    def test_cp1251_text_roundtrips_without_replacement(self):
        lib=modern();lib.symbols['Base'].properties['Value'].value='Резистор'
        result=convert_symbol(lib,'Base')
        data=result.cds.encode('cp1251')
        self.assertEqual(parse_cds(data.decode('cp1251')).components[0].value.value,'Резистор')

    def test_saved_controls_reproduce(self):
        for name,filename in [('R','R_control.cds'),('C','C_control.cds'),('CONN_01X06','CONN_01X06_control.cds')]:
            result=convert_symbol(self.legacy,name,project_name=filename)
            self.assertEqual(result.cds.encode('cp1251'),(PROJECT/'output/symbols'/filename).read_bytes())


class SchematorCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output=Path(self.tmp.name)/'R.cds'
        self.report=self.output.with_suffix('.report.json')

    def run_cli(self,*args,name='R'):
        return subprocess.run([sys.executable,'-B','-m','src.symbol_converter.write',str(CACHE),
            str(self.output),'--symbol',name,*args],cwd=PROJECT,text=True,capture_output=True)

    def test_cli_writes_cds_and_report_repeatably(self):
        result=self.run_cli('--footprint-name','R_0805_2012Metric')
        self.assertEqual(result.returncode,0,result.stderr)
        first=(self.output.read_bytes(),self.report.read_bytes())
        self.assertEqual(self.run_cli('--footprint-name','R_0805_2012Metric').returncode,0)
        self.assertEqual(first,(self.output.read_bytes(),self.report.read_bytes()))
        report=json.loads(first[1])
        self.assertEqual(report['source']['sha256'],hashlib.sha256(CACHE.read_bytes()).hexdigest())
        self.assertEqual(report['artifact_sha256'],hashlib.sha256(first[0]).hexdigest())

    def test_strict_preserves_old_cds_and_writes_rejection_report(self):
        self.output.write_bytes(b'previous CDS')
        self.assertEqual(self.run_cli('--strict').returncode,2)
        self.assertEqual(self.output.read_bytes(),b'previous CDS')
        report=json.loads(self.report.read_text())
        self.assertEqual(report['status'],'rejected_loss')
        self.assertFalse(report['target_output_generated'])

    def test_invalid_source_selection_preserves_both_previous_outputs(self):
        self.output.write_bytes(b'previous CDS');self.report.write_bytes(b'previous report')
        self.assertEqual(self.run_cli(name='PIC24FJ256GB106').returncode,1)
        self.assertEqual(self.output.read_bytes(),b'previous CDS')
        self.assertEqual(self.report.read_bytes(),b'previous report')

    def test_source_hardlink_and_model_storage_outputs_rejected(self):
        os.link(CACHE,self.output)
        before=CACHE.read_bytes()
        self.assertEqual(self.run_cli().returncode,1)
        self.assertEqual(CACHE.read_bytes(),before)
        self.output=PROJECT/'stl_files'/'must-not-create-symbol.cds'
        self.assertEqual(self.run_cli().returncode,1)
        self.assertFalse(self.output.exists())

    def test_report_cannot_overwrite_source_even_through_hardlink(self):
        report=Path(self.tmp.name)/'source.report.json';os.link(CACHE,report)
        before=CACHE.read_bytes()
        self.assertEqual(self.run_cli('--report',str(report)).returncode,1)
        self.assertFalse(self.output.exists())
        self.assertEqual(CACHE.read_bytes(),before)

    def test_output_extension_and_report_collision_rejected(self):
        self.output=self.output.with_suffix('.CDS')
        self.assertEqual(self.run_cli().returncode,1)
        self.assertFalse(self.output.exists())
        self.output=self.output.with_suffix('.cds')
        self.assertEqual(self.run_cli('--report',str(self.output)).returncode,1)


if __name__=='__main__':
    unittest.main()
