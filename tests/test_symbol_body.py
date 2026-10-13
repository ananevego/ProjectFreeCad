"""Body fill coverage on serialized NM strokes and native text ownership."""
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
from src.symbol_converter.schemator_format import parse_cds, validate_component
from src.component_converter import export_bundle, verify_bundle
from test_symbol_converter import library, symbol, pin, legacy

PROJECT=Path(__file__).resolve().parents[1]
FIXTURES=PROJECT/'tests/fixtures'
CONTROLS=('D_Filled','C_Polarized','Antenna_Shield','C_Network04','Ammeter_DC','FrequencyCounter')


def modern(graphics):
    pins=pin('1',name='~')+pin('2',name='~',at='5.08 0 180')
    return parse_library(library(symbol(body='(symbol "Base_1_1" '+graphics+pins.replace('input line','passive line')+')')))


def rectangle(fill='outline',width=.0001,start='-1 -1',end='1 1'):
    return f'(rectangle (start {start}) (end {end}) (stroke (width {width}) (type default)) (fill (type {fill})))'


def circle(fill='outline',width=.0001,center='0 0',radius=1):
    return f'(circle (center {center}) (radius {radius}) (stroke (width {width}) (type default)) (fill (type {fill})))'


def polygon(points,fill='outline'):
    pts=' '.join(f'(xy {x} {y})' for x,y in points)
    return f'(polyline (pts {pts}) (stroke (width 0.0001) (type default)) (fill (type {fill})))'


def text(value='A',at='0 0 0',effects=''):
    return f'(text "{value}" (at {at}) (effects (font (size 1 1)) {effects}))'


def segment_distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)


def edges(result,fill_index=0):
    native=parse_cds(result.cds).components[0]
    for i in result.report['filled_graphics'][fill_index]['target_polyline_indices']:
        poly=native.polylines[i]
        points=[(p.x/1e6,p.y/1e6) for p in poly.corners]
        if poly.closed:points.append(points[0])
        for a,b in zip(points,points[1:]):yield a,b,poly.width/2e6


def covered(point,strokes):
    return any(segment_distance(point,a,b)<=radius+1e-9 for a,b,radius in strokes)


class SymbolBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=parse_library((FIXTURES/'symbols/Device.kicad_sym').read_text())

    def test_filled_rectangle_interior_and_rounded_caps_obey_bound(self):
        result=convert_symbol(modern(rectangle()),'Base')
        strokes=list(edges(result));tol=.01
        for ix in range(31):
            for iy in range(31):
                self.assertTrue(covered((-1+ix/15,-1+iy/15),strokes))
        for a,b,r in strokes:
            for x,y in (a,b,((a[0]+b[0])/2,(a[1]+b[1])/2)):
                for i in range(12):
                    px,py=x+r*math.cos(i*math.tau/12),y+r*math.sin(i*math.tau/12)
                    outside=math.hypot(max(0,abs(px)-1),max(0,abs(py)-1))
                    self.assertLessEqual(outside,.0001/2+tol+1e-8)

    def test_filled_circle_covers_disk_and_has_bounded_radial_expansion(self):
        result=convert_symbol(modern(circle(center='2.125 -3.875')),'Base')
        strokes=list(edges(result));center=(2.125,-3.875)
        for i in range(90):
            for radius in (0,.1,.5,.9,.99,1):
                angle=i*math.tau/90
                self.assertTrue(covered((center[0]+radius*math.cos(angle),center[1]+radius*math.sin(angle)),strokes))
        for a,b,r in strokes:
            self.assertLessEqual(max(math.dist(a,center),math.dist(b,center))+r,1+.0001/2+.01+1e-8)
        fill=result.report['filled_graphics'][0]
        self.assertEqual(fill['center_mm'],center)
        self.assertTrue(fill['nominal_interior_covered'])

    def test_concave_polygon_covers_arms_and_does_not_fill_notch(self):
        pts=[(-1,-1),(1,-1),(1,0),(0,0),(0,1),(-1,1),(-1,-1)]
        result=convert_symbol(modern(polygon(pts)),'Base');strokes=list(edges(result))
        for x in (-.9,-.5,-.1,.1,.5,.9):
            for y in (-.9,-.5,-.1,.1,.5,.9):
                if x<=0 or y<=0:self.assertTrue(covered((x,y),strokes))
        self.assertFalse(covered((.5,.5),strokes))

    def test_background_rectangle_preserves_only_boundary_with_loss(self):
        result=convert_symbol(modern(rectangle('background')),'Base')
        fill=result.report['filled_graphics'][0]
        self.assertEqual(fill['native_policy'],'boundary_only')
        self.assertFalse(fill['background_occlusion_transferred'])
        self.assertEqual(len(fill['target_polyline_indices']),1)
        self.assertFalse(covered((0,0),list(edges(result))))
        diagnostic=next(d for d in result.report['diagnostics'] if d['code']=='SYMBOL_BACKGROUND_FILL_NOT_TRANSFERRED')
        self.assertEqual(diagnostic['severity'],'loss')

    def test_background_circle_has_bounded_boundary_and_no_fill_strokes(self):
        result=convert_symbol(modern(circle('background')),'Base')
        fill=result.report['filled_graphics'][0]
        self.assertEqual(fill['boundary_centerline_error_mm'],.01)
        self.assertFalse(covered((0,0),list(edges(result))))
        for a,b,_ in edges(result):
            self.assertLessEqual(abs(segment_distance((0,0),a,b)-1),.01+1e-8)

    def test_fill_metadata_and_pin_nodes_match_serialized_records(self):
        result=convert_symbol(modern(rectangle()),'Base');native=parse_cds(result.cds).components[0]
        fill=result.report['filled_graphics'][0]
        for i in fill['target_polyline_indices']:
            poly=native.polylines[i]
            self.assertEqual((poly.layer,poly.hatch),(6,0))
            self.assertTrue(all(c.style==c.node==0 for c in poly.corners))
            self.assertIsNone(poly.pin)
        pins=[p for p in native.polylines if p.pin]
        self.assertEqual([(p.pin.value,p.corners[-1].x,p.corners[-1].y,p.corners[-1].node) for p in pins],
                         [('1',-5080000,0,1),('2',5080000,0,1)])
        self.assertEqual(fill['emitted_polylines'],len(fill['target_polyline_indices']))
        self.assertEqual(result.report['counts']['losses'],sum(d['severity']=='loss' for d in result.report['diagnostics']))
        self.assertEqual(result.report['counts']['assumptions'],sum(d['severity']=='assumption' for d in result.report['diagnostics']))

    def test_fill_validation_refuses_open_crossed_collapsed_and_touching_contours(self):
        shapes=[[(0,0),(1,0),(0,1)],[(0,0),(1,1),(0,1),(1,0),(0,0)],
                [(0,0),(1,0),(1,0),(0,1),(0,0)],[(0,0),(1,0),(2,0),(0,0)]]
        for fill in ('outline','background'):
            for pts in shapes:
                with self.subTest(fill=fill,pts=pts),self.assertRaises(SymbolParseError):
                    convert_symbol(modern(polygon(pts,fill)),'Base')

    def test_filled_arcs_and_bezier_remain_explicit_refusals(self):
        for shape in ['(arc (start 1 0) (mid 0 1) (end -1 0)',
                      '(bezier (pts (xy 0 0) (xy 1 0) (xy 1 1) (xy 0 1))']:
            graphic=shape+' (stroke (width 0.1) (type default)) (fill (type outline)))'
            with self.assertRaises(SymbolParseError):convert_symbol(modern(graphic),'Base')

    def test_fill_tolerance_and_aggregate_geometry_limits_refuse_partial_generation(self):
        for value in (0,.00002,1.1,float('nan'),True,'0.01'):
            with self.subTest(value=value),self.assertRaises(SymbolParseError):
                convert_symbol(modern(rectangle()),'Base',fill_tolerance=value)
        with patch('src.symbol_converter.target.MAX_SYMBOL_FILL_STROKES',300):
            with self.assertRaisesRegex(SymbolParseError,'4096 emitted'):
                convert_symbol(modern(rectangle()+rectangle()),'Base')
        with patch('src.symbol_converter.target.MAX_BODY_CORNERS',10):
            with self.assertRaisesRegex(SymbolParseError,'native corners'):
                convert_symbol(modern(rectangle()),'Base')

    def test_body_text_attaches_to_outline_without_adding_a_pin(self):
        result=convert_symbol(modern(rectangle('none')+text('Hz',at='0 0 90')),'Base')
        native=parse_cds(result.cds).components[0];owner=result.report['graphic_texts'][0]['target_polyline_index']
        body=native.polylines[owner]
        self.assertIsNone(body.pin)
        self.assertEqual((body.layer,body.description.layer),(6,14))
        self.assertEqual((body.description.value,body.description.angle,body.description.size),('Hz',270,1000000))
        self.assertEqual(native.pin_count,2)
        self.assertEqual(result.report['target']['source_body_profile'],'bounded-fills-body-text-v1')

    def test_text_source_anchor_y_and_quarter_turn_sign_are_preserved(self):
        for angle,native in ((0,0),(90,270),(180,180),(270,90)):
            result=convert_symbol(modern(rectangle('none')+text(at=f'1.125 -2.75 {angle}')),'Base')
            t=result.document.components[0].polylines[0].description
            self.assertEqual((t.x,t.y,t.angle),(1125000,-2750000,native))
        with self.assertRaisesRegex(SymbolParseError,'quarter-turn'):
            convert_symbol(modern(rectangle('none')+text(at='0 0 45')),'Base')

    def test_hidden_styled_text_preserves_literal_and_source_metadata(self):
        graphic=text('R').replace('(size 1 1)','(size 1 1) (thickness 0.15) bold italic')
        graphic=graphic.replace('(effects (font','(effects hide (justify right top) (font')
        source=modern(rectangle('none')+graphic)
        source.symbols['Base'].pin_numbers_hidden=True
        source.symbols['Base'].pin_names_hidden=True
        before=deepcopy(source)
        result=convert_symbol(source,'Base');t=result.document.components[0].polylines[0].description
        self.assertEqual((t.value,t.size,t.width),('R',0,0))
        self.assertTrue(result.report['graphic_texts'][0]['hidden'])
        self.assertFalse(result.report['graphic_texts'][0]['font_layout_transferred'])
        self.assertNotIn('SYMBOL_PIN_LABEL_LAYOUT',{d['code'] for d in result.report['diagnostics']})
        self.assertEqual(source,before)

    def test_body_text_refuses_native_command_markup_variables_and_unencodable_strings(self):
        for value in ("it's",'A|B','A`B','~A~','^A','${VALUE}','A BLK','A BOM','PATH','DATE','ZONE','A PrintableArea','emoji😀'):
            with self.subTest(value=value),self.assertRaises(SymbolParseError):
                convert_symbol(modern(rectangle('none')+text(value)),'Base')

    def test_text_effect_and_scale_errors_are_clear_refusals(self):
        for graphic in (text().replace('(size 1 1)','(size 1e308 1e308)'),
                        text().replace('(size 1 1)','(size 1 1) (thickness -1)'),
                        text(effects='(future_option yes)')):
            with self.assertRaises(SymbolParseError):
                convert_symbol(modern(rectangle('none')+graphic),'Base')

    def test_body_text_needs_distinct_existing_body_carriers(self):
        for graphics in (text(),rectangle('none')+text('A')+text('B')):
            with self.assertRaisesRegex(SymbolParseError,'carrier'):
                convert_symbol(modern(graphics),'Base')
        result=convert_symbol(modern(rectangle('none')+circle('none')+text('A')+text('B')),'Base')
        self.assertEqual(len({t['target_polyline_index'] for t in result.report['graphic_texts']}),2)

    def test_body_text_on_fill_does_not_change_fill_geometry_or_endpoint_count(self):
        source=modern(rectangle());before=convert_symbol(source,'Base')
        after=convert_symbol(modern(rectangle()+text()),'Base')
        self.assertEqual([p.corners for p in before.document.components[0].polylines],
                         [p.corners for p in after.document.components[0].polylines])
        self.assertEqual(after.document.components[0].pin_count,2)
        self.assertEqual(after.report['graphic_texts'][0]['target_polyline_index'],0)

    def test_native_body_description_roundtrip_refuses_orphan_layer_and_control_text(self):
        result=convert_symbol(modern(rectangle('none')+text()),'Base')
        self.assertEqual(parse_cds(result.cds),result.document)
        for change in ('layer','control'):
            doc=deepcopy(result.document);body=doc.components[0].polylines[0]
            if change=='layer':body.description.layer=9
            else:body.description.value='A BLK'
            with self.assertRaises(SymbolParseError):validate_component(doc.components[0])
        bad=result.cds.replace('description: "A"','description: "A|B"')
        with self.assertRaises(SymbolParseError):parse_cds(bad)

    def test_legacy_T_normalizes_size_angle_visibility_styles_and_tilde_spaces(self):
        source=parse_library(legacy('S -100 -100 100 100 1 1 10 N\nT 900 50 -75 40 0 1 1 hello~world Italic 1 L T\nX IN 1 -200 0 100 R 40 50 1 1 I'))
        graphic=next(g for u in source.get_symbol('Test').units for g in u.graphics if g.kind=='text')
        self.assertEqual(graphic.geometry['text'],'hello world')
        self.assertEqual(graphic.geometry['at'],(1.27,-1.905,90))
        self.assertTrue(graphic.geometry['italic'] and graphic.geometry['bold'])
        t=convert_symbol(source,'Test').document.components[0].polylines[0].description
        self.assertEqual((t.value,t.x,t.y,t.angle,t.size),('hello world',1270000,-1905000,270,1016000))
        source=parse_library(legacy('T 0 0 0 50 1 1 1 "hidden label"'))
        self.assertTrue(source.get_symbol('Test').units[0].graphics[0].geometry['hidden'])

    def test_legacy_quoted_tilde_and_invalid_T_fields_are_preserved_or_rejected(self):
        source=parse_library(legacy('T 0 0 0 50 0 1 1 "~A~"'))
        self.assertEqual(source.get_symbol('Test').units[0].graphics[0].geometry['text'],'~A~')
        for record in ('T 0 0 0 0 0 1 1 A','T 0.5 0 0 50 0 1 1 A',
                       'T 0 0 0 50 0 1 1 A Mystery 0','T 0 0 0 50 0 1 1 A Normal 0 Z C'):
            with self.assertRaises(SymbolParseError):parse_library(legacy(record))

    def test_legacy_filled_rectangle_and_circle_use_same_native_Y_up_profile(self):
        source=parse_library(legacy('S -40 -40 40 40 1 1 1 F\nC 0 200 40 1 1 1 F\nX IN 1 -200 0 100 R 40 50 1 1 I'))
        result=convert_symbol(source,'Test')
        self.assertEqual(len(result.report['filled_graphics']),2)
        self.assertEqual(result.report['filled_graphics'][1]['center_mm'],(0,5.08))
        self.assertEqual(result.report['filled_graphics'][1]['source_kind'],'circle')

    def test_real_controls_fill_modes_text_and_functions_are_preserved_in_source(self):
        for name in CONTROLS:
            before=deepcopy(self.device.get_symbol(name));result=convert_symbol(self.device,name)
            self.assertEqual(self.device.get_symbol(name),before)
            self.assertFalse(result.report['gui_validated'] or result.report['target_import_verified'])
            self.assertEqual(result.document.components[0].pin_count,len(before.pins_for()))
        network=convert_symbol(self.device,'C_Network04')
        self.assertEqual([f['source_fill'] for f in network.report['filled_graphics']],['background','outline','outline','outline'])
        for name,value in [('Ammeter_DC','A'),('FrequencyCounter','Hz')]:
            result=convert_symbol(self.device,name)
            self.assertEqual(result.report['graphic_texts'][0]['source_text'],value)
            self.assertTrue(any(p.description and not p.pin for p in result.document.components[0].polylines))

    def test_strict_preserves_new_fill_text_and_background_rejection_metadata(self):
        for name in ('D_Filled','Ammeter_DC','C_Network04'):
            with self.assertRaises(LossySymbolConversionError) as raised:convert_symbol(self.device,name,strict=True)
            self.assertFalse(raised.exception.report['target_output_generated'])
            self.assertEqual(raised.exception.report['target']['source_body_profile'],'bounded-fills-body-text-v1')
            self.assertNotIn('artifact_sha256',raised.exception.report)

    def test_old_native_controls_remain_byte_and_report_identical(self):
        for stem,name in [('R_control','R'),('C_control','C'),('CONN_01X06_control','CONN_01X06'),
                          ('L_curves','L'),('Antenna_electrical','Antenna')]:
            path=PROJECT/'output/symbols'/(stem+'.cds')
            lib=parse_library((PROJECT/'KiCad/Pickit-cache.lib').read_text()) if stem.endswith('control') else self.device
            result=convert_symbol(lib,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes())
            old=json.loads(path.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(result.report)),{k:v for k,v in old.items() if k not in ('source','output')})

    def test_new_official_pinheader_and_saved_body_controls_are_reproducible(self):
        provenance=json.loads((FIXTURES/'components/body-provenance.json').read_text())
        for record in provenance['files']:
            data=(FIXTURES/record['file']).read_bytes()
            self.assertEqual(len(data),record['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
        for name in CONTROLS:
            path=PROJECT/'output/symbols'/(name+'_body.cds')
            result=convert_symbol(self.device,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes())
            report=json.loads(path.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(result.report)),{k:v for k,v in report.items() if k not in ('source','output')})

    def test_body_bundle_verifies_number_identity_after_relocation_with_fill_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store'
            for category,name in [('Diode_SMD','D_SOD-123'),('Connector_PinHeader_2.54mm','PinHeader_1x02_P2.54mm_Vertical')]:
                file=models/(category+'.3dshapes')/(name+'.stl');file.parent.mkdir(parents=True)
                file.write_bytes(b'opaque existing model bytes')
            out=root/'bundle';manifest=export_bundle(FIXTURES/'components/body.json',out,stl_root=models)
            self.assertEqual(manifest['summary']['complete_chains'],2)
            self.assertEqual(manifest['settings']['symbol_fill_tolerance_mm'],.01)
            for e in manifest['components']:
                report=json.loads((out/e['report']).read_text())['symbol_conversion']
                self.assertTrue(report['physical_pin_mapping_verified'])
                self.assertFalse(report['gui_validated'] or report['target_import_verified'])
                self.assertTrue(report.get('filled_graphics') or report.get('graphic_texts'))
            moved=root/'moved';shutil.copytree(out,moved);shutil.rmtree(models);shutil.rmtree(out)
            self.assertEqual(verify_bundle(moved),manifest)

    def test_invalid_bundle_fill_tolerance_is_rejected_before_publication(self):
        config=json.loads((FIXTURES/'components/body.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';out=Path(directory)/'bundle'
            for value in (0,.00002,2,True):
                config['symbol_fill_tolerance']=value;path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):export_bundle(path,out)
                self.assertFalse(out.exists())

    def test_cli_fill_setting_strict_and_error_preserve_previous_cds(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'body.cds'
            cmd=[sys.executable,'-B','-m','src.symbol_converter.write',str(FIXTURES/'symbols/Device.kicad_sym'),str(out),'--symbol','D_Filled','--fill-tolerance','0.005']
            result=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);before=out.read_bytes()
            self.assertEqual(json.loads(out.with_suffix('.report.json').read_text())['conversion_settings']['fill_tolerance_mm'],.005)
            result=subprocess.run(cmd+['--strict'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr);self.assertEqual(out.read_bytes(),before)
            result=subprocess.run(cmd+['--fill-tolerance','nan'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stderr);self.assertEqual(out.read_bytes(),before)


if __name__=='__main__':unittest.main()
